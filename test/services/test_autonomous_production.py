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
from app.services import (
    autonomous_production,
    operator_console,
    profile_manager,
    quality_score,
    safety_gate,
    scheduler,
    trend_radar,
    webui_task,
)
from app.services import state as sm


class TestAutonomousProductionLoop(unittest.TestCase):
    def setUp(self):
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

    def tearDown(self):
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

        # Mock operator_console.get_ready_stock retornando total_ready = 2 (estoque atingido)
        with patch("app.services.operator_console.get_ready_stock") as mock_stock, \
             patch("app.services.webui_task.submit_generation") as mock_sub:
            mock_stock.return_value = {"total_ready": 2, "youtube_count": 2, "tiktok_count": 2}
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

        with patch("app.services.operator_console.get_ready_stock") as mock_stock, \
             patch("app.services.autonomous_production.discover_candidate_topic") as mock_disc, \
             patch("app.services.webui_task.submit_generation") as mock_sub:
            mock_stock.return_value = {"total_ready": 1, "youtube_count": 1}
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

        with patch("app.services.operator_console.get_ready_stock") as mock_stock, \
             patch("app.services.autonomous_production.discover_candidate_topic") as mock_disc, \
             patch("app.services.webui_task.submit_generation") as mock_sub:
            mock_stock.return_value = {"total_ready": 0}  # Déficit de 10
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

        with patch("app.services.operator_console.get_ready_stock") as mock_stock, \
             patch("app.services.webui_task.submit_generation") as mock_sub:
            mock_stock.return_value = {"total_ready": 0}
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


if __name__ == "__main__":
    unittest.main()
