"""Testes direcionados da missão v2/flow-fechar-avisos.

Cobre (Playwright totalmente mockado / fake pages, zero rede):
(1) Modal com botão "Entendi" é fechado e loga "[FLOW_MODAL_DISMISSED] rotulo=Entendi" (sem vazar conta/e-mail);
(2) Modal com botão "Upgrade"/"Assinar" NÃO é clicado (tenta Escape; se persistir levanta FlowBlockingModalError / FLOW_BLOCKING_MODAL);
(3) Sem modal: nenhuma ação extra (zero cliques, zero Escape, zero espera);
(4) "Projeto não encontrado" e "Project not found" levantam FlowProjectNotFoundError imediato em ensure_studio_surface;
(5) Sem cenas completas nem dispatch confirmado: flow_project_url limpo mantendo flow_account_id e UMA retentativa com force_new_project=True; se ainda falhar, grava status/error no manifesto e para sem repetir nas demais cenas;
(6) Com cena completa ou generation_start_confirmed/credit_approval_confirmed: NÃO limpa flow_project_url e NÃO recria projeto;
(7) A leitura de saldo (flow_account_pool.read_flow_credit_balance) reutiliza dismiss_flow_announcements antes de clicar no ícone da conta.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from typing import Any, Callable, Dict, List, Optional
from unittest.mock import MagicMock, patch

from app.services import flow_account_pool as fap
from scripts import flow_playwright as fp
from scripts import flow_workflow as fw


class FakeButton:
    def __init__(
        self,
        text: str = "",
        aria_label: Optional[str] = None,
        visible: bool = True,
        on_click: Optional[Callable[[], None]] = None,
    ):
        self._text = text
        self._aria_label = aria_label
        self.visible = visible
        self._on_click = on_click
        self.click_count = 0

    def is_visible(self) -> bool:
        return self.visible

    def inner_text(self) -> str:
        return self._text

    def text_content(self) -> str:
        return self._text

    def get_attribute(self, name: str) -> Optional[str]:
        if name == "aria-label":
            return self._aria_label
        return None

    def click(self, timeout: int = 2000, force: bool = False) -> None:
        self.click_count += 1
        if self._on_click:
            self._on_click()


class FakeLocatorList:
    def __init__(self, items: List[Any]):
        self._items = items

    def count(self) -> int:
        return len(self._items)

    def nth(self, idx: int) -> Any:
        return self._items[idx]

    @property
    def first(self) -> Any:
        return self._items[0] if self._items else FakeButton(visible=False)


class FakeDialog:
    def __init__(
        self,
        buttons: List[FakeButton],
        visible: bool = True,
        body_text: str = "",
    ):
        self.buttons = buttons
        self.visible = visible
        self.body_text = body_text

    def is_visible(self) -> bool:
        return self.visible

    def inner_text(self) -> str:
        return self.body_text

    def locator(self, selector: str) -> FakeLocatorList:
        if "button" in selector:
            return FakeLocatorList(self.buttons)
        return FakeLocatorList([])


class FakeKeyboard:
    def __init__(self, on_escape: Optional[Callable[[], None]] = None):
        self.pressed: List[str] = []
        self._on_escape = on_escape

    def press(self, key: str) -> None:
        self.pressed.append(key)
        if key == "Escape" and self._on_escape:
            self._on_escape()


class FakePage:
    def __init__(
        self,
        url: str = "https://labs.google/fx/tools/flow/project/test-proj",
        dialogs: Optional[List[FakeDialog]] = None,
        visible_texts: Optional[List[str]] = None,
        on_escape: Optional[Callable[[], None]] = None,
    ):
        self.url = url
        self.dialogs: List[FakeDialog] = dialogs or []
        self.visible_texts: List[str] = visible_texts or []
        self.keyboard = FakeKeyboard(on_escape=on_escape)
        self.waits: List[int] = []
        self.goto_calls: List[str] = []
        self.default_timeout: Optional[int] = None

    def set_default_timeout(self, ms: int) -> None:
        self.default_timeout = ms

    def goto(self, url: str) -> None:
        self.goto_calls.append(url)
        self.url = url

    def wait_for_load_state(self, state: str = "domcontentloaded") -> None:
        pass

    def wait_for_url(self, pattern: Any, timeout: int = 30000) -> None:
        pass

    def wait_for_timeout(self, ms: int) -> None:
        self.waits.append(ms)

    def locator(self, selector: str) -> Any:
        if "[role='dialog']" in selector and "[aria-modal='true']" in selector:
            return FakeLocatorList(self.dialogs)
        if selector.startswith("text="):
            target = selector[len("text="):]
            matched = [FakeButton(text=t, visible=True) for t in self.visible_texts if target.lower() in t.lower()]
            return FakeLocatorList(matched)
        if ".cdk-overlay-backdrop" in selector:
            return FakeLocatorList([])
        if "ProseMirror" in selector:
            return FakeButton(visible=False)
        return FakeLocatorList([])


class TestFlowFecharAvisos(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_flow_fechar_avisos_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_manifest(
        self,
        project_url: Optional[str] = "https://labs.google/fx/tools/flow/project/dead-proj-001",
        account_id: str = "flow-primary",
        completed_scenes: Optional[List[int]] = None,
        generation_start_confirmed: bool = False,
        credit_approval_confirmed: bool = False,
        num_scenes: int = 3,
    ) -> str:
        clips_dir = os.path.join(self.test_dir, "clips")
        os.makedirs(clips_dir, exist_ok=True)
        manifest_path = os.path.join(self.test_dir, "manifest.json")
        manifest: Dict[str, Any] = {
            "task_id": "task-flow-modal-test",
            "project_name": "flow_modal_test",
            "flow_account_id": account_id,
            "scenes": [
                {
                    "scene_index": i,
                    "expected_clip": f"flow_scene_{i:02d}.mp4",
                    "is_flow_premium": True,
                    "narration": f"Cena {i} teste",
                    "flow_prompt": f"Prompt cena {i}",
                }
                for i in range(1, num_scenes + 1)
            ],
            "flow_generation": {
                "completed_scenes": list(completed_scenes or []),
                "generation_start_confirmed": generation_start_confirmed,
                "credit_approval_confirmed": credit_approval_confirmed,
            },
        }
        if project_url is not None:
            manifest["flow_project_url"] = project_url
            manifest["flow_generation"]["project_url"] = project_url

        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        return manifest_path

    # ------------------------------------------------------------------
    # (1) Modal com botão "Entendi" é fechado e loga (sem vazar conta/e-mail)
    # ------------------------------------------------------------------
    def test_1_modal_entendi_is_dismissed_and_logged_without_account_leak(self):
        dialog_holder: Dict[str, FakeDialog] = {}

        def close_dialog():
            dialog_holder["dlg"].visible = False

        btn_entendi = FakeButton(text="Entendi", on_click=close_dialog)
        dlg = FakeDialog(
            buttons=[btn_entendi],
            visible=True,
            body_text="A faster, easier-to-reach Flow Agent — secret.user@example.com",
        )
        dialog_holder["dlg"] = dlg
        page = FakePage(dialogs=[dlg])

        logs: List[str] = []
        sink_id = fp.logger.add(lambda m: logs.append(str(m)))
        try:
            closed = fp.dismiss_flow_announcements(page)
        finally:
            fp.logger.remove(sink_id)

        self.assertEqual(closed, 1)
        self.assertEqual(btn_entendi.click_count, 1)
        self.assertFalse(dlg.visible)
        self.assertEqual(page.keyboard.pressed, [])
        joined = "\n".join(logs)
        self.assertIn("[FLOW_MODAL_DISMISSED] rotulo=Entendi", joined)
        self.assertNotIn("secret.user@example.com", joined)

    # ------------------------------------------------------------------
    # (2) Modal com "Upgrade"/"Assinar" NÃO é clicado (tenta Escape; se persistir -> FLOW_BLOCKING_MODAL)
    # ------------------------------------------------------------------
    def test_2_modal_upgrade_assinar_never_clicked_and_persistent_raises_blocking_modal(self):
        btn_upgrade = FakeButton(text="Upgrade")
        btn_assinar = FakeButton(text="Assinar plano")
        btn_credits = FakeButton(text="Continuar e comprar créditos")
        dlg = FakeDialog(
            buttons=[btn_upgrade, btn_assinar, btn_credits],
            visible=True,
            body_text="Faça upgrade do seu plano",
        )
        # Escape não fecha o modal persistente
        page = FakePage(dialogs=[dlg])

        with self.assertRaises(fp.FlowBlockingModalError) as ctx:
            fp.dismiss_flow_announcements(page)

        self.assertIn("FLOW_BLOCKING_MODAL", str(ctx.exception))
        # Nenhum botão proibido pode ter sido clicado
        self.assertEqual(btn_upgrade.click_count, 0)
        self.assertEqual(btn_assinar.click_count, 0)
        self.assertEqual(btn_credits.click_count, 0)
        # Tentou Escape exatamente 3 rodadas
        self.assertEqual(page.keyboard.pressed, ["Escape", "Escape", "Escape"])

    def test_2b_modal_upgrade_closed_by_escape_succeeds_without_clicking_forbidden(self):
        btn_upgrade = FakeButton(text="Upgrade")
        dlg = FakeDialog(buttons=[btn_upgrade], visible=True)

        def dismiss_on_escape():
            dlg.visible = False

        page = FakePage(dialogs=[dlg], on_escape=dismiss_on_escape)

        logs: List[str] = []
        sink_id = fp.logger.add(lambda m: logs.append(str(m)))
        try:
            closed = fp.dismiss_flow_announcements(page)
        finally:
            fp.logger.remove(sink_id)

        self.assertEqual(closed, 1)
        self.assertEqual(btn_upgrade.click_count, 0)
        self.assertEqual(page.keyboard.pressed, ["Escape"])
        self.assertTrue(any("[FLOW_MODAL_DISMISSED] rotulo=Escape" in line for line in logs))

    # ------------------------------------------------------------------
    # (3) Sem modal: nenhuma ação extra
    # ------------------------------------------------------------------
    def test_3_no_modal_performs_no_extra_action(self):
        page = FakePage(dialogs=[])
        closed = fp.dismiss_flow_announcements(page)

        self.assertEqual(closed, 0)
        self.assertEqual(page.keyboard.pressed, [])
        self.assertEqual(page.waits, [])

    # ------------------------------------------------------------------
    # (4) "Projeto não encontrado" / "Project not found" levanta FlowProjectNotFoundError imediato
    # ------------------------------------------------------------------
    def test_4_project_not_found_raises_immediately_without_waiting_30s(self):
        dead_url = "https://labs.google/fx/tools/flow/project/dead-999"

        for msg in ("Projeto não encontrado", "Project not found"):
            page = FakePage(url="https://labs.google/fx/tools/flow", visible_texts=[msg])
            with patch("scripts.flow_playwright.expect") as mock_expect:
                with self.assertRaises(fp.FlowProjectNotFoundError) as ctx:
                    fp.ensure_studio_surface(page, project_url=dead_url, timeout_ms=30000)

                self.assertIn("FLOW_PROJECT_NOT_FOUND", str(ctx.exception))
                self.assertEqual(page.goto_calls, [dead_url])
                # Não esperou 30s no expect(editor) nem fez sleeps
                mock_expect.assert_not_called()
                self.assertEqual(page.waits, [])

    # ------------------------------------------------------------------
    # (5) Sem cenas completas nem dispatch: limpa flow_project_url, mantém mesma conta e tenta UMA vez force_new_project
    # ------------------------------------------------------------------
    def test_5_recreates_project_once_on_same_account_when_no_completed_scenes(self):
        manifest_path = self._create_manifest(
            project_url="https://labs.google/fx/tools/flow/project/dead-001",
            account_id="flow-primary",
            completed_scenes=[],
            num_scenes=2,
        )
        new_project_url = "https://labs.google/fx/tools/flow/project/fresh-777"
        calls: List[Dict[str, Any]] = []

        def fake_generate_flow_scene(
            manifest_path: str,
            scene_index: int,
            project_url: Optional[str] = None,
            failure_policy: str = "strict",
            force_new_project: bool = False,
            **kwargs,
        ):
            with open(manifest_path, "r", encoding="utf-8") as f:
                snap = json.load(f)
            calls.append({
                "scene_index": scene_index,
                "project_url": project_url,
                "force_new_project": force_new_project,
                "manifest_project_url": snap.get("flow_project_url"),
                "manifest_account_id": snap.get("flow_account_id"),
            })
            if len(calls) == 1:
                return fp.FlowSceneResult(
                    status="FLOW_PROJECT_NOT_FOUND",
                    scene_index=scene_index,
                    project_url=project_url,
                    error="FLOW_PROJECT_NOT_FOUND: Projeto não encontrado",
                )
            return fp.FlowSceneResult(
                status="SUCCESS",
                scene_index=scene_index,
                output_file=os.path.join(self.test_dir, "clips", f"flow_scene_{scene_index:02d}.mp4"),
                output_valid=True,
                duration=8.0,
                credits_consumed=15,
                project_url=new_project_url,
            )

        with patch("scripts.flow_workflow.generate_flow_scene", side_effect=fake_generate_flow_scene):
            res = fw.generate_pending_flow_scenes(
                manifest_path=manifest_path,
                failure_policy="fallback_to_stock",
            )

        self.assertEqual(res["status"], "COMPLETE")
        self.assertEqual(res["project_url"], new_project_url)
        # Cena 1 tentou projeto morto -> limpou URL e retentou 1x com force_new_project=True -> Cena 2 reutilizou URL nova
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0]["scene_index"], 1)
        self.assertEqual(calls[0]["force_new_project"], False)
        self.assertEqual(calls[0]["manifest_account_id"], "flow-primary")

        self.assertEqual(calls[1]["scene_index"], 1)
        self.assertEqual(calls[1]["force_new_project"], True)
        self.assertIsNone(calls[1]["project_url"])
        self.assertIsNone(calls[1]["manifest_project_url"])
        self.assertEqual(calls[1]["manifest_account_id"], "flow-primary")

        self.assertEqual(calls[2]["scene_index"], 2)
        self.assertEqual(calls[2]["project_url"], new_project_url)
        self.assertEqual(calls[2]["force_new_project"], False)

        with open(manifest_path, "r", encoding="utf-8") as f:
            final_manifest = json.load(f)
        self.assertEqual(final_manifest["flow_account_id"], "flow-primary")
        self.assertEqual(final_manifest["flow_project_url"], new_project_url)

    def test_5b_retry_still_fails_stops_immediately_and_records_status_and_error_in_manifest(self):
        manifest_path = self._create_manifest(
            project_url="https://labs.google/fx/tools/flow/project/dead-002",
            account_id="flow-primary",
            completed_scenes=[],
            num_scenes=5,
        )
        calls: List[Dict[str, Any]] = []

        def always_not_found(manifest_path: str, scene_index: int, project_url: Optional[str] = None, force_new_project: bool = False, **kwargs):
            calls.append({"scene_index": scene_index, "force_new_project": force_new_project})
            return fp.FlowSceneResult(
                status="FLOW_PROJECT_NOT_FOUND",
                scene_index=scene_index,
                project_url=project_url,
                error="FLOW_PROJECT_NOT_FOUND: Projeto morto persistente",
            )

        with patch("scripts.flow_workflow.generate_flow_scene", side_effect=always_not_found):
            res = fw.generate_pending_flow_scenes(
                manifest_path=manifest_path,
                failure_policy="fallback_to_stock",
            )

        # Apenas 2 chamadas na cena 1 (original + 1 retentativa force_new_project) e NÃO repete cenas 2..5
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], {"scene_index": 1, "force_new_project": False})
        self.assertEqual(calls[1], {"scene_index": 1, "force_new_project": True})
        self.assertEqual(res["status"], "FLOW_PROJECT_NOT_FOUND")

        with open(manifest_path, "r", encoding="utf-8") as f:
            final_manifest = json.load(f)
        self.assertEqual(final_manifest["flow_account_id"], "flow-primary")
        self.assertNotIn("flow_project_url", final_manifest)
        self.assertEqual(final_manifest["flow_generation"]["status"], "FLOW_PROJECT_NOT_FOUND")
        self.assertIn("FLOW_PROJECT_NOT_FOUND", final_manifest["flow_generation"]["error"])

    # ------------------------------------------------------------------
    # (6) Com cena completa ou generation_start_confirmed: NÃO limpa e NÃO recria
    # ------------------------------------------------------------------
    def test_6a_with_completed_scene_does_not_clear_project_url_or_recreate(self):
        dead_url = "https://labs.google/fx/tools/flow/project/partial-123"
        manifest_path = self._create_manifest(
            project_url=dead_url,
            account_id="flow-primary",
            completed_scenes=[1],
            num_scenes=3,
        )
        # Cena 1 já concluída no disco
        clip1 = os.path.join(self.test_dir, "clips", "flow_scene_01.mp4")
        with open(clip1, "wb") as f:
            f.write(b"valid-clip-1")

        calls: List[Dict[str, Any]] = []

        def fake_gen(manifest_path: str, scene_index: int, project_url: Optional[str] = None, force_new_project: bool = False, **kwargs):
            calls.append({"scene_index": scene_index, "project_url": project_url, "force_new_project": force_new_project})
            return fp.FlowSceneResult(
                status="FLOW_PROJECT_NOT_FOUND",
                scene_index=scene_index,
                project_url=project_url,
                error="FLOW_PROJECT_NOT_FOUND: Projeto não encontrado na cena 2",
            )

        def fake_validate(path: str):
            return {"valid": True, "duration": 8.0} if "01" in path else {"valid": False}

        with patch("scripts.flow_workflow.validate_clip_file", side_effect=fake_validate), \
             patch("scripts.flow_workflow.generate_flow_scene", side_effect=fake_gen):
            res = fw.generate_pending_flow_scenes(
                manifest_path=manifest_path,
                failure_policy="fallback_to_stock",
            )

        self.assertEqual(res["status"], "FLOW_PROJECT_NOT_FOUND")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["scene_index"], 2)
        self.assertFalse(calls[0]["force_new_project"])

        with open(manifest_path, "r", encoding="utf-8") as f:
            final_manifest = json.load(f)
        self.assertEqual(final_manifest["flow_project_url"], dead_url)
        self.assertEqual(final_manifest["flow_account_id"], "flow-primary")
        self.assertEqual(final_manifest["flow_generation"]["status"], "FLOW_PROJECT_NOT_FOUND")

    def test_6b_with_generation_start_confirmed_does_not_clear_project_url_or_recreate(self):
        dead_url = "https://labs.google/fx/tools/flow/project/dispatched-456"
        manifest_path = self._create_manifest(
            project_url=dead_url,
            account_id="flow-primary",
            completed_scenes=[],
            generation_start_confirmed=True,
            num_scenes=2,
        )

        calls: List[Dict[str, Any]] = []

        def fake_gen(manifest_path: str, scene_index: int, project_url: Optional[str] = None, force_new_project: bool = False, **kwargs):
            calls.append({"scene_index": scene_index, "force_new_project": force_new_project})
            raise fp.FlowProjectNotFoundError("FLOW_PROJECT_NOT_FOUND: Projeto não encontrado")

        with patch("scripts.flow_workflow.generate_flow_scene", side_effect=fake_gen):
            res = fw.generate_pending_flow_scenes(
                manifest_path=manifest_path,
                failure_policy="fallback_to_stock",
            )

        self.assertEqual(res["status"], "FLOW_PROJECT_NOT_FOUND")
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0]["force_new_project"])

        with open(manifest_path, "r", encoding="utf-8") as f:
            final_manifest = json.load(f)
        self.assertEqual(final_manifest["flow_project_url"], dead_url)
        self.assertEqual(final_manifest["flow_account_id"], "flow-primary")
        self.assertEqual(final_manifest["flow_generation"]["status"], "FLOW_PROJECT_NOT_FOUND")
        self.assertIn("FLOW_PROJECT_NOT_FOUND", final_manifest["flow_generation"]["error"])

    # ------------------------------------------------------------------
    # (7) A leitura de saldo chama a mesma função dismiss_flow_announcements antes do clique
    # ------------------------------------------------------------------
    def test_7_read_flow_credit_balance_reuses_dismiss_flow_announcements_before_clicking_account_icon(self):
        call_order: List[str] = []
        modal_state = {"visible": True}

        def close_modal():
            call_order.append("dismiss_modal_click")
            modal_state["visible"] = False

        modal_btn = FakeButton(text="Got it", on_click=close_modal)

        class DynamicModalDialog:
            def is_visible(self) -> bool:
                return modal_state["visible"]

            def locator(self, selector: str) -> FakeLocatorList:
                if "button" in selector:
                    return FakeLocatorList([modal_btn])
                return FakeLocatorList([])

        account_panel = MagicMock()
        account_panel.is_visible.return_value = True
        panel_credits_loc = MagicMock()
        panel_credits_loc.count.return_value = 1
        panel_credits_loc.nth.return_value.inner_text.return_value = "420 créditos"
        account_panel.locator.return_value = panel_credits_loc

        account_trigger = MagicMock()
        account_trigger.count.return_value = 1
        account_trigger.is_visible.return_value = True

        def on_account_click(timeout: int = 2500):
            call_order.append("account_icon_click")
            if modal_state["visible"]:
                raise TimeoutError("Modal still blocking account trigger!")

        account_trigger.click.side_effect = on_account_click

        class CreditFakePage:
            def __init__(self):
                self.keyboard = FakeKeyboard()

            def wait_for_timeout(self, ms: int) -> None:
                pass

            def locator(self, selector: str) -> Any:
                if "[role='dialog']" in selector and "[aria-modal='true']" in selector:
                    return FakeLocatorList([DynamicModalDialog()])
                if "flow-header-user-icon" in selector:
                    loc = MagicMock()
                    loc.first = account_trigger
                    return loc
                if "flow-account-panel" in selector:
                    loc = MagicMock()
                    loc.first = account_panel
                    return loc
                return FakeLocatorList([])

        page = CreditFakePage()
        with patch("scripts.flow_playwright.dismiss_flow_announcements", wraps=fp.dismiss_flow_announcements) as spy_dismiss:
            bal, src = fap.read_flow_credit_balance(page)

        spy_dismiss.assert_called_once_with(page)
        self.assertEqual(call_order, ["dismiss_modal_click", "account_icon_click"])
        self.assertEqual(bal, 420)
        self.assertEqual(src, fap.CREDIT_SOURCE_FLOW_UI_VERIFIED)

    # ------------------------------------------------------------------
    # (8) FLOW_BLOCKING_MODAL interrompe o loop imediatamente e registra status/error no manifest
    # ------------------------------------------------------------------
    def test_8_blocking_modal_stops_workflow_and_records_status_and_error_in_manifest(self):
        manifest_path = self._create_manifest(
            project_url="https://labs.google/fx/tools/flow/project/modal-001",
            account_id="flow-primary",
            completed_scenes=[],
            num_scenes=4,
        )
        calls: List[int] = []

        def fake_modal_fail(manifest_path: str, scene_index: int, **kwargs):
            calls.append(scene_index)
            return fp.FlowSceneResult(
                status="FLOW_BLOCKING_MODAL",
                scene_index=scene_index,
                project_url=kwargs.get("project_url"),
                error="FLOW_BLOCKING_MODAL: Modal persistente sem botão permitido",
            )

        with patch("scripts.flow_workflow.generate_flow_scene", side_effect=fake_modal_fail):
            res = fw.generate_pending_flow_scenes(
                manifest_path=manifest_path,
                failure_policy="fallback_to_stock",
            )

        self.assertEqual(res["status"], "FLOW_BLOCKING_MODAL")
        self.assertEqual(calls, [1])
        with open(manifest_path, "r", encoding="utf-8") as f:
            final_manifest = json.load(f)
        self.assertEqual(final_manifest["flow_generation"]["status"], "FLOW_BLOCKING_MODAL")
        self.assertIn("FLOW_BLOCKING_MODAL", final_manifest["flow_generation"]["error"])

    # ------------------------------------------------------------------
    # (9) force_new_project=True em generate_flow_scene nunca faz failover de conta
    # ------------------------------------------------------------------
    def test_9_force_new_project_never_switches_account_on_failure(self):
        manifest_path = self._create_manifest(
            project_url=None,
            account_id="flow-primary",
            completed_scenes=[],
            num_scenes=2,
        )
        mock_acc = {
            "account_id": "flow-primary",
            "user_data_dir": os.path.join(self.test_dir, "profile_primary"),
            "runtime": {"status": "AVAILABLE", "credits_remaining": 200, "credits_source": "FLOW_UI_VERIFIED"},
        }

        with patch("app.services.flow_account_pool.resolve_manifest_account", return_value=mock_acc), \
             patch("app.services.flow_account_pool.failover_flow_account") as mock_failover, \
             patch("app.services.flow_account_pool.record_account_error"), \
             patch("app.services.flow_account_pool.get_account_runtime", return_value=mock_acc["runtime"]), \
             patch("scripts.flow_playwright.run_playwright_flow_poc", return_value={
                 "status": "FLOW_PROJECT_NOT_FOUND",
                 "error": "FLOW_PROJECT_NOT_FOUND: Projeto morto",
             }) as mock_poc:
            res = fp.generate_flow_scene(
                manifest_path=manifest_path,
                scene_index=1,
                project_url=None,
                force_new_project=True,
            )

        self.assertEqual(res.status, "FLOW_PROJECT_NOT_FOUND")
        self.assertIn("FLOW_PROJECT_NOT_FOUND", res.error or "")
        self.assertEqual(res.details.get("flow_account_id"), "flow-primary")
        mock_failover.assert_not_called()
        mock_poc.assert_called_once()
        self.assertTrue(mock_poc.call_args.kwargs["force_new_project"])
        self.assertEqual(mock_poc.call_args.kwargs["flow_account_id"], "flow-primary")


if __name__ == "__main__":
    unittest.main()
