# -*- coding: utf-8 -*-
"""
app/services/visual_director.py
===============================
Fase V1.5A — Gemini Visual Director Foundation.

Transforma um ScenePlan em direção visual estruturada e cinematográfica
utilizando Structured Output nativo do Google Gemini (Pydantic / response_schema).

Gera:
1. VisualDirectionPlan global (global_style, continuity_rules).
2. VisualSceneSpec por cena (subject, action, environment, lighting, style,
   camera_motion, composition, lens_focus, ambiance, stock_search_terms,
   visual_importance, rationale).
3. Compilador determinístico de prompts Flow/Veo seguindo a ordem de especificação
   do Google Veo (vertical 9:16 portrait).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Literal, Optional

from loguru import logger
from pydantic import BaseModel, Field

from app.config import config
from app.models.llm_provider import get_llm_provider
from app.services.llm import sanitize_error_message


# =============================================================================
# Contratos Pydantic Estruturados
# =============================================================================

class VisualSceneSpec(BaseModel):
    """Especificação visual detalhada de uma cena individual."""
    scene_index: int = Field(..., ge=1, description="1-based scene index matching the scene plan")
    subject: str = Field(..., min_length=1, description="Concrete visual subject or focal entity in the scene")
    action: str = Field(..., min_length=1, description="Specific visual action or movement taking place")
    environment: str = Field(..., min_length=1, description="Physical environment, setting or backdrop")
    lighting: str = Field(..., min_length=1, description="Lighting style, direction, intensity and color palette")
    style: str = Field(..., min_length=1, description="Cinematic style, e.g. archival 35mm, realistic documentary, noir")
    camera_motion: str = Field(..., min_length=1, description="Camera movement, e.g. slow forward push-in, low-angle tracking")
    composition: str = Field(..., min_length=1, description="Framing and spatial composition, vertical 9:16 portrait oriented")
    lens_focus: str = Field(..., min_length=1, description="Lens type, depth of field and focus area, e.g. 50mm shallow depth of field")
    ambiance: str = Field(..., min_length=1, description="Atmosphere, mood, weather and emotional tone")
    stock_search_terms: List[str] = Field(
        ...,
        min_length=2,
        max_length=5,
        description="2 to 5 concrete English search terms for stock footage fallback",
    )
    visual_importance: Literal["high", "medium", "low"] = Field(
        ...,
        description="Visual impact level of the scene",
    )
    rationale: str = Field(..., min_length=1, max_length=300, description="Brief justification for the visual choices")


class VisualDirectionPlan(BaseModel):
    """Plano global de direção visual abrangendo todas as cenas do vídeo."""
    global_style: str = Field(..., min_length=1, description="Overall aesthetic and visual identity of the video")
    continuity_rules: List[str] = Field(
        ...,
        max_length=4,
        description="Up to 4 visual continuity rules across scenes",
    )
    scenes: List[VisualSceneSpec] = Field(
        ...,
        description="Visual specifications for all scenes in the scene plan",
    )


# =============================================================================
# Compilador Determinístico de Prompt (Padrão Google Veo)
# =============================================================================

TECHNICAL_CONSTRAINTS = (
    "vertical 9:16 portrait, single coherent cinematic shot, "
    "no text, no captions, no subtitles, no watermark"
)


def compile_flow_prompt(spec: VisualSceneSpec) -> str:
    """
    Compila um prompt determinístico para o Google Flow / Veo a partir da especificação visual.
    Segue a ordem recomendada pela documentação oficial do Google Veo:
    1. subject
    2. action
    3. environment/context
    4. style
    5. composition
    6. camera motion
    7. lens/focus
    8. lighting
    9. ambiance
    10. technical constraints

    IMPORTANTE:
    NÃO adiciona 'photorealistic' indiscriminadamente; o estilo vem do spec.style
    (documental, realista, ilustração, animação, archival, noir, etc.).
    """
    elements = [
        spec.subject.strip(),
        spec.action.strip(),
        spec.environment.strip(),
        spec.style.strip(),
        spec.composition.strip(),
        spec.camera_motion.strip(),
        spec.lens_focus.strip(),
        spec.lighting.strip(),
        spec.ambiance.strip(),
        TECHNICAL_CONSTRAINTS,
    ]
    cleaned = []
    for el in elements:
        c = el.rstrip(". ").strip()
        if c:
            cleaned.append(c)
    return ". ".join(cleaned) + "."


# =============================================================================
# Validação Estrita do Plano
# =============================================================================

def validate_visual_direction_plan(
    plan: VisualDirectionPlan,
    expected_scene_count: int,
    expected_indices: List[int],
) -> None:
    """
    Valida rigorosamente o plano retornado pelo Gemini:
    - Quantidade de cenas igual ao esperado.
    - scene_index exatamente iguais, sem duplicados e sem ausentes.
    - Nenhum campo obrigatório vazio.
    - stock_search_terms entre 2 e 5 itens.
    - continuity_rules com no máximo 4 itens.
    - visual_importance dentro dos valores permitidos.
    """
    if not isinstance(plan, VisualDirectionPlan):
        raise ValueError(f"VISUAL_DIRECTION_INVALID: Expected VisualDirectionPlan, got {type(plan)}")

    if not plan.global_style or not plan.global_style.strip():
        raise ValueError("VISUAL_DIRECTION_INVALID: global_style is empty")

    if len(plan.continuity_rules) > 4:
        raise ValueError(
            f"VISUAL_DIRECTION_INVALID: continuity_rules exceeds limit of 4 (got {len(plan.continuity_rules)})"
        )

    if len(plan.scenes) != expected_scene_count:
        raise ValueError(
            f"VISUAL_DIRECTION_INVALID: Scene count mismatch. Expected {expected_scene_count}, got {len(plan.scenes)}"
        )

    received_indices = [s.scene_index for s in plan.scenes]
    if len(received_indices) != len(set(received_indices)):
        duplicates = [idx for idx in received_indices if received_indices.count(idx) > 1]
        raise ValueError(f"VISUAL_DIRECTION_INVALID: Duplicate scene_index found: {set(duplicates)}")

    if received_indices != expected_indices:
        missing = set(expected_indices) - set(received_indices)
        extra = set(received_indices) - set(expected_indices)
        raise ValueError(f"VISUAL_DIRECTION_INVALID: Scene index mismatch. Missing: {missing}, Extra: {extra}")

    string_fields = [
        "subject",
        "action",
        "environment",
        "lighting",
        "style",
        "camera_motion",
        "composition",
        "lens_focus",
        "ambiance",
        "rationale",
    ]

    for s in plan.scenes:
        for field_name in string_fields:
            val = getattr(s, field_name, None)
            if not isinstance(val, str) or not val.strip():
                raise ValueError(
                    f"VISUAL_DIRECTION_INVALID: Scene {s.scene_index} has empty or invalid field '{field_name}'"
                )

        if not (2 <= len(s.stock_search_terms) <= 5):
            raise ValueError(
                f"VISUAL_DIRECTION_INVALID: Scene {s.scene_index} stock_search_terms count must be between 2 and 5 (got {len(s.stock_search_terms)})"
            )

        for term in s.stock_search_terms:
            if not isinstance(term, str) or not term.strip():
                raise ValueError(
                    f"VISUAL_DIRECTION_INVALID: Scene {s.scene_index} contains empty stock_search_term"
                )

        if s.visual_importance not in ("high", "medium", "low"):
            raise ValueError(
                f"VISUAL_DIRECTION_INVALID: Scene {s.scene_index} invalid visual_importance: '{s.visual_importance}'"
            )


# =============================================================================
# Resolução de Configuração Gemini
# =============================================================================

def get_gemini_config(app_config: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """
    Recupera a configuração ativa do Gemini a partir do config.toml / provider registry.
    Reutiliza api_key, model_name e base_url sem criar chaves redundantes.
    """
    runtime_app_config = app_config if app_config is not None else config.app
    provider = get_llm_provider("gemini")

    api_key = str(runtime_app_config.get("gemini_api_key", "")).strip()
    configured_model = str(runtime_app_config.get("gemini_model_name", "")).strip()

    if provider:
        model_name = provider.resolve_model_name(configured_model)
        configured_base_url = str(runtime_app_config.get(provider.config_key("base_url"), "")).strip()
        base_url = provider.resolve_base_url(configured_base_url)
    else:
        model_name = configured_model or "gemini-2.5-flash"
        base_url = str(runtime_app_config.get("gemini_base_url", "")).strip()

    return {
        "api_key": api_key,
        "model_name": model_name,
        "base_url": base_url,
    }


# =============================================================================
# Prompt Builder para o Visual Director
# =============================================================================

SYSTEM_DIRECTOR_PROMPT = """You are an expert cinematic Visual Director for short-form video (YouTube Shorts, TikTok, Reels, 9:16 vertical portrait).
Your task is to transform a complete narrative ScenePlan into a cohesive, shot-by-shot visual direction plan.

