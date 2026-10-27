"""test/services/test_production_diagnostics.py
=============================================
Testes direcionados para o serviço de Diagnósticos de Produção (Missão SIS3).
- Valida os 7 detectores estruturados (incluindo os 4 incidentes reais de 27/10)
- Garante comportamento estrito somente leitura (mode=ro, zero gravações)
- Valida formatação estável (códigos, severidades, evidências, ações sugeridas)
- Garante que THROTTLED_NORMAL nunca vire warning/critical
- Garante que dados ausentes sejam null/UNKNOWN e motivos desconhecidos fiquem crus
- Valida endpoint HTTP GET /api/v2/diagnostics/overview
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.models import const
from app.services import (
    autonomous_production,
    operator_console,
    production_diagnostics,
    production_overview,
    profile_manager,
    quality_score,
    safety_gate,
    scheduler,
)


def _create_synthetic_test_db(db_path: str) -> None:
    """Cria banco SQLite com esquema mínimo necessário para testes do diagnóstico."""
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS content_profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                slug TEXT,
                niche TEXT,
                language TEXT,
                region TEXT,
                default_preset TEXT,
                growth_mode TEXT,
                is_active INTEGER DEFAULT 1,
                settings_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_profiles (
                task_id TEXT PRIMARY KEY,
                profile_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS operational_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                component TEXT NOT NULL,
                severity TEXT NOT NULL,
                event_type TEXT NOT NULL,
                task_id TEXT,
                message TEXT NOT NULL,
                metadata_json TEXT
            );

            CREATE TABLE IF NOT EXISTS instance_locks (
                lock_key TEXT PRIMARY KEY,
                node_id TEXT NOT NULL,
                node_name TEXT NOT NULL,
                hostname TEXT NOT NULL,
                pid INTEGER NOT NULL,
                status TEXT NOT NULL,
                last_heartbeat TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS monetization_safety (
                task_id TEXT PRIMARY KEY,
                topic TEXT,
                preset TEXT NOT NULL,
                narrative_structure TEXT,
                word_count INTEGER,
                estimated_duration REAL,
                actual_duration REAL,
                safety_status TEXT NOT NULL,
                safety_reasons TEXT,
                hook_text TEXT,
                cta_text TEXT,
                checked_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS content_quality_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                trend_id TEXT,
                topic TEXT NOT NULL,
                quality_score REAL NOT NULL,
                quality_label TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS scheduled_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                scheduled_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'planned',
                created_at TEXT NOT NULL,
                profile_id TEXT
            );

            CREATE TABLE IF NOT EXISTS autopilot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS publication_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                status TEXT NOT NULL,
                published_at TEXT,
                metadata_json TEXT
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_detector_task_stuck_after_render_real_case_e9630f19():
    """Reproduz caso real e9630f19: vídeo final existe, Safety PASS, sem quality score, fora de agendamento."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = os.path.join(tmp_dir, "test_diag.db")
        tasks_dir = os.path.join(tmp_dir, "tasks")
        _create_synthetic_test_db(db_file)

        now = datetime(2026, 10, 27, 16, 0, 0, tzinfo=timezone.utc)
        now_iso = now.isoformat()
        stuck_time_iso = (now - timedelta(minutes=45)).isoformat()

        # Cria pasta e arquivo de vídeo final
        task_id = "e9630f19"
        task_path = os.path.join(tasks_dir, task_id)
        os.makedirs(task_path, exist_ok=True)
        with open(os.path.join(task_path, "final-1.mp4"), "wb") as f:
            f.write(b"fake mp4 video bytes")

        conn = sqlite3.connect(db_file)
        conn.execute(
            "INSERT INTO content_profiles (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("channel-escolhas", "Escolhas Impossíveis", now_iso, now_iso),
        )
        conn.execute(
            "INSERT INTO task_profiles (task_id, profile_id, created_at) VALUES (?, ?, ?)",
            (task_id, "channel-escolhas", stuck_time_iso),
        )
        conn.execute(
            "INSERT INTO monetization_safety (task_id, preset, safety_status, checked_at) VALUES (?, ?, ?, ?)",
            (task_id, "quiz_escolhas", "PASS", stuck_time_iso),
        )
        conn.execute(
            """
            INSERT INTO operational_events (timestamp, component, severity, event_type, task_id, message, metadata_json)
            VALUES (?, 'autonomous_production', 'INFO', 'generation_started', ?, 'Iniciando geração autônoma', ?)
            """,
            (stuck_time_iso, task_id, json.dumps({"topic": "Dilema Moral 01", "profile_id": "channel-escolhas"})),
        )
        conn.execute(
            "INSERT INTO autopilot_settings (key, value) VALUES ('autonomous_mode_enabled', 'true'), ('autonomous_state', 'IDLE');"
        )
        conn.commit()
        conn.close()

        res = production_diagnostics.get_diagnostics_overview(
            db_path=db_file,
            task_base_dir=tasks_dir,
            now=now,
        )

        channel_diag = next(c for c in res["channels"] if c["profile_id"] == "channel-escolhas")
        codes = [d["code"] for d in channel_diag["diagnoses"]]
        assert production_diagnostics.CODE_TASK_STUCK_AFTER_RENDER in codes

        stuck_d = next(d for d in channel_diag["diagnoses"] if d["code"] == production_diagnostics.CODE_TASK_STUCK_AFTER_RENDER)
        assert stuck_d["severity"] == production_diagnostics.SEVERITY_CRITICAL
        assert "e9630f19" in stuck_d["evidence"]["task_ids"]
        assert "e9630f19" in stuck_d["detail"]
        assert channel_diag["status"] == production_diagnostics.STATUS_PARADO


