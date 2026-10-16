#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
scripts/inspect_held_quality_videos.py
======================================
Ferramenta SOMENTE-LEITURA para inspecionar vídeos gerados que:
1. Possuem MP4 final íntegro no disco (tasks/<task_id>/final-1.mp4).
2. Foram retidos exclusivamente pelo Quality Gate (Quality Score < 70 / REVIEW).
3. Não apresentam rejeições impeditivas de Safety Gate ou Copyright Gate.
4. Ainda não chegaram ao Ready Stock nem foram publicados.

Garante:
- ZERO modificações no banco de dados (read-only).
- ZERO alteração de status ou flags operacionais.
- ZERO publicação ou geração de vídeos.
- Simulação/cálculo do score calibrado sob o Quality Gate V2.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from typing import Any, Dict, List, Optional

# Adiciona o diretório raiz do projeto ao sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.models import const
from app.services import quality_score, safety_gate, scheduler


def inspect_held_videos(
    db_path: Optional[str] = None,
    task_base_dir: Optional[str] = None,
    target_profile_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Inspeciona tarefas retidas por Quality Gate sem alterar nenhum registro."""
    effective_db = db_path or scheduler.get_db_path()
    effective_task_dir = task_base_dir or os.path.join(PROJECT_ROOT, "storage", "tasks")

    if not os.path.isfile(effective_db):
        return {
            "status": "error",
            "message": f"Banco de dados não encontrado em {effective_db}",
            "candidates": [],
        }

    conn = sqlite3.connect(effective_db, timeout=15.0)
    conn.row_factory = sqlite3.Row

    try:
        # 1. Identificar tarefas já publicadas no YouTube (para exclusão)
        published_task_ids = set()
        has_pub = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='publication_events';"
        ).fetchone()
        if has_pub:
            rows = conn.execute(
                "SELECT task_id FROM publication_events WHERE platform='youtube' AND status='success';"
            ).fetchall()
            published_task_ids.update(r["task_id"] for r in rows if r["task_id"])

        has_sched = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='scheduled_posts';"
        ).fetchone()
        if has_sched:
            rows = conn.execute(
                "SELECT task_id FROM scheduled_posts WHERE platform='youtube' AND status IN ('published', 'scheduled');"
            ).fetchall()
            published_task_ids.update(r["task_id"] for r in rows if r["task_id"])

        # 2. Buscar tarefas com avaliação em content_quality_scores
        has_quality = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='content_quality_scores';"
        ).fetchone()
        if not has_quality:
            return {
                "status": "ok",
                "message": "Tabela content_quality_scores inexistente no banco.",
                "candidates": [],
            }

        # Obter a avaliação de qualidade mais recente de cada task_id
        q_rows = conn.execute(
            """
            SELECT cqs.*
            FROM content_quality_scores cqs
            INNER JOIN (
                SELECT task_id, MAX(id) as max_id
                FROM content_quality_scores
                WHERE task_id IS NOT NULL AND task_id != ''
                GROUP BY task_id
            ) latest ON cqs.id = latest.max_id
            ORDER BY cqs.created_at DESC;
            """
        ).fetchall()

        candidates = []
        for q in q_rows:
            tid = q["task_id"]
            if not tid or tid in published_task_ids:
                continue

            orig_score = float(q["quality_score"]) if q["quality_score"] is not None else 0.0
            orig_label = str(q["quality_label"] or "WEAK")

            # 3. Verificar integridade do arquivo MP4 no disco
            video_path = scheduler.get_task_final_video(tid, task_base_dir=effective_task_dir)
            mp4_exists = bool(video_path and os.path.isfile(video_path) and os.path.getsize(video_path) > 0)
            mp4_size_mb = (os.path.getsize(video_path) / (1024 * 1024)) if mp4_exists else 0.0

            # 4. Consultar Safety Gate
            safety_rec = safety_gate.get_safety_assessment(tid, db_path=effective_db) or {}
            safety_status = str(safety_rec.get("safety_status") or "MISSING").upper().strip()
            safety_reasons = safety_rec.get("safety_reasons") or []

            # 5. Consultar Copyright Gate
            copyright_status = "UNKNOWN"
            has_cp = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='copyright_provenance';"
            ).fetchone()
            if has_cp:
                cp_row = conn.execute(
                    "SELECT status FROM copyright_provenance WHERE task_id = ? ORDER BY id DESC LIMIT 1;",
                    (tid,)
                ).fetchone()
                if cp_row:
                    copyright_status = str(cp_row["status"] or "UNKNOWN").upper().strip()
            else:
                copyright_status = "PASS"  # Se tabela não existe, trata como passível de auditoria

            # 6. Avaliar se foi retida por Quality Score
            # Critério: mp4 existe, safety != BLOCK, copyright != BLOCK, orig_score < 70
            is_held_by_quality = (
                mp4_exists
                and safety_status != const.SAFETY_STATUS_BLOCK
                and copyright_status != "BLOCK"
                and orig_score < 70.0
            )

            # 7. Simular recálculo sob QG-V2 (com destination platform 'youtube')
            topic = q["topic"] or tid
            niche = q["niche"]
            preset = q["preset"]
            hook = q["hook_text"]
            act_dur = safety_rec.get("actual_duration")

            qg_v2_eval = quality_score.evaluate_quality(
                topic=topic,
                niche=niche,
                hook_text=hook,
                preset=preset,
                narrative_structure=q["narrative_structure"],
                actual_duration=act_dur,
                task_id=tid,
                platform="youtube",
                persist=False,
                db_path=effective_db,
            )

            v2_score = qg_v2_eval.get("quality_score", orig_score)
            v2_label = qg_v2_eval.get("quality_label", orig_label)

            is_borderline = quality_score.is_borderline_review_candidate(
                quality_score=v2_score,
                safety_status=safety_status,
                copyright_status=copyright_status,
                has_valid_mp4=mp4_exists,
            )

            recommendation = "HELD"
            if is_held_by_quality:
                if v2_score >= 70.0 and v2_label in ("GOOD", "STRONG"):
                    recommendation = "ELIGIBLE_FOR_RE_EVALUATION"
                elif is_borderline:
                    recommendation = "BORDERLINE_REVIEW_CANDIDATE"
                else:
                    recommendation = "REMAIN_HELD"

            candidates.append({
                "task_id": tid,
                "topic": topic,
                "niche": niche or "Geral",
                "mp4_exists": mp4_exists,
                "mp4_size_mb": round(mp4_size_mb, 2),
                "mp4_path": video_path or "N/A",
                "original_quality_score": orig_score,
                "original_quality_label": orig_label,
                "qg_v2_quality_score": v2_score,
                "qg_v2_quality_label": v2_label,
                "safety_status": safety_status,
                "copyright_status": copyright_status,
                "is_held_by_quality": is_held_by_quality,
                "recommendation": recommendation,
                "borderline_candidate": is_borderline,
                "reasons": qg_v2_eval.get("reasons", []),
            })

        return {
            "status": "ok",
            "db_path": effective_db,
            "total_inspected": len(candidates),
            "held_by_quality_count": sum(1 for c in candidates if c["is_held_by_quality"]),
            "eligible_for_re_evaluation_count": sum(1 for c in candidates if c["recommendation"] == "ELIGIBLE_FOR_RE_EVALUATION"),
            "borderline_candidates_count": sum(1 for c in candidates if c["borderline_candidate"]),
            "candidates": candidates,
        }
    finally:
        conn.close()


def format_report(result: Dict[str, Any]) -> str:
    """Formata o relatório em texto legível para operador e console."""
    lines = [
        "=" * 80,
        "VIDEO FACTORY — AUDITORIA READ-ONLY DE VÍDEOS RETIDOS (QG-V2)",
        "=" * 80,
        f"Database: {result.get('db_path')}",
        f"Total Tarefas Inspecionadas: {result.get('total_inspected', 0)}",
        f"Retidos exclusivamente por Quality Gate: {result.get('held_by_quality_count', 0)}",
        f"Elegíveis para Reavaliação no QG-V2 (Score >= 70): {result.get('eligible_for_re_evaluation_count', 0)}",
        f"Candidatos Limítrofes (Score 65.0 - 69.9): {result.get('borderline_candidates_count', 0)}",
        "-" * 80,
    ]

    candidates = result.get("candidates", [])
    if not candidates:
        lines.append("Nenhum vídeo retido encontrado no banco inspecionado.")
    else:
        for c in candidates:
            lines.append(f"Task ID: {c['task_id']}")
            lines.append(f"  Tópico: {c['topic']}")
            lines.append(f"  MP4: {'VÁLIDO' if c['mp4_exists'] else 'INEXISTENTE'} ({c['mp4_size_mb']} MB) -> {c['mp4_path']}")
            lines.append(f"  Safety: {c['safety_status']} | Copyright: {c['copyright_status']}")
            lines.append(f"  Original: {c['original_quality_score']} ({c['original_quality_label']})")
            lines.append(f"  QG-V2 Calibrado (YouTube): {c['qg_v2_quality_score']} ({c['qg_v2_quality_label']})")
            lines.append(f"  Status / Recomendação: {c['recommendation']}")
            if c.get("reasons"):
                lines.append(f"  Motivos principais: {'; '.join(c['reasons'][:3])}")
            lines.append("-" * 80)

    lines.append("AVISO OBRIGATÓRIO: Esta execução é estritamente READ-ONLY.")
    lines.append("Nenhum status foi modificado. Nenhum vídeo foi agendado ou publicado.")
    lines.append("=" * 80)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Inspeciona vídeos retidos por Quality Gate (Read-Only)")
    parser.add_argument("--db-path", default=None, help="Caminho do banco SQLite")
    parser.add_argument("--task-dir", default=None, help="Diretório base das tarefas")
    parser.add_argument("--profile-id", default=None, help="Filtrar por perfil")
    parser.add_argument("--json", action="store_true", help="Saída em formato JSON")

    args = parser.parse_args()
    res = inspect_held_videos(
        db_path=args.db_path,
        task_base_dir=args.task_dir,
        target_profile_id=args.profile_id,
    )

    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print(format_report(res))


if __name__ == "__main__":
    main()
