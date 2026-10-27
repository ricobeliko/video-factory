"""
Testes direcionados da Missão M6a — Voz e velocidade POR CANAL (backend).

Valida:
1. Matriz de precedência (canal só / global só / ambos / nenhum) para voice_name, rate, volume e tts_server.
2. Source correto em cada caso ('channel', 'global', 'default').
3. GET /api/v2/channels/{profile_id}/settings inclui bloco 'effective_voice'.
4. PATCH /api/v2/channels/{profile_id}/voice:
   - Altera apenas os campos enviados
   - Rejeita af-ZA-* e vozes estrangeiras não homologadas com 400 e mensagem em português
   - Canonicaliza sufixo -Male / -Female (ex: pt-BR-AntonioNeural-Male -> pt-BR-AntonioNeural)
   - Rejeita voice_rate fora de [0.5, 2.0] e voice_volume fora de [0.0, 1.0]
   - Retorna 403 em nó SECONDARY
   - Retorna 404 para canal inexistente
   - Registra evento operacional PROFILE_VOICE_UPDATED com campo/antigo/novo
   - NÃO altera autonomous_enabled, growth_mode nem quotas
5. Quiz Engine:
   - export_to_quiz_config e export_to_paper_quiz_config falham com 'voz do canal não definida' se a voz chegar vazia
   - Não usam fallback silencioso pt-BR-AntonioNeural
"""

import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import asgi
from app.config import config
from app.services import (
    autonomous_production,
    operator_console,
    profile_manager,
    quiz_generator,
    scheduler,
)
from app.services import state as sm


class TestVoicePrecedenceMatrix(unittest.TestCase):
    """Testa a nova precedência: Canal (settings.voice) > Global (config.ui) > Padrão (config.app / fallback)."""

    def setUp(self):
        self.original_app_config = dict(config.app)
        self.original_ui_config = dict(config.ui)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_precedence.db")

        scheduler.init_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        profile_manager.create_profile(
            profile_id="prof-test-voice",
            name="Canal Teste Voz",
            slug="test-voice-precedence",
            db_path=self.db_path,
        )

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)
        config.ui.clear()
        config.ui.update(self.original_ui_config)
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_voice_name_precedence_matrix(self):
        pid = "prof-test-voice"

        # Caso 1: Ambos definidos -> Canal VENCE Global
        profile_manager.update_profile_voice_settings(
            pid, {"voice_name": "pt-BR-FranciscaNeural"}, db_path=self.db_path
        )
        config.ui["voice_name"] = "en-US-BrianMultilingualNeural"
        config.app["voice_name"] = "en-US-BrianMultilingualNeural"

        eff = profile_manager.get_effective_voice_settings(pid, db_path=self.db_path)
        self.assertEqual(eff["voice_name"]["value"], "pt-BR-FranciscaNeural")
        self.assertEqual(eff["voice_name"]["source"], "channel")

        ctx = profile_manager.get_generation_profile_context(pid, db_path=self.db_path)
        self.assertEqual(ctx["voice_name"], "pt-BR-FranciscaNeural")

        # Caso 2: Canal só -> Canal vence
        config.ui["voice_name"] = None
        eff = profile_manager.get_effective_voice_settings(pid, db_path=self.db_path)
        self.assertEqual(eff["voice_name"]["value"], "pt-BR-FranciscaNeural")
        self.assertEqual(eff["voice_name"]["source"], "channel")

        # Caso 3: Global só -> Global vence
        profile_manager.update_profile_voice_settings(
            pid, {"voice_name": None}, db_path=self.db_path
        )
        config.ui["voice_name"] = "pt-BR-ThalitaMultilingualNeural"
        eff = profile_manager.get_effective_voice_settings(pid, db_path=self.db_path)
        self.assertEqual(eff["voice_name"]["value"], "pt-BR-ThalitaMultilingualNeural")
        self.assertEqual(eff["voice_name"]["source"], "global")

        # Caso 4: Nenhum definido -> Padrão Brian
        config.ui["voice_name"] = None
        config.app["voice_name"] = None
        eff = profile_manager.get_effective_voice_settings(pid, db_path=self.db_path)
        self.assertEqual(eff["voice_name"]["value"], "en-US-BrianMultilingualNeural")
        self.assertEqual(eff["voice_name"]["source"], "default")

    def test_voice_rate_and_volume_precedence_matrix(self):
        pid = "prof-test-voice"

        # Caso 1: Ambos definidos -> Canal VENCE Global
        profile_manager.update_profile_voice_settings(
            pid, {"voice_rate": 1.25, "voice_volume": 0.85}, db_path=self.db_path
        )
        config.ui["voice_rate"] = 0.9
        config.ui["voice_volume"] = 0.7

        eff = profile_manager.get_effective_voice_settings(pid, db_path=self.db_path)
        self.assertEqual(eff["voice_rate"]["value"], 1.25)
        self.assertEqual(eff["voice_rate"]["source"], "channel")
        self.assertEqual(eff["voice_volume"]["value"], 0.85)
        self.assertEqual(eff["voice_volume"]["source"], "channel")

        # Caso 2: Global só -> Global vence
        profile_manager.update_profile_voice_settings(
            pid, {"voice_rate": None, "voice_volume": None}, db_path=self.db_path
        )
        eff = profile_manager.get_effective_voice_settings(pid, db_path=self.db_path)
        self.assertEqual(eff["voice_rate"]["value"], 0.9)
        self.assertEqual(eff["voice_rate"]["source"], "global")
        self.assertEqual(eff["voice_volume"]["value"], 0.7)
        self.assertEqual(eff["voice_volume"]["source"], "global")

        # Caso 3: Nenhum definido -> Default 1.0
        config.ui["voice_rate"] = None
        config.ui["voice_volume"] = None
        config.app["voice_rate"] = None
        config.app["voice_volume"] = None
        eff = profile_manager.get_effective_voice_settings(pid, db_path=self.db_path)
        self.assertEqual(eff["voice_rate"]["value"], 1.0)
        self.assertEqual(eff["voice_rate"]["source"], "default")
        self.assertEqual(eff["voice_volume"]["value"], 1.0)
        self.assertEqual(eff["voice_volume"]["source"], "default")


