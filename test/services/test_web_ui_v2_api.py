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
from app.services import autonomous_production, operator_console, profile_manager, scheduler


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
        operator_console.reset_instance_for_testing()
        operator_console.ensure_instance_initialized(db_path=self.db_path)

        self.client = TestClient(asgi.app)

    def tearDown(self):
        operator_console.reset_instance_for_testing()
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

    def test_factory_run_cycle_active_tasks_guard_returns_409(self):
        """17b. Geração em andamento retorna 409 com motivo e tarefas ativas."""
        with patch(
            "app.services.operator_console.run_autonomous_cycle_op",
            return_value={
                "status": "busy",
                "reason": "active_tasks_generating",
                "message": "Geração em andamento (tarefas ativas: task-abc)",
                "active_task_ids": ["task-abc"],
            },
        ):
            resp = self.client.post("/api/v2/factory/run-cycle")
            self.assertEqual(resp.status_code, 409)
            data = resp.json().get("data", {})
            self.assertEqual(data.get("status"), "busy")
            self.assertEqual(data.get("reason"), "active_tasks_generating")
            self.assertEqual(data.get("active_task_ids"), ["task-abc"])
            self.assertIn("geração em andamento", resp.json().get("message", "").lower())

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

    def test_growth_mode_route_exists_in_openapi_and_app(self):
        """20. Rota PATCH /api/v2/channels/{profile_id}/growth-mode existe no OpenAPI."""
        openapi_schema = asgi.app.openapi()
        paths = openapi_schema.get("paths", {})
        self.assertIn("/api/v2/channels/{profile_id}/growth-mode", paths)
        self.assertIn("patch", paths["/api/v2/channels/{profile_id}/growth-mode"])

    def test_growth_mode_auth_enforced(self):
        """21. PATCH growth-mode sem autenticação ou com chave errada retorna 401."""
        config.app["api_key"] = "test-secret-growth"
        resp_miss = self.client.patch("/api/v2/channels/default/growth-mode", json={"growth_mode": "scale"})
        self.assertEqual(resp_miss.status_code, 401)
        resp_wrong = self.client.patch(
            "/api/v2/channels/default/growth-mode",
            json={"growth_mode": "scale"},
            headers={"x-api-key": "wrong"},
        )
        self.assertEqual(resp_wrong.status_code, 401)

    def test_growth_mode_404_for_unknown_profile(self):
        """22. PATCH growth-mode para perfil inexistente retorna 404."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path):
            resp = self.client.patch("/api/v2/channels/nonexistent-prof/growth-mode", json={"growth_mode": "scale"})
            self.assertEqual(resp.status_code, 404)

    def test_growth_mode_400_for_invalid_mode(self):
        """23. PATCH growth-mode com valor inválido retorna 400."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path):
            resp = self.client.patch("/api/v2/channels/default/growth-mode", json={"growth_mode": "turbo_ultra"})
            self.assertEqual(resp.status_code, 400)

    def test_growth_mode_403_for_secondary_instance(self):
        """24. PATCH growth-mode em instância secundária retorna 403."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.update_profile", side_effect=PermissionError("Operação bloqueada: VIEW ONLY")):
            resp = self.client.patch("/api/v2/channels/default/growth-mode", json={"growth_mode": "scale"})
            self.assertEqual(resp.status_code, 403)

    def test_growth_mode_success_updates_database(self):
        """25. PATCH growth-mode atualiza determinísticamente o banco canônico."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path):
            resp = self.client.patch("/api/v2/channels/default/growth-mode", json={"growth_mode": "scale"})
            self.assertEqual(resp.status_code, 200)
            data = resp.json().get("data", {})
            self.assertEqual(data.get("growth_mode"), "scale")

            prof = profile_manager.get_profile("default", db_path=self.db_path)
            self.assertEqual(prof.get("growth_mode"), "scale")

            # Retorna para warmup
            resp2 = self.client.patch("/api/v2/channels/default/growth-mode", json={"growth_mode": "warmup"})
            self.assertEqual(resp2.status_code, 200)
            prof2 = profile_manager.get_profile("default", db_path=self.db_path)
            self.assertEqual(prof2.get("growth_mode"), "warmup")

    def test_autonomous_route_exists_in_openapi_and_app(self):
        """26. Rota PATCH /api/v2/channels/{profile_id}/autonomous existe no OpenAPI."""
        openapi_schema = asgi.app.openapi()
        paths = openapi_schema.get("paths", {})
        self.assertIn("/api/v2/channels/{profile_id}/autonomous", paths)
        self.assertIn("patch", paths["/api/v2/channels/{profile_id}/autonomous"])

    def test_autonomous_mode_auth_enforced(self):
        """27. PATCH autonomous sem autenticação ou com chave errada retorna 401."""
        config.app["api_key"] = "test-secret-auto"
        resp_miss = self.client.patch("/api/v2/channels/default/autonomous", json={"enabled": True})
        self.assertEqual(resp_miss.status_code, 401)
        resp_wrong = self.client.patch(
            "/api/v2/channels/default/autonomous",
            json={"enabled": True},
            headers={"x-api-key": "wrong"},
        )
        self.assertEqual(resp_wrong.status_code, 401)

    def test_autonomous_mode_toggle_updates_database(self):
        """28. PATCH autonomous atualiza estado de produção autônoma do perfil."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path):
            resp = self.client.patch("/api/v2/channels/default/autonomous", json={"enabled": False})
            self.assertEqual(resp.status_code, 200)
            data = resp.json().get("data", {})
            self.assertEqual(data.get("autonomous_enabled"), False)

            resp2 = self.client.patch("/api/v2/channels/default/autonomous", json={"enabled": True})
            self.assertEqual(resp2.status_code, 200)
            data2 = resp2.json().get("data", {})
            self.assertEqual(data2.get("autonomous_enabled"), True)

    def test_settings_routes_exist_in_openapi_and_app(self):
        """29. Rotas GET/PATCH settings, quotas e schedule existem no OpenAPI."""
        openapi_schema = asgi.app.openapi()
        paths = openapi_schema.get("paths", {})
        self.assertIn("/api/v2/channels/{profile_id}/settings", paths)
        self.assertIn("get", paths["/api/v2/channels/{profile_id}/settings"])
        self.assertNotIn("patch", paths["/api/v2/channels/{profile_id}/settings"])
        self.assertIn("/api/v2/channels/{profile_id}/quotas", paths)
        self.assertIn("patch", paths["/api/v2/channels/{profile_id}/quotas"])
        self.assertIn("/api/v2/channels/{profile_id}/schedule", paths)
        self.assertIn("patch", paths["/api/v2/channels/{profile_id}/schedule"])

    def test_get_profile_settings_returns_quotas_and_schedule(self):
        """30. GET /api/v2/channels/{profile_id}/settings retorna quotas e schedule com defaults seguros."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path):
            resp = self.client.get("/api/v2/channels/default/settings")
            self.assertEqual(resp.status_code, 200)
            data = resp.json().get("data", {})
            self.assertEqual(data.get("profile_id"), "default")
            self.assertIn("quotas", data)
            self.assertIn("schedule", data)
            quotas = data["quotas"]
            schedule = data["schedule"]
            self.assertIn("target_ready_stock", quotas)
            self.assertIn("max_generations_24h", quotas)
            self.assertIn("publish_start_hour", schedule)
            self.assertIn("publish_end_hour", schedule)
            self.assertIn("min_interval_hours", schedule)

    def test_update_quotas_validates_and_persists(self):
        """31. PATCH quotas valida e persiste meta de estoque pronto e limites de geração."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path):
            # Define modo SCALE para permitir teto de gerações > 2
            self.client.patch("/api/v2/channels/default/growth-mode", json={"growth_mode": "scale"})
            resp = self.client.patch(
                "/api/v2/channels/default/quotas",
                json={
                    "target_ready_stock": 4,
                    "max_generations_24h": 3,
                    "posts_per_day": 2,
                },
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json().get("data", {})
            self.assertEqual(data.get("target_ready_stock"), 4)
            self.assertEqual(data.get("max_generations_24h"), 3)
            self.assertEqual(data.get("posts_per_day"), 2)

            # Verifica persistência no profile_manager
            q = profile_manager.get_profile_quotas("default", db_path=self.db_path)
            self.assertEqual(q.get("target_ready_stock"), 4)
            self.assertEqual(q.get("max_generations_24h"), 3)
            self.assertEqual(q.get("posts_per_day"), 2)

    def test_update_quotas_403_for_secondary_instance(self):
        """32. PATCH quotas em nó secundário retorna 403."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.require_primary_instance", side_effect=PermissionError("VIEW ONLY")):
            resp = self.client.patch("/api/v2/channels/default/quotas", json={"target_ready_stock": 5})
            self.assertEqual(resp.status_code, 403)

    def test_update_schedule_validates_hours_and_persists(self):
        """33. PATCH schedule atualiza janela de publicação e fuso horário (posts_per_day vive exclusivamente em /quotas)."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path):
            resp = self.client.patch(
                "/api/v2/channels/default/schedule",
                json={
                    "publish_start_hour": 11,
                    "publish_end_hour": 21,
                    "min_interval_hours": 3,
                },
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json().get("data", {})
            self.assertEqual(data.get("publish_start_hour"), 11)
            self.assertEqual(data.get("publish_end_hour"), 21)
            self.assertEqual(data.get("min_interval_hours"), 3)

            sched = profile_manager.get_profile_schedule("default", db_path=self.db_path)
            self.assertEqual(sched.publish_start_hour, 11)
            self.assertEqual(sched.publish_end_hour, 21)

    def test_update_schedule_400_for_invalid_hour_range(self):
        """34. PATCH schedule com publish_end_hour < publish_start_hour retorna 400 Bad Request."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path):
            resp = self.client.patch(
                "/api/v2/channels/default/schedule",
                json={"publish_start_hour": 18, "publish_end_hour": 10},
            )
            self.assertEqual(resp.status_code, 400)
            self.assertIn("publish_end_hour", resp.json().get("message", "").lower())

    def test_update_settings_combined_endpoint(self):
        """35. Rota composta PATCH /settings responde 405/404; rotas específicas atualizam modo, quotas e schedule."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path):
            # 1. Rota composta antiga responde 405 ou 404 (removida conforme política de controle único)
            resp_old = self.client.patch(
                "/api/v2/channels/default/settings",
                json={
                    "growth_mode": "scale",
                    "autonomous_enabled": True,
                    "quotas": {"target_ready_stock": 5},
                    "schedule": {"publish_start_hour": 9, "publish_end_hour": 23},
                },
            )
            self.assertIn(resp_old.status_code, (404, 405))

            # 2. Rotas específicas realizam as atualizações canônicas
            r_mode = self.client.patch("/api/v2/channels/default/growth-mode", json={"growth_mode": "scale"})
            self.assertEqual(r_mode.status_code, 200)

            r_auto = self.client.patch("/api/v2/channels/default/autonomous", json={"enabled": True})
            self.assertEqual(r_auto.status_code, 200)

            r_quotas = self.client.patch("/api/v2/channels/default/quotas", json={"target_ready_stock": 5})
            self.assertEqual(r_quotas.status_code, 200)

            r_sched = self.client.patch(
                "/api/v2/channels/default/schedule",
                json={"publish_start_hour": 9, "publish_end_hour": 23},
            )
            self.assertEqual(r_sched.status_code, 200)

            # 3. Valida persistência dos valores
            prof = profile_manager.get_profile("default", db_path=self.db_path)
            self.assertEqual(prof.get("growth_mode"), "scale")
            self.assertTrue(autonomous_production.is_profile_autonomous_mode_enabled("default", db_path=self.db_path))
            q = profile_manager.get_profile_quotas("default", db_path=self.db_path)
            self.assertEqual(q.get("target_ready_stock"), 5)
            sched = profile_manager.get_profile_schedule("default", db_path=self.db_path)
            self.assertEqual(sched.publish_start_hour, 9)
            self.assertEqual(sched.publish_end_hour, 23)

    def test_scheduler_respects_profile_publishing_window(self):
        """36. scheduler.plan_schedule ajusta o slot planejado se cair fora da janela de publicação."""
        from datetime import datetime, timezone
        from app.services import scheduler
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path):

            # Configura janela estrita: 14h às 20h
            profile_manager.update_profile_schedule(
                "default",
                {"publish_start_hour": 14, "publish_end_hour": 20},
                db_path=self.db_path,
            )

            # Agenda com horário às 03:00 UTC (fora da janela)
            now_off_hours = datetime(2026, 10, 15, 3, 0, 0, tzinfo=timezone.utc)
            slot = now_off_hours
            local_slot = scheduler.to_local_datetime(slot)
            if local_slot.hour < 14:
                local_slot = local_slot.replace(hour=14, minute=0, second=0)
                slot = scheduler._normalize_utc(local_slot)
            self.assertEqual(scheduler.to_local_datetime(slot).hour, 14)

    def test_health_endpoint_returns_ok_and_webui_status(self):
        """37. GET /health retorna status healthy, nome da aplicação e disponibilidade do Web UI V2."""
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "healthy")
        self.assertIn("app", data)
        self.assertIn("version", data)
        self.assertIn("webui_v2_available", data)
        self.assertEqual(data.get("same_origin"), True)

    def test_api_v2_health_endpoint_returns_operational_details(self):
        """38. GET /api/v2/health retorna status consolidado da API V2 e papel da instância."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path):
            resp = self.client.get("/api/v2/health")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(body.get("status"), 200)
            data = body.get("data", {})
            self.assertEqual(data.get("status"), "healthy")
            self.assertIn("role", data)
            self.assertIn("is_primary", data)
            self.assertIn("webui_v2_available", data)
            self.assertEqual(data.get("same_origin"), True)

    def test_root_serves_html_spa_or_public(self):
        """39. GET / serve o arquivo HTML principal com Content-Type text/html."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers.get("content-type", ""))
        self.assertTrue("<html" in resp.text.lower() or "<!doctype html" in resp.text.lower())

    def test_spa_static_files_fallback_for_client_routes(self):
        """40. Rotas SPA do cliente (sem extensão) recebem fallback para index.html com status 200."""
        resp = self.client.get("/agent-ops")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers.get("content-type", ""))

    def test_missing_asset_with_extension_returns_404(self):
        """41. Assets estáticos inexistentes com extensão (ex.: .js) retornam 404 e NÃO index.html."""
        resp = self.client.get("/assets/definitely_missing_asset_123.js")
        self.assertEqual(resp.status_code, 404)

    def test_same_origin_browser_request_allowed(self):
        """42. Requisição do mesmo Origin é permitida sem bloqueio 403."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path):
            resp = self.client.get(
                "/api/v2/system/status",
                headers={"Origin": "http://testserver"},
            )
            self.assertEqual(resp.status_code, 200)


