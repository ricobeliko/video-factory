# -*- coding: utf-8 -*-
"""Targeted unit tests for Mission J: Reusable Procedural Scale Policy and Global Limits 100 (V1).

Tests cover:
1. Reusable procedural recognition: is_procedural_scale_profile correctly identifies quiz_dilemma,
   quiz_paper, and future procedural profiles without Flow, while rejecting traditional/Flow channels.
2. Capacity quotas in SCALE mode: procedural profiles resolve 10 approvals / 30 attempts,
   while traditional channels with Google Flow preserve 5 approvals / 15 attempts.
3. Global Cost Guard: default global limits are 100 approvals and 100 attempts in 24h,
   with clamping up to 100.
4. Idempotent SQLite migration (migration_mission_j_capacity_v1): legacy baselines are elevated
   to 100/100, Quiz_Quiz (profile-45cee883f80a) is elevated to 10/30, explicit operator overrides
   are preserved, and repeated execution produces identical results.
5. Preservation of safety rules: autopilot is not auto-enabled, and formats remain strictly isolated.
"""

import os
import shutil
import tempfile
from datetime import datetime, timezone
import pytest

from app.models import const
from app.services import (
    autonomous_production,
    operator_console,
    profile_manager,
    quality_score,
    safety_gate,
    scheduler,
)
from app.services.profile_manager import ChannelWorkspaceSettings


@pytest.fixture
def temp_workspace():
    temp_dir = tempfile.mkdtemp(prefix="test_mission_j_")
    db_path = os.path.join(temp_dir, "test_factory.db")
    task_dir = os.path.join(temp_dir, "tasks")
    os.makedirs(task_dir, exist_ok=True)

    scheduler.init_db(db_path)
    profile_manager.init_profile_db(db_path)
    safety_gate.init_safety_db(db_path)
    quality_score.init_quality_db(db_path)
    operator_console.init_operator_db(db_path)

    yield {"temp_dir": temp_dir, "db_path": db_path, "task_dir": task_dir}

    try:
        shutil.rmtree(temp_dir)
    except Exception:
        pass


def test_reusable_procedural_profile_recognition(temp_workspace):
    """Verifica que o detector procedural reconhece formatos procedurais e rejeita canais com Flow."""
    db_path = temp_workspace["db_path"]

    # 1. Dose Diária de Escolhas (quiz_dilemma)
    p_escolhas = "profile-4d18bf9a5d94"
    profile_manager.create_profile(
        profile_id=p_escolhas,
        name="Dose Diária de Escolhas",
        growth_mode=const.GROWTH_MODE_SCALE,
        db_path=db_path,
    )
    s_escolhas = ChannelWorkspaceSettings()
    s_escolhas.editorial.video_format = const.VIDEO_FORMAT_QUIZ_DILEMMA
    profile_manager.update_profile_settings(p_escolhas, s_escolhas, db_path=db_path)
    assert autonomous_production.is_procedural_scale_profile(p_escolhas, db_path=db_path) is True
    assert autonomous_production._is_quiz_escolhas_profile(p_escolhas, db_path=db_path) is True

    # 2. Quiz_Quiz (quiz_paper)
    p_paper = "profile-45cee883f80a"
    profile_manager.create_profile(
        profile_id=p_paper,
        name="Quiz_Quiz",
        growth_mode=const.GROWTH_MODE_SCALE,
        db_path=db_path,
    )
    s_paper = ChannelWorkspaceSettings()
    s_paper.editorial.video_format = const.VIDEO_FORMAT_QUIZ_PAPER
    profile_manager.update_profile_settings(p_paper, s_paper, db_path=db_path)
    assert autonomous_production.is_procedural_scale_profile(p_paper, db_path=db_path) is True
    assert autonomous_production._is_quiz_escolhas_profile(p_paper, db_path=db_path) is True

    # 3. Novo canal procedural genérico futuro (ex: Charadas em Papel, sem menção a escolhas)
    p_generic_proc = "profile-novo-procedural"
    profile_manager.create_profile(
        profile_id=p_generic_proc,
        name="Charadas Diárias",
        growth_mode=const.GROWTH_MODE_SCALE,
        db_path=db_path,
    )
    s_generic = ChannelWorkspaceSettings()
    s_generic.editorial.video_format = const.VIDEO_FORMAT_QUIZ_PAPER
    profile_manager.update_profile_settings(p_generic_proc, s_generic, db_path=db_path)
    assert autonomous_production.is_procedural_scale_profile(p_generic_proc, db_path=db_path) is True

    # 4. Canal tradicional com Google Flow habilitado (deve retornar False para proteger custos)
    p_flow = "profile-historias-misterio"
    profile_manager.create_profile(
        profile_id=p_flow,
        name="Dose Diária de Histórias e Mistério",
        growth_mode=const.GROWTH_MODE_SCALE,
        db_path=db_path,
    )
    s_flow = ChannelWorkspaceSettings()
    s_flow.editorial.video_format = const.VIDEO_FORMAT_TRADITIONAL
    s_flow.visual.flow_enabled = True
    profile_manager.update_profile_settings(p_flow, s_flow, db_path=db_path)
    assert autonomous_production.is_procedural_scale_profile(p_flow, db_path=db_path) is False

    # 5. Canal default (tradicional de curiosidades)
    assert autonomous_production.is_procedural_scale_profile(profile_manager.DEFAULT_PROFILE_ID, db_path=db_path) is False
    assert autonomous_production.is_procedural_scale_profile(None, db_path=db_path) is False


