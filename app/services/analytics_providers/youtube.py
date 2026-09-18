"""
YouTube Analytics Provider Foundation.
V10-A — Suporte à coleta e normalização de métricas do YouTube Data API v3.
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
    STATUS_HEALTHY,
    ERR_AUTH,
    ERR_INVALID_RESPONSE,
    ERR_NOT_FOUND,
    ERR_RATE_LIMIT,
    ERR_TEMPORARY,
    ERR_UNAVAILABLE,
)


class YouTubeAnalyticsProvider(AnalyticsProvider):
    """Provedor oficial de métricas do YouTube via YouTube Data API v3."""

    provider_name: str = "youtube_api"
    platform: str = "youtube"

    def _get_api_key(self) -> Optional[str]:
        """Obtém a chave de API de forma segura sem persistência em banco de dados."""
        key = config.app.get("youtube_api_key") or os.environ.get("YOUTUBE_API_KEY")
        if key and isinstance(key, str) and key.strip():
            return key.strip()
        return None

    def get_status(self, db_path: Optional[str] = None) -> str:
        """Verifica estaticamente se a credencial da API do YouTube está presente."""
        api_key = self._get_api_key()
        if api_key:
            return STATUS_CONFIGURED
        return STATUS_NOT_CONFIGURED

    def fetch_metrics(
        self,
        external_post_id: str,
        dry_run: bool = False,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Consulta as estatísticas do vídeo via YouTube Data API v3."""
        if not external_post_id or not str(external_post_id).strip():
            raise AnalyticsProviderError("external_post_id inválido ou vazio.", code=ERR_NOT_FOUND)

        clean_post_id = str(external_post_id).strip()

        if dry_run:
            logger.info(f"[ANALYTICS][YOUTUBE] Dry run fetch para video_id={clean_post_id}")
            return {
                "kind": "youtube#videoListResponse",
                "dry_run": True,
                "items": [
                    {
                        "id": clean_post_id,
                        "statistics": {
                            "viewCount": "0",
                            "likeCount": "0",
                            "commentCount": "0",
                            "favoriteCount": "0",
                        },
                    }
                ],
            }

        api_key = self._get_api_key()
        if not api_key:
            raise AnalyticsProviderError(
                "YouTube API key não configurada (defina youtube_api_key no config.toml ou YOUTUBE_API_KEY no ambiente).",
                code=ERR_AUTH,
            )

        endpoint = "https://www.googleapis.com/youtube/v3/videos"
        params = {
            "part": "statistics,contentDetails,snippet",
            "id": clean_post_id,
            "key": api_key,
        }

        try:
            resp = requests.get(endpoint, params=params, timeout=15)
        except requests.exceptions.Timeout:
            raise AnalyticsProviderError("Timeout ao conectar com a API do YouTube.", code=ERR_TEMPORARY)
        except requests.exceptions.RequestException as req_err:
            raise AnalyticsProviderError(f"Erro de rede ao conectar com YouTube API: {req_err}", code=ERR_UNAVAILABLE)

        if resp.status_code == 401:
            raise AnalyticsProviderError("Autenticação inválida na YouTube Data API.", code=ERR_AUTH)
        elif resp.status_code == 403:
            err_text = resp.text.lower()
            if "quota" in err_text or "ratelimit" in err_text:
                raise AnalyticsProviderError("Quota diária da YouTube Data API excedida.", code=ERR_RATE_LIMIT)
            raise AnalyticsProviderError("Acesso negado à YouTube Data API (403 Forbidden).", code=ERR_AUTH)
        elif resp.status_code == 404:
            raise AnalyticsProviderError(f"Vídeo '{clean_post_id}' não encontrado no YouTube.", code=ERR_NOT_FOUND)
        elif resp.status_code >= 500:
            raise AnalyticsProviderError(f"Servidor da YouTube API retornou erro {resp.status_code}.", code=ERR_TEMPORARY)
        elif resp.status_code != 200:
            raise AnalyticsProviderError(
                f"YouTube API retornou código inesperado {resp.status_code}: {resp.text[:200]}",
                code=ERR_INVALID_RESPONSE,
            )

        try:
            data = resp.json()
        except Exception as json_err:
            raise AnalyticsProviderError(f"Falha ao decodificar resposta da YouTube API: {json_err}", code=ERR_INVALID_RESPONSE)

        items = data.get("items") or []
        if not items:
            raise AnalyticsProviderError(f"Vídeo '{clean_post_id}' não encontrado na resposta do YouTube.", code=ERR_NOT_FOUND)

        return data

    def normalize_metrics(
        self,
        raw_data: Dict[str, Any],
        external_post_id: Optional[str] = None,
        external_url: Optional[str] = None,
    ) -> NormalizedAnalytics:
        """Normaliza o payload da YouTube Data API para o padrão interno."""
        items = raw_data.get("items") or []
        first_item = items[0] if items else {}
        stats = first_item.get("statistics") or {}

        resolved_id = external_post_id or first_item.get("id")
        resolved_url = external_url
        if not resolved_url and resolved_id:
            resolved_url = f"https://www.youtube.com/watch?v={resolved_id}"

        # Extração segura com conversão inteira
        def _parse_int(val: Any) -> Optional[int]:
            if val is None:
                return None
            try:
                return int(val)
            except (ValueError, TypeError):
                return None

        views = _parse_int(stats.get("viewCount")) or 0
        likes = _parse_int(stats.get("likeCount")) or 0
        comments = _parse_int(stats.get("commentCount")) or 0
        favorites = _parse_int(stats.get("favoriteCount")) or 0

        # Retention / View duration da API pública de vídeos não fornece watch time detalhado
        # (requer YouTube Analytics Reporting API com OAuth). Deixa None para não inventar métrica.
        return NormalizedAnalytics(
            platform=self.platform,
            external_post_id=resolved_id,
            external_url=resolved_url,
            views=views,
            likes=likes,
            comments=comments,
            shares=0,  # YouTube Data API não expõe contagem pública de shares
            favorites=favorites,
            watch_time_seconds=None,
            average_view_duration_seconds=None,
            average_view_percentage=None,
            retention_rate=None,
            engagement_rate=None,  # Será calculado deterministamente pelo pipeline do analytics
            followers_gained=None,
            provider=self.provider_name,
            raw_metadata={"item_id": first_item.get("id"), "dry_run": raw_data.get("dry_run", False)},
        )
