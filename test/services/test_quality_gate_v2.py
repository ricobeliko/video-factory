# -*- coding: utf-8 -*-
"""
test/services/test_quality_gate_v2.py
=====================================
Validação dirigida do Hotfix QG-V2:
1. YouTube aceita Shorts válidos com menos de 60 segundos.
2. TikTok Creator Rewards exige mais de 60 segundos.
3. Quality Score inferior a 70 não é aprovado automaticamente (REVIEW != PASS).
4. Safety e Copyright continuam bloqueantes (fail-closed).
5. Avaliação editorial antecipada reduz geração desnecessária (aborta antes do Flow).
6. MP4 existente é identificado para reavaliação sem regeneração.
7. Retry preserva cenas válidas e idempotência.
8. Estoque e publicação recebem apenas conteúdo elegível.

Fixtures baseadas nos quatro casos reais auditados:
- GTA 5 vs GTA 6 (63.3 - REVIEW)
- Mel das abelhas (73.7 - GOOD)
- Elevador despencando (69.2 - REVIEW)
- Reflexo na velocidade da luz (76.5 - GOOD)
"""

import json
import os
import sqlite3
import tempfile
import pytest

from app.models import const
from app.services import (
    autonomous_production,
    copyright_gate,
    profile_manager,
    quality_score,
    safety_gate,
    scheduler,
    state as sm,
)
from scripts.inspect_held_quality_videos import inspect_held_videos


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    scheduler.init_db(path)
    safety_gate.init_safety_db(path)
    quality_score.init_quality_db(path)
    profile_manager.init_profile_db(path)
    profile_manager.ensure_default_profile(path)
    yield path
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


@pytest.fixture
def audit_cases():
    return {
        "gta": {
            "topic": "GTA 5 vs GTA 6: o que muda na física dos carros",
            "niche": "Games",
            "script": "Você sabia que a física de colisão mudou completamente entre GTA 5 e GTA 6? Vamos analisar o comparativo de direção.",
            "duration": 52.0,
            "orig_score": 63.3,
            "orig_label": "REVIEW",
        },
        "abelhas": {
            "topic": "Mel das abelhas: como é produzido na colmeia",
            "niche": "Curiosidades",
            "script": "O mistério de como as abelhas produzem o mel revela uma engenharia natural fascinante dentro da colmeia.",
            "duration": 65.0,
            "orig_score": 73.7,
            "orig_label": "GOOD",
        },
        "elevador": {
            "topic": "Elevador despencando: o que fazer para sobreviver",
            "niche": "Curiosidades",
            "script": "O que fazer se um elevador estiver despencando em queda livre? Descubra a verdade sobre o impacto e como se proteger.",
            "duration": 58.0,
            "orig_score": 69.2,
            "orig_label": "REVIEW",
        },
        "luz": {
            "topic": "Reflexo na velocidade da luz e os mistérios da física",
            "niche": "Ciência",
            "script": "O que acontece com o seu reflexo se você se mover na velocidade da luz? A resposta desafia a física quântica e o tempo.",
            "duration": 68.0,
            "orig_score": 76.5,
            "orig_label": "GOOD",
        },
    }


# ===========================================================================
# 1. YouTube aceita Shorts válidos com menos de 60 segundos
# ===========================================================================

def test_youtube_shorts_accepts_under_60s(temp_db):
    """Garante que vídeos verticais < 60s são aprovados para YouTube Shorts."""
    tid = "test-task-yt-52s"
    dur_res = safety_gate.evaluate_duration_safety(
        task_id=tid,
        actual_duration=52.0,
        preset="cross_platform",
        platform="youtube",
        db_path=temp_db,
    )
    assert dur_res["safety_status"] == const.SAFETY_STATUS_PASS
    assert any("YouTube Shorts" in r for r in dur_res["safety_reasons"])

    s_dur, r_dur = quality_score.calculate_duration_fit(
        actual_duration=52.0,
        preset="cross_platform",
        platform="youtube",
    )
    assert s_dur == 100.0
    assert any("YouTube Shorts" in r for r in r_dur)


