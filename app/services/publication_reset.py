"""Serviço de Auditoria e Reset Controlado de Publicações Pendentes (Fase V16.4.2R / V16.4.2R.1).

Fornece operações seguras, auditáveis e não-destrutivas para neutralizar publicações
pendentes, stale processing ou com retries armados antes de correções no subsistema de publicação.

POLÍTICA DE PRESERVAÇÃO E SEGURANÇA (V16.4.2R.1):
- Preserva integralmente publication_events com status='success'.
- Preserva scheduled_posts com status='published' (NUNCA transforma em cancelled).
- Se scheduled_post com status='published' possuir next_attempt_at armado, limpa next_attempt_at
  e mantém status='published', preservando attempts como histórico (RETRY_DISARMED_AFTER_SUCCESS).
- Preserva external_id, external_url, published_at e integridade de publicação.
- Registros com status='failed' que possuem publication_events(success) NÃO são cancelados
  cegamente: permanecem status='failed', têm seus retries desarmados (next_attempt_at = NULL)
  e são preservados como inconsistência auditável para reconciliação determinística na V16.4.2A.
- planned, ready, queued e stale processing são neutralizados para status='cancelled'.
- Preserva dados de analytics, histórico operacional e perfis/canais.
- Zero deleção de arquivos de mídia ou diretórios de tarefas.
- Requer fail-closed: scheduler_enabled=False, auto_publish_enabled=False e active_primary=False
  antes de mutações reais.
- Gera backup consistente prévio com PRAGMA integrity_check e SHA-256.
- Executa mutações em transação atômica única com registro detalhado em operational_events.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from app.services import operator_console, production_backup, scheduler


class PreconditionError(RuntimeError):
    """Exceção levantada quando pré-condições operacionais de segurança não são atendidas."""
    pass


def check_reset_preconditions(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Verifica se o scheduler, auto_publish e nó PRIMARY estão inativos antes do reset."""
    target_db = scheduler.get_db_path(db_path)
    if not os.path.isfile(target_db):
        return {
            "passed": False,
            "database_exists": False,
            "scheduler_enabled": None,
            "auto_publish_enabled": None,
            "active_primary": False,
            "errors": [f"Banco de dados não encontrado em: {target_db}"],
        }

    settings = scheduler.get_all_settings(db_path=target_db)
    sched_enabled = bool(settings.get("scheduler_enabled", False))
    auto_pub_enabled = bool(settings.get("auto_publish_enabled", False))

    active_primary = False
    with scheduler.get_connection(target_db) as conn:
        table_check = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='instance_locks';"
        ).fetchone()
        if table_check:
            row = conn.execute(
                "SELECT node_id, node_name, status, last_heartbeat FROM instance_locks WHERE lock_key = ?;",
                (operator_console.DEFAULT_INSTANCE_LOCK_KEY,),
            ).fetchone()
            if row and row["status"] == operator_console.INSTANCE_STATUS_ACTIVE:
                active_primary = True

    errors: List[str] = []
    if sched_enabled:
        errors.append("scheduler_enabled está ativo (True). Produção deve estar parada.")
    if auto_pub_enabled:
        errors.append("auto_publish_enabled está ativo (True). Produção deve estar parada.")
    if active_primary:
        errors.append(
            "Instância primária (PRIMARY_FACTORY) está com status ACTIVE em instance_locks. "
            "Pare a aplicação no host (ex.: schtasks /End /TN MoneyPrinterTurbo) antes de executar o reset real."
        )

    passed = len(errors) == 0

    return {
        "passed": passed,
        "database_exists": True,
        "scheduler_enabled": sched_enabled,
        "auto_publish_enabled": auto_pub_enabled,
        "active_primary": active_primary,
        "errors": errors,
    }


