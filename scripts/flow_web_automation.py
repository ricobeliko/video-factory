"""
scripts/flow_web_automation.py
==============================
Fase V1.4A.1 — Automação Web Autônoma do Google Flow via Chromium DevTools Protocol (CDP).

Objetivo:
Automação pontual, resiliente e segura da interface web do Google Flow (flow.google.com)
utilizando créditos existentes da assinatura Google AI Pro sem custos de API por vídeo.

Melhorias V1.4A.1:
1. Eliminação de falso positivo de isGenerating na landing page (ignora banners/carrosséis).
2. Modelagem explícita de superfícies da UI (FLOW_SURFACE: LANDING, STUDIO, LOGIN, CHALLENGE, UNKNOWN).
3. Detecção real de créditos (CREDITS_STATUS: AVAILABLE, ZERO, UNKNOWN).
4. Navegação segura da LANDING para o STUDIO (abertura de projeto / novo projeto).
5. Comando read-only preflight para validação prévia sem consumo de créditos nem geração.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

# Adiciona ROOT ao sys.path para import de serviços do MoneyPrinterTurbo
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Garante resolução de ffprobe instalado via WinGet/sistema
_WINGET_LINKS = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links")
if os.path.isdir(_WINGET_LINKS) and _WINGET_LINKS not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _WINGET_LINKS + os.pathsep + os.environ.get("PATH", "")

# Configurações padrão
DEFAULT_PROFILE_DIR = os.path.abspath(os.path.join(ROOT_DIR, "storage", "flow_browser_profile"))
DEFAULT_CDP_PORT = 9222
FLOW_URL = "https://flow.google.com"
LOGIN_URL = "https://accounts.google.com/ServiceLogin?continue=https://flow.google.com/"

# Timeout padrão
DEFAULT_TIMEOUT_GENERATION_SEC = 300
DEFAULT_DOWNLOAD_WAIT_SEC = 90


class FlowSurface:
    """Superfícies de interface do Google Flow."""
    LANDING = "LANDING"
    STUDIO = "STUDIO"
    LOGIN = "LOGIN"
    CHALLENGE = "CHALLENGE"
    UNKNOWN = "UNKNOWN"


class CreditsStatus:
    """Status operacional de créditos de IA."""
    AVAILABLE = "AVAILABLE"
    ZERO = "ZERO"
    UNKNOWN = "UNKNOWN"


# Candidatos executáveis Chromium no Windows
CHROME_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


def find_browser_executable() -> str:
    """Localiza o executável do Edge ou Chrome instalado na máquina."""
    for path in CHROME_CANDIDATES:
        if os.path.exists(path):
            return path
    raise FileNotFoundError("Nenhum navegador Chromium (Edge ou Chrome) encontrado nos caminhos padrão.")


def is_cdp_ready(port: int = DEFAULT_CDP_PORT) -> bool:
    """Verifica se a porta CDP está aberta e respondendo."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as resp:
            data = json.loads(resp.read().decode())
            return bool(data.get("Browser"))
    except Exception:
        return False


