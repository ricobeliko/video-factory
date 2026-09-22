"""V12-F.2: temporary SQLite, fake publication/provider, no generation or HTTP."""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models import const
from app.config import config
from app.models.schema import VideoParams
from app.services import (analytics, analytics_ingestion, autonomous_production as autonomous,
                          content_strategy as strategy, operator_console as console,
                          profile_manager, quality_score, safety_gate, scheduler)
from app.services.analytics_providers.youtube import YouTubeAnalyticsProvider


@pytest.fixture
def history(tmp_path, monkeypatch):
    import socket
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network forbidden")))
    db = str(tmp_path / "history.db")
    console.init_operator_db(db)
    profile_manager.ensure_default_profile(db)
    analytics.init_analytics_db(db)
    safety_gate.init_safety_db(db)
    quality_score.init_quality_db(db)
    cutoff = datetime.now(timezone.utc) + timedelta(minutes=1)
    with scheduler.get_connection(db) as conn:
        channel = conn.execute("SELECT id FROM publishing_channels WHERE platform='youtube' AND profile_id='default'").fetchone()[0]
    scope = dict(platform="youtube", profile_id="default", channel_id=channel)
    counter = [0]

    def add(views=100, topic="Como funciona o oceano", structure="explainer", age=72):
        counter[0] += 1
        i = counter[0]
        task, external = f"task-{i}", f"video{i:06d}"
        published = cutoff - timedelta(days=5)
        profile_manager.save_task_profile(task, "default", db)
        # Fake publication records use the real persistence API, never an uploader.
        scheduler.record_publication_event(task_id=task, platform="youtube", status="success",
                                           external_id=external, profile_id="default", channel_id=channel,
                                           privacy_status="public", published_at=published, db_path=db)
        with scheduler.get_connection(db) as conn:
            conn.execute("INSERT INTO monetization_safety(task_id,topic,preset,narrative_structure,safety_status,checked_at) VALUES (?,?,?,?,?,?)",
                         (task, topic, "youtube_shorts_original", structure, "PASS", published.isoformat()))
            conn.execute("INSERT INTO content_quality_scores(task_id,topic,quality_score,quality_label,created_at) VALUES (?,?,?,?,?)",
                         (task, topic, 80, "GOOD", published.isoformat()))
        provider = YouTubeAnalyticsProvider()
        payload = {"items": [{"id": external, "statistics": {"viewCount": str(views), "likeCount": "1", "commentCount": "0"}}]}
        with patch.object(provider, "fetch_metrics", return_value=payload), patch.object(analytics_ingestion, "get_provider", return_value=provider):
            snapshot = analytics_ingestion.ingest_analytics_for_publication(task, "youtube", channel_id=channel,
                         collected_at=(published + timedelta(hours=age)).isoformat(), db_path=db)
        return snapshot

    def evidence():
        return analytics.get_learning_evidence(**scope, cutoff_time=cutoff, db_path=db)

    return db, scope, cutoff, add, evidence


def seed(history, n=12, a=100, b=10):
    for i in range(n):
        history[3](views=a if i % 2 == 0 else b,
                   topic="Como funciona o oceano" if i % 2 == 0 else "A historia do imperio",
                   structure="explainer" if i % 2 == 0 else "short_story")


@pytest.mark.parametrize("n,a,b,state", [(11,100,10,"INSUFFICIENT_DATA"), (12,100,10,"ELIGIBLE"),
                                         (12,0,0,"NO_CONTRAST"), (12,10,10,"NO_CONTRAST")])
def test_sample_gate(history,n,a,b,state):
    seed(history,n,a,b)
    ev = history[4]()
    assert ev["sample_count"] == n
    assert ev["evidence_state"] == state
    assert ev == history[4]()


def test_one_group(history):
    for _ in range(12):
        history[3]()
    assert history[4]()["evidence_state"] == "INSUFFICIENT_DATA"


def test_snapshots_and_tied_timestamps(history):
    first = history[3](age=80)
    db = history[0]
    with scheduler.get_connection(db) as conn:
        columns = [r[1] for r in conn.execute("PRAGMA table_info(content_analytics)") if r[1] != "id"]
        cols = ",".join(columns)
        select_cols = ",".join("?" if c == "collected_at" else c for c in columns)
        for i in range(11):
            stamp = (history[2] - timedelta(days=2) + timedelta(minutes=i)).isoformat()
            if i == 1:  # same instant, different legal ISO representation
                stamp = (history[2] - timedelta(days=2)).isoformat().replace("+00:00", "Z")
            conn.execute(f"INSERT INTO content_analytics({cols}) SELECT {select_cols} FROM content_analytics WHERE id=?", (stamp,first["id"]))
    ev = history[4]()
    assert ev["sample_count"] == 1
    assert ev["eligible_snapshot_ids"] == [2]


