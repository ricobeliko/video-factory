"""
test/services/test_quiz_dilemmas_novos.py
==========================================
Validação dos novos requisitos para Quiz Subjetivo (Missão v2/quiz-dilemas-novos):
1. Cenário A: LLM gera repetidos na rodada 1, recupera na rodada 2 com dilemas inéditos ->
   aprovado pelo gerador e aprovado pelo quiz_safety_gate (PASS).
2. Cenário B: LLM não entrega novos após 3 rodadas e catálogo se esgota ->
   falha limpa com código SEM_DILEMAS_NOVOS, sem completar com repetidos.
"""

import json
import tempfile
from unittest.mock import MagicMock, patch
import pytest

from app.models import const
from app.services.quiz_generator import QuizContentGenerator, CANONICAL_DILEMMA_CATALOG
from app.services import quiz_safety_gate


@pytest.fixture
def temp_generator():
    with tempfile.TemporaryDirectory() as temp_dir:
        gen = QuizContentGenerator(history_dir=temp_dir, templates_dir=temp_dir)
        yield gen


def test_scenario_a_llm_multi_round_recovery_and_gate_pass(temp_generator):
    """
    Cenário A:
    - O histórico isolado do canal possui 3 dilemas recentes.
    - Na Rodada 1, a LLM gera 6 dilemas, sendo 3 repetidos do canal e 3 novos.
    - O gerador aceita os 3 novos e rejeita os 3 repetidos.
    - O gerador dispara a Rodada 2 solicitando os 3 faltantes, passando o histórico e os rejeitados.
    - Na Rodada 2, a LLM retorna 3 dilemas inéditos.
    - O gerador completa os 6 dilemas ativos + fecha com Q7 (Jesus) e Q8 (CTA).
    - O quiz gerado é submetido ao quiz_safety_gate e obtém SAFETY_STATUS_PASS.
    """
    gen = temp_generator

    # 1. Histórico isolado do canal (3 dilemas já usados em vídeos anteriores)
    channel_history_dilemmas = [
        {
            "id": "h1",
            "top_title": "VISÃO DE RAIO X",
            "bottom_title": "AUDIÇÃO HIPERSÔNICA",
            "narration": "Você prefere ter visão de raio x... Ou ter audição hipersônica?",
            "is_closing": False,
        },
        {
            "id": "h2",
            "top_title": "FICAR SEM CELULAR",
            "bottom_title": "FICAR SEM INTERNET",
            "narration": "Você prefere ficar um ano sem celular... Ou um ano sem internet?",
            "is_closing": False,
        },
        {
            "id": "h3",
            "top_title": "MORAR NA LUA",
            "bottom_title": "MORAR NO FUNDO DO MAR",
            "narration": "Você prefere morar na lua... Ou morar no fundo do oceano?",
            "is_closing": False,
        },
    ]

    # Simulação da resposta da LLM na Rodada 1: 3 duplicatas (h1, h2, h3) e 3 inéditos (n1, n2, n3)
    llm_round_1_response = json.dumps({
        "questions": [
            {
                "id": "q1",
                "header": "O QUE VOCÊ PREFERE?",
                "narration": "Você prefere ter visão de raio x... Ou ter audição hipersônica?",
                "top": {"title": "VISÃO DE RAIO X", "image_query": "xray vision", "theme": "red"},
                "bottom": {"title": "AUDIÇÃO HIPERSÔNICA", "image_query": "super hearing", "theme": "blue"},
            },
            {
                "id": "q2",
                "header": "DECISÃO DIFÍCIL:",
                "narration": "Você prefere ficar um ano sem celular... Ou um ano sem internet?",
                "top": {"title": "FICAR SEM CELULAR", "image_query": "no phone", "theme": "red"},
                "bottom": {"title": "FICAR SEM INTERNET", "image_query": "no internet", "theme": "blue"},
            },
            {
                "id": "q3",
                "header": "DECISÃO DIFÍCIL:",
                "narration": "Você prefere morar na lua... Ou morar no fundo do oceano?",
                "top": {"title": "MORAR NA LUA", "image_query": "moon base", "theme": "red"},
                "bottom": {"title": "MORAR NO FUNDO DO OCEANO", "image_query": "underwater base", "theme": "blue"},
            },
            {
                "id": "q4",
                "header": "DECISÃO DIFÍCIL:",
                "narration": "Você prefere nunca mais sentir frio... Ou nunca mais sentir calor?",
                "top": {"title": "NUNCA MAIS SENTIR FRIO", "image_query": "warm sunlight", "theme": "red"},
                "bottom": {"title": "NUNCA MAIS SENTIR CALOR", "image_query": "cool breeze", "theme": "blue"},
            },
            {
                "id": "q5",
                "header": "DECISÃO DIFÍCIL:",
                "narration": "Você prefere falar todas as línguas humanas... Ou conseguir falar com os animais?",
                "top": {"title": "FALAR TODAS AS LÍNGUAS", "image_query": "world languages", "theme": "red"},
                "bottom": {"title": "FALAR COM ANIMAIS", "image_query": "talking to animals", "theme": "blue"},
            },
            {
                "id": "q6",
                "header": "DECISÃO DIFÍCIL:",
                "narration": "Você prefere viver dez anos no passado... Ou viajar dez anos para o futuro?",
                "top": {"title": "DEZ ANOS NO PASSADO", "image_query": "retro past", "theme": "red"},
                "bottom": {"title": "DEZ ANOS NO FUTURO", "image_query": "future city", "theme": "blue"},
            },
        ]
    })

    # Simulação da resposta da LLM na Rodada 2: 3 inéditos (n4, n5, n6)
    llm_round_2_response = json.dumps({
        "questions": [
            {
                "id": "q1",
                "header": "DECISÃO DIFÍCIL:",
                "narration": "Você prefere saber a data exata da sua morte... Ou saber a causa da sua morte?",
                "top": {"title": "SABER A DATA DA MORTE", "image_query": "calendar time", "theme": "red"},
                "bottom": {"title": "SABER A CAUSA DA MORTE", "image_query": "destiny question", "theme": "blue"},
            },
            {
                "id": "q2",
                "header": "DECISÃO DIFÍCIL:",
                "narration": "Você prefere poder pausar o tempo por dez minutos ao dia... Ou rebobinar cinco minutos?",
                "top": {"title": "PAUSAR O TEMPO 10 MIN", "image_query": "clock freeze", "theme": "red"},
                "bottom": {"title": "REBOBINAR 5 MINUTOS", "image_query": "rewind time", "theme": "blue"},
            },
            {
                "id": "q3",
                "header": "DECISÃO DIFÍCIL:",
                "narration": "Você prefere ser a pessoa mais inteligente do mundo em uma ilha deserta... Ou ser mediano cercado de amigos?",
                "top": {"title": "MAIS INTELIGENTE ISOLADO", "image_query": "desert island thinker", "theme": "red"},
                "bottom": {"title": "MEDIANO COM AMIGOS", "image_query": "friends laughing", "theme": "blue"},
            },
        ]
    })

    call_count = 0
    prompts_captured = []

    def mock_llm_generate(prompt):
        nonlocal call_count
        call_count += 1
        prompts_captured.append(prompt)
        if call_count == 1:
            return llm_round_1_response
        elif call_count == 2:
            return llm_round_2_response
        return "{}"

    with patch("app.services.llm._generate_response", side_effect=mock_llm_generate):
        raw_quiz = gen.generate_quiz_structure(
            niche="curiosidades_dilemas",
            format_type="subjective",
            num_questions=8,
            quiz_title="ESCOLHAS IMPOSSÍVEIS",
            closing_type="quiz_choice_religious",
            excluded_dilemmas=channel_history_dilemmas,
        )

    # Asserções do Gerador
    assert call_count == 2, f"Esperava 2 chamadas à LLM para recuperação, obteve {call_count}"
    assert len(prompts_captured) == 2
    # Na rodada 2, o prompt deve conter instrução com os dilemas proibidos
    assert "DILEMAS PROIBIDOS - NÃO REPETIR NENHUM DESTES" in prompts_captured[1]

    questions = raw_quiz.get("questions", [])
    assert len(questions) == 8, f"Esperava 8 perguntas no quiz final, obteve {len(questions)}"

    # Verifica que nenhum dos 6 dilemas ativos é duplicata do histórico
    active_questions = questions[:6]
    for aq in active_questions:
        for hd in channel_history_dilemmas:
            sim = gen._normalize_dilemma_for_comparison(aq)
            h_norm = gen._normalize_dilemma_for_comparison(hd)
            score = quiz_safety_gate.dilemma_similarity(sim, h_norm)
            assert score < 0.80, f"Dilema ativo '{sim['narration']}' repete histórico '{h_norm['narration']}' (sim={score})"

    # Dilemas de fechamento q7 e q8
    assert questions[6]["is_closing_choice"] is True
    assert "jesus" in (questions[6]["narration"] + " " + questions[6]["bottom"]["title"]).lower()
    assert questions[7]["is_closing_choice"] is True
    assert any(k in questions[7]["narration"].lower() for k in ("seguir", "canal", "perfil", "apoiar", "curtir"))

    # 2. Avaliação estrita no Safety Gate
    video_script = "\n\n".join(f"[{q['id']}] {q['header']} {q['narration']}" for q in questions)
    isolated_history_records = [
        {
            "task_id": "hist_task_1",
            "profile_id": "profile_quiz_teste",
            "channel_id": "chan_quiz_1",
            "dilemmas": channel_history_dilemmas,
        }
    ]

    safety_result = quiz_safety_gate.evaluate_quiz_script_safety(
        task_id="task_test_new_dilemmas",
        topic="ESCOLHAS IMPOSSÍVEIS",
        script=video_script,
        quiz_data=raw_quiz,
        narrative_structure=const.STRUCTURE_QUIZ_DILEMMA,
        platform="youtube",
        profile_id="profile_quiz_teste",
        channel_id="chan_quiz_1",
        history=isolated_history_records,
    )

    assert safety_result["safety_status"] == const.SAFETY_STATUS_PASS, (
        f"Quiz deveria passar no safety gate mas obteve: {safety_result['safety_status']} - {safety_result.get('safety_reasons')}"
    )


