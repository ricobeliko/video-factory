import os
import shutil
import unittest
from unittest.mock import patch

from app.models import const
from app.services import state as sm
from app.services.state import MemoryState
from app.utils import utils
from webui.Main import (
    _active_generation_tasks,
    _add_active_generation_task,
    _collect_task_summaries,
    _remove_active_generation_task,
)


class TestTaskManagerProgress(unittest.TestCase):
    def setUp(self):
        self.state = MemoryState()
        self.patcher_state = patch.object(sm, "state", self.state)
        self.patcher_state.start()
        self.temp_dirs = []
        _active_generation_tasks().clear()

    def tearDown(self):
        self.patcher_state.stop()
        _active_generation_tasks().clear()
        for d in self.temp_dirs:
            shutil.rmtree(d, ignore_errors=True)

    def _create_task_dir(self, task_id: str, create_video: bool = False) -> str:
        task_dir = os.path.join(utils.task_dir(), task_id)
        os.makedirs(task_dir, exist_ok=True)
        self.temp_dirs.append(task_dir)
        if create_video:
            video_path = os.path.join(task_dir, "final-1.mp4")
            with open(video_path, "wb") as f:
                f.write(b"fake video")
        return task_dir

    def test_task_with_progress_10_reads_10(self):
        """Task with progress 10 in TaskManager/sm.state should be read as 10 by the UI."""
        task_id = "test-task-progress-10"
        self._create_task_dir(task_id, create_video=False)

        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_PROCESSING,
            progress=10,
            video_subject="Video 10 percent",
        )
        _add_active_generation_task(task_id, subject="Video 10 percent")

        summaries = _collect_task_summaries(limit=50)
        task_map = {item["task_id"]: item for item in summaries}

        self.assertIn(task_id, task_map)
        self.assertEqual(task_map[task_id]["progress"], 10)
        self.assertEqual(task_map[task_id]["state"], const.TASK_STATE_PROCESSING)
        self.assertEqual(task_map[task_id]["subject"], "Video 10 percent")

    def test_backend_updates_to_55_next_read_shows_55(self):
        """Backend updating progress to 55 should be reflected on the very next read."""
        task_id = "test-task-progress-55"
        self._create_task_dir(task_id, create_video=False)

        # Initial submission at 10%
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_PROCESSING,
            progress=10,
            video_subject="Updating Video",
        )
        _add_active_generation_task(task_id, subject="Updating Video")

        first_summaries = _collect_task_summaries(limit=50)
        first_map = {item["task_id"]: item for item in first_summaries}
        self.assertEqual(first_map[task_id]["progress"], 10)

        # Backend advances pipeline to 55%
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_PROCESSING,
            progress=55,
            video_subject="Updating Video",
        )

        second_summaries = _collect_task_summaries(limit=50)
        second_map = {item["task_id"]: item for item in second_summaries}
        self.assertEqual(second_map[task_id]["progress"], 55)
        self.assertEqual(second_map[task_id]["state"], const.TASK_STATE_PROCESSING)

    def test_task_complete_shows_100(self):
        """Completed task should show progress 100 and state COMPLETE."""
        task_id = "test-task-complete"
        task_dir = self._create_task_dir(task_id, create_video=True)
        video_file = os.path.join(task_dir, "final-1.mp4")

        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            video_subject="Completed Video",
            videos=[video_file],
        )
        _add_active_generation_task(task_id, subject="Completed Video")

        summaries = _collect_task_summaries(limit=50)
        task_map = {item["task_id"]: item for item in summaries}

        self.assertIn(task_id, task_map)
        self.assertEqual(task_map[task_id]["progress"], 100)
        self.assertEqual(task_map[task_id]["state"], const.TASK_STATE_COMPLETE)
        # Should be cleared from active generation tasks
        self.assertNotIn(task_id, _active_generation_tasks())

    def test_task_failed_status_updated(self):
        """Failed task should have status updated to FAILED and removed from active."""
        task_id = "test-task-failed"
        self._create_task_dir(task_id, create_video=False)

        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_FAILED,
            progress=25,
            error="LLM quota exceeded",
            video_subject="Failed Video",
        )
        _add_active_generation_task(task_id, subject="Failed Video")

        summaries = _collect_task_summaries(limit=50)
        task_map = {item["task_id"]: item for item in summaries}

        self.assertIn(task_id, task_map)
        self.assertEqual(task_map[task_id]["state"], const.TASK_STATE_FAILED)
        self.assertNotIn(task_id, _active_generation_tasks())

    def test_multiple_batch_tasks_update_independently(self):
        """Multiple batch tasks in different stages should update progress independently."""
        t1 = "batch-task-1"
        t2 = "batch-task-2"
        t3 = "batch-task-3"

        self._create_task_dir(t1, create_video=False)
        self._create_task_dir(t2, create_video=False)
        self._create_task_dir(t3, create_video=False)

        # Batch submission: t1 running, t2 and t3 queued/pending
        sm.state.update_task(t1, state=const.TASK_STATE_PROCESSING, progress=40, video_subject="Topic 1")
        sm.state.update_task(t2, state=const.TASK_STATE_PROCESSING, progress=0, video_subject="Topic 2")
        sm.state.update_task(t3, state=const.TASK_STATE_PROCESSING, progress=0, video_subject="Topic 3")

        _add_active_generation_task(t1, subject="Topic 1")
        _add_active_generation_task(t2, subject="Topic 2")
        _add_active_generation_task(t3, subject="Topic 3")

        s1 = {item["task_id"]: item for item in _collect_task_summaries(limit=50)}
        self.assertEqual(s1[t1]["progress"], 40)
        self.assertEqual(s2_prog := s1[t2]["progress"], 0)
        self.assertEqual(s3_prog := s1[t3]["progress"], 0)
        self.assertEqual(s1[t1]["state"], const.TASK_STATE_PROCESSING)
        self.assertEqual(s1[t2]["state"], const.TASK_STATE_PROCESSING)
        self.assertEqual(s1[t3]["state"], const.TASK_STATE_PROCESSING)

        # t1 completes, t2 starts processing at 50%
        sm.state.update_task(t1, state=const.TASK_STATE_COMPLETE, progress=100, video_subject="Topic 1")
        sm.state.update_task(t2, state=const.TASK_STATE_PROCESSING, progress=50, video_subject="Topic 2")

        s2 = {item["task_id"]: item for item in _collect_task_summaries(limit=50)}
        self.assertEqual(s2[t1]["progress"], 100)
        self.assertEqual(s2[t1]["state"], const.TASK_STATE_COMPLETE)
        self.assertEqual(s2[t2]["progress"], 50)
        self.assertEqual(s2[t2]["state"], const.TASK_STATE_PROCESSING)
        self.assertEqual(s2[t3]["progress"], 0)
        self.assertEqual(s2[t3]["state"], const.TASK_STATE_PROCESSING)

        # t2 fails, t3 starts processing at 75%
        sm.state.update_task(t2, state=const.TASK_STATE_FAILED, progress=50, error="TTS timeout")
        sm.state.update_task(t3, state=const.TASK_STATE_PROCESSING, progress=75, video_subject="Topic 3")

        s3 = {item["task_id"]: item for item in _collect_task_summaries(limit=50)}
        self.assertEqual(s3[t1]["progress"], 100)
        self.assertEqual(s3[t1]["state"], const.TASK_STATE_COMPLETE)
        self.assertEqual(s3[t2]["state"], const.TASK_STATE_FAILED)
        self.assertEqual(s3[t3]["progress"], 75)
        self.assertEqual(s3[t3]["state"], const.TASK_STATE_PROCESSING)

    def test_render_task_table_reconsults_live_task_state(self):
        """Verify _render_task_table updates task dict with live state from sm.state before rendering."""
        from webui.Main import _render_task_table
        from unittest.mock import MagicMock

        task_id = "test-live-render"
        self._create_task_dir(task_id, create_video=False)
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_PROCESSING,
            progress=85,
            video_subject="Live Subject",
        )

        # Snapshot passed into table has old progress 0
        stale_task = {
            "task_id": task_id,
            "subject": "Old Subject",
            "state": const.TASK_STATE_PROCESSING,
            "progress": 0,
            "mtime": 12345,
            "task_path": os.path.join(utils.task_dir(), task_id),
            "video_file": "",
        }

        with patch("streamlit.container"), patch("streamlit.columns") as mock_cols:
            mock_col = MagicMock()
            mock_cols.return_value = [mock_col] * 5
            _render_task_table([stale_task], key_prefix="test")

        # The stale_task dict should have been refreshed to 85%
        self.assertEqual(stale_task["progress"], 85)
        self.assertEqual(stale_task["subject"], "Live Subject")


if __name__ == "__main__":
    unittest.main()