CORE SEMANTIC RULES:
1. VISUALIZE ACTUAL MEANING: Interpret the whole idea and narrative context of the scene, not isolated words or superficial puns.
2. CONCRETE SUBJECT & ACTION: Identify a concrete visual subject and a clearly visualizable action for each scene.
3. COMPATIBLE ENVIRONMENT: Set each scene in a realistic, contextual physical environment. Avoid disconnected abstract concepts.
4. DO NOT INVENT UNVERIFIED SPECIFICS: Do not invent names of unmentioned people, real brands, or historical artifacts not supported by the script. Use high-end, generic cinematic descriptions when specific details are unknown.
5. AESTHETIC CONTINUITY: Maintain visual identity and stylistic continuity across all scenes via global_style and continuity_rules (max 4 rules).
6. NICHE ADAPTATION: Tailor the style and camera language to the niche:
   - "curiosidades_ciencia": visual clarity, scientific/macro imagery, scale visualization, realistic cinematic science.
   - "historias_misterios": suspense, controlled shadows, atmospheric environments, restrained camera movement.
   - "futebol": energy, stadium/training/pitch context, dynamic sports cinematography.
     POLICY-SAFE SPORTS GUIDANCE (CRITICAL FOR FOOTBALL):
     When the script does NOT explicitly cite a specific real person, famous athlete, or real club:
     * Use fictional, non-identifiable football players.
     * No resemblance to real or famous athletes.
     * No real club logos, no sponsor emblems, no branded uniforms, no famous jersey numbers.
     * Use generic unbranded athletic kits (e.g. solid color jersey or simple athletic stripes).
     * No recognizable celebrity likeness.
     * Prioritize athletic action over facial identity (focus on physical momentum, ball trajectory, and body movement).
     * Camera framing must favor action: medium sports shots, wide pitch views, side or rear three-quarter tracking, dynamic ball follow. Faces may exist naturally and incidentally, but must NEVER be the central recognizable identity or close-up portrait feature.
     * Do NOT describe athletes as mannequins or hide faces artificially; preserve high-end natural cinematic sports quality.
   - other niches: strictly respect the topic and genre tone.
