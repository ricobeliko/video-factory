import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from time import perf_counter

from app.models.schema import SceneClipInstruction, VideoAspect, VideoParams
from app.services import task as tm
from app.services import video


class TestRenderGapInstrumentationV16_4_1C(unittest.TestCase):
    """Testes direcionados da Fase V16.4.1C — Render Pipeline Gap Instrumentation."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_v16_4_1c_")
        self.video_path = os.path.join(self.test_dir, "combined-1.mp4")
        self.audio_path = os.path.join(self.test_dir, "audio.mp3")
        self.subtitle_path = os.path.join(self.test_dir, "subs.srt")
        self.output_file = os.path.join(self.test_dir, "final-1.mp4")

        Path(self.video_path).write_bytes(b"dummy video data" * 50)
        Path(self.audio_path).write_bytes(b"dummy audio data" * 50)
        Path(self.subtitle_path).write_text(
            "1\n00:00:01,000 --> 00:00:03,000\nTeste de Legenda V16.4.1C\n\n",
            encoding="utf-8",
        )

        self.default_params = VideoParams(
            video_subject="Gap Instrumentation Test",
            video_aspect="9:16",
            subtitle_enabled=True,
            font_name="STHeitiMedium.ttc",
            font_size=60,
            text_fore_color="#FFFFFF",
            stroke_color="#000000",
            stroke_width=2,
            subtitle_position="bottom",
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("app.services.video._validate_final_render_output")
    @patch("app.services.video._render_final_ffmpeg_ass")
    @patch("app.services.video._mix_audio_ffmpeg")
    @patch("app.services.video.probe_media")
    @patch("app.services.video.logger.info")
    def test_final_render_persists_detailed_sub_timings_and_unaccounted_native(
        self, mock_logger, mock_probe, mock_mix, mock_render_ass, mock_validate
    ):
        """Valida se FFmpeg Native persiste todas as novas métricas de gap e calcula residual >= 0."""
        mock_probe.return_value = {"valid": True, "format_duration": "5.0"}
        mock_mix.return_value = True
        mock_render_ass.return_value = True
        mock_validate.return_value = True

        timings = {}
        res = video.generate_video(
            video_path=self.video_path,
            audio_path=self.audio_path,
            subtitle_path=self.subtitle_path,
            output_file=self.output_file,
            params=self.default_params,
            render_timings=timings,
        )

        self.assertTrue(res)
        self.assertEqual(timings.get("FINAL_RENDER_MODE"), "FFMPEG_NATIVE")

        # Métricas canônicas V16.4.1B preservadas
        self.assertIn("FINAL_RENDER_PREP_SECONDS", timings)
        self.assertIn("FINAL_RENDER_AUDIO_SECONDS", timings)
        self.assertIn("FINAL_RENDER_SUBTITLE_SECONDS", timings)
        self.assertIn("FINAL_RENDER_ENCODE_SECONDS", timings)
        self.assertIn("FINAL_RENDER_SECONDS", timings)

        # Novas métricas detalhadas V16.4.1C
        self.assertIn("FINAL_RENDER_MODE_SELECT_SECONDS", timings)
        self.assertIn("FINAL_RENDER_INPUT_PROBE_SECONDS", timings)
        self.assertIn("FINAL_RENDER_AUDIO_PROBE_SECONDS", timings)
        self.assertIn("FINAL_RENDER_AUDIO_MIX_SECONDS", timings)
        self.assertIn("FINAL_RENDER_VALIDATION_SECONDS", timings)
        self.assertIn("FINAL_RENDER_OUTPUT_PROBE_SECONDS", timings)
        self.assertIn("FINAL_RENDER_POST_ENCODE_SECONDS", timings)
        self.assertIn("FINAL_RENDER_UNACCOUNTED_SECONDS", timings)

        # Invariantes de valor
        self.assertGreaterEqual(timings["FINAL_RENDER_MODE_SELECT_SECONDS"], 0.0)
        self.assertGreaterEqual(timings["FINAL_RENDER_INPUT_PROBE_SECONDS"], 0.0)
        self.assertGreaterEqual(timings["FINAL_RENDER_AUDIO_MIX_SECONDS"], 0.0)
        self.assertGreaterEqual(timings["FINAL_RENDER_VALIDATION_SECONDS"], 0.0)
        self.assertGreaterEqual(timings["FINAL_RENDER_POST_ENCODE_SECONDS"], 0.0)
        self.assertGreaterEqual(timings["FINAL_RENDER_UNACCOUNTED_SECONDS"], 0.0)

        # Verificação do invariante de soma
        check = video.verify_render_timing_invariants(timings, tolerance=0.1)
        self.assertTrue(check["valid"], f"Invariants check failed: {check['warnings']}")

    @patch("app.services.video._validate_final_render_output")
    @patch("app.services.video._render_final_stream_copy")
    @patch("app.services.video._mix_audio_ffmpeg")
    @patch("app.services.video.probe_media")
    def test_final_render_persists_detailed_sub_timings_stream_copy(
        self, mock_probe, mock_mix, mock_stream_copy, mock_validate
    ):
        """Valida que FFMPEG_STREAM_COPY (sem legendas) registra métricas detalhadas e residual."""
        mock_probe.return_value = {"valid": True, "format_duration": "5.0"}
        mock_mix.return_value = True
        mock_stream_copy.return_value = True
        mock_validate.return_value = True

        params = self.default_params.model_copy(update={"subtitle_enabled": False})
        timings = {}
        res = video.generate_video(
            video_path=self.video_path,
            audio_path=self.audio_path,
            subtitle_path="",
            output_file=self.output_file,
            params=params,
            render_timings=timings,
        )

        self.assertTrue(res)
        self.assertEqual(timings.get("FINAL_RENDER_MODE"), "FFMPEG_STREAM_COPY")
        self.assertIn("FINAL_RENDER_VALIDATION_SECONDS", timings)
        self.assertIn("FINAL_RENDER_UNACCOUNTED_SECONDS", timings)
        self.assertGreaterEqual(timings["FINAL_RENDER_UNACCOUNTED_SECONDS"], 0.0)

        check = video.verify_render_timing_invariants(timings, tolerance=0.1)
        self.assertTrue(check["valid"], f"Invariants check failed: {check['warnings']}")

    @patch("app.services.video._write_videofile_with_codec_fallback")
    @patch("app.services.video.logger.info")
    def test_final_render_moviepy_fallback_persists_timing_and_residual(
        self, mock_logger, mock_write_videofile
    ):
        """Valida que o fallback MoviePy registra métricas de timing e calcula residual sem crash."""
        class _FakeClip:
            def __init__(self, duration=5.0):
                self.duration = duration
                self.fps = 44100
                self.size = (1080, 1920)
                self.w = 1080
                self.h = 1920
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def close(self):
                pass
            def with_effects(self, *args):
                return self
            def with_audio(self, *args):
                return self

        params = self.default_params.model_copy(
            update={"subtitle_position": "custom", "custom_position": 70, "bgm_volume": 0.0}
        )
        timings = {}

        source_video = _FakeClip()
        voice_source = _FakeClip()

        with patch("app.services.video._open_video_clip_quietly", return_value=source_video), \
             patch("app.services.video.AudioFileClip", return_value=voice_source), \
             patch("app.services.video.SubtitlesClip") as mock_sub:
            mock_sub_inst = MagicMock()
            mock_sub_inst.subtitles = []
            mock_sub.return_value.__enter__.return_value = mock_sub_inst

            res = video.generate_video(
                video_path=self.video_path,
                audio_path=self.audio_path,
                subtitle_path=self.subtitle_path,
                output_file=self.output_file,
                params=params,
                render_timings=timings,
            )

        self.assertTrue(res)
        self.assertEqual(timings.get("FINAL_RENDER_MODE"), "MOVIEPY_FALLBACK")
        self.assertIn("FINAL_RENDER_UNACCOUNTED_SECONDS", timings)
        self.assertGreaterEqual(timings["FINAL_RENDER_UNACCOUNTED_SECONDS"], 0.0)

    @patch("app.services.video.AudioFileClip")
    @patch("app.services.video._open_video_clip_quietly")
    @patch("app.services.video._write_videofile_with_codec_fallback")
    @patch("app.services.video.concat_video_clips_with_ffmpeg")
    @patch("app.services.video.delete_files")
    def test_combine_videos_persists_pre_post_concat_and_combine_total(
        self, mock_del, mock_concat, mock_write, mock_open, mock_audio
    ):
        """Valida que combine_videos registra SCENE_RENDER_PRE_CONCAT, POST_CONCAT e COMBINE_VIDEOS_SECONDS."""
        mock_audio_inst = MagicMock()
        mock_audio_inst.duration = 4.0
        mock_audio.return_value = mock_audio_inst

        mock_raw = MagicMock()
        mock_raw.duration = 10.0
        mock_raw.size = (1080, 1920)
        mock_raw.subclipped.return_value = mock_raw
        mock_open.return_value = mock_raw

        instructions = [
            SceneClipInstruction(
                scene_index=1,
                material_path=self.video_path,
                duration_seconds=4.0,
            )
        ]

        render_timings = {}
        combined_path = os.path.join(self.test_dir, "combined.mp4")
        video.combine_videos(
            combined_video_path=combined_path,
            video_paths=[],
            audio_file="dummy.mp3",
            video_aspect=VideoAspect.portrait,
            max_clip_duration=5,
            threads=2,
            scene_clip_instructions=instructions,
            render_timings=render_timings,
        )

        self.assertIn("SCENE_RENDER_PREP_SECONDS", render_timings)
        self.assertIn("SCENE_RENDER_CLIPS_SECONDS", render_timings)
        self.assertIn("SCENE_RENDER_PRE_CONCAT_SECONDS", render_timings)
        self.assertIn("CONCAT_SECONDS", render_timings)
        self.assertIn("SCENE_RENDER_POST_CONCAT_SECONDS", render_timings)
        self.assertIn("COMBINE_VIDEOS_SECONDS", render_timings)
        self.assertIn("COMBINE_VIDEOS_UNACCOUNTED_SECONDS", render_timings)

        self.assertGreaterEqual(render_timings["SCENE_RENDER_PRE_CONCAT_SECONDS"], 0.0)
        self.assertGreaterEqual(render_timings["SCENE_RENDER_POST_CONCAT_SECONDS"], 0.0)
        self.assertGreaterEqual(render_timings["COMBINE_VIDEOS_SECONDS"], 0.0)
        self.assertGreaterEqual(render_timings["COMBINE_VIDEOS_UNACCOUNTED_SECONDS"], 0.0)

    @patch("app.services.task.logger.info")
    @patch("app.services.task.logger.warning")
    @patch("app.services.task.video.combine_videos")
    @patch("app.services.task.video.generate_video")
    @patch("app.services.task.task_artifacts.patch_script_data")
    @patch("app.services.task.sm.state.update_task")
    def test_task_generate_final_videos_captures_pre_final_and_total_unaccounted(
        self, mock_update, mock_patch, mock_gen_video, mock_combine, mock_logger_warn, mock_logger_info
    ):
        """Valida que task.generate_final_videos calcula PRE_FINAL_RENDER e TOTAL_RENDER_UNACCOUNTED_SECONDS."""
        def fake_combine(**kwargs):
            timings = kwargs.get("render_timings")
            if timings is not None:
                timings["COMBINE_VIDEOS_SECONDS"] = 0.500
                timings["SCENE_RENDER_PREP_SECONDS"] = 0.050
                timings["SCENE_RENDER_CLIPS_SECONDS"] = 0.350
                timings["SCENE_RENDER_PRE_CONCAT_SECONDS"] = 0.010
                timings["CONCAT_SECONDS"] = 0.080
                timings["SCENE_RENDER_POST_CONCAT_SECONDS"] = 0.010
                timings["COMBINE_VIDEOS_UNACCOUNTED_SECONDS"] = 0.0
            return "/path/to/combined.mp4"

        def fake_generate(**kwargs):
            timings = kwargs.get("render_timings")
            if timings is not None:
                timings["FINAL_RENDER_MODE"] = "FFMPEG_NATIVE"
                timings["FINAL_RENDER_PREP_SECONDS"] = 0.010
                timings["FINAL_RENDER_MODE_SELECT_SECONDS"] = 0.005
                timings["FINAL_RENDER_INPUT_PROBE_SECONDS"] = 0.010
                timings["FINAL_RENDER_AUDIO_PROBE_SECONDS"] = 0.010
                timings["FINAL_RENDER_AUDIO_MIX_SECONDS"] = 0.020
                timings["FINAL_RENDER_AUDIO_SECONDS"] = 0.030
                timings["FINAL_RENDER_SUBTITLE_SECONDS"] = 0.010
                timings["FINAL_RENDER_ENCODE_SECONDS"] = 0.400
                timings["FINAL_RENDER_VALIDATION_SECONDS"] = 0.010
                timings["FINAL_RENDER_OUTPUT_PROBE_SECONDS"] = 0.010
                timings["FINAL_RENDER_POST_ENCODE_SECONDS"] = 0.005
                timings["FINAL_RENDER_SECONDS"] = 0.470
                timings["FINAL_RENDER_UNACCOUNTED_SECONDS"] = 0.0
                timings["POST_RENDER_TIMING_STORE_SECONDS"] = 0.0001
                timings["POST_RENDER_CLEANUP_SECONDS"] = 0.0002
                timings["_VIDEO_GENERATE_EXIT_TIMESTAMP"] = perf_counter()
            return True

        mock_combine.side_effect = fake_combine
        mock_gen_video.side_effect = fake_generate

        params = VideoParams(
            video_subject="TestV16_4_1C_Task",
            scene_based_generation_enabled=True,
            subtitle_required=False,
            final_media_quality_required=False,
            video_count=1,
            n_threads=2,
        )

        tm.generate_final_videos(
            task_id="task_gap_instrumentation_test",
            params=params,
            downloaded_videos=[self.video_path],
            audio_file=self.audio_path,
            subtitle_path=self.subtitle_path,
            audio_duration=5.0,
            scene_clip_instructions=[MagicMock()],
        )

        mock_patch.assert_called()
        patch_kwargs = mock_patch.call_args[1]
        timings = patch_kwargs["scene_render_timings"]

        # Verificação das métricas do macro pipeline
        self.assertIn("COMBINE_VIDEOS_CALL_SECONDS", timings)
        self.assertIn("COMBINE_VIDEOS_SECONDS", timings)
        self.assertIn("PRE_FINAL_RENDER_SECONDS", timings)
        self.assertIn("PRE_FINAL_RENDER_BATCH_ALLOCATION_SECONDS", timings)
        self.assertIn("PRE_FINAL_RENDER_BGM_GEN_SECONDS", timings)
        self.assertIn("PRE_FINAL_RENDER_SUBTITLE_VAL_SECONDS", timings)
        self.assertIn("FINAL_RENDER_CALL_SECONDS", timings)
        self.assertIn("FINAL_RENDER_SECONDS", timings)
        self.assertIn("TOTAL_RENDER_SECONDS", timings)
        self.assertIn("TOTAL_RENDER_UNACCOUNTED_SECONDS", timings)

        # Invariantes numéricos
        self.assertGreaterEqual(timings["TOTAL_RENDER_UNACCOUNTED_SECONDS"], 0.0)
        self.assertGreaterEqual(timings["PRE_FINAL_RENDER_SECONDS"], 0.0)

        # Verificador de invariantes
        check = video.verify_render_timing_invariants(timings, tolerance=0.1)
        self.assertTrue(check["valid"], f"Timing invariants violated: {check['warnings']}")

        # Summary log expandido
        info_logs = [call.args[0] for call in mock_logger_info.call_args_list if call.args]
        self.assertTrue(any("COMBINE_VIDEOS_SECONDS=" in str(log_msg) for log_msg in info_logs))
        self.assertTrue(any("PRE_FINAL_RENDER_SECONDS=" in str(log_msg) for log_msg in info_logs))
        self.assertTrue(any("TOTAL_RENDER_UNACCOUNTED_SECONDS=" in str(log_msg) for log_msg in info_logs))
        self.assertTrue(any("FINAL_RENDER_UNACCOUNTED_SECONDS=" in str(log_msg) for log_msg in info_logs))

    def test_verify_render_timing_invariants_flags_unaccounted_gap(self):
        """Valida que o helper detecta desvios significativos entre soma e tempo total."""
        anomalous_timings = {
            "FINAL_RENDER_MODE": "FFMPEG_NATIVE",
            "FINAL_RENDER_PREP_SECONDS": 0.01,
            "FINAL_RENDER_MODE_SELECT_SECONDS": 0.01,
            "FINAL_RENDER_AUDIO_SECONDS": 4.0,
            "FINAL_RENDER_AUDIO_PROBE_SECONDS": 0.5,
            "FINAL_RENDER_AUDIO_MIX_SECONDS": 3.5,
            "FINAL_RENDER_SUBTITLE_SECONDS": 0.5,
            "FINAL_RENDER_ENCODE_SECONDS": 380.0,
            "FINAL_RENDER_VALIDATION_SECONDS": 1.0,
            "FINAL_RENDER_POST_ENCODE_SECONDS": 0.01,
            "FINAL_RENDER_SECONDS": 1488.0,  # Gap intencional de ~1100s
            "FINAL_RENDER_UNACCOUNTED_SECONDS": 1102.47,
        }

        check = video.verify_render_timing_invariants(anomalous_timings, tolerance=1.0)
        self.assertFalse(check["valid"])
        self.assertGreater(check["final_render_delta"], 1000.0)
        self.assertTrue(any("FINAL_RENDER delta" in w for w in check["warnings"]))


if __name__ == "__main__":
    unittest.main()
