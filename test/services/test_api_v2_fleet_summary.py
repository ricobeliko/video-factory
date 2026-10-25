"""Testes do Endpoint de Resumo da Frota V2 (Missão C).

Valida:
1. Rota /api/v2/fleet/summary registrada no FastAPI e no OpenAPI;
2. Payload estruturado com 'totals' e 'channels';
3. Contagem correta com mais de 200 tarefas (sem truncamento por limites legados de paginação);
4. Presença de todos os campos obrigatórios por canal;
5. Classificação determinística de status (ok, running, attention, blocked, paused) e issue;
6. Comportamento estritamente read-only (GET não muta banco);
7. Aplicação do mecanismo verify_token.
"""

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import asgi
from app.config import config
from app.models import const
from app.services import operator_console, profile_manager, safety_gate, scheduler
from app.services import state as sm


class TestApiV2FleetSummary(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_fleet.db")
        config.app["api_key"] = ""

        # Inicializa o banco temporário
        scheduler.init_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        profile_manager.ensure_default_profile(self.db_path)
        operator_console.init_operator_db(self.db_path)
        safety_gate.init_safety_db(self.db_path)

        # Configura 3 perfis distintos
        with scheduler.get_connection(self.db_path) as conn:
            # 1. Perfil Default (Traditional / OK)
            conn.execute(
                """
                UPDATE content_profiles
                SET name = 'Dose Diária de Internet',
                    slug = 'default',
                    niche = 'internet_curiosities',
                    growth_mode = 'SCALE',
                    is_active = 1,
                    settings_json = ?
                WHERE id = 'default';
                """,
                (
                    json.dumps({
                        "editorial": {"video_format": "traditional"},
                        "schedule": {"posts_per_day": 2},
                        "automation": {"target_ready_stock": 10, "autonomous_enabled": True},
                    }),
                ),
            )

            # 2. Perfil Quiz de Papel (quiz_paper)
            conn.execute(
                """
                INSERT INTO content_profiles (id, name, slug, niche, default_preset, growth_mode, is_active, settings_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, '2026-10-24T00:00:00Z', '2026-10-24T00:00:00Z');
                """,
                (
                    "profile-quiz-paper",
                    "Quiz_Quiz",
                    "quiz-quiz",
                    "quiz_geral",
                    "quiz_paper",
                    "SCALE",
                    json.dumps({
                        "editorial": {"video_format": "quiz_paper"},
                        "schedule": {"posts_per_day": 3},
                        "automation": {"target_ready_stock": 10, "autonomous_enabled": True},
                    }),
                ),
            )

            # 3. Perfil Quiz de Escolhas (quiz_dilemma / Pausado)
            conn.execute(
                """
                INSERT INTO content_profiles (id, name, slug, niche, default_preset, growth_mode, is_active, settings_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, '2026-10-24T00:00:00Z', '2026-10-24T00:00:00Z');
                """,
                (
                    "profile-dilemma",
                    "Dose Diária de Escolhas",
                    "dose-diaria-de-escolhas",
                    "quiz_dilemma",
                    "quiz_dilemma",
                    "WARMUP",
                    json.dumps({
                        "editorial": {"video_format": "quiz_dilemma"},
                        "schedule": {"posts_per_day": 1},
                        "automation": {"target_ready_stock": 3, "autonomous_enabled": False},
                    }),
                ),
            )

            # Autopilot settings
            conn.execute("INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES ('autonomous_mode_enabled', 'True');")
            conn.execute("INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES ('autonomous_mode_enabled:profile-quiz-paper', 'True');")
            conn.execute("INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES ('autonomous_mode_enabled:profile-dilemma', 'False');")
            conn.execute("INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES ('autonomous_target_ready_stock', '10');")
            conn.execute("INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES ('autonomous_target_ready_stock:profile-quiz-paper', '10');")
            conn.execute("INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES ('autonomous_target_ready_stock:profile-dilemma', '3');")

            # Popula mais de 200 tarefas (> 230 tarefas prontas)
            # Perfil default: 150 tarefas prontas
            for i in range(150):
                tid = f"task-default-{i}"
                conn.execute(
                    "INSERT INTO task_profiles (task_id, profile_id, created_at) VALUES (?, 'default', '2026-10-24T00:00:00Z');",
                    (tid,),
                )
                conn.execute(
                    "INSERT INTO monetization_safety (task_id, topic, preset, safety_status, checked_at) VALUES (?, 'topico', 'default', 'PASS', '2026-10-24T00:00:00Z');",
                    (tid,),
                )
                sm.state.update_task(tid, state=const.TASK_STATE_COMPLETE, progress=100, safety_status="PASS", profile_id="default")

            # Perfil quiz_paper: 70 tarefas prontas
            for i in range(70):
                tid = f"task-paper-{i}"
                conn.execute(
                    "INSERT INTO task_profiles (task_id, profile_id, created_at) VALUES (?, 'profile-quiz-paper', '2026-10-24T00:00:00Z');",
                    (tid,),
                )
                conn.execute(
                    "INSERT INTO monetization_safety (task_id, topic, preset, safety_status, checked_at) VALUES (?, 'topico', 'quiz_paper', 'PASS', '2026-10-24T00:00:00Z');",
                    (tid,),
                )
                sm.state.update_task(tid, state=const.TASK_STATE_COMPLETE, progress=100, safety_status="PASS", profile_id="profile-quiz-paper")

            # Perfil dilemma: 10 tarefas prontas
            for i in range(10):
                tid = f"task-dilemma-{i}"
                conn.execute(
                    "INSERT INTO task_profiles (task_id, profile_id, created_at) VALUES (?, 'profile-dilemma', '2026-10-24T00:00:00Z');",
                    (tid,),
                )
                conn.execute(
                    "INSERT INTO monetization_safety (task_id, topic, preset, safety_status, checked_at) VALUES (?, 'topico', 'quiz_dilemma', 'PASS', '2026-10-24T00:00:00Z');",
                    (tid,),
                )
                sm.state.update_task(tid, state=const.TASK_STATE_COMPLETE, progress=100, safety_status="PASS", profile_id="profile-dilemma")

            # Scheduled posts (2 planned posts para default)
            conn.execute(
                "INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at, profile_id) VALUES ('task-sched-1', 'youtube', '2026-10-25T12:00:00Z', 'planned', '2026-10-24T00:00:00Z', 'default');"
            )
            conn.execute(
                "INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at, profile_id) VALUES ('task-sched-2', 'youtube', '2026-10-25T16:00:00Z', 'planned', '2026-10-24T00:00:00Z', 'default');"
            )

            # Publication events (1 publicado hoje para quiz-paper)
            now_iso = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO publication_events (task_id, platform, published_at, status, profile_id) VALUES ('task-pub-1', 'youtube', ?, 'success', 'profile-quiz-paper');",
                (now_iso,),
            )

            # Operational events (para approval_rate_24h de default: 3 aprovados, 1 rejeitado -> 0.75)
            conn.execute(
                "INSERT INTO operational_events (timestamp, component, severity, event_type, message, metadata_json) VALUES (?, 'autonomous_production', 'INFO', 'generation_approved', 'approved', ?);",
                (now_iso, json.dumps({"profile_id": "default"})),
            )
            conn.execute(
                "INSERT INTO operational_events (timestamp, component, severity, event_type, message, metadata_json) VALUES (?, 'autonomous_production', 'INFO', 'generation_approved', 'approved', ?);",
                (now_iso, json.dumps({"profile_id": "default"})),
            )
            conn.execute(
                "INSERT INTO operational_events (timestamp, component, severity, event_type, message, metadata_json) VALUES (?, 'autonomous_production', 'INFO', 'generation_approved', 'approved', ?);",
                (now_iso, json.dumps({"profile_id": "default"})),
            )
            conn.execute(
                "INSERT INTO operational_events (timestamp, component, severity, event_type, message, metadata_json) VALUES (?, 'autonomous_production', 'WARNING', 'task_gate_rejected', 'rejected', ?);",
                (now_iso, json.dumps({"profile_id": "default"})),
            )

        self.client = TestClient(asgi.app)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)
        self.temp_dir.cleanup()

    def test_route_exists_in_openapi_and_app(self):
        """1. Rota /api/v2/fleet/summary está registrada no OpenAPI."""
        openapi_schema = asgi.app.openapi()
        paths = openapi_schema.get("paths", {})
        self.assertIn("/api/v2/fleet/summary", paths)
        self.assertIn("get", paths["/api/v2/fleet/summary"])

    def test_fleet_summary_payload_and_over_200_tasks(self):
        """2. Retorna estrutura correta e conta mais de 200 tarefas sem truncamento."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path):

            resp = self.client.get("/api/v2/fleet/summary")
            self.assertEqual(resp.status_code, 200)

            data = resp.json().get("data", {})
            self.assertIn("totals", data)
            self.assertIn("channels", data)

            channels = data["channels"]
            self.assertEqual(len(channels), 3)

            # Mapeia canais por profile_id
            chan_map = {c["profile_id"]: c for c in channels}
            self.assertIn("default", chan_map)
            self.assertIn("profile-quiz-paper", chan_map)
            self.assertIn("profile-dilemma", chan_map)

            # Verifica contagem de estoque pronto individual e total (> 200!)
            self.assertEqual(chan_map["default"]["ready_stock"], 150)
            self.assertEqual(chan_map["profile-quiz-paper"]["ready_stock"], 70)
            self.assertEqual(chan_map["profile-dilemma"]["ready_stock"], 10)

            totals = data["totals"]
            self.assertEqual(totals["total_ready_stock"], 230)
            self.assertGreater(totals["total_ready_stock"], 200, "Estoque total deve superar 200 sem truncamento")
            self.assertEqual(totals["total_channels"], 3)
            self.assertEqual(totals["active_channels"], 3)
            self.assertEqual(totals["published_today"], 1)
            self.assertEqual(totals["goal_today"], 2 + 3 + 1)

            # Verifica presença de todas as chaves obrigatórias em cada canal
            required_keys = {
                "profile_id", "name", "slug", "niche", "format", "is_active",
                "autonomous_enabled", "growth_mode", "ready_stock", "target_stock",
                "pending_processing", "failed", "scheduled", "published_today",
                "goal_today", "approval_rate_24h", "last_run_at", "status", "issue"
            }
            allowed_statuses = {"ok", "running", "attention", "blocked", "paused"}

            for ch in channels:
                self.assertTrue(required_keys.issubset(set(ch.keys())), f"Chaves faltando no canal {ch.get('profile_id')}")
                self.assertIn(ch["status"], allowed_statuses)
                if ch["status"] == "ok":
                    self.assertIsNone(ch["issue"])
                else:
                    self.assertIsInstance(ch["issue"], str)

            # Validações específicas por perfil
            # Default: traditional, ok
            c_def = chan_map["default"]
            self.assertEqual(c_def["format"], "traditional")
            self.assertTrue(c_def["autonomous_enabled"])
            self.assertEqual(c_def["growth_mode"], "SCALE")
            self.assertEqual(c_def["scheduled"], 2)
            self.assertEqual(c_def["approval_rate_24h"], 0.75)
            self.assertEqual(c_def["status"], "ok")

            # Quiz Paper: quiz_paper, ok (70 >= target 10)
            c_paper = chan_map["profile-quiz-paper"]
            self.assertEqual(c_paper["format"], "quiz_paper")
            self.assertTrue(c_paper["autonomous_enabled"])
            self.assertEqual(c_paper["published_today"], 1)
            self.assertEqual(c_paper["status"], "ok")

            # Dilemma: quiz_dilemma, paused (autonomous_enabled=False)
            c_dil = chan_map["profile-dilemma"]
            self.assertEqual(c_dil["format"], "quiz_dilemma")
            self.assertFalse(c_dil["autonomous_enabled"])
            self.assertEqual(c_dil["status"], "paused")
            self.assertEqual(c_dil["issue"], "Modo autônomo desligado")

    def test_get_does_not_mutate_state(self):
        """3. Executar GET /api/v2/fleet/summary não muta o estado persistido."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path):

            with scheduler.get_connection(self.db_path) as conn:
                posts_count_before = conn.execute("SELECT COUNT(*) FROM scheduled_posts;").fetchone()[0]
                pubs_count_before = conn.execute("SELECT COUNT(*) FROM publication_events;").fetchone()[0]
                prof_count_before = conn.execute("SELECT COUNT(*) FROM content_profiles;").fetchone()[0]

            resp = self.client.get("/api/v2/fleet/summary")
            self.assertEqual(resp.status_code, 200)

            with scheduler.get_connection(self.db_path) as conn:
                posts_count_after = conn.execute("SELECT COUNT(*) FROM scheduled_posts;").fetchone()[0]
                pubs_count_after = conn.execute("SELECT COUNT(*) FROM publication_events;").fetchone()[0]
                prof_count_after = conn.execute("SELECT COUNT(*) FROM content_profiles;").fetchone()[0]

            self.assertEqual(posts_count_before, posts_count_after)
            self.assertEqual(pubs_count_before, pubs_count_after)
            self.assertEqual(prof_count_before, prof_count_after)

    def test_verify_token_enforced_when_api_key_set(self):
        """4. verify_token é aplicado na rota /api/v2/fleet/summary quando api_key está configurado."""
        config.app["api_key"] = "test-secret-key-12345"

        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path):
            # Sem token -> 401
            resp_no_token = self.client.get("/api/v2/fleet/summary")
            self.assertEqual(resp_no_token.status_code, 401)

            # Com token incorreto -> 401
            resp_bad_token = self.client.get(
                "/api/v2/fleet/summary",
                headers={"x-api-key": "wrong-token"},
            )
            self.assertEqual(resp_bad_token.status_code, 401)

            # Com token correto -> 200
            resp_good_token = self.client.get(
                "/api/v2/fleet/summary",
                headers={"x-api-key": "test-secret-key-12345"},
            )
            self.assertEqual(resp_good_token.status_code, 200)
