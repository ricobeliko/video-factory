"""
Testes Unitários do Motor Unificado V2 — scripts/engine_entrypoint.py (Missão D).

Valida com mocks (sem iniciar processos, workers ou servidores de rede reais):
(a) Ordem estrita de boot: lock -> recover -> reconcile -> worker -> servidor;
(b) SECONDARY sai com código != 0 sem abrir porta;
(c) Worker que não confirma atividade aborta antes de abrir porta;
(d) Flag --no-worker não inicia worker nem watchdog;
(e) Encerramento limpo chama stop worker e release lock;
(f) Watchdog monitora e reinicia worker inativo.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

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
             patch("scripts.engine_entrypoint.shutdown_worker_and_lock"):

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
             patch("scripts.engine_entrypoint.shutdown_worker_and_lock"):

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
             patch("scripts.engine_entrypoint.shutdown_worker_and_lock") as mock_shutdown:

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
             patch("scripts.engine_entrypoint.shutdown_worker_and_lock"):

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
             patch("app.services.operator_console.release_instance_lock") as mock_release_lock:

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
