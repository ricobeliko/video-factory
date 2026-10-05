"""Test suite direcionada para Auditoria e Reset de Publicações Pendentes (Fase V16.4.2R).

Valida:
1. Pré-condições de segurança (scheduler_enabled=False, auto_publish_enabled=False).
2. Desativação administrativa segura de pré-condições.
3. Inventário preciso de posts pendentes, sucessos publicados e anomalias.
4. Dry-run estritamente somente leitura (zero mutações).
5. Execução real controlada:
   - Exigência de confirm_token
   - Criação de backup consistente físico com SHA-256 e integrity_check
   - Neutralização de planned, ready, queued e stale processing
   - Desarmamento de retries (next_attempt_at = NULL)
   - Neutralização de duplicatas pendentes
   - Preservação integral de publication_events com status='success' e posts 'published'
   - Auditoria operacional gravada em operational_events
   - Verificação pós-reset: EXECUTABLE_PENDING_PUBLICATIONS = 0, ARMED_RETRIES = 0, STALE_PROCESSING = 0.
"""

import os
import shutil
import tempfile
import unittest

from app.services import publication_reset, scheduler


class TestPublicationReset(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_pub_reset_")
        self.db_path = os.path.join(self.temp_dir, "test_video_factory.db")
        self.backup_dir = os.path.join(self.temp_dir, "backups")
        scheduler.init_db(self.db_path)
        self._populate_test_data()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _populate_test_data(self):
        with scheduler.get_connection(self.db_path) as conn:
            # 1. autopilot_settings (inicialmente disabled para testes normais)
            conn.execute("INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES ('scheduler_enabled', 'false');")
            conn.execute("INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES ('auto_publish_enabled', 'false');")
            conn.execute("INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES ('dry_run', 'true');")

            # 2. scheduled_posts:
            # - Post 1: planned no futuro
            conn.execute(
                """
                INSERT INTO scheduled_posts (id, task_id, platform, scheduled_at, status, created_at, attempts, next_attempt_at)
                VALUES (1, 'task-planned', 'youtube', '2026-10-10T12:00:00+00:00', 'planned', '2026-09-16T12:00:00+00:00', 0, NULL);
                """
            )
            # - Post 2: ready no passado (due) com next_attempt_at armado
            conn.execute(
                """
                INSERT INTO scheduled_posts (id, task_id, platform, scheduled_at, status, created_at, attempts, next_attempt_at)
                VALUES (2, 'task-ready-due', 'youtube', '2026-09-17T10:00:00+00:00', 'ready', '2026-09-16T12:00:00+00:00', 1, '2026-09-17T10:30:00+00:00');
                """
            )
            # - Post 3: stale processing
            conn.execute(
                """
                INSERT INTO scheduled_posts (id, task_id, platform, scheduled_at, status, created_at, attempts, next_attempt_at)
                VALUES (3, 'task-stale-proc', 'youtube', '2026-09-17T09:00:00+00:00', 'processing', '2026-09-16T12:00:00+00:00', 1, NULL);
                """
            )
            # - Post 4: failed com retry armado
            conn.execute(
                """
                INSERT INTO scheduled_posts (id, task_id, platform, scheduled_at, status, created_at, attempts, next_attempt_at, last_error)
                VALUES (4, 'task-failed-retry', 'tiktok', '2026-09-17T08:00:00+00:00', 'failed', '2026-09-16T12:00:00+00:00', 2, '2026-09-17T08:30:00+00:00', 'Upload timeout');
                """
            )
            # - Post 5: published com sucesso legítimo
            conn.execute(
                """
                INSERT INTO scheduled_posts (id, task_id, platform, scheduled_at, status, created_at, attempts, next_attempt_at)
                VALUES (5, 'task-already-pub', 'youtube', '2026-09-16T12:00:00+00:00', 'published', '2026-09-16T12:00:00+00:00', 1, NULL);
                """
            )
            # - Post 6: pendente no tiktok para tarefa que já teve sucesso no tiktok
            conn.execute(
                """
                INSERT INTO scheduled_posts (id, task_id, platform, scheduled_at, status, created_at, attempts, next_attempt_at)
                VALUES (6, 'task-already-pub', 'tiktok', '2026-09-17T12:00:00+00:00', 'ready', '2026-09-16T12:00:00+00:00', 0, '2026-09-17T12:00:00+00:00');
                """
            )

            # 3. publication_events:
            conn.execute(
                """
                INSERT INTO publication_events (id, task_id, platform, published_at, status, external_id)
                VALUES (1, 'task-already-pub', 'youtube', '2026-09-16T12:05:00+00:00', 'success', 'yt-ext-123');
                """
            )
            conn.execute(
                """
                INSERT INTO publication_events (id, task_id, platform, published_at, status, external_id)
                VALUES (2, 'task-orphan-success', 'youtube', '2026-09-15T12:00:00+00:00', 'success', 'yt-orphan-456');
                """
            )
            conn.execute(
                """
                INSERT INTO publication_events (id, task_id, platform, published_at, status, error_code)
                VALUES (3, 'task-failed-retry', 'tiktok', '2026-09-17T08:00:00+00:00', 'failed', 'ERR_TIMEOUT');
                """
            )
            conn.execute(
                """
                INSERT INTO publication_events (id, task_id, platform, published_at, status, external_id)
                VALUES (4, 'task-already-pub', 'tiktok', '2026-09-16T12:06:00+00:00', 'success', 'tt-ext-999');
                """
            )

    def test_preconditions_check_and_disable(self):
        # 1. Com ambos False, passa
        pre = publication_reset.check_reset_preconditions(self.db_path)
        self.assertTrue(pre["passed"])
        self.assertFalse(pre["scheduler_enabled"])
        self.assertFalse(pre["auto_publish_enabled"])

        # 2. Ativa scheduler_enabled e verifica fail-closed
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute("UPDATE autopilot_settings SET value = 'true' WHERE key = 'scheduler_enabled';")

        pre_fail = publication_reset.check_reset_preconditions(self.db_path)
        self.assertFalse(pre_fail["passed"])
        self.assertTrue(pre_fail["scheduler_enabled"])
        self.assertIn("scheduler_enabled está ativo", pre_fail["errors"][0])

        # 3. Usa disable_scheduler_preconditions
        fixed_pre = publication_reset.disable_scheduler_preconditions(self.db_path)
        self.assertTrue(fixed_pre["passed"])
        self.assertFalse(fixed_pre["scheduler_enabled"])

    def test_inventory_before_reset(self):
        inv = publication_reset.inventory_before_reset(self.db_path)
        self.assertEqual(inv["pending_count"], 5)  # posts 1, 2, 3, 4, 6
        self.assertEqual(inv["total_publication_events"], 4)
        self.assertEqual(inv["success_publication_events_count"], 3)
        self.assertEqual(inv["failed_publication_events_count"], 1)

        # Anomalia detectada: post 6 é pendente para tarefa já publicada
        self.assertEqual(len(inv["pending_with_existing_success"]), 1)
        self.assertEqual(inv["pending_with_existing_success"][0]["scheduled_post_id"], 6)

        # Anomalia detectada: eventos de sucesso sem post 'published' coerente (eventos 2 e 4)
        self.assertEqual(len(inv["success_without_coherent_post"]), 2)
        orphan_tids = {item["task_id"] for item in inv["success_without_coherent_post"]}
        self.assertIn("task-orphan-success", orphan_tids)
        self.assertIn("task-already-pub", orphan_tids)

    def test_dry_run_zero_mutations(self):
        res = publication_reset.reset_pending_publications(
            db_path=self.db_path,
            dry_run=True,
        )
        self.assertTrue(res["dry_run"])
        self.assertIsNone(res["backup_info"])
        self.assertEqual(res["would_cancel_planned"], 3)  # posts 1, 2, 6
        self.assertEqual(res["would_cancel_processing"], 1)  # post 3
        self.assertEqual(res["would_disarm_retries"], 1)  # post 4
        self.assertEqual(res["would_clear_next_attempt"], 3)  # posts 2, 4, 6
        self.assertEqual(res["already_published_preserved"], 1)  # post 5

        # Garante zero mutações no banco
        with scheduler.get_connection(self.db_path) as conn:
            row1 = conn.execute("SELECT status FROM scheduled_posts WHERE id = 1;").fetchone()
            self.assertEqual(row1["status"], "planned")
            row3 = conn.execute("SELECT status FROM scheduled_posts WHERE id = 3;").fetchone()
            self.assertEqual(row3["status"], "processing")
            row4 = conn.execute("SELECT next_attempt_at FROM scheduled_posts WHERE id = 4;").fetchone()
            self.assertIsNotNone(row4["next_attempt_at"])

    def test_real_reset_execution_and_invariants(self):
        # 1. Rejeita sem confirm_token
        with self.assertRaises(ValueError):
            publication_reset.reset_pending_publications(
                db_path=self.db_path,
                dry_run=False,
                confirm_token="INVALID_TOKEN",
                backup_dir=self.backup_dir,
            )

        # 2. Executa reset com confirmação correta
        res = publication_reset.reset_pending_publications(
            db_path=self.db_path,
            dry_run=False,
            confirm_token="RESET_PENDING_PUBLICATIONS",
            backup_dir=self.backup_dir,
        )
        self.assertFalse(res["dry_run"])
        self.assertIsNotNone(res["backup_info"])
        self.assertTrue(os.path.isfile(res["backup_info"]["backup_file"]))
        self.assertEqual(res["backup_info"]["integrity"], "ok")

        # 3. Comprova invariantes de auditoria após reset
        after = res["after_audit"]
        self.assertEqual(after["executable_pending_publications"], 0)
        self.assertEqual(after["armed_retries"], 0)
        self.assertEqual(after["stale_processing"], 0)
        self.assertEqual(after["published_posts_count"], 1)  # post 5 preservado
        self.assertEqual(after["cancelled_posts_count"], 5)  # posts 1, 2, 3, 4, 6 cancelados
        self.assertTrue(after["published_success_records_preserved"])
        self.assertEqual(after["media_files_deleted"], 0)

        # 4. Verifica registros diretamente no SQLite
        with scheduler.get_connection(self.db_path) as conn:
            # Post 5 mantido published
            p5 = conn.execute("SELECT status, next_attempt_at FROM scheduled_posts WHERE id = 5;").fetchone()
            self.assertEqual(p5["status"], "published")
            self.assertIsNone(p5["next_attempt_at"])

            # Posts 1, 2, 3, 4, 6 cancelados sem next_attempt_at
            for pid in [1, 2, 3, 4, 6]:
                row = conn.execute("SELECT status, next_attempt_at FROM scheduled_posts WHERE id = ?;", (pid,)).fetchone()
                self.assertEqual(row["status"], "cancelled")
                self.assertIsNone(row["next_attempt_at"])

            # Publication events intactos (3 sucessos mantidos)
            succ_cnt = conn.execute("SELECT COUNT(*) AS cnt FROM publication_events WHERE status = 'success';").fetchone()["cnt"]
            self.assertEqual(succ_cnt, 3)

            # Operational events gravados
            op_events = conn.execute(
                "SELECT COUNT(*) AS cnt FROM operational_events WHERE event_type = 'PRE_REPAIR_PUBLICATION_RESET';"
            ).fetchone()["cnt"]
            self.assertEqual(op_events, 5)

    def test_preconditions_block_real_reset(self):
        # Ativa scheduler
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute("UPDATE autopilot_settings SET value = 'true' WHERE key = 'scheduler_enabled';")

        with self.assertRaises(publication_reset.PreconditionError):
            publication_reset.reset_pending_publications(
                db_path=self.db_path,
                dry_run=False,
                confirm_token="RESET_PENDING_PUBLICATIONS",
                backup_dir=self.backup_dir,
            )


if __name__ == "__main__":
    unittest.main()