def test_detector_false_interruption_likely():
    """Reproduz geração interrompida com vídeo final existente (falso positivo de interrupção)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = os.path.join(tmp_dir, "test_diag.db")
        tasks_dir = os.path.join(tmp_dir, "tasks")
        _create_synthetic_test_db(db_file)

        now = datetime(2026, 10, 27, 16, 0, 0, tzinfo=timezone.utc)
        now_iso = now.isoformat()
        interrupted_time = (now - timedelta(minutes=20)).isoformat()

        task_id = "task-interrupted-01"
        task_path = os.path.join(tasks_dir, task_id)
        os.makedirs(task_path, exist_ok=True)
        with open(os.path.join(task_path, "final-1.mp4"), "wb") as f:
            f.write(b"mp4 content")

        conn = sqlite3.connect(db_file)
        conn.execute(
            "INSERT INTO content_profiles (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("channel-quiz", "Quiz Geral", now_iso, now_iso),
        )
        conn.execute(
            "INSERT INTO task_profiles (task_id, profile_id, created_at) VALUES (?, ?, ?)",
            (task_id, "channel-quiz", interrupted_time),
        )
        conn.execute(
            """
            INSERT INTO operational_events (timestamp, component, severity, event_type, task_id, message, metadata_json)
            VALUES (?, 'autonomous_production', 'WARNING', 'generation_interrupted_recovery', ?, 'Geração interrompida por reinicialização', ?)
            """,
            (interrupted_time, task_id, json.dumps({"profile_id": "channel-quiz"})),
        )
        conn.execute(
            "INSERT INTO autopilot_settings (key, value) VALUES ('autonomous_mode_enabled', 'true'), ('autonomous_state', 'IDLE');"
        )
        conn.commit()
        conn.close()

        res = production_diagnostics.get_diagnostics_overview(
            db_path=db_file,
            task_base_dir=tasks_dir,
            now=now,
        )

        channel_diag = next(c for c in res["channels"] if c["profile_id"] == "channel-quiz")
        codes = [d["code"] for d in channel_diag["diagnoses"]]
        assert production_diagnostics.CODE_FALSE_INTERRUPTION_LIKELY in codes

        interr_d = next(d for d in channel_diag["diagnoses"] if d["code"] == production_diagnostics.CODE_FALSE_INTERRUPTION_LIKELY)
        assert interr_d["severity"] == production_diagnostics.SEVERITY_CRITICAL
        assert task_id in interr_d["evidence"]["task_ids"]


def test_detector_rejection_streak_real_case_quizzes_local_fallback():
    """Reproduz caso real de 27/10: sequência de reprovações consecutivas por 'local_fallback'."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = os.path.join(tmp_dir, "test_diag.db")
        _create_synthetic_test_db(db_file)

        now = datetime(2026, 10, 27, 16, 0, 0, tzinfo=timezone.utc)
        now_iso = now.isoformat()

        conn = sqlite3.connect(db_file)
        conn.execute(
            "INSERT INTO content_profiles (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("channel-quiz", "Canal de Quiz", now_iso, now_iso),
        )
        conn.execute(
            "INSERT INTO autopilot_settings (key, value) VALUES ('autonomous_mode_enabled', 'true'), ('autonomous_state', 'IDLE');"
        )

        # 4 tarefas rejeitadas em sequência
        for idx in range(1, 5):
            t_id = f"task-quiz-rej-{idx}"
            t_time = (now - timedelta(minutes=60 - idx * 10)).isoformat()
            conn.execute(
                "INSERT INTO task_profiles (task_id, profile_id, created_at) VALUES (?, ?, ?)",
                (t_id, "channel-quiz", t_time),
            )
            conn.execute(
                """
                INSERT INTO operational_events (timestamp, component, severity, event_type, task_id, message, metadata_json)
                VALUES (?, 'autonomous_production', 'INFO', 'generation_started', ?, ?, ?)
                """,
                (t_time, t_id, f"Iniciando geração autônoma: 'Quiz #{idx}'", json.dumps({"topic": f"Quiz #{idx}", "profile_id": "channel-quiz"})),
            )
            conn.execute(
                """
                INSERT INTO operational_events (timestamp, component, severity, event_type, task_id, message, metadata_json)
                VALUES (?, 'autonomous_production', 'WARNING', 'task_gate_rejected', ?, ?, ?)
                """,
                (
                    (now - timedelta(minutes=58 - idx * 10)).isoformat(),
                    t_id,
                    f"Tarefa {t_id} reprovada nos Gates: Provedor visual não autorizado: 'local_fallback' no clip #1",
                    json.dumps({
                        "unauthorized_provider": "local_fallback",
                        "copyright_provenance_gate": "FAIL",
                        "profile_id": "channel-quiz",
                    }),
                ),
            )

        conn.commit()
        conn.close()

        res = production_diagnostics.get_diagnostics_overview(
            db_path=db_file,
            now=now,
        )

        channel_diag = next(c for c in res["channels"] if c["profile_id"] == "channel-quiz")
        codes = [d["code"] for d in channel_diag["diagnoses"]]
        assert production_diagnostics.CODE_REJECTION_STREAK in codes

        streak_d = next(d for d in channel_diag["diagnoses"] if d["code"] == production_diagnostics.CODE_REJECTION_STREAK)
        assert streak_d["severity"] == production_diagnostics.SEVERITY_CRITICAL
        assert len(streak_d["evidence"]["task_ids"]) == 4
        assert "local_fallback" in streak_d["detail"]