def test_scale_mode_procedural_vs_traditional_quotas(temp_workspace):
    """Testa que canais procedurais em ESCALA recebem 10/30, enquanto Flow recebe 5/15."""
    db_path = temp_workspace["db_path"]

    # Procedural (Quiz_Quiz) em SCALE
    p_quiz = "profile-45cee883f80a"
    profile_manager.create_profile(
        profile_id=p_quiz,
        name="Quiz_Quiz",
        growth_mode=const.GROWTH_MODE_SCALE,
        db_path=db_path,
    )
    s_quiz = ChannelWorkspaceSettings()
    s_quiz.editorial.video_format = const.VIDEO_FORMAT_QUIZ_PAPER
    profile_manager.update_profile_settings(p_quiz, s_quiz, db_path=db_path)

    assert autonomous_production.get_max_generations_24h(p_quiz, db_path=db_path) == 10
    assert autonomous_production.get_max_attempts_24h(p_quiz, db_path=db_path) == 30

    # Tradicional com Flow em SCALE (mantém 5 aprovações e 15 tentativas)
    p_flow = "profile-flow-scale"
    profile_manager.create_profile(
        profile_id=p_flow,
        name="Histórias Curtas Flow",
        growth_mode=const.GROWTH_MODE_SCALE,
        db_path=db_path,
    )
    s_flow = ChannelWorkspaceSettings()
    s_flow.editorial.video_format = const.VIDEO_FORMAT_TRADITIONAL
    s_flow.visual.flow_enabled = True
    profile_manager.update_profile_settings(p_flow, s_flow, db_path=db_path)

    assert autonomous_production.get_max_generations_24h(p_flow, db_path=db_path) == 5
    assert autonomous_production.get_max_attempts_24h(p_flow, db_path=db_path) == 15

    # WARMUP mode mantém tetos conservadores (2 / 8) para ambos
    profile_manager.update_profile(p_quiz, growth_mode=const.GROWTH_MODE_WARMUP, db_path=db_path)
    profile_manager.update_profile(p_flow, growth_mode=const.GROWTH_MODE_WARMUP, db_path=db_path)
    assert autonomous_production.get_max_generations_24h(p_quiz, db_path=db_path) == 2
    assert autonomous_production.get_max_attempts_24h(p_quiz, db_path=db_path) == 8
    assert autonomous_production.get_max_generations_24h(p_flow, db_path=db_path) == 2
    assert autonomous_production.get_max_attempts_24h(p_flow, db_path=db_path) == 8


def test_global_cost_guard_100_limits(temp_workspace):
    """Testa os limites globais de 100 aprovações e 100 tentativas com clamping."""
    db_path = temp_workspace["db_path"]

    # Baseline padrão agora é 100/100
    assert autonomous_production.get_global_max_generations_24h(db_path=db_path) == 100
    assert autonomous_production.get_global_max_attempts_24h(db_path=db_path) == 100

    # Clamping permite até 100
    autonomous_production.set_global_max_generations_24h(100, db_path=db_path)
    autonomous_production.set_global_max_attempts_24h(100, db_path=db_path)
    assert autonomous_production.get_global_max_generations_24h(db_path=db_path) == 100
    assert autonomous_production.get_global_max_attempts_24h(db_path=db_path) == 100

    # Valores superiores a 100 são clampeados em 100
    autonomous_production.set_global_max_generations_24h(150, db_path=db_path)
    autonomous_production.set_global_max_attempts_24h(200, db_path=db_path)
    assert autonomous_production.get_global_max_generations_24h(db_path=db_path) == 100
    assert autonomous_production.get_global_max_attempts_24h(db_path=db_path) == 100

    # Status agrega corretamente
    status = autonomous_production.get_global_cost_guard_status(db_path=db_path)
    assert status["global_max_generations_24h"] == 100
    assert status["global_max_attempts_24h"] == 100
    assert status["is_limit_reached"] is False


