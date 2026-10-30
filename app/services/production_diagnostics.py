"""Production Diagnostics Service (Web UI V2 - Missão SIS3 / SIS3b).

Fornece diagnóstico estruturado e em tempo real sobre a produção de vídeos:
- Detecta por que canais não estão produzindo ou estão com estoque baixo
- Identifica tarefas presas, falsas interrupções, sequências de rejeições e erros
- Analisa operacionalidade da fábrica, limites de crescimento e cotas
- Somente leitura: não escreve em tabelas, não cria tabelas, opera em mode=ro
- Dados estáveis para alimentar a tela de Diagnóstico e futuros alertas
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger

from app.models import const
from app.services import (
    autonomous_production,
    operator_console,
    profile_manager,
    scheduler,
)
from app.services.channel_status import evaluate_canonical_channel_status

# =====================================================================
# Limiares de Detecção de Diagnósticos (Missão SIS3)
# =====================================================================
DEFAULT_STUCK_AFTER_RENDER_MINUTES: int = 10
"""Minutos após conclusão do render + Safety PASS sem registro em qualidade/estoque para considerar tarefa presa."""

DEFAULT_REJECTION_STREAK_THRESHOLD: int = 3
"""Quantidade de reprovações consecutivas nos gates pelo mesmo motivo para disparar alerta de repetição."""

DEFAULT_NO_GENERATION_GAP_HOURS: float = 6.0
"""Horas sem generation_started com fábrica ativa e estoque abaixo da meta para disparar alerta de hiato."""

DEFAULT_THROTTLE_RATIO_THRESHOLD: float = 0.8
"""Proporção de tentativas em 24h em relação a max_attempts_24h para indicar aproximação da cota diária."""

# =====================================================================
# Severidades e Status Padronizados
# =====================================================================
SEVERITY_INFO: str = "info"
SEVERITY_WARNING: str = "warning"
SEVERITY_CRITICAL: str = "critical"

SEVERITY_WEIGHT: Dict[str, int] = {
    SEVERITY_CRITICAL: 0,
    SEVERITY_WARNING: 1,
    SEVERITY_INFO: 2,
}

STATUS_OK: str = "ok"
STATUS_ATTENTION: str = "attention"
STATUS_BLOCKED: str = "blocked"
STATUS_RUNNING: str = "running"
STATUS_PAUSED: str = "paused"

# Constante para valor/estado desconhecido (separada dos status de canal; usada em factory.state e ready_stock.status)
STATUS_UNKNOWN: str = "UNKNOWN"

# Códigos Padronizados de Diagnóstico
CODE_TASK_STUCK_AFTER_RENDER: str = "TASK_STUCK_AFTER_RENDER"
CODE_FALSE_INTERRUPTION_LIKELY: str = "FALSE_INTERRUPTION_LIKELY"
CODE_REJECTION_STREAK: str = "REJECTION_STREAK"
CODE_NO_GENERATION_GAP: str = "NO_GENERATION_GAP"
CODE_INVALID_TOPIC: str = "INVALID_TOPIC"
CODE_FACTORY_PAUSED_OR_ERROR: str = "FACTORY_PAUSED_OR_ERROR"
CODE_THROTTLED_NORMAL: str = "THROTTLED_NORMAL"

# Novos detectores operacionais (Missão SIS3e)
CODE_AUTONOMOUS_DISABLED: str = "AUTONOMOUS_DISABLED"
CODE_DAILY_APPROVED_CAP_REACHED: str = "DAILY_APPROVED_CAP_REACHED"
CODE_DAILY_ATTEMPT_CAP_REACHED: str = "DAILY_ATTEMPT_CAP_REACHED"
CODE_APPROVED_CAP_EXCEEDED: str = "APPROVED_CAP_EXCEEDED"
CODE_REJECTION_BREAKER: str = "REJECTION_BREAKER"
CODE_GLOBAL_COST_GUARD: str = "GLOBAL_COST_GUARD"
CODE_GENERATION_FAILURE_STREAK: str = "GENERATION_FAILURE_STREAK"


def _get_ro_connection(target_path: str) -> sqlite3.Connection:
    """Abre conexão SQLite estritamente em modo somente leitura (mode=ro).

    Regras de robustez:
    - Monta URI via Path(target_path).resolve().as_uri() + "?mode=ro"
    - Executa PRAGMA query_only=ON
    - SEM fallback gravável
    - Se o arquivo não existir ou conexão falhar, lança exceção para tratamento seguro
    """
    p = Path(target_path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"Arquivo de banco de dados não encontrado: {p}")

    uri = p.as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON;")
    return conn


def resolve_channel_max_attempts(pid: str, auto_settings: Dict[str, str]) -> int:
    """Calcula o teto de tentativas 24h do canal conforme a lógica real de autonomous_production.get_max_attempts_24h.

    - Perfil default: DEFAULT_AUTONOMOUS_MAX_ATTEMPTS_24H (15) se não houver override.
    - Canais secundários: 8 se não houver override.
    - Override na chave autonomous_max_attempts_24h:<profile_id> tem precedência.
    """
    clean_p = str(pid or "").strip()
    is_default = (not clean_p) or (clean_p in (profile_manager.DEFAULT_PROFILE_ID, "default"))

    stored = None
    if not is_default:
        stored = auto_settings.get(f"{autonomous_production.KEY_AUTONOMOUS_MAX_ATTEMPTS_24H}:{clean_p}")
    else:
        if clean_p:
            stored = auto_settings.get(f"{autonomous_production.KEY_AUTONOMOUS_MAX_ATTEMPTS_24H}:{clean_p}")
        if stored is None:
            stored = auto_settings.get(autonomous_production.KEY_AUTONOMOUS_MAX_ATTEMPTS_24H)

    if stored is not None:
        try:
            return max(1, int(stored))
        except (ValueError, TypeError):
            pass

    return autonomous_production.DEFAULT_AUTONOMOUS_MAX_ATTEMPTS_24H if is_default else 8


def _parse_iso_to_utc(dt_str: Optional[str]) -> Optional[datetime]:
    """Converte string ISO 8601 em datetime UTC com timezone consciente."""
    if not dt_str:
        return None
    try:
        s = str(dt_str).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except Exception:
        return None


def _format_iso_utc(dt: Optional[datetime]) -> Optional[str]:
    """Formata datetime UTC com 'Z' no final (ex.: '2026-10-27T16:00:00Z')."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _extract_rejection_reason(msg: str, metadata: Dict[str, Any]) -> str:
    """Extrai motivo cru e fidedigno de reprovação a partir dos metadados e mensagem do evento."""
    unauth = metadata.get("unauthorized_provider")
    if unauth:
        return f"Provedor visual não autorizado: '{unauth}'"

    flow_fail = metadata.get("flow_validation_failure")
    if flow_fail:
        return f"Falha de proveniência Google Flow: {flow_fail}"

    cp_reason = metadata.get("copyright_reason") or metadata.get("rejection_reason")
    if cp_reason:
        return str(cp_reason).strip()

    bgm_status = metadata.get("bgm_status")
    if bgm_status and bgm_status not in ("SAFE_NO_BGM", "SAFE_PROCEDURAL"):
        return f"BGM não aprovada: {bgm_status}"

    if msg:
        raw_msg = str(msg).strip()
        if "reprovada nos Gates:" in raw_msg:
            parts = raw_msg.split("reprovada nos Gates:", 1)
            return parts[1].strip()
        if "retida:" in raw_msg:
            parts = raw_msg.split("retida:", 1)
            return parts[1].strip()
        return raw_msg

    return "Motivo de reprovação desconhecido"


