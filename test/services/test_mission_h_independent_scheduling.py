"""
Testes direcionados para a Missão H:
- Problema 1: Agendamento independente da produção.
  Produção OFF + Agendamento ON + Publicação ON consome e agenda o estoque existente sem disparar nova geração.
- Problema 2: Consistência de autorização da WebUI vs SQLite.
  WebUI reflete estritamente auto_publish_authorized por canal (ex: Quiz_Quiz auto_publish_authorized=0).
  Canal sem autorização permanece estritamente bloqueado (Fail-Closed).
  Alteração legítima de autorização pelo operador persiste corretamente via setter oficial.
- Preservação integral de Safety Gates, limites de capacidade, isolamento por perfil e idempotência.
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
    operator_console,
    profile_manager,
    quality_score,
    safety_gate,
    scheduler,
)
from webui.components import channel_factory


@pytest.fixture
def env():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_mission_h.db")
        tasks_dir = os.path.join(tmp_dir, "tasks")
        os.makedirs(tasks_dir, exist_ok=True)

        scheduler.init_db(db_path)
        safety_gate.init_safety_db(db_path)
        quality_score.init_quality_db(db_path)
        profile_manager.init_profile_db(db_path)
        operator_console.init_operator_db(db_path)

        # 1. Perfil Histórias e Mistério (Produção OFF, Canal YouTube Autorizado = 1)
        hm_pid = "profile-historias-misterio"
        with scheduler.get_connection(db_path) as conn:
            conn.execute(
                """
                INSERT INTO content_profiles (id, name, slug, niche, is_active, created_at, updated_at)
                VALUES (?, 'Dose Diaria de Historias e Misterio', 'historias-misterio', 'mistério', 1, '2026-10-23T00:00:00Z', '2026-10-23T00:00:00Z');
                """,
                (hm_pid,),
            )
            conn.execute(
                """
                INSERT INTO publishing_channels (id, profile_id, platform, display_name, is_enabled, auto_publish_authorized, created_at, updated_at)
                VALUES ('channel-hm-yt', ?, 'youtube', 'Histórias YouTube', 1, 1, '2026-10-23T00:00:00Z', '2026-10-23T00:00:00Z');
                """,
                (hm_pid,),
            )

        # 2. Perfil Quiz_Quiz (Produção ON, Canal YouTube NÃO Autorizado = 0)
        quiz_pid = "profile-45cee883f80a"
        with scheduler.get_connection(db_path) as conn:
            conn.execute(
                """
                INSERT INTO content_profiles (id, name, slug, niche, is_active, created_at, updated_at)
                VALUES (?, 'Quiz_Quiz', 'quiz-quiz', 'quiz', 1, '2026-10-23T00:00:00Z', '2026-10-23T00:00:00Z');
                """,
                (quiz_pid,),
            )
            conn.execute(
                """
                INSERT INTO publishing_channels (id, profile_id, platform, display_name, is_enabled, auto_publish_authorized, created_at, updated_at)
                VALUES ('channel-quiz-yt', ?, 'youtube', 'Quiz YouTube', 1, 0, '2026-10-23T00:00:00Z', '2026-10-23T00:00:00Z');
                """,
                (quiz_pid,),
            )

        # Configurações globais: Scheduler ON, Auto-Publish ON, Dry Run OFF, YouTube ON
        scheduler.set_setting("scheduler_enabled", "true", db_path=db_path)
        scheduler.set_setting("auto_publish_enabled", "true", db_path=db_path)
        scheduler.set_setting("dry_run", "false", db_path=db_path)
        scheduler.set_setting("youtube_enabled", "true", db_path=db_path)

        # Produção OFF para Histórias e Mistério
        autonomous_production.set_profile_autonomous_mode_enabled(hm_pid, False, db_path=db_path)

        # Produção ON para Quiz_Quiz
        autonomous_production.set_profile_autonomous_mode_enabled(quiz_pid, True, db_path=db_path)

        yield {
            "db_path": db_path,
            "tasks_dir": tasks_dir,
            "hm_pid": hm_pid,
            "quiz_pid": quiz_pid,
        }


def _create_approved_task(task_id: str, profile_id: str, tasks_dir: str, db_path: str, format_name: str = "quiz_dilemma"):
    """Cria uma tarefa concluída aprovada nos Safety, Monetization e Copyright Gates."""
    task_folder = os.path.join(tasks_dir, task_id)
    os.makedirs(task_folder, exist_ok=True)
    video_path = os.path.join(task_folder, "final-1.mp4")
    with open(video_path, "wb") as f:
        f.write(b"mock_mp4_bytes")

    params = VideoParams(
        video_subject="Teste Mission H",
        video_script="Roteiro de teste seguro para agendamento.",
        niche="curiosidades",
        video_format=format_name,
        bgm_type="ambient_auto",
    )
    with open(os.path.join(task_folder, "params.json"), "w", encoding="utf-8") as f:
        json.dump(params.model_dump(), f)

    script_data = {
        "state": const.TASK_STATE_COMPLETE,
        "duration": 65.0,
        "params": {
            "video_format": format_name,
            "narrative_structure": format_name,
            "bgm_type": "ambient_auto",
            "bgm_volume": 0.20,
            "profile_id": profile_id,
        },
        "quiz_data": {"format_type": "subjective"},
        "final_media_quality": {"status": "PASS"},
        "asset_provenance": {
            "bgm": {"enabled": True, "source": "procedural", "provenance_status": "SAFE_PROCEDURAL"},
            "visual_clips": [],
            "provenance_status": "SAFE_PROCEDURAL",
        },
    }
    with open(os.path.join(task_folder, "script.json"), "w", encoding="utf-8") as f:
        json.dump(script_data, f)

    meta = {
        "task_id": task_id,
        "profile_id": profile_id,
        "video_format": format_name,
        "video_file": video_path,
        "state": const.TASK_STATE_COMPLETE,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "final_media_quality": {"status": "PASS"},
        "bgm_provenance": "SAFE_NO_BGM",
        "visual_clips": [],
    }
    with open(os.path.join(task_folder, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f)

    now_iso = datetime.now(timezone.utc).isoformat()
    safety_gate.save_safety_assessment({
        "task_id": task_id,
        "safety_status": const.SAFETY_STATUS_PASS,
        "checked_at": now_iso,
    }, db_path=db_path)

    profile_manager.save_task_profile(task_id, profile_id, db_path=db_path)

    with scheduler.get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO content_quality_scores (task_id, topic, quality_score, quality_label, created_at)
            VALUES (?, 'Teste Topic', 85.0, 'GOOD', ?);
            """,
            (task_id, now_iso),
        )

    scheduler.save_task_platforms(task_id, ["youtube"], db_path=db_path)


