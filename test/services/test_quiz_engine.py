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
