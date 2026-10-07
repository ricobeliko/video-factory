"""
test/services/test_flow_workflow.py
===================================
Testes Unitários da Fase V1.2 — Otimização de Passos Manuais (Google Flow).

Cobre:
1. build_flow_prompt: geração de prompt cinematográfico 9:16 vertical sem texto/marca d'água.
2. prepare_project: divisão de cenas temporizada, manifest.json, prompts_for_flow.md e diretório clips/.
3. get_project_status: detecção correta de clipes prontos e faltantes.
4. render_project (dry-run): montagem determinística de instruções via ScenePlan e SceneAssembly.
"""

import json
import os
import shutil
import tempfile
import unittest

from scripts.flow_workflow import (
    build_flow_prompt,
    get_project_status,
    prepare_project,
    render_project,
)


class TestFlowWorkflow(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_flow_workflow_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_build_flow_prompt_cinematic_format(self):
        narration = "O comboio presidencial acelerou pelas ruas sob aplausos da multidão."
        prompt_data = build_flow_prompt(
            narration=narration,
            subject="JFK Dallas",
            visual_intent="archival footage",
        )

        self.assertIn("prompt_en", prompt_data)
        self.assertIn("prompt_pt", prompt_data)
        p_en = prompt_data["prompt_en"]

        # Requisitos fundamentais para o Google Flow / Veo
        self.assertIn("9:16 vertical portrait composition", p_en)
        self.assertIn("no text", p_en)
        self.assertIn("no watermark", p_en)
        self.assertIn("archival film", p_en)

    def test_prepare_project_generates_structure_and_manifest(self):
        script = (
            "A misteriosa maleta preta acompanhava o presidente em todas as viagens oficiais. "
            "Dentro dela estavam os códigos secretos de autorização do arsenal nuclear. "
            "Qualquer decisão errada poderia desencadear o fim imediato da civilização."
        )

        res = prepare_project(
            script_text=script,
            project_name="briefcase_test",
            video_subject="Maleta Nuclear",
            target_scene_duration=8.0,
            base_dir=self.test_dir,
        )

        project_dir = res["project_dir"]
        manifest_path = res["manifest_path"]
        prompts_md_path = res["prompts_md_path"]
        clips_dir = res["clips_dir"]

        self.assertTrue(os.path.isdir(project_dir))
        self.assertTrue(os.path.isdir(clips_dir))
        self.assertTrue(os.path.isfile(manifest_path))
        self.assertTrue(os.path.isfile(prompts_md_path))

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        self.assertEqual(manifest["project_name"], "briefcase_test")
        self.assertGreaterEqual(manifest["total_scenes"], 2)

        for sc in manifest["scenes"]:
            self.assertIn("scene_index", sc)
            self.assertIn("narration", sc)
            self.assertIn("expected_clip", sc)
            self.assertTrue(sc["expected_clip"].startswith("flow_scene_"))
            self.assertTrue(sc["expected_clip"].endswith(".mp4"))
            self.assertIn("prompt_en", sc)

        with open(prompts_md_path, "r", encoding="utf-8") as f:
            md_content = f.read()

        self.assertIn("Prompts Google Flow — Projeto: briefcase_test", md_content)
        self.assertIn("Cena 01", md_content)

    def test_get_project_status_and_dry_run_assembly(self):
        script = (
            "Primeira cena introdutória com foco na tensão política global. "
            "Segunda cena dramática mostrando a chegada ao hospital em alta velocidade."
        )

        prep = prepare_project(
            script_text=script,
            project_name="status_test",
            base_dir=self.test_dir,
        )
        p_dir = prep["project_dir"]

        # Inicialmente todos os clipes estão ausentes
        status_init = get_project_status(p_dir)
        self.assertEqual(status_init["ready_flow_clips"], 0)
        self.assertEqual(status_init["missing_clips"], status_init["total_scenes"])

        # Cria um arquivo mock para a cena 1
        clip1_path = os.path.join(prep["clips_dir"], "flow_scene_01.mp4")
        with open(clip1_path, "wb") as f:
            f.write(b"\x00" * 1024)

        status_after = get_project_status(p_dir)
        self.assertEqual(status_after["ready_flow_clips"], 1)

        # Cria mock para a cena 2 para permitir dry_run sem depender de cache_videos
        clip2_path = os.path.join(prep["clips_dir"], "flow_scene_02.mp4")
        with open(clip2_path, "wb") as f:
            f.write(b"\x00" * 1024)

        # Executa montagem em modo dry-run
        render_res = render_project(project_dir=p_dir, dry_run=True)
        self.assertEqual(render_res["status"], "DRY_RUN_SUCCESS")
        self.assertEqual(render_res["total_scenes"], status_after["total_scenes"])
        self.assertGreater(render_res["estimated_duration"], 0.0)
        self.assertEqual(len(render_res["instructions"]), status_after["total_scenes"])


if __name__ == "__main__":
    unittest.main()
