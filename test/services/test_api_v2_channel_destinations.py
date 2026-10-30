"""Testes de Destinos de Publicação por Canal na API V2.

Valida:
1. GET /api/v2/channels/{id}/destinations: retorna lista e by_platform para youtube e tiktok;
2. PATCH /api/v2/channels/{id}/destinations: atualiza destino existente e cria novo;
3. PATCH /api/v2/channels/{id}/destinations: suporta atualização em lote (batch array);
4. Instância SECONDARY_VIEW_ONLY bloqueada com HTTP 403 fail-closed;
5. Plataforma inválida rejeitada com HTTP 400;
6. YouTube ID sem 'UC' rejeitado com HTTP 400;
7. Auditoria registrada em operational_events (CHANNEL_DESTINATION_UPDATED) sem segredos;
8. Guarda fail-closed: PATCH /channels/{id}/autonomous com enabled=True em canal sem destinos retorna HTTP 400;
9. Guarda fail-closed: PATCH /channels/{id}/autonomous permite ligar com 200 quando há destino ativo;
10. Desligar modo autônomo (enabled=False) permitido mesmo sem destinos;
11. GET /api/v2/publishing/accounts retorna contas conectadas;
12. GET /api/v2/publishing/accounts trata falhas do provedor graciosamente (200 com lista vazia sem quebrar).
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import asgi
from app.config import config
from app.services import autonomous_production, operator_console, profile_manager, scheduler


class TestApiV2ChannelDestinations(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        self.original_ui_config = dict(config.ui)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_v2_destinations.db")
        config.app["api_key"] = ""

        # Inicializa tabelas no banco temporário
        scheduler.init_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        operator_console.init_operator_db(self.db_path)
        profile_manager.ensure_default_profile(self.db_path)

        # Configurações globais padrão
        config.ui["voice_name"] = "pt-BR-FranciscaNeural"

        # Patch do get_db_path para garantir isolamento absoluto
        self.patcher_db = patch("app.services.operator_console.get_db_path", return_value=self.db_path)
        self.mock_get_db = self.patcher_db.start()

        # Patch de primary instance para True por padrão
        self.patcher_primary = patch("app.services.operator_console.is_primary_instance", return_value=True)
        self.mock_is_primary = self.patcher_primary.start()

        self.client = TestClient(asgi.app)

        # Cria perfil de teste sem nenhum destino
        self.test_profile = profile_manager.create_profile(
            name="Canal Teste Destinos",
            niche="curiosidades",
            db_path=self.db_path,
        )
        self.profile_id = self.test_profile["id"]

    def tearDown(self):
        self.patcher_primary.stop()
        self.patcher_db.stop()
        config.app.clear()
        config.app.update(self.original_app_config)
        config.ui.clear()
        config.ui.update(self.original_ui_config)
        self.temp_dir.cleanup()

    def test_get_channel_destinations_initial(self):
        """GET /destinations retorna estrutura esperada mesmo sem canais cadastrados."""
        resp = self.client.get(f"/api/v2/channels/{self.profile_id}/destinations")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["profile_id"], self.profile_id)
        self.assertIn("destinations", data)
        self.assertIn("by_platform", data)
        self.assertEqual(len(data["destinations"]), 2)

        yt = data["by_platform"]["youtube"]
        tt = data["by_platform"]["tiktok"]
        self.assertFalse(yt["is_enabled"])
        self.assertFalse(tt["is_enabled"])
        self.assertIsNone(yt["external_account_id"])
        self.assertIsNone(tt["external_account_id"])

    def test_patch_channel_destinations_create_new(self):
        """PATCH /destinations cria novo canal de destino quando não existe."""
        payload = {
            "platform": "youtube",
            "is_enabled": True,
            "external_account_id": "UC1234567890abcdefghij",
            "project_id": "proj-farme",
            "auto_publish_authorized": True,
        }
        resp = self.client.patch(f"/api/v2/channels/{self.profile_id}/destinations", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        yt = data["by_platform"]["youtube"]
        self.assertTrue(yt["is_enabled"])
        self.assertEqual(yt["external_account_id"], "UC1234567890abcdefghij")
        self.assertEqual(yt["project_id"], "proj-farme")
        self.assertTrue(yt["auto_publish_authorized"])
        self.assertIsNotNone(yt["id"])

        # Confirma persistência no SQLite
        persisted = profile_manager.list_channels(profile_id=self.profile_id, db_path=self.db_path)
        self.assertEqual(len(persisted), 1)
        self.assertEqual(persisted[0]["platform"], "youtube")
        self.assertEqual(persisted[0]["is_enabled"], 1)
        self.assertEqual(persisted[0]["auto_publish_authorized"], 1)

    def test_patch_channel_destinations_update_existing(self):
        """PATCH /destinations atualiza atributos de canal já existente."""
        # Cria canal existente
        created = profile_manager.create_channel(
            profile_id=self.profile_id,
            platform="tiktok",
            display_name="TikTok Original",
            external_account_id="user_old",
            is_enabled=False,
            db_path=self.db_path,
        )
        self.assertEqual(created["is_enabled"], 0)

        # Atualiza via PATCH
        payload = {
            "platform": "tiktok",
            "is_enabled": True,
            "external_account_id": "user_new",
            "project_id": "proj-tt",
            "auto_publish_authorized": False,
        }
        resp = self.client.patch(f"/api/v2/channels/{self.profile_id}/destinations", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        tt = data["by_platform"]["tiktok"]
        self.assertTrue(tt["is_enabled"])
        self.assertEqual(tt["external_account_id"], "user_new")
        self.assertEqual(tt["project_id"], "proj-tt")
        self.assertFalse(tt["auto_publish_authorized"])

    def test_patch_channel_destinations_batch(self):
        """PATCH /destinations aceita múltiplos destinos em lote via campo destinations."""
        payload = {
            "destinations": [
                {
                    "platform": "youtube",
                    "is_enabled": True,
                    "external_account_id": "UCyoutube999999999",
                    "auto_publish_authorized": True,
                },
                {
                    "platform": "tiktok",
                    "is_enabled": True,
                    "external_account_id": "tiktok_acc_123",
                    "auto_publish_authorized": False,
                },
            ]
        }
        resp = self.client.patch(f"/api/v2/channels/{self.profile_id}/destinations", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertTrue(data["by_platform"]["youtube"]["is_enabled"])
        self.assertTrue(data["by_platform"]["tiktok"]["is_enabled"])

    def test_patch_channel_destinations_fail_closed_secondary(self):
        """PATCH /destinations retorna 403 fail-closed em nó SECUNDÁRIO."""
        self.patcher_primary.stop()
        self.patcher_primary = patch("app.services.operator_console.is_primary_instance", return_value=False)
        self.patcher_primary.start()

        payload = {
            "platform": "youtube",
            "is_enabled": True,
            "external_account_id": "UC1234567890abcdefghij",
        }
        resp = self.client.patch(f"/api/v2/channels/{self.profile_id}/destinations", json=payload)
        self.assertEqual(resp.status_code, 403)
        self.assertIn("only primary instance", resp.json()["message"])

    def test_patch_channel_destinations_invalid_platform_400(self):
        """PATCH /destinations rejeita plataforma inválida com HTTP 400."""
        payload = {
            "platform": "instagram",
            "is_enabled": True,
        }
        resp = self.client.patch(f"/api/v2/channels/{self.profile_id}/destinations", json=payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("inválida", resp.json()["message"].lower())

    def test_patch_channel_destinations_youtube_without_uc_400(self):
        """PATCH /destinations exige que YouTube ID inicie com 'UC'."""
        payload = {
            "platform": "youtube",
            "is_enabled": True,
            "external_account_id": "NOT_STARTING_WITH_UC",
        }
        resp = self.client.patch(f"/api/v2/channels/{self.profile_id}/destinations", json=payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("deve iniciar com 'UC'", resp.json()["message"])

    def test_patch_channel_destinations_audit_log_without_secrets(self):
        """PATCH /destinations registra operational_event CHANNEL_DESTINATION_UPDATED sem dados sensíveis."""
        payload = {
            "platform": "youtube",
            "is_enabled": True,
            "external_account_id": "UCaudit1234567890",
            "auto_publish_authorized": True,
        }
        resp = self.client.patch(f"/api/v2/channels/{self.profile_id}/destinations", json=payload)
        self.assertEqual(resp.status_code, 200)

        with profile_manager.get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM operational_events WHERE event_type = 'CHANNEL_DESTINATION_UPDATED' ORDER BY id DESC LIMIT 1;"
            ).fetchone()
            self.assertIsNotNone(row)
            meta = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
            self.assertEqual(meta.get("platform"), "youtube")
            self.assertIn("changed_fields", meta)
            self.assertTrue(meta.get("new_is_enabled"))
            self.assertTrue(meta.get("new_auto_publish_authorized"))
            # Nenhum external_account_id nem project_id gravado nos metadados de auditoria
            self.assertNotIn("external_account_id", meta)
            self.assertNotIn("project_id", meta)
            # Nenhum token ou secret gravado
            self.assertNotIn("token", meta)
            self.assertNotIn("secret", meta)
            self.assertNotIn("api_key", meta)

    def test_patch_channel_destinations_atomic_validation_all_or_nothing(self):
        """PATCH /destinations com item 1 válido e item 2 inválido rejeita tudo (400) e não grava nada."""
        # Garante estado inicial vazio
        initial = profile_manager.list_channels(profile_id=self.profile_id, db_path=self.db_path)
        self.assertEqual(len(initial), 0)

        payload = {
            "destinations": [
                {
                    "platform": "youtube",
                    "is_enabled": True,
                    "external_account_id": "UCvalid1234567890",
                },
                {
                    "platform": "youtube",
                    "is_enabled": True,
                    "external_account_id": "INVALID_NO_UC",
                },
            ]
        }
        resp = self.client.patch(f"/api/v2/channels/{self.profile_id}/destinations", json=payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("deve iniciar com 'UC'", resp.json()["message"])

        # Prova que o item 1 NÃO foi gravado no banco de dados
        after = profile_manager.list_channels(profile_id=self.profile_id, db_path=self.db_path)
        self.assertEqual(len(after), 0)

    def test_compute_active_platforms_parity_with_get_channel_active_platforms(self):
        """Prova paridade estrita entre compute_active_platforms (pura) e get_channel_active_platforms (banco) para todos os cenários."""
        scenarios = [
            ("so_youtube", [{"platform": "youtube", "is_enabled": 1}], [], True, True, True, ["youtube"]),
            ("so_tiktok", [], [{"platform": "tiktok", "is_enabled": 1}], True, True, True, ["tiktok"]),
            ("ambos", [{"platform": "youtube", "is_enabled": 1}], [{"platform": "tiktok", "is_enabled": 1}], True, True, True, ["youtube", "tiktok"]),
            ("nenhum", [], [], True, True, True, []),
            ("2_tiktok_habilitados", [], [{"platform": "tiktok", "is_enabled": 1}, {"platform": "tiktok", "is_enabled": 1}], True, True, True, []),
            ("setting_desligado", [{"platform": "youtube", "is_enabled": 1}], [{"platform": "tiktok", "is_enabled": 1}], False, False, True, []),
            ("perfil_inativo", [{"platform": "youtube", "is_enabled": 1}], [{"platform": "tiktok", "is_enabled": 1}], True, True, False, []),
        ]

        for name, yt_c, tt_c, yt_set, tt_set, prof_act, expected in scenarios:
            with self.subTest(scenario=name):
                # 1. Função pura direta
                combined = yt_c + tt_c
                pure_result = autonomous_production.compute_active_platforms(
                    channels=combined,
                    youtube_enabled=yt_set,
                    tiktok_enabled=tt_set,
                    profile_active=prof_act,
                )
                self.assertEqual(pure_result, expected, f"Pure function failed for scenario {name}")

                # 2. Função com banco
                prof = profile_manager.create_profile(
                    name=f"Profile {name}",
                    slug=f"slug-{name}",
                    db_path=self.db_path,
                )
                p_id = prof["id"]
                if not prof_act:
                    profile_manager.update_profile(p_id, is_active=False, db_path=self.db_path)

                for idx, ch in enumerate(yt_c):
                    profile_manager.create_channel(
                        profile_id=p_id,
                        platform="youtube",
                        display_name=f"YT {name} {idx}",
                        is_enabled=bool(ch["is_enabled"]),
                        db_path=self.db_path,
                    )
                for idx, ch in enumerate(tt_c):
                    profile_manager.create_channel(
                        profile_id=p_id,
                        platform="tiktok",
                        display_name=f"TT {name} {idx}",
                        is_enabled=bool(ch["is_enabled"]),
                        db_path=self.db_path,
                    )
                scheduler.set_setting("youtube_enabled", "true" if yt_set else "false", db_path=self.db_path)
                scheduler.set_setting("tiktok_enabled", "true" if tt_set else "false", db_path=self.db_path)

                db_result = autonomous_production.get_channel_active_platforms(profile_id=p_id, db_path=self.db_path)
                self.assertEqual(db_result, expected, f"DB function get_channel_active_platforms failed for scenario {name}")
                self.assertEqual(pure_result, db_result, f"Discrepancy between pure and DB results for scenario {name}")

    def test_guard_autonomous_mode_rejects_without_destinations_400(self):
        """Guarda FAIL-SAFE: ligar autônomo sem nenhum destino ativo retorna HTTP 400."""
        # Garante que não há destinos habilitados
        active_plats = autonomous_production.get_channel_active_platforms(self.profile_id, db_path=self.db_path)
        self.assertEqual(active_plats, [])

        resp = self.client.patch(
            f"/api/v2/channels/{self.profile_id}/autonomous",
            json={"enabled": True},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["message"], "Canal sem destino de publicação habilitado")

        # Verifica que o modo autônomo continua desligado
        is_auto = autonomous_production.is_profile_autonomous_mode_enabled(self.profile_id, db_path=self.db_path)
        self.assertFalse(is_auto)

    def test_guard_autonomous_mode_allows_when_destination_enabled_200(self):
        """Guarda FAIL-SAFE: ligar autônomo funciona normalmente (200) quando há destino habilitado."""
        # Habilita destino YouTube
        profile_manager.create_channel(
            profile_id=self.profile_id,
            platform="youtube",
            display_name="YT Canal",
            external_account_id="UCchannelvalid123",
            is_enabled=True,
            db_path=self.db_path,
        )

        resp = self.client.patch(
            f"/api/v2/channels/{self.profile_id}/autonomous",
            json={"enabled": True},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["data"]["autonomous_enabled"])

        # Confirma no SQLite
        is_auto = autonomous_production.is_profile_autonomous_mode_enabled(self.profile_id, db_path=self.db_path)
        self.assertTrue(is_auto)

    def test_guard_autonomous_mode_allows_disabling_anytime_200(self):
        """Desligar modo autônomo (enabled=False) sempre é permitido mesmo sem destinos."""
        resp = self.client.patch(
            f"/api/v2/channels/{self.profile_id}/autonomous",
            json={"enabled": False},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["data"]["autonomous_enabled"])

    def test_get_publishing_accounts_success(self):
        """GET /api/v2/publishing/accounts retorna contas conectadas do post_for_me."""
        mock_accounts = [
            {
                "external_account_id": "UCmockaccount123",
                "display_name": "Canal Mock YouTube",
                "username": "@mockyt",
                "platform": "youtube",
                "project_id": "proj-1",
                "project_name": "Farme Videos",
            }
        ]
        with patch("app.services.post_for_me.list_connected_publishing_accounts", return_value=mock_accounts):
            resp = self.client.get("/api/v2/publishing/accounts?platform=youtube")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()["data"]
            self.assertEqual(data["total"], 1)
            self.assertEqual(data["accounts"][0]["external_account_id"], "UCmockaccount123")

    def test_get_publishing_accounts_provider_failure_graceful(self):
        """GET /api/v2/publishing/accounts trata falhas do provedor sem quebrar a tela (HTTP 200 com lista vazia)."""
        with patch("app.services.post_for_me.list_connected_publishing_accounts", side_effect=RuntimeError("API post_for_me timeout")):
            resp = self.client.get("/api/v2/publishing/accounts")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()["data"]
            self.assertEqual(data["accounts"], [])
            self.assertEqual(data["total"], 0)

    def test_get_publishing_accounts_invalid_platform_400(self):
        """GET /api/v2/publishing/accounts com plataforma inválida retorna HTTP 400."""
        resp = self.client.get("/api/v2/publishing/accounts?platform=invalid_plat")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("inválida", resp.json()["message"].lower())


if __name__ == "__main__":
    unittest.main()
