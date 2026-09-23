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
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from app.utils import utils

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

    # Se material_sources não foi fornecido, tenta ler do script.json
    if material_sources is None:
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
        material_sources = script_data.get("material_sources", [])
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

        visual_clips.append({
            "provider": provider,
            "external_id": external_id,
            "provider_url": provider_url,
            "local_file": local_file,
            "search_term": search_term,
            "used_duration_sec": used_duration,
        })

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
        else ("UNVERIFIED_BGM" if bgm_is_enabled else "INCOMPLETE_ASSETS")
    )

    return {
        "bgm": bgm_prov,
        "visual_clips": visual_clips,
        "presenter": presenter_prov,
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

    if not asset_prov:
        # Reconstrói a partir dos metadados existentes
        asset_prov = build_asset_provenance(
            task_id=task_id,
            params=params_data,
            material_sources=script_data.get("material_sources"),
            task_base_dir=task_base_dir,
        )

    bgm_info = asset_prov.get("bgm", {})
    visual_clips = asset_prov.get("visual_clips", [])

    # 1. Verificação de BGM
    bgm_type = str(_get_param(params_data, "bgm_type", "") or "").lower().strip()

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
    feedback_eligible = (c_status == COPYRIGHT_STATUS_CLEAN_MANUAL)

    return {
        "task_id": resolved_task_id,
        "bgm_mode": "none" if not bgm_info.get("enabled") else "custom",
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
        "presenter_mode": presenter_mode,
        "presenter_character_id": presenter_character_id or "none",
        "presenter_provider": presenter_provider,
        "presenter_asset_status": presenter_asset_status,
    }

