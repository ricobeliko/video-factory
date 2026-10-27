import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.audit_voices import (
    _compute_file_sha256,
    _create_ro_temp_backup,
    _mask_secrets,
    audit_channel_voices,
    load_masked_config,
)


class TestAuditVoicesReadOnlyAndMasking(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_audit_voices_")
        self.db_path = os.path.join(self.temp_dir, "test_video_factory.db")
        self.config_path = os.path.join(self.temp_dir, "test_config.toml")
        self.tasks_dir = os.path.join(self.temp_dir, "tasks")
        os.makedirs(self.tasks_dir, exist_ok=True)

        # 1. Cria banco SQLite com esquema mínimo de content_profiles e task_profiles
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE content_profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                slug TEXT,
                niche TEXT,
                language TEXT DEFAULT 'pt-BR',
                region TEXT DEFAULT 'BR',
                default_preset TEXT DEFAULT 'monetized_strict',
                growth_mode TEXT DEFAULT 'STANDARD',
                is_active INTEGER DEFAULT 1,
                settings_json TEXT,
                created_at TEXT,
                updated_at TEXT
            );
        """)
        cur.execute("""
            CREATE TABLE task_profiles (
                task_id TEXT PRIMARY KEY,
                profile_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
        cur.execute("""
            CREATE TABLE operational_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                component TEXT NOT NULL,
                severity TEXT NOT NULL,
                event_type TEXT NOT NULL,
                task_id TEXT,
                message TEXT,
                metadata_json TEXT
            );
        """)

        # Perfil 1: Tradicional com voz Francisca no perfil
        cur.execute("""
            INSERT INTO content_profiles (id, name, is_active, settings_json)
            VALUES (?, ?, ?, ?);
        """, (
            "curiosidades_br",
            "Canal Curiosidades",
            1,
            json.dumps({
                "editorial": {"video_format": "traditional"},
                "voice": {"voice_name": "pt-BR-FranciscaNeural", "voice_rate": 1.0, "voice_volume": 1.0},
            }),
        ))

        # Perfil 2: Quiz Dilemma com voz nula no perfil (para testar fallback de quiz)
        cur.execute("""
            INSERT INTO content_profiles (id, name, is_active, settings_json)
            VALUES (?, ?, ?, ?);
        """, (
            "quiz_dilemas",
            "Canal Quiz Dilemas",
            1,
            json.dumps({
                "editorial": {"video_format": "quiz_dilemma", "narrative_structure": "quiz_dilemma"},
                "voice": {"voice_name": None, "voice_rate": 1.0, "voice_volume": 1.0},
            }),
        ))

        # Tarefa com voz gravada Brian (inconsistente com Francisca)
        cur.execute("""
            INSERT INTO task_profiles (task_id, profile_id, created_at)
            VALUES (?, ?, ?);
        """, ("task_001", "curiosidades_br", "2026-10-26T20:00:00Z"))

        t_dir = os.path.join(self.tasks_dir, "task_001")
        os.makedirs(t_dir, exist_ok=True)
        with open(os.path.join(t_dir, "script.json"), "w", encoding="utf-8") as sf:
            json.dump({
                "script": "Texto de teste",
                "params": {"voice_name": "en-US-BrianMultilingualNeural", "profile_id": "curiosidades_br"},
                "tts_diagnostic": {"provider": "azure-tts-v1", "voice_name": "en-US-BrianMultilingualNeural"},
            }, sf)
        with open(os.path.join(t_dir, "audio.mp3"), "wb") as af:
            af.write(b"FAKE_AUDIO_DATA_BYTES")

        conn.commit()
        conn.close()

        # 2. Cria config.toml com segredos a serem mascarados
        with open(self.config_path, "w", encoding="utf-8") as cf:
            cf.write("""
[app]
voice_name = "en-US-BrianMultilingualNeural"
api_key = "SUPER_SECRET_APP_KEY_12345"

[ui]
voice_name = "pt-BR-FranciscaNeural"
tts_server = "azure-tts-v1"
secret_token = "TOP_SECRET_UI_TOKEN_99999"

[deepseek]
api_key = "sk-deepseek-sensitive-credential-abcdef"
""")

    def tearDown(self):
        try:
            shutil.rmtree(self.temp_dir)
        except OSError:
            pass

    def test_audit_voices_read_only_and_masks_secrets(self):
        """Valida que audit_voices não escreve no banco original e mascara segredos rigorosamente."""
        initial_sha = _compute_file_sha256(self.db_path)
        initial_mtime = os.path.getmtime(self.db_path)

        # 1. Testa mascaramento de segredos
        masked_cfg, extracted = load_masked_config(self.config_path)
        cfg_str = json.dumps(masked_cfg)

        self.assertNotIn("SUPER_SECRET_APP_KEY_12345", cfg_str)
        self.assertNotIn("TOP_SECRET_UI_TOKEN_99999", cfg_str)
        self.assertNotIn("sk-deepseek-sensitive-credential-abcdef", cfg_str)
        self.assertIn("***MASKED***", cfg_str)

        # 2. Cria backup temporário somente-leitura e roda a auditoria
        temp_db_path, bkp_sha, bkp_mtime = _create_ro_temp_backup(self.db_path)
        try:
            report = audit_channel_voices(
                db_path=temp_db_path,
                config_path=self.config_path,
                tasks_dir=self.tasks_dir,
            )

            # Validações do relatório
            self.assertEqual(len(report["channels"]), 2)

            ch1 = next(c for c in report["channels"] if c["profile_id"] == "curiosidades_br")
            self.assertEqual(ch1["layer_a_config"]["config_ui_voice_name"], "pt-BR-FranciscaNeural")
            self.assertEqual(ch1["layer_b_profile_context"]["resolved_voice_name"], "pt-BR-FranciscaNeural")
            self.assertEqual(ch1["layer_c_autonomous_params"]["resolved_voice_name"], "pt-BR-FranciscaNeural")

            # Camada E: task_001 gravada com Brian deve ser INCONSISTENTE
            self.assertEqual(len(ch1["layer_e_last_tasks"]), 1)
            t1 = ch1["layer_e_last_tasks"][0]
            self.assertEqual(t1["task_id"], "task_001")
            self.assertEqual(t1["effective_recorded_voice"], "en-US-BrianMultilingualNeural")
            self.assertEqual(t1["status"], "INCONSISTENTE")
            self.assertTrue(t1["has_audio_mp3"])

            ch2 = next(c for c in report["channels"] if c["profile_id"] == "quiz_dilemas")
            self.assertTrue(ch2["layer_d_quiz_specifics"]["is_quiz_pipeline"])
            self.assertEqual(ch2["layer_d_quiz_specifics"]["export_to_quiz_config_fallback"], "pt-BR-AntonioNeural")

            # Nenhum segredo presente no relatório exportado
            report_str = json.dumps(report)
            self.assertNotIn("SUPER_SECRET_APP_KEY_12345", report_str)
            self.assertNotIn("TOP_SECRET_UI_TOKEN_99999", report_str)
            self.assertNotIn("sk-deepseek-sensitive-credential-abcdef", report_str)

        finally:
            import gc
            gc.collect()
            if os.path.exists(temp_db_path):
                try:
                    os.remove(temp_db_path)
                except OSError:
                    pass

        # 3. Garante que o banco de dados original permaneceu 100% INALTERADO
        final_sha = _compute_file_sha256(self.db_path)
        final_mtime = os.path.getmtime(self.db_path)
        self.assertEqual(initial_sha, final_sha, "O hash SHA-256 do banco de dados foi modificado!")
        self.assertEqual(initial_mtime, final_mtime, "O timestamp mtime do banco de dados foi alterado!")


if __name__ == "__main__":
    unittest.main()
