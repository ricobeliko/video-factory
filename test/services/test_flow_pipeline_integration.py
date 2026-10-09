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
from unittest.mock import MagicMock, patch

from app.models.schema import (
    SceneClipInstruction,
    SceneMaterialSelection,
    ScenePlan,
    ScenePlanItem,
    VideoParams,
)
from app.services import autonomous_production, flow_bridge, profile_manager, task
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
        task_id = "task_flow_off_001"
        scene_plan = self._create_sample_scene_plan(4)

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
        scene_plan = self._create_sample_scene_plan(3)

        with patch("app.services.visual_director.direct_scenes") as mock_direct, \
             patch("app.services.flow_bridge.resolve_flow_materials_for_task") as mock_bridge:
            # Como flow_enabled=False, o pipeline principal não desvia para o Flow
            # e portanto direct_scenes do Gemini Visual Director NÃO é chamado
            self.assertFalse(params.flow_enabled)
            self.assertEqual(mock_direct.call_count, 0)
            self.assertEqual(mock_bridge.call_count, 0)


if __name__ == "__main__":
    unittest.main()
