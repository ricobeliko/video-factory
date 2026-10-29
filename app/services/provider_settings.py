"""Provider settings management for Web UI V2.

Canonical service for reading and updating LLM provider and Upload-Post
configurations with key masking, atomic persistence, and backup.
"""

import os
import shutil
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from app.config import config
from app.models.llm_provider import (
    DEFAULT_LLM_PROVIDER_ID,
    LLM_PROVIDER_REGISTRY,
    get_llm_provider,
)
from app.services import operator_console
from app.utils import utils

VALID_PLATFORMS = {"tiktok", "instagram", "youtube"}
VALID_PRIVACY_STATUSES = {"public", "private", "unlisted"}


def mask_api_key(key: Optional[str]) -> str:
    """Retorna máscara com os 4 últimos caracteres de uma chave de API."""
    if not key or not str(key).strip():
        return ""
    clean = str(key).strip()
    if len(clean) <= 4:
        return "••••"
    return "••••" + clean[-4:]


def is_masked_or_empty(value: Optional[str], current_value: Optional[str] = None) -> bool:
    """Verifica se um valor de chave representa 'não alterar' (vazio ou máscara)."""
    if value is None:
        return True
    val_str = str(value).strip()
    if not val_str:
        return True
    if val_str.startswith("••••") or val_str.startswith("****"):
        return True
    if current_value:
        current_mask = mask_api_key(current_value)
        if current_mask and val_str == current_mask:
            return True
    return False


def get_providers_settings_snapshot() -> Dict[str, Any]:
    """Retorna snapshot das configurações de provedores com chaves mascaradas."""
    active_llm_id = str(config.app.get("llm_provider", DEFAULT_LLM_PROVIDER_ID)).strip().lower()
    active_spec = get_llm_provider(active_llm_id)
    if active_spec is None:
        active_llm_id = DEFAULT_LLM_PROVIDER_ID
        active_spec = get_llm_provider(active_llm_id)

    available_providers = []
    for p in LLM_PROVIDER_REGISTRY:
        p_key = config.app.get(p.config_key("api_key"), "")
        is_cfg = bool(p_key and str(p_key).strip())
        available_providers.append({
            "id": p.provider_id,
            "label": p.default_label,
            "default_model": p.default_model,
            "show_api_key": p.show_api_key,
            "show_base_url": p.show_base_url,
            "is_configured": is_cfg,
            "masked_api_key": mask_api_key(p_key) if is_cfg else "",
            "model_name": str(config.app.get(p.config_key("model_name"), "") or p.default_model),
            "base_url": str(config.app.get(p.config_key("base_url"), "") or p.effective_default_base_url),
        })

    active_key = config.app.get(active_spec.config_key("api_key"), "") if active_spec else ""
    active_is_cfg = bool(active_key and str(active_key).strip())

    llm_info = {
        "provider": active_llm_id,
        "provider_label": active_spec.default_label if active_spec else active_llm_id,
        "model_name": str(config.app.get(active_spec.config_key("model_name"), "") or (active_spec.default_model if active_spec else "")),
        "base_url": str(config.app.get(active_spec.config_key("base_url"), "") or (active_spec.effective_default_base_url if active_spec else "")),
        "is_configured": active_is_cfg,
        "masked_api_key": mask_api_key(active_key) if active_is_cfg else "",
        "show_api_key": active_spec.show_api_key if active_spec else True,
        "show_base_url": active_spec.show_base_url if active_spec else True,
        "available_providers": available_providers,
    }

    upload_post_key = config.app.get("upload_post_api_key", "")
    up_is_cfg = bool(upload_post_key and str(upload_post_key).strip())

    raw_platforms = config.app.get("upload_post_platforms", ["youtube", "tiktok"])
    if isinstance(raw_platforms, str):
        platforms = [p.strip() for p in raw_platforms.split(",") if p.strip()]
    elif isinstance(raw_platforms, list):
        platforms = list(raw_platforms)
    else:
        platforms = ["youtube", "tiktok"]

    upload_post_info = {
        "enabled": bool(config.app.get("upload_post_enabled", False)),
        "auto_upload": bool(config.app.get("upload_post_auto_upload", False)),
        "username": str(config.app.get("upload_post_username", "")),
        "is_configured": up_is_cfg,
        "masked_api_key": mask_api_key(upload_post_key) if up_is_cfg else "",
        "platforms": platforms,
        "youtube_privacy_status": str(config.app.get("upload_post_youtube_privacy_status", "public")),
        "youtube_made_for_kids": bool(config.app.get("upload_post_youtube_made_for_kids", False)),
    }

    return {
        "llm": llm_info,
        "upload_post": upload_post_info,
    }


