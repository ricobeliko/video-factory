"""Serviço de Reconciliação Determinística de Publicações (Fase V16.4.2A).

Garante a sincronização determinística entre publication_events e scheduled_posts,
tratando publication_events com status='success' como evidência canônica de publicação concluída.

REGRAS DE RECONCILIAÇÃO (V16.4.2A):
1. Se existir publication_events(status='success') para (task_id, platform):
   - Nunca chamar provider novamente e nunca republicar.
   - Todo scheduled_post correspondente deve ficar em estado não executável.
   - Retries devem ser desarmados (next_attempt_at = NULL).
   - Preservar external_id, external_url, published_at e histórico intactos.
2. failed + success:
   - Reconcilia o scheduled_post canônico para status='published' e next_attempt_at = NULL.
   - Preserva last_error e attempts como evidência histórica.
   - Emite evento auditável: PUBLICATION_RECONCILED_SUCCESS.
3. processing + success:
   - Reconcilia para status='published' e next_attempt_at = NULL.
   - Emite eventos auditáveis: STALE_PROCESSING_DETECTED e PUBLICATION_RECONCILED_SUCCESS.
4. published + retry residual:
   - Permanece status='published' e desarma retry (next_attempt_at = NULL).
   - Emite evento auditável: RETRY_DISARMED_AFTER_SUCCESS.
5. Duplicatas de scheduled_posts para o mesmo (task_id, platform):
   - Elegem exatamente um post canônico (published).
   - Neutralizam os posts duplicados excedentes para status='cancelled' com next_attempt_at = NULL.
   - Preservam histórico intacto.
   - Emitem evento auditável: DUPLICATE_SCHEDULE_DETECTED.
6. success sem scheduled_post correspondente (órfão histórico):
   - Registrado como inconsistência histórica reconciliada de forma auditável em operational_events.
   - Nenhuma chamada a provider ou mutação externa é inventada.
7. Preservação estrita:
   - Zero linhas deletadas em publication_events.
   - Zero linhas deletadas em scheduled_posts.
   - Zero arquivos de mídia deletados.
   - Nenhuma chamada a provedores externos (YouTube, TikTok, Post For Me).
8. Segurança e Idempotência:
   - Fail-closed: exige scheduler_enabled=False, auto_publish_enabled=False e active_primary=False.
   - Cria backup consistente com PRAGMA integrity_check e SHA-256 antes de qualquer mutação real.
   - Idempotência comprovada (execuções repetidas resultam em 0 mutações).
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from app.services import operator_console, production_backup, scheduler


class ReconciliationPreconditionError(RuntimeError):
    """Exceção levantada quando pré-condições operacionais de segurança não são atendidas."""
    pass


def check_reconciliation_preconditions(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Valida se o ambiente está em estado seguro para reconciliação."""
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
            "A fábrica deve estar parada antes da reconciliação."
        )

    return {
        "passed": len(errors) == 0,
        "database_exists": True,
        "scheduler_enabled": sched_enabled,
        "auto_publish_enabled": auto_pub_enabled,
        "active_primary": active_primary,
        "errors": errors,
    }


