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
from unittest.mock import patch

from scripts.flow_playwright import (
    FlowSceneResult,
    generate_flow_scene,
)
from scripts.flow_workflow import (
    DEFAULT_FLOW_PREMIUM_SCENES_PER_SHORT,
    build_flow_prompt,
    generate_pending_flow_scenes,
    get_project_status,
    prepare_project,
    render_project,
    select_default_flow_scenes,
    update_manifest_flow_checkpoint,
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

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True, "duration": 5.0}):
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

    def test_select_default_flow_scenes_and_backward_compatibility(self):
        self.assertEqual(DEFAULT_FLOW_PREMIUM_SCENES_PER_SHORT, 6)

        # Simula 8 cenas
        class MockScene:
            def __init__(self, idx, dur):
                self.scene_index = idx
                self.duration_hint = dur

        mock_8_scenes = [MockScene(i, 8.0) for i in range(1, 9)]
        selected_6 = select_default_flow_scenes(mock_8_scenes, target_count=6)

        # Deve selecionar exatamente 6 cenas
        self.assertEqual(len(selected_6), 6)
        # Sempre inclui Cena 1 (Hook) e Cena 8 (Fechamento)
        self.assertIn(1, selected_6)
        self.assertIn(8, selected_6)

        # Preparação com seleção automática padrão (6 cenas)
        long_script = " ".join([f"Frase explicativa detalhada para a cena número {i} do teste." for i in range(1, 9)])
        res_default = prepare_project(
            script_text=long_script,
            project_name="default_6_scenes_test",
            base_dir=self.test_dir,
            target_scene_duration=5.0,
        )
        with open(res_default["manifest_path"], "r", encoding="utf-8") as f:
            manifest_default = json.load(f)

        self.assertGreaterEqual(manifest_default["total_scenes"], 6)
        self.assertEqual(len(manifest_default["flow_scenes"]), 6)

        # Compatibilidade com projetos que passam explicitamente 4 cenas
        res_compat_4 = prepare_project(
            script_text=long_script,
            project_name="compat_4_scenes_test",
            base_dir=self.test_dir,
            flow_scenes=[1, 4, 5, 7],
            target_scene_duration=5.0,
        )
        with open(res_compat_4["manifest_path"], "r", encoding="utf-8") as f:
            manifest_compat = json.load(f)

        self.assertEqual(manifest_compat["flow_scenes"], [1, 4, 5, 7])
        flow_flags = [s["is_flow_premium"] for s in manifest_compat["scenes"] if s["scene_index"] in [1, 4, 5, 7]]
        self.assertTrue(all(flow_flags))

    def test_generate_flow_scene_idempotency_valid_clip(self):
        """1. Cena válida => ALREADY_COMPLETE e zero chamadas ao driver Playwright."""
        prep = prepare_project(
            script_text="Cena de teste único para idempotência.",
            project_name="idempotent_single",
            base_dir=self.test_dir,
            flow_scenes=[1],
        )
        clip_path = os.path.join(prep["clips_dir"], "flow_scene_01.mp4")
        with open(clip_path, "wb") as f:
            f.write(b"\x00" * 1024)

        with patch("scripts.flow_playwright.validate_clip_file") as mock_val, \
             patch("scripts.flow_playwright.run_playwright_flow_poc") as mock_poc:
            mock_val.return_value = {"valid": True, "duration": 7.5, "size": 1024, "file_path": clip_path}
            mock_poc.side_effect = AssertionError("run_playwright_flow_poc não deve ser chamado quando clipe é válido")

            res = generate_flow_scene(manifest_path=prep["manifest_path"], scene_index=1)

            self.assertEqual(res.status, "ALREADY_COMPLETE")
            self.assertEqual(res.credits_consumed, 0)
            self.assertTrue(res.output_valid)
            self.assertEqual(res.duration, 7.5)
            self.assertEqual(res.output_file, clip_path)
            mock_poc.assert_not_called()

    def test_generate_pending_two_scenes_ready_skips_browser(self):
        """2. Duas cenas prontas => generate_pending_flow_scenes não abre browser."""
        prep = prepare_project(
            script_text="Primeira cena completa. Segunda cena completa.",
            project_name="two_ready",
            base_dir=self.test_dir,
            flow_scenes=[1, 2],
        )
        for i in (1, 2):
            clip_path = os.path.join(prep["clips_dir"], f"flow_scene_{i:02d}.mp4")
            with open(clip_path, "wb") as f:
                f.write(b"\x00" * 1024)

        with patch("scripts.flow_workflow.validate_clip_file") as mock_val, \
             patch("scripts.flow_workflow.generate_flow_scene") as mock_gen:
            mock_val.return_value = {"valid": True, "duration": 6.0, "size": 1024}
            mock_gen.side_effect = AssertionError("generate_flow_scene não deve ser chamado quando todas cenas são válidas")

            res = generate_pending_flow_scenes(manifest_path=prep["manifest_path"])

            self.assertEqual(res["status"], "COMPLETE")
            self.assertEqual(res["completed_count"], 2)
            self.assertEqual(res["attempted_count"], 0)
            mock_gen.assert_not_called()

    def test_scenes_processed_sequentially_and_max_scenes_respected(self):
        """3 e 4. Cenas processadas sequencialmente e max_scenes respeitado."""
        long_script = (
            "Primeira cena explicativa detalhada para a abertura da narrativa histórica. "
            "Segunda cena dramática descrevendo o momento crítico do acontecimento. "
            "Terceira cena conclusiva finalizando a jornada com grande impacto."
        )
        prep = prepare_project(
            script_text=long_script,
            project_name="seq_test",
            base_dir=self.test_dir,
            flow_scenes=[1, 2, 3],
            target_scene_duration=4.0,
        )

        called_order = []

        def mock_generate(manifest_path, scene_index, **kwargs):
            called_order.append(scene_index)
            return FlowSceneResult(
                status="SUCCESS",
                scene_index=scene_index,
                output_file=f"dummy_{scene_index}.mp4",
                output_valid=True,
                credits_consumed=15,
            )

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": False}), \
             patch("scripts.flow_workflow.generate_flow_scene", side_effect=mock_generate):

            res = generate_pending_flow_scenes(manifest_path=prep["manifest_path"], max_scenes=2)

            # Processou sequencialmente 1, depois 2; não tentou cena 3
            self.assertEqual(called_order, [1, 2])
            self.assertEqual(res["attempted_count"], 2)
            self.assertEqual(res["completed_count"], 2)
            self.assertEqual(res["status"], "MAX_SCENES_REACHED")

    def test_flow_project_url_persisted_and_reused(self):
        """5. flow_project_url persistido e reutilizado entre execuções."""
        prep = prepare_project(
            script_text="Cena para testar project url persistente.",
            project_name="url_persist",
            base_dir=self.test_dir,
            flow_scenes=[1],
        )

        dummy_flow_url = "https://flow.google.com/project/ca11d34d-test-url"

        def mock_generate(manifest_path, scene_index, project_url=None, **kwargs):
            return FlowSceneResult(
                status="SUCCESS",
                scene_index=scene_index,
                output_valid=True,
                project_url=dummy_flow_url,
                credits_consumed=15,
            )

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": False}), \
             patch("scripts.flow_workflow.generate_flow_scene", side_effect=mock_generate):

            res = generate_pending_flow_scenes(manifest_path=prep["manifest_path"], max_scenes=1)
            self.assertEqual(res["project_url"], dummy_flow_url)

            # Verifica persistência no manifest.json
            with open(prep["manifest_path"], "r", encoding="utf-8") as f:
                manifest_data = json.load(f)

            self.assertEqual(manifest_data.get("flow_project_url"), dummy_flow_url)
            self.assertEqual(manifest_data.get("flow_generation", {}).get("project_url"), dummy_flow_url)

    def test_restart_skips_completed_scenes(self):
        """6. Restart pula cenas já concluídas e continua a partir da pendente."""
        long_script = (
            "Primeira cena explicativa detalhada já concluída no teste anterior. "
            "Segunda cena dramática detalhada também já concluída com sucesso. "
            "Terceira cena pendente que deve ser a única executada nesta chamada."
        )
        prep = prepare_project(
            script_text=long_script,
            project_name="resume_test",
            base_dir=self.test_dir,
            flow_scenes=[1, 2, 3],
            target_scene_duration=4.0,
        )
        # Cria arquivos para cena 1 e cena 2
        for i in (1, 2):
            clip_path = os.path.join(prep["clips_dir"], f"flow_scene_{i:02d}.mp4")
            with open(clip_path, "wb") as f:
                f.write(b"\x00" * 1024)

        called_scenes = []

        def mock_validate(path):
            if "01" in path or "02" in path:
                return {"valid": True, "duration": 5.0}
            return {"valid": False}

        def mock_generate(manifest_path, scene_index, **kwargs):
            called_scenes.append(scene_index)
            return FlowSceneResult(status="SUCCESS", scene_index=scene_index, output_valid=True)

        with patch("scripts.flow_workflow.validate_clip_file", side_effect=mock_validate), \
             patch("scripts.flow_workflow.generate_flow_scene", side_effect=mock_generate):

            res = generate_pending_flow_scenes(manifest_path=prep["manifest_path"])

            # Cenas 1 e 2 foram puladas; apenas Cena 3 foi chamada
            self.assertEqual(called_scenes, [3])
            self.assertEqual(res["attempted_count"], 1)
            self.assertEqual(res["completed_count"], 3)
            self.assertEqual(res["status"], "COMPLETE")

    def test_profile_busy_fail_closed(self):
        """7. Perfil ocupado (EDGE_PROFILE_CLOSE / FLOW_BROWSER_BUSY) => fail-closed sem retry/kill."""
        prep = prepare_project(
            script_text="Cena teste perfil ocupado.",
            project_name="busy_test",
            base_dir=self.test_dir,
            flow_scenes=[1],
        )

        with patch("scripts.flow_playwright.run_playwright_flow_poc") as mock_poc:
            mock_poc.return_value = {
                "status": "AWAITING_FLOW_EDGE_PROFILE_CLOSE",
                "error": "AWAITING_FLOW_EDGE_PROFILE_CLOSE",
            }
            res = generate_flow_scene(manifest_path=prep["manifest_path"], scene_index=1)
            self.assertEqual(res.status, "FLOW_BROWSER_BUSY")

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": False}), \
             patch("scripts.flow_workflow.generate_flow_scene") as mock_gen:
            mock_gen.return_value = FlowSceneResult(
                status="FLOW_BROWSER_BUSY",
                scene_index=1,
                error="AWAITING_FLOW_EDGE_PROFILE_CLOSE",
            )
            pending_res = generate_pending_flow_scenes(manifest_path=prep["manifest_path"])
            self.assertEqual(pending_res["status"], "FLOW_BROWSER_BUSY")

            with open(prep["manifest_path"], "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
            self.assertEqual(manifest_data["flow_generation"]["status"], "FLOW_BROWSER_BUSY")

    def test_strict_policy_blocks_render_when_flow_missing(self):
        """8. Política 'strict' => cena Flow ausente bloqueia render (FileNotFoundError)."""
        prep = prepare_project(
            script_text="Cena premium sem arquivo local.",
            project_name="strict_test",
            base_dir=self.test_dir,
            flow_scenes=[1],
        )
        with self.assertRaises(FileNotFoundError):
            render_project(project_dir=prep["project_dir"], dry_run=True, flow_failure_policy="strict")

    def test_fallback_stock_allows_render_when_flow_missing(self):
        """9. Política 'fallback_stock' => resolve material stock preservando source=stock_fallback."""
        prep = prepare_project(
            script_text="Cena premium que usará fallback de estoque.",
            project_name="fallback_test",
            base_dir=self.test_dir,
            flow_scenes=[1],
        )
        # Mock de clipe filler existente
        filler_path = os.path.join(self.test_dir, "filler.mp4")
        with open(filler_path, "wb") as f:
            f.write(b"\x00" * 1024)

        with patch("scripts.flow_workflow._find_stock_filler_clip", return_value=filler_path), \
             patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True, "duration": 5.0}):
            res = render_project(
                project_dir=prep["project_dir"],
                dry_run=True,
                flow_failure_policy="fallback_stock",
            )
            self.assertEqual(res["status"], "DRY_RUN_SUCCESS")
            self.assertEqual(res["instructions"][0]["source"], "stock_fallback")
            self.assertEqual(res["instructions"][0]["material_path"], filler_path)

    def test_ambiguous_post_consumption_needs_recovery(self):
        """10. Falha pós-consumo (aprovação/geração confirmada) => FLOW_GENERATION_NEEDS_RECOVERY sem retry cego."""
        prep = prepare_project(
            script_text="Cena com timeout após consumo.",
            project_name="recovery_test",
            base_dir=self.test_dir,
            flow_scenes=[1],
        )

        with patch("scripts.flow_playwright.run_playwright_flow_poc") as mock_poc:
            mock_poc.return_value = {
                "status": "DOWNLOAD_FAILED",
                "error": "DOWNLOAD_FAILED",
                "credit_approval_confirmed": True,
                "generation_start_confirmed": True,
                "credit_cost": 15,
            }
            res = generate_flow_scene(manifest_path=prep["manifest_path"], scene_index=1)
            self.assertEqual(res.status, "FLOW_GENERATION_NEEDS_RECOVERY")
            self.assertEqual(res.credits_consumed, 15)

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": False}), \
             patch("scripts.flow_workflow.generate_flow_scene") as mock_gen:
            mock_gen.return_value = FlowSceneResult(
                status="FLOW_GENERATION_NEEDS_RECOVERY",
                scene_index=1,
                credits_consumed=15,
                error="DOWNLOAD_FAILED",
            )
            pending_res = generate_pending_flow_scenes(manifest_path=prep["manifest_path"])
            self.assertEqual(pending_res["status"], "FLOW_GENERATION_NEEDS_RECOVERY")

            with open(prep["manifest_path"], "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
            self.assertEqual(manifest_data["flow_generation"]["status"], "FLOW_GENERATION_NEEDS_RECOVERY")

    def test_recovery_guard_blocks_when_last_scene_clip_missing(self):
        """1. recovery status + last_scene sem arquivo => continua bloqueado, zero geração."""
        prep = prepare_project(
            script_text="Cena 1. Cena 2.",
            project_name="rec_missing_test",
            base_dir=self.test_dir,
            flow_scenes=[1, 2],
        )
        update_manifest_flow_checkpoint(
            prep["manifest_path"],
            status="FLOW_GENERATION_NEEDS_RECOVERY",
            last_scene=2,
            completed_scenes=[1],
        )
        with patch("scripts.flow_workflow.generate_flow_scene") as mock_gen:
            res = generate_pending_flow_scenes(manifest_path=prep["manifest_path"])
            self.assertEqual(res["status"], "FLOW_GENERATION_NEEDS_RECOVERY")
            mock_gen.assert_not_called()

    def test_recovery_guard_blocks_when_last_scene_clip_invalid(self):
        """2. recovery status + last_scene com arquivo inválido => continua bloqueado, zero geração."""
        prep = prepare_project(
            script_text="Cena 1. Cena 2.",
            project_name="rec_invalid_test",
            base_dir=self.test_dir,
            flow_scenes=[1, 2],
        )
        update_manifest_flow_checkpoint(
            prep["manifest_path"],
            status="FLOW_GENERATION_NEEDS_RECOVERY",
            last_scene=2,
            completed_scenes=[1],
        )
        clip2_path = os.path.join(prep["clips_dir"], "flow_scene_02.mp4")
        with open(clip2_path, "wb") as f:
            f.write(b"corrupted")

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": False}), \
             patch("scripts.flow_workflow.generate_flow_scene") as mock_gen:
            res = generate_pending_flow_scenes(manifest_path=prep["manifest_path"])
            self.assertEqual(res["status"], "FLOW_GENERATION_NEEDS_RECOVERY")
            mock_gen.assert_not_called()

    def test_recovery_reconciles_when_last_scene_clip_valid_and_continues(self):
        """3. recovery status + last_scene com arquivo canônico válido => reconcilia completed_scenes, não regenera cena recuperada e continua para próxima."""
        prep = prepare_project(
            script_text="Cena 1. Cena 2. Cena 3.",
            project_name="rec_valid_test",
            base_dir=self.test_dir,
            flow_scenes=[1, 2, 3],
        )
        with open(prep["manifest_path"], "r", encoding="utf-8") as f:
            manifest_obj = json.load(f)
        manifest_obj["scenes"] = [
            {"scene_index": 1, "expected_clip": "flow_scene_01.mp4", "is_flow_premium": True, "narration": "Cena 1"},
            {"scene_index": 2, "expected_clip": "flow_scene_02.mp4", "is_flow_premium": True, "narration": "Cena 2"},
            {"scene_index": 3, "expected_clip": "flow_scene_03.mp4", "is_flow_premium": True, "narration": "Cena 3"},
        ]
        with open(prep["manifest_path"], "w", encoding="utf-8") as f:
            json.dump(manifest_obj, f)

        update_manifest_flow_checkpoint(
            prep["manifest_path"],
            status="FLOW_GENERATION_NEEDS_RECOVERY",
            last_scene=2,
            completed_scenes=[1],
        )
        clip1_path = os.path.join(prep["clips_dir"], "flow_scene_01.mp4")
        clip2_path = os.path.join(prep["clips_dir"], "flow_scene_02.mp4")
        with open(clip1_path, "wb") as f:
            f.write(b"valid1")
        with open(clip2_path, "wb") as f:
            f.write(b"valid2")

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True, "duration": 8.0}), \
             patch("scripts.flow_workflow.generate_flow_scene") as mock_gen:
            mock_gen.return_value = FlowSceneResult(
                status="SUCCESS",
                scene_index=3,
                output_file=os.path.join(prep["clips_dir"], "flow_scene_03.mp4"),
                output_valid=True,
                duration=8.0,
                credits_consumed=15,
            )
            res = generate_pending_flow_scenes(manifest_path=prep["manifest_path"])

            # Cena 3 foi gerada, mas cenas 1 e 2 NÃO foram regeneradas
            self.assertEqual(mock_gen.call_count, 1)
            self.assertEqual(mock_gen.call_args[1]["scene_index"], 3)

            with open(prep["manifest_path"], "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
            self.assertIn(1, manifest_data["flow_generation"]["completed_scenes"])
            self.assertIn(2, manifest_data["flow_generation"]["completed_scenes"])
            self.assertIn(3, manifest_data["flow_generation"]["completed_scenes"])

    def test_recovery_reconciliation_exact_scenario_completed_1_last_2_next_5(self):
        """4. completed_scenes=[1], last_scene=2, clips 1 e 2 válidos => resultado reconciliado contém [1,2], próxima geração solicitada é cena 5."""
        prep = prepare_project(
            script_text="Cena 1. Cena 2. Cena 5.",
            project_name="rec_production_scenario_test",
            base_dir=self.test_dir,
            flow_scenes=[1, 2, 5],
        )
        with open(prep["manifest_path"], "r", encoding="utf-8") as f:
            manifest_obj = json.load(f)
        manifest_obj["scenes"] = [
            {"scene_index": 1, "expected_clip": "flow_scene_01.mp4", "is_flow_premium": True, "narration": "Cena 1"},
            {"scene_index": 2, "expected_clip": "flow_scene_02.mp4", "is_flow_premium": True, "narration": "Cena 2"},
            {"scene_index": 5, "expected_clip": "flow_scene_05.mp4", "is_flow_premium": True, "narration": "Cena 5"},
        ]
        with open(prep["manifest_path"], "w", encoding="utf-8") as f:
            json.dump(manifest_obj, f)

        update_manifest_flow_checkpoint(
            prep["manifest_path"],
            status="FLOW_GENERATION_NEEDS_RECOVERY",
            last_scene=2,
            completed_scenes=[1],
        )
        clip1_path = os.path.join(prep["clips_dir"], "flow_scene_01.mp4")
        clip2_path = os.path.join(prep["clips_dir"], "flow_scene_02.mp4")
        with open(clip1_path, "wb") as f:
            f.write(b"clip1")
        with open(clip2_path, "wb") as f:
            f.write(b"clip2")

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True, "duration": 8.0}), \
             patch("scripts.flow_workflow.generate_flow_scene") as mock_gen:
            mock_gen.return_value = FlowSceneResult(
                status="SUCCESS",
                scene_index=5,
                output_file=os.path.join(prep["clips_dir"], "flow_scene_05.mp4"),
                output_valid=True,
                duration=8.0,
                credits_consumed=15,
            )
            res = generate_pending_flow_scenes(manifest_path=prep["manifest_path"])

            # Apenas cena 5 deve ser solicitada para geração
            mock_gen.assert_called_once()
            self.assertEqual(mock_gen.call_args[1]["scene_index"], 5)

            # Cenas 1 e 2 foram ALREADY_COMPLETE
            results = res["results"]
            c1_res = next((r for r in results if r["scene_index"] == 1), None)
            c2_res = next((r for r in results if r["scene_index"] == 2), None)
            c5_res = next((r for r in results if r["scene_index"] == 5), None)
            self.assertEqual(c1_res["status"], "ALREADY_COMPLETE")
            self.assertEqual(c2_res["status"], "ALREADY_COMPLETE")
            self.assertEqual(c5_res["status"], "SUCCESS")

    def test_recovery_all_scenes_valid_results_in_complete_zero_browser(self):
        """5. Se todas as cenas Flow já tiverem arquivos válidos => status COMPLETE, zero browser, zero créditos."""
        prep = prepare_project(
            script_text="Cena 1. Cena 2.",
            project_name="rec_all_valid_test",
            base_dir=self.test_dir,
            flow_scenes=[1, 2],
        )
        with open(prep["manifest_path"], "r", encoding="utf-8") as f:
            manifest_obj = json.load(f)
        manifest_obj["scenes"] = [
            {"scene_index": 1, "expected_clip": "flow_scene_01.mp4", "is_flow_premium": True, "narration": "Cena 1"},
            {"scene_index": 2, "expected_clip": "flow_scene_02.mp4", "is_flow_premium": True, "narration": "Cena 2"},
        ]
        with open(prep["manifest_path"], "w", encoding="utf-8") as f:
            json.dump(manifest_obj, f)

        update_manifest_flow_checkpoint(
            prep["manifest_path"],
            status="FLOW_GENERATION_NEEDS_RECOVERY",
            last_scene=2,
            completed_scenes=[1],
        )
        clip1_path = os.path.join(prep["clips_dir"], "flow_scene_01.mp4")
        clip2_path = os.path.join(prep["clips_dir"], "flow_scene_02.mp4")
        with open(clip1_path, "wb") as f:
            f.write(b"clip1")
        with open(clip2_path, "wb") as f:
            f.write(b"clip2")

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True, "duration": 8.0}), \
             patch("scripts.flow_workflow.generate_flow_scene") as mock_gen:
            res = generate_pending_flow_scenes(manifest_path=prep["manifest_path"])
            self.assertEqual(res["status"], "COMPLETE")
            mock_gen.assert_not_called()

            with open(prep["manifest_path"], "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
            self.assertEqual(manifest_data["flow_generation"]["status"], "COMPLETE")
            self.assertEqual(manifest_data["flow_generation"]["completed_scenes"], [1, 2])

    def test_status_distinguishes_flow_vs_stock(self):
        """11. get_project_status distingue READY_FLOW, READY_STOCK, PENDING_FLOW."""
        manifest_path = os.path.join(self.test_dir, "manifest.json")
        clips_dir = os.path.join(self.test_dir, "clips")
        os.makedirs(clips_dir, exist_ok=True)

        manifest = {
            "project_name": "mixed_status_test",
            "scenes": [
                {"scene_index": 1, "expected_clip": "flow_scene_01.mp4", "is_flow_premium": True, "narration": "A"},
                {"scene_index": 2, "expected_clip": "stock_scene_02.mp4", "is_flow_premium": False, "narration": "B"},
                {"scene_index": 3, "expected_clip": "flow_scene_03.mp4", "is_flow_premium": True, "narration": "C"},
                {"scene_index": 4, "expected_clip": "stock_scene_04.mp4", "is_flow_premium": False, "narration": "D"},
            ]
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f)

        # Cria mock dos arquivos para cena 1 (flow) e cena 2 (stock)
        with open(os.path.join(clips_dir, "flow_scene_01.mp4"), "wb") as f:
            f.write(b"\x00" * 1024)
        with open(os.path.join(clips_dir, "stock_scene_02.mp4"), "wb") as f:
            f.write(b"\x00" * 1024)

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True, "duration": 5.0}):
            status_info = get_project_status(self.test_dir)
            self.assertEqual(status_info["ready_flow_clips"], 1)
            self.assertEqual(status_info["ready_stock_clips"], 1)
            self.assertEqual(status_info["scenes"][0]["status"], "READY_FLOW")
            self.assertEqual(status_info["scenes"][1]["status"], "READY_STOCK")
            self.assertEqual(status_info["scenes"][2]["status"], "PENDING_FLOW")
            self.assertEqual(status_info["scenes"][3]["status"], "MISSING (STOCK_FALLBACK)")

    def test_mp4_size_gt_zero_but_invalid_does_not_become_ready_flow(self):
        """12. MP4 com size > 0 mas validate_clip_file=False não vira READY_FLOW e sim INVALID_FLOW."""
        manifest_path = os.path.join(self.test_dir, "manifest.json")
        clips_dir = os.path.join(self.test_dir, "clips")
        os.makedirs(clips_dir, exist_ok=True)

        manifest = {
            "project_name": "invalid_clip_test",
            "scenes": [
                {"scene_index": 1, "expected_clip": "flow_scene_01.mp4", "is_flow_premium": True, "narration": "A"}
            ],
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f)

        clip_path = os.path.join(clips_dir, "flow_scene_01.mp4")
        with open(clip_path, "wb") as f:
            f.write(b"corrupted_video_header_payload")

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": False, "error": "moov atom missing"}):
            status = get_project_status(self.test_dir)
            self.assertEqual(status["ready_flow_clips"], 0)
            self.assertEqual(status["invalid_flow_clips"], 1)
            self.assertEqual(status["scenes"][0]["status"], "INVALID_FLOW")
            self.assertFalse(status["scenes"][0]["is_valid"])

    def test_render_strict_rejects_invalid_flow_clip(self):
        """13. Render strict bloqueia com erro explícito INVALID_FLOW_CLIP quando clipe existe porém é inválido."""
        prep = prepare_project(
            script_text="Cena flow com clipe corrompido.",
            project_name="strict_invalid_test",
            base_dir=self.test_dir,
            flow_scenes=[1],
        )
        clip_path = os.path.join(prep["clips_dir"], "flow_scene_01.mp4")
        with open(clip_path, "wb") as f:
            f.write(b"truncated_clip")

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": False, "error": "truncated"}):
            with self.assertRaises(RuntimeError) as ctx:
                render_project(
                    project_dir=prep["project_dir"],
                    dry_run=True,
                    flow_failure_policy="strict",
                )
            self.assertIn("INVALID_FLOW_CLIP", str(ctx.exception))

    def test_fallback_stock_accepts_invalid_flow_when_no_recovery_pending(self):
        """14. Render com fallback_stock permite stock quando clipe é inválido e nenhum recovery está pendente."""
        prep = prepare_project(
            script_text="Cena flow com clipe corrompido aceita fallback.",
            project_name="fallback_invalid_test",
            base_dir=self.test_dir,
            flow_scenes=[1],
        )
        clip_path = os.path.join(prep["clips_dir"], "flow_scene_01.mp4")
        with open(clip_path, "wb") as f:
            f.write(b"truncated_clip")

        filler_path = os.path.join(self.test_dir, "filler.mp4")
        with open(filler_path, "wb") as f:
            f.write(b"valid_filler_bytes")

        def mock_validate(path):
            if path == filler_path:
                return {"valid": True, "duration": 5.0}
            return {"valid": False, "error": "corrupted"}

        with patch("scripts.flow_workflow._find_stock_filler_clip", return_value=filler_path), \
             patch("scripts.flow_workflow.validate_clip_file", side_effect=mock_validate):
            res = render_project(
                project_dir=prep["project_dir"],
                dry_run=True,
                flow_failure_policy="fallback_stock",
            )
            self.assertEqual(res["status"], "DRY_RUN_SUCCESS")
            self.assertEqual(res["instructions"][0]["source"], "stock_fallback")
            self.assertEqual(res["instructions"][0]["material_path"], filler_path)

    def test_needs_recovery_not_masked_by_fallback_stock(self):
        """15. FLOW_GENERATION_NEEDS_RECOVERY não é mascarado silenciosamente por fallback_stock no render."""
        prep = prepare_project(
            script_text="Cena flow que requer recovery.",
            project_name="needs_recovery_render_test",
            base_dir=self.test_dir,
            flow_scenes=[1],
        )
        update_manifest_flow_checkpoint(
            prep["manifest_path"],
            status="FLOW_GENERATION_NEEDS_RECOVERY",
            completed_scenes=[],
        )

        with self.assertRaises(RuntimeError) as ctx:
            render_project(
                project_dir=prep["project_dir"],
                dry_run=True,
                flow_failure_policy="fallback_stock",
            )
        self.assertIn("FLOW_GENERATION_NEEDS_RECOVERY", str(ctx.exception))

    def test_atomic_checkpoint_preserves_valid_json(self):
        """16. atomic_write_json escreve JSON UTF-8 válido e íntegro."""
        from app.services.task_artifacts import atomic_write_json

        manifest_path = os.path.join(self.test_dir, "atomic_manifest.json")
        payload = {"project_name": "atomic_test", "scenes": [1, 2, 3], "status": "COMPLETE"}
        atomic_write_json(manifest_path, payload)

        self.assertTrue(os.path.exists(manifest_path))
        with open(manifest_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        self.assertEqual(loaded, payload)

    def test_atomic_write_uses_tempfile_and_os_replace(self):
        """17. atomic_write_json cria tempfile no mesmo diretório e executa os.replace ao final."""
        from app.services.task_artifacts import atomic_write_json

        manifest_path = os.path.join(self.test_dir, "replace_manifest.json")
        payload = {"key": "value"}

        replaced_args = []
        original_replace = os.replace

        def mock_replace(src, dst):
            replaced_args.append((src, dst))
            original_replace(src, dst)

        with patch("os.replace", side_effect=mock_replace):
            atomic_write_json(manifest_path, payload)

        self.assertEqual(len(replaced_args), 1)
        src, dst = replaced_args[0]
        self.assertEqual(os.path.abspath(dst), os.path.abspath(manifest_path))
        self.assertEqual(os.path.dirname(os.path.abspath(src)), os.path.abspath(self.test_dir))
        self.assertTrue(os.path.basename(src).endswith(".tmp"))

    def test_atomic_write_failure_preserves_previous_manifest(self):
        """18. Falha antes de os.replace mantém arquivo anterior intocado e limpa tempfile."""
        from app.services.task_artifacts import atomic_write_json

        manifest_path = os.path.join(self.test_dir, "safe_manifest.json")
        original_payload = {"version": 1, "state": "ORIGINAL"}
        atomic_write_json(manifest_path, original_payload)

        with patch("os.fsync", side_effect=IOError("Simulated disk fsync crash")):
            with self.assertRaises(IOError):
                atomic_write_json(manifest_path, {"version": 2, "state": "CORRUPTED"})

        # Arquivo original deve permanecer inalterado
        with open(manifest_path, "r", encoding="utf-8") as f:
            current = json.load(f)
        self.assertEqual(current, original_payload)

        # Nenhum arquivo temporário .tmp residual deve permanecer
        tmp_files = [f for f in os.listdir(self.test_dir) if f.endswith(".tmp")]
        self.assertEqual(len(tmp_files), 0)


if __name__ == "__main__":
    unittest.main()


