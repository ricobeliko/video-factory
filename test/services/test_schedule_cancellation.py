"""
Testes unitários e de integração para cancelamento terminal de scheduled_posts com PRIMARY Guard (Hotfix V12-D.1).
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.services import operator_console, scheduler
from app.utils import utils


class TestScheduleCancellation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_sched_cancel_")
        self.db_path = os.path.join(self.temp_dir, "test_factory.db")
        scheduler.init_db(self.db_path)
        operator_console.init_operator_db(self.db_path)
        operator_console.reset_instance_for_testing()

    def tearDown(self):
        operator_console.reset_instance_for_testing()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _insert_post(
        self,
        task_id: str,
        platform: str = "youtube",
        status: str = "planned",
        scheduled_at: str = "2026-09-20T12:00:00+00:00",
        channel_id: str = None,
        profile_id: str = "default",
        attempts: int = 0,
        next_attempt_at: str = "2026-09-20T12:00:00+00:00",
    ) -> int:
        now_iso = datetime.now(timezone.utc).isoformat()
        with scheduler.get_connection(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO scheduled_posts (
                    task_id, platform, scheduled_at, status, created_at,
                    profile_id, channel_id, attempts, next_attempt_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (task_id, platform, scheduled_at, status, now_iso, profile_id, channel_id, attempts, next_attempt_at),
            )
            return cur.lastrowid

    def test_01_planned_to_cancelled_as_primary(self):
        """1. PRIMARY pode cancelar planned com preservação de scheduled_at e attempts."""
        post_id = self._insert_post("task-1", "youtube", status="planned", attempts=2, scheduled_at="2026-09-21T10:00:00+00:00")
        res = scheduler.cancel_scheduled_post(post_id, reason="Old test", db_path=self.db_path)

        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "cancelled")
        self.assertEqual(res["previous_status"], "planned")

        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT * FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
            self.assertEqual(row["status"], "cancelled")
            self.assertEqual(row["attempts"], 2)
            self.assertEqual(row["scheduled_at"], "2026-09-21T10:00:00+00:00")
            self.assertIsNone(row["next_attempt_at"])
            self.assertIn("Old test", row["last_error"])

    def test_02_ready_to_cancelled_as_primary(self):
        """2. PRIMARY pode cancelar ready."""
        post_id = self._insert_post("task-2", "tiktok", status="ready")
        res = scheduler.cancel_scheduled_post(post_id, reason="Cancel ready", db_path=self.db_path)

        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "cancelled")
        self.assertEqual(res["previous_status"], "ready")

        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT status, next_attempt_at FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
            self.assertEqual(row["status"], "cancelled")
            self.assertIsNone(row["next_attempt_at"])

    def test_03_published_cannot_be_cancelled(self):
        """3. published nunca pode ser alterado mesmo por PRIMARY."""
        post_id = self._insert_post("task-3", "youtube", status="published")
        res = scheduler.cancel_scheduled_post(post_id, reason="Try cancel pub", db_path=self.db_path)

        self.assertFalse(res["success"])
        self.assertEqual(res["error"], "cannot_cancel_published")
        self.assertEqual(res["status"], "published")

        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT status FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
            self.assertEqual(row["status"], "published")

    def test_04_processing_cannot_be_cancelled(self):
        """4. processing não pode ser cancelado (concorrência ativa)."""
        post_id = self._insert_post("task-4", "tiktok", status="processing")
        res = scheduler.cancel_scheduled_post(post_id, reason="Try cancel proc", db_path=self.db_path)

        self.assertFalse(res["success"])
        self.assertEqual(res["error"], "cannot_cancel_processing")
        self.assertEqual(res["status"], "processing")

        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT status FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
            self.assertEqual(row["status"], "processing")

    def test_05_cancellation_is_idempotent(self):
        """5. cancelar duas vezes é idempotente."""
        post_id = self._insert_post("task-5", "youtube", status="planned")
        res1 = scheduler.cancel_scheduled_post(post_id, reason="First", db_path=self.db_path)
        self.assertTrue(res1["success"])
        self.assertFalse(res1.get("already_cancelled", False))

        res2 = scheduler.cancel_scheduled_post(post_id, reason="Second", db_path=self.db_path)
        self.assertTrue(res2["success"])
        self.assertTrue(res2.get("already_cancelled"))

    def test_06_cancellation_creates_no_publication_events(self):
        """6. cancellation não cria publication_event."""
        post_id = self._insert_post("task-6", "youtube", status="ready")
        scheduler.cancel_scheduled_post(post_id, db_path=self.db_path)

        with scheduler.get_connection(self.db_path) as conn:
            cnt = conn.execute("SELECT COUNT(*) AS c FROM publication_events;").fetchone()["c"]
            self.assertEqual(cnt, 0)

    def test_07_cancellation_does_not_remove_task_or_video(self):
        """7. cancellation não remove task/video."""
        task_id = "task-7-retain"
        task_dir = os.path.join(self.temp_dir, "storage", "tasks", task_id)
        os.makedirs(task_dir, exist_ok=True)
        video_path = os.path.join(task_dir, "final-1.mp4")
        with open(video_path, "wb") as f:
            f.write(b"fake video content")

        post_id = self._insert_post(task_id, "youtube", status="planned")
        scheduler.cancel_scheduled_post(post_id, db_path=self.db_path)

        self.assertTrue(os.path.isfile(video_path))
        self.assertTrue(os.path.isdir(task_dir))

    def test_08_plan_schedule_does_not_recreate_cancelled_schedule(self):
        """8. plan_schedule não recria task/platform/channel cancelado."""
        task_id = "task-8-cancelled"
        post_id = self._insert_post(task_id, "youtube", status="planned", channel_id="ch-1")
        scheduler.cancel_scheduled_post(post_id, db_path=self.db_path)

        # Configura ambiente para permitir planejamento
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("youtube_enabled", True, db_path=self.db_path)
        operator_console.set_factory_state(operator_console.FACTORY_STATE_RUNNING, db_path=self.db_path)

        tasks = [
            {
                "task_id": task_id,
                "state": "complete",
                "video_file": "final-1.mp4",
                "planned_platforms": ["youtube"],
            }
        ]

        with patch("app.services.profile_manager.list_channels", return_value=[{"channel_id": "ch-1", "platform": "youtube", "is_enabled": True}]):
            new_posts = scheduler.plan_schedule(tasks, db_path=self.db_path)

        # Deve ser ignorado pelo planner porque já existe registro cancelado!
        self.assertEqual(len(new_posts), 0)

        # Confirma que só existe o registro cancelado no banco
        with scheduler.get_connection(self.db_path) as conn:
            rows = conn.execute("SELECT id, status FROM scheduled_posts WHERE task_id = ?;", (task_id,)).fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "cancelled")

    def test_09_existing_published_post_preserved(self):
        """9. publicação já existente continua preservada."""
        pub_id = self._insert_post("task-9", "youtube", status="published")
        plan_id = self._insert_post("task-9b", "tiktok", status="planned")

        res = scheduler.cancel_scheduled_post(plan_id, db_path=self.db_path)
        self.assertTrue(res["success"])

        with scheduler.get_connection(self.db_path) as conn:
            pub_row = conn.execute("SELECT status FROM scheduled_posts WHERE id = ?;", (pub_id,)).fetchone()
            self.assertEqual(pub_row["status"], "published")

    def test_10_bulk_cancellation_updates_only_eligible_ids(self):
        """10. bulk cancellation atualiza somente IDs elegíveis."""
        id_planned = self._insert_post("task-10-a", "youtube", status="planned")
        id_ready = self._insert_post("task-10-b", "tiktok", status="ready")
        id_pub = self._insert_post("task-10-c", "youtube", status="published")
        id_proc = self._insert_post("task-10-d", "tiktok", status="processing")

        summary = scheduler.cancel_scheduled_posts(
            [id_planned, id_ready, id_pub, id_proc],
            reason="Bulk test",
            db_path=self.db_path,
        )

        self.assertEqual(summary["total"], 4)
        self.assertEqual(summary["cancelled"], 2)  # planned e ready
        self.assertEqual(summary["failed"], 2)     # published e processing rejeitados

        with scheduler.get_connection(self.db_path) as conn:
            s_map = {
                r["id"]: r["status"]
                for r in conn.execute("SELECT id, status FROM scheduled_posts;").fetchall()
            }
            self.assertEqual(s_map[id_planned], "cancelled")
            self.assertEqual(s_map[id_ready], "cancelled")
            self.assertEqual(s_map[id_pub], "published")
            self.assertEqual(s_map[id_proc], "processing")

    def test_11_nonexistent_ids_do_not_break_bulk_cancellation(self):
        """11. IDs inexistentes não quebram operação."""
        id_planned = self._insert_post("task-11", "youtube", status="planned")

        summary = scheduler.cancel_scheduled_posts(
            [99999, id_planned, 88888],
            reason="Nonexistent test",
            db_path=self.db_path,
        )

        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["cancelled"], 1)
        self.assertEqual(summary["failed"], 2)

        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT status FROM scheduled_posts WHERE id = ?;", (id_planned,)).fetchone()
            self.assertEqual(row["status"], "cancelled")

    def test_12_factory_paused_state_preserved(self):
        """12. factory PAUSED continua preservada após cancelamento."""
        operator_console.set_factory_state(operator_console.FACTORY_STATE_PAUSED, db_path=self.db_path)
        post_id = self._insert_post("task-12", "youtube", status="ready")

        scheduler.cancel_scheduled_post(post_id, db_path=self.db_path)

        state = operator_console.get_factory_state(db_path=self.db_path)
        self.assertEqual(state, operator_console.FACTORY_STATE_PAUSED)

    def test_13_secondary_view_only_blocks_cancellation(self):
        """13. SECONDARY_VIEW_ONLY não pode cancelar e levanta PermissionError."""
        post_id = self._insert_post("task-13", "youtube", status="planned")

        with patch("app.services.operator_console.is_primary_instance", return_value=False):
            with self.assertRaises(PermissionError):
                scheduler.cancel_scheduled_post(post_id, db_path=self.db_path)

        # Garante que o registro no banco não foi modificado
        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT status FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
            self.assertEqual(row["status"], "planned")

    def test_14_bulk_cancellation_blocks_on_secondary_before_processing(self):
        """14. bulk cancellation em SECONDARY bloqueia ANTES de processar IDs (sem cancelamento parcial)."""
        id_planned_1 = self._insert_post("task-14-1", "youtube", status="planned")
        id_planned_2 = self._insert_post("task-14-2", "tiktok", status="planned")

        with patch("app.services.operator_console.is_primary_instance", return_value=False):
            with self.assertRaises(PermissionError):
                scheduler.cancel_scheduled_posts([id_planned_1, id_planned_2], db_path=self.db_path)

        # Garante que nenhum dos dois IDs sofreu mutação
        with scheduler.get_connection(self.db_path) as conn:
            s_map = {
                r["id"]: r["status"]
                for r in conn.execute("SELECT id, status FROM scheduled_posts;").fetchall()
            }
            self.assertEqual(s_map[id_planned_1], "planned")
            self.assertEqual(s_map[id_planned_2], "planned")

    def test_15_cli_blocks_and_returns_error_when_secondary(self):
        """15. CLI retorna erro (código 2) e mensagem sanitizada quando é SECONDARY."""
        post_id = self._insert_post("task-15", "youtube", status="planned")

        test_args = [
            "scheduler.py",
            "--cancel", str(post_id),
            "--reason", "CLI secondary test",
            "--db-path", self.db_path,
        ]

        stderr_buf = io.StringIO()
        with patch.object(sys, "argv", test_args):
            with patch("sys.stderr", stderr_buf):
                with patch("app.services.operator_console.is_primary_instance", return_value=False):
                    with self.assertRaises(SystemExit) as ctx:
                        scheduler.main()

                    self.assertEqual(ctx.exception.code, 2)
                    self.assertIn("Operação bloqueada", stderr_buf.getvalue())

        # Confirma que o post não foi modificado
        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT status FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
            self.assertEqual(row["status"], "planned")

    def test_16_cli_succeeds_when_lock_stopped(self):
        """16. CLI adquire PRIMARY legitimamente quando o lock está STOPPED e depois libera."""
        post_id = self._insert_post("task-16", "youtube", status="planned")

        # Configura o lock no banco como STOPPED
        now_iso = datetime.now(timezone.utc).isoformat()
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO instance_locks (
                    lock_key, node_id, node_name, hostname, pid, started_at, last_heartbeat, role, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    operator_console.DEFAULT_INSTANCE_LOCK_KEY,
                    "old-node-id",
                    "old-node-name",
                    "old-host",
                    1234,
                    now_iso,
                    now_iso,
                    operator_console.ROLE_PRIMARY,
                    operator_console.INSTANCE_STATUS_STOPPED,
                ),
            )

        test_args = [
            "scheduler.py",
            "--cancel", str(post_id),
            "--reason", "CLI legitimate stopped lock test",
            "--db-path", self.db_path,
        ]

        with patch.object(sys, "argv", test_args):
            with self.assertRaises(SystemExit) as ctx:
                scheduler.main()

            self.assertEqual(ctx.exception.code, 0)

        # Confirma que o post foi cancelado
        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT status, last_error FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
            self.assertEqual(row["status"], "cancelled")
            self.assertIn("CLI legitimate stopped lock test", row["last_error"])


if __name__ == "__main__":
    unittest.main()
