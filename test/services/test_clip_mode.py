"""
Test Suite para Clip Mode Foundation (Fase V11-A).

Valida os 40 requisitos obrigatórios da fundação de Clip Mode:
1. schema criado idempotentemente
2. authorization default false
3. sem autorização não fica READY
4. owned autorizado aceita
5. licensed autorizado aceita
6. permission autorizado aceita
7. public_domain autorizado aceita
8. extensão inválida rejeitada
9. arquivo inexistente rejeitado
10. arquivo vazio rejeitado
11. sem stream de vídeo rejeitado
12. ffprobe metadata persistida
13. duração persistida
14. resolução persistida
15. codec persistido
16. áudio detectado
17. vídeo sem áudio gera warning/estado válido
18. SHA256 calculado
19. duplicate hash detectado
20. duplicado não copia novamente
21. original nunca removido
22. stored filename seguro
23. path traversal bloqueado
24. source associado ao profile
25. legacy/default profile seguro
26. SECONDARY não importa
27. PRIMARY importa
28. create segment manual
29. start negativo bloqueado
30. end <= start bloqueado
31. end > duration bloqueado
32. duration calculada no backend
33. profile mismatch bloqueado
34. segment status padrão correto
35. selection_method=manual
36. source inexistente bloqueado
37. source inválido não recebe segmento
38. desativação não apaga arquivo
39. desativação não apaga segmentos
40. UI read path não executa ffprobe/hash/copy
"""
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.services import (
    clip_mode,
    operator_console,
    profile_manager,
)