def test_scenario_b_exhaustion_raises_sem_dilemas_novos(temp_generator):
    """
    Cenário B:
    - O histórico do canal já utilizou TODOS os itens do CANONICAL_DILEMMA_CATALOG.
    - A LLM falha ou devolve apenas duplicatas em todas as 3 rodadas.
    - O gerador tenta o catálogo canônico, mas todos os itens são duplicatas sob Critério 2.
    - O gerador DEVE falhar imediatamente levantando RuntimeError com o código 'SEM_DILEMAS_NOVOS'.
    - NUNCA completar com dilemas repetidos.
    """
    gen = temp_generator

    # Histórico do canal consome todo o CANONICAL_DILEMMA_CATALOG
    channel_history_exhausted = []
    for idx, item in enumerate(CANONICAL_DILEMMA_CATALOG):
        channel_history_exhausted.append({
            "id": f"used_cat_{idx}",
            "top_title": item["top"]["title"],
            "bottom_title": item["bottom"]["title"],
            "narration": item["narration"],
            "is_closing": False,
        })

    # LLM devolve sempre uma duplicata idêntica ao item 0 do histórico
    duplicate_response = json.dumps({
        "questions": [
            {
                "id": "q1",
                "header": "O QUE VOCÊ PREFERE?",
                "narration": CANONICAL_DILEMMA_CATALOG[0]["narration"],
                "top": {"title": CANONICAL_DILEMMA_CATALOG[0]["top"]["title"], "image_query": "test", "theme": "red"},
                "bottom": {"title": CANONICAL_DILEMMA_CATALOG[0]["bottom"]["title"], "image_query": "test", "theme": "blue"},
            }
        ]
    })

    call_count = 0
    def mock_llm_always_duplicate(prompt):
        nonlocal call_count
        call_count += 1
        return duplicate_response

    with patch("app.services.llm._generate_response", side_effect=mock_llm_always_duplicate):
        with pytest.raises(RuntimeError) as exc_info:
            gen.generate_quiz_structure(
                niche="curiosidades_dilemas",
                format_type="subjective",
                num_questions=8,
                quiz_title="ESCOLHAS IMPOSSÍVEIS",
                closing_type="quiz_choice_religious",
                excluded_dilemmas=channel_history_exhausted,
            )

    err_str = str(exc_info.value)
    assert "SEM_DILEMAS_NOVOS" in err_str, f"Esperava código SEM_DILEMAS_NOVOS na exceção, obteve: {err_str}"
    assert call_count == 3, f"Esperava exatamente 3 rodadas de LLM antes de esgotar, obteve {call_count}"


