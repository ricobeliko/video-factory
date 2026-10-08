"""
test/services/test_flow_web_automation.py
=========================================
Testes unitários e mocks locais para automação web do Google Flow (V1.4A).

Cobre:
1. Validação rigorosa de arquivo de mídia (validate_clip_file).
2. Idempotência obrigatória: reaproveita clipe existente sem nova chamada ao browser.
3. Fail-Closed para estados de risco:
   - Sessão não autenticada -> AWAITING_INITIAL_HUMAN_LOGIN
   - Desafio CAPTCHA -> BLOCKED_CAPTCHA
   - Créditos esgotados -> BLOCKED_NO_CREDITS
   - Geração já em andamento -> BLOCKED_GENERATION_IN_PROGRESS
4. Ciclo de download (.crdownload -> .mp4 final).
5. Timeout de geração.
6. Integração com flow_workflow.py status -> READY_FLOW.
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from scripts.flow_web_automation import (
    check_auth_and_ui_state,
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
                    "is_flow_premium": true if hasattr(__builtins__, "true") else True,
                    "prompt_en": "Majestic cosmic nebula in deep space, slow cinematic camera glide, 9:16 portrait composition.",
                }
            ],
        }
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(self.manifest_data, f, indent=2)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_validate_clip_file_missing_and_empty(self):
        # 1. Arquivo inexistente
        res_missing = validate_clip_file(os.path.join(self.test_dir, "nao_existe.mp4"))
        self.assertFalse(res_missing["valid"])
        self.assertEqual(res_missing["error"], "FILE_NOT_FOUND")

        # 2. Extensão inválida
        invalid_ext = os.path.join(self.test_dir, "video.txt")
        with open(invalid_ext, "w") as f:
            f.write("teste")
        res_ext = validate_clip_file(invalid_ext)
        self.assertFalse(res_ext["valid"])
        self.assertEqual(res_ext["error"], "NOT_MP4_EXTENSION")

        # 3. Arquivo vazio (0 bytes)
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

        # Caso válido
        mock_probe.return_value = {
            "valid": True,
            "format_duration": 6.5,
            "video_streams": [{"codec_name": "h264", "width": 1080, "height": 1920}],
        }
        res_valid = validate_clip_file(sample_mp4)
        self.assertTrue(res_valid["valid"])
        self.assertEqual(res_valid["duration"], 6.5)
        self.assertIsNone(res_valid["error"])

        # Caso duração zero
        mock_probe.return_value = {
            "valid": True,
            "format_duration": 0.0,
            "video_streams": [{"codec_name": "h264"}],
        }
        res_zero = validate_clip_file(sample_mp4)
        self.assertFalse(res_zero["valid"])
        self.assertEqual(res_zero["error"], "ZERO_DURATION")

        # Caso sem stream de vídeo
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

        # Executa sem cliente CDP: não deve nem tentar abrir o browser
        res = run_single_scene_poc(
            manifest_path=self.manifest_path,
            scene_index=1,
            cdp_client=None,
        )

        self.assertEqual(res["status"], "ALREADY_COMPLETE")
        self.assertTrue(res["idempotent"])
        self.assertEqual(res["duration"], 5.8)
        self.assertEqual(res["generation_attempts"], 0)

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
            "creditsAvailable": True,
            "isGenerating": False,
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
            "creditsAvailable": True,
            "isGenerating": False,
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
            "url": "https://flow.google.com/studio",
            "title": "Google Flow Studio",
            "isBlank": False,
            "hasCaptcha": False,
            "isAccountsPage": False,
            "isLandingAbout": False,
            "hasLoginBtn": False,
            "isAuthenticated": True,
            "credits": 0,
            "creditsAvailable": False,
            "isGenerating": False,
        }

        res = run_single_scene_poc(
            manifest_path=self.manifest_path,
            scene_index=1,
            cdp_client=mock_cdp,
        )

        self.assertEqual(res["status"], "BLOCKED_NO_CREDITS")
        self.assertEqual(res["credits_status"], "ZERO_OR_UNAVAILABLE")

    def test_fail_closed_generation_in_progress(self):
        mock_cdp = MagicMock()
        mock_cdp.eval_js.return_value = {
            "url": "https://flow.google.com/studio",
            "title": "Google Flow Studio",
            "isBlank": False,
            "hasCaptcha": False,
            "isAccountsPage": False,
            "isLandingAbout": False,
            "hasLoginBtn": False,
            "isAuthenticated": True,
            "creditsAvailable": True,
            "isGenerating": True,
        }

        res = run_single_scene_poc(
            manifest_path=self.manifest_path,
            scene_index=1,
            cdp_client=mock_cdp,
        )

        self.assertEqual(res["status"], "BLOCKED_GENERATION_IN_PROGRESS")

    def test_download_monitoring_crdownload_and_completion(self):
        temp_dl_dir = os.path.join(self.test_dir, "downloads")
        os.makedirs(temp_dl_dir, exist_ok=True)

        mock_cdp = MagicMock()
        # Estado inicial: não está gerando, tem vídeo pronto
        mock_cdp.eval_js.side_effect = [
            # 1. check_auth_and_ui_state no loop de espera
            {
                "hasCaptcha": False,
                "isGenerating": False,
                "isAuthenticated": True,
                "creditsAvailable": True,
            },
            # 2. check ready vídeo
            {"hasVideo": True, "hasDownloadBtn": True},
            # 3. trigger download
            {"clicked": True},
        ]

        # Cria arquivo .mp4 simulado
        finished_file = os.path.join(temp_dl_dir, "generated_scene.mp4")
        with open(finished_file, "wb") as f:
            f.write(b"mp4_content_12345")

        downloaded = wait_for_generation_and_download(
            cdp=mock_cdp,
            download_dir=temp_dl_dir,
            timeout_generation_sec=5,
            timeout_download_sec=5,
        )

        self.assertEqual(downloaded, finished_file)
        self.assertTrue(os.path.isfile(downloaded))

    def test_generation_timeout_fail_closed(self):
        mock_cdp = MagicMock()
        mock_cdp.eval_js.return_value = {
            "hasCaptcha": False,
            "isGenerating": True,
            "isAuthenticated": True,
            "creditsAvailable": True,
        }

        with self.assertRaises(TimeoutError):
            wait_for_generation_and_download(
                cdp=mock_cdp,
                download_dir=self.test_dir,
                timeout_generation_sec=1,
            )

    @patch("app.services.media_quality.probe_media")
    def test_flow_workflow_status_recognizes_ready_flow(self, mock_probe):
        mock_probe.return_value = {
            "valid": True,
            "format_duration": 6.0,
            "video_streams": [{"codec_name": "h264"}],
        }

        # Cria o clipe no diretório clips/
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
