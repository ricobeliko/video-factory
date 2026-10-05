"""Módulo canônico de política de retry e cleanup de metadados residuais (V16.4.2C).

Centraliza a política estrita de retry de publicações, garantindo que:
1. Posts em estados terminais ('published', 'cancelled', 'failed') nunca mantenham next_attempt_at armado.
2. Sucesso canônico em publication_events sempre desarme qualquer retry para a tupla (task_id, platform).
3. Apenas falhas transitórias com attempts < MAX_RETRY_ATTEMPTS possam agendar retries.
4. Erros permanentes ou retries esgotados transicionem deterministicamente para 'failed' com next_attempt_at = NULL.
5. Invariantes de retry sejam verificados e limpos deterministicamente (zero deleções).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from typing import Any, Dict, Optional

from loguru import logger

# Estados terminais canônicos do sistema
TERMINAL_STATUSES = frozenset({"published", "cancelled", "failed"})
MAX_RETRY_ATTEMPTS = 3


@dataclass(frozen=True)
class RetryDecision:
    can_retry: bool
    resulting_status: str  # 'ready', 'failed', 'published', 'cancelled', 'processing'
    next_attempt_at: Optional[str]  # ISO string or None
    backoff_seconds: int
    reason: str  # Motivo legível da decisão
    error_classification: str  # 'transient', 'permanent', 'none'


def is_terminal_status(status: Optional[str]) -> bool:
    """Verifica se um status de scheduled_post é terminal."""
    if not status:
        return False
    return str(status).lower().strip() in TERMINAL_STATUSES


def is_youtube_daily_quota_error(error_msg: Optional[str]) -> bool:
    """Detecta erro de quota diária de upload do YouTube."""
    msg = (error_msg or "").lower()
    quota_indicators = (
        "video uploads",
        "video_insert",
        "defaultvideoinsertperdayperproject",
        "resource_exhausted",
    )
    if "quota exceeded" in msg and any(ind in msg for ind in quota_indicators):
        return True
    if "resource_exhausted" in msg and any(
        ind in msg for ind in ("video uploads", "video_insert", "defaultvideoinsertperdayperproject")
    ):
        return True
    return False


def get_retry_after_hint(error_msg: Optional[str]) -> Optional[int]:
    """Retorna hint de retry_after em segundos baseado no tipo específico de erro."""
    if is_youtube_daily_quota_error(error_msg):
        return 86400  # 24 horas para quota diária de upload do YouTube
    return None


def classify_retry_error(error_msg: Optional[str]) -> str:
    """Classifica erro de publicação em 'transient' (retryable) ou 'permanent' (não-retryable)."""
    err = (error_msg or "").lower().strip()
    if not err:
        return "permanent"

    if is_youtube_daily_quota_error(err):
        return "transient"

    # Erros explicitamente permanentes / não-recuperáveis por repetição cega
    permanent_indicators = [
        "invalid_grant",
        "unauthorized",
        "401",
        "video_not_found",
        "file not found",
        "no such file",
        "channel_disabled",
        "profile_disabled",
        "copyright",
        "inappropriate",
        "terms of service",
        "suspended",
        "terminated",
        "invalid_argument",
        "validation_error",
        "remote_inconsistent",
        "ambiguous",
    ]
    for pi in permanent_indicators:
        if pi in err:
            return "permanent"

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
        "reset by peer",
        "socket",
    ]
    for kw in transient_keywords:
        if kw in err:
            return "transient"

    return "permanent"


def calculate_backoff_seconds(attempt: int, retry_after: Optional[int] = None) -> int:
    """Calcula o tempo de espera em segundos para retry de falhas temporárias."""
    if retry_after is not None and retry_after > 0:
        return retry_after
    if attempt <= 1:
        return 15 * 60  # 15 minutos
    if attempt == 2:
        return 60 * 60  # 60 minutos
    return 60 * 60


def evaluate_retry_decision(
    task_id: str,
    platform: str,
    current_status: str,
    attempts: int,
    error_msg: Optional[str] = None,
    has_canonical_success: Optional[bool] = None,
    max_attempts: int = MAX_RETRY_ATTEMPTS,
    current_time: Optional[datetime] = None,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> RetryDecision:
    """Avalia deterministicamente se uma publicação pode ou não ser reagendada (retry).

    Retorna um RetryDecision estruturado e imutável contendo o status resultante,
    next_attempt_at sanitizado, backoff e justificativa.
    """
    clean_task = str(task_id).strip()
    clean_plat = str(platform).lower().strip()
    curr_stat = str(current_status or "").lower().strip()
    now_dt = current_time or datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)

    # 1. Sucesso canônico em publication_events (Verdade definitiva - V16.4.2A / V16.4.2B)
    if has_canonical_success is None:
        from app.services import publishing_idempotency
        canon = publishing_idempotency.check_canonical_publication_status(clean_task, clean_plat, db_path=db_path, conn=conn)
        has_canonical_success = bool(canon.get("is_published"))

    if has_canonical_success:
        return RetryDecision(
            can_retry=False,
            resulting_status="published",
            next_attempt_at=None,
            backoff_seconds=0,
            reason="canonical_success_terminal",
            error_classification="none",
        )

    # 2. Status 'published' existente
    if curr_stat == "published":
        return RetryDecision(
            can_retry=False,
            resulting_status="published",
            next_attempt_at=None,
            backoff_seconds=0,
            reason="already_published_terminal",
            error_classification="none",
        )

    # 3. Status 'cancelled' existente (duplicatas neutralizadas ou cancelamento manual)
    if curr_stat == "cancelled":
        return RetryDecision(
            can_retry=False,
            resulting_status="cancelled",
            next_attempt_at=None,
            backoff_seconds=0,
            reason="cancelled_terminal",
            error_classification="none",
        )

    # 4. Status 'processing' ativo: nunca armar retry enquanto ativo
    if curr_stat == "processing" and error_msg is None:
        return RetryDecision(
            can_retry=False,
            resulting_status="processing",
            next_attempt_at=None,
            backoff_seconds=0,
            reason="processing_active",
            error_classification="none",
        )

    # 5. Esgotamento de tentativas (attempts >= max_attempts)
    next_attempt_num = attempts + 1
    if next_attempt_num > max_attempts:
        err_type = classify_retry_error(error_msg)
        return RetryDecision(
            can_retry=False,
            resulting_status="failed",
            next_attempt_at=None,
            backoff_seconds=0,
            reason=f"max_attempts_exceeded ({next_attempt_num - 1}/{max_attempts})",
            error_classification=err_type,
        )

    # 6. Classificação do erro
    err_type = classify_retry_error(error_msg)
    if err_type == "permanent":
        return RetryDecision(
            can_retry=False,
            resulting_status="failed",
            next_attempt_at=None,
            backoff_seconds=0,
            reason="permanent_error_non_retryable",
            error_classification="permanent",
        )

    # 7. Erro transitório dentro do limite -> retry autorizado
    retry_hint = get_retry_after_hint(error_msg)
    backoff_sec = calculate_backoff_seconds(next_attempt_num, retry_after=retry_hint)
    from app.services import scheduler
    next_retry_dt = now_dt + timedelta(seconds=backoff_sec)
    next_attempt_iso = scheduler._to_iso(next_retry_dt)

    return RetryDecision(
        can_retry=True,
        resulting_status="ready",
        next_attempt_at=next_attempt_iso,
        backoff_seconds=backoff_sec,
        reason=f"transient_retry_allowed ({next_attempt_num}/{max_attempts})",
        error_classification="transient",
    )


def cleanup_residual_retries(
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Varre e normaliza metadados residuais de retry em scheduled_posts (V16.4.2C).

    Regras de integridade aplicadas:
    1. Posts com status 'published' e next_attempt_at IS NOT NULL -> next_attempt_at = NULL.
    2. Posts com status 'cancelled' e next_attempt_at IS NOT NULL -> next_attempt_at = NULL.
    3. Posts com status 'failed' e next_attempt_at IS NOT NULL -> next_attempt_at = NULL.
    4. Posts para tuplas que já possuem publication_events.status = 'success' -> next_attempt_at = NULL, status = 'published'.
    5. Posts em 'planned' ou 'ready' com attempts >= MAX_RETRY_ATTEMPTS -> status = 'failed', next_attempt_at = NULL.
    6. Posts em 'planned' ou 'ready' com last_error permanente e next_attempt_at armado -> status = 'failed', next_attempt_at = NULL.

    Garantias:
    - Zero deleções de scheduled_posts ou publication_events.
    - Zero deleções de arquivos de mídia.
    - Zero chamadas a provedores externos.
    - Emite evento operacional RETRY_METADATA_CLEANED se houver mutações.
    """
    from app.services import scheduler

    scheduler.init_db(db_path)

    def _execute_cleanup(c: sqlite3.Connection) -> Dict[str, Any]:
        # 1. Contagens de candidatos antes
        # 1.1 Published com retry armado
        published_rows = c.execute(
            "SELECT id, task_id, platform FROM scheduled_posts WHERE status = 'published' AND next_attempt_at IS NOT NULL;"
        ).fetchall()

        # 1.2 Cancelled com retry armado
        cancelled_rows = c.execute(
            "SELECT id, task_id, platform FROM scheduled_posts WHERE status = 'cancelled' AND next_attempt_at IS NOT NULL;"
        ).fetchall()

        # 1.3 Failed com retry armado
        failed_rows = c.execute(
            "SELECT id, task_id, platform FROM scheduled_posts WHERE status = 'failed' AND next_attempt_at IS NOT NULL;"
        ).fetchall()

        # 1.4 Sucesso canônico em publication_events com retry residual no post
        canon_success_rows = c.execute(
            """
            SELECT sp.id, sp.task_id, sp.platform, sp.status
            FROM scheduled_posts sp
            WHERE sp.next_attempt_at IS NOT NULL
              AND EXISTS (
                SELECT 1 FROM publication_events pe
                WHERE pe.task_id = sp.task_id
                  AND pe.platform = sp.platform
                  AND pe.status = 'success'
              );
            """
        ).fetchall()

        # 1.5 Posts com attempts >= MAX_RETRY_ATTEMPTS ainda em planned/ready com retry armado
        exhausted_rows = c.execute(
            """
            SELECT id, task_id, platform, attempts FROM scheduled_posts
            WHERE status IN ('planned', 'ready')
              AND attempts >= ?
              AND next_attempt_at IS NOT NULL;
            """,
            (MAX_RETRY_ATTEMPTS,),
        ).fetchall()

        # 1.6 Posts em planned/ready com erro permanente armado
        pending_with_error = c.execute(
            """
            SELECT id, task_id, platform, attempts, last_error FROM scheduled_posts
            WHERE status IN ('planned', 'ready')
              AND next_attempt_at IS NOT NULL
              AND last_error IS NOT NULL
              AND last_error != '';
            """
        ).fetchall()

        permanent_error_ids = []
        for r in pending_with_error:
            if classify_retry_error(r["last_error"]) == "permanent":
                permanent_error_ids.append(r["id"])

        summary = {
            "published_residual_cleaned": len(published_rows),
            "cancelled_residual_cleaned": len(cancelled_rows),
            "failed_residual_cleaned": len(failed_rows),
            "canonical_success_residual_cleaned": len(canon_success_rows),
            "exhausted_attempts_cleaned": len(exhausted_rows),
            "permanent_error_cleaned": len(permanent_error_ids),
        }
        total_affected = (
            summary["published_residual_cleaned"]
            + summary["cancelled_residual_cleaned"]
            + summary["failed_residual_cleaned"]
            + summary["canonical_success_residual_cleaned"]
            + summary["exhausted_attempts_cleaned"]
            + summary["permanent_error_cleaned"]
        )
        summary["total_cleaned"] = total_affected

        if dry_run:
            logger.info(f"[RETRY_CLEANUP][DRY_RUN] Inventory: {summary}")
            return summary

        # Aplica mutações de limpeza
        if summary["published_residual_cleaned"] > 0:
            c.execute("UPDATE scheduled_posts SET next_attempt_at = NULL WHERE status = 'published' AND next_attempt_at IS NOT NULL;")

        if summary["cancelled_residual_cleaned"] > 0:
            c.execute("UPDATE scheduled_posts SET next_attempt_at = NULL WHERE status = 'cancelled' AND next_attempt_at IS NOT NULL;")

        if summary["failed_residual_cleaned"] > 0:
            c.execute("UPDATE scheduled_posts SET next_attempt_at = NULL WHERE status = 'failed' AND next_attempt_at IS NOT NULL;")

        if summary["canonical_success_residual_cleaned"] > 0:
            c.execute(
                """
                UPDATE scheduled_posts
                SET next_attempt_at = NULL
                WHERE next_attempt_at IS NOT NULL
                  AND EXISTS (
                    SELECT 1 FROM publication_events pe
                    WHERE pe.task_id = scheduled_posts.task_id
                      AND pe.platform = scheduled_posts.platform
                      AND pe.status = 'success'
                  );
                """
            )

        if summary["exhausted_attempts_cleaned"] > 0:
            c.execute(
                """
                UPDATE scheduled_posts
                SET status = 'failed', next_attempt_at = NULL
                WHERE status IN ('planned', 'ready')
                  AND attempts >= ?;
                """,
                (MAX_RETRY_ATTEMPTS,),
            )

        if len(permanent_error_ids) > 0:
            placeholders = ",".join("?" for _ in permanent_error_ids)
            c.execute(
                f"UPDATE scheduled_posts SET status = 'failed', next_attempt_at = NULL WHERE id IN ({placeholders});",
                permanent_error_ids,
            )

        if total_affected > 0:
            logger.info(f"[RETRY_CLEANUP] Limpeza concluída: {summary}")
            try:
                c.execute(
                    """
                    CREATE TABLE IF NOT EXISTS operational_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        component TEXT NOT NULL,
                        severity TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        task_id TEXT,
                        message TEXT NOT NULL,
                        metadata_json TEXT
                    );
                    """
                )
                from app.services import scheduler
                now_iso = scheduler._to_iso(datetime.now(timezone.utc))
                c.execute(
                    """
                    INSERT INTO operational_events (
                        timestamp, component, severity, event_type, task_id, message, metadata_json
                    ) VALUES (?, 'retry_policy', 'INFO', 'RETRY_METADATA_CLEANED', NULL, ?, ?);
                    """,
                    (
                        now_iso,
                        f"Limpeza de metadados residuais de retry concluída ({total_affected} correções).",
                        json.dumps(summary, sort_keys=True),
                    ),
                )
            except Exception as op_err:
                logger.debug(f"[RETRY_CLEANUP] Operational event não registrado: {op_err}")

        return summary

    if conn is not None:
        return _execute_cleanup(conn)
    with scheduler.get_connection(db_path) as c:
        return _execute_cleanup(c)
