"""Test suite para Recuperação Segura de Lock PRIMARY_FACTORY Stale (Fase V16.4.2R.2).

Valida estritamente em banco isolado temporário:
1. ACTIVE + heartbeat recente -> BLOCK
2. ACTIVE + heartbeat stale + processo vivo -> BLOCK
3. ACTIVE + heartbeat stale + processo ausente -> RELEASE permitido
4. scheduler ON -> BLOCK
5. auto_publish ON -> BLOCK
6. STOPPED -> idempotent/no-op
7. dry-run -> zero mutation
8. release real -> ACTIVE -> STOPPED
9. audit event criado em operational_events (STALE_PRIMARY_LOCK_RELEASED)
10. nenhuma linha deletada em instance_locks (preserva node_id, hostname, pid, started_at, role)
"""

import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.services import operator_console, publication_reset, scheduler


class TestStalePrimaryLockRecovery(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_stale_lock_")
        self.db_path = os.path.join(self.temp_dir, "test_video_factory.db")
        scheduler.init_db(self.db_path)
        operator_console.init_operator_db(self.db_path)

        # Baseline seguro: scheduler e auto_publish desligados
        scheduler.save_settings(
            {
                "scheduler_enabled": False,
                "auto_publish_enabled": False,
                "dry_run": True,
            },
            db_path=self.db_path,
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _insert_lock(
        self,
        status: str = operator_console.INSTANCE_STATUS_ACTIVE,
        heartbeat_age_seconds: int = 300,
        pid: int = 999999,
        hostname: str = "test-host",
    ):
        now_utc = datetime.now(timezone.utc)
        hb_time = (now_utc - timedelta(seconds=heartbeat_age_seconds)).isoformat()
        started_time = (now_utc - timedelta(hours=2)).isoformat()

        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO instance_locks (
                    lock_key, node_id, node_name, hostname, pid, started_at, last_heartbeat, role, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    operator_console.DEFAULT_INSTANCE_LOCK_KEY,
                    "node-stale-1",
                    operator_console.DEFAULT_FACTORY_NODE_NAME,
                    hostname,
                    pid,
                    started_time,
                    hb_time,
                    operator_console.ROLE_PRIMARY,
                    status,
                ),
            )

    def test_case_1_active_recent_heartbeat_blocks(self):
        """Caso 1: ACTIVE + heartbeat recente -> BLOCK."""
        # Heartbeat de 10 segundos atrás (threshold é 90s)
        self._insert_lock(
            status=operator_console.INSTANCE_STATUS_ACTIVE,
            heartbeat_age_seconds=10,
        )

        res = operator_console.release_stale_instance_lock(
            dry_run=True,
            db_path=self.db_path,
            stale_timeout_seconds=90,
        )
        self.assertFalse(res["can_release"])
        self.assertFalse(res["would_release"])
        self.assertIn("Heartbeat recente", res["reason"])

        # Em execução real, deve levantar exceção de segurança
        with self.assertRaises(RuntimeError) as cm:
            operator_console.release_stale_instance_lock(
                dry_run=False,
                confirm_token="RELEASE_STALE_PRIMARY",
                db_path=self.db_path,
                stale_timeout_seconds=90,
            )
        self.assertIn("Não é seguro liberar o lock", str(cm.exception))

    @patch("app.services.operator_console._is_local_pid_alive", return_value=True)
    def test_case_2_active_stale_heartbeat_process_alive_blocks(self, mock_pid_alive):
        """Caso 2: ACTIVE + heartbeat stale + processo vivo -> BLOCK."""
        import platform
        local_host = platform.node() or "localhost"

        # Heartbeat de 300 segundos atrás (stale), mas processo ainda vivo no mesmo host
        self._insert_lock(
            status=operator_console.INSTANCE_STATUS_ACTIVE,
            heartbeat_age_seconds=300,
            pid=os.getpid(),  # processo local atual
            hostname=local_host,
        )

        res = operator_console.release_stale_instance_lock(
            dry_run=True,
            db_path=self.db_path,
            stale_timeout_seconds=90,
        )
        self.assertFalse(res["can_release"])
        self.assertFalse(res["would_release"])
        self.assertTrue(res["process_alive"])
        self.assertIn("ainda está vivo em execução", res["reason"])

    @patch("app.services.operator_console._is_local_pid_alive", return_value=False)
    def test_case_3_active_stale_heartbeat_process_dead_allows_release(self, mock_pid_alive):
        """Caso 3: ACTIVE + heartbeat stale + processo ausente -> RELEASE permitido."""
        import platform
        local_host = platform.node() or "localhost"

        self._insert_lock(
            status=operator_console.INSTANCE_STATUS_ACTIVE,
            heartbeat_age_seconds=300,
            pid=987654,
            hostname=local_host,
        )

        res = operator_console.release_stale_instance_lock(
            dry_run=True,
            db_path=self.db_path,
            stale_timeout_seconds=90,
        )
        self.assertTrue(res["can_release"])
        self.assertTrue(res["would_release"])
        self.assertFalse(res["process_alive"])
        self.assertIn("Lock está stale", res["reason"])

    def test_case_4_scheduler_enabled_blocks(self):
        """Caso 4: scheduler ON -> BLOCK."""
        scheduler.save_settings({"scheduler_enabled": True}, db_path=self.db_path)
        self._insert_lock(
            status=operator_console.INSTANCE_STATUS_ACTIVE,
            heartbeat_age_seconds=300,
        )

        res = operator_console.release_stale_instance_lock(
            dry_run=True,
            db_path=self.db_path,
        )
        self.assertFalse(res["can_release"])
        self.assertIn("scheduler_enabled está ativo", res["reason"])

    def test_case_5_auto_publish_enabled_blocks(self):
        """Caso 5: auto_publish ON -> BLOCK."""
        scheduler.save_settings({"auto_publish_enabled": True}, db_path=self.db_path)
        self._insert_lock(
            status=operator_console.INSTANCE_STATUS_ACTIVE,
            heartbeat_age_seconds=300,
        )

        res = operator_console.release_stale_instance_lock(
            dry_run=True,
            db_path=self.db_path,
        )
        self.assertFalse(res["can_release"])
        self.assertIn("auto_publish_enabled está ativo", res["reason"])

    def test_case_6_stopped_is_idempotent_no_op(self):
        """Caso 6: STOPPED -> idempotent/no-op."""
        self._insert_lock(
            status=operator_console.INSTANCE_STATUS_STOPPED,
            heartbeat_age_seconds=500,
        )

        res = operator_console.release_stale_instance_lock(
            dry_run=True,
            db_path=self.db_path,
        )
        self.assertFalse(res["can_release"])
        self.assertFalse(res["would_release"])
        self.assertIn("já está com status='STOPPED'", res["reason"])

        # Em execução real também é no-op seguro
        res_exec = operator_console.release_stale_instance_lock(
            dry_run=False,
            confirm_token="RELEASE_STALE_PRIMARY",
            db_path=self.db_path,
        )
        self.assertFalse(res_exec["released"])

    @patch("app.services.operator_console._is_local_pid_alive", return_value=False)
    def test_case_7_dry_run_zero_mutation(self, mock_pid_alive):
        """Caso 7: dry-run -> zero mutation."""
        self._insert_lock(
            status=operator_console.INSTANCE_STATUS_ACTIVE,
            heartbeat_age_seconds=300,
        )

        res = operator_console.release_stale_instance_lock(
            dry_run=True,
            db_path=self.db_path,
        )
        self.assertTrue(res["would_release"])
        self.assertFalse(res["released"])

        # Verifica que o banco permaneceu ACTIVE
        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT status FROM instance_locks WHERE lock_key = ?;",
                (operator_console.DEFAULT_INSTANCE_LOCK_KEY,),
            ).fetchone()
            self.assertEqual(row["status"], operator_console.INSTANCE_STATUS_ACTIVE)

            # Nenhum evento operacional criado no dry-run
            ev_cnt = conn.execute("SELECT COUNT(*) FROM operational_events;").fetchone()[0]
            self.assertEqual(ev_cnt, 0)

    @patch("app.services.operator_console._is_local_pid_alive", return_value=False)
    def test_cases_8_9_10_real_release_updates_audits_and_preserves_row(self, mock_pid_alive):
        """Casos 8, 9 e 10: release real -> ACTIVE -> STOPPED, audit event criado, nenhuma linha deletada."""
        self._insert_lock(
            status=operator_console.INSTANCE_STATUS_ACTIVE,
            heartbeat_age_seconds=300,
            pid=55555,
            hostname="prod-node-1",
        )

        # 1. Requer confirm_token obrigatório
        with self.assertRaises(ValueError):
            operator_console.release_stale_instance_lock(
                dry_run=False,
                confirm_token="INVALID_TOKEN",
                db_path=self.db_path,
            )

        # 2. Execução com confirmação
        res = operator_console.release_stale_instance_lock(
            dry_run=False,
            confirm_token="RELEASE_STALE_PRIMARY",
            db_path=self.db_path,
        )
        self.assertTrue(res["released"])
        self.assertEqual(res["previous_status"], operator_console.INSTANCE_STATUS_ACTIVE)
        self.assertEqual(res["resulting_status"], operator_console.INSTANCE_STATUS_STOPPED)

        # 3. Verificação no banco: Caso 8 (ACTIVE -> STOPPED) e Caso 10 (nenhuma linha deletada, metadados preservados)
        with scheduler.get_connection(self.db_path) as conn:
            rows = conn.execute("SELECT * FROM instance_locks;").fetchall()
            self.assertEqual(len(rows), 1, "Nenhuma linha deve ser deletada")

            r = dict(rows[0])
            self.assertEqual(r["lock_key"], operator_console.DEFAULT_INSTANCE_LOCK_KEY)
            self.assertEqual(r["status"], operator_console.INSTANCE_STATUS_STOPPED)
            self.assertEqual(r["node_id"], "node-stale-1")
            self.assertEqual(r["node_name"], operator_console.DEFAULT_FACTORY_NODE_NAME)
            self.assertEqual(r["hostname"], "prod-node-1")
            self.assertEqual(r["pid"], 55555)
            self.assertEqual(r["role"], operator_console.ROLE_PRIMARY)

            # 4. Verificação Caso 9: audit event criado em operational_events
            ev = conn.execute(
                "SELECT * FROM operational_events WHERE event_type = ?;",
                (operator_console.EVENT_STALE_PRIMARY_LOCK_RELEASED,),
            ).fetchone()
            self.assertIsNotNone(ev)
            self.assertEqual(ev["component"], "InstanceLock")
            self.assertEqual(ev["severity"], operator_console.SEVERITY_WARNING)
            self.assertIn("liberado administrativamente", ev["message"])

        # 5. Comprovar que agora publication_reset.check_reset_preconditions passa!
        pre = publication_reset.check_reset_preconditions(self.db_path)
        self.assertTrue(pre["passed"])
        self.assertFalse(pre["active_primary"])


if __name__ == "__main__":
    unittest.main()
