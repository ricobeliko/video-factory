"""
Testes de Geração por Perfil e Profile Selector (Fase V9-B).
Validação dos 20 cenários obrigatórios especificados.
"""
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from app.models import const
from app.models.schema import VideoParams
from app.services import operator_console, profile_manager, state as sm, webui_task


class TestProfileGeneration(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_video_factory.db")
        operator_console.init_operator_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        operator_console.reset_instance_for_testing()

        # Garante nó local como PRIMARY
        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._current_role = operator_console.ROLE_PRIMARY

        # Configura o profile_manager para usar o DB temporário
        self.orig_get_db_path = profile_manager.get_db_path
        profile_manager.get_db_path = lambda custom=None: custom or self.db_path

        self.paused_patcher = patch("app.services.operator_console.is_factory_paused", return_value=False)
        self.paused_patcher.start()

    def tearDown(self):
        self.paused_patcher.stop()
        profile_manager.get_db_path = self.orig_get_db_path
        operator_console.reset_instance_for_testing()
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    # 1. default active profile
    def test_01_default_active_profile(self):
        active_id = profile_manager.get_active_profile_id(db_path=self.db_path)
        self.assertEqual(active_id, profile_manager.DEFAULT_PROFILE_ID)
        active_prof = profile_manager.get_active_profile(db_path=self.db_path)
        self.assertEqual(active_prof["id"], profile_manager.DEFAULT_PROFILE_ID)
        self.assertEqual(active_prof["name"], profile_manager.DEFAULT_PROFILE_NAME)

    # 2. set active profile
    def test_02_set_active_profile(self):
        p = profile_manager.create_profile(
            name="Curiosidades Brasil",
            niche="curiosidades",
            language="pt-BR",
            region="BR",
            default_preset=const.PRESET_CROSS_PLATFORM,
            db_path=self.db_path,
        )
        profile_manager.set_active_profile(p["id"], db_path=self.db_path)
        self.assertEqual(profile_manager.get_active_profile_id(db_path=self.db_path), p["id"])
        active = profile_manager.get_active_profile(db_path=self.db_path)
        self.assertEqual(active["id"], p["id"])
        self.assertEqual(active["name"], "Curiosidades Brasil")

    # 3. profile inativo não pode ficar ativo
    def test_03_inactive_profile_cannot_be_active(self):
        p = profile_manager.create_profile(
            name="Canal Desativado",
            is_active=False,
            db_path=self.db_path,
        )
        with self.assertRaises(ValueError):
            profile_manager.set_active_profile(p["id"], db_path=self.db_path)

        # Se for forçado no DB como inativo, get_active_profile_id deve fazer fallback para default
        with profile_manager.get_connection(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES (?, ?);",
                (profile_manager.ACTIVE_PROFILE_SETTING_KEY, p["id"]),
            )
        self.assertEqual(profile_manager.get_active_profile_id(db_path=self.db_path), profile_manager.DEFAULT_PROFILE_ID)

    # 4. profile inexistente faz fallback default
    def test_04_nonexistent_profile_fallback_default(self):
        with self.assertRaises(ValueError):
            profile_manager.set_active_profile("non_existent_uuid_123", db_path=self.db_path)

        # Se houver id inválido salvo no SQLite, fallback para default
        with profile_manager.get_connection(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES (?, ?);",
                (profile_manager.ACTIVE_PROFILE_SETTING_KEY, "ghost-id"),
            )
        self.assertEqual(profile_manager.get_active_profile_id(db_path=self.db_path), profile_manager.DEFAULT_PROFILE_ID)
        self.assertEqual(profile_manager.get_active_profile(db_path=self.db_path)["id"], profile_manager.DEFAULT_PROFILE_ID)

    # 5. VIEW ONLY pode ler active profile
    def test_05_view_only_can_read_active_profile(self):
        p = profile_manager.create_profile(
            name="Leitura Permissível",
            db_path=self.db_path,
        )
        profile_manager.set_active_profile(p["id"], db_path=self.db_path)

        # Muda nó para SECONDARY_VIEW_ONLY
        with operator_console._instance_state_lock:
            operator_console._current_role = operator_console.ROLE_SECONDARY_VIEW_ONLY

        active_id = profile_manager.get_active_profile_id(db_path=self.db_path)
        self.assertEqual(active_id, p["id"])
        active_prof = profile_manager.get_active_profile(db_path=self.db_path)
        self.assertEqual(active_prof["id"], p["id"])

    # 6. VIEW ONLY não pode trocar profile
    def test_06_view_only_cannot_change_profile(self):
        p = profile_manager.create_profile(
            name="Canal Teste Mutação",
            db_path=self.db_path,
        )
        # Muda nó para SECONDARY_VIEW_ONLY
        with operator_console._instance_state_lock:
            operator_console._current_role = operator_console.ROLE_SECONDARY_VIEW_ONLY

        with self.assertRaises((PermissionError, RuntimeError)) as ctx:
            profile_manager.set_active_profile(p["id"], db_path=self.db_path)
        self.assertIn("Operação bloqueada", str(ctx.exception))

    # 7. geração usa niche do profile
    @patch("app.services.webui_task._task_manager.add_task")
    def test_07_generation_uses_profile_niche(self, mock_add_task):
        p = profile_manager.create_profile(
            name="Canal Astronomia",
            niche="astronomia_avancada",
            db_path=self.db_path,
        )
        profile_manager.set_active_profile(p["id"], db_path=self.db_path)

        params = VideoParams(video_subject="Buracos Negros")
        webui_task.submit_generation(task_id="task_niche_01", params=params)

        saved = sm.state.get_task("task_niche_01")
        self.assertIsNotNone(saved)
        self.assertEqual(saved.get("niche"), "astronomia_avancada")

    # 8. geração usa language do profile
    @patch("app.services.webui_task._task_manager.add_task")
    def test_08_generation_uses_profile_language(self, mock_add_task):
        p = profile_manager.create_profile(
            name="Canal Global English",
            language="en-US",
            db_path=self.db_path,
        )
        profile_manager.set_active_profile(p["id"], db_path=self.db_path)

        params = VideoParams(video_subject="Space Exploration")
        webui_task.submit_generation(task_id="task_lang_01", params=params)

        call_args = mock_add_task.call_args[1]
        passed_params = call_args["params"]
        self.assertEqual(passed_params.video_language, "en-US")

    # 9. geração usa region do profile
    @patch("app.services.webui_task._task_manager.add_task")
    def test_09_generation_uses_profile_region(self, mock_add_task):
        p = profile_manager.create_profile(
            name="Canal US Content",
            region="US",
            db_path=self.db_path,
        )
        profile_manager.set_active_profile(p["id"], db_path=self.db_path)

        params = VideoParams(video_subject="US Politics")
        webui_task.submit_generation(task_id="task_reg_01", params=params)

        call_args = mock_add_task.call_args[1]
        passed_params = call_args["params"]
        self.assertEqual(passed_params.region, "US")

    # 10. geração usa preset do profile
    @patch("app.services.webui_task._task_manager.add_task")
    def test_10_generation_uses_profile_preset(self, mock_add_task):
        p = profile_manager.create_profile(
            name="Canal TikTok Exclusivo",
            default_preset=const.PRESET_TIKTOK_REWARDS,
            db_path=self.db_path,
        )
        profile_manager.set_active_profile(p["id"], db_path=self.db_path)

        # Usuário não informou preset explicitamente
        params = VideoParams(video_subject="Trend Rápida")
        webui_task.submit_generation(task_id="task_preset_01", params=params)

        call_args = mock_add_task.call_args[1]
        passed_params = call_args["params"]
        self.assertEqual(passed_params.monetization_preset, const.PRESET_TIKTOK_REWARDS)

    # 11. manual override vence profile
    @patch("app.services.webui_task._task_manager.add_task")
    def test_11_manual_override_beats_profile(self, mock_add_task):
        p = profile_manager.create_profile(
            name="Perfil Padrão",
            niche="nicho_perfil",
            language="pt-BR",
            region="BR",
            default_preset=const.PRESET_TIKTOK_REWARDS,
            db_path=self.db_path,
        )
        profile_manager.set_active_profile(p["id"], db_path=self.db_path)

        # Usuário informou explicitamente campos manuais divergentes
        params = VideoParams(
            video_subject="Override Test",
            niche="manual_niche",
            video_language="es-ES",
            region="ES",
            monetization_preset=const.PRESET_YOUTUBE_ORIGINAL,
        )
        webui_task.submit_generation(task_id="task_override_01", params=params)

        call_args = mock_add_task.call_args[1]
        passed = call_args["params"]
        self.assertEqual(passed.niche, "manual_niche")
        self.assertEqual(passed.video_language, "es-ES")
        self.assertEqual(passed.region, "ES")
        self.assertEqual(passed.monetization_preset, const.PRESET_YOUTUBE_ORIGINAL)

    # 12. profile vence fallback global
    def test_12_profile_beats_global_fallback(self):
        p = profile_manager.create_profile(
            name="Perfil Especial",
            niche="nicho_customizado_v9",
            language="de-DE",
            region="DE",
            default_preset=const.PRESET_YOUTUBE_ORIGINAL,
            db_path=self.db_path,
        )
        ctx = profile_manager.get_generation_profile_context(p["id"], db_path=self.db_path)
        self.assertEqual(ctx["niche"], "nicho_customizado_v9")
        self.assertEqual(ctx["language"], "de-DE")
        self.assertEqual(ctx["region"], "DE")
        self.assertEqual(ctx["default_preset"], const.PRESET_YOUTUBE_ORIGINAL)

    # 13. fallback global continua funcionando
    def test_13_global_fallback_still_works(self):
        ctx = profile_manager.get_generation_profile_context("default", db_path=self.db_path)
        self.assertTrue(bool(ctx["niche"]))
        self.assertTrue(bool(ctx["language"]))
        self.assertTrue(bool(ctx["region"]))
        self.assertEqual(ctx["default_preset"], const.DEFAULT_MONETIZATION_PRESET)

    # 14. Autopilot recebe contexto do profile
    def test_14_autopilot_receives_profile_context(self):
        p = profile_manager.create_profile(
            name="Autopilot Profile",
            niche="curiosidades_historicas",
            language="pt-BR",
            region="BR",
            default_preset=const.PRESET_CROSS_PLATFORM,
            growth_mode=const.GROWTH_MODE_SCALE,
            db_path=self.db_path,
        )
        profile_manager.set_active_profile(p["id"], db_path=self.db_path)
        ctx = profile_manager.get_generation_profile_context(db_path=self.db_path)

        self.assertEqual(ctx["profile_id"], p["id"])
        self.assertEqual(ctx["niche"], "curiosidades_historicas")
        self.assertEqual(ctx["growth_mode"], const.GROWTH_MODE_SCALE)

    # 15. task recebe profile_id
    @patch("app.services.webui_task._task_manager.add_task")
    def test_15_task_receives_profile_id(self, mock_add_task):
        p = profile_manager.create_profile(
            name="Canal Associado",
            db_path=self.db_path,
        )
        profile_manager.set_active_profile(p["id"], db_path=self.db_path)

        params = VideoParams(video_subject="Associação Task")
        webui_task.submit_generation(task_id="task_assoc_15", params=params)

        self.assertEqual(profile_manager.get_task_profile_id("task_assoc_15", db_path=self.db_path), p["id"])
        task_state = sm.state.get_task("task_assoc_15")
        self.assertEqual(task_state.get("profile_id"), p["id"])

    # 16. task antiga sem profile_id resolve default
    def test_16_legacy_task_resolves_default(self):
        resolved_pid = profile_manager.get_task_profile_id("legacy_task_9999", db_path=self.db_path)
        self.assertEqual(resolved_pid, profile_manager.DEFAULT_PROFILE_ID)

    # 17. trocar active profile não altera task já criada
    @patch("app.services.webui_task._task_manager.add_task")
    def test_17_changing_active_profile_does_not_alter_existing_task(self, mock_add_task):
        p1 = profile_manager.create_profile(name="Perfil Alpha", db_path=self.db_path)
        p2 = profile_manager.create_profile(name="Perfil Beta", db_path=self.db_path)

        profile_manager.set_active_profile(p1["id"], db_path=self.db_path)
        params = VideoParams(video_subject="Video Alpha")
        webui_task.submit_generation(task_id="task_immutable_17", params=params)

        self.assertEqual(profile_manager.get_task_profile_id("task_immutable_17", db_path=self.db_path), p1["id"])

        # Muda active profile para Beta
        profile_manager.set_active_profile(p2["id"], db_path=self.db_path)
        self.assertEqual(profile_manager.get_active_profile_id(db_path=self.db_path), p2["id"])

        # Task anterior continua pertencendo a Alpha (imutabilidade)
        self.assertEqual(profile_manager.get_task_profile_id("task_immutable_17", db_path=self.db_path), p1["id"])

    # 18. profile_id inválido não quebra leitura
    def test_18_invalid_profile_id_safe_reading(self):
        self.assertEqual(profile_manager.get_task_profile_id("", db_path=self.db_path), profile_manager.DEFAULT_PROFILE_ID)
        self.assertEqual(profile_manager.get_task_profile_id(None, db_path=self.db_path), profile_manager.DEFAULT_PROFILE_ID)
        ctx = profile_manager.get_generation_profile_context("invalid_uuid_non_existing", db_path=self.db_path)
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx["profile_id"], profile_manager.DEFAULT_PROFILE_ID)

    # 19. Operator Console exibe active profile
    def test_19_operator_console_displays_active_profile(self):
        p = profile_manager.create_profile(name="Console Profile", db_path=self.db_path)
        profile_manager.set_active_profile(p["id"], db_path=self.db_path)

        active = profile_manager.get_active_profile(db_path=self.db_path)
        self.assertEqual(active["name"], "Console Profile")
        self.assertEqual(active["slug"], "console-profile")

    # 20. single-instance safety preservada
    def test_20_single_instance_safety_preserved(self):
        p = profile_manager.create_profile(name="Single Instance Safety", db_path=self.db_path)

        # Torna nó VIEW ONLY
        with operator_console._instance_state_lock:
            operator_console._current_role = operator_console.ROLE_SECONDARY_VIEW_ONLY

        # Leitura permitida
        self.assertIsNotNone(profile_manager.get_active_profile_id(db_path=self.db_path))
        self.assertIsNotNone(profile_manager.get_generation_profile_context(db_path=self.db_path))

        # Mutação bloqueada
        with self.assertRaises((PermissionError, RuntimeError)):
            profile_manager.set_active_profile(p["id"], db_path=self.db_path)


if __name__ == "__main__":
    unittest.main()
