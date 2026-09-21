"""
Tests for V12-F.1B — Headless Worker Bootstrap (scripts/production_entrypoint.py).

Cobre os requisitos T1, T2, T3, T6, T7, T8, T9 definidos na fase.
T4 (idempotência de start_scheduler_worker) e T5 (tick/heartbeat sem navegador)
já são cobertos por test/services/test_scheduler_worker.py (testes 01-03), que
validam exatamente essas propriedades na mesma função de produção reutilizada
por este entrypoint — não duplicados aqui para evitar testes de thread real
redundantes e potencialmente instáveis.
T10 (regressão ampla) é executado separadamente via pytest multi-suite.

MANDATÓRIO: nenhuma chamada real ao Streamlit (bootstrap.run é sempre mockado),
nenhuma API externa, nenhuma publicação real.
"""
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENTRYPOINT_SCRIPT = PROJECT_ROOT / "scripts" / "production_entrypoint.py"

_SPEC = importlib.util.spec_from_file_location("production_entrypoint", ENTRYPOINT_SCRIPT)
production_entrypoint = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(production_entrypoint)

from app.services import operator_console, scheduler  # noqa: E402


class TestBootstrapPrimaryAndWorker(unittest.TestCase):
    """T1, T3, T7: bootstrap do PRIMARY guard + worker antes do Streamlit subir."""

    def test_t1_primary_acquired_starts_worker(self):
        """T1: startup sem browser => PRIMARY adquirido => worker iniciado."""
        with patch.object(
            operator_console, "ensure_instance_initialized",
            return_value=(operator_console.ROLE_PRIMARY, {"node_name": "n1", "pid": 123}),
        ) as mock_ensure, patch.object(scheduler, "start_scheduler_worker") as mock_start, \
             patch.object(scheduler, "is_worker_alive", return_value=True) as mock_alive:
            result = production_entrypoint.bootstrap_primary_and_worker()

        self.assertTrue(result)
        mock_ensure.assert_called_once()
        mock_start.assert_called_once_with(interval_seconds=production_entrypoint.DEFAULT_WORKER_INTERVAL_SECONDS)
        mock_alive.assert_called_once()

    def test_t2_no_streamlit_session_required(self):
        """T2: nenhuma sessão Streamlit é necessária para iniciar o worker."""
        # bootstrap_primary_and_worker não importa nem referencia o módulo streamlit.
        self.assertNotIn("streamlit", production_entrypoint.bootstrap_primary_and_worker.__globals__)

    def test_t3_secondary_does_not_start_worker(self):
        """T3: instância SECONDARY_VIEW_ONLY não inicia o worker."""
        with patch.object(
            operator_console, "ensure_instance_initialized",
            return_value=(operator_console.ROLE_SECONDARY_VIEW_ONLY, {"node_name": "primary-node", "pid": 999}),
        ), patch.object(scheduler, "start_scheduler_worker") as mock_start:
            result = production_entrypoint.bootstrap_primary_and_worker()

        self.assertFalse(result)
        mock_start.assert_not_called()

    def test_t7_worker_not_confirmed_alive_raises(self):
        """T7: falha ao confirmar o worker vivo levanta erro diagnosticável (fail-closed)."""
        with patch.object(
            operator_console, "ensure_instance_initialized",
            return_value=(operator_console.ROLE_PRIMARY, {"node_name": "n1", "pid": 123}),
        ), patch.object(scheduler, "start_scheduler_worker"), \
             patch.object(scheduler, "is_worker_alive", return_value=False):
            with self.assertRaises(RuntimeError):
                production_entrypoint.bootstrap_primary_and_worker()

    def test_t7_main_returns_error_code_and_never_starts_streamlit(self):
        """T7: erro crítico no bootstrap => main() retorna código != 0 e Streamlit nunca inicia."""
        with patch.object(
            production_entrypoint, "bootstrap_primary_and_worker", side_effect=RuntimeError("boom")
        ), patch.object(production_entrypoint, "run_streamlit_server") as mock_run:
            exit_code = production_entrypoint.main(argv=[])

        self.assertEqual(exit_code, 1)
        mock_run.assert_not_called()


