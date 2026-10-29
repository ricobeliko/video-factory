"""Testes dos Controles de Agendamento e Publicação da API V2.

Valida:
1. PATCH /api/v2/scheduler/settings com dados válidos altera e persiste;
2. PATCH com campos não permitidos -> 400;
3. PATCH com valores não-booleanos -> 400;
4. PATCH sem campos -> 400;
5. PATCH em instância NÃO-PRIMARY -> 403;
6. POST /api/v2/scheduler/run-cycle em PRIMARY chama scheduler.run_scheduler_cycle e responde com resultado canônico;
7. POST /api/v2/scheduler/run-cycle em NÃO-PRIMARY -> 403;
8. POST /api/v2/scheduler/plan em PRIMARY chama scheduler.plan_schedule e responde com contagem;
9. POST /api/v2/scheduler/plan em NÃO-PRIMARY -> 403;
10. Auditoria: verifica que operator_events registra as ações operacionais.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import asgi
from app.config import config
from app.services import operator_console, scheduler


class TestApiV2SchedulerControls(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_v2_scheduler.db")
        config.app["api_key"] = ""

        # Inicializa tabelas
        scheduler.init_db(self.db_path)
        operator_console.init_operator_db(self.db_path)
        operator_console.reset_instance_for_testing()
        operator_console.ensure_instance_initialized(db_path=self.db_path)

        self.client = TestClient(asgi.app)

    def tearDown(self):
        operator_console.reset_instance_for_testing()
        config.app.clear()
        config.app.update(self.original_app_config)
        self.temp_dir.cleanup()

    def test_patch_scheduler_settings_valid_persists_and_audits(self):
        """1. PATCH /api/v2/scheduler/settings com dados válidos altera, persiste e gera auditoria."""
        with patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.is_primary_instance", return_value=True):

            payload = {
                "auto_publish_enabled": True,
                "scheduler_enabled": True,
                "dry_run": False,
            }
            res = self.client.patch("/api/v2/scheduler/settings", json=payload)
            self.assertEqual(res.status_code, 200, res.text)
            data = res.json().get("data", {})
            self.assertTrue(data.get("auto_publish_enabled"))
            self.assertTrue(data.get("scheduler_enabled"))
            self.assertFalse(data.get("dry_run"))

            # Verifica persistência no banco
            current = scheduler.get_all_settings(self.db_path)
            self.assertTrue(current.get("auto_publish_enabled"))
            self.assertTrue(current.get("scheduler_enabled"))
            self.assertFalse(current.get("dry_run"))

            # Verifica registro de auditoria em operational_events
            events = operator_console.get_operational_events(limit=20, db_path=self.db_path)
            sched_events = [e for e in events if e.get("event_type") == "SCHEDULER_SETTINGS_UPDATED"]
            self.assertTrue(len(sched_events) >= 1, "Evento de auditoria SCHEDULER_SETTINGS_UPDATED não encontrado")
            updated_fields = [e.get("metadata", {}).get("field") for e in sched_events]
            self.assertIn("auto_publish_enabled", updated_fields)
            self.assertIn("scheduler_enabled", updated_fields)
            self.assertIn("dry_run", updated_fields)

    def test_patch_scheduler_settings_extra_fields_returns_400(self):
        """2. PATCH com campos não permitidos -> 400."""
        with patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.is_primary_instance", return_value=True):

            payload = {
                "auto_publish_enabled": True,
                "unauthorized_field": "danger",
            }
            res = self.client.patch("/api/v2/scheduler/settings", json=payload)
            self.assertEqual(res.status_code, 400, res.text)

    def test_patch_scheduler_settings_non_boolean_returns_400(self):
        """3. PATCH com valores não-booleanos -> 400."""
        with patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.is_primary_instance", return_value=True):

            payload = {
                "auto_publish_enabled": "yes",  # String inválida onde espera bool estrito
            }
            res = self.client.patch("/api/v2/scheduler/settings", json=payload)
            self.assertEqual(res.status_code, 400, res.text)

    def test_patch_scheduler_settings_empty_payload_returns_400(self):
        """4. PATCH sem campos -> 400."""
        with patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.is_primary_instance", return_value=True):

            res = self.client.patch("/api/v2/scheduler/settings", json={})
            self.assertEqual(res.status_code, 400, res.text)

    def test_patch_scheduler_settings_non_primary_returns_403(self):
        """5. PATCH em instância NÃO-PRIMARY -> 403."""
        with patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.is_primary_instance", return_value=False):

            payload = {"dry_run": True}
            res = self.client.patch("/api/v2/scheduler/settings", json=payload)
            self.assertEqual(res.status_code, 403, res.text)

    def test_post_run_cycle_primary_calls_scheduler_and_audits(self):
        """6. POST /api/v2/scheduler/run-cycle em PRIMARY chama run_scheduler_cycle e gera auditoria."""
        mock_result = {
            "status": "published",
            "task_id": "test_task_123",
            "platform": "youtube",
            "post_id": 42,
        }
        with patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.is_primary_instance", return_value=True), \
             patch("app.services.scheduler.run_scheduler_cycle", return_value=mock_result) as mock_cycle:

            res = self.client.post("/api/v2/scheduler/run-cycle")
            self.assertEqual(res.status_code, 200, res.text)
            mock_cycle.assert_called_once()
            data = res.json().get("data", {})
            self.assertEqual(data.get("status"), "published")
            self.assertEqual(data.get("task_id"), "test_task_123")

            # Verifica auditoria
            events = operator_console.get_operational_events(limit=20, db_path=self.db_path)
            cycle_events = [e for e in events if e.get("event_type") == "SCHEDULER_CYCLE_TRIGGERED"]
            self.assertTrue(len(cycle_events) >= 1)

    def test_post_run_cycle_non_primary_returns_403(self):
        """7. POST /api/v2/scheduler/run-cycle em NÃO-PRIMARY -> 403."""
        with patch("app.services.operator_console.is_primary_instance", return_value=False):
            res = self.client.post("/api/v2/scheduler/run-cycle")
            self.assertEqual(res.status_code, 403, res.text)

    def test_post_plan_primary_calls_plan_and_audits(self):
        """8. POST /api/v2/scheduler/plan em PRIMARY chama scheduler.plan_schedule e gera auditoria."""
        with patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.is_primary_instance", return_value=True), \
             patch("app.services.scheduler.plan_schedule", return_value=3) as mock_plan, \
             patch("app.services.scheduler.replan_future_schedule_for_growth_mode", return_value=2) as mock_replan:

            res = self.client.post("/api/v2/scheduler/plan")
            self.assertEqual(res.status_code, 200, res.text)
            mock_plan.assert_called_once()
            mock_replan.assert_called_once()
            data = res.json().get("data", {})
            self.assertEqual(data.get("planned_count"), 3)
            self.assertEqual(data.get("adjusted_count"), 2)

            # Verifica auditoria
            events = operator_console.get_operational_events(limit=20, db_path=self.db_path)
            plan_events = [e for e in events if e.get("event_type") == "SCHEDULE_PLANNED"]
            self.assertTrue(len(plan_events) >= 1)

    def test_post_plan_non_primary_returns_403(self):
        """9. POST /api/v2/scheduler/plan em NÃO-PRIMARY -> 403."""
        with patch("app.services.operator_console.is_primary_instance", return_value=False):
            res = self.client.post("/api/v2/scheduler/plan")
            self.assertEqual(res.status_code, 403, res.text)
