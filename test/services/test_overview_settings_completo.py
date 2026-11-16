"""
test/services/test_overview_settings_completo.py
==============================================
Testes direcionados da Missão v2/overview-settings-completo:
(a) GET /api/v2/channels (`channels[].settings`) e GET /api/v2/channels/{id}/settings
    devolvem settings com as MESMAS chaves e valores para o mesmo perfil
    (inclui effective_voice, workspace_settings.music.volume e voice_rate).
(b) Perfil com music.volume = 0.12 e voice_rate = 1.1 (e opcionalmente flow_scene_count = 3)
    aparece exatamente correto no item de /channels.
(c) Perfil sem voz fixada mostra source = "global" em effective_voice via /channels.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import asgi
from app.config import config
from app.services import autonomous_production, operator_console, profile_manager, scheduler
from app.services import state as sm


class TestOverviewSettingsCompleto(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        self.original_ui_config = dict(config.ui)
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_overview_settings.db")
        config.app["api_key"] = ""
        config.ui["voice_name"] = "en-US-BrianMultilingualNeural"
        config.ui["voice_rate"] = 1.0
        config.ui["voice_volume"] = 1.0

        if hasattr(sm, "state") and hasattr(sm.state, "_tasks"):
            sm.state._tasks.clear()

        scheduler.init_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        profile_manager.ensure_default_profile(self.db_path)
        operator_console.init_operator_db(self.db_path)
        operator_console.acquire_instance_lock(db_path=self.db_path)

        # Configura perfil tradicional estilo PROD ("Internet"):
        # - voice_name = None (herda global Brian -> source "global")
        # - voice_rate = 1.1 (fixado no canal -> source "channel")
        # - music.volume = 0.12
        self.prof_trad = profile_manager.onboard_channel_workspace(
            name="Canal Internet Completo",
            slug="canal-internet-completo",
            niche="curiosidades",
            topic_brief="Internet",
            video_format="traditional",
            require_destination=False,
            db_path=self.db_path,
        )["profile"]["id"]

        profile_manager.update_profile_voice_settings(
            self.prof_trad,
            {"voice_name": None, "voice_rate": 1.1, "voice_volume": None},
            db_path=self.db_path,
        )
        profile_manager.update_profile_music_settings(
            self.prof_trad,
            {"volume": 0.12},
            db_path=self.db_path,
        )
        profile_manager.update_profile_visual_settings(
            self.prof_trad,
            {"flow_scene_count": 3},
            db_path=self.db_path,
        )

        # Configura segundo perfil Quiz sem voz fixada e com volume padrão (None)
        self.prof_quiz = profile_manager.onboard_channel_workspace(
            name="Canal Quiz Completo",
            slug="canal-quiz-completo",
            niche="dilemas",
            topic_brief="Escolhas",
            video_format="quiz_dilemma",
            require_destination=False,
            db_path=self.db_path,
        )["profile"]["id"]
        profile_manager.update_profile_voice_settings(
            self.prof_quiz,
            {"voice_name": None, "voice_rate": None, "voice_volume": None},
            db_path=self.db_path,
        )

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
        shutil.rmtree(self.test_dir, ignore_errors=True)
        if hasattr(sm, "state") and hasattr(sm.state, "_tasks"):
            sm.state._tasks.clear()

    def test_01_channels_and_channel_settings_have_exact_parity(self):
        """(a) /channels e /channels/{id}/settings devolvem settings idênticos em chaves e valores."""
        ov_resp = self.client.get("/api/v2/channels")
        self.assertEqual(ov_resp.status_code, 200, ov_resp.text)
        ov_channels = ov_resp.json()["data"]["channels"]

        for pid in ("default", self.prof_trad, self.prof_quiz):
            ov_item = next((c for c in ov_channels if c.get("profile_id") == pid), None)
            self.assertIsNotNone(ov_item, f"Perfil {pid} ausente em GET /api/v2/channels")

            # Campos de topo legados de /channels continuam intactos
            for legacy_key in (
                "channel_id",
                "profile_id",
                "format",
                "is_quiz",
                "name",
                "slug",
                "niche",
                "language",
                "region",
                "growth_mode",
                "is_active",
                "is_active_profile",
                "autonomous_enabled",
                "target_stock",
                "ready_stock",
                "channel_status",
                "channels_count",
                "channels_enabled",
                "channels",
                "youtube_channel",
                "settings",
            ):
                self.assertIn(legacy_key, ov_item)

            direct_resp = self.client.get(f"/api/v2/channels/{pid}/settings")
            self.assertEqual(direct_resp.status_code, 200, direct_resp.text)
            direct_settings = direct_resp.json()["data"]

            ov_settings = ov_item["settings"]
            self.assertEqual(set(ov_settings.keys()), set(direct_settings.keys()))
            self.assertEqual(ov_settings, direct_settings)

    def test_02_custom_music_volume_voice_rate_and_flow_scenes_in_channels(self):
        """(b) Perfil com music.volume=0.12, voice_rate=1.1 e flow_scene_count=3 reflete correto em /channels."""
        resp = self.client.get("/api/v2/channels")
        self.assertEqual(resp.status_code, 200, resp.text)
        channels = resp.json()["data"]["channels"]

        item = next((c for c in channels if c.get("profile_id") == self.prof_trad), None)
        self.assertIsNotNone(item)
        sett = item["settings"]

        self.assertIn("workspace_settings", sett)
        self.assertIn("effective_voice", sett)
        self.assertEqual(sett["workspace_settings"]["music"]["volume"], 0.12)
        self.assertEqual(sett["workspace_settings"]["visual"]["flow_scene_count"], 3)
        self.assertEqual(sett["effective_voice"]["voice_rate"]["value"], 1.1)
        self.assertEqual(sett["effective_voice"]["voice_rate"]["source"], "channel")

    def test_03_unpinned_voice_shows_global_source_via_channels(self):
        """(c) Perfil sem voz fixada mostra source='global' em effective_voice via /channels."""
        config.ui["voice_name"] = "pt-BR-FranciscaNeural"

        resp = self.client.get("/api/v2/channels")
        self.assertEqual(resp.status_code, 200, resp.text)
        channels = resp.json()["data"]["channels"]

        for pid in (self.prof_trad, self.prof_quiz):
            item = next((c for c in channels if c.get("profile_id") == pid), None)
            self.assertIsNotNone(item)
            eff = item["settings"]["effective_voice"]
            self.assertEqual(eff["voice_name"]["value"], "pt-BR-FranciscaNeural")
            self.assertEqual(eff["voice_name"]["source"], "global")


if __name__ == "__main__":
    unittest.main()
