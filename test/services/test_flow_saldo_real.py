"""
test/services/test_flow_saldo_real.py
======================================
Testes direcionados da Missão v2/flow-saldo-real:
1. Reconciliação grava FLOW_UI_VERIFIED com timestamp e zera credits_used_since_verified.
2. refresh_account_credits e refresh_all_accounts_credits atualizam contas no runtime.
3. Endpoints de API V2 (/api/v2/flow/accounts/refresh e /api/v2/flow/accounts/{aid}/refresh).
4. Créditos insuficientes (< custo) => preflight bloqueia com mensagem clara.
5. Créditos suficientes (>= custo) => preflight aprova e ciclo segue normalmente.
6. Formatos sem Flow (flow_enabled=False) operam normalmente sem checar créditos Flow.
7. Créditos insuficientes no ciclo autônomo => canal entra em espera (STATE_BLOCKED),
   SEM criar tarefa, SEM registrar falha de geração (zero tentativas consumidas), SEM publicar.
"""

from datetime import datetime, timezone
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.services import flow_account_pool as fap
from app.services import autonomous_production as ap
from app import asgi
from fastapi.testclient import TestClient


class TestFlowSaldoReal(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.test_dir, "flow_accounts.json")
        self.runtime_path = os.path.join(self.test_dir, "flow_accounts_runtime.json")

        self.mock_config = {
            "schema_version": 1,
            "accounts": [
                {
                    "account_id": "flow-primary",
                    "display_name": "Flow Primary",
                    "enabled": True,
                    "priority": 100,
                    "user_data_dir": os.path.join(self.test_dir, "p1"),
                },
                {
                    "account_id": "flow-b",
                    "display_name": "Conta B",
                    "enabled": True,
                    "priority": 90,
                    "user_data_dir": os.path.join(self.test_dir, "p2"),
                },
                {
                    "account_id": "flow-c",
                    "display_name": "Conta C",
                    "enabled": True,
                    "priority": 80,
                    "user_data_dir": os.path.join(self.test_dir, "p3"),
                },
            ],
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.mock_config, f)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_record_verified_credit_balance_records_ui_verified(self):
        """1. Reconciliação grava FLOW_UI_VERIFIED com timestamp ISO recente e zera credits_used_since_verified."""
        # Salva estado verificado inicial
        fap.record_verified_credit_balance("flow-primary", 100, runtime_path=self.runtime_path)
        # Dedução local muda fonte para LOCAL_ESTIMATE
        fap.record_credit_deduction("flow-primary", 15, runtime_path=self.runtime_path)
        rt_before = fap.get_account_runtime("flow-primary", runtime_path=self.runtime_path)
        self.assertEqual(rt_before["credits_source"], fap.CREDIT_SOURCE_LOCAL_ESTIMATE)
        self.assertEqual(rt_before["credits_remaining"], 85)
        self.assertEqual(rt_before["credits_used_since_verified"], 15)

        # Reconcilia com saldo real lido na UI
        rt_after = fap.record_verified_credit_balance("flow-primary", 116, runtime_path=self.runtime_path)

        self.assertEqual(rt_after["credits_remaining"], 116)
        self.assertEqual(rt_after["credits_source"], fap.CREDIT_SOURCE_FLOW_UI_VERIFIED)
        self.assertEqual(rt_after["credits_used_since_verified"], 0)
        self.assertIsNotNone(rt_after["credits_last_verified_at"])
        dt_verified = datetime.fromisoformat(rt_after["credits_last_verified_at"])
        self.assertLess((datetime.now(timezone.utc) - dt_verified).total_seconds(), 10.0)
        self.assertEqual(rt_after["status"], fap.STATUS_AVAILABLE)

    def test_02_refresh_account_credits_updates_from_ui(self):
        """2. refresh_account_credits chama verificação e atualiza conta para FLOW_UI_VERIFIED."""
        mock_verify_res = {
            "account_id": "flow-b",
            "login_status": "AUTHENTICATED",
            "credits_remaining": 52,
            "credits_source": fap.CREDIT_SOURCE_FLOW_UI_VERIFIED,
            "message": None,
        }
        with patch("app.services.flow_account_pool.verify_flow_account_session", return_value=mock_verify_res):
            res = fap.refresh_account_credits(
                "flow-b",
                force=True,
                config_path=self.config_path,
                runtime_path=self.runtime_path,
            )

        self.assertTrue(res["success"])
        self.assertEqual(res["credits_remaining"], 52)
        self.assertEqual(res["credits_source"], fap.CREDIT_SOURCE_FLOW_UI_VERIFIED)

        rt = fap.get_account_runtime("flow-b", runtime_path=self.runtime_path)
        self.assertEqual(rt["credits_remaining"], 52)
        self.assertEqual(rt["credits_source"], fap.CREDIT_SOURCE_FLOW_UI_VERIFIED)

    def test_03_refresh_all_accounts_credits(self):
        """3. refresh_all_accounts_credits reconcilia todas as contas cadastradas."""
        def mock_verify_side_effect(aid, config_path=None, runtime_path=None):
            balances = {"flow-primary": 116, "flow-b": 52, "flow-c": 50}
            return {
                "account_id": aid,
                "login_status": "AUTHENTICATED",
                "credits_remaining": balances.get(aid, 0),
                "credits_source": fap.CREDIT_SOURCE_FLOW_UI_VERIFIED,
                "message": None,
            }

        with patch("app.services.flow_account_pool.verify_flow_account_session", side_effect=mock_verify_side_effect):
            results = fap.refresh_all_accounts_credits(
                force=True,
                config_path=self.config_path,
                runtime_path=self.runtime_path,
            )

        self.assertIn("flow-primary", results)
        self.assertIn("flow-b", results)
        self.assertIn("flow-c", results)
        self.assertEqual(results["flow-primary"]["credits_remaining"], 116)
        self.assertEqual(results["flow-b"]["credits_remaining"], 52)
        self.assertEqual(results["flow-c"]["credits_remaining"], 50)

    def test_04_flow_api_endpoints_refresh(self):
        """4. Endpoints de API V2 disparam reconciliação e retornam 200 com payload atualizado."""
        client = TestClient(asgi.app)

        mock_one = {
            "account_id": "flow-b",
            "refreshed": True,
            "success": True,
            "credits_remaining": 52,
            "credits_source": fap.CREDIT_SOURCE_FLOW_UI_VERIFIED,
            "message": "Saldo atualizado: 52 créditos.",
        }
        mock_all = {
            "flow-primary": {"account_id": "flow-primary", "credits_remaining": 116},
            "flow-b": {"account_id": "flow-b", "credits_remaining": 52},
            "flow-c": {"account_id": "flow-c", "credits_remaining": 50},
        }

        with patch("app.services.operator_console.refresh_flow_account_credits_op", return_value=mock_one), \
             patch("app.services.operator_console.refresh_all_flow_accounts_credits_op", return_value=mock_all):

            # POST conta específica
            res_one = client.post("/api/v2/flow/accounts/flow-b/refresh")
            self.assertEqual(res_one.status_code, 200)
            data_one = res_one.json()
            payload_one = data_one.get("data", data_one)
            self.assertEqual(payload_one["credits_remaining"], 52)

            # POST todas
            res_all = client.post("/api/v2/flow/accounts/refresh")
            self.assertEqual(res_all.status_code, 200)
            data_all = res_all.json()
            payload_all = data_all.get("data", data_all)
            self.assertIn("flow-primary", payload_all)
            self.assertIn("flow-b", payload_all)
            self.assertIn("flow-c", payload_all)

    def test_05_preflight_blocks_when_flow_credits_insufficient(self):
        """5. Preflight bloqueia com mensagem clara quando créditos Flow são insuficientes para as cenas."""
        fap.record_verified_credit_balance("flow-primary", 10, runtime_path=self.runtime_path)
        fap.record_verified_credit_balance("flow-b", 10, runtime_path=self.runtime_path)
        fap.record_verified_credit_balance("flow-c", 10, runtime_path=self.runtime_path)

        with patch("app.services.flow_account_pool.DEFAULT_CONFIG_PATH", self.config_path), \
             patch("app.services.flow_account_pool.DEFAULT_RUNTIME_PATH", self.runtime_path), \
             patch("app.utils.utils.check_ffmpeg_ready", return_value=True), \
             patch("app.services.material.has_material_api_keys", return_value=True), \
             patch("shutil.disk_usage", return_value=(100, 50, 10 * (1024 ** 3))), \
             patch("app.models.llm_provider.get_llm_provider") as mock_llm_prov:

            mock_spec = MagicMock()
            mock_spec.requires_api_key = False
            mock_llm_prov.return_value = mock_spec

            ok, msg, details = ap.check_required_providers_preflight(
                video_source="pexels",
                voice_name="pt-BR-AntonioNeural",
                flow_enabled=True,
                flow_scene_count=6,
            )

        self.assertFalse(ok)
        self.assertIn("Créditos Flow insuficientes", msg)
        self.assertEqual(details.get("Flow"), "INSUFFICIENT_CREDITS")

    def test_06_preflight_proceeds_when_flow_credits_sufficient(self):
        """6. Preflight aprova quando há conta com saldo suficiente para as cenas (ex: 116 >= 90 cr)."""
        fap.record_verified_credit_balance("flow-primary", 116, runtime_path=self.runtime_path)
        fap.record_verified_credit_balance("flow-b", 52, runtime_path=self.runtime_path)
        fap.record_verified_credit_balance("flow-c", 50, runtime_path=self.runtime_path)

        with patch("app.services.flow_account_pool.DEFAULT_CONFIG_PATH", self.config_path), \
             patch("app.services.flow_account_pool.DEFAULT_RUNTIME_PATH", self.runtime_path), \
             patch("app.utils.utils.check_ffmpeg_ready", return_value=True), \
             patch("app.services.material.has_material_api_keys", return_value=True), \
             patch("shutil.disk_usage", return_value=(100, 50, 10 * (1024 ** 3))), \
             patch("app.models.llm_provider.get_llm_provider") as mock_llm_prov:

            mock_spec = MagicMock()
            mock_spec.requires_api_key = False
            mock_llm_prov.return_value = mock_spec

            ok, msg, details = ap.check_required_providers_preflight(
                video_source="pexels",
                voice_name="pt-BR-AntonioNeural",
                flow_enabled=True,
                flow_scene_count=6,
            )

        self.assertTrue(ok)
        self.assertIn("Account flow-primary", details.get("Flow", ""))

    def test_07_preflight_ignores_flow_when_flow_disabled(self):
        """7. Formatos sem Flow (flow_enabled=False) não são bloqueados mesmo se créditos Flow forem 0."""
        fap.record_verified_credit_balance("flow-primary", 0, runtime_path=self.runtime_path)

        with patch("app.services.flow_account_pool.DEFAULT_CONFIG_PATH", self.config_path), \
             patch("app.services.flow_account_pool.DEFAULT_RUNTIME_PATH", self.runtime_path), \
             patch("app.utils.utils.check_ffmpeg_ready", return_value=True), \
             patch("app.services.material.has_material_api_keys", return_value=True), \
             patch("shutil.disk_usage", return_value=(100, 50, 10 * (1024 ** 3))), \
             patch("app.models.llm_provider.get_llm_provider") as mock_llm_prov:

            mock_spec = MagicMock()
            mock_spec.requires_api_key = False
            mock_llm_prov.return_value = mock_spec

            ok, msg, details = ap.check_required_providers_preflight(
                video_source="pexels",
                voice_name="pt-BR-AntonioNeural",
                flow_enabled=False,
            )

        self.assertTrue(ok)
        self.assertNotIn("Flow", details)

    def test_08_autonomous_cycle_waits_without_failure_when_credits_insufficient(self):
        """8. Ciclo autônomo entra em espera (STATE_BLOCKED) sem criar tarefa e sem contar falha de geração."""
        from app.models.schema import VideoParams
        from app.services import profile_manager

        test_db = os.path.join(self.test_dir, "test_operator.db")
        ap.scheduler.init_db(test_db)
        from app.services import operator_console
        operator_console.init_operator_db(test_db)
        profile_manager.init_profile_db(test_db)

        fake_params = VideoParams(
            video_subject="Mistério Antigo",
            video_source="pexels",
            voice_name="pt-BR-AntonioNeural",
            flow_enabled=True,
            flow_scene_count=6,
        )

        mock_submit = MagicMock()

        with patch("app.services.autonomous_production.check_required_providers_preflight",
                   return_value=(False, "Créditos Flow insuficientes no pool de contas (necessário: 90 cr para 6 cenas)", {"Flow": "INSUFFICIENT_CREDITS"})), \
             patch("app.services.operator_console.is_primary_instance", return_value=True), \
             patch("app.services.operator_console.require_primary_instance"), \
             patch("app.services.operator_console.is_factory_paused", return_value=False), \
             patch("app.services.autonomous_production.is_profile_autonomous_mode_enabled", return_value=True), \
             patch("app.services.autonomous_production.get_channel_active_platforms", return_value=["youtube"]), \
             patch("app.services.autonomous_production.get_autonomous_ready_stock", return_value={"ready_count": 0, "target_stock": 3, "ready_tasks": []}), \
             patch("app.services.autonomous_production.get_target_ready_stock", return_value=3), \
             patch("app.services.autonomous_production.build_autonomous_video_params", return_value=fake_params), \
             patch("app.services.webui_task.submit_generation", mock_submit):

            res = ap._run_autonomous_cycle(
                db_path=test_db,
                profile_id="prof-flow",
                channel_id="chan-flow",
            )

        # 1. Status deve ser blocked por créditos insuficientes
        self.assertEqual(res["status"], "blocked")
        self.assertEqual(res["reason"], "flow_creditos_insuficientes")
        self.assertIn("Créditos Flow insuficientes", res["message"])

        # 2. Nenhuma tarefa de geração deve ter sido submetida
        mock_submit.assert_not_called()

        # 3. Nenhuma tentativa 24h consumida
        attempts = ap.count_generation_attempts_in_last_24h(db_path=test_db, profile_id="prof-flow")
        self.assertEqual(attempts, 0)


if __name__ == "__main__":
    unittest.main()
