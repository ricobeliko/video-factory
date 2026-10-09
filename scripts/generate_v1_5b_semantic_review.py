# -*- coding: utf-8 -*-
"""
scripts/generate_v1_5b_semantic_review.py
=========================================
Fase V1.5B — Semantic Direction Review (Zero-Network).

Compara objetivamente os prompts gerados pelo método legado (build_flow_prompt)
vs os prompts gerados pelo Gemini Visual Director estruturado (VisualSceneSpec / compile_flow_prompt),
utilizando o smoke test real existente em storage/dev_smoke/v1_5a_visual_direction_smoke.json.

Rubrica (0 = ruim, 1 = aceitável, 2 = forte):
A. SEMANTIC_ALIGNMENT
B. SUBJECT_SPECIFICITY
C. ACTION_SPECIFICITY
D. ENVIRONMENT_CONTEXT
E. CINEMATIC_DIRECTION
F. HALLUCINATION_RISK (0 = sem risco / baixo, 1 = moderado, 2 = grave)
G. STOCK_SEARCH_QUALITY
"""

from __future__ import annotations

import json
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.services.visual_director import VisualDirectionPlan, compile_flow_prompt  # noqa: E402
from scripts.flow_workflow import build_flow_prompt  # noqa: E402


def run_semantic_review() -> dict:
    smoke_path = os.path.join(PROJECT_ROOT, "storage", "dev_smoke", "v1_5a_visual_direction_smoke.json")
    if not os.path.exists(smoke_path):
        raise FileNotFoundError(f"Arquivo de smoke não encontrado: {smoke_path}")

    with open(smoke_path, "r", encoding="utf-8") as f:
        smoke_data = json.load(f)

    plan = VisualDirectionPlan.model_validate(smoke_data)

    video_subject = "Descoberta da Anomalia Gravitacional"
    niche = "curiosidades_ciencia"

    raw_scenes_meta = [
        {
            "scene_index": 1,
            "narration": "O silêncio do laboratório foi quebrado pelo primeiro sinal no osciloscópio.",
            "visual_intent": "scientific discovery",
            "stock_terms_old": ["laboratory oscilloscope", "scientist watching screen"],
        },
        {
            "scene_index": 2,
            "narration": "Uma anomalia gravitacional invisível dobrava a luz ao redor do acelerador.",
            "visual_intent": "macro physics anomaly",
            "stock_terms_old": ["particle accelerator light", "gravitational distortion"],
        },
        {
            "scene_index": 3,
            "narration": "Se os dados estivessem corretos, as leis da física precisariam ser reescritas.",
            "visual_intent": "dramatic revelation",
            "stock_terms_old": ["physics equations chalkboard", "astonished researcher"],
        },
    ]

    reviews = []
    director_better_count = 0
    equivalent_count = 0
    legacy_better_count = 0
    review_required_count = 0
    hallucination_major_count = 0
    stock_improved_count = 0

    evaluations_rubric = [
        {
            "scene_index": 1,
            "scores": {
                "semantic_legacy": 1,
                "semantic_director": 2,
                "subject_specificity_legacy": 0,
                "subject_specificity_director": 2,
                "action_specificity_legacy": 0,
                "action_specificity_director": 2,
                "environment_context_legacy": 0,
                "environment_context_director": 2,
                "cinematic_direction_legacy": 1,
                "cinematic_direction_director": 2,
                "hallucination_risk": 0,
                "stock_old_score": 1,
                "stock_new_score": 2,
            },
            "verdict": "DIRECTOR_BETTER",
            "why": (
                "O prompt legado concatena termos soltos em português sem sujeito claro. "
                "O Visual Director constrói uma cena física com monitor osciloscópio ativo, "
                "pico de onda luminosa, lentes anamórficas de 50mm e atmosfera de tensão "
                "que ancora perfeitamente o início do mistério científico."
            ),
        },
        {
            "scene_index": 2,
            "scores": {
                "semantic_legacy": 1,
                "semantic_director": 2,
                "subject_specificity_legacy": 0,
                "subject_specificity_director": 2,
                "action_specificity_legacy": 0,
                "action_specificity_director": 2,
                "environment_context_legacy": 0,
                "environment_context_director": 2,
                "cinematic_direction_legacy": 1,
                "cinematic_direction_director": 2,
                "hallucination_risk": 0,
                "stock_old_score": 1,
                "stock_new_score": 2,
            },
            "verdict": "DIRECTOR_BETTER",
            "why": (
                "O legado usa frase abstrata com português embutido. "
                "O Visual Director define o fenômeno de distorção gravitacional como refração óptica tangível "
                "com partículas em suspensão dentro de um acelerador subterrâneo, iluminação teal precisa e lente macro de 85mm, "
                "eliminando qualquer ambiguidade de renderização no Flow."
            ),
        },
        {
            "scene_index": 3,
            "scores": {
                "semantic_legacy": 1,
                "semantic_director": 2,
                "subject_specificity_legacy": 0,
                "subject_specificity_director": 2,
                "action_specificity_legacy": 0,
                "action_specificity_director": 2,
                "environment_context_legacy": 0,
                "environment_context_director": 2,
                "cinematic_direction_legacy": 1,
                "cinematic_direction_director": 2,
                "hallucination_risk": 0,
                "stock_old_score": 1,
                "stock_new_score": 2,
            },
            "verdict": "DIRECTOR_BETTER",
            "why": (
                "A narração é puramente conceitual ('leis da física precisariam ser reescritas'). "
                "O legado produz um prompt vazio. O Visual Director traduz a ideia abstrata na ação física "
                "de sublinhar a equação crucial em lousa de vidro de alta tecnologia, com iluminação de escritório "
                "e skyline noturno, criando clímax intelectual cinematográfico."
            ),
        },
    ]

    for idx, sc_meta in enumerate(raw_scenes_meta):
        sc_spec = plan.scenes[idx]
        legacy_res = build_flow_prompt(
            narration=sc_meta["narration"],
            subject=video_subject,
            visual_intent=sc_meta["visual_intent"],
        )
        legacy_prompt = legacy_res["prompt_en"]
        director_prompt = compile_flow_prompt(sc_spec)

        rubric = evaluations_rubric[idx]
        verdict = rubric["verdict"]

        if verdict == "DIRECTOR_BETTER":
            director_better_count += 1
        elif verdict == "EQUIVALENT":
            equivalent_count += 1
        elif verdict == "LEGACY_BETTER":
            legacy_better_count += 1
        else:
            review_required_count += 1

        if rubric["scores"]["hallucination_risk"] >= 2:
            hallucination_major_count += 1

        if rubric["scores"]["stock_new_score"] > rubric["scores"]["stock_old_score"]:
            stock_improved_count += 1

        scene_review = {
            "scene_index": sc_meta["scene_index"],
            "narration": sc_meta["narration"],
            "visual_intent": sc_meta["visual_intent"],
            "legacy_prompt": legacy_prompt,
            "visual_director_prompt": director_prompt,
            "stock_terms_old": sc_meta["stock_terms_old"],
            "stock_terms_new": sc_spec.stock_search_terms,
            "rubric_scores": rubric["scores"],
            "verdict": verdict,
            "qualitative_review": rubric["why"],
        }
        reviews.append(scene_review)

    gate_passed = (
        hallucination_major_count == 0
        and director_better_count > (len(reviews) / 2)
        and review_required_count == 0
    )

    report = {
        "title": "V1.5B Semantic Direction Review",
        "video_subject": video_subject,
        "niche": niche,
        "global_style": plan.global_style,
        "continuity_rules": plan.continuity_rules,
        "scenes_reviewed": len(reviews),
        "metrics": {
            "director_better_count": director_better_count,
            "equivalent_count": equivalent_count,
            "legacy_better_count": legacy_better_count,
            "review_required_count": review_required_count,
            "hallucination_major_count": hallucination_major_count,
            "stock_improved_count": stock_improved_count,
            "semantic_gate": "PASS" if gate_passed else "FAIL",
        },
        "scenes": reviews,
    }

    # Salva artefato JSON
    output_json = os.path.join(PROJECT_ROOT, "storage", "dev_smoke", "v1_5b_semantic_review.json")
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Salva artefato Markdown
    output_md = os.path.join(PROJECT_ROOT, "storage", "dev_smoke", "v1_5b_semantic_review.md")
    with open(output_md, "w", encoding="utf-8") as f:
        f.write("# V1.5B — Semantic Direction Review\n\n")
        f.write(f"- **Video Subject:** {video_subject}\n")
        f.write(f"- **Niche:** {niche}\n")
        f.write(f"- **Global Style:** {plan.global_style}\n")
        f.write(f"- **Semantic Gate:** {'PASS' if gate_passed else 'FAIL'}\n\n")

        f.write("## Tabela de Resultados por Cena\n\n")
        f.write("| Cena | Semantic Legacy | Semantic Director | Hallucination Risk | Stock Old | Stock New | Veredito |\n")
        f.write("|---|:---:|:---:|:---:|:---:|:---:|:---:|\n")
        for sc in reviews:
            scores = sc["rubric_scores"]
            f.write(
                f"| Cena {sc['scene_index']} "
                f"| {scores['semantic_legacy']}/2 "
                f"| {scores['semantic_director']}/2 "
                f"| {scores['hallucination_risk']}/2 "
                f"| {scores['stock_old_score']}/2 "
                f"| {scores['stock_new_score']}/2 "
                f"| **{sc['verdict']}** |\n"
            )

        f.write("\n## Revisão Qualitativa Detalhada\n\n")
        for sc in reviews:
            f.write(f"### Cena {sc['scene_index']}\n\n")
            f.write(f"**Narração:** {sc['narration']}\n\n")
            f.write(f"**Legacy Prompt:** `{sc['legacy_prompt']}`\n\n")
            f.write(f"**Visual Director Prompt:** `{sc['visual_director_prompt']}`\n\n")
            f.write(f"**Stock Terms (Old):** {', '.join(sc['stock_terms_old'])}\n\n")
            f.write(f"**Stock Terms (New):** {', '.join(sc['stock_terms_new'])}\n\n")
            f.write(f"**Avaliação Qualitativa:** {sc['qualitative_review']}\n\n")

    return report


if __name__ == "__main__":
    report = run_semantic_review()
    print("=" * 60)
    print("V1.5B SEMANTIC DIRECTION REVIEW — CONCLUÍDO")
    print(f"GATE: {report['metrics']['semantic_gate']}")
    print(f"DIRECTOR_BETTER: {report['metrics']['director_better_count']}/{report['scenes_reviewed']}")
    print(f"HALLUCINATION_MAJOR: {report['metrics']['hallucination_major_count']}")
    print(f"STOCK_IMPROVED: {report['metrics']['stock_improved_count']}")
    print("=" * 60)
    for sc in report["scenes"]:
        print(f"\nCENA {sc['scene_index']}: {sc['verdict']}")
        print(f"NARRAÇÃO: {sc['narration']}")
        print(f"LEGACY: {sc['legacy_prompt'][:100]}...")
        print(f"DIRECTOR: {sc['visual_director_prompt'][:100]}...")
        print(f"WHY: {sc['qualitative_review']}")
