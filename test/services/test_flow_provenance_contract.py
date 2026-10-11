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
        self.assertEqual(mat_source["provenance_status"], "GENERATED_FLOW_PROVENANCE_VERIFIED")

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


if __name__ == "__main__":
    unittest.main()
