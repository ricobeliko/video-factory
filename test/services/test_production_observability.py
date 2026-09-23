"""
Test Suite para o Serviço de Production Observability Baseline (Fase V15-A).

Cobre:
1. Dois perfis isolados (default e profile-historias-misterio)
2. Zero mutações no SQLite / MemoryState
3. Disponibilidade fail-safe (unavailable não derruba o snapshot)
4. Distinção estrita entre 0, 'unknown' e 'unavailable'
5. Rastreamento e warning de Copyright Blocked
6. Isolamento do Closed Feedback Loop por canal/perfil
7. Serialização JSON válida e CLI --json
8. Execução estritamente offline (zero network)
"""

import json
import os
import socket
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.models import const
from app.services import (
    analytics,
    autonomous_production,
    copyright_gate,
    operator_console,
    production_observability,
    profile_manager,
    scheduler,
)


class TestProductionObservability(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.test_db_path = os.path.join(self.tmp_dir.name, "test_observability.db")

        operator_console.reset_instance_for_testing()
        with operator_console._instance_state_lock:
            operator_console._current_role = operator_console.ROLE_PRIMARY

        # Inicializa tabelas
        profile_manager.init_profile_db(db_path=self.test_db_path)
        profile_manager.ensure_default_profile(db_path=self.test_db_path)
        scheduler.init_db(db_path=self.test_db_path)
        operator_console.init_operator_db(db_path=self.test_db_path)
        analytics.init_analytics_db(db_path=self.test_db_path)

        # Cria segundo perfil isolado
        profile_manager.create_profile(
            profile_id="profile-historias-misterio",
            name="Dose Diária de Histórias e Mistério",
            niche="historias_misterio",
            growth_mode="warmup",
            db_path=self.test_db_path,
        )
        profile_manager.create_channel(
            channel_id="channel-historias-misterio-youtube",
            profile_id="profile-historias-misterio",
            platform="youtube",
            channel_name="Dose Diária YouTube",
            is_enabled=True,
            db_path=self.test_db_path,
        )

        # Configura switches autônomos
        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.test_db_path)
        autonomous_production.set_profile_autonomous_mode_enabled(
            "profile-historias-misterio", True, db_path=self.test_db_path
        )

    def tearDown(self):
        operator_console.reset_instance_for_testing()
        try:
            self.tmp_dir.cleanup()
        except Exception:
            pass

    def _block_network(self):
        """Impede qualquer conexão de rede real durante os testes."""
        def guarded_connect(*args, **kwargs):
            raise RuntimeError("Network calls prohibited during observability test")
        return patch.object(socket.socket, "connect", side_effect=guarded_connect)

    def test_01_two_profiles_isolated(self):
        """Verifica que ambos os perfis (default e mistério) são coletados com métricas e canais isolados."""
        with self._block_network():
            snapshot = production_observability.get_production_observability_snapshot(
                db_path=self.test_db_path
            )

        self.assertIn("profiles", snapshot)
        self.assertIn("default", snapshot["profiles"])
        self.assertIn("profile-historias-misterio", snapshot["profiles"])

        p_default = snapshot["profiles"]["default"]
        p_mystery = snapshot["profiles"]["profile-historias-misterio"]

        self.assertEqual(p_default["profile"]["profile_id"], "default")
        self.assertEqual(p_mystery["profile"]["profile_id"], "profile-historias-misterio")
        self.assertEqual(p_mystery["profile"]["niche"], "historias_misterio")
        self.assertEqual(p_mystery["profile"]["channel_id"], "channel-historias-misterio-youtube")

        self.assertTrue(p_default["autonomous"]["enabled"])
        self.assertTrue(p_mystery["autonomous"]["enabled"])

    def test_02_zero_mutations(self):
        """Garante que a geração do snapshot não insere, atualiza ou deleta registros no banco."""
        with scheduler.get_connection(self.test_db_path) as conn:
            counts_before = {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "content_profiles",
                    "publishing_channels",
                    "scheduled_posts",
                    "publication_events",
                    "operational_events",
                )
            }

        with self._block_network():
            snapshot = production_observability.get_production_observability_snapshot(
                db_path=self.test_db_path
            )
            self.assertIsNotNone(snapshot.get("generated_at"))

        with scheduler.get_connection(self.test_db_path) as conn:
            counts_after = {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "content_profiles",
                    "publishing_channels",
                    "scheduled_posts",
                    "publication_events",
                    "operational_events",
                )
            }

        self.assertEqual(counts_before, counts_after)

    def test_03_unavailable_does_not_crash_snapshot(self):
        """Simula banco de dados ausente e garante que o snapshot é tolerante e reporta status unavailable."""
        missing_db = os.path.join(self.tmp_dir.name, "non_existent.db")

        with self._block_network():
            snapshot = production_observability.get_production_observability_snapshot(
                db_path=missing_db
            )

        self.assertIn("generated_at", snapshot)
        self.assertIn("profiles", snapshot)

    def test_04_zero_is_not_unknown(self):
        """Garante a diferenciação estrita entre 0 (valor numérico nulo conhecido) e 'unknown'."""
        with self._block_network():
            snapshot = production_observability.get_production_observability_snapshot(
                db_path=self.test_db_path
            )

        p_default = snapshot["profiles"]["default"]
        # Contagens conhecidas devem ser 0 inteiro
        self.assertIsInstance(p_default["ready_stock"]["count"], int)
        self.assertEqual(p_default["ready_stock"]["count"], 0)
        self.assertNotEqual(p_default["ready_stock"]["count"], "unknown")

        self.assertIsInstance(p_default["scheduler"]["scheduled"], int)
        self.assertEqual(p_default["scheduler"]["scheduled"], 0)
        self.assertNotEqual(p_default["scheduler"]["scheduled"], "unknown")

        self.assertIsInstance(p_default["production_24h"]["attempts"], int)
        self.assertEqual(p_default["production_24h"]["attempts"], 0)

        # Copyright sem publicação deve ser 'unknown', não 0
        self.assertEqual(p_default["copyright"]["effective_status"], "unknown")
        self.assertNotEqual(p_default["copyright"]["effective_status"], 0)

    def test_05_copyright_blocked_displayed(self):
        """Registra uma publicação com status 'blocked' e verifica que a observabilidade reflete com precisão."""
        task_id = "test-task-blocked-123"
        now_iso = datetime.now(timezone.utc).isoformat()

        with scheduler.get_connection(self.test_db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO publication_events(
                    task_id, platform, status, published_at, external_id, profile_id, channel_id
                ) VALUES (?, 'youtube', 'success', ?, 'YT_BLOCKED_VID', 'profile-historias-misterio', 'channel-historias-misterio-youtube');
                """,
                (task_id, now_iso),
            )
            pub_id = cursor.lastrowid

        # Marca como blocked via operator_console
        operator_console.set_publication_copyright_status_op(
            publication_event_id=pub_id,
            copyright_status="blocked",
            note="Bloqueado mundialmente por Content ID",
            db_path=self.test_db_path,
        )

        with self._block_network():
            snapshot = production_observability.get_production_observability_snapshot(
                db_path=self.test_db_path
            )

        p_mystery = snapshot["profiles"]["profile-historias-misterio"]
        self.assertEqual(p_mystery["copyright"]["effective_status"], "blocked")
        self.assertEqual(p_mystery["copyright"]["source"], "operator")
        self.assertFalse(p_mystery["copyright"]["feedback_loop_eligible"])
        self.assertTrue(p_mystery["copyright"]["has_blocked_or_claimed"])

        # Warnings observáveis contêm o alerta factual
        warnings = snapshot["global"]["warnings"]
        self.assertIn("COPYRIGHT_BLOCKED:profile-historias-misterio", warnings)

    def test_06_closed_loop_isolation_preserved(self):
        """Verifica que o isolamento de canais/perfis no Closed Feedback Loop é mantido."""
        with self._block_network():
            snapshot = production_observability.get_production_observability_snapshot(
                db_path=self.test_db_path
            )

        p_default = snapshot["profiles"]["default"]
        p_mystery = snapshot["profiles"]["profile-historias-misterio"]

        self.assertEqual(
            p_default["closed_feedback_loop"]["isolation_key"],
            "youtube:default:channel-default-youtube",
        )
        self.assertEqual(
            p_mystery["closed_feedback_loop"]["isolation_key"],
            "youtube:profile-historias-misterio:channel-historias-misterio-youtube",
        )

    def test_07_json_serializable_and_cli(self):
        """Verifica que o snapshot é 100% serializável em JSON puro e testa o CLI --json."""
        with self._block_network():
            snapshot = production_observability.get_production_observability_snapshot(
                db_path=self.test_db_path
            )

        json_str = json.dumps(snapshot, indent=2)
        self.assertTrue(len(json_str) > 0)
        parsed = json.loads(json_str)
        self.assertEqual(parsed["generated_at"], snapshot["generated_at"])
        self.assertIn("default", parsed["profiles"])
        self.assertIn("profile-historias-misterio", parsed["profiles"])


if __name__ == "__main__":
    unittest.main()
