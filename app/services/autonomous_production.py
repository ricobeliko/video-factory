"""
Serviço de Orquestração da Produção Autônoma (Fase V12-E).

Transforma a Video Factory em uma fábrica de conteúdo autônoma e self-feeding:
1. Detecta falta de estoque pronto (ready stock < target).
2. Escolhe novos temas via Trend Radar / Content Strategy sem duplicação.
3. Cria tasks e submete ao pipeline existente (webui_task).
4. Avalia Quality Score e Safety Gate após a geração.
5. Descarta/retém conteúdo inadequado (Quality < 55 ou Safety REVIEW/BLOCK).
6. Alimenta o Scheduler existente exclusivamente para YouTube (TikTok bloqueado nesta fase).
7. Mantém estoque mínimo respeitando o Growth Mode e limites diários de segurança.
8. NÃO constrói segundo pipeline; reutiliza estritamente os serviços existentes.
9. NUNCA publica diretamente: o Scheduler Worker permanece como único executor da publicação.
"""
import math
import os
import shutil
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from app.config import config
from app.models import const
from app.models.schema import (
    VideoAspect,
    VideoConcatMode,
    VideoFitMode,
    VideoParams,
    VideoTransitionMode,
    _SUBTITLE_ANIMATIONS,
    _SUBTITLE_DISPLAY_MODES,
    _get_valid_ui_choice,
)
from app.services import (
    analytics,
    content_strategy,
    operator_console,
    profile_manager,
    quality_score,
    safety_gate,
    scheduler,
    trend_radar,
    voice,
    webui_task,
)
from app.utils import utils

# Estados da Máquina de Estados Autônoma
STATE_DISABLED = "disabled"
STATE_IDLE = "idle"
STATE_PLANNING = "planning"
STATE_GENERATING = "generating"
STATE_REVIEWING = "reviewing"
STATE_SCHEDULING = "scheduling"
STATE_WAITING_SCHEDULE = "waiting_schedule"
STATE_COOLDOWN = "cooldown"
STATE_BLOCKED = "blocked"
STATE_ERROR = "error"

VALID_AUTONOMOUS_STATES = {
    STATE_DISABLED,
    STATE_IDLE,
    STATE_PLANNING,
    STATE_GENERATING,
    STATE_REVIEWING,
    STATE_SCHEDULING,
    STATE_WAITING_SCHEDULE,
    STATE_COOLDOWN,
    STATE_BLOCKED,
    STATE_ERROR,
}

# Fontes de mídia permitidas sem supervisão para modo autônomo (fontes seguras/gratuitas)
ALLOWED_AUTONOMOUS_VIDEO_SOURCES = frozenset({"pexels", "pixabay", "coverr"})


class AutonomousConfigError(ValueError):
    """Erro de validação ou contrato de configuração para a produção autônoma."""
    pass


# Configurações padrão seguras
DEFAULT_AUTONOMOUS_MODE_ENABLED = False
DEFAULT_AUTONOMOUS_MAX_NEW_TASKS_PER_CYCLE = 1
DEFAULT_AUTONOMOUS_MAX_GENERATIONS_24H = 5
DEFAULT_AUTONOMOUS_CYCLE_INTERVAL_MINUTES = 15
MIN_REQUIRED_DISK_FREE_GB = 2.0
MIN_QUALITY_SCORE_FOR_AUTONOMOUS = 70.0

# Chaves de persistência em autopilot_settings
KEY_AUTONOMOUS_ENABLED = "autonomous_mode_enabled"
KEY_AUTONOMOUS_TARGET_STOCK = "autonomous_target_ready_stock"
KEY_AUTONOMOUS_MAX_TASKS_PER_CYCLE = "autonomous_max_new_tasks_per_cycle"
KEY_AUTONOMOUS_MAX_24H = "autonomous_max_generations_24h"
KEY_AUTONOMOUS_INTERVAL_MINUTES = "autonomous_cycle_interval_minutes"
KEY_AUTONOMOUS_LAST_TICK = "autonomous_last_tick"
KEY_AUTONOMOUS_STATE = "autonomous_state"
KEY_AUTONOMOUS_MESSAGE = "autonomous_message"
KEY_AUTONOMOUS_LAST_RESULT = "autonomous_last_result"
KEY_AUTONOMOUS_CURRENT_TASK_ID = "autonomous_current_task_id"
KEY_AUTONOMOUS_WAITING_TASK_ID = "autonomous_waiting_task_id"
KEY_AUTONOMOUS_LAST_ERROR = "autonomous_last_error"
KEY_AUTONOMOUS_CONSECUTIVE_REJECTIONS = "autonomous_consecutive_rejections"
KEY_AUTONOMOUS_MAX_ATTEMPTS_24H = "autonomous_max_attempts_24h"
KEY_AUTONOMOUS_LAST_NARRATIVE_STRUCTURE = "autonomous_last_narrative_structure"
KEY_AUTONOMOUS_REJECTED_NARRATIVE_STRUCTURE = "autonomous_rejected_narrative_structure"

# Chaves de persistência Global Cost Guard (Fase V12-F.5)
KEY_AUTONOMOUS_GLOBAL_MAX_24H = "autonomous_global_max_generations_24h"
KEY_AUTONOMOUS_GLOBAL_MAX_ATTEMPTS_24H = "autonomous_global_max_attempts_24h"

DEFAULT_AUTONOMOUS_MAX_CONSECUTIVE_REJECTIONS = 10
DEFAULT_AUTONOMOUS_MAX_ATTEMPTS_24H = 15
DEFAULT_AUTONOMOUS_GLOBAL_MAX_GENERATIONS_24H = 10
DEFAULT_AUTONOMOUS_GLOBAL_MAX_ATTEMPTS_24H = 25
_cycle_lock = threading.Lock()


# ---------------------------------------------------------------------------
# 1. Configurações Persistentes
# ---------------------------------------------------------------------------

def get_autonomous_setting(key: str, default: Any = None, db_path: Optional[str] = None) -> Any:
    """Lê configuração persistida do autonomous loop na tabela autopilot_settings."""
    return scheduler.get_setting(key, default, db_path=db_path)


def set_autonomous_setting(key: str, value: Any, db_path: Optional[str] = None) -> None:
    """Grava configuração persistida do autonomous loop na tabela autopilot_settings."""
    scheduler.set_setting(key, str(value), db_path=db_path)


def is_autonomous_mode_enabled(db_path: Optional[str] = None) -> bool:
    """Verifica se a produção autônoma está habilitada no banco."""
    val = get_autonomous_setting(KEY_AUTONOMOUS_ENABLED, str(DEFAULT_AUTONOMOUS_MODE_ENABLED), db_path=db_path)
    return str(val).lower() in ("true", "1", "yes")


def is_profile_autonomous_mode_enabled(profile_id: Optional[str] = None, db_path: Optional[str] = None) -> bool:
    """Verifica se a produção autônoma está habilitada para um perfil específico.

    O perfil padrão obedece ao switch global KEY_AUTONOMOUS_ENABLED.
    Perfis secundários possuem switch isolado (f'{KEY_AUTONOMOUS_ENABLED}:{profile_id}'),
    mantendo CONTINUOUS MODE estritamente OFF por padrão até homologação explícita.
    """
    clean_profile = str(profile_id or "").strip()
    if not clean_profile or clean_profile == profile_manager.DEFAULT_PROFILE_ID or clean_profile == "default":
        return is_autonomous_mode_enabled(db_path=db_path)
    val = get_autonomous_setting(f"{KEY_AUTONOMOUS_ENABLED}:{clean_profile}", "False", db_path=db_path)
    return str(val).lower() in ("true", "1", "yes")


def _get_cycle_setting(key: str, default: Any = None, profile_id: Optional[str] = None, db_path: Optional[str] = None) -> Any:
    clean_p = str(profile_id or "").strip()
    is_default = not clean_p or clean_p in (profile_manager.DEFAULT_PROFILE_ID, "default")
    if is_default:
        return get_autonomous_setting(key, default, db_path=db_path)
    val = get_autonomous_setting(f"{key}:{clean_p}", None, db_path=db_path)
    if val is not None:
        return val
    return default


def _set_cycle_setting(key: str, val: Any, profile_id: Optional[str] = None, db_path: Optional[str] = None) -> None:
    clean_p = str(profile_id or "").strip()
    is_default = not clean_p or clean_p in (profile_manager.DEFAULT_PROFILE_ID, "default")
    if is_default:
        set_autonomous_setting(key, val, db_path=db_path)
    else:
        set_autonomous_setting(f"{key}:{clean_p}", val, db_path=db_path)


def set_profile_autonomous_mode_enabled(profile_id: str, enabled: bool, db_path: Optional[str] = None) -> None:
    """Ativa ou desativa a produção autônoma de um perfil específico com validação de PRIMARY."""
    operator_console.require_primary_instance(db_path=db_path)
    clean_profile = str(profile_id or "").strip()
    if not clean_profile or clean_profile == profile_manager.DEFAULT_PROFILE_ID or clean_profile == "default":
        set_autonomous_mode_enabled(enabled, db_path=db_path)
        return
    val_str = "True" if enabled else "False"
    set_autonomous_setting(f"{KEY_AUTONOMOUS_ENABLED}:{clean_profile}", val_str, db_path=db_path)
    new_state = STATE_IDLE if enabled else STATE_DISABLED
    msg_state = "ativada" if enabled else "desativada"
    msg = f"Produção autônoma do perfil '{clean_profile}' {msg_state} pelo operador"
    set_autonomous_setting(f"{KEY_AUTONOMOUS_STATE}:{clean_profile}", new_state, db_path=db_path)
    set_autonomous_setting(f"{KEY_AUTONOMOUS_MESSAGE}:{clean_profile}", msg, db_path=db_path)
    operator_console.log_operational_event(
        component="autonomous_production",
        severity=operator_console.SEVERITY_INFO,
        event_type="profile_autonomous_mode_toggled",
        message=msg,
        metadata={"profile_id": clean_profile, "enabled": enabled},
        db_path=db_path,
    )
    logger.info(f"[AUTONOMOUS_PRODUCTION] {msg}")


def set_autonomous_mode_enabled(enabled: bool, db_path: Optional[str] = None) -> None:
    """Ativa ou desativa o modo autônomo com validação estrita de PRIMARY."""
    operator_console.require_primary_instance(db_path=db_path)
    val_str = "True" if enabled else "False"
    set_autonomous_setting(KEY_AUTONOMOUS_ENABLED, val_str, db_path=db_path)

    new_state = STATE_IDLE if enabled else STATE_DISABLED
    msg = "Produção autônoma ativada pelo operador" if enabled else "Produção autônoma desativada pelo operador"
    set_autonomous_setting(KEY_AUTONOMOUS_STATE, new_state, db_path=db_path)
    set_autonomous_setting(KEY_AUTONOMOUS_MESSAGE, msg, db_path=db_path)

    operator_console.log_operational_event(
        component="autonomous_production",
        severity=operator_console.SEVERITY_INFO,
        event_type="autonomous_mode_toggled",
        message=msg,
        metadata={"enabled": enabled},
        db_path=db_path,
    )
    logger.info(f"[AUTONOMOUS_PRODUCTION] {msg}")


def get_profile_growth_mode(profile_id: Optional[str] = None, db_path: Optional[str] = None) -> str:
    """Retorna o Growth Mode associado ao perfil de forma isolada."""
    clean_p = str(profile_id or "").strip()
    if clean_p and clean_p not in (profile_manager.DEFAULT_PROFILE_ID, "default"):
        try:
            prof = profile_manager.get_profile(clean_p, db_path=db_path)
            if prof and prof.get("growth_mode"):
                return str(prof.get("growth_mode")).lower().strip()
        except Exception:
            pass
    try:
        gm = scheduler.get_growth_mode("youtube", db_path=db_path)
        if gm:
            return str(gm).lower().strip()
    except Exception:
        pass
    return const.DEFAULT_GROWTH_MODE


def get_target_ready_stock(profile_id: Optional[str] = None, db_path: Optional[str] = None) -> int:
    """Retorna a meta de estoque pronto para um perfil específico (ou default).

    Regras V12-F.5:
    - WARMUP: default conservador = 3 (configurável de 3 a 6)
    - SCALE: default sugerido = 5 (configurável de 3 a 6)
    - Perfil default mantém fallback backward-compatible para a chave legada KEY_AUTONOMOUS_TARGET_STOCK.
    - Valores persistidos de produção não são alterados automaticamente.
    """
    clean_p = str(profile_id or "").strip()
    is_default = (not clean_p) or (clean_p in (profile_manager.DEFAULT_PROFILE_ID, "default"))

    stored = None
    if not is_default:
        stored = get_autonomous_setting(f"{KEY_AUTONOMOUS_TARGET_STOCK}:{clean_p}", None, db_path=db_path)
    else:
        if clean_p:
            stored = get_autonomous_setting(f"{KEY_AUTONOMOUS_TARGET_STOCK}:{clean_p}", None, db_path=db_path)
        if stored is None:
            stored = get_autonomous_setting(KEY_AUTONOMOUS_TARGET_STOCK, None, db_path=db_path)
        if stored is None:
            try:
                min_stock = operator_console.get_minimum_ready_stock(db_path=db_path)
                if min_stock is not None:
                    stored = min_stock
            except Exception:
                pass

    if stored is not None:
        try:
            val = int(stored)
            if not is_default:
                return max(3, min(6, val))
            return max(1, val)
        except (ValueError, TypeError):
            pass

    gm = get_profile_growth_mode(clean_p, db_path=db_path)
    if gm == const.GROWTH_MODE_SCALE:
        return 5
    return 3


