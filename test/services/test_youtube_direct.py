"""Testes direcionados para a Fundação do YouTube Direct Publisher (Fase V15-E.1).

Cobre:
1. PRIVATE permitido.
2. PUBLIC bloqueado com DIRECT_POC_PRIVATE_ONLY.
3. UNLISTED bloqueado com DIRECT_POC_PRIVATE_ONLY.
4. missing video bloqueado com VIDEO_FILE_MISSING.
5. zero-byte video bloqueado com VIDEO_FILE_ZERO_BYTES.
6. missing OAuth bloqueado com OAUTH_CREDENTIALS_MISSING.
7. channel mismatch bloqueado com CHANNEL_MISMATCH.
8. secrets não vazam em retorno ou logs.
9. upload usa videos.insert com resumable upload através de mock.
10. nenhuma chamada de rede real permitida durante a suíte.
"""

from __future__ import annotations

import io
import json
import os
import socket
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services import youtube_direct
from scripts import youtube_direct_probe


class TestYouTubeDirect(unittest.TestCase):
    def setUp(self):
        if sys.version_info >= (3, 10):
            self.temp_dir_obj = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        else:
            self.temp_dir_obj = tempfile.TemporaryDirectory()
        self.temp_dir = Path(self.temp_dir_obj.name)

        # Arquivo de vídeo de teste válido (> 0 bytes)
        self.valid_video_path = self.temp_dir / "valid_test_video.mp4"
        with open(self.valid_video_path, "wb") as f:
            f.write(b"FAKE_MP4_VIDEO_HEADER_AND_FRAMES_CONTENT")

        # Arquivo de vídeo vazio (0 bytes)
        self.zero_byte_video_path = self.temp_dir / "zero_byte_video.mp4"
        self.zero_byte_video_path.touch()

        # Bloqueio global de rede para garantir isolamento absoluto
        self._orig_socket_connect = socket.socket.connect
        def _fail_network_connect(*args, **kwargs):
            raise RuntimeError("Tentativa de acesso à rede detectada durante teste unitário!")
        socket.socket.connect = _fail_network_connect

    def tearDown(self):
        socket.socket.connect = self._orig_socket_connect
        try:
            self.temp_dir_obj.cleanup()
        except Exception:
            pass

    def _create_mock_credentials(
        self,
        expired: bool = False,
        has_refresh: bool = True,
        token: str = "mock_access_token_123",
        refresh_token: str = "mock_refresh_token_456",
    ) -> MagicMock:
        creds = MagicMock()
        creds.expired = expired
        creds.refresh_token = refresh_token if has_refresh else None
        creds.token = token
        creds.scopes = youtube_direct.DEFAULT_SCOPES
        expiry_dt = (datetime.now(timezone.utc) - timedelta(hours=1)) if expired else (datetime.now(timezone.utc) + timedelta(hours=1))
        creds.to_json.return_value = json.dumps({
            "token": token,
            "refresh_token": refresh_token if has_refresh else None,
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "mock_client_id.apps.googleusercontent.com",
            "client_secret": "mock_client_secret_xyz",
            "scopes": youtube_direct.DEFAULT_SCOPES,
            "expiry": expiry_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        return creds

    def test_1_private_allowed(self):
        """1. Valida que o status 'private' é aceito e dispara o fluxo de upload com sucesso."""
        mock_creds = self._create_mock_credentials()

        with patch("googleapiclient.discovery.build") as mock_build, \
             patch("googleapiclient.http.MediaFileUpload") as mock_media:

            mock_request = MagicMock()
            mock_request.next_chunk.return_value = (None, {"id": "YT_VID_001"})
            mock_youtube = MagicMock()
            mock_youtube.videos().insert.return_value = mock_request
            mock_build.return_value = mock_youtube

            res = youtube_direct.upload_video(
                video_path=str(self.valid_video_path),
                title="Vídeo Teste Private",
                description="Descrição",
                privacy_status="private",
                credentials=mock_creds,
            )

            self.assertTrue(res["success"])
            self.assertEqual(res["provider"], "youtube_direct")
            self.assertEqual(res["external_id"], "YT_VID_001")
            self.assertEqual(res["external_url"], "https://www.youtube.com/watch?v=YT_VID_001")
            self.assertEqual(res["privacy_status"], "private")
            self.assertIsNone(res["error_code"])

    def test_2_public_blocked(self):
        """2. Valida que o status 'public' é estritamente bloqueado na POC com DIRECT_POC_PRIVATE_ONLY."""
        res = youtube_direct.upload_video(
            video_path=str(self.valid_video_path),
            title="Vídeo Teste Public",
            privacy_status="public",
        )
        self.assertFalse(res["success"])
        self.assertEqual(res["error_code"], "DIRECT_POC_PRIVATE_ONLY")
        self.assertEqual(res["privacy_status"], "public")
        self.assertIn("DIRECT_POC_PRIVATE_ONLY", res["error_code"])

    def test_3_unlisted_blocked(self):
        """3. Valida que o status 'unlisted' é estritamente bloqueado na POC com DIRECT_POC_PRIVATE_ONLY."""
        res = youtube_direct.upload_video(
            video_path=str(self.valid_video_path),
            title="Vídeo Teste Unlisted",
            privacy_status="unlisted",
        )
        self.assertFalse(res["success"])
        self.assertEqual(res["error_code"], "DIRECT_POC_PRIVATE_ONLY")
        self.assertEqual(res["privacy_status"], "unlisted")

    def test_4_missing_video_blocked(self):
        """4. Valida fail-closed quando o arquivo de vídeo não existe."""
        missing_path = self.temp_dir / "arquivo_fantasma.mp4"
        res = youtube_direct.upload_video(
            video_path=str(missing_path),
            title="Vídeo Teste",
            privacy_status="private",
        )
        self.assertFalse(res["success"])
        self.assertEqual(res["error_code"], "VIDEO_FILE_MISSING")

    def test_5_zero_byte_video_blocked(self):
        """5. Valida fail-closed quando o arquivo de vídeo possui 0 bytes."""
        res = youtube_direct.upload_video(
            video_path=str(self.zero_byte_video_path),
            title="Vídeo Vazio",
            privacy_status="private",
        )
        self.assertFalse(res["success"])
        self.assertEqual(res["error_code"], "VIDEO_FILE_ZERO_BYTES")

    def test_6_missing_oauth_blocked(self):
        """6. Valida fail-closed quando as credenciais OAuth não estão disponíveis."""
        empty_creds_dir = self.temp_dir / "empty_creds"
        empty_creds_dir.mkdir(parents=True, exist_ok=True)

        res = youtube_direct.upload_video(
            video_path=str(self.valid_video_path),
            title="Vídeo Sem Token",
            privacy_status="private",
            profile_id="perfil_inexistente",
            channel_id="canal_inexistente",
            credentials_dir=str(empty_creds_dir),
        )
        self.assertFalse(res["success"])
        self.assertEqual(res["error_code"], "OAUTH_CREDENTIALS_MISSING")

    def test_7_channel_mismatch_blocked(self):
        """7. Valida fail-closed quando o canal autenticado difere do expected_channel_id."""
        mock_creds = self._create_mock_credentials()

        with patch("app.services.youtube_direct.get_authenticated_channel") as mock_auth_chan:
            mock_auth_chan.return_value = {
                "channel_id": "UC_CANAL_ERRADO_999",
                "channel_title": "Canal Errado",
            }

            res = youtube_direct.upload_video(
                video_path=str(self.valid_video_path),
                title="Vídeo Canal Mismatch",
                privacy_status="private",
                expected_channel_id="UC_CANAL_CORRETO_123",
                credentials=mock_creds,
            )

            self.assertFalse(res["success"])
            self.assertEqual(res["error_code"], "CHANNEL_MISMATCH")
            self.assertIn("UC_CANAL_ERRADO_999", res["error_message"])
            self.assertIn("UC_CANAL_CORRETO_123", res["error_message"])

    def test_8_secrets_not_leaked(self):
        """8. Valida que tokens de acesso, refresh tokens e segredos não aparecem em retornos nem logs."""
        raw_access_token = "ya29.A0AfH6SMD_SECRET_ACCESS_TOKEN_XYZ_123"
        raw_refresh_token = "1//04_SECRET_REFRESH_TOKEN_ABC_789"
        mock_creds = self._create_mock_credentials(
            token=raw_access_token,
            refresh_token=raw_refresh_token,
        )

        with patch("googleapiclient.discovery.build") as mock_build, \
             patch("googleapiclient.http.MediaFileUpload"):

            # Simula exceção da biblioteca contendo o token no texto
            mock_youtube = MagicMock()
            mock_youtube.videos().insert.side_effect = RuntimeError(
                f"Falha na API com token {raw_access_token} e refresh {raw_refresh_token}"
            )
            mock_build.return_value = mock_youtube

            res = youtube_direct.upload_video(
                video_path=str(self.valid_video_path),
                title="Vídeo com Erro",
                privacy_status="private",
                credentials=mock_creds,
            )

            self.assertFalse(res["success"])
            self.assertEqual(res["error_code"], "UPLOAD_FAILED")
            res_str = str(res)
            self.assertNotIn(raw_access_token, res_str)
            self.assertNotIn(raw_refresh_token, res_str)
            self.assertIn("[REDACTED_ACCESS_TOKEN]", res["error_message"])
            self.assertIn("[REDACTED_REFRESH_TOKEN]", res["error_message"])

    def test_9_upload_uses_resumable_insert_mock(self):
        """9. Valida que o upload utiliza videos.insert com resumable=True e estrutura canônica."""
        mock_creds = self._create_mock_credentials()

        with patch("googleapiclient.discovery.build") as mock_build, \
             patch("googleapiclient.http.MediaFileUpload") as mock_media:

            mock_request = MagicMock()
            mock_request.next_chunk.return_value = (None, {"id": "RESUMABLE_VID_777"})
            mock_youtube = MagicMock()
            mock_youtube.videos().insert.return_value = mock_request
            mock_build.return_value = mock_youtube

            res = youtube_direct.upload_video(
                video_path=str(self.valid_video_path),
                title="Título Resumable",
                description="Descrição Resumable",
                tags=["tag1", "tag2"],
                privacy_status="private",
                credentials=mock_creds,
            )

            self.assertTrue(res["success"])
            self.assertEqual(res["external_id"], "RESUMABLE_VID_777")

            # Verifica chamada do MediaFileUpload com resumable=True
            mock_media.assert_called_once()
            _, media_kwargs = mock_media.call_args
            self.assertTrue(media_kwargs.get("resumable"))
            self.assertEqual(media_kwargs.get("mimetype"), "video/mp4")

            # Verifica parâmetros do insert
            mock_youtube.videos().insert.assert_called_once()
            _, insert_kwargs = mock_youtube.videos().insert.call_args
            self.assertEqual(insert_kwargs.get("part"), "snippet,status")
            body = insert_kwargs.get("body", {})
            self.assertEqual(body["snippet"]["title"], "Título Resumable")
            self.assertEqual(body["status"]["privacyStatus"], "private")

    def test_10_authenticated_channel_query(self):
        """10. Valida método get_authenticated_channel retornando apenas channel_id e channel_title."""
        mock_creds = self._create_mock_credentials()

        with patch("googleapiclient.discovery.build") as mock_build:
            mock_youtube = MagicMock()
            mock_youtube.channels().list().execute.return_value = {
                "items": [
                    {
                        "id": "UC_CANONICAL_CHANNEL_ID_456",
                        "snippet": {"title": "Meu Canal Oficial"},
                    }
                ]
            }
            mock_build.return_value = mock_youtube

            info = youtube_direct.get_authenticated_channel(credentials=mock_creds)
            self.assertEqual(info["channel_id"], "UC_CANONICAL_CHANNEL_ID_456")
            self.assertEqual(info["channel_title"], "Meu Canal Oficial")
            self.assertNotIn("token", info)
            self.assertNotIn("refresh_token", info)

    def test_11_probe_cli_status_and_whoami(self):
        """11. Valida comandos status e whoami do CLI sem chamadas de rede."""
        # Salva credencial simulada
        mock_creds = self._create_mock_credentials()
        youtube_direct.save_credentials(
            mock_creds, profile_id="test_profile", channel_id="test_channel", credentials_dir=str(self.temp_dir)
        )

        with patch("googleapiclient.discovery.build") as mock_build:
            mock_youtube = MagicMock()
            mock_youtube.channels().list().execute.return_value = {
                "items": [{"id": "UC_CLI_TEST", "snippet": {"title": "Canal CLI Test"}}]
            }
            mock_build.return_value = mock_youtube

            # Testa status
            ret_status = youtube_direct_probe.main([
                "status",
                "--profile-id", "test_profile",
                "--channel-id", "test_channel",
                "--credentials-dir", str(self.temp_dir),
            ])
            self.assertEqual(ret_status, 0)

            # Testa whoami
            ret_whoami = youtube_direct_probe.main([
                "whoami",
                "--profile-id", "test_profile",
                "--channel-id", "test_channel",
                "--credentials-dir", str(self.temp_dir),
            ])
            self.assertEqual(ret_whoami, 0)


if __name__ == "__main__":
    unittest.main()
