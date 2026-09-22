"""
Suíte de Testes da Fase V12-E — Autonomous Production Loop.

Cobre todos os 18 cenários obrigatórios:
1. autonomous OFF nunca gera
2. factory PAUSED nunca gera
3. SECONDARY nunca gera
4. estoque suficiente não gera
5. estoque insuficiente gera quantidade limitada
6. max per cycle respeitado
7. limite 24h respeitado
8. task duplicada não criada
9. Safety BLOCK não agenda
10. Safety REVIEW não agenda automaticamente
11. Quality abaixo do mínimo não agenda
12. aprovado alimenta Scheduler
13. Scheduler continua único responsável pela publicação
14. reboot/recovery não duplica task
15. dois ciclos concorrentes não duplicam produção
16. falha de provider não cria loop infinito
17. zero chamadas reais ao Upload-Post nos testes
18. TikTok não é habilitado automaticamente
"""
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.config import config
from app.models import const
from app.models.schema import VideoAspect, VideoParams
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
from app.services import state as sm


class TestAutonomousProductionLoop(unittest.TestCase):
    def setUp(self):
        # Explicit synthetic provider: tests must not depend on local config.toml.
        self.llm_provider_patcher = patch.dict(config.app, {"llm_provider": "gemini"})
        self.llm_provider_patcher.start()
        self.addCleanup(self.llm_provider_patcher.stop)
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_autonomous.db")
        self.task_base_dir = os.path.join(self.test_dir, "tasks")
        os.makedirs(self.task_base_dir, exist_ok=True)

        # Inicializa bancos isolados
        operator_console.init_operator_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        profile_manager.ensure_default_profile(db_path=self.db_path)
        scheduler.init_db(self.db_path)
        trend_radar.init_trend_db(self.db_path)
        safety_gate.init_safety_db(self.db_path)
        quality_score.init_quality_db(self.db_path)

        # Configura instância de teste como PRIMARY por padrão
        operator_console.reset_instance_for_testing()
        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._current_role = operator_console.ROLE_PRIMARY

        # Configura fábrica RUNNING e estoque mínimo padrão
        operator_console.resume_factory(db_path=self.db_path)
        scheduler.set_setting("minimum_ready_stock", "3", db_path=self.db_path)

        # Configura canais do perfil default para YouTube
        profile_manager.create_channel(
            profile_id=profile_manager.DEFAULT_PROFILE_ID,
            platform="youtube",
            display_name="Canal YouTube Teste",
            is_enabled=True,
            db_path=self.db_path,
        )

        self.now = datetime(2026, 9, 19, 14, 0, 0, tzinfo=timezone.utc)

        # Spies para garantir ZERO chamadas a APIs de publicação
        self.upload_post_patcher = patch("app.services.upload_post.UploadPostService.upload_video")
        self.mock_upload_video = self.upload_post_patcher.start()

        self.cross_post_patcher = patch("app.services.upload_post.cross_post_video")
        self.mock_cross_post = self.cross_post_patcher.start()

        self.publish_task_patcher = patch("app.services.task.publish_task")
        self.mock_publish_task = self.publish_task_patcher.start()

        # Mock de autopilot.generate_ideas para garantir execução 100% offline
        self.autopilot_patcher = patch("app.services.autopilot.generate_ideas", return_value=["Ideia de Teste 1", "Ideia de Teste 2", "Ideia de Teste 3"])
        self.mock_autopilot = self.autopilot_patcher.start()

        # Configura chaves de API nos mocks para validação passiva de provedores
        config.app["gemini_api_key"] = "mock_test_gemini_key"
        config.app["pexels_api_keys"] = ["mock_test_pexels_key"]
        config.app["video_source"] = "pexels"
        config.ui["voice_mode"] = "tts"
        config.ui["voice_name"] = "pt-BR-AntonioNeural-Male"
        self.ffmpeg_patcher = patch("app.utils.utils.check_ffmpeg_ready", return_value=True)
        self.mock_ffmpeg = self.ffmpeg_patcher.start()

    def tearDown(self):
        self.ffmpeg_patcher.stop()
        config.app.pop("gemini_api_key", None)
        config.app.pop("pexels_api_keys", None)
        config.app.pop("pexels_api_key", None)
        config.app.pop("pixabay_api_keys", None)
        config.app.pop("pixabay_api_key", None)
        config.app.pop("coverr_api_keys", None)
        config.app.pop("coverr_api_key", None)
        config.app.pop("video_source", None)
        config.ui.pop("voice_mode", None)
        config.ui.pop("voice_name", None)
        config.ui.pop("subtitle_enabled", None)
        config.ui.pop("font_name", None)
        config.ui.pop("font_size", None)
        config.ui.pop("bgm_type", None)
        config.ui.pop("bgm_volume", None)
        config.ui.pop("video_aspect_pexels", None)
        config.ui.pop("video_aspect_pixabay", None)
        config.ui.pop("video_aspect_coverr", None)
        self.autopilot_patcher.stop()
        self.upload_post_patcher.stop()
        self.cross_post_patcher.stop()
        self.publish_task_patcher.stop()
        operator_console.reset_instance_for_testing()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_mock_video_file(self, task_id: str) -> str:
        """Cria um arquivo de vídeo falso no diretório da task para simular render completo."""
        t_dir = os.path.join(self.task_base_dir, task_id)
        os.makedirs(t_dir, exist_ok=True)
        video_path = os.path.join(t_dir, "final-1.mp4")
        with open(video_path, "wb") as f:
            f.write(b"fake mp4 video bytes for testing")
        return video_path

    # -----------------------------------------------------------------------
    # Cenário 1: autonomous OFF nunca gera
    # -----------------------------------------------------------------------
    def test_autonomous_off_never_generates(self):
        autonomous_production.set_autonomous_mode_enabled(False, db_path=self.db_path)

        with patch("app.services.webui_task.submit_generation") as mock_sub:
            res = autonomous_production.run_autonomous_cycle(db_path=self.db_path, now=self.now)
            self.assertEqual(res.get("status"), "disabled")
            mock_sub.assert_not_called()

    # -----------------------------------------------------------------------
    # Cenário 2: factory PAUSED nunca gera
    # -----------------------------------------------------------------------
    def test_factory_paused_never_generates(self):
        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        operator_console.pause_factory(db_path=self.db_path)

        with patch("app.services.webui_task.submit_generation") as mock_sub:
            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)
            self.assertEqual(res.get("status"), "blocked")
            self.assertEqual(res.get("reason"), "factory_paused")
            mock_sub.assert_not_called()

    # -----------------------------------------------------------------------
    # Cenário 3: SECONDARY nunca gera
    # -----------------------------------------------------------------------
    def test_secondary_never_generates(self):
        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        with operator_console._instance_state_lock:
            operator_console._current_role = operator_console.ROLE_SECONDARY_VIEW_ONLY

        with patch("app.services.webui_task.submit_generation") as mock_sub:
            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)
            self.assertEqual(res.get("status"), "blocked")
            self.assertEqual(res.get("reason"), "secondary_view_only")
            mock_sub.assert_not_called()

    # -----------------------------------------------------------------------
    # Cenário 4: estoque suficiente não gera
    # -----------------------------------------------------------------------
    def test_sufficient_stock_does_not_generate(self):
        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_TARGET_STOCK, "2", db_path=self.db_path
        )

        # Isola a decisão do ciclo; inventário persistente tem testes próprios.
        with patch("app.services.autonomous_production.get_autonomous_ready_stock") as mock_stock, \
             patch("app.services.webui_task.submit_generation") as mock_sub:
            mock_stock.return_value = {"ready_count": 2, "target_stock": 2}
            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)
            self.assertEqual(res.get("status"), "idle")
            self.assertIn("Estoque pronto suficiente", res.get("message"))
            mock_sub.assert_not_called()

    # -----------------------------------------------------------------------
    # Cenário 5: estoque insuficiente gera quantidade limitada
    # -----------------------------------------------------------------------
    def test_insufficient_stock_generates_limited_quantity(self):
        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_TARGET_STOCK, "3", db_path=self.db_path
        )
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_MAX_TASKS_PER_CYCLE, "1", db_path=self.db_path
        )

        with patch("app.services.autonomous_production.get_autonomous_ready_stock") as mock_stock, \
             patch("app.services.autonomous_production.discover_candidate_topic") as mock_disc, \
             patch("app.services.webui_task.submit_generation") as mock_sub:
            mock_stock.return_value = {"ready_count": 1, "target_stock": 3}
            mock_disc.return_value = {"topic": "O mistério das pirâmides submersas", "origin": "test"}

            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)
            self.assertEqual(res.get("status"), "generation_started")
            mock_sub.assert_called_once()
            called_params = mock_sub.call_args[1].get("params") or mock_sub.call_args[0][1]
            self.assertEqual(called_params.video_subject, "O mistério das pirâmides submersas")

    # -----------------------------------------------------------------------
    # Cenário 6: max per cycle respeitado
    # -----------------------------------------------------------------------
    def test_max_per_cycle_respected(self):
        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_TARGET_STOCK, "10", db_path=self.db_path
        )
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_MAX_TASKS_PER_CYCLE, "1", db_path=self.db_path
        )

        with patch("app.services.autonomous_production.get_autonomous_ready_stock") as mock_stock, \
             patch("app.services.autonomous_production.discover_candidate_topic") as mock_disc, \
             patch("app.services.webui_task.submit_generation") as mock_sub:
            mock_stock.return_value = {"ready_count": 0, "target_stock": 10}  # Déficit de 10
            mock_disc.return_value = {"topic": "3 fatos sobre buracos negros", "origin": "test"}

            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)
            self.assertEqual(res.get("status"), "generation_started")
            # Mesmo com deficit 10, gerou exatamente 1 tarefa no ciclo
            self.assertEqual(mock_sub.call_count, 1)

    # -----------------------------------------------------------------------
    # Cenário 7: limite 24h respeitado
    # -----------------------------------------------------------------------
    def test_24h_limit_respected(self):
        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_MAX_24H, "3", db_path=self.db_path
        )

        # Registra 3 gerações no banco nas últimas 2 horas
        for i in range(3):
            operator_console.log_operational_event(
                component="autonomous_production",
                severity=operator_console.SEVERITY_INFO,
                event_type="generation_started",
                message=f"Geração {i}",
                db_path=self.db_path,
            )

        with patch("app.services.autonomous_production.get_autonomous_ready_stock") as mock_stock, \
             patch("app.services.webui_task.submit_generation") as mock_sub:
            mock_stock.return_value = {"ready_count": 0, "target_stock": 10}
            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)
            self.assertEqual(res.get("status"), "blocked")
            self.assertEqual(res.get("reason"), "daily_limit_reached")
            mock_sub.assert_not_called()

    # -----------------------------------------------------------------------
    # Cenário 8: task duplicada não criada
    # -----------------------------------------------------------------------
    def test_duplicate_task_not_created(self):
        existing_topics = ["Curiosidades sobre o Planeta Marte", "História da Inteligência Artificial"]

        # Tópico idêntico ou com pequena variação
        self.assertTrue(autonomous_production.is_topic_duplicate("curiosidades sobre o planeta marte", existing_topics))
        self.assertTrue(autonomous_production.is_topic_duplicate("Curiosidades sobre o Planeta Marte!", existing_topics))

        # Tópico totalmente novo e distinto
        self.assertFalse(autonomous_production.is_topic_duplicate("Como funcionam os oceanos profundos", existing_topics))

    # -----------------------------------------------------------------------
    # Cenário 9: Safety BLOCK não agenda
    # -----------------------------------------------------------------------
    def test_safety_block_does_not_schedule(self):
        task_id = "task-safety-block-1"
        self._create_mock_video_file(task_id)

        # Registra avaliação de Safety Gate com status BLOCK
        safety_gate.save_safety_assessment(
            {
                "task_id": task_id,
                "preset": "youtube_shorts_original",
                "safety_status": const.SAFETY_STATUS_BLOCK,
                "safety_reasons": ["Duração muito curta (< 60s)"],
                "word_count": 50,
                "estimated_duration": 45.0,
                "actual_duration": 45.0,
                "hook_text": "Hook teste",
                "cta_text": "CTA teste",
                "checked_at": self.now.isoformat(),
            },
            db_path=self.db_path,
        )

        with patch("app.services.scheduler.get_task_final_video", return_value=self._create_mock_video_file(task_id)):
            approved, reason, _ = autonomous_production.evaluate_completed_task_gates(task_id, db_path=self.db_path)
            self.assertFalse(approved)
            self.assertIn("BLOCK", reason)

    # -----------------------------------------------------------------------
    # Cenário 10: Safety REVIEW não agenda automaticamente
    # -----------------------------------------------------------------------
    def test_safety_review_does_not_auto_schedule(self):
        task_id = "task-safety-review-1"
        self._create_mock_video_file(task_id)

        safety_gate.save_safety_assessment(
            {
                "task_id": task_id,
                "preset": "youtube_shorts_original",
                "safety_status": const.SAFETY_STATUS_REVIEW,
                "safety_reasons": ["Potencial similaridade com tema recente"],
                "word_count": 80,
                "estimated_duration": 63.0,
                "actual_duration": 63.0,
                "hook_text": "Hook teste",
                "cta_text": "CTA teste",
                "checked_at": self.now.isoformat(),
            },
            db_path=self.db_path,
        )

        with patch("app.services.scheduler.get_task_final_video", return_value=self._create_mock_video_file(task_id)):
            approved, reason, _ = autonomous_production.evaluate_completed_task_gates(task_id, db_path=self.db_path)
            self.assertFalse(approved)
            self.assertIn("REVIEW", reason)

    # -----------------------------------------------------------------------
    # Cenário 11: Quality abaixo do mínimo não agenda
    # -----------------------------------------------------------------------
    def test_quality_below_minimum_does_not_schedule(self):
        task_id = "task-quality-low-1"
        self._create_mock_video_file(task_id)

        safety_gate.save_safety_assessment(
            {
                "task_id": task_id,
                "safety_status": const.SAFETY_STATUS_PASS,
                "safety_reasons": [],
                "checked_at": self.now.isoformat(),
            },
            db_path=self.db_path,
        )

        with patch("app.services.quality_score.evaluate_quality") as mock_q, \
             patch("app.services.scheduler.get_task_final_video", return_value=self._create_mock_video_file(task_id)):
            mock_q.return_value = {
                "quality_score": 48.0,
                "quality_label": quality_score.LABEL_WEAK,
                "reasons": ["Hook fraco", "Baixa originalidade"],
            }
            approved, reason, metrics = autonomous_production.evaluate_completed_task_gates(task_id, db_path=self.db_path)
            self.assertFalse(approved)
            self.assertIn("Quality Score insuficiente", reason)

    # -----------------------------------------------------------------------
    # Cenário 12: Aprovado alimenta Scheduler
    # -----------------------------------------------------------------------
    def test_approved_feeds_scheduler(self):
        task_id = "task-approved-1"
        v_path = self._create_mock_video_file(task_id)

        # Simula task completa em sm.state
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            video_subject="3 segredos da mente humana",
            video_file=v_path,
            safety_status=const.SAFETY_STATUS_PASS,
            profile_id=profile_manager.DEFAULT_PROFILE_ID,
        )

        safety_gate.save_safety_assessment(
            {
                "task_id": task_id,
                "safety_status": const.SAFETY_STATUS_PASS,
                "safety_reasons": [],
                "checked_at": self.now.isoformat(),
            },
            db_path=self.db_path,
        )

        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_CURRENT_TASK_ID, task_id, db_path=self.db_path
        )

        with patch("app.services.webui_task.has_active_generation_tasks", return_value=False), \
             patch("app.services.quality_score.evaluate_quality") as mock_q, \
             patch("app.services.scheduler.get_task_final_video", return_value=v_path):
            mock_q.return_value = {
                "quality_score": 85.0,
                "quality_label": quality_score.LABEL_STRONG,
                "reasons": ["Excelente gancho"],
            }

            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)
            self.assertEqual(res.get("status"), "scheduled")
            self.assertEqual(res.get("task_id"), task_id)

            # Verifica se foi adotada na tabela task_platforms
            platforms = scheduler.get_task_platforms(task_id, db_path=self.db_path)
            self.assertIn("youtube", platforms)

            # Verifica se foi gerado scheduled_post
            with scheduler.get_connection(self.db_path) as conn:
                posts = conn.execute(
                    "SELECT task_id, platform, status FROM scheduled_posts WHERE task_id = ?;", (task_id,)
                ).fetchall()
                self.assertGreaterEqual(len(posts), 1)
                self.assertEqual(posts[0]["platform"], "youtube")

    # -----------------------------------------------------------------------
    # Cenário 13: Scheduler continua único responsável pela publicação
    # -----------------------------------------------------------------------
    def test_scheduler_remains_sole_publisher(self):
        # Executa ciclo completo do autonomous loop
        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        task_id = "task-sole-pub-1"
        v_path = self._create_mock_video_file(task_id)

        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            video_subject="O enigma do triângulo das bermudas",
            video_file=v_path,
            safety_status=const.SAFETY_STATUS_PASS,
            profile_id=profile_manager.DEFAULT_PROFILE_ID,
        )

        safety_gate.save_safety_assessment(
            {
                "task_id": task_id,
                "safety_status": const.SAFETY_STATUS_PASS,
                "safety_reasons": [],
                "checked_at": self.now.isoformat(),
            },
            db_path=self.db_path,
        )

        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_CURRENT_TASK_ID, task_id, db_path=self.db_path
        )

        with patch("app.services.webui_task.has_active_generation_tasks", return_value=False), \
             patch("app.services.quality_score.evaluate_quality") as mock_q, \
             patch("app.services.scheduler.get_task_final_video", return_value=v_path):
            mock_q.return_value = {"quality_score": 82.0, "quality_label": quality_score.LABEL_GOOD}
            autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)

        # Validação estrita: Nenhuma chamada direta de publicação foi feita pelo autonomous loop
        self.mock_publish_task.assert_not_called()
        self.mock_upload_video.assert_not_called()

    # -----------------------------------------------------------------------
    # Cenário 14: Reboot/recovery não duplica task
    # -----------------------------------------------------------------------
    def test_reboot_recovery_no_duplicate_task(self):
        task_id = "task-reboot-recover-1"
        v_path = self._create_mock_video_file(task_id)

        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_TARGET_STOCK, "1", db_path=self.db_path
        )
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_CURRENT_TASK_ID, task_id, db_path=self.db_path
        )

        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            video_subject="Fatos fascinantes",
            video_file=v_path,
            safety_status=const.SAFETY_STATUS_PASS,
            profile_id=profile_manager.DEFAULT_PROFILE_ID,
        )
        safety_gate.save_safety_assessment(
            {"task_id": task_id, "safety_status": const.SAFETY_STATUS_PASS, "safety_reasons": []},
            db_path=self.db_path,
        )

        self._persist_waiting_fixture(task_id)
        with patch("app.services.webui_task.has_active_generation_tasks", return_value=False), \
             patch("app.services.quality_score.evaluate_quality", return_value={"quality_score": 90.0, "quality_label": "STRONG"}), \
             patch("app.services.scheduler.get_task_final_video", return_value=v_path), \
             patch("app.services.webui_task.submit_generation"):
            # Primeiro ciclo pós-reboot adota e agenda
            res1 = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)
            self.assertEqual(res1.get("status"), "scheduled")

            # Segundo ciclo imediatamente a seguir: já não duplica e agora está idle ou cooldown
            res2 = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)
            self.assertIn(res2.get("status"), ("idle", "cooldown"))

            # Confirma que há apenas 1 scheduled_post para este task_id
            with scheduler.get_connection(self.db_path) as conn:
                count = conn.execute(
                    "SELECT count(*) FROM scheduled_posts WHERE task_id = ?;", (task_id,)
                ).fetchone()[0]
                self.assertEqual(count, 1)

    # -----------------------------------------------------------------------
    # Cenário 15: Dois ciclos concorrentes não duplicam produção
    # -----------------------------------------------------------------------
    def test_concurrent_cycles_no_duplicate_production(self):
        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)

        # Simula geração já ativa no InMemoryTaskManager
        with patch("app.services.webui_task.has_active_generation_tasks", return_value=True), \
             patch("app.services.webui_task.get_active_task_ids", return_value=["active-task-123"]), \
             patch("app.services.webui_task.submit_generation") as mock_sub:
            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)
            self.assertEqual(res.get("status"), "busy")
            self.assertEqual(res.get("state"), autonomous_production.STATE_GENERATING)
            mock_sub.assert_not_called()

    # -----------------------------------------------------------------------
    # Cenário 16: Falha de provider não cria loop infinito
    # -----------------------------------------------------------------------
    def test_provider_failure_no_infinite_loop(self):
        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)

        # Simula FFmpeg inoperante
        broken_health = {
            "FFmpeg": {"status": operator_console.PROVIDER_UNAVAILABLE, "details": "FFmpeg quebrado"}
        }
        with patch("app.services.operator_console.get_provider_health_summary", return_value=broken_health), \
             patch("app.services.webui_task.submit_generation") as mock_sub:
            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)
            self.assertEqual(res.get("status"), "blocked")
            self.assertEqual(res.get("reason"), "provider_unavailable")
            mock_sub.assert_not_called()

            # Estado persistido é blocked
            st = autonomous_production.get_autonomous_status(db_path=self.db_path)
            self.assertEqual(st.get("state"), autonomous_production.STATE_BLOCKED)

    # -----------------------------------------------------------------------
    # Cenário 17: Zero chamadas reais ao Upload-Post nos testes
    # -----------------------------------------------------------------------
    def test_zero_real_upload_post_calls(self):
        # O mock em setUp() espiona upload_post.upload_video
        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        with patch("app.services.webui_task.submit_generation"):
            autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)

        self.assertEqual(self.mock_upload_video.call_count, 0)
        self.assertEqual(self.mock_publish_task.call_count, 0)

    # -----------------------------------------------------------------------
    # Cenário 18: TikTok não é habilitado automaticamente
    # -----------------------------------------------------------------------
    def test_tiktok_not_automatically_enabled(self):
        task_id = "task-yt-only-1"
        v_path = self._create_mock_video_file(task_id)

        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            video_subject="Mistério e Ciência",
            video_file=v_path,
            safety_status=const.SAFETY_STATUS_PASS,
            profile_id=profile_manager.DEFAULT_PROFILE_ID,
        )
        safety_gate.save_safety_assessment(
            {"task_id": task_id, "safety_status": const.SAFETY_STATUS_PASS, "safety_reasons": []},
            db_path=self.db_path,
        )

        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_CURRENT_TASK_ID, task_id, db_path=self.db_path
        )

        with patch("app.services.webui_task.has_active_generation_tasks", return_value=False), \
             patch("app.services.quality_score.evaluate_quality", return_value={"quality_score": 85.0, "quality_label": "STRONG"}), \
             patch("app.services.scheduler.get_task_final_video", return_value=v_path):
            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)
            self.assertEqual(res.get("status"), "scheduled")

            # Plataformas associadas devem conter APENAS youtube
            platforms = scheduler.get_task_platforms(task_id, db_path=self.db_path)
            self.assertIn("youtube", platforms)
            self.assertNotIn("tiktok", platforms)

            # scheduled_posts não deve conter nenhum registro para tiktok
            with scheduler.get_connection(self.db_path) as conn:
                tt_posts = conn.execute(
                    "SELECT id FROM scheduled_posts WHERE task_id = ? AND platform = 'tiktok';", (task_id,)
                ).fetchall()
                self.assertEqual(len(tt_posts), 0)

    # -----------------------------------------------------------------------
    # FASE V12-E.1: Testes de Hardening
    # -----------------------------------------------------------------------

    # H1: Safety assessment ausente => bloqueia (fail-closed)
    def test_safety_assessment_missing_fails_closed(self):
        task_id = "task-safety-missing-1"
        self._create_mock_video_file(task_id)
        sm.state.update_task(task_id, state=const.TASK_STATE_COMPLETE, video_subject="Teste Missing")

        with patch("app.services.scheduler.get_task_final_video", return_value=self._create_mock_video_file(task_id)):
            approved, reason, metrics = autonomous_production.evaluate_completed_task_gates(task_id, db_path=self.db_path)
            self.assertFalse(approved)
            self.assertEqual(metrics.get("safety_status"), "MISSING")
            self.assertIn("fail-closed", reason)

    # H2: Safety status desconhecido => bloqueia
    def test_safety_status_unknown_fails_closed(self):
        task_id = "task-safety-unknown-1"
        self._create_mock_video_file(task_id)
        safety_gate.save_safety_assessment(
            {"task_id": task_id, "safety_status": "MAYBE_SAFE", "safety_reasons": []},
            db_path=self.db_path,
        )
        with patch("app.services.scheduler.get_task_final_video", return_value=self._create_mock_video_file(task_id)):
            approved, reason, metrics = autonomous_production.evaluate_completed_task_gates(task_id, db_path=self.db_path)
            self.assertFalse(approved)
            self.assertEqual(metrics.get("safety_status"), "MAYBE_SAFE")
            self.assertIn("não aprovado", reason)

    # H3: Safety lookup exception => bloqueia
    def test_safety_lookup_exception_fails_closed(self):
        task_id = "task-safety-exc-1"
        self._create_mock_video_file(task_id)
        with patch("app.services.safety_gate.get_safety_assessment", side_effect=RuntimeError("DB lock error")), \
             patch("app.services.scheduler.get_task_final_video", return_value=self._create_mock_video_file(task_id)):
            approved, reason, metrics = autonomous_production.evaluate_completed_task_gates(task_id, db_path=self.db_path)
            self.assertFalse(approved)
            self.assertEqual(metrics.get("safety_status"), "ERROR")
            self.assertIn("fail-closed", reason)

    # H4: Quality 69.9 => bloqueia
    def test_quality_69_9_blocks(self):
        task_id = "task-quality-69-9"
        self._create_mock_video_file(task_id)
        safety_gate.save_safety_assessment(
            {"task_id": task_id, "safety_status": const.SAFETY_STATUS_PASS, "safety_reasons": []},
            db_path=self.db_path,
        )
        with patch("app.services.quality_score.evaluate_quality", return_value={"quality_score": 69.9, "quality_label": "REVIEW"}), \
             patch("app.services.scheduler.get_task_final_video", return_value=self._create_mock_video_file(task_id)):
            approved, reason, metrics = autonomous_production.evaluate_completed_task_gates(task_id, db_path=self.db_path)
            self.assertFalse(approved)
            self.assertIn("insuficiente para produção autônoma", reason)

    # H5: Quality 70.0 => aprova
    def test_quality_70_approves(self):
        task_id = "task-quality-70-0"
        self._create_mock_video_file(task_id)
        safety_gate.save_safety_assessment(
            {"task_id": task_id, "safety_status": const.SAFETY_STATUS_PASS, "safety_reasons": []},
            db_path=self.db_path,
        )
        with patch("app.services.quality_score.evaluate_quality", return_value={"quality_score": 70.0, "quality_label": "GOOD"}), \
             patch("app.services.scheduler.get_task_final_video", return_value=self._create_mock_video_file(task_id)):
            approved, reason, metrics = autonomous_production.evaluate_completed_task_gates(task_id, db_path=self.db_path)
            self.assertTrue(approved)

    # H6: Quality 85.0 => aprova
    def test_quality_85_approves(self):
        task_id = "task-quality-85-0"
        self._create_mock_video_file(task_id)
        safety_gate.save_safety_assessment(
            {"task_id": task_id, "safety_status": const.SAFETY_STATUS_PASS, "safety_reasons": []},
            db_path=self.db_path,
        )
        with patch("app.services.quality_score.evaluate_quality", return_value={"quality_score": 85.0, "quality_label": "STRONG"}), \
             patch("app.services.scheduler.get_task_final_video", return_value=self._create_mock_video_file(task_id)):
            approved, reason, metrics = autonomous_production.evaluate_completed_task_gates(task_id, db_path=self.db_path)
            self.assertTrue(approved)

    # H7: Ready stock ignora REVIEW, BLOCK e safety ausente
    def test_ready_stock_ignores_review_block_and_missing(self):
        t_review = "t-rev-1"
        t_block = "t-blk-1"
        t_missing = "t-mis-1"
        t_pass = "t-pas-1"

        for tid, st in [(t_review, "REVIEW"), (t_block, "BLOCK"), (t_missing, None), (t_pass, "PASS")]:
            v_path = self._create_mock_video_file(tid)
            sm.state.update_task(
                tid,
                state=const.TASK_STATE_COMPLETE,
                safety_status=st,
                video_file=v_path,
                video_subject=f"Video {tid}",
            )
            if st:
                safety_gate.save_safety_assessment(
                    {"task_id": tid, "safety_status": st, "safety_reasons": []},
                    db_path=self.db_path,
                )

        stock = operator_console.get_ready_stock(task_base_dir=self.task_base_dir, db_path=self.db_path)
        # Apenas t_pass deve ser computado
        self.assertEqual(stock["total_ready"], 1)
        self.assertEqual(stock["youtube_count"], 1)
        self.assertEqual(stock["youtube_ready"][0]["task_id"], t_pass)

    # H8: YouTube stock não é inflado por TikTok
    def test_youtube_stock_not_inflated_by_tiktok(self):
        t_id = "t-yt-published-tt-ready"
        v_path = self._create_mock_video_file(t_id)
        sm.state.update_task(
            t_id,
            state=const.TASK_STATE_COMPLETE,
            safety_status="PASS",
            video_file=v_path,
            video_subject="Video YT Published",
        )
        safety_gate.save_safety_assessment(
            {"task_id": t_id, "safety_status": "PASS", "safety_reasons": []},
            db_path=self.db_path,
        )

        # Marca como já publicado no YouTube
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                "INSERT INTO publication_events (task_id, platform, status, published_at) VALUES (?, 'youtube', 'success', ?);",
                (t_id, self.now.isoformat()),
            )

        stock = operator_console.get_ready_stock(task_base_dir=self.task_base_dir, db_path=self.db_path)
        self.assertEqual(stock["tiktok_count"], 1)
        self.assertEqual(stock["youtube_count"], 0)

        # get_autonomous_ready_stock usa estritamente youtube_count
        auto_stock = autonomous_production.get_autonomous_ready_stock(db_path=self.db_path)
        self.assertEqual(auto_stock["ready_count"], 0)
        self.assertEqual(auto_stock["youtube_count"], 0)
        self.assertTrue(auto_stock["is_below_target"])

    # H9: approved + sem slot => waiting_schedule
    def test_approved_no_slots_enters_waiting_schedule(self):
        task_id = "task-waiting-1"
        v_path = self._create_mock_video_file(task_id)

        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            video_subject="Mistérios do Oceano",
            video_file=v_path,
            safety_status=const.SAFETY_STATUS_PASS,
            profile_id=profile_manager.DEFAULT_PROFILE_ID,
        )
        safety_gate.save_safety_assessment(
            {"task_id": task_id, "safety_status": const.SAFETY_STATUS_PASS, "safety_reasons": []},
            db_path=self.db_path,
        )

        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_CURRENT_TASK_ID, task_id, db_path=self.db_path
        )

        with patch("app.services.webui_task.has_active_generation_tasks", return_value=False), \
             patch("app.services.quality_score.evaluate_quality", return_value={"quality_score": 78.0, "quality_label": "GOOD"}), \
             patch("app.services.scheduler.get_task_final_video", return_value=v_path), \
             patch("app.services.scheduler.plan_schedule", return_value=[]):  # Simula Growth Mode sem slot

            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)
            self.assertEqual(res.get("status"), "waiting_schedule")
            self.assertEqual(res.get("task_id"), task_id)
            self.assertEqual(res.get("scheduled_items"), 0)

            # Verifica persistência de waiting_task_id
            waiting_id = autonomous_production.get_autonomous_setting(
                autonomous_production.KEY_AUTONOMOUS_WAITING_TASK_ID, db_path=self.db_path
            )
            self.assertEqual(waiting_id, task_id)
            status_snap = autonomous_production.get_autonomous_status(db_path=self.db_path)
            self.assertEqual(status_snap.get("state"), autonomous_production.STATE_WAITING_SCHEDULE)

    # H10: waiting_schedule + slot futuro => agenda sem duplicar
    def test_waiting_schedule_schedules_when_slot_available(self):
        task_id = "task-waiting-slot-avail-1"
        self._persist_waiting_fixture(task_id)
        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_WAITING_TASK_ID, task_id, db_path=self.db_path
        )
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_STATE, autonomous_production.STATE_WAITING_SCHEDULE, db_path=self.db_path
        )

        with patch("app.utils.utils.task_dir", return_value=self.task_base_dir), \
             patch("app.services.scheduler.plan_schedule", return_value=[{"task_id": task_id, "scheduled_id": 101}]), \
             patch("app.services.webui_task.submit_generation") as mock_sub:

            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)
            self.assertEqual(res.get("status"), "scheduled")
            self.assertEqual(res.get("task_id"), task_id)
            self.assertEqual(res.get("scheduled_items"), 1)

            # waiting_task_id deve ter sido limpo
            waiting_id = autonomous_production.get_autonomous_setting(
                autonomous_production.KEY_AUTONOMOUS_WAITING_TASK_ID, db_path=self.db_path
            )
            self.assertEqual(waiting_id, "")
            mock_sub.assert_not_called()

    # H11: reboot preserva waiting_schedule
    def test_reboot_preserves_waiting_schedule(self):
        task_id = "task-reboot-waiting-1"
        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_WAITING_TASK_ID, task_id, db_path=self.db_path
        )

        # Simula restart lendo puramente do SQLite
        st = autonomous_production.get_autonomous_status(db_path=self.db_path)
        self.assertEqual(st.get("waiting_task_id"), task_id)

    # H12: one_shot OFF funciona uma vez
    def test_one_shot_off_executes_once(self):
        autonomous_production.set_autonomous_mode_enabled(False, db_path=self.db_path)
        self.assertFalse(autonomous_production.is_autonomous_mode_enabled(db_path=self.db_path))

        with patch("app.services.autonomous_production.get_autonomous_ready_stock") as mock_stock:
            mock_stock.return_value = {"ready_count": 5, "youtube_count": 5, "target_stock": 3, "is_below_target": False}
            res = autonomous_production.run_autonomous_cycle(force=True, one_shot=True, db_path=self.db_path, now=self.now)
            # Permitiu a execução controlada
            self.assertEqual(res.get("status"), "idle")

            # Permanece com autonomous_mode_enabled desligado no banco
            self.assertFalse(autonomous_production.is_autonomous_mode_enabled(db_path=self.db_path))

    # H13: normal OFF continua disabled
    def test_normal_off_continues_disabled(self):
        autonomous_production.set_autonomous_mode_enabled(False, db_path=self.db_path)
        res = autonomous_production.run_autonomous_cycle(force=False, one_shot=False, db_path=self.db_path, now=self.now)
        self.assertEqual(res.get("status"), "disabled")

    # H14: trend não vira USED em falha de submit
    def test_trend_not_used_on_submit_failure(self):
        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_TARGET_STOCK, "5", db_path=self.db_path
        )

        with trend_radar.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO trend_items (
                    trend_id, source, title, normalized_topic, collected_at,
                    trend_score, novelty_score, relevance_score, opportunity_score,
                    source_confidence, verification, status, niche
                )
                VALUES (
                    'trend-fail-1', 'google_trends', 'Tema Incrivel', 'tema incrivel', ?,
                    80.0, 80.0, 80.0, 80.0, 'HIGH', 'UNVERIFIED', 'APPROVED', 'curiosidades'
                );
                """,
                (self.now.isoformat(),)
            )

        with patch("app.services.autonomous_production.get_autonomous_ready_stock", return_value={"ready_count": 0, "youtube_count": 0, "target_stock": 5, "is_below_target": True}), \
             patch("app.services.webui_task.submit_generation", side_effect=RuntimeError("Pipeline submit failed")):

            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)
            self.assertEqual(res.get("status"), "error")

            # Verifica que a trend NÃO foi alterada para USED
            items = trend_radar.get_trend_items(status="APPROVED", niche="curiosidades", db_path=self.db_path)
            self.assertTrue(any(i.get("trend_id") == "trend-fail-1" for i in items))

    # H15: provider necessário indisponível => zero geração
    def test_provider_unavailable_blocks_generation(self):
        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_TARGET_STOCK, "5", db_path=self.db_path
        )

        with patch("app.services.autonomous_production.check_required_providers_preflight", return_value=(False, "FFmpeg não executável", {"FFmpeg": "UNAVAILABLE"})), \
             patch("app.services.webui_task.submit_generation") as mock_sub:

            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)
            self.assertEqual(res.get("status"), "blocked")
            self.assertEqual(res.get("reason"), "provider_unavailable")
            mock_sub.assert_not_called()

    # -----------------------------------------------------------------------
    # V12-E.1.1: Testes de Contrato Real e Quality Ready Stock
    # -----------------------------------------------------------------------

    def test_pexels_api_keys_plural_contract_preflight(self):
        # 1. Configuração canônica real com lista
        config.app["pexels_api_keys"] = ["fake-pexels-key-123"]
        config.app.pop("pexels_api_key", None)
        ok, msg, details = autonomous_production.check_required_providers_preflight(
            video_source="pexels", db_path=self.db_path
        )
        self.assertTrue(ok)
        self.assertEqual(details.get("Media"), "Pexels")

        # 2. Ausência total da chave
        config.app.pop("pexels_api_keys", None)
        config.app.pop("pexels_api_key", None)
        with patch.dict(os.environ, {}, clear=True):
            ok, msg, details = autonomous_production.check_required_providers_preflight(
                video_source="pexels", db_path=self.db_path
            )
            self.assertFalse(ok)
            self.assertIn("pexels_api_keys", msg)
            self.assertEqual(details.get("Media"), "UNAVAILABLE")

    def test_pixabay_api_keys_plural_contract_preflight(self):
        # 1. Configuração canônica real com lista
        config.app["pixabay_api_keys"] = ["fake-pixabay-key-456"]
        config.app.pop("pixabay_api_key", None)
        ok, msg, details = autonomous_production.check_required_providers_preflight(
            video_source="pixabay", db_path=self.db_path
        )
        self.assertTrue(ok)
        self.assertEqual(details.get("Media"), "Pixabay")

        # 2. Ausência total da chave
        config.app.pop("pixabay_api_keys", None)
        config.app.pop("pixabay_api_key", None)
        with patch.dict(os.environ, {}, clear=True):
            ok, msg, details = autonomous_production.check_required_providers_preflight(
                video_source="pixabay", db_path=self.db_path
            )
            self.assertFalse(ok)
            self.assertIn("pixabay_api_keys", msg)
            self.assertEqual(details.get("Media"), "UNAVAILABLE")

    def test_operator_console_provider_health_plural_pexels(self):
        # Pexels saudável via pexels_api_keys plural
        config.app["pexels_api_keys"] = ["pexels-test-token"]
        config.app.pop("pexels_api_key", None)
        summary = operator_console.get_provider_health_summary(db_path=self.db_path)
        self.assertEqual(summary["Pexels"]["status"], operator_console.PROVIDER_HEALTHY)

        # Pexels indisponível quando ausente
        config.app.pop("pexels_api_keys", None)
        config.app.pop("pexels_api_key", None)
        with patch.dict(os.environ, {}, clear=True):
            summary = operator_console.get_provider_health_summary(db_path=self.db_path)
            self.assertEqual(summary["Pexels"]["status"], operator_console.PROVIDER_UNAVAILABLE)

    def test_quality_review_excluded_from_autonomous_ready_stock(self):
        t_id = "task-review-stock"
        v_path = self._create_mock_video_file(t_id)

        sm.state.update_task(
            t_id,
            state=const.TASK_STATE_COMPLETE,
            video_subject="Fatos Curiosos",
            video_file=v_path,
            safety_status=const.SAFETY_STATUS_PASS,
        )
        # Quality 62.0 / REVIEW
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO content_quality_scores (
                    task_id, topic, quality_score, quality_label, created_at
                ) VALUES (?, ?, ?, ?, ?);
                """,
                (t_id, "Fatos Curiosos", 62.0, "REVIEW", self.now.isoformat())
            )

        stock = autonomous_production.get_autonomous_ready_stock(
            task_base_dir=self.task_base_dir, db_path=self.db_path
        )
        self.assertEqual(stock["ready_count"], 0)
        self.assertEqual(len(stock["youtube_ready"]), 0)

    def test_quality_missing_excluded_from_autonomous_ready_stock(self):
        t_id = "task-no-quality-stock"
        v_path = self._create_mock_video_file(t_id)

        sm.state.update_task(
            t_id,
            state=const.TASK_STATE_COMPLETE,
            video_subject="Espaço Sideral",
            video_file=v_path,
            safety_status=const.SAFETY_STATUS_PASS,
        )
        # Sem registro na tabela content_quality_scores (fail-closed)
        stock = autonomous_production.get_autonomous_ready_stock(
            task_base_dir=self.task_base_dir, db_path=self.db_path
        )
        self.assertEqual(stock["ready_count"], 0)
        self.assertEqual(len(stock["youtube_ready"]), 0)

    def test_quality_good_and_strong_included_in_autonomous_ready_stock(self):
        t_good = "task-good-stock"
        v_good = self._create_mock_video_file(t_good)
        sm.state.update_task(
            t_good,
            state=const.TASK_STATE_COMPLETE,
            video_subject="Tema Good",
            video_file=v_good,
            safety_status=const.SAFETY_STATUS_PASS,
        )
        t_strong = "task-strong-stock"
        v_strong = self._create_mock_video_file(t_strong)
        sm.state.update_task(
            t_strong,
            state=const.TASK_STATE_COMPLETE,
            video_subject="Tema Strong",
            video_file=v_strong,
            safety_status=const.SAFETY_STATUS_PASS,
        )

        for task_id in (t_good, t_strong):
            self._persist_waiting_fixture(task_id)
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute("DELETE FROM content_quality_scores WHERE task_id IN (?, ?)", (t_good, t_strong))

        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO content_quality_scores (
                    task_id, topic, quality_score, quality_label, created_at
                ) VALUES (?, ?, ?, ?, ?);
                """,
                (t_good, "Tema Good", 70.0, "GOOD", self.now.isoformat())
            )
            conn.execute(
                """
                INSERT INTO content_quality_scores (
                    task_id, topic, quality_score, quality_label, created_at
                ) VALUES (?, ?, ?, ?, ?);
                """,
                (t_strong, "Tema Strong", 85.0, "STRONG", self.now.isoformat())
            )

        stock = autonomous_production.get_autonomous_ready_stock(
            task_base_dir=self.task_base_dir, db_path=self.db_path
        )
        self.assertEqual(stock["ready_count"], 2)
        self.assertEqual(len(stock["youtube_ready"]), 2)

    def test_replenishment_cycle_after_quality_reject(self):
        # Meta = 1
        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_TARGET_STOCK, "1", db_path=self.db_path
        )

        # Task A existente: COMPLETE, vídeo OK, Safety PASS, mas Quality 62 / REVIEW
        task_a = "task-rejected-a"
        v_path = self._create_mock_video_file(task_a)
        sm.state.update_task(
            task_a,
            state=const.TASK_STATE_COMPLETE,
            video_subject="Tópico Rejeitado",
            video_file=v_path,
            safety_status=const.SAFETY_STATUS_PASS,
        )
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO content_quality_scores (
                    task_id, topic, quality_score, quality_label, created_at
                ) VALUES (?, ?, ?, ?, ?);
                """,
                (task_a, "Tópico Rejeitado", 62.0, "REVIEW", self.now.isoformat())
            )

        # Garante que get_autonomous_ready_stock dá 0
        stock = autonomous_production.get_autonomous_ready_stock(
            task_base_dir=self.task_base_dir, db_path=self.db_path
        )
        self.assertEqual(stock["ready_count"], 0)

        # No ciclo autônomo, com task_base_dir apontando para os mocks, detecta déficit e gera substituto B
        with patch("app.utils.utils.task_dir", return_value=self.task_base_dir), \
             patch("app.services.autonomous_production.discover_candidate_topic") as mock_disc, \
             patch("app.services.webui_task.submit_generation") as mock_sub:

            mock_disc.return_value = {"topic": "Tópico Substituto B", "origin": "test"}
            mock_sub.return_value = {"success": True, "task_id": "task-replacement-b"}

            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)
            self.assertEqual(res.get("status"), "generation_started")
            mock_sub.assert_called_once()
            called_params = mock_sub.call_args[1].get("params") or mock_sub.call_args[0][1]
            self.assertEqual(called_params.video_subject, "Tópico Substituto B")

    # -----------------------------------------------------------------------
    # Cenários Fase V12-E.1.2: Autonomous Generation Config Contract
    # -----------------------------------------------------------------------

    def test_config_video_source_pexels_preflight_and_params(self):
        """1. config video_source=pexels => preflight recebe pexels => params.video_source == pexels"""
        config.app["video_source"] = "pexels"
        config.app["pexels_api_keys"] = ["test_pexels_key"]
        params = autonomous_production.build_autonomous_video_params("Tema Pexels", db_path=self.db_path)
        self.assertEqual(params.video_source, "pexels")

        ok, msg, details = autonomous_production.check_required_providers_preflight(
            video_source=params.video_source,
            voice_name=params.voice_name,
            db_path=self.db_path,
        )
        self.assertTrue(ok)
        self.assertEqual(details.get("Media"), "Pexels")

    def test_config_video_source_pixabay_preflight_and_params(self):
        """2. config video_source=pixabay => preflight recebe pixabay => params.video_source == pixabay"""
        config.app["video_source"] = "pixabay"
        config.app["pixabay_api_keys"] = ["test_pixabay_key"]
        params = autonomous_production.build_autonomous_video_params("Tema Pixabay", db_path=self.db_path)
        self.assertEqual(params.video_source, "pixabay")

        ok, msg, details = autonomous_production.check_required_providers_preflight(
            video_source=params.video_source,
            voice_name=params.voice_name,
            db_path=self.db_path,
        )
        self.assertTrue(ok)
        self.assertEqual(details.get("Media"), "Pixabay")

    def test_persisted_voice_name_inherited_by_autonomous_params(self):
        """3. voice_name persistida => autonomous params usa exatamente a mesma voice"""
        config.ui["voice_mode"] = "tts"
        config.ui["voice_name"] = "pt-BR-FranciscaNeural-Female"
        params = autonomous_production.build_autonomous_video_params("Tema Voz Persistida", db_path=self.db_path)
        self.assertEqual(params.voice_name, "pt-BR-FranciscaNeural-Female")

    def test_empty_voice_name_when_tts_active_blocks_cycle(self):
        """4. voice_name vazio quando TTS ativo => BLOCK, nenhuma geração"""
        config.ui["voice_mode"] = "tts"
        config.ui["voice_name"] = ""
        with self.assertRaises(autonomous_production.AutonomousConfigError) as ctx:
            autonomous_production.build_autonomous_video_params("Tema Voz Vazia", db_path=self.db_path)
        self.assertIn("voice_name vazio quando TTS ativo", str(ctx.exception))

        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        with patch("app.services.webui_task.submit_generation") as mock_sub:
            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)
            self.assertEqual(res.get("status"), "blocked")
            self.assertIn("voice_name vazio quando TTS ativo", res.get("message", ""))
            mock_sub.assert_not_called()

    def test_no_voice_mode_uses_official_sentinel(self):
        """5. no-voice mode => usa sentinel oficial corretamente"""
        config.ui["voice_mode"] = "none"
        params = autonomous_production.build_autonomous_video_params("Tema Sem Voz", db_path=self.db_path)
        self.assertEqual(params.voice_name, voice.NO_VOICE_NAME)
        self.assertTrue(voice.is_no_voice(params.voice_name))

        ok, msg, details = autonomous_production.check_required_providers_preflight(
            video_source=params.video_source,
            voice_name=params.voice_name,
            db_path=self.db_path,
        )
        self.assertTrue(ok)
        self.assertEqual(details.get("TTS"), "None (No Voiceover)")

    def test_paid_source_blocks_autonomous_cycle(self):
        """6. source paga/requer confirmação => BLOCK em autonomous mode"""
        config.app["video_source"] = "wavespeed"
        with self.assertRaises(autonomous_production.AutonomousConfigError) as ctx:
            autonomous_production.build_autonomous_video_params("Tema Pago", db_path=self.db_path)
        self.assertIn("Fonte requer confirmação de custo e não é permitida em modo autônomo", str(ctx.exception))

        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        with patch("app.services.webui_task.submit_generation") as mock_sub:
            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)
            self.assertEqual(res.get("status"), "blocked")
            self.assertIn("Fonte requer confirmação de custo e não é permitida em modo autônomo", res.get("message", ""))
            mock_sub.assert_not_called()

    def test_local_source_blocks_autonomous_cycle(self):
        """6b. local source requer upload manual => BLOCK em autonomous mode"""
        config.app["video_source"] = "local"
        with self.assertRaises(autonomous_production.AutonomousConfigError):
            autonomous_production.build_autonomous_video_params("Tema Local", db_path=self.db_path)

        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        with patch("app.services.webui_task.submit_generation") as mock_sub:
            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)
            self.assertEqual(res.get("status"), "blocked")
            mock_sub.assert_not_called()

    def test_upload_voice_mode_blocks_autonomous_cycle(self):
        """6c. upload voice mode requer arquivo manual => BLOCK em autonomous mode"""
        config.ui["voice_mode"] = "upload"
        with self.assertRaises(autonomous_production.AutonomousConfigError) as ctx:
            autonomous_production.build_autonomous_video_params("Tema Upload Voice", db_path=self.db_path)
        self.assertIn("Modo de voz 'upload' requer áudio manual e não é permitido em modo autônomo", str(ctx.exception))

        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        with patch("app.services.webui_task.submit_generation") as mock_sub:
            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)
            self.assertEqual(res.get("status"), "blocked")
            mock_sub.assert_not_called()

    def test_aspect_and_subtitle_settings_inherited_from_persisted_config(self):
        """7. parâmetros de aspect/subtitle relevantes são herdados da configuração persistida"""
        config.ui["video_aspect_pexels"] = "16:9"
        config.ui["subtitle_enabled"] = False
        config.ui["font_name"] = "CustomFont.ttf"
        config.ui["font_size"] = 52
        config.ui["bgm_type"] = "random"
        config.ui["bgm_volume"] = 0.35

        params = autonomous_production.build_autonomous_video_params("Tema Config", db_path=self.db_path)
        self.assertEqual(params.video_aspect, VideoAspect.landscape)
        self.assertFalse(params.subtitle_enabled)
        self.assertEqual(params.font_name, "CustomFont.ttf")
        self.assertEqual(params.font_size, 52)
        self.assertEqual(params.bgm_type, "random")
        self.assertAlmostEqual(params.bgm_volume, 0.35)

    def test_reboot_without_streamlit_session_state_resolves_params(self):
        """8. reinício sem Streamlit/session_state => parâmetros continuam resolvidos corretamente"""
        import sys
        # Garante ausência ou não dependência de st.session_state
        params = autonomous_production.build_autonomous_video_params("Tema Post-Reboot", db_path=self.db_path)
        self.assertIsNotNone(params)
        self.assertEqual(params.video_source, "pexels")
        self.assertEqual(params.voice_name, "pt-BR-AntonioNeural-Male")

    def test_preflight_receives_exact_submitted_params(self):
        """9. preflight recebe exatamente os parâmetros usados no submit"""
        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        config.ui["voice_name"] = "pt-BR-FranciscaNeural-Female"
        config.app["video_source"] = "pexels"

        preflight_calls = []
        orig_preflight = autonomous_production.check_required_providers_preflight

        def spy_preflight(*args, **kwargs):
            preflight_calls.append((args, kwargs))
            return orig_preflight(*args, **kwargs)

        with patch("app.utils.utils.task_dir", return_value=self.task_base_dir), \
             patch("app.services.autonomous_production.discover_candidate_topic", return_value={"topic": "Tema Exato", "origin": "test"}), \
             patch("app.services.autonomous_production.check_required_providers_preflight", side_effect=spy_preflight), \
             patch("app.services.webui_task.submit_generation") as mock_sub:

            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)
            self.assertEqual(res.get("status"), "generation_started")
            mock_sub.assert_called_once()
            submitted_params = mock_sub.call_args[1].get("params") or mock_sub.call_args[0][1]

            # O último preflight realizado antes do submit deve validar os mesmos campos
            last_preflight = preflight_calls[-1][1]
            self.assertEqual(last_preflight.get("video_source"), submitted_params.video_source)
            self.assertEqual(last_preflight.get("voice_name"), submitted_params.voice_name)

    def test_zero_external_api_calls_and_no_publishing(self):
        """10 & 11. zero APIs externas reais e nenhuma publicação"""
        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        with patch("app.utils.utils.task_dir", return_value=self.task_base_dir), \
             patch("app.services.autonomous_production.discover_candidate_topic", return_value={"topic": "Tema Offline", "origin": "test"}), \
             patch("app.services.webui_task.submit_generation"):

            autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)
            self.mock_upload_video.assert_not_called()
            self.mock_cross_post.assert_not_called()
            self.mock_publish_task.assert_not_called()

    def test_autonomous_off_remains_off(self):
        """12. Autonomous OFF continua OFF"""
        autonomous_production.set_autonomous_mode_enabled(False, db_path=self.db_path)
        self.assertFalse(autonomous_production.is_autonomous_mode_enabled(db_path=self.db_path))
        res = autonomous_production.run_autonomous_cycle(db_path=self.db_path, now=self.now)
        self.assertEqual(res.get("status"), "disabled")
        self.assertFalse(autonomous_production.is_autonomous_mode_enabled(db_path=self.db_path))


    # -----------------------------------------------------------------------
    # FASE V12-E.2.1: ONE-CYCLE / ONE-TRANSITION INVARIANT TESTS
    # -----------------------------------------------------------------------

    def _setup_current_task_with_video(self, task_id: str, safety_status: str = const.SAFETY_STATUS_PASS) -> str:
        """Helper: cria task com vídeo mock, Safety salvo e aponta current_task_id para ela."""
        v_path = self._create_mock_video_file(task_id)
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            video_subject=f"Topico {task_id}",
            video_file=v_path,
            safety_status=safety_status,
            profile_id=profile_manager.DEFAULT_PROFILE_ID,
        )
        safety_gate.save_safety_assessment(
            {
                "task_id": task_id,
                "safety_status": safety_status,
                "safety_reasons": [],
                "checked_at": self.now.isoformat(),
            },
            db_path=self.db_path,
        )
        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_CURRENT_TASK_ID, task_id, db_path=self.db_path
        )
        return v_path

    # T1: current_task + Safety PASS + Quality 45 => rejected, zero submit_generation
    def test_v12e21_t1_safety_pass_quality_45_rejected_no_new_task(self):
        """Safety PASS + Quality 45/WEAK => status=rejected, zero submit_generation no mesmo ciclo."""
        task_id = "v12e21-t1-quality-45"
        v_path = self._setup_current_task_with_video(task_id, const.SAFETY_STATUS_PASS)

        with patch("app.services.webui_task.has_active_generation_tasks", return_value=False), \
             patch("app.services.scheduler.get_task_final_video", return_value=v_path), \
             patch("app.services.quality_score.evaluate_quality", return_value={
                 "quality_score": 45.0,
                 "quality_label": quality_score.LABEL_WEAK,
             }), \
             patch("app.services.webui_task.submit_generation") as mock_sub:

            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)

            self.assertEqual(res.get("status"), "rejected")
            self.assertIn("task_id", res)
            self.assertEqual(res.get("task_id"), task_id)
            mock_sub.assert_not_called()

    # T2: current_task + Safety REVIEW => rejected, zero nova task
    def test_v12e21_t2_safety_review_rejected_no_new_task(self):
        """Safety REVIEW => status=rejected, zero submit_generation no mesmo ciclo."""
        task_id = "v12e21-t2-safety-review"
        v_path = self._setup_current_task_with_video(task_id, const.SAFETY_STATUS_REVIEW)

        with patch("app.services.webui_task.has_active_generation_tasks", return_value=False), \
             patch("app.services.scheduler.get_task_final_video", return_value=v_path), \
             patch("app.services.webui_task.submit_generation") as mock_sub:

            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)

            self.assertEqual(res.get("status"), "rejected")
            self.assertIn("REVIEW", res.get("reason", "") + res.get("message", ""))
            mock_sub.assert_not_called()

    # T3: current_task + Safety BLOCK => rejected, zero nova task
    def test_v12e21_t3_safety_block_rejected_no_new_task(self):
        """Safety BLOCK => status=rejected, zero submit_generation no mesmo ciclo."""
        task_id = "v12e21-t3-safety-block"
        v_path = self._setup_current_task_with_video(task_id, const.SAFETY_STATUS_BLOCK)

        with patch("app.services.webui_task.has_active_generation_tasks", return_value=False), \
             patch("app.services.scheduler.get_task_final_video", return_value=v_path), \
             patch("app.services.webui_task.submit_generation") as mock_sub:

            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)

            self.assertEqual(res.get("status"), "rejected")
            self.assertIn("BLOCK", res.get("reason", "") + res.get("message", ""))
            mock_sub.assert_not_called()

    # T4: current_task + Quality 69 => rejected, zero nova task
    def test_v12e21_t4_quality_69_rejected_no_new_task(self):
        """Quality 69/WEAK => status=rejected (abaixo do limiar 70), zero submit_generation."""
        task_id = "v12e21-t4-quality-69"
        v_path = self._setup_current_task_with_video(task_id, const.SAFETY_STATUS_PASS)

        with patch("app.services.webui_task.has_active_generation_tasks", return_value=False), \
             patch("app.services.scheduler.get_task_final_video", return_value=v_path), \
             patch("app.services.quality_score.evaluate_quality", return_value={
                 "quality_score": 69.0,
                 "quality_label": quality_score.LABEL_REVIEW,
             }), \
             patch("app.services.webui_task.submit_generation") as mock_sub:

            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)

            self.assertEqual(res.get("status"), "rejected")
            mock_sub.assert_not_called()

    # T5: current_task + Quality 70 => approved/scheduled ou waiting_schedule, zero segunda geração
    def test_v12e21_t5_quality_70_approved_zero_second_generation(self):
        """Quality 70/GOOD => approved e ciclo encerra (scheduled ou waiting_schedule), zero segunda geração."""
        task_id = "v12e21-t5-quality-70"
        v_path = self._setup_current_task_with_video(task_id, const.SAFETY_STATUS_PASS)

        with patch("app.services.webui_task.has_active_generation_tasks", return_value=False), \
             patch("app.services.scheduler.get_task_final_video", return_value=v_path), \
             patch("app.services.quality_score.evaluate_quality", return_value={
                 "quality_score": 70.0,
                 "quality_label": quality_score.LABEL_GOOD,
             }), \
             patch("app.services.webui_task.submit_generation") as mock_sub:

            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)

            # Deve ter encerrado com scheduled ou waiting_schedule — nunca com generation_started
            self.assertIn(res.get("status"), ("scheduled", "waiting_schedule"))
            # Zero geração adicional no mesmo ciclo
            mock_sub.assert_not_called()

    # T6: current_task interrompida (PROCESSING, sem vídeo) => recovery_error, zero geração
    def test_v12e21_t6_interrupted_task_recovery_error_no_new_generation(self):
        """Tarefa em PROCESSING sem vídeo final => recovery_error, zero submit_generation no mesmo ciclo."""
        task_id = "v12e21-t6-interrupted"
        # Não cria vídeo de propósito para simular crash
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_PROCESSING,
            progress=50,
            video_subject="Tarefa Interrompida",
            profile_id=profile_manager.DEFAULT_PROFILE_ID,
        )
        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_CURRENT_TASK_ID, task_id, db_path=self.db_path
        )

        with patch("app.services.webui_task.has_active_generation_tasks", return_value=False), \
             patch("app.services.scheduler.get_task_final_video", return_value=None), \
             patch("app.services.webui_task.submit_generation") as mock_sub:

            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)

            self.assertEqual(res.get("status"), "recovery_error")
            self.assertEqual(res.get("task_id"), task_id)
            self.assertEqual(res.get("reason"), "generation_interrupted")
            mock_sub.assert_not_called()

    # T7: ciclo seguinte após rejected + estoque abaixo da meta => pode gerar exatamente uma nova task
    def test_v12e21_t7_next_cycle_after_reject_can_generate_one_task(self):
        """Após rejeição, no ciclo seguinte (sem current_task_id), se estoque abaixo da meta pode gerar uma task."""
        # current_task_id já foi limpo (ciclo anterior terminou com rejected)
        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_CURRENT_TASK_ID, "", db_path=self.db_path
        )
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_TARGET_STOCK, "1", db_path=self.db_path
        )

        with patch("app.services.webui_task.has_active_generation_tasks", return_value=False), \
             patch("app.services.autonomous_production.get_autonomous_ready_stock", return_value={
                 "ready_count": 0, "youtube_count": 0, "target_stock": 1, "is_below_target": True,
             }), \
             patch("app.services.autonomous_production.discover_candidate_topic",
                   return_value={"topic": "Reposição Ciclo Seguinte", "origin": "test"}), \
             patch("app.services.webui_task.submit_generation") as mock_sub:

            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)

            self.assertEqual(res.get("status"), "generation_started")
            # Exatamente uma nova task — não mais de uma
            mock_sub.assert_called_once()

    # T8: one_shot nunca realiza duas transições principais (reject + generate) no mesmo ciclo
    def test_v12e21_t8_one_shot_never_two_transitions(self):
        """one_shot=True com current_task rejected => ciclo encerra em 'rejected', sem segunda geração."""
        task_id = "v12e21-t8-one-shot"
        v_path = self._setup_current_task_with_video(task_id, const.SAFETY_STATUS_PASS)
        # Desliga autonomous mode para confirmar que one_shot ainda aplica a regra
        autonomous_production.set_autonomous_mode_enabled(False, db_path=self.db_path)
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_CURRENT_TASK_ID, task_id, db_path=self.db_path
        )

        with patch("app.services.webui_task.has_active_generation_tasks", return_value=False), \
             patch("app.services.scheduler.get_task_final_video", return_value=v_path), \
             patch("app.services.quality_score.evaluate_quality", return_value={
                 "quality_score": 40.0,
                 "quality_label": quality_score.LABEL_WEAK,
             }), \
             patch("app.services.webui_task.submit_generation") as mock_sub:

            res = autonomous_production.run_autonomous_cycle(
                force=True, one_shot=True, db_path=self.db_path, now=self.now
            )

            # Deve encerrar em rejected — nunca em generation_started
            self.assertEqual(res.get("status"), "rejected")
            mock_sub.assert_not_called()

    # T9: autonomous contínuo (enabled=True) também respeita uma transição por ciclo
    def test_v12e21_t9_continuous_mode_also_one_transition_per_cycle(self):
        """autonomous_mode_enabled=True com current_task rejected => 'rejected', sem geração no mesmo ciclo."""
        task_id = "v12e21-t9-continuous"
        v_path = self._setup_current_task_with_video(task_id, const.SAFETY_STATUS_PASS)

        with patch("app.services.webui_task.has_active_generation_tasks", return_value=False), \
             patch("app.services.scheduler.get_task_final_video", return_value=v_path), \
             patch("app.services.quality_score.evaluate_quality", return_value={
                 "quality_score": 55.0,
                 "quality_label": quality_score.LABEL_REVIEW,
             }), \
             patch("app.services.webui_task.submit_generation") as mock_sub:

            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)

            self.assertEqual(res.get("status"), "rejected")
            mock_sub.assert_not_called()

    # T10: zero chamadas externas reais em todos os fluxos de rejeição
    def test_v12e21_t10_zero_external_calls_on_rejection(self):
        """Nenhuma chamada a APIs externas ou publicação durante rejeição."""
        task_id = "v12e21-t10-zero-ext"
        v_path = self._setup_current_task_with_video(task_id, const.SAFETY_STATUS_BLOCK)

        with patch("app.services.webui_task.has_active_generation_tasks", return_value=False), \
             patch("app.services.scheduler.get_task_final_video", return_value=v_path), \
             patch("app.services.webui_task.submit_generation") as mock_sub:

            autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)

            mock_sub.assert_not_called()
            self.mock_upload_video.assert_not_called()
            self.mock_cross_post.assert_not_called()
            self.mock_publish_task.assert_not_called()



    def _persist_waiting_fixture(self, task_id):
        video = self._create_mock_video_file(task_id)
        channels = profile_manager.list_channels(profile_id="default", db_path=self.db_path)
        for channel in channels[1:]:
            profile_manager.set_channel_enabled(channel["channel_id"], False, db_path=self.db_path)
        scheduler.save_task_platforms(task_id, ["youtube"], db_path=self.db_path)
        profile_manager.save_task_profile(task_id, "default", db_path=self.db_path)
        safety_gate.save_safety_assessment({
            "task_id": task_id, "safety_status": "PASS", "safety_reasons": [],
            "checked_at": self.now.isoformat(),
        }, db_path=self.db_path)
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                "INSERT INTO content_quality_scores "
                "(task_id, topic, quality_score, quality_label, created_at) VALUES (?, ?, 78.3, 'GOOD', ?)",
                (task_id, task_id, self.now.isoformat()),
            )
        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_WAITING_TASK_ID, task_id, db_path=self.db_path)
        return video

    def _retry_persisted_waiting(self, memory=None, one_shot=False, expected_generations=0):
        with patch.object(sm.state, "get_task", return_value=memory), \
             patch("app.utils.utils.task_dir", return_value=self.task_base_dir), \
             patch("app.services.webui_task.submit_generation") as submit, \
             patch("socket.socket.connect", side_effect=AssertionError("External network forbidden")):
            result = autonomous_production.run_autonomous_cycle(
                force=True, one_shot=one_shot, db_path=self.db_path, now=self.now)
        self.assertEqual(submit.call_count, expected_generations)
        self.mock_upload_video.assert_not_called()
        self.mock_cross_post.assert_not_called()
        self.mock_publish_task.assert_not_called()
        self.assertFalse(scheduler.get_all_settings(self.db_path)["auto_publish_enabled"])
        return result

    def test_v12e22_memory_present_absent_and_incomplete(self):
        task_id = "persistent-waiting"
        video = self._persist_waiting_fixture(task_id)
        for memory in (None, {"task_id": task_id}, {
            "task_id": task_id, "state": const.TASK_STATE_COMPLETE, "video_file": video,
        }):
            with self.subTest(memory=memory):
                with scheduler.get_connection(self.db_path) as conn:
                    conn.execute("DELETE FROM scheduled_posts")
                autonomous_production.set_autonomous_setting(
                    autonomous_production.KEY_AUTONOMOUS_WAITING_TASK_ID, task_id, db_path=self.db_path)
                self.assertEqual(self._retry_persisted_waiting(memory)["status"], "scheduled")
                with scheduler.get_connection(self.db_path) as conn:
                    rows = conn.execute("SELECT * FROM scheduled_posts").fetchall()
                self.assertTrue(rows)
                self.assertTrue(all(r["platform"] == "youtube" and r["profile_id"] == "default" for r in rows))

    def test_v12e22_fail_closed(self):
        cases = ("video", "empty_video", "BLOCK", "REVIEW", "safety_missing", "quality_missing",
                 "low_quality", "bad_label", "profile_disabled", "profile_missing", "channel_disabled", "destination_missing")
        for case in cases:
            with self.subTest(case=case):
                task_id = "fail-" + case
                video = self._persist_waiting_fixture(task_id)
                with scheduler.get_connection(self.db_path) as conn:
                    if case == "video":
                        os.remove(video)
                    elif case == "empty_video":
                        open(video, "wb").close()
                    elif case in ("BLOCK", "REVIEW"):
                        conn.execute("UPDATE monetization_safety SET safety_status=? WHERE task_id=?", (case, task_id))
                    elif case == "safety_missing":
                        conn.execute("DELETE FROM monetization_safety WHERE task_id=?", (task_id,))
                    elif case == "quality_missing":
                        conn.execute("DELETE FROM content_quality_scores WHERE task_id=?", (task_id,))
                    elif case == "low_quality":
                        conn.execute("UPDATE content_quality_scores SET quality_score=69 WHERE task_id=?", (task_id,))
                    elif case == "bad_label":
                        conn.execute("UPDATE content_quality_scores SET quality_label='REVIEW' WHERE task_id=?", (task_id,))
                    elif case == "profile_missing":
                        conn.execute("DELETE FROM task_profiles WHERE task_id=?", (task_id,))
                    elif case == "destination_missing":
                        conn.execute("DELETE FROM task_platforms WHERE task_id=?", (task_id,))
                if case == "profile_disabled":
                    with scheduler.get_connection(self.db_path) as conn:
                        conn.execute("UPDATE content_profiles SET is_active=0 WHERE id='default'")
                channels = profile_manager.list_channels(profile_id="default", db_path=self.db_path)
                if case == "channel_disabled":
                    for channel in channels:
                        profile_manager.set_channel_enabled(channel["channel_id"], False, db_path=self.db_path)
                result = self._retry_persisted_waiting()
                self.assertEqual(result["reason"], "waiting_recovery_failed")
                with scheduler.get_connection(self.db_path) as conn:
                    self.assertEqual(conn.execute("SELECT count(*) FROM scheduled_posts").fetchone()[0], 0)
                profile_manager.set_profile_active("default", True, db_path=self.db_path)
                for channel in channels:
                    profile_manager.set_channel_enabled(channel["channel_id"], bool(channel["is_enabled"]), db_path=self.db_path)

    def test_v12e22_no_growth_slot(self):
        self._persist_waiting_fixture("occupies-warmup-slot")
        self.assertEqual(self._retry_persisted_waiting()["status"], "scheduled")
        task_id = "no-slot"
        self._persist_waiting_fixture(task_id)
        self.assertEqual(self._retry_persisted_waiting(expected_generations=1)["status"], "generation_started")
        self.assertEqual(autonomous_production.get_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_WAITING_TASK_ID, db_path=self.db_path), task_id)

    def test_v12e22_persisted_tiktok_is_not_scheduled(self):
        task_id = "youtube-only-recovery"
        self._persist_waiting_fixture(task_id)
        scheduler.save_task_platforms(task_id, ["youtube", "tiktok"], db_path=self.db_path)
        self.assertEqual(self._retry_persisted_waiting()["status"], "scheduled")
        with scheduler.get_connection(self.db_path) as conn:
            platforms = [r[0] for r in conn.execute("SELECT platform FROM scheduled_posts")]
        self.assertEqual(platforms, ["youtube"])

    def test_v12e22_retry_idempotent_and_terminal(self):
        task_id = "retry-idempotent"
        self._persist_waiting_fixture(task_id)
        self.assertEqual(self._retry_persisted_waiting()["status"], "scheduled")
        with scheduler.get_connection(self.db_path) as conn:
            count = conn.execute("SELECT count(*) FROM scheduled_posts").fetchone()[0]
        for status in ("planned", "ready", "published", "cancelled"):
            with self.subTest(status=status):
                with scheduler.get_connection(self.db_path) as conn:
                    conn.execute("UPDATE scheduled_posts SET status=?", (status,))
                autonomous_production.set_autonomous_setting(
                    autonomous_production.KEY_AUTONOMOUS_WAITING_TASK_ID, task_id, db_path=self.db_path)
                autonomous_production.set_autonomous_setting(
                    autonomous_production.KEY_AUTONOMOUS_CURRENT_TASK_ID, "", db_path=self.db_path)
                self.assertEqual(self._retry_persisted_waiting(expected_generations=1)["status"], "generation_started")
                with scheduler.get_connection(self.db_path) as conn:
                    self.assertEqual(conn.execute("SELECT count(*) FROM scheduled_posts").fetchone()[0], count)

    def test_v12e22_one_shot_with_autonomous_off(self):
        self._persist_waiting_fixture("one-shot-recovery")
        autonomous_production.set_autonomous_mode_enabled(False, db_path=self.db_path)
        self.assertEqual(self._retry_persisted_waiting(one_shot=True)["status"], "scheduled")
        self.assertFalse(autonomous_production.is_autonomous_mode_enabled(db_path=self.db_path))


if __name__ == "__main__":
    unittest.main()
