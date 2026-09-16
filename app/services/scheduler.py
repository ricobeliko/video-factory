import os
import sqlite3
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
STATUS_PUBLISHED = "published"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

ACTIVE_SCHEDULE_STATUSES = (STATUS_PLANNED, STATUS_READY)


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
                created_at TEXT NOT NULL
            );
            """
        )

        # Índice único para evitar agendamento duplicado da mesma tarefa e plataforma
        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_active_schedule
            ON scheduled_posts(task_id, platform)
            WHERE status IN ('planned', 'ready', 'published');
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
                error_code TEXT
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


def get_all_settings(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Retorna todas as configurações com seus devidos tipos e defaults."""
    init_db(db_path)
    return {
        "tiktok_enabled": get_setting("tiktok_enabled", "true", db_path).lower() == "true",
        "tiktok_limit_24h": int(get_setting("tiktok_limit_24h", str(DEFAULT_TIKTOK_LIMIT), db_path)),
        "youtube_enabled": get_setting("youtube_enabled", "true", db_path).lower() == "true",
        "youtube_limit_24h": int(get_setting("youtube_limit_24h", str(DEFAULT_YOUTUBE_LIMIT), db_path)),
        "estoque_desejado": int(get_setting("estoque_desejado", str(DEFAULT_DESIRED_STOCK), db_path)),
        "scheduler_enabled": get_setting("scheduler_enabled", "false", db_path).lower() == "true",
    }


