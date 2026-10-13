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
