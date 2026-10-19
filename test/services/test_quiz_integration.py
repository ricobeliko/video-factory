"""
test/services/test_quiz_integration.py
======================================
VIDEO FACTORY — FASE Q4-B: TESTES DE INTEGRAÇÃO DO QUIZ ENGINE

Valida:
1. Roteamento do Quiz Engine via narrative_structure ("quiz_dilemma").
2. Preservação integral do pipeline tradicional para canais convencionais.
3. Bloqueio factual rigoroso para quizzes sem fontes independentes verificadas.
4. Promoção a READY_STOCK exclusivamente após aprovação em todos os gates.
5. Execução integrada pontual de um quiz com isolamento por task_id.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.models import const
from app.models.schema import VideoParams
from app.services import state as sm, task as tm
from app.utils import utils


class TestQuizIntegration(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.task_id = "test_quiz_task_q4b"

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("app.services.task._run_quiz_pipeline")
    @patch("app.utils.utils.check_ffmpeg_ready", return_value=True)
    def test_quiz_routing(self, mock_ffmpeg, mock_quiz_pipe):
        """1. Roteamento: narrative_structure='quiz_dilemma' deve acionar _run_quiz_pipeline."""
        mock_quiz_pipe.return_value = {"status": "ok", "routed_to": "quiz"}
        params = VideoParams(
            video_subject="Escolhas Impossíveis",
            narrative_structure="quiz_dilemma",
        )

        res = tm._run_pipeline(
            task_id=self.task_id,
            params=params,
            stop_at="video",
        )

        mock_quiz_pipe.assert_called_once_with(
            task_id=self.task_id,
            params=params,
            stop_at="video",
        )
        self.assertEqual(res, {"status": "ok", "routed_to": "quiz"})

    @patch("app.services.task._run_quiz_pipeline")
    @patch("app.services.task.generate_script", return_value="Roteiro tradicional de teste longo e completo com mais de cinquenta palavras para garantir que a validação de segurança não barre o teste.")
    @patch("app.services.safety_gate.evaluate_script_safety", return_value={"safety_status": const.SAFETY_STATUS_PASS, "safety_reasons": []})
    @patch("app.utils.utils.check_ffmpeg_ready", return_value=True)
    def test_traditional_pipeline_preserved(self, mock_ffmpeg, mock_safety, mock_gen_script, mock_quiz_pipe):
        """2. Tarefas tradicionais (narrative_structure=None) preservam o pipeline anterior."""
        params = VideoParams(
            video_subject="Curiosidades do Universo",
            narrative_structure=None,
        )

        res = tm._run_pipeline(
            task_id=self.task_id,
            params=params,
            stop_at="script",
        )

        mock_quiz_pipe.assert_not_called()
        mock_gen_script.assert_called_once()
        self.assertIn("script", res)
        self.assertEqual(res["script"], mock_gen_script.return_value)

    @patch("app.services.quiz_generator.QuizContentGenerator.generate_quiz_structure")
    @patch("app.services.safety_gate.evaluate_script_safety", return_value={"safety_status": const.SAFETY_STATUS_PASS, "safety_reasons": []})
    def test_factual_quiz_unverified_blocked(self, mock_safety, mock_gen_quiz):
        """3. Bloqueio factual: perguntas sem fontes independentes não avançam."""
        mock_gen_quiz.return_value = {
            "niche": "historia",
            "format_type": "factual",
            "questions": [
                {
                    "id": "q1",
                    "header": "PERGUNTA 1:",
                    "narration": "Quem descobriu o Brasil em mil e quinhentos durante as grandes navegações portuguesas?",
                    "verified": False,
                    "publication_gate": "BLOCKED_PENDING_EXTERNAL_AUDIT",
                    "evidence_source": "LLM Heuristic",
                    "is_closing_choice": False,
                }
            ],
        }

        params = VideoParams(
            video_subject="História do Brasil",
            narrative_structure="quiz_factual",
        )

        res = tm._run_quiz_pipeline(
            task_id=self.task_id,
            params=params,
            stop_at="video",
        )

        self.assertIn("error", res)
        self.assertEqual(res.get("failed_stage"), "factual_gate")
        task_state = sm.state.get_task(self.task_id)
        self.assertEqual(task_state.get("state"), const.TASK_STATE_FAILED)
        self.assertNotEqual(task_state.get("stage"), "READY_STOCK")

    @patch("app.services.quiz_generator.QuizContentGenerator.generate_quiz_structure")
    @patch("app.services.quiz_assets.QuizAssetManager.process_quiz")
    @patch("scripts.poc_quiz_render.QuizEngine.render")
    @patch("app.services.quiz_safety_gate.evaluate_quiz_script_safety")
    @patch("app.services.quiz_safety_gate.evaluate_quiz_duration_safety")
    @patch("app.services.media_quality.evaluate_final_media_quality")
    def test_ready_stock_promotion_after_gates(
        self,
        mock_mq,
        mock_dur_safety,
        mock_script_safety,
        mock_render,
        mock_process_quiz,
        mock_gen_quiz,
    ):
        """4. Promoção a READY_STOCK ocorre estritamente após aprovação de todos os gates."""
        mock_gen_quiz.return_value = {
            "niche": "dilemas",
            "format_type": "subjective",
            "questions": [
                {
                    "id": "q1",
                    "header": "DILEMA 1:",
                    "narration": "Você prefere ganhar um milhão de reais todo mês ou ter juventude eterna?",
                    "top": {"title": "A", "image_query": "query_a"},
                    "bottom": {"title": "B", "image_query": "query_b"},
                }
            ],
        }
        mock_script_safety.return_value = {
            "safety_status": const.SAFETY_STATUS_PASS,
            "safety_reasons": [],
        }
        mock_process_quiz.return_value = {
            "questions": mock_gen_quiz.return_value["questions"],
            "asset_provenance": [{"asset_id": "img1", "local_path": "dummy.jpg"}],
        }
        mock_render.return_value = {
            "status": "CONCLUIDO_COM_SUCESSO",
            "duration": 63.5,
        }
        mock_dur_safety.return_value = {
            "safety_status": const.SAFETY_STATUS_PASS,
            "safety_reasons": [],
        }
        mock_mq.return_value = {
            "status": "PASS",
            "reasons": [],
            "metrics": {"duration": 63.5},
        }

        params = VideoParams(
            video_subject="Dilemas da Vida",
            narrative_structure="quiz_dilemma",
        )

        res = tm._run_quiz_pipeline(
            task_id=self.task_id,
            params=params,
            stop_at="video",
        )

        self.assertNotIn("error", res)
        task_state = sm.state.get_task(self.task_id)
        self.assertEqual(task_state.get("state"), const.TASK_STATE_COMPLETE)
        self.assertEqual(task_state.get("stage"), "READY_STOCK")
        self.assertTrue(len(task_state.get("videos", [])) > 0)
        self.assertIn("final-1.mp4", task_state["videos"][0])

    @patch("app.services.quiz_assets.QuizAssetManager.resolve_option_image")
    @patch("scripts.poc_quiz_render.QuizEngine.render")
    @patch("app.services.quiz_safety_gate.evaluate_quiz_script_safety", return_value={"safety_status": const.SAFETY_STATUS_PASS, "safety_reasons": []})
    @patch("app.services.quiz_safety_gate.evaluate_quiz_duration_safety", return_value={"safety_status": const.SAFETY_STATUS_PASS, "safety_reasons": []})
    @patch("app.services.media_quality.evaluate_final_media_quality", return_value={"status": "PASS", "reasons": [], "metrics": {"duration": 62.0}})
    def test_integrated_single_quiz_execution(self, mock_mq, mock_dur_safety, mock_script_safety, mock_render, mock_resolve_img):
        """5. Execução integrada de um único quiz de dilema com dados reais da Q2/Q3."""
        from app.services.quiz_assets import ImageProvenance
        mock_prov = ImageProvenance(
            asset_id="test_asset",
            provider="test",
            source_url="http://example.com",
            creator_name="author",
            creator_url="http://example.com/author",
            license="free",
            content_hash="abc123",
            local_path="storage/dummy_path.jpg",
            resolution=(1200, 1066),
            query="query",
            question_id="q1",
            option_slot="top",
            status="READY",
        )
        mock_resolve_img.return_value = mock_prov

        mock_render.return_value = {
            "status": "CONCLUIDO_COM_SUCESSO",
            "duration": 62.0,
        }

        params = VideoParams(
            video_subject="O Que Você Faria?",
            narrative_structure="quiz_dilemma",
            niche="dilemas",
        )

        res = tm._run_pipeline(
            task_id=self.task_id,
            params=params,
            stop_at="video",
        )

        self.assertNotIn("error", res)
        task_state = sm.state.get_task(self.task_id)
        self.assertEqual(task_state.get("stage"), "READY_STOCK")
        self.assertEqual(task_state.get("state"), const.TASK_STATE_COMPLETE)
        self.assertTrue(task_state.get("audio_duration") >= 60.0)


if __name__ == "__main__":
    unittest.main()