def test_detector_invalid_topic_real_case_getaddrinfo():
    """Reproduz caso real: generation_started cujo tema é mensagem de erro de rede."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = os.path.join(tmp_dir, "test_diag.db")
        _create_synthetic_test_db(db_file)

        now = datetime(2026, 10, 27, 16, 0, 0, tzinfo=timezone.utc)
        now_iso = now.isoformat()
        err_topic = "Error: [Errno 11001] getaddrinfo failed"

        conn = sqlite3.connect(db_file)
        conn.execute(
            "INSERT INTO content_profiles (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("channel-network", "Canal Rede", now_iso, now_iso),
        )
        task_id = "task-net-err-01"
        conn.execute(
            "INSERT INTO task_profiles (task_id, profile_id, created_at) VALUES (?, ?, ?)",
            (task_id, "channel-network", now_iso),
        )
        conn.execute(
            """
            INSERT INTO operational_events (timestamp, component, severity, event_type, task_id, message, metadata_json)
            VALUES (?, 'autonomous_production', 'INFO', 'generation_started', ?, ?, ?)
            """,
            (
                now_iso,
                task_id,
                f"Iniciando geração autônoma: '{err_topic}' (task_id={task_id})",
                json.dumps({"topic": err_topic, "profile_id": "channel-network"}),
            ),
        )
        conn.execute(
            "INSERT INTO autopilot_settings (key, value) VALUES ('autonomous_mode_enabled', 'true'), ('autonomous_state', 'IDLE');"
        )
        conn.commit()
        conn.close()

        res = production_diagnostics.get_diagnostics_overview(
            db_path=db_file,
            now=now,
        )

        channel_diag = next(c for c in res["channels"] if c["profile_id"] == "channel-network")
        codes = [d["code"] for d in channel_diag["diagnoses"]]
        assert production_diagnostics.CODE_INVALID_TOPIC in codes

        invalid_d = next(d for d in channel_diag["diagnoses"] if d["code"] == production_diagnostics.CODE_INVALID_TOPIC)
        assert invalid_d["severity"] == production_diagnostics.SEVERITY_WARNING
        assert err_topic in invalid_d["detail"]


def test_detector_no_generation_gap_real_case_12h():
    """Reproduz caso real: canal sem generation_started há 12h com estoque abaixo da meta."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = os.path.join(tmp_dir, "test_diag.db")
        _create_synthetic_test_db(db_file)

        now = datetime(2026, 10, 27, 16, 0, 0, tzinfo=timezone.utc)
        now_iso = now.isoformat()
        old_time = (now - timedelta(hours=12)).isoformat()

        conn = sqlite3.connect(db_file)
        conn.execute(
            "INSERT INTO content_profiles (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("channel-gap", "Canal em Hiato", now_iso, now_iso),
        )
        task_id = "task-old-01"
        conn.execute(
            "INSERT INTO task_profiles (task_id, profile_id, created_at) VALUES (?, ?, ?)",
            (task_id, "channel-gap", old_time),
        )
        conn.execute(
            """
            INSERT INTO operational_events (timestamp, component, severity, event_type, task_id, message, metadata_json)
            VALUES (?, 'autonomous_production', 'INFO', 'generation_started', ?, 'Iniciando', ?)
            """,
            (old_time, task_id, json.dumps({"topic": "Tema Antigo", "profile_id": "channel-gap"})),
        )
        conn.execute(
            "INSERT INTO autopilot_settings (key, value) VALUES ('autonomous_mode_enabled', 'true'), ('autonomous_state', 'IDLE');"
        )
        conn.commit()
        conn.close()

        res = production_diagnostics.get_diagnostics_overview(
            db_path=db_file,
            now=now,
        )

        channel_diag = next(c for c in res["channels"] if c["profile_id"] == "channel-gap")
        codes = [d["code"] for d in channel_diag["diagnoses"]]
        assert production_diagnostics.CODE_NO_GENERATION_GAP in codes

        gap_d = next(d for d in channel_diag["diagnoses"] if d["code"] == production_diagnostics.CODE_NO_GENERATION_GAP)
        assert "12.0h sem novas gerações" in gap_d["title"]