@pytest.mark.parametrize("table,column,value,reason", [
    ("publication_events","privacy_status","private","publication_not_public_success"),
    ("publication_events","privacy_status","unlisted","publication_not_public_success"),
    ("publication_events","privacy_status",None,"publication_not_public_success"),
    ("publication_events","status","failed","publication_not_public_success"),
    ("monetization_safety","safety_status","BLOCK","safety_not_pass"),
    ("monetization_safety","safety_status","REVIEW","safety_not_pass"),
    ("content_quality_scores","quality_score",69,"quality_not_approved"),
    ("content_quality_scores","quality_label","WEAK","quality_not_approved"),
    ("content_analytics","source","manual","untrusted_source"),
    ("content_analytics","metadata_json",'{"dry_run":true}',"untrusted_source"),
    ("content_analytics","metadata_json",'{"dry_run":false,"synthetic":true}',"untrusted_source"),
    ("content_analytics","metadata_json",'{}',"untrusted_source"),
    ("content_analytics","external_id","wrong","identity_mismatch"),
    ("task_profiles","profile_id","other","task_profile_mismatch"),
])
def test_exclusions(history,table,column,value,reason):
    history[3]()
    with scheduler.get_connection(history[0]) as conn:
        conn.execute(f"UPDATE {table} SET {column}=?", (value,))
    ev = history[4]()
    assert ev["sample_count"] == 0
    assert ev["excluded_counts_by_reason"][reason] == 1


@pytest.mark.parametrize("table", ["monetization_safety", "content_quality_scores"])
def test_missing_gates(history,table):
    history[3]()
    with scheduler.get_connection(history[0]) as conn:
        conn.execute(f"DELETE FROM {table}")
    assert history[4]()["sample_count"] == 0


@pytest.mark.parametrize("column,value", [("profile_id","other"),("channel_id","other"),("platform","tiktok")])
def test_scope_before_aggregation(history,column,value):
    seed(history)
    before = history[4]()
    history[3](views=99999999)
    with scheduler.get_connection(history[0]) as conn:
        conn.execute(f"UPDATE content_analytics SET {column}=? WHERE id=13", (value,))
    assert history[4]() == before


@pytest.mark.parametrize("age", [71,97])
def test_age_window(history,age):
    history[3](age=age)
    assert history[4]()["sample_count"] == 0


@pytest.mark.parametrize("winner,state", [([10,10,10,10,999999],"NO_CONTRAST"),
                                        ([0,0,11,11,11],"UNSTABLE"),
                                        ([100,100,100,100,100],"ELIGIBLE")])
def test_leave_one_out(winner,state):
    samples = [{"g":"a","views":v,"engagement":0} for v in winner]
    samples += [{"g":"b","views":10,"engagement":0} for _ in range(5)]
    assert analytics._learning_groups(samples,"g")[2] == state


def decision(history,recent=()):
    base = {"topic":"A historia do imperio", "narrative_structure":"short_story", "trend_data":{"opportunity_score":70}}
    candidates = [{"topic":"Como funciona o oceano", "trend_data":{"opportunity_score":68}}]
    return strategy.select_closed_loop_candidate(base,candidates,history[4](),list(recent))


def test_bounded_selection(history):
    seed(history)
    result = decision(history)
    assert result["adapted"]
    assert result["selected_candidate"]["topic"] == "Como funciona o oceano"
    assert result["history_bonus"] <= 5
    with scheduler.get_connection(history[0]) as conn:
        conn.execute("UPDATE content_analytics SET performance_score=999999 WHERE views=10")
    assert decision(history) == result


@pytest.mark.parametrize("recent,reason", [([{"adapted":True}],"exploration_slot"),
    ([{}, {"adapted":True}],"exploration_slot"),
    ([{"topic_cluster":"oceanos"},{"topic_cluster":"oceanos"}],"cluster_saturated"),
    ([{"narrative_structure":"explainer"}],"structure_repetition")])
def test_diversity(history,recent,reason):
    seed(history)
    result = decision(history,recent)
    assert not result["adapted"]
    assert result["reason"] == reason


def test_third_submission_allows_adaptation(history):
    seed(history)
    assert decision(history,[{}, {}, {"adapted":True}])["adapted"]


def test_restart_submission_history(history):
    db,scope = history[:2]
    for i,adapted in enumerate([True,False,False]):
        console.log_operational_event("closed_loop","INFO","CLOSED_LOOP_SUBMITTED","test",task_id=str(i),metadata=dict(scope,adapted=adapted),db_path=db)
    first = console.get_closed_loop_submissions(**scope,db_path=db)
    console.reset_instance_for_testing()
    assert console.get_closed_loop_submissions(**scope,db_path=db) == first
    assert [r["adapted"] for r in first] == [False,False,True]


