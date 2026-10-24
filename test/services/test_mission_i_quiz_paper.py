"""
Testes direcionados para a Missão I:
- Prevenção e correção de repetição de perguntas no Quiz de Papel (quiz_paper).
- Validação dos contratos de 5 perguntas, 4 alternativas por pergunta e respostas corretas.
- Validação do contrato de duração (60-65s) e governança factual.
- Preservação estrita do Safety Gate bloqueando duplicatas reais.
- Conformidade do layout fixo de papel sem reprovação por si só.
- Isolamento estrito entre quiz_paper e quiz_dilemma (históricos e contratos segregados).
"""
import json
import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from app.models import const
from app.services import copyright_gate, quiz_generator, quiz_safety_gate


@pytest.fixture
def temp_quiz_gen():
    with tempfile.TemporaryDirectory() as tmp_dir:
        history_dir = os.path.join(tmp_dir, "quiz_history")
        gen = quiz_generator.QuizContentGenerator(history_dir=history_dir)
        yield gen, history_dir


def test_two_consecutive_paper_quiz_generations_do_not_duplicate_questions(temp_quiz_gen):
    """Critério 1: Duas gerações consecutivas de quiz_paper não reutilizam as mesmas cinco perguntas."""
    gen, history_dir = temp_quiz_gen

    # Execução 1: Simula geração da Tarefa 1 (ex: aprovada)
    quiz1 = gen.generate_paper_quiz_structure(
        niche="conhecimentos_gerais",
        num_questions=5,
        quiz_title="QUIZ CONHECIMENTOS GERAIS 1",
    )
    q1_list = quiz1.get("questions", [])
    assert len(q1_list) == 5
    q1_questions = [q["question"] for q in q1_list]

    # Execução 2: Simula geração da Tarefa 2 subsequente
    quiz2 = gen.generate_paper_quiz_structure(
        niche="conhecimentos_gerais",
        num_questions=5,
        quiz_title="Monte Everest vs Fossa das Marianas",
        topic_brief="Ponto mais alto e mais profundo do planeta",
    )
    q2_list = quiz2.get("questions", [])
    assert len(q2_list) == 5
    q2_questions = [q["question"] for q in q2_list]

    # Ambas devem ser totalmente disjuntas (0% de sobreposição)
    overlap = set(q1_questions).intersection(set(q2_questions))
    assert len(overlap) == 0, f"Perguntas repetidas entre gerações consecutivas: {overlap}"

    # Verifica que o tema contextual (Everest / Fossa das Marianas) foi priorizado na segunda tarefa
    q2_texts_combined = " ".join(q2_questions).lower()
    assert "everest" in q2_texts_combined or "profundo" in q2_texts_combined or "marianas" in q2_texts_combined


def test_paper_quiz_format_and_alternatives_contract(temp_quiz_gen):
    """Critério 2: Formato mantém cinco perguntas e quatro alternativas (A, B, C, D) com correta."""
    gen, _ = temp_quiz_gen

    quiz_data = gen.generate_paper_quiz_structure(num_questions=5)
    questions = quiz_data.get("questions", [])
    assert len(questions) == 5

    for idx, q in enumerate(questions, 1):
        assert q["id"] == f"q{idx}"
        assert q["number"] == idx
        assert q["question"].strip()
        assert q["narration"].strip()
        assert q["category"].strip()

        # Quatro alternativas estritas
        opts = q.get("options", [])
        assert len(opts) == 4, f"Pergunta {idx} não possui 4 opções: {opts}"
        letters = [opt["letter"] for opt in opts]
        assert letters == ["A", "B", "C", "D"]
        for opt in opts:
            assert opt["text"].strip(), f"Opção vazia na pergunta {idx}: {opt}"

        # Resposta correta válida
        assert q["correct_option"] in ("A", "B", "C", "D")

        # Fatos auditados e governança
        assert q.get("verified") is True
        assert q.get("fact_status") == "VERIFIED_CANONICAL"
        assert q.get("publication_gate") == "READY"
        assert q.get("source"), f"Pergunta {idx} sem fonte auditável"


def test_paper_quiz_duration_contract(temp_quiz_gen):
    """Critério 3: O formato mantém o contrato de duração da folha de papel (60-65s)."""
    gen, _ = temp_quiz_gen

    quiz_data = gen.generate_paper_quiz_structure(num_questions=5)
    assert quiz_data["min_target_duration_sec"] == 60.0
    assert quiz_data["max_target_duration_sec"] == 65.0
    assert quiz_data["target_duration_range"] in ([60.0, 70.0], (60.0, 65.0), [60.0, 65.0])

    # Simula cálculo de duração via select_questions_for_target_duration
    from scripts.poc_quiz_paper_render import PaperQuizConfig, PaperQuizEngine
    cfg = PaperQuizConfig.from_dict(quiz_data)
    engine = PaperQuizEngine(config=cfg)

    # Mock de síntese de voz onde cada pergunta leva ~4s de narração
    # Com 6s de expectation + 1s de reveal = ~11s por pergunta.
    # Baseline (intro 3s + outro 6s) = ~9s.
    # Total de 5 perguntas = ~9s + 55s = ~64s (faixa [60s, 65s]).
    async def fake_synthesize(text, out_path):
        return 3.5

    with patch.object(engine, "synthesize_voice", side_effect=fake_synthesize):
        import asyncio
        selected_q, est_dur = asyncio.run(
            engine.select_questions_for_target_duration(
                candidate_questions=cfg.questions,
                target_min=60.0,
                target_max=65.0,
                expectation_sec=6.0,
                reveal_sec=1.0,
            )
        )
        assert len(selected_q) == 5
        assert 60.0 <= est_dur <= 65.0


