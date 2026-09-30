"""
Testes direcionados da Fase de Reconciliação Post for Me e TikTok Autônomo.

Cobre rigorosamente os 8 cenários exigidos:
1. default + YouTube ON + TikTok ON + ambos canais habilitados: nova task autônoma planeja YouTube e TikTok.
2. perfil Mistérios sem canal TikTok: continua planejando somente YouTube.
3. TikTok global OFF: default continua somente YouTube.
4. timeout local + exatamente 1 remote success: reconcilia para publication_event success + scheduled_post published sem novo upload.
5. remote active: não duplica upload.
6. remote inconsistent/múltiplo: fail closed.
7. retry pendente não provoca reserva conflitante para o mesmo canal/slot.
8. fila futura normal continua permitida.
"""

import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.models import const
from app.services import (
    autonomous_production,
    operator_console,
    post_for_me,
    profile_manager,
    scheduler,
    youtube_publisher,
)
from app.services import state as sm


class TestV15ReconciliationAndTikTok(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_dir = self.temp_dir.name
        self.db_path = os.path.join(self.tmp_dir, "test_v15.db")

        # Inicializa bancos de dados de teste isolados
        operator_console.init_operator_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        profile_manager.ensure_default_profile(db_path=self.db_path)
        scheduler.init_db(self.db_path)

        # Configura papel PRIMARY e retoma fábrica
        operator_console.reset_instance_for_testing()
        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._current_role = operator_console.ROLE_PRIMARY
        operator_console.resume_factory(db_path=self.db_path)

        # Configura settings padrão de scheduler e provedores
        scheduler.set_setting("scheduler_enabled", "true", db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", "true", db_path=self.db_path)
        scheduler.set_setting("dry_run", "false", db_path=self.db_path)
        scheduler.set_setting("youtube_enabled", "true", db_path=self.db_path)
        scheduler.set_setting("tiktok_enabled", "true", db_path=self.db_path)
        youtube_publisher.set_youtube_publish_provider("post_for_me", db_path=self.db_path)

        self.video_file = os.path.join(self.tmp_dir, "final-0.mp4")
        with open(self.video_file, "wb") as f:
            f.write(b"\x00\x00\x00\x18ftypmp42" + b"X" * 1024)

    def tearDown(self):
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. default + YouTube ON + TikTok ON + ambos canais habilitados
    # -------------------------------------------------------------------------
    def test_1_default_youtube_and_tiktok_enabled_plans_both(self):
        """Verifica que nova task do perfil default planeja YouTube e TikTok reutilizando o mesmo asset."""
        planned = autonomous_production.resolve_autonomous_planned_platforms("default", db_path=self.db_path)
        self.assertEqual(planned, ["youtube", "tiktok"])

        elig_yt = autonomous_production.check_asset_eligibility_for_destination(
            {"profile_id": "default"}, "youtube", db_path=self.db_path
        )
        self.assertTrue(elig_yt["eligible"])
        self.assertTrue(elig_yt["enabled"])

        elig_tt = autonomous_production.check_asset_eligibility_for_destination(
            {"profile_id": "default"}, "tiktok", db_path=self.db_path
        )
        self.assertTrue(elig_tt["eligible"])
        self.assertTrue(elig_tt["enabled"])

        # Planejamento no Scheduler para o perfil default com ambas as plataformas
        task_id = "task-auton-dual-dest"
        task_dir = os.path.join(self.tmp_dir, task_id)
        os.makedirs(task_dir, exist_ok=True)
        shutil.copyfile(self.video_file, os.path.join(task_dir, "final-0.mp4"))

        task_data = {
            "task_id": task_id,
            "profile_id": "default",
            "planned_platforms": planned,
            "video_file": os.path.join(task_dir, "final-0.mp4"),
        }

        now = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
        scheduled = scheduler.plan_schedule([task_data], now=now, db_path=self.db_path, task_base_dir=self.tmp_dir)

        self.assertEqual(len(scheduled), 2)
        scheduled_plats = {s["platform"] for s in scheduled}
        self.assertEqual(scheduled_plats, {"youtube", "tiktok"})
        scheduled_channels = {s["channel_id"] for s in scheduled}
        self.assertEqual(scheduled_channels, {"channel-default-youtube", "channel-default-tiktok"})
        # Verifica que ambas as linhas referenciam exatamente a mesma task (mesmo asset de vídeo)
        for s in scheduled:
            self.assertEqual(s["task_id"], task_id)

    # -------------------------------------------------------------------------
    # 2. Perfil Mistérios sem canal TikTok: planeja somente YouTube
    # -------------------------------------------------------------------------
    def test_2_profile_misterios_without_tiktok_plans_youtube_only(self):
        """Verifica que perfil sem canal TikTok planeja apenas YouTube e nunca roteia para channel-default-tiktok."""
        profile_manager.create_profile(
            profile_id="profile-historias-misterio",
            name="Histórias de Mistério",
            is_active=True,
            db_path=self.db_path,
        )
        profile_manager.create_channel(
            channel_id="channel-historias-misterio-youtube",
            profile_id="profile-historias-misterio",
            platform="youtube",
            display_name="Mistérios YouTube",
            is_enabled=True,
            db_path=self.db_path,
        )

        planned = autonomous_production.resolve_autonomous_planned_platforms(
            "profile-historias-misterio", db_path=self.db_path
        )
        self.assertEqual(planned, ["youtube"])

        elig_tt = autonomous_production.check_asset_eligibility_for_destination(
            {"profile_id": "profile-historias-misterio"}, "tiktok", db_path=self.db_path
        )
        self.assertFalse(elig_tt["eligible"])
        self.assertIn("tiktok_channel_not_available_or_ambiguous", elig_tt["reasons"])

        task_id = "task-misterio-yt-only"
        task_dir = os.path.join(self.tmp_dir, task_id)
        os.makedirs(task_dir, exist_ok=True)
        shutil.copyfile(self.video_file, os.path.join(task_dir, "final-0.mp4"))
        profile_manager.save_task_profile(task_id, "profile-historias-misterio", db_path=self.db_path)

        task_data = {
            "task_id": task_id,
            "profile_id": "profile-historias-misterio",
            "planned_platforms": planned,
            "video_file": os.path.join(task_dir, "final-0.mp4"),
        }

        now = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
        scheduled = scheduler.plan_schedule([task_data], now=now, db_path=self.db_path, task_base_dir=self.tmp_dir)

        self.assertEqual(len(scheduled), 1)
        self.assertEqual(scheduled[0]["platform"], "youtube")
        self.assertEqual(scheduled[0]["channel_id"], "channel-historias-misterio-youtube")
        self.assertNotEqual(scheduled[0]["channel_id"], "channel-default-tiktok")

    # -------------------------------------------------------------------------
    # 3. TikTok global OFF: default continua somente YouTube
    # -------------------------------------------------------------------------
    def test_3_tiktok_global_off_default_plans_youtube_only(self):
        """Verifica que quando tiktok_enabled=false, o perfil default planeja somente YouTube."""
        scheduler.set_setting("tiktok_enabled", "false", db_path=self.db_path)

        planned = autonomous_production.resolve_autonomous_planned_platforms("default", db_path=self.db_path)
        self.assertEqual(planned, ["youtube"])

        elig_tt = autonomous_production.check_asset_eligibility_for_destination(
            {"profile_id": "default"}, "tiktok", db_path=self.db_path
        )
        self.assertFalse(elig_tt["eligible"])
        self.assertIn("tiktok_disabled_globally", elig_tt["reasons"])

    # -------------------------------------------------------------------------
    # 4. Timeout local + exatamente 1 remote success: reconcilia sem novo upload
    # -------------------------------------------------------------------------
    def test_4_local_timeout_with_remote_success_reconciles_without_upload(self):
        """Timeout local com 1 remote success reconcilia publication_event e scheduled_posts sem novo upload."""
        task_id = "task-local-timeout-reconciled"
        now = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
        iso_now = scheduler._to_iso(now)

        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO scheduled_posts (
                    task_id, platform, profile_id, channel_id, scheduled_at, status,
                    attempts, last_error, created_at
                ) VALUES (?, 'youtube', 'default', 'channel-default-youtube', ?, 'ready', 1,
                          'timeout: Post for Me post sp_123 still processing after 120s', ?);
                """,
                (task_id, iso_now, iso_now),
            )

        existing_success = {
            "post_id": "sp_mock_111",
            "social_account_id": "acc_yt_default",
            "status": "success",
            "external_id": f"video-factory:{task_id}:youtube:channel-default-youtube",
            "result_info": {
                "youtube_video_id": "yt_remote_vid_999",
                "url": "https://www.youtube.com/watch?v=yt_remote_vid_999",
                "privacy_status": "public",
            },
            "post": {
                "platform_configurations": {
                    "youtube": {"privacy_status": "public"}
                }
            },
        }
        mock_classification = {
            "success_posts": [existing_success],
            "active_posts": [],
            "failed_posts": [],
            "inconsistent_posts": [],
        }

        with patch.object(post_for_me.post_for_me_client, "is_configured", return_value=True), \
             patch.object(post_for_me.post_for_me_client, "resolve_youtube_account", return_value={"id": "acc_yt_default"}), \
             patch.object(post_for_me.post_for_me_client, "classify_existing_posts", return_value=mock_classification), \
             patch.object(post_for_me.post_for_me_client, "create_media_upload_url") as mock_upload, \
             patch.object(post_for_me.post_for_me_client, "create_social_post") as mock_create_post:

            recon = post_for_me.reconcile_post_for_me_status(
                task_id=task_id,
                platform="youtube",
                channel_id="channel-default-youtube",
                profile_id="default",
                db_path=self.db_path,
            )

            self.assertEqual(recon["status"], "reconciled_success")
            self.assertEqual(recon["external_id"], "yt_remote_vid_999")
            self.assertEqual(recon["external_url"], "https://www.youtube.com/watch?v=yt_remote_vid_999")

            # Garantia: ZERO novas chamadas de upload / criação de post
            mock_upload.assert_not_called()
            mock_create_post.assert_not_called()

            # Estado local no banco: scheduled_posts marcado como 'published', last_error limpo, attempts=1 preservado
            with scheduler.get_connection(self.db_path) as conn:
                post_row = conn.execute("SELECT * FROM scheduled_posts WHERE task_id=?", (task_id,)).fetchone()
                self.assertEqual(post_row["status"], "published")
                self.assertIsNone(post_row["last_error"])
                self.assertEqual(post_row["attempts"], 1)

                events = conn.execute("SELECT * FROM publication_events WHERE task_id=?", (task_id,)).fetchall()
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0]["status"], "success")
                self.assertEqual(events[0]["external_id"], "yt_remote_vid_999")
                self.assertEqual(events[0]["channel_id"], "channel-default-youtube")

    # -------------------------------------------------------------------------
    # 5. Remote active: não duplica upload
    # -------------------------------------------------------------------------
    def test_5_remote_active_does_not_duplicate_upload(self):
        """Verifica que quando post está ativo remotamente, reconciliação posterga e não duplica upload."""
        task_id = "task-remote-active"
        task_dir = os.path.join(self.tmp_dir, task_id)
        os.makedirs(task_dir, exist_ok=True)
        shutil.copyfile(self.video_file, os.path.join(task_dir, "final-0.mp4"))

        now = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
        iso_now = scheduler._to_iso(now)

        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO scheduled_posts (
                    task_id, platform, profile_id, channel_id, scheduled_at, status,
                    attempts, last_error, created_at
                ) VALUES (?, 'youtube', 'default', 'channel-default-youtube', ?, 'ready', 1,
                          'timeout: still processing', ?);
                """,
                (task_id, iso_now, iso_now),
            )

        mock_classification = {
            "success_posts": [],
            "active_posts": [{
                "post_id": "sp_active_mock",
                "social_post": {"id": "sp_active_mock", "status": "processing"},
            }],
            "failed_posts": [],
            "inconsistent_posts": [],
        }

        with patch.object(post_for_me.post_for_me_client, "is_configured", return_value=True), \
             patch.object(post_for_me.post_for_me_client, "resolve_youtube_account", return_value={"id": "acc_yt_default"}), \
             patch.object(post_for_me.post_for_me_client, "classify_existing_posts", return_value=mock_classification), \
             patch.object(post_for_me.post_for_me_client, "create_media_upload_url") as mock_upload, \
             patch.object(post_for_me.post_for_me_client, "create_social_post") as mock_create_post, \
             patch("app.services.task.publish_task") as mock_publish:

            recon = post_for_me.reconcile_post_for_me_status(
                task_id=task_id,
                platform="youtube",
                channel_id="channel-default-youtube",
                profile_id="default",
                db_path=self.db_path,
            )
            self.assertEqual(recon["status"], "active")

            cycle_res = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tmp_dir)
            self.assertEqual(cycle_res["status"], "postponed")
            self.assertEqual(cycle_res["reason"], "remote_active")

            mock_upload.assert_not_called()
            mock_create_post.assert_not_called()
            mock_publish.assert_not_called()

    # -------------------------------------------------------------------------
    # 6. Remote inconsistent / múltiplo: Fail Closed
    # -------------------------------------------------------------------------
    def test_6_remote_inconsistent_or_multiple_fails_closed(self):
        """Verifica fail closed imediato diante de múltiplos sucessos ou estados inconsistentes."""
        task_id = "task-ambiguous"
        task_dir = os.path.join(self.tmp_dir, task_id)
        os.makedirs(task_dir, exist_ok=True)
        shutil.copyfile(self.video_file, os.path.join(task_dir, "final-0.mp4"))

        now = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
        iso_now = scheduler._to_iso(now)

        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO scheduled_posts (
                    task_id, platform, profile_id, channel_id, scheduled_at, status,
                    attempts, last_error, created_at
                ) VALUES (?, 'youtube', 'default', 'channel-default-youtube', ?, 'ready', 1,
                          'timeout: still processing', ?);
                """,
                (task_id, iso_now, iso_now),
            )

        # Múltiplos sucessos -> ambiguidade -> fail closed
        mock_classification = {
            "success_posts": [{"post_id": "sp_1"}, {"post_id": "sp_2"}],
            "active_posts": [],
            "failed_posts": [],
            "inconsistent_posts": [],
        }

        with patch.object(post_for_me.post_for_me_client, "is_configured", return_value=True), \
             patch.object(post_for_me.post_for_me_client, "resolve_youtube_account", return_value={"id": "acc_yt_default"}), \
             patch.object(post_for_me.post_for_me_client, "classify_existing_posts", return_value=mock_classification), \
             patch.object(post_for_me.post_for_me_client, "create_media_upload_url") as mock_upload:

            recon = post_for_me.reconcile_post_for_me_status(
                task_id=task_id,
                platform="youtube",
                channel_id="channel-default-youtube",
                profile_id="default",
                db_path=self.db_path,
            )
            self.assertEqual(recon["status"], "inconsistent")
            self.assertEqual(recon["error_code"], "AMBIGUOUS_POSTS")
            mock_upload.assert_not_called()

            cycle_res = scheduler.run_scheduler_cycle(now=now, db_path=self.db_path, task_base_dir=self.tmp_dir)
            self.assertEqual(cycle_res["status"], "failed")
            self.assertEqual(cycle_res["reason"], "remote_inconsistent")
            mock_upload.assert_not_called()

            with scheduler.get_connection(self.db_path) as conn:
                row = conn.execute("SELECT status FROM scheduled_posts WHERE task_id=?", (task_id,)).fetchone()
                self.assertEqual(row["status"], "failed")

    # -------------------------------------------------------------------------
    # 7. Retry pendente não provoca reserva conflitante para o mesmo canal/slot
    # -------------------------------------------------------------------------
    def test_7_pending_retry_prevents_conflicting_reservation(self):
        """Verifica que uma tentativa anterior pendente de retry bloqueia colisão no mesmo canal até reconciliação."""
        now = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
        iso_now = scheduler._to_iso(now)

        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO scheduled_posts (
                    task_id, platform, profile_id, channel_id, scheduled_at, status,
                    attempts, last_error, created_at
                ) VALUES ('task-retry-pending', 'youtube', 'default', 'channel-default-youtube', ?, 'ready', 1,
                          'timeout: temporary', ?);
                """,
                (iso_now, iso_now),
            )

        # Provedor remoto ainda sem sucesso (ex: active)
        mock_classification = {
            "success_posts": [],
            "active_posts": [{"post_id": "sp_active"}],
            "failed_posts": [],
            "inconsistent_posts": [],
        }

        with patch.object(post_for_me.post_for_me_client, "is_configured", return_value=True), \
             patch.object(post_for_me.post_for_me_client, "resolve_youtube_account", return_value={"id": "acc_yt_default"}), \
             patch.object(post_for_me.post_for_me_client, "classify_existing_posts", return_value=mock_classification):

            task_b_id = "task-candidate-b"
            task_dir = os.path.join(self.tmp_dir, task_b_id)
            os.makedirs(task_dir, exist_ok=True)
            shutil.copyfile(self.video_file, os.path.join(task_dir, "final-0.mp4"))

            task_b_data = {
                "task_id": task_b_id,
                "profile_id": "default",
                "planned_platforms": ["youtube"],
                "video_file": os.path.join(task_dir, "final-0.mp4"),
            }

            scheduled = scheduler.plan_schedule([task_b_data], now=now, db_path=self.db_path, task_base_dir=self.tmp_dir)
            # Planejamento bloqueado para evitar colisão com retry pendente
            self.assertEqual(len(scheduled), 0)

            with scheduler.get_connection(self.db_path) as conn:
                b_row = conn.execute("SELECT * FROM scheduled_posts WHERE task_id=?", (task_b_id,)).fetchone()
                self.assertIsNone(b_row)

        # Agora o retry anterior é reconciliado com sucesso remoto
        existing_reconciled = {
            "post_id": "sp_success_reconciled",
            "social_account_id": "acc_yt_default",
            "status": "success",
            "external_id": "video-factory:task-retry-pending:youtube:channel-default-youtube",
            "result_info": {
                "youtube_video_id": "vid_rec_777",
                "url": "https://youtu.be/vid_rec_777",
                "privacy_status": "public",
            },
            "post": {
                "platform_configurations": {
                    "youtube": {"privacy_status": "public"}
                }
            },
        }
        mock_success_classification = {
            "success_posts": [existing_reconciled],
            "active_posts": [],
            "failed_posts": [],
            "inconsistent_posts": [],
        }

        # Permitir capacidade diária no profile para receber o post b após publicação do anterior
        profile_manager.update_profile("default", growth_mode="scale", db_path=self.db_path)

        with patch.object(post_for_me.post_for_me_client, "is_configured", return_value=True), \
             patch.object(post_for_me.post_for_me_client, "resolve_youtube_account", return_value={"id": "acc_yt_default"}), \
             patch.object(post_for_me.post_for_me_client, "classify_existing_posts", return_value=mock_success_classification):

            # Planejamento agora deve reconciliar a task pendente e permitir agendar task B
            scheduled_after = scheduler.plan_schedule([task_b_data], now=now, db_path=self.db_path, task_base_dir=self.tmp_dir)
            self.assertEqual(len(scheduled_after), 1)
            self.assertEqual(scheduled_after[0]["task_id"], task_b_id)

    # -------------------------------------------------------------------------
    # 8. Fila futura normal continua permitida
    # -------------------------------------------------------------------------
    def test_8_normal_future_queue_continues_to_be_allowed(self):
        """Verifica que post futuro normal (status='planned', attempts=0) não bloqueia agendamento normal de fila futura."""
        profile_manager.update_profile("default", growth_mode="scale", db_path=self.db_path)
        now = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
        iso_future = scheduler._to_iso(now + timedelta(hours=6))

        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO scheduled_posts (
                    task_id, platform, profile_id, channel_id, scheduled_at, status,
                    attempts, last_error, created_at
                ) VALUES ('task-normal-planned', 'youtube', 'default', 'channel-default-youtube', ?, 'planned', 0,
                          NULL, ?);
                """,
                (iso_future, iso_future),
            )

        task_c_id = "task-candidate-c"
        task_dir = os.path.join(self.tmp_dir, task_c_id)
        os.makedirs(task_dir, exist_ok=True)
        shutil.copyfile(self.video_file, os.path.join(task_dir, "final-0.mp4"))

        task_c_data = {
            "task_id": task_c_id,
            "profile_id": "default",
            "planned_platforms": ["youtube"],
            "video_file": os.path.join(task_dir, "final-0.mp4"),
        }

        scheduled = scheduler.plan_schedule([task_c_data], now=now, db_path=self.db_path, task_base_dir=self.tmp_dir)
        self.assertEqual(len(scheduled), 1)
        self.assertEqual(scheduled[0]["task_id"], task_c_id)
        self.assertEqual(scheduled[0]["status"], "planned")


if __name__ == "__main__":
    unittest.main()
