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

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from app.utils import utils

# Provedores visuais autorizados para o fluxo autônomo
ALLOWED_AUTONOMOUS_VISUAL_PROVIDERS = frozenset({"pexels", "pixabay", "coverr"})

# Conceitos para status futuro de direitos autorais (sem polling automático)
COPYRIGHT_STATUS_UNKNOWN = "unknown"
COPYRIGHT_STATUS_CLEAN_MANUAL = "clean_manual"
COPYRIGHT_STATUS_CLAIMED = "claimed"
COPYRIGHT_STATUS_BLOCKED = "blocked"
COPYRIGHT_STATUS_STRIKE = "strike"

COPYRIGHT_SOURCE_OPERATOR = "operator"
COPYRIGHT_SOURCE_FUTURE_PROVIDER = "future_provider"


def build_asset_provenance(
    task_id: str,
    params: Any,
    material_sources: Optional[List[Dict[str, Any]]] = None,
    bgm_file_used: Optional[str] = None,
) -> Dict[str, Any]:
    """Constrói a estrutura padronizada de proveniência de ativos da tarefa."""
    bgm_type = getattr(params, "bgm_type", None) or "none"
    try:
        bgm_volume = float(getattr(params, "bgm_volume", 0.0) or 0.0)
    except (ValueError, TypeError):
        bgm_volume = 0.0

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
        raw_bgm_file = bgm_file_used or getattr(params, "bgm_file", "") or ""
        filename = Path(raw_bgm_file).name if raw_bgm_file else None
        
        # Identifica se é faixa legada de resource/songs
        is_legacy = bool(
            raw_bgm_file and ("resource" in raw_bgm_file and "songs" in raw_bgm_file)
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
            "provenance_status": "UNAUDITED_LEGACY" if is_legacy else "UNKNOWN",
        }

    # Se material_sources não foi fornecido, tenta ler do script.json
    if material_sources is None:
        from app.services import task_artifacts
        script_data: Dict[str, Any] = {}
        try:
            target = task_artifacts._script_file(task_id)
            if target.is_file():
                with target.open("r", encoding="utf-8") as f:
                    script_data = json.load(f)
        except Exception as exc:
            logger.debug(f"[COPYRIGHT] Não foi possível ler script.json para task {task_id}: {exc}")
        material_sources = script_data.get("material_sources", [])

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

        visual_clips.append({
            "provider": provider,
            "external_id": external_id,
            "provider_url": provider_url,
            "local_file": local_file,
            "search_term": search_term,
            "used_duration_sec": used_duration,
        })

    prov_status = (
        "SAFE_NO_BGM"
        if not bgm_is_enabled and visual_clips
        else ("UNVERIFIED_BGM" if bgm_is_enabled else "INCOMPLETE_ASSETS")
    )

    return {
        "bgm": bgm_prov,
        "visual_clips": visual_clips,
        "provenance_status": prov_status,
    }


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

    C. NÃO PROMETER AUSÊNCIA DE CLAIM:
       - O retorno expressa COPYRIGHT_PROVENANCE_GATE = PASS, jamais CONTENT_ID_SAFE.
    """
    from app.services import state as sm
    from app.services import task_artifacts

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

    params_data = script_data.get("params") or task_mem.get("params") or {}
    asset_prov = script_data.get("asset_provenance") or task_mem.get("asset_provenance")

    if not asset_prov:
        # Reconstrói a partir dos metadados existentes
        asset_prov = build_asset_provenance(
            task_id=task_id,
            params=params_data,
            material_sources=script_data.get("material_sources"),
        )

    bgm_info = asset_prov.get("bgm", {})
    visual_clips = asset_prov.get("visual_clips", [])

    # 1. Verificação de BGM
    bgm_type = str(
        params_data.get("bgm_type")
        if isinstance(params_data, dict)
        else getattr(params_data, "bgm_type", "") or ""
    ).lower().strip()

    if bgm_info.get("enabled"):
        bgm_source = str(bgm_info.get("source", "")).lower()
        if "legacy" in bgm_source or "songs" in bgm_source or bgm_type in ("random", "preset"):
            return (
                False,
                "BGM legado de resource/songs não é permitido em gerações autônomas",
                {
                    "copyright_provenance_gate": "FAIL",
                    "bgm_status": "BLOCKED_LEGACY",
                    "bgm_source": bgm_source,
                },
            )
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
        return (
            False,
            "Nenhum clip visual registrado na proveniência da tarefa",
            {
                "copyright_provenance_gate": "FAIL",
                "visual_status": "MISSING_CLIPS",
            },
        )

    for idx, clip in enumerate(visual_clips):
        provider = str(clip.get("provider") or "").lower().strip()
        if provider not in ALLOWED_AUTONOMOUS_VISUAL_PROVIDERS:
            return (
                False,
                f"Provedor visual não autorizado: '{provider}' no clip #{idx + 1}. Permitidos: {sorted(ALLOWED_AUTONOMOUS_VISUAL_PROVIDERS)}",
                {
                    "copyright_provenance_gate": "FAIL",
                    "unauthorized_provider": provider,
                    "clip_index": idx,
                },
            )
        if not clip.get("local_file"):
            return (
                False,
                f"Clip #{idx + 1} sem identificação de arquivo local",
                {
                    "copyright_provenance_gate": "FAIL",
                    "missing_field": "local_file",
                    "clip_index": idx,
                },
            )

    return (
        True,
        "COPYRIGHT_PROVENANCE_GATE = PASS",
        {
            "copyright_provenance_gate": "PASS",
            "bgm_status": "SAFE_NO_BGM",
            "visual_clips_count": len(visual_clips),
            "providers_verified": list(sorted({c.get("provider") for c in visual_clips})),
        },
    )


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
        # Tenta pegar a tarefa atual do perfil ou a última tarefa registrada
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
            "feedback_loop_eligible": True,
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

    return {
        "task_id": resolved_task_id,
        "bgm_mode": "none" if not bgm_info.get("enabled") else "custom",
        "bgm_filename": bgm_info.get("filename") or "Nenhuma (SAFE_NO_BGM)",
        "bgm_provenance": bgm_info.get("provenance_status", "SAFE_NO_BGM"),
        "visual_providers": providers or ["Pexels", "Pixabay", "Coverr"],
        "clips_count": len(visual_clips),
        "provenance_status": asset_prov.get("provenance_status", "SAFE_NO_BGM"),
        "copyright_gate_status": "PASS" if gate_pass else "FAIL",
        "copyright_status": COPYRIGHT_STATUS_UNKNOWN,
        "feedback_loop_eligible": True,
    }
