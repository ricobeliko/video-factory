"""Pool de Contas e Telemetria de Créditos para Google Flow (FLOW-MA1).

Gerencia múltiplas contas autenticadas com perfis de navegador independentes,
seleção automática por saldo/prioridade, stickiness por tarefa e failover
seguro pré-dispatch.

ZERO segredos persistidos (senhas, cookies e tokens permanecem exclusivamente
nos perfis do navegador).
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from app.services.task_artifacts import atomic_write_json

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_CONFIG_PATH = os.path.join(ROOT_DIR, "storage", "flow_accounts.json")
DEFAULT_RUNTIME_PATH = os.path.join(ROOT_DIR, "storage", "flow_accounts_runtime.json")
LEGACY_ACCOUNT_ID = "flow-primary"
LEGACY_USER_DATA_DIR = os.path.join(ROOT_DIR, "storage", "flow_browser_profile")
SECONDARY_PROFILES_BASE_DIR = os.path.join(ROOT_DIR, "storage", "flow_browser_profiles")

# Estados operacionais permitidos
STATUS_AVAILABLE = "AVAILABLE"
STATUS_AVAILABLE_UNKNOWN_CREDITS = "AVAILABLE_UNKNOWN_CREDITS"
STATUS_LOW_CREDITS = "LOW_CREDITS"
STATUS_EXHAUSTED = "EXHAUSTED"
STATUS_COOLDOWN = "COOLDOWN"
STATUS_AUTH_REQUIRED = "AUTH_REQUIRED"
STATUS_AUTH_FAILED = "AUTH_FAILED"
STATUS_DISABLED = "DISABLED"
STATUS_BUSY = "BUSY"

NON_ELIGIBLE_STATUSES = {
    STATUS_DISABLED,
    STATUS_EXHAUSTED,
    STATUS_AUTH_FAILED,
    STATUS_AUTH_REQUIRED,
    STATUS_COOLDOWN,
    STATUS_BUSY,
}

# Fontes de telemetria de crédito
CREDIT_SOURCE_FLOW_UI_VERIFIED = "FLOW_UI_VERIFIED"
CREDIT_SOURCE_LOCAL_ESTIMATE = "LOCAL_ESTIMATE"
CREDIT_SOURCE_UNKNOWN = "UNKNOWN"

ACCOUNT_ID_PATTERN = re.compile(r"^[a-z0-9_-]+$")

_runtime_lock = threading.Lock()


def _get_config_path(custom: Optional[str] = None) -> str:
    return custom or DEFAULT_CONFIG_PATH


def _get_runtime_path(custom: Optional[str] = None) -> str:
    return custom or DEFAULT_RUNTIME_PATH


def validate_account_id(account_id: str) -> str:
    """Valida identificador de conta. Aceita apenas [a-z0-9_-] sem path traversal."""
    clean = str(account_id or "").strip()
    if not clean:
        raise ValueError("account_id cannot be empty")
    if ".." in clean or "/" in clean or "\\" in clean:
        raise ValueError(f"Path traversal detected in account_id '{clean}'")
    if not ACCOUNT_ID_PATTERN.match(clean):
        raise ValueError(
            f"Invalid account_id '{clean}'. Only lowercase alphanumeric, '-', and '_' are allowed."
        )
    return clean


def resolve_user_data_dir(account_id: str, base_dir: Optional[str] = None) -> str:
    """Retorna o diretório de dados do navegador para a conta informada."""
    valid_id = validate_account_id(account_id)
    if valid_id == LEGACY_ACCOUNT_ID:
        if base_dir:
            return os.path.join(base_dir, "flow_browser_profile")
        return LEGACY_USER_DATA_DIR
    if base_dir:
        return os.path.join(base_dir, "flow_browser_profiles", valid_id)
    return os.path.join(SECONDARY_PROFILES_BASE_DIR, valid_id)


def get_default_config() -> Dict[str, Any]:
    """Retorna a configuração default/virtual backward-compatible para conta primária."""
    return {
        "schema_version": 1,
        "accounts": [
            {
                "account_id": LEGACY_ACCOUNT_ID,
                "display_name": "Flow Primary",
                "enabled": True,
                "priority": 100,
                "user_data_dir": LEGACY_USER_DATA_DIR,
            }
        ],
    }


def load_accounts_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Carrega storage/flow_accounts.json. Se inexistente, retorna configuração padrão virtual."""
    path = _get_config_path(config_path)
    if not os.path.exists(path):
        return get_default_config()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "accounts" in data:
            return data
    except Exception as exc:
        logger.warning(f"[FLOW_ACCOUNT_POOL] Erro ao ler config de contas em {path}: {exc}")
    return get_default_config()


