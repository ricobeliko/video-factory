"""Testes direcionados da Missão K:
1. Calibração dinâmica da timeline do Quiz de Papel (quiz_paper) para atingir 60-65s.
2. Preservação do Duration Gate contra durações anômalas (fail-closed).
3. Reconciliação e persistência explícita de limites (Global 100/100, Procedurais 10/30).
4. Preservação de proteções de custo para canais Google Flow (5/15).
5. Idempotência da migração da Missão K.
"""

import asyncio
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
import pytest

from scripts.poc_quiz_paper_render import PaperQuizEngine, PaperQuizConfig, DurationGateError
from app.services import scheduler
from app.services import autonomous_production
from app.services import profile_manager


@pytest.fixture
def temp_workspace():
    temp_dir = tempfile.mkdtemp(prefix="test_mission_k_")
    db_path = os.path.join(temp_dir, "test_factory.db")
    task_dir = os.path.join(temp_dir, "tasks")
    os.makedirs(task_dir, exist_ok=True)

    scheduler.init_db(db_path)
    profile_manager.init_profile_db(db_path)

    yield {"temp_dir": temp_dir, "db_path": db_path, "task_dir": task_dir}

    try:
        shutil.rmtree(temp_dir)
    except Exception:
        pass


def test_quiz_paper_dynamic_calibration_achieves_target_duration():
    """Valida que o Quiz de Papel com 5 perguntas curtas calibra pausas e atinge entre 60.0s e 65.0s."""
    async def _run_async():
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = PaperQuizConfig(
                temp_dir=tmp_dir,
                output_video_path=os.path.join(tmp_dir, "output.mp4"),
                output_thumbnail_path=os.path.join(tmp_dir, "output.jpg"),
                timing_settings={
                    "intro_sec": 4.43,
                    "outro_sec": 6.00,
                    "expectation_sec": 6.00,
                    "reveal_sec": 1.00,
                    "target_duration_range": [60.0, 65.0],
                },
                questions=[
                    {
                        "id": f"q_{i}",
                        "question": f"Pergunta número {i}?",
                        "narration": f"Pergunta número {i} narrada",
                        "options": ["Opção A", "Opção B", "Opção C", "Opção D"],
                        "correct_index": 0,
                        "explanation": "Explicação curta.",
                    }
                    for i in range(1, 6)
                ],
            )

            engine = PaperQuizEngine(config)

            # Simula voz com 2.0s por pergunta (5 perguntas = 10.0s de voz)
            # Baseline = 4.43 + 6.00 = 10.43s
            # Total sem calibração = 10.43 + 10.0 + 5*(6.0+1.0) = 55.43s (< 60.0s)
            # Com calibração dinâmica: deve calibrar expectation_sec e reveal_sec para atingir ~62.5s
            async def fake_synthesize_voice(text, out_path):
                return 2.00

            engine.synthesize_voice = fake_synthesize_voice

            selected_q, est_dur = await engine.select_questions_for_target_duration(
                candidate_questions=config.questions,
                target_min=60.0,
                target_max=65.0,
            )

            assert len(selected_q) == 5
            assert 60.0 <= est_dur <= 65.0

            calibrated_exp = float(engine.config.timing_settings["expectation_sec"])
            calibrated_rev = float(engine.config.timing_settings["reveal_sec"])

            # Pausa por questão necessária = (62.5 - 20.43) / 5 = 42.07 / 5 = 8.414s
            total_dur = 10.43 + 10.0 + (5 * (calibrated_exp + calibrated_rev))
            assert 60.0 <= total_dur <= 65.0
            assert 5.0 <= calibrated_exp <= 8.5
            assert 1.0 <= calibrated_rev <= 3.0

    asyncio.run(_run_async())


def test_quiz_paper_duration_gate_fails_closed_on_anomalous_durations():
    """Valida que o Duration Gate continua levantando DurationGateError para casos anômalos que exigiriam pausas fora do limite seguro."""
    async def _run_async():
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = PaperQuizConfig(
                temp_dir=tmp_dir,
                output_video_path=os.path.join(tmp_dir, "output.mp4"),
                output_thumbnail_path=os.path.join(tmp_dir, "output.jpg"),
                timing_settings={
                    "intro_sec": 4.43,
                    "outro_sec": 6.00,
                    "expectation_sec": 6.00,
                    "reveal_sec": 1.00,
                    "target_duration_range": [60.0, 65.0],
                },
                # Apenas 1 pergunta fornecida (impossível atingir 60s mantendo pausas seguras <= 11s)
                questions=[
                    {
                        "id": "q_single",
                        "question": "Pergunta única?",
                        "narration": "Pergunta única",
                        "options": ["A", "B", "C", "D"],
                        "correct_index": 0,
                        "explanation": "Exp",
                    }
                ],
            )

            engine = PaperQuizEngine(config)

            async def fake_synthesize_voice(text, out_path):
                return 2.00

            engine.synthesize_voice = fake_synthesize_voice

            with pytest.raises(DurationGateError) as exc_info:
                await engine.select_questions_for_target_duration(
                    candidate_questions=config.questions,
                    target_min=60.0,
                    target_max=65.0,
                )

            assert "faixa permitida" in str(exc_info.value) or "DURATION GATE ERROR" in str(exc_info.value)

    asyncio.run(_run_async())


