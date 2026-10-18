"""
test/services/test_quiz_engine.py
=================================
Testes direcionados para o QuizEngine Reutilizável (Fase Q1).
Valida:
1. Carregamento de configuração via JSON e dict.
2. Presença e validação dos 10 itens configuráveis obrigatórios.
3. Resolução de caminhos, paletas de cores, gancho de retenção e countdown.
"""

import json
import os
import tempfile
import pytest

from scripts.poc_quiz_render import QuizConfig, QuizEngine


def test_quiz_config_from_dict():
    data = {
        "niche": "fatos_curiosos",
        "quiz_title": "O QUE VOCÊ ESCOLHE?",
        "output_video_path": "storage/poc_quiz/teste.mp4",
        "output_thumbnail_path": "storage/poc_quiz/teste.jpg",
        "min_target_duration_sec": 60.0,
        "target_duration_range": [60.0, 65.0],
        "voice_settings": {
            "voice_name": "pt-BR-FranciscaNeural",
            "voice_rate": "+10%"
        },
        "retention_hook": {
            "enabled": True,
            "question_id": "q1",
            "narration": "Atenção ao final!",
            "min_countdown_sec": 3.5
        },
        "countdown_settings": {
            "default_sec": 2.5,
            "closing_sec": 3.0,
            "badges": ["3", "2", "1"]
        },
        "questions": [
            {
                "id": "q1",
                "header": "ESCOLHA:",
                "narration": "Texto da pergunta 1",
                "top": {"title": "A", "tag": "OPÇÃO A", "image_query": "query a", "image_name": "a.jpg", "theme": "red"},
                "bottom": {"title": "B", "tag": "OPÇÃO B", "image_query": "query b", "image_name": "b.jpg", "theme": "blue"},
                "countdown_sec": 3.5,
                "is_hook": True
            }
        ]
    }
    cfg = QuizConfig.from_dict(data)
    assert cfg.niche == "fatos_curiosos"
    assert cfg.quiz_title == "O QUE VOCÊ ESCOLHE?"
    assert cfg.voice_settings["voice_name"] == "pt-BR-FranciscaNeural"
    assert cfg.voice_settings["voice_rate"] == "+10%"
    assert cfg.retention_hook["enabled"] is True
    assert cfg.retention_hook["narration"] == "Atenção ao final!"
    assert len(cfg.questions) == 1
    assert cfg.questions[0]["is_hook"] is True


def test_quiz_config_from_template_file():
    template_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "resource", "quiz_templates", "quiz_template_escolhas_impossiveis.json"
    )
    assert os.path.exists(template_path), f"Arquivo não encontrado: {template_path}"

    cfg = QuizConfig.from_json(template_path)
    assert cfg.niche == "curiosidades_dilemas"
    assert cfg.quiz_title == "QUAL VOCÊ ESCOLHERIA?"
    assert len(cfg.questions) == 6
    assert cfg.retention_hook["enabled"] is True
    assert cfg.retention_hook["question_id"] == "q1"
    assert "surpreender" in cfg.retention_hook["narration"]
    assert cfg.questions[5]["is_closing_choice"] is True
    assert cfg.min_target_duration_sec >= 60.0


def test_quiz_engine_instantiation():
    template_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "resource", "quiz_templates", "quiz_template_escolhas_impossiveis.json"
    )
    cfg = QuizConfig.from_json(template_path)
    engine = QuizEngine(cfg)
    assert engine.ffmpeg_bin != ""
    assert os.path.exists(cfg.images_dir)


def test_quiz_narrative_structure_constants_and_routing():
    from unittest.mock import patch
    from app.models import const, schema
    from app.services import safety_gate, task

    # 1. Constante e presença na lista de estruturas da UI
    assert hasattr(const, "STRUCTURE_QUIZ_DILEMMA")
    assert const.STRUCTURE_QUIZ_DILEMMA == "quiz_dilemma"
    assert const.STRUCTURE_QUIZ_DILEMMA in const.NARRATIVE_STRUCTURES

    # 2. Especificação no safety_gate
    spec = safety_gate.get_structure_spec(const.STRUCTURE_QUIZ_DILEMMA)
    assert spec is not None
    assert spec["id"] == "quiz_dilemma"
    assert len(spec["steps"]) >= 4

    # 3. Propagação em VideoParams
    params = schema.VideoParams(
        video_subject="Dilemas Homologação",
        narrative_structure=const.STRUCTURE_QUIZ_DILEMMA,
    )
    assert params.narrative_structure == "quiz_dilemma"

    # 4. Roteamento de pipeline no task manager (Quiz vs Tradicional)
    with patch("app.services.task._run_quiz_pipeline", return_value={"status": "mock_quiz_routed"}) as mock_quiz, \
         patch("app.services.task.generate_script", return_value="Roteiro mock") as mock_script, \
         patch("app.services.task._check_cancellation", return_value=None), \
         patch("app.services.task.utils.check_ffmpeg_ready", return_value=True):

        # 4a. Rota Quiz Engine
        res_quiz = task._run_pipeline("test-task-quiz", params)
        assert res_quiz == {"status": "mock_quiz_routed"}
        mock_quiz.assert_called_once()
        mock_script.assert_not_called()

        # 4b. Rota Tradicional (preservada)
        mock_quiz.reset_mock()
        mock_script.reset_mock()
        params_trad = schema.VideoParams(
            video_subject="Mistério Tradicional",
            narrative_structure=const.STRUCTURE_MYSTERY,
        )
        # stop_at="script" para validar que segue para generate_script sem executar render
        task._run_pipeline("test-task-trad", params_trad, stop_at="script")
        mock_quiz.assert_not_called()
        mock_script.assert_called_once()

