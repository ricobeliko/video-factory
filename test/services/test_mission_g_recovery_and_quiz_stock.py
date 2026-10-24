"""
Testes direcionados para a Missão G:
- Validação de proveniência de Quiz procedural (Copyright Gate PASS com visual_clips=[] e ambient_auto).
- Auto-reconciliação de task_platforms para tarefas legítimas de perfil autônomo.
- Reconhecimento e inclusão no estoque pronto (ready_count) via get_autonomous_ready_stock.
- Recuperação determinística de tarefas interrompidas pós-crash/reboot (sem loop infinito de generating).
- Preservação de bloqueios fail-closed (BGM legado continua FAIL).
- Scheduler plan_schedule agendando tarefas elegíveis e respeitando quotas/autorizações.
"""
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from app.models import const
from app.models.schema import VideoParams
from app.services import (
    autonomous_production,
    copyright_gate,
    operator_console,
    profile_manager,
    quality_score,
    safety_gate,
    scheduler,
)


@pytest.fixture
def env():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_mission_g.db")
        tasks_dir = os.path.join(tmp_dir, "tasks")
        os.makedirs(tasks_dir, exist_ok=True)

        scheduler.init_db(db_path)
        safety_gate.init_safety_db(db_path)
        quality_score.init_quality_db(db_path)
        profile_manager.init_profile_db(db_path)
        operator_console.init_operator_db(db_path)

        # Perfil Quiz (Dose Diária de Escolhas)
        quiz_pid = "profile-4d18bf9a5d94"
        with scheduler.get_connection(db_path) as conn:
            conn.execute(
                """
                INSERT INTO content_profiles (id, name, slug, niche, is_active, created_at, updated_at)
                VALUES (?, 'Dose Diaria de Escolhas', 'dose-diaria-escolhas', 'curiosidades', 1, '2026-10-23T00:00:00Z', '2026-10-23T00:00:00Z');
                """,
                (quiz_pid,),
            )
            conn.execute(
                """
                INSERT INTO publishing_channels (id, profile_id, platform, display_name, is_enabled, auto_publish_authorized, created_at, updated_at)
                VALUES ('channel-quiz-yt', ?, 'youtube', 'Quiz YT', 1, 1, '2026-10-23T00:00:00Z', '2026-10-23T00:00:00Z');
                """,
                (quiz_pid,),
            )
            conn.execute(
                """
                INSERT INTO publishing_channels (id, profile_id, platform, display_name, is_enabled, auto_publish_authorized, created_at, updated_at)
                VALUES ('channel-quiz-tt', ?, 'tiktok', 'Quiz TT', 1, 1, '2026-10-23T00:00:00Z', '2026-10-23T00:00:00Z');
                """,
                (quiz_pid,),
            )

        autonomous_production.set_profile_autonomous_mode_enabled(quiz_pid, True, db_path=db_path)

        with patch.object(operator_console, "require_primary_instance", return_value=None), \
             patch.object(operator_console, "is_primary_instance", return_value=True):
            yield {
                "db_path": db_path,
                "tasks_dir": tasks_dir,
                "quiz_pid": quiz_pid,
            }


def test_1_quiz_procedural_copyright_gate_pass(env):
    """Garante que vídeos procedurais de Quiz com visual_clips=[] e BGM ambient_auto passam no Copyright Gate."""
    db_path = env["db_path"]
    tasks_dir = env["tasks_dir"]
    tid = "task-quiz-pass-01"
    t_dir = os.path.join(tasks_dir, tid)
    os.makedirs(t_dir, exist_ok=True)

    # Cria script.json de quiz procedural com visual_clips vazio
    script_data = {
        "params": {
            "video_format": "quiz_dilemma",
            "narrative_structure": "quiz_dilemma",
            "bgm_type": "ambient_auto",
            "bgm_volume": 0.20,
            "profile_id": env["quiz_pid"],
        },
        "quiz_data": {"format_type": "subjective", "questions": []},
        "asset_provenance": {
            "bgm": {
                "enabled": True,
                "source": "procedural",
                "provenance_status": "SAFE_PROCEDURAL",
            },
            "visual_clips": [],
            "provenance_status": "SAFE_PROCEDURAL",
        },
    }
    with open(os.path.join(t_dir, "script.json"), "w", encoding="utf-8") as f:
        json.dump(script_data, f)

    passed, reason, metrics = copyright_gate.evaluate_copyright_provenance_gate(
        task_id=tid,
        task_base_dir=tasks_dir,
        db_path=db_path,
    )
    assert passed is True
    assert metrics["copyright_provenance_gate"] == "PASS"
    assert metrics["visual_status"] == "PROCEDURAL_QUIZ_CANVAS_VERIFIED"


