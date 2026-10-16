# -*- coding: utf-8 -*-
"""
test/services/test_quality_recovery_v2_2.py
============================================
Suíte de Testes Dirigidos para o QG-V2.2 (Recuperação Segura de Vídeos Retidos).

Cobre os 10 cenários obrigatórios:
1. GTA recuperável (b800744a-b57d-47e1-a1cf-a35df380091b: 63.3 REVIEW -> >=70.0 GOOD, MP4 válido).
2. Elevador recuperável (d6daebe0-69fb-414e-8409-7ae955ea749e: 69.2 REVIEW -> >=85.0 STRONG, MP4 válido).
3. Quality abaixo de 70 continua bloqueado (score QG-V2 < 70 -> NEEDS_REVIEW).
4. Safety rejeitado (safety_status = BLOCK -> BLOCKED).
5. Copyright rejeitado (copyright_status = BLOCK -> BLOCKED).
6. MP4 ausente ou inválido (0 bytes ou inexistente -> BLOCKED).
7. Vídeo já publicado (publication_events success -> ALREADY_PUBLISHED).
8. Vídeo já agendado (scheduled_posts scheduled -> ALREADY_SCHEDULED).
9. Aplicação repetida sem duplicação (idempotência -> ALREADY_STOCKED).
10. Preservação de histórico e ausência de publicação automática (append-only, scheduled_posts vazio).
"""

import json
import os
import sqlite3
import pytest

from app.models import const
from app.services import (
    autonomous_production,
    operator_console,
    profile_manager,
    quality_recovery,
    quality_score,
    safety_gate,
    scheduler,
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Configura ambiente temporário isolado para SQLite e storage."""
    db_file = str(tmp_path / "test_recovery.db")
    tasks_dir = str(tmp_path / "tasks")
    os.makedirs(tasks_dir, exist_ok=True)

    # Inicializa bancos
    scheduler.init_db(db_file)
    quality_score.init_quality_db(db_file)
    profile_manager.init_profile_db(db_file)
    operator_console.init_operator_db(db_file)

    # Cria perfil padrão ativo e canal YouTube habilitado para o Scheduler/Ready Stock
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO content_profiles (id, name, slug, niche, is_active, created_at, updated_at)
            VALUES ('default', 'Default Profile', 'default', 'Geral', 1, '2026-10-15T12:00:00Z', '2026-10-15T12:00:00Z');
            """
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO publishing_channels (id, profile_id, platform, display_name, is_enabled, created_at, updated_at)
            VALUES ('channel-default-youtube', 'default', 'youtube', 'Default YouTube', 1, '2026-10-15T12:00:00Z', '2026-10-15T12:00:00Z');
            """
        )

    # Mock de instância PRIMARY
    monkeypatch.setattr(operator_console, "require_primary_instance", lambda **kwargs: None)
    monkeypatch.setattr(operator_console, "is_primary_instance", lambda **kwargs: True)

    return {
        "db": db_file,
        "tasks_dir": tasks_dir,
    }


def _create_task_fixture(
    env,
    task_id: str,
    topic: str,
    orig_score: float,
    orig_label: str,
    safety_status: str = const.SAFETY_STATUS_PASS,
    copyright_status: str = "PASS",
    actual_duration: float = 58.0,
    mp4_bytes: int = 4096,
    niche: str = "Games",
    preset: str = "cross_platform",
    hook_text: str = "Você percebeu essa diferença chocante?",
    script_text: str = "Roteiro narrativo completo com mais de cem palavras detalhando a evolução gráfica...",
    profile_id: str = "default",
):
    """Cria uma fixture completa no SQLite e no disco para um task_id."""
    db = env["db"]
    tasks_dir = env["tasks_dir"]

    # 1. Diretório e arquivos
    t_dir = os.path.join(tasks_dir, task_id)
    os.makedirs(t_dir, exist_ok=True)

    if mp4_bytes > 0:
        with open(os.path.join(t_dir, "final-1.mp4"), "wb") as f:
            f.write(b"\x00" * mp4_bytes)

    script_payload = {
        "script": script_text,
        "material_sources": [
            {
                "provider": "pexels",
                "asset_id": "asset-123",
                "local_file": "vid-123.mp4",
                "source_page": "https://www.pexels.com/video/123/",
                "search_term": "game city",
                "duration": 10,
            }
        ],
        "asset_provenance": {
            "visual_clips": [
                {
                    "provider": "pexels",
                    "asset_id": "asset-123",
                    "local_file": "vid-123.mp4",
                    "provenance_status": "PEXELS_FREE_STOCK",
                }
            ],
            "bgm": {
                "enabled": False,
                "provenance_status": "SAFE_NO_BGM",
            },
        },
        "params": {
            "video_subject": topic,
            "video_script": script_text,
            "niche": niche,
            "preset": preset,
            "actual_duration": actual_duration,
            "profile_id": profile_id,
            "bgm_type": "none",
        },
    }
    with open(os.path.join(t_dir, "script.json"), "w", encoding="utf-8") as f:
        json.dump(script_payload, f)

    # 2. monetization_safety
    safety_gate.save_safety_assessment({
        "task_id": task_id,
        "preset": preset,
        "safety_status": safety_status,
        "safety_reasons": [] if safety_status == const.SAFETY_STATUS_PASS else ["Violou diretriz"],
        "actual_duration": actual_duration,
        "topic": topic,
        "hook_text": hook_text,
        "checked_at": "2026-10-15T12:00:00Z",
    }, db_path=db)

    # 3. content_quality_scores
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            INSERT INTO content_quality_scores (
                task_id, topic, niche, preset, hook_text, quality_score, quality_label, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (task_id, topic, niche, preset, hook_text, orig_score, orig_label, "2026-10-15T12:05:00Z"),
        )

        # 4. copyright_provenance
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS copyright_provenance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                status TEXT,
                reasons_json TEXT,
                created_at TEXT
            );
            """
        )
        conn.execute(
            """
            INSERT INTO copyright_provenance (task_id, status, reasons_json, created_at)
            VALUES (?, ?, ?, ?);
            """,
            (task_id, copyright_status, "[]", "2026-10-15T12:06:00Z"),
        )

        # 5. task_profiles
        conn.execute(
            """
            INSERT OR IGNORE INTO task_profiles (task_id, profile_id, created_at)
            VALUES (?, ?, ?);
            """,
            (task_id, profile_id, "2026-10-15T12:00:00Z"),
        )


