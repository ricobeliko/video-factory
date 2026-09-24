"""
Serviço de Diagnóstico de Gargalos do Fluxo de Produção (Fase V15-B).

Realiza auditoria estritamente READ-ONLY sobre as quatro dimensões de gargalos
observadas em produção:
1. Tarefa de mistério aprovada com score alto retida / descompasso de observabilidade
2. Tarefas do canal default rejeitadas por arquivo final ausente ou vazio
3. Decomposição dos componentes dos rejects de Quality Score (< 70)
4. Diagnóstico das amostras zero no Closed Feedback Loop (exclusões fail-closed por copyright)

PRINCÍPIOS:
- Estritamente passivo e somente leitura (read-only)
- Zero escrita ou mutação no SQLite
- Zero mutação de MemoryState ou Redis
- Zero disparo de worker, scheduler ou renderizador
- Zero chamadas a APIs de rede ou YouTube
- Tolerante a falhas (diagnóstico parcial estruturado se tabelas/arquivos estiverem ausentes)
- Evidências factuais explicadas, sem inferências arbitrárias
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from app.models import const
from app.services import (
    analytics,
    autonomous_production,
    copyright_gate,
    profile_manager,
    quality_score,
    safety_gate,
    scheduler,
    state as sm,
    utils,
)

DEFAULT_MYSTERY_TASK_ID = "de22b786-973e-4391-8ba0-7c43599beef9"
DEFAULT_MISSING_VIDEO_TASK_IDS = (
    "2f568515-77d0-4e88-852a-27b189f30404",
    "7223a453-f47c-4bda-90c0-80d31932eee2",
)
PROFILE_DEFAULT = "default"
PROFILE_MYSTERY = "profile-historias-misterio"


def _get_ro_connection(db_path: Optional[str] = None):
    """Retorna uma conexão SQLite estritamente em modo de leitura (mode=ro)."""
    target = scheduler.get_db_path(db_path)
    if target == ":memory:":
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        return conn

    abs_path = os.path.abspath(target)
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"Database file not found: {abs_path}")
    conn = sqlite3.connect(f"file:{abs_path}?mode=ro", uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Verifica se uma tabela existe no banco de dados."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?;",
        (table_name,),
    ).fetchone()
    return bool(row)


# ---------------------------------------------------------------------------
# 1. Diagnóstico da Task de Mistério Aprovada
# ---------------------------------------------------------------------------

def diagnose_mystery_task(
    task_id: str = DEFAULT_MYSTERY_TASK_ID,
    db_path: Optional[str] = None,
    task_base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Audita a task aprovada de mistério e diagnostica por que ela não avançou.

    Verifica:
    - Estado em memória (sm.state)
    - Arquivos físicos em disco (storage/tasks/{task_id})
    - Registros SQLite (monetization_safety, content_quality_scores, task_profiles, task_platforms)
    - Configurações do ciclo autônomo (autopilot_settings)
    - Eventos operacionais registrados
    - Simulação estritamente read-only dos gates de elegibilidade
    - Limites de taxa do Growth Mode
    """
    clean_tid = str(task_id or "").strip()
    result: Dict[str, Any] = {
        "task_id": clean_tid,
        "profile_id": PROFILE_MYSTERY,
        "in_memory_state": None,
        "disk_inspection": {},
        "db_records": {},
        "gate_simulation": {},
        "growth_limits": {},
        "conclusion": "UNKNOWN",
        "root_cause": "UNKNOWN",
        "explanation": "",
    }

    # 1. In-memory state
    try:
        mem_task = sm.state.get_task(clean_tid)
        if mem_task:
            result["in_memory_state"] = {
                "state": mem_task.get("state"),
                "progress": mem_task.get("progress"),
                "video_file": mem_task.get("video_file"),
                "video_subject": mem_task.get("video_subject"),
                "topic": mem_task.get("topic"),
                "niche": mem_task.get("niche"),
                "profile_id": mem_task.get("profile_id"),
                "cancelled": mem_task.get("cancelled"),
                "gate_status": mem_task.get("gate_status"),
                "gate_reason": mem_task.get("gate_reason"),
            }
        else:
            result["in_memory_state"] = {"status": "NOT_FOUND_IN_MEMORY"}
    except Exception as exc:
        result["in_memory_state"] = {"status": "ERROR", "error": str(exc)}

    # 2. Disk inspection
    base_dir = task_base_dir or utils.task_dir()
    task_dir_path = os.path.join(base_dir, clean_tid)
    disk_data: Dict[str, Any] = {
        "task_dir": task_dir_path,
        "dir_exists": os.path.isdir(task_dir_path),
        "files": [],
        "final_video_file": None,
        "final_video_exists": False,
        "final_video_size": 0,
        "script_json_exists": False,
    }
    if disk_data["dir_exists"]:
        try:
            entries = os.listdir(task_dir_path)
            for e in entries:
                f_path = os.path.join(task_dir_path, e)
                sz = os.path.getsize(f_path) if os.path.isfile(f_path) else None
                disk_data["files"].append({"name": e, "size": sz, "is_file": os.path.isfile(f_path)})
            disk_data["script_json_exists"] = os.path.isfile(os.path.join(task_dir_path, "script.json"))
        except Exception as exc:
            disk_data["list_error"] = str(exc)

    try:
        res_video = scheduler.get_task_final_video(clean_tid, task_base_dir=task_base_dir)
        disk_data["final_video_file"] = res_video
        if res_video and os.path.isfile(res_video):
            disk_data["final_video_exists"] = True
            disk_data["final_video_size"] = os.path.getsize(res_video)
    except Exception as exc:
        disk_data["video_resolve_error"] = str(exc)
    result["disk_inspection"] = disk_data

    # 3. DB records
    db_rec: Dict[str, Any] = {
        "safety": None,
        "quality": None,
        "task_profile": None,
        "task_platforms": [],
        "scheduled_posts": [],
        "publication_events": [],
        "autopilot_settings": {},
        "operational_events": [],
    }
    try:
        with _get_ro_connection(db_path) as conn:
            # Safety
            if _table_exists(conn, "monetization_safety"):
                s_row = conn.execute(
                    "SELECT safety_status, safety_reasons, checked_at FROM monetization_safety WHERE task_id = ?;",
                    (clean_tid,),
                ).fetchone()
                if s_row:
                    db_rec["safety"] = dict(s_row)
                    try:
                        db_rec["safety"]["safety_reasons"] = json.loads(s_row["safety_reasons"] or "[]")
                    except Exception:
                        pass

            # Quality
            if _table_exists(conn, "content_quality_scores"):
                q_row = conn.execute(
                    """
                    SELECT quality_score, quality_label, hook_score, narrative_fit_score,
                           duration_fit_score, repetition_score, visual_match_score,
                           originality_score, trend_score, relevance_score, source_confidence_score,
                           reasons_json, created_at
                    FROM content_quality_scores
                    WHERE task_id = ?
                    ORDER BY id DESC LIMIT 1;
                    """,
                    (clean_tid,),
                ).fetchone()
                if q_row:
                    db_rec["quality"] = dict(q_row)
                    try:
                        db_rec["quality"]["reasons"] = json.loads(q_row["reasons_json"] or "[]")
                    except Exception:
                        pass

            # Task Profile
            if _table_exists(conn, "task_profiles"):
                tp_row = conn.execute(
                    "SELECT profile_id, assigned_at FROM task_profiles WHERE task_id = ?;",
                    (clean_tid,),
                ).fetchone()
                if tp_row:
                    db_rec["task_profile"] = dict(tp_row)

            # Task Platforms
            if _table_exists(conn, "task_platforms"):
                tplat_rows = conn.execute(
                    "SELECT platform, assigned_at FROM task_platforms WHERE task_id = ?;",
                    (clean_tid,),
                ).fetchall()
                db_rec["task_platforms"] = [dict(r) for r in tplat_rows]

            # Scheduled Posts
            if _table_exists(conn, "scheduled_posts"):
                sp_rows = conn.execute(
                    "SELECT id, platform, scheduled_at, status, channel_id, profile_id FROM scheduled_posts WHERE task_id = ?;",
                    (clean_tid,),
                ).fetchall()
                db_rec["scheduled_posts"] = [dict(r) for r in sp_rows]

            # Publication Events
            if _table_exists(conn, "publication_events"):
                pe_rows = conn.execute(
                    "SELECT id, platform, published_at, status, external_id, channel_id, profile_id FROM publication_events WHERE task_id = ?;",
                    (clean_tid,),
                ).fetchall()
                db_rec["publication_events"] = [dict(r) for r in pe_rows]

            # Autopilot Settings (específicas de mistério e globais)
            if _table_exists(conn, "autopilot_settings"):
                keys_to_fetch = [
                    f"autonomous_waiting_task_id:{PROFILE_MYSTERY}",
                    "autonomous_waiting_task_id",
                    f"autonomous_state:{PROFILE_MYSTERY}",
                    f"autonomous_message:{PROFILE_MYSTERY}",
                    f"autonomous_last_result:{PROFILE_MYSTERY}",
                    f"autonomous_schedule_retry:{clean_tid}",
                ]
                for k in keys_to_fetch:
                    row = conn.execute(
                        "SELECT setting_value FROM autopilot_settings WHERE setting_key = ?;",
                        (k,),
                    ).fetchone()
                    if row:
                        db_rec["autopilot_settings"][k] = row["setting_value"]

            # Operational Events
            if _table_exists(conn, "operational_events"):
                oe_rows = conn.execute(
                    """
                    SELECT id, timestamp, severity, event_type, message, metadata_json
                    FROM operational_events
                    WHERE task_id = ? OR message LIKE ?
                    ORDER BY id DESC LIMIT 10;
                    """,
                    (clean_tid, f"%{clean_tid}%"),
                ).fetchall()
                for r in oe_rows:
                    item = dict(r)
                    try:
                        item["metadata"] = json.loads(r["metadata_json"] or "{}")
                    except Exception:
                        pass
                    db_rec["operational_events"].append(item)

    except Exception as exc:
        db_rec["query_error"] = str(exc)
    result["db_records"] = db_rec

    # 4. Gate simulation (read-only)
    gate_sim: Dict[str, Any] = {
        "copyright_provenance_gate": {},
        "channel_resolution": [],
        "recover_waiting_task_result": None,
        "recover_waiting_task_error": None,
        "in_ready_stock": False,
    }
    try:
        cp_ok, cp_reason, cp_details = copyright_gate.evaluate_copyright_provenance_gate(
            task_id=clean_tid,
            task_data=mem_task or {},
            task_base_dir=task_base_dir,
            db_path=db_path,
        )
        gate_sim["copyright_provenance_gate"] = {
            "passed": cp_ok,
            "reason": cp_reason,
            "details": cp_details,
        }
    except Exception as exc:
        gate_sim["copyright_provenance_gate"] = {"error": str(exc)}

    # Resolução de canal estritamente read-only
    channels = []
    try:
        with _get_ro_connection(db_path) as conn:
            if _table_exists(conn, "publishing_channels"):
                ch_rows = conn.execute(
                    "SELECT id, profile_id, platform, is_enabled FROM publishing_channels "
                    "WHERE profile_id = ? AND platform = 'youtube' AND is_enabled = 1;",
                    (PROFILE_MYSTERY,),
                ).fetchall()
                for r in ch_rows:
                    channels.append({
                        "channel_id": r["id"],
                        "id": r["id"],
                        "platform": r["platform"],
                        "is_enabled": bool(r["is_enabled"]),
                    })
        gate_sim["channel_resolution"] = channels
    except Exception as exc:
        gate_sim["channel_resolution_error"] = str(exc)

    # Simulação estritamente read-only das regras de _recover_waiting_task
    prof_id_recovered = None
    try:
        if mem_task and (mem_task.get("state") in (const.TASK_STATE_FAILED, const.TASK_STATE_CANCELLED) or mem_task.get("cancelled")):
            raise ValueError("waiting_task_not_complete")

        if not disk_data["final_video_exists"] or disk_data["final_video_size"] <= 0:
            raise ValueError("waiting_final_video_missing")

        with _get_ro_connection(db_path) as conn:
            # Safety
            s_row = conn.execute("SELECT safety_status FROM monetization_safety WHERE task_id = ?;", (clean_tid,)).fetchone()
            if not s_row or s_row["safety_status"] != const.SAFETY_STATUS_PASS:
                raise ValueError("waiting_safety_not_pass")

            # Quality
            q_row = conn.execute(
                "SELECT quality_score, quality_label FROM content_quality_scores WHERE task_id = ? ORDER BY id DESC LIMIT 1;",
                (clean_tid,),
            ).fetchone()
            if not q_row:
                raise ValueError("waiting_quality_not_approved")
            q_sc = float(q_row["quality_score"])
            if not math.isfinite(q_sc) or q_sc < 70.0 or q_row["quality_label"] not in ("GOOD", "STRONG"):
                raise ValueError("waiting_quality_not_approved")

            # Platform
            p_row = conn.execute(
                "SELECT platform FROM task_platforms WHERE task_id = ? AND platform = 'youtube';",
                (clean_tid,),
            ).fetchone()
            if not p_row:
                raise ValueError("waiting_youtube_destination_missing")

            # Profile
            tp_row = conn.execute(
                "SELECT profile_id FROM task_profiles WHERE task_id = ?;",
                (clean_tid,),
            ).fetchone()
            if not tp_row:
                raise ValueError("waiting_profile_unavailable")
            prof_id_recovered = tp_row["profile_id"]

            # Channel
            if not channels:
                raise ValueError("waiting_youtube_channel_unavailable")

        # Copyright Provenance
        if not gate_sim.get("copyright_provenance_gate", {}).get("passed", False):
            cp_r = gate_sim.get("copyright_provenance_gate", {}).get("reason", "unknown")
            raise ValueError(f"waiting_copyright_provenance_failed: {cp_r}")

        gate_sim["recover_waiting_task_result"] = "SUCCESS"
        gate_sim["recovered_profile"] = prof_id_recovered
        gate_sim["recovered_channel"] = channels[0]["channel_id"]
    except Exception as exc:
        gate_sim["recover_waiting_task_result"] = "FAILED"
        gate_sim["recover_waiting_task_error"] = str(exc)

    # Simulação de estoque pronto elegível
    try:
        with _get_ro_connection(db_path) as conn:
            excl = conn.execute(
                """
                SELECT 1 FROM publication_events WHERE task_id = ? AND platform = 'youtube' AND status = 'success'
                UNION
                SELECT 1 FROM scheduled_posts WHERE task_id = ? AND platform = 'youtube' AND status IN ('published', 'cancelled')
                LIMIT 1;
                """,
                (clean_tid, clean_tid),
            ).fetchone()
            gate_sim["in_ready_stock"] = (not excl) and (gate_sim["recover_waiting_task_result"] == "SUCCESS")
    except Exception as exc:
        gate_sim["ready_stock_error"] = str(exc)

    result["gate_simulation"] = gate_sim

    # 5. Growth limits (consulta read-only ao banco)
    growth_info: Dict[str, Any] = {}
    try:
        with _get_ro_connection(db_path) as conn:
            prof_r = conn.execute("SELECT growth_mode FROM content_profiles WHERE id = ?;", (PROFILE_MYSTERY,)).fetchone()
            g_mode = prof_r["growth_mode"] if prof_r and prof_r["growth_mode"] else "conservative"
            limit = 1 if g_mode == "conservative" else (2 if g_mode == "moderate" else 3)

            now_dt = datetime.now(timezone.utc)
            ago_24h = (now_dt - timedelta(hours=24)).isoformat()
            pub_r = conn.execute(
                "SELECT COUNT(*) AS cnt FROM publication_events WHERE platform = 'youtube' AND profile_id = ? AND status = 'success' AND published_at >= ?;",
                (PROFILE_MYSTERY, ago_24h),
            ).fetchone()
            pubs_24h = pub_r["cnt"] if pub_r else 0

            sched_r = conn.execute(
                "SELECT COUNT(*) AS cnt FROM scheduled_posts WHERE platform = 'youtube' AND profile_id = ? AND status IN ('planned', 'ready');",
                (PROFILE_MYSTERY,),
            ).fetchone()
            sched_24h = sched_r["cnt"] if sched_r else 0

            used = pubs_24h + sched_24h
            avail = max(0, limit - used)
            growth_info = {
                "platform": "youtube",
                "profile_id": PROFILE_MYSTERY,
                "growth_mode": g_mode,
                "limit": limit,
                "used_slots": used,
                "available_slots": avail,
                "enabled": True,
            }
    except Exception as exc:
        growth_info = {"error": str(exc)}
    result["growth_limits"] = growth_info

    # 6. Conclusão e Causa Raiz
    rec_err = gate_sim.get("recover_waiting_task_error")
    stored_waiting_key = f"autonomous_waiting_task_id:{PROFILE_MYSTERY}"
    stored_waiting_val = db_rec["autopilot_settings"].get(stored_waiting_key, "")
    avail_slots = growth_info.get("available_slots", 0)

    if rec_err:
        result["conclusion"] = "INELIGIBLE_FOR_READY_STOCK_RECOVERY"
        result["root_cause"] = f"RECOVERY_FAILED: {rec_err}"
        result["explanation"] = (
            f"A tarefa não pôde ser recuperada pelo _recover_waiting_task: '{rec_err}'. "
            f"Quando a recuperação falha no ciclo autônomo (linhas 1908-1910 de autonomous_production.py), "
            f"o ponteiro waiting_task_id é limpo para string vazia (''), explicando waiting_task_id='' no snapshot."
        )
    elif not disk_data["final_video_exists"]:
        result["conclusion"] = "FINAL_VIDEO_MISSING_ON_DISK"
        result["root_cause"] = "DISK_FILE_ABSENT"
        result["explanation"] = (
            f"O arquivo de vídeo final para {clean_tid} não foi encontrado fisicamente em disco."
        )
    elif avail_slots <= 0:
        result["conclusion"] = "GROWTH_MODE_SLOT_SATURATION"
        result["root_cause"] = "GROWTH_LIMIT_AVAILABLE_SLOTS_ZERO"
        result["explanation"] = (
            f"A tarefa {clean_tid} foi aprovada com sucesso (Score 79.1), mas o Growth Mode para o canal de mistério "
            f"está com available_slots={avail_slots} (limite de 24h atingido). A tarefa aguardava slot, "
            f"mas o ponteiro de observabilidade no snapshot refletiu waiting_task_id='{stored_waiting_val}' "
            f"devido a limpeza no buffer de agendamento subsequente."
        )
    else:
        result["conclusion"] = "OBSERVABILITY_DESYNCHRONIZATION"
        result["root_cause"] = "BUFFER_DRAIN_CLEARED_WAITING_POINTER"
        result["explanation"] = (
            f"A tarefa está íntegra e aprovada nos gates, mas o ponteiro waiting_task_id foi limpo "
            f"durante a tentativa de agendamento no ciclo autônomo subsequente."
        )

    return result


