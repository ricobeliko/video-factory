"""Testes direcionados para o LOTE 3A — Segurança de Publicação V1 (Correções CF-01 a CF-04).

Cobre:
CF-01: Autorização explícita (sem heurística de 'escolhas', allow_channels obrigatório na migração, histórico apenas diagnóstico).
CF-02: Fail-closed real (bloqueio quando channel_id é None/vazio/não autorizado em plan e cycle, independência de ordem init_db).
CF-03: Idempotência histórica (isolamento entre canal A e canal B, e proteção universal por registros legados sem canal NULL/'').
CF-04: Propagação ponta a ponta (JIT guard em youtube_publisher e post_for_me com channel_id, retry_policy isolado por canal).
"""

from datetime import datetime, timedelta, timezone
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from app.services import (
    operator_console,
    post_for_me,
    profile_manager,
    publishing_idempotency,
    retry_policy,
    scheduler,
    youtube_publisher,
)


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

    # -------------------------------------------------------------------------
    # CF-01: AUTORIZAÇÃO EXPLÍCITA
    # -------------------------------------------------------------------------

    def test_cf01_explicit_authorization_no_heuristics(self):
        """CF-01: Autorização depende estritamente das flags; zero heurísticas por substring."""
        self._insert_profile("profile-escolhas", is_active=1)
        self._insert_channel("chan-escolhas-tt", "profile-escolhas", "tiktok", "Dose Diária de Escolhas", is_enabled=1, auto_publish_authorized=0)

        # Sem autorização explícita -> False (fail-closed)
        self.assertFalse(scheduler.is_channel_auto_publish_authorized("chan-escolhas-tt", db_path=self.db_path))

        # set_channel_auto_publish_authorized funciona sem bloqueio por substring de texto
        scheduler.set_channel_auto_publish_authorized("chan-escolhas-tt", True, db_path=self.db_path)
        self.assertTrue(scheduler.is_channel_auto_publish_authorized("chan-escolhas-tt", db_path=self.db_path))

        # Se o perfil for desativado, volta a ser False
        self._insert_profile("profile-escolhas", is_active=0)
        self.assertFalse(scheduler.is_channel_auto_publish_authorized("chan-escolhas-tt", db_path=self.db_path))

    def test_cf01_migration_requires_explicit_allow_channels(self):
        """CF-01: Migração NÃO autoriza baseado apenas em histórico; exige allow_channels explícito."""
        self._insert_profile("p-main", is_active=1)
        self._insert_profile("p-pilot", is_active=1)

        self._insert_channel("c-yt-prod", "p-main", "youtube", "Canal Principal", is_enabled=1, auto_publish_authorized=0)
        self._insert_channel("c-dose-escolhas", "p-pilot", "tiktok", "Dose Diária de Escolhas", is_enabled=1, auto_publish_authorized=0)

        # Histórico prévio em c-yt-prod
        scheduler.record_publication_event(
            task_id="t-prev-1", platform="youtube", status="success",
            external_id="yt-123", channel_id="c-yt-prod", db_path=self.db_path,
        )

        # 1. Migração sem allow_channels (ou vazio): NÃO autoriza nada
        report_empty = scheduler.migrate_channel_auto_publish_authorizations(db_path=self.db_path, allow_channels=None, dry_run=False)
        self.assertEqual(len(report_empty["eligible_channels"]), 0)
        with scheduler.get_connection(self.db_path) as conn:
            val_prod = conn.execute("SELECT auto_publish_authorized FROM publishing_channels WHERE id = 'c-yt-prod';").fetchone()[0]
            val_esc = conn.execute("SELECT auto_publish_authorized FROM publishing_channels WHERE id = 'c-dose-escolhas';").fetchone()[0]
            self.assertEqual(val_prod, 0)
            self.assertEqual(val_esc, 0)

        # 2. Migração com allow_channels explícito apenas para c-yt-prod
        report_allowed = scheduler.migrate_channel_auto_publish_authorizations(
            db_path=self.db_path, allow_channels=["c-yt-prod"], dry_run=False
        )
        self.assertEqual(len(report_allowed["eligible_channels"]), 1)
        self.assertEqual(report_allowed["eligible_channels"][0]["channel_id"], "c-yt-prod")

        with scheduler.get_connection(self.db_path) as conn:
            val_prod = conn.execute("SELECT auto_publish_authorized FROM publishing_channels WHERE id = 'c-yt-prod';").fetchone()[0]
            val_esc = conn.execute("SELECT auto_publish_authorized FROM publishing_channels WHERE id = 'c-dose-escolhas';").fetchone()[0]
            self.assertEqual(val_prod, 1, "c-yt-prod deve ser autorizado pois estava em allow_channels")
            self.assertEqual(val_esc, 0, "Dose Diária de Escolhas DEVE permanecer com 0")

    # -------------------------------------------------------------------------
    # CF-02: FAIL-CLOSED REAL
    # -------------------------------------------------------------------------

    def test_cf02_fail_closed_on_none_empty_channel(self):
        """CF-02: channel_id None ou vazio NUNCA tem publicação automática autorizada."""
        self.assertFalse(scheduler.is_channel_auto_publish_authorized(None, db_path=self.db_path))
        self.assertFalse(scheduler.is_channel_auto_publish_authorized("", db_path=self.db_path))
        self.assertFalse(scheduler.is_channel_auto_publish_authorized("   ", db_path=self.db_path))

    def test_cf02_plan_schedule_blocks_unauthorized_or_empty_channel(self):
        """CF-02: plan_schedule não cria agendamento para canal vazio ou não autorizado."""
        self._insert_profile("prof-test", is_active=1)
        self._insert_channel("chan-unauth", "prof-test", "youtube", "Canal Não Autorizado", is_enabled=1, auto_publish_authorized=0)

        fake_video = os.path.join(self.test_dir, "fake_final.mp4")
        with open(fake_video, "wb") as f:
            f.write(b"video_bytes")

        tasks = [
            {
                "task_id": "task-unauth-1",
                "state": "complete",
                "video_file": fake_video,
                "profile_id": "prof-test",
                "planned_platforms": ["youtube"],
            }
        ]

        # Agendamento não cria slot para canal com auto_publish_authorized=0
        sched = scheduler.plan_schedule(tasks, db_path=self.db_path)
        self.assertEqual(len(sched), 0, "Canal sem auto_publish_authorized=1 não deve ser agendado")

        # Autoriza o canal
        scheduler.set_channel_auto_publish_authorized("chan-unauth", True, db_path=self.db_path)
        sched_auth = scheduler.plan_schedule(tasks, db_path=self.db_path)
        self.assertEqual(len(sched_auth), 1, "Canal autorizado deve ser agendado com sucesso")

    def test_cf02_run_cycle_postpones_when_channel_missing_or_unauthorized(self):
        """CF-02: run_scheduler_cycle bloqueia e adia execução se channel_id for vazio ou não autorizado."""
        now_dt = datetime.now(timezone.utc)
        due_time = scheduler._to_iso(now_dt - timedelta(minutes=5))

        # 1. Post agendado sem channel_id (NULL)
        with scheduler.get_connection(self.db_path) as conn:
            cur1 = conn.execute(
                "INSERT INTO scheduled_posts (task_id, platform, status, scheduled_at, created_at, channel_id) VALUES (?, ?, 'ready', ?, ?, NULL);",
                ("t-null-chan", "youtube", due_time, due_time),
            )
            p1_id = cur1.lastrowid

        res1 = scheduler.run_scheduler_cycle(db_path=self.db_path)
        self.assertEqual(res1.get("status"), "postponed")
        self.assertEqual(res1.get("reason"), "channel_not_authorized")

        with scheduler.get_connection(self.db_path) as conn:
            row1 = conn.execute("SELECT scheduled_at, status FROM scheduled_posts WHERE id = ?;", (p1_id,)).fetchone()
            self.assertEqual(row1["status"], "ready")
            self.assertGreater(scheduler._from_iso(row1["scheduled_at"]), now_dt)

    def test_cf02_init_db_order_independence(self):
        """CF-02: init_db chamado antes de init_profile_db cria o schema sem dependência de ordem."""
        fresh_db = os.path.join(self.test_dir, "fresh_order_test.db")
        # Chama apenas init_db (sem chamar init_profile_db antes)
        scheduler.init_db(fresh_db)

        # publishing_channels e auto_publish_authorized já devem existir
        with scheduler.get_connection(fresh_db) as conn:
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(publishing_channels);").fetchall()]
            self.assertIn("auto_publish_authorized", cols)

    # -------------------------------------------------------------------------
    # CF-03: IDEMPOTÊNCIA HISTÓRICA (NULL, "", Canal A, Canal B)
    # -------------------------------------------------------------------------

    def test_cf03_historical_null_and_empty_protects_against_republication(self):
        """CF-03: Evento histórico sem channel_id (NULL ou '') protege todos os canais contra republicação."""
        task_id = "task-legacy-repub"
        platform = "youtube"

        # Inserção de evento de sucesso legado com channel_id = NULL
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO publication_events (task_id, platform, status, external_id, channel_id, published_at)
                VALUES (?, ?, 'success', 'yt-leg-1', NULL, ?);
                """,
                (task_id, platform, scheduler._to_iso(datetime.now(timezone.utc))),
            )

        # Canal A, Canal B, NULL e string vazia devem TODOS detectar como já publicado
        for target_chan in ("channel-A", "channel-B", "", None):
            canon = publishing_idempotency.check_canonical_publication_status(
                task_id=task_id, platform=platform, channel_id=target_chan, db_path=self.db_path
            )
            self.assertTrue(canon["is_published"], f"Deveria estar publicado para channel_id={target_chan}")

            # can_schedule_task também deve bloquear
            can_sched, reason, _ = publishing_idempotency.can_schedule_task(
                task_id=task_id, platform=platform, channel_id=target_chan, db_path=self.db_path
            )
            self.assertFalse(can_sched)
            self.assertEqual(reason, "already_published")

            # has_existing_or_terminal_destination também deve bloquear
            has_dest = scheduler.has_existing_or_terminal_destination(
                task_id=task_id, platform=platform, channel_id=target_chan, db_path=self.db_path
            )
            self.assertTrue(has_dest, f"has_dest deve ser True para channel_id={target_chan}")

    def test_cf03_channel_a_success_does_not_block_channel_b(self):
        """CF-03: Evento em Canal A NÃO bloqueia Canal B (isolamento estrito multicanal)."""
        task_id = "task-chan-isolation"
        platform = "youtube"

        # Publicação confirmada apenas para channel-A
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO publication_events (task_id, platform, status, external_id, channel_id, published_at)
                VALUES (?, ?, 'success', 'yt-chan-a', 'channel-A', ?);
                """,
                (task_id, platform, scheduler._to_iso(datetime.now(timezone.utc))),
            )

        # Canal A está publicado
        canon_a = publishing_idempotency.check_canonical_publication_status(
            task_id, platform, channel_id="channel-A", db_path=self.db_path
        )
        self.assertTrue(canon_a["is_published"])

        # Canal B NÃO está publicado
        canon_b = publishing_idempotency.check_canonical_publication_status(
            task_id, platform, channel_id="channel-B", db_path=self.db_path
        )
        self.assertFalse(canon_b["is_published"])

        # Canal B pode agendar
        can_b, _, _ = publishing_idempotency.can_schedule_task(
            task_id, platform, channel_id="channel-B", db_path=self.db_path
        )
        self.assertTrue(can_b)

    # -------------------------------------------------------------------------
    # CF-04: PROPAGAÇÃO PONTA A PONTA (JIT & RETRY POLICY)
    # -------------------------------------------------------------------------

    def test_cf04_jit_guard_propagates_channel_id_in_publishers(self):
        """CF-04: JIT guard em youtube_publisher e post_for_me propaga channel_id e isola canais."""
        task_id = "task-jit-propagate"
        platform = "youtube"

        # Canal A publicado
        scheduler.record_publication_event(
            task_id=task_id, platform=platform, status="success",
            external_id="yt-chan-a-1", channel_id="channel-A", db_path=self.db_path
        )

        fake_video = os.path.join(self.test_dir, "fake.mp4")
        with open(fake_video, "wb") as f:
            f.write(b"data")

        # 1. youtube_publisher para Canal A é bloqueado por idempotência JIT
        res_a = youtube_publisher.publish_youtube_video(
            video_path=fake_video, title="Title A", caption="Desc",
            task_id=task_id, channel_id="channel-A", db_path=self.db_path
        )
        self.assertTrue(res_a.get("already_published"))

        # 2. youtube_publisher para Canal B NÃO é bloqueado pela publicação do Canal A
        with patch.object(post_for_me.post_for_me_client, "publish_video", return_value={"success": True, "external_id": "yt-chan-b-1"}) as mock_pub:
            with patch("app.services.youtube_publisher.get_youtube_publish_provider", return_value="post_for_me"):
                res_b = youtube_publisher.publish_youtube_video(
                    video_path=fake_video, title="Title B", caption="Desc",
                    task_id=task_id, channel_id="channel-B", db_path=self.db_path
                )
                self.assertFalse(res_b.get("already_published", False))
                mock_pub.assert_called_once()

    def test_cf04_retry_decision_isolated_between_channels(self):
        """CF-04: Sucesso no Canal A não interrompe nem altera indevidamente o retry do Canal B."""
        task_id = "task-retry-isolation"
        platform = "youtube"

        # Canal A já tem publicação confirmada
        scheduler.record_publication_event(
            task_id=task_id, platform=platform, status="success",
            external_id="yt-chan-a-win", channel_id="channel-A", db_path=self.db_path
        )

        # Canal B falhou na primeira tentativa (ex.: timeout)
        decision_b = retry_policy.evaluate_retry_decision(
            task_id=task_id,
            platform=platform,
            current_status="processing",
            attempts=1,
            error_msg="Temporary network timeout",
            channel_id="channel-B",
            db_path=self.db_path,
        )

        # Canal B DEVE poder fazer retry normalmente (não ser considerado 'published')
        self.assertTrue(decision_b.can_retry, "Canal B deveria poder fazer retry mesmo com Canal A publicado")
        self.assertEqual(decision_b.resulting_status, "ready")

        # Já para o Canal A, se avaliado, o sucesso canônico é terminal
        decision_a = retry_policy.evaluate_retry_decision(
            task_id=task_id,
            platform=platform,
            current_status="processing",
            attempts=1,
            error_msg="Temporary network timeout",
            channel_id="channel-A",
            db_path=self.db_path,
        )
        self.assertFalse(decision_a.can_retry)
        self.assertEqual(decision_a.resulting_status, "published")


if __name__ == "__main__":
    unittest.main()