def _extract_topic_from_event(msg: str, metadata: Dict[str, Any]) -> Optional[str]:
    """Extrai o tema do vídeo a partir de metadata ou texto cru da mensagem de início."""
    topic = metadata.get("topic") or metadata.get("video_subject")
    if topic:
        return str(topic).strip()

    if msg and "Iniciando geração autônoma: '" in msg:
        m = re.search(r"Iniciando geração autônoma:\s*'([^']+)'", msg)
        if m:
            return m.group(1).strip()
    return None


def get_diagnostics_overview(
    profile_id: Optional[str] = None,
    db_path: Optional[str] = None,
    task_base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
    _stock_fetcher: Optional[Any] = None,
    _limits_fetcher: Optional[Any] = None,
) -> Dict[str, Any]:
    """Retorna visão consolidada e detalhada de diagnóstico da fábrica e de cada canal."""
    effective_db = scheduler.get_db_path(db_path)
    now_utc = now if now is not None else datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    else:
        now_utc = now_utc.astimezone(timezone.utc)

    h24_ago_dt = now_utc - timedelta(hours=24)
    h24_ago_iso = h24_ago_dt.isoformat()

    clean_filter_pid = str(profile_id).strip() if profile_id else None

    # Verifica se arquivo existe antes de tentar abrir; nunca cria arquivo se inexistente
    p_db = Path(effective_db).resolve()
    if not p_db.is_file():
        return {
            "factory": {
                "state": STATUS_UNKNOWN,
                "is_paused": False,
                "message": f"Banco de dados não encontrado: {p_db}",
                "last_error": None,
                "primary_instance": {
                    "node_id": None, "node_name": None, "hostname": None,
                    "pid": None, "status": None, "last_heartbeat": None,
                },
            },
            "channels": [],
        }

    try:
        conn = _get_ro_connection(effective_db)
    except Exception as exc:
        return {
            "factory": {
                "state": STATUS_UNKNOWN,
                "is_paused": False,
                "message": f"Não foi possível abrir o banco em modo somente leitura: {exc}",
                "last_error": str(exc),
                "primary_instance": {
                    "node_id": None, "node_name": None, "hostname": None,
                    "pid": None, "status": None, "last_heartbeat": None,
                },
            },
            "channels": [],
        }

    try:
        existing_tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table';"
            ).fetchall()
        }

        # -----------------------------------------------------------------
        # 1. Leitura da Instância Primária e Estado Geral da Fábrica (Somente Leitura)
        # -----------------------------------------------------------------
        primary_inst: Dict[str, Any] = {
            "node_id": None,
            "node_name": None,
            "hostname": None,
            "pid": None,
            "status": None,
            "last_heartbeat": None,
        }

        if "instance_locks" in existing_tables:
            lock_row = conn.execute(
                "SELECT * FROM instance_locks WHERE lock_key = ?;",
                (operator_console.DEFAULT_INSTANCE_LOCK_KEY,),
            ).fetchone()
            if lock_row:
                lr = dict(lock_row)
                primary_inst = {
                    "node_id": lr.get("node_id"),
                    "node_name": lr.get("node_name"),
                    "hostname": lr.get("hostname"),
                    "pid": lr.get("pid"),
                    "status": lr.get("status"),
                    "last_heartbeat": _format_iso_utc(_parse_iso_to_utc(lr.get("last_heartbeat"))),
                }

        # Leitura puramente passiva de configurações operacionais da mesma fonte de Pausar/Retomar
        auto_settings: Dict[str, str] = {}
        if "autopilot_settings" in existing_tables:
            s_rows = conn.execute("SELECT key, value FROM autopilot_settings;").fetchall()
            auto_settings = {r[0]: str(r[1]) for r in s_rows if r[0]}

        # A tela Sistema e operator_console gravam 'factory_state' em autopilot_settings (operator_console.py:977)
        factory_state_setting = str(auto_settings.get("factory_state") or "").upper().strip()
        auto_state_setting = str(auto_settings.get("autonomous_state") or "").upper().strip()
        enabled_val = str(auto_settings.get("autonomous_mode_enabled") or "true").lower()
        is_factory_enabled = enabled_val in ("1", "true", "yes")

        is_factory_paused = (
            factory_state_setting == operator_console.FACTORY_STATE_PAUSED
            or auto_state_setting == "PAUSED"
            or not is_factory_enabled
        )

        if is_factory_paused:
            factory_state = "PAUSED"
        elif auto_state_setting == "ERROR":
            factory_state = "ERROR"
        else:
            factory_state = operator_console.get_consolidated_factory_state(db_path=effective_db)

        factory_msg = str(auto_settings.get("autonomous_message") or "")
        factory_error = auto_settings.get("autonomous_last_error")

        # -----------------------------------------------------------------
        # 2. Leitura de Perfis / Canais
        # -----------------------------------------------------------------
        profiles: List[Dict[str, Any]] = []
        if "content_profiles" in existing_tables:
            if clean_filter_pid:
                p_rows = conn.execute(
                    "SELECT id, name, is_active FROM content_profiles WHERE id = ? ORDER BY created_at ASC;",
                    (clean_filter_pid,),
                ).fetchall()
            else:
                p_rows = conn.execute(
                    "SELECT id, name, is_active FROM content_profiles ORDER BY created_at ASC;"
                ).fetchall()
            profiles = [dict(r) for r in p_rows]

        # -----------------------------------------------------------------
        # 3. Mapeamentos e Tabelas Relacionadas das últimas 24h
        # -----------------------------------------------------------------
        task_profile_map: Dict[str, str] = {}
        if "task_profiles" in existing_tables:
            tp_rows = conn.execute(
                "SELECT task_id, profile_id FROM task_profiles WHERE created_at >= ?;",
                (h24_ago_iso,),
            ).fetchall()
            for r in tp_rows:
                if r["profile_id"]:
                    task_profile_map[r["task_id"]] = str(r["profile_id"])

        scheduled_tasks: Dict[str, Dict[str, Any]] = {}
        if "scheduled_posts" in existing_tables:
            sp_rows = conn.execute(
                "SELECT id, task_id, status, scheduled_at, profile_id FROM scheduled_posts;"
            ).fetchall()
            for r in sp_rows:
                tid = r["task_id"]
                if tid:
                    scheduled_tasks[tid] = dict(r)
                    if r["profile_id"] and tid not in task_profile_map:
                        task_profile_map[tid] = str(r["profile_id"])

        safety_map: Dict[str, Dict[str, Any]] = {}
        if "monetization_safety" in existing_tables:
            ms_rows = conn.execute(
                "SELECT task_id, safety_status, safety_reasons, checked_at FROM monetization_safety WHERE checked_at >= ?;",
                (h24_ago_iso,),
            ).fetchall()
            for r in ms_rows:
                tid = r["task_id"]
                if tid:
                    safety_map[tid] = dict(r)

        quality_map: Dict[str, Dict[str, Any]] = {}
        if "content_quality_scores" in existing_tables:
            qs_rows = conn.execute(
                "SELECT task_id, quality_score, quality_label, created_at FROM content_quality_scores WHERE created_at >= ?;",
                (h24_ago_iso,),
            ).fetchall()
            for r in qs_rows:
                tid = r["task_id"]
                if tid:
                    quality_map[tid] = dict(r)

        events: List[Dict[str, Any]] = []
        if "operational_events" in existing_tables:
            oe_rows = conn.execute(
                """
                SELECT id, timestamp, component, severity, event_type, task_id, message, metadata_json
                FROM operational_events
                WHERE timestamp >= ?
                ORDER BY timestamp ASC;
                """,
                (h24_ago_iso,),
            ).fetchall()
            for r in oe_rows:
                ed = dict(r)
                meta = {}
                raw_m = ed.get("metadata_json")
                if raw_m:
                    try:
                        meta = json.loads(raw_m) if isinstance(raw_m, str) else raw_m
                    except Exception:
                        meta = {}
                ed["metadata"] = meta if isinstance(meta, dict) else {}
                events.append(ed)

                tid = ed.get("task_id")
                p_in_meta = ed["metadata"].get("profile_id")
                if tid and p_in_meta and tid not in task_profile_map:
                    task_profile_map[tid] = str(p_in_meta)

    finally:
        conn.close()

    # -----------------------------------------------------------------
    # 4. Tetos e Limites Globais (Global Cost Guard)
    # -----------------------------------------------------------------
    global_att_cap: Optional[int] = None
    global_att_used: Optional[int] = None
    global_gen_cap: Optional[int] = None
    global_gen_used: Optional[int] = None

    try:
        global_att_cap = autonomous_production.get_global_max_attempts_24h(db_path=effective_db)
    except Exception as exc:
        logger.warning(f"[PRODUCTION_DIAGNOSTICS] Erro ao obter teto global de tentativas: {exc}")

    try:
        global_att_used = autonomous_production.count_all_profiles_attempts_24h(now=now_utc, db_path=effective_db)
    except Exception as exc:
        logger.warning(f"[PRODUCTION_DIAGNOSTICS] Erro ao contar tentativas globais 24h: {exc}")

    try:
        global_gen_cap = autonomous_production.get_global_max_generations_24h(db_path=effective_db)
    except Exception as exc:
        logger.warning(f"[PRODUCTION_DIAGNOSTICS] Erro ao obter teto global de gerações aprovadas: {exc}")

    try:
        global_gen_used = autonomous_production.count_all_profiles_generations_24h(now=now_utc, db_path=effective_db)
    except Exception as exc:
        logger.warning(f"[PRODUCTION_DIAGNOSTICS] Erro ao contar gerações globais aprovadas 24h: {exc}")

    global_limits: Dict[str, Any] = {
        "attempts_24h": {"used": global_att_used, "cap": global_att_cap},
        "approved_24h": {"used": global_gen_used, "cap": global_gen_cap},
    }

    # -----------------------------------------------------------------
    # 5. Agrupamento de Eventos por Canal
    # -----------------------------------------------------------------
    events_by_channel: Dict[str, List[Dict[str, Any]]] = {}
    growth_limit_events_by_channel: Dict[str, List[Dict[str, Any]]] = {}

    for ev in events:
        tid = ev.get("task_id")
        p_id = None
        if tid and tid in task_profile_map:
            p_id = task_profile_map[tid]
        elif ev["metadata"].get("profile_id"):
            p_id = str(ev["metadata"]["profile_id"])

        target_channel_key = p_id if p_id else "unassigned"
        events_by_channel.setdefault(target_channel_key, []).append(ev)

        if ev.get("event_type") == "PROFILE_GROWTH_LIMIT_BLOCK":
            growth_limit_events_by_channel.setdefault(target_channel_key, []).append(ev)

    # Processa estritamente os canais cadastrados (Sem Canal não é canal)
    channels_to_process = list(profiles)

    channels_output: List[Dict[str, Any]] = []

    for prof in channels_to_process:
        pid = prof["id"]
        pname = prof["name"]

        chan_events = events_by_channel.get(pid, [])
        is_channel_active = bool(prof.get("is_active", 1))

        channel_warnings: List[str] = []

        # -------------------------------------------------------------
        # Limites do Canal (Guardas 5.1–5.4 do laço autônomo)
        # -------------------------------------------------------------
        growth_mode: Optional[str] = None
        autonomous_enabled: Optional[bool] = None
        app_used: Optional[int] = None
        app_cap: Optional[int] = None
        att_used: Optional[int] = None
        att_cap: Optional[int] = None
        cr_used: Optional[int] = None
        cr_limit: Optional[int] = autonomous_production.DEFAULT_AUTONOMOUS_MAX_CONSECUTIVE_REJECTIONS

        if _limits_fetcher is not None:
            try:
                lf_data = _limits_fetcher(profile_id=pid, db_path=effective_db, now=now_utc)
                if isinstance(lf_data, dict):
                    growth_mode = lf_data.get("growth_mode")
                    autonomous_enabled = lf_data.get("autonomous_enabled")
                    if "approved_24h" in lf_data and isinstance(lf_data["approved_24h"], dict):
                        app_used = lf_data["approved_24h"].get("used")
                        app_cap = lf_data["approved_24h"].get("cap")
                    if "attempts_24h" in lf_data and isinstance(lf_data["attempts_24h"], dict):
                        att_used = lf_data["attempts_24h"].get("used")
                        att_cap = lf_data["attempts_24h"].get("cap")
                    if "consecutive_rejections" in lf_data and isinstance(lf_data["consecutive_rejections"], dict):
                        cr_used = lf_data["consecutive_rejections"].get("used")
                        cr_limit = lf_data["consecutive_rejections"].get("limit", cr_limit)
            except Exception as exc:
                channel_warnings.append(f"Erro ao consultar limites do canal: {exc}")
        elif pid != "unassigned":
            try:
                growth_mode = autonomous_production.get_profile_growth_mode(profile_id=pid, db_path=effective_db)
            except Exception as exc:
                channel_warnings.append(f"Erro ao obter modo de crescimento: {exc}")

            try:
                autonomous_enabled = autonomous_production.is_profile_autonomous_mode_enabled(pid, db_path=effective_db)
            except Exception as exc:
                channel_warnings.append(f"Erro ao consultar modo autônomo do perfil: {exc}")

            try:
                app_cap = autonomous_production.get_max_generations_24h(profile_id=pid, db_path=effective_db)
            except Exception as exc:
                channel_warnings.append(f"Erro ao obter teto de aprovações 24h: {exc}")

            try:
                yt_channel = autonomous_production.resolve_autonomous_youtube_channel(pid, db_path=effective_db)
                app_used = autonomous_production.count_generations_in_last_24h(now=now_utc, db_path=effective_db, profile_id=pid, channel_id=yt_channel)
            except Exception as exc:
                channel_warnings.append(f"Erro ao contar gerações aprovadas 24h: {exc}")

            try:
                att_cap = autonomous_production.get_max_attempts_24h(profile_id=pid, db_path=effective_db)
            except Exception as exc:
                channel_warnings.append(f"Erro ao obter teto de tentativas 24h: {exc}")

            try:
                att_used = autonomous_production.count_generation_attempts_in_last_24h(now=now_utc, db_path=effective_db, profile_id=pid)
            except Exception as exc:
                channel_warnings.append(f"Erro ao contar tentativas 24h: {exc}")

            try:
                cr_used = autonomous_production.get_consecutive_rejections(db_path=effective_db, profile_id=pid)
            except Exception as exc:
                channel_warnings.append(f"Erro ao consultar rejeições consecutivas: {exc}")

        if autonomous_enabled is None and pid != "unassigned":
            try:
                autonomous_enabled = autonomous_production.is_profile_autonomous_mode_enabled(pid, db_path=effective_db)
            except Exception:
                pass

        channel_limits = {
            "growth_mode": growth_mode,
            "autonomous_enabled": autonomous_enabled,
            "approved_24h": {"used": app_used, "cap": app_cap},
            "attempts_24h": {"used": att_used, "cap": att_cap},
            "consecutive_rejections": {"used": cr_used, "limit": cr_limit},
        }

        # Cota de tentativas 24h reaproveitando regras canônicas de autonomous_production.get_max_attempts_24h
        if att_cap is not None:
            max_attempts_24h = att_cap
        else:
            max_attempts_24h = resolve_channel_max_attempts(pid, auto_settings)

        # -------------------------------------------------------------
        # Estoque Canônico e Meta Única (mesma fonte da tela Produção / laço autônomo)
        # -------------------------------------------------------------
        # Os init_* idempotentes (CREATE TABLE IF NOT EXISTS) disparados internamente por
        # get_canonical_ready_stock são o comportamento padrão aceito em todos os endpoints V2.
        stock_count: Optional[int] = None
        target_stock: Optional[int] = None
        stock_status: str = STATUS_UNKNOWN
        stock_error: Optional[str] = None
        ready_task_ids: Set[str] = set()

        try:
            if _stock_fetcher is not None:
                stock_info = _stock_fetcher(
                    task_base_dir=task_base_dir,
                    db_path=effective_db,
                    profile_id=pid,
                )
            else:
                stock_info = operator_console.get_canonical_ready_stock(
                    task_base_dir=task_base_dir,
                    db_path=effective_db,
                    profile_id=pid,
                )

            if isinstance(stock_info, dict):
                raw_count = stock_info.get("total_ready")
                if raw_count is None:
                    raw_count = stock_info.get("ready_count")
                if raw_count is not None:
                    stock_count = int(raw_count)

                # Meta única: obtida diretamente de minimum_threshold devolvido por get_canonical_ready_stock
                raw_target = stock_info.get("minimum_threshold")
                if raw_target is None:
                    raw_target = stock_info.get("target_stock")
                if raw_target is not None:
                    target_stock = int(raw_target)

                stock_status = "OK"
                ready_task_ids = {
                    it.get("task_id")
                    for it in stock_info.get("youtube_ready", [])
                    if isinstance(it, dict) and it.get("task_id")
                }
            else:
                stock_error = f"Resposta inesperada de estoque canônico: {type(stock_info)}"
        except Exception as exc:
            logger.warning(f"[PRODUCTION_DIAGNOSTICS] Erro ao obter estoque canônico para perfil {pid}: {exc}")
            stock_error = str(exc)
            stock_status = STATUS_UNKNOWN
            stock_count = None
            target_stock = None
            ready_task_ids = set()

        if stock_status == STATUS_UNKNOWN:
            msg = f"Estoque canônico indisponível: {stock_error}" if stock_error else "Estoque canônico indisponível"
            channel_warnings.append(msg)

        # -------------------------------------------------------------
        # Reconstrução das Gerações do Canal e Contadores 24h
        # -------------------------------------------------------------
        task_events: Dict[str, List[Dict[str, Any]]] = {}
        for ev in chan_events:
            tid = ev.get("task_id")
            if tid:
                task_events.setdefault(tid, []).append(ev)

        generations_list: List[Dict[str, Any]] = []
        counts_started = 0
        counts_approved = 0
        counts_rejected = 0
        counts_interrupted = 0

        for tid, t_evs in task_events.items():
            t_evs_sorted = sorted(t_evs, key=lambda x: x["timestamp"])

            start_ev = next((e for e in t_evs_sorted if e["event_type"] == "generation_started"), None)
            if start_ev:
                counts_started += 1
                started_at_dt = _parse_iso_to_utc(start_ev["timestamp"])
                topic = _extract_topic_from_event(start_ev["message"], start_ev["metadata"])
            else:
                started_at_dt = _parse_iso_to_utc(t_evs_sorted[0]["timestamp"])
                topic = _extract_topic_from_event(t_evs_sorted[0]["message"], t_evs_sorted[0]["metadata"])

            outcome = "UNKNOWN"
            reason = None

            has_approval = any(e["event_type"] in ("generation_approved", "task_approved_and_scheduled") for e in t_evs_sorted)
            has_rejection = next((e for e in reversed(t_evs_sorted) if e["event_type"] == "task_gate_rejected"), None)
            has_interruption = next((e for e in reversed(t_evs_sorted) if e["event_type"] == "generation_interrupted_recovery"), None)
            has_failed = next((e for e in reversed(t_evs_sorted) if e["event_type"] == "generation_failed"), None)

            if has_approval:
                outcome = "APPROVED"
                counts_approved += 1
            elif has_rejection:
                outcome = "REJECTED"
                counts_rejected += 1
                reason = _extract_rejection_reason(has_rejection["message"], has_rejection["metadata"])
            elif has_interruption:
                outcome = "INTERRUPTED"
                counts_interrupted += 1
                reason = has_interruption["message"]
            elif has_failed:
                outcome = "FAILED"
                reason = has_failed["message"]
            elif start_ev:
                outcome = "RUNNING"

            generations_list.append({
                "task_id": tid,
                "started_at": started_at_dt,
                "outcome": outcome,
                "reason": reason,
                "topic": topic,
                "events": t_evs_sorted,
            })

        generations_list.sort(key=lambda x: x["started_at"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

        recent_10 = generations_list[:10]
        last_gen = recent_10[0] if recent_10 else None
        last_gen_at = last_gen["started_at"] if last_gen else None
        last_outcome = last_gen["outcome"] if last_gen else None

        # -------------------------------------------------------------
        # Execução dos Detectores de Diagnóstico
        # -------------------------------------------------------------
        diagnoses: List[Dict[str, Any]] = []

        # -------------------------------------------------------------
        # Detector 1: TASK_STUCK_AFTER_RENDER
        # Tarefa com vídeo final existente + Safety PASS, sem linha em
        # content_quality_scores e fora de scheduled_posts/estoque há mais de N minutos
        # -------------------------------------------------------------
        for gen in generations_list:
            tid = gen["task_id"]
            final_vid = scheduler.get_task_final_video(tid, task_base_dir=task_base_dir)
            has_final_vid = bool(final_vid and os.path.isfile(final_vid) and os.path.getsize(final_vid) > 0)

            safety_record = safety_map.get(tid)
            has_safety_pass = bool(safety_record and safety_record.get("safety_status") == const.SAFETY_STATUS_PASS)

            in_quality = tid in quality_map
            in_scheduled = tid in scheduled_tasks
            in_stock = tid in ready_task_ids

            if has_final_vid and has_safety_pass and not in_quality and not in_scheduled and not in_stock:
                ref_time = _parse_iso_to_utc(safety_record.get("checked_at")) or gen["started_at"] or now_utc
                age_min = max(0.0, (now_utc - ref_time).total_seconds() / 60.0)

                if age_min >= DEFAULT_STUCK_AFTER_RENDER_MINUTES:
                    ev_ids = [e["id"] for e in gen.get("events", []) if "id" in e]
                    diagnoses.append({
                        "code": CODE_TASK_STUCK_AFTER_RENDER,
                        "severity": SEVERITY_CRITICAL,
                        "title": "Tarefa renderizada e segura travada antes da avaliação de qualidade",
                        "detail": (
                            f"A tarefa {tid} concluiu a renderização com vídeo final íntegro e validação de segurança "
                            f"aprovada (Safety PASS), mas permaneceu fora do estoque, sem nota de qualidade ou agendamento "
                            f"há {int(round(age_min))} minutos."
                        ),
                        "since": _format_iso_utc(ref_time),
                        "evidence": {
                            "task_ids": [tid],
                            "event_ids": ev_ids,
                        },
                        "suggested_action": "Disparar avaliação de gates para a tarefa ou incluí-la manualmente no estoque de publicação.",
                    })

        # -------------------------------------------------------------
        # Detector 2: FALSE_INTERRUPTION_LIKELY
        # generation_interrupted_recovery seguido de final-*.mp4 e/ou Safety PASS da MESMA tarefa
        # -------------------------------------------------------------
        for gen in generations_list:
            tid = gen["task_id"]
            interrupted_ev = next((e for e in gen.get("events", []) if e["event_type"] == "generation_interrupted_recovery"), None)
            if interrupted_ev:
                final_vid = scheduler.get_task_final_video(tid, task_base_dir=task_base_dir)
                has_final_vid = bool(final_vid and os.path.isfile(final_vid) and os.path.getsize(final_vid) > 0)
                safety_record = safety_map.get(tid)
                has_safety_pass = bool(safety_record and safety_record.get("safety_status") == const.SAFETY_STATUS_PASS)

                if has_final_vid or has_safety_pass:
                    diagnoses.append({
                        "code": CODE_FALSE_INTERRUPTION_LIKELY,
                        "severity": SEVERITY_CRITICAL,
                        "title": "Falso positivo de interrupção: vídeo renderizado apesar de recuperação de reinicialização",
                        "detail": (
                            f"A tarefa {tid} foi descartada por 'generation_interrupted_recovery', porém o arquivo de vídeo "
                            f"final existe em disco e/ou o Safety Gate foi concluído com sucesso. A renderização foi concluída."
                        ),
                        "since": _format_iso_utc(_parse_iso_to_utc(interrupted_ev["timestamp"])),
                        "evidence": {
                            "task_ids": [tid],
                            "event_ids": [interrupted_ev["id"]] if "id" in interrupted_ev else [],
                        },
                        "suggested_action": "Reavaliar a tarefa nos Gates para homologação no estoque sem descartar o render.",
                    })

        # -------------------------------------------------------------
        # Detector 3: REJECTION_STREAK
        # 3+ task_gate_rejected consecutivos do canal com o mesmo motivo
        # -------------------------------------------------------------
        streak_tasks: List[str] = []
        streak_event_ids: List[int] = []
        streak_reasons: List[str] = []

        for gen in generations_list:
            if gen["outcome"] == "REJECTED":
                streak_tasks.append(gen["task_id"])
                streak_reasons.append(gen["reason"] or "Motivo não especificado")
                for e in gen.get("events", []):
                    if e["event_type"] == "task_gate_rejected" and "id" in e:
                        streak_event_ids.append(e["id"])
            elif gen["outcome"] in ("APPROVED", "RUNNING"):
                break

        if len(streak_tasks) >= DEFAULT_REJECTION_STREAK_THRESHOLD:
            normalized_reasons = [r.lower().strip() for r in streak_reasons]
            first_norm = normalized_reasons[0]
            is_same_reason = all(
                r == first_norm
                or ("local_fallback" in r and "local_fallback" in first_norm)
                or ("provenance" in r and "provenance" in first_norm)
                for r in normalized_reasons
            )
            reported_reason = streak_reasons[0] if is_same_reason else "Múltiplas rejeições nos gates"

            first_ev_time = None
            if streak_tasks:
                first_tid = streak_tasks[0]
                first_ev = next((g["started_at"] for g in generations_list if g["task_id"] == first_tid), None)
                first_ev_time = first_ev

            diagnoses.append({
                "code": CODE_REJECTION_STREAK,
                "severity": SEVERITY_CRITICAL,
                "title": f"Sequência de {len(streak_tasks)} reprovações consecutivas nos gates",
                "detail": (
                    f"O canal acumulou {len(streak_tasks)} reprovações seguidas com o motivo: '{reported_reason}'. "
                    f"A produção autônoma pode estar travada por rejeição repetida nos filtros de segurança ou direitos autorais."
                ),
                "since": _format_iso_utc(first_ev_time),
                "evidence": {
                    "task_ids": streak_tasks,
                    "event_ids": streak_event_ids,
                },
                "suggested_action": "Inspecionar os parâmetros editoriais e provedores de mídia do canal para cessar as rejeições.",
            })

        # -------------------------------------------------------------
        # Detector 4: NO_GENERATION_GAP
        # Canal sem generation_started há mais de X horas, com fábrica não pausada e estoque abaixo da meta
        # -------------------------------------------------------------
        is_approved_cap_reached = bool(app_cap is not None and app_used is not None and app_cap > 0 and app_used >= app_cap)
        if not is_factory_paused and is_channel_active and autonomous_enabled is not False and stock_status != STATUS_UNKNOWN and stock_count is not None and target_stock is not None and not is_approved_cap_reached:
            if stock_count < target_stock:
                gap_hours = (
                    (now_utc - last_gen_at).total_seconds() / 3600.0
                    if last_gen_at is not None
                    else 24.0
                )
                if gap_hours >= DEFAULT_NO_GENERATION_GAP_HOURS:
                    severity = SEVERITY_CRITICAL if (gap_hours >= 12.0 and stock_count == 0) else SEVERITY_WARNING
                    diagnoses.append({
                        "code": CODE_NO_GENERATION_GAP,
                        "severity": severity,
                        "title": f"Hiato de produção: {gap_hours:.1f}h sem novas gerações",
                        "detail": (
                            f"Nenhuma tarefa foi iniciada para o canal nas últimas {gap_hours:.1f} horas. "
                            f"O estoque atual ({stock_count}/{target_stock}) está abaixo da meta e a fábrica está ativa."
                        ),
                        "since": _format_iso_utc(last_gen_at),
                        "evidence": {
                            "task_ids": [],
                            "event_ids": [],
                        },
                        "suggested_action": "Verificar se o scheduler está executando ticks periódicos e se há tópicos disponíveis para o canal.",
                    })

        # -------------------------------------------------------------
        # Detector 5: INVALID_TOPIC
        # generation_started cujo assunto começa com 'Error:' ou 'Traceback' (erro usado como título)
        # -------------------------------------------------------------
        for gen in generations_list:
            top = gen.get("topic")
            if top:
                clean_top = str(top).strip()
                is_invalid = (
                    clean_top.lower().startswith("error:")
                    or clean_top.lower().startswith("traceback")
                    or "[errno" in clean_top.lower()
                    or "getaddrinfo failed" in clean_top.lower()
                )
                if is_invalid:
                    tid = gen["task_id"]
                    ev_ids = [e["id"] for e in gen.get("events", []) if "id" in e]
                    diagnoses.append({
                        "code": CODE_INVALID_TOPIC,
                        "severity": SEVERITY_WARNING,
                        "title": "Tema inválido gerado a partir de mensagem de erro",
                        "detail": (
                            f"A tarefa {tid} foi iniciada com título correspondente a uma mensagem de erro ou exceção técnica: "
                            f"'{clean_top}'."
                        ),
                        "since": _format_iso_utc(gen["started_at"]),
                        "evidence": {
                            "task_ids": [tid],
                            "event_ids": ev_ids,
                        },
                        "suggested_action": "Revisar o pipeline de descoberta de tendências/geração de temas para descartar respostas de erro.",
                    })

        # -------------------------------------------------------------
        # Detector 6: FACTORY_PAUSED_OR_ERROR
        # Fábrica pausada ou estado ERROR (informe a mensagem real)
        # -------------------------------------------------------------
        if factory_state == "ERROR":
            diagnoses.append({
                "code": CODE_FACTORY_PAUSED_OR_ERROR,
                "severity": SEVERITY_CRITICAL,
                "title": "Fábrica em estado de erro crítico",
                "detail": factory_error or factory_msg or "A produção autônoma está em estado ERROR.",
                "since": None,
                "evidence": {"task_ids": [], "event_ids": []},
                "suggested_action": "Analisar o log de erro recente da fábrica e reiniciar o motor após a correção.",
            })
        elif is_factory_paused:
            diagnoses.append({
                "code": CODE_FACTORY_PAUSED_OR_ERROR,
                "severity": SEVERITY_INFO,
                "title": "Fábrica pausada operacionalmente",
                "detail": factory_msg or "A fábrica está pausada operacionalmente (factory_state='PAUSED'). Novas execuções e gerações estão bloqueadas.",
                "since": None,
                "evidence": {"task_ids": [], "event_ids": []},
                "suggested_action": "Retomar a fábrica através da barra superior para reativar o agendamento.",
            })

        # -------------------------------------------------------------
        # Detector 7: THROTTLED_NORMAL
        # Bloqueios de crescimento/cota (PROFILE_GROWTH_LIMIT_BLOCK, tentativas 24h perto do máximo)
        # com severidade 'info' e rótulo 'limitação normal', NUNCA como erro.
        # -------------------------------------------------------------
        growth_blocks = growth_limit_events_by_channel.get(pid, [])
        is_near_quota = (counts_started >= int(round(max_attempts_24h * DEFAULT_THROTTLE_RATIO_THRESHOLD)))

        if growth_blocks or is_near_quota:
            throttle_ev_ids = [e["id"] for e in growth_blocks if "id" in e]
            throttle_msg = (
                f"Canal em limitação normal de crescimento ou cota diária ({counts_started}/{max_attempts_24h} "
                f"tentativas nas últimas 24h). Comportamento de proteção esperado."
            )
            since_dt = _parse_iso_to_utc(growth_blocks[-1]["timestamp"]) if growth_blocks else now_utc
            diagnoses.append({
                "code": CODE_THROTTLED_NORMAL,
                "severity": SEVERITY_INFO,
                "title": "Limitação normal de cota / crescimento ativo",
                "detail": throttle_msg,
                "since": _format_iso_utc(since_dt),
                "evidence": {
                    "task_ids": [e["task_id"] for e in growth_blocks if e.get("task_id")],
                    "event_ids": throttle_ev_ids,
                },
                "suggested_action": "Nenhuma ação corretiva necessária. As tentativas serão liberadas com o avanço da janela de 24h.",
            })

        # -------------------------------------------------------------
        # Detector 8: AUTONOMOUS_DISABLED (info)
        # Produção autônoma desligada para o canal
        # -------------------------------------------------------------
        if autonomous_enabled is False:
            toggle_ev = next(
                (e for e in reversed(chan_events) if e.get("event_type") in ("profile_autonomous_mode_toggled", "autonomous_mode_toggled")),
                None,
            )
            toggle_since = _format_iso_utc(_parse_iso_to_utc(toggle_ev["timestamp"])) if toggle_ev else None
            diagnoses.append({
                "code": CODE_AUTONOMOUS_DISABLED,
                "severity": SEVERITY_INFO,
                "title": "Produção autônoma desativada para este canal",
                "detail": "A produção autônoma está desligada pelo operador para o canal. Nenhuma geração automática será iniciada.",
                "since": toggle_since,
                "evidence": {
                    "task_ids": [],
                    "event_ids": [toggle_ev["id"]] if (toggle_ev and "id" in toggle_ev) else [],
                },
                "suggested_action": "Ativar a produção autônoma do canal na tela Sistema ou configurações de perfil quando desejar produzir.",
            })

        # -------------------------------------------------------------
        # Detector 9: DAILY_APPROVED_CAP_REACHED (info) e APPROVED_CAP_EXCEEDED (warning)
        # -------------------------------------------------------------
        if app_used is not None and app_cap is not None:
            if app_used >= app_cap:
                approved_events = [
                    e for e in chan_events
                    if e.get("event_type") in ("generation_approved", "task_approved_and_scheduled", "task_waiting_schedule")
                ]
                release_info = ""
                if approved_events:
                    approved_events_sorted = sorted(approved_events, key=lambda x: x["timestamp"])
                    oldest_approved_dt = _parse_iso_to_utc(approved_events_sorted[0]["timestamp"])
                    if oldest_approved_dt:
                        est_release_dt = oldest_approved_dt + timedelta(hours=24)
                        release_info = f" Próxima liberação estimada em {_format_iso_utc(est_release_dt)}."

                mode_label = growth_mode.upper() if growth_mode else "NORMAL"
                diagnoses.append({
                    "code": CODE_DAILY_APPROVED_CAP_REACHED,
                    "severity": SEVERITY_INFO,
                    "title": f"Limite diário de aprovações atingido ({app_used}/{app_cap})",
                    "detail": (
                        f"O canal atingiu o teto diário de aprovações no modo {mode_label} ({app_used}/{app_cap} em 24h). "
                        f"A produção autônoma libera novas vagas quando as aprovações mais antigas saírem da janela de 24h.{release_info}"
                    ),
                    "since": None,
                    "evidence": {"task_ids": [], "event_ids": []},
                    "suggested_action": "Aguardar a janela de 24h avançar ou aumentar o teto de aprovações do perfil se desejado.",
                })

            if app_used > app_cap:
                diagnoses.append({
                    "code": CODE_APPROVED_CAP_EXCEEDED,
                    "severity": SEVERITY_WARNING,
                    "title": f"Teto diário de aprovações excedido ({app_used}/{app_cap})",
                    "detail": (
                        f"O canal possui {app_used} gerações aprovadas nas últimas 24h, excedendo o teto configurado de {app_cap}. "
                        f"Isso ocorre normalmente quando o teto é reduzido pelo operador enquanto havia vídeos gerados ou por intervenções pontuais."
                    ),
                    "since": None,
                    "evidence": {"task_ids": [], "event_ids": []},
                    "suggested_action": "Verificar se o teto de aprovações precisa ser ajustado ou aguardar a janela de 24h.",
                })

        # -------------------------------------------------------------
        # Detector 10: DAILY_ATTEMPT_CAP_REACHED (info)
        # -------------------------------------------------------------
        if att_used is not None and att_cap is not None and att_used >= att_cap:
            diagnoses.append({
                "code": CODE_DAILY_ATTEMPT_CAP_REACHED,
                "severity": SEVERITY_INFO,
                "title": f"Teto diário de tentativas atingido ({att_used}/{att_cap})",
                "detail": (
                    f"O canal realizou {att_used} tentativas de {att_cap} autorizadas em 24h ({att_used}/{att_cap}). "
                    f"Novas tentativas de geração estão em pausa de proteção até a liberação de cotas na janela de 24h."
                ),
                "since": None,
                "evidence": {"task_ids": [], "event_ids": []},
                "suggested_action": "Aguardar o ciclo da janela de 24h para liberação natural de novas tentativas de produção.",
            })

        # -------------------------------------------------------------
        # Detector 11: REJECTION_BREAKER (warning quando used >= 50% do limite; critical quando used >= limite)
        # -------------------------------------------------------------
        if cr_used is not None and cr_limit is not None and cr_limit > 0:
            if cr_used >= cr_limit:
                diagnoses.append({
                    "code": CODE_REJECTION_BREAKER,
                    "severity": SEVERITY_CRITICAL,
                    "title": f"Circuit breaker ativado: {cr_used}/{cr_limit} rejeições consecutivas",
                    "detail": (
                        f"Proteção de custo ativa: produção bloqueada até uma aprovação resetar o contador. "
                        f"O canal acumulou {cr_used} rejeições seguidas nos Gates (limite de bloqueio: {cr_limit})."
                    ),
                    "since": None,
                    "evidence": {"task_ids": [], "event_ids": []},
                    "suggested_action": "Investigar e corrigir as causas de reprovação nos gates e validar uma aprovação para reiniciar o ciclo.",
                })
            elif cr_used >= int(round(cr_limit * 0.5)):
                diagnoses.append({
                    "code": CODE_REJECTION_BREAKER,
                    "severity": SEVERITY_WARNING,
                    "title": f"Alerta de rejeições consecutivas: {cr_used}/{cr_limit} nos gates",
                    "detail": (
                        f"O canal acumulou {cr_used} rejeições consecutivas nos Gates (50% ou mais do limite de {cr_limit}). "
                        f"A produção autônoma será bloqueada se atingir {cr_limit} rejeições."
                    ),
                    "since": None,
                    "evidence": {"task_ids": [], "event_ids": []},
                    "suggested_action": "Revisar logs de reprovação e ajustes de prompt/mídia antes que o circuit breaker dispare.",
                })

        # -------------------------------------------------------------
        # Detector 12: GLOBAL_COST_GUARD (warning >= 80% de qualquer teto global; critical >= 100%)
        # -------------------------------------------------------------
        att_ratio = (global_att_used / global_att_cap) if (global_att_used is not None and global_att_cap and global_att_cap > 0) else 0.0
        gen_ratio = (global_gen_used / global_gen_cap) if (global_gen_used is not None and global_gen_cap and global_gen_cap > 0) else 0.0
        max_global_ratio = max(att_ratio, gen_ratio)

        if max_global_ratio >= 1.0:
            diagnoses.append({
                "code": CODE_GLOBAL_COST_GUARD,
                "severity": SEVERITY_CRITICAL,
                "title": "Global Cost Guard: teto global de custo atingido (100%)",
                "detail": (
                    f"A fábrica atingiu o teto global de produção autônoma "
                    f"(Tentativas: {global_att_used}/{global_att_cap}, Aprovações: {global_gen_used}/{global_gen_cap}). "
                    f"A produção autônoma de todos os canais está bloqueada por proteção de custos."
                ),
                "since": None,
                "evidence": {"task_ids": [], "event_ids": []},
                "suggested_action": "Aguardar a liberação de cotas na janela de 24h ou ajustar os tetos globais da fábrica.",
            })
        elif max_global_ratio >= 0.8:
            which_teto = "tentativas" if att_ratio >= gen_ratio else "aprovações"
            used_val = global_att_used if att_ratio >= gen_ratio else global_gen_used
            cap_val = global_att_cap if att_ratio >= gen_ratio else global_gen_cap
            diagnoses.append({
                "code": CODE_GLOBAL_COST_GUARD,
                "severity": SEVERITY_WARNING,
                "title": f"Global Cost Guard: consumo global próximo do teto ({max_global_ratio:.0%})",
                "detail": (
                    f"O consumo global da fábrica atingiu {max_global_ratio:.0%} do teto de {which_teto} "
                    f"({used_val}/{cap_val} em 24h). A produção será interrompida preventivamente ao atingir 100%."
                ),
                "since": None,
                "evidence": {"task_ids": [], "event_ids": []},
                "suggested_action": "Monitorar o volume global de produção para evitar bloqueio preventivo.",
            })

        # -------------------------------------------------------------
        # Detector 13: GENERATION_FAILURE_STREAK (warning)
        # 3+ eventos generation_failed seguidos do canal; texto cru da falha mais recente
        # -------------------------------------------------------------
        failed_streak = 0
        most_recent_failed_msg = None
        failed_ev_ids = []
        failed_task_ids = []
        for e in sorted(chan_events, key=lambda x: x["timestamp"], reverse=True):
            etype = e.get("event_type")
            if etype == "generation_failed":
                failed_streak += 1
                if not most_recent_failed_msg:
                    most_recent_failed_msg = e.get("message")
                if "id" in e:
                    failed_ev_ids.append(e["id"])
                if e.get("task_id"):
                    failed_task_ids.append(e["task_id"])
            elif etype in ("generation_approved", "task_approved_and_scheduled", "task_gate_rejected", "generation_interrupted_recovery"):
                break

        if failed_streak >= 3:
            diagnoses.append({
                "code": CODE_GENERATION_FAILURE_STREAK,
                "severity": SEVERITY_WARNING,
                "title": f"Sequência de {failed_streak} falhas consecutivas de geração",
                "detail": (
                    f"O canal registrou {failed_streak} falhas técnicas consecutivas na etapa de geração. "
                    f"Mensagem da falha mais recente: '{most_recent_failed_msg or 'Erro técnico na geração'}'."
                ),
                "since": None,
                "evidence": {
                    "task_ids": failed_task_ids,
                    "event_ids": failed_ev_ids,
                },
                "suggested_action": "Inspecionar os logs de erro técnico e verificar recursos locais como GPU, disco e dependências de render.",
            })

        # Ordena diagnósticos por severidade (critical > warning > info)
        diagnoses.sort(key=lambda d: SEVERITY_WEIGHT.get(d.get("severity", SEVERITY_INFO), 99))

        # -------------------------------------------------------------
        # Determinação do Status Geral do Canal via Função Canônica Única
        # -------------------------------------------------------------
        c_auto_state = str(auto_settings.get("autonomous_state" if pid in ("default", profile_manager.DEFAULT_PROFILE_ID) else f"autonomous_state:{pid}", "")).lower().strip()
        c_auto_msg = str(auto_settings.get("autonomous_message" if pid in ("default", profile_manager.DEFAULT_PROFILE_ID) else f"autonomous_message:{pid}", "")).strip()
        c_auto_err = str(auto_settings.get("autonomous_last_error" if pid in ("default", profile_manager.DEFAULT_PROFILE_ID) else f"autonomous_last_error:{pid}", "")).strip()

        # Falhas nas últimas 24h
        failed_count_24h = counts_interrupted + sum(1 for e in chan_events if e.get("event_type") == "generation_failed")

        status_eval = evaluate_canonical_channel_status(
            is_factory_paused=is_factory_paused,
            factory_state=factory_state,
            is_channel_active=is_channel_active,
            autonomous_enabled=bool(autonomous_enabled),
            auto_state=c_auto_state,
            auto_message=c_auto_msg,
            auto_last_error=c_auto_err,
            ready_stock=stock_count if stock_status != STATUS_UNKNOWN else None,
            target_stock=target_stock if target_stock is not None else 3,
            consec_rejections=cr_used or 0,
            max_rejections=cr_limit if cr_limit is not None else 10,
            approved_24h=app_used or counts_approved or 0,
            max_generations_24h=app_cap or 0,
            failed_24h=failed_count_24h,
            diagnoses=diagnoses,
        )
        channel_status = status_eval["status"]
        channel_status_label = status_eval.get("label", channel_status.capitalize())
        channel_reason_code = status_eval.get("reason_code", "")
        channel_reason = status_eval.get("reason", "")

        # Item 4: Remove o diagnóstico info redundante quando a causa do Pausado for AUTONOMOUS_DISABLED
        if channel_status == STATUS_PAUSED and channel_reason_code == "AUTONOMOUS_DISABLED":
            diagnoses = [d for d in diagnoses if d.get("code") != CODE_AUTONOMOUS_DISABLED]

        formatted_recent = [
            {
                "task_id": g["task_id"],
                "started_at": _format_iso_utc(g["started_at"]),
                "outcome": g["outcome"],
                "reason": g["reason"],
                "topic": g["topic"],
            }
            for g in recent_10
        ]

        prof_ctx = profile_manager.get_generation_profile_context(profile_id=pid, db_path=effective_db)
        fmt = prof_ctx.get("video_format") or prof_ctx.get("content_style") or "traditional"

        channels_output.append({
            "profile_id": pid,
            "name": pname,
            "format": fmt,
            "status": channel_status,
            "status_label": channel_status_label,
            "reason_code": channel_reason_code,
            "reason": channel_reason,
            "last_generation_at": _format_iso_utc(last_gen_at),
            "last_outcome": last_outcome,
            "counts_24h": {
                "started": counts_started,
                "approved": counts_approved,
                "rejected": counts_rejected,
                "interrupted": counts_interrupted,
            },
            "ready_stock": {
                "count": stock_count,
                "target": target_stock,
                "status": stock_status,
            },
            "limits": channel_limits,
            "recent_generations": formatted_recent,
            "diagnoses": diagnoses,
            "warnings": channel_warnings,
        })

    # -----------------------------------------------------------------
    # Processamento de Eventos sem Canal (unassigned)
    # Exposto à parte (não é canal, não entra nos totais da frota)
    # -----------------------------------------------------------------
    unassigned_info: Optional[Dict[str, Any]] = None
    u_events = events_by_channel.get("unassigned", [])
    if u_events and not clean_filter_pid:
        u_diagnoses: List[Dict[str, Any]] = []

        # Agrupa eventos de tarefas não atribuídas
        u_task_events: Dict[str, List[Dict[str, Any]]] = {}
        for ev in u_events:
            t_id = ev.get("task_id")
            if t_id:
                u_task_events.setdefault(t_id, []).append(ev)

        # Detectores de tarefas presas / falsas interrupções em tarefas sem canal
        for tid, t_evs in u_task_events.items():
            final_vid = scheduler.get_task_final_video(tid, task_base_dir=task_base_dir)
            has_final_vid = bool(final_vid and os.path.isfile(final_vid) and os.path.getsize(final_vid) > 0)
            safety_record = safety_map.get(tid)
            has_safety_pass = bool(safety_record and safety_record.get("safety_status") == const.SAFETY_STATUS_PASS)

            has_score = tid in quality_map
            is_scheduled = tid in scheduled_tasks
            is_ready = False

            if has_final_vid and has_safety_pass and not has_score and not is_scheduled and not is_ready:
                last_ev_time = max((_parse_iso_to_utc(e["timestamp"]) for e in t_evs), default=now_utc)
                mins_stuck = max(0.0, (now_utc - last_ev_time).total_seconds() / 60.0)
                if mins_stuck >= DEFAULT_STUCK_AFTER_RENDER_MINUTES:
                    u_diagnoses.append({
                        "code": CODE_TASK_STUCK_AFTER_RENDER,
                        "severity": SEVERITY_CRITICAL,
                        "title": f"Tarefa sem canal {tid} concluída e aprovada, mas não pontuada/agendada",
                        "detail": (
                            f"O vídeo final da tarefa {tid} foi gerado e aprovado no Safety Gate há {mins_stuck:.0f} minutos, "
                            f"mas a tarefa não possui canal associado e não avançou para pontuação de qualidade."
                        ),
                        "since": _format_iso_utc(last_ev_time),
                        "evidence": {"task_ids": [tid], "event_ids": [e["id"] for e in t_evs if "id" in e]},
                        "suggested_action": "Atribuir um canal à tarefa ou recuperar via painel operacional.",
                    })

            has_interruption = next((e for e in reversed(t_evs) if e["event_type"] == "generation_interrupted_recovery"), None)
            if has_interruption and has_final_vid:
                u_diagnoses.append({
                    "code": CODE_FALSE_INTERRUPTION_LIKELY,
                    "severity": SEVERITY_CRITICAL,
                    "title": f"Falso positivo de interrupção na tarefa sem canal {tid}",
                    "detail": f"A tarefa {tid} foi registrada como interrompida, porém o arquivo de vídeo final já existe no disco.",
                    "since": has_interruption.get("timestamp"),
                    "evidence": {"task_ids": [tid], "event_ids": [has_interruption.get("id")] if "id" in has_interruption else []},
                    "suggested_action": "Reaproveitar o vídeo renderizado e vincular a um canal.",
                })

        # Detector de tópico inválido em eventos unassigned
        for ev in u_events:
            if ev.get("event_type") == "generation_started":
                raw_topic = _extract_topic_from_event(ev.get("message", ""), ev.get("metadata"))
                if raw_topic and any(p in raw_topic.lower() for p in ("errno", "getaddrinfo", "failed to establish a new connection", "traceback")):
                    u_diagnoses.append({
                        "code": CODE_INVALID_TOPIC,
                        "severity": SEVERITY_CRITICAL,
                        "title": "Geração iniciada com mensagem de erro de rede como tema (sem canal)",
                        "detail": f"O tema da geração contém erro técnico de rede: '{raw_topic}'.",
                        "since": ev.get("timestamp"),
                        "evidence": {"task_ids": [ev.get("task_id")] if ev.get("task_id") else [], "event_ids": [ev.get("id")] if "id" in ev else []},
                        "suggested_action": "Verificar conectividade com provedores externos de LLM/temas.",
                    })

        u_diagnoses.sort(key=lambda d: SEVERITY_WEIGHT.get(d.get("severity", SEVERITY_INFO), 99))

        unassigned_info = {
            "count": len(u_events),
            "diagnoses": u_diagnoses,
        }

    overview: Dict[str, Any] = {
        "factory": {
            "state": factory_state,
            "is_paused": is_factory_paused,
            "message": factory_msg,
            "last_error": factory_error,
            "primary_instance": primary_inst,
            "limits": global_limits,
        },
        "limits": global_limits,
        "channels": channels_output,
    }
    if unassigned_info is not None:
        overview["unassigned_events"] = unassigned_info

    return overview
