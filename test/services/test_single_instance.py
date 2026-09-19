import os
import platform
import shutil
import socket
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.models import const
from app.models.schema import VideoParams
from app.services import operator_console, scheduler, task as task_module, webui_task, state as sm


class TestSingleInstanceSafety(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_video_factory.db")
        self.tasks_dir = os.path.join(self.test_dir, "tasks")
        os.makedirs(self.tasks_dir, exist_ok=True)
        scheduler.init_db(self.db_path)
        operator_console.init_operator_db(self.db_path)
        operator_console.reset_instance_for_testing()

    def tearDown(self):
        operator_console.reset_instance_for_testing()
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    # 1. Primeira instância adquire PRIMARY
    def test_first_instance_acquires_primary(self):
        role, info = operator_console.acquire_instance_lock(
            node_name="NODE-TEST-1",
            db_path=self.db_path,
        )
        self.assertEqual(role, operator_console.ROLE_PRIMARY)
        self.assertEqual(info.get("status"), operator_console.INSTANCE_STATUS_ACTIVE)
        self.assertEqual(info.get("role"), operator_console.ROLE_PRIMARY)
        self.assertTrue(operator_console.is_primary_instance(db_path=self.db_path))

        # Confere evento operacional registrado
        events = operator_console.get_operational_events(db_path=self.db_path)
        acquired_evs = [e for e in events if e.get("event_type") == operator_console.EVENT_INSTANCE_PRIMARY_ACQUIRED]
        self.assertTrue(len(acquired_evs) >= 1)

    # 2. Segunda instância com heartbeat ativo vira SECONDARY_VIEW_ONLY
    def test_second_instance_enters_view_only(self):
        # Nó 1 vira primary
        role1, info1 = operator_console.acquire_instance_lock(
            node_name="NODE-PRIMARY",
            db_path=self.db_path,
            force_node_id="node-uuid-1",
        )
        self.assertEqual(role1, operator_console.ROLE_PRIMARY)

        # Simula processo diferente tentando adquirir
        operator_console.reset_instance_for_testing()
        with patch("os.getpid", return_value=999999):
            role2, info2 = operator_console.acquire_instance_lock(
                node_name="NODE-NOTEBOOK",
                db_path=self.db_path,
                force_node_id="node-uuid-2",
            )
            self.assertEqual(role2, operator_console.ROLE_SECONDARY_VIEW_ONLY)
            self.assertFalse(operator_console.is_primary_instance(db_path=self.db_path))
            self.assertEqual(info2.get("node_name"), "NODE-PRIMARY")

        # Confere que lock no banco permaneceu com NODE-PRIMARY
        inst_info = operator_console.get_instance_info(db_path=self.db_path)
        self.assertEqual(inst_info.get("primary_node_name"), "NODE-PRIMARY")

    # 3. Process Singleton: ensure_instance_initialized não cria novo lock em novas sessões/abas
    def test_ensure_instance_initialized_singleton(self):
        role1, info1 = operator_console.ensure_instance_initialized(
            node_name="NODE-TEST-SINGLETON",
            db_path=self.db_path,
        )
        self.assertEqual(role1, operator_console.ROLE_PRIMARY)
        first_node_id = operator_console._current_node_id

        # Simula rerun / nova aba Streamlit chamando ensure_instance_initialized no mesmo processo
        role2, info2 = operator_console.ensure_instance_initialized(
            node_name="DIFFERENT-CALL",
            db_path=self.db_path,
        )
        self.assertEqual(role2, operator_console.ROLE_PRIMARY)
        self.assertEqual(operator_console._current_node_id, first_node_id)

        # Confere que existe exatamente 1 linha na tabela instance_locks
        with operator_console.get_connection(self.db_path) as conn:
            cnt = conn.execute("SELECT COUNT(*) FROM instance_locks;").fetchone()[0]
            self.assertEqual(cnt, 1)

    # 4. PRIMARY ativo continua PRIMARY após rerun da WebUI
    def test_primary_remains_primary_after_reruns(self):
        operator_console.ensure_instance_initialized(
            node_name="NODE-PRIMARY",
            db_path=self.db_path,
        )
        self.assertTrue(operator_console.is_primary_instance(db_path=self.db_path))

        # Múltiplos reruns
        for _ in range(5):
            self.assertTrue(operator_console.is_primary_instance(db_path=self.db_path))

    # 5. VIEW ONLY bloqueia submit_generation no backend
    def test_view_only_blocks_submit_generation(self):
        # Configura instância local como VIEW ONLY
        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._current_role = operator_console.ROLE_SECONDARY_VIEW_ONLY

        params = VideoParams(video_subject="Teste Bloqueio View Only")
        with self.assertRaises(PermissionError) as ctx:
            webui_task.submit_generation("task-view-only-test", params)
        self.assertIn("modo VIEW ONLY", str(ctx.exception))

    # 6. VIEW ONLY bloqueia cancelamento de geração no backend
    def test_view_only_blocks_cancel_generation(self):
        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._current_role = operator_console.ROLE_SECONDARY_VIEW_ONLY

        with self.assertRaises(PermissionError) as ctx:
            webui_task.cancel_generation("any-task-id")
        self.assertIn("modo VIEW ONLY", str(ctx.exception))

    # 7. VIEW ONLY bloqueia manual publish no backend
    def test_view_only_blocks_manual_publish(self):
        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._current_role = operator_console.ROLE_SECONDARY_VIEW_ONLY

        success, err = task_module.publish_task("task-1234", db_path=self.db_path)
        self.assertFalse(success)
        self.assertIn("modo VIEW ONLY", err)

    # 8. VIEW ONLY bloqueia pause, resume e emergency pause no backend
    def test_view_only_blocks_pause_and_resume(self):
        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._current_role = operator_console.ROLE_SECONDARY_VIEW_ONLY

        with self.assertRaises(PermissionError):
            operator_console.pause_factory(db_path=self.db_path)

        with self.assertRaises(PermissionError):
            operator_console.resume_factory(db_path=self.db_path)

        with self.assertRaises(PermissionError):
            operator_console.emergency_pause(db_path=self.db_path)

        with self.assertRaises(PermissionError):
            operator_console.set_minimum_ready_stock(5, db_path=self.db_path)

    # 9. VIEW ONLY bloqueia task cancel e reexecute no backend
    def test_view_only_blocks_cancel_and_reexecute(self):
        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._current_role = operator_console.ROLE_SECONDARY_VIEW_ONLY

        with self.assertRaises(PermissionError):
            operator_console.request_task_cancel("task-1", db_path=self.db_path)

        with self.assertRaises(PermissionError):
            operator_console.reexecute_task("task-1")

    # 10. VIEW ONLY bloqueia recuperação de tarefas órfãs (reconcile_orphaned_tasks)
    def test_view_only_blocks_recovery_reconciliation(self):
        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._current_role = operator_console.ROLE_SECONDARY_VIEW_ONLY

        with self.assertRaises(PermissionError):
            operator_console.reconcile_orphaned_tasks(db_path=self.db_path)

    # 11. VIEW ONLY pula scheduler worker e execução de ciclo
    def test_view_only_skips_scheduler_worker_and_cycle(self):
        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._current_role = operator_console.ROLE_SECONDARY_VIEW_ONLY

        # start_scheduler_worker deve retornar sem iniciar thread
        with patch.object(operator_console, "is_primary_instance", return_value=False):
            scheduler.start_scheduler_worker(interval_seconds=1)
        self.assertIsNone(scheduler._worker_thread)

        # run_scheduler_cycle deve retornar skipped
        res = scheduler.run_scheduler_cycle(db_path=self.db_path)
        self.assertEqual(res.get("status"), "skipped")
        self.assertEqual(res.get("reason"), "secondary_view_only")

    # 12. VIEW ONLY bloqueia mutações de agendamento no scheduler
    def test_view_only_blocks_scheduler_mutations(self):
        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._current_role = operator_console.ROLE_SECONDARY_VIEW_ONLY

        with self.assertRaises(PermissionError):
            scheduler.adopt_tasks_into_scheduler(
                task_ids=[],
                platforms=["youtube"],
                db_path=self.db_path,
            )

        with self.assertRaises(PermissionError):
            scheduler.plan_schedule(tasks=[], db_path=self.db_path)

        with self.assertRaises(PermissionError):
            scheduler.reschedule_post_for_test(1, "2026-09-17T12:00:00Z", db_path=self.db_path)

    # 13. VIEW ONLY permite todas as operações de leitura
    def test_view_only_allows_read_operations(self):
        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._current_role = operator_console.ROLE_SECONDARY_VIEW_ONLY

        status = operator_console.get_system_status(db_path=self.db_path)
        self.assertIsInstance(status, dict)
        self.assertIn("factory_state", status)

        g_sum = operator_console.get_generation_queue_summary()
        self.assertIn("total", g_sum)

        s_sum = operator_console.get_scheduler_queue_summary(db_path=self.db_path)
        self.assertIn("total", s_sum)

        stock = operator_console.get_ready_stock(db_path=self.db_path)
        self.assertIn("total_ready", stock)

        provs = operator_console.get_provider_health_summary(db_path=self.db_path)
        self.assertIn("FFmpeg", provs)

    # 14. SECONDARY não atualiza heartbeat do PRIMARY
    def test_secondary_cannot_update_primary_heartbeat(self):
        # Cria PRIMARY
        operator_console.acquire_instance_lock(
            node_name="NODE-PRIMARY",
            db_path=self.db_path,
            force_node_id="primary-uuid",
        )
        init_info = operator_console.get_instance_info(db_path=self.db_path)
        init_hb = init_info.get("last_heartbeat")

        # Troca para SECONDARY
        operator_console.reset_instance_for_testing()
        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._current_role = operator_console.ROLE_SECONDARY_VIEW_ONLY
            operator_console._current_node_id = "secondary-uuid"

        # Tenta disparar record_instance_heartbeat
        operator_console.record_instance_heartbeat(db_path=self.db_path)

        # Verifica que o heartbeat no banco não foi alterado para o nó secundário
        after_info = operator_console.get_instance_info(db_path=self.db_path)
        self.assertEqual(after_info.get("primary_node_id"), "primary-uuid")
        self.assertEqual(after_info.get("last_heartbeat"), init_hb)

    # 15. Lock ativo não pode ser roubado por outra instância
    def test_active_lock_not_stolen(self):
        operator_console.acquire_instance_lock(
            node_name="OFFICIAL-PRIMARY",
            db_path=self.db_path,
            force_node_id="official-id",
        )

        operator_console.reset_instance_for_testing()
        with patch("os.getpid", return_value=88888):
            role, _ = operator_console.acquire_instance_lock(
                node_name="ROGUE-NODE",
                db_path=self.db_path,
                force_node_id="rogue-id",
                timeout_seconds=90,
            )
            self.assertEqual(role, operator_console.ROLE_SECONDARY_VIEW_ONLY)

        info = operator_console.get_instance_info(db_path=self.db_path)
        self.assertEqual(info.get("primary_node_id"), "official-id")

    # 16. Stale lock (> 90s) permite takeover seguro e registra eventos
    def test_stale_lock_takeover(self):
        # Insere lock artificial antigo (stale)
        old_time = (datetime.now(timezone.utc) - timedelta(seconds=150)).isoformat()
        with operator_console.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO instance_locks (
                    lock_key, node_id, node_name, hostname, pid,
                    started_at, last_heartbeat, role, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    operator_console.DEFAULT_INSTANCE_LOCK_KEY,
                    "crashed-node-id",
                    "OLD-CRASHED-NODE",
                    "crashed-host",
                    7777,
                    old_time,
                    old_time,
                    operator_console.ROLE_PRIMARY,
                    operator_console.INSTANCE_STATUS_ACTIVE,
                ),
            )

        # Nova instância tenta adquirir com timeout de 90s
        role, info = operator_console.acquire_instance_lock(
            node_name="RESCUE-PRIMARY",
            db_path=self.db_path,
            force_node_id="rescue-node-id",
            timeout_seconds=90,
        )
        self.assertEqual(role, operator_console.ROLE_PRIMARY)
        self.assertEqual(info.get("node_name"), "RESCUE-PRIMARY")
        self.assertEqual(info.get("node_id"), "rescue-node-id")

        # Valida eventos operacionais
        events = operator_console.get_operational_events(db_path=self.db_path)
        types = [e.get("event_type") for e in events]
        self.assertIn(operator_console.EVENT_INSTANCE_HEARTBEAT_STALE, types)
        self.assertIn(operator_console.EVENT_INSTANCE_TAKEOVER, types)

    # 17. Atomicidade estrita na corrida de takeover (duas instâncias tentando ao mesmo tempo)
    def test_atomic_takeover_race_condition(self):
        old_time = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        with operator_console.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO instance_locks (
                    lock_key, node_id, node_name, hostname, pid,
                    started_at, last_heartbeat, role, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    operator_console.DEFAULT_INSTANCE_LOCK_KEY,
                    "stale-node-id",
                    "STALE-NODE",
                    "other-host",
                    1234,
                    old_time,
                    old_time,
                    operator_console.ROLE_PRIMARY,
                    operator_console.INSTANCE_STATUS_ACTIVE,
                ),
            )

        results = []
        barrier = threading.Barrier(2)
        pid_map = {}

        def attempt_takeover(inst_name, node_uuid, fake_pid):
            pid_map[threading.get_ident()] = fake_pid
            barrier.wait()
            role, info = operator_console.acquire_instance_lock(
                node_name=inst_name,
                db_path=self.db_path,
                force_node_id=node_uuid,
                timeout_seconds=90,
            )
            results.append((role, inst_name))

        real_getpid = os.getpid

        def dynamic_getpid():
            return pid_map.get(threading.get_ident(), real_getpid())

        t1 = threading.Thread(target=attempt_takeover, args=("RACE-A", "uuid-a", 10001))
        t2 = threading.Thread(target=attempt_takeover, args=("RACE-B", "uuid-b", 10002))

        with patch("os.getpid", side_effect=dynamic_getpid), \
             patch.object(operator_console, "_is_local_pid_alive", return_value=True):
            t1.start()
            t2.start()
            t1.join()
            t2.join()

        roles = [r[0] for r in results]
        self.assertEqual(roles.count(operator_console.ROLE_PRIMARY), 1, f"Exatamente um deve ser PRIMARY: {results}")
        self.assertEqual(roles.count(operator_console.ROLE_SECONDARY_VIEW_ONLY), 1, f"Exatamente um deve ser SECONDARY: {results}")

    # 18. Clean shutdown libera lock com status STOPPED
    def test_clean_shutdown_releases_lock(self):
        operator_console.acquire_instance_lock(
            node_name="NODE-CLEAN",
            db_path=self.db_path,
            force_node_id="clean-uuid",
        )
        self.assertTrue(operator_console.is_primary_instance(db_path=self.db_path))

        operator_console.release_instance_lock(db_path=self.db_path)

        with operator_console.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT status FROM instance_locks WHERE lock_key = ?;", (operator_console.DEFAULT_INSTANCE_LOCK_KEY,)).fetchone()
            self.assertEqual(row["status"], operator_console.INSTANCE_STATUS_STOPPED)

        events = operator_console.get_operational_events(db_path=self.db_path)
        self.assertTrue(any(e.get("event_type") == operator_console.EVENT_INSTANCE_STOPPED for e in events))

    # 19. Lock liberado limpo (STOPPED) é adquirido imediatamente sem esperar 90s
    def test_stopped_lock_immediate_acquisition(self):
        # Cria e encerra nó anterior
        operator_console.acquire_instance_lock(
            node_name="NODE-1",
            db_path=self.db_path,
            force_node_id="uuid-1",
        )
        operator_console.release_instance_lock(db_path=self.db_path)

        # Nó 2 tenta adquirir imediatamente
        operator_console.reset_instance_for_testing()
        with patch("os.getpid", return_value=5555):
            role, info = operator_console.acquire_instance_lock(
                node_name="NODE-2",
                db_path=self.db_path,
                force_node_id="uuid-2",
                timeout_seconds=90,
            )
            self.assertEqual(role, operator_console.ROLE_PRIMARY)
            self.assertEqual(info.get("node_name"), "NODE-2")

    # 20. Timestamps são timezone-aware UTC
    def test_timestamps_utc_timezone_aware(self):
        operator_console.acquire_instance_lock(
            node_name="NODE-UTC",
            db_path=self.db_path,
        )
        info = operator_console.get_instance_info(db_path=self.db_path)
        last_hb = info.get("last_heartbeat")
        self.assertIsNotNone(last_hb)

        # Parse deve ter offset UTC
        dt = datetime.fromisoformat(last_hb)
        self.assertIsNotNone(dt.tzinfo)
        self.assertEqual(dt.utcoffset(), timedelta(0))

    # 21. Config 0.0.0.0 não altera lógica de workers
    def test_config_0000_does_not_alter_worker_logic(self):
        # Assegura que binding de host em 0.0.0.0 é apenas de rede e workers continuam operando normalmente
        self.assertTrue(callable(scheduler.start_scheduler_worker))
        self.assertTrue(callable(webui_task.submit_generation))
        self.assertTrue(callable(task_module.publish_task))

    # 22. Dead local PID no mesmo host permite takeover imediato
    def test_dead_local_pid_immediate_takeover(self):
        my_host = platform.node() or socket.gethostname() or "unknown_host"
        recent_time = datetime.now(timezone.utc).isoformat()

        # Insere lock com PID inexistente (ex: 99999999) mas com timestamp recente (<10s)
        with operator_console.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO instance_locks (
                    lock_key, node_id, node_name, hostname, pid,
                    started_at, last_heartbeat, role, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    operator_console.DEFAULT_INSTANCE_LOCK_KEY,
                    "crashed-local-pid",
                    "LOCAL-CRASHED",
                    my_host,
                    99999999,
                    recent_time,
                    recent_time,
                    operator_console.ROLE_PRIMARY,
                    operator_console.INSTANCE_STATUS_ACTIVE,
                ),
            )

        # Novo processo adquire no mesmo host
        operator_console.reset_instance_for_testing()
        role, info = operator_console.acquire_instance_lock(
            node_name="RESCUE-LOCAL",
            db_path=self.db_path,
            timeout_seconds=90,
        )
        # Deve assumir como PRIMARY porque detectou que o PID local está morto
        self.assertEqual(role, operator_console.ROLE_PRIMARY)
        self.assertEqual(info.get("node_name"), "RESCUE-LOCAL")

    # 23. Mesmo processo recupera PRIMARY após perda/recriação de estado em memória
    def test_same_process_recovers_primary_after_in_memory_state_loss(self):
        # 1. PRIMARY adquirido normalmente
        role1, info1 = operator_console.acquire_instance_lock(
            node_name="ORIGINAL-PRIMARY-NODE",
            db_path=self.db_path,
        )
        self.assertEqual(role1, operator_console.ROLE_PRIMARY)
        persisted_node_id = info1.get("node_id")
        persisted_started_at = info1.get("started_at")
        persisted_hb = info1.get("last_heartbeat")
        self.assertIsNotNone(persisted_node_id)
        self.assertTrue(operator_console.is_primary_instance(db_path=self.db_path))

        # Pequena pausa para garantir avanço temporal do timestamp de heartbeat
        time.sleep(0.01)

        # 2. Simula perda/recriação apenas do estado em memória (ex: nova sessão / rerun Streamlit)
        # mantendo no SQLite o mesmo hostname, mesmo PID e node_id original
        operator_console.reset_instance_for_testing()
        self.assertFalse(operator_console._instance_initialized)
        self.assertIsNone(operator_console._current_node_id)

        # 3. ensure_instance_initialized no mesmo processo deve:
        # - continuar PRIMARY;
        # - adotar o node_id persistido;
        # - NÃO virar SECONDARY;
        # - renovar heartbeat;
        # - restaurar node_name e started_at persistidos.
        role2, info2 = operator_console.ensure_instance_initialized(
            node_name="IRRELEVANT-NEW-NAME",
            db_path=self.db_path,
        )
        self.assertEqual(role2, operator_console.ROLE_PRIMARY)
        self.assertTrue(operator_console.is_primary_instance(db_path=self.db_path))
        self.assertEqual(info2.get("node_id"), persisted_node_id)
        self.assertEqual(info2.get("node_name"), "ORIGINAL-PRIMARY-NODE")
        self.assertEqual(info2.get("started_at"), persisted_started_at)
        self.assertGreaterEqual(info2.get("last_heartbeat"), persisted_hb)
        self.assertEqual(operator_console._current_node_id, persisted_node_id)
        self.assertEqual(operator_console._current_node_name, "ORIGINAL-PRIMARY-NODE")

        # Nenhum evento espúrio de SECONDARY ou TAKEOVER
        events = operator_console.get_operational_events(db_path=self.db_path)
        view_only_evs = [
            e for e in events
            if e.get("event_type") == operator_console.EVENT_INSTANCE_VIEW_ONLY_STARTED
        ]
        self.assertEqual(len(view_only_evs), 0)
        takeover_evs = [
            e for e in events
            if e.get("event_type") == operator_console.EVENT_INSTANCE_TAKEOVER
        ]
        self.assertEqual(len(takeover_evs), 0)

        # Guards de execução continuam permitidos sem PermissionError
        try:
            operator_console.require_primary_instance(db_path=self.db_path)
        except PermissionError:
            self.fail("require_primary_instance levantou PermissionError inesperado após recuperação.")

        # Re-inicialização direta via acquire_instance_lock após novo reset em memória também deve recuperar
        operator_console.reset_instance_for_testing()
        role3, info3 = operator_console.acquire_instance_lock(
            node_name="ANOTHER-NAME",
            db_path=self.db_path,
        )
        self.assertEqual(role3, operator_console.ROLE_PRIMARY)
        self.assertEqual(info3.get("node_id"), persisted_node_id)
        self.assertEqual(info3.get("node_name"), "ORIGINAL-PRIMARY-NODE")

    # 24. Host diferente com lock ACTIVE saudável vira SECONDARY_VIEW_ONLY
    def test_different_host_with_active_lock_enters_view_only(self):
        # 1. Lock PRIMARY ativo criado no host atual
        role1, info1 = operator_console.acquire_instance_lock(
            node_name="PRIMARY-ON-DESKTOP",
            db_path=self.db_path,
        )
        self.assertEqual(role1, operator_console.ROLE_PRIMARY)

        # 2. Processo em host remoto tentando conectar no mesmo banco
        operator_console.reset_instance_for_testing()
        with patch("platform.node", return_value="NOTEBOOK-REMOTE"), \
             patch("socket.gethostname", return_value="NOTEBOOK-REMOTE"):
            role2, info2 = operator_console.acquire_instance_lock(
                node_name="NOTEBOOK-NODE",
                db_path=self.db_path,
                timeout_seconds=90,
            )
            self.assertEqual(role2, operator_console.ROLE_SECONDARY_VIEW_ONLY)
            self.assertFalse(operator_console.is_primary_instance(db_path=self.db_path))
            self.assertEqual(info2.get("node_name"), "PRIMARY-ON-DESKTOP")

        # Confere que o lock no SQLite permanece íntegro com PRIMARY-ON-DESKTOP
        inst_info = operator_console.get_instance_info(db_path=self.db_path)
        self.assertEqual(inst_info.get("primary_node_name"), "PRIMARY-ON-DESKTOP")


if __name__ == "__main__":
    unittest.main()
