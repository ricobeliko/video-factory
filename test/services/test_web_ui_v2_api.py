"""Testes da API V2 Channels Overview para Web UI V2.

Valida:
1. Existência da rota /api/v2/channels no OpenAPI e no FastAPI com método GET;
2. Comportamento read-only (chamada GET não muta estado persistido);
3. Estrutura e integridade da resposta com perfis/canais cadastrados;
4. Resposta tratada com lista vazia quando nenhum canal existe;
5. Ausência de segredos ou credenciais na resposta;
6. Aplicação de autenticação canônica via verify_token quando api_key configurada.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import asgi
from app.config import config
from app.services import operator_console, profile_manager, scheduler


class TestWebUiV2Api(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_v2_channels.db")
        config.app["api_key"] = ""

        # Inicializa o banco temporário
        scheduler.init_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        profile_manager.ensure_default_profile(self.db_path)
        operator_console.init_operator_db(self.db_path)

        self.client = TestClient(asgi.app)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)
        self.temp_dir.cleanup()

    def test_channels_route_exists_in_openapi_and_app(self):
        """1. Rota /api/v2/channels existe no OpenAPI e suporta GET."""
        openapi_schema = asgi.app.openapi()
        paths = openapi_schema.get("paths", {})

        self.assertIn("/api/v2/channels", paths, "Rota /api/v2/channels não encontrada no OpenAPI")
        self.assertIn("get", paths["/api/v2/channels"], "Método GET não encontrado para /api/v2/channels")

    def test_channels_get_does_not_mutate_state(self):
        """2. Executar GET /api/v2/channels é estritamente read-only e não muta o estado persistido."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path):

            with scheduler.get_connection(self.db_path) as conn:
                posts_count_before = conn.execute("SELECT COUNT(*) FROM scheduled_posts;").fetchone()[0]
                pubs_count_before = conn.execute("SELECT COUNT(*) FROM publication_events;").fetchone()[0]

            with profile_manager.get_connection(self.db_path) as conn:
                profiles_count_before = conn.execute("SELECT COUNT(*) FROM content_profiles;").fetchone()[0]

            resp = self.client.get("/api/v2/channels")
            self.assertEqual(resp.status_code, 200)

            with scheduler.get_connection(self.db_path) as conn:
                posts_count_after = conn.execute("SELECT COUNT(*) FROM scheduled_posts;").fetchone()[0]
                pubs_count_after = conn.execute("SELECT COUNT(*) FROM publication_events;").fetchone()[0]

            with profile_manager.get_connection(self.db_path) as conn:
                profiles_count_after = conn.execute("SELECT COUNT(*) FROM content_profiles;").fetchone()[0]

            self.assertEqual(posts_count_before, posts_count_after)
            self.assertEqual(pubs_count_before, pubs_count_after)
            self.assertEqual(profiles_count_before, profiles_count_after)

    def test_channels_overview_returns_expected_structure(self):
        """3. Retorna visão consolidada dos canais com campos operacionais serializáveis."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path):

            resp = self.client.get("/api/v2/channels")
            self.assertEqual(resp.status_code, 200)

            body = resp.json()
            self.assertEqual(body.get("status"), 200)
            data = body.get("data", {})
            self.assertIn("channels", data)
            self.assertIn("total", data)
            self.assertGreaterEqual(data["total"], 1)

            channel = data["channels"][0]
            expected_keys = [
                "channel_id",
                "profile_id",
                "name",
                "slug",
                "niche",
                "language",
                "growth_mode",
                "is_active",
                "is_active_profile",
                "autonomous_enabled",
                "target_stock",
                "ready_stock",
                "pending_processing",
                "scheduled",
                "failed",
                "channels_count",
                "channels_enabled",
                "channels",
                "settings",
            ]
            for key in expected_keys:
                self.assertIn(key, channel, f"Campo esperado ausente: {key}")

    def test_channels_overview_empty_response(self):
        """4. Quando não existem perfis/canais, retorna lista vazia com total 0 sem erro."""
        with patch("app.services.operator_console.get_profile_operations_overview", return_value=[]):
            resp = self.client.get("/api/v2/channels")
            self.assertEqual(resp.status_code, 200)

            body = resp.json()
            data = body.get("data", {})
            self.assertEqual(data.get("channels"), [])
            self.assertEqual(data.get("total"), 0)

    def test_channels_overview_does_not_expose_secrets(self):
        """5. Resposta não expõe tokens, senhas ou chaves de API sensíveis."""
        config.app["gemini_api_key"] = "SUPER_SECRET_GEMINI_KEY_CHANNELS"
        config.app["pexels_api_keys"] = ["SUPER_SECRET_PEXELS_KEY_CHANNELS"]

        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path):

            resp = self.client.get("/api/v2/channels")
            self.assertEqual(resp.status_code, 200)
            text = resp.text

            self.assertNotIn("SUPER_SECRET_GEMINI_KEY_CHANNELS", text)
            self.assertNotIn("SUPER_SECRET_PEXELS_KEY_CHANNELS", text)

    def test_verify_token_enforced_on_channels(self):
        """6. verify_token é aplicado no endpoint /api/v2/channels quando api_key configurada."""
        config.app["api_key"] = "test-secret-key-channels-v2"

        # Sem token -> 401
        resp_missing = self.client.get("/api/v2/channels")
        self.assertEqual(resp_missing.status_code, 401)

        # Token inválido -> 401
        resp_wrong = self.client.get("/api/v2/channels", headers={"x-api-key": "invalid-key"})
        self.assertEqual(resp_wrong.status_code, 401)

        # Token correto -> passa (200)
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path):

            resp_ok = self.client.get("/api/v2/channels", headers={"x-api-key": "test-secret-key-channels-v2"})
            self.assertEqual(resp_ok.status_code, 200)

    def test_factory_endpoints_exist_in_openapi_and_app(self):
        """7. Rotas POST /api/v2/factory/pause e /api/v2/factory/resume existem no OpenAPI."""
        openapi_schema = asgi.app.openapi()
        paths = openapi_schema.get("paths", {})

        self.assertIn("/api/v2/factory/pause", paths)
        self.assertIn("post", paths["/api/v2/factory/pause"])

        self.assertIn("/api/v2/factory/resume", paths)
        self.assertIn("post", paths["/api/v2/factory/resume"])

    def test_factory_pause_and_resume_auth_enforced(self):
        """8. Requisições sem autenticação ou com chave inválida são rejeitadas (401)."""
        config.app["api_key"] = "test-secret-key-factory"

        # Pause sem token / token inválido
        r_pause_miss = self.client.post("/api/v2/factory/pause")
        self.assertEqual(r_pause_miss.status_code, 401)
        r_pause_wrong = self.client.post("/api/v2/factory/pause", headers={"x-api-key": "wrong"})
        self.assertEqual(r_pause_wrong.status_code, 401)

        # Resume sem token / token inválido
        r_resume_miss = self.client.post("/api/v2/factory/resume")
        self.assertEqual(r_resume_miss.status_code, 401)
        r_resume_wrong = self.client.post("/api/v2/factory/resume", headers={"x-api-key": "wrong"})
        self.assertEqual(r_resume_wrong.status_code, 401)

    def test_factory_pause_calls_operation_once(self):
        """9. Pause chama operator_console.pause_factory exatamente uma vez."""
        with patch("app.services.operator_console.pause_factory") as mock_pause, \
             patch("app.services.operator_console.get_factory_state", return_value="PAUSED"), \
             patch("app.services.operator_console.is_factory_paused", return_value=True):

            resp = self.client.post("/api/v2/factory/pause")
            self.assertEqual(resp.status_code, 200)
            mock_pause.assert_called_once_with()

            data = resp.json().get("data", {})
            self.assertEqual(data.get("factory_state"), "PAUSED")
            self.assertEqual(data.get("is_paused"), True)

    def test_factory_resume_calls_operation_once(self):
        """10. Resume chama operator_console.resume_factory exatamente uma vez."""
        with patch("app.services.operator_console.resume_factory") as mock_resume, \
             patch("app.services.operator_console.get_factory_state", return_value="RUNNING"), \
             patch("app.services.operator_console.is_factory_paused", return_value=False):

            resp = self.client.post("/api/v2/factory/resume")
            self.assertEqual(resp.status_code, 200)
            mock_resume.assert_called_once_with()

            data = resp.json().get("data", {})
            self.assertEqual(data.get("factory_state"), "RUNNING")
            self.assertEqual(data.get("is_paused"), False)

    def test_factory_pause_and_resume_operational_failure_returns_controlled_error(self):
        """11. Falha operacional interna retorna erro controlado (500) sem vazar detalhes sensíveis."""
        with patch("app.services.operator_console.pause_factory", side_effect=RuntimeError("internal sqlite lock failure")):
            resp_pause = self.client.post("/api/v2/factory/pause")
            self.assertEqual(resp_pause.status_code, 500)
            self.assertNotIn("internal sqlite lock failure", resp_pause.text)
            self.assertNotIn("Traceback", resp_pause.text)

        with patch("app.services.operator_console.resume_factory", side_effect=RuntimeError("internal sqlite lock failure")):
            resp_resume = self.client.post("/api/v2/factory/resume")
            self.assertEqual(resp_resume.status_code, 500)
            self.assertNotIn("internal sqlite lock failure", resp_resume.text)
            self.assertNotIn("Traceback", resp_resume.text)

    def test_factory_pause_and_resume_blocked_on_unauthorized_environment(self):
        """12. Ambiente não autorizado (VIEW ONLY / SECONDARY) é bloqueado com 403."""
        with patch("app.services.operator_console.pause_factory", side_effect=PermissionError("Operação bloqueada: VIEW ONLY")):
            resp_pause = self.client.post("/api/v2/factory/pause")
            self.assertEqual(resp_pause.status_code, 403)
            self.assertIn("only primary instance", resp_pause.json().get("message", "").lower())

        with patch("app.services.operator_console.resume_factory", side_effect=PermissionError("Operação bloqueada: VIEW ONLY")):
            resp_resume = self.client.post("/api/v2/factory/resume")
            self.assertEqual(resp_resume.status_code, 403)
            self.assertIn("only primary instance", resp_resume.json().get("message", "").lower())

    def test_factory_run_cycle_exists_in_openapi_and_app(self):
        """13. Rota POST /api/v2/factory/run-cycle existe no OpenAPI e suporta POST."""
        openapi_schema = asgi.app.openapi()
        paths = openapi_schema.get("paths", {})

        self.assertIn("/api/v2/factory/run-cycle", paths)
        self.assertIn("post", paths["/api/v2/factory/run-cycle"])

    def test_factory_run_cycle_auth_enforced(self):
        """14. Requisições a run-cycle sem autenticação ou com chave inválida são rejeitadas (401)."""
        config.app["api_key"] = "test-secret-key-cycle"

        # Sem token -> 401
        r_miss = self.client.post("/api/v2/factory/run-cycle")
        self.assertEqual(r_miss.status_code, 401)

        # Token inválido -> 401
        r_wrong = self.client.post("/api/v2/factory/run-cycle", headers={"x-api-key": "invalid-token"})
        self.assertEqual(r_wrong.status_code, 401)

        # Token correto -> passa
        with patch("app.services.operator_console.run_autonomous_cycle_op", return_value={"status": "idle"}):
            r_ok = self.client.post(
                "/api/v2/factory/run-cycle",
                headers={"x-api-key": "test-secret-key-cycle"},
            )
            self.assertEqual(r_ok.status_code, 200)

    def test_factory_run_cycle_delegates_to_canonical_operation(self):
        """15. run-cycle delega a operator_console.run_autonomous_cycle_op com parâmetros corretos."""
        with patch("app.services.operator_console.run_autonomous_cycle_op") as mock_op:
            mock_op.return_value = {
                "status": "idle",
                "message": "Ciclo supervisionado executado",
                "profile_id": "test-prof-1",
            }

            # Chamada sem corpo (defaults: force=True, one_shot=True, profile_id=None, channel_id=None)
            resp = self.client.post("/api/v2/factory/run-cycle")
            self.assertEqual(resp.status_code, 200)
            mock_op.assert_called_once_with(
                force=True,
                one_shot=True,
                profile_id=None,
                channel_id=None,
            )
            mock_op.reset_mock()

            # Chamada com corpo JSON explícito
            resp_body = self.client.post(
                "/api/v2/factory/run-cycle",
                json={
                    "profile_id": "custom-prof",
                    "channel_id": "custom-chan",
                    "force": False,
                    "one_shot": True,
                },
            )
            self.assertEqual(resp_body.status_code, 200)
            mock_op.assert_called_once_with(
                force=False,
                one_shot=True,
                profile_id="custom-prof",
                channel_id="custom-chan",
            )

    def test_factory_run_cycle_blocked_on_unauthorized_environment(self):
        """16. Instância secundária (VIEW ONLY) é bloqueada com status 403."""
        with patch(
            "app.services.operator_console.run_autonomous_cycle_op",
            side_effect=PermissionError("Operação bloqueada: Esta instância está operando em modo VIEW ONLY."),
        ):
            resp = self.client.post("/api/v2/factory/run-cycle")
            self.assertEqual(resp.status_code, 403)
            self.assertIn("only primary instance", resp.json().get("message", "").lower())

    def test_factory_run_cycle_concurrency_guard_returns_409(self):
        """17. Ciclo concorrente em andamento é bloqueado com 409 Conflict."""
        with patch(
            "app.services.operator_console.run_autonomous_cycle_op",
            return_value={"status": "busy", "reason": "cycle_in_progress"},
        ):
            resp = self.client.post("/api/v2/factory/run-cycle")
            self.assertEqual(resp.status_code, 409)
            self.assertIn("already in progress", resp.json().get("message", "").lower())

    def test_factory_run_cycle_paused_guard_returns_409(self):
        """18. Fábrica pausada bloqueia disparo de ciclo com 409 Conflict."""
        with patch(
            "app.services.operator_console.run_autonomous_cycle_op",
            return_value={"status": "blocked", "reason": "factory_paused", "message": "Fábrica pausada"},
        ):
            resp = self.client.post("/api/v2/factory/run-cycle")
            self.assertEqual(resp.status_code, 409)
            self.assertIn("factory is paused", resp.json().get("message", "").lower())

    def test_factory_run_cycle_operational_failure_returns_controlled_error(self):
        """19. Erro operacional interno retorna 500 sem vazar dados sensíveis ou stack trace."""
        with patch(
            "app.services.operator_console.run_autonomous_cycle_op",
            side_effect=RuntimeError("internal sqlite lock failure with sensitive table path"),
        ):
            resp = self.client.post("/api/v2/factory/run-cycle")
            self.assertEqual(resp.status_code, 500)
            self.assertNotIn("internal sqlite lock failure", resp.text)
            self.assertNotIn("Traceback", resp.text)
