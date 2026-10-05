"""Serviço de Idempotência e Proteção contra Duplicatas de Publicação (Fase V16.4.2B).

Garante que nenhuma publicação externa seja criada, agendada, processada ou enviada
mais de uma vez para a mesma tupla canônica (task_id, platform).

Camadas de Proteção:
1. Camada de Criação / Agendamento (plan_schedule e can_schedule_task)
2. Camada de Scheduler Runtime (run_scheduler_cycle, seleção de candidatos e início de ciclo)
3. Camada Imediatamente Pré-Provider (Just-In-Time Idempotency Gate antes de qualquer chamada externa)
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger

from app.utils import utils


def _get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Abre conexão com o SQLite com row_factory ativada."""
    path = db_path or utils.storage_dir(create=True)
    if not path.endswith(".db"):
        import os
        path = os.path.join(path, "video_factory.db")
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def check_canonical_publication_status(
    task_id: str,
    platform: str,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """Consulta publication_events para verificar se a tupla (task_id, platform) já possui sucesso canônico."""
    clean_task = str(task_id).strip()
    clean_plat = str(platform).lower().strip()

    def _query(c: sqlite3.Connection) -> Dict[str, Any]:
        row = c.execute(
            """
            SELECT id, external_id, external_url, published_at, provider_request_id,
                   channel_id, profile_id, privacy_status
            FROM publication_events
            WHERE task_id = ? AND platform = ? AND status = 'success'
            ORDER BY id ASC LIMIT 1;
            """,
            (clean_task, clean_plat),
        ).fetchone()

        if row:
            return {
                "is_published": True,
                "event_id": row["id"],
                "external_id": row["external_id"],
                "external_url": row["external_url"],
                "published_at": row["published_at"],
                "provider_request_id": row["provider_request_id"],
                "channel_id": row["channel_id"],
                "profile_id": row["profile_id"],
                "privacy_status": row["privacy_status"],
            }
        return {
            "is_published": False,
            "event_id": None,
            "external_id": None,
            "external_url": None,
            "published_at": None,
            "provider_request_id": None,
            "channel_id": None,
            "profile_id": None,
            "privacy_status": None,
        }

    if conn is not None:
        return _query(conn)
    with _get_connection(db_path) as c:
        return _query(c)


def check_scheduled_posts_state(
    task_id: str,
    platform: str,
    exclude_post_id: Optional[int] = None,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """Analisa o estado de todos os scheduled_posts para a tupla (task_id, platform)."""
    clean_task = str(task_id).strip()
    clean_plat = str(platform).lower().strip()

    def _query(c: sqlite3.Connection) -> Dict[str, Any]:
        sql = """
            SELECT id, status, channel_id, profile_id, next_attempt_at, attempts
            FROM scheduled_posts
            WHERE task_id = ? AND platform = ?
        """
        params: List[Any] = [clean_task, clean_plat]
        if exclude_post_id is not None:
            sql += " AND id != ?"
            params.append(exclude_post_id)
        sql += " ORDER BY id ASC;"

        rows = c.execute(sql, tuple(params)).fetchall()

        has_published = False
        published_post_id: Optional[int] = None
        has_processing = False
        processing_post_id: Optional[int] = None
        has_executable = False
        executable_post_ids: List[int] = []
        cancelled_post_ids: List[int] = []

        for r in rows:
            st = str(r["status"]).lower().strip()
            pid = int(r["id"])
            if st == "published":
                has_published = True
                if published_post_id is None:
                    published_post_id = pid
            elif st == "processing":
                has_processing = True
                if processing_post_id is None:
                    processing_post_id = pid
            elif st in ("planned", "ready"):
                has_executable = True
                executable_post_ids.append(pid)
            elif st == "cancelled":
                cancelled_post_ids.append(pid)

        return {
            "has_published": has_published,
            "published_post_id": published_post_id,
            "has_processing": has_processing,
            "processing_post_id": processing_post_id,
            "has_executable": has_executable,
            "executable_post_ids": executable_post_ids,
            "cancelled_post_ids": cancelled_post_ids,
            "total_posts": len(rows),
        }

    if conn is not None:
        return _query(conn)
    with _get_connection(db_path) as c:
        return _query(c)


def can_schedule_task(
    task_id: str,
    platform: str,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    """Camada 1: Valida se um novo scheduled_post pode ser criado para (task_id, platform).

    Regras:
    1. Se já existir publication_event com status 'success' -> BLOQUEIA ('already_published').
    2. Se já existir scheduled_post com status 'published' -> BLOQUEIA ('already_published').
    3. Se já existir scheduled_post com status 'processing' -> BLOQUEIA ('already_processing').
    4. Se já existir scheduled_post executável ('planned' ou 'ready') -> BLOQUEIA ('already_scheduled').
    5. Duplicatas históricas canceladas ('cancelled') NÃO bloqueiam se não houver post ativo ou publicado.
    6. Múltiplas plataformas para a mesma task são completamente independentes.
    """
    clean_task = str(task_id).strip()
    clean_plat = str(platform).lower().strip()

    def _check(c: sqlite3.Connection) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        # 1. Checa sucesso canônico
        canon = check_canonical_publication_status(clean_task, clean_plat, conn=c)
        if canon["is_published"]:
            return False, "already_published", {"source": "publication_events", "details": canon}

        # 2. Checa estado dos scheduled_posts
        sp_state = check_scheduled_posts_state(clean_task, clean_plat, conn=c)

        if sp_state["has_published"]:
            return False, "already_published", {"source": "scheduled_posts", "details": sp_state}

        if sp_state["has_processing"]:
            return False, "already_processing", {"source": "scheduled_posts", "details": sp_state}

        if sp_state["has_executable"]:
            return False, "already_scheduled", {"source": "scheduled_posts", "details": sp_state}

        # Cancelados históricos não bloqueiam
        return True, None, {"status": "eligible", "details": sp_state}

    if conn is not None:
        return _check(conn)
    with _get_connection(db_path) as c:
        return _check(c)


def can_execute_scheduled_post(
    task_id: str,
    platform: str,
    post_id: int,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    """Camada 2: Valida se o post específico pode ser executado no ciclo do scheduler.

    Garante que:
    1. Não exista sucesso canônico já registrado.
    2. Não exista outro post em 'processing' ativo para a mesma tupla (task_id, platform).
    3. Não exista outro post em 'published' para a mesma tupla.
    """
    clean_task = str(task_id).strip()
    clean_plat = str(platform).lower().strip()

    def _check(c: sqlite3.Connection) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        # 1. Checa sucesso canônico
        canon = check_canonical_publication_status(clean_task, clean_plat, conn=c)
        if canon["is_published"]:
            return False, "already_published", {"source": "publication_events", "details": canon}

        # 2. Checa outros scheduled_posts (excluindo este post_id)
        sp_state = check_scheduled_posts_state(clean_task, clean_plat, exclude_post_id=post_id, conn=c)

        if sp_state["has_published"]:
            return False, "already_published", {"source": "scheduled_posts", "details": sp_state}

        if sp_state["has_processing"]:
            return False, "already_processing", {"source": "scheduled_posts", "details": sp_state}

        return True, None, {"status": "executable", "details": sp_state}

    if conn is not None:
        return _check(conn)
    with _get_connection(db_path) as c:
        return _check(c)


def jit_provider_idempotency_guard(
    task_id: str,
    platform: str,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Camada 3: Just-In-Time Idempotency Gate imediatamente antes de qualquer provider externo.

    Retorna:
    - (True, None): Seguro chamar o provider (nenhum sucesso prévio).
    - (False, canonical_info): BLOQUEAR chamada ao provider (já publicado).
    """
    clean_task = str(task_id).strip()
    clean_plat = str(platform).lower().strip()

    canon = check_canonical_publication_status(clean_task, clean_plat, db_path=db_path, conn=conn)
    if canon["is_published"]:
        logger.info(
            f"[IDEMPOTENCY_GATE][BLOCKED] Chamada ao provider cancelada para {clean_task} ({clean_plat}). "
            f"Publicação canônica já confirmada no evento #{canon['event_id']} (external_id={canon['external_id']})."
        )
        return False, canon

    return True, None


def neutralize_duplicate_executable_posts(
    task_id: str,
    platform: str,
    canonical_post_id: int,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """Neutraliza posts agendados executáveis redundantes para a mesma tupla (task_id, platform).

    Mantém canonical_post_id e converte os demais em 'cancelled' com next_attempt_at = NULL,
    emitindo evento operacional DUPLICATE_SCHEDULE_NEUTRALIZED.
    """
    clean_task = str(task_id).strip()
    clean_plat = str(platform).lower().strip()

    def _neutralize(c: sqlite3.Connection) -> int:
        rows = c.execute(
            """
            SELECT id, status, channel_id FROM scheduled_posts
            WHERE task_id = ? AND platform = ? AND id != ?
              AND status IN ('planned', 'ready');
            """,
            (clean_task, clean_plat, canonical_post_id),
        ).fetchall()

        if not rows:
            return 0

        cancelled_count = 0
        for r in rows:
            dup_id = r["id"]
            c.execute(
                """
                UPDATE scheduled_posts
                SET status = 'cancelled',
                    next_attempt_at = NULL,
                    last_error = 'Neutralizado por protecao de idempotencia (duplicata de #' || ? || ')'
                WHERE id = ?;
                """,
                (canonical_post_id, dup_id),
            )
            cancelled_count += 1
            logger.info(
                f"[IDEMPOTENCY] Post agendado duplicado #{dup_id} para ({clean_task}, {clean_plat}) "
                f"neutralizado em favor do post canônico #{canonical_post_id}."
            )

        return cancelled_count

    if conn is not None:
        return _neutralize(conn)
    with _get_connection(db_path) as c:
        with c:
            return _neutralize(c)
