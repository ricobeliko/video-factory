import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.services import scheduler


class TestSchedulerTestReschedule(unittest.TestCase):
    """Testes direcionados para a funcionalidade de homologação: reagendamento rápido de teste."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_reschedule.db")
        scheduler.init_db(self.db_path)
        self.now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _insert_post(self, task_id: str, platform: str, scheduled_at: datetime, status: str = "planned", next_attempt: str = None) -> int:
        with scheduler.get_connection(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at, next_attempt_at)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (task_id, platform, scheduler._to_iso(scheduled_at), status, scheduler._to_iso(self.now), next_attempt),
            )
            return cur.lastrowid

    def test_01_reschedule_post_planned(self):
        """1. Reagenda post com status 'planned' para +5 minutos."""
        orig_time = self.now + timedelta(hours=4)
        post_id = self._insert_post("task_1", "tiktok", orig_time, status="planned")

        res = scheduler.reschedule_post_for_test(post_id, minutes_from_now=5, db_path=self.db_path, now=self.now)
        self.assertTrue(res["success"])
        expected_time = scheduler._to_iso(self.now + timedelta(minutes=5))
        self.assertEqual(res["new_scheduled_at"], expected_time)

        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT scheduled_at, status, next_attempt_at FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
            self.assertEqual(row["scheduled_at"], expected_time)
            self.assertEqual(row["status"], "ready")
            self.assertIsNone(row["next_attempt_at"])

    def test_02_reschedule_post_ready(self):
        """2. Reagenda post com status 'ready' e limpa next_attempt_at anterior."""
        orig_time = self.now + timedelta(hours=2)
        old_retry = scheduler._to_iso(self.now + timedelta(hours=3))
        post_id = self._insert_post("task_2", "youtube", orig_time, status="ready", next_attempt=old_retry)

        res = scheduler.reschedule_post_for_test(post_id, minutes_from_now=2, db_path=self.db_path, now=self.now)
        self.assertTrue(res["success"])
        expected_time = scheduler._to_iso(self.now + timedelta(minutes=2))
        self.assertEqual(res["new_scheduled_at"], expected_time)

        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT scheduled_at, status, next_attempt_at FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
            self.assertEqual(row["scheduled_at"], expected_time)
            self.assertEqual(row["status"], "ready")
            self.assertIsNone(row["next_attempt_at"])

    def test_03_published_cannot_be_rescheduled(self):
        """3. Post já 'published' não pode ser reagendado."""
        orig_time = self.now - timedelta(hours=1)
        post_id = self._insert_post("task_3", "tiktok", orig_time, status="published")

        res = scheduler.reschedule_post_for_test(post_id, minutes_from_now=5, db_path=self.db_path, now=self.now)
        self.assertFalse(res["success"])
        self.assertEqual(res["error"], "invalid_status")

        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT scheduled_at, status FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
            self.assertEqual(row["scheduled_at"], scheduler._to_iso(orig_time))
            self.assertEqual(row["status"], "published")

    def test_04_processing_cannot_be_rescheduled(self):
        """4. Post com status 'processing' não pode ser reagendado."""
        orig_time = self.now
        post_id = self._insert_post("task_4", "youtube", orig_time, status="processing")

        res = scheduler.reschedule_post_for_test(post_id, minutes_from_now=10, db_path=self.db_path, now=self.now)
        self.assertFalse(res["success"])
        self.assertEqual(res["error"], "invalid_status")

    def test_05_cancelled_cannot_be_rescheduled(self):
        """5. Post com status 'cancelled' não pode ser reagendado."""
        orig_time = self.now + timedelta(hours=1)
        post_id = self._insert_post("task_5", "tiktok", orig_time, status="cancelled")

        res = scheduler.reschedule_post_for_test(post_id, minutes_from_now=2, db_path=self.db_path, now=self.now)
        self.assertFalse(res["success"])
        self.assertEqual(res["error"], "invalid_status")

    def test_06_invalid_interval_rejected(self):
        """6. Intervalos diferentes de 2, 5 e 10 minutos são estritamente rejeitados."""
        post_id = self._insert_post("task_6", "tiktok", self.now + timedelta(hours=1), status="planned")

        for invalid_min in (0, 1, 3, 4, 7, 15, 60, -5):
            res = scheduler.reschedule_post_for_test(post_id, minutes_from_now=invalid_min, db_path=self.db_path, now=self.now)
            self.assertFalse(res["success"])
            self.assertEqual(res["error"], "invalid_interval")

        # 2, 5 e 10 são aceitos
        for valid_min in (2, 5, 10):
            res = scheduler.reschedule_post_for_test(post_id, minutes_from_now=valid_min, db_path=self.db_path, now=self.now)
            self.assertTrue(res["success"])

    def test_07_only_selected_post_changes(self):
        """7. Apenas o post selecionado tem o horário alterado; os demais permanecem idênticos."""
        t1 = self.now + timedelta(hours=2)
        t2 = self.now + timedelta(hours=5)
        t3 = self.now + timedelta(hours=8)

        id1 = self._insert_post("task_a", "tiktok", t1, status="planned")
        id2 = self._insert_post("task_b", "youtube", t2, status="planned")
        id3 = self._insert_post("task_c", "tiktok", t3, status="ready")

        res = scheduler.reschedule_post_for_test(id2, minutes_from_now=10, db_path=self.db_path, now=self.now)
        self.assertTrue(res["success"])

        with scheduler.get_connection(self.db_path) as conn:
            row1 = conn.execute("SELECT scheduled_at, status FROM scheduled_posts WHERE id = ?;", (id1,)).fetchone()
            row2 = conn.execute("SELECT scheduled_at, status FROM scheduled_posts WHERE id = ?;", (id2,)).fetchone()
            row3 = conn.execute("SELECT scheduled_at, status FROM scheduled_posts WHERE id = ?;", (id3,)).fetchone()

            # id1 intocado
            self.assertEqual(row1["scheduled_at"], scheduler._to_iso(t1))
            self.assertEqual(row1["status"], "planned")

            # id2 alterado
            self.assertEqual(row2["scheduled_at"], scheduler._to_iso(self.now + timedelta(minutes=10)))
            self.assertEqual(row2["status"], "ready")

            # id3 intocado
            self.assertEqual(row3["scheduled_at"], scheduler._to_iso(t3))
            self.assertEqual(row3["status"], "ready")

    def test_08_does_not_create_new_scheduled_post(self):
        """8. Não cria nenhum novo registro em scheduled_posts."""
        id1 = self._insert_post("task_x", "tiktok", self.now + timedelta(hours=3), status="planned")

        with scheduler.get_connection(self.db_path) as conn:
            count_before = conn.execute("SELECT COUNT(*) AS cnt FROM scheduled_posts;").fetchone()["cnt"]

        scheduler.reschedule_post_for_test(id1, minutes_from_now=5, db_path=self.db_path, now=self.now)

        with scheduler.get_connection(self.db_path) as conn:
            count_after = conn.execute("SELECT COUNT(*) AS cnt FROM scheduled_posts;").fetchone()["cnt"]

        self.assertEqual(count_before, count_after)

    @patch("app.services.task.publish_task")
    def test_09_does_not_call_upload_post(self, mock_publish):
        """9. Reagendamento não dispara publicação nem chama Upload-Post."""
        id1 = self._insert_post("task_y", "youtube", self.now + timedelta(hours=6), status="planned")

        res = scheduler.reschedule_post_for_test(id1, minutes_from_now=2, db_path=self.db_path, now=self.now)
        self.assertTrue(res["success"])
        mock_publish.assert_not_called()

    def test_10_does_not_create_publication_event(self):
        """10. Reagendamento de homologação não cria nenhum registro em publication_events."""
        id1 = self._insert_post("task_z", "tiktok", self.now + timedelta(hours=1), status="planned")

        scheduler.reschedule_post_for_test(id1, minutes_from_now=5, db_path=self.db_path, now=self.now)

        with scheduler.get_connection(self.db_path) as conn:
            cnt = conn.execute("SELECT COUNT(*) AS cnt FROM publication_events;").fetchone()["cnt"]
            self.assertEqual(cnt, 0)


if __name__ == "__main__":
    unittest.main()
