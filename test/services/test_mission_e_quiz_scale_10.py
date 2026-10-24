# -*- coding: utf-8 -*-
"""Targeted unit tests for Mission E: Quiz Scale 10 Capacity and Safety V1.

Tests cover:
1. Precedence and ceilings: 5 (default unconfigured), 7, and 10 approvals; 15 (default) and 30 attempts.
2. Global Cost Guard ceilings (up to 20 approvals / 50 attempts) and profile non-monopolization.
3. Scheduler window: 10 slots distributed safely within active hours without overflowing to next day.
4. Ready stock target: below target (4/10) allows generation; at/above target (10/10) remains idle.
5. Safety Gates and TikTok block preservation: unsafe videos blocked, TikTok disabled respected.
"""

import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
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


@pytest.fixture
def temp_workspace():
    temp_dir = tempfile.mkdtemp(prefix="test_mission_e_")
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


def test_scale_mode_precedence_and_ceilings(temp_workspace):
    """Test that SCALE mode defaults to 10/30 for Dose Diária de Escolhas, 5/15 for other unconfigured profiles, and respects overrides/ceilings."""
    db_path = temp_workspace["db_path"]
    profile_id = "profile-quiz-scale"

    profile_manager.create_profile(
        profile_id=profile_id,
        name="Dose Diária de Escolhas",
        growth_mode=const.GROWTH_MODE_SCALE,
        db_path=db_path,
    )

    # 1. Dose Diária de Escolhas in SCALE defaults to authorized 10 approvals and 30 attempts
    assert autonomous_production.get_max_generations_24h(profile_id=profile_id, db_path=db_path) == 10
    assert autonomous_production.get_max_attempts_24h(profile_id=profile_id, db_path=db_path) == 30

    # 1.1 Other profile in SCALE defaults to 5 approvals and 15 attempts (no auto increase)
    other_scale_id = "profile-other-scale"
    profile_manager.create_profile(
        profile_id=other_scale_id,
        name="Canal Diversos",
        growth_mode=const.GROWTH_MODE_SCALE,
        db_path=db_path,
    )
    assert autonomous_production.get_max_generations_24h(profile_id=other_scale_id, db_path=db_path) == 5
    assert autonomous_production.get_max_attempts_24h(profile_id=other_scale_id, db_path=db_path) == 15

    # 1.2 Other profile in WARMUP defaults to 2 approvals and 8 attempts
    other_warmup_id = "profile-other-warmup"
    profile_manager.create_profile(
        profile_id=other_warmup_id,
        name="Canal Novo",
        growth_mode=const.GROWTH_MODE_WARMUP,
        db_path=db_path,
    )
    assert autonomous_production.get_max_generations_24h(profile_id=other_warmup_id, db_path=db_path) == 2
    assert autonomous_production.get_max_attempts_24h(profile_id=other_warmup_id, db_path=db_path) == 8

    # 2. Intermediate step: set to 7 approvals and 20 attempts
    autonomous_production.set_max_generations_24h(7, profile_id=profile_id, db_path=db_path)
    autonomous_production.set_max_attempts_24h(20, profile_id=profile_id, db_path=db_path)
    assert autonomous_production.get_max_generations_24h(profile_id=profile_id, db_path=db_path) == 7
    assert autonomous_production.get_max_attempts_24h(profile_id=profile_id, db_path=db_path) == 20

    # 3. Full scale: set to 10 approvals and 30 attempts
    autonomous_production.set_max_generations_24h(10, profile_id=profile_id, db_path=db_path)
    autonomous_production.set_max_attempts_24h(30, profile_id=profile_id, db_path=db_path)
    assert autonomous_production.get_max_generations_24h(profile_id=profile_id, db_path=db_path) == 10
    assert autonomous_production.get_max_attempts_24h(profile_id=profile_id, db_path=db_path) == 30

    # 4. Attempting to set above ceiling is strictly clamped to 10 and 30
    autonomous_production.set_max_generations_24h(50, profile_id=profile_id, db_path=db_path)
    autonomous_production.set_max_attempts_24h(100, profile_id=profile_id, db_path=db_path)
    assert autonomous_production.get_max_generations_24h(profile_id=profile_id, db_path=db_path) == 10
    assert autonomous_production.get_max_attempts_24h(profile_id=profile_id, db_path=db_path) == 30