def test_production_off_scheduling_on_schedules_ready_stock_without_new_generation(env):
    """Problema 1: Produção OFF + Agendamento ON deve agendar o estoque sem gerar novos vídeos."""
    db_path = env["db_path"]
    tasks_dir = env["tasks_dir"]
    hm_pid = env["hm_pid"]

    task_id = "task-hm-stock-1"
    _create_approved_task(task_id, hm_pid, tasks_dir, db_path)

    assert autonomous_production.is_profile_autonomous_mode_enabled(hm_pid, db_path=db_path) is False
    assert scheduler.get_setting("scheduler_enabled", db_path=db_path) == "true"

    with patch.object(operator_console, "require_primary_instance", return_value=None), \
         patch.object(operator_console, "is_primary_instance", return_value=True), \
         patch.object(autonomous_production.webui_task, "submit_generation") as mock_gen:

        res = autonomous_production.run_enabled_profiles_autonomous_cycle(
            db_path=db_path, task_base_dir=tasks_dir
        )

        hm_res = res["results"][hm_pid]
        assert hm_res["status"] == "scheduled"
        assert hm_res["scheduled_items"] == 1
        assert hm_res["task_id"] == task_id

        with scheduler.get_connection(db_path) as conn:
            post = conn.execute("SELECT * FROM scheduled_posts WHERE task_id = ?;", (task_id,)).fetchone()
            assert post is not None
            assert post["channel_id"] == "channel-hm-yt"
            assert post["status"] in ("planned", "scheduled")

        mock_gen.assert_not_called()

        res2 = autonomous_production.run_enabled_profiles_autonomous_cycle(
            db_path=db_path, task_base_dir=tasks_dir
        )
        hm_res2 = res2["results"][hm_pid]
        assert hm_res2["status"] == "production_paused"
        assert hm_res2["ready_stock"] == 1
        mock_gen.assert_not_called()


def test_production_off_scheduling_off_skips_profile(env):
    """Produção OFF + Agendamento OFF deve ignorar o perfil com segurança."""
    db_path = env["db_path"]
    tasks_dir = env["tasks_dir"]
    hm_pid = env["hm_pid"]

    scheduler.set_setting("scheduler_enabled", "false", db_path=db_path)

    task_id = "task-hm-stock-2"
    _create_approved_task(task_id, hm_pid, tasks_dir, db_path)

    with patch.object(operator_console, "require_primary_instance", return_value=None), \
         patch.object(operator_console, "is_primary_instance", return_value=True):
        res = autonomous_production.run_enabled_profiles_autonomous_cycle(
            db_path=db_path, task_base_dir=tasks_dir
        )
        hm_res = res["results"][hm_pid]
        assert hm_res["status"] == "disabled"
        assert hm_res["skipped"] is True

        with scheduler.get_connection(db_path) as conn:
            post = conn.execute("SELECT * FROM scheduled_posts WHERE task_id = ?;", (task_id,)).fetchone()
            assert post is None


