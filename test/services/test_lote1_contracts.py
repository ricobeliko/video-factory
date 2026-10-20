"""
Testes direcionados do Lote 1 - Contratos, Hidratação e Separação de Formatos.

Valida:
1. VideoParams: video_format canônico, narrative_structure ortogonal, isenção SRT no Quiz,
   retrocompatibilidade de chamadas legadas e normalização de closing_type/num_questions.
2. profile_manager.get_generation_profile_context: normalização determinística de formato,
   desativação de Flow/Director para Quiz, default 5 perguntas para quiz_paper.
3. webui_task.submit_generation: herança profilada completa para campos não informados,
   respeito estrito à precedência (manual explícito > perfil > fallback).
4. llm.py: injeção de topic_brief no build_script_prompt e generate_script.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from app.models import const
from app.models.schema import VideoParams
from app.services import profile_manager, webui_task, llm, operator_console


class TestLote1VideoParamsContract(unittest.TestCase):
    def test_default_initialization_is_traditional(self):
        p = VideoParams(video_subject="História do Brasil")
        self.assertEqual(p.video_format, const.VIDEO_FORMAT_TRADITIONAL)
        self.assertIsNone(p.narrative_structure)
        self.assertFalse(p.flow_enabled)
        self.assertFalse(p.visual_director_enabled)

    def test_quiz_dilemma_contract_and_retrocompatibility(self):
        # 1. Criação direta com video_format="quiz_dilemma"
        p = VideoParams(video_subject="Escolhas", video_format="quiz_dilemma")
        self.assertEqual(p.video_format, const.VIDEO_FORMAT_QUIZ_DILEMMA)
        # Retrocompatibilidade: preenche narrative_structure para código legado em task.py
        self.assertEqual(p.narrative_structure, const.VIDEO_FORMAT_QUIZ_DILEMMA)
        # Isenção de SRT / legendas e desativação de Flow
        self.assertFalse(p.subtitle_required)
        self.assertFalse(p.subtitle_enabled)
        self.assertFalse(p.flow_enabled)
        self.assertFalse(p.visual_director_enabled)

    def test_quiz_paper_contract_defaults(self):
        # Quiz de Papel padrão P1.3: 5 perguntas, sem SRT
        p = VideoParams(video_subject="Conhecimentos Gerais", video_format="quiz_paper")
        self.assertEqual(p.video_format, const.VIDEO_FORMAT_QUIZ_PAPER)
        self.assertEqual(p.num_questions, 5)
        self.assertFalse(p.subtitle_required)
        self.assertFalse(p.subtitle_enabled)

    def test_legacy_quiz_in_narrative_structure_reconciles_to_video_format(self):
        # Chamador legado que não passa video_format mas passa narrative_structure="quiz_dilemma"
        p = VideoParams(video_subject="Legado", narrative_structure="quiz_dilemma")
        self.assertEqual(p.video_format, const.VIDEO_FORMAT_QUIZ_DILEMMA)
        self.assertEqual(p.narrative_structure, "quiz_dilemma")
        self.assertFalse(p.subtitle_required)

    def test_traditional_with_orthogonal_narrative_structure(self):
        p = VideoParams(
            video_subject="Mistério no Ártico",
            video_format="traditional",
            narrative_structure="investigative_mystery",
        )
        self.assertEqual(p.video_format, const.VIDEO_FORMAT_TRADITIONAL)
        self.assertEqual(p.narrative_structure, "investigative_mystery")

    def test_closing_type_comments_normalizes_to_score_challenge(self):
        p = VideoParams(
            video_subject="Quiz",
            video_format="quiz_paper",
            closing_type="comments",
        )
        self.assertEqual(p.closing_type, "score_challenge")


class TestLote1ProfileContextResolution(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_lote1_profile.db")
        profile_manager.init_profile_db(self.db_path)
        operator_console.init_operator_db(self.db_path)

        # Configura nó como primary
        operator_console.reset_instance_for_testing()
        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._is_primary = True

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_traditional_profile_context(self):
        p_row = profile_manager.create_profile(
            name="Ciência Todo Dia",
            niche="ciencia",
            db_path=self.db_path,
        )
        pid = p_row["id"]

        settings = profile_manager.ChannelWorkspaceSettings()
        settings.editorial.video_format = "traditional"
        settings.editorial.content_style = "explainer"
        settings.editorial.topic_brief = "Canal de Ciência e Fatos"
        settings.visual.flow_enabled = True
        settings.visual.visual_director_enabled = True
        settings.visual.visual_style_brief = "cinematic ultra detailed"

        profile_manager.update_profile_settings(pid, settings, db_path=self.db_path)
        ctx = profile_manager.get_generation_profile_context(pid, db_path=self.db_path)

        self.assertEqual(ctx["video_format"], const.VIDEO_FORMAT_TRADITIONAL)
        self.assertEqual(ctx["narrative_structure"], "explainer")
        self.assertEqual(ctx["topic_brief"], "Canal de Ciência e Fatos")
        self.assertTrue(ctx["flow_enabled"])
        self.assertTrue(ctx["visual_director_enabled"])
        self.assertEqual(ctx["visual_style_brief"], "cinematic ultra detailed")

    def test_quiz_profile_context_disables_flow_and_normalizes_format(self):
        p_row = profile_manager.create_profile(
            name="Dose de Quiz",
            niche="quiz",
            db_path=self.db_path,
        )
        pid = p_row["id"]

        settings = profile_manager.ChannelWorkspaceSettings()
        settings.editorial.video_format = "quiz_paper"
        settings.editorial.closing_type = "comments"
        # Tenta ligar Flow indevidamente para Quiz
        settings.visual.flow_enabled = True
        settings.visual.visual_director_enabled = True

        profile_manager.update_profile_settings(pid, settings, db_path=self.db_path)
        ctx = profile_manager.get_generation_profile_context(pid, db_path=self.db_path)

        self.assertEqual(ctx["video_format"], const.VIDEO_FORMAT_QUIZ_PAPER)
        self.assertIsNone(ctx["narrative_structure"])
        self.assertEqual(ctx["closing_type"], "score_challenge")
        self.assertEqual(ctx["num_questions"], 5)
        # Flow e Visual Director estritamente desativados para Quiz
        self.assertFalse(ctx["flow_enabled"])
        self.assertFalse(ctx["visual_director_enabled"])


class TestLote1WebUITaskHydration(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_lote1_hydration.db")
        profile_manager.init_profile_db(self.db_path)
        operator_console.init_operator_db(self.db_path)

        operator_console.reset_instance_for_testing()
        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._is_primary = True

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("app.services.webui_task._task_manager.add_task")
    def test_submission_inherits_profile_for_unspecified_fields(self, mock_add_task):
        p_row = profile_manager.create_profile(
            name="Canal Tecnológico",
            niche="tecnologia",
            db_path=self.db_path,
        )
        pid = p_row["id"]

        settings = profile_manager.ChannelWorkspaceSettings()
        settings.editorial.video_format = "traditional"
        settings.editorial.content_style = "fact_context"
        settings.editorial.topic_brief = "Brief do Canal"
        settings.visual.flow_enabled = True
        settings.visual.visual_director_enabled = True
        settings.visual.visual_style_brief = "cyberpunk style"
        settings.voice.voice_name = "pt-BR-FranciscaNeural"
        settings.voice.voice_rate = 1.05

        profile_manager.update_profile_settings(pid, settings, db_path=self.db_path)

        # Entrada manual sem especificar campos editoriais/visuais/voz
        raw_params = VideoParams(video_subject="Inovações de IA")
        webui_task.submit_generation(
            task_id="task-test-hydration-1",
            params=raw_params,
            profile_id=pid,
            db_path=self.db_path,
        )

        mock_add_task.assert_called_once()
        _, kwargs = mock_add_task.call_args
        submitted_params: VideoParams = kwargs["params"]

        # Herança comprovada
        self.assertEqual(submitted_params.video_format, const.VIDEO_FORMAT_TRADITIONAL)
        self.assertEqual(submitted_params.narrative_structure, "fact_context")
        self.assertEqual(submitted_params.topic_brief, "Brief do Canal")
        self.assertTrue(submitted_params.flow_enabled)
        self.assertTrue(submitted_params.visual_director_enabled)
        self.assertEqual(submitted_params.visual_style_brief, "cyberpunk style")
        self.assertEqual(submitted_params.voice_rate, 1.05)

    @patch("app.services.webui_task._task_manager.add_task")
    def test_manual_override_wins_over_profile(self, mock_add_task):
        p_row = profile_manager.create_profile(
            name="Canal Override",
            niche="curiosidades",
            db_path=self.db_path,
        )
        pid = p_row["id"]

        settings = profile_manager.ChannelWorkspaceSettings()
        settings.editorial.video_format = "traditional"
        settings.editorial.topic_brief = "Brief Perfil"
        settings.voice.voice_rate = 1.0

        profile_manager.update_profile_settings(pid, settings, db_path=self.db_path)

        # Operador sobrescreve intencionalmente topic_brief e voice_rate
        manual_params = VideoParams(
            video_subject="Tema Exclusivo",
            topic_brief="Brief Manual Operador",
            voice_rate=1.25,
        )
        webui_task.submit_generation(
            task_id="task-test-override-1",
            params=manual_params,
            profile_id=pid,
            db_path=self.db_path,
        )

        mock_add_task.assert_called_once()
        _, kwargs = mock_add_task.call_args
        submitted_params: VideoParams = kwargs["params"]

        # Override manual comprovado
        self.assertEqual(submitted_params.topic_brief, "Brief Manual Operador")
        self.assertEqual(submitted_params.voice_rate, 1.25)


class TestLote1LLMTopicBriefIntegration(unittest.TestCase):
    def test_build_script_prompt_injects_topic_brief(self):
        prompt = llm.build_script_prompt(
            video_subject="Mistério das Pirâmides",
            language="pt-BR",
            topic_brief="Foco em teorias arquitetônicas reais sem ficção",
        )
        self.assertIn("Mistério das Pirâmides", prompt)
        self.assertIn("- topic brief / editorial direction: Foco em teorias arquitetônicas reais sem ficção", prompt)

    def test_build_script_prompt_without_topic_brief(self):
        prompt = llm.build_script_prompt(
            video_subject="Mistério das Pirâmides",
            language="pt-BR",
            topic_brief="",
        )
        self.assertNotIn("topic brief", prompt)


if __name__ == "__main__":
    unittest.main()
