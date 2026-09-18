"""
Testes unitários para o Scheduler + Publicação por Canal/Perfil (Fase V9-C).

Cobre os 25 cenários obrigatórios de conformidade:
1. task resolve profile original
2. active profile não altera task antiga
3. task legacy resolve default
4. channels ativos resolvidos corretamente
5. channel desabilitado ignorado
6. profile desabilitado bloqueia planejamento/publicação
7. scheduled post persiste profile_id
8. scheduled post persiste channel_id
9. YouTube/TikTok do mesmo profile criam destinos separados
10. duplicata task/channel/platform não é criada
11. publish resolve channel da task
12. manual publish não usa active profile errado
13. múltiplos canais ambíguos não escolhem arbitrariamente
14. profile growth_mode aplicado
15. global technical cap continua valendo
16. warmup não bypassa limit
17. execution-time revalidation funciona
18. channel desabilitado após planning bloqueia execução
19. profile desabilitado após planning bloqueia execução
20. VIEW ONLY continua bloqueando publicação
21. PAUSED continua bloqueando execução
22. fallback legado funciona sem channel
23. nenhuma secret é persistida
24. publication idempotency preservada
25. Operator Console exibe profile/channel quando disponível
"""
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.config import config
from app.models import const
from app.services import operator_console, profile_manager, scheduler
from app.services import task as task_module
from app.services import upload_post


