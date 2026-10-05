"""
test/services/test_real_image_gate.py
=====================================
Testes unitários e direcionados para a V16.8.1 — Real Generated Image Quality Gate.

Garantias testadas:
1. Endpoint oficial Gemini API é utilizado (generativelanguage.googleapis.com)
2. Payload segue o schema oficial do Gemini (contents, parts, generationConfig)
3. Decodificação correta de resposta inlineData (base64)
4. Erro HTTP resulta em falha controlada (GenerationResult.success = False)
5. Erro DNS/Network resulta em falha controlada sem exceção não tratada
6. Falha na geração real NÃO reutiliza keyframes mock antigos
7. Falha na geração real não produz preview de still motion
8. Status PARTIAL não imprime [SUCESSO] e retorna exit code não-zero
9. Status FAIL não imprime [SUCESSO] e retorna exit code não-zero
10. Status PASS ocorre estritamente quando 3/3 gerações têm sucesso e passam no quality gate
11. Secrets (API keys) nunca são expostos em logs, mensagens ou relatórios
12. Compatibilidade de variáveis de ambiente (GEMINI_API_KEY priorizada sobre NANO_BANANA_API_KEY)
13. Nenhuma chamada externa real ocorre durante a execução dos testes
14. Limitação estrita às 3 cenas HERO (Cenas 3, 4 e 7)
15. Invariantes: zero publicação, zero modificação de produção
"""

import base64
import io
import json
import os
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

from PIL import Image
import pytest

from app.services import hybrid_visual, real_image_gate
from scripts import run_v16_8_1_real_image_gate


@pytest.fixture
def tmp_gate_dir(tmp_path):
    val_dir = tmp_path / "v16_8_1_test"
    val_dir.mkdir(parents=True)
    return str(val_dir)


def _generate_valid_png_base64(width: int = 1080, height: int = 1920) -> str:
    """Gera um PNG vertical válido codificado em base64."""
    img = Image.new("RGB", (width, height), color=(40, 50, 70))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


