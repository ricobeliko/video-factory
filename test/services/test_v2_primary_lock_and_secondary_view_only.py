"""Testes de Garantia do Lock PRIMARY e Proteção Fail-Closed VIEW-ONLY no Motor V2.

Valida que:
1. Instância PRIMARY opera com sucesso total (PATCH /api/v2/scheduler/settings e rotas
   mutantes retornam HTTP 200; /api/v2/health reporta role='PRIMARY' e is_primary=True);
2. Instância SECONDARY_VIEW_ONLY é bloqueada em operações de escrita (PATCH retorna HTTP 403;
   /api/v2/health reporta role='SECONDARY_VIEW_ONLY' e is_primary=False);
3. O boot do motor unificado (engine_entrypoint.bootstrap_engine) aborta imediatamente
   retornando (False, None) quando outra instância ativa é o PRIMARY (fail-closed, sem abrir porta);
4. O boot é bem sucedido quando o lock é adquirido com papel PRIMARY.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

from app import asgi
from app.config import config
from app.services import operator_console, profile_manager, scheduler
from scripts import engine_entrypoint


class TestV2PrimaryLockAndSecondaryViewOnly(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_primary_lock.db")
        config.app["api_key"] = ""

        # Inicializa tabelas
        scheduler.init_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        profile_manager.ensure_default_profile(self.db_path)
        operator_console.init_operator_db(self.db_path)

        operator_console.reset_instance_for_testing()
        self.client = TestClient(asgi.app)

    def tearDown(self):
        operator_console.reset_instance_for_testing()
        config.app.clear()
        config.app.update(self.original_app_config)
        self.temp_dir.cleanup()

    def test_primary_instance_allows_patch_mutations_and_reports_primary(self):
        """PRIMARY adquire lock, reporta role=PRIMARY em /health e permite mutações PATCH (200)."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path):

            role, info = operator_console.ensure_instance_initialized(
                node_name="PrimaryTestNode", db_path=self.db_path
            )
            self.assertEqual(role, operator_console.ROLE_PRIMARY)
            self.assertTrue(operator_console.is_primary_instance(db_path=self.db_path))

            # Valida GET /api/v2/health
            resp_health = self.client.get("/api/v2/health")
            self.assertEqual(resp_health.status_code, 200)
            health_data = resp_health.json().get("data", {})
            self.assertEqual(health_data.get("status"), "healthy")
            self.assertEqual(health_data.get("role"), operator_console.ROLE_PRIMARY)
            self.assertEqual(health_data.get("is_primary"), True)

            # Valida PATCH /api/v2/scheduler/settings
            resp_patch = self.client.patch(
                "/api/v2/scheduler/settings",
                json={"auto_publish_enabled": True},
            )
            self.assertEqual(resp_patch.status_code, 200)
            body = resp_patch.json()
            self.assertEqual(body.get("status"), 200)
            self.assertEqual(body.get("data", {}).get("auto_publish_enabled"), True)

            # Valida PATCH /api/v2/channels/default/quotas
            resp_quotas = self.client.patch(
                "/api/v2/channels/default/quotas",
                json={"target_ready_stock": 7},
            )
            self.assertEqual(resp_quotas.status_code, 200)

    def test_secondary_instance_returns_403_and_blocks_mutations(self):
        """SECONDARY_VIEW_ONLY reporta role=SECONDARY em /health e bloqueia PATCH com 403."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path):

            # Força o papel da instância local para SECONDARY_VIEW_ONLY
            operator_console._current_role = operator_console.ROLE_SECONDARY_VIEW_ONLY
            operator_console._instance_initialized = True

            self.assertFalse(operator_console.is_primary_instance(db_path=self.db_path))
            with self.assertRaises(PermissionError):
                operator_console.require_primary_instance(db_path=self.db_path)

            # Valida GET /api/v2/health
            resp_health = self.client.get("/api/v2/health")
            self.assertEqual(resp_health.status_code, 200)
            health_data = resp_health.json().get("data", {})
            self.assertEqual(health_data.get("status"), "healthy")
            self.assertEqual(health_data.get("role"), operator_console.ROLE_SECONDARY_VIEW_ONLY)
            self.assertEqual(health_data.get("is_primary"), False)

            # Valida bloqueio de mutações com HTTP 403
            resp_patch_settings = self.client.patch(
                "/api/v2/scheduler/settings",
                json={"auto_publish_enabled": True},
            )
            self.assertEqual(resp_patch_settings.status_code, 403)
            self.assertIn("only primary instance", resp_patch_settings.json().get("message", ""))

            resp_patch_quotas = self.client.patch(
                "/api/v2/channels/default/quotas",
                json={"target_ready_stock": 10},
            )
            self.assertEqual(resp_patch_quotas.status_code, 403)
            self.assertIn("only primary instance", resp_patch_quotas.json().get("message", ""))

    def test_engine_bootstrap_aborts_fail_closed_if_secondary(self):
        """bootstrap_engine retorna (False, None) se não conseguir adquirir PRIMARY."""
        with patch("app.services.operator_console.ensure_instance_initialized", return_value=(
            operator_console.ROLE_SECONDARY_VIEW_ONLY,
            {"node_name": "ActivePrimary", "pid": 9999},
        )):
            ok, watchdog = engine_entrypoint.bootstrap_engine(
                enable_worker=True,
                lock_wait_seconds=0,
                db_path=self.db_path,
            )
            self.assertFalse(ok)
            self.assertIsNone(watchdog)

    def test_engine_bootstrap_succeeds_when_primary_lock_acquired(self):
        """bootstrap_engine retorna (True, watchdog/None) quando adquire PRIMARY."""
        with patch("app.services.operator_console.ensure_instance_initialized", return_value=(
            operator_console.ROLE_PRIMARY,
            {"node_name": "NewPrimary", "pid": 1111},
        )), \
             patch("app.services.task.recover_interrupted_cross_posts", return_value=[]), \
             patch("app.services.operator_console.reconcile_orphaned_tasks", return_value=[]):
            ok, watchdog = engine_entrypoint.bootstrap_engine(
                enable_worker=False,
                lock_wait_seconds=0,
                db_path=self.db_path,
            )
            self.assertTrue(ok)
            self.assertIsNone(watchdog)


if __name__ == "__main__":
    unittest.main()
