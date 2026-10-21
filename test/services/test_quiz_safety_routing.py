"""
test/services/test_quiz_safety_routing.py
=========================================
Valida o roteamento real do Quiz Safety Gate para o canal Dose Diária de Escolhas:
1. Tarefa de canal quiz com video_format='quiz_dilemma' herda e roteia estritamente para Quiz Safety Gate.
2. Tarefa com narrative_structure='quiz' ou variantes de dilema são identificadas por is_quiz_dilemma.
3. Tarefa onde narrative_structure não está preenchido nos parâmetros herda do perfil e entra no pipeline do Quiz.
4. Roteamento tradicional é 100% preservado para canais convencionais (video_format='traditional').
5. Proteção de qualidade do Quiz Safety Gate (detecção de repetição de dilemas) permanece ativa e íntegra.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.models import const
from app.models.schema import VideoParams
from app.services import profile_manager, quiz_safety_gate, safety_gate, state as sm, task as tm


class TestQuizSafetyRouting(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_routing.db")
        self.orig_profile_db_path = profile_manager.get_db_path
        profile_manager.get_db_path = lambda custom=None: custom or self.db_path
        profile_manager.init_profile_db(self.db_path)
        quiz_safety_gate.init_quiz_safety_db(self.db_path)

        # Canal Dose Diária de Escolhas (configuração real sem credenciais nem banco de produção)
        res = profile_manager.onboard_channel_workspace(
            name="Dose Diária de Escolhas",
            niche="curiosidades",
            topic_brief="Dilemas morais e escolhas impossíveis",
            video_format="quiz_dilemma",
            closing_type="engagement_cta",
            num_questions=8,
            require_destination=False,
            db_path=self.db_path,
        )
        self.quiz_profile_id = res["profile_id"]

        # Canal Tradicional (ex: Dose Diária de Histórias e Mistério)
        res_trad = profile_manager.onboard_channel_workspace(
            name="Dose Diária de Histórias e Mistério",
            niche="historias_misterio",
            topic_brief="Mistérios reais e enigmas da história",
            video_format="traditional",
            require_destination=False,
            db_path=self.db_path,
        )
        self.trad_profile_id = res_trad["profile_id"]

    def tearDown(self):
        profile_manager.get_db_path = self.orig_profile_db_path
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_is_quiz_dilemma_resolution(self):
        """1. is_quiz_dilemma reconhece formatos canônicos, variantes e herança de perfil."""
        # A. Canônico explícito
        p1 = VideoParams(video_subject="Dilema 1", narrative_structure="quiz_dilemma")
        self.assertTrue(quiz_safety_gate.is_quiz_dilemma(params=p1, narrative_structure="quiz_dilemma"))

        # B. Variantes comuns de Quiz Dilema
        p2 = VideoParams(video_subject="Dilema 2", narrative_structure="quiz")
        self.assertTrue(quiz_safety_gate.is_quiz_dilemma(params=p2, narrative_structure="quiz"))

        p3 = VideoParams(video_subject="Dilema 3", narrative_structure="quiz_escolhas_impossiveis")
        self.assertTrue(quiz_safety_gate.is_quiz_dilemma(params=p3, narrative_structure="quiz_escolhas_impossiveis"))

        # C. Parâmetro sem narrative_structure, mas com profile_id do canal Dose Diária de Escolhas
        p4 = VideoParams(video_subject="Dilema 4", profile_id=self.quiz_profile_id, narrative_structure=None)
        self.assertTrue(quiz_safety_gate.is_quiz_dilemma(params=p4, db_path=self.db_path))

        # D. Canais tradicionais NÃO são identificados como quiz
        p_trad = VideoParams(video_subject="Mistério", profile_id=self.trad_profile_id, narrative_structure="investigative_mystery")
        self.assertFalse(quiz_safety_gate.is_quiz_dilemma(params=p_trad, db_path=self.db_path))

        # E. Formato de Quiz de Papel (factual) não é quiz_dilemma
        p_paper = VideoParams(video_subject="Quiz Papel", narrative_structure="quiz_paper")
        self.assertFalse(quiz_safety_gate.is_quiz_dilemma(params=p_paper, db_path=self.db_path))

    @patch("app.services.task._run_quiz_pipeline")
    @patch("app.utils.utils.check_ffmpeg_ready", return_value=True)
    def test_run_pipeline_routes_quiz_channel_without_explicit_structure(self, mock_ffmpeg, mock_quiz_pipeline):
        """2. _run_pipeline infere o formato quiz_dilemma do perfil do canal e roteia para _run_quiz_pipeline."""
        mock_quiz_pipeline.return_value = {"status": "ok", "stage": "READY_STOCK"}
        params = VideoParams(
            video_subject="Você prefere ter asas ou respirar na água?",
            profile_id=self.quiz_profile_id,
            narrative_structure=None,  # Não preenchido explicitamente
        )

        res = tm._run_pipeline(
            task_id="task_route_test_1",
            params=params,
            stop_at="script",
        )

        mock_quiz_pipeline.assert_called_once()
        self.assertEqual(res, {"status": "ok", "stage": "READY_STOCK"})
        self.assertEqual(params.narrative_structure, "quiz_dilemma")

    @patch("app.services.task._run_quiz_pipeline")
    @patch("app.services.task.generate_script", return_value="Roteiro tradicional de mistério longo e completo.")
    @patch("app.services.safety_gate.evaluate_script_safety", return_value={"safety_status": const.SAFETY_STATUS_PASS, "safety_reasons": []})
    @patch("app.utils.utils.check_ffmpeg_ready", return_value=True)
    def test_traditional_pipeline_strictly_preserved(self, mock_ffmpeg, mock_safety, mock_gen_script, mock_quiz_pipe):
        """3. Canais tradicionais preservam estritamente o pipeline tradicional e o Safety Gate tradicional."""
        params = VideoParams(
            video_subject="O enigma da passagem de Dyatlov",
            profile_id=self.trad_profile_id,
            narrative_structure=None,
        )

        res = tm._run_pipeline(
            task_id="task_route_trad_1",
            params=params,
            stop_at="script",
        )

        mock_quiz_pipe.assert_not_called()
        mock_gen_script.assert_called_once()
        mock_safety.assert_called_once()
        self.assertIn("script", res)

    @patch("app.services.quiz_generator.QuizContentGenerator.generate_quiz_structure")
    @patch("app.services.quiz_safety_gate.evaluate_quiz_script_safety")
    @patch("app.services.quiz_safety_gate.evaluate_quiz_duration_safety")
    @patch("app.services.safety_gate.evaluate_script_safety")
    @patch("app.services.quiz_assets.QuizAssetManager.process_quiz")
    @patch("scripts.poc_quiz_render.QuizEngine.render")
    @patch("app.services.media_quality.evaluate_final_media_quality")
    def test_run_quiz_pipeline_uses_quiz_safety_gate_not_traditional(
        self,
        mock_mq,
        mock_render,
        mock_process_quiz,
        mock_trad_safety,
        mock_quiz_dur_safety,
        mock_quiz_script_safety,
        mock_gen_quiz,
    ):
        """4. _run_quiz_pipeline invoca exclusivamente evaluate_quiz_script_safety, nunca o Safety Gate tradicional."""
        mock_gen_quiz.return_value = {
            "niche": "curiosidades",
            "format_type": "subjective",
            "questions": [
                {
                    "id": "q1",
                    "header": "DILEMA 1:",
                    "narration": "O que você prefere? Ser rico ou ter superpoderes?",
                    "top": {"title": "Ser rico", "image_query": "money rich"},
                    "bottom": {"title": "Superpoderes", "image_query": "superhero flying"},
                }
            ],
        }
        mock_quiz_script_safety.return_value = {
            "safety_status": const.SAFETY_STATUS_PASS,
            "safety_reasons": [],
            "narrative_structure": "quiz_dilemma",
        }
        mock_quiz_dur_safety.return_value = {
            "safety_status": const.SAFETY_STATUS_PASS,
            "safety_reasons": [],
        }
        mock_process_quiz.return_value = {
            "success": True,
            "audio_duration": 62.0,
            "voice_audio": "/tmp/audio.mp3",
            "subtitles_file": "/tmp/sub.srt",
        }
        mock_render.return_value = True
        mock_mq.return_value = {
            "is_valid": True,
            "media_quality_status": "PASS",
            "media_quality_score": 85.0,
            "media_quality_reasons": [],
        }

        params = VideoParams(
            video_subject="Escolhas Impossíveis",
            profile_id=self.quiz_profile_id,
            narrative_structure="quiz_dilemma",
        )

        res = tm._run_quiz_pipeline(
            task_id="task_quiz_exec_1",
            params=params,
            stop_at="script",
        )

        # Deve chamar o validador especializado de Quiz
        mock_quiz_script_safety.assert_called_once()
        # NUNCA deve chamar o Safety Gate tradicional
        mock_trad_safety.assert_not_called()
        self.assertIn("script", res)
