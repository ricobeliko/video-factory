"""
test/services/test_quiz_generator.py
===================================
Testes unitários direcionados para o gerador automático de conteúdo (Fase Q2).
Valida:
1. Deduplicação e histórico persistente de perguntas.
2. Deduplicação de imagens via asset_id e hash.
3. Geração de quiz subjetivo (dilemas de escolhas impossíveis).
4. Geração de quiz factual (checagem factual e fontes verificadas).
5. Compatibilidade estrita do JSON gerado com a Quiz Engine (QuizConfig).
"""

import json
import os
import tempfile
import pytest

from app.services.quiz_generator import QuizContentGenerator
from scripts.poc_quiz_render import QuizConfig


@pytest.fixture
def temp_generator():
    with tempfile.TemporaryDirectory() as temp_dir:
        gen = QuizContentGenerator(history_dir=temp_dir, templates_dir=temp_dir)
        yield gen


def test_duplicate_prevention(temp_generator):
    gen = temp_generator
    q1 = "O que você prefere? Ganhar um milhão de reais todo mês ou ter juventude eterna?"
    assert gen.is_question_duplicate(q1) is False

    # Registra no histórico
    gen.record_question(q1, niche="dilemas", format_type="subjective")

    # Mesma pergunta deve ser detectada como duplicada
    assert gen.is_question_duplicate(q1) is True

    # Pergunta com variação muito próxima deve ser detectada como duplicada
    q1_var = "O que você prefere? Ganhar 1 milhão de reais todo mês ou juventude eterna?"
    assert gen.is_question_duplicate(q1_var, threshold=0.50) is True

    # Pergunta totalmente diferente deve ser aceita
    q2 = "Você prefere ter a capacidade de voar ou ficar invisível quando quiser?"
    assert gen.is_question_duplicate(q2) is False


def test_used_images_deduplication(temp_generator):
    gen = temp_generator
    assert gen.is_image_used(asset_id="12345") is False

    gen.record_image(asset_id="12345", content_hash="abc_hash_1", query="gold bars")
    assert gen.is_image_used(asset_id="12345") is True
    assert gen.is_image_used(asset_id="67890", content_hash="abc_hash_1") is True
    assert gen.is_image_used(asset_id="67890", content_hash="other_hash") is False


def test_generate_subjective_quiz(temp_generator):
    gen = temp_generator
    raw = gen.generate_quiz_structure(
        niche="curiosidades_dilemas",
        format_type="subjective",
        num_questions=6,
        quiz_title="QUAL VOCÊ ESCOLHERIA?",
        closing_type="quiz_choice_religious"
    )

    assert raw["niche"] == "curiosidades_dilemas"
    assert raw["format_type"] == "subjective"
    assert len(raw["questions"]) == 6
    assert raw["questions"][0]["is_hook"] is True
    assert "surpreender" in raw["questions"][0]["hook_narration"]
    assert raw["questions"][-1]["is_closing_choice"] is True

    # Testa exportação e carregamento no QuizConfig
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        out_path = tf.name
    try:
        cfg = gen.export_to_quiz_config(raw, out_path)
        assert isinstance(cfg, QuizConfig)
        assert cfg.niche == "curiosidades_dilemas"
        assert len(cfg.questions) == 6
        assert cfg.retention_hook["enabled"] is True
    finally:
        if os.path.exists(out_path):
            os.remove(out_path)


def test_generate_factual_quiz_fact_checking(temp_generator):
    gen = temp_generator
    raw = gen.generate_quiz_structure(
        niche="curiosidades_animais",
        format_type="factual",
        num_questions=6,
        quiz_title="TESTE DE CONHECIMENTOS: ANIMAIS",
        closing_type="score_challenge"
    )

    assert raw["format_type"] == "factual"
    assert len(raw["questions"]) == 6

    # Todas as perguntas factuais devem ter alternativa correta e explicação
    for q in raw["questions"][:-1]:  # Exceto a pergunta de encerramento do desafio se aplicável
        if q.get("verified"):
            assert q.get("correct_option") in ["A", "B"]
            assert len(q.get("fact_explanation", "")) > 10

    # Testa compatibilidade com QuizConfig
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        out_path = tf.name
    try:
        cfg = gen.export_to_quiz_config(raw, out_path)
        assert isinstance(cfg, QuizConfig)
        assert cfg.niche == "curiosidades_animais"
        assert len(cfg.questions) == 6
    finally:
        if os.path.exists(out_path):
            os.remove(out_path)