class TestClipMode(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_video_factory.db")

        # Configura instância como PRIMARY por padrão para os testes
        operator_console.reset_instance_for_testing()
        with operator_console._instance_state_lock:
            operator_console._current_role = operator_console.ROLE_PRIMARY

        # Inicializa tabelas
        profile_manager.init_profile_db(db_path=self.db_path)
        profile_manager.ensure_default_profile(db_path=self.db_path)
        clip_mode.init_clip_db(db_path=self.db_path)

        # Cria um arquivo de vídeo falso para testes
        self.fake_video_path = os.path.join(self.tmp_dir.name, "sample_clip.mp4")
        with open(self.fake_video_path, "wb") as f:
            f.write(b"FAKE_MP4_VIDEO_HEADER_1234567890_DATA_STREAM")

        # Metadata padrão para mock de probe
        self.default_probe_metadata = {
            "duration_seconds": 120.5,
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

    # 1. schema criado idempotentemente
    def test_01_schema_created_idempotently(self):
        # Chama init_clip_db múltiplas vezes
        clip_mode.init_clip_db(db_path=self.db_path)
        clip_mode.init_clip_db(db_path=self.db_path)

        with clip_mode.get_connection(self.db_path) as conn:
            c = conn.cursor()
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('clip_sources', 'clip_segments')")
            tables = [r[0] for r in c.fetchall()]
            self.assertIn("clip_sources", tables)
            self.assertIn("clip_segments", tables)

    # 2. authorization default false
    def test_02_authorization_default_false(self):
        with self.assertRaises(clip_mode.ClipAuthorizationError):
            clip_mode.import_clip_source(
                file_path=self.fake_video_path,
                source_origin="owned",
                authorization_confirmed=False,
                db_path=self.db_path,
            )

    # 3. sem autorização não fica READY
    def test_03_without_authorization_does_not_become_ready(self):
        with self.assertRaises(clip_mode.ClipAuthorizationError):
            clip_mode.import_clip_source(
                file_path=self.fake_video_path,
                source_origin="owned",
                authorization_confirmed=False,
                db_path=self.db_path,
            )
        # Verifica que nenhuma fonte foi criada
        sources = clip_mode.list_clip_sources(db_path=self.db_path)
        self.assertEqual(len(sources), 0)

    # 4. owned autorizado aceita
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_04_owned_authorized_accepted(self, mock_probe):
        mock_probe.return_value = self.default_probe_metadata
        res = clip_mode.import_clip_source(
            file_path=self.fake_video_path,
            source_origin="owned",
            authorization_confirmed=True,
            db_path=self.db_path,
        )
        self.assertEqual(res["status"], "created")
        src = clip_mode.get_clip_source(res["source_id"], db_path=self.db_path)
        self.assertEqual(src["status"], clip_mode.SOURCE_STATUS_READY)
        self.assertEqual(src["source_origin"], "owned")
        self.assertEqual(src["authorization_confirmed"], 1)

    # 5. licensed autorizado aceita
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_05_licensed_authorized_accepted(self, mock_probe):
        mock_probe.return_value = self.default_probe_metadata
        res = clip_mode.import_clip_source(
            file_path=self.fake_video_path,
            source_origin="licensed",
            authorization_confirmed=True,
            authorization_note="Licenca comercial #456",
            db_path=self.db_path,
        )
        src = clip_mode.get_clip_source(res["source_id"], db_path=self.db_path)
        self.assertEqual(src["source_origin"], "licensed")
        self.assertEqual(src["authorization_note"], "Licenca comercial #456")

    # 6. permission autorizado aceita
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_06_permission_authorized_accepted(self, mock_probe):
        mock_probe.return_value = self.default_probe_metadata
        res = clip_mode.import_clip_source(
            file_path=self.fake_video_path,
            source_origin="permission",
            authorization_confirmed=True,
            db_path=self.db_path,
        )
        src = clip_mode.get_clip_source(res["source_id"], db_path=self.db_path)
        self.assertEqual(src["source_origin"], "permission")

    # 7. public_domain autorizado aceita
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_07_public_domain_authorized_accepted(self, mock_probe):
        mock_probe.return_value = self.default_probe_metadata
        res = clip_mode.import_clip_source(
            file_path=self.fake_video_path,
            source_origin="public_domain",
            authorization_confirmed=True,
            db_path=self.db_path,
        )
        src = clip_mode.get_clip_source(res["source_id"], db_path=self.db_path)
        self.assertEqual(src["source_origin"], "public_domain")

    # 8. extensão inválida rejeitada
    def test_08_invalid_extension_rejected(self):
        bad_path = os.path.join(self.tmp_dir.name, "test.exe")
        with open(bad_path, "wb") as f:
            f.write(b"not a video")
        with self.assertRaises(clip_mode.ClipValidationError) as ctx:
            clip_mode.import_clip_source(
                file_path=bad_path,
                source_origin="owned",
                authorization_confirmed=True,
                db_path=self.db_path,
            )
        self.assertIn("não suportada", str(ctx.exception).lower())

    # 9. arquivo inexistente rejeitado
    def test_09_nonexistent_file_rejected(self):
        missing_path = os.path.join(self.tmp_dir.name, "missing.mp4")
        with self.assertRaises(clip_mode.ClipValidationError):
            clip_mode.import_clip_source(
                file_path=missing_path,
                source_origin="owned",
                authorization_confirmed=True,
                db_path=self.db_path,
            )

    # 10. arquivo vazio rejeitado
    def test_10_empty_file_rejected(self):
        empty_path = os.path.join(self.tmp_dir.name, "empty.mp4")
        with open(empty_path, "wb") as f:
            pass
        with self.assertRaises(clip_mode.ClipValidationError) as ctx:
            clip_mode.import_clip_source(
                file_path=empty_path,
                source_origin="owned",
                authorization_confirmed=True,
                db_path=self.db_path,
            )
        self.assertIn("vazio", str(ctx.exception).lower())

    # 11. sem stream de vídeo rejeitado
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_11_no_video_stream_rejected(self, mock_probe):
        mock_probe.side_effect = clip_mode.ClipValidationError("Arquivo não contém stream de vídeo válido.")
        with self.assertRaises(clip_mode.ClipValidationError):
            clip_mode.import_clip_source(
                file_path=self.fake_video_path,
                source_origin="owned",
                authorization_confirmed=True,
                db_path=self.db_path,
            )

    # 12. ffprobe metadata persistida
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_12_metadata_persisted(self, mock_probe):
        mock_probe.return_value = self.default_probe_metadata
        res = clip_mode.import_clip_source(
            file_path=self.fake_video_path,
            source_origin="owned",
            authorization_confirmed=True,
            db_path=self.db_path,
        )
        src = clip_mode.get_clip_source(res["source_id"], db_path=self.db_path)
        self.assertEqual(src["video_codec"], "h264")
        self.assertEqual(src["audio_codec"], "aac")

    # 13. duração persistida
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_13_duration_persisted(self, mock_probe):
        mock_probe.return_value = self.default_probe_metadata
        res = clip_mode.import_clip_source(
            file_path=self.fake_video_path,
            source_origin="owned",
            authorization_confirmed=True,
            db_path=self.db_path,
        )
        src = clip_mode.get_clip_source(res["source_id"], db_path=self.db_path)
        self.assertAlmostEqual(src["duration_seconds"], 120.5, places=2)

    # 14. resolução persistida
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_14_resolution_persisted(self, mock_probe):
        mock_probe.return_value = self.default_probe_metadata
        res = clip_mode.import_clip_source(
            file_path=self.fake_video_path,
            source_origin="owned",
            authorization_confirmed=True,
            db_path=self.db_path,
        )
        src = clip_mode.get_clip_source(res["source_id"], db_path=self.db_path)
        self.assertEqual(src["width"], 1920)
        self.assertEqual(src["height"], 1080)

    # 15. codec persistido
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_15_codec_persisted(self, mock_probe):
        mock_probe.return_value = self.default_probe_metadata
        res = clip_mode.import_clip_source(
            file_path=self.fake_video_path,
            source_origin="owned",
            authorization_confirmed=True,
            db_path=self.db_path,
        )
        src = clip_mode.get_clip_source(res["source_id"], db_path=self.db_path)
        self.assertEqual(src["video_codec"], "h264")

    # 16. áudio detectado
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_16_audio_detected(self, mock_probe):
        mock_probe.return_value = self.default_probe_metadata
        res = clip_mode.import_clip_source(
            file_path=self.fake_video_path,
            source_origin="owned",
            authorization_confirmed=True,
            db_path=self.db_path,
        )
        src = clip_mode.get_clip_source(res["source_id"], db_path=self.db_path)
        self.assertEqual(src["has_audio"], 1)

    # 17. vídeo sem áudio gera warning/estado válido
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_17_video_without_audio_generates_warning_and_valid_state(self, mock_probe):
        meta_no_audio = dict(self.default_probe_metadata)
        meta_no_audio["has_audio"] = False
        meta_no_audio["audio_codec"] = None
        mock_probe.return_value = meta_no_audio

        res = clip_mode.import_clip_source(
            file_path=self.fake_video_path,
            source_origin="owned",
            authorization_confirmed=True,
            db_path=self.db_path,
        )
        self.assertEqual(res["status"], "created")
        self.assertTrue(any("áudio" in w.lower() for w in res["warnings"]))
        src = clip_mode.get_clip_source(res["source_id"], db_path=self.db_path)
        self.assertEqual(src["has_audio"], 0)
        self.assertEqual(src["status"], clip_mode.SOURCE_STATUS_READY)

    # 18. SHA256 calculado
    def test_18_sha256_calculated(self):
        sha = clip_mode.calculate_file_sha256(self.fake_video_path)
        self.assertIsInstance(sha, str)
        self.assertEqual(len(sha), 64)

    # 19. duplicate hash detectado
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_19_duplicate_hash_detected(self, mock_probe):
        mock_probe.return_value = self.default_probe_metadata
        res1 = clip_mode.import_clip_source(
            file_path=self.fake_video_path,
            source_origin="owned",
            authorization_confirmed=True,
            db_path=self.db_path,
        )
        res2 = clip_mode.import_clip_source(
            file_path=self.fake_video_path,
            source_origin="owned",
            authorization_confirmed=True,
            db_path=self.db_path,
        )
        self.assertEqual(res2["status"], "duplicate")
        self.assertEqual(res2["source_id"], res1["source_id"])

    # 20. duplicado não copia novamente
    @patch("app.services.clip_mode.probe_video_metadata")
    @patch("shutil.copy2")
    def test_20_duplicate_does_not_recopy(self, mock_copy, mock_probe):
        mock_probe.return_value = self.default_probe_metadata
        clip_mode.import_clip_source(
            file_path=self.fake_video_path,
            source_origin="owned",
            authorization_confirmed=True,
            db_path=self.db_path,
        )
        self.assertEqual(mock_copy.call_count, 1)

        # Segunda importação do mesmo arquivo
        clip_mode.import_clip_source(
            file_path=self.fake_video_path,
            source_origin="owned",
            authorization_confirmed=True,
            db_path=self.db_path,
        )
        # copy2 não deve ser chamado uma segunda vez
        self.assertEqual(mock_copy.call_count, 1)

    # 21. original nunca removido
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_21_original_never_removed(self, mock_probe):
        mock_probe.return_value = self.default_probe_metadata
        self.assertTrue(os.path.exists(self.fake_video_path))
        clip_mode.import_clip_source(
            file_path=self.fake_video_path,
            source_origin="owned",
            authorization_confirmed=True,
            db_path=self.db_path,
        )
        self.assertTrue(os.path.exists(self.fake_video_path))

    # 22. stored filename seguro
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_22_stored_filename_safe(self, mock_probe):
        mock_probe.return_value = self.default_probe_metadata
        res = clip_mode.import_clip_source(
            file_path=self.fake_video_path,
            source_origin="owned",
            authorization_confirmed=True,
            db_path=self.db_path,
        )
        src = clip_mode.get_clip_source(res["source_id"], db_path=self.db_path)
        self.assertEqual(src["stored_filename"], "source.mp4")
        self.assertTrue(os.path.isabs(src["stored_path"]))

    # 23. path traversal bloqueado
    def test_23_path_traversal_blocked(self):
        traversal_name = sanitize = clip_mode.sanitize_clip_filename("../../etc/passwd.mp4")
        self.assertNotIn("/", traversal_name)
        self.assertNotIn("\\", traversal_name)
        self.assertEqual(traversal_name, "passwd.mp4")

    # 23b. source symlink é rejeitado (mock)
    @patch("os.path.islink", return_value=True)
    def test_23b_symlink_input_rejected_mock(self, mock_islink):
        with self.assertRaises(clip_mode.ClipValidationError) as ctx:
            clip_mode.import_clip_source(
                file_path=self.fake_video_path,
                source_origin="owned",
                authorization_confirmed=True,
                db_path=self.db_path,
            )
        self.assertIn("symlink", str(ctx.exception).lower())

    # 23c. probe de mídia rejeita symlink
    @patch("os.path.islink", return_value=True)
    def test_23c_probe_symlink_rejected(self, mock_islink):
        with self.assertRaises(clip_mode.ClipValidationError) as ctx:
            clip_mode.probe_video_metadata(self.fake_video_path)
        self.assertIn("symlink", str(ctx.exception).lower())

    # 23d. source symlink real rejeitado (se suportado pelo SO)
    def test_23d_real_symlink_rejected_if_supported(self):
        symlink_path = os.path.join(self.tmp_dir.name, "symlink_video.mp4")
        try:
            os.symlink(self.fake_video_path, symlink_path)
        except (OSError, NotImplementedError):
            # No Windows sem Developer Mode/privilégio de administrador, criação de symlink pode falhar
            return

        with self.assertRaises(clip_mode.ClipValidationError) as ctx:
            clip_mode.import_clip_source(
                file_path=symlink_path,
                source_origin="owned",
                authorization_confirmed=True,
                db_path=self.db_path,
            )
        self.assertIn("symlink", str(ctx.exception).lower())

    # 24. source associado ao profile
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_24_source_associated_to_profile(self, mock_probe):
        mock_probe.return_value = self.default_probe_metadata
        p = profile_manager.create_profile(name="Perfil Podcasts", db_path=self.db_path)
        res = clip_mode.import_clip_source(
            file_path=self.fake_video_path,
            source_origin="owned",
            authorization_confirmed=True,
            profile_id=p["id"],
            db_path=self.db_path,
        )
        src = clip_mode.get_clip_source(res["source_id"], db_path=self.db_path)
        self.assertEqual(src["profile_id"], p["id"])

    # 25. legacy/default profile seguro
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_25_legacy_default_profile_safe(self, mock_probe):
        mock_probe.return_value = self.default_probe_metadata
        res = clip_mode.import_clip_source(
            file_path=self.fake_video_path,
            source_origin="owned",
            authorization_confirmed=True,
            profile_id=None,
            db_path=self.db_path,
        )
        src = clip_mode.get_clip_source(res["source_id"], db_path=self.db_path)
        self.assertEqual(src["profile_id"], profile_manager.DEFAULT_PROFILE_ID)

    # 26. SECONDARY não importa
    @patch("app.services.operator_console.is_primary_instance", return_value=False)
    def test_26_secondary_cannot_import(self, mock_is_primary):
        with self.assertRaises(PermissionError):
            clip_mode.import_clip_source(
                file_path=self.fake_video_path,
                source_origin="owned",
                authorization_confirmed=True,
                db_path=self.db_path,
            )

    # 27. PRIMARY importa
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_27_primary_imports_successfully(self, mock_probe):
        mock_probe.return_value = self.default_probe_metadata
        res = clip_mode.import_clip_source(
            file_path=self.fake_video_path,
            source_origin="owned",
            authorization_confirmed=True,
            db_path=self.db_path,
        )
        self.assertEqual(res["status"], "created")

    # 28. create segment manual
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_28_create_segment_manual(self, mock_probe):
        mock_probe.return_value = self.default_probe_metadata
        s_res = clip_mode.import_clip_source(
            file_path=self.fake_video_path,
            source_origin="owned",
            authorization_confirmed=True,
            db_path=self.db_path,
        )
        src_id = s_res["source_id"]

        seg_res = clip_mode.create_clip_segment(
            source_id=src_id,
            start_seconds=10.0,
            end_seconds=45.0,
            title="Destaque Manual",
            db_path=self.db_path,
        )
        self.assertEqual(seg_res["status"], "created")
        seg = clip_mode.get_clip_segment(seg_res["segment_id"], db_path=self.db_path)
        self.assertEqual(seg["title"], "Destaque Manual")
        self.assertAlmostEqual(seg["duration_seconds"], 35.0, places=2)

    # 29. start negativo bloqueado
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_29_negative_start_blocked(self, mock_probe):
        mock_probe.return_value = self.default_probe_metadata
        s_res = clip_mode.import_clip_source(
            file_path=self.fake_video_path,
            source_origin="owned",
            authorization_confirmed=True,
            db_path=self.db_path,
        )
        with self.assertRaises(clip_mode.ClipValidationError):
            clip_mode.create_clip_segment(
                source_id=s_res["source_id"],
                start_seconds=-5.0,
                end_seconds=30.0,
                db_path=self.db_path,
            )

    # 30. end <= start bloqueado
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_30_end_less_than_or_equal_start_blocked(self, mock_probe):
        mock_probe.return_value = self.default_probe_metadata
        s_res = clip_mode.import_clip_source(
            file_path=self.fake_video_path,
            source_origin="owned",
            authorization_confirmed=True,
            db_path=self.db_path,
        )
        # end == start
        with self.assertRaises(clip_mode.ClipValidationError):
            clip_mode.create_clip_segment(
                source_id=s_res["source_id"],
                start_seconds=30.0,
                end_seconds=30.0,
                db_path=self.db_path,
            )
        # end < start
        with self.assertRaises(clip_mode.ClipValidationError):
            clip_mode.create_clip_segment(
                source_id=s_res["source_id"],
                start_seconds=30.0,
                end_seconds=20.0,
                db_path=self.db_path,
            )

    # 31. end > duration bloqueado
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_31_end_exceeds_duration_blocked(self, mock_probe):
        mock_probe.return_value = self.default_probe_metadata  # duration = 120.5
        s_res = clip_mode.import_clip_source(
            file_path=self.fake_video_path,
            source_origin="owned",
            authorization_confirmed=True,
            db_path=self.db_path,
        )
        with self.assertRaises(clip_mode.ClipValidationError):
            clip_mode.create_clip_segment(
                source_id=s_res["source_id"],
                start_seconds=10.0,
                end_seconds=150.0,
                db_path=self.db_path,
            )

    # 32. duration calculada no backend
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_32_duration_calculated_on_backend(self, mock_probe):
        mock_probe.return_value = self.default_probe_metadata
        s_res = clip_mode.import_clip_source(
            file_path=self.fake_video_path,
            source_origin="owned",
            authorization_confirmed=True,
            db_path=self.db_path,
        )
        seg_res = clip_mode.create_clip_segment(
            source_id=s_res["source_id"],
            start_seconds=15.2,
            end_seconds=42.7,
            db_path=self.db_path,
        )
        seg = clip_mode.get_clip_segment(seg_res["segment_id"], db_path=self.db_path)
        self.assertEqual(seg["duration_seconds"], 27.5)

    # 33. profile mismatch bloqueado
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_33_profile_mismatch_blocked(self, mock_probe):
        mock_probe.return_value = self.default_probe_metadata
        p1 = profile_manager.create_profile(name="P1", db_path=self.db_path)
        p2 = profile_manager.create_profile(name="P2", db_path=self.db_path)

        s_res = clip_mode.import_clip_source(
            file_path=self.fake_video_path,
            source_origin="owned",
            authorization_confirmed=True,
            profile_id=p1["id"],
            db_path=self.db_path,
        )
        with self.assertRaises(clip_mode.ClipValidationError) as ctx:
            clip_mode.create_clip_segment(
                source_id=s_res["source_id"],
                start_seconds=0.0,
                end_seconds=30.0,
                profile_id=p2["id"],
                db_path=self.db_path,
            )
        self.assertIn("conflito de perfil", str(ctx.exception).lower())

    # 34. segment status padrão correto
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_34_default_segment_status_is_candidate(self, mock_probe):
        mock_probe.return_value = self.default_probe_metadata
        s_res = clip_mode.import_clip_source(
            file_path=self.fake_video_path,
            source_origin="owned",
            authorization_confirmed=True,
            db_path=self.db_path,
        )
        seg_res = clip_mode.create_clip_segment(
            source_id=s_res["source_id"],
            start_seconds=5.0,
            end_seconds=25.0,
            db_path=self.db_path,
        )
        seg = clip_mode.get_clip_segment(seg_res["segment_id"], db_path=self.db_path)
        self.assertEqual(seg["status"], clip_mode.SEGMENT_STATUS_CANDIDATE)

    # 35. selection_method=manual
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_35_selection_method_manual(self, mock_probe):
        mock_probe.return_value = self.default_probe_metadata
        s_res = clip_mode.import_clip_source(
            file_path=self.fake_video_path,
            source_origin="owned",
            authorization_confirmed=True,
            db_path=self.db_path,
        )
        seg_res = clip_mode.create_clip_segment(
            source_id=s_res["source_id"],
            start_seconds=1.0,
            end_seconds=20.0,
            db_path=self.db_path,
        )
        seg = clip_mode.get_clip_segment(seg_res["segment_id"], db_path=self.db_path)
        self.assertEqual(seg["selection_method"], clip_mode.SELECTION_METHOD_MANUAL)

    # 36. source inexistente bloqueado
    def test_36_nonexistent_source_blocked(self):
        with self.assertRaises(clip_mode.ClipValidationError):
            clip_mode.create_clip_segment(
                source_id="src_inexistente_999",
                start_seconds=0.0,
                end_seconds=10.0,
                db_path=self.db_path,
            )

    # 37. source inválido não recebe segmento
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_37_invalid_source_cannot_receive_segment(self, mock_probe):
        mock_probe.return_value = self.default_probe_metadata
        s_res = clip_mode.import_clip_source(
            file_path=self.fake_video_path,
            source_origin="owned",
            authorization_confirmed=True,
            db_path=self.db_path,
        )
        # Desativa a fonte (status -> INACTIVE)
        clip_mode.deactivate_clip_source(s_res["source_id"], db_path=self.db_path)

        with self.assertRaises(clip_mode.ClipValidationError) as ctx:
            clip_mode.create_clip_segment(
                source_id=s_res["source_id"],
                start_seconds=0.0,
                end_seconds=15.0,
                db_path=self.db_path,
            )
        self.assertIn("ready", str(ctx.exception).lower())

    # 38. desativação não apaga arquivo
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_38_deactivation_does_not_delete_file(self, mock_probe):
        mock_probe.return_value = self.default_probe_metadata
        s_res = clip_mode.import_clip_source(
            file_path=self.fake_video_path,
            source_origin="owned",
            authorization_confirmed=True,
            db_path=self.db_path,
        )
        src = clip_mode.get_clip_source(s_res["source_id"], db_path=self.db_path)
        stored_path = src["stored_path"]
        self.assertTrue(os.path.exists(stored_path))

        clip_mode.deactivate_clip_source(s_res["source_id"], db_path=self.db_path)
        updated = clip_mode.get_clip_source(s_res["source_id"], db_path=self.db_path)
        self.assertEqual(updated["status"], clip_mode.SOURCE_STATUS_INACTIVE)
        # O arquivo físico DEVE continuar existindo no disco
        self.assertTrue(os.path.exists(stored_path))

    # 39. desativação não apaga segmentos
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_39_deactivation_does_not_delete_segments(self, mock_probe):
        mock_probe.return_value = self.default_probe_metadata
        s_res = clip_mode.import_clip_source(
            file_path=self.fake_video_path,
            source_origin="owned",
            authorization_confirmed=True,
            db_path=self.db_path,
        )
        seg_res = clip_mode.create_clip_segment(
            source_id=s_res["source_id"],
            start_seconds=0.0,
            end_seconds=10.0,
            db_path=self.db_path,
        )

        clip_mode.deactivate_clip_source(s_res["source_id"], db_path=self.db_path)
        segments = clip_mode.list_clip_segments(source_id=s_res["source_id"], db_path=self.db_path)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0]["id"], seg_res["segment_id"])

    # 40. UI read path não executa ffprobe/hash/copy
    @patch("app.services.clip_mode.probe_video_metadata")
    @patch("app.services.clip_mode.calculate_file_sha256")
    @patch("shutil.copy2")
    def test_40_ui_read_path_does_not_execute_heavy_operations(self, mock_copy, mock_hash, mock_probe):
        # Chama as operações de leitura expostas ao Operator Console
        operator_console.list_clip_sources_op(db_path=self.db_path)
        operator_console.get_clip_source_op("any_id", db_path=self.db_path)
        operator_console.list_clip_segments_op(db_path=self.db_path)

        # Garante que nenhuma operação de mídia foi invocada
        self.assertEqual(mock_probe.call_count, 0)
        self.assertEqual(mock_hash.call_count, 0)
        self.assertEqual(mock_copy.call_count, 0)


if __name__ == "__main__":
    unittest.main()