class TestProfileScheduler(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_video_factory.db")
        self.task_base_dir = os.path.join(self.test_dir, "tasks")
        os.makedirs(self.task_base_dir, exist_ok=True)

        # Inicializa bancos
        operator_console.init_operator_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        scheduler.init_db(self.db_path)

        # Garante nó local como PRIMARY por padrão para testes com mutação
        operator_console.reset_instance_for_testing()
        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._current_role = operator_console.ROLE_PRIMARY

        # Configuração do Upload-Post no config.app para simulações
        self._orig_config = dict(config.app)
        config.app["upload_post_enabled"] = True
        config.app["upload_post_api_key"] = "test-api-key"
        config.app["upload_post_username"] = "test-user"
        config.app["upload_post_platforms"] = ["youtube", "tiktok"]

        # Configurações do Scheduler
        scheduler.save_settings(
            {
                "scheduler_enabled": True,
                "auto_publish_enabled": True,
                "dry_run": False,
                "tiktok_enabled": True,
                "youtube_enabled": True,
                "tiktok_limit_24h": 10,
                "youtube_limit_24h": 10,
            },
            db_path=self.db_path,
        )

        self.now = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)

        self._llm_patcher = patch(
            "app.services.llm.generate_social_metadata",
            return_value={"title": "Test Title", "caption": "Test Caption", "hashtags": ["#test"]},
        )
        self._llm_patcher.start()

    def tearDown(self):
        if hasattr(self, "_llm_patcher"):
            self._llm_patcher.stop()
        operator_console.reset_instance_for_testing()
        config.app.clear()
        config.app.update(self._orig_config)
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_task_files(self, task_id: str) -> str:
        """Cria estrutura de diretório e arquivo de vídeo final para a task."""
        t_dir = os.path.join(self.task_base_dir, task_id)
        os.makedirs(t_dir, exist_ok=True)
        v_path = os.path.join(t_dir, "final-1.mp4")
        with open(v_path, "wb") as f:
            f.write(b"fake_mp4_video_data")
        return v_path

    # 1. task resolve profile original
    def test_01_task_resolves_original_profile(self):
        prof = profile_manager.create_profile("Tech Brasil", is_active=True, db_path=self.db_path)
        task_id = "task-tech-01"
        profile_manager.set_task_profile_id(task_id, prof["id"], db_path=self.db_path)

        resolved_id = profile_manager.get_task_profile_id(task_id, db_path=self.db_path)
        self.assertEqual(resolved_id, prof["id"])

    # 2. active profile não altera task antiga
    def test_02_active_profile_does_not_alter_old_task(self):
        prof_a = profile_manager.create_profile("Perfil Antigo", is_active=True, db_path=self.db_path)
        prof_b = profile_manager.create_profile("Perfil Novo", is_active=True, db_path=self.db_path)

        task_id = "task-historical-01"
        profile_manager.set_task_profile_id(task_id, prof_a["id"], db_path=self.db_path)

        # Operador muda para perfil B
        profile_manager.set_active_profile_id(prof_b["id"], db_path=self.db_path)

        # Task histórica continua pertencendo a A
        resolved_id = profile_manager.get_task_profile_id(task_id, db_path=self.db_path)
        self.assertEqual(resolved_id, prof_a["id"])

    # 3. task legacy resolve default
    def test_03_task_legacy_resolves_default(self):
        resolved_id = profile_manager.get_task_profile_id("task-without-profile", db_path=self.db_path)
        self.assertEqual(resolved_id, profile_manager.DEFAULT_PROFILE_ID)

    # 4. channels ativos resolvidos corretamente
    def test_04_active_channels_resolved_correctly(self):
        prof = profile_manager.create_profile("Canal Show", is_active=True, db_path=self.db_path)
        ch_yt = profile_manager.create_channel(
            profile_id=prof["id"],
            platform="youtube",
            display_name="Canal Show YT",
            is_enabled=True,
            db_path=self.db_path,
        )
        ch_tt = profile_manager.create_channel(
            profile_id=prof["id"],
            platform="tiktok",
            display_name="Canal Show TT",
            is_enabled=True,
            db_path=self.db_path,
        )
        task_id = "task-show-01"
        profile_manager.set_task_profile_id(task_id, prof["id"], db_path=self.db_path)

        channels = profile_manager.resolve_task_channels(task_id, db_path=self.db_path)
        self.assertEqual(len(channels), 2)
        c_ids = {c["channel_id"] for c in channels}
        self.assertIn(ch_yt["channel_id"], c_ids)
        self.assertIn(ch_tt["channel_id"], c_ids)

    # 5. channel desabilitado ignorado
    def test_05_disabled_channel_ignored(self):
        prof = profile_manager.create_profile("Moda BR", is_active=True, db_path=self.db_path)
        ch_enabled = profile_manager.create_channel(
            profile_id=prof["id"],
            platform="youtube",
            display_name="Moda Ativo",
            is_enabled=True,
            db_path=self.db_path,
        )
        profile_manager.create_channel(
            profile_id=prof["id"],
            platform="youtube",
            display_name="Moda Inativo",
            is_enabled=False,
            db_path=self.db_path,
        )
        task_id = "task-moda-01"
        profile_manager.set_task_profile_id(task_id, prof["id"], db_path=self.db_path)

        channels = profile_manager.resolve_task_channels(task_id, db_path=self.db_path)
        self.assertEqual(len(channels), 1)
        self.assertEqual(channels[0]["channel_id"], ch_enabled["channel_id"])

    # 6. profile desabilitado bloqueia planejamento/publicação
    def test_06_disabled_profile_blocks_planning_and_publishing(self):
        prof = profile_manager.create_profile("Inativo Corp", is_active=False, db_path=self.db_path)
        task_id = "task-disabled-prof"
        profile_manager.set_task_profile_id(task_id, prof["id"], db_path=self.db_path)

        fake_task = {
            "task_id": task_id,
            "state": const.TASK_STATE_COMPLETE,
            "planned_platforms": ["youtube"],
            "subject": "Tema Inativo",
            "video_file": self._create_task_files(task_id),
        }

        # 1. Planejamento bloqueado
        res = scheduler.plan_schedule([fake_task], now=self.now, db_path=self.db_path)
        self.assertEqual(len(res), 0)

        # Evento operacional gerado
        events = operator_console.get_operational_events(event_type="PROFILE_DISABLED_BLOCK", db_path=self.db_path)
        self.assertGreaterEqual(len(events), 1)

        # 2. Publicação manual bloqueada
        with patch("app.utils.utils.task_dir", return_value=self.task_base_dir):
            success, err = task_module.publish_task(task_id, platforms=["youtube"], db_path=self.db_path)
            self.assertFalse(success)
            self.assertIn("disabled", err.lower())

    # 7. scheduled post persiste profile_id
    def test_07_scheduled_post_persists_profile_id(self):
        prof = profile_manager.create_profile("Finanças BR", is_active=True, db_path=self.db_path)
        task_id = "task-fin-01"
        profile_manager.set_task_profile_id(task_id, prof["id"], db_path=self.db_path)

        fake_task = {
            "task_id": task_id,
            "state": const.TASK_STATE_COMPLETE,
            "planned_platforms": ["youtube"],
            "subject": "Finanças 101",
            "video_file": self._create_task_files(task_id),
        }

        res = scheduler.plan_schedule([fake_task], now=self.now, db_path=self.db_path)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["profile_id"], prof["id"])

        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT profile_id FROM scheduled_posts WHERE task_id = ?;", (task_id,)).fetchone()
            self.assertEqual(row["profile_id"], prof["id"])

    # 8. scheduled post persiste channel_id
    def test_08_scheduled_post_persists_channel_id(self):
        prof = profile_manager.create_profile("Gamer BR", is_active=True, db_path=self.db_path)
        ch = profile_manager.create_channel(
            profile_id=prof["id"],
            platform="youtube",
            display_name="Gamer Central",
            is_enabled=True,
            db_path=self.db_path,
        )
        task_id = "task-game-01"
        profile_manager.set_task_profile_id(task_id, prof["id"], db_path=self.db_path)

        fake_task = {
            "task_id": task_id,
            "state": const.TASK_STATE_COMPLETE,
            "planned_platforms": ["youtube"],
            "subject": "Gameplay 01",
            "video_file": self._create_task_files(task_id),
        }

        res = scheduler.plan_schedule([fake_task], now=self.now, db_path=self.db_path)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["channel_id"], ch["channel_id"])

        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT channel_id FROM scheduled_posts WHERE task_id = ?;", (task_id,)).fetchone()
            self.assertEqual(row["channel_id"], ch["channel_id"])

    # 9. YouTube/TikTok do mesmo profile criam destinos separados
    def test_09_youtube_and_tiktok_same_profile_create_separate_destinations(self):
        prof = profile_manager.create_profile("Cross BR", is_active=True, db_path=self.db_path)
        ch_yt = profile_manager.create_channel(prof["id"], "youtube", "Cross YT", is_enabled=True, db_path=self.db_path)
        ch_tt = profile_manager.create_channel(prof["id"], "tiktok", "Cross TT", is_enabled=True, db_path=self.db_path)

        task_id = "task-cross-01"
        profile_manager.set_task_profile_id(task_id, prof["id"], db_path=self.db_path)

        fake_task = {
            "task_id": task_id,
            "state": const.TASK_STATE_COMPLETE,
            "planned_platforms": ["youtube", "tiktok"],
            "subject": "Cross Video",
            "video_file": self._create_task_files(task_id),
        }

        res = scheduler.plan_schedule([fake_task], now=self.now, db_path=self.db_path)
        self.assertEqual(len(res), 2)
        plats = {r["platform"] for r in res}
        self.assertEqual(plats, {"youtube", "tiktok"})
        c_ids = {r["channel_id"] for r in res}
        self.assertEqual(c_ids, {ch_yt["channel_id"], ch_tt["channel_id"]})

    # 10. duplicata task/channel/platform não é criada
    def test_10_duplicate_task_channel_platform_not_created(self):
        prof = profile_manager.create_profile("Dup Test", is_active=True, db_path=self.db_path)
        ch = profile_manager.create_channel(prof["id"], "youtube", "Dup YT", is_enabled=True, db_path=self.db_path)

        task_id = "task-dup-01"
        profile_manager.set_task_profile_id(task_id, prof["id"], db_path=self.db_path)

        fake_task = {
            "task_id": task_id,
            "state": const.TASK_STATE_COMPLETE,
            "planned_platforms": ["youtube"],
            "subject": "Dup Subject",
            "video_file": self._create_task_files(task_id),
        }

        res1 = scheduler.plan_schedule([fake_task], now=self.now, db_path=self.db_path)
        self.assertEqual(len(res1), 1)

        # Segunda execução: não duplica
        res2 = scheduler.plan_schedule([fake_task], now=self.now, db_path=self.db_path)
        self.assertEqual(len(res2), 0)

        with scheduler.get_connection(self.db_path) as conn:
            cnt = conn.execute("SELECT COUNT(*) AS c FROM scheduled_posts WHERE task_id = ?;", (task_id,)).fetchone()["c"]
            self.assertEqual(cnt, 1)

    # 11. publish resolve channel da task
    def test_11_publish_resolves_task_channel(self):
        prof_a = profile_manager.create_profile("Perfil Alfa", is_active=True, db_path=self.db_path)
        ch_a = profile_manager.create_channel(
            prof_a["id"], "youtube", "Canal Alfa", external_profile_name="UploadPost_Alfa", is_enabled=True, db_path=self.db_path
        )
        prof_b = profile_manager.create_profile("Perfil Beta", is_active=True, db_path=self.db_path)
        profile_manager.create_channel(
            prof_b["id"], "youtube", "Canal Beta", external_profile_name="UploadPost_Beta", is_enabled=True, db_path=self.db_path
        )

        task_id = "task-alfa-01"
        profile_manager.set_task_profile_id(task_id, prof_a["id"], db_path=self.db_path)
        self._create_task_files(task_id)

        # Ativa Perfil Beta
        profile_manager.set_active_profile_id(prof_b["id"], db_path=self.db_path)

        with patch("app.utils.utils.task_dir", return_value=self.task_base_dir), \
             patch.object(upload_post, "cross_post_video", return_value={"success": True, "request_id": "req-11"}) as mock_cross:
            success, err = task_module.publish_task(task_id, platforms=["youtube"], synchronous=True, db_path=self.db_path)
            self.assertTrue(success, f"Publish falhou: {err}")
            self.assertTrue(mock_cross.called)
            kwargs = mock_cross.call_args[1]
            self.assertEqual(kwargs.get("external_profile_name"), "UploadPost_Alfa")

    # 12. manual publish não usa active profile errado
    def test_12_manual_publish_does_not_use_wrong_active_profile(self):
        prof_x = profile_manager.create_profile("Target Prof", is_active=True, db_path=self.db_path)
        ch_x = profile_manager.create_channel(prof_x["id"], "youtube", "Target Ch", is_enabled=True, db_path=self.db_path)
        prof_active = profile_manager.create_profile("Operator Active", is_active=True, db_path=self.db_path)
        profile_manager.set_active_profile_id(prof_active["id"], db_path=self.db_path)

        task_id = "task-manual-01"
        profile_manager.set_task_profile_id(task_id, prof_x["id"], db_path=self.db_path)
        self._create_task_files(task_id)

        with patch("app.utils.utils.task_dir", return_value=self.task_base_dir), \
             patch.object(upload_post, "cross_post_video", return_value={"success": True, "request_id": "req-12"}):
            success, err = task_module.publish_task(task_id, platforms=["youtube"], synchronous=True, db_path=self.db_path)
            self.assertTrue(success)

        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT profile_id, channel_id FROM publication_events WHERE task_id = ?;", (task_id,)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["profile_id"], prof_x["id"])
            self.assertEqual(row["channel_id"], ch_x["channel_id"])

    # 13. múltiplos canais ambíguos não escolhem arbitrariamente
    def test_13_multiple_ambiguous_channels_do_not_pick_arbitrarily(self):
        prof = profile_manager.create_profile("Multi YT", is_active=True, db_path=self.db_path)
        ch1 = profile_manager.create_channel(prof["id"], "youtube", "YT Canal 1", is_enabled=True, db_path=self.db_path)
        ch2 = profile_manager.create_channel(prof["id"], "youtube", "YT Canal 2", is_enabled=True, db_path=self.db_path)

        task_id = "task-ambiguous-01"
        profile_manager.set_task_profile_id(task_id, prof["id"], db_path=self.db_path)
        self._create_task_files(task_id)

        with patch("app.utils.utils.task_dir", return_value=self.task_base_dir):
            # Chamada sem channel_id explícito deve falhar por ambiguidade
            success, err = task_module.publish_task(task_id, platforms=["youtube"], db_path=self.db_path)
            self.assertFalse(success)
            self.assertIn("ambiguity", err.lower())

            # Chamada com channel_id explícito deve prosseguir
            with patch.object(upload_post, "cross_post_video", return_value={"success": True}):
                success2, err2 = task_module.publish_task(
                    task_id, platforms=["youtube"], channel_id=ch2["channel_id"], synchronous=True, db_path=self.db_path
                )
                self.assertTrue(success2, f"Falha com channel_id: {err2}")

    # 14. profile growth_mode aplicado
    def test_14_profile_growth_mode_applied(self):
        prof = profile_manager.create_profile("Warmup Profile", growth_mode=const.GROWTH_MODE_WARMUP, is_active=True, db_path=self.db_path)
        # Limite warmup no youtube é 1 post/24h
        info = scheduler.get_platform_rate_limits("youtube", db_path=self.db_path, now=self.now, profile_id=prof["id"])
        self.assertEqual(info["growth_mode"], const.GROWTH_MODE_WARMUP)
        self.assertEqual(info["effective_limit"], 1)
        self.assertEqual(info["available_slots"], 1)

    # 15. global technical cap continua valendo
    def test_15_global_technical_cap_still_holds(self):
        # Configura limite técnico global baixo: 2 posts
        scheduler.save_settings({"youtube_limit_24h": 2}, db_path=self.db_path)
        prof = profile_manager.create_profile("Scale Profile", growth_mode=const.GROWTH_MODE_SCALE, is_active=True, db_path=self.db_path)
        # Scale permitiria até 10, mas o teto global de 2 deve prevalecer
        info = scheduler.get_platform_rate_limits("youtube", db_path=self.db_path, now=self.now, profile_id=prof["id"])
        self.assertEqual(info["effective_limit"], 2)

    # 16. warmup não bypassa limit
    def test_16_warmup_does_not_bypass_limit(self):
        prof = profile_manager.create_profile("Warmup Only", growth_mode=const.GROWTH_MODE_WARMUP, is_active=True, db_path=self.db_path)
        # Registra 1 publicação recente para este perfil
        scheduler.record_publication_event(
            task_id="prev-task",
            platform="youtube",
            status="success",
            published_at=self.now - timedelta(hours=2),
            profile_id=prof["id"],
            db_path=self.db_path,
        )

        info = scheduler.get_platform_rate_limits("youtube", db_path=self.db_path, now=self.now, profile_id=prof["id"])
        self.assertEqual(info["available_slots"], 0)

    # 17. execution-time revalidation funciona
    def test_17_execution_time_revalidation_works(self):
        prof = profile_manager.create_profile("Exec Reval", is_active=True, db_path=self.db_path)
        ch = profile_manager.create_channel(prof["id"], "youtube", "Reval Ch", is_enabled=True, db_path=self.db_path)
        task_id = "task-reval-01"
        profile_manager.set_task_profile_id(task_id, prof["id"], db_path=self.db_path)
        scheduler.save_task_platforms(task_id, ["youtube"], db_path=self.db_path)
        self._create_task_files(task_id)

        sched_time = (self.now - timedelta(minutes=5)).isoformat()
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at, profile_id, channel_id)
                VALUES (?, 'youtube', ?, 'planned', ?, ?, ?);
                """,
                (task_id, sched_time, sched_time, prof["id"], ch["channel_id"]),
            )

        with patch("app.utils.utils.task_dir", return_value=self.task_base_dir), \
             patch.object(upload_post, "cross_post_video", return_value={"success": True, "request_id": "req-17"}):
            cycle_res = scheduler.run_scheduler_cycle(now=self.now, db_path=self.db_path, task_base_dir=self.task_base_dir)
            self.assertEqual(cycle_res.get("status"), "published")

    # 18. channel desabilitado após planning bloqueia execução
    def test_18_channel_disabled_after_planning_blocks_execution(self):
        prof = profile_manager.create_profile("Late Disable", is_active=True, db_path=self.db_path)
        ch = profile_manager.create_channel(prof["id"], "youtube", "Late Ch", is_enabled=True, db_path=self.db_path)
        task_id = "task-late-ch"
        profile_manager.set_task_profile_id(task_id, prof["id"], db_path=self.db_path)
        scheduler.save_task_platforms(task_id, ["youtube"], db_path=self.db_path)
        self._create_task_files(task_id)

        sched_time = (self.now - timedelta(minutes=5)).isoformat()
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at, profile_id, channel_id)
                VALUES (?, 'youtube', ?, 'ready', ?, ?, ?);
                """,
                (task_id, sched_time, sched_time, prof["id"], ch["channel_id"]),
            )

        profile_manager.update_channel(ch["channel_id"], is_enabled=False, db_path=self.db_path)

        cycle_res = scheduler.run_scheduler_cycle(now=self.now, db_path=self.db_path, task_base_dir=self.task_base_dir)
        self.assertEqual(cycle_res.get("status"), "postponed")
        self.assertEqual(cycle_res.get("reason"), "channel_disabled")

        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT status FROM scheduled_posts WHERE task_id = ?;", (task_id,)).fetchone()
            self.assertEqual(row["status"], "ready")

    # 19. profile desabilitado após planning bloqueia execução
    def test_19_profile_disabled_after_planning_blocks_execution(self):
        prof = profile_manager.create_profile("Late Disable Prof", is_active=True, db_path=self.db_path)
        ch = profile_manager.create_channel(prof["id"], "youtube", "Late Ch 2", is_enabled=True, db_path=self.db_path)
        task_id = "task-late-prof"
        profile_manager.set_task_profile_id(task_id, prof["id"], db_path=self.db_path)
        scheduler.save_task_platforms(task_id, ["youtube"], db_path=self.db_path)
        self._create_task_files(task_id)

        sched_time = (self.now - timedelta(minutes=5)).isoformat()
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at, profile_id, channel_id)
                VALUES (?, 'youtube', ?, 'ready', ?, ?, ?);
                """,
                (task_id, sched_time, sched_time, prof["id"], ch["channel_id"]),
            )

        profile_manager.update_profile(prof["id"], is_active=False, db_path=self.db_path)

        cycle_res = scheduler.run_scheduler_cycle(now=self.now, db_path=self.db_path, task_base_dir=self.task_base_dir)
        self.assertEqual(cycle_res.get("status"), "postponed")
        self.assertEqual(cycle_res.get("reason"), "profile_disabled")

        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute("SELECT status FROM scheduled_posts WHERE task_id = ?;", (task_id,)).fetchone()
            self.assertEqual(row["status"], "ready")

    # 20. VIEW ONLY continua bloqueando publicação
    def test_20_view_only_blocks_publishing(self):
        with operator_console._instance_state_lock:
            operator_console._current_role = operator_console.ROLE_SECONDARY_VIEW_ONLY

        task_id = "task-view-only"
        success, err = task_module.publish_task(task_id, db_path=self.db_path)
        self.assertFalse(success)
        self.assertIn("view only", err.lower())

        cycle_res = scheduler.run_scheduler_cycle(now=self.now, db_path=self.db_path)
        self.assertEqual(cycle_res.get("status"), "skipped")
        self.assertEqual(cycle_res.get("reason"), "secondary_view_only")

    # 21. PAUSED continua bloqueando execução
    def test_21_paused_blocks_execution(self):
        operator_console.pause_factory(db_path=self.db_path)
        task_id = "task-paused"

        success, err = task_module.publish_task(task_id, db_path=self.db_path)
        self.assertFalse(success)
        self.assertIn("paused", err.lower())

        cycle_res = scheduler.run_scheduler_cycle(now=self.now, db_path=self.db_path)
        self.assertEqual(cycle_res.get("status"), "skipped")
        self.assertEqual(cycle_res.get("reason"), "factory_paused")

    # 22. fallback legado funciona sem channel
    def test_22_legacy_fallback_works_without_channel(self):
        task_id = "task-legacy-fallback"
        self._create_task_files(task_id)

        with patch("app.utils.utils.task_dir", return_value=self.task_base_dir), \
             patch.object(upload_post, "cross_post_video", return_value={"success": True, "request_id": "req-legacy"}):
            success, err = task_module.publish_task(task_id, platforms=["youtube"], synchronous=True, db_path=self.db_path)
            self.assertTrue(success, f"Fallback falhou: {err}")

        events = operator_console.get_operational_events(event_type="CHANNEL_RESOLUTION_FALLBACK", db_path=self.db_path)
        self.assertGreaterEqual(len(events), 1)

    # 23. nenhuma secret é persistida
    def test_23_no_secrets_persisted(self):
        prof = profile_manager.create_profile("Security Prof", is_active=True, db_path=self.db_path)
        ch = profile_manager.create_channel(
            prof["id"], "youtube", "Sec Ch", external_profile_name="SecLabel", is_enabled=True, db_path=self.db_path
        )
        task_id = "task-sec-01"
        profile_manager.set_task_profile_id(task_id, prof["id"], db_path=self.db_path)

        scheduler.record_publication_event(
            task_id=task_id,
            platform="youtube",
            status="success",
            external_id="ext-123",
            channel_id=ch["channel_id"],
            profile_id=prof["id"],
            db_path=self.db_path,
        )

        with scheduler.get_connection(self.db_path) as conn:
            for tbl in ["scheduled_posts", "publication_events", "publishing_channels", "content_profiles"]:
                rows = conn.execute(f"SELECT * FROM {tbl};").fetchall()
                for r in rows:
                    for col, val in dict(r).items():
                        self.assertNotIn(col.lower(), ["api_key", "secret", "token", "password", "oauth"])
                        if isinstance(val, str):
                            self.assertNotIn("bearer ", val.lower())

    # 24. publication idempotency preservada
    def test_24_publication_idempotency_preserved(self):
        prof = profile_manager.create_profile("Idem Prof", is_active=True, db_path=self.db_path)
        ch = profile_manager.create_channel(prof["id"], "youtube", "Idem Ch", is_enabled=True, db_path=self.db_path)
        task_id = "task-idem-01"
        profile_manager.set_task_profile_id(task_id, prof["id"], db_path=self.db_path)
        self._create_task_files(task_id)

        scheduler.record_publication_event(
            task_id=task_id,
            platform="youtube",
            status="success",
            channel_id=ch["channel_id"],
            profile_id=prof["id"],
            db_path=self.db_path,
        )

        with patch("app.utils.utils.task_dir", return_value=self.task_base_dir):
            success, err = task_module.publish_task(
                task_id, platforms=["youtube"], channel_id=ch["channel_id"], synchronous=True, db_path=self.db_path
            )
            self.assertFalse(success)
            self.assertIn("already published", err.lower())

    # 25. Operator Console exibe profile/channel quando disponível
    def test_25_operator_console_shows_profile_and_channel_when_available(self):
        prof = profile_manager.create_profile("Console Prof", is_active=True, db_path=self.db_path)
        ch = profile_manager.create_channel(prof["id"], "youtube", "Console Canal YT", is_enabled=True, db_path=self.db_path)
        task_id = "task-console-01"

        iso_future = (self.now + timedelta(hours=1)).isoformat()
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at, profile_id, channel_id)
                VALUES (?, 'youtube', ?, 'planned', ?, ?, ?);
                """,
                (task_id, iso_future, iso_future, prof["id"], ch["channel_id"]),
            )

        summary = operator_console.get_scheduler_queue_summary(db_path=self.db_path)
        upcoming = summary.get("upcoming_posts", [])
        self.assertGreaterEqual(len(upcoming), 1)
        first = upcoming[0]
        self.assertEqual(first.get("profile_id"), prof["id"])
        self.assertEqual(first.get("channel_id"), ch["channel_id"])
        self.assertEqual(first.get("profile_name"), "Console Prof")
        self.assertEqual(first.get("channel_name"), "Console Canal YT")


if __name__ == "__main__":
    unittest.main()
