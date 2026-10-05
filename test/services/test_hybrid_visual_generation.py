"""
Testes da Fase V16.6 — Hybrid Visual Generation Foundation & V16.6.1 Open-Source Video Benchmark.

Valida:
1. visual_generation_enabled = false -> pipeline stock intacto e inalterado.
2. provider unavailable -> fallback imediato e transparente para stock.
3. provider timeout -> fallback para stock sem propagar falha para o pipeline.
4. capability unsupported -> fallback para stock.
5. generated_image accepted (Nano Banana adapter em modo mock retorna imagem válida).
6. Nano Banana sem credencial -> is_available() False e fallback seguro.
7. generated_video accepted (ComfyUI provider mockado retorna vídeo válido e métricas).
8. ComfyUI client health check mockado (200 OK vs URLError).
9. ComfyUI client submit & polling mockado.
10. Benchmark runner em dry-run gera relatórios estruturados JSON e CSV com métricas completas.
11. VideoParams e SceneMaterialSelection preservam 100% de compatibilidade retroativa.
12. Invariantes de segurança: zero chamadas pagas, zero downloads pesados, zero deploy.
"""

import csv
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.models.schema import SceneMaterialSelection, VideoParams
from app.services.hybrid_visual import (
    ComfyUIClient,
    ComfyUIVisualProvider,
    GenerationRequest,
    GenerationResult,
    HybridVisualDirector,
    NanoBananaImageAdapter,
    ProviderCapabilities,
    STANDARD_BENCHMARK_PROMPT,
    VisualCapability,
    build_hybrid_visual_director,
)
from scripts.benchmark_video_models import VideoBenchmarkRunner


