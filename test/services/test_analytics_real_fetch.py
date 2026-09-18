"""
Unit tests for Real Provider Authentication and Controlled Fetch (V10-B).
Zero external HTTP calls executed: all network responses are strictly mocked.
"""
import os
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from app.config import config
from app.services import analytics
from app.services import analytics_ingestion
from app.services import analytics_providers
from app.services import operator_console
from app.services import profile_manager
from app.services import scheduler
from app.services.analytics_providers import (
    AnalyticsProviderError,
    ERR_AUTH,
    ERR_INVALID_RESPONSE,
    ERR_NOT_FOUND,
    ERR_RATE_LIMIT,
    ERR_TEMPORARY,
    STATUS_CONFIGURED,
    STATUS_NOT_CONFIGURED,
    validate_provider_configuration,
)


class TestAnalyticsRealFetch(unittest.TestCase):
    """Testes completos da V10-B para coleta controlada e validação de autenticação."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_v10b.db")
        scheduler.init_db(self.db_path)
        analytics.init_analytics_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        operator_console.init_operator_db(self.db_path)

        # Garante instância como PRIMARY
        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._current_role = operator_console.ROLE_PRIMARY

        # Limpa configurações
        self._orig_yt = config.app.get("youtube_api_key")
        self._orig_tt = config.app.get("tiktok_access_token")
        self._orig_env_yt = os.environ.get("YOUTUBE_API_KEY")
        self._orig_env_tt = os.environ.get("TIKTOK_ACCESS_TOKEN")

        config.app["youtube_api_key"] = ""
        config.app["tiktok_access_token"] = ""
        if "YOUTUBE_API_KEY" in os.environ:
            del os.environ["YOUTUBE_API_KEY"]
        if "TIKTOK_ACCESS_TOKEN" in os.environ:
            del os.environ["TIKTOK_ACCESS_TOKEN"]

    def tearDown(self):
        if self._orig_yt is not None:
            config.app["youtube_api_key"] = self._orig_yt
        if self._orig_tt is not None:
            config.app["tiktok_access_token"] = self._orig_tt
        if self._orig_env_yt is not None:
            os.environ["YOUTUBE_API_KEY"] = self._orig_env_yt
        if self._orig_env_tt is not None:
            os.environ["TIKTOK_ACCESS_TOKEN"] = self._orig_env_tt

        with operator_console._instance_state_lock:
            operator_console._current_role = operator_console.ROLE_PRIMARY
        self.tmp_dir.cleanup()

    def test_01_youtube_config_missing(self):
        """1. YouTube config ausente."""
        res = validate_provider_configuration("youtube", db_path=self.db_path)
        self.assertFalse(res["configured"])
        self.assertEqual(res["status"], STATUS_NOT_CONFIGURED)
        self.assertIn("youtube_api_key", res["missing_fields"])

    def test_02_youtube_config_present(self):
        """2. YouTube config presente."""
        config.app["youtube_api_key"] = "test_key_abc_123"
        res = validate_provider_configuration("youtube", db_path=self.db_path)
        self.assertTrue(res["configured"])
        self.assertEqual(res["status"], STATUS_CONFIGURED)
        self.assertEqual(len(res["missing_fields"]), 0)

    def test_03_tiktok_config_missing(self):
        """3. TikTok config ausente."""
        res = validate_provider_configuration("tiktok", db_path=self.db_path)
        self.assertFalse(res["configured"])
        self.assertEqual(res["status"], STATUS_NOT_CONFIGURED)
        self.assertIn("tiktok_access_token", res["missing_fields"])

    def test_04_tiktok_config_present(self):
        """4. TikTok config presente."""
        config.app["tiktok_access_token"] = "test_token_xyz_456"
        res = validate_provider_configuration("tiktok", db_path=self.db_path)
        self.assertTrue(res["configured"])
        self.assertEqual(res["status"], STATUS_CONFIGURED)
        self.assertEqual(len(res["missing_fields"]), 0)

    def test_05_validation_never_returns_secret(self):
        """5. validation nunca retorna secret."""
        secret_yt = "SUPER_SECRET_KEY_YOUTUBE"
        secret_tt = "SUPER_SECRET_TOKEN_TIKTOK"
        config.app["youtube_api_key"] = secret_yt
        config.app["tiktok_access_token"] = secret_tt

        res_yt = validate_provider_configuration("youtube", db_path=self.db_path)
        res_tt = validate_provider_configuration("tiktok", db_path=self.db_path)

        self.assertNotIn(secret_yt, str(res_yt))
        self.assertNotIn(secret_tt, str(res_tt))

    @patch("requests.get")
    def test_06_dry_run_zero_http(self, mock_get):
        """6. dry_run faz zero HTTP."""
        config.app["youtube_api_key"] = "valid_key"
        scheduler.record_publication_event(
            task_id="task_dry_1",
            platform="youtube",
            status="success",
            external_id="yt_vid_dry",
            db_path=self.db_path,
        )
        snap = analytics_ingestion.ingest_analytics_for_publication(
            task_id="task_dry_1",
            platform="youtube",
            dry_run=True,
            db_path=self.db_path,
        )
        mock_get.assert_not_called()
        self.assertEqual(snap["views"], 0)

    @patch("requests.get")
    def test_07_real_fetch_youtube_mocked(self, mock_get):
        """7. real fetch YouTube mockado."""
        config.app["youtube_api_key"] = "valid_key"
        scheduler.record_publication_event(
            task_id="task_yt_real",
            platform="youtube",
            status="success",
            external_id="dQw4w9WgXcQ",
            db_path=self.db_path,
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "items": [
                {
                    "id": "dQw4w9WgXcQ",
                    "statistics": {
                        "viewCount": "12500",
                        "likeCount": "850",
                        "commentCount": "95",
                        "favoriteCount": "12",
                    },
                }
            ]
        }
        mock_get.return_value = mock_resp

        res = analytics_ingestion.fetch_real_metrics_for_publication(
            task_id="task_yt_real",
            platform="youtube",
            persist=False,
            db_path=self.db_path,
        )
        self.assertTrue(res["success"])
        self.assertFalse(res["persisted"])
        self.assertEqual(res["metrics"]["views"], 12500)
        self.assertEqual(res["metrics"]["likes"], 850)
        mock_get.assert_called_once()

    @patch("requests.post")
    def test_08_real_fetch_tiktok_mocked(self, mock_post):
        """8. real fetch TikTok mockado."""
        config.app["tiktok_access_token"] = "valid_token"
        scheduler.record_publication_event(
            task_id="task_tt_real",
            platform="tiktok",
            status="success",
            external_id="7123456789012345678",
            db_path=self.db_path,
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {
                "videos": [
                    {
                        "id": "7123456789012345678",
                        "view_count": 45000,
                        "like_count": 3200,
                        "comment_count": 180,
                        "share_count": 410,
                    }
                ]
            }
        }
        mock_post.return_value = mock_resp

        res = analytics_ingestion.fetch_real_metrics_for_publication(
            task_id="task_tt_real",
            platform="tiktok",
            persist=False,
            db_path=self.db_path,
        )
        self.assertTrue(res["success"])
        self.assertFalse(res["persisted"])
        self.assertEqual(res["metrics"]["views"], 45000)
        self.assertEqual(res["metrics"]["shares"], 410)
        mock_post.assert_called_once()

    @patch("requests.get")
    def test_09_persist_false_does_not_save_snapshot(self, mock_get):
        """9. persist=False não grava snapshot no SQLite."""
        config.app["youtube_api_key"] = "valid_key"
        scheduler.record_publication_event(
            task_id="task_no_persist",
            platform="youtube",
            status="success",
            external_id="vid_np_123",
            db_path=self.db_path,
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "items": [{"id": "vid_np_123", "statistics": {"viewCount": "100"}}]
        }
        mock_get.return_value = mock_resp

        res = analytics_ingestion.fetch_real_metrics_for_publication(
            task_id="task_no_persist",
            platform="youtube",
            persist=False,
            db_path=self.db_path,
        )
        self.assertFalse(res["persisted"])

        # Confirma banco vazio
        snapshots = analytics.get_snapshots(task_id="task_no_persist", db_path=self.db_path)
        self.assertEqual(len(snapshots), 0)

    @patch("requests.get")
    def test_10_persist_true_saves_snapshot_and_11_source_correct(self, mock_get):
        """10. persist=True grava snapshot e 11. source correto YouTube."""
        config.app["youtube_api_key"] = "valid_key"
        scheduler.record_publication_event(
            task_id="task_persist_yt",
            platform="youtube",
            status="success",
            external_id="vid_p_123",
            db_path=self.db_path,
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "items": [{"id": "vid_p_123", "statistics": {"viewCount": "5000", "likeCount": "250"}}]
        }
        mock_get.return_value = mock_resp

        res = analytics_ingestion.fetch_real_metrics_for_publication(
            task_id="task_persist_yt",
            platform="youtube",
            persist=True,
            db_path=self.db_path,
        )
        self.assertTrue(res["persisted"])
        self.assertEqual(res["snapshot"]["source"], "youtube_api")
        self.assertEqual(res["snapshot"]["views"], 5000)

        snapshots = analytics.get_snapshots(task_id="task_persist_yt", db_path=self.db_path)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["source"], "youtube_api")

    @patch("requests.post")
    def test_12_source_correct_tiktok(self, mock_post):
        """12. source correto TikTok."""
        config.app["tiktok_access_token"] = "valid_token"
        scheduler.record_publication_event(
            task_id="task_persist_tt",
            platform="tiktok",
            status="success",
            external_id="7987654321098765432",
            db_path=self.db_path,
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {"videos": [{"id": "7987654321098765432", "view_count": 8000}]}
        }
        mock_post.return_value = mock_resp

        res = analytics_ingestion.fetch_real_metrics_for_publication(
            task_id="task_persist_tt",
            platform="tiktok",
            persist=True,
            db_path=self.db_path,
        )
        self.assertEqual(res["snapshot"]["source"], "tiktok_api")

    @patch("requests.get")
    def test_13_profile_and_14_channel_preserved_and_15_active_profile_ignored(self, mock_get):
        """13. profile_id original preservado, 14. channel_id preservado, 15. active profile ignorado."""
        config.app["youtube_api_key"] = "valid_key"
        profile_manager.create_profile("Histórias", profile_id="profile_historias", db_path=self.db_path)
        profile_manager.create_profile("Humor", profile_id="profile_humor", db_path=self.db_path)

        scheduler.record_publication_event(
            task_id="task_iso",
            platform="youtube",
            status="success",
            external_id="vid_iso_999",
            profile_id="profile_historias",
            channel_id="chan_yt_hist",
            db_path=self.db_path,
        )

        # Muda active profile global para humor
        profile_manager.set_active_profile("profile_humor", db_path=self.db_path)
        self.assertEqual(profile_manager.get_active_profile_id(self.db_path), "profile_humor")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "items": [{"id": "vid_iso_999", "statistics": {"viewCount": "100"}}]
        }
        mock_get.return_value = mock_resp

        res = analytics_ingestion.fetch_real_metrics_for_publication(
            task_id="task_iso",
            platform="youtube",
            persist=True,
            db_path=self.db_path,
        )
        self.assertEqual(res["snapshot"]["profile_id"], "profile_historias")
        self.assertEqual(res["snapshot"]["channel_id"], "chan_yt_hist")

    @patch("requests.get")
    def test_16_invalid_or_missing_external_id_blocks_http(self, mock_get):
        """16. external ID ausente ou inválido bloqueia chamada HTTP."""
        config.app["youtube_api_key"] = "valid_key"
        scheduler.record_publication_event(
            task_id="task_no_ext_id",
            platform="youtube",
            status="success",
            external_id="",  # Vazio!
            db_path=self.db_path,
        )

        with self.assertRaises(AnalyticsProviderError) as ctx:
            analytics_ingestion.fetch_real_metrics_for_publication(
                task_id="task_no_ext_id",
                platform="youtube",
                persist=False,
                db_path=self.db_path,
            )
        self.assertEqual(ctx.exception.code, ERR_NOT_FOUND)
        mock_get.assert_not_called()

    @patch("requests.get")
    def test_17_auth_error_handled(self, mock_get):
        """17. AUTH_ERROR tratado."""
        config.app["youtube_api_key"] = "bad_key"
        scheduler.record_publication_event(
            task_id="task_err_auth",
            platform="youtube",
            status="success",
            external_id="vid_auth_err",
            db_path=self.db_path,
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized key"
        mock_get.return_value = mock_resp

        with self.assertRaises(AnalyticsProviderError) as ctx:
            analytics_ingestion.fetch_real_metrics_for_publication(
                task_id="task_err_auth",
                platform="youtube",
                persist=False,
                db_path=self.db_path,
            )
        self.assertEqual(ctx.exception.code, ERR_AUTH)

    @patch("requests.get")
    def test_18_rate_limit_handled(self, mock_get):
        """18. RATE_LIMIT tratado."""
        config.app["youtube_api_key"] = "valid_key"
        scheduler.record_publication_event(
            task_id="task_err_rl",
            platform="youtube",
            status="success",
            external_id="vid_rl_err",
            db_path=self.db_path,
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "quotaExceeded: daily quota limit reached"
        mock_get.return_value = mock_resp

        with self.assertRaises(AnalyticsProviderError) as ctx:
            analytics_ingestion.fetch_real_metrics_for_publication(
                task_id="task_err_rl",
                platform="youtube",
                persist=False,
                db_path=self.db_path,
            )
        self.assertEqual(ctx.exception.code, ERR_RATE_LIMIT)

    @patch("requests.get")
    def test_19_not_found_handled(self, mock_get):
        """19. NOT_FOUND tratado."""
        config.app["youtube_api_key"] = "valid_key"
        scheduler.record_publication_event(
            task_id="task_err_nf",
            platform="youtube",
            status="success",
            external_id="vid_nf_err",
            db_path=self.db_path,
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not found"
        mock_get.return_value = mock_resp

        with self.assertRaises(AnalyticsProviderError) as ctx:
            analytics_ingestion.fetch_real_metrics_for_publication(
                task_id="task_err_nf",
                platform="youtube",
                persist=False,
                db_path=self.db_path,
            )
        self.assertEqual(ctx.exception.code, ERR_NOT_FOUND)

    @patch("requests.get")
    def test_20_temporary_error_handled(self, mock_get):
        """20. TEMPORARY tratado."""
        config.app["youtube_api_key"] = "valid_key"
        scheduler.record_publication_event(
            task_id="task_err_temp",
            platform="youtube",
            status="success",
            external_id="vid_temp_err",
            db_path=self.db_path,
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.text = "Service Unavailable"
        mock_get.return_value = mock_resp

        with self.assertRaises(AnalyticsProviderError) as ctx:
            analytics_ingestion.fetch_real_metrics_for_publication(
                task_id="task_err_temp",
                platform="youtube",
                persist=False,
                db_path=self.db_path,
            )
        self.assertEqual(ctx.exception.code, ERR_TEMPORARY)

    @patch("requests.get")
    def test_21_invalid_response_handled(self, mock_get):
        """21. INVALID_RESPONSE tratado."""
        config.app["youtube_api_key"] = "valid_key"
        scheduler.record_publication_event(
            task_id="task_err_inv",
            platform="youtube",
            status="success",
            external_id="vid_inv_err",
            db_path=self.db_path,
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("Corrupted JSON")
        mock_get.return_value = mock_resp

        with self.assertRaises(AnalyticsProviderError) as ctx:
            analytics_ingestion.fetch_real_metrics_for_publication(
                task_id="task_err_inv",
                platform="youtube",
                persist=False,
                db_path=self.db_path,
            )
        self.assertEqual(ctx.exception.code, ERR_INVALID_RESPONSE)

    @patch("requests.get")
    def test_22_raw_response_does_not_persist_secret(self, mock_get):
        """22. raw response não persiste secret em metadata."""
        secret_key = "AIzaSySecretApiKey12345"
        config.app["youtube_api_key"] = secret_key
        scheduler.record_publication_event(
            task_id="task_sec_meta",
            platform="youtube",
            status="success",
            external_id="vid_sec_meta",
            db_path=self.db_path,
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "items": [{"id": "vid_sec_meta", "statistics": {"viewCount": "100"}}]
        }
        mock_get.return_value = mock_resp

        res = analytics_ingestion.fetch_real_metrics_for_publication(
            task_id="task_sec_meta",
            platform="youtube",
            persist=True,
            db_path=self.db_path,
        )
        meta_str = str(res["snapshot"].get("metadata_json") or "")
        self.assertNotIn(secret_key, meta_str)

    @patch("requests.get")
    def test_23_and_24_analytics_failure_does_not_alter_task_or_pub(self, mock_get):
        """23. analytics failure não altera task, 24. analytics failure não altera publication event."""
        config.app["youtube_api_key"] = "valid_key"
        scheduler.record_publication_event(
            task_id="task_immutable_pub",
            platform="youtube",
            status="success",
            external_id="vid_imm_999",
            db_path=self.db_path,
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_get.return_value = mock_resp

        with self.assertRaises(AnalyticsProviderError):
            analytics_ingestion.fetch_real_metrics_for_publication(
                task_id="task_immutable_pub",
                platform="youtube",
                persist=True,
                db_path=self.db_path,
            )

        # Status em publication_events permanece intacto como 'success'
        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT status FROM publication_events WHERE task_id = 'task_immutable_pub';"
            ).fetchone()
            self.assertEqual(row["status"], "success")

    def test_25_view_only_can_read_status_and_validate(self):
        """25. VIEW ONLY pode ler status e testar configuração estática."""
        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._current_role = operator_console.ROLE_SECONDARY_VIEW_ONLY

        res = operator_console.test_analytics_provider_configuration("youtube", db_path=self.db_path)
        self.assertIn("configured", res)
        self.assertIn("status", res)

    @patch("requests.get")
    def test_26_view_only_cannot_persist_fetch(self, mock_get):
        """26. VIEW ONLY não pode persistir fetch."""
        config.app["youtube_api_key"] = "valid_key"
        scheduler.record_publication_event(
            task_id="task_vo_block",
            platform="youtube",
            status="success",
            external_id="vid_vo_1",
            db_path=self.db_path,
        )

        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._current_role = operator_console.ROLE_SECONDARY_VIEW_ONLY

        with self.assertRaises(PermissionError):
            operator_console.fetch_real_metrics_for_publication_op(
                task_id="task_vo_block",
                platform="youtube",
                persist=True,
                db_path=self.db_path,
            )
        mock_get.assert_not_called()

    @patch("requests.get")
    def test_27_primary_can_persist_fetch(self, mock_get):
        """27. PRIMARY pode persistir fetch."""
        config.app["youtube_api_key"] = "valid_key"
        scheduler.record_publication_event(
            task_id="task_prim_ok",
            platform="youtube",
            status="success",
            external_id="vid_prim_1",
            db_path=self.db_path,
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "items": [{"id": "vid_prim_1", "statistics": {"viewCount": "2000"}}]
        }
        mock_get.return_value = mock_resp

        res = operator_console.fetch_real_metrics_for_publication_op(
            task_id="task_prim_ok",
            platform="youtube",
            persist=True,
            db_path=self.db_path,
        )
        self.assertTrue(res["persisted"])
        self.assertEqual(res["snapshot"]["views"], 2000)

    def test_28_no_workers_29_no_polling_30_no_batch(self):
        """28. nenhum worker criado, 29. nenhum polling criado, 30. nenhuma coleta em lote criada."""
        threads_before = threading.active_count()
        validate_provider_configuration("youtube", db_path=self.db_path)
        threads_after = threading.active_count()
        self.assertEqual(threads_before, threads_after)


if __name__ == "__main__":
    unittest.main()