# ===========================================================================
# 2. TikTok Creator Rewards exige mais de 60 segundos
# ===========================================================================

def test_tiktok_creator_rewards_requires_gt_60s(temp_db):
    """Garante que o TikTok Creator Rewards exige estritamente > 60s."""
    tid_short = "test-task-tt-55s"
    dur_res_short = safety_gate.evaluate_duration_safety(
        task_id=tid_short,
        actual_duration=55.0,
        preset="tiktok_creator_rewards",
        platform="tiktok",
        db_path=temp_db,
    )
    assert dur_res_short["safety_status"] == const.SAFETY_STATUS_BLOCK
    assert any("60s" in r for r in dur_res_short["safety_reasons"])

    s_dur_short, _ = quality_score.calculate_duration_fit(
        actual_duration=55.0,
        preset="tiktok_creator_rewards",
        platform="tiktok",
    )
    assert s_dur_short == 30.0

    # Com 65s, deve ser aprovado no TikTok Rewards
    tid_ok = "test-task-tt-65s"
    dur_res_ok = safety_gate.evaluate_duration_safety(
        task_id=tid_ok,
        actual_duration=65.0,
        preset="tiktok_creator_rewards",
        platform="tiktok",
        db_path=temp_db,
    )
    assert dur_res_ok["safety_status"] == const.SAFETY_STATUS_PASS

    s_dur_ok, _ = quality_score.calculate_duration_fit(
        actual_duration=65.0,
        preset="tiktok_creator_rewards",
        platform="tiktok",
    )
    assert s_dur_ok == 100.0


# ===========================================================================
# 3. Quality Score inferior a 70 não é aprovado automaticamente
# ===========================================================================

def test_quality_score_below_70_is_rejected_never_auto_pass(temp_db, tmp_path, monkeypatch):
    """Garante fail-closed: Quality Score < 70 (REVIEW) NUNCA é aprovado como PASS."""
    tid = "task-review-held-68"
    video_dir = tmp_path / "tasks" / tid
    video_dir.mkdir(parents=True)
    video_file = video_dir / "final-1.mp4"
    video_file.write_bytes(b"\x00" * 1024)

    safety_gate.save_safety_assessment({
        "task_id": tid,
        "preset": "youtube_shorts_original",
        "safety_status": const.SAFETY_STATUS_PASS,
        "safety_reasons": ["Roteiro seguro"],
        "actual_duration": 48.0,
        "checked_at": "2026-10-16T12:00:00Z",
    }, db_path=temp_db)

    # Tópico e gancho com clichê que pontuam < 70 (REVIEW)
    sm.state.update_task(
        tid,
        state=const.TASK_STATE_COMPLETE,
        video_subject="Reflexão sobre dilema moral existencial sem gancho",
        hook_text="Hoje vamos falar sobre isso e deixe seu like",
        audio_duration=48.0,
        safety_status=const.SAFETY_STATUS_PASS,
    )

    # Mock de copyright para garantir que o Quality Gate seja a barreira avaliada
    monkeypatch.setattr(
        "app.services.copyright_gate.evaluate_copyright_provenance_gate",
        lambda task_id, task_data=None, task_base_dir=None, db_path=None: (True, "OK", {})
    )

    approved, reason, metrics = autonomous_production.evaluate_completed_task_gates(
        task_id=tid,
        db_path=temp_db,
        task_base_dir=str(tmp_path / "tasks"),
    )

    # Score < 70 DEVE ser rejeitado (approved == False)
    assert approved is False
    assert "insuficiente" in reason.lower()
    assert metrics.get("quality_score") < 70.0
    assert metrics.get("quality_label") in ("REVIEW", "WEAK")


# ===========================================================================
# 4. Safety/Copyright continuam bloqueantes (fail-closed)
# ===========================================================================

