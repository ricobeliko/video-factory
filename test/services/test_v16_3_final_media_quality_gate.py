"""
Testes Unitários do Final Media Quality Gate (Fase V16.3)

Regra Fundamental: AUTONOMOUS_FINAL_MEDIA_WITH_CRITICAL_DEFECT = FORBIDDEN

Validações:
- Integridade física de arquivo (existência, tamanho mínimo, arquivo regular)
- Probing com ffprobe (timeout, erros, json parsing)
- Streams de vídeo (presença, resolução, aspect ratio, orientação)
- Duração (duração positiva, compatibilidade com áudio)
- Streams de áudio (presença obrigatória em autônomo, duração)
- Contrato de legenda obrigatória (preservação do artefato SRT)
- Pipeline fail-closed (bloqueio de publicação, persistência de stage e reasons)
- Multi-vídeo (falha de 1 bloqueia o lote)
- Preservação do fluxo manual
- Robustez e segurança de caminhos/parsing
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.models import const
from app.models.schema import VideoAspect, VideoParams
from app.services import autonomous_production, media_quality, task as tm
from app.services import state as sm
from app.utils import utils


def make_dummy_media_file(dir_path: str, filename: str = "final-1.mp4", size_bytes: int = 15 * 1024) -> str:
    """Cria arquivo dummy em disco com tamanho configurável."""
    file_path = os.path.join(dir_path, filename)
    with open(file_path, "wb") as f:
        f.write(b"X" * size_bytes)
    return file_path


def make_valid_probe_payload(
    duration: float = 45.0,
    width: int = 1080,
    height: int = 1920,
    fps: str = "30/1",
    video_codec: str = "h264",
    audio_codec: str = "aac",
    has_audio: bool = True,
    file_size: int = 1024 * 1024,
) -> dict:
    """Retorna payload JSON representativo de probe de sucesso."""
    v_stream = {
        "codec_type": "video",
        "codec_name": video_codec,
        "width": width,
        "height": height,
        "r_frame_rate": fps,
        "duration": str(duration),
    }
    streams = [v_stream]
    if has_audio:
        a_stream = {
            "codec_type": "audio",
            "codec_name": audio_codec,
            "duration": str(duration),
        }
        streams.append(a_stream)

    return {
        "format": {
            "duration": str(duration),
            "size": str(file_size),
        },
        "streams": streams,
    }


class TestV16_3FinalMediaQualityGate(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # =========================================================================
    # A. CHECAGENS FÍSICAS DE ARQUIVO (1 a 4)
    # =========================================================================

    def test_01_missing_final_video_blocks(self):
        """1. Arquivo inexistente -> BLOCK com FINAL_MEDIA_MISSING."""
        res = media_quality.evaluate_final_media_quality(
            video_path=os.path.join(self.tmp_dir, "nonexistent.mp4"),
            required=True,
        )
        self.assertEqual(res["status"], "BLOCK")
        self.assertIn("FINAL_MEDIA_MISSING", res["reasons"])

    def test_02_directory_instead_of_file_blocks(self):
        """2. Diretório no lugar de arquivo -> BLOCK com FINAL_MEDIA_NOT_A_FILE."""
        sub_dir = os.path.join(self.tmp_dir, "not_a_file_dir")
        os.makedirs(sub_dir, exist_ok=True)
        res = media_quality.evaluate_final_media_quality(video_path=sub_dir, required=True)
        self.assertEqual(res["status"], "BLOCK")
        self.assertIn("FINAL_MEDIA_NOT_A_FILE", res["reasons"])

    def test_03_zero_bytes_blocks(self):
        """3. Arquivo vazio (0 bytes) -> BLOCK com FINAL_MEDIA_EMPTY."""
        empty_file = os.path.join(self.tmp_dir, "empty.mp4")
        with open(empty_file, "wb") as f:
            pass
        res = media_quality.evaluate_final_media_quality(video_path=empty_file, required=True)
        self.assertEqual(res["status"], "BLOCK")
        self.assertIn("FINAL_MEDIA_EMPTY", res["reasons"])

    def test_04_absurdly_small_file_blocks(self):
        """4. Arquivo absurdamente pequeno (<10KB) -> BLOCK com FINAL_MEDIA_TOO_SMALL."""
        small_file = make_dummy_media_file(self.tmp_dir, "too_small.mp4", size_bytes=500)
        res = media_quality.evaluate_final_media_quality(video_path=small_file, required=True)
        self.assertEqual(res["status"], "BLOCK")
        self.assertIn("FINAL_MEDIA_TOO_SMALL", res["reasons"])

    # =========================================================================
    # B. PROBE COM FFPROBE (5 a 8)
    # =========================================================================

    def test_05_ffprobe_unavailable_blocks(self):
        """5. ffprobe indisponível -> BLOCK com FFPROBE_UNAVAILABLE."""
        valid_file = make_dummy_media_file(self.tmp_dir, "media.mp4", size_bytes=15000)
        with patch("app.services.media_quality.get_ffprobe_binary", return_value=None):
            res = media_quality.evaluate_final_media_quality(video_path=valid_file, required=True)
            self.assertEqual(res["status"], "BLOCK")
            self.assertIn("FFPROBE_UNAVAILABLE", res["reasons"])

    def test_06_ffprobe_timeout_blocks(self):
        """6. ffprobe com timeout -> BLOCK com FFPROBE_TIMEOUT."""
        valid_file = make_dummy_media_file(self.tmp_dir, "media.mp4", size_bytes=15000)
        with patch("app.services.media_quality.get_ffprobe_binary", return_value="ffprobe"), \
             patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["ffprobe"], timeout=15)):
            res = media_quality.evaluate_final_media_quality(video_path=valid_file, required=True)
            self.assertEqual(res["status"], "BLOCK")
            self.assertIn("FFPROBE_TIMEOUT", res["reasons"])

    def test_07_ffprobe_invalid_json_blocks(self):
        """7. ffprobe retornando stdout com JSON corrompido -> BLOCK com FFPROBE_PARSE_ERROR."""
        valid_file = make_dummy_media_file(self.tmp_dir, "media.mp4", size_bytes=15000)
        mock_proc = MagicMock(returncode=0, stdout="not valid json {", stderr="")
        with patch("app.services.media_quality.get_ffprobe_binary", return_value="ffprobe"), \
             patch("subprocess.run", return_value=mock_proc):
            res = media_quality.evaluate_final_media_quality(video_path=valid_file, required=True)
            self.assertEqual(res["status"], "BLOCK")
            self.assertIn("FFPROBE_PARSE_ERROR", res["reasons"])

    def test_08_ffprobe_nonzero_exit_blocks(self):
        """8. ffprobe retornando exit code != 0 -> BLOCK com FFPROBE_FAILED."""
        valid_file = make_dummy_media_file(self.tmp_dir, "media.mp4", size_bytes=15000)
        mock_proc = MagicMock(returncode=1, stdout="", stderr="Invalid data found when processing input")
        with patch("app.services.media_quality.get_ffprobe_binary", return_value="ffprobe"), \
             patch("subprocess.run", return_value=mock_proc):
            res = media_quality.evaluate_final_media_quality(video_path=valid_file, required=True)
            self.assertEqual(res["status"], "BLOCK")
            self.assertIn("FFPROBE_FAILED", res["reasons"])

    # =========================================================================
    # C. STREAMS DE VÍDEO (9 a 17)
    # =========================================================================

    def test_09_no_video_stream_blocks(self):
        """9. Contêiner sem stream de vídeo -> BLOCK com NO_VIDEO_STREAM."""
        valid_file = make_dummy_media_file(self.tmp_dir, "audio_only.mp4", size_bytes=15000)
        payload = {
            "format": {"duration": "30.0", "size": "15000"},
            "streams": [{"codec_type": "audio", "codec_name": "aac"}],
        }
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        with patch("app.services.media_quality.get_ffprobe_binary", return_value="ffprobe"), \
             patch("subprocess.run", return_value=mock_proc):
            res = media_quality.evaluate_final_media_quality(video_path=valid_file, required=True)
            self.assertEqual(res["status"], "BLOCK")
            self.assertIn("NO_VIDEO_STREAM", res["reasons"])

    def test_10_valid_video_stream_continues(self):
        """10. Stream de vídeo válido -> avança sem erro de stream."""
        valid_file = make_dummy_media_file(self.tmp_dir, "video.mp4", size_bytes=15000)
        payload = make_valid_probe_payload(duration=30.0, width=1080, height=1920)
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        with patch("app.services.media_quality.get_ffprobe_binary", return_value="ffprobe"), \
             patch("subprocess.run", return_value=mock_proc):
            res = media_quality.evaluate_final_media_quality(video_path=valid_file, required=True)
            self.assertEqual(res["status"], "PASS")
            self.assertEqual(res["reasons"], [])

    def test_11_width_zero_blocks(self):
        """11. width=0 -> BLOCK com INVALID_DIMENSIONS."""
        valid_file = make_dummy_media_file(self.tmp_dir, "dim.mp4", size_bytes=15000)
        payload = make_valid_probe_payload(duration=30.0, width=0, height=1920)
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        with patch("app.services.media_quality.get_ffprobe_binary", return_value="ffprobe"), \
             patch("subprocess.run", return_value=mock_proc):
            res = media_quality.evaluate_final_media_quality(video_path=valid_file, required=True)
            self.assertEqual(res["status"], "BLOCK")
            self.assertIn("INVALID_DIMENSIONS", res["reasons"])

    def test_12_height_zero_blocks(self):
        """12. height=0 -> BLOCK com INVALID_DIMENSIONS."""
        valid_file = make_dummy_media_file(self.tmp_dir, "dim.mp4", size_bytes=15000)
        payload = make_valid_probe_payload(duration=30.0, width=1080, height=0)
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        with patch("app.services.media_quality.get_ffprobe_binary", return_value="ffprobe"), \
             patch("subprocess.run", return_value=mock_proc):
            res = media_quality.evaluate_final_media_quality(video_path=valid_file, required=True)
            self.assertEqual(res["status"], "BLOCK")
            self.assertIn("INVALID_DIMENSIONS", res["reasons"])

    def test_13_low_resolution_blocks(self):
        """13. Resolução muito baixa (ex: 480x854 quando esperado portrait >= 720x1280) -> BLOCK com RESOLUTION_TOO_LOW."""
        valid_file = make_dummy_media_file(self.tmp_dir, "low_res.mp4", size_bytes=15000)
        payload = make_valid_probe_payload(duration=30.0, width=480, height=854)
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        params = VideoParams(video_subject="Low res", video_aspect=VideoAspect.portrait.value)
        with patch("app.services.media_quality.get_ffprobe_binary", return_value="ffprobe"), \
             patch("subprocess.run", return_value=mock_proc):
            res = media_quality.evaluate_final_media_quality(video_path=valid_file, params=params, required=True)
            self.assertEqual(res["status"], "BLOCK")
            self.assertIn("RESOLUTION_TOO_LOW", res["reasons"])

    def test_14_valid_vertical_resolution_passes(self):
        """14. Resolução vertical 1080x1920 portrait -> PASS."""
        valid_file = make_dummy_media_file(self.tmp_dir, "vert.mp4", size_bytes=15000)
        payload = make_valid_probe_payload(duration=30.0, width=1080, height=1920)
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        params = VideoParams(video_subject="Vertical", video_aspect=VideoAspect.portrait.value)
        with patch("app.services.media_quality.get_ffprobe_binary", return_value="ffprobe"), \
             patch("subprocess.run", return_value=mock_proc):
            res = media_quality.evaluate_final_media_quality(video_path=valid_file, params=params, required=True)
            self.assertEqual(res["status"], "PASS")

    def test_15_valid_horizontal_resolution_passes(self):
        """15. Resolução horizontal 1920x1080 landscape esperada -> PASS."""
        valid_file = make_dummy_media_file(self.tmp_dir, "horiz.mp4", size_bytes=15000)
        payload = make_valid_probe_payload(duration=30.0, width=1920, height=1080)
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        params = VideoParams(video_subject="Horizontal", video_aspect=VideoAspect.landscape.value)
        with patch("app.services.media_quality.get_ffprobe_binary", return_value="ffprobe"), \
             patch("subprocess.run", return_value=mock_proc):
            res = media_quality.evaluate_final_media_quality(video_path=valid_file, params=params, required=True)
            self.assertEqual(res["status"], "PASS")

    def test_16_wrong_orientation_blocks(self):
        """16. Orientação errada (esperado portrait 9:16 mas gerado horizontal 1920x1080) -> BLOCK com ASPECT_RATIO_MISMATCH."""
        valid_file = make_dummy_media_file(self.tmp_dir, "inverted.mp4", size_bytes=15000)
        payload = make_valid_probe_payload(duration=30.0, width=1920, height=1080)
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        params = VideoParams(video_subject="Inverted", video_aspect=VideoAspect.portrait.value)
        with patch("app.services.media_quality.get_ffprobe_binary", return_value="ffprobe"), \
             patch("subprocess.run", return_value=mock_proc):
            res = media_quality.evaluate_final_media_quality(video_path=valid_file, params=params, required=True)
            self.assertEqual(res["status"], "BLOCK")
            self.assertIn("ASPECT_RATIO_MISMATCH", res["reasons"])

    def test_17_aspect_mismatch_blocks(self):
        """17. Aspect ratio com desvio substancial (ex: 950x1280 ratio=0.742 vs 0.5625) -> BLOCK."""
        valid_file = make_dummy_media_file(self.tmp_dir, "mismatch.mp4", size_bytes=15000)
        payload = make_valid_probe_payload(duration=30.0, width=950, height=1280)
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        params = VideoParams(video_subject="Mismatch", video_aspect=VideoAspect.portrait.value)
        with patch("app.services.media_quality.get_ffprobe_binary", return_value="ffprobe"), \
             patch("subprocess.run", return_value=mock_proc):
            res = media_quality.evaluate_final_media_quality(video_path=valid_file, params=params, required=True)
            self.assertEqual(res["status"], "BLOCK")
            self.assertIn("ASPECT_RATIO_MISMATCH", res["reasons"])

    # =========================================================================
    # D. DURAÇÃO (18 a 22)
    # =========================================================================

    def test_18_zero_duration_blocks(self):
        """18. Duração zero -> BLOCK com INVALID_VIDEO_DURATION."""
        valid_file = make_dummy_media_file(self.tmp_dir, "zero_dur.mp4", size_bytes=15000)
        payload = make_valid_probe_payload(duration=0.0, width=1080, height=1920)
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        with patch("app.services.media_quality.get_ffprobe_binary", return_value="ffprobe"), \
             patch("subprocess.run", return_value=mock_proc):
            res = media_quality.evaluate_final_media_quality(video_path=valid_file, required=True)
            self.assertEqual(res["status"], "BLOCK")
            self.assertIn("INVALID_VIDEO_DURATION", res["reasons"])

    def test_19_negative_or_nan_duration_blocks(self):
        """19. Duração negativa ou NaN -> BLOCK com INVALID_VIDEO_DURATION."""
        valid_file = make_dummy_media_file(self.tmp_dir, "neg_dur.mp4", size_bytes=15000)
        payload = make_valid_probe_payload(duration=-5.0, width=1080, height=1920)
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        with patch("app.services.media_quality.get_ffprobe_binary", return_value="ffprobe"), \
             patch("subprocess.run", return_value=mock_proc):
            res = media_quality.evaluate_final_media_quality(video_path=valid_file, required=True)
            self.assertEqual(res["status"], "BLOCK")
            self.assertIn("INVALID_VIDEO_DURATION", res["reasons"])

    def test_20_expected_45s_final_2s_blocks(self):
        """20. Áudio esperado 45s e vídeo final 2s -> BLOCK com AUDIO_VIDEO_DURATION_MISMATCH."""
        valid_file = make_dummy_media_file(self.tmp_dir, "short_video.mp4", size_bytes=15000)
        payload = make_valid_probe_payload(duration=2.0, width=1080, height=1920)
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        with patch("app.services.media_quality.get_ffprobe_binary", return_value="ffprobe"), \
             patch("subprocess.run", return_value=mock_proc):
            res = media_quality.evaluate_final_media_quality(
                video_path=valid_file,
                expected_audio_duration=45.0,
                required=True,
            )
            self.assertEqual(res["status"], "BLOCK")
            self.assertIn("AUDIO_VIDEO_DURATION_MISMATCH", res["reasons"])

    def test_21_expected_45s_final_45s_passes(self):
        """21. Áudio esperado 45s e vídeo final 45s -> PASS."""
        valid_file = make_dummy_media_file(self.tmp_dir, "match_video.mp4", size_bytes=15000)
        payload = make_valid_probe_payload(duration=45.0, width=1080, height=1920)
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        with patch("app.services.media_quality.get_ffprobe_binary", return_value="ffprobe"), \
             patch("subprocess.run", return_value=mock_proc):
            res = media_quality.evaluate_final_media_quality(
                video_path=valid_file,
                expected_audio_duration=45.0,
                required=True,
            )
            self.assertEqual(res["status"], "PASS")

    def test_22_small_normal_tolerance_passes(self):
        """22. Áudio esperado 45s e vídeo 44.5s ou 46.2s -> PASS dentro da tolerância."""
        valid_file = make_dummy_media_file(self.tmp_dir, "tol_video.mp4", size_bytes=15000)
        payload = make_valid_probe_payload(duration=44.5, width=1080, height=1920)
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        with patch("app.services.media_quality.get_ffprobe_binary", return_value="ffprobe"), \
             patch("subprocess.run", return_value=mock_proc):
            res = media_quality.evaluate_final_media_quality(
                video_path=valid_file,
                expected_audio_duration=45.0,
                required=True,
            )
            self.assertEqual(res["status"], "PASS")

    # =========================================================================
    # E. ÁUDIO (23 a 25)
    # =========================================================================

    def test_23_autonomous_narrated_no_audio_stream_blocks(self):
        """23. Vídeo autônomo com locução mas sem stream de áudio -> BLOCK com NO_AUDIO_STREAM."""
        valid_file = make_dummy_media_file(self.tmp_dir, "no_audio.mp4", size_bytes=15000)
        payload = make_valid_probe_payload(duration=30.0, width=1080, height=1920, has_audio=False)
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        params = VideoParams(video_subject="Test", voice_name="pt-BR-AntonioNeural")
        with patch("app.services.media_quality.get_ffprobe_binary", return_value="ffprobe"), \
             patch("subprocess.run", return_value=mock_proc):
            res = media_quality.evaluate_final_media_quality(
                video_path=valid_file,
                params=params,
                required=True,
            )
            self.assertEqual(res["status"], "BLOCK")
            self.assertIn("NO_AUDIO_STREAM", res["reasons"])

    def test_24_audio_stream_present_passes(self):
        """24. Stream de áudio presente com duração válida -> PASS."""
        valid_file = make_dummy_media_file(self.tmp_dir, "with_audio.mp4", size_bytes=15000)
        payload = make_valid_probe_payload(duration=30.0, width=1080, height=1920, has_audio=True)
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        params = VideoParams(video_subject="Test", voice_name="pt-BR-AntonioNeural")
        with patch("app.services.media_quality.get_ffprobe_binary", return_value="ffprobe"), \
             patch("subprocess.run", return_value=mock_proc):
            res = media_quality.evaluate_final_media_quality(
                video_path=valid_file,
                params=params,
                required=True,
            )
            self.assertEqual(res["status"], "PASS")
            self.assertTrue(res["metrics"]["has_audio"])

    def test_25_invalid_audio_duration_blocks(self):
        """25. Stream de áudio presente com duration <= 0 -> BLOCK com INVALID_AUDIO_DURATION."""
        valid_file = make_dummy_media_file(self.tmp_dir, "corrupt_audio.mp4", size_bytes=15000)
        payload = make_valid_probe_payload(duration=30.0, width=1080, height=1920, has_audio=True)
        payload["streams"][1]["duration"] = "0.0"
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        params = VideoParams(video_subject="Test", voice_name="pt-BR-AntonioNeural")
        with patch("app.services.media_quality.get_ffprobe_binary", return_value="ffprobe"), \
             patch("subprocess.run", return_value=mock_proc):
            res = media_quality.evaluate_final_media_quality(
                video_path=valid_file,
                params=params,
                required=True,
            )
            self.assertEqual(res["status"], "BLOCK")
            self.assertIn("INVALID_AUDIO_DURATION", res["reasons"])

    # =========================================================================
    # F. CONTRATO DE LEGENDA (26 a 28)
    # =========================================================================

    def test_26_subtitle_required_missing_srt_blocks(self):
        """26. subtitle_required=True com SRT ausente -> BLOCK com SUBTITLE_ARTIFACT_MISSING."""
        valid_file = make_dummy_media_file(self.tmp_dir, "vid.mp4", size_bytes=15000)
        payload = make_valid_probe_payload(duration=30.0, width=1080, height=1920)
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        params = VideoParams(
            video_subject="Test",
            subtitle_enabled=True,
            subtitle_required=True,
        )
        with patch("app.services.media_quality.get_ffprobe_binary", return_value="ffprobe"), \
             patch("subprocess.run", return_value=mock_proc):
            res = media_quality.evaluate_final_media_quality(
                video_path=valid_file,
                params=params,
                subtitle_path=os.path.join(self.tmp_dir, "missing.srt"),
                required=True,
            )
            self.assertEqual(res["status"], "BLOCK")
            self.assertIn("SUBTITLE_ARTIFACT_MISSING", res["reasons"])

    def test_27_subtitle_required_false_does_not_block(self):
        """27. subtitle_required=False -> não bloqueia por falta de SRT."""
        valid_file = make_dummy_media_file(self.tmp_dir, "vid.mp4", size_bytes=15000)
        payload = make_valid_probe_payload(duration=30.0, width=1080, height=1920)
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        params = VideoParams(
            video_subject="Test",
            subtitle_enabled=True,
            subtitle_required=False,
        )
        with patch("app.services.media_quality.get_ffprobe_binary", return_value="ffprobe"), \
             patch("subprocess.run", return_value=mock_proc):
            res = media_quality.evaluate_final_media_quality(
                video_path=valid_file,
                params=params,
                subtitle_path=None,
                required=True,
            )
            self.assertEqual(res["status"], "PASS")

    def test_28_valid_subtitle_artifact_passes(self):
        """28. subtitle_required=True com SRT válido -> PASS."""
        valid_file = make_dummy_media_file(self.tmp_dir, "vid.mp4", size_bytes=15000)
        srt_file = os.path.join(self.tmp_dir, "valid.srt")
        with open(srt_file, "w", encoding="utf-8") as f:
            f.write("1\n00:00:00,100 --> 00:00:03,000\nTexto valido de legenda.\n\n")

        payload = make_valid_probe_payload(duration=30.0, width=1080, height=1920)
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        params = VideoParams(
            video_subject="Test",
            subtitle_enabled=True,
            subtitle_required=True,
        )
        with patch("app.services.media_quality.get_ffprobe_binary", return_value="ffprobe"), \
             patch("subprocess.run", return_value=mock_proc):
            res = media_quality.evaluate_final_media_quality(
                video_path=valid_file,
                params=params,
                subtitle_path=srt_file,
                required=True,
            )
            self.assertEqual(res["status"], "PASS")

    # =========================================================================
    # G. PIPELINE & INTEGRAÇÃO (29 a 34)
    # =========================================================================

    def test_29_pipeline_gate_pass_allows_completion(self):
        """29. Gate PASS no pipeline -> tarefa avança para conclusão e agendamento."""
        task_id = "test-pipe-pass"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            valid_mp4 = make_dummy_media_file(task_dir, "final-1.mp4", size_bytes=15000)
            audio_file = os.path.join(task_dir, "audio.mp3")
            with open(audio_file, "wb") as f:
                f.write(b"AUDIO")
            srt_file = os.path.join(task_dir, "audio.srt")
            with open(srt_file, "w", encoding="utf-8") as f:
                f.write("1\n00:00:00,100 --> 00:00:03,000\nLegenda.\n\n")

            params = VideoParams(
                video_subject="Pipeline Pass",
                final_media_quality_required=True,
            )

            mock_eval = {
                "status": "PASS",
                "reasons": [],
                "metrics": {"duration": 30.0, "width": 1080, "height": 1920},
            }

            with patch("app.services.task.generate_script", return_value="Script"), \
                 patch("app.services.task.generate_terms", return_value=["terms"]), \
                 patch("app.services.task.generate_audio", return_value=(audio_file, 30.0, MagicMock())), \
                 patch("app.services.task.generate_subtitle", return_value=srt_file), \
                 patch("app.services.task.get_video_materials", return_value=["mat1.mp4"]), \
                 patch("app.services.task.generate_final_videos", return_value=([valid_mp4], [valid_mp4], [])), \
                 patch("app.services.media_quality.evaluate_final_media_quality", return_value=mock_eval), \
                 patch("app.services.task._schedule_cross_post", return_value=None) as mock_cross_post:

                res = tm.start(task_id, params, stop_at="video")
                task_record = sm.state.get_task(task_id) or {}
                self.assertEqual(task_record.get("state"), const.TASK_STATE_COMPLETE)
                self.assertEqual(res.get("final_media_quality_status"), "PASS")
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_30_pipeline_gate_block_prevents_crosspost(self):
        """30. Gate BLOCK no pipeline -> cross-post NÃO é agendado."""
        task_id = "test-pipe-block-crosspost"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            bad_mp4 = make_dummy_media_file(task_dir, "final-1.mp4", size_bytes=15000)
            audio_file = os.path.join(task_dir, "audio.mp3")
            with open(audio_file, "wb") as f:
                f.write(b"AUDIO")
            srt_file = os.path.join(task_dir, "audio.srt")
            with open(srt_file, "w", encoding="utf-8") as f:
                f.write("1\n00:00:00,100 --> 00:00:03,000\nLegenda.\n\n")

            params = VideoParams(
                video_subject="Pipeline Block",
                final_media_quality_required=True,
            )

            mock_eval = {
                "status": "BLOCK",
                "reasons": ["NO_AUDIO_STREAM"],
                "metrics": {"duration": 30.0, "width": 1080, "height": 1920},
            }

            with patch("app.services.task.generate_script", return_value="Script"), \
                 patch("app.services.task.generate_terms", return_value=["terms"]), \
                 patch("app.services.task.generate_audio", return_value=(audio_file, 30.0, MagicMock())), \
                 patch("app.services.task.generate_subtitle", return_value=srt_file), \
                 patch("app.services.task.get_video_materials", return_value=["mat1.mp4"]), \
                 patch("app.services.task.generate_final_videos", return_value=([bad_mp4], [bad_mp4], [])), \
                 patch("app.services.media_quality.evaluate_final_media_quality", return_value=mock_eval), \
                 patch("app.services.task._schedule_cross_post") as mock_cross_post:

                res = tm.start(task_id, params, stop_at="video")
                self.assertEqual(res.get("state"), const.TASK_STATE_FAILED)
                self.assertEqual(res.get("failed_stage"), "final_media_quality")
                mock_cross_post.assert_not_called()
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_31_pipeline_gate_block_prevents_publication(self):
        """31. Gate BLOCK no pipeline -> funções de publicação nunca são chamadas."""
        task_id = "test-pipe-block-pub"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            bad_mp4 = make_dummy_media_file(task_dir, "final-1.mp4", size_bytes=15000)
            params = VideoParams(
                video_subject="Pipeline Block Pub",
                final_media_quality_required=True,
            )

            mock_eval = {
                "status": "BLOCK",
                "reasons": ["FINAL_MEDIA_TOO_SMALL"],
                "metrics": {},
            }

            with patch("app.services.task.generate_script", return_value="Script"), \
                 patch("app.services.task.generate_terms", return_value=["terms"]), \
                 patch("app.services.task.generate_audio", return_value=("a.mp3", 30.0, MagicMock())), \
                 patch("app.services.task.generate_subtitle", return_value="a.srt"), \
                 patch("app.services.task.get_video_materials", return_value=["m.mp4"]), \
                 patch("app.services.task.generate_final_videos", return_value=([bad_mp4], [bad_mp4], [])), \
                 patch("app.services.media_quality.evaluate_final_media_quality", return_value=mock_eval), \
                 patch("app.services.task._run_cross_post") as mock_run_pub:

                res = tm.start(task_id, params, stop_at="video")
                self.assertEqual(res.get("state"), const.TASK_STATE_FAILED)
                mock_run_pub.assert_not_called()
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_32_pipeline_gate_persists_failed_stage(self):
        """32. Tarefa com falha no media gate persiste failed_stage='final_media_quality'."""
        task_id = "test-pipe-failed-stage"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            bad_mp4 = make_dummy_media_file(task_dir, "final-1.mp4", size_bytes=15000)
            params = VideoParams(
                video_subject="Failed Stage",
                final_media_quality_required=True,
            )

            mock_eval = {
                "status": "BLOCK",
                "reasons": ["RESOLUTION_TOO_LOW"],
                "metrics": {},
            }

            with patch("app.services.task.generate_script", return_value="Script"), \
                 patch("app.services.task.generate_terms", return_value=["terms"]), \
                 patch("app.services.task.generate_audio", return_value=("a.mp3", 30.0, MagicMock())), \
                 patch("app.services.task.generate_subtitle", return_value="a.srt"), \
                 patch("app.services.task.get_video_materials", return_value=["m.mp4"]), \
                 patch("app.services.task.generate_final_videos", return_value=([bad_mp4], [bad_mp4], [])), \
                 patch("app.services.media_quality.evaluate_final_media_quality", return_value=mock_eval):

                res = tm.start(task_id, params, stop_at="video")
                self.assertEqual(res.get("state"), const.TASK_STATE_FAILED)
                self.assertEqual(res.get("failed_stage"), "final_media_quality")
                self.assertIn("RESOLUTION_TOO_LOW", res.get("error", ""))
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_33_pipeline_gate_reasons_persisted(self):
        """33. Razões de bloqueio persistem no details/state."""
        task_id = "test-pipe-reasons"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            bad_mp4 = make_dummy_media_file(task_dir, "final-1.mp4", size_bytes=15000)
            params = VideoParams(
                video_subject="Reasons Test",
                final_media_quality_required=True,
            )

            mock_eval = {
                "status": "BLOCK",
                "reasons": ["NO_AUDIO_STREAM", "ASPECT_RATIO_MISMATCH"],
                "metrics": {},
            }

            with patch("app.services.task.generate_script", return_value="Script"), \
                 patch("app.services.task.generate_terms", return_value=["terms"]), \
                 patch("app.services.task.generate_audio", return_value=("a.mp3", 30.0, MagicMock())), \
                 patch("app.services.task.generate_subtitle", return_value="a.srt"), \
                 patch("app.services.task.get_video_materials", return_value=["m.mp4"]), \
                 patch("app.services.task.generate_final_videos", return_value=([bad_mp4], [bad_mp4], [])), \
                 patch("app.services.media_quality.evaluate_final_media_quality", return_value=mock_eval):

                res = tm.start(task_id, params, stop_at="video")
                self.assertEqual(res.get("final_media_quality_status"), "BLOCK")
                self.assertIn("NO_AUDIO_STREAM", res.get("final_media_quality_reasons", []))
                self.assertIn("ASPECT_RATIO_MISMATCH", res.get("final_media_quality_reasons", []))
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_34_pipeline_gate_metrics_persisted(self):
        """34. Métricas consolidadas persistem no details/state."""
        task_id = "test-pipe-metrics"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            bad_mp4 = make_dummy_media_file(task_dir, "final-1.mp4", size_bytes=15000)
            params = VideoParams(
                video_subject="Metrics Test",
                final_media_quality_required=True,
            )

            metrics_data = {"duration": 28.5, "width": 1080, "height": 1920, "video_codec": "h264"}
            mock_eval = {
                "status": "BLOCK",
                "reasons": ["NO_AUDIO_STREAM"],
                "metrics": metrics_data,
            }

            with patch("app.services.task.generate_script", return_value="Script"), \
                 patch("app.services.task.generate_terms", return_value=["terms"]), \
                 patch("app.services.task.generate_audio", return_value=("a.mp3", 30.0, MagicMock())), \
                 patch("app.services.task.generate_subtitle", return_value="a.srt"), \
                 patch("app.services.task.get_video_materials", return_value=["m.mp4"]), \
                 patch("app.services.task.generate_final_videos", return_value=([bad_mp4], [bad_mp4], [])), \
                 patch("app.services.media_quality.evaluate_final_media_quality", return_value=mock_eval):

                res = tm.start(task_id, params, stop_at="video")
                self.assertEqual(res.get("final_media_quality_metrics"), metrics_data)
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    # =========================================================================
    # H. MULTI-VÍDEO (35 a 36)
    # =========================================================================

    def test_35_multi_video_one_fails_task_blocks(self):
        """35. Multi-vídeo: vídeo 1 PASS e vídeo 2 BLOCK -> tarefa falha como BLOCK."""
        task_id = "test-multi-fail"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            v1 = make_dummy_media_file(task_dir, "final-1.mp4", size_bytes=15000)
            v2 = make_dummy_media_file(task_dir, "final-2.mp4", size_bytes=15000)
            params = VideoParams(
                video_subject="Multi Video Test",
                video_count=2,
                final_media_quality_required=True,
            )

            eval_v1 = {"status": "PASS", "reasons": [], "metrics": {"duration": 30.0}}
            eval_v2 = {"status": "BLOCK", "reasons": ["NO_AUDIO_STREAM"], "metrics": {"duration": 30.0}}

            with patch("app.services.task.generate_script", return_value="Script"), \
                 patch("app.services.task.generate_terms", return_value=["terms"]), \
                 patch("app.services.task.generate_audio", return_value=("a.mp3", 30.0, MagicMock())), \
                 patch("app.services.task.generate_subtitle", return_value="a.srt"), \
                 patch("app.services.task.get_video_materials", return_value=["m.mp4"]), \
                 patch("app.services.task.generate_final_videos", return_value=([v1, v2], [v1, v2], [])), \
                 patch("app.services.media_quality.evaluate_final_media_quality", side_effect=[eval_v1, eval_v2]):

                res = tm.start(task_id, params, stop_at="video")
                self.assertEqual(res.get("state"), const.TASK_STATE_FAILED)
                self.assertEqual(res.get("failed_stage"), "final_media_quality")
                self.assertIn("NO_AUDIO_STREAM", res.get("error", ""))
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_36_multi_video_all_pass_task_succeeds(self):
        """36. Multi-vídeo: ambos os vídeos PASS -> tarefa avança para COMPLETE."""
        task_id = "test-multi-pass"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            v1 = make_dummy_media_file(task_dir, "final-1.mp4", size_bytes=15000)
            v2 = make_dummy_media_file(task_dir, "final-2.mp4", size_bytes=15000)
            params = VideoParams(
                video_subject="Multi Video Pass",
                video_count=2,
                final_media_quality_required=True,
            )

            eval_v1 = {"status": "PASS", "reasons": [], "metrics": {"duration": 30.0}}
            eval_v2 = {"status": "PASS", "reasons": [], "metrics": {"duration": 30.0}}

            with patch("app.services.task.generate_script", return_value="Script"), \
                 patch("app.services.task.generate_terms", return_value=["terms"]), \
                 patch("app.services.task.generate_audio", return_value=("a.mp3", 30.0, MagicMock())), \
                 patch("app.services.task.generate_subtitle", return_value="a.srt"), \
                 patch("app.services.task.get_video_materials", return_value=["m.mp4"]), \
                 patch("app.services.task.generate_final_videos", return_value=([v1, v2], [v1, v2], [])), \
                 patch("app.services.media_quality.evaluate_final_media_quality", side_effect=[eval_v1, eval_v2]), \
                 patch("app.services.task._schedule_cross_post", return_value=None):

                res = tm.start(task_id, params, stop_at="video")
                task_record = sm.state.get_task(task_id) or {}
                self.assertEqual(task_record.get("state"), const.TASK_STATE_COMPLETE)
                self.assertEqual(res.get("final_media_quality_status"), "PASS")
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    # =========================================================================
    # I. FLUXO MANUAL (37 a 38)
    # =========================================================================

    def test_37_manual_flow_without_strict_requirement_preserved(self):
        """37. final_media_quality_required=False (modo manual) não interrompe a tarefa."""
        task_id = "test-manual-preserve"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            mp4_file = make_dummy_media_file(task_dir, "final-1.mp4", size_bytes=15000)
            params = VideoParams(
                video_subject="Manual Generation",
                final_media_quality_required=False,
            )

            mock_eval = {
                "status": "BLOCK",
                "reasons": ["NO_AUDIO_STREAM"],
                "metrics": {},
            }

            with patch("app.services.task.generate_script", return_value="Script"), \
                 patch("app.services.task.generate_terms", return_value=["terms"]), \
                 patch("app.services.task.generate_audio", return_value=("a.mp3", 30.0, MagicMock())), \
                 patch("app.services.task.generate_subtitle", return_value="a.srt"), \
                 patch("app.services.task.get_video_materials", return_value=["m.mp4"]), \
                 patch("app.services.task.generate_final_videos", return_value=([mp4_file], [mp4_file], [])), \
                 patch("app.services.media_quality.evaluate_final_media_quality", return_value=mock_eval), \
                 patch("app.services.task._schedule_cross_post", return_value=None):

                res = tm.start(task_id, params, stop_at="video")
                task_record = sm.state.get_task(task_id) or {}
                self.assertEqual(task_record.get("state"), const.TASK_STATE_COMPLETE)
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_38_autonomous_params_builder_enforces_strict_flag(self):
        """38. Builder de parâmetros autônomos define final_media_quality_required=True."""
        params = autonomous_production.build_autonomous_video_params("Test Topic", profile_id=None)
        self.assertTrue(params.final_media_quality_required)
        self.assertTrue(params.subtitle_required)
        self.assertEqual(params.video_language, "pt-BR")

    # =========================================================================
    # J. ROBUSTEZ E TRATAMENTO SEGURO (39 a 44)
    # =========================================================================

    def test_39_codec_name_missing_does_not_block(self):
        """39. Nome de codec ausente -> registra 'unknown' e não bloqueia se o stream for válido."""
        valid_file = make_dummy_media_file(self.tmp_dir, "no_codec.mp4", size_bytes=15000)
        payload = make_valid_probe_payload(duration=30.0, width=1080, height=1920)
        del payload["streams"][0]["codec_name"]
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        with patch("app.services.media_quality.get_ffprobe_binary", return_value="ffprobe"), \
             patch("subprocess.run", return_value=mock_proc):
            res = media_quality.evaluate_final_media_quality(video_path=valid_file, required=True)
            self.assertEqual(res["status"], "PASS")
            self.assertEqual(res["metrics"]["video_codec"], "unknown")

    def test_40_fps_missing_does_not_block(self):
        """40. fps ausente ou não parseável -> fallback gracioso para 30.0 sem bloquear."""
        valid_file = make_dummy_media_file(self.tmp_dir, "no_fps.mp4", size_bytes=15000)
        payload = make_valid_probe_payload(duration=30.0, width=1080, height=1920)
        payload["streams"][0]["r_frame_rate"] = "invalid_fps"
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        with patch("app.services.media_quality.get_ffprobe_binary", return_value="ffprobe"), \
             patch("subprocess.run", return_value=mock_proc):
            res = media_quality.evaluate_final_media_quality(video_path=valid_file, required=True)
            self.assertEqual(res["status"], "PASS")
            self.assertEqual(res["metrics"]["fps"], 30.0)

    def test_41_numeric_strings_parse_safely(self):
        """41. Valores numéricos em formato string são parseados seguramente."""
        valid_file = make_dummy_media_file(self.tmp_dir, "str_num.mp4", size_bytes=15000)
        payload = make_valid_probe_payload(duration=35.123, width=1080, height=1920)
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        with patch("app.services.media_quality.get_ffprobe_binary", return_value="ffprobe"), \
             patch("subprocess.run", return_value=mock_proc):
            res = media_quality.evaluate_final_media_quality(video_path=valid_file, required=True)
            self.assertEqual(res["status"], "PASS")
            self.assertEqual(res["metrics"]["width"], 1080)
            self.assertEqual(res["metrics"]["height"], 1920)
            self.assertAlmostEqual(res["metrics"]["duration"], 35.123, places=2)

    def test_42_malformed_numeric_fields_fail_closed_safely(self):
        """42. Campos numéricos corrompidos (ex: width='abc') falham fechados sem exceção não tratada."""
        valid_file = make_dummy_media_file(self.tmp_dir, "corrupt_width.mp4", size_bytes=15000)
        payload = make_valid_probe_payload(duration=30.0, width=1080, height=1920)
        payload["streams"][0]["width"] = "not_a_number"
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        with patch("app.services.media_quality.get_ffprobe_binary", return_value="ffprobe"), \
             patch("subprocess.run", return_value=mock_proc):
            res = media_quality.evaluate_final_media_quality(video_path=valid_file, required=True)
            self.assertEqual(res["status"], "BLOCK")
            self.assertIn("INVALID_DIMENSIONS", res["reasons"])

    def test_43_huge_hour_durations_parse_safely(self):
        """43. Duração grande de horas (ex: 7200s) é parseada seguramente sem overflow."""
        valid_file = make_dummy_media_file(self.tmp_dir, "long_video.mp4", size_bytes=15000)
        payload = make_valid_probe_payload(duration=7200.0, width=1080, height=1920)
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        with patch("app.services.media_quality.get_ffprobe_binary", return_value="ffprobe"), \
             patch("subprocess.run", return_value=mock_proc):
            res = media_quality.evaluate_final_media_quality(video_path=valid_file, required=True)
            self.assertEqual(res["status"], "PASS")
            self.assertEqual(res["metrics"]["duration"], 7200.0)

    def test_44_paths_with_spaces_handled_safely(self):
        """44. Caminhos contendo espaços são passados seguramente como lista de argumentos sem shell=True."""
        space_file = make_dummy_media_file(self.tmp_dir, "final video with spaces.mp4", size_bytes=15000)
        payload = make_valid_probe_payload(duration=30.0, width=1080, height=1920)
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        with patch("app.services.media_quality.get_ffprobe_binary", return_value="ffprobe"), \
             patch("subprocess.run", return_value=mock_proc) as mock_sub:
            res = media_quality.evaluate_final_media_quality(video_path=space_file, required=True)
            self.assertEqual(res["status"], "PASS")
            call_args = mock_sub.call_args[0][0]
            self.assertEqual(call_args[-1], space_file)
            self.assertFalse(mock_sub.call_args[1].get("shell", False))


if __name__ == "__main__":
    unittest.main()
