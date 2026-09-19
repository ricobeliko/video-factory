"""
Test Suite para o Serviço de Production Health e Readiness (Fase V12-A).

Cobre:
1. Estado HEALTHY com todos os componentes operacionais
2. Diagnóstico de banco SQLite ausente -> UNHEALTHY
3. Diagnóstico de banco SQLite corrompido/inacessível -> UNHEALTHY
4. Diagnóstico de storage não gravável -> UNHEALTHY
5. Diagnóstico de FFmpeg indisponível -> UNHEALTHY
6. Identificação de papel PRIMARY vs SECONDARY_VIEW_ONLY
7. Estado da fábrica PAUSED -> status DEGRADED
8. Scheduler desabilitado -> status DEGRADED
9. Provedor degradado refletido no diagnóstico
10. Readiness check: Python runtime, venv, database, storage, ffmpeg
11. Readiness check: checagem passiva de presença de credenciais (PRESENT / MISSING)
12. Zero chamadas a APIs de rede externas
13. Zero geração de vídeo ou publicação
14. Operações estritamente read-only / passivas
"""
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.services import (
    operator_console,
    production_health,
    profile_manager,
    scheduler,
)
from app.utils import utils


class TestProductionHealth(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = os.path.join(self.tmp_dir.name, "test_health.db")

        operator_console.reset_instance_for_testing()
        with operator_console._instance_state_lock:
            operator_console._current_role = operator_console.ROLE_PRIMARY

        # Inicializa tabelas
        profile_manager.init_profile_db(db_path=self.test_db_path)
        profile_manager.ensure_default_profile(db_path=self.test_db_path)
        scheduler.init_db(db_path=self.test_db_path)
        operator_console.init_operator_db(db_path=self.test_db_path)

    def tearDown(self):
        operator_console.reset_instance_for_testing()
        self.tmp_dir.cleanup()

    def test_01_healthy_state(self):
        """Verifica que com todos os componentes operacionais o status é HEALTHY."""
        with patch("app.services.scheduler.is_worker_alive", return_value=True):
            with patch("app.services.scheduler.get_all_settings", return_value={"scheduler_enabled": True, "auto_publish_enabled": True, "dry_run": False}):
                with patch("app.utils.utils.check_ffmpeg_ready", return_value=True):
                    health = production_health.get_production_health(db_path=self.test_db_path)

                    self.assertEqual(health["status"], production_health.HEALTH_STATUS_HEALTHY)
                    self.assertEqual(health["instance_role"], operator_console.ROLE_PRIMARY)
                    self.assertEqual(health["factory_state"], operator_console.FACTORY_STATE_RUNNING)
                    self.assertTrue(health["database"]["accessible"])
                    self.assertTrue(health["storage"]["writable"])
                    self.assertTrue(health["ffmpeg"]["available"])
                    self.assertEqual(len(health["unhealthy_reasons"]), 0)

    def test_02_database_missing(self):
        """Se o arquivo de banco não existir em disco, o status é UNHEALTHY."""
        non_existent_db = os.path.join(self.tmp_dir.name, "non_existent.db")
        health = production_health.get_production_health(db_path=non_existent_db)

        self.assertEqual(health["status"], production_health.HEALTH_STATUS_UNHEALTHY)
        self.assertFalse(health["database"]["accessible"])
        self.assertIn("Banco de dados SQLite ausente", health["unhealthy_reasons"])

    def test_03_database_inaccessible(self):
        """Se houver erro de leitura no banco SQLite, o status é UNHEALTHY."""
        bad_db = os.path.join(self.tmp_dir.name, "corrupt.db")
        with open(bad_db, "w") as f:
            f.write("NOT_A_SQLITE_DATABASE")

        health = production_health.get_production_health(db_path=bad_db)
        self.assertEqual(health["status"], production_health.HEALTH_STATUS_UNHEALTHY)
        self.assertFalse(health["database"]["accessible"])
        self.assertIsNotNone(health["database"]["error"])

    def test_04_storage_inaccessible(self):
        """Se o diretório de storage não puder ser gravado, o status é UNHEALTHY."""
        with patch("builtins.open", side_effect=PermissionError("Disco protegido contra gravação")):
            health = production_health.get_production_health(db_path=self.test_db_path)
            self.assertEqual(health["status"], production_health.HEALTH_STATUS_UNHEALTHY)
            self.assertFalse(health["storage"]["writable"])
            self.assertIsNotNone(health["storage"]["error"])

    def test_05_ffmpeg_unavailable(self):
        """Se o FFmpeg não estiver disponível, o status é UNHEALTHY."""
        with patch("app.utils.utils.check_ffmpeg_ready", return_value=False):
            health = production_health.get_production_health(db_path=self.test_db_path)
            self.assertEqual(health["status"], production_health.HEALTH_STATUS_UNHEALTHY)
            self.assertFalse(health["ffmpeg"]["available"])
            self.assertIn("FFmpeg indisponível ou com falha na execução", health["unhealthy_reasons"])

    def test_06_primary_vs_secondary_role(self):
        """Instância SECONDARY_VIEW_ONLY é detectada e marca status como DEGRADED."""
        with operator_console._instance_state_lock:
            operator_console._current_role = operator_console.ROLE_SECONDARY_VIEW_ONLY

        with patch("app.utils.utils.check_ffmpeg_ready", return_value=True):
            health = production_health.get_production_health(db_path=self.test_db_path)
            self.assertEqual(health["instance_role"], operator_console.ROLE_SECONDARY_VIEW_ONLY)
            self.assertEqual(health["status"], production_health.HEALTH_STATUS_DEGRADED)
            self.assertTrue(any("SECONDARY_VIEW_ONLY" in r for r in health["degraded_reasons"]))

    def test_07_factory_paused(self):
        """Fábrica pausada marca o health status como DEGRADED."""
        operator_console.pause_factory(db_path=self.test_db_path)

        with patch("app.utils.utils.check_ffmpeg_ready", return_value=True):
            health = production_health.get_production_health(db_path=self.test_db_path)
            self.assertEqual(health["factory_state"], operator_console.FACTORY_STATE_PAUSED)
            self.assertEqual(health["status"], production_health.HEALTH_STATUS_DEGRADED)
            self.assertTrue(any("PAUSED" in r for r in health["degraded_reasons"]))

    def test_08_scheduler_unavailable_or_disabled(self):
        """Scheduler desabilitado ou com worker inativo marca o status como DEGRADED."""
        with patch("app.services.scheduler.is_worker_alive", return_value=False):
            with patch("app.services.scheduler.get_all_settings", return_value={"scheduler_enabled": False, "auto_publish_enabled": False, "dry_run": True}):
                with patch("app.utils.utils.check_ffmpeg_ready", return_value=True):
                    health = production_health.get_production_health(db_path=self.test_db_path)
                    self.assertEqual(health["status"], production_health.HEALTH_STATUS_DEGRADED)
                    self.assertFalse(health["scheduler"]["scheduler_enabled"])
                    self.assertFalse(health["scheduler"]["worker_alive"])

    def test_09_provider_health_included(self):
        """Verifica se os dados de provedores retornados por operator_console são incluídos."""
        health = production_health.get_production_health(db_path=self.test_db_path)
        self.assertIn("providers", health)
        self.assertIsInstance(health["providers"], dict)

    def test_10_readiness_check_success(self):
        """Verifica a checagem de prontidão (readiness check) técnica."""
        with patch("app.utils.utils.check_ffmpeg_ready", return_value=True):
            readiness = production_health.get_production_readiness(db_path=self.test_db_path)
            self.assertIn("ready", readiness)
            self.assertIn("checks", readiness)
            self.assertTrue(readiness["checks"]["python_runtime"]["passed"])
            self.assertTrue(readiness["checks"]["database"]["passed"])
            self.assertTrue(readiness["checks"]["storage"]["passed"])
            self.assertTrue(readiness["checks"]["ffmpeg"]["passed"])
            self.assertTrue(readiness["checks"]["scheduler_infra"]["passed"])

    def test_11_readiness_credentials_passive_and_masked(self):
        """Verifica que as credenciais são reportadas apenas como PRESENT ou MISSING."""
        readiness = production_health.get_production_readiness(db_path=self.test_db_path)
        creds = readiness["checks"]["credentials"]

        for k, v in creds.items():
            self.assertIn(v, {"PRESENT", "MISSING"})
            # Garante que nenhum valor de credencial real ou token vazou
            self.assertNotIn("AIza", str(v))
            self.assertNotIn("sk-", str(v))

    @patch("subprocess.run")
    @patch("urllib.request.urlopen")
    def test_12_zero_api_calls_and_zero_video_generation(self, mock_urlopen, mock_subproc):
        """Garante que tanto o health check quanto o readiness check realizam zero chamadas de rede e zero renders."""
        with patch("app.utils.utils.check_ffmpeg_ready", return_value=True):
            production_health.get_production_health(db_path=self.test_db_path)
            production_health.get_production_readiness(db_path=self.test_db_path)

        self.assertEqual(mock_urlopen.call_count, 0)
        self.assertEqual(mock_subproc.call_count, 0)


if __name__ == "__main__":
    unittest.main()
