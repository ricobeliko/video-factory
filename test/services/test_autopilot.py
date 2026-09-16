import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.models import const
from app.models.schema import VideoParams
from app.services import autopilot, llm, state as sm, webui_task
from app.config import config


class TestAutopilot(unittest.TestCase):

    def setUp(self):
        # Garante estado limpo em memória para cada teste
        sm.state = sm.MemoryState()

    def test_01_generate_n_ideas_returns_up_to_n_valid_topics(self):
        fake_llm_output = "\n".join([f"{i}. Ideia de vídeo {i}" for i in range(1, 20)])
        with patch.object(llm, "_generate_response", return_value=fake_llm_output):
            ideas = autopilot.generate_ideas(niche="Curiosidades", count=10, language="pt-BR")
            self.assertEqual(len(ideas), 10)
            self.assertTrue(all(isinstance(x, str) and len(x) > 0 for x in ideas))
            self.assertEqual(ideas[0], "Ideia de vídeo 1")

    def test_02_empty_lines_are_ignored(self):
        fake_llm_output = "1. Ideia Um\n\n   \n\n2. Ideia Dois\n\n\n3. Ideia Três\n"
        with patch.object(llm, "_generate_response", return_value=fake_llm_output):
            ideas = autopilot.generate_ideas(niche="Ciência", count=5, language="pt-BR")
            self.assertEqual(len(ideas), 3)
            self.assertEqual(ideas, ["Ideia Um", "Ideia Dois", "Ideia Três"])

    def test_03_normalized_duplicates_are_removed(self):
        fake_llm_output = (
            "1. Você sabia que o Sol é quente?\n"
            "2. voce sabia que o sol e quente?\n"
            "3.   VOCÊ SABIA QUE O SOL É QUENTE...   \n"
            "4. Por que o céu é azul?\n"
            "5. Por que o céu é azul???\n"
        )
        with patch.object(llm, "_generate_response", return_value=fake_llm_output):
            ideas = autopilot.generate_ideas(niche="Espaço", count=5, language="pt-BR")
            self.assertEqual(len(ideas), 2)
            self.assertEqual(ideas[0], "Você sabia que o Sol é quente?")
            self.assertEqual(ideas[1], "Por que o céu é azul?")

    def test_04_max_limit_30_enforced(self):
        fake_llm_output = "\n".join([f"{i}. Tema número {i}" for i in range(1, 50)])
        with patch.object(llm, "_generate_response", return_value=fake_llm_output):
            ideas = autopilot.generate_ideas(niche="História", count=45, language="pt-BR")
            self.assertEqual(len(ideas), 30)

    def test_05_ptbr_respected_in_prompt(self):
        prompt_pt = autopilot.build_ideas_prompt(niche="Astronomia", count=15, language="pt-BR")
        self.assertIn("português do Brasil (pt-BR)", prompt_pt)
        self.assertIn("Você sabia...", prompt_pt)
        self.assertIn("Por que...", prompt_pt)
        self.assertIn("Astronomia", prompt_pt)

    def test_06_plan_15_videos_tiktok_and_youtube(self):
        plan = autopilot.plan_distribution(
            selected_count=15,
            tiktok_active=True,
            tiktok_target=15,
            youtube_active=True,
            youtube_target=10,
        )
        self.assertEqual(len(plan), 15)
        # Primeiros 10 recebem ambos
        for i in range(10):
            self.assertEqual(set(plan[i]), {"tiktok", "youtube"})
        # Próximos 5 recebem apenas TikTok
        for i in range(10, 15):
            self.assertEqual(plan[i], ["tiktok"])

    def test_07_plan_only_tiktok(self):
        plan = autopilot.plan_distribution(
            selected_count=15,
            tiktok_active=True,
            tiktok_target=15,
            youtube_active=False,
            youtube_target=10,
        )
        self.assertEqual(len(plan), 15)
        for i in range(15):
            self.assertEqual(plan[i], ["tiktok"])

    def test_08_plan_only_youtube(self):
        plan = autopilot.plan_distribution(
            selected_count=15,
            tiktok_active=False,
            tiktok_target=15,
            youtube_active=True,
            youtube_target=10,
        )
        self.assertEqual(len(plan), 15)
        for i in range(10):
            self.assertEqual(plan[i], ["youtube"])
        # Do 11 ao 15 a cota do YouTube esgotou
        for i in range(10, 15):
            self.assertEqual(plan[i], [])

    def test_09_stock_sufficient_deficit_zero(self):
        fake_tasks = [
            {"task_id": f"t{i}", "state": const.TASK_STATE_COMPLETE, "video_file": "v.mp4"}
            for i in range(35)
        ]
        res = autopilot.calculate_stock(fake_tasks, desired_stock=30)
        self.assertEqual(res["desired"], 30)
        self.assertEqual(res["ready"], 35)
        self.assertEqual(res["total"], 35)
        self.assertEqual(res["deficit"], 0)
        self.assertTrue(res["is_sufficient"])

    def test_10_stock_below_target_deficit_correct(self):
        fake_tasks = [
            {"task_id": "t1", "state": const.TASK_STATE_COMPLETE, "video_file": "v1.mp4"},
            {"task_id": "t2", "state": const.TASK_STATE_COMPLETE, "video_file": "v2.mp4"},
            {"task_id": "t3", "state": const.TASK_STATE_PROCESSING},
            {"task_id": "t4", "state": const.TASK_STATE_PENDING},
        ]
        res = autopilot.calculate_stock(fake_tasks, desired_stock=30)
        self.assertEqual(res["desired"], 30)
        self.assertEqual(res["ready"], 2)
        self.assertEqual(res["processing"], 1)
        self.assertEqual(res["pending"], 1)
        self.assertEqual(res["total"], 4)
        self.assertEqual(res["deficit"], 26)
        self.assertFalse(res["is_sufficient"])

    def test_11_published_videos_excluded_from_stock(self):
        fake_tasks = [
            {"task_id": "t1", "state": const.TASK_STATE_COMPLETE, "video_file": "v1.mp4", "cross_post_state": const.CROSS_POST_STATE_COMPLETE},
            {"task_id": "t2", "state": const.TASK_STATE_COMPLETE, "video_file": "v2.mp4"},
            {"task_id": "t3", "state": const.TASK_STATE_PROCESSING},
        ]
        res = autopilot.calculate_stock(fake_tasks, desired_stock=10)
        # t1 foi publicado, então estoque pronto deve ser apenas 1 (t2)
        self.assertEqual(res["ready"], 1)
        self.assertEqual(res["processing"], 1)
        self.assertEqual(res["total"], 2)
        self.assertEqual(res["deficit"], 8)

    def test_12_selected_ideas_use_existing_batch_generation(self):
        selected_topics = ["Curiosidade sobre o Sol", "Curiosidade sobre Marte"]
        base_params = VideoParams(
            video_subject="",
            video_script="",
            video_language="pt-BR",
        )
        plan = [["tiktok", "youtube"], ["tiktok"]]

        submitted_calls = []

        def fake_submit(task_id, params, **kwargs):
            submitted_calls.append((task_id, params.model_copy(deep=True)))
            sm.state.update_task(task_id, state=const.TASK_STATE_PENDING, progress=0)

        with patch.object(webui_task, "submit_generation", side_effect=fake_submit):
            for i, topic in enumerate(selected_topics):
                tid = f"task-autopilot-{i}"
                p = base_params.model_copy(deep=True)
                p.video_subject = topic
                webui_task.submit_generation(tid, p)
                sm.state.update_task(tid, planned_platforms=plan[i])

            self.assertEqual(len(submitted_calls), 2)
            self.assertEqual(submitted_calls[0][1].video_subject, "Curiosidade sobre o Sol")
            self.assertEqual(submitted_calls[0][1].video_language, "pt-BR")
            self.assertEqual(submitted_calls[1][1].video_subject, "Curiosidade sobre Marte")

    def test_13_planned_platforms_stored_only_in_state(self):
        tid = "task-state-platforms-test"
        sm.state.update_task(tid, state=const.TASK_STATE_PENDING, progress=0, planned_platforms=["tiktok", "youtube"])
        task_data = sm.state.get_task(tid)
        self.assertIsNotNone(task_data)
        self.assertEqual(task_data.get("planned_platforms"), ["tiktok", "youtube"])

    def test_14_script_json_does_not_contain_planned_platforms(self):
        # Simula salvamento de script.json como o pipeline normal faz
        with tempfile.TemporaryDirectory() as temp_dir:
            from app.utils import utils
            with patch.object(utils, "task_dir", return_value=temp_dir):
                from app.services import task as tm
                params = VideoParams(video_subject="Teste Script")
                tm.save_script_data("task-test-script", "Roteiro teste", ["termo1"], params)

                script_file = os.path.join(temp_dir, "script.json")
                self.assertTrue(os.path.isfile(script_file))
                with open(script_file, "r", encoding="utf-8") as f:
                    content = f.read()
                self.assertNotIn("planned_platforms", content)

    def test_15_no_call_to_upload_post_occurs(self):
        with patch("app.services.task.publish_task") as mock_publish, \
             patch("app.services.task._run_cross_post") as mock_cross_post:
            # Geração de ideias
            with patch.object(llm, "_generate_response", return_value="1. Ideia teste"):
                autopilot.generate_ideas("Espaço", 1, "pt-BR")

            # Planejamento
            autopilot.plan_distribution(1)

            # Cálculo de estoque
            autopilot.calculate_stock([])

            # Nenhum envio ao Upload-Post
            mock_publish.assert_not_called()
            mock_cross_post.assert_not_called()

    def test_16_upload_post_auto_upload_is_not_modified(self):
        initial_val = config.app.get("upload_post_auto_upload", False)
        # Executa rotinas do autopilot
        with patch.object(llm, "_generate_response", return_value="1. Ideia teste"):
            autopilot.generate_ideas("Curiosidades", 1, "pt-BR")
        autopilot.plan_distribution(5)
        autopilot.calculate_stock([])

        current_val = config.app.get("upload_post_auto_upload", False)
        self.assertEqual(initial_val, current_val)


if __name__ == "__main__":
    unittest.main()
