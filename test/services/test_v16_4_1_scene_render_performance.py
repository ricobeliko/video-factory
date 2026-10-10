# -*- coding: utf-8 -*-
"""
test/services/test_v16_4_1_scene_render_performance.py
======================================================
Testes unit?rios e direcionados da Fase V16.4.1 ? Scene Render Performance Hardening.

Escopo:
1. Instrumenta??o de timings com perf_counter:
   - SCENE_RENDER_PREP_SECONDS
   - SCENE_RENDER_CLIPS_SECONDS
   - CONCAT_SECONDS
   - FINAL_RENDER_SECONDS
   - TOTAL_RENDER_SECONDS
2. Stream-Copy Concat no caminho scene-based:
   - Tentativa de -c copy quando allow_stream_copy=True
   - Valida??o de sa?da (returncode == 0 e tamanho > 0)
   - Log de CONCAT_MODE=STREAM_COPY em caso de sucesso
   - Fallback para transcode (-c:v libx264) e log de CONCAT_MODE=TRANSCODE_FALLBACK em caso de falha
3. Propaga??o de threads nas escritas scene-based:
   - Propaga??o correta de threads para _write_videofile_with_codec_fallback
"""

import os
import shutil
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.models.schema import (
    SceneClipInstruction,
    VideoAspect,
    VideoParams,
)
from app.services import task as tm, video


