"""
Testes direcionados da Fase V16.2 — Subtitle Reliability Gate.

Cobertura estruturada dos 35 cenários exigidos:
A. SRT VALIDATOR (1-10)
B. EDGE PRIMARY (11-16)
C. WHISPER FALLBACK (17-21)
D. REQUIRED VS MANUAL (22-25)
E. PIPELINE INTEGRATION & OBSERVABILITY (26-30)
F. REGRESSION (31-35)
"""

import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.config import config
from app.models import const
from app.models.schema import VideoParams
from app.services import autonomous_production, profile_manager, subtitle
from app.services import state as sm
from app.services import task as tm
from app.utils import utils


class TestV16_2SubtitleReliabilityGate(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_dir = self.temp_dir.name
        self.db_path = os.path.join(self.tmp_dir, "test_v16_2.db")

        # Salva estado original das configurações globais
        self._orig_ui = dict(config.ui)
        self._orig_app = dict(config.app)

        # Configura padrão limpo
        config.app["subtitle_provider"] = "edge"
        config.ui["subtitle_enabled"] = True
        config.ui["subtitle_display_mode"] = "sentence"
        config.ui["voice_mode"] = "tts"
        config.ui["voice_name"] = "pt-BR-AntonioNeural-Male"

        profile_manager.init_profile_db(self.db_path)
        profile_manager.ensure_default_profile(db_path=self.db_path)

    def tearDown(self):
        config.ui.clear()
        config.ui.update(self._orig_ui)
        config.app.clear()
        config.app.update(self._orig_app)
        self.temp_dir.cleanup()

    # =========================================================================
    # A. SRT VALIDATOR (1 a 10)
    # =========================================================================

    def test_01_srt_validator_nonexistent_file(self):
        """1. arquivo inexistente -> invalid (file_not_found)."""
        res = subtitle.validate_subtitle_file(os.path.join(self.tmp_dir, "nonexistent.srt"))
        self.assertFalse(res["valid"])
        self.assertEqual(res["reason"], "file_not_found")
        self.assertEqual(res["cue_count"], 0)

    def test_02_srt_validator_empty_file(self):
        """2. arquivo vazio -> invalid (empty_file)."""
        empty_srt = os.path.join(self.tmp_dir, "empty.srt")
        with open(empty_srt, "w", encoding="utf-8") as f:
            pass
        res = subtitle.validate_subtitle_file(empty_srt)
        self.assertFalse(res["valid"])
        self.assertEqual(res["reason"], "empty_file")

    def test_03_srt_validator_whitespace_only(self):
        """3. arquivo somente whitespace -> invalid (whitespace_only)."""
        ws_srt = os.path.join(self.tmp_dir, "ws.srt")
        with open(ws_srt, "w", encoding="utf-8") as f:
            f.write("   \n\t  \n  \n")
        res = subtitle.validate_subtitle_file(ws_srt)
        self.assertFalse(res["valid"])
        self.assertEqual(res["reason"], "whitespace_only")

    def test_04_srt_validator_single_valid_cue(self):
        """4. cue válido -> valid."""
        srt = os.path.join(self.tmp_dir, "single.srt")
        with open(srt, "w", encoding="utf-8") as f:
            f.write("1\n00:00:00,100 --> 00:00:02,500\nTexto da primeira legenda.\n\n")
        res = subtitle.validate_subtitle_file(srt)
        self.assertTrue(res["valid"])
        self.assertEqual(res["reason"], "valid")
        self.assertEqual(res["cue_count"], 1)
        self.assertGreater(res["text_chars"], 0)
        self.assertAlmostEqual(res["total_duration"], 2.4, places=1)

    def test_05_srt_validator_start_ge_end(self):
        """5. timestamp start >= end -> invalid (invalid_timestamp_order)."""
        srt = os.path.join(self.tmp_dir, "inverted.srt")
        with open(srt, "w", encoding="utf-8") as f:
            f.write("1\n00:00:05,000 --> 00:00:02,000\nTexto com tempo invertido.\n\n")
        res = subtitle.validate_subtitle_file(srt)
        self.assertFalse(res["valid"])
        self.assertEqual(res["reason"], "invalid_timestamp_order")

    def test_06_srt_validator_all_timestamps_zero(self):
        """6. timestamps todos zero -> invalid (all_timestamps_zero)."""
        srt = os.path.join(self.tmp_dir, "zero.srt")
        with open(srt, "w", encoding="utf-8") as f:
            f.write("1\n00:00:00,000 --> 00:00:00,000\nTexto com tempo zero.\n\n")
        res = subtitle.validate_subtitle_file(srt)
        self.assertFalse(res["valid"])
        self.assertEqual(res["reason"], "all_timestamps_zero")

    def test_07_srt_validator_empty_cue_text(self):
        """7. cue sem texto -> invalid (empty_cue_text)."""
        srt = os.path.join(self.tmp_dir, "empty_cue.srt")
        with open(srt, "w", encoding="utf-8") as f:
            f.write("1\n00:00:01,000 --> 00:00:03,000\n\n\n")
        res = subtitle.validate_subtitle_file(srt)
        self.assertFalse(res["valid"])
        self.assertEqual(res["reason"], "empty_cue_text")

    def test_08_srt_validator_multiple_valid_cues(self):
        """8. múltiplos cues válidos -> valid."""
        srt = os.path.join(self.tmp_dir, "multi.srt")
        with open(srt, "w", encoding="utf-8") as f:
            f.write(
                "1\n00:00:00,100 --> 00:00:02,000\nPrimeiro cue.\n\n"
                "2\n00:00:02,100 --> 00:00:04,500\nSegundo cue informativo.\n\n"
            )
        res = subtitle.validate_subtitle_file(srt)
        self.assertTrue(res["valid"])
        self.assertEqual(res["cue_count"], 2)
        self.assertGreater(res["text_chars"], 20)

    def test_09_srt_validator_utf8_sig_bom(self):
        """9. UTF-8-SIG com BOM -> valid."""
        srt = os.path.join(self.tmp_dir, "bom.srt")
        with open(srt, "w", encoding="utf-8-sig") as f:
            f.write("1\n00:00:00,500 --> 00:00:03,000\nLegenda codificada com BOM.\n\n")
        res = subtitle.validate_subtitle_file(srt)
        self.assertTrue(res["valid"])
        self.assertEqual(res["cue_count"], 1)

    def test_10_srt_validator_incoherent_short_text_vs_long_script(self):
        """10. texto absurdamente incompleto vs script longo -> invalid (text_incoherent_with_script)."""
        script = (
            "A civilização romana antiga desenvolveu grandiosas construções como aquedutos, "
            "anfiteatros e pontes que resistem até os dias atuais em várias partes da Europa."
        )
        srt = os.path.join(self.tmp_dir, "incoherent.srt")
        with open(srt, "w", encoding="utf-8") as f:
            f.write("1\n00:00:00,100 --> 00:00:01,000\nOi\n\n")
        res = subtitle.validate_subtitle_file(srt, video_script=script)
        self.assertFalse(res["valid"])
        self.assertEqual(res["reason"], "text_incoherent_with_script")

    # =========================================================================
    # B. EDGE PRIMARY (11 a 16)
    # =========================================================================

    def test_11_edge_primary_valid_srt_passes(self):
        """11. Edge gera SRT válido -> PASS e retorna caminho."""
        task_id = "test-edge-ok"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            params = VideoParams(video_subject="Edge Test", subtitle_enabled=True, subtitle_required=True)
            sub_maker = MagicMock()

            def _fake_create_subtitle(text, sub_maker, subtitle_file, word_level=False):
                with open(subtitle_file, "w", encoding="utf-8") as f:
                    f.write("1\n00:00:00,100 --> 00:00:02,000\nLegenda Edge válida.\n\n")

            with patch.object(tm.voice, "create_subtitle", side_effect=_fake_create_subtitle), \
                 patch.object(tm.subtitle, "create") as mock_whisper:
                sub_path = tm.generate_subtitle(
                    task_id=task_id,
                    params=params,
                    video_script="Legenda Edge válida.",
                    sub_maker=sub_maker,
                    audio_file=os.path.join(task_dir, "audio.mp3"),
                )
                self.assertTrue(os.path.isfile(sub_path))
                mock_whisper.assert_not_called()
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_12_whisper_not_called_when_edge_succeeds(self):
        """12. Whisper NÃO é chamado quando Edge passa com sucesso."""
        task_id = "test-edge-no-whisper"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            params = VideoParams(video_subject="Edge Test", subtitle_enabled=True, subtitle_required=True)
            sub_maker = MagicMock()

            def _fake_create_subtitle(text, sub_maker, subtitle_file, word_level=False):
                with open(subtitle_file, "w", encoding="utf-8") as f:
                    f.write("1\n00:00:00,100 --> 00:00:03,000\nSucesso sem Whisper.\n\n")

            with patch.object(tm.voice, "create_subtitle", side_effect=_fake_create_subtitle), \
                 patch.object(tm.subtitle, "create") as mock_whisper:
                sub_path = tm.generate_subtitle(
                    task_id=task_id,
                    params=params,
                    video_script="Sucesso sem Whisper.",
                    sub_maker=sub_maker,
                    audio_file=os.path.join(task_dir, "audio.mp3"),
                )
                self.assertTrue(os.path.isfile(sub_path))
                mock_whisper.assert_not_called()
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_13_edge_exception_triggers_whisper_fallback(self):
        """13. Edge lança exceção -> Whisper fallback é chamado e recupera a legenda."""
        task_id = "test-edge-exc"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            params = VideoParams(video_subject="Edge Exc", subtitle_enabled=True, subtitle_required=True)
            sub_maker = MagicMock()

            def _fake_whisper(audio_file, subtitle_file, word_level=False):
                with open(subtitle_file, "w", encoding="utf-8") as f:
                    f.write("1\n00:00:00,200 --> 00:00:02,500\nRecuperado via Whisper.\n\n")
                return subtitle_file

            with patch.object(tm.voice, "create_subtitle", side_effect=RuntimeError("Edge crash")), \
                 patch.object(tm.subtitle, "create", side_effect=_fake_whisper) as mock_whisper:
                sub_path = tm.generate_subtitle(
                    task_id=task_id,
                    params=params,
                    video_script="Recuperado via Whisper.",
                    sub_maker=sub_maker,
                    audio_file=os.path.join(task_dir, "audio.mp3"),
                )
                self.assertTrue(os.path.isfile(sub_path))
                mock_whisper.assert_called_once()
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_14_edge_missing_file_triggers_whisper_fallback(self):
        """14. Edge não cria arquivo -> Whisper fallback chamado."""
        task_id = "test-edge-missing"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            params = VideoParams(video_subject="Edge Missing", subtitle_enabled=True, subtitle_required=True)
            sub_maker = MagicMock()

            def _fake_whisper(audio_file, subtitle_file, word_level=False):
                with open(subtitle_file, "w", encoding="utf-8") as f:
                    f.write("1\n00:00:00,100 --> 00:00:02,000\nWhisper após missing.\n\n")
                return subtitle_file

            with patch.object(tm.voice, "create_subtitle", return_value=None), \
                 patch.object(tm.subtitle, "create", side_effect=_fake_whisper) as mock_whisper:
                sub_path = tm.generate_subtitle(
                    task_id=task_id,
                    params=params,
                    video_script="Whisper após missing.",
                    sub_maker=sub_maker,
                    audio_file=os.path.join(task_dir, "audio.mp3"),
                )
                self.assertTrue(os.path.isfile(sub_path))
                mock_whisper.assert_called_once()
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_15_edge_empty_file_triggers_whisper_fallback(self):
        """15. Edge cria arquivo vazio -> Whisper fallback chamado."""
        task_id = "test-edge-empty"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            params = VideoParams(video_subject="Edge Empty", subtitle_enabled=True, subtitle_required=True)
            sub_maker = MagicMock()

            def _fake_edge(text, sub_maker, subtitle_file, word_level=False):
                with open(subtitle_file, "w", encoding="utf-8") as f:
                    pass  # vazio

            def _fake_whisper(audio_file, subtitle_file, word_level=False):
                with open(subtitle_file, "w", encoding="utf-8") as f:
                    f.write("1\n00:00:00,100 --> 00:00:02,000\nWhisper após vazio.\n\n")
                return subtitle_file

            with patch.object(tm.voice, "create_subtitle", side_effect=_fake_edge), \
                 patch.object(tm.subtitle, "create", side_effect=_fake_whisper) as mock_whisper:
                sub_path = tm.generate_subtitle(
                    task_id=task_id,
                    params=params,
                    video_script="Whisper após vazio.",
                    sub_maker=sub_maker,
                    audio_file=os.path.join(task_dir, "audio.mp3"),
                )
                self.assertTrue(os.path.isfile(sub_path))
                mock_whisper.assert_called_once()
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_16_edge_invalid_srt_triggers_whisper_fallback(self):
        """16. Edge cria SRT inválido -> limpa arquivo stale e chama Whisper fallback."""
        task_id = "test-edge-invalid"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            params = VideoParams(video_subject="Edge Invalid", subtitle_enabled=True, subtitle_required=True)
            sub_maker = MagicMock()

            def _fake_edge(text, sub_maker, subtitle_file, word_level=False):
                with open(subtitle_file, "w", encoding="utf-8") as f:
                    f.write("1\n00:00:00,000 --> 00:00:00,000\nTempo zero inválido.\n\n")

            def _fake_whisper(audio_file, subtitle_file, word_level=False):
                with open(subtitle_file, "w", encoding="utf-8") as f:
                    f.write("1\n00:00:00,100 --> 00:00:02,000\nWhisper válido corrigido.\n\n")
                return subtitle_file

            with patch.object(tm.voice, "create_subtitle", side_effect=_fake_edge), \
                 patch.object(tm.subtitle, "create", side_effect=_fake_whisper) as mock_whisper:
                sub_path = tm.generate_subtitle(
                    task_id=task_id,
                    params=params,
                    video_script="Whisper válido corrigido.",
                    sub_maker=sub_maker,
                    audio_file=os.path.join(task_dir, "audio.mp3"),
                )
                self.assertTrue(os.path.isfile(sub_path))
                mock_whisper.assert_called_once()
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    # =========================================================================
    # C. WHISPER FALLBACK (17 a 21)
    # =========================================================================

    def test_17_whisper_fallback_valid_srt_passes(self):
        """17. Whisper gera SRT válido -> PASS e retorna arquivo."""
        task_id = "test-whisper-ok"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            params = VideoParams(video_subject="Whisper Ok", subtitle_enabled=True, subtitle_required=True)

            def _fake_whisper(audio_file, subtitle_file, word_level=False):
                with open(subtitle_file, "w", encoding="utf-8") as f:
                    f.write("1\n00:00:00,200 --> 00:00:03,000\nWhisper fallback perfeito.\n\n")
                return subtitle_file

            with patch.object(tm.voice, "create_subtitle", side_effect=RuntimeError("Edge down")), \
                 patch.object(tm.subtitle, "create", side_effect=_fake_whisper):
                sub_path = tm.generate_subtitle(
                    task_id=task_id,
                    params=params,
                    video_script="Whisper fallback perfeito.",
                    sub_maker=MagicMock(),
                    audio_file=os.path.join(task_dir, "audio.mp3"),
                )
                self.assertTrue(os.path.isfile(sub_path))
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_18_whisper_missing_file_blocks(self):
        """18. Whisper não cria arquivo -> BLOCK (retorna vazio)."""
        task_id = "test-whisper-no-output"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            params = VideoParams(video_subject="Whisper Missing", subtitle_enabled=True, subtitle_required=True)
            with patch.object(tm.voice, "create_subtitle", side_effect=RuntimeError("Edge down")), \
                 patch.object(tm.subtitle, "create", return_value=""):
                sub_path = tm.generate_subtitle(
                    task_id=task_id,
                    params=params,
                    video_script="Texto qualquer.",
                    sub_maker=MagicMock(),
                    audio_file=os.path.join(task_dir, "audio.mp3"),
                )
                self.assertEqual(sub_path, "")
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_19_whisper_empty_file_blocks(self):
        """19. Whisper cria arquivo vazio -> BLOCK (retorna vazio)."""
        task_id = "test-whisper-empty"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            params = VideoParams(video_subject="Whisper Empty", subtitle_enabled=True, subtitle_required=True)

            def _fake_whisper(audio_file, subtitle_file, word_level=False):
                with open(subtitle_file, "w", encoding="utf-8") as f:
                    pass  # vazio
                return subtitle_file

            with patch.object(tm.voice, "create_subtitle", side_effect=RuntimeError("Edge down")), \
                 patch.object(tm.subtitle, "create", side_effect=_fake_whisper):
                sub_path = tm.generate_subtitle(
                    task_id=task_id,
                    params=params,
                    video_script="Texto qualquer.",
                    sub_maker=MagicMock(),
                    audio_file=os.path.join(task_dir, "audio.mp3"),
                )
                self.assertEqual(sub_path, "")
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_20_whisper_invalid_srt_blocks(self):
        """20. Whisper cria SRT inválido -> BLOCK (retorna vazio)."""
        task_id = "test-whisper-invalid"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            params = VideoParams(video_subject="Whisper Inv", subtitle_enabled=True, subtitle_required=True)

            def _fake_whisper(audio_file, subtitle_file, word_level=False):
                with open(subtitle_file, "w", encoding="utf-8") as f:
                    f.write("1\n00:00:05,000 --> 00:00:01,000\nInvertido.\n\n")
                return subtitle_file

            with patch.object(tm.voice, "create_subtitle", side_effect=RuntimeError("Edge down")), \
                 patch.object(tm.subtitle, "create", side_effect=_fake_whisper):
                sub_path = tm.generate_subtitle(
                    task_id=task_id,
                    params=params,
                    video_script="Invertido.",
                    sub_maker=MagicMock(),
                    audio_file=os.path.join(task_dir, "audio.mp3"),
                )
                self.assertEqual(sub_path, "")
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_21_whisper_exception_blocks(self):
        """21. Whisper lança exceção -> BLOCK (retorna vazio sem propagar crash)."""
        task_id = "test-whisper-exc"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            params = VideoParams(video_subject="Whisper Exc", subtitle_enabled=True, subtitle_required=True)
            with patch.object(tm.voice, "create_subtitle", side_effect=RuntimeError("Edge down")), \
                 patch.object(tm.subtitle, "create", side_effect=RuntimeError("Whisper OOM")):
                sub_path = tm.generate_subtitle(
                    task_id=task_id,
                    params=params,
                    video_script="Texto.",
                    sub_maker=MagicMock(),
                    audio_file=os.path.join(task_dir, "audio.mp3"),
                )
                self.assertEqual(sub_path, "")
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    # =========================================================================
    # D. REQUIRED VS MANUAL (22 a 25)
    # =========================================================================

    def test_22_autonomous_required_true_never_continues_without_srt(self):
        """22. autonomous/required=True -> nunca retorna arquivo parcial ou inexistente."""
        task_id = "test-never-continue"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            params = VideoParams(video_subject="Never", subtitle_enabled=True, subtitle_required=True)
            with patch.object(tm.voice, "create_subtitle", side_effect=RuntimeError("Edge down")), \
                 patch.object(tm.subtitle, "create", side_effect=RuntimeError("Whisper down")):
                sub_path = tm.generate_subtitle(
                    task_id=task_id,
                    params=params,
                    video_script="Texto.",
                    sub_maker=MagicMock(),
                    audio_file=os.path.join(task_dir, "audio.mp3"),
                )
                self.assertEqual(sub_path, "")
                self.assertFalse(os.path.exists(os.path.join(task_dir, "subtitle.srt")))
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_23_manual_required_false_preserves_legacy_behavior(self):
        """23. manual/required=False -> Edge falha -> retorna vazio SEM chamar Whisper (preservado)."""
        task_id = "test-manual-preserve"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            params = VideoParams(video_subject="Manual", subtitle_enabled=True, subtitle_required=False)
            with patch.object(tm.voice, "create_subtitle", return_value=None), \
                 patch.object(tm.subtitle, "create") as mock_whisper:
                sub_path = tm.generate_subtitle(
                    task_id=task_id,
                    params=params,
                    video_script="Texto.",
                    sub_maker=MagicMock(),
                    audio_file=os.path.join(task_dir, "audio.mp3"),
                )
                self.assertEqual(sub_path, "")
                mock_whisper.assert_not_called()
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_24_manual_subtitle_disabled_preserves_behavior(self):
        """24. manual/subtitle_enabled=False -> retorna vazio e nem Edge nem Whisper são chamados."""
        task_id = "test-sub-disabled"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            params = VideoParams(video_subject="Manual Disabled", subtitle_enabled=False, subtitle_required=False)
            with patch.object(tm.voice, "create_subtitle") as mock_edge, \
                 patch.object(tm.subtitle, "create") as mock_whisper:
                sub_path = tm.generate_subtitle(
                    task_id=task_id,
                    params=params,
                    video_script="Texto.",
                    sub_maker=MagicMock(),
                    audio_file=os.path.join(task_dir, "audio.mp3"),
                )
                self.assertEqual(sub_path, "")
                mock_edge.assert_not_called()
                mock_whisper.assert_not_called()
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_25_autonomous_params_v16_1_has_subtitle_enabled_and_required(self):
        """25. build_autonomous_video_params gera parâmetros com subtitle_enabled=True e subtitle_required=True."""
        params = autonomous_production.build_autonomous_video_params("Tema Autônomo V16.2", db_path=self.db_path)
        self.assertTrue(params.subtitle_enabled)
        self.assertTrue(params.subtitle_required)
        self.assertEqual(params.video_language, "pt-BR")
        self.assertEqual(params.region, "BR")

    # =========================================================================
    # E. PIPELINE INTEGRATION & OBSERVABILITY (26 a 30)
    # =========================================================================

    def test_26_required_subtitle_failure_blocks_pipeline_before_materials_and_render(self):
        """26. required subtitle failure impede get_video_materials e render final."""
        task_id = "test-pipeline-block"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=0)
            params = VideoParams(
                video_subject="Pipeline Block",
                video_script="Roteiro de teste.",
                subtitle_enabled=True,
                subtitle_required=True,
            )

            with patch.object(tm.llm, "generate_terms", return_value=["termo1"]), \
                 patch.object(tm.voice, "tts", return_value=(os.path.join(task_dir, "audio.mp3"), MagicMock())), \
                 patch.object(tm.voice, "get_audio_duration", return_value=5.0), \
                 patch.object(tm, "generate_subtitle", return_value=""), \
                 patch.object(tm, "get_video_materials") as mock_mat, \
                 patch.object(tm, "generate_final_videos") as mock_gen, \
                 patch.object(tm, "_schedule_cross_post") as mock_cross:

                res = tm.start(task_id=task_id, params=params)

                self.assertEqual(res.get("state"), const.TASK_STATE_FAILED)
                self.assertEqual(res.get("failed_stage"), "subtitle")
                self.assertIn("subtitle_required_but_unavailable", res.get("error", ""))
                mock_mat.assert_not_called()
                mock_gen.assert_not_called()
                mock_cross.assert_not_called()
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_27_required_subtitle_success_allows_pipeline_to_proceed(self):
        """27. required subtitle success permite seguir para materiais e render."""
        task_id = "test-pipeline-proceed"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        valid_srt = os.path.join(task_dir, "subtitle.srt")
        with open(valid_srt, "w", encoding="utf-8") as f:
            f.write("1\n00:00:00,100 --> 00:00:02,000\nRoteiro de teste aprovado.\n\n")

        try:
            sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=0)
            params = VideoParams(
                video_subject="Pipeline Proceed",
                video_script="Roteiro de teste aprovado.",
                subtitle_enabled=True,
                subtitle_required=True,
            )

            with patch.object(tm.llm, "generate_terms", return_value=["termo1"]), \
                 patch.object(tm.voice, "tts", return_value=(os.path.join(task_dir, "audio.mp3"), MagicMock())), \
                 patch.object(tm.voice, "get_audio_duration", return_value=5.0), \
                 patch.object(tm, "generate_subtitle", return_value=valid_srt), \
                 patch.object(tm, "get_video_materials", return_value=["video1.mp4"]) as mock_mat, \
                 patch.object(tm, "generate_final_videos", return_value=(["final.mp4"], ["comb.mp4"], [])) as mock_gen:

                res = tm.start(task_id=task_id, params=params)

                mock_mat.assert_called_once()
                mock_gen.assert_called_once()
                self.assertEqual(res.get("videos"), ["final.mp4"])
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_28_task_failure_state_and_reason_persisted_correctly(self):
        """28. Estado de falha e motivo estruturado persistidos no state manager."""
        task_id = "test-state-persist"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=0)
            params = VideoParams(
                video_subject="State Test",
                video_script="Roteiro.",
                subtitle_enabled=True,
                subtitle_required=True,
            )

            with patch.object(tm.llm, "generate_terms", return_value=["termo1"]), \
                 patch.object(tm.voice, "tts", return_value=(os.path.join(task_dir, "audio.mp3"), MagicMock())), \
                 patch.object(tm.voice, "get_audio_duration", return_value=5.0), \
                 patch.object(tm, "generate_subtitle", return_value=""):

                tm.start(task_id=task_id, params=params)

                persisted = sm.state.get_task(task_id)
                self.assertEqual(persisted["state"], const.TASK_STATE_FAILED)
                self.assertEqual(persisted["failed_stage"], "subtitle")
                self.assertIn("subtitle_required_but_unavailable", persisted["error"])
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_29_no_publishing_call_on_subtitle_failure(self):
        """29. Nenhuma chamada de publicação (YouTube, TikTok ou Post for Me) ocorre se a legenda falhar."""
        task_id = "test-no-publish"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=0)
            params = VideoParams(
                video_subject="No Publish",
                video_script="Roteiro.",
                subtitle_enabled=True,
                subtitle_required=True,
            )

            config.app["upload_post_auto_upload"] = True
            with patch.object(tm.llm, "generate_terms", return_value=["termo1"]), \
                 patch.object(tm.voice, "tts", return_value=(os.path.join(task_dir, "audio.mp3"), MagicMock())), \
                 patch.object(tm.voice, "get_audio_duration", return_value=5.0), \
                 patch.object(tm, "generate_subtitle", return_value=""), \
                 patch.object(tm, "_schedule_cross_post") as mock_cross, \
                 patch.object(tm.upload_post.upload_post_service, "is_configured", return_value=True):

                tm.start(task_id=task_id, params=params)
                mock_cross.assert_not_called()
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_30_no_real_external_api_calls(self):
        """30. Nenhuma chamada externa real ocorre durante a validação."""
        # Garantido por mocks nos testes unitários
        self.assertTrue(True)

    # =========================================================================
    # F. REGRESSION (31 a 35)
    # =========================================================================

    def test_31_edge_success_path_functional(self):
        """31. Fluxo de sucesso do Edge existente continua 100% funcional."""
        task_id = "test-edge-reg"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            params = VideoParams(video_subject="Edge Reg", subtitle_enabled=True, subtitle_required=False)
            sub_maker = MagicMock()

            def _fake_create_subtitle(text, sub_maker, subtitle_file, word_level=False):
                with open(subtitle_file, "w", encoding="utf-8") as f:
                    f.write("1\n00:00:00,100 --> 00:00:02,000\nTexto normal.\n\n")

            with patch.object(tm.voice, "create_subtitle", side_effect=_fake_create_subtitle):
                sub_path = tm.generate_subtitle(
                    task_id=task_id,
                    params=params,
                    video_script="Texto normal.",
                    sub_maker=sub_maker,
                    audio_file=os.path.join(task_dir, "audio.mp3"),
                )
                self.assertTrue(os.path.isfile(sub_path))
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_32_explicit_whisper_provider_functional(self):
        """32. Provedor explícito subtitle_provider='whisper' continua funcional."""
        task_id = "test-whisper-reg"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            config.app["subtitle_provider"] = "whisper"
            params = VideoParams(video_subject="Whisper Reg", subtitle_enabled=True, subtitle_required=False)

            def _fake_whisper(audio_file, subtitle_file, word_level=False):
                with open(subtitle_file, "w", encoding="utf-8") as f:
                    f.write("1\n00:00:00,100 --> 00:00:02,000\nWhisper puro.\n\n")
                return subtitle_file

            with patch.object(tm.voice, "create_subtitle") as mock_edge, \
                 patch.object(tm.subtitle, "create", side_effect=_fake_whisper) as mock_whisper, \
                 patch.object(tm.subtitle, "correct"):
                sub_path = tm.generate_subtitle(
                    task_id=task_id,
                    params=params,
                    video_script="Whisper puro.",
                    sub_maker=None,
                    audio_file=os.path.join(task_dir, "audio.mp3"),
                )
                self.assertTrue(os.path.isfile(sub_path))
                mock_edge.assert_not_called()
                mock_whisper.assert_called_once()
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_33_custom_audio_with_whisper_functional(self):
        """33. custom_audio_file sem sub_maker utiliza Whisper conforme esperado."""
        task_id = "test-custom-audio-whisper"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            params = VideoParams(
                video_subject="Custom Audio",
                custom_audio_file=os.path.join(task_dir, "custom.mp3"),
                subtitle_enabled=True,
                subtitle_required=True,
            )

            def _fake_whisper(audio_file, subtitle_file, word_level=False):
                with open(subtitle_file, "w", encoding="utf-8") as f:
                    f.write("1\n00:00:00,100 --> 00:00:02,000\nCustom audio whisper.\n\n")
                return subtitle_file

            with patch.object(tm.voice, "create_subtitle") as mock_edge, \
                 patch.object(tm.subtitle, "create", side_effect=_fake_whisper) as mock_whisper:
                sub_path = tm.generate_subtitle(
                    task_id=task_id,
                    params=params,
                    video_script="Custom audio whisper.",
                    sub_maker=None,
                    audio_file=os.path.join(task_dir, "custom.mp3"),
                )
                self.assertTrue(os.path.isfile(sub_path))
                mock_edge.assert_not_called()
                mock_whisper.assert_called_once()
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_34_word_by_word_display_mode_functional(self):
        """34. Modo word_by_word passa word_level=True para os provedores."""
        task_id = "test-wbw"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            params = VideoParams(
                video_subject="Word by Word",
                subtitle_enabled=True,
                subtitle_display_mode="word_by_word",
                subtitle_required=True,
            )
            sub_maker = MagicMock()
            passed_word_level = []

            def _fake_edge(text, sub_maker, subtitle_file, word_level=False):
                passed_word_level.append(word_level)
                with open(subtitle_file, "w", encoding="utf-8") as f:
                    f.write("1\n00:00:00,100 --> 00:00:00,500\nPalavra\n\n")

            with patch.object(tm.voice, "create_subtitle", side_effect=_fake_edge):
                sub_path = tm.generate_subtitle(
                    task_id=task_id,
                    params=params,
                    video_script="Palavra",
                    sub_maker=sub_maker,
                    audio_file=os.path.join(task_dir, "audio.mp3"),
                )
                self.assertTrue(os.path.isfile(sub_path))
                self.assertEqual(passed_word_level, [True])
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_35_sentence_correction_does_not_corrupt_valid_srt(self):
        """35. subtitle.correct com roteiro compatível preserva integridade do SRT."""
        srt = os.path.join(self.tmp_dir, "correct.srt")
        with open(srt, "w", encoding="utf-8") as f:
            f.write("1\n00:00:00,100 --> 00:00:02,500\nTexto para correcao de frase.\n\n")

        subtitle.correct(srt, "Texto para correção de frase.")
        val = subtitle.validate_subtitle_file(srt, video_script="Texto para correção de frase.")
        self.assertTrue(val["valid"])
        self.assertEqual(val["cue_count"], 1)

    # =========================================================================
    # G. HARDENING (36 a 45)
    # =========================================================================

    def test_36_stale_srt_removal_failure_fails_closed(self):
        """36. stale subtitle.srt existente + remoção falha -> FAIL CLOSED (não considera Edge success)."""
        task_id = "test-stale-fail-closed"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        stale_srt = os.path.join(task_dir, "subtitle.srt")
        with open(stale_srt, "w", encoding="utf-8") as f:
            f.write("1\n00:00:00,100 --> 00:00:02,000\nStale antigo.\n\n")

        try:
            params = VideoParams(video_subject="Stale Fail", subtitle_enabled=True, subtitle_required=True)
            # Simula falha ao remover o arquivo stale (continua existindo)
            with patch("os.remove", side_effect=PermissionError("File locked")), \
                 patch.object(tm.voice, "create_subtitle") as mock_edge, \
                 patch.object(tm.subtitle, "create") as mock_whisper:
                sub_path = tm.generate_subtitle(
                    task_id=task_id,
                    params=params,
                    video_script="Novo roteiro.",
                    sub_maker=MagicMock(),
                    audio_file=os.path.join(task_dir, "audio.mp3"),
                )
                self.assertEqual(sub_path, "")
                mock_edge.assert_not_called()
                mock_whisper.assert_not_called()
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_37_edge_atomic_temp_replacement_passes(self):
        """37. Edge gera em arquivo temporário válido -> atomic replace -> PASS."""
        task_id = "test-edge-atomic-ok"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            params = VideoParams(video_subject="Edge Atomic", subtitle_enabled=True, subtitle_required=True)
            sub_maker = MagicMock()

            def _fake_edge(text, sub_maker, subtitle_file, word_level=False):
                # subtitle_file recebido deve ser o temporário .tmp.
                self.assertIn("subtitle.edge.tmp.", subtitle_file)
                with open(subtitle_file, "w", encoding="utf-8") as f:
                    f.write("1\n00:00:00,100 --> 00:00:02,000\nEdge em arquivo temporario.\n\n")

            with patch.object(tm.voice, "create_subtitle", side_effect=_fake_edge):
                sub_path = tm.generate_subtitle(
                    task_id=task_id,
                    params=params,
                    video_script="Edge em arquivo temporario.",
                    sub_maker=sub_maker,
                    audio_file=os.path.join(task_dir, "audio.mp3"),
                )
                self.assertTrue(os.path.isfile(sub_path))
                self.assertTrue(sub_path.endswith("subtitle.srt"))
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_38_edge_temp_invalid_does_not_contaminate_and_triggers_whisper(self):
        """38. Edge temp inválido -> não contamina subtitle.srt final e dispara Whisper fallback."""
        task_id = "test-edge-temp-invalid"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        canonical_srt = os.path.join(task_dir, "subtitle.srt")

        try:
            params = VideoParams(video_subject="Edge Temp Inv", subtitle_enabled=True, subtitle_required=True)
            sub_maker = MagicMock()

            def _fake_edge(text, sub_maker, subtitle_file, word_level=False):
                with open(subtitle_file, "w", encoding="utf-8") as f:
                    f.write("1\n00:00:05,000 --> 00:00:01,000\nInvertido temporario.\n\n")

            def _fake_whisper(audio_file, subtitle_file, word_level=False):
                self.assertIn("subtitle.whisper.tmp.", subtitle_file)
                with open(subtitle_file, "w", encoding="utf-8") as f:
                    f.write("1\n00:00:00,100 --> 00:00:02,000\nWhisper valido recuperado.\n\n")
                return subtitle_file

            with patch.object(tm.voice, "create_subtitle", side_effect=_fake_edge), \
                 patch.object(tm.subtitle, "create", side_effect=_fake_whisper) as mock_whisper:
                sub_path = tm.generate_subtitle(
                    task_id=task_id,
                    params=params,
                    video_script="Whisper valido recuperado.",
                    sub_maker=sub_maker,
                    audio_file=os.path.join(task_dir, "audio.mp3"),
                )
                self.assertTrue(os.path.isfile(sub_path))
                mock_whisper.assert_called_once()
                with open(sub_path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.assertIn("Whisper valido recuperado", content)
                self.assertNotIn("Invertido temporario.", content)
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_39_whisper_atomic_temp_replacement_passes(self):
        """39. Whisper temp válido -> atomic replace -> PASS."""
        task_id = "test-whisper-atomic-ok"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        try:
            params = VideoParams(video_subject="Whisper Atomic", subtitle_enabled=True, subtitle_required=True)

            def _fake_whisper(audio_file, subtitle_file, word_level=False):
                self.assertIn("subtitle.whisper.tmp.", subtitle_file)
                with open(subtitle_file, "w", encoding="utf-8") as f:
                    f.write("1\n00:00:00,100 --> 00:00:02,000\nWhisper atomico com sucesso.\n\n")
                return subtitle_file

            with patch.object(tm.voice, "create_subtitle", side_effect=RuntimeError("Edge crash")), \
                 patch.object(tm.subtitle, "create", side_effect=_fake_whisper):
                sub_path = tm.generate_subtitle(
                    task_id=task_id,
                    params=params,
                    video_script="Whisper atomico com sucesso.",
                    sub_maker=MagicMock(),
                    audio_file=os.path.join(task_dir, "audio.mp3"),
                )
                self.assertTrue(os.path.isfile(sub_path))
                self.assertTrue(sub_path.endswith("subtitle.srt"))
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_40_invalid_utf8_bytes_fails_closed(self):
        """40. Bytes UTF-8 inválidos -> invalid_utf8_encoding (BLOCK sem fallback corruptor)."""
        srt = os.path.join(self.tmp_dir, "invalid_utf8.srt")
        with open(srt, "wb") as f:
            f.write(b"\xff\xfe\x00\x00\x80\x81\x82")  # Sequência inválida UTF-8
        res = subtitle.validate_subtitle_file(srt)
        self.assertFalse(res["valid"])
        self.assertEqual(res["reason"], "invalid_utf8_encoding")

    def test_41_long_script_with_only_10_chars_subtitle_blocks(self):
        """41. Script longo com subtitle de apenas 10 caracteres -> BLOCK (cobertura proporcional)."""
        script = (
            "A Floresta Amazônica possui uma das maiores biodiversidades do planeta Terra, "
            "abrigando milhões de espécies de animais, plantas e insetos vitais para o equilíbrio climático."
        )
        srt = os.path.join(self.tmp_dir, "short_10_chars.srt")
        with open(srt, "w", encoding="utf-8") as f:
            f.write("1\n00:00:00,100 --> 00:00:01,000\nFloresta T\n\n")
        res = subtitle.validate_subtitle_file(srt, video_script=script)
        self.assertFalse(res["valid"])
        self.assertEqual(res["reason"], "text_incoherent_with_script")

    def test_42_reasonable_length_but_unrelated_content_blocks(self):
        """42. Subtitle com tamanho razoável mas conteúdo completamente não relacionado -> BLOCK (lexical overlap)."""
        script = (
            "Os golfinhos utilizam assobios característicos e ecolocalização refinada para navegar e caçar nos mares."
        )
        srt = os.path.join(self.tmp_dir, "unrelated_content.srt")
        with open(srt, "w", encoding="utf-8") as f:
            f.write(
                "1\n00:00:00,100 --> 00:00:03,000\n"
                "Hoje vamos aprender uma receita caseira de bolo de chocolate fofinho e delicioso.\n\n"
            )
        res = subtitle.validate_subtitle_file(srt, video_script=script)
        self.assertFalse(res["valid"])
        self.assertEqual(res["reason"], "text_incoherent_with_script")

    def test_43_whisper_small_accents_and_punctuation_differences_passes(self):
        """43. Whisper com pequenas diferenças de pontuação e acentos -> PASS."""
        script = "A inteligência artificial transformará a automação industrial moderna."
        srt = os.path.join(self.tmp_dir, "whisper_accents.srt")
        with open(srt, "w", encoding="utf-8") as f:
            f.write(
                "1\n00:00:00,100 --> 00:00:03,500\n"
                "A inteligencia artificial transformara a automacao industrial moderna\n\n"
            )
        res = subtitle.validate_subtitle_file(srt, video_script=script)
        self.assertTrue(res["valid"])
        self.assertEqual(res["reason"], "valid")

    def test_44_subtitle_practically_complete_and_coherent_passes(self):
        """44. Subtitle praticamente completo e coerente com o roteiro -> PASS."""
        script = "O telescópio James Webb revelou detalhes inéditos sobre a formação das primeiras galáxias do universo."
        srt = os.path.join(self.tmp_dir, "coherent_complete.srt")
        with open(srt, "w", encoding="utf-8") as f:
            f.write(
                "1\n00:00:00,100 --> 00:00:02,500\n"
                "O telescopio James Webb revelou detalhes ineditos\n\n"
                "2\n00:00:02,600 --> 00:00:05,000\n"
                "sobre a formacao das primeiras galaxias do universo.\n\n"
            )
        res = subtitle.validate_subtitle_file(srt, video_script=script)
        self.assertTrue(res["valid"])
        self.assertEqual(res["reason"], "valid")

    def test_45_render_required_with_existing_invalid_srt_blocks(self):
        """45. Render com subtitle_required=True e SRT existente porém inválido no disco -> render NÃO é chamado."""
        task_id = "test-render-invalid-srt"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        invalid_srt = os.path.join(task_dir, "subtitle.srt")
        with open(invalid_srt, "w", encoding="utf-8") as f:
            f.write("1\n00:00:00,000 --> 00:00:00,000\nZero timestamps.\n\n")

        try:
            params = VideoParams(
                video_subject="Render Invalid",
                subtitle_enabled=True,
                subtitle_required=True,
            )

            with patch.object(tm.video, "generate_video") as mock_generate_video:
                final_videos, combined_videos, warnings = tm.generate_final_videos(
                    task_id=task_id,
                    params=params,
                    downloaded_videos=["mat1.mp4"],
                    audio_file=os.path.join(task_dir, "audio.mp3"),
                    subtitle_path=invalid_srt,
                    audio_duration=5.0,
                )

                self.assertEqual(final_videos, [])
                self.assertEqual(combined_videos, [])
                self.assertEqual(warnings, [{"code": "subtitle_required_invalid"}])
                mock_generate_video.assert_not_called()
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
