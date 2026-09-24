#!/usr/bin/env python
"""
Ferramenta de Diagnóstico de Gargalos de Produção — Fase V15-B.

Executa auditoria passiva, consolidada e estritamente READ-ONLY sobre:
1. Tarefa de mistério aprovada retida / descompasso de observabilidade
2. Tarefas com arquivo final ausente ou vazio
3. Componentes do Quality Score que causaram rejeições (< 70)
4. Exclusões do Closed Feedback Loop (sample_count = 0)

USO:
    python scripts/diagnose_v15b.py
    python scripts/diagnose_v15b.py --json
    python scripts/diagnose_v15b.py --db-path storage/database/video_factory.db
"""

from __future__ import annotations

import sys

# Redireciona logs para stderr com nível WARNING se a flag --json for fornecida
if "--json" in sys.argv:
    from loguru import logger
    logger.remove()
    logger.add(sys.stderr, level="WARNING")

import argparse
import json
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services import flow_diagnostics


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Diagnóstico de Gargalos do Fluxo de Produção (V15-B)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Gera saída em JSON puro em stdout (logs e avisos vão para stderr)",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Caminho do banco SQLite (padrão: storage/database/video_factory.db)",
    )
    parser.add_argument(
        "--task-base-dir",
        default=None,
        help="Diretório base das tarefas (padrão: storage/tasks)",
    )
    parser.add_argument(
        "--mystery-task-id",
        default=flow_diagnostics.DEFAULT_MYSTERY_TASK_ID,
        help=f"ID da tarefa aprovada de mistério (padrão: {flow_diagnostics.DEFAULT_MYSTERY_TASK_ID})",
    )
    parser.add_argument(
        "--missing-video-task-ids",
        default=",".join(flow_diagnostics.DEFAULT_MISSING_VIDEO_TASK_IDS),
        help="IDs das tarefas com vídeo ausente separados por vírgula",
    )
    return parser.parse_args(list(sys.argv[1:] if argv is None else argv))


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    missing_ids = tuple(t.strip() for t in args.missing_video_task_ids.split(",") if t.strip())

    report = flow_diagnostics.run_v15b_diagnosis(
        db_path=args.db_path,
        task_base_dir=args.task_base_dir,
        mystery_task_id=args.mystery_task_id,
        missing_task_ids=missing_ids,
    )

    if args.json:
        sys.stdout.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        sys.stdout.flush()
        return 0

    # Saída formatada para o operador
    print("=" * 60)
    print(" 📊 DIAGNÓSTICO DE GARGALOS DE PRODUÇÃO — FASE V15-B")
    print("=" * 60)
    print(f"Timestamp: {report.get('timestamp')}")
    print()

    print("--- 1. CONCLUSÕES PRINCIPAIS ---")
    concl = report.get("conclusions", {})
    print(f"MYSTERY_APPROVED_TASK:               {concl.get('MYSTERY_APPROVED_TASK')}")
    print(f"MYSTERY_ROOT_CAUSE:                  {concl.get('MYSTERY_APPROVED_TASK_ROOT_CAUSE')}")
    print(f"MISSING_VIDEO_TASK_1_ROOT_CAUSE:     {concl.get('MISSING_VIDEO_TASK_1_ROOT_CAUSE')}")
    print(f"MISSING_VIDEO_TASK_2_ROOT_CAUSE:     {concl.get('MISSING_VIDEO_TASK_2_ROOT_CAUSE')}")
    print(f"DEFAULT_QUALITY_REJECT_COMPONENTS:   {concl.get('DEFAULT_QUALITY_REJECT_COMPONENTS')}")
    print(f"DEFAULT_CLOSED_LOOP_SAMPLE_ZERO:     {concl.get('DEFAULT_CLOSED_LOOP_SAMPLE_ZERO_REASON')}")
    print(f"MYSTERY_CLOSED_LOOP_SAMPLE_ZERO:     {concl.get('MYSTERY_CLOSED_LOOP_SAMPLE_ZERO_REASON')}")
    print()

    print("--- 2. DETALHES: CANAL DE MISTÉRIO ---")
    m_diag = report.get("mystery_task_diagnosis", {})
    print(f"Task ID: {m_diag.get('task_id')}")
    print(f"Explicação: {m_diag.get('explanation')}")
    print(f"Gate Simulation: {m_diag.get('gate_simulation', {}).get('recover_waiting_task_result')}")
    print()

    print("--- 3. DETALHES: VÍDEOS AUSENTES EM DISCO ---")
    mv_diag = report.get("missing_video_tasks_diagnosis", {})
    for tid, tinfo in mv_diag.get("tasks", {}).items():
        print(f"[{tid}] Causa: {tinfo.get('root_cause')}")
        print(f"  -> {tinfo.get('explanation')}")
    print()

    print("--- 4. DETALHES: REJEIÇÕES DE QUALITY SCORE ---")
    q_diag = report.get("quality_rejects_diagnosis", {})
    print(f"Total Rejeições Auditadas: {q_diag.get('rejected_count')}")
    print(f"Frequência de Componentes Falhos: {q_diag.get('failing_component_frequency')}")
    print(f"Resumo: {q_diag.get('drag_analysis_summary')}")
    print()

    print("--- 5. DETALHES: CLOSED FEEDBACK LOOP ---")
    cl_diag = report.get("closed_loop_diagnosis", {})
    print(f"Default: {cl_diag.get('default_profile', {}).get('conclusion')}")
    print(f"Mystery: {cl_diag.get('mystery_profile', {}).get('conclusion')}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
