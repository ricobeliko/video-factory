"""Testes unitários direcionados para V16.4.2C — Retry Metadata Cleanup.

Garante que posts em estados terminais ou com sucesso canônico não mantenham
next_attempt_at armado, que falhas respeitem a política centralizada de retry,
e que nenhum retry residual rearme publicações após restart ou concorrência.
"""

from datetime import datetime, timedelta, timezone
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from app.services import publishing_idempotency, retry_policy, scheduler


class TestPublishingRetryCleanup(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_retry_cleanup.db")
        scheduler.init_db(self.db_path)

        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)
        scheduler.set_setting("youtube_enabled", True, db_path=self.db_path)
        scheduler.set_setting("tiktok_enabled", True, db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _insert_post(
        self,
        task_id: str,
        platform: str,
        status: str = "ready",
        attempts: int = 0,
        scheduled_at: str = None,
        next_attempt_at: str = None,
        channel_id: str = "channel-1",
        last_error: str = None,
    ) -> int:
        now_dt = datetime.now(timezone.utc)
        now_iso = scheduler._to_iso(now_dt)
        sched_iso = scheduled_at or scheduler._to_iso(now_dt - timedelta(minutes=5))
        with scheduler.get_connection(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO scheduled_posts (
                    task_id, platform, status, scheduled_at, created_at,
                    channel_id, profile_id, attempts, next_attempt_at, last_error
                ) VALUES (?, ?, ?, ?, ?, ?, 'profile-1', ?, ?, ?);
                """,
                (task_id, platform, status, sched_iso, now_iso, channel_id, attempts, next_attempt_at, last_error),
            )
            return cur.lastrowid

    def _insert_event(
        self,
        task_id: str,
        platform: str,
        status: str = "success",
        external_id: str = "ext_123",
    ) -> int:
        now_iso = scheduler._to_iso(datetime.now(timezone.utc))
        with scheduler.get_connection(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO publication_events (
                    task_id, platform, published_at, status, external_id, channel_id
                ) VALUES (?, ?, ?, ?, ?, 'channel-1');
                """,
                (task_id, platform, now_iso, status, external_id),
            )
            return cur.lastrowid

    def test_published_plus_next_attempt_cleans_retry(self):
        """1. Post com status 'published' e next_attempt_at armado tem seu retry limpo."""
        task_id = "task-pub-retry"
        now_dt = datetime.now(timezone.utc)
        arm_time = scheduler._to_iso(now_dt + timedelta(minutes=30))

        post_id = self._insert_post(task_id, "youtube", status="published", next_attempt_at=arm_time)

        # Executa limpeza
        res = retry_policy.cleanup_residual_retries(db_path=self.db_path)
        self.assertGreaterEqual(res["published_residual_cleaned"], 1)

        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT status, next_attempt_at FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
            self.assertEqual(row["status"], "published")
            self.assertIsNone(row["next_attempt_at"])

    def test_cancelled_plus_next_attempt_cleans_retry(self):
        """2. Post com status 'cancelled' e next_attempt_at armado tem seu retry limpo."""
        task_id = "task-canc-retry"
        now_dt = datetime.now(timezone.utc)
        arm_time = scheduler._to_iso(now_dt + timedelta(minutes=15))

        post_id = self._insert_post(task_id, "youtube", status="cancelled", next_attempt_at=arm_time)

        res = retry_policy.cleanup_residual_retries(db_path=self.db_path)
        self.assertGreaterEqual(res["cancelled_residual_cleaned"], 1)

        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT status, next_attempt_at FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
            self.assertEqual(row["status"], "cancelled")
            self.assertIsNone(row["next_attempt_at"])

    def test_canonical_success_plus_failed_disarms_retry(self):
        """3. Sucesso canônico em publication_events desarma qualquer retry de post com falha."""
        task_id = "task-succ-failed"
        now_dt = datetime.now(timezone.utc)
        arm_time = scheduler._to_iso(now_dt + timedelta(minutes=10))

        self._insert_event(task_id, "youtube", status="success", external_id="yt-canon-ok")
        post_id = self._insert_post(task_id, "youtube", status="failed", attempts=2, next_attempt_at=arm_time)

        res = retry_policy.cleanup_residual_retries(db_path=self.db_path)
        self.assertGreaterEqual(res["canonical_success_residual_cleaned"], 1)

        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT status, next_attempt_at FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
            self.assertEqual(row["status"], "failed")
            self.assertIsNone(row["next_attempt_at"])

    def test_duplicate_neutralized_retry_never_returns(self):
        """4. Duplicata neutralizada permanece cancelada e nunca recupera retry."""
        task_id = "task-dup-neutral"
        now_dt = datetime.now(timezone.utc)
        past_time = scheduler._to_iso(now_dt - timedelta(minutes=10))

        p_canon = self._insert_post(task_id, "youtube", status="ready", scheduled_at=past_time, channel_id="channel-1")
        p_dup = self._insert_post(task_id, "youtube", status="ready", scheduled_at=past_time, channel_id="channel-2")

        with scheduler.get_connection(self.db_path) as conn:
            publishing_idempotency.neutralize_duplicate_executable_posts(task_id, "youtube", canonical_post_id=p_canon, conn=conn)

        # Roda ciclo e limpeza
        retry_policy.cleanup_residual_retries(db_path=self.db_path)

        with scheduler.get_connection(self.db_path) as conn:
            row_dup = conn.execute("SELECT status, next_attempt_at FROM scheduled_posts WHERE id = ?;", (p_dup,)).fetchone()
            self.assertEqual(row_dup["status"], "cancelled")
            self.assertIsNone(row_dup["next_attempt_at"])

    def test_failed_retryable_within_limit_schedules_retry(self):
        """5. Falha temporária com attempts < 3 pode agendar retry conforme política."""
        task_id = "task-retryable"
        error_msg = "503 Service Unavailable: backend timeout"

        decision = retry_policy.evaluate_retry_decision(
            task_id=task_id,
            platform="youtube",
            current_status="processing",
            attempts=1,
            error_msg=error_msg,
        )

        self.assertTrue(decision.can_retry)
        self.assertEqual(decision.resulting_status, "ready")
        self.assertIsNotNone(decision.next_attempt_at)
        self.assertEqual(decision.error_classification, "transient")
        self.assertGreater(decision.backoff_seconds, 0)

    def test_failed_non_retryable_does_not_schedule_retry(self):
        """6. Falha permanente não agenda retry e transiciona para 'failed' terminal."""
        task_id = "task-non-retryable"
        error_msg = "invalid_grant: Bad Request"

        decision = retry_policy.evaluate_retry_decision(
            task_id=task_id,
            platform="youtube",
            current_status="processing",
            attempts=1,
            error_msg=error_msg,
        )

        self.assertFalse(decision.can_retry)
        self.assertEqual(decision.resulting_status, "failed")
        self.assertIsNone(decision.next_attempt_at)
        self.assertEqual(decision.error_classification, "permanent")

    def test_retry_limit_reached_does_not_schedule_retry(self):
        """7. Limite de tentativas atingido (attempts=3) bloqueia novo retry e encerra como 'failed'."""
        task_id = "task-limit-reached"
        error_msg = "500 Internal Server Error"

        decision = retry_policy.evaluate_retry_decision(
            task_id=task_id,
            platform="youtube",
            current_status="processing",
            attempts=3,
            error_msg=error_msg,
        )

        self.assertFalse(decision.can_retry)
        self.assertEqual(decision.resulting_status, "failed")
        self.assertIsNone(decision.next_attempt_at)
        self.assertIn("max_attempts_exceeded", decision.reason)

    def test_restart_does_not_rearm_terminal_posts(self):
        """8. Restart de worker não rearma posts em estado terminal."""
        now_dt = datetime.now(timezone.utc)
        past_time = scheduler._to_iso(now_dt - timedelta(minutes=5))

        # Injeta terminal posts que teoricamente tinham next_attempt_at legado
        p1 = self._insert_post("t1", "youtube", status="published", next_attempt_at=past_time)
        p2 = self._insert_post("t2", "youtube", status="cancelled", next_attempt_at=past_time)
        p3 = self._insert_post("t3", "youtube", status="failed", attempts=3, next_attempt_at=past_time)

        with patch("app.services.task.publish_task") as mock_publish:
            # Simula reinício de ciclo
            res = scheduler.run_scheduler_cycle(db_path=self.db_path)
            mock_publish.assert_not_called()

        self.assertEqual(res.get("status"), "idle")

        with scheduler.get_connection(self.db_path) as conn:
            for pid in (p1, p2, p3):
                row = conn.execute("SELECT next_attempt_at FROM scheduled_posts WHERE id = ?;", (pid,)).fetchone()
                self.assertIsNone(row["next_attempt_at"])

    def test_v16_4_2b_guards_continue_blocking_provider_with_residual_retries(self):
        """9. Guards da V16.4.2B continuam bloqueando chamadas ao provider mesmo com retries residuais."""
        task_id = "task-guard-intact"
        now_dt = datetime.now(timezone.utc)
        past_time = scheduler._to_iso(now_dt - timedelta(minutes=10))

        # Evento canônico de sucesso
        self._insert_event(task_id, "youtube", status="success", external_id="yt-guard-ok")
        # Post que por alguma falha anterior ficou 'ready' com retry armado no passado
        post_id = self._insert_post(task_id, "youtube", status="ready", attempts=2, scheduled_at=past_time, next_attempt_at=past_time)

        with patch("app.services.task.publish_task") as mock_publish:
            res = scheduler.run_scheduler_cycle(db_path=self.db_path)
            mock_publish.assert_not_called()

        self.assertEqual(res.get("status"), "skipped")
        self.assertEqual(res.get("reason"), "already_published")

        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT status, next_attempt_at FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
            self.assertEqual(row["status"], "published")
            self.assertIsNone(row["next_attempt_at"])

    def test_multiple_platforms_remain_independent_under_retry_policy(self):
        """10. Múltiplas plataformas para a mesma task permanecem independentes."""
        task_id = "task-plat-indep"
        now_dt = datetime.now(timezone.utc)
        past_time = scheduler._to_iso(now_dt - timedelta(minutes=10))
        future_time = scheduler._to_iso(now_dt + timedelta(minutes=20))

        # YouTube com sucesso canônico
        self._insert_event(task_id, "youtube", status="success", external_id="yt-ok")
        pyt = self._insert_post(task_id, "youtube", status="published", next_attempt_at=past_time)

        # TikTok com retry válido em andamento (tentativa 1, transitória)
        ptt = self._insert_post(
            task_id, "tiktok", status="ready", attempts=1, scheduled_at=past_time, next_attempt_at=future_time, last_error="429 Rate Limit"
        )

        retry_policy.cleanup_residual_retries(db_path=self.db_path)

        with scheduler.get_connection(self.db_path) as conn:
            row_yt = conn.execute("SELECT status, next_attempt_at FROM scheduled_posts WHERE id = ?;", (pyt,)).fetchone()
            row_tt = conn.execute("SELECT status, next_attempt_at FROM scheduled_posts WHERE id = ?;", (ptt,)).fetchone()

        # YouTube teve retry residual limpo
        self.assertEqual(row_yt["status"], "published")
        self.assertIsNone(row_yt["next_attempt_at"])

        # TikTok manteve seu retry legítimo intacto
        self.assertEqual(row_tt["status"], "ready")
        self.assertEqual(row_tt["next_attempt_at"], future_time)

    def test_history_and_media_preserved(self):
        """11. Histórico de scheduled_posts e publication_events é 100% preservado (zero deleções)."""
        task_id = "task-audit-preserve"
        now_dt = datetime.now(timezone.utc)
        arm_time = scheduler._to_iso(now_dt + timedelta(minutes=10))

        self._insert_event(task_id, "youtube", status="success")
        self._insert_post(task_id, "youtube", status="published", next_attempt_at=arm_time)
        self._insert_post(task_id, "tiktok", status="cancelled", next_attempt_at=arm_time)

        retry_policy.cleanup_residual_retries(db_path=self.db_path)

        with scheduler.get_connection(self.db_path) as conn:
            ev_count = conn.execute("SELECT COUNT(*) AS cnt FROM publication_events WHERE task_id = ?;", (task_id,)).fetchone()["cnt"]
            post_count = conn.execute("SELECT COUNT(*) AS cnt FROM scheduled_posts WHERE task_id = ?;", (task_id,)).fetchone()["cnt"]

        self.assertEqual(ev_count, 1)
        self.assertEqual(post_count, 2)

    def test_cli_cleanup_dry_run_and_execute(self):
        """12. CLI scripts/cleanup_retry_metadata.py opera corretamente em --dry-run e --execute."""
        task_id = "task-cli-test"
        now_dt = datetime.now(timezone.utc)
        arm_time = scheduler._to_iso(now_dt + timedelta(minutes=15))

        post_id = self._insert_post(task_id, "youtube", status="published", next_attempt_at=arm_time)

        # 1. Dry run via CLI
        cmd_dry = [
            sys.executable,
            "scripts/cleanup_retry_metadata.py",
            "--dry-run",
            f"--db-path={self.db_path}",
        ]
        proc_dry = subprocess.run(cmd_dry, capture_output=True, text=True, check=True)
        self.assertIn("CLEANUP_DRY_RUN", proc_dry.stdout)

        # O post continua com next_attempt_at no dry-run
        with scheduler.get_connection(self.db_path) as conn:
            row_before = conn.execute("SELECT next_attempt_at FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
            self.assertIsNotNone(row_before["next_attempt_at"])

        # 2. Execute via CLI com confirmação
        cmd_exec = [
            sys.executable,
            "scripts/cleanup_retry_metadata.py",
            "--execute",
            "--confirm=CLEANUP_RETRY_METADATA",
            f"--db-path={self.db_path}",
        ]
        proc_exec = subprocess.run(cmd_exec, capture_output=True, text=True, check=True)
        self.assertIn("CLEANUP_EXECUTED", proc_exec.stdout)

        # O post teve seu next_attempt_at limpo
        with scheduler.get_connection(self.db_path) as conn:
            row_after = conn.execute("SELECT next_attempt_at FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
            self.assertIsNone(row_after["next_attempt_at"])


if __name__ == "__main__":
    unittest.main()
