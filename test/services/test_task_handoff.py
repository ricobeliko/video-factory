import unittest
from unittest.mock import MagicMock, patch

from app.models import const
from app.services import state as sm
from app.services import webui_task


class TestTaskHandoff(unittest.TestCase):
    def setUp(self):
        self.mock_st = MagicMock()
        self.mock_st.session_state = {
            "active_generation_tasks": {},
            "current_generation_task_id": "",
            "handled_generation_task_id": "",
        }
        self.patcher = patch.dict("sys.modules", {"streamlit": self.mock_st})
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_two_task_batch_handoff(self):
        from webui import Main
        Main.st = self.mock_st

        task_a = "task-batch-aaa-111"
        task_b = "task-batch-bbb-222"
        topic_a = "3 curiosidades sobre o sol?"
        topic_b = "3 curiosidades sobre Io a lua de Júpiter?"

        # 1. Tasks submitted in batch
        Main._add_active_generation_task(task_a, subject=topic_a)
        Main._add_active_generation_task(task_b, subject=topic_b)
        self.mock_st.session_state["current_generation_task_id"] = task_a

        # Task A: PROCESSING 40%, Task B: PENDING 0%
        sm.state.update_task(task_a, state=const.TASK_STATE_PROCESSING, progress=40, video_subject=topic_a)
        sm.state.update_task(task_b, state=const.TASK_STATE_PENDING, progress=0, video_subject=topic_b)

        # Verify initial rendering
        summaries = Main._collect_task_summaries(limit=20)
        sum_a = next((t for t in summaries if t["task_id"] == task_a), None)
        sum_b = next((t for t in summaries if t["task_id"] == task_b), None)
        self.assertIsNotNone(sum_a)
        self.assertIsNotNone(sum_b)
        self.assertEqual(sum_a["state"], const.TASK_STATE_PROCESSING)
        self.assertEqual(sum_a["progress"], 40)
        self.assertEqual(sum_b["state"], const.TASK_STATE_PENDING)
        self.assertEqual(sum_b["progress"], 0)

        # 2. Task A completes 100%, Task B starts PROCESSING 15%
        sm.state.update_task(task_a, state=const.TASK_STATE_COMPLETE, progress=100)
        sm.state.update_task(task_b, state=const.TASK_STATE_PROCESSING, progress=15)

        # Simulate task completion transition in running task fragment
        Main._remove_active_generation_task(task_a)
        next_task_id = Main._get_next_active_generation_task_id(current_task_id=task_a)
        if next_task_id:
            self.mock_st.session_state["current_generation_task_id"] = next_task_id

        self.assertEqual(self.mock_st.session_state["current_generation_task_id"], task_b)

        # Next rendering MUST show: A = COMPLETE / 100, B = PROCESSING / 15
        summaries = Main._collect_task_summaries(limit=20)
        sum_a = next((t for t in summaries if t["task_id"] == task_a), None)
        sum_b = next((t for t in summaries if t["task_id"] == task_b), None)
        self.assertIsNotNone(sum_a)
        self.assertIsNotNone(sum_b)
        self.assertEqual(sum_a["state"], const.TASK_STATE_COMPLETE)
        self.assertEqual(sum_a["progress"], 100)
        self.assertEqual(sum_b["state"], const.TASK_STATE_PROCESSING)
        self.assertEqual(sum_b["progress"], 15)

        # 3. Update B: 15 -> 50
        sm.state.update_task(task_b, state=const.TASK_STATE_PROCESSING, progress=50)
        summaries = Main._collect_task_summaries(limit=20)
        sum_b = next((t for t in summaries if t["task_id"] == task_b), None)
        self.assertEqual(sum_b["state"], const.TASK_STATE_PROCESSING)
        self.assertEqual(sum_b["progress"], 50)

        # 4. Update B: 50 -> 100
        sm.state.update_task(task_b, state=const.TASK_STATE_COMPLETE, progress=100)
        summaries = Main._collect_task_summaries(limit=20)
        sum_b = next((t for t in summaries if t["task_id"] == task_b), None)
        self.assertEqual(sum_b["state"], const.TASK_STATE_COMPLETE)
        self.assertEqual(sum_b["progress"], 100)

    def test_three_task_batch_handoff_tracks_task_c(self):
        from webui import Main
        Main.st = self.mock_st

        task_a = "task-batch-3-aaa"
        task_b = "task-batch-3-bbb"
        task_c = "task-batch-3-ccc"

        Main._add_active_generation_task(task_a, subject="Tema A")
        Main._add_active_generation_task(task_b, subject="Tema B")
        Main._add_active_generation_task(task_c, subject="Tema C")

        # Scenario: A COMPLETE, B COMPLETE, C PROCESSING 35
        sm.state.update_task(task_a, state=const.TASK_STATE_COMPLETE, progress=100, video_subject="Tema A")
        sm.state.update_task(task_b, state=const.TASK_STATE_COMPLETE, progress=100, video_subject="Tema B")
        sm.state.update_task(task_c, state=const.TASK_STATE_PROCESSING, progress=35, video_subject="Tema C")

        # A and B completed, removed from active
        Main._remove_active_generation_task(task_a)
        Main._remove_active_generation_task(task_b)

        # Next active task must be C
        next_task_id = Main._get_next_active_generation_task_id(current_task_id=task_b)
        self.mock_st.session_state["current_generation_task_id"] = next_task_id
        self.assertEqual(self.mock_st.session_state["current_generation_task_id"], task_c)

        # Verify UI summaries
        summaries = Main._collect_task_summaries(limit=20)
        sum_a = next((t for t in summaries if t["task_id"] == task_a), None)
        sum_b = next((t for t in summaries if t["task_id"] == task_b), None)
        sum_c = next((t for t in summaries if t["task_id"] == task_c), None)

        self.assertEqual(sum_a["state"], const.TASK_STATE_COMPLETE)
        self.assertEqual(sum_a["progress"], 100)
        self.assertEqual(sum_b["state"], const.TASK_STATE_COMPLETE)
        self.assertEqual(sum_b["progress"], 100)
        self.assertEqual(sum_c["state"], const.TASK_STATE_PROCESSING)
        self.assertEqual(sum_c["progress"], 35)

    def test_submit_generation_pending_transition(self):
        import threading
        import time
        from app.models.schema import VideoParams

        task_a = "test-sub-a"
        task_b = "test-sub-b"
        params = VideoParams(video_subject="Solar")

        started_tasks = []
        finish_event_a = threading.Event()

        def fake_start(task_id, **kwargs):
            started_tasks.append(task_id)
            if task_id == task_a:
                finish_event_a.wait(timeout=5)
            sm.state.update_task(task_id, state=const.TASK_STATE_COMPLETE, progress=100)
            return {"videos": ["fake.mp4"]}

        with patch("app.services.task.start", side_effect=fake_start):
            # 1. Submit task A
            webui_task.submit_generation(task_a, params)
            state_a = sm.state.get_task(task_a)
            self.assertEqual(state_a["state"], const.TASK_STATE_PROCESSING)

            # 2. Submit task B while A is running
            webui_task.submit_generation(task_b, params)
            state_b = sm.state.get_task(task_b)
            self.assertEqual(state_b["state"], const.TASK_STATE_PENDING)
            self.assertEqual(state_b["progress"], 0)

            # 3. Allow Task A to finish
            finish_event_a.set()

            # Wait briefly for worker to dequeue task B
            for _ in range(50):
                state_b = sm.state.get_task(task_b)
                if state_b and state_b.get("state") in (const.TASK_STATE_PROCESSING, const.TASK_STATE_COMPLETE):
                    break
                time.sleep(0.05)

            state_b = sm.state.get_task(task_b)
            self.assertIn(state_b["state"], (const.TASK_STATE_PROCESSING, const.TASK_STATE_COMPLETE))


if __name__ == "__main__":
    unittest.main()
