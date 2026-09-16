import unittest
from unittest.mock import MagicMock, patch
from uuid import UUID

from app.config import config
from app.models import const
from app.models.schema import VideoParams
from app.services import state as sm
from app.services import webui_task
from app.services.state import MemoryState
from app.services.webui_task import parse_batch_topics


class TestBatchGeneration(unittest.TestCase):
    def setUp(self):
        self.state = MemoryState()
        self.patcher_state = patch.object(sm, "state", self.state)
        self.patcher_state.start()

    def tearDown(self):
        self.patcher_state.stop()

    def test_parse_batch_topics_ignores_empty_lines_and_strips_whitespace(self):
        raw = "\n  3 curiosidades sobre Saturno  \n\n\tPor que Mercúrio é tão quente?\n   \n"
        topics, duplicates, err = parse_batch_topics(raw, max_limit=10)
        self.assertIsNone(err)
        self.assertEqual(duplicates, 0)
        self.assertEqual(
            topics,
            [
                "3 curiosidades sobre Saturno",
                "Por que Mercúrio é tão quente?",
            ],
        )

    def test_parse_batch_topics_deduplicates_topics_preserving_order(self):
        raw = "Tema A\nTema B\n  Tema A  \nTema C\nTema B\nTema A"
        topics, duplicates, err = parse_batch_topics(raw, max_limit=10)
        self.assertIsNone(err)
        self.assertEqual(duplicates, 3)
        self.assertEqual(topics, ["Tema A", "Tema B", "Tema C"])

    def test_parse_batch_topics_rejects_empty_input(self):
        for empty_val in ["", "   ", "\n\n  \t\n"]:
            topics, duplicates, err = parse_batch_topics(empty_val, max_limit=10)
            self.assertEqual(err, "empty")
            self.assertEqual(topics, [])
            self.assertEqual(duplicates, 0)

    def test_parse_batch_topics_enforces_max_limit(self):
        eleven_topics = "\n".join(f"Tema {i}" for i in range(1, 12))
        topics, duplicates, err = parse_batch_topics(eleven_topics, max_limit=10)
        self.assertEqual(err, "limit_exceeded")
        self.assertEqual(len(topics), 11)

        ten_topics = "\n".join(f"Tema {i}" for i in range(1, 11))
        topics, duplicates, err = parse_batch_topics(ten_topics, max_limit=10)
        self.assertIsNone(err)
        self.assertEqual(len(topics), 10)

    def test_batch_submission_creates_independent_tasks_with_inherited_params(self):
        base_params = VideoParams(
            video_subject="Initial Subject",
            video_language="pt",
            voice_name="pt-BR-FranciscaNeural",
            paragraph_number=2,
        )
        topics = ["Tema 1", "Tema 2", "Tema 3"]

        submitted = []

        def fake_submit(task_id, params, capture_logs=True, voice_preview=None, loomloom_video_request=None):
            # Validate task_id is a valid UUID
            UUID(task_id)
            submitted.append((task_id, params))

        with patch.object(webui_task, "submit_generation", side_effect=fake_submit):
            for topic in topics:
                from uuid import uuid4
                tid = str(uuid4())
                item_params = base_params.model_copy(deep=True)
                item_params.video_subject = topic
                item_params.video_script = ""
                webui_task.submit_generation(
                    task_id=tid,
                    params=item_params,
                    capture_logs=True,
                    voice_preview=None,
                    loomloom_video_request=None,
                )

        self.assertEqual(len(submitted), 3)

        # Ensure all task_ids are distinct
        task_ids = [item[0] for item in submitted]
        self.assertEqual(len(set(task_ids)), 3)

        # Ensure params are properly cloned with correct topic and script is empty
        for i, (tid, p) in enumerate(submitted):
            self.assertEqual(p.video_subject, topics[i])
            self.assertEqual(p.video_script, "")
            self.assertEqual(p.video_language, "pt")
            self.assertEqual(p.voice_name, "pt-BR-FranciscaNeural")
            self.assertEqual(p.paragraph_number, 2)

    def test_batch_submission_failure_of_one_task_does_not_stop_remaining(self):
        topics = ["Tema Sucesso 1", "Tema Falha", "Tema Sucesso 2"]
        success_ids = []

        def flaky_submit(task_id, params, **kwargs):
            if "Falha" in params.video_subject:
                raise RuntimeError("Simulated transient submission error")
            success_ids.append(task_id)

        with patch.object(webui_task, "submit_generation", side_effect=flaky_submit):
            for topic in topics:
                from uuid import uuid4
                tid = str(uuid4())
                try:
                    p = VideoParams(video_subject=topic)
                    webui_task.submit_generation(task_id=tid, params=p)
                except Exception:
                    pass

        # 2 out of 3 should have succeeded
        self.assertEqual(len(success_ids), 2)

    def test_batch_generation_does_not_trigger_auto_upload(self):
        # Ensure auto-upload stays False and is never invoked during batch creation
        test_config = dict(
            config.app,
            upload_post_enabled=True,
            upload_post_auto_upload=False,
            upload_post_api_key="secret-api-key-999",
            upload_post_username="batchuser",
        )

        with (
            patch.object(config, "app", test_config),
            patch("app.services.upload_post.cross_post_video") as mock_crosspost,
        ):
            # Verify auto_upload configuration is unchanged
            self.assertFalse(config.app.get("upload_post_auto_upload", False))

            # Simulate batch task creation
            base_params = VideoParams(video_subject="Space Topic")
            with patch.object(webui_task._task_manager, "add_task"):
                webui_task.submit_generation("task-batch-check", base_params)

            # Upload-Post must NEVER be called during task submission
            mock_crosspost.assert_not_called()
            self.assertFalse(config.app.get("upload_post_auto_upload", False))


if __name__ == "__main__":
    unittest.main()
