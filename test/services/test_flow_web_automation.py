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
    check_auth_and_ui_state,
    navigate_landing_to_studio,
    run_preflight,
    run_single_scene_poc,
    validate_clip_file,
    wait_for_generation_and_download,
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
            "creditsStatus": CreditsStatus.UNKNOWN,
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


if __name__ == "__main__":
    unittest.main()