def test_detector_throttled_normal_never_warning_or_critical():
    """Garante que PROFILE_GROWTH_LIMIT_BLOCK e aproximação de cota fiquem estritamente em 'info'."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = os.path.join(tmp_dir, "test_diag.db")
        _create_synthetic_test_db(db_file)

        now = datetime(2026, 10, 27, 16, 0, 0, tzinfo=timezone.utc)
        now_iso = now.isoformat()

        conn = sqlite3.connect(db_file)
        conn.execute(
            "INSERT INTO content_profiles (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("channel-growth", "Canal em Escala", now_iso, now_iso),
        )
        conn.execute(
            """
            INSERT INTO operational_events (timestamp, component, severity, event_type, task_id, message, metadata_json)
            VALUES (?, 'scheduler', 'INFO', 'PROFILE_GROWTH_LIMIT_BLOCK', 'task-g-01', 'Growth limit: youtube', ?)
            """,
            (now_iso, json.dumps({"profile_id": "channel-growth", "growth_mode": "WARMUP"})),
        )
        conn.execute(
            "INSERT INTO autopilot_settings (key, value) VALUES ('autonomous_mode_enabled', 'true'), ('autonomous_state', 'IDLE');"
        )
        conn.commit()
        conn.close()

        res = production_diagnostics.get_diagnostics_overview(
            db_path=db_file,
            now=now,
        )

        channel_diag = next(c for c in res["channels"] if c["profile_id"] == "channel-growth")
        throttle_d = next((d for d in channel_diag["diagnoses"] if d["code"] == production_diagnostics.CODE_THROTTLED_NORMAL), None)
        assert throttle_d is not None
        assert throttle_d["severity"] == production_diagnostics.SEVERITY_INFO
        assert throttle_d["severity"] != production_diagnostics.SEVERITY_WARNING
        assert throttle_d["severity"] != production_diagnostics.SEVERITY_CRITICAL
        # Status do canal não é rebaixado por limitação normal de crescimento
        assert channel_diag["status"] == production_diagnostics.STATUS_OK


def test_detector_factory_paused_and_error():
    """Valida estados de fábrica: PAUSED gera info e status PAUSADO; ERROR gera critical e status PARADO."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = os.path.join(tmp_dir, "test_diag.db")
        _create_synthetic_test_db(db_file)

        now = datetime(2026, 10, 27, 16, 0, 0, tzinfo=timezone.utc)
        now_iso = now.isoformat()

        conn = sqlite3.connect(db_file)
        conn.execute(
            "INSERT INTO content_profiles (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("channel-test", "Canal Teste", now_iso, now_iso),
        )
        conn.commit()
        conn.close()

        # Cenário A: Fábrica Pausada
        conn = sqlite3.connect(db_file)
        conn.execute("INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES ('autonomous_state', 'PAUSED'), ('autonomous_message', 'Fábrica pausada por operador');")
        conn.commit()
        conn.close()

        res_paused = production_diagnostics.get_diagnostics_overview(db_path=db_file, now=now)
        chan_paused = res_paused["channels"][0]
        assert chan_paused["status"] == production_diagnostics.STATUS_PAUSADO
        p_diag = next(d for d in chan_paused["diagnoses"] if d["code"] == production_diagnostics.CODE_FACTORY_PAUSED_OR_ERROR)
        assert p_diag["severity"] == production_diagnostics.SEVERITY_INFO

        # Cenário B: Fábrica com Erro Crítico
        conn = sqlite3.connect(db_file)
        conn.execute("INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES ('autonomous_state', 'ERROR'), ('autonomous_last_error', 'Crash inesperado de driver FFmpeg');")
        conn.commit()
        conn.close()

        res_error = production_diagnostics.get_diagnostics_overview(db_path=db_file, now=now)
        chan_error = res_error["channels"][0]
        assert chan_error["status"] == production_diagnostics.STATUS_PARADO
        e_diag = next(d for d in chan_error["diagnoses"] if d["code"] == production_diagnostics.CODE_FACTORY_PAUSED_OR_ERROR)
        assert e_diag["severity"] == production_diagnostics.SEVERITY_CRITICAL
        assert "Crash inesperado de driver FFmpeg" in e_diag["detail"]


