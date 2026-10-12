"""Testes da API V2 Read-Only (Fase R5A).

Valida:
1. Existência das 6 rotas no OpenAPI e no app FastAPI;
2. Comportamento read-only (GET não muta estado);
3. Perfil inexistente retorna 404 apropriado;
4. Parâmetros inválidos (ex: limit fora da faixa 1..100) retornam 400/422;
5. Mecanismo canônico verify_token é aplicado em todas as rotas V2;
6. Nenhuma chave secreta / API key é vazada nas respostas;
7. Provider health executa de forma passiva sem chamadas externas pagas;
8. Status de publicação 'success' é representado como status terminal canônico (UI-004).
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import asgi
from app.config import config
from app.services import operator_console, profile_manager, scheduler


class TestApiV2ReadOnly(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_v2.db")
        config.app["api_key"] = ""

        # Inicializa o banco temporário
        scheduler.init_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        operator_console.init_operator_db(self.db_path)

        self.client = TestClient(asgi.app)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)
        self.temp_dir.cleanup()

    def test_routes_exist_in_openapi_and_app(self):
        """1. Rotas existem no OpenAPI e estão registradas no FastAPI."""
        openapi_schema = asgi.app.openapi()
        paths = openapi_schema.get("paths", {})

        expected_routes = [
            "/api/v2/system/status",
            "/api/v2/profiles",
            "/api/v2/profiles/{profile_id}/status",
            "/api/v2/scheduler/posts",
            "/api/v2/publications",
            "/api/v2/providers/health",
        ]

        for route in expected_routes:
            self.assertIn(route, paths, f"Rota esperada não encontrada no OpenAPI: {route}")
            self.assertIn("get", paths[route], f"Método GET não encontrado para rota: {route}")

    def test_get_does_not_mutate_state(self):
        """2. Executar GET nas rotas não muta o estado persistido."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path):

            with scheduler.get_connection(self.db_path) as conn:
                posts_count_before = conn.execute("SELECT COUNT(*) FROM scheduled_posts;").fetchone()[0]
                pubs_count_before = conn.execute("SELECT COUNT(*) FROM publication_events;").fetchone()[0]

            r1 = self.client.get("/api/v2/system/status")
            r2 = self.client.get("/api/v2/profiles")
            r3 = self.client.get("/api/v2/scheduler/posts")
            r4 = self.client.get("/api/v2/publications")
            r5 = self.client.get("/api/v2/providers/health")

            self.assertEqual(r1.status_code, 200)
            self.assertEqual(r2.status_code, 200)
            self.assertEqual(r3.status_code, 200)
            self.assertEqual(r4.status_code, 200)
            self.assertEqual(r5.status_code, 200)

            with scheduler.get_connection(self.db_path) as conn:
                posts_count_after = conn.execute("SELECT COUNT(*) FROM scheduled_posts;").fetchone()[0]
                pubs_count_after = conn.execute("SELECT COUNT(*) FROM publication_events;").fetchone()[0]

            self.assertEqual(posts_count_before, posts_count_after)
            self.assertEqual(pubs_count_before, pubs_count_after)

    def test_missing_profile_returns_404(self):
        """3. Perfil inexistente retorna 404 apropriado."""
        with patch("app.services.profile_manager.get_db_path", return_value=self.db_path):
            resp = self.client.get("/api/v2/profiles/inexistent-profile-99999/status")
            self.assertEqual(resp.status_code, 404)
            data = resp.json()
            self.assertIn("not found", data.get("message", "").lower())

    def test_invalid_limit_returns_400_or_422(self):
        """4. Limit inválido (fora de 1..100 ou não inteiro) retorna 400 ou 422."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path):

            # Limit 0 (abaixo do mínimo 1)
            r_zero = self.client.get("/api/v2/publications?limit=0")
            self.assertIn(r_zero.status_code, (400, 422))

            # Limit 1000 (acima do máximo 100)
            r_excess = self.client.get("/api/v2/publications?limit=1000")
            self.assertIn(r_excess.status_code, (400, 422))

            # Limit não numérico
            r_alpha = self.client.get("/api/v2/publications?limit=abc")
            self.assertIn(r_alpha.status_code, (400, 422))

            # Scheduler posts com limit 0
            r_sched_zero = self.client.get("/api/v2/scheduler/posts?limit=0")
            self.assertIn(r_sched_zero.status_code, (400, 422))

    def test_verify_token_enforced_on_all_v2_routes(self):
        """5. verify_token é aplicado em todas as rotas V2 quando api_key está configurado."""
        config.app["api_key"] = "test-secret-key-12345"

        endpoints = [
            "/api/v2/system/status",
            "/api/v2/profiles",
            "/api/v2/profiles/default/status",
            "/api/v2/scheduler/posts",
            "/api/v2/publications",
            "/api/v2/providers/health",
        ]

        for ep in endpoints:
            # Sem token -> 401
            resp_missing = self.client.get(ep)
            self.assertEqual(resp_missing.status_code, 401, f"Endpoint {ep} não rejeitou ausência de chave")

            # Token errado -> 401
            resp_wrong = self.client.get(ep, headers={"x-api-key": "invalid-key"})
            self.assertEqual(resp_wrong.status_code, 401, f"Endpoint {ep} não rejeitou chave errada")

            # Token correto -> passa pela autenticação (não retorna 401)
            resp_ok = self.client.get(ep, headers={"x-api-key": "test-secret-key-12345"})
            self.assertNotEqual(resp_ok.status_code, 401, f"Endpoint {ep} falhou com chave correta")

    def test_responses_do_not_expose_secrets(self):
        """6. Respostas não expõem chaves de API, senhas ou segredos."""
        config.app["gemini_api_key"] = "SUPER_SECRET_GEMINI_KEY"
        config.app["pexels_api_keys"] = ["SUPER_SECRET_PEXELS_KEY"]

        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path):

            resp = self.client.get("/api/v2/providers/health")
            self.assertEqual(resp.status_code, 200)
            text = resp.text

            self.assertNotIn("SUPER_SECRET_GEMINI_KEY", text)
            self.assertNotIn("SUPER_SECRET_PEXELS_KEY", text)

    def test_provider_health_no_paid_external_calls(self):
        """7. Provider health é passivo e não realiza chamadas externas pagas."""
        with patch("urllib.request.urlopen") as mock_url, \
             patch("requests.get") as mock_get, \
             patch("requests.post") as mock_post:

            resp = self.client.get("/api/v2/providers/health")
            self.assertEqual(resp.status_code, 200)

            mock_url.assert_not_called()
            mock_get.assert_not_called()
            mock_post.assert_not_called()

    def test_publication_success_represented_as_terminal_success(self):
        """8. publication_events status='success' é representado como status terminal (UI-004)."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path):

            with scheduler.get_connection(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO publication_events (
                        task_id, platform, published_at, status, external_id,
                        profile_id, channel_id, external_url
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        "task-terminal-success-123",
                        "youtube",
                        "2026-10-11T22:00:00Z",
                        "success",
                        "yt-video-abc",
                        "profile-internet",
                        "channel-internet-yt",
                        "https://youtube.com/shorts/yt-video-abc",
                    ),
                )

            resp = self.client.get("/api/v2/publications?profile_id=profile-internet")
            self.assertEqual(resp.status_code, 200)
            payload = resp.json()
            data = payload.get("data", {})
            pubs = data.get("publications", [])

            self.assertEqual(len(pubs), 1)
            pub = pubs[0]
            self.assertEqual(pub["task_id"], "task-terminal-success-123")
            self.assertEqual(pub["status"], "success")
            self.assertEqual(pub["platform"], "youtube")
            self.assertIsNone(pub.get("error_code"))


if __name__ == "__main__":
    unittest.main()
