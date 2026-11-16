"""
test/services/test_flow_sem_credito_limpo.py
============================================
Testes direcionados da Missão v2/flow-sem-credito-limpo:
(a) Pool sem créditos não dispara TypeError ao construir FlowSceneResult
    (nem em account_info ausente, nem no failover pré-dispatch),
    e propaga INSUFFICIENT_POOL_CREDITS de forma limpa até flow_workflow /
    flow_bridge (mesmo com stock_fallback_enabled=True) / task._mark_task_failed.
(b) No ciclo autônomo, falha com INSUFFICIENT_POOL_CREDITS classifica como
    STATE_BLOCKED (reason="flow_creditos_insuficientes"), NÃO entra em loop de erro,
    NÃO incrementa consecutive_rejections, e reembolsa a tentativa nas contagens 24h
    de autonomous_production, operator_console e production_diagnostics.
(c) Ciclos subsequentes permanecem bloqueados sem criar nova tarefa ou tentar
    abertura de navegador até que o saldo/estado do pool ou flow_scene_count mude.
(d) visual_director.direct_scenes reutiliza GEMINI_RETRY_DELAYS_SECONDS /
    _is_gemini_transient_error de app.services.llm para 503 UNAVAILABLE e falha
    imediato em erro 400 não transitório.
"""

from datetime import datetime, timedelta, timezone
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, call, patch

from app.models import const
from app.models.schema import ScenePlanItem, VideoParams
from app.services import autonomous_production as ap
from app.services import flow_account_pool as fap
from app.services import flow_bridge
from app.services import operator_console as op_con
from app.services import production_diagnostics as prod_diag
from app.services import profile_manager as pm
from app.services import scheduler
from app.services import state as sm
from app.services import scene_planner
from app.services import task as task_svc
from app.services import visual_director as vd
from app.services.llm import GEMINI_RETRY_DELAYS_SECONDS
from scripts import flow_playwright, flow_workflow


class _InMemoryTaskState:
    """Stub isolado de sm.state para não tocar em storage/tasks real."""

    def __init__(self):
        self._tasks = {}

    def get_task(self, task_id):
        data = self._tasks.get(task_id)
        return dict(data) if data is not None else None

    def update_task(self, task_id, **kwargs):
        cur = self._tasks.setdefault(task_id, {"task_id": task_id, "state": const.TASK_STATE_PROCESSING})
        cur.update(kwargs)
        return dict(cur)


