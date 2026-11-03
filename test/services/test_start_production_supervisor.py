"""
Test Suite para o Supervisor do Motor V2 e Logging Persistente.

Cobre:
1. init_engine_logging: sink em storage/logs/engine.log e faulthandler em storage/logs/engine_fatal.log.
2. Contrato de parametros do script scripts/start_production.ps1 (SupervisorMaxRestarts, SupervisorRestartDelaySeconds, etc.).
3. Execucao funcional do supervisor: saida limpa (exit 0) encerra imediatamente sem relancar.
4. Execucao funcional do supervisor: falha transitoria (exit 1 seguido de exit 0) relanca e encerra com 0.
5. Execucao funcional do supervisor: falha persistente (exit 99) atinge o rate limit de relancamentos e encerra com codigo de falha.
6. Gravacao estruturada do historico de relancamentos no arquivo supervisor.log.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from loguru import logger
from app.utils.logging_utils import init_engine_logging

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "start_production.ps1"


class TestStartProductionSupervisor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assertTrue(
            SCRIPT_PATH.is_file(),
            f"O script '{SCRIPT_PATH}' deve existir em disco.",
        )
        with open(SCRIPT_PATH, "r", encoding="utf-8") as f:
            cls.script_content = f.read()

    # 1. Contrato de Parâmetros e Regras do Supervisor
    def test_01_script_contract_parameters(self):
        self.assertIn("SupervisorRestartDelaySeconds", self.script_content)
        self.assertIn("SupervisorMaxRestarts", self.script_content)
        self.assertIn("SupervisorWindowMinutes", self.script_content)
        self.assertIn("SupervisorLogFile", self.script_content)
        self.assertIn("CustomExecutable", self.script_content)
        self.assertIn("CustomExecutableArgs", self.script_content)

    def test_02_script_contract_legacy_unchanged(self):
        # Modo legado nao deve conter laco de supervisor
        legacy_idx = self.script_content.find("if ($Legacy)")
        self.assertNotEqual(legacy_idx, -1)
        else_idx = self.script_content.find("} else {", legacy_idx)
        self.assertNotEqual(else_idx, -1)

        legacy_block = self.script_content[legacy_idx:else_idx]
        self.assertNotIn("while ($true)", legacy_block)
        self.assertNotIn("SupervisorRestartDelaySeconds", legacy_block)

    def test_03_engine_logging_creates_files_and_enables_faulthandler(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            sink_id, fatal_file = init_engine_logging(base_dir=tmp_path, force=True)
            try:
                self.assertIsNotNone(sink_id)
                self.assertIsNotNone(fatal_file)

                engine_log = tmp_path / "storage" / "logs" / "engine.log"
                fatal_log = tmp_path / "storage" / "logs" / "engine_fatal.log"

                self.assertTrue(engine_log.is_file())
                self.assertTrue(fatal_log.is_file())

                # Escreve um log pelo loguru para validar que o sink esta ativo
                logger.info("TEST_SUPERVISOR_ENGINE_LOG_ENTRY")

                with open(engine_log, "r", encoding="utf-8") as f:
                    content = f.read()
                self.assertIn("TEST_SUPERVISOR_ENGINE_LOG_ENTRY", content)
            finally:
                if sink_id is not None:
                    try:
                        logger.remove(sink_id)
                    except Exception:
                        pass
                if fatal_file is not None:
                    try:
                        fatal_file.close()
                    except Exception:
                        pass

    # 4. Execução Funcional: Saída Limpa (Exit 0) encerra imediatamente
    def test_04_supervisor_exits_immediately_on_exit_code_zero(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            runner_script = tmp_path / "exit_zero_runner.py"
            runner_script.write_text("import sys; sys.exit(0)\n", encoding="utf-8")
            log_file = tmp_path / "supervisor_test.log"

            cmd = [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SCRIPT_PATH),
                "-CustomExecutable",
                os.sys.executable,
                "-CustomExecutableArgs",
                str(runner_script),
                "-SupervisorLogFile",
                str(log_file),
            ]

            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(PROJECT_ROOT),
                timeout=30,
            )

            self.assertEqual(res.returncode, 0, f"Deveria sair com 0. Stderr: {res.stderr}")
            self.assertTrue(log_file.is_file(), "Arquivo de log do supervisor deve ter sido criado")
            log_content = log_file.read_text(encoding="utf-8")
            self.assertIn("ExitCode 0", log_content)
            self.assertIn("saida limpa", log_content)

    # 5. Execução Funcional: Falha Transitória relança e tem sucesso
    def test_05_supervisor_relaunches_on_failure_then_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            counter_file = tmp_path / "runs_counter.txt"
            counter_file.write_text("0", encoding="utf-8")
            log_file = tmp_path / "supervisor_test.log"

            # Script de teste: na primeira vez sai com 1, na segunda com 0
            test_py = tmp_path / "flaky_runner.py"
            test_py.write_text(
                f"""
