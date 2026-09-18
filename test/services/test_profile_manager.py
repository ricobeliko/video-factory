"""
Testes unitários para o Profile Manager (Fase V9-A — Multi-Profile Foundation).
"""
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from app.models import const
from app.services import operator_console, profile_manager


class TestProfileManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_video_factory.db")
        operator_console.init_operator_db(self.db_path)
        operator_console.reset_instance_for_testing()
        # Garante nó local como PRIMARY para testes com mutação
        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._current_role = operator_console.ROLE_PRIMARY

    def tearDown(self):
        operator_console.reset_instance_for_testing()
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    # 1. default profile criado
    def test_01_default_profile_created(self):
        prof = profile_manager.ensure_default_profile(db_path=self.db_path)
        self.assertIsNotNone(prof)
        self.assertEqual(prof.get("id"), profile_manager.DEFAULT_PROFILE_ID)
        self.assertEqual(prof.get("name"), profile_manager.DEFAULT_PROFILE_NAME)
        self.assertEqual(prof.get("slug"), profile_manager.DEFAULT_PROFILE_SLUG)
        self.assertEqual(prof.get("is_active"), 1)

    # 2. inicialização idempotente
    def test_02_idempotent_initialization(self):
        prof1 = profile_manager.ensure_default_profile(db_path=self.db_path)
        prof2 = profile_manager.ensure_default_profile(db_path=self.db_path)
        self.assertEqual(prof1.get("id"), prof2.get("id"))
        all_profiles = profile_manager.list_profiles(db_path=self.db_path)
        self.assertEqual(len(all_profiles), 1)

    # 3. create profile
    def test_03_create_profile(self):
        prof = profile_manager.create_profile(
            name="Curiosidades Brasil",
            niche="curiosidades",
            language="pt-BR",
            region="BR",
            default_preset=const.PRESET_CROSS_PLATFORM,
            growth_mode=const.GROWTH_MODE_CONSERVATIVE,
            is_active=True,
            db_path=self.db_path,
        )
        self.assertIsNotNone(prof)
        self.assertEqual(prof.get("name"), "Curiosidades Brasil")
        self.assertEqual(prof.get("niche"), "curiosidades")
        self.assertEqual(prof.get("growth_mode"), const.GROWTH_MODE_CONSERVATIVE)
        self.assertEqual(prof.get("default_preset"), const.PRESET_CROSS_PLATFORM)

    # 4. slug gerado corretamente
    def test_04_slug_generated_correctly(self):
        slug = profile_manager.generate_slug("Histórias & Mistérios", db_path=self.db_path)
        self.assertEqual(slug, "historias-misterios")

    # 5. slug único
    def test_05_slug_uniqueness(self):
        p1 = profile_manager.create_profile(
            name="Histórias BR",
            db_path=self.db_path,
        )
        p2 = profile_manager.create_profile(
            name="Histórias BR",
            db_path=self.db_path,
        )
        self.assertEqual(p1.get("slug"), "historias-br")
        self.assertEqual(p2.get("slug"), "historias-br-2")

    # 6. update profile
    def test_06_update_profile(self):
        prof = profile_manager.create_profile(
            name="Canal Original",
            niche="tecnologia",
            db_path=self.db_path,
        )
        updated = profile_manager.update_profile(
            profile_id=prof["id"],
            name="Canal Renomeado",
            growth_mode=const.GROWTH_MODE_SCALE,
            db_path=self.db_path,
        )
        self.assertEqual(updated.get("name"), "Canal Renomeado")
        self.assertEqual(updated.get("growth_mode"), const.GROWTH_MODE_SCALE)
        self.assertEqual(updated.get("niche"), "tecnologia")

    # 7. list profiles
    def test_07_list_profiles(self):
        profile_manager.ensure_default_profile(db_path=self.db_path)
        profile_manager.create_profile(name="Canal Ativo", is_active=True, db_path=self.db_path)
        profile_manager.create_profile(name="Canal Inativo", is_active=False, db_path=self.db_path)

        all_p = profile_manager.list_profiles(active_only=False, db_path=self.db_path)
        active_p = profile_manager.list_profiles(active_only=True, db_path=self.db_path)

        self.assertEqual(len(all_p), 3)  # default + 2 criados
        self.assertEqual(len(active_p), 2)  # default + 1 ativo

    # 8. activate/deactivate
    def test_08_activate_deactivate(self):
        prof = profile_manager.create_profile(name="Canal Toggle", is_active=True, db_path=self.db_path)
        pid = prof["id"]

        success = profile_manager.set_profile_active(pid, False, db_path=self.db_path)
        self.assertTrue(success)
        self.assertEqual(profile_manager.get_profile(pid, db_path=self.db_path).get("is_active"), 0)

        success = profile_manager.set_profile_active(pid, True, db_path=self.db_path)
        self.assertTrue(success)
        self.assertEqual(profile_manager.get_profile(pid, db_path=self.db_path).get("is_active"), 1)

    # 9. growth mode válido
    def test_09_valid_growth_modes(self):
        for mode in const.GROWTH_MODES:
            prof = profile_manager.create_profile(
                name=f"Profile {mode}",
                growth_mode=mode,
                db_path=self.db_path,
            )
            self.assertEqual(prof.get("growth_mode"), mode)

    # 10. growth mode inválido rejeitado
    def test_10_invalid_growth_mode_rejected(self):
        with self.assertRaises(ValueError):
            profile_manager.create_profile(
                name="Profile Inválido",
                growth_mode="turbo_boost",
                db_path=self.db_path,
            )

    # 11. preset válido
    def test_11_valid_presets(self):
        for preset in const.MONETIZATION_PRESET_CHOICES:
            prof = profile_manager.create_profile(
                name=f"Profile {preset}",
                default_preset=preset,
                db_path=self.db_path,
            )
            self.assertEqual(prof.get("default_preset"), preset)

    # 12. preset inválido rejeitado
    def test_12_invalid_preset_rejected(self):
        with self.assertRaises(ValueError):
            profile_manager.create_profile(
                name="Profile Presets Errados",
                default_preset="cinema_4k_hdr",
                db_path=self.db_path,
            )

    # 13. create YouTube channel
    def test_13_create_youtube_channel(self):
        prof = profile_manager.ensure_default_profile(db_path=self.db_path)
        ch = profile_manager.create_channel(
            profile_id=prof["id"],
            platform="youtube",
            display_name="Canal Principal YT",
            external_profile_name="yt_channel_id",
            db_path=self.db_path,
        )
        self.assertEqual(ch.get("platform"), "youtube")
        self.assertEqual(ch.get("display_name"), "Canal Principal YT")
        self.assertEqual(ch.get("is_enabled"), 1)

    # 14. create TikTok channel
    def test_14_create_tiktok_channel(self):
        prof = profile_manager.ensure_default_profile(db_path=self.db_path)
        ch = profile_manager.create_channel(
            profile_id=prof["id"],
            platform="tiktok",
            display_name="TikTok Curiosidades",
            external_profile_name="tt_handle",
            db_path=self.db_path,
        )
        self.assertEqual(ch.get("platform"), "tiktok")
        self.assertEqual(ch.get("display_name"), "TikTok Curiosidades")
        self.assertEqual(ch.get("is_enabled"), 1)

    # 15. plataforma inválida rejeitada
    def test_15_invalid_platform_rejected(self):
        prof = profile_manager.ensure_default_profile(db_path=self.db_path)
        with self.assertRaises(ValueError):
            profile_manager.create_channel(
                profile_id=prof["id"],
                platform="instagram",
                display_name="Canal Insta",
                db_path=self.db_path,
            )

        with self.assertRaises(ValueError):
            profile_manager.create_channel(
                profile_id=prof["id"],
                platform="kwai",
                display_name="Canal Kwai",
                db_path=self.db_path,
            )

    # 16. channel pertence ao profile correto
    def test_16_channel_belongs_to_correct_profile(self):
        p1 = profile_manager.create_profile(name="Profile Um", db_path=self.db_path)
        p2 = profile_manager.create_profile(name="Profile Dois", db_path=self.db_path)

        ch1 = profile_manager.create_channel(profile_id=p1["id"], platform="youtube", display_name="YT 1", db_path=self.db_path)
        ch2 = profile_manager.create_channel(profile_id=p2["id"], platform="tiktok", display_name="TT 2", db_path=self.db_path)

        p1_channels = profile_manager.list_channels(profile_id=p1["id"], db_path=self.db_path)
        p2_channels = profile_manager.list_channels(profile_id=p2["id"], db_path=self.db_path)

        self.assertEqual([c["id"] for c in p1_channels], [ch1["id"]])
        self.assertEqual([c["id"] for c in p2_channels], [ch2["id"]])

    # 17. desabilitar channel
    def test_17_disable_channel(self):
        prof = profile_manager.ensure_default_profile(db_path=self.db_path)
        ch = profile_manager.create_channel(
            profile_id=prof["id"],
            platform="youtube",
            display_name="Canal Temporário",
            is_enabled=True,
            db_path=self.db_path,
        )
        cid = ch["id"]
        profile_manager.set_channel_enabled(cid, False, db_path=self.db_path)

        updated = profile_manager.get_channel(cid, db_path=self.db_path)
        self.assertEqual(updated.get("is_enabled"), 0)

        enabled_chs = profile_manager.list_channels(profile_id=prof["id"], enabled_only=True, db_path=self.db_path)
        self.assertNotIn(cid, [c["id"] for c in enabled_chs])

    # 18. nenhuma secret persistida
    def test_18_no_secrets_persisted(self):
        profile_manager.init_profile_db(db_path=self.db_path)
        with profile_manager.get_connection(self.db_path) as conn:
            prof_cols = [r["name"].lower() for r in conn.execute("PRAGMA table_info(content_profiles);").fetchall()]
            chan_cols = [r["name"].lower() for r in conn.execute("PRAGMA table_info(publishing_channels);").fetchall()]

        forbidden_keywords = ["token", "secret", "password", "key", "oauth", "cookie"]
        for col in prof_cols + chan_cols:
            for forbidden in forbidden_keywords:
                # Não deve haver colunas de credenciais/senhas
                self.assertNotIn(forbidden, col)

    # 19. leitura funciona em VIEW ONLY
    def test_19_read_operations_allowed_in_view_only(self):
        profile_manager.ensure_default_profile(db_path=self.db_path)

        # Coloca instância em modo SECONDARY_VIEW_ONLY
        with operator_console._instance_state_lock:
            operator_console._current_role = operator_console.ROLE_SECONDARY_VIEW_ONLY

        with patch.object(operator_console, "is_primary_instance", return_value=False):
            prof = profile_manager.get_profile(profile_manager.DEFAULT_PROFILE_ID, db_path=self.db_path)
            self.assertIsNotNone(prof)

            profs = profile_manager.list_profiles(db_path=self.db_path)
            self.assertIsInstance(profs, list)

            channels = profile_manager.list_channels(db_path=self.db_path)
            self.assertIsInstance(channels, list)

            default_p = profile_manager.get_default_profile(db_path=self.db_path)
            self.assertEqual(default_p.get("id"), profile_manager.DEFAULT_PROFILE_ID)

    # 20. mutação respeita PRIMARY quando aplicável
    def test_20_mutations_blocked_in_view_only(self):
        profile_manager.ensure_default_profile(db_path=self.db_path)

        # Coloca instância em modo SECONDARY_VIEW_ONLY
        with operator_console._instance_state_lock:
            operator_console._current_role = operator_console.ROLE_SECONDARY_VIEW_ONLY

        with patch.object(operator_console, "is_primary_instance", return_value=False):
            with self.assertRaises(PermissionError):
                profile_manager.create_profile(name="Tentativa Bloqueada", db_path=self.db_path)

            with self.assertRaises(PermissionError):
                profile_manager.update_profile(profile_id="default", name="Novo Nome", db_path=self.db_path)

            with self.assertRaises(PermissionError):
                profile_manager.set_profile_active("default", False, db_path=self.db_path)

            with self.assertRaises(PermissionError):
                profile_manager.create_channel(profile_id="default", platform="youtube", display_name="YT", db_path=self.db_path)

            with self.assertRaises(PermissionError):
                profile_manager.update_channel(channel_id="channel-default-youtube", display_name="Novo YT", db_path=self.db_path)

            with self.assertRaises(PermissionError):
                profile_manager.set_channel_enabled("channel-default-youtube", False, db_path=self.db_path)

    # 21. compatibilidade com DEFAULT PROFILE
    def test_21_compatibility_with_default_profile(self):
        default_prof = profile_manager.get_default_profile(db_path=self.db_path)
        self.assertEqual(default_prof.get("id"), "default")
        self.assertEqual(default_prof.get("slug"), "default")
        self.assertEqual(default_prof.get("name"), "Video Factory Default")
        self.assertEqual(default_prof.get("growth_mode"), const.DEFAULT_GROWTH_MODE)
        self.assertEqual(default_prof.get("default_preset"), const.DEFAULT_MONETIZATION_PRESET)

        # Verifica que canais padrão para YouTube e TikTok foram inicializados
        channels = profile_manager.list_channels(profile_id="default", db_path=self.db_path)
        platforms = [c.get("platform") for c in channels]
        self.assertIn("youtube", platforms)
        self.assertIn("tiktok", platforms)


if __name__ == "__main__":
    unittest.main()
