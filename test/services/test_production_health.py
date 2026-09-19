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
from datetime import datetime, timedelta, timezone
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
        mock_backup = {
            "status": "HEALTHY",
            "latest_backup_at": "2026-09-19T12:00:00Z",
            "latest_backup_age_seconds": 300,
            "valid_backups_count": 1,
            "latest_integrity": "ok",
            "path": "dummy.db",
            "backup_dir": "storage/backups/database",
            "error": None,
        }
        with patch("app.services.scheduler.is_worker_alive", return_value=True):
            with patch("app.services.scheduler.get_all_settings", return_value={"scheduler_enabled": True, "auto_publish_enabled": True, "dry_run": False}):
                with patch("app.utils.utils.check_ffmpeg_ready", return_value=True):
                    with patch("app.services.production_backup.get_latest_backup_info", return_value=mock_backup):
                        health = production_health.get_production_health(db_path=self.test_db_path)

                        self.assertEqual(health["status"], production_health.HEALTH_STATUS_HEALTHY)
                        self.assertEqual(health["instance_role"], operator_console.ROLE_PRIMARY)
                        self.assertEqual(health["factory_state"], operator_console.FACTORY_STATE_RUNNING)
                        self.assertTrue(health["database"]["accessible"])
                        self.assertTrue(health["storage"]["writable"])
                        self.assertTrue(health["ffmpeg"]["available"])
                        self.assertEqual(health["backup"]["status"], production_health.HEALTH_STATUS_HEALTHY)
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

    def test_19_health_with_valid_recent_backup(self):
        """Verifica que com backup válido recente o status de backup é HEALTHY."""
        mock_b = {
            "status": "HEALTHY",
            "latest_backup_at": "2026-09-19T18:00:00Z",
            "latest_backup_age_seconds": 600,
            "valid_backups_count": 2,
            "latest_integrity": "ok",
            "path": "some_backup.db",
            "backup_dir": "storage/backups/database",
            "error": None,
        }
        with patch("app.services.production_backup.get_latest_backup_info", return_value=mock_b):
            health = production_health.get_production_health(db_path=self.test_db_path)
            self.assertEqual(health["backup"]["status"], production_health.HEALTH_STATUS_HEALTHY)
            self.assertEqual(health["backup"]["valid_backups_count"], 2)

    def test_20_health_without_backup_is_degraded_not_unhealthy(self):
        """Ausência de backup marca DEGRADED sem marcar UNHEALTHY e sem quebrar readiness."""
        mock_b = {
            "status": "NONE",
            "latest_backup_at": None,
            "latest_backup_age_seconds": None,
            "valid_backups_count": 0,
            "latest_integrity": None,
            "path": None,
            "backup_dir": "storage/backups/database",
            "error": None,
        }
        with patch("app.services.production_backup.get_latest_backup_info", return_value=mock_b):
            health = production_health.get_production_health(db_path=self.test_db_path)
            self.assertEqual(health["backup"]["status"], production_health.HEALTH_STATUS_DEGRADED)
            self.assertTrue(any("Nenhum backup" in r for r in health["degraded_reasons"]))
            self.assertEqual(len(health["unhealthy_reasons"]), 0)

            # Readiness check não deve ser bloqueado por ausência de backup inicial
            readiness = production_health.get_production_readiness(db_path=self.test_db_path)
            self.assertTrue(readiness["checks"]["backup"]["passed"])
            self.assertIn("backup", str(readiness["warnings"]).lower())

    def test_21_health_check_never_creates_or_modifies_backups(self):
        """Garante que health e readiness operam em modo passivo e nunca criam backups ou diretórios."""
        # Cenário 1: Diretório de backups inexistente NÃO deve ser criado pelo health check
        non_existent_b_dir = os.path.join(self.tmp_dir.name, "health_backup_dir_does_not_exist")
        self.assertFalse(os.path.exists(non_existent_b_dir))

        health_non_exist = production_health.get_production_health(
            db_path=self.test_db_path,
            backup_dir=non_existent_b_dir,
        )
        self.assertFalse(
            os.path.exists(non_existent_b_dir),
            "get_production_health() criou indevidamente o diretório de backups!",
        )
        self.assertEqual(health_non_exist["backup"]["status"], production_health.HEALTH_STATUS_DEGRADED)

        # Cenário 2: Diretório existente deve permanecer estritamente intocado e vazio
        test_b_dir = os.path.join(self.tmp_dir.name, "health_backups_passive")
        os.makedirs(test_b_dir, exist_ok=True)

        health = production_health.get_production_health(db_path=self.test_db_path, backup_dir=test_b_dir)
        readiness = production_health.get_production_readiness(db_path=self.test_db_path)

        # Diretório deve continuar estritamente vazio
        files = os.listdir(test_b_dir)
        self.assertEqual(len(files), 0, f"Health check criou arquivos indevidamente: {files}")

    def test_22_status_sanitization_zero_secrets(self):
        """Garante que o diagnóstico sanitizado de produção não expõe segredos ou chaves reais."""
        import io
        import json
        from contextlib import redirect_stdout

        secret_value = "SECRET_API_KEY_SUPER_CONFIDENTIAL_123456"
        with patch.dict("app.config.config.app", {"gemini_api_key": secret_value}):
            readiness = production_health.get_production_readiness(db_path=self.test_db_path)
            creds = readiness["checks"]["credentials"]
            self.assertEqual(creds["gemini_api_key"], "PRESENT")
            self.assertNotIn(secret_value, json.dumps(readiness))

            # Execução de CLI via main() com redirect de stdout
            f = io.StringIO()
            with redirect_stdout(f), patch("sys.argv", ["production_health", "--readiness"]):
                try:
                    production_health.main()
                except SystemExit:
                    pass
            cli_output = f.getvalue()
            self.assertNotIn(secret_value, cli_output)
            self.assertIn("PRESENT", cli_output)

    def test_23_worker_health_in_process_thread(self):
        """1. is_worker_alive() True => worker_alive True / source in_process_thread."""
        with patch("app.services.scheduler.is_worker_alive", return_value=True):
            health = production_health.get_production_health(db_path=self.test_db_path)
            s = health["scheduler"]
            self.assertTrue(s["worker_alive"])
            self.assertEqual(s["worker_health_source"], scheduler.WORKER_SOURCE_IN_PROCESS_THREAD)

    def test_24_worker_health_persisted_heartbeat_recent(self):
        """2. is_worker_alive() False + executor_last_tick recente => worker_alive True / source persisted_heartbeat."""
        now_utc = datetime.now(timezone.utc)
        recent_iso = (now_utc - timedelta(seconds=15)).isoformat()
        scheduler.set_setting("executor_last_tick", recent_iso, db_path=self.test_db_path)
        scheduler.set_setting("scheduler_enabled", "true", db_path=self.test_db_path)

        with patch("app.services.scheduler.is_worker_alive", return_value=False):
            health = production_health.get_production_health(db_path=self.test_db_path)
            s = health["scheduler"]
            self.assertTrue(s["worker_alive"])
            self.assertEqual(s["worker_health_source"], scheduler.WORKER_SOURCE_PERSISTED_HEARTBEAT)
            self.assertEqual(s["worker_last_tick"], recent_iso)
            self.assertIsNotNone(s["worker_last_tick_age_seconds"])
            self.assertLessEqual(s["worker_last_tick_age_seconds"], 25)
            self.assertNotIn("Thread do scheduler worker inativa na instância primária", health["degraded_reasons"])

    def test_25_worker_health_heartbeat_stale_exceeds_threshold(self):
        """3. Heartbeat maior que threshold (>90s) => worker_alive False / source unavailable."""
        now_utc = datetime.now(timezone.utc)
        stale_iso = (now_utc - timedelta(seconds=120)).isoformat()
        scheduler.set_setting("executor_last_tick", stale_iso, db_path=self.test_db_path)
        scheduler.set_setting("scheduler_enabled", "true", db_path=self.test_db_path)

        with patch("app.services.scheduler.is_worker_alive", return_value=False):
            health = production_health.get_production_health(db_path=self.test_db_path)
            s = health["scheduler"]
            self.assertFalse(s["worker_alive"])
            self.assertEqual(s["worker_health_source"], scheduler.WORKER_SOURCE_UNAVAILABLE)
            self.assertEqual(s["worker_last_tick"], stale_iso)
            self.assertGreaterEqual(s["worker_last_tick_age_seconds"], 120)
            self.assertIn("Thread do scheduler worker inativa na instância primária", health["degraded_reasons"])

    def test_26_worker_health_heartbeat_missing(self):
        """4. Heartbeat ausente => worker_alive False / source unavailable."""
        with scheduler.get_connection(self.test_db_path) as conn:
            conn.execute("DELETE FROM autopilot_settings WHERE key = 'executor_last_tick';")

        with patch("app.services.scheduler.is_worker_alive", return_value=False):
            health = production_health.get_production_health(db_path=self.test_db_path)
            s = health["scheduler"]
            self.assertFalse(s["worker_alive"])
            self.assertEqual(s["worker_health_source"], scheduler.WORKER_SOURCE_UNAVAILABLE)
            self.assertIsNone(s["worker_last_tick"])
            self.assertIsNone(s["worker_last_tick_age_seconds"])

    def test_27_worker_health_heartbeat_invalid_no_crash(self):
        """5. Heartbeat inválido => worker_alive False sem crash."""
        scheduler.set_setting("executor_last_tick", "NOT_A_VALID_ISO_TIMESTAMP_GARBAGE", db_path=self.test_db_path)

        with patch("app.services.scheduler.is_worker_alive", return_value=False):
            health = production_health.get_production_health(db_path=self.test_db_path)
            s = health["scheduler"]
            self.assertFalse(s["worker_alive"])
            self.assertEqual(s["worker_health_source"], scheduler.WORKER_SOURCE_UNAVAILABLE)
            self.assertEqual(s["worker_last_tick"], "NOT_A_VALID_ISO_TIMESTAMP_GARBAGE")
            self.assertIsNone(s["worker_last_tick_age_seconds"])

    def test_28_factory_paused_with_recent_heartbeat(self):
        """6. Factory PAUSED + heartbeat recente => DEGRADED por factory PAUSED mas NÃO por worker inativo."""
        operator_console.pause_factory(db_path=self.test_db_path)
        scheduler.set_setting("scheduler_enabled", "true", db_path=self.test_db_path)
        recent_iso = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        scheduler.set_setting("executor_last_tick", recent_iso, db_path=self.test_db_path)

        with patch("app.services.scheduler.is_worker_alive", return_value=False):
            health = production_health.get_production_health(db_path=self.test_db_path)
            self.assertEqual(health["factory_state"], operator_console.FACTORY_STATE_PAUSED)
            self.assertTrue(health["scheduler"]["worker_alive"])
            self.assertEqual(health["scheduler"]["worker_health_source"], scheduler.WORKER_SOURCE_PERSISTED_HEARTBEAT)
            self.assertEqual(health["status"], production_health.HEALTH_STATUS_DEGRADED)
            self.assertTrue(any("PAUSED" in r for r in health["degraded_reasons"]))
            self.assertFalse(any("worker inativ" in r.lower() for r in health["degraded_reasons"]))

    def test_29_health_check_read_only_passivity_with_nonexistent_db(self):
        """7. Health permanece 100% read-only mesmo quando o banco ou tabelas não existem."""
        non_existent_db = os.path.join(self.tmp_dir.name, "strictly_missing_health_test.db")
        self.assertFalse(os.path.exists(non_existent_db))

        health = production_health.get_production_health(db_path=non_existent_db)
        self.assertFalse(os.path.exists(non_existent_db), "get_production_health() criou o banco indevidamente!")
        self.assertFalse(health["scheduler"]["worker_alive"])
        self.assertEqual(health["scheduler"]["worker_health_source"], scheduler.WORKER_SOURCE_UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
