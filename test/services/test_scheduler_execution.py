import gc
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from io import StringIO
from unittest.mock import MagicMock, patch

from loguru import logger

from app.config import config
from app.models import const
from app.services import scheduler
from app.services import state as sm
from app.services import task as tm
from app.services.state import MemoryState
from app.utils import utils


class TestSchedulerExecutionEngine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_exec.db")
        scheduler.init_db(self.db_path)
        scheduler.reset_executor_status()

        # Set in-memory task state
        self.state = MemoryState()
        self.patcher_state = patch.object(tm.sm, "state", self.state)
        self.patcher_state.start()

        # Task files directory
        self.tasks_base_dir = os.path.join(self.temp_dir.name, "tasks")
        os.makedirs(self.tasks_base_dir, exist_ok=True)
        self.patcher_task_dir = patch.object(utils, "task_dir", return_value=self.tasks_base_dir)
        self.patcher_task_dir.start()

        # Upload-post configuration
        self.test_config = dict(
            config.app,
            upload_post_enabled=True,
            upload_post_api_key="super-secret-key-12345",
            upload_post_username="testuser",
            upload_post_platforms=["tiktok", "youtube"],
        )
        self.patcher_config = patch.object(config, "app", self.test_config)
        self.patcher_config.start()

        # Mock social metadata generation to avoid external LLM calls
        self.patcher_meta = patch(
            "app.services.llm.generate_social_metadata",
            return_value={"title": "Test Title", "caption": "Test Caption", "hashtags": ["test"]},
        )
        self.patcher_meta.start()

    def tearDown(self):
        scheduler.stop_scheduler_worker()
        self.patcher_meta.stop()
        self.patcher_config.stop()
        self.patcher_task_dir.stop()
        self.patcher_state.stop()
        gc.collect()
        self.temp_dir.cleanup()

    def _create_task(self, task_id: str, platforms: list[str], has_video: bool = True) -> str:
        """Cria os artefatos de uma tarefa em disco e registra em task_platforms e sm.state."""
        task_dir = os.path.join(self.tasks_base_dir, task_id)
        os.makedirs(task_dir, exist_ok=True)

        video_path = None
        if has_video:
            video_path = os.path.join(task_dir, "final-1.mp4")
            with open(video_path, "wb") as f:
                f.write(b"dummy mp4 video content")

        script_path = os.path.join(task_dir, "script.json")
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump({
                "script": "Script content",
                "params": {"video_subject": f"Subject of {task_id}", "video_language": "pt"}
            }, f)

        # Salva em task_platforms do SQLite
        scheduler.save_task_platforms(task_id, platforms, db_path=self.db_path)

        # Salva no MemoryState
        self.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            videos=[video_path] if video_path else [],
            planned_platforms=platforms,
            subject=f"Subject of {task_id}",
            video_subject=f"Subject of {task_id}",
            cross_post_state=None,
        )
        return task_dir

    def _insert_scheduled_post(
        self,
        task_id: str,
        platform: str,
        scheduled_at: datetime,
        status: str = "planned",
        attempts: int = 0,
        next_attempt_at: datetime | None = None,
    ) -> int:
        with scheduler.get_connection(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at, attempts, next_attempt_at)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    task_id,
                    platform,
                    scheduler._to_iso(scheduled_at),
                    status,
                    scheduler._to_iso(datetime.now(timezone.utc)),
                    attempts,
                    scheduler._to_iso(next_attempt_at) if next_attempt_at else None,
                ),
            )
            return cur.lastrowid

    # 1. Post futuro não executa
    def test_01_future_post_does_not_execute(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)

        now = datetime.now(timezone.utc)
        self._create_task("task-fut-1", ["tiktok"])
        self._insert_scheduled_post("task-fut-1", "tiktok", now + timedelta(hours=2))

        with patch("app.services.upload_post.cross_post_video") as mock_upload:
            res = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tasks_base_dir)
            self.assertEqual(res["status"], "idle")
            mock_upload.assert_not_called()

    # 2. Post vencido + scheduler OFF não executa
    def test_02_due_post_with_scheduler_off_does_not_execute(self):
        scheduler.set_setting("scheduler_enabled", False, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)

        now = datetime.now(timezone.utc)
        self._create_task("task-off-1", ["tiktok"])
        self._insert_scheduled_post("task-off-1", "tiktok", now - timedelta(minutes=5))

        with patch("app.services.upload_post.cross_post_video") as mock_upload:
            res = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tasks_base_dir)
            self.assertEqual(res["status"], "skipped")
            self.assertEqual(res["reason"], "scheduler_disabled")
            mock_upload.assert_not_called()

    # 3. Scheduler ON + auto-publish OFF não executa
    def test_03_scheduler_on_auto_publish_off_does_not_execute(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", False, db_path=self.db_path)

        now = datetime.now(timezone.utc)
        self._create_task("task-autooff-1", ["tiktok"])
        self._insert_scheduled_post("task-autooff-1", "tiktok", now - timedelta(minutes=5))

        with patch("app.services.upload_post.cross_post_video") as mock_upload:
            res = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tasks_base_dir)
            self.assertEqual(res["status"], "skipped")
            self.assertEqual(res["reason"], "auto_publish_disabled")
            mock_upload.assert_not_called()

    # 4. DRY RUN não chama Upload-Post
    def test_04_dry_run_does_not_call_upload_post(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", True, db_path=self.db_path)

        now = datetime.now(timezone.utc)
        self._create_task("task-dry-1", ["tiktok"])
        self._insert_scheduled_post("task-dry-1", "tiktok", now - timedelta(minutes=5))

        with patch("app.services.upload_post.cross_post_video") as mock_upload:
            res = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tasks_base_dir)
            self.assertEqual(res["status"], "simulated")
            mock_upload.assert_not_called()

            # Valida que não gravou evento de sucesso real
            with scheduler.get_connection(self.db_path) as conn:
                count = conn.execute("SELECT COUNT(*) AS cnt FROM publication_events WHERE status = 'success';").fetchone()["cnt"]
                self.assertEqual(count, 0)
                # Post continua planejado/ready (não 'published')
                st = conn.execute("SELECT status FROM scheduled_posts WHERE task_id = 'task-dry-1';").fetchone()["status"]
                self.assertIn(st, ("planned", "ready"))

    # 5. Post vencido elegível executa em modo real
    def test_05_due_eligible_post_executes_in_real_mode(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)

        now = datetime.now(timezone.utc)
        self._create_task("task-real-1", ["tiktok"])
        self._insert_scheduled_post("task-real-1", "tiktok", now - timedelta(minutes=5))

        with patch("app.services.upload_post.cross_post_video", return_value={"success": True, "request_id": "req-999"}) as mock_upload:
            res = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tasks_base_dir)
            self.assertEqual(res["status"], "published")
            mock_upload.assert_called_once()

            # Status no banco deve ser 'published'
            with scheduler.get_connection(self.db_path) as conn:
                st = conn.execute("SELECT status FROM scheduled_posts WHERE task_id = 'task-real-1';").fetchone()["status"]
                self.assertEqual(st, "published")

    # 6. Publica somente na plataforma planejada
    def test_06_publishes_only_to_planned_platform(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)

        now = datetime.now(timezone.utc)
        self._create_task("task-plat-1", ["tiktok"])
        self._insert_scheduled_post("task-plat-1", "tiktok", now - timedelta(minutes=2))

        with patch("app.services.upload_post.cross_post_video", return_value={"success": True, "request_id": "req-tk"}) as mock_upload:
            res = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tasks_base_dir)
            self.assertEqual(res["status"], "published")
            mock_upload.assert_called_once()
            call_kwargs = mock_upload.call_args.kwargs
            self.assertEqual(call_kwargs["platforms"], ["tiktok"])

    # 7. TikTok não dispara YouTube
    def test_07_tiktok_does_not_trigger_youtube(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)

        now = datetime.now(timezone.utc)
        self._create_task("task-both-1", ["tiktok", "youtube"])
        self._insert_scheduled_post("task-both-1", "tiktok", now - timedelta(minutes=10))
        self._insert_scheduled_post("task-both-1", "youtube", now + timedelta(hours=2))

        with patch("app.services.upload_post.cross_post_video", return_value={"success": True, "request_id": "req-tk-only"}) as mock_upload:
            res = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tasks_base_dir)
            self.assertEqual(res["status"], "published")
            self.assertEqual(res["platform"], "tiktok")
            mock_upload.assert_called_once()
            self.assertEqual(mock_upload.call_args.kwargs["platforms"], ["tiktok"])

            # YouTube deve permanecer planned
            with scheduler.get_connection(self.db_path) as conn:
                yt_status = conn.execute(
                    "SELECT status FROM scheduled_posts WHERE task_id = 'task-both-1' AND platform = 'youtube';"
                ).fetchone()["status"]
                self.assertEqual(yt_status, "planned")

    # 8. YouTube não dispara TikTok
    def test_08_youtube_does_not_trigger_tiktok(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)

        now = datetime.now(timezone.utc)
        self._create_task("task-both-2", ["tiktok", "youtube"])
        self._insert_scheduled_post("task-both-2", "youtube", now - timedelta(minutes=5))
        self._insert_scheduled_post("task-both-2", "tiktok", now + timedelta(hours=3))

        with patch("app.services.upload_post.cross_post_video", return_value={"success": True, "request_id": "req-yt-only"}) as mock_upload:
            res = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tasks_base_dir)
            self.assertEqual(res["status"], "published")
            self.assertEqual(res["platform"], "youtube")
            mock_upload.assert_called_once()
            self.assertEqual(mock_upload.call_args.kwargs["platforms"], ["youtube"])

            # TikTok deve permanecer planned
            with scheduler.get_connection(self.db_path) as conn:
                tk_status = conn.execute(
                    "SELECT status FROM scheduled_posts WHERE task_id = 'task-both-2' AND platform = 'tiktok';"
                ).fetchone()["status"]
                self.assertEqual(tk_status, "planned")

    # 9. task_id + platform já publicado não duplica
    def test_09_task_id_platform_already_published_does_not_duplicate(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)

        now = datetime.now(timezone.utc)
        self._create_task("task-dup-1", ["tiktok"])
        scheduler.record_publication_event("task-dup-1", "tiktok", status="success", db_path=self.db_path)
        self._insert_scheduled_post("task-dup-1", "tiktok", now - timedelta(minutes=5), status="planned")

        with patch("app.services.upload_post.cross_post_video") as mock_upload:
            res = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tasks_base_dir)
            self.assertEqual(res["status"], "skipped")
            self.assertEqual(res["reason"], "already_published")
            mock_upload.assert_not_called()

    # 10. Reinício/reexecução lógica não duplica
    def test_10_restart_reexecution_does_not_duplicate(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)

        now = datetime.now(timezone.utc)
        self._create_task("task-restart-1", ["tiktok"])
        self._insert_scheduled_post("task-restart-1", "tiktok", now - timedelta(minutes=15), status="published")

        with patch("app.services.upload_post.cross_post_video") as mock_upload:
            res = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tasks_base_dir)
            self.assertEqual(res["status"], "idle")
            mock_upload.assert_not_called()

    # 11. Limite rolling 24h impede execução
    def test_11_rolling_24h_limit_prevents_execution(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)
        scheduler.set_setting("tiktok_limit_24h", 3, db_path=self.db_path)

        now = datetime.now(timezone.utc)
        # Preenche as 3 vagas nas últimas 24h
        for i in range(3):
            scheduler.record_publication_event(
                f"task-lim-{i}", "tiktok", status="success",
                published_at=now - timedelta(hours=2 + i), db_path=self.db_path
            )

        self._create_task("task-lim-blocked", ["tiktok"])
        post_id = self._insert_scheduled_post("task-lim-blocked", "tiktok", now - timedelta(minutes=5))

        with patch("app.services.upload_post.cross_post_video") as mock_upload:
            res = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tasks_base_dir)
            self.assertEqual(res["status"], "postponed")
            self.assertEqual(res["reason"], "rate_limit_reached")
            mock_upload.assert_not_called()

            # Deve ter sido postergado sem marcar falha
            with scheduler.get_connection(self.db_path) as conn:
                row = conn.execute("SELECT status, scheduled_at FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
                self.assertEqual(row["status"], "ready")
                new_dt = scheduler._from_iso(row["scheduled_at"])
                self.assertGreater(new_dt, now)

    # 12. Limite liberado permite execução
    def test_12_available_limit_allows_execution(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)
        scheduler.set_setting("tiktok_limit_24h", 5, db_path=self.db_path)

        now = datetime.now(timezone.utc)
        # Preenche apenas 2 vagas (3 disponíveis)
        for i in range(2):
            scheduler.record_publication_event(
                f"task-ok-{i}", "tiktok", status="success",
                published_at=now - timedelta(hours=1), db_path=self.db_path
            )

        self._create_task("task-ok-avail", ["tiktok"])
        self._insert_scheduled_post("task-ok-avail", "tiktok", now - timedelta(minutes=5))

        with patch("app.services.upload_post.cross_post_video", return_value={"success": True, "request_id": "req-ok"}) as mock_upload:
            res = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tasks_base_dir)
            self.assertEqual(res["status"], "published")
            mock_upload.assert_called_once()

    # 13. Múltiplos posts vencidos processados por scheduled_at ASC
    def test_13_multiple_due_posts_processed_scheduled_at_asc(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)

        now = datetime.now(timezone.utc)
        self._create_task("task-older", ["tiktok"])
        self._create_task("task-newer", ["tiktok"])

        self._insert_scheduled_post("task-newer", "tiktok", now - timedelta(minutes=5))
        self._insert_scheduled_post("task-older", "tiktok", now - timedelta(minutes=25))

        with patch("app.services.upload_post.cross_post_video", return_value={"success": True, "request_id": "req-1"}) as mock_upload:
            res = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tasks_base_dir)
            self.assertEqual(res["task_id"], "task-older")

    # 14. Somente um upload por vez
    def test_14_only_one_upload_at_a_time(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)

        now = datetime.now(timezone.utc)
        self._create_task("task-one-1", ["tiktok"])
        self._create_task("task-one-2", ["tiktok"])

        self._insert_scheduled_post("task-one-1", "tiktok", now - timedelta(minutes=15))
        self._insert_scheduled_post("task-one-2", "tiktok", now - timedelta(minutes=10))

        with patch("app.services.upload_post.cross_post_video", return_value={"success": True, "request_id": "req-one"}) as mock_upload:
            res = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tasks_base_dir)
            self.assertEqual(res["status"], "published")
            self.assertEqual(mock_upload.call_count, 1)

    # 15. Erro transient reagenda com backoff
    def test_15_transient_error_reschedules_with_backoff(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)

        now = datetime.now(timezone.utc)
        self._create_task("task-retry-1", ["tiktok"])
        post_id = self._insert_scheduled_post("task-retry-1", "tiktok", now - timedelta(minutes=5))

        with patch("app.services.upload_post.cross_post_video", return_value={"success": False, "error": "HTTP 429 Rate limit exceeded"}):
            res = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tasks_base_dir)
            self.assertEqual(res["status"], "retry_scheduled")
            self.assertEqual(res["attempt"], 1)

            with scheduler.get_connection(self.db_path) as conn:
                row = conn.execute("SELECT status, attempts, next_attempt_at FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
                self.assertEqual(row["status"], "ready")
                self.assertEqual(row["attempts"], 1)
                retry_dt = scheduler._from_iso(row["next_attempt_at"])
                self.assertAlmostEqual((retry_dt - now).total_seconds(), 900, delta=10)

    # 16. Retry não ocorre imediatamente
    def test_16_retry_does_not_occur_immediately(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)

        now = datetime.now(timezone.utc)
        self._create_task("task-retry-noimm", ["tiktok"])
        # Post com next_attempt_at no futuro (+10 minutos)
        self._insert_scheduled_post(
            "task-retry-noimm", "tiktok", now - timedelta(minutes=10),
            status="ready", attempts=1, next_attempt_at=now + timedelta(minutes=10)
        )

        with patch("app.services.upload_post.cross_post_video") as mock_upload:
            res = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tasks_base_dir)
            self.assertEqual(res["status"], "idle")
            mock_upload.assert_not_called()

    # 17. Max attempts encerra corretamente em failed
    def test_17_max_attempts_terminates_in_failed(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)

        now = datetime.now(timezone.utc)
        self._create_task("task-max-1", ["tiktok"])
        # Post já na 2ª tentativa (próxima será a 3ª)
        post_id = self._insert_scheduled_post(
            "task-max-1", "tiktok", now - timedelta(minutes=5),
            status="ready", attempts=2
        )

        with patch("app.services.upload_post.cross_post_video", return_value={"success": False, "error": "Connection timed out"}):
            res = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tasks_base_dir)
            self.assertEqual(res["status"], "failed")

            with scheduler.get_connection(self.db_path) as conn:
                row = conn.execute("SELECT status, attempts FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
                self.assertEqual(row["status"], "failed")
                self.assertEqual(row["attempts"], 3)

    # 18. Erro permanente vira failed de imediato
    def test_18_permanent_error_becomes_failed_immediately(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)

        now = datetime.now(timezone.utc)
        self._create_task("task-perm-1", ["tiktok"])
        post_id = self._insert_scheduled_post("task-perm-1", "tiktok", now - timedelta(minutes=5))

        with patch("app.services.upload_post.cross_post_video", return_value={"success": False, "error": "Invalid API key or account revoked"}):
            res = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tasks_base_dir)
            self.assertEqual(res["status"], "failed")

            with scheduler.get_connection(self.db_path) as conn:
                row = conn.execute("SELECT status, attempts, last_error FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
                self.assertEqual(row["status"], "failed")
                self.assertEqual(row["attempts"], 1)
                self.assertIn("Invalid API key", row["last_error"])

    # 19. Scheduler OFF pausa executor sem apagar agenda
    def test_19_scheduler_off_pauses_executor_without_clearing_schedule(self):
        scheduler.set_setting("scheduler_enabled", False, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)

        now = datetime.now(timezone.utc)
        self._create_task("task-pause-1", ["tiktok"])
        post_id = self._insert_scheduled_post("task-pause-1", "tiktok", now - timedelta(minutes=5))

        res = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tasks_base_dir)
        self.assertEqual(res["status"], "skipped")

        with scheduler.get_connection(self.db_path) as conn:
            cnt = conn.execute("SELECT COUNT(*) AS cnt FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()["cnt"]
            self.assertEqual(cnt, 1)

    # 20. Vídeo inexistente não tenta publicar
    def test_20_missing_video_does_not_attempt_publish(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)

        now = datetime.now(timezone.utc)
        self._create_task("task-no-vid", ["tiktok"], has_video=False)
        post_id = self._insert_scheduled_post("task-no-vid", "tiktok", now - timedelta(minutes=5))

        with patch("app.services.upload_post.cross_post_video") as mock_upload:
            res = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tasks_base_dir)
            self.assertEqual(res["status"], "failed")
            self.assertEqual(res["reason"], "video_not_found")
            mock_upload.assert_not_called()

            with scheduler.get_connection(self.db_path) as conn:
                st = conn.execute("SELECT status FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()["status"]
                self.assertEqual(st, "failed")

    # 21. Planned platform ausente não tenta publicar
    def test_21_absent_planned_platform_does_not_attempt_publish(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)

        now = datetime.now(timezone.utc)
        # Task planejada apenas para youtube
        self._create_task("task-only-yt", ["youtube"])
        # Mas post foi agendado para tiktok
        post_id = self._insert_scheduled_post("task-only-yt", "tiktok", now - timedelta(minutes=5))

        with patch("app.services.upload_post.cross_post_video") as mock_upload:
            res = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tasks_base_dir)
            self.assertEqual(res["status"], "failed")
            self.assertEqual(res["reason"], "platform_not_planned")
            mock_upload.assert_not_called()

    # 22. publication_events success persiste corretamente
    def test_22_publication_events_success_persists_correctly(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)

        now = datetime.now(timezone.utc)
        self._create_task("task-ev-1", ["tiktok"])
        self._insert_scheduled_post("task-ev-1", "tiktok", now - timedelta(minutes=5))

        with patch("app.services.upload_post.cross_post_video", return_value={"success": True, "request_id": "req-ev-123", "results": {"tiktok": {"post_id": "tk-post-123"}}}):
            res = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tasks_base_dir)
            self.assertEqual(res["status"], "published")

            with scheduler.get_connection(self.db_path) as conn:
                row = conn.execute("SELECT * FROM publication_events WHERE task_id = 'task-ev-1';").fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row["platform"], "tiktok")
                self.assertEqual(row["status"], "success")
                self.assertEqual(row["external_id"], "tk-post-123")
                self.assertEqual(row["provider_request_id"], "req-ev-123")

    # 23. cross_post global não fica COMPLETE se ainda faltar outra plataforma
    def test_23_cross_post_global_not_complete_if_other_platform_pending(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)

        now = datetime.now(timezone.utc)
        self._create_task("task-multi-cross", ["tiktok", "youtube"])
        self._insert_scheduled_post("task-multi-cross", "tiktok", now - timedelta(minutes=10))
        self._insert_scheduled_post("task-multi-cross", "youtube", now + timedelta(hours=3))

        with patch("app.services.upload_post.cross_post_video", return_value={"success": True, "request_id": "req-tk-done"}):
            res = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tasks_base_dir)
            self.assertEqual(res["status"], "published")

            # No MemoryState, o cross_post_state da task NÃO pode ser COMPLETE ainda!
            t = self.state.get_task("task-multi-cross")
            self.assertNotEqual(t.get("cross_post_state"), const.CROSS_POST_STATE_COMPLETE)
            self.assertEqual(t.get("cross_post_state"), const.CROSS_POST_STATE_PARTIAL)

    # 24. Quando todas as plataformas terminarem, estado global fica consistente
    def test_24_when_all_platforms_finished_cross_post_global_is_complete(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)

        now = datetime.now(timezone.utc)
        self._create_task("task-full-finish", ["tiktok", "youtube"])
        self._insert_scheduled_post("task-full-finish", "tiktok", now - timedelta(minutes=10))
        self._insert_scheduled_post("task-full-finish", "youtube", now - timedelta(minutes=5))

        with patch("app.services.upload_post.cross_post_video", return_value={"success": True, "request_id": "req-full"}):
            # 1º ciclo: publica TikTok
            res1 = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tasks_base_dir)
            self.assertEqual(res1["status"], "published")
            self.assertEqual(res1["platform"], "tiktok")
            t_mid = self.state.get_task("task-full-finish")
            self.assertEqual(t_mid.get("cross_post_state"), const.CROSS_POST_STATE_PARTIAL)

            # 2º ciclo: publica YouTube
            res2 = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tasks_base_dir)
            self.assertEqual(res2["status"], "published")
            self.assertEqual(res2["platform"], "youtube")

            # Agora sim, estado global fica COMPLETE
            t_end = self.state.get_task("task-full-finish")
            self.assertEqual(t_end.get("cross_post_state"), const.CROSS_POST_STATE_COMPLETE)

    # 25. Nenhum secret aparece em logs
    def test_25_no_secrets_appear_in_logs(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)

        log_capture = StringIO()
        handler_id = logger.add(log_capture, format="{message}")

        now = datetime.now(timezone.utc)
        self._create_task("task-secret-check", ["tiktok"])
        self._insert_scheduled_post("task-secret-check", "tiktok", now - timedelta(minutes=5))

        try:
            with patch("app.services.upload_post.cross_post_video", return_value={"success": True, "request_id": "req-sec"}):
                res = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tasks_base_dir)
                self.assertEqual(res["status"], "published")

            logs_text = log_capture.getvalue()
            secret = "super-secret-key-12345"
            self.assertNotIn(secret, logs_text)
        finally:
            logger.remove(handler_id)


if __name__ == "__main__":
    unittest.main()