def test_task_pipeline_marks_sem_dilemas_novos():
    """
    Verifica que se generate_quiz_structure levantar SEM_DILEMAS_NOVOS,
    o pipeline de task captura e registra a falha com stage='script' e error_code='SEM_DILEMAS_NOVOS'.
    """
    from app.services import state as sm
    from app.services.task import _mark_task_failed
    from app.models.schema import VideoParams

    test_tid = "task_test_fail_sem_dilemas"
    sm.state.update_task(test_tid, state=const.TASK_STATE_PROCESSING, progress=10, stage="SCRIPT")

    # Simula a captura de exceção SEM_DILEMAS_NOVOS conforme implementado em task.py
    exc_message = "SEM_DILEMAS_NOVOS: Não foi possível obter 6 dilemas inéditos para o canal."
    err_details = {
        "error_code": "SEM_DILEMAS_NOVOS",
        "reason": exc_message,
    }
    result = _mark_task_failed(test_tid, "script", f"Quiz generation failed: {exc_message}", details=err_details)

    assert result["state"] == const.TASK_STATE_FAILED
    assert result["failed_stage"] == "script"
    assert result["error_code"] == "SEM_DILEMAS_NOVOS"

    # Confirma que no estado em memória os metadados estão presentes
    saved_state = sm.state.get_task(test_tid)
    assert saved_state["error_code"] == "SEM_DILEMAS_NOVOS"
    assert saved_state["failed_stage"] == "script"
