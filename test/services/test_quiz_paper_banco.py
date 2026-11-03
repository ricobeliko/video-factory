"""
test/services/test_quiz_paper_banco.py
======================================
Validação dos requisitos da Missão v2/banco-prova-papel:
(i) Catálogo CANONICAL_PAPER_QUIZ_CATALOG com 132 entradas válidas
    (4 opções A-D, correct_option dentro das letras, sem duplicadas, source não vazio).
(ii) Com histórico simulado de 20 provas (100 questões consumidas), a seleção devolve 5 inéditas.
(iii) Com histórico que consome as questões inéditas, falha com código SEM_PERGUNTAS_NOVAS.
(iv) Nenhuma pergunta gerada por LLM sai como verified (estrita governança factual).
"""

import json
import tempfile
from unittest.mock import patch
import pytest

from app.models import const
from app.services.quiz_generator import (
    QuizContentGenerator,
    CANONICAL_PAPER_QUIZ_CATALOG,
    PAPER_QUIZ_USE_LLM,
)
from app.services import quiz_safety_gate


@pytest.fixture
def temp_generator():
    with tempfile.TemporaryDirectory() as temp_dir:
        gen = QuizContentGenerator(history_dir=temp_dir, templates_dir=temp_dir)
        yield gen


def test_i_catalog_has_132_valid_entries():
    """
    (i) Valida que o catálogo CANONICAL_PAPER_QUIZ_CATALOG possui exatamente 132 entradas
    homologadas, 4 opções com letras A-D, correct_option válida, sem perguntas duplicadas
    e source não vazio.
    """
    assert len(CANONICAL_PAPER_QUIZ_CATALOG) == 132, (
        f"Esperava 132 entradas no catálogo canônico, obteve {len(CANONICAL_PAPER_QUIZ_CATALOG)}"
    )

    seen_questions = set()
    for idx, item in enumerate(CANONICAL_PAPER_QUIZ_CATALOG):
        q_text = item.get("question", "").strip()
        assert q_text, f"Item {idx} possui 'question' vazia"
        q_norm = q_text.lower()
        assert q_norm not in seen_questions, f"Item {idx} possui pergunta duplicada: '{q_text}'"
        seen_questions.add(q_norm)

        # 4 opções com letras A-D
        options = item.get("options", [])
        assert len(options) == 4, f"Item {idx} ('{q_text}') deve ter exatamente 4 opções, obteve {len(options)}"
        letters = [opt.get("letter") for opt in options]
        assert letters == ["A", "B", "C", "D"], f"Item {idx} possui letras de opções inválidas: {letters}"
        for opt in options:
            assert opt.get("text", "").strip(), f"Item {idx} possui texto de opção vazio: {opt}"

        # correct_option dentro das letras A-D
        correct = item.get("correct_option")
        assert correct in ["A", "B", "C", "D"], f"Item {idx} possui correct_option inválida: {correct}"

        # source não vazio
        source = item.get("source", "").strip()
        assert source, f"Item {idx} possui 'source' vazio"

        # narration e category presentes
        assert item.get("narration", "").strip(), f"Item {idx} possui narration vazia"
        assert item.get("category", "").strip(), f"Item {idx} possui category vazia"


def test_ii_selection_with_20_simulated_proofs_returns_5_novel(temp_generator):
    """
    (ii) Com histórico simulado de 20 provas anteriores do canal (20 * 5 = 100 perguntas usadas),
    a seleção devolve 5 inéditas sem colidir com o histórico sob o critério da Fonte 2 (sim >= 0.80).
    """
    gen = temp_generator

    # Simula 100 perguntas já publicadas nos últimos 20 vídeos do canal
    history_items = CANONICAL_PAPER_QUIZ_CATALOG[:100]
    simulated_channel_history = [
        {
            "id": f"used_{i}",
            "header": f"QUESTÃO {(i % 5) + 1:02d}:",
            "narration": item["narration"],
            "top_title": "",
            "bottom_title": "",
            "is_closing": False,
        }
        for i, item in enumerate(history_items)
    ]

    raw_quiz = gen.generate_paper_quiz_structure(
        niche="conhecimentos_gerais",
        num_questions=5,
        quiz_title="TESTE PROVA DE PAPEL",
        closing_type="score_challenge",
        topic_brief="conhecimentos gerais variados",
        excluded_questions=simulated_channel_history,
    )

    questions = raw_quiz.get("questions", [])
    assert len(questions) == 5, f"Esperava 5 perguntas geradas, obteve {len(questions)}"

    # Verifica que nenhuma das 5 perguntas geradas colide com as 100 do histórico
    for q in questions:
        q_comp = {"narration": q["narration"], "top_title": "", "bottom_title": ""}
        for h in simulated_channel_history:
            h_comp = {"narration": h["narration"], "top_title": "", "bottom_title": ""}
            sim = quiz_safety_gate.dilemma_similarity(q_comp, h_comp)
            assert sim < 0.80, (
                f"Pergunta gerada '{q['narration']}' colidiu com histórico '{h['narration']}' (sim={sim:.2f})"
            )

        # Confirma marcação canônica de governança
        assert q.get("verified") is True
        assert q.get("fact_status") == "VERIFIED_CANONICAL"
        assert q.get("publication_gate") == "READY"