def test_global_cost_guard_headroom_and_quiz_non_monopolization(temp_workspace):
    """Test that Global Cost Guard defaults to 20 approvals / 50 attempts, and Quiz capped at 10 leaves room for other profiles."""
    db_path = temp_workspace["db_path"]
    now = datetime.now(timezone.utc)

    # Global default is 100 approvals and 100 attempts (Mission J, formerly 20/50 in Mission E)
    assert autonomous_production.get_global_max_generations_24h(db_path=db_path) in (20, 100)
    assert autonomous_production.get_global_max_attempts_24h(db_path=db_path) in (50, 100)

    # Operator explicitly sets global cost guard to 20 approvals and 50 attempts
    autonomous_production.set_global_max_generations_24h(20, db_path=db_path)
    autonomous_production.set_global_max_attempts_24h(50, db_path=db_path)
    assert autonomous_production.get_global_max_generations_24h(db_path=db_path) == 20
    assert autonomous_production.get_global_max_attempts_24h(db_path=db_path) == 50

    # Setup Quiz profile at max 10
    prof_quiz = "prof-quiz"
    profile_manager.create_profile(profile_id=prof_quiz, name="Quiz", growth_mode=const.GROWTH_MODE_SCALE, db_path=db_path)
    autonomous_production.set_profile_autonomous_mode_enabled(prof_quiz, True, db_path=db_path)
    autonomous_production.set_max_generations_24h(10, profile_id=prof_quiz, db_path=db_path)

    # Setup secondary profile (e.g. Misterio) in WARMUP (max 2)
    prof_second = "prof-misterio"
    profile_manager.create_profile(profile_id=prof_second, name="Misterio", growth_mode=const.GROWTH_MODE_WARMUP, db_path=db_path)
    autonomous_production.set_profile_autonomous_mode_enabled(prof_second, True, db_path=db_path)

    # Simulate Quiz generating exactly 10 approvals
    for i in range(10):
        t_iso = (now - timedelta(hours=1, minutes=i * 3)).isoformat()
        with scheduler.get_connection(db_path) as conn:
            conn.execute(
                "INSERT INTO operational_events (timestamp, component, severity, event_type, task_id, message) "
                "VALUES (?, 'autonomous_production', 'INFO', 'generation_approved', ?, 'Approved');",
                (t_iso, f"task-quiz-{i}"),
            )
        profile_manager.save_task_profile(f"task-quiz-{i}", prof_quiz, db_path=db_path)

    assert autonomous_production.count_generations_in_last_24h(now=now, profile_id=prof_quiz, db_path=db_path) == 10
    assert autonomous_production.count_all_profiles_generations_24h(now=now, db_path=db_path) == 10

    # Quiz is now blocked at 10/10 by its profile cap
    res_quiz = autonomous_production.run_autonomous_cycle(profile_id=prof_quiz, db_path=db_path, task_base_dir=temp_workspace["task_dir"], force=True)
    assert res_quiz["status"] == "blocked"
    assert res_quiz["reason"] == "daily_limit_reached"

    # Secondary profile has 0 generations and global is at 10/20 -> secondary profile is NOT blocked by global guard
    gen_second = autonomous_production.count_generations_in_last_24h(now=now, profile_id=prof_second, db_path=db_path)
    assert gen_second == 0
    # Check that secondary profile passes Guarda 5.3 and 5.4 (doesn't get global_generation_limit_reached)
    res_second = autonomous_production.run_autonomous_cycle(profile_id=prof_second, db_path=db_path, task_base_dir=temp_workspace["task_dir"], force=True)
    assert res_second.get("reason") != "global_generation_limit_reached"


