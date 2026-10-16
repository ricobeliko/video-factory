# -*- coding: utf-8 -*-
"""
app/services/quality_recovery.py
================================
Serviço Canônico para Reavaliação e Recuperação Segura de Vídeos Retidos por Quality Gate (QG-V2.2).

Objetivo:
Permitir a reavaliação de vídeos já renderizados e pagos sob o Quality Gate V2,
aprovando candidatos válidos diretamente para o Ready Stock SEM regeneração de vídeo,
SEM consumo de créditos Google Flow, SEM publicações imediatas e SEM duplicação de estoque.

Contratos Estritos:
1. DRY-RUN por padrão (zero mutação).
2. Recuperação controlada e explícita por task_id via flag --apply e confirmação RECOVER_HELD_VIDEOS.
3. Classificação determinística em 6 estados mutuamente exclusivos:
   - ELIGIBLE: MP4 válido, Safety PASS, Copyright PASS, score QG-V2 >= 70.0 (GOOD/STRONG), não agendado/publicado/estocado.
   - BLOCKED: MP4 ausente/inválido (0 bytes), Safety BLOCK/não-PASS, ou Copyright BLOCK/não-PASS.
   - ALREADY_STOCKED: Já atende a todos os critérios e está presente no Ready Stock.
   - ALREADY_SCHEDULED: Já possui post agendado ou em processamento no Scheduler.
   - ALREADY_PUBLISHED: Já possui publicação com sucesso registrada no YouTube.
   - NEEDS_REVIEW: MP4, Safety e Copyright válidos, porém score QG-V2 < 70.0.
4. Preservação histórica: a pontuação anterior em content_quality_scores NUNCA é apagada ou sobrescrita (append-only).
5. Idempotência: re-execução em tarefa já recuperada retorna ALREADY_STOCKED sem duplicação de registros.
6. Isolamento do Scheduler: entrar no Ready Stock NÃO insere registros em scheduled_posts nem causa publicação automática.
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from app.models import const
from app.services import (
    autonomous_production,
    copyright_gate,
    operator_console,
    profile_manager,
    quality_score,
    safety_gate,
    scheduler,
)
from app.utils import utils

CONFIRM_RECOVERY = "RECOVER_HELD_VIDEOS"

# Estados de classificação
CLASS_ELIGIBLE = "ELIGIBLE"
CLASS_BLOCKED = "BLOCKED"
CLASS_ALREADY_STOCKED = "ALREADY_STOCKED"
CLASS_ALREADY_SCHEDULED = "ALREADY_SCHEDULED"
CLASS_ALREADY_PUBLISHED = "ALREADY_PUBLISHED"
CLASS_NEEDS_REVIEW = "NEEDS_REVIEW"


def _resolve_paths(
    db_path: Optional[str] = None,
    task_base_dir: Optional[str] = None,
) -> Tuple[str, str]:
    """Resolve caminhos canônicos do banco e diretório de tarefas."""
    effective_db = db_path or scheduler.get_db_path()
    effective_task_dir = task_base_dir or os.path.join(utils.root_dir(), "storage", "tasks")
    return effective_db, effective_task_dir


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Verifica se a tabela existe no SQLite."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?;",
        (table_name,),
    ).fetchone()
    return bool(row)


def _read_task_script_metadata(
    task_id: str,
    task_base_dir: str,
) -> Dict[str, Any]:
    """Lê metadados originais de script.json de forma segura e fail-safe."""
    script_file = os.path.join(task_base_dir, task_id, "script.json")
    if not os.path.isfile(script_file):
        return {}

    try:
        with open(script_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.debug(f"[QUALITY_RECOVERY] Falha ao ler script.json da task {task_id}: {exc}")
        return {}


def inspect_single_held_task(
    task_id: str,
    db_path: Optional[str] = None,
    task_base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Inspeciona e classifica determinísticamente uma tarefa candidata sem aplicar mutações."""
    effective_db, effective_task_dir = _resolve_paths(db_path, task_base_dir)
    clean_tid = str(task_id or "").strip()

    if not clean_tid:
        return {
            "task_id": "",
            "classification": CLASS_BLOCKED,
            "reason": "task_id inválido ou vazio",
            "is_actionable": False,
        }

    conn = sqlite3.connect(effective_db, timeout=15.0)
    conn.row_factory = sqlite3.Row

    try:
        # 1. Consulta metadados de script.json
        script_data = _read_task_script_metadata(clean_tid, effective_task_dir)
        params_data = script_data.get("params") or {}
        script_text = script_data.get("script") or params_data.get("video_script")

        # 2. Consulta avaliação mais recente em content_quality_scores
        q_row = None
        if _table_exists(conn, "content_quality_scores"):
            q_row = conn.execute(
                """
                SELECT * FROM content_quality_scores
                WHERE task_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1;
                """,
                (clean_tid,),
            ).fetchone()

        # 3. Consulta Safety Gate
        safety_rec = safety_gate.get_safety_assessment(clean_tid, db_path=effective_db) or {}
        safety_status = str(safety_rec.get("safety_status") or "MISSING").upper().strip()
        actual_duration = safety_rec.get("actual_duration")

        # Se duração não estiver em safety_rec, tenta ler de params
        if actual_duration is None:
            raw_dur = params_data.get("actual_duration") or params_data.get("video_clip_duration")
            if raw_dur:
                try:
                    actual_duration = float(raw_dur)
                except (ValueError, TypeError):
                    actual_duration = None

        # 4. Consulta Copyright Gate
        cp_status = "UNKNOWN"
        if _table_exists(conn, "copyright_provenance"):
            cp_row = conn.execute(
                "SELECT status FROM copyright_provenance WHERE task_id = ? ORDER BY id DESC LIMIT 1;",
                (clean_tid,),
            ).fetchone()
            if cp_row and cp_row["status"]:
                raw_status = str(cp_row["status"]).upper().strip()
                if raw_status in ("BLOCK", "BLOCKED", "FAIL", "FAILED", "REJECTED"):
                    cp_status = "BLOCK"
                elif raw_status in ("PASS", "APPROVED"):
                    cp_status = "PASS"

        # Se não estiver explicitamente bloqueado no banco, valida proveniência / aprovação manual legada de forma fail-closed
        if cp_status != "BLOCK":
            try:
                cp_ok, _, _ = copyright_gate.evaluate_copyright_provenance_gate(
                    task_id=clean_tid,
                    task_base_dir=effective_task_dir,
                    db_path=effective_db,
                )
                if not cp_ok:
                    cp_status = "BLOCK"
                else:
                    cp_status = "PASS"
            except Exception:
                cp_status = "BLOCK"

        # 5. Consulta perfil associado
        profile_id = None
        if _table_exists(conn, "task_profiles"):
            tp_row = conn.execute(
                "SELECT profile_id FROM task_profiles WHERE task_id = ? LIMIT 1;",
                (clean_tid,),
            ).fetchone()
            if tp_row and tp_row["profile_id"]:
                profile_id = str(tp_row["profile_id"]).strip()

        if not profile_id:
            profile_id = params_data.get("profile_id") or profile_manager.get_task_profile_id(clean_tid, db_path=effective_db)

        # 6. Verifica arquivo MP4 final
        video_path = scheduler.get_task_final_video(clean_tid, task_base_dir=effective_task_dir)
        mp4_exists = bool(video_path and os.path.isfile(video_path) and os.path.getsize(video_path) > 0)
        mp4_size_mb = round(os.path.getsize(video_path) / (1024 * 1024), 2) if mp4_exists else 0.0

        # 7. Verifica se já publicado no YouTube
        is_published = False
        if _table_exists(conn, "publication_events"):
            pub_row = conn.execute(
                "SELECT 1 FROM publication_events WHERE task_id = ? AND platform = 'youtube' AND status = 'success' LIMIT 1;",
                (clean_tid,),
            ).fetchone()
            if pub_row:
                is_published = True

        if not is_published and _table_exists(conn, "scheduled_posts"):
            pub_sp = conn.execute(
                "SELECT 1 FROM scheduled_posts WHERE task_id = ? AND platform = 'youtube' AND status = 'published' LIMIT 1;",
                (clean_tid,),
            ).fetchone()
            if pub_sp:
                is_published = True

        # 8. Verifica se já agendado no Scheduler
        is_scheduled = False
        if not is_published and _table_exists(conn, "scheduled_posts"):
            sched_sp = conn.execute(
                "SELECT 1 FROM scheduled_posts WHERE task_id = ? AND platform = 'youtube' AND status IN ('scheduled', 'processing') LIMIT 1;",
                (clean_tid,),
            ).fetchone()
            if sched_sp:
                is_scheduled = True

        # 9. Extrai metadados factuais de conteúdo para o recálculo do QG-V2
        topic = (
            (q_row["topic"] if q_row else None)
            or params_data.get("video_subject")
            or safety_rec.get("topic")
            or clean_tid
        )
        niche = (q_row["niche"] if q_row else None) or params_data.get("niche") or "Geral"
        preset = (q_row["preset"] if q_row else None) or params_data.get("preset") or "youtube_shorts_original"
        hook_text = (
            (q_row["hook_text"] if q_row else None)
            or safety_rec.get("hook_text")
            or (script_text.split(".")[0] if script_text else topic)
        )
        narrative_structure = (q_row["narrative_structure"] if q_row else None) or params_data.get("narrative_structure")

        orig_score = float(q_row["quality_score"]) if (q_row and q_row["quality_score"] is not None) else 0.0
        orig_label = str(q_row["quality_label"] or "WEAK") if q_row else "WEAK"

        # 10. Recálculo no Quality Gate V2 com plataforma YouTube
        qg_v2_eval = quality_score.evaluate_quality(
            topic=topic,
            niche=niche,
            hook_text=hook_text,
            script_text=script_text,
            preset=preset,
            narrative_structure=narrative_structure,
            actual_duration=actual_duration,
            task_id=clean_tid,
            platform="youtube",
            profile_id=profile_id,
            persist=False,
            db_path=effective_db,
        )

        v2_score = qg_v2_eval.get("quality_score", orig_score)
        v2_label = qg_v2_eval.get("quality_label", orig_label)
        reasons = qg_v2_eval.get("reasons", [])

        # 11. Verifica se já está aprovado e no Ready Stock
        has_task_platform_yt = False
        if _table_exists(conn, "task_platforms"):
            tp_row = conn.execute(
                "SELECT 1 FROM task_platforms WHERE task_id = ? AND platform = 'youtube' LIMIT 1;",
                (clean_tid,),
            ).fetchone()
            has_task_platform_yt = bool(tp_row)

        is_already_stocked = (
            not is_published
            and not is_scheduled
            and orig_score >= 70.0
            and orig_label in ("GOOD", "STRONG")
            and safety_status == const.SAFETY_STATUS_PASS
            and cp_status == "PASS"
            and mp4_exists
            and has_task_platform_yt
        )

        # 12. Determina classificação e motivo da decisão
        classification = CLASS_NEEDS_REVIEW
        reason = ""

        if is_published:
            classification = CLASS_ALREADY_PUBLISHED
            reason = "Vídeo já publicado com sucesso no YouTube."
        elif is_scheduled:
            classification = CLASS_ALREADY_SCHEDULED
            reason = "Vídeo já agendado ou em processamento no Scheduler."
        elif is_already_stocked:
            classification = CLASS_ALREADY_STOCKED
            reason = "Vídeo já aprovado e disponível no Ready Stock."
        elif not mp4_exists:
            classification = CLASS_BLOCKED
            reason = "Arquivo final-1.mp4 ausente ou vazio (0 bytes) no disco."
        elif safety_status != const.SAFETY_STATUS_PASS:
            classification = CLASS_BLOCKED
            reason = f"Safety Gate não aprovado ({safety_status})."
        elif cp_status != "PASS":
            classification = CLASS_BLOCKED
            reason = f"Copyright Gate não aprovado ({cp_status})."
        elif v2_score >= 70.0 and v2_label in ("GOOD", "STRONG"):
            classification = CLASS_ELIGIBLE
            reason = f"Aprovado no QG-V2 ({v2_score:.1f} - {v2_label} >= 70.0). Elegível para recuperação de estoque."
        else:
            classification = CLASS_NEEDS_REVIEW
            reason = f"Score sob QG-V2 ({v2_score:.1f} - {v2_label}) insuficiente para aprovação autônoma (limiar >= 70.0)."

        return {
            "task_id": clean_tid,
            "topic": topic,
            "niche": niche,
            "preset": preset,
            "hook_text": hook_text,
            "script_text": script_text,
            "narrative_structure": narrative_structure,
            "actual_duration": actual_duration,
            "profile_id": profile_id,
            "mp4_exists": mp4_exists,
            "mp4_size_mb": mp4_size_mb,
            "mp4_path": video_path or "N/A",
            "safety_status": safety_status,
            "copyright_status": cp_status,
            "original_quality_score": orig_score,
            "original_quality_label": orig_label,
            "qg_v2_quality_score": v2_score,
            "qg_v2_quality_label": v2_label,
            "classification": classification,
            "reason": reason,
            "reasons": reasons,
            "is_actionable": classification == CLASS_ELIGIBLE,
        }
    finally:
        conn.close()


