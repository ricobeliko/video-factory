"""Testes unitários direcionados para Flow Multi-Account Provider Pool (FLOW-MA1).

Cobre:
1. ausência de config => flow-primary legado;
2. flow-primary usa storage/flow_browser_profile;
3. conta nova ganha user_data_dir isolado;
4. path traversal rejeitado;
5. conta disabled não é selecionada;
6. exhausted não é selecionada;
7. unknown credits ainda pode ser selecionada;
8. maior saldo conhecido tem preferência;
9. task/manifest mantém stickiness;
10. manifest legado com project_url => flow-primary;
11. failover permitido antes de dispatch;
12. failover proibido após project_url/dispatch;
13. credit deduction gera LOCAL_ESTIMATE;
14. nova leitura verificada reconcilia saldo;
15. nenhum secret aparece em status/config serializado.
"""

import json
import os
import unittest
from unittest.mock import MagicMock, patch

from app.services.flow_account_pool import (
    CREDIT_SOURCE_FLOW_UI_VERIFIED,
    CREDIT_SOURCE_LOCAL_ESTIMATE,
    CREDIT_SOURCE_UNKNOWN,
    LEGACY_ACCOUNT_ID,
    LEGACY_USER_DATA_DIR,
    STATUS_AUTH_REQUIRED,
    STATUS_AVAILABLE,
    STATUS_DISABLED,
    STATUS_EXHAUSTED,
    add_account,
    can_failover_account,
    check_flow_page_exhausted,
    disable_account,
    enable_account,
    failover_flow_account,
    find_edge_executable,
    get_flow_accounts_status,
    launch_edge_for_human_login,
    load_accounts_config,
    read_flow_credit_balance,
    record_account_error,
    record_account_success,
    record_credit_deduction,
    record_verified_credit_balance,
    resolve_manifest_account,
    resolve_user_data_dir,
    save_accounts_config,
    select_flow_account,
    validate_account_id,
    verify_flow_account_session,
)


