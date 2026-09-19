"""
Test Suite para o Serviço de Backup Seguro e Retenção do SQLite (Fase V12-C).

Cobre:
1. Criação de backup consistente de banco temporário
2. Backup funciona com banco fonte aberto em modo WAL e transações ativas
3. PRAGMA integrity_check retorna 'ok'
4. Hash SHA-256 no manifesto sidecar confere exatamente com o arquivo .db
5. Arquivo temporário (.tmp) é limpo em caso de sucesso
6. Falha no backup preserva backup anterior e banco original intactos
7. Política de retenção mantém exatamente a quantidade configurada
8. Retenção nunca apaga arquivos estranhos ou não reconhecidos
9. Listagem de backups ordenada decrescente por data/hora
10. Manifesto sidecar não contém segredos, tokens ou dumps de configuração
"""
import json
import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from app.services import production_backup


class TestProductionBackup(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = os.path.join(self.tmp_dir.name, "source_video_factory.db")
        self.test_backup_dir = os.path.join(self.tmp_dir.name, "backups")
        os.makedirs(self.test_backup_dir, exist_ok=True)

        # Inicializa banco SQLite fonte em modo WAL com dados
        conn = sqlite3.connect(self.test_db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("CREATE TABLE test_data (id INTEGER PRIMARY KEY, content TEXT);")
            conn.execute("INSERT INTO test_data (content) VALUES ('initial_seed_1');")
            conn.execute("INSERT INTO test_data (content) VALUES ('initial_seed_2');")
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        self.tmp_dir.cleanup()

    # 1. Cria backup válido de DB temporário
    def test_01_create_valid_backup_of_temp_db(self):
        res = production_backup.create_database_backup(
            db_path=self.test_db_path,
            backup_dir=self.test_backup_dir,
            retention_count=10,
        )
        self.assertTrue(res["success"])
        self.assertTrue(os.path.isfile(res["database_path"]))
        self.assertTrue(os.path.isfile(res["manifest_path"]))
        self.assertEqual(res["integrity_check"], "ok")
        self.assertGreater(res["size_bytes"], 0)

    # 2. Backup funciona com source DB aberto em modo WAL
    def test_02_backup_works_with_active_wal_connection(self):
        # Mantém conexão aberta fazendo escritas concorrentes
        active_conn = sqlite3.connect(self.test_db_path)
        try:
            active_conn.execute("INSERT INTO test_data (content) VALUES ('wal_concurrent_item');")
            active_conn.commit()

            res = production_backup.create_database_backup(
                db_path=self.test_db_path,
                backup_dir=self.test_backup_dir,
            )
            self.assertTrue(res["success"])

            # Valida que o dado inserido durante a conexão ativa está no backup
            b_conn = sqlite3.connect(res["database_path"])
            try:
                cnt = b_conn.execute("SELECT count(*) FROM test_data;").fetchone()[0]
                self.assertEqual(cnt, 3)
            finally:
                b_conn.close()
        finally:
            active_conn.close()

    # 3. integrity_check retorna ok
    def test_03_integrity_check_returns_ok(self):
        res = production_backup.create_database_backup(
            db_path=self.test_db_path,
            backup_dir=self.test_backup_dir,
        )
        verify = production_backup.verify_database_backup(res["database_path"])
        self.assertTrue(verify["valid"])
        self.assertEqual(verify["integrity"], "ok")
        self.assertTrue(verify["manifest_matched"])

    # 4. SHA256 do manifest corresponde ao arquivo
    def test_04_manifest_sha256_matches_file(self):
        res = production_backup.create_database_backup(
            db_path=self.test_db_path,
            backup_dir=self.test_backup_dir,
        )
        with open(res["manifest_path"], "r", encoding="utf-8") as f:
            manifest_data = json.load(f)

        actual_sha = production_backup._calculate_sha256(res["database_path"])
        self.assertEqual(manifest_data["sha256"], actual_sha)

    # 5. Arquivo temporário não permanece após sucesso
    def test_05_temp_file_cleaned_up_on_success(self):
        production_backup.create_database_backup(
            db_path=self.test_db_path,
            backup_dir=self.test_backup_dir,
        )
        files = os.listdir(self.test_backup_dir)
        temp_files = [f for f in files if ".tmp" in f]
        self.assertEqual(len(temp_files), 0, f"Arquivos temporários encontrados: {temp_files}")

    # 6. Falha no backup preserva backup anterior e banco fonte
    def test_06_failed_backup_preserves_previous_backup(self):
        # 1º backup com sucesso
        first_res = production_backup.create_database_backup(
            db_path=self.test_db_path,
            backup_dir=self.test_backup_dir,
        )
        first_db = first_res["database_path"]
        first_manifest = first_res["manifest_path"]

        # Força erro de integridade na 2ª tentativa
        with patch.object(production_backup, "verify_database_backup", return_value={"valid": False, "error": "CORRUPTED_MOCK"}):
            with self.assertRaises(RuntimeError):
                production_backup.create_database_backup(
                    db_path=self.test_db_path,
                    backup_dir=self.test_backup_dir,
                )

        # O primeiro backup e seu manifesto continuam intactos
        self.assertTrue(os.path.isfile(first_db))
        self.assertTrue(os.path.isfile(first_manifest))

        # O banco fonte continua íntegro e legível
        conn = sqlite3.connect(self.test_db_path)
        try:
            cnt = conn.execute("SELECT count(*) FROM test_data;").fetchone()[0]
            self.assertEqual(cnt, 2)
        finally:
            conn.close()

    # 7. Retenção mantém exatamente a quantidade configurada
    def test_07_retention_maintains_configured_count(self):
        # Gera 4 backups simulando timestamps distintos
        for i in range(4):
            time.sleep(1.05)  # Garante avanço de timestamp no nome de arquivo
            production_backup.create_database_backup(
                db_path=self.test_db_path,
                backup_dir=self.test_backup_dir,
                retention_count=2,  # Retém apenas os 2 mais recentes
            )

        backups = production_backup.list_database_backups(self.test_backup_dir)
        self.assertEqual(len(backups), 2)

    # 8. Retenção não apaga arquivos estranhos
    def test_08_retention_preserves_alien_files(self):
        alien_txt = os.path.join(self.test_backup_dir, "important_notes.txt")
        with open(alien_txt, "w", encoding="utf-8") as f:
            f.write("dados_externos_preservados")

        alien_json = os.path.join(self.test_backup_dir, "custom_config.json")
        with open(alien_json, "w", encoding="utf-8") as f:
            f.write("{}")

        # Gera backups com retenção baixa
        for _ in range(3):
            time.sleep(1.05)
            production_backup.create_database_backup(
                db_path=self.test_db_path,
                backup_dir=self.test_backup_dir,
                retention_count=1,
            )

        # Arquivos estranhos devem continuar existindo
        self.assertTrue(os.path.isfile(alien_txt))
        self.assertTrue(os.path.isfile(alien_json))

    # 9. Listagem ordenada decrescente por data/hora
    def test_09_list_backups_sorted_descending(self):
        for _ in range(3):
            time.sleep(1.05)
            production_backup.create_database_backup(
                db_path=self.test_db_path,
                backup_dir=self.test_backup_dir,
                retention_count=10,
            )

        backups = production_backup.list_database_backups(self.test_backup_dir)
        self.assertEqual(len(backups), 3)

        timestamps = [b["created_at"] for b in backups]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))

    # 10. Nenhum segredo ou token no manifesto
    def test_10_manifest_contains_zero_secrets(self):
        res = production_backup.create_database_backup(
            db_path=self.test_db_path,
            backup_dir=self.test_backup_dir,
        )
        with open(res["manifest_path"], "r", encoding="utf-8") as f:
            content = f.read()
            manifest = json.loads(content)

        # Campos permitidos no schema
        allowed_fields = {
            "schema_version",
            "created_at",
            "database_file",
            "size_bytes",
            "sha256",
            "integrity_check",
            "source_database",
            "app_version",
        }
        self.assertTrue(set(manifest.keys()).issubset(allowed_fields))

        forbidden_tokens = ["api_key", "secret", "password", "token", "credential", "auth"]
        for term in forbidden_tokens:
            self.assertNotIn(term, content.lower())


if __name__ == "__main__":
    unittest.main()
