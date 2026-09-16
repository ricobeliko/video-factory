import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.config import config
from app.models import const
from app.services import scheduler


class TestScheduler(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_video_factory.db")

    def tearDown(self):
        import gc
        gc.collect()
        self.temp_dir.cleanup()

    def test_01_sqlite_schema_created_automatically(self):
        self.assertFalse(os.path.exists(self.db_path))
        scheduler.init_db(self.db_path)
        self.assertTrue(os.path.exists(self.db_path))

        with scheduler.get_connection(self.db_path) as conn:
            tables = [
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table';"
                ).fetchall()
            ]
            self.assertIn("scheduled_posts", tables)
            self.assertIn("publication_events", tables)
            self.assertIn("autopilot_settings", tables)
            self.assertIn("task_platforms", tables)

    def test_02_settings_persist_after_reopening_db(self):
        scheduler.init_db(self.db_path)
        scheduler.set_setting("tiktok_limit_24h", 12, db_path=self.db_path)
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)

        # Fecha e reabre conexão em outra chamada
        settings = scheduler.get_all_settings(db_path=self.db_path)
        self.assertEqual(settings["tiktok_limit_24h"], 12)
        self.assertTrue(settings["scheduler_enabled"])

    def test_03_scheduled_post_persists_after_reopening_db(self):
        scheduler.init_db(self.db_path)
        now = datetime.now(timezone.utc)
        fake_task = {
            "task_id": "task-persist-1",
            "state": const.TASK_STATE_COMPLETE,
            "planned_platforms": ["tiktok"],
            "subject": "Tema Persistente",
        }
        res = scheduler.plan_schedule([fake_task], now=now, db_path=self.db_path)
        self.assertEqual(len(res), 1)

        # Nova leitura independente
        upcoming = scheduler.get_upcoming_posts(db_path=self.db_path)
        self.assertEqual(len(upcoming), 1)
        self.assertEqual(upcoming[0]["task_id"], "task-persist-1")
        self.assertEqual(upcoming[0]["platform"], "tiktok")
        self.assertEqual(upcoming[0]["status"], "planned")

    def test_04_task_id_and_platform_does_not_duplicate_schedule(self):
        scheduler.init_db(self.db_path)
        now = datetime.now(timezone.utc)
        fake_task = {
            "task_id": "task-dup-1",
            "state": const.TASK_STATE_COMPLETE,
            "planned_platforms": ["tiktok"],
            "subject": "Tema Teste",
        }
        res1 = scheduler.plan_schedule([fake_task], now=now, db_path=self.db_path)
        self.assertEqual(len(res1), 1)

        # Chamada subsequente idêntica (ex.: clique repetido ou rerun do Streamlit)
        res2 = scheduler.plan_schedule([fake_task], now=now, db_path=self.db_path)
        self.assertEqual(len(res2), 0)

        upcoming = scheduler.get_upcoming_posts(db_path=self.db_path)
        self.assertEqual(len(upcoming), 1)

    def test_05_tiktok_respects_15_per_24h_limit(self):
        scheduler.init_db(self.db_path)
        scheduler.set_setting("tiktok_limit_24h", 15, db_path=self.db_path)
        now = datetime.now(timezone.utc)

        # Tenta agendar 25 tarefas
        tasks = [
            {
                "task_id": f"task-tk-{i}",
                "state": const.TASK_STATE_COMPLETE,
                "planned_platforms": ["tiktok"],
                "subject": f"Tema {i}",
            }
            for i in range(25)
        ]
        created = scheduler.plan_schedule(tasks, now=now, db_path=self.db_path)
        self.assertEqual(len(created), 15)

        rate = scheduler.get_platform_rate_limits("tiktok", db_path=self.db_path, now=now)
        self.assertEqual(rate["limit"], 15)
        self.assertEqual(rate["scheduled_24h"], 15)
        self.assertEqual(rate["available_slots"], 0)

    def test_06_youtube_respects_10_per_24h_limit(self):
        scheduler.init_db(self.db_path)
        scheduler.set_setting("youtube_limit_24h", 10, db_path=self.db_path)
        now = datetime.now(timezone.utc)

        tasks = [
            {
                "task_id": f"task-yt-{i}",
                "state": const.TASK_STATE_COMPLETE,
                "planned_platforms": ["youtube"],
                "subject": f"Tema YT {i}",
            }
            for i in range(15)
        ]
        created = scheduler.plan_schedule(tasks, now=now, db_path=self.db_path)
        self.assertEqual(len(created), 10)

        rate = scheduler.get_platform_rate_limits("youtube", db_path=self.db_path, now=now)
        self.assertEqual(rate["limit"], 10)
        self.assertEqual(rate["scheduled_24h"], 10)
        self.assertEqual(rate["available_slots"], 0)

    def test_07_publications_in_last_24h_reduce_available_slots(self):
        scheduler.init_db(self.db_path)
        scheduler.set_setting("tiktok_limit_24h", 15, db_path=self.db_path)
        now = datetime.now(timezone.utc)

        # Registra 11 publicações ocorridas 5 horas atrás
        pub_time = now - timedelta(hours=5)
        for i in range(11):
            scheduler.record_publication_event(
                task_id=f"past-tk-{i}",
                platform="tiktok",
                status="success",
                published_at=pub_time,
                db_path=self.db_path,
            )

        rate = scheduler.get_platform_rate_limits("tiktok", db_path=self.db_path, now=now)
        self.assertEqual(rate["used_past_24h"], 11)
        self.assertEqual(rate["available_slots"], 4)

        # Planeja para 10 vídeos
        tasks = [
            {
                "task_id": f"new-tk-{i}",
                "state": const.TASK_STATE_COMPLETE,
                "planned_platforms": ["tiktok"],
                "subject": f"Novo {i}",
            }
            for i in range(10)
        ]
        created = scheduler.plan_schedule(tasks, now=now, db_path=self.db_path)
        self.assertEqual(len(created), 4)

    def test_08_publication_older_than_24h_does_not_count(self):
        scheduler.init_db(self.db_path)
        scheduler.set_setting("tiktok_limit_24h", 15, db_path=self.db_path)
        now = datetime.now(timezone.utc)

        # Publicação de 26 horas atrás
        old_pub_time = now - timedelta(hours=26)
        for i in range(10):
            scheduler.record_publication_event(
                task_id=f"old-tk-{i}",
                platform="tiktok",
                status="success",
                published_at=old_pub_time,
                db_path=self.db_path,
            )

        rate = scheduler.get_platform_rate_limits("tiktok", db_path=self.db_path, now=now)
        # Como foi > 24h, não deve consumir slots da janela móvel
        self.assertEqual(rate["used_past_24h"], 0)
        self.assertEqual(rate["available_slots"], 15)

    def test_09_schedule_distributes_times_evenly_across_the_day(self):
        scheduler.init_db(self.db_path)
        scheduler.set_setting("tiktok_limit_24h", 15, db_path=self.db_path)
        now = datetime.now(timezone.utc)

        tasks = [
            {
                "task_id": f"task-time-{i}",
                "state": const.TASK_STATE_COMPLETE,
                "planned_platforms": ["tiktok"],
                "subject": f"Tema {i}",
            }
            for i in range(3)
        ]
        created = scheduler.plan_schedule(tasks, now=now, db_path=self.db_path)
        self.assertEqual(len(created), 3)

        dt0 = datetime.fromisoformat(created[0]["scheduled_at"])
        dt1 = datetime.fromisoformat(created[1]["scheduled_at"])
        dt2 = datetime.fromisoformat(created[2]["scheduled_at"])

        diff1 = (dt1 - dt0).total_seconds()
        diff2 = (dt2 - dt1).total_seconds()

        # 86400 / 15 = 5760 segundos (96 minutos)
        self.assertEqual(diff1, 5760)
        self.assertEqual(diff2, 5760)

    def test_10_task_processing_is_not_scheduled(self):
        scheduler.init_db(self.db_path)
        now = datetime.now(timezone.utc)
        task = {
            "task_id": "task-proc",
            "state": const.TASK_STATE_PROCESSING,
            "planned_platforms": ["tiktok"],
        }
        created = scheduler.plan_schedule([task], now=now, db_path=self.db_path)
        self.assertEqual(len(created), 0)

    def test_11_task_pending_is_not_scheduled(self):
        scheduler.init_db(self.db_path)
        now = datetime.now(timezone.utc)
        task = {
            "task_id": "task-pend",
            "state": const.TASK_STATE_PENDING,
            "planned_platforms": ["tiktok"],
        }
        created = scheduler.plan_schedule([task], now=now, db_path=self.db_path)
        self.assertEqual(len(created), 0)

    def test_12_task_failed_is_not_scheduled(self):
        scheduler.init_db(self.db_path)
        now = datetime.now(timezone.utc)
        task = {
            "task_id": "task-fail",
            "state": const.TASK_STATE_FAILED,
            "planned_platforms": ["tiktok"],
        }
        created = scheduler.plan_schedule([task], now=now, db_path=self.db_path)
        self.assertEqual(len(created), 0)

    def test_13_task_complete_can_be_scheduled(self):
        scheduler.init_db(self.db_path)
        now = datetime.now(timezone.utc)
        task = {
            "task_id": "task-complete-ok",
            "state": const.TASK_STATE_COMPLETE,
            "planned_platforms": ["tiktok"],
        }
        created = scheduler.plan_schedule([task], now=now, db_path=self.db_path)
        self.assertEqual(len(created), 1)

    def test_14_already_published_task_is_not_scheduled(self):
        scheduler.init_db(self.db_path)
        now = datetime.now(timezone.utc)
        task = {
            "task_id": "task-already-pub",
            "state": const.TASK_STATE_COMPLETE,
            "cross_post_state": const.CROSS_POST_STATE_COMPLETE,
            "planned_platforms": ["tiktok"],
        }
        created = scheduler.plan_schedule([task], now=now, db_path=self.db_path)
        self.assertEqual(len(created), 0)

    def test_15_clear_schedule_removes_only_planned_and_ready(self):
        scheduler.init_db(self.db_path)
        now = datetime.now(timezone.utc)
        tasks = [
            {"task_id": f"t-clear-{i}", "state": const.TASK_STATE_COMPLETE, "planned_platforms": ["tiktok"]}
            for i in range(3)
        ]
        scheduler.plan_schedule(tasks, now=now, db_path=self.db_path)
        self.assertEqual(len(scheduler.get_upcoming_posts(db_path=self.db_path)), 3)

        deleted = scheduler.clear_future_schedule(db_path=self.db_path)
        self.assertEqual(deleted, 3)
        self.assertEqual(len(scheduler.get_upcoming_posts(db_path=self.db_path)), 0)

    def test_16_published_items_are_not_deleted_by_clear_schedule(self):
        scheduler.init_db(self.db_path)
        now = datetime.now(timezone.utc)
        scheduler.plan_schedule(
            [{"task_id": "t-keep-pub", "state": const.TASK_STATE_COMPLETE, "planned_platforms": ["tiktok"]}],
            now=now,
            db_path=self.db_path,
        )
        # Marca como published
        scheduler.record_publication_event("t-keep-pub", "tiktok", "success", now, db_path=self.db_path)

        # Agenda outra como planned
        scheduler.plan_schedule(
            [{"task_id": "t-planned-del", "state": const.TASK_STATE_COMPLETE, "planned_platforms": ["tiktok"]}],
            now=now,
            db_path=self.db_path,
        )

        deleted = scheduler.clear_future_schedule(db_path=self.db_path)
        self.assertEqual(deleted, 1)

        # O item publicado continua no banco
        with scheduler.get_connection(self.db_path) as conn:
            pub_row = conn.execute(
                "SELECT status FROM scheduled_posts WHERE task_id = 't-keep-pub';"
            ).fetchone()
            self.assertIsNotNone(pub_row)
            self.assertEqual(pub_row["status"], "published")

    def test_17_no_call_to_upload_post_occurs_during_scheduling(self):
        scheduler.init_db(self.db_path)
        now = datetime.now(timezone.utc)
        task = {
            "task_id": "task-no-upload",
            "state": const.TASK_STATE_COMPLETE,
            "planned_platforms": ["tiktok", "youtube"],
        }
        with patch("app.services.task.publish_task") as mock_pub, \
             patch("app.services.task._run_cross_post") as mock_cross:
            scheduler.plan_schedule([task], now=now, db_path=self.db_path)
            scheduler.clear_future_schedule(db_path=self.db_path)
            mock_pub.assert_not_called()
            mock_cross.assert_not_called()

    def test_18_upload_post_auto_upload_remains_unmodified(self):
        initial_val = config.app.get("upload_post_auto_upload", False)
        scheduler.init_db(self.db_path)
        scheduler.plan_schedule([], db_path=self.db_path)
        scheduler.get_platform_rate_limits("tiktok", db_path=self.db_path)
        current_val = config.app.get("upload_post_auto_upload", False)
        self.assertEqual(initial_val, current_val)

    def test_19_restarting_application_preserves_schedule_and_settings(self):
        # 1. Cria dados na "primeira execução"
        scheduler.init_db(self.db_path)
        scheduler.set_setting("tiktok_limit_24h", 14, db_path=self.db_path)
        scheduler.save_task_platforms("restart-task", ["tiktok", "youtube"], db_path=self.db_path)

        now = datetime.now(timezone.utc)
        scheduler.plan_schedule(
            [{"task_id": "restart-task", "state": const.TASK_STATE_COMPLETE}],
            now=now,
            db_path=self.db_path,
        )

        # 2. Simula encerramento da aplicação (nenhuma variável em memória)
        # Abre nova conexão apontando para o mesmo arquivo em disco
        reopened_settings = scheduler.get_all_settings(db_path=self.db_path)
        self.assertEqual(reopened_settings["tiktok_limit_24h"], 14)

        reopened_platforms = scheduler.get_task_platforms("restart-task", db_path=self.db_path)
        self.assertEqual(set(reopened_platforms), {"tiktok", "youtube"})

        reopened_posts = scheduler.get_upcoming_posts(db_path=self.db_path)
        self.assertEqual(len(reopened_posts), 2)
        self.assertEqual({p["platform"] for p in reopened_posts}, {"tiktok", "youtube"})

    def test_20_compatibility_with_tasks_without_planned_platforms(self):
        scheduler.init_db(self.db_path)
        now = datetime.now(timezone.utc)
        # Tarefa antiga sem planned_platforms nem registro no SQLite
        legacy_task = {
            "task_id": "legacy-task-123",
            "state": const.TASK_STATE_COMPLETE,
            "subject": "Vídeo Antigo",
        }
        # Não deve falhar nem agendar nada
        res = scheduler.plan_schedule([legacy_task], now=now, db_path=self.db_path)
    def _create_dummy_video(self, task_id: str) -> str:
        v_path = os.path.join(self.temp_dir.name, f"{task_id}.mp4")
        with open(v_path, "wb") as f:
            f.write(b"dummy video content")
        return v_path

    def test_21_complete_video_without_platforms_appears_for_adoption(self):
        v_path = self._create_dummy_video("adopt-task-1")
        task = {
            "task_id": "adopt-task-1",
            "state": const.TASK_STATE_COMPLETE,
            "video_file": v_path,
            "subject": "Vídeo para Adoção",
        }
        adoptable = scheduler.get_adoptable_tasks([task], db_path=self.db_path)
        self.assertEqual(len(adoptable), 1)
        self.assertEqual(adoptable[0]["task_id"], "adopt-task-1")

    def test_22_complete_with_nonexistent_video_does_not_appear(self):
        task = {
            "task_id": "adopt-task-nonexistent",
            "state": const.TASK_STATE_COMPLETE,
            "video_file": os.path.join(self.temp_dir.name, "does_not_exist.mp4"),
            "subject": "Vídeo Inexistente",
        }
        adoptable = scheduler.get_adoptable_tasks([task], db_path=self.db_path)
        self.assertEqual(len(adoptable), 0)

    def test_23_processing_task_does_not_appear(self):
        v_path = self._create_dummy_video("adopt-task-proc")
        task = {
            "task_id": "adopt-task-proc",
            "state": const.TASK_STATE_PROCESSING,
            "video_file": v_path,
        }
        adoptable = scheduler.get_adoptable_tasks([task], db_path=self.db_path)
        self.assertEqual(len(adoptable), 0)

    def test_24_failed_task_does_not_appear(self):
        v_path = self._create_dummy_video("adopt-task-fail")
        task = {
            "task_id": "adopt-task-fail",
            "state": const.TASK_STATE_FAILED,
            "video_file": v_path,
        }
        adoptable = scheduler.get_adoptable_tasks([task], db_path=self.db_path)
        self.assertEqual(len(adoptable), 0)

    def test_25_published_task_does_not_appear(self):
        v_path1 = self._create_dummy_video("adopt-task-pub1")
        task1 = {
            "task_id": "adopt-task-pub1",
            "state": const.TASK_STATE_COMPLETE,
            "video_file": v_path1,
            "cross_post_state": const.CROSS_POST_STATE_COMPLETE,
        }
        v_path2 = self._create_dummy_video("adopt-task-pub2")
        task2 = {
            "task_id": "adopt-task-pub2",
            "state": const.TASK_STATE_COMPLETE,
            "video_file": v_path2,
        }
        scheduler.record_publication_event("adopt-task-pub2", "tiktok", "success", db_path=self.db_path)

        adoptable = scheduler.get_adoptable_tasks([task1, task2], db_path=self.db_path)
        self.assertEqual(len(adoptable), 0)

    def test_26_adopt_tiktok_only(self):
        v_path = self._create_dummy_video("adopt-tk")
        count = scheduler.adopt_tasks_into_scheduler(["adopt-tk"], ["tiktok"], db_path=self.db_path)
        self.assertEqual(count, 1)

        platforms = scheduler.get_task_platforms("adopt-tk", db_path=self.db_path)
        self.assertEqual(platforms, ["tiktok"])

    def test_27_adopt_youtube_only(self):
        v_path = self._create_dummy_video("adopt-yt")
        count = scheduler.adopt_tasks_into_scheduler(["adopt-yt"], ["youtube"], db_path=self.db_path)
        self.assertEqual(count, 1)

        platforms = scheduler.get_task_platforms("adopt-yt", db_path=self.db_path)
        self.assertEqual(platforms, ["youtube"])

    def test_28_adopt_tiktok_and_youtube(self):
        v_path = self._create_dummy_video("adopt-both")
        count = scheduler.adopt_tasks_into_scheduler(["adopt-both"], ["tiktok", "youtube"], db_path=self.db_path)
        self.assertEqual(count, 1)

        platforms = scheduler.get_task_platforms("adopt-both", db_path=self.db_path)
        self.assertEqual(set(platforms), {"tiktok", "youtube"})

    def test_29_repeated_adoption_does_not_duplicate(self):
        v_path = self._create_dummy_video("adopt-dup")
        scheduler.adopt_tasks_into_scheduler(["adopt-dup"], ["tiktok", "youtube"], db_path=self.db_path)
        # Segunda chamada repetida
        scheduler.adopt_tasks_into_scheduler(["adopt-dup"], ["tiktok", "youtube"], db_path=self.db_path)

        platforms = scheduler.get_task_platforms("adopt-dup", db_path=self.db_path)
        self.assertEqual(len(platforms), 2)
        self.assertEqual(set(platforms), {"tiktok", "youtube"})

    def test_30_adopted_video_becomes_eligible_for_plan_schedule(self):
        v_path = self._create_dummy_video("adopt-eligible")
        task = {
            "task_id": "adopt-eligible",
            "state": const.TASK_STATE_COMPLETE,
            "video_file": v_path,
            "subject": "Vídeo Elegível Após Adoção",
        }
        # Antes da adoção: adoptable retorna 1, plan_schedule retorna 0
        self.assertEqual(len(scheduler.get_adoptable_tasks([task], db_path=self.db_path)), 1)
        self.assertEqual(len(scheduler.plan_schedule([task], db_path=self.db_path)), 0)

        # Adota no scheduler
        scheduler.adopt_tasks_into_scheduler(["adopt-eligible"], ["tiktok", "youtube"], db_path=self.db_path)

        # Após adoção: não é mais retornado em get_adoptable_tasks
        self.assertEqual(len(scheduler.get_adoptable_tasks([task], db_path=self.db_path)), 0)

        # E agora é elegível para plan_schedule
        scheduled = scheduler.plan_schedule([task], db_path=self.db_path)
        self.assertEqual(len(scheduled), 2)
        self.assertEqual({s["platform"] for s in scheduled}, {"tiktok", "youtube"})

    def test_31_no_upload_post_during_adoption(self):
        with patch("app.services.task.publish_task") as mock_pub, \
             patch("app.services.task._run_cross_post") as mock_cross, \
             patch("app.services.upload_post.UploadPostService.upload_video") as mock_upload:
            scheduler.adopt_tasks_into_scheduler(["adopt-no-pub"], ["tiktok", "youtube"], db_path=self.db_path)
            mock_pub.assert_not_called()
            mock_cross.assert_not_called()
            mock_upload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
