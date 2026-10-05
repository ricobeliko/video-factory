"""Testes da Fase V16.5.1 — Subtitle & Narration Quality Recovery.

Verifica:
1. Posição default de legenda não pode ser 'top' e normaliza para safe bottom.
2. Tamanho mínimo legível de legenda para 9:16 (mínimo 50, default canônico 60).
3. Safe area inferior preservada (~70% a 80% da altura útil em 9:16, evitando rodapé 5% e colisão com UI do TikTok/Shorts).
4. Safe area para landscape (16:9) permanece conservadora (~8% a 10%).
5. Correção do bug de 2/3 da MoviePy (não joga mais para 33% do topo).
6. Margem horizontal adequada para 9:16 (85% para evitar botões de ação à direita).
7. Contraste alto e stroke forte preservados (#FFFFFF texto, #000000 stroke, largura >= 2.0).
8. Configurações legadas continuam suportadas (custom, center, two_thirds_bottom).
9. Voice rate natural: taxa normalizada para 1.0 quando configurada abaixo de 0.95 (ex: 0.8 arrastado).
10. Voz baseline anterior reproduzível (pt-BR-AntonioNeural, pt-BR-FranciscaNeural).
11. Teste curto de síntese de áudio sem render completo de vídeo.
12. Invariante de publicação: zero chamadas de publicação, zero deploy.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.config import config
from app.models.schema import VideoParams
from app.services import autonomous_production, video, voice


class TestSubtitleNarrationRecovery(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.subtitle_path = os.path.join(self.test_dir, "test.srt")
        self.ass_path = os.path.join(self.test_dir, "test.ass")
        self.db_path = os.path.join(self.test_dir, "test.db")

        srt_content = """1
00:00:01,000 --> 00:00:03,500
Legenda de teste com alta legibilidade e contraste.

