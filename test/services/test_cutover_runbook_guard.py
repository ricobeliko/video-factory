"""Teste de Guarda contra Regressões no Roteiro de Cutover de Produção.

Garante que docs/v2/CUTOVER_PROD.md:
1. NÃO contém chamadas 'update_profile_voice(' (que gravavam direto no banco sem passar pela API V2);
2. NÃO contém 'python -c' invocando 'pause_factory' ou 'resume_factory' (mutações de fábrica devem
   ocorrer via tela V1 para pausa e tela/API V2 como PRIMARY para retomada);
3. Contém a parametrização do alvo como '<ALVO>' com nota de definição após o merge;
4. Contém o passo R0 de anotação do SHA anterior e o passo R3 iniciando via Scheduled Task;
5. Contém a passagem explícita de -RollbackHealthUrl no Passo 4.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class TestCutoverRunbookGuard(unittest.TestCase):
    def setUp(self):
        self.runbook_path = REPO_ROOT / "docs" / "v2" / "CUTOVER_PROD.md"
        self.assertTrue(
            self.runbook_path.is_file(),
            f"Roteiro de cutover não encontrado em: {self.runbook_path}",
        )
        self.content = self.runbook_path.read_text(encoding="utf-8")

    def test_no_update_profile_voice_in_runbook(self):
        """Garante que 'update_profile_voice(' foi banido do roteiro."""
        self.assertNotIn(
            "update_profile_voice(",
            self.content,
            "CUTOVER_PROD.md não deve conter chamadas diretas a 'update_profile_voice('. Use a API PATCH /api/v2/channels/<ID>/voice.",
        )

    def test_no_python_c_with_pause_or_resume_factory(self):
        """Garante que 'python -c' não é usado para pausar ou retomar a fábrica."""
        lines = self.content.splitlines()
        for i, line in enumerate(lines, 1):
            if "python" in line.lower() and "-c" in line:
                self.assertNotIn(
                    "pause_factory",
                    line,
                    f"Linha {i}: Proibido usar 'python -c' com pause_factory. A pausa deve ser feita pela tela da V1.",
                )
                self.assertNotIn(
                    "resume_factory",
                    line,
                    f"Linha {i}: Proibido usar 'python -c' com resume_factory. A retomada deve ser feita via API/tela da V2 PRIMARY.",
                )

    def test_target_ref_parameterized_with_alvo_and_note(self):
        """Garante que Passos 3 e 4 utilizam <ALVO> parametrizado com nota explicativa."""
        self.assertIn("-TargetRef <ALVO>", self.content)
        self.assertIn("origin/main", self.content)
        self.assertIn("origin/v2/base", self.content)

    def test_rollback_steps_and_r0_sha_capture(self):
        """Garante que o roteiro possui R0 anotando git rev-parse HEAD e R3 usando Scheduled Task."""
        self.assertIn("git rev-parse HEAD", self.content)
        self.assertIn('schtasks /Run /TN "VideoFactory Production"', self.content)
        self.assertNotIn(
            "start_production.ps1 -Legacy",
            self.content,
            "Roteiro de rollback não deve chamar -Legacy na V1 anterior porque o script antigo não suportava essa flag.",
        )

    def test_rollback_health_url_explicitly_passed_in_step_4(self):
        """Garante que o Passo 4 declara explicitamente -RollbackHealthUrl com a URL do Streamlit."""
        self.assertIn('-RollbackHealthUrl "http://127.0.0.1:8501/_stcore/health"', self.content)


if __name__ == "__main__":
    unittest.main()
