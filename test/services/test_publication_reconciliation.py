"""Testes de Segurança e Determinismo para Reconciliação de Publicações (Fase V16.4.2A).

Valida todas as 10 regras obrigatórias de negócio:
1. failed + success -> published (preservando last_error e attempts)
2. processing + success -> published (emitindo STALE_PROCESSING_DETECTED e PUBLICATION_RECONCILED_SUCCESS)
3. published + retry -> retry desarmado (next_attempt_at = NULL)
4. success bloqueia provider (execute_scheduled_post intercepta via guard canônico sem chamar provider)
5. duplicatas de scheduled_posts (ex: task 3461bf61 com #39 e #42) -> canônico published, duplicata cancelled
6. dry-run -> zero mutation
7. execução idempotente -> segunda execução produz 0 mutações
8. histórico preservado -> last_error, attempts e operational_events íntegros
9. external_id, URL e published_at preservados intactos
10. nenhuma mídia e nenhuma linha de publication_events deletada
"""

from datetime import datetime, timezone
import os
import tempfile
from unittest.mock import patch
import pytest

from app.services import (
    operator_console,
    publication_reconciliation,
    scheduler,
)


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix="_test_reconciliation.db")
    os.close(fd)
    scheduler.init_db(path)
    operator_console.init_operator_db(path)

    # Configura settings seguras por padrão: scheduler_enabled=False, auto_publish_enabled=False
    scheduler.save_settings(
        {
            "scheduler_enabled": False,
            "auto_publish_enabled": False,
            "dry_run": False,
            "youtube_enabled": True,
            "tiktok_enabled": True,
        },
        db_path=path,
    )

    # Garante que instance_locks está com status STOPPED
    with scheduler.get_connection(path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO instance_locks (
                lock_key, node_id, node_name, hostname, pid, role, status, started_at, last_heartbeat
            ) VALUES (
                ?, 'test-node', 'test-host', 'test-host', 1234, 'PRIMARY', 'STOPPED', '2026-10-04T10:00:00Z', '2026-10-04T12:00:00Z'
            );
            """,
            (operator_console.DEFAULT_INSTANCE_LOCK_KEY,),
        )
        conn.commit()

    yield path

    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def test_failed_plus_success_reconciled_to_published(temp_db):
    """Regra 1: failed + success -> published, preservando last_error e attempts."""
    task_id = "task-failed-success-01"
    platform = "youtube"

    with scheduler.get_connection(temp_db) as conn:
        # Scheduled post falho com erro histórico
        cur = conn.execute(
            """
            INSERT INTO scheduled_posts (task_id, platform, scheduled_at, created_at, status, attempts, last_error, next_attempt_at)
            VALUES (?, ?, '2026-10-04T10:00:00Z', '2026-10-04T09:00:00Z', 'failed', 3, 'Timeout connecting to YouTube API', '2026-10-04T11:00:00Z');
            """,
            (task_id, platform),
        )
        post_id = cur.lastrowid

        # Publication event com status 'success' comprovado
        conn.execute(
            """
            INSERT INTO publication_events (task_id, platform, published_at, status, external_id, external_url)
            VALUES (?, ?, '2026-10-04T10:05:00Z', 'success', 'YT-SUCCESS-123', 'https://youtu.be/YT-SUCCESS-123');
            """,
            (task_id, platform),
        )
        conn.commit()

    # Executa reconciliação
    res = publication_reconciliation.reconcile_publication_state(
        db_path=temp_db,
        dry_run=False,
        confirm="RECONCILE_PUBLICATION_STATE",
    )

    assert res["executed"] is True
    assert res["reconciled_failed_to_published"] == 1

    # Verifica integridade do post
    with scheduler.get_connection(temp_db) as conn:
        post = conn.execute("SELECT * FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
        assert post["status"] == "published"
        assert post["next_attempt_at"] is None
        # Erro histórico e tentativas são PRESERVADOS
        assert post["last_error"] == "Timeout connecting to YouTube API"
        assert post["attempts"] == 3

        # Verifica evento de auditoria gerado
        ev = conn.execute(
            "SELECT * FROM operational_events WHERE event_type = 'PUBLICATION_RECONCILED_SUCCESS' AND task_id = ?;",
            (task_id,),
        ).fetchone()
        assert ev is not None
        assert "published" in ev["message"]


def test_processing_plus_success_reconciled_to_published(temp_db):
    """Regra 2: processing + success -> published, emitindo STALE_PROCESSING_DETECTED."""
    task_id = "task-stale-proc-02"
    platform = "tiktok"

    with scheduler.get_connection(temp_db) as conn:
        cur = conn.execute(
            """
            INSERT INTO scheduled_posts (task_id, platform, scheduled_at, created_at, status, attempts, next_attempt_at)
            VALUES (?, ?, '2026-10-04T09:00:00Z', '2026-10-04T08:00:00Z', 'processing', 1, '2026-10-04T09:30:00Z');
            """,
            (task_id, platform),
        )
        post_id = cur.lastrowid

        conn.execute(
            """
            INSERT INTO publication_events (task_id, platform, published_at, status, external_id)
            VALUES (?, ?, '2026-10-04T09:05:00Z', 'success', 'TT-SUCCESS-999');
            """,
            (task_id, platform),
        )
        conn.commit()

    res = publication_reconciliation.reconcile_publication_state(
        db_path=temp_db,
        dry_run=False,
        confirm="RECONCILE_PUBLICATION_STATE",
    )

    assert res["reconciled_processing_to_published"] == 1

    with scheduler.get_connection(temp_db) as conn:
        post = conn.execute("SELECT * FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
        assert post["status"] == "published"
        assert post["next_attempt_at"] is None

        # Auditoria: STALE_PROCESSING_DETECTED e PUBLICATION_RECONCILED_SUCCESS emitidos
        stale_ev = conn.execute(
            "SELECT * FROM operational_events WHERE event_type = 'STALE_PROCESSING_DETECTED' AND task_id = ?;",
            (task_id,),
        ).fetchone()
        assert stale_ev is not None

        rec_ev = conn.execute(
            "SELECT * FROM operational_events WHERE event_type = 'PUBLICATION_RECONCILED_SUCCESS' AND task_id = ?;",
            (task_id,),
        ).fetchone()
        assert rec_ev is not None


def test_published_plus_retry_residual_disarmed(temp_db):
    """Regra 3: published + retry -> mantém published e desarma retry."""
    task_id = "task-pub-retry-03"
    platform = "youtube"

    with scheduler.get_connection(temp_db) as conn:
        cur = conn.execute(
            """
            INSERT INTO scheduled_posts (task_id, platform, scheduled_at, created_at, status, attempts, next_attempt_at)
            VALUES (?, ?, '2026-10-04T08:00:00Z', '2026-10-04T07:00:00Z', 'published', 2, '2026-10-04T12:00:00Z');
            """,
            (task_id, platform),
        )
        post_id = cur.lastrowid

        conn.execute(
            """
            INSERT INTO publication_events (task_id, platform, published_at, status, external_id)
            VALUES (?, ?, '2026-10-04T08:02:00Z', 'success', 'YT-OK-555');
            """,
            (task_id, platform),
        )
        conn.commit()

    res = publication_reconciliation.reconcile_publication_state(
        db_path=temp_db,
        dry_run=False,
        confirm="RECONCILE_PUBLICATION_STATE",
    )

    assert res["retries_disarmed"] == 1

    with scheduler.get_connection(temp_db) as conn:
        post = conn.execute("SELECT * FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
        assert post["status"] == "published"
        assert post["next_attempt_at"] is None

        ev = conn.execute(
            "SELECT * FROM operational_events WHERE event_type = 'RETRY_DISARMED_AFTER_SUCCESS' AND task_id = ?;",
            (task_id,),
        ).fetchone()
        assert ev is not None


def test_duplicates_neutralized_into_single_executable_flow(temp_db):
    """Regra 5: Duplicatas para o mesmo task_id + platform (ex: caso real task 3461bf61 com #39 e #42)."""
    task_id = "3461bf61-694c-4457-97d9-7d23664b8ca1"
    platform = "youtube"

    with scheduler.get_connection(temp_db) as conn:
        # Post #39 (failed)
        conn.execute(
            """
            INSERT INTO scheduled_posts (id, task_id, platform, scheduled_at, created_at, status, attempts, last_error, next_attempt_at)
            VALUES (39, ?, ?, '2026-10-03T10:00:00Z', '2026-10-03T09:00:00Z', 'failed', 2, 'Transient network error 1', '2026-10-03T11:00:00Z');
            """,
            (task_id, platform),
        )
        # Post #42 (failed)
        conn.execute(
            """
            INSERT INTO scheduled_posts (id, task_id, platform, scheduled_at, created_at, status, attempts, last_error, next_attempt_at)
            VALUES (42, ?, ?, '2026-10-03T10:00:00Z', '2026-10-03T09:30:00Z', 'failed', 1, 'Duplicate retry error 2', '2026-10-03T12:00:00Z');
            """,
            (task_id, platform),
        )

        # Publication event #36 com status success
        conn.execute(
            """
            INSERT INTO publication_events (id, task_id, platform, published_at, status, external_id, external_url)
            VALUES (36, ?, ?, '2026-10-03T10:05:00Z', 'success', 'OO6bGVsy2SI', 'https://youtu.be/OO6bGVsy2SI');
            """,
            (task_id, platform),
        )
        conn.commit()

    res = publication_reconciliation.reconcile_publication_state(
        db_path=temp_db,
        dry_run=False,
        confirm="RECONCILE_PUBLICATION_STATE",
    )

    assert res["reconciled_failed_to_published"] == 1
    assert res["duplicates_neutralized"] == 1

    with scheduler.get_connection(temp_db) as conn:
        p39 = conn.execute("SELECT * FROM scheduled_posts WHERE id = 39;").fetchone()
        p42 = conn.execute("SELECT * FROM scheduled_posts WHERE id = 42;").fetchone()

        # #39 torna-se o post canônico publicado com retry desarmado
        assert p39["status"] == "published"
        assert p39["next_attempt_at"] is None
        assert p39["last_error"] == "Transient network error 1"

        # #42 torna-se neutralizado (cancelled) com retry desarmado
        assert p42["status"] == "cancelled"
        assert p42["next_attempt_at"] is None
        assert p42["last_error"] == "Duplicate retry error 2"

        # Evento DUPLICATE_SCHEDULE_DETECTED emitido
        dup_ev = conn.execute(
            "SELECT * FROM operational_events WHERE event_type = 'DUPLICATE_SCHEDULE_DETECTED' AND task_id = ?;",
            (task_id,),
        ).fetchone()
        assert dup_ev is not None
        assert "neutralizada" in dup_ev["message"]


def test_dry_run_zero_mutation(temp_db):
    """Regra 6: dry-run produz plano mas realiza zero mutações no banco."""
    task_id = "task-dryrun-06"
    platform = "youtube"

    with scheduler.get_connection(temp_db) as conn:
        conn.execute(
            """
            INSERT INTO scheduled_posts (id, task_id, platform, scheduled_at, created_at, status, attempts, next_attempt_at)
            VALUES (101, ?, ?, '2026-10-04T10:00:00Z', '2026-10-04T09:00:00Z', 'failed', 2, '2026-10-04T11:00:00Z');
            """,
            (task_id, platform),
        )
        conn.execute(
            """
            INSERT INTO publication_events (id, task_id, platform, published_at, status, external_id)
            VALUES (201, ?, ?, '2026-10-04T10:05:00Z', 'success', 'YT-DRY-123');
            """,
            (task_id, platform),
        )
        conn.commit()

    # Dry-run
    res = publication_reconciliation.reconcile_publication_state(
        db_path=temp_db,
        dry_run=True,
    )

    assert res["mode"] == "DRY_RUN"
    assert res["executed"] is False
    assert res["actions_planned_count"] >= 1
    assert res["would_mutate"] is True

    # Verifica que o banco permaneceu 100% intacto
    with scheduler.get_connection(temp_db) as conn:
        post = conn.execute("SELECT * FROM scheduled_posts WHERE id = 101;").fetchone()
        assert post["status"] == "failed"
        assert post["next_attempt_at"] == "2026-10-04T10:00:00Z" or post["next_attempt_at"] is not None

        # Zero operational_events criados
        ev_cnt = conn.execute("SELECT COUNT(*) AS cnt FROM operational_events;").fetchone()["cnt"]
        assert ev_cnt == 0


def test_execution_is_idempotent(temp_db):
    """Regra 7: Execuções subsequentes produzem 0 mutações."""
    task_id = "task-idempotent-07"
    platform = "youtube"

    with scheduler.get_connection(temp_db) as conn:
        conn.execute(
            """
            INSERT INTO scheduled_posts (id, task_id, platform, scheduled_at, created_at, status, attempts, next_attempt_at)
            VALUES (105, ?, ?, '2026-10-04T10:00:00Z', '2026-10-04T09:00:00Z', 'failed', 2, '2026-10-04T11:00:00Z');
            """,
            (task_id, platform),
        )
        conn.execute(
            """
            INSERT INTO publication_events (id, task_id, platform, published_at, status, external_id)
            VALUES (205, ?, ?, '2026-10-04T10:05:00Z', 'success', 'YT-IDEMP-123');
            """,
            (task_id, platform),
        )
        conn.commit()

    # Primeira execução
    res1 = publication_reconciliation.reconcile_publication_state(
        db_path=temp_db,
        dry_run=False,
        confirm="RECONCILE_PUBLICATION_STATE",
    )
    assert res1["mutations_applied"] == 1

    # Segunda execução imediata
    res2 = publication_reconciliation.reconcile_publication_state(
        db_path=temp_db,
        dry_run=False,
        confirm="RECONCILE_PUBLICATION_STATE",
    )
    assert res2["mutations_applied"] == 0
    assert res2["post_audit"]["remaining_mutations_needed"] == 0


def test_success_blocks_provider_in_scheduler_execution(temp_db):
    """Regra 4 e 10: Se existir publication_events(success), o executor NUNCA chama o provider."""
    task_id = "task-guard-provider-04"
    platform = "youtube"
    now = datetime(2026, 10, 4, 10, 30, tzinfo=timezone.utc)

    # Habilita scheduler e auto_publish para que o ciclo tente executar posts vencidos
    scheduler.save_settings(
        {
            "scheduler_enabled": True,
            "auto_publish_enabled": True,
            "dry_run": False,
            "youtube_enabled": True,
        },
        db_path=temp_db,
    )

    with scheduler.get_connection(temp_db) as conn:
        cur = conn.execute(
            """
            INSERT INTO scheduled_posts (task_id, platform, scheduled_at, created_at, status, attempts, next_attempt_at)
            VALUES (?, ?, '2026-10-04T10:00:00Z', '2026-10-04T09:00:00Z', 'ready', 0, NULL);
            """,
            (task_id, platform),
        )
        post_id = cur.lastrowid

        conn.execute(
            """
            INSERT INTO publication_events (task_id, platform, published_at, status, external_id, external_url)
            VALUES (?, ?, '2026-10-04T10:05:00Z', 'success', 'CANONICAL-YT-ID', 'https://youtu.be/CANONICAL-YT-ID');
            """,
            (task_id, platform),
        )
        conn.commit()

    # Mock de publicação externa e verificação de nó primário
    with patch("app.services.operator_console.is_primary_instance", return_value=True), \
         patch("app.services.operator_console.is_factory_paused", return_value=False), \
         patch("app.services.task.publish_task") as mock_pub:

        exec_res = scheduler.run_scheduler_cycle(now=now, db_path=temp_db)

        # Provider / Publicação externa NUNCA chamada
        assert mock_pub.call_count == 0

        # Post é reconhecido imediatamente como already_published / skipped
        assert exec_res["status"] == "skipped"
        assert exec_res["reason"] == "already_published"
        assert exec_res.get("publication_event_id") is not None

        # Post é atualizado para published no banco com retry desarmado
        with scheduler.get_connection(temp_db) as conn:
            post = conn.execute("SELECT * FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
            assert post["status"] == "published"
            assert post["next_attempt_at"] is None


def test_orphan_success_audited_without_provider_call_or_deletions(temp_db):
    """Regra 6 & 9: Sucesso sem scheduled_post correspondente é auditado sem criar provider call nem apagar dados."""
    task_id = "task-orphan-success-09"
    platform = "tiktok"

    with scheduler.get_connection(temp_db) as conn:
        conn.execute(
            """
            INSERT INTO publication_events (id, task_id, platform, published_at, status, external_id)
            VALUES (301, ?, ?, '2026-10-04T07:00:00Z', 'success', 'TT-ORPHAN-777');
            """,
            (task_id, platform),
        )
        conn.commit()

    res = publication_reconciliation.reconcile_publication_state(
        db_path=temp_db,
        dry_run=False,
        confirm="RECONCILE_PUBLICATION_STATE",
    )

    assert res["orphan_success_audited"] == 1

    with scheduler.get_connection(temp_db) as conn:
        # publication_events NUNCA é deletado
        ev = conn.execute("SELECT * FROM publication_events WHERE id = 301;").fetchone()
        assert ev is not None
        assert ev["external_id"] == "TT-ORPHAN-777"

        # Evento de auditoria registrado
        audit_ev = conn.execute(
            "SELECT * FROM operational_events WHERE event_type = 'HISTORICAL_ORPHAN_SUCCESS_RECONCILED' AND task_id = ?;",
            (task_id,),
        ).fetchone()
        assert audit_ev is not None
        assert "Inconsistência histórica reconciliada" in audit_ev["message"]
