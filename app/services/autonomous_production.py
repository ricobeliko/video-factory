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
import os
import shutil
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from app.models import const
from app.models.schema import VideoParams
from app.services import (
    content_strategy,
    operator_console,
    profile_manager,
    quality_score,
    safety_gate,
    scheduler,
    trend_radar,
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


def get_target_ready_stock(db_path: Optional[str] = None) -> int:
    """Retorna a meta de estoque pronto, priorizando minimum_ready_stock existente."""
    stored = get_autonomous_setting(KEY_AUTONOMOUS_TARGET_STOCK, None, db_path=db_path)
    if stored is not None:
        try:
            return max(1, int(stored))
        except (ValueError, TypeError):
            pass
    return operator_console.get_minimum_ready_stock(db_path=db_path)


def get_max_tasks_per_cycle(db_path: Optional[str] = None) -> int:
    """Retorna o limite de novas tarefas criadas por ciclo (padrão conservador 1)."""
    val = get_autonomous_setting(KEY_AUTONOMOUS_MAX_TASKS_PER_CYCLE, str(DEFAULT_AUTONOMOUS_MAX_NEW_TASKS_PER_CYCLE), db_path=db_path)
    try:
        return max(1, int(val))
    except (ValueError, TypeError):
        return DEFAULT_AUTONOMOUS_MAX_NEW_TASKS_PER_CYCLE


def get_max_generations_24h(db_path: Optional[str] = None) -> int:
    """Retorna o teto de gerações em 24h para segurança de custos e infra."""
    val = get_autonomous_setting(KEY_AUTONOMOUS_MAX_24H, str(DEFAULT_AUTONOMOUS_MAX_GENERATIONS_24H), db_path=db_path)
    try:
        return max(1, int(val))
    except (ValueError, TypeError):
        return DEFAULT_AUTONOMOUS_MAX_GENERATIONS_24H


def get_cycle_interval_minutes(db_path: Optional[str] = None) -> int:
    """Retorna o intervalo entre ciclos normais em minutos."""
    val = get_autonomous_setting(KEY_AUTONOMOUS_INTERVAL_MINUTES, str(DEFAULT_AUTONOMOUS_CYCLE_INTERVAL_MINUTES), db_path=db_path)
    try:
        return max(1, int(val))
    except (ValueError, TypeError):
        return DEFAULT_AUTONOMOUS_CYCLE_INTERVAL_MINUTES


# ---------------------------------------------------------------------------
# 2. Telemetria e Status
# ---------------------------------------------------------------------------

def get_autonomous_ready_stock(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Calcula o estoque pronto elegível para o loop autônomo (YouTube-first e fail-closed).

    Garante que:
    - Somente vídeos com Safety PASS explícito e arquivo físico existente sejam computados.
    - O estoque represente tarefas elegíveis para YouTube (não publicado no YouTube).
    - Readiness de TikTok NÃO infle o estoque utilizado pelo loop YouTube.
    """
    stock_info = operator_console.get_ready_stock(db_path=db_path)
    youtube_ready = stock_info.get("youtube_ready")
    if youtube_ready is not None:
        youtube_count = len(youtube_ready)
    else:
        youtube_count = stock_info.get("youtube_count", stock_info.get("total_ready", 0))
        youtube_ready = []
    target_stock = get_target_ready_stock(db_path=db_path)

    return {
        "ready_count": youtube_count,
        "youtube_count": youtube_count,
        "tiktok_count": stock_info.get("tiktok_count", 0),
        "target_stock": target_stock,
        "is_below_target": youtube_count < target_stock,
        "youtube_ready": youtube_ready,
    }


def get_autonomous_status(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Retorna snapshot completo da telemetria de produção autônoma para UI e diagnósticos."""
    scheduler.init_db(db_path)
    enabled = is_autonomous_mode_enabled(db_path=db_path)
    state = get_autonomous_setting(KEY_AUTONOMOUS_STATE, STATE_DISABLED if not enabled else STATE_IDLE, db_path=db_path)
    message = get_autonomous_setting(KEY_AUTONOMOUS_MESSAGE, "Aguardando próximo ciclo", db_path=db_path)
    last_result = get_autonomous_setting(KEY_AUTONOMOUS_LAST_RESULT, "Nenhum ciclo executado ainda", db_path=db_path)
    last_tick = get_autonomous_setting(KEY_AUTONOMOUS_LAST_TICK, None, db_path=db_path)
    last_error = get_autonomous_setting(KEY_AUTONOMOUS_LAST_ERROR, None, db_path=db_path)
    current_task_id = get_autonomous_setting(KEY_AUTONOMOUS_CURRENT_TASK_ID, None, db_path=db_path)
    waiting_task_id = get_autonomous_setting(KEY_AUTONOMOUS_WAITING_TASK_ID, None, db_path=db_path)

    # Contagem de gerações nas últimas 24h
    generated_today = count_generations_in_last_24h(db_path=db_path)
    max_24h = get_max_generations_24h(db_path=db_path)

    # Estoque atual e meta (estritamente elegível para YouTube)
    stock_info = get_autonomous_ready_stock(db_path=db_path)
    target_stock = stock_info["target_stock"]
    ready_count = stock_info["ready_count"]

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
        "max_tasks_per_cycle": get_max_tasks_per_cycle(db_path=db_path),
        "cycle_interval_minutes": interval_min,
    }


def count_generations_in_last_24h(now: Optional[datetime] = None, db_path: Optional[str] = None) -> int:
    """Conta quantas gerações foram iniciadas pelo autonomous loop nas últimas 24 horas."""
    scheduler.init_db(db_path)
    now_utc = scheduler._normalize_utc(now)
    since_iso = scheduler._to_iso(now_utc - timedelta(hours=24))

    try:
        with scheduler.get_connection(db_path) as conn:
            row = conn.execute(
                """
                SELECT count(*) FROM operational_events
                WHERE component = 'autonomous_production'
                  AND event_type = 'generation_started'
                  AND timestamp >= ?;
                """,
                (since_iso,),
            ).fetchone()
            return int(row[0]) if row else 0
    except Exception as exc:
        logger.warning(f"[AUTONOMOUS_PRODUCTION] Erro ao contar gerações 24h: {exc}")
        return 0


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

    return True, "Aprovado nos Gates de Qualidade e Segurança", {
        "quality_score": q_score,
        "quality_label": q_label,
        "safety_status": clean_status,
        "video_path": video_path,
    }


def check_required_providers_preflight(
    video_source: str = "pexels",
    voice_name: str = "",
    db_path: Optional[str] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Validação passiva e estática (sem chamadas pagas) de provedores requeridos."""
    from app.config import config
    from app.models.llm_provider import get_llm_provider, DEFAULT_LLM_PROVIDER_ID

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
    clean_voice = (voice_name or "").lower().strip()
    if not clean_voice or "edge" in clean_voice:
        try:
            import edge_tts
            details["TTS"] = "Edge TTS"
        except Exception as exc:
            return False, f"Provedor de TTS (Edge TTS) indisponível: {exc}", {"TTS": "UNAVAILABLE"}
    elif "azure" in clean_voice:
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

    # 5. Fonte de Mídia Selecionada
    source_clean = (video_source or "pexels").lower().strip()
    if source_clean == "pexels":
        pexels_key = config.app.get("pexels_api_key") or os.environ.get("PEXELS_API_KEY")
        if not pexels_key:
            return False, "Fonte de mídia 'pexels' selecionada mas pexels_api_key não está configurada", {"Media": "UNAVAILABLE"}
        details["Media"] = "Pexels"
    elif source_clean == "pixabay":
        pixabay_key = config.app.get("pixabay_api_key") or os.environ.get("PIXABAY_API_KEY")
        if not pixabay_key:
            return False, "Fonte de mídia 'pixabay' selecionada mas pixabay_api_key não está configurada", {"Media": "UNAVAILABLE"}
        details["Media"] = "Pixabay"

    return True, "Todos os provedores necessários estão disponíveis", details


# ---------------------------------------------------------------------------
# 5. Ciclo Principal do Orquestrador
# ---------------------------------------------------------------------------

def run_autonomous_cycle(
    force: bool = False,
    one_shot: bool = False,
    now: Optional[datetime] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Executa um ciclo determinístico e idempotente do loop de produção autônoma.

    Responsabilidades:
    1. Exige nó PRIMARY e fábrica RUNNING.
    2. Verifica autonomous_mode_enabled (ou one_shot=True para execução supervisionada).
    3. Monitora tarefas em waiting_schedule e tenta replanejar agenda quando surgirem slots.
    4. Monitora/revisa tarefas geradas pendentes de Gate (Quality >= 70 e Safety PASS estrito).
    5. Avalia espaço em disco e saúde passiva dos provedores críticos requeridos.
    6. Verifica teto de gerações em 24h.
    7. Calcula estoque pronto elegível estritamente para YouTube.
    8. Se estoque suficiente -> entra em IDLE.
    9. Se estoque insuficiente -> seleciona tópico sem duplicação e cria nova tarefa no pipeline existente.
    10. Marca trend como USED apenas após sucesso de submissão da task.
    11. Tarefas aprovadas são adotadas no Scheduler exclusivamente para YouTube.
    12. Registra operational_events e atualiza telemetria.
    """
    scheduler.init_db(db_path)
    current_time = scheduler._normalize_utc(now)
    now_iso = scheduler._to_iso(current_time)

    # -----------------------------------------------------------------------
    # Guarda 1: PRIMARY Lock
    # -----------------------------------------------------------------------
    try:
        operator_console.require_primary_instance(db_path=db_path)
    except PermissionError as p_err:
        set_autonomous_setting(KEY_AUTONOMOUS_STATE, STATE_BLOCKED, db_path=db_path)
        set_autonomous_setting(KEY_AUTONOMOUS_MESSAGE, "Instância em modo SECONDARY_VIEW_ONLY. Produção autônoma bloqueada.", db_path=db_path)
        return {
            "status": "blocked",
            "reason": "secondary_view_only",
            "message": str(p_err),
        }

    # -----------------------------------------------------------------------
    # Guarda 2: Factory State RUNNING
    # -----------------------------------------------------------------------
    if operator_console.is_factory_paused(db_path=db_path):
        set_autonomous_setting(KEY_AUTONOMOUS_STATE, STATE_BLOCKED, db_path=db_path)
        set_autonomous_setting(KEY_AUTONOMOUS_MESSAGE, "Fábrica PAUSADA. Novas produções e agendamentos bloqueados.", db_path=db_path)
        return {
            "status": "blocked",
            "reason": "factory_paused",
            "message": "Fábrica pausada pelo operador",
        }

    # -----------------------------------------------------------------------
    # Guarda 3: Autonomous Mode Enabled ou One-Shot Supervisionado
    # -----------------------------------------------------------------------
    if not is_autonomous_mode_enabled(db_path=db_path) and not one_shot:
        set_autonomous_setting(KEY_AUTONOMOUS_STATE, STATE_DISABLED, db_path=db_path)
        set_autonomous_setting(KEY_AUTONOMOUS_MESSAGE, "Produção autônoma desativada.", db_path=db_path)
        return {
            "status": "disabled",
            "message": "autonomous_mode_enabled is False",
        }

    # -----------------------------------------------------------------------
    # Etapa A1: Tratar Tarefa Aprovada Aguardando Agenda (waiting_schedule)
    # -----------------------------------------------------------------------
    waiting_task_id = get_autonomous_setting(KEY_AUTONOMOUS_WAITING_TASK_ID, None, db_path=db_path)
    if waiting_task_id:
        from app.services import state as sm
        task_data = sm.state.get_task(waiting_task_id) or {"task_id": waiting_task_id}
        scheduled_items = scheduler.plan_schedule(tasks=[task_data], now=current_time, db_path=db_path)
        if scheduled_items:
            set_autonomous_setting(KEY_AUTONOMOUS_WAITING_TASK_ID, "", db_path=db_path)
            set_autonomous_setting(KEY_AUTONOMOUS_STATE, STATE_IDLE, db_path=db_path)
            msg = f"Tarefa {waiting_task_id} agendada com sucesso após espera de slot."
            set_autonomous_setting(KEY_AUTONOMOUS_LAST_RESULT, msg, db_path=db_path)
            set_autonomous_setting(KEY_AUTONOMOUS_MESSAGE, msg, db_path=db_path)
            operator_console.log_operational_event(
                component="autonomous_production",
                severity=operator_console.SEVERITY_INFO,
                event_type="task_approved_and_scheduled",
                task_id=waiting_task_id,
                message=msg,
                metadata={"scheduled_items": len(scheduled_items)},
                db_path=db_path,
            )
            return {
                "status": "scheduled",
                "task_id": waiting_task_id,
                "scheduled_items": len(scheduled_items),
                "message": msg,
            }
        else:
            set_autonomous_setting(KEY_AUTONOMOUS_STATE, STATE_WAITING_SCHEDULE, db_path=db_path)
            msg = f"Tarefa {waiting_task_id} aprovada aguardando slot de agendamento (Growth Mode / limite 24h)."
            set_autonomous_setting(KEY_AUTONOMOUS_MESSAGE, msg, db_path=db_path)
            return {
                "status": "waiting_schedule",
                "task_id": waiting_task_id,
                "scheduled_items": 0,
                "message": msg,
            }

    # -----------------------------------------------------------------------
    # Etapa A2: Tratar Geração Anterior / Revisão de Tarefas Concluídas
    # -----------------------------------------------------------------------
    current_task_id = get_autonomous_setting(KEY_AUTONOMOUS_CURRENT_TASK_ID, None, db_path=db_path)

    # Se há tarefas ativas gerando no task manager
    if webui_task.has_active_generation_tasks():
        set_autonomous_setting(KEY_AUTONOMOUS_STATE, STATE_GENERATING, db_path=db_path)
        active_ids = webui_task.get_active_task_ids()
        msg = f"Geração em andamento (tarefas ativas: {', '.join(active_ids[:3])})"
        set_autonomous_setting(KEY_AUTONOMOUS_MESSAGE, msg, db_path=db_path)
        return {
            "status": "busy",
            "state": STATE_GENERATING,
            "message": msg,
        }

    if current_task_id:
        from app.services import state as sm
        task_data = sm.state.get_task(current_task_id) or {}
        video_path = scheduler.get_task_final_video(current_task_id)

        # Se não há vídeo final e nenhuma thread ativa está rodando, houve crash/reboot
        if not video_path or not os.path.isfile(video_path):
            task_state = task_data.get("state")
            if task_state in (const.TASK_STATE_PROCESSING, const.TASK_STATE_PENDING):
                set_autonomous_setting(KEY_AUTONOMOUS_CURRENT_TASK_ID, "", db_path=db_path)
                set_autonomous_setting(KEY_AUTONOMOUS_STATE, STATE_ERROR, db_path=db_path)
                msg = f"Geração da tarefa {current_task_id} interrompida (reboot/crash). Vídeo final ausente."
                set_autonomous_setting(KEY_AUTONOMOUS_LAST_ERROR, msg, db_path=db_path)
                set_autonomous_setting(KEY_AUTONOMOUS_MESSAGE, msg, db_path=db_path)
                operator_console.log_operational_event(
                    component="autonomous_production",
                    severity=operator_console.SEVERITY_WARNING,
                    event_type="generation_interrupted_recovery",
                    task_id=current_task_id,
                    message=msg,
                    db_path=db_path,
                )
                current_task_id = None

    if current_task_id:
        set_autonomous_setting(KEY_AUTONOMOUS_STATE, STATE_REVIEWING, db_path=db_path)
        set_autonomous_setting(KEY_AUTONOMOUS_MESSAGE, f"Avaliando Gates para tarefa {current_task_id}...", db_path=db_path)

        approved, reason, metrics = evaluate_completed_task_gates(current_task_id, db_path=db_path)
        set_autonomous_setting(KEY_AUTONOMOUS_CURRENT_TASK_ID, "", db_path=db_path)

        if approved:
            set_autonomous_setting(KEY_AUTONOMOUS_STATE, STATE_SCHEDULING, db_path=db_path)
            # YouTube Primeiro: Apenas YouTube habilitado
            scheduler.adopt_tasks_into_scheduler([current_task_id], ["youtube"], db_path=db_path)

            from app.services import state as sm
            task_data = sm.state.get_task(current_task_id) or {"task_id": current_task_id}
            scheduled_items = scheduler.plan_schedule(tasks=[task_data], now=current_time, db_path=db_path)

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
                set_autonomous_setting(KEY_AUTONOMOUS_LAST_RESULT, summary, db_path=db_path)
                set_autonomous_setting(KEY_AUTONOMOUS_STATE, STATE_IDLE, db_path=db_path)
                set_autonomous_setting(KEY_AUTONOMOUS_MESSAGE, summary, db_path=db_path)
                set_autonomous_setting(KEY_AUTONOMOUS_LAST_TICK, now_iso, db_path=db_path)
                return {
                    "status": "scheduled",
                    "task_id": current_task_id,
                    "scheduled_items": len(scheduled_items),
                    "metrics": metrics,
                }
            else:
                # Aprovado mas sem slot imediato no Growth Mode -> waiting_schedule
                set_autonomous_setting(KEY_AUTONOMOUS_WAITING_TASK_ID, current_task_id, db_path=db_path)
                set_autonomous_setting(KEY_AUTONOMOUS_STATE, STATE_WAITING_SCHEDULE, db_path=db_path)
                msg = f"Tarefa {current_task_id} aprovada (Score {metrics.get('quality_score', 0):.1f}) aguardando slot de agendamento no Growth Mode."
                set_autonomous_setting(KEY_AUTONOMOUS_MESSAGE, msg, db_path=db_path)
                set_autonomous_setting(KEY_AUTONOMOUS_LAST_RESULT, msg, db_path=db_path)
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
            operator_console.log_operational_event(
                component="autonomous_production",
                severity=operator_console.SEVERITY_WARNING,
                event_type="task_gate_rejected",
                task_id=current_task_id,
                message=f"Tarefa {current_task_id} retida/reprovada nos Gates: {reason}",
                metadata=metrics,
                db_path=db_path,
            )
            set_autonomous_setting(KEY_AUTONOMOUS_LAST_RESULT, f"Tarefa {current_task_id} retida: {reason}", db_path=db_path)
            set_autonomous_setting(KEY_AUTONOMOUS_MESSAGE, f"Tarefa retida: {reason}", db_path=db_path)

    # -----------------------------------------------------------------------
    # Guarda 4: Cooldown Timer (a menos que force=True ou one_shot=True)
    # -----------------------------------------------------------------------
    last_tick_iso = get_autonomous_setting(KEY_AUTONOMOUS_LAST_TICK, None, db_path=db_path)
    interval_min = get_cycle_interval_minutes(db_path=db_path)
    if not force and not one_shot and last_tick_iso:
        try:
            last_dt = scheduler._from_iso(last_tick_iso)
            diff_min = (current_time - last_dt).total_seconds() / 60.0
            if diff_min < interval_min:
                rem_min = int(interval_min - diff_min)
                set_autonomous_setting(KEY_AUTONOMOUS_STATE, STATE_COOLDOWN, db_path=db_path)
                msg = f"Em cooldown. Próximo ciclo em aprox. {rem_min} min."
                set_autonomous_setting(KEY_AUTONOMOUS_MESSAGE, msg, db_path=db_path)
                return {
                    "status": "cooldown",
                    "remaining_minutes": rem_min,
                    "message": msg,
                }
        except Exception:
            pass

    set_autonomous_setting(KEY_AUTONOMOUS_LAST_TICK, now_iso, db_path=db_path)

    # -----------------------------------------------------------------------
    # Guarda 5: Limite Diário de Gerações (24h)
    # -----------------------------------------------------------------------
    max_24h = get_max_generations_24h(db_path=db_path)
    gen_today = count_generations_in_last_24h(now=current_time, db_path=db_path)
    if gen_today >= max_24h:
        set_autonomous_setting(KEY_AUTONOMOUS_STATE, STATE_BLOCKED, db_path=db_path)
        msg = f"Limite diário de gerações atingido ({gen_today}/{max_24h} em 24h). Aguardando liberação da janela."
        set_autonomous_setting(KEY_AUTONOMOUS_MESSAGE, msg, db_path=db_path)
        return {"status": "blocked", "reason": "daily_limit_reached", "message": msg}

    # -----------------------------------------------------------------------
    # Guarda 6: Provedores Críticos Requeridos (FFmpeg, Storage, LLM, TTS, Media)
    # -----------------------------------------------------------------------
    active_profile_id = profile_manager.get_active_profile_id(db_path=db_path)
    ctx = profile_manager.get_generation_profile_context(profile_id=active_profile_id, db_path=db_path)
    niche = ctx.get("niche") or "curiosidades"
    language = ctx.get("language") or "pt-BR"
    region = ctx.get("region") or "BR"
    preset = ctx.get("default_preset") or const.DEFAULT_MONETIZATION_PRESET

    prov_ok, prov_msg, prov_details = check_required_providers_preflight(
        video_source="pexels",
        voice_name=ctx.get("voice_name", ""),
        db_path=db_path,
    )
    if not prov_ok:
        set_autonomous_setting(KEY_AUTONOMOUS_STATE, STATE_BLOCKED, db_path=db_path)
        set_autonomous_setting(KEY_AUTONOMOUS_MESSAGE, prov_msg, db_path=db_path)
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
    stock_info = get_autonomous_ready_stock(db_path=db_path)
    ready_total = stock_info["ready_count"]
    target_stock = stock_info["target_stock"]

    if ready_total >= target_stock:
        set_autonomous_setting(KEY_AUTONOMOUS_STATE, STATE_IDLE, db_path=db_path)
        msg = f"Estoque pronto suficiente ({ready_total}/{target_stock}). Nenhuma nova geração necessária."
        set_autonomous_setting(KEY_AUTONOMOUS_MESSAGE, msg, db_path=db_path)
        set_autonomous_setting(KEY_AUTONOMOUS_LAST_RESULT, msg, db_path=db_path)
        return {
            "status": "idle",
            "ready_stock": ready_total,
            "target_stock": target_stock,
            "message": msg,
        }

    deficit = target_stock - ready_total
    max_per_cycle = get_max_tasks_per_cycle(db_path=db_path)
    tasks_to_create = min(deficit, max_per_cycle, 1)  # Fase V12-E.1: máximo efetivo = 1

    # -----------------------------------------------------------------------
    # Etapa C: Planejamento e Seleção de Temas (Planning)
    # -----------------------------------------------------------------------
    set_autonomous_setting(KEY_AUTONOMOUS_STATE, STATE_PLANNING, db_path=db_path)
    set_autonomous_setting(KEY_AUTONOMOUS_MESSAGE, f"Estoque abaixo da meta ({ready_total}/{target_stock}). Selecionando {tasks_to_create} tema(s)...", db_path=db_path)

    candidate = discover_candidate_topic(niche=niche, language=language, db_path=db_path)
    if not candidate or not candidate.get("topic"):
        set_autonomous_setting(KEY_AUTONOMOUS_STATE, STATE_IDLE, db_path=db_path)
        msg = "Nenhum candidato a tema elegível encontrado sem duplicação."
        set_autonomous_setting(KEY_AUTONOMOUS_MESSAGE, msg, db_path=db_path)
        return {"status": "idle", "reason": "no_candidate", "message": msg}

    chosen_topic = candidate["topic"]
    trend_id = candidate.get("trend_id")

    # Recomenda estrutura narrativa diversificada
    rec_struct, _ = content_strategy.recommend_narrative_structure(
        topic=chosen_topic,
        niche=niche,
    )

    # -----------------------------------------------------------------------
    # Etapa D: Criação da Task e Submissão ao Pipeline Existente (Generating)
    # -----------------------------------------------------------------------
    new_task_id = str(uuid.uuid4())
    params = VideoParams(
        video_subject=chosen_topic,
        video_language=language,
        niche=niche,
        region=region,
        monetization_preset=preset,
        narrative_structure=rec_struct,
        profile_id=active_profile_id,
    )

    set_autonomous_setting(KEY_AUTONOMOUS_CURRENT_TASK_ID, new_task_id, db_path=db_path)
    set_autonomous_setting(KEY_AUTONOMOUS_STATE, STATE_GENERATING, db_path=db_path)
    msg = f"Iniciando geração autônoma: '{chosen_topic}' (task_id={new_task_id})"
    set_autonomous_setting(KEY_AUTONOMOUS_MESSAGE, msg, db_path=db_path)

    operator_console.log_operational_event(
        component="autonomous_production",
        severity=operator_console.SEVERITY_INFO,
        event_type="generation_started",
        task_id=new_task_id,
        message=msg,
        metadata={
            "topic": chosen_topic,
            "niche": niche,
            "preset": preset,
            "narrative_structure": rec_struct,
            "origin": candidate.get("origin"),
        },
        db_path=db_path,
    )

    try:
        webui_task.submit_generation(
            task_id=new_task_id,
            params=params,
            profile_id=active_profile_id,
            db_path=db_path,
        )
    except Exception as g_exc:
        set_autonomous_setting(KEY_AUTONOMOUS_CURRENT_TASK_ID, "", db_path=db_path)
        set_autonomous_setting(KEY_AUTONOMOUS_STATE, STATE_ERROR, db_path=db_path)
        err_msg = f"Falha ao submeter geração autônoma: {g_exc}"
        set_autonomous_setting(KEY_AUTONOMOUS_LAST_ERROR, err_msg, db_path=db_path)
        set_autonomous_setting(KEY_AUTONOMOUS_MESSAGE, err_msg, db_path=db_path)
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

    res_summary = f"Tarefa {new_task_id} submetida com sucesso ao pipeline ('{chosen_topic}')"
    set_autonomous_setting(KEY_AUTONOMOUS_LAST_RESULT, res_summary, db_path=db_path)
    return {
        "status": "generation_started",
        "task_id": new_task_id,
        "topic": chosen_topic,
        "niche": niche,
        "message": res_summary,
    }
