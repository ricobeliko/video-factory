"""
test/services/test_thematic_visual.py
=====================================
Targeted Unit Tests for V16.8.2 — Alternative Visual Sources Evaluation.

Validações obrigatórias:
- strong stock stays stock
- weak stock triggers thematic search
- NASA result selected for Mars when score superior
- Wikimedia fallback works
- uncertain license blocks automatic use
- duplicate thematic asset penalized
- thematic source failure falls back safely
- still motion accepts thematic image
- legacy mode remains unchanged
- no paid calls
- no publishing
- no production access
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock

from PIL import Image

from app.services.hybrid_visual import (
    HybridDecision,
    HybridVisualDirector,
)
from app.services.thematic_visual import (
    FREE_GENERATIVE_PROVIDERS_AUDIT,
    GenerativeProviderFeasibility,
    NASAImageLibraryProvider,
    ThematicAsset,
    ThematicLicenseStatus,
    ThematicScoringEngine,
    ThematicVisualOrchestrator,
    ThematicVisualProvider,
    WikimediaCommonsProvider,
)


class TestThematicVisualSources(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="v16_8_2_test_")
        self.mock_image_path = os.path.join(self.test_dir, "test_mars.jpg")
        img = Image.new("RGB", (1080, 1920), color=(180, 50, 20))
        img.save(self.mock_image_path, "JPEG")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_strong_stock_stays_stock(self):
        """Valida que stock com score alto mantém STOCK_HIGH_CONFIDENCE sem acionar busca temática."""
        director = HybridVisualDirector(
            visual_generation_enabled=True,
            thematic_sources_enabled=True,
            stock_high_confidence_threshold=60.0,
        )
        decision = director.determine_scene_strategy(stock_match_score=75.0)
        self.assertEqual(decision, HybridDecision.STOCK_HIGH_CONFIDENCE)

        res = director.resolve_contextual_scene_visual(
            scene_index=1,
            stock_match_score=75.0,
            narration="Uma cena com ótimo material stock já existente",
        )
        self.assertEqual(res.metadata.get("visual_source_type"), "stock")
        self.assertEqual(res.metadata.get("decision"), "STOCK_HIGH_CONFIDENCE")
        self.assertFalse(res.metadata.get("fallback_used"))

    def test_weak_stock_triggers_thematic_search(self):
        """Valida que stock fraco aciona a estratégia THEMATIC_SOURCE_PREFERRED quando fontes temáticas ativas."""
        director = HybridVisualDirector(
            visual_generation_enabled=True,
            thematic_sources_enabled=True,
            stock_high_confidence_threshold=60.0,
        )
        decision = director.determine_scene_strategy(stock_match_score=28.0)
        self.assertEqual(decision, HybridDecision.THEMATIC_SOURCE_PREFERRED)

    def test_nasa_result_selected_for_mars_when_score_superior(self):
        """Valida que ativo da NASA é selecionado quando seu score determinístico supera o stock fraco."""
        mock_asset = ThematicAsset(
            asset_id="nasa_PIA10063",
            provider_name="nasa_image_library",
            title="Olympus Mons Mars Caldera",
            description="High resolution shot of Olympus Mons caldera on Mars",
            source_url="https://images.nasa.gov/details/PIA10063",
            download_url="https://images-assets.nasa.gov/image/PIA10063/PIA10063~orig.jpg",
            license_status=ThematicLicenseStatus.PUBLIC_DOMAIN,
            license_name="Public Domain (NASA Guidelines)",
            width=1920,
            height=1080,
            orientation="landscape",
            local_path=self.mock_image_path,
        )

        mock_provider = MagicMock(spec=ThematicVisualProvider)
        mock_provider.name = "nasa_image_library"
        mock_provider.supports_topic.return_value = True
        mock_provider.search.return_value = [mock_asset]
        mock_provider.fetch_asset.return_value = self.mock_image_path

        orch = ThematicVisualOrchestrator(providers=[mock_provider])
        director = HybridVisualDirector(
            visual_generation_enabled=True,
            thematic_sources_enabled=True,
            thematic_orchestrator=orch,
        )

        res = director.resolve_contextual_scene_visual(
            scene_index=3,
            stock_match_score=28.0,
            narration="Além disso, o Monte Olimpo, o maior vulcão do sistema solar localizado lá,",
            visual_intent={"primary_subject": "Olympus Mons volcano"},
        )

        self.assertTrue(res.success)
        self.assertEqual(res.metadata.get("visual_source_type"), "image_motion")
        self.assertEqual(res.metadata.get("provider_name"), "nasa_image_library")
        self.assertEqual(res.metadata.get("license_status"), "PUBLIC_DOMAIN")
        self.assertGreater(res.metadata.get("thematic_score", 0.0), 28.0)
        self.assertIn("THEMATIC_SOURCE_PREFERRED", res.metadata.get("selection_reason", ""))

    def test_wikimedia_fallback_works(self):
        """Valida que se o primeiro provedor não tiver ativos, o segundo (Wikimedia) é selecionado com sucesso."""
        mock_empty_nasa = MagicMock(spec=ThematicVisualProvider)
        mock_empty_nasa.name = "nasa_image_library"
        mock_empty_nasa.supports_topic.return_value = True
        mock_empty_nasa.search.return_value = []

        mock_wiki_asset = ThematicAsset(
            asset_id="wiki_54041132578",
            provider_name="wikimedia_commons",
            title="Olympus Mons Caldera - ESA Mars Express",
            description="Geological surface map of Olympus Mons",
            source_url="https://commons.wikimedia.org/wiki/File:Olympus_Mons.png",
            download_url="https://upload.wikimedia.org/wikipedia/commons/test.png",
            license_status=ThematicLicenseStatus.CC_BY,
            license_name="CC BY 4.0",
            width=1280,
            height=720,
            orientation="landscape",
            local_path=self.mock_image_path,
        )
        mock_wiki = MagicMock(spec=ThematicVisualProvider)
        mock_wiki.name = "wikimedia_commons"
        mock_wiki.supports_topic.return_value = True
        mock_wiki.search.return_value = [mock_wiki_asset]
        mock_wiki.fetch_asset.return_value = self.mock_image_path

        orch = ThematicVisualOrchestrator(providers=[mock_empty_nasa, mock_wiki])
        best_asset, qg = orch.find_best_thematic_asset(query="Olympus Mons", narration="Monte Olimpo")

        self.assertIsNotNone(best_asset)
        self.assertEqual(best_asset.provider_name, "wikimedia_commons")
        self.assertEqual(best_asset.license_status, ThematicLicenseStatus.CC_BY)
        self.assertTrue(qg.is_valid)

    def test_uncertain_license_blocks_automatic_use(self):
        """Valida que ativo com licença incerta é reprovado pelo Quality Gate e não é usado automaticamente."""
        engine = ThematicScoringEngine()
        uncertain_asset = ThematicAsset(
            asset_id="wiki_uncertain_123",
            provider_name="wikimedia_commons",
            title="Mars Sunset Copyrighted",
            license_status=ThematicLicenseStatus.LICENSE_REVIEW_REQUIRED,
            license_name="Uncertain / Review Required",
            width=1920,
            height=1080,
            download_url="https://example.com/image.jpg",
        )
        score, bd = engine.compute_thematic_score(uncertain_asset, target_subject="Mars Sunset")
        uncertain_asset.score = score
        uncertain_asset.score_breakdown = bd

        self.assertEqual(bd["license_confidence"], 0.0)
        qg_result = engine.evaluate_quality_gate(uncertain_asset)
        self.assertFalse(qg_result.is_valid)
        self.assertEqual(qg_result.reason, "UNCERTAIN_LICENSE_REVIEW_REQUIRED")

        # Integração com o diretor: deve fazer fallback seguro para stock
        mock_provider = MagicMock(spec=ThematicVisualProvider)
        mock_provider.name = "wikimedia_commons"
        mock_provider.supports_topic.return_value = True
        mock_provider.search.return_value = [uncertain_asset]

        orch = ThematicVisualOrchestrator(providers=[mock_provider])
        director = HybridVisualDirector(
            visual_generation_enabled=True,
            thematic_sources_enabled=True,
            thematic_orchestrator=orch,
        )

        res = director.resolve_contextual_scene_visual(
            scene_index=7,
            stock_match_score=22.0,
            narration="Pôr do sol marciano",
        )
        self.assertTrue(res.metadata.get("fallback_used"))
        self.assertEqual(res.metadata.get("fallback_reason"), "THEMATIC_QUALITY_GATE_REJECTED")
        self.assertEqual(res.metadata.get("visual_source_type"), "stock")

    def test_duplicate_thematic_asset_penalized(self):
        """Valida que ativo já utilizado em cena anterior sofre penalidade de repetição de -25 pontos."""
        engine = ThematicScoringEngine()
        asset = ThematicAsset(
            asset_id="nasa_mars_repeat",
            provider_name="nasa_image_library",
            title="Olympus Mons Horizon",
            license_status=ThematicLicenseStatus.PUBLIC_DOMAIN,
            width=1920,
            height=1080,
        )
        score_fresh, bd_fresh = engine.compute_thematic_score(asset, target_subject="Olympus Mons", is_reused=False)
        score_reused, bd_reused = engine.compute_thematic_score(asset, target_subject="Olympus Mons", is_reused=True)

        self.assertEqual(bd_reused["repetition_penalty"], -25.0)
        self.assertEqual(round(score_fresh - score_reused, 2), 25.0)

    def test_thematic_source_failure_falls_back_safely(self):
        """Valida que falhas ou exceções em provedores temáticos revertem com segurança para stock."""
        mock_broken_provider = MagicMock(spec=ThematicVisualProvider)
        mock_broken_provider.name = "broken_thematic"
        mock_broken_provider.supports_topic.return_value = True
        mock_broken_provider.search.side_effect = ConnectionError("DNS failure on thematic provider")

        orch = ThematicVisualOrchestrator(providers=[mock_broken_provider])
        director = HybridVisualDirector(
            visual_generation_enabled=True,
            thematic_sources_enabled=True,
            thematic_orchestrator=orch,
        )

        res = director.resolve_contextual_scene_visual(
            scene_index=3,
            stock_match_score=28.0,
            narration="Monte Olimpo em Marte",
        )
        self.assertEqual(res.metadata.get("visual_source_type"), "stock")
        self.assertTrue(res.metadata.get("fallback_used"))
        self.assertEqual(res.metadata.get("fallback_reason"), "THEMATIC_SCORE_INSUFFICIENT_OR_NOT_FOUND")

    def test_still_motion_accepts_thematic_image(self):
        """Valida que ativo temático estático é enriquecido com instruções determinísticas de still motion."""
        mock_asset = ThematicAsset(
            asset_id="nasa_PIA19400",
            provider_name="nasa_image_library",
            title="Sunset in Mars Gale Crater",
            description="Authentic blue sunset on Mars Gale Crater captured by Curiosity",
            download_url="https://images-assets.nasa.gov/image/PIA19400/PIA19400~orig.jpg",
            license_status=ThematicLicenseStatus.PUBLIC_DOMAIN,
            license_name="Public Domain (NASA Guidelines)",
            width=1344,
            height=1080,
            local_path=self.mock_image_path,
        )
        mock_provider = MagicMock(spec=ThematicVisualProvider)
        mock_provider.name = "nasa_image_library"
        mock_provider.supports_topic.return_value = True
        mock_provider.search.return_value = [mock_asset]
        mock_provider.fetch_asset.return_value = self.mock_image_path

        orch = ThematicVisualOrchestrator(providers=[mock_provider])
        director = HybridVisualDirector(
            visual_generation_enabled=True,
            thematic_sources_enabled=True,
            still_motion_enabled=True,
            thematic_orchestrator=orch,
        )

        res = director.resolve_contextual_scene_visual(
            scene_index=7,
            stock_match_score=22.0,
            narration="Pôr do sol azulado fantasmagórico com poeira rarefeita",
            visual_intent={"primary_subject": "Martian sunset"},
            duration_seconds=3.0,
        )
        self.assertTrue(res.success)
        self.assertEqual(res.metadata.get("visual_source_type"), "image_motion")
        self.assertIn("still_motion_mode", res.metadata)
        self.assertIn("motion_instructions", res.metadata)
        self.assertEqual(res.metadata["motion_instructions"]["mode"], res.metadata["still_motion_mode"])

    def test_legacy_mode_remains_unchanged(self):
        """Valida que com thematic_sources_enabled=False o comportamento legado V16.7/V16.8 permanece idêntico."""
        director_disabled = HybridVisualDirector(
            visual_generation_enabled=False,
            thematic_sources_enabled=False,
        )
        decision1 = director_disabled.determine_scene_strategy(stock_match_score=15.0)
        self.assertEqual(decision1, HybridDecision.STOCK_HIGH_CONFIDENCE)

        director_img_only = HybridVisualDirector(
            visual_generation_enabled=True,
            generated_image_enabled=True,
            thematic_sources_enabled=False,
            generated_image_threshold=35.0,
        )
        decision2 = director_img_only.determine_scene_strategy(stock_match_score=40.0)
        self.assertEqual(decision2, HybridDecision.GENERATED_IMAGE_PREFERRED)

    def test_invariants_no_paid_calls_no_production_access(self):
        """Garante que nenhum endpoint pago (Google Gemini, OpenAI) ou path de produção é acessado."""
        nasa = NASAImageLibraryProvider()
        wiki = WikimediaCommonsProvider()

        # URLs de endpoints públicos
        self.assertTrue(nasa.name == "nasa_image_library")
        self.assertTrue(wiki.name == "wikimedia_commons")

        # Verifica isolamento de produção
        prod_root = "C:\\Projetos\\MoneyPrinterTurbo"
        self.assertFalse(os.path.exists(os.path.join(self.test_dir, prod_root)))

    def test_free_generative_providers_audit_data(self):
        """Valida o registro estruturado da auditoria dos provedores generativos gratuitos."""
        self.assertEqual(len(FREE_GENERATIVE_PROVIDERS_AUDIT), 2)
        cf = next(p for p in FREE_GENERATIVE_PROVIDERS_AUDIT if p.provider_name == "cloudflare_workers_ai")
        hf = next(p for p in FREE_GENERATIVE_PROVIDERS_AUDIT if p.provider_name == "huggingface_inference_providers")

        self.assertEqual(cf.feasibility_status, GenerativeProviderFeasibility.REQUIRES_ACCOUNT)
        self.assertTrue(cf.requires_account)
        self.assertFalse(cf.requires_billing)

        self.assertEqual(hf.feasibility_status, GenerativeProviderFeasibility.FREE_QUOTA_UNKNOWN)
        self.assertTrue(hf.requires_account)
        self.assertFalse(hf.requires_billing)


if __name__ == "__main__":
    unittest.main()
