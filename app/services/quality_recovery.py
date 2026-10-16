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
from datetime import datetime, timezone
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


CONFIRM_RECOVERY = "RECOVER_HELD_VIDEOS"
CONFIRM_APPROVE_FOR_STOCK = "APPROVE_FOR_STOCK"
CONFIRM_DISCARD_HELD_VIDEO = "DISCARD_HELD_VIDEO"

# Estados de classificação
CLASS_ELIGIBLE = "ELIGIBLE"
CLASS_BLOCKED = "BLOCKED"
CLASS_ALREADY_STOCKED = "ALREADY_STOCKED"
CLASS_ALREADY_SCHEDULED = "ALREADY_SCHEDULED"
CLASS_ALREADY_PUBLISHED = "ALREADY_PUBLISHED"
CLASS_NEEDS_REVIEW = "NEEDS_REVIEW"
CLASS_DISCARDED = "DISCARDED"

DECISION_APPROVED = "APPROVED"
DECISION_DISCARDED = "DISCARDED"

# Cache em memória para evitar reavaliação NLP redundante de tarefas em cada listagem GET
_QG_V2_CACHE: Dict[str, Tuple[float, str, List[str]]] = {}


def clear_qg_v2_cache() -> None:
    """Limpa o cache em memória de recálculos QG-V2."""
    _QG_V2_CACHE.clear()


def init_review_db(db_path: Optional[str] = None) -> None:
    """Inicializa as tabelas de revisão humana e comandos operacionais no SQLite."""
    effective_db, _ = _resolve_paths(db_path)
    scheduler.init_db(effective_db)
    with sqlite3.connect(effective_db) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS operator_video_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT UNIQUE NOT NULL,
                decision TEXT NOT NULL,
                operator_id TEXT NOT NULL,
                note TEXT,
                original_score REAL,
                recalculated_score REAL,
                approved_below_threshold INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata_json TEXT
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_op_vid_reviews_task ON operator_video_reviews(task_id);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_op_vid_reviews_dec ON operator_video_reviews(decision);"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS operator_review_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                action TEXT NOT NULL,
                operator_id TEXT NOT NULL,
                note TEXT,
                status TEXT NOT NULL,
                result_json TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                processed_at TEXT,
                processed_by_node TEXT
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_op_rev_cmd_status ON operator_review_commands(status);"
        )
        conn.commit()


