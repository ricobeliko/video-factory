"""
Testes direcionados da Fase V16.1 — Brazilian Content Contract.

Cobertura estrita dos requisitos canônicos:
1. UI/config contém voice_name = "af-ZA-AdriNeural-Female" -> autonomous params rejeita com AutonomousConfigError.
2. video_language global ausente/None -> autonomous params continua "pt-BR" pelo contrato.
3. subtitle_enabled global/UI = False -> autonomous params retorna True.
4. text_fore_color = "#000000" -> autonomous params retorna "#FFFFFF".
5. stroke_color permanece preto ("#000000") e stroke_width >= 1.5 (default 2.0).
6. TTS + voice pt-BR válida (pt-BR-AntonioNeural, pt-BR-FranciscaNeural, pt-BR-ThalitaMultilingualNeural) -> PASS.
7. TTS + voice pt-PT (pt-PT-RaquelNeural, pt-PT-DuarteNeural) -> BLOCK.
8. TTS + voice en-US (en-US-GuyNeural, en-US-JennyNeural) -> BLOCK.
9. TTS + voice af-ZA (af-ZA-AdriNeural-Female) -> BLOCK.
10. Perfil 'default' -> language final = "pt-BR", region final = "BR".
11. Perfil 'profile-historias-misterio' -> language final = "pt-BR", region final = "BR".
12. Geração manual não é alterada inadvertidamente (VideoParams livre, contrato autônomo fail-closed).
13. match_materials_to_script default autônomo = True e video_concat_mode = sequential.
"""

import os
import tempfile
import unittest

from app.config import config
from app.models.schema import VideoConcatMode, VideoParams
from app.services import autonomous_production, profile_manager


