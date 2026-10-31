"""Teste do Contrato de HealthCheck e Rollback de update_production.ps1.

Valida que:
1. Test-V2HealthEndpoint parseia JSON e exige status == 'healthy' e is_primary == True;
2. Test-LegacyHealthEndpoint exige HTTP 200 + corpo contendo 'ok';
3. Test-RollbackHealthEndpoint roteia para Test-V2HealthEndpoint quando a URL for da V2 (/api/v2/health)
   e para Test-LegacyHealthEndpoint quando for do Streamlit (/_stcore/health);
4. O valor padrão de -RollbackHealthUrl é http://127.0.0.1:8080/api/v2/health;
5. O plano de pré-flight exibe a URL e o contrato escolhidos (Contrato V2 vs Contrato Legado V1).
"""

from __future__ import annotations

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class MockHealthHandler(BaseHTTPRequestHandler):
    mode = "v2_healthy_primary"

    def do_GET(self):
        if self.mode == "v2_healthy_primary":
            payload = json.dumps({"status": 200, "data": {"status": "healthy", "is_primary": True}})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload.encode("utf-8"))
        elif self.mode == "v2_secondary":
            payload = json.dumps({"status": 200, "data": {"status": "healthy", "is_primary": False}})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload.encode("utf-8"))
        elif self.mode == "v1_legacy_ok":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(500)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # silencia logs


class TestUpdateProductionHealthAndRollback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), MockHealthHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _run_ps_health_check(self, func_name: str, mode: str, path: str = "/health", timeout: int = 2) -> bool:
        MockHealthHandler.mode = mode
        # Executa somente a declaração das funções extraídas do script
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            f"""
            $code = Get-Content '{REPO_ROOT / "scripts" / "update_production.ps1"}' -Raw
            $fV2 = [regex]::Match($code, '(?s)function Test-V2HealthEndpoint .*?^}}', [System.Text.RegularExpressions.RegexOptions]::Multiline).Value
            $fLeg = [regex]::Match($code, '(?s)function Test-LegacyHealthEndpoint .*?^}}', [System.Text.RegularExpressions.RegexOptions]::Multiline).Value
            $fRoll = [regex]::Match($code, '(?s)function Test-RollbackHealthEndpoint .*?^}}', [System.Text.RegularExpressions.RegexOptions]::Multiline).Value
            Invoke-Expression $fV2
            Invoke-Expression $fLeg
            Invoke-Expression $fRoll
            $res = {func_name} -Url 'http://127.0.0.1:{self.port}{path}' -TimeoutSeconds {timeout} -IntervalSeconds 1
            if ($res) {{ exit 0 }} else {{ exit 1 }}
            """,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        return proc.returncode == 0

    def test_v2_health_endpoint_passes_on_healthy_primary(self):
        """Test-V2HealthEndpoint passa com status=healthy e is_primary=true."""
        ok = self._run_ps_health_check("Test-V2HealthEndpoint", "v2_healthy_primary")
        self.assertTrue(ok)

    def test_v2_health_endpoint_fails_on_secondary(self):
        """Test-V2HealthEndpoint falha se is_primary=false."""
        ok = self._run_ps_health_check("Test-V2HealthEndpoint", "v2_secondary")
        self.assertFalse(ok)

    def test_v2_health_endpoint_fails_on_legacy_ok_string(self):
        """Test-V2HealthEndpoint falha fechado se receber texto 'ok' sem JSON válido com status healthy."""
        ok = self._run_ps_health_check("Test-V2HealthEndpoint", "v1_legacy_ok")
        self.assertFalse(ok)

    def test_legacy_health_endpoint_passes_on_ok_string(self):
        """Test-LegacyHealthEndpoint passa com resposta HTTP 200 contendo 'ok'."""
        ok = self._run_ps_health_check("Test-LegacyHealthEndpoint", "v1_legacy_ok")
        self.assertTrue(ok)

    def test_legacy_health_endpoint_fails_on_v2_json_without_ok(self):
        """Test-LegacyHealthEndpoint falha se receber JSON da V2 sem a string 'ok'."""
        ok = self._run_ps_health_check("Test-LegacyHealthEndpoint", "v2_healthy_primary")
        self.assertFalse(ok)

    def test_rollback_health_endpoint_routes_to_v2_contract_for_v2_url(self):
        """Test-RollbackHealthEndpoint usa contrato V2 quando URL aponta para /api/v2/health."""
        # Sucesso: JSON healthy + primary
        ok_v2 = self._run_ps_health_check("Test-RollbackHealthEndpoint", "v2_healthy_primary", path="/api/v2/health")
        self.assertTrue(ok_v2)

        # Falha: JSON com secondary
        fail_sec = self._run_ps_health_check("Test-RollbackHealthEndpoint", "v2_secondary", path="/api/v2/health")
        self.assertFalse(fail_sec)

        # Falha: texto 'ok' sem JSON
        fail_txt = self._run_ps_health_check("Test-RollbackHealthEndpoint", "v1_legacy_ok", path="/api/v2/health")
        self.assertFalse(fail_txt)

    def test_rollback_health_endpoint_routes_to_legacy_contract_for_streamlit_url(self):
        """Test-RollbackHealthEndpoint usa contrato Legado V1 quando URL for Streamlit (/_stcore/health)."""
        # Sucesso: texto 'ok'
        ok_leg = self._run_ps_health_check("Test-RollbackHealthEndpoint", "v1_legacy_ok", path="/_stcore/health")
        self.assertTrue(ok_leg)

        # Falha: JSON V2 (não contém 'ok' solto)
        fail_v2 = self._run_ps_health_check("Test-RollbackHealthEndpoint", "v2_healthy_primary", path="/_stcore/health")
        self.assertFalse(fail_v2)

    def test_default_rollback_url_in_script_is_v2(self):
        """Garante que o parâmetro padrão de RollbackHealthUrl em update_production.ps1 é a V2."""
        script_code = (REPO_ROOT / "scripts" / "update_production.ps1").read_text(encoding="utf-8")
        self.assertIn('[string]$RollbackHealthUrl = "http://127.0.0.1:8080/api/v2/health"', script_code)

    def test_preflight_plan_code_formats_chosen_contracts(self):
        """Garante que o código de update_production.ps1 formata ROLLBACK_HEALTH com Contrato V2 e Contrato Legado V1."""
        script_code = (REPO_ROOT / "scripts" / "update_production.ps1").read_text(encoding="utf-8")
        self.assertIn("Contrato Legado V1 (HTTP 200 + 'ok')", script_code)
        self.assertIn("Contrato V2 (HTTP 200 + 'healthy' + is_primary=true)", script_code)
        self.assertIn('Write-Host "ROLLBACK_HEALTH : $RollbackHealthUrl (timeout 75s, $RollbackContractDesc)"', script_code)


if __name__ == "__main__":
    unittest.main()