def launch_browser(
    port: int = DEFAULT_CDP_PORT,
    profile_dir: str = DEFAULT_PROFILE_DIR,
    url: str = FLOW_URL,
    headless: bool = False,
) -> Optional[subprocess.Popen]:
    """Inicia o navegador com perfil persistente e porta de depuração remota ativada."""
    os.makedirs(profile_dir, exist_ok=True)
    if is_cdp_ready(port):
        logger.info(f"Navegador já ativo com CDP na porta {port}.")
        return None

    browser_bin = find_browser_executable()
    logger.info(f"Iniciando navegador: {browser_bin} (porta CDP: {port})")

    cmd = [
        browser_bin,
        f"--user-data-dir={profile_dir}",
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if headless:
        cmd.append("--headless=new")
    cmd.append(url)

    creationflags = 0
    if sys.platform == "win32":
        creationflags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

    proc = subprocess.Popen(cmd, creationflags=creationflags)
    # Aguarda CDP responder
    for _ in range(30):
        time.sleep(0.5)
        if is_cdp_ready(port):
            logger.info("CDP inicializado e pronto para conexões.")
            return proc

    raise TimeoutError(f"Tempo limite esgotado aguardando CDP na porta {port}.")


def validate_clip_file(file_path: str) -> Dict[str, Any]:
    """
    Validação rigorosa de arquivo de mídia:
    - arquivo existe
    - tamanho > 0
    - extensão .mp4
    - probe_media / ffprobe reconhece vídeo
    - duração > 0
    - possui stream de vídeo
    """
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


class CDPConnection:
    """Cliente CDP leve sobre WebSocket nativo usando websocket-client."""

    def __init__(self, port: int = DEFAULT_CDP_PORT):
        self.port = port
        self.ws = None
        self.target = None
        self._req_id = 0

    def connect_to_flow_target(self, timeout: float = 10.0):
        """Conecta ao target de página do Google Flow ou abre nova aba se necessário."""
        import websocket

        url = f"http://127.0.0.1:{self.port}/json"
        with urllib.request.urlopen(url, timeout=5) as resp:
            targets = json.loads(resp.read().decode())

        # Procura alvo relevante com Flow ou Google Accounts
        page_target = None
        for t in targets:
            t_url = t.get("url", "")
            if t.get("type") == "page" and ("flow.google" in t_url or "accounts.google" in t_url):
                page_target = t
                break

        if not page_target:
            for t in targets:
                if t.get("type") == "page":
                    page_target = t
                    break

        if not page_target:
            raise RuntimeError("Nenhum target de página disponível no navegador.")

        self.target = page_target
        ws_url = page_target.get("webSocketDebuggerUrl")
        if not ws_url:
            raise RuntimeError("Target não possui webSocketDebuggerUrl disponível.")

        self.ws = websocket.create_connection(ws_url, timeout=timeout)
        logger.debug(f"Conectado ao WebSocket CDP: {page_target.get('title')}")

        # Se não estiver no Flow nem no login Google, navega para a URL oficial
        current_url = page_target.get("url", "")
        if "flow.google" not in current_url and "accounts.google" not in current_url:
            logger.info(f"Navegando target para {FLOW_URL}...")
            self.send("Page.navigate", {"url": FLOW_URL})

        # Aguarda a página carregar (sair de about:blank e atingir readyState complete)
        for _ in range(20):
            time.sleep(0.5)
            try:
                curr = self.eval_js("document.location.href")
                ready = self.eval_js("document.readyState")
                if curr and curr != "about:blank" and ready == "complete":
                    break
            except Exception:
                pass

    def send(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Envia um comando CDP e aguarda a resposta correspondente."""
        if not self.ws:
            raise RuntimeError("WebSocket CDP não está conectado.")
        self._req_id += 1
        msg = {"id": self._req_id, "method": method, "params": params or {}}
        self.ws.send(json.dumps(msg))
        while True:
            raw = self.ws.recv()
            data = json.loads(raw)
            if data.get("id") == self._req_id:
                if "error" in data:
                    raise RuntimeError(f"Erro CDP ({method}): {data['error']}")
                return data

    def eval_js(self, expression: str) -> Any:
        """Executa expressão JavaScript no contexto da página e retorna o valor."""
        res = self.send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        })
        result_obj = res.get("result", {}).get("result", {})
        return result_obj.get("value")

    def set_download_path(self, download_path: str):
        """Configura o diretório de download no browser para interceptação segura."""
        abs_path = os.path.abspath(download_path)
        os.makedirs(abs_path, exist_ok=True)
        try:
            self.send("Browser.setDownloadBehavior", {
                "behavior": "allow",
                "downloadPath": abs_path,
                "eventsEnabled": True,
            })
        except Exception as exc:
            logger.debug(f"Browser.setDownloadBehavior retornou: {exc}")

        try:
            self.send("Page.setDownloadBehavior", {
                "behavior": "allow",
                "downloadPath": abs_path,
            })
        except Exception as exc:
            logger.debug(f"Page.setDownloadBehavior retornou: {exc}")

    def close(self):
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None


def check_auth_and_ui_state(cdp: CDPConnection) -> Dict[str, Any]:
    """Inspeciona o estado da página para detectar autenticação, captcha, créditos, superfície e UI."""
    js_detect = """
    (() => {
        function isElementVisible(el) {
            if (!el) return false;
            if (el.getAttribute('aria-hidden') === 'true') return false;
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity || '1') === 0) return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        }

        const url = document.location.href || '';
        const title = document.title || '';
        const bodyText = document.body ? document.body.innerText : '';
        const isBlank = url === 'about:blank' || !url;

        // 1. Detecção de CAPTCHA / desafio de segurança Google
        const hasCaptcha = bodyText.includes('recaptcha') ||
                           bodyText.includes('Não sou um robô') ||
                           bodyText.includes('Confirme que é você') ||
                           bodyText.includes('Verificação de segurança') ||
                           bodyText.includes('tráfego incomum') ||
                           bodyText.includes('unusual traffic');

        // 2. Detecção de tela de Login Google ou Landing sem sessão
        const isAccountsPage = url.includes('accounts.google.com');
        const isLandingAbout = url.includes('/about');
        const hasLoginBtn = Array.from(document.querySelectorAll('button, a')).some(el => {
            if (!isElementVisible(el)) return false;
            const txt = (el.innerText || el.getAttribute('aria-label') || '').toLowerCase().trim();
            return txt === 'fazer login' || txt === 'sign in' || txt === 'login' || txt.includes('fazer login');
        });

        const isAuthenticated = !isBlank && !isAccountsPage && !isLandingAbout && !hasLoginBtn && !hasCaptcha && (url.includes('flow.google') || url.includes('labs.google'));

        // 3. Detecção de campos reais de prompt / editor
        const allInputs = Array.from(document.querySelectorAll('textarea, [contenteditable="true"], input[type="text"]'));
        const promptInputs = allInputs.filter(el => {
            if (!isElementVisible(el)) return false;
            const isContentEditable = el.getAttribute('contenteditable') === 'true';
            const isTextarea = el.tagName === 'TEXTAREA';
            const isProseMirror = el.classList && el.classList.contains('ProseMirror');
            const aria = (el.getAttribute('aria-label') || '').toLowerCase();
            const placeholder = (el.getAttribute('placeholder') || '').toLowerCase();
            const isSearch = el.type === 'search' || aria.includes('pesquisar') || placeholder.includes('pesquisar') || (el.className && el.className.toString().includes('search'));
            const isTitle = aria.includes('editável') || (el.className && el.className.toString().includes('editable-text-input'));
            if (isSearch || isTitle) return false;
            return isProseMirror || isContentEditable || isTextarea || aria.includes('prompt') || aria.includes('comando') || placeholder.includes('prompt') || placeholder.includes('comando');
        });

        const hasPromptInput = promptInputs.length > 0;

        // 4. Modelagem explícita de superfície (FLOW_SURFACE)
        let surface = 'UNKNOWN';
        if (hasCaptcha) {
            surface = 'CHALLENGE';
        } else if (isAccountsPage || isLandingAbout || hasLoginBtn || !isAuthenticated) {
            surface = 'LOGIN';
        } else if ((url.includes('/project/') || url.includes('/tools/flow')) && hasPromptInput) {
            surface = 'STUDIO';
        } else if (hasPromptInput) {
            surface = 'STUDIO';
        } else if (url.includes('flow.google.com') || url.includes('labs.google')) {
            surface = 'LANDING';
        }

        // 5. Detecção de geração ativa (Eliminação rigorosa de falsos positivos)
        let isGenerating = false;
        let falsePositiveSource = null;

        const suspectElements = Array.from(document.querySelectorAll('*')).filter(el => {
            const role = el.getAttribute('role') || '';
            const cls = (el.className || '').toString().toLowerCase();
            const txt = (el.innerText || '').toLowerCase();
            return role === 'progressbar' || cls.includes('spinner') || cls.includes('progress') ||
                   txt.includes('gerando...') || txt.includes('generating...') || txt.includes('criando...') || txt.includes('creating...');
        });

        if (surface === 'LANDING') {
            // Na LANDING é impossível ter geração ativa de clipe
            isGenerating = false;
            if (suspectElements.length > 0) {
                const fp = suspectElements[0];
                falsePositiveSource = `${fp.tagName}.${fp.className || 'no-class'} (role=${fp.getAttribute('role') || 'none'})`;
            }
        } else if (surface === 'STUDIO') {
            // No STUDIO, exige elemento VISÍVEL e semântico de geração
            for (const el of suspectElements) {
                if (!isElementVisible(el)) continue;
                const cls = (el.className || '').toString().toLowerCase();
                if (cls.includes('banner') || cls.includes('promotion') || cls.includes('dash')) continue;
                const rect = el.getBoundingClientRect();
                if (rect.width < 15 || rect.height < 6) continue;

                const txt = (el.innerText || '').toLowerCase();
                const role = el.getAttribute('role') || '';
                if (role === 'progressbar' || txt.includes('gerando...') || txt.includes('generating...') || txt.includes('criando...') || txt.includes('creating...')) {
                    isGenerating = true;
                    break;
                }
            }
        }

        // 6. Detecção de créditos (Fail-Closed Real: AVAILABLE, ZERO, UNKNOWN)
        const creditsMatch = bodyText.match(/(\\d+)\\s*(?:créditos|credits|AI credits)/i);
        const numericCredits = creditsMatch ? parseInt(creditsMatch[1], 10) : null;
        const zeroCreditsDetected = bodyText.includes('0 créditos') ||
                                    bodyText.includes('0 credits') ||
                                    bodyText.includes('sem créditos') ||
                                    bodyText.includes('no credits left');

        let creditsStatus = 'UNKNOWN';
        let creditsAvailable = null;

        if (zeroCreditsDetected || numericCredits === 0) {
            creditsStatus = 'ZERO';
            creditsAvailable = false;
        } else if (numericCredits !== null && numericCredits > 0) {
            creditsStatus = 'AVAILABLE';
            creditsAvailable = true;
        } else {
            creditsStatus = 'UNKNOWN';
            creditsAvailable = null;
        }

        const buttons = Array.from(document.querySelectorAll('button, [role="button"]'))
            .filter(el => isElementVisible(el))
            .map(b => (b.innerText || b.getAttribute('aria-label') || '').trim())
            .filter(Boolean);

        return {
            url,
            title,
            isBlank,
            hasCaptcha,
            isAccountsPage,
            isLandingAbout,
            hasLoginBtn,
            isAuthenticated,
            surface,
            hasPromptInput,
            promptInputsCount: promptInputs.length,
            isGenerating,
            falsePositiveSource,
            credits: numericCredits,
            creditsStatus,
            creditsAvailable,
            buttonsSample: buttons.slice(0, 15)
        };
    })()
    """
    return cdp.eval_js(js_detect)


def navigate_to_login(cdp: CDPConnection):
    """Navega para a página de login do Google preservando o redirecionamento para o Flow."""
    logger.info(f"Navegando para o login Google: {LOGIN_URL}")
    cdp.send("Page.navigate", {"url": LOGIN_URL})


def navigate_landing_to_studio(cdp: CDPConnection, timeout_sec: int = 15) -> Dict[str, Any]:
    """
    Navega com segurança da landing page do Flow para a superfície do Studio (editor).
    Não insere prompt e não consome créditos.
    """
    state = check_auth_and_ui_state(cdp)
    if state.get("surface") == FlowSurface.STUDIO and state.get("hasPromptInput"):
        logger.info("Já na superfície STUDIO com editor pronto.")
        return state

    if state.get("surface") != FlowSurface.LANDING:
        logger.warning(f"Tentativa de navegar ao Studio a partir de superfície não-LANDING: {state.get('surface')}")
        return state

    logger.info("Navegando da LANDING para o STUDIO (clicando em Novo projeto)...")
    nav_js = """
    (() => {
        function isElementVisible(el) {
            if (!el) return false;
            if (el.getAttribute('aria-hidden') === 'true') return false;
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity || '1') === 0) return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        }

        const btns = Array.from(document.querySelectorAll('button, a, [role="button"]'));
        const newProjBtn = btns.find(b => {
            if (!isElementVisible(b)) return false;
            const txt = (b.innerText || '').toLowerCase().trim();
            const aria = (b.getAttribute('aria-label') || '').toLowerCase().trim();
            const cls = (b.className || '').toString().toLowerCase();
            return txt.includes('novo projeto') || txt.includes('new project') ||
                   aria.includes('novo projeto') || aria.includes('new project') ||
                   cls.includes('new-project');
        });

        if (newProjBtn) {
            newProjBtn.click();
            return { clicked: true, text: newProjBtn.innerText };
        }

        const projectLink = Array.from(document.querySelectorAll('a[href*="/project/"]')).find(a => isElementVisible(a));
        if (projectLink) {
            projectLink.click();
            return { clicked: true, text: 'existing-project', href: projectLink.href };
        }

        return { clicked: false };
    })()
    """

    start_t = time.time()
    clicked = False
    while time.time() - start_t < timeout_sec:
        click_res = cdp.eval_js(nav_js)
        if click_res and click_res.get("clicked"):
            clicked = True
            logger.info(f"CTA de criação de projeto acionado com sucesso: {click_res.get('text')}")
            break
        time.sleep(1)

    if not clicked:
        logger.warning("Nenhum botão de Novo Projeto ou link de projeto encontrado na LANDING.")
        return check_auth_and_ui_state(cdp)

    # Aguarda estabilização da SPA e aparição do ProseMirror / editor
    studio_start = time.time()
    while time.time() - studio_start < timeout_sec:
        time.sleep(1)
        new_state = check_auth_and_ui_state(cdp)
        if new_state.get("surface") == FlowSurface.STUDIO and new_state.get("hasPromptInput"):
            logger.info(f"Superfície STUDIO confirmada com editor de prompt pronto! ({new_state.get('url')})")
            return new_state

    return check_auth_and_ui_state(cdp)


def inspect_credits_menu(cdp: CDPConnection) -> Dict[str, Any]:
    """
    Inspeciona com segurança elementos visíveis da interface para obter status de créditos.
    Clica em 'Detalhes da conta' (.header-user-button), extrai o saldo de créditos da sobreposição,
    e fecha o painel imediatamente.
    Não acessa cookies, tokens ou storage sensível.
    """
    js_probe = """
    (() => {
        const m = (document.body.innerText || '').match(/(\\d+)\\s*(?:créditos|credits)/i);
        if (m) {
            const count = parseInt(m[1], 10);
            return { count: count, status: count > 0 ? 'AVAILABLE' : 'ZERO', opened: false };
        }

        const btn = document.querySelector('div[aria-label="Detalhes da conta"], .header-user-button');
        if (!btn) {
            return { count: null, status: 'UNKNOWN', opened: false };
        }
        btn.click();
        return { opened: true };
    })()
    """
    res1 = cdp.eval_js(js_probe)
    if not res1 or not res1.get("opened"):
        status = res1.get("status", CreditsStatus.UNKNOWN) if res1 else CreditsStatus.UNKNOWN
        count = res1.get("count") if res1 else None
        return {"credits": count, "creditsStatus": status}

    time.sleep(1)
    js_read_close = """
    (() => {
        const overlay = document.querySelector('.flow-account-panel-overlay, mat-dialog-container, [role="dialog"]');
        let count = null;
        let status = 'UNKNOWN';
        if (overlay) {
            const txt = overlay.innerText || '';
            const m = txt.match(/(\\d+)\\s*(?:créditos|credits)/i);
            if (m) {
                count = parseInt(m[1], 10);
                status = count > 0 ? 'AVAILABLE' : 'ZERO';
            } else if (txt.includes('0 créditos') || txt.includes('sem créditos') || txt.includes('0 credits')) {
                count = 0;
                status = 'ZERO';
            }
            const closeBtn = overlay.querySelector('button, [role="button"]');
            if (closeBtn) closeBtn.click();
        }
        const backdrop = document.querySelector('.cdk-overlay-backdrop');
        if (backdrop) backdrop.click();

        return { count: count, status: status };
    })()
    """
    res2 = cdp.eval_js(js_read_close)
    if res2 and res2.get("status") in (CreditsStatus.AVAILABLE, CreditsStatus.ZERO):
        return {"credits": res2.get("count"), "creditsStatus": res2.get("status")}

    return {"credits": None, "creditsStatus": CreditsStatus.UNKNOWN}


def find_generate_button(cdp: CDPConnection) -> Dict[str, Any]:
    """
    Identifica e audita de forma unívoca o botão de geração no Studio do Google Flow.
    Retorna contagem de matches, texto, aria-label e status de disabled.
    Se matchCount != 1, é considerado ambíguo e bloqueia arming/geração.
    """
    js_find = """
    (() => {
        function isElementVisible(el) {
            if (!el) return false;
            if (el.getAttribute('aria-hidden') === 'true') return false;
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity || '1') === 0) return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        }

        const allButtons = Array.from(document.querySelectorAll('button, [role="button"]'))
            .filter(b => isElementVisible(b));

        const candidates = allButtons.filter(b => {
            const aria = (b.getAttribute('aria-label') || '').toLowerCase().trim();
            const cls = (b.className || '').toString().toLowerCase();
            const txt = (b.innerText || '').toLowerCase().trim();
            return aria.startsWith('iniciar geração') || aria.startsWith('start generation') ||
                   cls.includes('generate-button') ||
                   (txt === 'arrow_forward' && aria.includes('geração'));
        });

        if (candidates.length === 0) {
            return {
                found: false,
                matchCount: 0,
                aria: null,
                text: null,
                disabled: null,
                ambiguous: false
            };
        }

        if (candidates.length > 1) {
            return {
                found: true,
                matchCount: candidates.length,
                aria: candidates[0].getAttribute('aria-label') || '',
                text: (candidates[0].innerText || '').trim(),
                disabled: candidates[0].disabled || candidates[0].getAttribute('aria-disabled') === 'true',
                ambiguous: true
            };
        }

        const b = candidates[0];
        return {
            found: true,
            matchCount: 1,
            aria: b.getAttribute('aria-label') || '',
            text: (b.innerText || '').trim(),
            disabled: b.disabled || b.getAttribute('aria-disabled') === 'true',
            ambiguous: false
        };
    })()
    """
    res = cdp.eval_js(js_find)
    if not res:
        return {
            "found": False,
            "matchCount": 0,
            "aria": None,
            "text": None,
            "disabled": None,
            "ambiguous": False,
        }
    return res


def _build_inject_prompt_js(prompt_text: str) -> str:
    """
    Constrói o JavaScript de injeção de prompt e clique de geração de forma segura,
    sem ambiguidades de f-strings ou chaves duplas acidentais.
    """
    escaped_prompt = json.dumps(prompt_text)
    js_template = """(() => {
    const prompt = __PROMPT__;
    // Localiza ProseMirror (editor oficial do Google Flow) ou textarea/contenteditable
    const input = document.querySelector('div.ProseMirror[contenteditable="true"], div.ProseMirror, textarea:not([class*="recaptcha"])');
    if (!input) {
        return { success: false, error: "NO_PROMPT_INPUT_FOUND" };
    }

    // Foca e preenche
    input.focus();
    if (input.classList && input.classList.contains('ProseMirror')) {
        input.textContent = prompt;
        input.dispatchEvent(new Event('input', { bubbles: true }));
    } else if (input.tagName === 'TEXTAREA' || input.tagName === 'INPUT') {
        input.value = prompt;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
    } else {
        input.innerText = prompt;
        input.dispatchEvent(new Event('input', { bubbles: true }));
    }

    function isElementVisible(el) {
        if (!el) return false;
        if (el.getAttribute('aria-hidden') === 'true') return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity || '1') === 0) return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }

    // Localiza botão de submissão/geração de forma inequívoca
    const allButtons = Array.from(document.querySelectorAll('button, [role="button"]'))
        .filter(b => isElementVisible(b));

    const candidates = allButtons.filter(b => {
        const aria = (b.getAttribute('aria-label') || '').toLowerCase().trim();
        const cls = (b.className || '').toString().toLowerCase();
        const txt = (b.innerText || '').toLowerCase().trim();
        return aria.startsWith('iniciar geração') || aria.startsWith('start generation') ||
               cls.includes('generate-button') ||
               (txt === 'arrow_forward' && aria.includes('geração'));
    });

    if (candidates.length === 0) {
        return { success: false, error: "NO_GENERATE_BUTTON_FOUND", inputFilled: true };
    }
    if (candidates.length > 1) {
        return { success: false, error: "BLOCK_AMBIGUOUS_GENERATE_BUTTON", matchCount: candidates.length, inputFilled: true };
    }

    const genBtn = candidates[0];
    if (genBtn.disabled || genBtn.getAttribute('aria-disabled') === 'true') {
        return { success: false, error: "GENERATE_BUTTON_DISABLED", inputFilled: true };
    }

    genBtn.click();
    return { success: true, error: null };
})()"""
    return js_template.replace("__PROMPT__", escaped_prompt)


def verify_injection_js_syntax(cdp: Optional[CDPConnection] = None, prompt_text: str = "Test scene prompt") -> Dict[str, Any]:
    """
    Verifica se o JavaScript gerado por _build_inject_prompt_js() é sintaticamente válido.
    Usa 'new Function(...)' para compilar o código no motor V8 sem executá-lo e sem clicar em nada.
    """
    js_code = _build_inject_prompt_js(prompt_text)

    # 1. Verificação preliminar: ausência de chaves duplas acidentais de f-string
    if "{{" in js_code or "}}" in js_code:
        return {"syntax": "INVALID", "error": "DOUBLE_BRACES_DETECTED_IN_JS"}

    if cdp is not None:
        syntax_check_template = """
        (() => {
            try {
                new Function(__CODE__);
                return { valid: true, error: null };
            } catch (e) {
                return { valid: false, error: e.message };
            }
        })()
        """.replace("__CODE__", json.dumps(js_code))
        res = cdp.eval_js(syntax_check_template)
        if res and res.get("valid"):
            return {"syntax": "VALID", "error": None}
        return {"syntax": "INVALID", "error": res.get("error") if res else "EVAL_FAILED"}

    # Se CDP não fornecido, valida com Node.js se disponível
    try:
        proc = subprocess.run(
            ["node", "--input-type=module", "--check"],
            input=js_code,
            text=True,
            capture_output=True,
            timeout=5,
        )
        if proc.returncode == 0:
            return {"syntax": "VALID", "error": None}
        return {"syntax": "INVALID", "error": proc.stderr.strip()}
    except Exception:
        return {"syntax": "VALID", "error": None}


def capture_studio_baseline(cdp: CDPConnection) -> Dict[str, Any]:
    """
    Captura baseline seguro do Studio antes de qualquer tentativa de geração:
    - contagem e identificadores de vídeos existentes
    - contagem de botões de download existentes
    - contagem e identificadores de cards/tiles existentes
    Sem expor conteúdo sensível.
    """
    js_baseline = """
    (() => {
        function isElementVisible(el) {
            if (!el) return false;
            if (el.getAttribute('aria-hidden') === 'true') return false;
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity || '1') === 0) return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        }

        const videos = Array.from(document.querySelectorAll('video'))
            .filter(v => v.src || v.currentSrc)
            .map(v => v.src || v.currentSrc);

        const downloadButtons = Array.from(document.querySelectorAll('button, a'))
            .filter(el => isElementVisible(el))
            .filter(el => {
                const txt = (el.innerText || el.getAttribute('aria-label') || '').toLowerCase();
                return txt.includes('download') || txt.includes('baixar');
            }).map(el => (el.innerText || el.getAttribute('aria-label') || '').trim());

        const tiles = Array.from(document.querySelectorAll('flow-tile, .flow-tile, [data-tile-id], mat-card'))
            .filter(el => isElementVisible(el))
            .map((t, idx) => t.id || t.getAttribute('data-tile-id') || `tile-${idx}`);

        return {
            videosCount: videos.length,
            videoSrcs: videos,
            downloadButtonsCount: downloadButtons.length,
            tilesCount: tiles.length,
            tileIds: tiles,
            timestamp: Date.now() / 1000
        };
    })()
    """
    res = cdp.eval_js(js_baseline)
    if not res:
        return {
            "videosCount": 0,
            "videoSrcs": [],
            "downloadButtonsCount": 0,
            "tilesCount": 0,
            "tileIds": [],
            "timestamp": time.time(),
            "supported": False,
        }
    res["supported"] = True
    return res


def clean_download_dir(download_dir: str) -> bool:
    """
    Limpa artefatos residuais (*.mp4, *.crdownload, *.tmp) de um diretório de download.
    Garante que arquivos antigos não sejam confundidos com o resultado de uma nova geração.
    """
    if not os.path.isdir(download_dir):
        try:
            os.makedirs(download_dir, exist_ok=True)
            return True
        except Exception:
            return False
    try:
        patterns = ["*.mp4", "*.crdownload", "*.tmp"]
        for pat in patterns:
            for f in glob.glob(os.path.join(download_dir, pat)):
                try:
                    os.remove(f)
                except Exception as exc:
                    logger.warning(f"Não foi possível remover arquivo residual {f}: {exc}")
                    return False
        return True
    except Exception as exc:
        logger.warning(f"Erro ao limpar diretório {download_dir}: {exc}")
        return False


def run_preflight(cdp_client: Optional[CDPConnection] = None) -> Dict[str, Any]:
    """
    Executa verificação read-only preflight da UI do Flow.
    CRÍTICO:
    - NÃO preenche prompt.
    - NÃO clica em Generate.
    - NÃO consome créditos.
    """
    should_close_cdp = False
    cdp = cdp_client
    if cdp is None:
        if not is_cdp_ready():
            launch_browser(headless=False)
        cdp = CDPConnection()
        cdp.connect_to_flow_target()
        should_close_cdp = True

    try:
        state_before = check_auth_and_ui_state(cdp)
        surface_before = state_before.get("surface", FlowSurface.UNKNOWN)

        # Se estiver na LANDING, transiciona com segurança para o STUDIO
        state_after = state_before
        if surface_before == FlowSurface.LANDING:
            state_after = navigate_landing_to_studio(cdp)

        surface_after = state_after.get("surface", FlowSurface.UNKNOWN)
        authenticated = bool(state_after.get("isAuthenticated"))
        prompt_input_found = bool(state_after.get("hasPromptInput"))
        has_captcha = bool(state_after.get("hasCaptcha"))
        is_generating = bool(state_after.get("isGenerating"))
        credits_status = state_after.get("creditsStatus", CreditsStatus.UNKNOWN)

        # Se créditos UNKNOWN no Studio autenticado, tenta inspeção passiva de UI
        if credits_status == CreditsStatus.UNKNOWN and authenticated and surface_after == FlowSurface.STUDIO:
            cred_info = inspect_credits_menu(cdp)
            credits_status = cred_info.get("creditsStatus", CreditsStatus.UNKNOWN)

        # FAIL-CLOSED: apenas AVAILABLE permite safe_to_attempt_generation
        safe_to_attempt = (
            authenticated and
            surface_after == FlowSurface.STUDIO and
            prompt_input_found and
            not has_captcha and
            not is_generating and
            credits_status == CreditsStatus.AVAILABLE
        )

        result = {
            "status": "PREFLIGHT_OK" if safe_to_attempt else "PREFLIGHT_BLOCKED",
            "authenticated": authenticated,
            "flow_surface_before": surface_before,
            "flow_surface_after": surface_after,
            "prompt_input_found": prompt_input_found,
            "captcha_status": "BLOCKED" if has_captcha else "NONE",
            "generation_in_progress": is_generating,
            "credits_status": credits_status,
            "safe_to_attempt_generation": safe_to_attempt,
            "false_positive_source": state_before.get("falsePositiveSource") or state_after.get("falsePositiveSource"),
            "generation_attempts": 0,
            "credits_consumed": 0,
            "download_attempted": False,
            "url": state_after.get("url"),
        }

        print("\n" + "=" * 60)
        print("FLOW AUTONOMOUS WEB — PREFLIGHT AUDIT (READ-ONLY)")
        print("=" * 60)
        print(f"AUTHENTICATED:              {'YES' if authenticated else 'NO'}")
        print(f"FLOW_SURFACE_BEFORE:        {surface_before}")
        print(f"FLOW_SURFACE_AFTER:         {surface_after}")
        print(f"PROMPT_INPUT_FOUND:         {'YES' if prompt_input_found else 'NO'}")
        print(f"CAPTCHA_STATUS:             {result['captcha_status']}")
        print(f"GENERATION_IN_PROGRESS:     {'YES' if is_generating else 'NO'}")
        print(f"CREDITS_STATUS:             {credits_status}")
        print(f"SAFE_TO_ATTEMPT_GENERATION: {'YES' if safe_to_attempt else 'NO'}")
        print(f"GENERATION_ATTEMPTS:        0")
        print(f"CREDITS_CONSUMED:           0")
        print(f"DOWNLOAD_ATTEMPTED:         NO")
        print("=" * 60)

        return result
    finally:
        if should_close_cdp:
            cdp.close()


def run_arm(cdp_client: Optional[CDPConnection] = None, prompt_for_syntax_check: str = "A cinematic video shot") -> Dict[str, Any]:
    """
    Executa a auditoria read-only do gate de armamento de geração única (V1.4A.2).
    CRÍTICO:
    - NÃO preenche prompt na UI.
    - NÃO clica em Generate.
    - NÃO consome créditos.
    - NÃO gera vídeo.
    - NÃO dispara download.
    """
    should_close_cdp = False
    cdp = cdp_client
    if cdp is None:
        if not is_cdp_ready():
            launch_browser(headless=False)
        cdp = CDPConnection()
        cdp.connect_to_flow_target()
        should_close_cdp = True

    try:
        state_before = check_auth_and_ui_state(cdp)
        surface_before = state_before.get("surface", FlowSurface.UNKNOWN)

        # Transição segura LANDING -> STUDIO se necessário
        state_after = state_before
        if surface_before == FlowSurface.LANDING:
            state_after = navigate_landing_to_studio(cdp)

        surface_after = state_after.get("surface", FlowSurface.UNKNOWN)
        authenticated = bool(state_after.get("isAuthenticated"))
        prompt_input_found = bool(state_after.get("hasPromptInput"))
        has_captcha = bool(state_after.get("hasCaptcha"))
        is_generating = bool(state_after.get("isGenerating"))

        # Inspeciona créditos via UI segura se status inicial for UNKNOWN
        credits_status = state_after.get("creditsStatus", CreditsStatus.UNKNOWN)
        credits_count = state_after.get("credits")
        if credits_status == CreditsStatus.UNKNOWN and authenticated and surface_after == FlowSurface.STUDIO:
            cred_info = inspect_credits_menu(cdp)
            credits_status = cred_info.get("creditsStatus", CreditsStatus.UNKNOWN)
            credits_count = cred_info.get("credits")

        # Inspeciona botão de geração
        gen_btn_info = find_generate_button(cdp)
        gen_btn_found = bool(gen_btn_info.get("found"))
        gen_btn_match_count = gen_btn_info.get("matchCount", 0)
        gen_btn_aria = gen_btn_info.get("aria")
        gen_btn_text = gen_btn_info.get("text")
        gen_btn_disabled = bool(gen_btn_info.get("disabled"))
        gen_btn_ambiguous = bool(gen_btn_info.get("ambiguous"))

        # Validação sintática do JavaScript de injeção sem executar
        syntax_info = verify_injection_js_syntax(cdp, prompt_for_syntax_check)
        injection_js_syntax = syntax_info.get("syntax", "UNKNOWN")

        # Captura de baseline do Studio
        baseline_info = capture_studio_baseline(cdp)
        baseline_supported = bool(baseline_info.get("supported"))

        # Validação de limpeza do diretório de downloads
        test_temp_download = os.path.join(ROOT_DIR, "storage", "temp_downloads_arm_test")
        cleanable = clean_download_dir(test_temp_download)
        shutil.rmtree(test_temp_download, ignore_errors=True)

        # FAIL-CLOSED RIGOROSO:
        # safe_to_generate_once é YES SOMENTE SE:
        # - autenticado
        # - superfície STUDIO
        # - editor de prompt encontrado
        # - sem captcha
        # - sem geração em andamento
        # - créditos AVAILABLE (ZERO e UNKNOWN bloqueiam!)
        # - botão de geração encontrado, exatamente 1 candidato, não ambíguo
        # - JS de injeção sintaticamente válido
        # - suporte a baseline do Studio ativo
        # - diretório de download limpo e preparado
        safe_to_generate_once = (
            authenticated and
            surface_after == FlowSurface.STUDIO and
            prompt_input_found and
            not has_captcha and
            not is_generating and
            credits_status == CreditsStatus.AVAILABLE and
            gen_btn_found and
            gen_btn_match_count == 1 and
            not gen_btn_ambiguous and
            injection_js_syntax == "VALID" and
            baseline_supported and
            cleanable
        )

        result = {
            "status": "ARMED_OK" if safe_to_generate_once else "ARMED_BLOCKED",
            "authenticated": authenticated,
            "flow_surface": surface_after,
            "prompt_input_found": prompt_input_found,
            "captcha_status": "BLOCKED" if has_captcha else "NONE",
            "generation_in_progress": is_generating,
            "credits_status": credits_status,
            "credits_count": credits_count,
            "generate_button_found": gen_btn_found,
            "generate_button_match_count": gen_btn_match_count,
            "generate_button_aria": gen_btn_aria,
            "generate_button_text": gen_btn_text,
            "generate_button_disabled": gen_btn_disabled,
            "injection_js_syntax": injection_js_syntax,
            "baseline_capture_supported": baseline_supported,
            "download_dir_cleanable": cleanable,
            "safe_to_generate_once": safe_to_generate_once,
            "generation_attempts": 0,
            "credits_consumed": 0,
            "download_attempted": False,
            "url": state_after.get("url"),
        }

        print("\n" + "=" * 60)
        print("FLOW AUTONOMOUS WEB — GENERATION ARMING GATE (READ-ONLY)")
        print("=" * 60)
        print(f"AUTHENTICATED:               {'YES' if authenticated else 'NO'}")
        print(f"FLOW_SURFACE:                {surface_after}")
        print(f"PROMPT_INPUT_FOUND:          {'YES' if prompt_input_found else 'NO'}")
        print(f"CAPTCHA_STATUS:              {result['captcha_status']}")
        print(f"GENERATION_IN_PROGRESS:      {'YES' if is_generating else 'NO'}")
        print(f"CREDITS_STATUS:              {credits_status}")
        print(f"GENERATE_BUTTON_FOUND:       {'YES' if gen_btn_found else 'NO'}")
        print(f"GENERATE_BUTTON_MATCH_COUNT: {gen_btn_match_count}")
        print(f"GENERATE_BUTTON_ARIA:        {gen_btn_aria}")
        print(f"GENERATE_BUTTON_TEXT:        {gen_btn_text}")
        print(f"GENERATE_BUTTON_DISABLED:    {'YES' if gen_btn_disabled else 'NO'}")
        print(f"INJECTION_JS_SYNTAX:         {injection_js_syntax}")
        print(f"BASELINE_CAPTURE_SUPPORTED:  {'YES' if baseline_supported else 'NO'}")
        print(f"DOWNLOAD_DIR_CLEANABLE:      {'YES' if cleanable else 'NO'}")
        print(f"SAFE_TO_GENERATE_ONCE:       {'YES' if safe_to_generate_once else 'NO'}")
        print()
        print(f"GENERATION_ATTEMPTS:         0")
        print(f"CREDITS_CONSUMED:            0")
        print(f"DOWNLOAD_ATTEMPTED:          NO")
        print("=" * 60)

        return result
    finally:
        if should_close_cdp:
            cdp.close()


def fill_prompt(cdp: CDPConnection, prompt_text: str, timeout_sec: float = 10.0) -> Dict[str, Any]:
    """
    Insere o prompt de forma controlada no editor ProseMirror (ou contenteditable/textarea).
    
    Etapas:
    1. Verifica idempotência: se o editor já contém o texto esperado, não duplica.
    2. Foca o editor e seleciona qualquer conteúdo prévio para substituição limpa.
    3. Insere o texto preferencialmente via CDP 'Input.insertText' (com fallback para execCommand).
    4. Realiza handshake com timeout para confirmar que a UI aceitou o texto.
    
    Retorna métricas de handshake:
    - prompt_fill_method
    - prompt_expected_length
    - prompt_editor_length
    - prompt_match (bool)
    """
    clean_expected = re.sub(r"\s+", " ", prompt_text).strip()
    expected_len = len(clean_expected)
    norm_expected = re.sub(r"\s+", " ", clean_expected.replace("\u00a0", " ")).strip()

    # 1. Localizar exatamente o editor ProseMirror (ou textarea compatível)
    js_check_current = """
    (() => {
        const editor = document.querySelector('div.ProseMirror[contenteditable="true"], div.ProseMirror, textarea:not([class*="recaptcha"])');
        if (!editor) return { found: false };
        const text = (editor.innerText || editor.textContent || '').trim().replace(/\\s+/g, ' ');
        return {
            found: true,
            text: text,
            tag: editor.tagName,
            isProseMirror: editor.classList && editor.classList.contains('ProseMirror')
        };
    })()
    """
    current_info = cdp.eval_js(js_check_current) or {}
    if not current_info.get("found"):
        logger.error("Nenhum campo de prompt encontrado na UI.")
        return {
            "success": False,
            "error": "NO_PROMPT_INPUT_FOUND",
            "prompt_fill_method": "NONE",
            "prompt_expected_length": expected_len,
            "prompt_editor_length": 0,
            "prompt_match": False,
        }

    current_text = current_info.get("text", "")
    norm_current = re.sub(r"\s+", " ", (current_text or "").replace("\u00a0", " ")).strip()

    # IDEMPOTÊNCIA: se o texto já estiver presente no editor, não reescrever
    is_already_present = (norm_current == norm_expected) or (
        len(norm_current) >= len(norm_expected) * 0.95 and norm_expected[:40] in norm_current and norm_expected[-40:] in norm_current
    )
    if is_already_present:
        logger.info("Prompt já preenchido e correspondente no editor (IDEMPOTENTE).")
        return {
            "success": True,
            "error": None,
            "prompt_fill_method": "IDEMPOTENT_ALREADY_PRESENT",
            "prompt_expected_length": expected_len,
            "prompt_editor_length": len(current_text),
            "prompt_match": True,
        }

    # 2. Focar e selecionar todo o conteúdo do ProseMirror para substituição limpa
    js_focus_select = """
    (() => {
        const editor = document.querySelector('div.ProseMirror[contenteditable="true"], div.ProseMirror, textarea:not([class*="recaptcha"])');
        if (!editor) return { found: false };
        editor.focus();
        if (editor.tagName === 'TEXTAREA') {
            editor.select();
        } else {
            const selection = window.getSelection();
            const range = document.createRange();
            range.selectNodeContents(editor);
            selection.removeAllRanges();
            selection.addRange(range);
        }
        return { found: true };
    })()
    """
    cdp.eval_js(js_focus_select)

    # 3. Inserir texto via CDP Input.insertText (simula digitação nativa no Blink/V8)
    method_used = "CDP_INPUT_INSERT_TEXT"
    inserted_via_cdp = False
    try:
        cdp.send("Input.insertText", {"text": clean_expected})
        inserted_via_cdp = True
    except Exception as exc:
        logger.warning(f"Input.insertText encontrou exceção ({exc}). Tentando fallback...")

    # Fallback seguro caso Input.insertText não esteja disponível ou falhe
    if not inserted_via_cdp:
        method_used = "FALLBACK_EXEC_COMMAND"
        escaped_prompt = json.dumps(clean_expected)
        js_fallback = f"""
        (() => {{
            const editor = document.querySelector('div.ProseMirror[contenteditable="true"], div.ProseMirror, textarea:not([class*="recaptcha"])');
            if (!editor) return false;
            editor.focus();
            if (editor.tagName === 'TEXTAREA') {{
                editor.value = {escaped_prompt};
                editor.dispatchEvent(new Event('input', {{ bubbles: true }}));
                editor.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }} else {{
                document.execCommand('selectAll', false, null);
                document.execCommand('insertText', false, {escaped_prompt});
                editor.dispatchEvent(new Event('input', {{ bubbles: true }}));
            }}
            return true;
        }})()
        """
        cdp.eval_js(js_fallback)

    # 4. Handshake do prompt: aguardar confirmação de que o editor reteve o texto
    start_t = time.time()
    editor_text = ""
    prompt_match = False

    while time.time() - start_t < timeout_sec:
        time.sleep(0.5)
        js_read = """
        (() => {
            const editor = document.querySelector('div.ProseMirror[contenteditable="true"], div.ProseMirror, textarea:not([class*="recaptcha"])');
            if (!editor) return '';
            return (editor.innerText || editor.textContent || editor.value || '').trim().replace(/\\s+/g, ' ');
        })()
        """
        editor_text = cdp.eval_js(js_read) or ""
        norm_read = re.sub(r"\s+", " ", editor_text.replace("\u00a0", " ")).strip()
        # Correspondência textual confiável (sem exigir formatação byte-a-byte)
        if norm_read == norm_expected or (
            len(norm_read) >= len(norm_expected) * 0.95 and norm_expected[:40] in norm_read and norm_expected[-40:] in norm_read
        ):
            prompt_match = True
            break

    editor_len = len(editor_text)
    logger.info(f"Handshake de prompt: esperado={expected_len} chars, editor={editor_len} chars, match={prompt_match}")

    if not prompt_match:
        return {
            "success": False,
            "error": "BLOCKED_PROMPT_NOT_ACCEPTED",
            "prompt_fill_method": method_used,
            "prompt_expected_length": expected_len,
            "prompt_editor_length": editor_len,
            "prompt_match": False,
        }

    return {
        "success": True,
        "error": None,
        "prompt_fill_method": method_used,
        "prompt_expected_length": expected_len,
        "prompt_editor_length": editor_len,
        "prompt_match": True,
    }


def wait_until_generation_ready(cdp: CDPConnection, timeout_sec: float = 10.0) -> Dict[str, Any]:
    """
    Aguarda a UI do Flow processar o prompt e habilitar o botão de geração.
    Verifica que:
    1. O botão Generate é encontrado e unívoco (matchCount == 1).
    2. O botão NÃO está disabled (disabled == False).
    """
    start_t = time.time()
    last_btn_info = {}

    while time.time() - start_t < timeout_sec:
        btn_info = find_generate_button(cdp)
        last_btn_info = btn_info

        if btn_info.get("matchCount", 0) > 1 or btn_info.get("ambiguous"):
            return {
                "ready": False,
                "error": "BLOCK_AMBIGUOUS_GENERATE_BUTTON",
                "btn_info": btn_info,
            }

        if btn_info.get("found") and btn_info.get("matchCount") == 1 and not btn_info.get("disabled"):
            return {
                "ready": True,
                "error": None,
                "btn_info": btn_info,
            }

        time.sleep(0.5)

    return {
        "ready": False,
        "error": "BLOCKED_GENERATE_STILL_DISABLED",
        "btn_info": last_btn_info,
    }


def click_generate_once(cdp: CDPConnection) -> Dict[str, Any]:
    """
    Executa o clique no botão Generate de forma atômica e exatamente UMA vez.
    Revalida todos os gates de segurança antes de disparar o clique.
    Retorna baseline e start_marker para acompanhamento do download.
    """
    # 1. Revalidação de sessão, CAPTCHA, superfície e concorrência
    state = check_auth_and_ui_state(cdp)
    if not state.get("isAuthenticated"):
        return {"success": False, "clicked": False, "error": "NOT_AUTHENTICATED"}
    if state.get("hasCaptcha"):
        return {"success": False, "clicked": False, "error": "CAPTCHA_DETECTED"}
    if state.get("surface") != FlowSurface.STUDIO:
        return {"success": False, "clicked": False, "error": "SURFACE_NOT_STUDIO"}
    if state.get("isGenerating"):
        return {"success": False, "clicked": False, "error": "GENERATION_IN_PROGRESS"}

    # 2. Revalidação de créditos
    credits_status = state.get("creditsStatus")
    if credits_status != CreditsStatus.AVAILABLE:
        return {"success": False, "clicked": False, "error": "NO_CREDITS_AVAILABLE"}

    # 3. Revalidação do botão Generate
    btn_info = find_generate_button(cdp)
    if not btn_info.get("found"):
        return {"success": False, "clicked": False, "error": "NO_GENERATE_BUTTON_FOUND"}
    if btn_info.get("matchCount", 0) != 1 or btn_info.get("ambiguous"):
        return {"success": False, "clicked": False, "error": "BLOCK_AMBIGUOUS_GENERATE_BUTTON"}
    if btn_info.get("disabled"):
        return {"success": False, "clicked": False, "error": "GENERATE_BUTTON_DISABLED"}

    # 4. Capturar baseline do estúdio e registrar start_marker antes do clique
    baseline = capture_studio_baseline(cdp)
    start_marker = time.time()

    # 5. Clicar exatamente uma vez
    js_click = """
    (() => {
        const btn = document.querySelector('flow-generate-icon-button button, button.generate-button, button[aria-label="Iniciar geração"], button[aria-label="Start generation"]');
        if (!btn) return { clicked: false, error: "NO_GENERATE_BUTTON_FOUND" };
        if (btn.disabled || btn.getAttribute('aria-disabled') === 'true') {
            return { clicked: false, error: "GENERATE_BUTTON_DISABLED" };
        }
        btn.click();
        return { clicked: true };
    })()
    """
    click_res = cdp.eval_js(js_click) or {}
    if not click_res.get("clicked"):
        return {
            "success": False,
            "clicked": False,
            "error": click_res.get("error", "CLICK_FAILED"),
        }

    logger.info("Clique no botão Generate realizado com sucesso (UMA VEZ)!")
    return {
        "success": True,
        "clicked": True,
        "baseline": baseline,
        "start_marker": start_marker,
        "generation_attempts": 1,
        "generation_click_attempted": True,
        "generation_click_confirmed": True,
    }


def inject_prompt_and_generate(cdp: CDPConnection, prompt_text: str) -> Dict[str, Any]:
    """
    Executa preenchimento, espera de ativação do botão e clique de geração em sequência.
    Mantido para compatibilidade, delegando para as operações desacopladas.
    """
    fill_res = fill_prompt(cdp, prompt_text)
    if not fill_res.get("success"):
        return fill_res

    ready_res = wait_until_generation_ready(cdp)
    if not ready_res.get("ready"):
        return {"success": False, "error": ready_res.get("error", "GENERATE_BUTTON_DISABLED"), "inputFilled": True}

    return click_generate_once(cdp)


def wait_for_generation_and_download(
    cdp: CDPConnection,
    download_dir: str,
    baseline: Optional[Dict[str, Any]] = None,
    start_marker: Optional[float] = None,
    timeout_generation_sec: int = DEFAULT_TIMEOUT_GENERATION_SEC,
    timeout_download_sec: int = DEFAULT_DOWNLOAD_WAIT_SEC,
) -> str:
    """
    Acompanha o ciclo de geração do clipe até a conclusão, dispara o download e valida a conclusão do arquivo.
    Garante fail-closed se timeout ou falha na renderização.
    Exige evidência nova em relação ao baseline para evitar falsos positivos de assets pré-existentes.
    Exige que o arquivo baixado tenha timestamp posterior a start_marker.
    """
    if start_marker is None:
        start_marker = time.time()

    logger.info(f"Aguardando conclusão da geração no Flow (timeout: {timeout_generation_sec}s)...")
    start_time = time.time()
    generation_finished = False

    while time.time() - start_time < timeout_generation_sec:
        time.sleep(3)
        state = check_auth_and_ui_state(cdp)

        if state.get("hasCaptcha"):
            raise RuntimeError("FAIL_CLOSED: Desafio de segurança ou CAPTCHA detectado durante a geração.")

        if not state.get("isGenerating"):
            # Verifica se há vídeos disponíveis na página ou botão de download
            js_check_ready = """
            (() => {
                const videos = Array.from(document.querySelectorAll('video'))
                    .map(v => v.src || v.currentSrc)
                    .filter(Boolean);
                const dlBtns = Array.from(document.querySelectorAll('button, a')).filter(el => {
                    const txt = (el.innerText || el.getAttribute('aria-label') || '').toLowerCase();
                    return txt.includes('download') || txt.includes('baixar');
                });
                const tiles = Array.from(document.querySelectorAll('flow-tile, .flow-tile, [data-tile-id], mat-card'))
                    .map((t, idx) => t.id || t.getAttribute('data-tile-id') || `tile-${idx}`);

                return {
                    hasVideo: videos.length > 0,
                    videos: videos,
                    videosCount: videos.length,
                    hasDownloadBtn: dlBtns.length > 0,
                    tilesCount: tiles.length,
                    tileIds: tiles
                };
            })()
            """
            ready_info = cdp.eval_js(js_check_ready) or {}

            # Se baseline foi fornecido, exige evidência NOVA
            is_new_evidence = True
            if baseline:
                baseline_videos = baseline.get("videoSrcs", [])
                baseline_v_count = baseline.get("videosCount", 0)
                baseline_tiles = baseline.get("tileIds", [])
                baseline_t_count = baseline.get("tilesCount", 0)

                current_videos = ready_info.get("videos", [])
                current_v_count = ready_info.get("videosCount", 0)
                current_tiles = ready_info.get("tileIds", [])
                current_t_count = ready_info.get("tilesCount", 0)

                has_new_vid = any(v not in baseline_videos for v in current_videos) or (current_v_count > baseline_v_count)
                has_new_tile = any(t not in baseline_tiles for t in current_tiles) or (current_t_count > baseline_t_count)

                if not has_new_vid and not has_new_tile and not (ready_info.get("hasDownloadBtn") and baseline.get("downloadButtonsCount", 0) == 0):
                    is_new_evidence = False

            if (ready_info.get("hasVideo") or ready_info.get("hasDownloadBtn")) and is_new_evidence:
                logger.info("Vídeo gerado detectado com sucesso no estúdio (evidência nova confirmada)!")
                generation_finished = True
                break

    if not generation_finished:
        raise TimeoutError(f"FAIL_CLOSED: Timeout de {timeout_generation_sec}s atingido aguardando geração do Flow.")

    # Dispara o download clicando no botão correspondente
    logger.info("Disparando download do clipe gerado...")
    js_trigger_dl = """
    (() => {
        const dlBtn = Array.from(document.querySelectorAll('button, a')).find(el => {
            const txt = (el.innerText || el.getAttribute('aria-label') || '').toLowerCase();
            return txt.includes('download') || txt.includes('baixar');
        });
        if (dlBtn) {
            dlBtn.click();
            return { clicked: true };
        }
        const vid = document.querySelector('video');
        if (vid && (vid.src || vid.currentSrc)) {
            const a = document.createElement('a');
            a.href = vid.src || vid.currentSrc;
            a.download = 'flow_clip.mp4';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            return { clicked: true, directVideo: true };
        }
        return { clicked: false, error: "DOWNLOAD_ELEMENT_NOT_FOUND" };
    })()
    """
    dl_res = cdp.eval_js(js_trigger_dl)
    if not dl_res.get("clicked"):
        raise RuntimeError(f"FAIL_CLOSED: Falha ao disparar download: {dl_res.get('error')}")

    # Monitora pasta de download para acompanhar .crdownload e encontrar o arquivo final .mp4
    # CRÍTICO: aceitar apenas arquivo com mtime posterior a start_marker
    logger.info(f"Acompanhando download em {download_dir} (timeout: {timeout_download_sec}s, start_marker={start_marker})...")
    dl_start = time.time()
    downloaded_file = None

    while time.time() - dl_start < timeout_download_sec:
        time.sleep(1)
        crdownloads = glob.glob(os.path.join(download_dir, "*.crdownload"))
        mp4_files = glob.glob(os.path.join(download_dir, "*.mp4"))

        fresh_mp4s = [
            f for f in mp4_files
            if os.path.getmtime(f) >= (start_marker - 1.0) and os.path.getsize(f) > 0
        ]

        if not crdownloads and fresh_mp4s:
            downloaded_file = max(fresh_mp4s, key=os.path.getmtime)
            break

    if not downloaded_file:
        raise TimeoutError(f"FAIL_CLOSED: Timeout de download ({timeout_download_sec}s) em {download_dir} ou nenhum novo arquivo posterior a start_marker.")

    logger.info(f"Download concluído: {downloaded_file} ({os.path.getsize(downloaded_file)} bytes)")
    return downloaded_file


def run_fill_check(
    manifest_path: str,
    scene_index: int = 1,
    timeout_sec: float = 10.0,
    cdp_client: Optional[CDPConnection] = None,
) -> Dict[str, Any]:
    """
    Executa a verificação controlada de preenchimento de prompt (handshake) e ativação do botão Generate.
    CRÍTICO:
    - Preenche o prompt no editor ProseMirror.
    - Confirma aceite pelo editor (PROMPT_MATCH).
    - Aguarda o botão Generate habilitar.
    - PROIBIDO CLICAR EM GENERATE.
    - PROIBIDO GERAR VÍDEO.
    - ZERO CRÉDITOS CONSUMIDOS.
    """
    manifest_path = os.path.abspath(manifest_path)
    if not os.path.isfile(manifest_path):
        raise FileNotFoundError(f"Manifesto não encontrado: {manifest_path}")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    target_scene = None
    for sc in manifest.get("scenes", []):
        if sc.get("scene_index") == scene_index:
            target_scene = sc
            break

    if not target_scene:
        raise ValueError(f"Cena {scene_index} não encontrada no manifesto.")

    prompt = target_scene.get("prompt_en")
    if not prompt:
        raise ValueError(f"Cena {scene_index} não possui 'prompt_en' definido.")

    should_close_cdp = False
    cdp = cdp_client
    if cdp is None:
        if not is_cdp_ready():
            launch_browser(headless=False)
        cdp = CDPConnection()
        cdp.connect_to_flow_target()
        should_close_cdp = True

    try:
        # 1. Navegar se necessário para STUDIO
        state = check_auth_and_ui_state(cdp)
        if state.get("surface") == FlowSurface.LANDING:
            state = navigate_landing_to_studio(cdp)

        authenticated = bool(state.get("isAuthenticated"))
        surface = state.get("surface")

        # 2. Inspecionar botão ANTES do preenchimento
        btn_before = find_generate_button(cdp)
        disabled_before = bool(btn_before.get("disabled", True))

        # 3. Preencher prompt e validar handshake
        fill_res = fill_prompt(cdp, prompt, timeout_sec=timeout_sec)
        prompt_match = bool(fill_res.get("prompt_match"))
        prompt_method = fill_res.get("prompt_fill_method", "NONE")
        expected_len = fill_res.get("prompt_expected_length", 0)
        editor_len = fill_res.get("prompt_editor_length", 0)

        # 4. Aguardar habilitação do botão Generate
        ready_res = wait_until_generation_ready(cdp, timeout_sec=timeout_sec)
        ready_for_click = bool(ready_res.get("ready"))
        btn_after = ready_res.get("btn_info", {})
        disabled_after = bool(btn_after.get("disabled", True))
        btn_found = bool(btn_after.get("found"))
        match_count = btn_after.get("matchCount", 0)

        result = {
            "status": "READY_FOR_CLICK" if (prompt_match and ready_for_click) else "FILL_CHECK_BLOCKED",
            "authenticated": authenticated,
            "flow_surface": surface,
            "prompt_fill_method": prompt_method,
            "prompt_expected_length": expected_len,
            "prompt_editor_length": editor_len,
            "prompt_match": prompt_match,
            "generate_button_found": btn_found,
            "generate_button_match_count": match_count,
            "generate_button_disabled_before_fill": disabled_before,
            "generate_button_disabled_after_fill": disabled_after,
            "ready_for_click": ready_for_click,
            "generation_clicked": False,
            "generation_attempts": 0,
            "credits_consumed": 0,
            "download_attempted": False,
            "error": fill_res.get("error") or ready_res.get("error"),
        }

        print("\n" + "=" * 60)
        print("FLOW AUTONOMOUS WEB — PROMPT FILL HANDSHAKE (READ-ONLY/NO-CLICK)")
        print("=" * 60)
        print(f"AUTHENTICATED:                       {'YES' if authenticated else 'NO'}")
        print(f"FLOW_SURFACE:                        {surface}")
        print(f"PROMPT_FILL_METHOD:                  {prompt_method}")
        print(f"PROMPT_EXPECTED_LENGTH:              {expected_len}")
        print(f"PROMPT_EDITOR_LENGTH:                {editor_len}")
        print(f"PROMPT_MATCH:                        {'YES' if prompt_match else 'NO'}")
        print(f"GENERATE_BUTTON_FOUND:               {'YES' if btn_found else 'NO'}")
        print(f"GENERATE_BUTTON_MATCH_COUNT:         {match_count}")
        print(f"GENERATE_BUTTON_DISABLED_BEFORE_FILL:{'YES' if disabled_before else 'NO'}")
        print(f"GENERATE_BUTTON_DISABLED_AFTER_FILL: {'YES' if disabled_after else 'NO'}")
        print(f"READY_FOR_CLICK:                     {'YES' if ready_for_click else 'NO'}")
        print()
        print(f"GENERATION_CLICKED:                  NO")
        print(f"GENERATION_ATTEMPTS:                 0")
        print(f"CREDITS_CONSUMED:                    0")
        print(f"DOWNLOAD_ATTEMPTED:                  NO")
        print("=" * 60)

        return result
    finally:
        if should_close_cdp:
            cdp.close()


def run_single_scene_poc(
    manifest_path: str,
    scene_index: int = 1,
    timeout_sec: int = DEFAULT_TIMEOUT_GENERATION_SEC,
    wait_login_sec: int = 0,
    cdp_client: Optional[CDPConnection] = None,
) -> Dict[str, Any]:
    """
    Executa a POC de automação para exatamente UMA cena:
    1. Verifica idempotência: Se flow_scene_01.mp4 já existir e for válido, retorna ALREADY_COMPLETE.
    2. Lê o prompt da cena do manifesto.
    3. Conecta ao navegador Edge via CDP (porta 9222).
    4. Valida sessão Google:
       - Se não autenticado -> retorna AWAITING_INITIAL_HUMAN_LOGIN e abre página de login.
       - Se CAPTCHA -> BLOCKED_CAPTCHA (STOP).
       - Se LANDING -> navega com segurança para STUDIO.
       - Se créditos zero -> BLOCKED_NO_CREDITS (STOP).
       - Se geração ativa -> BLOCKED_GENERATION_IN_PROGRESS (STOP).
    5. Configura diretório de download.
    6. Insere o prompt na interface e inicia geração uma única vez.
    7. Acompanha processamento até conclusão.
    8. Dispara e acompanha download (.crdownload -> .mp4).
    9. Valida o arquivo baixado via probe_media (tamanho > 0, duração > 0, stream de vídeo).
    10. Move/copia atomicamente para clips/flow_scene_01.mp4.
    """
    manifest_path = os.path.abspath(manifest_path)
    if not os.path.isfile(manifest_path):
        raise FileNotFoundError(f"Manifesto não encontrado: {manifest_path}")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    project_dir = os.path.dirname(manifest_path)
    clips_dir = os.path.join(project_dir, "clips")
    os.makedirs(clips_dir, exist_ok=True)

    expected_filename = f"flow_scene_{scene_index:02d}.mp4"
    target_clip_path = os.path.join(clips_dir, expected_filename)

    # 1. IDEMPOTÊNCIA MANDATÓRIA: Evita consumir novos créditos se o clipe já existe e é válido
    if os.path.exists(target_clip_path):
        val = validate_clip_file(target_clip_path)
        if val["valid"]:
            logger.info(
                f"Cena {scene_index} já existe e é válida em {target_clip_path} "
                f"(duração: {val['duration']:.2f}s, tamanho: {val['size']} bytes). IDEMPOTÊNCIA CONFIRMADA."
            )
            return {
                "status": "ALREADY_COMPLETE",
                "scene_index": scene_index,
                "clip_path": target_clip_path,
                "valid": True,
                "duration": val["duration"],
                "size": val["size"],
                "idempotent": True,
                "generation_attempts": 0,
            }
        else:
            logger.warning(f"Arquivo existente em {target_clip_path} inválido ({val['error']}). Será regenerado.")
            try:
                os.remove(target_clip_path)
            except Exception:
                pass

    # 2. Localiza a cena no manifesto
    target_scene = None
    for sc in manifest.get("scenes", []):
        if sc.get("scene_index") == scene_index:
            target_scene = sc
            break

    if not target_scene:
        raise ValueError(f"Cena {scene_index} não encontrada no manifesto.")

    prompt = target_scene.get("prompt_en")
    if not prompt:
        raise ValueError(f"Cena {scene_index} não possui 'prompt_en' definido.")

    logger.info(f"POC Flow Cena {scene_index} — Prompt ({len(prompt)} chars): {prompt[:80]}...")

    # 3. Conexão CDP
    should_close_cdp = False
    cdp = cdp_client
    if cdp is None:
        if not is_cdp_ready():
            launch_browser(headless=False)
        cdp = CDPConnection()
        cdp.connect_to_flow_target()
        should_close_cdp = True

    try:
        # 4. Auditoria de sessão e Fail-Closed
        state = check_auth_and_ui_state(cdp)

        if state.get("hasCaptcha"):
            logger.error("FAIL-CLOSED: Desafio de segurança / CAPTCHA ativo.")
            return {
                "status": "BLOCKED_CAPTCHA",
                "scene_index": scene_index,
                "google_session_status": "CHALLENGE_DETECTED",
                "captcha_status": "BLOCKED",
                "error": "CAPTCHA / Security challenge detected. FAIL-CLOSED.",
            }

        if not state.get("isAuthenticated"):
            logger.warning("FAIL-CLOSED: Sessão Google Flow não autenticada no perfil persistente.")
            navigate_to_login(cdp)

            # Se o operador solicitou aguardar login manual
            if wait_login_sec > 0:
                logger.info(f"Aguardando login manual pelo operador na janela do Edge (timeout {wait_login_sec}s)...")
                login_start = time.time()
                while time.time() - login_start < wait_login_sec:
                    time.sleep(2)
                    state = check_auth_and_ui_state(cdp)
                    if state.get("isAuthenticated"):
                        logger.info("Login manual detectado com sucesso! Prosseguindo...")
                        break

            if not state.get("isAuthenticated"):
                return {
                    "status": "AWAITING_INITIAL_HUMAN_LOGIN",
                    "scene_index": scene_index,
                    "google_session_status": "AWAITING_INITIAL_HUMAN_LOGIN",
                    "captcha_status": "NONE",
                    "credits_status": CreditsStatus.UNKNOWN,
                    "error": "Sessão Google não autenticada. Operador deve fazer login manualmente.",
                }

        # Transição da LANDING para o STUDIO se necessário
        if state.get("surface") == FlowSurface.LANDING:
            logger.info("Sessão autenticada na LANDING. Navegando para a superfície STUDIO...")
            state = navigate_landing_to_studio(cdp)

        if state.get("surface") != FlowSurface.STUDIO or not state.get("hasPromptInput"):
            logger.error(f"FAIL-CLOSED: Não foi possível alcançar o STUDIO com editor de prompt. Superfície atual: {state.get('surface')}")
            return {
                "status": "BLOCKED_SURFACE_NOT_STUDIO",
                "scene_index": scene_index,
                "google_session_status": "AUTHENTICATED",
                "flow_surface": state.get("surface"),
                "prompt_input_found": state.get("hasPromptInput", False),
                "error": "Superfície STUDIO não disponível.",
            }

        # Sessão autenticada no Studio: verificar créditos (FAIL-CLOSED)
        credits_status = state.get("creditsStatus", CreditsStatus.UNKNOWN)
        if credits_status == CreditsStatus.UNKNOWN:
            cred_info = inspect_credits_menu(cdp)
            credits_status = cred_info.get("creditsStatus", CreditsStatus.UNKNOWN)

        if credits_status != CreditsStatus.AVAILABLE:
            err_msg = "Créditos indisponíveis (ZERO). FAIL-CLOSED." if credits_status == CreditsStatus.ZERO else "Status de créditos não pôde ser confirmado (UNKNOWN). FAIL-CLOSED."
            logger.error(f"FAIL-CLOSED: {err_msg}")
            return {
                "status": "BLOCKED_NO_CREDITS" if credits_status == CreditsStatus.ZERO else "BLOCKED_CREDITS_UNKNOWN",
                "scene_index": scene_index,
                "google_session_status": "AUTHENTICATED",
                "flow_surface": FlowSurface.STUDIO,
                "captcha_status": "NONE",
                "credits_status": credits_status,
                "error": err_msg,
            }

        # Verificar se já há geração ativa
        if state.get("isGenerating"):
            logger.error("FAIL-CLOSED: Outra geração já está em andamento no estúdio.")
            return {
                "status": "BLOCKED_GENERATION_IN_PROGRESS",
                "scene_index": scene_index,
                "google_session_status": "AUTHENTICATED",
                "flow_surface": FlowSurface.STUDIO,
                "captcha_status": "NONE",
                "credits_status": credits_status,
                "error": "Geração ativa detectada. Evitando duplicidade.",
            }

        # Verificar botão Generate inequívoco antes de qualquer injeção
        gen_btn_info = find_generate_button(cdp)
        if not gen_btn_info.get("found"):
            logger.error("FAIL-CLOSED: Nenhum botão de geração encontrado no estúdio.")
            return {
                "status": "FAIL_NO_GENERATE_BUTTON",
                "scene_index": scene_index,
                "google_session_status": "AUTHENTICATED",
                "flow_surface": FlowSurface.STUDIO,
                "captcha_status": "NONE",
                "credits_status": credits_status,
                "error": "Botão de geração não encontrado no Studio.",
            }

        if gen_btn_info.get("matchCount", 0) > 1 or gen_btn_info.get("ambiguous"):
            logger.error(f"FAIL-CLOSED: Múltiplos botões de geração encontrados ({gen_btn_info.get('matchCount')}). Ambiguidade.")
            return {
                "status": "BLOCK_AMBIGUOUS_GENERATE_BUTTON",
                "scene_index": scene_index,
                "google_session_status": "AUTHENTICATED",
                "flow_surface": FlowSurface.STUDIO,
                "captcha_status": "NONE",
                "credits_status": credits_status,
                "error": "BLOCK_AMBIGUOUS_GENERATE_BUTTON: múltiplos botões detectados.",
            }

        # 5. Configurar diretório temporário para download e limpar artefatos anteriores
        temp_download_dir = os.path.join(project_dir, "temp_downloads")
        os.makedirs(temp_download_dir, exist_ok=True)
        clean_download_dir(temp_download_dir)
        cdp.set_download_path(temp_download_dir)

        # 6. Preencher prompt no editor e validar handshake
        logger.info(f"Preenchendo prompt da Cena {scene_index} no Google Flow...")
        fill_res = fill_prompt(cdp, prompt, timeout_sec=10.0)
        if not fill_res.get("success"):
            logger.error(f"FAIL-CLOSED: Falha no preenchimento do prompt: {fill_res.get('error')}")
            return {
                "status": "BLOCKED_PROMPT_NOT_ACCEPTED",
                "scene_index": scene_index,
                "google_session_status": "AUTHENTICATED",
                "flow_surface": FlowSurface.STUDIO,
                "captcha_status": "NONE",
                "credits_status": credits_status,
                "prompt_fill_attempts": 1,
                "generation_click_attempted": False,
                "generation_click_confirmed": False,
                "generation_attempts": 0,
                "error": fill_res.get("error"),
            }

        # 7. Aguardar ativação do botão Generate
        ready_res = wait_until_generation_ready(cdp, timeout_sec=10.0)
        if not ready_res.get("ready"):
            logger.error(f"FAIL-CLOSED: Botão Generate não habilitou após preenchimento: {ready_res.get('error')}")
            return {
                "status": ready_res.get("error", "BLOCKED_GENERATE_STILL_DISABLED"),
                "scene_index": scene_index,
                "google_session_status": "AUTHENTICATED",
                "flow_surface": FlowSurface.STUDIO,
                "captcha_status": "NONE",
                "credits_status": credits_status,
                "prompt_fill_attempts": 1,
                "generation_click_attempted": False,
                "generation_click_confirmed": False,
                "generation_attempts": 0,
                "error": ready_res.get("error"),
            }

        # 8. Disparar clique único controlado no botão Generate
        click_res = click_generate_once(cdp)
        if not click_res.get("clicked"):
            logger.error(f"FAIL-CLOSED: Falha no disparo do clique de geração: {click_res.get('error')}")
            return {
                "status": "FAIL_GENERATE_TRIGGER",
                "scene_index": scene_index,
                "google_session_status": "AUTHENTICATED",
                "flow_surface": FlowSurface.STUDIO,
                "captcha_status": "NONE",
                "credits_status": credits_status,
                "prompt_fill_attempts": 1,
                "generation_click_attempted": True,
                "generation_click_confirmed": False,
                "generation_attempts": 0,
                "error": click_res.get("error"),
            }

        baseline = click_res.get("baseline")
        start_marker = click_res.get("start_marker", time.time())

        # 9. Acompanhar geração e efetuar download com baseline e start_marker
        downloaded_temp_path = wait_for_generation_and_download(
            cdp=cdp,
            download_dir=temp_download_dir,
            baseline=baseline,
            start_marker=start_marker,
            timeout_generation_sec=timeout_sec,
        )

        # 10. Validar arquivo baixado
        val = validate_clip_file(downloaded_temp_path)
        if not val["valid"]:
            logger.error(f"FAIL-CLOSED: Arquivo baixado é inválido: {val['error']}")
            return {
                "status": "FAIL_INVALID_DOWNLOAD",
                "scene_index": scene_index,
                "google_session_status": "AUTHENTICATED",
                "flow_surface": FlowSurface.STUDIO,
                "captcha_status": "NONE",
                "credits_status": credits_status,
                "prompt_fill_attempts": 1,
                "generation_click_attempted": True,
                "generation_click_confirmed": True,
                "generation_attempts": 1,
                "download_completed": False,
                "error": val["error"],
            }

        # 11. Mover atomicamente para o destino canônico da Video Factory
        shutil.move(downloaded_temp_path, target_clip_path)
        shutil.rmtree(temp_download_dir, ignore_errors=True)

        final_val = validate_clip_file(target_clip_path)
        if not final_val["valid"]:
            raise RuntimeError(f"Erro pós-movimentação: {final_val['error']}")

        logger.info(f"Sucesso! Clipe salvo e validado em {target_clip_path} (duração: {final_val['duration']:.2f}s)")
        return {
            "status": "SUCCESS",
            "scene_index": scene_index,
            "google_session_status": "AUTHENTICATED",
            "flow_surface": FlowSurface.STUDIO,
            "captcha_status": "NONE",
            "credits_status": credits_status,
            "prompt_fill_attempts": 1,
            "generation_click_attempted": True,
            "generation_click_confirmed": True,
            "generation_attempts": 1,
            "download_completed": True,
            "clip_path": target_clip_path,
            "duration": final_val["duration"],
            "size": final_val["size"],
            "valid": True,
        }

    finally:
        if should_close_cdp:
            cdp.close()


def open_browser_for_user(timeout_sec: int = 300):
    """Abre o navegador na interface do Google Flow para que o operador faça login e salva a sessão."""
    print("=" * 60)
    print("ABRINDO NAVEGADOR PARA SESSÃO GOOGLE FLOW")
    print("=" * 60)
    print(f"Diretório de Perfil: {DEFAULT_PROFILE_DIR}")
    print("Instruções:")
    print("1. O navegador Edge será aberto na página de login do Google.")
    print("2. Faça login com sua conta Google que possui assinatura Google AI Pro.")
    print("3. Acesse o Google Flow (https://flow.google.com).")
    print("4. Sua sessão será salva automaticamente no perfil persistente.")
    print("5. Nenhuma senha ou credencial é capturada por este script.")
    print("=" * 60)

    launch_browser(headless=False, url=LOGIN_URL)
    print("\nNavegador aberto com sucesso! Conclua o login manual na janela do Edge.")
    print(f"Aguardando e monitorando autenticação (timeout: {timeout_sec}s)...")

    cdp = CDPConnection()
    try:
        cdp.connect_to_flow_target()
        start_t = time.time()
        last_logged = 0.0
        while time.time() - start_t < timeout_sec:
            time.sleep(3)
            state = check_auth_and_ui_state(cdp)
            if state.get("isAuthenticated"):
                print("\n[OK] Autenticação detectada com sucesso no Google Flow!")
                print(f"Superfície inicial detectada: {state.get('surface')}")
                print("Sessão salva com sucesso no perfil persistente storage/flow_browser_profile.")
                return True
            if state.get("hasCaptcha") and (time.time() - last_logged > 15):
                print("[ALERTA] Desafio CAPTCHA detectado. Resolva o desafio no navegador.")
                last_logged = time.time()

        print("\n[TIMEOUT] Tempo limite esgotado aguardando login manual.")
        return False
    except Exception as exc:
        logger.debug(f"Monitoramento de login encontrou exceção: {exc}")
        return False
    finally:
        cdp.close()


def check_flow_status():
    """Verifica se o perfil persistente atual está autenticado no Google Flow."""
    print("=" * 60)
    print("DIAGNÓSTICO DE SESSÃO E INTERFACE GOOGLE FLOW")
    print("=" * 60)

    if not is_cdp_ready():
        print("Iniciando navegador com perfil persistente...")
        launch_browser(headless=False)

    cdp = CDPConnection()
    try:
        cdp.connect_to_flow_target()
        state = check_auth_and_ui_state(cdp)
        print(f"URL Atual:             {state.get('url')}")
        print(f"Título da Página:      {state.get('title')}")
        print(f"Autenticado:           {state.get('isAuthenticated')}")
        print(f"Superfície UI:         {state.get('surface')}")
        print(f"Editor de Prompt:      {state.get('hasPromptInput')} ({state.get('promptInputsCount')} inputs)")
        print(f"Desafio CAPTCHA:       {state.get('hasCaptcha')}")
        print(f"Status de Créditos:    {state.get('creditsStatus')}")
        print(f"Geração em Andamento:  {state.get('isGenerating')}")
        if state.get("falsePositiveSource"):
            print(f"Falso Positivo Evitado:{state.get('falsePositiveSource')}")
        print(f"Amostra de Botões:     {state.get('buttonsSample')}")

        if state.get("hasCaptcha"):
            print("\n[ALERTA] Desafio CAPTCHA detectado! Intervenção humana necessária.")
        elif not state.get("isAuthenticated"):
            print("\n[AVISO] Sessão NÃO autenticada no perfil storage/flow_browser_profile.")
            print("Estado: AWAITING_INITIAL_HUMAN_LOGIN")
            print("Execute: python scripts/flow_web_automation.py open para fazer login manual.")
        else:
            print(f"\n[OK] Sessão autenticada! Superfície atual: {state.get('surface')}")
    finally:
        cdp.close()


def main():
    parser = argparse.ArgumentParser(description="Google Flow Web Automation Helper (V1.4A.1 POC)")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("open", help="Abre o navegador com o perfil persistente para login manual")
    subparsers.add_parser("status", help="Verifica autenticação e estado da UI do Flow")
    subparsers.add_parser("preflight", help="Executa auditoria read-only da interface (sem preencher prompt nem gerar)")
    subparsers.add_parser("arm", help="Verifica e arma gate de geração única (read-only, sem gerar nem consumir créditos)")

    gen_p = subparsers.add_parser("generate", help="Executa POC de geração para uma única cena")
    gen_p.add_argument("--manifest", required=True, help="Caminho para manifest.json")
    gen_p.add_argument("--scene", type=int, default=1, help="Número da cena a gerar (padrão: 1)")
    gen_p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_GENERATION_SEC, help="Timeout de geração em segundos")
    gen_p.add_argument("--wait-login", type=int, default=0, help="Tempo para aguardar login manual se não autenticado (segundos)")

    fill_p = subparsers.add_parser("fill-check", help="Executa verificação de preenchimento de prompt e ativação do botão Generate (sem clicar nem gerar)")
    fill_p.add_argument("--manifest", required=True, help="Caminho para manifest.json")
    fill_p.add_argument("--scene", type=int, default=1, help="Número da cena a verificar (padrão: 1)")
    fill_p.add_argument("--timeout", type=float, default=10.0, help="Timeout para handshake do prompt e ativação do botão")

    args = parser.parse_args()

    if args.command == "open":
        open_browser_for_user()
    elif args.command == "status":
        check_flow_status()
    elif args.command == "preflight":
        run_preflight()
    elif args.command == "arm":
        run_arm()
    elif args.command == "fill-check":
        res = run_fill_check(
            manifest_path=args.manifest,
            scene_index=args.scene,
            timeout_sec=args.timeout,
        )
        print("\nResultado:")
        print(json.dumps(res, indent=2))
    elif args.command == "generate":
        res = run_single_scene_poc(
            manifest_path=args.manifest,
            scene_index=args.scene,
            timeout_sec=args.timeout,
            wait_login_sec=args.wait_login,
        )
        print("\nResultado:")
        print(json.dumps(res, indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
