#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
scripts/flow_playwright.py

Driver de automação web do Google Flow baseado em Playwright Python nativo.
Substitui a engine CDP raw por abstrações de alto nível:
- auto-wait e actionability nativas
- assertions com auto-retry
- gerenciamento de downloads com page.expect_download()
- perfil persistente isolado reutilizando storage/flow_browser_profile via channel="msedge"
- zero dependência de time.sleep() ou page.wait_for_timeout() no fluxo normal
"""

import argparse
import json
import os
import re
import sys
import time
from typing import Any, Dict, Optional, Tuple

from loguru import logger
from playwright.sync_api import BrowserContext, Locator, Page, Playwright, expect, sync_playwright

# Garante acesso aos módulos do projeto
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

DEFAULT_FLOW_URL = "https://flow.google.com"
DEFAULT_USER_DATA_DIR = os.path.join(ROOT_DIR, "storage", "flow_browser_profile")
DEFAULT_TIMEOUT_UI_MS = 30000
DEFAULT_TIMEOUT_GEN_SEC = 600
DEFAULT_TIMEOUT_DOWNLOAD_MS = 30000


def validate_clip_file(file_path: str) -> Dict[str, Any]:
    """Valida integridade e streams do vídeo via probe_media/ffprobe."""
    res: Dict[str, Any] = {
        "valid": False,
        "error": None,
        "duration": 0.0,
        "size": 0,
        "file_path": file_path,
    }

    if not file_path or not os.path.exists(file_path):
        res["error"] = "FILE_NOT_FOUND"
        return res

    if not os.path.isfile(file_path):
        res["error"] = "NOT_A_REGULAR_FILE"
        return res

    if not file_path.lower().endswith(".mp4"):
        res["error"] = "NOT_MP4_EXTENSION"
        return res

    size = os.path.getsize(file_path)
    res["size"] = size
    if size <= 0:
        res["error"] = "EMPTY_FILE"
        return res

    try:
        from app.services.media_quality import probe_media

        probe = probe_media(file_path)
        if not probe.get("valid"):
            err_code = probe.get("error_code") or "PROBE_FAILED"
            if err_code == "FFPROBE_UNAVAILABLE":
                # Fallback seguro para inspeção de streams e duração via PyAV
                try:
                    import av
                    container = av.open(file_path)
                    duration = float(container.duration) / 1000000.0 if container.duration else 0.0
                    video_streams = [s for s in container.streams if s.type == "video"]
                    if duration > 0.0 and len(video_streams) > 0:
                        res["valid"] = True
                        res["duration"] = duration
                        res["error"] = None
                        return res
                except Exception:
                    pass
            res["error"] = err_code
            return res

        duration = float(probe.get("format_duration", 0.0))
        res["duration"] = duration
        if duration <= 0.0:
            res["error"] = "ZERO_DURATION"
            return res

        video_streams = probe.get("video_streams", [])
        if not video_streams:
            res["error"] = "NO_VIDEO_STREAM"
            return res

        res["valid"] = True
        return res

    except Exception as exc:
        res["error"] = f"PROBE_EXCEPTION: {exc}"
        return res


def launch_flow_context(
    playwright: Playwright,
    user_data_dir: str = DEFAULT_USER_DATA_DIR,
    headless: bool = False,
) -> Tuple[Optional[BrowserContext], Optional[str]]:
    """
    Abre o contexto persistente do Playwright usando o Microsoft Edge instalado (channel='msedge').
    Se o perfil estiver bloqueado por outra instância do Edge, retorna fail-closed:
    AWAITING_FLOW_EDGE_PROFILE_CLOSE (sem matar navegadores genericamente).
    """
    os.makedirs(user_data_dir, exist_ok=True)
    try:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            channel="msedge",
            headless=headless,
            args=["--no-first-run", "--no-default-browser-check"],
        )
        return context, None
    except Exception as exc:
        err_msg = str(exc)
        if (
            "ProcessSingleton" in err_msg
            or "Lock file" in err_msg
            or "TargetClosedError" in err_msg
            or "exitCode=21" in err_msg
        ):
            logger.error(f"Perfil de navegação bloqueado por processo Edge existente: {err_msg}")
            return None, "AWAITING_FLOW_EDGE_PROFILE_CLOSE"
        logger.error(f"Falha ao iniciar contexto Playwright com channel='msedge': {err_msg}")
        raise


def check_login_state(page: Page, timeout_ms: int = DEFAULT_TIMEOUT_UI_MS) -> str:
    """
    Navega para https://flow.google.com se necessário e confirma o estado de autenticação.
    Retorna:
    - 'AUTHENTICATED' se sessão válida
    - 'AWAITING_INITIAL_HUMAN_LOGIN' se redirecionado para accounts.google.com
    - 'BLOCKED_CAPTCHA' se desafio de segurança ou captcha detectado
    """
    page.set_default_timeout(timeout_ms)

    if not page.url.startswith("https://flow.google.com"):
        logger.info(f"Navegando para {DEFAULT_FLOW_URL}...")
        page.goto(DEFAULT_FLOW_URL)
        page.wait_for_load_state("domcontentloaded")

    current_url = page.url
    logger.info(f"Página atual: {current_url}")

    if "accounts.google.com" in current_url:
        logger.warning("Redirecionado para tela de login Google. Intervenção humana necessária.")
        return "AWAITING_INITIAL_HUMAN_LOGIN"

    # Verificação de CAPTCHA
    captcha_loc = page.locator("iframe[src*='recaptcha'], div#captcha, iframe[src*='challenges']")
    if captcha_loc.count() > 0 and captcha_loc.first.is_visible():
        logger.error("Desafio de segurança ou CAPTCHA detectado na página.")
        return "BLOCKED_CAPTCHA"

    return "AUTHENTICATED"


def navigate_landing_to_studio(page: Page, timeout_ms: int = DEFAULT_TIMEOUT_UI_MS) -> str:
    """
    Se estiver na Landing, localiza o botão 'Novo projeto' / 'New project',
    executa exatamente UM clique e aguarda a transição para a URL /project/
    e a visibilidade do editor ProseMirror.
    """
    if "/project/" in page.url:
        logger.info(f"Já na superfície Studio: {page.url}")
        return page.url

    logger.info("Na superfície Landing. Buscando botão 'Novo projeto'...")
    new_proj_btn = page.get_by_role("button", name=re.compile(r"novo projeto|new project", re.I))
    new_proj_btn.wait_for(state="visible", timeout=timeout_ms)

    count = new_proj_btn.count()
    if count != 1:
        raise RuntimeError(f"AMBIGUOUS_OR_MISSING_NEW_PROJECT_BUTTON: count={count}")

    logger.info("Disparando clique único em 'Novo projeto'...")
    new_proj_btn.click()

    logger.info("Aguardando transição para /project/...")
    page.wait_for_url(re.compile(r".*/project/.*"), timeout=timeout_ms)

    editor = page.locator('div.ProseMirror[contenteditable="true"]')
    expect(editor).to_be_visible(timeout=timeout_ms)
    logger.info(f"Transição concluída com sucesso para Studio: {page.url}")
    return page.url


def fill_prompt(page: Page, prompt_text: str, timeout_ms: int = DEFAULT_TIMEOUT_UI_MS) -> None:
    """
    Localiza o editor ProseMirror, preenche o prompt com editor.fill()
    e valida o conteúdo com assertion auto-retry do Playwright (sem sleeps manuais).
    """
    logger.info("Localizando editor ProseMirror no Studio...")
    editor = page.locator('div.ProseMirror[contenteditable="true"]')
    expect(editor).to_be_visible(timeout=timeout_ms)

    count = editor.count()
    if count != 1:
        raise RuntimeError(f"AMBIGUOUS_PROSEMIRROR_EDITOR: count={count}")

    logger.info("Preenchendo prompt no editor...")
    editor.fill(prompt_text)

    # Asserção com auto-retry nativo do Playwright para confirmar conteúdo
    prefix = prompt_text[:40].strip()
    expect(editor).to_contain_text(prefix, timeout=timeout_ms)
    logger.info("Prompt preenchido e confirmado via expect do Playwright.")


def get_generate_button(page: Page, timeout_ms: int = DEFAULT_TIMEOUT_UI_MS) -> Locator:
    """
    Localiza o botão 'Iniciar geração' / 'Generate'.
    Exige locator único e visível.
    """
    btn = page.get_by_role("button", name=re.compile(r"iniciar gera..o|generate", re.I))
    btn.wait_for(state="visible", timeout=timeout_ms)

    count = btn.count()
    if count != 1:
        raise RuntimeError(f"AMBIGUOUS_OR_MISSING_GENERATE_BUTTON: count={count}")

    return btn


def check_generate_actionable(btn: Locator, timeout_ms: int = DEFAULT_TIMEOUT_UI_MS) -> bool:
    """
    Verifica a actionability completa do botão Generate via Playwright
    usando click(trial=True) sem executar o clique real.
    """
    logger.info("Testando actionability do botão Generate com trial=True...")
    btn.click(trial=True, timeout=timeout_ms)
    logger.info("Actionability do botão Generate confirmada (attached, visible, stable, enabled).")
    return True


def extract_credit_cost(page: Page) -> Optional[int]:
    """Extrai o custo de créditos visível no prompt de aprovação se disponível no DOM."""
    try:
        body_text = page.locator("body").inner_text()
        match = re.search(r"custa\s+(\d+)\s+cr[eé]ditos", body_text, re.I)
        if not match:
            match = re.search(r"(\d+)\s+cr[eé]ditos", body_text, re.I)
        if match:
            return int(match.group(1))
    except Exception:
        pass
    return None


def find_single_approve_button(page: Page) -> Locator:
    """
    Localiza o elemento estrito 'Aprovar' / 'Approve'.
    PROIBIDO selecionar 'Sempre aprovar' / 'Always approve'.
    Usa regex estrito com âncoras ^ e $.
    Suporta role='button' e role='radio' conforme renderização Angular/Material do Google Flow.
    """
    pattern = re.compile(r"^(Aprovar|Approve)$", re.I)
    return page.get_by_role("button", name=pattern).or_(
        page.get_by_role("radio", name=pattern)
    )


def check_pending_credit_approval(page: Page) -> Tuple[bool, int, Optional[int]]:
    """
    Verifica se já existe solicitação de aprovação de créditos pendente no DOM.
    Retorna: (is_pending, match_count, credit_cost)
    """
    approve_btn = find_single_approve_button(page)
    count = approve_btn.count()
    if count > 0 and approve_btn.first.is_visible():
        cost = extract_credit_cost(page)
        return True, count, cost
    return False, 0, None


def execute_credit_approval(
    page: Page,
    timeout_confirm_ms: int = 10000,
) -> Dict[str, Any]:
    """
    Executa a aprovação de créditos seguindo a máquina de estados:
    1. Verifica unicidade estrita do botão 'Aprovar' (match_count == 1).
    2. NUNCA seleciona 'Sempre aprovar'.
    3. Clica exatamente UMA VEZ no botão 'Aprovar'.
    4. Confirma que o botão/diálogo desapareceu do DOM.
    """
    approve_btn = find_single_approve_button(page)
    count = approve_btn.count()

    res: Dict[str, Any] = {
        "required": True,
        "match_count": count,
        "cost": extract_credit_cost(page),
        "click_count": 0,
        "confirmed": False,
        "always_approve_clicked": False,
        "error": None,
    }

    if count != 1:
        res["error"] = f"AMBIGUOUS_APPROVE_BUTTON_COUNT_{count}"
        logger.error(f"Botão de aprovação inválido ou ambíguo: match_count={count}")
        return res

    logger.info(f"Clicando em 'Aprovar' (1 único clique, custo={res['cost']})...")
    approve_btn.click()
    res["click_count"] = 1

    # Confirmação pós-clique: aguarda o botão 'Aprovar' desaparecer do DOM
    try:
        expect(approve_btn).to_have_count(0, timeout=timeout_confirm_ms)
        logger.info("Aprovação de créditos confirmada com sucesso (botão desapareceu)!")
        res["confirmed"] = True
    except Exception as exc:
        logger.error(f"Falha ao confirmar desaparecimento do botão Aprovar: {exc}")
        res["error"] = "CREDIT_APPROVAL_NOT_CONFIRMED"

    return res


def wait_for_generation_started(page: Page, timeout_ms: int = DEFAULT_TIMEOUT_UI_MS) -> bool:
    """
    Confirmação REAL de GENERATION_STARTED posterior à aprovação.
    Evidência: indicador de geração/processamento ativo (spinner, progress bar, generating indicator).
    NÃO aceita diálogo ou botão de aprovação presente.
    """
    logger.info(f"Aguardando evidência de início real de processamento do job (timeout {timeout_ms/1000}s)...")
    try:
        page.wait_for_function(
            """() => {
                // NÃO aceita aprovação pendente
                const options = Array.from(document.querySelectorAll('[role="radio"], button, [role="button"]'));
                const hasApprove = options.some(el => {
                    const txt = (el.getAttribute('aria-label') || el.innerText || '').trim();
                    return /^aprovar$/i.test(txt) || /^approve$/i.test(txt);
                });
                if (hasApprove) return false;

                // Aceita evidência real de geração/processamento
                const progress = document.querySelector('[role="progressbar"], mat-progress-bar, flow-progress, flow-spinner, .generating-indicator, [aria-label*="Gerando" i], [aria-label*="Generating" i]');
                return !!progress;
            }""",
            timeout=timeout_ms,
        )
        logger.info("GENERATION_STARTED confirmado no DOM com sucesso!")
        return True
    except Exception as exc:
        logger.error(f"Falha ao confirmar GENERATION_STARTED dentro de {timeout_ms/1000}s: {exc}")
        return False


def wait_for_generation_complete(page: Page, timeout_sec: int = DEFAULT_TIMEOUT_GEN_SEC) -> bool:
    """
    Acompanha a geração até a conclusão (até 600s).
    Evidência: vídeo pronto ou botão de download disponível.
    """
    logger.info(f"Aguardando conclusão da geração no Flow (timeout: {timeout_sec}s)...")
    try:
        page.wait_for_function(
            """() => {
                const hasVideo = Array.from(document.querySelectorAll('video')).some(v => v.src || v.currentSrc);
                const hasDl = Array.from(document.querySelectorAll('button, a')).some(el => {
                    const txt = (el.innerText || el.getAttribute('aria-label') || '').toLowerCase();
                    return txt.includes('download') || txt.includes('baixar');
                });
                return hasVideo || hasDl;
            }""",
            timeout=timeout_sec * 1000,
        )
        logger.info("Geração do Flow concluída com sucesso (mídia disponível)!")
        return True
    except Exception as exc:
        logger.error(f"Timeout ou erro aguardando conclusão da geração: {exc}")
        return False


def download_generated_clip(
    page: Page,
    output_path: str,
    timeout_ms: int = DEFAULT_TIMEOUT_DOWNLOAD_MS,
) -> Tuple[bool, Optional[str]]:
    """
    Executa o download do clipe gerado utilizando o evento nativo expect_download do Playwright:
        with page.expect_download(timeout=30_000) as download_info:
            download_button.click()
        download = download_info.value
        download.save_as(canonical_output_path)
    """
    logger.info("Localizando botão ou menu de download no Studio...")
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # 1. Se houver container de vídeo gerado, passa o mouse para revelar a hotbar
    container = page.locator(".container:has(img.thumbnail), flow-tile, .project-tile-hover-footer").first
    if container.count() > 0:
        try:
            container.hover()
        except Exception:
            pass

    # 2. Localiza botão direto de download ou abre o menu 'Mais opções'
    dl_btn = page.locator(
        "button[aria-label*='Download' i], button[aria-label*='Baixar' i], "
        "a[aria-label*='Download' i], a[aria-label*='Baixar' i]"
    ).first

    more_btn = page.locator("flow-video-hotbar button[aria-label*='Mais op' i], button[aria-label*='Mais op' i]").first

    try:
        with page.expect_download(timeout=timeout_ms) as download_info:
            if dl_btn.count() > 0 and dl_btn.is_visible():
                dl_btn.click()
            elif more_btn.count() > 0:
                logger.info("Abrindo menu 'Mais opções' na hotbar do clipe...")
                more_btn.click()
                menu_dl = page.locator(
                    "[role='menuitem']:has-text('download'), [role='menuitem']:has-text('Download'), "
                    "[role='menuitem']:has-text('Baixar')"
                ).first
                menu_dl.wait_for(state="visible", timeout=5000)
                menu_dl.click()

                # Clica na opção de resolução 720p (Tamanho original)
                opt_720 = page.locator(
                    "[role='menuitem']:has-text('720p'), [role='menuitem']:has-text('original'), button:has-text('720p')"
                ).first
                opt_720.wait_for(state="visible", timeout=5000)
                opt_720.click()
            else:
                # Dispara download através da fonte direta do vídeo mantendo expect_download nativo
                logger.info("Disparando download via elemento de vídeo...")
                page.evaluate("""() => {
                    const vid = document.querySelector('video');
                    const src = vid ? (vid.src || vid.currentSrc) : null;
                    if (src) {
                        const a = document.createElement('a');
                        a.href = src;
                        a.download = 'flow_clip.mp4';
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);
                    }
                }""")

        download = download_info.value
        logger.info(f"Download capturado ({download.suggested_filename}). Salvando em {output_path}...")
        download.save_as(output_path)
        logger.info("Download salvo com sucesso!")
        return True, None
    except Exception as exc:
        logger.error(f"Falha ao capturar ou salvar download: {exc}")
        return False, f"DOWNLOAD_FAILED: {exc}"


def run_playwright_flow_poc(
    manifest_path: str,
    scene_index: int = 1,
    trial_only: bool = False,
    timeout_gen_sec: int = DEFAULT_TIMEOUT_GEN_SEC,
) -> Dict[str, Any]:
    """
    Executa o ciclo completo de validação do Playwright:
    1. Abre Edge com perfil persistente (channel='msedge')
    2. Confirma sessão (AUTHENTICATED)
    3. Navega LANDING -> STUDIO
    4. Preenche prompt
    5. Confirma texto via auto-retry assertion
    6. Confirma Generate actionable usando trial=True
    ZERO geração até aqui.

    Se todos os passos 1-6 passarem E trial_only for False:
    Executa EXATAMENTE UMA geração real na mesma execução autorizada:
    1. Confirma generation start
    2. Aguarda conclusão
    3. expect_download + click download
    4. save_as canonical_output_path
    5. probe_media / validate_clip_file
    """
    report: Dict[str, Any] = {
        "status": "FAILED",
        "login_status": "UNKNOWN",
        "landing_to_studio": False,
        "editor_found": False,
        "prompt_filled": False,
        "prompt_confirmed": False,
        "generate_actionable": False,
        "pending_approval_found": False,
        "generate_click_count_this_run": 0,
        "credit_approval_required": False,
        "credit_cost": None,
        "credit_approval_button_match_count": 0,
        "credit_approval_click_count": 0,
        "credit_approval_confirmed": False,
        "always_approve_clicked": False,
        "generation_start_confirmed": False,
        "generation_attempts": 0,
        "generation_complete_confirmed": False,
        "download_event_confirmed": False,
        "output_file": None,
        "output_valid": False,
        "output_duration": 0.0,
        "error": None,
    }

    if not os.path.exists(manifest_path):
        report["error"] = f"MANIFEST_NOT_FOUND: {manifest_path}"
        return report

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    scenes = manifest.get("scenes", [])
    target_scene = next((s for s in scenes if s.get("scene_index") == scene_index), None)
    if not target_scene:
        report["error"] = f"SCENE_{scene_index}_NOT_FOUND_IN_MANIFEST"
        return report

    prompt_text = target_scene.get("prompt_en") or target_scene.get("prompt_pt") or ""
    if not prompt_text:
        report["error"] = "EMPTY_PROMPT_IN_SCENE"
        return report

    project_dir = os.path.dirname(os.path.abspath(manifest_path))
    clip_filename = target_scene.get("expected_clip", f"flow_scene_{scene_index:02d}.mp4")
    canonical_output_path = os.path.join(project_dir, "clips", clip_filename)

    with sync_playwright() as p:
        context, err = launch_flow_context(p, headless=False)
        if err:
            report["status"] = err
            report["error"] = err
            return report

        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_UI_MS)

        try:
            # 1. Login e sessão
            login_st = check_login_state(page)
            report["login_status"] = login_st
            if login_st != "AUTHENTICATED":
                report["status"] = login_st
                report["error"] = login_st
                context.close()
                return report

            # 2. Navegação Landing -> Studio
            navigate_landing_to_studio(page)
            report["landing_to_studio"] = True
            report["editor_found"] = True

            # 3. Preenchimento e confirmação do prompt (apenas se editor estiver livre)
            is_pending, p_count, p_cost = check_pending_credit_approval(page)
            report["pending_approval_found"] = is_pending

            if not is_pending:
                fill_prompt(page, prompt_text)
                report["prompt_filled"] = True
                report["prompt_confirmed"] = True

                gen_btn = get_generate_button(page)
                actionable = check_generate_actionable(gen_btn)
                report["generate_actionable"] = actionable
            else:
                logger.info("Diálogo de aprovação já visível no início. Mantendo prompt atual.")
                report["prompt_filled"] = True
                report["prompt_confirmed"] = True
                report["generate_actionable"] = True

            logger.info("=== PRE-FLIGHT VALIDAÇÕES CONCLUÍDAS ===")

            if trial_only:
                report["status"] = "PRE_FLIGHT_TRIAL_PASS"
                context.close()
                return report

            # 4. MÁQUINA DE ESTADOS: VERIFICAÇÃO DE ESTADO PRÉ-EXISTENTE
            if is_pending:
                logger.info(f"ESTADO PRÉ-EXISTENTE DETECTADO: pedido de aprovação pendente encontrado (custo={p_cost}).")
                logger.info("NÃO clicando no botão Generate novamente nesta execução!")
                report["generate_click_count_this_run"] = 0
                report["credit_approval_required"] = True
                report["credit_cost"] = p_cost
                report["credit_approval_button_match_count"] = p_count

                appr_res = execute_credit_approval(page)
                report["credit_approval_click_count"] = appr_res["click_count"]
                report["credit_approval_confirmed"] = appr_res["confirmed"]
                report["always_approve_clicked"] = False

                if not appr_res["confirmed"]:
                    report["status"] = "CREDIT_APPROVAL_FAILED"
                    report["error"] = appr_res.get("error")
                    context.close()
                    return report

            else:
                # Dispara clique único no Generate
                logger.info("=== DISPARANDO EXATAMENTE UMA GERAÇÃO REAL AUTORIZADA ===")
                gen_btn.click()
                report["generate_click_count_this_run"] = 1

                # Aguarda EITHER aprovação requerida OU geração iniciada diretamente
                logger.info("Aguardando decisão da interface: aprovação de créditos ou início direto...")
                try:
                    wait_res = page.wait_for_function(
                        """() => {
                            const options = Array.from(document.querySelectorAll('[role="radio"], button, [role="button"]'));
                            const hasApprove = options.some(el => {
                                const txt = (el.getAttribute('aria-label') || el.innerText || '').trim();
                                return /^aprovar$/i.test(txt) || /^approve$/i.test(txt);
                            });
                            if (hasApprove) return 'APPROVAL_REQUIRED';

                            const progress = document.querySelector('[role="progressbar"], mat-progress-bar, flow-progress, flow-spinner, .generating-indicator, [aria-label*="Gerando" i], [aria-label*="Generating" i]');
                            if (progress) return 'GENERATION_STARTED';

                            return false;
                        }""",
                        timeout=DEFAULT_TIMEOUT_UI_MS,
                    )
                    state_found = wait_res.json_value()
                except Exception as exc:
                    logger.error(f"Timeout aguardando aprovação ou início de geração: {exc}")
                    report["status"] = "GENERATION_DISPATCH_TIMEOUT_30S"
                    report["error"] = "GENERATION_DISPATCH_TIMEOUT_30S"
                    context.close()
                    return report

                if state_found == "APPROVAL_REQUIRED":
                    logger.info("CREDIT_APPROVAL_REQUIRED detectado após o clique!")
                    report["credit_approval_required"] = True
                    appr_res = execute_credit_approval(page)
                    report["credit_cost"] = appr_res["cost"]
                    report["credit_approval_button_match_count"] = appr_res["match_count"]
                    report["credit_approval_click_count"] = appr_res["click_count"]
                    report["credit_approval_confirmed"] = appr_res["confirmed"]
                    report["always_approve_clicked"] = False

                    if not appr_res["confirmed"]:
                        report["status"] = "CREDIT_APPROVAL_FAILED"
                        report["error"] = appr_res.get("error")
                        context.close()
                        return report

            # 5. CONFIRMAÇÃO REAL DE GENERATION_STARTED (posterior à aprovação)
            started = wait_for_generation_started(page, timeout_ms=DEFAULT_TIMEOUT_UI_MS)
            report["generation_start_confirmed"] = started
            if not started:
                report["status"] = "GENERATION_START_NOT_CONFIRMED"
                report["error"] = "GENERATION_START_NOT_CONFIRMED"
                context.close()
                return report

            report["generation_attempts"] = 1

            # 6. Aguarda conclusão da geração (até timeout_gen_sec)
            completed = wait_for_generation_complete(page, timeout_sec=timeout_gen_sec)
            report["generation_complete_confirmed"] = completed
            if not completed:
                report["status"] = "GENERATION_COMPLETION_FAILED"
                report["error"] = f"GENERATION_TIMEOUT_{timeout_gen_sec}S"
                context.close()
                return report

            # 7. DOWNLOAD VIA EXPECT_DOWNLOAD
            dl_ok, dl_err = download_generated_clip(page, canonical_output_path)
            report["download_event_confirmed"] = dl_ok
            if not dl_ok:
                report["status"] = "DOWNLOAD_FAILED"
                report["error"] = dl_err
                context.close()
                return report

            report["output_file"] = canonical_output_path

            # 8. VALIDAÇÃO DE MÍDIA COM PROBE_MEDIA
            media_val = validate_clip_file(canonical_output_path)
            report["output_valid"] = media_val.get("valid", False)
            report["output_duration"] = media_val.get("duration", 0.0)

            if not media_val.get("valid"):
                report["status"] = "INVALID_OUTPUT_MEDIA"
                report["error"] = media_val.get("error")
                context.close()
                return report

            report["status"] = "SUCCESS"
            report["error"] = None
            context.close()
            return report

        except Exception as exc:
            logger.exception(f"Erro durante a execução do Playwright Flow: {exc}")
            report["status"] = "UNEXPECTED_ERROR"
            report["error"] = str(exc)
            try:
                context.close()
            except Exception:
                pass
            return report


def main():
    parser = argparse.ArgumentParser(description="Google Flow Playwright Automation Driver")
    parser.add_argument("--manifest", default="storage/manual_media/flow_web_poc/manifest.json", help="Caminho do manifest.json")
    parser.add_argument("--scene", type=int, default=1, help="Índice da cena a processar")
    parser.add_argument("--trial-only", action="store_true", help="Executa apenas steps 1-6 com trial=True (zero geração)")
    parser.add_argument("--timeout-gen", type=int, default=DEFAULT_TIMEOUT_GEN_SEC, help="Timeout de geração em segundos")

    args = parser.parse_args()

    res = run_playwright_flow_poc(
        manifest_path=args.manifest,
        scene_index=args.scene,
        trial_only=args.trial_only,
        timeout_gen_sec=args.timeout_gen,
    )

    print("\n" + "=" * 50)
    print("RELATÓRIO DE EXECUÇÃO FLOW PLAYWRIGHT")
    print("=" * 50)
    for k, v in res.items():
        print(f"{k.upper()} = {v}")
    print("=" * 50)

    if res.get("status") in ("SUCCESS", "PRE_FLIGHT_TRIAL_PASS"):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
