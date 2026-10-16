#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
scripts/recover_held_quality_videos.py
======================================
CLI de Reavaliação e Recuperação Segura de Vídeos Retidos por Quality Gate (QG-V2.2).

Modo Padrão: DRY-RUN (Somente Leitura)
- Localiza candidatos retidos no banco e no disco.
- Verifica integridade física do MP4 final.
- Verifica Safety Gate e Copyright Gate.
- Simula o recálculo do Quality Gate V2 com plataforma YouTube.
- Consulta se já está no Ready Stock, agendado ou publicado.
- Classifica cada vídeo em:
    ELIGIBLE | BLOCKED | ALREADY_STOCKED | ALREADY_SCHEDULED | ALREADY_PUBLISHED | NEEDS_REVIEW
- NENHUMA alteração é efetuada no banco ou no disco.

Modo Controlado: APPLY (Exclusivo por Task ID)
- Requer: --apply --task-id <TASK_ID> --confirm RECOVER_HELD_VIDEOS
- Executa a aprovação e promoção para o Ready Stock SEM regeneração e SEM publicação automática.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict

# Garante raiz do projeto no path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.services import quality_recovery


def format_console_report(result: Dict[str, Any]) -> str:
    """Formata o relatório de auditoria e inspeção para o terminal."""
    counts = result.get("counts", {})
    lines = [
        "=" * 90,
        "VIDEO FACTORY — RECUPERAÇÃO SEGURA DE VÍDEOS RETIDOS (QG-V2.2)",
        "=" * 90,
        f"Database: {result.get('db_path')}",
        f"Storage:  {result.get('task_base_dir')}",
        f"Total de Tarefas Inspecionadas: {result.get('total_inspected', 0)}",
        "-" * 90,
        f"  • ELIGIBLE (Aprovados QG-V2 prontos p/ recuperação): {counts.get(quality_recovery.CLASS_ELIGIBLE, 0)}",
        f"  • NEEDS_REVIEW (Score QG-V2 insuficiente < 70):       {counts.get(quality_recovery.CLASS_NEEDS_REVIEW, 0)}",
        f"  • ALREADY_STOCKED (Já presentes no Ready Stock):     {counts.get(quality_recovery.CLASS_ALREADY_STOCKED, 0)}",
        f"  • ALREADY_SCHEDULED (Já no Scheduler ativo):         {counts.get(quality_recovery.CLASS_ALREADY_SCHEDULED, 0)}",
        f"  • ALREADY_PUBLISHED (Já publicados no YouTube):       {counts.get(quality_recovery.CLASS_ALREADY_PUBLISHED, 0)}",
        f"  • BLOCKED (MP4 ausente/0B, Safety ou Copyright FAIL): {counts.get(quality_recovery.CLASS_BLOCKED, 0)}",
        "=" * 90,
    ]

    candidates = result.get("candidates", [])
    if not candidates:
        lines.append("Nenhum candidato localizado no ambiente especificado.")
    else:
        for idx, c in enumerate(candidates, 1):
            mp4_info = f"VÁLIDO ({c['mp4_size_mb']} MB)" if c["mp4_exists"] else "INEXISTENTE/0B"
            lines.append(f"[{idx:02d}] Task ID: {c['task_id']}")
            lines.append(f"     Tópico:      {c['topic']}")
            lines.append(f"     Nicho/Perfil:{c['niche']} (Perfil: {c.get('profile_id') or 'default'})")
            lines.append(f"     MP4 Final:   {mp4_info} -> {c['mp4_path']}")
            lines.append(f"     Safety:      {c['safety_status']} | Copyright: {c['copyright_status']}")
            lines.append(f"     Score Orig:  {c['original_quality_score']:.1f} ({c['original_quality_label']})")
            lines.append(f"     Score QG-V2: {c['qg_v2_quality_score']:.1f} ({c['qg_v2_quality_label']})")
            lines.append(f"     Decisão:     [{c['classification']}] -> {c['reason']}")
            if c.get("reasons"):
                lines.append(f"     Destaques:   {'; '.join(c['reasons'][:2])}")
            lines.append("-" * 90)

    lines.append("AVISO:")
    lines.append("  • Modo padrão: DRY-RUN (somente-leitura, zero mutações).")
    lines.append("  • Para aplicar recuperação segura em uma tarefa elegível:")
    lines.append("    python scripts/recover_held_quality_videos.py --apply --task-id <ID> --confirm RECOVER_HELD_VIDEOS")
    lines.append("=" * 90)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Auditoria e Recuperação Segura de Vídeos Retidos (QG-V2.2)")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Execução somente-leitura (padrão)")
    parser.add_argument("--apply", action="store_true", help="Executa recuperação controlada (requer --task-id e --confirm)")
    parser.add_argument("--task-id", default=None, help="ID específico da tarefa para inspeção ou recuperação")
    parser.add_argument("--confirm", default=None, help=f"Confirmação necessária para apply ('{quality_recovery.CONFIRM_RECOVERY}')")
    parser.add_argument("--db-path", default=None, help="Caminho personalizado do SQLite")
    parser.add_argument("--task-dir", default=None, help="Diretório base das tarefas")
    parser.add_argument("--profile-id", default=None, help="Filtrar por perfil")
    parser.add_argument("--json", action="store_true", help="Exibe saída em formato JSON")

    args = parser.parse_args()

    # Modo APPLY
    if args.apply:
        if not args.task_id:
            print("ERRO: A recuperação via --apply exige a especificação explícita de --task-id <ID>.", file=sys.stderr)
            sys.exit(1)
        if args.confirm != quality_recovery.CONFIRM_RECOVERY:
            print(f"ERRO: Confirmação obrigatória ausente. Use: --confirm {quality_recovery.CONFIRM_RECOVERY}", file=sys.stderr)
            sys.exit(1)

        try:
            res = quality_recovery.recover_held_quality_task(
                task_id=args.task_id,
                confirm=args.confirm,
                db_path=args.db_path,
                task_base_dir=args.task_dir,
            )
            if args.json:
                print(json.dumps(res, indent=2, ensure_ascii=False))
            else:
                print("=" * 70)
                print("RECUPERAÇÃO DE VÍDEO CONCLUÍDA COM SUCESSO (QG-V2.2)")
                print("=" * 70)
                print(f"Task ID:         {res.get('task_id')}")
                print(f"Status:          {res.get('status')}")
                print(f"Score Anterior:  {res.get('original_quality_score')} ({res.get('original_quality_label')})")
                print(f"Novo Score QG-V2:{res.get('qg_v2_quality_score')} ({res.get('qg_v2_quality_label')})")
                print(f"Ready Stock:     ELEGÍVEL (ready_stock_eligible={res.get('ready_stock_eligible')})")
                print(f"Scheduler:       NÃO AGENDADO (Aguardando slot do Growth Mode)")
                print(f"Publicação:      NÃO PUBLICADO (Auto Publish inalterado)")
                print(f"Mensagem:        {res.get('message')}")
                print("=" * 70)
            sys.exit(0)
        except Exception as exc:
            print(f"ERRO ao recuperar tarefa '{args.task_id}': {exc}", file=sys.stderr)
            sys.exit(1)

    # Modo DRY-RUN (padrão)
    if args.task_id:
        cand = quality_recovery.inspect_single_held_task(
            task_id=args.task_id,
            db_path=args.db_path,
            task_base_dir=args.task_dir,
        )
        res = {
            "status": "ok",
            "db_path": args.db_path or scheduler.get_db_path(),
            "task_base_dir": args.task_dir or os.path.join(PROJECT_ROOT, "storage", "tasks"),
            "total_inspected": 1,
            "counts": {cand["classification"]: 1},
            "candidates": [cand],
        }
    else:
        res = quality_recovery.inspect_all_held_tasks(
            db_path=args.db_path,
            task_base_dir=args.task_dir,
            profile_id=args.profile_id,
        )

    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print(format_console_report(res))


if __name__ == "__main__":
    main()
