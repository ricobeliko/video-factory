"""V12-F.5: Targeted tests for Multi-Channel Capacity and True Multi-Profile Autonomous Worker.

Requirements validated:
1. Default ON + Secondary ON: worker processes both independently of UI selection.
2. Secondary OFF: worker skips execution for it.
3. Profile cycle failure: failure in Profile A does not abort Profile B.
4. Per-profile ready stock: Profile A and B have isolated targets without cross-contamination.
5. Per-profile limits: attempts and approved generation limits isolated per profile.
6. Global Cost Guard: blocks new generation when aggregate ceiling is reached.
7. Global Cost Guard: does not block recovery, scheduling or publication of existing videos.
8. Backward compatibility: default profile preserves legacy configs and fallbacks.
9. TikTok remains strictly OFF: destination eligibility check rejects TikTok, no posts created.
10. State pointers and messages remain isolated: current_task, waiting_task, state per profile.
"""
import os
import socket
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.models import const
from app.services import (
    autonomous_production as autonomous,
    operator_console as console,
    profile_manager,
    quality_score,
    safety_gate,
    scheduler,
    state as sm,
)


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """Cria ambiente SQLite temporário e isolado para testes sem rede ou publicação real."""
    monkeypatch.setattr(
        socket.socket,
        "connect",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("Real network connection forbidden")),
    )
    db = str(tmp_path / "test_capacity.db")
    video_dir = tmp_path / "videos"
    video_dir.mkdir(parents=True, exist_ok=True)

    console.init_operator_db(db)
    scheduler.init_db(db)
    safety_gate.init_safety_db(db)
    quality_score.init_quality_db(db)
    profile_manager.ensure_default_profile(db)
    second_info = profile_manager.ensure_second_channel_profile(db)
    second_info["profile_id"] = second_info["profile"]["id"]
    second_info["channel_id"] = second_info["channel"]["id"]

    return db, video_dir, second_info


def _create_mock_video_task(task_id: str, profile_id: str, topic: str, video_dir, db_path: str, quality_val: float = 85.0):
    """Auxiliar para criar tarefa simulada com arquivo de vídeo no disco e gates aprovados."""
    task_folder = video_dir / task_id
    task_folder.mkdir(parents=True, exist_ok=True)
    video_path = task_folder / "final-1.mp4"
    video_path.write_bytes(b"mock_video_bytes_content")

    sm.state.update_task(
        task_id,
        state=const.TASK_STATE_COMPLETE,
        video_file=str(video_path),
        video_subject=topic,
        topic=topic,
        profile_id=profile_id,
        planned_platforms=["youtube"],
    )
    scheduler.save_task_platforms(task_id, ["youtube"], db_path)
    profile_manager.save_task_profile(task_id, profile_id, db_path)

    with scheduler.get_connection(db_path) as conn:
        now_iso = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT OR REPLACE INTO monetization_safety (
                task_id, topic, preset, narrative_structure, safety_status, checked_at
            ) VALUES (?, ?, ?, ?, 'PASS', ?);
            """,
            (task_id, topic, "youtube_shorts_original", "problem_solution", now_iso),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO content_quality_scores (
                task_id, topic, quality_score, quality_label, created_at
            ) VALUES (?, ?, ?, 'STRONG', ?);
            """,
            (task_id, topic, quality_val, now_iso),
        )


def test_1_multi_profile_worker_independent_of_ui_selection(isolated_env):
    """1. Default ON + Secondary ON: worker processa ambos independentemente da seleção na UI."""
    db, video_dir, second_info = isolated_env
    sec_id = second_info["profile_id"]

    # Ativa autonomous para ambos os perfis
    autonomous.set_profile_autonomous_mode_enabled("default", True, db_path=db)
    autonomous.set_profile_autonomous_mode_enabled(sec_id, True, db_path=db)

    # Fornece estoque pronto suficiente para ambos para teste de ciclo puro sem rede
    autonomous.set_target_ready_stock(3, profile_id="default", db_path=db)
    autonomous.set_target_ready_stock(3, profile_id=sec_id, db_path=db)
    _create_mock_video_task("def_vid_1", "default", "Topic 1", video_dir, db)
    _create_mock_video_task("def_vid_2", "default", "Topic 2", video_dir, db)
    _create_mock_video_task("def_vid_3", "default", "Topic 3", video_dir, db)
    _create_mock_video_task("sec_vid_1", sec_id, "Sec Topic 1", video_dir, db)
    _create_mock_video_task("sec_vid_2", sec_id, "Sec Topic 2", video_dir, db)
    _create_mock_video_task("sec_vid_3", sec_id, "Sec Topic 3", video_dir, db)

    # Simula UI selecionada em SECONDARY
    profile_manager.set_active_profile_id(sec_id, db_path=db)
    assert profile_manager.get_active_profile_id(db_path=db) == sec_id

    # Background worker executa ciclo
    res1 = autonomous.run_enabled_profiles_autonomous_cycle(db_path=db, task_base_dir=str(video_dir))
    assert res1["status"] == "completed"
    assert "default" in res1["results"]
    assert sec_id in res1["results"]
    assert res1["results"]["default"].get("status") in ("idle", "busy", "scheduled", "waiting_schedule")
    assert res1["results"][sec_id].get("status") in ("idle", "busy", "scheduled", "waiting_schedule")

    # Agora simula UI selecionada em DEFAULT
    profile_manager.set_active_profile_id("default", db_path=db)
    assert profile_manager.get_active_profile_id(db_path=db) == "default"

    res2 = autonomous.run_enabled_profiles_autonomous_cycle(db_path=db, task_base_dir=str(video_dir))
    assert res2["status"] == "completed"
    assert "default" in res2["results"]
    assert sec_id in res2["results"]