def test_unknown_reason_appears_raw_and_missing_data_is_null():
    """Garante que motivo desconhecido apareça cru e dados ausentes sejam null/UNKNOWN."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = os.path.join(tmp_dir, "test_diag.db")
        _create_synthetic_test_db(db_file)

        now = datetime(2026, 10, 27, 16, 0, 0, tzinfo=timezone.utc)
        now_iso = now.isoformat()

        raw_unusual_error = "Exceção incomum desconhecida no renderizador customizado #42"

        conn = sqlite3.connect(db_file)
        conn.execute(
            "INSERT INTO content_profiles (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("channel-raw", "Canal Cru", now_iso, now_iso),
        )
        task_id = "task-raw-01"
        conn.execute(
            "INSERT INTO task_profiles (task_id, profile_id, created_at) VALUES (?, ?, ?)",
            (task_id, "channel-raw", now_iso),
        )
        # Evento com mensagem crua e metadata vazia
        conn.execute(
            """
            INSERT INTO operational_events (timestamp, component, severity, event_type, task_id, message, metadata_json)
            VALUES (?, 'autonomous_production', 'WARNING', 'task_gate_rejected', ?, ?, NULL)
            """,
            (now_iso, task_id, raw_unusual_error),
        )
        conn.execute(
            "INSERT INTO autopilot_settings (key, value) VALUES ('autonomous_mode_enabled', 'true'), ('autonomous_state', 'IDLE');"
        )
        conn.commit()
        conn.close()

        res = production_diagnostics.get_diagnostics_overview(
            db_path=db_file,
            now=now,
        )

        chan = next(c for c in res["channels"] if c["profile_id"] == "channel-raw")
        rec = chan["recent_generations"][0]
        # Motivo preservado exatamente como a mensagem crua
        assert rec["reason"] == raw_unusual_error
        # Tópico ausente vira None (null), nunca inventado
        assert rec["topic"] is None


def _dump_table_content(conn: sqlite3.Connection, table_name: str) -> list[tuple]:
    """Retorna todas as linhas ordenadas para comparação exata de conteúdo."""
    cur = conn.execute(f"SELECT * FROM {table_name} ORDER BY 1;")
    return cur.fetchall()


def test_diagnostics_api_endpoint_200_and_strictly_read_only():
    """Verifica que o endpoint GET /api/v2/diagnostics/overview retorna 200 e não altera dados no banco."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = os.path.join(tmp_dir, "test_diag.db")
        scheduler.init_db(db_file)
        operator_console.init_operator_db(db_file)
        safety_gate.init_safety_db(db_file)
        quality_score.init_quality_db(db_file)
        profile_manager.ensure_default_profile(db_file)

        now_iso = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(db_file)
        try:
            conn.execute(
                "INSERT INTO content_profiles (id, name, slug, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("channel-api", "Canal API", "canal-api", now_iso, now_iso),
            )
            conn.execute(
                """
                INSERT INTO instance_locks (lock_key, node_id, node_name, hostname, pid, started_at, last_heartbeat, role, status)
                VALUES ('PRIMARY_FACTORY', 'node-01', 'PC-Forte', 'host1', 1234, ?, ?, 'PRIMARY', 'ACTIVE')
                """,
                (now_iso, now_iso),
            )
            conn.execute(
                "INSERT INTO autopilot_settings (key, value) VALUES ('autonomous_mode_enabled', 'true'), ('autonomous_state', 'IDLE');"
            )
            conn.commit()
        finally:
            conn.close()

        tables_to_check = [
            "operational_events",
            "scheduled_posts",
            "content_quality_scores",
            "monetization_safety",
            "autopilot_settings",
        ]

        # Mede conteúdo e contagem antes
        conn_pre = sqlite3.connect(db_file)
        content_pre = {tbl: _dump_table_content(conn_pre, tbl) for tbl in tables_to_check}
        counts_pre = {tbl: len(content_pre[tbl]) for tbl in tables_to_check}
        conn_pre.close()

        from app.asgi import app
        client = TestClient(app)

        with patch("app.services.scheduler.get_db_path", return_value=db_file):
            resp = client.get("/api/v2/diagnostics/overview")

        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        data = body["data"]
        assert "factory" in data
        assert "channels" in data
        assert data["factory"]["primary_instance"]["node_name"] == "PC-Forte"

        # Garante que nenhum registro foi inserido/alterado nas tabelas
        conn_post = sqlite3.connect(db_file)
        content_post = {tbl: _dump_table_content(conn_post, tbl) for tbl in tables_to_check}
        counts_post = {tbl: len(content_post[tbl]) for tbl in tables_to_check}
        conn_post.close()

        assert counts_pre == counts_post
        assert content_pre == content_post