def test_mission_k_migration_and_limit_reconciliation(temp_workspace):
    """Valida a migração da Missão K: reconciliação e persistência explícita no SQLite."""
    db_path = temp_workspace["db_path"]
    now_iso = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        # Insere dados legados pré-Missão K na tabela autopilot_settings
        conn.execute("INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES ('autonomous_max_generations_24h', '5');")
        conn.execute("INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES ('autonomous_max_attempts_24h', '15');")

        # Insere perfil de Quiz de Papel e perfil Dose Diária de Escolhas em modo SCALE
        conn.execute(
            "INSERT OR REPLACE INTO content_profiles (id, name, slug, growth_mode, settings_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?);",
            ("profile-45cee883f80a", "Quiz_Quiz", "quiz-quiz", "scale", '{"structure": "quiz_paper", "video_format": "quiz_paper"}', now_iso, now_iso)
        )
        conn.execute(
            "INSERT OR REPLACE INTO content_profiles (id, name, slug, growth_mode, settings_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?);",
            ("profile-4d18bf9a5d94", "Dose Diária de Escolhas", "dose-escolhas", "scale", '{"structure": "quiz_dilemma"}', now_iso, now_iso)
        )
        conn.execute(
            "INSERT OR REPLACE INTO content_profiles (id, name, slug, growth_mode, settings_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?);",
            ("profile-historias-misterio", "Dose Diária de Histórias", "historias", "scale", '{"narrative_structure": "three_acts"}', now_iso, now_iso)
        )
        conn.commit()

        # Executa migrações
        scheduler._run_migrations(conn)

        # 1. Valida migração da Missão K concluída
        mig_row = conn.execute("SELECT value FROM autopilot_settings WHERE key = 'migration_mission_k_reconcile_capacity_v1';").fetchone()
        assert mig_row is not None
        assert mig_row["value"] == "done"

        # 2. Valida limites globais explicitamente gravados no SQLite com 100
        g_gen = conn.execute("SELECT value FROM autopilot_settings WHERE key = 'autonomous_global_max_generations_24h';").fetchone()
        assert g_gen is not None
        assert g_gen["value"] == "100"

        g_att = conn.execute("SELECT value FROM autopilot_settings WHERE key = 'autonomous_global_max_attempts_24h';").fetchone()
        assert g_att is not None
        assert g_att["value"] == "100"

        # 3. Valida limites do Quiz de Papel explicitamente persistidos no SQLite (10 / 30)
        p_paper_gen = conn.execute("SELECT value FROM autopilot_settings WHERE key = 'autonomous_max_generations_24h:profile-45cee883f80a';").fetchone()
        assert p_paper_gen is not None
        assert p_paper_gen["value"] == "10"

        p_paper_att = conn.execute("SELECT value FROM autopilot_settings WHERE key = 'autonomous_max_attempts_24h:profile-45cee883f80a';").fetchone()
        assert p_paper_att is not None
        assert p_paper_att["value"] == "30"

        # 4. Valida limites do Quiz de Escolhas explicitamente persistidos no SQLite (10 / 30)
        p_dilemma_gen = conn.execute("SELECT value FROM autopilot_settings WHERE key = 'autonomous_max_generations_24h:profile-4d18bf9a5d94';").fetchone()
        assert p_dilemma_gen is not None
        assert p_dilemma_gen["value"] == "10"

        # 5. Valida canal tradicional Flow (profile-historias-misterio)
        # Não é procedural, logo NÃO recebe a chave de 10/30
        p_flow_gen = conn.execute("SELECT value FROM autopilot_settings WHERE key = 'autonomous_max_generations_24h:profile-historias-misterio';").fetchone()
        assert p_flow_gen is None

        # 6. Valida que a chave legada global sem sufixo permanece intacta (5/15) para resguardo de canais legados
        legacy_gen = conn.execute("SELECT value FROM autopilot_settings WHERE key = 'autonomous_max_generations_24h';").fetchone()
        assert legacy_gen is not None
        assert legacy_gen["value"] == "5"

        legacy_att = conn.execute("SELECT value FROM autopilot_settings WHERE key = 'autonomous_max_attempts_24h';").fetchone()
        assert legacy_att is not None
        assert legacy_att["value"] == "15"

    # 7. Valida getters em memória com o banco conectado em modo SCALE
    assert autonomous_production.get_global_max_generations_24h(db_path=db_path) == 100
    assert autonomous_production.get_global_max_attempts_24h(db_path=db_path) == 100
    assert autonomous_production.get_max_generations_24h("profile-45cee883f80a", db_path=db_path) == 10
    assert autonomous_production.get_max_attempts_24h("profile-45cee883f80a", db_path=db_path) == 30
    # Flow retorna a proteção de custo 5/15 mesmo em SCALE
    assert autonomous_production.get_max_generations_24h("profile-historias-misterio", db_path=db_path) == 5
    assert autonomous_production.get_max_attempts_24h("profile-historias-misterio", db_path=db_path) == 15

    # 8. Valida idempotência: executar _run_migrations novamente não altera nada
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        scheduler._run_migrations(conn)
        mig_row_after = conn.execute("SELECT value FROM autopilot_settings WHERE key = 'migration_mission_k_reconcile_capacity_v1';").fetchone()
        assert mig_row_after["value"] == "done"