def test_2_secondary_disabled_is_skipped(isolated_env):
    """2. Secondary OFF: worker não executa ciclo de geração para ele."""
    db, video_dir, second_info = isolated_env
    sec_id = second_info["profile_id"]

    autonomous.set_profile_autonomous_mode_enabled("default", True, db_path=db)
    autonomous.set_profile_autonomous_mode_enabled(sec_id, False, db_path=db)

    # Fornece estoque para default
    autonomous.set_target_ready_stock(3, profile_id="default", db_path=db)
    _create_mock_video_task("def_vid_skip_1", "default", "Topic Skip 1", video_dir, db)
    _create_mock_video_task("def_vid_skip_2", "default", "Topic Skip 2", video_dir, db)
    _create_mock_video_task("def_vid_skip_3", "default", "Topic Skip 3", video_dir, db)

    res = autonomous.run_enabled_profiles_autonomous_cycle(db_path=db, task_base_dir=str(video_dir))
    assert res["status"] == "completed"
    assert "default" in res["results"]
    assert res["results"]["default"].get("status") in ("idle", "busy", "scheduled", "waiting_schedule")
    assert sec_id in res["results"]
    assert res["results"][sec_id].get("status") == "disabled"
    assert res["results"][sec_id].get("skipped") is True


def test_3_profile_failure_isolated(isolated_env, monkeypatch):
    """3. Falha no ciclo do profile A: profile B ainda é processado com sucesso."""
    db, video_dir, second_info = isolated_env
    sec_id = second_info["profile_id"]

    autonomous.set_profile_autonomous_mode_enabled("default", True, db_path=db)
    autonomous.set_profile_autonomous_mode_enabled(sec_id, True, db_path=db)

    # Fornece estoque para secondary
    autonomous.set_target_ready_stock(3, profile_id=sec_id, db_path=db)
    _create_mock_video_task("sec_fail_1", sec_id, "Sec Fail Topic 1", video_dir, db)
    _create_mock_video_task("sec_fail_2", sec_id, "Sec Fail Topic 2", video_dir, db)
    _create_mock_video_task("sec_fail_3", sec_id, "Sec Fail Topic 3", video_dir, db)

    original_run = autonomous.run_autonomous_cycle

    def failing_run(*args, **kwargs):
        p_id = kwargs.get("profile_id")
        if p_id == "default":
            raise RuntimeError("Simulated crash in default profile")
        return original_run(*args, **kwargs)

    monkeypatch.setattr(autonomous, "run_autonomous_cycle", failing_run)

    res = autonomous.run_enabled_profiles_autonomous_cycle(db_path=db, task_base_dir=str(video_dir))
    assert res["status"] == "completed"
    # default falhou isoladamente
    assert res["results"]["default"]["status"] == "error"
    assert "Simulated crash" in res["results"]["default"]["error"]
    # secondary foi processado sem ser abortado
    assert res["results"][sec_id]["status"] in ("idle", "busy", "scheduled", "waiting_schedule")


