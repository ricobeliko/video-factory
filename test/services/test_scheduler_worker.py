import os
import shutil
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.models import const
from app.services import scheduler


class TestSchedulerWorker(unittest.TestCase):
    """Testes para validação do ciclo de vida, persistência e execução do worker daemon do Scheduler."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_worker.db")
        scheduler.init_db(self.db_path)
        scheduler.stop_scheduler_worker()
        scheduler.reset_executor_status(self.db_path)
        self.now = datetime(2026, 9, 16, 21, 0, 0, tzinfo=timezone.utc)

    def tearDown(self):
        scheduler.stop_scheduler_worker()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_task_structure(self, task_id: str) -> str:
        t_dir = os.path.join(self.test_dir, task_id)
        os.makedirs(t_dir, exist_ok=True)
        v_path = os.path.join(t_dir, "final-1.mp4")
        with open(v_path, "wb") as f:
            f.write(b"mp4_content")
        return v_path

    def _insert_post(self, task_id: str, platform: str, scheduled_at_iso: str, status: str = "planned", next_attempt: str = None) -> int:
        with scheduler.get_connection(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at, next_attempt_at)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (task_id, platform, scheduled_at_iso, status, scheduled_at_iso, next_attempt),
            )
            return cur.lastrowid

    # 1. start_scheduler_worker cria worker vivo
    def test_01_start_scheduler_worker_creates_alive_worker(self):
        scheduler.start_scheduler_worker(interval_seconds=1)
        self.assertIsNotNone(scheduler._worker_thread)
        self.assertTrue(scheduler._worker_thread.is_alive())
        status = scheduler.get_executor_status()
        self.assertTrue(status["worker_active"])

    # 2. chamar start duas vezes não cria dois workers
    def test_02_calling_start_twice_maintains_singleton(self):
        scheduler.start_scheduler_worker(interval_seconds=2)
        th1 = scheduler._worker_thread
        scheduler.start_scheduler_worker(interval_seconds=2)
        th2 = scheduler._worker_thread
        self.assertEqual(th1, th2)

    # 3. worker chama run_scheduler_cycle periodicamente e grava heartbeat
    def test_03_worker_updates_heartbeat_tick_periodically(self):
        with patch.object(scheduler, "run_scheduler_cycle") as mock_cycle:
            scheduler.start_scheduler_worker(interval_seconds=1)
            time.sleep(1.5)
            self.assertGreaterEqual(mock_cycle.call_count, 1)
            status = scheduler.get_executor_status()
            self.assertTrue(status["worker_active"])
            self.assertIsNotNone(status["last_tick"])

    # 4. worker continua vivo após ciclo sem posts
    def test_04_worker_remains_alive_after_empty_cycle(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.start_scheduler_worker(interval_seconds=1)
        time.sleep(1.2)
        self.assertTrue(scheduler._worker_thread.is_alive())
        status = scheduler.get_executor_status()
        self.assertTrue(status["worker_active"])

    # 5. worker não depende de session_state
    def test_05_worker_does_not_depend_on_streamlit_session_state(self):
        # Executando loop e ciclo sem streamlit
        res = scheduler.run_scheduler_cycle(now=self.now, db_path=self.db_path)
        self.assertIn("status", res)

    # 6. run_scheduler_cycle detecta post vencido real
    def test_06_run_scheduler_cycle_detects_real_due_post(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)

        self._create_task_structure("task_due_now")
        scheduler.save_task_platforms("task_due_now", ["tiktok"], db_path=self.db_path)
        due_time = self.now - timedelta(minutes=1)
        self._insert_post("task_due_now", "tiktok", scheduler._to_iso(due_time))

        with patch("app.services.task.publish_task", return_value=(True, None)):
            res = scheduler.run_scheduler_cycle(now=self.now, db_path=self.db_path, task_base_dir=self.test_dir)
            self.assertEqual(res["status"], "published")
            self.assertEqual(res["task_id"], "task_due_now")

    # 7. run_scheduler_cycle em Dry Run processa o post e avança scheduled_at e next_attempt_at
    def test_07_run_scheduler_cycle_in_dry_run_processes_and_reschedules(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", True, db_path=self.db_path)

        self._create_task_structure("task_dry_cycle")
        scheduler.save_task_platforms("task_dry_cycle", ["youtube"], db_path=self.db_path)
        due_time = self.now - timedelta(minutes=2)
        post_id = self._insert_post("task_dry_cycle", "youtube", scheduler._to_iso(due_time))

        res = scheduler.run_scheduler_cycle(now=self.now, db_path=self.db_path, task_base_dir=self.test_dir)
        self.assertEqual(res["status"], "simulated")
        self.assertTrue(res["dry_run"])

        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT scheduled_at, next_attempt_at, status FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
            expected_next = scheduler._to_iso(self.now + timedelta(minutes=30))
            # Ambos devem ser avançados para liberar o topo da lista
            self.assertEqual(row["scheduled_at"], expected_next)
            self.assertEqual(row["next_attempt_at"], expected_next)
            self.assertEqual(row["status"], "planned")

    # 8. botão/manual cycle usa a mesma função e atualiza status persistente
    def test_08_manual_cycle_uses_same_function(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", True, db_path=self.db_path)

        res = scheduler.run_scheduler_cycle(now=self.now, db_path=self.db_path)
        self.assertEqual(res["status"], "idle")
        status = scheduler.get_executor_status(db_path=self.db_path)
        self.assertEqual(status["last_cycle_summary"], "Nenhum post vencido")

    # 9. scheduler OFF não executa
    def test_09_scheduler_off_does_not_execute(self):
        scheduler.set_setting("scheduler_enabled", False, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        res = scheduler.run_scheduler_cycle(now=self.now, db_path=self.db_path)
        self.assertEqual(res["status"], "skipped")
        self.assertEqual(res["reason"], "scheduler_disabled")

    # 10. auto publish OFF não executa
    def test_10_auto_publish_off_does_not_execute(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", False, db_path=self.db_path)
        res = scheduler.run_scheduler_cycle(now=self.now, db_path=self.db_path)
        self.assertEqual(res["status"], "skipped")
        self.assertEqual(res["reason"], "auto_publish_disabled")

    # 11. due post com next_attempt_at futuro é ignorado corretamente
    def test_11_due_post_with_future_next_attempt_is_ignored(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)

        due_time = self.now - timedelta(minutes=5)
        future_next = self.now + timedelta(minutes=25)
        self._insert_post("task_blocked", "tiktok", scheduler._to_iso(due_time), next_attempt=scheduler._to_iso(future_next))

        res = scheduler.run_scheduler_cycle(now=self.now, db_path=self.db_path)
        self.assertEqual(res["status"], "idle")

    # 12. due post sem bloqueios executa
    def test_12_due_post_without_blocks_executes(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)

        self._create_task_structure("task_clear")
        scheduler.save_task_platforms("task_clear", ["tiktok"], db_path=self.db_path)
        due_time = self.now - timedelta(seconds=10)
        self._insert_post("task_clear", "tiktok", scheduler._to_iso(due_time), next_attempt=None)

        with patch("app.services.task.publish_task", return_value=(True, None)):
            res = scheduler.run_scheduler_cycle(now=self.now, db_path=self.db_path, task_base_dir=self.test_dir)
            self.assertEqual(res["status"], "published")

    # 13. worker e UI usam o mesmo db_path e compartilham status persistente
    def test_13_worker_and_ui_use_same_db_path(self):
        scheduler.set_setting("executor_last_result", "Sucesso Teste Persistente", db_path=self.db_path)
        scheduler.set_setting("executor_last_tick", scheduler._to_iso(self.now), db_path=self.db_path)

        ui_status = scheduler.get_executor_status(db_path=self.db_path)
        self.assertEqual(ui_status["last_result"], "Sucesso Teste Persistente")
        self.assertIsNotNone(ui_status["last_tick"])

    # 14. Teste de integração SQLite real com conexões separadas
    def test_14_dry_run_sqlite_persistence_new_connection(self):
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", True, db_path=self.db_path)

        scheduler.save_task_platforms("task_dry_persist", ["youtube"], db_path=self.db_path)
        self._create_task_structure("task_dry_persist")
        due_time = self.now - timedelta(minutes=5)
        post_id = self._insert_post("task_dry_persist", "youtube", scheduler._to_iso(due_time), next_attempt=None)

        # Executa o ciclo de simulação
        res = scheduler.run_scheduler_cycle(now=self.now, db_path=self.db_path, task_base_dir=self.test_dir)
        self.assertEqual(res["status"], "simulated")

        # Abre NOVA conexão SQLite isolada para verificar commit físico no disco
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT scheduled_at, next_attempt_at, status FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
        conn.close()

        expected_time = self.now + timedelta(minutes=30)
        expected_iso = scheduler._to_iso(expected_time)

        self.assertEqual(row["scheduled_at"], expected_iso)
        self.assertEqual(row["next_attempt_at"], expected_iso)

        # Verifica que get_upcoming_posts retorna o novo horário
        upcoming = scheduler.get_upcoming_posts(db_path=self.db_path)
        self.assertEqual(len(upcoming), 1)
        self.assertEqual(upcoming[0]["scheduled_at"], expected_iso)

    # 15. Garantir apenas 1 registro ativo por (task_id, platform)
    def test_15_single_active_record_per_task_id_platform(self):
        due_time = self.now - timedelta(minutes=10)
        post_id = self._insert_post("task_single", "youtube", scheduler._to_iso(due_time), status="planned")

        # Reagenda para teste
        res = scheduler.reschedule_post_for_test(post_id, 5, now=self.now, db_path=self.db_path)
        self.assertTrue(res["success"])

        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, task_id, platform, status FROM scheduled_posts WHERE task_id = 'task_single' AND platform = 'youtube' AND status IN ('planned', 'ready');"
        ).fetchall()
        conn.close()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], post_id)


if __name__ == "__main__":
    unittest.main()