def test_flag_default_and_primary(history):
    db = history[0]
    assert not console.get_closed_feedback_loop_enabled_op(db)
    with patch.object(console,"require_primary_instance",side_effect=PermissionError):
        with pytest.raises(PermissionError):
            console.set_closed_feedback_loop_enabled_op(True,db)
    assert not console.get_closed_feedback_loop_enabled_op(db)
    with patch.object(console,"require_primary_instance"):
        console.set_closed_feedback_loop_enabled_op(True,db)
        assert console.get_closed_feedback_loop_enabled_op(db)
        console.set_closed_feedback_loop_enabled_op(False,db)


def test_read_error(history):
    with patch.object(analytics.sqlite3,"connect",side_effect=RuntimeError):
        assert history[4]()["evidence_state"] == "ERROR_FALLBACK"


def run_generation(history, enabled=True, audit_error=False):
    db, scope = history[:2]
    baseline = {"topic":"A historia do imperio", "origin":"trend_radar_fresh", "trend_data":{"opportunity_score":70}}
    with patch.dict(config.app,{"video_source":"pexels"}), patch.dict(config.ui,{"voice_mode":"tts","voice_name":"pt-BR-AntonioNeural-Male"}), \
         patch.object(console,"require_primary_instance"), patch.object(console,"is_primary_instance",return_value=True), \
         patch.object(console,"is_factory_paused",return_value=False), \
         patch.object(autonomous,"get_autonomous_ready_stock",return_value={"ready_count":0,"target_stock":3}), \
         patch.object(autonomous,"count_generations_in_last_24h",return_value=0), \
         patch.object(autonomous,"check_required_providers_preflight",return_value=(True,"ok",{})), \
         patch.object(autonomous,"discover_candidate_topic",return_value=baseline), \
         patch.object(autonomous,"collect_existing_topics",return_value=[]), \
         patch.object(autonomous.trend_radar,"get_trend_items",return_value=[{"title":"Como funciona o oceano","opportunity_score":68}]), \
         patch.object(autonomous.webui_task,"submit_generation") as submit:
        baseline_params = autonomous.build_autonomous_video_params("probe",profile_id="default",db_path=db)
        console.set_closed_feedback_loop_enabled_op(enabled,db)
        # One-shot uses the existing OFF-safe generation contract; no production flag changes.
        original_log = console.record_closed_loop_decision
        def log(*args,**kwargs):
            if audit_error:
                raise RuntimeError("audit unavailable")
            return original_log(*args,**kwargs)
        with patch.object(console,"record_closed_loop_decision",side_effect=log):
            result = autonomous.run_autonomous_cycle(force=True,one_shot=True,db_path=db)
        assert result["status"] == "generation_started", result
        return submit.call_args.kwargs["params"], baseline_params


def test_closed_loop_fake_publication_to_real_autonomous_params(history):
    seed(history)
    params,baseline = run_generation(history)
    assert params.video_subject == "Como funciona o oceano"
    assert params.narrative_structure == "explainer"
    assert {k:v for k,v in params.model_dump().items() if k not in ("video_subject","narrative_structure")} == {
        k:v for k,v in baseline.model_dump().items() if k not in ("video_subject","narrative_structure")}
    with scheduler.get_connection(history[0]) as conn:
        row = conn.execute("SELECT metadata_json FROM operational_events WHERE event_type='CLOSED_LOOP_DECISION'").fetchone()
    audit = json.loads(row[0])
    assert audit["adapted"] and len(audit["snapshot_ids"]) == 12
    assert audit["applied_video_params"]["video_subject"] == params.video_subject


@pytest.mark.parametrize("enabled,audit_error,seed_data", [(False,False,True),(True,False,False),(True,True,True)])
def test_baseline_equivalence(history,enabled,audit_error,seed_data):
    if seed_data:
        seed(history)
    params,_ = run_generation(history,enabled,audit_error)
    assert params.video_subject == "A historia do imperio"
    assert params.narrative_structure == "short_story"


def test_off_never_reads_evidence(history):
    with patch.object(analytics,"get_learning_evidence",side_effect=AssertionError("must not read")) as read:
        run_generation(history,False)
    read.assert_not_called()


@pytest.mark.parametrize("failure", ["analytics", "strategy", "history"])
def test_optional_failures_preserve_generation(history,failure):
    seed(history)
    target = {"analytics": (analytics,"get_learning_evidence"),
              "strategy": (strategy,"select_closed_loop_candidate"),
              "history": (console,"get_closed_loop_submissions")}[failure]
    with patch.object(*target,side_effect=RuntimeError("unavailable")):
        params,_ = run_generation(history)
    assert params.video_subject == "A historia do imperio"