def update_providers_settings(
    updates: Dict[str, Any],
    db_path: Optional[str] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """Aplica atualizações nas configurações de provedores de forma atômica e com backup."""
    # 1. Validações
    known_provider_ids = {p.provider_id for p in LLM_PROVIDER_REGISTRY}

    new_provider = updates.get("llm_provider")
    if new_provider is not None:
        p_clean = str(new_provider).strip().lower()
        if p_clean not in known_provider_ids:
            raise ValueError(
                f"Provedor LLM inválido: '{new_provider}'. Provedores suportados: {sorted(list(known_provider_ids))}"
            )

    new_privacy = updates.get("upload_post_youtube_privacy_status")
    if new_privacy is not None:
        priv_clean = str(new_privacy).strip().lower()
        if priv_clean not in VALID_PRIVACY_STATUSES:
            raise ValueError(
                f"Status de privacidade YouTube inválido: '{new_privacy}'. Valores permitidos: {sorted(list(VALID_PRIVACY_STATUSES))}"
            )

    new_platforms = updates.get("upload_post_platforms")
    if new_platforms is not None:
        if not isinstance(new_platforms, list):
            raise ValueError("Plataformas devem ser fornecidas como uma lista de strings")
        for plat in new_platforms:
            if str(plat).strip().lower() not in VALID_PLATFORMS:
                raise ValueError(
                    f"Plataforma inválida: '{plat}'. Plataformas permitidas: {sorted(list(VALID_PLATFORMS))}"
                )

    # 2. Determina provedor alvo para chaves/modelos LLM
    current_provider = str(config.app.get("llm_provider", DEFAULT_LLM_PROVIDER_ID)).strip().lower()
    target_provider = str(new_provider).strip().lower() if new_provider is not None else current_provider
    target_spec = get_llm_provider(target_provider)

    updated_fields: List[str] = []

    # 3. Cria backup do arquivo de configuração antes de qualquer mutação
    cfg_file = getattr(config, "config_file", os.path.join(utils.root_dir(), "config.toml"))
    if os.path.exists(cfg_file):
        backup_path = cfg_file + ".bak"
        try:
            shutil.copy2(cfg_file, backup_path)
            logger.info(f"Backup do config.toml criado em: {backup_path}")
        except Exception as exc:
            logger.warning(f"Falha ao criar backup de {cfg_file}: {exc}")

    # 4. Aplica atualizações em config.app
    # Provedor ativo
    if new_provider is not None and target_provider != current_provider:
        config.app["llm_provider"] = target_provider
        updated_fields.append("llm_provider")

    # Chave LLM
    new_llm_key = updates.get("llm_api_key")
    if new_llm_key is not None:
        key_config_name = target_spec.config_key("api_key") if target_spec else f"{target_provider}_api_key"
        current_llm_key = config.app.get(key_config_name, "")
        if not is_masked_or_empty(new_llm_key, current_llm_key):
            clean_key = str(new_llm_key).strip()
            if clean_key != current_llm_key:
                config.app[key_config_name] = clean_key
                updated_fields.append("llm_api_key")

    # Modelo LLM
    new_model = updates.get("llm_model_name")
    if new_model is not None:
        model_config_name = target_spec.config_key("model_name") if target_spec else f"{target_provider}_model_name"
        clean_model = str(new_model).strip()
        if clean_model != config.app.get(model_config_name, ""):
            config.app[model_config_name] = clean_model
            updated_fields.append("llm_model_name")

    # Base URL LLM
    new_base_url = updates.get("llm_base_url")
    if new_base_url is not None:
        base_url_config_name = target_spec.config_key("base_url") if target_spec else f"{target_provider}_base_url"
        clean_url = str(new_base_url).strip()
        if clean_url != config.app.get(base_url_config_name, ""):
            config.app[base_url_config_name] = clean_url
            updated_fields.append("llm_base_url")

    # Upload-Post
    if "upload_post_enabled" in updates and updates["upload_post_enabled"] is not None:
        val = bool(updates["upload_post_enabled"])
        if config.app.get("upload_post_enabled") != val:
            config.app["upload_post_enabled"] = val
            updated_fields.append("upload_post_enabled")

    if "upload_post_auto_upload" in updates and updates["upload_post_auto_upload"] is not None:
        val = bool(updates["upload_post_auto_upload"])
        if config.app.get("upload_post_auto_upload") != val:
            config.app["upload_post_auto_upload"] = val
            updated_fields.append("upload_post_auto_upload")

    if "upload_post_username" in updates and updates["upload_post_username"] is not None:
        clean_uname = str(updates["upload_post_username"]).strip()
        if config.app.get("upload_post_username") != clean_uname:
            config.app["upload_post_username"] = clean_uname
            updated_fields.append("upload_post_username")

    new_up_key = updates.get("upload_post_api_key")
    if new_up_key is not None:
        current_up_key = config.app.get("upload_post_api_key", "")
        if not is_masked_or_empty(new_up_key, current_up_key):
            clean_up_key = str(new_up_key).strip()
            if clean_up_key != current_up_key:
                config.app["upload_post_api_key"] = clean_up_key
                updated_fields.append("upload_post_api_key")

    if new_platforms is not None:
        clean_platforms = [str(p).strip().lower() for p in new_platforms]
        if config.app.get("upload_post_platforms") != clean_platforms:
            config.app["upload_post_platforms"] = clean_platforms
            updated_fields.append("upload_post_platforms")

    if new_privacy is not None:
        clean_priv = str(new_privacy).strip().lower()
        if config.app.get("upload_post_youtube_privacy_status") != clean_priv:
            config.app["upload_post_youtube_privacy_status"] = clean_priv
            updated_fields.append("upload_post_youtube_privacy_status")

    if "upload_post_youtube_made_for_kids" in updates and updates["upload_post_youtube_made_for_kids"] is not None:
        val = bool(updates["upload_post_youtube_made_for_kids"])
        if config.app.get("upload_post_youtube_made_for_kids") != val:
            config.app["upload_post_youtube_made_for_kids"] = val
            updated_fields.append("upload_post_youtube_made_for_kids")

    # 5. Salva configuração no disco atomicamente se houver alterações
    if updated_fields:
        config.save_config()

        # 6. Registra evento de auditoria SEM expor segredos
        operator_console.log_operational_event(
            component="settings",
            severity=operator_console.SEVERITY_INFO,
            event_type="PROVIDER_SETTINGS_UPDATED",
            message=f"Configurações de provedores atualizadas: {', '.join(updated_fields)}",
            metadata={
                "updated_fields": updated_fields,
            },
            db_path=db_path,
        )

    return get_providers_settings_snapshot(), updated_fields
