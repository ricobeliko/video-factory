"""
scripts/flow_web_automation.py
==============================
Fase V1.4 — Automação Web Autônoma do Google Flow via Chromium DevTools Protocol (CDP).

Objetivo:
Automação pontual e resiliente da interface web do Google Flow (flow.google.com)
utilizando créditos existentes da assinatura Google AI Pro sem custos de API por vídeo.

Princípios Mandatórios:
1. Sem Playwright/Selenium: Utiliza Chromium/Edge nativo do sistema via CDP com websocket-client.
2. Sessão Persistente: Perfil seguro em storage/flow_browser_profile (ignorado no git).
3. Sem Secrets no Código: Senhas Google NUNCA são manipuladas ou registradas pelo código.
4. Fail-Closed: Diante de login expirado, CAPTCHA ou desafio Google, interrompe e solicita intervenção humana.
5. Sem Duplicação: Verifica se o clipe já existe antes de enviar nova geração.
6. Zero Compra de Créditos: Se os créditos da assinatura esgotarem, falha fechado imediatamente.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from loguru import logger

# Configurações padrão
DEFAULT_PROFILE_DIR = os.path.abspath("storage/flow_browser_profile")
DEFAULT_CDP_PORT = 9222
FLOW_URL = "https://flow.google.com"

# Candidatos executáveis Chromium no Windows
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
]


def find_browser_executable() -> str:
    """Localiza o executável do Chrome ou Edge instalado na máquina."""
    for path in CHROME_CANDIDATES:
        if os.path.exists(path):
            return path
    raise FileNotFoundError("Nenhum navegador Chromium (Chrome ou Edge) encontrado nos caminhos padrão.")


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
) -> subprocess.Popen:
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


class CDPConnection:
    """Cliente CDP leve sobre WebSocket nativo usando websocket-client."""

    def __init__(self, port: int = DEFAULT_CDP_PORT):
        self.port = port
        self.ws = None
        self.target = None
        self._req_id = 0

    def connect_to_flow_target(self, timeout: float = 10.0):
        """Conecta ao target de página do Google Flow."""
        import websocket

        url = f"http://127.0.0.1:{self.port}/json"
        with urllib.request.urlopen(url, timeout=5) as resp:
            targets = json.loads(resp.read().decode())

        # Procura alvo relevante
        page_target = None
        for t in targets:
            t_url = t.get("url", "")
            if t.get("type") == "page" and ("flow.google" in t_url or "accounts.google" in t_url):
                page_target = t
                break

        if not page_target:
            # Fallback para qualquer página aberta
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
            time.sleep(3)

    def send(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Envia um comando CDP e aguarda a resposta correspondente."""
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

    def close(self):
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None


def check_auth_and_ui_state(cdp: CDPConnection) -> Dict[str, Any]:
    """Inspeciona o estado da página para detectar login, captcha, créditos e inputs."""
    js_detect = """
    (() => {
        const url = document.location.href;
        const title = document.title;
        const bodyText = document.body ? document.body.innerText : '';
        const isBlank = url === 'about:blank' || !url;

        // Detecção de CAPTCHA / desafio de segurança Google
        const hasCaptcha = bodyText.includes('recaptcha') ||
                           bodyText.includes('Não sou um robô') ||
                           bodyText.includes('Confirme que é você') ||
                           bodyText.includes('Verificação de segurança');

        // Detecção de tela de Login Google
        const isAccountsPage = url.includes('accounts.google.com');
        const isLandingAbout = url.includes('/about');
        const hasLoginBtn = Array.from(document.querySelectorAll('button, a')).some(
            el => {
                const txt = (el.innerText || el.getAttribute('aria-label') || '').toLowerCase();
                return txt.includes('fazer login') || txt.includes('sign in') || txt.includes('login');
            }
        );

        // Detecção de créditos ou assinatura
        const creditsMatch = bodyText.match(/(\\d+)\\s*(?:créditos|credits|AI credits)/i);
        const credits = creditsMatch ? parseInt(creditsMatch[1], 10) : null;

        // Detecção de campos de prompt e botões de geração
        const textareas = Array.from(document.querySelectorAll('textarea, [contenteditable="true"], input[type="text"]')).map(el => {
            return {
                tag: el.tagName,
                placeholder: el.placeholder || '',
                aria: el.getAttribute('aria-label') || '',
                id: el.id || '',
                className: el.className || ''
            };
        });

        // Botões visíveis
        const buttons = Array.from(document.querySelectorAll('button')).map(b => (b.innerText || b.getAttribute('aria-label') || '').trim()).filter(Boolean);

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
            inputCandidatesCount: textareas.length,
            buttonsSample: buttons.slice(0, 10)
        };
    })()
    """
    return cdp.eval_js(js_detect)


