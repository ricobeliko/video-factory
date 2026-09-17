import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from app.services import analytics, scheduler, trend_radar
from app.services.trends.base import TrendSignal


class TestAnalytics(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_analytics_")
        self.db_path = os.path.join(self.test_dir, "analytics_test.db")
        analytics.DB_PATH = self.db_path
        trend_radar.DB_PATH = self.db_path
        scheduler.init_db(self.db_path)
        analytics.init_analytics_db(self.db_path)
        trend_radar.init_trend_db(self.db_path)


    def tearDown(self):
        analytics.DB_PATH = None
        trend_radar.DB_PATH = None
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_save_snapshot(self):
        """1. Salvar snapshot com sucesso e verificar integridade dos campos."""
        now = datetime.now(timezone.utc)
        snap = analytics.save_snapshot(
            task_id="task-001",
            platform="youtube",
            views=1000,
            likes=100,
            comments=20,
            shares=10,
            published_at=now - timedelta(hours=10),
            collected_at=now,
            db_path=self.db_path,
        )
        self.assertIsNotNone(snap["id"])
        self.assertEqual(snap["task_id"], "task-001")
        self.assertEqual(snap["platform"], "youtube")
        self.assertEqual(snap["views"], 1000)
        self.assertEqual(snap["likes"], 100)
        self.assertEqual(snap["engagement_rate"], 0.13)
        self.assertEqual(snap["age_bucket"], analytics.BUCKET_0_24H)
        self.assertGreater(snap["performance_score"], 0.0)

    def test_02_multiple_snapshots_same_video(self):
        """2. Múltiplos snapshots cumulativos do mesmo vídeo sem sobrescrever histórico."""
        base_time = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
        
        # Snapshot 24h
        s1 = analytics.save_snapshot(
            task_id="task-multi",
            platform="youtube",
            views=500,
            likes=40,
            published_at=base_time,
            collected_at=base_time + timedelta(hours=24),
            db_path=self.db_path,
        )
        
        # Snapshot 72h
        s2 = analytics.save_snapshot(
            task_id="task-multi",
            platform="youtube",
            views=1200,
            likes=95,
            published_at=base_time,
            collected_at=base_time + timedelta(hours=72),
            db_path=self.db_path,
        )

        all_snaps = analytics.get_snapshots(task_id="task-multi", latest_only=False, db_path=self.db_path)
        self.assertEqual(len(all_snaps), 2)
        self.assertEqual(all_snaps[0]["views"], 1200)
        self.assertEqual(all_snaps[1]["views"], 500)

        latest = analytics.get_snapshots(task_id="task-multi", latest_only=True, db_path=self.db_path)
        self.assertEqual(len(latest), 1)
        self.assertEqual(latest[0]["views"], 1200)

    def test_03_validate_negatives(self):
        """3. Validação de métricas negativas rejeita chamadas inválidas."""
        with self.assertRaises(ValueError):
            analytics.save_snapshot(task_id="t1", platform="tiktok", views=-1, db_path=self.db_path)
        with self.assertRaises(ValueError):
            analytics.save_snapshot(task_id="t1", platform="tiktok", likes=-5, db_path=self.db_path)
        with self.assertRaises(ValueError):
            analytics.save_snapshot(task_id="t1", platform="tiktok", comments=-2, db_path=self.db_path)
        with self.assertRaises(ValueError):
            analytics.save_snapshot(task_id="t1", platform="tiktok", shares=-10, db_path=self.db_path)
        with self.assertRaises(ValueError):
            analytics.save_snapshot(task_id="t1", platform="tiktok", favorites=-1, db_path=self.db_path)
        with self.assertRaises(ValueError):
            analytics.save_snapshot(task_id="t1", platform="tiktok", average_view_duration=-0.5, db_path=self.db_path)

    def test_04_percentage_over_100_rejected(self):
        """4. Porcentagens maiores que 100% devem ser rejeitadas."""
        with self.assertRaises(ValueError):
            analytics.save_snapshot(
                task_id="t2", platform="youtube", average_percentage_viewed=105.0, db_path=self.db_path
            )
        with self.assertRaises(ValueError):
            analytics.save_snapshot(
                task_id="t2", platform="tiktok", completion_rate=100.1, db_path=self.db_path
            )

    def test_05_engagement_rate(self):
        """5. Cálculo determinístico da taxa de engajamento."""
        eng = analytics.calculate_engagement_rate(views=2000, likes=150, comments=30, shares=20)
        self.assertEqual(eng, 0.10)

        # Divisão por zero segura
        eng_zero = analytics.calculate_engagement_rate(views=0, likes=10, comments=5, shares=2)
        self.assertEqual(eng_zero, 0.0)

    def test_06_retention_none_when_absent(self):
        """6. Retention score ausente retorna estritamente None."""
        ret = analytics.calculate_retention_score(completion_rate=None, average_percentage_viewed=None)
        self.assertIsNone(ret)

        # Se completion_rate fornecido
        ret_comp = analytics.calculate_retention_score(completion_rate=72.5)
        self.assertEqual(ret_comp, 72.5)

        # Se average_percentage_viewed fornecido
        ret_avg = analytics.calculate_retention_score(average_percentage_viewed=58.3)
        self.assertEqual(ret_avg, 58.3)

    def test_07_bucket_0_24h(self):
        """7. Bucket de idade 0–24h para medições nas primeiras 24 horas."""
        p_at = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
        c_at = datetime(2026, 9, 1, 18, 30, tzinfo=timezone.utc)
        bucket = analytics.calculate_age_bucket(p_at, c_at)
        self.assertEqual(bucket, analytics.BUCKET_0_24H)

    def test_08_bucket_24_72h(self):
        """8. Bucket de idade 24–72h para medições entre 24 e 72 horas."""
        p_at = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
        c_at = datetime(2026, 9, 2, 16, 0, tzinfo=timezone.utc)  # 30h
        bucket = analytics.calculate_age_bucket(p_at, c_at)
        self.assertEqual(bucket, analytics.BUCKET_24_72H)

    def test_09_platform_separated_normalization(self):
        """9. Normalização separada por plataforma: YouTube e TikTok não se contaminam."""
        # Popula histórico no YouTube
        for v in [100, 200, 300]:
            analytics.save_snapshot(
                task_id=f"yt-{v}", platform="youtube", views=v, likes=10, db_path=self.db_path
            )
        # Popula histórico no TikTok
        for v in [10000, 20000, 30000]:
            analytics.save_snapshot(
                task_id=f"tk-{v}", platform="tiktok", views=v, likes=1000, db_path=self.db_path
            )

        yt_item = analytics.save_snapshot(
            task_id="yt-target", platform="youtube", views=350, likes=20, db_path=self.db_path
        )
        tk_item = analytics.save_snapshot(
            task_id="tk-target", platform="tiktok", views=350, likes=20, db_path=self.db_path
        )

        # 350 views no YouTube é o topo do histórico -> score alto
        # 350 views no TikTok é muito abaixo do histórico -> score baixo
        self.assertGreater(yt_item["performance_score"], tk_item["performance_score"])

    def test_10_performance_score_uses_only_available_metrics(self):
        """10. Performance score não penaliza injustamente métrica ausente."""
        # Item com views e likes apenas (sem retenção)
        hist = [{"views": 500, "engagement_rate": 0.05, "retention_score": None}]
        score_no_ret = analytics.calculate_performance_score(
            views=500, engagement_rate=0.05, retention_score=None, history_items=hist
        )
        self.assertGreaterEqual(score_no_ret, 50.0)

    def test_11_association_task_id(self):
        """11. Associação automática com task_id e enriquecimento de metadados."""
        from app.services import safety_gate
        safety_gate.init_safety_db(self.db_path)
        safety_gate.save_safety_assessment(
            {
                "task_id": "task-assoc",
                "topic": "Curiosidade Espacial",
                "preset": "curiosities",
                "narrative_structure": "investigative_mystery",
                "actual_duration": 45.2,
                "safety_status": "APPROVED",
            },
            db_path=self.db_path,
        )

        snap = analytics.save_snapshot(
            task_id="task-assoc", platform="youtube", views=500, likes=30, db_path=self.db_path
        )
        self.assertEqual(snap["topic"], "Curiosidade Espacial")
        self.assertEqual(snap["preset"], "curiosities")
        self.assertEqual(snap["narrative_structure"], "investigative_mystery")
        self.assertEqual(snap["duration_seconds"], 45.2)

    def test_12_association_trend_id(self):
        """12. Associação correta com trend_id."""
        sig = TrendSignal(
            source="google_trends",
            source_key="oceanos",
            title="Por que o oceano é azul?",
            trend_score=75.0,
        )
        trend_id = trend_radar.upsert_trend_item(sig, niche="Curiosidades", db_path=self.db_path)

        snap = analytics.save_snapshot(
            task_id="task-tr",
            platform="youtube",
            trend_id=trend_id,
            views=1500,
            likes=120,
            db_path=self.db_path,
        )
        self.assertEqual(snap["trend_id"], trend_id)


    def test_13_feedback_by_narrative_structure(self):
        """13. Feedback agregador por narrative_structure com cálculo de relative_diff."""
        # Salva itens de estruturas diferentes
        analytics.save_snapshot(
            task_id="t-struct-1", platform="youtube", narrative_structure="investigative_mystery",
            views=5000, likes=500, comments=50, db_path=self.db_path
        )
        analytics.save_snapshot(
            task_id="t-struct-2", platform="youtube", narrative_structure="short_story",
            views=100, likes=5, comments=1, db_path=self.db_path
        )

        fb = analytics.get_content_performance_feedback(db_path=self.db_path)
        self.assertIn("investigative_mystery", fb["structures"])
        self.assertIn("short_story", fb["structures"])

        mystery_data = fb["structures"]["investigative_mystery"]
        story_data = fb["structures"]["short_story"]

        self.assertGreater(mystery_data["avg_performance"], story_data["avg_performance"])
        self.assertGreater(mystery_data["relative_diff"], story_data["relative_diff"])

    def test_14_feedback_by_preset(self):
        """14. Feedback agregador por preset de monetização."""
        analytics.save_snapshot(
            task_id="t-pre-1", platform="tiktok", preset="curiosities", views=3000, likes=200, db_path=self.db_path
        )
        analytics.save_snapshot(
            task_id="t-pre-2", platform="tiktok", preset="educational", views=1000, likes=50, db_path=self.db_path
        )

        fb = analytics.get_content_performance_feedback(platform="tiktok", db_path=self.db_path)
        self.assertIn("curiosities", fb["presets"])
        self.assertIn("educational", fb["presets"])
        self.assertGreater(fb["presets"]["curiosities"]["avg_performance"], fb["presets"]["educational"]["avg_performance"])

    def test_15_feedback_by_trend_source(self):
        """15. Feedback agregador relacionando performance à fonte original do Trend Radar."""
        sig_gt = TrendSignal(
            source="google_trends", source_key="gt-k", title="Tema GT", trend_score=80.0
        )
        tid_gt = trend_radar.upsert_trend_item(sig_gt, db_path=self.db_path)

        sig_rss = TrendSignal(
            source="rss", source_key="rss-k", title="Tema RSS", trend_score=60.0
        )
        tid_rss = trend_radar.upsert_trend_item(sig_rss, db_path=self.db_path)

        analytics.save_snapshot(
            task_id="t-tr-gt", platform="youtube", trend_id=tid_gt, views=4000, likes=300, db_path=self.db_path
        )
        analytics.save_snapshot(
            task_id="t-tr-rss", platform="youtube", trend_id=tid_rss, views=800, likes=40, db_path=self.db_path
        )

        perf = analytics.get_trend_source_performance(db_path=self.db_path)
        self.assertIn("google_trends", perf)
        self.assertIn("rss", perf)
        self.assertGreater(perf["google_trends"]["avg_performance"], perf["rss"]["avg_performance"])

    def test_16_persistence_after_restart(self):
        """16. Dados gravados permanecem íntegros após reabertura de conexão."""
        analytics.save_snapshot(
            task_id="t-persist",
            platform="youtube",
            views=777,
            likes=88,
            topic="Persistência SQLite",
            preset="curiosities",
            db_path=self.db_path,
        )

        # Simula reinício limpando referências e reabrindo
        del analytics.DB_PATH
        analytics.DB_PATH = self.db_path

        snaps = analytics.get_snapshots(task_id="t-persist", db_path=self.db_path)
        self.assertEqual(len(snaps), 1)
        self.assertEqual(snaps[0]["topic"], "Persistência SQLite")
        self.assertEqual(snaps[0]["views"], 777)
        self.assertEqual(snaps[0]["likes"], 88)

    def test_17_autopilot_integration_with_performance_context(self):
        """17. Autopilot integra feedback de performance sem destruir variedade nem violar anti-repetição."""
        from app.services import autopilot

        perf_ctx = {
            "structures": {
                "investigative_mystery": {"relative_diff": 25.0},
                "explainer": {"relative_diff": 10.0},
                "short_story": {"relative_diff": -15.0},
            }
        }
        assigned = autopilot.assign_batch_narrative_structures(
            selected_count=5,
            recent_structures=["short_story"],
            performance_context=perf_ctx,
        )
        self.assertEqual(len(assigned), 5)
        # O primeiro não pode repetir o último recente
        self.assertNotEqual(assigned[0], "short_story")
        # Deve preferir a melhor estrutura no início se não colidir
        self.assertEqual(assigned[0], "investigative_mystery")
        # Dois consecutivos nunca são iguais
        for i in range(len(assigned) - 1):
            self.assertNotEqual(assigned[i], assigned[i + 1])

    def test_18_analytics_provider_stubs(self):
        """18. Interfaces e stubs de providers para YouTube e TikTok não realizam chamadas externas."""
        yt_prov = analytics.YouTubeAnalyticsProvider()
        tk_prov = analytics.TikTokAnalyticsProvider()

        self.assertEqual(yt_prov.platform, "youtube")
        self.assertEqual(tk_prov.platform, "tiktok")
        self.assertIsNone(yt_prov.fetch_metrics("ext-yt-123"))
        self.assertIsNone(tk_prov.fetch_metrics("ext-tk-456"))


if __name__ == "__main__":
    unittest.main()

