"""
test/services/test_v16_4_scene_based_video_generation.py
========================================================
Testes Unitários da Fase V16.4 — Scene-Based Video Generation.

Regra Fundamental:
AUTONOMOUS_SCENE_VISUALS_MUST_FOLLOW_SCRIPT_ORDER = REQUIRED

Cobertura de Testes:
1. Scene Planner:
   - Planejamento determinístico com índices 1..N.
   - Script vazio falha fechado (SCENE_PLAN_EMPTY).
   - Frase única e textos longos.
   - Preservação de acentos e caracteres em português (pt-BR).
   - Validador de plano (planos vazios, índices descontínuos, duplicados, termos vazios).
2. Scene Material Resolver:
   - Resolução individual de materiais por cena.
   - Fallback ordenado entre termos da cena e genérico.
   - Prevenção de repetição consecutiva do mesmo ativo.
   - Falha fechada (strict) quando material está ausente (SCENE_MATERIAL_MISSING).
   - Persistência e proveniência (script_data).
3. Scene Assembly:
   - Montagem sequencial estrita mantendo a ordem exata das cenas.
   - Distribuição proporcional de duração com base no áudio.
   - Rejeição de seleções duplicadas ou faltantes.
4. Integração na Pipeline:
   - Pipeline ponta a ponta com scene_based_generation_enabled=True.
   - Preservação do fluxo manual com scene_based_generation_enabled=False.
   - Configuração autônoma padrão ativa scene_based_generation_enabled.
"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.models import const
from app.models.schema import (
    MaterialInfo,
    SceneClipInstruction,
    SceneMaterialSelection,
    ScenePlan,
    ScenePlanItem,
    VideoAspect,
    VideoParams,
)
from app.services import (
    autonomous_production,
    scene_assembly,
    scene_material,
    scene_planner,
    task as tm,
    task_artifacts,
    video,
)


class TestScenePlanner(unittest.TestCase):
    """Testes unitários para o Scene Planner."""

    def test_plan_scenes_basic(self):
        script = (
            "A Floresta Amazônica abriga a maior biodiversidade do planeta Terra. "
            "Seus rios imensos cortam milhares de quilômetros de matas preservadas. "
            "Proteger esse ecossistema vital é crucial para o equilíbrio climático mundial."
        )
        plan = scene_planner.plan_scenes(
            video_script=script,
            target_scene_duration=5.0,
            task_id="task_basic_test",
        )

        self.assertIsInstance(plan, ScenePlan)
        self.assertGreaterEqual(plan.total_scenes, 2)
        self.assertEqual(len(plan.scenes), plan.total_scenes)

        for idx, scene in enumerate(plan.scenes):
            self.assertEqual(scene.scene_index, idx + 1)
            self.assertTrue(len(scene.narration) > 0)
            self.assertTrue(len(scene.search_terms) > 0)
            self.assertGreater(scene.duration_hint, 0.0)
            self.assertTrue(isinstance(scene.visual_intent, str))

    def test_plan_scenes_empty_script_raises_error(self):
        with self.assertRaises(scene_planner.ScenePlanError) as ctx:
            scene_planner.plan_scenes("", task_id="task_empty")
        self.assertEqual(ctx.exception.reason_code, "SCENE_PLAN_EMPTY")

        with self.assertRaises(scene_planner.ScenePlanError) as ctx2:
            scene_planner.plan_scenes("   \n\t   ", task_id="task_spaces")
        self.assertEqual(ctx2.exception.reason_code, "SCENE_PLAN_EMPTY")

    def test_plan_scenes_single_sentence(self):
        script = "O telescópio James Webb revelou galáxias formadas logo após o Big Bang."
        plan = scene_planner.plan_scenes(script, task_id="task_single")
        self.assertEqual(plan.total_scenes, 1)
        self.assertEqual(plan.scenes[0].scene_index, 1)
        self.assertIn("telescópio", plan.scenes[0].narration)
        self.assertGreater(len(plan.scenes[0].search_terms), 0)

    def test_plan_scenes_portuguese_accents_preserved(self):
        script = (
            "A preservação do coração das matas e das regiões com vegetação nativa é essencial. "
            "Sem ações eficazes, a proteção não acontecerá nos próximos séculos."
        )
        plan = scene_planner.plan_scenes(script, task_id="task_accents")
        self.assertGreaterEqual(len(plan.scenes), 1)
        full_narration = " ".join(s.narration for s in plan.scenes)
        self.assertIn("coração", full_narration)
        self.assertIn("ações", full_narration)
        self.assertIn("séculos", full_narration)

    def test_validate_scene_plan_scenarios(self):
        # 1. Plano válido
        valid_scenes = [
            ScenePlanItem(scene_index=1, narration="Primeira cena", search_terms=["nature"]),
            ScenePlanItem(scene_index=2, narration="Segunda cena", search_terms=["city"]),
        ]
        valid_plan = ScenePlan(scenes=valid_scenes, total_scenes=2)
        is_valid, reasons = scene_planner.validate_scene_plan(valid_plan)
        self.assertTrue(is_valid)
        self.assertEqual(reasons, [])

        # 2. Plano vazio
        empty_plan = ScenePlan(scenes=[], total_scenes=0)
        is_valid, reasons = scene_planner.validate_scene_plan(empty_plan)
        self.assertFalse(is_valid)
        self.assertIn("SCENE_PLAN_EMPTY", reasons)

        # 3. Ordem inválida / pulo de índice
        invalid_order = ScenePlan(
            scenes=[
                ScenePlanItem(scene_index=1, narration="Cena 1", search_terms=["a"]),
                ScenePlanItem(scene_index=3, narration="Cena 3", search_terms=["b"]),
            ],
            total_scenes=2,
        )
        is_valid, reasons = scene_planner.validate_scene_plan(invalid_order)
        self.assertFalse(is_valid)
        self.assertIn("SCENE_ORDER_INVALID", reasons)

        # 4. Índice duplicado
        duplicate_idx = ScenePlan(
            scenes=[
                ScenePlanItem(scene_index=1, narration="Cena 1", search_terms=["a"]),
                ScenePlanItem(scene_index=1, narration="Cena 1 duplicada", search_terms=["b"]),
            ],
            total_scenes=2,
        )
        is_valid, reasons = scene_planner.validate_scene_plan(duplicate_idx)
        self.assertFalse(is_valid)
        self.assertIn("SCENE_INDEX_INVALID", reasons)

        # 5. Narração vazia
        empty_narration = ScenePlan(
            scenes=[
                ScenePlanItem(scene_index=1, narration="   ", search_terms=["a"]),
            ],
            total_scenes=1,
        )
        is_valid, reasons = scene_planner.validate_scene_plan(empty_narration)
        self.assertFalse(is_valid)
        self.assertIn("SCENE_INVALID", reasons)

        # 6. Termos vazios
        empty_terms = ScenePlan(
            scenes=[
                ScenePlanItem(scene_index=1, narration="Cena válida", search_terms=[]),
            ],
            total_scenes=1,
        )
        is_valid, reasons = scene_planner.validate_scene_plan(empty_terms, strict=True)
        self.assertFalse(is_valid)
        self.assertIn("SCENE_TERMS_EMPTY", reasons)


class TestSceneMaterial(unittest.TestCase):
    """Testes unitários para o Scene Material Resolver."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="scene_mat_test_")
        self.dummy_video_path = os.path.join(self.test_dir, "clip1.mp4")
        with open(self.dummy_video_path, "wb") as f:
            f.write(b"dummy video data")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("app.services.material._search_videos_with_cache")
    @patch("app.services.material.save_video")
    @patch("app.services.task_artifacts.patch_script_data")
    def test_scene_material_resolution_success(self, mock_patch, mock_save, mock_search):
        mock_save.return_value = self.dummy_video_path
        mock_search.return_value = [
            MaterialInfo(
                provider="pexels",
                url="https://example.com/video1.mp4",
                duration=10.0,
                source_info={"asset_id": "asset_100", "source_page": "https://pexels.com/100"},
            )
        ]

        plan = ScenePlan(
            scenes=[
                ScenePlanItem(scene_index=1, narration="Cena 1", search_terms=["term1"]),
                ScenePlanItem(scene_index=2, narration="Cena 2", search_terms=["term2"]),
            ],
            total_scenes=2,
        )
        params = VideoParams(video_subject="Teste")

        selections = scene_material.resolve_scene_materials(
            task_id="task_res_success",
            scene_plan=plan,
            params=params,
        )

        self.assertEqual(len(selections), 2)
        self.assertEqual(selections[0].scene_index, 1)
        self.assertEqual(selections[1].scene_index, 2)
        self.assertEqual(selections[0].search_term_used, "term1")
        self.assertFalse(selections[0].fallback_used)
        self.assertEqual(selections[0].material_path, self.dummy_video_path)
        self.assertTrue(mock_patch.called)

    @patch("app.services.material._search_videos_with_cache")
    @patch("app.services.material.save_video")
    @patch("app.services.task_artifacts.patch_script_data")
    def test_scene_material_fallback_to_second_term(self, mock_patch, mock_save, mock_search):
        mock_save.return_value = self.dummy_video_path

        def search_side_effect(provider, search_videos, search_term, **kwargs):
            if search_term == "primary_fail":
                return []
            if search_term == "secondary_ok":
                return [
                    MaterialInfo(
                        provider="pexels",
                        url="https://example.com/video_fb.mp4",
                        duration=8.0,
                        source_info={"asset_id": "asset_fb"},
                    )
                ]
            return []

        mock_search.side_effect = search_side_effect

        plan = ScenePlan(
            scenes=[
                ScenePlanItem(
                    scene_index=1,
                    narration="Cena com fallback",
                    search_terms=["primary_fail", "secondary_ok"],
                )
            ],
            total_scenes=1,
        )
        params = VideoParams(video_subject="Fallback")

        selections = scene_material.resolve_scene_materials(
            task_id="task_fallback",
            scene_plan=plan,
            params=params,
        )

        self.assertEqual(len(selections), 1)
        self.assertEqual(selections[0].search_term_used, "secondary_ok")
        self.assertTrue(selections[0].fallback_used)

    @patch("app.services.material._search_videos_with_cache")
    @patch("app.services.material.save_video")
    def test_scene_material_consecutive_duplicate_avoidance(self, mock_save, mock_search):
        mock_save.return_value = self.dummy_video_path

        candidate_a = MaterialInfo(
            provider="pexels",
            url="https://example.com/video_a.mp4",
            duration=10.0,
            source_info={"asset_id": "asset_A"},
        )
        candidate_b = MaterialInfo(
            provider="pexels",
            url="https://example.com/video_b.mp4",
            duration=10.0,
            source_info={"asset_id": "asset_B"},
        )

        # Ambas as buscas retornam candidates A e B
        mock_search.return_value = [candidate_a, candidate_b]

        plan = ScenePlan(
            scenes=[
                ScenePlanItem(scene_index=1, narration="Cena 1", search_terms=["common"]),
                ScenePlanItem(scene_index=2, narration="Cena 2", search_terms=["common"]),
            ],
            total_scenes=2,
        )
        params = VideoParams(video_subject="Duplicata")

        selections = scene_material.resolve_scene_materials(
            task_id="task_dedup",
            scene_plan=plan,
            params=params,
        )

        self.assertEqual(len(selections), 2)
        # Cena 1 pega o primeiro (A)
        self.assertEqual(selections[0].asset_id, "asset_A")
        # Cena 2 evita A consecutivamente e escolhe B
        self.assertEqual(selections[1].asset_id, "asset_B")

    @patch("app.services.material._search_videos_with_cache")
    def test_scene_material_strict_fail_closed(self, mock_search):
        mock_search.return_value = []  # Nenhum material disponível em nenhum termo

        plan = ScenePlan(
            scenes=[
                ScenePlanItem(scene_index=1, narration="Cena sem material", search_terms=["sem_termo"]),
            ],
            total_scenes=1,
        )
        params = VideoParams(video_subject="SemMaterial")

        with self.assertRaises(scene_material.SceneMaterialError) as ctx:
            scene_material.resolve_scene_materials(
                task_id="task_fail_closed",
                scene_plan=plan,
                params=params,
                strict=True,
            )
        self.assertEqual(ctx.exception.reason_code, "SCENE_MATERIAL_MISSING")

    @patch("app.services.material._search_videos_with_cache")
    @patch("app.services.material.save_video")
    def test_scene_material_filters_banned_generic_terms(self, mock_save, mock_search):
        mock_save.return_value = self.dummy_video_path
        searched_terms = []

        def search_side_effect(search_term, **kwargs):
            searched_terms.append(search_term)
            return [
                MaterialInfo(
                    provider="pexels",
                    url="https://example.com/v.mp4",
                    duration=10.0,
                    source_info={"asset_id": "asset_forest"},
                )
            ]

        mock_search.side_effect = search_side_effect

        plan = ScenePlan(
            scenes=[
                ScenePlanItem(
                    scene_index=1,
                    narration="Cena com termos genéricos",
                    search_terms=["fundo de video", "floresta amazonica", "video escuro"],
                )
            ],
            total_scenes=1,
        )
        params = VideoParams(video_subject="Termos Proibidos")

        selections = scene_material.resolve_scene_materials(
            task_id="task_banned_filter",
            scene_plan=plan,
            params=params,
        )

        # Apenas "floresta amazonica" deve ter sido pesquisado
        self.assertEqual(searched_terms, ["floresta amazonica"])
        self.assertEqual(selections[0].search_term_used, "floresta amazonica")

        # Se todos os termos da cena forem proibidos, strict mode falha com SCENE_TERMS_EMPTY_OR_BANNED
        plan_all_banned = ScenePlan(
            scenes=[
                ScenePlanItem(
                    scene_index=1,
                    narration="Cena somente genérica",
                    search_terms=["fundo de video", "background video"],
                )
            ],
            total_scenes=1,
        )
        with self.assertRaises(scene_material.SceneMaterialError) as ctx:
            scene_material.resolve_scene_materials(
                task_id="task_all_banned",
                scene_plan=plan_all_banned,
                params=params,
                strict=True,
            )
        self.assertEqual(ctx.exception.reason_code, "SCENE_TERMS_EMPTY_OR_BANNED")

    @patch("app.services.material._search_videos_with_cache")
    def test_scene_material_rejects_generic_visual_intent_in_strict(self, mock_search):
        searched_terms = []

        def search_side_effect(search_term, **kwargs):
            searched_terms.append(search_term)
            if search_term == "cinematic stock":
                return [
                    MaterialInfo(
                        provider="pexels",
                        url="https://example.com/cinematic.mp4",
                        duration=10.0,
                        source_info={"asset_id": "asset_cinematic_generic"},
                    )
                ]
            return []

        mock_search.side_effect = search_side_effect

        plan = ScenePlan(
            scenes=[
                ScenePlanItem(
                    scene_index=1,
                    narration="Roteiro narrativo da cena",
                    search_terms=["termo_especifico_sem_resultado"],
                    visual_intent="cinematic stock",
                )
            ],
            total_scenes=1,
        )
        params = VideoParams(video_subject="")

        with self.assertRaises(scene_material.SceneMaterialError) as ctx:
            scene_material.resolve_scene_materials(
                task_id="task_reject_generic_vi",
                scene_plan=plan,
                params=params,
                strict=True,
            )

        self.assertEqual(ctx.exception.reason_code, "SCENE_MATERIAL_MISSING")
        self.assertNotIn("cinematic stock", searched_terms)
        self.assertNotIn("cinematic stock", [t.lower() for t in searched_terms])


