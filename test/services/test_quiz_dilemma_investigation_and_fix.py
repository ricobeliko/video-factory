"""Testes direcionados da Investigação e Correção do Quiz de Escolhas (quiz_dilemma):
1. Diversificação e catálogo rotativo de dilemas anti-duplicação no fallback.
2. Não repetição entre gerações sucessivas e conformidade com o Safety Gate.
3. Isolamento estrito entre quiz_dilemma e quiz_paper.
4. Destravamento seguro e idempotente do circuit breaker exclusivamente para o perfil profile-4d18bf9a5d94.
"""

import os
import shutil
import sqlite3
import tempfile
import pytest

from app.services.quiz_generator import QuizContentGenerator, CANONICAL_DILEMMA_CATALOG
from app.services import quiz_safety_gate
from app.services import scheduler
from app.services import autonomous_production
from app.services import profile_manager


@pytest.fixture
def temp_workspace():
    temp_dir = tempfile.mkdtemp(prefix="test_dilemma_")
    db_path = os.path.join(temp_dir, "test_factory.db")
    task_dir = os.path.join(temp_dir, "tasks")
    os.makedirs(task_dir, exist_ok=True)

    scheduler.init_db(db_path)
    profile_manager.init_profile_db(db_path)
    quiz_safety_gate.init_quiz_safety_db(db_path)

    yield {"temp_dir": temp_dir, "db_path": db_path, "task_dir": task_dir}

    try:
        shutil.rmtree(temp_dir)
    except Exception:
        pass


def test_dilemma_fallback_rotates_and_avoids_duplication(temp_workspace):
    """Valida que o gerador de dilemas rotaciona o catálogo canônico e não gera dilemas repetidos entre vídeos sucessivos."""
    history_dir = os.path.join(temp_workspace["temp_dir"], "storage")
    os.makedirs(history_dir, exist_ok=True)
    generator = QuizContentGenerator(history_dir=history_dir)

    # Gera 3 quizzes sucessivos de dilemas (forçando o fallback determinístico para testar a rotação anti-duplicação)
    quiz1 = generator._generate_fallback_content("curiosidades", "subjective", 8, "Dilema 1", "quiz_choice_religious")
    # Registra as perguntas do quiz1 no histórico como o pipeline real faz
    for q in quiz1["questions"]:
        generator.record_question(q["narration"], "curiosidades", "subjective", f"{q['top']['title']} {q['bottom']['title']}")

    quiz2 = generator._generate_fallback_content("curiosidades", "subjective", 8, "Dilema 2", "quiz_choice_religious")
    for q in quiz2["questions"]:
        generator.record_question(q["narration"], "curiosidades", "subjective", f"{q['top']['title']} {q['bottom']['title']}")

    quiz3 = generator._generate_fallback_content("curiosidades", "subjective", 8, "Dilema 3", "quiz_choice_religious")

    # Extrai as narrações dos dilemas ativos (q1 a q6) de cada quiz
    q1_narrs = [q["narration"] for q in quiz1["questions"][:6]]
    q2_narrs = [q["narration"] for q in quiz2["questions"][:6]]
    q3_narrs = [q["narration"] for q in quiz3["questions"][:6]]

    # Nenhuma das 6 perguntas ativas do quiz2 deve ser idêntica às do quiz1
    assert set(q1_narrs).isdisjoint(set(q2_narrs))
    # Nenhuma das 6 perguntas ativas do quiz3 deve ser idêntica às do quiz2
    assert set(q2_narrs).isdisjoint(set(q3_narrs))


def test_dilemma_safety_gate_passes_consecutive_generations(temp_workspace):
    """Valida que gerações sucessivas com a nova rotação passam no Quiz Safety Gate sem overlap excessivo."""
    db_path = temp_workspace["db_path"]
    history_dir = os.path.join(temp_workspace["temp_dir"], "storage")
    os.makedirs(history_dir, exist_ok=True)
    generator = QuizContentGenerator(history_dir=history_dir)

    quiz1 = generator._generate_fallback_content("curiosidades", "subjective", 8, "Quiz 1", "quiz_choice_religious")
    for q in quiz1["questions"]:
        generator.record_question(q["narration"], "curiosidades", "subjective", f"{q['top']['title']} {q['bottom']['title']}")

    # Constrói script texto simulado do quiz1 e avalia no safety gate
    script1 = "\n".join([f"{q['narration']} Opção A: {q['top']['title']}. Opção B: {q['bottom']['title']}." for q in quiz1["questions"]])
    assessment1 = quiz_safety_gate.evaluate_quiz_script_safety(
        task_id="task-dilemma-01",
        script=script1,
        topic="Quiz 1",
        preset="cross_platform",
        platform="youtube",
        profile_id="profile-4d18bf9a5d94",
        channel_id="channel-escolhas-yt",
        quiz_data=quiz1,
        db_path=db_path,
    )
    assert assessment1["safety_status"] == "PASS"

    # Gera quiz2
    quiz2 = generator._generate_fallback_content("curiosidades", "subjective", 8, "Quiz 2", "quiz_choice_religious")
    for q in quiz2["questions"]:
        generator.record_question(q["narration"], "curiosidades", "subjective", f"{q['top']['title']} {q['bottom']['title']}")

    script2 = "\n".join([f"{q['narration']} Opção A: {q['top']['title']}. Opção B: {q['bottom']['title']}." for q in quiz2["questions"]])
    assessment2 = quiz_safety_gate.evaluate_quiz_script_safety(
        task_id="task-dilemma-02",
        script=script2,
        topic="Quiz 2",
        preset="cross_platform",
        platform="youtube",
        profile_id="profile-4d18bf9a5d94",
        channel_id="channel-escolhas-yt",
        quiz_data=quiz2,
        db_path=db_path,
    )
    assert assessment2["safety_status"] == "PASS"


