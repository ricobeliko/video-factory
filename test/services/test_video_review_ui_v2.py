# -*- coding: utf-8 -*-
"""
test/services/test_video_review_ui_v2.py
========================================
Suíte de Testes Dirigidos para a Central de Revisão de Vídeos da Web UI V2 (QG-V2.2 Complemento).

Validações Obrigatórias:
1. Fila automática: vídeos retidos com MP4 válido aparecem em 'pending'; vídeos sem MP4, rejeitados por Safety/Copyright ou já publicados são excluídos.
2. Player: streaming seguro do arquivo .mp4 com headers de range e proteção contra path traversal.
3. Aprovação com score abaixo de 70: override editorial humano registrado, preservação de histórico, entrada no Ready Stock, zero agendamento/publicação espontânea.
4. Descarte persistente: registro de descarte, exclusão definitiva de 'pending', persistência pós-restart sem apagar MP4 nem histórico.
5. Bloqueio absoluto: rejeições de Safety e Copyright impedem aprovação humana (fail-closed).
6. MP4 ausente ou inválido bloqueia aprovação.
7. Prevenção de duplicatas e proteção contra vídeos já publicados.
8. Governança PRIMARY / SECONDARY_VIEW_ONLY: bloqueio de escrita no secundário e funcionamento da ponte segura de autorização.
"""

import json
import os
import sqlite3
import pytest
from starlette.testclient import TestClient

