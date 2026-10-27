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

import json
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.models import const
from app.services import production_diagnostics


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


def test_diagnostics_api_endpoint_200_and_strictly_read_only():
    """Verifica que o endpoint GET /api/v2/diagnostics/overview retorna 200 e não escreve no banco."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = os.path.join(tmp_dir, "test_diag.db")
        _create_synthetic_test_db(db_file)

        now_iso = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(db_file)
        conn.execute(
            "INSERT INTO content_profiles (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("channel-api", "Canal API", now_iso, now_iso),
        )
        conn.execute(
            """
            INSERT INTO instance_locks (lock_key, node_id, node_name, hostname, pid, status, last_heartbeat)
            VALUES ('PRIMARY_FACTORY', 'node-01', 'PC-Forte', 'host1', 1234, 'ACTIVE', ?)
            """,
            (now_iso,),
        )
        conn.execute(
            "INSERT INTO autopilot_settings (key, value) VALUES ('autonomous_mode_enabled', 'true'), ('autonomous_state', 'IDLE');"
        )
        conn.commit()
        conn.close()

        # Mede contagem de tabelas e registros antes
        conn_pre = sqlite3.connect(db_file)
        tables_pre = conn_pre.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
        pre_counts = {t[0]: conn_pre.execute(f"SELECT count(*) FROM {t[0]};").fetchone()[0] for t in tables_pre}
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

        # Garante que nenhuma tabela nova foi criada e nenhum registro foi inserido/alterado
        conn_post = sqlite3.connect(db_file)
        tables_post = conn_post.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
        post_counts = {t[0]: conn_post.execute(f"SELECT count(*) FROM {t[0]};").fetchone()[0] for t in tables_post}
        conn_post.close()

        assert tables_pre == tables_post
        assert pre_counts == post_counts
