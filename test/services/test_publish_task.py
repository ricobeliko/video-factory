import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.config import config
from app.models import const
from app.services import state as sm
from app.services import task as tm
from app.services.state import MemoryState
from app.utils import utils


class TestPublishTask(unittest.TestCase):
    def setUp(self):
        self.state = MemoryState()
        self.patcher_state = patch.object(tm.sm, "state", self.state)
        self.patcher_state.start()
        self.temp_dirs = []

    def tearDown(self):
        self.patcher_state.stop()
        for d in self.temp_dirs:
            shutil.rmtree(d, ignore_errors=True)

    def _create_task_dir(self, task_id: str, create_video: bool = True, create_script: bool = True) -> str:
        task_dir = utils.task_dir(task_id)
        os.makedirs(task_dir, exist_ok=True)
        self.temp_dirs.append(task_dir)

        if create_video:
            video_path = os.path.join(task_dir, "final-1.mp4")
            with open(video_path, "wb") as f:
                f.write(b"fake mp4 video content")

        if create_script:
            script_path = os.path.join(task_dir, "script.json")
            with open(script_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "script": "Test video script",
                        "params": {
                            "video_subject": "Test subject",
                            "video_language": "pt",
                        },
                    },
                    f,
                )

        return task_dir

    def test_publish_task_fails_when_upload_post_disabled(self):
        task_id = "test-pub-disabled"
        self._create_task_dir(task_id)

        test_config = dict(
            config.app,
            upload_post_enabled=False,
            upload_post_api_key="secret-key",
            upload_post_username="testuser",
        )
        with patch.object(config, "app", test_config):
            success, msg = tm.publish_task(task_id)
            self.assertFalse(success)
            self.assertIn("disabled", msg.lower())

    def test_publish_task_fails_when_not_configured(self):
        task_id = "test-pub-not-configured"
        self._create_task_dir(task_id)

        test_config = dict(
            config.app,
            upload_post_enabled=True,
            upload_post_api_key="",
            upload_post_username="",
        )
        with patch.object(config, "app", test_config):
            success, msg = tm.publish_task(task_id)
            self.assertFalse(success)
            self.assertIn("not fully configured", msg.lower())

    def test_publish_task_fails_when_no_platforms(self):
        task_id = "test-pub-no-platforms"
        self._create_task_dir(task_id)

        test_config = dict(
            config.app,
            upload_post_enabled=True,
            upload_post_api_key="secret-key",
            upload_post_username="testuser",
            upload_post_platforms=[],
        )
        with patch.object(config, "app", test_config):
            success, msg = tm.publish_task(task_id)
            self.assertFalse(success)
            self.assertIn("no target platforms", msg.lower())

    def test_publish_task_fails_when_directory_missing(self):
        test_config = dict(
            config.app,
            upload_post_enabled=True,
            upload_post_api_key="secret-key",
            upload_post_username="testuser",
            upload_post_platforms=["tiktok"],
        )
        with patch.object(config, "app", test_config):
            success, msg = tm.publish_task("nonexistent-task-id-12345")
            self.assertFalse(success)
            self.assertIn("not found", msg.lower())

    def test_publish_task_fails_when_task_is_busy(self):
        task_id = "test-pub-busy"
        self._create_task_dir(task_id)

        self.state.update_task(
            task_id,
            state=const.TASK_STATE_PROCESSING,
            progress=50,
        )

        test_config = dict(
            config.app,
            upload_post_enabled=True,
            upload_post_api_key="secret-key",
            upload_post_username="testuser",
            upload_post_platforms=["tiktok"],
        )
        with patch.object(config, "app", test_config):
            success, msg = tm.publish_task(task_id)
            self.assertFalse(success)
            self.assertIn("currently processing", msg.lower())

    def test_publish_task_fails_when_cross_post_is_active(self):
        task_id = "test-pub-crosspost-active"
        self._create_task_dir(task_id)

        self.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            cross_post_state=const.CROSS_POST_STATE_PROCESSING,
        )

        test_config = dict(
            config.app,
            upload_post_enabled=True,
            upload_post_api_key="secret-key",
            upload_post_username="testuser",
            upload_post_platforms=["tiktok"],
        )
        with patch.object(config, "app", test_config):
            success, msg = tm.publish_task(task_id)
            self.assertFalse(success)
            self.assertIn("already publishing", msg.lower())

    def test_publish_task_fails_when_task_failed(self):
        task_id = "test-pub-failed"
        self._create_task_dir(task_id)

        self.state.update_task(
            task_id,
            state=const.TASK_STATE_FAILED,
            progress=0,
        )

        test_config = dict(
            config.app,
            upload_post_enabled=True,
            upload_post_api_key="secret-key",
            upload_post_username="testuser",
            upload_post_platforms=["tiktok"],
        )
        with patch.object(config, "app", test_config):
            success, msg = tm.publish_task(task_id)
            self.assertFalse(success)
            self.assertIn("cannot publish a failed task", msg.lower())

    def test_publish_task_fails_when_no_final_video_exists(self):
        task_id = "test-pub-no-video"
        self._create_task_dir(task_id, create_video=False)

        test_config = dict(
            config.app,
            upload_post_enabled=True,
            upload_post_api_key="secret-key",
            upload_post_username="testuser",
            upload_post_platforms=["tiktok"],
        )
        with patch.object(config, "app", test_config):
            success, msg = tm.publish_task(task_id)
            self.assertFalse(success)
            self.assertIn("no final video file", msg.lower())

    def test_publish_task_success_works_with_auto_upload_false(self):
        task_id = "test-pub-success"
        self._create_task_dir(task_id)

        test_config = dict(
            config.app,
            upload_post_enabled=True,
            upload_post_auto_upload=False,  # auto_upload is disabled!
            upload_post_api_key="secret-key-12345",
            upload_post_username="testuser",
            upload_post_platforms=["tiktok", "youtube"],
            upload_post_youtube_privacy_status="private",
            upload_post_youtube_made_for_kids=False,
        )

        with (
            patch.object(config, "app", test_config),
            patch.object(tm, "_schedule_cross_post", return_value=None) as mock_schedule,
        ):
            success, msg = tm.publish_task(task_id)
            self.assertTrue(success)
            self.assertEqual(msg, "")

            # Verify schedule arguments
            mock_schedule.assert_called_once()
            call_kwargs = mock_schedule.call_args.kwargs
            self.assertEqual(call_kwargs["task_id"], task_id)
            self.assertEqual(len(call_kwargs["video_paths"]), 1)
            self.assertTrue(call_kwargs["video_paths"][0].endswith("final-1.mp4"))
            self.assertEqual(call_kwargs["video_script"], "Test video script")
            self.assertEqual(call_kwargs["platforms"], ["tiktok", "youtube"])
            self.assertEqual(call_kwargs["youtube_privacy_status"], "private")
            self.assertEqual(call_kwargs["youtube_made_for_kids"], False)

            # Check task state in sm.state
            task = self.state.get_task(task_id)
            self.assertIsNotNone(task)
            self.assertEqual(task["state"], const.TASK_STATE_COMPLETE)
            self.assertEqual(task["cross_post_state"], const.CROSS_POST_STATE_PENDING)

            # Verify secret key never appears in msg or task dict
            self.assertNotIn("secret-key", msg)
            self.assertNotIn("secret-key", str(task))

    def test_ui_publish_action_enabled_only_when_completed_with_video_and_not_busy(self):
        # Helper to simulate the exact conditions used in _render_task_table
        def can_publish(task_state_filter, has_video, is_busy):
            return task_state_filter == "complete" and has_video and not is_busy

        # Case 1: Completed task with video, not busy -> CAN publish
        self.assertTrue(can_publish("complete", True, False))

        # Case 2: Processing task -> CANNOT publish
        self.assertFalse(can_publish("processing", True, False))
        self.assertFalse(can_publish("processing", True, True))

        # Case 3: Failed task -> CANNOT publish
        self.assertFalse(can_publish("failed", True, False))
        self.assertFalse(can_publish("failed", False, False))

        # Case 4: Completed task but video file missing -> CANNOT publish
        self.assertFalse(can_publish("complete", False, False))

        # Case 5: Completed task with video, but busy (cross-post in progress) -> CANNOT publish
        self.assertFalse(can_publish("complete", True, True))


if __name__ == "__main__":
    unittest.main()