def test_iii_exhaustion_raises_sem_perguntas_novas_and_marks_failure(temp_generator):
    """
    (iii) Com histórico simulado que consome as perguntas inéditas do catálogo (restam < 5),
    a seleção DEVE falhar imediatamente levantando RuntimeError com SEM_PERGUNTAS_NOVAS
    (sem completar com repetidos), e o pipeline de task registra error_code='SEM_PERGUNTAS_NOVAS'.
    """
    gen = temp_generator

    # Consome todas as 132 perguntas no histórico simulado
    exhausted_history = [
        {
            "id": f"used_all_{i}",
            "header": f"QUESTÃO {(i % 5) + 1:02d}:",
            "narration": item["narration"],
            "top_title": "",
            "bottom_title": "",
            "is_closing": False,
        }
        for i, item in enumerate(CANONICAL_PAPER_QUIZ_CATALOG)
    ]

    with pytest.raises(RuntimeError) as exc_info:
        gen.generate_paper_quiz_structure(
            niche="conhecimentos_gerais",
            num_questions=5,
            quiz_title="TESTE ESGOTAMENTO",
            excluded_questions=exhausted_history,
        )

    err_str = str(exc_info.value)
    assert "SEM_PERGUNTAS_NOVAS" in err_str, (
        f"Esperava código 'SEM_PERGUNTAS_NOVAS' na exceção, obteve: {err_str}"
    )

    # Validação do pipeline de task: captura de SEM_PERGUNTAS_NOVAS e gravação do error_code
    from app.services import state as sm
    from app.services.task import _mark_task_failed

    test_tid = "task_test_fail_sem_perguntas_novas"
    sm.state.update_task(test_tid, state=const.TASK_STATE_PROCESSING, progress=10, stage="SCRIPT")

    exc_msg = "SEM_PERGUNTAS_NOVAS: Não foi possível obter 5 perguntas inéditas para o canal no catálogo canônico."
    err_details = {
        "error_code": "SEM_PERGUNTAS_NOVAS",
        "reason": exc_msg,
    }
    result = _mark_task_failed(test_tid, "script", f"Quiz generation failed: {exc_msg}", details=err_details)

    assert result["state"] == const.TASK_STATE_FAILED
    assert result["failed_stage"] == "script"
    assert result["error_code"] == "SEM_PERGUNTAS_NOVAS"

    saved_state = sm.state.get_task(test_tid)
    assert saved_state["error_code"] == "SEM_PERGUNTAS_NOVAS"
    assert saved_state["failed_stage"] == "script"


def test_iv_no_llm_question_leaves_as_verified(temp_generator):
    """
    (iv) Governança factual: Prova de papel não usa LLM por padrão (PAPER_QUIZ_USE_LLM = False).
    E mesmo que PAPER_QUIZ_USE_LLM seja ativado e a LLM retorne perguntas, nenhuma pergunta
    de LLM sai como verified=True ou VERIFIED_CANONICAL (segue UNVERIFIED_LLM_HEURISTIC).
    """
    # 1. Por padrão no sistema, PAPER_QUIZ_USE_LLM é False
    assert PAPER_QUIZ_USE_LLM is False, "PAPER_QUIZ_USE_LLM deve ser False por padrão"

    gen = temp_generator

    # 2. Simula ativação de PAPER_QUIZ_USE_LLM com retorno de perguntas da LLM
    llm_simulated_questions = json.dumps({
        "questions": [
            {
                "id": "q1",
                "question": "Pergunta Factual Gerada pela IA?",
                "category": "TESTE",
                "options": [
                    {"letter": "A", "text": "Opção 1"},
                    {"letter": "B", "text": "Opção 2"},
                    {"letter": "C", "text": "Opção 3"},
                    {"letter": "D", "text": "Opção 4"},
                ],
                "correct_option": "A",
                "narration": "Pergunta Factual Gerada pela IA?",
                "explanation": "Explicação auto-atestada pela IA.",
                "source": "Gerado por Inteligência Artificial",
            }
        ]
    })

    with patch("app.services.quiz_generator.PAPER_QUIZ_USE_LLM", True):
        with patch("app.services.llm._generate_response", return_value=llm_simulated_questions):
            raw_quiz = gen.generate_paper_quiz_structure(
                niche="conhecimentos_gerais",
                num_questions=1,
            )

    qs = raw_quiz.get("questions", [])
    assert len(qs) >= 1
    llm_q = qs[0]

    # Prova de papel: Pergunta gerada por LLM NUNCA sai como verified
    assert llm_q.get("verified") is False, f"Pergunta de LLM não pode ter verified=True: {llm_q}"
    assert llm_q.get("fact_status") == "UNVERIFIED_LLM_HEURISTIC", (
        f"Esperava UNVERIFIED_LLM_HEURISTIC, obteve: {llm_q.get('fact_status')}"
    )
    assert llm_q.get("publication_gate") == "BLOCKED_PENDING_EXTERNAL_AUDIT", (
        f"Esperava BLOCKED_PENDING_EXTERNAL_AUDIT, obteve: {llm_q.get('publication_gate')}"
    )
