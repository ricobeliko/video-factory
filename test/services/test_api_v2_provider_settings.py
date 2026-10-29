"""Testes da Gestão de Chaves e Provedores Críticos na API V2.

Valida:
1. Gravação por LEITURA-MODIFICAÇÃO-GRAVAÇÃO no disco: valores alterados no disco
   fora do processo (ex.: voice_name e voice_rate) permanecem intactos após PATCH;
2. Apenas a chave enviada no PATCH é alterada;
3. Dois PATCHs consecutivos geram 2 backups distintos com data/hora;
4. Retenção de no máximo 10 backups mais recentes;
5. TOML inválido no disco aborta sem gravar nada e retorna HTTP 500 sem vazar segredos;
6. GET /settings/providers lê os valores diretamente do disco;
7. Auditoria em operational_events e respostas da API nunca expõem segredos;
8. Instância NÃO-PRIMARY recebe 403 fail-closed;
9. Máscara ('••••xxxx' ou '****') ou string vazia não altera chave existente;
10. Isolamento total: usa arquivo de configuração TEMPORÁRIO, NUNCA o config.toml real.
"""

from datetime import datetime
import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import toml

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

[other_section]
custom_setting = "keep_me_untouched"
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

    def test_disk_modification_preserved_after_patch(self):
        """1. Leitura-Modificação-Gravação no disco: alterações externas no disco são preservadas."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.is_primary_instance", return_value=True):

            # Simula alteração externa feita diretamente no arquivo de disco após o boot:
            # voice_name, voice_rate e uma seção extra são alterados no disco.
            # Em memória (config.app), os valores continuam os antigos.
            disk_toml = """[app]
llm_provider = "openai"
openai_api_key = "sk-initial-secret-key-1234"
openai_model_name = "gpt-4o"
openai_base_url = "https://api.openai.com/v1"
voice_name = "pt-BR-FranciscaNeural"
voice_rate = 1.35
tts_server = "edge-tts"
upload_post_enabled = false
upload_post_auto_upload = false
upload_post_api_key = "up-initial-secret-5678"
upload_post_username = "operador_teste"
upload_post_platforms = ["youtube", "tiktok"]
upload_post_youtube_privacy_status = "public"
upload_post_youtube_made_for_kids = false

