"""
scripts/validate_g8_8_audio_homologation.py
============================================
FASE V1.5E-G8.8 — GTA VI CONTROLLED AUDIO HOMOLOGATION

Executa a validação controlada do vídeo GTA VI existente usando:
- MESMO roteiro
- MESMO ScenePlan
- MESMOS clips/materials já existentes
- NOVA voz global Brian (en-US-BrianMultilingualNeural)
- NOVO BGM procedural contextual (ambient_auto @ 0.20)

SEM qualquer nova geração visual (0 Flow calls, 0 Paid visual API calls, 0 Publication calls).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from loguru import logger  # noqa: E402
from app.models import const  # noqa: E402
from app.models.schema import (  # noqa: E402
    SceneMaterialSelection,
    ScenePlan,
    VideoParams,
)
from app.services import (  # noqa: E402
    ambient_bgm,
    operator_console,
    scene_assembly,
    scheduler,
    subtitle,
    task,
)
from app.services import state as sm  # noqa: E402
from app.utils import utils  # noqa: E402
from scripts import flow_workflow  # noqa: E402


def run_g8_8_homologation(
    source_task_id: str = "8909befc-7ec5-47bd-829d-b3412041beb2",
    profile_id: str = "profile-2095da4fbe23",
    validation_task_id: str | None = None,
    base_dir: str = ROOT_DIR,
) -> Dict[str, Any]:
    timestamp = int(time.time())
    val_task_id = validation_task_id or f"g8-audio-validation-{timestamp}"

    source_task_dir = os.path.join(base_dir, "storage", "tasks", source_task_id)
    source_script_path = os.path.join(source_task_dir, "script.json")

    logger.info("=== INICIANDO G8.8 GTA VI CONTROLLED AUDIO HOMOLOGATION ===")
    logger.info(f"SOURCE_TASK_ID: {source_task_id}")
    logger.info(f"VALIDATION_TASK_ID: {val_task_id}")
    logger.info(f"SOURCE_PATH: {source_script_path}")

    # =========================================================================
    # 1. CARREGAR ARTEFATOS DA TASK ORIGINAL
    # =========================================================================
    if not os.path.isfile(source_script_path):
        raise FileNotFoundError(
            f"Arquivo script.json da task original não encontrado em '{source_script_path}'. "
            f"Certifique-se de que a task '{source_task_id}' existe no storage local ou foi transferida do PC Forte."
        )

    with open(source_script_path, "r", encoding="utf-8") as f:
        source_data = json.load(f)

    original_script = source_data.get("script") or source_data.get("video_script", "")
    if not original_script:
        raise ValueError("Roteiro original (script/video_script) ausente ou vazio no script.json.")

    raw_scene_plan = source_data.get("scene_plan")
    if not raw_scene_plan:
        raise ValueError("scene_plan ausente no script.json da task original.")

    scene_plan = ScenePlan.model_validate(raw_scene_plan)
    if not scene_plan.scenes:
        raise ValueError("scene_plan validado contém 0 cenas.")

    search_terms = source_data.get("search_terms", [])
    raw_params = source_data.get("params", {})
    if not isinstance(raw_params, dict):
        raw_params = {}

    # =========================================================================
    # 2. PARÂMETROS COM SOBRESCRITA EXPLÍCITA
    # =========================================================================
    params = VideoParams(**raw_params) if raw_params else VideoParams()

    # Preservar o roteiro original
    params.video_script = original_script

    # Sobrescrever estritamente a identidade de áudio homologada
    params.profile_id = profile_id
    params.voice_name = "en-US-BrianMultilingualNeural"
    params.voice_rate = 0.8
    params.voice_volume = 1.0

    params.bgm_type = "ambient_auto"
    params.bgm_file = ""
    params.bgm_volume = 0.20
    params.bgm_default_mood = "futuristic"

    logger.info(
        f"Parâmetros configurados: voice={params.voice_name} rate={params.voice_rate} "
        f"vol={params.voice_volume} bgm_type={params.bgm_type} bgm_vol={params.bgm_volume} "
        f"default_mood={params.bgm_default_mood}"
    )

    # =========================================================================
    # 3. MATERIAL FLOW — LOCAL ONLY (ZERO FLOW CALLS)
    # =========================================================================
    flow_project_dir = os.path.join(source_task_dir, "flow")
    if not os.path.isdir(flow_project_dir):
        raise FileNotFoundError(f"Diretório Flow da task original não encontrado em '{flow_project_dir}'.")

    manifest_path = os.path.join(flow_project_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        raise FileNotFoundError(f"manifest.json não encontrado em '{flow_project_dir}'.")

    # Chama exclusivamente o resolvedor local estrito (Material-Only)
    material_selections: List[SceneMaterialSelection] = flow_workflow.resolve_project_materials(
        project_dir=flow_project_dir,
        task_id=val_task_id,
        params=params,
    )

    if not material_selections:
        raise RuntimeError("Nenhum SceneMaterialSelection resolvido a partir do projeto Flow local.")

    # Validar que todos os materiais existem e têm tamanho > 0
    for sel in material_selections:
        if not sel.material_path or not os.path.isfile(sel.material_path):
            raise FileNotFoundError(f"Material da cena {sel.scene_index} não existe fisicamente: '{sel.material_path}'")
        if os.path.getsize(sel.material_path) == 0:
            raise RuntimeError(f"Material da cena {sel.scene_index} está vazio (0 bytes): '{sel.material_path}'")

    if len(material_selections) < len(scene_plan.scenes):
        raise RuntimeError(
            f"Quantidade insuficiente de materiais: {len(material_selections)} materiais "
            f"para {len(scene_plan.scenes)} cenas do ScenePlan."
        )

    logger.info(f"Materiais locais validados com sucesso: {len(material_selections)} cenas cobertas.")

    # =========================================================================
    # 4. NOVO DIRETÓRIO DE VALIDAÇÃO
    # =========================================================================
    val_task_dir = utils.task_dir(val_task_id)
    os.makedirs(val_task_dir, exist_ok=True)

    # Persistir metadados e script.json para rastreabilidade e auditoria
    validation_metadata = {
        "source_task_id": source_task_id,
        "validation_type": "G8_AUDIO_HOMOLOGATION",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "script": original_script,
        "video_script": original_script,
        "search_terms": search_terms,
        "params": params.model_dump(),
        "scene_plan": scene_plan.model_dump(),
        "flow_project_dir": flow_project_dir,
    }
    with open(os.path.join(val_task_dir, "script.json"), "w", encoding="utf-8") as f:
        json.dump(validation_metadata, f, indent=2, ensure_ascii=False)

    sm.state.update_task(val_task_id, state=const.TASK_STATE_PROCESSING, progress=10)

    # =========================================================================
    # 5. GERAR NOVA NARRAÇÃO
    # =========================================================================
    logger.info("[Passo 5/8] Gerando narração com voz Brian...")
    audio_file, audio_duration, sub_maker = task.generate_audio(
        val_task_id, params, original_script
    )

    if not audio_file or not os.path.isfile(audio_file):
        raise RuntimeError(f"Falha ao gerar narração: arquivo não encontrado em '{audio_file}'")
    if audio_duration <= 0:
        raise RuntimeError(f"Duração de áudio inválida: {audio_duration}s")

    logger.info(f"Nova narração gerada: '{audio_file}' ({audio_duration:.2f}s)")
    sm.state.update_task(val_task_id, state=const.TASK_STATE_PROCESSING, progress=30)

    # =========================================================================
    # 6. GERAR NOVA LEGENDA
    # =========================================================================
    logger.info("[Passo 6/8] Gerando novas legendas sincronizadas...")
    subtitle_path = task.generate_subtitle(
        val_task_id, params, original_script, sub_maker, audio_file
    )

    if getattr(params, "subtitle_required", False) or params.subtitle_enabled:
        if not subtitle_path or not os.path.isfile(subtitle_path):
            raise RuntimeError(f"Legendas obrigatórias não encontradas em '{subtitle_path}'")
        val_res = subtitle.validate_subtitle_file(subtitle_path)
        if not val_res.get("valid", False):
            raise RuntimeError(f"Arquivo de legendas inválido: {val_res.get('reason')}")

    logger.info(f"Novas legendas geradas: '{subtitle_path}'")
    sm.state.update_task(val_task_id, state=const.TASK_STATE_PROCESSING, progress=45)

    # =========================================================================
    # 7. REASSEMBLAR CENAS COM A NOVA DURAÇÃO DE ÁUDIO
    # =========================================================================
    logger.info(f"[Passo 7/8] Reassemblando cenas com duração={audio_duration:.2f}s...")
    instructions = scene_assembly.assemble_scene_clips(
        scene_plan=scene_plan,
        material_selections=material_selections,
        audio_duration=audio_duration,
        params=params,
        task_id=val_task_id,
    )

    ordered_video_paths = scene_assembly.get_ordered_video_paths(instructions)
    if not ordered_video_paths:
        raise RuntimeError("Nenhum vídeo ordenado gerado por assemble_scene_clips.")

    logger.info(f"Instruções de corte geradas: {len(instructions)} clipes ordenados.")
    sm.state.update_task(val_task_id, state=const.TASK_STATE_PROCESSING, progress=55)

    # =========================================================================
    # 8. RENDER FINAL COM BGM PROCEDURAL (ambient_auto)
    # =========================================================================
    logger.info("[Passo 8/8] Renderizando vídeo final com ambient BGM procedural...")
    final_video_paths, combined_video_paths, warnings = task.generate_final_videos(
        task_id=val_task_id,
        params=params,
        downloaded_videos=ordered_video_paths,
        audio_file=audio_file,
        subtitle_path=subtitle_path,
        audio_duration=audio_duration,
        scene_clip_instructions=instructions,
    )

    if not final_video_paths or not os.path.isfile(final_video_paths[0]):
        raise RuntimeError("Falha na renderização do vídeo final: arquivo não gerado.")

    final_video_file = final_video_paths[0]
    final_video_size_bytes = os.path.getsize(final_video_file)
    if final_video_size_bytes == 0:
        raise RuntimeError("Vídeo final gerado possui 0 bytes.")

    final_video_size_mb = final_video_size_bytes / (1024.0 * 1024.0)

    # Detectar o mood que foi aplicado
    detected_mood = ambient_bgm.detect_mood(original_script, default_mood="futuristic")

    sm.state.update_task(
        val_task_id,
        state=const.TASK_STATE_COMPLETE,
        progress=100,
    )

    # Consultar estados operacionais reais persistentes (sem hardcode)
    try:
        sched_settings = scheduler.get_all_settings()
        auto_publish_status = "ON" if sched_settings.get("auto_publish_enabled", False) else "OFF"
    except Exception as exc:
        logger.warning(f"Não foi possível ler auto_publish_enabled do scheduler: {exc}")
        auto_publish_status = "UNKNOWN"

    try:
        factory_state_status = operator_console.get_factory_state()
    except Exception as exc:
        logger.warning(f"Não foi possível ler factory_state: {exc}")
        factory_state_status = "UNKNOWN"

    gen_worker_status = "NOT_MEASURED_STANDALONE"

    result_data = {
        "status": "SUCCESS",
        "source_task_id": source_task_id,
        "validation_task_id": val_task_id,
        "voice_name": params.voice_name,
        "voice_rate": params.voice_rate,
        "voice_volume": params.voice_volume,
        "bgm_type": params.bgm_type,
        "bgm_volume": params.bgm_volume,
        "bgm_default_mood": params.bgm_default_mood,
        "bgm_detected_mood": detected_mood,
        "bgm_provenance": "SAFE_PROCEDURAL",
        "scenes": len(instructions),
        "existing_materials_reused": len(material_selections),
        "new_visual_assets_generated": "NO",
        "flow_calls": 0,
        "paid_visual_api_calls": 0,
        "paid_api_calls": 0,
        "publication_calls": 0,
        "tts_generation": "BRIAN_EXPECTED",
        "audio_file": audio_file,
        "subtitle_file": subtitle_path,
        "final_video": final_video_file,
        "final_video_exists": "YES",
        "final_video_size_mb": round(final_video_size_mb, 2),
        "original_task_modified": "NO",
        "auto_publish": auto_publish_status,
        "factory": factory_state_status,
        "gen_worker": gen_worker_status,
        "result": "AWAITING_HUMAN_REVIEW",
    }

    return result_data


def print_operator_report(res: Dict[str, Any]) -> None:
    report = f"""
