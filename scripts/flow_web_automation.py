"""
scripts/flow_web_automation.py
==============================
Fase V1.4A — Automação Web Autônoma do Google Flow via Chromium DevTools Protocol (CDP).

Objetivo:
Automação pontual, resiliente e segura da interface web do Google Flow (flow.google.com)
utilizando créditos existentes da assinatura Google AI Pro sem custos de API por vídeo.

Princípios Mandatórios:
1. Sem Playwright/Selenium: Utiliza Chromium/Edge nativo do sistema via CDP com websocket-client==1.9.0.
2. Sessão Persistente: Perfil seguro isolado em storage/flow_browser_profile (ignorado no git).
3. Sem Secrets no Código: Senhas Google NUNCA são manipuladas, pedidas ou registradas pelo código.
4. Fail-Closed Obrigatório:
   - Login expirado / não autenticado -> AWAITING_INITIAL_HUMAN_LOGIN (STOP).
   - CAPTCHA / desafio Google -> BLOCKED_CAPTCHA (STOP).
   - Créditos zero ou indisponíveis -> BLOCKED_NO_CREDITS (STOP).
   - Geração já em andamento -> BLOCKED_GENERATION_IN_PROGRESS (STOP).
   - Timeout de geração / UI ambígua -> STOP / FAIL-CLOSED.
5. Idempotência Rigorosa: Se o clipe (flow_scene_01.mp4) já existir e for válido, NÃO gera novamente.
   Retorna ALREADY_COMPLETE sem consumir novos créditos.
6. Validação Completa de Download: O clipe final deve ser validado via probe_media / ffprobe
   (existência, extensão .mp4, tamanho > 0, duração > 0 e presença de stream de vídeo).
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
    """Inspeciona o estado da página para detectar autenticação, captcha, créditos e UI."""
    js_detect = """
    (() => {
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
            const txt = (el.innerText || el.getAttribute('aria-label') || '').toLowerCase().trim();
            return txt === 'fazer login' || txt === 'sign in' || txt === 'login' || txt.includes('fazer login');
        });

        // 3. Detecção de créditos ou assinatura
        const creditsMatch = bodyText.match(/(\\d+)\\s*(?:créditos|credits|AI credits)/i);
        const credits = creditsMatch ? parseInt(creditsMatch[1], 10) : null;
        const noCreditsDetected = bodyText.includes('0 créditos') ||
                                  bodyText.includes('0 credits') ||
                                  bodyText.includes('sem créditos') ||
                                  bodyText.includes('no credits left');

        // Se créditos forem explicitamente 0 ou acusarem esgotamento
        const creditsAvailable = noCreditsDetected ? false : (credits === 0 ? false : true);

        // 4. Detecção de geração em andamento
        const isGenerating = Array.from(document.querySelectorAll('*')).some(el => {
            const role = el.getAttribute('role') || '';
            const cls = (el.className || '').toString();
            const txt = (el.innerText || '').toLowerCase();
            return role === 'progressbar' ||
                   cls.includes('spinner') ||
                   cls.includes('progress') ||
                   txt.includes('gerando...') ||
                   txt.includes('generating...') ||
                   txt.includes('criando...') ||
                   txt.includes('creating...');
        });

        // 5. Detecção de campos de prompt e botões
        const inputs = Array.from(document.querySelectorAll('textarea, [contenteditable="true"], input[type="text"]')).map(el => {
            return {
                tag: el.tagName,
                placeholder: el.placeholder || '',
                aria: el.getAttribute('aria-label') || '',
                id: el.id || '',
                className: (el.className || '').toString()
            };
        });

        const buttons = Array.from(document.querySelectorAll('button')).map(b => (b.innerText || b.getAttribute('aria-label') || '').trim()).filter(Boolean);

        // Vídeos prontos na página
        const videoElements = Array.from(document.querySelectorAll('video')).map(v => ({
            src: v.src || '',
            currentSrc: v.currentSrc || ''
        }));

        const isAuthenticated = !isBlank && !isAccountsPage && !isLandingAbout && !hasLoginBtn && !hasCaptcha && (url.includes('flow.google') || url.includes('labs.google'));

        return {
            url,
            title,
            isBlank,
            hasCaptcha,
            isAccountsPage,
            isLandingAbout,
            hasLoginBtn,
            isAuthenticated,
            credits,
            creditsAvailable,
            isGenerating,
            inputCandidatesCount: inputs.length,
            buttonsSample: buttons.slice(0, 15),
            videoElementsCount: videoElements.length
        };
    })()
    """
    return cdp.eval_js(js_detect)


def navigate_to_login(cdp: CDPConnection):
    """Navega para a página de login do Google preservando o redirecionamento para o Flow."""
    logger.info(f"Navegando para o login Google: {LOGIN_URL}")
    cdp.send("Page.navigate", {"url": LOGIN_URL})


def inject_prompt_and_generate(cdp: CDPConnection, prompt_text: str) -> Dict[str, Any]:
    """
    Localiza o campo de prompt na UI do Flow, insere o prompt da cena e clica em Gerar.
    Fail-closed se nenhum input for encontrado ou botão indisponível.
    """
    js_inject = f"""
    (() => {{
        const prompt = {json.dumps(prompt_text)};
        // Localiza campo de prompt
        const input = document.querySelector('textarea, [contenteditable="true"], input[type="text"]');
        if (!input) {{
            return {{ success: false, error: "NO_PROMPT_INPUT_FOUND" }};
        }}

        // Foca e preenche
        input.focus();
        if (input.tagName === 'TEXTAREA' || input.tagName === 'INPUT') {{
            input.value = prompt;
            input.dispatchEvent(new Event('input', {{ bubbles: true }}));
            input.dispatchEvent(new Event('change', {{ bubbles: true }}));
        }} else {{
            input.innerText = prompt;
            input.dispatchEvent(new Event('input', {{ bubbles: true }}));
        }}

        // Localiza botão de submissão/geração
        const buttons = Array.from(document.querySelectorAll('button'));
        const genBtn = buttons.find(b => {{
            const txt = (b.innerText || b.getAttribute('aria-label') || '').toLowerCase();
            return txt.includes('gerar') || txt.includes('generate') || txt.includes('criar') || txt.includes('create') || txt.includes('submit');
        }});

        if (!genBtn) {{
            return {{ success: false, error: "NO_GENERATE_BUTTON_FOUND", inputFilled: true }};
        }}

        if (genBtn.disabled) {{
            return {{ success: false, error: "GENERATE_BUTTON_DISABLED", inputFilled: true }};
        }}

        genBtn.click();
        return {{ success: true, error: null }};
    }})()
    """
    return cdp.eval_js(js_inject)


def wait_for_generation_and_download(
    cdp: CDPConnection,
    download_dir: str,
    timeout_generation_sec: int = DEFAULT_TIMEOUT_GENERATION_SEC,
    timeout_download_sec: int = DEFAULT_DOWNLOAD_WAIT_SEC,
) -> str:
    """
    Acompanha o ciclo de geração do clipe até a conclusão, dispara o download e valida a conclusão do arquivo.
    Garante fail-closed se timeout ou falha na renderização.
    """
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
                const videos = Array.from(document.querySelectorAll('video')).filter(v => v.src || v.currentSrc);
                const dlBtns = Array.from(document.querySelectorAll('button, a')).filter(el => {
                    const txt = (el.innerText || el.getAttribute('aria-label') || '').toLowerCase();
                    return txt.includes('download') || txt.includes('baixar');
                });
                return {
                    hasVideo: videos.length > 0,
                    hasDownloadBtn: dlBtns.length > 0
                };
            })()
            """
            ready_info = cdp.eval_js(js_check_ready)
            if ready_info.get("hasVideo") or ready_info.get("hasDownloadBtn"):
                logger.info("Vídeo gerado detectado com sucesso no estúdio!")
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
        // Se houver vídeo com src direto, tenta disparar download programático
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
    logger.info(f"Acompanhando download em {download_dir} (timeout: {timeout_download_sec}s)...")
    dl_start = time.time()
    downloaded_file = None

    while time.time() - dl_start < timeout_download_sec:
        time.sleep(1)
        crdownloads = glob.glob(os.path.join(download_dir, "*.crdownload"))
        mp4_files = glob.glob(os.path.join(download_dir, "*.mp4"))

        # Se não há mais download pendente e há pelo menos um mp4
        if not crdownloads and mp4_files:
            # Pega o arquivo mp4 mais recente
            latest_mp4 = max(mp4_files, key=os.path.getmtime)
            if os.path.getsize(latest_mp4) > 0:
                downloaded_file = latest_mp4
                break

    if not downloaded_file:
        raise TimeoutError(f"FAIL_CLOSED: Timeout de download ({timeout_download_sec}s) em {download_dir}.")

    logger.info(f"Download concluído: {downloaded_file} ({os.path.getsize(downloaded_file)} bytes)")
    return downloaded_file


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
                    "credits_status": "UNKNOWN",
                    "error": "Sessão Google não autenticada. Operador deve fazer login manualmente.",
                }

        # Sessão autenticada: verificar créditos
        if state.get("creditsAvailable") is False or state.get("credits") == 0:
            logger.error("FAIL-CLOSED: Créditos de IA da assinatura esgotados ou indisponíveis.")
            return {
                "status": "BLOCKED_NO_CREDITS",
                "scene_index": scene_index,
                "google_session_status": "AUTHENTICATED",
                "captcha_status": "NONE",
                "credits_status": "ZERO_OR_UNAVAILABLE",
                "error": "Créditos indisponíveis. FAIL-CLOSED.",
            }

        # Verificar se já há geração ativa
        if state.get("isGenerating"):
            logger.error("FAIL-CLOSED: Outra geração já está em andamento no estúdio.")
            return {
                "status": "BLOCKED_GENERATION_IN_PROGRESS",
                "scene_index": scene_index,
                "google_session_status": "AUTHENTICATED",
                "captcha_status": "NONE",
                "credits_status": "AVAILABLE",
                "error": "Geração ativa detectada. Evitando duplicidade.",
            }

        # 5. Configurar diretório temporário para download
        temp_download_dir = os.path.join(project_dir, "temp_downloads")
        os.makedirs(temp_download_dir, exist_ok=True)
        cdp.set_download_path(temp_download_dir)

        # 6. Injetar prompt e disparar geração uma única vez
        logger.info(f"Injetando prompt da Cena {scene_index} no Google Flow...")
        inj_res = inject_prompt_and_generate(cdp, prompt)
        if not inj_res.get("success"):
            logger.error(f"FAIL-CLOSED: Falha na injeção ou disparo da geração: {inj_res.get('error')}")
            return {
                "status": "FAIL_GENERATE_TRIGGER",
                "scene_index": scene_index,
                "google_session_status": "AUTHENTICATED",
                "captcha_status": "NONE",
                "credits_status": "AVAILABLE",
                "generation_attempts": 1,
                "error": inj_res.get("error"),
            }

        # 7 & 8. Acompanhar geração e efetuar download
        downloaded_temp_path = wait_for_generation_and_download(
            cdp=cdp,
            download_dir=temp_download_dir,
            timeout_generation_sec=timeout_sec,
        )

        # 9. Validar arquivo baixado
        val = validate_clip_file(downloaded_temp_path)
        if not val["valid"]:
            logger.error(f"FAIL-CLOSED: Arquivo baixado é inválido: {val['error']}")
            return {
                "status": "FAIL_INVALID_DOWNLOAD",
                "scene_index": scene_index,
                "google_session_status": "AUTHENTICATED",
                "captcha_status": "NONE",
                "credits_status": "AVAILABLE",
                "generation_attempts": 1,
                "download_completed": False,
                "error": val["error"],
            }

        # 10. Mover atomicamente para o destino canônico da Video Factory
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
            "captcha_status": "NONE",
            "credits_status": "AVAILABLE",
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
        print(f"Login Pendente:        {state.get('hasLoginBtn') or state.get('isLandingAbout') or state.get('isAccountsPage')}")
        print(f"Desafio CAPTCHA:       {state.get('hasCaptcha')}")
        print(f"Créditos Disponíveis:  {state.get('creditsAvailable')}")
        print(f"Geração em Andamento:  {state.get('isGenerating')}")
        print(f"Inputs de Prompt:      {state.get('inputCandidatesCount')}")
        print(f"Amostra de Botões:     {state.get('buttonsSample')}")

        if state.get("hasCaptcha"):
            print("\n[ALERTA] Desafio CAPTCHA detectado! Intervenção humana necessária.")
        elif not state.get("isAuthenticated"):
            print("\n[AVISO] Sessão NÃO autenticada no perfil storage/flow_browser_profile.")
            print("Estado: AWAITING_INITIAL_HUMAN_LOGIN")
            print("Execute: python scripts/flow_web_automation.py open para fazer login manual.")
        else:
            print("\n[OK] Sessão autenticada e pronta para automação no Google Flow!")
    finally:
        cdp.close()


def main():
    parser = argparse.ArgumentParser(description="Google Flow Web Automation Helper (V1.4A POC)")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("open", help="Abre o navegador com o perfil persistente para login manual")
    subparsers.add_parser("status", help="Verifica autenticação e estado da UI do Flow")

    gen_p = subparsers.add_parser("generate", help="Executa POC de geração para uma única cena")
    gen_p.add_argument("--manifest", required=True, help="Caminho para manifest.json")
    gen_p.add_argument("--scene", type=int, default=1, help="Número da cena a gerar (padrão: 1)")
    gen_p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_GENERATION_SEC, help="Timeout de geração em segundos")
    gen_p.add_argument("--wait-login", type=int, default=0, help="Tempo para aguardar login manual se não autenticado (segundos)")

    args = parser.parse_args()

    if args.command == "open":
        open_browser_for_user()
    elif args.command == "status":
        check_flow_status()
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
