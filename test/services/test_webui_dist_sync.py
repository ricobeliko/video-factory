"""Teste de sincronização do bundle de produção webui-v2/dist.

Garante que:
1. webui-v2/dist existe e contém index.html e BUILD_STAMP.json;
2. BUILD_STAMP.json coincide exatamente com o hash dos arquivos em webui-v2/src,
   do package-lock.json e da versão do Vite;
3. Qualquer alteração em src ou package-lock.json sem re-execução de 'npm run build'
   faz o teste FALHAR deterministicamente.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from scripts import build_stamp

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class TestWebuiDistSync(unittest.TestCase):
    def test_dist_exists_and_matches_current_source_code(self):
        """Verifica se webui-v2/dist está perfeitamente sincronizado com o código fonte."""
        src_dir, lock_file, dist_dir, stamp_file = build_stamp.get_paths(str(REPO_ROOT))

        self.assertTrue(os.path.isdir(dist_dir), f"Diretório dist ausente: {dist_dir}")
        self.assertTrue(
            os.path.isfile(os.path.join(dist_dir, "index.html")),
            f"index.html ausente no dist: {dist_dir}",
        )
        self.assertTrue(
            os.path.isfile(stamp_file),
            f"BUILD_STAMP.json ausente no dist: {stamp_file}",
        )

        ok, msg, current = build_stamp.verify_build_stamp(str(REPO_ROOT))
        self.assertTrue(
            ok,
            f"FALHA de sincronização do bundle de produção: {msg}. Execute 'npm run build' em webui-v2.",
        )
        self.assertIsNotNone(current)
        self.assertIn("combined_hash", current)

    def test_verification_fails_closed_when_stamp_is_outdated_or_tampered(self):
        """Comprova que a verificação falha estritamente se o carimbo estiver desatualizado."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Simula um repositório temporário
            tmp_webui = os.path.join(tmp_dir, "webui-v2")
            tmp_src = os.path.join(tmp_webui, "src")
            tmp_dist = os.path.join(tmp_webui, "dist")
            os.makedirs(tmp_src, exist_ok=True)
            os.makedirs(tmp_dist, exist_ok=True)

            with open(os.path.join(tmp_src, "index.js"), "w", encoding="utf-8") as f:
                f.write("console.log('v1');\n")
            with open(os.path.join(tmp_webui, "package-lock.json"), "w", encoding="utf-8") as f:
                f.write('{"packages": {"node_modules/vite": {"version": "6.0.0"}}}\n')
            with open(os.path.join(tmp_dist, "index.html"), "w", encoding="utf-8") as f:
                f.write("<html><body>V1</body></html>\n")

            # Gera carimbo válido
            build_stamp.write_build_stamp(tmp_dir)
            ok, msg, _ = build_stamp.verify_build_stamp(tmp_dir)
            self.assertTrue(ok, f"Deveria ser válido: {msg}")

            # Altera o código em src sem atualizar o carimbo
            with open(os.path.join(tmp_src, "index.js"), "w", encoding="utf-8") as f:
                f.write("console.log('v2-modified');\n")

            ok2, msg2, _ = build_stamp.verify_build_stamp(tmp_dir)
            self.assertFalse(ok2, "Deveria falhar após alteração em src")
            self.assertIn("Divergência de código em src", msg2)


if __name__ == "__main__":
    unittest.main()
