"""
Test Suite para Inicialização Automática e Persistente da Web UI V2 (Scheduled Task).

Valida:
1. Existência e permissões de scripts/register_webui_v2_task.ps1 e scripts/start_webui_v2.ps1.
2. Contrato de parâmetros da Scheduled Task (TaskName="VideoFactory WebUI V2", PrimaryTaskName="VideoFactory Production").
3. Configuração de Trigger (AtStartup - boot sem login), Action (Hidden window), Principal (SYSTEM/ServiceAccount) e Settings (MultipleInstances IgnoreNew, RestartCount=3, RestartInterval=1min, ExecutionTimeLimit=0).
4. Proteção estrita de não-interferência: a tarefa de produção 'VideoFactory Production' nunca é modificada, interrompida ou desregistrada.
5. Proteção contra processos duplicados na porta 8080 em start_webui_v2.ps1 e rastreamento de PID.
6. Validação sintática formal dos scripts PowerShell via AST Parser.
"""

import os
import re
import subprocess
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
REGISTER_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "register_webui_v2_task.ps1"
START_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "start_webui_v2.ps1"


class TestWebUiV2AutoStart(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assertTrue(REGISTER_SCRIPT_PATH.is_file(), f"'{REGISTER_SCRIPT_PATH}' deve existir.")
        cls.assertTrue(START_SCRIPT_PATH.is_file(), f"'{START_SCRIPT_PATH}' deve existir.")

        with open(REGISTER_SCRIPT_PATH, "r", encoding="utf-8") as f:
            cls.register_content = f.read()

        with open(START_SCRIPT_PATH, "r", encoding="utf-8") as f:
            cls.start_content = f.read()

    def test_01_scripts_exist_and_non_empty(self):
        """1. Ambos os scripts devem existir e ter conteúdo substancial."""
        self.assertGreater(len(self.register_content), 500)
        self.assertGreater(len(self.start_content), 500)

    def test_02_register_script_param_contract(self):
        """2. Contrato de parâmetros do script register_webui_v2_task.ps1."""
        param_match = re.search(r"param\s*\((.*?)\)", self.register_content, re.DOTALL)
        self.assertIsNotNone(param_match, "Bloco param(...) deve existir no script.")
        param_block = param_match.group(1)

        self.assertIn("RepoPath", param_block)
        self.assertIn(r"C:\Projetos\MoneyPrinterTurbo", param_block)
        self.assertIn("TaskName", param_block)
        self.assertIn("VideoFactory WebUI V2", param_block)
        self.assertIn("PrimaryTaskName", param_block)
        self.assertIn("VideoFactory Production", param_block)
        self.assertIn("Port", param_block)
        self.assertIn("8080", param_block)
        self.assertIn("TaskUser", param_block)
        self.assertIn("NT AUTHORITY\\SYSTEM", param_block)

    def test_03_scheduled_task_invariants(self):
        """3. Invariantes técnicas da Scheduled Task (AtStartup, Hidden, IgnoreNew, RestartCount)."""
        # Trigger no boot sem login
        self.assertIn("-AtStartup", self.register_content)
        # Janela invisível / não-interativa
        self.assertIn("-WindowStyle Hidden", self.register_content)
        # Proteção contra concorrência e processos duplicados no agendador
        self.assertIn("-MultipleInstances IgnoreNew", self.register_content)
        # Política de resiliência e auto-recuperação
        self.assertIn("-RestartCount 3", self.register_content)
        self.assertIn("-RestartInterval", self.register_content)
        # Sem timeout de execução (serviço contínuo)
        self.assertIn("-ExecutionTimeLimit (New-TimeSpan -Days 0)", self.register_content)

    def test_04_production_task_protection_invariants(self):
        """4. Garantia estrita de que a tarefa de produção não é violada."""
        # Não pode dar Stop ou Unregister na tarefa de produção principal
        self.assertNotIn("Stop-ScheduledTask -TaskName $PrimaryTaskName", self.register_content)
        self.assertNotIn("Unregister-ScheduledTask -TaskName $PrimaryTaskName", self.register_content)
        self.assertNotIn("schtasks /End /TN $PrimaryTaskName", self.register_content)
        self.assertNotIn("schtasks /Delete /TN $PrimaryTaskName", self.register_content)

        # Não pode conter comandos destrutivos de Git
        destructive_patterns = [
            r"\bgit\s+reset\s+--hard\b",
            r"\bgit\s+restore\s+\.\b",
            r"\bgit\s+clean\s+-[a-zA-Z]*f\b",
        ]
        for pattern in destructive_patterns:
            self.assertIsNone(
                re.search(pattern, self.register_content, re.IGNORECASE),
                f"Comando destrutivo detectado: {pattern}",
            )

    def test_05_start_script_duplicate_protection(self):
        """5. Proteção de porta e processo duplicado em start_webui_v2.ps1."""
        self.assertIn("$TcpClient", self.start_content)
        self.assertIn("Instância ativa da Web UI V2 já em execução", self.start_content)
        self.assertIn("webui_v2.pid", self.start_content)
        self.assertIn("KillExisting", self.start_content)

    def test_06_powershell_syntax_ast_validation(self):
        """6. Validação de sintaxe formal dos scripts PowerShell via AST Parser."""
        for script_path in [REGISTER_SCRIPT_PATH, START_SCRIPT_PATH]:
            script_full = str(script_path.resolve()).replace("\\", "\\\\")
            cmd = [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                f"$errs = @(); [System.Management.Automation.Language.Parser]::ParseFile('{script_full}', [ref]$null, [ref]$errs); if ($errs.Count -gt 0) {{ foreach ($e in $errs) {{ Write-Host $e.Message }}; exit 1 }} else {{ exit 0 }}",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(
                res.returncode,
                0,
                f"Erro de sintaxe PowerShell no script '{script_path.name}': {res.stdout} {res.stderr}",
            )


if __name__ == "__main__":
    unittest.main()
