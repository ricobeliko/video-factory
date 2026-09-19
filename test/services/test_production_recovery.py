"""
Test Suite para o Serviço de Restauração Controlada e Segura (Fase V12-C).

Cobre:
11. Restauração bem-sucedida de backup válido em banco de dados destino
12. Arquivo de backup corrompido é rejeitado sem afetar o destino
13. Divergência de SHA-256 contra manifesto é rejeitada
14. Safety copy pré-restore é criada e preserva o estado anterior do banco
15. Falha antes do replace atômico preserva o banco destino original
16. PRAGMA integrity_check pós-restauração é executado com sucesso
17. Arquivos temporários (.tmp_restore) são limpos em qualquer cenário
18. Proteção contra restauração com backend ativo bloqueia execução
"""
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app.services import production_backup, production_recovery


class TestProductionRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.source_db = os.path.join(self.tmp_dir.name, "source_to_backup.db")
        self.target_db = os.path.join(self.tmp_dir.name, "target_production.db")
        self.backup_dir = os.path.join(self.tmp_dir.name, "backups")
        self.safety_dir = os.path.join(self.tmp_dir.name, "safety")
        os.makedirs(self.backup_dir, exist_ok=True)
        os.makedirs(self.safety_dir, exist_ok=True)

        # 1. Cria banco fonte com conteúdo específico
        conn_src = sqlite3.connect(self.source_db)
        try:
            conn_src.execute("CREATE TABLE records (key TEXT, val TEXT);")
            conn_src.execute("INSERT INTO records VALUES ('source_key', 'restored_content_999');")
            conn_src.commit()
        finally:
            conn_src.close()

        # 2. Gera backup válido do banco fonte
        backup_res = production_backup.create_database_backup(
            db_path=self.source_db,
            backup_dir=self.backup_dir,
        )
        self.valid_backup_path = backup_res["database_path"]
        self.valid_manifest_path = backup_res["manifest_path"]

        # 3. Cria banco destino com estado inicial que será sobrescrito
        conn_tgt = sqlite3.connect(self.target_db)
        try:
            conn_tgt.execute("CREATE TABLE records (key TEXT, val TEXT);")
            conn_tgt.execute("INSERT INTO records VALUES ('target_key', 'initial_target_state_000');")
            conn_tgt.commit()
        finally:
            conn_tgt.close()

    def tearDown(self):
        self.tmp_dir.cleanup()

    # 11. Restauração bem-sucedida de backup válido em banco temporário
    def test_11_restore_valid_backup_into_target(self):
        res = production_recovery.restore_database_backup(
            backup_file_path=self.valid_backup_path,
            target_db_path=self.target_db,
            safety_copy_dir=self.safety_dir,
            check_active_server=False,
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["integrity_check"], "ok")

        # Verifica que os dados no banco destino são agora os do backup
        conn = sqlite3.connect(self.target_db)
        try:
            row = conn.execute("SELECT val FROM records WHERE key = 'source_key';").fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "restored_content_999")
        finally:
            conn.close()

    # 12. Backup corrompido é rejeitado
    def test_12_corrupted_backup_rejected(self):
        corrupt_db = os.path.join(self.backup_dir, "corrupt.db")
        with open(corrupt_db, "wb") as f:
            f.write(b"NOT_A_VALID_SQLITE_HEADER_DATA_123456789")

        with self.assertRaises(ValueError) as ctx:
            production_recovery.restore_database_backup(
                backup_file_path=corrupt_db,
                target_db_path=self.target_db,
                safety_copy_dir=self.safety_dir,
                check_active_server=False,
            )
        self.assertIn("inválido ou corrompido", str(ctx.exception))

        # Confere que o banco destino permaneceu inalterado
        conn = sqlite3.connect(self.target_db)
        try:
            row = conn.execute("SELECT val FROM records WHERE key = 'target_key';").fetchone()
            self.assertEqual(row[0], "initial_target_state_000")
        finally:
            conn.close()

    # 13. SHA mismatch é rejeitado
    def test_13_sha_mismatch_rejected(self):
        # Altera o manifesto para um hash inválido
        with open(self.valid_manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        manifest["sha256"] = "0000000000000000000000000000000000000000000000000000000000000000"
        with open(self.valid_manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f)

        with self.assertRaises(ValueError) as ctx:
            production_recovery.restore_database_backup(
                backup_file_path=self.valid_backup_path,
                target_db_path=self.target_db,
                safety_copy_dir=self.safety_dir,
                check_active_server=False,
            )
        self.assertIn("SHA-256 mismatch", str(ctx.exception))

    # 14. Safety copy é criada
    def test_14_safety_copy_created(self):
        res = production_recovery.restore_database_backup(
            backup_file_path=self.valid_backup_path,
            target_db_path=self.target_db,
            safety_copy_dir=self.safety_dir,
            check_active_server=False,
        )
        safety_path = res["safety_copy"]
        self.assertIsNotNone(safety_path)
        self.assertTrue(os.path.isfile(safety_path))

        # A safety copy deve conter os dados ANTERIORES do destino
        conn = sqlite3.connect(safety_path)
        try:
            row = conn.execute("SELECT val FROM records WHERE key = 'target_key';").fetchone()
            self.assertEqual(row[0], "initial_target_state_000")
        finally:
            conn.close()

    # 15. Falha anterior ao atomic replace preserva DB original
    def test_15_failure_before_replace_preserves_original(self):
        # Simula erro de integridade ao verificar o arquivo temporário restaurado
        original_verify = production_backup.verify_database_backup

        def mock_verify(path):
            if "tmp_restore" in path:
                return {"valid": False, "error": "SIMULATED_COPY_CORRUPTION"}
            return original_verify(path)

        with patch.object(production_backup, "verify_database_backup", side_effect=mock_verify):
            with self.assertRaises(RuntimeError) as ctx:
                production_recovery.restore_database_backup(
                    backup_file_path=self.valid_backup_path,
                    target_db_path=self.target_db,
                    safety_copy_dir=self.safety_dir,
                    check_active_server=False,
                )
            self.assertIn("SIMULATED_COPY_CORRUPTION", str(ctx.exception))

        # Destino original permanece intacto
        conn = sqlite3.connect(self.target_db)
        try:
            row = conn.execute("SELECT val FROM records WHERE key = 'target_key';").fetchone()
            self.assertEqual(row[0], "initial_target_state_000")
        finally:
            conn.close()

    # 16. integrity_check pós-restore executado
    def test_16_post_restore_integrity_check(self):
        res = production_recovery.restore_database_backup(
            backup_file_path=self.valid_backup_path,
            target_db_path=self.target_db,
            safety_copy_dir=self.safety_dir,
            check_active_server=False,
        )
        self.assertEqual(res["integrity_check"], "ok")

        # Verifica integridade diretamente no banco final restaurado
        final_check = production_backup.verify_database_backup(self.target_db)
        self.assertTrue(final_check["valid"])
        self.assertEqual(final_check["integrity"], "ok")

    # 17. Arquivos temporários são limpos
    def test_17_temp_restore_files_cleaned(self):
        production_recovery.restore_database_backup(
            backup_file_path=self.valid_backup_path,
            target_db_path=self.target_db,
            safety_copy_dir=self.safety_dir,
            check_active_server=False,
        )
        target_dir = os.path.dirname(self.target_db)
        temp_files = [f for f in os.listdir(target_dir) if "tmp_restore" in f]
        self.assertEqual(len(temp_files), 0, f"Arquivos temporários remanescentes: {temp_files}")

    # 18. Proteção contra restauração com backend ativo
    def test_18_active_backend_protection_blocks_restore(self):
        # Simula backend ativo detectado
        with patch.object(production_recovery, "is_backend_active", return_value=(True, "Simulated active Streamlit server")):
            with self.assertRaises(RuntimeError) as ctx:
                production_recovery.restore_database_backup(
                    backup_file_path=self.valid_backup_path,
                    target_db_path=self.target_db,
                    safety_copy_dir=self.safety_dir,
                    check_active_server=True,
                    force=False,
                )
            self.assertIn("RESTAURAÇÃO BLOQUEADA POR SEGURANÇA", str(ctx.exception))

            # Com flag force=True, a restauração é permitida (caso o operador decida forçar)
            res_forced = production_recovery.restore_database_backup(
                backup_file_path=self.valid_backup_path,
                target_db_path=self.target_db,
                safety_copy_dir=self.safety_dir,
                check_active_server=True,
                force=True,
            )
            self.assertTrue(res_forced["success"])


if __name__ == "__main__":
    unittest.main()
