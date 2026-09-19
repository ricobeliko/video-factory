"""
Test Suite para Clip Transcription Service (Fase V11-B).

Cobre os requisitos 1 a 30:
1. schema transcript idempotente
2. schema transcript segments idempotente
3. READY source aceita
4. INVALID source rejeita
5. inactive source rejeita quando apropriado
6. sem autorização rejeita
7. SECONDARY bloqueado
8. PRIMARY aceita
9. source sem áudio retorna NO_AUDIO
10. audio extraction usa storage controlado
11. audio mono 16k config
12. subprocess shell=False
13. timeout tratado
14. ffmpeg error tratado
15. source não alterada em failure
16. transcript FAILED registrado
17. successful transcript COMPLETED
18. full_text persistido
19. language persistida
20. provider persistido
21. model persistido
22. transcript segments ordenados
23. timestamps válidos
24. confidence nullable
25. PROCESSING duplicado bloqueado
26. completed identical reused
27. force cria histórico novo
28. nenhuma transcrição apagada
29. profile preservado
30. UI read não carrega engine
"""
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from app.services import (
    clip_mode,
    clip_transcription,
    operator_console,
    profile_manager,
)
from app.utils import utils


class TestClipTranscription(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_video_factory.db")

        # Configura instância como PRIMARY
        operator_console.reset_instance_for_testing()
        with operator_console._instance_state_lock:
            operator_console._current_role = operator_console.ROLE_PRIMARY

        # Inicializa tabelas
        profile_manager.init_profile_db(db_path=self.db_path)
        profile_manager.ensure_default_profile(db_path=self.db_path)
        clip_mode.init_clip_db(db_path=self.db_path)
        clip_transcription.init_clip_transcription_db(db_path=self.db_path)

        # Registra mock provider padrão
        self.mock_provider = clip_transcription.MockTranscriptProvider()
        clip_transcription.register_transcript_provider("mock", self.mock_provider)

        # Cria arquivo de vídeo de teste
        self.fake_video_path = os.path.join(self.tmp_dir.name, "sample_clip.mp4")
        with open(self.fake_video_path, "wb") as f:
            f.write(b"FAKE_MP4_VIDEO_FOR_TRANSCRIPTION_TESTS_1234567890")

        self.default_probe_metadata = {
            "duration_seconds": 90.0,
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
            "video_codec": "h264",
            "audio_codec": "aac",
            "has_audio": True,
        }

    def tearDown(self):
        operator_console.reset_instance_for_testing()
        self.tmp_dir.cleanup()

    def _import_ready_source(self, has_audio=True, duration=90.0, profile_id="default"):
        probe_meta = dict(self.default_probe_metadata)
        probe_meta["has_audio"] = has_audio
        probe_meta["duration_seconds"] = duration

        with patch("app.services.clip_mode.probe_video_metadata", return_value=probe_meta):
            res = clip_mode.import_clip_source(
                file_path=self.fake_video_path,
                source_origin="owned",
                authorization_confirmed=True,
                authorization_note="Autorizado para testes V11-B",
                profile_id=profile_id,
                db_path=self.db_path,
            )
            return res["source_id"]

    # 1. schema transcript idempotente
    def test_01_schema_transcript_idempotent(self):
        clip_transcription.init_clip_transcription_db(db_path=self.db_path)
        clip_transcription.init_clip_transcription_db(db_path=self.db_path)

        with clip_mode.get_connection(self.db_path) as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='clip_transcripts';")
            self.assertIsNotNone(cursor.fetchone())

            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_clip_transcripts_source';")
            self.assertIsNotNone(cursor.fetchone())

    # 2. schema transcript segments idempotente
    def test_02_schema_transcript_segments_idempotent(self):
        clip_transcription.init_clip_transcription_db(db_path=self.db_path)
        clip_transcription.init_clip_transcription_db(db_path=self.db_path)

        with clip_mode.get_connection(self.db_path) as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='clip_transcript_segments';")
            self.assertIsNotNone(cursor.fetchone())

            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_clip_tsegments_transcript';")
            self.assertIsNotNone(cursor.fetchone())

    # 3. READY source aceita
    @patch("app.services.clip_transcription.extract_clip_source_audio")
    def test_03_ready_source_accepted(self, mock_extract):
        source_id = self._import_ready_source(has_audio=True)
        dummy_wav = os.path.join(self.tmp_dir.name, "audio.wav")
        with open(dummy_wav, "wb") as f:
            f.write(b"RIFF_WAV_DUMMY_DATA")
        mock_extract.return_value = dummy_wav

        res = clip_transcription.transcribe_clip_source(
            source_id=source_id,
            provider_name="mock",
            db_path=self.db_path,
        )
        self.assertEqual(res["status"], "completed")
        self.assertIn("transcript_id", res)
        self.assertEqual(res["transcript"]["status"], "COMPLETED")

    # 4. INVALID source rejeita
    def test_04_invalid_source_rejected(self):
        source_id = self._import_ready_source()
        with clip_mode.get_connection(self.db_path) as conn:
            conn.execute("UPDATE clip_sources SET status = 'INVALID' WHERE id = ?", (source_id,))

        with self.assertRaises(clip_mode.ClipValidationError) as ctx:
            clip_transcription.transcribe_clip_source(source_id=source_id, db_path=self.db_path)
        self.assertIn("READY", str(ctx.exception))

    # 5. inactive source rejeita quando apropriado
    def test_05_inactive_source_rejected(self):
        source_id = self._import_ready_source()
        clip_mode.deactivate_clip_source(source_id, db_path=self.db_path)

        with self.assertRaises(clip_mode.ClipValidationError) as ctx:
            clip_transcription.transcribe_clip_source(source_id=source_id, db_path=self.db_path)
        self.assertIn("READY", str(ctx.exception))

    # 6. sem autorização rejeita
    def test_06_unauthorized_source_rejected(self):
        source_id = self._import_ready_source()
        with clip_mode.get_connection(self.db_path) as conn:
            conn.execute("UPDATE clip_sources SET authorization_confirmed = 0 WHERE id = ?", (source_id,))

        with self.assertRaises(clip_mode.ClipAuthorizationError):
            clip_transcription.transcribe_clip_source(source_id=source_id, db_path=self.db_path)

    # 7. SECONDARY bloqueado
    def test_07_secondary_blocked(self):
        source_id = self._import_ready_source()
        with patch("app.services.operator_console.is_primary_instance", return_value=False):
            with self.assertRaises(PermissionError):
                clip_transcription.transcribe_clip_source(source_id=source_id, db_path=self.db_path)

    # 8. PRIMARY aceita
    @patch("app.services.clip_transcription.extract_clip_source_audio")
    def test_08_primary_accepted(self, mock_extract):
        source_id = self._import_ready_source()
        dummy_wav = os.path.join(self.tmp_dir.name, "audio.wav")
        with open(dummy_wav, "wb") as f:
            f.write(b"RIFF_WAV_DUMMY_DATA")
        mock_extract.return_value = dummy_wav

        with operator_console._instance_state_lock:
            operator_console._current_role = operator_console.ROLE_PRIMARY

        res = clip_transcription.transcribe_clip_source(source_id=source_id, provider_name="mock", db_path=self.db_path)
        self.assertEqual(res["status"], "completed")

    # 9. source sem áudio retorna NO_AUDIO
    def test_09_source_without_audio_returns_no_audio(self):
        source_id = self._import_ready_source(has_audio=False)

        with self.assertRaises(clip_mode.ClipModeError) as ctx:
            clip_transcription.transcribe_clip_source(source_id=source_id, db_path=self.db_path)
        self.assertEqual(str(ctx.exception), "NO_AUDIO")

        # Verifica que o status da fonte permanece READY
        src = clip_mode.get_clip_source(source_id, db_path=self.db_path)
        self.assertEqual(src["status"], clip_mode.SOURCE_STATUS_READY)

    # 10. audio extraction usa storage controlado
    @patch("subprocess.run")
    def test_10_audio_extraction_uses_controlled_storage(self, mock_run):
        source_id = self._import_ready_source(has_audio=True)
        src = clip_mode.get_clip_source(source_id, db_path=self.db_path)

        def side_effect(cmd, **kwargs):
            audio_out = cmd[-1]
            os.makedirs(os.path.dirname(audio_out), exist_ok=True)
            with open(audio_out, "wb") as f:
                f.write(b"RIFF_PCM_16K_WAV_DATA")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        mock_run.side_effect = side_effect

        audio_path = clip_transcription.extract_clip_source_audio(source_id, db_path=self.db_path)
        self.assertTrue(os.path.isfile(audio_path))
        # Verifica se está estritamente contido no diretório da source
        expected_dir = os.path.normpath(os.path.join(utils.root_dir(), "storage", "clip_sources", source_id, "transcription"))
        self.assertEqual(os.path.normpath(os.path.dirname(audio_path)), expected_dir)
        # Verifica que o vídeo original continua intacto
        self.assertTrue(os.path.isfile(src["stored_path"]))

    # 11. audio mono 16k config
    @patch("subprocess.run")
    def test_11_audio_mono_16k_config(self, mock_run):
        source_id = self._import_ready_source(has_audio=True)

        def side_effect(cmd, **kwargs):
            audio_out = cmd[-1]
            os.makedirs(os.path.dirname(audio_out), exist_ok=True)
            with open(audio_out, "wb") as f:
                f.write(b"WAV_DATA")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        mock_run.side_effect = side_effect

        clip_transcription.extract_clip_source_audio(source_id, force=True, db_path=self.db_path)
        self.assertTrue(mock_run.called)
        cmd = mock_run.call_args[0][0]
        self.assertIn("-ac", cmd)
        idx_ac = cmd.index("-ac")
        self.assertEqual(cmd[idx_ac + 1], "1")
        self.assertIn("-ar", cmd)
        idx_ar = cmd.index("-ar")
        self.assertEqual(cmd[idx_ar + 1], "16000")
        self.assertIn("-c:a", cmd)
        idx_ca = cmd.index("-c:a")
        self.assertEqual(cmd[idx_ca + 1], "pcm_s16le")

    # 12. subprocess shell=False
    @patch("subprocess.run")
    def test_12_subprocess_shell_false(self, mock_run):
        source_id = self._import_ready_source(has_audio=True)

        def side_effect(cmd, **kwargs):
            audio_out = cmd[-1]
            os.makedirs(os.path.dirname(audio_out), exist_ok=True)
            with open(audio_out, "wb") as f:
                f.write(b"WAV_DATA")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        mock_run.side_effect = side_effect

        clip_transcription.extract_clip_source_audio(source_id, force=True, db_path=self.db_path)
        kwargs = mock_run.call_args[1]
        self.assertFalse(kwargs.get("shell", False))

    # 13. timeout tratado
    @patch("subprocess.run")
    def test_13_timeout_handled(self, mock_run):
        source_id = self._import_ready_source(has_audio=True)
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=120)

        with self.assertRaises(clip_mode.ClipValidationError) as ctx:
            clip_transcription.extract_clip_source_audio(source_id, force=True, db_path=self.db_path)
        self.assertIn("Timeout", str(ctx.exception))

    # 14. ffmpeg error tratado
    @patch("subprocess.run")
    def test_14_ffmpeg_error_handled(self, mock_run):
        source_id = self._import_ready_source(has_audio=True)
        mock_run.return_value = subprocess.CompletedProcess(
            args=["ffmpeg"],
            returncode=1,
            stdout="",
            stderr="Invalid audio stream or codec error",
        )

        with self.assertRaises(clip_mode.ClipValidationError) as ctx:
            clip_transcription.extract_clip_source_audio(source_id, force=True, db_path=self.db_path)
        self.assertIn("Falha ao extrair áudio com FFmpeg", str(ctx.exception))

    # 15. source não alterada em failure
    @patch("app.services.clip_transcription.extract_clip_source_audio")
    def test_15_source_not_altered_in_failure(self, mock_extract):
        source_id = self._import_ready_source(has_audio=True)
        failing_provider = clip_transcription.MockTranscriptProvider(should_fail=True)
        clip_transcription.register_transcript_provider("failing", failing_provider)

        dummy_wav = os.path.join(self.tmp_dir.name, "audio.wav")
        with open(dummy_wav, "wb") as f:
            f.write(b"RIFF_WAV")
        mock_extract.return_value = dummy_wav

        with self.assertRaises(clip_mode.ClipModeError):
            clip_transcription.transcribe_clip_source(
                source_id=source_id,
                provider_name="failing",
                db_path=self.db_path,
            )

        src = clip_mode.get_clip_source(source_id, db_path=self.db_path)
        self.assertEqual(src["status"], clip_mode.SOURCE_STATUS_READY)

    # 16. transcript FAILED registrado
    @patch("app.services.clip_transcription.extract_clip_source_audio")
    def test_16_transcript_failed_registered(self, mock_extract):
        source_id = self._import_ready_source(has_audio=True)
        failing_provider = clip_transcription.MockTranscriptProvider(should_fail=True)
        clip_transcription.register_transcript_provider("failing", failing_provider)

        dummy_wav = os.path.join(self.tmp_dir.name, "audio.wav")
        with open(dummy_wav, "wb") as f:
            f.write(b"RIFF_WAV")
        mock_extract.return_value = dummy_wav

        with self.assertRaises(clip_mode.ClipModeError):
            clip_transcription.transcribe_clip_source(
                source_id=source_id,
                provider_name="failing",
                db_path=self.db_path,
            )

        with clip_mode.get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM clip_transcripts WHERE source_id = ? ORDER BY created_at DESC LIMIT 1;",
                (source_id,),
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["status"], "FAILED")
            self.assertEqual(row["error_code"], "TRANSCRIPTION_ERROR")
            self.assertIn("Mock transcript provider failure", row["error_message"])

    # 17. successful transcript COMPLETED
    @patch("app.services.clip_transcription.extract_clip_source_audio")
    def test_17_successful_transcript_completed(self, mock_extract):
        source_id = self._import_ready_source(has_audio=True)
        dummy_wav = os.path.join(self.tmp_dir.name, "audio.wav")
        with open(dummy_wav, "wb") as f:
            f.write(b"RIFF_WAV")
        mock_extract.return_value = dummy_wav

        res = clip_transcription.transcribe_clip_source(source_id=source_id, provider_name="mock", db_path=self.db_path)
        tr = res["transcript"]
        self.assertEqual(tr["status"], "COMPLETED")
        self.assertIsNotNone(tr["completed_at"])
        self.assertIsNotNone(tr["started_at"])

    # 18. full_text persistido
    @patch("app.services.clip_transcription.extract_clip_source_audio")
    def test_18_full_text_persisted(self, mock_extract):
        source_id = self._import_ready_source(has_audio=True)
        dummy_wav = os.path.join(self.tmp_dir.name, "audio.wav")
        with open(dummy_wav, "wb") as f:
            f.write(b"RIFF_WAV")
        mock_extract.return_value = dummy_wav

        res = clip_transcription.transcribe_clip_source(source_id=source_id, provider_name="mock", db_path=self.db_path)
        tr = res["transcript"]
        self.assertIn("inteligência artificial", tr["full_text"])

    # 19. language persistida
    @patch("app.services.clip_transcription.extract_clip_source_audio")
    def test_19_language_persisted(self, mock_extract):
        source_id = self._import_ready_source(has_audio=True)
        dummy_wav = os.path.join(self.tmp_dir.name, "audio.wav")
        with open(dummy_wav, "wb") as f:
            f.write(b"RIFF_WAV")
        mock_extract.return_value = dummy_wav

        res = clip_transcription.transcribe_clip_source(
            source_id=source_id,
            language="pt",
            provider_name="mock",
            db_path=self.db_path,
        )
        self.assertEqual(res["transcript"]["language"], "pt")

    # 20. provider persistido
    @patch("app.services.clip_transcription.extract_clip_source_audio")
    def test_20_provider_persisted(self, mock_extract):
        source_id = self._import_ready_source(has_audio=True)
        dummy_wav = os.path.join(self.tmp_dir.name, "audio.wav")
        with open(dummy_wav, "wb") as f:
            f.write(b"RIFF_WAV")
        mock_extract.return_value = dummy_wav

        res = clip_transcription.transcribe_clip_source(source_id=source_id, provider_name="mock", db_path=self.db_path)
        self.assertEqual(res["transcript"]["provider"], "mock")

    # 21. model persistido
    @patch("app.services.clip_transcription.extract_clip_source_audio")
    def test_21_model_persisted(self, mock_extract):
        source_id = self._import_ready_source(has_audio=True)
        dummy_wav = os.path.join(self.tmp_dir.name, "audio.wav")
        with open(dummy_wav, "wb") as f:
            f.write(b"RIFF_WAV")
        mock_extract.return_value = dummy_wav

        res = clip_transcription.transcribe_clip_source(
            source_id=source_id,
            model_name="tiny",
            provider_name="mock",
            db_path=self.db_path,
        )
        self.assertEqual(res["transcript"]["model_name"], "tiny")

    # 22. transcript segments ordenados
    @patch("app.services.clip_transcription.extract_clip_source_audio")
    def test_22_transcript_segments_ordered(self, mock_extract):
        source_id = self._import_ready_source(has_audio=True)
        dummy_wav = os.path.join(self.tmp_dir.name, "audio.wav")
        with open(dummy_wav, "wb") as f:
            f.write(b"RIFF_WAV")
        mock_extract.return_value = dummy_wav

        res = clip_transcription.transcribe_clip_source(source_id=source_id, provider_name="mock", db_path=self.db_path)
        tid = res["transcript_id"]

        segs = clip_transcription.list_clip_transcript_segments(tid, db_path=self.db_path)
        self.assertGreaterEqual(len(segs), 2)
        for i in range(len(segs) - 1):
            self.assertLess(segs[i]["sequence"], segs[i + 1]["sequence"])
            self.assertLessEqual(segs[i]["start_seconds"], segs[i + 1]["start_seconds"])

    # 23. timestamps válidos
    @patch("app.services.clip_transcription.extract_clip_source_audio")
    def test_23_timestamps_valid(self, mock_extract):
        source_id = self._import_ready_source(has_audio=True)
        dummy_wav = os.path.join(self.tmp_dir.name, "audio.wav")
        with open(dummy_wav, "wb") as f:
            f.write(b"RIFF_WAV")
        mock_extract.return_value = dummy_wav

        res = clip_transcription.transcribe_clip_source(source_id=source_id, provider_name="mock", db_path=self.db_path)
        segs = clip_transcription.list_clip_transcript_segments(res["transcript_id"], db_path=self.db_path)
        for seg in segs:
            self.assertGreaterEqual(seg["start_seconds"], 0.0)
            self.assertGreater(seg["end_seconds"], seg["start_seconds"])

    # 24. confidence nullable
    @patch("app.services.clip_transcription.extract_clip_source_audio")
    def test_24_confidence_nullable(self, mock_extract):
        source_id = self._import_ready_source(has_audio=True)
        custom_provider = clip_transcription.MockTranscriptProvider(
            mock_segments=[{
                "sequence": 0,
                "start_seconds": 0.0,
                "end_seconds": 10.0,
                "text": "Segmento sem confiança.",
                "confidence": None,
            }]
        )
        clip_transcription.register_transcript_provider("no_conf", custom_provider)

        dummy_wav = os.path.join(self.tmp_dir.name, "audio.wav")
        with open(dummy_wav, "wb") as f:
            f.write(b"RIFF_WAV")
        mock_extract.return_value = dummy_wav

        res = clip_transcription.transcribe_clip_source(
            source_id=source_id,
            provider_name="no_conf",
            db_path=self.db_path,
        )
        segs = clip_transcription.list_clip_transcript_segments(res["transcript_id"], db_path=self.db_path)
        self.assertEqual(len(segs), 1)
        self.assertIsNone(segs[0]["confidence"])

    # 25. PROCESSING duplicado bloqueado
    def test_25_duplicate_processing_blocked(self):
        source_id = self._import_ready_source(has_audio=True)
        # Insere manualmente um registro PROCESSING
        with clip_mode.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO clip_transcripts (
                    id, source_id, profile_id, provider, model_name, language,
                    status, full_text, started_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    "tr_in_proc",
                    source_id,
                    "default",
                    "mock",
                    "small",
                    "auto",
                    clip_transcription.TRANSCRIPT_STATUS_PROCESSING,
                    None,
                    "2026-09-18T00:00:00Z",
                    "2026-09-18T00:00:00Z",
                    "2026-09-18T00:00:00Z",
                ),
            )

        with self.assertRaises(clip_mode.ClipModeError) as ctx:
            clip_transcription.transcribe_clip_source(source_id=source_id, provider_name="mock", db_path=self.db_path)
        self.assertIn("DUPLICATE_PROCESSING", str(ctx.exception))

    # 26. completed identical reused
    @patch("app.services.clip_transcription.extract_clip_source_audio")
    def test_26_completed_identical_reused(self, mock_extract):
        source_id = self._import_ready_source(has_audio=True)
        dummy_wav = os.path.join(self.tmp_dir.name, "audio.wav")
        with open(dummy_wav, "wb") as f:
            f.write(b"RIFF_WAV")
        mock_extract.return_value = dummy_wav

        res1 = clip_transcription.transcribe_clip_source(
            source_id=source_id,
            provider_name="mock",
            model_name="small",
            language="auto",
            db_path=self.db_path,
        )
        self.assertEqual(res1["status"], "completed")

        res2 = clip_transcription.transcribe_clip_source(
            source_id=source_id,
            provider_name="mock",
            model_name="small",
            language="auto",
            force=False,
            db_path=self.db_path,
        )
        self.assertEqual(res2["status"], "reused")
        self.assertEqual(res2["transcript_id"], res1["transcript_id"])

    # 27. force cria histórico novo
    @patch("app.services.clip_transcription.extract_clip_source_audio")
    def test_27_force_creates_new_history(self, mock_extract):
        source_id = self._import_ready_source(has_audio=True)
        dummy_wav = os.path.join(self.tmp_dir.name, "audio.wav")
        with open(dummy_wav, "wb") as f:
            f.write(b"RIFF_WAV")
        mock_extract.return_value = dummy_wav

        res1 = clip_transcription.transcribe_clip_source(
            source_id=source_id,
            provider_name="mock",
            force=False,
            db_path=self.db_path,
        )
        res2 = clip_transcription.transcribe_clip_source(
            source_id=source_id,
            provider_name="mock",
            force=True,
            db_path=self.db_path,
        )
        self.assertEqual(res2["status"], "completed")
        self.assertNotEqual(res1["transcript_id"], res2["transcript_id"])

    # 28. nenhuma transcrição apagada
    @patch("app.services.clip_transcription.extract_clip_source_audio")
    def test_28_no_transcript_deleted(self, mock_extract):
        source_id = self._import_ready_source(has_audio=True)
        dummy_wav = os.path.join(self.tmp_dir.name, "audio.wav")
        with open(dummy_wav, "wb") as f:
            f.write(b"RIFF_WAV")
        mock_extract.return_value = dummy_wav

        clip_transcription.transcribe_clip_source(source_id=source_id, provider_name="mock", force=False, db_path=self.db_path)
        clip_transcription.transcribe_clip_source(source_id=source_id, provider_name="mock", force=True, db_path=self.db_path)

        with clip_mode.get_connection(self.db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM clip_transcripts WHERE source_id = ?", (source_id,)).fetchone()[0]
            self.assertEqual(count, 2)

    # 29. profile preservado
    @patch("app.services.clip_transcription.extract_clip_source_audio")
    def test_29_profile_preserved(self, mock_extract):
        profile_manager.create_profile("Tech Channel", profile_id="channel_tech", db_path=self.db_path)
        source_id = self._import_ready_source(has_audio=True, profile_id="channel_tech")

        dummy_wav = os.path.join(self.tmp_dir.name, "audio.wav")
        with open(dummy_wav, "wb") as f:
            f.write(b"RIFF_WAV")
        mock_extract.return_value = dummy_wav

        res = clip_transcription.transcribe_clip_source(source_id=source_id, provider_name="mock", db_path=self.db_path)
        self.assertEqual(res["transcript"]["profile_id"], "channel_tech")

    # 30. UI read não carrega engine
    @patch("app.services.clip_transcription.extract_clip_source_audio")
    def test_30_ui_read_does_not_load_engine(self, mock_extract):
        source_id = self._import_ready_source(has_audio=True)
        dummy_wav = os.path.join(self.tmp_dir.name, "audio.wav")
        with open(dummy_wav, "wb") as f:
            f.write(b"RIFF_WAV")
        mock_extract.return_value = dummy_wav

        res = clip_transcription.transcribe_clip_source(source_id=source_id, provider_name="mock", db_path=self.db_path)
        tid = res["transcript_id"]

        # Agora testa as leituras de UI: nenhuma deve chamar extract_clip_source_audio ou transcribe do mock
        mock_extract.reset_mock()
        initial_count = self.mock_provider.call_count

        t1 = clip_transcription.get_clip_transcript(tid, db_path=self.db_path)
        self.assertIsNotNone(t1)

        t2 = clip_transcription.get_latest_successful_transcript(source_id, db_path=self.db_path)
        self.assertIsNotNone(t2)

        segs = clip_transcription.list_clip_transcript_segments(tid, db_path=self.db_path)
        self.assertGreater(len(segs), 0)

        # Nenhuma operação pesada executada
        mock_extract.assert_not_called()
        self.assertEqual(self.mock_provider.call_count, initial_count)

    # 31. duas tentativas sobre mesma source não criam dois PROCESSING
    @patch("app.services.clip_transcription.extract_clip_source_audio")
    def test_31_concurrent_threads_cannot_create_two_processing(self, mock_extract):
        source_id = self._import_ready_source(has_audio=True)
        dummy_wav = os.path.join(self.tmp_dir.name, "audio.wav")
        with open(dummy_wav, "wb") as f:
            f.write(b"RIFF_WAV")
        mock_extract.return_value = dummy_wav

        started_event = threading.Event()
        finish_event = threading.Event()

        class BlockingProvider(clip_transcription.TranscriptProvider):
            @property
            def name(self):
                return "blocking"
            def status(self):
                return "AVAILABLE"
            def transcribe(self, audio_path, language="auto", model_name="small"):
                started_event.set()
                finish_event.wait(timeout=5.0)
                return "Texto", "pt", []

        clip_transcription.register_transcript_provider("blocking", BlockingProvider())

        results = []
        errors = []

        def worker1():
            try:
                res = clip_transcription.transcribe_clip_source(
                    source_id=source_id,
                    provider_name="blocking",
                    force=True,
                    db_path=self.db_path,
                )
                results.append(res)
            except Exception as e:
                errors.append(e)

        def worker2():
            # Aguarda worker1 estar ativamente executando dentro de PROCESSING
            started_event.wait(timeout=5.0)
            try:
                res = clip_transcription.transcribe_clip_source(
                    source_id=source_id,
                    provider_name="mock",
                    force=True,
                    db_path=self.db_path,
                )
                results.append(res)
            except Exception as e:
                errors.append(e)
            finally:
                finish_event.set()

        t1 = threading.Thread(target=worker1)
        t2 = threading.Thread(target=worker2)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        self.assertIn("DUPLICATE_PROCESSING", str(errors[0]))

    # 32. force=True não bypassa PROCESSING ativo
    def test_32_force_true_cannot_bypass_active_processing(self):
        source_id = self._import_ready_source(has_audio=True)
        with clip_mode.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO clip_transcripts (
                    id, source_id, profile_id, provider, model_name, language,
                    status, full_text, started_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    "tr_active_proc",
                    source_id,
                    "default",
                    "mock",
                    "small",
                    "auto",
                    clip_transcription.TRANSCRIPT_STATUS_PROCESSING,
                    None,
                    "2026-09-18T00:00:00Z",
                    "2026-09-18T00:00:00Z",
                    "2026-09-18T00:00:00Z",
                ),
            )

        with self.assertRaises(clip_mode.ClipModeError) as ctx:
            clip_transcription.transcribe_clip_source(
                source_id=source_id,
                provider_name="mock",
                force=True,
                db_path=self.db_path,
            )
        self.assertIn("DUPLICATE_PROCESSING", str(ctx.exception))

    # 33. transação é liberada antes de FFmpeg/STT pesado
    @patch("app.services.clip_transcription.extract_clip_source_audio")
    def test_33_db_transaction_released_before_heavy_stt(self, mock_extract):
        source_id = self._import_ready_source(has_audio=True)
        dummy_wav = os.path.join(self.tmp_dir.name, "audio.wav")
        with open(dummy_wav, "wb") as f:
            f.write(b"RIFF_WAV")
        mock_extract.return_value = dummy_wav

        db_accessible = []

        class SlowProvider(clip_transcription.TranscriptProvider):
            @property
            def name(self):
                return "slow"
            def status(self):
                return "AVAILABLE"
            def transcribe(self, audio_path, language="auto", model_name="small"):
                with clip_mode.get_connection(self_db_path) as conn:
                    # Se estivesse travado numa transação longa, daria erro
                    row = conn.execute("SELECT status FROM clip_transcripts WHERE source_id = ?", (source_id,)).fetchone()
                    db_accessible.append(row["status"] == clip_transcription.TRANSCRIPT_STATUS_PROCESSING)
                return "Texto transcrito", "pt", []

        self_db_path = self.db_path
        clip_transcription.register_transcript_provider("slow", SlowProvider())

        res = clip_transcription.transcribe_clip_source(
            source_id=source_id,
            provider_name="slow",
            db_path=self.db_path,
        )
        self.assertEqual(res["status"], "completed")
        self.assertTrue(db_accessible[0])

    # 34. FFmpeg escreve em temp, não diretamente em audio.wav
    @patch("subprocess.run")
    def test_34_ffmpeg_writes_to_temp_first(self, mock_run):
        source_id = self._import_ready_source(has_audio=True)

        def side_effect(cmd, **kwargs):
            out_file = cmd[-1]
            self.assertTrue(out_file.endswith(".tmp.wav"))
            self.assertNotIn("audio.wav", os.path.basename(out_file))
            with open(out_file, "wb") as f:
                f.write(b"RIFF_WAV_TEMP")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        mock_run.side_effect = side_effect
        final_audio = clip_transcription.extract_clip_source_audio(source_id, db_path=self.db_path)
        self.assertTrue(final_audio.endswith("audio.wav"))
        self.assertTrue(os.path.isfile(final_audio))

    # 35. sucesso promove temp → audio.wav atomicamente com os.replace
    @patch("subprocess.run")
    def test_35_atomic_promotion_on_success(self, mock_run):
        source_id = self._import_ready_source(has_audio=True)

        def side_effect(cmd, **kwargs):
            out_file = cmd[-1]
            with open(out_file, "wb") as f:
                f.write(b"TEMP_AUDIO_DATA_FOR_PROMOTION")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        mock_run.side_effect = side_effect
        with patch("os.replace", wraps=os.replace) as mock_replace:
            final_audio = clip_transcription.extract_clip_source_audio(source_id, db_path=self.db_path)
            mock_replace.assert_called_once()
            self.assertEqual(mock_replace.call_args[0][1], final_audio)

    # 36. timeout não deixa audio.wav parcial e remove temp
    @patch("subprocess.run")
    def test_36_timeout_cleans_temp_and_leaves_no_partial_audio(self, mock_run):
        source_id = self._import_ready_source(has_audio=True)
        created_temp = []

        def side_effect(cmd, **kwargs):
            temp_f = cmd[-1]
            created_temp.append(temp_f)
            with open(temp_f, "wb") as f:
                f.write(b"PARTIAL_BEFORE_TIMEOUT")
            raise subprocess.TimeoutExpired(cmd, 120)

        mock_run.side_effect = side_effect

        with self.assertRaises(clip_mode.ClipValidationError):
            clip_transcription.extract_clip_source_audio(source_id, force=True, db_path=self.db_path)

        self.assertFalse(os.path.exists(created_temp[0]))
        target_dir = utils.storage_dir(os.path.join("clip_sources", source_id, "transcription"))
        self.assertFalse(os.path.exists(os.path.join(target_dir, "audio.wav")))

    # 37. FFmpeg error não deixa audio.wav parcial e remove temp
    @patch("subprocess.run")
    def test_37_ffmpeg_error_cleans_temp_and_leaves_no_partial_audio(self, mock_run):
        source_id = self._import_ready_source(has_audio=True)
        created_temp = []

        def side_effect(cmd, **kwargs):
            temp_f = cmd[-1]
            created_temp.append(temp_f)
            with open(temp_f, "wb") as f:
                f.write(b"CORRUPT_BYTES")
            return subprocess.CompletedProcess(cmd, 1, "", "FFmpeg exit with error")

        mock_run.side_effect = side_effect

        with self.assertRaises(clip_mode.ClipValidationError):
            clip_transcription.extract_clip_source_audio(source_id, force=True, db_path=self.db_path)

        self.assertFalse(os.path.exists(created_temp[0]))
        target_dir = utils.storage_dir(os.path.join("clip_sources", source_id, "transcription"))
        self.assertFalse(os.path.exists(os.path.join(target_dir, "audio.wav")))

    # 38. FFmpeg error preserva audio.wav válido pré-existente
    @patch("subprocess.run")
    def test_38_ffmpeg_failure_preserves_existing_valid_cache(self, mock_run):
        source_id = self._import_ready_source(has_audio=True)
        target_dir = utils.storage_dir(os.path.join("clip_sources", source_id, "transcription"), create=True)
        final_audio = os.path.join(target_dir, "audio.wav")
        with open(final_audio, "wb") as f:
            f.write(b"VALID_PREVIOUS_AUDIO_CACHE")

        mock_run.return_value = subprocess.CompletedProcess(["ffmpeg"], 1, "", "Decoding failed")

        with self.assertRaises(clip_mode.ClipValidationError):
            clip_transcription.extract_clip_source_audio(source_id, force=True, db_path=self.db_path)

        self.assertTrue(os.path.exists(final_audio))
        with open(final_audio, "rb") as f:
            self.assertEqual(f.read(), b"VALID_PREVIOUS_AUDIO_CACHE")

    # 39. temp vazio é rejeitado e removido
    @patch("subprocess.run")
    def test_39_empty_temp_file_rejected_and_cleaned(self, mock_run):
        source_id = self._import_ready_source(has_audio=True)
        created_temp = []

        def side_effect(cmd, **kwargs):
            temp_f = cmd[-1]
            created_temp.append(temp_f)
            with open(temp_f, "wb") as f:
                pass
            return subprocess.CompletedProcess(cmd, 0, "", "")

        mock_run.side_effect = side_effect

        with self.assertRaises(clip_mode.ClipValidationError) as ctx:
            clip_transcription.extract_clip_source_audio(source_id, force=True, db_path=self.db_path)
        self.assertIn("vazio", str(ctx.exception))
        self.assertFalse(os.path.exists(created_temp[0]))

    # 40. cache vazio não é considerado válido
    @patch("subprocess.run")
    def test_40_empty_cache_not_reused(self, mock_run):
        source_id = self._import_ready_source(has_audio=True)
        target_dir = utils.storage_dir(os.path.join("clip_sources", source_id, "transcription"), create=True)
        final_audio = os.path.join(target_dir, "audio.wav")
        with open(final_audio, "wb") as f:
            pass

        def side_effect(cmd, **kwargs):
            with open(cmd[-1], "wb") as f:
                f.write(b"NEW_NON_EMPTY_AUDIO")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        mock_run.side_effect = side_effect

        res_audio = clip_transcription.extract_clip_source_audio(source_id, force=False, db_path=self.db_path)
        self.assertTrue(mock_run.called)
        self.assertGreater(os.path.getsize(res_audio), 0)

    # 41. cache symlink não é considerado válido
    @patch("subprocess.run")
    def test_41_symlink_cache_not_reused(self, mock_run):
        source_id = self._import_ready_source(has_audio=True)
        target_dir = utils.storage_dir(os.path.join("clip_sources", source_id, "transcription"), create=True)
        final_audio = os.path.join(target_dir, "audio.wav")
        with open(final_audio, "wb") as f:
            f.write(b"DUMMY")

        def side_effect(cmd, **kwargs):
            with open(cmd[-1], "wb") as f:
                f.write(b"REAL_AUDIO")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        mock_run.side_effect = side_effect

        orig_islink = os.path.islink
        def selective_islink(path):
            if str(path).endswith("audio.wav") and not str(path).endswith(".tmp.wav"):
                return True
            return orig_islink(path)

        with patch("os.path.islink", side_effect=selective_islink):
            clip_transcription.extract_clip_source_audio(source_id, force=False, db_path=self.db_path)
        self.assertTrue(mock_run.called)

    # 42. paths temporários permanecem dentro do diretório da source
    @patch("subprocess.run")
    def test_42_temp_path_strictly_within_source_directory(self, mock_run):
        source_id = self._import_ready_source(has_audio=True)
        expected_dir = os.path.normpath(os.path.join(utils.root_dir(), "storage", "clip_sources", source_id, "transcription"))

        def side_effect(cmd, **kwargs):
            out_file = cmd[-1]
            norm_out_dir = os.path.normpath(os.path.dirname(out_file))
            self.assertEqual(norm_out_dir, expected_dir)
            with open(out_file, "wb") as f:
                f.write(b"DATA")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        mock_run.side_effect = side_effect
        clip_transcription.extract_clip_source_audio(source_id, force=True, db_path=self.db_path)


if __name__ == "__main__":
    unittest.main()
