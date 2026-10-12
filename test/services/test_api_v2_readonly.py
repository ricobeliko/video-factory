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
        profile_manager.ensure_default_profile(self.db_path)
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
            "/api/v2/executions/live",
            "/api/v2/executions/{task_id}",
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
            "/api/v2/executions/live",
            "/api/v2/executions/task-test-auth-123",
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

    def test_executions_live_exists_and_is_readonly(self):
        """9. /api/v2/executions/live existe e é estritamente read-only."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path):

            with scheduler.get_connection(self.db_path) as conn:
                posts_before = conn.execute("SELECT COUNT(*) FROM scheduled_posts;").fetchone()[0]

            resp = self.client.get("/api/v2/executions/live")
            self.assertEqual(resp.status_code, 200)
            data = resp.json().get("data", {})
            self.assertIn("channels", data)

            with scheduler.get_connection(self.db_path) as conn:
                posts_after = conn.execute("SELECT COUNT(*) FROM scheduled_posts;").fetchone()[0]
            self.assertEqual(posts_before, posts_after)

    def test_live_execution_channel_mapping_and_idle_state(self):
        """10. Perfis sem atividade retornam IDLE e execution=None de forma limpa."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path), \
             patch("app.services.state.state.get_task", return_value=None):

            resp = self.client.get("/api/v2/executions/live")
            self.assertEqual(resp.status_code, 200)
            data = resp.json().get("data", {})
            channels = data.get("channels", [])
            self.assertGreater(len(channels), 0)

            for ch in channels:
                self.assertIn("profile_id", ch)
                self.assertIn("status", ch)
                if ch["status"] == "IDLE":
                    self.assertIsNone(ch["execution"])

    def test_live_execution_task_belongs_to_correct_profile(self):
        """11. Tarefa em execução pertence exclusivamente ao perfil correto."""
        from app.models import const
        fake_task = {
            "task_id": "task-prof-internet-456",
            "profile_id": "default",
            "state": const.TASK_STATE_PROCESSING,
            "progress": 35,
            "video_subject": "Novidades da Web",
            "stage": None,
        }

        mock_status_internet = {
            "enabled": True,
            "state": "generating",
            "message": "Gerando vídeo",
            "current_task_id": "task-prof-internet-456",
            "waiting_task_id": None,
        }

        def mock_auto_status(profile_id=None, db_path=None):
            if profile_id == "default":
                return mock_status_internet
            return {"enabled": False, "state": "idle", "message": "Idle", "current_task_id": None, "waiting_task_id": None}

        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path), \
             patch("app.services.autonomous_production.get_autonomous_status", side_effect=mock_auto_status), \
             patch("app.services.state.state.get_task", return_value=fake_task):

            resp = self.client.get("/api/v2/executions/live")
            self.assertEqual(resp.status_code, 200)
            channels = resp.json().get("data", {}).get("channels", [])

            # Verifica que a task aparece no perfil default e não em outros perfis
            default_ch = next((c for c in channels if c["profile_id"] == "default"), None)
            self.assertIsNotNone(default_ch)
            self.assertEqual(default_ch["status"], "RUNNING")
            self.assertEqual(default_ch["execution"]["task_id"], "task-prof-internet-456")
            self.assertEqual(default_ch["execution"]["topic"], "Novidades da Web")

            other_chs = [c for c in channels if c["profile_id"] != "default"]
            for oc in other_chs:
                self.assertNotEqual(oc["status"], "RUNNING")

    def test_live_execution_real_stage_used_when_available(self):
        """12. Processamento com stage persistido mapeia para o estágio canônico e provedor real."""
        from app.models import const
        rendered_task = {
            "task_id": "task-render-789",
            "profile_id": "default",
            "state": const.TASK_STATE_PROCESSING,
            "progress": 70,
            "video_subject": "GTA VI Lançamento",
            "stage": "SCENE_RENDER_CLIPS",
        }

        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path), \
             patch("app.services.autonomous_production.get_autonomous_status", return_value={
                 "enabled": True, "state": "generating", "message": "Renderizando", "current_task_id": "task-render-789"
             }), \
             patch("app.services.state.state.get_task", return_value=rendered_task):

            resp = self.client.get("/api/v2/executions/live")
            self.assertEqual(resp.status_code, 200)
            ch = next(c for c in resp.json()["data"]["channels"] if c["profile_id"] == "default")
            self.assertEqual(ch["status"], "RUNNING")
            self.assertEqual(ch["execution"]["pipeline_stage"], "RENDER")
            self.assertEqual(ch["execution"]["provider"], "ffmpeg")
            self.assertEqual(ch["execution"]["next_stage"], "SAFETY")

    def test_live_execution_stage_not_invented_when_absent(self):
        """13. Se o estágio não foi persistido, pipeline_stage é None / UNKNOWN, NUNCA inferido pelo progress."""
        from app.models import const
        unindexed_task = {
            "task_id": "task-unknown-stage-111",
            "profile_id": "default",
            "state": const.TASK_STATE_PROCESSING,
            "progress": 40,  # 40% não deve ser inferido como VISUALS!
            "video_subject": "Mistérios Antigos",
            "stage": None,
        }

        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path), \
             patch("app.services.autonomous_production.get_autonomous_status", return_value={
                 "enabled": True, "state": "generating", "message": "Gerando", "current_task_id": "task-unknown-stage-111"
             }), \
             patch("app.services.state.state.get_task", return_value=unindexed_task):

            resp = self.client.get("/api/v2/executions/live")
            self.assertEqual(resp.status_code, 200)
            ch = next(c for c in resp.json()["data"]["channels"] if c["profile_id"] == "default")
            self.assertEqual(ch["status"], "RUNNING")
            self.assertIsNone(ch["execution"]["pipeline_stage"])
            self.assertIsNone(ch["execution"]["provider"])
            self.assertNotEqual(ch["execution"]["pipeline_stage"], "VISUALS")

    def test_publication_success_overrides_stale_retry_in_live_view(self):
        """14. publication_events status='success' prevalece sobre tentativas antigas do scheduler (UI-004)."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path), \
             patch("app.services.autonomous_production.get_autonomous_status", return_value={
                 "enabled": True, "state": "idle", "current_task_id": None, "waiting_task_id": None
             }), \
             patch("app.services.state.state.get_task", return_value=None):

            with scheduler.get_connection(self.db_path) as conn:
                # Scheduler com retry antigo
                conn.execute(
                    """
                    INSERT INTO scheduled_posts (
                        task_id, platform, scheduled_at, status, created_at, attempts, last_error, profile_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    ("task-stale-retry-999", "youtube", "2026-10-11T22:15:00Z", "pending", "2026-10-11T22:00:00Z", 2, "Timeout anterior", "default")
                )
                # Mas publicação já concluída com sucesso!
                conn.execute(
                    """
                    INSERT INTO publication_events (
                        task_id, platform, published_at, status, external_url, profile_id
                    ) VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    ("task-stale-retry-999", "youtube", "2026-10-11T22:20:00Z", "success", "https://youtube.com/shorts/xyz", "default")
                )

            resp = self.client.get("/api/v2/executions/live")
            self.assertEqual(resp.status_code, 200)
            ch = next(c for c in resp.json()["data"]["channels"] if c["profile_id"] == "default")
            self.assertEqual(ch["status"], "SUCCESS")
            self.assertEqual(ch["execution"]["pipeline_stage"], "YOUTUBE")
            self.assertIsNotNone(ch["execution"]["publication_state"])
            self.assertEqual(ch["execution"]["publication_state"]["status"], "success")

    def test_execution_detail_endpoint(self):
        """15. /api/v2/executions/{task_id} retorna o trace causal completo e 404 para task inexistente."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path):

            # 404 para task inexistente
            r_404 = self.client.get("/api/v2/executions/non-existent-task-000")
            self.assertEqual(r_404.status_code, 404)

            # Cria evento para task existente
            with scheduler.get_connection(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO publication_events (
                        task_id, platform, published_at, status, external_url, profile_id
                    ) VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    ("task-trace-detail-123", "youtube", "2026-10-11T22:00:00Z", "success", "https://youtube.com/shorts/trace123", "default")
                )

            r_ok = self.client.get("/api/v2/executions/task-trace-detail-123")
            self.assertEqual(r_ok.status_code, 200)
            data = r_ok.json().get("data", {})
            self.assertEqual(data["task_id"], "task-trace-detail-123")
            self.assertIn("execution_trace", data)
            nodes = [n["node"] for n in data["execution_trace"]]
            self.assertIn("CHANNEL", nodes)
            self.assertIn("AUTONOMOUS_PRODUCTION", nodes)
            self.assertIn("SERVICE", nodes)
            self.assertIn("PROVIDER", nodes)
            self.assertIn("RESULT", nodes)
            self.assertIn("NEXT_SERVICE", nodes)


if __name__ == "__main__":
    unittest.main()

