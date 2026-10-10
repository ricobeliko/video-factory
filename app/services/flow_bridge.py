"""
app/services/flow_bridge.py
===========================
Fase V1.5E-E — Bridge desacoplado entre a Video Factory e o Google Flow.

Responsabilidade EXCLUSIVA:
1. Localizar o diretório persistente e determinístico da tarefa (storage/tasks/<task_id>/flow/).
2. Preparar (ou carregar em resume) o manifest.json da tarefa utilizando o ScenePlan canônico.
3. Executar as cenas Flow pendentes sequencialmente sob FLOW_CONCURRENCY_LOCK.
4. Resolver materiais (Flow + Stock fallback) sem efeitos colaterais de render.
5. Retornar SceneMaterialSelection[] e metadados operacionais para gravação em script.json.

Garantias:
- ZERO renderização de vídeo final.
- ZERO síntese de áudio (TTS).
- ZERO geração de legendas.
- Import tardio (lazy import) de scripts.flow_workflow para evitar ciclo com task.py.
- Fail-closed em manifesto corrompido ou estado FLOW_GENERATION_NEEDS_RECOVERY.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from app.models.schema import SceneMaterialSelection, ScenePlan, VideoParams
from app.utils import utils

# Trava a nível de processo para assegurar que apenas uma sessão do navegador Flow
# execute por vez, prevenindo concorrência cruzada entre múltiplos canais.
FLOW_CONCURRENCY_LOCK = threading.Lock()


def get_task_flow_dir(task_id: str) -> str:
    """Retorna o caminho canônico e persistente do diretório Flow para a tarefa."""
    base_task_dir = utils.task_dir(task_id)
    return os.path.join(base_task_dir, "flow")


def resolve_flow_materials_for_task(
    task_id: str,
    params: VideoParams,
    video_script: str,
    scene_plan: ScenePlan,
) -> Tuple[List[SceneMaterialSelection], Dict[str, Any]]:
    """
    Coordena a resolução de materiais Flow para a tarefa.

    Reutiliza ou cria o manifest.json, dispara a geração das cenas necessárias
    sob controle de concorrência e resolve os materiais com o ScenePlan canônico.
    """
    # Import tardio para prevenir ciclo de dependências com task.py
    from scripts import flow_workflow

    if not task_id or not str(task_id).strip():
        raise ValueError("task_id não pode ser vazio")
    if scene_plan is None or not getattr(scene_plan, "scenes", None):
        raise ValueError("FLOW_REQUIRES_SCENE_PLAN: ScenePlan canônico obrigatório para integração com Flow")

    task_base_dir = utils.task_dir(task_id)
    flow_dir = get_task_flow_dir(task_id)
    manifest_path = os.path.join(flow_dir, "manifest.json")

    failure_policy = "fallback_stock" if getattr(params, "stock_fallback_enabled", True) else "strict"

    # 1. Tratamento de Manifest: Inexistente vs Existente vs Corrompido
    if not os.path.exists(manifest_path):
        os.makedirs(flow_dir, exist_ok=True)
        logger.info(f"[FLOW_BRIDGE] Criando novo manifesto Flow para task '{task_id}' em {flow_dir}...")
        prep_res = flow_workflow.prepare_project(
            script_text=video_script,
            project_name="flow",
            video_subject=params.video_subject,
            voice_name=params.voice_name or "pt-BR-AntonioNeural-Male",
            base_dir=task_base_dir,
            niche=params.niche or "",
            target_flow_scenes=int(getattr(params, "flow_scene_count", 6)),
            visual_director_enabled=bool(getattr(params, "visual_director_enabled", False)),
            visual_style_brief=str(getattr(params, "visual_style_brief", "") or ""),
            scene_plan=scene_plan,
        )
        if not os.path.exists(manifest_path):
            raise FileNotFoundError(f"Falha ao criar manifest.json em {manifest_path}")
    else:
        # Resume de projeto existente: valida integridade do JSON
        logger.info(f"[FLOW_BRIDGE] Reutilizando manifesto existente em {manifest_path} (zero re-planejamento).")
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
        except Exception as json_err:
            logger.error(f"[FLOW_BRIDGE] Manifesto corrompido em {manifest_path}: {json_err}")
            raise ValueError(f"FLOW_MANIFEST_INVALID: Manifesto corrompido em {manifest_path}. Intervenção manual obrigatória.")
    # 2. Execução sequencial das cenas pendentes sob FLOW_CONCURRENCY_LOCK
    logger.info(f"[FLOW_BRIDGE] Adquirindo trava de concorrência Flow para task '{task_id}'...")
    acquired = FLOW_CONCURRENCY_LOCK.acquire(blocking=True, timeout=120.0)
    if not acquired:
        logger.warning(f"[FLOW_BRIDGE] Timeout ao aguardar FLOW_CONCURRENCY_LOCK para task '{task_id}'.")
        raise RuntimeError("FLOW_BROWSER_BUSY: Sessão do navegador Flow ocupada por outra tarefa.")

    try:
        gen_res = flow_workflow.generate_pending_flow_scenes(
            manifest_path=manifest_path,
            failure_policy=failure_policy,
        )
    finally:
        FLOW_CONCURRENCY_LOCK.release()
        logger.debug(f"[FLOW_BRIDGE] Trava de concorrência Flow liberada para task '{task_id}'.")

    if gen_res.get("status") == "FLOW_GENERATION_NEEDS_RECOVERY":
        raise RuntimeError(
            f"FLOW_GENERATION_NEEDS_RECOVERY: Falha ao gerar cenas Flow da task '{task_id}'. "
            "Requer recuperação manual."
        )
    if gen_res.get("status") == "FLOW_BROWSER_BUSY":
        raise RuntimeError("FLOW_BROWSER_BUSY: Sessão do navegador Flow ocupada.")

    # 3. Resolução de materiais (Material-Only Resolver)
    material_selections = flow_workflow.resolve_project_materials(
        project_dir=flow_dir,
        task_id=task_id,
        stock_source=getattr(params, "video_source", "coverr"),
        flow_failure_policy=failure_policy,
        params=params,
    )

    # 4. Compilação de metadados operacionais para persistência em script.json
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            final_manifest = json.load(f)
    except Exception:
        final_manifest = {}

    final_flow_gen = final_manifest.get("flow_generation", {})
    completed_scenes = final_flow_gen.get("completed_scenes", [])

    meta = {
        "flow_enabled": True,
        "flow_scene_count_requested": int(getattr(params, "flow_scene_count", 6)),
        "flow_scene_count_completed": len(completed_scenes),
        "flow_failure_policy": failure_policy,
        "flow_manifest_path": manifest_path,
        "flow_project_url": final_manifest.get("flow_project_url"),
        "flow_status": final_flow_gen.get("status", gen_res.get("status", "COMPLETE")),
        "flow_completed_scenes": completed_scenes,
        "visual_director_enabled": bool(getattr(params, "visual_director_enabled", False)),
        "stock_fallback_enabled": bool(getattr(params, "stock_fallback_enabled", True)),
    }

    return material_selections, meta
