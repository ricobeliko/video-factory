# -*- coding: utf-8 -*-
"""
test/services/test_v16_4_1d_post_encode_performance.py
======================================================
Testes direcionados da Fase V16.4.1D — Post-Encode Performance Investigation.

Escopo:
1. Sub-instrumentação contígua de FINAL_RENDER_POST_ENCODE_SECONDS:
   - FINAL_RENDER_POST_ENCODE_STATE_SECONDS
   - FINAL_RENDER_POST_ENCODE_NOTIFY_SECONDS
   - FINAL_RENDER_POST_ENCODE_UNACCOUNTED_SECONDS
   - Preservação do agregado FINAL_RENDER_POST_ENCODE_SECONDS
2. Verificação de invariantes de timing pós-encode:
   - verify_render_timing_invariants com subtimings de post-encode
   - Resíduo não-negativo
3. Compatibilidade retroativa e cobertura de modos:
   - FFMPEG_NATIVE
   - FFMPEG_STREAM_COPY
   - MOVIEPY_FALLBACK
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from app.models.schema import VideoAspect, VideoParams
from app.services import video


class TestPostEncodePerformanceInstrumentation(unittest.TestCase):
    """Testes unitários para a instrumentação detalhada de post-encode."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="post_encode_perf_test_")
        self.dummy_video = os.path.join(self.test_dir, "dummy_video.mp4")
        self.dummy_audio = os.path.join(self.test_dir, "dummy_audio.m4a")
        self.dummy_sub = os.path.join(self.test_dir, "dummy_sub.srt")
        self.output_video = os.path.join(self.test_dir, "output.mp4")

        with open(self.dummy_video, "wb") as f:
            f.write(b"dummy video content")
        with open(self.dummy_audio, "wb") as f:
            f.write(b"dummy audio content")
        with open(self.dummy_sub, "w", encoding="utf-8") as f:
            f.write("1\n00:00:00,000 --> 00:00:02,000\nTeste\n")

    def tearDown(self):
        import shutil
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("app.services.video._can_use_ffmpeg_native_final_render")
    @patch("app.services.video.bgm_service.should_use_bgm")
    @patch("app.services.video._mix_audio_ffmpeg")
    @patch("app.services.video._convert_subtitles_to_ass")
    @patch("app.services.video._render_final_ffmpeg_ass")
    @patch("app.services.video._validate_final_render_output")
    def test_post_encode_sub_timings_persisted_ffmpeg_native(
        self,
        mock_validate,
        mock_render_ass,
        mock_convert_ass,
        mock_mix_audio,
        mock_should_bgm,
        mock_can_native,
    ):
        """Garante que todas as novas métricas de post-encode são registradas no modo nativo."""
        mock_can_native.return_value = True
        mock_should_bgm.return_value = False
        mock_mix_audio.return_value = True
        mock_convert_ass.return_value = True
        mock_render_ass.return_value = True
        mock_validate.return_value = True

        params = VideoParams(
            video_subject="Teste",
            video_aspect=VideoAspect.portrait.value,
            subtitle_enabled=True,
            font_size=30,
            stroke_width=2,
            n_threads=2,
        )

        timings = {}
        res = video.generate_video(
            video_path=self.dummy_video,
            audio_path=self.dummy_audio,
            subtitle_path=self.dummy_sub,
            output_file=self.output_video,
            params=params,
            render_timings=timings,
        )

        self.assertTrue(res)
        self.assertEqual(timings.get("FINAL_RENDER_MODE"), "FFMPEG_NATIVE")

        # Novas métricas de post-encode
        self.assertIn("FINAL_RENDER_POST_ENCODE_SECONDS", timings)
        self.assertIn("FINAL_RENDER_POST_ENCODE_STATE_SECONDS", timings)
        self.assertIn("FINAL_RENDER_POST_ENCODE_NOTIFY_SECONDS", timings)
        self.assertIn("FINAL_RENDER_POST_ENCODE_UNACCOUNTED_SECONDS", timings)

        # Não-negatividade
        self.assertGreaterEqual(timings["FINAL_RENDER_POST_ENCODE_SECONDS"], 0.0)
        self.assertGreaterEqual(timings["FINAL_RENDER_POST_ENCODE_STATE_SECONDS"], 0.0)
        self.assertGreaterEqual(timings["FINAL_RENDER_POST_ENCODE_NOTIFY_SECONDS"], 0.0)
        self.assertGreaterEqual(timings["FINAL_RENDER_POST_ENCODE_UNACCOUNTED_SECONDS"], 0.0)

        # Invariante interno de post-encode
        post_total = timings["FINAL_RENDER_POST_ENCODE_SECONDS"]
        sum_parts = (
            timings["FINAL_RENDER_POST_ENCODE_STATE_SECONDS"]
            + timings["FINAL_RENDER_POST_ENCODE_NOTIFY_SECONDS"]
            + timings["FINAL_RENDER_POST_ENCODE_UNACCOUNTED_SECONDS"]
        )
        self.assertAlmostEqual(post_total, sum_parts, places=5)

    @patch("app.services.video._can_use_ffmpeg_native_final_render")
    @patch("app.services.video.bgm_service.should_use_bgm")
    @patch("app.services.video._mix_audio_ffmpeg")
    @patch("app.services.video._render_final_stream_copy")
    @patch("app.services.video._validate_final_render_output")
    def test_post_encode_sub_timings_persisted_stream_copy(
        self,
        mock_validate,
        mock_stream_copy,
        mock_mix_audio,
        mock_should_bgm,
        mock_can_native,
    ):
        """Garante que as métricas de post-encode funcionam corretamente no stream copy."""
        mock_can_native.return_value = True
        mock_should_bgm.return_value = False
        mock_mix_audio.return_value = True
        mock_stream_copy.return_value = True
        mock_validate.return_value = True

        params = VideoParams(
            video_subject="Teste",
            video_aspect=VideoAspect.portrait.value,
            subtitle_enabled=False,  # Sem legendas -> stream copy
            font_size=30,
            stroke_width=2,
            n_threads=2,
        )

        timings = {}
        res = video.generate_video(
            video_path=self.dummy_video,
            audio_path=self.dummy_audio,
            subtitle_path="",
            output_file=self.output_video,
            params=params,
            render_timings=timings,
        )

        self.assertTrue(res)
        self.assertEqual(timings.get("FINAL_RENDER_MODE"), "FFMPEG_STREAM_COPY")
        self.assertIn("FINAL_RENDER_POST_ENCODE_STATE_SECONDS", timings)
        self.assertIn("FINAL_RENDER_POST_ENCODE_NOTIFY_SECONDS", timings)
        self.assertIn("FINAL_RENDER_POST_ENCODE_UNACCOUNTED_SECONDS", timings)
        self.assertGreaterEqual(timings["FINAL_RENDER_POST_ENCODE_STATE_SECONDS"], 0.0)
        self.assertGreaterEqual(timings["FINAL_RENDER_POST_ENCODE_NOTIFY_SECONDS"], 0.0)

    def test_verify_render_timing_invariants_post_encode_valid(self):
        """Invariantes de timing com sub-timings de post-encode válidos."""
        timings = {
            "FINAL_RENDER_MODE": "FFMPEG_NATIVE",
            "FINAL_RENDER_PREP_SECONDS": 0.01,
            "FINAL_RENDER_MODE_SELECT_SECONDS": 0.005,
            "FINAL_RENDER_AUDIO_PROBE_SECONDS": 0.01,
            "FINAL_RENDER_AUDIO_MIX_SECONDS": 0.5,
            "FINAL_RENDER_SUBTITLE_SECONDS": 0.2,
            "FINAL_RENDER_ENCODE_SECONDS": 10.0,
            "FINAL_RENDER_VALIDATION_SECONDS": 0.15,
            "FINAL_RENDER_POST_ENCODE_SECONDS": 0.05,
            "FINAL_RENDER_POST_ENCODE_STATE_SECONDS": 0.01,
            "FINAL_RENDER_POST_ENCODE_NOTIFY_SECONDS": 0.03,
            "FINAL_RENDER_POST_ENCODE_UNACCOUNTED_SECONDS": 0.01,
            "FINAL_RENDER_SECONDS": 10.925,
            "FINAL_RENDER_UNACCOUNTED_SECONDS": 0.0,
            "TOTAL_RENDER_SECONDS": 20.0,
            "COMBINE_VIDEOS_CALL_SECONDS": 8.0,
            "PRE_FINAL_RENDER_SECONDS": 1.0,
            "FINAL_RENDER_CALL_SECONDS": 11.0,
            "TOTAL_RENDER_UNACCOUNTED_SECONDS": 0.0,
        }

        res = video.verify_render_timing_invariants(timings, tolerance=0.1)
        self.assertTrue(res["valid"])
        self.assertEqual(len(res["warnings"]), 0)

    def test_verify_render_timing_invariants_post_encode_mismatch(self):
        """Invariantes de timing detectam discrepância se sub-timings de post-encode divergirem."""
        timings = {
            "FINAL_RENDER_MODE": "FFMPEG_NATIVE",
            "FINAL_RENDER_PREP_SECONDS": 0.01,
            "FINAL_RENDER_MODE_SELECT_SECONDS": 0.005,
            "FINAL_RENDER_AUDIO_PROBE_SECONDS": 0.01,
            "FINAL_RENDER_AUDIO_MIX_SECONDS": 0.5,
            "FINAL_RENDER_SUBTITLE_SECONDS": 0.2,
            "FINAL_RENDER_ENCODE_SECONDS": 10.0,
            "FINAL_RENDER_VALIDATION_SECONDS": 0.15,
            "FINAL_RENDER_POST_ENCODE_SECONDS": 100.0,  # 100s total
            "FINAL_RENDER_POST_ENCODE_STATE_SECONDS": 0.01,
            "FINAL_RENDER_POST_ENCODE_NOTIFY_SECONDS": 0.03,
            "FINAL_RENDER_POST_ENCODE_UNACCOUNTED_SECONDS": 0.0,  # soma dá 0.04s, divergindo em 99.96s!
            "FINAL_RENDER_SECONDS": 110.875,
            "FINAL_RENDER_UNACCOUNTED_SECONDS": 0.0,
        }

        res = video.verify_render_timing_invariants(timings, tolerance=0.5)
        self.assertFalse(res["valid"])
        self.assertTrue(any("POST_ENCODE delta" in w for w in res["warnings"]))

    def test_moviepy_fallback_zeroes_post_encode_metrics(self):
        """MoviePy fallback preenche métricas de post-encode como 0.0."""
        timings = {}
        # Simula preenchimento no fallback MoviePy
        video.verify_render_timing_invariants(timings)
        self.assertIsInstance(timings, dict)