class TestFlowAccountPool(unittest.TestCase):
    def setUp(self):
        self.test_dir = os.path.join("storage", "test_pool_tmp")
        os.makedirs(self.test_dir, exist_ok=True)
        self.config_path = os.path.join(self.test_dir, "test_flow_accounts.json")
        self.runtime_path = os.path.join(self.test_dir, "test_flow_accounts_runtime.json")

    def tearDown(self):
        for p in (self.config_path, self.runtime_path):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
        if os.path.exists(self.test_dir):
            try:
                import shutil
                shutil.rmtree(self.test_dir, ignore_errors=True)
            except Exception:
                pass

    def test_01_missing_config_returns_legacy_flow_primary(self):
        """1. Ausência de config => flow-primary legado virtual."""
        non_existent = os.path.join(self.test_dir, "does_not_exist.json")
        cfg = load_accounts_config(non_existent)
        self.assertEqual(cfg.get("schema_version"), 1)
        accounts = cfg.get("accounts", [])
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["account_id"], LEGACY_ACCOUNT_ID)
        self.assertTrue(accounts[0]["enabled"])

    def test_02_flow_primary_uses_legacy_profile_dir(self):
        """2. flow-primary usa storage/flow_browser_profile."""
        resolved = resolve_user_data_dir("flow-primary")
        self.assertEqual(os.path.normpath(resolved), os.path.normpath(LEGACY_USER_DATA_DIR))
        self.assertTrue(resolved.endswith(os.path.join("storage", "flow_browser_profile")))

    def test_03_new_account_gets_isolated_user_data_dir(self):
        """3. Conta nova ganha user_data_dir isolado."""
        resolved = resolve_user_data_dir("flow-b")
        expected_suffix = os.path.join("storage", "flow_browser_profiles", "flow-b")
        self.assertTrue(os.path.normpath(resolved).endswith(os.path.normpath(expected_suffix)))
        self.assertNotEqual(resolved, LEGACY_USER_DATA_DIR)

    def test_04_path_traversal_rejected(self):
        """4. Path traversal e caracteres inválidos são rejeitados."""
        bad_ids = [
            "../bad",
            "..\\bad",
            "flow/b",
            "flow\\b",
            "flow b",
            "flow@b",
            "FLOW-B",  # somente lowercase
            "",
            "   ",
        ]
        for bad in bad_ids:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    validate_account_id(bad)

    def test_05_disabled_account_not_selected(self):
        """5. Conta disabled não é selecionada."""
        cfg = {
            "schema_version": 1,
            "accounts": [
                {
                    "account_id": "flow-primary",
                    "display_name": "Conta A",
                    "enabled": False,
                    "priority": 100,
                },
                {
                    "account_id": "flow-b",
                    "display_name": "Conta B",
                    "enabled": True,
                    "priority": 50,
                },
            ],
        }
        save_accounts_config(cfg, self.config_path)
        chosen = select_flow_account(config_path=self.config_path, runtime_path=self.runtime_path)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen["account_id"], "flow-b")

    def test_06_exhausted_account_not_selected(self):
        """6. Conta com status EXHAUSTED não é selecionada."""
        cfg = {
            "schema_version": 1,
            "accounts": [
                {"account_id": "flow-primary", "display_name": "Conta A", "enabled": True, "priority": 100},
                {"account_id": "flow-b", "display_name": "Conta B", "enabled": True, "priority": 90},
            ],
        }
        save_accounts_config(cfg, self.config_path)
        # flow-primary exhausted
        record_account_error("flow-primary", "Out of credits", is_exhausted=True, runtime_path=self.runtime_path)

        chosen = select_flow_account(config_path=self.config_path, runtime_path=self.runtime_path)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen["account_id"], "flow-b")

    def test_07_unknown_credits_account_eligible(self):
        """7. Conta com saldo UNKNOWN continua elegível."""
        cfg = {
            "schema_version": 1,
            "accounts": [
                {"account_id": "flow-primary", "display_name": "Conta A", "enabled": True, "priority": 100},
            ],
        }
        save_accounts_config(cfg, self.config_path)
        chosen = select_flow_account(config_path=self.config_path, runtime_path=self.runtime_path)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen["account_id"], "flow-primary")
        self.assertIsNone(chosen["runtime"]["credits_remaining"])
        self.assertEqual(chosen["runtime"]["credits_source"], CREDIT_SOURCE_UNKNOWN)

    def test_08_highest_known_credits_preferred(self):
        """8. Maior saldo conhecido tem preferência sobre prioridade."""
        cfg = {
            "schema_version": 1,
            "accounts": [
                {"account_id": "flow-primary", "display_name": "Conta A", "enabled": True, "priority": 100},
                {"account_id": "flow-b", "display_name": "Conta B", "enabled": True, "priority": 50},
            ],
        }
        save_accounts_config(cfg, self.config_path)
        record_verified_credit_balance("flow-primary", 50, runtime_path=self.runtime_path)
        record_verified_credit_balance("flow-b", 500, runtime_path=self.runtime_path)

        chosen = select_flow_account(config_path=self.config_path, runtime_path=self.runtime_path)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen["account_id"], "flow-b")
        self.assertEqual(chosen["runtime"]["credits_remaining"], 500)

    def test_09_task_manifest_stickiness(self):
        """9. Tarefa já vinculada à conta mantém stickiness estrita se produção iniciada."""
        cfg = {
            "schema_version": 1,
            "accounts": [
                {"account_id": "flow-primary", "display_name": "Conta A", "enabled": True, "priority": 100},
                {"account_id": "flow-b", "display_name": "Conta B", "enabled": True, "priority": 50},
            ],
        }
        save_accounts_config(cfg, self.config_path)
        record_verified_credit_balance("flow-primary", 900, runtime_path=self.runtime_path)
        record_verified_credit_balance("flow-b", 100, runtime_path=self.runtime_path)

        manifest = {
            "flow_account_id": "flow-b",
            "flow_project_url": "https://flow.google.com/project/xyz",
        }
        chosen = select_flow_account(manifest, config_path=self.config_path, runtime_path=self.runtime_path)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen["account_id"], "flow-b")

    def test_10_legacy_manifest_with_project_url_assigns_flow_primary(self):
        """10. Manifest legado com flow_project_url mas sem flow_account_id atribui flow-primary."""
        manifest_path = os.path.join(self.test_dir, "legacy_manifest.json")
        manifest = {
            "flow_project_url": "https://flow.google.com/legacy_proj",
            "scenes": [{"scene_index": 1}],
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f)

        resolved = resolve_manifest_account(
            manifest,
            manifest_path=manifest_path,
            config_path=self.config_path,
            runtime_path=self.runtime_path,
        )
        self.assertEqual(resolved["account_id"], LEGACY_ACCOUNT_ID)
        self.assertEqual(manifest.get("flow_account_id"), LEGACY_ACCOUNT_ID)

        # Confirma persistência atômica no arquivo
        with open(manifest_path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved.get("flow_account_id"), LEGACY_ACCOUNT_ID)

    def test_11_failover_allowed_before_dispatch(self):
        """11. Failover permitido antes de dispatch: altera conta e persiste."""
        cfg = {
            "schema_version": 1,
            "accounts": [
                {"account_id": "flow-primary", "display_name": "Conta A", "enabled": True, "priority": 100},
                {"account_id": "flow-b", "display_name": "Conta B", "enabled": True, "priority": 90},
            ],
        }
        save_accounts_config(cfg, self.config_path)
        manifest_path = os.path.join(self.test_dir, "fresh_manifest.json")
        manifest = {
            "flow_account_id": "flow-primary",
            "flow_project_url": None,
            "flow_generation": {},
            "scenes": [{"scene_index": 1}],
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f)

        self.assertTrue(can_failover_account(manifest))

        next_acc = failover_flow_account(
            manifest_path=manifest_path,
            failed_account_id="flow-primary",
            error_reason="Login required",
            config_path=self.config_path,
            runtime_path=self.runtime_path,
        )
        self.assertIsNotNone(next_acc)
        self.assertEqual(next_acc["account_id"], "flow-b")

        # Verifica manifesto persistido
        with open(manifest_path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved.get("flow_account_id"), "flow-b")

    def test_12_failover_prohibited_after_project_url_or_dispatch(self):
        """12. Failover proibido após project_url ou dispatch confirmado."""
        manifest_path = os.path.join(self.test_dir, "in_flight_manifest.json")
        manifest = {
            "flow_account_id": "flow-primary",
            "flow_project_url": "https://flow.google.com/active",
            "flow_generation": {"generation_start_confirmed": True},
            "scenes": [{"scene_index": 1}],
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f)

        self.assertFalse(can_failover_account(manifest))

        failover_res = failover_flow_account(
            manifest_path=manifest_path,
            failed_account_id="flow-primary",
            error_reason="Timeout waiting for clip",
            config_path=self.config_path,
            runtime_path=self.runtime_path,
        )
        self.assertIsNone(failover_res)

        # Manifesto não deve ser alterado
        with open(manifest_path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved.get("flow_account_id"), "flow-primary")

    def test_13_credit_deduction_generates_local_estimate(self):
        """13. Dedução de crédito gera LOCAL_ESTIMATE com contador de créditos usados."""
        record_verified_credit_balance("flow-b", 100, runtime_path=self.runtime_path)
        rt1 = record_credit_deduction("flow-b", 15, runtime_path=self.runtime_path)

        self.assertEqual(rt1["credits_remaining"], 85)
        self.assertEqual(rt1["credits_source"], CREDIT_SOURCE_LOCAL_ESTIMATE)
        self.assertEqual(rt1["credits_used_since_verified"], 15)
        self.assertEqual(rt1["last_credit_cost"], 15)

    def test_14_verified_reading_reconciles_balance(self):
        """14. Nova leitura da UI reconcilia saldo e reseta contador local."""
        record_verified_credit_balance("flow-b", 100, runtime_path=self.runtime_path)
        record_credit_deduction("flow-b", 15, runtime_path=self.runtime_path)

        # Leitura real da interface encontra 90 créditos
        rt2 = record_verified_credit_balance("flow-b", 90, runtime_path=self.runtime_path)
        self.assertEqual(rt2["credits_remaining"], 90)
        self.assertEqual(rt2["credits_source"], CREDIT_SOURCE_FLOW_UI_VERIFIED)
        self.assertEqual(rt2["credits_used_since_verified"], 0)
        self.assertIsNotNone(rt2["credits_last_verified_at"])

    def test_15_no_secrets_in_serialized_config_or_status(self):
        """15. ZERO segredos aparecem em config, runtime ou status de telemetria."""
        cfg = {
            "schema_version": 1,
            "accounts": [
                {
                    "account_id": "flow-primary",
                    "display_name": "Conta Primária",
                    "enabled": True,
                    "priority": 100,
                    "user_data_dir": "storage/flow_browser_profile",
                },
                {
                    "account_id": "flow-b",
                    "display_name": "Conta B",
                    "enabled": True,
                    "priority": 90,
                    "user_data_dir": "storage/flow_browser_profiles/flow-b",
                },
            ],
        }
        save_accounts_config(cfg, self.config_path)
        record_verified_credit_balance("flow-primary", 164, runtime_path=self.runtime_path)

        status_obj = get_flow_accounts_status(config_path=self.config_path, runtime_path=self.runtime_path)
        status_json = json.dumps(status_obj)
        cfg_json = json.dumps(cfg)

        forbidden_keys = ["password", "token", "cookie", "secret", "refresh_token", "api_key"]
        for fk in forbidden_keys:
            self.assertNotIn(fk, status_json.lower())
            self.assertNotIn(fk, cfg_json.lower())

        self.assertEqual(status_obj["total_known_credits"], 164)
        self.assertEqual(len(status_obj["accounts"]), 2)

    def test_16_credit_reader_and_exhaustion_detection(self):
        """16. Teste isolado das funções de leitura de crédito e detecção de esgotamento na página."""
        # Mock de página com créditos na UI
        mock_page = MagicMock()
        mock_loc = MagicMock()
        mock_loc.count.return_value = 1
        mock_loc.nth.return_value.inner_text.return_value = "164 créditos"
        mock_page.locator.return_value = mock_loc

        val, src = read_flow_credit_balance(mock_page)
        self.assertEqual(val, 164)
        self.assertEqual(src, CREDIT_SOURCE_FLOW_UI_VERIFIED)

        # Mock de página sem créditos
        mock_page_empty = MagicMock()
        mock_empty_loc = MagicMock()
        mock_empty_loc.count.return_value = 0
        mock_page_empty.locator.return_value = mock_empty_loc
        val_nil, src_nil = read_flow_credit_balance(mock_page_empty)
        self.assertIsNone(val_nil)
        self.assertEqual(src_nil, CREDIT_SOURCE_UNKNOWN)

        # Mock de página com aviso de esgotamento
        mock_page_exh = MagicMock()
        mock_exh_loc = MagicMock()
        mock_exh_loc.count.return_value = 1
        mock_exh_loc.first.is_visible.return_value = True
        mock_page_exh.locator.return_value = mock_exh_loc
        self.assertTrue(check_flow_page_exhausted(mock_page_exh))

    def test_17_cli_operations_add_disable_enable(self):
        """17. Operações de CLI: add, disable, enable."""
        acc = add_account("flow-c", "Conta C", priority=80, config_path=self.config_path)
        self.assertEqual(acc["account_id"], "flow-c")
        self.assertTrue(acc["enabled"])

        # Desativa
        ok_dis = disable_account("flow-c", config_path=self.config_path)
        self.assertTrue(ok_dis)
        cfg = load_accounts_config(self.config_path)
        acc_c = next(a for a in cfg["accounts"] if a["account_id"] == "flow-c")
        self.assertFalse(acc_c["enabled"])

        # Reativa
        ok_en = enable_account("flow-c", config_path=self.config_path)
        self.assertTrue(ok_en)
        cfg2 = load_accounts_config(self.config_path)
        acc_c2 = next(a for a in cfg2["accounts"] if a["account_id"] == "flow-c")
        self.assertTrue(acc_c2["enabled"])

    def test_18_login_resolves_account_isolated_profile_and_launches_native_edge(self):
        """18. Login resolve conta, usa user_data_dir isolado, lança Edge nativo sem Playwright e sem manifest."""
        add_account("flow-b", "Conta B", config_path=self.config_path)
        fake_edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
        with patch("app.services.flow_account_pool.find_edge_executable", return_value=fake_edge), \
             patch("subprocess.Popen") as mock_popen, \
             patch("playwright.sync_api.sync_playwright") as mock_pw:

            res = launch_edge_for_human_login("flow-b", config_path=self.config_path)

            self.assertEqual(res["account_id"], "flow-b")
            self.assertEqual(res["mode"], "HUMAN_LOGIN")
            self.assertTrue(res["edge_launched"])
            self.assertTrue(os.path.normpath(res["profile"]).endswith(os.path.normpath(os.path.join("storage", "flow_browser_profiles", "flow-b"))))

            mock_popen.assert_called_once()
            cmd = mock_popen.call_args[0][0]
            self.assertEqual(cmd[0], fake_edge)
            self.assertIn(f"--user-data-dir={res['profile']}", cmd)
            self.assertIn("https://flow.google.com", cmd)

            # Playwright NUNCA é chamado para login humano
            mock_pw.assert_not_called()

    def test_19_verify_uses_correct_profile_and_returns_authenticated(self):
        """19. Verify usa profile correto e retorna AUTHENTICATED sem gerar nada nem consumir crédito."""
        add_account("flow-b", "Conta B", config_path=self.config_path)
        mock_ctx = MagicMock()
        mock_page = MagicMock()
        mock_ctx.pages = [mock_page]

        with patch("scripts.flow_playwright.launch_flow_context", return_value=(mock_ctx, None)) as mock_launch, \
             patch("scripts.flow_playwright.check_login_state", return_value="AUTHENTICATED"), \
             patch("playwright.sync_api.sync_playwright"):

            res = verify_flow_account_session("flow-b", config_path=self.config_path, runtime_path=self.runtime_path)

            self.assertEqual(res["account_id"], "flow-b")
            self.assertEqual(res["login_status"], "AUTHENTICATED")
            self.assertTrue(res["zero_generation"])
            self.assertTrue(res["zero_credit_consumption"])

            mock_launch.assert_called_once()
            _, kwargs = mock_launch.call_args
            self.assertTrue(os.path.normpath(kwargs["user_data_dir"]).endswith(os.path.normpath(os.path.join("storage", "flow_browser_profiles", "flow-b"))))
            self.assertTrue(kwargs.get("headless"))

    def test_20_verify_auth_required_does_not_attempt_auto_login(self):
        """20. Verify com AUTH_REQUIRED não tenta login automático nem preenche senhas."""
        add_account("flow-b", "Conta B", config_path=self.config_path)
        mock_ctx = MagicMock()
        mock_page = MagicMock()
        mock_ctx.pages = [mock_page]

        with patch("scripts.flow_playwright.launch_flow_context", return_value=(mock_ctx, None)), \
             patch("scripts.flow_playwright.check_login_state", return_value="AWAITING_INITIAL_HUMAN_LOGIN"), \
             patch("playwright.sync_api.sync_playwright"):

            res = verify_flow_account_session("flow-b", config_path=self.config_path, runtime_path=self.runtime_path)

            self.assertEqual(res["account_id"], "flow-b")
            self.assertEqual(res["login_status"], "AUTH_REQUIRED")
            self.assertTrue(res["zero_generation"])
            self.assertTrue(res["zero_credit_consumption"])

            # Confirma que a página não recebeu clicks de login nem campos preenchidos
            mock_page.fill.assert_not_called()
            mock_page.click.assert_not_called()

    def test_21_add_account_recommends_native_edge_login_and_verify(self):
        """21. CLI add imprime novo fluxo com native edge login e verify (sem Playwright trial)."""
        import io
        from contextlib import redirect_stdout
        from app.services.flow_account_pool import cli_main

        buf = io.StringIO()
        with patch("sys.argv", ["flow_account_pool", "add", "--account-id", "flow-b", "--display-name", "Conta B"]), \
             patch("app.services.flow_account_pool.DEFAULT_CONFIG_PATH", self.config_path), \
             redirect_stdout(buf):
            cli_main()

        out = buf.getvalue()
        self.assertIn("python -m app.services.flow_account_pool login --account-id flow-b", out)
        self.assertIn("python -m app.services.flow_account_pool verify --account-id flow-b", out)
        self.assertNotIn("--headful --trial-only", out)


if __name__ == "__main__":
    unittest.main()
