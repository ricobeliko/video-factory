"""
scripts/resolve_quiz_assets.py
==============================
VIDEO FACTORY — FASE Q3: AUTOMATIZAÇÃO DE IMAGENS E ASSETS
Ambiente: DEV — D:\\Projetos\\MoneyPrinterTurbo

CLI para resolução automática de imagens de quiz:
Recebe o JSON de quiz (Q2), busca/baixa/prepara imagens (1200x1066)
com deduplicação e proveniência e gera o JSON pronto para renderização (Q1).

Uso:
    .\\.venv\\Scripts\\python.exe scripts/resolve_quiz_assets.py --input-json resource/quiz_templates/quiz_escolhas_impossiveis_gerado.json --output-json storage/poc_quiz/quiz_q3_ready.json
"""

import argparse
import json
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from loguru import logger
from app.services.quiz_assets import QuizAssetManager


def main():
    parser = argparse.ArgumentParser(description="Resolve e prepara ativos visuais de quiz.")
    parser.add_argument(
        "--input-json",
        required=True,
        help="Caminho do JSON de quiz (ex: saída da Q2).",
    )
    parser.add_argument(
        "--output-json",
        default="storage/poc_quiz/quiz_q3_ready.json",
        help="Caminho do JSON resultante pronto para a Quiz Engine Q1.",
    )
    parser.add_argument(
        "--images-dir",
        default="storage/poc_quiz/images_q3",
        help="Diretório onde as imagens preparadas serão salvas.",
    )
    parser.add_argument(
        "--output-video-path",
        default=None,
        help="Caminho personalizado para o vídeo final renderizado.",
    )
    parser.add_argument(
        "--output-thumbnail-path",
        default=None,
        help="Caminho personalizado para a thumbnail independente.",
    )
    args = parser.parse_args()

    if not os.path.exists(args.input_json):
        logger.error(f"Arquivo de entrada não encontrado: {args.input_json}")
        sys.exit(1)

    with open(args.input_json, "r", encoding="utf-8") as f:
        quiz_data = json.load(f)

    manager = QuizAssetManager(default_images_dir=args.images_dir)
    result = manager.process_quiz(
        quiz_data=quiz_data,
        output_images_dir=args.images_dir,
        output_json_path=args.output_json,
        output_video_path=args.output_video_path,
        output_thumbnail_path=args.output_thumbnail_path,
    )

    logger.info(
        f"Concluído! {len(result.get('asset_provenance', []))} imagens resolvidas com proveniência. "
        f"JSON pronto salvo em: {args.output_json}"
    )


if __name__ == "__main__":
    main()
