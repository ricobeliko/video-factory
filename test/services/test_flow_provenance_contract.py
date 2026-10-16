"""
test/services/test_flow_provenance_contract.py
==============================================
Regressões estritas para o contrato de proveniência do Google Flow (V1.5E-G8).

Cobre requisitos A até I:
A. ramo Flow persiste scene_materials/material_sources
B. Google Flow válido → provenance PASS (GENERATED_FLOW_PROVENANCE_VERIFIED)
C. Flow sem manifest → FAIL
D. Flow scene não completed → FAIL
E. arquivo Flow fora da task → FAIL
F. arquivo Flow inexistente → FAIL
G. local_cache sem origem comprovada → FAIL
H. pexels/pixabay/coverr continuam PASS
I. ambient_auto SAFE_PROCEDURAL continua PASS

Follow-up pós-review PR #90:
J. exceção em validate_clip_file → gate FAIL (fail-closed)
K. basename(local_file) != expected_clip (mesmo scene_index) → gate FAIL
L. autônomo: cache/clip local sem proveniência ignorado; resolver stock canônico usado
M. autônomo: falha de persistência → FLOW_PROVENANCE_PERSIST_FAILED antes do render
N. autônomo: patch_script_data sem persistir (False) → FLOW_PROVENANCE_PERSIST_FAILED
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from app.models.schema import SceneMaterialSelection, ScenePlan, ScenePlanItem, VideoParams
from app.services import copyright_gate, flow_bridge, task_artifacts


class TestFlowProvenanceContract(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_flow_prov_")
        self.task_id = "test_flow_prov_task_001"
        self.task_dir = os.path.join(self.test_dir, self.task_id)
        os.makedirs(self.task_dir, exist_ok=True)
        self.flow_dir = os.path.join(self.task_dir, "flow")
        self.clips_dir = os.path.join(self.flow_dir, "clips")
        os.makedirs(self.clips_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_script_json(self, payload: dict):
        script_path = os.path.join(self.task_dir, "script.json")
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def _create_flow_manifest(
        self,
        status="COMPLETE",
        completed_scenes=None,
        is_flow_premium=True,
        expected_clip="flow_scene_01.mp4",
        scene_index=1,
    ):
        if completed_scenes is None:
            completed_scenes = [1]
        manifest = {
            "project_name": "flow",
            "flow_generation": {
                "status": status,
                "completed_scenes": completed_scenes,
            },
            "scenes": [
                {
                    "scene_index": scene_index,
                    "expected_clip": expected_clip,
                    "is_flow_premium": is_flow_premium,
                    "narration": "Cena de teste",
                    "duration_hint": 5.0,
                }
            ],
        }
        manifest_path = os.path.join(self.flow_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        return manifest_path

    # =========================================================================
    # A. ramo Flow persiste scene_materials/material_sources
    # =========================================================================
    def test_a_flow_branch_persists_scene_materials_and_material_sources(self):
        clip_file = os.path.join(self.clips_dir, "flow_scene_01.mp4")
        with open(clip_file, "wb") as f:
            f.write(b"\x00" * 1024)

        self._create_flow_manifest(status="COMPLETE", completed_scenes=[1])
        self._create_script_json({"params": {"video_subject": "Teste"}})

        mock_selection = SceneMaterialSelection(
            scene_index=1,
            material_path=clip_file,
            duration=5.0,
            provider="google_flow",
            asset_id="flow_scene_01.mp4",
            visual_source_type="flow",
            media_type="video",
        )

        scene_plan = ScenePlan(
            total_scenes=1,
            scenes=[
                ScenePlanItem(
                    scene_index=1,
                    narration="Texto de narração",
                    duration_hint=5.0,
                )
            ],
        )
        params = VideoParams(
            video_subject="Teste",
            video_script="Texto de narração",
            voice_name="pt-BR-AntonioNeural-Male",
        )

        with patch("scripts.flow_workflow.generate_pending_flow_scenes", return_value={"status": "COMPLETE"}), \
             patch("scripts.flow_workflow.resolve_project_materials", return_value=[mock_selection]), \
             patch("app.utils.utils.task_dir", return_value=self.task_dir), \
             patch("app.services.task_artifacts._script_file", return_value=task_artifacts.Path(os.path.join(self.task_dir, "script.json"))):

            selections, meta = flow_bridge.resolve_flow_materials_for_task(
                task_id=self.task_id,
                params=params,
                video_script="Texto de narração",
                scene_plan=scene_plan,
            )

        self.assertEqual(len(selections), 1)
        self.assertEqual(selections[0].provider, "google_flow")

        # Verifica persistência no script.json
        with open(os.path.join(self.task_dir, "script.json"), "r", encoding="utf-8") as f:
            saved_script = json.load(f)

        self.assertIn("scene_materials", saved_script)
        self.assertIn("material_sources", saved_script)
        self.assertEqual(len(saved_script["scene_materials"]), 1)
        self.assertEqual(len(saved_script["material_sources"]), 1)

        mat_source = saved_script["material_sources"][0]
        self.assertEqual(mat_source["provider"], "google_flow")
        self.assertEqual(mat_source["local_file"], clip_file)
        self.assertEqual(mat_source["visual_source_type"], "flow")
        # Status VERIFIED só pode ser emitido pelo Copyright Gate após validação.
        self.assertEqual(mat_source["provenance_status"], "GENERATED_FLOW_EVIDENCE_RECORDED")

    # =========================================================================
    # B. Google Flow válido → provenance PASS
    # =========================================================================
    def test_b_google_flow_valid_provenance_pass(self):
        clip_file = os.path.join(self.clips_dir, "flow_scene_01.mp4")
        with open(clip_file, "wb") as f:
            f.write(b"\x00" * 1024)

        self._create_flow_manifest(status="COMPLETE", completed_scenes=[1])
        sources = [
            {
                "provider": "google_flow",
                "asset_id": "flow_scene_01.mp4",
                "local_file": clip_file,
                "scene_index": 1,
            }
        ]
        self._create_script_json({
            "params": {"bgm_type": "none", "bgm_volume": 0.0},
            "material_sources": sources,
        })

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True, "duration": 5.0}), \
             patch("app.utils.utils.task_dir", return_value=self.task_dir):
            passed, reason, details = copyright_gate.evaluate_copyright_provenance_gate(
                task_id=self.task_id,
                task_base_dir=self.test_dir,
            )

        self.assertTrue(passed, f"Gate deveria aprovar Google Flow válido: {reason}")
        self.assertEqual(details.get("copyright_provenance_gate"), "PASS")
        self.assertEqual(details.get("flow_provenance_status"), "GENERATED_FLOW_PROVENANCE_VERIFIED")
        self.assertEqual(details.get("flow_clips_verified"), 1)

    # =========================================================================
    # C. Flow sem manifest → FAIL
    # =========================================================================
    def test_c_flow_without_manifest_fails_gate(self):
        clip_file = os.path.join(self.clips_dir, "flow_scene_01.mp4")
        with open(clip_file, "wb") as f:
            f.write(b"\x00" * 1024)

        # Sem criar manifest.json
        sources = [
            {
                "provider": "google_flow",
                "asset_id": "flow_scene_01.mp4",
                "local_file": clip_file,
                "scene_index": 1,
            }
        ]
        self._create_script_json({
            "params": {"bgm_type": "none", "bgm_volume": 0.0},
            "material_sources": sources,
        })

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True, "duration": 5.0}), \
             patch("app.utils.utils.task_dir", return_value=self.task_dir):
            passed, reason, details = copyright_gate.evaluate_copyright_provenance_gate(
                task_id=self.task_id,
                task_base_dir=self.test_dir,
            )

        self.assertFalse(passed)
        self.assertIn("Manifesto Flow inexistente", reason)

    # =========================================================================
    # D. Flow scene não completed → FAIL
    # =========================================================================
    def test_d_flow_scene_not_completed_fails_gate(self):
        clip_file = os.path.join(self.clips_dir, "flow_scene_01.mp4")
        with open(clip_file, "wb") as f:
            f.write(b"\x00" * 1024)

        # completed_scenes vazio
        self._create_flow_manifest(status="COMPLETE", completed_scenes=[])
        sources = [
            {
                "provider": "google_flow",
                "asset_id": "flow_scene_01.mp4",
                "local_file": clip_file,
                "scene_index": 1,
            }
        ]
        self._create_script_json({
            "params": {"bgm_type": "none", "bgm_volume": 0.0},
            "material_sources": sources,
        })

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True, "duration": 5.0}), \
             patch("app.utils.utils.task_dir", return_value=self.task_dir):
            passed, reason, details = copyright_gate.evaluate_copyright_provenance_gate(
                task_id=self.task_id,
                task_base_dir=self.test_dir,
            )

        self.assertFalse(passed)
        self.assertIn("não consta em completed_scenes", reason)

    # =========================================================================
    # E. arquivo Flow fora da task → FAIL
    # =========================================================================
    def test_e_flow_clip_outside_task_dir_fails_gate(self):
        outside_clip = os.path.join(self.test_dir, "outside_flow.mp4")
        with open(outside_clip, "wb") as f:
            f.write(b"\x00" * 1024)

        self._create_flow_manifest(status="COMPLETE", completed_scenes=[1])
        sources = [
            {
                "provider": "google_flow",
                "asset_id": "outside_flow.mp4",
                "local_file": outside_clip,
                "scene_index": 1,
            }
        ]
        self._create_script_json({
            "params": {"bgm_type": "none", "bgm_volume": 0.0},
            "material_sources": sources,
        })

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True, "duration": 5.0}), \
             patch("app.utils.utils.task_dir", return_value=self.task_dir):
            passed, reason, details = copyright_gate.evaluate_copyright_provenance_gate(
                task_id=self.task_id,
                task_base_dir=self.test_dir,
            )

        self.assertFalse(passed)
        self.assertIn("fora", reason.lower())

    # =========================================================================
    # F. arquivo Flow inexistente → FAIL
    # =========================================================================
    def test_f_flow_clip_nonexistent_file_fails_gate(self):
        nonexistent_clip = os.path.join(self.clips_dir, "nonexistent.mp4")
        self._create_flow_manifest(status="COMPLETE", completed_scenes=[1], expected_clip="nonexistent.mp4")
        sources = [
            {
                "provider": "google_flow",
                "asset_id": "nonexistent.mp4",
                "local_file": nonexistent_clip,
                "scene_index": 1,
            }
        ]
        self._create_script_json({
            "params": {"bgm_type": "none", "bgm_volume": 0.0},
            "material_sources": sources,
        })

        with patch("app.utils.utils.task_dir", return_value=self.task_dir):
            passed, reason, details = copyright_gate.evaluate_copyright_provenance_gate(
                task_id=self.task_id,
                task_base_dir=self.test_dir,
            )

        self.assertFalse(passed)
        self.assertIn("inexistente", reason.lower())

    # =========================================================================
    # G. local_cache sem origem comprovada → FAIL
    # =========================================================================
    def test_g_local_cache_unverified_origin_fails_gate(self):
        clip_file = os.path.join(self.task_dir, "cache_clip.mp4")
        with open(clip_file, "wb") as f:
            f.write(b"\x00" * 1024)

        sources = [
            {
                "provider": "local_cache",
                "asset_id": "cache_clip.mp4",
                "local_file": clip_file,
                "scene_index": 1,
            }
        ]
        self._create_script_json({
            "params": {"bgm_type": "none", "bgm_volume": 0.0},
            "material_sources": sources,
        })

        with patch("app.utils.utils.task_dir", return_value=self.task_dir):
            passed, reason, details = copyright_gate.evaluate_copyright_provenance_gate(
                task_id=self.task_id,
                task_base_dir=self.test_dir,
            )

        self.assertFalse(passed)
        self.assertIn("não autorizado ou sem proveniência comprovada", reason)

    # =========================================================================
    # H. pexels/pixabay/coverr continuam PASS
    # =========================================================================
    def test_h_remote_stock_providers_continue_to_pass(self):
        for provider in ["pexels", "pixabay", "coverr"]:
            clip_file = os.path.join(self.task_dir, f"{provider}_clip.mp4")
            with open(clip_file, "wb") as f:
                f.write(b"\x00" * 1024)

            sources = [
                {
                    "provider": provider,
                    "asset_id": f"id_{provider}_123",
                    "local_file": clip_file,
                    "source_page": f"https://{provider}.com/video/123",
                    "scene_index": 1,
                }
            ]
            self._create_script_json({
                "params": {"bgm_type": "none", "bgm_volume": 0.0},
                "material_sources": sources,
            })

            with patch("app.utils.utils.task_dir", return_value=self.task_dir):
                passed, reason, details = copyright_gate.evaluate_copyright_provenance_gate(
                    task_id=self.task_id,
                    task_base_dir=self.test_dir,
                )

            self.assertTrue(passed, f"Provedor {provider} deveria passar no gate: {reason}")
            self.assertEqual(details.get("copyright_provenance_gate"), "PASS")

    # =========================================================================
    # I. ambient_auto SAFE_PROCEDURAL continua PASS
    # =========================================================================
    def test_i_ambient_auto_safe_procedural_continues_to_pass(self):
        clip_file = os.path.join(self.task_dir, "coverr_clip.mp4")
        with open(clip_file, "wb") as f:
            f.write(b"\x00" * 1024)

        sources = [
            {
                "provider": "coverr",
                "asset_id": "coverr_001",
                "local_file": clip_file,
                "scene_index": 1,
            }
        ]
        self._create_script_json({
            "params": {"bgm_type": "ambient_auto", "bgm_volume": 0.2},
            "material_sources": sources,
        })

        with patch("app.utils.utils.task_dir", return_value=self.task_dir):
            prov = copyright_gate.build_asset_provenance(
                task_id=self.task_id,
                params={"bgm_type": "ambient_auto", "bgm_volume": 0.2},
                material_sources=sources,
                task_base_dir=self.test_dir,
            )
            passed, reason, details = copyright_gate.evaluate_copyright_provenance_gate(
                task_id=self.task_id,
                task_base_dir=self.test_dir,
            )

        self.assertEqual(prov["bgm"]["provenance_status"], "SAFE_PROCEDURAL")
        self.assertEqual(prov["provenance_status"], "SAFE_PROCEDURAL")
        self.assertTrue(passed, f"ambient_auto SAFE_PROCEDURAL deveria passar: {reason}")
        self.assertEqual(details.get("bgm_status"), "SAFE_PROCEDURAL")

    # =========================================================================
    # J. validate_clip_file lança exceção → gate FAIL (fail-closed)
    # =========================================================================
    def test_j_validator_exception_fails_gate(self):
        clip_file = os.path.join(self.clips_dir, "flow_scene_01.mp4")
        with open(clip_file, "wb") as f:
            f.write(b"\x00" * 1024)
        self._create_flow_manifest(status="COMPLETE", completed_scenes=[1])
        self._create_script_json({
            "params": {"bgm_type": "none", "bgm_volume": 0.0},
            "material_sources": [
                {"provider": "google_flow", "asset_id": "flow_scene_01.mp4", "local_file": clip_file, "scene_index": 1}
            ],
        })

        with patch("scripts.flow_workflow.validate_clip_file", side_effect=RuntimeError("ffprobe crashed")), \
             patch("app.utils.utils.task_dir", return_value=self.task_dir):
            passed, reason, details = copyright_gate.evaluate_copyright_provenance_gate(
                task_id=self.task_id,
                task_base_dir=self.test_dir,
            )

        self.assertFalse(passed)
        self.assertEqual(details.get("copyright_provenance_gate"), "FAIL")
        self.assertIn("fail-closed", reason)

    # =========================================================================
    # K. expected_clip deve ser EXATO (sem fallback por scene_index)
    # =========================================================================
    def test_k_expected_clip_must_match_exactly(self):
        other_clip = os.path.join(self.clips_dir, "outro_nome.mp4")
        with open(other_clip, "wb") as f:
            f.write(b"\x00" * 1024)
        self._create_flow_manifest(
            status="COMPLETE", completed_scenes=[1], expected_clip="flow_scene_01.mp4", scene_index=1
        )
        self._create_script_json({
            "params": {"bgm_type": "none", "bgm_volume": 0.0},
            "material_sources": [
                {"provider": "google_flow", "asset_id": "outro_nome.mp4", "local_file": other_clip, "scene_index": 1}
            ],
        })

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True, "duration": 5.0}), \
             patch("app.utils.utils.task_dir", return_value=self.task_dir):
            passed, reason, details = copyright_gate.evaluate_copyright_provenance_gate(
                task_id=self.task_id,
                task_base_dir=self.test_dir,
            )

        self.assertFalse(passed)
        self.assertEqual(details.get("copyright_provenance_gate"), "FAIL")
        self.assertIn("expected_clip", reason)

    # =========================================================================
    # L. Autônomo: cache local sem proveniência NÃO é selecionado
    # =========================================================================
    def test_l_autonomous_skips_unverified_local_cache_and_uses_remote_stock(self):
        from scripts import flow_workflow

        manifest = {
            "project_name": "flow",
            "flow_generation": {"status": "COMPLETE", "completed_scenes": []},
            "scenes": [
                # Flow premium sem clipe → fallback_stock (filler local existiria)
                {"scene_index": 1, "expected_clip": "flow_scene_01.mp4", "is_flow_premium": True,
                 "narration": "Cena um", "duration_hint": 5.0, "search_terms": ["city"]},
                # Stock filler com clipe local existente em clips/ (local_clip)
                {"scene_index": 2, "expected_clip": "stock_scene_02.mp4", "is_flow_premium": False,
                 "narration": "Cena dois", "duration_hint": 5.0, "search_terms": ["ocean"]},
            ],
        }
        with open(os.path.join(self.flow_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f)

        local_clip = os.path.join(self.clips_dir, "stock_scene_02.mp4")
        with open(local_clip, "wb") as f:
            f.write(b"\x00" * 1024)
        cache_clip = os.path.join(self.test_dir, "cache_videos", "cached.mp4")
        os.makedirs(os.path.dirname(cache_clip), exist_ok=True)
        with open(cache_clip, "wb") as f:
            f.write(b"\x00" * 1024)

        def fake_resolver(task_id, scene_plan, params, audio_duration, strict):
            idx = scene_plan.scenes[0].scene_index
            return [
                SceneMaterialSelection(
                    scene_index=idx,
                    material_path=os.path.join(self.task_dir, f"pexels_{idx}.mp4"),
                    duration=5.0,
                    provider="pexels",
                    asset_id=f"pexels-{idx}",
                    source_url=f"https://www.pexels.com/video/{idx}/",
                    search_term_used=f"term-{idx}",
                    media_type="video",
                    visual_source_type="stock",
                )
            ]

        params = VideoParams(
            video_subject="Autônomo",
            video_source="pexels",
            final_media_quality_required=True,
        )

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True, "duration": 5.0}), \
             patch("scripts.flow_workflow._list_valid_stock_filler_clips", return_value=[cache_clip]) as mock_pool, \
             patch("scripts.flow_workflow._find_stock_filler_clip", return_value=cache_clip), \
             patch("app.services.material.has_material_api_keys", return_value=True), \
             patch("app.services.scene_material.resolve_scene_materials", side_effect=fake_resolver) as mock_res:
            selections = flow_workflow.resolve_project_materials(
                project_dir=self.flow_dir,
                task_id=self.task_id,
                stock_source="pexels",
                flow_failure_policy="fallback_stock",
                params=params,
            )

        self.assertEqual(mock_res.call_count, 2)
        mock_pool.assert_not_called()
        self.assertEqual(len(selections), 2)
        for sel in selections:
            self.assertNotIn(sel.material_path, (local_clip, cache_clip))
            self.assertNotIn(sel.provider, ("local_cache", "local_clip", "stock_fallback"))
            self.assertEqual(sel.provider, "pexels")
            self.assertEqual(sel.asset_id, f"pexels-{sel.scene_index}")
            self.assertEqual(sel.source_url, f"https://www.pexels.com/video/{sel.scene_index}/")
            self.assertEqual(sel.search_term_used, f"term-{sel.scene_index}")

    # =========================================================================
    # M. Autônomo: persist_scene_resolution lança exceção → fail-closed cedo
    # =========================================================================
    def _autonomous_bridge_inputs(self):
        clip_file = os.path.join(self.clips_dir, "flow_scene_01.mp4")
        with open(clip_file, "wb") as f:
            f.write(b"\x00" * 1024)
        self._create_flow_manifest(status="COMPLETE", completed_scenes=[1])
        selection = SceneMaterialSelection(
            scene_index=1,
            material_path=clip_file,
            duration=5.0,
            provider="google_flow",
            asset_id="flow_scene_01.mp4",
            visual_source_type="flow",
            media_type="video",
        )
        scene_plan = ScenePlan(
            total_scenes=1,
            scenes=[ScenePlanItem(scene_index=1, narration="Texto", duration_hint=5.0)],
        )
        params = VideoParams(video_subject="Autônomo", final_media_quality_required=True)
        return selection, scene_plan, params

    def test_m_autonomous_persist_exception_blocks_before_render(self):
        selection, scene_plan, params = self._autonomous_bridge_inputs()
        self._create_script_json({"params": {"video_subject": "Autônomo"}})

        with patch("scripts.flow_workflow.generate_pending_flow_scenes", return_value={"status": "COMPLETE"}), \
             patch("scripts.flow_workflow.resolve_project_materials", return_value=[selection]), \
             patch("app.utils.utils.task_dir", return_value=self.task_dir), \
             patch("app.services.scene_material.persist_scene_resolution", side_effect=OSError("disk full")), \
             patch("app.services.scene_assembly.assemble_scene_clips") as mock_asm, \
             patch("app.services.video.generate_video") as mock_render:
            with self.assertRaises(flow_bridge.FlowProvenancePersistError) as ctx:
                flow_bridge.resolve_flow_materials_for_task(
                    task_id=self.task_id,
                    params=params,
                    video_script="Texto",
                    scene_plan=scene_plan,
                )

        self.assertIn("FLOW_PROVENANCE_PERSIST_FAILED", str(ctx.exception))
        self.assertEqual(getattr(ctx.exception, "reason_code", None), "FLOW_PROVENANCE_PERSIST_FAILED")
        mock_asm.assert_not_called()
        mock_render.assert_not_called()

    # =========================================================================
    # N. Autônomo: patch_script_data não persiste (script.json ausente) → fail-closed
    # =========================================================================
    def test_n_autonomous_patch_not_persisted_blocks(self):
        selection, scene_plan, params = self._autonomous_bridge_inputs()
        # Sem script.json → patch_script_data retorna False

        with patch("scripts.flow_workflow.generate_pending_flow_scenes", return_value={"status": "COMPLETE"}), \
             patch("scripts.flow_workflow.resolve_project_materials", return_value=[selection]), \
             patch("app.utils.utils.task_dir", return_value=self.task_dir), \
             patch("app.services.task_artifacts._script_file", return_value=task_artifacts.Path(os.path.join(self.task_dir, "script.json"))):
            with self.assertRaises(flow_bridge.FlowProvenancePersistError):
                flow_bridge.resolve_flow_materials_for_task(
                    task_id=self.task_id,
                    params=params,
                    video_script="Texto",
                    scene_plan=scene_plan,
                )

    # =========================================================================
    # O. Legacy Flow: script.json sem material_sources/scene_materials,
    #    asset_provenance com visual_clips=[] → reconstrói via manifest.json → PASS
    # =========================================================================
    def test_o_legacy_flow_manifest_fallback_provenance_pass(self):
        clip_file = os.path.join(self.clips_dir, "flow_scene_01.mp4")
        with open(clip_file, "wb") as f:
            f.write(b"\x00" * 1024)

        self._create_flow_manifest(
            status="COMPLETE",
            completed_scenes=[1],
            expected_clip="flow_scene_01.mp4",
            scene_index=1,
            is_flow_premium=True,
        )

        # Sem material_sources, sem scene_materials, asset_provenance com visual_clips=[]
        self._create_script_json({
            "params": {"bgm_type": "none", "bgm_volume": 0.0},
            "asset_provenance": {
                "bgm": {
                    "enabled": False,
                    "filename": None,
                    "source": "none",
                    "license_type": "not_applicable",
                    "provenance_status": "SAFE_NO_BGM",
                },
                "visual_clips": [],
                "presenter": {"enabled": False, "mode": "none"},
                "provenance_status": "INCOMPLETE_ASSETS",
            },
        })

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True, "duration": 5.0}), \
             patch("app.utils.utils.task_dir", return_value=self.task_dir):
            passed, reason, details = copyright_gate.evaluate_copyright_provenance_gate(
                task_id=self.task_id,
                task_base_dir=self.test_dir,
            )

        self.assertTrue(passed, f"Gate deveria aprovar Flow legado reconstruído a partir do manifest: {reason}")
        self.assertEqual(details.get("copyright_provenance_gate"), "PASS")
        self.assertEqual(details.get("flow_provenance_status"), "GENERATED_FLOW_PROVENANCE_VERIFIED")
        self.assertEqual(details.get("flow_clips_verified"), 1)

    # =========================================================================
    # P. Legacy Flow: se o manifesto não comprovar a cena → fail-closed FAIL
    # =========================================================================
    def test_p_legacy_flow_manifest_unproven_scene_fails_gate(self):
        clip_file = os.path.join(self.clips_dir, "flow_scene_01.mp4")
        with open(clip_file, "wb") as f:
            f.write(b"\x00" * 1024)

        # Subcaso 1: cena NÃO consta em completed_scenes
        self._create_flow_manifest(
            status="COMPLETE",
            completed_scenes=[],  # cena 1 não completada
            expected_clip="flow_scene_01.mp4",
            scene_index=1,
            is_flow_premium=True,
        )
        self._create_script_json({
            "params": {"bgm_type": "none", "bgm_volume": 0.0},
            "asset_provenance": {"visual_clips": []},
        })

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True, "duration": 5.0}), \
             patch("app.utils.utils.task_dir", return_value=self.task_dir):
            passed, reason, details = copyright_gate.evaluate_copyright_provenance_gate(
                task_id=self.task_id,
                task_base_dir=self.test_dir,
            )

        self.assertFalse(passed, "Gate deve reprovar se cena não estiver em completed_scenes")
        self.assertEqual(details.get("copyright_provenance_gate"), "FAIL")

        # Subcaso 2: is_flow_premium == False
        self._create_flow_manifest(
            status="COMPLETE",
            completed_scenes=[1],
            expected_clip="flow_scene_01.mp4",
            scene_index=1,
            is_flow_premium=False,
        )
        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True, "duration": 5.0}), \
             patch("app.utils.utils.task_dir", return_value=self.task_dir):
            passed, reason, details = copyright_gate.evaluate_copyright_provenance_gate(
                task_id=self.task_id,
                task_base_dir=self.test_dir,
            )
        self.assertFalse(passed, "Gate deve reprovar se is_flow_premium for False")

        # Subcaso 3: flow_generation status != COMPLETE (needs recovery)
        self._create_flow_manifest(
            status="FLOW_GENERATION_NEEDS_RECOVERY",
            completed_scenes=[1],
            expected_clip="flow_scene_01.mp4",
            scene_index=1,
            is_flow_premium=True,
        )
        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True, "duration": 5.0}), \
             patch("app.utils.utils.task_dir", return_value=self.task_dir):
            passed, reason, details = copyright_gate.evaluate_copyright_provenance_gate(
                task_id=self.task_id,
                task_base_dir=self.test_dir,
            )
        self.assertFalse(passed, "Gate deve reprovar se Flow status for NEEDS_RECOVERY")

    # =========================================================================
    # Regressões Direcionadas: Hotfix Flow Parcial
    # =========================================================================
    def test_partial_flow_all_used_scenes_proven_pass(self):
        """1. Flow parcialmente falho (ex: FAILED_SCENE_11) com todas as cenas efetivamente usadas comprovadas -> PASS."""
        # Cria clipes Flow para as cenas completadas [1, 2, 5]
        for s_idx in [1, 2, 5]:
            clip_f = os.path.join(self.clips_dir, f"flow_scene_{s_idx:02d}.mp4")
            with open(clip_f, "wb") as f:
                f.write(b"\x00" * 1024)

        # Cria clipes Pexels para cenas alternativas [3, 11]
        for s_idx in [3, 11]:
            clip_f = os.path.join(self.task_dir, f"pexels_scene_{s_idx:02d}.mp4")
            with open(clip_f, "wb") as f:
                f.write(b"\x00" * 1024)

        # Manifesto com status FAILED_SCENE_11 e completed_scenes=[1, 2, 5]
        manifest = {
            "project_name": "flow",
            "flow_generation": {
                "status": "FAILED_SCENE_11",
                "completed_scenes": [1, 2, 5],
            },
            "scenes": [
                {"scene_index": 1, "expected_clip": "flow_scene_01.mp4", "is_flow_premium": True, "duration_hint": 5.0},
                {"scene_index": 2, "expected_clip": "flow_scene_02.mp4", "is_flow_premium": True, "duration_hint": 5.0},
                {"scene_index": 5, "expected_clip": "flow_scene_05.mp4", "is_flow_premium": True, "duration_hint": 5.0},
                {"scene_index": 11, "expected_clip": "flow_scene_11.mp4", "is_flow_premium": True, "duration_hint": 5.0},
            ],
        }
        with open(os.path.join(self.flow_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        # material_sources: cenas 1, 2, 5 como Flow; cenas 3, 11 como Pexels
        sources = [
            {"provider": "google_flow", "asset_id": "flow_scene_01.mp4", "local_file": os.path.join(self.clips_dir, "flow_scene_01.mp4"), "scene_index": 1},
            {"provider": "google_flow", "asset_id": "flow_scene_02.mp4", "local_file": os.path.join(self.clips_dir, "flow_scene_02.mp4"), "scene_index": 2},
            {"provider": "pexels", "asset_id": "px_3", "local_file": os.path.join(self.task_dir, "pexels_scene_03.mp4"), "scene_index": 3},
            {"provider": "google_flow", "asset_id": "flow_scene_05.mp4", "local_file": os.path.join(self.clips_dir, "flow_scene_05.mp4"), "scene_index": 5},
            {"provider": "pexels", "asset_id": "px_11", "local_file": os.path.join(self.task_dir, "pexels_scene_11.mp4"), "scene_index": 11},
        ]
        self._create_script_json({
            "params": {"bgm_type": "none", "bgm_volume": 0.0},
            "material_sources": sources,
        })

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True, "duration": 5.0}), \
             patch("app.utils.utils.task_dir", return_value=self.task_dir):
            passed, reason, details = copyright_gate.evaluate_copyright_provenance_gate(
                task_id=self.task_id,
                task_base_dir=self.test_dir,
            )

        self.assertTrue(passed, f"Gate deveria aprovar Flow parcial com todas as cenas comprovadas: {reason}")
        self.assertEqual(details.get("copyright_provenance_gate"), "PASS")
        self.assertEqual(details.get("flow_provenance_status"), "GENERATED_FLOW_PROVENANCE_VERIFIED")
        self.assertEqual(details.get("flow_clips_verified"), 3)

    def test_partial_flow_unproven_scene_fails_gate(self):
        """2. Flow parcialmente falho com cena Flow não comprovada (não concluída no manifesto) -> BLOCK."""
        # Cria clipes Flow para as cenas completadas [1, 2, 5]
        for s_idx in [1, 2, 5]:
            clip_f = os.path.join(self.clips_dir, f"flow_scene_{s_idx:02d}.mp4")
            with open(clip_f, "wb") as f:
                f.write(b"\x00" * 1024)

        # Cria clipe não completado da cena 11
        clip_11 = os.path.join(self.clips_dir, "flow_scene_11.mp4")
        with open(clip_11, "wb") as f:
            f.write(b"\x00" * 1024)

        manifest = {
            "project_name": "flow",
            "flow_generation": {
                "status": "FAILED_SCENE_11",
                "completed_scenes": [1, 2, 5],
            },
            "scenes": [
                {"scene_index": 1, "expected_clip": "flow_scene_01.mp4", "is_flow_premium": True, "duration_hint": 5.0},
                {"scene_index": 11, "expected_clip": "flow_scene_11.mp4", "is_flow_premium": True, "duration_hint": 5.0},
            ],
        }
        with open(os.path.join(self.flow_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        # material_sources tenta usar cena 11 como google_flow mesmo sem estar em completed_scenes
        sources = [
            {"provider": "google_flow", "asset_id": "flow_scene_01.mp4", "local_file": os.path.join(self.clips_dir, "flow_scene_01.mp4"), "scene_index": 1},
            {"provider": "google_flow", "asset_id": "flow_scene_11.mp4", "local_file": clip_11, "scene_index": 11},
        ]
        self._create_script_json({
            "params": {"bgm_type": "none", "bgm_volume": 0.0},
            "material_sources": sources,
        })

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True, "duration": 5.0}), \
             patch("app.utils.utils.task_dir", return_value=self.task_dir):
            passed, reason, details = copyright_gate.evaluate_copyright_provenance_gate(
                task_id=self.task_id,
                task_base_dir=self.test_dir,
            )

        self.assertFalse(passed, "Gate deve reprovar se cena Flow não estiver em completed_scenes")
        self.assertEqual(details.get("copyright_provenance_gate"), "FAIL")
        self.assertIn("completed_scenes", reason)

    def test_full_flow_valid_continues_pass(self):
        """3. Flow completo válido continua PASS."""
        for s_idx in [1, 2]:
            clip_f = os.path.join(self.clips_dir, f"flow_scene_{s_idx:02d}.mp4")
            with open(clip_f, "wb") as f:
                f.write(b"\x00" * 1024)

        manifest = {
            "project_name": "flow",
            "flow_generation": {
                "status": "COMPLETE",
                "completed_scenes": [1, 2],
            },
            "scenes": [
                {"scene_index": 1, "expected_clip": "flow_scene_01.mp4", "is_flow_premium": True, "duration_hint": 5.0},
                {"scene_index": 2, "expected_clip": "flow_scene_02.mp4", "is_flow_premium": True, "duration_hint": 5.0},
            ],
        }
        with open(os.path.join(self.flow_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        sources = [
            {"provider": "google_flow", "asset_id": "flow_scene_01.mp4", "local_file": os.path.join(self.clips_dir, "flow_scene_01.mp4"), "scene_index": 1},
            {"provider": "google_flow", "asset_id": "flow_scene_02.mp4", "local_file": os.path.join(self.clips_dir, "flow_scene_02.mp4"), "scene_index": 2},
        ]
        self._create_script_json({
            "params": {"bgm_type": "none", "bgm_volume": 0.0},
            "material_sources": sources,
        })

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True, "duration": 5.0}), \
             patch("app.utils.utils.task_dir", return_value=self.task_dir):
            passed, reason, details = copyright_gate.evaluate_copyright_provenance_gate(
                task_id=self.task_id,
                task_base_dir=self.test_dir,
            )

        self.assertTrue(passed, f"Gate deveria aprovar Flow completo válido: {reason}")
        self.assertEqual(details.get("copyright_provenance_gate"), "PASS")
        self.assertEqual(details.get("flow_clips_verified"), 2)


if __name__ == "__main__":
    unittest.main()