def inspect_all_held_tasks(
    db_path: Optional[str] = None,
    task_base_dir: Optional[str] = None,
    profile_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Inspeciona todas as tarefas com registros no banco e classifica cada candidato."""
    effective_db, effective_task_dir = _resolve_paths(db_path, task_base_dir)

    if not os.path.isfile(effective_db):
        return {
            "status": "error",
            "message": f"Banco de dados não encontrado em {effective_db}",
            "candidates": [],
        }

    conn = sqlite3.connect(effective_db, timeout=15.0)
    conn.row_factory = sqlite3.Row

    try:
        task_ids: List[str] = []
        seen = set()

        def _add_tid(tid: Any):
            clean = str(tid or "").strip()
            if clean and clean not in seen:
                seen.add(clean)
                task_ids.append(clean)

        # 1. Coleta IDs de content_quality_scores
        if _table_exists(conn, "content_quality_scores"):
            rows = conn.execute("SELECT DISTINCT task_id FROM content_quality_scores WHERE task_id IS NOT NULL;").fetchall()
            for r in rows:
                _add_tid(r["task_id"])

        # 2. Coleta IDs de monetization_safety
        if _table_exists(conn, "monetization_safety"):
            rows = conn.execute("SELECT DISTINCT task_id FROM monetization_safety WHERE task_id IS NOT NULL;").fetchall()
            for r in rows:
                _add_tid(r["task_id"])

        # 3. Coleta tarefas do disco que possuem final-1.mp4
        if os.path.isdir(effective_task_dir):
            try:
                for entry in os.listdir(effective_task_dir):
                    sub = os.path.join(effective_task_dir, entry)
                    if os.path.isdir(sub) and os.path.isfile(os.path.join(sub, "final-1.mp4")):
                        _add_tid(entry)
            except OSError:
                pass
    finally:
        conn.close()

    candidates = []
    clean_target_profile = str(profile_id or "").strip()

    for tid in task_ids:
        cand = inspect_single_held_task(tid, db_path=effective_db, task_base_dir=effective_task_dir)
        if clean_target_profile and cand.get("profile_id") != clean_target_profile:
            continue
        candidates.append(cand)

    # Ordenação: ELIGIBLE primeiro, depois por QG-V2 score decrescente
    sort_priority = {
        CLASS_ELIGIBLE: 0,
        CLASS_NEEDS_REVIEW: 1,
        CLASS_ALREADY_STOCKED: 2,
        CLASS_ALREADY_SCHEDULED: 3,
        CLASS_ALREADY_PUBLISHED: 4,
        CLASS_BLOCKED: 5,
    }
    candidates.sort(key=lambda c: (sort_priority.get(c["classification"], 99), -c["qg_v2_quality_score"]))

    counts = {
        CLASS_ELIGIBLE: sum(1 for c in candidates if c["classification"] == CLASS_ELIGIBLE),
        CLASS_BLOCKED: sum(1 for c in candidates if c["classification"] == CLASS_BLOCKED),
        CLASS_NEEDS_REVIEW: sum(1 for c in candidates if c["classification"] == CLASS_NEEDS_REVIEW),
        CLASS_ALREADY_STOCKED: sum(1 for c in candidates if c["classification"] == CLASS_ALREADY_STOCKED),
        CLASS_ALREADY_SCHEDULED: sum(1 for c in candidates if c["classification"] == CLASS_ALREADY_SCHEDULED),
        CLASS_ALREADY_PUBLISHED: sum(1 for c in candidates if c["classification"] == CLASS_ALREADY_PUBLISHED),
    }

    return {
        "status": "ok",
        "db_path": effective_db,
        "task_base_dir": effective_task_dir,
        "total_inspected": len(candidates),
        "counts": counts,
        "candidates": candidates,
    }


def recover_held_quality_task(
    task_id: str,
    confirm: Optional[str] = None,
    db_path: Optional[str] = None,
    task_base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Aplica a recuperação controlada de uma tarefa explicitamente selecionada por ID.

    Garante:
    - Exclusividade PRIMARY (require_primary_instance).
    - Confirmação explícita obrigatória: confirm == 'RECOVER_HELD_VIDEOS'.
    - Tarefas já em Ready Stock retornam status='already_stocked' sem duplicação.
    - Tarefas inelegíveis, publicadas ou bloqueadas falham de forma fail-closed.
    - Gravação append-only em content_quality_scores preservando histórico anterior.
    - Vínculo com 'youtube' em task_platforms e persistência de perfil em task_profiles.
    - Atualização do estado em sm.state para COMPLETE e approved.
    - Registro de evento auditável em operational_events.
    - ZERO agendamento em scheduled_posts e ZERO publicação.
    """
    effective_db, effective_task_dir = _resolve_paths(db_path, task_base_dir)
    clean_tid = str(task_id or "").strip()

    if not clean_tid:
        raise ValueError("task_id inválido ou ausente.")

    clean_confirm = str(confirm or "").strip()
    if clean_confirm != CONFIRM_RECOVERY:
        raise ValueError(
            f"Confirmação explícita '{CONFIRM_RECOVERY}' é obrigatória "
            f"para recuperar vídeos retidos."
        )

    operator_console.require_primary_instance(db_path=effective_db)

    # Inspeciona a tarefa atual
    cand = inspect_single_held_task(clean_tid, db_path=effective_db, task_base_dir=effective_task_dir)

    if cand["classification"] == CLASS_ALREADY_STOCKED:
        return {
            "status": "already_stocked",
            "task_id": clean_tid,
            "message": "Tarefa já se encontra aprovada no Ready Stock.",
            "data": cand,
        }

    if cand["classification"] == CLASS_ALREADY_PUBLISHED:
        raise ValueError(f"Tarefa '{clean_tid}' já foi publicada com sucesso no YouTube.")

    if cand["classification"] == CLASS_ALREADY_SCHEDULED:
        raise ValueError(f"Tarefa '{clean_tid}' já está agendada ou em processamento no Scheduler.")

    if cand["classification"] != CLASS_ELIGIBLE:
        raise ValueError(f"Tarefa '{clean_tid}' não é elegível para recuperação: {cand['reason']}")

    # 1. Persiste a nova avaliação calibrada QG-V2 em content_quality_scores (append-only)
    new_score = cand["qg_v2_quality_score"]
    new_label = cand["qg_v2_quality_label"]

    quality_score.evaluate_quality(
        topic=cand["topic"],
        niche=cand["niche"],
        hook_text=cand["hook_text"],
        script_text=cand.get("script_text"),
        preset=cand.get("preset"),
        narrative_structure=cand.get("narrative_structure"),
        actual_duration=cand.get("actual_duration"),
        task_id=clean_tid,
        profile_id=cand.get("profile_id"),
        platform="youtube",
        persist=True,
        db_path=effective_db,
    )

    # 2. Garante persistência em task_platforms
    scheduler.save_task_platforms(clean_tid, ["youtube"], db_path=effective_db)

    # 3. Garante persistência de perfil em task_profiles
    assigned_profile = cand.get("profile_id") or profile_manager.DEFAULT_PROFILE_ID
    profile_manager.save_task_profile(clean_tid, assigned_profile, db_path=effective_db)

    # 4. Atualiza estado em sm.state
    try:
        from app.services import state as sm
        sm.state.patch_task(
            clean_tid,
            state=const.TASK_STATE_COMPLETE,
            gate_status="approved",
            gate_reason=f"Recuperado pelo operador via QG-V2 ({new_score:.1f} {new_label})",
            quality_score=new_score,
            quality_label=new_label,
            video_file=cand["mp4_path"],
            planned_platforms=["youtube"],
            profile_id=assigned_profile,
        )
    except Exception as exc:
        logger.debug(f"[QUALITY_RECOVERY] Falha ao atualizar sm.state para {clean_tid}: {exc}")

    # 5. Registra evento operacional auditável
    operator_console.log_operational_event(
        component="quality_gate",
        severity=operator_console.SEVERITY_INFO,
        event_type="held_task_quality_recovered",
        task_id=clean_tid,
        message=(
            f"Tarefa {clean_tid} retida recuperada para o Ready Stock sob QG-V2 "
            f"(Score: {cand['original_quality_score']:.1f} -> {new_score:.1f} {new_label})."
        ),
        metadata={
            "task_id": clean_tid,
            "topic": cand["topic"],
            "original_quality_score": cand["original_quality_score"],
            "original_quality_label": cand["original_quality_label"],
            "qg_v2_quality_score": new_score,
            "qg_v2_quality_label": new_label,
            "safety_status": cand["safety_status"],
            "copyright_status": cand["copyright_status"],
            "mp4_path": cand["mp4_path"],
            "profile_id": assigned_profile,
        },
        db_path=effective_db,
    )

    return {
        "status": "success",
        "task_id": clean_tid,
        "message": f"Tarefa {clean_tid} recuperada com sucesso para o Ready Stock.",
        "original_quality_score": cand["original_quality_score"],
        "original_quality_label": cand["original_quality_label"],
        "qg_v2_quality_score": new_score,
        "qg_v2_quality_label": new_label,
        "ready_stock_eligible": True,
    }