def set_target_ready_stock(
    target: int,
    profile_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> None:
    """Grava a meta de estoque pronto isolada por perfil, validando o intervalo [3, 6]."""
    operator_console.require_primary_instance(db_path=db_path)
    clean_p = str(profile_id or "").strip()
    clamped_target = max(3, min(6, int(target)))
    is_default = (not clean_p) or (clean_p in (profile_manager.DEFAULT_PROFILE_ID, "default"))
    if not is_default:
        set_autonomous_setting(f"{KEY_AUTONOMOUS_TARGET_STOCK}:{clean_p}", str(clamped_target), db_path=db_path)
    else:
        if clean_p:
            set_autonomous_setting(f"{KEY_AUTONOMOUS_TARGET_STOCK}:{clean_p}", str(clamped_target), db_path=db_path)
        set_autonomous_setting(KEY_AUTONOMOUS_TARGET_STOCK, str(clamped_target), db_path=db_path)


def get_max_tasks_per_cycle(db_path: Optional[str] = None) -> int:
    """Retorna o limite de novas tarefas criadas por ciclo (padrão conservador 1)."""
    val = get_autonomous_setting(KEY_AUTONOMOUS_MAX_TASKS_PER_CYCLE, str(DEFAULT_AUTONOMOUS_MAX_NEW_TASKS_PER_CYCLE), db_path=db_path)
    try:
        return min(DEFAULT_AUTONOMOUS_MAX_NEW_TASKS_PER_CYCLE, max(1, int(val)))
    except (ValueError, TypeError):
        return DEFAULT_AUTONOMOUS_MAX_NEW_TASKS_PER_CYCLE


def get_max_generations_24h(profile_id: Optional[str] = None, db_path: Optional[str] = None) -> int:
    """Retorna o teto de gerações aprovadas em 24h para um perfil específico (ou default).

    Regras V12-F.5:
    - WARMUP: 2 / 24h
    - SCALE: 5 / 24h
    - Configuração isolada por perfil: autonomous_max_generations_24h:<profile_id>
    - Perfil default mantém compatibilidade com KEY_AUTONOMOUS_MAX_24H quando não houver override.
    """
    clean_p = str(profile_id or "").strip()
    is_default = (not clean_p) or (clean_p in (profile_manager.DEFAULT_PROFILE_ID, "default"))

    stored = None
    if not is_default:
        stored = get_autonomous_setting(f"{KEY_AUTONOMOUS_MAX_24H}:{clean_p}", None, db_path=db_path)
    else:
        if clean_p:
            stored = get_autonomous_setting(f"{KEY_AUTONOMOUS_MAX_24H}:{clean_p}", None, db_path=db_path)
        if stored is None:
            stored = get_autonomous_setting(KEY_AUTONOMOUS_MAX_24H, None, db_path=db_path)

    if stored is not None:
        try:
            return max(1, int(stored))
        except (ValueError, TypeError):
            pass

    gm = get_profile_growth_mode(clean_p, db_path=db_path)
    if gm == const.GROWTH_MODE_SCALE:
        return 5
    elif gm == const.GROWTH_MODE_WARMUP:
        return 2
    return DEFAULT_AUTONOMOUS_MAX_GENERATIONS_24H if is_default else 2


def set_max_generations_24h(
    val: int,
    profile_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> None:
    """Grava o teto de gerações aprovadas em 24h para um perfil específico."""
    operator_console.require_primary_instance(db_path=db_path)
    clean_p = str(profile_id or "").strip()
    clamped = max(1, int(val))
    is_default = (not clean_p) or (clean_p in (profile_manager.DEFAULT_PROFILE_ID, "default"))
    if not is_default:
        set_autonomous_setting(f"{KEY_AUTONOMOUS_MAX_24H}:{clean_p}", str(clamped), db_path=db_path)
    else:
        if clean_p:
            set_autonomous_setting(f"{KEY_AUTONOMOUS_MAX_24H}:{clean_p}", str(clamped), db_path=db_path)
        set_autonomous_setting(KEY_AUTONOMOUS_MAX_24H, str(clamped), db_path=db_path)


def get_cycle_interval_minutes(db_path: Optional[str] = None) -> int:
    """Retorna o intervalo entre ciclos normais em minutos."""
    val = get_autonomous_setting(KEY_AUTONOMOUS_INTERVAL_MINUTES, str(DEFAULT_AUTONOMOUS_CYCLE_INTERVAL_MINUTES), db_path=db_path)
    try:
        return max(1, int(val))
    except (ValueError, TypeError):
        return DEFAULT_AUTONOMOUS_CYCLE_INTERVAL_MINUTES


def get_consecutive_rejections(db_path: Optional[str] = None, profile_id: Optional[str] = None) -> int:
    """Retorna a contagem atual de rejeições consecutivas nos Gates."""
    clean_profile = str(profile_id or "").strip()
    if clean_profile and clean_profile != profile_manager.DEFAULT_PROFILE_ID:
        val = get_autonomous_setting(f"{KEY_AUTONOMOUS_CONSECUTIVE_REJECTIONS}:{clean_profile}", "0", db_path=db_path)
    else:
        val = get_autonomous_setting(KEY_AUTONOMOUS_CONSECUTIVE_REJECTIONS, "0", db_path=db_path)
    try:
        return max(0, int(val))
    except (ValueError, TypeError):
        return 0


def get_max_attempts_24h(profile_id: Optional[str] = None, db_path: Optional[str] = None) -> int:
    """Retorna o teto de tentativas totais de geração em 24h para um perfil específico (ou default).

    Regras V12-F.5:
    - WARMUP: 8 / 24h
    - SCALE: 15 / 24h
    - Configuração isolada por perfil: autonomous_max_attempts_24h:<profile_id>
    - Perfil default mantém compatibilidade com KEY_AUTONOMOUS_MAX_ATTEMPTS_24H quando não houver override.
    """
    clean_p = str(profile_id or "").strip()
    is_default = (not clean_p) or (clean_p in (profile_manager.DEFAULT_PROFILE_ID, "default"))

    stored = None
    if not is_default:
        stored = get_autonomous_setting(f"{KEY_AUTONOMOUS_MAX_ATTEMPTS_24H}:{clean_p}", None, db_path=db_path)
    else:
        if clean_p:
            stored = get_autonomous_setting(f"{KEY_AUTONOMOUS_MAX_ATTEMPTS_24H}:{clean_p}", None, db_path=db_path)
        if stored is None:
            stored = get_autonomous_setting(KEY_AUTONOMOUS_MAX_ATTEMPTS_24H, None, db_path=db_path)

    if stored is not None:
        try:
            return max(1, int(stored))
        except (ValueError, TypeError):
            pass

    gm = get_profile_growth_mode(clean_p, db_path=db_path)
    if gm == const.GROWTH_MODE_SCALE:
        return 15
    elif gm == const.GROWTH_MODE_WARMUP:
        return 8
    return DEFAULT_AUTONOMOUS_MAX_ATTEMPTS_24H if is_default else 8


def set_max_attempts_24h(
    val: int,
    profile_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> None:
    """Grava o teto de tentativas totais em 24h para um perfil específico."""
    operator_console.require_primary_instance(db_path=db_path)
    clean_p = str(profile_id or "").strip()
    clamped = max(1, int(val))
    is_default = (not clean_p) or (clean_p in (profile_manager.DEFAULT_PROFILE_ID, "default"))
    if not is_default:
        set_autonomous_setting(f"{KEY_AUTONOMOUS_MAX_ATTEMPTS_24H}:{clean_p}", str(clamped), db_path=db_path)
    else:
        if clean_p:
            set_autonomous_setting(f"{KEY_AUTONOMOUS_MAX_ATTEMPTS_24H}:{clean_p}", str(clamped), db_path=db_path)
        set_autonomous_setting(KEY_AUTONOMOUS_MAX_ATTEMPTS_24H, str(clamped), db_path=db_path)


def get_global_max_generations_24h(db_path: Optional[str] = None) -> int:
    """Retorna o teto global de gerações aprovadas em 24h somando todos os perfis."""
    val = get_autonomous_setting(KEY_AUTONOMOUS_GLOBAL_MAX_24H, str(DEFAULT_AUTONOMOUS_GLOBAL_MAX_GENERATIONS_24H), db_path=db_path)
    try:
        return max(1, int(val))
    except (ValueError, TypeError):
        return DEFAULT_AUTONOMOUS_GLOBAL_MAX_GENERATIONS_24H


def set_global_max_generations_24h(max_gen: int, db_path: Optional[str] = None) -> None:
    """Define o teto global de gerações aprovadas em 24h somando todos os perfis."""
    operator_console.require_primary_instance(db_path=db_path)
    set_autonomous_setting(KEY_AUTONOMOUS_GLOBAL_MAX_24H, str(max(1, int(max_gen))), db_path=db_path)


def get_global_max_attempts_24h(db_path: Optional[str] = None) -> int:
    """Retorna o teto global de tentativas de geração em 24h somando todos os perfis."""
    val = get_autonomous_setting(KEY_AUTONOMOUS_GLOBAL_MAX_ATTEMPTS_24H, str(DEFAULT_AUTONOMOUS_GLOBAL_MAX_ATTEMPTS_24H), db_path=db_path)
    try:
        return max(1, int(val))
    except (ValueError, TypeError):
        return DEFAULT_AUTONOMOUS_GLOBAL_MAX_ATTEMPTS_24H


def set_global_max_attempts_24h(max_att: int, db_path: Optional[str] = None) -> None:
    """Define o teto global de tentativas de geração em 24h somando todos os perfis."""
    operator_console.require_primary_instance(db_path=db_path)
    set_autonomous_setting(KEY_AUTONOMOUS_GLOBAL_MAX_ATTEMPTS_24H, str(max(1, int(max_att))), db_path=db_path)


def resolve_autonomous_youtube_channel(profile_id: str, db_path: Optional[str] = None) -> Optional[str]:
    """Resolve com segurança o canal YouTube ativo do perfil.

    Retorna o channel_id somente se houver exatamente um canal habilitado
    para a plataforma 'youtube' em um perfil ativo. Caso contrário (0 ou múltiplos),
    retorna None para garantir isolamento estrito e fail-safe para baseline.
    """
    clean_profile = str(profile_id or "").strip()
    if not clean_profile:
        return None
    try:
        with scheduler.get_connection(db_path) as conn:
            ch_rows = conn.execute(
                "SELECT c.id FROM publishing_channels c JOIN content_profiles p ON p.id = c.profile_id "
                "WHERE c.platform = 'youtube' AND c.profile_id = ? AND c.is_enabled = 1 AND p.is_active = 1",
                (clean_profile,),
            ).fetchall()
            if len(ch_rows) == 1:
                return str(ch_rows[0][0])
    except Exception:
        pass
    return None


def get_channel_last_narrative_structure(
    profile_id: str,
    channel_id: Optional[str],
    db_path: Optional[str] = None,
) -> Optional[str]:
    """Recupera a última estrutura narrativa isolada por perfil e canal."""
    clean_profile = str(profile_id or "").strip()
    clean_channel = str(channel_id or "").strip()
    if clean_profile and clean_channel:
        scoped_key = f"{KEY_AUTONOMOUS_LAST_NARRATIVE_STRUCTURE}:{clean_profile}:{clean_channel}"
        val = get_autonomous_setting(scoped_key, None, db_path=db_path)
        if val:
            return val
    if clean_profile == profile_manager.DEFAULT_PROFILE_ID:
        return get_autonomous_setting(KEY_AUTONOMOUS_LAST_NARRATIVE_STRUCTURE, None, db_path=db_path)
    return None


def set_channel_last_narrative_structure(
    profile_id: str,
    channel_id: Optional[str],
    structure: str,
    db_path: Optional[str] = None,
) -> None:
    """Persiste a última estrutura narrativa isolada por perfil e canal."""
    clean_profile = str(profile_id or "").strip()
    clean_channel = str(channel_id or "").strip()
    if clean_profile and clean_channel:
        scoped_key = f"{KEY_AUTONOMOUS_LAST_NARRATIVE_STRUCTURE}:{clean_profile}:{clean_channel}"
        set_autonomous_setting(scoped_key, structure, db_path=db_path)
    if clean_profile == profile_manager.DEFAULT_PROFILE_ID or not clean_profile:
        set_autonomous_setting(KEY_AUTONOMOUS_LAST_NARRATIVE_STRUCTURE, structure, db_path=db_path)


def get_channel_rejected_narrative_structure(
    profile_id: str,
    channel_id: Optional[str],
    db_path: Optional[str] = None,
) -> Optional[str]:
    clean_profile = str(profile_id or "").strip()
    clean_channel = str(channel_id or "").strip()
    if clean_profile and clean_channel:
        scoped_key = f"{KEY_AUTONOMOUS_REJECTED_NARRATIVE_STRUCTURE}:{clean_profile}:{clean_channel}"
        val = get_autonomous_setting(scoped_key, None, db_path=db_path)
        if val:
            return val
    if clean_profile == profile_manager.DEFAULT_PROFILE_ID:
        return get_autonomous_setting(KEY_AUTONOMOUS_REJECTED_NARRATIVE_STRUCTURE, None, db_path=db_path)
    return None


def set_channel_rejected_narrative_structure(
    profile_id: str,
    channel_id: Optional[str],
    structure: str,
    db_path: Optional[str] = None,
) -> None:
    clean_profile = str(profile_id or "").strip()
    clean_channel = str(channel_id or "").strip()
    if clean_profile and clean_channel:
        scoped_key = f"{KEY_AUTONOMOUS_REJECTED_NARRATIVE_STRUCTURE}:{clean_profile}:{clean_channel}"
        set_autonomous_setting(scoped_key, structure, db_path=db_path)
    if clean_profile == profile_manager.DEFAULT_PROFILE_ID or not clean_profile:
        set_autonomous_setting(KEY_AUTONOMOUS_REJECTED_NARRATIVE_STRUCTURE, structure, db_path=db_path)


# ---------------------------------------------------------------------------
# 2. Telemetria e Status
# ---------------------------------------------------------------------------

def get_autonomous_ready_stock(
    task_base_dir: Optional[str] = None,
    db_path: Optional[str] = None,
    profile_id: Optional[str] = None,
    channel_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Calcula o estoque pronto elegível para o loop autônomo (YouTube-first, fail-closed em Safety e Quality).

    Garante que:
    - Tarefa em TASK_STATE_COMPLETE com vídeo físico existente em disco.
    - Safety PASS explícito.
    - Quality assessment existente com quality_score >= 70 e quality_label em ('GOOD', 'STRONG').
    - Ausência de Quality assessment é fail-closed (não conta no estoque autônomo).
    - Tarefa ainda não publicada no YouTube.
    - Aprovação e destinos persistidos; perfil ativo e canal YouTube habilitado.
    - MemoryState vazio não elimina aprovações recuperáveis.
    - Readiness de TikTok NÃO infle o estoque utilizado pelo loop YouTube.
    - Isolamento estrito por perfil e canal se especificados.
    """
    scheduler.init_db(db_path)
    quality_score.init_quality_db(db_path)
    with scheduler.get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT task_id FROM monetization_safety WHERE safety_status = 'PASS' "
            "ORDER BY checked_at, task_id"
        ).fetchall()
        excluded = {r["task_id"] for r in conn.execute(
            "SELECT task_id FROM publication_events WHERE platform='youtube' AND status='success' "
            "UNION SELECT task_id FROM scheduled_posts WHERE platform='youtube' "
            "AND status IN ('published', 'cancelled')"
        )}
    eligible = []
    clean_profile = str(profile_id or "").strip()
    clean_channel = str(channel_id or "").strip()
    for row in rows:
        if row["task_id"] in excluded:
            continue
        try:
            t = _recover_waiting_task(row["task_id"], db_path, task_base_dir)
            if clean_profile and t.get("profile_id") != clean_profile:
                continue
            if clean_channel and t.get("channel_id") != clean_channel:
                continue
            eligible.append(t)
        except (ValueError, TypeError, OSError):
            continue
    target = get_target_ready_stock(profile_id=clean_profile, db_path=db_path)
    return {"ready_count": len(eligible), "youtube_count": len(eligible),
            "tiktok_count": 0, "target_stock": target,
            "is_below_target": len(eligible) < target, "youtube_ready": eligible}


def get_autonomous_status(
    db_path: Optional[str] = None,
    profile_id: Optional[str] = None,
    channel_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Retorna snapshot completo da telemetria de produção autônoma para UI e diagnósticos."""
    scheduler.init_db(db_path)
    target_profile = profile_id or profile_manager.get_active_profile_id(db_path=db_path)
    target_channel = channel_id or resolve_autonomous_youtube_channel(target_profile, db_path=db_path)

    enabled = is_profile_autonomous_mode_enabled(target_profile, db_path=db_path)
    state = _get_cycle_setting(KEY_AUTONOMOUS_STATE, STATE_DISABLED if not enabled else STATE_IDLE, profile_id=target_profile, db_path=db_path)
    if not enabled and state != STATE_BLOCKED:
        state = STATE_DISABLED
    default_msg = "Aguardando próximo ciclo" if enabled else f"Produção autônoma desativada para perfil '{target_profile}'."
    message = _get_cycle_setting(KEY_AUTONOMOUS_MESSAGE, default_msg, profile_id=target_profile, db_path=db_path)
    last_result = _get_cycle_setting(KEY_AUTONOMOUS_LAST_RESULT, "Nenhum ciclo executado ainda", profile_id=target_profile, db_path=db_path)
    last_tick = _get_cycle_setting(KEY_AUTONOMOUS_LAST_TICK, None, profile_id=target_profile, db_path=db_path)
    last_error = _get_cycle_setting(KEY_AUTONOMOUS_LAST_ERROR, None, profile_id=target_profile, db_path=db_path)
    current_task_id = _get_cycle_setting(KEY_AUTONOMOUS_CURRENT_TASK_ID, None, profile_id=target_profile, db_path=db_path)
    waiting_task_id = _get_cycle_setting(KEY_AUTONOMOUS_WAITING_TASK_ID, None, profile_id=target_profile, db_path=db_path)

    # Scoping de current_task_id e waiting_task_id para o perfil alvo
    if current_task_id:
        task_prof = profile_manager.get_task_profile_id(current_task_id, db_path=db_path)
        if not task_prof:
            from app.services import state as sm
            t_obj = sm.state.get_task(current_task_id) or {}
            task_prof = t_obj.get("profile_id")
        is_default_target = not target_profile or target_profile in (profile_manager.DEFAULT_PROFILE_ID, "default")
        if is_default_target:
            if task_prof and task_prof not in (profile_manager.DEFAULT_PROFILE_ID, "default"):
                current_task_id = None
        else:
            if task_prof and task_prof != target_profile:
                current_task_id = None

    if waiting_task_id:
        task_prof = profile_manager.get_task_profile_id(waiting_task_id, db_path=db_path)
        if not task_prof:
            from app.services import state as sm
            t_obj = sm.state.get_task(waiting_task_id) or {}
            task_prof = t_obj.get("profile_id")
        is_default_target = not target_profile or target_profile in (profile_manager.DEFAULT_PROFILE_ID, "default")
        if is_default_target:
            if task_prof and task_prof not in (profile_manager.DEFAULT_PROFILE_ID, "default"):
                waiting_task_id = None
        else:
            if task_prof and task_prof != target_profile:
                waiting_task_id = None

    # Contagem de gerações nas últimas 24h
    generated_today = count_generations_in_last_24h(db_path=db_path, profile_id=target_profile)
    attempts_today = count_generation_attempts_in_last_24h(db_path=db_path, profile_id=target_profile)
    max_24h = get_max_generations_24h(profile_id=target_profile, db_path=db_path)
    max_att = get_max_attempts_24h(profile_id=target_profile, db_path=db_path)
    consecutive_rejections = get_consecutive_rejections(db_path=db_path, profile_id=target_profile)

    # Estoque atual e meta (estritamente elegível para YouTube e para o perfil selecionado)
    stock_info = get_autonomous_ready_stock(db_path=db_path, profile_id=target_profile, channel_id=target_channel)
    target_stock = stock_info["target_stock"]
    ready_count = stock_info["ready_count"]

    # Global Cost Guard snapshot
    global_approved = count_all_profiles_generations_24h(db_path=db_path)
    global_max_gen = get_global_max_generations_24h(db_path=db_path)
    global_attempts = count_all_profiles_attempts_24h(db_path=db_path)
    global_max_att = get_global_max_attempts_24h(db_path=db_path)

    # Próximo ciclo previsto
    interval_min = get_cycle_interval_minutes(db_path=db_path)
    next_cycle_iso = None
    if last_tick:
        try:
            last_dt = scheduler._from_iso(last_tick)
            next_dt = last_dt + timedelta(minutes=interval_min)
            next_cycle_iso = scheduler._to_iso(next_dt)
        except Exception:
            pass

    return {
        "autonomous_mode_enabled": enabled,
        "state": state,
        "message": message,
        "last_result": last_result,
        "last_tick": last_tick,
        "next_cycle_at": next_cycle_iso,
        "last_error": last_error,
        "current_task_id": current_task_id,
        "waiting_task_id": waiting_task_id,
        "ready_stock_total": ready_count,
        "target_ready_stock": target_stock,
        "youtube_ready_count": stock_info["youtube_count"],
        "is_below_target": stock_info["is_below_target"],
        "generated_today_24h": generated_today,
        "max_generations_24h": max_24h,
        "generation_attempts_24h": attempts_today,
        "max_attempts_24h": max_att,
        "global_approved_24h": global_approved,
        "global_max_generations_24h": global_max_gen,
        "global_attempts_24h": global_attempts,
        "global_max_attempts_24h": global_max_att,
        "consecutive_rejections": consecutive_rejections,
        "max_tasks_per_cycle": get_max_tasks_per_cycle(db_path=db_path),
        "cycle_interval_minutes": interval_min,
        "profile_id": target_profile,
        "channel_id": target_channel,
    }


def count_generations_in_last_24h(now: Optional[datetime] = None, db_path: Optional[str] = None, profile_id: Optional[str] = None) -> int:
    """Conta quantas gerações APROVADAS foram concluídas pelo autonomous loop nas últimas 24 horas.

    Separa tentativas/rejeições de vídeos aprovados/prontos para assegurar que
    rejeições não impeçam a fábrica de repor o estoque até a meta.
    Mantém isolamento por perfil e canal sem quebrar compatibilidade com eventos legados.
    """
    scheduler.init_db(db_path)
    try:
        operator_console.init_operator_db(db_path)
    except Exception:
        pass
    now_utc = scheduler._normalize_utc(now)
    since_iso = scheduler._to_iso(now_utc - timedelta(hours=24))

    clean_profile = str(profile_id or "").strip()
    is_default = (not clean_profile) or (clean_profile == profile_manager.DEFAULT_PROFILE_ID) or (clean_profile == "default")

    try:
        with scheduler.get_connection(db_path) as conn:
            if not clean_profile:
                row = conn.execute(
                    """
                    SELECT count(DISTINCT COALESCE(NULLIF(o.task_id, ''), CAST(o.id AS TEXT)))
                    FROM operational_events o
                    WHERE o.component = 'autonomous_production'
                      AND o.event_type IN ('generation_approved', 'task_approved_and_scheduled', 'task_waiting_schedule')
                      AND o.timestamp >= ?;
                    """,
                    (since_iso,),
                ).fetchone()
            elif is_default:
                row = conn.execute(
                    """
                    SELECT count(DISTINCT COALESCE(NULLIF(o.task_id, ''), CAST(o.id AS TEXT)))
                    FROM operational_events o
                    LEFT JOIN task_profiles tp ON tp.task_id = o.task_id
                    WHERE o.component = 'autonomous_production'
                      AND o.event_type IN ('generation_approved', 'task_approved_and_scheduled', 'task_waiting_schedule')
                      AND (tp.profile_id = ? OR tp.profile_id IS NULL OR tp.profile_id = 'default')
                      AND o.timestamp >= ?;
                    """,
                    (profile_manager.DEFAULT_PROFILE_ID, since_iso),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT count(DISTINCT COALESCE(NULLIF(o.task_id, ''), CAST(o.id AS TEXT)))
                    FROM operational_events o
                    JOIN task_profiles tp ON tp.task_id = o.task_id
                    WHERE o.component = 'autonomous_production'
                      AND o.event_type IN ('generation_approved', 'task_approved_and_scheduled', 'task_waiting_schedule')
                      AND tp.profile_id = ?
                      AND o.timestamp >= ?;
                    """,
                    (clean_profile, since_iso),
                ).fetchone()
            return int(row[0]) if (row and row[0] is not None) else 0
    except Exception as exc:
        logger.warning(f"[AUTONOMOUS_PRODUCTION] Erro ao contar gerações aprovadas 24h: {exc}")
        return 0


def count_generation_attempts_in_last_24h(now: Optional[datetime] = None, db_path: Optional[str] = None, profile_id: Optional[str] = None) -> int:
    """Conta quantas tentativas de geração foram iniciadas pelo autonomous loop nas últimas 24 horas."""
    scheduler.init_db(db_path)
    try:
        operator_console.init_operator_db(db_path)
    except Exception:
        pass
    now_utc = scheduler._normalize_utc(now)
    since_iso = scheduler._to_iso(now_utc - timedelta(hours=24))

    clean_profile = str(profile_id or "").strip()
    is_default = (not clean_profile) or (clean_profile == profile_manager.DEFAULT_PROFILE_ID) or (clean_profile == "default")

    try:
        with scheduler.get_connection(db_path) as conn:
            if not clean_profile:
                row = conn.execute(
                    """
                    SELECT count(DISTINCT COALESCE(NULLIF(o.task_id, ''), CAST(o.id AS TEXT)))
                    FROM operational_events o
                    WHERE o.component = 'autonomous_production'
                      AND o.event_type = 'generation_started'
                      AND o.timestamp >= ?;
                    """,
                    (since_iso,),
                ).fetchone()
            elif is_default:
                row = conn.execute(
                    """
                    SELECT count(DISTINCT COALESCE(NULLIF(o.task_id, ''), CAST(o.id AS TEXT)))
                    FROM operational_events o
                    LEFT JOIN task_profiles tp ON tp.task_id = o.task_id
                    WHERE o.component = 'autonomous_production'
                      AND o.event_type = 'generation_started'
                      AND (tp.profile_id = ? OR tp.profile_id IS NULL OR tp.profile_id = 'default')
                      AND o.timestamp >= ?;
                    """,
                    (profile_manager.DEFAULT_PROFILE_ID, since_iso),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT count(DISTINCT COALESCE(NULLIF(o.task_id, ''), CAST(o.id AS TEXT)))
                    FROM operational_events o
                    JOIN task_profiles tp ON tp.task_id = o.task_id
                    WHERE o.component = 'autonomous_production'
                      AND o.event_type = 'generation_started'
                      AND tp.profile_id = ?
                      AND o.timestamp >= ?;
                    """,
                    (clean_profile, since_iso),
                ).fetchone()
            return int(row[0]) if (row and row[0] is not None) else 0
    except Exception as exc:
        logger.warning(f"[AUTONOMOUS_PRODUCTION] Erro ao contar tentativas 24h: {exc}")
        return 0


def count_all_profiles_generations_24h(now: Optional[datetime] = None, db_path: Optional[str] = None) -> int:
    """Conta de forma explícita e agregada quantas gerações APROVADAS foram concluídas
    por TODOS os perfis combinados nas últimas 24 horas."""
    scheduler.init_db(db_path)
    try:
        operator_console.init_operator_db(db_path)
    except Exception:
        pass
    now_utc = scheduler._normalize_utc(now)
    since_iso = scheduler._to_iso(now_utc - timedelta(hours=24))
    try:
        with scheduler.get_connection(db_path) as conn:
            row = conn.execute(
                """
                SELECT count(DISTINCT COALESCE(NULLIF(o.task_id, ''), CAST(o.id AS TEXT)))
                FROM operational_events o
                WHERE o.component = 'autonomous_production'
                  AND o.event_type IN ('generation_approved', 'task_approved_and_scheduled', 'task_waiting_schedule')
                  AND o.timestamp >= ?;
                """,
                (since_iso,),
            ).fetchone()
            return int(row[0]) if (row and row[0] is not None) else 0
    except Exception as exc:
        logger.warning(f"[AUTONOMOUS_PRODUCTION] Erro ao contar gerações globais 24h: {exc}")
        return 0


def count_all_profiles_attempts_24h(now: Optional[datetime] = None, db_path: Optional[str] = None) -> int:
    """Conta de forma explícita e agregada quantas tentativas de geração foram iniciadas
    por TODOS os perfis combinados nas últimas 24 horas."""
    scheduler.init_db(db_path)
    try:
        operator_console.init_operator_db(db_path)
    except Exception:
        pass
    now_utc = scheduler._normalize_utc(now)
    since_iso = scheduler._to_iso(now_utc - timedelta(hours=24))
    try:
        with scheduler.get_connection(db_path) as conn:
            row = conn.execute(
                """
                SELECT count(DISTINCT COALESCE(NULLIF(o.task_id, ''), CAST(o.id AS TEXT)))
                FROM operational_events o
                WHERE o.component = 'autonomous_production'
                  AND o.event_type = 'generation_started'
                  AND o.timestamp >= ?;
                """,
                (since_iso,),
            ).fetchone()
            return int(row[0]) if (row and row[0] is not None) else 0
    except Exception as exc:
        logger.warning(f"[AUTONOMOUS_PRODUCTION] Erro ao contar tentativas globais 24h: {exc}")
        return 0


def get_global_cost_guard_status(now: Optional[datetime] = None, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Retorna o estado agregado do Global Cost Guard somando todos os perfis."""
    global_approved = count_all_profiles_generations_24h(now=now, db_path=db_path)
    global_max_gen = get_global_max_generations_24h(db_path=db_path)
    global_attempts = count_all_profiles_attempts_24h(now=now, db_path=db_path)
    global_max_att = get_global_max_attempts_24h(db_path=db_path)
    is_blocked = (global_attempts >= global_max_att) or (global_approved >= global_max_gen)
    return {
        "global_approved_24h": global_approved,
        "global_max_generations_24h": global_max_gen,
        "global_attempts_24h": global_attempts,
        "global_max_attempts_24h": global_max_att,
        "is_limit_reached": is_blocked,
    }


def check_asset_eligibility_for_destination(
    task_data: Dict[str, Any],
    platform: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Avalia a elegibilidade de um asset aprovado para um destino específico.

    Conceito arquitetural multi-destino (V12-F.5):
    Prepara a distribuição de 1 asset aprovado para múltiplos destinos (ex: YouTube e futuramente TikTok)
    sem necessidade de re-renderização, validando critérios como:
    - aspect ratio (ex: 9:16 vertical para Shorts / TikTok)
    - duração (ex: <= 60s para Shorts / TikTok)
    - áudio / legendas
    - políticas da plataforma

    Nesta fase (V12-F.5):
    - YouTube é o único destino efetivamente habilitado.
    - TikTok permanece estritamente OFF (eligible=False, enabled=False).
    """
    clean_plat = str(platform or "").lower().strip()
    if clean_plat == "youtube":
        return {
            "platform": "youtube",
            "eligible": True,
            "enabled": True,
            "reasons": [],
        }
    elif clean_plat == "tiktok":
        return {
            "platform": "tiktok",
            "eligible": False,
            "enabled": False,
            "reasons": ["tiktok_disabled_in_v12_f5"],
        }
    return {
        "platform": clean_plat,
        "eligible": False,
        "enabled": False,
        "reasons": [f"unsupported_platform_{clean_plat}"],
    }


# ---------------------------------------------------------------------------
# 3. Deduplicação e Seleção de Temas
# ---------------------------------------------------------------------------

def collect_existing_topics(db_path: Optional[str] = None) -> List[str]:
    """Coleta tópicos recentes de tarefas, agendamentos e publicações para anti-duplicação."""
    from app.services import state as sm
    existing_topics: List[str] = []
    seen = set()

    def _add(text: Optional[str]):
        if not text:
            return
        cleaned = text.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            existing_topics.append(cleaned)

    # 1. Tarefas em memória/estado recente
    try:
        tasks, _ = sm.state.get_all_tasks(1, 100)
        for t in tasks:
            _add(t.get("video_subject") or t.get("topic"))
    except Exception:
        pass

    # 2. monetization_safety (histórico recente)
    try:
        with scheduler.get_connection(db_path) as conn:
            rows = conn.execute(
                "SELECT topic FROM monetization_safety ORDER BY checked_at DESC LIMIT 50;"
            ).fetchall()
            for r in rows:
                _add(r["topic"])
    except Exception:
        pass

    # 3. content_quality_scores
    try:
        with scheduler.get_connection(db_path) as conn:
            rows = conn.execute(
                "SELECT topic FROM content_quality_scores ORDER BY created_at DESC LIMIT 50;"
            ).fetchall()
            for r in rows:
                _add(r["topic"])
    except Exception:
        pass

    # 4. scheduled_posts / trends marcadas como USED
    try:
        with scheduler.get_connection(db_path) as conn:
            rows = conn.execute(
                "SELECT title FROM trend_items WHERE status = 'USED' ORDER BY id DESC LIMIT 50;"
            ).fetchall()
            for r in rows:
                _add(r["title"])
    except Exception:
        pass

    return existing_topics


def is_topic_duplicate(candidate_topic: str, existing_topics: List[str], threshold: float = 0.65) -> bool:
    """Verifica se um tópico é idêntico ou semanticamente/lexicamente similar a tópicos existentes."""
    if not candidate_topic or not candidate_topic.strip():
        return True

    norm_cand = trend_radar.normalize_topic(candidate_topic)
    if not norm_cand:
        return True

    for exist in existing_topics:
        norm_exist = trend_radar.normalize_topic(exist)
        if not norm_exist:
            continue
        # Igualdade exata após normalização
        if norm_cand == norm_exist:
            return True
        # Similaridade leve via Trend Radar
        if trend_radar.are_topics_similar(norm_cand, norm_exist):
            return True
        # Similaridade léxica / overlap via Safety Gate
        sim = safety_gate.text_similarity(norm_cand, norm_exist)
        if sim >= threshold:
            return True

    return False


def discover_candidate_topic(
    niche: str,
    language: str = "pt-BR",
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Obtém o melhor candidato a novo tema a partir do Trend Radar ou Content Strategy.

    Remove temas repetidos ou duplicados antes de retornar.
    """
    existing_topics = collect_existing_topics(db_path=db_path)

    # 1. Tenta candidatos pré-aprovados no Trend Radar
    try:
        approved_trends = trend_radar.get_trend_items(status="APPROVED", niche=niche, limit=15, db_path=db_path)
        for t in approved_trends:
            title = t.get("title") or t.get("topic")
            if not is_topic_duplicate(title, existing_topics):
                return {
                    "topic": title,
                    "trend_id": t.get("trend_id"),
                    "source": t.get("source", "trend_radar"),
                    "trend_data": t,
                    "origin": "trend_radar_approved",
                }
    except Exception as exc:
        logger.warning(f"[AUTONOMOUS_PRODUCTION] Erro ao consultar trends aprovadas: {exc}")

    # 2. Tenta candidatos existentes no Trend Radar
    try:
        fresh_trends = trend_radar.get_trend_items(niche=niche, limit=20, db_path=db_path)
        for t in fresh_trends:
            title = t.get("title") or t.get("topic")
            if not is_topic_duplicate(title, existing_topics):
                return {
                    "topic": title,
                    "trend_id": t.get("trend_id"),
                    "source": t.get("source", "trend_radar_fresh"),
                    "trend_data": t,
                    "origin": "trend_radar_fresh",
                }
    except Exception as exc:
        logger.warning(f"[AUTONOMOUS_PRODUCTION] Erro ao consultar fresh trends: {exc}")

    # 3. Fallback: Autopilot Idea Generator
    try:
        from app.services import autopilot
        ideas = autopilot.generate_ideas(niche=niche, count=10, language=language)
        for idea in ideas:
            if not is_topic_duplicate(idea, existing_topics):
                return {
                    "topic": idea,
                    "trend_id": None,
                    "source": "autopilot_llm",
                    "trend_data": None,
                    "origin": "autopilot_ideas",
                }
    except Exception as exc:
        logger.warning(f"[AUTONOMOUS_PRODUCTION] Erro ao gerar ideias via autopilot: {exc}")

    return None


# ---------------------------------------------------------------------------
# 4. Revisão de Qualidade e Segurança (Quality & Safety Gates)
# ---------------------------------------------------------------------------

def evaluate_completed_task_gates(task_id: str, db_path: Optional[str] = None) -> Tuple[bool, str, Dict[str, Any]]:
    """Avalia uma tarefa recém-concluída através dos Gates de Quality Score e Safety Gate.

    Retorna: (is_approved, reason, metrics)
    Regras estritas (FAIL-CLOSED):
    - Quality Score >= 70 (apenas GOOD e STRONG; REVIEW e WEAK são retidos/rejeitados).
    - Safety Status == PASS explícito (rejeita BLOCK, REVIEW, ausente ou desconhecido).
    - Arquivo de vídeo final deve existir fisicamente em disco.
    - NUNCA infere PASS na ausência de registro.
    """
    from app.services import state as sm

    task_data = sm.state.get_task(task_id) or {}
    topic = task_data.get("video_subject") or task_data.get("topic") or task_id
    niche = task_data.get("niche")
    profile_id = task_data.get("profile_id")

    # 1. Verifica integridade do vídeo em disco
    video_path = scheduler.get_task_final_video(task_id)
    if not video_path or not os.path.isfile(video_path) or os.path.getsize(video_path) == 0:
        return False, "Arquivo de vídeo final inexistente ou vazio em disco", {}

    # 2. Consulta Safety Gate (estritamente FAIL-CLOSED)
    try:
        safety_rec = safety_gate.get_safety_assessment(task_id, db_path=db_path)
    except Exception as exc:
        return False, f"Falha ao consultar Safety Gate (fail-closed): {exc}", {"safety_status": "ERROR"}

    safety_status = (safety_rec.get("safety_status") if safety_rec else None) or task_data.get("safety_status")
    safety_reasons = (safety_rec.get("safety_reasons") if safety_rec else None) or task_data.get("safety_reasons") or []

    if not safety_rec and not task_data.get("safety_status"):
        return False, "Safety Gate assessment ausente para a tarefa (fail-closed)", {"safety_status": "MISSING"}

    if not safety_status:
        return False, "Safety status ausente na avaliação (fail-closed)", {"safety_status": "MISSING"}

    clean_status = str(safety_status).upper().strip()
    if clean_status == const.SAFETY_STATUS_BLOCK:
        return False, f"Safety Gate REPROVADO (BLOCK): {'; '.join(safety_reasons)}", {"safety_status": clean_status}

    if clean_status == const.SAFETY_STATUS_REVIEW:
        return False, f"Safety Gate RETIDO para revisão manual (REVIEW): {'; '.join(safety_reasons)}", {"safety_status": clean_status}

    if clean_status != const.SAFETY_STATUS_PASS:
        return False, f"Safety Gate status desconhecido/não aprovado ({clean_status})", {"safety_status": clean_status}

    # 3. Avalia Quality Score (Fase V12-E.1: MIN_QUALITY_SCORE_FOR_AUTONOMOUS = 70.0)
    q_eval = quality_score.evaluate_quality(
        topic=topic,
        niche=niche,
        task_id=task_id,
        persist=True,
        db_path=db_path,
    )
    q_score = q_eval.get("quality_score", 0.0)
    q_label = q_eval.get("quality_label", "WEAK")

    if q_score < MIN_QUALITY_SCORE_FOR_AUTONOMOUS or q_label in (quality_score.LABEL_WEAK, quality_score.LABEL_REVIEW):
        return False, f"Quality Score insuficiente para produção autônoma ({q_score:.1f} - {q_label} < {MIN_QUALITY_SCORE_FOR_AUTONOMOUS})", {
            "quality_score": q_score,
            "quality_label": q_label,
            "safety_status": clean_status,
        }

    # Garante persistência na tabela content_quality_scores caso evaluate_quality
    # tenha sido interceptada por mock ou não tenha persistido.
    try:
        quality_score.init_quality_db(db_path)
        with scheduler.get_connection(db_path) as conn:
            existing = conn.execute(
                "SELECT id FROM content_quality_scores WHERE task_id = ? LIMIT 1;", (task_id,)
            ).fetchone()
            if not existing:
                created_iso = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    """
                    INSERT INTO content_quality_scores (
                        task_id, topic, quality_score, quality_label, created_at
                    ) VALUES (?, ?, ?, ?, ?);
                    """,
                    (task_id, str(topic or task_id), q_score, q_label, created_iso),
                )
    except Exception as p_exc:
        logger.warning(f"[AUTONOMOUS_PRODUCTION] Erro ao assegurar persistência de quality score: {p_exc}")

    # 4. Avalia Copyright Provenance Gate (Fase V14-B: fail-closed)
    from app.services import copyright_gate
    cp_approved, cp_reason, cp_metrics = copyright_gate.evaluate_copyright_provenance_gate(
        task_id=task_id,
        task_base_dir=None,
        db_path=db_path,
    )
    if not cp_approved:
        return False, f"Copyright Provenance Gate REPROVADO: {cp_reason}", {
            "quality_score": q_score,
            "quality_label": q_label,
            "safety_status": clean_status,
            "copyright_provenance_gate": "FAIL",
            "copyright_reason": cp_reason,
        }

    return True, "Aprovado nos Gates de Qualidade, Segurança e Copyright", {
        "quality_score": q_score,
        "quality_label": q_label,
        "safety_status": clean_status,
        "video_path": video_path,
        "copyright_provenance_gate": "PASS",
    }



def build_autonomous_video_params(
    topic: str,
    profile_id: Optional[str] = None,
    narrative_structure: Optional[str] = None,
    db_path: Optional[str] = None,
) -> VideoParams:
    """Constrói VideoParams canônico para produção autônoma herdando configurações reais persistidas.

    Precedência estrita:
    1. Perfil específico (quando o campo fizer parte do perfil)
    2. Configuração persistida da aplicação/WebUI (config.app e config.ui)
    3. Defaults seguros do schema (VideoParams)
    """
    from app.config import config
    from app.services import voice

    # 1. Obter contexto do perfil
    assigned_profile_id = profile_id or profile_manager.get_active_profile_id(db_path=db_path)
    ctx = profile_manager.get_generation_profile_context(profile_id=assigned_profile_id, db_path=db_path)

    # Identidade / Metadados operacionais
    niche = ctx.get("niche") or config.app.get("default_niche") or "curiosidades"
    language = ctx.get("language") or config.app.get("video_language") or "pt-BR"
    region = ctx.get("region") or config.app.get("default_region") or "BR"
    preset = ctx.get("default_preset") or const.DEFAULT_MONETIZATION_PRESET

    # 2. Fonte de Vídeo (video_source)
    # Precedência: Profile -> config.app["video_source"] -> "pexels"
    raw_source = ctx.get("video_source") or config.app.get("video_source", "pexels")
    video_source = str(raw_source or "pexels").lower().strip()

    if video_source not in ALLOWED_AUTONOMOUS_VIDEO_SOURCES:
        raise AutonomousConfigError(
            f"Fonte requer confirmação de custo e não é permitida em modo autônomo: '{video_source}'"
        )

    # 3. Voz (voice_mode & voice_name)
    saved_voice_mode = ctx.get("voice_mode") or config.ui.get("voice_mode")
    saved_tts_server = config.ui.get("tts_server", "azure-tts-v1")

    if saved_voice_mode not in {"tts", "upload", "none"}:
        if saved_tts_server == voice.NO_VOICE_NAME:
            saved_voice_mode = "none"
        else:
            saved_voice_mode = "tts"

    if saved_voice_mode == "upload":
        raise AutonomousConfigError(
            "Modo de voz 'upload' requer áudio manual e não é permitido em modo autônomo"
        )
    elif saved_voice_mode == "none":
        resolved_voice_name = voice.NO_VOICE_NAME
    else:  # "tts"
        resolved_voice_name = ctx.get("voice_name") or config.ui.get("voice_name", "")
        resolved_voice_name = str(resolved_voice_name or "").strip()
        if not resolved_voice_name:
            raise AutonomousConfigError(
                "voice_name vazio quando TTS ativo na configuração persistida"
            )

    try:
        voice_volume = float(config.ui.get("voice_volume", 1.0))
    except (ValueError, TypeError):
        voice_volume = 1.0

    try:
        voice_rate = float(config.ui.get("voice_rate", 1.0))
    except (ValueError, TypeError):
        voice_rate = 1.0

    # 4. Aspect Ratio & Fit Mode
    default_aspect = VideoAspect.landscape.value if video_source == "coverr" else VideoAspect.portrait.value
    aspect_str = config.ui.get(f"video_aspect_{video_source}") or config.ui.get("video_aspect") or default_aspect
    try:
        video_aspect = VideoAspect(aspect_str)
    except (ValueError, TypeError):
        video_aspect = VideoAspect(default_aspect)

    fit_mode_str = config.ui.get("video_fit_mode", VideoFitMode.cover.value)
    try:
        video_fit_mode = VideoFitMode(fit_mode_str)
    except (ValueError, TypeError):
        video_fit_mode = VideoFitMode.cover

    # 5. Concat Mode & Script Order Match
    match_materials_to_script = bool(config.app.get("match_materials_to_script", False))
    if match_materials_to_script:
        video_concat_mode = VideoConcatMode.sequential
    else:
        concat_str = config.ui.get("video_concat_mode", VideoConcatMode.random.value)
        try:
            video_concat_mode = VideoConcatMode(concat_str)
        except (ValueError, TypeError):
            video_concat_mode = VideoConcatMode.random

    # 6. Transição
    trans_str = config.ui.get("video_transition_mode", None)
    if trans_str:
        try:
            video_transition_mode = VideoTransitionMode(trans_str)
        except (ValueError, TypeError):
            video_transition_mode = None
    else:
        video_transition_mode = None

    # 7. Duração do clipe e contagem de vídeos
    try:
        video_clip_duration = max(1, int(config.ui.get("video_clip_duration", 5)))
    except (ValueError, TypeError):
        video_clip_duration = 5

    try:
        video_count = max(1, int(config.ui.get("video_count", 1)))
    except (ValueError, TypeError):
        video_count = 1

    # 8. Legendas
    subtitle_enabled = bool(config.ui.get("subtitle_enabled", True))
    font_name = str(config.ui.get("font_name", "MicrosoftYaHeiBold.ttc") or "MicrosoftYaHeiBold.ttc")
    subtitle_position = str(config.ui.get("subtitle_position", "bottom"))
    subtitle_display_mode = _get_valid_ui_choice("subtitle_display_mode", _SUBTITLE_DISPLAY_MODES, "sentence")
    subtitle_animation = _get_valid_ui_choice("subtitle_animation", _SUBTITLE_ANIMATIONS, "none")
    try:
        custom_position = float(config.ui.get("custom_position", 70.0))
    except (ValueError, TypeError):
        custom_position = 70.0

    text_fore_color = str(config.ui.get("text_fore_color", "#FFFFFF"))
    try:
        font_size = int(config.ui.get("font_size", 60))
    except (ValueError, TypeError):
        font_size = 60

    stroke_color = str(config.ui.get("stroke_color", "#000000"))
    try:
        stroke_width = float(config.ui.get("stroke_width", 1.5))
    except (ValueError, TypeError):
        stroke_width = 1.5

    subtitle_bg_enabled = bool(config.ui.get("subtitle_background_enabled", False))
    subtitle_bg_color = str(config.ui.get("subtitle_background_color", "#000000"))
    text_background_color = subtitle_bg_color if subtitle_bg_enabled else False
    rounded_subtitle_background = bool(config.ui.get("rounded_subtitle_background", False))

    # 9. Trilha Sonora (BGM) - Fail-closed para modo autônomo (V14-B)
    from app.services import bgm as bgm_service
    auto_bgm = bgm_service.resolve_autonomous_bgm(config.ui)
    bgm_type = auto_bgm["type"]
    bgm_file = auto_bgm["file"]
    bgm_volume = auto_bgm["volume"]

    return VideoParams(
        video_subject=topic,
        video_language=language,
        niche=niche,
        region=region,
        monetization_preset=preset,
        narrative_structure=narrative_structure,
        profile_id=assigned_profile_id,
        video_source=video_source,
        voice_name=resolved_voice_name,
        voice_volume=voice_volume,
        voice_rate=voice_rate,
        video_aspect=video_aspect,
        video_fit_mode=video_fit_mode,
        video_concat_mode=video_concat_mode,
        video_transition_mode=video_transition_mode,
        match_materials_to_script=match_materials_to_script,
        video_clip_duration=video_clip_duration,
        video_count=video_count,
        subtitle_enabled=subtitle_enabled,
        font_name=font_name,
        subtitle_position=subtitle_position,
        subtitle_display_mode=subtitle_display_mode,
        subtitle_animation=subtitle_animation,
        custom_position=custom_position,
        text_fore_color=text_fore_color,
        font_size=font_size,
        stroke_color=stroke_color,
        stroke_width=stroke_width,
        text_background_color=text_background_color,
        rounded_subtitle_background=rounded_subtitle_background,
        bgm_type=bgm_type,
        bgm_file=bgm_file,
        bgm_volume=bgm_volume,
    )


def check_required_providers_preflight(
    video_source: Optional[str] = None,
    voice_name: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Validação passiva e estática (sem chamadas pagas) de provedores requeridos."""
    from app.config import config
    from app.models.llm_provider import get_llm_provider, DEFAULT_LLM_PROVIDER_ID
    from app.services import voice

    # Se não especificado explicitamente, herda os parâmetros configurados canônicos
    if video_source is None:
        video_source = config.app.get("video_source", "pexels")

    if voice_name is None:
        mode = config.ui.get("voice_mode")
        if mode == "none":
            voice_name = voice.NO_VOICE_NAME
        else:
            voice_name = config.ui.get("voice_name", "")

    details: Dict[str, Any] = {}

    # 1. FFmpeg
    health_summary = operator_console.get_provider_health_summary(db_path=db_path)
    ffmpeg_st = health_summary.get("FFmpeg", {}).get("status")
    if ffmpeg_st == operator_console.PROVIDER_UNAVAILABLE or not utils.check_ffmpeg_ready():
        return False, "FFmpeg não encontrado no PATH ou não executável", {"FFmpeg": "UNAVAILABLE"}
    details["FFmpeg"] = "HEALTHY"

    # 2. Armazenamento (>= 2GB livres)
    try:
        task_dir_path = utils.task_dir()
        _, _, free_bytes = shutil.disk_usage(task_dir_path)
        free_gb = free_bytes / (1024 ** 3)
        if free_gb < MIN_REQUIRED_DISK_FREE_GB:
            return False, f"Armazenamento insuficiente ({free_gb:.2f} GB livres < mínimo {MIN_REQUIRED_DISK_FREE_GB} GB)", {"Storage": "LOW"}
        details["Storage"] = f"{free_gb:.2f}GB"
    except Exception as exc:
        logger.warning(f"[AUTONOMOUS_PRODUCTION] Falha ao verificar disco: {exc}")

    # 3. LLM Configurado
    llm_prov_id = config.app.get("llm_provider", DEFAULT_LLM_PROVIDER_ID)
    prov_spec = get_llm_provider(llm_prov_id)
    if prov_spec and prov_spec.requires_api_key:
        api_key = config.app.get(prov_spec.config_key("api_key"), "") or os.environ.get(prov_spec.config_key("api_key").upper(), "")
        if not api_key:
            if llm_prov_id == "gemini":
                api_key = config.app.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY")
            elif llm_prov_id == "openai":
                api_key = config.app.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return False, f"Provedor de LLM configurado ('{llm_prov_id}') não possui API Key configurada", {"LLM": "UNAVAILABLE"}
    details["LLM"] = "HEALTHY"

    # 4. Provedor de TTS Selecionado
    if voice.is_no_voice(voice_name):
        details["TTS"] = "None (No Voiceover)"
    elif not voice_name or not voice_name.strip():
        return False, "voice_name vazio quando TTS ativo na configuração persistida", {"TTS": "MISSING"}
    else:
        clean_voice = voice_name.lower().strip()
        if "azure" in clean_voice:
            azure_key = config.azure.get("speech_key") or os.environ.get("AZURE_SPEECH_KEY")
            if not azure_key:
                return False, "Provedor Azure TTS selecionado mas speech_key ausente", {"TTS": "UNAVAILABLE"}
            details["TTS"] = "Azure"
        elif "elevenlabs" in clean_voice:
            el_key = config.elevenlabs.get("api_key") or os.environ.get("ELEVENLABS_API_KEY")
            if not el_key:
                return False, "Provedor ElevenLabs selecionado mas api_key ausente", {"TTS": "UNAVAILABLE"}
            details["TTS"] = "ElevenLabs"
        elif "siliconflow" in clean_voice:
            sf_key = config.siliconflow.get("api_key") or os.environ.get("SILICONFLOW_API_KEY")
            if not sf_key:
                return False, "Provedor SiliconFlow TTS selecionado mas api_key ausente", {"TTS": "UNAVAILABLE"}
            details["TTS"] = "SiliconFlow"
        elif "gemini" in clean_voice:
            gemini_key = config.app.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY")
            if not gemini_key:
                return False, "Provedor Gemini TTS selecionado mas gemini_api_key ausente", {"TTS": "UNAVAILABLE"}
            details["TTS"] = "Gemini"
        else:
            try:
                import edge_tts
                details["TTS"] = "Edge TTS"
            except Exception as exc:
                return False, f"Provedor de TTS (Edge TTS) indisponível: {exc}", {"TTS": "UNAVAILABLE"}

    # 5. Fonte de Mídia Selecionada (contratos canônicos: pexels_api_keys, pixabay_api_keys, coverr_api_keys)
    source_clean = (video_source or "pexels").lower().strip()
    if source_clean not in ALLOWED_AUTONOMOUS_VIDEO_SOURCES:
        return False, f"Fonte requer confirmação de custo e não é permitida em modo autônomo: '{source_clean}'", {"Media": "UNAUTHORIZED_SOURCE"}

    from app.services import material
    if source_clean == "pexels":
        if not material.has_material_api_keys("pexels"):
            return False, "Fonte de mídia 'pexels' selecionada mas pexels_api_keys não está configurada", {"Media": "UNAVAILABLE"}
        details["Media"] = "Pexels"
    elif source_clean == "pixabay":
        if not material.has_material_api_keys("pixabay"):
            return False, "Fonte de mídia 'pixabay' selecionada mas pixabay_api_keys não está configurada", {"Media": "UNAVAILABLE"}
        details["Media"] = "Pixabay"
    elif source_clean == "coverr":
        if not material.has_material_api_keys("coverr"):
            return False, "Fonte de mídia 'coverr' selecionada mas coverr_api_keys não está configurada", {"Media": "UNAVAILABLE"}
        details["Media"] = "Coverr"

    return True, "Todos os provedores necessários estão disponíveis", details


# ---------------------------------------------------------------------------
# 5. Ciclo Principal do Orquestrador
# ---------------------------------------------------------------------------

def _recover_waiting_task(task_id: str, db_path: Optional[str] = None,
                          task_base_dir: Optional[str] = None) -> Dict[str, Any]:
    """Revalidate persisted approval before retrying the existing scheduler."""
    from app.services import state as sm

    task = dict(sm.state.get_task(task_id) or {})
    if task.get("state") in (const.TASK_STATE_FAILED, const.TASK_STATE_CANCELLED) or task.get("cancelled"):
        raise ValueError("waiting_task_not_complete")

    video = scheduler.get_task_final_video(task_id, task_base_dir=task_base_dir)
    if not video or not os.path.isfile(video) or os.path.getsize(video) <= 0:
        raise ValueError("waiting_final_video_missing")

    if task.get("state") in (const.TASK_STATE_PROCESSING, const.TASK_STATE_PENDING):
        try:
            from app.services import webui_task
            if webui_task.has_active_generation_tasks() and task_id in webui_task.get_active_task_ids():
                raise ValueError("waiting_task_not_complete")
        except Exception:
            pass

    safety = safety_gate.get_safety_assessment(task_id, db_path=db_path) or {}
    if safety.get("safety_status") != const.SAFETY_STATUS_PASS:
        raise ValueError("waiting_safety_not_pass")
    with scheduler.get_connection(db_path) as conn:
        quality = conn.execute(
            "SELECT quality_score, quality_label FROM content_quality_scores "
            "WHERE task_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        profile = conn.execute(
            "SELECT profile_id FROM task_profiles WHERE task_id = ?", (task_id,),
        ).fetchone()
    score = float(quality["quality_score"]) if quality else float("nan")
    if (not math.isfinite(score) or score < MIN_QUALITY_SCORE_FOR_AUTONOMOUS
            or quality["quality_label"] not in ("GOOD", "STRONG")):
        raise ValueError("waiting_quality_not_approved")
    if "youtube" not in scheduler.get_task_platforms(task_id, db_path=db_path):
        raise ValueError("waiting_youtube_destination_missing")
    prof = profile_manager.get_profile(profile["profile_id"], db_path=db_path) if profile else None
    if not prof or not prof.get("is_active"):
        raise ValueError("waiting_profile_unavailable")
    resolved_channel = profile_manager.resolve_task_channels(task_id, platforms=["youtube"], db_path=db_path)
    if not resolved_channel:
        raise ValueError("waiting_youtube_channel_unavailable")
    chan_id = resolved_channel[0].get("channel_id") or resolved_channel[0].get("id")
    prof_id = profile["profile_id"] if profile else profile_manager.DEFAULT_PROFILE_ID
    task.update(task_id=task_id, state=const.TASK_STATE_COMPLETE, video_file=video,
                safety_status=const.SAFETY_STATUS_PASS, planned_platforms=["youtube"],
                profile_id=prof_id, quality_score=score,
                quality_label=quality["quality_label"],
                channel_id=chan_id)
    return task


def run_autonomous_cycle(
    force: bool = False,
    one_shot: bool = False,
    now: Optional[datetime] = None,
    db_path: Optional[str] = None,
    profile_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    task_base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Serialize worker/manual cycles inside the PRIMARY process."""
    if not _cycle_lock.acquire(blocking=False):
        return {"status": "busy", "reason": "cycle_in_progress"}
    try:
        return _run_autonomous_cycle(
            force=force,
            one_shot=one_shot,
            now=now,
            db_path=db_path,
            profile_id=profile_id,
            channel_id=channel_id,
            task_base_dir=task_base_dir,
        )
    finally:
        _cycle_lock.release()


def _run_autonomous_cycle(
    force: bool = False,
    one_shot: bool = False,
    now: Optional[datetime] = None,
    db_path: Optional[str] = None,
    profile_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    task_base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Executa um ciclo determinístico e idempotente do loop de produção autônoma.

    Responsabilidades:
    1. Exige nó PRIMARY e fábrica RUNNING.
    2. Verifica autonomous_mode_enabled (ou one_shot=True para execução supervisionada).
    3. Monitora/revisa a geração atual antes de escolher uma nova ação.
    4. Recupera aprovações persistidas e tenta agendar uma task se houver slot.
    5. Avalia espaço em disco e saúde passiva dos provedores críticos requeridos.
    6. Verifica teto de gerações em 24h.
    7. Calcula estoque pronto elegível estritamente para YouTube.
    8. Se estoque suficiente -> entra em IDLE.
    9. Se estoque insuficiente -> seleciona tópico sem duplicação e cria nova tarefa no pipeline existente.
    10. Marca trend como USED apenas após sucesso de submissão da task.
    11. Tarefas aprovadas são adotadas no Scheduler exclusivamente para YouTube.
    12. Registra operational_events e atualiza telemetria isolada por perfil.
    """
    scheduler.init_db(db_path)
    current_time = scheduler._normalize_utc(now)
    now_iso = scheduler._to_iso(current_time)

    target_profile_id = profile_id or profile_manager.get_active_profile_id(db_path=db_path)
    target_channel_id = channel_id or resolve_autonomous_youtube_channel(target_profile_id, db_path=db_path)

    def _set_status(key: str, val: Any) -> None:
        _set_cycle_setting(key, val, profile_id=target_profile_id, db_path=db_path)

    def _get_status(key: str, default: Any = None) -> Any:
        return _get_cycle_setting(key, default, profile_id=target_profile_id, db_path=db_path)

    # -----------------------------------------------------------------------
    # Guarda 1: PRIMARY Lock
    # -----------------------------------------------------------------------
    try:
        operator_console.require_primary_instance(db_path=db_path)
    except PermissionError as p_err:
        _set_status(KEY_AUTONOMOUS_STATE, STATE_BLOCKED)
        _set_status(KEY_AUTONOMOUS_MESSAGE, "Instância em modo SECONDARY_VIEW_ONLY. Produção autônoma bloqueada.")
        return {
            "status": "blocked",
            "reason": "secondary_view_only",
            "message": str(p_err),
        }

    # -----------------------------------------------------------------------
    # Guarda 2: Factory State RUNNING
    # -----------------------------------------------------------------------
    if operator_console.is_factory_paused(db_path=db_path):
        _set_status(KEY_AUTONOMOUS_STATE, STATE_BLOCKED)
        _set_status(KEY_AUTONOMOUS_MESSAGE, "Fábrica PAUSADA. Novas produções e agendamentos bloqueados.")
        return {
            "status": "blocked",
            "reason": "factory_paused",
            "message": "Fábrica pausada pelo operador",
        }

    # -----------------------------------------------------------------------
    # Guarda 3: Autonomous Mode Enabled ou One-Shot Supervisionado
    # -----------------------------------------------------------------------
    if not is_profile_autonomous_mode_enabled(target_profile_id, db_path=db_path) and not one_shot:
        msg = f"Produção autônoma desativada para perfil '{target_profile_id}'."
        _set_status(KEY_AUTONOMOUS_STATE, STATE_DISABLED)
        _set_status(KEY_AUTONOMOUS_MESSAGE, msg)
        return {
            "status": "disabled",
            "profile_id": target_profile_id,
            "message": f"autonomous_mode_enabled is False for profile '{target_profile_id}'",
        }

    # -----------------------------------------------------------------------
    # Etapa A2: Tratar Geração Anterior / Revisão de Tarefas Concluídas
    # -----------------------------------------------------------------------
    current_task_id = _get_status(KEY_AUTONOMOUS_CURRENT_TASK_ID, None)
    if current_task_id:
        task_prof = profile_manager.get_task_profile_id(current_task_id, db_path=db_path)
        is_default_target = not target_profile_id or target_profile_id in (profile_manager.DEFAULT_PROFILE_ID, "default")
        is_default_task = not task_prof or task_prof in (profile_manager.DEFAULT_PROFILE_ID, "default")
        if (is_default_target and not is_default_task) or (not is_default_target and task_prof != target_profile_id):
            current_task_id = None

    # Se há tarefas ativas gerando no task manager
    if webui_task.has_active_generation_tasks():
        _set_status(KEY_AUTONOMOUS_STATE, STATE_GENERATING)
        active_ids = webui_task.get_active_task_ids()
        msg = f"Geração em andamento (tarefas ativas: {', '.join(active_ids[:3])})"
        _set_status(KEY_AUTONOMOUS_MESSAGE, msg)
        return {
            "status": "busy",
            "state": STATE_GENERATING,
            "message": msg,
        }

    if current_task_id:
        from app.services import state as sm
        task_data = sm.state.get_task(current_task_id) or {}
        video_path = scheduler.get_task_final_video(current_task_id, task_base_dir=task_base_dir)

        # Se não há vídeo final e nenhuma thread ativa está rodando, houve crash/reboot
        if not video_path or not os.path.isfile(video_path):
            task_state = task_data.get("state")
            if task_state in (const.TASK_STATE_PROCESSING, const.TASK_STATE_PENDING):
                interrupted_task_id = current_task_id
                _set_status(KEY_AUTONOMOUS_CURRENT_TASK_ID, "")
                _set_status(KEY_AUTONOMOUS_STATE, STATE_ERROR)
                msg = f"Geração da tarefa {current_task_id} interrompida (reboot/crash). Vídeo final ausente."
                _set_status(KEY_AUTONOMOUS_LAST_ERROR, msg)
                _set_status(KEY_AUTONOMOUS_MESSAGE, msg)
                operator_console.log_operational_event(
                    component="autonomous_production",
                    severity=operator_console.SEVERITY_WARNING,
                    event_type="generation_interrupted_recovery",
                    task_id=current_task_id,
                    message=msg,
                    db_path=db_path,
                )
                # UMA TRANSIÇÃO POR CICLO: recovery encerra o ciclo aqui.
                # O próximo ciclo poderá gerar reposição se o estoque estiver abaixo da meta.
                return {
                    "status": "recovery_error",
                    "task_id": interrupted_task_id,
                    "reason": "generation_interrupted",
                    "message": msg,
                }

    if current_task_id:
        _set_status(KEY_AUTONOMOUS_STATE, STATE_REVIEWING)
        _set_status(KEY_AUTONOMOUS_MESSAGE, f"Avaliando Gates para tarefa {current_task_id}...")

        approved, reason, metrics = evaluate_completed_task_gates(current_task_id, db_path=db_path)
        _set_status(KEY_AUTONOMOUS_CURRENT_TASK_ID, "")

        if approved:
            # Reseta contador de rejeições consecutivas e limpa tracking de rejeição narrativa isolada
            _set_cycle_setting(KEY_AUTONOMOUS_CONSECUTIVE_REJECTIONS, "0", profile_id=target_profile_id, db_path=db_path)
            _set_cycle_setting(KEY_AUTONOMOUS_REJECTED_NARRATIVE_STRUCTURE, "", profile_id=target_profile_id, db_path=db_path)

            operator_console.log_operational_event(
                component="autonomous_production",
                severity=operator_console.SEVERITY_INFO,
                event_type="generation_approved",
                task_id=current_task_id,
                message=f"Tarefa {current_task_id} aprovada nos Gates de Qualidade e Segurança.",
                metadata=metrics,
                db_path=db_path,
            )

            _set_status(KEY_AUTONOMOUS_STATE, STATE_SCHEDULING)
            # YouTube Primeiro: Apenas YouTube habilitado
            scheduler.adopt_tasks_into_scheduler([current_task_id], ["youtube"], db_path=db_path)

            from app.services import state as sm
            task_data = dict(sm.state.get_task(current_task_id) or {})
            task_data["task_id"] = current_task_id
            if not task_data.get("video_file") and video_path:
                task_data["video_file"] = video_path
            task_data["state"] = const.TASK_STATE_COMPLETE
            if "youtube" not in (task_data.get("planned_platforms") or []):
                task_data["planned_platforms"] = ["youtube"]
            task_data["profile_id"] = target_profile_id
            if target_channel_id:
                task_data["channel_id"] = target_channel_id

            scheduled_items = scheduler.plan_schedule(
                tasks=[task_data], now=current_time, db_path=db_path, task_base_dir=task_base_dir
            )

            if scheduled_items:
                operator_console.log_operational_event(
                    component="autonomous_production",
                    severity=operator_console.SEVERITY_INFO,
                    event_type="task_approved_and_scheduled",
                    task_id=current_task_id,
                    message=f"Tarefa {current_task_id} aprovada nos Gates e agendada para YouTube.",
                    metadata=metrics,
                    db_path=db_path,
                )
                summary = f"Tarefa {current_task_id} aprovada (Score {metrics.get('quality_score', 0):.1f}) e agendada."
                _set_status(KEY_AUTONOMOUS_LAST_RESULT, summary)
                _set_status(KEY_AUTONOMOUS_STATE, STATE_IDLE)
                _set_status(KEY_AUTONOMOUS_MESSAGE, summary)
                _set_status(KEY_AUTONOMOUS_LAST_TICK, now_iso)
                return {
                    "status": "scheduled",
                    "task_id": current_task_id,
                    "scheduled_items": len(scheduled_items),
                    "metrics": metrics,
                }
            else:
                # Aprovado mas sem slot imediato no Growth Mode -> waiting_schedule
                _set_status(KEY_AUTONOMOUS_WAITING_TASK_ID, current_task_id)
                _set_status(KEY_AUTONOMOUS_STATE, STATE_WAITING_SCHEDULE)
                msg = f"Tarefa {current_task_id} aprovada (Score {metrics.get('quality_score', 0):.1f}) aguardando slot de agendamento no Growth Mode."
                _set_status(KEY_AUTONOMOUS_MESSAGE, msg)
                _set_status(KEY_AUTONOMOUS_LAST_RESULT, msg)
                operator_console.log_operational_event(
                    component="autonomous_production",
                    severity=operator_console.SEVERITY_INFO,
                    event_type="task_waiting_schedule",
                    task_id=current_task_id,
                    message=msg,
                    metadata=metrics,
                    db_path=db_path,
                )
                return {
                    "status": "waiting_schedule",
                    "task_id": current_task_id,
                    "scheduled_items": 0,
                    "metrics": metrics,
                }
        else:
            rejected_task_id = current_task_id
            consec = get_consecutive_rejections(db_path=db_path, profile_id=target_profile_id) + 1
            _set_cycle_setting(KEY_AUTONOMOUS_CONSECUTIVE_REJECTIONS, str(consec), profile_id=target_profile_id, db_path=db_path)

            try:
                from app.services import state as sm
                sm.state.patch_task(rejected_task_id, gate_status="rejected", gate_reason=reason)
            except Exception:
                pass

            from app.services import state as sm
            rej_task = sm.state.get_task(rejected_task_id) or {}
            rej_struct = rej_task.get("narrative_structure") or metrics.get("narrative_structure")
            is_narrative_repetition = any(
                term in str(reason).lower()
                for term in ["repetição", "repetida", "mesma estrutura", "estrutura narrativa", "narrative_fit"]
            )
            if is_narrative_repetition and rej_struct:
                rej_profile_id = rej_task.get("profile_id") or profile_manager.get_task_profile_id(rejected_task_id, db_path=db_path)
                rej_channel_id = resolve_autonomous_youtube_channel(rej_profile_id, db_path=db_path)
                set_channel_rejected_narrative_structure(rej_profile_id, rej_channel_id, str(rej_struct), db_path=db_path)

            operator_console.log_operational_event(
                component="autonomous_production",
                severity=operator_console.SEVERITY_WARNING,
                event_type="task_gate_rejected",
                task_id=current_task_id,
                message=f"Tarefa {current_task_id} retida/reprovada nos Gates: {reason}",
                metadata=metrics,
                db_path=db_path,
            )
            rejection_summary = f"Tarefa {current_task_id} retida: {reason}"
            _set_status(KEY_AUTONOMOUS_LAST_RESULT, rejection_summary)
            _set_status(KEY_AUTONOMOUS_STATE, STATE_IDLE)
            _set_status(KEY_AUTONOMOUS_MESSAGE, rejection_summary)
            _set_status(KEY_AUTONOMOUS_LAST_TICK, now_iso)
            # UMA TRANSIÇÃO POR CICLO: rejeição encerra o ciclo aqui.
            # O próximo ciclo poderá gerar reposição se o estoque estiver abaixo da meta.
            return {
                "status": "rejected",
                "task_id": rejected_task_id,
                "reason": reason,
                "metrics": metrics,
                "message": rejection_summary,
            }

    # Select exactly one action. A blocked publication destination is not a
    # generation lock; all persisted approvals remain discoverable after restart.
    waiting_task_id = _get_status(KEY_AUTONOMOUS_WAITING_TASK_ID, None)
    if waiting_task_id:
        wait_prof = profile_manager.get_task_profile_id(waiting_task_id, db_path=db_path)
        is_default_target = not target_profile_id or target_profile_id in (profile_manager.DEFAULT_PROFILE_ID, "default")
        is_default_wait = not wait_prof or wait_prof in (profile_manager.DEFAULT_PROFILE_ID, "default")
        if (is_default_target and not is_default_wait) or (not is_default_target and wait_prof != target_profile_id):
            waiting_task_id = None

    if waiting_task_id:
        try:
            _recover_waiting_task(waiting_task_id, db_path=db_path, task_base_dir=task_base_dir)
        except (ValueError, TypeError, OSError) as exc:
            _set_status(KEY_AUTONOMOUS_WAITING_TASK_ID, "")
            _set_status(KEY_AUTONOMOUS_STATE, STATE_WAITING_SCHEDULE)
            _set_status(KEY_AUTONOMOUS_MESSAGE, str(exc))
            return {"status": "waiting_schedule", "task_id": waiting_task_id,
                    "reason": "waiting_recovery_failed", "message": str(exc), "scheduled_items": 0}

    stock_info = get_autonomous_ready_stock(task_base_dir=task_base_dir, db_path=db_path, profile_id=target_profile_id, channel_id=target_channel_id)
    pending = []
    for task_data in stock_info.get("youtube_ready", []):
        channels = profile_manager.resolve_task_channels(
            task_data["task_id"], platforms=["youtube"], db_path=db_path)
        with scheduler.get_connection(db_path) as conn:
            unscheduled = any(not scheduler.has_existing_or_terminal_destination(
                task_data["task_id"], "youtube", c["channel_id"], conn
            ) for c in channels)
            queued = conn.execute(
                "SELECT 1 FROM scheduled_posts WHERE task_id=? AND platform='youtube' "
                "AND status IN ('planned', 'ready', 'processing') LIMIT 1", (task_data["task_id"],)
            ).fetchone()
        if unscheduled and not queued:
            pending.append(task_data)
    # This pointer is scoped per profile for display and recovery
    _set_status(KEY_AUTONOMOUS_WAITING_TASK_ID, pending[0]["task_id"] if pending else "")
    for task_data in pending:
        t_prof = task_data.get("profile_id") or target_profile_id
        t_chan = task_data.get("channel_id") or target_channel_id
        rate = scheduler.get_platform_rate_limits(
            "youtube", now=current_time, profile_id=t_prof, channel_id=t_chan, db_path=db_path)
        if not rate["enabled"] or rate["available_slots"] <= 0:
            scheduler.log_growth_limit_block(
                task_data["task_id"], t_prof, "youtube", rate,
                now=current_time, db_path=db_path)
            continue
        retry_key = "autonomous_schedule_retry:" + task_data["task_id"]
        retry_at = get_autonomous_setting(retry_key, None, db_path=db_path)
        if retry_at:
            try:
                if current_time < scheduler._from_iso(retry_at):
                    continue
            except (ValueError, TypeError):
                pass  # Malformed retry metadata must not block the whole buffer.
        set_autonomous_setting(retry_key, scheduler._to_iso(current_time + timedelta(minutes=15)), db_path=db_path)
        scheduled = scheduler.plan_schedule(tasks=[task_data], now=current_time, db_path=db_path, task_base_dir=task_base_dir)
        status = "scheduled" if scheduled else "waiting_schedule"
        _set_status(KEY_AUTONOMOUS_STATE, STATE_IDLE if scheduled else STATE_WAITING_SCHEDULE)
        message = f"Task {task_data['task_id']}: {status} ({len(scheduled)} scheduled items)."
        _set_status(KEY_AUTONOMOUS_MESSAGE, message)
        _set_status(KEY_AUTONOMOUS_LAST_RESULT, message)
        if scheduled:
            set_autonomous_setting(retry_key, "", db_path=db_path)
            _set_status(KEY_AUTONOMOUS_WAITING_TASK_ID, "")
            operator_console.log_operational_event(
                component="autonomous_production", severity=operator_console.SEVERITY_INFO,
                event_type="task_approved_and_scheduled", task_id=task_data["task_id"],
                message="Persisted approval scheduled for YouTube.",
                metadata={"scheduled_items": len(scheduled)}, db_path=db_path)
        return {"status": status, "task_id": task_data["task_id"],
                "scheduled_items": len(scheduled), "message": message}

    ready_total = stock_info["ready_count"]
    target_stock = stock_info["target_stock"]

    if ready_total >= target_stock:
        _set_status(KEY_AUTONOMOUS_STATE, STATE_IDLE)
        msg = f"Estoque pronto suficiente ({ready_total}/{target_stock}). Nenhuma nova geração necessária."
        _set_status(KEY_AUTONOMOUS_MESSAGE, msg)
        _set_status(KEY_AUTONOMOUS_LAST_RESULT, msg)
        return {
            "status": "idle",
            "ready_stock": ready_total,
            "target_stock": target_stock,
            "message": msg,
        }

    # -----------------------------------------------------------------------
    # Guarda 4: Cooldown Timer (a menos que force=True ou one_shot=True)
    # -----------------------------------------------------------------------
    last_tick_iso = _get_status(KEY_AUTONOMOUS_LAST_TICK, None)
    interval_min = get_cycle_interval_minutes(db_path=db_path)
    if not force and not one_shot and last_tick_iso:
        try:
            last_dt = scheduler._from_iso(last_tick_iso)
            diff_min = (current_time - last_dt).total_seconds() / 60.0
            if diff_min < interval_min:
                rem_min = int(interval_min - diff_min)
                _set_status(KEY_AUTONOMOUS_STATE, STATE_COOLDOWN)
                msg = f"Em cooldown. Próximo ciclo em aprox. {rem_min} min."
                _set_status(KEY_AUTONOMOUS_MESSAGE, msg)
                return {
                    "status": "cooldown",
                    "remaining_minutes": rem_min,
                    "message": msg,
                }
        except Exception:
            pass

    _set_status(KEY_AUTONOMOUS_LAST_TICK, now_iso)

    # -----------------------------------------------------------------------
    # Guarda 5: Limite Diário de Gerações Aprovadas e Proteção contra Loop de Custo
    # -----------------------------------------------------------------------
    # 5.1 Proteção contra loop infinito de falhas consecutivas (Circuit Breaker)
    consecutive_rejections = get_consecutive_rejections(db_path=db_path, profile_id=target_profile_id)
    if consecutive_rejections >= DEFAULT_AUTONOMOUS_MAX_CONSECUTIVE_REJECTIONS:
        _set_status(KEY_AUTONOMOUS_STATE, STATE_BLOCKED)
        msg = (
            f"Proteção de custo ativada: {consecutive_rejections} rejeições consecutivas nos Gates. "
            f"Produção pausada para evitar loop/gasto descontrolado."
        )
        _set_status(KEY_AUTONOMOUS_MESSAGE, msg)
        return {"status": "blocked", "reason": "consecutive_rejections_limit", "message": msg}

    # 5.2 Teto de tentativas totais em 24h do perfil (para evitar consumo excessivo de API)
    max_attempts_24h = get_max_attempts_24h(profile_id=target_profile_id, db_path=db_path)
    attempts_today = count_generation_attempts_in_last_24h(now=current_time, db_path=db_path, profile_id=target_profile_id)
    if attempts_today >= max_attempts_24h:
        _set_status(KEY_AUTONOMOUS_STATE, STATE_BLOCKED)
        msg = f"Teto diário de tentativas atingido para perfil '{target_profile_id}' ({attempts_today}/{max_attempts_24h} em 24h). Aguardando liberação da janela."
        _set_status(KEY_AUTONOMOUS_MESSAGE, msg)
        return {"status": "blocked", "reason": "daily_attempt_limit_reached", "message": msg, "profile_id": target_profile_id}

    # 5.3 Limite diário de gerações APROVADAS do perfil (máximo de vídeos prontos por 24h)
    max_24h = get_max_generations_24h(profile_id=target_profile_id, db_path=db_path)
    gen_today = count_generations_in_last_24h(now=current_time, db_path=db_path, profile_id=target_profile_id)
    if gen_today >= max_24h:
        _set_status(KEY_AUTONOMOUS_STATE, STATE_BLOCKED)
        msg = f"Limite diário de gerações aprovadas atingido para perfil '{target_profile_id}' ({gen_today}/{max_24h} em 24h). Aguardando liberação da janela."
        _set_status(KEY_AUTONOMOUS_MESSAGE, msg)
        return {"status": "blocked", "reason": "daily_limit_reached", "message": msg, "profile_id": target_profile_id}

    # 5.4 Global Cost Guard (Teto Agregado de Todos os Perfis)
    global_max_att = get_global_max_attempts_24h(db_path=db_path)
    global_att = count_all_profiles_attempts_24h(now=current_time, db_path=db_path)
    if global_att >= global_max_att:
        _set_status(KEY_AUTONOMOUS_STATE, STATE_BLOCKED)
        msg = f"Global Cost Guard: teto global de tentativas atingido ({global_att}/{global_max_att} em 24h). Nenhuma nova geração iniciada."
        _set_status(KEY_AUTONOMOUS_MESSAGE, msg)
        return {"status": "blocked", "reason": "global_attempt_limit_reached", "message": msg, "profile_id": target_profile_id}

    global_max_gen = get_global_max_generations_24h(db_path=db_path)
    global_gen = count_all_profiles_generations_24h(now=current_time, db_path=db_path)
    if global_gen >= global_max_gen:
        _set_status(KEY_AUTONOMOUS_STATE, STATE_BLOCKED)
        msg = f"Global Cost Guard: teto global de gerações aprovadas atingido ({global_gen}/{global_max_gen} em 24h). Nenhuma nova geração iniciada."
        _set_status(KEY_AUTONOMOUS_MESSAGE, msg)
        return {"status": "blocked", "reason": "global_generation_limit_reached", "message": msg, "profile_id": target_profile_id}

    # -----------------------------------------------------------------------
    # Guarda 6: Provedores Críticos Requeridos (FFmpeg, Storage, LLM, TTS, Media)
    # -----------------------------------------------------------------------
    active_profile_id = target_profile_id
    try:
        probe_params = build_autonomous_video_params(
            topic="probe",
            profile_id=target_profile_id,
            db_path=db_path,
        )
    except AutonomousConfigError as cfg_err:
        _set_status(KEY_AUTONOMOUS_STATE, STATE_BLOCKED)
        _set_status(KEY_AUTONOMOUS_MESSAGE, str(cfg_err))
        operator_console.log_operational_event(
            component="autonomous_production",
            severity=operator_console.SEVERITY_ERROR,
            event_type="configuration_contract_block",
            message=str(cfg_err),
            metadata={"error": str(cfg_err)},
            db_path=db_path,
        )
        return {"status": "blocked", "reason": "invalid_configuration", "message": str(cfg_err)}

    prov_ok, prov_msg, prov_details = check_required_providers_preflight(
        video_source=probe_params.video_source,
        voice_name=probe_params.voice_name,
        db_path=db_path,
    )
    if not prov_ok:
        _set_status(KEY_AUTONOMOUS_STATE, STATE_BLOCKED)
        _set_status(KEY_AUTONOMOUS_MESSAGE, prov_msg)
        operator_console.log_operational_event(
            component="autonomous_production",
            severity=operator_console.SEVERITY_ERROR,
            event_type="provider_unavailable_block",
            message=prov_msg,
            metadata=prov_details,
            db_path=db_path,
        )
        return {"status": "blocked", "reason": "provider_unavailable", "message": prov_msg}

    # -----------------------------------------------------------------------
    # Etapa B: Cálculo do Estoque Pronto YouTube vs Meta (get_autonomous_ready_stock)
    # -----------------------------------------------------------------------
    deficit = target_stock - ready_total
    max_per_cycle = get_max_tasks_per_cycle(db_path=db_path)
    tasks_to_create = min(deficit, max_per_cycle, 1)  # Fase V12-E.1: máximo efetivo = 1

    # -----------------------------------------------------------------------
    # Etapa C: Planejamento e Seleção de Temas (Planning)
    # -----------------------------------------------------------------------
    _set_status(KEY_AUTONOMOUS_STATE, STATE_PLANNING)
    _set_status(KEY_AUTONOMOUS_MESSAGE, f"Estoque abaixo da meta ({ready_total}/{target_stock}). Selecionando {tasks_to_create} tema(s)...")

    candidate = discover_candidate_topic(
        niche=probe_params.niche,
        language=probe_params.video_language,
        db_path=db_path,
    )
    if not candidate or not candidate.get("topic"):
        _set_status(KEY_AUTONOMOUS_STATE, STATE_IDLE)
        msg = "Nenhum candidato a tema elegível encontrado sem duplicação."
        _set_status(KEY_AUTONOMOUS_MESSAGE, msg)
        return {"status": "idle", "reason": "no_candidate", "message": msg}

    chosen_topic = candidate["topic"]
    trend_id = candidate.get("trend_id")

    # Resolve canal YouTube com segurança para o perfil alvo
    yt_channel_id = target_channel_id or resolve_autonomous_youtube_channel(target_profile_id, db_path=db_path)

    # Recomenda estrutura narrativa diversificada evitando repetições (isolada por perfil e canal)
    last_struct = get_channel_last_narrative_structure(target_profile_id, yt_channel_id, db_path=db_path)
    rejected_struct = get_channel_rejected_narrative_structure(target_profile_id, yt_channel_id, db_path=db_path)

    rec_struct, _ = content_strategy.recommend_narrative_structure(
        topic=chosen_topic,
        niche=probe_params.niche,
        last_used_structure=rejected_struct or last_struct,
    )
    if rejected_struct and rec_struct == rejected_struct:
        for alt_st in const.NARRATIVE_STRUCTURES:
            if alt_st != rejected_struct:
                rec_struct = alt_st
                break

    set_channel_last_narrative_structure(target_profile_id, yt_channel_id, rec_struct, db_path=db_path)
    if rejected_struct:
        set_channel_rejected_narrative_structure(target_profile_id, yt_channel_id, "", db_path=db_path)

    # -----------------------------------------------------------------------
    # Etapa D: Criação da Task e Submissão ao Pipeline Existente (Generating)
    # -----------------------------------------------------------------------
    new_task_id = str(uuid.uuid4())
    chosen_topic = candidate["topic"]
    trend_id = candidate.get("trend_id")
    baseline_topic = chosen_topic
    baseline_struct = rec_struct

    closed_loop_decision_recorded = False
    closed_loop_meta = None

    try:
        if operator_console.get_closed_feedback_loop_enabled_op(db_path=db_path):
            if yt_channel_id:
                evidence = analytics.get_learning_evidence(
                    platform="youtube",
                    profile_id=target_profile_id,
                    channel_id=yt_channel_id,
                    cutoff_time=current_time,
                    db_path=db_path,
                )
                alt_items = trend_radar.get_trend_items(db_path=db_path) or []
                candidates = []
                for it in alt_items:
                    t = it.get("title") or it.get("topic")
                    if t:
                        candidates.append({
                            "topic": t,
                            "trend_data": {"opportunity_score": it.get("opportunity_score", 50.0)},
                        })

                recent_subs = operator_console.get_closed_loop_submissions(
                    platform="youtube",
                    profile_id=target_profile_id,
                    channel_id=yt_channel_id,
                    db_path=db_path,
                )

                baseline_candidate = {
                    "topic": baseline_topic,
                    "origin": candidate.get("origin", "unknown"),
                    "trend_data": candidate.get("trend_data") or {"opportunity_score": 50.0},
                    "narrative_structure": baseline_struct,
                }

                selection = content_strategy.select_closed_loop_candidate(
                    baseline_candidate=baseline_candidate,
                    candidates=candidates,
                    evidence=evidence,
                    recent_submissions=recent_subs,
                    niche=probe_params.niche,
                )

                if selection.get("adapted"):
                    chosen_topic = selection["selected_candidate"]["topic"]
                    rec_struct = selection["selected_candidate"]["narrative_structure"]
                    for it in alt_items:
                        if (it.get("title") or it.get("topic")) == chosen_topic and it.get("id"):
                            trend_id = it.get("id")
                            break

                cand_ranks = [
                    {
                        "topic": baseline_candidate["topic"],
                        "baseline_rank": float((baseline_candidate.get("trend_data") or {}).get("opportunity_score", 50.0)),
                    }
                ]
                for c in candidates:
                    cand_ranks.append({
                        "topic": c["topic"],
                        "baseline_rank": float((c.get("trend_data") or {}).get("opportunity_score", 50.0)),
                    })

                temp_params = build_autonomous_video_params(
                    topic=chosen_topic,
                    profile_id=target_profile_id,
                    narrative_structure=rec_struct,
                    db_path=db_path,
                )

                audit_metadata = {
                    "platform": "youtube",
                    "profile_id": target_profile_id,
                    "channel_id": yt_channel_id,
                    "task_id": new_task_id,
                    "adapted": bool(selection.get("adapted")),
                    "baseline_topic": baseline_topic,
                    "baseline_structure": baseline_struct,
                    "selected_topic": chosen_topic,
                    "selected_structure": rec_struct,
                    "candidate_ranks": cand_ranks,
                    "evidence": evidence,
                    "snapshot_ids": evidence.get("eligible_snapshot_ids", []),
                    "recent_submissions": recent_subs[:5],
                    "history_bonus": selection.get("history_bonus", 0.0),
                    "reason": selection.get("reason", "baseline"),
                    "policy_version": selection.get("policy_version", analytics.LEARNING_POLICY_VERSION),
                    "applied_video_params": temp_params.model_dump(),
                }

                operator_console.record_closed_loop_decision(
                    new_task_id,
                    audit_metadata,
                    db_path=db_path,
                )
                closed_loop_decision_recorded = True
                closed_loop_meta = {
                    "platform": "youtube",
                    "profile_id": target_profile_id,
                    "channel_id": yt_channel_id,
                    "task_id": new_task_id,
                    "adapted": bool(selection.get("adapted")),
                    "topic_cluster": content_strategy.classify_topic_cluster(chosen_topic),
                    "narrative_structure": rec_struct,
                }
            else:
                logger.info(f"[AUTONOMOUS] Closed feedback loop: channel unresolvable for profile '{target_profile_id}' (using baseline).")
    except Exception as cl_exc:
        logger.warning(f"[AUTONOMOUS] Closed feedback loop fallback to baseline: {cl_exc}")
        chosen_topic = baseline_topic
        rec_struct = baseline_struct
        closed_loop_decision_recorded = False
        closed_loop_meta = None

    set_channel_last_narrative_structure(target_profile_id, yt_channel_id, rec_struct, db_path=db_path)
    params = build_autonomous_video_params(
        topic=chosen_topic,
        profile_id=target_profile_id,
        narrative_structure=rec_struct,
        db_path=db_path,
    )

    # Validação estrita do mesmo conjunto de parâmetros construídos
    final_ok, final_msg, final_details = check_required_providers_preflight(
        video_source=params.video_source,
        voice_name=params.voice_name,
        db_path=db_path,
    )
    if not final_ok:
        _set_status(KEY_AUTONOMOUS_STATE, STATE_BLOCKED)
        _set_status(KEY_AUTONOMOUS_MESSAGE, final_msg)
        operator_console.log_operational_event(
            component="autonomous_production",
            severity=operator_console.SEVERITY_ERROR,
            event_type="provider_unavailable_block",
            message=final_msg,
            metadata=final_details,
            db_path=db_path,
        )
        return {"status": "blocked", "reason": "provider_unavailable", "message": final_msg}

    _set_status(KEY_AUTONOMOUS_CURRENT_TASK_ID, new_task_id)
    _set_status(KEY_AUTONOMOUS_STATE, STATE_GENERATING)
    msg = f"Iniciando geração autônoma: '{chosen_topic}' (task_id={new_task_id})"
    _set_status(KEY_AUTONOMOUS_MESSAGE, msg)

    aspect_val = params.video_aspect.value if hasattr(params.video_aspect, "value") else str(params.video_aspect)
    concat_val = params.video_concat_mode.value if hasattr(params.video_concat_mode, "value") else str(params.video_concat_mode)
    trans_val = params.video_transition_mode.value if hasattr(params.video_transition_mode, "value") else (str(params.video_transition_mode) if params.video_transition_mode else "None")

    param_snapshot = {
        "topic": chosen_topic,
        "niche": params.niche,
        "language": params.video_language,
        "region": params.region,
        "preset": params.monetization_preset,
        "profile_id": params.profile_id,
        "narrative_structure": params.narrative_structure,
        "video_source": params.video_source,
        "voice_name": params.voice_name,
        "voice_volume": params.voice_volume,
        "voice_rate": params.voice_rate,
        "video_aspect": aspect_val,
        "video_concat_mode": concat_val,
        "video_transition_mode": trans_val,
        "match_materials_to_script": params.match_materials_to_script,
        "subtitle_enabled": params.subtitle_enabled,
        "subtitle_position": params.subtitle_position,
        "subtitle_display_mode": params.subtitle_display_mode,
        "subtitle_animation": params.subtitle_animation,
        "font_name": params.font_name,
        "font_size": params.font_size,
        "bgm_type": params.bgm_type,
        "bgm_volume": params.bgm_volume,
        "video_clip_duration": params.video_clip_duration,
        "video_count": params.video_count,
        "origin": candidate.get("origin"),
    }

    operator_console.log_operational_event(
        component="autonomous_production",
        severity=operator_console.SEVERITY_INFO,
        event_type="generation_started",
        task_id=new_task_id,
        message=msg,
        metadata=param_snapshot,
        db_path=db_path,
    )

    try:
        webui_task.submit_generation(
            task_id=new_task_id,
            params=params,
            profile_id=target_profile_id,
            db_path=db_path,
        )
    except Exception as g_exc:
        _set_status(KEY_AUTONOMOUS_CURRENT_TASK_ID, "")
        _set_status(KEY_AUTONOMOUS_STATE, STATE_ERROR)
        err_msg = f"Falha ao submeter geração autônoma: {g_exc}"
        _set_status(KEY_AUTONOMOUS_LAST_ERROR, err_msg)
        _set_status(KEY_AUTONOMOUS_MESSAGE, err_msg)
        operator_console.log_operational_event(
            component="autonomous_production",
            severity=operator_console.SEVERITY_ERROR,
            event_type="generation_submission_failed",
            task_id=new_task_id,
            message=err_msg,
            db_path=db_path,
        )
        return {"status": "error", "message": err_msg}

    # Trend USED SOMENTE APÓS SUCESSO DE SUBMISSÃO
    if trend_id:
        try:
            trend_radar.update_trend_item_status(trend_id, "USED", db_path=db_path)
        except Exception:
            pass

    if closed_loop_decision_recorded and closed_loop_meta:
        try:
            operator_console.log_operational_event(
                component="closed_loop",
                severity=operator_console.SEVERITY_INFO,
                event_type="CLOSED_LOOP_SUBMITTED",
                task_id=new_task_id,
                message="Closed feedback loop task submitted",
                metadata=closed_loop_meta,
                db_path=db_path,
            )
        except Exception as cl_sub_err:
            logger.warning(f"[AUTONOMOUS] Failed to log CLOSED_LOOP_SUBMITTED: {cl_sub_err}")

    res_summary = f"Tarefa {new_task_id} submetida com sucesso ao pipeline ('{chosen_topic}')"
    _set_status(KEY_AUTONOMOUS_LAST_RESULT, res_summary)
    return {
        "status": "generation_started",
        "task_id": new_task_id,
        "topic": chosen_topic,
        "niche": params.niche,
        "message": res_summary,
    }


def run_enabled_profiles_autonomous_cycle(
    now: Optional[datetime] = None,
    db_path: Optional[str] = None,
    task_base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Executa um tick do worker para todos os perfis ativos com autonomous mode ativado.

    Contrato V12-F.5:
    1. ZERO dependência de get_active_profile_id(). O perfil visual do Console não interfere.
    2. Lista perfis ativos de forma determinística (ordenados por profile_id/id).
    3. Para cada perfil:
       - Se autonomous_mode_enabled estiver OFF, ignora com segurança.
       - Resolve o canal do perfil explicitamente.
       - Executa no máximo UMA transição de ciclo para aquele perfil.
    4. Falha em um perfil NÃO interrompe nem afeta o processamento dos demais (try/except isolado).
    5. current_task, waiting_task, state e messages permanecem 100% isolados por perfil.
    """
    scheduler.init_db(db_path)
    profile_manager.init_profile_db(db_path)

    if not operator_console.is_primary_instance(db_path=db_path):
        return {"status": "skipped", "reason": "secondary_view_only"}

    all_profiles = profile_manager.list_profiles(active_only=True, db_path=db_path)
    sorted_profiles = sorted(all_profiles, key=lambda p: str(p.get("id") or ""))

    results: Dict[str, Any] = {}
    for prof in sorted_profiles:
        p_id = str(prof.get("id") or "").strip()
        if not p_id:
            continue

        if not is_profile_autonomous_mode_enabled(p_id, db_path=db_path):
            results[p_id] = {"status": "disabled", "skipped": True}
            continue

        chan_id = resolve_autonomous_youtube_channel(p_id, db_path=db_path)
        try:
            res = run_autonomous_cycle(
                force=False,
                one_shot=False,
                now=now,
                db_path=db_path,
                profile_id=p_id,
                channel_id=chan_id,
                task_base_dir=task_base_dir,
            )
            results[p_id] = res
        except Exception as exc:
            logger.exception(f"[AUTONOMOUS_PRODUCTION] Erro no ciclo do perfil '{p_id}': {exc}")
            results[p_id] = {
                "status": "error",
                "error": str(exc),
                "profile_id": p_id,
            }

    return {"status": "completed", "profiles_processed": len(results), "results": results}
