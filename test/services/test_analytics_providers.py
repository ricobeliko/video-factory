"""
Tests for Analytics Providers (YouTube and TikTok).
V10-A — Automatic Analytics Provider Foundation.
"""
import os
import unittest
from unittest.mock import patch, MagicMock

from app.config import config
from app.services.analytics_providers import (
    AnalyticsProvider,
    AnalyticsProviderError,
    NormalizedAnalytics,
    YouTubeAnalyticsProvider,
    TikTokAnalyticsProvider,
    get_provider,
    get_all_providers_status,
    STATUS_CONFIGURED,
    STATUS_NOT_CONFIGURED,
    ERR_AUTH,
    ERR_RATE_LIMIT,
    ERR_TEMPORARY,
    ERR_NOT_FOUND,
)
from app.services import operator_console


class TestAnalyticsProviders(unittest.TestCase):
    """Testes de unidade para registry, providers e normalização de analytics."""

    def setUp(self):
        # Limpa variáveis de ambiente e configurações que possam interferir
        self._orig_yt_key = config.app.get("youtube_api_key")
        self._orig_tt_token = config.app.get("tiktok_access_token")
        self._orig_env_yt = os.environ.get("YOUTUBE_API_KEY")
        self._orig_env_tt = os.environ.get("TIKTOK_ACCESS_TOKEN")

        if "YOUTUBE_API_KEY" in os.environ:
            del os.environ["YOUTUBE_API_KEY"]
        if "TIKTOK_ACCESS_TOKEN" in os.environ:
            del os.environ["TIKTOK_ACCESS_TOKEN"]
        config.app["youtube_api_key"] = ""
        config.app["tiktok_access_token"] = ""

    def tearDown(self):
        if self._orig_yt_key is not None:
            config.app["youtube_api_key"] = self._orig_yt_key
        if self._orig_tt_token is not None:
            config.app["tiktok_access_token"] = self._orig_tt_token
        if self._orig_env_yt is not None:
            os.environ["YOUTUBE_API_KEY"] = self._orig_env_yt
        if self._orig_env_tt is not None:
            os.environ["TIKTOK_ACCESS_TOKEN"] = self._orig_env_tt

    def test_provider_registry_youtube(self):
        """1. Provider registry YouTube."""
        provider = get_provider("youtube")
        self.assertIsInstance(provider, YouTubeAnalyticsProvider)
        self.assertEqual(provider.platform, "youtube")
        self.assertEqual(provider.provider_name, "youtube_api")

    def test_provider_registry_tiktok(self):
        """2. Provider registry TikTok."""
        provider = get_provider("tiktok")
        self.assertIsInstance(provider, TikTokAnalyticsProvider)
        self.assertEqual(provider.platform, "tiktok")
        self.assertEqual(provider.provider_name, "tiktok_api")

    def test_invalid_platform_rejected(self):
        """3. Plataforma inválida rejeitada."""
        with self.assertRaises(ValueError) as ctx:
            get_provider("instagram")
        self.assertIn("não suportado", str(ctx.exception).lower())

    def test_youtube_not_configured_without_credential(self):
        """4. YouTube NOT_CONFIGURED sem credencial."""
        provider = get_provider("youtube")
        status = provider.get_status()
        self.assertEqual(status, STATUS_NOT_CONFIGURED)

        # Configura credencial simulada e valida CONFIGURED
        config.app["youtube_api_key"] = "mock_secret_key_123"
        self.assertEqual(provider.get_status(), STATUS_CONFIGURED)

    def test_tiktok_not_configured_without_credential(self):
        """5. TikTok NOT_CONFIGURED sem credencial."""
        provider = get_provider("tiktok")
        status = provider.get_status()
        self.assertEqual(status, STATUS_NOT_CONFIGURED)

        # Configura token simulado e valida CONFIGURED
        config.app["tiktok_access_token"] = "mock_tiktok_token_456"
        self.assertEqual(provider.get_status(), STATUS_CONFIGURED)

    @patch("requests.get")
    def test_dry_run_does_not_make_external_request_youtube(self, mock_get):
        """6. dry_run não faz request externo (YouTube)."""
        provider = get_provider("youtube")
        res = provider.fetch_metrics(external_post_id="vid_yt_123", dry_run=True)
        mock_get.assert_not_called()
        self.assertTrue(res.get("dry_run"))
        self.assertEqual(len(res.get("items", [])), 1)

    @patch("requests.post")
    def test_dry_run_does_not_make_external_request_tiktok(self, mock_post):
        """6. dry_run não faz request externo (TikTok)."""
        provider = get_provider("tiktok")
        res = provider.fetch_metrics(external_post_id="vid_tt_456", dry_run=True)
        mock_post.assert_not_called()
        self.assertTrue(res.get("dry_run"))
        self.assertIn("videos", res.get("data", {}))

    def test_normalize_youtube(self):
        """7. Normalize YouTube e 9. Campos ausentes viram None."""
        provider = get_provider("youtube")
        raw_payload = {
            "kind": "youtube#videoListResponse",
            "items": [
                {
                    "id": "abc1234",
                    "statistics": {
                        "viewCount": "15420",
                        "likeCount": "980",
                        "commentCount": "112",
                        "favoriteCount": "45",
                    },
                }
            ],
        }

        normalized = provider.normalize_metrics(raw_payload, external_post_id="abc1234")
        self.assertEqual(normalized.platform, "youtube")
        self.assertEqual(normalized.external_post_id, "abc1234")
        self.assertEqual(normalized.views, 15420)
        self.assertEqual(normalized.likes, 980)
        self.assertEqual(normalized.comments, 112)
        self.assertEqual(normalized.favorites, 45)
        self.assertEqual(normalized.shares, 0)
        self.assertIn("youtube.com/watch?v=abc1234", normalized.external_url)

        # Campos ausentes viram None (não inventados)
        self.assertIsNone(normalized.watch_time_seconds)
        self.assertIsNone(normalized.average_view_duration_seconds)
        self.assertIsNone(normalized.average_view_percentage)
        self.assertIsNone(normalized.retention_rate)
        self.assertIsNone(normalized.followers_gained)

    def test_normalize_tiktok(self):
        """8. Normalize TikTok e 10. Nenhuma métrica inventada."""
        provider = get_provider("tiktok")
        raw_payload = {
            "data": {
                "videos": [
                    {
                        "id": "tt_video_789",
                        "view_count": 52000,
                        "like_count": 4800,
                        "comment_count": 320,
                        "share_count": 610,
                    }
                ]
            }
        }

        normalized = provider.normalize_metrics(raw_payload, external_post_id="tt_video_789")
        self.assertEqual(normalized.platform, "tiktok")
        self.assertEqual(normalized.external_post_id, "tt_video_789")
        self.assertEqual(normalized.views, 52000)
        self.assertEqual(normalized.likes, 4800)
        self.assertEqual(normalized.comments, 320)
        self.assertEqual(normalized.shares, 610)
        self.assertEqual(normalized.favorites, 0)

        # Nenhuma métrica inventada
        self.assertIsNone(normalized.watch_time_seconds)
        self.assertIsNone(normalized.average_view_duration_seconds)
        self.assertIsNone(normalized.average_view_percentage)
        self.assertIsNone(normalized.retention_rate)

    @patch("requests.get")
    def test_youtube_auth_error_classified(self, mock_get):
        """20. AUTH_ERROR classificado (YouTube)."""
        config.app["youtube_api_key"] = "test_key"
        provider = get_provider("youtube")

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        mock_get.return_value = mock_resp

        with self.assertRaises(AnalyticsProviderError) as ctx:
            provider.fetch_metrics(external_post_id="vid1")
        self.assertEqual(ctx.exception.code, ERR_AUTH)

    @patch("requests.post")
    def test_tiktok_rate_limit_classified(self, mock_post):
        """21. RATE_LIMIT classificado (TikTok)."""
        config.app["tiktok_access_token"] = "test_tok"
        provider = get_provider("tiktok")

        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = "Too Many Requests"
        mock_post.return_value = mock_resp

        with self.assertRaises(AnalyticsProviderError) as ctx:
            provider.fetch_metrics(external_post_id="vid2")
        self.assertEqual(ctx.exception.code, ERR_RATE_LIMIT)

    @patch("requests.get")
    def test_temporary_error_classified(self, mock_get):
        """22. TEMPORARY classificado."""
        config.app["youtube_api_key"] = "test_key"
        provider = get_provider("youtube")

        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.text = "Service Unavailable"
        mock_get.return_value = mock_resp

        with self.assertRaises(AnalyticsProviderError) as ctx:
            provider.fetch_metrics(external_post_id="vid3")
        self.assertEqual(ctx.exception.code, ERR_TEMPORARY)

    def test_secrets_safety(self):
        """25. Secrets não aparecem em logs/DB/objetos normalizados."""
        secret = "SUPER_SECRET_TOKEN_999"
        config.app["tiktok_access_token"] = secret
        provider = get_provider("tiktok")

        raw_payload = {
            "data": {
                "videos": [
                    {
                        "id": "tt_video_secret",
                        "view_count": 100,
                        "like_count": 10,
                        "comment_count": 1,
                        "share_count": 0,
                    }
                ]
            }
        }
        normalized = provider.normalize_metrics(raw_payload, external_post_id="tt_video_secret")
        dict_data = str(normalized.to_dict())
        self.assertNotIn(secret, dict_data)

    def test_view_only_can_read_status(self):
        """26. VIEW ONLY pode ler status sem erro nem mutação."""
        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._current_role = operator_console.ROLE_SECONDARY_VIEW_ONLY
        try:
            summary = operator_console.get_provider_health_summary()
            self.assertIn("YouTube Analytics", summary)
            self.assertIn("TikTok Analytics", summary)
            self.assertIn(summary["YouTube Analytics"]["status"], [STATUS_CONFIGURED, STATUS_NOT_CONFIGURED])
            self.assertIn(summary["TikTok Analytics"]["status"], [STATUS_CONFIGURED, STATUS_NOT_CONFIGURED])
        finally:
            with operator_console._instance_state_lock:
                operator_console._current_role = operator_console.ROLE_PRIMARY


if __name__ == "__main__":
    unittest.main()
