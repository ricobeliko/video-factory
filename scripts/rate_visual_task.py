"""
scripts/rate_visual_task.py
===========================
CLI para Avaliação Humana de Experiências Visuais (V16.11).

Permite listar as cenas de uma tarefa renderizada e registrar feedback humano
(GOOD, BAD, NEUTRAL, nota 1 a 5 e justificativa).

Uso:
    # Listar cenas de uma task:
    python -m scripts.rate_visual_task TASK_ID --list

    # Avaliar cena específica:
    python -m scripts.rate_visual_task TASK_ID --scene 3 --feedback GOOD --score 5 --reason "Excelente vulcão autêntico"

    # Avaliar o vídeo globalmente (sem afetar cenas individuais automaticamente):
    python -m scripts.rate_visual_task TASK_ID --global-feedback GOOD --score 5 --reason "Vídeo homologado"

    # Avaliar globalmente com confirmação explícita para todas as cenas:
    python -m scripts.rate_visual_task TASK_ID --global-feedback GOOD --score 5 --confirm-all
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from app.services import adaptive_visual_feedback as avf


def main(args: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Registra feedback humano para o pipeline visual (V16.11)"
    )
    parser.add_argument("task_id", help="Identificador único da tarefa (UUID)")
    parser.add_argument("--scene", "-s", type=int, help="Índice da cena a ser avaliada (1..N)")
    parser.add_argument(
        "--feedback",
        "-f",
        choices=["GOOD", "BAD", "NEUTRAL"],
        help="Classificação de qualidade da cena",
    )
    parser.add_argument("--score", type=int, choices=[1, 2, 3, 4, 5], help="Nota de 1 a 5")
    parser.add_argument("--reason", "-r", type=str, help="Justificativa do feedback")
    parser.add_argument(
        "--global-feedback",
        "-g",
        choices=["GOOD", "BAD", "NEUTRAL"],
        help="Avaliação global do vídeo como um todo",
    )
    parser.add_argument(
        "--confirm-all",
        action="store_true",
        help="Se informado junto com --global-feedback, aplica a nota a todas as cenas",
    )
    parser.add_argument("--list", "-l", action="store_true", help="Apenas lista as cenas da tarefa")
    parser.add_argument("--db-path", type=str, help="Caminho alternativo do banco SQLite")

    parsed = parser.parse_args(args)

    task_id = parsed.task_id
    db_path = parsed.db_path

    experiences = avf.get_task_visual_experiences(task_id, db_path=db_path)
    global_fb = avf.get_task_feedback(task_id, db_path=db_path)

    if not experiences:
        print(f"[AVISO] Nenhuma experiência visual encontrada para task_id '{task_id}'.")
        if not parsed.global_feedback:
            return 1

    # Operação 1: Listagem
    if parsed.list or (not parsed.scene and not parsed.feedback and not parsed.global_feedback):
        print("\n" + "=" * 80)
        print(f"EXPERIÊNCIAS VISUAIS REGISTRADAS — Task: {task_id}")
        if global_fb:
            print(
                f"Status Global: {global_fb.get('global_feedback')} "
                f"(Nota: {global_fb.get('global_score')}) — {global_fb.get('global_reason')}"
            )
        print("=" * 80)
        print(
            f"{'Cena':<5} | {'Estratégia':<25} | {'Provedor':<18} | {'Score':<6} | {'Feedback':<11} | {'Nota':<4} | Ativo"
        )
        print("-" * 80)
        for exp in experiences:
            hs = str(exp.get("human_score") or "-")
            print(
                f"{exp['scene_index']:<5} | "
                f"{exp['strategy_selected'][:25]:<25} | "
                f"{exp['provider'][:18]:<18} | "
                f"{exp['final_score']:<6.1f} | "
                f"{exp['human_feedback']:<11} | "
                f"{hs:<4} | "
                f"{exp['asset_id'][:25]}"
            )
        print("=" * 80 + "\n")
        return 0

    # Operação 2: Avaliação de Cena Específica
    if parsed.scene is not None:
        fb_choice = parsed.feedback or "GOOD"
        res = avf.record_human_feedback(
            task_id=task_id,
            scene_index=parsed.scene,
            feedback=fb_choice,
            score=parsed.score,
            reason=parsed.reason,
            confirm_all=False,
            db_path=db_path,
        )
        print(
            f"[SUCESSO] Feedback registrado para Cena {parsed.scene}: "
            f"{res['feedback']} (Nota: {res['score']}) — {res['reason']}"
        )
        return 0

    # Operação 3: Avaliação Global do Vídeo
    if parsed.global_feedback:
        res = avf.record_human_feedback(
            task_id=task_id,
            scene_index=None,
            feedback=parsed.global_feedback,
            score=parsed.score,
            reason=parsed.reason,
            confirm_all=parsed.confirm_all,
            db_path=db_path,
        )
        print(
            f"[SUCESSO] Feedback global registrado para Tarefa {task_id}: {res['global_feedback']} "
            f"(Nota: {res['global_score']}). Cenas atualizadas: {res['scenes_updated']} (confirm_all={parsed.confirm_all})"
        )
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
