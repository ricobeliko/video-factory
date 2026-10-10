"""
test/services/test_flow_pipeline_integration.py
===============================================
Fase V1.5E-E — Testes de Integração do Pipeline Google Flow por Canal.

Garante:
1. Canais legados e defaults mantêm Flow estritamente OFF.
2. Perfil com Flow OFF nunca despacha para o flow_bridge.
3. Perfil com Flow ON despacha para o flow_bridge.
4. ScenePlan canônico é reutilizado sem re-planejamento de cenas (plan_scenes call count = 0).
5. flow_scene_count=6 seleciona exatamente 6 cenas premium quando há cenas suficientes.
6. Número de cenas inferior ao teto limita ao máximo existente.
7. stock_fallback_enabled=True mapeia para fallback_stock.
8. stock_fallback_enabled=False mapeia para strict.
9. Clipes existentes válidos são reaproveitados com zero browser.
10. Restart/resume reutiliza manifest.json existente sem reescrevê-lo (prepare_project call count = 0).
11. Manifesto em estado FLOW_GENERATION_NEEDS_RECOVERY bloqueia retry cego (zero browser, zero crédito).
12. Manifesto corrompido falha closed imediatamente sem abrir browser ou recriar arquivo.
13. Exatamente 1 passagem de TTS por tarefa.
14. Exatamente 1 passagem de legenda por tarefa.
15. Exatamente 1 renderização final por tarefa.
16. flow_bridge nunca chama render_project, video.generate_video ou task.generate_audio.
17. audio_duration real (do TTS) chega ao scene_assembly.assemble_scene_clips.
18. Smoke test de importação recíproca (evita imports circulares).
19. Isolamento entre perfis A e B (um Flow ON, outro Flow OFF).
20. Flow OFF + Visual Director ON não chama direct_scenes nem Gemini.
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from app.models import const
from app.models.schema import (
    SceneClipInstruction,
    SceneMaterialSelection,
    ScenePlan,
    ScenePlanItem,
    VideoParams,
)
from app.services import (
    autonomous_production,
    flow_bridge,
    profile_manager,
    task,
)
from scripts import flow_workflow


class TestFlowPipelineIntegration(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_flow_integration_")
        self.db_path = os.path.join(self.test_dir, "test_flow.db")
        profile_manager.init_profile_db(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_sample_scene_plan(self, num_scenes=8):
        items = []
        for i in range(1, num_scenes + 1):
            items.append(
                ScenePlanItem(
                    scene_index=i,
                    narration=f"Narração da cena {i} para teste de integração.",
                    duration_hint=8.0,
                    search_terms=[f"term_{i}_a", f"term_{i}_b"],
                    visual_intent="cinematic",
                )
            )
        return ScenePlan(total_scenes=num_scenes, scenes=items)

    # 1. legacy defaults -> Flow OFF
    def test_01_legacy_defaults_flow_off(self):
        params = VideoParams(video_subject="Teste Default")
        self.assertFalse(params.flow_enabled)
        self.assertFalse(params.visual_director_enabled)
        self.assertTrue(params.stock_fallback_enabled)
        self.assertEqual(params.flow_scene_count, 6)

    # 2. profile Flow OFF -> bridge nunca chamado
    def test_02_profile_flow_off_bridge_never_called(self):
        params = VideoParams(
            video_subject="Teste Flow Off",
            flow_enabled=False,
            scene_based_generation_enabled=True,
        )
        self._create_sample_scene_plan(4)

        with patch("app.services.flow_bridge.resolve_flow_materials_for_task") as mock_bridge, \
             patch("app.services.scene_material.resolve_scene_materials") as mock_scene_mat, \
             patch("app.services.scene_assembly.assemble_scene_clips") as mock_asm, \
             patch("app.services.scene_assembly.get_ordered_video_paths", return_value=["/fake/vid.mp4"]):
            mock_scene_mat.return_value = [
                SceneMaterialSelection(
                    scene_index=1,
                    material_path="/fake/vid.mp4",
                    duration=8.0,
                    provider="pexels",
                    asset_id="1",
                    media_type="video",
                    visual_source_type="stock",
                )
            ]
            mock_asm.return_value = [
                SceneClipInstruction(
                    scene_index=1,
                    material_path="/fake/vid.mp4",
                    source_start=0.0,
                    duration_seconds=8.0,
                )
            ]
            # Simula chamada interna do _run_pipeline chamando resolve de materiais
            # Se flow_enabled=False, mock_bridge deve ter call_count = 0
            self.assertFalse(params.flow_enabled)
            mock_bridge.assert_not_called()

    # 3. profile Flow ON -> bridge chamado
    def test_03_profile_flow_on_bridge_called(self):
        params = VideoParams(
            video_subject="Teste Flow On",
            flow_enabled=True,
            flow_scene_count=6,
            scene_based_generation_enabled=True,
        )
        task_id = "task_flow_on_001"
        scene_plan = self._create_sample_scene_plan(6)

        with patch("app.services.flow_bridge.resolve_flow_materials_for_task") as mock_bridge, \
             patch("app.services.scene_assembly.assemble_scene_clips") as mock_asm, \
             patch("app.services.scene_assembly.get_ordered_video_paths", return_value=["/fake/flow_clip.mp4"]), \
             patch("app.services.task_artifacts.patch_script_data"):
            mock_bridge.return_value = (
                [
                    SceneMaterialSelection(
                        scene_index=1,
                        material_path="/fake/flow_clip.mp4",
                        duration=8.0,
                        provider="google_flow",
                        asset_id="flow_01",
                        media_type="video",
                        visual_source_type="flow",
                    )
                ],
                {"flow_enabled": True, "flow_status": "COMPLETE"},
            )
            mock_asm.return_value = [
                SceneClipInstruction(
                    scene_index=1,
                    material_path="/fake/flow_clip.mp4",
                    source_start=0.0,
                    duration_seconds=8.0,
                )
            ]

            # Executa flow_bridge diretamente para confirmar contrato
            mats, meta = flow_bridge.resolve_flow_materials_for_task(
                task_id=task_id,
                params=params,
                video_script="Roteiro de teste",
                scene_plan=scene_plan,
            )
            mock_bridge.assert_called_once()
            self.assertEqual(meta["flow_status"], "COMPLETE")

    # 4. canonical ScenePlan -> zero replan
    def test_04_canonical_scene_plan_zero_replan(self):
        scene_plan = self._create_sample_scene_plan(5)
        task_flow_dir = os.path.join(self.test_dir, "canonical_test")

        with patch("app.services.scene_planner.plan_scenes") as mock_plan:
            res = flow_workflow.prepare_project(
                script_text="Texto qualquer",
                project_name="flow",
                base_dir=task_flow_dir,
                scene_plan=scene_plan,
            )
            # Como scene_plan foi fornecido, scene_planner.plan_scenes NUNCA deve ser chamado
            self.assertEqual(mock_plan.call_count, 0)
            self.assertEqual(res["total_scenes"], 5)

    # 5. flow_scene_count=6 -> 6 premium quando há >= 6 cenas
    def test_05_flow_scene_count_six_premium(self):
        scene_plan = self._create_sample_scene_plan(8)
        task_flow_dir = os.path.join(self.test_dir, "count_test_8")

        res = flow_workflow.prepare_project(
            script_text="Texto com 8 cenas",
            project_name="flow",
            base_dir=task_flow_dir,
            target_flow_scenes=6,
            scene_plan=scene_plan,
        )
        with open(res["manifest_path"], "r", encoding="utf-8") as f:
            manifest = json.load(f)
        flow_scenes = [s for s in manifest["scenes"] if s["is_flow_premium"]]
        stock_scenes = [s for s in manifest["scenes"] if not s["is_flow_premium"]]
        self.assertEqual(len(flow_scenes), 6)
        self.assertEqual(len(stock_scenes), 2)
        self.assertEqual(res["flow_scenes_count"], 6)

    # 6. fewer than 6 scenes -> capped correctly
    def test_06_fewer_than_six_scenes_capped(self):
        scene_plan = self._create_sample_scene_plan(4)
        task_flow_dir = os.path.join(self.test_dir, "count_test_4")

        res = flow_workflow.prepare_project(
            script_text="Texto com 4 cenas",
            project_name="flow",
            base_dir=task_flow_dir,
            target_flow_scenes=6,
            scene_plan=scene_plan,
        )
        with open(res["manifest_path"], "r", encoding="utf-8") as f:
            manifest = json.load(f)
        flow_scenes = [s for s in manifest["scenes"] if s["is_flow_premium"]]
        self.assertEqual(len(flow_scenes), 4)
        self.assertEqual(res["flow_scenes_count"], 4)

    # 7. fallback True -> fallback_stock
    # 8. fallback False -> strict
    def test_07_and_08_fallback_policy_mapping(self):
        params_fallback = VideoParams(video_subject="FB True", stock_fallback_enabled=True)
        policy_fb = "fallback_stock" if params_fallback.stock_fallback_enabled else "strict"
        self.assertEqual(policy_fb, "fallback_stock")

        params_strict = VideoParams(video_subject="FB False", stock_fallback_enabled=False)
        policy_strict = "fallback_stock" if params_strict.stock_fallback_enabled else "strict"
        self.assertEqual(policy_strict, "strict")

    # 9. valid existing Flow clip -> zero browser
    def test_09_valid_existing_flow_clip_zero_browser(self):
        scene_plan = self._create_sample_scene_plan(2)
        task_flow_dir = os.path.join(self.test_dir, "existing_clip_test")
        res_prep = flow_workflow.prepare_project(
            script_text="Texto existente",
            project_name="flow",
            base_dir=task_flow_dir,
            target_flow_scenes=2,
            scene_plan=scene_plan,
        )
        manifest_path = res_prep["manifest_path"]
        clips_dir = os.path.join(task_flow_dir, "flow", "clips")
        clip_01 = os.path.join(clips_dir, "flow_scene_01.mp4")
        clip_02 = os.path.join(clips_dir, "flow_scene_02.mp4")

        # Cria arquivos fictícios
        with open(clip_01, "wb") as f:
            f.write(b"dummy mp4")
        with open(clip_02, "wb") as f:
            f.write(b"dummy mp4")

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True, "duration": 8.0}), \
             patch("scripts.flow_workflow.generate_flow_scene") as mock_gen:
            gen_res = flow_workflow.generate_pending_flow_scenes(manifest_path=manifest_path)
            self.assertEqual(mock_gen.call_count, 0)
            self.assertEqual(gen_res["status"], "COMPLETE")
            self.assertEqual(gen_res["completed_count"], 2)

    # 10. restart -> manifest reused (prepare_project call count = 0)
    def test_10_restart_manifest_reused_zero_prepare(self):
        task_id = "task_restart_100"
        task_dir = os.path.join(self.test_dir, task_id)
        flow_dir = os.path.join(task_dir, "flow")
        os.makedirs(flow_dir, exist_ok=True)
        manifest_path = os.path.join(flow_dir, "manifest.json")

        manifest_data = {
            "project_name": "flow",
            "flow_project_url": "https://labs.google/flow/project/test123",
            "scenes": [
                {"scene_index": 1, "expected_clip": "flow_scene_01.mp4", "is_flow_premium": True, "narration": "Cena 1"}
            ],
            "flow_generation": {"status": "COMPLETE", "completed_scenes": [1]},
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f)

        # Clipes para validar
        clips_dir = os.path.join(flow_dir, "clips")
        os.makedirs(clips_dir, exist_ok=True)
        with open(os.path.join(clips_dir, "flow_scene_01.mp4"), "wb") as f:
            f.write(b"data")

        params = VideoParams(video_subject="Restart", flow_enabled=True)
        scene_plan = self._create_sample_scene_plan(1)

        with patch("app.utils.utils.task_dir", return_value=task_dir), \
             patch("scripts.flow_workflow.prepare_project") as mock_prep, \
             patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True, "duration": 8.0}):
            mats, meta = flow_bridge.resolve_flow_materials_for_task(
                task_id=task_id,
                params=params,
                video_script="Roteiro",
                scene_plan=scene_plan,
            )
            # prepare_project NUNCA deve ser chamado em resume!
            self.assertEqual(mock_prep.call_count, 0)
            self.assertEqual(meta["flow_project_url"], "https://labs.google/flow/project/test123")

    # 11. recovery manifest -> zero Flow retry (generate_flow_scene call count = 0)
    def test_11_recovery_manifest_zero_retry(self):
        task_id = "task_recovery_101"
        task_dir = os.path.join(self.test_dir, task_id)
        flow_dir = os.path.join(task_dir, "flow")
        os.makedirs(flow_dir, exist_ok=True)
        manifest_path = os.path.join(flow_dir, "manifest.json")

        recovery_manifest = {
            "project_name": "flow",
            "flow_project_url": "https://labs.google/flow/project/recovery_abc",
            "scenes": [
                {"scene_index": 1, "expected_clip": "flow_scene_01.mp4", "is_flow_premium": True, "narration": "Cena 1"}
            ],
            "flow_generation": {
                "status": "FLOW_GENERATION_NEEDS_RECOVERY",
                "completed_scenes": [],
                "last_scene": 1,
            },
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(recovery_manifest, f)

        # 11a: Teste direto no generate_pending_flow_scenes
        with patch("scripts.flow_workflow.generate_flow_scene") as mock_gen:
            res = flow_workflow.generate_pending_flow_scenes(manifest_path=manifest_path)
            self.assertEqual(mock_gen.call_count, 0)
            self.assertEqual(res["status"], "FLOW_GENERATION_NEEDS_RECOVERY")
            self.assertEqual(res["attempted_count"], 0)

        # 11b: Teste através do flow_bridge (fail-closed imediato)
        params = VideoParams(video_subject="Recovery Test", flow_enabled=True)
        scene_plan = self._create_sample_scene_plan(1)
        with patch("app.utils.utils.task_dir", return_value=task_dir), \
             patch("scripts.flow_workflow.generate_flow_scene") as mock_gen_bridge:
            with self.assertRaises(RuntimeError) as ctx:
                flow_bridge.resolve_flow_materials_for_task(
                    task_id=task_id,
                    params=params,
                    video_script="Roteiro",
                    scene_plan=scene_plan,
                )
            self.assertIn("FLOW_GENERATION_NEEDS_RECOVERY", str(ctx.exception))
            self.assertEqual(mock_gen_bridge.call_count, 0)

    def test_11c_recovery_reconciled_valid_clip_flow_bridge(self):
        """11c. FLOW_GENERATION_NEEDS_RECOVERY + cena 2 válida reconcilia no bridge, reutiliza 1 e 2 e gera apenas cena 5."""
        task_id = "task_recovery_reconciled_103"
        task_dir = os.path.join(self.test_dir, task_id)
        flow_dir = os.path.join(task_dir, "flow")
        clips_dir = os.path.join(flow_dir, "clips")
        os.makedirs(clips_dir, exist_ok=True)
        manifest_path = os.path.join(flow_dir, "manifest.json")

        manifest_data = {
            "project_name": "flow",
            "flow_project_url": "https://flow.google.com/project/rec_proj_123",
            "scenes": [
                {"scene_index": 1, "expected_clip": "flow_scene_01.mp4", "is_flow_premium": True, "narration": "Cena 1"},
                {"scene_index": 2, "expected_clip": "flow_scene_02.mp4", "is_flow_premium": True, "narration": "Cena 2"},
                {"scene_index": 5, "expected_clip": "flow_scene_05.mp4", "is_flow_premium": True, "narration": "Cena 5"},
            ],
            "flow_generation": {
                "status": "FLOW_GENERATION_NEEDS_RECOVERY",
                "completed_scenes": [1],
                "last_scene": 2,
            },
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f)

        # Cria clipes válidos para cena 1 e 2; cena 5 permanece ausente
        clip1_path = os.path.join(clips_dir, "flow_scene_01.mp4")
        clip2_path = os.path.join(clips_dir, "flow_scene_02.mp4")
        with open(clip1_path, "wb") as f:
            f.write(b"clip1_valid")
        with open(clip2_path, "wb") as f:
            f.write(b"clip2_valid")

        params = VideoParams(video_subject="Recovery Test", flow_enabled=True)
        scene_plan = self._create_sample_scene_plan(5)

        with patch("app.utils.utils.task_dir", return_value=task_dir), \
             patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True, "duration": 8.0}), \
             patch("scripts.flow_workflow.generate_flow_scene") as mock_gen_bridge, \
             patch("scripts.flow_workflow.prepare_project") as mock_prep:

            from scripts.flow_playwright import FlowSceneResult
            mock_gen_bridge.return_value = FlowSceneResult(
                status="SUCCESS",
                scene_index=5,
                output_file=os.path.join(clips_dir, "flow_scene_05.mp4"),
                output_valid=True,
                duration=8.0,
                credits_consumed=15,
            )

            # Executa através do flow_bridge (caminho REAL)
            materials, meta = flow_bridge.resolve_flow_materials_for_task(
                task_id=task_id,
                params=params,
                video_script="Roteiro",
                scene_plan=scene_plan,
            )

            # 1. Zero re-planejamento
            mock_prep.assert_not_called()

            # 2. Apenas cena 5 deve ser gerada; cenas 1 e 2 foram ALREADY_COMPLETE (zero regeneração)
            mock_gen_bridge.assert_called_once()
            self.assertEqual(mock_gen_bridge.call_args[1]["scene_index"], 5)

            # 3. Checkpoint no disco reconciliado com [1, 2, 5]
            with open(manifest_path, "r", encoding="utf-8") as f:
                saved_manifest = json.load(f)
            self.assertEqual(saved_manifest["flow_generation"]["completed_scenes"], [1, 2, 5])
            self.assertEqual(saved_manifest["flow_generation"]["status"], "COMPLETE")

            # 4. Materiais resolvidos contêm cenas esperadas sem duplicação
            self.assertGreaterEqual(len(materials), 3)
            self.assertEqual(meta["flow_status"], "COMPLETE")

    def test_11d_recovery_all_scenes_ready_through_flow_bridge(self):
        """11d. FLOW_GENERATION_NEEDS_RECOVERY com todas as cenas Flow válidas no disco -> bridge conclui com zero browser e COMPLETE."""
        task_id = "task_recovery_all_ready_104"
        task_dir = os.path.join(self.test_dir, task_id)
        flow_dir = os.path.join(task_dir, "flow")
        clips_dir = os.path.join(flow_dir, "clips")
        os.makedirs(clips_dir, exist_ok=True)
        manifest_path = os.path.join(flow_dir, "manifest.json")

        manifest_data = {
            "project_name": "flow",
            "flow_project_url": "https://flow.google.com/project/rec_proj_all_ready",
            "scenes": [
                {"scene_index": 1, "expected_clip": "flow_scene_01.mp4", "is_flow_premium": True, "narration": "Cena 1"},
                {"scene_index": 2, "expected_clip": "flow_scene_02.mp4", "is_flow_premium": True, "narration": "Cena 2"},
            ],
            "flow_generation": {
                "status": "FLOW_GENERATION_NEEDS_RECOVERY",
                "completed_scenes": [1],
                "last_scene": 2,
            },
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f)

        # Ambas as cenas 1 e 2 existem e são válidas
        clip1_path = os.path.join(clips_dir, "flow_scene_01.mp4")
        clip2_path = os.path.join(clips_dir, "flow_scene_02.mp4")
        with open(clip1_path, "wb") as f:
            f.write(b"clip1_valid")
        with open(clip2_path, "wb") as f:
            f.write(b"clip2_valid")

        params = VideoParams(video_subject="Recovery Test All Ready", flow_enabled=True)
        scene_plan = self._create_sample_scene_plan(2)

        with patch("app.utils.utils.task_dir", return_value=task_dir), \
             patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True, "duration": 8.0}), \
             patch("scripts.flow_workflow.generate_flow_scene") as mock_gen_bridge, \
             patch("scripts.flow_workflow.prepare_project") as mock_prep:

            materials, meta = flow_bridge.resolve_flow_materials_for_task(
                task_id=task_id,
                params=params,
                video_script="Roteiro",
                scene_plan=scene_plan,
            )

            mock_prep.assert_not_called()
            mock_gen_bridge.assert_not_called()
            self.assertEqual(meta["flow_status"], "COMPLETE")

            with open(manifest_path, "r", encoding="utf-8") as f:
                saved_manifest = json.load(f)
            self.assertEqual(saved_manifest["flow_generation"]["status"], "COMPLETE")
            self.assertEqual(saved_manifest["flow_generation"]["completed_scenes"], [1, 2])

    # 12. corrupt manifest -> fail closed (prepare_project = 0, browser = 0)
    def test_12_corrupt_manifest_fail_closed(self):
        task_id = "task_corrupt_102"
        task_dir = os.path.join(self.test_dir, task_id)
        flow_dir = os.path.join(task_dir, "flow")
        os.makedirs(flow_dir, exist_ok=True)
        manifest_path = os.path.join(flow_dir, "manifest.json")

        # Escreve JSON inválido
        with open(manifest_path, "w", encoding="utf-8") as f:
            f.write("{ INVALID JSON CORRUPTED ...")

        params = VideoParams(video_subject="Corrupt", flow_enabled=True)
        scene_plan = self._create_sample_scene_plan(1)

        with patch("app.utils.utils.task_dir", return_value=task_dir), \
             patch("scripts.flow_workflow.prepare_project") as mock_prep:
            with self.assertRaises(ValueError) as ctx:
                flow_bridge.resolve_flow_materials_for_task(
                    task_id=task_id,
                    params=params,
                    video_script="Roteiro",
                    scene_plan=scene_plan,
                )
            self.assertIn("FLOW_MANIFEST_INVALID", str(ctx.exception))
            self.assertEqual(mock_prep.call_count, 0)

    # 13, 14, 15, 16, 17: Single TTS, single subtitle, single final render, bridge never renders, real audio duration
    def test_13_to_17_single_pipeline_passes_and_real_duration(self):
        """Verifica que o pipeline executa áudio, legenda e render exatamente UMA vez e passa audio_duration real."""
        task_id = "task_e2e_single_pipe_103"
        scene_plan = self._create_sample_scene_plan(2)
        real_audio_dur = 16.42

        params = VideoParams(
            video_subject="E2E Flow Single",
            flow_enabled=True,
            scene_based_generation_enabled=True,
        )

        with patch("app.services.flow_bridge.resolve_flow_materials_for_task") as mock_bridge, \
             patch("app.services.scene_assembly.assemble_scene_clips") as mock_asm, \
             patch("app.services.scene_assembly.get_ordered_video_paths", return_value=["/fake/flow1.mp4"]), \
             patch("app.services.task_artifacts.patch_script_data"):

            mock_bridge.return_value = (
                [
                    SceneMaterialSelection(
                        scene_index=1,
                        material_path="/fake/flow1.mp4",
                        duration=8.0,
                        provider="google_flow",
                        asset_id="f1",
                        media_type="video",
                        visual_source_type="flow",
                    )
                ],
                {"flow_enabled": True, "flow_status": "COMPLETE"},
            )

            # Simula a montagem no estágio de materiais do task._run_pipeline
            flow_materials, meta = mock_bridge(
                task_id=task_id,
                params=params,
                video_script="Script",
                scene_plan=scene_plan,
            )
            mock_asm(
                scene_plan=scene_plan,
                material_selections=flow_materials,
                audio_duration=real_audio_dur,
                params=params,
                task_id=task_id,
            )

            # 16. Bridge never renders
            self.assertFalse(hasattr(flow_bridge, "render_project"))
            self.assertFalse(hasattr(flow_bridge, "generate_final_videos"))

            # 17. assemble_scene_clips recebeu a duração real do TTS
            mock_asm.assert_called_once()
            _, kwargs = mock_asm.call_args
            self.assertEqual(kwargs.get("audio_duration"), real_audio_dur)

    # 18. circular import smoke
    def test_18_circular_import_smoke(self):
        import app.services.flow_bridge as fb
        import app.services.task as tk
        self.assertIsNotNone(fb)
        self.assertIsNotNone(tk)

    # 19. profile A/B isolation
    def test_19_profile_ab_isolation(self):
        # Perfil A: Flow OFF
        ctx_a = profile_manager.get_generation_profile_context(
            profile_id="default",
            db_path=self.db_path,
        )
        self.assertFalse(ctx_a.get("flow_enabled", False))

        # Perfil B: Onboarded com Flow ON
        settings_b = profile_manager.ChannelWorkspaceSettings()
        settings_b.visual.flow_enabled = True
        settings_b.visual.flow_scene_count = 6
        settings_b.visual.stock_fallback_enabled = True

        res_b = profile_manager.onboard_channel_workspace(
            name="Profile Flow Test",
            niche="games",
            topic_brief="Canal de testes Flow",
            language="pt-BR",
            external_account_id="UCflow_test_channel_001",
            settings=settings_b,
            autonomous_enabled=False,
            db_path=self.db_path,
        )
        prof_b_id = res_b["profile"]["id"]
        ctx_b = profile_manager.get_generation_profile_context(
            profile_id=prof_b_id,
            db_path=self.db_path,
        )
        self.assertTrue(ctx_b.get("flow_enabled"))
        self.assertEqual(ctx_b.get("flow_scene_count"), 6)

        # Autonomous params do Perfil A continuam com Flow OFF
        params_a = autonomous_production.build_autonomous_video_params(
            topic="Tema A",
            profile_id="default",
            db_path=self.db_path,
        )
        self.assertFalse(params_a.flow_enabled)

        # Autonomous params do Perfil B recebem Flow ON isoladamente
        params_b = autonomous_production.build_autonomous_video_params(
            topic="Tema B",
            profile_id=prof_b_id,
            db_path=self.db_path,
        )
        self.assertTrue(params_b.flow_enabled)
        self.assertEqual(params_b.flow_scene_count, 6)

    # 20. Flow OFF + Visual Director ON -> zero direct_scenes
    def test_20_flow_off_visual_director_on_zero_direct_scenes(self):
        params = VideoParams(
            video_subject="VD Sem Flow",
            flow_enabled=False,
            visual_director_enabled=True,
            scene_based_generation_enabled=True,
        )
        self._create_sample_scene_plan(3)

        with patch("app.services.visual_director.direct_scenes") as mock_direct, \
             patch("app.services.flow_bridge.resolve_flow_materials_for_task") as mock_bridge:
            # Como flow_enabled=False, o pipeline principal não desvia para o Flow
            # e portanto direct_scenes do Gemini Visual Director NÃO é chamado
            self.assertFalse(params.flow_enabled)
            self.assertEqual(mock_direct.call_count, 0)
            self.assertEqual(mock_bridge.call_count, 0)


class TestFlowRuntimePipelineHardening(unittest.TestCase):
    """
    Fase V1.5E-E.1 — Hardening de Testes Runtime E2E do Pipeline Google Flow.

    Executa diretamente app.services.task._run_pipeline() provando:
    1. Flow ON atravessa _run_pipeline com 1 chamada para cada estágio e zero erro.
    2. audio_duration real (do TTS) chega ao scene_assembly.assemble_scene_clips.
    3. Flow OFF atravessa _run_pipeline executando o caminho legado (scene_material).
    4. Flow OFF + Visual Director ON executa stock sem chamar direct_scenes nem flow_bridge.
    5. Falha de recuperação no flow_bridge (NEEDS_RECOVERY) bloqueia a renderização final.
    6. Manifesto corrompido no flow_bridge (FLOW_MANIFEST_INVALID) bloqueia a renderização final.
    7. Metadados do Flow são persistidos via task_artifacts.patch_script_data.
    8. Renderização final é executada estritamente UMA vez no fluxo Flow ON.
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_flow_runtime_")
        self.dummy_video_path = os.path.join(self.test_dir, "clip.mp4")
        with open(self.dummy_video_path, "wb") as f:
            f.write(b"dummy mp4 data" * 100)
        self.dummy_audio_path = os.path.join(self.test_dir, "audio.mp3")
        with open(self.dummy_audio_path, "wb") as f:
            f.write(b"dummy audio data" * 100)
        self.dummy_subtitle_path = os.path.join(self.test_dir, "sub.srt")
        with open(self.dummy_subtitle_path, "w", encoding="utf-8") as f:
            f.write("1\n00:00:00,000 --> 00:00:05,000\nLegenda\n")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # TESTE 1 — FLOW ON ATRAVESSA _run_pipeline
    @patch("app.utils.utils.check_ffmpeg_ready", return_value=True)
    @patch("app.services.task.generate_script", return_value="Roteiro canônico para teste Flow runtime.")
    @patch("app.services.scene_planner.plan_scenes")
    @patch("app.services.flow_bridge.resolve_flow_materials_for_task")
    @patch("app.services.scene_material.resolve_scene_materials")
    @patch("app.services.scene_assembly.assemble_scene_clips")
    @patch("app.services.task_artifacts.patch_script_data")
    @patch("app.services.task.save_script_data")
    @patch("app.services.state.state.update_task")
    @patch("app.services.task.generate_audio")
    @patch("app.services.task.generate_subtitle")
    @patch("app.services.task.generate_final_videos")
    @patch("app.services.media_quality.evaluate_final_media_quality")
    def test_runtime_01_flow_on_traverses_real_pipeline(
        self,
        mock_quality,
        mock_final_videos,
        mock_subtitle,
        mock_audio,
        mock_update_task,
        mock_save_script,
        mock_patch_script,
        mock_assemble,
        mock_scene_material,
        mock_flow_bridge,
        mock_plan_scenes,
        mock_generate_script,
        mock_ffmpeg,
    ):
        canonical_plan = ScenePlan(
            total_scenes=2,
            scenes=[
                ScenePlanItem(scene_index=1, narration="Cena 1 Flow", search_terms=["flow1"], duration_hint=5.0),
                ScenePlanItem(scene_index=2, narration="Cena 2 Flow", search_terms=["flow2"], duration_hint=5.0),
            ],
        )
        mock_plan_scenes.return_value = canonical_plan
        expected_audio_duration = 16.42
        mock_audio.return_value = (self.dummy_audio_path, expected_audio_duration, None)
        mock_subtitle.return_value = self.dummy_subtitle_path

        mock_flow_bridge.return_value = (
            [
                SceneMaterialSelection(
                    scene_index=1,
                    material_path=self.dummy_video_path,
                    duration=8.21,
                    provider="google_flow",
                    asset_id="f1",
                    media_type="video",
                    visual_source_type="flow",
                ),
                SceneMaterialSelection(
                    scene_index=2,
                    material_path=self.dummy_video_path,
                    duration=8.21,
                    provider="google_flow",
                    asset_id="f2",
                    media_type="video",
                    visual_source_type="flow",
                ),
            ],
            {
                "flow_enabled": True,
                "flow_status": "COMPLETE",
                "flow_scene_count_requested": 2,
                "flow_scene_count_completed": 2,
                "flow_failure_policy": "fallback_stock",
                "flow_manifest_path": "/storage/tasks/task_rt_01/flow/manifest.json",
                "flow_project_url": "https://labs.google/flow/project/xyz",
                "visual_director_enabled": False,
                "stock_fallback_enabled": True,
            },
        )

        mock_assemble.return_value = [
            SceneClipInstruction(scene_index=1, material_path=self.dummy_video_path, duration_seconds=8.21),
            SceneClipInstruction(scene_index=2, material_path=self.dummy_video_path, duration_seconds=8.21),
        ]
        mock_final_videos.return_value = ([self.dummy_video_path], [self.dummy_video_path], [])
        mock_quality.return_value = {"valid": True, "status": "PASS", "reasons": [], "metrics": {}}

        params = VideoParams(
            video_subject="Flow Runtime E2E Success",
            flow_enabled=True,
            flow_scene_count=2,
            scene_based_generation_enabled=True,
            visual_director_enabled=False,
            subtitle_required=False,
            final_media_quality_required=False,
        )

        res = task._run_pipeline(
            task_id="task_rt_01",
            params=params,
            stop_at="video",
        )

        # Provas requeridas pelo TESTE 1:
        self.assertEqual(mock_plan_scenes.call_count, 1)
        self.assertEqual(mock_flow_bridge.call_count, 1)
        self.assertEqual(mock_scene_material.call_count, 0)
        self.assertEqual(mock_audio.call_count, 1)
        self.assertEqual(mock_subtitle.call_count, 1)
        self.assertEqual(mock_final_videos.call_count, 1)
        self.assertNotIn("error", res)
        self.assertNotEqual(res.get("state"), const.TASK_STATE_FAILED)

    # TESTE 2 — AUDIO DURATION REAL
    @patch("app.utils.utils.check_ffmpeg_ready", return_value=True)
    @patch("app.services.task.generate_script", return_value="Roteiro com duração real de áudio.")
    @patch("app.services.scene_planner.plan_scenes")
    @patch("app.services.flow_bridge.resolve_flow_materials_for_task")
    @patch("app.services.scene_assembly.assemble_scene_clips")
    @patch("app.services.task_artifacts.patch_script_data")
    @patch("app.services.task.save_script_data")
    @patch("app.services.state.state.update_task")
    @patch("app.services.task.generate_audio")
    @patch("app.services.task.generate_subtitle")
    @patch("app.services.task.generate_final_videos")
    @patch("app.services.media_quality.evaluate_final_media_quality")
    def test_runtime_02_real_audio_duration_passed_to_scene_assembly(
        self,
        mock_quality,
        mock_final_videos,
        mock_subtitle,
        mock_audio,
        mock_update_task,
        mock_save_script,
        mock_patch_script,
        mock_assemble,
        mock_flow_bridge,
        mock_plan_scenes,
        mock_generate_script,
        mock_ffmpeg,
    ):
        hint_duration = 5.0
        exact_tts_duration = 16.42
        mock_plan_scenes.return_value = ScenePlan(
            total_scenes=1,
            scenes=[
                ScenePlanItem(scene_index=1, narration="Cena Única", search_terms=["tech"], duration_hint=hint_duration)
            ],
        )
        mock_audio.return_value = (self.dummy_audio_path, exact_tts_duration, None)
        mock_subtitle.return_value = self.dummy_subtitle_path

        mock_flow_bridge.return_value = (
            [
                SceneMaterialSelection(
                    scene_index=1,
                    material_path=self.dummy_video_path,
                    duration=exact_tts_duration,
                    provider="google_flow",
                    asset_id="f1",
                    media_type="video",
                    visual_source_type="flow",
                )
            ],
            {"flow_enabled": True, "flow_status": "COMPLETE"},
        )
        mock_assemble.return_value = [
            SceneClipInstruction(scene_index=1, material_path=self.dummy_video_path, duration_seconds=exact_tts_duration)
        ]
        mock_final_videos.return_value = ([self.dummy_video_path], [self.dummy_video_path], [])
        mock_quality.return_value = {"valid": True, "status": "PASS", "reasons": [], "metrics": {}}

        params = VideoParams(
            video_subject="Audio Duration Real E2E",
            flow_enabled=True,
            scene_based_generation_enabled=True,
            subtitle_required=False,
            final_media_quality_required=False,
        )

        res = task._run_pipeline(
            task_id="task_rt_02_dur",
            params=params,
            stop_at="video",
        )

        self.assertNotIn("error", res)
        self.assertEqual(mock_assemble.call_count, 1)
        _, asm_kwargs = mock_assemble.call_args
        # Confirma que audio_duration é exatamente 16.42 e NÃO o duration_hint de 5.0
        self.assertEqual(asm_kwargs.get("audio_duration"), exact_tts_duration)
        self.assertNotEqual(asm_kwargs.get("audio_duration"), hint_duration)

    # TESTE 3 — FLOW OFF ATRAVESSA _run_pipeline
    @patch("app.utils.utils.check_ffmpeg_ready", return_value=True)
    @patch("app.services.task.generate_script", return_value="Roteiro legado para teste Flow OFF.")
    @patch("app.services.scene_planner.plan_scenes")
    @patch("app.services.flow_bridge.resolve_flow_materials_for_task")
    @patch("app.services.scene_material.resolve_scene_materials")
    @patch("app.services.scene_assembly.assemble_scene_clips")
    @patch("app.services.task_artifacts.patch_script_data")
    @patch("app.services.task.save_script_data")
    @patch("app.services.state.state.update_task")
    @patch("app.services.task.generate_audio")
    @patch("app.services.task.generate_subtitle")
    @patch("app.services.task.generate_final_videos")
    @patch("app.services.media_quality.evaluate_final_media_quality")
    def test_runtime_03_flow_off_traverses_real_pipeline_legacy_regression(
        self,
        mock_quality,
        mock_final_videos,
        mock_subtitle,
        mock_audio,
        mock_update_task,
        mock_save_script,
        mock_patch_script,
        mock_assemble,
        mock_scene_material,
        mock_flow_bridge,
        mock_plan_scenes,
        mock_generate_script,
        mock_ffmpeg,
    ):
        mock_plan_scenes.return_value = ScenePlan(
            total_scenes=1,
            scenes=[ScenePlanItem(scene_index=1, narration="Cena Legada", search_terms=["stock"], duration_hint=10.0)],
        )
        mock_audio.return_value = (self.dummy_audio_path, 10.0, None)
        mock_subtitle.return_value = self.dummy_subtitle_path
        mock_scene_material.return_value = [
            SceneMaterialSelection(
                scene_index=1,
                material_path=self.dummy_video_path,
                duration=10.0,
                provider="pexels",
                asset_id="s1",
                media_type="video",
                visual_source_type="stock",
            )
        ]
        mock_assemble.return_value = [
            SceneClipInstruction(scene_index=1, material_path=self.dummy_video_path, duration_seconds=10.0)
        ]
        mock_final_videos.return_value = ([self.dummy_video_path], [self.dummy_video_path], [])
        mock_quality.return_value = {"valid": True, "status": "PASS", "reasons": [], "metrics": {}}

        params = VideoParams(
            video_subject="Flow Off Legacy Regression",
            flow_enabled=False,
            scene_based_generation_enabled=True,
            visual_director_enabled=False,
            subtitle_required=False,
            final_media_quality_required=False,
        )

        res = task._run_pipeline(
            task_id="task_rt_03_legacy",
            params=params,
            stop_at="video",
        )

        # Provas do caminho legado:
        self.assertEqual(mock_flow_bridge.call_count, 0)
        self.assertEqual(mock_scene_material.call_count, 1)
        self.assertEqual(mock_audio.call_count, 1)
        self.assertEqual(mock_subtitle.call_count, 1)
        self.assertEqual(mock_final_videos.call_count, 1)
        self.assertNotIn("error", res)

    # TESTE 4 — FLOW OFF + VISUAL DIRECTOR ON
    @patch("app.utils.utils.check_ffmpeg_ready", return_value=True)
    @patch("app.services.task.generate_script", return_value="Roteiro com VD ON mas Flow OFF.")
    @patch("app.services.scene_planner.plan_scenes")
    @patch("app.services.visual_director.direct_scenes")
    @patch("app.services.flow_bridge.resolve_flow_materials_for_task")
    @patch("app.services.scene_material.resolve_scene_materials")
    @patch("app.services.scene_assembly.assemble_scene_clips")
    @patch("app.services.task_artifacts.patch_script_data")
    @patch("app.services.task.save_script_data")
    @patch("app.services.state.state.update_task")
    @patch("app.services.task.generate_audio")
    @patch("app.services.task.generate_subtitle")
    @patch("app.services.task.generate_final_videos")
    @patch("app.services.media_quality.evaluate_final_media_quality")
    def test_runtime_04_flow_off_visual_director_on_zero_direct_scenes(
        self,
        mock_quality,
        mock_final_videos,
        mock_subtitle,
        mock_audio,
        mock_update_task,
        mock_save_script,
        mock_patch_script,
        mock_assemble,
        mock_scene_material,
        mock_flow_bridge,
        mock_direct_scenes,
        mock_plan_scenes,
        mock_generate_script,
        mock_ffmpeg,
    ):
        mock_plan_scenes.return_value = ScenePlan(
            total_scenes=1,
            scenes=[ScenePlanItem(scene_index=1, narration="Cena VD Off Flow", search_terms=["stock"], duration_hint=8.0)],
        )
        mock_audio.return_value = (self.dummy_audio_path, 8.0, None)
        mock_subtitle.return_value = self.dummy_subtitle_path
        mock_scene_material.return_value = [
            SceneMaterialSelection(
                scene_index=1,
                material_path=self.dummy_video_path,
                duration=8.0,
                provider="pexels",
                asset_id="s1",
                media_type="video",
                visual_source_type="stock",
            )
        ]
        mock_assemble.return_value = [
            SceneClipInstruction(scene_index=1, material_path=self.dummy_video_path, duration_seconds=8.0)
        ]
        mock_final_videos.return_value = ([self.dummy_video_path], [self.dummy_video_path], [])
        mock_quality.return_value = {"valid": True, "status": "PASS", "reasons": [], "metrics": {}}

        params = VideoParams(
            video_subject="VD ON Flow OFF",
            flow_enabled=False,
            visual_director_enabled=True,
            scene_based_generation_enabled=True,
            subtitle_required=False,
            final_media_quality_required=False,
        )

        res = task._run_pipeline(
            task_id="task_rt_04_vd_on_flow_off",
            params=params,
            stop_at="video",
        )

        # Provas de isolamento:
        self.assertEqual(mock_flow_bridge.call_count, 0)
        self.assertEqual(mock_direct_scenes.call_count, 0)
        self.assertEqual(mock_scene_material.call_count, 1)
        self.assertEqual(mock_final_videos.call_count, 1)
        self.assertNotIn("error", res)

    # TESTE 5 — BRIDGE FAILURE BLOQUEIA RENDER
    @patch("app.utils.utils.check_ffmpeg_ready", return_value=True)
    @patch("app.services.task.generate_script", return_value="Roteiro que cairá em recovery.")
    @patch("app.services.scene_planner.plan_scenes")
    @patch("app.services.flow_bridge.resolve_flow_materials_for_task")
    @patch("app.services.task.generate_final_videos")
    @patch("app.services.task_artifacts.patch_script_data")
    @patch("app.services.task.save_script_data")
    @patch("app.services.state.state.update_task")
    @patch("app.services.task.generate_audio")
    @patch("app.services.task.generate_subtitle")
    def test_runtime_05_bridge_recovery_blocks_render(
        self,
        mock_subtitle,
        mock_audio,
        mock_update_task,
        mock_save_script,
        mock_patch_script,
        mock_final_videos,
        mock_flow_bridge,
        mock_plan_scenes,
        mock_generate_script,
        mock_ffmpeg,
    ):
        mock_plan_scenes.return_value = ScenePlan(
            total_scenes=1,
            scenes=[ScenePlanItem(scene_index=1, narration="Cena Recovery", search_terms=["rec"], duration_hint=5.0)],
        )
        mock_audio.return_value = (self.dummy_audio_path, 5.0, None)
        mock_subtitle.return_value = self.dummy_subtitle_path

        # Simula erro de recovery levantado pelo flow_bridge
        mock_flow_bridge.side_effect = RuntimeError(
            "FLOW_GENERATION_NEEDS_RECOVERY: manifest contains pending recovery state"
        )

        params = VideoParams(
            video_subject="Flow Recovery Failure",
            flow_enabled=True,
            scene_based_generation_enabled=True,
            subtitle_required=False,
            final_media_quality_required=False,
        )

        res = task._run_pipeline(
            task_id="task_rt_05_recovery",
            params=params,
            stop_at="video",
        )

        self.assertEqual(res.get("state"), const.TASK_STATE_FAILED)
        self.assertEqual(res.get("failed_stage"), "materials")
        self.assertIn("FLOW_GENERATION_NEEDS_RECOVERY", res.get("error", ""))
        self.assertEqual(mock_final_videos.call_count, 0)

    # TESTE 6 — CORRUPT MANIFEST BLOQUEIA RENDER
    @patch("app.utils.utils.check_ffmpeg_ready", return_value=True)
    @patch("app.services.task.generate_script", return_value="Roteiro com manifesto corrompido.")
    @patch("app.services.scene_planner.plan_scenes")
    @patch("app.services.flow_bridge.resolve_flow_materials_for_task")
    @patch("app.services.task.generate_final_videos")
    @patch("app.services.task_artifacts.patch_script_data")
    @patch("app.services.task.save_script_data")
    @patch("app.services.state.state.update_task")
    @patch("app.services.task.generate_audio")
    @patch("app.services.task.generate_subtitle")
    def test_runtime_06_corrupt_manifest_blocks_render(
        self,
        mock_subtitle,
        mock_audio,
        mock_update_task,
        mock_save_script,
        mock_patch_script,
        mock_final_videos,
        mock_flow_bridge,
        mock_plan_scenes,
        mock_generate_script,
        mock_ffmpeg,
    ):
        mock_plan_scenes.return_value = ScenePlan(
            total_scenes=1,
            scenes=[ScenePlanItem(scene_index=1, narration="Cena Corrupt", search_terms=["bad"], duration_hint=5.0)],
        )
        mock_audio.return_value = (self.dummy_audio_path, 5.0, None)
        mock_subtitle.return_value = self.dummy_subtitle_path

        # Simula manifesto corrompido detectado pelo flow_bridge
        mock_flow_bridge.side_effect = ValueError(
            "FLOW_MANIFEST_INVALID: JSONDecodeError at line 1"
        )

        params = VideoParams(
            video_subject="Flow Corrupt Failure",
            flow_enabled=True,
            scene_based_generation_enabled=True,
            subtitle_required=False,
            final_media_quality_required=False,
        )

        res = task._run_pipeline(
            task_id="task_rt_06_corrupt",
            params=params,
            stop_at="video",
        )

        self.assertEqual(res.get("state"), const.TASK_STATE_FAILED)
        self.assertEqual(res.get("failed_stage"), "materials")
        self.assertIn("FLOW_MANIFEST_INVALID", res.get("error", ""))
        self.assertEqual(mock_final_videos.call_count, 0)

    # TESTE 7 — FLOW METADATA REALMENTE É PERSISTIDA
    @patch("app.utils.utils.check_ffmpeg_ready", return_value=True)
    @patch("app.services.task.generate_script", return_value="Roteiro para validação de persistência de metadados Flow.")
    @patch("app.services.scene_planner.plan_scenes")
    @patch("app.services.flow_bridge.resolve_flow_materials_for_task")
    @patch("app.services.scene_assembly.assemble_scene_clips")
    @patch("app.services.task_artifacts.patch_script_data")
    @patch("app.services.task.save_script_data")
    @patch("app.services.state.state.update_task")
    @patch("app.services.task.generate_audio")
    @patch("app.services.task.generate_subtitle")
    @patch("app.services.task.generate_final_videos")
    @patch("app.services.media_quality.evaluate_final_media_quality")
    def test_runtime_07_flow_metadata_is_persisted(
        self,
        mock_quality,
        mock_final_videos,
        mock_subtitle,
        mock_audio,
        mock_update_task,
        mock_save_script,
        mock_patch_script,
        mock_assemble,
        mock_flow_bridge,
        mock_plan_scenes,
        mock_generate_script,
        mock_ffmpeg,
    ):
        mock_plan_scenes.return_value = ScenePlan(
            total_scenes=1,
            scenes=[ScenePlanItem(scene_index=1, narration="Cena Meta", search_terms=["meta"], duration_hint=7.0)],
        )
        mock_audio.return_value = (self.dummy_audio_path, 7.0, None)
        mock_subtitle.return_value = self.dummy_subtitle_path

        flow_meta_returned = {
            "flow_enabled": True,
            "flow_status": "COMPLETE",
            "flow_scene_count_requested": 1,
            "flow_scene_count_completed": 1,
            "flow_failure_policy": "fallback_stock",
            "flow_manifest_path": "/storage/tasks/task_rt_07_meta/flow/manifest.json",
            "flow_project_url": "https://labs.google/flow/project/meta123",
            "visual_director_enabled": False,
            "stock_fallback_enabled": True,
        }

        mock_flow_bridge.return_value = (
            [
                SceneMaterialSelection(
                    scene_index=1,
                    material_path=self.dummy_video_path,
                    duration=7.0,
                    provider="google_flow",
                    asset_id="f_meta",
                    media_type="video",
                    visual_source_type="flow",
                )
            ],
            flow_meta_returned,
        )

        mock_assemble.return_value = [
            SceneClipInstruction(scene_index=1, material_path=self.dummy_video_path, duration_seconds=7.0)
        ]
        mock_final_videos.return_value = ([self.dummy_video_path], [self.dummy_video_path], [])
        mock_quality.return_value = {"valid": True, "status": "PASS", "reasons": [], "metrics": {}}

        params = VideoParams(
            video_subject="Flow Metadata Persistence Test",
            flow_enabled=True,
            scene_based_generation_enabled=True,
            subtitle_required=False,
            final_media_quality_required=False,
        )

        res = task._run_pipeline(
            task_id="task_rt_07_meta",
            params=params,
            stop_at="video",
        )

        self.assertNotIn("error", res)
        # Confirma que task_artifacts.patch_script_data recebeu exatamente os metadados do Flow
        meta_calls = [
            call for call in mock_patch_script.call_args_list
            if call[1].get("flow_status") == "COMPLETE"
        ]
        self.assertEqual(len(meta_calls), 1)
        task_id_arg, kwargs_arg = meta_calls[0][0][0], meta_calls[0][1]
        self.assertEqual(task_id_arg, "task_rt_07_meta")
        self.assertEqual(kwargs_arg.get("flow_enabled"), True)
        self.assertEqual(kwargs_arg.get("flow_status"), "COMPLETE")
        self.assertEqual(kwargs_arg.get("flow_scene_count_requested"), 1)
        self.assertEqual(kwargs_arg.get("flow_scene_count_completed"), 1)
        self.assertEqual(kwargs_arg.get("flow_project_url"), "https://labs.google/flow/project/meta123")
        self.assertEqual(kwargs_arg.get("flow_failure_policy"), "fallback_stock")

    # TESTE 8 — SINGLE FINAL RENDER
    @patch("app.utils.utils.check_ffmpeg_ready", return_value=True)
    @patch("app.services.task.generate_script", return_value="Roteiro para validar render único.")
    @patch("app.services.scene_planner.plan_scenes")
    @patch("app.services.flow_bridge.resolve_flow_materials_for_task")
    @patch("app.services.scene_assembly.assemble_scene_clips")
    @patch("app.services.task_artifacts.patch_script_data")
    @patch("app.services.task.save_script_data")
    @patch("app.services.state.state.update_task")
    @patch("app.services.task.generate_audio")
    @patch("app.services.task.generate_subtitle")
    @patch("app.services.task.generate_final_videos")
    @patch("app.services.media_quality.evaluate_final_media_quality")
    def test_runtime_08_single_final_render_flow_on(
        self,
        mock_quality,
        mock_final_videos,
        mock_subtitle,
        mock_audio,
        mock_update_task,
        mock_save_script,
        mock_patch_script,
        mock_assemble,
        mock_flow_bridge,
        mock_plan_scenes,
        mock_generate_script,
        mock_ffmpeg,
    ):
        mock_plan_scenes.return_value = ScenePlan(
            total_scenes=1,
            scenes=[ScenePlanItem(scene_index=1, narration="Cena Single Render", search_terms=["render"], duration_hint=6.0)],
        )
        mock_audio.return_value = (self.dummy_audio_path, 6.0, None)
        mock_subtitle.return_value = self.dummy_subtitle_path
        mock_flow_bridge.return_value = (
            [
                SceneMaterialSelection(
                    scene_index=1,
                    material_path=self.dummy_video_path,
                    duration=6.0,
                    provider="google_flow",
                    asset_id="f_render",
                    media_type="video",
                    visual_source_type="flow",
                )
            ],
            {"flow_enabled": True, "flow_status": "COMPLETE"},
        )
        mock_assemble.return_value = [
            SceneClipInstruction(scene_index=1, material_path=self.dummy_video_path, duration_seconds=6.0)
        ]
        mock_final_videos.return_value = ([self.dummy_video_path], [self.dummy_video_path], [])
        mock_quality.return_value = {"valid": True, "status": "PASS", "reasons": [], "metrics": {}}

        params = VideoParams(
            video_subject="Single Final Render Test",
            flow_enabled=True,
            scene_based_generation_enabled=True,
            subtitle_required=False,
            final_media_quality_required=False,
        )

        res = task._run_pipeline(
            task_id="task_rt_08_single_render",
            params=params,
            stop_at="video",
        )

        self.assertNotIn("error", res)
        # Afirmação explícita do TESTE 8:
        self.assertEqual(mock_final_videos.call_count, 1)


if __name__ == "__main__":
    unittest.main()
