"""
test/services/test_ffmpeg_bgm_amix_normalization.py
===================================================
Testes para validação da correção de normalização do amix e proteção de pico
com alimiter no mixer FFmpeg de voz + BGM (_mix_audio_ffmpeg).

Garante:
1. Sintaxe do filtro contém 'normalize=0' e 'alimiter=limit=0.95'
2. Preservação de voice_volume=1.0 e bgm_volume=0.20 aplicados exatamente uma vez
3. Teste AUDIO-ONLY real via FFmpeg local medindo com volumedetect:
   - Output válido
   - Sem queda artificial de ~6 dB na voz
   - Sem clipping
   - Pico respeitando o teto do limiter (<= ~-0.4 dBFS)
"""

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from app.services import ambient_bgm, video
from app.utils import utils


class TestFFmpegBgmAmixNormalization(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_amix_norm_")
        self.voice_file = os.path.join(self.test_dir, "voice.wav")
        self.bgm_file = os.path.join(self.test_dir, "bgm.wav")
        self.output_audio = os.path.join(self.test_dir, "mixed.m4a")

        with open(self.voice_file, "wb") as f:
            f.write(b"\x00" * 1024)
        with open(self.bgm_file, "wb") as f:
            f.write(b"\x00" * 1024)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # =========================================================================
    # 1. Teste de sintaxe e flags do filtro FFmpeg
    # =========================================================================
    def test_filter_syntax_normalize_zero_and_alimiter(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            # Simula que o arquivo de saída existe para passar o check de retorno
            with open(self.output_audio, "wb") as f:
                f.write(b"dummy")

            ok = video._mix_audio_ffmpeg(
                voice_file=self.voice_file,
                bgm_file=self.bgm_file,
                output_audio_file=self.output_audio,
                target_duration=8.0,
                voice_volume=1.0,
                bgm_volume=0.20,
            )

            self.assertTrue(ok)
            self.assertTrue(mock_run.called)
            cmd = mock_run.call_args[0][0]

            self.assertIn("-filter_complex", cmd)
            filter_idx = cmd.index("-filter_complex") + 1
            filter_str = cmd[filter_idx]

            # Requisitos essenciais:
            # - normalize=0 no amix
            self.assertIn("normalize=0", filter_str)
            # - alimiter=limit=0.95 após a soma
            self.assertIn("alimiter=limit=0.95", filter_str)
            # - duration=first e dropout_transition=0 preservados
            self.assertIn("duration=first", filter_str)
            self.assertIn("dropout_transition=0", filter_str)
            # - volumes canônicos preservados e aplicados uma vez
            self.assertIn("volume=1.00", filter_str)
            self.assertIn("volume=0.20", filter_str)
            self.assertIn("[aout]", filter_str)

    # =========================================================================
    # 2. Teste AUDIO-ONLY real via FFmpeg local e volumedetect
    # =========================================================================
    def test_audio_only_local_mix_levels_no_artificial_voice_drop(self):
        ffmpeg_bin = utils.get_ffmpeg_binary()
        if not ffmpeg_bin or not os.path.exists(ffmpeg_bin):
            self.skipTest("Binário do FFmpeg não encontrado para teste de áudio")

        real_voice = os.path.join(self.test_dir, "real_voice.wav")
        real_bgm = os.path.join(self.test_dir, "real_bgm.wav")
        real_output_new = os.path.join(self.test_dir, "real_output_new.m4a")
        real_output_old = os.path.join(self.test_dir, "real_output_old.m4a")

        # 1. Gerar voz sintética de 8 segundos (tom puro a -10 dBFS)
        subprocess.run(
            [
                ffmpeg_bin, "-y",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
                "-filter:a", "volume=-10dB",
                "-c:a", "pcm_s16le", real_voice,
            ],
            capture_output=True,
            check=True,
        )

        # 2. Gerar ambient BGM procedural local de 8 segundos
        ambient_bgm.generate_ambient_bgm(
            output_path=real_bgm,
            duration=8.0,
            mood="neutral",
        )
        self.assertTrue(os.path.exists(real_bgm))

        def _measure_levels(audio_path: str):
            res = subprocess.run(
                [ffmpeg_bin, "-i", audio_path, "-filter:a", "volumedetect", "-f", "null", "-"],
                capture_output=True,
                text=True,
            )
            mean_match = re.search(r"mean_volume:\s*([-\d.]+)\s*dB", res.stderr)
            max_match = re.search(r"max_volume:\s*([-\d.]+)\s*dB", res.stderr)
            self.assertIsNotNone(mean_match, f"volumedetect falhou: {res.stderr}")
            self.assertIsNotNone(max_match, f"volumedetect falhou: {res.stderr}")
            return float(mean_match.group(1)), float(max_match.group(1))

        voice_mean, voice_max = _measure_levels(real_voice)

        # 3. Mixar usando o novo _mix_audio_ffmpeg (normalize=0, alimiter=limit=0.95)
        ok = video._mix_audio_ffmpeg(
            voice_file=real_voice,
            bgm_file=real_bgm,
            output_audio_file=real_output_new,
            target_duration=8.0,
            voice_volume=1.0,
            bgm_volume=0.20,
        )
        self.assertTrue(ok)
        self.assertTrue(os.path.isfile(real_output_new))
        self.assertGreater(os.path.getsize(real_output_new), 0)

        new_mean, new_max = _measure_levels(real_output_new)

        # 4. Mixar usando o filtro antigo (amix com normalize=1 implícito)
        filter_old = (
            "[0:a]volume=1.00[v];"
            "[1:a]volume=0.20,afade=t=out:st=5.00:d=3[b];"
            "[v][b]amix=inputs=2:duration=first:dropout_transition=0[aout]"
        )
        subprocess.run(
            [
                ffmpeg_bin, "-y",
                "-i", real_voice,
                "-stream_loop", "-1",
                "-i", real_bgm,
                "-filter_complex", filter_old,
                "-map", "[aout]",
                "-c:a", "aac",
                "-b:a", "192k",
                "-t", "8.000",
                real_output_old,
            ],
            capture_output=True,
            check=True,
        )
        old_mean, old_max = _measure_levels(real_output_old)

        # Critério principal: A nova mixagem NÃO pode ter a queda artificial de ~6 dB
        # O ganho do novo mixer em relação ao antigo deve ser de aproximadamente ~6 dB
        gain_db = new_mean - old_mean
        self.assertGreater(
            gain_db,
            5.0,
            f"O ganho do novo mixer ({gain_db:.2f} dB) deve recuperar a atenuação indevida de ~6 dB",
        )

        # Proteção contra clipping: o pico deve respeitar o teto do limiter (0.95 amplitude ~ -0.44 dBFS)
        self.assertLessEqual(new_max, 0.0, "O áudio mixado não pode sofrer clipping (> 0 dBFS)")
        self.assertLessEqual(new_max, -0.3, "O pico deve estar limitado pelo alimiter=limit=0.95")


if __name__ == "__main__":
    unittest.main()