def test_1_gta_candidate_recoverable(env):
    """Cenário 1: GTA 5 vs GTA 6 recalculado >= 70.0 GOOD e recuperado com sucesso para Ready Stock."""
    tid = "b800744a-b57d-47e1-a1cf-a35df380091b"
    _create_task_fixture(
        env,
        task_id=tid,
        topic="GTA 5 vs GTA 6: O que a Rockstar realmente escondeu no novo trailer?",
        orig_score=63.3,
        orig_label="REVIEW",
        actual_duration=58.0,
        niche="Games",
    )

    # Dry-run
    cand = quality_recovery.inspect_single_held_task(tid, db_path=env["db"], task_base_dir=env["tasks_dir"])
    assert cand["classification"] == quality_recovery.CLASS_ELIGIBLE
    assert cand["qg_v2_quality_score"] >= 70.0
    assert cand["qg_v2_quality_label"] in ("GOOD", "STRONG")
    assert cand["mp4_exists"] is True

    # Apply com sucesso
    res = quality_recovery.recover_held_quality_task(
        tid,
        confirm="RECOVER_HELD_VIDEOS",
        db_path=env["db"],
        task_base_dir=env["tasks_dir"],
    )
    assert res["status"] == "success"
    assert res["qg_v2_quality_score"] >= 70.0

    # Verifica entrada no Ready Stock
    stock = autonomous_production.get_autonomous_ready_stock(
        task_base_dir=env["tasks_dir"],
        db_path=env["db"],
    )
    assert stock["ready_count"] == 1
    assert any(t["task_id"] == tid for t in stock["youtube_ready"])