class TestSceneRenderPerformanceTiming(unittest.TestCase):
    """Testes de instrumenta??o de timing com perf_counter."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="scene_perf_test_")
        self.dummy_video_path = os.path.join(self.test_dir, "clip.mp4")
        with open(self.dummy_video_path, "wb") as f:
            f.write(b"dummy clip data" * 100)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("app.services.video.logger.info")
    @patch("app.services.video.AudioFileClip")
    @patch("app.services.video._open_video_clip_quietly")
    @patch("app.services.video._write_videofile_with_codec_fallback")
    @patch("app.services.video.concat_video_clips_with_ffmpeg")
    def test_combine_videos_measures_and_logs_scene_timings(
        self, mock_concat, mock_write, mock_open, mock_audio, mock_logger_info
    ):
        mock_audio_instance = MagicMock()
        mock_audio_instance.duration = 4.0
        mock_audio.return_value = mock_audio_instance

        mock_raw_clip = MagicMock()
        mock_raw_clip.duration = 10.0
        mock_raw_clip.size = (1080, 1920)
        mock_raw_clip.subclipped.return_value = mock_raw_clip
        mock_open.return_value = mock_raw_clip

        instructions = [
            SceneClipInstruction(
                scene_index=1,
                material_path=self.dummy_video_path,
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
            threads=3,
            scene_clip_instructions=instructions,
            render_timings=render_timings,
        )

        self.assertIn("SCENE_RENDER_PREP_SECONDS", render_timings)
        self.assertIn("SCENE_RENDER_CLIPS_SECONDS", render_timings)
        self.assertIn("CONCAT_SECONDS", render_timings)
        self.assertGreaterEqual(render_timings["SCENE_RENDER_PREP_SECONDS"], 0.0)
        self.assertGreaterEqual(render_timings["SCENE_RENDER_CLIPS_SECONDS"], 0.0)
        self.assertGreaterEqual(render_timings["CONCAT_SECONDS"], 0.0)

        info_logs = [call.args[0] for call in mock_logger_info.call_args_list if call.args]
        self.assertTrue(any("SCENE_RENDER_PREP_SECONDS=" in str(log) for log in info_logs))
        self.assertTrue(any("SCENE_RENDER_CLIPS_SECONDS=" in str(log) for log in info_logs))
        self.assertTrue(any("CONCAT_SECONDS=" in str(log) for log in info_logs))

    @patch("app.services.task.logger.info")
    @patch("app.services.task.video.combine_videos")
    @patch("app.services.task.video.generate_video")
    @patch("app.services.task.task_artifacts.patch_script_data")
    @patch("app.services.task.sm.state.update_task")
    def test_generate_final_videos_measures_final_and_total_timings(
        self, mock_update, mock_patch, mock_gen_video, mock_combine, mock_logger
    ):
        mock_combine.return_value = "/path/to/combined.mp4"
        mock_gen_video.return_value = True

        params = VideoParams(
            video_subject="TestPerf",
            scene_based_generation_enabled=True,
            subtitle_required=False,
            final_media_quality_required=False,
            video_count=1,
            n_threads=4,
        )

        instructions = [
            SceneClipInstruction(
                scene_index=1,
                material_path=self.dummy_video_path,
                duration_seconds=5.0,
            )
        ]

        def fake_combine(**kwargs):
            timings = kwargs.get("render_timings")
            if timings is not None:
                timings["SCENE_RENDER_PREP_SECONDS"] = 0.05
                timings["SCENE_RENDER_CLIPS_SECONDS"] = 1.20
                timings["CONCAT_SECONDS"] = 0.10
            return kwargs.get("combined_video_path")

        mock_combine.side_effect = fake_combine

        tm.generate_final_videos(
            task_id="task_perf_timing_test",
            params=params,
            downloaded_videos=[self.dummy_video_path],
            audio_file="dummy.mp3",
            subtitle_path="dummy.srt",
            audio_duration=5.0,
            scene_clip_instructions=instructions,
        )

        mock_patch.assert_called()
        patch_kwargs = mock_patch.call_args[1]
        self.assertIn("scene_render_timings", patch_kwargs)
        timings = patch_kwargs["scene_render_timings"]
        self.assertIn("SCENE_RENDER_PREP_SECONDS", timings)
        self.assertIn("SCENE_RENDER_CLIPS_SECONDS", timings)
        self.assertIn("CONCAT_SECONDS", timings)
        self.assertIn("FINAL_RENDER_SECONDS", timings)
        self.assertIn("TOTAL_RENDER_SECONDS", timings)
        self.assertGreaterEqual(timings["FINAL_RENDER_SECONDS"], 0.0)
        self.assertGreaterEqual(timings["TOTAL_RENDER_SECONDS"], 0.0)

        logged = [call.args[0] for call in mock_logger.call_args_list if call.args]
        self.assertTrue(any("FINAL_RENDER_SECONDS=" in str(log) for log in logged))
        self.assertTrue(any("TOTAL_RENDER_SECONDS=" in str(log) for log in logged))
    @patch("app.services.video.logger.info")
    @patch("app.services.video._write_videofile_with_codec_fallback")
    @patch("app.services.video.VideoFileClip")
    @patch("app.services.video.AudioFileClip")
    def test_generate_video_measures_and_logs_final_render_timing(
        self, mock_audio, mock_video, mock_write, mock_logger
    ):
        mock_audio_clip = MagicMock()
        mock_audio_clip.duration = 5.0
        mock_audio.return_value = mock_audio_clip

        mock_video_clip = MagicMock()
        mock_video_clip.duration = 5.0
        mock_video_clip.with_audio.return_value = mock_video_clip
        mock_video.return_value = mock_video_clip

        params = VideoParams(
            video_subject="DirectGenTest",
            scene_based_generation_enabled=True,
            subtitle_enabled=False,
            bgm_type="",
        )

        timings = {}
        res = video.generate_video(
            video_path=self.dummy_video_path,
            audio_path="dummy.mp3",
            subtitle_path="",
            output_file=os.path.join(self.test_dir, "final.mp4"),
            params=params,
            render_timings=timings,
        )

        self.assertTrue(res)
        self.assertIn("FINAL_RENDER_SECONDS", timings)
        self.assertGreaterEqual(timings["FINAL_RENDER_SECONDS"], 0.0)

        logs = [call.args[0] for call in mock_logger.call_args_list if call.args]
        self.assertTrue(any("FINAL_RENDER_SECONDS=" in str(log_item) for log_item in logs))



class TestStreamCopyConcat(unittest.TestCase):
    """Testes para concat stream-copy, validação de mídia via probe e fallback para transcode."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="stream_copy_test_")
        self.clip1 = os.path.join(self.test_dir, "clip1.mp4")
        self.clip2 = os.path.join(self.test_dir, "clip2.mp4")
        self.output_file = os.path.join(self.test_dir, "combined.mp4")
        Path(self.clip1).write_bytes(b"clip1 data")
        Path(self.clip2).write_bytes(b"clip2 data")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("app.services.video.probe_media")
    @patch("app.services.video.logger.info")
    @patch("app.services.video.subprocess.run")
    def test_stream_copy_rc0_valid_probe_succeeds_as_stream_copy(
        self, mock_run, mock_logger_info, mock_probe
    ):
        """Cenário 1: rc=0 + arquivo não vazio + probe válido com video stream -> STREAM_COPY."""
        mock_probe.return_value = {
            "valid": True,
            "video_streams": [{"codec_type": "video", "width": 1080, "height": 1920}],
            "audio_streams": [],
        }

        def fake_run(command, capture_output, text, check):
            if "-c" in command and command[command.index("-c") + 1] == "copy":
                Path(self.output_file).write_bytes(b"concatenated stream copy data")
                return types.SimpleNamespace(returncode=0, stdout="", stderr="")
            return types.SimpleNamespace(returncode=1, stdout="", stderr="unexpected transcode")

        mock_run.side_effect = fake_run

        codec_result = video.concat_video_clips_with_ffmpeg(
            clip_files=[self.clip1, self.clip2],
            output_file=self.output_file,
            threads=2,
            output_dir=self.test_dir,
            max_duration=10.0,
            allow_stream_copy=True,
        )

        self.assertEqual(codec_result, "copy")
        mock_probe.assert_called_once_with(self.output_file)
        first_call_cmd = mock_run.call_args_list[0].args[0]
        self.assertIn("-c", first_call_cmd)
        self.assertEqual(first_call_cmd[first_call_cmd.index("-c") + 1], "copy")

        info_logs = [call.args[0] for call in mock_logger_info.call_args_list if call.args]
        self.assertTrue(any("CONCAT_MODE=STREAM_COPY" in str(log) for log in info_logs))

    @patch("app.services.video.probe_media")
    @patch("app.services.video.logger.warning")
    @patch("app.services.video.subprocess.run")
    def test_stream_copy_rc0_invalid_probe_triggers_transcode_fallback(
        self, mock_run, mock_logger_warn, mock_probe
    ):
        """Cenário 2: rc=0 + arquivo não vazio + probe inválido -> TRANSCODE_FALLBACK."""
        # Probe indica mídia inválida ou corrompida
        mock_probe.return_value = {
            "valid": False,
            "error_code": "FFPROBE_PARSE_ERROR",
            "error_message": "corrupted stream headers",
            "video_streams": [],
        }

        def fake_run(command, capture_output, text, check):
            if "-c" in command and command[command.index("-c") + 1] == "copy":
                Path(self.output_file).write_bytes(b"corrupted copy data")
                return types.SimpleNamespace(returncode=0, stdout="", stderr="")
            # Fallback de transcode escreve arquivo final válido
            Path(self.output_file).write_bytes(b"transcoded video")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        mock_run.side_effect = fake_run

        codec_result = video.concat_video_clips_with_ffmpeg(
            clip_files=[self.clip1, self.clip2],
            output_file=self.output_file,
            threads=2,
            output_dir=self.test_dir,
            max_duration=10.0,
            allow_stream_copy=True,
        )

        self.assertIn(codec_result, ["libx264", video._DEFAULT_VIDEO_CODEC])
        # Primeiro comando foi stream-copy, segundo comando foi transcode fallback
        self.assertEqual(len(mock_run.call_args_list), 2)
        first_cmd = mock_run.call_args_list[0].args[0]
        self.assertEqual(first_cmd[first_cmd.index("-c") + 1], "copy")
        second_cmd = mock_run.call_args_list[1].args[0]
        self.assertIn("-c:v", second_cmd)

        # Log emitido deve ser TRANSCODE_FALLBACK
        warn_logs = [call.args[0] for call in mock_logger_warn.call_args_list if call.args]
        self.assertTrue(any("CONCAT_MODE=TRANSCODE_FALLBACK" in str(log) for log in warn_logs))

    @patch("app.services.video.probe_media")
    @patch("app.services.video.logger.warning")
    @patch("app.services.video.subprocess.run")
    def test_stream_copy_rc0_no_video_stream_triggers_transcode_fallback(
        self, mock_run, mock_logger_warn, mock_probe
    ):
        """Cenário 3: rc=0 + arquivo não vazio + probe válido mas sem video streams -> TRANSCODE_FALLBACK."""
        mock_probe.return_value = {
            "valid": True,
            "video_streams": [],
            "audio_streams": [{"codec_type": "audio"}],
        }

        def fake_run(command, capture_output, text, check):
            if "-c" in command and command[command.index("-c") + 1] == "copy":
                Path(self.output_file).write_bytes(b"audio only data")
                return types.SimpleNamespace(returncode=0, stdout="", stderr="")
            Path(self.output_file).write_bytes(b"transcoded video")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        mock_run.side_effect = fake_run

        codec_result = video.concat_video_clips_with_ffmpeg(
            clip_files=[self.clip1, self.clip2],
            output_file=self.output_file,
            threads=2,
            output_dir=self.test_dir,
            max_duration=10.0,
            allow_stream_copy=True,
        )

        self.assertIn(codec_result, ["libx264", video._DEFAULT_VIDEO_CODEC])
        warn_logs = [call.args[0] for call in mock_logger_warn.call_args_list if call.args]
        self.assertTrue(any("CONCAT_MODE=TRANSCODE_FALLBACK" in str(log) for log in warn_logs))

    @patch("app.services.video.logger.warning")
    @patch("app.services.video.subprocess.run")
    def test_stream_copy_fails_and_falls_back_to_transcode(self, mock_run, mock_logger_warn):
        """Cenário 4: rc!=0 no stream copy -> TRANSCODE_FALLBACK."""
        def fake_run(command, capture_output, text, check):
            if "-c" in command and command[command.index("-c") + 1] == "copy":
                return types.SimpleNamespace(returncode=1, stdout="", stderr="stream copy error: incompatible codec")
            Path(self.output_file).write_bytes(b"transcoded video")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        mock_run.side_effect = fake_run

        codec_result = video.concat_video_clips_with_ffmpeg(
            clip_files=[self.clip1, self.clip2],
            output_file=self.output_file,
            threads=2,
            output_dir=self.test_dir,
            max_duration=10.0,
            allow_stream_copy=True,
        )

        self.assertIn(codec_result, ["libx264", video._DEFAULT_VIDEO_CODEC])
        self.assertEqual(len(mock_run.call_args_list), 2)
        first_cmd = mock_run.call_args_list[0].args[0]
        self.assertEqual(first_cmd[first_cmd.index("-c") + 1], "copy")
        second_cmd = mock_run.call_args_list[1].args[0]
        self.assertIn("-c:v", second_cmd)

        warn_logs = [call.args[0] for call in mock_logger_warn.call_args_list if call.args]
        self.assertTrue(any("CONCAT_MODE=TRANSCODE_FALLBACK" in str(log) for log in warn_logs))

    @patch("app.services.video.logger.warning")
    @patch("app.services.video.subprocess.run")
    def test_stream_copy_zero_byte_output_triggers_transcode_fallback(
        self, mock_run, mock_logger_warn
    ):
        """Cenário 5: rc=0 mas arquivo de 0 bytes -> TRANSCODE_FALLBACK."""
        def fake_run(command, capture_output, text, check):
            if "-c" in command and command[command.index("-c") + 1] == "copy":
                Path(self.output_file).write_bytes(b"")
                return types.SimpleNamespace(returncode=0, stdout="", stderr="")
            Path(self.output_file).write_bytes(b"transcoded output")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        mock_run.side_effect = fake_run

        codec_result = video.concat_video_clips_with_ffmpeg(
            clip_files=[self.clip1, self.clip2],
            output_file=self.output_file,
            threads=2,
            output_dir=self.test_dir,
            max_duration=10.0,
            allow_stream_copy=True,
        )

        self.assertIn(codec_result, ["libx264", video._DEFAULT_VIDEO_CODEC])
        self.assertEqual(Path(self.output_file).read_bytes(), b"transcoded output")
        warn_logs = [call.args[0] for call in mock_logger_warn.call_args_list if call.args]
        self.assertTrue(any("CONCAT_MODE=TRANSCODE_FALLBACK" in str(log) for log in warn_logs))

    @patch("app.services.video.subprocess.run")
    def test_legacy_mode_does_not_attempt_stream_copy(self, mock_run):
        """Cenário 6: Modo legado não tenta stream copy."""
        def fake_run(command, capture_output, text, check):
            Path(self.output_file).write_bytes(b"transcoded video")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        mock_run.side_effect = fake_run

        video.concat_video_clips_with_ffmpeg(
            clip_files=[self.clip1, self.clip2],
            output_file=self.output_file,
            threads=2,
            output_dir=self.test_dir,
            max_duration=10.0,
            allow_stream_copy=False,
        )

        self.assertEqual(len(mock_run.call_args_list), 1)
        cmd = mock_run.call_args_list[0].args[0]
        self.assertIn("-c:v", cmd)
        self.assertNotIn("copy", cmd)


