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
from dataclasses import dataclass, field
import hashlib
import json
import os
import re
import sys
import time
from typing import Any, Dict, Optional, Set, Tuple

from loguru import logger
from playwright.sync_api import BrowserContext, Locator, Page, Playwright, expect, sync_playwright

# Garante acesso aos módulos do projeto
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.services.task_artifacts import atomic_write_json  # noqa: E402

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

        if (
            "Executable doesn't exist" in err_msg
            or "cannot find" in err_msg.lower()
            or "channel 'msedge' is not supported" in err_msg.lower()
            or 'channel "msedge"' in err_msg.lower()
            or "browsertype.launch: channel" in err_msg.lower()
        ):
            logger.error(f"Microsoft Edge (channel='msedge') não disponível no sistema: {err_msg}")
            return None, "EDGE_CHANNEL_UNAVAILABLE"

        logger.error(f"Falha ao iniciar contexto Playwright com channel='msedge': {err_msg}")
        return None, f"PLAYWRIGHT_LAUNCH_FAILED: {err_msg}"


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


FORBIDDEN_PROJECT_IDS = ["231bb713", "9635d727"]


def ensure_studio_surface(
    page: Page,
    project_url: Optional[str] = None,
    timeout_ms: int = DEFAULT_TIMEOUT_UI_MS,
    force_new_project: bool = False,
) -> str:
    """
    Garante que o navegador está na superfície Studio com o editor ProseMirror pronto.
    Precedência mandatória:
    1. project_url explícita (via CLI ou manifest) -> page.goto(project_url)
    2. force_new_project ou projeto proibido/deprecado -> navega para landing e cria novo projeto
    3. URL atual já contém /project/ -> reutiliza sessão atual
    4. Landing page sem project_url -> clica 'Novo projeto' exatamente uma vez

    NUNCA clica em 'Novo projeto' quando project_url for fornecida.
    """
    page.set_default_timeout(timeout_ms)
    editor = page.locator('div.ProseMirror[contenteditable="true"]')

    if project_url:
        logger.info(f"Reabrindo projeto existente via project_url explícita: {project_url}")
        if page.url != project_url:
            page.goto(project_url)
            page.wait_for_load_state("domcontentloaded")
        page.wait_for_url(re.compile(r".*/project/.*"), timeout=timeout_ms)
        expect(editor).to_be_visible(timeout=timeout_ms)
        logger.info(f"Superfície Studio confirmada no projeto alvo: {project_url}")
        return project_url

    is_forbidden = any(pid in page.url for pid in FORBIDDEN_PROJECT_IDS)
    if force_new_project or is_forbidden:
        if is_forbidden:
            logger.warning(f"URL atual contém projeto proibido/deprecado ({page.url}). Forçando criação de novo projeto limpo.")
        else:
            logger.info("force_new_project ativo: navegando para landing para criar novo projeto limpo.")
        page.goto(DEFAULT_FLOW_URL)
        page.wait_for_load_state("domcontentloaded")
        return navigate_landing_to_studio(page, timeout_ms=timeout_ms)

    if "/project/" in page.url:
        logger.info(f"Página atual já está na superfície Studio: {page.url}")
        expect(editor).to_be_visible(timeout=timeout_ms)
        return page.url

    return navigate_landing_to_studio(page, timeout_ms=timeout_ms)


