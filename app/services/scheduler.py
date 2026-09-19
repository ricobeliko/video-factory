import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger

from app.models import const
from app.utils import utils

# Centralized default limits and intervals
DEFAULT_TIKTOK_LIMIT = 15
DEFAULT_YOUTUBE_LIMIT = 10
DEFAULT_DESIRED_STOCK = 30
DEFAULT_SCHEDULER_ENABLED = False

STATUS_PLANNED = "planned"
STATUS_READY = "ready"
STATUS_PROCESSING = "processing"
STATUS_PUBLISHED = "published"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

ACTIVE_SCHEDULE_STATUSES = (STATUS_PLANNED, STATUS_READY)

_FINAL_VIDEO_PATTERN = re.compile(r"^final-(?P<index>\d+)\.mp4$")


from contextlib import contextmanager


def get_db_path(custom_path: Optional[str] = None) -> str:
    """Retorna o caminho do banco SQLite do scheduler."""
    if custom_path:
        return custom_path
    storage_folder = utils.storage_dir(create=True)
    return os.path.join(storage_folder, "video_factory.db")


@contextmanager
def get_connection(db_path: Optional[str] = None):
    """Abre conexão com o banco SQLite e garante commit e fechamento no Windows."""
    path = get_db_path(db_path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        with conn:
            yield conn
    finally:
        conn.close()


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Executa migrações incrementais de forma não destrutiva e idempotente."""
    cursor = conn.execute("PRAGMA table_info(scheduled_posts);")
    existing_cols = {row["name"] for row in cursor.fetchall()}
    if "attempts" not in existing_cols:
        conn.execute("ALTER TABLE scheduled_posts ADD COLUMN attempts INTEGER DEFAULT 0;")
    if "last_error" not in existing_cols:
        conn.execute("ALTER TABLE scheduled_posts ADD COLUMN last_error TEXT;")
    if "next_attempt_at" not in existing_cols:
        conn.execute("ALTER TABLE scheduled_posts ADD COLUMN next_attempt_at TEXT;")
    if "profile_id" not in existing_cols:
        conn.execute("ALTER TABLE scheduled_posts ADD COLUMN profile_id TEXT;")
    if "channel_id" not in existing_cols:
        conn.execute("ALTER TABLE scheduled_posts ADD COLUMN channel_id TEXT;")

    cursor_pub = conn.execute("PRAGMA table_info(publication_events);")
    existing_pub_cols = {row["name"] for row in cursor_pub.fetchall()}
    if "provider_request_id" not in existing_pub_cols:
        conn.execute("ALTER TABLE publication_events ADD COLUMN provider_request_id TEXT;")
    if "profile_id" not in existing_pub_cols:
        conn.execute("ALTER TABLE publication_events ADD COLUMN profile_id TEXT;")
    if "channel_id" not in existing_pub_cols:
        conn.execute("ALTER TABLE publication_events ADD COLUMN channel_id TEXT;")
    if "external_url" not in existing_pub_cols:
        conn.execute("ALTER TABLE publication_events ADD COLUMN external_url TEXT;")

    # Idempotência aprimorada por task_id + channel_id + platform
    conn.execute("DROP INDEX IF EXISTS idx_active_schedule;")
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_active_schedule_v2
        ON scheduled_posts(task_id, COALESCE(channel_id, ''), platform)
        WHERE status IN ('planned', 'ready', 'published');
        """
    )


def init_db(db_path: Optional[str] = None) -> None:
    """Inicializa o schema do banco SQLite de forma idempotente."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()

        # 1. Tabela de agendamentos futuros e status
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS scheduled_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                scheduled_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'planned',
                created_at TEXT NOT NULL,
                profile_id TEXT,
                channel_id TEXT,
                attempts INTEGER DEFAULT 0,
                last_error TEXT,
                next_attempt_at TEXT
            );
            """
        )

        # 2. Histórico de publicações reais
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS publication_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                published_at TEXT NOT NULL,
                status TEXT NOT NULL,
                external_id TEXT,
                error_code TEXT,
                provider_request_id TEXT,
                profile_id TEXT,
                channel_id TEXT,
                external_url TEXT
            );
            """
        )

        # 3. Configurações persistentes do Autopilot / Scheduler
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS autopilot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )

        # 4. Mapeamento persistente de destinos (task_id -> platforms)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS task_platforms (
                task_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                PRIMARY KEY (task_id, platform)
            );
            """
        )

        _run_migrations(conn)

    try:
        from app.services import safety_gate
        safety_gate.init_safety_db(db_path)
    except Exception as exc:
        logger.warning(f"[SCHEDULER] Falha ao inicializar safety_gate db: {exc}")


# ---------------------------------------------------------------------------
# Configurações do Autopilot
# ---------------------------------------------------------------------------

def get_setting(key: str, default: Any = None, db_path: Optional[str] = None) -> Any:
    """Lê uma configuração persistida."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM autopilot_settings WHERE key = ?;", (key,)
        ).fetchone()
        if row is not None:
            return row["value"]
        return default


def set_setting(key: str, value: Any, db_path: Optional[str] = None) -> None:
    """Salva uma configuração persistente."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO autopilot_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value;
            """,
            (key, str(value)),
        )


def get_growth_mode(platform: Optional[str] = None, db_path: Optional[str] = None) -> str:
    """Retorna o modo de crescimento configurado (global ou por plataforma).

    Default para conta nova: WARMUP ('warmup').
    """
    if platform:
        clean_plat = platform.lower().strip()
        plat_val = get_setting(f"growth_mode_{clean_plat}", None, db_path)
        if plat_val and str(plat_val).lower().strip() in const.GROWTH_MODES:
            return str(plat_val).lower().strip()

    val = get_setting("growth_mode", const.DEFAULT_GROWTH_MODE, db_path)
    if val and str(val).lower().strip() in const.GROWTH_MODES:
        return str(val).lower().strip()
    return const.DEFAULT_GROWTH_MODE


def set_growth_mode(mode: str, platform: Optional[str] = None, db_path: Optional[str] = None) -> None:
    """Define e persiste o modo de crescimento (global ou por plataforma)."""
    clean_mode = str(mode).lower().strip()
    if clean_mode not in const.GROWTH_MODES:
        raise ValueError(f"Modo de crescimento inválido: '{mode}'. Opções: {const.GROWTH_MODES}")

    if platform:
        clean_plat = platform.lower().strip()
        set_setting(f"growth_mode_{clean_plat}", clean_mode, db_path)
    else:
        set_setting("growth_mode", clean_mode, db_path)

    try:
        replan_future_schedule_for_growth_mode(db_path=db_path)
    except Exception as exc:
        logger.warning(f"[SCHEDULER] Falha ao replanejar após alterar growth_mode: {exc}")


def get_growth_mode_info(platform: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Retorna informações operacionais completas do modo de crescimento para a plataforma."""
    mode = get_growth_mode(platform, db_path)
    clean_plat = platform.lower().strip()
    limits_map = const.GROWTH_MODE_LIMITS.get(mode, const.GROWTH_MODE_LIMITS[const.DEFAULT_GROWTH_MODE])
    return {
        "platform": clean_plat,
        "growth_mode": mode,
        "max_posts_24h": limits_map.get(clean_plat),
        "min_interval_hours": limits_map.get("min_interval_hours", 0),
    }


def get_effective_limit(
    platform: str,
    technical_limit: int,
    mode: Optional[str] = None,
    db_path: Optional[str] = None,
) -> int:
    """Calcula o limite efetivo de publicações para a plataforma.

    Regra Central: O menor limite sempre prevalece entre o teto técnico
    do Scheduler e o limite operacional do modo de crescimento ativo.
    """
    if mode is None:
        mode = get_growth_mode(platform, db_path)
    else:
        mode = str(mode).lower().strip()
        if mode not in const.GROWTH_MODES:
            mode = const.DEFAULT_GROWTH_MODE

    clean_plat = platform.lower().strip()
    limits_map = const.GROWTH_MODE_LIMITS.get(mode, {})
    mode_limit = limits_map.get(clean_plat)
    if mode_limit is None:
        return technical_limit
    return min(technical_limit, mode_limit)