class TestFlowSemCreditoLimpo(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.test_dir, "flow_accounts.json")
        self.runtime_path = os.path.join(self.test_dir, "flow_accounts_runtime.json")
        self.db_path = os.path.join(self.test_dir, "factory.sqlite")
        self.task_base_dir = os.path.join(self.test_dir, "tasks")
        os.makedirs(self.task_base_dir, exist_ok=True)

        self.mock_config = {
            "schema_version": 1,
            "accounts": [
                {
                    "account_id": "flow-primary",
                    "display_name": "Flow Primary",
                    "enabled": True,
                    "priority": 100,
                    "user_data_dir": os.path.join(self.test_dir, "p1"),
                },
                {
                    "account_id": "flow-b",
                    "display_name": "Conta B",
                    "enabled": True,
                    "priority": 90,
                    "user_data_dir": os.path.join(self.test_dir, "p2"),
                },
            ],
        }
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.mock_config, f)

        scheduler.init_db(self.db_path)
        op_con.init_operator_db(self.db_path)
        pm.init_profile_db(self.db_path)
        default_prof = pm.ensure_default_profile(db_path=self.db_path)
        self.profile_id = default_prof["id"]

        # Configurar perfil padrão com Flow ativo e voz pt-BR válida
        settings = pm.get_profile_settings(self.profile_id, db_path=self.db_path)
        settings.visual.flow_enabled = True
        settings.visual.flow_scene_count = 6
        settings.voice.voice_name = "pt-BR-AntonioNeural"
        settings.automation.target_ready_stock = 3
        pm.update_profile_settings(self.profile_id, settings, db_path=self.db_path)

        ap.set_autonomous_setting(ap.KEY_AUTONOMOUS_ENABLED, "True", db_path=self.db_path)
        ap.set_autonomous_setting(ap.KEY_AUTONOMOUS_TARGET_STOCK, "3", db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_manifest(self, task_id: str, scenes_count: int = 6) -> str:
        tdir = os.path.join(self.task_base_dir, task_id)
        flow_dir = os.path.join(tdir, "flow_clips")
        os.makedirs(flow_dir, exist_ok=True)
        manifest_path = os.path.join(tdir, "flow_manifest.json")
        manifest = {
            "task_id": task_id,
            "video_subject": "Tema Teste Flow",
            "scenes": [
                {
                    "scene_index": i,
                    "prompt_en": f"Vertical 9:16 scene {i}",
                    "is_flow_premium": True,
                }
                for i in range(1, scenes_count + 1)
            ],
            "flow_generation": {
                "status": "PENDING",
                "completed_scenes": [],
            },
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f)
        return manifest_path

    # ------------------------------------------------------------------
    # (a) Sem TypeError no FlowSceneResult & propagação limpa até a task
    # ------------------------------------------------------------------

    def test_a1_flow_playwright_no_account_returns_clean_result_no_typeerror(self):
        manifest_path = self._create_manifest("task-a1", scenes_count=6)
        fap.record_verified_credit_balance("flow-primary", 52, runtime_path=self.runtime_path)
        fap.record_verified_credit_balance("flow-b", 50, runtime_path=self.runtime_path)

        with patch("app.services.flow_account_pool.DEFAULT_CONFIG_PATH", self.config_path), \
             patch("app.services.flow_account_pool.DEFAULT_RUNTIME_PATH", self.runtime_path):
            res = flow_playwright.generate_flow_scene(
                manifest_path=manifest_path,
                scene_index=1,
            )

        self.assertIsInstance(res, flow_playwright.FlowSceneResult)
        self.assertEqual(res.status, "FAILED")
        self.assertIsNone(res.output_file)
        self.assertFalse(res.output_valid)
        self.assertIn("INSUFFICIENT_POOL_CREDITS", res.error or "")
        self.assertEqual(res.details.get("error_code"), "INSUFFICIENT_POOL_CREDITS")
        self.assertTrue(res.details.get("pool_insufficient"))
        self.assertEqual(res.details.get("required_credits"), 90)

    def test_a2_flow_playwright_predispatch_reconcile_failover_exhausted_no_typeerror(self):
        manifest_path = self._create_manifest("task-a2", scenes_count=6)
        # Conta stale Tier 3 com leitura antiga < 90; ao reconciliar permanece 52 < 90
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        fap.update_account_runtime(
            "flow-primary",
            {
                "status": fap.STATUS_AVAILABLE,
                "credits_remaining": 40,
                "credits_source": fap.CREDIT_SOURCE_LOCAL_ESTIMATE,
                "credits_last_verified_at": old_ts,
            },
            runtime_path=self.runtime_path,
        )
        # Segunda conta já verificada com saldo insuficiente (Tier 4 -> failover retorna None)
        fap.record_verified_credit_balance("flow-b", 50, runtime_path=self.runtime_path)

        def _fake_refresh(account_id, force=False, runtime_path=None):
            fap.record_verified_credit_balance(account_id, 52, runtime_path=self.runtime_path)
            return {
                "success": True,
                "ok": True,
                "credits_remaining": 52,
                "status": fap.STATUS_LOW_CREDITS,
            }

        with patch("app.services.flow_account_pool.DEFAULT_CONFIG_PATH", self.config_path), \
             patch("app.services.flow_account_pool.DEFAULT_RUNTIME_PATH", self.runtime_path), \
             patch("app.services.flow_account_pool.refresh_account_credits", side_effect=_fake_refresh), \
             patch("scripts.flow_playwright.run_playwright_flow_poc") as mock_poc:
            res = flow_playwright.generate_flow_scene(
                manifest_path=manifest_path,
                scene_index=1,
            )

        mock_poc.assert_not_called()
        self.assertIsInstance(res, flow_playwright.FlowSceneResult)
        self.assertEqual(res.status, "FAILED")
        self.assertIsNone(res.output_file)
        self.assertIn("INSUFFICIENT_POOL_CREDITS", res.error or "")
        self.assertEqual(res.details.get("error_code"), "INSUFFICIENT_POOL_CREDITS")
        self.assertTrue(res.details.get("pool_insufficient"))
        self.assertEqual(res.details.get("account_id"), "flow-primary")
        self.assertEqual(res.details.get("credits_remaining"), 52)
        self.assertEqual(res.details.get("required_credits"), 90)

    def test_a3_workflow_and_bridge_abort_cleanly_even_with_stock_fallback(self):
        task_id = "task-a3"
        manifest_path = self._create_manifest(task_id, scenes_count=3)
        fap.record_verified_credit_balance("flow-primary", 10, runtime_path=self.runtime_path)
        fap.record_verified_credit_balance("flow-b", 10, runtime_path=self.runtime_path)

        # Workflow deve abortar na 1ª cena sem tentar gerar todas as cenas
        with patch("app.services.flow_account_pool.DEFAULT_CONFIG_PATH", self.config_path), \
             patch("app.services.flow_account_pool.DEFAULT_RUNTIME_PATH", self.runtime_path), \
             patch("scripts.flow_workflow.generate_flow_scene", wraps=flow_playwright.generate_flow_scene) as spy_gen:
            gen_res = flow_workflow.generate_pending_flow_scenes(manifest_path=manifest_path)

        self.assertEqual(spy_gen.call_count, 1)
        self.assertEqual(gen_res.get("status"), "INSUFFICIENT_POOL_CREDITS")

        # Bridge com stock_fallback_enabled=True NÃO deve silenciar com stock nem dar TypeError
        bridge_task_dir = os.path.join(self.task_base_dir, task_id)
        bridge_flow_dir = os.path.join(bridge_task_dir, "flow")
        os.makedirs(bridge_flow_dir, exist_ok=True)
        bridge_manifest_path = os.path.join(bridge_flow_dir, "manifest.json")
        shutil.copyfile(manifest_path, bridge_manifest_path)

        params = VideoParams(
            video_subject="Tema Flow",
            flow_enabled=True,
            stock_fallback_enabled=True,
        )
        plan = scene_planner.ScenePlan(
            scenes=[
                ScenePlanItem(scene_index=1, narration="Cena 1."),
                ScenePlanItem(scene_index=2, narration="Cena 2."),
                ScenePlanItem(scene_index=3, narration="Cena 3."),
            ],
            total_scenes=3,
            script_hash="hash-test-a3",
        )
        with patch("app.services.flow_account_pool.DEFAULT_CONFIG_PATH", self.config_path), \
             patch("app.services.flow_account_pool.DEFAULT_RUNTIME_PATH", self.runtime_path), \
             patch("app.utils.utils.task_dir", return_value=bridge_task_dir), \
             patch("scripts.flow_workflow.prepare_project", return_value={"manifest_path": bridge_manifest_path, "scenes": []}):
            with self.assertRaises(flow_bridge.FlowInsufficientCreditsError) as ctx:
                flow_bridge.resolve_flow_materials_for_task(
                    task_id=task_id,
                    params=params,
                    video_script="Cena 1. Cena 2. Cena 3.",
                    scene_plan=plan,
                )
        self.assertEqual(getattr(ctx.exception, "reason_code", None), "INSUFFICIENT_POOL_CREDITS")

        # task._mark_task_failed persiste reason + error_code de forma estruturada
        fake_sm = _InMemoryTaskState()
        fake_sm.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=20)
        with patch.object(task_svc.sm, "state", fake_sm):
            reason = getattr(ctx.exception, "reason_code", "FLOW_MATERIAL_FAILED")
            fail_details = {"reason": reason}
            if reason != "FLOW_MATERIAL_FAILED":
                fail_details["error_code"] = reason
            task_svc._mark_task_failed(
                task_id,
                "materials",
                f"Flow material resolution failed: {ctx.exception}",
                details=fail_details,
            )
            persisted = fake_sm.get_task(task_id)
        self.assertEqual(persisted["state"], const.TASK_STATE_FAILED)
        self.assertEqual(persisted["failed_stage"], "materials")
        self.assertEqual(persisted["error_code"], "INSUFFICIENT_POOL_CREDITS")
        self.assertEqual(persisted["reason"], "INSUFFICIENT_POOL_CREDITS")

    # ------------------------------------------------------------------
    # (b) & (c) Ciclo autônomo: STATE_BLOCKED, reembolso 24h, sem retry cego
    # ------------------------------------------------------------------

    def test_bc_autonomous_cycle_reclassifies_refunds_24h_and_holds_until_pool_or_cost_changes(self):
        task_id = "task-flow-nocred-1"
        fake_sm = _InMemoryTaskState()
        fake_sm.update_task(
            task_id,
            state=const.TASK_STATE_FAILED,
            progress=15,
            failed_stage="materials",
            stage="materials",
            reason="INSUFFICIENT_POOL_CREDITS",
            error_code="INSUFFICIENT_POOL_CREDITS",
            error="Flow material resolution failed: INSUFFICIENT_POOL_CREDITS: Pool sem saldo.",
        )

        # Vincula task ao perfil e registra generation_started em operational_events
        pm.save_task_profile(task_id, self.profile_id, db_path=self.db_path)
        op_con.log_operational_event(
            component="autonomous_production",
            severity=op_con.SEVERITY_INFO,
            event_type="generation_started",
            task_id=task_id,
            message="Geração autônoma iniciada",
            db_path=self.db_path,
        )
        ap._set_cycle_setting(ap.KEY_AUTONOMOUS_CURRENT_TASK_ID, task_id, profile_id=self.profile_id, db_path=self.db_path)

        # Confirma que antes da reclassificação existia 1 tentativa contada nas últimas 24h
        now_dt = datetime.now(timezone.utc)
        self.assertEqual(
            ap.count_generation_attempts_in_last_24h(now=now_dt, db_path=self.db_path, profile_id=self.profile_id),
            1,
        )
        self.assertEqual(ap.count_all_profiles_attempts_24h(now=now_dt, db_path=self.db_path), 1)

        # Mantém 1 conta Tier-3 stale para provar que Guard 6 NÃO re-tenta cegamente
        old_ts = (now_dt - timedelta(hours=36)).isoformat()
        fap.update_account_runtime(
            "flow-primary",
            {
                "status": fap.STATUS_AVAILABLE,
                "credits_remaining": None,
                "credits_source": fap.CREDIT_SOURCE_UNKNOWN,
                "credits_last_verified_at": old_ts,
            },
            runtime_path=self.runtime_path,
        )
        fap.record_verified_credit_balance("flow-b", 52, runtime_path=self.runtime_path)

        with patch("app.services.flow_account_pool.DEFAULT_CONFIG_PATH", self.config_path), \
             patch("app.services.flow_account_pool.DEFAULT_RUNTIME_PATH", self.runtime_path), \
             patch("app.services.state.state", fake_sm), \
             patch("app.services.webui_task.has_active_generation_tasks", return_value=False), \
             patch("app.services.operator_console.reconcile_orphaned_tasks"), \
             patch("app.utils.utils.check_ffmpeg_ready", return_value=True), \
             patch("app.services.material.has_material_api_keys", return_value=True), \
             patch("shutil.disk_usage", return_value=(100, 50, 10 * (1024 ** 3))), \
             patch("app.models.llm_provider.get_llm_provider") as mock_llm_prov, \
             patch("app.services.voice.check_voice_availability", return_value=(True, "OK")), \
             patch("app.services.autonomous_production.discover_candidate_topic") as mock_discover, \
             patch("app.services.webui_task.submit_generation") as mock_submit:

            mock_spec = MagicMock()
            mock_spec.requires_api_key = False
            mock_llm_prov.return_value = mock_spec

            # Ciclo 1: trata task FAILED por INSUFFICIENT_POOL_CREDITS
            res1 = ap.run_autonomous_cycle(
                force=True,
                now=now_dt,
                db_path=self.db_path,
                profile_id=self.profile_id,
                task_base_dir=self.task_base_dir,
            )

            self.assertEqual(res1["status"], "blocked")
            self.assertEqual(res1["reason"], "flow_creditos_insuficientes")
            self.assertEqual(res1.get("task_id"), task_id)
            self.assertEqual(
                ap._get_cycle_setting(ap.KEY_AUTONOMOUS_STATE, None, profile_id=self.profile_id, db_path=self.db_path),
                ap.STATE_BLOCKED,
            )
            self.assertEqual(
                ap._get_cycle_setting(ap.KEY_AUTONOMOUS_CURRENT_TASK_ID, None, profile_id=self.profile_id, db_path=self.db_path),
                "",
            )
            self.assertEqual(ap.get_consecutive_rejections(db_path=self.db_path, profile_id=self.profile_id), 0)

            # (b) Tentativas 24h zeradas em TODAS as fontes (autonomous_production, operator_console, production_diagnostics)
            self.assertEqual(
                ap.count_generation_attempts_in_last_24h(now=now_dt, db_path=self.db_path, profile_id=self.profile_id),
                0,
            )
            self.assertEqual(ap.count_all_profiles_attempts_24h(now=now_dt, db_path=self.db_path), 0)

            fleet = op_con.get_fleet_summary(db_path=self.db_path, fresh=True)
            chan_summary = next(c for c in fleet["channels"] if c["profile_id"] == self.profile_id)
            self.assertEqual(chan_summary["attempts_24h"], 0)

            diag = prod_diag.get_diagnostics_overview(
                profile_id=self.profile_id,
                db_path=self.db_path,
                task_base_dir=self.task_base_dir,
                now=now_dt,
                fresh=True,
            )
            self.assertEqual(diag["limits"]["attempts_24h"]["used"], 0)
            chan_diag = next(c for c in diag["channels"] if c["profile_id"] == self.profile_id)
            self.assertEqual(chan_diag["limits"]["attempts_24h"]["used"], 0)
            self.assertEqual(chan_diag["counts_24h"]["started"], 0)
            gen_entry = next(g for g in chan_diag["recent_generations"] if g["task_id"] == task_id)
            self.assertEqual(gen_entry["outcome"], "BLOCKED")

            # (c1) Ciclos subsequentes (após 20min ou force=True) permanecem bloqueados sem re-tentar
            res2 = ap.run_autonomous_cycle(
                force=True,
                now=now_dt + timedelta(minutes=20),
                db_path=self.db_path,
                profile_id=self.profile_id,
                task_base_dir=self.task_base_dir,
            )
            res3 = ap.run_autonomous_cycle(
                force=True,
                now=now_dt + timedelta(minutes=40),
                db_path=self.db_path,
                profile_id=self.profile_id,
                task_base_dir=self.task_base_dir,
            )
            for res in (res2, res3):
                self.assertEqual(res["status"], "blocked")
                self.assertEqual(res["reason"], "flow_creditos_insuficientes")
            mock_discover.assert_not_called()
            mock_submit.assert_not_called()
            self.assertEqual(
                ap.count_generation_attempts_in_last_24h(now=now_dt, db_path=self.db_path, profile_id=self.profile_id),
                0,
            )

            # (c2) Quando o operador reduz flow_scene_count (6 -> 3 = 45 cr <= 52 cr da flow-b), desbloqueia!
            pm.update_profile_visual_settings(self.profile_id, {"flow_scene_count": 3}, db_path=self.db_path)
            mock_discover.return_value = {
                "topic": "Curiosidade GTA VI teste",
                "origin": "trend_radar",
                "trend_id": None,
            }
            res4 = ap.run_autonomous_cycle(
                force=True,
                now=now_dt + timedelta(minutes=45),
                db_path=self.db_path,
                profile_id=self.profile_id,
                task_base_dir=self.task_base_dir,
            )
            mock_discover.assert_called_once()
            mock_submit.assert_called_once()
            self.assertEqual(res4.get("status"), "generation_started")

    def test_c2_pool_credit_recharge_unblocks_without_changing_scene_count(self):
        now_dt = datetime.now(timezone.utc)
        fap.record_verified_credit_balance("flow-primary", 52, runtime_path=self.runtime_path)
        fap.record_verified_credit_balance("flow-b", 50, runtime_path=self.runtime_path)

        with patch("app.services.flow_account_pool.DEFAULT_CONFIG_PATH", self.config_path), \
             patch("app.services.flow_account_pool.DEFAULT_RUNTIME_PATH", self.runtime_path), \
             patch("app.services.webui_task.has_active_generation_tasks", return_value=False), \
             patch("app.services.operator_console.reconcile_orphaned_tasks"), \
             patch("app.utils.utils.check_ffmpeg_ready", return_value=True), \
             patch("app.services.material.has_material_api_keys", return_value=True), \
             patch("shutil.disk_usage", return_value=(100, 50, 10 * (1024 ** 3))), \
             patch("app.models.llm_provider.get_llm_provider") as mock_llm_prov, \
             patch("app.services.voice.check_voice_availability", return_value=(True, "OK")), \
             patch("app.services.autonomous_production.discover_candidate_topic") as mock_discover, \
             patch("app.services.webui_task.submit_generation") as mock_submit:

            mock_spec = MagicMock()
            mock_spec.requires_api_key = False
            mock_llm_prov.return_value = mock_spec

            # Ciclo 1: bloqueado pelo preflight (necessário 90 cr, máximo no pool 52 cr)
            r1 = ap.run_autonomous_cycle(
                force=True,
                now=now_dt,
                db_path=self.db_path,
                profile_id=self.profile_id,
                task_base_dir=self.task_base_dir,
            )
            self.assertEqual(r1["status"], "blocked")
            self.assertEqual(r1["reason"], "flow_creditos_insuficientes")

            # Ciclo 2: mesmo pool, mesmo custo -> permanece bloqueado via assinatura sem descobrir/submeter
            r2 = ap.run_autonomous_cycle(
                force=True,
                now=now_dt + timedelta(minutes=16),
                db_path=self.db_path,
                profile_id=self.profile_id,
                task_base_dir=self.task_base_dir,
            )
            self.assertEqual(r2["status"], "blocked")
            self.assertEqual(r2["reason"], "flow_creditos_insuficientes")
            mock_discover.assert_not_called()
            mock_submit.assert_not_called()

            # Saldo do pool sobe para 116 cr sem alterar flow_scene_count (6 cenas = 90 cr) -> desbloqueia!
            fap.record_verified_credit_balance("flow-primary", 116, runtime_path=self.runtime_path)
            mock_discover.return_value = {
                "topic": "Tema após recarga Flow",
                "origin": "trend_radar",
                "trend_id": None,
            }
            r3 = ap.run_autonomous_cycle(
                force=True,
                now=now_dt + timedelta(minutes=32),
                db_path=self.db_path,
                profile_id=self.profile_id,
                task_base_dir=self.task_base_dir,
            )
            mock_discover.assert_called_once()
            mock_submit.assert_called_once()
            self.assertEqual(r3.get("status"), "generation_started")

    # ------------------------------------------------------------------
    # (d) Retry transitório no visual_director reutilizando política de llm.py
    # ------------------------------------------------------------------

    @patch("app.services.visual_director.time.sleep")
    @patch("app.services.visual_director.get_gemini_config")
    def test_d1_visual_director_retries_503_unavailable_and_succeeds(self, mock_get_cfg, mock_sleep):
        mock_get_cfg.return_value = {
            "api_key": "dummy_key",
            "model_name": "gemini-3.5-flash-lite",
            "base_url": "",
        }
        valid_plan = {
            "video_subject": "Tema Teste",
            "global_style": "Dark moody documentary lighting",
            "continuity_rules": ["Vertical 9:16 portrait", "High contrast"],
            "scenes": [
                {
                    "scene_index": 1,
                    "subject": "Investigator at desk",
                    "action": "Examining a glowing map",
                    "environment": "Dimly lit office",
                    "lighting": "Cold blue monitor glow",
                    "style": "Cinematic documentary",
                    "camera_motion": "Slow push in",
                    "composition": "Medium close-up vertical 9:16",
                    "lens_focus": "Shallow depth of field",
                    "ambiance": "Floating dust motes",
                    "stock_search_terms": ["detective", "dark office"],
                    "visual_importance": "high",
                    "rationale": "Establishes suspense",
                }
            ],
        }
        ok_resp = MagicMock()
        ok_resp.text = json.dumps(valid_plan)

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = [
            RuntimeError("503 UNAVAILABLE: This model is currently experiencing high demand"),
            ok_resp,
        ]

        plan = vd.direct_scenes(
            scenes=[{"scene_index": 1, "narration": "O mistério começou à meia-noite."}],
            video_subject="Tema Teste",
            client=mock_client,
        )

        self.assertEqual(len(plan.scenes), 1)
        self.assertEqual(mock_client.models.generate_content.call_count, 2)
        mock_sleep.assert_called_once_with(GEMINI_RETRY_DELAYS_SECONDS[0])

    @patch("app.services.visual_director.time.sleep")
    @patch("app.services.visual_director.get_gemini_config")
    def test_d2_visual_director_exhausts_retries_and_fails_fast_on_400(self, mock_get_cfg, mock_sleep):
        mock_get_cfg.return_value = {
            "api_key": "dummy_key",
            "model_name": "gemini-3.5-flash-lite",
            "base_url": "",
        }

        # 1. Falha 503 em todas as tentativas -> 4 chamadas e sleeps (5, 15, 45)
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = RuntimeError("503 UNAVAILABLE")
        with self.assertRaises(RuntimeError) as ctx_503:
            vd.direct_scenes(
                scenes=[{"scene_index": 1, "narration": "Cena única."}],
                video_subject="Tema Teste",
                client=mock_client,
            )
        self.assertIn("VISUAL_DIRECTOR_FAILED", str(ctx_503.exception))
        self.assertEqual(mock_client.models.generate_content.call_count, 1 + len(GEMINI_RETRY_DELAYS_SECONDS))
        self.assertEqual(mock_sleep.call_args_list, [call(d) for d in GEMINI_RETRY_DELAYS_SECONDS])

        # 2. Erro 400 não transitório -> 1 tentativa, zero sleeps
        mock_sleep.reset_mock()
        mock_client_400 = MagicMock()
        mock_client_400.models.generate_content.side_effect = RuntimeError("400 Bad Request: Invalid schema")
        with self.assertRaises(RuntimeError) as ctx_400:
            vd.direct_scenes(
                scenes=[{"scene_index": 1, "narration": "Cena única."}],
                video_subject="Tema Teste",
                client=mock_client_400,
            )
        self.assertIn("VISUAL_DIRECTOR_FAILED", str(ctx_400.exception))
        self.assertEqual(mock_client_400.models.generate_content.call_count, 1)
        mock_sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
