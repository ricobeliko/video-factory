"""
Tests for Automatic Analytics Collection Scheduler.
Fase V10-C — Automatic Analytics Collection Scheduler.

Cobre rigorosamente todos os 40 requisitos especificados:
1. auto collection default disabled
2. enable requires PRIMARY
3. VIEW ONLY não habilita
4. disabled não executa fetch
5. PAUSED não executa fetch
6. publication sem external ID ignorada
7. publication failed ignorada
8. unsupported platform ignorada
9. provider not configured ignorado
10. first snapshot eligible
11. recent snapshot respeita cooldown
12. 0–6h usa janela 60m
13. 6–24h usa janela 3h
14. 1–3d usa janela 6h
15. 3–7d usa janela 12h
16. 7–30d usa janela 24h
17. >30d não coleta
18. max 3 fetches por ciclo
19. prioridade sem snapshot primeiro
20. múltiplos profiles não multiplicam limite
21. multiple channels preservam isolamento
22. analytics usa profile/channel original
23. AUTH_ERROR aplica backoff
24. RATE_LIMIT aplica backoff
25. TEMPORARY aplica backoff
26. NOT_FOUND não retry imediato
27. UNAVAILABLE aplica backoff
28. failure não altera task
29. failure não altera publication
30. success cria snapshot
31. source correto
32. idempotência da janela
33. próximo ciclo futuro pode criar novo snapshot
34. operational event success
35. operational event failure/backoff
36. nenhum secret em eventos
37. private YouTube conhecido é skip
38. Run One Cycle respeita limite
39. scheduler único preservado
40. nenhum worker/thread novo

MANDATÓRIO:
100% chamadas externas MOCKADAS. Zero chamadas reais HTTP.
Zero tokens/chaves expostos.
"""
from datetime import datetime, timedelta, timezone
import json
import os
import tempfile
import threading
from typing import Any, Dict, List, Optional, Tuple
import unittest
from unittest.mock import MagicMock, patch

from app.services import (
    analytics,
    analytics_ingestion,
    analytics_scheduler,
    operator_console,
    profile_manager,
    scheduler,
)
from app.services.analytics_providers import (
    AnalyticsProvider,
    AnalyticsProviderError,
    ERR_AUTH,
    ERR_INVALID_RESPONSE,
    ERR_NOT_FOUND,
    ERR_RATE_LIMIT,
    ERR_TEMPORARY,
    ERR_UNAVAILABLE,
    NormalizedAnalytics,
    get_provider,
    register_provider,
)


class MockAnalyticsProvider(AnalyticsProvider):
    """Provedor mockado que simula respostas sem qualquer chamada HTTP externa."""

    def __init__(self, platform: str = "youtube", configured: bool = True):
        self._platform = platform
        self._configured = configured
        self.fetch_call_count = 0
        self.should_raise: Optional[Exception] = None
        self.mock_metrics = {
            "views": 1500,
            "likes": 120,
            "comments": 15,
            "shares": 5,
            "favorites": 2,
            "watch_time_seconds": 3600.0,
            "average_view_duration_seconds": 45.0,
            "average_view_percentage": 50.0,
            "retention_rate": 0.5,
            "followers_gained": 8,
        }

    @property
    def platform_name(self) -> str:
        return self._platform

    @property
    def platform(self) -> str:
        return self._platform

    @property
    def provider_name(self) -> str:
        return f"{self._platform}_api"

    def get_status(self, db_path: Optional[str] = None) -> str:
        return "CONFIGURED" if self._configured else "NOT_CONFIGURED"

    def validate_configuration(self, db_path: Optional[str] = None) -> dict:
        return {
            "configured": self._configured,
            "missing_fields": [] if self._configured else ["api_key"],
            "platform": self._platform,
        }

    def fetch_metrics(self, external_post_id: str, dry_run: bool = False) -> dict:
        self.fetch_call_count += 1
        if self.should_raise:
            raise self.should_raise
        return {
            "id": external_post_id,
            "statistics": {
                "viewCount": str(self.mock_metrics["views"]),
                "likeCount": str(self.mock_metrics["likes"]),
                "commentCount": str(self.mock_metrics["comments"]),
                "favoriteCount": str(self.mock_metrics["favorites"]),
            },
        }

    def normalize_metrics(
        self,
        raw_metrics: dict,
        external_post_id: str,
        external_url: Optional[str] = None,
    ) -> NormalizedAnalytics:
        return NormalizedAnalytics(
            platform=self._platform,
            provider=self.provider_name,
            external_post_id=external_post_id,
            external_url=external_url,
            collected_at=datetime.now(timezone.utc).isoformat(),
            views=self.mock_metrics["views"],
            likes=self.mock_metrics["likes"],
            comments=self.mock_metrics["comments"],
            shares=self.mock_metrics["shares"],
            favorites=self.mock_metrics["favorites"],
            average_view_duration_seconds=self.mock_metrics["average_view_duration_seconds"],
            average_view_percentage=self.mock_metrics["average_view_percentage"],
            retention_rate=self.mock_metrics["retention_rate"],
            followers_gained=self.mock_metrics["followers_gained"],
            raw_metadata={"mocked": True},
        )


