"""
test/services/test_p3_quiz_multi_dest.py
========================================
Testes direcionados da Fase P3:
1. Seleção persistente dos dois formatos de quiz (quiz_dilemma e quiz_paper) por canal.
2. Roteamento para o renderizador correto (QuizEngine Q0-R vs PaperQuizEngine P1.3).
3. Autonomia herdando o formato salvo.
4. Resolução independente YouTube e TikTok via banco de dados (sem IDs fixos).
5. Idempotência por conta/plataforma.
6. Bloqueio factual rigoroso para quizzes não verificados.
7. Duração obrigatória na faixa 60-65 segundos.
8. Bypass completo do Google Flow para os formatos de quiz.
9. Preservação integral do pipeline tradicional.
"""

import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.models import const
from app.models.schema import VideoParams
from app.services import (
    autonomous_production,
    operator_console,
    post_for_me,
    profile_manager,
    scheduler,
    state as sm,
    task as tm,
)


class TestP3QuizMultiDestination(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_p3.db")
        self.task_id = "test_p3_task_id"

        # Inicializa dbs
        operator_console.init_operator_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        scheduler.init_db(self.db_path)

        # Garante nó local como PRIMARY
        operator_console.reset_instance_for_testing()
        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._is_primary = True

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_format_selection_persistence_channel_factory(self):
        """1. Seleção persistente de quiz_paper, quiz_dilemma e tradicional com multi-destino."""
        # A. Canal Quiz de Papel com YouTube e TikTok
        settings_paper = profile_manager.ChannelWorkspaceSettings()
        settings_paper.editorial.video_format = "quiz_paper"
        settings_paper.editorial.content_style = "quiz_paper"
        settings_paper.editorial.closing_type = "comments"
        settings_paper.editorial.num_questions = 5

        res_paper = profile_manager.onboard_channel_workspace(
            name="Curiosidades em Papel",
            niche="curiosidades",
            topic_brief="Fatos históricos em papel",
            settings=settings_paper,
            destinations=[
                {"platform": "youtube", "external_account_id": "UC_PAPER_YT_0123456789", "is_enabled": True},
                {"platform": "tiktok", "external_account_id": "tt_paper_01", "is_enabled": True},
            ],
            db_path=self.db_path,
        )
        pid_paper = res_paper["profile"]["id"]
        saved_paper = profile_manager.get_profile_settings(pid_paper, db_path=self.db_path)
        self.assertEqual(saved_paper.editorial.video_format, "quiz_paper")
        self.assertEqual(saved_paper.editorial.num_questions, 5)

        channels_paper = profile_manager.list_channels(profile_id=pid_paper, db_path=self.db_path)
        yt_c = next((c for c in channels_paper if c.get("platform") == "youtube"), None)
        tt_c = next((c for c in channels_paper if c.get("platform") == "tiktok"), None)
        self.assertIsNotNone(yt_c)
        self.assertEqual(yt_c.get("external_account_id"), "UC_PAPER_YT_0123456789")
        self.assertIsNotNone(tt_c)
        self.assertEqual(tt_c.get("external_account_id"), "tt_paper_01")

        # B. Canal Quiz Dilema com YouTube apenas
        settings_dilemma = profile_manager.ChannelWorkspaceSettings()
        settings_dilemma.editorial.video_format = "quiz_dilemma"
        settings_dilemma.editorial.closing_type = "auto"
        settings_dilemma.editorial.num_questions = 8

        res_dilemma = profile_manager.onboard_channel_workspace(
            name="Dilemas Noturnos",
            niche="dilemas",
            topic_brief="Escolhas impossíveis",
            settings=settings_dilemma,
            destinations=[
                {"platform": "youtube", "external_account_id": "UC_DILEMMA_YT_012345678", "is_enabled": True},
            ],
            db_path=self.db_path,
        )
        pid_dilemma = res_dilemma["profile"]["id"]
        saved_dilemma = profile_manager.get_profile_settings(pid_dilemma, db_path=self.db_path)
        self.assertEqual(saved_dilemma.editorial.video_format, "quiz_dilemma")
        self.assertEqual(saved_dilemma.editorial.num_questions, 8)

        # C. Canal Tradicional somente estoque (sem destinos)
        settings_trad = profile_manager.ChannelWorkspaceSettings()
        settings_trad.editorial.video_format = "traditional"
        res_trad = profile_manager.onboard_channel_workspace(
            name="Histórias Globais",
            niche="misterio",
            topic_brief="Histórias investigativas",
            settings=settings_trad,
            destinations=[],
            db_path=self.db_path,
        )
        pid_trad = res_trad["profile"]["id"]
        channels_trad = profile_manager.list_channels(profile_id=pid_trad, db_path=self.db_path)
        self.assertTrue(all(not c.get("is_enabled") for c in channels_trad))

    def test_02_independent_youtube_and_tiktok_resolution(self):
        """2. Resolução independente YouTube e TikTok via banco de dados sem IDs fixos."""
        settings = profile_manager.ChannelWorkspaceSettings()
        res = profile_manager.onboard_channel_workspace(
            name="Multi Canal Teste",
            niche="geral",
            settings=settings,
            destinations=[
                {"platform": "youtube", "external_account_id": "UC_MULTI_YT_123456789012", "is_enabled": True},
                {"platform": "tiktok", "external_account_id": "tt_multi_user_88", "is_enabled": True},
            ],
            db_path=self.db_path,
        )
        pid = res["profile"]["id"]

        # Resolução YouTube
        yt_resolved = post_for_me.resolve_target_youtube_channel_id(profile_id=pid, db_path=self.db_path)
        self.assertEqual(yt_resolved, "UC_MULTI_YT_123456789012")

        # Resolução TikTok
        tt_resolved = post_for_me.resolve_target_tiktok_user_id(profile_id=pid, db_path=self.db_path)
        self.assertEqual(tt_resolved, "tt_multi_user_88")

        # Fail-closed quando inexistente
        self.assertIsNone(post_for_me.resolve_target_youtube_channel_id(profile_id="nonexistent", db_path=self.db_path))
        self.assertIsNone(post_for_me.resolve_target_tiktok_user_id(profile_id="nonexistent", db_path=self.db_path))

    @patch("scripts.poc_quiz_paper_render.PaperQuizEngine.render")
    @patch("scripts.poc_quiz_render.QuizEngine.render")
    @patch("app.services.quiz_assets.QuizAssetManager.process_quiz")
    @patch("app.services.quiz_generator.QuizContentGenerator.generate_paper_quiz_structure")
    @patch("app.services.quiz_safety_gate.evaluate_quiz_script_safety", return_value={"safety_status": const.SAFETY_STATUS_PASS, "safety_reasons": []})
    @patch("app.services.quiz_safety_gate.evaluate_quiz_duration_safety", return_value={"safety_status": const.SAFETY_STATUS_PASS, "safety_reasons": []})
    @patch("app.services.media_quality.evaluate_final_media_quality", return_value={"status": "PASS", "reasons": [], "metrics": {"duration": 62.0}})
    def test_03_routing_to_paper_quiz_engine(
        self,
        mock_mq,
        mock_dur_safety,
        mock_script_safety,
        mock_gen_paper,
        mock_process_quiz,
        mock_dilemma_render,
        mock_paper_render,
    ):
        """3. Roteamento: quiz_paper aciona PaperQuizEngine (P1.3) e não aciona QuizEngine (Q0-R)."""
        mock_gen_paper.return_value = {
            "niche": "historia",
            "format_type": "factual",
            "questions": [
                {
                    "id": "q1",
                    "header": "PERGUNTA 1:",
                    "narration": "Quem pintou a Mona Lisa no século dezesseis?",
                    "correct_option_index": 0,
                    "verified": True,
                    "evidence_source": "Enciclopedia Britanica",
                    "options": ["Leonardo da Vinci", "Pablo Picasso", "Vincent van Gogh", "Claude Monet"],
                }
            ],
        }
        mock_process_quiz.return_value = {
            "questions": mock_gen_paper.return_value["questions"],
            "asset_provenance": [],
        }
        mock_paper_render.return_value = {
            "status": "CONCLUIDO_COM_SUCESSO",
            "duration": 62.0,
        }

        params = VideoParams(
            video_subject="Grandes Pintores",
            narrative_structure="quiz_paper",
        )

        res = tm._run_quiz_pipeline(
            task_id=self.task_id,
            params=params,
            stop_at="video",
        )

        self.assertNotIn("error", res)
        mock_paper_render.assert_called_once()
        mock_dilemma_render.assert_not_called()
        task_state = sm.state.get_task(self.task_id)
        self.assertEqual(task_state.get("stage"), "READY_STOCK")

    @patch("app.services.task._run_quiz_pipeline")
    @patch("app.services.flow_account_pool.select_flow_account")
    @patch("app.services.task.generate_script", return_value="Roteiro tradicional de teste longo e completo para bypass.")
    @patch("app.services.quiz_safety_gate.evaluate_quiz_script_safety", return_value={"safety_status": const.SAFETY_STATUS_PASS, "safety_reasons": []})
    @patch("app.utils.utils.check_ffmpeg_ready", return_value=True)
    def test_04_google_flow_bypass_and_traditional_preservation(
        self,
        mock_ffmpeg,
        mock_safety,
        mock_gen_script,
        mock_flow,
        mock_quiz_pipe,
    ):
        """4. Quizzes bypassam completamente Google Flow; pipeline tradicional é preservado."""
        mock_quiz_pipe.return_value = {"status": "ok"}

        # A. Quiz de Papel
        params_paper = VideoParams(
            video_subject="Quiz Papel",
            narrative_structure="quiz_paper",
        )
        tm._run_pipeline(task_id="task_p", params=params_paper, stop_at="video")
        mock_flow.assert_not_called()

        # B. Quiz Dilema
        params_dilemma = VideoParams(
            video_subject="Quiz Dilema",
            narrative_structure="quiz_dilemma",
        )
        tm._run_pipeline(task_id="task_d", params=params_dilemma, stop_at="video")
        mock_flow.assert_not_called()

        # C. Tradicional preservado (chama pipeline comum, não chama quiz pipeline)
        mock_quiz_pipe.reset_mock()
        params_trad = VideoParams(
            video_subject="Ciência Tradicional",
            narrative_structure=None,
        )
        tm._run_pipeline(task_id="task_t", params=params_trad, stop_at="script")
        mock_quiz_pipe.assert_not_called()
        mock_gen_script.assert_called_once()

    @patch("app.services.quiz_generator.QuizContentGenerator.generate_paper_quiz_structure")
    @patch("app.services.quiz_safety_gate.evaluate_quiz_script_safety", return_value={"safety_status": const.SAFETY_STATUS_PASS, "safety_reasons": []})
    def test_05_factual_safety_blocking_unverified(self, mock_safety, mock_gen_paper):
        """5. Quizzes factuais não verificados são estritamente bloqueados no factual_gate."""
        mock_gen_paper.return_value = {
            "niche": "ciencia",
            "format_type": "factual",
            "questions": [
                {
                    "id": "q1",
                    "header": "PERGUNTA 1:",
                    "narration": "Qual elemento químico possui símbolo Au na tabela periódica?",
                    "verified": False,
                    "publication_gate": "BLOCKED_PENDING_EXTERNAL_AUDIT",
                    "evidence_source": "LLM text output",
                    "options": ["Ouro", "Prata", "Cobre", "Chumbo"],
                }
            ],
        }

        params = VideoParams(
            video_subject="Química Geral",
            narrative_structure="quiz_paper",
        )

        res = tm._run_quiz_pipeline(
            task_id="task_unverified",
            params=params,
            stop_at="video",
        )

        self.assertIn("error", res)
        self.assertEqual(res.get("failed_stage"), "factual_gate")
        task_state = sm.state.get_task("task_unverified")
        self.assertEqual(task_state.get("state"), const.TASK_STATE_FAILED)
        self.assertNotEqual(task_state.get("stage"), "READY_STOCK")

    @patch("scripts.poc_quiz_paper_render.PaperQuizEngine.render")
    @patch("app.services.quiz_assets.QuizAssetManager.process_quiz")
    @patch("app.services.quiz_generator.QuizContentGenerator.generate_paper_quiz_structure")
    @patch("app.services.quiz_safety_gate.evaluate_quiz_script_safety", return_value={"safety_status": const.SAFETY_STATUS_PASS, "safety_reasons": []})
    def test_06_duration_gate_enforcement(
        self,
        mock_script_safety,
        mock_gen_paper,
        mock_process_quiz,
        mock_paper_render,
    ):
        """6. Duração obrigatória entre 60 e 65 segundos: durações fora da faixa são bloqueadas."""
        mock_gen_paper.return_value = {
            "niche": "historia",
            "format_type": "factual",
            "questions": [
                {
                    "id": "q1",
                    "header": "PERGUNTA 1:",
                    "narration": "Pergunta teste",
                    "verified": True,
                    "evidence_source": "Fonte Atestada",
                    "options": ["A", "B", "C", "D"],
                }
            ],
        }
        mock_process_quiz.return_value = {
            "questions": mock_gen_paper.return_value["questions"],
            "asset_provenance": [],
        }

        # Caso A: Duração 58s (< 60s) -> Bloqueado
        mock_paper_render.return_value = {
            "status": "CONCLUIDO_COM_SUCESSO",
            "duration": 58.0,
        }
        params_short = VideoParams(video_subject="Curto", narrative_structure="quiz_paper")
        res_short = tm._run_quiz_pipeline(task_id="task_short", params=params_short, stop_at="video")
        self.assertIn("error", res_short)
        self.assertEqual(res_short.get("failed_stage"), "duration_safety")

        # Caso B: Duração 73s (> 70s) -> Bloqueado
        mock_paper_render.return_value = {
            "status": "CONCLUIDO_COM_SUCESSO",
            "duration": 73.0,
        }
        params_long = VideoParams(video_subject="Longo", narrative_structure="quiz_paper")
        res_long = tm._run_quiz_pipeline(task_id="task_long", params=params_long, stop_at="video")
        self.assertIn("error", res_long)
        self.assertEqual(res_long.get("failed_stage"), "duration_safety")

    def test_07_multi_destination_idempotency_schema(self):
        """7. Agendamento idempotente permitindo mesmo task_id para YouTube e TikTok simultaneamente."""
        task_id = "task_multi_sched_01"
        now_iso = "2026-10-18T10:00:00Z"

        with scheduler.get_connection(self.db_path) as conn:
            # 1. Agendamento YouTube
            conn.execute(
                """
                INSERT INTO scheduled_posts (
                    task_id, platform, scheduled_at, status, created_at, channel_id
                ) VALUES (?, 'youtube', ?, 'planned', ?, 'ch_yt_01');
                """,
                (task_id, now_iso, now_iso),
            )

            # 2. Agendamento TikTok concomitante para a mesma task
            conn.execute(
                """
                INSERT INTO scheduled_posts (
                    task_id, platform, scheduled_at, status, created_at, channel_id
                ) VALUES (?, 'tiktok', ?, 'planned', ?, 'ch_tt_02');
                """,
                (task_id, now_iso, now_iso),
            )

            # 3. Verifica que ambos existem isolados
            rows = conn.execute(
                "SELECT platform, channel_id FROM scheduled_posts WHERE task_id = ? ORDER BY platform;",
                (task_id,),
            ).fetchall()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["platform"], "tiktok")
            self.assertEqual(rows[1]["platform"], "youtube")

            # 4. Violação de idempotência: tentar duplicar agendamento para mesmo task_id + platform + channel_id
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO scheduled_posts (
                        task_id, platform, scheduled_at, status, created_at, channel_id
                    ) VALUES (?, 'youtube', ?, 'planned', ?, 'ch_yt_01');
                    """,
                    (task_id, now_iso, now_iso),
                )


if __name__ == "__main__":
    unittest.main()