def replan_future_schedule_for_growth_mode(
    db_path: Optional[str] = None,
    now: Optional[datetime] = None,
) -> int:
    """Replaneja com segurança os posts futuros agendados para respeitar o modo atual.

    Regra: Posts futuros que excederem o limite ou violarem o intervalo mínimo
    NUNCA são apagados nem marcados como failed; são reorganizados cronologicamente.
    """
    init_db(db_path)
    current_time = _normalize_utc(now)
    total_adjusted = 0

    for platform in ("tiktok", "youtube"):
        rate_info = get_platform_rate_limits(platform, db_path, now=current_time)
        min_interval_seconds = rate_info.get("min_interval_hours", 0) * 3600
        effective_limit = rate_info.get("effective_limit", rate_info.get("limit", 1))
        uniform_interval_seconds = max(60, int(86400 / max(1, effective_limit)))
        step_seconds = max(min_interval_seconds, uniform_interval_seconds)

        # Última publicação real
        with get_connection(db_path) as conn:
            last_pub_row = conn.execute(
                """
                SELECT MAX(published_at) AS max_pub FROM publication_events
                WHERE platform = ? AND status = 'success';
                """,
                (platform,),
            ).fetchone()

        last_ref_dt = current_time
        if last_pub_row and last_pub_row["max_pub"]:
            try:
                p_dt = _from_iso(last_pub_row["max_pub"])
                last_ref_dt = max(last_ref_dt, p_dt + timedelta(seconds=min_interval_seconds))
            except Exception:
                pass

        # Posts futuros em ordem cronológica
        with get_connection(db_path) as conn:
            posts = conn.execute(
                """
                SELECT id, scheduled_at FROM scheduled_posts
                WHERE platform = ? AND status IN ('planned', 'ready')
                ORDER BY scheduled_at ASC;
                """,
                (platform,),
            ).fetchall()

        if not posts:
            continue

        next_slot = last_ref_dt
        for p in posts:
            post_id = p["id"]
            current_sched = _from_iso(p["scheduled_at"])
            target_slot = max(current_sched, next_slot)
            if target_slot != current_sched:
                iso_target = _to_iso(target_slot)
                with get_connection(db_path) as conn:
                    conn.execute(
                        """
                        UPDATE scheduled_posts
                        SET scheduled_at = ?, next_attempt_at = ?
                        WHERE id = ?;
                        """,
                        (iso_target, iso_target, post_id),
                    )
                total_adjusted += 1
            next_slot = target_slot + timedelta(seconds=step_seconds)

    return total_adjusted


def get_all_settings(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Retorna todas as configurações com seus devidos tipos e defaults."""
    init_db(db_path)
    growth_mode = get_growth_mode(db_path=db_path)
    return {
        "tiktok_enabled": get_setting("tiktok_enabled", "true", db_path).lower() == "true",
        "tiktok_limit_24h": int(get_setting("tiktok_limit_24h", str(DEFAULT_TIKTOK_LIMIT), db_path)),
        "youtube_enabled": get_setting("youtube_enabled", "true", db_path).lower() == "true",
        "youtube_limit_24h": int(get_setting("youtube_limit_24h", str(DEFAULT_YOUTUBE_LIMIT), db_path)),
        "estoque_desejado": int(get_setting("estoque_desejado", str(DEFAULT_DESIRED_STOCK), db_path)),
        "scheduler_enabled": get_setting("scheduler_enabled", "false", db_path).lower() == "true",
        "auto_publish_enabled": get_setting("auto_publish_enabled", "false", db_path).lower() == "true",
        "dry_run": get_setting("dry_run", "true", db_path).lower() == "true",
        "growth_mode": growth_mode,
        "growth_mode_youtube": get_growth_mode("youtube", db_path=db_path),
        "growth_mode_tiktok": get_growth_mode("tiktok", db_path=db_path),
    }


def save_settings(settings: Dict[str, Any], db_path: Optional[str] = None) -> None:
    """Atualiza múltiplas configurações."""
    init_db(db_path)
    mode_changed = False
    with get_connection(db_path) as conn:
        for k, v in settings.items():
            if k == "growth_mode":
                current_mode = get_growth_mode(db_path=db_path)
                if current_mode != str(v).lower().strip():
                    mode_changed = True
            conn.execute(
                """
                INSERT INTO autopilot_settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value;
                """,
                (k, str(v)),
            )
    if mode_changed:
        try:
            replan_future_schedule_for_growth_mode(db_path=db_path)
        except Exception as exc:
            logger.warning(f"Erro ao replanejar agenda após alteração de growth_mode: {exc}")


# ---------------------------------------------------------------------------
# Persistência de Destinos (task_platforms)
# ---------------------------------------------------------------------------

def save_task_platforms(task_id: str, platforms: List[str], db_path: Optional[str] = None) -> None:
    """Salva a relação task_id -> platforms de forma persistente."""
    if not task_id or not platforms:
        return
    init_db(db_path)
    with get_connection(db_path) as conn:
        for p in platforms:
            clean_p = p.strip().lower()
            if clean_p:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO task_platforms (task_id, platform)
                    VALUES (?, ?);
                    """,
                    (task_id, clean_p),
                )


def get_task_platforms(task_id: str, db_path: Optional[str] = None) -> List[str]:
    """Retorna a lista de plataformas configuradas para a task."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT platform FROM task_platforms WHERE task_id = ? ORDER BY platform ASC;",
            (task_id,),
        ).fetchall()
        return [r["platform"] for r in rows]


def get_all_task_platforms(db_path: Optional[str] = None) -> Dict[str, List[str]]:
    """Carrega todo o mapeamento persistente de destinos das tasks."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT task_id, platform FROM task_platforms;").fetchall()
        result: Dict[str, List[str]] = {}
        for r in rows:
            result.setdefault(r["task_id"], []).append(r["platform"])
        return result