def test_4_ready_target_isolated(isolated_env):
    """4. Ready target isolado: Profile A pode ter target 3 e Profile B target 5 sem contaminação."""
    db, video_dir, second_info = isolated_env
    sec_id = second_info["profile_id"]

    autonomous.set_target_ready_stock(3, profile_id="default", db_path=db)
    autonomous.set_target_ready_stock(5, profile_id=sec_id, db_path=db)

    assert autonomous.get_target_ready_stock(profile_id="default", db_path=db) == 3
    assert autonomous.get_target_ready_stock(profile_id=sec_id, db_path=db) == 5

    stock_def = autonomous.get_autonomous_ready_stock(profile_id="default", db_path=db)
    stock_sec = autonomous.get_autonomous_ready_stock(profile_id=sec_id, db_path=db)

    assert stock_def["target_stock"] == 3
    assert stock_sec["target_stock"] == 5

    # Clamping entre 3 e 6
    autonomous.set_target_ready_stock(1, profile_id=sec_id, db_path=db)
    assert autonomous.get_target_ready_stock(profile_id=sec_id, db_path=db) == 3
    autonomous.set_target_ready_stock(10, profile_id=sec_id, db_path=db)
    assert autonomous.get_target_ready_stock(profile_id=sec_id, db_path=db) == 6


def test_5_limits_per_profile_isolated(isolated_env):
    """5. Limite de attempts/approved isolado por perfil e compatível com Growth Mode."""
    db, video_dir, second_info = isolated_env
    sec_id = second_info["profile_id"]

    # Verifica defaults automáticos pelo Growth Mode (sec_id está em WARMUP)
    assert autonomous.get_max_generations_24h(profile_id=sec_id, db_path=db) == 2
    assert autonomous.get_max_attempts_24h(profile_id=sec_id, db_path=db) == 8

    # Overrides explícitos por perfil
    autonomous.set_max_generations_24h(4, profile_id=sec_id, db_path=db)
    autonomous.set_max_attempts_24h(12, profile_id=sec_id, db_path=db)

    autonomous.set_max_generations_24h(5, profile_id="default", db_path=db)
    autonomous.set_max_attempts_24h(15, profile_id="default", db_path=db)

    assert autonomous.get_max_generations_24h(profile_id=sec_id, db_path=db) == 4
    assert autonomous.get_max_attempts_24h(profile_id=sec_id, db_path=db) == 12
    assert autonomous.get_max_generations_24h(profile_id="default", db_path=db) == 5
    assert autonomous.get_max_attempts_24h(profile_id="default", db_path=db) == 15


def test_6_global_cost_guard_blocks_new_generation(isolated_env):
    """6. Global aggregate guard bloqueia NOVA geração ao atingir teto."""
    db, video_dir, second_info = isolated_env
    sec_id = second_info["profile_id"]

    autonomous.set_profile_autonomous_mode_enabled(sec_id, True, db_path=db)
    # Define teto global de tentativas para 2
    autonomous.set_global_max_attempts_24h(2, db_path=db)
    assert autonomous.get_global_max_attempts_24h(db_path=db) == 2

    # Registra 2 tentativas globais
    console.log_operational_event(
        component="autonomous_production",
        severity=console.SEVERITY_INFO,
        event_type="generation_started",
        message="Tentativa 1",
        task_id="task_prior_1",
        db_path=db,
    )
    console.log_operational_event(
        component="autonomous_production",
        severity=console.SEVERITY_INFO,
        event_type="generation_started",
        message="Tentativa 2",
        task_id="task_prior_2",
        db_path=db,
    )

    assert autonomous.count_all_profiles_attempts_24h(db_path=db) == 2
    guard = autonomous.get_global_cost_guard_status(db_path=db)
    assert guard["is_limit_reached"] is True

    # Tentativa de executar ciclo para sec_id (estoque 0, meta 3) deve ser barrada pelo Global Guard
    res = autonomous.run_autonomous_cycle(profile_id=sec_id, db_path=db, force=True)
    assert res["status"] == "blocked"
    assert res["reason"] == "global_attempt_limit_reached"


def test_7_global_guard_does_not_block_recovery_or_scheduling(isolated_env):
    """7. Global guard não impede recovery/scheduling/publicação de asset já existente."""
    db, video_dir, second_info = isolated_env
    sec_id = second_info["profile_id"]

    autonomous.set_profile_autonomous_mode_enabled(sec_id, True, db_path=db)
    # Teto global de gerações aprovadas atingido (1/1)
    autonomous.set_global_max_generations_24h(1, db_path=db)
    console.log_operational_event(
        component="autonomous_production",
        severity=console.SEVERITY_INFO,
        event_type="generation_approved",
        message="Aprovado 1",
        task_id="task_past_approved",
        db_path=db,
    )
    assert autonomous.count_all_profiles_generations_24h(db_path=db) == 1

    # Cria tarefa prévia com vídeo já aprovado aguardando scheduler
    _create_mock_video_task("task_ready_1", sec_id, "Mistério das Profundezas", video_dir, db)

    # Executa ciclo: não deve falhar com blocked, e sim processar/agendar o vídeo pronto
    res = autonomous.run_autonomous_cycle(profile_id=sec_id, db_path=db, force=True, task_base_dir=str(video_dir))
    assert res["status"] in ("scheduled", "waiting_schedule", "idle")
    assert res.get("reason") != "global_generation_limit_reached"


