"""Testes unitários direcionados para V16.4.2B — Publishing Idempotency / Duplicate Protection.

Garante que o sistema impeça definitivamente a criação, agendamento, processamento
ou envio de mais de uma publicação externa para a mesma tupla canônica (task_id, platform).
"""

from datetime import datetime, timedelta, timezone
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from app.services import post_for_me, publishing_idempotency, scheduler, youtube_publisher


class TestPublishingIdempotency(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_idempotency.db")
        scheduler.init_db(self.db_path)

        # Configurações básicas de scheduler no DB
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", True, db_path=self.db_path)
        scheduler.set_setting("dry_run", False, db_path=self.db_path)
        scheduler.set_setting("youtube_enabled", True, db_path=self.db_path)
        scheduler.set_setting("tiktok_enabled", True, db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _insert_scheduled_post(
        self,
        task_id: str,
        platform: str,
        status: str = "ready",
        scheduled_at: str = None,
        channel_id: str = "channel-1",
        profile_id: str = "profile-1",
        attempts: int = 0,
        next_attempt_at: str = None,
    ) -> int:
        now_dt = datetime.now(timezone.utc)
        now_iso = scheduler._to_iso(now_dt)
        sched_iso = scheduled_at or scheduler._to_iso(now_dt - timedelta(minutes=5))
        with scheduler.get_connection(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO scheduled_posts (
                    task_id, platform, status, scheduled_at, created_at,
                    channel_id, profile_id, attempts, next_attempt_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (task_id, platform, status, sched_iso, now_iso, channel_id, profile_id, attempts, next_attempt_at),
            )
            return cur.lastrowid

    def _insert_publication_event(
        self,
        task_id: str,
        platform: str,
        status: str = "success",
        external_id: str = "ext_123",
        external_url: str = "https://youtube.com/watch?v=ext_123",
        channel_id: str = "channel-1",
    ) -> int:
        return scheduler.record_publication_event(
            task_id=task_id,
            platform=platform,
            status=status,
            external_id=external_id,
            external_url=external_url,
            channel_id=channel_id,
            db_path=self.db_path,
        )

    def test_existing_success_blocks_provider(self):
        """1. Sucesso existente em publication_events bloqueia chamada ao provider no ciclo e no publisher."""
        task_id = "task-success-block"
        platform = "youtube"

        self._insert_publication_event(task_id, platform, status="success", external_id="yt-canon-1")
        post_id = self._insert_scheduled_post(task_id, platform, status="ready")

        with patch("app.services.task.publish_task") as mock_publish:
            result = scheduler.run_scheduler_cycle(db_path=self.db_path)
            mock_publish.assert_not_called()

        self.assertEqual(result.get("status"), "skipped")
        self.assertEqual(result.get("reason"), "already_published")

        # Verifica se o post foi marcado como published e retry desarmado
        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT status, next_attempt_at FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
            self.assertEqual(row["status"], "published")
            self.assertIsNone(row["next_attempt_at"])

        # Também testa a chamada direta a youtube_publisher.publish_youtube_video
        with patch.object(post_for_me.post_for_me_client, "publish_video") as mock_pfm:
            yt_res = youtube_publisher.publish_youtube_video(
                video_path="dummy.mp4",
                title="title",
                caption="caption",
                task_id=task_id,
                db_path=self.db_path,
            )
            mock_pfm.assert_not_called()
            self.assertTrue(yt_res.get("success"))
            self.assertTrue(yt_res.get("already_published"))
            self.assertEqual(yt_res.get("external_id"), "yt-canon-1")

    def test_existing_executable_blocks_second_schedule(self):
        """2. scheduled_post executável existente ('ready'/'planned') bloqueia novo agendamento."""
        task_id = "task-exec-block"
        platform = "youtube"

        self._insert_scheduled_post(task_id, platform, status="ready")

        can_sched, reason, details = publishing_idempotency.can_schedule_task(
            task_id=task_id, platform=platform, db_path=self.db_path
        )
        self.assertFalse(can_sched)
        self.assertEqual(reason, "already_scheduled")

        # Verifica que has_existing_or_terminal_destination também bloqueia
        exists = scheduler.has_existing_or_terminal_destination(
            task_id=task_id, platform=platform, db_path=self.db_path
        )
        self.assertTrue(exists)

    def test_existing_processing_blocks_second_flow(self):
        """3. scheduled_post em 'processing' bloqueia novo agendamento e segundo fluxo concorrente."""
        task_id = "task-proc-block"
        platform = "tiktok"

        _proc_id = self._insert_scheduled_post(task_id, platform, status="processing")
        sec_id = self._insert_scheduled_post(task_id, platform, status="ready", channel_id="channel-2")

        can_sched, reason, _ = publishing_idempotency.can_schedule_task(
            task_id=task_id, platform=platform, db_path=self.db_path
        )
        self.assertFalse(can_sched)
        self.assertEqual(reason, "already_processing")

        can_exec, exec_reason, _ = publishing_idempotency.can_execute_scheduled_post(
            task_id=task_id, platform=platform, post_id=sec_id, db_path=self.db_path
        )
        self.assertFalse(can_exec)
        self.assertEqual(exec_reason, "already_processing")

    def test_existing_published_blocks_new_schedule(self):
        """4. scheduled_post em 'published' bloqueia criação de novo agendamento."""
        task_id = "task-pub-block"
        platform = "youtube"

        self._insert_scheduled_post(task_id, platform, status="published")

        can_sched, reason, _ = publishing_idempotency.can_schedule_task(
            task_id=task_id, platform=platform, db_path=self.db_path
        )
        self.assertFalse(can_sched)
        self.assertEqual(reason, "already_published")

    def test_duplicate_historical_cancelled_does_not_interfere(self):
        """5. Duplicata histórica cancelada ('cancelled') não impede post ativo de rodar nem causa erro."""
        task_id = "task-hist-canc"
        platform = "youtube"

        # Post #1 histórico cancelado
        self._insert_scheduled_post(task_id, platform, status="cancelled", channel_id="channel-old")
        # Post #2 ativo elegível
        active_id = self._insert_scheduled_post(task_id, platform, status="ready", channel_id="channel-new")

        can_exec, reason, _ = publishing_idempotency.can_execute_scheduled_post(
            task_id=task_id, platform=platform, post_id=active_id, db_path=self.db_path
        )
        self.assertTrue(can_exec)
        self.assertIsNone(reason)

    def test_simulated_race_success_before_provider_aborts_safely(self):
        """6. Race condition simulada: sucesso aparece antes do provider -> provider bloqueado."""
        task_id = "task-race-test"
        platform = "youtube"

        now_dt = datetime.now(timezone.utc)
        sched_iso = scheduler._to_iso(now_dt - timedelta(minutes=5))
        now_iso = scheduler._to_iso(now_dt)

        with scheduler.get_connection(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO scheduled_posts (
                    task_id, platform, status, scheduled_at, created_at,
                    channel_id, profile_id, attempts, next_attempt_at
                ) VALUES (?, ?, 'ready', ?, ?, 'channel-1', 'profile-1', 0, NULL);
                """,
                (task_id, platform, sched_iso, now_iso),
            )
            post_id = cur.lastrowid

            # Injetamos o evento de sucesso simulando race condition concorrente
            conn.execute(
                """
                INSERT INTO publication_events (task_id, platform, status, external_id, channel_id, published_at)
                VALUES (?, ?, 'success', 'yt-race-win', 'channel-1', ?);
                """,
                (task_id, platform, sched_iso),
            )

        # 1. Disparamos JIT guard com evento existente
        is_safe, canon = publishing_idempotency.jit_provider_idempotency_guard(task_id, platform, db_path=self.db_path)
        self.assertFalse(is_safe)
        self.assertEqual(canon["external_id"], "yt-race-win")

        # 2. Executa ciclo: o scheduler deve detectar a publicação e abortar antes de chamar task_module.publish_task
        with patch("app.services.profile_manager.get_profile", return_value={"is_active": True}), \
             patch("app.services.profile_manager.get_channel", return_value={"is_enabled": True}), \
             patch("app.services.scheduler.get_task_platforms", return_value=[platform]), \
             patch("app.services.scheduler.get_task_final_video", return_value="fake.mp4"), \
             patch("os.path.isfile", return_value=True), \
             patch("app.services.task.publish_task") as mock_publish:

            res = scheduler.run_scheduler_cycle(db_path=self.db_path)
            mock_publish.assert_not_called()
            self.assertEqual(res.get("status"), "skipped")
            self.assertEqual(res.get("reason"), "already_published")

        # 3. Verifica se o post foi marcado como published e retry desarmado
        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT status, next_attempt_at FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
            self.assertEqual(row["status"], "published")
            self.assertIsNone(row["next_attempt_at"])

    def test_only_one_provider_call_for_same_tuple(self):
        """7. Apenas uma chamada de provider é executada mesmo havendo duplicatas executáveis no banco."""
        task_id = "task-single-call"
        platform = "youtube"

        now_dt = datetime.now(timezone.utc)
        t1 = scheduler._to_iso(now_dt - timedelta(minutes=10))
        t2 = scheduler._to_iso(now_dt - timedelta(minutes=5))

        _post1 = self._insert_scheduled_post(task_id, platform, status="ready", scheduled_at=t1, channel_id="channel-default-youtube")
        post2 = self._insert_scheduled_post(task_id, platform, status="ready", scheduled_at=t2, channel_id="channel-historias-misterio-youtube")

        with patch("app.services.profile_manager.get_profile", return_value={"is_active": True}), \
             patch("app.services.profile_manager.get_channel", return_value={"is_enabled": True}), \
             patch("app.services.scheduler.get_task_platforms", return_value=[platform]), \
             patch("app.services.scheduler.get_task_final_video", return_value="fake.mp4"), \
             patch("os.path.isfile", return_value=True), \
             patch("app.services.task.publish_task", return_value=(True, "")) as mock_publish:

            # Primeiro ciclo: executa post1 e neutraliza post2
            res1 = scheduler.run_scheduler_cycle(db_path=self.db_path)
            self.assertEqual(res1.get("status"), "published")
            self.assertEqual(mock_publish.call_count, 1)

            # Verifica que o post2 foi neutralizado para 'cancelled' com next_attempt_at = NULL
            with scheduler.get_connection(self.db_path) as conn:
                p2_row = conn.execute("SELECT status, next_attempt_at FROM scheduled_posts WHERE id = ?;", (post2,)).fetchone()
                self.assertEqual(p2_row["status"], "cancelled")
                self.assertIsNone(p2_row["next_attempt_at"])

            # Segundo ciclo: nenhum post executável restante
            res2 = scheduler.run_scheduler_cycle(db_path=self.db_path)
            self.assertEqual(res2.get("status"), "idle")
            self.assertEqual(mock_publish.call_count, 1)

    def test_multiple_platforms_remain_independent(self):
        """8. Múltiplas plataformas para a mesma task permanecem independentes."""
        task_id = "task-multi-platform"

        # YouTube publicado com sucesso
        self._insert_publication_event(task_id, "youtube", status="success", external_id="yt-123")
        self._insert_scheduled_post(task_id, "youtube", status="published")

        # TikTok pronto para publicação
        tt_id = self._insert_scheduled_post(task_id, "tiktok", status="ready")

        can_yt, _, _ = publishing_idempotency.can_schedule_task(task_id, "youtube", db_path=self.db_path)
        self.assertFalse(can_yt)

        can_tt, _, _ = publishing_idempotency.can_schedule_task(task_id, "tiktok", db_path=self.db_path)
        # TikTok já tem agendamento ativo, então não cria novo, mas pode executar o existente
        self.assertFalse(can_tt)

        can_exec_tt, reason_tt, _ = publishing_idempotency.can_execute_scheduled_post(
            task_id, "tiktok", post_id=tt_id, db_path=self.db_path
        )
        self.assertTrue(can_exec_tt)
        self.assertIsNone(reason_tt)

    def test_idempotency_after_retry_or_restart(self):
        """9. Idempotência mantida após retry armado ou restart de worker se sucesso já existir."""
        task_id = "task-retry-idempotency"
        platform = "youtube"

        now_dt = datetime.now(timezone.utc)
        past_time = scheduler._to_iso(now_dt - timedelta(minutes=10))

        # Simula registro de retry armado anterior que ficou 'ready' antes do restart/crash
        with scheduler.get_connection(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO scheduled_posts (
                    task_id, platform, status, scheduled_at, created_at,
                    channel_id, profile_id, attempts, next_attempt_at
                ) VALUES (?, ?, 'ready', ?, ?, 'channel-1', 'profile-1', 2, ?);
                """,
                (task_id, platform, past_time, past_time, past_time),
            )
            post_id = cur.lastrowid

            # Publicação canônica já confirmada em publication_events
            conn.execute(
                """
                INSERT INTO publication_events (task_id, platform, status, external_id, channel_id, published_at)
                VALUES (?, ?, 'success', 'yt-done', 'channel-1', ?);
                """,
                (task_id, platform, past_time),
            )

        with patch("app.services.task.publish_task") as mock_publish:
            res = scheduler.run_scheduler_cycle(db_path=self.db_path)
            mock_publish.assert_not_called()

        self.assertEqual(res.get("status"), "skipped")
        self.assertEqual(res.get("reason"), "already_published")

        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT status, attempts, next_attempt_at FROM scheduled_posts WHERE id = ?;", (post_id,)).fetchone()
            self.assertEqual(row["status"], "published")
            self.assertEqual(row["attempts"], 2)
            self.assertIsNone(row["next_attempt_at"])

    def test_history_and_media_preserved(self):
        """10. Histórico de scheduled_posts e publication_events é integralmente preservado (zero deleções)."""
        task_id = "task-preserve-audit"
        platform = "youtube"

        _ev_id = self._insert_publication_event(task_id, platform, status="success")
        p1 = self._insert_scheduled_post(task_id, platform, status="ready", channel_id="channel-1")
        _p2 = self._insert_scheduled_post(task_id, platform, status="ready", channel_id="channel-2")

        with scheduler.get_connection(self.db_path) as conn:
            publishing_idempotency.neutralize_duplicate_executable_posts(task_id, platform, canonical_post_id=p1, conn=conn)

        with scheduler.get_connection(self.db_path) as conn:
            # Conta eventos e posts: nenhum registro foi deletado
            ev_count = conn.execute("SELECT COUNT(*) AS cnt FROM publication_events WHERE task_id = ?;", (task_id,)).fetchone()["cnt"]
            post_count = conn.execute("SELECT COUNT(*) AS cnt FROM scheduled_posts WHERE task_id = ?;", (task_id,)).fetchone()["cnt"]

        self.assertEqual(ev_count, 1)
        self.assertEqual(post_count, 2)


if __name__ == "__main__":
    unittest.main()