def test_settings_and_publications_unchanged(history):
    seed(history)
    db = history[0]
    settings = {"auto_publish_enabled":"True","autonomous_mode_enabled":"True",
                "analytics_auto_collection_enabled":"True","growth_mode":"warmup",
                "tiktok_enabled":"False","analytics_max_fetches_per_cycle":"1",
                "analytics_cycle_min_interval_seconds":"300"}
    for key,value in settings.items():
        scheduler.set_setting(key,value,db)
    with scheduler.get_connection(db) as conn:
        publications = [tuple(r) for r in conn.execute("SELECT * FROM publication_events")]
    run_generation(history)
    assert {key:scheduler.get_setting(key,db_path=db) for key in settings} == settings
    with scheduler.get_connection(db) as conn:
        assert [tuple(r) for r in conn.execute("SELECT * FROM publication_events")] == publications
        assert conn.execute("SELECT COUNT(*) FROM scheduled_posts").fetchone()[0] == 0


def test_replay_and_reservation(history):
    seed(history)
    run_generation(history)
    db,scope = history[:2]
    with scheduler.get_connection(db) as conn:
        audit = json.loads(conn.execute("SELECT metadata_json FROM operational_events WHERE event_type='CLOSED_LOOP_DECISION'").fetchone()[0])
        conn.execute("DELETE FROM operational_events WHERE event_type='CLOSED_LOOP_SUBMITTED'")
    assert console.get_closed_loop_submissions(**scope,db_path=db)[0]["pending"]
    baseline = {"topic":audit["baseline_topic"],"narrative_structure":audit["baseline_structure"],
                "trend_data":{"opportunity_score":audit["candidate_ranks"][0]["baseline_rank"]}}
    candidates = [{"topic":c["topic"],"trend_data":{"opportunity_score":c["baseline_rank"]}} for c in audit["candidate_ranks"][1:]]
    replay = strategy.select_closed_loop_candidate(baseline,candidates,audit["evidence"],audit["recent_submissions"])
    assert replay["selected_candidate"]["topic"] == audit["selected_topic"]
    assert replay["selected_candidate"]["narrative_structure"] == audit["selected_structure"]


def test_one_qualified_group_is_not_enough(history):
    for i in range(12):
        history[3](topic="Como funciona o oceano" if i < 8 else "A historia do imperio",
                   structure="explainer" if i < 8 else "short_story")
    assert history[4]()["evidence_state"] == "INSUFFICIENT_DATA"


@pytest.mark.parametrize("field,value", [("platform","tiktok"),("profile_id",""),("channel_id","")])
def test_invalid_scope(history,field,value):
    scope = dict(history[1], **{field:value})
    ev = analytics.get_learning_evidence(**scope,db_path=history[0])
    assert ev["sample_count"] == 0 and ev["fallback_reason"] == "invalid_scope"


def test_five_points_cannot_override_strong_trend(history):
    seed(history)
    baseline = {"topic":"A historia do imperio","narrative_structure":"short_story","trend_data":{"opportunity_score":90}}
    candidates = [{"topic":"Como funciona o oceano","trend_data":{"opportunity_score":60}}]
    result = strategy.select_closed_loop_candidate(baseline,candidates,history[4](),[])
    assert result["selected_candidate"]["topic"] == baseline["topic"]


def test_concurrent_stale_decision_cannot_reserve_again(history):
    seed(history)
    run_generation(history)
    db = history[0]
    with scheduler.get_connection(db) as conn:
        audit = json.loads(conn.execute("SELECT metadata_json FROM operational_events WHERE event_type='CLOSED_LOOP_DECISION'").fetchone()[0])
    with pytest.raises(ValueError, match="submission_history_changed"):
        console.record_closed_loop_decision("competing-task",audit,db)
    with scheduler.get_connection(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM operational_events WHERE event_type='CLOSED_LOOP_DECISION'").fetchone()[0] == 1


def test_no_schema_changes_and_no_score_rewrite(history):
    seed(history)
    db = history[0]
    with scheduler.get_connection(db) as conn:
        before_schema = [tuple(r) for r in conn.execute("SELECT type,name,sql FROM sqlite_master ORDER BY name")]
        before_scores = [tuple(r) for r in conn.execute("SELECT id,performance_score FROM content_analytics ORDER BY id")]
    run_generation(history)
    with scheduler.get_connection(db) as conn:
        assert [tuple(r) for r in conn.execute("SELECT type,name,sql FROM sqlite_master ORDER BY name")] == before_schema
        assert [tuple(r) for r in conn.execute("SELECT id,performance_score FROM content_analytics ORDER BY id")] == before_scores