def _resolve_paths(
    db_path: Optional[str] = None,
    task_base_dir: Optional[str] = None,
) -> Tuple[str, str]:
    """Resolve caminhos canônicos do banco e diretório de tarefas."""
    effective_db = db_path or scheduler.get_db_path()
    effective_task_dir = task_base_dir or utils.task_dir()
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
    fast_listing: bool = False,
    conn: Optional[sqlite3.Connection] = None,
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

    close_conn = False
    if conn is None:
        active_conn = sqlite3.connect(effective_db, timeout=15.0)
        active_conn.row_factory = sqlite3.Row
        close_conn = True
    else:
        active_conn = conn

    try:
        # 1. Consulta metadados de script.json
        script_data = _read_task_script_metadata(clean_tid, effective_task_dir)
        params_data = script_data.get("params") or {}
        script_text = script_data.get("script") or params_data.get("video_script")

        # 2. Consulta avaliação mais recente em content_quality_scores
        q_row = None
        if _table_exists(active_conn, "content_quality_scores"):
            q_row = active_conn.execute(
                """
                SELECT * FROM content_quality_scores
                WHERE task_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1;
                """,
                (clean_tid,),
            ).fetchone()

        # 3. Consulta Safety Gate diretamente via active_conn para evitar DDL/reconexões redundantes
        safety_status = "MISSING"
        actual_duration = None
        s_topic = None
        s_hook = None
        if _table_exists(active_conn, "monetization_safety"):
            s_row = active_conn.execute(
                "SELECT safety_status, actual_duration, topic, hook_text FROM monetization_safety WHERE task_id = ? LIMIT 1;",
                (clean_tid,),
            ).fetchone()
            if s_row:
                safety_status = str(s_row["safety_status"] or "MISSING").upper().strip()
                actual_duration = s_row["actual_duration"]
                s_topic = s_row["topic"]
                s_hook = s_row["hook_text"]

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
        copyright_reason = ""
        if _table_exists(active_conn, "copyright_provenance"):
            cp_row = active_conn.execute(
                "SELECT status FROM copyright_provenance WHERE task_id = ? ORDER BY id DESC LIMIT 1;",
                (clean_tid,),
            ).fetchone()
            if cp_row and cp_row["status"]:
                raw_status = str(cp_row["status"]).upper().strip()
                if raw_status in ("BLOCK", "BLOCKED", "FAIL", "FAILED", "REJECTED"):
                    cp_status = "BLOCK"
                    copyright_reason = "Bloqueio registrado em copyright_provenance."
                elif raw_status in ("PASS", "APPROVED"):
                    cp_status = "PASS"

        # Se não estiver explicitamente bloqueado no banco, valida proveniência de forma fail-closed
        if cp_status != "BLOCK":
            if fast_listing:
                if cp_status == "UNKNOWN":
                    # 4.1. Verifica aprovação manual legada em operational_events
                    has_manual_appr = False
                    if _table_exists(active_conn, "operational_events"):
                        row_appr = active_conn.execute(
                            "SELECT 1 FROM operational_events WHERE task_id = ? AND event_type = ? LIMIT 1;",
                            (clean_tid, copyright_gate.EVENT_TASK_COPYRIGHT_MANUAL_APPROVAL),
                        ).fetchone()
                        has_manual_appr = bool(row_appr)

                    if has_manual_appr:
                        cp_status = "PASS"
                    else:
                        # 4.2. Obtém ou reconstrói proveniência via build_asset_provenance
                        prov = script_data.get("asset_provenance") if isinstance(script_data, dict) else None
                        if not prov:
                            mat_sources = script_data.get("material_sources")
                            if not mat_sources and script_data.get("scene_materials"):
                                mat_sources = [
                                    {
                                        "provider": sm.get("provider"),
                                        "asset_id": sm.get("asset_id"),
                                        "local_file": sm.get("material_path"),
                                        "source_page": sm.get("source_url") or "",
                                        "search_term": sm.get("search_term_used") or "",
                                        "duration": sm.get("duration", 0),
                                        "used_duration_sec": sm.get("duration", 0),
                                        "scene_index": sm.get("scene_index"),
                                        "visual_source_type": sm.get("visual_source_type", "stock"),
                                    }
                                    for sm in script_data.get("scene_materials", [])
                                ]
                            prov = copyright_gate.build_asset_provenance(
                                task_id=clean_tid,
                                params=params_data,
                                material_sources=mat_sources,
                                task_base_dir=effective_task_dir,
                            )

                        # 4.3. Avalia proveniência respeitando o contrato real do Copyright Gate
                        # Não declara PASS simplesmente porque BGM está off ou parece stock:
                        # exige conformidade de BGM E conformidade de todos os clips visuais.
                        if prov and isinstance(prov, dict):
                            bgm = prov.get("bgm") or {}
                            bgm_enabled = bgm.get("enabled", False)
                            bgm_source = str(bgm.get("source", "")).lower()
                            bgm_status = str(bgm.get("provenance_status", "")).upper()
                            bgm_type = str(params_data.get("bgm_type") or "").lower().strip()

                            bgm_ok = False
                            bgm_blocked = False

                            if bgm_enabled:
                                if bgm_type == "ambient_auto" and (bgm_source == "procedural" or bgm_status == "SAFE_PROCEDURAL"):
                                    bgm_ok = True
                                elif "legacy" in bgm_source or "songs" in bgm_source or bgm_type in ("random", "preset"):
                                    bgm_blocked = True
                                else:
                                    bgm_blocked = False
                                    bgm_ok = False
                            else:
                                bgm_ok = True

                            clips = prov.get("visual_clips") or []
                            if bgm_blocked:
                                cp_status = "BLOCK"
                                copyright_reason = "BGM de origem não autorizada ou legada."
                            elif not clips:
                                cp_status = "UNKNOWN"
                                copyright_reason = "Nenhum clipe visual com proveniência registrada."
                            else:
                                allowed_stock_providers = {"pexels", "pixabay", "coverr"}
                                all_clips_safe = True
                                any_blocked = False
                                has_unverified_flow = False
                                for cl in clips:
                                    cl_provider = str(cl.get("provider") or "").lower().strip()
                                    cl_status = str(cl.get("provenance_status") or "").upper().strip()
                                    local_f = cl.get("local_file")
                                    if cl_status in ("FAIL", "BLOCK", "BLOCKED", "UNAUTHORIZED"):
                                        any_blocked = True
                                        copyright_reason = f"Clipe com status adverso: {cl_status}"
                                        break
                                    if cl_provider in ("google_flow", "flow"):
                                        if cl_status != "GENERATED_FLOW_PROVENANCE_VERIFIED":
                                            has_unverified_flow = True
                                    elif cl_provider not in allowed_stock_providers or not local_f:
                                        all_clips_safe = False

                                if any_blocked:
                                    cp_status = "BLOCK"
                                elif has_unverified_flow:
                                    cp_status = "UNKNOWN"
                                    copyright_reason = "Contém clipes Google Flow pendentes de validação completa no primário."
                                elif bgm_ok and all_clips_safe and len(clips) > 0:
                                    cp_status = "PASS"
                                else:
                                    cp_status = "UNKNOWN"
                                    copyright_reason = "Proveniência visual ou de áudio incompleta para aprovação rápida."
                        else:
                            cp_status = "UNKNOWN"
                            copyright_reason = "Proveniência de ativos ausente."
            else:
                try:
                    cp_ok, cp_reason, _ = copyright_gate.evaluate_copyright_provenance_gate(
                        task_id=clean_tid,
                        task_base_dir=effective_task_dir,
                        db_path=effective_db,
                    )
                    if not cp_ok:
                        cp_status = "BLOCK"
                        copyright_reason = cp_reason
                    else:
                        cp_status = "PASS"
                except Exception as exc:
                    cp_status = "BLOCK"
                    copyright_reason = f"Exceção na avaliação de copyright: {exc}"

        # 5. Consulta perfil associado
        profile_id = None
        if _table_exists(active_conn, "task_profiles"):
            tp_row = active_conn.execute(
                "SELECT profile_id FROM task_profiles WHERE task_id = ? LIMIT 1;",
                (clean_tid,),
            ).fetchone()
            if tp_row and tp_row["profile_id"]:
                profile_id = str(tp_row["profile_id"]).strip()

        if not profile_id:
            profile_id = params_data.get("profile_id") or profile_manager.DEFAULT_PROFILE_ID

        # 6. Verifica arquivo MP4 final
        video_path = scheduler.get_task_final_video(clean_tid, task_base_dir=effective_task_dir)
        mp4_exists = bool(video_path and os.path.isfile(video_path) and os.path.getsize(video_path) > 0)
        mp4_size_mb = round(os.path.getsize(video_path) / (1024 * 1024), 2) if mp4_exists else 0.0

        # 7. Verifica se já publicado no YouTube
        is_published = False
        if _table_exists(active_conn, "publication_events"):
            pub_row = active_conn.execute(
                "SELECT 1 FROM publication_events WHERE task_id = ? AND platform = 'youtube' AND status = 'success' LIMIT 1;",
                (clean_tid,),
            ).fetchone()
            if pub_row:
                is_published = True

        if not is_published and _table_exists(active_conn, "scheduled_posts"):
            pub_sp = active_conn.execute(
                "SELECT 1 FROM scheduled_posts WHERE task_id = ? AND platform = 'youtube' AND status = 'published' LIMIT 1;",
                (clean_tid,),
            ).fetchone()
            if pub_sp:
                is_published = True

        # 8. Verifica se já agendado no Scheduler
        is_scheduled = False
        if not is_published and _table_exists(active_conn, "scheduled_posts"):
            sched_sp = active_conn.execute(
                "SELECT 1 FROM scheduled_posts WHERE task_id = ? AND platform = 'youtube' AND status IN ('scheduled', 'processing') LIMIT 1;",
                (clean_tid,),
            ).fetchone()
            if sched_sp:
                is_scheduled = True

        # 9. Extrai metadados factuais de conteúdo para o recálculo do QG-V2
        topic = (
            (q_row["topic"] if q_row else None)
            or params_data.get("video_subject")
            or s_topic
            or clean_tid
        )
        niche = (q_row["niche"] if q_row else None) or params_data.get("niche") or "Geral"
        preset = (q_row["preset"] if q_row else None) or params_data.get("preset") or "youtube_shorts_original"
        hook_text = (
            (q_row["hook_text"] if q_row else None)
            or s_hook
            or (script_text.split(".")[0] if script_text else topic)
        )
        narrative_structure = (q_row["narrative_structure"] if q_row else None) or params_data.get("narrative_structure")

        orig_score = float(q_row["quality_score"]) if (q_row and q_row["quality_score"] is not None) else 0.0
        orig_label = str(q_row["quality_label"] or "WEAK") if q_row else "WEAK"

        # 10. Recálculo no Quality Gate V2 com plataforma YouTube
        v2_score = orig_score
        v2_label = orig_label
        reasons = []

        if (is_published or is_scheduled) and fast_listing:
            # Tarefas já comprovadamente publicadas ou agendadas não precisam de recálculo no fast_listing
            v2_score = orig_score
            v2_label = orig_label
            reasons = []
        elif orig_score >= 70.0 and orig_label in ("GOOD", "STRONG"):
            # Vídeo já aprovado com excelência no Quality Gate original; não recalcula nem gasta CPU/I/O
            v2_score = orig_score
            v2_label = orig_label
            reasons = []
        elif fast_listing and clean_tid in _QG_V2_CACHE:
            v2_score, v2_label, reasons = _QG_V2_CACHE[clean_tid]
        else:
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
            _QG_V2_CACHE[clean_tid] = (v2_score, v2_label, reasons)

        # 11. Verifica se já está aprovado e no Ready Stock
        has_task_platform_yt = False
        if _table_exists(active_conn, "task_platforms"):
            tp_row = active_conn.execute(
                "SELECT 1 FROM task_platforms WHERE task_id = ? AND platform = 'youtube' LIMIT 1;",
                (clean_tid,),
            ).fetchone()
            has_task_platform_yt = bool(tp_row)

        # Consulta decisão de revisão humana prévia (se existir)
        human_review = None
        if _table_exists(active_conn, "operator_video_reviews"):
            hr_row = active_conn.execute(
                "SELECT decision, operator_id, note, approved_below_threshold, created_at FROM operator_video_reviews WHERE task_id = ?;",
                (clean_tid,),
            ).fetchone()
            if hr_row:
                human_review = dict(hr_row)

        human_decision = human_review.get("decision") if human_review else None

        is_already_stocked = (
            not is_published
            and not is_scheduled
            and (
                human_decision == DECISION_APPROVED
                or (
                    orig_score >= 70.0
                    and orig_label in ("GOOD", "STRONG")
                    and safety_status == const.SAFETY_STATUS_PASS
                    and cp_status == "PASS"
                    and mp4_exists
                )
            )
        )

        # 12. Determina classificação e motivo da decisão
        classification = CLASS_NEEDS_REVIEW
        reason = ""

        if human_decision == DECISION_DISCARDED:
            classification = CLASS_DISCARDED
            reason = f"Vídeo descartado da fila de revisão pelo operador ({human_review.get('operator_id')})."
        elif human_decision == DECISION_APPROVED:
            classification = CLASS_ALREADY_STOCKED
            reason = f"Vídeo aprovado pelo operador ({human_review.get('operator_id')}) para o Ready Stock."
        elif is_published:
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
        elif cp_status == "BLOCK":
            classification = CLASS_BLOCKED
            reason = f"Copyright Gate bloqueado: {copyright_reason}" if copyright_reason else "Copyright Gate bloqueado (violação ou material não licenciado)."
        elif cp_status == "UNKNOWN":
            classification = CLASS_NEEDS_REVIEW
            reason = f"Copyright Gate pendente de validação em nó primário (UNKNOWN); score QG-V2 ({v2_score:.1f} - {v2_label})."
        elif v2_score >= 70.0 and v2_label in ("GOOD", "STRONG"):
            classification = CLASS_ELIGIBLE
            reason = f"Aprovado no QG-V2 ({v2_score:.1f} - {v2_label} >= 70.0). Elegível para recuperação de estoque."
        else:
            classification = CLASS_NEEDS_REVIEW
            reason = f"Score sob QG-V2 ({v2_score:.1f} - {v2_label}) insuficiente para aprovação autônoma (limiar >= 70.0); aguarda decisão editorial humana."

        is_actionable = (
            classification in (CLASS_ELIGIBLE, CLASS_NEEDS_REVIEW)
            and cp_status == "PASS"
            and safety_status == const.SAFETY_STATUS_PASS
            and mp4_exists
        )

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
            "copyright_reason": copyright_reason,
            "original_quality_score": orig_score,
            "original_quality_label": orig_label,
            "qg_v2_quality_score": v2_score,
            "qg_v2_quality_label": v2_label,
            "classification": classification,
            "reason": reason,
            "reasons": reasons,
            "is_actionable": is_actionable,
            "human_review": human_review,
        }
    finally:
        if close_conn:
            active_conn.close()


