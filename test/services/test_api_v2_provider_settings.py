"""Testes da Gestão de Chaves e Provedores Críticos na API V2.

Valida:
1. GET /api/v2/settings/providers nunca expõe chave completa (somente is_configured e máscara '••••xxxx');
2. PATCH /api/v2/settings/providers atualiza apenas campos enviados e preserva as demais chaves do config;
3. PATCH com máscara ('••••xxxx' ou '****') ou string vazia não altera chave existente;
4. PATCH cria backup de segurança antes da alteração (config.toml.bak);
5. PATCH em instância NÃO-PRIMARY retorna 403 (fail-closed);
6. Auditoria: operational_events registra PROVIDER_SETTINGS_UPDATED com updated_fields e ZERO segredos;
7. Validação: rejeita plataformas inválidas e valores desconhecidos (400 ou 422);
8. Isolamento: usa arquivo de configuração TEMPORÁRIO, NUNCA o config.toml real.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import asgi
from app.config import config
from app.services import operator_console, provider_settings


class TestApiV2ProviderSettings(unittest.TestCase):
    def setUp(self):
        self.orig_config_file = config.config_file
        self.orig_app_config = dict(config.app)

        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_config_path = os.path.join(self.temp_dir.name, "test_config.toml")
        self.db_path = os.path.join(self.temp_dir.name, "test_providers.db")

        # Configura arquivo temporário isolado com valores conhecidos
        initial_toml = """[app]
