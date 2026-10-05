"""
app/services/scene_material.py
==============================
V16.4 — Scene-Based Video Generation: Scene Material Resolver.

Responsabilidade:
Resolver materiais de vídeo especificamente para cada cena de um ScenePlan,
seguindo a ordem narrativa, aplicando fallback ordenado e observável,
evitando repetições consecutivas desnecessárias e preservando proveniência.
"""

from __future__ import annotations

import os
from typing import Any, List, Optional, Set, Tuple

from loguru import logger

from app.config import config
from app.models.schema import (
    MaterialInfo,
    SceneMaterialSelection,
    ScenePlan,
    VideoAspect,
    VideoParams,
)
from app.services import material, task_artifacts
from app.utils import utils


class SceneMaterialError(RuntimeError):
    """Exceção levantada quando a resolução de materiais de uma cena falha criticamente."""
    def __init__(self, message: str, reason_code: str = "SCENE_MATERIAL_MISSING"):
        super().__init__(message)
        self.reason_code = reason_code


BANNED_GENERIC_TERMS = {
    "cinematic visual",
    "cinematic stock",
    "generic footage",
    "generic stock",
    "generic video",
    "stock video",
    "stock footage",
    "background video",
    "fundo de video",
    "fundo de tela",
    "video escuro",
    "fundo escuro",
}


def _get_provider_search_func(source: str):
    """Retorna o par (provider_name, search_func) adequado para o provider configurado."""
    provider = "pexels"
    remote_func = material.search_videos_pexels
    if source == "pixabay":
        provider = "pixabay"
        remote_func = material.search_videos_pixabay
    elif source == "coverr":
        provider = "coverr"
        remote_func = material.search_videos_coverr
    return provider, remote_func


def _search_candidates(
    search_term: str,
    source: str,
    video_aspect: VideoAspect,
    min_duration: int = 3,
) -> List[MaterialInfo]:
    """Busca candidatos usando o cache unificado de material.py."""
    provider, remote_func = _get_provider_search_func(source)
    try:
        return material._search_videos_with_cache(
            provider=provider,
            search_videos=remote_func,
            search_term=search_term,
            minimum_duration=min_duration,
            video_aspect=video_aspect,
        )
    except Exception as exc:
        logger.warning(
            f"error searching material for term '{search_term}' via {source}: {exc}"
        )
        return []


