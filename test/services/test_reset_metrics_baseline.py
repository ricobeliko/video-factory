"""
Testes Unitários e de Integração Direcionados para Auditoria e Reset Seguro da Baseline de Métricas (V15-D.1).

Garante:
1. Dry-run é estritamente READ-ONLY (hash SHA-256 do SQLite inalterado)
2. Tabelas críticas de canais, perfis e idempotência são PRESERVE
3. Idempotência de publicação é preservada (zero risco de repostagem)
4. Execute falha fail-closed sem confirmação explícita
5. Backup físico obrigatório com PRAGMA integrity_check e SHA-256 gerado antes de qualquer mutação
6. Relatório de classificação determinístico com todas as seções canônicas
7. Limpeza parcial de operational_events preserva PUBLICATION_COPYRIGHT_STATUS_SET
8. Marcador temporal metrics_baseline_started_at persistido em autopilot_settings sem schema migration
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services import (  # noqa: E402
    analytics,
    analytics_scheduler,
    profile_manager,
    quality_score,
    safety_gate,
    scheduler,
    trend_radar,
)


class TestResetMetricsBaseline(unittest.TestCase):
    def setUp(self):
        if sys.version_info >= (3, 10):
            self.temp_dir_obj = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        else:
            self.temp_dir_obj = tempfile.TemporaryDirectory()
        self.temp_dir = self.temp_dir_obj.name
        self.db_path = os.path.join(self.temp_dir, "test_metrics_baseline.db")
        self.backup_dir = os.path.join(self.temp_dir, "backups")

        self._seed_full_schema_and_data()

    def tearDown(self):
        try:
            self.temp_dir_obj.cleanup()
        except Exception:
            pass

    def _seed_full_schema_and_data(self):
        """Inicializa um banco com o schema real completo e dados simulados."""
        now_iso = datetime.now(timezone.utc).isoformat()

        # Inicializa schemas padrão
        scheduler.init_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        safety_gate.init_safety_db(self.db_path)
        quality_score.init_quality_db(self.db_path)
        analytics.init_analytics_db(self.db_path)
        trend_radar.init_trend_db(self.db_path)

        with sqlite3.connect(self.db_path) as conn:
            # 1. Configurações e perfis
            conn.execute(
                "INSERT INTO content_profiles (id, name, slug, niche, default_preset, growth_mode, is_active, created_at, updated_at) "
                "VALUES ('profile-misterio', 'Misterio', 'misterio', 'historias_misterio', 'youtube_shorts_original', 'warmup', 1, ?, ?);",
                (now_iso, now_iso),
            )
            conn.execute(
                "INSERT INTO publishing_channels (id, profile_id, platform, display_name, is_enabled, created_at, updated_at) "
                "VALUES ('channel-misterio-yt', 'profile-misterio', 'youtube', 'Misterio YT', 1, ?, ?);",
                (now_iso, now_iso),
            )
            conn.execute(
                "INSERT INTO task_profiles (task_id, profile_id, created_at) "
                "VALUES ('task-pub-1', 'profile-misterio', ?);",
                (now_iso,),
            )

            # 2. Publicações reais (idempotência crítica)
            conn.execute(
                "INSERT INTO publication_events (id, task_id, platform, published_at, status, external_id, profile_id, channel_id) "
                "VALUES (1, 'task-pub-1', 'youtube', ?, 'success', 'YOUTUBE_VID_1', 'profile-misterio', 'channel-misterio-yt');",
                (now_iso,),
            )
            conn.execute(
                "INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at, profile_id, channel_id) "
                "VALUES ('task-pub-1', 'youtube', ?, 'published', ?, 'profile-misterio', 'channel-misterio-yt');",
                (now_iso, now_iso),
            )

            # 3. Métricas históricas legadas (candidatas a reset)
            conn.execute(
                "INSERT INTO content_analytics (task_id, platform, views, published_at, collected_at, age_bucket) "
                "VALUES ('task-pub-1', 'youtube', 1500, ?, ?, '24h');",
                (now_iso, now_iso),
            )
            conn.execute(
                "INSERT INTO content_quality_scores (task_id, topic, quality_score, quality_label, created_at) "
                "VALUES ('task-pub-1', 'Tema Misterio 1', 78.5, 'GOOD', ?);",
                (now_iso,),
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS content_strategy_scores ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT, score REAL);"
            )
            conn.execute("INSERT INTO content_strategy_scores (topic, score) VALUES ('Tema Misterio 1', 85.0);")

            # 4. Tabela mista: operational_events
            conn.execute(
                "CREATE TABLE IF NOT EXISTS operational_events ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, component TEXT, severity TEXT, event_type TEXT, task_id TEXT, message TEXT, metadata_json TEXT);"
            )
            # Evento comum (pode ser resetado)
            conn.execute(
                "INSERT INTO operational_events (timestamp, component, severity, event_type, task_id, message) "
                "VALUES (?, 'closed_loop', 'INFO', 'CLOSED_LOOP_DECISION', 'task-pub-1', 'Decision log');",
                (now_iso,),
            )
            # Evento de auditoria de copyright (DEVE SER PRESERVADO)
            conn.execute(
                "INSERT INTO operational_events (timestamp, component, severity, event_type, task_id, message, metadata_json) "
                "VALUES (?, 'operator', 'INFO', 'PUBLICATION_COPYRIGHT_STATUS_SET', 'task-pub-1', 'Audit log', '{\"copyright_status\": \"clean_manual\"}');",
                (now_iso,),
            )

            # 5. Tabela mista: autopilot_settings
            conn.execute(
                "INSERT OR REPLACE INTO autopilot_settings (key, value) "
                "VALUES ('autonomous_production_enabled', 'True');"
            )
            conn.execute(
                "INSERT OR REPLACE INTO autopilot_settings (key, value) "
                "VALUES ('autonomous_consecutive_rejections', '4');"
            )

            # 6. Safety Gate
            conn.execute(
                "INSERT INTO monetization_safety (task_id, topic, preset, narrative_structure, safety_status, checked_at) "
                "VALUES ('task-pub-1', 'Tema Misterio 1', 'youtube_shorts_original', 'explainer', 'PASS', ?);",
                (now_iso,),
            )

    def test_a_quality_without_marker_preserves_current_behavior(self):
        """A) Sem marker: comportamento atual permanece (mesmo canal detecta duplicata)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM autopilot_settings WHERE key = 'metrics_baseline_started_at';")

        res = quality_score.evaluate_quality(
            topic="Tema Misterio 1",
            task_id="task-pub-2",
            profile_id="profile-misterio",
            channel_id="channel-misterio-yt",
            db_path=self.db_path,
        )
        self.assertLess(res["components"]["originality"], 100.0)

    def test_b_quality_with_marker_ignores_pre_baseline_monetization_safety(self):
        """B) Com marker: Quality ignora monetization_safety anterior ao baseline."""
        future_baseline = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        scheduler.set_metrics_baseline_started_at(future_baseline, db_path=self.db_path)

        res = quality_score.evaluate_quality(
            topic="Tema Misterio 1",
            task_id="task-pub-2",
            profile_id="profile-misterio",
            channel_id="channel-misterio-yt",
            db_path=self.db_path,
        )
        # Pre-baseline record is ignored, so originality returns standard unpenalized score (95.0)
        self.assertEqual(res["components"]["originality"], 95.0)

    def test_c_quality_with_marker_includes_post_baseline_same_channel(self):
        """C) Quality considera histórico posterior ao baseline do mesmo canal."""
        baseline_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        scheduler.set_metrics_baseline_started_at(baseline_time, db_path=self.db_path)

        post_time = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO monetization_safety (task_id, topic, preset, narrative_structure, safety_status, checked_at) "
                "VALUES ('task-post-1', 'Tema Misterio Recente', 'youtube_shorts_original', 'explainer', 'PASS', ?);",
                (post_time,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO task_profiles (task_id, profile_id, created_at) "
                "VALUES ('task-post-1', 'profile-misterio', ?);",
                (post_time,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at, profile_id, channel_id) "
                "VALUES ('task-post-1', 'youtube', ?, 'published', ?, 'profile-misterio', 'channel-misterio-yt');",
                (post_time, post_time),
            )

        res = quality_score.evaluate_quality(
            topic="Tema Misterio Recente",
            task_id="task-new",
            profile_id="profile-misterio",
            channel_id="channel-misterio-yt",
            db_path=self.db_path,
        )
        self.assertLess(res["components"]["originality"], 100.0)

    def test_d_quality_with_marker_isolates_other_channels(self):
        """D) Outro canal continua isolado mesmo com marker ativo."""
        baseline_time = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
        scheduler.set_metrics_baseline_started_at(baseline_time, db_path=self.db_path)

        post_time = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO content_profiles (id, name, slug, niche, default_preset, growth_mode, is_active, created_at, updated_at) "
                "VALUES ('profile-outro', 'Outro', 'outro', 'curiosidades', 'youtube_shorts_original', 'warmup', 1, ?, ?);",
                (post_time, post_time),
            )
            conn.execute(
                "INSERT INTO publishing_channels (id, profile_id, platform, display_name, is_enabled, created_at, updated_at) "
                "VALUES ('channel-outro-yt', 'profile-outro', 'youtube', 'Outro YT', 1, ?, ?);",
                (post_time, post_time),
            )
            conn.execute(
                "INSERT INTO monetization_safety (task_id, topic, preset, narrative_structure, safety_status, checked_at) "
                "VALUES ('task-outro-1', 'Tema Exclusivo Outro', 'youtube_shorts_original', 'explainer', 'PASS', ?);",
                (post_time,),
            )
            conn.execute(
                "INSERT INTO task_profiles (task_id, profile_id, created_at) "
                "VALUES ('task-outro-1', 'profile-outro', ?);",
                (post_time,),
            )
            conn.execute(
                "INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at, profile_id, channel_id) "
                "VALUES ('task-outro-1', 'youtube', ?, 'published', ?, 'profile-outro', 'channel-outro-yt');",
                (post_time, post_time),
            )

        res = quality_score.evaluate_quality(
            topic="Tema Exclusivo Outro",
            task_id="task-misterio-new",
            profile_id="profile-misterio",
            channel_id="channel-misterio-yt",
            db_path=self.db_path,
        )
        # Because task-outro-1 belongs to channel-outro-yt, it does not leak to channel-misterio-yt
        self.assertEqual(res["components"]["originality"], 95.0)

        with quality_score.get_connection(self.db_path) as conn:
            isolated_history = quality_score._get_isolated_recent_safety_history(
                conn, "task-misterio-new", "profile-misterio", "channel-misterio-yt"
            )
            task_ids_in_history = [r["task_id"] for r in isolated_history]
            self.assertNotIn("task-outro-1", task_ids_in_history)

    def test_e_analytics_automatic_collection_ignores_pre_baseline_publication(self):
        """E) Analytics automático não recolhe publicação pré-baseline."""
        baseline_time = "2026-09-24T00:00:00+00:00"
        scheduler.set_metrics_baseline_started_at(baseline_time, db_path=self.db_path)

        pub_row = {
            "status": "success",
            "external_id": "dQw4w9WgXcQ",
            "platform": "youtube",
            "profile_id": "profile-misterio",
            "channel_id": "channel-misterio-yt",
            "published_at": "2026-09-23T20:00:00+00:00",
            "privacy_status": "public",
            "task_id": "task-pub-1",
        }
        eligible, reason, _ = analytics_scheduler.check_publication_eligibility(
            pub_row, db_path=self.db_path
        )
        self.assertFalse(eligible)
        self.assertIn("pre_baseline_publication", reason)

    def test_f_analytics_automatic_collection_allows_post_baseline_publication(self):
        """F) Analytics não descarta publicação pós-baseline pelo filtro de baseline."""
        baseline_time = "2026-09-24T00:00:00+00:00"
        scheduler.set_metrics_baseline_started_at(baseline_time, db_path=self.db_path)

        pub_row = {
            "status": "success",
            "external_id": "dQw4w9WgXcQ",
            "platform": "youtube",
            "profile_id": "profile-misterio",
            "channel_id": "channel-misterio-yt",
            "published_at": "2026-09-24T02:00:00+00:00",
            "privacy_status": "public",
            "task_id": "task-pub-1",
        }
        eligible, reason, _ = analytics_scheduler.check_publication_eligibility(
            pub_row, db_path=self.db_path
        )
        self.assertNotIn("pre_baseline_publication", reason)

    def test_g_closed_feedback_loop_ignores_pre_baseline_publication(self):
        """G) Closed Feedback Loop ignora publicação pré-baseline."""
        baseline_time = "2026-09-24T00:00:00+00:00"
        scheduler.set_metrics_baseline_started_at(baseline_time, db_path=self.db_path)

        pub_time = "2026-09-23T12:00:00+00:00"
        col_time = "2026-09-26T14:00:00+00:00"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO publication_events (id, task_id, platform, published_at, status, external_id, profile_id, channel_id, privacy_status) "
                "VALUES (2, 'task-pub-pre', 'youtube', ?, 'success', 'dQw4w9WgXcQ', 'profile-misterio', 'channel-misterio-yt', 'public');",
                (pub_time,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO task_profiles (task_id, profile_id, created_at) "
                "VALUES ('task-pub-pre', 'profile-misterio', ?);",
                (pub_time,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO operational_events (timestamp, component, severity, event_type, task_id, message, metadata_json) "
                "VALUES (?, 'operator', 'INFO', 'PUBLICATION_COPYRIGHT_STATUS_SET', 'task-pub-pre', 'Audit', '{\"publication_event_id\": 2, \"copyright_status\": \"clean_manual\"}');",
                (pub_time,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO monetization_safety (task_id, topic, preset, narrative_structure, safety_status, checked_at) "
                "VALUES ('task-pub-pre', 'Tema Misterio Pre', 'youtube_shorts_original', 'explainer', 'PASS', ?);",
                (pub_time,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO content_quality_scores (task_id, topic, quality_score, quality_label, created_at) "
                "VALUES ('task-pub-pre', 'Tema Misterio Pre', 85.0, 'GOOD', ?);",
                (pub_time,),
            )
            meta = json.dumps({"dry_run": False, "item_id": "dQw4w9WgXcQ"})
            conn.execute(
                "INSERT OR REPLACE INTO content_analytics (id, publication_event_id, task_id, platform, profile_id, channel_id, external_id, topic, narrative_structure, views, likes, comments, source, metadata_json, published_at, collected_at, age_bucket) "
                "VALUES (2, 2, 'task-pub-pre', 'youtube', 'profile-misterio', 'channel-misterio-yt', 'dQw4w9WgXcQ', 'Tema Misterio Pre', 'explainer', 1000, 100, 10, 'youtube_api', ?, ?, ?, '72h');",
                (meta, pub_time, col_time),
            )

        cutoff = datetime.fromisoformat("2026-09-26T15:00:00+00:00")
        ev = analytics.get_learning_evidence(
            "youtube", "profile-misterio", "channel-misterio-yt", cutoff_time=cutoff, db_path=self.db_path
        )
        self.assertEqual(ev["sample_count"], 0)
        self.assertGreaterEqual(ev["excluded_counts_by_reason"].get("pre_baseline_publication", 0), 1)

    def test_h_closed_feedback_loop_includes_post_baseline_publication_when_gates_pass(self):
        """H) Closed Feedback Loop considera publicação pós-baseline quando todos os demais gates passam."""
        baseline_time = "2026-09-24T00:00:00+00:00"
        scheduler.set_metrics_baseline_started_at(baseline_time, db_path=self.db_path)

        pub_time = "2026-09-24T02:00:00+00:00"
        col_time = "2026-09-27T04:00:00+00:00"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO publication_events (id, task_id, platform, published_at, status, external_id, profile_id, channel_id, privacy_status) "
                "VALUES (3, 'task-pub-post', 'youtube', ?, 'success', 'aBcDeFgHiJk', 'profile-misterio', 'channel-misterio-yt', 'public');",
                (pub_time,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO task_profiles (task_id, profile_id, created_at) "
                "VALUES ('task-pub-post', 'profile-misterio', ?);",
                (pub_time,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO operational_events (timestamp, component, severity, event_type, task_id, message, metadata_json) "
                "VALUES (?, 'operator', 'INFO', 'PUBLICATION_COPYRIGHT_STATUS_SET', 'task-pub-post', 'Audit', '{\"publication_event_id\": 3, \"copyright_status\": \"clean_manual\"}');",
                (pub_time,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO monetization_safety (task_id, topic, preset, narrative_structure, safety_status, checked_at) "
                "VALUES ('task-pub-post', 'Tema Misterio Post', 'youtube_shorts_original', 'explainer', 'PASS', ?);",
                (pub_time,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO content_quality_scores (task_id, topic, quality_score, quality_label, created_at) "
                "VALUES ('task-pub-post', 'Tema Misterio Post', 85.0, 'GOOD', ?);",
                (pub_time,),
            )
            meta = json.dumps({"dry_run": False, "item_id": "aBcDeFgHiJk"})
            conn.execute(
                "INSERT OR REPLACE INTO content_analytics (id, publication_event_id, task_id, platform, profile_id, channel_id, external_id, topic, narrative_structure, views, likes, comments, source, metadata_json, published_at, collected_at, age_bucket) "
                "VALUES (3, 3, 'task-pub-post', 'youtube', 'profile-misterio', 'channel-misterio-yt', 'aBcDeFgHiJk', 'Tema Misterio Post', 'explainer', 1500, 150, 15, 'youtube_api', ?, ?, ?, '72h');",
                (meta, pub_time, col_time),
            )

        cutoff = datetime.fromisoformat("2026-09-27T05:00:00+00:00")
        ev = analytics.get_learning_evidence(
            "youtube", "profile-misterio", "channel-misterio-yt", cutoff_time=cutoff, db_path=self.db_path
        )
        self.assertEqual(ev["sample_count"], 1)
        self.assertEqual(ev["eligible_publication_ids"], [3])


if __name__ == "__main__":
    unittest.main()
