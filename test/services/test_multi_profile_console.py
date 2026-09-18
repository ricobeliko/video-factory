"""
Testes de Homologação Final V9-D — Multi-Profile Console & End-to-End System Safety.
Cobertura de todos os 30 itens especificados na FASE V9-D.
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


class TestMultiProfileConsole(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_v9d.db")
        self.task_base_dir = os.path.join(self.test_dir, "tasks")
        os.makedirs(self.task_base_dir, exist_ok=True)

        # Inicializa bancos
        operator_console.init_operator_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        profile_manager.ensure_default_profile(db_path=self.db_path)
        scheduler.init_db(self.db_path)

        # Configura instância como PRIMARY
        operator_console.reset_instance_for_testing()
        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._current_role = operator_console.ROLE_PRIMARY

        # Upload-Post mock config
        self._orig_config = dict(config.app)
        config.app["upload_post_enabled"] = True
        config.app["upload_post_api_key"] = "mock-key"
        config.app["upload_post_username"] = "mock-user"
        config.app["upload_post_platforms"] = ["youtube", "tiktok"]

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

        # Mock LLM social metadata para testes determinísticos
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
        t_dir = os.path.join(self.task_base_dir, task_id)
        os.makedirs(t_dir, exist_ok=True)
        v_file = os.path.join(t_dir, "final-1.mp4")
        with open(v_file, "wb") as f:
            f.write(b"FAKE_MP4_V9D_CONTENT")
        return v_file

    # 1. list profiles na UI/backend
    def test_01_list_profiles(self):
        profs = profile_manager.list_profiles(db_path=self.db_path)
        self.assertGreaterEqual(len(profs), 1)
        self.assertTrue(any(p["id"] == "default" for p in profs))

        overview = operator_console.get_profile_operations_overview(db_path=self.db_path)
        self.assertIsInstance(overview, list)
        self.assertGreaterEqual(len(overview), 1)
        self.assertTrue(any(po["profile_id"] == "default" for po in overview))

    # 2. create profile
    def test_02_create_profile(self):
        prof = profile_manager.create_profile(
            name="Curiosidades Brasil",
            niche="curiosidades",
            language="pt-BR",
            region="BR",
            default_preset="cross_platform",
            growth_mode="warmup",
            is_active=True,
            db_path=self.db_path,
        )
        self.assertIsNotNone(prof["id"])
        self.assertEqual(prof["name"], "Curiosidades Brasil")
        self.assertEqual(prof["slug"], "curiosidades-brasil")
        self.assertEqual(prof["growth_mode"], "warmup")
        self.assertTrue(prof["is_active"])

    # 3. edit profile
    def test_03_edit_profile(self):
        prof = profile_manager.create_profile(
            name="Nome Original",
            growth_mode="normal",
            db_path=self.db_path,
        )
        updated = profile_manager.update_profile(
            profile_id=prof["id"],
            name="Nome Alterado",
            growth_mode="scale",
            niche="novo_nicho",
            db_path=self.db_path,
        )
        self.assertEqual(updated["id"], prof["id"])
        self.assertEqual(updated["name"], "Nome Alterado")
        self.assertEqual(updated["growth_mode"], "scale")
        self.assertEqual(updated["niche"], "novo_nicho")

    # 4. default profile protegido
    def test_04_default_profile_protected(self):
        with self.assertRaises(ValueError) as ctx:
            profile_manager.set_profile_active("default", False, db_path=self.db_path)
        self.assertIn("segurança", str(ctx.exception).lower())

        with self.assertRaises(ValueError) as ctx2:
            profile_manager.update_profile("default", is_active=False, db_path=self.db_path)
        self.assertIn("segurança", str(ctx2.exception).lower())

        # Verifica que o default continua ativo
        default_prof = profile_manager.get_profile("default", db_path=self.db_path)
        self.assertTrue(default_prof["is_active"])

    # 5. deactivate profile
    def test_05_deactivate_profile(self):
        prof = profile_manager.create_profile("Desativavel", is_active=True, db_path=self.db_path)
        ok = profile_manager.set_profile_active(prof["id"], False, db_path=self.db_path)
        self.assertTrue(ok)
        fetched = profile_manager.get_profile(prof["id"], db_path=self.db_path)
        self.assertFalse(fetched["is_active"])

    # 6. active profile selector
    def test_06_active_profile_selector(self):
        prof = profile_manager.create_profile("Novo Ativo", is_active=True, db_path=self.db_path)
        profile_manager.set_active_profile(prof["id"], db_path=self.db_path)
        active_id = profile_manager.get_active_profile_id(db_path=self.db_path)
        self.assertEqual(active_id, prof["id"])

    # 7. VIEW ONLY não troca profile
    def test_07_view_only_does_not_change_active_profile(self):
        prof = profile_manager.create_profile("Profile Vo", is_active=True, db_path=self.db_path)
        with operator_console._instance_state_lock:
            operator_console._current_role = operator_console.ROLE_SECONDARY_VIEW_ONLY

        with self.assertRaises((PermissionError, RuntimeError)) as ctx:
            profile_manager.set_active_profile(prof["id"], db_path=self.db_path)
        self.assertIn("view only", str(ctx.exception).lower())

    # 8. create YouTube channel
    def test_08_create_youtube_channel(self):
        prof = profile_manager.create_profile("Canal YT Prof", is_active=True, db_path=self.db_path)
        ch = profile_manager.create_channel(
            prof["id"], "youtube", "Canal YouTube Teste", external_profile_name="uploadpost_yt", is_enabled=True, db_path=self.db_path
        )
        self.assertIsNotNone(ch["id"])
        self.assertEqual(ch["platform"], "youtube")
        self.assertEqual(ch["external_profile_name"], "uploadpost_yt")

    # 9. create TikTok channel
    def test_09_create_tiktok_channel(self):
        prof = profile_manager.create_profile("Canal TT Prof", is_active=True, db_path=self.db_path)
        ch = profile_manager.create_channel(
            prof["id"], "tiktok", "Canal TikTok Teste", external_profile_name="uploadpost_tt", is_enabled=True, db_path=self.db_path
        )
        self.assertEqual(ch["platform"], "tiktok")

    # 10. edit channel
    def test_10_edit_channel(self):
        prof = profile_manager.create_profile("Edit Ch Prof", is_active=True, db_path=self.db_path)
        ch = profile_manager.create_channel(prof["id"], "youtube", "Nome Original", db_path=self.db_path)
        cid = ch["channel_id"]
        up = profile_manager.update_channel(cid, display_name="Nome Editado", external_profile_name="ext_novo", db_path=self.db_path)
        self.assertEqual(up["display_name"], "Nome Editado")
        self.assertEqual(up["external_profile_name"], "ext_novo")

    # 11. disable channel
    def test_11_disable_channel(self):
        prof = profile_manager.create_profile("Dis Ch Prof", is_active=True, db_path=self.db_path)
        ch = profile_manager.create_channel(prof["id"], "youtube", "Canal Ativo", is_enabled=True, db_path=self.db_path)
        cid = ch["channel_id"]
        profile_manager.set_channel_enabled(cid, False, db_path=self.db_path)
        fetched = profile_manager.get_channel(cid, db_path=self.db_path)
        self.assertFalse(fetched["is_enabled"])

    # 12. VIEW ONLY não muta channel
    def test_12_view_only_cannot_mutate_channel(self):
        prof = profile_manager.create_profile("VO Ch Prof", is_active=True, db_path=self.db_path)
        ch = profile_manager.create_channel(prof["id"], "youtube", "Canal Original", db_path=self.db_path)
        cid = ch["channel_id"]

        with operator_console._instance_state_lock:
            operator_console._current_role = operator_console.ROLE_SECONDARY_VIEW_ONLY

        with self.assertRaises((PermissionError, RuntimeError)):
            profile_manager.create_channel(prof["id"], "tiktok", "Canal Bloqueado", db_path=self.db_path)

        with self.assertRaises((PermissionError, RuntimeError)):
            profile_manager.update_channel(cid, display_name="Mutação Bloqueada", db_path=self.db_path)

        with self.assertRaises((PermissionError, RuntimeError)):
            profile_manager.set_channel_enabled(cid, False, db_path=self.db_path)

    # 13. nenhuma secret persistida
    def test_13_no_secrets_persisted(self):
        prof = profile_manager.create_profile("No Secret", is_active=True, db_path=self.db_path)
        ch = profile_manager.create_channel(
            prof["id"], "youtube", "YT Sec", external_profile_name="public_handle", db_path=self.db_path
        )
        with scheduler.get_connection(self.db_path) as conn:
            p_cols = [c["name"].lower() for c in conn.execute("PRAGMA table_info(content_profiles);").fetchall()]
            c_cols = [c["name"].lower() for c in conn.execute("PRAGMA table_info(publishing_channels);").fetchall()]
            forbidden = ["api_key", "secret", "password", "token", "oauth"]
            for f in forbidden:
                self.assertNotIn(f, p_cols)
                self.assertNotIn(f, c_cols)

    # 14. múltiplos canais mesma plataforma exibidos
    def test_14_multiple_channels_same_platform_displayed(self):
        prof = profile_manager.create_profile("Multi Same", is_active=True, db_path=self.db_path)
        ch1 = profile_manager.create_channel(prof["id"], "youtube", "Canal 1", is_enabled=True, db_path=self.db_path)
        ch2 = profile_manager.create_channel(prof["id"], "youtube", "Canal 2", is_enabled=True, db_path=self.db_path)

        overview = operator_console.get_profile_operations_overview(db_path=self.db_path)
        po = next(p for p in overview if p["profile_id"] == prof["id"])
        self.assertEqual(po["channels_count"], 2)
        self.assertEqual(po["channels_enabled"], 2)

    # 15. queue aceita NULL legado
    def test_15_queue_accepts_null_legacy(self):
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at, profile_id, channel_id)
                VALUES ('task-legacy-01', 'youtube', '2026-09-18T14:00:00Z', 'planned', '2026-09-18T12:00:00Z', NULL, NULL);
                """
            )
        summary = operator_console.get_scheduler_queue_summary(db_path=self.db_path)
        posts = summary["upcoming_posts"]
        leg = next(p for p in posts if p["task_id"] == "task-legacy-01")
        self.assertIsNone(leg["profile_id"])
        self.assertIsNone(leg["channel_id"])
        self.assertIsNone(leg.get("profile_name"))
        self.assertIsNone(leg.get("channel_name"))

    # 16. queue mostra profile
    def test_16_queue_shows_profile(self):
        prof = profile_manager.create_profile("Queue Prof", is_active=True, db_path=self.db_path)
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at, profile_id)
                VALUES ('task-qp-01', 'youtube', '2026-09-18T14:00:00Z', 'planned', '2026-09-18T12:00:00Z', ?);
                """,
                (prof["id"],),
            )
        summary = operator_console.get_scheduler_queue_summary(db_path=self.db_path)
        post = next(p for p in summary["upcoming_posts"] if p["task_id"] == "task-qp-01")
        self.assertEqual(post["profile_name"], "Queue Prof")

    # 17. queue mostra channel
    def test_17_queue_shows_channel(self):
        prof = profile_manager.create_profile("Queue Ch Prof", is_active=True, db_path=self.db_path)
        ch = profile_manager.create_channel(prof["id"], "youtube", "Canal Estilizado", is_enabled=True, db_path=self.db_path)
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at, profile_id, channel_id)
                VALUES ('task-qc-01', 'youtube', '2026-09-18T14:00:00Z', 'planned', '2026-09-18T12:00:00Z', ?, ?);
                """,
                (prof["id"], ch["channel_id"]),
            )
        summary = operator_console.get_scheduler_queue_summary(db_path=self.db_path)
        post = next(p for p in summary["upcoming_posts"] if p["task_id"] == "task-qc-01")
        self.assertEqual(post["channel_name"], "Canal Estilizado")

    # 18. filtros profile/platform/status
    def test_18_filters_profile_platform_status(self):
        prof_a = profile_manager.create_profile("Prof Alfa", is_active=True, db_path=self.db_path)
        prof_b = profile_manager.create_profile("Prof Beta", is_active=True, db_path=self.db_path)
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at, profile_id)
                VALUES
                ('t-1', 'youtube', '2026-09-18T14:00:00Z', 'planned', '2026-09-18T12:00:00Z', ?),
                ('t-2', 'tiktok', '2026-09-18T15:00:00Z', 'ready', '2026-09-18T12:00:00Z', ?);
                """,
                (prof_a["id"], prof_b["id"]),
            )
        summary = operator_console.get_scheduler_queue_summary(db_path=self.db_path)
        posts = summary["upcoming_posts"]

        # Filtro Profile
        filtered_p = [p for p in posts if p.get("profile_name") == "Prof Alfa"]
        self.assertEqual(len(filtered_p), 1)
        self.assertEqual(filtered_p[0]["task_id"], "t-1")

        # Filtro Platform
        filtered_plat = [p for p in posts if p.get("platform") == "tiktok"]
        self.assertEqual(len(filtered_plat), 1)
        self.assertEqual(filtered_plat[0]["task_id"], "t-2")

        # Filtro Status
        filtered_st = [p for p in posts if p.get("status") == "ready"]
        self.assertEqual(len(filtered_st), 1)
        self.assertEqual(filtered_st[0]["task_id"], "t-2")

    # 19. task mantém profile original
    def test_19_task_maintains_original_profile(self):
        prof_x = profile_manager.create_profile("Profile X", is_active=True, db_path=self.db_path)
        prof_y = profile_manager.create_profile("Profile Y", is_active=True, db_path=self.db_path)
        task_id = "task-origin-01"
        profile_manager.set_task_profile_id(task_id, prof_x["id"], db_path=self.db_path)

        # Troca operador para Y
        profile_manager.set_active_profile(prof_y["id"], db_path=self.db_path)

        resolved_pid = profile_manager.get_task_profile_id(task_id, db_path=self.db_path)
        self.assertEqual(resolved_pid, prof_x["id"])

    # 20. Scheduler mantém routing correto
    def test_20_scheduler_maintains_correct_routing(self):
        prof_x = profile_manager.create_profile("Routing Prof", is_active=True, db_path=self.db_path)
        ch = profile_manager.create_channel(prof_x["id"], "youtube", "Routing YT", is_enabled=True, db_path=self.db_path)
        task_id = "task-sched-route-01"
        profile_manager.set_task_profile_id(task_id, prof_x["id"], db_path=self.db_path)

        fake_task = {
            "task_id": task_id,
            "state": const.TASK_STATE_COMPLETE,
            "planned_platforms": ["youtube"],
            "subject": "Routing Video",
            "video_file": self._create_task_files(task_id),
        }
        res = scheduler.plan_schedule([fake_task], now=self.now, db_path=self.db_path)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["profile_id"], prof_x["id"])
        self.assertEqual(res[0]["channel_id"], ch["channel_id"])

    # 21. publication routing mantém channel correto
    def test_21_publication_routing_maintains_correct_channel(self):
        prof = profile_manager.create_profile("Pub Route Prof", is_active=True, db_path=self.db_path)
        ch = profile_manager.create_channel(
            prof["id"], "youtube", "Pub Ch", external_profile_name="uploadpost_pub", is_enabled=True, db_path=self.db_path
        )
        task_id = "task-pub-route-01"
        profile_manager.set_task_profile_id(task_id, prof["id"], db_path=self.db_path)
        self._create_task_files(task_id)

        with patch("app.utils.utils.task_dir", return_value=self.task_base_dir), \
             patch.object(upload_post, "cross_post_video", return_value={"success": True}) as mock_cross:
            success, err = task_module.publish_task(task_id, platforms=["youtube"], synchronous=True, db_path=self.db_path)
            self.assertTrue(success, f"Falha na publicação: {err}")
            self.assertEqual(mock_cross.call_args[1].get("external_profile_name"), "uploadpost_pub")

    # 22. disabled profile bloqueia
    def test_22_disabled_profile_blocks(self):
        prof = profile_manager.create_profile("Dis Prof Sched", is_active=False, db_path=self.db_path)
        profile_manager.create_channel(prof["id"], "youtube", "YT Dis", is_enabled=True, db_path=self.db_path)
        task_id = "task-dis-prof-01"
        profile_manager.set_task_profile_id(task_id, prof["id"], db_path=self.db_path)

        fake_task = {
            "task_id": task_id,
            "state": const.TASK_STATE_COMPLETE,
            "planned_platforms": ["youtube"],
            "subject": "Dis Video",
            "video_file": self._create_task_files(task_id),
        }
        res = scheduler.plan_schedule([fake_task], now=self.now, db_path=self.db_path)
        self.assertEqual(len(res), 0)

    # 23. disabled channel bloqueia
    def test_23_disabled_channel_blocks(self):
        prof = profile_manager.create_profile("Dis Ch Sched", is_active=True, db_path=self.db_path)
        ch = profile_manager.create_channel(prof["id"], "youtube", "YT Inativo", is_enabled=False, db_path=self.db_path)
        task_id = "task-dis-ch-01"
        profile_manager.set_task_profile_id(task_id, prof["id"], db_path=self.db_path)

        channels = profile_manager.resolve_task_channels(task_id, platforms=["youtube"], db_path=self.db_path)
        self.assertEqual(len(channels), 0)

    # 24. technical cap continua global
    def test_24_technical_cap_remains_global(self):
        scheduler.save_settings({"youtube_limit_24h": 2}, db_path=self.db_path)
        prof1 = profile_manager.create_profile("Prof 1", growth_mode="scale", is_active=True, db_path=self.db_path)
        prof2 = profile_manager.create_profile("Prof 2", growth_mode="scale", is_active=True, db_path=self.db_path)

        info1 = scheduler.get_platform_rate_limits("youtube", db_path=self.db_path, now=self.now, profile_id=prof1["id"])
        info2 = scheduler.get_platform_rate_limits("youtube", db_path=self.db_path, now=self.now, profile_id=prof2["id"])
        self.assertEqual(info1["effective_limit"], 2)
        self.assertEqual(info2["effective_limit"], 2)

    # 25. worker único preservado
    def test_25_single_worker_preserved(self):
        from app.services import scheduler
        with operator_console._instance_state_lock:
            operator_console._current_role = operator_console.ROLE_SECONDARY_VIEW_ONLY

        scheduler.start_scheduler_worker(interval_seconds=1)
        self.assertIsNone(scheduler._worker_thread)

    # 26. PRIMARY guard preservado
    def test_26_primary_guard_preserved(self):
        with operator_console._instance_state_lock:
            operator_console._current_role = operator_console.ROLE_SECONDARY_VIEW_ONLY

        with self.assertRaises((PermissionError, RuntimeError)):
            profile_manager.create_profile("Guarded", db_path=self.db_path)

    # 27. fluxo legacy preservado
    def test_27_legacy_flow_preserved(self):
        # Task sem task_profiles
        channels = profile_manager.resolve_task_channels("task-sem-registro", platforms=["youtube"], db_path=self.db_path)
        # Default profile canais padrão estão ativos
        self.assertGreaterEqual(len(channels), 1)
        self.assertEqual(channels[0]["profile_id"], "default")

    # 28. active profile fallback preservado
    def test_28_active_profile_fallback_preserved(self):
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute("DELETE FROM autopilot_settings WHERE key = 'active_profile_id';")
        act = profile_manager.get_active_profile(db_path=self.db_path)
        self.assertEqual(act["id"], "default")

    # 29. nenhum delete físico
    def test_29_no_physical_delete(self):
        self.assertFalse(hasattr(profile_manager, "delete_profile"))
        self.assertFalse(hasattr(profile_manager, "delete_channel"))

    # 30. schema permanece aditivo/idempotente
    def test_30_schema_remains_additive_and_idempotent(self):
        profile_manager.init_profile_db(self.db_path)
        scheduler.init_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        scheduler.init_db(self.db_path)

        with scheduler.get_connection(self.db_path) as conn:
            sp_cols = [c["name"] for c in conn.execute("PRAGMA table_info(scheduled_posts);").fetchall()]
            pe_cols = [c["name"] for c in conn.execute("PRAGMA table_info(publication_events);").fetchall()]
            self.assertIn("profile_id", sp_cols)
            self.assertIn("channel_id", sp_cols)
            self.assertIn("profile_id", pe_cols)
            self.assertIn("channel_id", pe_cols)


if __name__ == "__main__":
    unittest.main()