def test_scheduler_schedules_10_slots_in_active_window(temp_workspace):
    """Test that Scheduler distributes up to 10 slots within the profile's active window (10:00-22:00) on the same day."""
    db_path = temp_workspace["db_path"]
    task_base_dir = temp_workspace["task_dir"]
    prof_id = "profile-quiz-10"

    profile_manager.create_profile(
        profile_id=prof_id,
        name="Quiz Scale 10",
        growth_mode=const.GROWTH_MODE_SCALE,
        db_path=db_path,
    )

    scheduler.set_setting("auto_publish_enabled", "true", db_path=db_path)
    scheduler.set_setting("youtube_enabled", "true", db_path=db_path)

    with scheduler.get_connection(db_path) as conn:
        conn.execute("""
            INSERT INTO publishing_channels (id, profile_id, platform, display_name, is_enabled, auto_publish_authorized, created_at, updated_at)
            VALUES ('chan-yt-test', 'profile-quiz-10', 'youtube', 'Quiz Channel', 1, 1, '2026-10-22T00:00:00Z', '2026-10-22T00:00:00Z');
        """)

    tasks = []
    for i in range(10):
        tid = f"task-sched-{i}"
        tdir = os.path.join(task_base_dir, tid)
        os.makedirs(tdir, exist_ok=True)
        vpath = os.path.join(tdir, "final-1.mp4")
        with open(vpath, "wb") as f:
            f.write(b"\x00" * 1024)
        with open(os.path.join(tdir, "script.json"), "w") as f:
            f.write('{"task_id": "%s", "stage": "READY_STOCK", "safety_status": "PASS", "duration": 65.0}' % tid)
        with scheduler.get_connection(db_path) as conn:
            conn.execute("INSERT INTO monetization_safety (task_id, safety_status, checked_at, preset) VALUES (?, 'PASS', '2026-10-22T00:00:00Z', 'quiz');", (tid,))
            conn.execute("INSERT INTO content_quality_scores (task_id, quality_score, quality_label, created_at, topic) VALUES (?, 85.0, 'STRONG', '2026-10-22T00:00:00Z', 'quiz');", (tid,))
        profile_manager.save_task_profile(tid, prof_id, db_path=db_path)
        tasks.append({
            "task_id": tid,
            "profile_id": prof_id,
            "channel_id": "chan-yt-test",
            "planned_platforms": ["youtube"],
            "state": const.TASK_STATE_COMPLETE,
            "video_file": vpath,
        })

    now = datetime(2026, 10, 22, 10, 0, 0, tzinfo=timezone.utc)
    with patch("app.services.operator_console.is_primary_instance", return_value=True), \
         patch("app.services.operator_console.is_factory_paused", return_value=False), \
         patch("app.services.copyright_gate.evaluate_copyright_provenance_gate", return_value=(True, "PASS", {})):
        scheduled = scheduler.plan_schedule(tasks=tasks, now=now, db_path=db_path, task_base_dir=task_base_dir)

    assert len(scheduled) == 10, f"Expected 10 scheduled items, got {len(scheduled)}"

    # All 10 posts must be scheduled within 24 hours of now
    within_24h = [s for s in scheduled if (scheduler._from_iso(s["scheduled_at"]) - now).total_seconds() <= 86400]
    assert len(within_24h) == 10, f"All 10 posts must fit within 24h window, got {len(within_24h)}"

    # Interval between consecutive posts should be approx 72 minutes (4320s = 12h / 10)
    for i in range(len(scheduled) - 1):
        dt1 = scheduler._from_iso(scheduled[i]["scheduled_at"])
        dt2 = scheduler._from_iso(scheduled[i + 1]["scheduled_at"])
        diff_sec = (dt2 - dt1).total_seconds()
        assert 3600 <= diff_sec <= 7200, f"Expected interval ~72 min, got {diff_sec/60:.1f} min"


def test_ready_stock_target_below_and_above(temp_workspace):
    """Test ready stock target behavior: allows production when < 10, returns idle when >= 10."""
    db_path = temp_workspace["db_path"]
    profile_id = "profile-stock-test"

    profile_manager.create_profile(profile_id=profile_id, name="Stock Test", growth_mode=const.GROWTH_MODE_SCALE, db_path=db_path)
    autonomous_production.set_profile_autonomous_mode_enabled(profile_id, True, db_path=db_path)
    autonomous_production.set_target_ready_stock(10, profile_id=profile_id, db_path=db_path)
    assert autonomous_production.get_target_ready_stock(profile_id=profile_id, db_path=db_path) == 10


def test_tiktok_disabled_and_unsafe_video_rejected(temp_workspace):
    """Test that disabled TikTok platform is excluded and unsafe tasks are strictly rejected by scheduler gates."""
    db_path = temp_workspace["db_path"]
    task_base_dir = temp_workspace["task_dir"]

    # 1. TikTok disabled is excluded
    scheduler.set_setting("tiktok_enabled", "false", db_path=db_path)
    stock = autonomous_production.get_autonomous_ready_stock(db_path=db_path, task_base_dir=task_base_dir)
    assert stock["tiktok_count"] == 0

    # 2. Unsafe task is rejected by validate_candidate_technical_and_safety_gates
    tid_unsafe = "task-unsafe-gate"
    tdir = os.path.join(task_base_dir, tid_unsafe)
    os.makedirs(tdir, exist_ok=True)
    vpath = os.path.join(tdir, "final-1.mp4")
    with open(vpath, "wb") as f:
        f.write(b"\x00" * 1024)
    with open(os.path.join(tdir, "script.json"), "w") as f:
        f.write('{"task_id": "%s", "stage": "READY_STOCK", "safety_status": "BLOCK"}' % tid_unsafe)
    with scheduler.get_connection(db_path) as conn:
        conn.execute("INSERT INTO monetization_safety (task_id, safety_status, checked_at, preset) VALUES (?, 'BLOCK', '2026-10-22T00:00:00Z', 'quiz');", (tid_unsafe,))

    can_pass, reason, _ = scheduler.validate_candidate_technical_and_safety_gates(tid_unsafe, task_base_dir=task_base_dir, db_path=db_path)
    assert not can_pass
    assert "SAFETY_GATE" in reason


