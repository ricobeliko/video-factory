"""
scripts/run_hybrid_validation.py
================================
Runner do Experimento Controlado V16.8 (Controlled Hybrid Render Validation).

Executa a comparação lado a lado (Baseline vs Hybrid Scene Director),
avalia a auditoria de legendas/narração, sintetiza os prompts contextuais,
gera os artefatos em storage/validation e gera preview de movimento com ffmpeg.
"""

import argparse
import os
import subprocess
import sys

from loguru import logger

from app.services import hybrid_validation, hybrid_visual
from app.utils import utils


def main():
    parser = argparse.ArgumentParser(description="V16.8 Controlled Hybrid Render Validation")
    parser.add_argument(
        "--task-id",
        type=str,
        default="17386147-cb1b-4192-b827-251a1bbd411f",
        help="ID da tarefa histórica a ser utilizada como baseline (default: 17386147... Marte)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="storage/validation",
        help="Diretório onde os artefatos de validação serão persistidos",
    )
    parser.add_argument(
        "--generate-preview",
        action="store_true",
        default=True,
        help="Gera trecho preview leve em MP4 com still motion ffmpeg",
    )
    args = parser.parse_args()

    task_id = args.task_id
    script_path = os.path.join("storage", "tasks", task_id, "script.json")

    if not os.path.exists(script_path):
        logger.error(f"Arquivo de script da tarefa não encontrado: {script_path}")
        sys.exit(1)

    print("\n=======================================================")
    print("  V16.8 — CONTROLLED HYBRID RENDER VALIDATION")
    print("=======================================================")
    print(f"Task ID: {task_id}")
    print(f"Script Data: {script_path}")
    print(f"Output Directory: {args.output_dir}\n")

    experiment = hybrid_validation.run_controlled_hybrid_validation(
        task_id=task_id,
        script_data_path=script_path,
        output_dir=args.output_dir,
    )

    print("\n--- PLACAR GERAL DE QUALIDADE ---")
    print(f"Baseline Quality Score : {experiment.quality_scores.baseline_quality_score} / 100")
    print(f"Hybrid Quality Score   : {experiment.quality_scores.hybrid_quality_score} / 100")
    print(f"Quality Delta          : +{experiment.quality_scores.quality_delta} pts")

    print("\n--- AUDITORIA DE LEGENDAS E NARRAÇÃO (V16.5.1 COMPLIANCE) ---")
    audit = experiment.subtitle_narration_audit
    print(f"Conformidade Estrita   : {'PASS' if audit.is_valid else 'FAIL'}")
    print(f"Posição de Legenda     : {audit.subtitle_position} (seguro inferior)")
    print(f"Font Size              : {audit.font_size} (>= 50 em 9:16)")
    print(f"Cores de Legenda       : texto {audit.text_fore_color}, stroke {audit.stroke_color} ({audit.stroke_width}px)")
    print(f"Voz e Velocidade       : {audit.voice_name} @ rate={audit.voice_rate}")
    if audit.violations:
        print(f"Violações Detectadas   : {audit.violations}")

    print("\n--- RESUMO BASELINE vs HÍBRIDO ---")
    print(f"Total de Cenas         : {experiment.baseline_summary.total_scenes}")
    print(f"Baseline Stock Scenes  : {experiment.baseline_summary.stock_scenes} (Reuso: {experiment.baseline_summary.repeated_assets})")
    print(f"Baseline Score Médio   : {experiment.baseline_summary.average_stock_score}")
    print(f"Cenas com Stock Fraco  : {experiment.baseline_summary.low_score_scenes} (HERO fracas: {experiment.baseline_summary.hero_scenes_with_weak_stock})")
    print(f"Hybrid Stock Scenes    : {experiment.hybrid_summary.stock_scenes}")
    print(f"Hybrid Generated Scenes: {experiment.hybrid_summary.generated_image_scenes}")
    print(f"HERO Scenes Melhoradas : {experiment.hybrid_summary.hero_scenes_improved}")

    print("\n--- RELATÓRIO CENA A CENA ---")
    for s in experiment.scenes:
        print(f"Cena {s.scene_index} [{s.scene_importance}]: score={s.stock_score} -> baseline={s.baseline_visual_source} | hybrid={s.final_hybrid_source} ({s.still_motion_mode or 'none'})")
        print(f"   Candidato Stock: {s.stock_candidate_title}")
        print(f"   Benefício Perceptual: {s.expected_perceptual_benefit}")
        if s.generated_prompt:
            print(f"   Prompt Gerado: {s.generated_prompt[:90]}...")

    # Gera preview de movimento leve se solicitado
    if args.generate_preview:
        print("\n--- GERANDO PREVIEW LEVE COM STILL MOTION (FFMPEG) ---")
        try:
            adapter = hybrid_visual.NanoBananaImageAdapter(mock_mode=True)
            preview_img = os.path.join(args.output_dir, "preview_keyframe_scene_3.png")
            req = hybrid_visual.GenerationRequest(
                scene_id=3,
                prompt="photorealistic 9:16 vertical shot of Olympus Mons colossal volcanic caldera on Mars",
                aspect_ratio="9:16",
                output_path=preview_img,
                target_capability=hybrid_visual.VisualCapability.TEXT_TO_IMAGE,
            )
            res = adapter.generate(req)
            if res.success and res.output_path:
                preview_mp4 = os.path.join(args.output_dir, "preview_still_motion_scene_3.mp4")
                ffmpeg_bin = utils.get_ffmpeg_binary()
                inst = hybrid_visual.generate_still_motion_instructions(
                    image_path=res.output_path,
                    duration_seconds=3.0,
                    aspect_ratio="9:16",
                    mode=hybrid_visual.StillMotionMode.ZOOM_IN,
                )
                cmd = [
                    ffmpeg_bin, "-y", "-loop", "1", "-i", res.output_path,
                    "-vf", inst["ffmpeg_filter"],
                    "-t", "3.0",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    preview_mp4,
                ]
                sub_res = subprocess.run(cmd, capture_output=True, text=True)
                if sub_res.returncode == 0 and os.path.exists(preview_mp4):
                    print(f"Preview gerado com sucesso: {preview_mp4} ({os.path.getsize(preview_mp4)} bytes)")
                    experiment.artifacts_generated.append(preview_mp4)
                else:
                    print(f"Aviso: FFmpeg falhou ao gerar preview: {sub_res.stderr[-200:]}")
        except Exception as exc:
            print(f"Aviso ao gerar preview: {exc}")

    print("\n--- ARTEFATOS GERADOS ---")
    for art in experiment.artifacts_generated:
        print(f" - {art}")

    print(f"\nRender Command Preparado:\n{experiment.render_command_prepared}")
    print("\n[VALIDAÇÃO V16.8 CONCLUÍDA COM SUCESSO]\n")


if __name__ == "__main__":
    main()
