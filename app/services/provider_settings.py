"""Provider settings management for Web UI V2.

Canonical service for reading and updating LLM provider and Upload-Post
configurations with key masking, disk-first atomic persistence, and backup.
"""

from datetime import datetime
import os
import shutil
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
import toml

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
DEFAULT_MAX_BACKUPS = 10


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


def read_raw_toml_from_disk(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Lê o arquivo TOML diretamente do disco garantindo integridade.

    Se a leitura falhar ou o arquivo estiver inválido, lança RuntimeError claro
    sem expor conteúdo ou chaves.
    """
    target_file = config_path or getattr(config, "config_file", os.path.join(utils.root_dir(), "config.toml"))
    if not os.path.isfile(target_file):
        logger.error(f"Arquivo de configuracao nao encontrado: {target_file}")
        raise RuntimeError("Falha ao ler o arquivo de configuracao no disco (arquivo nao encontrado).")

    try:
        with open(target_file, mode="r", encoding="utf-8") as f:
            raw_text = f.read()
        normalized = raw_text.lstrip("\ufeff")
        data = toml.loads(normalized)
        if not isinstance(data, dict):
            raise ValueError("Conteudo TOML nao estruturado como dicionario")
        return data
    except Exception as exc:
        logger.error(f"Falha ao ler ou decodificar arquivo TOML {target_file}: {type(exc).__name__}")
        raise RuntimeError("Falha ao ler ou decodificar o arquivo de configuracao no disco (TOML invalido ou inacessivel).")


def create_timestamped_backup(config_path: str, max_backups: int = DEFAULT_MAX_BACKUPS) -> str:
    """Cria backup nomeado com data/hora (config.toml.bak.YYYYMMDD_HHMMSS) e retém os 10 mais recentes."""
    if not os.path.isfile(config_path):
        return ""

    dir_name = os.path.dirname(os.path.abspath(config_path))
    base_name = os.path.basename(config_path)

    now = datetime.now()
    ts_str = now.strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(dir_name, f"{base_name}.bak.{ts_str}")

    # Garante que dois backups gerados no mesmo segundo tenham nomes distintos
    if os.path.exists(backup_path):
        seq = 1
        while os.path.exists(os.path.join(dir_name, f"{base_name}.bak.{ts_str}_{seq}")):
            seq += 1
        backup_path = os.path.join(dir_name, f"{base_name}.bak.{ts_str}_{seq}")

    try:
        shutil.copy2(config_path, backup_path)
        logger.info(f"Backup do config criado em: {backup_path}")
        prune_old_backups(config_path, max_backups=max_backups)
        return backup_path
    except Exception as exc:
        logger.warning(f"Falha ao criar backup de {config_path}: {exc}")
        return ""


def prune_old_backups(config_path: str, max_backups: int = DEFAULT_MAX_BACKUPS) -> List[str]:
    """Remove backups antigos mantendo apenas os max_backups mais recentes."""
    dir_name = os.path.dirname(os.path.abspath(config_path))
    base_name = os.path.basename(config_path)
    prefix = f"{base_name}.bak."

    backups = []
    try:
        for fname in os.listdir(dir_name):
            if fname.startswith(prefix):
                full_path = os.path.join(dir_name, fname)
                if os.path.isfile(full_path):
                    backups.append((os.path.getmtime(full_path), fname, full_path))
    except OSError as exc:
        logger.warning(f"Falha ao listar backups em {dir_name}: {exc}")
        return []

    # Ordena pelo mtime crescente e nome
    backups.sort(key=lambda x: (x[0], x[1]))

    removed = []
    while len(backups) > max_backups:
        oldest = backups.pop(0)
        try:
            os.remove(oldest[2])
            removed.append(oldest[2])
        except OSError as exc:
            logger.warning(f"Falha ao remover backup antigo {oldest[2]}: {exc}")

    return removed


def get_providers_settings_snapshot(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Retorna snapshot das configurações de provedores lidas diretamente do DISCO com chaves mascaradas."""
    with config._config_save_lock:
        disk_data = read_raw_toml_from_disk(config_path)
        disk_app = disk_data.get("app", {})
        if not isinstance(disk_app, dict):
            disk_app = {}

        active_llm_id = str(disk_app.get("llm_provider", DEFAULT_LLM_PROVIDER_ID)).strip().lower()
        active_spec = get_llm_provider(active_llm_id)
        if active_spec is None:
            active_llm_id = DEFAULT_LLM_PROVIDER_ID
            active_spec = get_llm_provider(active_llm_id)

        available_providers = []
        for p in LLM_PROVIDER_REGISTRY:
            p_key = disk_app.get(p.config_key("api_key"), "")
            is_cfg = bool(p_key and str(p_key).strip())
            available_providers.append({
                "id": p.provider_id,
                "label": p.default_label,
                "default_model": p.default_model,
                "show_api_key": p.show_api_key,
                "show_base_url": p.show_base_url,
                "is_configured": is_cfg,
                "masked_api_key": mask_api_key(p_key) if is_cfg else "",
                "model_name": str(disk_app.get(p.config_key("model_name"), "") or p.default_model),
                "base_url": str(disk_app.get(p.config_key("base_url"), "") or p.effective_default_base_url),
            })

        active_key = disk_app.get(active_spec.config_key("api_key"), "") if active_spec else ""
        active_is_cfg = bool(active_key and str(active_key).strip())

        llm_info = {
            "provider": active_llm_id,
            "provider_label": active_spec.default_label if active_spec else active_llm_id,
            "model_name": str(disk_app.get(active_spec.config_key("model_name"), "") or (active_spec.default_model if active_spec else "")),
            "base_url": str(disk_app.get(active_spec.config_key("base_url"), "") or (active_spec.effective_default_base_url if active_spec else "")),
            "is_configured": active_is_cfg,
            "masked_api_key": mask_api_key(active_key) if active_is_cfg else "",
            "show_api_key": active_spec.show_api_key if active_spec else True,
            "show_base_url": active_spec.show_base_url if active_spec else True,
            "available_providers": available_providers,
        }

        upload_post_key = disk_app.get("upload_post_api_key", "")
        up_is_cfg = bool(upload_post_key and str(upload_post_key).strip())

        raw_platforms = disk_app.get("upload_post_platforms", ["youtube", "tiktok"])
        if isinstance(raw_platforms, str):
            platforms = [p.strip() for p in raw_platforms.split(",") if p.strip()]
        elif isinstance(raw_platforms, list):
            platforms = list(raw_platforms)
        else:
            platforms = ["youtube", "tiktok"]

        upload_post_info = {
            "enabled": bool(disk_app.get("upload_post_enabled", False)),
            "auto_upload": bool(disk_app.get("upload_post_auto_upload", False)),
            "username": str(disk_app.get("upload_post_username", "")),
            "is_configured": up_is_cfg,
            "masked_api_key": mask_api_key(upload_post_key) if up_is_cfg else "",
            "platforms": platforms,
            "youtube_privacy_status": str(disk_app.get("upload_post_youtube_privacy_status", "public")),
            "youtube_made_for_kids": bool(disk_app.get("upload_post_youtube_made_for_kids", False)),
        }

        return {
            "llm": llm_info,
            "upload_post": upload_post_info,
        }


def update_providers_settings(
    updates: Dict[str, Any],
    db_path: Optional[str] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """Aplica atualizações por LEITURA-MODIFICAÇÃO-GRAVAÇÃO direto no disco.

    Altera SOMENTE as chaves editadas na seção [app] do config.toml, preservando
    todas as demais chaves e seções exatamente como estão no disco, cria backup
    com data/hora (retendo 10 mais recentes) e sincroniza a memória (config.app).
    """
    # 1. Validações preliminares de negócio
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

    cfg_file = getattr(config, "config_file", os.path.join(utils.root_dir(), "config.toml"))

    with config._config_save_lock:
        # 2. LEITURA DIRETA DO DISCO (dentro do lock)
        disk_data = read_raw_toml_from_disk(cfg_file)
        if "app" not in disk_data or not isinstance(disk_data["app"], dict):
            disk_data["app"] = {}
        disk_app = disk_data["app"]

        # Determina provedor alvo com base no disco
        current_provider = str(disk_app.get("llm_provider", DEFAULT_LLM_PROVIDER_ID)).strip().lower()
        target_provider = str(new_provider).strip().lower() if new_provider is not None else current_provider
        target_spec = get_llm_provider(target_provider)

        app_updates: Dict[str, Any] = {}
        updated_fields: List[str] = []

        # 3. MODIFICAÇÃO: Avalia apenas campos editados e compara contra o DISCO
        # Provedor ativo
        if new_provider is not None and target_provider != current_provider:
            app_updates["llm_provider"] = target_provider
            updated_fields.append("llm_provider")

        # Chave LLM
        new_llm_key = updates.get("llm_api_key")
        if new_llm_key is not None:
            key_config_name = target_spec.config_key("api_key") if target_spec else f"{target_provider}_api_key"
            current_llm_key = disk_app.get(key_config_name, "")
            if not is_masked_or_empty(new_llm_key, current_llm_key):
                clean_key = str(new_llm_key).strip()
                if clean_key != current_llm_key:
                    app_updates[key_config_name] = clean_key
                    updated_fields.append("llm_api_key")

        # Modelo LLM
        new_model = updates.get("llm_model_name")
        if new_model is not None:
            model_config_name = target_spec.config_key("model_name") if target_spec else f"{target_provider}_model_name"
            clean_model = str(new_model).strip()
            if clean_model != disk_app.get(model_config_name, ""):
                app_updates[model_config_name] = clean_model
                updated_fields.append("llm_model_name")

        # Base URL LLM
        new_base_url = updates.get("llm_base_url")
        if new_base_url is not None:
            base_url_config_name = target_spec.config_key("base_url") if target_spec else f"{target_provider}_base_url"
            clean_url = str(new_base_url).strip()
            if clean_url != disk_app.get(base_url_config_name, ""):
                app_updates[base_url_config_name] = clean_url
                updated_fields.append("llm_base_url")

        # Upload-Post
        if "upload_post_enabled" in updates and updates["upload_post_enabled"] is not None:
            val = bool(updates["upload_post_enabled"])
            if disk_app.get("upload_post_enabled") != val:
                app_updates["upload_post_enabled"] = val
                updated_fields.append("upload_post_enabled")

        if "upload_post_auto_upload" in updates and updates["upload_post_auto_upload"] is not None:
            val = bool(updates["upload_post_auto_upload"])
            if disk_app.get("upload_post_auto_upload") != val:
                app_updates["upload_post_auto_upload"] = val
                updated_fields.append("upload_post_auto_upload")

        if "upload_post_username" in updates and updates["upload_post_username"] is not None:
            clean_uname = str(updates["upload_post_username"]).strip()
            if disk_app.get("upload_post_username") != clean_uname:
                app_updates["upload_post_username"] = clean_uname
                updated_fields.append("upload_post_username")

        new_up_key = updates.get("upload_post_api_key")
        if new_up_key is not None:
            current_up_key = disk_app.get("upload_post_api_key", "")
            if not is_masked_or_empty(new_up_key, current_up_key):
                clean_up_key = str(new_up_key).strip()
                if clean_up_key != current_up_key:
                    app_updates["upload_post_api_key"] = clean_up_key
                    updated_fields.append("upload_post_api_key")

        if new_platforms is not None:
            clean_platforms = [str(p).strip().lower() for p in new_platforms]
            if disk_app.get("upload_post_platforms") != clean_platforms:
                app_updates["upload_post_platforms"] = clean_platforms
                updated_fields.append("upload_post_platforms")

        if new_privacy is not None:
            clean_priv = str(new_privacy).strip().lower()
            if disk_app.get("upload_post_youtube_privacy_status") != clean_priv:
                app_updates["upload_post_youtube_privacy_status"] = clean_priv
                updated_fields.append("upload_post_youtube_privacy_status")

        if "upload_post_youtube_made_for_kids" in updates and updates["upload_post_youtube_made_for_kids"] is not None:
            val = bool(updates["upload_post_youtube_made_for_kids"])
            if disk_app.get("upload_post_youtube_made_for_kids") != val:
                app_updates["upload_post_youtube_made_for_kids"] = val
                updated_fields.append("upload_post_youtube_made_for_kids")

        # 4. GRAVAÇÃO: Se houve alterações, altera SOMENTE essas chaves no TOML do disco
        if updated_fields and app_updates:
            for k, v in app_updates.items():
                disk_app[k] = v

            # Serializa o TOML completo lido do disco com as mutações pontuais
            serialized_config = toml.dumps(disk_data)

            # Cria backup datado antes da substituição atômica
            create_timestamped_backup(cfg_file, max_backups=DEFAULT_MAX_BACKUPS)

            # Grava atomicamente no disco reaproveitando o helper comum de config
            config._atomic_write_file(cfg_file, serialized_config)

            # Atualiza na memória (config.app) SOMENTE essas mesmas chaves
            for k, v in app_updates.items():
                config.app[k] = v
                if isinstance(config._cfg.get("app"), dict):
                    config._cfg["app"][k] = v

            # 5. Registra evento de auditoria SEM expor segredos
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

        return get_providers_settings_snapshot(cfg_file), updated_fields