class TestV16_1BrazilianContentContract(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_dir = self.temp_dir.name
        self.db_path = os.path.join(self.tmp_dir, "test_v16_1.db")

        # Inicializa banco de dados com perfis padrão
        profile_manager.init_profile_db(self.db_path)
        profile_manager.ensure_default_profile(db_path=self.db_path)

        # Salva estado original das configurações globais
        self._orig_ui = dict(config.ui)
        self._orig_app = dict(config.app)

        # Configura base limpa com voz válida pt-BR
        config.ui["voice_mode"] = "tts"
        config.ui["voice_name"] = "pt-BR-AntonioNeural-Male"
        config.ui["video_source"] = "pexels"
        config.app["video_source"] = "pexels"
        config.app["video_language"] = "pt-BR"
        config.app["default_region"] = "BR"

    def tearDown(self):
        config.ui.clear()
        config.ui.update(self._orig_ui)
        config.app.clear()
        config.app.update(self._orig_app)
        self.temp_dir.cleanup()

    def test_01_foreign_af_za_voice_in_ui_config_rejected(self):
        """1. UI/config contém voice_name af-ZA-AdriNeural-Female -> autonomous params NÃO aceita essa voz."""
        config.ui["voice_name"] = "af-ZA-AdriNeural-Female"

        with self.assertRaises(autonomous_production.AutonomousConfigError) as ctx:
            autonomous_production.build_autonomous_video_params("Tema Teste", db_path=self.db_path)

        self.assertIn("af-ZA-AdriNeural-Female", str(ctx.exception))
        self.assertIn("não pertence ao locale pt-BR", str(ctx.exception))

    def test_02_video_language_missing_or_none_defaults_to_pt_br(self):
        """2. video_language global ausente/None -> autonomous params continua pt-BR pelo contrato."""
        config.app["video_language"] = None

        params = autonomous_production.build_autonomous_video_params("Tema Teste", db_path=self.db_path)
        self.assertEqual(params.video_language, "pt-BR")
        self.assertEqual(params.region, "BR")

    def test_03_subtitle_enabled_false_in_ui_overridden_to_true(self):
        """3. subtitle_enabled global/UI = False -> autonomous params retorna True obrigatoriamente."""
        config.ui["subtitle_enabled"] = False

        params = autonomous_production.build_autonomous_video_params("Tema Teste", db_path=self.db_path)
        self.assertTrue(params.subtitle_enabled)

    def test_04_subtitle_text_fore_color_black_overridden_to_white(self):
        """4. text_fore_color = #000000 -> autonomous params retorna #FFFFFF obrigatoriamente."""
        config.ui["text_fore_color"] = "#000000"

        params = autonomous_production.build_autonomous_video_params("Tema Teste", db_path=self.db_path)
        self.assertEqual(params.text_fore_color, "#FFFFFF")

    def test_05_stroke_color_remains_black_and_stroke_width_ge_1_5(self):
        """5. stroke_color permanece preto (#000000) e stroke_width >= 1.5 (default 2.0)."""
        # Teste com valor padrão da UI (espera 2.0)
        params_default = autonomous_production.build_autonomous_video_params("Tema Stroke Default", db_path=self.db_path)
        self.assertEqual(params_default.stroke_color, "#000000")
        self.assertGreaterEqual(params_default.stroke_width, 1.5)
        self.assertEqual(params_default.stroke_width, 2.0)

        # Teste quando UI tenta definir stroke_width muito fino (< 1.5)
        config.ui["stroke_width"] = 0.5
        config.ui["stroke_color"] = "#000000"
        params_clamped = autonomous_production.build_autonomous_video_params("Tema Stroke Clamped", db_path=self.db_path)
        self.assertEqual(params_clamped.stroke_color, "#000000")
        self.assertGreaterEqual(params_clamped.stroke_width, 1.5)

    def test_06_tts_valid_pt_br_voices_pass(self):
        """6. TTS + voice pt-BR válida -> PASS."""
        valid_voices = [
            "pt-BR-AntonioNeural",
            "pt-BR-FranciscaNeural",
            "pt-BR-ThalitaMultilingualNeural",
            "pt-BR-AntonioNeural-Male",
            "pt-BR-FranciscaNeural-Female",
            "pt-br-brenda-neural",
        ]

        for v in valid_voices:
            with self.subTest(voice=v):
                self.assertTrue(
                    autonomous_production.is_valid_pt_br_voice(v),
                    f"is_valid_pt_br_voice deveria retornar True para '{v}'"
                )
                config.ui["voice_name"] = v
                params = autonomous_production.build_autonomous_video_params(f"Tema {v}", db_path=self.db_path)
                self.assertEqual(params.voice_name, v)

                eval_res = autonomous_production.validate_autonomous_brazilian_content_contract(params)
                self.assertTrue(eval_res["valid"])
                self.assertEqual(eval_res["status"], "PASS")
                self.assertEqual(eval_res["reasons"], [])

    def test_07_tts_pt_pt_voices_blocked(self):
        """7. TTS + voice pt-PT -> BLOCK."""
        pt_pt_voices = ["pt-PT-RaquelNeural", "pt-PT-DuarteNeural", "pt-PT-FernandaNeural"]

        for v in pt_pt_voices:
            with self.subTest(voice=v):
                self.assertFalse(autonomous_production.is_valid_pt_br_voice(v))

                eval_res = autonomous_production.validate_autonomous_brazilian_content_contract({
                    "video_language": "pt-BR",
                    "region": "BR",
                    "subtitle_enabled": True,
                    "text_fore_color": "#FFFFFF",
                    "stroke_color": "#000000",
                    "stroke_width": 2.0,
                    "voice_name": v,
                })
                self.assertFalse(eval_res["valid"])
                self.assertEqual(eval_res["status"], "BLOCK")
                self.assertIn("foreign_or_invalid_voice_locale", eval_res["reasons"])

                config.ui["voice_name"] = v
                with self.assertRaises(autonomous_production.AutonomousConfigError):
                    autonomous_production.build_autonomous_video_params(f"Tema {v}", db_path=self.db_path)

    def test_08_tts_en_us_voices_blocked(self):
        """8. TTS + voice en-US -> BLOCK."""
        en_voices = ["en-US-GuyNeural", "en-US-JennyNeural", "en-GB-SoniaNeural"]

        for v in en_voices:
            with self.subTest(voice=v):
                self.assertFalse(autonomous_production.is_valid_pt_br_voice(v))

                eval_res = autonomous_production.validate_autonomous_brazilian_content_contract({
                    "video_language": "pt-BR",
                    "region": "BR",
                    "subtitle_enabled": True,
                    "text_fore_color": "#FFFFFF",
                    "stroke_color": "#000000",
                    "stroke_width": 2.0,
                    "voice_name": v,
                })
                self.assertFalse(eval_res["valid"])
                self.assertEqual(eval_res["status"], "BLOCK")
                self.assertIn("foreign_or_invalid_voice_locale", eval_res["reasons"])

                config.ui["voice_name"] = v
                with self.assertRaises(autonomous_production.AutonomousConfigError):
                    autonomous_production.build_autonomous_video_params(f"Tema {v}", db_path=self.db_path)

    def test_09_tts_af_za_voices_blocked(self):
        """9. TTS + voice af-ZA -> BLOCK."""
        af_voices = ["af-ZA-AdriNeural-Female", "af-ZA-WillemNeural-Male", "af-ZA-AdriNeural"]

        for v in af_voices:
            with self.subTest(voice=v):
                self.assertFalse(autonomous_production.is_valid_pt_br_voice(v))

                eval_res = autonomous_production.validate_autonomous_brazilian_content_contract({
                    "video_language": "pt-BR",
                    "region": "BR",
                    "subtitle_enabled": True,
                    "text_fore_color": "#FFFFFF",
                    "stroke_color": "#000000",
                    "stroke_width": 2.0,
                    "voice_name": v,
                })
                self.assertFalse(eval_res["valid"])
                self.assertEqual(eval_res["status"], "BLOCK")
                self.assertIn("foreign_or_invalid_voice_locale", eval_res["reasons"])

                config.ui["voice_name"] = v
                with self.assertRaises(autonomous_production.AutonomousConfigError):
                    autonomous_production.build_autonomous_video_params(f"Tema {v}", db_path=self.db_path)

    def test_10_profile_default_enforces_pt_br_and_br(self):
        """10. Perfil 'default' -> language final = pt-BR e region final = BR."""
        params = autonomous_production.build_autonomous_video_params(
            "Tema Perfil Default",
            profile_id="default",
            db_path=self.db_path,
        )
        self.assertEqual(params.video_language, "pt-BR")
        self.assertEqual(params.region, "BR")

    def test_11_profile_historias_misterio_enforces_pt_br_and_br(self):
        """11. Perfil 'profile-historias-misterio' -> language final = pt-BR e region final = BR."""
        params = autonomous_production.build_autonomous_video_params(
            "Tema Mistério",
            profile_id="profile-historias-misterio",
            db_path=self.db_path,
        )
        self.assertEqual(params.video_language, "pt-BR")
        self.assertEqual(params.region, "BR")

    def test_12_manual_generation_preserved_and_contract_fail_closed(self):
        """12. Geração manual não é alterada inadvertidamente e contrato autônomo é estrito fail-closed."""
        # Geração manual instancia VideoParams diretamente (sem build_autonomous_video_params)
        # e deve permitir idiomas livres para fluxos manuais sem quebrar
        manual_params = VideoParams(
            video_subject="Manual English Video",
            video_language="en-US",
            voice_name="en-US-JennyNeural",
            subtitle_enabled=False,
            text_fore_color="#000000",
            stroke_color="#FFFFFF",
            stroke_width=1.0,
        )
        self.assertEqual(manual_params.video_language, "en-US")
        self.assertEqual(manual_params.voice_name, "en-US-JennyNeural")
        self.assertFalse(manual_params.subtitle_enabled)

        # O validador autônomo rejeita esses parâmetros manuais fail-closed
        eval_res = autonomous_production.validate_autonomous_brazilian_content_contract(manual_params)
        self.assertFalse(eval_res["valid"])
        self.assertEqual(eval_res["status"], "BLOCK")
        self.assertIn("invalid_video_language", eval_res["reasons"])
        self.assertIn("subtitle_disabled", eval_res["reasons"])
        self.assertIn("invalid_subtitle_color", eval_res["reasons"])
        self.assertIn("foreign_or_invalid_voice_locale", eval_res["reasons"])

        # check_required_providers_preflight também rejeita voz estrangeira
        ok, msg, details = autonomous_production.check_required_providers_preflight(
            video_source="pexels",
            voice_name="en-US-JennyNeural",
            db_path=self.db_path,
        )
        self.assertFalse(ok)
        self.assertEqual(details.get("TTS"), "INVALID_LOCALE")

    def test_13_autonomous_default_match_materials_to_script(self):
        """13. match_materials_to_script default autônomo = True e video_concat_mode = sequential."""
        params = autonomous_production.build_autonomous_video_params(
            "Tema Match Materials",
            db_path=self.db_path,
        )
        self.assertTrue(params.match_materials_to_script)
        self.assertEqual(params.video_concat_mode, VideoConcatMode.sequential)


if __name__ == "__main__":
    unittest.main()
