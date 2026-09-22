"""V12-E.3: real temporary persistence, fake generation, no publication/network."""
import os
import unittest
from datetime import timedelta
from unittest.mock import patch

from app.models import const
from app.services import autonomous_production as autonomous
from app.services import operator_console, profile_manager, scheduler
from app.services import state as sm
from test.services import test_autonomous_production as fixtures


class TestStockBuffer(unittest.TestCase):
    setUp = fixtures.TestAutonomousProductionLoop.setUp
    tearDown = fixtures.TestAutonomousProductionLoop.tearDown
    _create_mock_video_file = fixtures.TestAutonomousProductionLoop._create_mock_video_file
    _persist_waiting_fixture = fixtures.TestAutonomousProductionLoop._persist_waiting_fixture

    def stock(self):
        with patch.object(sm.state, "get_task", return_value=None):
            return autonomous.get_autonomous_ready_stock(self.task_base_dir, self.db_path)

    def cycle(self, now=None, slots=0):
        with patch.object(sm.state, "get_task", return_value=None), \
             patch("app.utils.utils.task_dir", return_value=self.task_base_dir), \
             patch.object(scheduler, "get_platform_rate_limits", return_value={
                 "enabled": True, "available_slots": slots, "growth_mode": "WARMUP"}), \
             patch.object(scheduler, "plan_schedule", wraps=scheduler.plan_schedule) as plan, \
             patch("app.services.webui_task.has_active_generation_tasks", return_value=False), \
             patch("app.services.webui_task.submit_generation") as submit, \
             patch.object(autonomous, "check_required_providers_preflight", return_value=(True, "ok", {})), \
             patch.object(autonomous, "discover_candidate_topic", return_value={"topic": "New topic", "origin": "test"}):
            result = autonomous.run_autonomous_cycle(force=True, now=now or self.now, db_path=self.db_path)
        self.assertLessEqual(submit.call_count, 1)
        self.assertFalse(submit.called and plan.called, "schedule and generation in same cycle")
        self.mock_upload_video.assert_not_called()
        self.mock_cross_post.assert_not_called()
        self.mock_publish_task.assert_not_called()
        return result, submit.call_count, plan.call_count

    def test_waiting_one_then_two_then_three_stops(self):
        for size in (1, 2, 3):
            self._persist_waiting_fixture(f"buffer-{size}")
            autonomous.set_autonomous_setting(autonomous.KEY_AUTONOMOUS_CURRENT_TASK_ID, "", self.db_path)
            result, generated, planned = self.cycle()
            self.assertEqual(generated, int(size < 3))
            self.assertEqual(planned, 0)
            self.assertEqual(result["status"], "generation_started" if size < 3 else "idle")
            self.assertEqual(self.stock()["ready_count"], size)

    def test_restart_without_memory_or_waiting_pointer_reconstructs_all(self):
        for n in range(3):
            self._persist_waiting_fixture(f"restart-{n}")
        autonomous.set_autonomous_setting(autonomous.KEY_AUTONOMOUS_WAITING_TASK_ID, "", self.db_path)
        self.assertEqual(self.stock()["ready_count"], 3)
        self.assertEqual(self.cycle()[1:], (0, 0))

    def test_empty_stock_starts_exactly_one_generation(self):
        autonomous.set_autonomous_mode_enabled(True, db_path=self.db_path)
        autonomous.set_autonomous_setting(autonomous.KEY_AUTONOMOUS_MAX_TASKS_PER_CYCLE, "20", self.db_path)
        self.assertEqual(self.cycle()[1:], (1, 0))

    def test_active_generation_precedes_waiting_task(self):
        self._persist_waiting_fixture("waiting-active")
        with patch("app.services.webui_task.has_active_generation_tasks", return_value=True), \
             patch("app.services.webui_task.get_active_task_ids", return_value=["rendering"]), \
             patch("app.services.webui_task.submit_generation") as submit, \
             patch.object(scheduler, "plan_schedule") as plan:
            result = autonomous.run_autonomous_cycle(force=True, now=self.now, db_path=self.db_path)
        self.assertEqual(result["status"], "busy")
        submit.assert_not_called()
        plan.assert_not_called()

    def test_concurrent_cycle_is_rejected_before_any_action(self):
        with autonomous._cycle_lock, patch.object(autonomous, "_run_autonomous_cycle") as cycle:
            result = autonomous.run_autonomous_cycle(force=True, db_path=self.db_path)
        self.assertEqual(result["reason"], "cycle_in_progress")
        cycle.assert_not_called()

    def test_invalid_legacy_pointer_cannot_permanently_block_buffer(self):
        self._persist_waiting_fixture("invalid-pointer")
        os.remove(scheduler.get_task_final_video("invalid-pointer", self.task_base_dir))
        self.assertEqual(self.cycle()[0]["reason"], "waiting_recovery_failed")
        self.assertEqual(self.cycle()[1:], (1, 0))

    def test_schedule_retry_cooldown_survives_new_cycle(self):
        self._persist_waiting_fixture("race-slot")
        with patch.object(sm.state, "get_task", return_value=None), \
             patch("app.utils.utils.task_dir", return_value=self.task_base_dir), \
             patch.object(scheduler, "plan_schedule", return_value=[]) as plan, \
             patch("app.services.webui_task.submit_generation") as submit:
            result = autonomous.run_autonomous_cycle(force=True, now=self.now, db_path=self.db_path)
            self.assertEqual(result["status"], "waiting_schedule")
            plan.assert_called_once()
            submit.assert_not_called()
            result = autonomous.run_autonomous_cycle(force=True, now=self.now + timedelta(seconds=30), db_path=self.db_path)
            self.assertEqual(result["status"], "generation_started")
            plan.assert_called_once()
            submit.assert_called_once()

    def test_existing_legacy_schedule_counts_without_rescheduling(self):
        self._persist_waiting_fixture("legacy-queued")
        autonomous.set_autonomous_setting(autonomous.KEY_AUTONOMOUS_TARGET_STOCK, "1", self.db_path)
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute("INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at) "
                         "VALUES ('legacy-queued', 'youtube', ?, 'planned', ?)",
                         (self.now.isoformat(), self.now.isoformat()))
        self.assertEqual(self.stock()["ready_count"], 1)
        self.assertEqual(self.cycle(slots=1)[1:], (0, 0))

    def test_latest_quality_and_publication_event_are_authoritative(self):
        self._persist_waiting_fixture("latest")
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute("INSERT INTO content_quality_scores (task_id, topic, quality_score, quality_label, created_at) "
                         "VALUES ('latest', 'Latest assessment', 60, 'REVIEW', ?)", ((self.now + timedelta(seconds=1)).isoformat(),))
        self.assertEqual(self.stock()["ready_count"], 0)
        self._persist_waiting_fixture("published-event")
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute("INSERT INTO publication_events (task_id, platform, published_at, status) "
                         "VALUES ('published-event', 'youtube', ?, 'success')", (self.now.isoformat(),))
        self.assertEqual(self.stock()["ready_count"], 0)

    def test_growth_and_auto_publish_settings_unchanged(self):
        self._persist_waiting_fixture("settings")
        before = scheduler.get_all_settings(self.db_path)
        growth_before = scheduler.get_growth_mode("youtube", self.db_path)
        profile_before = profile_manager.get_profile("default", db_path=self.db_path)
        self.cycle()
        after = scheduler.get_all_settings(self.db_path)
        for key in ("auto_publish_enabled", "youtube_enabled", "tiktok_enabled", "youtube_limit_24h", "tiktok_limit_24h"):
            self.assertEqual(after[key], before[key])
        self.assertEqual(scheduler.get_growth_mode("youtube", self.db_path), growth_before)
        self.assertEqual(profile_manager.get_profile("default", db_path=self.db_path)["growth_mode"],
                         profile_before["growth_mode"])

    def test_invalid_approvals_not_counted(self):
        cases = ("missing_video", "empty_video", "BLOCK", "REVIEW", "missing_safety",
                 "missing_quality", "low_quality", "bad_label", "infinite", "published",
                 "cancelled", "missing_profile", "missing_destination")
        for case in cases:
            with self.subTest(case=case):
                task_id = "invalid-" + case
                video = self._persist_waiting_fixture(task_id)
                with scheduler.get_connection(self.db_path) as conn:
                    if case == "missing_video":
                        os.remove(video)
                    elif case == "empty_video":
                        open(video, "wb").close()
                    elif case in ("BLOCK", "REVIEW"):
                        conn.execute("UPDATE monetization_safety SET safety_status=? WHERE task_id=?", (case, task_id))
                    elif case == "missing_safety":
                        conn.execute("DELETE FROM monetization_safety WHERE task_id=?", (task_id,))
                    elif case == "missing_quality":
                        conn.execute("DELETE FROM content_quality_scores WHERE task_id=?", (task_id,))
                    elif case in ("low_quality", "infinite"):
                        conn.execute("UPDATE content_quality_scores SET quality_score=? WHERE task_id=?",
                                     (69 if case == "low_quality" else float("inf"), task_id))
                    elif case == "bad_label":
                        conn.execute("UPDATE content_quality_scores SET quality_label='REVIEW' WHERE task_id=?", (task_id,))
                    elif case in ("published", "cancelled"):
                        conn.execute("INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at) "
                                     "VALUES (?, 'youtube', ?, ?, ?)", (task_id, self.now.isoformat(), case, self.now.isoformat()))
                    elif case == "missing_profile":
                        conn.execute("DELETE FROM task_profiles WHERE task_id=?", (task_id,))
                    elif case == "missing_destination":
                        conn.execute("DELETE FROM task_platforms WHERE task_id=?", (task_id,))
                self.assertEqual(self.stock()["ready_count"], 0)

    def test_disabled_profile_and_channel_excluded(self):
        self._persist_waiting_fixture("disabled")
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute("UPDATE content_profiles SET is_active=0 WHERE id='default'")
        self.assertEqual(self.stock()["ready_count"], 0)
        profile_manager.set_profile_active("default", True, db_path=self.db_path)
        for channel in profile_manager.list_channels(profile_id="default", db_path=self.db_path):
            profile_manager.set_channel_enabled(channel["channel_id"], False, db_path=self.db_path)
        self.assertEqual(self.stock()["ready_count"], 0)

    def test_active_memory_state_vetoes_persisted_approval(self):
        self._persist_waiting_fixture("active")
        for state in (const.TASK_STATE_PENDING, const.TASK_STATE_PROCESSING, const.TASK_STATE_CANCELLED):
            with patch.object(sm.state, "get_task", return_value={"state": state}):
                self.assertEqual(autonomous.get_autonomous_ready_stock(self.task_base_dir, self.db_path)["ready_count"], 0)

    def test_daily_hard_ceiling_cannot_be_increased(self):
        self._persist_waiting_fixture("daily")
        autonomous.set_autonomous_setting(autonomous.KEY_AUTONOMOUS_MAX_24H, "500", self.db_path)
        for n in range(5):
            operator_console.log_operational_event("autonomous_production", "INFO", "generation_started", str(n), db_path=self.db_path)
        result, generated, planned = self.cycle()
        self.assertEqual(result["reason"], "daily_limit_reached")
        self.assertEqual((generated, planned), (0, 0))

    def test_growth_event_dedup_scope_and_expiry(self):
        rate = {"growth_mode": "WARMUP"}
        def emit(task="a", profile="default", platform="youtube", now=None):
            return scheduler.log_growth_limit_block(task, profile, platform, rate, now or self.now, self.db_path)
        self.assertTrue(emit())
        for seconds in (0, 30, 300, 899):
            self.assertFalse(emit(now=self.now + timedelta(seconds=seconds)))
        self.assertTrue(emit(task="b"))
        self.assertTrue(emit(profile="other"))
        self.assertTrue(emit(platform="tiktok"))
        rate["growth_mode"] = "NORMAL"
        self.assertTrue(emit())
        rate["growth_mode"] = "WARMUP"
        self.assertTrue(emit(now=self.now + timedelta(minutes=15)))

    def test_multiple_waiting_tasks_schedule_one_per_cycle_idempotently(self):
        for n in range(3):
            self._persist_waiting_fixture(f"queue-{n}")
        with patch.object(sm.state, "get_task", return_value=None), \
             patch("app.utils.utils.task_dir", return_value=self.task_base_dir), \
             patch("app.services.webui_task.submit_generation") as submit:
            for n in range(3):
                # Advance beyond the WARMUP rolling window, without publishing.
                result = autonomous.run_autonomous_cycle(force=True, now=self.now + timedelta(days=n), db_path=self.db_path)
                self.assertEqual(result["status"], "scheduled")
            result = autonomous.run_autonomous_cycle(force=True, now=self.now + timedelta(days=3), db_path=self.db_path)
            self.assertEqual(result["status"], "idle")
            submit.assert_not_called()
        with scheduler.get_connection(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT count(DISTINCT task_id) FROM scheduled_posts").fetchone()[0], 3)
            self.assertEqual(conn.execute("SELECT count(*) FROM scheduled_posts").fetchone()[0], 3)
            self.assertEqual(conn.execute("SELECT count(*) FROM scheduled_posts WHERE platform='tiktok'").fetchone()[0], 0)
