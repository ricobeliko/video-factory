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
    capture_tile_baseline,
    check_generate_actionable,
    check_login_state,
    check_pending_credit_approval,
    download_generated_clip,
    execute_credit_approval,
    extract_tile_identifier_from_src,
    fill_prompt,
    find_single_approve_button,
    launch_flow_context,
    navigate_landing_to_studio,
    validate_clip_file,
    wait_for_generation_complete,
    wait_for_generation_started,
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
        mock_tile = MagicMock()
        mock_tile.count.return_value = 1
        mock_btn = MagicMock()
        mock_btn.count.return_value = 1
        mock_btn.is_visible.return_value = True
        mock_tile.locator.return_value = mock_btn

        mock_download = MagicMock()
        mock_download.suggested_filename = "flow_video.mp4"

        mock_download_info = MagicMock()
        mock_download_info.value = mock_download

        mock_page.expect_download.return_value.__enter__.return_value = mock_download_info
        mock_page.expect_download.return_value.__exit__.return_value = None

        with patch("scripts.flow_playwright.expect"):
            ok, err = download_generated_clip(mock_page, "storage/output.mp4", tile_locator=mock_tile)
            self.assertTrue(ok)
            self.assertIsNone(err)
            mock_btn.click.assert_called_once()
            mock_download.save_as.assert_called_once_with("storage/output.mp4")

    def test_approval_present_does_not_mean_generation_started(self):
        """1. A presença de Aprovar significa apenas aprovação requerida, NÃO geração iniciada."""
        mock_page = MagicMock()
        # Simula wait_for_function falhando porque há botão aprovar pendente
        mock_page.wait_for_function.side_effect = Exception("Timeout: approval pending")
        started = wait_for_generation_started(mock_page, timeout_ms=100)
        self.assertFalse(started)

    def test_find_single_approve_button_matches_aprovar(self):
        """2. Aprovar único é selecionado estritamente por regex ^(Aprovar|Approve)$."""
        mock_page = MagicMock()
        find_single_approve_button(mock_page)
        self.assertEqual(mock_page.get_by_role.call_count, 2)
        args, kwargs = mock_page.get_by_role.call_args_list[0]
        self.assertEqual(args[0], "button")
        pattern = kwargs["name"]
        self.assertTrue(pattern.match("Aprovar"))
        self.assertTrue(pattern.match("Approve"))
        self.assertTrue(pattern.match("aprovar"))

    def test_always_approve_never_selected(self):
        """3. Sempre aprovar NUNCA é selecionado pelo locator de aprovação única."""
        mock_page = MagicMock()
        find_single_approve_button(mock_page)
        args, kwargs = mock_page.get_by_role.call_args_list[0]
        pattern = kwargs["name"]
        self.assertIsNone(pattern.match("Sempre aprovar"))
        self.assertIsNone(pattern.match("Always approve"))
        self.assertIsNone(pattern.match("sempre aprovar"))

    def test_execute_credit_approval_click_and_confirmation(self):
        """5. Approval click dispara exatamente 1 clique e confirma desaparecimento do botão."""
        mock_page = MagicMock()
        mock_btn = MagicMock()
        mock_btn.count.return_value = 1
        mock_page.get_by_role.return_value.or_.return_value = mock_btn

        with patch("scripts.flow_playwright.expect") as mock_expect:
            res = execute_credit_approval(mock_page, timeout_confirm_ms=1000)
            self.assertTrue(res["required"])
            self.assertEqual(res["click_count"], 1)
            self.assertTrue(res["confirmed"])
            self.assertFalse(res["always_approve_clicked"])
            mock_btn.click.assert_called_once()
            mock_expect.assert_called_once_with(mock_btn)

    def test_execute_credit_approval_timeout_fails_closed_no_retry(self):
        """6. Approval timeout falha fechado com CREDIT_APPROVAL_NOT_CONFIRMED e sem segundo clique."""
        mock_page = MagicMock()
        mock_btn = MagicMock()
        mock_btn.count.return_value = 1
        mock_page.get_by_role.return_value.or_.return_value = mock_btn

        with patch("scripts.flow_playwright.expect", side_effect=Exception("Timeout waiting for hidden")):
            res = execute_credit_approval(mock_page, timeout_confirm_ms=100)
            self.assertFalse(res["confirmed"])
            self.assertEqual(res["error"], "CREDIT_APPROVAL_NOT_CONFIRMED")
            self.assertEqual(res["click_count"], 1)
            # Garantia mandatória: disparado estritamente UMA vez
            mock_btn.click.assert_called_once()

    def test_check_pending_approval_found(self):
        """4. Approval pendente no início é detectado com contagem e custo."""
        mock_page = MagicMock()
        mock_btn = MagicMock()
        mock_btn.count.return_value = 1
        mock_btn.first.is_visible.return_value = True
        mock_page.get_by_role.return_value.or_.return_value = mock_btn
        mock_page.locator.return_value.inner_text.return_value = "custa 15 créditos para gerar"

        is_pending, count, cost = check_pending_credit_approval(mock_page)
        self.assertTrue(is_pending)
        self.assertEqual(count, 1)
        self.assertEqual(cost, 15)

    def test_old_result_cannot_confirm_new_job_when_baseline_has_same_tile(self):
        """1. Resultado antigo no baseline não confirma resultado novo (timeout -> fail-closed)."""
        mock_page = MagicMock()
        mock_page.wait_for_function.side_effect = Exception("Timeout waiting for new tile")
        ok, tile_loc, err = wait_for_generation_complete(
            mock_page, baseline_ids={"token_cena_01"}, timeout_sec=1
        )
        self.assertFalse(ok)
        self.assertIsNone(tile_loc)
        self.assertEqual(err, "GENERATION_RESULT_NOT_FOUND")

    def test_baseline_with_same_tile_not_complete(self):
        """2. Baseline com 1 tile + mesmo tile presente no DOM => não completo."""
        mock_page = MagicMock()
        mock_page.wait_for_function.side_effect = Exception("Timeout: only existing tile in DOM")
        ok, tile_loc, err = wait_for_generation_complete(
            mock_page, baseline_ids={"asb_existing_scene_01"}, timeout_sec=1
        )
        self.assertFalse(ok)
        self.assertIsNone(tile_loc)
        self.assertEqual(err, "GENERATION_RESULT_NOT_FOUND")

    def test_baseline_with_one_new_tile_identifies_new_tile(self):
        """3. Baseline com 1 tile existente + exatamente 1 novo tile identifica e retorna o novo tile."""
        mock_page = MagicMock()
        mock_wait_res = MagicMock()
        mock_wait_res.json_value.return_value = {"status": "READY", "newId": "token_cena_02"}
        mock_page.wait_for_function.return_value = mock_wait_res

        mock_tile_loc = MagicMock()
        mock_page.locator.return_value.filter.return_value = mock_tile_loc

        with patch("scripts.flow_playwright.expect") as mock_expect:
            ok, tile_loc, err = wait_for_generation_complete(
                mock_page, baseline_ids={"token_cena_01"}, timeout_sec=10
            )
            self.assertTrue(ok)
            self.assertEqual(tile_loc, mock_tile_loc)
            self.assertIsNone(err)
            mock_expect.assert_called_once_with(mock_tile_loc)

    def test_multiple_new_tiles_fails_closed_ambiguous(self):
        """4. Mais de 1 novo tile detectado simultaneamente falha fechado com AMBIGUOUS_GENERATION_RESULTS."""
        mock_page = MagicMock()
        mock_wait_res = MagicMock()
        mock_wait_res.json_value.return_value = {"status": "AMBIGUOUS", "count": 2}
        mock_page.wait_for_function.return_value = mock_wait_res

        ok, tile_loc, err = wait_for_generation_complete(
            mock_page, baseline_ids={"token_cena_01"}, timeout_sec=10
        )
        self.assertFalse(ok)
        self.assertIsNone(tile_loc)
        self.assertEqual(err, "AMBIGUOUS_GENERATION_RESULTS")

    def test_download_requires_or_receives_specific_tile(self):
        """5. Download recebe tile_locator específico e busca elementos dentro dele."""
        mock_page = MagicMock()
        mock_tile = MagicMock()
        mock_tile.count.return_value = 1

        mock_dl_btn = MagicMock()
        mock_dl_btn.count.return_value = 1
        mock_dl_btn.is_visible.return_value = True
        mock_tile.locator.return_value = mock_dl_btn

        mock_download = MagicMock()
        mock_download.suggested_filename = "clip.mp4"
        mock_download_info = MagicMock()
        mock_download_info.value = mock_download
        mock_page.expect_download.return_value.__enter__.return_value = mock_download_info
        mock_page.expect_download.return_value.__exit__.return_value = None

        with patch("scripts.flow_playwright.expect"):
            ok, err = download_generated_clip(mock_page, "storage/output.mp4", tile_locator=mock_tile)
            self.assertTrue(ok)
            self.assertIsNone(err)
            mock_tile.hover.assert_called_once()
            mock_dl_btn.click.assert_called_once()
            mock_download.save_as.assert_called_once_with("storage/output.mp4")

    def test_two_tiles_does_not_arbitrarily_pick_first(self):
        """6. Se houver 2 tiles existentes e nenhum tile_locator específico, download bloqueia fail-closed sem usar .first."""
        mock_page = MagicMock()
        mock_tiles = MagicMock()
        mock_tiles.count.return_value = 2
        mock_page.locator.return_value = mock_tiles

        ok, err = download_generated_clip(mock_page, "storage/output.mp4", tile_locator=None)
        self.assertFalse(ok)
        self.assertEqual(err, "AMBIGUOUS_TILE_TARGET_COUNT_2")
        mock_tiles.hover.assert_not_called()

    def test_ambiguous_tile_locator_blocks(self):
        """7. Se tile_locator não passar na asserção de unicidade (count != 1), download bloqueia."""
        mock_page = MagicMock()
        mock_tile = MagicMock()
        with patch("scripts.flow_playwright.expect", side_effect=Exception("Locator count != 1")):
            ok, err = download_generated_clip(mock_page, "storage/output.mp4", tile_locator=mock_tile)
            self.assertFalse(ok)
            self.assertEqual(err, "AMBIGUOUS_TILE_TARGET")

    def test_expect_download_remains_used(self):
        """8. Verifica que o context manager expect_download nativo é ativado durante o download."""
        mock_page = MagicMock()
        mock_tile = MagicMock()
        mock_tile.count.return_value = 1
        mock_dl_btn = MagicMock()
        mock_dl_btn.count.return_value = 1
        mock_dl_btn.is_visible.return_value = True
        mock_tile.locator.return_value = mock_dl_btn

        mock_download = MagicMock()
        mock_download.suggested_filename = "test.mp4"
        mock_download_info = MagicMock()
        mock_download_info.value = mock_download
        mock_page.expect_download.return_value.__enter__.return_value = mock_download_info
        mock_page.expect_download.return_value.__exit__.return_value = None

        with patch("scripts.flow_playwright.expect"):
            download_generated_clip(mock_page, "storage/out.mp4", tile_locator=mock_tile)
            mock_page.expect_download.assert_called_once()

    def test_playwright_pinned_in_dependencies(self):
        """9. Verifica que playwright==1.63.0 está fixado em pyproject.toml e requirements.txt."""
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        pyproject_path = os.path.join(root_dir, "pyproject.toml")
        req_path = os.path.join(root_dir, "requirements.txt")

        with open(pyproject_path, "r", encoding="utf-8") as f:
            pyproject_content = f.read()
        self.assertIn('"playwright==1.63.0"', pyproject_content)

        with open(req_path, "r", encoding="utf-8") as f:
            req_content = f.read()
        self.assertIn("playwright==1.63.0", req_content)

    def test_uv_lock_contains_playwright_pinned(self):
        """10. Verifica que uv.lock contém playwright 1.63.0."""
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        uv_lock_path = os.path.join(root_dir, "uv.lock")

        with open(uv_lock_path, "r", encoding="utf-8") as f:
            uv_lock_content = f.read()
        self.assertIn('name = "playwright"', uv_lock_content)
        self.assertIn('version = "1.63.0"', uv_lock_content)


if __name__ == "__main__":
    unittest.main()
