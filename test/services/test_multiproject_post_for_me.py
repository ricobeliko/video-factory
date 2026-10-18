"""Testes direcionados para suporte multiprojeto Post for Me (Fase Correção Multiprojeto).

Cobre:
1. Descoberta de contas em múltiplos projetos (farme videos LABEL e tiktok)
2. YouTube principal usando credencial principal (POST_FOR_ME_API_KEY)
3. TikTok usando credencial secundária (POST_FOR_ME_TIKTOK_API_KEY / POST_FOR_ME_QUICKSTART_API_KEY)
4. Um perfil com destinos em projetos diferentes
5. Falha segura sem credencial (Fail Closed)
6. Compatibilidade retroativa de canais legados (project_id = NULL)
7. Idempotência, status e reconciliação no projeto correto
8. Proteção absoluta contra exposição de credenciais (sanitize_secrets)
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.services import post_for_me, profile_manager, task


class TestMultiProjectPostForMe(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_video_factory.db")
        profile_manager.init_profile_db(self.db_path)
        profile_manager.ensure_default_profile(db_path=self.db_path)

        # Mock das variáveis de ambiente para isolamento completo
        self.env_patcher = patch.dict(
            os.environ,
            {
                "POST_FOR_ME_API_KEY": "pfm_live_key_principal_farme_12345",
                "POST_FOR_ME_TIKTOK_API_KEY": "pfm_live_key_secundaria_tiktok_67890",
                "POST_FOR_ME_QUICKSTART_API_KEY": "pfm_live_key_secundaria_tiktok_67890",
            },
        )
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_1_discovery_across_two_projects(self):
        """1. Descoberta de contas sociais agrega contas de ambos os projetos sem expor chaves."""
        accounts_farme = [
            {
                "id": "spc_yt_farme_1",
                "platform": "youtube",
                "user_id": "UC_farme_channel_11111111",
                "display_name": "Farme Channel 1",
                "status": "connected",
            },
            {
                "id": "spc_yt_farme_2",
                "platform": "youtube",
                "user_id": "UC_farme_channel_22222222",
                "display_name": "Farme Channel 2",
                "status": "connected",
            },
        ]
        accounts_tiktok = [
            {
                "id": "spc_tt_project_yt",
                "platform": "youtube",
                "user_id": "UC_tiktok_proj_yt_333333",
                "display_name": "YouTube in TikTok Project",
                "status": "connected",
            },
            {
                "id": "spc_tt_project_tt1",
                "platform": "tiktok",
                "user_id": "tiktok_user_dose_escolhas_99",
                "display_name": "Dose Diária de Escolhas",
                "status": "connected",
            },
        ]

        with patch.object(post_for_me.post_for_me_client, "list_social_accounts", return_value=accounts_farme), \
             patch.object(post_for_me.post_for_me_tiktok_client, "list_social_accounts") as mock_tt_list:

            # Quando consultar youtube: farme_videos retorna 2 contas, tiktok retorna 1
            mock_tt_list.return_value = [accounts_tiktok[0]]
            yt_res = post_for_me.list_connected_publishing_accounts(platform="youtube")
            self.assertEqual(len(yt_res), 3)

            # Verifica tagging correto de project_id e project_name
            farme_entries = [a for a in yt_res if a["project_id"] == "farme_videos"]
            tt_entries = [a for a in yt_res if a["project_id"] == "tiktok"]
            self.assertEqual(len(farme_entries), 2)
            self.assertEqual(len(tt_entries), 1)
            self.assertEqual(farme_entries[0]["project_name"], "farme videos LABEL")
            self.assertEqual(tt_entries[0]["project_name"], "tiktok")

            # Quando consultar tiktok: farme_videos retorna 0, tiktok retorna a conta "Dose Diária de Escolhas"
            mock_tt_list.return_value = [accounts_tiktok[1]]
            with patch.object(post_for_me.post_for_me_client, "list_social_accounts", return_value=[]):
                tt_res = post_for_me.list_connected_publishing_accounts(platform="tiktok")
                self.assertEqual(len(tt_res), 1)
                self.assertEqual(tt_res[0]["display_name"], "Dose Diária de Escolhas")
                self.assertEqual(tt_res[0]["external_account_id"], "tiktok_user_dose_escolhas_99")
                self.assertEqual(tt_res[0]["project_id"], "tiktok")

    def test_2_youtube_uses_primary_credential(self):
        """2. Destino YouTube principal utiliza cliente com POST_FOR_ME_API_KEY."""
        ch = profile_manager.create_channel(
            profile_id="default",
            platform="youtube",
            display_name="Canal YouTube Principal",
            external_account_id="UCss-ng7mkGuB2v-5KKtIN9A",
            project_id=post_for_me.PROJECT_FARME_VIDEOS,
            db_path=self.db_path,
        )

        client = post_for_me.get_client_for_channel(
            channel_id=ch["id"],
            platform="youtube",
            db_path=self.db_path,
        )
        self.assertEqual(client.project_id, post_for_me.PROJECT_FARME_VIDEOS)
        self.assertEqual(client.api_key, "pfm_live_key_principal_farme_12345")

    def test_3_tiktok_uses_secondary_credential(self):
        """3. Destino TikTok utiliza cliente secundário (POST_FOR_ME_TIKTOK_API_KEY)."""
        ch = profile_manager.create_channel(
            profile_id="default",
            platform="tiktok",
            display_name="Dose Diária de Escolhas",
            external_account_id="tiktok_user_dose_escolhas_99",
            project_id=post_for_me.PROJECT_TIKTOK,
            db_path=self.db_path,
        )

        client = post_for_me.get_client_for_channel(
            channel_id=ch["id"],
            platform="tiktok",
            db_path=self.db_path,
        )
        self.assertEqual(client.project_id, post_for_me.PROJECT_TIKTOK)
        self.assertEqual(client.api_key, "pfm_live_key_secundaria_tiktok_67890")

    def test_4_single_profile_with_destinations_in_different_projects(self):
        """4. Um perfil com destinos em projetos distintos roteia cada publicação para a API Key correta."""
        onboard_res = profile_manager.onboard_channel_workspace(
            name="Canal Híbrido Multiprojeto",
            niche="curiosidades",
            topic_brief="Fatos fascinantes",
            destinations=[
                {
                    "platform": "youtube",
                    "display_name": "Canal YouTube Farme",
                    "external_account_id": "UC_farme_test_1234567890",
                    "project_id": post_for_me.PROJECT_FARME_VIDEOS,
                    "is_enabled": True,
                },
                {
                    "platform": "tiktok",
                    "display_name": "TikTok Projeto TikTok",
                    "external_account_id": "tiktok_user_hybrid_456",
                    "project_id": post_for_me.PROJECT_TIKTOK,
                    "is_enabled": True,
                },
            ],
            db_path=self.db_path,
        )
        pid = onboard_res["profile_id"]
        channels = profile_manager.list_channels(profile_id=pid, db_path=self.db_path)
        yt_ch = next(c for c in channels if c["platform"] == "youtube")
        tt_ch = next(c for c in channels if c["platform"] == "tiktok")

        # Verifica persistência do project_id
        self.assertEqual(yt_ch.get("project_id"), post_for_me.PROJECT_FARME_VIDEOS)
        self.assertEqual(tt_ch.get("project_id"), post_for_me.PROJECT_TIKTOK)

        # Resolução de clientes
        yt_client = post_for_me.get_client_for_channel(channel_id=yt_ch["id"], platform="youtube", db_path=self.db_path)
        tt_client = post_for_me.get_client_for_channel(channel_id=tt_ch["id"], platform="tiktok", db_path=self.db_path)

        self.assertEqual(yt_client.project_id, post_for_me.PROJECT_FARME_VIDEOS)
        self.assertEqual(yt_client.api_key, "pfm_live_key_principal_farme_12345")

        self.assertEqual(tt_client.project_id, post_for_me.PROJECT_TIKTOK)
        self.assertEqual(tt_client.api_key, "pfm_live_key_secundaria_tiktok_67890")

    def test_5_fail_closed_without_credentials(self):
        """5. Falha com segurança (Fail Closed) quando chave do projeto não está configurada."""
        with patch.dict(os.environ, {"POST_FOR_ME_API_KEY": "", "POST_FOR_ME_TIKTOK_API_KEY": "", "POST_FOR_ME_QUICKSTART_API_KEY": ""}, clear=True):
            client = post_for_me.PostForMeClient(env_api_key_name=post_for_me.ENV_TIKTOK_API_KEY)
            self.assertFalse(client.is_configured())
            with self.assertRaises(post_for_me.PostForMeAuthError):
                client._headers()

            # Em task.publish_task validação fail-closed
            can_pub, reason = task.publish_task("dummy_task_id", platforms=["tiktok"], db_path=self.db_path)
            self.assertFalse(can_pub)
            self.assertIn("missing API Key", reason)

    def test_6_legacy_channels_backward_compatibility(self):
        """6. Compatibilidade estrita com canais legados (project_id = NULL) no banco."""
        with profile_manager.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO publishing_channels (
                    id, profile_id, platform, display_name, external_profile_name,
                    external_account_id, project_id, is_enabled, created_at, updated_at
                ) VALUES ('legacy-yt-1', 'default', 'youtube', 'Legacy YouTube', NULL, 'UCss-ng7mkGuB2v-5KKtIN9A', NULL, 1, '2026-01-01', '2026-01-01');
                """
            )
            conn.execute(
                """
                INSERT INTO publishing_channels (
                    id, profile_id, platform, display_name, external_profile_name,
                    external_account_id, project_id, is_enabled, created_at, updated_at
                ) VALUES ('legacy-tt-1', 'default', 'tiktok', 'Legacy TikTok', NULL, '-00084CZ8cOFQstM-kHqpIgjFOeYUf6w4a4F', NULL, 1, '2026-01-01', '2026-01-01');
                """
            )

        # Canal legado YouTube com project_id=NULL resolve para o cliente principal (farme videos)
        client_yt = post_for_me.get_client_for_channel(channel_id="legacy-yt-1", platform="youtube", db_path=self.db_path)
        self.assertEqual(client_yt.project_id, post_for_me.PROJECT_FARME_VIDEOS)
        self.assertEqual(client_yt.api_key, "pfm_live_key_principal_farme_12345")

        # Canal legado TikTok com project_id=NULL resolve para o cliente tiktok
        client_tt = post_for_me.get_client_for_channel(channel_id="legacy-tt-1", platform="tiktok", db_path=self.db_path)
        self.assertEqual(client_tt.project_id, post_for_me.PROJECT_TIKTOK)
        self.assertEqual(client_tt.api_key, "pfm_live_key_secundaria_tiktok_67890")

    def test_7_idempotency_and_reconciliation_in_correct_project(self):
        """7. Reconciliação e idempotência utilizam o cliente do projeto correto preservando IDs existentes."""
        onboard_res = profile_manager.onboard_channel_workspace(
            name="Canal TikTok Reconcile",
            niche="humor",
            topic_brief="Humor diário",
            destinations=[
                {
                    "platform": "tiktok",
                    "display_name": "TikTok Reconcile Account",
                    "external_account_id": "tt_acc_reconcile_999",
                    "project_id": post_for_me.PROJECT_TIKTOK,
                    "is_enabled": True,
                }
            ],
            db_path=self.db_path,
        )
        tt_cid = onboard_res["channel_ids"][0]
        task_id = "test_recon_task_001"

        mock_classification = {
            "success_posts": [
                {
                    "post_id": "spp_existing_remote_987",
                    "post": {
                        "id": "spp_existing_remote_987",
                        "status": "success",
                        "privacy": "public",
                    },
                    "result_info": {
                        "success": True,
                        "post_id": "spp_existing_remote_987",
                        "tiktok_video_id": "7421893819283192",
                        "url": "https://www.tiktok.com/video/7421893819283192",
                        "privacy_status": "public",
                    },
                }
            ],
            "active_posts": [],
            "failed_posts": [],
            "inconsistent_posts": [],
        }

        with patch.object(post_for_me.post_for_me_tiktok_client, "resolve_tiktok_account_for_user", return_value={"id": "spc_tt_rec_999"}), \
             patch.object(post_for_me.post_for_me_tiktok_client, "classify_existing_posts", return_value=mock_classification):

            recon = post_for_me.reconcile_post_for_me_status(
                task_id=task_id,
                platform="tiktok",
                channel_id=tt_cid,
                db_path=self.db_path,
            )
            self.assertEqual(recon.get("status"), "reconciled_success")
            self.assertEqual(recon.get("external_id"), "7421893819283192")
            self.assertEqual(recon.get("external_url"), "https://www.tiktok.com/video/7421893819283192")

    def test_8_sanitize_secrets_protects_all_project_keys(self):
        """8. Proteção absoluta contra vazamento de chaves em logs/mensagens de erro."""
        err_msg = (
            "Erro HTTP: chave principal pfm_live_key_principal_farme_12345 rejeitada "
            "e chave secundária pfm_live_key_secundaria_tiktok_67890 também."
        )
        sanitized = post_for_me.sanitize_secrets(err_msg)
        self.assertNotIn("pfm_live_key_principal_farme_12345", sanitized)
        self.assertNotIn("pfm_live_key_secundaria_tiktok_67890", sanitized)
        self.assertIn("[REDACTED_API_KEY]", sanitized)


if __name__ == "__main__":
    unittest.main()