def save_settings(settings: Dict[str, Any], db_path: Optional[str] = None) -> None:
    """Atualiza múltiplas configurações."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        for k, v in settings.items():
            conn.execute(
                """
                INSERT INTO autopilot_settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value;
                """,
                (k, str(v)),
            )


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
# Janela Móvel de 24h e Limites
# ---------------------------------------------------------------------------

def _to_iso(dt: datetime) -> str:
    """Converte datetime para string ISO 8601 UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _from_iso(iso_str: str) -> datetime:
    """Converte string ISO 8601 para datetime UTC."""
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_platform_rate_limits(
    platform: str,
    db_path: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Calcula a janela móvel de 24 horas para uma plataforma específica.
    
    Regra:
    - posts_publicados_ultimas_24h: publicações com status='success' nos últimos 24h (published_at >= now - 24h e <= now)
    - posts_agendados_proximas_24h: posts agendados ativos (status IN ('planned', 'ready')) agendados entre now e now + 24h
    - usados_janela: posts_publicados_ultimas_24h + posts_agendados_proximas_24h
    - disponiveis: max(0, limite_configurado - usados_janela)
    """
    init_db(db_path)
    current_time = now or datetime.now(timezone.utc)
    window_past = current_time - timedelta(hours=24)
    window_future = current_time + timedelta(hours=24)

    iso_past = _to_iso(window_past)
    iso_now = _to_iso(current_time)
    iso_future = _to_iso(window_future)

    settings = get_all_settings(db_path)
    clean_platform = platform.lower().strip()

    if clean_platform == "tiktok":
        limit = settings["tiktok_limit_24h"]
        enabled = settings["tiktok_enabled"]
    elif clean_platform == "youtube":
        limit = settings["youtube_limit_24h"]
        enabled = settings["youtube_enabled"]
    else:
        limit = 10
        enabled = True

    with get_connection(db_path) as conn:
        # Publicações das últimas 24h
        pub_row = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM publication_events
            WHERE platform = ? AND status = 'success'
            AND published_at >= ? AND published_at <= ?;
            """,
            (clean_platform, iso_past, iso_now),
        ).fetchone()
        used_past = pub_row["cnt"] if pub_row else 0

        # Posts já agendados para a janela próxima de 24h
        sched_row = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM scheduled_posts
            WHERE platform = ? AND status IN ('planned', 'ready')
            AND scheduled_at >= ? AND scheduled_at <= ?;
            """,
            (clean_platform, iso_now, iso_future),
        ).fetchone()
        scheduled_count = sched_row["cnt"] if sched_row else 0

    total_used = used_past + scheduled_count
    available_slots = max(0, limit - total_used) if enabled else 0

    return {
        "platform": clean_platform,
        "enabled": enabled,
        "limit": limit,
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
    db_path: Optional[str] = None,
) -> None:
    """Registra um evento de publicação (usado pelo publicador manual ou testes)."""
    init_db(db_path)
    pub_time = published_at or datetime.now(timezone.utc)
    iso_time = _to_iso(pub_time)
    clean_platform = platform.lower().strip()

    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO publication_events (task_id, platform, published_at, status, external_id, error_code)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (task_id, clean_platform, iso_time, status, external_id, error_code),
        )
        if status == "success":
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
    """Retorna os próximos posts agendados ativos ordenados cronologicamente."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, task_id, platform, scheduled_at, status, created_at
            FROM scheduled_posts
            WHERE status IN ('planned', 'ready')
            ORDER BY scheduled_at ASC
            LIMIT ?;
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def plan_schedule(
    tasks: List[Dict[str, Any]],
    now: Optional[datetime] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Gera o planejamento da agenda para vídeos concluídos ainda não agendados.
    
    Regras estritas:
    - Apenas vídeos concluídos (state == TASK_STATE_COMPLETE ou has_video)
    - Não agenda PROCESSING, PENDING, FAILED ou já publicados
    - Respeita os limites por rede na janela móvel de 24h
    - Distribui horários uniformemente ao longo do período
    - Idempotência: não duplica (task_id, platform) já agendada ou publicada
    - NÃO chama Upload-Post
    """
    init_db(db_path)
    current_time = now or datetime.now(timezone.utc)
    persisted_platforms_map = get_all_task_platforms(db_path)
    settings = get_all_settings(db_path)

    # 1. Filtra tarefas elegíveis
    eligible_tasks: List[Tuple[str, Dict[str, Any], List[str]]] = []
    for t in tasks:
        task_id = t.get("task_id", "")
        if not task_id:
            continue

        state = t.get("state")
        cross_post_state = t.get("cross_post_state")
        has_video = bool(t.get("video_file"))

        # Ignora estados não concluídos
        if state in (const.TASK_STATE_PROCESSING, const.TASK_STATE_PENDING, const.TASK_STATE_FAILED):
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

        eligible_tasks.append((task_id, t, [p.lower().strip() for p in platforms]))

    if not eligible_tasks:
        return []

    created_schedule: List[Dict[str, Any]] = []

    # 2. Processa por plataforma para manter cadência individual uniforme
    for platform in ("tiktok", "youtube"):
        rate_info = get_platform_rate_limits(platform, db_path, current_time)
        if not rate_info["enabled"]:
            continue

        available_slots = rate_info["available_slots"]
        if available_slots <= 0:
            continue

        limit_24h = rate_info["limit"]
        # Intervalo uniforme: 24h (86400s) / limite diário
        interval_seconds = max(60, int(86400 / max(1, limit_24h)))

        # Encontra o último horário agendado existente para essa plataforma
        with get_connection(db_path) as conn:
            last_row = conn.execute(
                """
                SELECT MAX(scheduled_at) AS max_time FROM scheduled_posts
                WHERE platform = ? AND status IN ('planned', 'ready');
                """,
                (platform,),
            ).fetchone()

        if last_row and last_row["max_time"]:
            try:
                last_dt = _from_iso(last_row["max_time"])
                base_slot = max(current_time, last_dt + timedelta(seconds=interval_seconds))
            except Exception:
                base_slot = current_time + timedelta(seconds=interval_seconds)
        else:
            base_slot = current_time + timedelta(seconds=interval_seconds)

        # Enfileira slots para as tasks elegíveis que possuem esta plataforma
        current_slot = base_slot
        for task_id, task_data, platforms in eligible_tasks:
            if available_slots <= 0:
                break
            if platform not in platforms:
                continue

            # Verifica idempotência: se já existe para esta task_id e platform
            with get_connection(db_path) as conn:
                existing = conn.execute(
                    """
                    SELECT id FROM scheduled_posts
                    WHERE task_id = ? AND platform = ?
                    AND status IN ('planned', 'ready', 'published');
                    """,
                    (task_id, platform),
                ).fetchone()
                if existing:
                    continue

                # Insere novo slot planejado
                iso_slot = _to_iso(current_slot)
                iso_created = _to_iso(current_time)
                cursor = conn.execute(
                    """
                    INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at)
                    VALUES (?, ?, ?, 'planned', ?);
                    """,
                    (task_id, platform, iso_slot, iso_created),
                )
                new_id = cursor.lastrowid

            record = {
                "id": new_id,
                "task_id": task_id,
                "platform": platform,
                "scheduled_at": iso_slot,
                "status": STATUS_PLANNED,
                "subject": task_data.get("subject", task_id),
            }
            created_schedule.append(record)
            available_slots -= 1
            current_slot += timedelta(seconds=interval_seconds)

    return created_schedule
