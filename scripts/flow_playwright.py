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
            res["error"] = probe.get("error_code") or "PROBE_FAILED"
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


def dispatch_and_confirm_generation(
    page: Page,
    generate_btn: Locator,
    timeout_start_ms: int = DEFAULT_TIMEOUT_UI_MS,
    timeout_complete_sec: int = DEFAULT_TIMEOUT_GEN_SEC,
) -> Dict[str, Any]:
    """
    Dispara o clique no botão Generate exatamente UMA VEZ e aguarda:
    1. Confirmação do início do job (até 30s) por evidência observável no DOM
       (botão Generate desabilitado ou spinner/progressbar ativo).
       Se não confirmar: para imediatamente com GENERATION_START_NOT_CONFIRMED.
    2. Conclusão da geração (até 600s) pelo surgimento de vídeo ou botão de download.
    """
    logger.info("Disparando clique no botão Generate (EXATAMENTE UMA VEZ)...")
    generate_btn.click()

    # Confirmação do início do job via expectativa do Playwright
    logger.info(f"Aguardando confirmação observável do início do job (timeout {timeout_start_ms/1000}s)...")
    try:
        page.wait_for_function(
            """() => {
                const genBtn = document.querySelector('button[aria-label="Iniciar geração"], button[aria-label="Start generation"], flow-generate-icon-button button, button.generate-button');
                if (genBtn && (genBtn.disabled || genBtn.getAttribute('aria-disabled') === 'true')) {
                    return true;
                }
                const progress = document.querySelector('[role="progressbar"], mat-progress-bar, flow-progress, flow-spinner, .generating-indicator, [aria-label*="Gerando" i], [aria-label*="Generating" i]');
                const approveBtn = Array.from(document.querySelectorAll('button')).some(b => {
                    const txt = (b.innerText || '').toLowerCase();
                    return txt.includes('aprovar') || txt.includes('approve');
                });
                return !!progress || approveBtn;
            }""",
            timeout=timeout_start_ms,
        )
        logger.info("Início do job confirmado no DOM com sucesso!")

        # Se o assistente solicitar confirmação de créditos ("Quer que eu inicie essa geração..."), aprova
        approve_btn = page.get_by_role("button", name=re.compile(r"^(aprovar|approve|sempre aprovar|always approve)$", re.I)).first
        try:
            if approve_btn.count() > 0 and approve_btn.is_visible():
                logger.info("Detectado pedido de aprovação de créditos pelo assistente. Clicando em Aprovar...")
                approve_btn.click()
                logger.info("Aprovação de créditos enviada!")
        except Exception as e_appr:
            logger.debug(f"Nenhum botão de aprovação adicional necessário: {e_appr}")

    except Exception as exc:
        logger.error(f"Falha ao confirmar início da geração no DOM dentro de {timeout_start_ms/1000}s: {exc}")
        return {
            "start_confirmed": False,
            "complete_confirmed": False,
            "error": "GENERATION_START_NOT_CONFIRMED",
        }

    # Aguarda a conclusão da geração no Studio (até timeout_complete_sec)
    logger.info(f"Aguardando conclusão da geração no Flow (timeout: {timeout_complete_sec}s)...")
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
            timeout=timeout_complete_sec * 1000,
        )
        logger.info("Geração do Flow concluída com sucesso (mídia disponível)!")
        return {
            "start_confirmed": True,
            "complete_confirmed": True,
            "error": None,
        }
    except Exception as exc:
        logger.error(f"Timeout ou erro aguardando conclusão da geração: {exc}")
        return {
            "start_confirmed": True,
            "complete_confirmed": False,
            "error": f"GENERATION_TIMEOUT_{timeout_complete_sec}S",
        }


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
    logger.info("Localizando botão de download no Studio...")
    download_btn = page.locator(
        "button[aria-label*='Download' i], button[aria-label*='Baixar' i], "
        "a[aria-label*='Download' i], a[aria-label*='Baixar' i], "
        "button:has-text('Download'), button:has-text('Baixar'), "
        "button:has(mat-icon:has-text('download')), button:has(span:has-text('download'))"
    ).first

    # Se o botão estiver oculto aguardando hover, passa o mouse sobre o vídeo
    try:
        if download_btn.count() == 0 or not download_btn.is_visible():
            vid = page.locator("video").first
            if vid.count() > 0:
                vid.hover()
    except Exception:
        pass

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    logger.info("Disparando download e aguardando evento page.expect_download()...")
    try:
        with page.expect_download(timeout=timeout_ms) as download_info:
            if download_btn.count() > 0 and download_btn.is_visible():
                download_btn.click()
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
        "generation_click_count": 0,
        "generation_start_confirmed": False,
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

            # 3. Preenchimento e confirmação do prompt
            fill_prompt(page, prompt_text)
            report["prompt_filled"] = True
            report["prompt_confirmed"] = True

            # 4. Localização e actionability check com trial=True
            gen_btn = get_generate_button(page)
            actionable = check_generate_actionable(gen_btn)
            report["generate_actionable"] = actionable

            logger.info("=== PASSOS 1-6 VALIDADOS COM SUCESSO (ZERO GERAÇÕES EFETUADAS) ===")

            if trial_only:
                report["status"] = "PRE_FLIGHT_TRIAL_PASS"
                context.close()
                return report

            # 5. DISPARO REAL (EXATAMENTE UMA VEZ)
            logger.info("=== DISPARANDO EXATAMENTE UMA GERAÇÃO REAL AUTORIZADA ===")
            report["generation_click_count"] = 1
            gen_res = dispatch_and_confirm_generation(page, gen_btn)
            report["generation_start_confirmed"] = gen_res["start_confirmed"]
            report["generation_complete_confirmed"] = gen_res["complete_confirmed"]

            if not gen_res["start_confirmed"]:
                report["status"] = "GENERATION_START_NOT_CONFIRMED"
                report["error"] = gen_res.get("error")
                context.close()
                return report

            if not gen_res["complete_confirmed"]:
                report["status"] = "GENERATION_COMPLETION_FAILED"
                report["error"] = gen_res.get("error")
                context.close()
                return report

            # 6. DOWNLOAD VIA EXPECT_DOWNLOAD
            dl_ok, dl_err = download_generated_clip(page, canonical_output_path)
            report["download_event_confirmed"] = dl_ok
            if not dl_ok:
                report["status"] = "DOWNLOAD_FAILED"
                report["error"] = dl_err
                context.close()
                return report

            report["output_file"] = canonical_output_path

            # 7. VALIDAÇÃO DE MÍDIA COM PROBE_MEDIA
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