def get_adoptable_tasks(
    tasks: List[Dict[str, Any]],
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Identifica tarefas concluídas com vídeo final existente e ainda sem destino persistido.

    Critérios:
    - task_id presente
    - state == const.TASK_STATE_COMPLETE
    - vídeo final existente em disco (os.path.isfile)
    - não publicado (cross_post_state != complete e sem publicação com sucesso)
    - sem plataformas associadas (não presente em task_platforms e sem planned_platforms)
    - descarta PROCESSING, PENDING, FAILED
    """
    init_db(db_path)
    persisted_platforms_map = get_all_task_platforms(db_path)

    # Busca tarefas já publicadas no banco
    published_task_ids = set()
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT task_id FROM publication_events WHERE status = 'success';"
        ).fetchall()
        for r in rows:
            published_task_ids.add(r["task_id"])

        pub_sched = conn.execute(
            "SELECT DISTINCT task_id FROM scheduled_posts WHERE status = 'published';"
        ).fetchall()
        for r in pub_sched:
            published_task_ids.add(r["task_id"])

    adoptable = []
    for t in tasks:
        task_id = t.get("task_id", "")
        if not task_id:
            continue

        state = t.get("state")
        cross_post_state = t.get("cross_post_state")
        video_file = t.get("video_file", "")

        # Ignora estados não concluídos
        if state in (const.TASK_STATE_PROCESSING, const.TASK_STATE_PENDING, const.TASK_STATE_FAILED):
            continue

        # Ignora se não estiver COMPLETE
        if state != const.TASK_STATE_COMPLETE:
            continue

        # Ignora se vídeo não existir no disco
        if not (video_file and os.path.isfile(video_file)):
            continue

        # Ignora se já estiver publicado (MoneyPrinterTurbo cross_post ou scheduler DB)
        if cross_post_state == const.CROSS_POST_STATE_COMPLETE or task_id in published_task_ids:
            continue

        # Ignora se já tiver destinos planejados (no SQLite ou no state da tarefa)
        if persisted_platforms_map.get(task_id) or t.get("planned_platforms"):
            continue

        adoptable.append(t)

    return adoptable


def adopt_tasks_into_scheduler(
    task_ids: List[str],
    platforms: List[str],
    db_path: Optional[str] = None,
) -> int:
    """Associa tarefas concluídas aos destinos no SQLite (task_platforms).

    Retorna o número de tarefas associadas com sucesso.
    Idempotente: não duplica registros existentes.
    NÃO chama Upload-Post, NÃO move arquivos, NÃO altera script.json.
    """
    from app.services import operator_console
    operator_console.require_primary_instance(db_path=db_path)

    if not task_ids or not platforms:
        return 0

    init_db(db_path)

    count = 0
    for tid in task_ids:
        clean_id = (tid or "").strip()
        if clean_id:
            save_task_platforms(clean_id, platforms, db_path=db_path)
            count += 1
    return count


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Janela Móvel de 24h, Limites e Utilitários Temporais (UTC / Local)
# ---------------------------------------------------------------------------

def _normalize_utc(dt: Optional[datetime]) -> datetime:
    """Garante que um datetime seja UTC timezone-aware.

    - Se None: retorna datetime.now(timezone.utc).
    - Se naive: assume horário local do sistema e converte via .astimezone(timezone.utc).
    - Se aware: converte diretamente para UTC.
    """
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.astimezone(timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_iso(dt: datetime) -> str:
    """Converte datetime para string ISO 8601 UTC timezone-aware."""
    return _normalize_utc(dt).isoformat()


def _from_iso(iso_str: str) -> datetime:
    """Converte string ISO 8601 para datetime UTC timezone-aware.

    Compatibilidade segura com registros existentes:
    - Normaliza sufixo 'Z' para '+00:00'.
    - Se contiver timezone offset (+HH:MM / -HH:MM), normaliza para UTC.
    - Se for registro legado naive (sem offset), assume UTC (padrão do SQLite) e anexa timezone.utc.
    """
    if not iso_str:
        return datetime.now(timezone.utc)
    clean_str = str(iso_str).strip()
    if clean_str.endswith("Z"):
        clean_str = clean_str[:-1] + "+00:00"
    dt = datetime.fromisoformat(clean_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_local_datetime(dt_or_iso: Any, target_tz: Optional[timezone] = None) -> datetime:
    """Converte datetime ou string ISO 8601 para datetime no fuso horário local.

    Se target_tz for especificado (ex: UTC-3), converte para esse fuso.
    Caso contrário, converte para o fuso horário local do sistema operacional.
    """
    if isinstance(dt_or_iso, str):
        utc_dt = _from_iso(dt_or_iso)
    elif isinstance(dt_or_iso, datetime):
        utc_dt = _normalize_utc(dt_or_iso)
    else:
        utc_dt = datetime.now(timezone.utc)

    if target_tz is not None:
        return utc_dt.astimezone(target_tz)
    return utc_dt.astimezone()


def format_local_time(
    dt_or_iso: Any,
    fmt: str = "%H:%M (%d/%m)",
    target_tz: Optional[timezone] = None,
) -> str:
    """Formata datetime ou ISO string para exibição no fuso horário local do sistema."""
    if not dt_or_iso:
        return ""
    local_dt = to_local_datetime(dt_or_iso, target_tz=target_tz)
    return local_dt.strftime(fmt)


def get_platform_rate_limits(
    platform: str,
    db_path: Optional[str] = None,
    now: Optional[datetime] = None,
    current_time: Optional[datetime] = None,
    growth_mode: Optional[str] = None,
    profile_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Calcula a janela móvel de 24 horas para uma plataforma específica.
    
    Regra V3.1 / V9-C:
    - O menor limite sempre prevalece entre o teto técnico e o modo de crescimento operacional do perfil.
    - posts_publicados_ultimas_24h: publicações com status='success' nos últimos 24h (published_at >= now - 24h e <= now)
    - posts_agendados_proximas_24h: posts agendados ativos (status IN ('planned', 'ready')) agendados entre now e now + 24h
    - usados_janela: posts_publicados_ultimas_24h + posts_agendados_proximas_24h
    - disponiveis: max(0, limite_efetivo - usados_janela)
    """
    init_db(db_path)
    ref_time = now if now is not None else current_time
    calc_now = _normalize_utc(ref_time)
    window_past = calc_now - timedelta(hours=24)
    window_future = calc_now + timedelta(hours=24)

    iso_past = _to_iso(window_past)
    iso_now = _to_iso(calc_now)
    iso_future = _to_iso(window_future)

    settings = get_all_settings(db_path)
    clean_platform = platform.lower().strip()

    if clean_platform == "tiktok":
        technical_limit = settings["tiktok_limit_24h"]
        enabled = settings["tiktok_enabled"]
    elif clean_platform == "youtube":
        technical_limit = settings["youtube_limit_24h"]
        enabled = settings["youtube_enabled"]
    else:
        technical_limit = 10
        enabled = True

    if profile_id and not growth_mode:
        from app.services import profile_manager
        prof = profile_manager.get_profile(profile_id, db_path=db_path)
        if prof and prof.get("growth_mode"):
            growth_mode = prof.get("growth_mode")

    active_growth_mode = growth_mode or get_growth_mode(clean_platform, db_path)
    effective_limit = get_effective_limit(clean_platform, technical_limit, mode=active_growth_mode, db_path=db_path)
    mode_limits = const.GROWTH_MODE_LIMITS.get(active_growth_mode, {})
    min_interval_hours = mode_limits.get("min_interval_hours", 0)

    # O menor limite sempre prevalece como limite operacional de agendamento
    limit = effective_limit

    with get_connection(db_path) as conn:
        # Publicações globais das últimas 24h (apenas status='success')
        global_pub_row = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM publication_events
            WHERE platform = ? AND status = 'success'
            AND published_at >= ? AND published_at <= ?;
            """,
            (clean_platform, iso_past, iso_now),
        ).fetchone()
        global_used_past = global_pub_row["cnt"] if global_pub_row else 0

        # Posts globais já agendados para a janela próxima de 24h
        global_sched_row = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM scheduled_posts
            WHERE platform = ? AND status IN ('planned', 'ready')
            AND scheduled_at >= ? AND scheduled_at <= ?;
            """,
            (clean_platform, iso_now, iso_future),
        ).fetchone()
        global_sched_count = global_sched_row["cnt"] if global_sched_row else 0
        global_total_used = global_used_past + global_sched_count
        global_slots = max(0, technical_limit - global_total_used) if enabled else 0

        if profile_id:
            from app.services import profile_manager
            prof_norm = profile_id.strip()
            if prof_norm == profile_manager.DEFAULT_PROFILE_ID:
                prof_pub_row = conn.execute(
                    """
                    SELECT COUNT(*) AS cnt FROM publication_events
                    WHERE platform = ? AND status = 'success'
                    AND (profile_id = ? OR profile_id IS NULL OR profile_id = '')
                    AND published_at >= ? AND published_at <= ?;
                    """,
                    (clean_platform, prof_norm, iso_past, iso_now),
                ).fetchone()
                prof_sched_row = conn.execute(
                    """
                    SELECT COUNT(*) AS cnt FROM scheduled_posts
                    WHERE platform = ? AND status IN ('planned', 'ready')
                    AND (profile_id = ? OR profile_id IS NULL OR profile_id = '')
                    AND scheduled_at >= ? AND scheduled_at <= ?;
                    """,
                    (clean_platform, prof_norm, iso_now, iso_future),
                ).fetchone()
            else:
                prof_pub_row = conn.execute(
                    """
                    SELECT COUNT(*) AS cnt FROM publication_events
                    WHERE platform = ? AND status = 'success' AND profile_id = ?
                    AND published_at >= ? AND published_at <= ?;
                    """,
                    (clean_platform, prof_norm, iso_past, iso_now),
                ).fetchone()
                prof_sched_row = conn.execute(
                    """
                    SELECT COUNT(*) AS cnt FROM scheduled_posts
                    WHERE platform = ? AND status IN ('planned', 'ready') AND profile_id = ?
                    AND scheduled_at >= ? AND scheduled_at <= ?;
                    """,
                    (clean_platform, prof_norm, iso_now, iso_future),
                ).fetchone()

            used_past = prof_pub_row["cnt"] if prof_pub_row else 0
            scheduled_count = prof_sched_row["cnt"] if prof_sched_row else 0
            total_used = used_past + scheduled_count
            raw_mode_limit = mode_limits.get(clean_platform)
            profile_mode_limit = technical_limit if raw_mode_limit is None else raw_mode_limit
            profile_slots = max(0, profile_mode_limit - total_used) if enabled else 0
            available_slots = min(global_slots, profile_slots)
        else:
            used_past = global_used_past
            scheduled_count = global_sched_count
            total_used = global_total_used
            available_slots = max(0, limit - total_used) if enabled else 0

    return {
        "platform": clean_platform,
        "enabled": enabled,
        "limit": limit,
        "technical_limit": technical_limit,
        "effective_limit": effective_limit,
        "growth_mode": active_growth_mode,
        "min_interval_hours": min_interval_hours,
        "used_past_24h": used_past,
        "scheduled_24h": scheduled_count,
        "total_used": total_used,
        "available_slots": available_slots,
    }



# ---------------------------------------------------------------------------
# Scheduler: Planejamento e Agenda
# ---------------------------------------------------------------------------

