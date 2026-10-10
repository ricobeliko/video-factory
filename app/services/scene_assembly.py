"""
app/services/scene_assembly.py
==============================
V16.4 — Scene-Based Video Generation: Scene Assembly.

Responsabilidade:
Transformar o ScenePlan e as seleções de materiais (SceneMaterialSelection)
em uma sequência estrita e ordenada de instruções de corte (SceneClipInstruction),
garantindo preservação da ordem narrativa, alocação coerente de duração
e fail-closed em caso de corrupção ou inconsistência estrutural.
"""

from __future__ import annotations

from typing import List, Optional

from loguru import logger

from app.models.schema import (
    SceneClipInstruction,
    SceneMaterialSelection,
    ScenePlan,
    VideoParams,
)


class SceneAssemblyError(ValueError):
    """Exceção levantada quando a montagem das cenas falha ou viola o contrato."""
    def __init__(self, message: str, reason_code: str = "SCENE_ASSEMBLY_FAILED"):
        super().__init__(message)
        self.reason_code = reason_code


def assemble_scene_clips(
    scene_plan: ScenePlan,
    material_selections: List[SceneMaterialSelection],
    audio_duration: float = 0.0,
    params: Optional[VideoParams] = None,
    task_id: Optional[str] = None,
) -> List[SceneClipInstruction]:
    """
    Constrói a lista sequencial de instruções de corte para cada cena.
    Garante que:
    1. A ordem das cenas é rigorosamente respeitada (1..N).
    2. Cada cena possui exatamente um material válido.
    3. As durações de cada cena somam a duração do áudio ou respeitam as estimativas.
    4. Entrada fora de ordem ou duplicada falha fechada ou normaliza deterministicamente.
    """
    tid_str = task_id or "unknown"
    logger.info(
        f"[SCENE_ASSEMBLY][START] task_id={tid_str} "
        f"scenes_count={len(scene_plan.scenes if scene_plan else [])} "
        f"materials_count={len(material_selections or [])}"
    )

    if not scene_plan or not scene_plan.scenes:
        logger.error(f"[SCENE_ASSEMBLY][BLOCK] task_id={tid_str} reason=SCENE_PLAN_EMPTY")
        raise SceneAssemblyError("SCENE_PLAN_EMPTY: no scenes in scene_plan", reason_code="SCENE_PLAN_EMPTY")

    if not material_selections:
        logger.error(f"[SCENE_ASSEMBLY][BLOCK] task_id={tid_str} reason=SCENE_MATERIAL_MISSING")
        raise SceneAssemblyError("SCENE_MATERIAL_MISSING: no material selections provided", reason_code="SCENE_MATERIAL_MISSING")

    # Mapeia seleções por scene_index, detectando duplicados
    selection_by_idx: dict[int, SceneMaterialSelection] = {}
    for mat in material_selections:
        if mat.scene_index in selection_by_idx:
            logger.error(
                f"[SCENE_ASSEMBLY][BLOCK] task_id={tid_str} "
                f"reason=SCENE_INDEX_INVALID duplicate_scene_index={mat.scene_index}"
            )
            raise SceneAssemblyError(
                f"SCENE_INDEX_INVALID: duplicate material selection for scene {mat.scene_index}",
                reason_code="SCENE_INDEX_INVALID",
            )
        selection_by_idx[mat.scene_index] = mat

    # Verifica se todas as cenas do plano possuem material
    for scene in scene_plan.scenes:
        if scene.scene_index not in selection_by_idx:
            logger.error(
                f"[SCENE_ASSEMBLY][BLOCK] task_id={tid_str} "
                f"reason=SCENE_MATERIAL_MISSING missing_scene_index={scene.scene_index}"
            )
            raise SceneAssemblyError(
                f"SCENE_MATERIAL_MISSING: missing material for scene {scene.scene_index}",
                reason_code="SCENE_MATERIAL_MISSING",
            )

    fit_mode = "cover"
    if params and hasattr(params, "video_fit_mode"):
        fit_mode = getattr(params.video_fit_mode, "value", str(params.video_fit_mode))

    # Cálculo das durações por cena
    durations: List[float] = []
    if audio_duration > 0.0:
        # Se temos hints de duração, usamos como peso proporcional
        hints = [max(1.0, float(s.duration_hint or 1.0)) for s in scene_plan.scenes]
        sum_hints = sum(hints)
        for h in hints:
            dur = round((h / sum_hints) * audio_duration, 3)
            durations.append(max(0.5, dur))

        # Ajuste residual no último clip para precisão exata com áudio
        diff = round(audio_duration - sum(durations), 3)
        if durations and abs(diff) > 0.01:
            durations[-1] = max(0.5, round(durations[-1] + diff, 3))
    else:
        # Fallback para duração padrão estimada
        for s in scene_plan.scenes:
            durations.append(max(1.0, float(s.duration_hint or 5.0)))

    instructions: List[SceneClipInstruction] = []
    # Itera em ordem determinística 1..N
    sorted_scenes = sorted(scene_plan.scenes, key=lambda s: s.scene_index)

    for i, scene in enumerate(sorted_scenes):
        mat = selection_by_idx[scene.scene_index]

        if not mat.material_path or not isinstance(mat.material_path, str):
            logger.error(
                f"[SCENE_ASSEMBLY][BLOCK] task_id={tid_str} "
                f"reason=SCENE_ASSEMBLY_FAILED invalid_material_path={mat.material_path}"
            )
            raise SceneAssemblyError(
                f"SCENE_ASSEMBLY_FAILED: invalid material_path for scene {scene.scene_index}",
                reason_code="SCENE_ASSEMBLY_FAILED",
            )

        clip_dur = durations[i]
        if clip_dur <= 0.0:
            logger.error(
                f"[SCENE_ASSEMBLY][BLOCK] task_id={tid_str} "
                f"reason=SCENE_ASSEMBLY_FAILED invalid_duration={clip_dur}"
            )
            raise SceneAssemblyError(
                f"SCENE_ASSEMBLY_FAILED: invalid duration {clip_dur} for scene {scene.scene_index}",
                reason_code="SCENE_ASSEMBLY_FAILED",
            )

        instruction = SceneClipInstruction(
            scene_index=scene.scene_index,
            material_path=mat.material_path,
            duration_seconds=clip_dur,
            fit_mode=fit_mode,
            start_offset=0.0,
        )
        instructions.append(instruction)

    logger.info(
        f"[SCENE_ASSEMBLY][PASS] task_id={tid_str} "
        f"instructions_count={len(instructions)} total_duration={sum(i.duration_seconds for i in instructions):.2f}s"
    )
    return instructions


def get_ordered_video_paths(instructions: List[SceneClipInstruction]) -> List[str]:
    """Retorna os caminhos de materiais na ordem exata e sequencial das cenas."""
    # Garante ordenação por scene_index
    sorted_insts = sorted(instructions, key=lambda inst: inst.scene_index)
    return [inst.material_path for inst in sorted_insts]