def disable_scheduler_preconditions(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Desativa administrativamente scheduler_enabled e auto_publish_enabled no autopilot_settings."""
    target_db = scheduler.get_db_path(db_path)
    scheduler.save_settings(
        {
            "scheduler_enabled": False,
            "auto_publish_enabled": False,
        },
        db_path=target_db,
    )
    operator_console.log_operational_event(
        component="PublishingReset",
        severity=operator_console.SEVERITY_WARNING,
        event_type="PRE_REPAIR_SCHEDULER_DISABLED",
        message="scheduler_enabled e auto_publish_enabled foram desativados administrativamente para reset de publicações.",
        db_path=target_db,
    )
    return check_reset_preconditions(target_db)


def inventory_before_reset(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Gera um inventário completo e detalhado do estado do banco antes do reset."""
    target_db = scheduler.get_db_path(db_path)
    if not os.path.isfile(target_db):
        raise FileNotFoundError(f"Banco de dados não encontrado: {target_db}")

    with scheduler.get_connection(target_db) as conn:
        # 1. Contagem por platform, status, profile_id, channel_id
        counts_cursor = conn.execute(
            """
            SELECT platform, status, COALESCE(profile_id, 'None') AS prof, COALESCE(channel_id, 'None') AS chan, COUNT(*) AS cnt
            FROM scheduled_posts
            GROUP BY platform, status, profile_id, channel_id
            ORDER BY platform, status;
            """
        )
        grouped_counts = [dict(r) for r in counts_cursor.fetchall()]

        # 2. Listagem de posts pendentes / stale / retries armados / posts que necessitam de intervenção
        pending_cursor = conn.execute(
            """
            SELECT id, task_id, platform, status, attempts, scheduled_at, next_attempt_at, last_error, profile_id, channel_id
            FROM scheduled_posts
            WHERE status IN ('planned', 'ready', 'queued', 'processing')
               OR next_attempt_at IS NOT NULL
               OR (status = 'failed' AND attempts > 0)
            ORDER BY id ASC;
            """
        )
        pending_posts = [dict(r) for r in pending_cursor.fetchall()]

        # 3. Análise de publication_events
        pub_events_cursor = conn.execute(
            """
            SELECT id, task_id, platform, published_at, status, external_id, external_url, provider_request_id, profile_id, channel_id
            FROM publication_events
            ORDER BY id ASC;
            """
        )
        all_pub_events = [dict(r) for r in pub_events_cursor.fetchall()]

        success_events = [e for e in all_pub_events if e["status"] == "success"]
        failed_events = [e for e in all_pub_events if e["status"] != "success"]

        # 4. Múltiplos sucessos para o mesmo task_id + platform
        dup_success_cursor = conn.execute(
            """
            SELECT task_id, platform, COUNT(*) AS cnt
            FROM publication_events
            WHERE status = 'success'
            GROUP BY task_id, platform
            HAVING COUNT(*) > 1;
            """
        )
        duplicate_successes = [dict(r) for r in dup_success_cursor.fetchall()]

        # 5. Success sem scheduled_post coerente
        success_without_coherent_post = []
        for ev in success_events:
            row = conn.execute(
                "SELECT id, status FROM scheduled_posts WHERE task_id = ? AND platform = ?;",
                (ev["task_id"], ev["platform"]),
            ).fetchone()
            if not row or row["status"] != "published":
                success_without_coherent_post.append({
                    "publication_event_id": ev["id"],
                    "task_id": ev["task_id"],
                    "platform": ev["platform"],
                    "external_id": ev["external_id"],
                    "matching_scheduled_post": dict(row) if row else None,
                })

        # 6. Scheduled post pendente que já possua publication_event success
        pending_with_existing_success = []
        # 6B. Scheduled post 'published' com next_attempt_at armado (para normalização)
        published_with_armed_retries = []
        # 6C. Scheduled post 'failed' com publication_event success (inconsistência a preservar)
        failed_with_existing_success = []

        for post in pending_posts:
            row = conn.execute(
                "SELECT id, external_id, published_at FROM publication_events WHERE task_id = ? AND platform = ? AND status = 'success';",
                (post["task_id"], post["platform"]),
            ).fetchone()

            if post["status"] == "published" and post.get("next_attempt_at") is not None:
                published_with_armed_retries.append({
                    "scheduled_post_id": post["id"],
                    "task_id": post["task_id"],
                    "platform": post["platform"],
                    "next_attempt_at": post["next_attempt_at"],
                    "attempts": post["attempts"],
                })

            if row:
                entry = {
                    "scheduled_post_id": post["id"],
                    "task_id": post["task_id"],
                    "platform": post["platform"],
                    "scheduled_post_status": post["status"],
                    "publication_event_id": row["id"],
                    "external_id": row["external_id"],
                    "published_at": row["published_at"],
                }
                if post["status"] == "failed":
                    failed_with_existing_success.append(entry)
                elif post["status"] in ("planned", "ready", "queued", "processing"):
                    pending_with_existing_success.append(entry)

    # 7. Arquivos e vídeos das tarefas pendentes
    tasks_root = os.path.join(os.path.dirname(target_db), "tasks")
    task_media_info: List[Dict[str, Any]] = []
    unique_pending_tasks = sorted(list({p["task_id"] for p in pending_posts if p.get("task_id")}))

    for tid in unique_pending_tasks:
        task_dir = os.path.join(tasks_root, tid)
        exists = os.path.isdir(task_dir)
        media_files: List[str] = []
        if exists:
            try:
                media_files = [f for f in os.listdir(task_dir) if f.endswith(".mp4") or f.endswith(".mp3")]
            except OSError:
                pass
        task_media_info.append({
            "task_id": tid,
            "directory_exists": exists,
            "media_files": media_files,
            "media_files_count": len(media_files),
        })

    return {
        "database_path": target_db,
        "grouped_counts": grouped_counts,
        "pending_posts": pending_posts,
        "pending_count": len(pending_posts),
        "total_publication_events": len(all_pub_events),
        "success_publication_events_count": len(success_events),
        "failed_publication_events_count": len(failed_events),
        "duplicate_successes": duplicate_successes,
        "success_without_coherent_post": success_without_coherent_post,
        "pending_with_existing_success": pending_with_existing_success,
        "published_with_armed_retries": published_with_armed_retries,
        "failed_with_existing_success": failed_with_existing_success,
        "task_media_info": task_media_info,
        "media_files_deleted": 0,
    }


def reset_pending_publications(
    db_path: Optional[str] = None,
    dry_run: bool = True,
    confirm_token: Optional[str] = None,
    force_preconditions: bool = False,
    backup_dir: Optional[str] = None,
    audit_reason: str = "PRE_REPAIR_PUBLICATION_RESET",
) -> Dict[str, Any]:
    """Executa simulação (dry_run=True) ou reset controlado (dry_run=False) de publicações pendentes."""
    target_db = scheduler.get_db_path(db_path)
    preconditions = check_reset_preconditions(target_db)

    if not dry_run and not force_preconditions and not preconditions.get("passed"):
        raise PreconditionError(
            f"Falha de pré-condições para reset: {preconditions.get('errors')}. "
            "Se scheduler ou auto_publish estiverem ativos ou nó primário ativo: ABORTAR."
        )

    if not dry_run and confirm_token != "RESET_PENDING_PUBLICATIONS":
        raise ValueError("Confirmação obrigatória ausente. Use confirm_token='RESET_PENDING_PUBLICATIONS' para executar.")

    before_inv = inventory_before_reset(target_db)
    pending_posts = before_inv["pending_posts"]

    # Classificação de ações planejadas
    would_cancel_planned = 0
    would_cancel_processing = 0
    would_disarm_retries = 0
    would_clear_next_attempt = 0
    would_neutralize_duplicates = 0
    already_published_preserved = 0
    normalized_published = 0
    failed_with_success_preserved = 0

    actions_plan: List[Dict[str, Any]] = []

    with scheduler.get_connection(target_db) as conn:
        pub_count_row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM scheduled_posts WHERE status = 'published';"
        ).fetchone()
        already_published_preserved = pub_count_row["cnt"] if pub_count_row else 0

        # Mapeia todas as tarefas e plataformas que já possuem evento com status = 'success'
        success_events_rows = conn.execute(
            "SELECT DISTINCT task_id, platform FROM publication_events WHERE status = 'success';"
        ).fetchall()
        success_pairs = {(r["task_id"], r["platform"]) for r in success_events_rows}

        # Mapeia todas as tarefas e plataformas que possuem status = 'published' em scheduled_posts
        published_rows = conn.execute(
            "SELECT DISTINCT task_id, platform FROM scheduled_posts WHERE status = 'published';"
        ).fetchall()
        published_pairs = {(r["task_id"], r["platform"]) for r in published_rows}

    # Detecta duplicatas entre posts pendentes (excluindo posts 'published')
    seen_pending_keys = set()
    duplicate_pending_ids = set()
    for post in pending_posts:
        if post["status"] == "published":
            continue
        key = (post["task_id"], post.get("channel_id") or "", post["platform"])
        if key in seen_pending_keys:
            duplicate_pending_ids.add(post["id"])
        else:
            seen_pending_keys.add(key)

    for post in pending_posts:
        post_id = post["id"]
        status = post["status"]
        next_attempt = post.get("next_attempt_at")
        task_id = post["task_id"]
        platform = post["platform"]

        has_published_record = (task_id, platform) in published_pairs
        has_success_event = (task_id, platform) in success_pairs
        has_canonical_success = has_published_record or has_success_event
        is_dup = post_id in duplicate_pending_ids

        resulting_status = "cancelled"
        reason = audit_reason

        # -------------------------------------------------------------
        # REGRA 1: PUBLISHED (com ou sem publication_event success)
        # NUNCA transformar em cancelled! Manter published, limpar next_attempt_at.
        # -------------------------------------------------------------
        if status == "published":
            resulting_status = "published"
            if next_attempt is not None:
                would_clear_next_attempt += 1
                normalized_published += 1
                reason = f"{audit_reason}: RETRY_DISARMED_AFTER_SUCCESS: Published post normalized, retry disarmed"
            else:
                reason = f"{audit_reason}: PUBLISHED_POST_PRESERVED"

        # -------------------------------------------------------------
        # REGRA 2: PLANNED / READY / QUEUED
        # Neutralizar para cancelled. Se já houver sucesso publicado, registrar como duplicata.
        # -------------------------------------------------------------
        elif status in ("planned", "ready", "queued"):
            resulting_status = "cancelled"
            if next_attempt is not None:
                would_clear_next_attempt += 1

            if has_canonical_success:
                would_neutralize_duplicates += 1
                reason = f"{audit_reason}: PENDING_DUPLICATE_ALREADY_PUBLISHED_CANCELLED: Publication already completed"
            elif is_dup:
                would_neutralize_duplicates += 1
                reason = f"{audit_reason}: PENDING_DUPLICATE_CANCELLED: Neutralizing duplicate scheduled post"
            else:
                would_cancel_planned += 1
                reason = f"{audit_reason}: PENDING_PUBLICATION_CANCELLED"

        # -------------------------------------------------------------
        # REGRA 3: PROCESSING (stale durante manutenção)
        # Neutralizar para cancelled. Não volta automaticamente para fila.
        # -------------------------------------------------------------
        elif status == "processing":
            resulting_status = "cancelled"
            if next_attempt is not None:
                would_clear_next_attempt += 1
            would_cancel_processing += 1
            reason = f"{audit_reason}: STALE_PROCESSING_CANCELLED"

        # -------------------------------------------------------------
        # REGRA 4: FAILED
        # Se possuir publication_event success: NÃO cancelar cegamente.
        # Manter status='failed', desarmar retry (next_attempt_at = NULL),
        # preservar para reconciliação na V16.4.2A.
        # Se NÃO possuir publication_event success: cancelar e desarmar retry.
        # -------------------------------------------------------------
        elif status == "failed":
            if next_attempt is not None:
                would_clear_next_attempt += 1
            would_disarm_retries += 1

            if has_canonical_success:
                resulting_status = "failed"
                failed_with_success_preserved += 1
                reason = f"{audit_reason}: FAILED_WITH_SUCCESS_INCONSISTENCY_DISARMED: Preserved as failed for V16.4.2A reconciliation"
            else:
                resulting_status = "cancelled"
                reason = f"{audit_reason}: FAILED_WITHOUT_SUCCESS_CANCELLED: Retry disarmed and post cancelled"

        # -------------------------------------------------------------
        # REGRA 5: Outros status (ex.: cancelled)
        # -------------------------------------------------------------
        else:
            resulting_status = status
            if next_attempt is not None:
                would_clear_next_attempt += 1
                reason = f"{audit_reason}: RETRY_DISARMED_FOR_POST"
            else:
                reason = f"{audit_reason}: POST_STATUS_PRESERVED"

        actions_plan.append({
            "scheduled_post_id": post_id,
            "task_id": task_id,
            "platform": platform,
            "channel_id": post.get("channel_id"),
            "previous_status": status,
            "resulting_status": resulting_status,
            "previous_next_attempt_at": next_attempt,
            "resulting_next_attempt_at": None,
            "reason": reason,
        })

    backup_info: Optional[Dict[str, Any]] = None

    if not dry_run:
        # 1. Executa backup obrigatório antes de qualquer mutação
        logger.info(f"Executando backup obrigatório do banco de dados antes do reset: {target_db}")
        backup_info = production_backup.create_database_backup(
            db_path=target_db,
            backup_dir=backup_dir,
        )
        backup_info["backup_file"] = backup_info.get("database_path") or backup_info.get("database_file")
        backup_info["integrity"] = backup_info.get("integrity_check") or "ok"
        logger.info(f"Backup de segurança gerado em: {backup_info['backup_file']} (SHA-256: {backup_info['sha256']})")

        # 2. Executa mutação atômica
        operator_console.init_operator_db(target_db)
        now_iso = datetime.now(timezone.utc).isoformat()
        with scheduler.get_connection(target_db) as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                for act in actions_plan:
                    conn.execute(
                        """
                        UPDATE scheduled_posts
                        SET status = ?, next_attempt_at = NULL
                        WHERE id = ?;
                        """,
                        (act["resulting_status"], act["scheduled_post_id"]),
                    )

                    # Grava trilha de auditoria no operational_events
                    conn.execute(
                        """
                        INSERT INTO operational_events (
                            timestamp, component, severity, event_type, task_id, message, metadata_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            now_iso,
                            "PublishingReset",
                            operator_console.SEVERITY_WARNING,
                            "PRE_REPAIR_PUBLICATION_RESET",
                            act["task_id"],
                            f"Reset operacional da publicação {act['scheduled_post_id']} ({act['platform']}): {act['previous_status']} -> {act['resulting_status']}",
                            json.dumps(act),
                        ),
                    )
                conn.commit()
            except Exception as exc:
                conn.rollback()
                logger.error(f"Erro durante reset atômico de publicações: {exc}")
                raise

    # 3. Auditoria After
    after_audit = audit_after_reset(target_db, before_inv)

    return {
        "dry_run": dry_run,
        "database_path": target_db,
        "preconditions": preconditions,
        "backup_info": backup_info,
        "would_cancel_planned": would_cancel_planned,
        "would_cancel_processing": would_cancel_processing,
        "would_disarm_retries": would_disarm_retries,
        "would_clear_next_attempt": would_clear_next_attempt,
        "would_neutralize_duplicates": would_neutralize_duplicates,
        "already_published_preserved": already_published_preserved,
        "normalized_published": normalized_published,
        "failed_with_success_preserved": failed_with_success_preserved,
        "media_files_preserved": True,
        "actions_plan": actions_plan,
        "before_inventory": before_inv,
        "after_audit": after_audit,
    }


def audit_after_reset(
    db_path: Optional[str] = None,
    before_inventory: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Audita o banco após a simulação ou execução real para comprovar neutralização total."""
    target_db = scheduler.get_db_path(db_path)

    with scheduler.get_connection(target_db) as conn:
        # Executable pending: status IN ('planned', 'ready')
        exec_count = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM scheduled_posts
            WHERE status IN ('planned', 'ready');
            """
        ).fetchone()["cnt"]

        # Armed retries: next_attempt_at IS NOT NULL
        retries_count = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM scheduled_posts
            WHERE next_attempt_at IS NOT NULL;
            """
        ).fetchone()["cnt"]

        # Stale processing
        processing_count = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM scheduled_posts
            WHERE status = 'processing';
            """
        ).fetchone()["cnt"]

        # Total publication_events success
        success_events_count = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM publication_events
            WHERE status = 'success';
            """
        ).fetchone()["cnt"]

        # Contagem de posts cancelados
        cancelled_count = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM scheduled_posts
            WHERE status = 'cancelled';
            """
        ).fetchone()["cnt"]

        # Contagem de posts publicados
        published_count = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM scheduled_posts
            WHERE status = 'published';
            """
        ).fetchone()["cnt"]

    expected_success_count = (
        before_inventory["success_publication_events_count"]
        if before_inventory else success_events_count
    )

    published_success_preserved = (success_events_count == expected_success_count)

    # Inconsistências remanescentes para relatório de entrega da V16.4.2A
    remaining_inconsistencies: List[str] = []
    if before_inventory and before_inventory.get("success_without_coherent_post"):
        for item in before_inventory["success_without_coherent_post"]:
            remaining_inconsistencies.append(
                f"Task {item['task_id']} ({item['platform']}): publicado com sucesso ({item['external_id']}), "
                f"mas sem registro coerente com status='published' em scheduled_posts."
            )

    with scheduler.get_connection(target_db) as conn:
        failed_with_success_cursor = conn.execute(
            """
            SELECT sp.id, sp.task_id, sp.platform, pe.external_id
            FROM scheduled_posts sp
            JOIN publication_events pe ON sp.task_id = pe.task_id AND sp.platform = pe.platform
            WHERE sp.status = 'failed' AND pe.status = 'success';
            """
        )
        for row in failed_with_success_cursor.fetchall():
            remaining_inconsistencies.append(
                f"Post #{row['id']} (Task {row['task_id']}, {row['platform']}): status='failed' "
                f"apesar de publicação com sucesso ({row['external_id']}). Preservado para reconciliação na V16.4.2A."
            )

    return {
        "executable_pending_publications": exec_count,
        "armed_retries": retries_count,
        "stale_processing": processing_count,
        "cancelled_posts_count": cancelled_count,
        "published_posts_count": published_count,
        "success_publication_events_count": success_events_count,
        "published_success_records_preserved": published_success_preserved,
        "media_files_deleted": 0,
        "remaining_inconsistencies": remaining_inconsistencies,
    }


def release_stale_primary_lock(
    db_path: Optional[str] = None,
    dry_run: bool = True,
    confirm_token: Optional[str] = None,
    stale_timeout_seconds: int = operator_console.DEFAULT_INSTANCE_TIMEOUT_SECONDS,
    force_ignore_flags: bool = False,
) -> Dict[str, Any]:
    """Recupera administrativamente o lock PRIMARY_FACTORY stale antes do reset."""
    target_db = scheduler.get_db_path(db_path)
    return operator_console.release_stale_instance_lock(
        lock_key=operator_console.DEFAULT_INSTANCE_LOCK_KEY,
        stale_timeout_seconds=stale_timeout_seconds,
        dry_run=dry_run,
        confirm_token=confirm_token,
        db_path=target_db,
        force_ignore_flags=force_ignore_flags,
    )

