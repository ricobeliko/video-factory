"""Testes direcionados para o LOTE 3A — Segurança de Publicação V1.

Cobre:
1. Autorização canônica individual por canal (fail-closed).
2. Bloqueio absoluto e irrevogável de 'Dose Diária de Escolhas'.
3. Migração explícita e auditável de canais (dry_run por padrão).
4. Idempotência multicanal: isolamento estrito por (task_id, platform, channel_id).
5. Neutralização de duplicatas apenas no mesmo canal.
6. Scheduler plan e cycle respeitando autorização de canal.
"""

from datetime import datetime, timedelta, timezone
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from app.services import operator_console, profile_manager, publishing_idempotency, scheduler


class TestLote3APublishingSecurity(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_lote3a.db")
        scheduler.init_db(self.db_path)
        operator_console.init_operator_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)

        # Configurações básicas de scheduler no DB
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)
        scheduler.set_setting("youtube_enabled", True, db_path=self.db_path)
        scheduler.set_setting("tiktok_enabled", True, db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _insert_profile(self, profile_id: str, is_active: int = 1):
        now_iso = scheduler._to_iso(datetime.now(timezone.utc))
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO content_profiles (id, name, slug, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (profile_id, f"Profile {profile_id}", profile_id, is_active, now_iso, now_iso),
            )

    def _insert_channel(
        self,
        channel_id: str,
        profile_id: str,
        platform: str,
        display_name: str,
        is_enabled: int = 1,
        auto_publish_authorized: int = 0,
    ):
        now_iso = scheduler._to_iso(datetime.now(timezone.utc))
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO publishing_channels (
                    id, profile_id, platform, display_name, is_enabled, auto_publish_authorized, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (channel_id, profile_id, platform, display_name, is_enabled, auto_publish_authorized, now_iso, now_iso),
            )

    def test_canonical_authorization_fail_closed(self):
        """1. Validação Fail-Closed: sem autorização explícita ou canal inválido retorna False."""
        self._insert_profile("prof-1", is_active=1)
        self._insert_channel("chan-default-yt", "prof-1", "youtube", "Canal Padrão", is_enabled=1, auto_publish_authorized=0)

        # Canal com auto_publish_authorized=0 -> False
        self.assertFalse(scheduler.is_channel_auto_publish_authorized("chan-default-yt", db_path=self.db_path))

        # Canal inexistente -> False
        self.assertFalse(scheduler.is_channel_auto_publish_authorized("chan-inexistente", db_path=self.db_path))

        # channel_id vazio / None sem resolução -> False
        self.assertFalse(scheduler.is_channel_auto_publish_authorized(None, db_path=self.db_path))

        # Ativa canal -> agora True
        scheduler.set_channel_auto_publish_authorized("chan-default-yt", True, db_path=self.db_path)
        self.assertTrue(scheduler.is_channel_auto_publish_authorized("chan-default-yt", db_path=self.db_path))

        # Canal desabilitado (is_enabled=0) mesmo com flag 1 -> False
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute("UPDATE publishing_channels SET is_enabled = 0 WHERE id = 'chan-default-yt';")
        self.assertFalse(scheduler.is_channel_auto_publish_authorized("chan-default-yt", db_path=self.db_path))

    def test_dose_escolhas_strictly_forbidden(self):
        """2. 'Dose Diária de Escolhas' é proibido de publicar automaticamente de forma estrita e absoluta."""
        self._insert_profile("profile-escolhas", is_active=1)
        self._insert_channel("chan-escolhas-tt", "profile-escolhas", "tiktok", "Dose Diária de Escolhas", is_enabled=1, auto_publish_authorized=0)

        # Não autorizado inicialmente
        self.assertFalse(scheduler.is_channel_auto_publish_authorized("chan-escolhas-tt", db_path=self.db_path))

        # Tentativa de autorizar via set_channel_auto_publish_authorized deve levantar PermissionError
        with self.assertRaises(PermissionError):
            scheduler.set_channel_auto_publish_authorized("chan-escolhas-tt", True, db_path=self.db_path)

        # Se alguém injetar diretamente no banco auto_publish_authorized = 1, is_channel_auto_publish_authorized AINDA bloqueia
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute("UPDATE publishing_channels SET auto_publish_authorized = 1 WHERE id = 'chan-escolhas-tt';")

        self.assertFalse(
            scheduler.is_channel_auto_publish_authorized("chan-escolhas-tt", db_path=self.db_path),
            "Dose Diária de Escolhas NUNCA deve ser autorizada mesmo com flag adulterada no banco"
        )

    def test_migration_dry_run_and_execution(self):
        """3. Processo de migração auditável: dry_run por padrão, proteção a Escolhas e ativação segura."""
        self._insert_profile("p-main", is_active=1)
        self._insert_profile("p-escolhas", is_active=1)

        self._insert_channel("c-yt-prod", "p-main", "youtube", "Canal Principal", is_enabled=1, auto_publish_authorized=0)
        self._insert_channel("c-escolhas", "p-escolhas", "tiktok", "Dose Diária de Escolhas", is_enabled=1, auto_publish_authorized=0)
        self._insert_channel("c-new-empty", "p-main", "tiktok", "Novo Sem Histórico", is_enabled=1, auto_publish_authorized=0)

        # Simula histórico de sucesso comprovado para c-yt-prod
        scheduler.record_publication_event(
            task_id="t-prev-1",
            platform="youtube",
            status="success",
            external_id="yt-prev-123",
            channel_id="c-yt-prod",
            db_path=self.db_path,
        )

        # 3.1 Executa dry_run (padrão)
        report_dry = scheduler.migrate_channel_auto_publish_authorizations(db_path=self.db_path)
        self.assertTrue(report_dry["dry_run"])
        self.assertEqual(report_dry["status"], "dry_run")

        eligible_ids = [e["channel_id"] for e in report_dry["eligible_channels"]]
        self.assertIn("c-yt-prod", eligible_ids)
        self.assertNotIn("c-escolhas", eligible_ids)
        self.assertNotIn("c-new-empty", eligible_ids)

        # Verifica que no dry_run NENHUMA alteração foi gravada
        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT auto_publish_authorized FROM publishing_channels WHERE id = 'c-yt-prod';").fetchone()
            self.assertEqual(row["auto_publish_authorized"], 0)

        # 3.2 Executa migração real (dry_run=False)
        report_exec = scheduler.migrate_channel_auto_publish_authorizations(db_path=self.db_path, dry_run=False)
        self.assertFalse(report_exec["dry_run"])
        self.assertEqual(report_exec["status"], "executed")

        with scheduler.get_connection(self.db_path) as conn:
            row_prod = conn.execute("SELECT auto_publish_authorized FROM publishing_channels WHERE id = 'c-yt-prod';").fetchone()
            row_esc = conn.execute("SELECT auto_publish_authorized FROM publishing_channels WHERE id = 'c-escolhas';").fetchone()
            row_empty = conn.execute("SELECT auto_publish_authorized FROM publishing_channels WHERE id = 'c-new-empty';").fetchone()

            self.assertEqual(row_prod["auto_publish_authorized"], 1)
            self.assertEqual(row_esc["auto_publish_authorized"], 0)
            self.assertEqual(row_empty["auto_publish_authorized"], 0)

    def test_multichannel_idempotency_isolation(self):
        """4. Idempotência multicanal: dois canais no YouTube para a mesma task são completamente independentes."""
        task_id = "task-multi-channel-yt"
        platform = "youtube"
        chan_a = "channel-a-youtube"
        chan_b = "channel-b-youtube"

        self._insert_profile("prof-multi", is_active=1)
        self._insert_channel(chan_a, "prof-multi", "youtube", "Canal A", is_enabled=1, auto_publish_authorized=1)
        self._insert_channel(chan_b, "prof-multi", "youtube", "Canal B", is_enabled=1, auto_publish_authorized=1)

        # 4.1 Ambos podem ser agendados para a mesma task
        can_a, reason_a, _ = publishing_idempotency.can_schedule_task(task_id, platform, channel_id=chan_a, db_path=self.db_path)
        self.assertTrue(can_a, f"Canal A deveria poder agendar: {reason_a}")

        # Insere post planejado para canal A
        now_dt = datetime.now(timezone.utc)
        iso_time = scheduler._to_iso(now_dt)
        with scheduler.get_connection(self.db_path) as conn:
            cur_a = conn.execute(
                """
                INSERT INTO scheduled_posts (task_id, platform, status, scheduled_at, created_at, channel_id)
                VALUES (?, ?, 'planned', ?, ?, ?);
                """,
                (task_id, platform, iso_time, iso_time, chan_a),
            )
            post_a_id = cur_a.lastrowid

        # Canal A agora bloqueia novo agendamento para si mesmo
        can_a_again, reason_a_again, _ = publishing_idempotency.can_schedule_task(task_id, platform, channel_id=chan_a, db_path=self.db_path)
        self.assertFalse(can_a_again)
        self.assertEqual(reason_a_again, "already_scheduled")

        # Canal B AINDA pode ser agendado para a mesma task e mesma plataforma!
        can_b, reason_b, _ = publishing_idempotency.can_schedule_task(task_id, platform, channel_id=chan_b, db_path=self.db_path)
        self.assertTrue(can_b, f"Canal B deveria poder agendar independentemente de Canal A: {reason_b}")

        # Insere post planejado para canal B
        with scheduler.get_connection(self.db_path) as conn:
            cur_b = conn.execute(
                """
                INSERT INTO scheduled_posts (task_id, platform, status, scheduled_at, created_at, channel_id)
                VALUES (?, ?, 'planned', ?, ?, ?);
                """,
                (task_id, platform, iso_time, iso_time, chan_b),
            )
            post_b_id = cur_b.lastrowid

        # 4.2 Publicação de Canal A não bloqueia Canal B
        scheduler.record_publication_event(
            task_id=task_id,
            platform=platform,
            status="success",
            external_id="yt-pub-chan-a",
            channel_id=chan_a,
            db_path=self.db_path,
        )

        # Canal A agora é detectado como já publicado
        can_exec_a, reason_exec_a, _ = publishing_idempotency.can_execute_scheduled_post(
            task_id, platform, post_id=post_a_id, channel_id=chan_a, db_path=self.db_path
        )
        self.assertFalse(can_exec_a)
        self.assertEqual(reason_exec_a, "already_published")

        # Canal B AINDA é perfeitamente executável!
        can_exec_b, reason_exec_b, _ = publishing_idempotency.can_execute_scheduled_post(
            task_id, platform, post_id=post_b_id, channel_id=chan_b, db_path=self.db_path
        )
        self.assertTrue(can_exec_b, f"Canal B deveria poder executar mesmo com Canal A já publicado: {reason_exec_b}")

        # JIT guard no Canal B é seguro (True), enquanto no Canal A é bloqueado (False)
        safe_b, canon_b = publishing_idempotency.jit_provider_idempotency_guard(task_id, platform, channel_id=chan_b, db_path=self.db_path)
        self.assertTrue(safe_b)
        self.assertIsNone(canon_b)

        safe_a, canon_a = publishing_idempotency.jit_provider_idempotency_guard(task_id, platform, channel_id=chan_a, db_path=self.db_path)
        self.assertFalse(safe_a)
        self.assertIsNotNone(canon_a)

    def test_duplicate_neutralization_scoped_to_same_channel(self):
        """5. Neutralização de duplicatas afeta apenas o mesmo canal; outros canais permanecem intactos."""
        task_id = "task-dup-neutralize"
        platform = "youtube"
        chan_a = "chan-a"
        chan_b = "chan-b"

        now_dt = datetime.now(timezone.utc)
        iso_time = scheduler._to_iso(now_dt)

        with scheduler.get_connection(self.db_path) as conn:
            # Desativa temporariamente o índice unique para simular banco legado com duplicatas existentes
            conn.execute("DROP INDEX IF EXISTS idx_active_schedule_v2;")

            # Dois posts para chan_a (um canônico e um duplicado)
            cur1 = conn.execute(
                "INSERT INTO scheduled_posts (task_id, platform, status, scheduled_at, created_at, channel_id) VALUES (?, ?, 'ready', ?, ?, ?);",
                (task_id, platform, iso_time, iso_time, chan_a),
            )
            p1_a = cur1.lastrowid

            cur2 = conn.execute(
                "INSERT INTO scheduled_posts (task_id, platform, status, scheduled_at, created_at, channel_id) VALUES (?, ?, 'ready', ?, ?, ?);",
                (task_id, platform, iso_time, iso_time, chan_a),
            )
            p2_a = cur2.lastrowid

            # Um post para chan_b
            cur3 = conn.execute(
                "INSERT INTO scheduled_posts (task_id, platform, status, scheduled_at, created_at, channel_id) VALUES (?, ?, 'ready', ?, ?, ?);",
                (task_id, platform, iso_time, iso_time, chan_b),
            )
            p3_b = cur3.lastrowid

            # Executa neutralização em favor de p1_a no canal chan_a
            neutralized = publishing_idempotency.neutralize_duplicate_executable_posts(
                task_id=task_id,
                platform=platform,
                canonical_post_id=p1_a,
                channel_id=chan_a,
                conn=conn,
            )

        self.assertEqual(neutralized, 1)

        with scheduler.get_connection(self.db_path) as conn:
            row_p1 = conn.execute("SELECT status FROM scheduled_posts WHERE id = ?;", (p1_a,)).fetchone()
            row_p2 = conn.execute("SELECT status FROM scheduled_posts WHERE id = ?;", (p2_a,)).fetchone()
            row_p3 = conn.execute("SELECT status FROM scheduled_posts WHERE id = ?;", (p3_b,)).fetchone()

            self.assertEqual(row_p1["status"], "ready")
            self.assertEqual(row_p2["status"], "cancelled", "Duplicata no mesmo canal deve ser cancelada")
            self.assertEqual(row_p3["status"], "ready", "Post de outro canal NÃO deve ser cancelado")

    def test_run_scheduler_cycle_blocks_unauthorized_channel(self):
        """6. Ciclo do scheduler bloqueia execução se canal não estiver autorizado, adiando com segurança."""
        task_id = "task-unauth-cycle"
        platform = "youtube"
        chan_id = "chan-unauthorized"

        self._insert_profile("prof-test", is_active=1)
        self._insert_channel(chan_id, "prof-test", "youtube", "Canal Não Autorizado", is_enabled=1, auto_publish_authorized=0)

        now_dt = datetime.now(timezone.utc)
        due_time = scheduler._to_iso(now_dt - timedelta(minutes=5))

        with scheduler.get_connection(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO scheduled_posts (task_id, platform, status, scheduled_at, created_at, channel_id, profile_id)
                VALUES (?, ?, 'ready', ?, ?, ?, ?);
                """,
                (task_id, platform, due_time, due_time, chan_id, "prof-test"),
            )
            post_id = cur.lastrowid

        with patch("app.services.task.publish_task") as mock_publish:
            res = scheduler.run_scheduler_cycle(db_path=self.db_path)
            mock_publish.assert_not_called()

        self.assertEqual(res.get("status"), "postponed")
        self.assertEqual(res.get("reason"), "channel_not_authorized")

        # Verifica se o post foi adiado no banco de dados (scheduled_at > now)
        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT scheduled_at, next_attempt_at, status FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
            new_sched = scheduler._from_iso(row["scheduled_at"])
            self.assertGreater(new_sched, now_dt)
            self.assertEqual(row["status"], "ready")


if __name__ == "__main__":
    unittest.main()
