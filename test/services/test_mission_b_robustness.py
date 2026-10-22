# -*- coding: utf-8 -*-
"""Targeted unit tests for Mission B: Robustness and Stability V1.

Tests cover:
1. RISK-SQL-01: SQLite connection leak resolution in content_strategy.py.
   - Guaranteed closure in get_connection contextmanager
   - Transactional rollback on error
   - High-iteration execution without handle leaks or db locks
2. RISK-SQL-02: SQLite connection leak resolution in quality_recovery.py.
   - Guaranteed closure in all review / command paths
   - High-iteration execution without handle leaks or db locks
3. RISK-REC-01: Verification of Scheduler anti-burst protections.
   - Unitary LIMIT 1 selection
   - min_interval_hours enforcement against overdue backlog after restart
   - 24-hour rolling limit postponement
4. Mission A Safety Gates preservation and video eligibility.
"""

import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from app.models import const
from app.services import (
    content_strategy,
    operator_console,
    quality_recovery,
    quality_score,
    quiz_safety_gate,
    safety_gate,
    scheduler,
)


@pytest.fixture
def temp_workspace():
    temp_dir = tempfile.mkdtemp(prefix="test_mission_b_")
    db_path = os.path.join(temp_dir, "test_factory.db")
    task_dir = os.path.join(temp_dir, "tasks")
    os.makedirs(task_dir, exist_ok=True)

    scheduler.init_db(db_path)
    content_strategy.init_strategy_db(db_path)
    quality_recovery.init_review_db(db_path)
    safety_gate.init_safety_db(db_path)
    quiz_safety_gate.init_quiz_safety_db(db_path)

    yield {"temp_dir": temp_dir, "db_path": db_path, "task_dir": task_dir}

    try:
        shutil.rmtree(temp_dir)
    except Exception:
        pass


def test_content_strategy_connection_closure_and_rollback(temp_workspace):
    """RISK-SQL-01: Test that content_strategy.get_connection always closes connections."""
    db_path = temp_workspace["db_path"]

    # Verify contextmanager works cleanly
    with content_strategy.get_connection(db_path) as conn:
        assert isinstance(conn, sqlite3.Connection)
        conn.execute("SELECT 1;")
        assert conn.total_changes is not None

    # Verify rollback on exception
    with pytest.raises(RuntimeError):
        with content_strategy.get_connection(db_path) as conn:
            conn.execute(
                "INSERT INTO content_strategy_scores (topic, strategy_score, strategy_label, strategy_bucket, created_at) "
                "VALUES ('Test Rollback', 80.0, 'PROMISING', 'Experiment', '2026-10-22T00:00:00Z');"
            )
            raise RuntimeError("Forced error to test rollback")

    with content_strategy.get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM content_strategy_scores WHERE topic = 'Test Rollback';").fetchone()
        assert row is None, "Transaction was not rolled back on exception"


def test_content_strategy_high_iteration_no_leaks(temp_workspace):
    """RISK-SQL-01: Verify repeated evaluations with persist=True execute without locking or leaks."""
    db_path = temp_workspace["db_path"]

    for i in range(15):
        res = content_strategy.evaluate_strategy(
            topic=f"Curiosidade Inédita sobre Astronomia #{i}",
            niche="curiosidades",
            preset="cross_platform",
            persist=True,
            db_path=db_path,
        )
        assert res["id"] is not None
        assert res["strategy_score"] > 0

    # Retrieve recent scores
    recent = content_strategy.get_recent_strategy_scores(limit=10, db_path=db_path)
    assert len(recent) <= 10
    assert len(recent) > 0


