"""
Test Suite para Atualização Segura e Não-Destrutiva de Produção (Fase V13-A).

Cobre:
1. Existência e permissões do script scripts/update_production.ps1
2. Contrato de parâmetros obrigatórios e opcionais (TargetRef, RepoPath, TaskName, HealthUrl, PreflightOnly)
3. Proibição estrita de comandos destrutivos (git reset, git restore, git clean)
4. Contrato de Fast-Forward obrigatório (git merge-base --is-ancestor)
5. Contrato de Backup transacional com integridade (PRAGMA integrity_check) e hash SHA-256 antes do stop
6. Contrato de Stop seguro precedendo qualquer mutação no Git
7. Contrato de Start e Health check delimitado (timeout finito, sem polling infinito)
8. Contrato de Rollback não-destrutivo via 'git switch --detach CURRENT_SHA'
9. Contrato de Lock exclusivo contra deploy duplo com limpeza em finally
10. Contrato de Logging local sanitizado em logs/deploy/ (zero segredos/tokens/config.toml)
11. Execução funcional de Pre-flight em repositório Git temporário (LIMPO => PASS)
12. Execução funcional de Pre-flight fail-closed com working tree suja (DIRTY => FAIL)
13. Execução funcional de Pre-flight fail-closed em caso de não-ancestral (NON-FF => FAIL)
"""

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "update_production.ps1"


