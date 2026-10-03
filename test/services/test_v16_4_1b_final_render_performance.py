import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.models.schema import VideoParams
from app.services import video


class _FakeMoviePyClip:
    """Mock MoviePy clip para testes de fallback sem encoding pesado."""

    def __init__(self, *, duration=5, fps=44100):
        self.duration = duration
        self.fps = fps
        self.size = (1080, 1920)
        self.w = 1080
        self.h = 1920
        self.close_calls = 0
        self.with_audio_result = self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def close(self):
        self.close_calls += 1

    def with_effects(self, _effects):
        return self

    def with_audio(self, _audio):
        return self.with_audio_result


class TestFinalRenderPerformance(unittest.TestCase):
    """Testes unitários direcionados para V16.4.1B — Final Render Performance."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_v16_4_1b_")
        self.video_path = os.path.join(self.test_dir, "combined-1.mp4")
        self.audio_path = os.path.join(self.test_dir, "audio.mp3")
        self.subtitle_path = os.path.join(self.test_dir, "subs.srt")
        self.output_file = os.path.join(self.test_dir, "final-1.mp4")

        Path(self.video_path).write_bytes(b"dummy video data")
        Path(self.audio_path).write_bytes(b"dummy audio data")
        Path(self.subtitle_path).write_text(
            "1\n00:00:01,000 --> 00:00:03,000\nTeste de Legenda V16.4.1B\n\n",
            encoding="utf-8",
        )

        self.default_params = VideoParams(
            video_subject="Performance Test",
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
    @patch("app.services.video.logger.info")
    def test_final_render_with_subtitles_uses_ffmpeg_native(
        self, mock_logger, mock_mix, mock_render_ass, mock_validate
    ):
        """Cenário 1: Com legendas padrão -> FFMPEG_NATIVE."""
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
        mock_render_ass.assert_called_once()
        mock_validate.assert_called_once_with(self.output_file)

        # Log do modo
        info_logs = [call.args[0] for call in mock_logger.call_args_list if call.args]
        self.assertTrue(any("FINAL_RENDER_MODE=FFMPEG_NATIVE" in str(log) for log in info_logs))

        # Métricas subdivididas
        self.assertIn("FINAL_RENDER_PREP_SECONDS", timings)
        self.assertIn("FINAL_RENDER_AUDIO_SECONDS", timings)
        self.assertIn("FINAL_RENDER_SUBTITLE_SECONDS", timings)
        self.assertIn("FINAL_RENDER_ENCODE_SECONDS", timings)
        self.assertIn("FINAL_RENDER_SECONDS", timings)

    @patch("app.services.video._validate_final_render_output")
    @patch("app.services.video._render_final_stream_copy")
    @patch("app.services.video._mix_audio_ffmpeg")
    @patch("app.services.video.logger.info")
    def test_final_render_without_subtitles_uses_ffmpeg_stream_copy(
        self, mock_logger, mock_mix, mock_render_copy, mock_validate
    ):
        """Cenário 2: Sem legendas -> FFMPEG_STREAM_COPY (0 re-encodes de vídeo)."""
        mock_mix.return_value = True
        mock_render_copy.return_value = True
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
        mock_render_copy.assert_called_once()
        mock_validate.assert_called_once_with(self.output_file)

        info_logs = [call.args[0] for call in mock_logger.call_args_list if call.args]
        self.assertTrue(any("FINAL_RENDER_MODE=FFMPEG_STREAM_COPY" in str(log) for log in info_logs))

        self.assertIn("FINAL_RENDER_PREP_SECONDS", timings)
        self.assertIn("FINAL_RENDER_AUDIO_SECONDS", timings)
        self.assertIn("FINAL_RENDER_ENCODE_SECONDS", timings)
        self.assertIn("FINAL_RENDER_SECONDS", timings)

    @patch("app.services.video._write_videofile_with_codec_fallback")
    @patch("app.services.video.logger.info")
    def test_avatar_mode_triggers_moviepy_fallback(
        self, mock_logger, mock_write_videofile
    ):
        """Cenário 3: Virtual presenter ativado -> MOVIEPY_FALLBACK."""
        params = self.default_params.model_copy(update={"avatar_mode": "character_top"})
        timings = {}

        source_video = _FakeMoviePyClip()
        voice_source = _FakeMoviePyClip()

        with patch("app.services.video._open_video_clip_quietly", return_value=source_video), \
             patch("app.services.video.AudioFileClip", return_value=voice_source), \
             patch("app.services.presenter.build_presenter_clips", return_value=[]), \
             patch("app.services.video.SubtitlesClip") as mock_sub:
            mock_sub_inst = MagicMock()
            mock_sub_inst.subtitles = []
            mock_sub.return_value.__enter__.return_value = mock_sub_inst

            video.generate_video(
                video_path=self.video_path,
                audio_path=self.audio_path,
                subtitle_path="",
                output_file=self.output_file,
                params=params,
                render_timings=timings,
            )

        info_logs = [call.args[0] for call in mock_logger.call_args_list if call.args]
        self.assertTrue(any("FINAL_RENDER_MODE=MOVIEPY_FALLBACK" in str(log) for log in info_logs))
        mock_write_videofile.assert_called_once()
        self.assertIn("FINAL_RENDER_ENCODE_SECONDS", timings)

    @patch("app.services.video._write_videofile_with_codec_fallback")
    @patch("app.services.video.logger.info")
    def test_subtitle_animation_triggers_moviepy_fallback(
        self, mock_logger, mock_write_videofile
    ):
        """Cenário 4: Animação de mola ativada -> MOVIEPY_FALLBACK."""
        params = self.default_params.model_copy(update={"subtitle_animation": "pop_spring"})
        timings = {}

        source_video = _FakeMoviePyClip()
        voice_source = _FakeMoviePyClip()

        with patch("app.services.video._open_video_clip_quietly", return_value=source_video), \
             patch("app.services.video.AudioFileClip", return_value=voice_source), \
             patch("app.services.video.SubtitlesClip") as mock_sub:
            mock_sub_inst = MagicMock()
            mock_sub_inst.subtitles = []
            mock_sub.return_value.__enter__.return_value = mock_sub_inst

            video.generate_video(
                video_path=self.video_path,
                audio_path=self.audio_path,
                subtitle_path=self.subtitle_path,
                output_file=self.output_file,
                params=params,
                render_timings=timings,
            )

        info_logs = [call.args[0] for call in mock_logger.call_args_list if call.args]
        self.assertTrue(any("FINAL_RENDER_MODE=MOVIEPY_FALLBACK" in str(log) for log in info_logs))
        mock_write_videofile.assert_called_once()

    @patch("app.services.video._write_videofile_with_codec_fallback")
    @patch("app.services.video.logger.info")
    def test_rounded_background_triggers_moviepy_fallback(
        self, mock_logger, mock_write_videofile
    ):
        """Cenário 5: Fundo arredondado -> MOVIEPY_FALLBACK."""
        params = self.default_params.model_copy(
            update={"rounded_subtitle_background": True, "text_background_color": "#000000"}
        )
        timings = {}

        source_video = _FakeMoviePyClip()
        voice_source = _FakeMoviePyClip()

        with patch("app.services.video._open_video_clip_quietly", return_value=source_video), \
             patch("app.services.video.AudioFileClip", return_value=voice_source), \
             patch("app.services.video.SubtitlesClip") as mock_sub:
            mock_sub_inst = MagicMock()
            mock_sub_inst.subtitles = []
            mock_sub.return_value.__enter__.return_value = mock_sub_inst

            video.generate_video(
                video_path=self.video_path,
                audio_path=self.audio_path,
                subtitle_path=self.subtitle_path,
                output_file=self.output_file,
                params=params,
                render_timings=timings,
            )

        info_logs = [call.args[0] for call in mock_logger.call_args_list if call.args]
        self.assertTrue(any("FINAL_RENDER_MODE=MOVIEPY_FALLBACK" in str(log) for log in info_logs))
        mock_write_videofile.assert_called_once()

    @patch("app.services.video._write_videofile_with_codec_fallback")
    @patch("app.services.video._render_final_ffmpeg_ass")
    @patch("app.services.video._mix_audio_ffmpeg")
    @patch("app.services.video.logger.info")
    def test_ffmpeg_native_failure_triggers_moviepy_fallback(
        self, mock_logger, mock_mix, mock_render_ass, mock_write_videofile
    ):
        """Cenário 6: Falha no FFmpeg nativo -> MOVIEPY_FALLBACK."""
        mock_mix.return_value = True
        mock_render_ass.return_value = False  # FFmpeg falha
        timings = {}

        source_video = _FakeMoviePyClip()
        voice_source = _FakeMoviePyClip()

        with patch("app.services.video._open_video_clip_quietly", return_value=source_video), \
             patch("app.services.video.AudioFileClip", return_value=voice_source), \
             patch("app.services.video.SubtitlesClip") as mock_sub:
            mock_sub_inst = MagicMock()
            mock_sub_inst.subtitles = []
            mock_sub.return_value.__enter__.return_value = mock_sub_inst

            video.generate_video(
                video_path=self.video_path,
                audio_path=self.audio_path,
                subtitle_path=self.subtitle_path,
                output_file=self.output_file,
                params=self.default_params,
                render_timings=timings,
            )

        info_logs = [call.args[0] for call in mock_logger.call_args_list if call.args]
        self.assertTrue(any("FINAL_RENDER_MODE=MOVIEPY_FALLBACK" in str(log) for log in info_logs))
        mock_write_videofile.assert_called_once()

    @patch("app.services.video._write_videofile_with_codec_fallback")
    @patch("app.services.video._validate_final_render_output")
    @patch("app.services.video._render_final_ffmpeg_ass")
    @patch("app.services.video._mix_audio_ffmpeg")
    @patch("app.services.video.logger.info")
    def test_invalid_probe_triggers_moviepy_fallback(
        self, mock_logger, mock_mix, mock_render_ass, mock_validate, mock_write_videofile
    ):
        """Cenário 7: Arquivo gerado falha no probe -> MOVIEPY_FALLBACK."""
        mock_mix.return_value = True
        mock_render_ass.return_value = True
        mock_validate.return_value = False  # Saída inválida
        timings = {}

        source_video = _FakeMoviePyClip()
        voice_source = _FakeMoviePyClip()

        with patch("app.services.video._open_video_clip_quietly", return_value=source_video), \
             patch("app.services.video.AudioFileClip", return_value=voice_source), \
             patch("app.services.video.SubtitlesClip") as mock_sub:
            mock_sub_inst = MagicMock()
            mock_sub_inst.subtitles = []
            mock_sub.return_value.__enter__.return_value = mock_sub_inst

            video.generate_video(
                video_path=self.video_path,
                audio_path=self.audio_path,
                subtitle_path=self.subtitle_path,
                output_file=self.output_file,
                params=self.default_params,
                render_timings=timings,
            )

        info_logs = [call.args[0] for call in mock_logger.call_args_list if call.args]
        self.assertTrue(any("FINAL_RENDER_MODE=MOVIEPY_FALLBACK" in str(log) for log in info_logs))
        mock_write_videofile.assert_called_once()

    def test_convert_subtitles_to_ass_formatting(self):
        """Cenário 8: Validação da formatação ASS gerada."""
        ass_path = os.path.join(self.test_dir, "generated.ass")
        ok = video._convert_subtitles_to_ass(
            subtitle_path=self.subtitle_path,
            ass_path=ass_path,
            params=self.default_params,
            video_width=1080,
            video_height=1920,
            font_path=os.path.join(self.test_dir, "dummy.ttc"),
        )
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(ass_path))
        content = Path(ass_path).read_text(encoding="utf-8")

        self.assertIn("[Script Info]", content)
        self.assertIn("PlayResX: 1080", content)
        self.assertIn("PlayResY: 1920", content)
        self.assertIn("[V4+ Styles]", content)
        self.assertIn("Style: Default,", content)
        self.assertIn("&H00FFFFFF&", content)  # Primary color
        self.assertIn("&H00000000&", content)  # Outline color
        self.assertIn("Dialogue: 0,0:00:01.00,0:00:03.00,Default", content)
        self.assertIn("Teste de Legenda V16.4.1B", content)


if __name__ == "__main__":
    unittest.main()