def test_ro_connection_guarantees_and_non_existent_db():
    """Valida garantias estritas de somente leitura (_get_ro_connection) e caso de banco inexistente."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = os.path.join(tmp_dir, "test_ro.db")
        scheduler.init_db(db_file)
        operator_console.init_operator_db(db_file)
        safety_gate.init_safety_db(db_file)
        quality_score.init_quality_db(db_file)
        profile_manager.ensure_default_profile(db_file)

        now_iso = datetime.now(timezone.utc).isoformat()
        h1_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        conn = sqlite3.connect(db_file)
        try:
            conn.execute(
                "INSERT INTO content_profiles (id, name, slug, created_at, updated_at) VALUES ('c1', 'Canal 1', 'canal-1', ?, ?)",
                (now_iso, now_iso),
            )
            conn.execute(
                "INSERT INTO autopilot_settings (key, value) VALUES ('autonomous_mode_enabled', 'true'), ('autonomous_state', 'IDLE');"
            )
            conn.execute(
                "INSERT INTO task_profiles (task_id, profile_id, created_at) VALUES ('t-recent-1', 'c1', ?)",
                (h1_ago,),
            )
            conn.execute(
                """
                INSERT INTO operational_events (timestamp, component, severity, event_type, task_id, message, metadata_json)
                VALUES (?, 'autonomous_production', 'INFO', 'generation_started', 't-recent-1', 'Iniciando', ?)
                """,
                (h1_ago, json.dumps({"topic": "Tema Recente", "profile_id": "c1"})),
            )
            conn.commit()
        finally:
            conn.close()

        # 1. Tentativa de escrita pela conexão RO falha
        ro_conn = production_diagnostics._get_ro_connection(db_file)
        with pytest.raises(sqlite3.OperationalError):
            ro_conn.execute("INSERT INTO autopilot_settings (key, value) VALUES ('hacked', 'yes');")
        with pytest.raises(sqlite3.OperationalError):
            ro_conn.execute("CREATE TABLE should_not_exist (id INT);")
        ro_conn.close()

        # 2. Compara conteúdo das tabelas antes e depois da execução do serviço em banco inicializado
        tables_to_check = [
            "operational_events",
            "scheduled_posts",
            "content_quality_scores",
            "monetization_safety",
            "autopilot_settings",
        ]
        conn_pre = sqlite3.connect(db_file)
        content_before = {tbl: _dump_table_content(conn_pre, tbl) for tbl in tables_to_check}
        counts_before = {tbl: len(content_before[tbl]) for tbl in tables_to_check}
        conn_pre.close()

        overview = production_diagnostics.get_diagnostics_overview(db_path=db_file)
        assert overview["factory"]["state"] == "IDLE"
        assert any(c["profile_id"] == "c1" for c in overview["channels"])

        conn_post = sqlite3.connect(db_file)
        content_after = {tbl: _dump_table_content(conn_post, tbl) for tbl in tables_to_check}
        counts_after = {tbl: len(content_after[tbl]) for tbl in tables_to_check}
        conn_post.close()

        # Nenhuma linha inserida, alterada ou apagada nas tabelas de dados
        assert counts_before == counts_after
        assert content_before == content_after

        # 3. Caso de banco inexistente devolve status UNKNOWN sem criar o arquivo em disco
        ghost_db = os.path.join(tmp_dir, "ghost_database_does_not_exist.db")
        assert not os.path.exists(ghost_db)

        ghost_overview = production_diagnostics.get_diagnostics_overview(db_path=ghost_db)
        assert ghost_overview["factory"]["state"] == production_diagnostics.STATUS_UNKNOWN
        assert not os.path.exists(ghost_db)


def test_ready_stock_canonical_and_older_than_24h():
    """Valida que estoque canônico inclui vídeo pronto >24h e é idêntico ao production_overview."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = os.path.join(tmp_dir, "test_stock.db")
        tasks_dir = os.path.join(tmp_dir, "tasks")
        os.makedirs(tasks_dir, exist_ok=True)
        scheduler.init_db(db_file)
        operator_console.init_operator_db(db_file)
        safety_gate.init_safety_db(db_file)
        quality_score.init_quality_db(db_file)
        profile_manager.ensure_default_profile(db_file)

        now = datetime(2026, 10, 27, 16, 0, 0, tzinfo=timezone.utc)
        now_iso = now.isoformat()
        old_time = now - timedelta(hours=36)
        old_iso = old_time.isoformat()

        task_id = "task-ready-old-36h"
        task_path = os.path.join(tasks_dir, task_id)
        os.makedirs(task_path, exist_ok=True)
        with open(os.path.join(task_path, "final-1.mp4"), "wb") as f:
            f.write(b"video mp4 bytes")
        with open(os.path.join(task_path, "script.json"), "w", encoding="utf-8") as f:
            json.dump({
                "params": {"bgm_type": "none", "video_subject": "Fatos sobre Saturno"},
                "material_sources": [{"provider": "pexels", "local_file": "v1.mp4"}]
            }, f)

        safety_gate.save_safety_assessment(
            {"task_id": task_id, "safety_status": const.SAFETY_STATUS_PASS, "safety_reasons": []},
            db_path=db_file,
        )
        with scheduler.get_connection(db_file) as conn:
            conn.execute(
                "UPDATE monetization_safety SET checked_at = ? WHERE task_id = ?",
                (old_iso, task_id),
            )
            conn.execute(
                "INSERT INTO content_quality_scores "
                "(task_id, topic, quality_score, quality_label, created_at) VALUES (?, ?, 82.0, 'GOOD', ?)",
                (task_id, "Fatos sobre Saturno", old_iso),
            )
        scheduler.save_task_platforms(task_id, ["youtube"], db_path=db_file)
        profile_manager.save_task_profile(task_id, "default", db_path=db_file)
        operator_console.invalidate_render_pass_cache()

        # Executa com task_dir apontando para tasks_dir
        with patch("app.utils.utils.task_dir", return_value=tasks_dir):
            # Diagnóstico de produção
            diag_res = production_diagnostics.get_diagnostics_overview(
                db_path=db_file,
                task_base_dir=tasks_dir,
                now=now,
            )
            chan_diag = next(c for c in diag_res["channels"] if c["profile_id"] == "default")
            # Vídeo pronto há 36h DEVE estar no estoque do diagnóstico
            assert chan_diag["ready_stock"]["count"] == 1

            # Overview da tela Produção
            production_overview.clear_production_overview_cache()
            overview_res = production_overview.get_production_overview(
                profile_id="default",
                db_path=db_file,
                use_cache=False,
            )
            chan_overview = next(c for c in overview_res["channels"] if c["profile_id"] == "default")

            # O estoque do diagnóstico deve ser idêntico ao que a tela Produção mostra para o mesmo canal
            assert chan_diag["ready_stock"]["count"] == chan_overview["ready_stock"]["total"]
            assert chan_diag["ready_stock"]["count"] == overview_res["totals"]["total_ready"]


