"""
scripts/generate_quiz_content.py
================================
VIDEO FACTORY — FASE Q2: CLI DE GERAÇÃO AUTOMÁTICA DE CONTEÚDO

Gera automaticamente conteúdo estruturado original em JSON para o Quiz Engine:
- Nichos subjetivos (dilemas de escolhas impossíveis) ou factuais (trivia/conhecimentos verificados).
- Deduplicação persistente contra histórico anterior.
- Ganchos de retenção dinâmicos contextualizados com a última pergunta.
- Encerramentos configuráveis por canal.
- Validação imediata de conformidade com o schema do Quiz Engine.

Uso:
    .\\.venv\\Scripts\\python.exe scripts/generate_quiz_content.py --niche curiosidades_dilemas --format subjective --output resource/quiz_templates/quiz_escolhas_impossiveis_gerado.json
    .\\.venv\\Scripts\\python.exe scripts/generate_quiz_content.py --niche curiosidades_animais --format factual --output resource/quiz_templates/quiz_conhecimentos_animais_factual.json
"""

import argparse
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from loguru import logger
from app.services.quiz_generator import QuizContentGenerator
from scripts.poc_quiz_render import QuizConfig


def parse_args():
    parser = argparse.ArgumentParser(description="Gerador Automático de Conteúdo para Quiz (Fase Q2)")
    parser.add_argument("--niche", type=str, default="curiosidades_animais", help="Nicho temático do quiz")
    parser.add_argument("--format", type=str, choices=["subjective", "factual"], default="factual", help="Formato do quiz")
    parser.add_argument("--num-questions", type=int, default=6, help="Quantidade de perguntas no quiz")
    parser.add_argument("--title", type=str, default=None, help="Título do quiz")
    parser.add_argument(
        "--closing-type",
        type=str,
        choices=["engagement_cta", "score_challenge", "quiz_choice_religious"],
        default="engagement_cta",
        help="Tipo de encerramento do canal",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Caminho do arquivo JSON de saída",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    generator = QuizContentGenerator()

    niche = args.niche
    format_type = args.format
    num_questions = args.num_questions
    title = args.title
    closing_type = args.closing_type

    if not args.output:
        slug = niche.replace(" ", "_").lower()
        output_json = os.path.join(ROOT_DIR, "resource", "quiz_templates", f"quiz_{slug}_{format_type}.json")
    else:
        output_json = os.path.abspath(args.output) if os.path.isabs(args.output) else os.path.join(ROOT_DIR, args.output)

    logger.info(f"Gerando conteúdo: nicho='{niche}', formato='{format_type}', perguntas={num_questions}")
    raw_quiz = generator.generate_quiz_structure(
        niche=niche,
        format_type=format_type,
        num_questions=num_questions,
        quiz_title=title,
        closing_type=closing_type,
    )

    # Exporta para arquivo JSON e valida compatibilidade com QuizConfig
    config = generator.export_to_quiz_config(raw_quiz, output_json)

    # Validação do Schema
    assert len(config.questions) == num_questions, f"Esperado {num_questions} perguntas, obtido {len(config.questions)}"
    assert config.retention_hook["enabled"] is True, "Gancho de retenção ausente"
    assert config.output_video_path != "", "Caminho de vídeo ausente"
    assert config.output_thumbnail_path != "", "Caminho de thumbnail ausente"

    # Verificação de fatos se for factual
    if format_type == "factual":
        verified_count = sum(1 for q in config.questions if q.get("verified"))
        logger.info(f"Perguntas com checagem factual estrita: {verified_count}/{num_questions}")

    print("\n" + "=" * 60)
    print("STATUS = CONTEUDO_GERADO_E_VALIDADO")
    print(f"NICHE = {config.niche}")
    print(f"FORMAT_TYPE = {format_type}")
    print(f"QUIZ_TITLE = {config.quiz_title}")
    print(f"JSON_PATH = {output_json}")
    print(f"TOTAL_QUESTIONS = {len(config.questions)}")
    print(f"RETENTION_HOOK = {config.retention_hook['narration']}")
    print(f"CLOSING_HEADER = {config.questions[-1]['header']}")
    print("ENGINE_COMPATIBILITY = VALIDADO (Aceito 100% pelo QuizConfig)")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
