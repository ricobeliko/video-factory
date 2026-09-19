"""
Test Suite para Clip Rendering Service (Fase V11-C — Vertical Clip Rendering).

Cobertura completa dos 60 requisitos individuais:
1. schema idempotente
2. source inexistente rejeita
3. source não READY rejeita
4. source sem autorização rejeita
5. segment inexistente rejeita
6. CANDIDATE não renderiza
7. REJECTED não renderiza
8. SELECTED aceita
9. profile mismatch rejeita
10. SECONDARY bloqueado
11. PRIMARY aceita
12. FIT_BLUR é default
13. CENTER_CROP aceita
14. strategy inválida rejeita
15. start/end vêm do backend
16. duration backend calculated
17. FFmpeg shell=False
18. argument list usada
19. timeout configurado
20. output temp no diretório correto
21. FFmpeg escreve em temp
22. sucesso promove atomicamente
23. os.replace usado
24. erro remove temp
25. timeout remove temp
26. final parcial nunca criado
27. output width 1080
28. output height 1920
29. output duration válida
30. video stream obrigatório
31. source com áudio preserva áudio
32. source sem áudio renderiza
33. no-audio warning correto
34. low-resolution warning
35. center-crop warning
36. completed render persistido
37. FAILED render persistido
38. failure não altera source
39. failure não altera segment
40. fingerprint determinístico
41. same config force=False reutiliza
42. force=True cria histórico
43. render antigo preservado
44. PROCESSING duplicado bloqueado
45. criação PROCESSING atômica
46. FFmpeg fora da transação
47. render path contido
48. symlink output rejeitado
49. empty output rejeitado
50. invalid probe rejeitado
51. source_sha256 preservado
52. profile preservado
53. segment_id preservado
54. UI read zero FFmpeg
55. UI read zero render
56. zero HTTP
57. zero publication
58. manual segments SELECTED renderizam normalmente
59. heuristic SELECTED renderizam normalmente
60. REJECTED heuristic não renderiza
"""
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from app.services import (
    clip_discovery,
    clip_mode,
    clip_rendering,
    operator_console,
    profile_manager,
)
from app.utils import utils


