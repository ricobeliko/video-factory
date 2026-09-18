"""
TikTok Analytics Provider Foundation.
V10-A — Suporte à coleta e normalização de métricas do TikTok for Developers API.
"""
import os
from typing import Any, Dict, Optional
import requests
from loguru import logger

from app.config import config
from app.services.analytics_providers.base import (
    AnalyticsProvider,
    AnalyticsProviderError,
    NormalizedAnalytics,
    STATUS_CONFIGURED,
    STATUS_NOT_CONFIGURED,
    ERR_AUTH,
    ERR_INVALID_RESPONSE,
    ERR_NOT_FOUND,
    ERR_RATE_LIMIT,
    ERR_TEMPORARY,
    ERR_UNAVAILABLE,
)


class TikTokAnalyticsProvider(AnalyticsProvider):
    """Provedor oficial de métricas do TikTok via TikTok for Developers API v2."""

    provider_name: str = "tiktok_api"
    platform: str = "tiktok"

    def _get_access_token(self) -> Optional[str]:
        """Obtém o token de acesso de forma segura sem persistência em SQLite."""
        token = config.app.get("tiktok_access_token") or os.environ.get("TIKTOK_ACCESS_TOKEN")
        if token and isinstance(token, str) and token.strip():
            return token.strip()
        return None

    def get_status(self, db_path: Optional[str] = None) -> str:
        """Verifica estaticamente se o access token do TikTok está presente."""
        token = self._get_access_token()
        if token:
            return STATUS_CONFIGURED
        return STATUS_NOT_CONFIGURED

    def fetch_metrics(
        self,
        external_post_id: str,
        dry_run: bool = False,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Consulta as métricas do vídeo via TikTok Video Query API."""
        if not external_post_id or not str(external_post_id).strip():
            raise AnalyticsProviderError("external_post_id inválido ou vazio.", code=ERR_NOT_FOUND)

        clean_post_id = str(external_post_id).strip()

        if dry_run:
            logger.info(f"[ANALYTICS][TIKTOK] Dry run fetch para video_id={clean_post_id}")
            return {
                "dry_run": True,
                "data": {
                    "videos": [
                        {
                            "id": clean_post_id,
                            "view_count": 0,
                            "like_count": 0,
                            "comment_count": 0,
                            "share_count": 0,
                        }
                    ]
                },
            }

        token = self._get_access_token()
        if not token:
            raise AnalyticsProviderError(
                "TikTok access token não configurado (defina tiktok_access_token no config.toml ou TIKTOK_ACCESS_TOKEN no ambiente).",
                code=ERR_AUTH,
            )

        endpoint = "https://open.tiktokapis.com/v2/video/query/"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        params = {
            "fields": "id,title,view_count,like_count,comment_count,share_count"
        }
        payload = {
            "filters": {
                "video_ids": [clean_post_id]
            }
        }

        try:
            resp = requests.post(endpoint, params=params, json=payload, headers=headers, timeout=15)
        except requests.exceptions.Timeout:
            raise AnalyticsProviderError("Timeout ao conectar com a API do TikTok.", code=ERR_TEMPORARY)
        except requests.exceptions.RequestException as req_err:
            raise AnalyticsProviderError(f"Erro de rede ao conectar com TikTok API: {req_err}", code=ERR_UNAVAILABLE)

        if resp.status_code in (401, 403):
            raise AnalyticsProviderError("Token inválido ou sem permissão na TikTok API.", code=ERR_AUTH)
        elif resp.status_code == 429:
            raise AnalyticsProviderError("Rate limit excedido na TikTok API.", code=ERR_RATE_LIMIT)
        elif resp.status_code == 404:
            raise AnalyticsProviderError(f"Vídeo '{clean_post_id}' não encontrado no TikTok.", code=ERR_NOT_FOUND)
        elif resp.status_code >= 500:
            raise AnalyticsProviderError(f"Servidor da TikTok API retornou erro {resp.status_code}.", code=ERR_TEMPORARY)
        elif resp.status_code != 200:
            raise AnalyticsProviderError(
                f"TikTok API retornou status inesperado {resp.status_code}: {resp.text[:200]}",
                code=ERR_INVALID_RESPONSE,
            )

        try:
            data = resp.json()
        except Exception as json_err:
            raise AnalyticsProviderError(f"Falha ao decodificar resposta da TikTok API: {json_err}", code=ERR_INVALID_RESPONSE)

        # TikTok API costuma retornar {"error": {"code": ...}}
        error_info = data.get("error") or {}
        if error_info.get("code") and error_info.get("code") != "ok":
            msg = error_info.get("message") or f"Erro código {error_info.get('code')}"
            code_str = str(error_info.get("code")).lower()
            if "scope" in code_str or "auth" in code_str or "token" in code_str:
                raise AnalyticsProviderError(f"Erro de autenticação TikTok: {msg}", code=ERR_AUTH)
            elif "rate" in code_str or "limit" in code_str:
                raise AnalyticsProviderError(f"Rate limit TikTok: {msg}", code=ERR_RATE_LIMIT)
            raise AnalyticsProviderError(f"Falha na API do TikTok: {msg}", code=ERR_INVALID_RESPONSE)

        videos = (data.get("data") or {}).get("videos") or []
        if not videos:
            raise AnalyticsProviderError(f"Vídeo '{clean_post_id}' não encontrado na lista da TikTok API.", code=ERR_NOT_FOUND)

        return data

    def normalize_metrics(
        self,
        raw_data: Dict[str, Any],
        external_post_id: Optional[str] = None,
        external_url: Optional[str] = None,
    ) -> NormalizedAnalytics:
        """Normaliza o payload da TikTok API para o padrão interno."""
        videos = (raw_data.get("data") or {}).get("videos") or []
        first_video = videos[0] if videos else {}

        resolved_id = external_post_id or first_video.get("id")
        resolved_url = external_url

        def _parse_int(val: Any) -> Optional[int]:
            if val is None:
                return None
            try:
                return int(val)
            except (ValueError, TypeError):
                return None

        views = _parse_int(first_video.get("view_count")) or 0
        likes = _parse_int(first_video.get("like_count")) or 0
        comments = _parse_int(first_video.get("comment_count")) or 0
        shares = _parse_int(first_video.get("share_count")) or 0

        return NormalizedAnalytics(
            platform=self.platform,
            external_post_id=resolved_id,
            external_url=resolved_url,
            views=views,
            likes=likes,
            comments=comments,
            shares=shares,
            favorites=0,
            watch_time_seconds=None,
            average_view_duration_seconds=None,
            average_view_percentage=None,
            retention_rate=None,
            engagement_rate=None,
            followers_gained=None,
            provider=self.provider_name,
            raw_metadata={"video_id": first_video.get("id"), "dry_run": raw_data.get("dry_run", False)},
        )
