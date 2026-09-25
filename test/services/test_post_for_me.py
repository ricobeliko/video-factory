"""Testes direcionados do Post for Me API Client e Publicador YouTube (Fase V15-E.2).

ZERO chamadas de rede real: todas as interações HTTP são 100% mockadas.
NENHUMA API Key real utilizada.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.services import post_for_me
from app.services.post_for_me import (
    CHANNEL_DEFAULT_YT_ID,
    CHANNEL_MYSTERY_YT_ID,
    PostForMeAccountDisconnectedError,
    PostForMeAccountNotFoundError,
    PostForMeAmbiguousAccountError,
    PostForMeAmbiguousPostError,
    PostForMeAmbiguousResultError,
    PostForMeAuthError,
    PostForMeClient,
    PostForMeTimeoutError,
    PostForMeUploadError,
    extract_post_result,
    extract_youtube_video_id,
    resolve_target_youtube_channel_id,
    sanitize_secrets,
)


class TestPostForMeClient(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.video_file = os.path.join(self.temp_dir.name, "test_video.mp4")
        with open(self.video_file, "wb") as f:
            f.write(b"\x00\x00\x00\x18ftypmp42" + b"A" * 1024)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_missing_api_key_fails_closed(self):
        """1. API key ausente -> fail closed."""
        with patch.dict(os.environ, {}, clear=True):
            client = PostForMeClient(api_key="")
            self.assertFalse(client.is_configured())
            res = client.publish_video(
                video_path=self.video_file,
                title="Title",
                caption="Caption",
                channel_id="channel-default-youtube",
                task_id="task-001",
            )
            self.assertFalse(res["success"])
            self.assertEqual(res["error_code"], "AUTH_CONFIG_MISSING")
            self.assertIn("ausente", res["error"].lower())

    def test_base_url_default_and_override(self):
        """Base URL padrão e override por variável de ambiente."""
        client_def = PostForMeClient(api_key="mock-key")
        self.assertEqual(client_def.base_url, "https://api.postforme.dev/v1")

        with patch.dict(os.environ, {"POST_FOR_ME_BASE_URL": "https://custom.api/v1/"}):
            client_custom = PostForMeClient(api_key="mock-key")
            self.assertEqual(client_custom.base_url, "https://custom.api/v1")

    def test_resolve_default_channel_correctly(self):
        """4. Resolve default channel corretamente."""
        c_id = resolve_target_youtube_channel_id(channel_id="channel-default-youtube")
        self.assertEqual(c_id, CHANNEL_DEFAULT_YT_ID)
        self.assertEqual(c_id, "UCss-ng7mkGuB2v-5KKtIN9A")

        # Fallback por profile_id="default"
        c_id_prof = resolve_target_youtube_channel_id(channel_id=None, profile_id="default")
        self.assertEqual(c_id_prof, CHANNEL_DEFAULT_YT_ID)

    def test_resolve_mystery_channel_correctly(self):
        """5. Resolve mystery channel corretamente."""
        c_id = resolve_target_youtube_channel_id(channel_id="channel-historias-misterio-youtube")
        self.assertEqual(c_id, CHANNEL_MYSTERY_YT_ID)
        self.assertEqual(c_id, "UCGJaC83EuaOwiZ0a3-KqUZA")

        # Fallback por profile_id="profile-historias-misterio"
        c_id_prof = resolve_target_youtube_channel_id(channel_id=None, profile_id="profile-historias-misterio")
        self.assertEqual(c_id_prof, CHANNEL_MYSTERY_YT_ID)

    def test_wrong_channel_never_accepted(self):
        """6. Canal errado nunca é aceito (Fail Closed)."""
        self.assertIsNone(resolve_target_youtube_channel_id(channel_id="channel-outro-invalido"))
        self.assertIsNone(resolve_target_youtube_channel_id(channel_id="tiktok-default"))

        client = PostForMeClient(api_key="mock-key")
        res = client.publish_video(
            video_path=self.video_file,
            title="Title",
            caption="Caption",
            channel_id="invalid-channel",
            task_id="task-002",
        )
        self.assertFalse(res["success"])
        self.assertEqual(res["error_code"], "CHANNEL_RESOLUTION_FAILED")

    def test_account_resolution_by_user_id_and_connected_status(self):
        """Resolução determinística de conta por user_id do YouTube e status connected."""
        client = PostForMeClient(api_key="mock-key")
        mock_accounts = [
            {
                "id": "spc_wrong_platform",
                "platform": "tiktok",
                "user_id": CHANNEL_DEFAULT_YT_ID,
                "status": "connected",
            },
            {
                "id": "spc_yt_default",
                "platform": "youtube",
                "user_id": CHANNEL_DEFAULT_YT_ID,
                "status": "connected",
                "name": "Dose Diária De Internet",
            },
            {
                "id": "spc_yt_mystery",
                "platform": "youtube",
                "user_id": CHANNEL_MYSTERY_YT_ID,
                "status": "connected",
                "name": "Dose Diária de Histórias e mistérios",
            },
        ]
        with patch.object(client, "list_social_accounts", return_value=mock_accounts):
            acc_default = client.resolve_youtube_account(CHANNEL_DEFAULT_YT_ID)
            self.assertEqual(acc_default["id"], "spc_yt_default")

            acc_mystery = client.resolve_youtube_account(CHANNEL_MYSTERY_YT_ID)
            self.assertEqual(acc_mystery["id"], "spc_yt_mystery")

    def test_disconnected_account_blocks(self):
        """7. Conta disconnected bloqueia (Fail Closed)."""
        client = PostForMeClient(api_key="mock-key")
        mock_accounts = [
            {
                "id": "spc_disconnected",
                "platform": "youtube",
                "user_id": CHANNEL_DEFAULT_YT_ID,
                "status": "disconnected",
            }
        ]
        with patch.object(client, "list_social_accounts", return_value=mock_accounts):
            with self.assertRaises(PostForMeAccountDisconnectedError):
                client.resolve_youtube_account(CHANNEL_DEFAULT_YT_ID)

    def test_ambiguous_multiple_accounts_blocks(self):
        """8. Múltiplas contas ambíguas bloqueiam (Fail Closed)."""
        client = PostForMeClient(api_key="mock-key")
        mock_accounts = [
            {"id": "spc_1", "platform": "youtube", "user_id": CHANNEL_DEFAULT_YT_ID, "status": "connected"},
            {"id": "spc_2", "platform": "youtube", "user_id": CHANNEL_DEFAULT_YT_ID, "status": "connected"},
        ]
        with patch.object(client, "list_social_accounts", return_value=mock_accounts):
            with self.assertRaises(PostForMeAmbiguousAccountError):
                client.resolve_youtube_account(CHANNEL_DEFAULT_YT_ID)

    def test_account_not_found_blocks(self):
        """Nenhuma conta encontrada bloqueia."""
        client = PostForMeClient(api_key="mock-key")
        with patch.object(client, "list_social_accounts", return_value=[]):
            with self.assertRaises(PostForMeAccountNotFoundError):
                client.resolve_youtube_account(CHANNEL_DEFAULT_YT_ID)

    def test_create_upload_url_put_and_create_post(self):
        """9. create-upload-url -> PUT -> create post -> get_post_result."""
        client = PostForMeClient(api_key="mock-key")
        fake_account = {"id": "spc_yt_01", "platform": "youtube", "user_id": CHANNEL_DEFAULT_YT_ID, "status": "connected"}

        with (
            patch.object(client, "resolve_youtube_account", return_value=fake_account),
            patch.object(client, "get_social_post_by_external_id", return_value=None),
            patch.object(client, "create_media_upload_url", return_value=("https://s3.fake/upload", "https://s3.fake/media.mp4")) as mock_create_upload,
            patch.object(client, "upload_media_binary") as mock_put,
            patch.object(client, "create_social_post", return_value={"id": "spt_100", "status": "processed"}) as mock_create_post,
            patch.object(client, "poll_social_post", return_value={"id": "spt_100", "status": "processed"}),
            patch.object(client, "get_post_result_for_account", return_value={
                "id": "spr_01",
                "social_account_id": "spc_yt_01",
                "post_id": "spt_100",
                "success": True,
                "platform_data": {"id": "YT_VID_999", "url": "https://www.youtube.com/watch?v=YT_VID_999"},
            }) as mock_get_result,
        ):
            res = client.publish_video(
                video_path=self.video_file,
                title="Meu Shorts Incrível",
                caption="Descrição top",
                channel_id="channel-default-youtube",
                task_id="task-42",
                privacy_status="public",
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["provider"], "post_for_me")
            self.assertEqual(res["request_id"], "spt_100")
            self.assertEqual(res["external_id"], "YT_VID_999")
            self.assertEqual(res["external_url"], "https://www.youtube.com/watch?v=YT_VID_999")

            mock_create_upload.assert_called_once_with()
            mock_put.assert_called_once_with("https://s3.fake/upload", self.video_file)
            mock_create_post.assert_called_once()
            mock_get_result.assert_called_once_with(post_id="spt_100", social_account_id="spc_yt_01")
            call_kwargs = mock_create_post.call_args.kwargs
            self.assertEqual(call_kwargs["media_url"], "https://s3.fake/media.mp4")
            self.assertEqual(call_kwargs["social_account_id"], "spc_yt_01")
            self.assertEqual(call_kwargs["privacy_status"], "public")

    def test_privacy_statuses_public_private_unlisted_propagated(self):
        """10, 11, 12. Privacy public, private, unlisted propagadas."""
        client = PostForMeClient(api_key="mock-key")
        for priv in ("public", "private", "unlisted"):
            with patch.object(client, "_request", return_value={"data": {"id": f"spt_{priv}"}}):
                post = client.create_social_post(
                    caption="Caption",
                    social_account_id="spc_1",
                    media_url="https://media.url",
                    title="Title",
                    privacy_status=priv,
                    external_id="ext-01",
                )
                self.assertEqual(post["id"], f"spt_{priv}")

    def test_invalid_privacy_status_blocked(self):
        """13. Privacy inválida bloqueada (Fail Closed)."""
        client = PostForMeClient(api_key="mock-key")
        with self.assertRaises(ValueError):
            client.create_social_post(
                caption="Caption",
                social_account_id="spc_1",
                media_url="https://media.url",
                title="Title",
                privacy_status="draft",
                external_id="ext-01",
            )

        res = client.publish_video(
            video_path=self.video_file,
            title="Title",
            caption="Caption",
            channel_id="channel-default-youtube",
            task_id="task-01",
            privacy_status="direct_poc_private",
        )
        self.assertFalse(res["success"])
        self.assertEqual(res["error_code"], "INVALID_PRIVACY_STATUS")

    def test_deterministic_external_id(self):
        """14. external_id determinístico: video-factory:<task_id>:youtube:<channel_id>."""
        client = PostForMeClient(api_key="mock-key")
        fake_account = {"id": "spc_01", "platform": "youtube", "user_id": CHANNEL_DEFAULT_YT_ID, "status": "connected"}

        captured_external_id = []

        def mock_get_ext(ext_id):
            captured_external_id.append(ext_id)
            return None

        with (
            patch.object(client, "resolve_youtube_account", return_value=fake_account),
            patch.object(client, "get_social_post_by_external_id", side_effect=mock_get_ext),
            patch.object(client, "create_media_upload_url", return_value=("https://upload", "https://media")),
            patch.object(client, "upload_media_binary"),
            patch.object(client, "create_social_post", return_value={"id": "spt_10"}),
            patch.object(client, "poll_social_post", return_value={"id": "spt_10", "status": "processed"}),
            patch.object(client, "get_post_result_for_account", return_value={
                "id": "spr_10",
                "social_account_id": "spc_01",
                "success": True,
                "platform_data": {"id": "YT_01"},
            }),
        ):
            client.publish_video(
                video_path=self.video_file,
                title="Title",
                caption="Caption",
                channel_id="channel-default-youtube",
                task_id="task-xyz-987",
            )

            expected_id = "video-factory:task-xyz-987:youtube:channel-default-youtube"
            self.assertEqual(captured_external_id, [expected_id, expected_id])

    def test_retry_finds_existing_post_and_does_not_duplicate(self):
        """15. Retry encontra post existente e NÃO cria duplicado."""
        client = PostForMeClient(api_key="mock-key")
        fake_account = {"id": "spc_01", "platform": "youtube", "user_id": CHANNEL_DEFAULT_YT_ID, "status": "connected"}
        existing_post = {
            "id": "spt_existing_555",
            "external_id": "video-factory:task-dup-01:youtube:channel-default-youtube",
            "status": "processed",
            "platform_configurations": {"youtube": {"privacy_status": "public"}},
        }

        with (
            patch.object(client, "resolve_youtube_account", return_value=fake_account),
            patch.object(client, "get_social_post_by_external_id", return_value=existing_post),
            patch.object(client, "create_media_upload_url") as mock_upload,
            patch.object(client, "create_social_post") as mock_create,
            patch.object(client, "poll_social_post", return_value=existing_post),
            patch.object(client, "get_post_result_for_account", return_value={
                "id": "spr_01",
                "social_account_id": "spc_01",
                "success": True,
                "platform_data": {"id": "YT_EXISTING_VID"},
            }),
        ):
            res = client.publish_video(
                video_path=self.video_file,
                title="Title",
                caption="Caption",
                channel_id="channel-default-youtube",
                task_id="task-dup-01",
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["request_id"], "spt_existing_555")
            self.assertEqual(res["external_id"], "YT_EXISTING_VID")

            # upload e criação de post NÃO foram chamados
            mock_upload.assert_not_called()
            mock_create.assert_not_called()

    def test_processing_polling_success(self):
        """16. processing -> polling -> success."""
        client = PostForMeClient(api_key="mock-key")
        poll_responses = [
            {"id": "spt_poll", "status": "processing"},
            {"id": "spt_poll", "status": "processing"},
            {"id": "spt_poll", "status": "processed"},
        ]
        with (
            patch.object(client, "get_social_post", side_effect=poll_responses),
            patch("time.sleep", return_value=None),
        ):
            post = client.poll_social_post("spt_poll", timeout_sec=10, poll_interval_sec=0.1)
            self.assertEqual(post["status"], "processed")

    def test_poll_social_post_accepts_processed_status(self):
        """GAP 1: poll_social_post aceita 'processed' como estado terminal."""
        client = PostForMeClient(api_key="mock-key")
        poll_responses = [
            {"id": "spt_poll_proc", "status": "processing"},
            {"id": "spt_poll_proc", "status": "processed"},
        ]
        with (
            patch.object(client, "get_social_post", side_effect=poll_responses),
            patch("time.sleep", return_value=None),
        ):
            post = client.poll_social_post("spt_poll_proc", timeout_sec=10, poll_interval_sec=0.1)
            self.assertEqual(post["status"], "processed")

    def test_processing_to_processed_post_result_success(self):
        """GAP 1 & 2: processing -> processed -> Post Result success -> publicação success."""
        client = PostForMeClient(api_key="mock-key")
        fake_account = {"id": "spc_01", "platform": "youtube", "user_id": CHANNEL_DEFAULT_YT_ID, "status": "connected"}

        with (
            patch.object(client, "resolve_youtube_account", return_value=fake_account),
            patch.object(client, "get_social_post_by_external_id", return_value=None),
            patch.object(client, "create_media_upload_url", return_value=("https://up", "https://media")),
            patch.object(client, "upload_media_binary"),
            patch.object(client, "create_social_post", return_value={"id": "spt_ok", "status": "processing"}),
            patch.object(client, "poll_social_post", return_value={"id": "spt_ok", "status": "processed"}),
            patch.object(client, "get_post_result_for_account", return_value={
                "id": "spr_success",
                "post_id": "spt_ok",
                "social_account_id": "spc_01",
                "success": True,
                "platform_data": {
                    "id": "YT_PROC_SUCCESS",
                    "url": "https://www.youtube.com/watch?v=YT_PROC_SUCCESS",
                },
            }),
        ):
            res = client.publish_video(
                video_path=self.video_file,
                title="Title Success",
                caption="Caption",
                channel_id="channel-default-youtube",
                task_id="task-proc-succ-01",
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["request_id"], "spt_ok")
            self.assertEqual(res["external_id"], "YT_PROC_SUCCESS")
            self.assertEqual(res["external_url"], "https://www.youtube.com/watch?v=YT_PROC_SUCCESS")
            self.assertIsNone(res["error"])

    def test_processing_to_processed_post_result_failure(self):
        """GAP 1 & 2: processing -> processed -> Post Result failure -> publicação failure."""
        client = PostForMeClient(api_key="mock-key")
        fake_account = {"id": "spc_01", "platform": "youtube", "user_id": CHANNEL_DEFAULT_YT_ID, "status": "connected"}

        with (
            patch.object(client, "resolve_youtube_account", return_value=fake_account),
            patch.object(client, "get_social_post_by_external_id", return_value=None),
            patch.object(client, "create_media_upload_url", return_value=("https://up", "https://media")),
            patch.object(client, "upload_media_binary"),
            patch.object(client, "create_social_post", return_value={"id": "spt_fail_proc", "status": "processing"}),
            patch.object(client, "poll_social_post", return_value={"id": "spt_fail_proc", "status": "processed"}),
            patch.object(client, "get_post_result_for_account", return_value={
                "id": "spr_fail",
                "post_id": "spt_fail_proc",
                "social_account_id": "spc_01",
                "success": False,
                "error": {"message": "Account copyright strike limit reached"},
            }),
        ):
            res = client.publish_video(
                video_path=self.video_file,
                title="Title Failure",
                caption="Caption",
                channel_id="channel-default-youtube",
                task_id="task-proc-fail-01",
            )
            self.assertFalse(res["success"])
            self.assertEqual(res["error_code"], "POST_RESULT_FAILED")
            self.assertIn("Account copyright strike limit reached", res["error"])

    def test_list_social_post_results_and_get_post_result_for_account(self):
        """GAP 2: list_social_post_results e get_post_result_for_account chamam GET /v1/social-post-results."""
        client = PostForMeClient(api_key="mock-key")
        fake_results_data = {
            "data": [
                {
                    "id": "spr_other",
                    "post_id": "spt_100",
                    "social_account_id": "spc_tiktok_01",
                    "success": True,
                },
                {
                    "id": "spr_yt",
                    "post_id": "spt_100",
                    "social_account_id": "spc_yt_01",
                    "success": True,
                    "platform_data": {"id": "YT_REAL_001", "url": "https://youtu.be/YT_REAL_001"},
                },
            ],
            "meta": {"total": 2, "offset": 0, "limit": 10, "next": None},
        }

        with patch.object(client, "_request", return_value=fake_results_data) as mock_req:
            # 1. list_social_post_results
            items = client.list_social_post_results(post_id="spt_100", social_account_id="spc_yt_01", platform="youtube")
            self.assertEqual(len(items), 2)
            mock_req.assert_called_once_with(
                "GET",
                "/social-post-results",
                params={"post_id": "spt_100", "social_account_id": "spc_yt_01", "platform": "youtube"},
            )

            # 2. get_post_result_for_account seleciona a conta correta
            acc_result = client.get_post_result_for_account("spt_100", social_account_id="spc_yt_01")
            self.assertIsNotNone(acc_result)
            self.assertEqual(acc_result["id"], "spr_yt")
            self.assertEqual(acc_result["social_account_id"], "spc_yt_01")

    def test_idempotency_retry_recovers_post_result_without_upload(self):
        """IDEMPOTÊNCIA: primeira execução sofre timeout, segunda reutiliza post e recupera Post Result com 0 uploads."""
        client = PostForMeClient(api_key="mock-key")
        fake_account = {"id": "spc_yt_01", "platform": "youtube", "user_id": CHANNEL_DEFAULT_YT_ID, "status": "connected"}

        post_store = {}

        def mock_get_by_external_id(ext_id):
            return post_store.get(ext_id)

        def mock_create_post(**kwargs):
            p = {
                "id": "spt_retry_flow_101",
                "external_id": kwargs["external_id"],
                "status": "processing",
            }
            post_store[kwargs["external_id"]] = p
            return p

        # === 1ª EXECUÇÃO ===
        mock_create_upload = MagicMock(return_value=("https://upload.url", "https://media.url"))
        mock_put = MagicMock()
        mock_poll_1 = MagicMock(side_effect=PostForMeTimeoutError("timeout: Post for Me post spt_retry_flow_101 still processing after 120s"))

        with (
            patch.object(client, "resolve_youtube_account", return_value=fake_account),
            patch.object(client, "get_social_post_by_external_id", side_effect=mock_get_by_external_id),
            patch.object(client, "create_media_upload_url", mock_create_upload),
            patch.object(client, "upload_media_binary", mock_put),
            patch.object(client, "create_social_post", side_effect=mock_create_post),
            patch.object(client, "poll_social_post", mock_poll_1),
        ):
            res1 = client.publish_video(
                video_path=self.video_file,
                title="Shorts Idempotency",
                caption="Caption",
                channel_id="channel-default-youtube",
                task_id="task-retry-idem-01",
            )
            self.assertFalse(res1["success"])
            self.assertEqual(res1["error_code"], "POLLING_TIMEOUT")
            self.assertEqual(mock_create_upload.call_count, 1)
            self.assertEqual(mock_put.call_count, 1)

        # Post ficou persistido no mock server
        self.assertIn("video-factory:task-retry-idem-01:youtube:channel-default-youtube", post_store)

        # === 2ª EXECUÇÃO (Retry do Scheduler) ===
        mock_create_upload_2 = MagicMock()
        mock_put_2 = MagicMock()
        mock_create_post_2 = MagicMock()
        mock_poll_2 = MagicMock(return_value={"id": "spt_retry_flow_101", "status": "processed"})
        mock_get_result_2 = MagicMock(return_value={
            "id": "spr_idem_99",
            "post_id": "spt_retry_flow_101",
            "social_account_id": "spc_yt_01",
            "success": True,
            "platform_data": {
                "id": "YT_RECOVERED_VID_77",
                "url": "https://www.youtube.com/watch?v=YT_RECOVERED_VID_77",
            },
        })

        with (
            patch.object(client, "resolve_youtube_account", return_value=fake_account),
            patch.object(client, "get_social_post_by_external_id", side_effect=mock_get_by_external_id),
            patch.object(client, "create_media_upload_url", mock_create_upload_2),
            patch.object(client, "upload_media_binary", mock_put_2),
            patch.object(client, "create_social_post", mock_create_post_2),
            patch.object(client, "poll_social_post", mock_poll_2),
            patch.object(client, "get_post_result_for_account", mock_get_result_2),
        ):
            res2 = client.publish_video(
                video_path=self.video_file,
                title="Shorts Idempotency",
                caption="Caption",
                channel_id="channel-default-youtube",
                task_id="task-retry-idem-01",
            )
            # Verificações estritas:
            self.assertTrue(res2["success"])
            self.assertEqual(res2["request_id"], "spt_retry_flow_101")
            self.assertEqual(res2["external_id"], "YT_RECOVERED_VID_77")
            self.assertEqual(res2["external_url"], "https://www.youtube.com/watch?v=YT_RECOVERED_VID_77")

            # ZERO create-upload-url, ZERO PUT, ZERO novo social-post
            mock_create_upload_2.assert_not_called()
            mock_put_2.assert_not_called()
            mock_create_post_2.assert_not_called()

            # Poll e recuperação de resultado executados com sucesso
            mock_poll_2.assert_called_once_with("spt_retry_flow_101", timeout_sec=120, poll_interval_sec=2.0)
            mock_get_result_2.assert_called_once_with(post_id="spt_retry_flow_101", social_account_id="spc_yt_01")

    def test_made_for_kids_true_propagated(self):
        """GAP 3: made_for_kids=True é propagado para create_social_post e platform_configurations.youtube."""
        client = PostForMeClient(api_key="mock-key")

        # 1. create_social_post envia made_for_kids=True no payload JSON
        with patch.object(client, "_request", return_value={"data": {"id": "spt_kids_true"}}) as mock_req:
            client.create_social_post(
                caption="Kids Caption",
                social_account_id="spc_1",
                media_url="https://media.url",
                title="Kids Title",
                privacy_status="public",
                external_id="ext-kids-1",
                made_for_kids=True,
            )
            mock_req.assert_called_once()
            call_kwargs = mock_req.call_args.kwargs
            json_payload = call_kwargs["json_data"]
            self.assertIn("platform_configurations", json_payload)
            self.assertIn("youtube", json_payload["platform_configurations"])
            yt_cfg = json_payload["platform_configurations"]["youtube"]
            self.assertIs(yt_cfg["made_for_kids"], True)

        # 2. publish_video passa made_for_kids=True para create_social_post
        fake_account = {"id": "spc_yt_01", "platform": "youtube", "user_id": CHANNEL_DEFAULT_YT_ID, "status": "connected"}
        with (
            patch.object(client, "resolve_youtube_account", return_value=fake_account),
            patch.object(client, "get_social_post_by_external_id", return_value=None),
            patch.object(client, "create_media_upload_url", return_value=("https://up", "https://media")),
            patch.object(client, "upload_media_binary"),
            patch.object(client, "create_social_post", return_value={"id": "spt_kids_true"}) as mock_create,
            patch.object(client, "poll_social_post", return_value={"id": "spt_kids_true", "status": "processed"}),
            patch.object(client, "get_post_result_for_account", return_value={
                "id": "spr_kids",
                "social_account_id": "spc_yt_01",
                "success": True,
                "platform_data": {"id": "YT_KIDS_TRUE"},
            }),
        ):
            res = client.publish_video(
                video_path=self.video_file,
                title="Kids Title",
                caption="Caption",
                channel_id="channel-default-youtube",
                task_id="task-kids-t",
                made_for_kids=True,
            )
            self.assertTrue(res["success"])
            mock_create.assert_called_once()
            self.assertIs(mock_create.call_args.kwargs["made_for_kids"], True)

    def test_made_for_kids_false_propagated(self):
        """GAP 3: made_for_kids=False é propagado para create_social_post e platform_configurations.youtube."""
        client = PostForMeClient(api_key="mock-key")

        # 1. create_social_post envia made_for_kids=False no payload JSON
        with patch.object(client, "_request", return_value={"data": {"id": "spt_kids_false"}}) as mock_req:
            client.create_social_post(
                caption="Not Kids Caption",
                social_account_id="spc_1",
                media_url="https://media.url",
                title="Not Kids Title",
                privacy_status="public",
                external_id="ext-kids-0",
                made_for_kids=False,
            )
            mock_req.assert_called_once()
            call_kwargs = mock_req.call_args.kwargs
            json_payload = call_kwargs["json_data"]
            self.assertIn("platform_configurations", json_payload)
            self.assertIn("youtube", json_payload["platform_configurations"])
            yt_cfg = json_payload["platform_configurations"]["youtube"]
            self.assertIs(yt_cfg["made_for_kids"], False)

        # 2. publish_video passa made_for_kids=False para create_social_post
        fake_account = {"id": "spc_yt_01", "platform": "youtube", "user_id": CHANNEL_DEFAULT_YT_ID, "status": "connected"}
        with (
            patch.object(client, "resolve_youtube_account", return_value=fake_account),
            patch.object(client, "get_social_post_by_external_id", return_value=None),
            patch.object(client, "create_media_upload_url", return_value=("https://up", "https://media")),
            patch.object(client, "upload_media_binary"),
            patch.object(client, "create_social_post", return_value={"id": "spt_kids_false"}) as mock_create,
            patch.object(client, "poll_social_post", return_value={"id": "spt_kids_false", "status": "processed"}),
            patch.object(client, "get_post_result_for_account", return_value={
                "id": "spr_nokids",
                "social_account_id": "spc_yt_01",
                "success": True,
                "platform_data": {"id": "YT_KIDS_FALSE"},
            }),
        ):
            res = client.publish_video(
                video_path=self.video_file,
                title="Not Kids Title",
                caption="Caption",
                channel_id="channel-default-youtube",
                task_id="task-kids-f",
                made_for_kids=False,
            )
            self.assertTrue(res["success"])
            mock_create.assert_called_once()
            self.assertIs(mock_create.call_args.kwargs["made_for_kids"], False)

    def test_processing_timeout_produces_transient_error(self):
        """17. processing -> timeout produz erro transient."""
        client = PostForMeClient(api_key="mock-key")
        fake_account = {"id": "spc_01", "platform": "youtube", "user_id": CHANNEL_DEFAULT_YT_ID, "status": "connected"}

        with (
            patch.object(client, "resolve_youtube_account", return_value=fake_account),
            patch.object(client, "get_social_post_by_external_id", return_value=None),
            patch.object(client, "create_media_upload_url", return_value=("https://up", "https://media")),
            patch.object(client, "upload_media_binary"),
            patch.object(client, "create_social_post", return_value={"id": "spt_timeout_post"}),
            patch.object(client, "poll_social_post", side_effect=PostForMeTimeoutError("timeout: Post for Me post spt_timeout_post still processing after 120s")),
        ):
            res = client.publish_video(
                video_path=self.video_file,
                title="Title",
                caption="Caption",
                channel_id="channel-default-youtube",
                task_id="task-timeout-01",
            )
            self.assertFalse(res["success"])
            self.assertEqual(res["error_code"], "POLLING_TIMEOUT")
            # Verifica que a mensagem contém "timeout" para compatibilidade com scheduler.classify_error
            self.assertIn("timeout", res["error"].lower())

            # Verifica classificação no scheduler
            from app.services import scheduler
            self.assertEqual(scheduler.classify_error(res["error"]), "transient")

    def test_result_failure_produces_correct_error(self):
        """18. result failure produz erro correto."""
        client = PostForMeClient(api_key="mock-key")
        fake_account = {"id": "spc_01", "platform": "youtube", "user_id": CHANNEL_DEFAULT_YT_ID, "status": "connected"}
        failed_post = {
            "id": "spt_fail_01",
            "status": "failed",
        }
        with (
            patch.object(client, "resolve_youtube_account", return_value=fake_account),
            patch.object(client, "get_social_post_by_external_id", return_value=None),
            patch.object(client, "create_media_upload_url", return_value=("https://up", "https://media")),
            patch.object(client, "upload_media_binary"),
            patch.object(client, "create_social_post", return_value={"id": "spt_fail_01"}),
            patch.object(client, "poll_social_post", return_value=failed_post),
            patch.object(client, "get_post_result_for_account", return_value={
                "id": "spr_fail_01",
                "social_account_id": "spc_01",
                "success": False,
                "error": "YouTube quota exceeded for channel",
            }),
        ):
            res = client.publish_video(
                video_path=self.video_file,
                title="Title",
                caption="Caption",
                channel_id="channel-default-youtube",
                task_id="task-fail-01",
            )
            self.assertFalse(res["success"])
            self.assertEqual(res["error_code"], "POST_RESULT_FAILED")
            self.assertIn("YouTube quota exceeded", res["error"])

    def test_youtube_video_id_extraction_patterns(self):
        """19. YouTube video ID extraído da URL/platform_data quando necessário."""
        # 1. Native ID in platform_data
        d1 = {"platform_data": {"id": "vid_abc_123"}}
        self.assertEqual(extract_youtube_video_id(d1), "vid_abc_123")

        # 2. Watch URL
        d2 = {"platform_data": {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}}
        self.assertEqual(extract_youtube_video_id(d2), "dQw4w9WgXcQ")

        # 3. Youtu.be short URL
        d3 = {"url": "https://youtu.be/dQw4w9WgXcQ"}
        self.assertEqual(extract_youtube_video_id(d3), "dQw4w9WgXcQ")

        # 4. Shorts URL
        d4 = "https://www.youtube.com/shorts/ShortVideo123"
        self.assertEqual(extract_youtube_video_id(d4), "ShortVideo123")

        # 5. Post for Me internal IDs are REJECTED as YouTube Video IDs
        d5 = {"platform_data": {"id": "spt_fake_id", "url": "https://youtu.be/RealId456"}}
        self.assertEqual(extract_youtube_video_id(d5), "RealId456")

    def test_missing_video_id_does_not_fail_publication(self):
        """20. Publicação confirmada mas sem video ID nativo não cria duplicata e retorna com aviso."""
        post = {
            "id": "spt_succ_no_vid",
            "status": "completed",
            "results": [{
                "social_account_id": "spc_01",
                "success": True,
                "url": "https://unknown-link.example.com/item/123",
            }],
        }
        res_info = extract_post_result(post, target_account_id="spc_01")
        self.assertTrue(res_info["success"])
        self.assertIsNone(res_info["youtube_video_id"])

    def test_secrets_never_appear_in_sanitized_output(self):
        """21. API key nunca aparece em erro/log/resultado."""
        secret_key = "pfm_live_sec_999988887777"
        raw_msg = f"Failed to call https://api.postforme.dev with Bearer {secret_key} and key={secret_key}"
        sanitized = sanitize_secrets(raw_msg, api_key=secret_key)

        self.assertNotIn(secret_key, sanitized)
        self.assertIn("[REDACTED_API_KEY]", sanitized)
        self.assertIn("[REDACTED_TOKEN]", sanitized)


    def test_create_upload_url_sends_no_body(self):
        """1. POST /v1/media/create-upload-url é enviado sem request body."""
        client = PostForMeClient(api_key="mock-key")
        fake_resp = {
            "data": {
                "upload_url": "https://s3.amazonaws.com/presigned-upload",
                "media_url": "https://api.postforme.dev/v1/media/med_123",
            }
        }
        with patch.object(client, "_request", return_value=fake_resp) as mock_req:
            up_url, med_url = client.create_media_upload_url()
            self.assertEqual(up_url, "https://s3.amazonaws.com/presigned-upload")
            self.assertEqual(med_url, "https://api.postforme.dev/v1/media/med_123")
            mock_req.assert_called_once_with("POST", "/media/create-upload-url")
            # Verifica que nenhum json_data foi passado
            self.assertIsNone(mock_req.call_args.kwargs.get("json_data"))

    def test_upload_media_binary_uses_video_mp4_content_type(self):
        """1. PUT para a signed URL utiliza Content-Type: video/mp4."""
        client = PostForMeClient(api_key="mock-key")
        with patch("requests.put") as mock_put:
            mock_resp = MagicMock()
            mock_resp.raise_for_status.return_value = None
            mock_put.return_value = mock_resp

            client.upload_media_binary("https://signed-url.example/upload", self.video_file)

            mock_put.assert_called_once()
            called_headers = mock_put.call_args.kwargs.get("headers")
            self.assertIsNotNone(called_headers)
            self.assertEqual(called_headers.get("Content-Type"), "video/mp4")

    def test_tags_and_synthetic_media_propagated_to_platform_configurations(self):
        """2. tags, contains_synthetic_media=True e description são propagados no platform_configurations.youtube."""
        client = PostForMeClient(api_key="mock-key")

        with patch.object(client, "_request", return_value={"data": {"id": "spt_meta_ok"}}) as mock_req:
            client.create_social_post(
                caption="Legenda do Vídeo #shorts",
                social_account_id="spc_01",
                media_url="https://media.url/v.mp4",
                title="Título do Vídeo",
                privacy_status="public",
                external_id="ext-meta-01",
                made_for_kids=False,
                tags=["#shorts", "#tecnologia", "#ia"],
                contains_synthetic_media=True,
            )

            mock_req.assert_called_once()
            json_payload = mock_req.call_args.kwargs.get("json_data")
            self.assertIsNotNone(json_payload)
            yt_cfg = json_payload["platform_configurations"]["youtube"]
            self.assertEqual(yt_cfg["title"], "Título do Vídeo")
            self.assertEqual(yt_cfg["description"], "Legenda do Vídeo #shorts")
            self.assertEqual(yt_cfg["tags"], ["#shorts", "#tecnologia", "#ia"])
            self.assertIs(yt_cfg["contains_synthetic_media"], True)
            self.assertIs(yt_cfg["made_for_kids"], False)
            self.assertEqual(yt_cfg["privacy_status"], "public")

    def test_publish_video_propagates_tags_and_synthetic_media(self):
        """2. publish_video propaga tags e contains_synthetic_media para create_social_post."""
        client = PostForMeClient(api_key="mock-key")
        fake_account = {"id": "spc_yt_01", "platform": "youtube", "user_id": CHANNEL_DEFAULT_YT_ID, "status": "connected"}

        with (
            patch.object(client, "resolve_youtube_account", return_value=fake_account),
            patch.object(client, "get_social_post_by_external_id", return_value=None),
            patch.object(client, "create_media_upload_url", return_value=("https://up", "https://media")),
            patch.object(client, "upload_media_binary"),
            patch.object(client, "create_social_post", return_value={"id": "spt_meta_ok"}) as mock_create,
            patch.object(client, "poll_social_post", return_value={"id": "spt_meta_ok", "status": "processed"}),
            patch.object(client, "get_post_result_for_account", return_value={
                "id": "spr_meta",
                "post_id": "spt_meta_ok",
                "social_account_id": "spc_yt_01",
                "success": True,
                "platform_data": {"id": "YT_META_123"},
            }),
        ):
            res = client.publish_video(
                video_path=self.video_file,
                title="Title",
                caption="Caption",
                channel_id="channel-default-youtube",
                task_id="task-meta-01",
                tags=["#viral", "#curiosidades"],
                contains_synthetic_media=True,
                made_for_kids=False,
            )
            self.assertTrue(res["success"])
            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args.kwargs
            self.assertEqual(call_kwargs["tags"], ["#viral", "#curiosidades"])
            self.assertIs(call_kwargs["contains_synthetic_media"], True)
            self.assertIs(call_kwargs["made_for_kids"], False)

    def test_post_result_wrong_account_rejected(self):
        """3A. Resultado de outra conta é rejeitado (retorna None)."""
        client = PostForMeClient(api_key="mock-key")
        results = [
            {
                "id": "spr_other",
                "post_id": "spt_100",
                "social_account_id": "spc_wrong_account",
                "success": True,
            }
        ]
        with patch.object(client, "list_social_post_results", return_value=results):
            res = client.get_post_result_for_account(
                post_id="spt_100",
                social_account_id="spc_expected_account",
            )
            self.assertIsNone(res)

    def test_post_result_wrong_post_id_rejected(self):
        """3B. Resultado da conta correta mas outro post_id é rejeitado (retorna None)."""
        client = PostForMeClient(api_key="mock-key")
        results = [
            {
                "id": "spr_wrong_post",
                "post_id": "spt_other_post_999",
                "social_account_id": "spc_expected_account",
                "success": True,
            }
        ]
        with patch.object(client, "list_social_post_results", return_value=results):
            res = client.get_post_result_for_account(
                post_id="spt_expected_100",
                social_account_id="spc_expected_account",
            )
            self.assertIsNone(res)

    def test_post_result_correct_post_and_account_accepted(self):
        """3C. post_id e social_account_id estritamente corretos é aceito."""
        client = PostForMeClient(api_key="mock-key")
        matching = {
            "id": "spr_correct",
            "post_id": "spt_100",
            "social_account_id": "spc_yt_01",
            "success": True,
            "platform_data": {"id": "YT_OK"},
        }
        with patch.object(client, "list_social_post_results", return_value=[matching]):
            res = client.get_post_result_for_account(
                post_id="spt_100",
                social_account_id="spc_yt_01",
            )
            self.assertIsNotNone(res)
            self.assertEqual(res["id"], "spr_correct")

    def test_post_result_ambiguous_matches_fail_closed(self):
        """3D. Múltiplos matches levantam PostForMeAmbiguousResultError (Fail Closed)."""
        client = PostForMeClient(api_key="mock-key")
        ambiguous_results = [
            {
                "id": "spr_match_1",
                "post_id": "spt_100",
                "social_account_id": "spc_yt_01",
                "success": True,
            },
            {
                "id": "spr_match_2",
                "post_id": "spt_100",
                "social_account_id": "spc_yt_01",
                "success": True,
            },
        ]
        with patch.object(client, "list_social_post_results", return_value=ambiguous_results):
            with self.assertRaises(PostForMeAmbiguousResultError):
                client.get_post_result_for_account(
                    post_id="spt_100",
                    social_account_id="spc_yt_01",
                )

    def test_list_social_posts_by_external_id_strict_equality(self):
        """Passo 2: list_social_posts_by_external_id filtra estritamente por external_id exato."""
        client = PostForMeClient(api_key="mock-key")
        target_ext_id = "video-factory:task-123:youtube:channel-default-youtube"
        raw_items = [
            {"id": "sp_1", "external_id": target_ext_id},
            {"id": "sp_2", "external_id": "video-factory:task-123:youtube:channel-default-youtube:retry:1"},
            {"id": "sp_3", "external_id": "other-external-id"},
            {"id": "sp_4", "external_id": target_ext_id},
        ]
        with patch.object(client, "_request", return_value={"data": raw_items}) as mock_req:
            res = client.list_social_posts_by_external_id(target_ext_id)
            mock_req.assert_called_once_with("GET", "/social-posts", params={"external_id": target_ext_id})
            self.assertEqual(len(res), 2)
            self.assertEqual([p["id"] for p in res], ["sp_1", "sp_4"])

    def test_publish_no_previous_post_uploads_and_creates_once(self):
        """Passo 8.1: nenhum post anterior -> upload + create exatamente uma vez."""
        client = PostForMeClient(api_key="mock-key")
        fake_account = {"id": "spc_yt_01", "platform": "youtube", "user_id": CHANNEL_DEFAULT_YT_ID, "status": "connected"}

        with (
            patch.object(client, "resolve_youtube_account", return_value=fake_account),
            patch.object(client, "list_social_posts_by_external_id", return_value=[]),
            patch.object(client, "create_media_upload_url", return_value=("https://up", "https://media")) as mock_up,
            patch.object(client, "upload_media_binary") as mock_bin,
            patch.object(client, "create_social_post", return_value={"id": "sp_fresh_01"}) as mock_create,
            patch.object(client, "poll_social_post", return_value={"id": "sp_fresh_01", "status": "processed"}) as mock_poll,
            patch.object(client, "get_post_result_for_account", return_value={
                "id": "spr_fresh_01",
                "post_id": "sp_fresh_01",
                "social_account_id": "spc_yt_01",
                "success": True,
                "platform_data": {"id": "YT_FRESH_VID_01"},
            }),
        ):
            res = client.publish_video(
                video_path=self.video_file,
                title="Fresh Video",
                caption="Fresh Caption",
                channel_id="channel-default-youtube",
                task_id="task-fresh-01",
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["request_id"], "sp_fresh_01")
            self.assertEqual(res["external_id"], "YT_FRESH_VID_01")
            mock_up.assert_called_once()
            mock_bin.assert_called_once()
            mock_create.assert_called_once()
            mock_poll.assert_called_once()

    def test_publish_existing_processing_post_resumes_polling_without_upload(self):
        """Passo 8.2: post existente processing -> NÃO upload, NÃO create, continua polling do existente."""
        client = PostForMeClient(api_key="mock-key")
        fake_account = {"id": "spc_yt_01", "platform": "youtube", "user_id": CHANNEL_DEFAULT_YT_ID, "status": "connected"}

        existing_active_post = {
            "id": "sp_active_01",
            "external_id": "video-factory:task-active-01:youtube:channel-default-youtube",
            "status": "processing",
            "social_accounts": ["spc_yt_01"],
        }

        with (
            patch.object(client, "resolve_youtube_account", return_value=fake_account),
            patch.object(client, "list_social_posts_by_external_id", return_value=[existing_active_post]),
            patch.object(client, "create_media_upload_url") as mock_up,
            patch.object(client, "upload_media_binary") as mock_bin,
            patch.object(client, "create_social_post") as mock_create,
            patch.object(client, "poll_social_post", return_value={"id": "sp_active_01", "status": "processed"}) as mock_poll,
            patch.object(client, "get_post_result_for_account", return_value={
                "id": "spr_act_01",
                "post_id": "sp_active_01",
                "social_account_id": "spc_yt_01",
                "success": True,
                "platform_data": {"id": "YT_ACTIVE_RESOLVED"},
            }),
        ):
            res = client.publish_video(
                video_path=self.video_file,
                title="Active Video",
                caption="Active Caption",
                channel_id="channel-default-youtube",
                task_id="task-active-01",
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["request_id"], "sp_active_01")
            self.assertEqual(res["external_id"], "YT_ACTIVE_RESOLVED")
            # NÃO faz upload novo, NÃO cria social post
            mock_up.assert_not_called()
            mock_bin.assert_not_called()
            mock_create.assert_not_called()
            # Polling retomado no post existente
            mock_poll.assert_called_once_with("sp_active_01", timeout_sec=120, poll_interval_sec=2.0)

    def test_publish_existing_success_post_returns_immediately_without_upload(self):
        """Passo 8.3: post existente success -> NÃO upload, NÃO create, retorna sucesso existente."""
        client = PostForMeClient(api_key="mock-key")
        fake_account = {"id": "spc_yt_01", "platform": "youtube", "user_id": CHANNEL_DEFAULT_YT_ID, "status": "connected"}

        existing_success_post = {
            "id": "sp_success_01",
            "external_id": "video-factory:task-succ-01:youtube:channel-default-youtube",
            "status": "processed",
            "social_accounts": ["spc_yt_01"],
            "platform_configurations": {"youtube": {"privacy_status": "public"}},
        }
        success_result = {
            "id": "spr_succ_01",
            "post_id": "sp_success_01",
            "social_account_id": "spc_yt_01",
            "success": True,
            "platform_data": {"id": "YT_EXISTING_SUCC_VID", "url": "https://www.youtube.com/watch?v=YT_EXISTING_SUCC_VID"},
        }

        with (
            patch.object(client, "resolve_youtube_account", return_value=fake_account),
            patch.object(client, "list_social_posts_by_external_id", return_value=[existing_success_post]),
            patch.object(client, "get_post_result_for_account", return_value=success_result),
            patch.object(client, "create_media_upload_url") as mock_up,
            patch.object(client, "upload_media_binary") as mock_bin,
            patch.object(client, "create_social_post") as mock_create,
            patch.object(client, "poll_social_post") as mock_poll,
        ):
            res = client.publish_video(
                video_path=self.video_file,
                title="Succ Video",
                caption="Succ Caption",
                channel_id="channel-default-youtube",
                task_id="task-succ-01",
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["request_id"], "sp_success_01")
            self.assertEqual(res["external_id"], "YT_EXISTING_SUCC_VID")
            self.assertEqual(res["external_url"], "https://www.youtube.com/watch?v=YT_EXISTING_SUCC_VID")
            # ZERO upload, ZERO create, ZERO poll
            mock_up.assert_not_called()
            mock_bin.assert_not_called()
            mock_create.assert_not_called()
            mock_poll.assert_not_called()

    def test_publish_terminal_failed_post_allows_new_attempt(self):
        """Passo 8.4: post terminal failed -> nova tentativa permitida."""
        client = PostForMeClient(api_key="mock-key")
        fake_account = {"id": "spc_yt_01", "platform": "youtube", "user_id": CHANNEL_DEFAULT_YT_ID, "status": "connected"}

        old_failed_post = {
            "id": "sp_failed_old",
            "external_id": "video-factory:task-retry-01:youtube:channel-default-youtube",
            "status": "processed",
            "social_accounts": ["spc_yt_01"],
        }
        failed_result = {
            "id": "spr_failed_old",
            "post_id": "sp_failed_old",
            "social_account_id": "spc_yt_01",
            "success": False,
            "error": "429 Too Many Requests RESOURCE_EXHAUSTED Quota exceeded for quota metric 'Video Uploads' defaultVideoInsertPerDayPerProject",
        }

        # Simula que a busca de posts antes do upload retorna apenas o post falho
        def mock_list_posts(ext_id):
            return [old_failed_post]

        def mock_get_result(post_id, social_account_id):
            if post_id == "sp_failed_old":
                return failed_result
            if post_id == "sp_new_attempt_02":
                return {
                    "id": "spr_new_attempt_02",
                    "post_id": "sp_new_attempt_02",
                    "social_account_id": "spc_yt_01",
                    "success": True,
                    "platform_data": {"id": "YT_NEW_ATTEMPT_SUCCESS"},
                }
            return None

        with (
            patch.object(client, "resolve_youtube_account", return_value=fake_account),
            patch.object(client, "list_social_posts_by_external_id", side_effect=mock_list_posts),
            patch.object(client, "get_post_result_for_account", side_effect=mock_get_result),
            patch.object(client, "create_media_upload_url", return_value=("https://up2", "https://media2")) as mock_up,
            patch.object(client, "upload_media_binary") as mock_bin,
            patch.object(client, "create_social_post", return_value={"id": "sp_new_attempt_02"}) as mock_create,
            patch.object(client, "poll_social_post", return_value={"id": "sp_new_attempt_02", "status": "processed"}) as mock_poll,
        ):
            res = client.publish_video(
                video_path=self.video_file,
                title="Retry Title",
                caption="Retry Caption",
                channel_id="channel-default-youtube",
                task_id="task-retry-01",
            )
            # Nova tentativa foi criada e teve sucesso
            self.assertTrue(res["success"])
            self.assertEqual(res["request_id"], "sp_new_attempt_02")
            self.assertEqual(res["external_id"], "YT_NEW_ATTEMPT_SUCCESS")
            mock_up.assert_called_once()
            mock_bin.assert_called_once()
            mock_create.assert_called_once()
            mock_poll.assert_called_once_with("sp_new_attempt_02", timeout_sec=120, poll_interval_sec=2.0)

    def test_publish_lineage_old_failed_and_new_success_returns_success_without_third_attempt(self):
        """Passo 8.5: histórico: failed antigo + success novo -> chamada seguinte retorna success sem criar 3ª tentativa."""
        client = PostForMeClient(api_key="mock-key")
        fake_account = {"id": "spc_yt_01", "platform": "youtube", "user_id": CHANNEL_DEFAULT_YT_ID, "status": "connected"}

        post_failed_old = {
            "id": "sp_lineage_fail_01",
            "external_id": "video-factory:task-lineage-01:youtube:channel-default-youtube",
            "status": "processed",
            "social_accounts": ["spc_yt_01"],
        }
        post_success_new = {
            "id": "sp_lineage_succ_02",
            "external_id": "video-factory:task-lineage-01:youtube:channel-default-youtube",
            "status": "processed",
            "social_accounts": ["spc_yt_01"],
            "platform_configurations": {"youtube": {"privacy_status": "public"}},
        }

        def mock_get_result(post_id, social_account_id):
            if post_id == "sp_lineage_fail_01":
                return {
                    "id": "spr_fail",
                    "post_id": "sp_lineage_fail_01",
                    "social_account_id": "spc_yt_01",
                    "success": False,
                }
            if post_id == "sp_lineage_succ_02":
                return {
                    "id": "spr_succ",
                    "post_id": "sp_lineage_succ_02",
                    "social_account_id": "spc_yt_01",
                    "success": True,
                    "platform_data": {"id": "YT_LINEAGE_WON"},
                }
            return None

        with (
            patch.object(client, "resolve_youtube_account", return_value=fake_account),
            patch.object(client, "list_social_posts_by_external_id", return_value=[post_failed_old, post_success_new]),
            patch.object(client, "get_post_result_for_account", side_effect=mock_get_result),
            patch.object(client, "create_media_upload_url") as mock_up,
            patch.object(client, "upload_media_binary") as mock_bin,
            patch.object(client, "create_social_post") as mock_create,
            patch.object(client, "poll_social_post") as mock_poll,
        ):
            res = client.publish_video(
                video_path=self.video_file,
                title="Lineage Title",
                caption="Lineage Caption",
                channel_id="channel-default-youtube",
                task_id="task-lineage-01",
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["request_id"], "sp_lineage_succ_02")
            self.assertEqual(res["external_id"], "YT_LINEAGE_WON")
            # NENHUMA 3ª tentativa criada
            mock_up.assert_not_called()
            mock_bin.assert_not_called()
            mock_create.assert_not_called()
            mock_poll.assert_not_called()

    def test_publish_multiple_success_fails_closed(self):
        """Passo 8.6: múltiplos success -> fail closed."""
        client = PostForMeClient(api_key="mock-key")
        fake_account = {"id": "spc_yt_01", "platform": "youtube", "user_id": CHANNEL_DEFAULT_YT_ID, "status": "connected"}

        post_succ_1 = {
            "id": "sp_dup_1",
            "external_id": "video-factory:task-dup-01:youtube:channel-default-youtube",
            "status": "processed",
            "social_accounts": ["spc_yt_01"],
        }
        post_succ_2 = {
            "id": "sp_dup_2",
            "external_id": "video-factory:task-dup-01:youtube:channel-default-youtube",
            "status": "processed",
            "social_accounts": ["spc_yt_01"],
        }

        def mock_get_result(post_id, social_account_id):
            return {
                "id": f"spr_{post_id}",
                "post_id": post_id,
                "social_account_id": "spc_yt_01",
                "success": True,
                "platform_data": {"id": f"YT_{post_id}"},
            }

        with (
            patch.object(client, "resolve_youtube_account", return_value=fake_account),
            patch.object(client, "list_social_posts_by_external_id", return_value=[post_succ_1, post_succ_2]),
            patch.object(client, "get_post_result_for_account", side_effect=mock_get_result),
            patch.object(client, "create_media_upload_url") as mock_up,
            patch.object(client, "create_social_post") as mock_create,
        ):
            res = client.publish_video(
                video_path=self.video_file,
                title="Dup Title",
                caption="Dup Caption",
                channel_id="channel-default-youtube",
                task_id="task-dup-01",
            )
            self.assertFalse(res["success"])
            self.assertEqual(res["error_code"], "AMBIGUOUS_SUCCESS")
            self.assertIn("Múltiplos sucessos", res["error"])
            mock_up.assert_not_called()
            mock_create.assert_not_called()

    def test_publish_multiple_active_fails_closed(self):
        """Passo 8.7: múltiplos active -> fail closed."""
        client = PostForMeClient(api_key="mock-key")
        fake_account = {"id": "spc_yt_01", "platform": "youtube", "user_id": CHANNEL_DEFAULT_YT_ID, "status": "connected"}

        post_active_1 = {
            "id": "sp_act_1",
            "external_id": "video-factory:task-act-02:youtube:channel-default-youtube",
            "status": "processing",
            "social_accounts": ["spc_yt_01"],
        }
        post_active_2 = {
            "id": "sp_act_2",
            "external_id": "video-factory:task-act-02:youtube:channel-default-youtube",
            "status": "pending",
            "social_accounts": ["spc_yt_01"],
        }

        with (
            patch.object(client, "resolve_youtube_account", return_value=fake_account),
            patch.object(client, "list_social_posts_by_external_id", return_value=[post_active_1, post_active_2]),
            patch.object(client, "create_media_upload_url") as mock_up,
            patch.object(client, "create_social_post") as mock_create,
        ):
            res = client.publish_video(
                video_path=self.video_file,
                title="Act Title",
                caption="Act Caption",
                channel_id="channel-default-youtube",
                task_id="task-act-02",
            )
            self.assertFalse(res["success"])
            self.assertEqual(res["error_code"], "AMBIGUOUS_ACTIVE")
            self.assertIn("Múltiplas tentativas ativas", res["error"])
            mock_up.assert_not_called()
            mock_create.assert_not_called()

    def test_publish_inconsistent_post_fails_closed_without_upload(self):
        """Passo 2E: post processed sem Post Result conclusivo -> INCONSISTENT -> FAIL CLOSED sem upload."""
        client = PostForMeClient(api_key="mock-key")
        fake_account = {"id": "spc_yt_01", "platform": "youtube", "user_id": CHANNEL_DEFAULT_YT_ID, "status": "connected"}

        inconclusive_post = {
            "id": "sp_inconclusive_01",
            "external_id": "video-factory:task-inconcl-01:youtube:channel-default-youtube",
            "status": "processed",  # processed sem Post Result retornado
            "social_accounts": ["spc_yt_01"],
        }

        with (
            patch.object(client, "resolve_youtube_account", return_value=fake_account),
            patch.object(client, "list_social_posts_by_external_id", return_value=[inconclusive_post]),
            patch.object(client, "get_post_result_for_account", return_value=None),  # Post Result ausente/inconclusivo
            patch.object(client, "create_media_upload_url") as mock_up,
            patch.object(client, "create_social_post") as mock_create,
        ):
            res = client.publish_video(
                video_path=self.video_file,
                title="Inconsistent Title",
                caption="Inconsistent Caption",
                channel_id="channel-default-youtube",
                task_id="task-inconcl-01",
            )
            # Fail closed estrito
            self.assertFalse(res["success"])
            self.assertEqual(res["error_code"], "AMBIGUOUS_POSTS")
            self.assertIn("inconsistente", res["error"].lower())
            # ZERO upload, ZERO create
            mock_up.assert_not_called()
            mock_create.assert_not_called()

    def test_list_social_posts_by_external_id_bounded_pagination(self):
        """Passo 3: list_social_posts_by_external_id executa paginação bounded se meta.next estiver presente."""
        client = PostForMeClient(api_key="mock-key")
        target_ext_id = "video-factory:task-page-01:youtube:channel-default-youtube"

        page_1 = {
            "data": [{"id": f"sp_p1_{i}", "external_id": target_ext_id} for i in range(50)],
            "meta": {"total": 60, "offset": 0, "limit": 50, "next": "https://api.postforme.dev/v1/social-posts?offset=50&limit=50"},
        }
        page_2 = {
            "data": [{"id": f"sp_p2_{i}", "external_id": target_ext_id} for i in range(10)],
            "meta": {"total": 60, "offset": 50, "limit": 50, "next": None},
        }

        def mock_request(method, path, params=None, **kwargs):
            if params and params.get("offset") == 50:
                return page_2
            return page_1

        with patch.object(client, "_request", side_effect=mock_request) as mock_req:
            posts = client.list_social_posts_by_external_id(target_ext_id)
            self.assertEqual(len(posts), 60)
            self.assertEqual(mock_req.call_count, 2)

    def test_publish_existing_success_preserves_real_privacy_even_if_call_requests_different(self):
        """GAP 1.1: existing success com privacy real = private; nova chamada pede public -> retorna private."""
        client = PostForMeClient(api_key="mock-key")
        fake_account = {"id": "spc_yt_01", "platform": "youtube", "user_id": CHANNEL_DEFAULT_YT_ID, "status": "connected"}

        existing_success_post = {
            "id": "sp_success_priv",
            "external_id": "video-factory:task-priv-01:youtube:channel-default-youtube",
            "status": "processed",
            "social_accounts": ["spc_yt_01"],
            "platform_configurations": {"youtube": {"privacy_status": "private"}},
        }
        success_result = {
            "id": "spr_succ_priv",
            "post_id": "sp_success_priv",
            "social_account_id": "spc_yt_01",
            "success": True,
            "platform_data": {"id": "YT_EXISTING_PRIV_VID", "url": "https://www.youtube.com/watch?v=YT_EXISTING_PRIV_VID"},
        }

        with (
            patch.object(client, "resolve_youtube_account", return_value=fake_account),
            patch.object(client, "list_social_posts_by_external_id", return_value=[existing_success_post]),
            patch.object(client, "get_post_result_for_account", return_value=success_result),
            patch.object(client, "create_media_upload_url") as mock_up,
            patch.object(client, "upload_media_binary") as mock_bin,
            patch.object(client, "create_social_post") as mock_create,
            patch.object(client, "poll_social_post") as mock_poll,
        ):
            res = client.publish_video(
                video_path=self.video_file,
                title="Privacy Video",
                caption="Privacy Caption",
                channel_id="channel-default-youtube",
                task_id="task-priv-01",
                privacy_status="public",  # Chamada atual pede public
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["request_id"], "sp_success_priv")
            self.assertEqual(res["external_id"], "YT_EXISTING_PRIV_VID")
            self.assertEqual(res["external_url"], "https://www.youtube.com/watch?v=YT_EXISTING_PRIV_VID")
            self.assertEqual(res["privacy_status"], "private")  # Retorna a privacidade REAL do post existente
            mock_up.assert_not_called()
            mock_bin.assert_not_called()
            mock_create.assert_not_called()
            mock_poll.assert_not_called()

    def test_publish_existing_success_unknown_privacy_fails_closed(self):
        """GAP 1.2: existing success sem privacy comprovável -> FAIL CLOSED (EXISTING_SUCCESS_PRIVACY_UNKNOWN)."""
        client = PostForMeClient(api_key="mock-key")
        fake_account = {"id": "spc_yt_01", "platform": "youtube", "user_id": CHANNEL_DEFAULT_YT_ID, "status": "connected"}

        existing_success_post = {
            "id": "sp_success_unk",
            "external_id": "video-factory:task-unk-01:youtube:channel-default-youtube",
            "status": "processed",
            "social_accounts": ["spc_yt_01"],
            # Sem platform_configurations e sem privacy_status
        }
        success_result = {
            "id": "spr_succ_unk",
            "post_id": "sp_success_unk",
            "social_account_id": "spc_yt_01",
            "success": True,
            "platform_data": {"id": "YT_EXISTING_UNK_VID"},
            # Sem privacy_status
        }

        with (
            patch.object(client, "resolve_youtube_account", return_value=fake_account),
            patch.object(client, "list_social_posts_by_external_id", return_value=[existing_success_post]),
            patch.object(client, "get_post_result_for_account", return_value=success_result),
            patch.object(client, "create_media_upload_url") as mock_up,
            patch.object(client, "create_social_post") as mock_create,
        ):
            res = client.publish_video(
                video_path=self.video_file,
                title="Unknown Priv Video",
                caption="Caption",
                channel_id="channel-default-youtube",
                task_id="task-unk-01",
                privacy_status="public",
            )
            self.assertFalse(res["success"])
            self.assertEqual(res["error_code"], "EXISTING_SUCCESS_PRIVACY_UNKNOWN")
            self.assertEqual(res["request_id"], "sp_success_unk")
            self.assertEqual(res["external_id"], "YT_EXISTING_UNK_VID")
            self.assertIsNone(res["privacy_status"])
            mock_up.assert_not_called()
            mock_create.assert_not_called()

    def test_publish_zero_history_revalidation_finds_active_resumes_without_upload(self):
        """GAP 2.1: revalidação zero-history: primeira vazio, segunda encontra 1 active -> NÃO upload, retoma active."""
        client = PostForMeClient(api_key="mock-key")
        fake_account = {"id": "spc_yt_01", "platform": "youtube", "user_id": CHANNEL_DEFAULT_YT_ID, "status": "connected"}

        active_post = {
            "id": "sp_race_act_01",
            "external_id": "video-factory:task-zero-race:youtube:channel-default-youtube",
            "status": "processing",
            "social_accounts": ["spc_yt_01"],
        }

        call_count = 0
        def mock_list_posts(ext_id):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return []
            return [active_post]

        with (
            patch.object(client, "resolve_youtube_account", return_value=fake_account),
            patch.object(client, "list_social_posts_by_external_id", side_effect=mock_list_posts),
            patch.object(client, "create_media_upload_url") as mock_up,
            patch.object(client, "upload_media_binary") as mock_bin,
            patch.object(client, "create_social_post") as mock_create,
            patch.object(client, "poll_social_post", return_value={"id": "sp_race_act_01", "status": "processed"}) as mock_poll,
            patch.object(client, "get_post_result_for_account", return_value={
                "id": "spr_race_act_01",
                "post_id": "sp_race_act_01",
                "social_account_id": "spc_yt_01",
                "success": True,
                "platform_data": {"id": "YT_RACE_RESOLVED"},
            }),
        ):
            res = client.publish_video(
                video_path=self.video_file,
                title="Race Active Video",
                caption="Caption",
                channel_id="channel-default-youtube",
                task_id="task-zero-race",
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["request_id"], "sp_race_act_01")
            self.assertEqual(res["external_id"], "YT_RACE_RESOLVED")
            mock_up.assert_not_called()
            mock_bin.assert_not_called()
            mock_create.assert_not_called()
            mock_poll.assert_called_once_with("sp_race_act_01", timeout_sec=120, poll_interval_sec=2.0)

    def test_publish_zero_history_revalidation_finds_success_reuses_without_upload(self):
        """GAP 2.2: revalidação zero-history: primeira vazio, segunda encontra success -> reutiliza, NÃO upload."""
        client = PostForMeClient(api_key="mock-key")
        fake_account = {"id": "spc_yt_01", "platform": "youtube", "user_id": CHANNEL_DEFAULT_YT_ID, "status": "connected"}

        success_post = {
            "id": "sp_race_succ_01",
            "external_id": "video-factory:task-zero-succ:youtube:channel-default-youtube",
            "status": "processed",
            "social_accounts": ["spc_yt_01"],
            "platform_configurations": {"youtube": {"privacy_status": "public"}},
        }
        success_result = {
            "id": "spr_race_succ_01",
            "post_id": "sp_race_succ_01",
            "social_account_id": "spc_yt_01",
            "success": True,
            "platform_data": {"id": "YT_RACE_SUCC_VID"},
        }

        call_count = 0
        def mock_list_posts(ext_id):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return []
            return [success_post]

        with (
            patch.object(client, "resolve_youtube_account", return_value=fake_account),
            patch.object(client, "list_social_posts_by_external_id", side_effect=mock_list_posts),
            patch.object(client, "get_post_result_for_account", return_value=success_result),
            patch.object(client, "create_media_upload_url") as mock_up,
            patch.object(client, "upload_media_binary") as mock_bin,
            patch.object(client, "create_social_post") as mock_create,
            patch.object(client, "poll_social_post") as mock_poll,
        ):
            res = client.publish_video(
                video_path=self.video_file,
                title="Race Succ Video",
                caption="Caption",
                channel_id="channel-default-youtube",
                task_id="task-zero-succ",
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["request_id"], "sp_race_succ_01")
            self.assertEqual(res["external_id"], "YT_RACE_SUCC_VID")
            self.assertEqual(res["privacy_status"], "public")
            mock_up.assert_not_called()
            mock_bin.assert_not_called()
            mock_create.assert_not_called()
            mock_poll.assert_not_called()

    def test_publish_zero_history_revalidation_empty_creates_once(self):
        """GAP 2.3: revalidação zero-history: primeira vazio, segunda continua vazia -> 1 create_media, 1 upload, 1 create_post."""
        client = PostForMeClient(api_key="mock-key")
        fake_account = {"id": "spc_yt_01", "platform": "youtube", "user_id": CHANNEL_DEFAULT_YT_ID, "status": "connected"}

        call_count = 0
        def mock_list_posts(ext_id):
            nonlocal call_count
            call_count += 1
            return []

        with (
            patch.object(client, "resolve_youtube_account", return_value=fake_account),
            patch.object(client, "list_social_posts_by_external_id", side_effect=mock_list_posts),
            patch.object(client, "create_media_upload_url", return_value=("https://up", "https://media")) as mock_up,
            patch.object(client, "upload_media_binary") as mock_bin,
            patch.object(client, "create_social_post", return_value={"id": "sp_fresh_zero"}) as mock_create,
            patch.object(client, "poll_social_post", return_value={"id": "sp_fresh_zero", "status": "processed"}) as mock_poll,
            patch.object(client, "get_post_result_for_account", return_value={
                "id": "spr_fresh_zero",
                "post_id": "sp_fresh_zero",
                "social_account_id": "spc_yt_01",
                "success": True,
                "platform_data": {"id": "YT_FRESH_ZERO_VID"},
            }),
        ):
            res = client.publish_video(
                video_path=self.video_file,
                title="Fresh Video",
                caption="Caption",
                channel_id="channel-default-youtube",
                task_id="task-zero-clean",
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["request_id"], "sp_fresh_zero")
            self.assertEqual(res["external_id"], "YT_FRESH_ZERO_VID")
            self.assertEqual(call_count, 2)  # Primeira classificação + Revalidação pré-upload
            mock_up.assert_called_once()
            mock_bin.assert_called_once()
            mock_create.assert_called_once()
            mock_poll.assert_called_once()


if __name__ == "__main__":
    unittest.main()
