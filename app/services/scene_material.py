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
from typing import Any, List, Optional, Set

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
    last_selected_path: Optional[str] = None

    for scene in scene_plan.scenes:
        scene_idx = scene.scene_index
        logger.info(f"[SCENE_MATERIAL][START] task_id={tid_str} scene_index={scene_idx}")

        terms_to_try = list(scene.search_terms or [])
        # Fallback genérico adicional se nenhum dos termos da cena resolver
        if params.video_subject and params.video_subject not in terms_to_try:
            terms_to_try.append(params.video_subject.strip())
        if "cinematic visual" not in terms_to_try:
            terms_to_try.append("cinematic visual")

        resolved_item: Optional[MaterialInfo] = None
        term_used: str = ""
        fallback_used: bool = False

        for term_i, term in enumerate(terms_to_try):
            candidates = _search_candidates(
                search_term=term,
                source=source,
                video_aspect=video_aspect,
                min_duration=min_clip_dur,
            )

            if not candidates:
                continue

            # Tenta evitar repetição consecutiva com a cena anterior se houver alternativas
            selected_candidate: Optional[MaterialInfo] = None
            if last_selected_asset_id or last_selected_path:
                non_duplicate_candidates = [
                    c for c in candidates
                    if str((c.source_info or {}).get("asset_id", "") or c.url) != last_selected_asset_id
                ]
                if non_duplicate_candidates:
                    selected_candidate = non_duplicate_candidates[0]
                else:
                    selected_candidate = candidates[0]
            else:
                selected_candidate = candidates[0]

            resolved_item = selected_candidate
            term_used = term
            fallback_used = (term_i > 0)
            if fallback_used:
                logger.info(
                    f"[SCENE_MATERIAL][FALLBACK] task_id={tid_str} "
                    f"scene_index={scene_idx} term_used='{term}' fallback_index={term_i}"
                )
            break

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
                # Se não estrito, continua
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
        )
        selections.append(selection)

        last_selected_asset_id = asset_id or resolved_item.url
        last_selected_path = saved_path
        used_asset_ids.add(last_selected_asset_id)

        logger.info(
            f"[SCENE_MATERIAL][SELECTED] task_id={tid_str} scene_index={scene_idx} "
            f"asset_id={asset_id or 'unknown'} search_term='{term_used}' "
            f"fallback={fallback_used} path={saved_path}"
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
