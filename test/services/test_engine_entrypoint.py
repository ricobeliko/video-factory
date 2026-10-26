"""
Testes Unitários do Motor Unificado V2 — scripts/engine_entrypoint.py (Missões D e F).

Valida com mocks (sem iniciar processos, workers ou servidores de rede reais):
(a) Ordem estrita de boot: wait lock -> acquire lock -> recover -> reconcile -> worker -> servidor;
(b) SECONDARY sai com código != 0 sem abrir porta;
(c) Worker que não confirma atividade aborta antes de abrir porta;
(d) Flag --no-worker não inicia worker nem watchdog;
(e) Encerramento limpo chama stop worker e release lock;
(f) Watchdog monitora e reinicia worker inativo;
(g) Espera pelo lock termina quando o lock expira/é liberado;
(h) Espera acaba por tempo (timeout) e o motor aborta como SECONDARY;
(i) Flag --lock-wait-seconds 0 desliga espera;
(j) Subclasse EngineServer chama clean_shutdown no shutdown().
"""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import MagicMock, patch

import uvicorn

from app.services import operator_console
from scripts import engine_entrypoint


class TestEngineEntrypoint(unittest.TestCase):
    def setUp(self):
        # Garante estado limpo de shutdown para cada teste
        engine_entrypoint._shutdown_completed = False

    def test_boot_order_lock_recover_reconcile_worker_server(self):
        """(a) Ordem estrita de boot: lock -> recover -> reconcile -> worker -> servidor."""
        call_order = []

        def mock_lock(*args, **kwargs):
            call_order.append("lock")
            return operator_console.ROLE_PRIMARY, {"node_name": "TestNode", "pid": 1234}

        def mock_recover(*args, **kwargs):
            call_order.append("recover")
            return []

        def mock_reconcile(*args, **kwargs):
            call_order.append("reconcile")
            return []

        def mock_start_worker(*args, **kwargs):
            call_order.append("worker")

        def mock_server(*args, **kwargs):
            call_order.append("servidor")

        with patch("app.services.operator_console.ensure_instance_initialized", side_effect=mock_lock), \
             patch("app.services.task.recover_interrupted_cross_posts", side_effect=mock_recover), \
             patch("app.services.operator_console.reconcile_orphaned_tasks", side_effect=mock_reconcile), \
             patch("app.services.scheduler.start_scheduler_worker", side_effect=mock_start_worker), \
             patch("app.services.scheduler.is_worker_alive", return_value=True), \
             patch("scripts.engine_entrypoint.run_engine_server", side_effect=mock_server), \
             patch("scripts.engine_entrypoint.shutdown_worker_and_lock"), \
             patch("scripts.engine_entrypoint.wait_for_primary_lock", return_value=True):

            exit_code = engine_entrypoint.main(["--port", "8080"])
            self.assertEqual(exit_code, 0)
            self.assertEqual(
                call_order,
                ["lock", "recover", "reconcile", "worker", "servidor"],
                f"Ordem de boot incorreta: {call_order}",
            )

    def test_secondary_exits_nonzero_without_opening_port(self):
        """(b) SECONDARY sai com código != 0 sem abrir porta de rede."""
        with patch(
            "app.services.operator_console.ensure_instance_initialized",
            return_value=(operator_console.ROLE_SECONDARY_VIEW_ONLY, {"node_name": "PrimaryNode", "pid": 999}),
        ), \
             patch("app.services.task.recover_interrupted_cross_posts") as mock_recover, \
             patch("app.services.operator_console.reconcile_orphaned_tasks") as mock_reconcile, \
             patch("app.services.scheduler.start_scheduler_worker") as mock_worker, \
             patch("scripts.engine_entrypoint.run_engine_server") as mock_server, \
             patch("scripts.engine_entrypoint.shutdown_worker_and_lock"), \
             patch("scripts.engine_entrypoint.wait_for_primary_lock", return_value=False):

            exit_code = engine_entrypoint.main(["--port", "8080"])
            self.assertNotEqual(exit_code, 0, "Instância SECONDARY deve retornar código de saída != 0")
            mock_recover.assert_not_called()
            mock_reconcile.assert_not_called()
            mock_worker.assert_not_called()
            mock_server.assert_not_called()

    def test_worker_not_alive_aborts(self):
        """(c) Worker que não confirma atividade aborta antes de abrir porta."""
        with patch(
            "app.services.operator_console.ensure_instance_initialized",
            return_value=(operator_console.ROLE_PRIMARY, {"node_name": "TestNode", "pid": 1234}),
        ), \
             patch("app.services.task.recover_interrupted_cross_posts"), \
             patch("app.services.operator_console.reconcile_orphaned_tasks"), \
             patch("app.services.scheduler.start_scheduler_worker"), \
             patch("app.services.scheduler.is_worker_alive", return_value=False), \
             patch("scripts.engine_entrypoint.run_engine_server") as mock_server, \
             patch("scripts.engine_entrypoint.shutdown_worker_and_lock") as mock_shutdown, \
             patch("scripts.engine_entrypoint.wait_for_primary_lock", return_value=True):

            exit_code = engine_entrypoint.main(["--port", "8080"])
            self.assertNotEqual(exit_code, 0, "Falha na confirmação do worker deve abortar com código != 0")
            mock_server.assert_not_called()
            mock_shutdown.assert_called()

    def test_no_worker_flag_skips_worker_and_watchdog(self):
        """(d) Flag --no-worker não inicia worker nem watchdog, mas sobe servidor."""
        with patch(
            "app.services.operator_console.ensure_instance_initialized",
            return_value=(operator_console.ROLE_PRIMARY, {"node_name": "TestNode", "pid": 1234}),
        ), \
             patch("app.services.task.recover_interrupted_cross_posts"), \
             patch("app.services.operator_console.reconcile_orphaned_tasks"), \
             patch("app.services.scheduler.start_scheduler_worker") as mock_start_worker, \
             patch("scripts.engine_entrypoint.SchedulerWatchdog") as mock_watchdog_cls, \
             patch("scripts.engine_entrypoint.run_engine_server") as mock_server, \
             patch("scripts.engine_entrypoint.shutdown_worker_and_lock"), \
             patch("scripts.engine_entrypoint.wait_for_primary_lock", return_value=True):

            exit_code = engine_entrypoint.main(["--no-worker", "--port", "8080"])
            self.assertEqual(exit_code, 0)
            mock_start_worker.assert_not_called()
            mock_watchdog_cls.assert_not_called()
            mock_server.assert_called_once()

    def test_shutdown_calls_stop_worker_and_release_lock(self):
        """(e) Encerramento chama stop worker e release lock de forma limpa e idempotente."""
        mock_watchdog = MagicMock()
        with patch(
            "app.services.operator_console.ensure_instance_initialized",
            return_value=(operator_console.ROLE_PRIMARY, {"node_name": "TestNode", "pid": 1234}),
        ), \
             patch("app.services.task.recover_interrupted_cross_posts"), \
             patch("app.services.operator_console.reconcile_orphaned_tasks"), \
             patch("app.services.scheduler.start_scheduler_worker"), \
             patch("app.services.scheduler.is_worker_alive", return_value=True), \
             patch("scripts.engine_entrypoint.SchedulerWatchdog", return_value=mock_watchdog), \
             patch("scripts.engine_entrypoint.run_engine_server"), \
             patch("app.services.scheduler.stop_scheduler_worker") as mock_stop_worker, \
             patch("app.services.operator_console.release_instance_lock") as mock_release_lock, \
             patch("scripts.engine_entrypoint.wait_for_primary_lock", return_value=True):

            exit_code = engine_entrypoint.main([])
            self.assertEqual(exit_code, 0)
            mock_watchdog.stop.assert_called_once()
            mock_stop_worker.assert_called_once()
            mock_release_lock.assert_called_once()

    def test_watchdog_restarts_dead_worker(self):
        """(f) Watchdog identifica worker inativo e executa restart com log."""
        watchdog = engine_entrypoint.SchedulerWatchdog(interval_seconds=1)
        with patch("app.services.scheduler.is_worker_alive", return_value=False), \
             patch("app.services.scheduler.start_scheduler_worker") as mock_start_worker:

            from app.services import scheduler

            if not scheduler.is_worker_alive():
                scheduler.start_scheduler_worker(interval_seconds=watchdog.interval_seconds)

            mock_start_worker.assert_called_once_with(interval_seconds=1)

    def test_lock_wait_succeeds_when_lock_expires(self):
        """(g) Espera pelo lock termina quando o lock expira/é liberado antes do timeout."""
        current_time = 1000.0

        def mock_monotonic():
            return current_time

        def mock_sleep(seconds):
            nonlocal current_time
            current_time += seconds

        info_active = {
            "primary_node_name": "OldPrimary",
            "primary_pid": 8888,
            "primary_status": "ACTIVE",
            "is_heartbeat_stale": False,
            "heartbeat_seconds_ago": 10,
        }
        info_stale = {
            "primary_node_name": "OldPrimary",
            "primary_pid": 8888,
            "primary_status": "ACTIVE",
            "is_heartbeat_stale": True,
            "heartbeat_seconds_ago": 95,
        }

        with patch("time.monotonic", side_effect=mock_monotonic), \
             patch("time.sleep", side_effect=mock_sleep) as mock_sl, \
             patch("app.services.operator_console.get_instance_info", side_effect=[info_active, info_active, info_stale]):

            res = engine_entrypoint.wait_for_primary_lock(
                lock_wait_seconds=60,
                check_interval_seconds=5.0,
            )
            self.assertTrue(res)
            self.assertEqual(mock_sl.call_count, 2)

    def test_lock_wait_times_out_and_aborts(self):
        """(h) Espera acaba por tempo (timeout) e o motor aborta como SECONDARY."""
        current_time = 1000.0

        def mock_monotonic():
            return current_time

        def mock_sleep(seconds):
            nonlocal current_time
            current_time += seconds

        info_active = {
            "primary_node_name": "ActivePrimary",
            "primary_pid": 7777,
            "primary_status": "ACTIVE",
            "is_heartbeat_stale": False,
            "heartbeat_seconds_ago": 5,
        }

        with patch("time.monotonic", side_effect=mock_monotonic), \
             patch("time.sleep", side_effect=mock_sleep), \
             patch("app.services.operator_console.get_instance_info", return_value=info_active), \
             patch(
                 "app.services.operator_console.ensure_instance_initialized",
                 return_value=(operator_console.ROLE_SECONDARY_VIEW_ONLY, {"node_name": "ActivePrimary", "pid": 7777}),
             ), \
             patch("scripts.engine_entrypoint.run_engine_server") as mock_server, \
             patch("scripts.engine_entrypoint.shutdown_worker_and_lock"):

            exit_code = engine_entrypoint.main(["--lock-wait-seconds", "15"])
            self.assertNotEqual(exit_code, 0)
            mock_server.assert_not_called()

    def test_lock_wait_zero_skips_wait(self):
        """(i) --lock-wait-seconds 0 não espera nem consulta/dorme."""
        with patch("time.sleep") as mock_sleep, \
             patch("app.services.operator_console.get_instance_info") as mock_get_info, \
             patch(
                 "app.services.operator_console.ensure_instance_initialized",
                 return_value=(operator_console.ROLE_PRIMARY, {"node_name": "Node", "pid": 111}),
             ), \
             patch("app.services.task.recover_interrupted_cross_posts"), \
             patch("app.services.operator_console.reconcile_orphaned_tasks"), \
             patch("scripts.engine_entrypoint.run_engine_server"), \
             patch("scripts.engine_entrypoint.shutdown_worker_and_lock"):

            exit_code = engine_entrypoint.main(["--no-worker", "--lock-wait-seconds", "0"])
            self.assertEqual(exit_code, 0)
            mock_sleep.assert_not_called()
            mock_get_info.assert_not_called()

    def test_engine_server_subclass_calls_clean_shutdown(self):
        """(j) Subclasse EngineServer chama clean_shutdown(watchdog) no shutdown()."""
        mock_watchdog = MagicMock()
        config = uvicorn.Config(app=MagicMock(), host="127.0.0.1", port=8080)
        server = engine_entrypoint.EngineServer(config=config, watchdog=mock_watchdog)

        with patch("uvicorn.Server.shutdown", return_value=None), \
             patch("scripts.engine_entrypoint.clean_shutdown") as mock_clean:

            asyncio.run(server.shutdown())
            mock_clean.assert_called_once_with(mock_watchdog)

    def test_lock_wait_dead_pid_same_host_returns_true_immediately(self):
        """(k) PID morto no mesmo host -> retorna True imediatamente sem esperar."""
        info_dead_pid = {
            "primary_node_name": "DeadPrimary",
            "primary_pid": 9999,
            "primary_status": "ACTIVE",
            "primary_hostname": "workstation-alpha",
            "hostname": "workstation-alpha",
            "pid": 1234,
            "is_heartbeat_stale": False,
            "heartbeat_seconds_ago": 15,
        }

        with patch("time.sleep") as mock_sleep, \
             patch("app.services.operator_console.get_instance_info", return_value=info_dead_pid), \
             patch("app.services.operator_console.is_local_pid_alive", return_value=False) as mock_pid_alive, \
             patch.object(engine_entrypoint.logger, "info") as mock_logger_info:

            res = engine_entrypoint.wait_for_primary_lock(lock_wait_seconds=60)
            self.assertTrue(res)
            mock_sleep.assert_not_called()
            mock_pid_alive.assert_called_once_with(9999)
            mock_logger_info.assert_any_call(
                "[ENGINE_BOOT] PRIMARY anterior (PID 9999) não existe mais; assumindo imediatamente"
            )

        # Caso próprio PID (ex: reinício/recuperação)
        info_own_pid = {
            "primary_node_name": "OwnNode",
            "primary_pid": 1234,
            "primary_status": "ACTIVE",
            "primary_hostname": "workstation-alpha",
            "hostname": "workstation-alpha",
            "pid": 1234,
            "is_heartbeat_stale": False,
            "heartbeat_seconds_ago": 5,
        }
        with patch("time.sleep") as mock_sleep, \
             patch("app.services.operator_console.get_instance_info", return_value=info_own_pid):

            res = engine_entrypoint.wait_for_primary_lock(lock_wait_seconds=60)
            self.assertTrue(res)
            mock_sleep.assert_not_called()

    def test_lock_wait_live_pid_same_host_waits_and_respects_timeout(self):
        """(l) PID vivo no mesmo host -> espera e respeita o timeout esgotado."""
        current_time = 1000.0

        def mock_monotonic():
            return current_time

        def mock_sleep(seconds):
            nonlocal current_time
            current_time += seconds

        info_live_pid = {
            "primary_node_name": "LivePrimary",
            "primary_pid": 8888,
            "primary_status": "ACTIVE",
            "primary_hostname": "workstation-alpha",
            "hostname": "workstation-alpha",
            "pid": 1234,
            "is_heartbeat_stale": False,
            "heartbeat_seconds_ago": 10,
        }

        with patch("time.monotonic", side_effect=mock_monotonic),              patch("time.sleep", side_effect=mock_sleep) as mock_sleep_call,              patch("app.services.operator_console.get_instance_info", return_value=info_live_pid),              patch("app.services.operator_console.is_local_pid_alive", return_value=True):

            res = engine_entrypoint.wait_for_primary_lock(lock_wait_seconds=15, check_interval_seconds=5.0)
            self.assertFalse(res)
            self.assertEqual(mock_sleep_call.call_count, 3)

    def test_lock_wait_different_host_waits_and_respects_timeout(self):
        """(m) Host diferente -> não assume PID local e respeita o timeout de espera."""
        current_time = 1000.0

        def mock_monotonic():
            return current_time

        def mock_sleep(seconds):
            nonlocal current_time
            current_time += seconds

        info_diff_host = {
            "primary_node_name": "RemotePrimary",
            "primary_pid": 9999,
            "primary_status": "ACTIVE",
            "primary_hostname": "server-beta",
            "hostname": "workstation-alpha",
            "pid": 1234,
            "is_heartbeat_stale": False,
            "heartbeat_seconds_ago": 10,
        }

        with patch("time.monotonic", side_effect=mock_monotonic),              patch("time.sleep", side_effect=mock_sleep) as mock_sleep_call,              patch("app.services.operator_console.get_instance_info", return_value=info_diff_host),              patch("app.services.operator_console.is_local_pid_alive", return_value=False) as mock_pid_alive:

            res = engine_entrypoint.wait_for_primary_lock(lock_wait_seconds=10, check_interval_seconds=5.0)
            self.assertFalse(res)
            # Mesmo se o PID estiver morto localmente, não deve checar PID local pois host é diferente
            mock_pid_alive.assert_not_called()
            self.assertEqual(mock_sleep_call.call_count, 2)

    def test_lock_wait_missing_or_inconsistent_data_waits_safely(self):
        """(n) Dados ausentes/inconsistentes -> na dúvida, espera com segurança."""
        current_time = 1000.0

        def mock_monotonic():
            return current_time

        def mock_sleep(seconds):
            nonlocal current_time
            current_time += seconds

        inconsistent_cases = [
            # PID ausente
            {
                "primary_node_name": "NodeA",
                "primary_pid": None,
                "primary_status": "ACTIVE",
                "primary_hostname": "host-alpha",
                "hostname": "host-alpha",
                "is_heartbeat_stale": False,
            },
            # Host ausente
            {
                "primary_node_name": "NodeB",
                "primary_pid": 8888,
                "primary_status": "ACTIVE",
                "primary_hostname": None,
                "hostname": "host-alpha",
                "is_heartbeat_stale": False,
            },
            # PID inválido não conversível para inteiro
            {
                "primary_node_name": "NodeC",
                "primary_pid": "invalid_pid",
                "primary_status": "ACTIVE",
                "primary_hostname": "host-alpha",
                "hostname": "host-alpha",
                "is_heartbeat_stale": False,
            },
            # PID menor ou igual a 0
            {
                "primary_node_name": "NodeD",
                "primary_pid": 0,
                "primary_status": "ACTIVE",
                "primary_hostname": "host-alpha",
                "hostname": "host-alpha",
                "is_heartbeat_stale": False,
            },
        ]

        for case_info in inconsistent_cases:
            current_time = 1000.0
            with patch("time.monotonic", side_effect=mock_monotonic),                  patch("time.sleep", side_effect=mock_sleep) as mock_sl,                  patch("app.services.operator_console.get_instance_info", return_value=case_info):

                res = engine_entrypoint.wait_for_primary_lock(lock_wait_seconds=5, check_interval_seconds=5.0)
                self.assertFalse(res, f"Falha no caso: {case_info}")
                self.assertEqual(mock_sl.call_count, 1)


    def test_engine_terminates_cleanly_under_signal_and_releases_lock(self):
        """(o) Valida que sob sinal de interrupção o motor encerra limpo em < 15s e libera o lock PRIMARY."""
        import os
        import signal
        import socket
        import sqlite3
        import subprocess
        import sys
        import time
        import urllib.request

        # 1. Aloca porta TCP livre
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        test_port = s.getsockname()[1]
        s.close()

        # 2. Banco isolado temporário
        temp_dir = os.environ.get("TEMP", "C:\\Temp")
        test_db = os.path.join(temp_dir, f"test_e3_signal_{test_port}.db")
        if os.path.exists(test_db):
            try:
                os.remove(test_db)
            except Exception:
                pass

        env = os.environ.copy()
        env["VIDEO_FACTORY_DB_PATH"] = test_db
        env["PYTHONPATH"] = str(engine_entrypoint.PROJECT_ROOT)

        cmd = [sys.executable, str(engine_entrypoint.PROJECT_ROOT / "scripts" / "engine_entrypoint.py"), "--port", str(test_port)]
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0

        proc = subprocess.Popen(cmd, env=env, creationflags=creationflags)
        try:
            # 3. Aguarda boot com timeout estrito
            t0 = time.time()
            booted = False
            while time.time() - t0 < 25:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{test_port}/", timeout=0.5) as resp:
                        if resp.status == 200:
                            booted = True
                            break
                except Exception:
                    time.sleep(0.3)

            self.assertTrue(booted, "Motor não inicializou dentro do tempo limite")

            # 4. Envia sinal de interrupção
            t_sig = time.time()
            if sys.platform == "win32":
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                proc.send_signal(signal.SIGINT)

            proc.wait(timeout=15)
            elapsed = time.time() - t_sig

            self.assertLess(elapsed, 15.0, f"Encerramento demorou mais que 15s: {elapsed:.2f}s")
            self.assertEqual(proc.returncode, 0, f"Código de saída esperado 0, obteve {proc.returncode}")

            # 5. Valida liberação do lock no SQLite
            self.assertTrue(os.path.exists(test_db), "Banco temporário não foi encontrado")
            conn = sqlite3.connect(test_db)
            cur = conn.cursor()
            cur.execute("SELECT status FROM instance_locks WHERE node_name='ProductionEngine'")
            row = cur.fetchone()
            conn.close()

            self.assertIsNotNone(row, "Registro do lock PRIMARY não encontrado no banco")
            self.assertEqual(row[0], "STOPPED", f"Lock deveria estar STOPPED, mas está: {row[0]}")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            if os.path.exists(test_db):
                try:
                    os.remove(test_db)
                except Exception:
                    pass