def inspect_all_held_tasks(
    db_path: Optional[str] = None,
    task_base_dir: Optional[str] = None,
    profile_id: Optional[str] = None,
    fast_listing: bool = True,
) -> Dict[str, Any]:
    """Inspeciona todas as tarefas com registros no banco e classifica cada candidato."""
    effective_db, effective_task_dir = _resolve_paths(db_path, task_base_dir)

    if not os.path.isfile(effective_db):
        return {
            "status": "error",
            "message": f"Banco de dados não encontrado em {effective_db}",
            "candidates": [],
        }

    # Inicializações DDL executadas uma única vez antes das leituras
    init_review_db(effective_db)
    safety_gate.init_safety_db(effective_db)
    profile_manager.init_profile_db(effective_db)

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

        # 1. Coleta IDs de operator_video_reviews
        if _table_exists(conn, "operator_video_reviews"):
            rows = conn.execute("SELECT DISTINCT task_id FROM operator_video_reviews WHERE task_id IS NOT NULL;").fetchall()
            for r in rows:
                _add_tid(r["task_id"])

        # 2. Coleta IDs de content_quality_scores
        if _table_exists(conn, "content_quality_scores"):
            rows = conn.execute("SELECT DISTINCT task_id FROM content_quality_scores WHERE task_id IS NOT NULL;").fetchall()
            for r in rows:
                _add_tid(r["task_id"])

        # 3. Coleta IDs de monetization_safety
        if _table_exists(conn, "monetization_safety"):
            rows = conn.execute("SELECT DISTINCT task_id FROM monetization_safety WHERE task_id IS NOT NULL;").fetchall()
            for r in rows:
                _add_tid(r["task_id"])

        # 4. Coleta tarefas do disco que possuem final-1.mp4
        if os.path.isdir(effective_task_dir):
            try:
                for entry in os.listdir(effective_task_dir):
                    sub = os.path.join(effective_task_dir, entry)
                    if os.path.isdir(sub) and os.path.isfile(os.path.join(sub, "final-1.mp4")):
                        _add_tid(entry)
            except OSError:
                pass

        candidates = []
        clean_target_profile = str(profile_id or "").strip()

        for tid in task_ids:
            cand = inspect_single_held_task(
                tid,
                db_path=effective_db,
                task_base_dir=effective_task_dir,
                fast_listing=fast_listing,
                conn=conn,
            )
            if clean_target_profile and cand.get("profile_id") != clean_target_profile:
                continue
            candidates.append(cand)
    finally:
        conn.close()

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