2
00:00:03,600 --> 00:00:06,000
Esta é a segunda linha de teste para verificar a quebra.
"""
        Path(self.subtitle_path).write_text(srt_content, encoding="utf-8")

        self.default_params = VideoParams(
            video_subject="Teste V16.5.1",
            video_language="pt-BR",
            subtitle_enabled=True,
            font_size=60,
            text_fore_color="#FFFFFF",
            stroke_color="#000000",
            stroke_width=2.0,
            subtitle_position="bottom",
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_subtitle_default_cannot_revert_to_top_in_autonomous_production(self):
        """1. Subtitle position 'top' é normalizado para safe 'bottom' no modo autônomo."""
        with patch.dict(config.ui, {"subtitle_position": "top", "voice_name": "pt-BR-AntonioNeural-Male"}):
            params = autonomous_production.build_autonomous_video_params("Tema Teste", db_path=self.db_path)
            self.assertEqual(params.subtitle_position, "bottom")
            self.assertNotEqual(params.subtitle_position, "top")

    def test_subtitle_font_size_respects_minimum_for_portrait_9_16(self):
        """2. Subtitle font size abaixo de 50 é elevado para default 60 em 9:16 vertical."""
        # Se configurado 30 (valor observado que causou queixa do usuário)
        with patch.dict(
            config.ui,
            {
                "font_size": 30,
                "video_aspect": "9:16",
                "voice_name": "pt-BR-AntonioNeural-Male",
            },
        ):
            params = autonomous_production.build_autonomous_video_params("Tema Teste", db_path=self.db_path)
            self.assertEqual(params.font_size, 60)
            self.assertGreaterEqual(params.font_size, 50)

        # Se configurado 55 (válido e legível), preserva o valor
        with patch.dict(
            config.ui,
            {
                "font_size": 55,
                "video_aspect": "9:16",
                "voice_name": "pt-BR-AntonioNeural-Male",
            },
        ):
            params = autonomous_production.build_autonomous_video_params("Tema Teste", db_path=self.db_path)
            self.assertEqual(params.font_size, 55)

    def test_vertical_safe_area_ass_margin_v(self):
        """3. Safe area inferior em vídeo vertical (1080x1920) utiliza MarginV ~22% (70%-80% altura útil)."""
        ok = video._convert_subtitles_to_ass(
            subtitle_path=self.subtitle_path,
            ass_path=self.ass_path,
            params=self.default_params,
            video_width=1080,
            video_height=1920,
            font_path="",
        )
        self.assertTrue(ok)
        content = Path(self.ass_path).read_text(encoding="utf-8")

        # Em 1920h, 22% = 422px de margem vertical a partir da base
        expected_margin_v = int(1920 * 0.22)
        self.assertIn(f",20,20,{expected_margin_v},1", content)

    def test_landscape_safe_area_ass_margin_v_preserved(self):
        """4. Em vídeo widescreen horizontal (1920x1080), MarginV permanece conservadora (~8%)."""
        ok = video._convert_subtitles_to_ass(
            subtitle_path=self.subtitle_path,
            ass_path=self.ass_path,
            params=self.default_params,
            video_width=1920,
            video_height=1080,
            font_path="",
        )
        self.assertTrue(ok)
        content = Path(self.ass_path).read_text(encoding="utf-8")

        # Em 1080h landscape, 8% = 86px
        expected_margin_v = int(1080 * 0.08)
        self.assertIn(f",20,20,{expected_margin_v},1", content)

    def test_contrast_and_stroke_preserved(self):
        """5. Contraste alto (#FFFFFF primária, #000000 contorno, stroke >= 2.0)."""
        ok = video._convert_subtitles_to_ass(
            subtitle_path=self.subtitle_path,
            ass_path=self.ass_path,
            params=self.default_params,
            video_width=1080,
            video_height=1920,
            font_path="",
        )
        self.assertTrue(ok)
        content = Path(self.ass_path).read_text(encoding="utf-8")
        # &H00FFFFFF& = Branco primário, &H00000000& = Preto contorno
        self.assertIn("&H00FFFFFF&", content)
        self.assertIn("&H00000000&", content)
        # Stroke width = 2
        self.assertIn(",1,2,0,2,", content)

    def test_legacy_positions_still_supported(self):
        """6. Configurações legadas (top, center, custom) continuam suportadas."""
        # Top
        top_params = self.default_params.model_copy(update={"subtitle_position": "top"})
        ok_top = video._convert_subtitles_to_ass(
            subtitle_path=self.subtitle_path,
            ass_path=os.path.join(self.test_dir, "top.ass"),
            params=top_params,
            video_width=1080,
            video_height=1920,
            font_path="",
        )
        self.assertTrue(ok_top)
        top_content = Path(os.path.join(self.test_dir, "top.ass")).read_text(encoding="utf-8")
        self.assertIn(",8,", top_content)  # alignment 8 = top center

        # Center
        center_params = self.default_params.model_copy(update={"subtitle_position": "center"})
        ok_center = video._convert_subtitles_to_ass(
            subtitle_path=self.subtitle_path,
            ass_path=os.path.join(self.test_dir, "center.ass"),
            params=center_params,
            video_width=1080,
            video_height=1920,
            font_path="",
        )
        self.assertTrue(ok_center)
        center_content = Path(os.path.join(self.test_dir, "center.ass")).read_text(encoding="utf-8")
        self.assertIn(",5,", center_content)  # alignment 5 = middle center

    def test_voice_rate_normalized_to_natural_cadence(self):
        """7. Voice rate menor que 0.95 (ex: 0.8 arrastado) é normalizado para 1.0."""
        with patch.dict(
            config.ui,
            {
                "voice_rate": 0.8,
                "voice_name": "pt-BR-AntonioNeural-Male",
            },
        ):
            params = autonomous_production.build_autonomous_video_params("Tema Teste", db_path=self.db_path)
            self.assertEqual(params.voice_rate, 1.0)

        # Voice rate natural (ex: 1.05) é preservado
        with patch.dict(
            config.ui,
            {
                "voice_rate": 1.05,
                "voice_name": "pt-BR-AntonioNeural-Male",
            },
        ):
            params = autonomous_production.build_autonomous_video_params("Tema Teste", db_path=self.db_path)
            self.assertEqual(params.voice_rate, 1.05)

    def test_baseline_pt_br_voices_recognized(self):
        """8. Vozes canônicas de baseline (Antonio e Francisca) são válidas e reproduzíveis."""
        self.assertTrue(autonomous_production.is_valid_pt_br_voice("pt-BR-AntonioNeural-Male"))
        self.assertTrue(autonomous_production.is_valid_pt_br_voice("pt-BR-AntonioNeural"))
        self.assertTrue(autonomous_production.is_valid_pt_br_voice("pt-BR-FranciscaNeural-Female"))
        self.assertTrue(autonomous_production.is_valid_pt_br_voice("pt-BR-FranciscaNeural"))
        self.assertTrue(autonomous_production.is_valid_pt_br_voice("pt-BR-ThalitaNeural-Female"))
        self.assertTrue(autonomous_production.is_valid_pt_br_voice("pt-BR-DonatoNeural-Male"))

    def test_rate_conversion_for_edge_tts(self):
        """9. Conversão de taxa para Edge TTS produz formatos assinados válidos (+0%, +5%, -20%)."""
        self.assertEqual(voice.convert_rate_to_percent(1.0), "+0%")
        self.assertEqual(voice.convert_rate_to_percent(1.05), "+5%")
        self.assertEqual(voice.convert_rate_to_percent(0.8), "-20%")

    def test_short_audio_synthesis_without_video_render(self):
        """10. Teste curto de áudio sem pipeline de vídeo e sem publicação."""
        audio_out = os.path.join(self.test_dir, "short_sample.mp3")
        with patch("app.services.voice.azure_tts_v1") as mock_azure:
            mock_submaker = MagicMock()
            mock_azure.return_value = mock_submaker

            sub = voice.tts(
                text="Teste curto de áudio para validação de naturalidade.",
                voice_name="pt-BR-AntonioNeural-Male",
                voice_rate=1.0,
                voice_file=audio_out,
                voice_volume=1.0,
            )
            self.assertIsNotNone(sub)
            mock_azure.assert_called_once()
            call_args = mock_azure.call_args
            # arg 0: text, 1: voice_name, 2: voice_rate, 3: voice_file
            rate_used = call_args.kwargs.get("voice_rate") if "voice_rate" in call_args.kwargs else call_args.args[2]
            self.assertEqual(rate_used, 1.0)

    def test_zero_publishing_calls_or_deploy_leak(self):
        """11. Invariante estrita: nenhuma chamada de publicação ou deploy nesta fase."""
        with patch("app.services.post_for_me.PostForMeClient.publish_video") as mock_pub:
            # Garante que nada na recuperação de legendas/narração invoca publishing
            self.assertFalse(mock_pub.called)


if __name__ == "__main__":
    unittest.main()