from pathlib import Path
import sys

p = Path(r'{counter_file}')
count = int(p.read_text(encoding='utf-8').strip())
p.write_text(str(count + 1), encoding='utf-8')

if count == 0:
    sys.exit(1)
else:
    sys.exit(0)
""",
                encoding="utf-8",
            )

            cmd = [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SCRIPT_PATH),
                "-CustomExecutable",
                os.sys.executable,
                "-CustomExecutableArgs",
                str(test_py),
                "-SupervisorRestartDelaySeconds",
                "1",
                "-SupervisorMaxRestarts",
                "3",
                "-SupervisorLogFile",
                str(log_file),
            ]

            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(PROJECT_ROOT),
                timeout=30,
            )

            self.assertEqual(res.returncode, 0, f"Deveria sair com 0 apos recuperacao. Stderr: {res.stderr}")
            final_runs = int(counter_file.read_text(encoding="utf-8").strip())
            self.assertEqual(final_runs, 2, "Deveria ter executado 2 vezes (1 falha + 1 sucesso)")

            log_content = log_file.read_text(encoding="utf-8")
            self.assertIn("[ExitCode 1][Restarts 1]", log_content)
            self.assertIn("[ExitCode 0][Restarts 1]", log_content)

    # 6. Execução Funcional: Limite de Relançamentos Excedido encerra com erro
    def test_06_supervisor_stops_after_max_restarts_limit(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            counter_file = tmp_path / "runs_counter.txt"
            counter_file.write_text("0", encoding="utf-8")
            log_file = tmp_path / "supervisor_test.log"

            test_py = tmp_path / "failing_runner.py"
            test_py.write_text(
                f"""
from pathlib import Path
import sys

p = Path(r'{counter_file}')
count = int(p.read_text(encoding='utf-8').strip())
p.write_text(str(count + 1), encoding='utf-8')
sys.exit(99)
""",
                encoding="utf-8",
            )

            # MaxRestarts = 2, delay = 1s -> 1 exec inicial + 2 reinicios = 3 execucoes no total
            cmd = [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SCRIPT_PATH),
                "-CustomExecutable",
                os.sys.executable,
                "-CustomExecutableArgs",
                str(test_py),
                "-SupervisorRestartDelaySeconds",
                "1",
                "-SupervisorMaxRestarts",
                "2",
                "-SupervisorLogFile",
                str(log_file),
            ]

            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(PROJECT_ROOT),
                timeout=30,
            )

            self.assertEqual(res.returncode, 99, f"Deveria sair com codigo de falha 99. Stderr: {res.stderr}")
            final_runs = int(counter_file.read_text(encoding="utf-8").strip())
            self.assertEqual(final_runs, 3, "Deveria ter executado 3 vezes (1 inicial + 2 relancamentos permitidos)")

            log_content = log_file.read_text(encoding="utf-8")
            self.assertIn("Limite de relancamentos do supervisor excedido", log_content)
            self.assertIn("[ExitCode 99][Restarts 3]", log_content)


if __name__ == "__main__":
    unittest.main()