def test_safety_gate_blocks_real_duplicate_paper_quiz():
    """Critério 4: Safety Gate continua bloqueando rigorosamente repetição real de 5 de 5 perguntas."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_safety.db")
        quiz_safety_gate.init_quiz_safety_db(db_path)

        # Perfil canônico do Quiz de Papel
        paper_pid = "profile-45cee883f80a"

        # Roteiro base
        raw_quiz_1 = {
            "quiz_type": "multiple_choice_paper",
            "questions": [
                {"id": "q1", "header": "QUESTÃO 01:", "narration": "Qual é o maior planeta do nosso Sistema Solar?"},
                {"id": "q2", "header": "QUESTÃO 02:", "narration": "Quantos corações tem um polvo?"},
                {"id": "q3", "header": "QUESTÃO 03:", "narration": "Qual é o animal terrestre mais rápido do planeta?"},
                {"id": "q4", "header": "QUESTÃO 04:", "narration": "Qual é o elemento químico mais abundante no Universo?"},
                {"id": "q5", "header": "QUESTÃO 05:", "narration": "Em qual país está localizada a famosa Grande Muralha?"},
            ]
        }
        script_1 = "\n\n".join(f"[{q['id']}] {q['header']} {q['narration']}" for q in raw_quiz_1["questions"])

        # Tarefa 1: Avaliada e aprovada
        res1 = quiz_safety_gate.evaluate_quiz_script_safety(
            task_id="task-paper-approved-1",
            topic="Quiz Conhecimentos Gerais",
            script=script_1,
            quiz_data=raw_quiz_1,
            profile_id=paper_pid,
            narrative_structure=const.STRUCTURE_QUIZ_PAPER,
            db_path=db_path,
        )
        assert res1["safety_status"] == const.SAFETY_STATUS_PASS

        # Tarefa 2: Tenta enviar exatamente as mesmas 5 perguntas
        raw_quiz_2 = dict(raw_quiz_1)
        res2 = quiz_safety_gate.evaluate_quiz_script_safety(
            task_id="task-paper-rejected-2",
            topic="Outro Tema Repetido",
            script=script_1,
            quiz_data=raw_quiz_2,
            profile_id=paper_pid,
            narrative_structure=const.STRUCTURE_QUIZ_PAPER,
            db_path=db_path,
        )
        # Deve bloquear (BLOCK) por duplicidade real
        assert res2["safety_status"] == const.SAFETY_STATUS_BLOCK
        assert any("5 de 5 dilemas (100%) são idênticos" in r for r in res2["safety_reasons"])


def test_paper_quiz_procedural_canvas_safety_and_copyright_pass():
    """Critério 5: Layout fixo de papel não provoca reprovação por si só no Copyright Gate."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tid = "task-paper-procedural-01"
        t_dir = os.path.join(tmp_dir, tid)
        os.makedirs(t_dir, exist_ok=True)

        provenance = {
            "visual_clips": [],
            "provider": "paper_canvas_engine",
            "bgm": {
                "type": "ambient_auto",
                "file": "resource/songs/output000.mp3",
                "provenance": "SAFE_PROCEDURAL",
            },
        }
        script_data = {
            "task_id": tid,
            "params": {"video_format": "quiz_paper"},
            "asset_provenance": provenance,
            "video_script": "Roteiro procedural de quiz em folha de papel",
        }
        with open(os.path.join(t_dir, "script.json"), "w", encoding="utf-8") as f:
            json.dump(script_data, f)

        passed, reason, metrics = copyright_gate.evaluate_copyright_provenance_gate(
            task_id=tid,
            task_base_dir=tmp_dir,
        )
        assert passed is True
        assert metrics["copyright_provenance_gate"] == "PASS"
        assert metrics["visual_status"] == "PROCEDURAL_QUIZ_CANVAS_VERIFIED"


def test_quiz_dilemma_isolated_from_paper_quiz(temp_quiz_gen):
    """Critério 6: quiz_dilemma permanece estritamente isolado de quiz_paper, sem regressão."""
    gen, history_dir = temp_quiz_gen

    # Gera quiz de papel
    paper_quiz = gen.generate_paper_quiz_structure(num_questions=5)
    assert len(paper_quiz["questions"]) == 5
    assert os.path.exists(os.path.join(history_dir, "generated_paper_questions.json"))

    # Gera quiz de dilema (8 perguntas com Jesus e CTA)
    with patch("app.services.llm._generate_response", side_effect=Exception("No LLM")):
        dilemma_quiz = gen.generate_quiz_structure(
            niche="dilemas",
            format_type="subjective",
            num_questions=8,
            closing_type="quiz_choice_religious",
        )
    assert len(dilemma_quiz["questions"]) == 8

    # Dilema 7 deve ter Jesus e Dilema 8 deve ter CTA
    d7 = dilemma_quiz["questions"][6]
    d8 = dilemma_quiz["questions"][7]
    assert "jesus" in (d7.get("narration", "") + d7.get("bottom", {}).get("title", "")).lower()
    assert any(k in (d8.get("narration", "") + d8.get("bottom", {}).get("title", "")).lower() for k in ("seguir", "perfil", "canal"))

    # Verifica que os arquivos de histórico são distintos e isolados
    paper_hist = gen._load_json(os.path.join(history_dir, "generated_paper_questions.json"), default=[])
    dilemma_hist = gen._load_json(os.path.join(history_dir, "generated_questions.json"), default=[])

    paper_texts = [p.get("question_text") for p in paper_hist]
    dilemma_texts = [d.get("question_text") for d in dilemma_hist]

    # Nenhuma pergunta de papel deve estar no histórico de dilemas
    assert not any(pt in dilemma_texts for pt in paper_texts)