class TestFlagOptionsAndStreamlitLauncher(unittest.TestCase):
    """T6: o launcher do Streamlit recebe os mesmos parâmetros operacionais atuais."""

    def test_t6_build_flag_options_matches_current_operational_parameters(self):
        args = production_entrypoint.parse_args([
            "--server.address=0.0.0.0",
            "--server.port=8501",
            "--server.headless=true",
            "--browser.gatherUsageStats=false",
            "--client.toolbarMode=minimal",
            "--logger.hideWelcomeMessage=true",
            "--server.showEmailPrompt=false",
            "--server.enableCORS=true",
        ])
        flag_options = production_entrypoint.build_flag_options(args)

        self.assertEqual(flag_options, {
            "server_address": "0.0.0.0",
            "server_port": 8501,
            "server_headless": True,
            "browser_gatherUsageStats": False,
            "client_toolbarMode": "minimal",
            "logger_hideWelcomeMessage": True,
            "server_showEmailPrompt": False,
            "server_enableCORS": True,
        })

    def test_t6_run_streamlit_server_calls_public_bootstrap_api_same_process(self):
        fake_bootstrap = MagicMock()
        fake_streamlit_web = MagicMock(bootstrap=fake_bootstrap)
        flag_options = {"server_address": "0.0.0.0", "server_port": 8501}

        with patch.dict(sys.modules, {
            "streamlit.web": fake_streamlit_web,
            "streamlit.web.bootstrap": fake_bootstrap,
        }):
            production_entrypoint.run_streamlit_server(flag_options, main_script_path="webui/Main.py")

        fake_bootstrap.load_config_options.assert_called_once_with(flag_options=flag_options)
        fake_bootstrap.run.assert_called_once_with("webui/Main.py", False, [], flag_options)


class TestShutdownConvergence(unittest.TestCase):
    """T8: shutdown converge sem corromper estado, mesmo com falhas parciais."""

    def test_t8_shutdown_stops_worker_and_releases_lock(self):
        with patch.object(scheduler, "stop_scheduler_worker") as mock_stop, \
             patch.object(operator_console, "release_instance_lock") as mock_release:
            production_entrypoint.shutdown_worker_and_lock()

        mock_stop.assert_called_once()
        mock_release.assert_called_once()

    def test_t8_shutdown_survives_partial_failure(self):
        """Uma falha ao parar o worker não impede a liberação do lock (nem propaga exceção)."""
        with patch.object(scheduler, "stop_scheduler_worker", side_effect=Exception("worker error")), \
             patch.object(operator_console, "release_instance_lock") as mock_release:
            production_entrypoint.shutdown_worker_and_lock()  # não deve levantar

        mock_release.assert_called_once()

    def test_t9_no_external_api_or_real_publication_in_shutdown(self):
        """T9: shutdown não aciona rede/publicação real (apenas os dois helpers locais)."""
        with patch.object(scheduler, "stop_scheduler_worker") as mock_stop, \
             patch.object(operator_console, "release_instance_lock") as mock_release, \
             patch("requests.request") as mock_requests:
            production_entrypoint.shutdown_worker_and_lock()

        mock_stop.assert_called_once()
        mock_release.assert_called_once()
        mock_requests.assert_not_called()


class TestMainFinallyShutdown(unittest.TestCase):
    """T8: mesmo se o servidor Streamlit lançar exceção, o shutdown ainda converge."""

    def test_main_calls_shutdown_even_if_streamlit_raises(self):
        with patch.object(
            production_entrypoint, "bootstrap_primary_and_worker", return_value=True
        ), patch.object(
            production_entrypoint, "run_streamlit_server", side_effect=RuntimeError("server crashed")
        ), patch.object(production_entrypoint, "shutdown_worker_and_lock") as mock_shutdown:
            with self.assertRaises(RuntimeError):
                production_entrypoint.main(argv=[])

        mock_shutdown.assert_called_once()


if __name__ == "__main__":
    unittest.main()