def test_circuit_breaker_recovery_migration(temp_workspace):
    """Valida o destravamento seguro e idempotente do circuit breaker para profile-4d18bf9a5d94."""
    db_path = temp_workspace["db_path"]

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        # Simula o perfil travado no circuit breaker (10 rejeições, estado cooldown)
        conn.execute(
            "INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES ('autonomous_consecutive_rejections:profile-4d18bf9a5d94', '10');"
        )
        conn.execute(
            "INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES ('autonomous_state:profile-4d18bf9a5d94', 'cooldown');"
        )
        # Mantém intactas as quotas e outros perfis
        conn.execute(
            "INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES ('autonomous_max_generations_24h:profile-4d18bf9a5d94', '10');"
        )
        conn.execute(
            "INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES ('autonomous_consecutive_rejections:profile-other', '7');"
        )
        conn.commit()

        # Executa migrações
        scheduler._run_migrations(conn)

        # 1. Valida que consecutive_rejections do perfil foi zerado
        row_rej = conn.execute(
            "SELECT value FROM autopilot_settings WHERE key = 'autonomous_consecutive_rejections:profile-4d18bf9a5d94';"
        ).fetchone()
        assert row_rej is not None
        assert row_rej["value"] == "0"

        # 2. Valida que estado do perfil foi destravado para idle
        row_st = conn.execute(
            "SELECT value FROM autopilot_settings WHERE key = 'autonomous_state:profile-4d18bf9a5d94';"
        ).fetchone()
        assert row_st is not None
        assert row_st["value"] == "idle"

        # 3. Valida que quotas foram estritamente preservadas
        row_quot = conn.execute(
            "SELECT value FROM autopilot_settings WHERE key = 'autonomous_max_generations_24h:profile-4d18bf9a5d94';"
        ).fetchone()
        assert row_quot is not None
        assert row_quot["value"] == "10"

        # 4. Valida que outros perfis não foram alterados
        row_oth = conn.execute(
            "SELECT value FROM autopilot_settings WHERE key = 'autonomous_consecutive_rejections:profile-other';"
        ).fetchone()
        assert row_oth is not None
        assert row_oth["value"] == "7"


def test_isolation_between_quiz_dilemma_and_quiz_paper(temp_workspace):
    """Valida que os formatos quiz_dilemma e quiz_paper permanecem rigorosamente isolados."""
    history_dir = os.path.join(temp_workspace["temp_dir"], "storage")
    os.makedirs(history_dir, exist_ok=True)
    generator = QuizContentGenerator(history_dir=history_dir)

    # Gera quiz de papel
    paper_quiz = generator.generate_paper_quiz_structure(
        niche="conhecimentos_gerais",
        num_questions=5,
        quiz_title="Quiz Teste Papel",
    )
    # Gera quiz de dilemas
    dilemma_quiz = generator.generate_quiz_structure(
        niche="curiosidades",
        format_type="subjective",
        num_questions=8,
        quiz_title="Dilema Teste",
        closing_type="quiz_choice_religious",
    )

    # 1. Estruturas totalmente distintas
    assert "format_type" in dilemma_quiz and dilemma_quiz["format_type"] == "subjective"
    assert len(dilemma_quiz["questions"]) == 8
    # Papel tem 5 perguntas e cada pergunta tem 4 alternativas
    assert len(paper_quiz["questions"]) == 5
    for q in paper_quiz["questions"]:
        assert len(q["options"]) == 4

    # 2. Arquivos de histórico separados
    paper_hist_file = os.path.join(history_dir, "generated_paper_questions.json")
    dilemma_hist_file = os.path.join(history_dir, "generated_questions.json")
    assert os.path.exists(paper_hist_file)
    assert os.path.exists(dilemma_hist_file)
