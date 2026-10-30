"""Testes dos Controles de Agendamento e Publicação da API V2.

Valida:
1. PATCH /api/v2/scheduler/settings com dados válidos altera e persiste;
2. PATCH com campos não permitidos -> 400;
3. PATCH com valores não-booleanos -> 400;
4. PATCH sem campos -> 400;
5. PATCH em instância NÃO-PRIMARY -> 403;
6. POST /api/v2/scheduler/run-cycle em PRIMARY chama scheduler.run_scheduler_cycle e responde com resultado canônico;
7. POST /api/v2/scheduler/run-cycle em NÃO-PRIMARY -> 403;
8. POST /api/v2/scheduler/plan em PRIMARY chama scheduler.plan_schedule e responde com contagem;
9. POST /api/v2/scheduler/plan em NÃO-PRIMARY -> 403;
10. Auditoria: verifica que operator_events registra as ações operacionais.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import asgi
from app.config import config
from app.services import operator_console, scheduler

config.app['api_key'] = ''


class TestApiV2SchedulerControls(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_v2_scheduler.db")
        config.app["api_key"] = ""

        # Inicializa tabelas
        scheduler.init_db(self.db_path)
        operator_console.init_operator_db(self.db_path)
        operator_console.reset_instance_for_testing()
        operator_console.ensure_instance_initialized(db_path=self.db_path)

        self.client = TestClient(asgi.app)

    def tearDown(self):
        operator_console.reset_instance_for_testing()
        config.app.clear()
        config.app.update(self.original_app_config)
        self.temp_dir.cleanup()

    def test_patch_scheduler_settings_valid_persists_and_audits(self):
        """1. PATCH /api/v2/scheduler/settings com dados válidos altera, persiste e gera auditoria."""
        with patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.is_primary_instance", return_value=True):

            payload = {
                "auto_publish_enabled": True,
                "scheduler_enabled": True,
                "dry_run": False,
            }
            res = self.client.patch("/api/v2/scheduler/settings", json=payload)
            self.assertEqual(res.status_code, 200, res.text)
            data = res.json().get("data", {})
            self.assertTrue(data.get("auto_publish_enabled"))
            self.assertTrue(data.get("scheduler_enabled"))
            self.assertFalse(data.get("dry_run"))

            # Verifica persistência no banco
            current = scheduler.get_all_settings(self.db_path)
            self.assertTrue(current.get("auto_publish_enabled"))
            self.assertTrue(current.get("scheduler_enabled"))
            self.assertFalse(current.get("dry_run"))

            # Verifica registro de auditoria em operational_events
            events = operator_console.get_operational_events(limit=20, db_path=self.db_path)
            sched_events = [e for e in events if e.get("event_type") == "SCHEDULER_SETTINGS_UPDATED"]
            self.assertTrue(len(sched_events) >= 1, "Evento de auditoria SCHEDULER_SETTINGS_UPDATED não encontrado")
            updated_fields = [e.get("metadata", {}).get("field") for e in sched_events]
            self.assertIn("auto_publish_enabled", updated_fields)
            self.assertIn("scheduler_enabled", updated_fields)
            self.assertIn("dry_run", updated_fields)

    def test_patch_scheduler_settings_extra_fields_returns_400(self):
        """2. PATCH com campos não permitidos -> 400."""
        with patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.is_primary_instance", return_value=True):

            payload = {
                "auto_publish_enabled": True,
                "unauthorized_field": "danger",
            }
            res = self.client.patch("/api/v2/scheduler/settings", json=payload)
            self.assertEqual(res.status_code, 400, res.text)

    def test_patch_scheduler_settings_non_boolean_returns_400(self):
        """3. PATCH com valores não-booleanos -> 400."""
        with patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.is_primary_instance", return_value=True):

            payload = {
                "auto_publish_enabled": "yes",  # String inválida onde espera bool estrito
            }
            res = self.client.patch("/api/v2/scheduler/settings", json=payload)
            self.assertEqual(res.status_code, 400, res.text)

    def test_patch_scheduler_settings_empty_payload_returns_400(self):
        """4. PATCH sem campos -> 400."""
        with patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.is_primary_instance", return_value=True):

            res = self.client.patch("/api/v2/scheduler/settings", json={})
            self.assertEqual(res.status_code, 400, res.text)

    def test_patch_scheduler_settings_non_primary_returns_403(self):
        """5. PATCH em instância NÃO-PRIMARY -> 403."""
        with patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.is_primary_instance", return_value=False):

            payload = {"dry_run": True}
            res = self.client.patch("/api/v2/scheduler/settings", json=payload)
            self.assertEqual(res.status_code, 403, res.text)

    def test_post_run_cycle_primary_calls_scheduler_and_audits(self):
        """6. POST /api/v2/scheduler/run-cycle em PRIMARY chama run_scheduler_cycle e gera auditoria."""
        mock_result = {
            "status": "published",
            "task_id": "test_task_123",
            "platform": "youtube",
            "post_id": 42,
        }
        with patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.is_primary_instance", return_value=True), \
             patch("app.services.scheduler.run_scheduler_cycle", return_value=mock_result) as mock_cycle:

            res = self.client.post("/api/v2/scheduler/run-cycle")
            self.assertEqual(res.status_code, 200, res.text)
            mock_cycle.assert_called_once()
            data = res.json().get("data", {})
            self.assertEqual(data.get("status"), "published")
            self.assertEqual(data.get("task_id"), "test_task_123")

            # Verifica auditoria
            events = operator_console.get_operational_events(limit=20, db_path=self.db_path)
            cycle_events = [e for e in events if e.get("event_type") == "SCHEDULER_CYCLE_TRIGGERED"]
            self.assertTrue(len(cycle_events) >= 1)

    def test_post_run_cycle_non_primary_returns_403(self):
        """7. POST /api/v2/scheduler/run-cycle em NÃO-PRIMARY -> 403."""
        with patch("app.services.operator_console.is_primary_instance", return_value=False):
            res = self.client.post("/api/v2/scheduler/run-cycle")
            self.assertEqual(res.status_code, 403, res.text)

    def test_post_plan_primary_calls_plan_and_audits(self):
        """8. POST /api/v2/scheduler/plan em PRIMARY chama scheduler.plan_schedule e gera auditoria."""
        with patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.is_primary_instance", return_value=True), \
             patch("app.services.scheduler.plan_schedule", return_value=3) as mock_plan:

            res = self.client.post("/api/v2/scheduler/plan")
            self.assertEqual(res.status_code, 200, res.text)
            mock_plan.assert_called_once()
            data = res.json().get("data", {})
            self.assertEqual(data.get("planned_count"), 3)
            self.assertNotIn("adjusted_count", data)

            # Verifica auditoria
            events = operator_console.get_operational_events(limit=20, db_path=self.db_path)
            plan_events = [e for e in events if e.get("event_type") == "SCHEDULE_PLANNED"]
            self.assertTrue(len(plan_events) >= 1)
            metadata = plan_events[0].get("metadata", {})
            self.assertEqual(metadata.get("planned_count"), 3)
            self.assertNotIn("adjusted_count", metadata)

    def test_post_plan_non_primary_returns_403(self):
        """9. POST /api/v2/scheduler/plan em NÃO-PRIMARY -> 403."""
        with patch("app.services.operator_console.is_primary_instance", return_value=False):
            res = self.client.post("/api/v2/scheduler/plan")
            self.assertEqual(res.status_code, 403, res.text)

    def test_init_db_guards_recreate_schema_when_db_deleted_in_live_process(self):
        """10. Apagar o arquivo .db com o processo vivo e chamar init/API recria o schema nas 3 camadas."""
        from app.services import profile_manager
        live_db = os.path.join(self.temp_dir.name, "live_deleted.db")

        # Inicializa as 3 camadas pela primeira vez (entra nos conjuntos _INITIALIZED_*_DBS)
        scheduler.init_db(live_db)
        profile_manager.init_profile_db(live_db)
        operator_console.init_operator_db(live_db)
        self.assertTrue(os.path.isfile(live_db))

        # Apaga o arquivo .db com o processo vivo (sem limpar os conjuntos em memória)
        for ext in ("", "-wal", "-shm"):
            p_ext = live_db + ext
            if os.path.exists(p_ext):
                os.remove(p_ext)
        self.assertFalse(os.path.isfile(live_db))

        # 1) scheduler: deve recriar autopilot_settings e scheduled_posts sem erro
        scheduler.set_setting("auto_publish_enabled", "true", db_path=live_db)
        self.assertTrue(os.path.isfile(live_db))
        self.assertEqual(scheduler.get_setting("auto_publish_enabled", db_path=live_db), "true")

        # Apaga novamente para provar profile_manager isoladamente
        for ext in ("", "-wal", "-shm"):
            p_ext = live_db + ext
            if os.path.exists(p_ext):
                os.remove(p_ext)
        self.assertFalse(os.path.isfile(live_db))

        # 2) profile_manager: deve recriar content_profiles e publishing_channels sem erro
        profile_manager.ensure_default_profile(live_db)
        profs = profile_manager.list_profiles(db_path=live_db)
        self.assertTrue(len(profs) >= 1)

        # Apaga novamente para provar operator_console e API V2
        for ext in ("", "-wal", "-shm"):
            p_ext = live_db + ext
            if os.path.exists(p_ext):
                os.remove(p_ext)
        self.assertFalse(os.path.isfile(live_db))

        # 3) operator_console + chamada de API V2: deve recriar operational_events/instance_locks sem erro
        operator_console.log_operational_event(
            component="test",
            severity="INFO",
            event_type="DB_RECREATED",
            message="recriado",
            db_path=live_db,
        )
        evs = operator_console.get_operational_events(limit=5, db_path=live_db)
        self.assertEqual(len(evs), 1)

        with patch("app.services.scheduler.get_db_path", return_value=live_db), \
             patch("app.services.profile_manager.get_db_path", return_value=live_db), \
             patch("app.services.operator_console.get_db_path", return_value=live_db):
            res = self.client.get("/api/v2/channels/overview")
            self.assertEqual(res.status_code, 200, res.text)

    def test_growth_mode_single_source_parity_and_invalid_numeric_fallback(self):
        """11. Paridade entre get_all_settings e get_growth_mode (válidos, inválidos, ausentes, por plataforma) e fallback numérico."""
        from app.models import const

        # Caso 1: Ausentes -> default warmup em todos
        s_all = scheduler.get_all_settings(self.db_path)
        self.assertEqual(s_all["growth_mode"], scheduler.get_growth_mode(db_path=self.db_path))
        self.assertEqual(s_all["growth_mode_youtube"], scheduler.get_growth_mode("youtube", db_path=self.db_path))
        self.assertEqual(s_all["growth_mode_tiktok"], scheduler.get_growth_mode("tiktok", db_path=self.db_path))
        self.assertEqual(s_all["growth_mode"], const.DEFAULT_GROWTH_MODE)

        # Caso 2: Global válido ('scale'), youtube específico ('warmup'), tiktok ausente (herda 'scale')
        scheduler.set_setting("growth_mode", "SCALE", db_path=self.db_path)
        scheduler.set_setting("growth_mode_youtube", "warmup", db_path=self.db_path)
        s_all = scheduler.get_all_settings(self.db_path)
        self.assertEqual(s_all["growth_mode"], "scale")
        self.assertEqual(s_all["growth_mode_youtube"], "warmup")
        self.assertEqual(s_all["growth_mode_tiktok"], "scale")
        self.assertEqual(s_all["growth_mode"], scheduler.get_growth_mode(db_path=self.db_path))
        self.assertEqual(s_all["growth_mode_youtube"], scheduler.get_growth_mode("youtube", db_path=self.db_path))
        self.assertEqual(s_all["growth_mode_tiktok"], scheduler.get_growth_mode("tiktok", db_path=self.db_path))

        # Caso 3: Valor inválido por plataforma -> cai para o global; valor global inválido -> cai para DEFAULT_GROWTH_MODE
        scheduler.set_setting("growth_mode_youtube", "MODO_INEXISTENTE", db_path=self.db_path)
        scheduler.set_setting("growth_mode_tiktok", "normal", db_path=self.db_path)
        s_all = scheduler.get_all_settings(self.db_path)
        self.assertEqual(s_all["growth_mode_youtube"], "scale")
        self.assertEqual(s_all["growth_mode_tiktok"], "normal")
        self.assertEqual(s_all["growth_mode_youtube"], scheduler.get_growth_mode("youtube", db_path=self.db_path))
        self.assertEqual(s_all["growth_mode_tiktok"], scheduler.get_growth_mode("tiktok", db_path=self.db_path))

        scheduler.set_setting("growth_mode", "INVALID_GLOBAL", db_path=self.db_path)
        s_all = scheduler.get_all_settings(self.db_path)
        self.assertEqual(s_all["growth_mode"], const.DEFAULT_GROWTH_MODE)
        self.assertEqual(s_all["growth_mode_youtube"], const.DEFAULT_GROWTH_MODE)
        self.assertEqual(s_all["growth_mode"], scheduler.get_growth_mode(db_path=self.db_path))
        self.assertEqual(s_all["growth_mode_youtube"], scheduler.get_growth_mode("youtube", db_path=self.db_path))

        # Caso 4: Valor numérico inválido em estoque/limites cai no default sem levantar ValueError
        scheduler.set_setting("tiktok_limit_24h", "abc_invalido", db_path=self.db_path)
        scheduler.set_setting("youtube_limit_24h", "", db_path=self.db_path)
        scheduler.set_setting("estoque_desejado", "nao_numero", db_path=self.db_path)
        s_all = scheduler.get_all_settings(self.db_path)
        self.assertEqual(s_all["tiktok_limit_24h"], scheduler.DEFAULT_TIKTOK_LIMIT)
        self.assertEqual(s_all["youtube_limit_24h"], scheduler.DEFAULT_YOUTUBE_LIMIT)
        self.assertEqual(s_all["estoque_desejado"], scheduler.DEFAULT_DESIRED_STOCK)

    def test_render_pass_cache_invalidation_on_write_and_disabled_outside_scope(self):
        """12. (a) Cache por requisição invalida após escrita na mesma requisição; (b) fora de render_pass_scope nada é cacheado."""
        from app.services import profile_manager

        profile_manager.init_profile_db(self.db_path)
        profile_manager.ensure_default_profile(self.db_path)

        # (b) Fora de render_pass_scope: get_render_pass_cache() é None (nada é cacheado)
        self.assertIsNone(operator_console.get_render_pass_cache())
        scheduler.set_setting("dry_run", "true", db_path=self.db_path)
        self.assertEqual(scheduler.get_setting("dry_run", db_path=self.db_path), "true")
        self.assertIsNone(operator_console.get_render_pass_cache())

        # (a) Dentro de render_pass_scope:
        with operator_console.render_pass_scope() as rp_cache:
            self.assertIsInstance(rp_cache, dict)

            # 1. get_setting popula cache; set_setting invalida; próximo get_setting devolve valor novo
            v1 = scheduler.get_setting("dry_run", db_path=self.db_path)
            self.assertEqual(v1, "true")
            self.assertTrue(len(rp_cache) > 0)

            scheduler.set_setting("dry_run", "false", db_path=self.db_path)
            self.assertEqual(len(rp_cache), 0, "Cache deve ser limpo imediatamente após set_setting")
            v2 = scheduler.get_setting("dry_run", db_path=self.db_path)
            self.assertEqual(v2, "false")

            # 2. list_profiles popula cache; create_profile invalida; próximo list_profiles traz o novo perfil
            p_before = profile_manager.list_profiles(db_path=self.db_path)
            ids_before = {p["id"] for p in p_before}
            new_prof = profile_manager.create_profile(
                name="Canal Cache Test",
                slug="canal-cache-test",
                niche="teste",
                db_path=self.db_path,
            )
            p_after = profile_manager.list_profiles(db_path=self.db_path)
            ids_after = {p["id"] for p in p_after}
            self.assertIn(new_prof["id"], ids_after - ids_before)

            # 3. list_channels popula cache; update_channel invalida; próximo list_channels reflete alteração
            ch = profile_manager.create_channel(
                profile_id=new_prof["id"],
                platform="youtube",
                display_name="YT Original",
                external_account_id="UCcachetest123456789012",
                is_enabled=True,
                db_path=self.db_path,
            )
            chans_1 = profile_manager.list_channels(profile_id=new_prof["id"], db_path=self.db_path)
            self.assertEqual(chans_1[0]["display_name"], "YT Original")

            profile_manager.update_channel(
                channel_id=ch["id"],
                display_name="YT Atualizado",
                db_path=self.db_path,
            )
            chans_2 = profile_manager.list_channels(profile_id=new_prof["id"], db_path=self.db_path)
            self.assertEqual(chans_2[0]["display_name"], "YT Atualizado")

        # Ao sair do with, o cache volta a ser None
        self.assertIsNone(operator_console.get_render_pass_cache())

    def test_ttl_caches_provider_health_and_publishing_accounts(self):
        """13. (c) TTL do cache de saúde dos provedores (15s) e de publishing/accounts (60s): hit, expiração e force=true."""
        from app.controllers.v2 import operations as v2_ops

        operator_console.clear_provider_health_cache()
        v2_ops.clear_publishing_accounts_cache()

        # 1. Publishing Accounts Cache (TTL 60s)
        fake_accounts = [{"id": "acc-1", "platform": "youtube", "username": "Canal YT"}]
        with patch("app.services.post_for_me.list_connected_publishing_accounts", return_value=fake_accounts) as mock_pfm:
            # 1ª chamada: miss -> chama post_for_me (2 plataformas: youtube + tiktok)
            r1 = self.client.get("/api/v2/publishing/accounts")
            self.assertEqual(r1.status_code, 200)
            self.assertEqual(mock_pfm.call_count, 2)

            # 2ª chamada dentro do TTL: hit -> não chama post_for_me novamente
            r2 = self.client.get("/api/v2/publishing/accounts")
            self.assertEqual(r2.status_code, 200)
            self.assertEqual(mock_pfm.call_count, 2)

            # 3ª chamada com force=true: ignora cache -> chama post_for_me novamente
            r3 = self.client.get("/api/v2/publishing/accounts?force=true")
            self.assertEqual(r3.status_code, 200)
            self.assertEqual(mock_pfm.call_count, 4)

            # 4ª chamada após expirar TTL (>60s): miss -> chama post_for_me novamente
            for k in list(v2_ops._PUBLISHING_ACCOUNTS_CACHE.keys()):
                ts, val = v2_ops._PUBLISHING_ACCOUNTS_CACHE[k]
                v2_ops._PUBLISHING_ACCOUNTS_CACHE[k] = (ts - 61.0, val)
            r4 = self.client.get("/api/v2/publishing/accounts")
            self.assertEqual(r4.status_code, 200)
            self.assertEqual(mock_pfm.call_count, 6)

        # 2. Provider Health Cache (TTL 15s)
        with patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.utils.utils.check_ffmpeg_ready", return_value=(True, "ffmpeg ok")) as mock_ff:
            operator_console.clear_provider_health_cache()

            # 1ª chamada: miss -> executa check
            h1 = self.client.get("/api/v2/providers/health")
            self.assertEqual(h1.status_code, 200)
            c1 = mock_ff.call_count
            self.assertGreaterEqual(c1, 1)

            # 2ª chamada dentro do TTL (15s): hit -> não executa check novamente
            h2 = self.client.get("/api/v2/providers/health")
            self.assertEqual(h2.status_code, 200)
            self.assertEqual(mock_ff.call_count, c1)

            # 3ª chamada com force=true: bypassa cache -> executa check
            h3 = self.client.get("/api/v2/providers/health?force=true")
            self.assertEqual(h3.status_code, 200)
            c3 = mock_ff.call_count
            self.assertGreater(c3, c1)

            # 4ª chamada após expirar TTL (>15s): miss -> executa check
            operator_console._PROVIDER_HEALTH_CACHE['timestamp'] -= 16.0
            h4 = self.client.get("/api/v2/providers/health")
            self.assertEqual(h4.status_code, 200)
            self.assertGreater(mock_ff.call_count, c3)

