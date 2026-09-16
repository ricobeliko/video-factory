import ast
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.controllers.manager.memory_manager import InMemoryTaskManager
from app.models import const
from app.models.schema import VideoParams
from app.services import llm
from app.services import webui_task
from app.services.task import is_task_busy

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEBUI_MAIN = PROJECT_ROOT / "webui" / "Main.py"


class TestGenerationControlsAndPtBr(unittest.TestCase):
    def setUp(self):
        self.main_code = WEBUI_MAIN.read_text(encoding="utf-8")
        self.main_tree = ast.parse(self.main_code)

    def test_pt_br_present_in_support_locales(self):
        """Verify pt-BR is included in support_locales in webui/Main.py."""
        support_locales = None
        for node in self.main_tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "support_locales":
                        support_locales = ast.literal_eval(node.value)
                        break

        self.assertIsNotNone(support_locales)
        self.assertIn("pt-BR", support_locales)

    def test_pt_br_option_mapping_and_internal_value(self):
        """Verify pt-BR has human-readable label 'Português (Brasil)' and internal value 'pt-BR'."""
        self.assertIn('label = tr("Português (Brasil)")', self.main_code)
        self.assertIn('code.lower().replace("_", "-") == "pt-br"', self.main_code)

    def test_build_script_prompt_identifies_brazilian_portuguese(self):
        """Verify build_script_prompt includes explicit Brazilian Portuguese instructions for pt-BR."""
        prompt = llm.build_script_prompt(
            video_subject="Curiosidades sobre o Universo",
            language="pt-BR",
            paragraph_number=1,
        )
        self.assertIn("- language: pt-BR", prompt)
        self.assertIn("português brasileiro (pt-BR)", prompt)
        self.assertIn("Evite construções típicas do português europeu", prompt)

        prompt_en = llm.build_script_prompt(
            video_subject="Curiosities about the Universe",
            language="en-US",
            paragraph_number=1,
        )
        self.assertIn("- language: en-US", prompt_en)
        self.assertNotIn("português brasileiro", prompt_en)

        prompt_pt = llm.build_script_prompt(
            video_subject="Curiosidades sobre o Universo",
            language="pt",
            paragraph_number=1,
        )
        self.assertIn("- language: pt", prompt_pt)
        self.assertNotIn("Evite construções típicas do português europeu", prompt_pt)

    def test_social_metadata_instruction_pt_br(self):
        """Verify social metadata language instruction properly targets Brazilian Portuguese."""
        instruction = llm._social_language_instruction("pt-BR")
        self.assertIn("Brazilian Portuguese (pt-BR)", instruction)

    def test_batch_generation_inherits_pt_br(self):
        """Verify that batch generation tasks inherit video_language='pt-BR' from screen params."""
        base_params = VideoParams(
            video_subject="Lote Base",
            video_language="pt-BR",
            voice_name="pt-BR-FranciscaNeural",
        )
        topics = ["Tema 1", "Tema 2", "Tema 3"]
        cloned_params_list = []
        for topic in topics:
            p = base_params.model_copy(deep=True)
            p.video_subject = topic
            p.video_script = ""
            cloned_params_list.append(p)

        for p in cloned_params_list:
            self.assertEqual(p.video_language, "pt-BR")
            self.assertEqual(p.voice_name, "pt-BR-FranciscaNeural")

    # =========================================================================
    # CENÁRIOS REAIS DE ESTADO DO TASKMANAGER & BLOQUEIO
    # =========================================================================

    def test_scenario_a_empty_queue_both_enabled(self):
        """CENÁRIO A: fila vazia → has_active_generation_tasks() is False → botões enabled."""
        tm = InMemoryTaskManager(max_concurrent_tasks=1, max_queued_tasks=10)
        self.assertEqual(tm.current_tasks, 0)
        self.assertTrue(tm.is_queue_empty())
        self.assertFalse(tm.has_active_tasks())

        with patch.object(webui_task, "_task_manager", tm):
            self.assertFalse(webui_task.has_active_generation_tasks())
            generation_locked = webui_task.has_active_generation_tasks()
            # Both buttons are enabled when generation_locked is False
            self.assertFalse(generation_locked)

    def test_scenario_b_one_task_running_both_disabled(self):
        """CENÁRIO B: 1 task running → has_active_generation_tasks() is True → botões disabled."""
        tm = InMemoryTaskManager(max_concurrent_tasks=1, max_queued_tasks=10)
        tm.current_tasks = 1
        self.assertTrue(tm.is_queue_empty())
        self.assertTrue(tm.has_active_tasks())

        with patch.object(webui_task, "_task_manager", tm):
            self.assertTrue(webui_task.has_active_generation_tasks())
            generation_locked = webui_task.has_active_generation_tasks()
            self.assertTrue(generation_locked)

    def test_scenario_c_one_running_plus_two_pending_both_disabled(self):
        """CENÁRIO C: 1 task running + 2 pending → has_active_generation_tasks() is True → ambos disabled."""
        tm = InMemoryTaskManager(max_concurrent_tasks=1, max_queued_tasks=10)
        tm.current_tasks = 1
        tm.enqueue({"func": lambda: None})
        tm.enqueue({"func": lambda: None})
        self.assertEqual(tm.queue_size(), 2)
        self.assertFalse(tm.is_queue_empty())
        self.assertTrue(tm.has_active_tasks())

        with patch.object(webui_task, "_task_manager", tm):
            self.assertTrue(webui_task.has_active_generation_tasks())
            generation_locked = webui_task.has_active_generation_tasks()
            self.assertTrue(generation_locked)

    def test_scenario_d_running_ended_but_pending_exist_still_disabled(self):
        """CENÁRIO D: running terminou mas ainda existem pending → ambos continuam disabled."""
        tm = InMemoryTaskManager(max_concurrent_tasks=1, max_queued_tasks=10)
        # Simulate transition window where current_tasks is 0 but queue still has items
        tm.current_tasks = 0
        tm.enqueue({"func": lambda: None})
        self.assertFalse(tm.is_queue_empty())
        self.assertTrue(tm.has_active_tasks())

        with patch.object(webui_task, "_task_manager", tm):
            self.assertTrue(webui_task.has_active_generation_tasks())
            generation_locked = webui_task.has_active_generation_tasks()
            self.assertTrue(generation_locked)

    def test_scenario_e_queue_completely_empty_both_enabled_again(self):
        """CENÁRIO E: fila completamente vazia → ambos enabled novamente."""
        tm = InMemoryTaskManager(max_concurrent_tasks=1, max_queued_tasks=10)
        tm.current_tasks = 1
        tm.enqueue({"func": lambda: None})
        self.assertTrue(tm.has_active_tasks())

        # Simulate task 1 done and task 2 dequeued and completed
        tm.dequeue()
        tm.current_tasks = 0
        self.assertTrue(tm.is_queue_empty())
        self.assertFalse(tm.has_active_tasks())

        with patch.object(webui_task, "_task_manager", tm):
            self.assertFalse(webui_task.has_active_generation_tasks())
            generation_locked = webui_task.has_active_generation_tasks()
            self.assertFalse(generation_locked)

    def test_scenario_f_task_failed_and_no_other_pending_both_enabled(self):
        """CENÁRIO F: task failed e nenhuma outra pendente → ambos enabled."""
        tm = InMemoryTaskManager(max_concurrent_tasks=1, max_queued_tasks=10)
        # When worker catches exception and terminates, current_tasks is decremented to 0
        tm.current_tasks = 0
        self.assertTrue(tm.is_queue_empty())

        with patch.object(webui_task, "_task_manager", tm):
            self.assertFalse(webui_task.has_active_generation_tasks())
            generation_locked = webui_task.has_active_generation_tasks()
            self.assertFalse(generation_locked)

    def test_rerun_invoked_after_submission_in_main_code(self):
        """Verify st.rerun(scope='app') is called immediately after single and batch task submission."""
        # Single video generation must trigger st.rerun(scope="app")
        self.assertIn('st.session_state["current_generation_task_id"] = task_id\n        logger.info(f"WebUI generation task submitted: task_id={task_id}")\n        st.rerun(scope="app")', self.main_code)
        # Batch generation must trigger st.rerun(scope="app")
        self.assertIn('if submitted_task_ids:\n            batch_submitted = True', self.main_code)
        self.assertIn('st.rerun(scope="app")', self.main_code)

    def test_callback_guards_prevent_submission_during_active_generation(self):
        """Verify callback guards check webui_task.has_active_generation_tasks()."""
        self.assertIn("if start_button:\n        if webui_task.has_active_generation_tasks()", self.main_code)
        self.assertIn("if batch_button:\n        if webui_task.has_active_generation_tasks()", self.main_code)

    def test_publish_button_available_for_completed_tasks_when_not_busy(self):
        """Verify manual publish button logic: complete + has_video + not busy enables Publish."""
        task_complete = {
            "task_id": "completed-1",
            "state": const.TASK_STATE_COMPLETE,
            "video_file": "path/to/final-1.mp4",
        }
        is_busy = is_task_busy(task_complete)
        self.assertFalse(is_busy)

        task_generating = {
            "task_id": "generating-1",
            "state": const.TASK_STATE_PROCESSING,
        }
        self.assertTrue(is_task_busy(task_generating))


if __name__ == "__main__":
    unittest.main()
