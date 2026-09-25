"""Roteador unificado de publicação YouTube (Fase V15-E.2).

Responsável por selecionar o provider de publicação YouTube:
- 'upload_post': Provider legado via Upload-Post API (default seguro)
- 'post_for_me': Novo provider direto via Post for Me API v1

Garantias:
- ZERO schema migration: configuração persistida em autopilot_settings (key: 'youtube_publish_provider')
- Default estrito: 'upload_post' (produção não muda automaticamente)
- Contrato normalizado de retorno para ambos os providers
- Fail-closed para providers desconhecidos ou configurações inválidas
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
from loguru import logger

from app.services import post_for_me, upload_post

SETTING_KEY_PROVIDER = "youtube_publish_provider"
PROVIDER_UPLOAD_POST = "upload_post"
PROVIDER_POST_FOR_ME = "post_for_me"

ALLOWED_PROVIDERS = {PROVIDER_UPLOAD_POST, PROVIDER_POST_FOR_ME}
DEFAULT_PROVIDER = PROVIDER_UPLOAD_POST


def get_youtube_publish_provider(db_path: Optional[str] = None) -> str:
    """Retorna o provider configurado em autopilot_settings para publicação no YouTube.
    
    Default: 'upload_post'
    """
    try:
        from app.services import scheduler
        val = scheduler.get_setting(SETTING_KEY_PROVIDER, DEFAULT_PROVIDER, db_path=db_path)
        clean_val = str(val or "").strip().lower()
        if clean_val in ALLOWED_PROVIDERS:
            return clean_val
    except Exception as exc:
        logger.warning(f"[YOUTUBE_PUBLISHER] Falha ao ler {SETTING_KEY_PROVIDER} de autopilot_settings: {exc}")
    return DEFAULT_PROVIDER


def set_youtube_publish_provider(provider: str, db_path: Optional[str] = None) -> None:
    """Define o provider de publicação YouTube em autopilot_settings."""
    clean_val = str(provider or "").strip().lower()
    if clean_val not in ALLOWED_PROVIDERS:
        raise ValueError(
            f"Provider de publicação YouTube inválido: '{provider}'. "
            f"Valores permitidos: {sorted(ALLOWED_PROVIDERS)}"
        )
    from app.services import scheduler
    scheduler.set_setting(SETTING_KEY_PROVIDER, clean_val, db_path=db_path)
    logger.info(f"[YOUTUBE_PUBLISHER] Provider YouTube atualizado para: {clean_val}")


def publish_youtube_video(
    video_path: str,
    title: str,
    caption: str,
    task_id: str,
    channel_id: Optional[str] = None,
    profile_id: Optional[str] = None,
    privacy_status: Optional[str] = None,
    made_for_kids: bool = False,
    tags: Optional[List[str]] = None,
    external_profile_name: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Publica um vídeo no YouTube utilizando o provider atualmente selecionado.
    
    Retorno normalizado:
    {
        "success": bool,
        "provider": str,
        "request_id": Optional[str],
        "external_id": Optional[str],     # YouTube video ID nativo
        "external_url": Optional[str],    # URL pública do vídeo
        "privacy_status": str,
        "error": Optional[str],
        "error_code": Optional[str],
    }
    """
    provider = get_youtube_publish_provider(db_path=db_path)
    logger.info(
        f"[YOUTUBE_PUBLISHER] Publicando vídeo para task {task_id} via provider '{provider}' "
        f"(channel_id={channel_id}, profile_id={profile_id})"
    )

    if provider == PROVIDER_POST_FOR_ME:
        effective_privacy = privacy_status or "public"
        client = post_for_me.post_for_me_client
        return client.publish_video(
            video_path=video_path,
            title=title,
            caption=caption,
            channel_id=channel_id or "channel-default-youtube",
            task_id=task_id,
            privacy_status=effective_privacy,
            made_for_kids=made_for_kids,
            profile_id=profile_id,
        )

    elif provider == PROVIDER_UPLOAD_POST:
        effective_privacy = (
            privacy_status or upload_post.upload_post_service.youtube_privacy_status or "public"
        )
        youtube_extra = {
            "youtube_title": title[:100],
            "youtube_description": caption,
            "tags": tags or [],
            "privacyStatus": effective_privacy,
            "selfDeclaredMadeForKids": made_for_kids,
            "containsSyntheticMedia": True,
        }

        res = upload_post.cross_post_video(
            video_path=video_path,
            title=caption or title,
            platforms=["youtube"],
            youtube_extra=youtube_extra,
            external_profile_name=external_profile_name,
        )

        if not isinstance(res, dict):
            res = {"success": False, "error": "Upload-Post retornou resposta inválida"}

        sub_results = res.get("results", {}) if isinstance(res.get("results"), dict) else {}
        yt_info = sub_results.get("youtube", {}) if isinstance(sub_results.get("youtube"), dict) else {}

        platform_post_id = (
            yt_info.get("post_id")
            or yt_info.get("id")
            or yt_info.get("video_id")
            or yt_info.get("itemId")
        )
        platform_post_url = (
            yt_info.get("url")
            or yt_info.get("link")
            or yt_info.get("video_url")
            or yt_info.get("share_url")
        )

        success = bool(res.get("success", False))
        error_msg = res.get("error") or res.get("message") if not success else None

        return {
            "success": success,
            "provider": PROVIDER_UPLOAD_POST,
            "request_id": res.get("request_id"),
            "external_id": str(platform_post_id) if platform_post_id else None,
            "external_url": str(platform_post_url) if platform_post_url else None,
            "privacy_status": effective_privacy,
            "error": error_msg,
            "error_code": None if success else "UPLOAD_POST_ERROR",
        }

    else:
        err = f"Provider de publicação YouTube desconhecido: '{provider}'"
        logger.error(f"[YOUTUBE_PUBLISHER] {err}")
        return {
            "success": False,
            "provider": provider,
            "request_id": None,
            "external_id": None,
            "external_url": None,
            "privacy_status": privacy_status or "unknown",
            "error": err,
            "error_code": "UNKNOWN_PROVIDER",
        }