def test_2_elevator_candidate_recoverable(env):
    """Cenário 2: Elevador despencando recalculado >= 85.0 STRONG e recuperado para Ready Stock."""
    tid = "d6daebe0-69fb-414e-8409-7ae955ea749e"
    _create_task_fixture(
        env,
        task_id=tid,
        topic="Elevador despencando: o que fazer para sobreviver a uma queda de prédio?",
        orig_score=69.2,
        orig_label="REVIEW",
        actual_duration=55.0,
        niche="Curiosidades",
        hook_text="Se o elevador começar a despencar, pular no último segundo funciona?",
    )

    # Dry-run
    cand = quality_recovery.inspect_single_held_task(tid, db_path=env["db"], task_base_dir=env["tasks_dir"])
    assert cand["classification"] == quality_recovery.CLASS_ELIGIBLE
    assert cand["qg_v2_quality_score"] >= 85.0
    assert cand["qg_v2_quality_label"] == "STRONG"

    # Apply
    res = quality_recovery.recover_held_quality_task(
        tid,
        confirm="RECOVER_HELD_VIDEOS",
        db_path=env["db"],
        task_base_dir=env["tasks_dir"],
    )
    assert res["status"] == "success"

    stock = autonomous_production.get_autonomous_ready_stock(
        task_base_dir=env["tasks_dir"],
        db_path=env["db"],
    )
    assert stock["ready_count"] == 1


def test_3_quality_below_70_remains_blocked(env):
    """Cenário 3: Roteiro com penalidade de repetição e duração que pontua < 70 é NEEDS_REVIEW e rejeitado no apply."""
    tid = "task-weak-score"
    # Popula histórico prévio com tema idêntico para disparar penalidade máxima de repetição
    safety_gate.save_safety_assessment({
        "task_id": "task-prev-identical",
        "preset": "youtube_shorts_original",
        "safety_status": const.SAFETY_STATUS_PASS,
        "actual_duration": 10.0,
        "topic": "Dilema moral e o existencialismo abstrato da mente",
        "hook_text": "Você já pensou nisso?",
        "checked_at": "2026-10-15T10:00:00Z",
    }, db_path=env["db"])

    _create_task_fixture(
        env,
        task_id=tid,
        topic="Dilema moral e o existencialismo abstrato da mente",
        orig_score=45.0,
        orig_label="WEAK",
        hook_text="Você já pensou nisso?",
        script_text="Texto puramente abstrato sobre a alma, mente e consciência sem elementos concretos.",
        actual_duration=10.0,  # Duração muito curta (< 30s)
    )

    cand = quality_recovery.inspect_single_held_task(tid, db_path=env["db"], task_base_dir=env["tasks_dir"])
    assert cand["classification"] == quality_recovery.CLASS_NEEDS_REVIEW
    assert cand["qg_v2_quality_score"] < 70.0

    with pytest.raises(ValueError, match="não é elegível para recuperação"):
        quality_recovery.recover_held_quality_task(
            tid,
            confirm="RECOVER_HELD_VIDEOS",
            db_path=env["db"],
            task_base_dir=env["tasks_dir"],
        )


def test_4_safety_rejected_blocks_recovery(env):
    """Cenário 4: Safety Gate em BLOCK impede recuperação e classifica como BLOCKED."""
    tid = "task-safety-blocked"
    _create_task_fixture(
        env,
        task_id=tid,
        topic="Como invadir sistemas e quebrar senhas alheias",
        orig_score=75.0,
        orig_label="GOOD",
        safety_status=const.SAFETY_STATUS_BLOCK,
    )

    cand = quality_recovery.inspect_single_held_task(tid, db_path=env["db"], task_base_dir=env["tasks_dir"])
    assert cand["classification"] == quality_recovery.CLASS_BLOCKED
    assert "Safety Gate não aprovado" in cand["reason"]

    with pytest.raises(ValueError, match="não é elegível para recuperação"):
        quality_recovery.recover_held_quality_task(
            tid,
            confirm="RECOVER_HELD_VIDEOS",
            db_path=env["db"],
            task_base_dir=env["tasks_dir"],
        )


def test_5_copyright_rejected_blocks_recovery(env):
    """Cenário 5: Copyright Gate em BLOCK impede recuperação e classifica como BLOCKED."""
    tid = "task-copyright-blocked"
    _create_task_fixture(
        env,
        task_id=tid,
        topic="GTA 5 gameplay com música comercial protegida",
        orig_score=75.0,
        orig_label="GOOD",
        copyright_status="BLOCK",
    )

    cand = quality_recovery.inspect_single_held_task(tid, db_path=env["db"], task_base_dir=env["tasks_dir"])
    assert cand["classification"] == quality_recovery.CLASS_BLOCKED
    assert "Copyright Gate não aprovado" in cand["reason"]

    with pytest.raises(ValueError, match="não é elegível para recuperação"):
        quality_recovery.recover_held_quality_task(
            tid,
            confirm="RECOVER_HELD_VIDEOS",
            db_path=env["db"],
            task_base_dir=env["tasks_dir"],
        )