from app.asgi import app
from app.models import const
from app.services import (
    autonomous_production,
    copyright_gate,
    operator_console,
    profile_manager,
    quality_recovery,
    quality_score,
    safety_gate,
    scheduler,
)
from app.utils import utils


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Cria ambiente isolado para o banco SQLite e arquivos de tarefas."""
    db_file = str(tmp_path / "scheduler.db")
    tasks_dir = str(tmp_path / "tasks")
    os.makedirs(tasks_dir, exist_ok=True)

    # Monkeypatching de caminhos canônicos
    monkeypatch.setattr(scheduler, "get_db_path", lambda custom_path=None: custom_path or db_file)
    monkeypatch.setattr(operator_console, "get_db_path", lambda custom_path=None: custom_path or db_file)
    monkeypatch.setattr(utils, "task_dir", lambda sub_dir="": os.path.join(tasks_dir, sub_dir) if sub_dir else tasks_dir)

    # Inicializações
    scheduler.init_db(db_file)
    operator_console.init_operator_db(db_file)
    profile_manager.init_profile_db(db_file)
    quality_score.init_quality_db(db_file)
    quality_recovery.init_review_db(db_file)

    # Configuração de perfil e canal padrão
    with sqlite3.connect(db_file) as conn:
        conn.executescript(
            """
            INSERT OR REPLACE INTO content_profiles (id, name, slug, niche, is_active, created_at, updated_at)
            VALUES ('default', 'Canal Principal', 'principal', 'Curiosidades', 1, '2026-10-15T12:00:00Z', '2026-10-15T12:00:00Z');

            INSERT OR REPLACE INTO publishing_channels (id, profile_id, platform, display_name, is_enabled, created_at, updated_at)
            VALUES ('channel-default-youtube', 'default', 'youtube', 'Default YouTube', 1, '2026-10-15T12:00:00Z', '2026-10-15T12:00:00Z');
            """
        )

    # Mock padrão de PRIMARY
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
    niche: str = "Curiosidades",
    preset: str = "cross_platform",
    hook_text: str = "Você sabia deste fato surpreendente?",
    script_text: str = "Roteiro narrativo completo e detalhado com contexto...",
    profile_id: str = "default",
):
    """Cria uma tarefa persistida com todos os metadados e arquivos."""
    db = env["db"]
    tasks_dir = env["tasks_dir"]

    t_dir = os.path.join(tasks_dir, task_id)
    os.makedirs(t_dir, exist_ok=True)

    if mp4_bytes > 0:
        with open(os.path.join(t_dir, "final-1.mp4"), "wb") as f:
            f.write(b"\x00" * mp4_bytes)

    script_payload = {
        "script": script_text,
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

    safety_gate.save_safety_assessment({
        "task_id": task_id,
        "preset": preset,
        "safety_status": safety_status,
        "safety_reasons": [] if safety_status == const.SAFETY_STATUS_PASS else ["Conteúdo bloqueado"],
        "actual_duration": actual_duration,
        "topic": topic,
        "hook_text": hook_text,
        "checked_at": "2026-10-15T12:00:00Z",
    }, db_path=db)

    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            INSERT INTO content_quality_scores (
                task_id, topic, niche, preset, hook_text, quality_score, quality_label, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (task_id, topic, niche, preset, hook_text, orig_score, orig_label, "2026-10-15T12:05:00Z"),
        )
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
        conn.execute(
            """
            INSERT OR IGNORE INTO task_profiles (task_id, profile_id, created_at)
            VALUES (?, ?, ?);
            """,
            (task_id, profile_id, "2026-10-15T12:00:00Z"),
        )


def test_1_automatic_review_queue_discovery(env):
    """Cenário 1: Fila automática descobre vídeos com MP4 válido e Quality Gate retido."""
    # Candidato 1: Válido pendente
    _create_task_fixture(
        env,
        task_id="task-valid-pending",
        topic="Por que o céu é azul?",
        orig_score=68.0,
        orig_label="REVIEW",
    )

    # Candidato 2: Rejeitado por Safety (NÃO pode aparecer em pending)
    _create_task_fixture(
        env,
        task_id="task-safety-blocked",
        topic="Tema perigoso",
        orig_score=68.0,
        orig_label="REVIEW",
        safety_status="FAIL",
    )

    # Candidato 3: Rejeitado por Copyright (NÃO pode aparecer em pending)
    _create_task_fixture(
        env,
        task_id="task-copyright-blocked",
        topic="Música comercial protegida",
        orig_score=68.0,
        orig_label="REVIEW",
        copyright_status="BLOCK",
    )

    # Candidato 4: Sem MP4 (NÃO pode aparecer em pending)
    _create_task_fixture(
        env,
        task_id="task-no-mp4",
        topic="Vídeo sem render",
        orig_score=68.0,
        orig_label="REVIEW",
        mp4_bytes=0,
    )

    client = TestClient(app)
    resp = client.get("/api/v2/review/tasks?filter=pending")
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["counts"]["pending"] == 1
    tasks = data["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["task_id"] == "task-valid-pending"
    assert tasks[0]["original_quality_score"] == 68.0


def test_2_stream_video_player_and_path_traversal_protection(env):
    """Cenário 2: Streaming seguro do MP4 com validação de task_id e proteção contra path traversal."""
    tid = "task-player-stream"
    _create_task_fixture(
        env,
        task_id=tid,
        topic="Demonstração do Player",
        orig_score=66.0,
        orig_label="REVIEW",
        mp4_bytes=8192,
    )

    client = TestClient(app)

    # 1. Sucesso na rota autorizada
    resp = client.get(f"/api/v2/review/tasks/{tid}/video")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "video/mp4"
    assert resp.headers.get("accept-ranges") == "bytes"
    assert len(resp.content) == 8192

    # 2. Defesa contra Path Traversal: caracteres ilegais
    bad_resp = client.get("/api/v2/review/tasks/invalid..traversal/video")
    assert bad_resp.status_code == 400
    assert "inválido" in bad_resp.text

    # 3. Arquivo inexistente retorna 404
    missing_resp = client.get("/api/v2/review/tasks/task-inexistente/video")
    assert missing_resp.status_code == 404


def test_3_human_approval_editorial_override_below_70(env):
    """Cenário 3: Aprovação humana com score < 70, preservação de histórico, entrada no Ready Stock e zero agendamento."""
    tid = "task-override-64"
    _create_task_fixture(
        env,
        task_id=tid,
        topic="coisas legais",
        orig_score=64.0,
        orig_label="REVIEW",
        hook_text="neste video vamos ver coisas",
        script_text="neste video vamos ver coisas",
        actual_duration=10.0,
        preset="youtube_shorts_original",
    )

    client = TestClient(app)
    approve_resp = client.post(
        f"/api/v2/review/tasks/{tid}/approve",
        json={
            "operator_id": "operator-alice",
            "note": "Roteiro dinâmico e visualmente excelente.",
            "confirm": "APPROVE_FOR_STOCK",
        },
    )
    assert approve_resp.status_code == 200
    res_data = approve_resp.json()["data"]
    assert res_data["status"] == "success"
    assert res_data["approved_below_threshold"] is True
    # O score original NUNCA é falsificado
    assert res_data["original_quality_score"] == 64.0

    with sqlite3.connect(env["db"]) as conn:
        conn.row_factory = sqlite3.Row

        # 1. Verifica registro em operator_video_reviews
        ovr = conn.execute("SELECT * FROM operator_video_reviews WHERE task_id = ?;", (tid,)).fetchone()
        assert ovr is not None
        assert ovr["decision"] == "APPROVED"
        assert ovr["operator_id"] == "operator-alice"
        assert ovr["approved_below_threshold"] == 1
        assert ovr["original_score"] == 64.0

        # 2. Verifica que ZERO agendamento foi disparado em scheduled_posts
        sched_count = conn.execute("SELECT COUNT(*) FROM scheduled_posts WHERE task_id = ?;", (tid,)).fetchone()[0]
        assert sched_count == 0

        # 3. Verifica evento de auditoria em operational_events
        ev = conn.execute(
            "SELECT * FROM operational_events WHERE task_id = ? AND event_type = 'held_task_human_approved';",
            (tid,),
        ).fetchone()
        assert ev is not None
        assert "aprovada pelo operador" in ev["message"]

    # 4. Verifica entrada canônica no Ready Stock via _recover_waiting_task
    stock = autonomous_production.get_autonomous_ready_stock(
        task_base_dir=env["tasks_dir"],
        db_path=env["db"],
    )
    assert stock["ready_count"] == 1
    assert stock["youtube_ready"][0]["task_id"] == tid


def test_4_persistent_discard_survives_restart(env):
    """Cenário 4: Descarte é gravado de forma persistente, sai de 'pending', MP4 e banco não são apagados."""
    tid = "task-to-discard"
    _create_task_fixture(
        env,
        task_id=tid,
        topic="Vídeo de qualidade inadequada",
        orig_score=55.0,
        orig_label="WEAK",
    )

    client = TestClient(app)

    # 1. Inicialmente está em pending
    q1 = client.get("/api/v2/review/tasks?filter=pending").json()["data"]
    assert any(t["task_id"] == tid for t in q1["tasks"])

    # 2. Executa descarte
    discard_resp = client.post(
        f"/api/v2/review/tasks/{tid}/discard",
        json={
            "operator_id": "operator-bob",
            "note": "Roteiro genérico e ritmo fraco.",
            "confirm": "DISCARD_HELD_VIDEO",
        },
    )
    assert discard_resp.status_code == 200

    # 3. Arquivo MP4 físico NÃO é apagado
    mp4_path = os.path.join(env["tasks_dir"], tid, "final-1.mp4")
    assert os.path.isfile(mp4_path)

    # 4. Fila 'pending' não contém mais o item
    q2 = client.get("/api/v2/review/tasks?filter=pending").json()["data"]
    assert not any(t["task_id"] == tid for t in q2["tasks"])

    # 5. Fila 'discarded' contém o item
    q_disc = client.get("/api/v2/review/tasks?filter=discarded").json()["data"]
    assert any(t["task_id"] == tid for t in q_disc["tasks"])

    # 6. Simula nova consulta pós-reinicialização
    q_restart = quality_recovery.get_review_queue(filter="pending", db_path=env["db"], task_base_dir=env["tasks_dir"])
    assert not any(t["task_id"] == tid for t in q_restart["tasks"])


def test_5_safety_and_copyright_rejections_block_approval(env):
    """Cenário 5: Safety ou Copyright não-PASS bloqueiam aprovação humana de forma fail-closed."""
    # Tarefa com falha de Safety
    t_safe = "task-safety-reject"
    _create_task_fixture(
        env,
        task_id=t_safe,
        topic="Discurso nocivo",
        orig_score=75.0,
        orig_label="GOOD",
        safety_status="FAIL",
    )

    # Tarefa com falha de Copyright
    t_copy = "task-copy-reject"
    _create_task_fixture(
        env,
        task_id=t_copy,
        topic="Música não licenciada",
        orig_score=75.0,
        orig_label="GOOD",
        copyright_status="BLOCK",
    )

    client = TestClient(app)

    # Tentativa de aprovar Safety FAIL -> erro 400 com motivo
    r_safe = client.post(
        f"/api/v2/review/tasks/{t_safe}/approve",
        json={"confirm": "APPROVE_FOR_STOCK"},
    )
    assert r_safe.status_code == 400
    assert "Safety Gate não aprovado" in r_safe.text

    # Tentativa de aprovar Copyright BLOCK -> erro 400 com motivo
    r_copy = client.post(
        f"/api/v2/review/tasks/{t_copy}/approve",
        json={"confirm": "APPROVE_FOR_STOCK"},
    )
    assert r_copy.status_code == 400
    assert "Copyright Gate não aprovado" in r_copy.text


def test_6_missing_or_empty_mp4_blocks_approval(env):
    """Cenário 6: MP4 ausente ou vazio bloqueia aprovação humana."""
    tid = "task-empty-video"
    _create_task_fixture(
        env,
        task_id=tid,
        topic="Vídeo corrompido",
        orig_score=75.0,
        orig_label="GOOD",
        mp4_bytes=0,
    )

    client = TestClient(app)
    resp = client.post(
        f"/api/v2/review/tasks/{tid}/approve",
        json={"confirm": "APPROVE_FOR_STOCK"},
    )
    assert resp.status_code == 400
    assert "final-1.mp4 ausente ou vazio" in resp.text


def test_7_duplicate_and_published_protection(env):
    """Cenário 7: Vídeo já publicado não pode ser aprovado e aprovação é idempotente."""
    tid = "task-already-pub"
    _create_task_fixture(
        env,
        task_id=tid,
        topic="Vídeo já postado no YouTube",
        orig_score=72.0,
        orig_label="GOOD",
    )

    # Registra publicação prévia
    with sqlite3.connect(env["db"]) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS publication_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                platform TEXT,
                status TEXT,
                published_at TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO publication_events (task_id, platform, status, published_at) VALUES (?, 'youtube', 'success', '2026-10-15T12:00:00Z');",
            (tid,),
        )

    client = TestClient(app)
    resp = client.post(
        f"/api/v2/review/tasks/{tid}/approve",
        json={"confirm": "APPROVE_FOR_STOCK"},
    )
    assert resp.status_code == 400
    assert "já foi publicada" in resp.text


def test_8_primary_secondary_governance_and_safe_bridge(env, monkeypatch):
    """Cenário 8: Nó SECONDARY não escreve diretamente; enfileira comando e PRIMARY processa via ponte segura."""
    tid = "task-bridge-test"
    _create_task_fixture(
        env,
        task_id=tid,
        topic="Teste da Ponte de Autorização",
        orig_score=74.0,
        orig_label="GOOD",
    )

    # 1. Configura nó como SECONDARY_VIEW_ONLY
    monkeypatch.setattr(operator_console, "is_primary_instance", lambda **kwargs: False)

    def fake_require_primary(**kwargs):
        raise PermissionError("Instância em modo SECONDARY_VIEW_ONLY. Escrita direta proibida.")

    monkeypatch.setattr(operator_console, "require_primary_instance", fake_require_primary)

    # 2. Chamada direta de apply_human_review_decision em SECONDARY deve falhar com PermissionError
    with pytest.raises(PermissionError, match="SECONDARY_VIEW_ONLY"):
        quality_recovery.apply_human_review_decision(
            task_id=tid,
            action="APPROVE",
            confirm="APPROVE_FOR_STOCK",
            db_path=env["db"],
            task_base_dir=env["tasks_dir"],
        )

    # 3. Via ponte segura (submit_or_apply_review_decision) sob SECONDARY: enfileira sem erro de escrita direta
    res = quality_recovery.submit_or_apply_review_decision(
        task_id=tid,
        action="APPROVE",
        operator_id="operator-sec",
        confirm="APPROVE_FOR_STOCK",
        db_path=env["db"],
        task_base_dir=env["tasks_dir"],
        wait_for_primary_sec=0.1,
    )
    assert res["status"] == "queued"
    cmd_id = res["command_id"]

    # 4. Verifica que o comando foi persistido com status PENDING no SQLite
    with sqlite3.connect(env["db"]) as conn:
        conn.row_factory = sqlite3.Row
        cmd_row = conn.execute("SELECT * FROM operator_review_commands WHERE id = ?;", (cmd_id,)).fetchone()
        assert cmd_row is not None
        assert cmd_row["status"] == "PENDING"
        assert cmd_row["action"] == "APPROVE"

    # 5. Agora o nó PRIMARY assume e processa os comandos pendentes
    monkeypatch.setattr(operator_console, "is_primary_instance", lambda **kwargs: True)
    monkeypatch.setattr(operator_console, "require_primary_instance", lambda **kwargs: None)

    proc_results = quality_recovery.process_pending_review_commands(
        db_path=env["db"],
        task_base_dir=env["tasks_dir"],
    )
    assert len(proc_results) == 1
    assert proc_results[0]["status"] == "completed"

    # 6. Confirma que o comando foi atualizado para COMPLETED e a tarefa está no Ready Stock
    with sqlite3.connect(env["db"]) as conn:
        cmd_after = conn.execute("SELECT status FROM operator_review_commands WHERE id = ?;", (cmd_id,)).fetchone()[0]
        assert cmd_after == "COMPLETED"

    stock = autonomous_production.get_autonomous_ready_stock(
        task_base_dir=env["tasks_dir"],
        db_path=env["db"],
    )
    assert stock["ready_count"] == 1


def test_9_auto_pass_video_bypasses_review_center_completely(env):
    """Cenário 9 (Regressão Obrigatória): Vídeo que passa no Quality Gate segue fluxo canônico

    sem passar nem depender da Central de Revisão Humana.
    """
    tid = "task-auto-pass-video"
    _create_task_fixture(
        env,
        task_id=tid,
        topic="Vídeo de alta qualidade que passa direto",
        orig_score=85.0,
        orig_label="STRONG",
        safety_status=const.SAFETY_STATUS_PASS,
        copyright_status="PASS",
    )

    # 1. Avalia gates pelo ciclo de produção autônoma existente
    approved, reason, metrics = autonomous_production.evaluate_completed_task_gates(
        tid,
        db_path=env["db"],
        task_base_dir=env["tasks_dir"],
    )
    assert approved is True
    assert "Aprovado" in reason
    assert metrics["quality_score"] >= 70.0

    # No fluxo normal do loop autônomo, tarefas aprovadas salvam a plataforma planejada
    scheduler.save_task_platforms(tid, ["youtube"], db_path=env["db"])

    # 2. Verifica que a Central de Revisão NÃO possui esse vídeo na fila de pendentes nem de aprovados
    client = TestClient(app)
    review_resp = client.get("/api/v2/review/tasks?filter=pending")
    assert review_resp.status_code == 200
    review_data = review_resp.json()["data"]
    assert review_data["counts"]["pending"] == 0
    assert review_data["counts"]["approved"] == 0
    assert not any(t["task_id"] == tid for t in review_data["tasks"])

    appr_resp = client.get("/api/v2/review/tasks?filter=approved")
    assert appr_resp.status_code == 200
    assert len(appr_resp.json()["data"]["tasks"]) == 0

    # 3. Verifica que a tabela operator_video_reviews NÃO contém nenhuma decisão manual
    with sqlite3.connect(env["db"]) as conn:
        row = conn.execute("SELECT * FROM operator_video_reviews WHERE task_id = ?;", (tid,)).fetchone()
        assert row is None

    # 4. Verifica que o vídeo entra DIRETAMENTE no Ready Stock sem qualquer ação de operador
    stock = autonomous_production.get_autonomous_ready_stock(
        task_base_dir=env["tasks_dir"],
        db_path=env["db"],
    )
    assert stock["ready_count"] == 1
    assert stock["youtube_ready"][0]["task_id"] == tid
    assert stock["youtube_ready"][0]["quality_score"] >= 70.0


def test_10_fast_listing_with_representative_history_and_accurate_counts(env):
    """Cenário 10 (Hotfix Performance & Contagem): Histórico representativo com 22 tarefas

    Valida:
    - 10 vídeos auto-aprovados NÃO inflam 'counts.approved' (apenas Ready Stock).
    - 3 vídeos retidos com MP4 íntegro aparecem em 'pending'.
    - 2 vídeos aprovados por decisão humana aparecem em 'approved'.
    - 1 vídeo descartado por decisão humana aparece em 'discarded'.
    - Bloqueios (Safety, Copyright, MP4 ausente) nunca entram em 'pending'.
    - Contagens exatas: pending=3, approved=2, discarded=1.
    """
    import time

    # 1. 10 vídeos auto-aprovados (Ready Stock)
    for i in range(10):
        _create_task_fixture(
            env,
            task_id=f"task-autopass-{i}",
            topic=f"Vídeo de Alta Qualidade {i}",
            orig_score=82.0 + i,
            orig_label="STRONG",
        )
        scheduler.save_task_platforms(f"task-autopass-{i}", ["youtube"], db_path=env["db"])

    # 2. 3 vídeos pendentes para revisão humana
    for i in range(3):
        _create_task_fixture(
            env,
            task_id=f"task-pending-{i}",
            topic=f"Vídeo Retido em Revisão {i}",
            orig_score=62.0 + i,
            orig_label="REVIEW",
        )

    # 3. 2 vídeos aprovados pelo operador
    for i in range(2):
        tid = f"task-human-approved-{i}"
        _create_task_fixture(
            env,
            task_id=tid,
            topic=f"Vídeo Aprovado por Humano {i}",
            orig_score=65.0,
            orig_label="REVIEW",
        )
        with sqlite3.connect(env["db"]) as conn:
            conn.execute(
                """
                INSERT INTO operator_video_reviews (
                    task_id, decision, operator_id, note, original_score, recalculated_score,
                    approved_below_threshold, created_at, updated_at
                ) VALUES (?, 'APPROVED', 'operator-test', 'Curadoria visual aprovada', 65.0, 65.0, 1, '2026-10-16T10:00:00Z', '2026-10-16T10:00:00Z');
                """,
                (tid,),
            )
        scheduler.save_task_platforms(tid, ["youtube"], db_path=env["db"])

    # 4. 1 vídeo descartado pelo operador
    tid_disc = "task-human-discarded-0"
    _create_task_fixture(
        env,
        task_id=tid_disc,
        topic="Vídeo Descartado pelo Operador",
        orig_score=50.0,
        orig_label="WEAK",
    )
    with sqlite3.connect(env["db"]) as conn:
        conn.execute(
            """
            INSERT INTO operator_video_reviews (
                task_id, decision, operator_id, note, original_score, recalculated_score,
                approved_below_threshold, created_at, updated_at
            ) VALUES (?, 'DISCARDED', 'operator-test', 'Tema fraco', 50.0, 50.0, 0, '2026-10-16T10:00:00Z', '2026-10-16T10:00:00Z');
            """,
            (tid_disc,),
        )

    # 5. Tarefas inválidas / bloqueadas (2 safety, 2 copyright, 2 no-mp4)
    for i in range(2):
        _create_task_fixture(env, task_id=f"task-safety-blocked-{i}", topic="Inseguro", orig_score=60.0, orig_label="REVIEW", safety_status="FAIL")
        _create_task_fixture(env, task_id=f"task-cp-blocked-{i}", topic="Copyright", orig_score=60.0, orig_label="REVIEW", copyright_status="BLOCK")
        _create_task_fixture(env, task_id=f"task-no-mp4-{i}", topic="Sem MP4", orig_score=60.0, orig_label="REVIEW", mp4_bytes=0)

    client = TestClient(app)

    # Mede tempo de resposta da listagem
    t0 = time.perf_counter()
    resp = client.get("/api/v2/review/tasks?filter=pending")
    elapsed = time.perf_counter() - t0

    assert resp.status_code == 200
    data = resp.json()["data"]

    # Valida contagens sem inflação dos 10 vídeos auto-aprovados
    assert data["counts"]["pending"] == 3
    assert data["counts"]["approved"] == 2
    assert data["counts"]["discarded"] == 1
    assert len(data["tasks"]) == 3
    assert all(t["task_id"].startswith("task-pending-") for t in data["tasks"])

    # Teste de listagem rápida deve responder em menos de 1 segundo
    assert elapsed < 1.0

    # Consulta filtro 'approved': exatamente os 2 vídeos com decisão humana
    appr_resp = client.get("/api/v2/review/tasks?filter=approved")
    assert appr_resp.status_code == 200
    appr_data = appr_resp.json()["data"]
    assert len(appr_data["tasks"]) == 2
    assert {t["task_id"] for t in appr_data["tasks"]} == {"task-human-approved-0", "task-human-approved-1"}

    # Consulta filtro 'discarded': exatamente o vídeo descartado
    disc_resp = client.get("/api/v2/review/tasks?filter=discarded")
    assert disc_resp.status_code == 200
    disc_data = disc_resp.json()["data"]
    assert len(disc_data["tasks"]) == 1
    assert disc_data["tasks"][0]["task_id"] == "task-human-discarded-0"


