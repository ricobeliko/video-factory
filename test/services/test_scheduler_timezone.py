import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.models import const
from app.services import scheduler


class TestSchedulerTimezone(unittest.TestCase):
    """Testes obrigatórios para garantia de consistência temporal (UTC no banco / Local na UI)."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_timezone.db")
        scheduler.init_db(self.db_path)
        self.tz_br = timezone(timedelta(hours=-3))  # Brasil / UTC-3

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_task_structure(self, task_id: str) -> str:
        t_dir = os.path.join(self.test_dir, task_id)
        os.makedirs(t_dir, exist_ok=True)
        v_path = os.path.join(t_dir, "final-1.mp4")
        with open(v_path, "wb") as f:
            f.write(b"fake_mp4_bytes")
        return v_path

    def _insert_post(self, task_id: str, platform: str, scheduled_at_iso: str, status: str = "planned") -> int:
        with scheduler.get_connection(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at)
                VALUES (?, ?, ?, ?, ?);
                """,
                (task_id, platform, scheduled_at_iso, status, scheduled_at_iso),
            )
            return cur.lastrowid

    # 1. +2 min usa corretamente o instante atual
    def test_01_plus_2_min_uses_current_instant_correctly(self):
        local_now = datetime(2026, 9, 16, 20, 56, 0, tzinfo=self.tz_br)
        utc_now = local_now.astimezone(timezone.utc)  # 23:56:00+00:00

        post_id = self._insert_post("task_tz_1", "tiktok", scheduler._to_iso(utc_now + timedelta(hours=2)))
        res = scheduler.reschedule_post_for_test(post_id, minutes_from_now=2, db_path=self.db_path, now=local_now)

        self.assertTrue(res["success"])
        expected_utc_iso = "2026-09-16T23:58:00+00:00"
        self.assertEqual(res["new_scheduled_at"], expected_utc_iso)
        self.assertEqual(res["new_scheduled_at_local"].strftime("%H:%M"), "20:58")
        self.assertEqual(scheduler.format_local_time(res["new_scheduled_at"], fmt="%H:%M", target_tz=self.tz_br), "20:58")

    # 2. UTC armazenado é exibido como horário local
    def test_02_stored_utc_displayed_as_local_time(self):
        utc_iso = "2026-09-16T23:00:00+00:00"
        local_time = scheduler.format_local_time(utc_iso, fmt="%H:%M (%d/%m)", target_tz=self.tz_br)
        self.assertEqual(local_time, "20:00 (16/09)")

    # 3. Worker executa no instante correto
    def test_03_worker_executes_at_correct_instant(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)

        self._create_task_structure("task_due_check")
        scheduler.save_task_platforms("task_due_check", ["tiktok"], db_path=self.db_path)

        # Post agendado para 20:58 local (23:58 UTC)
        sched_time_utc = datetime(2026, 9, 16, 23, 58, 0, tzinfo=timezone.utc)
        self._insert_post("task_due_check", "tiktok", scheduler._to_iso(sched_time_utc))

        with patch("app.services.task.publish_task", return_value=(True, None)) as mock_pub:
            # Às 20:57 local (23:57 UTC) -> Não deve executar
            check_time_1 = datetime(2026, 9, 16, 20, 57, 0, tzinfo=self.tz_br)
            res1 = scheduler.run_scheduler_cycle(now=check_time_1, db_path=self.db_path, task_base_dir=self.test_dir)
            self.assertEqual(res1["status"], "idle")
            mock_pub.assert_not_called()

            # Às 20:58 local (23:58 UTC) -> Deve executar
            check_time_2 = datetime(2026, 9, 16, 20, 58, 0, tzinfo=self.tz_br)
            res2 = scheduler.run_scheduler_cycle(now=check_time_2, db_path=self.db_path, task_base_dir=self.test_dir)
            self.assertEqual(res2["status"], "published")
            mock_pub.assert_called_once()

    # 4. Não ocorre offset duplo
    def test_04_no_double_offset(self):
        orig_utc_iso = "2026-09-16T23:56:00+00:00"
        local_dt = scheduler.to_local_datetime(orig_utc_iso, target_tz=self.tz_br)
        re_utc_iso = scheduler._to_iso(local_dt)
        self.assertEqual(orig_utc_iso, re_utc_iso)

    # 5. Timestamps UTC-aware funcionam
    def test_05_utc_aware_timestamps_work(self):
        dt_aware = datetime(2026, 9, 16, 15, 30, 0, tzinfo=timezone.utc)
        iso_str = scheduler._to_iso(dt_aware)
        self.assertEqual(iso_str, "2026-09-16T15:30:00+00:00")
        parsed_dt = scheduler._from_iso(iso_str)
        self.assertEqual(parsed_dt, dt_aware)
        self.assertIsNotNone(parsed_dt.tzinfo)

    # 6. Timestamps legados naive continuam legíveis
    def test_06_legacy_naive_timestamps_continue_readable(self):
        # Registro gravado sem offset por versão legada
        legacy_naive_iso = "2026-09-16T23:00:00"
        dt = scheduler._from_iso(legacy_naive_iso)
        self.assertEqual(dt.tzinfo, timezone.utc)
        formatted = scheduler.format_local_time(legacy_naive_iso, fmt="%H:%M", target_tz=self.tz_br)
        self.assertEqual(formatted, "20:00")

    # 7. Rolling 24h continua correto
    def test_07_rolling_24h_remains_correct_with_timezones(self):
        # Publicação às 20:00 local (23:00 UTC)
        pub_time = datetime(2026, 9, 16, 20, 0, 0, tzinfo=self.tz_br)
        scheduler.record_publication_event("task_roll", "tiktok", status="success", published_at=pub_time, db_path=self.db_path)

        # Checa limites a partir de horário local 22:00 (01:00 UTC do dia seguinte)
        now_local = datetime(2026, 9, 16, 22, 0, 0, tzinfo=self.tz_br)
        limits_local = scheduler.get_platform_rate_limits("tiktok", db_path=self.db_path, now=now_local)
        self.assertEqual(limits_local["used_past_24h"], 1)

        # Checa usando datetime UTC correspondente (deve ser idêntico)
        now_utc = now_local.astimezone(timezone.utc)
        limits_utc = scheduler.get_platform_rate_limits("tiktok", db_path=self.db_path, now=now_utc)
        self.assertEqual(limits_utc["used_past_24h"], 1)
        self.assertEqual(limits_local["available_slots"], limits_utc["available_slots"])

    # 8. Retry +15m correto
    def test_08_retry_plus_15m_correct(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)

        self._create_task_structure("task_transient")
        scheduler.save_task_platforms("task_transient", ["tiktok"], db_path=self.db_path)

        local_now = datetime(2026, 9, 16, 20, 0, 0, tzinfo=self.tz_br)
        post_id = self._insert_post("task_transient", "tiktok", scheduler._to_iso(local_now))

        with patch("app.services.task.publish_task", return_value=(False, "HTTP 429 Too Many Requests")):
            res = scheduler.run_scheduler_cycle(now=local_now, db_path=self.db_path, task_base_dir=self.test_dir)
            self.assertEqual(res["status"], "retry_scheduled")

            # Retry esperado: +15 minutos = 20:15 local (23:15 UTC)
            expected_retry_utc = "2026-09-16T23:15:00+00:00"
            self.assertEqual(res["next_attempt"], expected_retry_utc)
            self.assertEqual(scheduler.format_local_time(res["next_attempt"], fmt="%H:%M", target_tz=self.tz_br), "20:15")

    # 9. Retry +60m correto
    def test_09_retry_plus_60m_correct(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)

        self._create_task_structure("task_transient_2")
        scheduler.save_task_platforms("task_transient_2", ["tiktok"], db_path=self.db_path)

        local_now = datetime(2026, 9, 16, 20, 0, 0, tzinfo=self.tz_br)
        # Inserindo post com attempts=1
        with scheduler.get_connection(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at, attempts)
                VALUES (?, ?, ?, 'ready', ?, 1);
                """,
                ("task_transient_2", "tiktok", scheduler._to_iso(local_now), scheduler._to_iso(local_now)),
            )
            post_id = cur.lastrowid

        with patch("app.services.task.publish_task", return_value=(False, "Connection timed out")):
            res = scheduler.run_scheduler_cycle(now=local_now, db_path=self.db_path, task_base_dir=self.test_dir)
            self.assertEqual(res["status"], "retry_scheduled")
            self.assertEqual(res["attempt"], 2)

            # Retry esperado: 2ª tentativa = +60 minutos = 21:00 local (00:00 UTC do dia seguinte)
            expected_retry_utc = "2026-09-17T00:00:00+00:00"
            self.assertEqual(res["next_attempt"], expected_retry_utc)
            self.assertEqual(scheduler.format_local_time(res["next_attempt"], fmt="%H:%M", target_tz=self.tz_br), "21:00")

    # 10. Dry Run +30m correto
    def test_10_dry_run_plus_30m_correct(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", True, db_path=self.db_path)

        self._create_task_structure("task_dry_tz")
        scheduler.save_task_platforms("task_dry_tz", ["tiktok"], db_path=self.db_path)

        local_now = datetime(2026, 9, 16, 20, 0, 0, tzinfo=self.tz_br)
        post_id = self._insert_post("task_dry_tz", "tiktok", scheduler._to_iso(local_now))

        res = scheduler.run_scheduler_cycle(now=local_now, db_path=self.db_path, task_base_dir=self.test_dir)
        self.assertEqual(res["status"], "simulated")

        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT scheduled_at, next_attempt_at FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
            # Post postergado para +30m: 20:30 local (23:30 UTC)
            expected_utc = "2026-09-16T23:30:00+00:00"
            self.assertEqual(row["scheduled_at"], expected_utc)
            self.assertEqual(row["next_attempt_at"], expected_utc)
            self.assertEqual(scheduler.format_local_time(row["scheduled_at"], fmt="%H:%M", target_tz=self.tz_br), "20:30")

    # 11. Posts futuros continuam futuros
    def test_11_future_posts_remain_future(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)

        local_now = datetime(2026, 9, 16, 20, 0, 0, tzinfo=self.tz_br)
        # Post para 20:30 local
        local_future = local_now + timedelta(minutes=30)
        self._insert_post("task_fut", "tiktok", scheduler._to_iso(local_future))

        res = scheduler.run_scheduler_cycle(now=local_now, db_path=self.db_path, task_base_dir=self.test_dir)
        self.assertEqual(res["status"], "idle")

    # 12. Posts vencidos continuam vencidos
    def test_12_due_posts_remain_due(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)

        self._create_task_structure("task_due_past")
        scheduler.save_task_platforms("task_due_past", ["tiktok"], db_path=self.db_path)

        # Post vencido há 5 minutos: 19:55 local (22:55 UTC)
        local_now = datetime(2026, 9, 16, 20, 0, 0, tzinfo=self.tz_br)
        local_past = local_now - timedelta(minutes=5)
        self._insert_post("task_due_past", "tiktok", scheduler._to_iso(local_past))

        with patch("app.services.task.publish_task", return_value=(True, None)):
            res = scheduler.run_scheduler_cycle(now=local_now, db_path=self.db_path, task_base_dir=self.test_dir)
            self.assertEqual(res["status"], "published")

    # 13. Teste explícito simulando timezone UTC-3
    def test_13_explicit_utc_minus_3_simulation(self):
        """Cenário exato do requisito:
        local = 20:00 UTC-3
        UTC = 23:00 UTC

        +2 minutos:
        local esperado = 20:02
        UTC persistido = 23:02
        """
        local_dt = datetime(2026, 9, 16, 20, 0, 0, tzinfo=self.tz_br)
        utc_dt = local_dt.astimezone(timezone.utc)
        self.assertEqual(utc_dt.strftime("%H:%M"), "23:00")

        post_id = self._insert_post("task_spec", "youtube", scheduler._to_iso(utc_dt + timedelta(hours=1)))

        res = scheduler.reschedule_post_for_test(post_id, minutes_from_now=2, db_path=self.db_path, now=local_dt)

        self.assertTrue(res["success"])
        # UTC persistido deve ser 23:02
        self.assertEqual(res["new_scheduled_at"], "2026-09-16T23:02:00+00:00")

        # Local esperado na UI deve ser 20:02
        local_formatted = scheduler.format_local_time(res["new_scheduled_at"], fmt="%H:%M", target_tz=self.tz_br)
        self.assertEqual(local_formatted, "20:02")


if __name__ == "__main__":
    unittest.main()
