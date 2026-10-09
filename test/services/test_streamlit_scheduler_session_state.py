import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.services import scheduler
import webui.Main as main_module


class TestStreamlitSchedulerSessionState(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_video_factory.db")
        scheduler.init_db(self.db_path)

        # Configurações iniciais conhecidas no banco de teste
        scheduler.set_setting("scheduler_enabled", False, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", False, db_path=self.db_path)
        scheduler.set_setting("dry_run", True, db_path=self.db_path)

        # Mock de Streamlit para simular render da UI
        self.session_state = {}
        self.mock_st = MagicMock()
        self.mock_st.session_state = self.session_state

        def fake_columns(spec, **kwargs):
            n = spec if isinstance(spec, int) else len(spec)
            cols = []
            for _ in range(n):
                col = MagicMock()
                col.__enter__ = MagicMock(return_value=col)
                col.__exit__ = MagicMock(return_value=None)
                cols.append(col)
            return cols

        self.mock_st.columns.side_effect = fake_columns
        self.mock_st.selectbox.side_effect = lambda *args, **kwargs: kwargs.get("options", ["warmup"])[kwargs.get("index", 0)]

    def tearDown(self):
        import gc
        gc.collect()
        self.temp_dir.cleanup()

    def _render(self):
        """Executa _render_publication_schedule isolando worker e banco de dados."""
        func = getattr(main_module._render_publication_schedule, "__wrapped__", main_module._render_publication_schedule)
        with patch.object(scheduler, "get_db_path", return_value=self.db_path), \
             patch.object(scheduler, "start_scheduler_worker"), \
             patch.object(scheduler, "plan_schedule", return_value=[]), \
             patch.object(main_module, "st", self.mock_st):
            func()

    def test_01_stale_scheduler_session_true_db_false(self):
        """Caso 1: stale session True, DB False -> DB continua False."""
        # DB canônico está False
        self.assertFalse(scheduler.get_all_settings(db_path=self.db_path)["scheduler_enabled"])

        # Session state contém resíduo antigo True
        self.session_state["scheduler_enabled_cb"] = True

        with patch.object(scheduler, "get_db_path", return_value=self.db_path), \
             patch.object(scheduler, "set_setting", wraps=scheduler.set_setting) as spy_set:
            self._render()

            # scheduler.set_setting NÃO pode ter sido chamado para scheduler_enabled
            for call_args in spy_set.call_args_list:
                self.assertNotEqual(
                    call_args[0][0],
                    "scheduler_enabled",
                    "scheduler.set_setting foi chamado indevidamente no render!",
                )

        # DB permanece False
        db_settings = scheduler.get_all_settings(db_path=self.db_path)
        self.assertFalse(db_settings["scheduler_enabled"])

        # Widget state foi sincronizado para False
        self.assertFalse(self.session_state["scheduler_enabled_cb"])

    def test_02_stale_auto_publish_session_true_db_false(self):
        """Caso 2: stale Auto Publish True, DB False -> DB continua False."""
        # DB canônico está False
        self.assertFalse(scheduler.get_all_settings(db_path=self.db_path)["auto_publish_enabled"])

        # Session state contém resíduo antigo True
        self.session_state["scheduler_auto_publish_cb"] = True

        with patch.object(scheduler, "get_db_path", return_value=self.db_path), \
             patch.object(scheduler, "set_setting", wraps=scheduler.set_setting) as spy_set:
            self._render()

            # scheduler.set_setting NÃO pode ter sido chamado para auto_publish_enabled
            for call_args in spy_set.call_args_list:
                self.assertNotEqual(
                    call_args[0][0],
                    "auto_publish_enabled",
                    "scheduler.set_setting foi chamado indevidamente no render!",
                )

        # DB permanece False
        db_settings = scheduler.get_all_settings(db_path=self.db_path)
        self.assertFalse(db_settings["auto_publish_enabled"])

        # Widget state foi sincronizado para False
        self.assertFalse(self.session_state["scheduler_auto_publish_cb"])

    def test_03_stale_dry_run_session_divergent(self):
        """Caso 3: stale Dry Run divergente -> DB não é alterado."""
        # Cenário 3A: DB True, stale session False
        scheduler.set_setting("dry_run", True, db_path=self.db_path)
        self.session_state["scheduler_dry_run_cb"] = False

        with patch.object(scheduler, "get_db_path", return_value=self.db_path), \
             patch.object(scheduler, "set_setting", wraps=scheduler.set_setting) as spy_set:
            self._render()

            for call_args in spy_set.call_args_list:
                self.assertNotEqual(
                    call_args[0][0],
                    "dry_run",
                    "scheduler.set_setting foi chamado indevidamente no render!",
                )

        db_settings = scheduler.get_all_settings(db_path=self.db_path)
        self.assertTrue(db_settings["dry_run"])
        self.assertTrue(self.session_state["scheduler_dry_run_cb"])

        # Cenário 3B: DB False, stale session True
        scheduler.set_setting("dry_run", False, db_path=self.db_path)
        self.session_state["scheduler_dry_run_cb"] = True

        with patch.object(scheduler, "get_db_path", return_value=self.db_path), \
             patch.object(scheduler, "set_setting", wraps=scheduler.set_setting) as spy_set:
            self._render()

            for call_args in spy_set.call_args_list:
                self.assertNotEqual(
                    call_args[0][0],
                    "dry_run",
                    "scheduler.set_setting foi chamado indevidamente no render!",
                )

        db_settings = scheduler.get_all_settings(db_path=self.db_path)
        self.assertFalse(db_settings["dry_run"])
        self.assertFalse(self.session_state["scheduler_dry_run_cb"])

    def test_04_explicit_user_interaction_persists_settings(self):
        """Caso 4: interação explícita do usuário -> setting é persistido."""
        with patch.object(scheduler, "get_db_path", return_value=self.db_path), \
             patch.object(main_module, "st", self.mock_st):

            # 4A: Usuário clica Scheduler Enabled -> ON
            self.session_state["scheduler_enabled_cb"] = True
            main_module._on_scheduler_enabled_changed()
            self.assertTrue(scheduler.get_all_settings(db_path=self.db_path)["scheduler_enabled"])

            # Usuário clica Scheduler Enabled -> OFF
            self.session_state["scheduler_enabled_cb"] = False
            main_module._on_scheduler_enabled_changed()
            self.assertFalse(scheduler.get_all_settings(db_path=self.db_path)["scheduler_enabled"])

            # 4B: Usuário clica Auto Publish -> ON
            self.session_state["scheduler_auto_publish_cb"] = True
            main_module._on_auto_publish_enabled_changed()
            self.assertTrue(scheduler.get_all_settings(db_path=self.db_path)["auto_publish_enabled"])

            # 4C: Usuário clica Dry Run -> OFF (produção real)
            self.session_state["scheduler_dry_run_cb"] = False
            main_module._on_dry_run_changed()
            self.assertFalse(scheduler.get_all_settings(db_path=self.db_path)["dry_run"])

    def test_05_render_without_interaction_causes_no_writes(self):
        """Caso 5: reruns periódicos sem interação -> nenhuma escrita operacional indevida."""
        # Estado DB conhecido
        scheduler.set_setting("scheduler_enabled", False, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", False, db_path=self.db_path)
        scheduler.set_setting("dry_run", True, db_path=self.db_path)

        # Session state inicializado
        self.session_state["scheduler_enabled_cb"] = False
        self.session_state["scheduler_auto_publish_cb"] = False
        self.session_state["scheduler_dry_run_cb"] = True

        with patch.object(scheduler, "get_db_path", return_value=self.db_path), \
             patch.object(scheduler, "set_setting", wraps=scheduler.set_setting) as spy_set:

            # 10 renders consecutivos (simulando fragment run_every="10s")
            for _ in range(10):
                self._render()

            # Nenhuma chamada de escrita para nenhum dos 3 settings operacionais
            operational_keys = {"scheduler_enabled", "auto_publish_enabled", "dry_run"}
            for call_args in spy_set.call_args_list:
                key_called = call_args[0][0]
                self.assertNotIn(
                    key_called,
                    operational_keys,
                    f"scheduler.set_setting('{key_called}') foi chamado indevidamente durante render sem interação!",
                )

        # Estado do DB permanece exatamente intacto
        final_settings = scheduler.get_all_settings(db_path=self.db_path)
        self.assertFalse(final_settings["scheduler_enabled"])
        self.assertFalse(final_settings["auto_publish_enabled"])
        self.assertTrue(final_settings["dry_run"])