def test_6_mp4_missing_or_empty_blocks_recovery(env):
    """Cenário 6: MP4 inexistente ou com 0 bytes é classificado como BLOCKED."""
    tid = "task-no-mp4"
    _create_task_fixture(
        env,
        task_id=tid,
        topic="GTA 5 sem arquivo de vídeo final",
        orig_score=65.0,
        orig_label="REVIEW",
        mp4_bytes=0,  # Zero bytes
    )

    cand = quality_recovery.inspect_single_held_task(tid, db_path=env["db"], task_base_dir=env["tasks_dir"])
    assert cand["classification"] == quality_recovery.CLASS_BLOCKED
    assert "Arquivo final-1.mp4 ausente ou vazio" in cand["reason"]

    with pytest.raises(ValueError, match="não é elegível para recuperação"):
        quality_recovery.recover_held_quality_task(
            tid,
            confirm="RECOVER_HELD_VIDEOS",
            db_path=env["db"],
            task_base_dir=env["tasks_dir"],
        )


def test_7_video_already_published_cannot_be_recovered(env):
    """Cenário 7: Vídeo já publicado no YouTube é classificado como ALREADY_PUBLISHED e rejeitado no apply."""
    tid = "task-already-pub"
    _create_task_fixture(
        env,
        task_id=tid,
        topic="GTA 5 já publicado com sucesso",
        orig_score=68.0,
        orig_label="REVIEW",
    )

    # Insere evento de publicação
    with sqlite3.connect(env["db"]) as conn:
        conn.execute(
            """
            INSERT INTO publication_events (
                task_id, platform, status, external_id, published_at
            ) VALUES (?, ?, ?, ?, ?);
            """,
            (tid, "youtube", "success", "yt-video-123", "2026-10-15T14:00:00Z"),
        )

    cand = quality_recovery.inspect_single_held_task(tid, db_path=env["db"], task_base_dir=env["tasks_dir"])
    assert cand["classification"] == quality_recovery.CLASS_ALREADY_PUBLISHED

    with pytest.raises(ValueError, match="já foi publicada com sucesso"):
        quality_recovery.recover_held_quality_task(
            tid,
            confirm="RECOVER_HELD_VIDEOS",
            db_path=env["db"],
            task_base_dir=env["tasks_dir"],
        )


def test_8_video_already_scheduled_cannot_be_recovered(env):
    """Cenário 8: Vídeo já agendado no Scheduler é classificado como ALREADY_SCHEDULED e rejeitado no apply."""
    tid = "task-already-sched"
    _create_task_fixture(
        env,
        task_id=tid,
        topic="GTA 5 já presente no Scheduler",
        orig_score=68.0,
        orig_label="REVIEW",
    )

    with sqlite3.connect(env["db"]) as conn:
        conn.execute(
            """
            INSERT INTO scheduled_posts (
                task_id, platform, status, scheduled_at, profile_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?);
            """,
            (tid, "youtube", "scheduled", "2026-10-17T18:00:00Z", "default", "2026-10-15T14:00:00Z"),
        )

    cand = quality_recovery.inspect_single_held_task(tid, db_path=env["db"], task_base_dir=env["tasks_dir"])
    assert cand["classification"] == quality_recovery.CLASS_ALREADY_SCHEDULED

    with pytest.raises(ValueError, match="já está agendada ou em processamento"):
        quality_recovery.recover_held_quality_task(
            tid,
            confirm="RECOVER_HELD_VIDEOS",
            db_path=env["db"],
            task_base_dir=env["tasks_dir"],
        )