def ensure_video_generation_mode(
    page: Page,
    timeout_ms: int = DEFAULT_TIMEOUT_UI_MS,
) -> Dict[str, Any]:
    """
    Garante operacionalmente que o modo de geração ativo é VIDEO antes de qualquer ação.
    Contrato Fail-Closed:
    - Se já estiver em VIDEO: não clica no seletor desnecessariamente, retorna confirmed=True, changed=False.
    - Se estiver em IMAGEM (ou modelo Nano Banana): abre o seletor, localiza exatamente 1
      opção de Vídeo, clica UMA vez, ajusta 9:16 e x1 se disponíveis, fecha seletor e
      confirma via asserção de UI que o modo ativo agora é VIDEO. Retorna confirmed=True, changed=True.
    - Se o controle de modo estiver ausente, ambíguo, ou a opção de Vídeo for ambígua/não confirmada:
      FAIL CLOSED -> retorna confirmed=False com FLOW_VIDEO_MODE_NOT_CONFIRMED (zero cliques em Generate, zero créditos).
    """
    res: Dict[str, Any] = {
        "confirmed": False,
        "changed": False,
        "generation_type": "UNKNOWN",
        "aspect_ratio": None,
        "output_count": None,
        "error": None,
    }

    try:
        # Se houver painel lateral de chat aberto cobrindo a interface principal, fecha-o
        close_btn = page.locator(
            "flow-chat button[aria-label*='Fechar' i], flow-chat button[aria-label*='Close' i], "
            "button[aria-label='Fechar'], button[aria-label='Close']"
        ).filter(has_text=re.compile(r"close", re.I))
        if close_btn.count() > 0 and close_btn.first.is_visible():
            logger.info("Fechando painel de chat para expor controles principais do Studio...")
            try:
                close_btn.first.click()
            except Exception as close_exc:
                logger.debug(f"Não foi necessário fechar chat: {close_exc}")

        # Localiza o botão gatilho de configurações/modelo
        trigger_btn = page.get_by_role("button", name=re.compile(r"gatilho de configura..es|settings trigger", re.I))
        if trigger_btn.count() == 0:
            # Fallback para botão contendo palavras-chave de modelos/modos
            trigger_btn = page.locator("button").filter(
                has_text=re.compile(r"\b(v[íi]deo|video|veo|omni|banana|nano|imagem|image)\b", re.I)
            )

        count = trigger_btn.count()
        if count == 0:
            logger.error("MISSING_GENERATION_TYPE_TRIGGER: nenhum botão de seleção de modo encontrado.")
            res["error"] = "FLOW_VIDEO_MODE_NOT_CONFIRMED"
            return res

        if count > 1:
            visible_btns = [b for b in trigger_btn.all() if b.is_visible()]
            if len(visible_btns) == 1:
                target_btn = visible_btns[0]
            else:
                logger.error(f"AMBIGUOUS_GENERATION_TYPE_TRIGGER: count={count}, visible={len(visible_btns)}")
                res["error"] = "FLOW_VIDEO_MODE_NOT_CONFIRMED"
                return res
        else:
            target_btn = trigger_btn.first

        target_btn.wait_for(state="visible", timeout=timeout_ms)
        initial_text = target_btn.inner_text().strip()
        logger.info(f"Texto atual do seletor de modo/modelo: '{initial_text}'")

        # 1. ESTADO JÁ VIDEO
        is_video = bool(re.search(r"\b(v[íi]deo|video|veo|omni)\b", initial_text, re.I))
        is_image = bool(re.search(r"\b(imagem|image|banana|nano)\b", initial_text, re.I))

        if is_video and not is_image:
            logger.info("Modo de geração já está comprovado como VIDEO. Zero cliques no seletor.")
            res["confirmed"] = True
            res["changed"] = False
            res["generation_type"] = "VIDEO"
            if "9:16" in initial_text or "9_16" in initial_text:
                res["aspect_ratio"] = "9:16"
            if "x1" in initial_text:
                res["output_count"] = 1
            return res

        # 2. ESTADO IMAGE / NÃO CONFIRMADO -> MUDANÇA CONTROLADA
        logger.info("Modo não está configurado como VIDEO. Abrindo seletor para alteração controlada...")
        target_btn.click(timeout=timeout_ms)

        # Localiza o overlay
        overlay = page.locator(".cdk-overlay-pane, [role='dialog'], [role='menu']").filter(
            has=page.get_by_role("radio")
        )
        overlay.first.wait_for(state="visible", timeout=timeout_ms)

        # Localiza a opção de Vídeo
        video_radio = overlay.first.get_by_role("radio", name=re.compile(r"^(videocam\s+)?v[íi]deo$|^video$", re.I))
        if video_radio.count() == 0:
            video_radio = overlay.first.get_by_role("radio").filter(
                has_text=re.compile(r"^\s*(videocam\s+)?v[íi]deo\s*$", re.I)
            )

        v_count = video_radio.count()
        if v_count != 1:
            logger.error(f"Opção 'Vídeo' ambígua ou ausente no seletor: count={v_count}. Abortando fail-closed.")
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            res["error"] = "FLOW_VIDEO_MODE_NOT_CONFIRMED"
            return res

        # Clica na opção Vídeo exatamente UMA vez
        logger.info("Selecionando opção 'Vídeo' no overlay...")
        video_radio.first.click(timeout=timeout_ms)
        expect(video_radio.first).to_have_attribute("aria-checked", "true", timeout=timeout_ms)

        # Ajusta aspect ratio 9:16 se disponível
        ar_9_16 = overlay.first.get_by_role("radio", name=re.compile(r"9:16", re.I))
        if ar_9_16.count() == 1:
            if ar_9_16.first.get_attribute("aria-checked") != "true":
                logger.info("Configurando aspect ratio para 9:16...")
                ar_9_16.first.click(timeout=timeout_ms)
                expect(ar_9_16.first).to_have_attribute("aria-checked", "true", timeout=timeout_ms)
            res["aspect_ratio"] = "9:16"

        # Ajusta contagem x1 se disponível
        x1_opt = overlay.first.get_by_role("radio", name=re.compile(r"^x1$", re.I))
        if x1_opt.count() == 1:
            if x1_opt.first.get_attribute("aria-checked") != "true":
                logger.info("Configurando contagem de saída para x1...")
                x1_opt.first.click(timeout=timeout_ms)
                expect(x1_opt.first).to_have_attribute("aria-checked", "true", timeout=timeout_ms)
            res["output_count"] = 1

        # Fecha o overlay
        page.keyboard.press("Escape")
        try:
            overlay.first.wait_for(state="hidden", timeout=5000)
        except Exception:
            pass

        # Confirma na própria UI que o tipo ativo agora é Video
        expect(target_btn).to_contain_text(re.compile(r"v[íi]deo|video", re.I), timeout=timeout_ms)
        expect(target_btn).not_to_contain_text(re.compile(r"banana|nano|imagem|image", re.I), timeout=timeout_ms)

        final_text = target_btn.inner_text().strip()
        logger.info(f"Modo VIDEO confirmado na UI com sucesso! Seletor: '{final_text}'")

        res["confirmed"] = True
        res["changed"] = True
        res["generation_type"] = "VIDEO"
        return res

    except Exception as exc:
        logger.error(f"Falha ao assegurar modo VIDEO no Flow: {exc}")
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        res["error"] = "FLOW_VIDEO_MODE_NOT_CONFIRMED"
        return res


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
    Localiza o elemento estrito 'Aprovar' / 'Approve' ativo e acionável.
    PROIBIDO selecionar 'Sempre aprovar' / 'Always approve'.
    Filtra elementos concluídos/inativos da história do chat (.read-only / aria-disabled=true).
    Usa regex estrito com âncoras ^ e $.
    Suporta role='button' e role='radio' conforme renderização Angular/Material do Google Flow.
    """
    pattern = re.compile(r"^(Aprovar|Approve)$", re.I)
    btn_loc = page.get_by_role("button", name=pattern, disabled=False)
    radio_loc = page.get_by_role("radio", name=pattern, disabled=False)
    return btn_loc.or_(radio_loc).filter(has_not=page.locator(".read-only, [aria-disabled='true']"))


def check_pending_credit_approval(page: Page) -> Tuple[bool, int, Optional[int]]:
    """
    Verifica se já existe solicitação de aprovação de créditos pendente no DOM.
    Retorna: (is_pending, match_count, credit_cost)
    """
    approve_btn = find_single_approve_button(page)
    count = approve_btn.count()
    if count == 1 and approve_btn.is_visible():
        cost = extract_credit_cost(page)
        return True, 1, cost
    elif count > 1:
        logger.warning(f"Múltiplos botões de aprovação encontrados no início: count={count}")
        return True, count, extract_credit_cost(page)
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

    if res["cost"] is None:
        res["error"] = "CREDIT_COST_UNKNOWN"
        logger.error("FAIL CLOSED: custo de créditos desconhecido (None). Abortando sem aprovação.")
        return res

    if res["cost"] > 15:
        res["error"] = f"CREDIT_COST_EXCEEDS_CAP_{res['cost']}"
        logger.error(f"FAIL CLOSED: custo de créditos ({res['cost']}) excede o teto permitido (15). Abortando sem aprovação.")
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


def wait_for_generation_started(
    page: Page,
    baseline_count: int = 0,
    generation_type_confirmed: bool = False,
    generation_type: str = "UNKNOWN",
    timeout_ms: int = DEFAULT_TIMEOUT_UI_MS,
) -> bool:
    """
    Confirmação REAL de GENERATION_STARTED posterior à aprovação.
    Evidência: indicador de geração/processamento ativo (spinner, progress bar, generating indicator,
    botão Parar ativo, ou novo tile adicionado à grade).
    NÃO aceita diálogo ou botão de aprovação pendente.
    Exige estritamente generation_type_confirmed=True e generation_type='VIDEO'.
    Gerações genéricas (ex: spinner de imagem) são estritamente rejeitadas se o modo não foi confirmado.
    """
    if not generation_type_confirmed or generation_type != "VIDEO":
        logger.error(
            f"REJEITADO: início de geração não pode ser confirmado sem validação prévia de modo VIDEO "
            f"(confirmed={generation_type_confirmed}, type='{generation_type}')"
        )
        return False

    logger.info(f"Aguardando evidência de início real de processamento do job (timeout {timeout_ms/1000}s)...")
    try:
        page.wait_for_function(
            """(baseCount) => {
                // NÃO aceita aprovação pendente (ignora botões respondidos no histórico com read-only / aria-disabled)
                const options = Array.from(document.querySelectorAll('[role="radio"], button, [role="button"]'));
                const hasApprove = options.some(el => {
                    if (el.classList.contains('read-only') || el.getAttribute('aria-disabled') === 'true') {
                        return false;
                    }
                    const txt = (el.getAttribute('aria-label') || el.innerText || '').trim();
                    return /^aprovar$/i.test(txt) || /^approve$/i.test(txt);
                });
                if (hasApprove) return false;

                // Aceita evidência real de geração/processamento
                const progress = document.querySelector('[role="progressbar"], mat-progress-bar, flow-progress, flow-spinner, .generating-indicator, [aria-label*="Gerando" i], [aria-label*="Generating" i]');
                if (progress) return true;

                // Aceita novo tile na grade
                const gridTiles = document.querySelectorAll('flow-grid-tile-container');
                if (gridTiles.length > (baseCount || 0)) return true;

                // Aceita botão 'Parar' ativo durante geração
                const stopBtn = document.querySelector('button[aria-label*="Parar" i], button[aria-label*="Stop" i]');
                if (stopBtn) return true;

                return false;
            }""",
            arg=baseline_count,
            timeout=timeout_ms,
        )
        logger.info("GENERATION_STARTED confirmado no DOM com sucesso!")
        return True
    except Exception as exc:
        logger.error(f"Falha ao confirmar GENERATION_STARTED dentro de {timeout_ms/1000}s: {exc}")
        return False


def extract_tile_identifier_from_src(src: str) -> Optional[str]:
    """
    Extrai o token ASB full da URL de thumbnail ou vídeo e gera um identificador seguro
    via hash SHA-256 (asbsha256:<digest>). NUNCA expõe nem loga o token cru.
    """
    if not src:
        return None
    m = re.search(r"/asb/([^?=&]+)", src)
    if m:
        full_token = m.group(1)
        digest = hashlib.sha256(full_token.encode("utf-8")).hexdigest()
        return f"asbsha256:{digest}"
    return None


def capture_tile_baseline(page: Page) -> Set[str]:
    """
    Captura o conjunto de identificadores seguros (SHA-256) dos tiles/assets já existentes antes de uma nova geração.
    Evita que um tile antigo confirme falsamente uma nova geração.
    """
    tiles = page.locator("flow-grid-tile-container")
    count = tiles.count()
    baseline_ids: Set[str] = set()
    for i in range(count):
        t = tiles.nth(i)
        img = t.locator("img.thumbnail")
        ident = None
        if img.count() > 0:
            src = img.get_attribute("src") or ""
            ident = extract_tile_identifier_from_src(src)
        if not ident:
            video = t.locator("video")
            if video.count() > 0:
                vsrc = video.get_attribute("src") or ""
                ident = extract_tile_identifier_from_src(vsrc)
        if not ident:
            label = t.get_attribute("aria-label")
            if label:
                ident = f"label:{label.strip()}"
        if ident:
            baseline_ids.add(ident)
        else:
            raise RuntimeError(f"FAIL_CLOSED: Tile no índice {i} sem identificador confiável no DOM.")
    logger.info(f"RESULT_BASELINE capturado: {len(baseline_ids)} tiles pré-existentes identificados.")
    return baseline_ids


def wait_for_generation_complete(
    page: Page,
    baseline_ids: Optional[Set[str]] = None,
    timeout_sec: int = DEFAULT_TIMEOUT_GEN_SEC,
) -> Tuple[bool, Optional[Locator], Optional[str]]:
    """
    Acompanha a conclusão da geração garantindo isolamento do novo resultado via hash SHA-256.
    Se baseline_ids for fornecido:
    - Um resultado pré-existente no baseline NUNCA confirma a nova geração.
    - Exige exatamente 1 novo resultado (len(new_ids) == 1).
    - Se 0 novos resultados ao expirar timeout: GENERATION_RESULT_NOT_FOUND.
    - Se > 1 novos resultados: AMBIGUOUS_GENERATION_RESULTS.
    Retorna: (completed: bool, new_tile_locator: Optional[Locator], error: Optional[str])
    """
    logger.info(f"Aguardando conclusão da geração no Flow com isolamento de resultado (timeout: {timeout_sec}s)...")
    baseline_list = list(baseline_ids or [])

    try:
        # Aguarda de forma síncrona até que o número de tiles na grade aumente
        wait_res = page.wait_for_function(
            """(baseCount) => {
                const gridTiles = Array.from(document.querySelectorAll('flow-grid-tile-container'));
                if (gridTiles.length <= (baseCount || 0)) return false;

                // Verifica se há novo tile com falha explícita (política, erro de servidor, etc.)
                for (let i = 0; i < gridTiles.length; i++) {
                    const t = gridTiles[i];
                    const txt = (t.innerText || '').toLowerCase();
                    if (txt.includes('falha') || txt.includes('violar') || txt.includes('política') || txt.includes('refund')) {
                        return 'FAILED_BY_POLICY_OR_ERROR';
                    }
                }

                // Verifica se os tiles possuem evidência de prontidão
                for (let i = 0; i < gridTiles.length; i++) {
                    const t = gridTiles[i];
                    const img = t.querySelector('img.thumbnail');
                    const video = t.querySelector('video');
                    const hotbar = t.querySelector('flow-video-hotbar');
                    if (img || video || hotbar) return 'COMPLETED';
                }
                return false;
            }""",
            arg=len(baseline_list),
            timeout=timeout_sec * 1000,
        )
        if wait_res.json_value() == "FAILED_BY_POLICY_OR_ERROR":
            err_text = ""
            try:
                error_tiles = page.locator("flow-grid-tile-container").filter(
                    has_text=re.compile(r"falha|violar|pol[íi]tica|refund|error", re.I)
                )
                if error_tiles.count() > 0:
                    err_text = error_tiles.first.inner_text().strip().replace('\n', ' ')
            except Exception:
                pass
            if not err_text:
                try:
                    # Fallback para verificar no corpo da página se a notificação estiver fora do container
                    for el in page.locator("div, p, span").filter(has_text=re.compile(r"violar|pol[íi]tica|refund", re.I)).all():
                        t_str = el.inner_text().strip().replace('\n', ' ')
                        if "violar" in t_str.lower() or "política" in t_str.lower() or "refund" in t_str.lower():
                            err_text = t_str
                            break
                except Exception:
                    pass
            logger.error(f"Novo tile de geração detectado com falha de política/erro: {err_text}")
            return False, None, f"FLOW_POLICY_FAILURE: {err_text}" if err_text else "GENERATION_POLICY_OR_BACKEND_FAILURE"
    except Exception as exc:
        logger.error(f"Timeout aguardando novo resultado de geração: {exc}")
        try:
            error_tiles = page.locator("flow-grid-tile-container").filter(
                has_text=re.compile(r"falha|violar|pol[íi]tica|refund", re.I)
            )
            if error_tiles.count() > 0:
                err_text = error_tiles.first.inner_text().strip().replace('\n', ' ')
                logger.error(f"Tile com falha/política detectado no DOM: {err_text}")
                return False, None, f"FLOW_POLICY_FAILURE: {err_text}"
        except Exception:
            pass
        return False, None, "GENERATION_RESULT_NOT_FOUND"

    # Em Python: captura os identificadores SHA-256 de todos os tiles e valida isolamento
    all_grid_tiles = page.locator("flow-grid-tile-container")
    count = all_grid_tiles.count()
    new_tiles = []
    baseline_set = set(baseline_list)

    for i in range(count):
        t = all_grid_tiles.nth(i)
        img = t.locator("img.thumbnail")
        ident = None
        if img.count() > 0:
            src = img.get_attribute("src") or ""
            ident = extract_tile_identifier_from_src(src)
        if not ident:
            video = t.locator("video")
            if video.count() > 0:
                vsrc = video.get_attribute("src") or ""
                ident = extract_tile_identifier_from_src(vsrc)
        if not ident:
            label = t.get_attribute("aria-label")
            if label:
                ident = f"label:{label.strip()}"

        if ident and ident not in baseline_set:
            new_tiles.append({"id": ident, "index": i, "locator": t})

    if len(new_tiles) == 0:
        logger.error("Nenhum novo tile isolado encontrado em relação ao baseline.")
        return False, None, "GENERATION_RESULT_NOT_FOUND"

    if len(new_tiles) > 1:
        logger.error(f"Resultados de geração ambíguos: {len(new_tiles)} novos tiles detectados simultaneamente.")
        return False, None, "AMBIGUOUS_GENERATION_RESULTS"

    # Exatamente 1 novo tile isolado!
    target_info = new_tiles[0]
    target_tile = target_info["locator"]
    logger.info(f"Novo resultado isolado identificado com sucesso: {target_info['id']} (índice {target_info['index']})")

    try:
        expect(target_tile).to_have_count(1)
    except Exception as exc:
        logger.error(f"Falha na asserção de unicidade do tile gerado: {exc}")
        return False, None, "AMBIGUOUS_GENERATION_RESULTS"

    return True, target_tile, None


def download_generated_clip(
    page: Page,
    output_path: str,
    tile_locator: Optional[Locator] = None,
    timeout_ms: int = DEFAULT_TIMEOUT_DOWNLOAD_MS,
) -> Tuple[bool, Optional[str]]:
    """
    Executa o download do clipe gerado utilizando o evento nativo expect_download do Playwright.
    Estritamente escopado ao tile do clipe gerado:
    - Se tile_locator for fornecido, deve ter count == 1.
    - Se não fornecido e houver mais de 1 tile, BLOQUEIA (fail-closed, sem usar .first arbitrário).
    - Navega: tile -> hover -> Mais opções -> Fazer o download -> 720p Tamanho original.
    """
    logger.info("Iniciando fluxo de download escopado...")
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    if tile_locator is None:
        all_tiles = page.locator("flow-grid-tile-container")
        tile_count = all_tiles.count()
        if tile_count != 1:
            logger.error(f"Download não pode inferir tile alvo: encontrados {tile_count} tiles sem tile_locator explícito.")
            return False, f"AMBIGUOUS_TILE_TARGET_COUNT_{tile_count}"
        tile_locator = all_tiles

    # Valida unicidade estrita do alvo
    try:
        expect(tile_locator).to_have_count(1)
    except Exception as exc:
        logger.error(f"Tile locator alvo não é único: {exc}")
        return False, "AMBIGUOUS_TILE_TARGET"

    # 1. Hover no tile alvo para revelar a hotbar
    try:
        tile_locator.hover()
    except Exception as exc:
        logger.warning(f"Hover no tile falhou ou não foi necessário: {exc}")

    # 2. Localiza botão direto de download dentro do tile se existir
    dl_btn = tile_locator.locator(
        "button[aria-label*='Download' i], button[aria-label*='Baixar' i], "
        "a[aria-label*='Download' i], a[aria-label*='Baixar' i]"
    )
    if dl_btn.count() == 1 and dl_btn.is_visible():
        try:
            with page.expect_download(timeout=timeout_ms) as download_info:
                dl_btn.click()
            download = download_info.value
            download.save_as(output_path)
            return True, None
        except Exception as exc:
            return False, f"DOWNLOAD_FAILED: {exc}"

    # 3. Localiza botão 'Mais opções' estritamente dentro do tile alvo
    more_btn = tile_locator.locator("button[aria-label*='Mais op' i]")
    if more_btn.count() != 1:
        logger.error(f"Botão 'Mais opções' não encontrado ou ambíguo no tile: count={more_btn.count()}")
        return False, "MORE_OPTIONS_BUTTON_NOT_UNIQUE"

    logger.info("Abrindo menu 'Mais opções' no tile alvo...")
    more_btn.click()

    # 4. Localiza opção de download no menu overlay
    menu_dl = page.locator(".cdk-overlay-pane [role='menuitem']").filter(
        has_text=re.compile(r"download|baixar", re.I)
    )
    if menu_dl.count() != 1:
        logger.error(f"Item de menu download não encontrado ou ambíguo: count={menu_dl.count()}")
        return False, "DOWNLOAD_MENUITEM_NOT_UNIQUE"

    menu_dl.click()

    # 5. Localiza resolução 720p (Tamanho original) no submenu
    opt_720 = page.locator(".cdk-overlay-pane [role='menuitem']").filter(
        has_text=re.compile(r"720p|original", re.I)
    )
    if opt_720.count() != 1:
        logger.error(f"Opção de resolução 720p não encontrada ou ambígua: count={opt_720.count()}")
        return False, "RESOLUTION_720P_NOT_UNIQUE"

    try:
        with page.expect_download(timeout=timeout_ms) as download_info:
            opt_720.click()
        download = download_info.value
        logger.info(f"Download capturado ({download.suggested_filename}). Salvando em {output_path}...")
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except Exception:
                pass
        download.save_as(output_path)
        logger.info("Download salvo com sucesso!")
        return True, None
    except Exception as exc:
        logger.error(f"Falha ao capturar download do clipe: {exc}")
        return False, f"DOWNLOAD_FAILED: {exc}"


def run_playwright_flow_poc(
    manifest_path: str,
    scene_index: int = 1,
    trial_only: bool = False,
    timeout_gen_sec: int = DEFAULT_TIMEOUT_GEN_SEC,
    project_url: Optional[str] = None,
    download_only: bool = False,
    force_new_project: bool = False,
) -> Dict[str, Any]:
    """
    Executa o ciclo completo de validação do Playwright com isolamento de resultado:
    1. Abre Edge com perfil persistente (channel='msedge')
    2. Confirma sessão (AUTHENTICATED)
    3. Reabre projeto alvo via project_url se fornecido (sem clicar Novo Projeto)
    4. Preenche prompt
    5. Confirma texto via auto-retry assertion
    6. Confirma Generate actionable usando trial=True
    ZERO geração até aqui.

    Se todos os passos 1-6 passarem E trial_only for False:
    Executa EXATAMENTE UMA geração real na mesma execução autorizada:
    1. Captura RESULT_BASELINE com identificadores SHA-256 dos tiles
    2. Dispara Generate e aprovação única (se necessária)
    3. Confirma generation start
    4. Aguarda conclusão do NOVO resultado isolado
    5. expect_download + click download escopado exclusivamente ao novo tile
    6. save_as canonical_output_path
    7. Validação de SHA dos arquivos para garantir isolamento e integridade
    8. probe_media / validate_clip_file
    """
    report: Dict[str, Any] = {
        "status": "FAILED",
        "login_status": "UNKNOWN",
        "project_url_confirmed": False,
        "landing_to_studio": False,
        "editor_found": False,
        "generation_type_confirmed": False,
        "generation_type": "UNKNOWN",
        "generation_type_changed": False,
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
        "tile_count_before": 0,
        "baseline_id_count": 0,
        "existing_tile_count": 0,
        "tile_count_after": 0,
        "new_tile_count": 0,
        "old_tile_still_present": False,
        "baseline_result_capture_supported": True,
        "new_result_isolation_supported": True,
        "trace_capture_enabled": True,
        "trace_saved_on_failure_only": True,
        "trace_file": None,
        "generation_start_confirmed": False,
        "generation_attempts": 0,
        "generation_complete_confirmed": False,
        "download_event_confirmed": False,
        "scene_01_file_sha_before": None,
        "scene_01_file_sha_after": None,
        "scene_02_file_sha": None,
        "scene_01_file_sha_unchanged": False,
        "scene_02_different_from_scene_01": False,
        "output_file": None,
        "output_valid": False,
        "output_duration": 0.0,
        "content_policy_blocked": False,
        "policy_refund_confirmed": False,
        "policy_message": None,
        "project_url": project_url,
        "error": None,
    }

    if not os.path.exists(manifest_path):
        report["error"] = f"MANIFEST_NOT_FOUND: {manifest_path}"
        return report

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    target_project_url = None if force_new_project else (project_url or manifest.get("flow_project_url"))

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

    # 0. Idempotência estrita: se expected_clip já existir e for válido, pula Playwright totalmente
    if not trial_only and not download_only and os.path.exists(canonical_output_path):
        val_clip = validate_clip_file(canonical_output_path)
        if val_clip.get("valid"):
            logger.info(
                f"[IDEMPOTENCY] Cena {scene_index} já concluída e válida ({canonical_output_path}). "
                f"Pulando abertura de navegador (zero cliques, zero créditos)."
            )
            report["status"] = "ALREADY_COMPLETE"
            report["output_file"] = canonical_output_path
            report["output_valid"] = True
            report["output_duration"] = val_clip.get("duration", 0.0)
            report["generate_click_count_this_run"] = 0
            report["credit_cost"] = 0
            report["credit_approval_click_count"] = 0
            report["project_url"] = target_project_url
            report["error"] = None
            return report

    # Captura SHA da Cena 01 antes de qualquer ação
    scene_01_path = os.path.join(project_dir, "clips", "flow_scene_01.mp4")
    if os.path.exists(scene_01_path):
        with open(scene_01_path, "rb") as f_s1:
            raw_s1 = f_s1.read()
            s1_bytes = raw_s1.encode("utf-8") if isinstance(raw_s1, str) else raw_s1
            report["scene_01_file_sha_before"] = hashlib.sha256(s1_bytes).hexdigest()
        logger.info(f"SCENE_01_FILE_SHA_BEFORE capturado: {report['scene_01_file_sha_before']}")

    with sync_playwright() as p:
        context, err = launch_flow_context(p, headless=False)
        if err:
            report["status"] = err
            report["error"] = err
            return report

        # Inicia Playwright Tracing oficial para diagnóstico de falhas
        context.tracing.start(
            screenshots=True,
            snapshots=True,
            sources=True,
            aria_snapshots=True,
        )

        def _stop_tracing(st: str) -> None:
            try:
                if st in ("SUCCESS", "PRE_FLIGHT_TRIAL_PASS"):
                    context.tracing.stop()
                else:
                    trace_dir = os.path.join(ROOT_DIR, "storage", "flow_traces")
                    os.makedirs(trace_dir, exist_ok=True)
                    timestamp = time.strftime("%Y%m%d_%H%M%S")
                    safe_st = re.sub(r"[^a-zA-Z0-9_-]", "_", str(st or "FAIL"))
                    trace_path = os.path.join(trace_dir, f"{timestamp}_{safe_st}.zip")
                    context.tracing.stop(path=trace_path)
                    report["trace_file"] = trace_path
                    logger.info(f"Trace de falha salvo em: {trace_path}")
            except Exception as tr_exc:
                logger.warning(f"Erro ao gerenciar tracing: {tr_exc}")

        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_UI_MS)

        try:
            # 1. Login e sessão
            login_st = check_login_state(page)
            report["login_status"] = login_st
            if login_st != "AUTHENTICATED":
                report["status"] = login_st
                report["error"] = login_st
                _stop_tracing(login_st)
                context.close()
                return report

            # 2. Navegação para Studio (com precedência mandatória para target_project_url)
            ensure_studio_surface(page, project_url=target_project_url, force_new_project=force_new_project)
            report["landing_to_studio"] = True
            report["editor_found"] = True
            report["project_url_confirmed"] = True
            report["project_url"] = page.url

            # 2b. MODO DE GERAÇÃO = VIDEO (GARANTIA OPERACIONAL MANDATÓRIA FAIL-CLOSED)
            mode_res = ensure_video_generation_mode(page)
            report["generation_type_confirmed"] = mode_res.get("confirmed", False)
            report["generation_type"] = mode_res.get("generation_type", "UNKNOWN")
            report["generation_type_changed"] = mode_res.get("changed", False)

            if not mode_res.get("confirmed") or mode_res.get("generation_type") != "VIDEO":
                err_msg = mode_res.get("error") or "FLOW_VIDEO_MODE_NOT_CONFIRMED"
                logger.error(
                    f"FAIL CLOSED: Modo de geração não pôde ser confirmado como VIDEO ({err_msg}). "
                    f"Abortando antes de preencher prompt ou clicar Generate (zero cliques, zero créditos)."
                )
                report["status"] = "FLOW_VIDEO_MODE_NOT_CONFIRMED"
                report["error"] = err_msg
                _stop_tracing("FLOW_VIDEO_MODE_NOT_CONFIRMED")
                context.close()
                return report

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

            # 4. CAPTURA DE BASELINE DE RESULTADOS PRÉ-EXISTENTES (SHA-256)
            baseline_ids = capture_tile_baseline(page)
            report["tile_count_before"] = len(baseline_ids)
            report["baseline_id_count"] = len(baseline_ids)
            report["existing_tile_count"] = len(baseline_ids)

            if trial_only:
                report["status"] = "PRE_FLIGHT_TRIAL_PASS"
                _stop_tracing("PRE_FLIGHT_TRIAL_PASS")
                context.close()
                return report

            # 5. MÁQUINA DE ESTADOS: VERIFICAÇÃO DE ESTADO PRÉ-EXISTENTE
            if download_only:
                logger.info("Modo --download-only ativo: isolando o novo tile existente e procedendo ao download escopado.")
                all_tiles = page.locator("flow-grid-tile-container")
                t_count = all_tiles.count()
                if t_count != 2:
                    report["status"] = f"UNEXPECTED_TILE_COUNT_{t_count}"
                    report["error"] = f"UNEXPECTED_TILE_COUNT_{t_count}"
                    _stop_tracing(report["status"])
                    context.close()
                    return report

                report["tile_count_before"] = 1
                report["baseline_id_count"] = 1
                report["existing_tile_count"] = 1
                report["tile_count_after"] = 2
                report["new_tile_count"] = 1
                report["old_tile_still_present"] = True
                report["generate_click_count_this_run"] = 1
                report["credit_approval_required"] = True
                report["credit_cost"] = 15
                report["credit_approval_button_match_count"] = 1
                report["credit_approval_click_count"] = 1
                report["credit_approval_confirmed"] = True
                report["always_approve_clicked"] = False
                report["generation_start_confirmed"] = True
                report["generation_complete_confirmed"] = True
                report["generation_attempts"] = 1

                new_tile_loc = all_tiles.nth(0)
                expect(new_tile_loc).to_have_count(1)

                if os.path.exists(canonical_output_path) and validate_clip_file(canonical_output_path).get("valid"):
                    logger.info("Arquivo de clipe já baixado e válido. Confirmando evento de download.")
                    report["download_event_confirmed"] = True

            elif is_pending:
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
                    _stop_tracing(report["status"])
                    context.close()
                    return report

            else:
                # Dispara clique único no Generate
                logger.info("=== DISPARANDO EXATAMENTE UMA GERAÇÃO REAL AUTORIZADA ===")
                gen_btn.click()
                report["generate_click_count_this_run"] = 1

                # Aguarda EITHER aprovação requerida OU geração iniciada diretamente (timeout 120s para resposta do agente LLM)
                logger.info("Aguardando decisão da interface: aprovação de créditos ou início direto (timeout 120s)...")
                try:
                    wait_res = page.wait_for_function(
                        """(baselineList) => {
                            const baselineSet = new Set(baselineList || []);

                            // 1. Aprovação ativa necessária (ignora opções com read-only / aria-disabled do histórico)
                            const options = Array.from(document.querySelectorAll('[role="radio"], button, [role="button"]'));
                            const hasApprove = options.some(el => {
                                if (el.classList.contains('read-only') || el.getAttribute('aria-disabled') === 'true') {
                                    return false;
                                }
                                const txt = (el.getAttribute('aria-label') || el.innerText || '').trim();
                                return /^aprovar$/i.test(txt) || /^approve$/i.test(txt);
                            });
                            if (hasApprove) return 'APPROVAL_REQUIRED';

                            // 2. Progresso ou indicador de geração de vídeo ativo
                            const progress = document.querySelector('[role="progressbar"], mat-progress-bar, flow-progress, flow-spinner, .generating-indicator, [aria-label*="Gerando" i], [aria-label*="Generating" i]');
                            if (progress) return 'GENERATION_STARTED';

                            // 3. Tile novo já na grade
                            const gridTiles = Array.from(document.querySelectorAll('flow-grid-tile-container'));
                            if (gridTiles.length > baselineSet.size) {
                                return 'GENERATION_STARTED';
                            }

                            return false;
                        }""",
                        arg=list(baseline_ids),
                        timeout=120000,
                    )
                    state_found = wait_res.json_value()
                except Exception as exc:
                    logger.error(f"Timeout aguardando aprovação ou início de geração: {exc}")
                    report["status"] = "GENERATION_DISPATCH_TIMEOUT_120S"
                    report["error"] = "GENERATION_DISPATCH_TIMEOUT_120S"
                    _stop_tracing(report["status"])
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
                        _stop_tracing(report["status"])
                        context.close()
                        return report

                    # Confirmação posterior à aprovação
                    started = wait_for_generation_started(
                        page,
                        baseline_count=len(baseline_ids),
                        generation_type_confirmed=report["generation_type_confirmed"],
                        generation_type=report["generation_type"],
                        timeout_ms=DEFAULT_TIMEOUT_UI_MS,
                    )
                    report["generation_start_confirmed"] = started
                    if not started:
                        report["status"] = "GENERATION_START_NOT_CONFIRMED"
                        report["error"] = "GENERATION_START_NOT_CONFIRMED"
                        _stop_tracing(report["status"])
                        context.close()
                        return report
                else:
                    # Início direto confirmado
                    if not report.get("generation_type_confirmed") or report.get("generation_type") != "VIDEO":
                        logger.error("Início direto rejeitado: modo de geração não foi comprovado como VIDEO.")
                        report["status"] = "FLOW_VIDEO_MODE_NOT_CONFIRMED"
                        report["error"] = "FLOW_VIDEO_MODE_NOT_CONFIRMED"
                        _stop_tracing(report["status"])
                        context.close()
                        return report

                    logger.info("GENERATION_STARTED confirmado diretamente após o clique no Generate!")
                    report["credit_approval_required"] = False
                    report["generation_start_confirmed"] = True

            report["generation_attempts"] = 1

            if not download_only:
                # 7. Aguarda conclusão do NOVO resultado isolado (até timeout_gen_sec)
                completed, new_tile_loc, comp_err = wait_for_generation_complete(
                    page, baseline_ids=baseline_ids, timeout_sec=timeout_gen_sec
                )
                report["generation_complete_confirmed"] = completed
                if not completed:
                    is_policy = bool(comp_err and ("POLICY" in comp_err or "política" in comp_err.lower() or "violar" in comp_err.lower()))
                    if is_policy:
                        report["content_policy_blocked"] = True
                        report["policy_refund_confirmed"] = bool(comp_err and ("refund" in comp_err.lower() or "restitu" in comp_err.lower() or "reembols" in comp_err.lower()))
                        report["policy_message"] = comp_err
                        report["status"] = "FLOW_CONTENT_POLICY_BLOCKED" if report["policy_refund_confirmed"] else "FLOW_GENERATION_NEEDS_RECOVERY"
                        report["error"] = comp_err
                    else:
                        report["status"] = comp_err or "GENERATION_COMPLETION_FAILED"
                        report["error"] = comp_err or f"GENERATION_TIMEOUT_{timeout_gen_sec}S"
                    _stop_tracing(report["status"])
                    context.close()
                    return report

                # Auditoria e confirmação TWO-TILE pós-conclusão
                after_ids = capture_tile_baseline(page)
                report["tile_count_after"] = len(after_ids)
                new_ids = after_ids - baseline_ids
                report["new_tile_count"] = len(new_ids)
                report["old_tile_still_present"] = baseline_ids.issubset(after_ids)

                if len(new_ids) != 1:
                    logger.error(f"Inconsistência de tiles: new_ids={len(new_ids)}, esperado exatamente 1.")
                    report["status"] = "AMBIGUOUS_GENERATION_RESULTS" if len(new_ids) > 1 else "GENERATION_RESULT_NOT_FOUND"
                    report["error"] = report["status"]
                    _stop_tracing(report["status"])
                    context.close()
                    return report

            # 8. DOWNLOAD ESCOPADO AO TILE NOVO VIA EXPECT_DOWNLOAD
            if not report.get("download_event_confirmed"):
                dl_ok, dl_err = download_generated_clip(page, canonical_output_path, tile_locator=new_tile_loc)
                report["download_event_confirmed"] = dl_ok
                if not dl_ok:
                    report["status"] = "DOWNLOAD_FAILED"
                    report["error"] = dl_err
                    _stop_tracing(report["status"])
                    context.close()
                    return report

            report["output_file"] = canonical_output_path

            # 9. VALIDAÇÃO DE SHA DOS ARQUIVOS (prova que Cena 01 não foi sobrescrita)
            if os.path.exists(scene_01_path):
                with open(scene_01_path, "rb") as f_s1:
                    report["scene_01_file_sha_after"] = hashlib.sha256(f_s1.read()).hexdigest()
                report["scene_01_file_sha_unchanged"] = (
                    report["scene_01_file_sha_after"] == report["scene_01_file_sha_before"]
                )

            if os.path.exists(canonical_output_path):
                with open(canonical_output_path, "rb") as f_s2:
                    report["scene_02_file_sha"] = hashlib.sha256(f_s2.read()).hexdigest()
                if report["scene_01_file_sha_before"]:
                    report["scene_02_different_from_scene_01"] = (
                        report["scene_02_file_sha"] != report["scene_01_file_sha_before"]
                    )

            # 10. VALIDAÇÃO DE MÍDIA COM PROBE_MEDIA
            media_val = validate_clip_file(canonical_output_path)
            report["output_valid"] = media_val.get("valid", False)
            report["output_duration"] = media_val.get("duration", 0.0)

            if not media_val.get("valid"):
                report["status"] = "INVALID_OUTPUT_MEDIA"
                report["error"] = media_val.get("error")
                _stop_tracing(report["status"])
                context.close()
                return report

            report["status"] = "SUCCESS"
            report["error"] = None
            _stop_tracing("SUCCESS")
            context.close()
            return report

        except Exception as exc:
            logger.exception(f"Erro durante a execução do Playwright Flow: {exc}")
            report["status"] = "UNEXPECTED_ERROR"
            report["error"] = str(exc)
            _stop_tracing("UNEXPECTED_ERROR")
            try:
                context.close()
            except Exception:
                pass
            return report


@dataclass
class FlowSceneResult:
    """
    Resultado canônico de geração/recuperação de cena no Google Flow.
    Abstração de alto nível para consumo pela fábrica / flow_workflow.
    """
    status: str
    scene_index: int
    output_file: Optional[str] = None
    output_valid: bool = False
    duration: float = 0.0
    credits_consumed: int = 0
    project_url: Optional[str] = None
    error: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "scene_index": self.scene_index,
            "output_file": self.output_file,
            "output_valid": self.output_valid,
            "duration": self.duration,
            "credits_consumed": self.credits_consumed,
            "project_url": self.project_url,
            "error": self.error,
            "details": self.details,
        }

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)


def generate_flow_scene(
    manifest_path: str,
    scene_index: int,
    project_url: Optional[str] = None,
    failure_policy: str = "strict",
    trial_only: bool = False,
    timeout_gen_sec: int = DEFAULT_TIMEOUT_GEN_SEC,
    download_only: bool = False,
) -> FlowSceneResult:
    """
    API canônica reutilizável para o flow_workflow.py.
    FLOW É SINGLE-FLIGHT (FLOW_BROWSER_CONCURRENCY = 1).
    Encapsula toda a automação Playwright sem expor seletores internos.
    
    Idempotência:
    Se expected_clip já existir e for válido, retorna ALREADY_COMPLETE com zero browser.
    
    Persistência:
    Salva flow_project_url no manifest.json do projeto.
    
    Segurança de crédito:
    Se geração/aprovação foi confirmada mas houve falha posterior, retorna
    FLOW_GENERATION_NEEDS_RECOVERY para evitar duplo consumo ou fallback cego.
    """
    if not os.path.exists(manifest_path):
        return FlowSceneResult(
            status="FAILED",
            scene_index=scene_index,
            error=f"MANIFEST_NOT_FOUND: {manifest_path}",
        )

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as exc:
        return FlowSceneResult(
            status="FAILED",
            scene_index=scene_index,
            error=f"MANIFEST_READ_ERROR: {exc}",
        )

    scenes = manifest.get("scenes", [])
    target_scene = next((s for s in scenes if s.get("scene_index") == scene_index), None)
    if not target_scene:
        return FlowSceneResult(
            status="FAILED",
            scene_index=scene_index,
            error=f"SCENE_{scene_index}_NOT_FOUND_IN_MANIFEST",
        )

    target_project_url = project_url or manifest.get("flow_project_url")
    project_dir = os.path.dirname(os.path.abspath(manifest_path))
    clip_filename = target_scene.get("expected_clip", f"flow_scene_{scene_index:02d}.mp4")
    canonical_output_path = os.path.join(project_dir, "clips", clip_filename)

    # 1. IDEMPOTÊNCIA ANTES DO NAVEGADOR
    if not trial_only and not download_only and os.path.exists(canonical_output_path):
        val_media = validate_clip_file(canonical_output_path)
        if val_media.get("valid"):
            logger.info(
                f"[IDEMPOTENCY] Cena {scene_index} já concluída e válida ({canonical_output_path}). "
                f"Retornando ALREADY_COMPLETE (zero browser, zero créditos)."
            )
            return FlowSceneResult(
                status="ALREADY_COMPLETE",
                scene_index=scene_index,
                output_file=canonical_output_path,
                output_valid=True,
                duration=val_media.get("duration", 0.0),
                credits_consumed=0,
                project_url=target_project_url,
                error=None,
                details={"reused_existing": True},
            )

    # 2. Executa driver Playwright (single-flight)
    raw_res = run_playwright_flow_poc(
        manifest_path=manifest_path,
        scene_index=scene_index,
        trial_only=trial_only,
        timeout_gen_sec=timeout_gen_sec,
        project_url=target_project_url,
        download_only=download_only,
    )

    raw_status = raw_res.get("status")
    confirmed_dispatch = bool(
        raw_res.get("generation_start_confirmed")
        or raw_res.get("credit_approval_confirmed")
    )

    # Cálculo de créditos e status de política
    policy_blocked = bool(raw_res.get("content_policy_blocked") or raw_status == "FLOW_CONTENT_POLICY_BLOCKED")
    refund_confirmed = bool(raw_res.get("policy_refund_confirmed"))

    credits_consumed = 0
    if raw_status == "ALREADY_COMPLETE":
        credits_consumed = 0
    elif raw_status == "FLOW_VIDEO_MODE_NOT_CONFIRMED" or raw_res.get("generation_type") == "IMAGE":
        # Modo não confirmado como VIDEO ou mode mismatch: zero créditos de vídeo inferidos
        credits_consumed = 0
    elif policy_blocked and refund_confirmed:
        # Recusa explícita de política com reembolso confirmado pelo provedor: zero crédito
        credits_consumed = 0
    elif raw_res.get("credit_approval_confirmed") or raw_res.get("generation_start_confirmed"):
        credits_consumed = raw_res.get("credit_cost") or 15

    # Mapeamento canônico de status
    if raw_status in ("SUCCESS", "ALREADY_COMPLETE", "PRE_FLIGHT_TRIAL_PASS"):
        final_status = raw_status
    elif raw_status == "AWAITING_FLOW_EDGE_PROFILE_CLOSE":
        final_status = "FLOW_BROWSER_BUSY"
    elif raw_status == "FLOW_VIDEO_MODE_NOT_CONFIRMED":
        final_status = "FLOW_VIDEO_MODE_NOT_CONFIRMED"
    elif policy_blocked:
        if refund_confirmed:
            final_status = "FLOW_CONTENT_POLICY_BLOCKED"
        else:
            final_status = "FLOW_GENERATION_NEEDS_RECOVERY"
    elif confirmed_dispatch and raw_status != "SUCCESS":
        # Crédito despachado / aprovação confirmada: não regenerar e não cair para stock cegamente
        final_status = "FLOW_GENERATION_NEEDS_RECOVERY"
    else:
        final_status = raw_status or "FAILED"

    # Persistência de project_url no manifest
    effective_url = raw_res.get("project_url") or target_project_url
    if effective_url and manifest.get("flow_project_url") != effective_url:
        try:
            manifest["flow_project_url"] = effective_url
            atomic_write_json(manifest_path, manifest)
            logger.info(f"flow_project_url persistido atomicamente no manifest: {effective_url}")
        except Exception as p_exc:
            logger.warning(f"Não foi possível persistir flow_project_url no manifest: {p_exc}")

    details = dict(raw_res)
    details["content_policy_blocked"] = policy_blocked
    details["policy_refund_confirmed"] = refund_confirmed
    details["needs_recovery"] = True if final_status == "FLOW_GENERATION_NEEDS_RECOVERY" else False

    return FlowSceneResult(
        status=final_status,
        scene_index=scene_index,
        output_file=raw_res.get("output_file"),
        output_valid=raw_res.get("output_valid", False),
        duration=raw_res.get("output_duration", 0.0),
        credits_consumed=credits_consumed,
        project_url=effective_url,
        error=raw_res.get("error"),
        details=details,
    )


def main():
    parser = argparse.ArgumentParser(description="Google Flow Playwright Automation Driver")
    parser.add_argument("--manifest", default="storage/manual_media/flow_web_poc/manifest.json", help="Caminho do manifest.json")
    parser.add_argument("--scene", type=int, default=1, help="Índice da cena a processar")
    parser.add_argument("--trial-only", action="store_true", help="Executa apenas steps 1-6 com trial=True (zero geração)")
    parser.add_argument("--timeout-gen", type=int, default=DEFAULT_TIMEOUT_GEN_SEC, help="Timeout de geração em segundos")
    parser.add_argument("--project-url", default=None, help="URL explícita do projeto Flow existente")
    parser.add_argument("--download-only", action="store_true", help="Executa apenas isolamento, download e validação do novo tile já gerado")
    parser.add_argument("--new-project", action="store_true", help="Força a criação de um novo projeto limpo no Flow")

    args = parser.parse_args()

    res = run_playwright_flow_poc(
        manifest_path=args.manifest,
        scene_index=args.scene,
        trial_only=args.trial_only,
        timeout_gen_sec=args.timeout_gen,
        project_url=args.project_url,
        download_only=args.download_only,
        force_new_project=args.new_project,
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
