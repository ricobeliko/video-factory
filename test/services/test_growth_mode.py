import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from app.models import const
from app.services import scheduler


class TestGrowthMode(unittest.TestCase):
    """Testes direcionados da fase V3.1: Account Warm-Up / Ramp-Up Control."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_growth_factory.db")
        scheduler.init_db(self.db_path)
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)

        self.tasks_base_dir = os.path.join(self.temp_dir.name, "tasks")
        os.makedirs(self.tasks_base_dir, exist_ok=True)

    def tearDown(self):
        scheduler.stop_scheduler_worker()
        import gc
        gc.collect()
        self.temp_dir.cleanup()

    def _create_mock_task(self, task_id: str, platforms: list) -> str:
        """Cria artefatos de vídeo e destinos persistidos para a tarefa de teste."""
        task_dir = os.path.join(self.tasks_base_dir, task_id)
        os.makedirs(task_dir, exist_ok=True)
        video_path = os.path.join(task_dir, "final-1.mp4")
        with open(video_path, "wb") as f:
            f.write(b"mock video content")
        scheduler.save_task_platforms(task_id, platforms, db_path=self.db_path)
        return task_dir

    def test_01_default_growth_mode_is_warmup(self):
        """1. Default para conta nova deve ser WARMUP."""
        mode = scheduler.get_growth_mode(db_path=self.db_path)
        self.assertEqual(mode, const.GROWTH_MODE_WARMUP)

        settings = scheduler.get_all_settings(db_path=self.db_path)
        self.assertEqual(settings["growth_mode"], const.GROWTH_MODE_WARMUP)

    def test_02_warmup_youtube_limit_is_one(self):
        """2. Warmup YouTube deve limitar a 1 post / 24h."""
        limit = scheduler.get_effective_limit("youtube", 10, mode=const.GROWTH_MODE_WARMUP, db_path=self.db_path)
        self.assertEqual(limit, 1)

        rate = scheduler.get_platform_rate_limits("youtube", db_path=self.db_path, growth_mode=const.GROWTH_MODE_WARMUP)
        self.assertEqual(rate["effective_limit"], 1)
        self.assertEqual(rate["limit"], 1)
        self.assertEqual(rate["available_slots"], 1)

    def test_03_warmup_tiktok_limit_is_one(self):
        """3. Warmup TikTok deve limitar a 1 post / 24h."""
        limit = scheduler.get_effective_limit("tiktok", 15, mode=const.GROWTH_MODE_WARMUP, db_path=self.db_path)
        self.assertEqual(limit, 1)

        rate = scheduler.get_platform_rate_limits("tiktok", db_path=self.db_path, growth_mode=const.GROWTH_MODE_WARMUP)
        self.assertEqual(rate["effective_limit"], 1)
        self.assertEqual(rate["limit"], 1)
        self.assertEqual(rate["available_slots"], 1)

    def test_04_conservative_limits_are_two(self):
        """4. Modo Conservative deve ser 2/24h com intervalo mínimo de 6h."""
        yt_lim = scheduler.get_effective_limit("youtube", 10, mode=const.GROWTH_MODE_CONSERVATIVE, db_path=self.db_path)
        tk_lim = scheduler.get_effective_limit("tiktok", 15, mode=const.GROWTH_MODE_CONSERVATIVE, db_path=self.db_path)
        self.assertEqual(yt_lim, 2)
        self.assertEqual(tk_lim, 2)

        scheduler.set_growth_mode(const.GROWTH_MODE_CONSERVATIVE, db_path=self.db_path)
        info = scheduler.get_growth_mode_info("youtube", db_path=self.db_path)
        self.assertEqual(info["max_posts_24h"], 2)
        self.assertEqual(info["min_interval_hours"], 6)

    def test_05_normal_limits_are_three(self):
        """5. Modo Normal deve ser 3/24h com intervalo mínimo de 4h."""
        scheduler.set_growth_mode(const.GROWTH_MODE_NORMAL, db_path=self.db_path)
        yt_lim = scheduler.get_effective_limit("youtube", 10, mode=const.GROWTH_MODE_NORMAL, db_path=self.db_path)
        tk_lim = scheduler.get_effective_limit("tiktok", 15, mode=const.GROWTH_MODE_NORMAL, db_path=self.db_path)
        self.assertEqual(yt_lim, 3)
        self.assertEqual(tk_lim, 3)

        info = scheduler.get_growth_mode_info("tiktok", db_path=self.db_path)
        self.assertEqual(info["max_posts_24h"], 3)
        self.assertEqual(info["min_interval_hours"], 4)

    def test_06_lowest_limit_prevails(self):
        """6. O menor limite sempre prevalece entre o técnico e o growth mode."""
        # Se técnico for 10 e modo warmup (1), efetivo é 1
        self.assertEqual(scheduler.get_effective_limit("youtube", 10, mode=const.GROWTH_MODE_WARMUP), 1)
        # Se técnico for 1 e modo normal (3), efetivo é 1 (técnico menor prevalece)
        self.assertEqual(scheduler.get_effective_limit("youtube", 1, mode=const.GROWTH_MODE_NORMAL), 1)
        # Se técnico for 2 e modo conservative (2), efetivo é 2
        self.assertEqual(scheduler.get_effective_limit("tiktok", 2, mode=const.GROWTH_MODE_CONSERVATIVE), 2)
        # Modo scale usa o teto técnico existente
        self.assertEqual(scheduler.get_effective_limit("youtube", 7, mode=const.GROWTH_MODE_SCALE), 7)

    def test_07_min_interval_enforced(self):
        """7. Intervalo mínimo é respeitado entre agendamentos (anti-burst)."""
        scheduler.set_growth_mode(const.GROWTH_MODE_CONSERVATIVE, db_path=self.db_path)
        now = datetime.now(timezone.utc)
        tasks = [
            {"task_id": "task-ib-1", "state": const.TASK_STATE_COMPLETE, "planned_platforms": ["youtube"], "subject": "Video 1"},
            {"task_id": "task-ib-2", "state": const.TASK_STATE_COMPLETE, "planned_platforms": ["youtube"], "subject": "Video 2"},
        ]
        created = scheduler.plan_schedule(tasks, now=now, db_path=self.db_path, growth_mode=const.GROWTH_MODE_CONSERVATIVE)
        self.assertEqual(len(created), 2)

        dt1 = scheduler._from_iso(created[0]["scheduled_at"])
        dt2 = scheduler._from_iso(created[1]["scheduled_at"])
        diff_hours = (dt2 - dt1).total_seconds() / 3600.0
        # No modo conservative, o min_interval é 6h
        self.assertGreaterEqual(diff_hours, 6.0)

    def test_08_second_post_in_warmup_is_rescheduled(self):
        """8. Segundo post no warmup não cabe na mesma janela de 24h e não é agendado junto."""
        scheduler.set_growth_mode(const.GROWTH_MODE_WARMUP, db_path=self.db_path)
        now = datetime.now(timezone.utc)
        tasks = [
            {"task_id": "task-w1", "state": const.TASK_STATE_COMPLETE, "planned_platforms": ["youtube"], "subject": "W1"},
            {"task_id": "task-w2", "state": const.TASK_STATE_COMPLETE, "planned_platforms": ["youtube"], "subject": "W2"},
        ]
        created = scheduler.plan_schedule(tasks, now=now, db_path=self.db_path, growth_mode=const.GROWTH_MODE_WARMUP)
        # No warmup, o limite é 1/24h, logo apenas 1 slot é gerado imediatamente na janela de 24h
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["task_id"], "task-w1")

    def test_09_growth_mode_block_does_not_mark_failed(self):
        """9. Bloqueio por limite ou intervalo no executor adia o post sem marcar failed."""
        now = datetime.now(timezone.utc)
        iso_past = scheduler._to_iso(now - timedelta(minutes=5))
        scheduler.set_growth_mode(const.GROWTH_MODE_WARMUP, db_path=self.db_path)

        self._create_mock_task("task-mock-1", ["youtube"])

        # Insere um post vencido pronto para publicação
        with scheduler.get_connection(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at) VALUES (?, ?, ?, 'ready', ?);",
                ("task-mock-1", "youtube", iso_past, iso_past),
            )
            post_id = cur.lastrowid

        # Simula que o limite de 24h já está preenchido por 1 publicação recente
        scheduler.record_publication_event(
            task_id="task-prior",
            platform="youtube",
            status="success",
            published_at=now - timedelta(hours=2),
            db_path=self.db_path,
        )

        res = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tasks_base_dir)
        self.assertEqual(res["status"], "postponed")

        # Verifica que o post não foi marcado como failed no banco
        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT status, last_error FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
            self.assertNotEqual(row["status"], scheduler.STATUS_FAILED)
            self.assertIn(row["status"], (scheduler.STATUS_READY, scheduler.STATUS_PLANNED))

    def test_10_dry_run_does_not_count_as_real_publication(self):
        """10. Simulação Dry Run não conta como publicação real."""
        now = datetime.now(timezone.utc)
        iso_past = scheduler._to_iso(now - timedelta(minutes=5))
        scheduler.set_setting("dry_run", True, db_path=self.db_path)

        self._create_mock_task("task-sim-1", ["youtube"])

        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                "INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at) VALUES (?, ?, ?, 'ready', ?);",
                ("task-sim-1", "youtube", iso_past, iso_past),
            )

        res = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tasks_base_dir)
        self.assertEqual(res["status"], "simulated")

        # Confirma que publication_events permanece vazio de publicações reais
        rate = scheduler.get_platform_rate_limits("youtube", db_path=self.db_path, now=now)
        self.assertEqual(rate["used_past_24h"], 0)

    def test_11_publication_events_success_counts(self):
        """11. Eventos com status='success' em publication_events consomem a quota."""
        now = datetime.now(timezone.utc)
        scheduler.record_publication_event(
            task_id="task-real-1",
            platform="youtube",
            status="success",
            published_at=now - timedelta(hours=3),
            db_path=self.db_path,
        )
        rate = scheduler.get_platform_rate_limits("youtube", db_path=self.db_path, now=now)
        self.assertEqual(rate["used_past_24h"], 1)

    def test_12_scheduled_future_considered_in_planning(self):
        """12. Posts agendados futuros são considerados no cálculo de slots disponíveis."""
        now = datetime.now(timezone.utc)
        iso_future = scheduler._to_iso(now + timedelta(hours=2))
        scheduler.set_growth_mode(const.GROWTH_MODE_CONSERVATIVE, db_path=self.db_path) # Limite 2

        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                "INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at) VALUES (?, ?, ?, 'planned', ?);",
                ("task-fut-1", "youtube", iso_future, scheduler._to_iso(now)),
            )

        rate = scheduler.get_platform_rate_limits("youtube", db_path=self.db_path, now=now)
        self.assertEqual(rate["scheduled_24h"], 1)
        self.assertEqual(rate["total_used"], 1)
        # Limite é 2, já tem 1 agendado, restam 1
        self.assertEqual(rate["available_slots"], 1)

    def test_13_growth_mode_persists_after_restart(self):
        """13. Mudança de modo de crescimento persiste no SQLite."""
        scheduler.set_growth_mode(const.GROWTH_MODE_NORMAL, db_path=self.db_path)
        # Reabre e consulta
        mode = scheduler.get_growth_mode(db_path=self.db_path)
        self.assertEqual(mode, const.GROWTH_MODE_NORMAL)

    def test_14_safety_review_block_gated_before_growth_mode(self):
        """14. Tarefas Safety BLOCK / REVIEW continuam bloqueadas antes do Growth Mode."""
        now = datetime.now(timezone.utc)
        tasks = [
            {"task_id": "task-safe-pass", "state": const.TASK_STATE_COMPLETE, "planned_platforms": ["youtube"], "safety_status": const.SAFETY_STATUS_PASS},
            {"task_id": "task-safe-review", "state": const.TASK_STATE_COMPLETE, "planned_platforms": ["youtube"], "safety_status": const.SAFETY_STATUS_REVIEW},
            {"task_id": "task-safe-block", "state": const.TASK_STATE_COMPLETE, "planned_platforms": ["youtube"], "safety_status": const.SAFETY_STATUS_BLOCK},
        ]
        created = scheduler.plan_schedule(tasks, now=now, db_path=self.db_path, growth_mode=const.GROWTH_MODE_SCALE)
        # Apenas task-safe-pass entra
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["task_id"], "task-safe-pass")

    def test_15_executor_revalidates_growth_mode_at_runtime(self):
        """15. Executor revalida o intervalo mínimo de growth mode no momento da publicação."""
        now = datetime.now(timezone.utc)
        iso_past = scheduler._to_iso(now - timedelta(minutes=5))
        scheduler.set_growth_mode(const.GROWTH_MODE_WARMUP, db_path=self.db_path)

        self._create_mock_task("task-rt-1", ["youtube"])

        # Insere post pronto para publicação vencido
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                "INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at) VALUES (?, ?, ?, 'ready', ?);",
                ("task-rt-1", "youtube", iso_past, iso_past),
            )

        # Simula publicação recente há apenas 2 horas (warmup exige 8h)
        recent_pub = now - timedelta(hours=2)
        scheduler.record_publication_event(
            task_id="task-prev",
            platform="youtube",
            status="success",
            published_at=recent_pub,
            db_path=self.db_path,
        )

        res = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tasks_base_dir)

        # Deve adiar pelo rate_limit_reached (1/24h) ou min_interval_not_met
        self.assertEqual(res["status"], "postponed")
        self.assertIn(res["reason"], ("rate_limit_reached", "min_interval_not_met"))