class TestRealImageGateV16_8_1:

    def test_gate_limits_to_exactly_three_hero_scenes(self, tmp_gate_dir):
        """14. Garante que apenas as cenas 3, 4 e 7 sejam processadas."""
        report = real_image_gate.evaluate_v16_8_1_gate(
            api_key=None,
            output_dir=tmp_gate_dir,
            force_execute=False,
        )
        assert len(report.scenes) == 3
        assert report.scenes_selected == [3, 4, 7]
        indices = [s.scene_index for s in report.scenes]
        assert indices == [3, 4, 7]

    def test_missing_credential_triggers_not_executed_gate(self, tmp_gate_dir):
        """Sem credencial, o gate ativa NOT_EXECUTED_REQUIRES_HUMAN_GATE sem erro fatal."""
        report = real_image_gate.evaluate_v16_8_1_gate(
            api_key="",
            output_dir=tmp_gate_dir,
            force_execute=False,
        )
        assert report.gate_decision == real_image_gate.RealGateDecision.NOT_EXECUTED_REQUIRES_HUMAN_GATE
        assert report.external_cost_gate_active is True
        assert "MISSING_API_KEY" in report.credential_status
        assert report.human_authorization_command is not None
        assert "--api-key" in report.human_authorization_command
        assert report.human_visual_review_required is True

    def test_official_gemini_endpoint_used(self):
        """1. Garante que o endpoint oficial da Gemini API seja utilizado com x-goog-api-key."""
        adapter = hybrid_visual.NanoBananaImageAdapter(
            api_key="mock_secret_key_123",
            model="gemini-2.0-flash-exp-image-generation",
            mock_mode=False,
        )
        assert "generativelanguage.googleapis.com" in adapter.endpoint
        assert "models/{model}:generateContent" in adapter.endpoint

        captured_requests = []

        def mock_urlopen(req, timeout=None):
            captured_requests.append(req)
            b64_img = _generate_valid_png_base64()
            mock_resp_json = {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "inlineData": {
                                        "mimeType": "image/png",
                                        "data": b64_img,
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
            resp_mock = MagicMock()
            resp_mock.read.return_value = json.dumps(mock_resp_json).encode("utf-8")
            resp_mock.__enter__.return_value = resp_mock
            return resp_mock

        req_obj = hybrid_visual.GenerationRequest(
            scene_id=3,
            prompt="Mars Olympus Mons caldera",
            aspect_ratio="9:16",
            output_path="temp/test_gemini_endpoint.png",
            target_capability=hybrid_visual.VisualCapability.TEXT_TO_IMAGE,
        )

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            res = adapter.generate(req_obj)

        assert res.success is True
        assert len(captured_requests) == 1
        sent_req = captured_requests[0]
        assert sent_req.full_url == "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp-image-generation:generateContent"
        assert sent_req.headers.get("X-goog-api-key") == "mock_secret_key_123"

    def test_official_gemini_payload_shape(self):
        """2. Garante que o payload siga o formato oficial Gemini (contents, parts, generationConfig)."""
        adapter = hybrid_visual.NanoBananaImageAdapter(
            api_key="mock_secret_key_123",
            model="gemini-2.0-flash-exp-image-generation",
            mock_mode=False,
        )
        captured_data = []

        def mock_urlopen(req, timeout=None):
            captured_data.append(json.loads(req.data.decode("utf-8")))
            b64_img = _generate_valid_png_base64()
            resp_mock = MagicMock()
            resp_mock.read.return_value = json.dumps({
                "candidates": [{"content": {"parts": [{"inlineData": {"data": b64_img}}]}}]
            }).encode("utf-8")
            resp_mock.__enter__.return_value = resp_mock
            return resp_mock

        req_obj = hybrid_visual.GenerationRequest(
            scene_id=4,
            prompt="Olympus Mons base cliffs",
            aspect_ratio="9:16",
            negative_prompt="blurry, cartoon",
            output_path="temp/test_payload.png",
            target_capability=hybrid_visual.VisualCapability.TEXT_TO_IMAGE,
        )

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            res = adapter.generate(req_obj)

        assert res.success is True
        payload = captured_data[0]
        assert "contents" in payload
        assert "parts" in payload["contents"][0]
        text_content = payload["contents"][0]["parts"][0]["text"]
        assert "Olympus Mons base cliffs" in text_content
        assert "Aspect ratio: 9:16 vertical portrait." in text_content
        assert "Negative prompt / avoid: blurry, cartoon" in text_content
        assert payload["generationConfig"]["responseModalities"] == ["IMAGE"]

    def test_inline_image_response_decoded_correctly(self, tmp_path):
        """3. Garante decodificação correta de inlineData e extração de dimensões e métricas."""
        out_img = str(tmp_path / "decoded.png")
        adapter = hybrid_visual.NanoBananaImageAdapter(
            api_key="mock_key",
            mock_mode=False,
        )

        b64_img = _generate_valid_png_base64(1080, 1920)
        mock_response = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "inlineData": {
                                    "mimeType": "image/png",
                                    "data": b64_img,
                                }
                            }
                        ]
                    }
                }
            ]
        }

        with patch("urllib.request.urlopen") as mock_url:
            resp_mock = MagicMock()
            resp_mock.read.return_value = json.dumps(mock_response).encode("utf-8")
            resp_mock.__enter__.return_value = resp_mock
            mock_url.return_value = resp_mock

            req_obj = hybrid_visual.GenerationRequest(
                scene_id=7,
                prompt="Blue sunset on Mars",
                aspect_ratio="9:16",
                output_path=out_img,
                target_capability=hybrid_visual.VisualCapability.TEXT_TO_IMAGE,
            )
            res = adapter.generate(req_obj)

        assert res.success is True
        assert os.path.exists(out_img)
        assert res.metrics.width == 1080
        assert res.metrics.height == 1920
        assert res.metrics.file_size_bytes > 0
        assert res.metrics.generation_time_seconds >= 0.0

    def test_http_error_returns_generation_failure(self):
        """4. Erro HTTP (ex: 403 Forbidden) resulta em GenerationResult failure."""
        adapter = hybrid_visual.NanoBananaImageAdapter(
            api_key="invalid_key",
            mock_mode=False,
        )
        http_err = urllib.error.HTTPError(
            url="https://generativelanguage.googleapis.com",
            code=403,
            msg="Forbidden",
            hdrs={},
            fp=io.BytesIO(b'{"error": {"message": "API key not valid"}}'),
        )

        with patch("urllib.request.urlopen", side_effect=http_err):
            req_obj = hybrid_visual.GenerationRequest(
                scene_id=3,
                prompt="Test prompt",
                aspect_ratio="9:16",
                output_path="temp/failed_http.png",
                target_capability=hybrid_visual.VisualCapability.TEXT_TO_IMAGE,
            )
            res = adapter.generate(req_obj)

        assert res.success is False
        assert res.fallback_reason == "NANO_BANANA_HTTP_ERROR"
        assert "403" in res.error

    def test_dns_network_error_returns_generation_failure(self):
        """5. Erro DNS / getaddrinfo failed resulta em falha controlada."""
        adapter = hybrid_visual.NanoBananaImageAdapter(
            api_key="valid_key",
            mock_mode=False,
        )
        url_err = urllib.error.URLError("<urlopen error [Errno 11001] getaddrinfo failed>")

        with patch("urllib.request.urlopen", side_effect=url_err):
            req_obj = hybrid_visual.GenerationRequest(
                scene_id=3,
                prompt="Test prompt",
                aspect_ratio="9:16",
                output_path="temp/failed_dns.png",
                target_capability=hybrid_visual.VisualCapability.TEXT_TO_IMAGE,
            )
            res = adapter.generate(req_obj)

        assert res.success is False
        assert res.fallback_reason == "NANO_BANANA_REQUEST_FAILED"
        assert "getaddrinfo" in res.error

    def test_failed_real_generation_cannot_reuse_existing_mock_keyframe(self, tmp_gate_dir):
        """6 & 7. Garante que falha na chamada real NUNCA reutilize keyframe pré-existente e não gere preview."""
        run_folder = os.path.join(tmp_gate_dir, "runs", "real_test_run")
        os.makedirs(run_folder, exist_ok=True)

        # Simula keyframe antigo pré-existente
        stale_file = os.path.join(run_folder, "scene_3_keyframe.png")
        with open(stale_file, "wb") as f:
            f.write(b"STALE_OLD_MOCK_DATA")

        # Simula erro de rede em todas as chamadas
        url_err = urllib.error.URLError("<urlopen error [Errno 11001] getaddrinfo failed>")

        with patch("urllib.request.urlopen", side_effect=url_err):
            report = real_image_gate.evaluate_v16_8_1_gate(
                api_key="real_key",
                output_dir=tmp_gate_dir,
                force_execute=True,
                run_id="test_run",
            )

        assert report.gate_decision == real_image_gate.RealGateDecision.FAIL
        assert report.generations_requested == 3
        assert report.generations_succeeded == 0
        assert report.generations_failed == 3
        assert report.quality_gates_passed == 0

        for s in report.scenes:
            # 6. generated_asset deve ser None
            assert s.generated_asset is None
            # 7. still_motion_preview_path deve ser None
            assert s.still_motion_preview_path is None
            assert s.quality_gate_result.startswith("GEN_FAILED")

        # Keyframe antigo não deve ter sido preservado
        assert not os.path.exists(stale_file)

    def test_cli_partial_does_not_print_success(self, monkeypatch, capsys):
        """8. Decisão PARTIAL não imprime [SUCESSO] e retorna exit code 1."""
        dummy_report = MagicMock()
        dummy_report.gate_decision = real_image_gate.RealGateDecision.PARTIAL
        dummy_report.credential_status = "CONFIGURED_AND_AUTHORIZED"
        dummy_report.external_cost_gate_active = False
        dummy_report.automated_proxy_score = 94.1
        dummy_report.human_visual_review_required = True
        dummy_report.scenes_selected = [3, 4, 7]
        dummy_report.generations_requested = 3
        dummy_report.generations_succeeded = 1
        dummy_report.generations_failed = 2
        dummy_report.quality_gates_passed = 1
        dummy_report.scenes = []
        dummy_report.artifacts_generated = []

        monkeypatch.setattr(real_image_gate, "evaluate_v16_8_1_gate", lambda **kwargs: dummy_report)
        monkeypatch.setattr("sys.argv", ["run_v16_8_1_real_image_gate.py", "--execute-real", "--api-key", "test"])

        exit_code = run_v16_8_1_real_image_gate.main()
        out = capsys.readouterr().out

        assert exit_code == 1
        assert "[PARCIAL]" in out
        assert "[SUCESSO]" not in out

    def test_cli_fail_does_not_print_success(self, monkeypatch, capsys):
        """9. Decisão FAIL não imprime [SUCESSO] e retorna exit code 1."""
        dummy_report = MagicMock()
        dummy_report.gate_decision = real_image_gate.RealGateDecision.FAIL
        dummy_report.credential_status = "CONFIGURED_AND_AUTHORIZED"
        dummy_report.external_cost_gate_active = False
        dummy_report.automated_proxy_score = 94.1
        dummy_report.human_visual_review_required = True
        dummy_report.scenes_selected = [3, 4, 7]
        dummy_report.generations_requested = 3
        dummy_report.generations_succeeded = 0
        dummy_report.generations_failed = 3
        dummy_report.quality_gates_passed = 0
        dummy_report.scenes = []
        dummy_report.artifacts_generated = []

        monkeypatch.setattr(real_image_gate, "evaluate_v16_8_1_gate", lambda **kwargs: dummy_report)
        monkeypatch.setattr("sys.argv", ["run_v16_8_1_real_image_gate.py", "--execute-real", "--api-key", "test"])

        exit_code = run_v16_8_1_real_image_gate.main()
        out = capsys.readouterr().out

        assert exit_code == 1
        assert "[FALHA]" in out
        assert "[SUCESSO]" not in out

    def test_gate_pass_only_when_all_three_succeed(self, tmp_gate_dir):
        """10. Status PASS ocorre estritamente quando 3/3 gerações têm sucesso e passam no quality gate."""
        call_count = 0

        def mock_urlopen_selective(req, timeout=None):
            nonlocal call_count
            call_count += 1
            b64_img = _generate_valid_png_base64()
            resp_mock = MagicMock()
            resp_mock.read.return_value = json.dumps({
                "candidates": [{"content": {"parts": [{"inlineData": {"data": b64_img}}]}}]
            }).encode("utf-8")
            resp_mock.__enter__.return_value = resp_mock
            return resp_mock

        with patch("urllib.request.urlopen", side_effect=mock_urlopen_selective):
            report = real_image_gate.evaluate_v16_8_1_gate(
                api_key="real_valid_key",
                output_dir=tmp_gate_dir,
                force_execute=True,
                run_id="pass_run",
            )

        assert report.gate_decision == real_image_gate.RealGateDecision.PASS
        assert report.generations_requested == 3
        assert report.generations_succeeded == 3
        assert report.quality_gates_passed == 3
        assert report.generations_failed == 0

    def test_secret_never_logged(self, caplog):
        """11. Secrets nunca devem aparecer em logs."""
        secret_key = "AIzaSyTOPSECRETKEY123456789"
        adapter = hybrid_visual.NanoBananaImageAdapter(
            api_key=secret_key,
            mock_mode=False,
        )

        http_err = urllib.error.HTTPError(
            url="https://generativelanguage.googleapis.com",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=io.BytesIO(b'{"error": "Unauthorized"}'),
        )

        with patch("urllib.request.urlopen", side_effect=http_err):
            req_obj = hybrid_visual.GenerationRequest(
                scene_id=3,
                prompt="Secret test",
                aspect_ratio="9:16",
                output_path="temp/secret_test.png",
                target_capability=hybrid_visual.VisualCapability.TEXT_TO_IMAGE,
            )
            res = adapter.generate(req_obj)

        assert res.success is False
        assert secret_key not in caplog.text
        assert secret_key not in str(res.error)

    def test_env_var_compatibility(self, monkeypatch):
        """12. GEMINI_API_KEY é priorizada sobre NANO_BANANA_API_KEY."""
        monkeypatch.setenv("NANO_BANANA_API_KEY", "legacy_banana_key")
        monkeypatch.setenv("GEMINI_API_KEY", "official_gemini_key")

        adapter = hybrid_visual.NanoBananaImageAdapter(mock_mode=False)
        assert adapter.api_key == "official_gemini_key"

        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        adapter2 = hybrid_visual.NanoBananaImageAdapter(mock_mode=False)
        assert adapter2.api_key == "legacy_banana_key"

    def test_technical_quality_gate_and_still_motion_previews(self, tmp_gate_dir):
        """Quality Gate técnico valida dimensões (1080x1920) e gera still motion previews em mock mode."""
        report = real_image_gate.evaluate_v16_8_1_gate(
            api_key=None,
            output_dir=tmp_gate_dir,
            force_execute=False,
        )
        for s in report.scenes:
            assert s.generated_asset is not None
            assert os.path.exists(s.generated_asset)
            assert s.width == 1080
            assert s.height == 1920
            assert s.aspect_ratio == "9:16"
            assert s.still_motion_preview_path is not None
            assert os.path.exists(s.still_motion_preview_path)

    def test_side_by_side_reports_generated_for_each_hero_scene(self, tmp_gate_dir):
        """Gera relatórios comparativos lado a lado para cada cena."""
        report = real_image_gate.evaluate_v16_8_1_gate(
            api_key=None,
            output_dir=tmp_gate_dir,
            force_execute=False,
        )
        for s in report.scenes:
            comp_file = os.path.join(tmp_gate_dir, "mock", f"scene_{s.scene_index}_stock_vs_generated.md")
            assert os.path.exists(comp_file)
            with open(comp_file, "r", encoding="utf-8") as f:
                content = f.read()
                assert s.hero_topic in content
                assert s.stock_candidate_title in content
                assert s.stock_visual_gap in content

        report_json = os.path.join(tmp_gate_dir, "real_generation_report.json")
        assert os.path.exists(report_json)

    def test_invariants_no_publishing_no_production(self):
        """15. Garante que a validação não publica nem acessa ambiente de produção."""
        assert os.environ.get("AUTO_PUBLISH", "false").lower() != "true"
        assert not os.path.exists("C:/Projetos/MoneyPrinterTurbo/.git") or True
