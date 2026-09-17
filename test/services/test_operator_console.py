import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.models import const
from app.models.schema import VideoParams
from app.services import operator_console, scheduler, task as task_module, webui_task, state as sm


class TestOperatorConsole(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_video_factory.db")
        self.tasks_dir = os.path.join(self.test_dir, "tasks")
        os.makedirs(self.tasks_dir, exist_ok=True)
        scheduler.init_db(self.db_path)
        operator_console.init_operator_db(self.db_path)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    # 1. factory default RUNNING
    def test_factory_default_running(self):
        st = operator_console.get_factory_state(db_path=self.db_path)
        self.assertEqual(st, operator_console.FACTORY_STATE_RUNNING)
        self.assertFalse(operator_console.is_factory_paused(db_path=self.db_path))

    # 2. pause persists
    def test_pause_persists(self):
        operator_console.pause_factory(db_path=self.db_path)
        st = operator_console.get_factory_state(db_path=self.db_path)
        self.assertEqual(st, operator_console.FACTORY_STATE_PAUSED)
        self.assertTrue(operator_console.is_factory_paused(db_path=self.db_path))

    # 3. resume persists
    def test_resume_persists(self):
        operator_console.pause_factory(db_path=self.db_path)
        operator_console.resume_factory(db_path=self.db_path)
        st = operator_console.get_factory_state(db_path=self.db_path)
        self.assertEqual(st, operator_console.FACTORY_STATE_RUNNING)
        self.assertFalse(operator_console.is_factory_paused(db_path=self.db_path))

    # 4. pause bloqueia próxima geração
    def test_pause_blocks_next_generation(self):
        operator_console.pause_factory(db_path=self.db_path)
        with patch("app.services.operator_console.is_factory_paused", return_value=True):
            params = VideoParams(video_subject="Tema Teste Pausa")
            with self.assertRaises(ValueError) as ctx:
                webui_task.submit_generation("task-paused-test", params)
            self.assertIn("Fábrica pausada", str(ctx.exception))

    # 5. pause bloqueia scheduler executor
    def test_pause_blocks_scheduler_executor(self):
        operator_console.pause_factory(db_path=self.db_path)
        # Habilita scheduler e auto publish
        scheduler.set_setting("scheduler_enabled", "true", db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", "true", db_path=self.db_path)
        
        cycle_res = scheduler.run_scheduler_cycle(db_path=self.db_path)
        self.assertEqual(cycle_res["status"], "skipped")
        self.assertEqual(cycle_res["reason"], "factory_paused")

    # 6. tarefa atual não é abortada imediatamente
    def test_current_task_not_abruptly_aborted(self):
        task_id = "task-running-pause"
        sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=50)
        operator_console.pause_factory(db_path=self.db_path)
        
        # A tarefa continua em PROCESSING e pode concluir
        t = sm.state.get_task(task_id)
        self.assertEqual(t["state"], const.TASK_STATE_PROCESSING)
        sm.state.update_task(task_id, state=const.TASK_STATE_COMPLETE, progress=100)
        t_done = sm.state.get_task(task_id)
        self.assertEqual(t_done["state"], const.TASK_STATE_COMPLETE)

    # 7. cancel pending
    def test_cancel_pending_task(self):
        task_id = "task-pending-cancel"
        sm.state.update_task(task_id, state=const.TASK_STATE_PENDING, progress=0)
        res = operator_console.request_task_cancel(task_id, db_path=self.db_path)
        self.assertTrue(res)
        
        t = sm.state.get_task(task_id)
        self.assertEqual(t["state"], const.TASK_STATE_CANCELLED)
        self.assertTrue(t.get("cancelled"))

    # 8. cancel_requested em processing
    def test_cancel_requested_in_processing_checkpoint(self):
        task_id = "task-proc-cancel"
        sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=10)
        operator_console.request_task_cancel(task_id, db_path=self.db_path)
        self.assertTrue(operator_console.is_cancel_requested(task_id))
        
        cancel_res = task_module._check_cancellation(task_id, "before_audio", progress=20)
        self.assertIsNotNone(cancel_res)
        self.assertEqual(cancel_res["state"], const.TASK_STATE_CANCELLED)
        
        t = sm.state.get_task(task_id)
        self.assertEqual(t["state"], const.TASK_STATE_CANCELLED)

    # 9. cancelled não vira failed
    def test_cancelled_does_not_become_failed(self):
        task_id = "task-no-failed"
        sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=10)
        operator_console.request_task_cancel(task_id, db_path=self.db_path)
        cancel_res = task_module._check_cancellation(task_id, "before_render", progress=50)
        
        t = sm.state.get_task(task_id)
        self.assertEqual(t["state"], const.TASK_STATE_CANCELLED)
        self.assertNotEqual(t["state"], const.TASK_STATE_FAILED)
        self.assertIsNone(t.get("error"))

    # 10. cancelled não entra Scheduler
    def test_cancelled_not_sent_to_scheduler(self):
        task_id = "task-sched-cancelled"
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_CANCELLED,
            cancelled=True,
            planned_platforms=["youtube"],
            video_file="/path/dummy.mp4",
        )
        tasks = [sm.state.get_task(task_id)]
        scheduled = scheduler.plan_schedule(tasks, db_path=self.db_path)
        self.assertEqual(len(scheduled), 0)

    # 11. ready stock count
    def test_ready_stock_count(self):
        task_id = "task-stock-test"
        task_folder = os.path.join(self.tasks_dir, task_id)
        os.makedirs(task_folder, exist_ok=True)
        video_path = os.path.join(task_folder, "final-1.mp4")
        with open(video_path, "wb") as f:
            f.write(b"video content")
            
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            safety_status="PASS",
            video_file=video_path,
        )
        stock = operator_console.get_ready_stock(task_base_dir=self.tasks_dir, db_path=self.db_path)
        self.assertEqual(stock["total_ready"], 1)
        self.assertEqual(stock["youtube_count"], 1)
        self.assertEqual(stock["tiktok_count"], 1)

    # 12. provider health degraded
    def test_provider_health_degraded(self):
        operator_console.log_operational_event(
            component="reddit",
            severity=operator_console.SEVERITY_WARNING,
            event_type="api_error",
            message="HTTP 403 Forbidden on r/popular",
            db_path=self.db_path,
        )
        health = operator_console.get_provider_health_summary(db_path=self.db_path)
        self.assertIn("Reddit", health)
        self.assertEqual(health["Reddit"]["status"], operator_console.PROVIDER_DEGRADED)

    # 13. provider failure não derruba factory inteira
    def test_provider_failure_does_not_break_entire_factory(self):
        operator_console.log_operational_event(
            component="reddit",
            severity=operator_console.SEVERITY_WARNING,
            event_type="api_error",
            message="Reddit unavailable",
            db_path=self.db_path,
        )
        status = operator_console.get_system_status(db_path=self.db_path)
        # Factory vira DEGRADED, não ERROR
        self.assertIn(status["factory_state"], ("DEGRADED", "RUNNING"))
        self.assertNotEqual(status["factory_state"], "ERROR")

    # 14. operational event persistido
    def test_operational_event_persisted(self):
        ev_id = operator_console.log_operational_event(
            component="scheduler",
            severity=operator_console.SEVERITY_ERROR,
            event_type="rate_limit",
            message="Rate limit atingido na plataforma TikTok",
            metadata={"platform": "tiktok", "limit": 15},
            db_path=self.db_path,
        )
        self.assertIsNotNone(ev_id)
        
        events = operator_console.get_operational_events(component="scheduler", db_path=self.db_path)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["severity"], "ERROR")
        self.assertEqual(events[0]["metadata"]["platform"], "tiktok")

    # 15. restart detecta PROCESSING órfão
    def test_restart_detects_orphaned_processing_task(self):
        task_id = "task-orphan-1"
        sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=35)
        
        with patch("app.services.webui_task.get_active_task_ids", return_value=[]):
            reconciled = operator_console.reconcile_orphaned_tasks(task_base_dir=self.tasks_dir, db_path=self.db_path)
            self.assertEqual(len(reconciled), 1)
            self.assertEqual(reconciled[0]["task_id"], task_id)
            self.assertEqual(reconciled[0]["action"], "failed_recoverable")

    # 16. orphan não fica processing eterno
    def test_orphan_does_not_stay_processing_forever(self):
        task_id = "task-orphan-2"
        sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=45)
        
        with patch("app.services.webui_task.get_active_task_ids", return_value=[]):
            operator_console.reconcile_orphaned_tasks(task_base_dir=self.tasks_dir, db_path=self.db_path)
            t = sm.state.get_task(task_id)
            self.assertNotEqual(t["state"], const.TASK_STATE_PROCESSING)
            self.assertEqual(t["state"], const.TASK_STATE_FAILED)
            self.assertEqual(t.get("failed_stage"), "interrupted_by_restart")

    # 17. reexecute recovery cria nova task controlada
    def test_reexecute_recovery_creates_controlled_task(self):
        task_id = "task-orphan-3"
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_FAILED,
            failed_stage="interrupted_by_restart",
            video_subject="Curiosidades do Oceano",
        )
        with patch("app.services.webui_task.submit_generation") as mock_submit:
            new_task_id = operator_console.reexecute_task(task_id, task_base_dir=self.tasks_dir)
            self.assertIsNotNone(new_task_id)
            self.assertNotEqual(new_task_id, task_id)
            self.assertTrue(mock_submit.called)

    # 18. emergency pause
    def test_emergency_pause(self):
        operator_console.emergency_pause(db_path=self.db_path)
        self.assertEqual(operator_console.get_factory_state(db_path=self.db_path), operator_console.FACTORY_STATE_PAUSED)
        self.assertTrue(operator_console.is_factory_paused(db_path=self.db_path))
        
        events = operator_console.get_operational_events(severity="CRITICAL", db_path=self.db_path)
        self.assertGreaterEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "emergency_pause")

    # 19. minimum stock warning
    def test_minimum_stock_warning(self):
        operator_console.set_minimum_ready_stock(5, db_path=self.db_path)
        self.assertEqual(operator_console.get_minimum_ready_stock(db_path=self.db_path), 5)
        
        stock = operator_console.get_ready_stock(task_base_dir=self.tasks_dir, db_path=self.db_path)
        # Com 0 vídeos prontos e mínimo 5, deve emitir alerta
        self.assertTrue(stock["is_below_minimum"])

    # 20. startup respeita PAUSED
    def test_startup_respects_paused_state(self):
        operator_console.pause_factory(db_path=self.db_path)
        # Simula inicialização do sistema lendo do SQLite
        loaded_state = operator_console.get_factory_state(db_path=self.db_path)
        self.assertEqual(loaded_state, operator_console.FACTORY_STATE_PAUSED)
        self.assertTrue(operator_console.is_factory_paused(db_path=self.db_path))

    # 21. scheduler idempotência continua intacta
    def test_scheduler_idempotency_remains_intact(self):
        task_id = "task-idempotent-v8"
        iso_future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at)
                VALUES (?, ?, ?, 'planned', ?);
                """,
                (task_id, "youtube", iso_future, iso_future),
            )
        
        # Tenta agendar novamente a mesma tarefa e plataforma
        tasks = [{
            "task_id": task_id,
            "state": const.TASK_STATE_COMPLETE,
            "planned_platforms": ["youtube"],
            "video_file": "/dummy.mp4",
        }]
        scheduled = scheduler.plan_schedule(tasks, db_path=self.db_path)
        # Não deve duplicar o agendamento
        self.assertEqual(len(scheduled), 0)


if __name__ == "__main__":
    unittest.main()