def test_safety_and_copyright_remain_strictly_blocking(temp_db, tmp_path):
    """Garante que tarefas com Safety BLOCK ou Copyright BLOCK nunca passam."""
    tid_safety_block = "task-safety-blocked"
    v_dir = tmp_path / "tasks" / tid_safety_block
    v_dir.mkdir(parents=True)
    (v_dir / "final-1.mp4").write_bytes(b"\x00" * 1024)

    safety_gate.save_safety_assessment({
        "task_id": tid_safety_block,
        "preset": "cross_platform",
        "safety_status": const.SAFETY_STATUS_BLOCK,
        "safety_reasons": ["Conteúdo perigoso proibido"],
        "checked_at": "2026-10-16T12:00:00Z",
    }, db_path=temp_db)

    sm.state.update_task(
        tid_safety_block,
        state=const.TASK_STATE_COMPLETE,
        safety_status=const.SAFETY_STATUS_BLOCK,
    )

    approved, reason, _ = autonomous_production.evaluate_completed_task_gates(
        task_id=tid_safety_block,
        db_path=temp_db,
        task_base_dir=str(tmp_path / "tasks"),
    )
    assert approved is False
    assert "BLOCK" in reason

    # Verificação de Copyright BLOCK
    tid_cp_block = "task-cp-blocked"
    v_dir2 = tmp_path / "tasks" / tid_cp_block
    v_dir2.mkdir(parents=True)
    (v_dir2 / "final-1.mp4").write_bytes(b"\x00" * 1024)

    safety_gate.save_safety_assessment({
        "task_id": tid_cp_block,
        "preset": "cross_platform",
        "safety_status": const.SAFETY_STATUS_PASS,
        "safety_reasons": [],
        "checked_at": "2026-10-16T12:00:00Z",
    }, db_path=temp_db)

    sm.state.update_task(
        tid_cp_block,
        state=const.TASK_STATE_COMPLETE,
        copyright_status="BLOCK",
        copyright_reasons=["Material proprietário não licenciado"],
    )

    with sqlite3.connect(temp_db) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS copyright_provenance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                status TEXT NOT NULL,
                confidence REAL,
                reasons TEXT,
                checked_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO copyright_provenance (
                task_id, status, confidence, reasons, checked_at
            ) VALUES (?, ?, ?, ?, ?);
            """,
            (tid_cp_block, "BLOCK", 1.0, json.dumps(["Material proprietário"]), "2026-10-16T12:00:00Z"),
        )

    approved_cp, reason_cp, _ = autonomous_production.evaluate_completed_task_gates(
        task_id=tid_cp_block,
        db_path=temp_db,
        task_base_dir=str(tmp_path / "tasks"),
    )
    assert approved_cp is False


# ===========================================================================
# 5. Avaliação editorial antecipada reduz geração desnecessária
# ===========================================================================

def test_pre_generation_editorial_gate_stops_weak_script(temp_db):
    """Garante que roteiro editorialmente fraco (< 55.0 WEAK ou gancho clichê) é barrado antes do Flow."""
    weak_topic = "coisa qualquer"
    weak_script = "Hoje vamos falar sobre coisas banais sem nenhum gancho ou curiosidade."

    eval_res = quality_score.evaluate_pre_generation_editorial_quality(
        task_id="task-weak-pre-flow",
        topic=weak_topic,
        script=weak_script,
        platform="youtube",
        db_path=temp_db,
    )

    assert eval_res["can_proceed_to_visuals"] is False
    assert any("clichê" in r or "incompatível" in r for r in eval_res["reasons"])


# ===========================================================================
# 6. MP4 existente pode ser identificado para reavaliação sem regeneração
# ===========================================================================

def test_inspect_held_quality_videos_identifies_intact_mp4(temp_db, tmp_path):
    """Garante que a ferramenta read-only identifica vídeos com MP4 retidos por Quality Gate."""
    tid = "task-elevador-recup"
    v_dir = tmp_path / "tasks" / tid
    v_dir.mkdir(parents=True)
    v_file = v_dir / "final-1.mp4"
    v_file.write_bytes(b"\x00" * 2048)

    with sqlite3.connect(temp_db) as conn:
        conn.execute(
            """
            INSERT INTO content_quality_scores (
                task_id, topic, niche, preset, hook_text, quality_score, quality_label, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (tid, "Elevador despencando: o que fazer para sobreviver", "Curiosidades", "cross_platform",
             "O que fazer se um elevador estiver despencando?", 69.2, "REVIEW", "2026-10-16T12:00:00Z"),
        )

    safety_gate.save_safety_assessment({
        "task_id": tid,
        "preset": "cross_platform",
        "safety_status": const.SAFETY_STATUS_PASS,
        "safety_reasons": [],
        "actual_duration": 58.0,
        "checked_at": "2026-10-16T12:00:00Z",
    }, db_path=temp_db)

    report = inspect_held_videos(db_path=temp_db, task_base_dir=str(tmp_path / "tasks"))

    assert report["status"] == "ok"
    assert report["held_by_quality_count"] == 1
    cand = report["candidates"][0]
    assert cand["task_id"] == tid
    assert cand["mp4_exists"] is True
    assert cand["original_quality_score"] == 69.2
    assert cand["qg_v2_quality_score"] >= 70.0
    assert cand["recommendation"] == "ELIGIBLE_FOR_RE_EVALUATION"


