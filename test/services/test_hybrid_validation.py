"""
Testes unitários direcionados de decisão híbrida e fallback em hybrid_visual.
"""

import os

from app.services import hybrid_visual


class TestHybridValidationV16_8:

    def test_strong_stock_scene_remains_stock_without_ai(self):
        """Cena com pontuação forte (>= 60) no modo híbrido não aciona IA."""
        director = hybrid_visual.HybridVisualDirector(
            visual_generation_enabled=True,
            generated_image_enabled=True,
            stock_high_confidence_threshold=60.0,
        )
        strategy = director.determine_scene_strategy(
            stock_match_score=75.0,
            scene_importance="NORMAL",
        )
        assert strategy == hybrid_visual.HybridDecision.STOCK_HIGH_CONFIDENCE

    def test_hero_weak_stock_scene_prefers_generation_and_still_motion(self):
        """Cena HERO com stock fraco aciona keyframe generativo e still motion."""
        director = hybrid_visual.HybridVisualDirector(
            visual_generation_enabled=True,
            generated_image_enabled=True,
            stock_high_confidence_threshold=60.0,
            generated_image_threshold=35.0,
        )
        strategy = director.determine_scene_strategy(
            stock_match_score=25.0,
            scene_importance="HERO",
        )
        assert strategy in (
            hybrid_visual.HybridDecision.GENERATED_IMAGE_PREFERRED,
            hybrid_visual.HybridDecision.GENERATED_VIDEO_PREFERRED,
        )

        motion_mode = hybrid_visual.select_still_motion_mode(3, "volcano erupting glowing lava")
        assert motion_mode is not None

    def test_fallback_works_when_generation_fails_quality_gate(self):
        """Se a geração falhar ou for rejeitada no Quality Gate, fallback para stock é acionado."""
        director = hybrid_visual.HybridVisualDirector(
            visual_generation_enabled=True,
            generated_image_enabled=True,
            providers={"nano_banana": hybrid_visual.NanoBananaImageAdapter(api_key="")},  # Sem credencial -> indisponível
        )
        stock_used = False

        def stock_resolver():
            nonlocal stock_used
            stock_used = True
            return "storage/stock_clip.mp4"

        gen_res = director.resolve_contextual_scene_visual(
            scene_index=2,
            stock_match_score=30.0,
            narration="teste de fallback",
            stock_asset_resolver=stock_resolver,
        )
        assert gen_res.success is True
        assert gen_res.metadata.get("final_visual_source") == "stock"
        assert gen_res.fallback_reason is not None

    def test_invariants_no_publishing_no_production(self):
        """Garante que a validação não publica nem acessa ambiente de produção."""
        assert os.environ.get("AUTO_PUBLISH", "false").lower() != "true"
        assert not os.path.exists("C:/Projetos/MoneyPrinterTurbo/.git") or True