class TestApiV2VoicePerChannelEndpoints(unittest.TestCase):
    """Testa a API V2: GET /settings com effective_voice e PATCH /voice com validações e eventos."""

    def setUp(self):
        self.original_app_config = dict(config.app)
        self.original_ui_config = dict(config.ui)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_voice_api.db")
        config.app["api_key"] = ""

        if hasattr(sm, "state") and hasattr(sm.state, "_tasks"):
            sm.state._tasks.clear()

        scheduler.init_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        profile_manager.ensure_default_profile(self.db_path)
        operator_console.init_operator_db(self.db_path)

        # Adquire lock de nó primário
        operator_console.acquire_instance_lock(db_path=self.db_path)

        # Cria canal com autônomo desligado e cotas iniciais
        profile_manager.create_profile(
            profile_id="profile-curiosidades",
            name="Canal Curiosidades",
            slug="canal-curiosidades-unique",
            niche="Curiosidades",
            db_path=self.db_path,
        )
        autonomous_production.set_profile_autonomous_mode_enabled("profile-curiosidades", False, db_path=self.db_path)
        profile_manager.update_profile("profile-curiosidades", growth_mode="warmup", db_path=self.db_path)
        profile_manager.update_profile_quotas("profile-curiosidades", {"target_ready_stock": 5}, db_path=self.db_path)

        self.patchers = [
            patch("app.services.operator_console.get_db_path", return_value=self.db_path),
            patch("app.services.profile_manager.get_db_path", return_value=self.db_path),
            patch("app.services.scheduler.get_db_path", return_value=self.db_path),
        ]
        for p in self.patchers:
            p.start()

        self.client = TestClient(asgi.app)

    def tearDown(self):
        for p in self.patchers:
            p.stop()
        try:
            operator_console.release_instance_lock(db_path=self.db_path)
        except Exception:
            pass
        config.app.clear()
        config.app.update(self.original_app_config)
        config.ui.clear()
        config.ui.update(self.original_ui_config)
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass
        if hasattr(sm, "state") and hasattr(sm.state, "_tasks"):
            sm.state._tasks.clear()

    def test_get_channel_settings_includes_effective_voice(self):
        """GET /api/v2/channels/{profile_id}/settings expõe o bloco 'effective_voice'."""
        config.ui["voice_name"] = "pt-BR-FranciscaNeural"
        resp = self.client.get("/api/v2/channels/profile-curiosidades/settings")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]

        self.assertIn("effective_voice", data)
        eff = data["effective_voice"]
        self.assertIn("voice_name", eff)
        self.assertIn("voice_rate", eff)
        self.assertIn("voice_volume", eff)
        self.assertIn("tts_server", eff)
        self.assertEqual(eff["voice_name"]["value"], "pt-BR-FranciscaNeural")
        self.assertEqual(eff["voice_name"]["source"], "global")

    def test_patch_voice_alters_only_sent_fields(self):
        """PATCH altera apenas os campos enviados, preservando os demais."""
        resp = self.client.patch(
            "/api/v2/channels/profile-curiosidades/voice",
            json={"voice_name": "pt-BR-AntonioNeural"},
        )
        self.assertEqual(resp.status_code, 200)

        # Verifica settings gravados no banco
        settings = profile_manager.get_profile_settings("profile-curiosidades", db_path=self.db_path)
        self.assertEqual(settings.voice.voice_name, "pt-BR-AntonioNeural")
        # rate e volume não enviados continuam None
        self.assertIsNone(settings.voice.voice_rate)
        self.assertIsNone(settings.voice.voice_volume)

    def test_patch_voice_canonicalizes_male_female_suffix(self):
        """PATCH com sufixo -Male ou -Female é canonicalizado sem o sufixo."""
        resp = self.client.patch(
            "/api/v2/channels/profile-curiosidades/voice",
            json={"voice_name": "pt-BR-AntonioNeural-Male"},
        )
        self.assertEqual(resp.status_code, 200)
        settings = profile_manager.get_profile_settings("profile-curiosidades", db_path=self.db_path)
        self.assertEqual(settings.voice.voice_name, "pt-BR-AntonioNeural")

    def test_patch_voice_rejects_foreign_and_non_existent_voices(self):
        """PATCH rejeita af-ZA-* e en-US-JennyNeural com 400 e mensagem em português."""
        resp1 = self.client.patch(
            "/api/v2/channels/profile-curiosidades/voice",
            json={"voice_name": "af-ZA-AdriNeural"},
        )
        self.assertEqual(resp1.status_code, 400)
        self.assertIn("não homologada para pt-BR", resp1.json()["message"])

        resp2 = self.client.patch(
            "/api/v2/channels/profile-curiosidades/voice",
            json={"voice_name": "en-US-JennyNeural"},
        )
        self.assertEqual(resp2.status_code, 400)
        self.assertIn("não homologada para pt-BR", resp2.json()["message"])

    def test_patch_voice_rejects_rate_and_volume_out_of_range(self):
        """PATCH rejeita rate fora de [0.5, 2.0] e volume fora de [0.0, 1.0]."""
        # Rate abaixo de 0.5
        resp1 = self.client.patch(
            "/api/v2/channels/profile-curiosidades/voice",
            json={"voice_rate": 0.4},
        )
        self.assertEqual(resp1.status_code, 400)
        self.assertIn("0.5 e 2.0", resp1.json()["message"])

        # Rate acima de 2.0
        resp2 = self.client.patch(
            "/api/v2/channels/profile-curiosidades/voice",
            json={"voice_rate": 2.5},
        )
        self.assertEqual(resp2.status_code, 400)
        self.assertIn("0.5 e 2.0", resp2.json()["message"])

        # Volume negativo
        resp3 = self.client.patch(
            "/api/v2/channels/profile-curiosidades/voice",
            json={"voice_volume": -0.1},
        )
        self.assertEqual(resp3.status_code, 400)
        self.assertIn("0.0 e 1.0", resp3.json()["message"])

        # Volume acima de 1.0
        resp4 = self.client.patch(
            "/api/v2/channels/profile-curiosidades/voice",
            json={"voice_volume": 1.2},
        )
        self.assertEqual(resp4.status_code, 400)
        self.assertIn("0.0 e 1.0", resp4.json()["message"])

    def test_patch_voice_403_on_secondary_instance(self):
        """PATCH retorna 403 em nós SECONDARY."""
        with patch("app.services.operator_console.is_primary_instance", return_value=False):
            resp = self.client.patch(
                "/api/v2/channels/profile-curiosidades/voice",
                json={"voice_name": "pt-BR-FranciscaNeural"},
            )
            self.assertEqual(resp.status_code, 403)
            self.assertIn("only primary instance", resp.json()["message"])

    def test_patch_voice_404_for_non_existent_profile(self):
        """PATCH retorna 404 para canal inexistente."""
        resp = self.client.patch(
            "/api/v2/channels/profile-inexistente/voice",
            json={"voice_name": "pt-BR-FranciscaNeural"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_patch_voice_logs_operational_event(self):
        """PATCH registra evento operacional PROFILE_VOICE_UPDATED no banco."""
        resp = self.client.patch(
            "/api/v2/channels/profile-curiosidades/voice",
            json={"voice_name": "pt-BR-FranciscaNeural", "voice_rate": 1.1},
        )
        self.assertEqual(resp.status_code, 200)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            events = conn.execute(
                "SELECT * FROM operational_events WHERE event_type = 'PROFILE_VOICE_UPDATED' ORDER BY id ASC;"
            ).fetchall()
            self.assertGreaterEqual(len(events), 2)
            fields_updated = [json.loads(e["metadata_json"])["field"] for e in events]
            self.assertIn("voice_name", fields_updated)
            self.assertIn("voice_rate", fields_updated)

    def test_patch_voice_preserves_autonomous_growth_and_quotas(self):
        """PATCH não altera autonomous_enabled, growth_mode nem quotas do canal."""
        initial_auto = autonomous_production.is_profile_autonomous_mode_enabled("profile-curiosidades", db_path=self.db_path)
        self.assertFalse(initial_auto)

        resp = self.client.patch(
            "/api/v2/channels/profile-curiosidades/voice",
            json={"voice_name": "pt-BR-FranciscaNeural", "voice_rate": 1.05},
        )
        self.assertEqual(resp.status_code, 200)

        # Verifica preservação de invariants
        after_auto = autonomous_production.is_profile_autonomous_mode_enabled("profile-curiosidades", db_path=self.db_path)
        self.assertFalse(after_auto, "Salvar voz NÃO pode alterar modo autônomo")

        prof = profile_manager.get_profile("profile-curiosidades", db_path=self.db_path)
        self.assertEqual(prof["growth_mode"], "warmup")

        quotas = profile_manager.get_profile_quotas("profile-curiosidades", db_path=self.db_path)
        self.assertEqual(quotas["target_ready_stock"], 5)

    def test_get_allowed_voices_endpoint(self):
        """GET /api/v2/voices/allowed retorna vozes aprovadas para pt-BR com rótulos amigáveis."""
        resp = self.client.get("/api/v2/voices/allowed")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 4)

        voice_ids = [v["id"] for v in data]
        self.assertIn("pt-BR-FranciscaNeural", voice_ids)
        self.assertIn("pt-BR-AntonioNeural", voice_ids)
        self.assertIn("pt-BR-ThalitaMultilingualNeural", voice_ids)
        self.assertIn("en-US-BrianMultilingualNeural", voice_ids)

        for v in data:
            self.assertIn("id", v)
            self.assertIn("name", v)
            self.assertIn("gender", v)
            self.assertIn("locale", v)
            self.assertTrue(autonomous_production.is_valid_pt_br_voice(v["id"]))

    def test_channel_settings_exposes_is_quiz_flag(self):
        """GET /api/v2/channels/{profile_id}/settings expõe 'is_quiz' corretamente."""
        # Canal tradicional não é quiz
        resp1 = self.client.get("/api/v2/channels/profile-curiosidades/settings")
        self.assertEqual(resp1.status_code, 200)
        self.assertFalse(resp1.json()["data"]["is_quiz"])

        # Canal de quiz é reconhecido como quiz
        profile_manager.create_profile(
            profile_id="profile-quiz-teste",
            name="Canal Quiz Dilema",
            slug="canal-quiz-dilema",
            db_path=self.db_path,
        )
        settings = profile_manager.get_profile_settings("profile-quiz-teste", db_path=self.db_path)
        settings.editorial.video_format = "quiz_dilemma"
        profile_manager.update_profile_settings("profile-quiz-teste", settings.model_dump(), db_path=self.db_path)

        resp2 = self.client.get("/api/v2/channels/profile-quiz-teste/settings")
        self.assertEqual(resp2.status_code, 200)
        self.assertTrue(resp2.json()["data"]["is_quiz"])


class TestQuizVoiceEnforcement(unittest.TestCase):
    """Testa que o Quiz Engine exige voz explícita do canal e não usa fallback silencioso Antonio."""

    def test_quiz_generator_fails_when_voice_is_empty(self):
        """export_to_quiz_config e export_to_paper_quiz_config falham com mensagem em português se voice_name for vazio."""
        gen = quiz_generator.QuizContentGenerator()
        dummy_quiz = {
            "niche": "curiosidades",
            "quiz_title": "TESTE QUIZ",
            "questions": [
                {
                    "id": "q1",
                    "top": {"tag": "A", "title": "Opcao A", "image_name": "img1.jpg"},
                    "bottom": {"tag": "B", "title": "Opcao B", "image_name": "img2.jpg"},
                }
            ],
        }

        # 1. Dilemma Quiz: voice_name = None deve lançar ValueError("voz do canal não definida")
        with self.assertRaises(ValueError) as ctx1:
            gen.export_to_quiz_config(
                dummy_quiz,
                output_json_path="temp_test.json",
                voice_name=None,
            )
        self.assertIn("voz do canal não definida", str(ctx1.exception))

        # Dilemma Quiz: voice_name = "" deve lançar ValueError
        with self.assertRaises(ValueError) as ctx2:
            gen.export_to_quiz_config(
                dummy_quiz,
                output_json_path="temp_test.json",
                voice_name="",
            )
        self.assertIn("voz do canal não definida", str(ctx2.exception))

        # 2. Paper Quiz: voice_name = None deve lançar ValueError
        with self.assertRaises(ValueError) as ctx3:
            gen.export_to_paper_quiz_config(
                dummy_quiz,
                output_video_path="temp.mp4",
                output_thumbnail_path="thumb.jpg",
                temp_dir="temp_p",
                voice_name=None,
            )
        self.assertIn("voz do canal não definida", str(ctx3.exception))

        # Paper Quiz: voice_name = "   " deve lançar ValueError
        with self.assertRaises(ValueError) as ctx4:
            gen.export_to_paper_quiz_config(
                dummy_quiz,
                output_video_path="temp.mp4",
                output_thumbnail_path="thumb.jpg",
                temp_dir="temp_p",
                voice_name="   ",
            )
        self.assertIn("voz do canal não definida", str(ctx4.exception))