def test_8_default_backward_compatibility(isolated_env):
    """8. Default mantém backward compatibility com chaves legadas e chamadas sem profile_id."""
    db, video_dir, second_info = isolated_env

    # Configura chaves legadas
    autonomous.set_autonomous_setting(autonomous.KEY_AUTONOMOUS_TARGET_STOCK, "4", db_path=db)
    autonomous.set_autonomous_setting(autonomous.KEY_AUTONOMOUS_MAX_24H, "5", db_path=db)
    autonomous.set_autonomous_setting(autonomous.KEY_AUTONOMOUS_MAX_ATTEMPTS_24H, "15", db_path=db)

    # get_target_ready_stock com profile_id=None ou "default" respeita chave legada
    assert autonomous.get_target_ready_stock(profile_id=None, db_path=db) == 4
    assert autonomous.get_target_ready_stock(profile_id="default", db_path=db) == 4

    assert autonomous.get_max_generations_24h(profile_id=None, db_path=db) == 5
    assert autonomous.get_max_generations_24h(profile_id="default", db_path=db) == 5

    assert autonomous.get_max_attempts_24h(profile_id=None, db_path=db) == 15
    assert autonomous.get_max_attempts_24h(profile_id="default", db_path=db) == 15


def test_9_tiktok_remains_strictly_off_and_destination_eligibility(isolated_env):
    """9. Nenhuma criação/publicação TikTok; elegibilidade multi-destino preparada."""
    db, video_dir, second_info = isolated_env

    # Arquitetura de elegibilidade de destino
    yt_check = autonomous.check_asset_eligibility_for_destination({}, "youtube", db_path=db)
    assert yt_check["eligible"] is True
    assert yt_check["enabled"] is True

    tt_check = autonomous.check_asset_eligibility_for_destination({}, "tiktok", db_path=db)
    assert tt_check["eligible"] is False
    assert tt_check["enabled"] is False

    # Nenhum post de TikTok existente
    with scheduler.get_connection(db) as conn:
        tt_posts = conn.execute("SELECT count(*) FROM scheduled_posts WHERE platform='tiktok'").fetchone()[0]
        assert tt_posts == 0
        tt_events = conn.execute("SELECT count(*) FROM publication_events WHERE platform='tiktok'").fetchone()[0]
        assert tt_events == 0


def test_10_state_pointers_and_messages_isolated(isolated_env):
    """10. current/waiting/state permanecem 100% isolados entre os perfis."""
    db, video_dir, second_info = isolated_env
    sec_id = second_info["profile_id"]

    autonomous.set_profile_autonomous_mode_enabled("default", True, db_path=db)
    autonomous.set_profile_autonomous_mode_enabled(sec_id, True, db_path=db)

    autonomous._set_cycle_setting(autonomous.KEY_AUTONOMOUS_CURRENT_TASK_ID, "task_def_123", profile_id="default", db_path=db)
    autonomous._set_cycle_setting(autonomous.KEY_AUTONOMOUS_CURRENT_TASK_ID, "task_sec_456", profile_id=sec_id, db_path=db)

    autonomous._set_cycle_setting(autonomous.KEY_AUTONOMOUS_STATE, "generating", profile_id="default", db_path=db)
    autonomous._set_cycle_setting(autonomous.KEY_AUTONOMOUS_STATE, "idle", profile_id=sec_id, db_path=db)

    autonomous._set_cycle_setting(autonomous.KEY_AUTONOMOUS_MESSAGE, "Msg default", profile_id="default", db_path=db)
    autonomous._set_cycle_setting(autonomous.KEY_AUTONOMOUS_MESSAGE, "Msg secondary", profile_id=sec_id, db_path=db)

    assert autonomous._get_cycle_setting(autonomous.KEY_AUTONOMOUS_CURRENT_TASK_ID, profile_id="default", db_path=db) == "task_def_123"
    assert autonomous._get_cycle_setting(autonomous.KEY_AUTONOMOUS_CURRENT_TASK_ID, profile_id=sec_id, db_path=db) == "task_sec_456"

    status_def = autonomous.get_autonomous_status(profile_id="default", db_path=db)
    status_sec = autonomous.get_autonomous_status(profile_id=sec_id, db_path=db)

    assert status_def["state"] == "generating"
    assert status_sec["state"] == "idle"
    assert status_def["message"] == "Msg default"
    assert status_sec["message"] == "Msg secondary"
