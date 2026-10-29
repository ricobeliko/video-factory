"""Testes de Criação e Onboarding de Canal na API V2 (Item 2.7).

Valida:
1. Criação com sucesso de canal editorial (born disabled: autonomous_enabled=False, growth_mode=WARMUP, target_stock=3);
2. Rejeição de nome duplicado com HTTP 409;
3. Rejeição de slug duplicado com HTTP 409;
4. Rejeição de campos inválidos (nome vazio, nicho vazio, formato inválido, voz inválida) com HTTP 400;
5. Instância não-PRIMARY bloqueada com HTTP 403 fail-closed;
6. Registro de auditoria em operational_events (CHANNEL_CREATED) sem dados sensíveis;
7. Resolução de voz canônica pt-BR segura (nunca herda voz inválida).
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import asgi
from app.config import config
from app.models import const
from app.services import autonomous_production, operator_console, profile_manager, scheduler


class TestApiV2ChannelCreation(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        self.original_ui_config = dict(config.ui)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_v2_channels.db")
        config.app["api_key"] = ""

        # Inicializa tabelas no banco temporário
        scheduler.init_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        operator_console.init_operator_db(self.db_path)
        profile_manager.ensure_default_profile(self.db_path)

        # Configurações globais padrão seguras
        config.ui["voice_name"] = "pt-BR-FranciscaNeural"

        # Patch do get_db_path para garantir isolamento absoluto
        self.patcher_db = patch("app.services.operator_console.get_db_path", return_value=self.db_path)
        self.mock_get_db = self.patcher_db.start()

        # Patch de primary instance para True por padrão
        self.patcher_primary = patch("app.services.operator_console.is_primary_instance", return_value=True)
        self.mock_is_primary = self.patcher_primary.start()

        self.client = TestClient(asgi.app)

    def tearDown(self):
        self.patcher_primary.stop()
        self.patcher_db.stop()
        config.app.clear()
        config.app.update(self.original_app_config)
        config.ui.clear()
        config.ui.update(self.original_ui_config)
        self.temp_dir.cleanup()

    def test_create_channel_success_born_disabled(self):
        """1. Criação com sucesso de canal: nasce desligado, WARMUP e meta de estoque 3."""
        payload = {
            "name": "Canal Mistérios Antigos",
            "niche": "historia",
            "video_format": "traditional",
            "topic_brief": "Mistérios e civilizações perdidas da antiguidade.",
            "language": "pt-BR",
        }
        res = self.client.post("/api/v2/channels", json=payload)
        self.assertEqual(res.status_code, 201)

        body = res.json()
        data = body.get("data", {})
        new_pid = data.get("profile_id")
        self.assertTrue(new_pid.startswith("profile-"))
        self.assertEqual(data.get("name"), "Canal Mistérios Antigos")
        self.assertEqual(data.get("niche"), "historia")
        self.assertEqual(data.get("video_format"), "traditional")
        self.assertEqual(str(data.get("growth_mode")).upper(), "WARMUP")
        self.assertEqual(data.get("autonomous_enabled"), False)
        self.assertEqual(data.get("target_ready_stock"), 3)

        # Verifica persistência no SQLite isolado
        with profile_manager.get_connection(self.db_path) as conn:
            # Perfil
            p_row = conn.execute("SELECT * FROM content_profiles WHERE id = ?", (new_pid,)).fetchone()
            self.assertIsNotNone(p_row)
            self.assertEqual(p_row["name"], "Canal Mistérios Antigos")
            self.assertEqual(str(p_row["growth_mode"]).lower(), const.GROWTH_MODE_WARMUP.lower())

            # Autopilot
            ap_row = conn.execute(
                "SELECT value FROM autopilot_settings WHERE key = ?",
                (f"autonomous_mode_enabled:{new_pid}",),
            ).fetchone()
            self.assertIsNotNone(ap_row)
            self.assertEqual(ap_row["value"], "False")

            stock_row = conn.execute(
                "SELECT value FROM autopilot_settings WHERE key = ?",
                (f"autonomous_target_ready_stock:{new_pid}",),
            ).fetchone()
            self.assertIsNotNone(stock_row)
            self.assertEqual(stock_row["value"], "3")

            # Publishing channel fallback (somente estoque, desativado)
            ch_row = conn.execute(
                "SELECT * FROM publishing_channels WHERE profile_id = ?",
                (new_pid,),
            ).fetchone()
            self.assertIsNotNone(ch_row)
            self.assertEqual(ch_row["is_enabled"], 0)

    def test_duplicate_name_rejected_409(self):
        """2. Tentativa de cadastrar canal com nome duplicado retorna 409 Conflict."""
        payload = {
            "name": "Canal Curiosidades Dev",
            "niche": "tecnologia",
            "video_format": "traditional",
        }
        res1 = self.client.post("/api/v2/channels", json=payload)
        self.assertEqual(res1.status_code, 201)

        # Segunda tentativa com o mesmo nome (mesmo com case diferente)
        payload_dup = {
            "name": "  canal curiosidades dev  ",
            "niche": "programacao",
            "video_format": "traditional",
        }
        res2 = self.client.post("/api/v2/channels", json=payload_dup)
        self.assertEqual(res2.status_code, 409)
        self.assertIn("Já existe um canal cadastrado com o nome", res2.json().get("detail", res2.json().get("message", "")))

    def test_duplicate_slug_rejected_409(self):
        """3. Tentativa de cadastrar canal com slug duplicado retorna 409 Conflict."""
        payload1 = {
            "name": "Canal Alpha",
            "niche": "alpha",
            "slug": "canal-alpha-unico",
        }
        res1 = self.client.post("/api/v2/channels", json=payload1)
        self.assertEqual(res1.status_code, 201)

        payload2 = {
            "name": "Canal Alpha Diferente",
            "niche": "beta",
            "slug": "canal-alpha-unico",
        }
        res2 = self.client.post("/api/v2/channels", json=payload2)
        self.assertEqual(res2.status_code, 409)
        self.assertIn("slug", res2.json().get("detail", res2.json().get("message", "")).lower())

    def test_invalid_fields_rejected_400(self):
        """4. Campos vazios ou inválidos são rejeitados com HTTP 400."""
        # Nome vazio
        res = self.client.post("/api/v2/channels", json={"name": "   ", "niche": "tech"})
        self.assertEqual(res.status_code, 400)

        # Nicho vazio
        res = self.client.post("/api/v2/channels", json={"name": "Canal Teste", "niche": "   "})
        self.assertEqual(res.status_code, 400)

        # Formato de vídeo inválido
        res = self.client.post(
            "/api/v2/channels",
            json={"name": "Canal Teste", "niche": "tech", "video_format": "documentary_long"},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("Formato de vídeo", res.json().get("detail", res.json().get("message", "")))

        # Voz inválida
        res = self.client.post(
            "/api/v2/channels",
            json={"name": "Canal Teste", "niche": "tech", "voice_name": "zh-CN-XiaoxiaoNeural"},
        )
        self.assertEqual(res.status_code, 400)
        detail_msg = res.json().get("detail", res.json().get("message", "")).lower()
        self.assertTrue("inválida" in detail_msg or "homologada" in detail_msg)

    def test_secondary_instance_blocked_403(self):
        """5. Instância não-PRIMARY é bloqueada com HTTP 403 fail-closed."""
        with patch("app.services.operator_console.require_primary_instance", side_effect=PermissionError("Secondary instance view-only")):
            res = self.client.post(
                "/api/v2/channels",
                json={"name": "Canal Secundário", "niche": "geral"},
            )
            self.assertEqual(res.status_code, 403)
            self.assertIn("only primary instance", res.json().get("detail", res.json().get("message", "")).lower())

    def test_audit_event_logged(self):
        """6. Registro de auditoria CHANNEL_CREATED é gravado em operational_events sem dados sensíveis."""
        payload = {
            "name": "Canal Auditado",
            "niche": "auditoria",
            "video_format": "quiz_paper",
            "topic_brief": "Quiz sobre normas de segurança",
        }
        res = self.client.post("/api/v2/channels", json=payload)
        self.assertEqual(res.status_code, 201)
        new_pid = res.json()["data"]["profile_id"]

        with profile_manager.get_connection(self.db_path) as conn:
            event = conn.execute(
                "SELECT * FROM operational_events WHERE event_type = 'CHANNEL_CREATED' ORDER BY id DESC LIMIT 1;"
            ).fetchone()
            self.assertIsNotNone(event)
            self.assertEqual(event["component"], "channels")
            self.assertEqual(event["severity"], "INFO")
            self.assertIn("Canal Auditado", event["message"])
            metadata_str = event["metadata_json"]
            self.assertIn(new_pid, metadata_str)
            self.assertIn("quiz_paper", metadata_str)
            # Garante que chaves sensíveis não vazaram no log de auditoria
            for sensitive_word in ("api_key", "password", "token", "secret"):
                self.assertNotIn(sensitive_word, metadata_str.lower())

    def test_voice_inheritance_and_pt_br_safety(self):
        """7. Canal herda voz canônica pt-BR e nunca nasce com voz inválida."""
        # Caso A: Sem voz especificada -> herda precedência canônica
        res_a = self.client.post(
            "/api/v2/channels",
            json={"name": "Canal Voz Padrão", "niche": "geral"},
        )
        self.assertEqual(res_a.status_code, 201)
        data_a = res_a.json()["data"]
        self.assertIsNone(data_a.get("voice_name"))
        self.assertEqual(data_a.get("voice_declaration"), "inherited")
        effective_v = data_a.get("effective_voice", {}).get("voice_name", {})
        self.assertTrue(autonomous_production.is_valid_pt_br_voice(effective_v.get("value")))

        # Caso B: Com voz homologada explícita -> salva override
        res_b = self.client.post(
            "/api/v2/channels",
            json={"name": "Canal Voz Thalita", "niche": "geral", "voice_name": "pt-BR-ThalitaMultilingualNeural"},
        )
        self.assertEqual(res_b.status_code, 201)
        data_b = res_b.json()["data"]
        self.assertEqual(data_b.get("voice_name"), "pt-BR-ThalitaMultilingualNeural")
        self.assertEqual(data_b.get("voice_declaration"), "override")
        effective_b = data_b.get("effective_voice", {}).get("voice_name", {})
        self.assertEqual(effective_b.get("value"), "pt-BR-ThalitaMultilingualNeural")
        self.assertEqual(effective_b.get("source"), "channel")


if __name__ == "__main__":
    unittest.main()
