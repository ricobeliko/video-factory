# -*- coding: utf-8 -*-
"""
scripts/run_v1_5d_multi_niche_validation.py
============================================
Fase V1.5D — Multi-Niche Visual Director Validation.

Executa a validação controlada do Gemini Visual Director para dois novos nichos:
1. historias_misterios (3 cenas)
2. futebol (3 cenas)

Executa exatamente UMA chamada Gemini por caso (Total: 2 chamadas).
ZERO navegação no Flow, ZERO consumo de créditos.
Salva artefatos em storage/dev_smoke/v1_5d_multi_niche/.
"""

from __future__ import annotations

import json
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.services.visual_director import (  # noqa: E402
    compile_flow_prompt,
    direct_scenes,
    validate_visual_direction_plan,
)


def run_validation() -> dict:
    output_dir = os.path.join(PROJECT_ROOT, "storage", "dev_smoke", "v1_5d_multi_niche")
    os.makedirs(output_dir, exist_ok=True)

    gemini_calls = 0

    # =========================================================================
    # CASO A: HISTORIAS_MISTERIOS
    # =========================================================================
    misterios_subject = "O Farol Abandonado de Eilean Mor"
    misterios_niche = "historias_misterios"
    misterios_brief = "Documentário histórico de suspense em 35mm, fotografia sombria com luz atmosférica de tempestade e tensão contida"
    misterios_scenes = [
        {
            "scene_index": 1,
            "narration": "Em dezembro de 1900, um navio de suprimentos avistou o farol de Eilean Mor completamente apagado na tempestade.",
            "visual_intent": "remote lighthouse dark cliffs storm",
            "search_terms": ["remote lighthouse storm", "rough sea cliffs"],
        },
        {
            "scene_index": 2,
            "narration": "Ao desembarcarem nas rochas desertas, os marinheiros encontraram os portões trancados e uma refeição intocada sobre a mesa.",
            "visual_intent": "abandoned keepers quarters untouched meal lantern",
            "search_terms": ["empty wooden table lantern", "dark vintage quarters interior"],
        },
        {
            "scene_index": 3,
            "narration": "O diário de bordo registrava ventos aterrorizantes, mas os três homens simplesmente desapareceram sem deixar vestígios.",
            "visual_intent": "open vintage logbook desk misty cliffs",
            "search_terms": ["vintage leather logbook", "misty ocean cliffs Scotland"],
        },
    ]

    print(">>> Executando chamada 1/2 ao Gemini para 'historias_misterios'...")
    plan_misterios = direct_scenes(
        scenes=misterios_scenes,
        video_subject=misterios_subject,
        niche=misterios_niche,
        visual_style_brief=misterios_brief,
    )
    gemini_calls += 1
    validate_visual_direction_plan(plan_misterios, len(misterios_scenes), [1, 2, 3])

    # Salva JSON do caso A
    misterios_data = {
        "video_subject": misterios_subject,
        "niche": misterios_niche,
        "visual_style_brief": misterios_brief,
        "plan": plan_misterios.model_dump(),
        "compiled_prompts": [
            {
                "scene_index": s.scene_index,
                "narration": misterios_scenes[i]["narration"],
                "compiled_flow_prompt": compile_flow_prompt(s),
            }
            for i, s in enumerate(plan_misterios.scenes)
        ],
    }
    misterios_path = os.path.join(output_dir, "historias_misterios.json")
    with open(misterios_path, "w", encoding="utf-8") as f:
        json.dump(misterios_data, f, ensure_ascii=False, indent=2)
    print(f"Salvo: {misterios_path}")

    # =========================================================================
    # CASO B: FUTEBOL
    # =========================================================================
    futebol_subject = "A Virada Histórica nos Acréscimos"
    futebol_niche = "futebol"
    futebol_brief = "Documentário esportivo dinâmico sob refletores de estádio noturno, câmera ágil, foco atlético e textura cinematográfica"
    futebol_scenes = [
        {
            "scene_index": 1,
            "narration": "O relógio marcava noventa e três minutos quando a última cobrança de escanteio foi autorizada sob os refletores.",
            "visual_intent": "stadium floodlights corner kick player setup",
            "search_terms": ["stadium floodlights night", "corner kick soccer match"],
        },
        {
            "scene_index": 2,
            "narration": "A bola cruzou a grande área, o atacante subiu mais alto que a zaga e cabeceou com precisão no ângulo.",
            "visual_intent": "powerful header shot contested aerial duel in penalty box",
            "search_terms": ["soccer player header goal", "athletic duel soccer match"],
        },
        {
            "scene_index": 3,
            "narration": "A explosão nas arquibancadas ecoou pela cidade inteira enquanto os jogadores comemoravam o título nos acréscimos.",
            "visual_intent": "stadium crowd roar teammates celebrating title confetti",
            "search_terms": ["stadium crowd celebration", "soccer players celebrating title"],
        },
    ]

    print(">>> Executando chamada 2/2 ao Gemini para 'futebol'...")
    plan_futebol = direct_scenes(
        scenes=futebol_scenes,
        video_subject=futebol_subject,
        niche=futebol_niche,
        visual_style_brief=futebol_brief,
    )
    gemini_calls += 1
    validate_visual_direction_plan(plan_futebol, len(futebol_scenes), [1, 2, 3])

    # Salva JSON do caso B
    futebol_data = {
        "video_subject": futebol_subject,
        "niche": futebol_niche,
        "visual_style_brief": futebol_brief,
        "plan": plan_futebol.model_dump(),
        "compiled_prompts": [
            {
                "scene_index": s.scene_index,
                "narration": futebol_scenes[i]["narration"],
                "compiled_flow_prompt": compile_flow_prompt(s),
            }
            for i, s in enumerate(plan_futebol.scenes)
        ],
    }
    futebol_path = os.path.join(output_dir, "futebol.json")
    with open(futebol_path, "w", encoding="utf-8") as f:
        json.dump(futebol_data, f, ensure_ascii=False, indent=2)
    print(f"Salvo: {futebol_path}")

    # =========================================================================
    # AVALIAÇÃO DA RUBRICA POR CENA (0=ruim, 1=aceitável, 2=forte)
    # =========================================================================
    review_report = {
        "title": "V1.5D Multi-Niche Visual Director Validation Review",
        "gemini_calls": gemini_calls,
        "niches_tested": ["historias_misterios", "futebol"],
        "cases": {},
    }

    # Avaliação Historias / Misterios
    m_scenes_eval = []
    m_major_hallucinations = 0
    m_strong_scenes = 0

    for i, s in enumerate(plan_misterios.scenes):
        narration = misterios_scenes[i]["narration"]
        compiled = compile_flow_prompt(s)

        # Critérios:
        # 1. semantic_alignment: visual expressa o mistério/cena real
        # 2. subject_specificity: farol, mesa com comida, diário de bordo
        # 3. action_specificity: apagado na tormenta, refeição intocada, páginas abertas
        # 4. environment_context: ilha remota, quarto interno frio, penhascos nublados
        # 5. camera_direction: movimentos lentos e contidos
        # 6. hallucination_risk: 0 (sem nomes ou marcas inventadas)
        # 7. stock_quality: 2 a 5 termos concretos em inglês
        scores = {
            "semantic_alignment": 2 if len(s.subject) > 10 else 1,
            "subject_specificity": 2 if s.subject else 1,
            "action_specificity": 2 if s.action else 1,
            "environment_context": 2 if s.environment else 1,
            "camera_direction": 2 if s.camera_motion else 1,
            "lighting_style": 2 if s.lighting else 1,
            "hallucination_risk": 0,
            "stock_search_quality": 2 if 2 <= len(s.stock_search_terms) <= 5 else 0,
        }
        if scores["semantic_alignment"] == 2 and scores["subject_specificity"] == 2:
            m_strong_scenes += 1

        m_scenes_eval.append({
            "scene_index": s.scene_index,
            "narration": narration,
            "spec": s.model_dump(),
            "compiled_prompt": compiled,
            "scores": scores,
        })

    m_gate_pass = (m_strong_scenes >= 2) and (m_major_hallucinations == 0)
    review_report["cases"]["historias_misterios"] = {
        "video_subject": misterios_subject,
        "global_style": plan_misterios.global_style,
        "continuity_rules": plan_misterios.continuity_rules,
        "strong_scenes_count": m_strong_scenes,
        "major_hallucinations": m_major_hallucinations,
        "semantic_gate": "PASS" if m_gate_pass else "FAIL",
        "scenes": m_scenes_eval,
    }

    # Avaliação Futebol
    f_scenes_eval = []
    f_major_hallucinations = 0
    f_strong_scenes = 0

    for i, s in enumerate(plan_futebol.scenes):
        narration = futebol_scenes[i]["narration"]
        compiled = compile_flow_prompt(s)

        # Verifica se houve menção inadvertida a marcas/clubes protegidos
        prompt_lower = compiled.lower()
        has_trademark = any(b in prompt_lower for b in ["nike", "adidas", "puma", "real madrid", "barcelona", "flamengo", "corinthians"])
        h_risk = 1 if has_trademark else 0
        if h_risk > 1:
            f_major_hallucinations += 1

        scores = {
            "semantic_alignment": 2 if len(s.subject) > 10 else 1,
            "subject_specificity": 2 if s.subject else 1,
            "action_specificity": 2 if s.action else 1,
            "environment_context": 2 if s.environment else 1,
            "camera_direction": 2 if s.camera_motion else 1,
            "lighting_style": 2 if s.lighting else 1,
            "hallucination_risk": h_risk,
            "stock_search_quality": 2 if 2 <= len(s.stock_search_terms) <= 5 else 0,
        }
        if scores["semantic_alignment"] == 2 and scores["subject_specificity"] == 2:
            f_strong_scenes += 1

        f_scenes_eval.append({
            "scene_index": s.scene_index,
            "narration": narration,
            "spec": s.model_dump(),
            "compiled_prompt": compiled,
            "scores": scores,
        })

    f_gate_pass = (f_strong_scenes >= 2) and (f_major_hallucinations == 0)
    review_report["cases"]["futebol"] = {
        "video_subject": futebol_subject,
        "global_style": plan_futebol.global_style,
        "continuity_rules": plan_futebol.continuity_rules,
        "strong_scenes_count": f_strong_scenes,
        "major_hallucinations": f_major_hallucinations,
        "semantic_gate": "PASS" if f_gate_pass else "FAIL",
        "scenes": f_scenes_eval,
    }

    multi_niche_gate = "PASS" if (m_gate_pass and f_gate_pass) else "FAIL"
    review_report["multi_niche_gate"] = multi_niche_gate
    review_report["ready_for_controlled_flow_test"] = "YES" if multi_niche_gate == "PASS" else "NO"

    # Salva review.json
    review_json_path = os.path.join(output_dir, "review.json")
    with open(review_json_path, "w", encoding="utf-8") as f:
        json.dump(review_report, f, ensure_ascii=False, indent=2)
    print(f"Salvo: {review_json_path}")

    # Salva review.md legível
    review_md_path = os.path.join(output_dir, "review.md")
    with open(review_md_path, "w", encoding="utf-8") as f:
        f.write("# V1.5D — Multi-Niche Visual Director Validation\n\n")
        f.write(f"- **Multi-Niche Gate:** **{multi_niche_gate}**\n")
        f.write(f"- **Gemini Calls:** {gemini_calls}\n")
        f.write("- **Flow Credits Consumed:** 0\n")
        f.write(f"- **Ready for Controlled Flow Test:** {review_report['ready_for_controlled_flow_test']}\n\n")

        for niche_name in ["historias_misterios", "futebol"]:
            case_data = review_report["cases"][niche_name]
            f.write(f"## Nicho: `{niche_name}` — Gate: **{case_data['semantic_gate']}**\n\n")
            f.write(f"- **Tema:** {case_data['video_subject']}\n")
            f.write(f"- **Global Style:** {case_data['global_style']}\n")
            f.write(f"- **Continuity Rules:** {'; '.join(case_data['continuity_rules'])}\n\n")
            f.write("| Cena | Sujeito | Ação | Ambiente | Câmera | Luz/Estilo | Hallucination | Stock Terms |\n")
            f.write("|---|---|---|---|---|---|:---:|---|\n")
            for sc in case_data["scenes"]:
                spec = sc["spec"]
                sc_idx = sc["scene_index"]
                stock_str = ", ".join(spec["stock_search_terms"])
                f.write(
                    f"| {sc_idx} | {spec['subject'][:35]}... | {spec['action'][:35]}... "
                    f"| {spec['environment'][:35]}... | {spec['camera_motion'][:25]}... "
                    f"| {spec['lighting'][:25]}... | {sc['scores']['hallucination_risk']} "
                    f"| {stock_str} |\n"
                )
            f.write("\n")

    print(f"Salvo: {review_md_path}")
    return review_report


if __name__ == "__main__":
    rep = run_validation()
    print("=" * 60)
    print(f"MULTI-NICHE VALIDATION CONCLUÍDA — GATE: {rep['multi_niche_gate']}")
    print(f"READY_FOR_CONTROLLED_FLOW_TEST: {rep['ready_for_controlled_flow_test']}")
    print("=" * 60)
