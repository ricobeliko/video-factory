"""
test/services/test_visual_matching.py
=====================================
Testes da Fase V16.5 — Visual Matching v2.

Validações Obrigatórias:
1. Cena específica gera query específica e descritiva.
2. Termos genéricos recebem contexto visual (subject, action, environment).
3. Melhor candidato semântico vence candidato fraco ou genérico.
4. Orientação inadequada perde prioridade / recebe penalidade.
5. Duplicata perde prioridade e diversidade global é respeitada em cenas não adjacentes.
6. Cenas diferentes recebem materiais diferentes quando há alternativas.
7. Fallback funciona sem quebrar a geração (resiliência).
8. Pipeline legado continua funcionando quando novos metadados não existirem.
9. Zero chamadas reais a provedores externos (100% isolado por mocks).
10. Cenários realistas de desastres/natureza (Tornado, Terremoto, Aurora, Vulcão) com evidência Antes vs Depois.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from app.models.schema import (
    MaterialInfo,
    ScenePlan,
    ScenePlanItem,
    VideoAspect,
    VideoParams,
)
from app.services import (
    scene_material,
    visual_matching,
)


class TestVisualMatchingV2(unittest.TestCase):
    """Bateria de testes unitários para o Visual Matching v2."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="v16_5_visual_test_")
        self.dummy_video_path = os.path.join(self.test_dir, "test_clip.mp4")
        with open(self.dummy_video_path, "wb") as f:
            f.write(b"fake mp4 video bytes")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_specific_scene_generates_specific_query(self):
        """1. Cena específica deve gerar query rica e descritiva em vez de termo genérico simples."""
        narration = "Um violento tornado tocou o solo em uma área rural, girando sob nuvens escuras."
        intent = visual_matching.extract_scene_visual_intent(
            narration=narration,
            video_subject="Desastres Naturais",
            scene_index=1,
        )

        self.assertIsInstance(intent, visual_matching.SceneVisualIntent)
        self.assertIn("tornado", intent.primary_subject.lower())
        self.assertIn("tornado", intent.must_include)
        self.assertGreater(len(intent.search_queries), 1)

        # Query principal deve ser descritiva e não apenas 'tornado'
        top_query = intent.search_queries[0]
        self.assertNotEqual(top_query.strip().lower(), "tornado")
        self.assertTrue(
            "tornado" in top_query.lower() and ("storm" in top_query.lower() or "clouds" in top_query.lower())
        )

    def test_generic_terms_receive_context(self):
        """2. Termos genéricos recebem contexto visual do assunto global e da ação narrada."""
        narration = "A destruição avançava rapidamente."
        intent = visual_matching.extract_scene_visual_intent(
            narration=narration,
            video_subject="Terremotos Históricos",
            scene_index=1,
        )

        # Contextualizado com o assunto Terremotos
        self.assertIn("earthquake", intent.primary_subject.lower())
        self.assertTrue(any("earthquake" in q.lower() for q in intent.search_queries))
        # Termos genéricos banidos não devem estar nas queries
        for q in intent.search_queries:
            self.assertNotIn(q.lower(), visual_matching.BANNED_GENERIC_TERMS)

    def test_better_candidate_beats_semantically_weak_candidate(self):
        """3. Candidato com maior aderência semântica e tags precisas vence candidato fraco."""
        intent = visual_matching.SceneVisualIntent(
            primary_subject="volcano eruption glowing lava",
            action="spewing molten lava ash clouds",
            environment="volcanic mountain crater night",
            visual_style="cinematic documentary",
            must_include=["volcano", "lava"],
            avoid=["indoor", "beach"],
            search_queries=["volcano erupting glowing lava flow"],
        )

        strong_candidate = MaterialInfo(
            provider="pexels",
            url="https://example.com/volcano_eruption.mp4",
            duration=12.0,
            source_info={
                "asset_id": "strong_volcano_1",
                "title": "Volcano erupting with glowing lava at night",
                "tags": ["volcano", "lava", "eruption", "crater", "night"],
                "rendition": {"width": 1080, "height": 1920},
            },
        )

        weak_candidate = MaterialInfo(
            provider="pexels",
            url="https://example.com/coffee_cup.mp4",
            duration=10.0,
            source_info={
                "asset_id": "weak_coffee_2",
                "title": "Person drinking coffee near window",
                "tags": ["coffee", "cup", "morning", "table"],
                "rendition": {"width": 1080, "height": 1920},
            },
        )

        score_strong, bd_strong = visual_matching.score_candidate_material(
            candidate=strong_candidate,
            visual_intent=intent,
            target_aspect=VideoAspect.portrait,
            search_query_used="volcano erupting glowing lava flow",
        )

        score_weak, bd_weak = visual_matching.score_candidate_material(
            candidate=weak_candidate,
            visual_intent=intent,
            target_aspect=VideoAspect.portrait,
            search_query_used="volcano erupting glowing lava flow",
        )

        self.assertGreater(score_strong, 65.0)
        self.assertLess(score_weak, 35.0)
        self.assertGreater(score_strong, score_weak + 30.0)

        # Teste de ranking: o forte deve ser selecionado em 1º lugar
        best_cand, best_score, reason, _ = visual_matching.rank_and_select_candidates(
            candidates=[weak_candidate, strong_candidate],
            visual_intent=intent,
            target_aspect=VideoAspect.portrait,
            search_query_used="volcano erupting glowing lava flow",
        )
        self.assertEqual(best_cand.source_info["asset_id"], "strong_volcano_1")

    def test_orientation_mismatch_penalization(self):
        """4. Candidato com orientação inadequada (ex: horizontal quando vertical requerido) perde prioridade."""
        intent = visual_matching.SceneVisualIntent(
            primary_subject="aurora borealis lights",
            action="dancing in night sky",
            environment="arctic snow stars",
            visual_style="cinematic",
            must_include=["aurora"],
            avoid=[],
            search_queries=["aurora borealis northern lights"],
        )

        portrait_candidate = MaterialInfo(
            provider="pexels",
            url="https://example.com/aurora_portrait.mp4",
            duration=8.0,
            source_info={
                "asset_id": "aurora_portrait",
                "title": "Aurora borealis green lights",
                "tags": ["aurora", "green"],
                "rendition": {"width": 1080, "height": 1920},  # Vertical
            },
        )

        landscape_candidate = MaterialInfo(
            provider="pexels",
            url="https://example.com/aurora_landscape.mp4",
            duration=8.0,
            source_info={
                "asset_id": "aurora_landscape",
                "title": "Aurora borealis green lights",
                "tags": ["aurora", "green"],
                "rendition": {"width": 1920, "height": 1080},  # Horizontal
            },
        )

        score_port, bd_port = visual_matching.score_candidate_material(
            candidate=portrait_candidate,
            visual_intent=intent,
            target_aspect=VideoAspect.portrait,
        )

        score_land, bd_land = visual_matching.score_candidate_material(
            candidate=landscape_candidate,
            visual_intent=intent,
            target_aspect=VideoAspect.portrait,
        )

        self.assertEqual(bd_port["aspect_score"], 15.0)
        self.assertEqual(bd_land["aspect_score"], -30.0)
        self.assertGreater(score_port, score_land)

    def test_duplicate_asset_across_scenes_penalization_and_global_diversity(self):
        """5. Reutilização de ativo sofre penalidade global (-35 pts) mesmo em cenas não contíguas."""
        intent = visual_matching.SceneVisualIntent(
            primary_subject="mountain peaks",
            action="standing tall in clouds",
            environment="alpine range",
            visual_style="cinematic",
            must_include=["mountain"],
            avoid=[],
            search_queries=["mountain peaks"],
        )

        asset_1 = MaterialInfo(
            provider="pexels",
            url="https://example.com/m1.mp4",
            duration=10.0,
            source_info={"asset_id": "asset_mountain_1"},
        )
        asset_2 = MaterialInfo(
            provider="pexels",
            url="https://example.com/m2.mp4",
            duration=10.0,
            source_info={"asset_id": "asset_mountain_2"},
        )

        # Sem uso prévio
        score_fresh, _ = visual_matching.score_candidate_material(
            candidate=asset_1,
            visual_intent=intent,
            used_asset_ids=set(),
            last_selected_asset_id=None,
        )

        # Com uso na cena imediatamente anterior (penalidade imediata -50)
        score_adj, bd_adj = visual_matching.score_candidate_material(
            candidate=asset_1,
            visual_intent=intent,
            used_asset_ids={"asset_mountain_1"},
            last_selected_asset_id="asset_mountain_1",
        )
        self.assertEqual(bd_adj["repetition_penalty"], -50.0)

        # Com uso prévio não adjacente (penalidade global -35)
        score_global, bd_global = visual_matching.score_candidate_material(
            candidate=asset_1,
            visual_intent=intent,
            used_asset_ids={"asset_mountain_1"},
            last_selected_asset_id="asset_mountain_99",  # Outro ativo foi o último
        )
        self.assertEqual(bd_global["repetition_penalty"], -35.0)

        # O ativo novo deve vencer facilmente o ativo repetido globalmente
        score_unused, _ = visual_matching.score_candidate_material(
            candidate=asset_2,
            visual_intent=intent,
            used_asset_ids={"asset_mountain_1"},
            last_selected_asset_id="asset_mountain_99",
        )
        self.assertGreater(score_unused, score_global)

    @patch("app.services.material._search_videos_with_cache")
    @patch("app.services.material.save_video")
    @patch("app.services.task_artifacts.patch_script_data")
    def test_different_scenes_receive_different_materials(self, mock_patch, mock_save, mock_search):
        """6. Três cenas consecutivas recebem três materiais distintos quando disponíveis."""
        mock_save.return_value = self.dummy_video_path

        cand_1 = MaterialInfo(
            provider="pexels",
            url="https://example.com/1.mp4",
            duration=8.0,
            source_info={"asset_id": "asset_A", "title": "Volcano eruption 1"},
        )
        cand_2 = MaterialInfo(
            provider="pexels",
            url="https://example.com/2.mp4",
            duration=8.0,
            source_info={"asset_id": "asset_B", "title": "Volcano eruption 2"},
        )
        cand_3 = MaterialInfo(
            provider="pexels",
            url="https://example.com/3.mp4",
            duration=8.0,
            source_info={"asset_id": "asset_C", "title": "Volcano eruption 3"},
        )

        mock_search.return_value = [cand_1, cand_2, cand_3]

        plan = ScenePlan(
            scenes=[
                ScenePlanItem(scene_index=1, narration="O vulcão desperta.", search_terms=["volcano"]),
                ScenePlanItem(scene_index=2, narration="A lava escorre veloz.", search_terms=["volcano"]),
                ScenePlanItem(scene_index=3, narration="Nuvens de cinzas sobem.", search_terms=["volcano"]),
            ],
            total_scenes=3,
        )
        params = VideoParams(video_subject="Vulcões")

        selections = scene_material.resolve_scene_materials(
            task_id="task_multi_scene_diversity",
            scene_plan=plan,
            params=params,
        )

        self.assertEqual(len(selections), 3)
        chosen_assets = [s.asset_id for s in selections]
        # Todos os 3 ativos devem ser distintos
        self.assertEqual(len(set(chosen_assets)), 3)
        self.assertEqual(chosen_assets, ["asset_A", "asset_B", "asset_C"])

    @patch("app.services.material._search_videos_with_cache")
    @patch("app.services.material.save_video")
    @patch("app.services.task_artifacts.patch_script_data")
    def test_fallback_works_without_breaking_generation(self, mock_patch, mock_save, mock_search):
        """7. Se termos específicos falharem, fallbacks subsequentes resolvem sem erro."""
        mock_save.return_value = self.dummy_video_path

        def search_side_effect(search_term, **kwargs):
            if "rare_hyper_specific_term" in search_term:
                return []
            if "tornado" in search_term.lower() or "weather" in search_term.lower():
                return [
                    MaterialInfo(
                        provider="pexels",
                        url="https://example.com/tornado_fb.mp4",
                        duration=10.0,
                        source_info={"asset_id": "asset_tornado_fallback", "title": "Tornado storm"},
                    )
                ]
            return []

        mock_search.side_effect = search_side_effect

        plan = ScenePlan(
            scenes=[
                ScenePlanItem(
                    scene_index=1,
                    narration="O tornado destruiu o celeiro.",
                    search_terms=["rare_hyper_specific_term_fail"],
                )
            ],
            total_scenes=1,
        )
        params = VideoParams(video_subject="Tornados")

        selections = scene_material.resolve_scene_materials(
            task_id="task_resilient_fallback",
            scene_plan=plan,
            params=params,
        )

        self.assertEqual(len(selections), 1)
        self.assertEqual(selections[0].asset_id, "asset_tornado_fallback")
        self.assertTrue(selections[0].fallback_used)
        self.assertGreater(selections[0].fallback_tier, 0)
        self.assertGreater(selections[0].match_score, 0.0)

    @patch("app.services.material._search_videos_with_cache")
    @patch("app.services.material.save_video")
    @patch("app.services.task_artifacts.patch_script_data")
    def test_legacy_pipeline_compatibility_when_metadata_missing(self, mock_patch, mock_save, mock_search):
        """8. Candidatos legados sem tags, rendition ou source_info completo continuam funcionando."""
        mock_save.return_value = self.dummy_video_path

        legacy_cand = MaterialInfo(
            provider="pexels",
            url="https://example.com/legacy_video.mp4",
            duration=7.0,
            # Sem source_info ou com dict vazio
            source_info={},
        )
        mock_search.return_value = [legacy_cand]

        plan = ScenePlan(
            scenes=[
                ScenePlanItem(
                    scene_index=1,
                    narration="Cena com material legado.",
                    search_terms=["legacy_term"],
                )
            ],
            total_scenes=1,
        )
        params = VideoParams(video_subject="Legado")

        selections = scene_material.resolve_scene_materials(
            task_id="task_legacy_compat",
            scene_plan=plan,
            params=params,
        )

        self.assertEqual(len(selections), 1)
        self.assertEqual(selections[0].material_path, self.dummy_video_path)
        self.assertIsNotNone(selections[0].match_score)

    def test_realistic_disasters_before_after_demonstration(self):
        """10. Demonstração de Evidência Antes vs Depois para Tornados, Terremotos, Auroras e Vulcões."""
        scenarios = [
            {
                "topic": "Tornado",
                "narration": "O gigantesco tornado tocou o solo varrendo a planície com ventos violentos e nuvens carregadas.",
                "legacy_term": "o gigantesco",  # Termo legado que extraía bigrama ingênuo pt-BR
                "expected_domain": "tornado",
            },
            {
                "topic": "Terremoto",
                "narration": "O violento terremoto sacudiu os prédios da cidade, abrindo fissuras no asfalto e espalhando escombros.",
                "legacy_term": "o violento",
                "expected_domain": "earthquake",
            },
            {
                "topic": "Aurora",
                "narration": "No céu ártico congelado, a espetacular aurora boreal dança em tons de verde sob as estrelas.",
                "legacy_term": "artico congelado",
                "expected_domain": "aurora",
            },
            {
                "topic": "Vulcão",
                "narration": "O imponente vulcão entrou em erupção, expelindo rios de lava incandescente e densas nuvens de cinzas.",
                "legacy_term": "o imponente",
                "expected_domain": "volcano",
            },
        ]

        for sc in scenarios:
            intent = visual_matching.extract_scene_visual_intent(
                narration=sc["narration"],
                video_subject=f"Documentário sobre {sc['topic']}",
                scene_index=1,
            )

            # Evidência V16.5:
            # - Queries são em inglês, específicas e descritivas
            self.assertGreaterEqual(len(intent.search_queries), 3)
            first_query = intent.search_queries[0]
            self.assertIn(sc["expected_domain"], first_query.lower())
            self.assertGreater(len(first_query.split()), 3)

            # - Intenção estruturada possui campos completos
            self.assertTrue(len(intent.primary_subject) > 0)
            self.assertTrue(len(intent.action) > 0)
            self.assertTrue(len(intent.environment) > 0)
            self.assertTrue(len(intent.must_include) > 0)
            self.assertTrue(len(intent.avoid) > 0)

            # - Pontuação de candidato altamente aderente vs genérico
            strong_cand = MaterialInfo(
                provider="pexels",
                url="https://example.com/best.mp4",
                duration=10.0,
                source_info={
                    "title": f"Cinematic {sc['expected_domain']} in high definition",
                    "tags": [sc["expected_domain"], "nature", "weather"],
                    "rendition": {"width": 1080, "height": 1920},
                },
            )
            score_strong, _ = visual_matching.score_candidate_material(
                candidate=strong_cand,
                visual_intent=intent,
                target_aspect=VideoAspect.portrait,
                search_query_used=first_query,
            )
            self.assertGreaterEqual(score_strong, 60.0)


if __name__ == "__main__":
    unittest.main()