7. PREVENT REPETITION: Differentiate angles, focal lengths, and camera movements across sequential scenes to keep viewer retention high.
8. STOCK SEARCH TERMS: For each scene, generate 2 to 5 concrete English search terms (objects, locations, environments) suitable for stock video fallback (e.g. "ancient stone ruin", "deep space nebula", "vintage laboratory microscope").
9. VISUAL IMPORTANCE: Rate each scene's narrative impact as "high", "medium", or "low".
10. STRICT CONFORMITY: Return all scenes matching their exact scene_index."""


def build_director_prompt(
    normalized_scenes: List[Dict[str, Any]],
    video_subject: str,
    niche: str = "",
    visual_style_brief: str = "",
) -> str:
    payload = {
        "video_subject": video_subject,
        "niche": niche or "general",
        "visual_style_brief": visual_style_brief or "cinematic",
        "total_scenes": len(normalized_scenes),
        "scenes": normalized_scenes,
    }
    futebol_directive = ""
    is_futebol = (niche.lower() == "futebol") or ("futebol" in video_subject.lower()) or ("football" in niche.lower())
    if is_futebol:
        futebol_directive = (
            "\n\nSPECIAL DIRECTIVE FOR FOOTBALL NICHE:\n"
            "This video depicts fictional football moments. Ensure all generated scene specs depict fictional, "
            "non-identifiable players with no resemblance to famous real athletes, no real club logos, no branded jerseys, "
            "and prioritize athletic action over facial identity (focusing on sports action, movement, and ball trajectory)."
        )

    return (
        f"{SYSTEM_DIRECTOR_PROMPT}\n\n"
        f"Input ScenePlan data:\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
        f"{futebol_directive}\n\n"
        f"Generate the complete VisualDirectionPlan for all {len(normalized_scenes)} scenes."
    )


# =============================================================================
# Serviço Principal: direct_scenes
# =============================================================================

def direct_scenes(
    scenes: List[Any],
    video_subject: str,
    niche: str = "",
    visual_style_brief: str = "",
    app_config: Optional[Dict[str, Any]] = None,
    client: Optional[Any] = None,
) -> VisualDirectionPlan:
    """
    Executa a direção visual completa para todas as cenas em UMA ÚNICA chamada ao Gemini.
    Retorna o VisualDirectionPlan validado.
    Em caso de falha ou invalidação, levanta VISUAL_DIRECTOR_FAILED.
    """
    if not scenes:
        raise ValueError("VISUAL_DIRECTOR_FAILED: scenes list cannot be empty")

    normalized_scenes: List[Dict[str, Any]] = []
    expected_indices: List[int] = []

    for sc in scenes:
        if hasattr(sc, "scene_index"):
            s_idx = sc.scene_index
            narration = getattr(sc, "narration", "")
            visual_intent = getattr(sc, "visual_intent", "")
            search_terms = getattr(sc, "search_terms", [])
        elif isinstance(sc, dict):
            s_idx = sc.get("scene_index")
            narration = sc.get("narration", "")
            visual_intent = sc.get("visual_intent", "")
            search_terms = sc.get("search_terms", [])
        else:
            raise ValueError(f"VISUAL_DIRECTOR_FAILED: Unsupported scene item type: {type(sc)}")

        normalized_scenes.append({
            "scene_index": s_idx,
            "narration": narration,
            "current_visual_intent": visual_intent or "cinematic",
            "current_search_terms": list(search_terms) if search_terms else [],
        })
        expected_indices.append(s_idx)

    gemini_cfg = get_gemini_config(app_config)
    api_key = gemini_cfg["api_key"]
    model_name = gemini_cfg["model_name"]
    base_url = gemini_cfg["base_url"]

    if not api_key:
        raise ValueError("VISUAL_DIRECTOR_FAILED: gemini_api_key is not set in configuration")

    full_prompt = build_director_prompt(
        normalized_scenes=normalized_scenes,
        video_subject=video_subject,
        niche=niche,
        visual_style_brief=visual_style_brief,
    )

    logger.info(
        f"[VisualDirector] Solicitando direção visual via Gemini ({model_name}) "
        f"para {len(normalized_scenes)} cenas (UMA chamada, Structured Output)..."
    )

    try:
        from google import genai
        from google.genai import types

        http_options = types.HttpOptions(base_url=base_url) if base_url else None
        generation_config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=VisualDirectionPlan,
            max_output_tokens=8192,
        )

        if client is not None:
            # Reutiliza cliente fornecido (injeção para mocks / testes)
            response = client.models.generate_content(
                model=model_name,
                contents=full_prompt,
                config=generation_config,
            )
        else:
            with genai.Client(
                api_key=api_key,
                http_options=http_options,
            ) as real_client:
                response = real_client.models.generate_content(
                    model=model_name,
                    contents=full_prompt,
                    config=generation_config,
                )

        plan: Optional[VisualDirectionPlan] = None
        if hasattr(response, "parsed") and isinstance(response.parsed, VisualDirectionPlan):
            plan = response.parsed
        elif hasattr(response, "parsed") and isinstance(response.parsed, dict):
            plan = VisualDirectionPlan.model_validate(response.parsed)
        elif hasattr(response, "text") and response.text:
            plan = VisualDirectionPlan.model_validate_json(response.text)
        else:
            raise ValueError("Empty response received from Gemini model")

        if plan is None:
            raise ValueError("Failed to parse Gemini response into VisualDirectionPlan")

        validate_visual_direction_plan(plan, len(normalized_scenes), expected_indices)
        logger.info(
            f"[VisualDirector] Direção visual gerada com sucesso: "
            f"estilo='{plan.global_style}', {len(plan.scenes)} cenas validadas."
        )
        return plan

    except Exception as exc:
        err_msg = sanitize_error_message(exc)
        logger.error(f"[VisualDirector] Falha na direção visual: {err_msg}")
        if "VISUAL_DIRECTION_INVALID" in err_msg or "VISUAL_DIRECTOR_FAILED" in err_msg:
            if isinstance(exc, ValueError):
                raise ValueError(err_msg) from None
            raise RuntimeError(err_msg) from None
        raise RuntimeError(f"VISUAL_DIRECTOR_FAILED: {err_msg}") from None


# =============================================================================
# CLI Preview Helper
# =============================================================================

def preview_visual_direction(
    manifest_or_dir: str,
    brief: str = "",
) -> Dict[str, Any]:
    """Inspeciona um projeto e gera prévia da direção visual."""
    manifest_path = manifest_or_dir
    if os.path.isdir(manifest_or_dir):
        manifest_path = os.path.join(manifest_or_dir, "manifest.json")

    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"Manifest não encontrado: {manifest_path}")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    scenes = manifest.get("scenes", [])
    subject = manifest.get("video_subject", "") or manifest.get("subject", "")
    niche = manifest.get("niche", "")

    plan = direct_scenes(
        scenes=scenes,
        video_subject=subject,
        niche=niche,
        visual_style_brief=brief,
    )

    summary: List[Dict[str, Any]] = []
    for sc_spec in plan.scenes:
        compiled_prompt = compile_flow_prompt(sc_spec)
        summary.append({
            "scene_index": sc_spec.scene_index,
            "subject": sc_spec.subject,
            "action": sc_spec.action,
            "environment": sc_spec.environment,
            "style": sc_spec.style,
            "visual_importance": sc_spec.visual_importance,
            "stock_search_terms": sc_spec.stock_search_terms,
            "compiled_flow_prompt": compiled_prompt,
        })

    return {
        "global_style": plan.global_style,
        "continuity_rules": plan.continuity_rules,
        "scenes": summary,
    }


def main():
    parser = argparse.ArgumentParser(description="Gemini Visual Director — Preview")
    parser.add_argument("target", help="Caminho do manifest.json ou diretório do projeto")
    parser.add_argument("--brief", default="", help="Breve diretriz de estilo visual")
    args = parser.parse_args()

    try:
        res = preview_visual_direction(args.target, brief=args.brief)
        print("\n" + "=" * 70)
        print("VISUAL DIRECTOR PREVIEW")
        print("=" * 70)
        print(f"Global Style: {res['global_style']}")
        print(f"Continuity Rules: {res['continuity_rules']}")
        print("-" * 70)
        for s in res["scenes"]:
            print(f"\n[Cena {s['scene_index']:02d}] Importance: {s['visual_importance'].upper()}")
            print(f"  Subject:     {s['subject']}")
            print(f"  Action:      {s['action']}")
            print(f"  Environment: {s['environment']}")
            print(f"  Stock Terms: {s['stock_search_terms']}")
            print(f"  Flow Prompt:\n    {s['compiled_flow_prompt']}")
        print("\n" + "=" * 70)
    except Exception as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
