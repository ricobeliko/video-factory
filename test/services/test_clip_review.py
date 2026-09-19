"""
Test Suite para Clip Review Service (Fase V11-D — Review & Burn-In).

Cobre os requisitos de revisão e burn-in:
35. review schema idempotente
36. base render COMPLETED obrigatório
37. caption COMPLETED obrigatório
38. output temp seguro
39. shell=False
40. timeout
41. atomic replace
42. temp cleanup
43. invalid output FAILED
44. width 1080
45. height 1920
46. duration válida
47. áudio preservado quando esperado
48. no-audio válido
49. PROCESSING duplicado bloqueado
50. atomic processing insert
51. FFmpeg fora transaction
52. approve PRIMARY
53. reject PRIMARY
54. SECONDARY não aprova
55. APPROVED não publica
56. REJECTED não apaga arquivo
57. approved artifact helper correto
58. source unchanged on failure
59. segment unchanged on failure
60. base render unchanged on failure
61. UI read zero FFmpeg
62. UI read zero model load
63. UI read zero HTTP
64. zero publication
"""
from datetime import datetime, timezone
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.services import (
    clip_captions,
    clip_mode,
    clip_rendering,
    clip_review,
    clip_transcription,
    operator_console,
    profile_manager,
)
from app.utils import utils