def test_max_attempts_24h_quota_canonical_logic():
    """Valida resolução da cota max_attempts_24h conforme regra canônica de autonomous_production."""
    # 1. Perfil default sem override -> 15 (DEFAULT_AUTONOMOUS_MAX_ATTEMPTS_24H)
    assert production_diagnostics.resolve_channel_max_attempts(
        "default", {}
    ) == autonomous_production.DEFAULT_AUTONOMOUS_MAX_ATTEMPTS_24H
    assert production_diagnostics.resolve_channel_max_attempts(
        None, {}
    ) == autonomous_production.DEFAULT_AUTONOMOUS_MAX_ATTEMPTS_24H
    assert production_diagnostics.resolve_channel_max_attempts(
        "", {}
    ) == autonomous_production.DEFAULT_AUTONOMOUS_MAX_ATTEMPTS_24H

    # 2. Canal secundário sem override -> 8
    assert production_diagnostics.resolve_channel_max_attempts(
        "channel-secundario", {}
    ) == 8

    # 3. Canal secundário com override -> valor do override (ex.: 30)
    settings_override_sec = {
        f"{autonomous_production.KEY_AUTONOMOUS_MAX_ATTEMPTS_24H}:channel-secundario": "30"
    }
    assert production_diagnostics.resolve_channel_max_attempts(
        "channel-secundario", settings_override_sec
    ) == 30

    # 4. Canal default com override -> valor do override (ex.: 25)
    settings_override_def = {
        f"{autonomous_production.KEY_AUTONOMOUS_MAX_ATTEMPTS_24H}:default": "25"
    }
    assert production_diagnostics.resolve_channel_max_attempts(
        "default", settings_override_def
    ) == 25