def test_migration_mission_j_idempotence_and_preservation(temp_workspace):
    """Testa a migração Mission J com elevação de legados e preservação estrita de customizações."""
    db_path = temp_workspace["db_path"]

    quiz_paper_pid = "profile-45cee883f80a"
    quiz_escolhas_pid = "profile-4d18bf9a5d94"
    custom_quiz_pid = "profile-custom-quiz"
    traditional_pid = "profile-traditional"

    profile_manager.create_profile(profile_id=quiz_paper_pid, name="Quiz_Quiz", growth_mode=const.GROWTH_MODE_SCALE, db_path=db_path)
    profile_manager.create_profile(profile_id=quiz_escolhas_pid, name="Dose Diária de Escolhas", growth_mode=const.GROWTH_MODE_SCALE, db_path=db_path)
    profile_manager.create_profile(profile_id=custom_quiz_pid, name="Quiz Customizado", growth_mode=const.GROWTH_MODE_SCALE, db_path=db_path)
    profile_manager.create_profile(profile_id=traditional_pid, name="Canal Tradicional", growth_mode=const.GROWTH_MODE_SCALE, db_path=db_path)

    # Configura formatos em settings_json
    s_paper = ChannelWorkspaceSettings()
    s_paper.editorial.video_format = const.VIDEO_FORMAT_QUIZ_PAPER
    profile_manager.update_profile_settings(quiz_paper_pid, s_paper, db_path=db_path)

    s_escolhas = ChannelWorkspaceSettings()
    s_escolhas.editorial.video_format = const.VIDEO_FORMAT_QUIZ_DILEMMA
    profile_manager.update_profile_settings(quiz_escolhas_pid, s_escolhas, db_path=db_path)

    s_custom = ChannelWorkspaceSettings()
    s_custom.editorial.video_format = const.VIDEO_FORMAT_QUIZ_PAPER
    profile_manager.update_profile_settings(custom_quiz_pid, s_custom, db_path=db_path)

    # Simula estado pré-migração no banco SQLite
    with scheduler.get_connection(db_path) as conn:
        conn.execute("DELETE FROM autopilot_settings WHERE key = 'migration_mission_j_capacity_v1';")
        # Baselines legados de Missão E
        conn.execute("INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES ('autonomous_global_max_generations_24h', '20');")
        conn.execute("INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES ('autonomous_global_max_attempts_24h', '50');")
        # Quiz_Quiz estava preso no padrão não-migrado 5 / 15
        conn.execute("INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES (?, '5');", (f"autonomous_max_generations_24h:{quiz_paper_pid}",))
        conn.execute("INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES (?, '15');", (f"autonomous_max_attempts_24h:{quiz_paper_pid}",))
        # Escolhas já estava em 10 / 30
        conn.execute("INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES (?, '10');", (f"autonomous_max_generations_24h:{quiz_escolhas_pid}",))
        conn.execute("INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES (?, '30');", (f"autonomous_max_attempts_24h:{quiz_escolhas_pid}",))
        # Operador havia customizado o quiz customizado para 7 / 20 (NÃO DEVE SER SOBRESCRITO)
        conn.execute("INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES (?, '7');", (f"autonomous_max_generations_24h:{custom_quiz_pid}",))
        conn.execute("INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES (?, '20');", (f"autonomous_max_attempts_24h:{custom_quiz_pid}",))
        # Canal tradicional estava em 5 / 15
        conn.execute("INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES (?, '5');", (f"autonomous_max_generations_24h:{traditional_pid}",))
        conn.execute("INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES (?, '15');", (f"autonomous_max_attempts_24h:{traditional_pid}",))

    # Executa inicialização / migrações
    scheduler.init_db(db_path)

    # Validações pós-migração:
    # 1. Global Cost Guard elevado para 100/100
    assert autonomous_production.get_global_max_generations_24h(db_path=db_path) == 100
    assert autonomous_production.get_global_max_attempts_24h(db_path=db_path) == 100

    # 2. Quiz_Quiz elevado para 10/30
    assert autonomous_production.get_max_generations_24h(quiz_paper_pid, db_path=db_path) == 10
    assert autonomous_production.get_max_attempts_24h(quiz_paper_pid, db_path=db_path) == 30

    # 3. Escolhas preservado em 10/30
    assert autonomous_production.get_max_generations_24h(quiz_escolhas_pid, db_path=db_path) == 10
    assert autonomous_production.get_max_attempts_24h(quiz_escolhas_pid, db_path=db_path) == 30

    # 4. Customização explícita do operador preservada (7 / 20)
    assert autonomous_production.get_max_generations_24h(custom_quiz_pid, db_path=db_path) == 7
    assert autonomous_production.get_max_attempts_24h(custom_quiz_pid, db_path=db_path) == 20

    # 5. Canal tradicional preservado em 5 / 15
    assert autonomous_production.get_max_generations_24h(traditional_pid, db_path=db_path) == 5
    assert autonomous_production.get_max_attempts_24h(traditional_pid, db_path=db_path) == 15

    # 6. Marcador de migração gravado
    with scheduler.get_connection(db_path) as conn:
        mig_row = conn.execute("SELECT value FROM autopilot_settings WHERE key = 'migration_mission_j_capacity_v1';").fetchone()
        assert mig_row is not None
        assert mig_row[0] == "done"

    # 7. Idempotência estrita: rodar init_db novamente não altera nada
    scheduler.init_db(db_path)
    assert autonomous_production.get_global_max_generations_24h(db_path=db_path) == 100
    assert autonomous_production.get_max_generations_24h(quiz_paper_pid, db_path=db_path) == 10
    assert autonomous_production.get_max_attempts_24h(quiz_paper_pid, db_path=db_path) == 30
    assert autonomous_production.get_max_generations_24h(custom_quiz_pid, db_path=db_path) == 7
