"""Production Overview Service (Web UI V2 - Missão P1).

Fornece visão consolidada e em tempo real da produção para a Web UI V2:
- Estoque de vídeos prontos canônico (get_canonical_ready_stock)
- Fila de agendamento (scheduled_posts)
- Tarefas recentes das últimas 24h (recent_runs com status SUCCESS, FAILED, REJECTED, RUNNING)
- Totais gerais agregados
- Filtros por profile_id e limit_per_section
- Cache curto configurável (10s) para garantir performance sub-segundo
"""
from __future__ import annotations

import copy
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from app.models import const
from app.services import (
    autonomous_production,
    operator_console,
    profile_manager,
    scheduler,
)
from app.services import state as sm

_cache_lock = threading.Lock()
_overview_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
CACHE_TTL_SECONDS = 10.0


def clear_production_overview_cache() -> None:
    """Limpa o cache em memória do overview de produção."""
    with _cache_lock:
        _overview_cache.clear()


def _get_ro_connection(target_path: str) -> sqlite3.Connection:
    """Abre conexão SQLite em modo somente leitura (mode=ro) com fallback seguro."""
    abs_path = os.path.abspath(target_path)
    if os.path.isfile(abs_path):
        try:
            conn = sqlite3.connect(f"file:{abs_path}?mode=ro", uri=True, timeout=5.0)
            conn.row_factory = sqlite3.Row
            return conn
        except Exception:
            pass
    conn = sqlite3.connect(abs_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


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


def _calculate_age_hours(created_at_str: Optional[str], now_utc: datetime) -> Optional[float]:
    """Calcula a idade em horas a partir da data de criação."""
    dt = _parse_iso_to_utc(created_at_str)
    if dt is None:
        return None
    diff_sec = (now_utc - dt).total_seconds()
    return round(max(0.0, diff_sec / 3600.0), 1)


def get_production_overview(
    profile_id: Optional[str] = None,
    limit_per_section: int = 20,
    db_path: Optional[str] = None,
    use_cache: bool = True,
) -> Dict[str, Any]:
    """Retorna o resumo operacional de produção da V2 com estoque, agendados e runs recentes."""
    effective_limit = max(1, min(int(limit_per_section), 100))
    clean_profile_id = str(profile_id).strip() if profile_id else None
    effective_db = scheduler.get_db_path(db_path)

    # 1. Verificação de Cache
    cache_key = f"{clean_profile_id}:{effective_limit}:{effective_db}"
    if use_cache:
        with _cache_lock:
            cached_entry = _overview_cache.get(cache_key)
            if cached_entry:
                cached_time, cached_data = cached_entry
                if time.monotonic() - cached_time < CACHE_TTL_SECONDS:
                    return copy.deepcopy(cached_data)

    now_utc = datetime.now(timezone.utc)
    h24_ago_dt = now_utc - timedelta(hours=24)
    h24_ago_iso = h24_ago_dt.isoformat()

    conn = _get_ro_connection(effective_db)
    try:
        existing_tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table';"
            ).fetchall()
        }

        empty_response = {
            "totals": {
                "total_ready": 0,
                "total_scheduled": 0,
                "total_runs_24h": 0,
                "ready_stock": 0,
                "scheduled": 0,
                "success_24h": 0,
                "failed_24h": 0,
                "rejected_24h": 0,
                "total_ready_stock": 0,
                "total_scheduled": 0,
                "total_success_24h": 0,
                "total_failed_24h": 0,
                "total_rejected_24h": 0,
            },
            "channels": [],
        }

        if "content_profiles" not in existing_tables:
            return empty_response

        # 2. Carrega Perfis
        if clean_profile_id:
            profile_rows = conn.execute(
                """
                SELECT id, name, slug, niche, language, region, default_preset,
                       growth_mode, is_active, settings_json, created_at, updated_at
                FROM content_profiles
                WHERE id = ?
                ORDER BY created_at ASC;
                """,
                (clean_profile_id,),
            ).fetchall()
        else:
            profile_rows = conn.execute(
                """
                SELECT id, name, slug, niche, language, region, default_preset,
                       growth_mode, is_active, settings_json, created_at, updated_at
                FROM content_profiles
                ORDER BY created_at ASC;
                """
            ).fetchall()

        if not profile_rows:
            return empty_response

        profiles = [dict(r) for r in profile_rows]

        # 3. Mapeamento de Canais de Publicação
        channels_by_prof: Dict[str, List[Dict[str, Any]]] = {}
        if "publishing_channels" in existing_tables:
            chan_rows = conn.execute(
                """
                SELECT id, profile_id, platform, display_name, is_enabled
                FROM publishing_channels
                WHERE is_enabled = 1;
                """
            ).fetchall()
            for cr in chan_rows:
                c_pid = cr["profile_id"]
                if c_pid:
                    channels_by_prof.setdefault(c_pid, []).append(dict(cr))

        # 4. Dados para resolução de Scheduled Posts
        scheduled_posts_by_prof: Dict[str, List[Dict[str, Any]]] = {}
        if "scheduled_posts" in existing_tables:
            s_rows = conn.execute(
                """
                SELECT id, task_id, scheduled_at, status, created_at, profile_id
                FROM scheduled_posts
                WHERE status IN ('planned', 'ready')
                ORDER BY scheduled_at ASC;
                """
            ).fetchall()
            for sr in s_rows:
                s_pid = sr["profile_id"] or profile_manager.DEFAULT_PROFILE_ID
                scheduled_posts_by_prof.setdefault(s_pid, []).append(dict(sr))

        # 5. Dados para Recent Runs das últimas 24h
        # 5.1 task_profiles
        task_prof_map: Dict[str, str] = {}
        task_created_map: Dict[str, str] = {}
        if "task_profiles" in existing_tables:
            tp_rows = conn.execute("SELECT task_id, profile_id, created_at FROM task_profiles;").fetchall()
            for tpr in tp_rows:
                task_prof_map[tpr["task_id"]] = tpr["profile_id"] or profile_manager.DEFAULT_PROFILE_ID
                if tpr["created_at"]:
                    task_created_map[tpr["task_id"]] = tpr["created_at"]

        # 5.2 monetization_safety recente
        safety_map: Dict[str, Dict[str, Any]] = {}
        if "monetization_safety" in existing_tables:
            ms_cols = {r[1] for r in conn.execute("PRAGMA table_info(monetization_safety);").fetchall()}
            sel_reasons = "safety_reasons" if "safety_reasons" in ms_cols else ("gate_reason" if "gate_reason" in ms_cols else "NULL AS safety_reasons")
            ms_rows = conn.execute(
                f"""
                SELECT task_id, safety_status, {sel_reasons}, checked_at
                FROM monetization_safety
                WHERE checked_at >= ? OR checked_at IS NULL;
                """,
                (h24_ago_iso,),
            ).fetchall()
            for msr in ms_rows:
                safety_map[msr["task_id"]] = dict(msr)

        # 5.3 quality scores recente
        quality_map: Dict[str, Dict[str, Any]] = {}
        if "content_quality_scores" in existing_tables:
            qs_rows = conn.execute(
                """
                SELECT task_id, quality_score, quality_label, created_at
                FROM content_quality_scores
                WHERE created_at >= ? OR created_at IS NULL
                ORDER BY created_at DESC;
                """,
                (h24_ago_iso,),
            ).fetchall()
            for qsr in qs_rows:
                if qsr["task_id"] not in quality_map:
                    quality_map[qsr["task_id"]] = dict(qsr)

        # 5.4 operational_events recente
        events_by_task: Dict[str, List[Dict[str, Any]]] = {}
        if "operational_events" in existing_tables:
            oe_rows = conn.execute(
                """
                SELECT task_id, event_type, timestamp, metadata_json
                FROM operational_events
                WHERE timestamp >= ?
                ORDER BY timestamp ASC;
                """,
                (h24_ago_iso,),
            ).fetchall()
            for oer in oe_rows:
                tid = oer["task_id"]
                if tid:
                    events_by_task.setdefault(tid, []).append(dict(oer))

        # 5.5 tasks table se existir
        tasks_table_data: Dict[str, Dict[str, Any]] = {}
        if "tasks" in existing_tables:
            try:
                t_rows = conn.execute(
                    """
                    SELECT * FROM tasks
                    WHERE created_at >= ? OR updated_at >= ?;
                    """,
                    (h24_ago_iso, h24_ago_iso),
                ).fetchall()
                for tr in t_rows:
                    tasks_table_data[tr["task_id"]] = dict(tr)
            except Exception:
                pass

    finally:
        conn.close()

    # Identifica tarefas ativas / em processamento
    active_running_tids = set()
    try:
        from app.services import webui_task
        active_running_tids.update(webui_task.get_active_task_ids())
    except Exception:
        pass

    # Tarefas em memória
    memory_tasks = {}
    state_obj = getattr(sm, "state", None)
    if state_obj and hasattr(state_obj, "_tasks") and isinstance(state_obj._tasks, dict):
        with getattr(state_obj, "_lock", threading.Lock()):
            memory_tasks = {k: copy.deepcopy(v) for k, v in state_obj._tasks.items()}

    # 6. Construção dos dados por canal
    channels_output = []
    tot_ready_stock = 0
    tot_scheduled = 0
    tot_runs_24h = 0
    tot_success_24h = 0
    tot_failed_24h = 0
    tot_rejected_24h = 0

    for prof in profiles:
        pid = prof["id"]
        pname = prof["name"]

        # Canal de publicação primário
        p_chans = channels_by_prof.get(pid, [])
        primary_ch = p_chans[0] if p_chans else None
        cname = (
            primary_ch.get("channel_name")
            or primary_ch.get("display_name")
            if primary_ch
            else pname
        )

        # Contexto e formato editorial
        prof_ctx = profile_manager.get_generation_profile_context(profile_id=pid, db_path=effective_db)
        video_format = prof_ctx.get("video_format") or prof_ctx.get("content_style") or "traditional"

        # -------------------------------------------------------------
        # A. Ready Stock Canônico
        # -------------------------------------------------------------
        try:
            stock_info = operator_console.get_canonical_ready_stock(
                profile_id=pid,
                db_path=effective_db,
            )
        except Exception as exc:
            logger.warning(f"[PRODUCTION_OVERVIEW] Erro ao obter estoque canônico para perfil {pid}: {exc}")
            stock_info = {"total_ready": 0, "youtube_ready": []}

        stock_total = int(stock_info.get("total_ready", 0))
        raw_ready_items = stock_info.get("youtube_ready", [])

        ready_stock_items = []
        for item in raw_ready_items:
            t_id = item.get("task_id")
            topic = item.get("video_subject") or item.get("topic") or None

            q_score = item.get("quality_score")
            try:
                q_score = float(q_score) if q_score is not None else None
            except (ValueError, TypeError):
                q_score = None

            safety_status = item.get("safety_status") or None
            copyright_status = (
                item.get("copyright_provenance_gate")
                or item.get("copyright_status")
                or "PASS"
            )
            gate_status = item.get("gate_status") or ("APPROVED" if safety_status == "PASS" else None)
            created_at = item.get("created_at") or None
            age_hours = _calculate_age_hours(created_at, now_utc)

            duration = (
                item.get("video_duration")
                or item.get("duration")
                or item.get("video_duration_sec")
            )
            try:
                duration = float(duration) if duration is not None else None
            except (ValueError, TypeError):
                duration = None

            ready_stock_items.append({
                "task_id": t_id,
                "topic": topic,
                "quality_score": q_score,
                "safety_status": safety_status,
                "copyright_status": copyright_status,
                "gate_status": gate_status,
                "created_at": created_at,
                "age_hours": age_hours,
                "duration": duration,
            })

        ready_stock_section = {
            "total": stock_total,
            "items": ready_stock_items[:effective_limit],
        }

        # -------------------------------------------------------------
        # B. Scheduled Posts
        # -------------------------------------------------------------
        sched_rows = scheduled_posts_by_prof.get(pid, [])
        sched_items = []
        for sr in sched_rows:
            sr_tid = sr.get("task_id")
            sr_topic = None

            # Busca tópico em memória ou banco
            mem_t = memory_tasks.get(sr_tid)
            if mem_t:
                sr_topic = mem_t.get("video_subject") or mem_t.get("topic")
            if not sr_topic and sr_tid in tasks_table_data:
                sr_topic = tasks_table_data[sr_tid].get("video_subject") or tasks_table_data[sr_tid].get("topic")

            sched_items.append({
                "post_id": sr["id"],
                "task_id": sr_tid,
                "topic": sr_topic or None,
                "scheduled_at": sr["scheduled_at"],
                "status": sr["status"],
            })

        scheduled_section = {
            "total": len(sched_rows),
            "items": sched_items[:effective_limit],
        }

        # -------------------------------------------------------------
        # C. Recent Runs (últimas 24h)
        # -------------------------------------------------------------
        # Reúne task_ids candidatos pertencentes a este perfil nas últimas 24h
        candidate_tids = set()

        for tid, t_pid in task_prof_map.items():
            is_match = (t_pid == pid) if pid not in ("default", profile_manager.DEFAULT_PROFILE_ID) else (t_pid in ("default", profile_manager.DEFAULT_PROFILE_ID))
            if is_match:
                c_time = task_created_map.get(tid)
                if c_time and c_time >= h24_ago_iso:
                    candidate_tids.add(tid)

        for tid, t_dict in memory_tasks.items():
            t_pid = t_dict.get("profile_id") or task_prof_map.get(tid) or "default"
            is_match = (t_pid == pid) if pid not in ("default", profile_manager.DEFAULT_PROFILE_ID) else (t_pid in ("default", profile_manager.DEFAULT_PROFILE_ID))
            if is_match:
                t_state = t_dict.get("state")
                c_time = t_dict.get("created_at") or task_created_map.get(tid)
                u_time = t_dict.get("updated_at") or t_dict.get("finished_at")
                if t_state in (const.TASK_STATE_PROCESSING, const.TASK_STATE_PENDING) or tid in active_running_tids:
                    candidate_tids.add(tid)
                elif (c_time and c_time >= h24_ago_iso) or (u_time and u_time >= h24_ago_iso):
                    candidate_tids.add(tid)

        for tid, t_dict in tasks_table_data.items():
            t_pid = t_dict.get("profile_id") or task_prof_map.get(tid) or "default"
            is_match = (t_pid == pid) if pid not in ("default", profile_manager.DEFAULT_PROFILE_ID) else (t_pid in ("default", profile_manager.DEFAULT_PROFILE_ID))
            if is_match:
                candidate_tids.add(tid)

        # Monta os registros consolidados de runs
        runs_list = []
        for tid in candidate_tids:
            mem_t = memory_tasks.get(tid) or {}
            sql_t = tasks_table_data.get(tid) or {}
            ms_entry = safety_map.get(tid) or {}
            qs_entry = quality_map.get(tid) or {}
            t_events = events_by_task.get(tid) or []

            topic = (
                mem_t.get("video_subject")
                or mem_t.get("topic")
                or sql_t.get("video_subject")
                or sql_t.get("topic")
                or None
            )

            created_at = (
                mem_t.get("created_at")
                or sql_t.get("created_at")
                or task_created_map.get(tid)
                or (t_events[0]["timestamp"] if t_events else None)
            )

            finished_at = (
                mem_t.get("finished_at")
                or sql_t.get("finished_at")
                or mem_t.get("updated_at")
                or sql_t.get("updated_at")
                or ms_entry.get("checked_at")
                or qs_entry.get("created_at")
                or None
            )

            # Classificação estrita de status: SUCCESS, FAILED, REJECTED, RUNNING
            t_state = mem_t.get("state")
            if t_state is None and "state" in sql_t:
                t_state = sql_t["state"]

            is_active = (tid in active_running_tids) or (t_state in (const.TASK_STATE_PROCESSING, const.TASK_STATE_PENDING))
            has_failed_event = any(e.get("event_type") == "generation_failed" for e in t_events)
            has_reject_event = any(e.get("event_type") == "task_gate_rejected" for e in t_events)

            error_msg = mem_t.get("error") or sql_t.get("error") or None
            safety_status = ms_entry.get("safety_status") or mem_t.get("safety_status")
            gate_status = mem_t.get("gate_status") or ("APPROVED" if (safety_status and str(safety_status).upper() == "PASS") else ("REJECTED" if (safety_status and str(safety_status).upper() == "FAIL") else None))
            gate_reason = (
                ms_entry.get("safety_reasons")
                or ms_entry.get("gate_reason")
                or mem_t.get("gate_reason")
                or sql_t.get("gate_reason")
                or None
            )
            failure_stage = (
                mem_t.get("failed_stage")
                or mem_t.get("failure_stage")
                or sql_t.get("failed_stage")
                or sql_t.get("failure_stage")
                or mem_t.get("stage")
                or None
            )

            if is_active:
                status = "RUNNING"
                failure_stage = None
                gate_reason = None
                error_msg = None
                finished_at = None
            elif t_state == const.TASK_STATE_FAILED or error_msg or has_failed_event:
                status = "FAILED"
            elif (
                has_reject_event
                or gate_status == "REJECTED"
                or (safety_status and str(safety_status).upper() == "FAIL")
            ):
                status = "REJECTED"
                if not failure_stage:
                    if safety_status and str(safety_status).upper() == "FAIL":
                        failure_stage = "SAFETY"
                    else:
                        failure_stage = "QUALITY"
            elif t_state == const.TASK_STATE_COMPLETE:
                status = "SUCCESS"
                failure_stage = None
                gate_reason = None
                error_msg = None
            else:
                # Se não há estado explícito mas tem erro -> FAILED, senão SUCCESS
                status = "FAILED" if error_msg else "SUCCESS"

            runs_list.append({
                "task_id": tid,
                "topic": topic,
                "status": status,
                "failure_stage": failure_stage,
                "gate_reason": gate_reason,
                "error": error_msg,
                "created_at": created_at,
                "finished_at": finished_at,
            })

        # Ordenação cronológica reversa (mais recente primeiro)
        def _sort_key(item: Dict[str, Any]) -> str:
            return item.get("created_at") or item.get("finished_at") or ""

        runs_list.sort(key=_sort_key, reverse=True)

        recent_runs_section = {
            "total": len(runs_list),
            "items": runs_list[:effective_limit],
        }

        # Acumula totais gerais
        tot_ready_stock += stock_total
        tot_scheduled += len(sched_rows)
        tot_runs_24h += len(runs_list)
        for r in runs_list:
            if r["status"] == "SUCCESS":
                tot_success_24h += 1
            elif r["status"] == "FAILED":
                tot_failed_24h += 1
            elif r["status"] == "REJECTED":
                tot_rejected_24h += 1

        channels_output.append({
            "profile_id": pid,
            "profile_name": pname,
            "channel_name": cname,
            "video_format": video_format,
            "ready_stock": ready_stock_section,
            "scheduled": scheduled_section,
            "recent_runs": recent_runs_section,
        })

    response_data = {
        "totals": {
            "total_ready": tot_ready_stock,
            "total_scheduled": tot_scheduled,
            "total_runs_24h": tot_runs_24h,
            "ready_stock": tot_ready_stock,
            "scheduled": tot_scheduled,
            "success_24h": tot_success_24h,
            "failed_24h": tot_failed_24h,
            "rejected_24h": tot_rejected_24h,
            "total_ready_stock": tot_ready_stock,
            "total_scheduled": tot_scheduled,
            "total_success_24h": tot_success_24h,
            "total_failed_24h": tot_failed_24h,
            "total_rejected_24h": tot_rejected_24h,
        },
        "channels": channels_output,
    }

    if use_cache:
        with _cache_lock:
            _overview_cache[cache_key] = (time.monotonic(), copy.deepcopy(response_data))

    return response_data
