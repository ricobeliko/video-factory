"""
Analytics Collection Scheduler Service.
Fase V10-C — Automatic Analytics Collection Scheduler.

Responsável por automatizar a coleta periódica de métricas de publicações
existentes com política de coleta conservadora por idade da publicação,
respeito a rate limits globais por plataforma, backoff por tipo de erro,
idempotência e total isolamento de falhas.
"""
from datetime import datetime, timedelta, timezone
import json
import os
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from app.models import const
from app.services import analytics, analytics_ingestion
from app.services.analytics_providers import (
    AnalyticsProviderError,
    ERR_AUTH,
    ERR_INVALID_RESPONSE,
    ERR_NOT_FOUND,
    ERR_RATE_LIMIT,
    ERR_TEMPORARY,
    ERR_UNAVAILABLE,
    get_provider,
    validate_provider_configuration,
)
from app.services import operator_console, profile_manager, scheduler

# ---------------------------------------------------------------------------
# Constantes e Políticas
# ---------------------------------------------------------------------------

DEFAULT_ANALYTICS_AUTO_COLLECTION_ENABLED = False
DEFAULT_ANALYTICS_MAX_FETCHES_PER_CYCLE = 3
SUPPORTED_ANALYTICS_PLATFORMS = ("youtube", "tiktok")

# Throttle mínimo entre ciclos automáticos (Hotfix V10-C)
ANALYTICS_CYCLE_MIN_INTERVAL_SECONDS = 300  # 5 minutos

# Cooldowns por idade da publicação (em segundos)
# 0–6h: 60 min (3600s)
# 6–24h: 3h (10800s)
# 1–3d (24-72h): 6h (21600s)
# 3–7d (72-168h): 12h (43200s)
# 7–30d (168-720h): 24h (86400s)
# >30d: None (não coletar automaticamente)
COOLDOWN_0_6H = 60 * 60         # 1h
COOLDOWN_6_24H = 3 * 3600       # 3h
COOLDOWN_1_3D = 6 * 3600        # 6h
COOLDOWN_3_7D = 12 * 3600       # 12h
COOLDOWN_7_30D = 24 * 3600      # 24h

# Backoff durations por tipo de erro (em segundos)
BACKOFF_DURATIONS: Dict[str, int] = {
    ERR_AUTH: 24 * 3600,             # 24h
    ERR_RATE_LIMIT: 6 * 3600,        # 6h
    ERR_TEMPORARY: 15 * 60,          # 15m
    ERR_NOT_FOUND: 6 * 3600,         # 6h
    ERR_UNAVAILABLE: 15 * 60,        # 15m
    ERR_INVALID_RESPONSE: 15 * 60,   # 15m
}

# Limites globais conservadores por plataforma (máximo técnico interno por janela de 1h)
DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 3600
DEFAULT_PLATFORM_HOURLY_LIMITS: Dict[str, int] = {
    "youtube": 30,
    "tiktok": 30,
}


def _normalize_utc(dt_val: Optional[Any]) -> datetime:
    """Converte qualquer datetime ou ISO string para datetime UTC consciente."""
    if dt_val is None:
        return datetime.now(timezone.utc)
    if isinstance(dt_val, datetime):
        if dt_val.tzinfo is None:
            return dt_val.replace(tzinfo=timezone.utc)
        return dt_val.astimezone(timezone.utc)
    if isinstance(dt_val, str):
        clean_str = dt_val.strip()
        if clean_str.endswith("Z"):
            clean_str = clean_str[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(clean_str)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc)


