# -*- coding: utf-8 -*-
"""
test/services/test_flow_playwright.py

Testes unitários direcionados para o driver de automação Playwright do Google Flow.
Valida contratos de isolamento, profile locking, autenticação, actionability e download.
"""

import hashlib
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from scripts.flow_playwright import (
    GENERATION_COMPLETE_JS,
    check_generate_actionable,
    check_login_state,
    check_pending_credit_approval,
    _persist_download,
    download_generated_clip,
    ensure_studio_surface,
    ensure_video_generation_mode,
    execute_credit_approval,
    extract_tile_identifier_from_src,
    fill_prompt,
    find_single_approve_button,
    generate_flow_scene,
    launch_flow_context,
    navigate_landing_to_studio,
    resolve_flow_headless,
    run_playwright_flow_poc,
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

    def test_check_login_state_public_about_landing(self):
        """1. Landing pública (/about) retorna AWAITING_INITIAL_HUMAN_LOGIN (fail-closed)."""
        mock_page = MagicMock()
        mock_page.url = "https://flow.google.com/about"

        status = check_login_state(mock_page)
        self.assertEqual(status, "AWAITING_INITIAL_HUMAN_LOGIN")

    def test_check_login_state_public_cta_detected(self):
        """2. Landing pública com CTA 'Crie com o Google Flow' retorna AWAITING_INITIAL_HUMAN_LOGIN."""
        mock_page = MagicMock()
        mock_page.url = "https://flow.google.com"
        mock_cta = MagicMock()
        mock_cta.count.return_value = 1
        mock_cta.first.is_visible.return_value = True
        mock_page.get_by_text.return_value = mock_cta

        status = check_login_state(mock_page)
        self.assertEqual(status, "AWAITING_INITIAL_HUMAN_LOGIN")

    def test_check_login_state_redirect_to_accounts(self):
        """3. Redirecionamento para accounts.google.com retorna AWAITING_INITIAL_HUMAN_LOGIN."""
        mock_page = MagicMock()
        mock_page.url = "https://accounts.google.com/signin/v2/identifier"

        status = check_login_state(mock_page)
        self.assertEqual(status, "AWAITING_INITIAL_HUMAN_LOGIN")

    def test_check_login_state_captcha_detected(self):
        """4. Desafio de captcha presente retorna BLOCKED_CAPTCHA."""
        mock_page = MagicMock()
        mock_page.url = "https://flow.google.com"
        mock_captcha = MagicMock()
        mock_captcha.count.return_value = 1
        mock_captcha.first.is_visible.return_value = True
        mock_page.locator.return_value = mock_captcha

        status = check_login_state(mock_page)
        self.assertEqual(status, "BLOCKED_CAPTCHA")

    def test_check_login_state_authenticated_project_url(self):
        """5. URL contendo /project/ é evidência positiva e retorna AUTHENTICATED."""
        mock_page = MagicMock()
        mock_page.url = "https://flow.google.com/project/abc-123"

        status = check_login_state(mock_page)
        self.assertEqual(status, "AUTHENTICATED")

    def test_check_login_state_authenticated_with_new_project_button(self):
        """6. Landing com evidência inequívoca do botão 'Novo projeto' retorna AUTHENTICATED."""
        mock_page = MagicMock()
        mock_page.url = "https://flow.google.com"
        mock_btn = MagicMock()
        mock_btn.count.return_value = 1
        mock_btn.first.is_visible.return_value = True
        mock_page.get_by_role.return_value = mock_btn

        status = check_login_state(mock_page)
        self.assertEqual(status, "AUTHENTICATED")

    def test_check_login_state_landing_without_positive_evidence_fails_closed(self):
        """7. Landing sem evidência positiva de autenticação falha fechada para AWAITING_INITIAL_HUMAN_LOGIN."""
        mock_page = MagicMock()
        mock_page.url = "https://flow.google.com"
        mock_btn = MagicMock()
        mock_btn.count.return_value = 0
        mock_page.get_by_role.return_value = mock_btn

        status = check_login_state(mock_page)
        self.assertNotEqual(status, "AUTHENTICATED")
        self.assertEqual(status, "AWAITING_INITIAL_HUMAN_LOGIN")

    def test_check_login_state_authenticated(self):
        """Compatibilidade: sessão no Flow com botão 'Novo projeto' visível retorna AUTHENTICATED."""
        mock_page = MagicMock()
        mock_page.url = "https://flow.google.com"
        mock_btn = MagicMock()
        mock_btn.count.return_value = 1
        mock_btn.first.is_visible.return_value = True
        mock_page.get_by_role.return_value = mock_btn

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
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_file = os.path.join(tmp_dir, "output.mp4")
            mock_page = MagicMock()
            mock_tile = MagicMock()
            mock_tile.count.return_value = 1
            mock_btn = MagicMock()
            mock_btn.count.return_value = 1
            mock_btn.is_visible.return_value = True
            mock_tile.locator.return_value = mock_btn

            mock_download = MagicMock()
            mock_download.suggested_filename = "flow_video.mp4"
            def _fake_save(p):
                with open(p, "wb") as f:
                    f.write(b"flow_video_bytes")
            mock_download.save_as.side_effect = _fake_save

            mock_download_info = MagicMock()
            mock_download_info.value = mock_download

            mock_page.expect_download.return_value.__enter__.return_value = mock_download_info
            mock_page.expect_download.return_value.__exit__.return_value = None

            with patch("scripts.flow_playwright.expect"), \
                 patch("scripts.flow_playwright.validate_clip_file", return_value={"valid": True, "duration": 8.0}):
                ok, err = download_generated_clip(mock_page, out_file, tile_locator=mock_tile)
                self.assertTrue(ok)
                self.assertIsNone(err)
                mock_btn.click.assert_called_once()
                mock_download.save_as.assert_called_once_with(out_file)

    def test_approval_present_does_not_mean_generation_started(self):
        """1. A presença de Aprovar significa apenas aprovação requerida, NÃO geração iniciada."""
        mock_page = MagicMock()
        # Simula wait_for_function falhando porque há botão aprovar pendente
        mock_page.wait_for_function.side_effect = Exception("Timeout: approval pending")
        started = wait_for_generation_started(
            mock_page,
            generation_type_confirmed=True,
            generation_type="VIDEO",
            timeout_ms=100,
        )
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

    def test_find_single_approve_button_filters_read_only_and_aria_disabled(self):
        """3b. Garante que opções respondidas (read-only / aria-disabled) são filtradas pelo locator."""
        mock_page = MagicMock()
        mock_filtered = MagicMock()
        mock_page.get_by_role.return_value.or_.return_value.filter.return_value = mock_filtered

        res = find_single_approve_button(mock_page)
        self.assertEqual(res, mock_filtered)
        mock_page.locator.assert_called_with(".read-only, [aria-disabled='true']")
        mock_page.get_by_role.return_value.or_.return_value.filter.assert_called_once()

    def test_execute_credit_approval_click_and_confirmation(self):
        """5. Approval click dispara exatamente 1 clique e confirma desaparecimento do botão."""
        mock_page = MagicMock()
        mock_btn = MagicMock()
        mock_btn.count.return_value = 1
        mock_page.get_by_role.return_value.or_.return_value.filter.return_value = mock_btn

        with patch("scripts.flow_playwright.expect") as mock_expect, \
             patch("scripts.flow_playwright.extract_credit_cost", return_value=15):
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
        mock_page.get_by_role.return_value.or_.return_value.filter.return_value = mock_btn

        with patch("scripts.flow_playwright.expect", side_effect=Exception("Timeout waiting for hidden")), \
             patch("scripts.flow_playwright.extract_credit_cost", return_value=15):
            res = execute_credit_approval(mock_page, timeout_confirm_ms=100)
            self.assertFalse(res["confirmed"])
            self.assertEqual(res["error"], "CREDIT_APPROVAL_NOT_CONFIRMED")
            self.assertEqual(res["click_count"], 1)
            # Garantia mandatória: disparado estritamente UMA vez
            mock_btn.click.assert_called_once()

    def test_unknown_credit_cost_blocks_approval(self):
        """1. Custo de crédito desconhecido (None) bloqueia aprovação fail-closed com zero cliques."""
        mock_page = MagicMock()
        mock_btn = MagicMock()
        mock_btn.count.return_value = 1
        mock_page.get_by_role.return_value.or_.return_value.filter.return_value = mock_btn

        with patch("scripts.flow_playwright.extract_credit_cost", return_value=None):
            res = execute_credit_approval(mock_page)
            self.assertEqual(res["error"], "CREDIT_COST_UNKNOWN")
            self.assertEqual(res["click_count"], 0)
            self.assertFalse(res["confirmed"])
            mock_btn.click.assert_not_called()

    def test_explicit_policy_refund_maps_terminal(self):
        """2. Recusa explícita de política com reembolso confirmado mapeia para FLOW_CONTENT_POLICY_BLOCKED, créditos=0 e needs_recovery=False."""
        raw_res = {
            "status": "FLOW_CONTENT_POLICY_BLOCKED",
            "content_policy_blocked": True,
            "policy_refund_confirmed": True,
            "policy_message": "Falha: Esse comando pode violar nossas políticas. You will be refunded for this generation.",
            "error": "FLOW_POLICY_FAILURE",
            "generation_start_confirmed": True,
            "credit_cost": 15,
        }
        with patch("scripts.flow_playwright.run_playwright_flow_poc", return_value=raw_res), \
             patch("os.path.exists", return_value=True), \
             patch("builtins.open", unittest.mock.mock_open(read_data=json.dumps({
                 "scenes": [{"scene_index": 1, "prompt_en": "test", "expected_clip": "clip.mp4"}]
             }))):
            res = generate_flow_scene("dummy_manifest.json", scene_index=1)
            self.assertEqual(res.status, "FLOW_CONTENT_POLICY_BLOCKED")
            self.assertEqual(res.credits_consumed, 0)
            self.assertFalse(res.details.get("needs_recovery"))
            self.assertTrue(res.details.get("content_policy_blocked"))
            self.assertTrue(res.details.get("policy_refund_confirmed"))

    def test_policy_block_without_refund_stays_recovery(self):
        """3. Bloqueio de política sem confirmação segura de reembolso mantém comportamento conservador FLOW_GENERATION_NEEDS_RECOVERY."""
        raw_res = {
            "status": "FLOW_GENERATION_NEEDS_RECOVERY",
            "content_policy_blocked": True,
            "policy_refund_confirmed": False,
            "policy_message": "Falha: Esse comando pode violar políticas.",
            "error": "FLOW_POLICY_FAILURE",
            "generation_start_confirmed": True,
            "credit_cost": 15,
        }
        with patch("scripts.flow_playwright.run_playwright_flow_poc", return_value=raw_res), \
             patch("os.path.exists", return_value=True), \
             patch("builtins.open", unittest.mock.mock_open(read_data=json.dumps({
                 "scenes": [{"scene_index": 1, "prompt_en": "test", "expected_clip": "clip.mp4"}]
             }))):
            res = generate_flow_scene("dummy_manifest.json", scene_index=1)
            self.assertEqual(res.status, "FLOW_GENERATION_NEEDS_RECOVERY")
            self.assertEqual(res.credits_consumed, 15)
            self.assertTrue(res.details.get("needs_recovery"))

    def test_check_pending_approval_found(self):
        """4. Approval pendente no início é detectado com contagem e custo."""
        mock_page = MagicMock()
        mock_btn = MagicMock()
        mock_btn.count.return_value = 1
        mock_btn.is_visible.return_value = True
        mock_page.get_by_role.return_value.or_.return_value.filter.return_value = mock_btn
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
        mock_tiles = MagicMock()
        mock_tiles.count.return_value = 2

        mock_t0 = MagicMock()
        mock_img0 = MagicMock()
        mock_img0.count.return_value = 1
        mock_img0.get_attribute.return_value = "https://flow.google.com/asb/NEW_TOKEN_SCENE_02"
        mock_t0.locator.side_effect = lambda sel: mock_img0 if "img" in sel else MagicMock(count=lambda: 0)

        mock_t1 = MagicMock()
        mock_img1 = MagicMock()
        mock_img1.count.return_value = 1
        mock_img1.get_attribute.return_value = "https://flow.google.com/asb/OLD_TOKEN_SCENE_01"
        mock_t1.locator.side_effect = lambda sel: mock_img1 if "img" in sel else MagicMock(count=lambda: 0)

        mock_tiles.nth.side_effect = [mock_t0, mock_t1]
        mock_page.locator.return_value = mock_tiles

        base_id_01 = extract_tile_identifier_from_src("https://flow.google.com/asb/OLD_TOKEN_SCENE_01")

        with patch("scripts.flow_playwright.expect") as mock_expect:
            ok, tile_loc, err = wait_for_generation_complete(
                mock_page, baseline_ids={base_id_01}, timeout_sec=10
            )
            self.assertTrue(ok)
            self.assertEqual(tile_loc, mock_t0)
            self.assertIsNone(err)
            mock_expect.assert_called_once_with(mock_t0)

    def test_multiple_new_tiles_fails_closed_ambiguous(self):
        """4. Mais de 1 novo tile detectado simultaneamente falha fechado com AMBIGUOUS_GENERATION_RESULTS."""
        mock_page = MagicMock()
        mock_tiles = MagicMock()
        mock_tiles.count.return_value = 2

        mock_t0 = MagicMock()
        mock_img0 = MagicMock()
        mock_img0.count.return_value = 1
        mock_img0.get_attribute.return_value = "https://flow.google.com/asb/NEW_TOKEN_A"
        mock_t0.locator.side_effect = lambda sel: mock_img0 if "img" in sel else MagicMock(count=lambda: 0)

        mock_t1 = MagicMock()
        mock_img1 = MagicMock()
        mock_img1.count.return_value = 1
        mock_img1.get_attribute.return_value = "https://flow.google.com/asb/NEW_TOKEN_B"
        mock_t1.locator.side_effect = lambda sel: mock_img1 if "img" in sel else MagicMock(count=lambda: 0)

        mock_tiles.nth.side_effect = [mock_t0, mock_t1]
        mock_page.locator.return_value = mock_tiles

        ok, tile_loc, err = wait_for_generation_complete(
            mock_page, baseline_ids={"token_outra_cena"}, timeout_sec=10
        )
        self.assertFalse(ok)
        self.assertIsNone(tile_loc)
        self.assertEqual(err, "AMBIGUOUS_GENERATION_RESULTS")

    def test_old_ready_tile_does_not_complete_new_placeholder(self):
        """Um tile antigo do baseline pronto NÃO completa um novo placeholder; completa apenas quando o novo fica pronto."""
        # 1. Validação direta da lógica JS (readyCount > baseCount)
        js_test = f"""
        const func = {GENERATION_COMPLETE_JS};
        // Estado A: baseline=1, tile 0 pronto, tile 1 placeholder não pronto
        let tilesA = [
            {{ querySelector: (sel) => (sel.includes('img') ? {{}} : null), innerText: '' }},
            {{ querySelector: (sel) => null, innerText: '' }}
        ];
        global.document = {{
            querySelectorAll: () => tilesA
        }};
        const resA = func(1);
        if (resA !== false) {{
            process.stderr.write("FAILED_A: expected false but got " + resA);
            process.exit(1);
        }}

        // Estado B: baseline=1, tile 0 pronto E tile 1 pronto
        let tilesB = [
            {{ querySelector: (sel) => (sel.includes('img') ? {{}} : null), innerText: '' }},
            {{ querySelector: (sel) => (sel.includes('img') ? {{}} : null), innerText: '' }}
        ];
        global.document = {{
            querySelectorAll: () => tilesB
        }};
        const resB = func(1);
        if (resB !== 'COMPLETED') {{
            process.stderr.write("FAILED_B: expected COMPLETED but got " + resB);
            process.exit(2);
        }}
        process.stdout.write("OK");
        """
        import subprocess
        proc = subprocess.run(["node", "-e", js_test], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, f"JS readiness failed: {proc.stderr}")
        self.assertEqual(proc.stdout.strip(), "OK")

        # 2. Validação no Python em wait_for_generation_complete
        mock_page = MagicMock()
        mock_tiles = MagicMock()
        mock_tiles.count.return_value = 2

        # Tile 0: antigo da cena 1 (já no baseline)
        mock_t0 = MagicMock()
        mock_img0 = MagicMock()
        mock_img0.count.return_value = 1
        mock_img0.get_attribute.return_value = "https://flow.google.com/asb/OLD_TOKEN_SCENE_01"
        mock_t0.locator.side_effect = lambda sel: mock_img0 if "img" in sel else MagicMock(count=lambda: 0)

        # Tile 1: novo da cena 2 (novo resultado)
        mock_t1 = MagicMock()
        mock_img1 = MagicMock()
        mock_img1.count.return_value = 1
        mock_img1.get_attribute.return_value = "https://flow.google.com/asb/NEW_TOKEN_SCENE_02"
        mock_t1.locator.side_effect = lambda sel: mock_img1 if "img" in sel else MagicMock(count=lambda: 0)

        mock_tiles.nth.side_effect = lambda idx: mock_t0 if idx == 0 else mock_t1
        mock_page.locator.return_value = mock_tiles

        base_id_01 = extract_tile_identifier_from_src("https://flow.google.com/asb/OLD_TOKEN_SCENE_01")

        with patch("scripts.flow_playwright.expect") as mock_expect:
            ok, tile_loc, err = wait_for_generation_complete(
                mock_page, baseline_ids={base_id_01}, timeout_sec=10
            )
            self.assertTrue(ok)
            self.assertEqual(tile_loc, mock_t1)
            self.assertIsNone(err)
            mock_expect.assert_called_once_with(mock_t1)

    def test_download_requires_or_receives_specific_tile(self):
        """5. Download recebe tile_locator específico e busca elementos dentro dele."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_file = os.path.join(tmp_dir, "output.mp4")
            mock_page = MagicMock()
            mock_tile = MagicMock()
            mock_tile.count.return_value = 1

            mock_dl_btn = MagicMock()
            mock_dl_btn.count.return_value = 1
            mock_dl_btn.is_visible.return_value = True
            mock_tile.locator.return_value = mock_dl_btn

            mock_download = MagicMock()
            mock_download.suggested_filename = "clip.mp4"
            def _fake_save(p):
                with open(p, "wb") as f:
                    f.write(b"clip_bytes")
            mock_download.save_as.side_effect = _fake_save

            mock_download_info = MagicMock()
            mock_download_info.value = mock_download
            mock_page.expect_download.return_value.__enter__.return_value = mock_download_info
            mock_page.expect_download.return_value.__exit__.return_value = None

            with patch("scripts.flow_playwright.expect"), \
                 patch("scripts.flow_playwright.validate_clip_file", return_value={"valid": True, "duration": 8.0}):
                ok, err = download_generated_clip(mock_page, out_file, tile_locator=mock_tile)
                self.assertTrue(ok)
                self.assertIsNone(err)
                mock_tile.hover.assert_called_once()
                mock_dl_btn.click.assert_called_once()
                mock_download.save_as.assert_called_once_with(out_file)

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

    def test_asb_full_token_generates_stable_sha256(self):
        """11. ASB full token gera identificador estável com prefixo asbsha256: e hash correto."""
        token = "SAMPLE_ASB_FULL_TOKEN_123456789"
        url = f"https://flow.google.com/asb/{token}?param=xyz"
        expected_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        expected_id = f"asbsha256:{expected_digest}"

        ident = extract_tile_identifier_from_src(url)
        self.assertEqual(ident, expected_id)

    def test_different_tokens_produce_different_hashes(self):
        """12. Tokens ASB diferentes geram hashes SHA-256 distintos."""
        url_a = "https://flow.google.com/asb/TOKEN_A_FIRST_VIDEO"
        url_b = "https://flow.google.com/asb/TOKEN_B_SECOND_VIDEO"
        ident_a = extract_tile_identifier_from_src(url_a)
        ident_b = extract_tile_identifier_from_src(url_b)
        self.assertNotEqual(ident_a, ident_b)

    def test_raw_token_does_not_appear_in_identifier(self):
        """13. O token ASB cru NUNCA aparece no identificador seguro gerado."""
        raw_secret_token = "SECRET_SUPER_TOKEN_NEVER_LOGGED"
        url = f"https://flow.google.com/asb/{raw_secret_token}"
        ident = extract_tile_identifier_from_src(url)
        self.assertNotIn(raw_secret_token, ident)
        self.assertTrue(ident.startswith("asbsha256:"))

    def test_project_url_provided_does_not_click_novo_projeto(self):
        """14. Quando project_url é fornecida, navega diretamente e NÃO clica em 'Novo projeto'."""
        mock_page = MagicMock()
        mock_page.url = "https://flow.google.com"
        target_url = "https://flow.google.com/project/ca11d34d-0f59-44cb-ad45-371b62aa223d"

        with patch("scripts.flow_playwright.expect") as mock_expect:
            res_url = ensure_studio_surface(mock_page, project_url=target_url)
            self.assertEqual(res_url, target_url)
            mock_page.goto.assert_called_once_with(target_url)
            mock_page.wait_for_url.assert_called_once()
            # Botão 'Novo projeto' NUNCA deve ser buscado/clicado
            mock_page.get_by_role.assert_not_called()
            mock_expect.assert_called()

    def test_scene_01_not_destination_of_scene_02_download(self):
        """15. Cena 01 não pode ser destino do download da Cena 02."""
        # Garante que o caminho canônico para cena 2 é flow_scene_02.mp4
        manifest_path = "storage/manual_media/flow_web_poc/manifest.json"
        if os.path.exists(manifest_path):
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
        else:
            manifest_data = {
                "scenes": [
                    {"scene_index": 1, "expected_clip": "flow_scene_01.mp4"},
                    {"scene_index": 2, "expected_clip": "flow_scene_02.mp4"},
                ]
            }
        scene_02 = next((s for s in manifest_data["scenes"] if s["scene_index"] == 2), None)
        self.assertIsNotNone(scene_02)
        self.assertEqual(scene_02["expected_clip"], "flow_scene_02.mp4")
        self.assertNotEqual(scene_02["expected_clip"], "flow_scene_01.mp4")

    def test_ensure_video_generation_mode_already_video(self):
        """A. already_video: confirma Video e zero cliques no seletor."""
        mock_page = MagicMock()
        mock_close = MagicMock()
        mock_close.count.return_value = 0
        mock_close.first.is_visible.return_value = False
        mock_page.locator.return_value.filter.return_value = mock_close

        mock_trigger = MagicMock()
        mock_trigger.count.return_value = 1
        mock_trigger.first = mock_trigger
        mock_trigger.inner_text.return_value = "Vídeo · 720p · 8s crop_9_16 x1"
        mock_page.get_by_role.return_value = mock_trigger

        res = ensure_video_generation_mode(mock_page)
        self.assertTrue(res["confirmed"])
        self.assertFalse(res["changed"])
        self.assertEqual(res["generation_type"], "VIDEO")
        self.assertEqual(res["aspect_ratio"], "9:16")
        self.assertEqual(res["output_count"], 1)
        mock_trigger.click.assert_not_called()

    def test_ensure_video_generation_mode_image_to_video(self):
        """B. image_to_video: abre seletor, escolhe Vídeo exatamente 1 vez, confirma estado."""
        mock_page = MagicMock()

        mock_trigger = MagicMock()
        mock_trigger.count.return_value = 1
        mock_trigger.first = mock_trigger
        mock_trigger.inner_text.side_effect = ["🍌 Nano Banana 2.1 crop_16_9 x2", "Vídeo · 720p · 8s crop_9_16 x1"]
        mock_page.get_by_role.return_value = mock_trigger

        mock_overlay = MagicMock()
        mock_overlay.first = mock_overlay

        mock_video_radio = MagicMock()
        mock_video_radio.count.return_value = 1
        mock_video_radio.first = mock_video_radio

        mock_ar_radio = MagicMock()
        mock_ar_radio.count.return_value = 1
        mock_ar_radio.first = mock_ar_radio
        mock_ar_radio.first.get_attribute.return_value = "false"

        mock_x1_radio = MagicMock()
        mock_x1_radio.count.return_value = 1
        mock_x1_radio.first = mock_x1_radio
        mock_x1_radio.first.get_attribute.return_value = "false"

        def _get_by_role_overlay(role, name=None):
            if role == "radio":
                p = getattr(name, "pattern", "") if name else ""
                if "v" in p or "video" in p:
                    return mock_video_radio
                elif "9:16" in p:
                    return mock_ar_radio
                elif "x1" in p:
                    return mock_x1_radio
            return MagicMock(count=lambda: 0)

        mock_overlay.get_by_role.side_effect = _get_by_role_overlay

        def _mock_locator(selector):
            loc = MagicMock()
            if "flow-chat" in selector or "Fechar" in selector:
                mock_close = MagicMock()
                mock_close.count.return_value = 0
                mock_close.first.is_visible.return_value = False
                loc.filter.return_value = mock_close
            elif "cdk-overlay-pane" in selector:
                loc.filter.return_value = mock_overlay
            return loc

        mock_page.locator.side_effect = _mock_locator

        with patch("scripts.flow_playwright.expect") as mock_expect:
            res = ensure_video_generation_mode(mock_page)
            self.assertTrue(res["confirmed"])
            self.assertTrue(res["changed"])
            self.assertEqual(res["generation_type"], "VIDEO")
            mock_trigger.click.assert_called_once()
            mock_video_radio.click.assert_called_once()
            mock_ar_radio.click.assert_called_once()
            mock_x1_radio.click.assert_called_once()
            mock_page.keyboard.press.assert_called_with("Escape")
            mock_expect.assert_called()

    def test_ensure_video_generation_mode_ambiguous_video_option(self):
        """C. ambiguous_video_option: fail closed, Generate não é clicado."""
        mock_page = MagicMock()

        mock_trigger = MagicMock()
        mock_trigger.count.return_value = 1
        mock_trigger.first = mock_trigger
        mock_trigger.inner_text.return_value = "🍌 Nano Banana 2.1"
        mock_page.get_by_role.return_value = mock_trigger

        mock_overlay = MagicMock()
        mock_overlay.first = mock_overlay

        mock_video_radio = MagicMock()
        mock_video_radio.count.return_value = 2  # Múltiplas opções de vídeo = ambíguo
        mock_overlay.get_by_role.return_value = mock_video_radio

        def _mock_locator(selector):
            loc = MagicMock()
            if "flow-chat" in selector or "Fechar" in selector:
                mock_close = MagicMock()
                mock_close.count.return_value = 0
                mock_close.first.is_visible.return_value = False
                loc.filter.return_value = mock_close
            elif "cdk-overlay-pane" in selector:
                loc.filter.return_value = mock_overlay
            return loc

        mock_page.locator.side_effect = _mock_locator

        res = ensure_video_generation_mode(mock_page)
        self.assertFalse(res["confirmed"])
        self.assertEqual(res["error"], "FLOW_VIDEO_MODE_NOT_CONFIRMED")
        mock_video_radio.first.click.assert_not_called()

    def test_ensure_video_generation_mode_missing_generation_type(self):
        """D. missing_generation_type: fail closed."""
        mock_page = MagicMock()

        mock_trigger = MagicMock()
        mock_trigger.count.return_value = 0
        mock_page.get_by_role.return_value = mock_trigger

        def _mock_locator(selector):
            loc = MagicMock()
            if "flow-chat" in selector or "Fechar" in selector:
                mock_close = MagicMock()
                mock_close.count.return_value = 0
                mock_close.first.is_visible.return_value = False
                loc.filter.return_value = mock_close
            else:
                loc.filter.return_value = mock_trigger
            return loc

        mock_page.locator.side_effect = _mock_locator

        res = ensure_video_generation_mode(mock_page)
        self.assertFalse(res["confirmed"])
        self.assertEqual(res["error"], "FLOW_VIDEO_MODE_NOT_CONFIRMED")

    def test_trial_only_confirms_video_zero_generate(self):
        """E. trial_only confirma Video e garante Generate real = 0 e crédito = 0."""
        with patch("scripts.flow_playwright.sync_playwright"), \
             patch("scripts.flow_playwright.launch_flow_context") as mock_launch, \
             patch("scripts.flow_playwright.check_login_state", return_value="AUTHENTICATED"), \
             patch("scripts.flow_playwright.ensure_studio_surface"), \
             patch("scripts.flow_playwright.ensure_video_generation_mode", return_value={"confirmed": True, "changed": False, "generation_type": "VIDEO"}), \
             patch("scripts.flow_playwright.check_pending_credit_approval", return_value=(False, 0, None)), \
             patch("scripts.flow_playwright.fill_prompt"), \
             patch("scripts.flow_playwright.get_generate_button") as mock_get_gen, \
             patch("scripts.flow_playwright.check_generate_actionable", return_value=True), \
             patch("scripts.flow_playwright.capture_tile_baseline", return_value={"tile_a"}), \
             patch("os.path.exists", return_value=True), \
             patch("builtins.open", unittest.mock.mock_open(read_data=json.dumps({
                 "scenes": [{"scene_index": 1, "prompt_en": "test prompt", "expected_clip": "flow_scene_01.mp4"}]
             }))):

            mock_ctx = MagicMock()
            mock_launch.return_value = (mock_ctx, None)
            mock_gen_btn = MagicMock()
            mock_get_gen.return_value = mock_gen_btn

            res = run_playwright_flow_poc(manifest_path="dummy_manifest.json", scene_index=1, trial_only=True)

            self.assertEqual(res["status"], "PRE_FLIGHT_TRIAL_PASS")
            self.assertTrue(res["generation_type_confirmed"])
            self.assertEqual(res["generation_type"], "VIDEO")
            self.assertEqual(res["generate_click_count_this_run"], 0)
            mock_gen_btn.click.assert_not_called()

    def test_image_mode_blocks_generate(self):
        """F. Modo imagem nunca pode chegar em Generate (fail closed imediato)."""
        with patch("scripts.flow_playwright.sync_playwright"), \
             patch("scripts.flow_playwright.launch_flow_context") as mock_launch, \
             patch("scripts.flow_playwright.check_login_state", return_value="AUTHENTICATED"), \
             patch("scripts.flow_playwright.ensure_studio_surface"), \
             patch("scripts.flow_playwright.ensure_video_generation_mode", return_value={"confirmed": False, "changed": False, "generation_type": "UNKNOWN", "error": "FLOW_VIDEO_MODE_NOT_CONFIRMED"}), \
             patch("scripts.flow_playwright.fill_prompt") as mock_fill, \
             patch("scripts.flow_playwright.get_generate_button") as mock_get_gen, \
             patch("os.path.exists", return_value=True), \
             patch("builtins.open", unittest.mock.mock_open(read_data=json.dumps({
                 "scenes": [{"scene_index": 1, "prompt_en": "test prompt", "expected_clip": "flow_scene_01.mp4"}]
             }))):

            mock_ctx = MagicMock()
            mock_launch.return_value = (mock_ctx, None)

            res = run_playwright_flow_poc(manifest_path="dummy_manifest.json", scene_index=1, trial_only=False)

            self.assertEqual(res["status"], "FLOW_VIDEO_MODE_NOT_CONFIRMED")
            self.assertFalse(res["generation_type_confirmed"])
            self.assertEqual(res["generate_click_count_this_run"], 0)
            mock_fill.assert_not_called()
            mock_get_gen.assert_not_called()

    def test_generation_start_rejected_without_video_confirmation(self):
        """G. generation_start genérico sem video confirmation é estritamente rejeitado."""
        mock_page = MagicMock()
        mock_page.wait_for_function.return_value = True

        started = wait_for_generation_started(
            mock_page,
            generation_type_confirmed=False,
            generation_type="UNKNOWN",
        )
        self.assertFalse(started)
        mock_page.wait_for_function.assert_not_called()

    def test_flow_headless_canonical_default_true(self):
        """Automação canônica do Flow usa headless=True por padrão."""
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(resolve_flow_headless())
            self.assertTrue(resolve_flow_headless(None))
            self.assertTrue(resolve_flow_headless(True))

        with patch("scripts.flow_playwright.sync_playwright"), \
             patch("scripts.flow_playwright.launch_flow_context") as mock_launch, \
             patch("scripts.flow_playwright.check_login_state", return_value="AUTHENTICATED"), \
             patch("scripts.flow_playwright.ensure_studio_surface"), \
             patch("scripts.flow_playwright.ensure_video_generation_mode", return_value={"confirmed": True, "changed": False, "generation_type": "VIDEO"}), \
             patch("scripts.flow_playwright.check_pending_credit_approval", return_value=(False, 0, None)), \
             patch("scripts.flow_playwright.fill_prompt"), \
             patch("scripts.flow_playwright.get_generate_button"), \
             patch("scripts.flow_playwright.check_generate_actionable", return_value=True), \
             patch("scripts.flow_playwright.capture_tile_baseline", return_value=set()), \
             patch("os.path.exists", return_value=True), \
             patch("builtins.open", unittest.mock.mock_open(read_data=json.dumps({
                 "scenes": [{"scene_index": 1, "prompt_en": "test", "expected_clip": "clip.mp4"}]
             }))):
            mock_ctx = MagicMock()
            mock_launch.return_value = (mock_ctx, None)
            res = run_playwright_flow_poc(manifest_path="dummy.json", scene_index=1, trial_only=True)
            self.assertEqual(res["status"], "PRE_FLIGHT_TRIAL_PASS")
            mock_launch.assert_called_once()
            _, kwargs = mock_launch.call_args
            self.assertTrue(kwargs.get("headless"))

    def test_flow_headless_explicit_false_diagnostic(self):
        """Modo explícito de diagnóstico pode usar headless=False."""
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(resolve_flow_headless(False))

        with patch.dict(os.environ, {"FLOW_HEADLESS": "false"}):
            self.assertFalse(resolve_flow_headless())
        with patch.dict(os.environ, {"FLOW_HEADLESS": "0"}):
            self.assertFalse(resolve_flow_headless())

        with patch("scripts.flow_playwright.sync_playwright"), \
             patch("scripts.flow_playwright.launch_flow_context") as mock_launch, \
             patch("scripts.flow_playwright.check_login_state", return_value="AUTHENTICATED"), \
             patch("scripts.flow_playwright.ensure_studio_surface"), \
             patch("scripts.flow_playwright.ensure_video_generation_mode", return_value={"confirmed": True, "changed": False, "generation_type": "VIDEO"}), \
             patch("scripts.flow_playwright.check_pending_credit_approval", return_value=(False, 0, None)), \
             patch("scripts.flow_playwright.fill_prompt"), \
             patch("scripts.flow_playwright.get_generate_button"), \
             patch("scripts.flow_playwright.check_generate_actionable", return_value=True), \
             patch("scripts.flow_playwright.capture_tile_baseline", return_value=set()), \
             patch("os.path.exists", return_value=True), \
             patch("builtins.open", unittest.mock.mock_open(read_data=json.dumps({
                 "scenes": [{"scene_index": 1, "prompt_en": "test", "expected_clip": "clip.mp4"}]
             }))):
            mock_ctx = MagicMock()
            mock_launch.return_value = (mock_ctx, None)
            res = run_playwright_flow_poc(manifest_path="dummy.json", scene_index=1, trial_only=True, headless=False)
            self.assertEqual(res["status"], "PRE_FLIGHT_TRIAL_PASS")
            mock_launch.assert_called_once()
            _, kwargs = mock_launch.call_args
            self.assertFalse(kwargs.get("headless"))

    def test_download_only_telemetry_zero_clicks_zero_attempts(self):
        """--download-only reporta telemetria verdadeira: 0 cliques Generate, 0 aprovações, 0 tentativas."""
        with patch("scripts.flow_playwright.sync_playwright"), \
             patch("scripts.flow_playwright.launch_flow_context") as mock_launch, \
             patch("scripts.flow_playwright.check_login_state", return_value="AUTHENTICATED"), \
             patch("scripts.flow_playwright.ensure_studio_surface"), \
             patch("scripts.flow_playwright.ensure_video_generation_mode", return_value={"confirmed": True, "changed": False, "generation_type": "VIDEO"}), \
             patch("scripts.flow_playwright.check_pending_credit_approval", return_value=(False, 0, None)), \
             patch("scripts.flow_playwright.fill_prompt"), \
             patch("scripts.flow_playwright.get_generate_button") as mock_get_gen, \
             patch("scripts.flow_playwright.check_generate_actionable", return_value=True), \
             patch("scripts.flow_playwright.capture_tile_baseline", return_value={"tile_a"}), \
             patch("scripts.flow_playwright.download_generated_clip", return_value=(True, None)), \
             patch("scripts.flow_playwright.validate_clip_file", return_value={"valid": True, "duration": 8.0}), \
             patch("os.path.exists", return_value=True), \
             patch("builtins.open", unittest.mock.mock_open(read_data=json.dumps({
                 "scenes": [{"scene_index": 2, "prompt_en": "test prompt", "expected_clip": "flow_scene_02.mp4"}]
             }))):

            mock_ctx = MagicMock()
            mock_page = MagicMock()
            mock_ctx.pages = [mock_page]
            mock_launch.return_value = (mock_ctx, None)
            mock_gen_btn = MagicMock()
            mock_get_gen.return_value = mock_gen_btn

            # Simula grade com 2 tiles para download_only
            mock_tiles = MagicMock()
            mock_tiles.count.return_value = 2
            mock_t0 = MagicMock()
            mock_t0.get_attribute.side_effect = lambda a: "test prompt" if a == "aria-label" else ""
            mock_t1 = MagicMock()
            mock_t1.get_attribute.side_effect = lambda a: "other scene" if a == "aria-label" else ""
            mock_tiles.nth.side_effect = lambda idx: mock_t0 if idx == 0 else mock_t1
            mock_page.locator.return_value = mock_tiles

            with patch("scripts.flow_playwright.expect"):
                res = run_playwright_flow_poc(
                    manifest_path="dummy_manifest.json",
                    scene_index=2,
                    download_only=True,
                )

            self.assertEqual(res["generate_click_count_this_run"], 0)
            self.assertEqual(res["credit_approval_click_count"], 0)
            self.assertFalse(res["credit_approval_confirmed"])
            self.assertEqual(res["generation_attempts"], 0)
            mock_gen_btn.click.assert_not_called()

    # 1. download normal: expect_download -> persistência -> arquivo válido -> SUCCESS
    def test_download_normal_persistence_valid_clip(self):
        """1. Download normal: expect_download -> save_as persiste -> clipe validado -> SUCCESS."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_file = os.path.join(tmp_dir, "output.mp4")

            mock_page = MagicMock()
            mock_tile = MagicMock()
            mock_tile.count.return_value = 1
            mock_dl_btn = MagicMock()
            mock_dl_btn.count.return_value = 1
            mock_dl_btn.is_visible.return_value = True
            mock_tile.locator.return_value = mock_dl_btn

            mock_download = MagicMock()
            mock_download.suggested_filename = "flow_clip.mp4"

            # Simula save_as gravando um arquivo no disco
            def _fake_save_as(path):
                with open(path, "wb") as f:
                    f.write(b"mp4_content")
            mock_download.save_as.side_effect = _fake_save_as

            mock_info = MagicMock()
            mock_info.value = mock_download
            mock_page.expect_download.return_value.__enter__.return_value = mock_info
            mock_page.expect_download.return_value.__exit__.return_value = None

            with patch("scripts.flow_playwright.expect"), \
                 patch("scripts.flow_playwright.validate_clip_file", return_value={"valid": True, "duration": 8.0}):
                ok, err = download_generated_clip(mock_page, out_file, tile_locator=mock_tile)

            self.assertTrue(ok)
            self.assertIsNone(err)
            self.assertTrue(os.path.exists(out_file))

    # 2. TargetClosedError durante save_as sem artefato => DOWNLOAD_FAILED / recovery
    def test_download_target_closed_no_staging_fails_closed(self):
        """2. TargetClosedError durante save_as sem artefato em staging -> fail-closed (DOWNLOAD_FAILED)."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_file = os.path.join(tmp_dir, "output.mp4")
            staging_dir = os.path.join(tmp_dir, "staging_downloads")
            os.makedirs(staging_dir, exist_ok=True)

            mock_page = MagicMock()
            mock_tile = MagicMock()
            mock_tile.count.return_value = 1
            mock_dl_btn = MagicMock()
            mock_dl_btn.count.return_value = 1
            mock_dl_btn.is_visible.return_value = True
            mock_tile.locator.return_value = mock_dl_btn

            mock_download = MagicMock()
            mock_download.suggested_filename = "flow_clip.mp4"
            mock_download.save_as.side_effect = Exception("Target page, context or browser has been closed")
            mock_download.path.side_effect = Exception("Target page, context or browser has been closed")

            mock_info = MagicMock()
            mock_info.value = mock_download
            mock_page.expect_download.return_value.__enter__.return_value = mock_info
            mock_page.expect_download.return_value.__exit__.return_value = None

            with patch("scripts.flow_playwright.expect"):
                ok, err = download_generated_clip(
                    mock_page, out_file, tile_locator=mock_tile, staging_dir=staging_dir
                )

            self.assertFalse(ok)
            self.assertIn("DOWNLOAD_FAILED", str(err))
            self.assertIn("Target page, context or browser has been closed", str(err))
            self.assertFalse(os.path.exists(out_file))

    # 3. TargetClosedError com artefato válido concluído no staging => recuperado com sucesso
    def test_download_target_closed_recovered_from_staging_valid_clip(self):
        """3. TargetClosedError durante save_as, mas staging possui clipe válido -> recuperado e canonical criado."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_file = os.path.join(tmp_dir, "output.mp4")
            staging_dir = os.path.join(tmp_dir, "staging_downloads")
            os.makedirs(staging_dir, exist_ok=True)

            # Coloca um artefato válido concluído no staging
            staged_file = os.path.join(staging_dir, "Neural_network_clip_123.mp4")
            with open(staged_file, "wb") as f:
                f.write(b"valid_staged_content")

            mock_page = MagicMock()
            mock_tile = MagicMock()
            mock_tile.count.return_value = 1
            mock_dl_btn = MagicMock()
            mock_dl_btn.count.return_value = 1
            mock_dl_btn.is_visible.return_value = True
            mock_tile.locator.return_value = mock_dl_btn

            mock_download = MagicMock()
            mock_download.suggested_filename = "Neural_network_clip_123.mp4"
            mock_download.save_as.side_effect = Exception("Target page, context or browser has been closed")
            mock_download.path.side_effect = Exception("Target page, context or browser has been closed")

            mock_info = MagicMock()
            mock_info.value = mock_download
            mock_page.expect_download.return_value.__enter__.return_value = mock_info
            mock_page.expect_download.return_value.__exit__.return_value = None

            with patch("scripts.flow_playwright.expect"), \
                 patch("scripts.flow_playwright.validate_clip_file", return_value={"valid": True, "duration": 8.0}):
                ok, err = download_generated_clip(
                    mock_page, out_file, tile_locator=mock_tile, staging_dir=staging_dir
                )

            self.assertTrue(ok)
            self.assertIsNone(err)
            self.assertTrue(os.path.exists(out_file))
            with open(out_file, "rb") as f:
                self.assertEqual(f.read(), b"valid_staged_content")
            # Staging limpo após recuperação
            self.assertEqual(len(os.listdir(staging_dir)), 0)

    # 4. staging com mais de um candidato => fail-closed (AMBIGUOUS_STAGING_DOWNLOAD_CANDIDATES)
    def test_download_staging_multiple_candidates_fails_closed(self):
        """4. Staging com múltiplos candidatos -> bloqueia fail-closed sem adivinhação."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_file = os.path.join(tmp_dir, "output.mp4")
            staging_dir = os.path.join(tmp_dir, "staging_downloads")
            os.makedirs(staging_dir, exist_ok=True)

            with open(os.path.join(staging_dir, "cand1.mp4"), "wb") as f:
                f.write(b"cand1")
            with open(os.path.join(staging_dir, "cand2.mp4"), "wb") as f:
                f.write(b"cand2")

            mock_page = MagicMock()
            mock_tile = MagicMock()
            mock_tile.count.return_value = 1
            mock_dl_btn = MagicMock()
            mock_dl_btn.count.return_value = 1
            mock_dl_btn.is_visible.return_value = True
            mock_tile.locator.return_value = mock_dl_btn

            mock_download = MagicMock()
            mock_download.suggested_filename = "flow.mp4"
            mock_download.save_as.side_effect = Exception("TargetClosedError")
            mock_download.path.side_effect = Exception("TargetClosedError")

            mock_info = MagicMock()
            mock_info.value = mock_download
            mock_page.expect_download.return_value.__enter__.return_value = mock_info
            mock_page.expect_download.return_value.__exit__.return_value = None

            with patch("scripts.flow_playwright.expect"):
                ok, err = download_generated_clip(
                    mock_page, out_file, tile_locator=mock_tile, staging_dir=staging_dir
                )

            self.assertFalse(ok)
            self.assertEqual(err, "AMBIGUOUS_STAGING_DOWNLOAD_CANDIDATES")
            self.assertFalse(os.path.exists(out_file))

    # 5. staging com arquivo inválido => fail-closed (INVALID_STAGING_DOWNLOAD_CLIP)
    def test_download_staging_invalid_candidate_fails_closed(self):
        """5. Staging com arquivo inválido/corrompido -> fail-closed sem copiar para canonical."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_file = os.path.join(tmp_dir, "output.mp4")
            staging_dir = os.path.join(tmp_dir, "staging_downloads")
            os.makedirs(staging_dir, exist_ok=True)

            with open(os.path.join(staging_dir, "corrupt.mp4"), "wb") as f:
                f.write(b"corrupt")

            mock_page = MagicMock()
            mock_tile = MagicMock()
            mock_tile.count.return_value = 1
            mock_dl_btn = MagicMock()
            mock_dl_btn.count.return_value = 1
            mock_dl_btn.is_visible.return_value = True
            mock_tile.locator.return_value = mock_dl_btn

            mock_download = MagicMock()
            mock_download.suggested_filename = "corrupt.mp4"
            mock_download.save_as.side_effect = Exception("TargetClosedError")
            mock_download.path.side_effect = Exception("TargetClosedError")

            mock_info = MagicMock()
            mock_info.value = mock_download
            mock_page.expect_download.return_value.__enter__.return_value = mock_info
            mock_page.expect_download.return_value.__exit__.return_value = None

            with patch("scripts.flow_playwright.expect"), \
                 patch("scripts.flow_playwright.validate_clip_file", return_value={"valid": False, "error": "CORRUPT_HEADER"}):
                ok, err = download_generated_clip(
                    mock_page, out_file, tile_locator=mock_tile, staging_dir=staging_dir
                )

            self.assertFalse(ok)
            self.assertIn("INVALID_STAGING_DOWNLOAD_CLIP", str(err))
            self.assertFalse(os.path.exists(out_file))

    def test_persist_download_never_returns_true_without_valid_output_file(self):
        """Bloqueio 2: _persist_download NUNCA retorna True sem output_path existente e comprovadamente válido (zero bypass de mock)."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_file = os.path.join(tmp_dir, "output.mp4")

            # Caso A: mock_download não cria arquivo -> retorna False, DOWNLOAD_FAILED (sem exceção de mock)
            mock_dl = MagicMock()
            mock_dl.suggested_filename = "test.mp4"
            mock_dl.path.return_value = None
            ok, err = _persist_download(mock_dl, out_file)
            self.assertFalse(ok)
            self.assertIn("DOWNLOAD_FAILED", str(err))

            # Caso B: arquivo gravado no disco mas validate_clip_file diz inválido -> retorna False
            def _write_bad(p):
                with open(p, "wb") as f:
                    f.write(b"bad_bytes")
            mock_dl.save_as.side_effect = _write_bad

            with patch("scripts.flow_playwright.validate_clip_file", return_value={"valid": False, "error": "CORRUPT_MEDIA"}):
                ok, err = _persist_download(mock_dl, out_file)
                self.assertFalse(ok)
                self.assertEqual(err, "INVALID_OUTPUT_MEDIA: CORRUPT_MEDIA")

            # Caso C: arquivo gravado e validate_clip_file diz válido -> retorna True
            def _write_good(p):
                with open(p, "wb") as f:
                    f.write(b"good_bytes")
            mock_dl.save_as.side_effect = _write_good

            with patch("scripts.flow_playwright.validate_clip_file", return_value={"valid": True, "duration": 8.0}):
                ok, err = _persist_download(mock_dl, out_file)
                self.assertTrue(ok)
                self.assertIsNone(err)

    def test_context_close_not_recoverable_solely_by_downloads_path_config(self):
        """Bloqueio 1: Fechamento de contexto NÃO é recuperável apenas por downloads_path configurado; sem artefato válido no staging, fail-closed."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_file = os.path.join(tmp_dir, "output.mp4")
            staging_dir = os.path.join(tmp_dir, "staging_downloads")
            os.makedirs(staging_dir, exist_ok=True)

            mock_dl = MagicMock()
            mock_dl.suggested_filename = "flow.mp4"
            mock_dl.save_as.side_effect = Exception("Target page, context or browser has been closed")
            mock_dl.path.side_effect = Exception("Target page, context or browser has been closed")

            # Staging configurado, mas vazio (ou purgado pelo encerramento do context Playwright)
            ok, err = _persist_download(mock_dl, out_file, staging_dir=staging_dir)
            self.assertFalse(ok)
            self.assertIn("DOWNLOAD_FAILED", str(err))
            self.assertIn("Target page, context or browser has been closed", str(err))
            self.assertFalse(os.path.exists(out_file))

    # 6. nenhum segundo clique Generate após falha de download
    def test_no_second_generate_click_after_download_failure(self):
        """6. Falha no download resulta em exatamente 1 clique Generate (zero retry/segundo clique)."""
        with patch("scripts.flow_playwright.sync_playwright"), \
             patch("scripts.flow_playwright.launch_flow_context") as mock_launch, \
             patch("scripts.flow_playwright.check_login_state", return_value="AUTHENTICATED"), \
             patch("scripts.flow_playwright.ensure_studio_surface"), \
             patch("scripts.flow_playwright.ensure_video_generation_mode", return_value={"confirmed": True, "changed": False, "generation_type": "VIDEO"}), \
             patch("scripts.flow_playwright.check_pending_credit_approval", return_value=(False, 0, None)), \
             patch("scripts.flow_playwright.fill_prompt"), \
             patch("scripts.flow_playwright.get_generate_button") as mock_get_gen, \
             patch("scripts.flow_playwright.check_generate_actionable", return_value=True), \
             patch("scripts.flow_playwright.capture_tile_baseline") as mock_base, \
             patch("scripts.flow_playwright.wait_for_generation_complete", return_value=(True, MagicMock(), None)), \
             patch("scripts.flow_playwright.download_generated_clip", return_value=(False, "DOWNLOAD_FAILED: TargetClosedError")), \
             patch("os.path.exists", side_effect=lambda p: True if "dummy" in str(p) or "manifest" in str(p) else False), \
             patch("builtins.open", unittest.mock.mock_open(read_data=json.dumps({
                 "scenes": [{"scene_index": 5, "prompt_en": "test prompt", "expected_clip": "flow_scene_05.mp4"}]
             }))):

            mock_ctx = MagicMock()
            mock_page = MagicMock()
            mock_page.wait_for_function.return_value.json_value.return_value = "GENERATION_STARTED"
            mock_ctx.pages = [mock_page]
            mock_launch.return_value = (mock_ctx, None)

            mock_gen_btn = MagicMock()
            mock_get_gen.return_value = mock_gen_btn
            mock_base.side_effect = [{"tile_old"}, {"tile_old", "tile_new"}]

            res = run_playwright_flow_poc(manifest_path="dummy.json", scene_index=5)

            self.assertEqual(res["status"], "DOWNLOAD_FAILED")
            self.assertEqual(res["generate_click_count_this_run"], 1)
            mock_gen_btn.click.assert_called_once()

    # 8. multi-tile download-only: nunca selecionar tile arbitrariamente
    def test_multi_tile_download_only_never_selects_arbitrary_tile(self):
        """8. Multi-tile download-only: match determinístico seleciona tile correto; ambiguidade bloqueia fail-closed."""
        # 8a: match determinístico seleciona tile correto em grade de 3 tiles
        with patch("scripts.flow_playwright.sync_playwright"), \
             patch("scripts.flow_playwright.launch_flow_context") as mock_launch, \
             patch("scripts.flow_playwright.check_login_state", return_value="AUTHENTICATED"), \
             patch("scripts.flow_playwright.ensure_studio_surface"), \
             patch("scripts.flow_playwright.ensure_video_generation_mode", return_value={"confirmed": True, "changed": False, "generation_type": "VIDEO"}), \
             patch("scripts.flow_playwright.check_pending_credit_approval", return_value=(False, 0, None)), \
             patch("scripts.flow_playwright.fill_prompt"), \
             patch("scripts.flow_playwright.get_generate_button"), \
             patch("scripts.flow_playwright.check_generate_actionable", return_value=True), \
             patch("scripts.flow_playwright.capture_tile_baseline", return_value={"t1", "t2", "t5"}), \
             patch("scripts.flow_playwright.download_generated_clip", return_value=(True, None)), \
             patch("scripts.flow_playwright.validate_clip_file", return_value={"valid": True, "duration": 8.0}), \
             patch("os.path.exists", return_value=True), \
             patch("builtins.open", unittest.mock.mock_open(read_data=json.dumps({
                 "scenes": [
                     {"scene_index": 1, "prompt_en": "Cena um cidade", "expected_clip": "flow_scene_01.mp4"},
                     {"scene_index": 2, "prompt_en": "Cena dois praia", "expected_clip": "flow_scene_02.mp4"},
                     {"scene_index": 5, "prompt_en": "Cena cinco neural network", "expected_clip": "flow_scene_05.mp4"},
                 ]
             }))):

            mock_ctx = MagicMock()
            mock_page = MagicMock()
            mock_ctx.pages = [mock_page]
            mock_launch.return_value = (mock_ctx, None)

            mock_tiles = MagicMock()
            mock_tiles.count.return_value = 3
            mock_t1 = MagicMock()
            mock_t1.get_attribute.side_effect = lambda a: "Cena um cidade" if a == "aria-label" else ""
            mock_t2 = MagicMock()
            mock_t2.get_attribute.side_effect = lambda a: "Cena dois praia" if a == "aria-label" else ""
            mock_t5 = MagicMock()
            mock_t5.get_attribute.side_effect = lambda a: "Cena cinco neural network" if a == "aria-label" else ""

            def _nth(idx):
                return [mock_t1, mock_t2, mock_t5][idx]
            mock_tiles.nth.side_effect = _nth
            mock_page.locator.return_value = mock_tiles

            with patch("scripts.flow_playwright.expect"):
                res = run_playwright_flow_poc(manifest_path="dummy.json", scene_index=5, download_only=True)

            self.assertEqual(res["status"], "SUCCESS")
            self.assertEqual(res["generate_click_count_this_run"], 0)
            self.assertEqual(res["generation_attempts"], 0)

        # 8b: grade com 3 tiles mas sem nenhum match de prompt para cena 5 -> fail-closed (sem pegar nth(0))
        with patch("scripts.flow_playwright.sync_playwright"), \
             patch("scripts.flow_playwright.launch_flow_context") as mock_launch, \
             patch("scripts.flow_playwright.check_login_state", return_value="AUTHENTICATED"), \
             patch("scripts.flow_playwright.ensure_studio_surface"), \
             patch("scripts.flow_playwright.ensure_video_generation_mode", return_value={"confirmed": True, "changed": False, "generation_type": "VIDEO"}), \
             patch("scripts.flow_playwright.check_pending_credit_approval", return_value=(False, 0, None)), \
             patch("scripts.flow_playwright.fill_prompt"), \
             patch("scripts.flow_playwright.get_generate_button"), \
             patch("scripts.flow_playwright.check_generate_actionable", return_value=True), \
             patch("scripts.flow_playwright.capture_tile_baseline", return_value={"t1", "t2", "t3"}), \
             patch("os.path.exists", side_effect=lambda p: True if "dummy" in str(p) or "manifest" in str(p) else False), \
             patch("builtins.open", unittest.mock.mock_open(read_data=json.dumps({
                 "scenes": [{"scene_index": 5, "prompt_en": "Cena cinco neural", "expected_clip": "flow_scene_05.mp4"}]
             }))):

            mock_ctx = MagicMock()
            mock_page = MagicMock()
            mock_ctx.pages = [mock_page]
            mock_launch.return_value = (mock_ctx, None)

            mock_tiles = MagicMock()
            mock_tiles.count.return_value = 3
            mock_tx = MagicMock()
            mock_tx.get_attribute.side_effect = lambda a: "outro prompt qualquer" if a == "aria-label" else ""
            mock_tiles.nth.return_value = mock_tx
            mock_page.locator.return_value = mock_tiles

            res = run_playwright_flow_poc(manifest_path="dummy.json", scene_index=5, download_only=True)

            self.assertEqual(res["status"], "AMBIGUOUS_TILE_TARGET_FOR_SCENE_5")
            self.assertEqual(res["generate_click_count_this_run"], 0)
            self.assertEqual(res["generation_attempts"], 0)


if __name__ == "__main__":
    unittest.main()