def resolve_scene_materials(
    task_id: str,
    scene_plan: ScenePlan,
    params: VideoParams,
    audio_duration: float = 0.0,
    strict: bool = True,
) -> List[SceneMaterialSelection]:
    """
    Resolve e vincula materiais de vídeo para cada cena do plano ordenado.
    Em modo autônomo estrito (strict=True), se uma cena não conseguir material
    minimamente utilizável após esgotar todos os fallbacks, falha fechado (BLOCK).
    """
    tid_str = task_id or "unknown"
    if not scene_plan or not scene_plan.scenes:
        logger.error(f"[SCENE_MATERIAL][BLOCK] task_id={tid_str} reason=SCENE_PLAN_EMPTY")
        raise SceneMaterialError("SCENE_PLAN_EMPTY: no scenes in plan", reason_code="SCENE_PLAN_EMPTY")

    material_directory = config.app.get("material_directory", "").strip()
    if material_directory == "task":
        material_directory = utils.task_dir(task_id)
    elif material_directory and not os.path.isdir(material_directory):
        material_directory = ""

    source = getattr(params, "video_source", "pexels") or "pexels"
    video_aspect = getattr(params, "video_aspect", VideoAspect.portrait)
    if isinstance(video_aspect, str):
        try:
            video_aspect = VideoAspect(video_aspect)
        except ValueError:
            video_aspect = VideoAspect.portrait

    min_clip_dur = int(getattr(params, "video_clip_duration", 3) or 3)

    selections: List[SceneMaterialSelection] = []
    material_sources_records: List[dict[str, Any]] = []
    used_asset_ids: Set[str] = set()
    last_selected_asset_id: Optional[str] = None

    from app.services import visual_matching

    for scene in scene_plan.scenes:
        scene_idx = scene.scene_index
        logger.info(f"[SCENE_MATERIAL][START] task_id={tid_str} scene_index={scene_idx}")

        terms_to_try: List[str] = []

        # 1. search_terms da própria cena
        has_explicit_terms = bool(scene.search_terms)
        valid_explicit_terms = [
            t.strip() for t in (scene.search_terms or [])
            if t.strip() and t.strip().lower() not in BANNED_GENERIC_TERMS
        ]
        if strict and has_explicit_terms and not valid_explicit_terms:
            raise SceneMaterialError(
                f"SCENE_TERMS_EMPTY_OR_BANNED: scene {scene_idx} has only banned search terms",
                reason_code="SCENE_TERMS_EMPTY_OR_BANNED",
            )

        for term in (scene.search_terms or []):
            t_clean = term.strip()
            if t_clean and t_clean not in terms_to_try:
                if t_clean.lower() in BANNED_GENERIC_TERMS:
                    continue
                terms_to_try.append(t_clean)

        # 2. Intenção visual estruturada V16.5
        if getattr(scene, "visual_intent_v2", None) and isinstance(scene.visual_intent_v2, dict):
            intent = visual_matching.SceneVisualIntent.from_dict(scene.visual_intent_v2)
        else:
            intent = visual_matching.extract_scene_visual_intent(
                narration=scene.narration or "",
                video_subject=params.video_subject,
                scene_index=scene_idx,
                total_scenes=len(scene_plan.scenes),
            )

        for q in intent.search_queries:
            q_clean = q.strip()
            if q_clean and q_clean not in terms_to_try:
                if strict and q_clean.lower() in BANNED_GENERIC_TERMS:
                    continue
                terms_to_try.append(q_clean)

        # 3. Termos derivados da narration da própria cena
        if scene.narration:
            from app.services.scene_planner import _extract_scene_search_terms
            derived = _extract_scene_search_terms(
                narration=scene.narration,
                video_subject=params.video_subject,
                max_terms=3,
            )
            for dt in derived:
                dt_clean = dt.strip()
                if dt_clean and dt_clean not in terms_to_try:
                    if dt_clean.lower() in BANNED_GENERIC_TERMS:
                        continue
                    terms_to_try.append(dt_clean)

        # 4. visual_intent textual contextualizado com a cena
        if getattr(scene, "visual_intent", None):
            vi = str(scene.visual_intent).strip()
            if vi and vi not in terms_to_try:
                if not (strict and vi.lower() in BANNED_GENERIC_TERMS):
                    terms_to_try.append(vi)

        # 5. video_subject contextualizado com a cena, se aplicável
        if params.video_subject:
            vs = str(params.video_subject).strip()
            if vs and vs not in terms_to_try:
                if not (strict and vs.lower() in BANNED_GENERIC_TERMS):
                    terms_to_try.append(vs)

        if strict and not terms_to_try:
            raise SceneMaterialError(
                f"SCENE_TERMS_EMPTY_OR_BANNED: scene {scene_idx} has no valid non-banned search terms",
                reason_code="SCENE_TERMS_EMPTY_OR_BANNED",
            )

        # Fallback genérico amplo permitido SOMENTE se strict=False
        if not strict:
            if "cinematic visual" not in terms_to_try:
                terms_to_try.append("cinematic visual")

        queries_tried: List[str] = []
        evaluated_candidates: List[Tuple[MaterialInfo, float, dict, str, int]] = []
        resolved_item: Optional[MaterialInfo] = None
        resolved_score: float = 0.0
        resolved_reason: str = ""
        term_used: str = ""
        chosen_tier: int = 0
        fallback_used: bool = False

        for term_i, term in enumerate(terms_to_try):
            if strict and term.lower() in BANNED_GENERIC_TERMS:
                continue

            queries_tried.append(term)
            candidates = _search_candidates(
                search_term=term,
                source=source,
                video_aspect=video_aspect,
                min_duration=min_clip_dur,
            )

            if not candidates:
                continue

            # Avalia e pontua candidatos com o score determinístico v2
            scored_current: List[Tuple[MaterialInfo, float, dict]] = []
            for c in candidates:
                sc, bd = visual_matching.score_candidate_material(
                    candidate=c,
                    visual_intent=intent,
                    target_aspect=video_aspect,
                    used_asset_ids=used_asset_ids,
                    last_selected_asset_id=last_selected_asset_id,
                    scene_duration_hint=scene.duration_hint,
                    search_query_used=term,
                )
                evaluated_candidates.append((c, sc, bd, term, term_i))
                scored_current.append((c, sc, bd))

            scored_current.sort(key=lambda x: x[1], reverse=True)
            best_cand, best_sc, best_bd = scored_current[0]

            # Critério de parada:
            # 1. Se for o primeiro termo e tem score razoável (>= 25.0) sem penalidade imediata
            # 2. Ou se for termo subsequente com alta aderência (score >= 45.0) sem penalidade imediata
            repetition_pen = best_bd.get("repetition_penalty", 0.0)
            if best_sc >= 15.0 and repetition_pen == 0.0:
                resolved_item = best_cand
                resolved_score = best_sc
                term_used = term
                chosen_tier = term_i
                fallback_used = (term_i > 0)
                matched_str = ",".join(best_bd.get("matched_terms", [])[:3])
                resolved_reason = f"score={best_sc:.1f} terms=[{matched_str}] tier={term_i}"
                if fallback_used:
                    logger.info(
                        f"[SCENE_MATERIAL][FALLBACK] task_id={tid_str} "
                        f"scene_index={scene_idx} term_used='{term}' fallback_index={term_i}"
                    )
                break

        # Se nenhum candidato atingiu o critério de parada rápida mas temos candidatos avaliados:
        if not resolved_item and evaluated_candidates:
            # Ordena decrescente por score global
            evaluated_candidates.sort(key=lambda x: x[1], reverse=True)
            best_cand, best_sc, best_bd, cand_term, cand_tier = evaluated_candidates[0]
            resolved_item = best_cand
            resolved_score = best_sc
            term_used = cand_term
            chosen_tier = cand_tier
            fallback_used = (cand_tier > 0 or best_bd.get("repetition_penalty", 0.0) < 0.0)
            matched_str = ",".join(best_bd.get("matched_terms", [])[:3])
            resolved_reason = f"relaxed_score={best_sc:.1f} terms=[{matched_str}] tier={cand_tier}"
            if fallback_used:
                logger.info(
                    f"[SCENE_MATERIAL][FALLBACK] task_id={tid_str} "
                    f"scene_index={scene_idx} term_used='{cand_term}' fallback_index={cand_tier}"
                )

        if not resolved_item:
            logger.error(
                f"[SCENE_MATERIAL][BLOCK] task_id={tid_str} scene_index={scene_idx} "
                f"reason=SCENE_MATERIAL_MISSING terms={terms_to_try}"
            )
            if strict:
                raise SceneMaterialError(
                    f"SCENE_MATERIAL_MISSING: failed to resolve material for scene {scene_idx}",
                    reason_code="SCENE_MATERIAL_MISSING",
                )
            else:
                continue

        # Baixa / salva o arquivo de vídeo
        saved_path = material.save_video(
            video_url=resolved_item.url,
            save_dir=material_directory,
        )

        if not saved_path or not os.path.exists(saved_path):
            logger.error(
                f"[SCENE_MATERIAL][BLOCK] task_id={tid_str} scene_index={scene_idx} "
                f"reason=SCENE_MATERIAL_DOWNLOAD_FAILED url={resolved_item.url}"
            )
            if strict:
                raise SceneMaterialError(
                    f"SCENE_MATERIAL_DOWNLOAD_FAILED: failed to download material for scene {scene_idx}",
                    reason_code="SCENE_MATERIAL_DOWNLOAD_FAILED",
                )
            continue

        source_info = (
            resolved_item.source_info
            if isinstance(resolved_item.source_info, dict)
            else {}
        )
        asset_id = str(source_info.get("asset_id") or source_info.get("id") or "")
        source_url = str(source_info.get("source_page") or resolved_item.url or "")
        prov_record = material._material_source_record(resolved_item, saved_path)
        material_sources_records.append(prov_record)

        selection = SceneMaterialSelection(
            scene_index=scene_idx,
            material_path=saved_path,
            provider=resolved_item.provider or source,
            asset_id=asset_id or None,
            source_url=source_url or None,
            search_term_used=term_used,
            fallback_used=fallback_used,
            duration=float(resolved_item.duration or 0.0),
            provenance=prov_record,
            visual_intent=intent.to_dict(),
            match_score=resolved_score,
            selection_reason=resolved_reason,
            queries_tried=queries_tried,
            fallback_tier=chosen_tier,
        )
        selections.append(selection)

        last_selected_asset_id = asset_id or resolved_item.url
        used_asset_ids.add(last_selected_asset_id)

        logger.info(
            f"[SCENE_MATERIAL][SELECTED] task_id={tid_str} scene_index={scene_idx} "
            f"asset_id={asset_id or 'unknown'} search_term='{term_used}' "
            f"score={resolved_score:.1f} fallback={fallback_used} path={saved_path}"
        )

    # Persiste materiais de cena e fontes de proveniência no script_data
    _persist_scene_resolution(task_id, selections, material_sources_records)

    return selections


def _persist_scene_resolution(
    task_id: str,
    selections: List[SceneMaterialSelection],
    material_sources: List[dict[str, Any]],
) -> None:
    """Persiste dados de materiais de cenas e proveniência de forma segura."""
    try:
        serialized_materials = [
            {
                "scene_index": s.scene_index,
                "provider": s.provider,
                "asset_id": s.asset_id,
                "material_path": s.material_path,
                "search_term_used": s.search_term_used,
                "fallback_used": s.fallback_used,
                "duration": s.duration,
                "match_score": s.match_score,
                "selection_reason": s.selection_reason,
                "queries_tried": s.queries_tried,
                "fallback_tier": s.fallback_tier,
                "visual_intent": s.visual_intent,
            }
            for s in selections
        ]
        task_artifacts.patch_script_data(
            task_id,
            scene_materials=serialized_materials,
            material_sources=material_sources,
        )
    except Exception as exc:
        logger.warning(
            f"failed to persist scene material resolution in script_data: {exc}"
        )
