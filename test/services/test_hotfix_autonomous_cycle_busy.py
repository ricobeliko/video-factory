# -*- coding: utf-8 -*-
"""
test/services/test_hotfix_autonomous_cycle_busy.py
==================================================
Validação do hotfix consolidado de produção autônoma:
1. Contrato estruturado de busy (reason e message presentes em ambos os casos).
2. Eliminação do UnboundLocalError em rejected_struct para formatos fixos.
3. Reconciliação não-destrutiva de tarefas órfãs com final-1.mp4.
"""

import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from app.services import autonomous_production, operator_console, profile_manager, scheduler
from app.models import const


class TestHotfixAutonomousCycleBusy(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_hotfix.db")
        scheduler.init_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        operator_console.init_operator_db(self.db_path)

        # Registra lock primário para permitir execução de ciclos
        operator_console.acquire_instance_lock(db_path=self.db_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_cycle_lock_busy_returns_structured_contract(self):
        """1. Quando _cycle_lock está retido, run_autonomous_cycle retorna status busy, reason e message claros."""
        with autonomous_production._cycle_lock:
            result = autonomous_production.run_autonomous_cycle(
                force=True,
                one_shot=True,
                db_path=self.db_path,
            )

        self.assertEqual(result.get("status"), "busy")
        self.assertEqual(result.get("reason"), "cycle_in_progress")
        self.assertIsNotNone(result.get("message"))
        self.assertIn("já em execução", result.get("message"))

    def test_active_tasks_busy_returns_structured_contract(self):
        """2. Quando há tarefas ativas de geração, o retorno de busy inclui reason='active_tasks_generating' e message."""
        with patch("app.services.webui_task.has_active_generation_tasks", return_value=True), \
             patch("app.services.webui_task.get_active_task_ids", return_value=["task-abc-123"]):
            result = autonomous_production.run_autonomous_cycle(
                force=True,
                one_shot=True,
                db_path=self.db_path,
            )

        self.assertEqual(result.get("status"), "busy")
        self.assertEqual(result.get("reason"), "active_tasks_generating")
        self.assertIsNotNone(result.get("message"))
        self.assertIn("Geração em andamento", result.get("message"))
        self.assertIn("task-abc-123", result.get("message"))

    def test_fixed_format_does_not_raise_unbound_local_error(self):
        """3. Para canal com formato fixo (quiz_dilemma), rejected_struct inicializada previne UnboundLocalError."""
        # Cria perfil com formato fixo
        prof = profile_manager.create_profile(
            name="Canal Quiz",
            niche="Curiosidades",
            db_path=self.db_path,
        )
        pid = prof["id"]

        # Configura formato fixo na seção editorial do perfil
        ws_settings = profile_manager.get_profile_settings(pid, db_path=self.db_path)
        ws_dict = ws_settings.model_dump()
        ws_dict["editorial"]["video_format"] = "quiz_dilemma"
        profile_manager.update_profile_settings(pid, ws_dict, db_path=self.db_path)

        # Mock das dependências para testar a seleção de estrutura narrativa sem gerar mídia real
        candidate = {"topic": "Você prefere A ou B?", "trend_id": "tr-1"}
        with patch("app.services.autonomous_production.discover_candidate_topic", return_value=candidate), \
             patch("app.services.autonomous_production.resolve_autonomous_youtube_channel", return_value="yt-1"), \
             patch("app.services.autonomous_production.check_required_providers_preflight", return_value=(True, "", {})), \
             patch("app.services.webui_task.submit_generation") as mock_submit:

            # Executa ciclo: não deve lançar UnboundLocalError
            try:
                result = autonomous_production.run_autonomous_cycle(
                    force=True,
                    one_shot=True,
                    profile_id=pid,
                    db_path=self.db_path,
                )
            except UnboundLocalError as err:
                self.fail(f"UnboundLocalError foi lançado: {err}")

            # Verifica que o ciclo submeteu com a estrutura correta fixada
            last_st = autonomous_production.get_channel_last_narrative_structure(pid, "yt-1", db_path=self.db_path)
            self.assertEqual(last_st, "quiz_dilemma")
            self.assertTrue(mock_submit.called)

    def test_orphaned_tasks_reconciled_on_cycle_start(self):
        """4. Tarefas órfãs com final-1.mp4 são reconciliadas para COMPLETE no início do ciclo."""
        from app.services import state as sm
        task_dir = os.path.join(self.tmp_dir.name, "task-orphan-1")
        os.makedirs(task_dir, exist_ok=True)
        final_mp4 = os.path.join(task_dir, "final-1.mp4")
        with open(final_mp4, "wb") as f:
            f.write(b"fake mp4 video bytes")

        sm.state.update_task(
            "task-orphan-1",
            state=const.TASK_STATE_PROCESSING,
            progress=50,
        )

        with patch("app.services.webui_task.get_active_task_ids", return_value=[]), \
             patch("app.services.autonomous_production.discover_candidate_topic", return_value=None), \
             patch("app.utils.utils.task_dir", return_value=self.tmp_dir.name):
            # Executa ciclo: deve reconciliar e parar em no_candidate sem gerar tasks extras
            autonomous_production.run_autonomous_cycle(
                force=True,
                one_shot=True,
                db_path=self.db_path,
                task_base_dir=self.tmp_dir.name,
            )

        # Verifica se task-orphan-1 foi reconciliada para COMPLETE
        task_info = sm.state.get_task("task-orphan-1")
        self.assertEqual(task_info.get("state"), const.TASK_STATE_COMPLETE)
        self.assertEqual(task_info.get("progress"), 100)


if __name__ == "__main__":
    unittest.main()
