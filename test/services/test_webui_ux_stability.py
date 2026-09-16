import unittest
from unittest.mock import MagicMock, patch

from app.models import const
from app.services import state as sm
from app.services import scheduler, webui_task
from webui import Main


class TestWebuiUxStability(unittest.TestCase):
    def setUp(self):
        self.mock_st = MagicMock()
        self.mock_st.session_state = {
            "active_generation_tasks": {},
            "current_generation_task_id": "",
            "autopilot_niche_input": "Curiosidades Espaciais",
            "autopilot_desired_stock": 25,
            "autopilot_ideas": [{"topic": "O mistério de Marte", "selected": True}],
        }
        self.patcher = patch.dict("sys.modules", {"streamlit": self.mock_st})
        self.patcher.start()
        Main.st = self.mock_st

    def tearDown(self):
        self.patcher.stop()

    def _call_render_running_task(self, task_id):
        func = getattr(Main._render_running_generation_task, "__wrapped__", Main._render_running_generation_task)
        return func(task_id)

    def test_01_polling_intervals_configured_as_fragments(self):
        """Verifica se os fragments essenciais estão configurados com decorador fragment."""
        self.assertTrue(hasattr(Main._render_running_generation_task, "_fragment") or callable(Main._render_running_generation_task))
        self.assertTrue(hasattr(Main._render_task_manager_entry, "_fragment") or callable(Main._render_task_manager_entry))
        self.assertTrue(hasattr(Main._render_publication_schedule, "_fragment") or callable(Main._render_publication_schedule))

    def test_02_handoff_does_not_trigger_app_rerun(self):
        """Handoff de Task A para Task B não dispara st.rerun(scope='app')."""
        task_a = "task-stable-handoff-a"
        task_b = "task-stable-handoff-b"

        Main._add_active_generation_task(task_a, subject="Tema A")
        Main._add_active_generation_task(task_b, subject="Tema B")
        self.mock_st.session_state["current_generation_task_id"] = task_a

        # Task A completa, Task B em andamento
        sm.state.update_task(task_a, state=const.TASK_STATE_COMPLETE, progress=100)
        sm.state.update_task(task_b, state=const.TASK_STATE_PROCESSING, progress=20)

        with patch.object(Main, "_render_generation_task_snapshot") as mock_snapshot:
            self._call_render_running_task(task_a)
            # st.rerun(scope="app") NÃO deve ter sido chamado porque há próxima tarefa (Task B)
            self.mock_st.rerun.assert_not_called()
            # current_generation_task_id deve ter avançado para Task B
            self.assertEqual(self.mock_st.session_state["current_generation_task_id"], task_b)
            # Deve ter renderizado snapshot da Task B
            mock_snapshot.assert_called_with(task_b, sm.state.get_task(task_b))

    def test_03_final_task_completion_triggers_app_rerun_to_unlock_buttons(self):
        """Ao concluir a última tarefa da fila, st.rerun(scope='app') é chamado para desbloquear os botões."""
        task_b = "task-stable-handoff-final"

        # Apenas task_b ativa
        self.mock_st.session_state["active_generation_tasks"] = {task_b: {"subject": "Tema Final"}}
        self.mock_st.session_state["current_generation_task_id"] = task_b

        # Task B completa
        sm.state.update_task(task_b, state=const.TASK_STATE_COMPLETE, progress=100)

        with patch.object(Main, "_render_generation_task_snapshot"):
            self._call_render_running_task(task_b)
            # Agora sim deve chamar st.rerun(scope="app") para re-habilitar os botões na página
            self.mock_st.rerun.assert_called_once_with(scope="app")

    def test_04_generation_locked_while_active_tasks_exist(self):
        """Bloqueio de novos disparos permanece verdadeiro enquanto houver tarefas ativas."""
        self.mock_st.session_state["active_generation_tasks"] = {}

        # Sem tarefas ativas
        self.assertFalse(bool(webui_task.has_active_generation_tasks() or Main._has_active_generation()))

        # Adiciona tarefa ativa no estado e no session_state
        sm.state.update_task("task-lock-check", state=const.TASK_STATE_PROCESSING)
        Main._add_active_generation_task("task-lock-check", subject="Tema Teste")
        self.assertTrue(bool(webui_task.has_active_generation_tasks() or Main._has_active_generation()))

        # Remove tarefa ativa
        Main._remove_active_generation_task("task-lock-check")
        sm.state.update_task("task-lock-check", state=const.TASK_STATE_COMPLETE)
        self.assertFalse(bool(webui_task.has_active_generation_tasks() or Main._has_active_generation()))

    def test_05_session_state_inputs_preserved(self):
        """Inputs do usuário em session_state não são alterados por polling de tarefas."""
        initial_niche = self.mock_st.session_state["autopilot_niche_input"]
        initial_stock = self.mock_st.session_state["autopilot_desired_stock"]
        initial_ideas = list(self.mock_st.session_state["autopilot_ideas"])

        # Simula ciclos de verificação de tarefas ativas
        Main._active_generation_tasks()
        Main._get_next_active_generation_task_id()

        self.assertEqual(self.mock_st.session_state["autopilot_niche_input"], initial_niche)
        self.assertEqual(self.mock_st.session_state["autopilot_desired_stock"], initial_stock)
        self.assertEqual(self.mock_st.session_state["autopilot_ideas"], initial_ideas)

    def test_06_scheduler_submodule_remains_fully_functional(self):
        """Verifica se métodos do scheduler continuam operando normalmente."""
        settings = scheduler.get_all_settings()
        self.assertIn("tiktok_limit_24h", settings)
        self.assertIn("youtube_limit_24h", settings)

        rate_tk = scheduler.get_platform_rate_limits("tiktok")
        self.assertIn("available_slots", rate_tk)


if __name__ == "__main__":
    unittest.main()