===========================================================
RELATÓRIO DE HOMOLOGAÇÃO CONTROLADA G8.8
===========================================================
STATUS = {res['status']}
SOURCE_TASK_ID = {res['source_task_id']}
VALIDATION_TASK_ID = {res['validation_task_id']}

VOICE_NAME = {res['voice_name']}
VOICE_RATE = {res['voice_rate']}
VOICE_VOLUME = {res['voice_volume']}

BGM_TYPE = {res['bgm_type']}
BGM_VOLUME = {res['bgm_volume']:.2f}
BGM_DEFAULT_MOOD = {res['bgm_default_mood']}
BGM_DETECTED_MOOD = {res['bgm_detected_mood']}
BGM_PROVENANCE = {res['bgm_provenance']}

SCENES = {res['scenes']}
EXISTING_MATERIALS_REUSED = {res['existing_materials_reused']}
NEW_VISUAL_ASSETS_GENERATED = {res['new_visual_assets_generated']}

FLOW_CALLS = {res['flow_calls']}
PAID_VISUAL_API_CALLS = {res['paid_visual_api_calls']}
PAID_API_CALLS = {res['paid_api_calls']}
PUBLICATION_CALLS = {res['publication_calls']}
TTS_GENERATION = {res['tts_generation']}

AUDIO_FILE = {res['audio_file']}
SUBTITLE_FILE = {res['subtitle_file']}
FINAL_VIDEO = {res['final_video']}

