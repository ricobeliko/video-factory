"""Testes para edição de quotas e schedule de canais (SIS2).

Valida que:
- PATCH altera SOMENTE os campos enviados
- NÃO altera autonomous_enabled nem growth_mode
- Rejeita valores fora da faixa e janelas inválidas (start > end)
- Retorna 403 quando executado em nó SECONDARY
- Registra eventos operacionais em operational_events
"""

import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import asgi
from app.config import config
from app.models import const
from app.services import (
    autonomous_production,
    operator_console,
    profile_manager,
    scheduler,
)
from app.services import state as sm


class TestApiV2ChannelSettingsEdit(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_settings_edit.db")
        config.app["api_key"] = ""

        # Limpa tarefas em memória
        if hasattr(sm, 'state') and hasattr(sm.state, '_tasks'):
            sm.state._tasks.clear()

        # Inicializa tabelas
        scheduler.init_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        profile_manager.ensure_default_profile(self.db_path)
        operator_console.init_operator_db(self.db_path)

        # Garante nó primário com lock ativo
        operator_console.acquire_instance_lock(
            db_path=self.db_path,
        )

        # Cria perfil de teste (ex: canal GTA VI com autônomo desligado)
        profile_manager.create_profile(
            profile_id="profile-gtavi",
            name="Canal GTA VI",
            slug="gtavi",
            niche="Games",
            db_path=self.db_path,
        )
        # Garante autônomo desligado e modo WARMUP
        autonomous_production.set_profile_autonomous_mode_enabled("profile-gtavi", False, db_path=self.db_path)
        profile_manager.update_profile("profile-gtavi", growth_mode="warmup", db_path=self.db_path)

        # Inicia patches de db_path para o TestClient
        self.patchers = [
            patch("app.services.operator_console.get_db_path", return_value=self.db_path),
            patch("app.services.profile_manager.get_db_path", return_value=self.db_path),
            patch("app.services.scheduler.get_db_path", return_value=self.db_path),
        ]
        for p in self.patchers:
            p.start()

        self.client = TestClient(asgi.app)

    def tearDown(self):
        for p in self.patchers:
            p.stop()
        try:
            operator_console.release_instance_lock(db_path=self.db_path)
        except Exception:
            pass
        config.app.clear()
        config.app.update(self.original_app_config)
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass
        if hasattr(sm, 'state') and hasattr(sm.state, '_tasks'):
            sm.state._tasks.clear()

    def test_patch_quotas_alters_only_sent_fields_and_preserves_autonomous_and_growth_mode(self):
        """1. PATCH /quotas altera apenas os campos enviados e mantém autônomo e growth_mode intocados."""
        # Estado inicial
        initial_auto = autonomous_production.is_profile_autonomous_mode_enabled("profile-gtavi", db_path=self.db_path)
        self.assertFalse(initial_auto, "GTA VI deve começar com autônomo desligado")

        initial_quotas = profile_manager.get_profile_quotas("profile-gtavi", db_path=self.db_path)
        self.assertEqual(initial_quotas["growth_mode"], "warmup")

        # Altera SOMENTE target_ready_stock
        resp = self.client.patch(
            "/api/v2/channels/profile-gtavi/quotas",
            json={"target_ready_stock": 7},
        )
        self.assertEqual(resp.status_code, 200)

        # Verifica dados atualizados
        after_quotas = profile_manager.get_profile_quotas("profile-gtavi", db_path=self.db_path)
        self.assertEqual(after_quotas["target_ready_stock"], 7)
        # max_generations e max_attempts continuam intocados
        self.assertEqual(after_quotas["max_generations_24h"], initial_quotas["max_generations_24h"])
        self.assertEqual(after_quotas["max_attempts_24h"], initial_quotas["max_attempts_24h"])

        # Autônomo e growth_mode continuam rigorosamente os mesmos
        after_auto = autonomous_production.is_profile_autonomous_mode_enabled("profile-gtavi", db_path=self.db_path)
        self.assertFalse(after_auto, "Salvar quotas NÃO pode ligar o modo autônomo!")
        after_prof = profile_manager.get_profile("profile-gtavi", db_path=self.db_path)
        self.assertEqual(after_prof["growth_mode"], "warmup")

        # Verifica se evento operacional foi registrado no banco
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM operational_events WHERE event_type = 'PROFILE_QUOTAS_UPDATED' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["component"], "profile_manager")
            meta = json.loads(row["metadata_json"])
            self.assertEqual(meta["profile_id"], "profile-gtavi")
            self.assertEqual(meta["field"], "target_ready_stock")
            self.assertEqual(meta["new_value"], 7)
        finally:
            conn.close()

    def test_patch_schedule_alters_only_sent_fields(self):
        """2. PATCH /schedule altera apenas os campos de janela enviados e registra evento."""
        initial_sched = profile_manager.get_profile_schedule("profile-gtavi", db_path=self.db_path).model_dump()

        resp = self.client.patch(
            "/api/v2/channels/profile-gtavi/schedule",
            json={"publish_start_hour": 8, "publish_end_hour": 20, "min_interval_hours": 6},
        )
        self.assertEqual(resp.status_code, 200)

        after_sched = profile_manager.get_profile_schedule("profile-gtavi", db_path=self.db_path).model_dump()
        self.assertEqual(after_sched["publish_start_hour"], 8)
        self.assertEqual(after_sched["publish_end_hour"], 20)
        self.assertEqual(after_sched["min_interval_hours"], 6)
        # timezone não enviado permanece o mesmo
        self.assertEqual(after_sched["timezone"], initial_sched["timezone"])

        # Verifica evento registrado para schedule
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM operational_events WHERE event_type = 'PROFILE_SCHEDULE_UPDATED' ORDER BY id ASC"
            ).fetchall()
            self.assertGreaterEqual(len(rows), 1)
            fields_logged = {json.loads(r["metadata_json"])["field"] for r in rows}
            self.assertIn("publish_start_hour", fields_logged)
            self.assertIn("publish_end_hour", fields_logged)
        finally:
            conn.close()

    def test_posts_per_day_syncs_between_quotas_and_schedule(self):
        """3. Alteração de posts_per_day em quotas sincroniza automaticamente com schedule."""
        resp = self.client.patch(
            "/api/v2/channels/profile-gtavi/quotas",
            json={"posts_per_day": 3},
        )
        self.assertEqual(resp.status_code, 200)

        quotas = profile_manager.get_profile_quotas("profile-gtavi", db_path=self.db_path)
        self.assertEqual(quotas["posts_per_day"], 3)

        sched = profile_manager.get_profile_schedule("profile-gtavi", db_path=self.db_path).model_dump()
        self.assertEqual(sched["posts_per_day"], 3)

    def test_rejects_out_of_range_and_invalid_window(self):
        """4. Rejeita valores fora da faixa permitida e janela onde end < start."""
        # target_ready_stock < 1 (espera 400 ou 422 de validação)
        resp_low = self.client.patch(
            "/api/v2/channels/profile-gtavi/quotas",
            json={"target_ready_stock": 0},
        )
        self.assertIn(resp_low.status_code, (400, 422))

        # target_ready_stock > 10
        resp_high = self.client.patch(
            "/api/v2/channels/profile-gtavi/quotas",
            json={"target_ready_stock": 15},
        )
        self.assertIn(resp_high.status_code, (400, 422))

        # publish_start_hour > 23
        resp_hr = self.client.patch(
            "/api/v2/channels/profile-gtavi/schedule",
            json={"publish_start_hour": 25},
        )
        self.assertIn(resp_hr.status_code, (400, 422))

        # Janela com end < start (ex: start 18, end 10) -> regra de negócio do backend (espera 400)
        resp_inv = self.client.patch(
            "/api/v2/channels/profile-gtavi/schedule",
            json={"publish_start_hour": 18, "publish_end_hour": 10},
        )
        self.assertEqual(resp_inv.status_code, 400)
        self.assertIn("publish_end_hour não pode ser menor que publish_start_hour", resp_inv.json().get("message", ""))

    def test_secondary_instance_returns_403(self):
        """5. Instância secundária (sem lock primário) recebe 403 Forbidden."""
        with patch("app.services.operator_console.is_primary_instance", return_value=False), \
             patch("app.services.operator_console.require_primary_instance", side_effect=PermissionError("Instância em modo somente leitura")):
            resp_q = self.client.patch(
                "/api/v2/channels/profile-gtavi/quotas",
                json={"target_ready_stock": 5},
            )
            self.assertEqual(resp_q.status_code, 403)
            self.assertIn("only primary instance can update profile quotas", resp_q.json().get("message", ""))

            resp_s = self.client.patch(
                "/api/v2/channels/profile-gtavi/schedule",
                json={"publish_start_hour": 10},
            )
            self.assertEqual(resp_s.status_code, 403)
            self.assertIn("only primary instance can update profile schedule", resp_s.json().get("message", ""))

    def test_profile_not_found_returns_404(self):
        """6. Perfil inexistente retorna 404 Not Found."""
        resp = self.client.patch(
            "/api/v2/channels/perfil-inexistente-123/quotas",
            json={"target_ready_stock": 5},
        )
        self.assertEqual(resp.status_code, 404)
        self.assertIn("not found", resp.json().get("message", "").lower())