def test_9_repeated_application_idempotent_no_duplication(env):
    """Cenário 9: Aplicação repetida em tarefa já recuperada retorna ALREADY_STOCKED sem duplicação."""
    tid = "task-idempotent"
    _create_task_fixture(
        env,
        task_id=tid,
        topic="GTA 5 vs GTA 6: Teste de Idempotência Operacional",
        orig_score=63.0,
        orig_label="REVIEW",
    )

    # Primeira recuperação
    res1 = quality_recovery.recover_held_quality_task(
        tid,
        confirm="RECOVER_HELD_VIDEOS",
        db_path=env["db"],
        task_base_dir=env["tasks_dir"],
    )
    assert res1["status"] == "success"

    # Conta linhas após primeira aplicação
    with sqlite3.connect(env["db"]) as conn:
        count_cqs_1 = conn.execute("SELECT COUNT(*) FROM content_quality_scores WHERE task_id = ?;", (tid,)).fetchone()[0]
        count_tp_1 = conn.execute("SELECT COUNT(*) FROM task_platforms WHERE task_id = ?;", (tid,)).fetchone()[0]

    assert count_cqs_1 == 2  # Original (63.0) + Recuperado (QG-V2 >= 70.0)
    assert count_tp_1 == 1   # 'youtube'

    # Segunda recuperação (deve ser ALREADY_STOCKED sem inserir nada)
    res2 = quality_recovery.recover_held_quality_task(
        tid,
        confirm="RECOVER_HELD_VIDEOS",
        db_path=env["db"],
        task_base_dir=env["tasks_dir"],
    )
    assert res2["status"] == "already_stocked"

    # Conta linhas novamente (deve ser IDÊNTICA)
    with sqlite3.connect(env["db"]) as conn:
        count_cqs_2 = conn.execute("SELECT COUNT(*) FROM content_quality_scores WHERE task_id = ?;", (tid,)).fetchone()[0]
        count_tp_2 = conn.execute("SELECT COUNT(*) FROM task_platforms WHERE task_id = ?;", (tid,)).fetchone()[0]

    assert count_cqs_2 == count_cqs_1
    assert count_tp_2 == count_tp_1


def test_10_preserves_history_and_no_automatic_publication(env):
    """Cenário 10: Preserva histórico de score antigo, registra evento de auditoria e NÃO agenda/publica."""
    tid = "task-history-audit"
    _create_task_fixture(
        env,
        task_id=tid,
        topic="GTA 5 vs GTA 6: Preservação de Histórico Canônico",
        orig_score=63.3,
        orig_label="REVIEW",
    )

    # Recupera tarefa
    quality_recovery.recover_held_quality_task(
        tid,
        confirm="RECOVER_HELD_VIDEOS",
        db_path=env["db"],
        task_base_dir=env["tasks_dir"],
    )

    with sqlite3.connect(env["db"]) as conn:
        conn.row_factory = sqlite3.Row

        # 1. Preservação de histórico em content_quality_scores
        rows = conn.execute(
            "SELECT quality_score, quality_label, created_at FROM content_quality_scores WHERE task_id = ? ORDER BY id ASC;",
            (tid,),
        ).fetchall()
        assert len(rows) == 2
        # Registro antigo preservado
        assert rows[0]["quality_score"] == 63.3
        assert rows[0]["quality_label"] == "REVIEW"
        # Registro novo adicionado
        assert rows[1]["quality_score"] >= 70.0
        assert rows[1]["quality_label"] in ("GOOD", "STRONG")

        # 2. ZERO agendamento automático em scheduled_posts
        sched_rows = conn.execute("SELECT COUNT(*) FROM scheduled_posts WHERE task_id = ?;", (tid,)).fetchone()[0]
        assert sched_rows == 0

        # 3. ZERO publicação em publication_events
        pub_rows = conn.execute("SELECT COUNT(*) FROM publication_events WHERE task_id = ?;", (tid,)).fetchone()[0]
        assert pub_rows == 0

        # 4. Evento de auditoria registrado em operational_events
        ev = conn.execute(
            "SELECT * FROM operational_events WHERE task_id = ? AND event_type = 'held_task_quality_recovered';",
            (tid,),
        ).fetchone()
        assert ev is not None
        assert "retida recuperada para o Ready Stock" in ev["message"]
        meta = json.loads(ev["metadata_json"])
        assert meta["original_quality_score"] == 63.3
        assert meta["qg_v2_quality_score"] >= 70.0

    # 5. Confirmar que a tarefa é reconhecida pelo Ready Stock
    stock = autonomous_production.get_autonomous_ready_stock(
        task_base_dir=env["tasks_dir"],
        db_path=env["db"],
    )
    assert stock["ready_count"] == 1
    assert stock["youtube_ready"][0]["task_id"] == tid