def test_2_quiz_procedural_with_legacy_bgm_fails(env):
    """Garante que vídeos procedurais com BGM legado continuam reprovados fail-closed."""
    db_path = env["db_path"]
    tasks_dir = env["tasks_dir"]
    tid = "task-quiz-legacy-bgm-02"
    t_dir = os.path.join(tasks_dir, tid)
    os.makedirs(t_dir, exist_ok=True)

    script_data = {
        "params": {
            "video_format": "quiz_dilemma",
            "bgm_type": "random",
            "bgm_volume": 0.20,
        },
        "quiz_data": {"format_type": "subjective"},
        "asset_provenance": {
            "bgm": {
                "enabled": True,
                "source": "legacy_resource_songs",
                "provenance_status": "UNAUDITED_LEGACY",
            },
            "visual_clips": [],
        },
    }
    with open(os.path.join(t_dir, "script.json"), "w", encoding="utf-8") as f:
        json.dump(script_data, f)

    passed, reason, metrics = copyright_gate.evaluate_copyright_provenance_gate(
        task_id=tid,
        task_base_dir=tasks_dir,
        db_path=db_path,
    )
    assert passed is False
    assert metrics["copyright_provenance_gate"] == "FAIL"
    assert "BGM legado" in reason


def test_3_auto_reconcile_and_ready_stock_for_quiz(env):
    """Simula o caso real de PROD: 4 tarefas aprovadas em Safety/Quality com task_platforms vazio

    são auto-reconciliadas e entram no ready_stock (ready_count == 1).
    """
    db_path = env["db_path"]
    tasks_dir = env["tasks_dir"]
    quiz_pid = env["quiz_pid"]
    tid = "28806b52-8861-4307-bb19-d6cdcf8530f7"
    t_dir = os.path.join(tasks_dir, tid)
    os.makedirs(t_dir, exist_ok=True)

    # Cria MP4
    with open(os.path.join(t_dir, "final-1.mp4"), "wb") as f:
        f.write(b"mp4_content_valid_65s")

    # Cria script.json
    script_data = {
        "state": const.TASK_STATE_COMPLETE,
        "duration": 65.0,
        "params": {
            "video_format": "quiz_dilemma",
            "narrative_structure": "quiz_dilemma",
            "bgm_type": "ambient_auto",
            "bgm_volume": 0.20,
            "profile_id": quiz_pid,
        },
        "quiz_data": {"format_type": "subjective"},
        "final_media_quality": {"status": "PASS"},
        "asset_provenance": {
            "bgm": {"enabled": True, "source": "procedural", "provenance_status": "SAFE_PROCEDURAL"},
            "visual_clips": [],
        },
    }
    with open(os.path.join(t_dir, "script.json"), "w", encoding="utf-8") as f:
        json.dump(script_data, f)

    # Registros SQLite
    safety_gate.save_safety_assessment({
        "task_id": tid,
        "safety_status": const.SAFETY_STATUS_PASS,
        "checked_at": "2026-10-23T12:00:00Z",
    }, db_path=db_path)

    profile_manager.save_task_profile(tid, quiz_pid, db_path=db_path)

    with scheduler.get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO content_quality_scores (task_id, topic, quality_score, quality_label, created_at)
            VALUES (?, 'Quiz Dilemma 1', 81.0, 'GOOD', '2026-10-23T12:05:00Z');
            """,
            (tid,),
        )

    # Antes: task_platforms está VAZIO
    tp_before = scheduler.get_task_platforms(tid, db_path=db_path)
    assert tp_before == []

    # get_autonomous_ready_stock deve reconciliar task_platforms e computar ready_count = 1
    stock = autonomous_production.get_autonomous_ready_stock(
        task_base_dir=tasks_dir,
        db_path=db_path,
        profile_id=quiz_pid,
    )
    assert stock["ready_count"] == 1
    assert stock["youtube_ready"][0]["task_id"] == tid

    # Depois: task_platforms foi reconciliado no SQLite
    tp_after = scheduler.get_task_platforms(tid, db_path=db_path)
    assert "youtube" in tp_after


def test_4_crash_recovery_clears_stuck_generating(env):
    """Garante que se o sistema reiniciou enquanto gerava (vídeo ausente e sem worker vivo),

    o Autopilot não fica preso em 'generating', limpa current_task_id e reporta erro de recuperação.
    """
    db_path = env["db_path"]
    tasks_dir = env["tasks_dir"]
    quiz_pid = env["quiz_pid"]

    tid = "task-crashed-mid-render"
    profile_manager.save_task_profile(tid, quiz_pid, db_path=db_path)
    autonomous_production._set_cycle_setting(
        autonomous_production.KEY_AUTONOMOUS_CURRENT_TASK_ID,
        tid,
        profile_id=quiz_pid,
        db_path=db_path,
    )

    # Executa ciclo autônomo sem mocks de worker (worker não está rodando tid)
    res = autonomous_production.run_autonomous_cycle(
        force=True,
        one_shot=True,
        db_path=db_path,
        profile_id=quiz_pid,
        task_base_dir=tasks_dir,
    )

    assert res["status"] == "recovery_error"
    assert res["reason"] == "generation_interrupted"

    # current_task_id deve ter sido limpo
    curr = autonomous_production._get_cycle_setting(
        autonomous_production.KEY_AUTONOMOUS_CURRENT_TASK_ID,
        "",
        profile_id=quiz_pid,
        db_path=db_path,
    )
    assert curr == ""


def test_5_scheduler_plans_and_respects_limits(env):
    """Garante que plan_schedule agenda a tarefa reconciliada do estoque respeitando autorizações e quotas."""
    db_path = env["db_path"]
    tasks_dir = env["tasks_dir"]
    quiz_pid = env["quiz_pid"]

    # Cria tarefa elegível pronta
    tid = "task-to-schedule-05"
    t_dir = os.path.join(tasks_dir, tid)
    os.makedirs(t_dir, exist_ok=True)
    with open(os.path.join(t_dir, "final-1.mp4"), "wb") as f:
        f.write(b"mp4_sample_content")

    script_data = {
        "state": const.TASK_STATE_COMPLETE,
        "duration": 65.0,
        "params": {
            "video_format": "quiz_dilemma",
            "bgm_type": "ambient_auto",
            "bgm_volume": 0.20,
            "profile_id": quiz_pid,
        },
        "quiz_data": {"format_type": "subjective"},
        "asset_provenance": {"visual_clips": [], "bgm": {"enabled": True, "source": "procedural", "provenance_status": "SAFE_PROCEDURAL"}},
    }
    with open(os.path.join(t_dir, "script.json"), "w", encoding="utf-8") as f:
        json.dump(script_data, f)

    safety_gate.save_safety_assessment({"task_id": tid, "safety_status": const.SAFETY_STATUS_PASS}, db_path=db_path)
    profile_manager.save_task_profile(tid, quiz_pid, db_path=db_path)
    scheduler.save_task_platforms(tid, ["youtube"], db_path=db_path)

    with scheduler.get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO content_quality_scores (task_id, topic, quality_score, quality_label, created_at) VALUES (?, 'T', 80.0, 'GOOD', '2026-10-23T12:00:00Z')",
            (tid,),
        )

    task_obj = {
        "task_id": tid,
        "state": const.TASK_STATE_COMPLETE,
        "video_file": os.path.join(t_dir, "final-1.mp4"),
        "profile_id": quiz_pid,
        "planned_platforms": ["youtube"],
    }

    # Ativa scheduler settings
    scheduler.save_settings({
        "scheduler_enabled": "true",
        "auto_publish_enabled": "true",
        "youtube_enabled": "true",
    }, db_path=db_path)

    scheduled = scheduler.plan_schedule([task_obj], db_path=db_path, task_base_dir=tasks_dir)
    assert len(scheduled) == 1
    assert scheduled[0]["task_id"] == tid
    assert scheduled[0]["platform"] == "youtube"

    # Idempotência: rodar novamente não duplica
    scheduled_2 = scheduler.plan_schedule([task_obj], db_path=db_path, task_base_dir=tasks_dir)
    assert len(scheduled_2) == 0