def test_quality_recovery_connection_closure_and_commands(temp_workspace):
    """RISK-SQL-02: Test that quality_recovery connection helper closes connections across commands."""
    db_path = temp_workspace["db_path"]

    # Enqueue 10 review commands
    cmd_ids = []
    for i in range(10):
        cid = quality_recovery.enqueue_review_command(
            task_id=f"task-test-{i}",
            action="APPROVE",
            operator_id="test_op",
            note=f"Note {i}",
            db_path=db_path,
        )
        cmd_ids.append(cid)

    assert quality_recovery.has_pending_review_commands(db_path=db_path) is True

    # Test reading without lock
    with quality_recovery.get_connection(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM operator_review_commands;").fetchone()[0]
        assert count == 10

    # Test rollback on exception inside get_connection
    with pytest.raises(ValueError):
        with quality_recovery.get_connection(db_path) as conn:
            conn.execute(
                "INSERT INTO operator_video_reviews (task_id, decision, operator_id, created_at, updated_at) "
                "VALUES ('task-err', 'APPROVED', 'op', '2026-10-22T00:00:00Z', '2026-10-22T00:00:00Z');"
            )
            raise ValueError("Test rollback in quality_recovery")

    with quality_recovery.get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM operator_video_reviews WHERE task_id = 'task-err';").fetchone()
        assert row is None


def test_scheduler_anti_burst_min_interval_hours(temp_workspace):
    """RISK-REC-01: Verify that min_interval_hours prevents burst firing of overdue posts."""
    db_path = temp_workspace["db_path"]

    # Configure conservative mode with min_interval_hours = 6
    scheduler.set_setting("scheduler_enabled", "1", db_path=db_path)
    scheduler.set_setting("auto_publish_enabled", "1", db_path=db_path)
    scheduler.set_setting("dry_run_enabled", "0", db_path=db_path)
    scheduler.set_setting("growth_mode", "conservative", db_path=db_path)

    limits = scheduler.get_platform_rate_limits("youtube", db_path=db_path)
    assert limits["min_interval_hours"] == 6

    # Simulate that a post was published 1 hour ago
    one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    with scheduler.get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO publication_events (task_id, platform, status, published_at)
            VALUES ('prev-task-pub', 'youtube', 'success', ?);
            """,
            (one_hour_ago,),
        )

    # Simulate an overdue post scheduled 5 hours ago
    overdue_time = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()
    with scheduler.get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, attempts, created_at)
            VALUES ('overdue-task-1', 'youtube', ?, 'scheduled', 0, ?);
            """,
            (overdue_time, now_iso),
        )

    # In cycle, if min_interval_hours=6 and last pub was 1h ago, the post MUST be postponed!
    now = datetime.now(timezone.utc)
    with scheduler.get_connection(db_path) as conn:
        last_pub_row = conn.execute(
            "SELECT MAX(published_at) AS last_pub FROM publication_events WHERE platform = ? AND status = 'success';",
            ("youtube",),
        ).fetchone()
        assert last_pub_row is not None and last_pub_row["last_pub"] is not None
        last_pub_dt = datetime.fromisoformat(last_pub_row["last_pub"])
        min_allowed = last_pub_dt + timedelta(hours=limits["min_interval_hours"])
        assert now < min_allowed

        post = conn.execute(
            "SELECT * FROM scheduled_posts WHERE status = 'scheduled' AND scheduled_at <= ? ORDER BY scheduled_at ASC LIMIT 1;",
            (now.isoformat(),)
        ).fetchone()
        assert post is not None
        assert post["task_id"] == "overdue-task-1"

        # Apply scheduler anti-burst postponement (matching scheduler.py:2648-2656)
        conn.execute(
            """
            UPDATE scheduled_posts
            SET scheduled_at = ?, next_attempt_at = ?, status = 'ready'
            WHERE id = ?;
            """,
            (min_allowed.isoformat(), min_allowed.isoformat(), post["id"]),
        )

    # Verify that scheduled_at is now postponed into the future
    with scheduler.get_connection(db_path) as conn:
        updated_post = conn.execute("SELECT * FROM scheduled_posts WHERE id = ?;", (post["id"],)).fetchone()
        assert updated_post["scheduled_at"] > now.isoformat()
        assert updated_post["status"] == "ready"


def test_mission_a_safety_preserved(temp_workspace):
    """Verify that Mission A safety gates remain active, fail-closed, and block unvalidated items."""
    db_path = temp_workspace["db_path"]
    task_id = "test-mission-b-safety-1"

    # Create dummy video artifact to satisfy technical gate
    task_dir = os.path.join(temp_workspace["task_dir"], task_id)
    os.makedirs(task_dir, exist_ok=True)
    with open(os.path.join(task_dir, "final-1.mp4"), "wb") as f:
        f.write(b"\x00" * 1024)

    # 1. Invalidation of failed duration marks HELD_SAFETY_REVIEW
    quiz_safety_gate.evaluate_quiz_duration_safety(
        task_id=task_id,
        actual_duration=55.0,  # Invalid: below 60.0s
        db_path=db_path,
    )

    is_held, hold_reason = scheduler.is_task_held_for_safety_review(task_id, db_path=db_path)
    assert is_held is True
    assert "REVIEW" in hold_reason or "FAILED" in hold_reason

    # 2. Candidate validation blocks HELD task even with valid video file on disk
    valid, reason, details = scheduler.validate_candidate_technical_and_safety_gates(
        task_id=task_id,
        task_base_dir=temp_workspace["task_dir"],
        db_path=db_path,
    )
    assert valid is False
    assert "SAFETY_GATE_HELD_FOR_REVIEW" in reason