class TestAnalyticsScheduler(unittest.TestCase):
    """Suíte de testes completa para a Fase V10-C."""

    def setUp(self):
        # ignore_cleanup_errors evita falha de teardown quando a thread real do
        # worker (ex.: test_39) toca o storage_dir patchado de forma concorrente.
        self.tmp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = os.path.join(self.tmp_dir.name, "test_factory.db")

        # Inicializa tabelas
        scheduler.init_db(self.db_path)
        analytics.init_analytics_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        operator_console.init_operator_db(self.db_path)

        # Garante instância PRIMARY por padrão nos testes
        operator_console.reset_instance_for_testing()
        operator_console.acquire_instance_lock(
            node_name="test-primary",
            timeout_seconds=30,
            db_path=self.db_path,
        )

        # Fábrica em RUNNING
        operator_console.set_factory_state(operator_console.FACTORY_STATE_RUNNING, db_path=self.db_path)

        # Salva provedores originais para restauração
        self._orig_yt = get_provider("youtube")
        self._orig_tt = get_provider("tiktok")

        # Provedores mockados
        self.mock_yt = MockAnalyticsProvider(platform="youtube", configured=True)
        self.mock_tt = MockAnalyticsProvider(platform="tiktok", configured=True)
        register_provider("youtube", self.mock_yt)
        register_provider("tiktok", self.mock_tt)

        self.base_time = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)

        # V12-F.1A: privacidade do YouTube passa a ser fail-closed (PUBLIC comprovado
        # é exigido). Todos os testes legados assumem publicação pública por padrão;
        # testes específicos de privacidade sobrescrevem via `_insert_publication`.
        self._storage_dir_patcher = patch("app.utils.utils.storage_dir", return_value=self.tmp_dir.name)
        self._storage_dir_patcher.start()

    def tearDown(self):
        self._storage_dir_patcher.stop()
        # Restaura provedores originais
        register_provider("youtube", self._orig_yt)
        register_provider("tiktok", self._orig_tt)
        operator_console.reset_instance_for_testing()
        self.tmp_dir.cleanup()

    def _write_task_privacy(self, task_id: str, youtube_privacy_status: Optional[str]) -> None:
        """Escreve (ou omite) task.json com o status de privacidade do YouTube."""
        if youtube_privacy_status is None:
            return
        task_dir = os.path.join(self.tmp_dir.name, "tasks", task_id)
        os.makedirs(task_dir, exist_ok=True)
        with open(os.path.join(task_dir, "task.json"), "w", encoding="utf-8") as f:
            json.dump({"publish_info": {"youtube_privacy_status": youtube_privacy_status}}, f)

    def _insert_publication(
        self,
        task_id: str,
        platform: str = "youtube",
        external_id: Optional[str] = "ext_vid_123",
        status: str = "success",
        published_at: Optional[datetime] = None,
        profile_id: Optional[str] = "default",
        channel_id: Optional[str] = None,
        youtube_privacy_status: Optional[str] = "public",
    ) -> int:
        """Helper para inserir evento de publicação. Por padrão, marca o YouTube como
        'public' comprovado (privacidade fail-closed exige isso para ser elegível)."""
        if platform == "youtube":
            self._write_task_privacy(task_id, youtube_privacy_status)
        p_at = published_at or self.base_time
        iso_p_at = p_at.isoformat()
        with scheduler.get_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO publication_events (
                    task_id, platform, published_at, status, external_id,
                    profile_id, channel_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (task_id, platform, iso_p_at, status, external_id, profile_id, channel_id),
            )
            return cursor.lastrowid

    # -----------------------------------------------------------------------
    # 1. auto collection default disabled
    # -----------------------------------------------------------------------
    def test_01_auto_collection_default_disabled(self):
        self.assertFalse(analytics_scheduler.is_analytics_auto_collection_enabled(db_path=self.db_path))

    # -----------------------------------------------------------------------
    # 2. enable requires PRIMARY
    # -----------------------------------------------------------------------
    def test_02_enable_requires_primary(self):
        # Em PRIMARY, habilitar funciona
        res = operator_console.set_analytics_auto_collection_enabled_op(True, db_path=self.db_path)
        self.assertTrue(res["success"])
        self.assertTrue(analytics_scheduler.is_analytics_auto_collection_enabled(db_path=self.db_path))

    # -----------------------------------------------------------------------
    # 3. VIEW ONLY não habilita
    # -----------------------------------------------------------------------
    def test_03_view_only_cannot_enable(self):
        # Simula nó secundário (VIEW ONLY)
        with patch.object(operator_console, "is_primary_instance", return_value=False):
            with self.assertRaises(PermissionError):
                operator_console.set_analytics_auto_collection_enabled_op(True, db_path=self.db_path)

    # -----------------------------------------------------------------------
    # 4. disabled não executa fetch
    # -----------------------------------------------------------------------
    def test_04_disabled_skips_fetch(self):
        self._insert_publication("t1", external_id="yt_1")
        analytics_scheduler.set_analytics_auto_collection_enabled(False, db_path=self.db_path)
        res = analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time)
        self.assertEqual(res["status"], "skipped")
        self.assertEqual(res["reason"], "disabled")
        self.assertEqual(self.mock_yt.fetch_call_count, 0)

    # -----------------------------------------------------------------------
    # 5. PAUSED não executa fetch
    # -----------------------------------------------------------------------
    def test_05_paused_skips_fetch(self):
        self._insert_publication("t1", external_id="yt_1")
        analytics_scheduler.set_analytics_auto_collection_enabled(True, db_path=self.db_path)
        operator_console.set_factory_state(operator_console.FACTORY_STATE_PAUSED, db_path=self.db_path)

        res = analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time)
        self.assertEqual(res["status"], "skipped")
        self.assertEqual(res["reason"], "factory_paused")
        self.assertEqual(self.mock_yt.fetch_call_count, 0)

    # -----------------------------------------------------------------------
    # 6. publication sem external ID ignorada
    # -----------------------------------------------------------------------
    def test_06_publication_without_external_id_skipped(self):
        self._insert_publication("t1", external_id=None)
        self._insert_publication("t2", external_id="")
        candidates = analytics_scheduler.get_eligible_analytics_candidates(db_path=self.db_path, now=self.base_time)
        self.assertEqual(len(candidates), 0)

    # -----------------------------------------------------------------------
    # 7. publication failed ignorada
    # -----------------------------------------------------------------------
    def test_07_publication_failed_ignored(self):
        self._insert_publication("t1", external_id="yt_1", status="failed")
        candidates = analytics_scheduler.get_eligible_analytics_candidates(db_path=self.db_path, now=self.base_time)
        self.assertEqual(len(candidates), 0)

    # -----------------------------------------------------------------------
    # 8. unsupported platform ignorada
    # -----------------------------------------------------------------------
    def test_08_unsupported_platform_ignored(self):
        self._insert_publication("t1", platform="instagram", external_id="ig_1")
        candidates = analytics_scheduler.get_eligible_analytics_candidates(db_path=self.db_path, now=self.base_time)
        self.assertEqual(len(candidates), 0)

    # -----------------------------------------------------------------------
    # 9. provider not configured ignorado
    # -----------------------------------------------------------------------
    def test_09_provider_not_configured_ignored(self):
        self.mock_yt._configured = False
        self._insert_publication("t1", platform="youtube", external_id="yt_1")
        candidates = analytics_scheduler.get_eligible_analytics_candidates(db_path=self.db_path, now=self.base_time)
        self.assertEqual(len(candidates), 0)

    # -----------------------------------------------------------------------
    # 10. first snapshot eligible
    # -----------------------------------------------------------------------
    def test_10_first_snapshot_eligible(self):
        pub_time = self.base_time - timedelta(minutes=30)
        self._insert_publication("t1", external_id="yt_1", published_at=pub_time)
        candidates = analytics_scheduler.get_eligible_analytics_candidates(db_path=self.db_path, now=self.base_time)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["task_id"], "t1")
        self.assertIsNone(candidates[0]["last_snapshot_at"])

    # -----------------------------------------------------------------------
    # 11. recent snapshot respeita cooldown
    # -----------------------------------------------------------------------
    def test_11_recent_snapshot_respects_cooldown(self):
        pub_time = self.base_time - timedelta(hours=2)
        self._insert_publication("t1", external_id="yt_1", published_at=pub_time)

        # Snapshot criado há 15 minutos (janela 0-6h exige 60m)
        snap_time = self.base_time - timedelta(minutes=15)
        analytics.save_snapshot(
            task_id="t1",
            platform="youtube",
            views=100,
            collected_at=snap_time.isoformat(),
            db_path=self.db_path,
        )

        candidates = analytics_scheduler.get_eligible_analytics_candidates(db_path=self.db_path, now=self.base_time)
        self.assertEqual(len(candidates), 0)

    # -----------------------------------------------------------------------
    # 12. 0–6h usa janela 60m
    # -----------------------------------------------------------------------
    def test_12_window_0_6h_uses_60m(self):
        pub_time = self.base_time - timedelta(hours=3)
        self._insert_publication("t1", external_id="yt_1", published_at=pub_time)

        # Snapshot há 59 minutos (deve ser bloqueado)
        analytics.save_snapshot("t1", "youtube", 10, collected_at=(self.base_time - timedelta(minutes=59)).isoformat(), db_path=self.db_path)
        cands_59m = analytics_scheduler.get_eligible_analytics_candidates(db_path=self.db_path, now=self.base_time)
        self.assertEqual(len(cands_59m), 0)

        # Snapshot há 61 minutos (deve ser elegível)
        with analytics.get_connection(self.db_path) as conn:
            conn.execute("UPDATE content_analytics SET collected_at = ? WHERE task_id = 't1';", ((self.base_time - timedelta(minutes=61)).isoformat(),))
        cands_61m = analytics_scheduler.get_eligible_analytics_candidates(db_path=self.db_path, now=self.base_time)
        self.assertEqual(len(cands_61m), 1)

    # -----------------------------------------------------------------------
    # 13. 6–24h usa janela 3h
    # -----------------------------------------------------------------------
    def test_13_window_6_24h_uses_3h(self):
        pub_time = self.base_time - timedelta(hours=12)
        self._insert_publication("t1", external_id="yt_1", published_at=pub_time)

        # Snapshot há 2h50m (bloqueado)
        analytics.save_snapshot("t1", "youtube", 10, collected_at=(self.base_time - timedelta(minutes=170)).isoformat(), db_path=self.db_path)
        self.assertEqual(len(analytics_scheduler.get_eligible_analytics_candidates(db_path=self.db_path, now=self.base_time)), 0)

        # Snapshot há 3h05m (elegível)
        with analytics.get_connection(self.db_path) as conn:
            conn.execute("UPDATE content_analytics SET collected_at = ? WHERE task_id = 't1';", ((self.base_time - timedelta(minutes=185)).isoformat(),))
        self.assertEqual(len(analytics_scheduler.get_eligible_analytics_candidates(db_path=self.db_path, now=self.base_time)), 1)

    # -----------------------------------------------------------------------
    # 14. 1–3d usa janela 6h
    # -----------------------------------------------------------------------
    def test_14_window_1_3d_uses_6h(self):
        pub_time = self.base_time - timedelta(hours=48)
        self._insert_publication("t1", external_id="yt_1", published_at=pub_time)

        # Snapshot há 5h (bloqueado)
        analytics.save_snapshot("t1", "youtube", 10, collected_at=(self.base_time - timedelta(hours=5)).isoformat(), db_path=self.db_path)
        self.assertEqual(len(analytics_scheduler.get_eligible_analytics_candidates(db_path=self.db_path, now=self.base_time)), 0)

        # Snapshot há 7h (elegível)
        with analytics.get_connection(self.db_path) as conn:
            conn.execute("UPDATE content_analytics SET collected_at = ? WHERE task_id = 't1';", ((self.base_time - timedelta(hours=7)).isoformat(),))
        self.assertEqual(len(analytics_scheduler.get_eligible_analytics_candidates(db_path=self.db_path, now=self.base_time)), 1)

    # -----------------------------------------------------------------------
    # 15. 3–7d usa janela 12h
    # -----------------------------------------------------------------------
    def test_15_window_3_7d_uses_12h(self):
        pub_time = self.base_time - timedelta(days=5)
        self._insert_publication("t1", external_id="yt_1", published_at=pub_time)

        # Snapshot há 11h (bloqueado)
        analytics.save_snapshot("t1", "youtube", 10, collected_at=(self.base_time - timedelta(hours=11)).isoformat(), db_path=self.db_path)
        self.assertEqual(len(analytics_scheduler.get_eligible_analytics_candidates(db_path=self.db_path, now=self.base_time)), 0)

        # Snapshot há 13h (elegível)
        with analytics.get_connection(self.db_path) as conn:
            conn.execute("UPDATE content_analytics SET collected_at = ? WHERE task_id = 't1';", ((self.base_time - timedelta(hours=13)).isoformat(),))
        self.assertEqual(len(analytics_scheduler.get_eligible_analytics_candidates(db_path=self.db_path, now=self.base_time)), 1)

    # -----------------------------------------------------------------------
    # 16. 7–30d usa janela 24h
    # -----------------------------------------------------------------------
    def test_16_window_7_30d_uses_24h(self):
        pub_time = self.base_time - timedelta(days=15)
        self._insert_publication("t1", external_id="yt_1", published_at=pub_time)

        # Snapshot há 23h (bloqueado)
        analytics.save_snapshot("t1", "youtube", 10, collected_at=(self.base_time - timedelta(hours=23)).isoformat(), db_path=self.db_path)
        self.assertEqual(len(analytics_scheduler.get_eligible_analytics_candidates(db_path=self.db_path, now=self.base_time)), 0)

        # Snapshot há 25h (elegível)
        with analytics.get_connection(self.db_path) as conn:
            conn.execute("UPDATE content_analytics SET collected_at = ? WHERE task_id = 't1';", ((self.base_time - timedelta(hours=25)).isoformat(),))
        self.assertEqual(len(analytics_scheduler.get_eligible_analytics_candidates(db_path=self.db_path, now=self.base_time)), 1)

    # -----------------------------------------------------------------------
    # 17. >30d não coleta
    # -----------------------------------------------------------------------
    def test_17_over_30d_not_collected(self):
        pub_time = self.base_time - timedelta(days=31)
        self._insert_publication("t1", external_id="yt_1", published_at=pub_time)
        candidates = analytics_scheduler.get_eligible_analytics_candidates(db_path=self.db_path, now=self.base_time)
        self.assertEqual(len(candidates), 0)

    # -----------------------------------------------------------------------
    # 18. max 3 fetches por ciclo
    # -----------------------------------------------------------------------
    def test_18_max_3_fetches_per_cycle(self):
        for i in range(1, 7):
            self._insert_publication(f"task_{i}", external_id=f"yt_{i}", published_at=self.base_time - timedelta(minutes=i * 10))

        analytics_scheduler.set_analytics_auto_collection_enabled(True, db_path=self.db_path)
        res = analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time)
        self.assertEqual(res["processed_count"], 3)
        self.assertEqual(self.mock_yt.fetch_call_count, 3)

    # -----------------------------------------------------------------------
    # 19. prioridade sem snapshot primeiro
    # -----------------------------------------------------------------------
    def test_19_priority_no_snapshot_first(self):
        # task_A: tem snapshot antigo
        self._insert_publication("task_A", external_id="yt_A", published_at=self.base_time - timedelta(hours=2))
        analytics.save_snapshot("task_A", "youtube", 50, collected_at=(self.base_time - timedelta(hours=2)).isoformat(), db_path=self.db_path)

        # task_B: não tem snapshot
        self._insert_publication("task_B", external_id="yt_B", published_at=self.base_time - timedelta(hours=1))

        candidates = analytics_scheduler.get_eligible_analytics_candidates(limit=2, db_path=self.db_path, now=self.base_time)
        self.assertEqual(len(candidates), 2)
        # Primeiro candidato deve ser o que não tem snapshot
        self.assertEqual(candidates[0]["task_id"], "task_B")
        self.assertEqual(candidates[1]["task_id"], "task_A")

    # -----------------------------------------------------------------------
    # 20. múltiplos profiles não multiplicam limite
    # -----------------------------------------------------------------------
    def test_20_multi_profiles_do_not_multiply_rate_limit(self):
        # Limite global de 2 coletas para youtube
        platform = "youtube"
        analytics_scheduler.set_analytics_max_fetches_per_cycle(5, db_path=self.db_path)

        # Primeira chamada consome 1
        allowed1 = analytics_scheduler.check_and_increment_rate_limit(platform, max_per_window=2, now=self.base_time, db_path=self.db_path)
        # Segunda chamada consome 2
        allowed2 = analytics_scheduler.check_and_increment_rate_limit(platform, max_per_window=2, now=self.base_time, db_path=self.db_path)
        # Terceira chamada (mesmo que de outro profile) é bloqueada
        allowed3 = analytics_scheduler.check_and_increment_rate_limit(platform, max_per_window=2, now=self.base_time, db_path=self.db_path)

        self.assertTrue(allowed1)
        self.assertTrue(allowed2)
        self.assertFalse(allowed3)

    # -----------------------------------------------------------------------
    # 21. multiple channels preservam isolamento
    # -----------------------------------------------------------------------
    def test_21_multiple_channels_isolated(self):
        self._insert_publication("t1", external_id="yt_ch1", profile_id="p1", channel_id="ch_alpha")
        self._insert_publication("t2", external_id="yt_ch2", profile_id="p1", channel_id="ch_beta")

        analytics_scheduler.set_analytics_auto_collection_enabled(True, db_path=self.db_path)
        analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time)

        snap1 = analytics_scheduler.get_publication_latest_analytics("t1", "youtube", channel_id="ch_alpha", db_path=self.db_path)
        snap2 = analytics_scheduler.get_publication_latest_analytics("t2", "youtube", channel_id="ch_beta", db_path=self.db_path)

        self.assertEqual(snap1["channel_id"], "ch_alpha")
        self.assertEqual(snap2["channel_id"], "ch_beta")
        self.assertIsNotNone(snap1["last_snapshot_at"])
        self.assertIsNotNone(snap2["last_snapshot_at"])

    # -----------------------------------------------------------------------
    # 22. analytics usa profile/channel original
    # -----------------------------------------------------------------------
    def test_22_analytics_uses_original_profile_channel(self):
        self._insert_publication("t1", external_id="yt_orig", profile_id="prof_custom", channel_id="chan_custom")
        analytics_scheduler.set_analytics_auto_collection_enabled(True, db_path=self.db_path)
        res = analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time)
        self.assertEqual(res["processed_count"], 1)

        snapshots = analytics.get_snapshots(task_id="t1", db_path=self.db_path)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["profile_id"], "prof_custom")
        self.assertEqual(snapshots[0]["channel_id"], "chan_custom")

    # -----------------------------------------------------------------------
    # 23. AUTH_ERROR aplica backoff
    # -----------------------------------------------------------------------
    def test_23_auth_error_applies_backoff(self):
        self._insert_publication("t1", external_id="yt_err")
        self.mock_yt.should_raise = AnalyticsProviderError("Token inválido", code=ERR_AUTH)

        analytics_scheduler.set_analytics_auto_collection_enabled(True, db_path=self.db_path)
        res = analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time)
        self.assertEqual(res["results"][0]["status"], "failed")

        bo = analytics_scheduler.get_provider_backoff("youtube", now=self.base_time, db_path=self.db_path)
        self.assertIsNotNone(bo)
        self.assertEqual(bo["reason"], ERR_AUTH)
        # 24h backoff
        self.assertGreaterEqual(bo["remaining_seconds"], 23 * 3600)

    # -----------------------------------------------------------------------
    # 24. RATE_LIMIT aplica backoff
    # -----------------------------------------------------------------------
    def test_24_rate_limit_applies_backoff(self):
        self._insert_publication("t1", external_id="yt_err")
        self.mock_yt.should_raise = AnalyticsProviderError("Quota exceeded", code=ERR_RATE_LIMIT)

        analytics_scheduler.set_analytics_auto_collection_enabled(True, db_path=self.db_path)
        analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time)

        bo = analytics_scheduler.get_provider_backoff("youtube", now=self.base_time, db_path=self.db_path)
        self.assertIsNotNone(bo)
        self.assertEqual(bo["reason"], ERR_RATE_LIMIT)
        # 6h backoff
        self.assertGreaterEqual(bo["remaining_seconds"], 5 * 3600)

    # -----------------------------------------------------------------------
    # 25. TEMPORARY aplica backoff
    # -----------------------------------------------------------------------
    def test_25_temporary_applies_backoff(self):
        self._insert_publication("t1", external_id="yt_err")
        self.mock_yt.should_raise = AnalyticsProviderError("Network glitch", code=ERR_TEMPORARY)

        analytics_scheduler.set_analytics_auto_collection_enabled(True, db_path=self.db_path)
        analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time)

        bo = analytics_scheduler.get_provider_backoff("youtube", now=self.base_time, db_path=self.db_path)
        self.assertIsNotNone(bo)
        self.assertEqual(bo["reason"], ERR_TEMPORARY)
        # 15m backoff
        self.assertGreaterEqual(bo["remaining_seconds"], 14 * 60)

    # -----------------------------------------------------------------------
    # 26. NOT_FOUND não retry imediato
    # -----------------------------------------------------------------------
    def test_26_not_found_no_immediate_retry(self):
        self._insert_publication("t1", external_id="yt_notfound")
        self.mock_yt.should_raise = AnalyticsProviderError("Video não encontrado", code=ERR_NOT_FOUND)

        analytics_scheduler.set_analytics_auto_collection_enabled(True, db_path=self.db_path)
        analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time)

        bo = analytics_scheduler.get_provider_backoff("youtube", now=self.base_time, db_path=self.db_path)
        self.assertIsNotNone(bo)
        self.assertEqual(bo["reason"], ERR_NOT_FOUND)

        # Imediatamente após, segundo ciclo não consulta provider
        self.mock_yt.fetch_call_count = 0
        analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time)
        self.assertEqual(self.mock_yt.fetch_call_count, 0)

    # -----------------------------------------------------------------------
    # 27. UNAVAILABLE aplica backoff
    # -----------------------------------------------------------------------
    def test_27_unavailable_applies_backoff(self):
        self._insert_publication("t1", external_id="yt_err")
        self.mock_yt.should_raise = AnalyticsProviderError("503 Service Unavailable", code=ERR_UNAVAILABLE)

        analytics_scheduler.set_analytics_auto_collection_enabled(True, db_path=self.db_path)
        analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time)

        bo = analytics_scheduler.get_provider_backoff("youtube", now=self.base_time, db_path=self.db_path)
        self.assertIsNotNone(bo)
        self.assertEqual(bo["reason"], ERR_UNAVAILABLE)

    # -----------------------------------------------------------------------
    # 28. failure não altera task
    # -----------------------------------------------------------------------
    def test_28_failure_does_not_alter_task(self):
        self._insert_publication("t1", external_id="yt_err")
        self.mock_yt.should_raise = AnalyticsProviderError("500 Server Error", code=ERR_TEMPORARY)

        analytics_scheduler.set_analytics_auto_collection_enabled(True, db_path=self.db_path)
        analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time)

        # Task não deve ser alterada de forma alguma
        # (se existisse no state ou sqlite, nenhum update é feito)
        # Verifica publication_events intacto
        with scheduler.get_connection(self.db_path) as conn:
            pub = conn.execute("SELECT status FROM publication_events WHERE task_id = 't1';").fetchone()
            self.assertEqual(pub["status"], "success")

    # -----------------------------------------------------------------------
    # 29. failure não altera publication
    # -----------------------------------------------------------------------
    def test_29_failure_does_not_alter_publication(self):
        self._insert_publication("t1", external_id="yt_err")
        self.mock_yt.should_raise = AnalyticsProviderError("Rate limit", code=ERR_RATE_LIMIT)

        analytics_scheduler.set_analytics_auto_collection_enabled(True, db_path=self.db_path)
        analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time)

        with scheduler.get_connection(self.db_path) as conn:
            pub = conn.execute("SELECT status, external_id FROM publication_events WHERE task_id = 't1';").fetchone()
            self.assertEqual(pub["status"], "success")
            self.assertEqual(pub["external_id"], "yt_err")

    # -----------------------------------------------------------------------
    # 30. success cria snapshot
    # -----------------------------------------------------------------------
    def test_30_success_creates_snapshot(self):
        self._insert_publication("t1", external_id="yt_ok")
        analytics_scheduler.set_analytics_auto_collection_enabled(True, db_path=self.db_path)
        res = analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time)

        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["processed_count"], 1)

        snapshots = analytics.get_snapshots(task_id="t1", db_path=self.db_path)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["views"], 1500)

    # -----------------------------------------------------------------------
    # 31. source correto
    # -----------------------------------------------------------------------
    def test_31_source_correct(self):
        self._insert_publication("t1", external_id="yt_ok")
        analytics_scheduler.set_analytics_auto_collection_enabled(True, db_path=self.db_path)
        analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time)

        snapshots = analytics.get_snapshots(task_id="t1", db_path=self.db_path)
        self.assertEqual(snapshots[0]["source"], "youtube_api")

    # -----------------------------------------------------------------------
    # 32. idempotência da janela
    # -----------------------------------------------------------------------
    def test_32_idempotency_within_window(self):
        self._insert_publication("t1", external_id="yt_ok", published_at=self.base_time - timedelta(minutes=30))
        analytics_scheduler.set_analytics_auto_collection_enabled(True, db_path=self.db_path)

        # Primeiro ciclo coleta
        res1 = analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time)
        self.assertEqual(res1["processed_count"], 1)

        # Segundo ciclo 10 minutos depois (cycle throttle de 5m passou, mas cooldown de 60m da publicação continua ativo): não coleta novamente
        later = self.base_time + timedelta(minutes=10)
        res2 = analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=later)
        self.assertEqual(res2.get("processed_count", 0), 0)

        snapshots = analytics.get_snapshots(task_id="t1", db_path=self.db_path)
        self.assertEqual(len(snapshots), 1)

    # -----------------------------------------------------------------------
    # 33. próximo ciclo futuro pode criar novo snapshot
    # -----------------------------------------------------------------------
    def test_33_future_cycle_creates_next_snapshot(self):
        self._insert_publication("t1", external_id="yt_ok", published_at=self.base_time - timedelta(minutes=30))
        analytics_scheduler.set_analytics_auto_collection_enabled(True, db_path=self.db_path)

        # Ciclo 1 (t0)
        analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time)

        # Avança 65 minutos no futuro (idade agora ~95m, janela 0-6h, cooldown de 60m já passou)
        future_time = self.base_time + timedelta(minutes=65)
        self.mock_yt.mock_metrics["views"] = 2000

        res2 = analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=future_time)
        self.assertEqual(res2["processed_count"], 1)

        snapshots = analytics.get_snapshots(task_id="t1", db_path=self.db_path)
        self.assertEqual(len(snapshots), 2)
        self.assertEqual(snapshots[0]["views"], 2000)

    # -----------------------------------------------------------------------
    # 34. operational event success
    # -----------------------------------------------------------------------
    def test_34_operational_event_success(self):
        self._insert_publication("t1", external_id="yt_ok")
        analytics_scheduler.set_analytics_auto_collection_enabled(True, db_path=self.db_path)
        analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time)

        events = operator_console.get_operational_events(limit=10, db_path=self.db_path)
        success_events = [e for e in events if e.get("event_type") == "ANALYTICS_COLLECTION_SUCCESS"]
        self.assertGreaterEqual(len(success_events), 1)

    # -----------------------------------------------------------------------
    # 35. operational event failure/backoff
    # -----------------------------------------------------------------------
    def test_35_operational_event_failure_backoff(self):
        self._insert_publication("t1", external_id="yt_err")
        self.mock_yt.should_raise = AnalyticsProviderError("Rate limit hit", code=ERR_RATE_LIMIT)

        analytics_scheduler.set_analytics_auto_collection_enabled(True, db_path=self.db_path)
        analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time)

        events = operator_console.get_operational_events(limit=10, db_path=self.db_path)
        backoff_events = [e for e in events if e.get("event_type") == "ANALYTICS_PROVIDER_BACKOFF"]
        self.assertGreaterEqual(len(backoff_events), 1)

    # -----------------------------------------------------------------------
    # 36. nenhum secret em eventos
    # -----------------------------------------------------------------------
    def test_36_zero_secrets_in_events(self):
        self._insert_publication("t1", external_id="yt_ok")
        analytics_scheduler.set_analytics_auto_collection_enabled(True, db_path=self.db_path)
        analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time)

        events = operator_console.get_operational_events(limit=20, db_path=self.db_path)
        for e in events:
            text_payload = json.dumps(e)
            self.assertNotIn("AIza", text_payload)
            self.assertNotIn("token", text_payload.lower())
            self.assertNotIn("api_key", text_payload.lower())

    # -----------------------------------------------------------------------
    # 37. private YouTube conhecido é skip
    # -----------------------------------------------------------------------
    def test_37_private_youtube_skipped(self):
        tid = "task_private_yt"
        self._insert_publication(tid, external_id="yt_priv", youtube_privacy_status="private")

        candidates = analytics_scheduler.get_eligible_analytics_candidates(db_path=self.db_path, now=self.base_time)
        self.assertEqual(len(candidates), 0)

    # -----------------------------------------------------------------------
    # 41. V12-F.1A: privacidade UNKNOWN (sem task.json) bloqueia fail-closed
    # -----------------------------------------------------------------------
    def test_41_unknown_privacy_blocks_fail_closed(self):
        tid = "task_unknown_privacy"
        self._insert_publication(tid, external_id="yt_unknown", youtube_privacy_status=None)

        candidates = analytics_scheduler.get_eligible_analytics_candidates(db_path=self.db_path, now=self.base_time)
        self.assertEqual(len(candidates), 0)

        pub_row = {
            "task_id": tid,
            "platform": "youtube",
            "status": "success",
            "external_id": "yt_unknown",
            "published_at": self.base_time.isoformat(),
            "profile_id": "default",
            "channel_id": None,
        }
        is_eligible, reason, _ = analytics_scheduler.check_publication_eligibility(
            pub_row, now=self.base_time, db_path=self.db_path
        )
        self.assertFalse(is_eligible)
        self.assertIn("youtube_privacy_not_public_confirmed", reason)

    # -----------------------------------------------------------------------
    # 42. V12-F.1A: privacidade PUBLIC comprovada é elegível
    # -----------------------------------------------------------------------
    def test_42_public_privacy_eligible(self):
        tid = "task_public_privacy"
        self._insert_publication(tid, external_id="yt_public", youtube_privacy_status="public")

        candidates = analytics_scheduler.get_eligible_analytics_candidates(db_path=self.db_path, now=self.base_time)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["task_id"], tid)

    # -----------------------------------------------------------------------
    # 43. V12-F.1A: coleta automática restrita a YouTube (TikTok fora do escopo)
    # -----------------------------------------------------------------------
    def test_43_automatic_collection_youtube_only(self):
        self.assertEqual(analytics_scheduler.SUPPORTED_ANALYTICS_PLATFORMS, ("youtube",))
        self._insert_publication("t_tt", platform="tiktok", external_id="tt_1")
        candidates = analytics_scheduler.get_eligible_analytics_candidates(db_path=self.db_path, now=self.base_time)
        self.assertEqual(len(candidates), 0)

    # -----------------------------------------------------------------------
    # 44. V12-F.1A: exclusão mútua entre ciclo manual e automático
    # -----------------------------------------------------------------------
    def test_44_mutual_exclusion_between_cycles(self):
        self._insert_publication("t1", external_id="yt_ok")
        analytics_scheduler.set_analytics_auto_collection_enabled(True, db_path=self.db_path)

        # Simula um ciclo já em andamento (lock recém-adquirido)
        scheduler.set_setting(
            "analytics_cycle_lock_at",
            self.base_time.isoformat(),
            db_path=self.db_path,
        )
        result = analytics_scheduler.run_analytics_collection_cycle(
            db_path=self.db_path, now=self.base_time, force=True
        )
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "cycle_already_running")
        self.assertEqual(self.mock_yt.fetch_call_count, 0)

    # -----------------------------------------------------------------------
    # 45. V12-F.1A: lock é liberado ao final do ciclo (não trava ciclos seguintes)
    # -----------------------------------------------------------------------
    def test_45_lock_released_after_cycle(self):
        self._insert_publication("t1", external_id="yt_ok")
        analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time, force=True)

        lock_after = scheduler.get_setting("analytics_cycle_lock_at", None, db_path=self.db_path)
        self.assertIn(lock_after, (None, ""))

    # -----------------------------------------------------------------------
    # 46. V12-F.1A: revalidação de backoff antes de cada fetch no mesmo ciclo
    # -----------------------------------------------------------------------
    def test_46_backoff_revalidated_before_each_fetch_same_cycle(self):
        # Duas publicações YouTube elegíveis; a primeira falha e aciona backoff,
        # a segunda deve ser pulada por revalidação (não deve chamar o provider).
        self.mock_yt.should_raise = AnalyticsProviderError("Auth failed", code=ERR_AUTH)
        self._insert_publication("t1", external_id="yt_1", published_at=self.base_time - timedelta(minutes=5))
        self._insert_publication("t2", external_id="yt_2", published_at=self.base_time - timedelta(minutes=10))

        result = analytics_scheduler.run_analytics_collection_cycle(
            db_path=self.db_path, now=self.base_time, force=True
        )
        # Apenas a primeira publicação deve ter efetivamente chamado o provider;
        # a segunda é bloqueada pela revalidação de backoff antes do fetch.
        self.assertEqual(self.mock_yt.fetch_call_count, 1)
        skipped = [r for r in result["results"] if r["status"] == "skipped"]
        self.assertGreaterEqual(len(skipped), 1)

    # -----------------------------------------------------------------------
    # 47. V12-F.1A: default de auto-coleta usa a constante como fonte real
    # -----------------------------------------------------------------------
    def test_47_default_source_is_constant(self):
        with patch.object(analytics_scheduler, "DEFAULT_ANALYTICS_AUTO_COLLECTION_ENABLED", True):
            # Sem setting persistido ainda, deve refletir a constante (não um literal fixo).
            fresh_db = os.path.join(self.tmp_dir.name, "fresh_default.db")
            scheduler.init_db(fresh_db)
            self.assertTrue(analytics_scheduler.is_analytics_auto_collection_enabled(db_path=fresh_db))

    # -----------------------------------------------------------------------
    # 38. Run One Cycle respeita limite
    # -----------------------------------------------------------------------
    def test_38_run_one_cycle_now_respects_limit(self):
        for i in range(1, 6):
            self._insert_publication(f"t_{i}", external_id=f"yt_{i}", published_at=self.base_time - timedelta(minutes=i * 10))

        # Auto collection disabled, mas Run One Cycle force=True
        res = operator_console.run_analytics_collection_cycle_op(db_path=self.db_path)
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["processed_count"], 3)
        self.assertEqual(self.mock_yt.fetch_call_count, 3)

    # -----------------------------------------------------------------------
    # 39. scheduler único preservado
    # -----------------------------------------------------------------------
    def test_39_single_scheduler_preserved(self):
        # O worker daemon do scheduler permanece o mesmo
        # start_scheduler_worker cria apenas uma thread SchedulerExecutionWorker
        scheduler.start_scheduler_worker()
        worker_threads = [t for t in threading.enumerate() if t.name == "SchedulerExecutionWorker"]
        self.assertEqual(len(worker_threads), 1)
        scheduler.stop_scheduler_worker()

    # -----------------------------------------------------------------------
    # 40. nenhum worker/thread novo
    # -----------------------------------------------------------------------
    def test_40_zero_new_workers_created(self):
        threads_before = {t.name for t in threading.enumerate()}
        self._insert_publication("t1", external_id="yt_ok")
        analytics_scheduler.set_analytics_auto_collection_enabled(True, db_path=self.db_path)
        analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time)
        threads_after = {t.name for t in threading.enumerate()}

        new_threads = threads_after - threads_before
        # Nenhuma thread nova pode ter sido criada pelo ciclo de analytics
        self.assertEqual(len(new_threads), 0)

    # -----------------------------------------------------------------------
    # 41. ciclo automático inicial executa
    # -----------------------------------------------------------------------
    def test_41_initial_auto_cycle_executes(self):
        self._insert_publication("t1", external_id="yt_ok", published_at=self.base_time - timedelta(minutes=30))
        analytics_scheduler.set_analytics_auto_collection_enabled(True, db_path=self.db_path)
        res = analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time)
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["processed_count"], 1)

    # -----------------------------------------------------------------------
    # 42. segundo ciclo automático após 30s é bloqueado por throttle
    # -----------------------------------------------------------------------
    def test_42_second_auto_cycle_after_30s_blocked(self):
        self._insert_publication("t1", external_id="yt_ok", published_at=self.base_time - timedelta(minutes=30))
        self._insert_publication("t2", external_id="yt_ok2", published_at=self.base_time - timedelta(minutes=30))
        analytics_scheduler.set_analytics_auto_collection_enabled(True, db_path=self.db_path)

        # Ciclo 1 aos 0s
        res1 = analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time)
        self.assertEqual(res1["status"], "completed")

        # Ciclo 2 aos 30s (worker tick normal)
        tick_30s = self.base_time + timedelta(seconds=30)
        res2 = analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=tick_30s)
        self.assertEqual(res2["status"], "skipped")
        self.assertEqual(res2["reason"], "cycle_throttled")
        self.assertGreater(res2["remaining_seconds"], 200)

    # -----------------------------------------------------------------------
    # 43. ciclo após >=300s executa
    # -----------------------------------------------------------------------
    def test_43_cycle_after_300s_executes(self):
        analytics_scheduler.set_analytics_max_fetches_per_cycle(1, db_path=self.db_path)
        self._insert_publication("t1", external_id="yt_ok", published_at=self.base_time - timedelta(minutes=30))
        self._insert_publication("t2", external_id="yt_ok2", published_at=self.base_time - timedelta(minutes=30))
        analytics_scheduler.set_analytics_auto_collection_enabled(True, db_path=self.db_path)

        # Ciclo 1 aos 0s consome t1 (limite 1)
        res1 = analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time)
        self.assertEqual(res1["status"], "completed")
        self.assertEqual(res1["processed_count"], 1)

        # Ciclo aos 305s (passou throttle de 300s) consome t2
        tick_305s = self.base_time + timedelta(seconds=305)
        res2 = analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=tick_305s)
        self.assertEqual(res2["status"], "completed")
        self.assertEqual(res2["processed_count"], 1)

    # -----------------------------------------------------------------------
    # 44. bloqueio por throttle faz zero HTTP
    # -----------------------------------------------------------------------
    def test_44_throttle_block_makes_zero_http(self):
        self._insert_publication("t1", external_id="yt_ok", published_at=self.base_time - timedelta(minutes=30))
        self._insert_publication("t2", external_id="yt_ok2", published_at=self.base_time - timedelta(minutes=30))
        analytics_scheduler.set_analytics_auto_collection_enabled(True, db_path=self.db_path)

        # Ciclo 1 consome chamadas
        analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time)
        initial_calls = self.mock_yt.fetch_call_count

        # Ciclo 2 aos 30s é throttled
        tick_30s = self.base_time + timedelta(seconds=30)
        res2 = analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=tick_30s)
        self.assertEqual(res2["status"], "skipped")
        self.assertEqual(res2["reason"], "cycle_throttled")
        # Nenhuma chamada HTTP adicional
        self.assertEqual(self.mock_yt.fetch_call_count, initial_calls)

    # -----------------------------------------------------------------------
    # 45. bloqueio por throttle faz zero discovery pesada
    # -----------------------------------------------------------------------
    def test_45_throttle_block_zero_heavy_discovery(self):
        self._insert_publication("t1", external_id="yt_ok", published_at=self.base_time - timedelta(minutes=30))
        analytics_scheduler.set_analytics_auto_collection_enabled(True, db_path=self.db_path)

        # Ciclo 1 executa
        analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time)

        # Ciclo 2 aos 30s não pode chamar get_eligible_analytics_candidates
        tick_30s = self.base_time + timedelta(seconds=30)
        with patch.object(analytics_scheduler, "get_eligible_analytics_candidates") as mock_disc:
            res2 = analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=tick_30s)
            self.assertEqual(res2["status"], "skipped")
            self.assertEqual(res2["reason"], "cycle_throttled")
            mock_disc.assert_not_called()

    # -----------------------------------------------------------------------
    # 46. force=True ignora apenas cycle throttle
    # -----------------------------------------------------------------------
    def test_46_force_true_ignores_only_cycle_throttle(self):
        analytics_scheduler.set_analytics_max_fetches_per_cycle(1, db_path=self.db_path)
        self._insert_publication("t1", external_id="yt_ok", published_at=self.base_time - timedelta(minutes=30))
        self._insert_publication("t2", external_id="yt_ok2", published_at=self.base_time - timedelta(minutes=30))
        analytics_scheduler.set_analytics_auto_collection_enabled(True, db_path=self.db_path)

        # Ciclo 1 aos 0s consome t1 (limite 1)
        res1 = analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time)
        self.assertEqual(res1["status"], "completed")
        self.assertEqual(res1["processed_count"], 1)

        # Ciclo manual aos 30s com force=True deve rodar ignorando o throttle de 300s e consumir t2
        tick_30s = self.base_time + timedelta(seconds=30)
        res_forced = analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=tick_30s, force=True)
        self.assertEqual(res_forced["status"], "completed")
        self.assertEqual(res_forced["processed_count"], 1)

    # -----------------------------------------------------------------------
    # 47. force=True ainda respeita rate limit
    # -----------------------------------------------------------------------
    def test_47_force_true_still_respects_rate_limit(self):
        self._insert_publication("t1", external_id="yt_ok", published_at=self.base_time - timedelta(minutes=30))
        # Simula rate limit de 30 chamadas atingido
        scheduler.set_setting("analytics_rl_start_youtube", self.base_time.isoformat(), db_path=self.db_path)
        scheduler.set_setting("analytics_rl_count_youtube", "30", db_path=self.db_path)

        # force=True NÃO ignora o rate limit
        res = analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time, force=True)
        self.assertEqual(res["results"][0]["status"], "skipped")
        self.assertEqual(res["results"][0]["reason"], "rate_limit_exceeded")

    # -----------------------------------------------------------------------
    # 48. force=True ainda respeita PAUSED
    # -----------------------------------------------------------------------
    def test_48_force_true_still_respects_paused(self):
        self._insert_publication("t1", external_id="yt_ok", published_at=self.base_time - timedelta(minutes=30))
        operator_console.set_factory_state(operator_console.FACTORY_STATE_PAUSED, db_path=self.db_path)

        # force=True NÃO ignora factory PAUSED
        res = analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time, force=True)
        self.assertEqual(res["status"], "skipped")
        self.assertEqual(res["reason"], "factory_paused")

    # -----------------------------------------------------------------------
    # 49. force=True ainda respeita provider backoff
    # -----------------------------------------------------------------------
    def test_49_force_true_still_respects_provider_backoff(self):
        self._insert_publication("t1", external_id="yt_ok", published_at=self.base_time - timedelta(minutes=30))
        analytics_scheduler.set_provider_backoff("youtube", reason=ERR_RATE_LIMIT, now=self.base_time, db_path=self.db_path)

        # force=True NÃO ignora provider backoff
        res = analytics_scheduler.run_analytics_collection_cycle(db_path=self.db_path, now=self.base_time, force=True)
        self.assertEqual(res["status"], "idle")
        self.assertEqual(res["candidates_count"], 0)

    # -----------------------------------------------------------------------
    # 50. default OFF continua intacto
    # -----------------------------------------------------------------------
    def test_50_default_off_intact(self):
        self.assertFalse(analytics_scheduler.is_analytics_auto_collection_enabled(db_path=self.db_path))


if __name__ == "__main__":
    unittest.main()