class TestThreadPropagation(unittest.TestCase):
    """Testes de propaga??o de threads nas escritas scene-based."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="threads_test_")
        self.dummy_video = os.path.join(self.test_dir, "clip.mp4")
        Path(self.dummy_video).write_bytes(b"video data")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("app.services.video.AudioFileClip")
    @patch("app.services.video._open_video_clip_quietly")
    @patch("app.services.video._write_videofile_with_codec_fallback")
    @patch("app.services.video.concat_video_clips_with_ffmpeg")
    def test_combine_videos_propagates_threads_to_scene_clip_writes(
        self, mock_concat, mock_write, mock_open, mock_audio
    ):
        mock_audio_instance = MagicMock()
        mock_audio_instance.duration = 4.0
        mock_audio.return_value = mock_audio_instance

        mock_clip = MagicMock()
        mock_clip.duration = 10.0
        mock_clip.size = (1080, 1920)
        mock_clip.subclipped.return_value = mock_clip
        mock_open.return_value = mock_clip

        instructions = [
            SceneClipInstruction(
                scene_index=1,
                material_path=self.dummy_video,
                duration_seconds=4.0,
            )
        ]

        video.combine_videos(
            combined_video_path=os.path.join(self.test_dir, "out.mp4"),
            video_paths=[],
            audio_file="dummy.mp3",
            threads=8,
            scene_clip_instructions=instructions,
        )

        mock_write.assert_called_once()
        self.assertEqual(mock_write.call_args[1].get("threads"), 8)
        mock_concat.assert_called_once()
        self.assertEqual(mock_concat.call_args[1].get("threads"), 8)


if __name__ == "__main__":
    unittest.main()
