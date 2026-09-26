import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from app.models import const
from app.services import (
    post_for_me,
    profile_manager,
    scheduler,
    task as tm,
    youtube_publisher,
)
from app.services import state as sm
from app.utils import utils


class TestTikTokPostForMe(unittest.TestCase):
    """Testes completos da integração TikTok via Post for Me Quickstart."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_dir = self.temp_dir.name
        self.db_path = os.path.join(self.tmp_dir, "test_tiktok.db")
        scheduler.init_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        profile_manager.ensure_default_profile(self.db_path)

        self.state = sm.MemoryState()
        self.patcher_state = patch.object(tm.sm, "state", self.state)
        self.patcher_state.start()

        self.video_file = os.path.join(self.tmp_dir, "test_video.mp4")
        with open(self.video_file, "wb") as f:
            f.write(b"\x00\x00\x00\x18ftypmp42" + b"X" * 1024)

    def tearDown(self):
        self.patcher_state.stop()
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. Independent Clients & Secrets Isolation
    # -------------------------------------------------------------------------
    def test_independent_clients_and_env_vars(self):
        """Verifica que post_for_me_client e post_for_me_quickstart_client são instâncias separadas com envs distintas."""
        with patch.dict(os.environ, {
            "POST_FOR_ME_API_KEY": "wl_secret_111",
            "POST_FOR_ME_QUICKSTART_API_KEY": "qs_secret_222",
        }):
            wl_client = post_for_me.PostForMeClient(env_api_key_name="POST_FOR_ME_API_KEY")
            qs_client = post_for_me.PostForMeClient(env_api_key_name="POST_FOR_ME_QUICKSTART_API_KEY")

            self.assertEqual(wl_client.api_key, "wl_secret_111")
            self.assertEqual(qs_client.api_key, "qs_secret_222")
            self.assertNotEqual(wl_client.api_key, qs_client.api_key)

    def test_secrets_sanitization(self):
        """Verifica que sanitize_secrets redige tanto chaves White Label quanto Quickstart."""
        wl_key = "wl_secret_abc123"
        qs_key = "qs_secret_xyz789"
        with patch.dict(os.environ, {
            "POST_FOR_ME_API_KEY": wl_key,
            "POST_FOR_ME_QUICKSTART_API_KEY": qs_key,
        }):
            msg = f"Error with key {wl_key} and other key {qs_key}"
            clean = post_for_me.sanitize_secrets(msg)
            self.assertNotIn(wl_key, clean)
            self.assertNotIn(qs_key, clean)
            self.assertIn("[REDACTED_API_KEY]", clean)

    # -------------------------------------------------------------------------
    # 2. Deterministic TikTok Account Resolution
    # -------------------------------------------------------------------------
    def test_resolve_tiktok_account_channel_default_resolves_real_user_id(self):
        """channel-default-tiktok resolve exatamente para o USER_ID real homologado."""
        client = post_for_me.PostForMeClient(api_key="mock_key")
        mock_accounts = [
            {
                "id": "spc_ApRwpsWI1CKGNskTEXRZb",
                "platform": "tiktok",
                "status": "connected",
                "user_id": post_for_me.CHANNEL_DEFAULT_TIKTOK_USER_ID,
                "username": "Dose Diária De Internet",
            }
        ]
        with patch.object(client, "list_social_accounts", return_value=mock_accounts):
            acc = client.resolve_tiktok_account(expected_account_id="channel-default-tiktok")
            self.assertEqual(acc["id"], "spc_ApRwpsWI1CKGNskTEXRZb")
            self.assertEqual(acc["user_id"], "-00084CZ8cOFQstM-kHqpIgjFOeYUf6w4a4F")
            self.assertEqual(acc["status"], "connected")

    def test_resolve_tiktok_account_username_match_wrong_user_id_fail_closed(self):
        """Username correto com user_id errado NUNCA resolve e falha fechado (FAIL CLOSED)."""
        client = post_for_me.PostForMeClient(api_key="mock_key")
        mock_accounts = [
            {
                "id": "spc_wrong_user",
                "platform": "tiktok",
                "status": "connected",
                "user_id": "wrong_user_id_999",
                "username": "Dose Diária De Internet",
            }
        ]
        with patch.object(client, "list_social_accounts", return_value=mock_accounts):
            with self.assertRaises(post_for_me.PostForMeAccountNotFoundError):
                client.resolve_tiktok_account(expected_account_id="channel-default-tiktok")

    def test_resolve_tiktok_account_real_user_id_different_username_resolves(self):
        """User_id correto com username alterado continua resolvendo com sucesso."""
        client = post_for_me.PostForMeClient(api_key="mock_key")
        mock_accounts = [
            {
                "id": "spc_ApRwpsWI1CKGNskTEXRZb",
                "platform": "tiktok",
                "status": "connected",
                "user_id": post_for_me.CHANNEL_DEFAULT_TIKTOK_USER_ID,
                "username": "Novo Nome Alterado No TikTok",
            }
        ]
        with patch.object(client, "list_social_accounts", return_value=mock_accounts):
            acc = client.resolve_tiktok_account(expected_account_id="channel-default-tiktok")
            self.assertEqual(acc["id"], "spc_ApRwpsWI1CKGNskTEXRZb")
            self.assertEqual(acc["user_id"], "-00084CZ8cOFQstM-kHqpIgjFOeYUf6w4a4F")

    def test_resolve_tiktok_account_disconnected_fail_closed(self):
        """Conta TikTok com user_id correto mas desconectada falha fechada com PostForMeAccountDisconnectedError."""
        client = post_for_me.PostForMeClient(api_key="mock_key")
        mock_accounts = [
            {
                "id": "spc_ApRwpsWI1CKGNskTEXRZb",
                "platform": "tiktok",
                "status": "disconnected",
                "user_id": post_for_me.CHANNEL_DEFAULT_TIKTOK_USER_ID,
                "username": "Dose Diária De Internet",
            }
        ]
        with patch.object(client, "list_social_accounts", return_value=mock_accounts):
            with self.assertRaises(post_for_me.PostForMeAccountDisconnectedError):
                client.resolve_tiktok_account(expected_account_id="channel-default-tiktok")

    def test_resolve_tiktok_account_duplicate_user_id_ambiguous_fail_closed(self):
        """Duas contas com mesmo user_id geram PostForMeAmbiguousAccountError (Fail Closed)."""
        client = post_for_me.PostForMeClient(api_key="mock_key")
        mock_accounts = [
            {
                "id": "spc_1",
                "platform": "tiktok",
                "status": "connected",
                "user_id": post_for_me.CHANNEL_DEFAULT_TIKTOK_USER_ID,
            },
            {
                "id": "spc_2",
                "platform": "tiktok",
                "status": "connected",
                "user_id": post_for_me.CHANNEL_DEFAULT_TIKTOK_USER_ID,
            },
        ]
        with patch.object(client, "list_social_accounts", return_value=mock_accounts):
            with self.assertRaises(post_for_me.PostForMeAmbiguousAccountError):
                client.resolve_tiktok_account(expected_account_id="channel-default-tiktok")

    def test_resolve_tiktok_account_reconnection_spc_changed_resolves(self):
        """spc_ diferente após reconexão da conta, mantendo mesmo user_id, continua resolvendo dinamicamente."""
        client = post_for_me.PostForMeClient(api_key="mock_key")
        mock_accounts = [
            {
                "id": "spc_NEW_RECONNECTED_AFTER_DISCONNECT",
                "platform": "tiktok",
                "status": "connected",
                "user_id": post_for_me.CHANNEL_DEFAULT_TIKTOK_USER_ID,
                "username": "Dose Diária De Internet",
            }
        ]
        with patch.object(client, "list_social_accounts", return_value=mock_accounts):
            acc = client.resolve_tiktok_account(expected_account_id="channel-default-tiktok")
            self.assertEqual(acc["id"], "spc_NEW_RECONNECTED_AFTER_DISCONNECT")
            self.assertEqual(acc["user_id"], "-00084CZ8cOFQstM-kHqpIgjFOeYUf6w4a4F")

    # -------------------------------------------------------------------------
    # 3. Deterministic external_id & Idempotency in publish_tiktok_video
    # -------------------------------------------------------------------------
    def test_publish_tiktok_video_reuse_existing_success(self):
        """Reutiliza post com sucesso já existente sem novo upload e preserva privacidade."""
        client = post_for_me.PostForMeClient(api_key="mock_key")
        mock_account = {"id": "soc_acc_tt", "platform": "tiktok", "status": "connected", "user_id": "tt_uid"}

        existing_success = {
            "post_id": "pfm_existing_111",
            "social_account_id": "soc_acc_tt",
            "status": "success",
            "external_id": "video-factory:task-tt-1:tiktok:channel-default-tiktok",
            "result_info": {
                "tiktok_video_id": "7123456789012345678",
                "url": "https://www.tiktok.com/@user/video/7123456789012345678",
                "privacy_status": "public",
            },
            "post": {
                "platform_configurations": {
                    "tiktok": {"privacy_status": "public"}
                }
            }
        }

        classification = {
            "success_posts": [existing_success],
            "active_posts": [],
            "failed_posts": [],
            "inconsistent_posts": [],
        }

        with (
            patch.object(client, "resolve_tiktok_account", return_value=mock_account),
            patch.object(client, "classify_existing_posts", return_value=classification),
            patch.object(client, "create_media_upload_url") as mock_upload,
        ):
            res = client.publish_tiktok_video(
                video_path=self.video_file,
                caption="Test TikTok",
                task_id="task-tt-1",
                channel_id="channel-default-tiktok",
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["request_id"], "pfm_existing_111")
            self.assertEqual(res["external_id"], "7123456789012345678")
            self.assertEqual(res["privacy_status"], "public")
            mock_upload.assert_not_called()

    def test_publish_tiktok_video_existing_success_unknown_privacy_fail_closed(self):
        """Sucesso existente sem privacidade comprovada falha fechado com EXISTING_SUCCESS_PRIVACY_UNKNOWN."""
        client = post_for_me.PostForMeClient(api_key="mock_key")
        mock_account = {"id": "soc_acc_tt", "platform": "tiktok", "status": "connected", "user_id": "tt_uid"}

        existing_success = {
            "post_id": "pfm_existing_222",
            "social_account_id": "soc_acc_tt",
            "status": "success",
            "external_id": "video-factory:task-tt-2:tiktok:channel-default-tiktok",
            "result_info": {
                "tiktok_video_id": "7123456789012345678",
                "url": "https://www.tiktok.com/@user/video/7123456789012345678",
                # sem privacy_status
            },
            "post": {}
        }

        classification = {
            "success_posts": [existing_success],
            "active_posts": [],
            "failed_posts": [],
            "inconsistent_posts": [],
        }

        with (
            patch.object(client, "resolve_tiktok_account", return_value=mock_account),
            patch.object(client, "classify_existing_posts", return_value=classification),
        ):
            res = client.publish_tiktok_video(
                video_path=self.video_file,
                caption="Test TikTok",
                task_id="task-tt-2",
                channel_id="channel-default-tiktok",
            )
            self.assertFalse(res["success"])
            self.assertEqual(res["error_code"], "EXISTING_SUCCESS_PRIVACY_UNKNOWN")

    def test_publish_tiktok_video_active_resume_success(self):
        """Retoma polling de post ativo existente sem novo upload."""
        client = post_for_me.PostForMeClient(api_key="mock_key")
        mock_account = {"id": "soc_acc_tt", "platform": "tiktok", "status": "connected", "user_id": "tt_uid"}

        active_post = {
            "post_id": "pfm_active_333",
            "social_account_id": "soc_acc_tt",
            "status": "processing",
            "external_id": "video-factory:task-tt-3:tiktok:channel-default-tiktok",
            "post": {
                "platform_configurations": {
                    "tiktok": {"privacy_status": "public"}
                }
            }
        }

        classification = {
            "success_posts": [],
            "active_posts": [active_post],
            "failed_posts": [],
            "inconsistent_posts": [],
        }

        mock_final_post = {"id": "pfm_active_333", "status": "success"}
        mock_post_result = {
            "social_account_id": "soc_acc_tt",
            "status": "success",
            "platform_data": {
                "platform_post_id": "7987654321",
                "url": "https://www.tiktok.com/@user/video/7987654321",
                "privacy_status": "public",
            },
        }

        with (
            patch.object(client, "resolve_tiktok_account", return_value=mock_account),
            patch.object(client, "classify_existing_posts", return_value=classification),
            patch.object(client, "create_media_upload_url") as mock_upload,
            patch.object(client, "poll_social_post", return_value=mock_final_post),
            patch.object(client, "get_post_result_for_account", return_value=mock_post_result),
        ):
            res = client.publish_tiktok_video(
                video_path=self.video_file,
                caption="Test TikTok",
                task_id="task-tt-3",
                channel_id="channel-default-tiktok",
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["request_id"], "pfm_active_333")
            self.assertEqual(res["external_id"], "7987654321")
            self.assertEqual(res["privacy_status"], "public")
            mock_upload.assert_not_called()

    def test_publish_tiktok_video_active_resume_unknown_privacy_fail_closed(self):
        """Post ativo reutilizado que conclui sem privacidade comprovada falha fechado."""
        client = post_for_me.PostForMeClient(api_key="mock_key")
        mock_account = {"id": "soc_acc_tt", "platform": "tiktok", "status": "connected", "user_id": "tt_uid"}

        active_post = {
            "post_id": "pfm_active_444",
            "social_account_id": "soc_acc_tt",
            "status": "processing",
            "external_id": "video-factory:task-tt-4:tiktok:channel-default-tiktok",
            "post": {}
        }

        classification = {
            "success_posts": [],
            "active_posts": [active_post],
            "failed_posts": [],
            "inconsistent_posts": [],
        }

        mock_final_post = {"id": "pfm_active_444", "status": "success"}
        mock_post_result = {
            "social_account_id": "soc_acc_tt",
            "status": "success",
            "platform_data": {
                "platform_post_id": "7987654321",
                "url": "https://www.tiktok.com/@user/video/7987654321",
            },
        }

        with (
            patch.object(client, "resolve_tiktok_account", return_value=mock_account),
            patch.object(client, "classify_existing_posts", return_value=classification),
            patch.object(client, "poll_social_post", return_value=mock_final_post),
            patch.object(client, "get_post_result_for_account", return_value=mock_post_result),
        ):
            res = client.publish_tiktok_video(
                video_path=self.video_file,
                caption="Test TikTok",
                task_id="task-tt-4",
                channel_id="channel-default-tiktok",
            )
            self.assertFalse(res["success"])
            self.assertEqual(res["error_code"], "ACTIVE_SUCCESS_PRIVACY_UNKNOWN")

    def test_publish_tiktok_video_terminal_failed_retry_success(self):
        """Post anterior com falha terminal permite nova tentativa controlada com revalidação."""
        client = post_for_me.PostForMeClient(api_key="mock_key")
        mock_account = {"id": "soc_acc_tt", "platform": "tiktok", "status": "connected", "user_id": "tt_uid"}

        failed_post = {
            "post_id": "pfm_failed_555",
            "social_account_id": "soc_acc_tt",
            "status": "failed",
            "external_id": "video-factory:task-tt-5:tiktok:channel-default-tiktok",
        }

        classification = {
            "success_posts": [],
            "active_posts": [],
            "failed_posts": [failed_post],
            "inconsistent_posts": [],
        }

        new_post = {"id": "pfm_new_666", "status": "processing"}
        mock_final_post = {"id": "pfm_new_666", "status": "success"}
        mock_post_result = {
            "social_account_id": "soc_acc_tt",
            "status": "success",
            "platform_data": {
                "platform_post_id": "7111222333",
                "url": "https://www.tiktok.com/@user/video/7111222333",
                "privacy_status": "public",
            },
        }

        with (
            patch.object(client, "resolve_tiktok_account", return_value=mock_account),
            patch.object(client, "classify_existing_posts", return_value=classification),
            patch.object(client, "create_media_upload_url", return_value=("https://upload.url", "https://media.url")),
            patch.object(client, "upload_media_binary"),
            patch.object(client, "create_tiktok_social_post", return_value=new_post),
            patch.object(client, "poll_social_post", return_value=mock_final_post),
            patch.object(client, "get_post_result_for_account", return_value=mock_post_result),
        ):
            res = client.publish_tiktok_video(
                video_path=self.video_file,
                caption="Test TikTok",
                task_id="task-tt-5",
                channel_id="channel-default-tiktok",
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["request_id"], "pfm_new_666")
            self.assertEqual(res["external_id"], "7111222333")

    # -------------------------------------------------------------------------
    # 4. Profile Guardrail (Only channel-default-tiktok supported)
    # -------------------------------------------------------------------------
    def test_profile_without_tiktok_channel_blocked(self):
        """Perfil sem canal TikTok habilitado (ex: profile-historias-misterio) é bloqueado deterministicamente."""
        profile_manager.create_profile(
            name="Histórias Mistério",
            profile_id="profile-historias-misterio",
            db_path=self.db_path,
        )
        task_id = "task-misterio-1"
        profile_manager.save_task_profile(task_id, "profile-historias-misterio", db_path=self.db_path)

        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        task_video = os.path.join(task_dir, "final-1.mp4")
        shutil.copyfile(self.video_file, task_video)
        script_file = os.path.join(task_dir, "script.json")
        with open(script_file, "w", encoding="utf-8") as f:
            json.dump({"script": "Test script", "params": {"video_subject": "Test"}}, f)
        self.state.update_task(task_id, state=const.TASK_STATE_COMPLETE, progress=100)

        with (
            patch.dict(os.environ, {"POST_FOR_ME_QUICKSTART_API_KEY": "test-qs-key"}),
            patch.object(post_for_me.post_for_me_quickstart_client, "is_configured", return_value=True),
            patch("app.services.operator_console.require_primary_instance", return_value=True),
            patch("app.services.operator_console.is_factory_paused", return_value=False),
        ):
            success, msg = tm.publish_task(
                task_id=task_id,
                platforms=["tiktok"],
                synchronous=True,
                db_path=self.db_path,
            )
            self.assertFalse(success)
            self.assertIn("has no enabled TikTok channel", msg)
        shutil.rmtree(task_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # 5. Multi-platform Routing & Idempotency
    # -------------------------------------------------------------------------
    def test_routing_dual_platforms_independent_execution(self):
        """["youtube", "tiktok"] executa ambos via seus clientes Post for Me independentes."""
        task_id = "task-dual-1"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        task_video = os.path.join(task_dir, "final-1.mp4")
        shutil.copyfile(self.video_file, task_video)
        script_file = os.path.join(task_dir, "script.json")
        with open(script_file, "w", encoding="utf-8") as f:
            json.dump({"script": "Test script", "params": {"video_subject": "Test"}}, f)
        self.state.update_task(task_id, state=const.TASK_STATE_COMPLETE, progress=100)

        youtube_publisher.set_youtube_publish_provider("post_for_me", db_path=self.db_path)

        mock_yt_res = {
            "success": True,
            "provider": "post_for_me",
            "request_id": "yt_req_1",
            "external_id": "yt_vid_1",
            "external_url": "https://youtube.com/watch?v=yt_vid_1",
            "privacy_status": "public",
        }
        mock_tt_res = {
            "success": True,
            "provider": "post_for_me",
            "request_id": "tt_req_1",
            "external_id": "tt_vid_1",
            "external_url": "https://tiktok.com/@u/video/tt_vid_1",
            "privacy_status": "public",
        }

        with (
            patch.dict(os.environ, {
                "POST_FOR_ME_API_KEY": "wl-key",
                "POST_FOR_ME_QUICKSTART_API_KEY": "qs-key",
            }),
            patch.object(post_for_me.post_for_me_client, "is_configured", return_value=True),
            patch.object(post_for_me.post_for_me_quickstart_client, "is_configured", return_value=True),
            patch.object(youtube_publisher, "publish_youtube_video", return_value=mock_yt_res) as mock_yt,
            patch.object(post_for_me.post_for_me_quickstart_client, "publish_tiktok_video", return_value=mock_tt_res) as mock_tt,
            patch("app.services.operator_console.require_primary_instance", return_value=True),
            patch("app.services.operator_console.is_factory_paused", return_value=False),
        ):
            success, msg = tm.publish_task(
                task_id=task_id,
                platforms=["youtube", "tiktok"],
                synchronous=True,
                db_path=self.db_path,
            )
            self.assertTrue(success, f"publish_task failed: {msg}")
            mock_yt.assert_called_once()
            mock_tt.assert_called_once()

            # Confirma que eventos foram gravados separadamente
            with scheduler.get_connection(self.db_path) as conn:
                yt_evt = conn.execute("SELECT * FROM publication_events WHERE task_id = ? AND platform = 'youtube'", (task_id,)).fetchone()
                tt_evt = conn.execute("SELECT * FROM publication_events WHERE task_id = ? AND platform = 'tiktok'", (task_id,)).fetchone()
                self.assertIsNotNone(yt_evt)
                self.assertIsNotNone(tt_evt)
                self.assertEqual(yt_evt["external_id"], "yt_vid_1")
                self.assertEqual(tt_evt["external_id"], "tt_vid_1")

        shutil.rmtree(task_dir, ignore_errors=True)

    def test_retry_after_partial_failure_does_not_republish_success_platform(self):
        """Se YouTube sucedeu mas TikTok falhou, retry com as duas plataformas NÃO republica YouTube."""
        task_id = "task-partial-retry"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        task_video = os.path.join(task_dir, "final-1.mp4")
        shutil.copyfile(self.video_file, task_video)
        script_file = os.path.join(task_dir, "script.json")
        with open(script_file, "w", encoding="utf-8") as f:
            json.dump({"script": "Test script", "params": {"video_subject": "Test"}}, f)
        self.state.update_task(task_id, state=const.TASK_STATE_COMPLETE, progress=100)

        youtube_publisher.set_youtube_publish_provider("post_for_me", db_path=self.db_path)

        # Pré-grava sucesso do YouTube
        scheduler.record_publication_event(
            task_id=task_id,
            platform="youtube",
            status="success",
            external_id="yt_already_done",
            provider_request_id="yt_req_done",
            channel_id="channel-default-youtube",
            profile_id="default",
            external_url="https://youtube.com/watch?v=yt_already_done",
            privacy_status="public",
            db_path=self.db_path,
        )

        mock_tt_res = {
            "success": True,
            "provider": "post_for_me",
            "request_id": "tt_req_new",
            "external_id": "tt_vid_new",
            "external_url": "https://tiktok.com/@u/video/tt_vid_new",
            "privacy_status": "public",
        }

        with (
            patch.dict(os.environ, {
                "POST_FOR_ME_API_KEY": "wl-key",
                "POST_FOR_ME_QUICKSTART_API_KEY": "qs-key",
            }),
            patch.object(post_for_me.post_for_me_client, "is_configured", return_value=True),
            patch.object(post_for_me.post_for_me_quickstart_client, "is_configured", return_value=True),
            patch.object(youtube_publisher, "publish_youtube_video") as mock_yt,
            patch.object(post_for_me.post_for_me_quickstart_client, "publish_tiktok_video", return_value=mock_tt_res) as mock_tt,
            patch("app.services.operator_console.require_primary_instance", return_value=True),
            patch("app.services.operator_console.is_factory_paused", return_value=False),
        ):
            success, msg = tm.publish_task(
                task_id=task_id,
                platforms=["youtube", "tiktok"],
                synchronous=True,
                db_path=self.db_path,
            )
            self.assertTrue(success, f"publish_task failed: {msg}")
            # YouTube NÃO deve ser chamado novamente!
            mock_yt.assert_not_called()
            # TikTok DEVE ser chamado e sucedido
            mock_tt.assert_called_once()

        shutil.rmtree(task_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