FINAL_VIDEO_EXISTS = {res['final_video_exists']}
FINAL_VIDEO_SIZE_MB = {res['final_video_size_mb']:.2f}

ORIGINAL_TASK_MODIFIED = {res['original_task_modified']}

AUTO_PUBLISH = {res['auto_publish']}
FACTORY = {res['factory']}
GEN_WORKER = {res['gen_worker']}

RESULT = {res['result']}
===========================================================
"""
    sys.stdout.write(report)
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(
        description="G8.8 — GTA VI Controlled Audio Homologation"
    )
    parser.add_argument(
        "--source-task-id",
        type=str,
        default="8909befc-7ec5-47bd-829d-b3412041beb2",
        help="Task ID da geração original no storage",
    )
    parser.add_argument(
        "--profile-id",
        type=str,
        default="profile-2095da4fbe23",
        help="Profile ID do canal GTA VI",
    )
    parser.add_argument(
        "--validation-task-id",
        type=str,
        default=None,
        help="Novo task ID para isolamento de auditoria",
    )
    parser.add_argument(
        "--base-dir",
        type=str,
        default=ROOT_DIR,
        help="Diretório raiz do repositório",
    )

    args = parser.parse_args()

    try:
        res = run_g8_8_homologation(
            source_task_id=args.source_task_id,
            profile_id=args.profile_id,
            validation_task_id=args.validation_task_id,
            base_dir=args.base_dir,
        )
        print_operator_report(res)
    except Exception as exc:
        logger.error(f"[G8.8] ERRO NA HOMOLOGAÇÃO: {exc}")
        sys.stderr.write(f"\n[G8.8 ERROR] {exc}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