def inventory_reconciliation(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Analisa inconsistências entre publication_events e scheduled_posts."""
    target_db = scheduler.get_db_path(db_path)
    if not os.path.isfile(target_db):
        raise FileNotFoundError(f"Banco de dados não encontrado: {target_db}")

    with scheduler.get_connection(target_db) as conn:
        # 1. Todos os publication_events com status 'success'
        pub_rows = conn.execute(
            """
            SELECT id, task_id, platform, published_at, status, external_id,
                   external_url, provider_request_id, profile_id, channel_id, privacy_status
            FROM publication_events
            WHERE status = 'success'
            ORDER BY id ASC;
            """
        ).fetchall()
        success_events = [dict(r) for r in pub_rows]

        # 2. Todos os scheduled_posts
        post_rows = conn.execute(
            """
            SELECT id, task_id, platform, scheduled_at, status, created_at,
                   attempts, last_error, next_attempt_at, profile_id, channel_id
            FROM scheduled_posts
            ORDER BY id ASC;
            """
        ).fetchall()
        all_posts = [dict(r) for r in post_rows]

    # Agrupa posts por (task_id, platform)
    posts_by_target: Dict[tuple[str, str], List[Dict[str, Any]]] = {}
    for p in all_posts:
        tid = p.get("task_id") or ""
        plat = (p.get("platform") or "").lower().strip()
        key = (tid, plat)
        posts_by_target.setdefault(key, []).append(p)

    # Agrupa eventos de sucesso por (task_id, platform)
    events_by_target: Dict[tuple[str, str], List[Dict[str, Any]]] = {}
    for ev in success_events:
        tid = ev.get("task_id") or ""
        plat = (ev.get("platform") or "").lower().strip()
        key = (tid, plat)
        events_by_target.setdefault(key, []).append(ev)

    actions_plan: List[Dict[str, Any]] = []
    failed_to_published: List[Dict[str, Any]] = []
    processing_to_published: List[Dict[str, Any]] = []
    pending_to_published: List[Dict[str, Any]] = []
    cancelled_to_published: List[Dict[str, Any]] = []
    retries_to_disarm: List[Dict[str, Any]] = []
    duplicates_to_neutralize: List[Dict[str, Any]] = []
    orphan_success_events: List[Dict[str, Any]] = []
    already_coherent: List[Dict[str, Any]] = []

    # Iterar sobre todos os alvos com evento de sucesso comprovado
    for (tid, plat), ev_list in events_by_target.items():
        primary_ev = ev_list[0]
        matching_posts = posts_by_target.get((tid, plat), [])

        if not matching_posts:
            # Caso 1: Sucesso sem scheduled_post correspondente (órfão histórico)
            orphan_success_events.append({
                "task_id": tid,
                "platform": plat,
                "publication_event_id": primary_ev["id"],
                "external_id": primary_ev.get("external_id"),
                "published_at": primary_ev.get("published_at"),
            })
            continue

        # Selecionar o post canônico
        # Preferência: post que já está 'published'; senão, post com menor ID
        published_posts = [p for p in matching_posts if p["status"] == "published"]
        if published_posts:
            canonical_post = published_posts[0]
        else:
            canonical_post = matching_posts[0]

        # 1. Tratar o post canônico
        c_status = canonical_post["status"]
        c_id = canonical_post["id"]
        c_next = canonical_post.get("next_attempt_at")

        if c_status == "failed":
            failed_to_published.append({
                "scheduled_post_id": c_id,
                "task_id": tid,
                "platform": plat,
                "previous_status": "failed",
                "resulting_status": "published",
                "last_error": canonical_post.get("last_error"),
                "attempts": canonical_post.get("attempts"),
                "publication_event_id": primary_ev["id"],
                "external_id": primary_ev.get("external_id"),
                "published_at": primary_ev.get("published_at"),
            })
            actions_plan.append({
                "action": "reconcile_to_published",
                "scheduled_post_id": c_id,
                "task_id": tid,
                "platform": plat,
                "previous_status": "failed",
                "resulting_status": "published",
                "disarm_retry": c_next is not None,
                "last_error": canonical_post.get("last_error"),
                "publication_event_id": primary_ev["id"],
            })
        elif c_status == "processing":
            processing_to_published.append({
                "scheduled_post_id": c_id,
                "task_id": tid,
                "platform": plat,
                "previous_status": "processing",
                "resulting_status": "published",
                "publication_event_id": primary_ev["id"],
                "external_id": primary_ev.get("external_id"),
            })
            actions_plan.append({
                "action": "reconcile_to_published",
                "scheduled_post_id": c_id,
                "task_id": tid,
                "platform": plat,
                "previous_status": "processing",
                "resulting_status": "published",
                "disarm_retry": c_next is not None,
                "publication_event_id": primary_ev["id"],
            })
        elif c_status in ("planned", "ready", "queued"):
            pending_to_published.append({
                "scheduled_post_id": c_id,
                "task_id": tid,
                "platform": plat,
                "previous_status": c_status,
                "resulting_status": "published",
                "publication_event_id": primary_ev["id"],
            })
            actions_plan.append({
                "action": "reconcile_to_published",
                "scheduled_post_id": c_id,
                "task_id": tid,
                "platform": plat,
                "previous_status": c_status,
                "resulting_status": "published",
                "disarm_retry": c_next is not None,
                "publication_event_id": primary_ev["id"],
            })
        elif c_status == "cancelled":
            cancelled_to_published.append({
                "scheduled_post_id": c_id,
                "task_id": tid,
                "platform": plat,
                "previous_status": "cancelled",
                "resulting_status": "published",
                "publication_event_id": primary_ev["id"],
            })
            actions_plan.append({
                "action": "reconcile_to_published",
                "scheduled_post_id": c_id,
                "task_id": tid,
                "platform": plat,
                "previous_status": "cancelled",
                "resulting_status": "published",
                "disarm_retry": c_next is not None,
                "publication_event_id": primary_ev["id"],
            })
        elif c_status == "published":
            if c_next is not None:
                retries_to_disarm.append({
                    "scheduled_post_id": c_id,
                    "task_id": tid,
                    "platform": plat,
                    "next_attempt_at": c_next,
                })
                actions_plan.append({
                    "action": "disarm_retry",
                    "scheduled_post_id": c_id,
                    "task_id": tid,
                    "platform": plat,
                    "previous_next_attempt_at": c_next,
                })
            else:
                already_coherent.append({
                    "scheduled_post_id": c_id,
                    "task_id": tid,
                    "platform": plat,
                    "publication_event_id": primary_ev["id"],
                })

        # 2. Tratar duplicatas (posts adicionais para o mesmo task_id + platform)
        for dup in matching_posts:
            if dup["id"] == canonical_post["id"]:
                continue

            dup_id = dup["id"]
            dup_status = dup["status"]
            dup_next = dup.get("next_attempt_at")

            # Se a duplicata não está cancelada, neutraliza para cancelled
            if dup_status != "cancelled":
                duplicates_to_neutralize.append({
                    "canonical_post_id": canonical_post["id"],
                    "duplicate_post_id": dup_id,
                    "task_id": tid,
                    "platform": plat,
                    "previous_status": dup_status,
                    "resulting_status": "cancelled",
                    "publication_event_id": primary_ev["id"],
                    "last_error": dup.get("last_error"),
                    "attempts": dup.get("attempts"),
                })
                actions_plan.append({
                    "action": "neutralize_duplicate",
                    "canonical_post_id": canonical_post["id"],
                    "scheduled_post_id": dup_id,
                    "task_id": tid,
                    "platform": plat,
                    "previous_status": dup_status,
                    "resulting_status": "cancelled",
                    "disarm_retry": dup_next is not None,
                    "publication_event_id": primary_ev["id"],
                })
            elif dup_next is not None:
                # Já cancelado, mas com retry armado
                retries_to_disarm.append({
                    "scheduled_post_id": dup_id,
                    "task_id": tid,
                    "platform": plat,
                    "next_attempt_at": dup_next,
                })
                actions_plan.append({
                    "action": "disarm_retry",
                    "scheduled_post_id": dup_id,
                    "task_id": tid,
                    "platform": plat,
                    "previous_next_attempt_at": dup_next,
                })

    # Verificar retries residuais armados em outros scheduled_posts não cobertos por sucesso
    for (tid, plat), post_list in posts_by_target.items():
        if (tid, plat) in events_by_target:
            continue  # Já tratado acima
        for p in post_list:
            if p.get("next_attempt_at") is not None and p["status"] in ("published", "failed", "cancelled"):
                retries_to_disarm.append({
                    "scheduled_post_id": p["id"],
                    "task_id": tid,
                    "platform": plat,
                    "next_attempt_at": p["next_attempt_at"],
                })
                actions_plan.append({
                    "action": "disarm_retry",
                    "scheduled_post_id": p["id"],
                    "task_id": tid,
                    "platform": plat,
                    "previous_next_attempt_at": p["next_attempt_at"],
                })

    return {
        "database_path": target_db,
        "total_success_events": len(success_events),
        "total_scheduled_posts": len(all_posts),
        "already_coherent_count": len(already_coherent),
        "failed_to_published": failed_to_published,
        "failed_to_published_count": len(failed_to_published),
        "processing_to_published": processing_to_published,
        "processing_to_published_count": len(processing_to_published),
        "pending_to_published": pending_to_published,
        "pending_to_published_count": len(pending_to_published),
        "cancelled_to_published": cancelled_to_published,
        "cancelled_to_published_count": len(cancelled_to_published),
        "retries_to_disarm": retries_to_disarm,
        "retries_to_disarm_count": len(retries_to_disarm),
        "duplicates_to_neutralize": duplicates_to_neutralize,
        "duplicates_to_neutralize_count": len(duplicates_to_neutralize),
        "orphan_success_events": orphan_success_events,
        "orphan_success_events_count": len(orphan_success_events),
        "actions_plan": actions_plan,
        "total_mutations_planned": len(actions_plan),
    }


def reconcile_publication_state(
    db_path: Optional[str] = None,
    dry_run: bool = True,
    confirm: Optional[str] = None,
    force_preconditions: bool = False,
) -> Dict[str, Any]:
    """Executa a reconciliação determinística entre publication_events e scheduled_posts."""
    target_db = scheduler.get_db_path(db_path)
    preconditions = check_reconciliation_preconditions(target_db)

    if not dry_run:
        if not force_preconditions and not preconditions["passed"]:
            raise ReconciliationPreconditionError(
                f"Pré-condições operacionais falharam: {'; '.join(preconditions['errors'])}"
            )
        if confirm != "RECONCILE_PUBLICATION_STATE":
            raise ValueError(
                f"Confirmação inválida para execução real. Forneça confirm='RECONCILE_PUBLICATION_STATE'. Recebido: {confirm}"
            )

    inventory = inventory_reconciliation(target_db)
    actions = inventory["actions_plan"]

    if dry_run:
        return {
            "mode": "DRY_RUN",
            "preconditions": preconditions,
            "inventory": inventory,
            "actions_planned_count": len(actions),
            "reconciled_failed_to_published": inventory["failed_to_published_count"],
            "reconciled_processing_to_published": inventory["processing_to_published_count"],
            "reconciled_pending_to_published": inventory["pending_to_published_count"],
            "reconciled_cancelled_to_published": inventory["cancelled_to_published_count"],
            "retries_disarmed": inventory["retries_to_disarm_count"],
            "duplicates_neutralized": inventory["duplicates_to_neutralize_count"],
            "orphan_success_audited": inventory["orphan_success_events_count"],
            "would_mutate": len(actions) > 0 or inventory["orphan_success_events_count"] > 0,
            "executed": False,
        }

    # EXECUÇÃO REAL
    backup_result = production_backup.create_database_backup(
        db_path=target_db,
    )
    if not backup_result.get("success"):
        raise RuntimeError(f"Falha ao criar backup obrigatório pré-reconciliação: {backup_result.get('error')}")

    mutations_applied = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    def _record_audit_event(
        connection: sqlite3.Connection,
        component: str,
        severity: str,
        event_type: str,
        task_id: Optional[str],
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        meta_str = json.dumps(metadata) if metadata else None
        connection.execute(
            """
            INSERT INTO operational_events (
                timestamp, component, severity, event_type, task_id, message, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (now_iso, component, severity, event_type, task_id, message[:1000], meta_str),
        )

    with scheduler.get_connection(target_db) as conn:
        cursor = conn.cursor()

        # 1. Aplicar ações do plano em transação atômica
        for act in actions:
            action_type = act["action"]
            post_id = act["scheduled_post_id"]
            tid = act["task_id"]
            plat = act["platform"]

            if action_type == "reconcile_to_published":
                prev_status = act.get("previous_status")
                ev_id = act.get("publication_event_id")

                # Se era processing, emite STALE_PROCESSING_DETECTED
                if prev_status == "processing":
                    _record_audit_event(
                        conn,
                        component="PublicationReconciliation",
                        severity=operator_console.SEVERITY_WARNING,
                        event_type="STALE_PROCESSING_DETECTED",
                        task_id=tid,
                        message=f"Stale processing detectado no post #{post_id} ({plat}). Sucesso comprovado no evento #{ev_id}.",
                        metadata={"scheduled_post_id": post_id, "task_id": tid, "platform": plat, "publication_event_id": ev_id},
                    )

                # Atualiza para published, desarmando retry e preservando last_error e attempts
                cursor.execute(
                    """
                    UPDATE scheduled_posts
                    SET status = 'published', next_attempt_at = NULL
                    WHERE id = ?;
                    """,
                    (post_id,),
                )
                mutations_applied += 1

                # Emite PUBLICATION_RECONCILED_SUCCESS
                _record_audit_event(
                    conn,
                    component="PublicationReconciliation",
                    severity=operator_console.SEVERITY_INFO,
                    event_type="PUBLICATION_RECONCILED_SUCCESS",
                    task_id=tid,
                    message=f"Post #{post_id} ({plat}) reconciliado de {prev_status} -> published com base no evento #{ev_id}.",
                    metadata={
                        "scheduled_post_id": post_id,
                        "task_id": tid,
                        "platform": plat,
                        "previous_status": prev_status,
                        "resulting_status": "published",
                        "publication_event_id": ev_id,
                        "last_error": act.get("last_error"),
                    },
                )

            elif action_type == "neutralize_duplicate":
                canonical_id = act["canonical_post_id"]
                prev_status = act.get("previous_status")
                ev_id = act.get("publication_event_id")

                # Neutraliza a duplicata para cancelled com retry desarmado
                cursor.execute(
                    """
                    UPDATE scheduled_posts
                    SET status = 'cancelled', next_attempt_at = NULL
                    WHERE id = ?;
                    """,
                    (post_id,),
                )
                mutations_applied += 1

                _record_audit_event(
                    conn,
                    component="PublicationReconciliation",
                    severity=operator_console.SEVERITY_WARNING,
                    event_type="DUPLICATE_SCHEDULE_DETECTED",
                    task_id=tid,
                    message=f"Duplicata de scheduled_post #{post_id} ({plat}) neutralizada (status='cancelled') em favor do post canônico #{canonical_id}.",
                    metadata={
                        "canonical_post_id": canonical_id,
                        "duplicate_post_id": post_id,
                        "task_id": tid,
                        "platform": plat,
                        "previous_status": prev_status,
                        "resulting_status": "cancelled",
                        "publication_event_id": ev_id,
                    },
                )

            elif action_type == "disarm_retry":
                cursor.execute(
                    """
                    UPDATE scheduled_posts
                    SET next_attempt_at = NULL
                    WHERE id = ?;
                    """,
                    (post_id,),
                )
                mutations_applied += 1

                _record_audit_event(
                    conn,
                    component="PublicationReconciliation",
                    severity=operator_console.SEVERITY_INFO,
                    event_type="RETRY_DISARMED_AFTER_SUCCESS",
                    task_id=tid,
                    message=f"Retry desarmado para post #{post_id} ({plat}). next_attempt_at limpo.",
                    metadata={
                        "scheduled_post_id": post_id,
                        "task_id": tid,
                        "platform": plat,
                        "previous_next_attempt_at": act.get("previous_next_attempt_at"),
                    },
                )

        # 2. Registrar sucessos órfãos históricos como reconciliados
        for orphan in inventory["orphan_success_events"]:
            _record_audit_event(
                conn,
                component="PublicationReconciliation",
                severity=operator_console.SEVERITY_INFO,
                event_type="HISTORICAL_ORPHAN_SUCCESS_RECONCILED",
                task_id=orphan["task_id"],
                message=(
                    f"Inconsistência histórica reconciliada: evento de sucesso #{orphan['publication_event_id']} "
                    f"({orphan['platform']}) comprovado ({orphan.get('external_id')}), sem scheduled_post. "
                    "Evidência canônica preservada sem chamada a provedor."
                ),
                metadata=orphan,
            )

        conn.commit()

    # Pós-auditoria: verificar inventário atualizado
    post_inventory = inventory_reconciliation(target_db)

    # Contagem de posts executáveis remanescentes
    with scheduler.get_connection(target_db) as conn:
        exec_count = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM scheduled_posts
            WHERE status IN ('planned', 'ready', 'queued', 'processing')
               OR (next_attempt_at IS NOT NULL AND status != 'cancelled');
            """
        ).fetchone()["cnt"]

        armed_retries_count = conn.execute(
            "SELECT COUNT(*) AS cnt FROM scheduled_posts WHERE next_attempt_at IS NOT NULL;"
        ).fetchone()["cnt"]

        stale_processing_count = conn.execute(
            "SELECT COUNT(*) AS cnt FROM scheduled_posts WHERE status = 'processing';"
        ).fetchone()["cnt"]

        published_posts_count = conn.execute(
            "SELECT COUNT(*) AS cnt FROM scheduled_posts WHERE status = 'published';"
        ).fetchone()["cnt"]

    logger.info(
        f"[RECONCILIATION] Concluída com sucesso: {mutations_applied} mutações aplicadas. "
        f"Executáveis={exec_count}, Retries={armed_retries_count}, Published={published_posts_count}"
    )

    return {
        "mode": "EXECUTE",
        "preconditions": preconditions,
        "backup": {
            "path": backup_result.get("database_path"),
            "sha256": backup_result.get("sha256"),
            "integrity": backup_result.get("integrity_check"),
        },
        "mutations_applied": mutations_applied,
        "reconciled_failed_to_published": inventory["failed_to_published_count"],
        "reconciled_processing_to_published": inventory["processing_to_published_count"],
        "reconciled_pending_to_published": inventory["pending_to_published_count"],
        "reconciled_cancelled_to_published": inventory["cancelled_to_published_count"],
        "retries_disarmed": inventory["retries_to_disarm_count"],
        "duplicates_neutralized": inventory["duplicates_to_neutralize_count"],
        "orphan_success_audited": inventory["orphan_success_events_count"],
        "post_audit": {
            "executable_pending_publications": exec_count,
            "armed_retries": armed_retries_count,
            "stale_processing": stale_processing_count,
            "published_posts_count": published_posts_count,
            "remaining_mutations_needed": post_inventory["total_mutations_planned"],
        },
        "executed": True,
    }