llm_provider = "openai"
openai_api_key = "sk-initial-secret-key-1234"
openai_model_name = "gpt-4o"
openai_base_url = "https://api.openai.com/v1"
voice_name = "pt-BR-AntonioNeural"
voice_rate = 1.0
tts_server = "edge-tts"
upload_post_enabled = false
upload_post_auto_upload = false
upload_post_api_key = "up-initial-secret-5678"
upload_post_username = "operador_teste"
upload_post_platforms = ["youtube", "tiktok"]
upload_post_youtube_privacy_status = "public"
upload_post_youtube_made_for_kids = false
"""
        with open(self.test_config_path, "w", encoding="utf-8") as f:
            f.write(initial_toml)

        config.config_file = self.test_config_path
        config.app.clear()
        config.app.update({
            "api_key": "",
            "llm_provider": "openai",
            "openai_api_key": "sk-initial-secret-key-1234",
            "openai_model_name": "gpt-4o",
            "openai_base_url": "https://api.openai.com/v1",
            "voice_name": "pt-BR-AntonioNeural",
            "voice_rate": 1.0,
            "tts_server": "edge-tts",
            "upload_post_enabled": False,
            "upload_post_auto_upload": False,
            "upload_post_api_key": "up-initial-secret-5678",
            "upload_post_username": "operador_teste",
            "upload_post_platforms": ["youtube", "tiktok"],
            "upload_post_youtube_privacy_status": "public",
            "upload_post_youtube_made_for_kids": False,
        })

        operator_console.init_operator_db(self.db_path)
        operator_console.reset_instance_for_testing()
        operator_console.ensure_instance_initialized(db_path=self.db_path)

        self.client = TestClient(asgi.app)

    def tearDown(self):
        operator_console.reset_instance_for_testing()
        config.config_file = self.orig_config_file
        config.app.clear()
        config.app.update(self.orig_app_config)
        self.temp_dir.cleanup()

    def test_get_settings_never_exposes_full_keys(self):
        """1. GET /api/v2/settings/providers nunca expõe segredos completos."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path):
            res = self.client.get("/api/v2/settings/providers")
            self.assertEqual(res.status_code, 200, res.text)
            data = res.json().get("data", {})

            # LLM
            llm = data.get("llm", {})
            self.assertEqual(llm.get("provider"), "openai")
            self.assertTrue(llm.get("is_configured"))
            self.assertEqual(llm.get("masked_api_key"), "••••1234")
            self.assertNotIn("sk-initial-secret-key-1234", str(data))

            # Upload-Post
            up = data.get("upload_post", {})
            self.assertEqual(up.get("username"), "operador_teste")
            self.assertTrue(up.get("is_configured"))
            self.assertEqual(up.get("masked_api_key"), "••••5678")
            self.assertNotIn("up-initial-secret-5678", str(data))

            # Provedores disponíveis
            avail = llm.get("available_providers", [])
            openai_p = next((p for p in avail if p.get("id") == "openai"), None)
            self.assertIsNotNone(openai_p)
            self.assertTrue(openai_p.get("is_configured"))
            self.assertEqual(openai_p.get("masked_api_key"), "••••1234")

    def test_patch_settings_updates_sent_fields_and_preserves_others(self):
        """2. PATCH atualiza campos enviados, preserva os demais e gera backup."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.is_primary_instance", return_value=True):

            payload = {
                "llm_provider": "gemini",
                "llm_api_key": "ai-new-gemini-secret-9999",
                "llm_model_name": "gemini-2.5-flash",
                "upload_post_enabled": True,
                "upload_post_auto_upload": True,
                "upload_post_platforms": ["youtube", "tiktok", "instagram"],
                "upload_post_youtube_privacy_status": "unlisted",
                "upload_post_youtube_made_for_kids": True,
            }

            res = self.client.patch("/api/v2/settings/providers", json=payload)
            self.assertEqual(res.status_code, 200, res.text)
            data = res.json().get("data", {})

            # Confirma resposta mascarada
            self.assertEqual(data["llm"]["provider"], "gemini")
            self.assertEqual(data["llm"]["masked_api_key"], "••••9999")
            self.assertTrue(data["upload_post"]["enabled"])
            self.assertTrue(data["upload_post"]["auto_upload"])
            self.assertEqual(data["upload_post"]["youtube_privacy_status"], "unlisted")
            self.assertTrue(data["upload_post"]["youtube_made_for_kids"])

            # Preservou chaves alheias no config.app (voice_name, tts_server, etc)
            self.assertEqual(config.app.get("voice_name"), "pt-BR-AntonioNeural")
            self.assertEqual(config.app.get("voice_rate"), 1.0)
            self.assertEqual(config.app.get("tts_server"), "edge-tts")
            # Preservou a chave antiga do openai intocada
            self.assertEqual(config.app.get("openai_api_key"), "sk-initial-secret-key-1234")
            # Gravou nova chave gemini
            self.assertEqual(config.app.get("gemini_api_key"), "ai-new-gemini-secret-9999")

            # Backup criado
            bak_path = self.test_config_path + ".bak"
            self.assertTrue(os.path.isfile(bak_path))
            with open(bak_path, "r", encoding="utf-8") as f:
                bak_content = f.read()
            self.assertIn("sk-initial-secret-key-1234", bak_content)

    def test_patch_with_mask_or_empty_does_not_alter_key(self):
        """3. Enviar a máscara ou chave vazia NÃO altera a chave existente."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.is_primary_instance", return_value=True):

            payload = {
                "llm_provider": "openai",
                "llm_api_key": "••••1234",  # Máscara vinda do input
                "upload_post_api_key": "",   # Vazio
                "llm_model_name": "gpt-4o-mini",
            }

            res = self.client.patch("/api/v2/settings/providers", json=payload)
            self.assertEqual(res.status_code, 200, res.text)

            # A chave anterior permanece inalterada
            self.assertEqual(config.app.get("openai_api_key"), "sk-initial-secret-key-1234")
            self.assertEqual(config.app.get("upload_post_api_key"), "up-initial-secret-5678")
            self.assertEqual(config.app.get("openai_model_name"), "gpt-4o-mini")

    def test_patch_on_secondary_instance_fails_closed_403(self):
        """4. Instância NÃO-PRIMARY recebe 403 fail-closed ao tentar alterar configurações."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.is_primary_instance", return_value=False):

            res = self.client.patch("/api/v2/settings/providers", json={"llm_provider": "claude"})
            self.assertEqual(res.status_code, 403)
            self.assertIn("only primary instance", res.text.lower())

    def test_patch_audit_event_logged_without_secrets(self):
        """5. Alteração gera operational_events com updated_fields e SEM segredos."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.is_primary_instance", return_value=True):

            secret_key = "super-secret-password-xyz-8888"
            payload = {
                "llm_provider": "openai",
                "llm_api_key": secret_key,
                "upload_post_username": "novo_username",
            }

            res = self.client.patch("/api/v2/settings/providers", json=payload)
            self.assertEqual(res.status_code, 200)

            # Inspeciona eventos no banco
            events = operator_console.get_operational_events(limit=20, db_path=self.db_path)
            prov_events = [e for e in events if e.get("event_type") == "PROVIDER_SETTINGS_UPDATED"]
            self.assertTrue(len(prov_events) >= 1)

            latest_event = prov_events[0]
            meta = latest_event.get("metadata", {})
            self.assertIn("updated_fields", meta)
            self.assertIn("llm_api_key", meta["updated_fields"])
            self.assertIn("upload_post_username", meta["updated_fields"])

            # Prova absoluta de que o segredo NUNCA vazou no log de auditoria
            event_dump = str(latest_event)
            self.assertNotIn("super-secret-password-xyz", event_dump)
            self.assertNotIn("8888", event_dump)

    def test_patch_validation_rejects_invalid_inputs(self):
        """6. Rejeita plataformas inválidas ou provedores desconhecidos."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.is_primary_instance", return_value=True):

            # Plataforma inválida
            res1 = self.client.patch("/api/v2/settings/providers", json={
                "upload_post_platforms": ["orkut", "youtube"]
            })
            self.assertEqual(res1.status_code, 400)
            self.assertIn("orkut", res1.text)

            # Privacidade YouTube inválida
            res2 = self.client.patch("/api/v2/settings/providers", json={
                "upload_post_youtube_privacy_status": "hidden"
            })
            self.assertEqual(res2.status_code, 400)
            self.assertIn("hidden", res2.text)

            # Provedor LLM desconhecido
            res3 = self.client.patch("/api/v2/settings/providers", json={
                "llm_provider": "fake_ai_model_never_exists"
            })
            self.assertEqual(res3.status_code, 400)
            self.assertIn("fake_ai_model_never_exists", res3.text)

            # Payload vazio
            res4 = self.client.patch("/api/v2/settings/providers", json={})
            self.assertEqual(res4.status_code, 400)