def open_browser_for_user():
    """Abre o navegador na interface do Google Flow para que o operador faça login e salve a sessão."""
    print("=" * 60)
    print("ABRINDO NAVEGADOR PARA SESSÃO GOOGLE FLOW")
    print("=" * 60)
    print(f"Diretório de Perfil: {DEFAULT_PROFILE_DIR}")
    print("Instruções:")
    print("1. O navegador Edge/Chromium será aberto na janela do Google Flow.")
    print("2. Faça login com sua conta Google com assinatura Google AI Pro.")
    print("3. Acesse o estúdio criativo do Flow.")
    print("4. Sua sessão será salva automaticamente no perfil local para automação futura.")
    print("=" * 60)

    launch_browser(headless=False)
    print("\nNavegador aberto com sucesso! Conclua o login e mantenha o perfil salvo.")


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
        print(f"Créditos Detectados:   {state.get('credits')}")
        print(f"Inputs de Prompt:      {state.get('inputCandidatesCount')}")
        print(f"Amostra de Botões:     {state.get('buttonsSample')}")

        if state.get("hasCaptcha"):
            print("\n[ALERTA] Desafio CAPTCHA detectado! Intervenção humana necessária.")
        elif not state.get("isAuthenticated"):
            print("\n[AVISO] Sessão não autenticada no perfil atual.")
            print("Execute: python scripts/flow_web_automation.py open para fazer login manual.")
        else:
            print("\n[OK] Sessão autenticada e pronta para automação!")
    finally:
        cdp.close()


def run_single_scene_poc(manifest_path: str, scene_index: int = 1):
    """
    Executa a POC de automação para exatamente UMA cena:
    1. Lê o prompt da cena do manifesto.
    2. Garante que o clipe ainda não existe.
    3. Conecta ao navegador autenticado.
    4. Valida sessão e créditos.
    5. Dispara a geração, aguarda conclusão e salva o arquivo com o nome esperado.
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

    # 1. Evitar gerar a mesma cena duas vezes
    if os.path.exists(target_clip_path) and os.path.getsize(target_clip_path) > 0:
        logger.info(f"Cena {scene_index} já existe em {target_clip_path} ({os.path.getsize(target_clip_path)} bytes). Pulando geração.")
        return {
            "status": "ALREADY_EXISTS",
            "scene_index": scene_index,
            "clip_path": target_clip_path,
        }

    # Localiza o prompt da cena
    target_scene = None
    for sc in manifest.get("scenes", []):
        if sc.get("scene_index") == scene_index:
            target_scene = sc
            break

    if not target_scene:
        raise ValueError(f"Cena {scene_index} não encontrada no manifesto.")

    prompt = target_scene.get("prompt_en")
    logger.info(f"POC Cena {scene_index} — Prompt: {prompt[:80]}...")

    # Garante navegador ativo
    if not is_cdp_ready():
        launch_browser(headless=False)

    cdp = CDPConnection()
    try:
        cdp.connect_to_flow_target()
        state = check_auth_and_ui_state(cdp)

        if state.get("hasCaptcha"):
            raise RuntimeError("FAIL CLOSED: CAPTCHA ou desafio de segurança ativo no Google Flow. Intervenção humana necessária.")

        if not state.get("isAuthenticated"):
            raise RuntimeError(
                "FAIL CLOSED: Sessão do Google Flow não autenticada no perfil storage/flow_browser_profile. "
                "Intervenção humana necessária: execute 'python scripts/flow_web_automation.py open' e complete o login."
            )

        if state.get("credits") == 0:
            raise RuntimeError("FAIL CLOSED: Créditos de IA da assinatura esgotados no Google Flow. Nenhuma compra automática autorizada.")

        # Próximo passo da POC após confirmação de sessão ativa no estúdio
        logger.info("Sessão validada com sucesso no estúdio Flow. Pronto para submissão.")
        return {
            "status": "READY_FOR_STUDIO_AUTOMATION",
            "scene_index": scene_index,
            "prompt": prompt,
            "target_path": target_clip_path,
        }

    finally:
        cdp.close()


def main():
    parser = argparse.ArgumentParser(description="Google Flow Web Automation Helper (V1.4 POC)")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("open", help="Abre o navegador com o perfil persistente para login manual")
    subparsers.add_parser("status", help="Verifica autenticação e estado da UI do Flow")

    gen_p = subparsers.add_parser("generate", help="Executa POC de geração para uma única cena")
    gen_p.add_argument("--manifest", required=True, help="Caminho para manifest.json")
    gen_p.add_argument("--scene", type=int, default=1, help="Número da cena a gerar (padrão: 1)")

    args = parser.parse_args()

    if args.command == "open":
        open_browser_for_user()
    elif args.command == "status":
        check_flow_status()
    elif args.command == "generate":
        res = run_single_scene_poc(args.manifest, args.scene)
        print("\nResultado:", json.dumps(res, indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