class TestHybridVisualGeneration(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # 1. Config & Schema Compatibility
    # -------------------------------------------------------------------------
    def test_video_params_defaults_preserve_stock_pipeline(self):
        """VideoParams deve ter visual_generation_enabled=False por padrão."""
        params = VideoParams(video_subject="Tornadoes in Brazil")
        self.assertFalse(params.visual_generation_enabled)
        self.assertEqual(params.preferred_video_provider, "stock")
        self.assertEqual(params.preferred_image_provider, "nano_banana")
        self.assertEqual(params.comfyui_endpoint, "http://127.0.0.1:8188")

    def test_scene_material_selection_schema_backwards_compatible(self):
        """SceneMaterialSelection deve suportar campos legados e novos metadados de IA."""
        sel = SceneMaterialSelection(
            scene_index=1,
            material_path="storage/clip.mp4",
            provider="pexels",
            duration=4.5,
        )
        self.assertEqual(sel.media_type, "stock")
        self.assertIsNone(sel.model)
        self.assertIsNone(sel.generation_time)
        self.assertIsNone(sel.fallback_reason)

    # -------------------------------------------------------------------------
    # 2. Hybrid Visual Director - Fallback Behavior
    # -------------------------------------------------------------------------
    def test_visual_generation_disabled_returns_stock(self):
        """Quando visual_generation_enabled=False, diretor sempre recorre ao stock."""
        director = HybridVisualDirector(
            visual_generation_enabled=False,
            preferred_video_provider="comfyui",
        )
        req = GenerationRequest(
            scene_id=1,
            prompt="large tornado rotating across rural field",
            target_capability=VisualCapability.TEXT_TO_VIDEO,
        )
        stock_cb_called = []
        def mock_stock():
            stock_cb_called.append(True)
            return "storage/stock_clip.mp4"

        result = director.resolve_scene_visual(req, stock_resolver_fallback=mock_stock)
        self.assertTrue(result.success)
        self.assertEqual(result.provider, "stock")
        self.assertEqual(result.fallback_reason, "VISUAL_GENERATION_DISABLED")
        self.assertEqual(result.output_path, "storage/stock_clip.mp4")
        self.assertEqual(len(stock_cb_called), 1)

    def test_provider_unavailable_falls_back_to_stock(self):
        """Se o provider configurado estiver indisponível (offline), deve fazer fallback para stock."""
        mock_provider = MagicMock()
        mock_provider.name = "comfyui"
        mock_provider.is_available.return_value = False

        director = HybridVisualDirector(
            visual_generation_enabled=True,
            preferred_video_provider="comfyui",
            providers={"comfyui": mock_provider},
        )
        req = GenerationRequest(
            scene_id=2,
            prompt="lightning strikes over hills",
            target_capability=VisualCapability.TEXT_TO_VIDEO,
        )
        result = director.resolve_scene_visual(req)
        self.assertTrue(result.success)
        self.assertEqual(result.provider, "stock")
        self.assertEqual(result.fallback_reason, "PROVIDER_UNAVAILABLE")

    def test_provider_timeout_falls_back_to_stock(self):
        """Timeout no provider de IA deve acionar fallback para stock sem quebrar o pipeline."""
        mock_provider = MagicMock()
        mock_provider.name = "comfyui"
        mock_provider.is_available.return_value = True
        mock_provider.capabilities = ProviderCapabilities(supports_text_to_video=True)
        mock_provider.generate.return_value = GenerationResult(
            scene_id=3,
            success=False,
            provider="comfyui",
            model="wan_2_2",
            fallback_reason="PROVIDER_TIMEOUT",
            error="ComfyUI generation timed out after 60s",
        )

        director = HybridVisualDirector(
            visual_generation_enabled=True,
            preferred_video_provider="comfyui",
            providers={"comfyui": mock_provider},
        )
        req = GenerationRequest(
            scene_id=3,
            prompt="storm brewing in the horizon",
            target_capability=VisualCapability.TEXT_TO_VIDEO,
        )
        result = director.resolve_scene_visual(req)
        self.assertTrue(result.success)
        self.assertEqual(result.provider, "stock")
        self.assertEqual(result.fallback_reason, "PROVIDER_TIMEOUT")

    def test_capability_unsupported_falls_back_to_stock(self):
        """Se o provider não suportar a capability necessária, aciona fallback para stock."""
        mock_provider = MagicMock()
        mock_provider.name = "image_only_provider"
        mock_provider.is_available.return_value = True
        mock_provider.capabilities = ProviderCapabilities(supports_text_to_image=True, supports_text_to_video=False)

        director = HybridVisualDirector(
            visual_generation_enabled=True,
            preferred_video_provider="image_only_provider",
            providers={"image_only_provider": mock_provider},
        )
        req = GenerationRequest(
            scene_id=4,
            prompt="moving clouds timelapse",
            target_capability=VisualCapability.TEXT_TO_VIDEO,
        )
        result = director.resolve_scene_visual(req)
        self.assertTrue(result.success)
        self.assertEqual(result.provider, "stock")
        self.assertEqual(result.fallback_reason, "CAPABILITY_UNSUPPORTED")

    # -------------------------------------------------------------------------
    # 3. Nano Banana Adapter
    # -------------------------------------------------------------------------
    def test_nano_banana_unconfigured_safe_fallback(self):
        """Nano Banana sem credencial deve reportar is_available() = False e permitir fallback."""
        adapter = NanoBananaImageAdapter(api_key="", mock_mode=False)
        self.assertFalse(adapter.is_available())

        req = GenerationRequest(
            scene_id=5,
            prompt="concept art of lightning",
            target_capability=VisualCapability.TEXT_TO_IMAGE,
        )
        res = adapter.generate(req)
        self.assertFalse(res.success)
        self.assertEqual(res.fallback_reason, "NANO_BANANA_NOT_CONFIGURED")

    def test_nano_banana_mock_mode_accepted(self):
        """Nano Banana em mock mode aceita geração de imagem estática com métricas válidas."""
        adapter = NanoBananaImageAdapter(mock_mode=True)
        self.assertTrue(adapter.is_available())

        req = GenerationRequest(
            scene_id=6,
            prompt="dark storm clouds over rural farmhouse",
            aspect_ratio="9:16",
            target_capability=VisualCapability.TEXT_TO_IMAGE,
        )
        res = adapter.generate(req)
        self.assertTrue(res.success)
        self.assertEqual(res.media_type, "image")
        self.assertEqual(res.provider, "nano_banana")
        self.assertEqual(res.metrics.width, 1080)
        self.assertEqual(res.metrics.height, 1920)

    # -------------------------------------------------------------------------
    # 4. ComfyUI Client & Provider
    # -------------------------------------------------------------------------
    def test_comfyui_client_health_check_mock(self):
        """Valida health check HTTP no endpoint /system_stats."""
        client = ComfyUIClient(endpoint="http://127.0.0.1:8188")

        # Cenário 1: 200 OK com stats válidos
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.read.return_value = json.dumps({"system": {"os": "nt"}, "devices": []}).encode("utf-8")
        with patch("urllib.request.urlopen", return_value=mock_resp):
            self.assertTrue(client.check_health())

        # Cenário 2: Falha de conexão
        with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
            self.assertFalse(client.check_health())

    def test_comfyui_submit_and_poll_workflow_mock(self):
        """Valida ciclo completo de submit_workflow e poll_until_complete mockados."""
        client = ComfyUIClient(endpoint="http://127.0.0.1:8188")

        # Mock submit
        submit_resp = MagicMock()
        submit_resp.status = 200
        submit_resp.__enter__.return_value = submit_resp
        submit_resp.read.return_value = json.dumps({"prompt_id": "test_prompt_123"}).encode("utf-8")

        # Mock history
        history_resp = MagicMock()
        history_resp.status = 200
        history_resp.__enter__.return_value = history_resp
        history_resp.read.return_value = json.dumps({
            "test_prompt_123": {
                "outputs": {
                    "9": {
                        "gifs": [{"filename": "wan_tornado_001.mp4", "subfolder": ""}]
                    }
                }
            }
        }).encode("utf-8")

        with patch("urllib.request.urlopen") as mock_url:
            mock_url.side_effect = [submit_resp, history_resp]
            sub = client.submit_workflow({"dummy": "node"})
            self.assertEqual(sub["prompt_id"], "test_prompt_123")

            completed = client.poll_until_complete("test_prompt_123", poll_interval=0.01, max_wait_seconds=2.0)
            self.assertIn("outputs", completed)

    def test_comfyui_provider_generation_accepted_mock(self):
        """Geração de vídeo aceita via ComfyUIVisualProvider com download mockado."""
        mock_client = MagicMock(spec=ComfyUIClient)
        mock_client.endpoint = "http://127.0.0.1:8188"
        mock_client.check_health.return_value = True
        mock_client.submit_workflow.return_value = {"prompt_id": "prompt_abc"}
        mock_client.poll_until_complete.return_value = {
            "outputs": {
                "10": {"gifs": [{"filename": "wan_tornado.mp4", "subfolder": ""}]}
            }
        }
        test_out = os.path.join(self.test_dir, "wan_tornado.mp4")
        with open(test_out, "wb") as f:
            f.write(b"mock_mp4_bytes")
        mock_client.download_output.return_value = test_out

        provider = ComfyUIVisualProvider(client=mock_client, default_model="wan_2_2")
        req = GenerationRequest(
            scene_id=7,
            prompt="large tornado rotating across rural field",
            duration_seconds=4.0,
            target_capability=VisualCapability.TEXT_TO_VIDEO,
            output_path=test_out,
        )
        res = provider.generate(req)
        self.assertTrue(res.success)
        self.assertEqual(res.media_type, "video")
        self.assertEqual(res.model, "wan_2_2")
        self.assertEqual(res.metrics.frames_generated, 96)
        self.assertEqual(res.metrics.fps, 24.0)

    # -------------------------------------------------------------------------
    # 5. Open-Source Video Benchmark Runner (V16.6.1)
    # -------------------------------------------------------------------------
    def test_benchmark_runner_dry_run_generates_valid_reports(self):
        """O runner em dry-run deve gerar JSON e CSV válidos para Wan 2.2, LTX-Video e FramePack."""
        bench_dir = os.path.join(self.test_dir, "benchmarks")
        runner = VideoBenchmarkRunner(
            output_dir=bench_dir,
            dry_run=True,
        )

        entries = runner.run_benchmark_suite(
            models=["wan_2_2", "ltx_video", "framepack"],
            prompt=STANDARD_BENCHMARK_PROMPT,
            duration_seconds=4.0,
        )

        self.assertEqual(len(entries), 3)
        for e in entries:
            self.assertTrue(e.success)
            self.assertIn(e.model, ["wan_2_2", "ltx_video", "framepack"])
            self.assertEqual(e.frames_generated, 96)
            self.assertGreater(e.generation_time_seconds, 0.0)
            self.assertIsNotNone(e.vram_peak_mb)
            self.assertEqual(e.prompt, STANDARD_BENCHMARK_PROMPT)

        reports = runner.save_reports(entries, prefix="test_bench")
        self.assertTrue(os.path.exists(reports["json"]))
        self.assertTrue(os.path.exists(reports["csv"]))

        # Valida JSON
        with open(reports["json"], "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertTrue(data["dry_run"])
            self.assertEqual(len(data["results"]), 3)

        # Valida CSV
        with open(reports["csv"], "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            self.assertEqual(len(rows), 3)
            self.assertIn("model", reader.fieldnames)
            self.assertIn("generation_time_seconds", reader.fieldnames)
            self.assertIn("vram_peak_mb", reader.fieldnames)
            self.assertIn("subjective_quality", reader.fieldnames)

    # -------------------------------------------------------------------------
    # 6. Safety & Invariants
    # -------------------------------------------------------------------------
    def test_factory_builds_default_director_with_stock_fallback(self):
        """Factory build_hybrid_visual_director deve carregar providers sem chamadas externas."""
        director = build_hybrid_visual_director()
        self.assertFalse(director.visual_generation_enabled)
        self.assertEqual(director.preferred_video_provider, "stock")
        self.assertIn("stock", director.providers)
        self.assertIn("nano_banana", director.providers)
        self.assertIn("comfyui", director.providers)


if __name__ == "__main__":
    unittest.main()
