# -*- coding: utf-8 -*-
"""
Testes Direcionados — Fase V2.13 (Ensaio de Migração e Compatibilidade de Dados)
"""

import os
import unittest
import sqlite3
import tempfile
import shutil
from scripts import rehearse_v2_migration
from app.services import profile_manager, scheduler

class TestV213MigrationRehearsal(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="v2_13_rehearsal_")
        self.source_db = os.path.join(self.test_dir, "legacy_source.db")
        self.target_db = os.path.join(self.test_dir, "migrated_target.db")
        self.backup_db = os.path.join(self.test_dir, "pre_backup.db")
        rehearse_v2_migration.create_legacy_synthetic_db(self.source_db)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_legacy_schema_structure(self):
        with sqlite3.connect(self.source_db) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(content_profiles);").fetchall()}
            self.assertNotIn("settings_json", cols)
            ch_cols = {r[1] for r in conn.execute("PRAGMA table_info(publishing_channels);").fetchall()}
            self.assertNotIn("external_account_id", ch_cols)
            self.assertNotIn("project_id", ch_cols)

    def test_migration_rehearsal_full_lifecycle(self):
        res = rehearse_v2_migration.run_migration_rehearsal(
            self.source_db, self.target_db, self.backup_db
        )
        self.assertEqual(res["status"], "PASS")
        self.assertEqual(res["profiles_count"], 3)
        self.assertEqual(res["channels_count"], 5)
        self.assertEqual(res["integrity"], "ok")
        self.assertEqual(res["idempotency"], "PASS")
        self.assertEqual(res["rollback"], "PASS")

    def test_migrated_channels_settings_and_multiproject(self):
        rehearse_v2_migration.run_migration_rehearsal(
            self.source_db, self.target_db, self.backup_db
        )
        profiles = profile_manager.list_profiles(db_path=self.target_db)
        self.assertEqual(len(profiles), 3)

        # Verificar canais e formatos
        p_map = {p["id"]: p for p in profiles}
        self.assertIn("legacy_curiosidades", p_map)
        self.assertIn("legacy_quiz_biblico", p_map)
        self.assertIn("legacy_misterios", p_map)

        st_curio = profile_manager.get_profile_settings("legacy_curiosidades", db_path=self.target_db)
        self.assertEqual(st_curio.editorial.video_format, "traditional")
        self.assertEqual(st_curio.voice.voice_name, "pt-BR-AntonioNeural")

        st_quiz = profile_manager.get_profile_settings("legacy_quiz_biblico", db_path=self.target_db)
        self.assertEqual(st_quiz.editorial.video_format, "quiz_dilemma")
        self.assertEqual(st_quiz.voice.voice_name, "pt-BR-FranciscaNeural")

        st_mist = profile_manager.get_profile_settings("legacy_misterios", db_path=self.target_db)
        self.assertEqual(st_mist.editorial.video_format, "quiz_paper")
        self.assertEqual(st_mist.voice.voice_name, "pt-BR-AntonioNeural")

        # Verificar canais vinculados e multiprojeto
        channels = profile_manager.list_channels(db_path=self.target_db)
        self.assertEqual(len(channels), 5)
        for ch in channels:
            self.assertTrue(ch.get("external_account_id"))
            self.assertTrue(ch.get("project_id"))

    def test_scheduled_posts_and_tasks_preserved(self):
        rehearse_v2_migration.run_migration_rehearsal(
            self.source_db, self.target_db, self.backup_db
        )
        with sqlite3.connect(self.target_db) as conn:
            sched_count = conn.execute("SELECT COUNT(*) FROM scheduled_posts;").fetchone()[0]
            self.assertEqual(sched_count, 3)
            task_count = conn.execute("SELECT COUNT(*) FROM task_profiles;").fetchone()[0]
            self.assertEqual(task_count, 4)
            pub_count = conn.execute("SELECT COUNT(*) FROM publication_events;").fetchone()[0]
            self.assertEqual(pub_count, 1)

if __name__ == "__main__":
    unittest.main()
