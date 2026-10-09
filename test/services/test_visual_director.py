# -*- coding: utf-8 -*-
"""
test/services/test_visual_director.py
=====================================
Testes unitários direcionados para o serviço Gemini Visual Director (V1.5A).
Valida contratos de schema, regras de validação, compilador determinístico de prompt,
chamada única ao Gemini e integração com o flow_workflow.
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.services.visual_director import (
    VisualDirectionPlan,
    VisualSceneSpec,
    build_director_prompt,
    compile_flow_prompt,
    direct_scenes,
    preview_visual_direction,
    validate_visual_direction_plan,
)
from scripts.flow_workflow import prepare_project


def make_sample_spec(scene_index: int = 1, style: str = "35mm documentary") -> VisualSceneSpec:
    return VisualSceneSpec(
        scene_index=scene_index,
        subject="Vintage 1963 Presidential motorcade limousine",
        action="driving slowly through a sunlit plaza lined with waving spectators",
        environment="Dealey Plaza in Dallas under bright midday autumn sun",
        lighting="harsh overhead direct sunlight with sharp distinct shadows",
        style=style,
        camera_motion="slow continuous lateral tracking shot parallel to the street",
        composition="vertical 9:16 portrait orientation with limousine in lower third",
        lens_focus="50mm anamorphic lens with deep focus capturing background crowds",
        ambiance="tense historical atmosphere with palpable anticipation",
        stock_search_terms=["vintage limousine motorcade", "crowd cheering 1960s", "sunny downtown plaza"],
        visual_importance="high",
        rationale="Establishes historical context and primary vehicle in motion.",
    )


def make_sample_plan(count: int = 2, style: str = "35mm documentary") -> VisualDirectionPlan:
    return VisualDirectionPlan(
        global_style="Authentic 1960s archival documentary with textured color grading",
        continuity_rules=[
            "Maintain consistent daylight exposure across daytime scenes",
            "Keep period-accurate 1960s architectural and automotive details",
        ],
        scenes=[make_sample_spec(scene_index=i + 1, style=style) for i in range(count)],
    )


class TestVisualDirector(unittest.TestCase):

    def test_schema_valid(self):
        """1. Schema Pydantic é válido e instancia corretamente."""
        plan = make_sample_plan(count=3)
        self.assertEqual(len(plan.scenes), 3)
        self.assertEqual(plan.scenes[0].scene_index, 1)
        self.assertEqual(plan.scenes[2].scene_index, 3)
        self.assertEqual(len(plan.continuity_rules), 2)
        dump = plan.model_dump()
        self.assertIn("global_style", dump)
        self.assertIn("scenes", dump)

    def test_scene_indexes_preserved(self):
        """2. Validação passa quando índices são preservados exatamente."""
        plan = make_sample_plan(count=3)
        # Não deve levantar exceção
        validate_visual_direction_plan(plan, expected_scene_count=3, expected_indices=[1, 2, 3])

    def test_missing_scene_rejected(self):
        """3. Falta de cena esperada é rejeitada com VISUAL_DIRECTION_INVALID."""
        plan = make_sample_plan(count=2)
        # Esperava 3 cenas, plano tem 2
        with self.assertRaises(ValueError) as ctx:
            validate_visual_direction_plan(plan, expected_scene_count=3, expected_indices=[1, 2, 3])
        self.assertIn("VISUAL_DIRECTION_INVALID", str(ctx.exception))

    def test_duplicate_scene_rejected(self):
        """4. Cenas com scene_index duplicado são rejeitadas."""
        spec1 = make_sample_spec(scene_index=1)
        spec2 = make_sample_spec(scene_index=1)  # Duplicado
        plan = VisualDirectionPlan(
            global_style="Cinematic",
            continuity_rules=["rule1"],
            scenes=[spec1, spec2],
        )
        with self.assertRaises(ValueError) as ctx:
            validate_visual_direction_plan(plan, expected_scene_count=2, expected_indices=[1, 2])
        self.assertIn("VISUAL_DIRECTION_INVALID", str(ctx.exception))
        self.assertIn("Duplicate", str(ctx.exception))

    def test_empty_required_field_rejected(self):
        """5. Campo obrigatório vazio é rejeitado com VISUAL_DIRECTION_INVALID."""
        spec = make_sample_spec(scene_index=1)
        spec.subject = "   "  # Espaço em branco
        plan = VisualDirectionPlan(
            global_style="Cinematic",
            continuity_rules=[],
            scenes=[spec],
        )
        with self.assertRaises(ValueError) as ctx:
            validate_visual_direction_plan(plan, expected_scene_count=1, expected_indices=[1])
        self.assertIn("VISUAL_DIRECTION_INVALID", str(ctx.exception))
        self.assertIn("subject", str(ctx.exception))

    def test_stock_terms_count_limits(self):
        """6. Quantidade de stock_search_terms deve estar rigorosamente entre 2 e 5."""
        spec_too_few = make_sample_spec(scene_index=1)
        spec_too_few.stock_search_terms = ["only_one_term"]
        plan1 = VisualDirectionPlan(
            global_style="Cinematic",
            continuity_rules=[],
            scenes=[spec_too_few],
        )
        with self.assertRaises(ValueError) as ctx:
            validate_visual_direction_plan(plan1, expected_scene_count=1, expected_indices=[1])
        self.assertIn("VISUAL_DIRECTION_INVALID", str(ctx.exception))

        spec_too_many = make_sample_spec(scene_index=1)
        spec_too_many.stock_search_terms = ["t1", "t2", "t3", "t4", "t5", "t6"]
        plan2 = VisualDirectionPlan(
            global_style="Cinematic",
            continuity_rules=[],
            scenes=[spec_too_many],
        )
        with self.assertRaises(ValueError) as ctx:
            validate_visual_direction_plan(plan2, expected_scene_count=1, expected_indices=[1])
        self.assertIn("VISUAL_DIRECTION_INVALID", str(ctx.exception))

    def test_compile_prompt_contains_subject_action_environment(self):
        """7. Compilador de prompt inclui subject, action e environment."""
        spec = make_sample_spec(scene_index=1)
        prompt = compile_flow_prompt(spec)
        self.assertIn(spec.subject, prompt)
        self.assertIn(spec.action, prompt)
        self.assertIn(spec.environment, prompt)

    def test_compile_prompt_contains_camera_composition_lens(self):
        """8. Compilador inclui câmera, composição, lente, iluminação e ambiente."""
        spec = make_sample_spec(scene_index=1)
        prompt = compile_flow_prompt(spec)
        self.assertIn(spec.camera_motion, prompt)
        self.assertIn(spec.composition, prompt)
        self.assertIn(spec.lens_focus, prompt)
        self.assertIn(spec.lighting, prompt)
        self.assertIn(spec.ambiance, prompt)

    def test_compile_prompt_contains_9_16(self):
        """9. Compilador inclui formato vertical 9:16 portrait fixo."""
        spec = make_sample_spec(scene_index=1)
        prompt = compile_flow_prompt(spec)
        self.assertIn("vertical 9:16 portrait", prompt)

    def test_compile_prompt_contains_technical_constraints(self):
        """10. Compilador inclui constraints técnicas negativas completas."""
        spec = make_sample_spec(scene_index=1)
        prompt = compile_flow_prompt(spec)
        self.assertIn("no text", prompt)
        self.assertIn("no captions", prompt)
        self.assertIn("no subtitles", prompt)
        self.assertIn("no watermark", prompt)
        self.assertIn("single coherent cinematic shot", prompt)

    def test_compile_prompt_does_not_force_photorealistic(self):
        """11. Compilador NÃO força 'photorealistic' quando o estilo especificado for outro."""
        spec = make_sample_spec(scene_index=1, style="charcoal sketch animation style")
        prompt = compile_flow_prompt(spec)
        self.assertIn("charcoal sketch animation style", prompt)
        self.assertNotIn("photorealistic", prompt.lower())

    def test_niche_passed_to_gemini_prompt(self):
        """12. O nicho e contexto chegam intactos ao prompt gerado para o Gemini."""
        prompt = build_director_prompt(
            normalized_scenes=[{"scene_index": 1, "narration": "Texto teste", "current_visual_intent": "macro", "current_search_terms": []}],
            video_subject="Buracos Negros",
            niche="curiosidades_ciencia",
            visual_style_brief="Scientific documentary aesthetic",
        )
        self.assertIn("curiosidades_ciencia", prompt)
        self.assertIn("Buracos Negros", prompt)
        self.assertIn("Scientific documentary aesthetic", prompt)
        self.assertIn("Texto teste", prompt)

    def test_all_scenes_sent_in_one_call(self):
        """13. Todas as cenas são enviadas em UMA ÚNICA chamada ao Gemini."""
        sample_plan = make_sample_plan(count=3)
        mock_response = MagicMock()
        mock_response.parsed = sample_plan

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        scenes = [
            {"scene_index": 1, "narration": "Cena 1", "visual_intent": "style1", "search_terms": []},
            {"scene_index": 2, "narration": "Cena 2", "visual_intent": "style2", "search_terms": []},
            {"scene_index": 3, "narration": "Cena 3", "visual_intent": "style3", "search_terms": []},
        ]

        result_plan = direct_scenes(
            scenes=scenes,
            video_subject="Ciência Moderna",
            niche="curiosidades_ciencia",
            app_config={"gemini_api_key": "dummy_key", "gemini_model_name": "gemini-3.5-flash-lite"},
            client=mock_client,
        )

        self.assertEqual(mock_client.models.generate_content.call_count, 1)
        self.assertEqual(len(result_plan.scenes), 3)

    def test_missing_api_key_raises_visual_director_failed(self):
        """14. Ausência de gemini_api_key levanta erro explícito VISUAL_DIRECTOR_FAILED."""
        scenes = [{"scene_index": 1, "narration": "Texto", "visual_intent": "mood", "search_terms": []}]
        with self.assertRaises(ValueError) as ctx:
            direct_scenes(
                scenes=scenes,
                video_subject="Teste",
                app_config={"gemini_api_key": ""},
            )
        self.assertIn("VISUAL_DIRECTOR_FAILED", str(ctx.exception))


class TestVisualDirectorWorkflowIntegration(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_visual_director_enabled_false_preserves_legacy_behavior(self):
        """15. visual_director_enabled=False preserva 100% o comportamento legado do manifest."""
        script = "Primeira cena curta de teste. Segunda cena com ação."
        res = prepare_project(
            script_text=script,
            project_name="legacy_test",
            base_dir=self.test_dir,
            visual_director_enabled=False,
        )
        import json
        with open(res["manifest_path"], "r", encoding="utf-8") as f:
            manifest = json.load(f)

        self.assertNotIn("visual_director", manifest)
        for sc in manifest["scenes"]:
            self.assertNotIn("visual_direction", sc)
            self.assertTrue(sc["prompt_en"].startswith("Cinematic scene depicting"))

    @patch("scripts.flow_workflow.direct_scenes")
    @patch("scripts.flow_workflow.get_gemini_config")
    def test_visual_director_enabled_true_persists_spec_without_secrets(self, mock_get_cfg, mock_direct):
        """16. visual_director_enabled=True persiste spec compilada sem expor credenciais."""
        mock_get_cfg.return_value = {
            "api_key": "SUPER_SECRET_KEY_NEVER_LOGGED",
            "model_name": "gemini-3.5-flash-lite",
            "base_url": "",
        }
        mock_direct.return_value = make_sample_plan(count=2)

        script = "Primeira cena histórica. Segunda cena de desfecho."
        res = prepare_project(
            script_text=script,
            project_name="director_test",
            base_dir=self.test_dir,
            visual_director_enabled=True,
            visual_style_brief="Documentary Noir",
        )

        import json
        with open(res["manifest_path"], "r", encoding="utf-8") as f:
            manifest = json.load(f)

        self.assertIn("visual_director", manifest)
        vd_meta = manifest["visual_director"]
        self.assertTrue(vd_meta["enabled"])
        self.assertEqual(vd_meta["provider"], "gemini")
        self.assertEqual(vd_meta["model"], "gemini-3.5-flash-lite")
        self.assertNotIn("SUPER_SECRET_KEY", json.dumps(manifest))

        for sc in manifest["scenes"]:
            self.assertIn("visual_direction", sc)
            self.assertIn("subject", sc["visual_direction"])
            self.assertIn("action", sc["visual_direction"])
            self.assertIn("environment", sc["visual_direction"])
            self.assertIn("stock_search_terms", sc["visual_direction"])
            self.assertIn("vertical 9:16 portrait", sc["prompt_en"])

    @patch("scripts.flow_workflow.direct_scenes")
    def test_visual_director_failed_raises_explicit_error(self, mock_direct):
        """17. Falha do Visual Director resulta em erro explícito VISUAL_DIRECTOR_FAILED."""
        mock_direct.side_effect = RuntimeError("VISUAL_DIRECTOR_FAILED: Rate limit exceeded")
        script = "Cena única para teste de falha."

        with self.assertRaises(RuntimeError) as ctx:
            prepare_project(
                script_text=script,
                project_name="fail_test",
                base_dir=self.test_dir,
                visual_director_enabled=True,
            )
        self.assertIn("VISUAL_DIRECTOR_FAILED", str(ctx.exception))

    @patch("app.services.visual_director.direct_scenes")
    def test_preview_visual_direction_uses_video_subject(self, mock_direct):
        """18. preview_visual_direction extrai corretamente video_subject do manifest."""
        manifest_data = {
            "video_subject": "Canonical Subject JFK",
            "niche": "historias_misterios",
            "scenes": [
                {
                    "scene_index": 1,
                    "narration": "Texto de abertura.",
                    "visual_intent": "historical",
                    "search_terms": ["jfk", "dallas"],
                }
            ],
        }
        manifest_path = os.path.join(self.test_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f)

        mock_direct.return_value = make_sample_plan(count=1)

        preview_visual_direction(manifest_path)

        mock_direct.assert_called_once()
        call_kwargs = mock_direct.call_args[1]
        self.assertEqual(call_kwargs.get("video_subject"), "Canonical Subject JFK")

    @patch("app.services.visual_director.get_gemini_config")
    def test_direct_scenes_sanitizes_sensitive_error_in_log_and_exception(self, mock_get_cfg):
        """19. Exceção com URL/API key sensível é sanitizada sem expor credenciais no log ou erro."""
        mock_get_cfg.return_value = {
            "api_key": "dummy_key",
            "model_name": "gemini-3.5-flash-lite",
            "base_url": "",
        }

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = RuntimeError(
            "Connection failed: https://user:password@example.com/v1?api_key=SECRET"
        )

        scenes = [{"scene_index": 1, "narration": "Test narration"}]

        with self.assertRaises(RuntimeError) as ctx:
            direct_scenes(
                scenes=scenes,
                video_subject="Test Subject",
                client=mock_client,
            )

        err_text = str(ctx.exception)
        self.assertNotIn("password", err_text)
        self.assertNotIn("SECRET", err_text)
        self.assertIn("***:***@", err_text)
        self.assertIn("api_key=***", err_text)
        self.assertIn("VISUAL_DIRECTOR_FAILED", err_text)

    def test_comparison_legacy_director_does_not_alter_manifest(self):
        """20. Comparação entre prompt legado e visual director não altera o manifest original."""
        original_manifest = {
            "video_subject": "Quantum Paradox",
            "scenes": [
                {
                    "scene_index": 1,
                    "narration": "O experimento começou às três da manhã.",
                    "prompt_en": "Legacy prompt text",
                    "visual_intent": "science lab",
                }
            ],
        }
        manifest_copy = json.loads(json.dumps(original_manifest))

        spec = make_sample_spec(scene_index=1)
        compiled_dir_prompt = compile_flow_prompt(spec)
        legacy_prompt = original_manifest["scenes"][0]["prompt_en"]

        self.assertNotEqual(compiled_dir_prompt, legacy_prompt)
        self.assertEqual(original_manifest, manifest_copy)

    @patch("scripts.flow_playwright.sync_playwright")
    def test_semantic_review_does_not_open_browser(self, mock_playwright):
        """21. Revisão e compilação de direção visual opera estritamente offline sem abrir browser."""
        spec = make_sample_spec(scene_index=1)
        prompt = compile_flow_prompt(spec)
        self.assertTrue(len(prompt) > 20)
        mock_playwright.assert_not_called()

    def test_football_prompt_contains_non_identifiable_fictional_guidance(self):
        """22. Prompt para nicho futebol contém diretrizes explícitas de atletas fictícios e não identificáveis."""
        scenes = [{"scene_index": 1, "narration": "O atacante cabeceou a bola para o gol."}]
        prompt = build_director_prompt(scenes, video_subject="Gol de Placa", niche="futebol")
        p_lower = prompt.lower()
        self.assertIn("fictional, non-identifiable football", p_lower)
        self.assertIn("no resemblance to real or famous", p_lower)
        self.assertIn("no real club logos", p_lower)
        self.assertIn("prioritize athletic action over facial identity", p_lower)

    def test_generic_football_prompt_contains_no_forced_real_player_club(self):
        """23. Prompt genérico de futebol não força nem cita nenhum jogador ou clube real específico."""
        scenes = [{"scene_index": 1, "narration": "A bola cruzou a grande área."}]
        prompt = build_director_prompt(scenes, video_subject="Cruzamento Perfeito", niche="futebol")
        # Confirma que não menciona nomes de celebridades esportivas reais
        for famous in ["Neymar", "Messi", "Cristiano Ronaldo", "Pelé", "Mbappé", "Flamengo", "Real Madrid"]:
            self.assertNotIn(famous, prompt)

    def test_non_football_niches_unchanged(self):
        """24. Nichos não-futebol preservam suas diretrizes específicas sem injetar regras de futebol."""
        scenes = [{"scene_index": 1, "narration": "O acelerador de partículas detectou a anomalia."}]
        prompt = build_director_prompt(scenes, video_subject="Física Quântica", niche="curiosidades_ciencia")
        self.assertNotIn("SPECIAL DIRECTIVE FOR FOOTBALL NICHE", prompt)
        self.assertIn("curiosidades_ciencia", prompt)
        self.assertIn("scientific/macro imagery", prompt)


if __name__ == "__main__":
    unittest.main()
