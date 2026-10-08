"""
test/services/test_flow_web_automation.py
=========================================
Testes unitários e mocks locais para automação web do Google Flow (V1.4A.1).

Cobre:
1. Validação de mídia e idempotência.
2. Eliminação de falso positivo: landing não vira generation_in_progress.
3. Elemento hidden progress/spinner não conta; progressbar visível no studio conta.
4. Modelagem de créditos: ausente -> UNKNOWN, zero -> ZERO, numérico -> AVAILABLE.
5. Modelagem de superfícies: LANDING != STUDIO, STUDIO exige prompt/editor real.
6. Navegação segura landing -> studio sem disparar geração nem consumir créditos (preflight).
7. Fail-closed para sessão, CAPTCHA e concorrência.
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from scripts.flow_web_automation import (
    CreditsStatus,
    FlowSurface,
    _build_inject_prompt_js,
    capture_studio_baseline,
    check_auth_and_ui_state,
    clean_download_dir,
    click_generate_once,
    fill_prompt,
    find_generate_button,
    inspect_credits_menu,
    navigate_landing_to_studio,
    run_arm,
    run_fill_check,
    run_preflight,
    run_single_scene_poc,
    validate_clip_file,
    verify_injection_js_syntax,
    wait_for_generation_and_download,
    wait_until_generation_ready,
)
from scripts.flow_workflow import get_project_status


class TestFlowWebAutomation(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_flow_auto_")
        self.manifest_path = os.path.join(self.test_dir, "manifest.json")
        self.clips_dir = os.path.join(self.test_dir, "clips")
        os.makedirs(self.clips_dir, exist_ok=True)

        self.manifest_data = {
            "project_name": "test_flow_poc",
            "video_subject": "Nebulosa Cósmica",
            "total_scenes": 1,
            "scenes": [
                {
                    "scene_index": 1,
                    "narration": "Nebulosas estelares em rotação contínua.",
                    "duration_hint": 6.0,
                    "expected_clip": "flow_scene_01.mp4",
                    "is_flow_premium": True,
                    "prompt_en": "Majestic cosmic nebula in deep space, slow cinematic camera glide, 9:16 portrait composition.",
                }
            ],
        }
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(self.manifest_data, f, indent=2)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_validate_clip_file_missing_and_empty(self):
        res_missing = validate_clip_file(os.path.join(self.test_dir, "nao_existe.mp4"))
        self.assertFalse(res_missing["valid"])
        self.assertEqual(res_missing["error"], "FILE_NOT_FOUND")

        invalid_ext = os.path.join(self.test_dir, "video.txt")
        with open(invalid_ext, "w") as f:
            f.write("teste")
        res_ext = validate_clip_file(invalid_ext)
        self.assertFalse(res_ext["valid"])
        self.assertEqual(res_ext["error"], "NOT_MP4_EXTENSION")

        empty_mp4 = os.path.join(self.test_dir, "empty.mp4")
        open(empty_mp4, "wb").close()
        res_empty = validate_clip_file(empty_mp4)
        self.assertFalse(res_empty["valid"])
        self.assertEqual(res_empty["error"], "EMPTY_FILE")

    @patch("app.services.media_quality.probe_media")
    def test_validate_clip_file_with_mocked_probe(self, mock_probe):
        sample_mp4 = os.path.join(self.test_dir, "sample.mp4")
        with open(sample_mp4, "wb") as f:
            f.write(b"fake_mp4_bytes")

        mock_probe.return_value = {
            "valid": True,
            "format_duration": 6.5,
            "video_streams": [{"codec_name": "h264", "width": 1080, "height": 1920}],
        }
        res_valid = validate_clip_file(sample_mp4)
        self.assertTrue(res_valid["valid"])
        self.assertEqual(res_valid["duration"], 6.5)
        self.assertIsNone(res_valid["error"])

        mock_probe.return_value = {
            "valid": True,
            "format_duration": 0.0,
            "video_streams": [{"codec_name": "h264"}],
        }
        res_zero = validate_clip_file(sample_mp4)
        self.assertFalse(res_zero["valid"])
        self.assertEqual(res_zero["error"], "ZERO_DURATION")

        mock_probe.return_value = {
            "valid": True,
            "format_duration": 5.0,
            "video_streams": [],
        }
        res_no_stream = validate_clip_file(sample_mp4)
        self.assertFalse(res_no_stream["valid"])
        self.assertEqual(res_no_stream["error"], "NO_VIDEO_STREAM")

    @patch("scripts.flow_web_automation.validate_clip_file")
    def test_idempotency_skips_when_valid_clip_exists(self, mock_validate):
        target_clip = os.path.join(self.clips_dir, "flow_scene_01.mp4")
        with open(target_clip, "wb") as f:
            f.write(b"existing_clip")

        mock_validate.return_value = {
            "valid": True,
            "duration": 5.8,
            "size": 123456,
            "error": None,
        }

        res = run_single_scene_poc(
            manifest_path=self.manifest_path,
            scene_index=1,
            cdp_client=None,
        )

        self.assertEqual(res["status"], "ALREADY_COMPLETE")
        self.assertTrue(res["idempotent"])
        self.assertEqual(res["duration"], 5.8)
        self.assertEqual(res["generation_attempts"], 0)

    def test_landing_does_not_trigger_generation_in_progress(self):
        """Landing page com promoção/carrossel NÃO deve marcar isGenerating=True."""
        mock_cdp = MagicMock()
        mock_cdp.eval_js.return_value = {
            "url": "https://flow.google.com/?pli=1",
            "title": "Google Flow",
            "isBlank": False,
            "hasCaptcha": False,
            "isAccountsPage": False,
            "isLandingAbout": False,
            "hasLoginBtn": False,
            "isAuthenticated": True,
            "surface": FlowSurface.LANDING,
            "hasPromptInput": False,
            "promptInputsCount": 0,
            "isGenerating": False,
            "falsePositiveSource": "DIV.promotion-banner-progress-bar (role=none)",
            "credits": None,
            "creditsStatus": CreditsStatus.UNKNOWN,
        }

        state = check_auth_and_ui_state(mock_cdp)
        self.assertEqual(state["surface"], FlowSurface.LANDING)
        self.assertFalse(state["isGenerating"])
        self.assertIn("promotion-banner-progress-bar", state["falsePositiveSource"])

    def test_hidden_progress_element_does_not_count(self):
        """Elemento com classe progress/spinner ou role=progressbar porém oculto não conta."""
        mock_cdp = MagicMock()
        mock_cdp.eval_js.return_value = {
            "url": "https://flow.google.com/project/123",
            "title": "Google Flow Studio",
            "surface": FlowSurface.STUDIO,
            "isAuthenticated": True,
            "hasPromptInput": True,
            "isGenerating": False,
            "falsePositiveSource": None,
        }

        state = check_auth_and_ui_state(mock_cdp)
        self.assertFalse(state["isGenerating"])

    def test_visible_progressbar_in_studio_counts(self):
        """Progressbar visível real dentro do studio marca isGenerating=True."""
        mock_cdp = MagicMock()
        mock_cdp.eval_js.return_value = {
            "url": "https://flow.google.com/project/123",
            "title": "Google Flow Studio",
            "surface": FlowSurface.STUDIO,
            "isAuthenticated": True,
            "hasPromptInput": True,
            "isGenerating": True,
            "falsePositiveSource": None,
        }

        state = check_auth_and_ui_state(mock_cdp)
        self.assertEqual(state["surface"], FlowSurface.STUDIO)
        self.assertTrue(state["isGenerating"])

    def test_credits_absent_evaluates_to_unknown(self):
        """Ausência de contador de créditos resulta em UNKNOWN, e não AVAILABLE."""
        mock_cdp = MagicMock()
        mock_cdp.eval_js.return_value = {
            "url": "https://flow.google.com/",
            "surface": FlowSurface.LANDING,
            "isAuthenticated": True,
            "credits": None,
            "creditsStatus": CreditsStatus.UNKNOWN,
            "creditsAvailable": None,
        }

        state = check_auth_and_ui_state(mock_cdp)
        self.assertEqual(state["creditsStatus"], CreditsStatus.UNKNOWN)
        self.assertIsNone(state["creditsAvailable"])

    def test_landing_different_from_studio(self):
        """LANDING (sem editor) é estritamente diferente de STUDIO (com editor)."""
        mock_cdp = MagicMock()

        # 1. Landing
        mock_cdp.eval_js.return_value = {
            "url": "https://flow.google.com/",
            "surface": FlowSurface.LANDING,
            "isAuthenticated": True,
            "hasPromptInput": False,
        }
        landing_state = check_auth_and_ui_state(mock_cdp)
        self.assertEqual(landing_state["surface"], FlowSurface.LANDING)
        self.assertFalse(landing_state["hasPromptInput"])

        # 2. Studio
        mock_cdp.eval_js.return_value = {
            "url": "https://flow.google.com/project/abc-123",
            "surface": FlowSurface.STUDIO,
            "isAuthenticated": True,
            "hasPromptInput": True,
            "promptInputsCount": 1,
        }
        studio_state = check_auth_and_ui_state(mock_cdp)
        self.assertEqual(studio_state["surface"], FlowSurface.STUDIO)
        self.assertTrue(studio_state["hasPromptInput"])
        self.assertNotEqual(landing_state["surface"], studio_state["surface"])

    def test_studio_requires_real_prompt_editor(self):
        """STUDIO exige editor de prompt real presente (ex: ProseMirror/textarea)."""
        mock_cdp = MagicMock()
        # Sem editor de prompt -> não pode ser considerado pronto para gerar
        mock_cdp.eval_js.return_value = {
            "url": "https://flow.google.com/project/abc-123",
            "surface": FlowSurface.STUDIO,
            "hasPromptInput": False,
            "promptInputsCount": 0,
        }
        state = check_auth_and_ui_state(mock_cdp)
        self.assertFalse(state["hasPromptInput"])

    def test_safe_navigation_and_preflight_does_not_trigger_generate(self):
        """Navegação segura e preflight fazem transição LANDING -> STUDIO sem disparar geração."""
        mock_cdp = MagicMock()

        # Sequência simulada no preflight:
        # 1. State before (LANDING)
        # 2. Navegação (click em novo projeto)
        # 3. State after (STUDIO)
        state_landing = {
            "url": "https://flow.google.com/",
            "title": "Google Flow",
            "isAuthenticated": True,
            "surface": FlowSurface.LANDING,
            "hasPromptInput": False,
            "promptInputsCount": 0,
            "hasCaptcha": False,
            "isGenerating": False,
            "creditsStatus": CreditsStatus.UNKNOWN,
            "falsePositiveSource": "DIV.promotion-banner-progress-bar",
        }
        state_studio = {
            "url": "https://flow.google.com/project/proj-uuid-123",
            "title": "Google Flow Studio",
            "isAuthenticated": True,
            "surface": FlowSurface.STUDIO,
            "hasPromptInput": True,
            "promptInputsCount": 1,
            "hasCaptcha": False,
            "isGenerating": False,
            "creditsStatus": CreditsStatus.AVAILABLE,
            "falsePositiveSource": None,
        }

        # No preflight, check_auth_and_ui_state é chamado para before e after
        with patch("scripts.flow_web_automation.check_auth_and_ui_state", side_effect=[state_landing, state_studio]):
            with patch("scripts.flow_web_automation.navigate_landing_to_studio", return_value=state_studio) as mock_nav:
                res = run_preflight(cdp_client=mock_cdp)

                mock_nav.assert_called_once()
                self.assertEqual(res["status"], "PREFLIGHT_OK")
                self.assertEqual(res["flow_surface_before"], FlowSurface.LANDING)
                self.assertEqual(res["flow_surface_after"], FlowSurface.STUDIO)
                self.assertTrue(res["prompt_input_found"])
                self.assertFalse(res["generation_in_progress"])
                self.assertTrue(res["safe_to_attempt_generation"])
                self.assertEqual(res["generation_attempts"], 0)
                self.assertEqual(res["credits_consumed"], 0)
                self.assertFalse(res["download_attempted"])

    def test_fail_closed_unauthenticated(self):
        mock_cdp = MagicMock()
        mock_cdp.eval_js.return_value = {
            "url": "https://flow.google.com/about",
            "title": "Google Flow",
            "isBlank": False,
            "hasCaptcha": False,
            "isAccountsPage": False,
            "isLandingAbout": True,
            "hasLoginBtn": True,
            "isAuthenticated": False,
            "surface": FlowSurface.LOGIN,
            "hasPromptInput": False,
            "isGenerating": False,
            "creditsStatus": CreditsStatus.UNKNOWN,
        }

        res = run_single_scene_poc(
            manifest_path=self.manifest_path,
            scene_index=1,
            cdp_client=mock_cdp,
            wait_login_sec=0,
        )

        self.assertEqual(res["status"], "AWAITING_INITIAL_HUMAN_LOGIN")
        self.assertEqual(res["google_session_status"], "AWAITING_INITIAL_HUMAN_LOGIN")

    def test_fail_closed_captcha(self):
        mock_cdp = MagicMock()
        mock_cdp.eval_js.return_value = {
            "url": "https://flow.google.com",
            "title": "Google Flow",
            "isBlank": False,
            "hasCaptcha": True,
            "isAccountsPage": False,
            "isLandingAbout": False,
            "hasLoginBtn": False,
            "isAuthenticated": False,
            "surface": FlowSurface.CHALLENGE,
            "hasPromptInput": False,
            "isGenerating": False,
            "creditsStatus": CreditsStatus.UNKNOWN,
        }

        res = run_single_scene_poc(
            manifest_path=self.manifest_path,
            scene_index=1,
            cdp_client=mock_cdp,
        )

        self.assertEqual(res["status"], "BLOCKED_CAPTCHA")
        self.assertEqual(res["captcha_status"], "BLOCKED")

    def test_fail_closed_no_credits(self):
        mock_cdp = MagicMock()
        mock_cdp.eval_js.return_value = {
            "url": "https://flow.google.com/project/test",
            "title": "Google Flow Studio",
            "isBlank": False,
            "hasCaptcha": False,
            "isAccountsPage": False,
            "isLandingAbout": False,
            "hasLoginBtn": False,
            "isAuthenticated": True,
            "surface": FlowSurface.STUDIO,
            "hasPromptInput": True,
            "credits": 0,
            "creditsStatus": CreditsStatus.ZERO,
            "creditsAvailable": False,
            "isGenerating": False,
        }

        res = run_single_scene_poc(
            manifest_path=self.manifest_path,
            scene_index=1,
            cdp_client=mock_cdp,
        )

        self.assertEqual(res["status"], "BLOCKED_NO_CREDITS")
        self.assertEqual(res["credits_status"], CreditsStatus.ZERO)

    @patch("app.services.media_quality.probe_media")
    def test_flow_workflow_status_recognizes_ready_flow(self, mock_probe):
        mock_probe.return_value = {
            "valid": True,
            "format_duration": 6.0,
            "video_streams": [{"codec_name": "h264"}],
        }

        clip_path = os.path.join(self.clips_dir, "flow_scene_01.mp4")
        with open(clip_path, "wb") as f:
            f.write(b"valid_clip_content_for_testing")

        status_info = get_project_status(self.test_dir)
        self.assertEqual(status_info["total_scenes"], 1)
        self.assertEqual(status_info["ready_flow_clips"], 1)
        self.assertEqual(status_info["missing_clips"], 0)
        self.assertTrue(status_info["is_fully_flow"])

        scene1 = status_info["scenes"][0]
        self.assertEqual(scene1["scene_index"], 1)
        self.assertEqual(scene1["expected_clip"], "flow_scene_01.mp4")
        self.assertEqual(scene1["status"], "READY_FLOW")

    def test_injection_js_syntax_is_valid(self):
        """Verifica que o JS de injeção gerado não contém double braces e é sintaticamente válido."""
        prompt = "Cosmic nebula, 9:16 vertical, slow glide, high details."
        js_code = _build_inject_prompt_js(prompt)
        self.assertNotIn("{{", js_code, "JS não pode conter double braces de f-string")
        self.assertNotIn("}}", js_code, "JS não pode conter double braces de f-string")
        self.assertIn("Cosmic nebula", js_code)

        syntax_res = verify_injection_js_syntax(cdp=None, prompt_text=prompt)
        self.assertEqual(syntax_res["syntax"], "VALID")
        self.assertIsNone(syntax_res["error"])

    def test_arm_credits_unknown_blocks_arming(self):
        """Créditos UNKNOWN devem resultar em SAFE_TO_GENERATE_ONCE = NO (Fail-Closed)."""
        mock_cdp = MagicMock()
        mock_cdp.eval_js.side_effect = [
            # check_auth_and_ui_state: Studio autenticado, mas créditos UNKNOWN
            {
                "url": "https://flow.google.com/project/test-uuid",
                "title": "Google Flow Studio",
                "isAuthenticated": True,
                "surface": FlowSurface.STUDIO,
                "hasPromptInput": True,
                "promptInputsCount": 1,
                "hasCaptcha": False,
                "isGenerating": False,
                "creditsStatus": CreditsStatus.UNKNOWN,
                "credits": None,
            },
            # inspect_credits_menu: não consegue encontrar contador
            {"count": None, "status": CreditsStatus.UNKNOWN, "opened": False},
            # find_generate_button: 1 botão único
            {"found": True, "matchCount": 1, "aria": "Iniciar geração", "text": "arrow_forward", "disabled": True, "ambiguous": False},
            # verify_injection_js_syntax via CDP
            {"valid": True, "error": None},
            # capture_studio_baseline
            {"videosCount": 0, "videoSrcs": [], "downloadButtonsCount": 0, "tilesCount": 0, "tileIds": []},
        ]

        res = run_arm(cdp_client=mock_cdp)
        self.assertEqual(res["status"], "ARMED_BLOCKED")
        self.assertFalse(res["safe_to_generate_once"])
        self.assertEqual(res["credits_status"], CreditsStatus.UNKNOWN)
        self.assertEqual(res["generation_attempts"], 0)
        self.assertEqual(res["credits_consumed"], 0)
        self.assertFalse(res["download_attempted"])

    def test_arm_credits_zero_blocks_arming(self):
        """Créditos ZERO devem resultar em SAFE_TO_GENERATE_ONCE = NO (Fail-Closed)."""
        mock_cdp = MagicMock()
        mock_cdp.eval_js.side_effect = [
            # check_auth_and_ui_state: Studio autenticado, créditos ZERO
            {
                "url": "https://flow.google.com/project/test-uuid",
                "title": "Google Flow Studio",
                "isAuthenticated": True,
                "surface": FlowSurface.STUDIO,
                "hasPromptInput": True,
                "promptInputsCount": 1,
                "hasCaptcha": False,
                "isGenerating": False,
                "creditsStatus": CreditsStatus.ZERO,
                "credits": 0,
            },
            # find_generate_button: 1 botão único
            {"found": True, "matchCount": 1, "aria": "Iniciar geração", "text": "arrow_forward", "disabled": True, "ambiguous": False},
            # verify_injection_js_syntax via CDP
            {"valid": True, "error": None},
            # capture_studio_baseline
            {"videosCount": 0, "videoSrcs": [], "downloadButtonsCount": 0, "tilesCount": 0, "tileIds": []},
        ]

        res = run_arm(cdp_client=mock_cdp)
        self.assertEqual(res["status"], "ARMED_BLOCKED")
        self.assertFalse(res["safe_to_generate_once"])
        self.assertEqual(res["credits_status"], CreditsStatus.ZERO)
        self.assertEqual(res["generation_attempts"], 0)

    def test_arm_credits_available_passes_gate(self):
        """Créditos AVAILABLE e todos os requisitos válidos resultam em SAFE_TO_GENERATE_ONCE = YES."""
        mock_cdp = MagicMock()
        mock_cdp.eval_js.side_effect = [
            # check_auth_and_ui_state: Studio autenticado com 915 créditos
            {
                "url": "https://flow.google.com/project/test-uuid",
                "title": "Google Flow Studio",
                "isAuthenticated": True,
                "surface": FlowSurface.STUDIO,
                "hasPromptInput": True,
                "promptInputsCount": 1,
                "hasCaptcha": False,
                "isGenerating": False,
                "creditsStatus": CreditsStatus.AVAILABLE,
                "credits": 915,
            },
            # find_generate_button: 1 botão único e visível
            {"found": True, "matchCount": 1, "aria": "Iniciar geração", "text": "arrow_forward", "disabled": True, "ambiguous": False},
            # verify_injection_js_syntax via CDP
            {"valid": True, "error": None},
            # capture_studio_baseline
            {"videosCount": 0, "videoSrcs": [], "downloadButtonsCount": 0, "tilesCount": 0, "tileIds": []},
        ]

        res = run_arm(cdp_client=mock_cdp)
        self.assertEqual(res["status"], "ARMED_OK")
        self.assertTrue(res["safe_to_generate_once"])
        self.assertEqual(res["credits_status"], CreditsStatus.AVAILABLE)
        self.assertEqual(res["credits_count"], 915)
        self.assertTrue(res["generate_button_found"])
        self.assertEqual(res["generate_button_match_count"], 1)
        self.assertEqual(res["generate_button_aria"], "Iniciar geração")
        self.assertEqual(res["generate_button_text"], "arrow_forward")
        self.assertTrue(res["generate_button_disabled"])
        self.assertEqual(res["injection_js_syntax"], "VALID")
        self.assertTrue(res["baseline_capture_supported"])
        self.assertTrue(res["download_dir_cleanable"])
        self.assertEqual(res["generation_attempts"], 0)
        self.assertEqual(res["credits_consumed"], 0)
        self.assertFalse(res["download_attempted"])

    def test_arm_multiple_generate_buttons_blocks_arming(self):
        """Múltiplos botões de geração na interface devem bloquear o arming (ambiguidade)."""
        mock_cdp = MagicMock()
        mock_cdp.eval_js.side_effect = [
            # check_auth_and_ui_state
            {
                "url": "https://flow.google.com/project/test-uuid",
                "title": "Google Flow Studio",
                "isAuthenticated": True,
                "surface": FlowSurface.STUDIO,
                "hasPromptInput": True,
                "promptInputsCount": 1,
                "hasCaptcha": False,
                "isGenerating": False,
                "creditsStatus": CreditsStatus.AVAILABLE,
                "credits": 915,
            },
            # find_generate_button: 2 botões encontrados (ambiguidade!)
            {"found": True, "matchCount": 2, "aria": "Iniciar geração", "text": "arrow_forward", "disabled": True, "ambiguous": True},
            # verify_injection_js_syntax via CDP
            {"valid": True, "error": None},
            # capture_studio_baseline
            {"videosCount": 0, "videoSrcs": [], "downloadButtonsCount": 0, "tilesCount": 0, "tileIds": []},
        ]

        res = run_arm(cdp_client=mock_cdp)
        self.assertEqual(res["status"], "ARMED_BLOCKED")
        self.assertFalse(res["safe_to_generate_once"])
        self.assertEqual(res["generate_button_match_count"], 2)

    def test_run_single_scene_fails_closed_on_unknown_credits(self):
        """run_single_scene_poc falha fechado se créditos permanecerem UNKNOWN."""
        mock_cdp = MagicMock()
        mock_cdp.eval_js.side_effect = [
            # check_auth_and_ui_state
            {
                "url": "https://flow.google.com/project/test-uuid",
                "title": "Google Flow Studio",
                "isAuthenticated": True,
                "surface": FlowSurface.STUDIO,
                "hasPromptInput": True,
                "promptInputsCount": 1,
                "hasCaptcha": False,
                "isGenerating": False,
                "creditsStatus": CreditsStatus.UNKNOWN,
                "credits": None,
            },
            # inspect_credits_menu falha em resolver
            {"count": None, "status": CreditsStatus.UNKNOWN, "opened": False},
        ]

        res = run_single_scene_poc(
            manifest_path=self.manifest_path,
            scene_index=1,
            cdp_client=mock_cdp,
        )
        self.assertEqual(res["status"], "BLOCKED_CREDITS_UNKNOWN")
        self.assertEqual(res["credits_status"], CreditsStatus.UNKNOWN)

    def test_run_single_scene_fails_closed_on_ambiguous_generate_buttons(self):
        """run_single_scene_poc falha fechado se houver múltiplos botões de geração."""
        mock_cdp = MagicMock()
        mock_cdp.eval_js.side_effect = [
            # check_auth_and_ui_state
            {
                "url": "https://flow.google.com/project/test-uuid",
                "title": "Google Flow Studio",
                "isAuthenticated": True,
                "surface": FlowSurface.STUDIO,
                "hasPromptInput": True,
                "promptInputsCount": 1,
                "hasCaptcha": False,
                "isGenerating": False,
                "creditsStatus": CreditsStatus.AVAILABLE,
                "credits": 50,
            },
            # find_generate_button retorna ambíguo
            {"found": True, "matchCount": 2, "aria": "Iniciar geração", "text": "arrow_forward", "disabled": False, "ambiguous": True},
        ]

        res = run_single_scene_poc(
            manifest_path=self.manifest_path,
            scene_index=1,
            cdp_client=mock_cdp,
        )
        self.assertEqual(res["status"], "BLOCK_AMBIGUOUS_GENERATE_BUTTON")

    def test_baseline_prevents_old_result_acceptance(self):
        """Resultado antigo já existente no baseline NÃO deve ser aceito como nova geração."""
        mock_cdp = MagicMock()
        baseline = {
            "videosCount": 1,
            "videoSrcs": ["https://flow.google.com/media/existing_old_video.mp4"],
            "downloadButtonsCount": 1,
            "tilesCount": 1,
            "tileIds": ["tile-0"],
            "timestamp": 1000.0,
            "supported": True,
        }

        # Simula que a página do Studio só tem o MESMO vídeo e mesmo tile pré-existente
        mock_cdp.eval_js.side_effect = [
            # check_auth_and_ui_state
            {"hasCaptcha": False, "isGenerating": False},
            # js_check_ready: mesmos vídeos e tiles do baseline
            {
                "hasVideo": True,
                "videos": ["https://flow.google.com/media/existing_old_video.mp4"],
                "videosCount": 1,
                "hasDownloadBtn": True,
                "tilesCount": 1,
                "tileIds": ["tile-0"],
            },
        ]

        # Com timeout curto de 1s, deve estourar TimeoutError porque não há evidência NOVA
        with self.assertRaises(TimeoutError):
            wait_for_generation_and_download(
                cdp=mock_cdp,
                download_dir=self.clips_dir,
                baseline=baseline,
                start_marker=2000.0,
                timeout_generation_sec=1,
            )

    def test_download_ignores_old_mp4_in_temp_dir(self):
        """Um mp4 antigo com mtime anterior ao start_marker é estritamente ignorado."""
        download_dir = os.path.join(self.test_dir, "temp_test_download")
        os.makedirs(download_dir, exist_ok=True)

        old_mp4 = os.path.join(download_dir, "old_file.mp4")
        with open(old_mp4, "wb") as f:
            f.write(b"old_clip_data")
        # Define mtime antigo (1 hora atrás)
        os.utime(old_mp4, (1000.0, 1000.0))

        start_marker = 5000.0  # Muito posterior ao mtime do old_file

        mock_cdp = MagicMock()
        mock_cdp.eval_js.side_effect = [
            # check_auth_and_ui_state
            {"hasCaptcha": False, "isGenerating": False},
            # js_check_ready: novo vídeo detectado
            {"hasVideo": True, "videos": ["https://new.mp4"], "videosCount": 1, "hasDownloadBtn": True, "tilesCount": 1, "tileIds": ["new-tile"]},
            # js_trigger_dl: download clicado
            {"clicked": True},
        ]

        # Com timeout curto de download, deve estourar TimeoutError pois o old_mp4 não é aceito
        with self.assertRaises(TimeoutError):
            wait_for_generation_and_download(
                cdp=mock_cdp,
                download_dir=download_dir,
                baseline={"videosCount": 0, "videoSrcs": [], "tileIds": []},
                start_marker=start_marker,
                timeout_generation_sec=5,
                timeout_download_sec=2,
            )

    def test_download_accepts_new_mp4_after_start_marker(self):
        """Um mp4 novo com mtime posterior ao start_marker é selecionado com sucesso."""
        download_dir = os.path.join(self.test_dir, "temp_test_download_valid")
        os.makedirs(download_dir, exist_ok=True)

        # Arquivo antigo (deve ser ignorado)
        old_mp4 = os.path.join(download_dir, "stale_file.mp4")
        with open(old_mp4, "wb") as f:
            f.write(b"stale_data")
        os.utime(old_mp4, (1000.0, 1000.0))

        # Start marker definido no tempo presente
        start_marker = 5000.0

        # Arquivo novo (deve ser selecionado)
        new_mp4 = os.path.join(download_dir, "fresh_flow_video.mp4")
        with open(new_mp4, "wb") as f:
            f.write(b"fresh_video_data")
        os.utime(new_mp4, (5005.0, 5005.0))

        mock_cdp = MagicMock()
        mock_cdp.eval_js.side_effect = [
            {"hasCaptcha": False, "isGenerating": False},
            {"hasVideo": True, "videos": ["https://new.mp4"], "videosCount": 1, "hasDownloadBtn": True, "tilesCount": 1, "tileIds": ["new-tile"]},
            {"clicked": True},
        ]

        res_file = wait_for_generation_and_download(
            cdp=mock_cdp,
            download_dir=download_dir,
            baseline={"videosCount": 0, "videoSrcs": [], "tileIds": []},
            start_marker=start_marker,
            timeout_generation_sec=5,
            timeout_download_sec=5,
        )

        self.assertEqual(res_file, new_mp4)

    def test_fill_and_click_are_separate_functions(self):
        """1. fill_prompt, wait_until_generation_ready e click_generate_once são funções desacopladas e invocáveis separadamente."""
        import inspect
        self.assertTrue(callable(fill_prompt))
        self.assertTrue(callable(wait_until_generation_ready))
        self.assertTrue(callable(click_generate_once))
        self.assertTrue(callable(run_fill_check))

        # Assinaturas independentes
        fill_sig = inspect.signature(fill_prompt)
        self.assertIn("cdp", fill_sig.parameters)
        self.assertIn("prompt_text", fill_sig.parameters)

        ready_sig = inspect.signature(wait_until_generation_ready)
        self.assertIn("cdp", ready_sig.parameters)

        click_sig = inspect.signature(click_generate_once)
        self.assertIn("cdp", click_sig.parameters)

    def test_button_initially_disabled_enables_after_poll(self):
        """2. Botão Generate inicialmente desabilitado torna-se habilitado após poll UI."""
        mock_cdp = MagicMock()
        # Primeira chamada: disabled=True; Segunda chamada: disabled=False
        mock_cdp.eval_js.side_effect = [
            {"found": True, "matchCount": 1, "aria": "Iniciar geração", "text": "arrow_forward", "disabled": True, "ambiguous": False},
            {"found": True, "matchCount": 1, "aria": "Iniciar geração", "text": "arrow_forward", "disabled": False, "ambiguous": False},
        ]

        ready_res = wait_until_generation_ready(mock_cdp, timeout_sec=2.0)
        self.assertTrue(ready_res["ready"])
        self.assertIsNone(ready_res["error"])
        self.assertFalse(ready_res["btn_info"]["disabled"])

    def test_prompt_confirmed_before_click(self):
        """3. Prompt deve ser confirmado no editor (handshake) com PROMPT_MATCH=True."""
        mock_cdp = MagicMock()
        prompt_text = "Majestic cosmic nebula in deep space"
        # 1. check_current (vazio)
        # 2. focus_select
        # 3. read back no handshake (retorna o texto inserido)
        mock_cdp.eval_js.side_effect = [
            {"found": True, "text": "", "tag": "DIV", "isProseMirror": True},
            {"found": True},
            prompt_text,
        ]

        fill_res = fill_prompt(mock_cdp, prompt_text, timeout_sec=1.0)
        self.assertTrue(fill_res["success"])
        self.assertTrue(fill_res["prompt_match"])
        self.assertEqual(fill_res["prompt_fill_method"], "CDP_INPUT_INSERT_TEXT")
        self.assertEqual(fill_res["prompt_expected_length"], len(prompt_text))
        self.assertEqual(fill_res["prompt_editor_length"], len(prompt_text))
        mock_cdp.send.assert_called_with("Input.insertText", {"text": prompt_text})

    def test_prompt_not_confirmed_blocks(self):
        """4. Prompt não confirmado pelo handshake bloqueia execução (fail-closed)."""
        mock_cdp = MagicMock()
        prompt_text = "Majestic cosmic nebula in deep space"
        # 1. check_current (vazio)
        # 2. focus_select
        # 3. read back no handshake retorna texto vazio ou incompatível repetidamente
        mock_cdp.eval_js.side_effect = [
            {"found": True, "text": "", "tag": "DIV", "isProseMirror": True},
            {"found": True},
            "",
            "",
            "",
        ]

        fill_res = fill_prompt(mock_cdp, prompt_text, timeout_sec=0.2)
        self.assertFalse(fill_res["success"])
        self.assertFalse(fill_res["prompt_match"])
        self.assertEqual(fill_res["error"], "BLOCKED_PROMPT_NOT_ACCEPTED")

    def test_button_still_disabled_blocks(self):
        """5. Botão que continua disabled após timeout bloqueia com BLOCKED_GENERATE_STILL_DISABLED."""
        mock_cdp = MagicMock()
        # Retorna sempre disabled=True
        mock_cdp.eval_js.return_value = {
            "found": True,
            "matchCount": 1,
            "aria": "Iniciar geração",
            "text": "arrow_forward",
            "disabled": True,
            "ambiguous": False,
        }

        ready_res = wait_until_generation_ready(mock_cdp, timeout_sec=0.2)
        self.assertFalse(ready_res["ready"])
        self.assertEqual(ready_res["error"], "BLOCKED_GENERATE_STILL_DISABLED")

    def test_prompt_already_present_does_not_duplicate(self):
        """6. Prompt já presente no editor é detectado e não duplicado (idempotência)."""
        mock_cdp = MagicMock()
        prompt_text = "Majestic cosmic nebula in deep space"
        # Editor já contém exatamente o prompt
        mock_cdp.eval_js.return_value = {
            "found": True,
            "text": prompt_text,
            "tag": "DIV",
            "isProseMirror": True,
        }

        fill_res = fill_prompt(mock_cdp, prompt_text, timeout_sec=1.0)
        self.assertTrue(fill_res["success"])
        self.assertTrue(fill_res["prompt_match"])
        self.assertEqual(fill_res["prompt_fill_method"], "IDEMPOTENT_ALREADY_PRESENT")
        # CDP Input.insertText NÃO deve ser chamado!
        mock_cdp.send.assert_not_called()

    def test_generation_attempts_zero_when_no_click(self):
        """7. generation_attempts deve ser 0 quando nenhum clique Generate ocorreu."""
        mock_cdp = MagicMock()
        prompt_text = self.manifest_data["scenes"][0]["prompt_en"]

        # Executa run_fill_check (que NUNCA clica)
        mock_cdp.eval_js.side_effect = [
            # check_auth_and_ui_state
            {"surface": FlowSurface.STUDIO, "isAuthenticated": True, "hasPromptInput": True},
            # find_generate_button ANTES
            {"found": True, "matchCount": 1, "disabled": True, "ambiguous": False},
            # fill_prompt: check_current
            {"found": True, "text": "", "tag": "DIV", "isProseMirror": True},
            # fill_prompt: focus_select
            {"found": True},
            # fill_prompt: handshake read
            prompt_text,
            # wait_until_generation_ready: find_generate_button DEPOIS
            {"found": True, "matchCount": 1, "disabled": False, "ambiguous": False},
        ]

        res = run_fill_check(
            manifest_path=self.manifest_path,
            scene_index=1,
            timeout_sec=1.0,
            cdp_client=mock_cdp,
        )

        self.assertEqual(res["status"], "READY_FOR_CLICK")
        self.assertTrue(res["ready_for_click"])
        self.assertFalse(res["generation_clicked"])
        self.assertEqual(res["generation_attempts"], 0)
        self.assertEqual(res["credits_consumed"], 0)

    def test_generation_attempts_one_only_after_confirmed_click(self):
        """8. generation_attempts deve ser 1 somente após clique real confirmado."""
        mock_cdp = MagicMock()
        mock_cdp.eval_js.side_effect = [
            # check_auth_and_ui_state
            {
                "url": "https://flow.google.com/project/test-uuid",
                "surface": FlowSurface.STUDIO,
                "isAuthenticated": True,
                "hasCaptcha": False,
                "isGenerating": False,
                "creditsStatus": CreditsStatus.AVAILABLE,
            },
            # find_generate_button
            {"found": True, "matchCount": 1, "disabled": False, "ambiguous": False},
            # capture_studio_baseline
            {"videosCount": 0, "videoSrcs": [], "downloadButtonsCount": 0, "tilesCount": 0, "tileIds": []},
            # js_click
            {"clicked": True},
        ]

        click_res = click_generate_once(mock_cdp)
        self.assertTrue(click_res["success"])
        self.assertTrue(click_res["clicked"])
        self.assertEqual(click_res["generation_attempts"], 1)
        self.assertTrue(click_res["generation_click_attempted"])
        self.assertTrue(click_res["generation_click_confirmed"])

    @patch("scripts.flow_web_automation.inspect_credits_menu")
    def test_click_generate_once_revalidates_credits_unknown_to_available(self, mock_inspect_menu):
        """click_generate_once: DOM credits UNKNOWN + inspect menu AVAILABLE -> prossegue e clica com sucesso."""
        mock_inspect_menu.return_value = {"creditsStatus": CreditsStatus.AVAILABLE, "count": 915}
        mock_cdp = MagicMock()
        mock_cdp.eval_js.side_effect = [
            # check_auth_and_ui_state (creditsStatus UNKNOWN)
            {
                "url": "https://flow.google.com/project/test-uuid",
                "surface": FlowSurface.STUDIO,
                "isAuthenticated": True,
                "hasCaptcha": False,
                "isGenerating": False,
                "creditsStatus": CreditsStatus.UNKNOWN,
            },
            # find_generate_button
            {"found": True, "matchCount": 1, "disabled": False, "ambiguous": False},
            # capture_studio_baseline
            {"videosCount": 0, "videoSrcs": [], "downloadButtonsCount": 0, "tilesCount": 0, "tileIds": []},
            # js_click
            {"clicked": True},
        ]

        click_res = click_generate_once(mock_cdp)
        self.assertTrue(click_res["success"])
        self.assertTrue(click_res["clicked"])
        self.assertEqual(click_res["generation_attempts"], 1)
        mock_inspect_menu.assert_called_once_with(mock_cdp)

    @patch("scripts.flow_web_automation.inspect_credits_menu")
    def test_click_generate_once_blocks_on_unknown_credits_after_inspect(self, mock_inspect_menu):
        """click_generate_once: UNKNOWN + inspect UNKNOWN -> bloqueia fail-closed."""
        mock_inspect_menu.return_value = {"creditsStatus": CreditsStatus.UNKNOWN, "count": None}
        mock_cdp = MagicMock()
        mock_cdp.eval_js.return_value = {
            "url": "https://flow.google.com/project/test-uuid",
            "surface": FlowSurface.STUDIO,
            "isAuthenticated": True,
            "hasCaptcha": False,
            "isGenerating": False,
            "creditsStatus": CreditsStatus.UNKNOWN,
        }

        click_res = click_generate_once(mock_cdp)
        self.assertFalse(click_res["success"])
        self.assertFalse(click_res["clicked"])
        self.assertEqual(click_res["error"], "BLOCKED_CREDITS_UNKNOWN")
        mock_inspect_menu.assert_called_once_with(mock_cdp)

    def test_click_generate_once_blocks_on_zero_credits(self):
        """click_generate_once: ZERO créditos -> bloqueia fail-closed."""
        mock_cdp = MagicMock()
        mock_cdp.eval_js.return_value = {
            "url": "https://flow.google.com/project/test-uuid",
            "surface": FlowSurface.STUDIO,
            "isAuthenticated": True,
            "hasCaptcha": False,
            "isGenerating": False,
            "creditsStatus": CreditsStatus.ZERO,
        }

        click_res = click_generate_once(mock_cdp)
        self.assertFalse(click_res["success"])
        self.assertFalse(click_res["clicked"])
        self.assertEqual(click_res["error"], "NO_CREDITS_AVAILABLE")

    @patch("scripts.flow_web_automation.clean_download_dir")
    def test_run_single_scene_blocks_when_clean_download_dir_fails(self, mock_clean_dir):
        """run_single_scene_poc: clean_download_dir retorna False -> fail-closed sem clicar geração."""
        mock_clean_dir.return_value = False
        mock_cdp = MagicMock()
        mock_cdp.eval_js.side_effect = [
            # check_auth_and_ui_state (STUDIO, autenticado, créditos AVAILABLE)
            {
                "url": "https://flow.google.com/project/test-uuid",
                "surface": FlowSurface.STUDIO,
                "isAuthenticated": True,
                "hasPromptInput": True,
                "promptInputsCount": 1,
                "hasCaptcha": False,
                "isGenerating": False,
                "creditsStatus": CreditsStatus.AVAILABLE,
                "credits": 915,
            },
            # find_generate_button
            {"found": True, "matchCount": 1, "disabled": False, "ambiguous": False},
        ]

        res = run_single_scene_poc(
            manifest_path=self.manifest_path,
            scene_index=1,
            cdp_client=mock_cdp,
        )

        self.assertEqual(res["status"], "BLOCKED_DOWNLOAD_DIR_NOT_CLEAN")
        self.assertEqual(res["generation_attempts"], 0)
        self.assertFalse(res["generation_click_attempted"])
        self.assertFalse(res["generation_click_confirmed"])


if __name__ == "__main__":
    unittest.main()
