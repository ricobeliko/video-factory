"""Test suite direcionada para Auditoria e Reset de Publicações Pendentes (Fases V16.4.2R / V16.4.2R.1).

Valida estritamente em banco isolado temporário:
1. published + success + next_attempt_at -> continua published, next_attempt_at=NULL (normalizado).
2. published + success + attempts > 0 -> continua published, attempts preservado.
3. failed + success -> não pode voltar à fila, histórico preservado (status='failed', next_attempt_at=NULL).
4. planned sem success -> cancelled.
5. stale processing -> cancelled.
6. duplicate schedules + success -> nenhum executável, publicação canônica preservada.
7. dry-run reproduz exatamente essas regras sem realizar nenhuma mutação no banco.
8. active_primary=true em instance_locks bloqueia execução real com PreconditionError.
"""

import os
import shutil
import tempfile
import unittest

from app.services import operator_console, publication_reset, scheduler


class TestPublicationReset(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_pub_reset_")
        self.db_path = os.path.join(self.temp_dir, "test_video_factory.db")
        self.backup_dir = os.path.join(self.temp_dir, "backups")
        scheduler.init_db(self.db_path)
        operator_console.init_operator_db(self.db_path)
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
            # - Post 1: planned no futuro sem success (Caso 4)
            conn.execute(
                """
                INSERT INTO scheduled_posts (id, task_id, platform, scheduled_at, status, created_at, attempts, next_attempt_at)
                VALUES (1, 'task-planned', 'youtube', '2026-10-10T12:00:00+00:00', 'planned', '2026-09-16T12:00:00+00:00', 0, NULL);
                """
            )
            # - Post 2: ready no passado sem success
            conn.execute(
                """
                INSERT INTO scheduled_posts (id, task_id, platform, scheduled_at, status, created_at, attempts, next_attempt_at)
                VALUES (2, 'task-ready-due', 'youtube', '2026-09-17T10:00:00+00:00', 'ready', '2026-09-16T12:00:00+00:00', 1, '2026-09-17T10:30:00+00:00');
                """
            )
            # - Post 3: stale processing (Caso 5)
            conn.execute(
                """
                INSERT INTO scheduled_posts (id, task_id, platform, scheduled_at, status, created_at, attempts, next_attempt_at)
                VALUES (3, 'task-stale-proc', 'youtube', '2026-09-17T09:00:00+00:00', 'processing', '2026-09-16T12:00:00+00:00', 1, NULL);
                """
            )
            # - Post 4: failed SEM success (retry armado)
            conn.execute(
                """
                INSERT INTO scheduled_posts (id, task_id, platform, scheduled_at, status, created_at, attempts, next_attempt_at, last_error)
                VALUES (4, 'task-failed-no-succ', 'tiktok', '2026-09-17T08:00:00+00:00', 'failed', '2026-09-16T12:00:00+00:00', 2, '2026-09-17T08:30:00+00:00', 'Upload timeout');
                """
            )
            # - Post 5: published com sucesso legítimo, SEM retry armado (Caso 6 canônico)
            conn.execute(
                """
                INSERT INTO scheduled_posts (id, task_id, platform, channel_id, scheduled_at, status, created_at, attempts, next_attempt_at)
                VALUES (5, 'task-already-pub-clean', 'youtube', 'main-channel', '2026-09-16T12:00:00+00:00', 'published', '2026-09-16T12:00:00+00:00', 1, NULL);
                """
            )
            # - Post 6: duplicata planned em canal alternativo para tarefa já com sucesso (Caso 6 duplicata)
            conn.execute(
                """
                INSERT INTO scheduled_posts (id, task_id, platform, channel_id, scheduled_at, status, created_at, attempts, next_attempt_at)
                VALUES (6, 'task-already-pub-clean', 'youtube', 'alt-channel', '2026-09-17T12:00:00+00:00', 'ready', '2026-09-16T12:00:00+00:00', 0, '2026-09-17T12:00:00+00:00');
                """
            )
            # - Post 7: published COM next_attempt_at armado e attempts > 0 (Casos 1 e 2 - Cenário real prod)
            conn.execute(
                """
                INSERT INTO scheduled_posts (id, task_id, platform, scheduled_at, status, created_at, attempts, next_attempt_at)
                VALUES (7, 'task-pub-with-retry', 'youtube', '2026-09-16T14:00:00+00:00', 'published', '2026-09-16T14:00:00+00:00', 3, '2026-09-16T15:00:00+00:00');
                """
            )
            # - Post 8: failed COM publication_event success (Caso 3)
            conn.execute(
                """
                INSERT INTO scheduled_posts (id, task_id, platform, scheduled_at, status, created_at, attempts, next_attempt_at, last_error)
                VALUES (8, 'task-failed-with-succ', 'tiktok', '2026-09-16T10:00:00+00:00', 'failed', '2026-09-16T10:00:00+00:00', 2, '2026-09-16T10:30:00+00:00', 'API glitch');
                """
            )

            # 3. publication_events:
            # - Evento 1: Sucesso para Post 5
            conn.execute(
                """
                INSERT INTO publication_events (id, task_id, platform, published_at, status, external_id)
                VALUES (1, 'task-already-pub-clean', 'youtube', '2026-09-16T12:05:00+00:00', 'success', 'yt-clean-123');
                """
            )
            # - Evento 2: Sucesso para Post 7
            conn.execute(
                """
                INSERT INTO publication_events (id, task_id, platform, published_at, status, external_id)
                VALUES (2, 'task-pub-with-retry', 'youtube', '2026-09-16T14:05:00+00:00', 'success', 'yt-retry-456');
                """
            )
            # - Evento 3: Sucesso para Post 8 (que está como status='failed' em scheduled_posts)
            conn.execute(
                """
                INSERT INTO publication_events (id, task_id, platform, published_at, status, external_id)
                VALUES (3, 'task-failed-with-succ', 'tiktok', '2026-09-16T10:05:00+00:00', 'success', 'tt-succ-789');
                """
            )
            # - Evento 4: Falha para Post 4
            conn.execute(
                """
                INSERT INTO publication_events (id, task_id, platform, published_at, status, error_code)
                VALUES (4, 'task-failed-no-succ', 'tiktok', '2026-09-17T08:00:00+00:00', 'failed', 'ERR_TIMEOUT');
                """
            )

    def test_preconditions_check_and_disable(self):
        pre = publication_reset.check_reset_preconditions(self.db_path)
        self.assertTrue(pre["passed"])
        self.assertFalse(pre["scheduler_enabled"])
        self.assertFalse(pre["auto_publish_enabled"])

        # Ativa scheduler_enabled e verifica fail-closed
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute("UPDATE autopilot_settings SET value = 'true' WHERE key = 'scheduler_enabled';")

        pre_fail = publication_reset.check_reset_preconditions(self.db_path)
        self.assertFalse(pre_fail["passed"])
        self.assertIn("scheduler_enabled está ativo", pre_fail["errors"][0])

        # Desativa administrativamente
        fixed_pre = publication_reset.disable_scheduler_preconditions(self.db_path)
        self.assertTrue(fixed_pre["passed"])
        self.assertFalse(fixed_pre["scheduler_enabled"])

    def test_case_8_active_primary_blocks_real_reset(self):
        """Caso 8: active_primary=true em instance_locks bloqueia execução real."""
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO instance_locks (
                    lock_key, node_id, node_name, hostname, pid, started_at, last_heartbeat, role, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    operator_console.DEFAULT_INSTANCE_LOCK_KEY,
                    "node-test-1",
                    "PRIMARY_TEST",
                    "host-test",
                    1234,
                    "2026-10-04T12:00:00+00:00",
                    "2026-10-04T12:00:00+00:00",
                    operator_console.ROLE_PRIMARY,
                    operator_console.INSTANCE_STATUS_ACTIVE,
                ),
            )

        pre = publication_reset.check_reset_preconditions(self.db_path)
        self.assertFalse(pre["passed"])
        self.assertTrue(pre["active_primary"])
        self.assertTrue(any("PRIMARY_FACTORY" in err for err in pre["errors"]))

        # Real reset deve levantar PreconditionError
        with self.assertRaises(publication_reset.PreconditionError):
            publication_reset.reset_pending_publications(
                db_path=self.db_path,
                dry_run=False,
                confirm_token="RESET_PENDING_PUBLICATIONS",
                backup_dir=self.backup_dir,
            )

    def test_case_1_and_2_published_with_success_and_next_attempt_normalized(self):
        """Casos 1 e 2: published + success + next_attempt_at e attempts > 0 -> continua published, next_attempt_at NULL."""
        res = publication_reset.reset_pending_publications(
            db_path=self.db_path,
            dry_run=False,
            confirm_token="RESET_PENDING_PUBLICATIONS",
            backup_dir=self.backup_dir,
        )
        self.assertFalse(res["dry_run"])

        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT status, attempts, next_attempt_at FROM scheduled_posts WHERE id = 7;").fetchone()
            self.assertEqual(row["status"], "published")
            self.assertEqual(row["attempts"], 3)  # histórico de attempts preservado
            self.assertIsNone(row["next_attempt_at"])  # retry desarmado

        # Verifica na trilha de auditoria
        plan_act7 = [act for act in res["actions_plan"] if act["scheduled_post_id"] == 7][0]
        self.assertEqual(plan_act7["resulting_status"], "published")
        self.assertIn("RETRY_DISARMED_AFTER_SUCCESS", plan_act7["reason"])

    def test_case_3_failed_with_success_preserved_not_executable(self):
        """Caso 3: failed + success -> não pode voltar à fila, histórico preservado."""
        res = publication_reset.reset_pending_publications(
            db_path=self.db_path,
            dry_run=False,
            confirm_token="RESET_PENDING_PUBLICATIONS",
            backup_dir=self.backup_dir,
        )
        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT status, attempts, next_attempt_at FROM scheduled_posts WHERE id = 8;").fetchone()
            self.assertEqual(row["status"], "failed")  # preservado como failed para reconciliação
            self.assertEqual(row["attempts"], 2)
            self.assertIsNone(row["next_attempt_at"])  # não executável

        # Verifica anomalia na auditoria after
        inconsistencies = res["after_audit"]["remaining_inconsistencies"]
        self.assertTrue(any("Post #8" in inc and "status='failed'" in inc for inc in inconsistencies))

    def test_case_4_planned_without_success_cancelled(self):
        """Caso 4: planned sem success -> cancelled."""
        publication_reset.reset_pending_publications(
            db_path=self.db_path,
            dry_run=False,
            confirm_token="RESET_PENDING_PUBLICATIONS",
            backup_dir=self.backup_dir,
        )
        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT status, next_attempt_at FROM scheduled_posts WHERE id = 1;").fetchone()
            self.assertEqual(row["status"], "cancelled")
            self.assertIsNone(row["next_attempt_at"])

    def test_case_5_stale_processing_cancelled(self):
        """Caso 5: stale processing -> cancelled."""
        publication_reset.reset_pending_publications(
            db_path=self.db_path,
            dry_run=False,
            confirm_token="RESET_PENDING_PUBLICATIONS",
            backup_dir=self.backup_dir,
        )
        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT status, next_attempt_at FROM scheduled_posts WHERE id = 3;").fetchone()
            self.assertEqual(row["status"], "cancelled")
            self.assertIsNone(row["next_attempt_at"])

    def test_case_6_duplicate_schedules_with_success_preserves_canonical(self):
        """Caso 6: duplicate schedules + success -> nenhum executável, publicação canônica preservada."""
        publication_reset.reset_pending_publications(
            db_path=self.db_path,
            dry_run=False,
            confirm_token="RESET_PENDING_PUBLICATIONS",
            backup_dir=self.backup_dir,
        )
        with scheduler.get_connection(self.db_path) as conn:
            # Canônico Post 5 permanece published
            p5 = conn.execute("SELECT status, next_attempt_at FROM scheduled_posts WHERE id = 5;").fetchone()
            self.assertEqual(p5["status"], "published")
            self.assertIsNone(p5["next_attempt_at"])

            # Duplicata Post 6 cancelada
            p6 = conn.execute("SELECT status, next_attempt_at FROM scheduled_posts WHERE id = 6;").fetchone()
            self.assertEqual(p6["status"], "cancelled")
            self.assertIsNone(p6["next_attempt_at"])

    def test_case_7_dry_run_reproduces_rules_without_mutation(self):
        """Caso 7: dry-run reproduz exatamente essas regras sem mutation."""
        res = publication_reset.reset_pending_publications(
            db_path=self.db_path,
            dry_run=True,
        )
        self.assertTrue(res["dry_run"])
        self.assertIsNone(res["backup_info"])
        self.assertEqual(res["normalized_published"], 1)
        self.assertEqual(res["failed_with_success_preserved"], 1)
        self.assertEqual(res["would_cancel_planned"], 2)
        self.assertEqual(res["would_cancel_processing"], 1)
        self.assertEqual(res["would_neutralize_duplicates"], 1)
        self.assertEqual(res["would_clear_next_attempt"], 5)
        self.assertEqual(res["already_published_preserved"], 2)

        # Garante ZERO mutações no banco durante dry-run
        with scheduler.get_connection(self.db_path) as conn:
            r7 = conn.execute("SELECT status, next_attempt_at FROM scheduled_posts WHERE id = 7;").fetchone()
            self.assertEqual(r7["status"], "published")
            self.assertIsNotNone(r7["next_attempt_at"])

            r8 = conn.execute("SELECT status, next_attempt_at FROM scheduled_posts WHERE id = 8;").fetchone()
            self.assertEqual(r8["status"], "failed")
            self.assertIsNotNone(r8["next_attempt_at"])

            r1 = conn.execute("SELECT status FROM scheduled_posts WHERE id = 1;").fetchone()
            self.assertEqual(r1["status"], "planned")

            r3 = conn.execute("SELECT status FROM scheduled_posts WHERE id = 3;").fetchone()
            self.assertEqual(r3["status"], "processing")


if __name__ == "__main__":
    unittest.main()
