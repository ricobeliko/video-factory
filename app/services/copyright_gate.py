"""Módulo de Copyright Baseline Hardening e Asset Provenance (Fase V14-B).

Responsável por:
1. Garantir fail-closed para trilhas de fundo (BGM) em novas tarefas autônomas.
2. Rastrear e persistir a proveniência dos ativos (BGM e clips de vídeo).
3. Avaliar o Copyright Provenance Gate antes da aprovação autônoma.
4. Definir modelos conceituais para status de reivindicação (Content ID claim).

IMPORTANTE: Nenhum gate local garante ausência de reivindicações de Content ID no YouTube.
O objetivo é reduzir risco e garantir total auditabilidade dos ativos utilizados.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from app.utils import utils

# Eventos e Modos de Aprovação Manual Legada (V1.5E)
EVENT_TASK_COPYRIGHT_MANUAL_APPROVAL = "TASK_COPYRIGHT_MANUAL_APPROVAL"
APPROVAL_MODE_MANUAL_LEGACY = "MANUAL_LEGACY_FINAL_ARTIFACT"
SCOPE_LEGACY_FINAL_ARTIFACT = "legacy_final_artifact"
CONFIRM_LEGACY_COPYRIGHT = "APPROVE_LEGACY_COPYRIGHT"


def calculate_file_sha256(file_path: str) -> str:
    """Calcula o hash SHA-256 de um arquivo em disco em blocos de 64KB."""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            sha.update(chunk)
    return sha.hexdigest()


# Provedores visuais autorizados para o fluxo autônomo
ALLOWED_AUTONOMOUS_VISUAL_PROVIDERS = frozenset({"pexels", "pixabay", "coverr"})

# Conceitos para status de direitos autorais (V14-B.2 - Manual / Operador / Auditável)
COPYRIGHT_STATUS_UNKNOWN = "unknown"
COPYRIGHT_STATUS_CLEAN_MANUAL = "clean_manual"
COPYRIGHT_STATUS_CLAIMED = "claimed"
COPYRIGHT_STATUS_BLOCKED = "blocked"
COPYRIGHT_STATUS_STRIKE = "strike"

ALLOWED_COPYRIGHT_STATUSES = frozenset({
    COPYRIGHT_STATUS_UNKNOWN,
    COPYRIGHT_STATUS_CLEAN_MANUAL,
    COPYRIGHT_STATUS_CLAIMED,
    COPYRIGHT_STATUS_BLOCKED,
    COPYRIGHT_STATUS_STRIKE,
})

COPYRIGHT_SOURCE_OPERATOR = "operator"
COPYRIGHT_SOURCE_FUTURE_PROVIDER = "future_provider"

ALLOWED_COPYRIGHT_SOURCES = frozenset({
    COPYRIGHT_SOURCE_OPERATOR,
    COPYRIGHT_SOURCE_FUTURE_PROVIDER,
})


def _resolve_task_dir(task_id: str, task_base_dir: Optional[str] = None) -> str:
    """Resolve o diretório canônico da tarefa para inspeção de arquivos."""
    if task_base_dir:
        norm = os.path.normpath(task_base_dir)
        if os.path.basename(norm) == task_id or os.path.exists(os.path.join(task_base_dir, "script.json")):
            return os.path.abspath(task_base_dir)
        return os.path.abspath(os.path.join(task_base_dir, task_id))
    return os.path.abspath(utils.task_dir(task_id))


def validate_flow_clip_provenance(
    task_id: str,
    clip: Dict[str, Any],
    task_base_dir: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Validação estrita de evidência local para clips do Google Flow (V1.5E-G8).

    Exige comprovadamente:
    1. local_file presente e contido dentro do diretório canônico da task.
    2. local_file localizado no subdiretório flow/clips/.
    3. Arquivo físico existente, não-vazio e válido no disco.
    4. Manifesto flow/manifest.json existente e legível.
    5. Cena correspondente existente no manifesto.
    6. is_flow_premium == True na cena do manifesto.
    7. scene_index presente em completed_scenes do flow_generation.
    8. flow_generation.status == 'COMPLETE' e sem recovery pendente.
    """
    if not task_id or not str(task_id).strip():
        return False, "task_id inválido ou ausente"

    local_file = str(clip.get("local_file") or "").strip()
    if not local_file:
        return False, "local_file ausente na proveniência do clipe Flow"

    task_dir_path = _resolve_task_dir(task_id, task_base_dir)
    task_dir_abs = os.path.abspath(task_dir_path)
    if not os.path.isabs(local_file):
        local_file_abs = os.path.abspath(os.path.join(task_dir_abs, local_file))
    else:
        local_file_abs = os.path.abspath(local_file)

    # 1. Arquivo dentro do diretório da tarefa
    try:
        rel_task = os.path.relpath(local_file_abs, task_dir_abs)
        if rel_task.startswith("..") or os.path.isabs(rel_task):
            return False, f"Arquivo Flow fora do diretório da tarefa: {local_file}"
    except ValueError:
        return False, f"Arquivo Flow em unidade distinta da tarefa: {local_file}"

    # 2. Localizado em flow/clips/
    flow_clips_dir = os.path.abspath(os.path.join(task_dir_abs, "flow", "clips"))
    try:
        rel_clips = os.path.relpath(local_file_abs, flow_clips_dir)
        if rel_clips.startswith("..") or os.path.isabs(rel_clips):
            return False, f"Arquivo Flow fora de flow/clips/: {local_file}"
    except ValueError:
        return False, f"Arquivo Flow fora de flow/clips/: {local_file}"

    # 3. Arquivo existente e não-vazio no disco
    if not os.path.isfile(local_file_abs):
        return False, f"Arquivo Flow inexistente no disco: {local_file}"
    try:
        if os.path.getsize(local_file_abs) == 0:
            return False, f"Arquivo Flow vazio (zero bytes): {local_file}"
    except OSError as e:
        return False, f"Falha ao verificar tamanho do arquivo Flow: {e}"

    # Validação do arquivo de clipe (fail-closed: qualquer exceção reprova)
    try:
        from scripts.flow_workflow import validate_clip_file
        clip_val = validate_clip_file(local_file_abs)
    except Exception as exc:
        logger.warning(f"[COPYRIGHT_GATE] Falha ao executar validate_clip_file em {local_file_abs}: {exc}")
        return False, f"Falha ao validar arquivo Flow (fail-closed): {exc}"
    if not isinstance(clip_val, dict) or not clip_val.get("valid", False):
        return False, f"Arquivo Flow inválido ou corrompido: {local_file}"

    # 4. Manifesto flow/manifest.json existente e legível
    manifest_path = os.path.join(task_dir_abs, "flow", "manifest.json")
    if not os.path.isfile(manifest_path):
        return False, f"Manifesto Flow inexistente: {manifest_path}"

    try:
        with open(manifest_path, "r", encoding="utf-8") as mf:
            manifest = json.load(mf)
    except Exception as exc:
        return False, f"Manifesto Flow corrompido ou ilegível: {exc}"

    if not isinstance(manifest, dict):
        return False, "Manifesto Flow inválido (não é um objeto JSON)"

    # 5. Cena correspondente no manifesto (match EXATO por expected_clip; sem fallback)
    clip_filename = os.path.basename(local_file_abs)
    manifest_scenes = manifest.get("scenes", []) or []
    matching_scene = None
    for sc in manifest_scenes:
        if isinstance(sc, dict) and sc.get("expected_clip") == clip_filename:
            matching_scene = sc
            break

    if not matching_scene:
        return False, f"Clipe Flow '{clip_filename}' não corresponde exatamente a nenhum expected_clip do manifesto"

    c_sidx = clip.get("scene_index")
    if c_sidx is not None and str(c_sidx) != str(matching_scene.get("scene_index")):
        return False, (
            f"scene_index do clipe ({c_sidx}) diverge do manifesto "
            f"({matching_scene.get('scene_index')}) para '{clip_filename}'"
        )

    # 6. is_flow_premium == True
    if not matching_scene.get("is_flow_premium", False):
        return False, f"Cena {matching_scene.get('scene_index')} no manifesto não está marcada como is_flow_premium=True"

    # 7. scene_index em completed_scenes
    scene_idx = matching_scene.get("scene_index")
    flow_gen = manifest.get("flow_generation", {})
    if not isinstance(flow_gen, dict):
        flow_gen = {}
    completed_scenes = flow_gen.get("completed_scenes", [])
    completed_set = {str(s) for s in (completed_scenes or [])}
    if str(scene_idx) not in completed_set:
        return False, f"Cena Flow {scene_idx} não consta em completed_scenes do manifesto"

    # 8. Verificação de status e recovery da geração Flow
    flow_status = str(flow_gen.get("status") or "").strip()
    manifest_status = str(manifest.get("status") or "").strip()

    if (
        flow_status == "FLOW_GENERATION_NEEDS_RECOVERY"
        or manifest_status == "FLOW_GENERATION_NEEDS_RECOVERY"
    ):
        return False, "Flow possui recovery pendente"

    if flow_status == "COMPLETE":
        return True, "GENERATED_FLOW_PROVENANCE_VERIFIED"

    if (
        flow_status.startswith("FAILED_SCENE_")
        or flow_status.startswith("FALLBACK_STOCK_SCENE_")
    ):
        if flow_status == f"FAILED_SCENE_{scene_idx}":
            return False, f"Cena Flow {scene_idx} falhou na geração"
        return True, "GENERATED_FLOW_PROVENANCE_VERIFIED"

    return False, f"Status da geração Flow não é COMPLETE (status={flow_status})"


