"""
test/services/test_volume_musica_por_perfil.py
================================================
Testes direcionados da Missão v2/volume-musica-por-perfil:
(a) Perfil sem volume definido (None) preserva equivalência canônica:
    - Quiz (quiz_dilemma, quiz_paper) resolve para 0.14.
    - Tradicional / Autônomo Flow/acervo resolve para 0.20.
(b) Perfil com volume customizado (ex: 0.08):
    - quiz_dilemma, quiz_paper e autônomo usam todos exatamente 0.08.
(c) Validação rejeita valores fora da faixa [0.02, 0.20]:
    - Rejeita < 0.02, > 0.20 e não-numéricos.
    - normalize_volume em ambient_bgm suporta clamp até 0.02.
(d) Endpoint API PATCH /api/v2/channels/{profile_id}/music:
    - Grava com sucesso e emite evento PROFILE_MUSIC_UPDATED.
    - Rejeita valores inválidos (400/422).
    - Permite reset para None (padrão do formato).
(e) Migração legada:
    - Perfis legados com volume=0.2 são migrados de forma segura para None.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from app.services import profile_manager
from app.services import bgm
from app.services import ambient_bgm
from app.services import operator_console
from app import asgi
from fastapi.testclient import TestClient


class TestVolumeMusicaPorPerfil(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_profiles.db")
        profile_manager.init_profile_db(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_profile_without_volume_preserves_compatibility(self):
        """(a) Perfil sem volume (None) preserva quiz=0.14 e autônomo=0.20."""
        # 1. Resolução direta com music_settings = None ou volume = None
        self.assertEqual(
            profile_manager.resolve_effective_bgm_volume(
                music_settings=None,
                video_format="quiz_dilemma",
            ),
            0.14,
        )
        self.assertEqual(
            profile_manager.resolve_effective_bgm_volume(
                music_settings={"volume": None},
                video_format="quiz_paper",
            ),
            0.14,
        )
        self.assertEqual(
            profile_manager.resolve_effective_bgm_volume(
                music_settings={"volume": None},
                video_format="traditional",
            ),
            0.20,
        )

        # 2. Resolução através de bgm.resolve_autonomous_bgm para canal autônomo
        auto_res = bgm.resolve_autonomous_bgm(
            music_settings={"enabled": True, "mode": "auto", "volume": None}
        )
        self.assertEqual(auto_res["volume"], 0.20)
        self.assertEqual(auto_res["type"], "ambient_auto")

        # 3. Contexto operacional completo de geração para perfis onboarded
        prof_quiz = profile_manager.onboard_channel_workspace(
            name="Canal Quiz Dilemma",
            slug="canal-quiz-dilemma",
            niche="curiosidades",
            topic_brief="Dilemas",
            video_format="quiz_dilemma",
            require_destination=False,
            db_path=self.db_path,
        )
        pid_quiz = prof_quiz["profile"]["id"]
        ctx_quiz = profile_manager.get_generation_profile_context(pid_quiz, db_path=self.db_path)
        self.assertIsNone(ctx_quiz["music_volume"])
        self.assertEqual(ctx_quiz["effective_bgm_volume"], 0.14)

        prof_trad = profile_manager.onboard_channel_workspace(
            name="Canal Tradicional",
            slug="canal-tradicional",
            niche="historia",
            topic_brief="Historias",
            video_format="traditional",
            require_destination=False,
            db_path=self.db_path,
        )
        pid_trad = prof_trad["profile"]["id"]
        ctx_trad = profile_manager.get_generation_profile_context(pid_trad, db_path=self.db_path)
        self.assertIsNone(ctx_trad["music_volume"])
        self.assertEqual(ctx_trad["effective_bgm_volume"], 0.20)

    def test_02_profile_with_explicit_volume_used_by_all_pipelines(self):
        """(b) Perfil com 0.08: quiz_dilemma, quiz_paper e autônomo usam todos 0.08."""
        explicit_vol = 0.08

        # 1. Resolução única para quiz_dilemma
        self.assertEqual(
            profile_manager.resolve_effective_bgm_volume(
                music_settings={"volume": explicit_vol},
                video_format="quiz_dilemma",
            ),
            explicit_vol,
        )

        # 2. Resolução única para quiz_paper
        self.assertEqual(
            profile_manager.resolve_effective_bgm_volume(
                music_settings={"volume": explicit_vol},
                video_format="quiz_paper",
            ),
            explicit_vol,
        )

        # 3. Resolução única para autônomo / tradicional
        self.assertEqual(
            profile_manager.resolve_effective_bgm_volume(
                music_settings={"volume": explicit_vol},
                video_format="traditional",
            ),
            explicit_vol,
        )

        # 4. Pipeline autônomo via bgm.resolve_autonomous_bgm
        auto_res = bgm.resolve_autonomous_bgm(
            music_settings={"enabled": True, "mode": "auto", "volume": explicit_vol}
        )
        self.assertEqual(auto_res["volume"], explicit_vol)

        # 5. Gravando via update_profile_music_settings e verificando context
        prof = profile_manager.onboard_channel_workspace(
            name="Canal Ajustado",
            slug="canal-ajustado",
            niche="variedades",
            topic_brief="Variados",
            video_format="quiz_dilemma",
            require_destination=False,
            db_path=self.db_path,
        )
        pid = prof["profile"]["id"]

        with patch("app.services.operator_console.require_primary_instance", return_value=True):
            profile_manager.update_profile_music_settings(
                pid,
                {"volume": explicit_vol},
                db_path=self.db_path,
            )

        ctx = profile_manager.get_generation_profile_context(pid, db_path=self.db_path)
        self.assertEqual(ctx["music_volume"], explicit_vol)
        self.assertEqual(ctx["effective_bgm_volume"], explicit_vol)

    def test_03_validation_bounds_strict(self):
        """(c) Validação rejeita fora de [0.02, 0.20] e normalize_volume suporta clamp 0.02."""
        prof = profile_manager.onboard_channel_workspace(
            name="Canal Validação",
            slug="canal-validacao",
            niche="teste",
            topic_brief="Teste",
            require_destination=False,
            db_path=self.db_path,
        )
        pid = prof["profile"]["id"]

        with patch("app.services.operator_console.require_primary_instance", return_value=True):
            # Limites válidos: 0.02 e 0.20
            res_min = profile_manager.update_profile_music_settings(pid, {"volume": 0.02}, db_path=self.db_path)
            self.assertEqual(res_min.volume, 0.02)

            res_max = profile_manager.update_profile_music_settings(pid, {"volume": 0.20}, db_path=self.db_path)
            self.assertEqual(res_max.volume, 0.20)

            # Rejeita < 0.02
            with self.assertRaises(ValueError):
                profile_manager.update_profile_music_settings(pid, {"volume": 0.019}, db_path=self.db_path)

            with self.assertRaises(ValueError):
                profile_manager.update_profile_music_settings(pid, {"volume": -0.1}, db_path=self.db_path)

            # Rejeita > 0.20
            with self.assertRaises(ValueError):
                profile_manager.update_profile_music_settings(pid, {"volume": 0.21}, db_path=self.db_path)

            # Rejeita não-numérico
            with self.assertRaises(ValueError):
                profile_manager.update_profile_music_settings(pid, {"volume": "invalido"}, db_path=self.db_path)

        # ambient_bgm.normalize_volume suporta faixa [0.02, 0.20]
        self.assertEqual(ambient_bgm.normalize_volume(0.02), 0.02)
        self.assertEqual(ambient_bgm.normalize_volume(0.08), 0.08)
        self.assertEqual(ambient_bgm.normalize_volume(0.20), 0.20)
        self.assertEqual(ambient_bgm.normalize_volume(0.01), 0.02)  # clamp inferior
        self.assertEqual(ambient_bgm.normalize_volume(0.30), 0.20)  # clamp superior

    def test_04_api_patch_music_and_event(self):
        """(d) API PATCH /api/v2/channels/{profile_id}/music grava e emite PROFILE_MUSIC_UPDATED."""
        prof = profile_manager.onboard_channel_workspace(
            name="Canal API Music",
            slug="canal-api-music",
            niche="games",
            topic_brief="GTA VI",
            require_destination=False,
            db_path=self.db_path,
        )
        pid = prof["profile"]["id"]

        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.require_primary_instance", return_value=True), \
             patch("app.services.operator_console.log_operational_event") as mock_log:

            client = TestClient(asgi.app)

            # 1. PATCH com volume 0.08
            resp = client.patch(f"/api/v2/channels/{pid}/music", json={"volume": 0.08})
            self.assertEqual(resp.status_code, 200, resp.text)
            data = resp.json()["data"]
            self.assertEqual(data.get("volume"), 0.08)

            # Confirma que evento operacional foi disparado
            mock_log.assert_called_once()
            call_kwargs = mock_log.call_args.kwargs
            self.assertEqual(call_kwargs.get("event_type"), "PROFILE_MUSIC_UPDATED")
            self.assertEqual(call_kwargs.get("metadata", {}).get("old_value"), None)
            self.assertEqual(call_kwargs.get("metadata", {}).get("new_value"), 0.08)

            # Confirma persistência no DB
            settings = profile_manager.get_profile_settings(pid, db_path=self.db_path)
            self.assertEqual(settings.music.volume, 0.08)

            # 2. PATCH com valor inválido (< 0.02) -> 400 ou 422
            resp_low = client.patch(f"/api/v2/channels/{pid}/music", json={"volume": 0.01})
            self.assertIn(resp_low.status_code, (400, 422))

            # 3. PATCH com valor inválido (> 0.20) -> 400 ou 422
            resp_high = client.patch(f"/api/v2/channels/{pid}/music", json={"volume": 0.25})
            self.assertIn(resp_high.status_code, (400, 422))

            # 4. PATCH restaurando padrão do formato (None)
            resp_reset = client.patch(f"/api/v2/channels/{pid}/music", json={"volume": None})
            self.assertEqual(resp_reset.status_code, 200, resp_reset.text)
            settings_after = profile_manager.get_profile_settings(pid, db_path=self.db_path)
            self.assertIsNone(settings_after.music.volume)

    def test_05_legacy_db_migration(self):
        """(e) Migração legada: perfis com volume=0.2 são convertidos para None mantendo equivalência."""
        # Cria banco simulando versão legada (sem a tabela schema_migrations e com volume=0.2 em settings_json)
        legacy_db = os.path.join(self.test_dir, "legacy.db")
        with profile_manager.get_connection(legacy_db) as conn:
            conn.execute(
                """
                CREATE TABLE content_profiles (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    slug TEXT UNIQUE NOT NULL,
                    niche TEXT,
                    language TEXT,
                    region TEXT,
                    default_preset TEXT,
                    growth_mode TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    settings_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            # Perfil quiz legado com volume: 0.2 gerado automaticamente pelo schema antigo
            legacy_settings = (
                '{"schema_version": 1, "editorial": {"video_format": "quiz_dilemma"}, '
                '"music": {"enabled": false, "mode": "auto", "volume": 0.2, "default_mood": "neutral"}}'
            )
            conn.execute(
                "INSERT INTO content_profiles (id, name, slug, settings_json, created_at, updated_at) "
                "VALUES ('prof-legacy-quiz', 'Quiz Legado', 'quiz-legado', ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');",
                (legacy_settings,),
            )

        # Executa init_profile_db (com force=True para forçar inicialização do novo db_path)
        profile_manager.init_profile_db(legacy_db, force=True)

        # Verifica que o volume foi migrado para None
        migrated_settings = profile_manager.get_profile_settings("prof-legacy-quiz", db_path=legacy_db)
        self.assertIsNone(migrated_settings.music.volume)

        # E agora quiz herda o padrão do formato (0.14) sem salto indevido para 0.20!
        ctx = profile_manager.get_generation_profile_context("prof-legacy-quiz", db_path=legacy_db)
        self.assertEqual(ctx["effective_bgm_volume"], 0.14)


if __name__ == "__main__":
    unittest.main()
