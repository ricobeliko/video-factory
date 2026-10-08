# -*- coding: utf-8 -*-
"""
test/services/test_flow_playwright.py

Testes unitários direcionados para o driver de automação Playwright do Google Flow.
Valida contratos de isolamento, profile locking, autenticação, actionability e download.
"""

import os
import unittest
from unittest.mock import MagicMock, patch

from scripts.flow_playwright import (
    check_generate_actionable,
    check_login_state,
    download_generated_clip,
    fill_prompt,
    launch_flow_context,
    navigate_landing_to_studio,
    validate_clip_file,
)


class TestFlowPlaywright(unittest.TestCase):

    def test_validate_clip_file_missing_and_invalid(self):
        """Validação de clipe falha quando arquivo não existe ou é inválido."""
        res_missing = validate_clip_file("caminho/inexistente/video.mp4")
        self.assertFalse(res_missing["valid"])
        self.assertEqual(res_missing["error"], "FILE_NOT_FOUND")

        res_ext = validate_clip_file(__file__)
        self.assertFalse(res_ext["valid"])
        self.assertEqual(res_ext["error"], "NOT_MP4_EXTENSION")

    @patch("app.services.media_quality.probe_media")
    def test_validate_clip_file_valid(self, mock_probe):
        """Validação de clipe tem sucesso quando probe_media retorna streams válidos."""
        mock_probe.return_value = {
            "valid": True,
            "format_duration": 5.4,
            "video_streams": [{"codec_name": "h264"}],
        }
        with patch("os.path.exists", return_value=True), \
             patch("os.path.isfile", return_value=True), \
             patch("os.path.getsize", return_value=1024 * 1024):
            res = validate_clip_file("storage/test_video.mp4")
            self.assertTrue(res["valid"])
            self.assertEqual(res["duration"], 5.4)

    def test_launch_flow_context_locked_profile_fail_closed(self):
        """Se o perfil estiver bloqueado por outro Edge, retorna AWAITING_FLOW_EDGE_PROFILE_CLOSE."""
        mock_playwright = MagicMock()
        mock_playwright.chromium.launch_persistent_context.side_effect = Exception(
            "Failed to create a ProcessSingleton for your profile directory. Lock file can not be created! Error code: 32"
        )

        ctx, err = launch_flow_context(mock_playwright, user_data_dir="storage/test_profile")
        self.assertIsNone(ctx)
        self.assertEqual(err, "AWAITING_FLOW_EDGE_PROFILE_CLOSE")

    def test_check_login_state_redirect_to_accounts(self):
        """Detecta tela de login do Google e retorna AWAITING_INITIAL_HUMAN_LOGIN."""
        mock_page = MagicMock()
        mock_page.url = "https://accounts.google.com/signin/v2/identifier"

        status = check_login_state(mock_page)
        self.assertEqual(status, "AWAITING_INITIAL_HUMAN_LOGIN")

    def test_check_login_state_captcha_detected(self):
        """Detecta desafio de captcha e retorna BLOCKED_CAPTCHA."""
        mock_page = MagicMock()
        mock_page.url = "https://flow.google.com"
        mock_captcha = MagicMock()
        mock_captcha.count.return_value = 1
        mock_captcha.first.is_visible.return_value = True
        mock_page.locator.return_value = mock_captcha

        status = check_login_state(mock_page)
        self.assertEqual(status, "BLOCKED_CAPTCHA")

    def test_check_login_state_authenticated(self):
        """Detecta sessão válida no Flow e retorna AUTHENTICATED."""
        mock_page = MagicMock()
        mock_page.url = "https://flow.google.com"
        mock_captcha = MagicMock()
        mock_captcha.count.return_value = 0
        mock_page.locator.return_value = mock_captcha

        status = check_login_state(mock_page)
        self.assertEqual(status, "AUTHENTICATED")

    def test_navigate_landing_to_studio_already_in_studio(self):
        """Se já estiver no Studio (/project/), não clica novamente."""
        mock_page = MagicMock()
        mock_page.url = "https://flow.google.com/project/abc-123"

        res_url = navigate_landing_to_studio(mock_page)
        self.assertEqual(res_url, "https://flow.google.com/project/abc-123")
        mock_page.get_by_role.assert_not_called()

    def test_navigate_landing_to_studio_from_landing(self):
        """Na Landing, localiza botão 'Novo projeto', clica uma vez e aguarda URL /project/."""
        mock_page = MagicMock()
        mock_page.url = "https://flow.google.com"
        mock_btn = MagicMock()
        mock_btn.count.return_value = 1
        mock_page.get_by_role.return_value = mock_btn

        with patch("scripts.flow_playwright.expect") as mock_expect:
            navigate_landing_to_studio(mock_page)
            mock_btn.click.assert_called_once()
            mock_page.wait_for_url.assert_called_once()
            mock_expect.assert_called()

    def test_fill_prompt_prosemirror(self):
        """Preenche prompt no ProseMirror via editor.fill() nativo."""
        mock_page = MagicMock()
        mock_editor = MagicMock()
        mock_editor.count.return_value = 1
        mock_page.locator.return_value = mock_editor

        with patch("scripts.flow_playwright.expect") as mock_expect:
            fill_prompt(mock_page, "Um vídeo cinematográfico de nebulosa espacial")
            mock_editor.fill.assert_called_once_with("Um vídeo cinematográfico de nebulosa espacial")
            mock_expect.assert_called()

    def test_check_generate_actionable_trial_true(self):
        """Validação de actionability usa click(trial=True) sem disparar clique real."""
        mock_btn = MagicMock()
        res = check_generate_actionable(mock_btn)
        self.assertTrue(res)
        mock_btn.click.assert_called_once_with(trial=True, timeout=30000)

    def test_download_generated_clip_expect_download(self):
        """Download utiliza expect_download nativo e salva com download.save_as."""
        mock_page = MagicMock()
        mock_btn = MagicMock()
        mock_btn.count.return_value = 1
        mock_btn.is_visible.return_value = True
        mock_page.locator.return_value.first = mock_btn

        mock_download = MagicMock()
        mock_download.suggested_filename = "flow_video.mp4"

        mock_download_info = MagicMock()
        mock_download_info.value = mock_download

        mock_page.expect_download.return_value.__enter__.return_value = mock_download_info
        mock_page.expect_download.return_value.__exit__.return_value = None

        ok, err = download_generated_clip(mock_page, "storage/output.mp4")
        self.assertTrue(ok)
        self.assertIsNone(err)
        mock_btn.click.assert_called_once()
        mock_download.save_as.assert_called_once_with("storage/output.mp4")


if __name__ == "__main__":
    unittest.main()