[other_section]
custom_setting = "preserved_value_from_disk"
"""
            with open(self.test_config_path, "w", encoding="utf-8") as f:
                f.write(disk_toml)

            # PATCH altera SOMENTE a chave de API
            res = self.client.patch("/api/v2/settings/providers", json={
                "llm_api_key": "sk-new-secret-key-9999",
            })
            self.assertEqual(res.status_code, 200, res.text)

            # Lê o disco diretamente para provar que os valores do disco continuam intactos
            with open(self.test_config_path, "r", encoding="utf-8") as f:
                saved_content = f.read()
            saved_dict = toml.loads(saved_content)

            # A chave enviada foi atualizada
            self.assertEqual(saved_dict["app"]["openai_api_key"], "sk-new-secret-key-9999")

            # Os valores que mudaram no disco NÃO foram sobrescritos pelos valores em memória
            self.assertEqual(saved_dict["app"]["voice_name"], "pt-BR-FranciscaNeural")
            self.assertEqual(saved_dict["app"]["voice_rate"], 1.35)
            self.assertEqual(saved_dict["other_section"]["custom_setting"], "preserved_value_from_disk")

    def test_only_sent_key_changes_on_disk(self):
        """2. Apenas a chave enviada no PATCH muda no disco."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.is_primary_instance", return_value=True):

            res = self.client.patch("/api/v2/settings/providers", json={
                "upload_post_username": "novo_operador_disco",
            })
            self.assertEqual(res.status_code, 200, res.text)

            with open(self.test_config_path, "r", encoding="utf-8") as f:
                saved_dict = toml.loads(f.read())

            self.assertEqual(saved_dict["app"]["upload_post_username"], "novo_operador_disco")
            self.assertEqual(saved_dict["app"]["openai_api_key"], "sk-initial-secret-key-1234")
            self.assertEqual(saved_dict["app"]["upload_post_api_key"], "up-initial-secret-5678")
            self.assertEqual(saved_dict["app"]["voice_name"], "pt-BR-AntonioNeural")

    def test_two_consecutive_patches_generate_two_distinct_backups(self):
        """3. Dois PATCHs seguidos geram 2 backups distintos com data/hora."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.is_primary_instance", return_value=True):

            res1 = self.client.patch("/api/v2/settings/providers", json={
                "upload_post_username": "usuario_patch_1",
            })
            self.assertEqual(res1.status_code, 200)

            res2 = self.client.patch("/api/v2/settings/providers", json={
                "upload_post_username": "usuario_patch_2",
            })
            self.assertEqual(res2.status_code, 200)

            backups = [f for f in os.listdir(self.temp_dir.name) if f.startswith("test_config.toml.bak.")]
            self.assertGreaterEqual(len(backups), 2)
            self.assertNotEqual(backups[0], backups[1])

    def test_backup_retention_max_10(self):
        """4. Retenção de no máximo 10 backups mais recentes."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.is_primary_instance", return_value=True):

            for i in range(15):
                res = self.client.patch("/api/v2/settings/providers", json={
                    "upload_post_username": f"user_cycle_{i}",
                })
                self.assertEqual(res.status_code, 200)

            backups = [f for f in os.listdir(self.temp_dir.name) if f.startswith("test_config.toml.bak.")]
            self.assertEqual(len(backups), 10)

    def test_invalid_toml_on_disk_aborts_without_writing_and_returns_500(self):
        """5. TOML inválido no disco aborta sem gravar nada e retorna HTTP 500 sem vazar segredos."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.is_primary_instance", return_value=True):

            broken_content = "INVALID_CORRUPT_TOML = [[[ unclosed bracket"
            with open(self.test_config_path, "w", encoding="utf-8") as f:
                f.write(broken_content)

            # PATCH deve falhar com 500 claro
            res_patch = self.client.patch("/api/v2/settings/providers", json={
                "llm_provider": "gemini",
            })
            self.assertEqual(res_patch.status_code, 500)
            self.assertIn("invalido ou inacessivel", res_patch.text.lower())
            self.assertNotIn("unclosed", res_patch.text.lower())

            # Conteúdo no disco NÃO foi modificado
            with open(self.test_config_path, "r", encoding="utf-8") as f:
                disk_now = f.read()
            self.assertEqual(disk_now, broken_content)

            # GET também falha com 500 claro
            res_get = self.client.get("/api/v2/settings/providers")
            self.assertEqual(res_get.status_code, 500)
            self.assertIn("invalido ou inacessivel", res_get.text.lower())

    def test_get_reads_directly_from_disk(self):
        """6. GET /api/v2/settings/providers lê valores diretamente do disco."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path):
            # Altera modelo e provedor diretamente no disco (sem tocar em config.app)
            with open(self.test_config_path, "r", encoding="utf-8") as f:
                cfg = toml.loads(f.read())
            cfg["app"]["openai_model_name"] = "gpt-model-from-disk-only"
            with open(self.test_config_path, "w", encoding="utf-8") as f:
                f.write(toml.dumps(cfg))

            res = self.client.get("/api/v2/settings/providers")
            self.assertEqual(res.status_code, 200)
            data = res.json().get("data", {})
            self.assertEqual(data["llm"]["model_name"], "gpt-model-from-disk-only")

    def test_get_settings_never_exposes_full_keys(self):
        """7. GET nunca expõe segredos completos (máscara de 4 dígitos)."""
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

    def test_patch_on_secondary_instance_fails_closed_403(self):
        """8. Instância NÃO-PRIMARY recebe 403 fail-closed."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.is_primary_instance", return_value=False):

            res = self.client.patch("/api/v2/settings/providers", json={"llm_provider": "claude"})
            self.assertEqual(res.status_code, 403)
            self.assertIn("only primary instance", res.text.lower())

    def test_patch_with_mask_or_empty_does_not_alter_key(self):
        """9. Enviar máscara ou string vazia não altera chave existente."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.is_primary_instance", return_value=True):

            payload = {
                "llm_provider": "openai",
                "llm_api_key": "••••1234",
                "upload_post_api_key": "",
                "llm_model_name": "gpt-4o-mini",
            }

            res = self.client.patch("/api/v2/settings/providers", json=payload)
            self.assertEqual(res.status_code, 200, res.text)

            with open(self.test_config_path, "r", encoding="utf-8") as f:
                disk_cfg = toml.loads(f.read())

            self.assertEqual(disk_cfg["app"]["openai_api_key"], "sk-initial-secret-key-1234")
            self.assertEqual(disk_cfg["app"]["upload_post_api_key"], "up-initial-secret-5678")
            self.assertEqual(disk_cfg["app"]["openai_model_name"], "gpt-4o-mini")

    def test_patch_audit_event_logged_without_secrets(self):
        """10. Alteração gera operational_events com updated_fields e SEM segredos."""
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
