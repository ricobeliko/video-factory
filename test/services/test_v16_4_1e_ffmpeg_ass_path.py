import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.models.schema import VideoParams
from app.services import video
from app.utils import utils


class _FakeMoviePyClip:
    """Mock MoviePy clip para testes sem encoding pesado."""

    def __init__(self, *, duration=2, fps=30):
        self.duration = duration
        self.fps = fps
        self.size = (1080, 1920)
        self.w = 1080
        self.h = 1920
        self.close_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def close(self):
        self.close_calls += 1

    def with_effects(self, _effects):
        return self

    def with_audio(self, _audio):
        return self


class TestFFmpegAssPathResolution(unittest.TestCase):
    """
    Testes de regressão direcionados para V16.4.1E:
    Correção do bug de caminho relativo do filtro ASS no FFmpeg Native.
    
    Causa raiz:
    O filtro libass recebia caminho relativo a output_dir (virando apenas o basename),
    mas o subprocess FFmpeg herda os.getcwd(). Quando output_dir != os.getcwd(),
    a abertura do arquivo falhava com 'fopen failed' (rc=4294967274) e caía
    desnecessariamente no MoviePy fallback.
    """

    def setUp(self):
        # Cria diretório de teste dentro do workspace para simular tasks reais (storage/tasks/...)
        self.base_tasks_dir = os.path.join(os.getcwd(), "storage", "test_regression_tasks")
        os.makedirs(self.base_tasks_dir, exist_ok=True)
        self.task_dir = tempfile.mkdtemp(dir=self.base_tasks_dir, prefix="task_b789c82b_")

        self.video_path = os.path.join(self.task_dir, "combined-1.mp4")
        self.audio_path = os.path.join(self.task_dir, "audio.mp3")
        self.ass_path = os.path.join(self.task_dir, "temp-sub.ass")
        self.output_file = os.path.join(self.task_dir, "final-1.mp4")

        Path(self.video_path).write_bytes(b"dummy video data")
        Path(self.audio_path).write_bytes(b"dummy audio data")
        Path(self.ass_path).write_text(
            """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,60,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,50,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,Teste de legenda V16.4.1E
""",
            encoding="utf-8",
        )

        # Parâmetros reais auditados da task b789c82b-adb9-46c9-a7ac-d4c18cba16b9
        self.params = VideoParams(
            video_subject="Regressao ASS Path",
            video_aspect="9:16",
            subtitle_enabled=True,
            font_name="BeVietnamPro-Bold.ttf",
            font_size=60,
            text_fore_color="#FFFFFF",
            stroke_color="#000000",
            stroke_width=2,
            subtitle_position="bottom",
            avatar_mode="none",
            subtitle_animation="none",
            text_background_color=False,
            rounded_subtitle_background=False,
            bgm_type="",
        )

    def tearDown(self):
        shutil.rmtree(self.task_dir, ignore_errors=True)
        if os.path.exists(self.base_tasks_dir):
            try:
                os.rmdir(self.base_tasks_dir)
            except OSError:
                pass

    def test_01_output_dir_distinct_from_cwd(self):
        """1. Garante que o cenário de teste reproduz a situação real onde output_dir != os.getcwd()."""
        output_dir = os.path.dirname(os.path.abspath(self.output_file))
        self.assertNotEqual(
            os.path.normpath(output_dir),
            os.path.normpath(os.getcwd()),
            "output_dir deve ser diferente de os.getcwd() para reproduzir o bug",
        )
        self.assertTrue(os.path.exists(self.ass_path), "Arquivo ASS deve existir no disco")

    def test_02_ass_filter_path_not_incorrect_basename_and_resolves_from_cwd(self):
        """
        2. O caminho informado ao filtro libass:
        - NÃO deve ser apenas o basename (comportamento antigo com bug);
        - DEVE resolver corretamente a partir do working directory REAL (os.getcwd());
        - DEVE usar separadores Windows válidos (/);
        - DEVE preservar fontsdir.
        """
        captured_cmd = []

        def fake_run(cmd, staged_out):
            captured_cmd.extend(cmd)
            # Cria arquivo simulado de staged_output para o método continuar
            Path(staged_out).write_bytes(b"rendered video")
            mock_res = MagicMock()
            mock_res.returncode = 0
            return mock_res

        with patch("app.services.video._run_concat_with_heartbeat", side_effect=fake_run):
            ok = video._render_final_ffmpeg_ass(
                video_path=self.video_path,
                audio_path=self.audio_path,
                ass_path=self.ass_path,
                output_file=self.output_file,
            )

        self.assertTrue(ok)
        self.assertTrue(captured_cmd, "Comando FFmpeg deveria ter sido gerado")

        # Localiza o filtro -vf
        vf_idx = captured_cmd.index("-vf")
        vf_str = captured_cmd[vf_idx + 1]

        # Extrai o caminho do filtro ass=filename='...':fontsdir=...
        match = re.search(r"ass=filename='([^']+)':fontsdir=([^,]+)", vf_str)
        self.assertIsNotNone(match, f"Filtro ass mal formatado: {vf_str}")

        ass_filename_arg = match.group(1)
        fontsdir_arg = match.group(2)

        # 3. Caminho NÃO vira basename incorreto
        ass_basename = os.path.basename(self.ass_path)
        self.assertNotEqual(
            ass_filename_arg,
            ass_basename,
            f"Bug de basename relativo detectado: '{ass_filename_arg}' é apenas o basename de '{self.ass_path}'",
        )

        # 4. Caminho resolve corretamente a partir de os.getcwd()
        resolved_from_cwd = os.path.normpath(os.path.join(os.getcwd(), ass_filename_arg))
        expected_abs_ass = os.path.normpath(os.path.abspath(self.ass_path))

        self.assertTrue(
            os.path.exists(resolved_from_cwd),
            f"Caminho '{ass_filename_arg}' não pôde ser resolvido a partir de cwd '{os.getcwd()}'",
        )
        self.assertEqual(
            resolved_from_cwd,
            expected_abs_ass,
            f"Caminho resolvido '{resolved_from_cwd}' difere do arquivo real '{expected_abs_ass}'",
        )

        # 5. Separadores aceitos no FFmpeg (barras normais /, sem backslashes invertidas não escapadas)
        self.assertNotIn("\\", ass_filename_arg, "Caminho no filtro libass deve usar forward slashes (/)")

        # 6. fontsdir continua presente e configurado
        self.assertTrue(len(fontsdir_arg) > 0, "fontsdir deve estar presente")
        self.assertIn("fonts", fontsdir_arg)

    def test_03_old_behavior_fails_from_cwd_comparison(self):
        """
        3. Prova que o comportamento antigo falha ao resolver de os.getcwd(),
        enquanto o novo comportamento resolve com sucesso.
        """
        output_dir = os.path.dirname(os.path.abspath(self.output_file))

        # Lógica antiga
        old_ass_rel = os.path.relpath(self.ass_path, output_dir).replace("\\", "/")
        old_path_from_cwd = os.path.join(os.getcwd(), old_ass_rel)

        # Na lógica antiga, o arquivo NÃO existe no cwd
        self.assertFalse(
            os.path.exists(old_path_from_cwd),
            "No comportamento antigo, o arquivo DEVERIA falhar ao ser procurado no cwd",
        )

        # Lógica nova
        new_ass_rel = os.path.relpath(os.path.abspath(self.ass_path), os.getcwd()).replace("\\", "/")
        new_path_from_cwd = os.path.join(os.getcwd(), new_ass_rel)

        # Na lógica nova, o arquivo EXISTE
        self.assertTrue(
            os.path.exists(new_path_from_cwd),
            "No comportamento novo, o arquivo DEVE existir ao ser procurado no cwd",
        )

    def test_04_ffmpeg_native_eligibility_and_no_moviepy_fallback(self):
        """
        4. Comprova que parâmetros reais tornam a task elegível para FFMPEG_NATIVE,
        e que o fallback MoviePy NÃO é acionado quando o render nativo é bem-sucedido.
        """
        font_path = os.path.join(utils.font_dir(), "BeVietnamPro-Bold.ttf")
        subtitle_path = os.path.join(self.task_dir, "subs.srt")
        Path(subtitle_path).write_text("1\n00:00:00,000 --> 00:00:02,000\nTeste\n\n", encoding="utf-8")

        # 7. FFMPEG_NATIVE continua elegível
        can_native = video._can_use_ffmpeg_native_final_render(
            self.params, subtitle_path, font_path
        )
        self.assertTrue(can_native, "Task com parâmetros auditados DEVE ser elegível para FFMPEG_NATIVE")

        # 8. Fallback MoviePy não é acionado quando native render é válido
        with patch("app.services.video._mix_audio_ffmpeg", return_value=True), \
             patch("app.services.video._render_final_ffmpeg_ass", return_value=True) as mock_burn, \
             patch("app.services.video._validate_final_render_output", return_value=True), \
             patch("app.services.video.logger.info") as mock_info:

            timings = {}
            res = video.generate_video(
                video_path=self.video_path,
                audio_path=self.audio_path,
                subtitle_path=subtitle_path,
                output_file=self.output_file,
                params=self.params,
                render_timings=timings,
            )

            self.assertTrue(res)
            mock_burn.assert_called_once()
            self.assertEqual(timings.get("FINAL_RENDER_MODE"), "FFMPEG_NATIVE")

            logged_messages = [str(call.args[0]) for call in mock_info.call_args_list if call.args]
            self.assertTrue(any("FINAL_RENDER_MODE=FFMPEG_NATIVE" in m for m in logged_messages))
            self.assertFalse(any("FINAL_RENDER_MODE=MOVIEPY_FALLBACK" in m for m in logged_messages))

    def test_05_ffmpeg_native_failure_still_falls_back_safely(self):
        """5. Garante que se o render nativo falhar, o fallback para MoviePy continua funcional e seguro."""
        subtitle_path = os.path.join(self.task_dir, "subs.srt")
        Path(subtitle_path).write_text("1\n00:00:00,000 --> 00:00:02,000\nTeste\n\n", encoding="utf-8")

        source_video = _FakeMoviePyClip()
        voice_source = _FakeMoviePyClip()

        with patch("app.services.video._mix_audio_ffmpeg", return_value=True), \
             patch("app.services.video._render_final_ffmpeg_ass", return_value=False), \
             patch("app.services.video._open_video_clip_quietly", return_value=source_video), \
             patch("app.services.video.AudioFileClip", return_value=voice_source), \
             patch("app.services.video.SubtitlesClip") as mock_sub, \
             patch("app.services.video.CompositeVideoClip", return_value=_FakeMoviePyClip()), \
             patch("app.services.video._write_videofile_with_codec_fallback") as mock_write, \
             patch("app.services.video.logger.info") as mock_info:

            mock_sub_inst = MagicMock()
            mock_sub_inst.subtitles = []
            mock_sub.return_value.__enter__.return_value = mock_sub_inst

            timings = {}
            res = video.generate_video(
                video_path=self.video_path,
                audio_path=self.audio_path,
                subtitle_path=subtitle_path,
                output_file=self.output_file,
                params=self.params,
                render_timings=timings,
            )

            self.assertTrue(res)
            mock_write.assert_called_once()
            self.assertEqual(timings.get("FINAL_RENDER_MODE"), "MOVIEPY_FALLBACK")

            logged_messages = [str(call.args[0]) for call in mock_info.call_args_list if call.args]
            self.assertTrue(any("FINAL_RENDER_MODE=MOVIEPY_FALLBACK" in m for m in logged_messages))

    def test_06_real_ffmpeg_execution_with_ass_burn_in(self):
        """
        6. Teste de ponta a ponta com o binário real do FFmpeg:
        Gera um clipe de teste de 1 segundo e queima a legenda ASS quando output_dir != os.getcwd().
        Verifica que o FFmpeg conclui com rc=0 (sem erro de fopen na libass).
        """
        ffmpeg_exe = utils.get_ffmpeg_binary()
        if not os.path.isfile(ffmpeg_exe):
            self.skipTest("Binário do FFmpeg não encontrado")

        # Cria clipe de vídeo e áudio reais de 1 segundo
        test_video = os.path.join(self.task_dir, "real_input.mp4")
        test_audio = os.path.join(self.task_dir, "real_audio.mp4")
        real_output = os.path.join(self.task_dir, "real_output.mp4")

        # Cria vídeo preto de 1s
        import subprocess
        cmd_v = [
            ffmpeg_exe, "-y",
            "-f", "lavfi", "-i", "color=c=black:s=1080x1920:d=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
            test_video,
        ]
        res_v = subprocess.run(cmd_v, capture_output=True, text=True)
        self.assertEqual(res_v.returncode, 0, f"Falha ao gerar clipe de teste: {res_v.stderr}")

        # Cria áudio silencioso de 1s
        cmd_a = [
            ffmpeg_exe, "-y",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", "1", "-c:a", "aac",
            test_audio,
        ]
        res_a = subprocess.run(cmd_a, capture_output=True, text=True)
        self.assertEqual(res_a.returncode, 0, f"Falha ao gerar áudio de teste: {res_a.stderr}")

        # Executa _render_final_ffmpeg_ass REAL
        ok = video._render_final_ffmpeg_ass(
            video_path=test_video,
            audio_path=test_audio,
            ass_path=self.ass_path,
            output_file=real_output,
            threads=2,
            fps=30,
        )

        self.assertTrue(ok, "FFmpeg Native ASS render real deveria ter sucedido")
        self.assertTrue(os.path.exists(real_output), "Arquivo final gerado deve existir")
        self.assertGreater(os.path.getsize(real_output), 0, "Arquivo final gerado não pode ser vazio")


if __name__ == "__main__":
    unittest.main()