def save_accounts_config(config: Dict[str, Any], config_path: Optional[str] = None) -> None:
    """Salva atomicamente a configuração de contas."""
    path = _get_config_path(config_path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    atomic_write_json(path, config)


def load_runtime_state(runtime_path: Optional[str] = None) -> Dict[str, Any]:
    """Carrega storage/flow_accounts_runtime.json."""
    path = _get_runtime_path(runtime_path)
    if not os.path.exists(path):
        return {"schema_version": 1, "accounts": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "accounts" in data:
            return data
    except Exception as exc:
        logger.warning(f"[FLOW_ACCOUNT_POOL] Erro ao ler runtime em {path}: {exc}")
    return {"schema_version": 1, "accounts": {}}


def save_runtime_state(runtime: Dict[str, Any], runtime_path: Optional[str] = None) -> None:
    """Salva atomicamente o estado em runtime das contas."""
    path = _get_runtime_path(runtime_path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    atomic_write_json(path, runtime)


def get_account_runtime(account_id: str, runtime_path: Optional[str] = None) -> Dict[str, Any]:
    """Recupera o registro de runtime de uma conta com validação de expiração de cooldown."""
    with _runtime_lock:
        state = load_runtime_state(runtime_path)
        accounts_rt = state.get("accounts", {})
        rt = accounts_rt.get(account_id)
        if rt:
            if rt.get("status") == STATUS_COOLDOWN and rt.get("cooldown_until"):
                try:
                    exp = datetime.fromisoformat(rt["cooldown_until"])
                    if datetime.now(timezone.utc) >= exp:
                        rt["status"] = STATUS_AVAILABLE
                        rt["cooldown_until"] = None
                        save_runtime_state(state, runtime_path)
                except Exception:
                    pass
            return dict(rt)

        return {
            "account_id": account_id,
            "status": STATUS_AVAILABLE,
            "credits_remaining": None,
            "credits_source": CREDIT_SOURCE_UNKNOWN,
            "credits_last_verified_at": None,
            "last_credit_cost": None,
            "credits_used_since_verified": 0,
            "current_task_id": None,
            "last_task_id": None,
            "last_success_at": None,
            "last_error_at": None,
            "last_error": None,
            "cooldown_until": None,
        }


def update_account_runtime(
    account_id: str,
    updates: Dict[str, Any],
    runtime_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Atualiza de forma thread-safe e atômica campos de runtime de uma conta."""
    with _runtime_lock:
        state = load_runtime_state(runtime_path)
        accounts_rt = state.setdefault("accounts", {})
        curr = accounts_rt.get(account_id, {
            "account_id": account_id,
            "status": STATUS_AVAILABLE,
            "credits_remaining": None,
            "credits_source": CREDIT_SOURCE_UNKNOWN,
            "credits_last_verified_at": None,
            "last_credit_cost": None,
            "credits_used_since_verified": 0,
            "current_task_id": None,
            "last_task_id": None,
            "last_success_at": None,
            "last_error_at": None,
            "last_error": None,
            "cooldown_until": None,
        })
        curr.update(updates)
        accounts_rt[account_id] = curr
        save_runtime_state(state, runtime_path)
        return dict(curr)


def record_credit_deduction(
    account_id: str,
    cost: int,
    runtime_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Deduz créditos consumidos por um dispatch confirmado, mudando a fonte para LOCAL_ESTIMATE."""
    with _runtime_lock:
        state = load_runtime_state(runtime_path)
        accounts_rt = state.setdefault("accounts", {})
        curr = accounts_rt.get(account_id, {
            "account_id": account_id,
            "status": STATUS_AVAILABLE,
            "credits_remaining": None,
            "credits_source": CREDIT_SOURCE_UNKNOWN,
            "credits_last_verified_at": None,
            "last_credit_cost": None,
            "credits_used_since_verified": 0,
            "current_task_id": None,
            "last_task_id": None,
            "last_success_at": None,
            "last_error_at": None,
            "last_error": None,
            "cooldown_until": None,
        })
        curr["last_credit_cost"] = int(cost)
        curr["credits_used_since_verified"] = int(curr.get("credits_used_since_verified", 0)) + int(cost)

        rem = curr.get("credits_remaining")
        if rem is not None:
            new_rem = max(0, int(rem) - int(cost))
            curr["credits_remaining"] = new_rem
            curr["credits_source"] = CREDIT_SOURCE_LOCAL_ESTIMATE
            if new_rem == 0:
                curr["status"] = STATUS_EXHAUSTED
            elif new_rem <= 15:
                curr["status"] = STATUS_LOW_CREDITS

        accounts_rt[account_id] = curr
        save_runtime_state(state, runtime_path)
        return dict(curr)


def record_verified_credit_balance(
    account_id: str,
    balance: int,
    runtime_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Reconcilia saldo com leitura verificada da UI, zerando o contador local estimado."""
    with _runtime_lock:
        state = load_runtime_state(runtime_path)
        accounts_rt = state.setdefault("accounts", {})
        curr = accounts_rt.get(account_id, {
            "account_id": account_id,
            "status": STATUS_AVAILABLE,
            "credits_remaining": None,
            "credits_source": CREDIT_SOURCE_UNKNOWN,
            "credits_last_verified_at": None,
            "last_credit_cost": None,
            "credits_used_since_verified": 0,
            "current_task_id": None,
            "last_task_id": None,
            "last_success_at": None,
            "last_error_at": None,
            "last_error": None,
            "cooldown_until": None,
        })
        now_iso = datetime.now(timezone.utc).isoformat()
        bal = max(0, int(balance))
        curr["credits_remaining"] = bal
        curr["credits_source"] = CREDIT_SOURCE_FLOW_UI_VERIFIED
        curr["credits_last_verified_at"] = now_iso
        curr["credits_used_since_verified"] = 0
        if bal == 0:
            curr["status"] = STATUS_EXHAUSTED
        elif bal <= 15:
            curr["status"] = STATUS_LOW_CREDITS
            if curr.get("status") in (STATUS_AUTH_FAILED, STATUS_AUTH_REQUIRED, STATUS_COOLDOWN):
                curr["last_error"] = None
                curr["cooldown_until"] = None
        else:
            curr["status"] = STATUS_AVAILABLE
            curr["last_error"] = None
            curr["cooldown_until"] = None

        accounts_rt[account_id] = curr
        save_runtime_state(state, runtime_path)
        return dict(curr)


def record_account_error(
    account_id: str,
    error: str,
    is_auth: bool = False,
    is_exhausted: bool = False,
    runtime_path: Optional[str] = None,
) -> None:
    """Registra falha de execução para a conta."""
    now_iso = datetime.now(timezone.utc).isoformat()
    status = STATUS_AUTH_FAILED if is_auth else (STATUS_EXHAUSTED if is_exhausted else None)
    updates: Dict[str, Any] = {
        "last_error": str(error),
        "last_error_at": now_iso,
    }
    if status:
        updates["status"] = status
    update_account_runtime(account_id, updates, runtime_path=runtime_path)


def record_account_success(
    account_id: str,
    task_id: Optional[str] = None,
    runtime_path: Optional[str] = None,
) -> None:
    """Registra conclusão bem-sucedida de cena/task para a conta."""
    now_iso = datetime.now(timezone.utc).isoformat()
    rt = get_account_runtime(account_id, runtime_path=runtime_path)
    updates: Dict[str, Any] = {
        "last_success_at": now_iso,
        "current_task_id": None,
    }
    if task_id:
        updates["last_task_id"] = task_id
    if rt.get("status") not in (STATUS_EXHAUSTED, STATUS_LOW_CREDITS, STATUS_DISABLED):
        updates["status"] = STATUS_AVAILABLE
    update_account_runtime(account_id, updates, runtime_path=runtime_path)


def select_flow_account(
    task_manifest: Optional[Dict[str, Any]] = None,
    config_path: Optional[str] = None,
    runtime_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Seleciona a conta mais apropriada no pool para uma nova cena/tarefa.

    Critérios de elegibilidade:
    - enabled = True
    - status NOT IN (DISABLED, EXHAUSTED, AUTH_FAILED, AUTH_REQUIRED, COOLDOWN, BUSY)

    Critérios de preferência:
    1. Conta já vinculada ao manifesto/tarefa (stickiness mandatória se já iniciada produção);
    2. Maior saldo de créditos conhecido;
    3. Maior prioridade configurada;
    4. Ordem estável por account_id.
    """
    config = load_accounts_config(config_path)
    accounts = config.get("accounts", [])

    # 1. Stickiness de task/manifest
    if task_manifest and task_manifest.get("flow_account_id"):
        bound_id = task_manifest["flow_account_id"]
        has_url = bool(task_manifest.get("flow_project_url"))
        has_completed = bool(task_manifest.get("flow_generation", {}).get("completed_scenes"))
        is_sticky = has_url or has_completed

        target = next((a for a in accounts if a.get("account_id") == bound_id), None)
        if target:
            rt = get_account_runtime(bound_id, runtime_path)
            if is_sticky:
                res = dict(target)
                res["runtime"] = rt
                return res
            rem = rt.get("credits_remaining")
            if target.get("enabled", True) and rt.get("status") not in NON_ELIGIBLE_STATUSES and (rem is None or rem >= 15):
                res = dict(target)
                res["runtime"] = rt
                return res

    # 2. Filtragem de contas elegíveis
    eligible: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for acct in accounts:
        if not acct.get("enabled", True):
            continue
        aid = acct.get("account_id")
        rt = get_account_runtime(aid, runtime_path)
        if rt.get("status") in NON_ELIGIBLE_STATUSES:
            continue
        eligible.append((acct, rt))

    if not eligible:
        return None

    # 3. Ordenação
    def _sort_key(item: Tuple[Dict[str, Any], Dict[str, Any]]):
        acct, rt = item
        rem = rt.get("credits_remaining")
        has_known = 1 if rem is not None else 0
        rem_val = rem if rem is not None else 0
        prio = acct.get("priority", 100)
        aid = acct.get("account_id", "")
        return (-has_known, -rem_val, -prio, aid)

    eligible.sort(key=_sort_key)
    chosen_acct, chosen_rt = eligible[0]
    res = dict(chosen_acct)
    res["runtime"] = chosen_rt
    return res


def can_failover_account(manifest: Dict[str, Any]) -> bool:
    """Verifica se é permitido realizar failover automático para outra conta.

    Failover é PERMITIDO SOMENTE se:
    - flow_project_url ainda NÃO existe;
    - Nenhuma cena Flow foi completada;
    - Nenhum dispatch ou aprovação de crédito foi confirmado.
    """
    if not manifest or not isinstance(manifest, dict):
        return False
    if manifest.get("flow_project_url"):
        return False
    flow_gen = manifest.get("flow_generation", {})
    if flow_gen.get("completed_scenes"):
        return False
    if flow_gen.get("generation_start_confirmed") or flow_gen.get("credit_approval_confirmed"):
        return False
    return True


def failover_flow_account(
    manifest_path: str,
    failed_account_id: str,
    error_reason: str,
    config_path: Optional[str] = None,
    runtime_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Executa failover automático seguro para uma nova conta no pool se pré-dispatch."""
    if not os.path.exists(manifest_path):
        return None
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception:
        return None

    if not can_failover_account(manifest):
        logger.warning(
            f"[FLOW_FAILOVER] Failover proibido para {manifest_path}: projeto já iniciado na conta original."
        )
        return None

    is_auth = "auth" in error_reason.lower() or "login" in error_reason.lower()
    is_exhausted = "exhausted" in error_reason.lower() or "credit" in error_reason.lower()
    now_iso = datetime.now(timezone.utc).isoformat()
    cooldown_until = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()

    status = STATUS_AUTH_FAILED if is_auth else (STATUS_EXHAUSTED if is_exhausted else STATUS_COOLDOWN)
    update_account_runtime(
        failed_account_id,
        {
            "status": status,
            "last_error": str(error_reason),
            "last_error_at": now_iso,
            "cooldown_until": cooldown_until if status == STATUS_COOLDOWN else None,
        },
        runtime_path=runtime_path,
    )

    temp_manifest = dict(manifest)
    temp_manifest["flow_account_id"] = None
    next_acc = select_flow_account(temp_manifest, config_path=config_path, runtime_path=runtime_path)

    if not next_acc or next_acc.get("account_id") == failed_account_id:
        logger.warning(f"[FLOW_FAILOVER] Nenhuma conta alternativa disponível para substituir '{failed_account_id}'.")
        return None

    new_aid = next_acc["account_id"]
    manifest["flow_account_id"] = new_aid
    atomic_write_json(manifest_path, manifest)
    logger.info(f"[FLOW_FAILOVER] Failover seguro executado: '{failed_account_id}' -> '{new_aid}' em {manifest_path}.")
    return next_acc


def resolve_manifest_account(
    manifest: Dict[str, Any],
    manifest_path: Optional[str] = None,
    config_path: Optional[str] = None,
    runtime_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve ou atribui atomicamente flow_account_id no manifesto da tarefa."""
    current_aid = manifest.get("flow_account_id")
    if current_aid:
        has_url = bool(manifest.get("flow_project_url"))
        has_completed = bool(manifest.get("flow_generation", {}).get("completed_scenes"))
        is_sticky = has_url or has_completed

        rt = get_account_runtime(current_aid, runtime_path)
        rem = rt.get("credits_remaining")
        st = rt.get("status")

        # Se for sticky, preserva a conta vinculada (não troca de conta em projeto já iniciado)
        if is_sticky:
            config = load_accounts_config(config_path)
            for a in config.get("accounts", []):
                if a.get("account_id") == current_aid:
                    res = dict(a)
                    res["runtime"] = rt
                    return res
            return {
                "account_id": current_aid,
                "display_name": current_aid,
                "enabled": True,
                "priority": 100,
                "user_data_dir": resolve_user_data_dir(current_aid),
                "runtime": rt,
            }

        # Se NÃO for sticky (pré-dispatch), avalia se a conta atual é elegível e possui saldo viável (>= 15)
        is_ineligible = st in NON_ELIGIBLE_STATUSES or (rem is not None and rem < 15)
        if not is_ineligible:
            config = load_accounts_config(config_path)
            for a in config.get("accounts", []):
                if a.get("account_id") == current_aid and a.get("enabled", True):
                    res = dict(a)
                    res["runtime"] = rt
                    return res

        # Pré-dispatch: se a conta vinculada for inelegível ou com saldo insuficiente, seleciona melhor conta no pool
        chosen = select_flow_account(manifest, config_path=config_path, runtime_path=runtime_path)
        if chosen and chosen.get("account_id") != current_aid:
            logger.info(
                f"[FLOW_ACCOUNT_RESOLVER] Pré-dispatch switch: conta '{current_aid}' "
                f"(status={st}, rem={rem}) substituída por '{chosen['account_id']}'."
            )
            manifest["flow_account_id"] = chosen["account_id"]
            if manifest_path and os.path.exists(manifest_path):
                try:
                    atomic_write_json(manifest_path, manifest)
                except Exception as exc:
                    logger.warning(f"Erro ao persistir novo flow_account_id no manifest: {exc}")
            return chosen

        config = load_accounts_config(config_path)
        for a in config.get("accounts", []):
            if a.get("account_id") == current_aid:
                res = dict(a)
                res["runtime"] = rt
                return res
        return {
            "account_id": current_aid,
            "display_name": current_aid,
            "enabled": True,
            "priority": 100,
            "user_data_dir": resolve_user_data_dir(current_aid),
            "runtime": rt,
        }

    # Manifesto legado com projeto já existente
    if manifest.get("flow_project_url") or manifest.get("flow_generation", {}).get("completed_scenes"):
        manifest["flow_account_id"] = LEGACY_ACCOUNT_ID
        if manifest_path and os.path.exists(manifest_path):
            try:
                atomic_write_json(manifest_path, manifest)
            except Exception as exc:
                logger.warning(f"Erro ao persistir flow_account_id legado no manifest: {exc}")
        return {
            "account_id": LEGACY_ACCOUNT_ID,
            "display_name": "Flow Primary",
            "enabled": True,
            "priority": 100,
            "user_data_dir": LEGACY_USER_DATA_DIR,
            "runtime": get_account_runtime(LEGACY_ACCOUNT_ID, runtime_path),
        }

    # Nova tarefa: seleciona do pool
    chosen = select_flow_account(manifest, config_path=config_path, runtime_path=runtime_path)
    if not chosen:
        chosen = {
            "account_id": LEGACY_ACCOUNT_ID,
            "display_name": "Flow Primary",
            "enabled": True,
            "priority": 100,
            "user_data_dir": LEGACY_USER_DATA_DIR,
            "runtime": get_account_runtime(LEGACY_ACCOUNT_ID, runtime_path),
        }

    manifest["flow_account_id"] = chosen["account_id"]
    if manifest_path and os.path.exists(manifest_path):
        try:
            atomic_write_json(manifest_path, manifest)
        except Exception as exc:
            logger.warning(f"Erro ao persistir flow_account_id no manifest: {exc}")
    return chosen


# ---------------------------------------------------------------------------
# Leitura de Crédito e Esgotamento na UI do Flow
# ---------------------------------------------------------------------------

FLOW_CREDIT_SPECIFIC_REGEX = re.compile(
    r"(?:(\d[\d\s,.]*)\s*(?:cr[eé]ditos?(?:\s+do)?\s*Google\s*Flow|Google\s*Flow\s*credits?|credits?\s+(?:of|for)\s+Google\s+Flow))|"
    r"(?:(?:cr[eé]ditos?(?:\s+do)?\s*Google\s*Flow|Google\s*Flow\s*credits?|credits?\s+(?:of|for)\s+Google\s+Flow)\s*[:\-]?\s*(\d[\d\s,.]*))",
    re.IGNORECASE,
)

CREDIT_REGEX = re.compile(
    r"(?:(\d[\d\s,.]*)\s*(?:cr[eé]ditos?|credits?))|(?:(?:cr[eé]ditos?|credits?)\s*[:\-]?\s*(\d[\d\s,.]*))",
    re.IGNORECASE,
)

EXHAUSTION_PATTERNS = [
    "not enough credits",
    "insufficient credits",
    "out of credits",
    "créditos insuficientes",
    "sem créditos suficientes",
    "0 créditos restantes",
    "0 credits remaining",
]


def read_flow_credit_balance(page: Any) -> Tuple[Optional[int], str]:
    """Lê saldo de créditos restantes do Google Flow na interface (fail-closed).

    1. Inspeciona se há exibição direta de créditos na interface.
    2. Se não houver, abre o menu da conta/avatar no canto superior direito
       (flow-header-user-icon / 'Detalhes da conta' / 'Account details').
    3. Lê o elemento específico de créditos do Google Flow (flow-account-panel, .credits-count).
    4. Fecha o menu com Escape.
    5. Se não houver evidência inequívoca de saldo Google Flow, retorna (None, CREDIT_SOURCE_UNKNOWN).
    """
    if not page:
        return None, CREDIT_SOURCE_UNKNOWN

    def _extract_from_text(raw_text: str, is_dedicated_element: bool = False) -> Optional[int]:
        if not raw_text:
            return None
        text = raw_text.strip()
        m_spec = FLOW_CREDIT_SPECIFIC_REGEX.search(text)
        if m_spec:
            num_str = m_spec.group(1) or m_spec.group(2)
            clean_num = re.sub(r"[^\d]", "", num_str)
            if clean_num:
                return int(clean_num)

        if is_dedicated_element:
            lower = text.lower()
            if any(
                term in lower
                for term in (
                    "additional",
                    "adicionais",
                    "adicional",
                    "daily",
                    "diário",
                    "diários",
                    "diaria",
                    "diarias",
                    "monthly",
                    "mensal",
                    "mensais",
                    "plan",
                    "plano",
                )
            ):
                return None
            m_gen = CREDIT_REGEX.search(text)
            if m_gen:
                num_str = m_gen.group(1) or m_gen.group(2)
                clean_num = re.sub(r"[^\d]", "", num_str)
                if clean_num:
                    return int(clean_num)
        return None

    try:
        # Etapa 1: Elementos dedicados de créditos diretamente na barra superior / UI
        direct_locators = page.locator(
            ".credits-count, [class*='credits-count'], [aria-label*='Exibição de créditos' i], [aria-label*='Credit display' i], [aria-label*='crédito' i], [aria-label*='credit' i]"
        )
        try:
            raw_cnt = direct_locators.count()
            cnt = int(raw_cnt) if isinstance(raw_cnt, (int, float)) else 0
        except Exception:
            cnt = 0

        for idx in range(min(cnt, 5)):
            try:
                el = direct_locators.nth(idx)
                txt = (el.inner_text() or el.get_attribute("aria-label") or "").strip()
                val = _extract_from_text(txt, is_dedicated_element=True)
                if val is not None:
                    logger.info(f"[FLOW_CREDIT_READER] Créditos lidos diretamente na UI: {val}")
                    return val, CREDIT_SOURCE_FLOW_UI_VERIFIED
            except Exception:
                continue

        # Etapa 2: Localizar e abrir o menu de conta/avatar no canto superior direito
        account_trigger = page.locator(
            "flow-header-user-icon [role='button'], flow-header-user-icon, [aria-label*='Detalhes da conta' i], [aria-label*='Account details' i], button[aria-label*='Conta' i], button[aria-label*='Account' i]"
        ).first

        try:
            raw_trig_cnt = account_trigger.count()
            trig_cnt = int(raw_trig_cnt) if isinstance(raw_trig_cnt, (int, float)) else 0
        except Exception:
            trig_cnt = 0

        if trig_cnt > 0 and getattr(account_trigger, "is_visible", lambda: False)() is True:
            account_trigger.click(timeout=2500)
            page.wait_for_timeout(500)

            panel = page.locator(
                "flow-account-panel, .flow-account-panel-over, [role='dialog'][aria-label*='conta' i], [role='dialog'][aria-label*='account' i], [role='dialog']"
            ).first

            panel_visible = False
            try:
                panel_visible = getattr(panel, "is_visible", lambda: False)() is True
            except Exception:
                panel_visible = False

            credit_found: Optional[int] = None
            if panel_visible:
                # 2.1 Busca primária nos seletores dedicados do painel
                panel_credit_locs = panel.locator(
                    ".credits-count, [class*='credits-count'], .credits-row, [aria-label*='Exibição de créditos' i], [aria-label*='Credit display' i], [aria-label*='crédito' i], [aria-label*='credit' i]"
                )
                try:
                    p_raw_cnt = panel_credit_locs.count()
                    p_cnt = int(p_raw_cnt) if isinstance(p_raw_cnt, (int, float)) else 0
                except Exception:
                    p_cnt = 0

                for idx in range(min(p_cnt, 5)):
                    try:
                        p_el = panel_credit_locs.nth(idx)
                        p_txt = (p_el.inner_text() or p_el.get_attribute("aria-label") or "").strip()
                        val = _extract_from_text(p_txt, is_dedicated_element=True)
                        if val is not None:
                            credit_found = val
                            break
                    except Exception:
                        continue

                # 2.2 Busca de fallback no texto geral do painel com padrão específico inequívoco
                if credit_found is None:
                    try:
                        p_full_text = panel.inner_text()
                        val = _extract_from_text(p_full_text, is_dedicated_element=False)
                        if val is not None:
                            credit_found = val
                    except Exception:
                        pass

            # Fecha o painel após leitura garantindo que backdrops do CDK sejam dispensados
            try:
                backdrop = page.locator(".cdk-overlay-backdrop")
                if getattr(backdrop, "count", lambda: 0)() > 0 and getattr(backdrop.first, "is_visible", lambda: False)() is True:
                    backdrop.first.click(force=True, timeout=1000)
                else:
                    page.keyboard.press("Escape")
            except Exception:
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass

            try:
                page.wait_for_timeout(200)
                backdrop = page.locator(".cdk-overlay-backdrop")
                if getattr(backdrop, "count", lambda: 0)() > 0 and getattr(backdrop.first, "is_visible", lambda: False)() is True:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(200)
            except Exception:
                pass

            if credit_found is not None:
                logger.info(f"[FLOW_CREDIT_READER] Créditos lidos no menu de conta: {credit_found}")
                return credit_found, CREDIT_SOURCE_FLOW_UI_VERIFIED

    except Exception as exc:
        logger.debug(f"[FLOW_CREDIT_READER] Leitura de créditos best-effort não concluída: {exc}")

    return None, CREDIT_SOURCE_UNKNOWN


def check_flow_page_exhausted(page: Any) -> bool:
    """Verifica se há evidência inequívoca de esgotamento de créditos na tela."""
    if not page:
        return False
    try:
        for pattern in EXHAUSTION_PATTERNS:
            loc = page.locator(f"text={pattern}")
            try:
                raw_cnt = loc.count()
                cnt = int(raw_cnt) if isinstance(raw_cnt, (int, float)) else 0
            except Exception:
                cnt = 0
            if cnt > 0 and getattr(loc.first, "is_visible", lambda: False)() is True:
                logger.warning(f"[FLOW_EXHAUSTION_GUARD] Evidência visível de esgotamento detectada: '{pattern}'")
                return True
    except Exception as exc:
        logger.debug(f"[FLOW_EXHAUSTION_GUARD] Erro ao checar esgotamento: {exc}")
    return False


# ---------------------------------------------------------------------------
# Telemetria para Frontend / Web UI
# ---------------------------------------------------------------------------

def get_flow_accounts_status(
    config_path: Optional[str] = None,
    runtime_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Retorna estado consolidado de todas as contas no pool formatado para consumo por frontend/UI."""
    config = load_accounts_config(config_path)
    accounts = config.get("accounts", [])

    result_accounts = []
    total_known = 0
    any_known = False

    for acct in accounts:
        aid = acct.get("account_id")
        rt = get_account_runtime(aid, runtime_path)
        rem = rt.get("credits_remaining")
        st = rt.get("status", STATUS_AVAILABLE)
        is_enabled = acct.get("enabled", True)

        # Apenas contas operacionais e elegíveis somam ao total utilizável do pool
        is_usable = is_enabled and st not in NON_ELIGIBLE_STATUSES
        if rem is not None and is_usable:
            total_known += rem
            any_known = True

        acc_summary = {
            "account_id": aid,
            "display_name": acct.get("display_name", aid),
            "enabled": acct.get("enabled", True),
            "priority": acct.get("priority", 100),
            "status": rt.get("status", STATUS_AVAILABLE),
            "credits_remaining": rem,
            "credits_source": rt.get("credits_source", CREDIT_SOURCE_UNKNOWN),
            "credits_last_verified_at": rt.get("credits_last_verified_at"),
            "current_task_id": rt.get("current_task_id"),
            "last_credit_cost": rt.get("last_credit_cost"),
            "last_success_at": rt.get("last_success_at"),
            "last_error": rt.get("last_error"),
        }
        result_accounts.append(acc_summary)

    active_acct = select_flow_account(config_path=config_path, runtime_path=runtime_path)
    active_id = active_acct["account_id"] if active_acct else None

    return {
        "accounts": result_accounts,
        "active_account_id": active_id,
        "total_known_credits": total_known if any_known else None,
    }


# ---------------------------------------------------------------------------
# Gerenciamento de Configuração (CLI & Admin)
# ---------------------------------------------------------------------------

def add_account(
    account_id: str,
    display_name: str,
    priority: int = 100,
    config_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Adiciona nova conta ao pool criando apenas configuração e pasta do navegador. ZERO login ou senha."""
    valid_id = validate_account_id(account_id)
    config = load_accounts_config(config_path)
    accounts = config.setdefault("accounts", [])

    for a in accounts:
        if a.get("account_id") == valid_id:
            raise ValueError(f"Account '{valid_id}' already exists.")

    user_data_dir = resolve_user_data_dir(valid_id)
    os.makedirs(user_data_dir, exist_ok=True)

    new_acc = {
        "account_id": valid_id,
        "display_name": display_name,
        "enabled": True,
        "priority": int(priority),
        "user_data_dir": user_data_dir,
    }
    accounts.append(new_acc)
    save_accounts_config(config, config_path)
    return new_acc


def disable_account(account_id: str, config_path: Optional[str] = None) -> bool:
    """Desativa uma conta no pool."""
    valid_id = validate_account_id(account_id)
    config = load_accounts_config(config_path)
    accounts = config.get("accounts", [])
    for a in accounts:
        if a.get("account_id") == valid_id:
            a["enabled"] = False
            save_accounts_config(config, config_path)
            return True
    return False


def enable_account(account_id: str, config_path: Optional[str] = None) -> bool:
    """Reativa uma conta no pool."""
    valid_id = validate_account_id(account_id)
    config = load_accounts_config(config_path)
    accounts = config.get("accounts", [])
    for a in accounts:
        if a.get("account_id") == valid_id:
            a["enabled"] = True
            save_accounts_config(config, config_path)
            return True
    return False


def get_account(account_id: str, config_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Busca uma conta cadastrada no pool."""
    valid_id = validate_account_id(account_id)
    config = load_accounts_config(config_path)
    for a in config.get("accounts", []):
        if a.get("account_id") == valid_id:
            return dict(a)
    return None


def find_edge_executable() -> Optional[str]:
    """Localiza o executável do Microsoft Edge no sistema operacional."""
    if os.name == "nt":
        candidates = [
            shutil.which("msedge"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        for c in candidates:
            if c and os.path.isfile(c):
                return c
    else:
        w_edge = shutil.which("microsoft-edge") or shutil.which("msedge")
        if w_edge and os.path.isfile(w_edge):
            return w_edge
    return None


def launch_edge_for_human_login(
    account_id: str,
    target_url: str = "https://flow.google.com",
    config_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Abre o Microsoft Edge nativo com o perfil isolado da conta para login humano inicial no Google Flow.

    NÃO usa Playwright.
    NÃO manipula credenciais, senhas, 2FA ou cookies.
    NÃO exige manifest.
    """
    valid_id = validate_account_id(account_id)
    acc = get_account(valid_id, config_path=config_path)
    user_data_dir = (acc.get("user_data_dir") if acc else None) or resolve_user_data_dir(valid_id)
    os.makedirs(user_data_dir, exist_ok=True)

    edge_bin = find_edge_executable()
    if not edge_bin:
        raise RuntimeError(
            "Microsoft Edge não encontrado no sistema. Instale o Edge ou adicione msedge ao PATH."
        )

    cmd = [
        edge_bin,
        f"--user-data-dir={os.path.abspath(user_data_dir)}",
        target_url,
    ]
    subprocess.Popen(cmd)

    return {
        "account_id": valid_id,
        "profile": os.path.abspath(user_data_dir),
        "mode": "HUMAN_LOGIN",
        "edge_launched": True,
        "edge_bin": edge_bin,
    }


def verify_flow_account_session(
    account_id: str,
    config_path: Optional[str] = None,
    runtime_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Verifica se a sessão persistida da conta no Playwright headless está autenticada.

    NÃO exige manifest.
    NÃO cria projeto.
    NÃO preenche prompt.
    NÃO clica Generate.
    NÃO consome créditos.
    """
    valid_id = validate_account_id(account_id)
    acc = get_account(valid_id, config_path=config_path)
    user_data_dir = (acc.get("user_data_dir") if acc else None) or resolve_user_data_dir(valid_id)
    profile_exists = os.path.exists(user_data_dir)

    result = {
        "account_id": valid_id,
        "login_status": "UNKNOWN",
        "profile_exists": profile_exists,
        "zero_generation": True,
        "zero_credit_consumption": True,
        "credits_remaining": None,
        "credits_source": CREDIT_SOURCE_UNKNOWN,
        "message": None,
    }

    try:
        from playwright.sync_api import sync_playwright
        from scripts.flow_playwright import launch_flow_context, check_login_state
    except Exception as imp_err:
        result["login_status"] = "AUTH_FAILED"
        result["message"] = f"Dependência ausente: {imp_err}"
        return result

    try:
        with sync_playwright() as p:
            context, err = launch_flow_context(
                p,
                user_data_dir=user_data_dir,
                headless=True,
            )
            if err:
                if "AWAITING_FLOW_EDGE_PROFILE_CLOSE" in err:
                    result["login_status"] = "AUTH_REQUIRED"
                    result["message"] = (
                        "Janela do Edge ainda aberta ou perfil bloqueado. "
                        "Feche completamente o Microsoft Edge antes de verificar."
                    )
                else:
                    result["login_status"] = "AUTH_REQUIRED"
                    result["message"] = f"Falha ao iniciar contexto: {err}"
                update_account_runtime(
                    valid_id,
                    {"status": STATUS_AUTH_REQUIRED, "last_error": result["message"]},
                    runtime_path=runtime_path,
                )
                return result

            page = context.pages[0] if context.pages else context.new_page()
            st = check_login_state(page)

            if st == "AUTHENTICATED":
                result["login_status"] = "AUTHENTICATED"
                try:
                    bal, src = read_flow_credit_balance(page)
                    if bal is not None:
                        result["credits_remaining"] = bal
                        result["credits_source"] = src
                        record_verified_credit_balance(valid_id, bal, runtime_path=runtime_path)
                    else:
                        update_account_runtime(
                            valid_id,
                            {
                                "status": STATUS_AVAILABLE,
                                "last_error": None,
                            },
                            runtime_path=runtime_path,
                        )
                except Exception:
                    update_account_runtime(
                        valid_id,
                        {
                            "status": STATUS_AVAILABLE,
                            "last_error": None,
                        },
                        runtime_path=runtime_path,
                    )
            else:
                result["login_status"] = "AUTH_REQUIRED"
                result["message"] = f"Sessão não autenticada no Flow: {st}"
                update_account_runtime(
                    valid_id,
                    {"status": STATUS_AUTH_REQUIRED, "last_error": result["message"]},
                    runtime_path=runtime_path,
                )

            context.close()
    except Exception as exc:
        result["login_status"] = "AUTH_REQUIRED"
        result["message"] = f"Exceção durante verificação: {exc}"
        update_account_runtime(
            valid_id,
            {"status": STATUS_AUTH_REQUIRED, "last_error": str(exc)},
            runtime_path=runtime_path,
        )

    return result


def cli_main():
    """Interface de Linha de Comando operacional mínima para o pool de contas."""
    parser = argparse.ArgumentParser(description="Google Flow Account Pool CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # list
    subparsers.add_parser("list", help="Lista todas as contas configuradas")

    # add
    add_parser = subparsers.add_parser("add", help="Adiciona uma nova conta ao pool")
    add_parser.add_argument("--account-id", required=True, help="Identificador único (ex: flow-b)")
    add_parser.add_argument("--display-name", required=True, help="Nome de exibição (ex: 'Conta B')")
    add_parser.add_argument("--priority", type=int, default=90, help="Prioridade de seleção (default 90)")

    # login (onboarding humano via Edge nativo)
    login_parser = subparsers.add_parser(
        "login",
        help="Abre o Microsoft Edge nativo com o perfil da conta para autenticação humana inicial",
    )
    login_parser.add_argument("--account-id", required=True, help="Identificador único da conta (ex: flow-b)")

    # verify (validação de sessão via Playwright headless)
    verify_parser = subparsers.add_parser(
        "verify",
        help="Verifica se a sessão persistida da conta está autenticada via Playwright headless",
    )
    verify_parser.add_argument("--account-id", required=True, help="Identificador único da conta (ex: flow-b)")

    # disable
    dis_parser = subparsers.add_parser("disable", help="Desativa uma conta")
    dis_parser.add_argument("--account-id", required=True, help="Identificador da conta")

    # enable
    en_parser = subparsers.add_parser("enable", help="Ativa uma conta")
    en_parser.add_argument("--account-id", required=True, help="Identificador da conta")

    # status
    subparsers.add_parser("status", help="Exibe status e telemetria consolidada de todas as contas")

    args = parser.parse_args()

    if args.command == "list":
        cfg = load_accounts_config()
        print(f"\nGoogle Flow Accounts Pool ({len(cfg.get('accounts', []))} contas):")
        print("-" * 70)
        for a in cfg.get("accounts", []):
            st = "ENABLED" if a.get("enabled", True) else "DISABLED"
            print(f"- [{a['account_id']}] {a['display_name']} ({st}) | Prio: {a.get('priority', 100)} | Path: {a['user_data_dir']}")
        print("-" * 70)

    elif args.command == "add":
        acc = add_account(args.account_id, args.display_name, priority=args.priority)
        print(f"Conta '{acc['account_id']}' adicionada com sucesso!")
        print(f"Diretório de perfil: {acc['user_data_dir']}")
        print("\nPara login inicial humano, execute:")
        print(f"  python -m app.services.flow_account_pool login --account-id {acc['account_id']}")
        print("\nApós concluir o login e fechar o Edge, valide com:")
        print(f"  python -m app.services.flow_account_pool verify --account-id {acc['account_id']}")

    elif args.command == "login":
        try:
            res = launch_edge_for_human_login(args.account_id)
            print(f"FLOW ACCOUNT = {res['account_id']}")
            print(f"PROFILE = {res['profile']}")
            print(f"MODE = {res['mode']}")
            print(f"EDGE_LAUNCHED = {res['edge_launched']}")
            print("\nFaça login manualmente no Google Flow.")
            print("Após concluir, feche completamente esta janela do Edge.")
            print("Depois execute:\n")
            print(f"python -m app.services.flow_account_pool verify --account-id {res['account_id']}")
        except Exception as exc:
            print(f"ERRO AO ABRIR EDGE: {exc}")
            sys.exit(1)

    elif args.command == "verify":
        try:
            res = verify_flow_account_session(args.account_id)
            print(f"ACCOUNT_ID = {res['account_id']}")
            print(f"LOGIN_STATUS = {res['login_status']}")
            print(f"PROFILE_EXISTS = {res['profile_exists']}")
            print("ZERO_GENERATION = True")
            print("ZERO_CREDIT_CONSUMPTION = True")
            if res.get("credits_remaining") is not None:
                print(f"CREDITS_REMAINING = {res['credits_remaining']}")
                print(f"CREDITS_SOURCE = {res['credits_source']}")
            else:
                print("CREDITS_REMAINING = UNKNOWN")
                print(f"CREDITS_SOURCE = {res.get('credits_source', CREDIT_SOURCE_UNKNOWN)}")
            if res.get("message"):
                print(f"MESSAGE = {res['message']}")

            if res["login_status"] == "AUTHENTICATED":
                sys.exit(0)
            else:
                sys.exit(1)
        except Exception as exc:
            print(f"ERRO NA VERIFICAÇÃO: {exc}")
            sys.exit(1)

    elif args.command == "disable":
        ok = disable_account(args.account_id)
        if ok:
            print(f"Conta '{args.account_id}' desativada.")
        else:
            print(f"Conta '{args.account_id}' não encontrada.")
            sys.exit(1)

    elif args.command == "enable":
        ok = enable_account(args.account_id)
        if ok:
            print(f"Conta '{args.account_id}' ativada.")
        else:
            print(f"Conta '{args.account_id}' não encontrada.")
            sys.exit(1)

    elif args.command == "status":
        st = get_flow_accounts_status()
        print(json.dumps(st, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    cli_main()