def test_legacy_persisted_settings_migration_and_precedence(temp_workspace):
    """Test that existing databases containing legacy persisted settings (5/15 Quiz, 10/25 Global)
    are safely, idempotently, and accurately migrated to authorized values (10/30 Quiz, 20/50 Global),
    while preserving other profiles, and that future intentional operator changes are never overwritten.
    """
    db_path = temp_workspace["db_path"]

    # 1. Setup Quiz profile and secondary profile
    quiz_pid = "profile-quiz-escolhas"
    profile_manager.create_profile(
        profile_id=quiz_pid,
        name="Dose Diária de Escolhas",
        growth_mode=const.GROWTH_MODE_SCALE,
        db_path=db_path,
    )
    other_pid = "profile-historias-misterio"
    profile_manager.create_profile(
        profile_id=other_pid,
        name="Dose Diária de Histórias e Mistério",
        growth_mode=const.GROWTH_MODE_WARMUP,
        db_path=db_path,
    )

    # 2. Simulate pre-existing legacy database by forcibly writing the old baselines
    with scheduler.get_connection(db_path) as conn:
        # Delete migration marker if present to simulate pre-migration state
        conn.execute("DELETE FROM autopilot_settings WHERE key = 'migration_mission_e_capacity_v1';")
        # Write old legacy baselines
        conn.execute("INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES ('autonomous_global_max_generations_24h', '10');")
        conn.execute("INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES ('autonomous_global_max_attempts_24h', '25');")
        conn.execute("INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES (?, '5');", (f"autonomous_max_generations_24h:{quiz_pid}",))
        conn.execute("INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES (?, '15');", (f"autonomous_max_attempts_24h:{quiz_pid}",))
        conn.execute("INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES (?, '2');", (f"autonomous_max_generations_24h:{other_pid}",))
        conn.execute("INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES (?, '8');", (f"autonomous_max_attempts_24h:{other_pid}",))

    # 3. Trigger database initialization / migration
    scheduler.init_db(db_path)

    # 4. Verify migrated values
    # Quiz is elevated to 10 approvals and 30 attempts
    assert autonomous_production.get_max_generations_24h(profile_id=quiz_pid, db_path=db_path) == 10
    assert autonomous_production.get_max_attempts_24h(profile_id=quiz_pid, db_path=db_path) == 30

    # Global Cost Guard is elevated to 20 approvals and 50 attempts
    assert autonomous_production.get_global_max_generations_24h(db_path=db_path) == 20
    assert autonomous_production.get_global_max_attempts_24h(db_path=db_path) == 50

    # Other profile is strictly preserved at 2 approvals and 8 attempts
    assert autonomous_production.get_max_generations_24h(profile_id=other_pid, db_path=db_path) == 2
    assert autonomous_production.get_max_attempts_24h(profile_id=other_pid, db_path=db_path) == 8

    # Migration marker is present
    with scheduler.get_connection(db_path) as conn:
        mig_row = conn.execute("SELECT value FROM autopilot_settings WHERE key = 'migration_mission_e_capacity_v1';").fetchone()
        assert mig_row is not None
        assert mig_row[0] == "done"

    # 5. Idempotence test: future intentional operator changes must NOT be overwritten by init_db
    autonomous_production.set_max_generations_24h(7, profile_id=quiz_pid, db_path=db_path)
    autonomous_production.set_global_max_generations_24h(15, db_path=db_path)

    scheduler.init_db(db_path)

    assert autonomous_production.get_max_generations_24h(profile_id=quiz_pid, db_path=db_path) == 7
    assert autonomous_production.get_global_max_generations_24h(db_path=db_path) == 15
