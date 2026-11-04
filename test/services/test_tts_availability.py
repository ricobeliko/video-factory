import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.config import config
from app.services import (
    autonomous_production,
    operator_console,
    profile_manager,
    quality_score,
    safety_gate,
    scheduler,
    trend_radar,
    voice,
    webui_task,
)


class TestTTSAvailability(unittest.TestCase):
    def setUp(self):
        voice.clear_voice_availability_cache()

        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_tts.db")
        self.task_base_dir = os.path.join(self.test_dir, "tasks")
        os.makedirs(self.task_base_dir, exist_ok=True)

        self.task_dir_patcher = patch("app.utils.utils.task_dir", return_value=self.task_base_dir)
        self.mock_task_dir = self.task_dir_patcher.start()
        self.addCleanup(self.task_dir_patcher.stop)

        self.ffmpeg_patcher = patch("app.utils.utils.check_ffmpeg_ready", return_value=True)
        self.mock_ffmpeg = self.ffmpeg_patcher.start()
        self.addCleanup(self.ffmpeg_patcher.stop)

        operator_console.init_operator_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        profile_manager.ensure_default_profile(db_path=self.db_path)
        scheduler.init_db(self.db_path)
        trend_radar.init_trend_db(self.db_path)
        safety_gate.init_safety_db(self.db_path)
        quality_score.init_quality_db(self.db_path)

        operator_console.reset_instance_for_testing()
        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._current_role = operator_console.ROLE_PRIMARY

        operator_console.resume_factory(db_path=self.db_path)
        scheduler.set_setting("minimum_ready_stock", "3", db_path=self.db_path)

        profile_manager.create_channel(
            profile_id=profile_manager.DEFAULT_PROFILE_ID,
            platform="youtube",
            display_name="Canal YouTube Teste",
            is_enabled=True,
            db_path=self.db_path,
        )

        self.now = datetime(2026, 11, 3, 15, 30, 0, tzinfo=timezone.utc)

        self.orig_app = dict(config.app)
        self.orig_ui = dict(config.ui)

        config.app["llm_provider"] = "gemini"
        config.app["gemini_api_key"] = "mock_key"
        config.app["pexels_api_keys"] = ["mock_key"]
        config.app["video_source"] = "pexels"
        config.ui["voice_mode"] = "tts"
        config.ui["voice_name"] = "en-US-BrianMultilingualNeural-Male"

    def tearDown(self):
        voice.clear_voice_availability_cache()
        config.app.clear()
        config.app.update(self.orig_app)
        config.ui.clear()
        config.ui.update(self.orig_ui)

    def test_1_probe_falhando_retorna_tts_indisponivel_e_nao_cria_generation_started(self):
        """1) probe falhando => ciclo retorna tts_indisponivel e NÃO cria evento generation_started."""
        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_TARGET_STOCK, "3", db_path=self.db_path
        )

        with patch("app.services.autonomous_production.get_autonomous_ready_stock", return_value={"ready_count": 0, "target_stock": 3}), \
             patch("app.services.autonomous_production.discover_candidate_topic", return_value={"topic": "Mistérios do Oceano", "origin": "test"}), \
             patch("app.services.voice.check_voice_availability", return_value=(False, "edge_tts stream timed out after 10s")) as mock_probe, \
             patch("app.services.webui_task.submit_generation") as mock_submit:

            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)

            # Valida retorno estrito do status/motivo
            self.assertEqual(res.get("status"), "tts_indisponivel")
            self.assertEqual(res.get("reason"), "tts_indisponivel")
            self.assertIn("Serviço de voz indisponível", res.get("message", ""))
            self.assertIn("edge_tts stream timed out after 10s", res.get("message", ""))

            # Valida que submit_generation NÃO foi chamado
            mock_submit.assert_not_called()

            # Valida que NÃO criou evento generation_started
            events = operator_console.get_operational_events(event_type="generation_started", db_path=self.db_path)
            self.assertEqual(len(events), 0)

            # Valida que NÃO consumiu tentativa do canal (0 de 8)
            attempts = autonomous_production.count_generation_attempts_in_last_24h(db_path=self.db_path, now=self.now)
            self.assertEqual(attempts, 0)

            # Valida que NÃO incrementou rejeições consecutivas
            rejections = autonomous_production.get_consecutive_rejections(db_path=self.db_path)
            self.assertEqual(rejections, 0)

            # Valida visibilidade onde a Produção já mostra o estado do canal
            status_snap = autonomous_production.get_autonomous_status(db_path=self.db_path)
            self.assertEqual(status_snap.get("state"), autonomous_production.STATE_BLOCKED)
            self.assertIn("Serviço de voz indisponível", status_snap.get("message", ""))

    def test_2_probe_ok_fluxo_normal(self):
        """2) probe ok => fluxo normal."""
        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_TARGET_STOCK, "3", db_path=self.db_path
        )

        with patch("app.services.autonomous_production.get_autonomous_ready_stock", return_value={"ready_count": 0, "target_stock": 3}), \
             patch("app.services.autonomous_production.discover_candidate_topic", return_value={"topic": "Mistérios do Espaço", "origin": "test"}), \
             patch("app.services.voice.check_voice_availability", return_value=(True, "ok")) as mock_probe, \
             patch("app.services.webui_task.submit_generation") as mock_submit:

            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)

            # Valida avanço para generation_started
            self.assertEqual(res.get("status"), "generation_started")
            mock_submit.assert_called_once()

            # Valida gravação do evento generation_started e consumo de tentativa
            events = operator_console.get_operational_events(event_type="generation_started", db_path=self.db_path)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["metadata"]["topic"], "Mistérios do Espaço")

            attempts = autonomous_production.count_generation_attempts_in_last_24h(db_path=self.db_path, now=self.now)
            self.assertEqual(attempts, 1)

    def test_3_cache_segundo_ciclo_em_menos_de_5min_nao_repete_probe(self):
        """3) cache: segundo ciclo em <5 min não repete o probe."""
        class _MockCommunicate:
            def __init__(self, *args, **kwargs):
                pass

        def _fake_stream(communicate, on_chunk, timeout_seconds=None):
            on_chunk({"type": "audio", "data": b"mock_audio_chunk"})

        with patch("app.services.voice.create_edge_tts_communicate", side_effect=_MockCommunicate) as mock_comm, \
             patch("app.services.voice.stream_edge_tts_chunks", side_effect=_fake_stream) as mock_stream:

            # 1ª chamada: executa probe
            ok1, msg1 = voice.check_voice_availability("en-US-BrianMultilingualNeural-Male")
            self.assertTrue(ok1)
            self.assertEqual(msg1, "ok")
            self.assertEqual(mock_comm.call_count, 1)
            self.assertEqual(mock_stream.call_count, 1)

            # 2ª chamada em < 5 min: cache hit, NÃO repete o probe
            ok2, msg2 = voice.check_voice_availability("en-US-BrianMultilingualNeural-Male")
            self.assertTrue(ok2)
            self.assertEqual(msg2, "ok")
            self.assertEqual(mock_comm.call_count, 1)
            self.assertEqual(mock_stream.call_count, 1)

        # Também valida cache para falha
        voice.clear_voice_availability_cache()

        with patch("app.services.voice.create_edge_tts_communicate", side_effect=TimeoutError("stream timed out")) as mock_fail_comm:
            ok_f1, msg_f1 = voice.check_voice_availability("en-US-BrianMultilingualNeural-Male")
            self.assertFalse(ok_f1)
            self.assertEqual(mock_fail_comm.call_count, 1)

            # 2ª chamada de falha: cache hit imediato, não reexecuta
            ok_f2, msg_f2 = voice.check_voice_availability("en-US-BrianMultilingualNeural-Male")
            self.assertFalse(ok_f2)
            self.assertEqual(msg_f2, msg_f1)
            self.assertEqual(mock_fail_comm.call_count, 1)

    def test_4_provedores_nao_edge_tts_passam_direto_sem_probe(self):
        """Outros provedores (Gemini, ElevenLabs, etc.) e sem voz passam direto sem probe."""
        with patch("app.services.voice.create_edge_tts_communicate") as mock_comm:
            ok, msg = voice.check_voice_availability("gemini:Puck")
            self.assertTrue(ok)
            self.assertEqual(mock_comm.call_count, 0)

            ok, msg = voice.check_voice_availability("elevenlabs:adam")
            self.assertTrue(ok)
            self.assertEqual(mock_comm.call_count, 0)

            ok, msg = voice.check_voice_availability("none")
            self.assertTrue(ok)
            self.assertEqual(mock_comm.call_count, 0)