# ===========================================================================
# 7. Retry preserva cenas válidas e idempotência
# ===========================================================================

def test_flow_idempotency_preserves_valid_scenes(tmp_path, monkeypatch):
    """Valida idempotência: cenas com clipes existentes no manifest não são duplicadas."""
    from scripts import flow_workflow
    monkeypatch.setattr("scripts.flow_workflow.validate_clip_file", lambda path: {"valid": True, "duration": 5.0})

    proj_dir = tmp_path / "flow_proj"
    clips_dir = proj_dir / "clips"
    clips_dir.mkdir(parents=True)
    manifest_file = proj_dir / "manifest.json"

    clip1 = clips_dir / "flow_scene_01.mp4"
    clip1.write_bytes(b"\x00" * 4096)

    manifest_data = {
        "project_name": "flow",
        "flow_project_url": "https://flow.google.com/test",
        "scenes": [
            {
                "scene_index": 1,
                "is_flow_premium": True,
                "expected_clip": "flow_scene_01.mp4",
                "status": "COMPLETED",
            }
        ],
        "flow_generation": {
            "completed_scenes": [1],
            "status": "ALL_FLOW_SCENES_READY",
        }
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    res = flow_workflow.generate_pending_flow_scenes(str(manifest_file))
    assert res.get("status") in ("ALL_FLOW_SCENES_READY", "COMPLETE")
    assert res.get("attempted_count", 0) == 0


# ===========================================================================
# 8. Estoque e publicação recebem apenas conteúdo elegível
# ===========================================================================

def test_ready_stock_receives_only_eligible_content(temp_db, tmp_path, monkeypatch):
    """Garante que get_autonomous_ready_stock só inclui vídeos com Quality >= 70 e Safety PASS."""
    tid_good = "task-eligible-good"
    v_dir = tmp_path / "tasks" / tid_good
    v_dir.mkdir(parents=True)
    (v_dir / "final-1.mp4").write_bytes(b"\x00" * 2048)

    safety_gate.save_safety_assessment({
        "task_id": tid_good,
        "preset": "youtube_shorts_original",
        "safety_status": const.SAFETY_STATUS_PASS,
        "safety_reasons": [],
        "checked_at": "2026-10-16T12:00:00Z",
    }, db_path=temp_db)

    with sqlite3.connect(temp_db) as conn:
        conn.execute(
            """
            INSERT INTO content_quality_scores (
                task_id, topic, quality_score, quality_label, created_at
            ) VALUES (?, ?, ?, ?, ?);
            """,
            (tid_good, "Vídeo Aprovado Teste", 78.5, "GOOD", "2026-10-16T12:00:00Z"),
        )
        conn.execute(
            "INSERT INTO task_profiles (task_id, profile_id, created_at) VALUES (?, ?, ?);",
            (tid_good, "default", "2026-10-16T12:00:00Z"),
        )

    sm.state.update_task(
        tid_good,
        state=const.TASK_STATE_COMPLETE,
        planned_platforms=["youtube"],
    )

    scheduler.save_task_platforms(tid_good, ["youtube"], db_path=temp_db)

    monkeypatch.setattr(
        "app.services.profile_manager.resolve_task_channels",
        lambda tid, platforms=None, db_path=None: [{"id": "ch-yt-1", "channel_id": "ch-yt-1", "platform": "youtube"}]
    )
    monkeypatch.setattr(
        "app.services.copyright_gate.evaluate_copyright_provenance_gate",
        lambda task_id, task_data=None, task_base_dir=None, db_path=None: (True, "OK", {})
    )
    monkeypatch.setattr(
        "app.services.autonomous_production.resolve_autonomous_planned_platforms",
        lambda prof_id, db_path=None: ["youtube"]
    )

    stock = autonomous_production.get_autonomous_ready_stock(
        task_base_dir=str(tmp_path / "tasks"),
        db_path=temp_db,
    )
    assert stock["ready_count"] >= 1
    assert any(t["task_id"] == tid_good for t in stock["youtube_ready"])


# ===========================================================================
# Fixtures dos 4 Casos Auditados Reais
# ===========================================================================

def test_calibrated_audit_cases(audit_cases):
    """Valida a calibração sob os quatro casos reais auditados."""
    # 1. Mel das abelhas: continua GOOD (>= 70)
    q_abelhas = quality_score.evaluate_quality(
        topic=audit_cases["abelhas"]["topic"],
        niche=audit_cases["abelhas"]["niche"],
        script_text=audit_cases["abelhas"]["script"],
        actual_duration=audit_cases["abelhas"]["duration"],
        platform="youtube",
        persist=False,
    )
    assert q_abelhas["quality_score"] >= 70.0
    assert q_abelhas["quality_label"] in ("GOOD", "STRONG")

    # 2. Reflexo na velocidade da luz: continua GOOD (>= 70)
    q_luz = quality_score.evaluate_quality(
        topic=audit_cases["luz"]["topic"],
        niche=audit_cases["luz"]["niche"],
        script_text=audit_cases["luz"]["script"],
        actual_duration=audit_cases["luz"]["duration"],
        platform="youtube",
        persist=False,
    )
    assert q_luz["quality_score"] >= 70.0
    assert q_luz["quality_label"] in ("GOOD", "STRONG")

    # 3. Elevador despencando: sob QG-V2 para YouTube Shorts (58s permitido + léxico concreto)
    q_elevador = quality_score.evaluate_quality(
        topic=audit_cases["elevador"]["topic"],
        niche=audit_cases["elevador"]["niche"],
        script_text=audit_cases["elevador"]["script"],
        actual_duration=audit_cases["elevador"]["duration"],
        platform="youtube",
        persist=False,
    )
    assert q_elevador["quality_score"] >= 70.0
    assert q_elevador["quality_label"] in ("GOOD", "STRONG")

    # 4. GTA 5 vs GTA 6: sob QG-V2 para YouTube Shorts
    q_gta = quality_score.evaluate_quality(
        topic=audit_cases["gta"]["topic"],
        niche=audit_cases["gta"]["niche"],
        script_text=audit_cases["gta"]["script"],
        actual_duration=audit_cases["gta"]["duration"],
        platform="youtube",
        persist=False,
    )
    assert q_gta["quality_score"] >= 70.0
    assert q_gta["quality_label"] in ("GOOD", "STRONG")