class TestSafeProductionUpdate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script_path = SCRIPT_PATH
        cls.assertTrue(
            cls.script_path.is_file(),
            f"O script '{cls.script_path}' deve existir em disco.",
        )
        with open(cls.script_path, "r", encoding="utf-8") as f:
            cls.script_content = f.read()

    # 1. Existência do Script
    def test_01_script_exists(self):
        self.assertTrue(self.script_path.is_file())
        self.assertGreater(len(self.script_content), 100)

    # 2. Contrato de Parâmetros
    def test_02_parameters_contract(self):
        # Verifica se o bloco param declara os parâmetros especificados
        param_match = re.search(r"param\s*\((.*?)\)", self.script_content, re.DOTALL)
        self.assertIsNotNone(param_match, "Bloco param(...) deve existir no script.")
        param_block = param_match.group(1)

        self.assertIn("$TargetRef", param_block)
        self.assertIn("origin/main", param_block)
        self.assertIn("$RepoPath", param_block)
        self.assertIn(r"C:\Projetos\MoneyPrinterTurbo", param_block)
        self.assertIn("$TaskName", param_block)
        self.assertIn("VideoFactory Production", param_block)
        self.assertIn("$HealthUrl", param_block)
        self.assertIn("http://127.0.0.1:8501/_stcore/health", param_block)
        self.assertIn("$PreflightOnly", param_block)

    # 3. Proibição de Comandos Destrutivos (Zero git reset / git restore / git clean)
    def test_03_no_destructive_git_commands(self):
        # Remove comentários do script para validar somente código executável
        lines = self.script_content.splitlines()
        code_lines = []
        in_comment_block = False
        for line in lines:
            stripped = line.strip()
            if "<#" in stripped:
                in_comment_block = True
            if in_comment_block:
                if "#>" in stripped:
                    in_comment_block = False
                continue
            if stripped.startswith("#"):
                continue
            code_lines.append(stripped)

        code_text = "\n".join(code_lines)
        self.assertNotRegex(
            code_text,
            r"\bgit\s+reset\b",
            "O script NUNCA deve conter comandos executáveis 'git reset'.",
        )
        self.assertNotRegex(
            code_text,
            r"\bgit\s+restore\b",
            "O script NUNCA deve conter comandos executáveis 'git restore'.",
        )
        self.assertNotRegex(
            code_text,
            r"\bgit\s+clean\b",
            "O script NUNCA deve conter comandos executáveis 'git clean'.",
        )

    # 4. Fast-Forward Safety Obrigatório
    def test_04_fast_forward_safety_enforced(self):
        self.assertIn("merge-base --is-ancestor", self.script_content)
        self.assertIn("git merge --ff-only", self.script_content)

    # 5. Backup Transacional e Integridade Antes de Parar Produção
    def test_05_backup_before_stop_and_integrity_check(self):
        # Verifica se o backup chama production_backup com integridade
        self.assertIn("app.services.production_backup", self.script_content)
        self.assertIn("integrity_check", self.script_content)
        self.assertIn("sha256", self.script_content)

        # Ordem de execução: backup deve aparecer antes de schtasks /End
        backup_pos = self.script_content.find("app.services.production_backup")
        stop_pos = self.script_content.find("schtasks /End")
        self.assertGreater(backup_pos, 0)
        self.assertGreater(stop_pos, 0)
        self.assertLess(
            backup_pos,
            stop_pos,
            "Backup do banco SQLite DEVE ocorrer antes da chamada de parada 'schtasks /End'.",
        )

    # 6. Stop Precede Alteração no Git
    def test_06_stop_precedes_git_update(self):
        stop_pos = self.script_content.find("schtasks /End")
        update_pos = self.script_content.find("git merge --ff-only")
        self.assertGreater(stop_pos, 0)
        self.assertGreater(update_pos, 0)
        self.assertLess(
            stop_pos,
            update_pos,
            "A parada do serviço DEVE ocorrer antes da atualização Git FF-only.",
        )

    # 7. Start e Health Check Delimitado
    def test_07_start_and_bounded_health_check(self):
        self.assertIn("schtasks /Run", self.script_content)
        self.assertIn("Test-HealthEndpoint", self.script_content)
        self.assertIn("TimeoutSeconds", self.script_content)
        self.assertIn("http://127.0.0.1:8501/_stcore/health", self.script_content)

    # 8. Rollback Seguro via git switch --detach
    def test_08_safe_rollback_contract(self):
        self.assertIn("git switch --detach", self.script_content)
        self.assertIn("ROLLBACK_SUCCESS", self.script_content)
        self.assertIn("ROLLBACK_FAILED", self.script_content)
        self.assertIn("DETACHED HEAD", self.script_content)

    # 9. Lock Contra Deploy Concorrente
    def test_09_concurrency_lock_mechanism(self):
        self.assertIn("update_production.lock", self.script_content)
        self.assertIn("finally", self.script_content)
        self.assertIn("Remove-Item $LockFile", self.script_content)

    # 10. Sanitização de Logs Locais
    def test_10_sanitized_deploy_logs(self):
        self.assertIn(r"logs\deploy", self.script_content)
        self.assertNotIn("gemini_api_key", self.script_content)
        self.assertNotIn("pexels_api_key", self.script_content)
        self.assertNotIn("upload_post_token", self.script_content)
        self.assertNotIn("youtube_client_secret", self.script_content)

    # 11. Preflight Funcional em Repo Temporário Limpo (PASS)
    def test_11_preflight_on_clean_temp_repo(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            # Inicializa repo git temporário
            subprocess.run(["git", "init", str(temp_path)], check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Tester"], cwd=temp_path, check=True)
            subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=temp_path, check=True)

            # Cria commit inicial
            readme = temp_path / "README.md"
            readme.write_text("Test", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=temp_path, check=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=temp_path, check=True)

            # Cria estrutura mínima para preflight
            venv_scripts = temp_path / ".venv" / "Scripts"
            venv_scripts.mkdir(parents=True, exist_ok=True)
            dummy_python = venv_scripts / "python.exe"
            dummy_python.write_text("", encoding="utf-8")

            # Executa Preflight com -SkipTaskCheck
            cmd = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-File", str(self.script_path),
                "-RepoPath", str(temp_path),
                "-TargetRef", "HEAD",
                "-PreflightOnly",
                "-SkipTaskCheck",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(
                result.returncode,
                0,
                f"Preflight em repo limpo deve retornar 0. Erro: {result.stderr}\nSaída: {result.stdout}",
            )
            self.assertIn("PREFLIGHT_PASS", result.stdout)

    # 12. Preflight Funcional Fail-Closed com Working Tree Suja (DIRTY => FAIL)
    def test_12_preflight_fails_on_dirty_worktree(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            subprocess.run(["git", "init", str(temp_path)], check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Tester"], cwd=temp_path, check=True)
            subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=temp_path, check=True)

            readme = temp_path / "README.md"
            readme.write_text("Initial", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=temp_path, check=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=temp_path, check=True)

            venv_scripts = temp_path / ".venv" / "Scripts"
            venv_scripts.mkdir(parents=True, exist_ok=True)
            dummy_python = venv_scripts / "python.exe"
            dummy_python.write_text("", encoding="utf-8")

            # Suja o arquivo rastreado
            readme.write_text("Modified but uncommitted content", encoding="utf-8")

            cmd = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-File", str(self.script_path),
                "-RepoPath", str(temp_path),
                "-TargetRef", "HEAD",
                "-PreflightOnly",
                "-SkipTaskCheck",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            self.assertNotEqual(
                result.returncode,
                0,
                "Preflight DEVE abortar com código diferente de zero quando a working tree estiver suja.",
            )
            self.assertIn("Working tree", result.stdout + result.stderr)

    # 13. Preflight Funcional Fail-Closed em Caso de Não-Ancestral (NON-FF => FAIL)
    def test_13_preflight_fails_on_non_ancestor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            subprocess.run(["git", "init", str(temp_path)], check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Tester"], cwd=temp_path, check=True)
            subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=temp_path, check=True)

            readme = temp_path / "README.md"
            readme.write_text("Base", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=temp_path, check=True)
            subprocess.run(["git", "commit", "-m", "base"], cwd=temp_path, check=True)

            # Cria branch divergente
            subprocess.run(["git", "checkout", "-b", "divergent"], cwd=temp_path, check=True)
            f1 = temp_path / "div.txt"
            f1.write_text("Divergent commit", encoding="utf-8")
            subprocess.run(["git", "add", "div.txt"], cwd=temp_path, check=True)
            subprocess.run(["git", "commit", "-m", "div commit"], cwd=temp_path, check=True)
            target_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=temp_path, capture_output=True, text=True, check=True
            ).stdout.strip()

            # Volta para main e faz outro commit divergente (torna target_sha não-ancestral de main)
            subprocess.run(["git", "checkout", "master" if "master" in subprocess.run(["git", "branch"], cwd=temp_path, capture_output=True, text=True).stdout else "main"], cwd=temp_path, check=True)
            f2 = temp_path / "main.txt"
            f2.write_text("Main commit", encoding="utf-8")
            subprocess.run(["git", "add", "main.txt"], cwd=temp_path, check=True)
            subprocess.run(["git", "commit", "-m", "main commit"], cwd=temp_path, check=True)

            # Agora target_sha NÃO é descendente da HEAD atual
            venv_scripts = temp_path / ".venv" / "Scripts"
            venv_scripts.mkdir(parents=True, exist_ok=True)
            dummy_python = venv_scripts / "python.exe"
            dummy_python.write_text("", encoding="utf-8")

            cmd = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-File", str(self.script_path),
                "-RepoPath", str(temp_path),
                "-TargetRef", target_sha,
                "-PreflightOnly",
                "-SkipTaskCheck",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            self.assertNotEqual(
                result.returncode,
                0,
                "Preflight DEVE abortar com código diferente de zero quando target não for ancestral Fast-Forward.",
            )
            self.assertIn("Fast-Forward", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