def get_review_queue(
    filter: str = "pending",
    profile_id: Optional[str] = None,
    db_path: Optional[str] = None,
    task_base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Retorna a fila de tarefas para a Central de Revisão de Vídeos.

    Filtros suportados:
    - 'pending': vídeos íntegros com MP4 válido, Safety e Copyright PASS, não publicados,
                 aguardando aprovação ou descarte do operador.
    - 'approved': vídeos aprovados manualmente ou com QG-V2 >= 70 no Ready Stock.
    - 'discarded': vídeos explicitamente descartados pelo operador (nunca reaparecem em pending).
    - 'all': todos os vídeos inspecionados.
    """
    effective_db, effective_task_dir = _resolve_paths(db_path, task_base_dir)
    init_review_db(effective_db)

    inspection = inspect_all_held_tasks(
        db_path=effective_db,
        task_base_dir=effective_task_dir,
        profile_id=profile_id,
        fast_listing=True,
    )
    all_candidates = inspection.get("candidates", [])

    pending_list = []
    approved_list = []
    discarded_list = []

    for c in all_candidates:
        cls = c["classification"]
        hr = c.get("human_review")
        # Regra de exclusão estrita: se não tiver MP4, ou Safety!=PASS, ou Copyright!=PASS,
        # ou se já foi publicado, nunca aparece como candidato à aprovação pendente.
        if cls == CLASS_DISCARDED or (hr and hr.get("decision") == DECISION_DISCARDED):
            discarded_list.append(c)
        elif hr and hr.get("decision") == DECISION_APPROVED:
            approved_list.append(c)
        elif cls in (CLASS_ELIGIBLE, CLASS_NEEDS_REVIEW) and not (hr and hr.get("decision")):
            # Tarefas com MP4 válido, Safety PASS, Copyright PASS ou UNKNOWN (pendente de validação)
            if c.get("mp4_exists") and c.get("safety_status") == const.SAFETY_STATUS_PASS and c.get("copyright_status") in ("PASS", "UNKNOWN"):
                pending_list.append(c)

    clean_filter = str(filter or "pending").lower().strip()
    if clean_filter == "approved":
        selected_tasks = approved_list
    elif clean_filter == "discarded":
        selected_tasks = discarded_list
    elif clean_filter == "all":
        selected_tasks = all_candidates
    else:  # default "pending"
        selected_tasks = pending_list

    return {
        "status": "ok",
        "filter": clean_filter,
        "counts": {
            "pending": len(pending_list),
            "approved": len(approved_list),
            "discarded": len(discarded_list),
            "total_inspected": len(all_candidates),
        },
        "tasks": selected_tasks,
    }


def apply_human_review_decision(
    task_id: str,
    action: str,
    operator_id: Optional[str] = "operator",
    note: Optional[str] = None,
    confirm: Optional[str] = None,
    db_path: Optional[str] = None,
    task_base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Aplica a decisão editorial humana explícita (APPROVE ou DISCARD).
    
    Exige:
    - Execução sob nó PRIMARY (require_primary_instance).
    - Confirmação explícita:
      - APPROVE: confirm == 'APPROVE_FOR_STOCK'
      - DISCARD: confirm == 'DISCARD_HELD_VIDEO'
    - Revalidação estrita de MP4, Safety, Copyright e plataforma.
    - Preservação do histórico e score original (NUNCA falsificado).
    - Gravação em operator_video_reviews e operational_events.
    """
    effective_db, effective_task_dir = _resolve_paths(db_path, task_base_dir)
    clean_tid = str(task_id or "").strip()
    raw_action = str(action or "").upper().strip()
    if raw_action in ("APPROVE", "APPROVED"):
        clean_action = DECISION_APPROVED
    elif raw_action in ("DISCARD", "DISCARDED"):
        clean_action = DECISION_DISCARDED
    else:
        raise ValueError(f"Ação inválida: '{action}'. Opções permitidas: APPROVE, DISCARD.")

    clean_op = str(operator_id or "operator").strip()
    clean_note = str(note or "").strip()

    if not clean_tid:
        raise ValueError("task_id inválido ou ausente.")

    # 1. PRIMARY Guard estrito
    operator_console.require_primary_instance(db_path=effective_db)
    init_review_db(effective_db)

    # No momento da aprovação, executa obrigatoriamente fast_listing=False para validação integral
    is_approval = (clean_action == DECISION_APPROVED)
    cand = inspect_single_held_task(
        clean_tid,
        db_path=effective_db,
        task_base_dir=effective_task_dir,
        fast_listing=(not is_approval),
    )

    now_iso = _now_iso()

    if clean_action == DECISION_DISCARDED:
        if confirm != CONFIRM_DISCARD_HELD_VIDEO:
            raise ValueError(
                f"Confirmação explícita '{CONFIRM_DISCARD_HELD_VIDEO}' é obrigatória "
                f"para descartar tarefas da revisão."
            )
        
        # Registra o descarte em operator_video_reviews
        with sqlite3.connect(effective_db) as conn:
            conn.execute(
                """
                INSERT INTO operator_video_reviews (
                    task_id, decision, operator_id, note, original_score, recalculated_score,
                    approved_below_threshold, created_at, updated_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    decision = excluded.decision,
                    operator_id = excluded.operator_id,
                    note = excluded.note,
                    updated_at = excluded.updated_at,
                    metadata_json = excluded.metadata_json;
                """,
                (
                    clean_tid,
                    DECISION_DISCARDED,
                    clean_op,
                    clean_note,
                    cand["original_quality_score"],
                    cand["qg_v2_quality_score"],
                    now_iso,
                    now_iso,
                    json.dumps({"reasons": cand.get("reasons", [])}, ensure_ascii=False),
                ),
            )
            conn.commit()

        # Log auditável em operational_events
        operator_console.log_operational_event(
            component="quality_gate",
            severity=operator_console.SEVERITY_INFO,
            event_type="held_task_human_discarded",
            task_id=clean_tid,
            message=f"Tarefa {clean_tid} descartada da revisão humana pelo operador {clean_op}.",
            metadata={
                "task_id": clean_tid,
                "operator_id": clean_op,
                "note": clean_note,
                "original_quality_score": cand["original_quality_score"],
                "qg_v2_quality_score": cand["qg_v2_quality_score"],
            },
            db_path=effective_db,
        )

        return {
            "status": "success",
            "decision": DECISION_DISCARDED,
            "task_id": clean_tid,
            "message": f"Tarefa {clean_tid} descartada com sucesso da fila de revisão.",
        }

    # Caso DECISION_APPROVED:
    if confirm != CONFIRM_APPROVE_FOR_STOCK:
        raise ValueError(
            f"Confirmação explícita '{CONFIRM_APPROVE_FOR_STOCK}' é obrigatória "
            f"para aprovar tarefas para o estoque."
        )

    # 2. Verificações de bloqueio estritas (fail-closed)
    if not cand["mp4_exists"]:
        raise ValueError(f"Bloqueio: Arquivo de vídeo final-1.mp4 ausente ou vazio para a tarefa '{clean_tid}'.")

    if cand["safety_status"] != const.SAFETY_STATUS_PASS:
        raise ValueError(f"Bloqueio: Safety Gate não aprovado ({cand['safety_status']}). Conteúdo inseguro não pode ser liberado.")

    if cand["copyright_status"] != "PASS":
        cp_detail = cand.get("copyright_reason") or cand.get("reason") or "pendência de direitos"
        raise ValueError(f"Bloqueio: Copyright Gate não aprovado ({cand['copyright_status']}) - {cp_detail}")

    if cand["classification"] == CLASS_ALREADY_PUBLISHED:
        raise ValueError(f"Bloqueio: Tarefa '{clean_tid}' já foi publicada no YouTube.")

    if cand["classification"] == CLASS_ALREADY_SCHEDULED:
        raise ValueError(f"Bloqueio: Tarefa '{clean_tid}' já está agendada no Scheduler.")

    # 3. Tratamento de score
    # Se QG-V2 >= 70.0, é uma recuperação normal QG-V2
    # Se QG-V2 < 70.0, é uma aprovação editorial humana abaixo do limiar (approved_below_threshold = 1)
    # Em NENHUM dos casos o score original é falsificado!
    is_below_threshold = (cand["qg_v2_quality_score"] < 70.0)

    if not is_below_threshold:
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

    # Garante task_platforms com youtube
    scheduler.save_task_platforms(clean_tid, ["youtube"], db_path=effective_db)

    # Garante task_profiles
    assigned_profile = cand.get("profile_id") or profile_manager.DEFAULT_PROFILE_ID
    profile_manager.save_task_profile(clean_tid, assigned_profile, db_path=effective_db)

    # Grava aprovação em operator_video_reviews
    with sqlite3.connect(effective_db) as conn:
        conn.execute(
            """
            INSERT INTO operator_video_reviews (
                task_id, decision, operator_id, note, original_score, recalculated_score,
                approved_below_threshold, created_at, updated_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                decision = excluded.decision,
                operator_id = excluded.operator_id,
                note = excluded.note,
                approved_below_threshold = excluded.approved_below_threshold,
                updated_at = excluded.updated_at,
                metadata_json = excluded.metadata_json;
            """,
            (
                clean_tid,
                DECISION_APPROVED,
                clean_op,
                clean_note,
                cand["original_quality_score"],
                cand["qg_v2_quality_score"],
                1 if is_below_threshold else 0,
                now_iso,
                now_iso,
                json.dumps({
                    "topic": cand["topic"],
                    "approved_by_operator": clean_op,
                    "approved_below_threshold": is_below_threshold,
                }, ensure_ascii=False),
            ),
        )
        conn.commit()

    # Atualiza sm.state
    try:
        from app.services import state as sm
        sm.state.patch_task(
            clean_tid,
            state=const.TASK_STATE_COMPLETE,
            gate_status="approved",
            gate_reason=f"Aprovado humanamente pelo operador {clean_op}" + (" (override editorial)" if is_below_threshold else ""),
            quality_score=cand["qg_v2_quality_score"] if not is_below_threshold else cand["original_quality_score"],
            quality_label=cand["qg_v2_quality_label"] if not is_below_threshold else cand["original_quality_label"],
            video_file=cand["mp4_path"],
            planned_platforms=["youtube"],
            profile_id=assigned_profile,
        )
    except Exception as exc:
        logger.debug(f"[QUALITY_RECOVERY] Falha ao atualizar sm.state para {clean_tid}: {exc}")

    # Log de auditoria em operational_events
    operator_console.log_operational_event(
        component="quality_gate",
        severity=operator_console.SEVERITY_INFO,
        event_type="held_task_human_approved",
        task_id=clean_tid,
        message=(
            f"Tarefa {clean_tid} aprovada pelo operador {clean_op} para o Ready Stock "
            f"(Score original: {cand['original_quality_score']:.1f}, "
            f"QG-V2: {cand['qg_v2_quality_score']:.1f}"
            + (" - Override editorial com score < 70" if is_below_threshold else "")
            + ")."
        ),
        metadata={
            "task_id": clean_tid,
            "operator_id": clean_op,
            "note": clean_note,
            "original_quality_score": cand["original_quality_score"],
            "original_quality_label": cand["original_quality_label"],
            "qg_v2_quality_score": cand["qg_v2_quality_score"],
            "qg_v2_quality_label": cand["qg_v2_quality_label"],
            "approved_below_threshold": is_below_threshold,
            "safety_status": cand["safety_status"],
            "copyright_status": cand["copyright_status"],
            "mp4_path": cand["mp4_path"],
            "profile_id": assigned_profile,
        },
        db_path=effective_db,
    )

    return {
        "status": "success",
        "decision": DECISION_APPROVED,
        "task_id": clean_tid,
        "message": f"Tarefa {clean_tid} aprovada pelo operador e integrada ao Ready Stock.",
        "approved_below_threshold": is_below_threshold,
        "original_quality_score": cand["original_quality_score"],
        "qg_v2_quality_score": cand["qg_v2_quality_score"],
        "ready_stock_eligible": True,
    }


def enqueue_review_command(
    task_id: str,
    action: str,
    operator_id: Optional[str] = "operator",
    note: Optional[str] = None,
    confirm: Optional[str] = None,
    db_path: Optional[str] = None,
) -> int:
    """Enfileira um comando de revisão no SQLite para ser processado pelo nó PRIMARY."""
    effective_db, _ = _resolve_paths(db_path)
    init_review_db(effective_db)

    now_iso = _now_iso()
    with sqlite3.connect(effective_db) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO operator_review_commands (
                task_id, action, operator_id, note, status, created_at
            ) VALUES (?, ?, ?, ?, 'PENDING', ?);
            """,
            (task_id, action, operator_id, note or "", now_iso),
        )
        conn.commit()
        return cursor.lastrowid


def has_pending_review_commands(db_path: Optional[str] = None) -> bool:
    """Verifica de forma ultra-leve se existem comandos pendentes."""
    effective_db, _ = _resolve_paths(db_path)
    if not os.path.isfile(effective_db):
        return False
    with sqlite3.connect(effective_db) as conn:
        if not _table_exists(conn, "operator_review_commands"):
            return False
        row = conn.execute("SELECT 1 FROM operator_review_commands WHERE status = 'PENDING' LIMIT 1;").fetchone()
        return bool(row)


def process_pending_review_commands(
    db_path: Optional[str] = None,
    task_base_dir: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Processa todos os comandos de revisão pendentes. EXECUTADO APENAS PELO NÓ PRIMARY."""
    effective_db, effective_task_dir = _resolve_paths(db_path, task_base_dir)
    init_review_db(effective_db)

    if not operator_console.is_primary_instance(db_path=effective_db):
        return []

    with sqlite3.connect(effective_db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM operator_review_commands WHERE status = 'PENDING' ORDER BY id ASC;"
        ).fetchall()

    results = []
    for r in rows:
        cid = r["id"]
        tid = r["task_id"]
        act = r["action"]
        op = r["operator_id"]
        note = r["note"]
        confirm_token = CONFIRM_APPROVE_FOR_STOCK if str(act).upper() in ("APPROVE", "APPROVED") else CONFIRM_DISCARD_HELD_VIDEO

        now_iso = _now_iso()
        try:
            res = apply_human_review_decision(
                task_id=tid,
                action=act,
                operator_id=op,
                note=note,
                confirm=confirm_token,
                db_path=effective_db,
                task_base_dir=effective_task_dir,
            )
            with sqlite3.connect(effective_db) as conn:
                conn.execute(
                    """
                    UPDATE operator_review_commands
                    SET status = 'COMPLETED', result_json = ?, processed_at = ?, processed_by_node = ?
                    WHERE id = ?;
                    """,
                    (json.dumps(res, ensure_ascii=False), now_iso, "PRIMARY", cid),
                )
                conn.commit()
            results.append({"command_id": cid, "status": "completed", "result": res})
        except Exception as exc:
            with sqlite3.connect(effective_db) as conn:
                conn.execute(
                    """
                    UPDATE operator_review_commands
                    SET status = 'FAILED', error_message = ?, processed_at = ?, processed_by_node = ?
                    WHERE id = ?;
                    """,
                    (str(exc), now_iso, "PRIMARY", cid),
                )
                conn.commit()
            results.append({"command_id": cid, "status": "failed", "error": str(exc)})

    return results


def submit_or_apply_review_decision(
    task_id: str,
    action: str,
    operator_id: Optional[str] = "operator",
    note: Optional[str] = None,
    confirm: Optional[str] = None,
    db_path: Optional[str] = None,
    task_base_dir: Optional[str] = None,
    wait_for_primary_sec: float = 2.0,
) -> Dict[str, Any]:
    """Ponte de execução de decisão de revisão:
    - Se for nó PRIMARY: aplica imediatamente.
    - Se for nó SECONDARY_VIEW_ONLY: enfileira o comando para o PRIMARY e aguarda até wait_for_primary_sec.
    """
    effective_db, effective_task_dir = _resolve_paths(db_path, task_base_dir)
    init_review_db(effective_db)

    is_primary = operator_console.is_primary_instance(db_path=effective_db)
    if is_primary:
        return apply_human_review_decision(
            task_id=task_id,
            action=action,
            operator_id=operator_id,
            note=note,
            confirm=confirm,
            db_path=effective_db,
            task_base_dir=effective_task_dir,
        )

    # Se for SECONDARY_VIEW_ONLY, NÃO executa diretamente!
    cmd_id = enqueue_review_command(
        task_id=task_id,
        action=action,
        operator_id=operator_id,
        note=note,
        confirm=confirm,
        db_path=effective_db,
    )

    import time
    start_t = time.time()
    while (time.time() - start_t) < wait_for_primary_sec:
        time.sleep(0.15)
        with sqlite3.connect(effective_db) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM operator_review_commands WHERE id = ?;", (cmd_id,)).fetchone()
            if row and row["status"] == "COMPLETED":
                res_data = json.loads(row["result_json"]) if row["result_json"] else {}
                return {**res_data, "executed_by": "PRIMARY_BRIDGE", "command_id": cmd_id}
            if row and row["status"] == "FAILED":
                raise ValueError(row["error_message"] or "Falha no processamento pelo nó PRIMARY")

    return {
        "status": "queued",
        "command_id": cmd_id,
        "message": "Decisão registrada com sucesso e enfileirada para execução pelo nó PRIMARY.",
        "task_id": task_id,
        "action": action,
    }