def test_quiz_paper_unauthorized_channel_blocked_from_scheduling(env):
    """Problema 2: Canal com auto_publish_authorized = 0 não pode ser agendado automaticamente."""
    db_path = env["db_path"]
    tasks_dir = env["tasks_dir"]
    quiz_pid = env["quiz_pid"]

    task_id = "task-quiz-paper-1"
    _create_approved_task(task_id, quiz_pid, tasks_dir, db_path, format_name="quiz_paper")

    with scheduler.get_connection(db_path) as conn:
        ch = conn.execute("SELECT auto_publish_authorized FROM publishing_channels WHERE id = 'channel-quiz-yt';").fetchone()
        assert int(ch["auto_publish_authorized"]) == 0

    assert scheduler.is_channel_auto_publish_authorized("channel-quiz-yt", db_path=db_path) is False

    with patch.object(operator_console, "require_primary_instance", return_value=None), \
         patch.object(operator_console, "is_primary_instance", return_value=True), \
         patch.object(autonomous_production.webui_task, "submit_generation"):

        res = autonomous_production.run_autonomous_cycle(
            profile_id=quiz_pid,
            channel_id="channel-quiz-yt",
            db_path=db_path,
            task_base_dir=tasks_dir,
        )

        assert res["status"] == "waiting_schedule"
        assert res["scheduled_items"] == 0

        with scheduler.get_connection(db_path) as conn:
            post = conn.execute("SELECT * FROM scheduled_posts WHERE task_id = ?;", (task_id,)).fetchone()
            assert post is None

        with scheduler.get_connection(db_path) as conn:
            ch_after = conn.execute("SELECT auto_publish_authorized FROM publishing_channels WHERE id = 'channel-quiz-yt';").fetchone()
            assert int(ch_after["auto_publish_authorized"]) == 0


def test_webui_channel_factory_reflects_and_persists_authorization(env):
    """Problema 2: WebUI reflete fielmente o status de auto-publicação e persiste alterações legítimas."""
    db_path = env["db_path"]
    quiz_pid = env["quiz_pid"]

    prof = profile_manager.get_profile(quiz_pid, db_path=db_path)
    card_data = channel_factory._get_channel_card_data(prof, db_path=db_path)

    yt_channel = card_data["yt_channel"]
    assert yt_channel["id"] == "channel-quiz-yt"
    assert yt_channel["is_enabled"] == 1
    assert int(yt_channel["auto_publish_authorized"]) == 0

    with patch.object(operator_console, "require_primary_instance", return_value=None), \
         patch.object(operator_console, "is_primary_instance", return_value=True):
        scheduler.set_channel_auto_publish_authorized("channel-quiz-yt", True, db_path=db_path)

    assert scheduler.is_channel_auto_publish_authorized("channel-quiz-yt", db_path=db_path) is True

    card_data_updated = channel_factory._get_channel_card_data(prof, db_path=db_path)
    assert int(card_data_updated["yt_channel"]["auto_publish_authorized"]) == 1

    with patch.object(operator_console, "require_primary_instance", return_value=None), \
         patch.object(operator_console, "is_primary_instance", return_value=True):
        scheduler.set_channel_auto_publish_authorized("channel-quiz-yt", False, db_path=db_path)

    assert scheduler.is_channel_auto_publish_authorized("channel-quiz-yt", db_path=db_path) is False
    card_data_revoked = channel_factory._get_channel_card_data(prof, db_path=db_path)
    assert int(card_data_revoked["yt_channel"]["auto_publish_authorized"]) == 0


def test_scheduler_cycle_respects_channel_authorization(env):
    """Scheduler cycle de publicação não despacha post de canal com auto_publish_authorized = 0."""
    db_path = env["db_path"]

    now_iso = scheduler._to_iso(datetime.now(timezone.utc))
    with scheduler.get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO scheduled_posts (task_id, profile_id, platform, channel_id, scheduled_at, status, created_at)
            VALUES ('task-unauth-1', 'profile-45cee883f80a', 'youtube', 'channel-quiz-yt', ?, 'scheduled', ?);
            """,
            (now_iso, now_iso),
        )

    with patch.object(operator_console, "require_primary_instance", return_value=None), \
         patch.object(operator_console, "is_primary_instance", return_value=True):
        cycle_res = scheduler.run_scheduler_cycle(db_path=db_path)
        assert cycle_res.get("status") in ("skipped", "idle")