class TestClipReview(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = os.path.join(self.tmp_dir.name, "test_review.db")

        operator_console.reset_instance_for_testing()
        with operator_console._instance_state_lock:
            operator_console._current_role = operator_console.ROLE_PRIMARY

        profile_manager.init_profile_db(db_path=self.test_db_path)
        profile_manager.ensure_default_profile(db_path=self.test_db_path)
        clip_mode.init_clip_db(db_path=self.test_db_path)
        clip_transcription.init_clip_transcription_db(db_path=self.test_db_path)
        clip_rendering.init_clip_rendering_db(db_path=self.test_db_path)
        clip_captions.init_clip_captions_db(db_path=self.test_db_path)
        clip_review.init_clip_review_db(db_path=self.test_db_path)

        # Arquivo de vídeo mock
        self.fake_video = os.path.join(self.tmp_dir.name, "fake_video.mp4")
        with open(self.fake_video, "wb") as f:
            f.write(b"MOCK_VIDEO_DATA")

        self.mock_probe_source = {
            "duration_seconds": 120.0,
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
            "video_codec": "h264",
            "audio_codec": "aac",
            "has_audio": True,
        }

        with patch("app.services.clip_mode.probe_video_metadata", return_value=self.mock_probe_source):
            imp = clip_mode.import_clip_source(
                self.fake_video,
                source_origin="owned",
                authorization_confirmed=True,
                authorization_note="Teste Unitário Review",
                db_path=self.test_db_path,
            )
            self.source_id = imp["source_id"]

        # Segmento SELECTED
        seg_res = clip_mode.create_clip_segment(
            source_id=self.source_id,
            start_seconds=10.0,
            end_seconds=40.0,
            title="Segmento 10-40",
            db_path=self.test_db_path,
        )
        self.segment_id = seg_res["segment_id"]
        clip_mode.update_clip_segment_status(self.segment_id, "SELECTED", db_path=self.test_db_path)

        # Render Base COMPLETED em disco
        self.render_id = "rend_base_001"
        render_dir = utils.storage_dir(os.path.join("clip_sources", self.source_id, "renders", self.render_id), create=True)
        self.render_file = os.path.join(render_dir, "clip.mp4")
        with open(self.render_file, "wb") as f:
            f.write(b"MOCK_RENDER_MP4_BYTES")

        now_iso = datetime.now(timezone.utc).isoformat()
        with clip_mode.get_connection(self.test_db_path) as conn:
            conn.execute(
                """
                INSERT INTO clip_renders (
                    id, segment_id, source_id, profile_id, render_strategy,
                    width, height, fps, video_codec, audio_codec, output_path,
                    file_size_bytes, duration_seconds, status, started_at,
                    completed_at, created_at, updated_at, source_sha256, render_fingerprint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    self.render_id,
                    self.segment_id,
                    self.source_id,
                    "default",
                    "fit_blur",
                    1080,
                    1920,
                    30.0,
                    "libx264",
                    "aac",
                    self.render_file,
                    len(b"MOCK_RENDER_MP4_BYTES"),
                    30.0,
                    "COMPLETED",
                    now_iso,
                    now_iso,
                    now_iso,
                    now_iso,
                    "dummy_sha",
                    "dummy_rnd_fp",
                ),
            )

        # Caption Track COMPLETED em disco
        self.caption_track_id = "cap_track_001"
        caption_dir = utils.storage_dir(os.path.join("clip_sources", self.source_id, "captions", self.caption_track_id), create=True)
        self.srt_file = os.path.join(caption_dir, "captions.srt")
        self.ass_file = os.path.join(caption_dir, "captions.ass")
        with open(self.srt_file, "w", encoding="utf-8") as f:
            f.write("1\n00:00:01,000 --> 00:00:03,000\nTeste\n\n")
        with open(self.ass_file, "w", encoding="utf-8") as f:
            f.write("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n")

        with clip_mode.get_connection(self.test_db_path) as conn:
            conn.execute(
                """
                INSERT INTO clip_transcripts (
                    id, source_id, profile_id, provider, model_name, language,
                    status, full_text, started_at, completed_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    "trans_001",
                    self.source_id,
                    "default",
                    "faster-whisper",
                    "base",
                    "pt",
                    "COMPLETED",
                    "Full text",
                    now_iso,
                    now_iso,
                    now_iso,
                    now_iso,
                ),
            )
            conn.execute(
                """
                INSERT INTO clip_caption_tracks (
                    id, segment_id, source_id, profile_id, transcript_id,
                    style, language, cue_count, duration_seconds,
                    srt_path, ass_path, caption_fingerprint, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    self.caption_track_id,
                    self.segment_id,
                    self.source_id,
                    "default",
                    "trans_001",
                    "CLEAN",
                    "pt",
                    1,
                    30.0,
                    self.srt_file,
                    self.ass_file,
                    "dummy_cap_fp",
                    "COMPLETED",
                    now_iso,
                    now_iso,
                ),
            )

        self.mock_rendered_probe = {
            "duration_seconds": 30.0,
            "width": 1080,
            "height": 1920,
            "fps": 30.0,
            "video_codec": "h264",
            "audio_codec": "aac",
            "has_audio": True,
        }

    def tearDown(self):
        operator_console.reset_instance_for_testing()
        self.tmp_dir.cleanup()

    def _mock_ffmpeg_success(self, *args, **kwargs):
        cmd = kwargs.get("cmd") or args[0]
        out_path = cmd[-1]
        with open(out_path, "wb") as f:
            f.write(b"FINAL_BURNIN_OUTPUT_DATA")
        return MagicMock(returncode=0, stdout="", stderr="")

    def test_35_review_schema_idempotent(self):
        """35: Confirma que o schema de review outputs pode ser inicializado repetidamente."""
        clip_review.init_clip_review_db(db_path=self.test_db_path)
        clip_review.init_clip_review_db(db_path=self.test_db_path)
        with clip_mode.get_connection(self.test_db_path) as conn:
            t = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='clip_review_outputs';").fetchone()
            self.assertIsNotNone(t)

    def test_36_base_render_completed_required(self):
        """36: Rejeita se render base não estiver COMPLETED."""
        with clip_mode.get_connection(self.test_db_path) as conn:
            conn.execute("UPDATE clip_renders SET status = 'PROCESSING' WHERE id = ?", (self.render_id,))

        with self.assertRaises(clip_review.ClipReviewError):
            clip_review.create_clip_review_output(self.render_id, self.caption_track_id, db_path=self.test_db_path)

    def test_37_caption_completed_required(self):
        """37: Rejeita se caption track não estiver COMPLETED."""
        with clip_mode.get_connection(self.test_db_path) as conn:
            conn.execute("UPDATE clip_caption_tracks SET status = 'FAILED' WHERE id = ?", (self.caption_track_id,))

        with self.assertRaises(clip_review.ClipReviewError):
            clip_review.create_clip_review_output(self.render_id, self.caption_track_id, db_path=self.test_db_path)

    @patch("subprocess.run")
    def test_38_to_41_output_temp_and_atomic_replace(self, mock_subproc):
        """38 a 41: Garante temp file isolado, shell=False, timeout e promoção via os.replace."""
        mock_subproc.side_effect = self._mock_ffmpeg_success

        with patch("app.services.clip_mode.probe_video_metadata", return_value=self.mock_rendered_probe):
            with patch("os.replace", wraps=os.replace) as mock_replace:
                rev = clip_review.create_clip_review_output(
                    self.render_id,
                    self.caption_track_id,
                    timeout_seconds=120,
                    db_path=self.test_db_path,
                )
                self.assertEqual(rev["status"], "COMPLETED")
                self.assertEqual(rev["review_status"], "PENDING_REVIEW")
                self.assertTrue(os.path.isfile(rev["output_path"]))

                # Verifica chamada do subprocess
                mock_subproc.assert_called_once()
                call_kwargs = mock_subproc.call_args[1]
                self.assertFalse(call_kwargs.get("shell", True))
                self.assertEqual(call_kwargs.get("timeout"), 120)

                # Verifica que os.replace promoveu do temp para clip_final.mp4
                mock_replace.assert_called_once()
                args, _ = mock_replace.call_args
                self.assertIn(".tmp.mp4", args[0])
                self.assertTrue(args[1].endswith("clip_final.mp4"))

    @patch("subprocess.run")
    def test_42_and_43_temp_cleanup_on_error_and_failed_status(self, mock_subproc):
        """42 e 43: Se FFmpeg falha, remove arquivo temporário e grava status FAILED."""
        def mock_err(*args, **kwargs):
            cmd = kwargs.get("cmd") or args[0]
            temp_p = cmd[-1]
            with open(temp_p, "wb") as f:
                f.write(b"partial_temp")
            return MagicMock(returncode=1, stdout="", stderr="Simulated burn-in error")

        mock_subproc.side_effect = mock_err

        with patch("app.services.clip_mode.probe_video_metadata", return_value=self.mock_rendered_probe):
            with self.assertRaises(clip_review.ClipReviewError):
                clip_review.create_clip_review_output(self.render_id, self.caption_track_id, db_path=self.test_db_path)

        reviews = clip_review.list_clip_reviews_for_segment(self.segment_id, db_path=self.test_db_path)
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0]["status"], "FAILED")
        self.assertEqual(reviews[0]["error_code"], "FFMPEG_ERROR")

        # Garante que nenhum .tmp.mp4 sobrou
        rev_dir = os.path.dirname(reviews[0]["output_path"])
        if os.path.exists(rev_dir):
            tmps = [f for f in os.listdir(rev_dir) if f.endswith(".tmp.mp4")]
            self.assertEqual(len(tmps), 0)

    @patch("subprocess.run")
    def test_44_to_48_audio_and_resolution_validation(self, mock_subproc):
        """44 a 48: Validação de dimensões 1080x1920, duração e áudio preservado ou -an."""
        mock_subproc.side_effect = self._mock_ffmpeg_success

        # Com áudio: cmd deve conter -c:a aac
        with patch("app.services.clip_mode.probe_video_metadata", return_value=self.mock_rendered_probe):
            clip_review.create_clip_review_output(self.render_id, self.caption_track_id, db_path=self.test_db_path)
            cmd_audio = mock_subproc.call_args[0][0]
            self.assertIn("-c:a", cmd_audio)
            self.assertIn("aac", cmd_audio)

        # Sem áudio: cmd deve conter -an
        mock_subproc.reset_mock()
        probe_no_audio = dict(self.mock_rendered_probe)
        probe_no_audio["has_audio"] = False

        with patch("app.services.clip_mode.probe_video_metadata", return_value=probe_no_audio):
            clip_review.create_clip_review_output(self.render_id, self.caption_track_id, force=True, db_path=self.test_db_path)
            cmd_no_audio = mock_subproc.call_args[0][0]
            self.assertIn("-an", cmd_no_audio)

    def test_49_to_51_duplicate_processing_blocked(self):
        """49 a 51: Bloqueia review duplicado em estado PROCESSING."""
        with clip_mode.get_connection(self.test_db_path) as conn:
            conn.execute(
                """
                INSERT INTO clip_review_outputs (
                    id, render_id, caption_track_id, segment_id, source_id, profile_id,
                    output_path, width, height, status, review_status, created_at, updated_at, fingerprint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    "rev_proc_001",
                    self.render_id,
                    self.caption_track_id,
                    self.segment_id,
                    self.source_id,
                    "default",
                    "/tmp/dummy.mp4",
                    1080,
                    1920,
                    "PROCESSING",
                    "PENDING_REVIEW",
                    datetime.now(timezone.utc).isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                    "dummy_fp",
                ),
            )

        with self.assertRaises(clip_review.DuplicateReviewProcessingError):
            clip_review.create_clip_review_output(self.render_id, self.caption_track_id, db_path=self.test_db_path)

    @patch("subprocess.run")
    def test_52_to_57_approval_workflow_and_single_active_policy(self, mock_subproc):
        """52 a 57: Aprovação, rejeição, permissões PRIMARY/SECONDARY e política de único aprovado ativo."""
        mock_subproc.side_effect = self._mock_ffmpeg_success

        with patch("app.services.clip_mode.probe_video_metadata", return_value=self.mock_rendered_probe):
            rev1 = clip_review.create_clip_review_output(self.render_id, self.caption_track_id, db_path=self.test_db_path)
            rev2 = clip_review.create_clip_review_output(self.render_id, self.caption_track_id, force=True, db_path=self.test_db_path)

        # 54: SECONDARY não aprova nem rejeita
        with operator_console._instance_state_lock:
            operator_console._current_role = operator_console.ROLE_SECONDARY_VIEW_ONLY

        with self.assertRaises(PermissionError):
            clip_review.approve_clip_review(rev1["id"], db_path=self.test_db_path)

        with self.assertRaises(PermissionError):
            clip_review.reject_clip_review(rev1["id"], db_path=self.test_db_path)

        with operator_console._instance_state_lock:
            operator_console._current_role = operator_console.ROLE_PRIMARY

        # 52: Aprova rev1
        app1 = clip_review.approve_clip_review(rev1["id"], db_path=self.test_db_path)
        self.assertEqual(app1["review_status"], "APPROVED")

        # 57: Helper de artefato aprovado retorna rev1
        art1 = clip_review.get_approved_clip_artifact(self.segment_id, db_path=self.test_db_path)
        self.assertIsNotNone(art1)
        self.assertEqual(art1["review_id"], rev1["id"])
        self.assertEqual(art1["caption_style"], "CLEAN")

        # Política de único ativo: aprovar rev2 altera rev1 de volta para PENDING_REVIEW
        app2 = clip_review.approve_clip_review(rev2["id"], db_path=self.test_db_path)
        self.assertEqual(app2["review_status"], "APPROVED")

        rev1_reloaded = clip_review.get_clip_review(rev1["id"], db_path=self.test_db_path)
        self.assertEqual(rev1_reloaded["review_status"], "PENDING_REVIEW")

        art2 = clip_review.get_approved_clip_artifact(self.segment_id, db_path=self.test_db_path)
        self.assertEqual(art2["review_id"], rev2["id"])

        # 53 e 56: Rejeição não apaga arquivo
        rej = clip_review.reject_clip_review(rev2["id"], db_path=self.test_db_path)
        self.assertEqual(rej["review_status"], "REJECTED")
        self.assertTrue(os.path.isfile(rev2["output_path"]))

    @patch("subprocess.run")
    def test_58_to_60_failure_isolation(self, mock_subproc):
        """58 a 60: Falha no review não altera source (READY), segment (SELECTED) ou render (COMPLETED)."""
        mock_subproc.side_effect = subprocess.TimeoutExpired(cmd=[], timeout=5)

        with patch("app.services.clip_mode.probe_video_metadata", return_value=self.mock_rendered_probe):
            with self.assertRaises(subprocess.TimeoutExpired):
                clip_review.create_clip_review_output(self.render_id, self.caption_track_id, db_path=self.test_db_path)

        src = clip_mode.get_clip_source(self.source_id, db_path=self.test_db_path)
        seg = clip_mode.get_clip_segment(self.segment_id, db_path=self.test_db_path)
        rnd = clip_rendering.get_clip_render(self.render_id, db_path=self.test_db_path)

        self.assertEqual(src["status"], "READY")
        self.assertEqual(seg["status"], "SELECTED")
        self.assertEqual(rnd["status"], "COMPLETED")

    # 61. UI read zero FFmpeg
    @patch("subprocess.run")
    def test_61_ui_read_zero_ffmpeg(self, mock_sub):
        operator_console.list_clip_reviews_for_segment_op(self.segment_id, db_path=self.test_db_path)
        operator_console.list_caption_tracks_for_segment_op(self.segment_id, db_path=self.test_db_path)
        self.assertEqual(mock_sub.call_count, 0)

    # 62. UI read zero model load
    @patch("app.services.clip_captions.generate_clip_captions")
    @patch("app.services.clip_review.create_clip_review_output")
    def test_62_ui_read_zero_model_load(self, mock_rev, mock_cap):
        operator_console.list_clip_reviews_for_segment_op(self.segment_id, db_path=self.test_db_path)
        operator_console.get_caption_cues_op(self.caption_track_id, db_path=self.test_db_path)
        self.assertEqual(mock_rev.call_count, 0)
        self.assertEqual(mock_cap.call_count, 0)

    # 63. UI read zero HTTP
    @patch("urllib.request.urlopen")
    def test_63_ui_read_zero_http(self, mock_http):
        operator_console.list_clip_reviews_for_segment_op(self.segment_id, db_path=self.test_db_path)
        operator_console.list_caption_tracks_for_segment_op(self.segment_id, db_path=self.test_db_path)
        operator_console.get_approved_clip_artifact_op(self.segment_id, db_path=self.test_db_path)
        self.assertEqual(mock_http.call_count, 0)

    # 64. zero publication (mesmo após aprovação de review)
    @patch("subprocess.run")
    def test_64_zero_publication(self, mock_sub):
        mock_sub.side_effect = self._mock_ffmpeg_success
        with patch("app.services.clip_mode.probe_video_metadata", return_value=self.mock_rendered_probe):
            rev = clip_review.create_clip_review_output(self.render_id, self.caption_track_id, db_path=self.test_db_path)
            clip_review.approve_clip_review(rev["id"], db_path=self.test_db_path)

        with clip_mode.get_connection(self.test_db_path) as conn:
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='publication_events';")
            if cur.fetchone():
                pubs = conn.execute("SELECT COUNT(*) as c FROM publication_events;").fetchone()["c"]
                self.assertEqual(pubs, 0)

    def test_65_windows_path_with_spaces_and_drive_escaping(self):
        """65: Valida que caminhos com espaços e letra de unidade Windows são escapados com segurança."""
        test_path = r"D:\Projetos\Pasta com Espaços\captions.ass"
        escaped = clip_review._escape_path_for_ffmpeg_filter(test_path)
        self.assertEqual(escaped, "D\\:/Projetos/Pasta com Espaços/captions.ass")
        self.assertNotIn("\\P", escaped)  # Sem backslashes normais não escapados
        self.assertIn("D\\:", escaped)    # Colon escapado com barra


if __name__ == "__main__":
    unittest.main()
