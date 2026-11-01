import json
import os
import sqlite3
import tempfile
import pytest

from app.services import copyright_gate
from app.services import scheduler
from app.services import operator_console
from app.services import autonomous_production


def _create_test_db(db_path: str):
    scheduler.init_db(db_path)
    operator_console.init_operator_db(db_path)


def _simulate_old_batch_logic(conn):
    """Simulação fiel da lógica anterior de autonomous_production.py (linhas 857-869)."""
    adverse_copyright = set()
    has_op = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='operational_events';").fetchone()
    if has_op:
        for row_op in conn.execute("SELECT metadata_json FROM operational_events WHERE event_type = 'PUBLICATION_COPYRIGHT_STATUS_SET' ORDER BY id DESC;").fetchall():
            try:
                m = json.loads(row_op["metadata_json"] or "{}")
                st_cp = m.get("copyright_status")
                if st_cp in ("claimed", "blocked", "strike"):
                    tid_cp = m.get("task_id")
                    if tid_cp:
                        adverse_copyright.add(tid_cp)
            except Exception:
                pass
    return adverse_copyright


def test_old_batch_logic_fails_on_claimed_then_cleared():
    """Confirma que a lógica antiga falha: marca adverso em 'claimed depois liberado'."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_old_parity.db")
        _create_test_db(db_path)
        with scheduler.get_connection(db_path) as conn:
            t2 = "task_claimed_then_cleared"
            conn.execute(
                "INSERT INTO operational_events (component, event_type, severity, message, timestamp, metadata_json) "
                "VALUES ('copyright_gate', 'PUBLICATION_COPYRIGHT_STATUS_SET', 'WARNING', 'Claimed', '2026-11-01T00:00:02', ?);",
                (json.dumps({"task_id": t2, "copyright_status": "claimed"}),)
            )
            conn.execute(
                "INSERT INTO operational_events (component, event_type, severity, message, timestamp, metadata_json) "
                "VALUES ('copyright_gate', 'PUBLICATION_COPYRIGHT_STATUS_SET', 'INFO', 'Cleaned', '2026-11-01T00:00:03', ?);",
                (json.dumps({"task_id": t2, "copyright_status": "clean_manual"}),)
            )
            old_adverse = _simulate_old_batch_logic(conn)

        # Na lógica antiga, t2 era marcado adverso indevidamente!
        assert t2 in old_adverse, "Lógica antiga deveria marcar adverso erroneamente"

        # Enquanto a função original canônica considera limpo:
        orig = copyright_gate.get_publication_copyright_status(task_id=t2, db_path=db_path)
        assert orig.get("copyright_status") == "clean_manual"


def test_copyright_batch_vs_original_parity():
    """Valida paridade exata entre a resolução em lote e get_publication_copyright_status nos 6 casos."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_parity.db")
        _create_test_db(db_path)

        with scheduler.get_connection(db_path) as conn:
            # Setup dos 6 cenários

            # Cenário 1: claimed por task_id
            t1 = "task_claimed_direct"
            conn.execute(
                "INSERT INTO operational_events (component, event_type, severity, message, timestamp, metadata_json) "
                "VALUES ('copyright_gate', 'PUBLICATION_COPYRIGHT_STATUS_SET', 'WARNING', 'Claimed', '2026-11-01T00:00:01', ?);",
                (json.dumps({"task_id": t1, "copyright_status": "claimed"}),)
            )

            # Cenário 2: claimed depois liberado (NÃO deve bloquear)
            t2 = "task_claimed_then_cleared"
            conn.execute(
                "INSERT INTO operational_events (component, event_type, severity, message, timestamp, metadata_json) "
                "VALUES ('copyright_gate', 'PUBLICATION_COPYRIGHT_STATUS_SET', 'WARNING', 'Claimed', '2026-11-01T00:00:02', ?);",
                (json.dumps({"task_id": t2, "copyright_status": "claimed"}),)
            )
            conn.execute(
                "INSERT INTO operational_events (component, event_type, severity, message, timestamp, metadata_json) "
                "VALUES ('copyright_gate', 'PUBLICATION_COPYRIGHT_STATUS_SET', 'INFO', 'Cleaned', '2026-11-01T00:00:03', ?);",
                (json.dumps({"task_id": t2, "copyright_status": "clean_manual"}),)
            )

            # Cenário 3: liberado depois claimed (DEVE bloquear)
            t3 = "task_cleared_then_claimed"
            conn.execute(
                "INSERT INTO operational_events (component, event_type, severity, message, timestamp, metadata_json) "
                "VALUES ('copyright_gate', 'PUBLICATION_COPYRIGHT_STATUS_SET', 'INFO', 'Cleaned', '2026-11-01T00:00:04', ?);",
                (json.dumps({"task_id": t3, "copyright_status": "clean_manual"}),)
            )
            conn.execute(
                "INSERT INTO operational_events (component, event_type, severity, message, timestamp, metadata_json) "
                "VALUES ('copyright_gate', 'PUBLICATION_COPYRIGHT_STATUS_SET', 'WARNING', 'Claimed', '2026-11-01T00:00:05', ?);",
                (json.dumps({"task_id": t3, "copyright_status": "claimed"}),)
            )

            # Cenário 4: registro só por external_id
            t4 = "task_match_by_external_id"
            conn.execute(
                "INSERT INTO publication_events (task_id, platform, published_at, status, external_id) "
                "VALUES (?, 'youtube', '2026-11-01T00:00:00', 'published', 'yt-ext-444');",
                (t4,)
            )
            conn.execute(
                "INSERT INTO operational_events (component, event_type, severity, message, timestamp, metadata_json) "
                "VALUES ('copyright_gate', 'PUBLICATION_COPYRIGHT_STATUS_SET', 'WARNING', 'Claimed by ext', '2026-11-01T00:00:06', ?);",
                (json.dumps({"external_id": "yt-ext-444", "copyright_status": "claimed"}),)
            )

            # Cenário 5: registro só por publication_event_id
            t5 = "task_match_by_pub_id"
            cur5 = conn.execute(
                "INSERT INTO publication_events (task_id, platform, published_at, status, external_id) "
                "VALUES (?, 'youtube', '2026-11-01T00:00:00', 'published', 'yt-ext-555');",
                (t5,)
            )
            pub_id_5 = cur5.lastrowid
            conn.execute(
                "INSERT INTO operational_events (component, event_type, severity, message, timestamp, metadata_json) "
                "VALUES ('copyright_gate', 'PUBLICATION_COPYRIGHT_STATUS_SET', 'ERROR', 'Strike by pub id', '2026-11-01T00:00:07', ?);",
                (json.dumps({"publication_event_id": pub_id_5, "copyright_status": "strike"}),)
            )

            # Cenário 6: sem registro
            t6 = "task_no_record_at_all"

        tasks = [t1, t2, t3, t4, t5, t6]

        # 1. Resolução individual canônica original
        original_statuses = {}
        for tid in tasks:
            st_info = copyright_gate.get_publication_copyright_status(task_id=tid, db_path=db_path)
            original_statuses[tid] = st_info.get("copyright_status")

        assert original_statuses[t1] == "claimed"
        assert original_statuses[t2] == "clean_manual"  # O mais recente liberou!
        assert original_statuses[t3] == "claimed"       # O mais recente bloqueou!
        assert original_statuses[t4] == "claimed"       # Casou por external_id!
        assert original_statuses[t5] == "strike"        # Casou por publication_event_id!
        assert original_statuses[t6] == "unknown"       # Sem registro!

        # 2. Resolução em lote
        batch_statuses = copyright_gate.get_batch_publication_copyright_status(tasks, db_path=db_path)

        # Asserções de paridade estrita
        for tid in tasks:
            assert batch_statuses[tid] == original_statuses[tid], (
                f"Divergência de paridade para task '{tid}': "
                f"batch={batch_statuses[tid]} != original={original_statuses[tid]}"
            )

        # 3. Verificação no gate de copyright com batch_context
        adverse_statuses = {"claimed", "blocked", "strike"}
        adverse_batch = {tid for tid, st in batch_statuses.items() if st in adverse_statuses}
        batch_ctx = {"adverse_copyright": adverse_batch, "copyright_statuses": batch_statuses}

        # t1 deve falhar no gate
        p1, r1, _ = copyright_gate.evaluate_copyright_provenance_gate(t1, db_path=db_path, batch_context=batch_ctx)
        assert p1 is False

        # t2 NÃO deve falhar no gate prévio de status adverso
        assert t2 not in adverse_batch, "task_claimed_then_cleared não pode estar no conjunto de adversos do lote!"

        # t3 deve estar no conjunto de adversos
        assert t3 in adverse_batch

        # t4 deve estar no conjunto de adversos
        assert t4 in adverse_batch

        # t5 deve estar no conjunto de adversos
        assert t5 in adverse_batch

        # t6 NÃO deve estar no conjunto de adversos
        assert t6 not in adverse_batch
