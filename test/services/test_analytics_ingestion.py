"""
Tests for Analytics Ingestion Service and Snapshot Compatibility.
V10-A — Automatic Analytics Provider Foundation.
"""
import os
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from app.services import analytics
from app.services import analytics_ingestion
from app.services import profile_manager
from app.services import scheduler
from app.services.analytics_providers import (
    AnalyticsProviderError,
    ERR_AUTH,
    NormalizedAnalytics,
    YouTubeAnalyticsProvider,
    register_provider,
)


class TestAnalyticsIngestion(unittest.TestCase):
    """Testes para o pipeline de ingestão de analytics, compatibilidade e isolamento de perfis."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_factory.db")
        scheduler.init_db(self.db_path)
        analytics.init_analytics_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_manual_snapshot_preserved(self):
        """11. source manual preservado e 14. Snapshots manuais continuam funcionando."""
        snap = analytics.save_snapshot(
            task_id="task_manual_1",
            platform="youtube",
            views=1000,
            likes=100,
            comments=10,
            shares=5,
            db_path=self.db_path,
        )
        self.assertEqual(snap["source"], "manual")
        self.assertEqual(snap["views"], 1000)
        self.assertGreater(snap["performance_score"], 0.0)

        # Recupera e confirma que o source é retornado como manual
        snapshots = analytics.get_snapshots(task_id="task_manual_1", db_path=self.db_path)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["source"], "manual")

    def test_ingestion_resolves_correct_task_profile_and_channel(self):
        """15. Ingestion resolve task correta, 16. Profile original, 17. Channel original."""
        # Registra publicação bem-sucedida para task_A
        scheduler.record_publication_event(
            task_id="task_A",
            platform="youtube",
            status="success",
            external_id="yt_video_100",
            profile_id="profile_invest",
            channel_id="chan_yt_invest",
            external_url="https://www.youtube.com/watch?v=yt_video_100",
            db_path=self.db_path,
        )

        ref = analytics_ingestion.get_published_content_reference(
            task_id="task_A",
            platform="youtube",
            db_path=self.db_path,
        )
        self.assertEqual(ref.task_id, "task_A")
        self.assertEqual(ref.profile_id, "profile_invest")
        self.assertEqual(ref.channel_id, "chan_yt_invest")
        self.assertEqual(ref.external_post_id, "yt_video_100")
        self.assertEqual(ref.external_url, "https://www.youtube.com/watch?v=yt_video_100")

    def test_active_profile_does_not_influence_analytics(self):
        """18. active profile não influencia analytics (isolamento estrito)."""
        # Cria dois perfis
        profile_manager.create_profile("Investimentos", profile_id="profile_invest", db_path=self.db_path)
        profile_manager.create_profile("Humor", profile_id="profile_humor", db_path=self.db_path)

        # Publicação foi feita pelo profile_invest
        scheduler.record_publication_event(
            task_id="task_B",
            platform="youtube",
            status="success",
            external_id="yt_video_200",
            profile_id="profile_invest",
            channel_id="chan_yt_invest",
            db_path=self.db_path,
        )

        # Simula troca do perfil ativo global para profile_humor
        profile_manager.set_active_profile("profile_humor", db_path=self.db_path)
        self.assertEqual(profile_manager.get_active_profile_id(self.db_path), "profile_humor")

        # Ingestão em dry_run
        snap = analytics_ingestion.ingest_analytics_for_publication(
            task_id="task_B",
            platform="youtube",
            dry_run=True,
            db_path=self.db_path,
        )

        # O snapshot gerado DEVE pertencer a profile_invest, NUNCA ao active profile atual (profile_humor)
        self.assertEqual(snap["profile_id"], "profile_invest")
        self.assertEqual(snap["channel_id"], "chan_yt_invest")

    def test_source_youtube_api_persisted(self):
        """12. source youtube_api persistido."""
        scheduler.record_publication_event(
            task_id="task_yt",
            platform="youtube",
            status="success",
            external_id="yt_video_300",
            profile_id="profile_default",
            db_path=self.db_path,
        )

        snap = analytics_ingestion.ingest_analytics_for_publication(
            task_id="task_yt",
            platform="youtube",
            dry_run=True,
            db_path=self.db_path,
        )
        self.assertEqual(snap["source"], "youtube_api")
        self.assertEqual(snap["external_id"], "yt_video_300")

    def test_source_tiktok_api_persisted(self):
        """13. source tiktok_api persistido."""
        scheduler.record_publication_event(
            task_id="task_tt",
            platform="tiktok",
            status="success",
            external_id="tt_video_400",
            profile_id="profile_default",
            db_path=self.db_path,
        )

        snap = analytics_ingestion.ingest_analytics_for_publication(
            task_id="task_tt",
            platform="tiktok",
            dry_run=True,
            db_path=self.db_path,
        )
        self.assertEqual(snap["source"], "tiktok_api")
        self.assertEqual(snap["external_id"], "tt_video_400")

    def test_provider_failure_does_not_alter_task_status(self):
        """19. failure de provider não altera task status (Analytics failure != publication failure)."""
        scheduler.record_publication_event(
            task_id="task_failed_analytics",
            platform="youtube",
            status="success",
            external_id="yt_fail_500",
            db_path=self.db_path,
        )

        # Mock de erro no provider
        mock_provider = MagicMock(spec=YouTubeAnalyticsProvider)
        mock_provider.platform = "youtube"
        mock_provider.provider_name = "youtube_api"
        mock_provider.fetch_metrics.side_effect = AnalyticsProviderError("Auth failed", code=ERR_AUTH)

        register_provider("youtube", mock_provider)
        try:
            with self.assertRaises(AnalyticsProviderError):
                analytics_ingestion.ingest_analytics_for_publication(
                    task_id="task_failed_analytics",
                    platform="youtube",
                    dry_run=False,
                    db_path=self.db_path,
                )

            # Verifica se o evento de publicação original continua 'success'
            with scheduler.get_connection(self.db_path) as conn:
                row = conn.execute(
                    "SELECT status FROM publication_events WHERE task_id = 'task_failed_analytics';"
                ).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row["status"], "success")
        finally:
            # Restaura provider original
            register_provider("youtube", YouTubeAnalyticsProvider())

    def test_idempotence_preserved(self):
        """23. idempotência preservada: mesma publicação + provider + timestamp não duplica."""
        scheduler.record_publication_event(
            task_id="task_idem",
            platform="youtube",
            status="success",
            external_id="yt_idem_600",
            db_path=self.db_path,
        )

        fixed_time = "2026-09-18T10:00:00+00:00"
        snap1 = analytics_ingestion.ingest_analytics_for_publication(
            task_id="task_idem",
            platform="youtube",
            dry_run=True,
            collected_at=fixed_time,
            db_path=self.db_path,
        )
        id1 = snap1["id"]

        # Segunda chamada com o mesmo collected_at exato
        snap2 = analytics_ingestion.ingest_analytics_for_publication(
            task_id="task_idem",
            platform="youtube",
            dry_run=True,
            collected_at=fixed_time,
            db_path=self.db_path,
        )
        id2 = snap2["id"]

        self.assertEqual(id1, id2)

        # Confirma que só existe 1 registro no banco
        snapshots = analytics.get_snapshots(task_id="task_idem", db_path=self.db_path)
        self.assertEqual(len(snapshots), 1)

    def test_legacy_content_continues_readable(self):
        """24. legacy content continua legível (source assume manual)."""
        # Insere registro simulando schema legado onde source e profile_id eram nulos
        with analytics.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO content_analytics (
                    task_id, platform, external_id, views, published_at, collected_at, age_bucket
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                ("task_legacy", "youtube", "yt_leg_700", 500, "2026-09-01T00:00:00+00:00", "2026-09-02T00:00:00+00:00", "0-24h"),
            )

        snaps = analytics.get_snapshots(task_id="task_legacy", db_path=self.db_path)
        self.assertEqual(len(snaps), 1)
        self.assertEqual(snaps[0]["source"], "manual")
        self.assertEqual(snaps[0]["views"], 500)

    def test_dry_run_no_external_mutation(self):
        """27. nenhuma mutation externa em dry_run."""
        scheduler.record_publication_event(
            task_id="task_dry",
            platform="youtube",
            status="success",
            external_id="yt_dry_800",
            db_path=self.db_path,
        )

        with patch("requests.get") as mock_get:
            snap = analytics_ingestion.ingest_analytics_for_publication(
                task_id="task_dry",
                platform="youtube",
                dry_run=True,
                db_path=self.db_path,
            )
            mock_get.assert_not_called()
            self.assertEqual(snap["task_id"], "task_dry")

    def test_no_new_workers_and_single_instance_preserved(self):
        """28. nenhum worker novo e 29. single-instance architecture preservada."""
        active_threads_before = threading.active_count()
        # Chama rotinas do provider e da ingestão
        provider = analytics_ingestion.get_provider("youtube")
        status = provider.get_status(db_path=self.db_path)
        active_threads_after = threading.active_count()

        # Nenhuma thread daemon ou worker extra foi disparada
        self.assertEqual(active_threads_before, active_threads_after)

    def test_scoring_existing_not_duplicated(self):
        """30. scoring existente não duplicado: cálculos vêm de analytics.py."""
        scheduler.record_publication_event(
            task_id="task_score",
            platform="youtube",
            status="success",
            external_id="yt_score_900",
            db_path=self.db_path,
        )

        snap = analytics_ingestion.ingest_analytics_for_publication(
            task_id="task_score",
            platform="youtube",
            dry_run=True,
            db_path=self.db_path,
        )
        # engagement_rate e performance_score foram calculados pelas funções matemáticas de analytics.py
        self.assertIn("performance_score", snap)
        self.assertIn("engagement_rate", snap)
        self.assertIn("retention_score", snap)


if __name__ == "__main__":
    unittest.main()
