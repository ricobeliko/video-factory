"""
scripts/run_v16_8_1_real_image_gate.py
======================================
CLI Runner da V16.8.1 — Real Generated Image Quality Gate.

Avalia as 3 cenas HERO da tarefa de Marte, verifica credencial,
aplica o gate de custo externo e prepara os artefatos comparativos.
"""

import argparse
import os
import sys

# Garante raiz do repositório no sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.services import real_image_gate  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="V16.8.1 Real Generated Image Quality Gate Runner")
    parser.add_argument(
        "--task-id",
        type=str,
        default="17386147-cb1b-4192-b827-251a1bbd411f",
        help="ID da tarefa histórica (default: Marte 17386147...)",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Chave de API Gemini / Google AI Studio para autorização de geração real",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Modelo oficial Gemini de imagem (default: gemini-3.1-flash-image)",
    )
    parser.add_argument(
        "--execute-real",
        action="store_true",
        default=False,
        help="Autoriza consumo de créditos externos e executa chamadas reais para as 3 cenas",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="storage/validation/v16_8_1",
        help="Diretório de saída para os artefatos da V16.8.1",
    )
    args = parser.parse_args()

    print("\n=======================================================")
    print("  V16.8.1 — REAL GENERATED IMAGE QUALITY GATE")
    print("=======================================================")
    print(f"Task ID: {args.task_id}")
    print(f"Output Directory: {args.output_dir}")
    print(f"Autorização de Custo Externo: {args.execute_real}\n")

    report = real_image_gate.evaluate_v16_8_1_gate(
        api_key=args.api_key,
        model=args.model,
        output_dir=args.output_dir,
        force_execute=args.execute_real,
        task_id=args.task_id,
    )

    print(f"GATE DECISION                  : {report.gate_decision.value}")
    print(f"STATUS DE CREDENCIAL           : {report.credential_status}")
    print(f"GATE DE CUSTO EXTERNO ATIVO    : {report.external_cost_gate_active}")
    print(f"AUTOMATED PROXY SCORE          : {report.automated_proxy_score} / 100")
    print(f"HUMAN VISUAL REVIEW REQUIRED   : {report.human_visual_review_required}")
    print(f"CENAS HERO SELECIONADAS        : {report.scenes_selected}")
    print(f"GERAÇÕES SOLICITADAS           : {report.generations_requested}")
    print(f"GERAÇÕES COM SUCESSO           : {report.generations_succeeded}")
    print(f"GERAÇÕES COM FALHA             : {report.generations_failed}")
    print(f"QUALITY GATES APROVADOS        : {report.quality_gates_passed}")

    print("\n--- CENAS AVALIADAS ---")
    for s in report.scenes:
        print(f"\n[Cena {s.scene_index}] {s.hero_topic}")
        print(f"  Narração: \"{s.narration}\"")
        print(f"  Stock Candidate: {s.stock_candidate_title} (score={s.stock_score})")
        print(f"  Stock Gap: {s.stock_visual_gap}")
        print(f"  Prompt: {s.prompt[:80]}...")
        print(f"  Still Motion: {s.still_motion_mode}")
        print(f"  Quality Gate: {s.quality_gate_result}")
        if s.still_motion_preview_path:
            print(f"  Preview MP4: {s.still_motion_preview_path}")

    print("\n--- ARTEFATOS GERADOS ---")
    for art in report.artifacts_generated:
        print(f" - {art}")

    if report.gate_decision == real_image_gate.RealGateDecision.PASS:
        print("\n[SUCESSO] 3/3 gerações reais aprovadas.\n")
        return 0
    elif report.gate_decision == real_image_gate.RealGateDecision.PARTIAL:
        print("\n[PARCIAL] Uma ou mais gerações falharam. Gate real NÃO aprovado.\n")
        return 1
    elif report.gate_decision == real_image_gate.RealGateDecision.FAIL:
        print("\n[FALHA] Gate real reprovado.\n")
        return 1
    elif report.gate_decision == real_image_gate.RealGateDecision.NOT_EXECUTED_REQUIRES_HUMAN_GATE:
        print("\n[GATE ATIVO] Execução real não realizada.")
        print(f"Comando de autorização:\n{report.human_authorization_command}\n")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
