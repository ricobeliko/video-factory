"""
test/services/test_webui_manual_publish.py
==========================================
Testes direcionados para publicação manual de tarefas via Post For Me na WebUI.

Valida:
A. YouTube + post_for_me + Upload-Post OFF => modal permite publicação.
B. Confirmação => tm.publish_task recebe platforms=["youtube"].
C. Provider legado => validações Upload-Post continuam funcionando.
D. Post For Me não configurado => modal bloqueia antes da confirmação.
"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.config import config
from app.services import youtube_publisher
from webui import Main


class TestWebUIManualPublish(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_manual_publish_")
        self.task_id = "task_manual_pub_001"
        self.task_dir = os.path.join(self.test_dir, self.task_id)
        os.makedirs(self.task_dir, exist_ok=True)
        self.video_file = os.path.join(self.task_dir, "final.mp4")
        with open(self.video_file, "wb") as f:
            f.write(b"\x00" * 1024)
        self.tr_patcher = patch.object(Main, "tr", side_effect=lambda k: k)
        self.tr_patcher.start()

    def tearDown(self):
        self.tr_patcher.stop()
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _setup_mock_st(self):
        mock_st = MagicMock()
        mock_st.session_state = {}
        # mock columns to return two column mocks
        col1 = MagicMock()
        col2 = MagicMock()
        col1.button.return_value = False
        col2.button.return_value = False
        mock_st.columns.return_value = (col1, col2)
        mock_st.button.return_value = False
        return mock_st, col1, col2

    # =========================================================================
    # A. YouTube + post_for_me + Upload-Post OFF => modal permite publicação
    # =========================================================================
    def test_a_youtube_post_for_me_upload_post_off_allows_publish(self):
        mock_st, col1, col2 = self._setup_mock_st()
        test_app_config = dict(
            config.app,
            upload_post_enabled=False,
            upload_post_api_key="",
            upload_post_username="",
            upload_post_platforms=["youtube"],
        )

        with patch.object(Main, "st", mock_st), \
             patch.object(config, "app", test_app_config), \
             patch("app.utils.utils.task_dir", return_value=self.test_dir), \
             patch("app.services.state.state.get_task", return_value={"video_subject": "Teste PFM", "videos": [self.video_file]}), \
             patch("app.services.youtube_publisher.get_youtube_publish_provider", return_value=youtube_publisher.PROVIDER_POST_FOR_ME), \
             patch("app.services.post_for_me.post_for_me_client.is_configured", return_value=True), \
             patch("app.services.operator_console.is_primary_instance", return_value=True):

            Main._render_task_publish_dialog.__wrapped__(self.task_id)

        # Não deve emitir erro de Upload-Post desabilitado nem não-configurado
        for call_args in mock_st.error.call_args_list:
            msg = str(call_args[0][0])
            self.assertNotIn("Upload-Post integration is disabled", msg)
            self.assertNotIn("Upload-Post is not configured", msg)

        # Deve exibir a tela de confirmação
        written_messages = [str(call[0][0]) for call in mock_st.write.call_args_list]
        self.assertTrue(any("Publish Task Confirmation" in m for m in written_messages))
        self.assertTrue(col2.button.called)

    # =========================================================================
    # B. Confirmação => publish_task recebe platforms=["youtube"]
    # =========================================================================
    def test_b_youtube_post_for_me_confirmation_calls_publish_task_platforms_youtube(self):
        mock_st, col1, col2 = self._setup_mock_st()
        # Simula clique em Confirm Publish
        col2.button.return_value = True

        test_app_config = dict(
            config.app,
            upload_post_enabled=False,
            upload_post_api_key="",
            upload_post_username="",
            upload_post_platforms=["youtube"],
        )

        with patch.object(Main, "st", mock_st), \
             patch.object(config, "app", test_app_config), \
             patch("app.utils.utils.task_dir", return_value=self.test_dir), \
             patch("app.services.state.state.get_task", return_value={"video_subject": "Teste PFM", "videos": [self.video_file]}), \
             patch("app.services.youtube_publisher.get_youtube_publish_provider", return_value=youtube_publisher.PROVIDER_POST_FOR_ME), \
             patch("app.services.post_for_me.post_for_me_client.is_configured", return_value=True), \
             patch("app.services.operator_console.is_primary_instance", return_value=True), \
             patch("app.services.task.publish_task", return_value=(True, "")) as mock_publish:

            Main._render_task_publish_dialog.__wrapped__(self.task_id)

        mock_publish.assert_called_once_with(self.task_id, platforms=["youtube"])
        self.assertEqual(mock_st.session_state.get("task_publish_succeeded"), True)

    # =========================================================================
    # C. Provider legado => validações Upload-Post continuam funcionando
    # =========================================================================
    def test_c_legacy_provider_enforces_upload_post_validations(self):
        mock_st, col1, col2 = self._setup_mock_st()
        test_app_config = dict(
            config.app,
            upload_post_enabled=False,
            upload_post_api_key="key_123",
            upload_post_username="user_123",
            upload_post_platforms=["youtube"],
        )

        with patch.object(Main, "st", mock_st), \
             patch.object(config, "app", test_app_config), \
             patch("app.utils.utils.task_dir", return_value=self.test_dir), \
             patch("app.services.state.state.get_task", return_value={"video_subject": "Teste Legado", "videos": [self.video_file]}), \
             patch("app.services.youtube_publisher.get_youtube_publish_provider", return_value=youtube_publisher.PROVIDER_UPLOAD_POST):

            Main._render_task_publish_dialog.__wrapped__(self.task_id)

        # Provider legado com Upload-Post disabled deve bloquear imediatamente com erro
        mock_st.error.assert_called_once()
        err_msg = str(mock_st.error.call_args[0][0])
        self.assertIn("Upload-Post integration is disabled", err_msg)
        self.assertFalse(col2.button.called)

    def test_c2_legacy_provider_enforces_api_key_and_username(self):
        mock_st, col1, col2 = self._setup_mock_st()
        test_app_config = dict(
            config.app,
            upload_post_enabled=True,
            upload_post_api_key="",
            upload_post_username="",
            upload_post_platforms=["youtube"],
        )

        with patch.object(Main, "st", mock_st), \
             patch.object(config, "app", test_app_config), \
             patch("app.utils.utils.task_dir", return_value=self.test_dir), \
             patch("app.services.state.state.get_task", return_value={"video_subject": "Teste Legado", "videos": [self.video_file]}), \
             patch("app.services.youtube_publisher.get_youtube_publish_provider", return_value=youtube_publisher.PROVIDER_UPLOAD_POST):

            Main._render_task_publish_dialog.__wrapped__(self.task_id)

        mock_st.error.assert_called_once()
        err_msg = str(mock_st.error.call_args[0][0])
        self.assertIn("Upload-Post is not configured", err_msg)
        self.assertFalse(col2.button.called)

    # =========================================================================
    # D. Post For Me não configurado => modal bloqueia
    # =========================================================================
    def test_d_post_for_me_unconfigured_blocks_publish(self):
        mock_st, col1, col2 = self._setup_mock_st()
        test_app_config = dict(
            config.app,
            upload_post_enabled=False,
            upload_post_platforms=["youtube"],
        )

        with patch.object(Main, "st", mock_st), \
             patch.object(config, "app", test_app_config), \
             patch("app.utils.utils.task_dir", return_value=self.test_dir), \
             patch("app.services.state.state.get_task", return_value={"video_subject": "Teste PFM", "videos": [self.video_file]}), \
             patch("app.services.youtube_publisher.get_youtube_publish_provider", return_value=youtube_publisher.PROVIDER_POST_FOR_ME), \
             patch("app.services.post_for_me.post_for_me_client.is_configured", return_value=False):

            Main._render_task_publish_dialog.__wrapped__(self.task_id)

        mock_st.error.assert_called_once()
        err_msg = str(mock_st.error.call_args[0][0])
        self.assertIn("Post for Me is not configured", err_msg)
        self.assertFalse(col2.button.called)

    # =========================================================================
    # E. Confirmação do provider legado chama publish_task sem platforms
    # =========================================================================
    def test_e_legacy_provider_confirmation_calls_publish_task_default(self):
        mock_st, col1, col2 = self._setup_mock_st()
        col2.button.return_value = True

        test_app_config = dict(
            config.app,
            upload_post_enabled=True,
            upload_post_api_key="key_ok",
            upload_post_username="user_ok",
            upload_post_platforms=["youtube"],
        )

        with patch.object(Main, "st", mock_st), \
             patch.object(config, "app", test_app_config), \
             patch("app.utils.utils.task_dir", return_value=self.test_dir), \
             patch("app.services.state.state.get_task", return_value={"video_subject": "Teste Legado", "videos": [self.video_file]}), \
             patch("app.services.youtube_publisher.get_youtube_publish_provider", return_value=youtube_publisher.PROVIDER_UPLOAD_POST), \
             patch("app.services.operator_console.is_primary_instance", return_value=True), \
             patch("app.services.task.publish_task", return_value=(True, "")) as mock_publish:

            Main._render_task_publish_dialog.__wrapped__(self.task_id)

        mock_publish.assert_called_once_with(self.task_id)


if __name__ == "__main__":
    unittest.main()