def _to_iso(dt_val: datetime) -> str:
    """Serializa datetime UTC para ISO 8601 com sufixo +00:00."""
    return dt_val.astimezone(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Configurações Persistidas do Analytics Scheduler
# ---------------------------------------------------------------------------

def is_analytics_auto_collection_enabled(db_path: Optional[str] = None) -> bool:
    """Verifica se a coleta automática de analytics está ativada."""
    val = scheduler.get_setting("analytics_auto_collection_enabled", "False", db_path=db_path)
    return str(val).lower() in ("true", "1", "yes")


def set_analytics_auto_collection_enabled(
    enabled: bool,
    db_path: Optional[str] = None,
) -> None:
    """Ativa ou desativa a coleta automática de analytics."""
    scheduler.set_setting("analytics_auto_collection_enabled", str(bool(enabled)), db_path=db_path)
    logger.info(f"[ANALYTICS_SCHEDULER] analytics_auto_collection_enabled definido como {bool(enabled)}")


def get_analytics_max_fetches_per_cycle(db_path: Optional[str] = None) -> int:
    """Retorna o teto máximo de coletas por ciclo."""
    val = scheduler.get_setting(
        "analytics_max_fetches_per_cycle",
        str(DEFAULT_ANALYTICS_MAX_FETCHES_PER_CYCLE),
        db_path=db_path,
    )
    try:
        int_val = int(val)
        return max(1, int_val)
    except Exception:
        return DEFAULT_ANALYTICS_MAX_FETCHES_PER_CYCLE


def set_analytics_max_fetches_per_cycle(
    max_fetches: int,
    db_path: Optional[str] = None,
) -> None:
    """Define o teto de coletas por ciclo."""
    clean_val = max(1, int(max_fetches))
    scheduler.set_setting("analytics_max_fetches_per_cycle", str(clean_val), db_path=db_path)


def get_analytics_cycle_min_interval_seconds(db_path: Optional[str] = None) -> int:
    """Retorna o intervalo mínimo em segundos entre ciclos automáticos (padrão 300s)."""
    val = scheduler.get_setting(
        "analytics_cycle_min_interval_seconds",
        str(ANALYTICS_CYCLE_MIN_INTERVAL_SECONDS),
        db_path=db_path,
    )
    try:
        return max(1, int(val))
    except Exception:
        return ANALYTICS_CYCLE_MIN_INTERVAL_SECONDS


def set_analytics_cycle_min_interval_seconds(
    interval_seconds: int,
    db_path: Optional[str] = None,
) -> None:
    """Define o intervalo mínimo em segundos entre ciclos automáticos."""
    clean_val = max(1, int(interval_seconds))
    scheduler.set_setting("analytics_cycle_min_interval_seconds", str(clean_val), db_path=db_path)



# ---------------------------------------------------------------------------
# Política de Coleta por Idade (Cooldown determinístico)
# ---------------------------------------------------------------------------

def calculate_minimum_cooldown(age_seconds: float) -> Optional[int]:
    """
    Retorna o cooldown mínimo (em segundos) entre snapshots com base na idade
    da publicação:
    0–6h: 60 min (3600s)
    6–24h: 3h (10800s)
    1–3 dias (24–72h): 6h (21600s)
    3–7 dias (72–168h): 12h (43200s)
    7–30 dias (168–720h): 24h (86400s)
    >30 dias: None (não coletar automaticamente)
    """
    if age_seconds < 0:
        age_seconds = 0

    hours = age_seconds / 3600.0

    if hours < 6.0:
        return COOLDOWN_0_6H
    elif hours < 24.0:
        return COOLDOWN_6_24H
    elif hours < 72.0:
        return COOLDOWN_1_3D
    elif hours < 168.0:
        return COOLDOWN_3_7D
    elif hours <= 720.0:
        return COOLDOWN_7_30D
    else:
        return None  # > 30 dias


# ---------------------------------------------------------------------------
# Backoff por Provedor / Plataforma
# ---------------------------------------------------------------------------

def get_provider_backoff(
    platform: str,
    now: Optional[datetime] = None,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Verifica se a plataforma/provedor está em período de backoff.
    Retorna detalhes do backoff se ativo, ou None se livre.
    """
    clean_platform = (platform or "").strip().lower()
    until_iso = scheduler.get_setting(f"analytics_backoff_{clean_platform}_until", None, db_path=db_path)
    if not until_iso:
        return None

    current_time = _normalize_utc(now)
    until_dt = _normalize_utc(until_iso)

    if current_time < until_dt:
        reason = scheduler.get_setting(f"analytics_backoff_{clean_platform}_reason", "UNKNOWN", db_path=db_path)
        remaining_seconds = max(0, int((until_dt - current_time).total_seconds()))
        return {
            "platform": clean_platform,
            "reason": reason,
            "until": until_iso,
            "remaining_seconds": remaining_seconds,
        }
    else:
        # Expirou: limpa os registros
        scheduler.set_setting(f"analytics_backoff_{clean_platform}_until", "", db_path=db_path)
        scheduler.set_setting(f"analytics_backoff_{clean_platform}_reason", "", db_path=db_path)
        return None


def set_provider_backoff(
    platform: str,
    reason: str,
    duration_seconds: Optional[int] = None,
    now: Optional[datetime] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Registra um período de backoff para o provedor/plataforma no SQLite.
    Gera evento operacional sem expor segredos.
    """
    clean_platform = (platform or "").strip().lower()
    clean_reason = (reason or "UNKNOWN").strip().upper()

    if duration_seconds is None:
        duration_seconds = BACKOFF_DURATIONS.get(clean_reason, 15 * 60)

    current_time = _normalize_utc(now)
    until_dt = current_time + timedelta(seconds=duration_seconds)
    until_iso = _to_iso(until_dt)

    scheduler.set_setting(f"analytics_backoff_{clean_platform}_until", until_iso, db_path=db_path)
    scheduler.set_setting(f"analytics_backoff_{clean_platform}_reason", clean_reason, db_path=db_path)

    # Evento operacional seguro
    event_type = "ANALYTICS_AUTH_BLOCK" if clean_reason == ERR_AUTH else "ANALYTICS_PROVIDER_BACKOFF"
    severity = "CRITICAL" if clean_reason == ERR_AUTH else "WARNING"
    operator_console.log_operational_event(
        component="analytics",
        severity=severity,
        event_type=event_type,
        message=f"Provider '{clean_platform}' em backoff por {duration_seconds}s. Motivo: {clean_reason}.",
        metadata={
            "platform": clean_platform,
            "reason": clean_reason,
            "duration_seconds": duration_seconds,
            "backoff_until": until_iso,
        },
        db_path=db_path,
    )

    logger.warning(
        f"[ANALYTICS_SCHEDULER] Provider '{clean_platform}' em backoff até {until_iso} "
        f"(motivo={clean_reason}, duração={duration_seconds}s)"
    )

    return {
        "platform": clean_platform,
        "reason": clean_reason,
        "until": until_iso,
        "duration_seconds": duration_seconds,
    }


def clear_provider_backoff(
    platform: str,
    db_path: Optional[str] = None,
) -> None:
    """Remove manualmente o backoff de uma plataforma."""
    clean_platform = (platform or "").strip().lower()
    scheduler.set_setting(f"analytics_backoff_{clean_platform}_until", "", db_path=db_path)
    scheduler.set_setting(f"analytics_backoff_{clean_platform}_reason", "", db_path=db_path)


# ---------------------------------------------------------------------------
# Rate Limiting Global por Provedor / Plataforma
# ---------------------------------------------------------------------------

def check_and_increment_rate_limit(
    platform: str,
    max_per_window: Optional[int] = None,
    window_seconds: int = DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
    now: Optional[datetime] = None,
    db_path: Optional[str] = None,
) -> bool:
    """
    Verifica se o rate limit global para a plataforma/provedor foi atingido.
    Múltiplos profiles/canais compartilham o mesmo teto global.
    Retorna True se a chamada é permitida e incrementa o contador.
    Retorna False se o limite foi atingido.
    """
    clean_platform = (platform or "").strip().lower()
    current_time = _normalize_utc(now)
    now_iso = _to_iso(current_time)

    if max_per_window is None:
        max_per_window = DEFAULT_PLATFORM_HOURLY_LIMITS.get(clean_platform, 30)

    start_iso = scheduler.get_setting(f"analytics_rl_start_{clean_platform}", None, db_path=db_path)
    count_str = scheduler.get_setting(f"analytics_rl_count_{clean_platform}", "0", db_path=db_path)

    try:
        count = int(count_str)
    except Exception:
        count = 0

    if not start_iso:
        # Primeira chamada
        scheduler.set_setting(f"analytics_rl_start_{clean_platform}", now_iso, db_path=db_path)
        scheduler.set_setting(f"analytics_rl_count_{clean_platform}", "1", db_path=db_path)
        return True

    start_dt = _normalize_utc(start_iso)
    elapsed = (current_time - start_dt).total_seconds()

    if elapsed >= window_seconds:
        # Nova janela
        scheduler.set_setting(f"analytics_rl_start_{clean_platform}", now_iso, db_path=db_path)
        scheduler.set_setting(f"analytics_rl_count_{clean_platform}", "1", db_path=db_path)
        return True

    if count >= max_per_window:
        logger.warning(
            f"[ANALYTICS_SCHEDULER] Rate limit global atingido para '{clean_platform}': "
            f"{count}/{max_per_window} na janela de {window_seconds}s"
        )
        operator_console.log_operational_event(
            component="analytics",
            severity="WARNING",
            event_type="ANALYTICS_RATE_LIMIT_BLOCK",
            message=f"Rate limit global da plataforma '{clean_platform}' atingido ({count}/{max_per_window}).",
            metadata={
                "platform": clean_platform,
                "current_count": count,
                "max_per_window": max_per_window,
            },
            db_path=db_path,
        )
        return False

    # Incrementa contador na mesma janela
    scheduler.set_setting(f"analytics_rl_count_{clean_platform}", str(count + 1), db_path=db_path)
    return True


# ---------------------------------------------------------------------------
# Snapshot Age & Analytics Lookup Helper (Seção 6)
# ---------------------------------------------------------------------------

def get_publication_latest_analytics(
    task_id: str,
    platform: str,
    channel_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Retorna metadados agregados e o snapshot mais recente de uma publicação:
    - last_snapshot_at
    - snapshot_count
    - latest_source
    - latest_views
    - latest_performance_score
    """
    clean_task_id = str(task_id or "").strip()
    clean_platform = str(platform or "").strip().lower()

    analytics.init_analytics_db(db_path)

    with analytics.get_connection(db_path) as conn:
        # 1. Contagem e data mais recente
        if channel_id:
            summary_query = """
                SELECT COUNT(*) AS cnt, MAX(collected_at) AS max_collected
                FROM content_analytics
                WHERE task_id = ? AND platform = ? AND channel_id = ?;
            """
            summary_row = conn.execute(summary_query, (clean_task_id, clean_platform, str(channel_id))).fetchone()
            latest_query = """
                SELECT collected_at, source, views, performance_score
                FROM content_analytics
                WHERE task_id = ? AND platform = ? AND channel_id = ?
                ORDER BY collected_at DESC, id DESC
                LIMIT 1;
            """
            latest_row = conn.execute(latest_query, (clean_task_id, clean_platform, str(channel_id))).fetchone()
        else:
            summary_query = """
                SELECT COUNT(*) AS cnt, MAX(collected_at) AS max_collected
                FROM content_analytics
                WHERE task_id = ? AND platform = ?;
            """
            summary_row = conn.execute(summary_query, (clean_task_id, clean_platform)).fetchone()
            latest_query = """
                SELECT collected_at, source, views, performance_score
                FROM content_analytics
                WHERE task_id = ? AND platform = ?
                ORDER BY collected_at DESC, id DESC
                LIMIT 1;
            """
            latest_row = conn.execute(latest_query, (clean_task_id, clean_platform)).fetchone()

    count = summary_row["cnt"] if summary_row else 0
    last_collected = summary_row["max_collected"] if (summary_row and summary_row["max_collected"]) else None

    latest_source = latest_row["source"] if latest_row else None
    latest_views = latest_row["views"] if latest_row else None
    latest_perf_score = latest_row["performance_score"] if latest_row else None

    return {
        "task_id": clean_task_id,
        "platform": clean_platform,
        "channel_id": channel_id,
        "snapshot_count": count,
        "last_snapshot_at": last_collected,
        "latest_source": latest_source,
        "latest_views": latest_views,
        "latest_performance_score": latest_perf_score,
    }


# ---------------------------------------------------------------------------
# Verificação de Privacidade Conhecida (Seção 5)
# ---------------------------------------------------------------------------

def is_publication_known_private(
    task_id: str,
    platform: str,
    db_path: Optional[str] = None,
) -> bool:
    """
    Verifica se o conteúdo é sabidamente 'private'.
    No YouTube, vídeos privados não são acessíveis via API Key pública.
    Se a privacidade for 'private' comprovada nos metadados da tarefa, ignora
    automaticamente para não desperdiçar cota. Se desconhecida, não inventa.
    """
    clean_platform = str(platform or "").strip().lower()
    if clean_platform != "youtube":
        return False

    clean_tid = str(task_id or "").strip()
    if not clean_tid:
        return False

    try:
        from app.utils import utils
        storage_folder = utils.storage_dir(create=False)
        task_json_path = os.path.join(storage_folder, "tasks", clean_tid, "task.json")
        if os.path.exists(task_json_path):
            with open(task_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                privacy = (
                    data.get("params", {}).get("youtube_privacy_status")
                    or data.get("publish_info", {}).get("youtube_privacy_status")
                    or data.get("publish_info", {}).get("privacy")
                    or data.get("privacy")
                )
                if privacy and str(privacy).strip().lower() == "private":
                    return True
    except Exception:
        pass

    return False


# ---------------------------------------------------------------------------
# Elegibilidade de Publicação (Seção 4)
# ---------------------------------------------------------------------------

def check_publication_eligibility(
    pub_row: Dict[str, Any],
    now: Optional[datetime] = None,
    db_path: Optional[str] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Avalia rigorosamente a elegibilidade de uma publicação para coleta de analytics.
    Retorna: (is_eligible, reason, latest_analytics_info)
    """
    current_time = _normalize_utc(now)

    # 1. Status deve ser 'success'
    status = (pub_row.get("status") or "").strip().lower()
    if status != "success":
        return False, f"status_not_success ({status})", None

    # 2. external_post_id presente
    ext_id = pub_row.get("external_id")
    if not ext_id or not str(ext_id).strip():
        return False, "missing_external_id", None

    # 3. Plataforma suportada
    platform = (pub_row.get("platform") or "").strip().lower()
    if platform not in SUPPORTED_ANALYTICS_PLATFORMS:
        return False, f"unsupported_platform ({platform})", None

    # 4. Profile ativo
    task_id = str(pub_row.get("task_id") or "").strip()
    profile_id = pub_row.get("profile_id")
    if not profile_id:
        try:
            profile_id = profile_manager.get_task_profile_id(task_id, db_path=db_path)
        except Exception:
            profile_id = "default"

    prof = profile_manager.get_profile(profile_id, db_path=db_path)
    if prof and not prof.get("is_active"):
        return False, f"profile_inactive ({profile_id})", None

    # 5. Canal habilitado (se especificado)
    channel_id = pub_row.get("channel_id")
    if channel_id:
        ch = profile_manager.get_channel(channel_id, db_path=db_path)
        if ch and not ch.get("is_enabled"):
            return False, f"channel_disabled ({channel_id})", None

    # 6. Provedor configurado
    config_validation = validate_provider_configuration(platform, db_path=db_path)
    if not config_validation.get("configured"):
        return False, f"provider_not_configured ({platform})", None

    # 7. Provedor fora de backoff
    backoff = get_provider_backoff(platform, now=current_time, db_path=db_path)
    if backoff is not None:
        return False, f"provider_in_backoff ({backoff['reason']})", None

    # 8. Verificação de YouTube sabidamente privado
    if is_publication_known_private(task_id, platform, db_path=db_path):
        return False, "private_youtube_skipped", None

    # 9. Janela de idade (publicação deve ter <= 30 dias)
    published_at_str = pub_row.get("published_at")
    if not published_at_str:
        return False, "missing_published_at", None

    published_at_dt = _normalize_utc(published_at_str)
    age_seconds = (current_time - published_at_dt).total_seconds()
    if age_seconds < 0:
        age_seconds = 0

    min_cooldown = calculate_minimum_cooldown(age_seconds)
    if min_cooldown is None:
        return False, "exceeds_max_age_30d", None

    # 10. Intervalo mínimo desde o último snapshot
    analytics_info = get_publication_latest_analytics(
        task_id=task_id,
        platform=platform,
        channel_id=channel_id,
        db_path=db_path,
    )

    last_snapshot_at = analytics_info.get("last_snapshot_at")
    if last_snapshot_at:
        last_snap_dt = _normalize_utc(last_snapshot_at)
        elapsed_since_snap = (current_time - last_snap_dt).total_seconds()
        if elapsed_since_snap < min_cooldown:
            remaining_cooldown = int(min_cooldown - elapsed_since_snap)
            return False, f"cooldown_active ({remaining_cooldown}s remaining)", analytics_info

    # Elegível!
    return True, "eligible", analytics_info


# ---------------------------------------------------------------------------
# Descoberta e Ordenação de Candidatos (Seção 7)
# ---------------------------------------------------------------------------

def get_eligible_analytics_candidates(
    limit: Optional[int] = None,
    now: Optional[datetime] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Descobre e ordena publicações elegíveis para coleta neste ciclo:
    Ordenação estrita:
    1. Publicação elegível sem snapshot (first snapshot)
    2. Snapshot mais antigo (last_snapshot_at ASC)
    3. Publicação mais recente dentro da janela útil (published_at DESC)
    """
    if limit is None:
        limit = get_analytics_max_fetches_per_cycle(db_path=db_path)

    current_time = _normalize_utc(now)
    scheduler.init_db(db_path)

    with scheduler.get_connection(db_path) as conn:
        # Busca todas as publicações com status 'success' e external_id preenchido
        cursor = conn.execute(
            """
            SELECT id, task_id, platform, published_at, status, external_id,
                   provider_request_id, profile_id, channel_id, external_url
            FROM publication_events
            WHERE status = 'success'
              AND external_id IS NOT NULL
              AND TRIM(external_id) != ''
            ORDER BY id DESC;
            """
        )
        rows = [dict(r) for r in cursor.fetchall()]

    candidates = []
    for row in rows:
        is_eligible, reason, a_info = check_publication_eligibility(row, now=current_time, db_path=db_path)
        if is_eligible:
            candidate_entry = dict(row)
            candidate_entry["latest_analytics"] = a_info
            candidate_entry["last_snapshot_at"] = a_info.get("last_snapshot_at") if a_info else None
            candidates.append(candidate_entry)

    # Ordenação:
    # 1. Sem snapshot primeiro (0 para None, 1 para quem tem snapshot)
    # 2. last_snapshot_at ASC (mais antigo primeiro)
    # 3. published_at DESC (mais recente primeiro)
    def sort_key(c: Dict[str, Any]):
        has_snapshot = 0 if c["last_snapshot_at"] is None else 1
        snap_time = c["last_snapshot_at"] or ""
        # published_at decrescente: invertemos a string ISO para ordenação lexicográfica decrescente
        pub_time = c.get("published_at") or ""
        return (has_snapshot, snap_time, "".join(chr(255 - ord(ch)) for ch in pub_time))

    candidates.sort(key=sort_key)
    return candidates[:limit]


# ---------------------------------------------------------------------------
# Ciclo Principal de Coleta (Seção 2, 10, 11, 12, 13, 14)
# ---------------------------------------------------------------------------

def run_analytics_collection_cycle(
    db_path: Optional[str] = None,
    now: Optional[datetime] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Executa um ciclo leve de coleta de analytics:
    - Respeita PRIMARY guard
    - Respeita Factory Paused guard
    - Respeita auto_collection_enabled (a menos que force=True para teste manual)
    - Limite de até MAX_ANALYTICS_FETCHES_PER_CYCLE
    - Rate limit e backoff por provedor
    - Total isolamento de falhas (falha de analytics nunca altera task ou publicação)
    """
    current_time = _normalize_utc(now)
    now_iso = _to_iso(current_time)
    scheduler.init_db(db_path)

    # 1. PRIMARY Guard (Seção 13)
    if not operator_console.is_primary_instance(db_path=db_path):
        logger.info("[ANALYTICS_SCHEDULER] Ciclo ignorado: instância em modo SECONDARY_VIEW_ONLY.")
        return {
            "status": "skipped",
            "reason": "secondary_view_only",
            "message": "Instância secundária (somente leitura): coleta automática desativada",
        }

    # 2. PAUSED Factory Guard (Seção 14)
    if operator_console.is_factory_paused(db_path=db_path):
        logger.info("[ANALYTICS_SCHEDULER] Ciclo ignorado: fábrica pausada (PAUSED).")
        return {
            "status": "skipped",
            "reason": "factory_paused",
            "message": "Fábrica pausada: coleta automática de analytics suspensa",
        }

    # 3. Auto-collection enabled guard (Seção 15)
    enabled = is_analytics_auto_collection_enabled(db_path=db_path)
    if not enabled and not force:
        logger.info("[ANALYTICS_SCHEDULER] Ciclo ignorado: coleta automática desativada.")
        return {
            "status": "skipped",
            "reason": "disabled",
            "message": "Coleta automática de analytics desativada",
        }

    # 4. Throttle de Ciclo Automático (Hotfix V10-C)
    # Garante que o ciclo automático só executa a cada >= 300s, mesmo com o worker acordando a cada 30s.
    # Run One Cycle Now (force=True) ignora SOMENTE o throttle de 300s.
    if not force:
        cycle_interval = get_analytics_cycle_min_interval_seconds(db_path=db_path)
        last_auto_cycle_iso = scheduler.get_setting("analytics_last_auto_cycle_at", None, db_path=db_path)
        if last_auto_cycle_iso:
            try:
                last_auto_dt = _normalize_utc(last_auto_cycle_iso)
                elapsed_cycle = (current_time - last_auto_dt).total_seconds()
                if elapsed_cycle < cycle_interval:
                    remaining_throttle = max(0, int(cycle_interval - elapsed_cycle))
                    logger.debug(
                        f"[ANALYTICS_SCHEDULER] Ciclo automático em throttle ({remaining_throttle}s restantes)."
                    )
                    return {
                        "status": "skipped",
                        "reason": "cycle_throttled",
                        "remaining_seconds": remaining_throttle,
                        "message": f"Ciclo automático em intervalo de espera ({remaining_throttle}s restantes)",
                    }
            except Exception:
                pass

    # Registra timestamp do ciclo
    scheduler.set_setting("analytics_last_cycle_at", now_iso, db_path=db_path)
    if not force:
        scheduler.set_setting("analytics_last_auto_cycle_at", now_iso, db_path=db_path)

    max_fetches = get_analytics_max_fetches_per_cycle(db_path=db_path)
    candidates = get_eligible_analytics_candidates(limit=max_fetches, now=current_time, db_path=db_path)

    if not candidates:
        summary_msg = "Nenhuma publicação elegível para coleta de analytics neste ciclo."
        scheduler.set_setting("analytics_last_cycle_status", "idle", db_path=db_path)
        scheduler.set_setting("analytics_last_cycle_summary", summary_msg, db_path=db_path)
        logger.info(f"[ANALYTICS_SCHEDULER] {summary_msg}")
        return {
            "status": "idle",
            "candidates_count": 0,
            "processed_count": 0,
            "results": [],
            "message": summary_msg,
        }

    logger.info(f"[ANALYTICS_SCHEDULER] Iniciando coleta para {len(candidates)} publicações elegíveis.")
    results = []
    processed_count = 0

    for cand in candidates:
        task_id = cand["task_id"]
        platform = cand["platform"]
        channel_id = cand.get("channel_id")
        ext_id = cand.get("external_id")

        # Verifica rate limit global
        if not check_and_increment_rate_limit(platform, now=current_time, db_path=db_path):
            results.append({
                "task_id": task_id,
                "platform": platform,
                "status": "skipped",
                "reason": "rate_limit_exceeded",
            })
            continue

        try:
            # Coleta e ingestão do snapshot com isolamento total de falhas
            snapshot = analytics_ingestion.ingest_analytics_for_publication(
                task_id=task_id,
                platform=platform,
                channel_id=channel_id,
                db_path=db_path,
                collected_at=now_iso,
            )
            processed_count += 1

            # Sucesso
            scheduler.set_setting("analytics_last_success_at", now_iso, db_path=db_path)
            operator_console.log_operational_event(
                component="analytics",
                severity="INFO",
                event_type="ANALYTICS_COLLECTION_SUCCESS",
                task_id=task_id,
                message=f"Analytics coletado com sucesso para {task_id} ({platform}). Score: {snapshot.get('performance_score')}.",
                metadata={
                    "platform": platform,
                    "channel_id": channel_id,
                    "source": snapshot.get("source"),
                    "views": snapshot.get("views"),
                    "likes": snapshot.get("likes"),
                    "performance_score": snapshot.get("performance_score"),
                },
                db_path=db_path,
            )

            results.append({
                "task_id": task_id,
                "platform": platform,
                "status": "success",
                "snapshot_id": snapshot.get("id"),
                "source": snapshot.get("source"),
                "views": snapshot.get("views"),
                "performance_score": snapshot.get("performance_score"),
            })

        except AnalyticsProviderError as ape:
            err_code = ape.code or "UNKNOWN"
            logger.warning(
                f"[ANALYTICS_SCHEDULER] Erro do provider '{platform}' ao coletar task {task_id}: "
                f"code={err_code}, msg={ape}"
            )
            # Aplica backoff no provider
            set_provider_backoff(platform, reason=err_code, now=current_time, db_path=db_path)
            results.append({
                "task_id": task_id,
                "platform": platform,
                "status": "failed",
                "error_code": err_code,
                "error_message": str(ape),
            })

        except Exception as exc:
            logger.exception(f"[ANALYTICS_SCHEDULER] Falha inesperada ao coletar task {task_id}: {exc}")
            set_provider_backoff(platform, reason=ERR_TEMPORARY, now=current_time, db_path=db_path)
            results.append({
                "task_id": task_id,
                "platform": platform,
                "status": "failed",
                "error_code": "EXCEPTION",
                "error_message": str(exc),
            })

    summary_msg = f"Ciclo de analytics concluído: {processed_count}/{len(candidates)} processados com sucesso."
    scheduler.set_setting("analytics_last_cycle_status", "completed", db_path=db_path)
    scheduler.set_setting("analytics_last_cycle_summary", summary_msg, db_path=db_path)

    logger.info(f"[ANALYTICS_SCHEDULER] {summary_msg}")
    return {
        "status": "completed",
        "candidates_count": len(candidates),
        "processed_count": processed_count,
        "results": results,
        "message": summary_msg,
    }


# ---------------------------------------------------------------------------
# Helpers para Console do Operador (Seção 17)
# ---------------------------------------------------------------------------

def get_analytics_scheduler_status(
    now: Optional[datetime] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Retorna o status operacional detalhado para o Operator Console:
    - Status: Enabled / Disabled
    - Last cycle
    - Last success
    - Next eligible collection
    - Provider backoff
    - Snapshots today
    """
    current_time = _normalize_utc(now)
    today_start_iso = current_time.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    enabled = is_analytics_auto_collection_enabled(db_path=db_path)
    last_cycle = scheduler.get_setting("analytics_last_cycle_at", None, db_path=db_path)
    last_cycle_status = scheduler.get_setting("analytics_last_cycle_status", "idle", db_path=db_path)
    last_cycle_summary = scheduler.get_setting("analytics_last_cycle_summary", "Nenhum ciclo executado", db_path=db_path)
    last_success = scheduler.get_setting("analytics_last_success_at", None, db_path=db_path)
    max_fetches = get_analytics_max_fetches_per_cycle(db_path=db_path)

    # Backoffs por plataforma
    backoffs = {}
    for plat in SUPPORTED_ANALYTICS_PLATFORMS:
        bo = get_provider_backoff(plat, now=current_time, db_path=db_path)
        if bo:
            backoffs[plat] = bo

    # Snapshots today
    analytics.init_analytics_db(db_path)
    snapshots_today = 0
    with analytics.get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM content_analytics WHERE collected_at >= ?;",
            (today_start_iso,),
        ).fetchone()
        if row:
            snapshots_today = row["cnt"]

    # Próxima coleta elegível (candidatos atuais)
    candidates = get_eligible_analytics_candidates(limit=1, now=current_time, db_path=db_path)
    has_eligible_now = len(candidates) > 0

    last_auto_cycle = scheduler.get_setting("analytics_last_auto_cycle_at", None, db_path=db_path)
    cycle_interval = get_analytics_cycle_min_interval_seconds(db_path=db_path)

    return {
        "auto_collection_enabled": enabled,
        "max_fetches_per_cycle": max_fetches,
        "min_cycle_interval_seconds": cycle_interval,
        "last_cycle_at": last_cycle,
        "last_auto_cycle_at": last_auto_cycle,
        "last_cycle_status": last_cycle_status,
        "last_cycle_summary": last_cycle_summary,
        "last_success_at": last_success,
        "has_eligible_now": has_eligible_now,
        "provider_backoffs": backoffs,
        "snapshots_today": snapshots_today,
    }
