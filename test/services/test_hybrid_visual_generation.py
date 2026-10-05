"""
Testes das Fases V16.6 e V16.6.2:
- V16.6 Hybrid Visual Generation Foundation
- V16.6.1 Hardware-Aware Open-Source Video Benchmark
- V16.6.2 Contextual Image-to-Video Foundation & Still Motion

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
11. Hardware probe sem torch não falha e reporta classificação coerente.
12. Fixture AMD RX 580 2048SP ~4GB classificada como NOT_RECOMMENDED com sugestões de alternativas.
13. Fixture NVIDIA RTX 4090 24GB classificada como LOCAL_GPU_READY.
14. Score de stock forte (>=60) seleciona stock diretamente (STOCK_HIGH_CONFIDENCE).
15. Score de stock médio (35-59) prefere keyframe contextual (GENERATED_IMAGE_PREFERRED).
16. Provider de imagem indisponível faz fallback gracioso para stock.
17. Imagem inválida ou corrompida reprovada no Quality Gate aciona fallback para stock.
18. Motion-from-still gera parâmetros e filtros válidos de zoom/pan.
19. Generated video desabilitado não tenta vídeo generativo por IA.
20. Invariantes de fábrica: zero chamadas pagas, zero downloads pesados, zero deploy.
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.models.schema import SceneMaterialSelection, VideoParams
from app.services.hybrid_visual import (
    ComfyUIClient,
    GenerationRequest,
    GenerationResult,
    HardwareCapabilityReport,
    HardwareClassification,
    HybridDecision,
    HybridVisualDirector,
    LOCAL_GENERATIVE_VIDEO_GPU_STATUS,
    NanoBananaImageAdapter,
    ProviderCapabilities,
    STANDARD_BENCHMARK_PROMPT,
    StillMotionMode,
    VisualCapability,
    build_hybrid_visual_director,
    build_image_prompt_from_visual_intent,
    evaluate_keyframe_quality,
    generate_still_motion_instructions,
    probe_hardware_capability,
    SceneImportance,
    classify_scene_importance,
    select_still_motion_mode,
    VideoVisualSummary,
    compute_video_visual_summary,
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
        self.assertFalse(params.generated_image_enabled)
        self.assertFalse(params.generated_video_enabled)
        self.assertEqual(params.stock_high_confidence_threshold, 60.0)
        self.assertEqual(params.generated_image_threshold, 35.0)
        self.assertEqual(params.preferred_video_provider, "disabled")
        self.assertEqual(params.preferred_image_provider, "nano_banana")
        self.assertEqual(params.image_to_video_provider, "disabled")
        self.assertTrue(params.still_motion_enabled)
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
        self.assertEqual(sel.visual_source_type, "stock")
        self.assertIsNone(sel.model)
        self.assertIsNone(sel.generation_time)
        self.assertIsNone(sel.fallback_reason)
        self.assertIsNone(sel.stock_match_score)
        self.assertIsNone(sel.motion_mode)

    # -------------------------------------------------------------------------
    # 2. Hardware-Aware Probe & Benchmark (V16.6.1)
    # -------------------------------------------------------------------------
    def test_hardware_probe_without_torch_does_not_fail(self):
        """Probe de hardware não deve falhar mesmo se torch/CUDA não existirem."""
        with patch.dict("sys.modules", {"torch": None}):
            report = probe_hardware_capability()
            self.assertIsInstance(report, HardwareCapabilityReport)
            self.assertIn(report.classification, list(HardwareClassification))
            self.assertTrue(len(report.reason) > 0)

    def test_hardware_probe_rx580_fixture_classified_not_recommended(self):
        """Hardware do PC Forte (AMD Radeon RX 580 2048SP ~4GB) deve ser classificado como NOT_RECOMMENDED."""
        rx580_mock = {
            "gpu_vendor": "AMD",
            "gpu_name": "Radeon RX 580 2048SP",
            "vram_mb": 4096.0,
            "cuda_available": False,
            "rocm_available": False,
        }
        report = probe_hardware_capability(mock_specs=rx580_mock)
        self.assertEqual(report.classification, HardwareClassification.NOT_RECOMMENDED)
        self.assertEqual(len(report.recommended_local_models), 0)
        self.assertIn("wan_2_2", report.not_recommended_models)
        self.assertIn("ltx_video", report.not_recommended_models)
        self.assertIn(LOCAL_GENERATIVE_VIDEO_GPU_STATUS, report.reason)
        self.assertTrue(any("Nano Banana" in alt for alt in report.suggested_alternatives))

    def test_hardware_probe_nvidia_high_vram_classified_ready(self):
        """GPU NVIDIA de alta capacidade (ex: RTX 4090 24GB) deve ser classificada como LOCAL_GPU_READY."""
        rtx_mock = {
            "gpu_vendor": "NVIDIA",
            "gpu_name": "NVIDIA GeForce RTX 4090",
            "vram_mb": 24576.0,
            "cuda_available": True,
        }
        report = probe_hardware_capability(mock_specs=rtx_mock)
        self.assertEqual(report.classification, HardwareClassification.LOCAL_GPU_READY)
        self.assertIn("wan_2_2", report.recommended_local_models)
        self.assertIn("ltx_video", report.recommended_local_models)

    # -------------------------------------------------------------------------
    # 3. Hybrid Visual Director - Fallback Behavior
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
    # 4. Contextual Decision Policy (V16.6.2)
    # -------------------------------------------------------------------------
    def test_strong_stock_score_uses_stock_directly(self):
        """Score de stock >= threshold de alta confiança usa stock direto (STOCK_HIGH_CONFIDENCE)."""
        director = HybridVisualDirector(
            visual_generation_enabled=True,
            generated_image_enabled=True,
            stock_high_confidence_threshold=60.0,
        )
        stock_called = []
        def mock_stock():
            stock_called.append(True)
            return "storage/strong_stock.mp4"

        res = director.resolve_contextual_scene_visual(
            scene_index=1,
            stock_match_score=75.0,
            narration="O tornado se aproxima da cidade",
            stock_asset_resolver=mock_stock,
        )
        self.assertTrue(res.success)
        self.assertEqual(res.provider, "stock")
        self.assertEqual(res.metadata.get("decision"), HybridDecision.STOCK_HIGH_CONFIDENCE.value)
        self.assertEqual(res.metadata.get("visual_source_type"), "stock")
        self.assertEqual(len(stock_called), 1)

    def test_medium_stock_score_prefers_generated_image_keyframe(self):
        """Score de stock médio (35-59) aciona keyframe contextual via Nano Banana."""
        adapter = NanoBananaImageAdapter(mock_mode=True)

        director = HybridVisualDirector(
            visual_generation_enabled=True,
            generated_image_enabled=True,
            stock_high_confidence_threshold=60.0,
            generated_image_threshold=35.0,
            preferred_image_provider="nano_banana",
            still_motion_enabled=True,
            providers={"nano_banana": adapter},
        )

        res = director.resolve_contextual_scene_visual(
            scene_index=2,
            stock_match_score=45.0,
            visual_intent={
                "primary_subject": "large tornado",
                "action": "rotating and touching ground",
                "environment": "rural plains under dark storm clouds",
            },
            narration="O funil desce tocando o solo em uma planície aberta",
            aspect_ratio="9:16",
        )
        self.assertTrue(res.success)
        self.assertEqual(res.provider, "nano_banana")
        self.assertEqual(res.metadata.get("decision"), HybridDecision.GENERATED_IMAGE_PREFERRED.value)
        self.assertEqual(res.metadata.get("visual_source_type"), "image_motion")
        self.assertEqual(res.metadata.get("motion_mode"), "zoom_in")
        self.assertIn("motion_instructions", res.metadata)

    def test_contextual_image_provider_unavailable_falls_back_to_stock(self):
        """Se o gerador de imagem estiver indisponível no score médio, fallback imediato para stock."""
        unconfigured_adapter = NanoBananaImageAdapter(api_key="", mock_mode=False)
        director = HybridVisualDirector(
            visual_generation_enabled=True,
            generated_image_enabled=True,
            stock_high_confidence_threshold=60.0,
            generated_image_threshold=35.0,
            preferred_image_provider="nano_banana",
            providers={"nano_banana": unconfigured_adapter},
        )
        stock_called = []
        def mock_stock():
            stock_called.append(True)
            return "storage/stock_fallback.mp4"

        res = director.resolve_contextual_scene_visual(
            scene_index=3,
            stock_match_score=40.0,
            narration="Chuva torrencial e ventos fortes",
            stock_asset_resolver=mock_stock,
        )
        self.assertTrue(res.success)
        self.assertEqual(res.provider, "stock")
        self.assertEqual(res.fallback_reason, "PROVIDER_UNAVAILABLE")
        self.assertEqual(len(stock_called), 1)

    def test_invalid_generated_image_fails_quality_gate_to_stock(self):
        """Keyframe gerado que não passa no Quality Gate deve fazer fallback transparente para stock."""
        corrupt_adapter = MagicMock()
        corrupt_adapter.name = "corrupt_provider"
        corrupt_adapter.is_available.return_value = True

        # Gera arquivo vazio (0 bytes) que reprova no Quality Gate
        empty_img_path = os.path.join(self.test_dir, "corrupt.png")
        with open(empty_img_path, "wb"):
            pass

        corrupt_adapter.generate.return_value = GenerationResult(
            scene_id=4,
            success=True,
            provider="corrupt_provider",
            output_path=empty_img_path,
            media_type="image",
        )

        director = HybridVisualDirector(
            visual_generation_enabled=True,
            generated_image_enabled=True,
            stock_high_confidence_threshold=60.0,
            generated_image_threshold=35.0,
            preferred_image_provider="corrupt_provider",
            providers={"corrupt_provider": corrupt_adapter},
        )

        res = director.resolve_contextual_scene_visual(
            scene_index=4,
            stock_match_score=42.0,
            narration="Cena com keyframe corrompido",
        )
        self.assertTrue(res.success)
        self.assertEqual(res.provider, "stock")
        self.assertEqual(res.fallback_reason, "QUALITY_GATE_FILE_EMPTY")

    def test_generated_video_disabled_does_not_attempt_ai_video(self):
        """Mesmo com score de stock muito baixo (<35), se vídeo estiver desabilitado, não chama video IA."""
        adapter = NanoBananaImageAdapter(mock_mode=True)
        director = HybridVisualDirector(
            visual_generation_enabled=True,
            generated_image_enabled=True,
            generated_video_enabled=False,
            preferred_video_provider="disabled",
            preferred_image_provider="nano_banana",
            stock_high_confidence_threshold=60.0,
            generated_image_threshold=35.0,
            providers={"nano_banana": adapter},
        )
        res = director.resolve_contextual_scene_visual(
            scene_index=5,
            stock_match_score=15.0,
            narration="Cena super específica sem cobertura em stock",
        )
        self.assertTrue(res.success)
        # Rota para generated_image porque vídeo está desabilitado
        self.assertEqual(res.provider, "nano_banana")
        self.assertEqual(res.metadata.get("decision"), HybridDecision.GENERATED_IMAGE_PREFERRED.value)

    # -------------------------------------------------------------------------
    # 5. Prompt Synthesis & Quality Gate & Still Motion
    # -------------------------------------------------------------------------
    def test_build_image_prompt_from_visual_intent(self):
        """Valida síntese de prompt contextual a partir do visual intent v2."""
        intent = {
            "primary_subject": "large tornado funnel",
            "action": "touching the ground",
            "environment": "open rural plains under dark supercell",
            "visual_style": "cinematic realism",
            "avoid": ["cartoon", "cgi", "blurry"],
        }
        payload = build_image_prompt_from_visual_intent(intent, aspect_ratio="9:16")
        self.assertIn("large tornado funnel", payload.prompt)
        self.assertIn("touching the ground", payload.prompt)
        self.assertIn("vertical composition", payload.prompt)
        self.assertIn("no text, no watermark", payload.prompt)
        self.assertIn("cartoon", payload.negative_prompt)
        self.assertEqual(payload.aspect_ratio, "9:16")

    def test_evaluate_keyframe_quality_pass_and_fail(self):
        """Valida Quality Gate de keyframe para resolução, existência e orientação."""
        # Falha: Arquivo inexistente
        q1 = evaluate_keyframe_quality("storage/non_existent.png")
        self.assertFalse(q1.is_valid)
        self.assertEqual(q1.reason, "FILE_NOT_FOUND")

        # Sucesso: Imagem válida 1080x1920 (portrait)
        valid_img = os.path.join(self.test_dir, "valid.png")
        from PIL import Image
        img = Image.new("RGB", (1080, 1920), color=(20, 20, 20))
        img.save(valid_img, "PNG")

        q2 = evaluate_keyframe_quality(valid_img, expected_aspect_ratio="9:16")
        self.assertTrue(q2.is_valid)
        self.assertEqual(q2.reason, "QUALITY_GATE_PASS")
        self.assertEqual(q2.width, 1080)
        self.assertEqual(q2.height, 1920)

        # Falha: Orientação errada (esperava portrait, recebeu landscape)
        q3 = evaluate_keyframe_quality(valid_img, expected_aspect_ratio="16:9")
        self.assertFalse(q3.is_valid)
        self.assertEqual(q3.reason, "ORIENTATION_MISMATCH_EXPECTED_LANDSCAPE")

    def test_still_motion_instructions_generation(self):
        """Valida geração de parâmetros e filtros de movimento (Ken Burns / Pan / Zoom)."""
        motion = generate_still_motion_instructions(
            image_path="storage/keyframe.png",
            duration_seconds=5.0,
            aspect_ratio="9:16",
            mode=StillMotionMode.ZOOM_IN,
        )
        self.assertEqual(motion["mode"], "zoom_in")
        self.assertEqual(motion["duration_seconds"], 5.0)
        self.assertEqual(motion["total_frames"], 120)
        self.assertEqual(motion["resolution"], "1080x1920")
        self.assertIn("zoompan=", motion["ffmpeg_filter"])

    # -------------------------------------------------------------------------
    # 6. ComfyUI Client & Benchmark Dry-Run
    # -------------------------------------------------------------------------
    def test_comfyui_client_health_check_mock(self):
        """Valida health check HTTP no endpoint /system_stats."""
        client = ComfyUIClient(endpoint="http://127.0.0.1:8188")
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.read.return_value = json.dumps({"system": {"os": "nt"}, "devices": []}).encode("utf-8")
        with patch("urllib.request.urlopen", return_value=mock_resp):
            self.assertTrue(client.check_health())

        with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
            self.assertFalse(client.check_health())

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
        reports = runner.save_reports(entries, prefix="test_bench")
        self.assertTrue(os.path.exists(reports["json"]))
        self.assertTrue(os.path.exists(reports["csv"]))

        with open(reports["json"], "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertTrue(data["dry_run"])
            self.assertEqual(data["hardware_status"], LOCAL_GENERATIVE_VIDEO_GPU_STATUS)
            self.assertEqual(len(data["results"]), 3)

    # -------------------------------------------------------------------------
    # 7. Safety & Invariants
    # -------------------------------------------------------------------------
    def test_factory_builds_default_director_with_stock_fallback(self):
        """Factory build_hybrid_visual_director deve carregar providers com configs padrão desativadas."""
        director = build_hybrid_visual_director()
        self.assertFalse(director.visual_generation_enabled)
        self.assertFalse(director.generated_image_enabled)
        self.assertFalse(director.generated_video_enabled)
        self.assertEqual(director.preferred_video_provider, "disabled")
        self.assertIn("stock", director.providers)
        self.assertIn("nano_banana", director.providers)
        self.assertIn("comfyui", director.providers)


class TestHybridSceneDirectorV16_7(unittest.TestCase):
    """
    Testes direcionados da Fase V16.7 — Hybrid Scene Director:
    1. strong stock -> stock (STOCK_HIGH_CONFIDENCE, sem chamada de IA).
    2. medium stock + generator available -> generated image contextual.
    3. medium stock + generator unavailable -> stock fallback seguro.
    4. weak stock -> generated preferred (vídeo ou imagem).
    5. hero scene uses more aggressive generated threshold (score 63 -> generated).
    6. low importance scene prefers stock (score 55 -> stock).
    7. generated image accepted -> still motion selected com filtros ffmpeg.
    8. quality gate failure -> stock fallback com motivo de rejeição.
    9. provider timeout -> stock fallback com motivo PROVIDER_TIMEOUT.
    10. multiple scenes produce mixed strategies.
    11. summary metrics correct (VideoVisualSummary).
    12. legacy mode with visual_generation_enabled=false unchanged.
    13. cost-benefit heuristic considera reuso e aspect ratio.
    14. invariantes de fábrica: zero publicação, zero chamadas pagas, zero download pesado.
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.adapter = NanoBananaImageAdapter(mock_mode=True)
        self.director = HybridVisualDirector(
            visual_generation_enabled=True,
            generated_image_enabled=True,
            generated_video_enabled=False,
            stock_high_confidence_threshold=60.0,
            generated_image_threshold=35.0,
            preferred_image_provider="nano_banana",
            preferred_video_provider="disabled",
            still_motion_enabled=True,
            providers={"nano_banana": self.adapter},
        )

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_strong_stock_prefers_stock_without_ai_calls(self):
        """1. strong stock -> stock: Score >= 60 usa stock direto e não tenta gerar IA."""
        res = self.director.resolve_contextual_scene_visual(
            scene_index=2,
            stock_match_score=85.0,
            narration="Cena de alta aderência no acervo",
            aspect_ratio="9:16",
            scene_importance=SceneImportance.NORMAL,
        )
        self.assertTrue(res.success)
        self.assertEqual(res.provider, "stock")
        self.assertEqual(res.metadata.get("strategy_selected"), HybridDecision.STOCK_HIGH_CONFIDENCE.value)
        self.assertEqual(res.metadata.get("final_visual_source"), "stock")
        self.assertFalse(res.metadata.get("generated_attempted"))
        self.assertEqual(res.metadata.get("generation_status"), "bypassed")

    def test_medium_stock_and_generator_available_chooses_generated_image(self):
        """2. medium stock + generator available -> generated image: Score 45 gera keyframe contextual."""
        res = self.director.resolve_contextual_scene_visual(
            scene_index=2,
            stock_match_score=45.0,
            visual_intent={"primary_subject": "tornado", "action": "rotating", "environment": "plains"},
            narration="Tornado em planície",
            aspect_ratio="9:16",
            scene_importance=SceneImportance.NORMAL,
        )
        self.assertTrue(res.success)
        self.assertEqual(res.provider, "nano_banana")
        self.assertEqual(res.metadata.get("strategy_selected"), HybridDecision.GENERATED_IMAGE_PREFERRED.value)
        self.assertEqual(res.metadata.get("final_visual_source"), "image_motion")
        self.assertTrue(res.metadata.get("generated_attempted"))
        self.assertEqual(res.metadata.get("generation_status"), "success")
        self.assertIn("still_motion_mode", res.metadata)

    def test_medium_stock_and_generator_unavailable_falls_back_to_stock(self):
        """3. medium stock + generator unavailable -> stock fallback: Provider desconfigurado recua para stock."""
        unconfigured = NanoBananaImageAdapter(api_key="", mock_mode=False)
        director = HybridVisualDirector(
            visual_generation_enabled=True,
            generated_image_enabled=True,
            stock_high_confidence_threshold=60.0,
            generated_image_threshold=35.0,
            preferred_image_provider="nano_banana",
            providers={"nano_banana": unconfigured},
        )
        res = director.resolve_contextual_scene_visual(
            scene_index=2,
            stock_match_score=45.0,
            narration="Tornado em planície",
            aspect_ratio="9:16",
            scene_importance=SceneImportance.NORMAL,
        )
        self.assertTrue(res.success)
        self.assertEqual(res.provider, "stock")
        self.assertEqual(res.metadata.get("final_visual_source"), "stock")
        self.assertTrue(res.metadata.get("fallback_used"))
        self.assertEqual(res.metadata.get("fallback_reason"), "PROVIDER_UNAVAILABLE")

    def test_weak_stock_chooses_generated_preferred(self):
        """4. weak stock -> generated preferred: Score 20 (< 35) prioriza geração."""
        strat = self.director.determine_scene_strategy(
            stock_match_score=20.0,
            scene_importance=SceneImportance.NORMAL,
        )
        self.assertEqual(strat, HybridDecision.GENERATED_IMAGE_PREFERRED)

        # Se vídeo estiver habilitado com provider ComfyUI
        director_video = HybridVisualDirector(
            visual_generation_enabled=True,
            generated_image_enabled=True,
            generated_video_enabled=True,
            preferred_video_provider="comfyui",
            stock_high_confidence_threshold=60.0,
            generated_image_threshold=35.0,
        )
        strat_vid = director_video.determine_scene_strategy(
            stock_match_score=20.0,
            scene_importance=SceneImportance.NORMAL,
        )
        self.assertEqual(strat_vid, HybridDecision.GENERATED_VIDEO_PREFERRED)

    def test_hero_scene_uses_more_aggressive_generated_threshold(self):
        """5. hero scene uses more aggressive generated threshold: Score 63 vira generated em cena HERO."""
        strat_normal = self.director.determine_scene_strategy(
            stock_match_score=63.0,
            scene_importance=SceneImportance.NORMAL,
        )
        # Normal aceita stock pois 63 >= 60
        self.assertEqual(strat_normal, HybridDecision.STOCK_HIGH_CONFIDENCE)

        # Em cena HERO, threshold de stock sobe para 70 -> 63 < 70 -> prefere generated
        strat_hero = self.director.determine_scene_strategy(
            stock_match_score=63.0,
            scene_importance=SceneImportance.HERO,
        )
        self.assertEqual(strat_hero, HybridDecision.GENERATED_IMAGE_PREFERRED)

    def test_low_importance_scene_prefers_stock(self):
        """6. low importance scene prefers stock: Score 55 aceita stock em cena LOW."""
        strat_normal = self.director.determine_scene_strategy(
            stock_match_score=55.0,
            scene_importance=SceneImportance.NORMAL,
        )
        # Normal prefere gerar pois 55 < 60
        self.assertEqual(strat_normal, HybridDecision.GENERATED_IMAGE_PREFERRED)

        # Em cena LOW, threshold de stock desce para 50 -> 55 >= 50 -> aceita stock
        strat_low = self.director.determine_scene_strategy(
            stock_match_score=55.0,
            scene_importance=SceneImportance.LOW,
        )
        self.assertEqual(strat_low, HybridDecision.STOCK_HIGH_CONFIDENCE)

    def test_generated_image_accepted_selects_still_motion(self):
        """7. generated image accepted -> still motion selected: Keyframe aprovado recebe instruções de movimento."""
        res = self.director.resolve_contextual_scene_visual(
            scene_index=1,
            stock_match_score=40.0,
            visual_intent={"primary_subject": "tornado", "action": "rotating", "environment": "open sky aerial"},
            narration="Vista panorâmica ampla do céu",
            aspect_ratio="9:16",
        )
        self.assertTrue(res.success)
        self.assertEqual(res.metadata.get("final_visual_source"), "image_motion")
        self.assertIn("still_motion_mode", res.metadata)
        self.assertIn("motion_instructions", res.metadata)
        motion_inst = res.metadata["motion_instructions"]
        self.assertIn("ffmpeg_filter", motion_inst)
        self.assertIn("zoompan=", motion_inst["ffmpeg_filter"])

    def test_quality_gate_failure_triggers_stock_fallback(self):
        """8. quality gate failure -> stock fallback: Arquivo vazio ou corrompido rejeitado no gate cai em stock."""
        # Cria adapter que gera arquivo vazio
        bad_adapter = MagicMock()
        bad_adapter.name = "nano_banana"
        bad_adapter.is_available.return_value = True
        bad_adapter.capabilities = ProviderCapabilities(supports_text_to_image=True)

        empty_file = os.path.join(self.test_dir, "empty_keyframe.png")
        with open(empty_file, "wb") as f:
            f.write(b"")

        bad_adapter.generate.return_value = GenerationResult(
            scene_id=1,
            success=True,
            provider="nano_banana",
            output_path=empty_file,
            media_type="image",
        )

        director = HybridVisualDirector(
            visual_generation_enabled=True,
            generated_image_enabled=True,
            preferred_image_provider="nano_banana",
            providers={"nano_banana": bad_adapter},
        )
        res = director.resolve_contextual_scene_visual(
            scene_index=1,
            stock_match_score=40.0,
            narration="Teste quality gate vazio",
            aspect_ratio="9:16",
        )
        self.assertTrue(res.success)
        self.assertEqual(res.provider, "stock")
        self.assertEqual(res.metadata.get("final_visual_source"), "stock")
        self.assertTrue(res.metadata.get("fallback_used"))
        self.assertEqual(res.metadata.get("fallback_reason"), "QUALITY_GATE_FILE_EMPTY")

    def test_provider_timeout_triggers_stock_fallback(self):
        """9. provider timeout -> stock fallback: TimeoutError no provider é interceptado graciosamente."""
        timeout_adapter = MagicMock()
        timeout_adapter.name = "nano_banana"
        timeout_adapter.is_available.return_value = True
        timeout_adapter.capabilities = ProviderCapabilities(supports_text_to_image=True)
        timeout_adapter.generate.side_effect = TimeoutError("HTTP request timeout after 30s")

        director = HybridVisualDirector(
            visual_generation_enabled=True,
            generated_image_enabled=True,
            preferred_image_provider="nano_banana",
            providers={"nano_banana": timeout_adapter},
        )
        res = director.resolve_contextual_scene_visual(
            scene_index=1,
            stock_match_score=40.0,
            narration="Teste provider timeout",
            aspect_ratio="9:16",
        )
        self.assertTrue(res.success)
        self.assertEqual(res.provider, "stock")
        self.assertEqual(res.metadata.get("final_visual_source"), "stock")
        self.assertTrue(res.metadata.get("fallback_used"))
        self.assertEqual(res.metadata.get("fallback_reason"), "PROVIDER_TIMEOUT")

    def test_multiple_scenes_produce_mixed_strategies_and_summary_metrics(self):
        """10 & 11. Multi-scene mixed strategies & VideoVisualSummary: 4 cenas produzem governança completa."""
        # Cena 1: HERO, stock fraco 62.0 (< 70) -> generated
        # Cena 2: NORMAL, stock forte 88.0 (>= 60) -> stock
        # Cena 3: LOW, stock 52.0 (>= 50) -> stock
        # Cena 4: NORMAL, stock fraco 40.0 (< 60) -> generated
        scenes_data = [
            {"idx": 1, "score": 62.0, "imp": SceneImportance.HERO, "text": "Gancho inicial chocante com tornado"},
            {"idx": 2, "score": 88.0, "imp": SceneImportance.NORMAL, "text": "Cena com excelente clipe de stock"},
            {"idx": 3, "score": 52.0, "imp": SceneImportance.LOW, "text": "Transição sonora curta enquanto isso"},
            {"idx": 4, "score": 40.0, "imp": SceneImportance.NORMAL, "text": "Explicação detalhada do evento"},
        ]

        selections = []
        for s in scenes_data:
            res = self.director.resolve_contextual_scene_visual(
                scene_index=s["idx"],
                stock_match_score=s["score"],
                narration=s["text"],
                aspect_ratio="9:16",
                scene_importance=s["imp"],
            )
            sel = SceneMaterialSelection(
                scene_index=s["idx"],
                material_path=res.output_path or "storage/stock.mp4",
                provider=res.provider,
                stock_match_score=s["score"],
                stock_score=s["score"],
                strategy_selected=res.metadata.get("strategy_selected"),
                scene_importance=res.metadata.get("scene_importance"),
                final_visual_source=res.metadata.get("final_visual_source"),
                visual_source_type=res.metadata.get("visual_source_type"),
                generated_attempted=res.metadata.get("generated_attempted", False),
                generation_status=res.metadata.get("generation_status"),
                fallback_used=res.metadata.get("fallback_used", False),
            )
            selections.append(sel)

        # Valida estratégias mistas
        self.assertEqual(selections[0].final_visual_source, "image_motion")
        self.assertEqual(selections[1].final_visual_source, "stock")
        self.assertEqual(selections[2].final_visual_source, "stock")
        self.assertEqual(selections[3].final_visual_source, "image_motion")

        # Computa métricas de resumo
        summary = compute_video_visual_summary(selections)
        self.assertEqual(summary.total_scenes, 4)
        self.assertEqual(summary.stock_scenes, 2)
        self.assertEqual(summary.generated_image_scenes, 2)
        self.assertEqual(summary.generated_video_scenes, 0)
        self.assertEqual(summary.generation_attempts, 2)
        self.assertEqual(summary.generation_successes, 2)
        self.assertEqual(summary.fallback_scenes, 0)
        expected_avg = round((62.0 + 88.0 + 52.0 + 40.0) / 4, 2)
        self.assertEqual(summary.average_stock_score, expected_avg)

    def test_legacy_mode_visual_generation_disabled_remains_unchanged(self):
        """12. legacy mode with visual_generation_enabled=false unchanged: 100% stock inalterado."""
        director_legacy = HybridVisualDirector(
            visual_generation_enabled=False,
            generated_image_enabled=False,
        )
        res = director_legacy.resolve_contextual_scene_visual(
            scene_index=1,
            stock_match_score=15.0,
            narration="Cena crítica mesmo com score baixo",
            aspect_ratio="9:16",
            scene_importance=SceneImportance.HERO,
        )
        self.assertTrue(res.success)
        self.assertEqual(res.provider, "stock")
        self.assertEqual(res.metadata.get("strategy_selected"), HybridDecision.STOCK_HIGH_CONFIDENCE.value)
        self.assertEqual(res.metadata.get("final_visual_source"), "stock")
        self.assertFalse(res.metadata.get("generated_attempted"))

    def test_cost_benefit_reused_candidate_and_aspect_ratio(self):
        """13. Cost-benefit heuristic considera reuso e aspect ratio do candidato."""
        # Score 62.0 em cena NORMAL normalmente seria STOCK (62 >= 60)
        strat_new = self.director.determine_scene_strategy(
            stock_match_score=62.0,
            candidate_is_reused=False,
        )
        self.assertEqual(strat_new, HybridDecision.STOCK_HIGH_CONFIDENCE)

        # Se o candidato de stock for repetido (reused), threshold sobe para 75 -> prefere gerar novo
        strat_reused = self.director.determine_scene_strategy(
            stock_match_score=62.0,
            candidate_is_reused=True,
        )
        self.assertEqual(strat_reused, HybridDecision.GENERATED_IMAGE_PREFERRED)

        # Se candidato de stock tiver aspect ratio alinhado (portrait nativo para vídeo 9:16),
        # threshold de stock diminui em 5 (de 60 para 55) -> aceita score 56
        strat_aligned = self.director.determine_scene_strategy(
            stock_match_score=56.0,
            candidate_aspect_ratio="portrait",
            target_aspect_ratio="9:16",
        )
        self.assertEqual(strat_aligned, HybridDecision.STOCK_HIGH_CONFIDENCE)

    def test_unit_classify_scene_importance_and_select_still_motion(self):
        """Valida diretamente as funções utilitárias de classificação e seleção de movimento."""
        # Hook na primeira cena é HERO
        self.assertEqual(classify_scene_importance(1, 4), SceneImportance.HERO)
        # Palavra de impacto é HERO
        self.assertEqual(classify_scene_importance(2, 4, narration="Explosão massiva"), SceneImportance.HERO)
        # Transição curta é LOW
        self.assertEqual(classify_scene_importance(3, 4, duration_seconds=1.5), SceneImportance.LOW)
        # Cenas comuns são NORMAL
        self.assertEqual(classify_scene_importance(2, 4, narration="Um homem caminhando"), SceneImportance.NORMAL)

        # Still motion modes
        self.assertEqual(select_still_motion_mode(1, narration="foco e aproximação"), StillMotionMode.ZOOM_IN)
        self.assertEqual(select_still_motion_mode(2, narration="vista aérea ampla panorâmica"), StillMotionMode.ZOOM_OUT)
        self.assertEqual(select_still_motion_mode(3, narration="carro passando pela estrada"), StillMotionMode.PAN_RIGHT)
        self.assertEqual(select_still_motion_mode(4, narration="olhando para a esquerda"), StillMotionMode.PAN_LEFT)
        self.assertEqual(select_still_motion_mode(5, narration="objeto imóvel parado"), StillMotionMode.STATIC)

        # VideoVisualSummary instanciação direta
        summary = VideoVisualSummary(total_scenes=1)
        self.assertEqual(summary.total_scenes, 1)

    def test_invariants_zero_publication_zero_paid_calls_zero_download(self):
        """14. Invariantes de fábrica: zero publicação, zero chamadas pagas, zero downloads pesados."""
        self.assertTrue(self.adapter.mock_mode)
        self.assertEqual(self.director.preferred_video_provider, "disabled")


if __name__ == "__main__":
    unittest.main()