class TestSceneAssembly(unittest.TestCase):
    """Testes unitários para o Scene Assembly."""

    def test_scene_assembly_order_preservation(self):
        plan = ScenePlan(
            scenes=[
                ScenePlanItem(scene_index=1, narration="Cena 1", search_terms=["a"], duration_hint=5.0),
                ScenePlanItem(scene_index=2, narration="Cena 2", search_terms=["b"], duration_hint=5.0),
                ScenePlanItem(scene_index=3, narration="Cena 3", search_terms=["c"], duration_hint=5.0),
            ],
            total_scenes=3,
        )
        materials = [
            SceneMaterialSelection(scene_index=1, material_path="/path/to/video1.mp4"),
            SceneMaterialSelection(scene_index=2, material_path="/path/to/video2.mp4"),
            SceneMaterialSelection(scene_index=3, material_path="/path/to/video3.mp4"),
        ]

        instructions = scene_assembly.assemble_scene_clips(
            scene_plan=plan,
            material_selections=materials,
            audio_duration=15.0,
        )

        self.assertEqual(len(instructions), 3)
        self.assertEqual([inst.scene_index for inst in instructions], [1, 2, 3])
        self.assertEqual(
            scene_assembly.get_ordered_video_paths(instructions),
            ["/path/to/video1.mp4", "/path/to/video2.mp4", "/path/to/video3.mp4"],
        )

    def test_scene_assembly_duration_proportional_distribution(self):
        plan = ScenePlan(
            scenes=[
                ScenePlanItem(scene_index=1, narration="Curta", search_terms=["a"], duration_hint=2.0),
                ScenePlanItem(scene_index=2, narration="Longa", search_terms=["b"], duration_hint=8.0),
            ],
            total_scenes=2,
        )
        materials = [
            SceneMaterialSelection(scene_index=1, material_path="/v1.mp4"),
            SceneMaterialSelection(scene_index=2, material_path="/v2.mp4"),
        ]

        instructions = scene_assembly.assemble_scene_clips(
            scene_plan=plan,
            material_selections=materials,
            audio_duration=20.0,
        )

        total_dur = sum(inst.duration_seconds for inst in instructions)
        self.assertAlmostEqual(total_dur, 20.0, places=2)
        # Cena 2 deve ter duração significativamente maior que cena 1
        self.assertGreater(instructions[1].duration_seconds, instructions[0].duration_seconds)

    def test_scene_assembly_duplicate_or_missing_fails_closed(self):
        plan = ScenePlan(
            scenes=[
                ScenePlanItem(scene_index=1, narration="Cena 1", search_terms=["a"]),
                ScenePlanItem(scene_index=2, narration="Cena 2", search_terms=["b"]),
            ],
            total_scenes=2,
        )

        # Faltando material para cena 2
        missing_materials = [
            SceneMaterialSelection(scene_index=1, material_path="/v1.mp4"),
        ]
        with self.assertRaises(scene_assembly.SceneAssemblyError) as ctx:
            scene_assembly.assemble_scene_clips(plan, missing_materials)
        self.assertEqual(ctx.exception.reason_code, "SCENE_MATERIAL_MISSING")

        # Material duplicado para cena 1
        duplicate_materials = [
            SceneMaterialSelection(scene_index=1, material_path="/v1.mp4"),
            SceneMaterialSelection(scene_index=1, material_path="/v1_alt.mp4"),
        ]
        with self.assertRaises(scene_assembly.SceneAssemblyError) as ctx2:
            scene_assembly.assemble_scene_clips(plan, duplicate_materials)
        self.assertEqual(ctx2.exception.reason_code, "SCENE_INDEX_INVALID")


