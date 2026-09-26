"""Testes direcionados do roteador YouTube Publisher (Fase V15-E.2).

Cobre:
- Default provider = upload_post
- Provider post_for_me selecionado via autopilot_settings
- Dispatching correto para Upload-Post e Post for Me
- publication_events recebe YouTube Video ID nativo, não Post for Me post ID
- Upload-Post existente continua funcionando
- TikTok inalterado
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.models import const
from app.services import (
    post_for_me,
    profile_manager,
    scheduler,
    state as sm,
    task as tm,
    upload_post,
    youtube_publisher,
)
from app.services.state import MemoryState
from app.utils import utils


class TestYouTubePublisherRouter(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_router.db")
        scheduler.init_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        profile_manager.ensure_default_profile(self.db_path)

        self.state = MemoryState()
        self.patcher_state = patch.object(tm.sm, "state", self.state)
        self.patcher_state.start()

        self.video_file = os.path.join(self.temp_dir.name, "final-1.mp4")
        with open(self.video_file, "wb") as f:
            f.write(b"\x00\x00\x00\x18ftypmp42" + b"X" * 1024)

    def tearDown(self):
        self.patcher_state.stop()
        self.temp_dir.cleanup()

    def test_default_provider_is_upload_post(self):
        """2. default provider = upload_post."""
        provider = youtube_publisher.get_youtube_publish_provider(db_path=self.db_path)
        self.assertEqual(provider, youtube_publisher.PROVIDER_UPLOAD_POST)
        self.assertEqual(provider, "upload_post")

    def test_provider_post_for_me_selected_correctly(self):
        """3. provider post_for_me selecionado corretamente."""
        youtube_publisher.set_youtube_publish_provider("post_for_me", db_path=self.db_path)
        provider = youtube_publisher.get_youtube_publish_provider(db_path=self.db_path)
        self.assertEqual(provider, "post_for_me")

        # Configuração inválida é rejeitada
        with self.assertRaises(ValueError):
            youtube_publisher.set_youtube_publish_provider("invalid_provider", db_path=self.db_path)

    def test_router_dispatches_to_upload_post_when_default(self):
        """Upload-Post é chamado quando provider é upload_post."""
        mock_upload_post_res = {
            "success": True,
            "request_id": "up_req_123",
            "results": {
                "youtube": {
                    "post_id": "UP_YT_VID_777",
                    "url": "https://www.youtube.com/watch?v=UP_YT_VID_777",
                }
            },
        }
        with patch.object(upload_post, "cross_post_video", return_value=mock_upload_post_res) as mock_cp:
            res = youtube_publisher.publish_youtube_video(
                video_path=self.video_file,
                title="Title",
                caption="Caption",
                task_id="task-up-01",
                channel_id="channel-default-youtube",
                profile_id="default",
                db_path=self.db_path,
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["provider"], "upload_post")
            self.assertEqual(res["request_id"], "up_req_123")
            self.assertEqual(res["external_id"], "UP_YT_VID_777")
            self.assertEqual(res["external_url"], "https://www.youtube.com/watch?v=UP_YT_VID_777")
            mock_cp.assert_called_once()

    def test_router_dispatches_to_post_for_me_when_configured(self):
        """Post for Me é chamado quando provider é post_for_me."""
        youtube_publisher.set_youtube_publish_provider("post_for_me", db_path=self.db_path)

        mock_pfm_res = {
            "success": True,
            "provider": "post_for_me",
            "request_id": "spt_pfm_888",
            "external_id": "PFM_YT_VID_999",
            "external_url": "https://www.youtube.com/watch?v=PFM_YT_VID_999",
            "privacy_status": "public",
            "error": None,
            "error_code": None,
        }
        with patch.object(post_for_me.post_for_me_client, "publish_video", return_value=mock_pfm_res) as mock_pv:
            res = youtube_publisher.publish_youtube_video(
                video_path=self.video_file,
                title="Title",
                caption="Caption",
                task_id="task-pfm-01",
                channel_id="channel-default-youtube",
                profile_id="default",
                privacy_status="public",
                db_path=self.db_path,
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["provider"], "post_for_me")
            self.assertEqual(res["request_id"], "spt_pfm_888")
            self.assertEqual(res["external_id"], "PFM_YT_VID_999")
            self.assertEqual(res["external_url"], "https://www.youtube.com/watch?v=PFM_YT_VID_999")
            mock_pv.assert_called_once()
            self.assertIs(mock_pv.call_args.kwargs.get("made_for_kids"), False)

    def test_router_propagates_made_for_kids_true_to_post_for_me(self):
        """GAP 3: Router propaga made_for_kids=True para o cliente Post for Me."""
        youtube_publisher.set_youtube_publish_provider("post_for_me", db_path=self.db_path)

        mock_pfm_res = {
            "success": True,
            "provider": "post_for_me",
            "request_id": "spt_pfm_kids_true",
            "external_id": "PFM_YT_KIDS",
            "external_url": "https://www.youtube.com/watch?v=PFM_YT_KIDS",
            "privacy_status": "public",
            "error": None,
            "error_code": None,
        }
        with patch.object(post_for_me.post_for_me_client, "publish_video", return_value=mock_pfm_res) as mock_pv:
            res = youtube_publisher.publish_youtube_video(
                video_path=self.video_file,
                title="Title Kids",
                caption="Caption Kids",
                task_id="task-pfm-kids-01",
                channel_id="channel-default-youtube",
                profile_id="default",
                privacy_status="public",
                made_for_kids=True,
                db_path=self.db_path,
            )
            self.assertTrue(res["success"])
            mock_pv.assert_called_once()
            self.assertIs(mock_pv.call_args.kwargs.get("made_for_kids"), True)

    def test_router_propagates_tags_and_synthetic_media_to_post_for_me(self):
        """2. Router propaga tags e contains_synthetic_media=True para Post for Me."""
        youtube_publisher.set_youtube_publish_provider("post_for_me", db_path=self.db_path)

        mock_pfm_res = {
            "success": True,
            "provider": "post_for_me",
            "request_id": "spt_pfm_tags",
            "external_id": "PFM_YT_TAGS",
            "external_url": "https://www.youtube.com/watch?v=PFM_YT_TAGS",
            "privacy_status": "public",
            "error": None,
            "error_code": None,
        }
        with patch.object(post_for_me.post_for_me_client, "publish_video", return_value=mock_pfm_res) as mock_pv:
            res = youtube_publisher.publish_youtube_video(
                video_path=self.video_file,
                title="Title Tags",
                caption="Caption Tags",
                task_id="task-pfm-tags-01",
                channel_id="channel-default-youtube",
                profile_id="default",
                privacy_status="public",
                tags=["#tech", "#gadgets"],
                contains_synthetic_media=True,
                db_path=self.db_path,
            )
            self.assertTrue(res["success"])
            mock_pv.assert_called_once()
            call_kwargs = mock_pv.call_args.kwargs
            self.assertEqual(call_kwargs.get("tags"), ["#tech", "#gadgets"])
            self.assertIs(call_kwargs.get("contains_synthetic_media"), True)

    def test_publish_task_synchronous_records_native_youtube_video_id_with_post_for_me(self):
        """20. publication_events recebe external YouTube video ID, não Post for Me post ID."""
        youtube_publisher.set_youtube_publish_provider("post_for_me", db_path=self.db_path)

        task_id = "test-task-pfm-events"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        task_video = os.path.join(task_dir, "final-1.mp4")
        shutil.copyfile(self.video_file, task_video)
        script_file = os.path.join(task_dir, "script.json")
        with open(script_file, "w", encoding="utf-8") as f:
            json.dump({"script": "Test script", "params": {"video_subject": "Test"}}, f)
        self.state.update_task(task_id, state=const.TASK_STATE_COMPLETE, progress=100)

        mock_pfm_res = {
            "success": True,
            "provider": "post_for_me",
            "request_id": "spt_social_post_id_12345",
            "external_id": "NATIVE_YOUTUBE_VID_678",
            "external_url": "https://www.youtube.com/watch?v=NATIVE_YOUTUBE_VID_678",
            "privacy_status": "public",
            "error": None,
            "error_code": None,
        }

        with (
            patch.object(post_for_me.post_for_me_client, "is_configured", return_value=True),
            patch.object(youtube_publisher, "publish_youtube_video", return_value=mock_pfm_res),
            patch("app.services.operator_console.require_primary_instance", return_value=True),
            patch("app.services.operator_console.is_factory_paused", return_value=False),
        ):
            success, msg = tm.publish_task(
                task_id=task_id,
                platforms=["youtube"],
                channel_id="channel-default-youtube",
                synchronous=True,
                db_path=self.db_path,
                youtube_privacy_status="public",
            )
            self.assertTrue(success)
            self.assertEqual(msg, "")

            # Verifica o registro persistido em publication_events
            with scheduler.get_connection(self.db_path) as conn:
                row = conn.execute(
                    "SELECT platform, status, external_id, provider_request_id, external_url, privacy_status, channel_id, profile_id FROM publication_events WHERE task_id = ?;",
                    (task_id,),
                ).fetchone()

            self.assertIsNotNone(row)
            self.assertEqual(row["platform"], "youtube")
            self.assertEqual(row["status"], "success")
            # CRÍTICO: external_id DEVE ser o native YouTube video ID, NÃO o spt_...
            self.assertEqual(row["external_id"], "NATIVE_YOUTUBE_VID_678")
            self.assertNotEqual(row["external_id"], "spt_social_post_id_12345")
            # provider_request_id guarda o ID do Post for Me
            self.assertEqual(row["provider_request_id"], "spt_social_post_id_12345")
            self.assertEqual(row["external_url"], "https://www.youtube.com/watch?v=NATIVE_YOUTUBE_VID_678")
            self.assertEqual(row["privacy_status"], "public")
            self.assertEqual(row["channel_id"], "channel-default-youtube")
            self.assertIsNotNone(row["profile_id"])

        shutil.rmtree(task_dir, ignore_errors=True)

    def test_retry_failure_never_generates_publication_event(self):
        """Passo 8.10: retry ou falha nunca gera publication_event antes de success confirmado."""
        youtube_publisher.set_youtube_publish_provider("post_for_me", db_path=self.db_path)

        task_id = "test-task-pfm-fail-no-event"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        task_video = os.path.join(task_dir, "final-1.mp4")
        shutil.copyfile(self.video_file, task_video)
        script_file = os.path.join(task_dir, "script.json")
        with open(script_file, "w", encoding="utf-8") as f:
            json.dump({"script": "Test script", "params": {"video_subject": "Test"}}, f)
        self.state.update_task(task_id, state=const.TASK_STATE_COMPLETE, progress=100)

        mock_pfm_fail = {
            "success": False,
            "provider": "post_for_me",
            "request_id": "sp_failed_attempt",
            "external_id": None,
            "external_url": None,
            "privacy_status": "public",
            "error": "429 Too Many Requests RESOURCE_EXHAUSTED Quota exceeded for quota metric 'Video Uploads'",
            "error_code": "POST_RESULT_FAILED",
        }

        with (
            patch.object(post_for_me.post_for_me_client, "is_configured", return_value=True),
            patch.object(youtube_publisher, "publish_youtube_video", return_value=mock_pfm_fail),
            patch("app.services.operator_console.require_primary_instance", return_value=True),
            patch("app.services.operator_console.is_factory_paused", return_value=False),
        ):
            success, msg = tm.publish_task(
                task_id=task_id,
                platforms=["youtube"],
                channel_id="channel-default-youtube",
                synchronous=True,
                db_path=self.db_path,
                youtube_privacy_status="public",
            )
            self.assertFalse(success)

            # Verifica que NENHUM evento de publicação foi gravado para esta task
            with scheduler.get_connection(self.db_path) as conn:
                count = conn.execute(
                    "SELECT COUNT(*) as cnt FROM publication_events WHERE task_id = ?;",
                    (task_id,),
                ).fetchone()["cnt"]

            self.assertEqual(count, 0)

        shutil.rmtree(task_dir, ignore_errors=True)


    def test_tiktok_uses_post_for_me_quickstart(self):
        """23. TikTok publica via Post for Me Quickstart."""
        task_id = "test-task-tiktok"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        task_video = os.path.join(task_dir, "final-1.mp4")
        shutil.copyfile(self.video_file, task_video)
        script_file = os.path.join(task_dir, "script.json")
        with open(script_file, "w", encoding="utf-8") as f:
            json.dump({"script": "Test script", "params": {"video_subject": "Test"}}, f)
        self.state.update_task(task_id, state=const.TASK_STATE_COMPLETE, progress=100)

        mock_res = {
            "success": True,
            "provider": "post_for_me",
            "request_id": "pfm_tiktok_req",
            "external_id": "TT_POST_123",
            "external_url": "https://www.tiktok.com/@user/video/123",
            "privacy_status": "public",
        }

        with (
            patch.dict(os.environ, {"POST_FOR_ME_QUICKSTART_API_KEY": "test-quickstart-key"}),
            patch.object(post_for_me.post_for_me_quickstart_client, "is_configured", return_value=True),
            patch.object(post_for_me.post_for_me_quickstart_client, "publish_tiktok_video", return_value=mock_res) as mock_tt,
            patch("app.services.operator_console.require_primary_instance", return_value=True),
            patch("app.services.operator_console.is_factory_paused", return_value=False),
        ):
            success, msg = tm.publish_task(
                task_id=task_id,
                platforms=["tiktok"],
                channel_id="channel-default-tiktok",
                synchronous=True,
                db_path=self.db_path,
            )
            self.assertTrue(success, f"publish_task failed: {msg}")
            mock_tt.assert_called_once()
        shutil.rmtree(task_dir, ignore_errors=True)

    def test_publish_task_post_for_me_missing_key_fails(self):
        """Post for Me selecionado mas sem API Key configurada falha no publish_task."""
        youtube_publisher.set_youtube_publish_provider("post_for_me", db_path=self.db_path)

        task_id = "test-task-pfm-nokey"
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        task_video = os.path.join(task_dir, "final-1.mp4")
        shutil.copyfile(self.video_file, task_video)

        with (
            patch.object(post_for_me.post_for_me_client, "is_configured", return_value=False),
            patch("app.services.operator_console.require_primary_instance", return_value=True),
            patch("app.services.operator_console.is_factory_paused", return_value=False),
        ):
            success, msg = tm.publish_task(
                task_id=task_id,
                platforms=["youtube"],
                channel_id="channel-default-youtube",
                synchronous=True,
                db_path=self.db_path,
            )
            self.assertFalse(success)
            self.assertIn("Post for Me is not configured", msg)

        shutil.rmtree(task_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

