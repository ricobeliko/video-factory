"""
Testes Unitários e de Integração Direcionados para Diagnóstico V15-B.

Garante:
1. Auditoria da tarefa de mistério aprovada (isolamento, gates, Growth Mode, causa de retenção)
2. Auditoria de tarefas com arquivos de vídeo ausentes/vazios
3. Decomposição factual dos componentes de Quality Score em rejeições (< 70)
4. Diagnóstico de exclusões fail-closed no Closed Feedback Loop (copyright unknown e blocked)
5. Estritamente READ-ONLY (hash do SQLite imutável antes e depois do diagnóstico)
6. CLI produz JSON válido em stdout sem corrupção por logs
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone

from app.models import const
from app.services import flow_diagnostics, quality_score, scheduler
from scripts import diagnose_v15b


class TestV15BDiagnostics(unittest.TestCase):
    def setUp(self):
        if sys.version_info >= (3, 10):
            self.temp_dir_obj = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        else:
            self.temp_dir_obj = tempfile.TemporaryDirectory()
        self.temp_dir = self.temp_dir_obj.name
        self.db_path = os.path.join(self.temp_dir, "test_v15b.db")
        self.task_base_dir = os.path.join(self.temp_dir, "tasks")
        os.makedirs(self.task_base_dir, exist_ok=True)

        self._init_test_db()

    def tearDown(self):
        try:
            self.temp_dir_obj.cleanup()
        except Exception:
            pass

    def _init_test_db(self):
        """Cria o schema mínimo necessário no SQLite de teste."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS content_profiles (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    slug TEXT UNIQUE NOT NULL,
                    niche TEXT,
                    language TEXT,
                    region TEXT,
                    default_preset TEXT,
                    growth_mode TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS publishing_channels (
                    id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    display_name TEXT,
                    name TEXT,
                    external_profile_name TEXT,
                    is_enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS task_profiles (
                    task_id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL,
                    assigned_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS task_platforms (
                    task_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    assigned_at TEXT NOT NULL,
                    PRIMARY KEY (task_id, platform)
                );

                CREATE TABLE IF NOT EXISTS monetization_safety (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT UNIQUE,
                    safety_status TEXT NOT NULL,
                    safety_reasons TEXT,
                    checked_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS content_quality_scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT,
                    trend_id TEXT,
                    topic TEXT NOT NULL,
                    niche TEXT,
                    preset TEXT,
                    narrative_structure TEXT,
                    hook_text TEXT,
                    quality_score REAL NOT NULL,
                    quality_label TEXT NOT NULL,
                    hook_score REAL,
                    originality_score REAL,
                    trend_score REAL,
                    relevance_score REAL,
                    source_confidence_score REAL,
                    repetition_score REAL,
                    narrative_fit_score REAL,
                    duration_fit_score REAL,
                    historical_performance_score REAL,
                    visual_match_score REAL,
                    reasons_json TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS scheduled_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    profile_id TEXT,
                    channel_id TEXT,
                    scheduled_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'planned',
                    attempts INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS publication_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    profile_id TEXT,
                    channel_id TEXT,
                    published_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    privacy_status TEXT DEFAULT 'public',
                    external_id TEXT
                );

                CREATE TABLE IF NOT EXISTS autopilot_settings (
                    setting_key TEXT PRIMARY KEY,
                    setting_value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
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

                CREATE TABLE IF NOT EXISTS content_analytics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    publication_event_id INTEGER NOT NULL,
                    task_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    profile_id TEXT,
                    channel_id TEXT,
                    external_id TEXT,
                    collected_at TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    metadata_json TEXT
                );
                """
            )
            # Popula perfis e canais de teste
            conn.execute("INSERT INTO content_profiles (id, name, slug, is_active, created_at, updated_at) VALUES ('default', 'Canal Principal', 'default', 1, '2026-09-20T00:00:00Z', '2026-09-20T00:00:00Z');")
            conn.execute("INSERT INTO content_profiles (id, name, slug, is_active, created_at, updated_at) VALUES ('profile-historias-misterio', 'Histórias de Mistério', 'historias-misterio', 1, '2026-09-20T00:00:00Z', '2026-09-20T00:00:00Z');")
            conn.execute("INSERT INTO publishing_channels (id, profile_id, platform, display_name, name, is_enabled, created_at, updated_at) VALUES ('chan_default_yt', 'default', 'youtube', 'YouTube Principal', 'YouTube Principal', 1, '2026-09-20T00:00:00Z', '2026-09-20T00:00:00Z');")
            conn.execute("INSERT INTO publishing_channels (id, profile_id, platform, display_name, name, is_enabled, created_at, updated_at) VALUES ('chan_mystery_yt', 'profile-historias-misterio', 'youtube', 'YouTube Mistério', 'YouTube Mistério', 1, '2026-09-20T00:00:00Z', '2026-09-20T00:00:00Z');")
            conn.commit()
        finally:
            conn.close()

    def _file_hash(self, path: str) -> str:
        """Calcula o SHA256 de um arquivo."""
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def test_01_diagnose_mystery_task_approved_waiting_state(self):
        """Diagnostica tarefa aprovada de mistério retida e simula gates estritamente read-only."""
        tid = "de22b786-973e-4391-8ba0-7c43599beef9"
        # Cria pasta física com vídeo e script
        task_dir = os.path.join(self.task_base_dir, tid)
        os.makedirs(task_dir, exist_ok=True)
        with open(os.path.join(task_dir, "final-1.mp4"), "wb") as f:
            f.write(b"mp4_mock_data_for_test")
        with open(os.path.join(task_dir, "script.json"), "w", encoding="utf-8") as f:
            json.dump({
                "asset_provenance": {
                    "provenance_status": "SAFE_NO_BGM",
                    "bgm": {"enabled": False},
                    "visual_clips": [{"provider": "pexels", "local_file": "clip_1.mp4"}],
                }
            }, f)

        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("INSERT INTO task_profiles (task_id, profile_id, assigned_at) VALUES (?, 'profile-historias-misterio', '2026-09-23T00:00:00Z');", (tid,))
            conn.execute("INSERT INTO task_platforms (task_id, platform, assigned_at) VALUES (?, 'youtube', '2026-09-23T00:00:00Z');", (tid,))
            conn.execute("INSERT INTO monetization_safety (task_id, safety_status, safety_reasons, checked_at) VALUES (?, 'PASS', '[]', '2026-09-23T00:00:00Z');", (tid,))
            conn.execute(
                """
                INSERT INTO content_quality_scores (
                    task_id, topic, quality_score, quality_label, created_at
                ) VALUES (?, 'Mistério do Farol', 79.1, 'GOOD', '2026-09-23T00:00:00Z');
                """,
                (tid,),
            )
            # Salva setting do ciclo autônomo com waiting_task_id limpo
            conn.execute(
                "INSERT INTO autopilot_settings (setting_key, setting_value, updated_at) VALUES ('autonomous_waiting_task_id:profile-historias-misterio', '', '2026-09-23T00:00:00Z');"
            )
            conn.commit()
        finally:
            conn.close()

        diag = flow_diagnostics.diagnose_mystery_task(
            task_id=tid,
            db_path=self.db_path,
            task_base_dir=self.task_base_dir,
        )

        self.assertEqual(diag["task_id"], tid)
        self.assertTrue(diag["disk_inspection"]["final_video_exists"])
        self.assertEqual(diag["db_records"]["safety"]["safety_status"], "PASS")
        self.assertEqual(diag["db_records"]["quality"]["quality_score"], 79.1)
        self.assertEqual(diag["gate_simulation"]["recover_waiting_task_result"], "SUCCESS")
        self.assertIn(diag["conclusion"], ("GROWTH_MODE_SLOT_SATURATION", "OBSERVABILITY_DESYNCHRONIZATION"))

    def test_02_diagnose_missing_video_tasks(self):
        """Diagnostica tarefas com final video ausente, diferenciando render nunca iniciado de pasta inexistente."""
        t1 = "2f568515-77d0-4e88-852a-27b189f30404"
        t2 = "7223a453-f47c-4bda-90c0-80d31932eee2"

        # t1: Pasta existe com script mas sem vídeo e sem evento de render
        t1_dir = os.path.join(self.task_base_dir, t1)
        os.makedirs(t1_dir, exist_ok=True)
        with open(os.path.join(t1_dir, "script.json"), "w", encoding="utf-8") as f:
            json.dump({"topic": "Vídeo Incompleto"}, f)

        # t2: Pasta nem existe
        # (não cria pasta para t2)

        diag = flow_diagnostics.diagnose_missing_video_tasks(
            task_ids=(t1, t2),
            db_path=self.db_path,
            task_base_dir=self.task_base_dir,
        )

        self.assertIn(t1, diag["tasks"])
        self.assertIn(t2, diag["tasks"])
        self.assertEqual(diag["tasks"][t1]["root_cause"], "TASK_ABORTED_BEFORE_RENDER_STAGE")
        self.assertEqual(diag["tasks"][t2]["root_cause"], "TASK_DIRECTORY_NEVER_CREATED_OR_DELETED")

    def test_03_diagnose_quality_rejects_components(self):
        """Analisa decomposição de Quality Rejects identificando os sub-componentes falhos."""
        conn = sqlite3.connect(self.db_path)
        try:
            # Insere 4 tarefas com scores aproximadamente 45.9, 49.1, 50.0, 51.4
            # onde duration_fit (30.0) e visual_match (45.0) foram os vilões
            items = [
                ("t_q1", 45.9, 70.0, 70.0, 30.0, 45.0),
                ("t_q2", 49.1, 70.0, 70.0, 30.0, 45.0),
                ("t_q3", 50.0, 50.0, 70.0, 30.0, 70.0),
                ("t_q4", 51.4, 70.0, 70.0, 30.0, 70.0),
            ]
            for tid, q_score, h_score, n_score, d_score, v_score in items:
                conn.execute(
                    """
                    INSERT INTO content_quality_scores (
                        task_id, topic, quality_score, quality_label,
                        hook_score, narrative_fit_score, duration_fit_score, visual_match_score,
                        reasons_json, created_at
                    ) VALUES (?, 'Tópico de Teste', ?, 'REVIEW', ?, ?, ?, ?, '["Duração abaixo da meta"]', '2026-09-23T00:00:00Z');
                    """,
                    (tid, q_score, h_score, n_score, d_score, v_score),
                )
            conn.commit()
        finally:
            conn.close()

        diag = flow_diagnostics.diagnose_quality_rejects(
            db_path=self.db_path,
            threshold=70.0,
        )

        self.assertEqual(diag["rejected_count"], 4)
        self.assertIn("duration_fit", diag["top_failing_components"])
        self.assertEqual(diag["failing_component_frequency"]["duration_fit"], 4)
        self.assertEqual(diag["failing_component_frequency"]["visual_match"], 2)

    def test_04_diagnose_closed_loop_zero_samples(self):
        """Diagnostica por que sample_count = 0 (default: unknown, mystery: blocked #18)."""
        conn = sqlite3.connect(self.db_path)
        try:
            # 1. Publicação para default sem copyright auditado (fica unknown)
            conn.execute(
                """
                INSERT INTO publication_events (
                    id, task_id, platform, profile_id, channel_id, published_at, status, privacy_status, external_id
                ) VALUES (10, 'task_def_1', 'youtube', 'default', 'chan_default_yt', '2026-09-20T12:00:00Z', 'success', 'public', 'abcde123456');
                """
            )

            conn.execute("INSERT INTO task_profiles (task_id, profile_id, assigned_at) VALUES ('task_def_1', 'default', '2026-09-20T00:00:00Z');")
            conn.execute("INSERT INTO task_profiles (task_id, profile_id, assigned_at) VALUES ('task_myst_18', 'profile-historias-misterio', '2026-09-20T00:00:00Z');")

            # 2. Publicação #18 para mystery com status blocked em operational_events
            conn.execute(
                """
                INSERT INTO publication_events (
                    id, task_id, platform, profile_id, channel_id, published_at, status, privacy_status, external_id
                ) VALUES (18, 'task_myst_18', 'youtube', 'profile-historias-misterio', 'chan_mystery_yt', '2026-09-20T12:00:00Z', 'success', 'public', 'xyz98765432');
                """
            )
            conn.execute(
                """
                INSERT INTO operational_events (
                    timestamp, component, severity, event_type, task_id, message, metadata_json
                ) VALUES (
                    '2026-09-22T00:00:00Z', 'operator_console', 'INFO', 'PUBLICATION_COPYRIGHT_STATUS_SET',
                    'task_myst_18', 'Copyright set to blocked', '{"publication_event_id": 18, "copyright_status": "blocked"}'
                );
                """
            )
            conn.commit()
        finally:
            conn.close()

        diag = flow_diagnostics.diagnose_closed_loop_zero_samples(db_path=self.db_path)

        self.assertIn("FAIL_CLOSED_COPYRIGHT_UNKNOWN", diag["default_profile"]["conclusion"])
        self.assertEqual(len(diag["default_profile"]["publications_blocked_by_unknown_copyright"]), 1)
        self.assertTrue(diag["mystery_profile"]["blocked_publication_18_confirmed"])
        self.assertIn("FAIL_CLOSED_COPYRIGHT_BLOCKED", diag["mystery_profile"]["conclusion"])

    def test_05_read_only_strictly_preserves_database(self):
        """Garante que a execução de run_v15b_diagnosis é 100% read-only (zero mutações no SQLite)."""
        initial_hash = self._file_hash(self.db_path)

        # Executa diagnóstico completo consolidado
        report = flow_diagnostics.run_v15b_diagnosis(
            db_path=self.db_path,
            task_base_dir=self.task_base_dir,
        )

        final_hash = self._file_hash(self.db_path)
        self.assertEqual(initial_hash, final_hash, "O banco de dados SQLite foi mutado durante o diagnóstico!")
        self.assertEqual(report["status"], "ok")

    def test_06_cli_json_valid_stdout(self):
        """Garante que o script scripts/diagnose_v15b.py com --json retorna JSON válido em stdout."""
        stdout_capture = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = stdout_capture
            code = diagnose_v15b.main([
                "--json",
                "--db-path", self.db_path,
                "--task-base-dir", self.task_base_dir,
            ])
            self.assertEqual(code, 0)
        finally:
            sys.stdout = old_stdout

        output_str = stdout_capture.getvalue().strip()
        parsed = json.loads(output_str)
        self.assertEqual(parsed.get("status"), "ok")
        self.assertIn("conclusions", parsed)
        self.assertIn("MYSTERY_APPROVED_TASK", parsed["conclusions"])


if __name__ == "__main__":
    unittest.main()
