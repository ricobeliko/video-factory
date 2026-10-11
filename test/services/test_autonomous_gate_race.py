"""
Testes de Regressão — V1.5E HOTFIX: Autonomous Premature Gate / Generation Race.

Reproduz exatamente o incidente real de produção (task 02b7b85b-252e-4313-b677-7d203e17ca45):
- current_task_id persistido
- has_active_generation_tasks() = False
- final-1.mp4 ainda não existe em disco
- task não está em estado terminal FAILED ou CANCELLED

Garante:
1. evaluate_completed_task_gates NUNCA é chamado prematuramente.
2. current_task_id permanece no tracking durante a geração.
3. Contador de rejeições NÃO aumenta.
4. Nenhuma nova geração é submetida.
5. Retorna estado de espera/geração de forma idempotente.
6. Após surgimento de final-1.mp4 válido e conclusão, Gate é executado exatamente uma vez.
7. Estados terminais explícitos (FAILED, CANCELLED, recovery pós-reboot) encerram tracking corretamente.
"""
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.config import config
from app.models import const
from app.services import (
    autonomous_production,
    operator_console,
    profile_manager,
    quality_score,
    safety_gate,
    scheduler,
    trend_radar,
)
from app.services import state as sm


class TestAutonomousPrematureGateRace(unittest.TestCase):
    def setUp(self):
        self.llm_provider_patcher = patch.dict(config.app, {"llm_provider": "gemini"})
        self.llm_provider_patcher.start()
        self.addCleanup(self.llm_provider_patcher.stop)

        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_race.db")
        self.task_base_dir = os.path.join(self.test_dir, "tasks")
        os.makedirs(self.task_base_dir, exist_ok=True)

        self.task_dir_patcher = patch("app.utils.utils.task_dir", return_value=self.task_base_dir)
        self.task_dir_patcher.start()
        self.addCleanup(self.task_dir_patcher.stop)

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
            display_name="Canal Teste",
            is_enabled=True,
            db_path=self.db_path,
        )

        self.now = datetime(2026, 10, 11, 16, 12, 18, tzinfo=timezone.utc)

        self.autopilot_patcher = patch(
            "app.services.autopilot.generate_ideas",
            return_value=["Ideia 1", "Ideia 2"],
        )
        self.autopilot_patcher.start()
        self.addCleanup(self.autopilot_patcher.stop)

        self.ffmpeg_patcher = patch("app.utils.utils.check_ffmpeg_ready", return_value=True)
        self.ffmpeg_patcher.start()
        self.addCleanup(self.ffmpeg_patcher.stop)

        config.app["gemini_api_key"] = "mock_key"
        config.app["pexels_api_keys"] = ["mock_key"]
        config.app["video_source"] = "pexels"
        config.ui["voice_mode"] = "tts"
        config.ui["voice_name"] = "pt-BR-AntonioNeural-Male"

    def tearDown(self):
        config.app.pop("gemini_api_key", None)
        config.app.pop("pexels_api_keys", None)
        config.app.pop("pexels_api_key", None)
        config.app.pop("video_source", None)
        config.ui.pop("voice_mode", None)
        config.ui.pop("voice_name", None)
        operator_console.reset_instance_for_testing()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_mock_video_file(self, task_id: str) -> str:
        t_dir = os.path.join(self.task_base_dir, task_id)
        os.makedirs(t_dir, exist_ok=True)
        video_path = os.path.join(t_dir, "final-1.mp4")
        with open(video_path, "wb") as f:
            f.write(b"valid video content bytes > 0")
        script_path = os.path.join(t_dir, "script.json")
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump({
                "params": {"bgm_type": "none"},
                "asset_provenance": {
                    "bgm": {"enabled": False, "source": "none"},
                    "visual_clips": [{"provider": "pexels", "local_file": video_path}],
                },
            }, f)
        return video_path

    def test_incident_reproduction_in_progress_generation_waits_safely(self):
        """Reproduz o incidente exato: task gerando, has_active=False, sem final-1.mp4.

        Não pode avaliar gates, não pode limpar current_task_id, não pode incrementar
        rejeições, não pode submeter nova geração.
        Em seguida simula finalização: Gate avalia exatamente uma vez.
        """
        incident_task_id = "02b7b85b-252e-4313-b677-7d203e17ca45"

        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_CURRENT_TASK_ID, incident_task_id,
            db_path=self.db_path,
        )

        sm.state.update_task(
            incident_task_id,
            state=const.TASK_STATE_PROCESSING,
            progress=25,
            video_subject="Buracos Negros",
            profile_id=profile_manager.DEFAULT_PROFILE_ID,
        )

        with patch("app.services.webui_task.has_active_generation_tasks", return_value=False), \
             patch("app.services.autonomous_production.evaluate_completed_task_gates") as mock_gates, \
             patch("app.services.webui_task.submit_generation") as mock_submit:

            # 1. Ciclo durante geração: sem final-1.mp4 em disco
            res1 = autonomous_production.run_autonomous_cycle(
                force=True,
                db_path=self.db_path,
                task_base_dir=self.task_base_dir,
                now=self.now,
            )

            # EXPECTATIVAS FAIL-CLOSED:
            mock_gates.assert_not_called()
            mock_submit.assert_not_called()
            self.assertIn(res1.get("status"), ("generating", "waiting_generation"))
            self.assertEqual(res1.get("state"), autonomous_production.STATE_GENERATING)
            self.assertEqual(res1.get("task_id"), incident_task_id)

            # Tracking preservado
            current_tracked = autonomous_production.get_autonomous_setting(
                autonomous_production.KEY_AUTONOMOUS_CURRENT_TASK_ID,
                db_path=self.db_path,
            )
            self.assertEqual(current_tracked, incident_task_id)

            # Rejeições consecutivas NÃO incrementadas
            rejections = autonomous_production.get_consecutive_rejections(
                db_path=self.db_path,
            )
            self.assertEqual(rejections, 0)

        # 2. Ciclo posterior: geração concluiu, final-1.mp4 surge e state vira COMPLETE
        video_path = self._create_mock_video_file(incident_task_id)
        sm.state.update_task(
            incident_task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            video_file=video_path,
        )

        with patch("app.services.webui_task.has_active_generation_tasks", return_value=False), \
             patch("app.services.autonomous_production.evaluate_completed_task_gates",
                   return_value=(True, "Aprovado", {"quality_score": 85.0})) as mock_gates, \
             patch("app.services.webui_task.submit_generation") as mock_submit:

            res2 = autonomous_production.run_autonomous_cycle(
                force=True,
                db_path=self.db_path,
                task_base_dir=self.task_base_dir,
                now=self.now,
            )

            mock_gates.assert_called_once_with(
                incident_task_id,
                db_path=self.db_path,
                task_base_dir=self.task_base_dir,
            )
            mock_submit.assert_not_called()
            self.assertIn(res2.get("status"), ("scheduled", "waiting_schedule"))

            # Tracking limpo após conclusão e avaliação bem-sucedida
            after_tracked = autonomous_production.get_autonomous_setting(
                autonomous_production.KEY_AUTONOMOUS_CURRENT_TASK_ID,
                db_path=self.db_path,
            )
            self.assertEqual(after_tracked, "")

    def test_incident_with_missing_state_waits_without_premature_gate(self):
        """Se sm.state não possui o registro da task (desync em memória), ainda assim aguarda.

        Ausência de final-*.mp4 não pode inferir rejeição nem avaliar gates.
        """
        task_id = "missing-state-task-456"

        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_CURRENT_TASK_ID, task_id,
            db_path=self.db_path,
        )

        with patch("app.services.webui_task.has_active_generation_tasks", return_value=False), \
             patch("app.services.state.MemoryState.get_task", return_value=None), \
             patch("app.services.autonomous_production.evaluate_completed_task_gates") as mock_gates, \
             patch("app.services.webui_task.submit_generation") as mock_submit:

            res = autonomous_production.run_autonomous_cycle(
                force=True,
                db_path=self.db_path,
                task_base_dir=self.task_base_dir,
                now=self.now,
            )

            mock_gates.assert_not_called()
            mock_submit.assert_not_called()
            self.assertIn(res.get("status"), ("generating", "waiting_generation"))
            self.assertEqual(res.get("task_id"), task_id)

            current_tracked = autonomous_production.get_autonomous_setting(
                autonomous_production.KEY_AUTONOMOUS_CURRENT_TASK_ID,
                db_path=self.db_path,
            )
            self.assertEqual(current_tracked, task_id)
            self.assertEqual(autonomous_production.get_consecutive_rejections(db_path=self.db_path), 0)

    def test_explicit_failed_task_cleans_tracking_and_records_error(self):
        """Terminal FAILED explícito limpa tracking, não avalia gates e retorna error."""
        task_id = "failed-task-789"

        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_CURRENT_TASK_ID, task_id,
            db_path=self.db_path,
        )

        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_FAILED,
            failed_stage="pipeline",
            error="Falha de render no pipeline",
            progress=40,
        )

        with patch("app.services.webui_task.has_active_generation_tasks", return_value=False), \
             patch("app.services.autonomous_production.evaluate_completed_task_gates") as mock_gates, \
             patch("app.services.webui_task.submit_generation") as mock_submit:

            res = autonomous_production.run_autonomous_cycle(
                force=True,
                db_path=self.db_path,
                task_base_dir=self.task_base_dir,
                now=self.now,
            )

            mock_gates.assert_not_called()
            mock_submit.assert_not_called()
            self.assertEqual(res.get("status"), "error")
            self.assertEqual(res.get("task_id"), task_id)

            current_tracked = autonomous_production.get_autonomous_setting(
                autonomous_production.KEY_AUTONOMOUS_CURRENT_TASK_ID,
                db_path=self.db_path,
            )
            self.assertEqual(current_tracked, "")

    def test_explicit_cancelled_task_cleans_tracking_and_sets_idle(self):
        """Terminal CANCELLED explícito limpa tracking, não avalia gates e retorna cancelled."""
        task_id = "cancelled-task-101"

        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_CURRENT_TASK_ID, task_id,
            db_path=self.db_path,
        )

        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_CANCELLED,
            cancelled=True,
            progress=10,
        )

        with patch("app.services.webui_task.has_active_generation_tasks", return_value=False), \
             patch("app.services.autonomous_production.evaluate_completed_task_gates") as mock_gates, \
             patch("app.services.webui_task.submit_generation") as mock_submit:

            res = autonomous_production.run_autonomous_cycle(
                force=True,
                db_path=self.db_path,
                task_base_dir=self.task_base_dir,
                now=self.now,
            )

            mock_gates.assert_not_called()
            mock_submit.assert_not_called()
            self.assertEqual(res.get("status"), "cancelled")
            self.assertEqual(res.get("task_id"), task_id)

            current_tracked = autonomous_production.get_autonomous_setting(
                autonomous_production.KEY_AUTONOMOUS_CURRENT_TASK_ID,
                db_path=self.db_path,
            )
            self.assertEqual(current_tracked, "")

    def test_reboot_crash_recovery_cleans_tracking_and_returns_recovery_error(self):
        """Reboot/crash reconciliado com failed_stage='interrupted_by_restart' aciona recovery_error."""
        task_id = "reboot-task-202"

        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_CURRENT_TASK_ID, task_id,
            db_path=self.db_path,
        )

        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_FAILED,
            failed_stage="interrupted_by_restart",
            error="Execução interrompida pela reinicialização do sistema",
            progress=50,
        )

        with patch("app.services.webui_task.has_active_generation_tasks", return_value=False), \
             patch("app.services.autonomous_production.evaluate_completed_task_gates") as mock_gates, \
             patch("app.services.webui_task.submit_generation") as mock_submit:

            res = autonomous_production.run_autonomous_cycle(
                force=True,
                db_path=self.db_path,
                task_base_dir=self.task_base_dir,
                now=self.now,
            )

            mock_gates.assert_not_called()
            mock_submit.assert_not_called()
            self.assertEqual(res.get("status"), "recovery_error")
            self.assertEqual(res.get("reason"), "generation_interrupted")
            self.assertEqual(res.get("task_id"), task_id)

            current_tracked = autonomous_production.get_autonomous_setting(
                autonomous_production.KEY_AUTONOMOUS_CURRENT_TASK_ID,
                db_path=self.db_path,
            )
            self.assertEqual(current_tracked, "")

    def test_video_exists_but_task_still_processing_waits_without_gate(self):
        """Mesmo se arquivo de vídeo existir, se task_state ainda estiver PROCESSING, aguarda."""
        task_id = "video-exists-still-processing-303"

        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_CURRENT_TASK_ID, task_id,
            db_path=self.db_path,
        )

        self._create_mock_video_file(task_id)
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_PROCESSING,
            progress=95,
        )

        with patch("app.services.webui_task.has_active_generation_tasks", return_value=False), \
             patch("app.services.autonomous_production.evaluate_completed_task_gates") as mock_gates, \
             patch("app.services.webui_task.submit_generation") as mock_submit:

            res = autonomous_production.run_autonomous_cycle(
                force=True,
                db_path=self.db_path,
                task_base_dir=self.task_base_dir,
                now=self.now,
            )

            mock_gates.assert_not_called()
            mock_submit.assert_not_called()
            self.assertIn(res.get("status"), ("generating", "waiting_generation"))
            self.assertEqual(res.get("task_id"), task_id)

            current_tracked = autonomous_production.get_autonomous_setting(
                autonomous_production.KEY_AUTONOMOUS_CURRENT_TASK_ID,
                db_path=self.db_path,
            )
            self.assertEqual(current_tracked, task_id)