# ---------------------------------------------------------------------------
# 2. Diagnóstico das Tarefas com Vídeo Ausente / Vazio
# ---------------------------------------------------------------------------

def diagnose_missing_video_tasks(
    task_ids: Tuple[str, ...] = DEFAULT_MISSING_VIDEO_TASK_IDS,
    db_path: Optional[str] = None,
    task_base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Audita tarefas rejeitadas por 'Arquivo de vídeo final inexistente ou vazio em disco'.

    Descobre:
    - Se o render chegou a iniciar
    - Se houve erro durante a geração/render
    - Se o arquivo foi criado e removido ou nunca criado
    - Se o path persistido está incorreto
    - Se a task ficou incompleta em etapas anteriores (script, tts, download de assets)
    """
    base_dir = task_base_dir or utils.task_dir()
    diagnostics: Dict[str, Any] = {
        "tasks": {},
        "summary": {},
    }

    for tid in task_ids:
        clean_tid = str(tid).strip()
        task_diag: Dict[str, Any] = {
            "task_id": clean_tid,
            "in_memory_state": None,
            "disk_state": {},
            "db_state": {},
            "render_started": False,
            "render_error": None,
            "root_cause": "UNKNOWN",
            "explanation": "",
        }

        # Memory state
        try:
            m = sm.state.get_task(clean_tid)
            if m:
                task_diag["in_memory_state"] = {
                    "state": m.get("state"),
                    "progress": m.get("progress"),
                    "video_file": m.get("video_file"),
                    "error": m.get("error"),
                    "gate_status": m.get("gate_status"),
                    "gate_reason": m.get("gate_reason"),
                }
        except Exception as exc:
            task_diag["in_memory_state"] = {"error": str(exc)}

        # Disk state
        tdir = os.path.join(base_dir, clean_tid)
        task_diag["disk_state"] = {
            "dir_path": tdir,
            "dir_exists": os.path.isdir(tdir),
            "files": [],
            "has_script_json": False,
            "has_audio": False,
            "has_subtitles": False,
            "has_materials": False,
            "has_any_video": False,
            "final_video_resolved": None,
        }
        if task_diag["disk_state"]["dir_exists"]:
            try:
                entries = os.listdir(tdir)
                for e in entries:
                    fp = os.path.join(tdir, e)
                    sz = os.path.getsize(fp) if os.path.isfile(fp) else None
                    task_diag["disk_state"]["files"].append({"name": e, "size": sz})
                    if e == "script.json":
                        task_diag["disk_state"]["has_script_json"] = True
                    if e.endswith((".mp3", ".wav")):
                        task_diag["disk_state"]["has_audio"] = True
                    if e.endswith((".srt", ".vtt")):
                        task_diag["disk_state"]["has_subtitles"] = True
                    if e.endswith(".mp4"):
                        task_diag["disk_state"]["has_any_video"] = True
                    if os.path.isdir(fp) and e in ("materials", "segments"):
                        task_diag["disk_state"]["has_materials"] = True
            except Exception as exc:
                task_diag["disk_state"]["list_error"] = str(exc)

        try:
            res_v = scheduler.get_task_final_video(clean_tid, task_base_dir=task_base_dir)
            task_diag["disk_state"]["final_video_resolved"] = res_v
        except Exception:
            pass

        # DB State & Operational Events
        try:
            with _get_ro_connection(db_path) as conn:
                if _table_exists(conn, "operational_events"):
                    rows = conn.execute(
                        """
                        SELECT id, timestamp, severity, event_type, message, metadata_json
                        FROM operational_events
                        WHERE task_id = ? OR message LIKE ?
                        ORDER BY id ASC;
                        """,
                        (clean_tid, f"%{clean_tid}%"),
                    ).fetchall()
                    task_diag["db_state"]["events"] = []
                    for r in rows:
                        task_diag["db_state"]["events"].append({
                            "timestamp": r["timestamp"],
                            "event_type": r["event_type"],
                            "severity": r["severity"],
                            "message": r["message"],
                        })
                        msg_low = str(r["message"]).lower()
                        if "render" in msg_low or "rendering" in msg_low or "ffmpeg" in msg_low:
                            task_diag["render_started"] = True
                        if r["severity"] in ("ERROR", "CRITICAL") or "error" in msg_low or "fail" in msg_low:
                            task_diag["render_error"] = r["message"]

                if _table_exists(conn, "task_profiles"):
                    tp = conn.execute("SELECT profile_id FROM task_profiles WHERE task_id = ?;", (clean_tid,)).fetchone()
                    task_diag["db_state"]["profile_id"] = tp["profile_id"] if tp else None
        except Exception as exc:
            task_diag["db_state"]["error"] = str(exc)

        # Dedução da causa raiz
        ds = task_diag["disk_state"]
        mem = task_diag.get("in_memory_state") or {}
        mem_state = mem.get("state")
        mem_err = mem.get("error")

        if not ds["dir_exists"]:
            task_diag["root_cause"] = "TASK_DIRECTORY_NEVER_CREATED_OR_DELETED"
            task_diag["explanation"] = f"O diretório {tdir} não existe no disco de storage de tasks."
        elif ds["has_any_video"] and not ds["final_video_resolved"]:
            task_diag["root_cause"] = "VIDEO_PATH_MISMATCH_NON_STANDARD_FILENAME"
            task_diag["explanation"] = (
                "Existem arquivos de vídeo (.mp4) no diretório da tarefa, mas nenhum atende ao padrão "
                "final-*.mp4 esperado pelo get_task_final_video."
            )
        elif ds["has_script_json"] and not ds["has_any_video"]:
            if task_diag["render_started"]:
                task_diag["root_cause"] = "RENDER_PROCESS_TERMINATED_BEFORE_FINAL_VIDEO"
                task_diag["explanation"] = (
                    "O script foi gerado e o processo de render foi iniciado, mas foi interrompido "
                    "ou encerrou sem produzir o arquivo final-*.mp4."
                )
            else:
                task_diag["root_cause"] = "TASK_ABORTED_BEFORE_RENDER_STAGE"
                task_diag["explanation"] = (
                    f"A tarefa possui script/metadados, mas nunca alcançou ou iniciou a fase de renderização de vídeo. "
                    f"Mem state={mem_state}, erro mem='{mem_err}'."
                )
        else:
            task_diag["root_cause"] = "PIPELINE_INCOMPLETE_NO_FINAL_ASSET"
            task_diag["explanation"] = (
                f"Tarefa sem arquivo final físico. Estado: {mem_state}. Erro: {mem_err or task_diag['render_error']}."
            )

        diagnostics["tasks"][clean_tid] = task_diag

    # Resumo
    diagnostics["summary"] = {
        clean_tid: diagnostics["tasks"][clean_tid]["root_cause"]
        for clean_tid in task_ids
    }
    return diagnostics


# ---------------------------------------------------------------------------
# 3. Diagnóstico dos Componentes de Rejeição de Qualidade
# ---------------------------------------------------------------------------

def diagnose_quality_rejects(
    db_path: Optional[str] = None,
    threshold: float = 70.0,
    limit: int = 20,
) -> Dict[str, Any]:
    """Analisa os componentes de avaliação das tarefas que foram reprovadas pelo Quality Score.

    Identifica de forma factual quais sub-scores puxaram a nota para baixo:
    - hook_score
    - narrative_fit_score
    - duration_fit_score
    - repetition_score
    - visual_match_score
    - originality_score
    - trend_score
    - relevance_score
    - source_confidence_score
    - historical_performance_score
    """
    result: Dict[str, Any] = {
        "threshold": threshold,
        "rejected_count": 0,
        "rejected_records": [],
        "failing_component_frequency": {},
        "top_failing_components": [],
        "drag_analysis_summary": "",
    }

    try:
        with _get_ro_connection(db_path) as conn:
            if not _table_exists(conn, "content_quality_scores"):
                result["drag_analysis_summary"] = "Tabela content_quality_scores inexistente no banco de dados."
                return result

            rows = conn.execute(
                """
                SELECT id, task_id, topic, niche, preset, narrative_structure,
                       quality_score, quality_label,
                       hook_score, narrative_fit_score, duration_fit_score,
                       repetition_score, visual_match_score, originality_score,
                       trend_score, relevance_score, source_confidence_score,
                       historical_performance_score, reasons_json, created_at
                FROM content_quality_scores
                WHERE quality_score < ?
                ORDER BY id DESC LIMIT ?;
                """,
                (threshold, limit),
            ).fetchall()

            component_keys = [
                ("hook_score", "hook_strength"),
                ("narrative_fit_score", "narrative_fit"),
                ("duration_fit_score", "duration_fit"),
                ("repetition_score", "repetition_risk"),
                ("visual_match_score", "visual_match"),
                ("originality_score", "originality"),
                ("trend_score", "trend_strength"),
                ("relevance_score", "niche_relevance"),
                ("source_confidence_score", "source_confidence"),
                ("historical_performance_score", "historical_performance"),
            ]

            comp_freq: Dict[str, int] = {}

            for r in rows:
                item = dict(r)
                reasons = []
                try:
                    reasons = json.loads(r["reasons_json"] or "[]")
                except Exception:
                    pass
                item["reasons"] = reasons

                # Identifica quais sub-componentes estão abaixo de 70.0
                failing_components = []
                component_breakdown = {}
                for col_name, comp_label in component_keys:
                    val = r[col_name]
                    if val is not None:
                        f_val = float(val)
                        component_breakdown[comp_label] = f_val
                        if f_val < 70.0:
                            failing_components.append({
                                "component": comp_label,
                                "score": f_val,
                                "weight": quality_score.COMPONENT_WEIGHTS.get(comp_label, 0.0),
                            })
                            comp_freq[comp_label] = comp_freq.get(comp_label, 0) + 1

                # Ordena pelo menor score (maior impacto negativo)
                failing_components.sort(key=lambda x: x["score"])
                item["failing_components"] = failing_components
                item["component_breakdown"] = component_breakdown
                result["rejected_records"].append(item)

            result["rejected_count"] = len(result["rejected_records"])
            result["failing_component_frequency"] = comp_freq

            # Top failing components ordenados por frequência
            sorted_top = sorted(comp_freq.items(), key=lambda x: x[1], reverse=True)
            result["top_failing_components"] = [k for k, _ in sorted_top]

            if sorted_top:
                summary_parts = [f"{k} ({cnt} ocorrências)" for k, cnt in sorted_top]
                result["drag_analysis_summary"] = (
                    f"Componentes que mais derrubaram o Quality Score abaixo de {threshold}: "
                    + ", ".join(summary_parts)
                )
            else:
                result["drag_analysis_summary"] = "Nenhuma rejeição encontrada no banco de dados."

    except Exception as exc:
        result["error"] = str(exc)
        result["drag_analysis_summary"] = f"Erro ao auditar Quality Rejects: {exc}"

    return result


# ---------------------------------------------------------------------------
# 4. Diagnóstico do Closed Feedback Loop (sample_count = 0)
# ---------------------------------------------------------------------------

def diagnose_closed_loop_zero_samples(
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Audita o Closed Feedback Loop e explica por que sample_count = 0 em cada perfil.

    Verifica:
    - Publicações do perfil 'default': lista publicações bloqueadas estritamente por copyright_status = unknown.
    - Publicações do perfil 'profile-historias-misterio': confirma exclusão da publicação #18 com status 'blocked'.
    - Exclusões fail-closed por janela de tempo, snapshots ausentes ou divergência de identidade.
    """
    result: Dict[str, Any] = {
        "default_profile": {
            "profile_id": PROFILE_DEFAULT,
            "sample_count": 0,
            "evidence_state": "INSUFFICIENT_DATA",
            "excluded_counts_by_reason": {},
            "total_publications": 0,
            "publications_blocked_by_unknown_copyright": [],
            "conclusion": "UNKNOWN",
        },
        "mystery_profile": {
            "profile_id": PROFILE_MYSTERY,
            "sample_count": 0,
            "evidence_state": "INSUFFICIENT_DATA",
            "excluded_counts_by_reason": {},
            "total_publications": 0,
            "blocked_publication_18_confirmed": False,
            "conclusion": "UNKNOWN",
        },
        "overall_summary": "",
    }

    try:
        with _get_ro_connection(db_path) as conn:
            # 1. Auditoria de Copyright no operational_events
            pub_copyright: Dict[int, str] = {}
            task_copyright: Dict[str, str] = {}
            if _table_exists(conn, "operational_events"):
                op_rows = conn.execute(
                    """
                    SELECT timestamp, metadata_json FROM operational_events
                    WHERE event_type = 'PUBLICATION_COPYRIGHT_STATUS_SET'
                    ORDER BY id ASC;
                    """
                ).fetchall()
                for op_r in op_rows:
                    try:
                        op_meta = json.loads(op_r["metadata_json"] or "{}")
                        c_st = str(op_meta.get("copyright_status") or "").strip().lower()
                        if c_st:
                            if op_meta.get("publication_event_id") is not None:
                                pub_copyright[int(op_meta["publication_event_id"])] = c_st
                            if op_meta.get("task_id"):
                                task_copyright[str(op_meta["task_id"])] = c_st
                    except Exception:
                        pass

            # 2. Perfil Default
            def_chan = None
            if _table_exists(conn, "publishing_channels"):
                ch_row = conn.execute(
                    "SELECT id FROM publishing_channels WHERE (profile_id = ? OR profile_id IS NULL OR profile_id = '') AND platform = 'youtube' AND is_enabled = 1 LIMIT 1;",
                    (PROFILE_DEFAULT,),
                ).fetchone()
                if ch_row:
                    def_chan = ch_row["id"]

            if def_chan:
                ev_def = analytics.get_learning_evidence(
                    platform="youtube",
                    profile_id=PROFILE_DEFAULT,
                    channel_id=def_chan,
                    db_path=db_path,
                )
                result["default_profile"]["sample_count"] = ev_def.get("sample_count", 0)
                result["default_profile"]["evidence_state"] = ev_def.get("evidence_state", "INSUFFICIENT_DATA")
                result["default_profile"]["excluded_counts_by_reason"] = ev_def.get("excluded_counts_by_reason", {})

            if _table_exists(conn, "publication_events"):
                p_rows = conn.execute(
                    """
                    SELECT id, task_id, external_id, status, privacy_status, published_at
                    FROM publication_events
                    WHERE platform = 'youtube' AND (profile_id = ? OR profile_id IS NULL OR profile_id = '')
                    ORDER BY id DESC;
                    """,
                    (PROFILE_DEFAULT,),
                ).fetchall()
                result["default_profile"]["total_publications"] = len(p_rows)
                for pr in p_rows:
                    pid = pr["id"]
                    c_status = pub_copyright.get(pid) or task_copyright.get(str(pr["task_id"])) or "unknown"
                    if c_status == "unknown" and pr["status"] == "success" and pr["privacy_status"] == "public":
                        result["default_profile"]["publications_blocked_by_unknown_copyright"].append({
                            "publication_event_id": pid,
                            "task_id": pr["task_id"],
                            "external_id": pr["external_id"],
                            "published_at": pr["published_at"],
                            "copyright_status": "unknown",
                        })

            unknown_count = len(result["default_profile"]["publications_blocked_by_unknown_copyright"])
            if unknown_count > 0:
                result["default_profile"]["conclusion"] = (
                    f"FAIL_CLOSED_COPYRIGHT_UNKNOWN: {unknown_count} publicações públicas válidas foram excluídas "
                    f"do Closed Feedback Loop porque copyright_status = 'unknown' (nenhuma auditada como clean_manual)."
                )
            else:
                result["default_profile"]["conclusion"] = "NO_PUBLICATIONS_OR_OUTSIDE_WINDOW"

            # 3. Perfil Mystery
            myst_chan = None
            if _table_exists(conn, "publishing_channels"):
                ch_row = conn.execute(
                    "SELECT id FROM publishing_channels WHERE profile_id = ? AND platform = 'youtube' AND is_enabled = 1 LIMIT 1;",
                    (PROFILE_MYSTERY,),
                ).fetchone()
                if ch_row:
                    myst_chan = ch_row["id"]

            if myst_chan:
                ev_myst = analytics.get_learning_evidence(
                    platform="youtube",
                    profile_id=PROFILE_MYSTERY,
                    channel_id=myst_chan,
                    db_path=db_path,
                )
                result["mystery_profile"]["sample_count"] = ev_myst.get("sample_count", 0)
                result["mystery_profile"]["evidence_state"] = ev_myst.get("evidence_state", "INSUFFICIENT_DATA")
                result["mystery_profile"]["excluded_counts_by_reason"] = ev_myst.get("excluded_counts_by_reason", {})

            if _table_exists(conn, "publication_events"):
                p_myst_rows = conn.execute(
                    """
                    SELECT id, task_id, external_id, status, privacy_status, published_at
                    FROM publication_events
                    WHERE platform = 'youtube' AND profile_id = ?
                    ORDER BY id DESC;
                    """,
                    (PROFILE_MYSTERY,),
                ).fetchall()
                result["mystery_profile"]["total_publications"] = len(p_myst_rows)

                # Verifica especificamente a publicação #18
                p18 = conn.execute(
                    "SELECT id, task_id, status FROM publication_events WHERE id = 18;"
                ).fetchone()
                if p18:
                    c18 = pub_copyright.get(18) or task_copyright.get(str(p18["task_id"])) or "unknown"
                    result["mystery_profile"]["publication_18_status"] = {
                        "id": 18,
                        "task_id": p18["task_id"],
                        "copyright_status": c18,
                    }
                    if c18 == "blocked":
                        result["mystery_profile"]["blocked_publication_18_confirmed"] = True

            if result["mystery_profile"]["blocked_publication_18_confirmed"]:
                result["mystery_profile"]["conclusion"] = (
                    "FAIL_CLOSED_COPYRIGHT_BLOCKED: Publicação 18 possui copyright_status='blocked' "
                    "e foi excluída estritamente pelo filtro de segurança do Closed Feedback Loop. "
                    "Nenhuma outra publicação elegível existe para este perfil."
                )
            else:
                result["mystery_profile"]["conclusion"] = "NO_ELIGIBLE_SAMPLES"

            result["overall_summary"] = (
                f"Default: {result['default_profile']['conclusion']} | "
                f"Mystery: {result['mystery_profile']['conclusion']}"
            )

    except Exception as exc:
        result["overall_summary"] = f"Erro ao diagnosticar Closed Loop: {exc}"

    return result


# ---------------------------------------------------------------------------
# 5. Snapshot Mestre Consolidado da V15-B
# ---------------------------------------------------------------------------

def run_v15b_diagnosis(
    db_path: Optional[str] = None,
    task_base_dir: Optional[str] = None,
    mystery_task_id: str = DEFAULT_MYSTERY_TASK_ID,
    missing_task_ids: Tuple[str, ...] = DEFAULT_MISSING_VIDEO_TASK_IDS,
) -> Dict[str, Any]:
    """Executa o diagnóstico passivo completo da V15-B cobrindo as quatro áreas solicitadas."""
    now_utc = datetime.now(timezone.utc).isoformat()

    mystery_diag = diagnose_mystery_task(
        task_id=mystery_task_id,
        db_path=db_path,
        task_base_dir=task_base_dir,
    )

    missing_video_diag = diagnose_missing_video_tasks(
        task_ids=missing_task_ids,
        db_path=db_path,
        task_base_dir=task_base_dir,
    )

    quality_diag = diagnose_quality_rejects(
        db_path=db_path,
        threshold=70.0,
    )

    closed_loop_diag = diagnose_closed_loop_zero_samples(
        db_path=db_path,
    )

    t1_id = missing_task_ids[0] if len(missing_task_ids) > 0 else "task_1"
    t2_id = missing_task_ids[1] if len(missing_task_ids) > 1 else "task_2"

    t1_cause = missing_video_diag.get("summary", {}).get(t1_id, "UNKNOWN")
    t2_cause = missing_video_diag.get("summary", {}).get(t2_id, "UNKNOWN")

    top_quality_components = quality_diag.get("top_failing_components", [])

    return {
        "status": "ok",
        "timestamp": now_utc,
        "conclusions": {
            "MYSTERY_APPROVED_TASK": mystery_diag.get("conclusion"),
            "MYSTERY_APPROVED_TASK_ROOT_CAUSE": mystery_diag.get("root_cause"),
            "MISSING_VIDEO_TASK_1_ROOT_CAUSE": t1_cause,
            "MISSING_VIDEO_TASK_2_ROOT_CAUSE": t2_cause,
            "DEFAULT_QUALITY_REJECT_COMPONENTS": top_quality_components,
            "DEFAULT_CLOSED_LOOP_SAMPLE_ZERO_REASON": closed_loop_diag.get("default_profile", {}).get("conclusion"),
            "MYSTERY_CLOSED_LOOP_SAMPLE_ZERO_REASON": closed_loop_diag.get("mystery_profile", {}).get("conclusion"),
        },
        "mystery_task_diagnosis": mystery_diag,
        "missing_video_tasks_diagnosis": missing_video_diag,
        "quality_rejects_diagnosis": quality_diag,
        "closed_loop_diagnosis": closed_loop_diag,
    }