def test_factory_pause_via_operator_console_and_gap_suppression():
    """Valida que pause_factory() de operator_console gera FACTORY_PAUSED_OR_ERROR e suprime NO_GENERATION_GAP."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = os.path.join(tmp_dir, "test_pause.db")
        scheduler.init_db(db_file)
        operator_console.init_operator_db(db_file)

        now = datetime(2026, 10, 27, 16, 0, 0, tzinfo=timezone.utc)
        now_iso = now.isoformat()
        old_time = (now - timedelta(hours=14)).isoformat()

        conn = sqlite3.connect(db_file)
        try:
            conn.execute(
                "INSERT INTO content_profiles (id, name, slug, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("channel-paused-test", "Canal Pausa", "canal-pausa", now_iso, now_iso),
            )
            task_id = "task-pause-01"
            conn.execute(
                "INSERT INTO task_profiles (task_id, profile_id, created_at) VALUES (?, ?, ?)",
                (task_id, "channel-paused-test", old_time),
            )
            conn.execute(
                """
                INSERT INTO operational_events (timestamp, component, severity, event_type, task_id, message, metadata_json)
                VALUES (?, 'autonomous_production', 'INFO', 'generation_started', ?, 'Iniciando', ?)
                """,
                (old_time, task_id, json.dumps({"topic": "Tema Antigo", "profile_id": "channel-paused-test"})),
            )
            conn.commit()
        finally:
            conn.close()

        # Pausa a fábrica chamando a função real usada pela tela Sistema / API
        with patch("app.services.operator_console.is_primary_instance", return_value=True):
            operator_console.pause_factory(db_path=db_file)

        diag_res = production_diagnostics.get_diagnostics_overview(
            db_path=db_file,
            now=now,
        )

        assert diag_res["factory"]["state"] == "PAUSED"
        assert diag_res["factory"]["is_paused"] is True
        chan = next(c for c in diag_res["channels"] if c["profile_id"] == "channel-paused-test")
        assert chan["status"] == production_diagnostics.STATUS_PAUSADO

        codes = [d["code"] for d in chan["diagnoses"]]
        # Confirma que FACTORY_PAUSED_OR_ERROR com severidade info está presente
        assert production_diagnostics.CODE_FACTORY_PAUSED_OR_ERROR in codes
        p_diag = next(d for d in chan["diagnoses"] if d["code"] == production_diagnostics.CODE_FACTORY_PAUSED_OR_ERROR)
        assert p_diag["severity"] == production_diagnostics.SEVERITY_INFO

        # Confirma que NO_GENERATION_GAP NÃO dispara enquanto pausada
        assert production_diagnostics.CODE_NO_GENERATION_GAP not in codes


def test_no_monkeypatching_identity_preserved():
    """Garante que get_diagnostics_overview não altera a identidade das funções de módulos externos."""
    funcs_before = {
        "sched_init": scheduler.init_db,
        "sched_conn": scheduler.get_connection,
        "pm_conn": profile_manager.get_connection,
        "pm_init": profile_manager.init_profile_db,
        "qs_init": quality_score.init_quality_db,
        "op_init": operator_console.init_operator_db,
    }

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = os.path.join(tmp_dir, "test_ident.db")
        scheduler.init_db(db_file)
        operator_console.init_operator_db(db_file)
        profile_manager.ensure_default_profile(db_file)

        res = production_diagnostics.get_diagnostics_overview(db_path=db_file)
        assert res["factory"]["state"] in ("IDLE", "RUNNING")

    assert scheduler.init_db is funcs_before["sched_init"]
    assert scheduler.get_connection is funcs_before["sched_conn"]
    assert profile_manager.get_connection is funcs_before["pm_conn"]
    assert profile_manager.init_profile_db is funcs_before["pm_init"]
    assert quality_score.init_quality_db is funcs_before["qs_init"]
    assert operator_console.init_operator_db is funcs_before["op_init"]


def test_concurrent_threads_execution_and_identity_preserved():
    """Garante que chamadas concorrentes em múltiplas threads retornam sem erro e preservam funções originais."""
    import concurrent.futures

    funcs_before = {
        "sched_init": scheduler.init_db,
        "sched_conn": scheduler.get_connection,
        "pm_conn": profile_manager.get_connection,
        "pm_init": profile_manager.init_profile_db,
        "qs_init": quality_score.init_quality_db,
        "op_init": operator_console.init_operator_db,
    }

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = os.path.join(tmp_dir, "test_concurrent.db")
        scheduler.init_db(db_file)
        operator_console.init_operator_db(db_file)
        profile_manager.ensure_default_profile(db_file)

        def _worker():
            return production_diagnostics.get_diagnostics_overview(db_path=db_file)

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(_worker) for _ in range(8)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert len(results) == 8
        for r in results:
            assert "factory" in r
            assert "channels" in r

    assert scheduler.init_db is funcs_before["sched_init"]
    assert scheduler.get_connection is funcs_before["sched_conn"]
    assert profile_manager.get_connection is funcs_before["pm_conn"]
    assert profile_manager.init_profile_db is funcs_before["pm_init"]
    assert quality_score.init_quality_db is funcs_before["qs_init"]
    assert operator_console.init_operator_db is funcs_before["op_init"]


def test_static_guard_against_monkeypatching():
    """Varre production_diagnostics.py e falha se encontrar atribuição a módulos externos como alvo de '='."""
    import re
    from pathlib import Path

    src_path = Path(production_diagnostics.__file__).resolve()
    content = src_path.read_text(encoding="utf-8")

    pattern = re.compile(
        r"^\s*(?:scheduler|profile_manager|quality_score|operator_console)\.[a-zA-Z0-9_]+\s*=",
        re.MULTILINE,
    )
    matches = pattern.findall(content)
    assert not matches, f"Encontrado monkeypatch proibido em {src_path.name}: {matches}"


