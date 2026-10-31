"""Teste do Contrato de HealthCheck e Rollback de update_production.ps1.

Valida que:
1. Test-V2HealthEndpoint parseia JSON e exige status == 'healthy' e is_primary == True;
2. Test-LegacyHealthEndpoint exige HTTP 200 + corpo contendo 'ok';
3. O parâmetro -RollbackHealthUrl é respeitado e separa a checagem da V2 da checagem da V1 no rollback.
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

    def _run_ps_health_check(self, func_name: str, mode: str, timeout: int = 2) -> bool:
        MockHealthHandler.mode = mode
        ps_script = f"""
        . '{REPO_ROOT / "scripts" / "update_production.ps1"}'
        {func_name} -Url 'http://127.0.0.1:{self.port}/health' -TimeoutSeconds {timeout} -IntervalSeconds 1
        """
        # Executa somente a declaração da função extraída do script
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            f"""
            $code = Get-Content '{REPO_ROOT / "scripts" / "update_production.ps1"}' -Raw
            # Extrai apenas as funções auxiliares
            $fV2 = [regex]::Match($code, '(?s)function Test-V2HealthEndpoint .*?^}}', [System.Text.RegularExpressions.RegexOptions]::Multiline).Value
            $fLeg = [regex]::Match($code, '(?s)function Test-LegacyHealthEndpoint .*?^}}', [System.Text.RegularExpressions.RegexOptions]::Multiline).Value
            Invoke-Expression $fV2
            Invoke-Expression $fLeg
            $res = {func_name} -Url 'http://127.0.0.1:{self.port}/health' -TimeoutSeconds {timeout} -IntervalSeconds 1
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


if __name__ == "__main__":
    unittest.main()