class TestClipRendering(unittest.TestCase):
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
        clip_rendering.init_clip_rendering_db(db_path=self.db_path)

        # Arquivo de vídeo de teste
        self.fake_video_path = os.path.join(self.tmp_dir.name, "source_video.mp4")
        with open(self.fake_video_path, "wb") as f:
            f.write(b"FAKE_SOURCE_VIDEO_BYTES_FOR_RENDERING_V11C_TESTS")

        self.default_probe = {
            "duration_seconds": 120.0,
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
            "video_codec": "h264",
            "audio_codec": "aac",
            "has_audio": True,
        }

        self.valid_rendered_probe = {
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

    def _import_ready_source(
        self,
        has_audio=True,
        duration=120.0,
        width=1920,
        height=1080,
        fps=30.0,
        authorization_confirmed=True,
        profile_id="default",
    ) -> str:
        probe_meta = dict(self.default_probe)
        probe_meta["has_audio"] = has_audio
        probe_meta["duration_seconds"] = duration
        probe_meta["width"] = width
        probe_meta["height"] = height
        probe_meta["fps"] = fps

        with patch("app.services.clip_mode.probe_video_metadata", return_value=probe_meta):
            res = clip_mode.import_clip_source(
                file_path=self.fake_video_path,
                source_origin="owned",
                authorization_confirmed=authorization_confirmed,
                authorization_note="Autorizado para testes V11-C",
                profile_id=profile_id,
                db_path=self.db_path,
            )
            return res["source_id"]

    def _create_segment(
        self,
        source_id: str,
        start=10.0,
        end=40.0,
        status="SELECTED",
        method="manual",
        profile_id="default",
    ) -> str:
        res = clip_mode.create_clip_segment(
            source_id=source_id,
            start_seconds=start,
            end_seconds=end,
            title="Segmento Teste",
            selection_method=method,
            profile_id=profile_id,
            db_path=self.db_path,
        )
        seg_id = res["segment_id"]
        if status != "CANDIDATE":
            clip_mode.update_clip_segment_status(seg_id, status, db_path=self.db_path)
        return seg_id

    def _fake_ffmpeg_run_success(self, cmd, *args, **kwargs):
        temp_out = cmd[-1]
        os.makedirs(os.path.dirname(temp_out), exist_ok=True)
        with open(temp_out, "wb") as f:
            f.write(b"SIMULATED_MP4_VERTICAL_VIDEO_DATA")
        res = MagicMock()
        res.returncode = 0
        res.stdout = ""
        res.stderr = ""
        return res

    # 1. schema idempotente
    def test_01_schema_idempotente(self):
        clip_rendering.init_clip_rendering_db(db_path=self.db_path)
        clip_rendering.init_clip_rendering_db(db_path=self.db_path)
        with clip_mode.get_connection(self.db_path) as conn:
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='clip_renders';")
            self.assertIsNotNone(cur.fetchone())
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_clip_renders_segment';")
            self.assertIsNotNone(cur.fetchone())

    # 2. source inexistente rejeita
    def test_02_source_inexistente_rejeita(self):
        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        with clip_mode.get_connection(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = OFF;")
            conn.execute("DELETE FROM clip_sources WHERE id = ?", (source_id,))
            conn.commit()

        with self.assertRaises(clip_rendering.ClipRenderError) as ctx:
            clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)
        self.assertIn("associada ao segmento não encontrada", str(ctx.exception))

    # 3. source não READY rejeita
    def test_03_source_nao_ready_rejeita(self):
        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)
        clip_mode.deactivate_clip_source(source_id, db_path=self.db_path)

        with self.assertRaises(clip_rendering.ClipRenderError) as ctx:
            clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)
        self.assertIn("não está no estado READY", str(ctx.exception))

    # 4. source sem autorização rejeita
    def test_04_source_sem_autorizacao_rejeita(self):
        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)
        with clip_mode.get_connection(self.db_path) as conn:
            conn.execute("UPDATE clip_sources SET authorization_confirmed = 0 WHERE id = ?", (source_id,))
            conn.commit()

        with self.assertRaises(clip_rendering.ClipRenderError) as ctx:
            clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)
        self.assertIn("não possui autorização legal confirmada", str(ctx.exception))

    # 5. segment inexistente rejeita
    def test_05_segment_inexistente_rejeita(self):
        with self.assertRaises(clip_rendering.ClipRenderError) as ctx:
            clip_rendering.render_clip_segment("nonexistent_segment_id", db_path=self.db_path)
        self.assertIn("não encontrado", str(ctx.exception))

    # 6. CANDIDATE não renderiza
    def test_06_candidate_nao_renderiza(self):
        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id, status="CANDIDATE")

        with self.assertRaises(clip_rendering.ClipRenderError) as ctx:
            clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)
        self.assertIn("status CANDIDATE não pode ser renderizado", str(ctx.exception))

    # 7. REJECTED não renderiza
    def test_07_rejected_nao_renderiza(self):
        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id, status="REJECTED")

        with self.assertRaises(clip_rendering.ClipRenderError) as ctx:
            clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)
        self.assertIn("status REJECTED não pode ser renderizado", str(ctx.exception))

    # 8. SELECTED aceita
    @patch("subprocess.run")
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_08_selected_aceita(self, mock_probe, mock_sub):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        mock_probe.return_value = dict(self.valid_rendered_probe)

        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id, status="SELECTED")

        render = clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)
        self.assertEqual(render["status"], clip_rendering.RENDER_STATUS_COMPLETED)
        self.assertTrue(os.path.exists(render["output_path"]))

    # 9. profile mismatch rejeita
    def test_09_profile_mismatch_rejeita(self):
        source_id = self._import_ready_source(profile_id="default")
        seg_id = self._create_segment(source_id, profile_id="default")

        with clip_mode.get_connection(self.db_path) as conn:
            conn.execute("UPDATE clip_segments SET profile_id = 'other_profile' WHERE id = ?", (seg_id,))
            conn.commit()

        with self.assertRaises(clip_rendering.ClipRenderError) as ctx:
            clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)
        self.assertIn("Inconsistência de profile_id", str(ctx.exception))

    # 10. SECONDARY bloqueado
    def test_10_secondary_bloqueado(self):
        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        with operator_console._instance_state_lock:
            operator_console._current_role = operator_console.ROLE_SECONDARY_VIEW_ONLY

        with self.assertRaises(PermissionError):
            clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)

    # 11. PRIMARY aceita
    @patch("subprocess.run")
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_11_primary_aceita(self, mock_probe, mock_sub):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        mock_probe.return_value = dict(self.valid_rendered_probe)

        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        with operator_console._instance_state_lock:
            operator_console._current_role = operator_console.ROLE_PRIMARY

        render = clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)
        self.assertEqual(render["status"], clip_rendering.RENDER_STATUS_COMPLETED)

    # 12. FIT_BLUR é default
    @patch("subprocess.run")
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_12_fit_blur_default(self, mock_probe, mock_sub):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        mock_probe.return_value = dict(self.valid_rendered_probe)

        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        render = clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)
        self.assertEqual(render["render_strategy"], clip_rendering.STRATEGY_FIT_BLUR)

        cmd_called = mock_sub.call_args[0][0]
        self.assertIn("boxblur=20:5", " ".join(cmd_called))

    # 13. CENTER_CROP aceita
    @patch("subprocess.run")
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_13_center_crop_aceita(self, mock_probe, mock_sub):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        mock_probe.return_value = dict(self.valid_rendered_probe)

        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        render = clip_rendering.render_clip_segment(seg_id, strategy="center_crop", db_path=self.db_path)
        self.assertEqual(render["render_strategy"], clip_rendering.STRATEGY_CENTER_CROP)

        cmd_called = mock_sub.call_args[0][0]
        cmd_str = " ".join(cmd_called)
        self.assertIn("crop=1080:1920", cmd_str)
        self.assertNotIn("boxblur", cmd_str)

    # 14. strategy inválida rejeita
    def test_14_strategy_invalida_rejeita(self):
        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        with self.assertRaises(clip_rendering.ClipRenderError) as ctx:
            clip_rendering.render_clip_segment(seg_id, strategy="invalid_strategy_xyz", db_path=self.db_path)
        self.assertIn("inválida", str(ctx.exception))

    # 15. start/end vêm do backend
    @patch("subprocess.run")
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_15_start_end_vem_do_backend(self, mock_probe, mock_sub):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        mock_probe.return_value = dict(self.valid_rendered_probe)

        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id, start=12.5, end=42.5)

        clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)
        cmd = mock_sub.call_args[0][0]
        ss_idx = cmd.index("-ss")
        self.assertEqual(cmd[ss_idx + 1], "12.500")

    # 16. duration backend calculated
    @patch("subprocess.run")
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_16_duration_backend_calculated(self, mock_probe, mock_sub):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        mock_probe.return_value = dict(self.valid_rendered_probe)

        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id, start=10.25, end=35.50)

        clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)
        cmd = mock_sub.call_args[0][0]
        t_idx = cmd.index("-t")
        expected_dur = f"{(35.50 - 10.25):.3f}"
        self.assertEqual(cmd[t_idx + 1], expected_dur)

    # 17. FFmpeg shell=False
    @patch("subprocess.run")
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_17_ffmpeg_shell_false(self, mock_probe, mock_sub):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        mock_probe.return_value = dict(self.valid_rendered_probe)

        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)
        kwargs = mock_sub.call_args[1]
        self.assertFalse(kwargs.get("shell", True))

    # 18. argument list usada
    @patch("subprocess.run")
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_18_argument_list_usada(self, mock_probe, mock_sub):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        mock_probe.return_value = dict(self.valid_rendered_probe)

        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)
        args = mock_sub.call_args[0]
        self.assertIsInstance(args[0], list)

    # 19. timeout configurado
    @patch("subprocess.run")
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_19_timeout_configurado(self, mock_probe, mock_sub):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        mock_probe.return_value = dict(self.valid_rendered_probe)

        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        clip_rendering.render_clip_segment(seg_id, timeout_seconds=240, db_path=self.db_path)
        kwargs = mock_sub.call_args[1]
        self.assertEqual(kwargs.get("timeout"), 240)

    # 20. output temp no diretório correto
    @patch("subprocess.run")
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_20_output_temp_diretorio_correto(self, mock_probe, mock_sub):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        mock_probe.return_value = dict(self.valid_rendered_probe)

        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        render = clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)
        cmd = mock_sub.call_args[0][0]
        temp_out = cmd[-1]
        self.assertTrue(temp_out.endswith(".tmp.mp4"))
        self.assertIn(os.path.join("clip_sources", source_id, "renders", render["id"]), temp_out)

    # 21. FFmpeg escreve em temp
    @patch("subprocess.run")
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_21_ffmpeg_escreve_em_temp(self, mock_probe, mock_sub):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        mock_probe.return_value = dict(self.valid_rendered_probe)

        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        render = clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)
        cmd = mock_sub.call_args[0][0]
        self.assertNotEqual(cmd[-1], render["output_path"])
        self.assertIn(".tmp.mp4", cmd[-1])

    # 22. sucesso promove atomicamente
    @patch("os.replace")
    @patch("subprocess.run")
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_22_sucesso_promove_atomicamente(self, mock_probe, mock_sub, mock_replace):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        mock_probe.return_value = dict(self.valid_rendered_probe)

        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        render = clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)
        self.assertTrue(mock_replace.called)
        self.assertEqual(render["status"], clip_rendering.RENDER_STATUS_COMPLETED)

    # 23. os.replace usado
    @patch("os.replace")
    @patch("subprocess.run")
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_23_os_replace_usado(self, mock_probe, mock_sub, mock_replace):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        mock_probe.return_value = dict(self.valid_rendered_probe)

        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        render = clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)
        self.assertTrue(mock_replace.called)
        src_path, dst_path = mock_replace.call_args[0]
        self.assertTrue(src_path.endswith(".tmp.mp4"))
        self.assertEqual(dst_path, render["output_path"])

    # 24. erro remove temp
    @patch("subprocess.run")
    def test_24_erro_remove_temp(self, mock_sub):
        def _err_run(cmd, *args, **kwargs):
            temp_out = cmd[-1]
            os.makedirs(os.path.dirname(temp_out), exist_ok=True)
            with open(temp_out, "wb") as f:
                f.write(b"ERR_DATA")
            res = MagicMock()
            res.returncode = 1
            res.stderr = "FFmpeg fatal error"
            return res

        mock_sub.side_effect = _err_run
        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        with self.assertRaises(clip_rendering.ClipRenderError):
            clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)

        temp_out = mock_sub.call_args[0][0][-1]
        self.assertFalse(os.path.exists(temp_out))

    # 25. timeout remove temp
    @patch("subprocess.run")
    def test_25_timeout_remove_temp(self, mock_sub):
        def _tout_run(cmd, *args, **kwargs):
            temp_out = cmd[-1]
            os.makedirs(os.path.dirname(temp_out), exist_ok=True)
            with open(temp_out, "wb") as f:
                f.write(b"TIMEOUT_DATA")
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 10))

        mock_sub.side_effect = _tout_run
        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        with self.assertRaises(subprocess.TimeoutExpired):
            clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)

        temp_out = mock_sub.call_args[0][0][-1]
        self.assertFalse(os.path.exists(temp_out))

    # 26. final parcial nunca criado
    @patch("subprocess.run")
    def test_26_final_parcial_nunca_criado(self, mock_sub):
        mock_sub.side_effect = subprocess.TimeoutExpired(cmd=[], timeout=5)
        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        with self.assertRaises(subprocess.TimeoutExpired):
            clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)

        renders = clip_rendering.list_clip_renders_for_segment(seg_id, db_path=self.db_path)
        self.assertEqual(len(renders), 1)
        final_file = renders[0]["output_path"]
        self.assertFalse(os.path.exists(final_file))

    # 27. output width 1080
    @patch("subprocess.run")
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_27_output_width_1080(self, mock_probe, mock_sub):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        mock_probe.return_value = {"width": 720, "height": 1920, "duration_seconds": 30.0, "has_audio": True}
        with self.assertRaises(clip_rendering.ClipRenderError) as ctx:
            clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)
        self.assertIn("Resolução inválida", str(ctx.exception))

    # 28. output height 1920
    @patch("subprocess.run")
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_28_output_height_1920(self, mock_probe, mock_sub):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        mock_probe.return_value = {"width": 1080, "height": 1080, "duration_seconds": 30.0, "has_audio": True}
        with self.assertRaises(clip_rendering.ClipRenderError) as ctx:
            clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)
        self.assertIn("Resolução inválida", str(ctx.exception))

    # 29. output duration válida
    @patch("subprocess.run")
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_29_output_duration_valida(self, mock_probe, mock_sub):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        mock_probe.return_value = {"width": 1080, "height": 1920, "duration_seconds": 0.0, "has_audio": True}
        with self.assertRaises(clip_rendering.ClipRenderError) as ctx:
            clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)
        self.assertIn("Duração inválida", str(ctx.exception))

    # 30. video stream obrigatório
    @patch("subprocess.run")
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_30_video_stream_obrigatorio(self, mock_probe, mock_sub):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        mock_probe.side_effect = clip_mode.ClipValidationError("Arquivo não contém stream de vídeo válido.")
        with self.assertRaises(clip_rendering.ClipRenderError) as ctx:
            clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)
        self.assertIn("Falha ao inspecionar", str(ctx.exception))

    # 31. source com áudio preserva áudio
    @patch("subprocess.run")
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_31_source_com_audio_preserva_audio(self, mock_probe, mock_sub):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        mock_probe.return_value = dict(self.valid_rendered_probe)

        source_id = self._import_ready_source(has_audio=True)
        seg_id = self._create_segment(source_id)

        clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)
        cmd = " ".join(mock_sub.call_args[0][0])
        self.assertIn("-c:a aac", cmd)
        self.assertIn("-b:a 192k", cmd)
        self.assertNotIn("-an", cmd)

    # 32. source sem áudio renderiza
    @patch("subprocess.run")
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_32_source_sem_audio_renderiza(self, mock_probe, mock_sub):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        probe_no_audio = dict(self.valid_rendered_probe)
        probe_no_audio["has_audio"] = False
        probe_no_audio["audio_codec"] = None
        mock_probe.return_value = probe_no_audio

        source_id = self._import_ready_source(has_audio=False)
        seg_id = self._create_segment(source_id)

        render = clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)
        self.assertEqual(render["status"], clip_rendering.RENDER_STATUS_COMPLETED)
        self.assertEqual(render["audio_codec"], "none")

        cmd = " ".join(mock_sub.call_args[0][0])
        self.assertIn("-an", cmd)
        self.assertNotIn("-c:a aac", cmd)

    # 33. no-audio warning correto
    def test_33_no_audio_warning_correto(self):
        source = {"has_audio": False, "width": 1920, "height": 1080}
        warns = clip_rendering.get_render_warnings(source, strategy="fit_blur")
        self.assertIn(clip_rendering.WARN_NO_AUDIO, warns)

    # 34. low-resolution warning
    def test_34_low_resolution_warning(self):
        source = {"has_audio": True, "width": 640, "height": 360}
        warns = clip_rendering.get_render_warnings(source, strategy="fit_blur")
        self.assertIn(clip_rendering.WARN_LOW_SOURCE_RESOLUTION, warns)

    # 35. center-crop warning
    def test_35_center_crop_warning(self):
        source = {"has_audio": True, "width": 1920, "height": 1080}
        warns = clip_rendering.get_render_warnings(source, strategy="center_crop")
        self.assertIn(clip_rendering.WARN_CENTER_CROP_MAY_CUT_SIDES, warns)

    # 36. completed render persistido
    @patch("subprocess.run")
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_36_completed_render_persistido(self, mock_probe, mock_sub):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        mock_probe.return_value = dict(self.valid_rendered_probe)

        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        rnd = clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)
        stored = clip_rendering.get_clip_render(rnd["id"], db_path=self.db_path)
        self.assertEqual(stored["status"], clip_rendering.RENDER_STATUS_COMPLETED)
        self.assertIsNotNone(stored["completed_at"])
        self.assertIsNotNone(stored["file_size_bytes"])

    # 37. FAILED render persistido
    @patch("subprocess.run")
    def test_37_failed_render_persistido(self, mock_sub):
        mock_sub.side_effect = subprocess.TimeoutExpired(cmd=[], timeout=5)
        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        with self.assertRaises(subprocess.TimeoutExpired):
            clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)

        renders = clip_rendering.list_clip_renders_for_segment(seg_id, db_path=self.db_path)
        self.assertEqual(len(renders), 1)
        self.assertEqual(renders[0]["status"], clip_rendering.RENDER_STATUS_FAILED)
        self.assertEqual(renders[0]["error_code"], "FFMPEG_TIMEOUT")

    # 38. failure não altera source
    @patch("subprocess.run")
    def test_38_failure_nao_altera_source(self, mock_sub):
        mock_sub.side_effect = subprocess.TimeoutExpired(cmd=[], timeout=5)
        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        with self.assertRaises(subprocess.TimeoutExpired):
            clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)

        src = clip_mode.get_clip_source(source_id, db_path=self.db_path)
        self.assertEqual(src["status"], clip_mode.SOURCE_STATUS_READY)

    # 39. failure não altera segment
    @patch("subprocess.run")
    def test_39_failure_nao_altera_segment(self, mock_sub):
        mock_sub.side_effect = subprocess.TimeoutExpired(cmd=[], timeout=5)
        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        with self.assertRaises(subprocess.TimeoutExpired):
            clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)

        seg = clip_mode.get_clip_segment(seg_id, db_path=self.db_path)
        self.assertEqual(seg["status"], clip_mode.SEGMENT_STATUS_SELECTED)

    # 40. fingerprint determinístico
    def test_40_fingerprint_deterministico(self):
        fp1 = clip_rendering.compute_render_fingerprint("hash_abc", "seg_01", 10.0, 40.0, "fit_blur")
        fp2 = clip_rendering.compute_render_fingerprint("hash_abc", "seg_01", 10.0, 40.0, "fit_blur")
        self.assertEqual(fp1, fp2)

    # 41. same config force=False reutiliza
    @patch("subprocess.run")
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_41_same_config_force_false_reutiliza(self, mock_probe, mock_sub):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        mock_probe.return_value = dict(self.valid_rendered_probe)

        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        rnd1 = clip_rendering.render_clip_segment(seg_id, force=False, db_path=self.db_path)
        rnd2 = clip_rendering.render_clip_segment(seg_id, force=False, db_path=self.db_path)
        self.assertEqual(rnd1["id"], rnd2["id"])
        self.assertEqual(mock_sub.call_count, 1)

    # 42. force=True cria histórico
    @patch("subprocess.run")
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_42_force_true_cria_historico(self, mock_probe, mock_sub):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        mock_probe.return_value = dict(self.valid_rendered_probe)

        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        rnd1 = clip_rendering.render_clip_segment(seg_id, force=False, db_path=self.db_path)
        rnd2 = clip_rendering.render_clip_segment(seg_id, force=True, db_path=self.db_path)
        self.assertNotEqual(rnd1["id"], rnd2["id"])
        self.assertEqual(mock_sub.call_count, 2)

    # 43. render antigo preservado
    @patch("subprocess.run")
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_43_render_antigo_preservado(self, mock_probe, mock_sub):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        mock_probe.return_value = dict(self.valid_rendered_probe)

        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        rnd1 = clip_rendering.render_clip_segment(seg_id, force=False, db_path=self.db_path)
        clip_rendering.render_clip_segment(seg_id, force=True, db_path=self.db_path)

        all_r = clip_rendering.list_clip_renders_for_segment(seg_id, db_path=self.db_path)
        self.assertEqual(len(all_r), 2)
        old = clip_rendering.get_clip_render(rnd1["id"], db_path=self.db_path)
        self.assertIsNotNone(old)
        self.assertEqual(old["status"], clip_rendering.RENDER_STATUS_COMPLETED)

    # 44. PROCESSING duplicado bloqueado
    def test_44_processing_duplicado_bloqueado(self):
        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        with clip_mode.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO clip_renders (
                    id, segment_id, source_id, profile_id, render_strategy,
                    width, height, fps, video_codec, audio_codec, output_path,
                    status, started_at, created_at, updated_at, source_sha256,
                    render_fingerprint
                ) VALUES (
                    'rend_active', ?, ?, 'default', 'fit_blur', 1080, 1920,
                    30.0, 'libx264', 'aac', 'some_path', 'PROCESSING',
                    '2026-09-18T00:00:00Z', '2026-09-18T00:00:00Z',
                    '2026-09-18T00:00:00Z', 'hash', 'fingerprint'
                )
                """,
                (seg_id, source_id),
            )
            conn.commit()

        with self.assertRaises(clip_rendering.DuplicateProcessingError):
            clip_rendering.render_clip_segment(seg_id, force=True, db_path=self.db_path)

    # 45. criação PROCESSING atômica
    def test_45_criacao_processing_atomica(self):
        self.assertTrue(hasattr(clip_rendering, "_render_creation_lock"))
        self.assertIsInstance(clip_rendering._render_creation_lock, type(threading.Lock()))

    # 46. FFmpeg fora da transação
    @patch("subprocess.run")
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_46_ffmpeg_fora_da_transacao(self, mock_probe, mock_sub):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        mock_probe.return_value = dict(self.valid_rendered_probe)

        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        def _check_db_not_locked(cmd, *args, **kwargs):
            # Enquanto FFmpeg está rodando, outro cursor pode ler a tabela normalmente
            with clip_mode.get_connection(self.db_path) as conn:
                row = conn.execute("SELECT status FROM clip_renders WHERE segment_id = ?", (seg_id,)).fetchone()
                self.assertEqual(row["status"], clip_rendering.RENDER_STATUS_PROCESSING)
            return self._fake_ffmpeg_run_success(cmd, *args, **kwargs)

        mock_sub.side_effect = _check_db_not_locked
        clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)

    # 47. render path contido
    def test_47_render_path_contido(self):
        base_dir = os.path.join(self.tmp_dir.name, "target_render_dir")
        os.makedirs(base_dir, exist_ok=True)
        outside_file = os.path.join(self.tmp_dir.name, "outside.mp4")
        with open(outside_file, "wb") as f:
            f.write(b"OUTSIDE_DATA")
        with self.assertRaises(clip_rendering.ClipRenderError) as ctx:
            clip_rendering.validate_rendered_output(outside_file, 30.0, True, expected_dir=base_dir)
        self.assertIn("viola limites de isolamento", str(ctx.exception))

    # 48. symlink output rejeitado
    def test_48_symlink_output_rejeitado(self):
        base_dir = os.path.join(self.tmp_dir.name, "target_render_dir")
        os.makedirs(base_dir, exist_ok=True)
        valid_file = os.path.join(base_dir, "valid.mp4")
        with open(valid_file, "wb") as f:
            f.write(b"SOME_BYTES")
        with patch("os.path.islink", return_value=True):
            with self.assertRaises(clip_rendering.ClipRenderError) as ctx:
                clip_rendering.validate_rendered_output(valid_file, 30.0, True, expected_dir=base_dir)
            self.assertIn("link simbólico", str(ctx.exception))

    # 49. empty output rejeitado
    def test_49_empty_output_rejeitado(self):
        base_dir = os.path.join(self.tmp_dir.name, "target_render_dir")
        os.makedirs(base_dir, exist_ok=True)
        empty_file = os.path.join(base_dir, "empty.mp4")
        with open(empty_file, "wb") as f:
            pass
        with self.assertRaises(clip_rendering.ClipRenderError) as ctx:
            clip_rendering.validate_rendered_output(empty_file, 30.0, True, expected_dir=base_dir)
        self.assertIn("vazio (0 bytes)", str(ctx.exception))

    # 50. invalid probe rejeitado
    def test_50_invalid_probe_rejeitado(self):
        base_dir = os.path.join(self.tmp_dir.name, "target_render_dir")
        os.makedirs(base_dir, exist_ok=True)
        probe_file = os.path.join(base_dir, "probe_target.mp4")
        with open(probe_file, "wb") as f:
            f.write(b"DATA")
        with patch("app.services.clip_mode.probe_video_metadata", side_effect=Exception("Corrupted container")):
            with self.assertRaises(clip_rendering.ClipRenderError) as ctx:
                clip_rendering.validate_rendered_output(probe_file, 30.0, True, expected_dir=base_dir)
            self.assertIn("Falha ao inspecionar", str(ctx.exception))

    # 51. source_sha256 preservado
    @patch("subprocess.run")
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_51_source_sha256_preservado(self, mock_probe, mock_sub):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        mock_probe.return_value = dict(self.valid_rendered_probe)

        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        render = clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)
        src = clip_mode.get_clip_source(source_id, db_path=self.db_path)
        self.assertEqual(render["source_sha256"], src["sha256"])

    # 52. profile preservado
    @patch("subprocess.run")
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_52_profile_preservado(self, mock_probe, mock_sub):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        mock_probe.return_value = dict(self.valid_rendered_probe)

        source_id = self._import_ready_source(profile_id="default")
        seg_id = self._create_segment(source_id, profile_id="default")

        render = clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)
        self.assertEqual(render["profile_id"], "default")

    # 53. segment_id preservado
    @patch("subprocess.run")
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_53_segment_id_preservado(self, mock_probe, mock_sub):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        mock_probe.return_value = dict(self.valid_rendered_probe)

        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)

        render = clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)
        self.assertEqual(render["segment_id"], seg_id)

    # 54. UI read zero FFmpeg
    @patch("subprocess.run")
    def test_54_ui_read_zero_ffmpeg(self, mock_sub):
        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)
        operator_console.list_clip_renders_for_segment_op(seg_id, db_path=self.db_path)
        self.assertEqual(mock_sub.call_count, 0)

    # 55. UI read zero render
    @patch("app.services.clip_rendering.render_clip_segment")
    def test_55_ui_read_zero_render(self, mock_render):
        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)
        operator_console.get_latest_completed_render_op(seg_id, db_path=self.db_path)
        self.assertEqual(mock_render.call_count, 0)

    # 56. zero HTTP
    @patch("subprocess.run")
    @patch("urllib.request.urlopen")
    def test_56_zero_http(self, mock_http, mock_sub):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        with patch("app.services.clip_mode.probe_video_metadata", return_value=dict(self.valid_rendered_probe)):
            source_id = self._import_ready_source()
            seg_id = self._create_segment(source_id)
            clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)
        self.assertEqual(mock_http.call_count, 0)

    # 57. zero publication
    @patch("subprocess.run")
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_57_zero_publication(self, mock_probe, mock_sub):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        mock_probe.return_value = dict(self.valid_rendered_probe)

        source_id = self._import_ready_source()
        seg_id = self._create_segment(source_id)
        clip_rendering.render_clip_segment(seg_id, db_path=self.db_path)

        with clip_mode.get_connection(self.db_path) as conn:
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='publication_events';")
            if cur.fetchone():
                pubs = conn.execute("SELECT COUNT(*) as c FROM publication_events;").fetchone()["c"]
                self.assertEqual(pubs, 0)

    # 58. manual segments SELECTED renderizam normalmente
    @patch("subprocess.run")
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_58_manual_segments_selected_renderizam_normalmente(self, mock_probe, mock_sub):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        mock_probe.return_value = dict(self.valid_rendered_probe)

        source_id = self._import_ready_source()
        manual_seg = self._create_segment(source_id, status="SELECTED", method="manual")
        rnd = clip_rendering.render_clip_segment(manual_seg, db_path=self.db_path)
        self.assertEqual(rnd["status"], clip_rendering.RENDER_STATUS_COMPLETED)

    # 59. heuristic SELECTED renderizam normalmente
    @patch("subprocess.run")
    @patch("app.services.clip_mode.probe_video_metadata")
    def test_59_heuristic_selected_renderizam_normalmente(self, mock_probe, mock_sub):
        mock_sub.side_effect = self._fake_ffmpeg_run_success
        mock_probe.return_value = dict(self.valid_rendered_probe)

        source_id = self._import_ready_source()
        heur_seg = self._create_segment(source_id, status="SELECTED", method="heuristic")
        rnd = clip_rendering.render_clip_segment(heur_seg, db_path=self.db_path)
        self.assertEqual(rnd["status"], clip_rendering.RENDER_STATUS_COMPLETED)

    # 60. REJECTED heuristic não renderiza
    def test_60_rejected_heuristic_nao_renderiza(self):
        source_id = self._import_ready_source()
        heur_rej = self._create_segment(source_id, status="REJECTED", method="heuristic")
        with self.assertRaises(clip_rendering.ClipRenderError):
            clip_rendering.render_clip_segment(heur_rej, db_path=self.db_path)


if __name__ == "__main__":
    unittest.main()