def _reconstruct_legacy_flow_materials(
    task_id: str,
    task_base_dir: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Reconstrói material_sources a partir do manifesto do Google Flow para tasks legadas.

    Aplicável como fallback estrito quando material_sources e scene_materials estão
    ausentes ou vazios no script.json, mas flow/manifest.json e os clipes existem.

    Requisitos Fail-Closed:
    1. flow/manifest.json deve existir e ser JSON válido.
    2. flow_generation.status deve ser COMPLETE.
    3. Nem flow_generation.status nem manifest.status podem ser FLOW_GENERATION_NEEDS_RECOVERY.
    4. Cada cena utilizada deve:
       - ter scene_index válido;
       - ter expected_clip não-vazio;
       - ter is_flow_premium == True;
       - scene_index estar em completed_scenes.
    5. O arquivo flow/clips/<expected_clip> deve existir fisicamente e ter size > 0.
    6. Se qualquer critério falhar para qualquer cena, retorna lista vazia (fail-closed).
    """
    if not task_id or not str(task_id).strip():
        return []

    task_dir_path = _resolve_task_dir(task_id, task_base_dir)
    manifest_path = os.path.join(task_dir_path, "flow", "manifest.json")
    if not os.path.isfile(manifest_path):
        return []

    try:
        with open(manifest_path, "r", encoding="utf-8") as mf:
            manifest = json.load(mf)
    except Exception as exc:
        logger.warning(f"[COPYRIGHT_GATE] Manifesto Flow ilegível para reconstrução em {task_id}: {exc}")
        return []

    if not isinstance(manifest, dict):
        return []

    flow_gen = manifest.get("flow_generation")
    if not isinstance(flow_gen, dict):
        return []

    flow_status = flow_gen.get("status")
    if flow_status != "COMPLETE":
        return []

    if flow_status == "FLOW_GENERATION_NEEDS_RECOVERY" or manifest.get("status") == "FLOW_GENERATION_NEEDS_RECOVERY":
        return []

    completed_scenes = flow_gen.get("completed_scenes")
    if not isinstance(completed_scenes, (list, tuple)) or not completed_scenes:
        return []

    completed_set = {str(s) for s in completed_scenes}

    manifest_scenes = manifest.get("scenes")
    if not isinstance(manifest_scenes, (list, tuple)) or not manifest_scenes:
        return []

    clips_dir = os.path.join(task_dir_path, "flow", "clips")
    reconstructed: List[Dict[str, Any]] = []

    for sc in manifest_scenes:
        if not isinstance(sc, dict):
            return []

        scene_idx = sc.get("scene_index")
        if scene_idx is None:
            return []

        expected_clip = str(sc.get("expected_clip") or "").strip()
        if not expected_clip:
            return []

        if sc.get("is_flow_premium") is not True:
            return []

        if str(scene_idx) not in completed_set:
            return []

        clip_path = os.path.join(clips_dir, expected_clip)
        if not os.path.isfile(clip_path):
            return []

        try:
            if os.path.getsize(clip_path) <= 0:
                return []
        except OSError:
            return []

        reconstructed.append({
            "provider": "google_flow",
            "asset_id": expected_clip,
            "local_file": clip_path,
            "source_page": None,
            "search_term": sc.get("narration") or sc.get("prompt") or "",
            "duration": sc.get("duration_hint", 0),
            "used_duration_sec": sc.get("duration_hint", 0),
            "scene_index": scene_idx,
            "source": "generated",
            "visual_source_type": "flow",
            "provenance_status": "GENERATED_FLOW_EVIDENCE_RECORDED",
        })

    if not reconstructed:
        return []

    reconstructed.sort(key=lambda x: int(x.get("scene_index", 0)) if str(x.get("scene_index", 0)).isdigit() else 0)
    return reconstructed


def _get_param(params: Any, key: str, default: Any = None) -> Any:
    """Helper unificado para extrair campos de params seja dict ou objeto."""
    if params is None:
        return default
    if isinstance(params, dict):
        if key not in params and "params" in params and isinstance(params["params"], dict):
            val = params["params"].get(key, default)
            return default if val is None else val
        val = params.get(key, default)
        return default if val is None else val
    val = getattr(params, key, default)
    return default if val is None else val


def build_asset_provenance(
    task_id: str,
    params: Any,
    material_sources: Optional[List[Dict[str, Any]]] = None,
    bgm_file_used: Optional[str] = None,
    task_base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Constrói a estrutura padronizada de proveniência de ativos da tarefa."""
    raw_type = _get_param(params, "bgm_type", None)
    bgm_type = str(raw_type or "none").lower().strip()
    try:
        raw_vol = _get_param(params, "bgm_volume", None)
        if raw_vol is None:
            bgm_volume = 0.2 if bgm_type not in ("", "none") else 0.0
        else:
            bgm_volume = float(raw_vol)
    except (ValueError, TypeError):
        bgm_volume = 0.2 if bgm_type not in ("", "none") else 0.0

    bgm_is_enabled = bool(
        bgm_type
        and bgm_type != "none"
        and bgm_volume > 0
    )

    if not bgm_is_enabled:
        bgm_prov = {
            "enabled": False,
            "filename": None,
            "source": "none",
            "license_type": "not_applicable",
            "provenance_status": "SAFE_NO_BGM",
        }
    else:
        raw_bgm_file = bgm_file_used or _get_param(params, "bgm_file", "") or ""
        filename = Path(raw_bgm_file).name if raw_bgm_file else None

        if bgm_type == "ambient_auto":
            bgm_prov = {
                "enabled": True,
                "filename": filename or "ambient_auto_procedural",
                "source": "procedural",
                "license_type": "safe_procedural",
                "provenance_status": "SAFE_PROCEDURAL",
            }
        else:
            # Identifica se é faixa legada de resource/songs
            is_legacy = bool(
                (raw_bgm_file and ("resource" in raw_bgm_file and "songs" in raw_bgm_file))
                or (filename and filename.lower().startswith("output") and filename.lower().endswith(".mp3"))
                or bgm_type in ("random", "preset")
            )
            source = "legacy_resource_songs" if is_legacy else (
                "custom_upload" if bgm_type == "custom" else str(bgm_type)
            )
            bgm_prov = {
                "enabled": True,
                "filename": filename,
                "source": source,
                "license_type": "unknown",
                "provenance_status": "UNAUDITED_LEGACY" if is_legacy else ("UNAUDITED_CUSTOM" if bgm_type == "custom" else "UNKNOWN"),
            }

    # Se material_sources não foi fornecido ou está vazio, tenta ler do script.json
    if not material_sources:
        base_dir = task_base_dir or utils.task_dir()
        script_file = os.path.join(base_dir, task_id, "script.json")
        script_data: Dict[str, Any] = {}
        if os.path.isfile(script_file):
            try:
                with open(script_file, "r", encoding="utf-8") as f:
                    script_data = json.load(f)
            except Exception as exc:
                logger.debug(f"[COPYRIGHT] Não foi possível ler script.json para task {task_id}: {exc}")
        else:
            from app.services import task_artifacts
            try:
                target = task_artifacts._script_file(task_id)
                if target.is_file():
                    with target.open("r", encoding="utf-8") as f:
                        script_data = json.load(f)
            except Exception:
                pass
        material_sources = script_data.get("material_sources")
        if not material_sources and script_data.get("scene_materials"):
            material_sources = [
                {
                    "provider": sm.get("provider"),
                    "asset_id": sm.get("asset_id") or (os.path.basename(sm.get("material_path", "")) if sm.get("material_path") else None),
                    "local_file": sm.get("material_path"),
                    "source_page": sm.get("source_url") or "",
                    "search_term": sm.get("search_term_used") or "",
                    "duration": sm.get("duration", 0),
                    "used_duration_sec": sm.get("duration", 0),
                    "scene_index": sm.get("scene_index"),
                    "visual_source_type": sm.get("visual_source_type", "stock"),
                }
                for sm in script_data.get("scene_materials", [])
            ]
        if not material_sources:
            # Fallback backward-compatible para Flow legado (flow/manifest.json):
            material_sources = _reconstruct_legacy_flow_materials(
                task_id=task_id,
                task_base_dir=task_base_dir,
            )
        if material_sources is None:
            material_sources = []
        if not params and script_data.get("params"):
            params = script_data.get("params")
            raw_type = _get_param(params, "bgm_type", None)
            bgm_type = str(raw_type or "none").lower().strip()
            raw_vol = _get_param(params, "bgm_volume", None)
            bgm_volume = float(0.2 if raw_vol is None else raw_vol) if bgm_type not in ("", "none") else 0.0
            bgm_is_enabled = bool(bgm_type and bgm_type != "none" and bgm_volume > 0)
            if not bgm_is_enabled:
                bgm_prov = {
                    "enabled": False,
                    "filename": None,
                    "source": "none",
                    "license_type": "not_applicable",
                    "provenance_status": "SAFE_NO_BGM",
                }
            else:
                raw_bgm_file = bgm_file_used or _get_param(params, "bgm_file", "") or ""
                filename = Path(raw_bgm_file).name if raw_bgm_file else None
                if bgm_type == "ambient_auto":
                    bgm_prov = {
                        "enabled": True,
                        "filename": filename or "ambient_auto_procedural",
                        "source": "procedural",
                        "license_type": "safe_procedural",
                        "provenance_status": "SAFE_PROCEDURAL",
                    }
                else:
                    is_legacy = bool(
                        (raw_bgm_file and ("resource" in raw_bgm_file and "songs" in raw_bgm_file))
                        or (filename and filename.lower().startswith("output") and filename.lower().endswith(".mp3"))
                        or bgm_type in ("random", "preset")
                    )
                    source = "legacy_resource_songs" if is_legacy else ("custom_upload" if bgm_type == "custom" else str(bgm_type))
                    bgm_prov = {
                        "enabled": True,
                        "filename": filename,
                        "source": source,
                        "license_type": "unknown",
                        "provenance_status": "UNAUDITED_LEGACY" if is_legacy else ("UNAUDITED_CUSTOM" if bgm_type == "custom" else "UNKNOWN"),
                    }

    visual_clips: List[Dict[str, Any]] = []
    for item in (material_sources or []):
        provider = str(item.get("provider") or "unknown").lower().strip()
        asset_id = item.get("asset_id")
        external_id = str(asset_id) if asset_id not in (None, "") else None
        provider_url = item.get("source_page")
        local_file = str(item.get("local_file") or "")
        search_term = item.get("search_term")
        duration = item.get("duration")
        used_duration = item.get("used_duration_sec", duration)

        clip_dict = {
            "provider": provider,
            "external_id": external_id,
            "provider_url": provider_url,
            "local_file": local_file,
            "search_term": search_term,
            "used_duration_sec": used_duration,
        }
        if "scene_index" in item:
            clip_dict["scene_index"] = item["scene_index"]
        if "visual_source_type" in item:
            clip_dict["visual_source_type"] = item["visual_source_type"]
        if "provenance_status" in item:
            clip_dict["provenance_status"] = item["provenance_status"]
        if "source" in item:
            clip_dict["source"] = item["source"]
        visual_clips.append(clip_dict)

    # Proveniência do Presenter / Character Overlay (Fase V14-C)
    avatar_mode = str(_get_param(params, "avatar_mode", "none") or "none").lower().strip()
    if avatar_mode in ("", "none"):
        presenter_prov = {
            "enabled": False,
            "mode": "none",
        }
    else:
        provider = str(_get_param(params, "avatar_provider", "local") or "local")
        character_id = str(_get_param(params, "avatar_character_id", "") or "")
        asset_path = str(_get_param(params, "avatar_asset_path", "") or "")
        if not asset_path and character_id:
            try:
                from app.services import presenter
                pack = presenter.resolve_character_pack(character_id)
                asset_path = pack.get("root_dir", "")
                asset_type = "pack"
            except Exception:
                asset_type = "pack"
        else:
            ext = Path(asset_path).suffix.lower().lstrip(".") if asset_path else ""
            asset_type = ext if ext else "unknown"
        presenter_prov = {
            "enabled": True,
            "mode": avatar_mode,
            "provider": provider,
            "character_id": character_id,
            "asset_path": asset_path,
            "asset_type": asset_type,
            "provenance_status": "LOCAL_OPERATOR_ASSET",
        }

    prov_status = (
        "SAFE_NO_BGM"
        if not bgm_is_enabled and visual_clips
        else (
            "SAFE_PROCEDURAL"
            if bgm_is_enabled and bgm_prov.get("provenance_status") == "SAFE_PROCEDURAL" and visual_clips
            else ("UNVERIFIED_BGM" if bgm_is_enabled else "INCOMPLETE_ASSETS")
        )
    )

    return {
        "bgm": bgm_prov,
        "visual_clips": visual_clips,
        "presenter": presenter_prov,
        "provenance_status": prov_status,
    }


def get_legacy_task_copyright_approval(
    task_id: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Consulta aprovação manual persistida em operational_events para artefato final legado (V1.5E, read-only).

    Recupera o registro mais recente com event_type='TASK_COPYRIGHT_MANUAL_APPROVAL' para a task.
    Valida que o evento pertence ao operador, possui status 'clean_manual', escopo 'legacy_final_artifact'
    e hash SHA-256 válido gravado no metadata.
    Retorna None se não houver aprovação válida.
    """
    clean_task_id = str(task_id or "").strip()
    if not clean_task_id:
        return None

    try:
        from app.services import operator_console
        operator_console.init_operator_db(db_path)
    except Exception:
        pass

    from app.services import scheduler
    with scheduler.get_connection(db_path) as conn:
        try:
            rows = conn.execute(
                """
                SELECT id, timestamp, metadata_json
                FROM operational_events
                WHERE event_type = ? AND task_id = ?
                ORDER BY id DESC;
                """,
                (EVENT_TASK_COPYRIGHT_MANUAL_APPROVAL, clean_task_id),
            ).fetchall()
        except sqlite3.OperationalError:
            return None

        for row in rows:
            try:
                meta = json.loads(row["metadata_json"] or "{}")
                if (
                    str(meta.get("task_id") or "").strip() == clean_task_id
                    and str(meta.get("copyright_status") or "").strip().lower() == COPYRIGHT_STATUS_CLEAN_MANUAL
                    and str(meta.get("source") or "").strip().lower() == COPYRIGHT_SOURCE_OPERATOR
                    and str(meta.get("scope") or "").strip().lower() == SCOPE_LEGACY_FINAL_ARTIFACT
                    and meta.get("final_video_sha256")
                ):
                    return {
                        "id": row["id"],
                        "task_id": clean_task_id,
                        "copyright_status": COPYRIGHT_STATUS_CLEAN_MANUAL,
                        "source": COPYRIGHT_SOURCE_OPERATOR,
                        "scope": SCOPE_LEGACY_FINAL_ARTIFACT,
                        "final_video_sha256": str(meta.get("final_video_sha256")).lower().strip(),
                        "final_video_size": meta.get("final_video_size"),
                        "timestamp": meta.get("timestamp") or row["timestamp"],
                        "note": meta.get("note"),
                    }
            except Exception:
                continue

    return None


def _try_manual_legacy_approval_fallback(
    task_id: str,
    bgm_info: Dict[str, Any],
    task_base_dir: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Optional[Tuple[bool, str, Dict[str, Any]]]:
    """Tenta validar a aprovação manual de copyright para artefato final legado (V1.5E).

    Apenas converte falha de proveniência visual em PASS se TODOS os critérios forem atendidos:
    1. BGM deve ser SAFE_NO_BGM ou SAFE_PROCEDURAL.
    2. Zero evidência de claim, blocked ou strike.
    3. Existe TASK_COPYRIGHT_MANUAL_APPROVAL válida com source='operator' e copyright_status='clean_manual'.
    4. Arquivo final-1.mp4 canônico existe, não está vazio e seu SHA-256 é IDÊNTICO ao gravado na aprovação.
    5. Se houver cenas Flow premium no manifesto, todas devem estar fisicamente íntegras e passar
       estritamente em validate_flow_clip_provenance().
    6. Nunca retorna CONTENT_ID_SAFE.

    Retorna None se qualquer critério falhar (fail-closed).
    """
    clean_task_id = str(task_id or "").strip()
    if not clean_task_id:
        return None

    # 1. BGM deve continuar segura: SAFE_NO_BGM ou SAFE_PROCEDURAL
    bgm_enabled = bool(bgm_info.get("enabled"))
    if bgm_enabled:
        bgm_source = str(bgm_info.get("source") or "").lower()
        bgm_prov = str(bgm_info.get("provenance_status") or "").upper()
        if not (bgm_source == "procedural" or bgm_prov == "SAFE_PROCEDURAL"):
            return None

    # 2. Zero evidência de claim, blocked ou strike
    pub_status = get_publication_copyright_status(task_id=clean_task_id, db_path=db_path)
    if pub_status.get("copyright_status") in (
        COPYRIGHT_STATUS_CLAIMED,
        COPYRIGHT_STATUS_BLOCKED,
        COPYRIGHT_STATUS_STRIKE,
    ):
        return None

    from app.services import scheduler
    with scheduler.get_connection(db_path) as conn:
        try:
            adv_rows = conn.execute(
                "SELECT metadata_json FROM operational_events WHERE task_id = ? ORDER BY id DESC;",
                (clean_task_id,),
            ).fetchall()
            for r in adv_rows:
                try:
                    m = json.loads(r["metadata_json"] or "{}")
                    st = str(m.get("copyright_status") or "").lower().strip()
                    if st in (COPYRIGHT_STATUS_CLAIMED, COPYRIGHT_STATUS_BLOCKED, COPYRIGHT_STATUS_STRIKE):
                        return None
                except Exception:
                    continue
        except sqlite3.OperationalError:
            pass

    # 3. Consulta aprovação manual válida
    approval = get_legacy_task_copyright_approval(task_id=clean_task_id, db_path=db_path)
    if not approval:
        return None

    if approval.get("task_id") != clean_task_id:
        return None
    if approval.get("source") != COPYRIGHT_SOURCE_OPERATOR:
        return None
    if approval.get("copyright_status") != COPYRIGHT_STATUS_CLEAN_MANUAL:
        return None
    if approval.get("scope") != SCOPE_LEGACY_FINAL_ARTIFACT:
        return None

    approved_sha256 = approval.get("final_video_sha256")
    if not approved_sha256:
        return None

    # 4. final-1.mp4 deve existir, tamanho > 0 e SHA-256 deve coincidir exatamente
    task_dir_path = _resolve_task_dir(clean_task_id, task_base_dir)
    final_video_path = os.path.join(task_dir_path, "final-1.mp4")
    if not os.path.isfile(final_video_path):
        return None
    try:
        if os.path.getsize(final_video_path) <= 0:
            return None
        current_sha256 = calculate_file_sha256(final_video_path)
    except OSError:
        return None

    if current_sha256.lower() != approved_sha256.lower():
        return None

    # 5. Se houver Flow no manifesto: validar todas as cenas Flow premium estritamente
    flow_clips_verified = 0
    manifest_path = os.path.join(task_dir_path, "flow", "manifest.json")
    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as mf:
                manifest = json.load(mf)
        except Exception:
            return None

        if not isinstance(manifest, dict):
            return None

        flow_gen = manifest.get("flow_generation")
        if not isinstance(flow_gen, dict):
            return None

        if flow_gen.get("status") != "COMPLETE":
            return None
        if (
            flow_gen.get("status") == "FLOW_GENERATION_NEEDS_RECOVERY"
            or manifest.get("status") == "FLOW_GENERATION_NEEDS_RECOVERY"
        ):
            return None

        completed_scenes = {str(s) for s in (flow_gen.get("completed_scenes") or [])}
        scenes = manifest.get("scenes") or []
        if not isinstance(scenes, list):
            return None

        clips_dir = os.path.join(task_dir_path, "flow", "clips")
        for sc in scenes:
            if isinstance(sc, dict) and sc.get("is_flow_premium") is True:
                s_idx = sc.get("scene_index")
                if s_idx is None or str(s_idx) not in completed_scenes:
                    return None
                expected_clip = str(sc.get("expected_clip") or "").strip()
                if not expected_clip:
                    return None
                clip_file = os.path.join(clips_dir, expected_clip)
                if not os.path.isfile(clip_file):
                    return None
                try:
                    if os.path.getsize(clip_file) <= 0:
                        return None
                except OSError:
                    return None

                clip_dict = {
                    "local_file": clip_file,
                    "scene_index": s_idx,
                }
                valid, _ = validate_flow_clip_provenance(clean_task_id, clip_dict, task_base_dir)
                if not valid:
                    return None
                flow_clips_verified += 1

    # 6. Retorna PASS explícito de aprovação manual (nunca CONTENT_ID_SAFE)
    bgm_final_status = (
        "SAFE_PROCEDURAL"
        if (bgm_info.get("enabled") and bgm_info.get("provenance_status") == "SAFE_PROCEDURAL")
        else "SAFE_NO_BGM"
    )
    details: Dict[str, Any] = {
        "copyright_provenance_gate": "PASS",
        "approval_mode": APPROVAL_MODE_MANUAL_LEGACY,
        "copyright_status": COPYRIGHT_STATUS_CLEAN_MANUAL,
        "source": COPYRIGHT_SOURCE_OPERATOR,
        "final_video_sha256_verified": True,
        "final_video_sha256": current_sha256,
        "bgm_status": bgm_final_status,
    }
    if flow_clips_verified > 0:
        details["flow_provenance_status"] = "GENERATED_FLOW_PROVENANCE_VERIFIED"
        details["flow_clips_verified"] = flow_clips_verified
    if approval.get("note"):
        details["approval_note"] = approval["note"]

    return (
        True,
        f"COPYRIGHT_PROVENANCE_GATE = PASS ({APPROVAL_MODE_MANUAL_LEGACY})",
        details,
    )


def evaluate_copyright_provenance_gate(
    task_id: str,
    task_data: Optional[Dict[str, Any]] = None,
    task_base_dir: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Avalia a conformidade de procedência e direitos autorais da tarefa (V14-B).

    Regras Fail-Closed:
    A. BGM:
       - Autonomous com BGM legado (resource/songs) => FAIL
       - BGM desconhecido => FAIL
       - BGM none => PASS
       - Futura faixa em whitelist => PASS

    B. VISUAL:
       - Provider deve estar na lista autorizada: Pexels, Pixabay, Coverr
       - Cada arquivo utilizado deve conter proveniência mínima (local_file identificado)

    C. APROVAÇÃO MANUAL LEGADA (V1.5E):
       - Se automático FAIL por lacuna de proveniência visual legada E existir
         TASK_COPYRIGHT_MANUAL_APPROVAL válida para o SHA-256 exato de final-1.mp4,
         retorna PASS explícito (approval_mode=MANUAL_LEGACY_FINAL_ARTIFACT).

    D. NÃO PROMETER AUSÊNCIA DE CLAIM:
       - O retorno expressa COPYRIGHT_PROVENANCE_GATE = PASS, jamais CONTENT_ID_SAFE.
    """
    from app.services import state as sm
    from app.services import task_artifacts

    # 0. Verificação Prévia de Status Adverso Conhecido (claimed, blocked, strike)
    pub_status = get_publication_copyright_status(task_id=task_id, db_path=db_path)
    if pub_status.get("copyright_status") in (
        COPYRIGHT_STATUS_CLAIMED,
        COPYRIGHT_STATUS_BLOCKED,
        COPYRIGHT_STATUS_STRIKE,
    ):
        return (
            False,
            f"Tarefa com status de direitos autorais adverso registrado: {pub_status.get('copyright_status')}",
            {
                "copyright_provenance_gate": "FAIL",
                "copyright_status": pub_status.get("copyright_status"),
            },
        )

    # Obtém dados da memória ou do disco
    task_mem = task_data or sm.state.get_task(task_id) or {}
    base_dir = task_base_dir or utils.task_dir()
    script_file = os.path.join(base_dir, task_id, "script.json")

    script_data: Dict[str, Any] = {}
    if os.path.isfile(script_file):
        try:
            with open(script_file, "r", encoding="utf-8") as f:
                script_data = json.load(f)
        except Exception as exc:
            logger.warning(f"[COPYRIGHT_GATE] Falha ao ler script.json para {task_id}: {exc}")
    else:
        try:
            target = task_artifacts._script_file(task_id)
            if target.is_file():
                with target.open("r", encoding="utf-8") as f:
                    script_data = json.load(f)
        except Exception:
            pass

    params_data = script_data.get("params") or task_mem.get("params") or {}
    asset_prov = script_data.get("asset_provenance") or task_mem.get("asset_provenance")

    mat_sources_input = script_data.get("material_sources") or task_mem.get("material_sources")
    if not asset_prov:
        # Reconstrói a partir dos metadados existentes
        asset_prov = build_asset_provenance(
            task_id=task_id,
            params=params_data,
            material_sources=mat_sources_input,
            task_base_dir=task_base_dir,
        )
    elif not asset_prov.get("visual_clips"):
        # V1.5E: Se asset_provenance já existia persistido mas visual_clips está vazio
        # (caso de tasks legadas Flow sem material_sources/scene_materials no script.json),
        # tenta reconstrução estrita a partir do Flow manifest.
        rebuilt = build_asset_provenance(
            task_id=task_id,
            params=params_data,
            material_sources=mat_sources_input,
            task_base_dir=task_base_dir,
        )
        if rebuilt.get("visual_clips"):
            asset_prov["visual_clips"] = rebuilt["visual_clips"]
            if rebuilt.get("provenance_status"):
                asset_prov["provenance_status"] = rebuilt["provenance_status"]

    bgm_info = asset_prov.get("bgm", {})
    visual_clips = asset_prov.get("visual_clips", [])

    # 1. Verificação de BGM
    bgm_type = str(_get_param(params_data, "bgm_type", "") or "").lower().strip()

    if bgm_info.get("enabled"):
        bgm_source = str(bgm_info.get("source", "")).lower()
        bgm_prov_status = str(bgm_info.get("provenance_status", "")).upper()
        if bgm_type == "ambient_auto" and (bgm_source == "procedural" or bgm_prov_status == "SAFE_PROCEDURAL"):
            # SAFE_PROCEDURAL é expressamente aprovada para modo autônomo (V1.5E-G8)
            pass
        elif "legacy" in bgm_source or "songs" in bgm_source or bgm_type in ("random", "preset"):
            return (
                False,
                "BGM legado de resource/songs não é permitido em gerações autônomas",
                {
                    "copyright_provenance_gate": "FAIL",
                    "bgm_status": "BLOCKED_LEGACY",
                    "bgm_source": bgm_source,
                },
            )
        else:
            return (
                False,
                f"BGM ativa sem whitelist comprovada para produção autônoma (type={bgm_type})",
                {
                    "copyright_provenance_gate": "FAIL",
                    "bgm_status": "UNAPPROVED_SOURCE",
                    "bgm_source": bgm_source,
                },
            )

    # 2. Verificação de Ativos Visuais
    if not visual_clips:
        fallback = _try_manual_legacy_approval_fallback(
            task_id=task_id,
            bgm_info=bgm_info,
            task_base_dir=task_base_dir,
            db_path=db_path,
        )
        if fallback is not None:
            return fallback

        return (
            False,
            "Nenhum clip visual registrado na proveniência da tarefa",
            {
                "copyright_provenance_gate": "FAIL",
                "visual_status": "MISSING_CLIPS",
            },
        )

    flow_clips_verified = 0
    for idx, clip in enumerate(visual_clips):
        provider = str(clip.get("provider") or "").lower().strip()
        if not clip.get("local_file"):
            fallback = _try_manual_legacy_approval_fallback(
                task_id=task_id,
                bgm_info=bgm_info,
                task_base_dir=task_base_dir,
                db_path=db_path,
            )
            if fallback is not None:
                return fallback
            return (
                False,
                f"Clip #{idx + 1} sem identificação de arquivo local",
                {
                    "copyright_provenance_gate": "FAIL",
                    "missing_field": "local_file",
                    "clip_index": idx,
                },
            )

        if provider in ("google_flow", "flow"):
            valid, reason = validate_flow_clip_provenance(
                task_id=task_id,
                clip=clip,
                task_base_dir=task_base_dir,
            )
            if not valid:
                return (
                    False,
                    f"Falha na validação de proveniência do Google Flow no clip #{idx + 1}: {reason}",
                    {
                        "copyright_provenance_gate": "FAIL",
                        "unauthorized_provider": provider,
                        "flow_validation_failure": reason,
                        "clip_index": idx,
                    },
                )
            flow_clips_verified += 1
            clip["provenance_status"] = "GENERATED_FLOW_PROVENANCE_VERIFIED"
        elif provider in ALLOWED_AUTONOMOUS_VISUAL_PROVIDERS:
            # pexels, pixabay, coverr
            pass
        else:
            fallback = _try_manual_legacy_approval_fallback(
                task_id=task_id,
                bgm_info=bgm_info,
                task_base_dir=task_base_dir,
                db_path=db_path,
            )
            if fallback is not None:
                return fallback
            return (
                False,
                f"Provedor visual não autorizado ou sem proveniência comprovada: '{provider}' no clip #{idx + 1}. Permitidos: {sorted(ALLOWED_AUTONOMOUS_VISUAL_PROVIDERS)} ou 'google_flow' verificado.",
                {
                    "copyright_provenance_gate": "FAIL",
                    "unauthorized_provider": provider,
                    "clip_index": idx,
                },
            )

    bgm_final_status = (
        "SAFE_PROCEDURAL"
        if (bgm_info.get("enabled") and bgm_info.get("provenance_status") == "SAFE_PROCEDURAL")
        else "SAFE_NO_BGM"
    )
    details = {
        "copyright_provenance_gate": "PASS",
        "bgm_status": bgm_final_status,
        "visual_clips_count": len(visual_clips),
        "providers_verified": list(sorted({c.get("provider") for c in visual_clips})),
    }
    if flow_clips_verified > 0:
        details["flow_provenance_status"] = "GENERATED_FLOW_PROVENANCE_VERIFIED"
        details["flow_clips_verified"] = flow_clips_verified

    return (
        True,
        "COPYRIGHT_PROVENANCE_GATE = PASS",
        details,
    )



def get_publication_copyright_status(
    publication_event_id: Optional[int] = None,
    task_id: Optional[str] = None,
    external_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Consulta o status de copyright persistido e auditável para uma publicação/tarefa (V14-B.2).

    Recupera o registro mais recente em `operational_events` com event_type='PUBLICATION_COPYRIGHT_STATUS_SET'.
    Se nenhum registro auditado existir (como em publicações legadas), retorna status efetivo 'unknown'.
    Nunca chama rede nem APIs externas.
    """
    from app.services import scheduler

    clean_task_id = str(task_id).strip() if task_id else None
    clean_external_id = str(external_id).strip() if external_id else None
    clean_pub_id = int(publication_event_id) if publication_event_id is not None else None

    # Garante tabela operational_events se banco já existir
    try:
        from app.services import operator_console
        operator_console.init_operator_db(db_path)
    except Exception:
        pass

    with scheduler.get_connection(db_path) as conn:
        pub_row = None
        if clean_pub_id is not None:
            pub_row = conn.execute("SELECT * FROM publication_events WHERE id = ?", (clean_pub_id,)).fetchone()
        elif clean_task_id:
            pub_row = conn.execute(
                "SELECT * FROM publication_events WHERE task_id = ? AND platform = 'youtube' ORDER BY id DESC LIMIT 1",
                (clean_task_id,),
            ).fetchone()
        elif clean_external_id:
            pub_row = conn.execute(
                "SELECT * FROM publication_events WHERE external_id = ? AND platform = 'youtube' ORDER BY id DESC LIMIT 1",
                (clean_external_id,),
            ).fetchone()

        resolved_pub_id = clean_pub_id or (pub_row["id"] if pub_row else None)
        resolved_task_id = clean_task_id or (pub_row["task_id"] if pub_row else None)
        resolved_external_id = clean_external_id or (pub_row["external_id"] if pub_row else None)
        resolved_platform = (pub_row["platform"] if pub_row else "youtube")

        try:
            op_rows = conn.execute(
                "SELECT id, timestamp, metadata_json FROM operational_events "
                "WHERE event_type = 'PUBLICATION_COPYRIGHT_STATUS_SET' "
                "ORDER BY id DESC"
            ).fetchall()
        except sqlite3.OperationalError:
            op_rows = []

        for row in op_rows:
            try:
                meta = json.loads(row["metadata_json"] or "{}")
                m_pub_id = meta.get("publication_event_id")
                m_task_id = meta.get("task_id")
                m_ext_id = meta.get("external_id")

                match = False
                if resolved_pub_id is not None and m_pub_id is not None:
                    if int(m_pub_id) == int(resolved_pub_id):
                        match = True
                elif resolved_task_id and m_task_id:
                    if str(m_task_id) == str(resolved_task_id):
                        match = True
                elif resolved_external_id and m_ext_id:
                    if str(m_ext_id) == str(resolved_external_id):
                        match = True

                if match:
                    c_status = str(meta.get("copyright_status") or COPYRIGHT_STATUS_UNKNOWN).strip().lower()
                    if c_status not in ALLOWED_COPYRIGHT_STATUSES:
                        c_status = COPYRIGHT_STATUS_UNKNOWN
                    return {
                        "publication_event_id": resolved_pub_id if resolved_pub_id is not None else m_pub_id,
                        "task_id": resolved_task_id or m_task_id,
                        "platform": meta.get("platform", resolved_platform),
                        "external_id": resolved_external_id or m_ext_id,
                        "copyright_status": c_status,
                        "source": meta.get("source", COPYRIGHT_SOURCE_OPERATOR),
                        "timestamp": meta.get("timestamp") or row["timestamp"],
                        "note": meta.get("note") or meta.get("optional_note"),
                    }
            except Exception:
                continue

    return {
        "publication_event_id": resolved_pub_id,
        "task_id": resolved_task_id,
        "platform": resolved_platform,
        "external_id": resolved_external_id,
        "copyright_status": COPYRIGHT_STATUS_UNKNOWN,
        "source": None,
        "timestamp": None,
        "note": None,
    }


def set_publication_copyright_status_op(*args, **kwargs):
    """Encaminha para a operação auditável em operator_console (PRIMARY only)."""
    from app.services import operator_console
    return operator_console.set_publication_copyright_status_op(*args, **kwargs)


def approve_legacy_task_copyright_op(*args, **kwargs):
    """Encaminha para a aprovação manual de copyright legado em operator_console (PRIMARY only)."""
    from app.services import operator_console
    return operator_console.approve_legacy_task_copyright_op(*args, **kwargs)


def get_copyright_provenance_summary(
    task_id: Optional[str] = None,
    profile_id: Optional[str] = None,
    task_base_dir: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Retorna um resumo de Copyright e Provenance para visualização no Operator Console."""
    from app.services import state as sm

    resolved_task_id = task_id
    if not resolved_task_id:
        try:
            from app.services import autonomous_production
            status_data = autonomous_production.get_autonomous_status(
                profile_id=profile_id, db_path=db_path
            )
            curr = status_data.get("current_task_id")
            if curr and curr != "—":
                resolved_task_id = curr
        except Exception:
            pass

    if not resolved_task_id:
        return {
            "task_id": "—",
            "bgm_mode": "none",
            "bgm_filename": "Nenhuma (SAFE_NO_BGM)",
            "bgm_provenance": "SAFE_NO_BGM",
            "visual_providers": ["Pexels", "Pixabay", "Coverr"],
            "clips_count": 0,
            "provenance_status": "SAFE_NO_BGM",
            "copyright_gate_status": "PASS",
            "copyright_status": COPYRIGHT_STATUS_UNKNOWN,
            "copyright_source": "—",
            "copyright_note": None,
            "feedback_loop_eligible": False,
            "presenter_mode": "none",
            "presenter_character_id": "none",
            "presenter_provider": "local",
            "presenter_asset_status": "NOT_CONFIGURED",
        }

    task_mem = sm.state.get_task(resolved_task_id) or {}
    base_dir = task_base_dir or utils.task_dir()
    script_file = os.path.join(base_dir, resolved_task_id, "script.json")

    script_data: Dict[str, Any] = {}
    if os.path.isfile(script_file):
        try:
            with open(script_file, "r", encoding="utf-8") as f:
                script_data = json.load(f)
        except Exception:
            pass

    asset_prov = script_data.get("asset_provenance") or task_mem.get("asset_provenance")
    if not asset_prov:
        asset_prov = build_asset_provenance(
            task_id=resolved_task_id,
            params=script_data.get("params") or task_mem.get("params") or {},
            material_sources=script_data.get("material_sources"),
            task_base_dir=task_base_dir,
        )

    bgm_info = asset_prov.get("bgm", {})
    visual_clips = asset_prov.get("visual_clips", [])
    providers = list(sorted({c.get("provider", "").title() for c in visual_clips if c.get("provider")}))

    gate_pass, _, _ = evaluate_copyright_provenance_gate(
        task_id=resolved_task_id,
        task_data=task_mem,
        task_base_dir=task_base_dir,
        db_path=db_path,
    )

    presenter_info = asset_prov.get("presenter", {})
    presenter_mode = presenter_info.get("mode", "none")
    presenter_enabled = presenter_info.get("enabled", False)
    presenter_provider = presenter_info.get("provider", "local")
    presenter_character_id = presenter_info.get("character_id", "")
    presenter_asset_path = presenter_info.get("asset_path", "")
    presenter_asset_status = "NOT_CONFIGURED" if not presenter_enabled else (
        "VALID_LOCAL_ASSET" if (
            (presenter_asset_path and (os.path.isfile(presenter_asset_path) or os.path.isdir(presenter_asset_path)))
            or (presenter_character_id and presenter_character_id != "none")
        ) else "MISSING_ASSET"
    )

    c_info = get_publication_copyright_status(task_id=resolved_task_id, db_path=db_path)
    c_status = c_info.get("copyright_status") or COPYRIGHT_STATUS_UNKNOWN
    c_source = c_info.get("source") or "—"
    c_note = c_info.get("note")
    if c_status == COPYRIGHT_STATUS_UNKNOWN:
        legacy_appr = get_legacy_task_copyright_approval(task_id=resolved_task_id, db_path=db_path)
        if legacy_appr:
            c_status = legacy_appr.get("copyright_status") or COPYRIGHT_STATUS_CLEAN_MANUAL
            c_source = legacy_appr.get("source") or COPYRIGHT_SOURCE_OPERATOR
            c_note = legacy_appr.get("note")
    feedback_eligible = (c_status == COPYRIGHT_STATUS_CLEAN_MANUAL)

    return {
        "task_id": resolved_task_id,
        "bgm_mode": "none" if not bgm_info.get("enabled") else ("procedural" if bgm_info.get("source") == "procedural" else "custom"),
        "bgm_filename": bgm_info.get("filename") or "Nenhuma (SAFE_NO_BGM)",
        "bgm_provenance": bgm_info.get("provenance_status", "SAFE_NO_BGM"),
        "visual_providers": providers or ["Pexels", "Pixabay", "Coverr"],
        "clips_count": len(visual_clips),
        "provenance_status": asset_prov.get("provenance_status", "SAFE_NO_BGM"),
        "copyright_gate_status": "PASS" if gate_pass else "FAIL",
        "copyright_status": c_status,
        "copyright_source": c_source,
        "copyright_note": c_note,
        "feedback_loop_eligible": feedback_eligible,
        "publication_event_id": c_info.get("publication_event_id"),
        "external_id": c_info.get("external_id"),
        "presenter_mode": presenter_mode,
        "presenter_character_id": presenter_character_id or "none",
        "presenter_provider": presenter_provider,
        "presenter_asset_status": presenter_asset_status,
    }