def record_publication_event(
    task_id: str,
    platform: str,
    status: str = "success",
    published_at: Optional[datetime] = None,
    external_id: Optional[str] = None,
    error_code: Optional[str] = None,
    provider_request_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    profile_id: Optional[str] = None,
    external_url: Optional[str] = None,
    db_path: Optional[str] = None,
) -> None:
    """Registra um evento de publicação (usado pelo publicador manual ou testes)."""
    init_db(db_path)
    pub_time = _normalize_utc(published_at)
    iso_time = _to_iso(pub_time)
    clean_platform = platform.lower().strip()

    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO publication_events (
                task_id, platform, published_at, status, external_id, error_code, provider_request_id, profile_id, channel_id, external_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (task_id, clean_platform, iso_time, status, external_id, error_code, provider_request_id, profile_id, channel_id, external_url),
        )
        if status == "success":
            if channel_id:
                conn.execute(
                    """
                    UPDATE scheduled_posts
                    SET status = 'published'
                    WHERE task_id = ? AND platform = ? AND channel_id = ? AND status IN ('planned', 'ready');
                    """,
                    (task_id, clean_platform, channel_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE scheduled_posts
                    SET status = 'published'
                    WHERE task_id = ? AND platform = ? AND status IN ('planned', 'ready');
                    """,
                    (task_id, clean_platform),
                )


def clear_future_schedule(db_path: Optional[str] = None) -> int:
    """Remove apenas itens agendados futuros (planned e ready), preservando histórico published."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            DELETE FROM scheduled_posts
            WHERE status IN ('planned', 'ready');
            """
        )
        return cursor.rowcount


def get_upcoming_posts(limit: int = 50, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retorna os próximos posts agendados ativos ordenados cronologicamente com metadados de profile/channel."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, task_id, platform, scheduled_at, status, created_at, attempts, last_error, next_attempt_at, profile_id, channel_id
            FROM scheduled_posts
            WHERE status IN ('planned', 'ready')
            ORDER BY scheduled_at ASC
            LIMIT ?;
            """,
            (limit,),
        ).fetchall()

        from app.services import profile_manager
        enriched = []
        for r in rows:
            d = dict(r)
            pid = d.get("profile_id")
            cid = d.get("channel_id")
            if pid:
                prof = profile_manager.get_profile(pid, db_path=db_path)
                if prof:
                    d["profile_name"] = prof.get("name")
            if cid:
                ch = profile_manager.get_channel(cid, db_path=db_path)
                if ch:
                    d["channel_name"] = ch.get("channel_name")
            enriched.append(d)
        return enriched


def plan_schedule(
    tasks: List[Dict[str, Any]],
    now: Optional[datetime] = None,
    db_path: Optional[str] = None,
    growth_mode: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Gera o planejamento da agenda para vídeos concluídos ainda não agendados.
    
    Regras estritas:
    - Apenas vídeos concluídos (state == TASK_STATE_COMPLETE ou has_video)
    - Não agenda PROCESSING, PENDING, FAILED ou já publicados
    - Respeita o perfil imutável da task e os canais habilitados vinculados
    - Respeita os limites por rede na janela móvel de 24h (teto técnico + growth mode do perfil)
    - Distribui horários uniformemente ao longo do período
    - Idempotência: não duplica (task_id, channel_id, platform) já agendada ou publicada
    - NÃO chama Upload-Post
    """
    from app.services import operator_console, profile_manager
    operator_console.require_primary_instance(db_path=db_path)
    if operator_console.is_factory_paused(db_path=db_path):
        return []

    init_db(db_path)

    current_time = _normalize_utc(now)
    persisted_platforms_map = get_all_task_platforms(db_path)
    settings = get_all_settings(db_path)

    # 1. Filtra tarefas elegíveis e resolve canais/destinos de acordo com o perfil imutável da task
    eligible_tasks: List[Tuple[str, Dict[str, Any], List[Tuple[str, Optional[str], str]]]] = []
    for t in tasks:
        task_id = t.get("task_id", "")
        if not task_id:
            continue

        state = t.get("state")
        cross_post_state = t.get("cross_post_state")
        has_video = bool(t.get("video_file"))

        # Ignora estados não concluídos ou cancelados
        if state in (const.TASK_STATE_PROCESSING, const.TASK_STATE_PENDING, const.TASK_STATE_FAILED, const.TASK_STATE_CANCELLED) or t.get("cancelled"):
            continue

        # Ignora tarefas já publicadas no MoneyPrinterTurbo
        if cross_post_state == const.CROSS_POST_STATE_COMPLETE:
            continue

        # Deve estar completo ou com vídeo final gerado
        is_complete = state == const.TASK_STATE_COMPLETE or has_video
        if not is_complete:
            continue

        # Obtém destinos planejados (do state da task ou do SQLite persistido)
        platforms = t.get("planned_platforms") or persisted_platforms_map.get(task_id, [])
        if not platforms:
            continue

        # Gate de Monetização: tarefas com safety_status BLOCK ou REVIEW não entram automaticamente no Scheduler
        safety_status = t.get("safety_status")
        if not safety_status:
            try:
                from app.services import safety_gate
                safety_rec = safety_gate.get_safety_assessment(task_id, db_path=db_path)
                if safety_rec:
                    safety_status = safety_rec.get("safety_status")
            except Exception:
                safety_status = None

        if safety_status and str(safety_status).upper() in (const.SAFETY_STATUS_BLOCK, const.SAFETY_STATUS_REVIEW):
            logger.info(f"[SCHEDULER][GATE] Tarefa {task_id} ignorada no agendamento automático devido a Safety={safety_status}")
            continue

        # Resolução do perfil da task
        task_profile_id = profile_manager.get_task_profile_id(task_id, db_path=db_path)
        prof = profile_manager.get_profile(task_profile_id, db_path=db_path)
        if prof and not prof.get("is_active"):
            operator_console.log_operational_event(
                component="scheduler",
                severity="WARNING",
                event_type="PROFILE_DISABLED_BLOCK",
                task_id=task_id,
                message=f"Perfil '{task_profile_id}' está desativado. Agendamento ignorado.",
                metadata={"profile_id": task_profile_id},
                db_path=db_path,
            )
            continue

        clean_platforms = [p.lower().strip() for p in platforms if p and p.strip()]
        all_prof_channels = profile_manager.list_channels(profile_id=task_profile_id, db_path=db_path)

        destinations: List[Tuple[str, Optional[str], str]] = []
        if all_prof_channels:
            for plat in clean_platforms:
                plat_channels = [c for c in all_prof_channels if c.get("platform", "").lower().strip() == plat]
                if plat_channels:
                    enabled_plat = [c for c in plat_channels if c.get("is_enabled")]
                    if not enabled_plat:
                        operator_console.log_operational_event(
                            component="scheduler",
                            severity="WARNING",
                            event_type="CHANNEL_DISABLED_BLOCK",
                            task_id=task_id,
                            message=f"Todos os canais de {plat} para o perfil {task_profile_id} estão desativados.",
                            metadata={"profile_id": task_profile_id, "platform": plat},
                            db_path=db_path,
                        )
                        continue
                    for c in enabled_plat:
                        destinations.append((task_profile_id, c["channel_id"], plat))
                else:
                    destinations.append((task_profile_id, None, plat))
        else:
            # Sem canais configurados no perfil -> fallback legado seguro
            for plat in clean_platforms:
                destinations.append((task_profile_id, None, plat))

        if not destinations:
            continue

        eligible_tasks.append((task_id, t, destinations))

    if not eligible_tasks:
        return []

    created_schedule: List[Dict[str, Any]] = []

    # 2. Processa por plataforma para manter cadência individual uniforme e anti-burst
    for platform in ("tiktok", "youtube"):
        clean_plat = platform.lower().strip()
        if clean_plat == "tiktok" and not settings["tiktok_enabled"]:
            continue
        if clean_plat == "youtube" and not settings["youtube_enabled"]:
            continue

        # Coleta candidatos para esta plataforma
        candidates: List[Tuple[str, Dict[str, Any], str, Optional[str]]] = []
        for task_id, task_data, destinations in eligible_tasks:
            for pid, cid, plat in destinations:
                if plat == clean_plat:
                    candidates.append((task_id, task_data, pid, cid))

        if not candidates:
            continue

        # Encontra a última publicação real e o último agendamento existente para essa plataforma
        with get_connection(db_path) as conn:
            last_sched_row = conn.execute(
                """
                SELECT MAX(scheduled_at) AS max_time FROM scheduled_posts
                WHERE platform = ? AND status IN ('planned', 'ready');
                """,
                (clean_plat,),
            ).fetchone()
            last_pub_row = conn.execute(
                """
                SELECT MAX(published_at) AS max_pub FROM publication_events
                WHERE platform = ? AND status = 'success';
                """,
                (clean_plat,),
            ).fetchone()

        # Enfileira slots para os candidatos
        for task_id, task_data, task_profile_id, channel_id in candidates:
            # 1. Verifica idempotência: já existe no scheduled_posts ou publication_events?
            with get_connection(db_path) as conn:
                if channel_id:
                    existing = conn.execute(
                        """
                        SELECT id FROM scheduled_posts
                        WHERE task_id = ? AND platform = ? AND channel_id = ?
                        AND status IN ('planned', 'ready', 'published');
                        """,
                        (task_id, clean_plat, channel_id),
                    ).fetchone()
                    already_pub = conn.execute(
                        """
                        SELECT id FROM publication_events
                        WHERE task_id = ? AND platform = ? AND channel_id = ?
                        AND status = 'success';
                        """,
                        (task_id, clean_plat, channel_id),
                    ).fetchone()
                else:
                    existing = conn.execute(
                        """
                        SELECT id FROM scheduled_posts
                        WHERE task_id = ? AND platform = ? AND (channel_id IS NULL OR channel_id = '')
                        AND status IN ('planned', 'ready', 'published');
                        """,
                        (task_id, clean_plat),
                    ).fetchone()
                    already_pub = conn.execute(
                        """
                        SELECT id FROM publication_events
                        WHERE task_id = ? AND platform = ? AND (channel_id IS NULL OR channel_id = '')
                        AND status = 'success';
                        """,
                        (task_id, clean_plat),
                    ).fetchone()

                if existing or already_pub:
                    continue

            # 2. Consulta limites específicos do perfil no modo de crescimento ativo
            rate_info = get_platform_rate_limits(
                clean_plat,
                db_path=db_path,
                now=current_time,
                growth_mode=growth_mode,
                profile_id=task_profile_id,
            )
            if not rate_info["enabled"] or rate_info["available_slots"] <= 0:
                operator_console.log_operational_event(
                    component="scheduler",
                    severity="INFO",
                    event_type="PROFILE_GROWTH_LIMIT_BLOCK",
                    task_id=task_id,
                    message=f"Limite do modo {rate_info.get('growth_mode')} atingido para {clean_plat} no perfil {task_profile_id}.",
                    metadata={"profile_id": task_profile_id, "platform": clean_plat, "growth_mode": rate_info.get("growth_mode")},
                    db_path=db_path,
                )
                continue

            limit_24h = rate_info["limit"]
            min_interval_seconds = rate_info.get("min_interval_hours", 0) * 3600
            uniform_interval_seconds = max(60, int(86400 / max(1, limit_24h)))
            step_seconds = max(min_interval_seconds, uniform_interval_seconds)

            candidate_base = current_time
            if last_pub_row and last_pub_row["max_pub"]:
                try:
                    p_dt = _from_iso(last_pub_row["max_pub"])
                    candidate_base = max(candidate_base, p_dt + timedelta(seconds=min_interval_seconds))
                except Exception:
                    pass

            if last_sched_row and last_sched_row["max_time"]:
                try:
                    s_dt = _from_iso(last_sched_row["max_time"])
                    candidate_base = max(candidate_base, s_dt + timedelta(seconds=step_seconds))
                except Exception:
                    candidate_base = max(candidate_base, current_time + timedelta(seconds=step_seconds))
            else:
                if candidate_base == current_time:
                    candidate_base = current_time + timedelta(seconds=min(300, step_seconds))

            target_slot = candidate_base

            # 3. Insere novo slot planejado com profile_id e channel_id
            iso_slot = _to_iso(target_slot)
            iso_created = _to_iso(current_time)
            with get_connection(db_path) as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO scheduled_posts (
                        task_id, platform, scheduled_at, status, created_at, profile_id, channel_id
                    ) VALUES (?, ?, ?, 'planned', ?, ?, ?);
                    """,
                    (task_id, clean_plat, iso_slot, iso_created, task_profile_id, channel_id),
                )
                new_id = cursor.lastrowid

            record = {
                "id": new_id,
                "task_id": task_id,
                "platform": clean_plat,
                "profile_id": task_profile_id,
                "channel_id": channel_id,
                "scheduled_at": iso_slot,
                "status": STATUS_PLANNED,
                "subject": task_data.get("subject", task_id),
            }
            created_schedule.append(record)

            # Atualiza last_sched_row para o próximo candidato desta plataforma
            last_sched_row = {"max_time": iso_slot}

    return created_schedule


# ---------------------------------------------------------------------------
# V2.2: Scheduler Execution Engine & Worker Daemon
# ---------------------------------------------------------------------------

_worker_thread: Optional[threading.Thread] = None
_worker_lock = threading.Lock()
_worker_stop_event = threading.Event()
_executor_status: Dict[str, Any] = {
    "state": "stopped",
    "message": "Executor parado",
    "last_run_at": None,
    "last_result": None,
    "last_cycle_summary": None,
    "current_post": None,
}


def _set_executor_status(
    state: Optional[str] = None,
    message: Optional[str] = None,
    last_run_at: Optional[str] = None,
    last_result: Optional[str] = None,
    last_cycle_summary: Optional[str] = None,
    current_post: Optional[Dict[str, Any]] = None,
    db_path: Optional[str] = None,
) -> None:
    """Atualiza o status do executor na memória e no SQLite."""
    global _executor_status
    if state is not None:
        _executor_status["state"] = state
        set_setting("executor_state", state, db_path=db_path)
    if message is not None:
        _executor_status["message"] = message
        set_setting("executor_message", message, db_path=db_path)
    if last_run_at is not None:
        _executor_status["last_run_at"] = last_run_at
        set_setting("executor_last_run_at", last_run_at, db_path=db_path)
    if last_result is not None:
        _executor_status["last_result"] = last_result
        set_setting("executor_last_result", last_result, db_path=db_path)
    if last_cycle_summary is not None:
        _executor_status["last_cycle_summary"] = last_cycle_summary
        set_setting("executor_last_cycle_summary", last_cycle_summary, db_path=db_path)
    if current_post is not None:
        _executor_status["current_post"] = current_post


def reset_executor_status(db_path: Optional[str] = None) -> None:
    """Restaura o estado do executor para valores padrão (usado em testes)."""
    global _executor_status
    _executor_status = {
        "state": "stopped",
        "message": "Executor parado",
        "last_run_at": None,
        "last_result": None,
        "last_cycle_summary": None,
        "current_post": None,
    }
    init_db(db_path)
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM autopilot_settings WHERE key LIKE 'executor_%';")


def get_executor_status(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Retorna o status atual do executor do scheduler de forma persistente e thread-safe."""
    init_db(db_path)

    # 1. Determina se o worker está ativo (referência viva OU heartbeat recente nos últimos 60s)
    is_alive = False
    with _worker_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            is_alive = True

    last_tick_iso = get_setting("executor_last_tick", None, db_path=db_path)
    if not is_alive and last_tick_iso:
        try:
            tick_dt = _from_iso(last_tick_iso)
            diff_sec = abs((datetime.now(timezone.utc) - tick_dt).total_seconds())
            if diff_sec < 60:
                is_alive = True
        except Exception:
            pass

    default_state = "idle" if is_alive else "stopped"
    default_msg = "Aguardando posts agendados" if is_alive else "Executor parado"

    state = get_setting("executor_state", default_state, db_path=db_path)
    message = get_setting("executor_message", default_msg, db_path=db_path)
    last_run_at = get_setting("executor_last_run_at", _executor_status.get("last_run_at"), db_path=db_path)
    last_result = get_setting("executor_last_result", _executor_status.get("last_result"), db_path=db_path)
    last_cycle_summary = get_setting("executor_last_cycle_summary", _executor_status.get("last_cycle_summary"), db_path=db_path)

    return {
        "worker_active": is_alive,
        "state": state if is_alive else "stopped",
        "message": message,
        "last_tick": last_tick_iso,
        "last_run_at": last_run_at,
        "last_result": last_result,
        "last_cycle_summary": last_cycle_summary,
        "current_post": _executor_status.get("current_post"),
    }


def classify_error(error_msg: str) -> str:
    """Classifica um erro de publicação em 'transient' ou 'permanent'."""
    err = (error_msg or "").lower()
    transient_keywords = [
        "429",
        "rate limit",
        "too many requests",
        "timeout",
        "timed out",
        "connection",
        "network",
        "500",
        "502",
        "503",
        "504",
        "server error",
        "service unavailable",
        "temporary",
        "econnreset",
    ]
    for kw in transient_keywords:
        if kw in err:
            return "transient"
    return "permanent"


def calculate_backoff_seconds(attempt: int, retry_after: Optional[int] = None) -> int:
    """Calcula o tempo de espera em segundos para retry de falhas temporárias."""
    if retry_after and retry_after > 0:
        return retry_after
    if attempt == 1:
        return 15 * 60  # 15 minutos
    if attempt == 2:
        return 60 * 60  # 60 minutos
    return 60 * 60


def get_task_final_video(task_id: str, task_base_dir: Optional[str] = None) -> Optional[str]:
    """Retorna o caminho absoluto do arquivo de vídeo final existente em disco."""
    base = task_base_dir or utils.task_dir()
    task_path = os.path.join(base, task_id)
    if not os.path.isdir(task_path):
        return None
    try:
        final_videos = []
        for file_name in os.listdir(task_path):
            match = _FINAL_VIDEO_PATTERN.fullmatch(file_name)
            if match:
                final_videos.append((int(match.group("index")), os.path.join(task_path, file_name)))
            elif file_name.startswith("final-") and file_name.endswith(".mp4"):
                final_videos.append((0, os.path.join(task_path, file_name)))
        if final_videos:
            final_videos.sort(key=lambda x: x[0])
            first_path = final_videos[0][1]
            if os.path.isfile(first_path):
                return first_path
    except OSError:
        pass
    return None


def run_scheduler_cycle(
    now: Optional[datetime] = None,
    db_path: Optional[str] = None,
    task_base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Executa um ciclo do motor de publicação do Scheduler.

    Verifica se há publicações vencidas (scheduled_at <= now), revalida todos os
    pré-requisitos de segurança, limites de 24h e idempotência, e processa exatamente
    um post por ciclo (concorrência unitária).
    """
    init_db(db_path)
    current_time = _normalize_utc(now)
    iso_now = _to_iso(current_time)
    settings = get_all_settings(db_path)

    logger.info(
        f"[SCHEDULER][CYCLE] scheduler_enabled={settings['scheduler_enabled']} "
        f"auto_publish_enabled={settings['auto_publish_enabled']} "
        f"dry_run={settings['dry_run']} db_path={get_db_path(db_path)}"
    )

    from app.services import operator_console
    if not operator_console.is_primary_instance(db_path=db_path):
        _set_executor_status(
            state="idle",
            message="Instância secundária (VIEW ONLY): execuções de publicação bloqueadas",
            last_cycle_summary="Instância em modo leitura",
            db_path=db_path,
        )
        logger.info("[SCHEDULER][CYCLE] skipped reason=secondary_view_only")
        return {"status": "skipped", "reason": "secondary_view_only"}

    if operator_console.is_factory_paused(db_path=db_path):

        _set_executor_status(
            state="paused",
            message="Fábrica pausada: execuções de publicação bloqueadas",
            last_cycle_summary="Fábrica pausada",
            db_path=db_path,
        )
        logger.info("[SCHEDULER][CYCLE] skipped reason=factory_paused")
        return {"status": "skipped", "reason": "factory_paused"}

    if not settings["scheduler_enabled"]:
        _set_executor_status(state="stopped", message="Scheduler desativado", last_cycle_summary="Scheduler desativado", db_path=db_path)
        logger.info("[SCHEDULER][CYCLE] skipped reason=scheduler_disabled")
        return {"status": "skipped", "reason": "scheduler_disabled"}

    if not settings["auto_publish_enabled"]:
        _set_executor_status(state="idle", message="Publicação automática desativada (Scheduler em modo planejamento)", last_cycle_summary="Publicação automática desativada", db_path=db_path)
        logger.info("[SCHEDULER][CYCLE] skipped reason=auto_publish_disabled")
        return {"status": "skipped", "reason": "auto_publish_disabled"}

    # 1. Busca o post vencido mais antigo
    with get_connection(db_path) as conn:
        due_count = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM scheduled_posts
            WHERE status IN ('planned', 'ready')
            AND scheduled_at <= ?
            AND (next_attempt_at IS NULL OR next_attempt_at <= ?);
            """,
            (iso_now, iso_now),
        ).fetchone()["cnt"]

        due_row = conn.execute(
            """
            SELECT id, task_id, platform, scheduled_at, status, created_at, attempts, last_error, next_attempt_at, profile_id, channel_id
            FROM scheduled_posts
            WHERE status IN ('planned', 'ready')
            AND scheduled_at <= ?
            AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
            ORDER BY scheduled_at ASC
            LIMIT 1;
            """,
            (iso_now, iso_now),
        ).fetchone()

    logger.info(f"[SCHEDULER][CYCLE] due_posts={due_count}")

    if not due_row:
        _set_executor_status(state="idle", message="Aguardando posts agendados", last_cycle_summary="Nenhum post vencido", db_path=db_path)
        return {"status": "idle"}

    post = dict(due_row)
    post_id = post["id"]
    task_id = post["task_id"]
    platform = post["platform"].lower().strip()
    attempts = int(post.get("attempts") or 0)
    dry_run = settings["dry_run"]

    from app.services import profile_manager
    profile_id = post.get("profile_id") or profile_manager.get_task_profile_id(task_id, db_path=db_path)
    channel_id = post.get("channel_id")

    logger.info(f"[SCHEDULER][CYCLE] candidate id={post_id} task_id={task_id} platform={platform} profile_id={profile_id} channel_id={channel_id} scheduled_at={post['scheduled_at']}")

    # 2. Revalidação: Perfil da task ativo
    prof = profile_manager.get_profile(profile_id, db_path=db_path)
    if prof and not prof.get("is_active"):
        postpone_time = current_time + timedelta(minutes=30)
        with get_connection(db_path) as conn:
            conn.execute(
                "UPDATE scheduled_posts SET scheduled_at = ?, next_attempt_at = ?, status = 'ready' WHERE id = ?;",
                (_to_iso(postpone_time), _to_iso(postpone_time), post_id),
            )
        operator_console.log_operational_event(
            component="scheduler",
            severity="WARNING",
            event_type="PROFILE_DISABLED_BLOCK",
            task_id=task_id,
            message=f"Publicação bloqueada: perfil '{profile_id}' está inativo.",
            metadata={"profile_id": profile_id, "post_id": post_id},
            db_path=db_path,
        )
        _set_executor_status(
            state="idle",
            message=f"Post {post_id} postergado: perfil {profile_id} desativado",
            last_cycle_summary=f"Post {post_id} adiado: perfil {profile_id} desativado",
            db_path=db_path,
        )
        logger.warning(f"[SCHEDULER][CYCLE] Post {post_id} postergado: perfil '{profile_id}' desativado.")
        return {"status": "postponed", "reason": "profile_disabled", "profile_id": profile_id}

    # 3. Revalidação: Canal de publicação ativo (se channel_id especificado)
    if channel_id:
        ch = profile_manager.get_channel(channel_id, db_path=db_path)
        if not ch or not ch.get("is_enabled"):
            postpone_time = current_time + timedelta(minutes=30)
            with get_connection(db_path) as conn:
                conn.execute(
                    "UPDATE scheduled_posts SET scheduled_at = ?, next_attempt_at = ?, status = 'ready' WHERE id = ?;",
                    (_to_iso(postpone_time), _to_iso(postpone_time), post_id),
                )
            operator_console.log_operational_event(
                component="scheduler",
                severity="WARNING",
                event_type="CHANNEL_DISABLED_BLOCK",
                task_id=task_id,
                message=f"Publicação bloqueada: canal '{channel_id}' está desabilitado.",
                metadata={"channel_id": channel_id, "post_id": post_id},
                db_path=db_path,
            )
            _set_executor_status(
                state="idle",
                message=f"Post {post_id} postergado: canal {channel_id} desativado",
                last_cycle_summary=f"Post {post_id} adiado: canal {channel_id} desativado",
                db_path=db_path,
            )
            logger.warning(f"[SCHEDULER][CYCLE] Post {post_id} postergado: canal '{channel_id}' desabilitado.")
            return {"status": "postponed", "reason": "channel_disabled", "channel_id": channel_id}

    # 4. Revalidação: Plataforma habilitada nas configurações
    if platform == "tiktok" and not settings["tiktok_enabled"]:
        logger.info(f"[SCHEDULER][CYCLE] skipped reason=platform_disabled (tiktok)")
        _set_executor_status(last_cycle_summary=f"Post {post_id} ignorado: tiktok desativado", db_path=db_path)
        return {"status": "skipped", "reason": "platform_disabled", "platform": platform}
    if platform == "youtube" and not settings["youtube_enabled"]:
        logger.info(f"[SCHEDULER][CYCLE] skipped reason=platform_disabled (youtube)")
        _set_executor_status(last_cycle_summary=f"Post {post_id} ignorado: youtube desativado", db_path=db_path)
        return {"status": "skipped", "reason": "platform_disabled", "platform": platform}

    # 5. Revalidação: Plataforma planejada para a tarefa
    planned_platforms = get_task_platforms(task_id, db_path)
    if planned_platforms and platform not in planned_platforms:
        with get_connection(db_path) as conn:
            conn.execute(
                "UPDATE scheduled_posts SET status = 'failed', last_error = ? WHERE id = ?;",
                (f"Plataforma {platform} não está planejada para a tarefa", post_id),
            )
        logger.error(f"[SCHEDULER][CYCLE] skipped reason=platform_not_planned ({platform}) na task {task_id}")
        _set_executor_status(last_cycle_summary=f"Post {post_id} falhou: plataforma não planejada", db_path=db_path)
        return {"status": "failed", "reason": "platform_not_planned", "task_id": task_id, "platform": platform}

    # 6. Revalidação: Arquivo de vídeo final existente em disco
    video_file = get_task_final_video(task_id, task_base_dir=task_base_dir)
    if not video_file or not os.path.isfile(video_file):
        with get_connection(db_path) as conn:
            conn.execute(
                "UPDATE scheduled_posts SET status = 'failed', last_error = 'Arquivo de vídeo final não encontrado' WHERE id = ?;",
                (post_id,),
            )
        logger.error(f"[SCHEDULER][CYCLE] skipped reason=video_not_found para a task {task_id}")
        _set_executor_status(last_cycle_summary=f"Post {post_id} falhou: vídeo não encontrado", db_path=db_path)
        return {"status": "failed", "reason": "video_not_found", "task_id": task_id}

    # 7. Idempotência: Checa se já existe publicação concluída com sucesso
    with get_connection(db_path) as conn:
        if channel_id:
            pub_event = conn.execute(
                "SELECT id FROM publication_events WHERE task_id = ? AND platform = ? AND channel_id = ? AND status = 'success';",
                (task_id, platform, channel_id),
            ).fetchone()
            other_pub = conn.execute(
                "SELECT id FROM scheduled_posts WHERE task_id = ? AND platform = ? AND channel_id = ? AND status = 'published' AND id != ?;",
                (task_id, platform, channel_id, post_id),
            ).fetchone()
        else:
            pub_event = conn.execute(
                "SELECT id FROM publication_events WHERE task_id = ? AND platform = ? AND status = 'success';",
                (task_id, platform),
            ).fetchone()
            other_pub = conn.execute(
                "SELECT id FROM scheduled_posts WHERE task_id = ? AND platform = ? AND status = 'published' AND id != ?;",
                (task_id, platform, post_id),
            ).fetchone()

    if pub_event or other_pub:
        with get_connection(db_path) as conn:
            conn.execute(
                "UPDATE scheduled_posts SET status = 'published', last_error = NULL WHERE id = ?;",
                (post_id,),
            )
        logger.info(f"[SCHEDULER][CYCLE] skipped reason=already_published ({task_id} - {platform})")
        _set_executor_status(last_cycle_summary=f"Post {post_id} ignorado por idempotência (já publicado)", db_path=db_path)
        return {"status": "skipped", "reason": "already_published", "task_id": task_id, "platform": platform}

    # 8. Revalidação da Janela Móvel de 24 horas (Técnica + Growth Mode do perfil)
    rate_info = get_platform_rate_limits(platform, db_path, now=current_time, profile_id=profile_id)
    if rate_info["available_slots"] <= 0:
        window_past = current_time - timedelta(hours=24)
        with get_connection(db_path) as conn:
            if profile_id and profile_id != profile_manager.DEFAULT_PROFILE_ID:
                oldest_row = conn.execute(
                    """
                    SELECT MIN(published_at) AS oldest_pub FROM publication_events
                    WHERE platform = ? AND profile_id = ? AND status = 'success' AND published_at >= ?;
                    """,
                    (platform, profile_id, _to_iso(window_past)),
                ).fetchone()
            else:
                oldest_row = conn.execute(
                    """
                    SELECT MIN(published_at) AS oldest_pub FROM publication_events
                    WHERE platform = ? AND status = 'success' AND published_at >= ?;
                    """,
                    (platform, _to_iso(window_past)),
                ).fetchone()

        if oldest_row and oldest_row["oldest_pub"]:
            try:
                oldest_dt = _from_iso(oldest_row["oldest_pub"])
                next_eligible = oldest_dt + timedelta(hours=24, minutes=1)
            except Exception:
                next_eligible = current_time + timedelta(minutes=15)
        else:
            next_eligible = current_time + timedelta(minutes=15)

        if next_eligible <= current_time:
            next_eligible = current_time + timedelta(minutes=15)

        with get_connection(db_path) as conn:
            conn.execute(
                """
                UPDATE scheduled_posts
                SET scheduled_at = ?, next_attempt_at = ?, status = 'ready'
                WHERE id = ?;
                """,
                (_to_iso(next_eligible), _to_iso(next_eligible), post_id),
            )

        operator_console.log_operational_event(
            component="scheduler",
            severity="INFO",
            event_type="PROFILE_GROWTH_LIMIT_BLOCK",
            task_id=task_id,
            message=f"Limite de {platform} atingido ({rate_info['total_used']}/{rate_info['limit']} no modo {rate_info.get('growth_mode')}) para perfil {profile_id}.",
            metadata={"profile_id": profile_id, "platform": platform, "growth_mode": rate_info.get("growth_mode")},
            db_path=db_path,
        )

        _set_executor_status(
            state="limit_blocked",
            message=f"Limite de {platform} atingido ({rate_info['total_used']}/{rate_info['limit']} no modo {rate_info.get('growth_mode')})",
            last_cycle_summary=f"Post {post_id} bloqueado por limite de {platform} ({rate_info.get('growth_mode')})",
            db_path=db_path,
        )
        logger.warning(
            f"[SCHEDULER][LIMIT] Limite da plataforma {platform} atingido ({rate_info['total_used']}/{rate_info['limit']} - {rate_info.get('growth_mode')}). "
            f"Post {post_id} postergado com segurança para {_to_iso(next_eligible)}"
        )
        return {
            "status": "postponed",
            "reason": "rate_limit_reached",
            "platform": platform,
            "next_eligible": _to_iso(next_eligible),
        }

    # 8.1 Revalidação de Intervalo Mínimo (Growth Mode Anti-Burst do perfil)
    min_interval_hours = rate_info.get("min_interval_hours", 0)
    if min_interval_hours > 0:
        with get_connection(db_path) as conn:
            if profile_id and profile_id != profile_manager.DEFAULT_PROFILE_ID:
                last_pub = conn.execute(
                    """
                    SELECT MAX(published_at) AS last_pub FROM publication_events
                    WHERE platform = ? AND profile_id = ? AND status = 'success';
                    """,
                    (platform, profile_id),
                ).fetchone()
            else:
                last_pub = conn.execute(
                    """
                    SELECT MAX(published_at) AS last_pub FROM publication_events
                    WHERE platform = ? AND status = 'success';
                    """,
                    (platform,),
                ).fetchone()
        if last_pub and last_pub["last_pub"]:
            try:
                last_pub_dt = _from_iso(last_pub["last_pub"])
                min_allowed = last_pub_dt + timedelta(hours=min_interval_hours)
                if current_time < min_allowed:
                    next_eligible = min_allowed
                    with get_connection(db_path) as conn:
                        conn.execute(
                            """
                            UPDATE scheduled_posts
                            SET scheduled_at = ?, next_attempt_at = ?, status = 'ready'
                            WHERE id = ?;
                            """,
                            (_to_iso(next_eligible), _to_iso(next_eligible), post_id),
                        )
                    _set_executor_status(
                        state="interval_blocked",
                        message=f"Intervalo mínimo de {platform} ({min_interval_hours}h) não atingido no modo {rate_info.get('growth_mode')}",
                        last_cycle_summary=f"Post {post_id} adiado: intervalo mínimo de {platform} não atingido",
                        db_path=db_path,
                    )
                    logger.warning(
                        f"[SCHEDULER][GROWTH_MODE] Intervalo mínimo de {min_interval_hours}h para {platform} ({rate_info.get('growth_mode')}) não atingido. "
                        f"Última publicação foi em {_to_iso(last_pub_dt)}. Post {post_id} reagendado com segurança para {_to_iso(next_eligible)}"
                    )
                    return {
                        "status": "postponed",
                        "reason": "min_interval_not_met",
                        "platform": platform,
                        "next_eligible": _to_iso(next_eligible),
                    }
            except Exception as exc:
                logger.warning(f"Erro ao verificar intervalo mínimo para {platform}: {exc}")


    # 7. Modo Simulação (DRY RUN)
    if dry_run:
        sim_next = current_time + timedelta(minutes=30)
        before_sched = post.get("scheduled_at")
        with get_connection(db_path) as conn:
            cur = conn.execute(
                "UPDATE scheduled_posts SET scheduled_at = ?, next_attempt_at = ? WHERE id = ?;",
                (_to_iso(sim_next), _to_iso(sim_next), post_id),
            )
            update_rowcount = cur.rowcount
            after_row = conn.execute(
                "SELECT scheduled_at, next_attempt_at FROM scheduled_posts WHERE id = ?;",
                (post_id,),
            ).fetchone()
            after_sched = after_row["scheduled_at"] if after_row else None
            after_next = after_row["next_attempt_at"] if after_row else None

        logger.info(f"[SCHEDULER][DRY-RUN] post_id={post_id}")
        logger.info(f"[SCHEDULER][DRY-RUN] before scheduled_at={before_sched}")
        logger.info(f"[SCHEDULER][DRY-RUN] sim_next={_to_iso(sim_next)}")
        logger.info(f"[SCHEDULER][DRY-RUN] update_rowcount={update_rowcount}")
        logger.info(f"[SCHEDULER][DRY-RUN] after_db scheduled_at={after_sched}")
        logger.info(f"[SCHEDULER][DRY-RUN] after_db next_attempt_at={after_next}")

        _set_executor_status(
            state="idle",
            message="Simulação Dry Run concluída",
            last_run_at=iso_now,
            last_result=f"[DRY-RUN] Simulação concluída com sucesso para {task_id} ({platform})",
            last_cycle_summary=f"[DRY-RUN] Post {post_id} ({platform}) simulado",
            db_path=db_path,
        )
        return {
            "status": "simulated",
            "task_id": task_id,
            "platform": platform,
            "dry_run": True,
        }

    # 8. Execução Real (DRY RUN == False)
    # Bloqueio atômico de concorrência: altera status para 'processing'
    with get_connection(db_path) as conn:
        cur = conn.execute(
            "UPDATE scheduled_posts SET status = 'processing' WHERE id = ? AND status IN ('planned', 'ready');",
            (post_id,),
        )
        if cur.rowcount == 0:
            return {"status": "skipped", "reason": "already_locked"}

    _set_executor_status(
        state="processing",
        message=f"Publicando {task_id} no {platform}...",
        current_post={"task_id": task_id, "platform": platform},
        last_cycle_summary=f"Publicando post {post_id} ({platform})",
        db_path=db_path,
    )
    logger.info(f"[SCHEDULER][PUBLISH] Iniciando publicação automática para {task_id} no {platform}")

    from app.services import task as task_module
    success, err_msg = task_module.publish_task(
        task_id,
        platforms=[platform],
        channel_id=channel_id,
        synchronous=True,
        db_path=db_path,
    )

    pub_now_iso = _to_iso(datetime.now(timezone.utc))
    _set_executor_status(current_post=None, last_run_at=pub_now_iso, db_path=db_path)

    if success:
        with get_connection(db_path) as conn:
            conn.execute(
                "UPDATE scheduled_posts SET status = 'published', last_error = NULL WHERE id = ?;",
                (post_id,),
            )
        _set_executor_status(
            state="idle",
            message="Aguardando posts agendados",
            last_result=f"Sucesso: {task_id} publicado no {platform}",
            last_cycle_summary=f"Sucesso: post {post_id} publicado no {platform}",
            db_path=db_path,
        )
        logger.success(f"[SCHEDULER][PUBLISH] Tarefa {task_id} publicada com sucesso no {platform}")
        return {"status": "published", "task_id": task_id, "platform": platform}
    else:
        err_type = classify_error(err_msg)
        new_attempts = attempts + 1
        if err_type == "transient" and new_attempts < 3:
            backoff_sec = calculate_backoff_seconds(new_attempts)
            next_retry = current_time + timedelta(seconds=backoff_sec)
            with get_connection(db_path) as conn:
                conn.execute(
                    """
                    UPDATE scheduled_posts
                    SET status = 'ready', attempts = ?, last_error = ?, next_attempt_at = ?
                    WHERE id = ?;
                    """,
                    (new_attempts, (err_msg or "")[:500], _to_iso(next_retry), post_id),
                )
            _set_executor_status(
                state="error",
                message=f"Retry {new_attempts}/3 agendado ({platform})",
                last_result=f"Falha temporária ({platform}): {(err_msg or '')[:100]} - Retry {new_attempts}/3 em {backoff_sec//60}min",
                last_cycle_summary=f"Retry agendado para post {post_id} ({platform})",
                db_path=db_path,
            )
            logger.warning(
                f"[SCHEDULER][RETRY] Falha transitória na task {task_id} ({platform}): {err_msg}. "
                f"Reagendando tentativa {new_attempts}/3 para {_to_iso(next_retry)}"
            )
            return {
                "status": "retry_scheduled",
                "task_id": task_id,
                "platform": platform,
                "attempt": new_attempts,
                "next_attempt": _to_iso(next_retry),
                "error": err_msg,
            }
        else:
            with get_connection(db_path) as conn:
                conn.execute(
                    """
                    UPDATE scheduled_posts
                    SET status = 'failed', attempts = ?, last_error = ?
                    WHERE id = ?;
                    """,
                    (new_attempts, (err_msg or "")[:500], post_id),
                )
            _set_executor_status(
                state="error",
                message=f"Falha permanente ({platform})",
                last_result=f"Falha ({platform}): {(err_msg or '')[:100]}",
                last_cycle_summary=f"Falha no post {post_id} ({platform})",
                db_path=db_path,
            )
            logger.error(f"[SCHEDULER] Falha na publicação da task {task_id} ({platform}): {err_msg}. Marcada como failed.")
            return {
                "status": "failed",
                "task_id": task_id,
                "platform": platform,
                "error": err_msg,
            }


def _scheduler_worker_loop(interval_seconds: int = 30) -> None:
    """Loop contínuo em thread daemon para o executor do scheduler."""
    logger.info(f"[SCHEDULER][WORKER] Loop iniciado (pid={os.getpid()}, thread={threading.get_ident()})")
    while not _worker_stop_event.is_set():
        try:
            now_iso = _to_iso(datetime.now(timezone.utc))
            set_setting("executor_last_tick", now_iso)
            logger.info(f"[SCHEDULER][WORKER] tick (now={now_iso})")
            run_scheduler_cycle()

            # Fase V10-C: Ciclo leve de analytics reutilizando o Scheduler existente
            try:
                from app.services import analytics_scheduler
                analytics_scheduler.run_analytics_collection_cycle()
            except Exception as a_exc:
                logger.warning(f"[SCHEDULER][WORKER] Erro no ciclo de analytics (não fatal): {a_exc}")
        except Exception as exc:
            logger.exception(f"[SCHEDULER][WORKER] Erro inesperado no ciclo de execução: {exc}")
            _set_executor_status(state="error", message=f"Erro no worker: {exc}")
        _worker_stop_event.wait(interval_seconds)


def start_scheduler_worker(interval_seconds: int = 30) -> None:
    """Inicia a thread daemon singleton do executor em segundo plano se ainda não estiver ativa."""
    from app.services import operator_console
    if not operator_console.is_primary_instance():
        logger.info("[SCHEDULER] Worker daemon não iniciado: instância em modo VIEW ONLY.")
        return

    global _worker_thread
    with _worker_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return

        _worker_stop_event.clear()
        _worker_thread = threading.Thread(
            target=_scheduler_worker_loop,
            args=(interval_seconds,),
            name="SchedulerExecutionWorker",
            daemon=True,
        )
        _worker_thread.start()
        logger.info(f"[SCHEDULER] Worker daemon do executor iniciado (intervalo={interval_seconds}s)")


def stop_scheduler_worker() -> None:
    """Para a thread do worker daemon com segurança."""
    global _worker_thread
    with _worker_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            _worker_stop_event.set()
            _worker_thread = None
            logger.info("[SCHEDULER] Worker daemon do executor finalizado.")


def is_worker_alive() -> bool:
    """Informa se a thread do scheduler worker está em execução."""
    global _worker_thread
    with _worker_lock:
        return _worker_thread is not None and _worker_thread.is_alive()


WORKER_HEARTBEAT_STALE_SECONDS = 90
WORKER_SOURCE_IN_PROCESS_THREAD = "in_process_thread"
WORKER_SOURCE_PERSISTED_HEARTBEAT = "persisted_heartbeat"
WORKER_SOURCE_UNAVAILABLE = "unavailable"


def _read_persisted_heartbeat_readonly(
    db_path: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Tuple[Optional[str], Optional[int]]:
    """Lê de forma estritamente somente leitura o último tick do worker no SQLite e calcula a idade em segundos.

    Não cria arquivos, tabelas ou conexões de escrita.
    Retorna (last_tick_iso, age_seconds).
    """
    target_db = get_db_path(db_path)
    if not os.path.isfile(target_db):
        return None, None

    last_tick_str = None
    try:
        uri = f"file:{os.path.abspath(target_db)}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        try:
            cur = conn.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='autopilot_settings';"
            )
            if cur.fetchone()[0] > 0:
                row = conn.execute(
                    "SELECT value FROM autopilot_settings WHERE key = 'executor_last_tick';"
                ).fetchone()
                if row:
                    last_tick_str = row[0]
        finally:
            conn.close()
    except Exception:
        return None, None

    if not last_tick_str:
        return None, None

    now_utc = _normalize_utc(now)
    try:
        dt = _from_iso(last_tick_str)
        diff_sec = (now_utc - dt).total_seconds()
        age_seconds = max(0, int(diff_sec))
        return last_tick_str, age_seconds
    except Exception:
        # Timestamp corrompido ou inválido
        return last_tick_str, None


def get_worker_health(
    db_path: Optional[str] = None,
    stale_threshold_seconds: int = WORKER_HEARTBEAT_STALE_SECONDS,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Avalia a saúde e vivacidade do worker do scheduler tanto in-process quanto via persisted heartbeat.

    Regra de avaliação:
    1. IN-PROCESS: Se is_worker_alive() == True -> worker_alive = True (source: 'in_process_thread').
    2. EXTERNAL / FALLBACK: Se thread inativa em memória, lê executor_last_tick do SQLite.
       Se age_seconds <= stale_threshold_seconds -> worker_alive = True (source: 'persisted_heartbeat').
    3. Caso ausente, antigo (> threshold) ou inválido -> worker_alive = False (source: 'unavailable').

    Operação estritamente passiva e somente leitura.
    """
    # 1. Checagem In-Process
    if is_worker_alive():
        last_tick_iso, age_sec = _read_persisted_heartbeat_readonly(db_path, now=now)
        return {
            "worker_alive": True,
            "worker_health_source": WORKER_SOURCE_IN_PROCESS_THREAD,
            "worker_last_tick": last_tick_iso,
            "worker_last_tick_age_seconds": age_sec,
        }

    # 2. Fallback Externo (persisted heartbeat)
    last_tick_iso, age_sec = _read_persisted_heartbeat_readonly(db_path, now=now)
    if last_tick_iso is not None and age_sec is not None and age_sec <= stale_threshold_seconds:
        return {
            "worker_alive": True,
            "worker_health_source": WORKER_SOURCE_PERSISTED_HEARTBEAT,
            "worker_last_tick": last_tick_iso,
            "worker_last_tick_age_seconds": age_sec,
        }

    return {
        "worker_alive": False,
        "worker_health_source": WORKER_SOURCE_UNAVAILABLE,
        "worker_last_tick": last_tick_iso,
        "worker_last_tick_age_seconds": age_sec,
    }


# ---------------------------------------------------------------------------
# Homologação & Teste Rápido (Apenas para ambiente de testes/validação)
# ---------------------------------------------------------------------------

ALLOWED_TEST_RESCHEDULE_MINUTES = (2, 5, 10)


def reschedule_post_for_test(
    scheduled_post_id: int,
    minutes_from_now: int,
    db_path: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """[HOMOLOGAÇÃO/TEST] Reagenda um post planejado existente para daqui a poucos minutos.

    Regras estritas de segurança e idempotência:
    - Aceita apenas intervalos de 2, 5 ou 10 minutos.
    - Valida que o post existe no SQLite.
    - Rejeita posts com status 'published', 'cancelled', 'processing' ou 'failed'.
    - Atualiza somente o scheduled_at e limpa next_attempt_at do registro com id especificado.
    - Mantém status como 'ready' para elegibilidade imediata pelo worker.
    - NÃO cria novo scheduled_post.
    - NÃO chama Upload-Post nem gera publication_events.
    - Não altera horários dos demais posts.
    """
    from app.services import operator_console
    operator_console.require_primary_instance(db_path=db_path)

    if minutes_from_now not in ALLOWED_TEST_RESCHEDULE_MINUTES:

        return {
            "success": False,
            "error": "invalid_interval",
            "message": f"Intervalo inválido: {minutes_from_now}. Permitidos apenas: {ALLOWED_TEST_RESCHEDULE_MINUTES}",
        }

    init_db(db_path)
    with get_connection(db_path) as conn:
        post = conn.execute(
            """
            SELECT id, task_id, platform, scheduled_at, status, next_attempt_at
            FROM scheduled_posts
            WHERE id = ?;
            """,
            (scheduled_post_id,),
        ).fetchone()

        if not post:
            return {
                "success": False,
                "error": "not_found",
                "message": f"Post agendado id={scheduled_post_id} não encontrado",
            }

        curr_status = post["status"]
        if curr_status not in (STATUS_PLANNED, STATUS_READY):
            return {
                "success": False,
                "error": "invalid_status",
                "status": curr_status,
                "message": f"Post id={scheduled_post_id} possui status '{curr_status}' e não pode ser reagendado",
            }

        base_time = _normalize_utc(now)
        new_dt = base_time + timedelta(minutes=minutes_from_now)
        new_iso = _to_iso(new_dt)
        target_tz = now.tzinfo if (now and now.tzinfo) else None
        local_dt = to_local_datetime(new_dt, target_tz=target_tz)

        conn.execute(
            """
            UPDATE scheduled_posts
            SET scheduled_at = ?, next_attempt_at = NULL, status = 'ready'
            WHERE id = ? AND status IN ('planned', 'ready');
            """,
            (new_iso, scheduled_post_id),
        )

        logger.info(
            f"[SCHEDULER][TEST] Post {scheduled_post_id} ({post['task_id']} - {post['platform']}) "
            f"reagendado para {new_iso} (+{minutes_from_now} min)"
        )

        return {
            "success": True,
            "id": scheduled_post_id,
            "task_id": post["task_id"],
            "platform": post["platform"],
            "new_scheduled_at": new_iso,
            "new_scheduled_at_dt": new_dt,
            "new_scheduled_at_local": local_dt,
        }