class TestPipelineSceneIntegration(unittest.TestCase):
    """Testes de integração com a pipeline (task.py e autonomous_production.py)."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="pipeline_scene_test_")
        self.dummy_video_path = os.path.join(self.test_dir, "final-1.mp4")
        with open(self.dummy_video_path, "wb") as f:
            f.write(b"dummy mp4" * 2000)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("app.services.profile_manager.get_active_profile_id", return_value="default")
    @patch("app.services.profile_manager.get_generation_profile_context", return_value={"voice_name": "pt-BR-AntonioNeural", "voice_mode": "tts"})
    def test_build_autonomous_video_params_enables_scene_generation(self, mock_ctx, mock_active):
        params = autonomous_production.build_autonomous_video_params(
            topic="Roteiro Autônomo",
            profile_id="default",
        )
        self.assertTrue(params.scene_based_generation_enabled)
        self.assertEqual(params.video_language, "pt-BR")
        self.assertEqual(params.region, "BR")

    @patch("app.services.task.generate_script")
    @patch("app.services.scene_planner.plan_scenes")
    @patch("app.services.scene_material.resolve_scene_materials")
    @patch("app.services.scene_assembly.assemble_scene_clips")
    @patch("app.services.task_artifacts.patch_script_data")
    @patch("app.services.task.save_script_data")
    @patch("app.services.state.state.update_task")
    @patch("app.services.task.generate_audio")
    @patch("app.services.task.generate_subtitle")
    @patch("app.services.task.generate_final_videos")
    @patch("app.services.media_quality.evaluate_final_media_quality")
    def test_pipeline_executes_scene_flow_when_enabled(
        self,
        mock_quality,
        mock_final_videos,
        mock_subtitle,
        mock_audio,
        mock_update_task,
        mock_save_script,
        mock_patch_script,
        mock_assemble,
        mock_resolve,
        mock_plan,
        mock_gen_script,
    ):
        mock_gen_script.return_value = "Texto do roteiro completo para vídeo de cena."
        mock_plan.return_value = ScenePlan(
            scenes=[
                ScenePlanItem(scene_index=1, narration="Cena 1", search_terms=["tech"]),
                ScenePlanItem(scene_index=2, narration="Cena 2", search_terms=["ai"]),
            ],
            total_scenes=2,
        )
        mock_audio.return_value = ("/path/audio.mp3", 10.0, None)
        mock_subtitle.return_value = "/path/sub.srt"

        mock_resolve.return_value = [
            SceneMaterialSelection(scene_index=1, material_path=self.dummy_video_path),
            SceneMaterialSelection(scene_index=2, material_path=self.dummy_video_path),
        ]
        mock_assemble.return_value = [
            SceneClipInstruction(scene_index=1, material_path=self.dummy_video_path, duration_seconds=5.0),
            SceneClipInstruction(scene_index=2, material_path=self.dummy_video_path, duration_seconds=5.0),
        ]
        mock_final_videos.return_value = ([self.dummy_video_path], [self.dummy_video_path], [])
        mock_quality.return_value = {"valid": True, "status": "PASS", "reasons": [], "metrics": {}}

        params = VideoParams(
            video_subject="Teste Integração",
            scene_based_generation_enabled=True,
            subtitle_required=False,
            final_media_quality_required=False,
        )

        res = tm._run_pipeline(
            task_id="task_pipeline_scene_test",
            params=params,
            stop_at="video",
        )

        self.assertTrue(mock_plan.called)
        self.assertTrue(mock_resolve.called)
        self.assertTrue(mock_assemble.called)
        self.assertNotIn("error", res)

    @patch("app.services.task.generate_script")
    @patch("app.services.scene_planner.plan_scenes")
    @patch("app.services.task.get_video_materials")
    @patch("app.services.task.generate_terms")
    @patch("app.services.task_artifacts.patch_script_data")
    @patch("app.services.task.save_script_data")
    @patch("app.services.state.state.update_task")
    @patch("app.services.task.generate_audio")
    @patch("app.services.task.generate_subtitle")
    @patch("app.services.task.generate_final_videos")
    def test_pipeline_preserves_manual_flow_when_disabled(
        self,
        mock_final_videos,
        mock_subtitle,
        mock_audio,
        mock_update_task,
        mock_save_script,
        mock_patch_script,
        mock_gen_terms,
        mock_get_materials,
        mock_plan,
        mock_gen_script,
    ):
        mock_gen_script.return_value = "Roteiro manual padrão."
        mock_gen_terms.return_value = ["nature", "forest"]
        mock_audio.return_value = ("/path/audio.mp3", 10.0, None)
        mock_subtitle.return_value = "/path/sub.srt"
        mock_get_materials.return_value = [self.dummy_video_path]
        mock_final_videos.return_value = ([self.dummy_video_path], [self.dummy_video_path], [])

        params = VideoParams(
            video_subject="Manual",
            scene_based_generation_enabled=False,  # Fluxo manual
            subtitle_required=False,
            final_media_quality_required=False,
        )

        res = tm._run_pipeline(
            task_id="task_pipeline_manual_test",
            params=params,
            stop_at="video",
        )

        # O planejador de cenas NÃO deve ser chamado quando desabilitado
        self.assertFalse(mock_plan.called)
        # O fluxo tradicional de materiais DEVE ser chamado
        self.assertTrue(mock_get_materials.called)
        self.assertNotIn("error", res)


class TestSceneRenderFailClosed(unittest.TestCase):
    """Testes para garantir renderização fail-closed de cenas."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="scene_render_test_")
        self.dummy_video_path = os.path.join(self.test_dir, "clip.mp4")
        with open(self.dummy_video_path, "wb") as f:
            f.write(b"dummy clip data" * 100)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("app.services.video.AudioFileClip")
    def test_combine_videos_raises_on_missing_material(self, mock_audio_clip):
        mock_audio_instance = MagicMock()
        mock_audio_instance.duration = 5.0
        mock_audio_clip.return_value = mock_audio_instance
        instructions = [
            SceneClipInstruction(scene_index=1, material_path="/non/existent/path.mp4", duration_seconds=5.0)
        ]
        with self.assertRaises(video.SceneRenderError) as ctx:
            video.combine_videos(
                combined_video_path=os.path.join(self.test_dir, "out.mp4"),
                video_paths=[],
                audio_file="dummy.mp3",
                video_aspect=VideoAspect.portrait,
                max_clip_duration=5,
                threads=1,
                scene_clip_instructions=instructions,
            )
        self.assertEqual(ctx.exception.reason_code, "SCENE_RENDER_FAILURE")

    @patch("app.services.video.AudioFileClip")
    @patch("app.services.video._open_video_clip_quietly")
    def test_combine_videos_raises_on_clip_decode_error(self, mock_open, mock_audio_clip):
        mock_audio_instance = MagicMock()
        mock_audio_instance.duration = 5.0
        mock_audio_clip.return_value = mock_audio_instance
        mock_open.side_effect = RuntimeError("decoder error")
        instructions = [
            SceneClipInstruction(scene_index=1, material_path=self.dummy_video_path, duration_seconds=5.0)
        ]
        with self.assertRaises(video.SceneRenderError) as ctx:
            video.combine_videos(
                combined_video_path=os.path.join(self.test_dir, "out.mp4"),
                video_paths=[],
                audio_file="dummy.mp3",
                video_aspect=VideoAspect.portrait,
                max_clip_duration=5,
                threads=1,
                scene_clip_instructions=instructions,
            )
        self.assertEqual(ctx.exception.reason_code, "SCENE_RENDER_FAILURE")

    @patch("app.services.task.generate_script")
    @patch("app.services.scene_planner.plan_scenes")
    @patch("app.services.scene_material.resolve_scene_materials")
    @patch("app.services.scene_assembly.assemble_scene_clips")
    @patch("app.services.task_artifacts.patch_script_data")
    @patch("app.services.task.save_script_data")
    @patch("app.services.state.state.update_task")
    @patch("app.services.task.generate_audio")
    @patch("app.services.task.generate_subtitle")
    @patch("app.services.task.generate_final_videos")
    def test_pipeline_fails_closed_when_scene_render_fails(
        self,
        mock_final_videos,
        mock_subtitle,
        mock_audio,
        mock_update_task,
        mock_save_script,
        mock_patch_script,
        mock_assemble,
        mock_resolve,
        mock_plan,
        mock_gen_script,
    ):
        mock_gen_script.return_value = "Roteiro para teste de falha de render."
        mock_plan.return_value = ScenePlan(
            scenes=[ScenePlanItem(scene_index=1, narration="Cena 1", search_terms=["term1"])],
            total_scenes=1,
        )
        mock_audio.return_value = ("/path/audio.mp3", 5.0, None)
        mock_subtitle.return_value = "/path/sub.srt"
        mock_resolve.return_value = [
            SceneMaterialSelection(scene_index=1, material_path=self.dummy_video_path)
        ]
        mock_assemble.return_value = [
            SceneClipInstruction(scene_index=1, material_path=self.dummy_video_path, duration_seconds=5.0)
        ]
        mock_final_videos.side_effect = video.SceneRenderError("failed rendering scene 1")

        params = VideoParams(
            video_subject="FailRender",
            scene_based_generation_enabled=True,
            subtitle_required=False,
            final_media_quality_required=False,
        )

        res = tm._run_pipeline(
            task_id="task_render_fail_test",
            params=params,
            stop_at="video",
        )

        self.assertEqual(res.get("state"), const.TASK_STATE_FAILED)
        self.assertEqual(res.get("failed_stage"), "scene_render")
        self.assertIn("failed to render video", res.get("error", ""))


if __name__ == "__main__":
    unittest.main()
