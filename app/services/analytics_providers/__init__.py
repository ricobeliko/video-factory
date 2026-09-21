"""
Analytics Providers Package.
V10-A — Automatic Analytics Provider Foundation.
"""
from typing import Any, Dict, Optional

from app.services.analytics_providers.base import (
    AnalyticsProvider,
    AnalyticsProviderError,
    NormalizedAnalytics,
    STATUS_CONFIGURED,
    STATUS_NOT_CONFIGURED,
    STATUS_HEALTHY,
    STATUS_DEGRADED,
    STATUS_UNAVAILABLE,
    STATUS_UNKNOWN,
    ERR_AUTH,
    ERR_INVALID_RESPONSE,
    ERR_NOT_FOUND,
    ERR_RATE_LIMIT,
    ERR_TEMPORARY,
    ERR_UNAVAILABLE,
    ERR_PRIVACY_BLOCKED,
    sanitize_error_text,
)
from app.services.analytics_providers.youtube import YouTubeAnalyticsProvider
from app.services.analytics_providers.tiktok import TikTokAnalyticsProvider

# Registry interno de singletons de providers
_PROVIDERS_REGISTRY: Dict[str, AnalyticsProvider] = {
    "youtube": YouTubeAnalyticsProvider(),
    "tiktok": TikTokAnalyticsProvider(),
}


def get_provider(platform: str) -> AnalyticsProvider:
    """Retorna o provedor de analytics registrado para a plataforma especificada."""
    clean_platform = (platform or "").strip().lower()
    if clean_platform not in _PROVIDERS_REGISTRY:
        raise ValueError(
            f"Provider de analytics não suportado para plataforma '{platform}'. "
            f"Plataformas suportadas: {sorted(list(_PROVIDERS_REGISTRY.keys()))}"
        )
    return _PROVIDERS_REGISTRY[clean_platform]


def register_provider(platform: str, provider: AnalyticsProvider) -> None:
    """Permite registrar ou substituir provedor (útil para testes unitários com mocks)."""
    clean_platform = (platform or "").strip().lower()
    _PROVIDERS_REGISTRY[clean_platform] = provider


def get_all_providers_status(db_path: Optional[str] = None) -> Dict[str, str]:
    """Retorna o status de todos os provedores de analytics registrados."""
    return {
        plat: prov.get_status(db_path=db_path)
        for plat, prov in _PROVIDERS_REGISTRY.items()
    }


def validate_provider_configuration(platform: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Retorna validação estruturada do provedor sem expor segredos ou tokens."""
    provider = get_provider(platform)
    return provider.validate_configuration(db_path=db_path)


__all__ = [
    "AnalyticsProvider",
    "AnalyticsProviderError",
    "NormalizedAnalytics",
    "YouTubeAnalyticsProvider",
    "TikTokAnalyticsProvider",
    "get_provider",
    "register_provider",
    "get_all_providers_status",
    "validate_provider_configuration",
    "STATUS_CONFIGURED",
    "STATUS_NOT_CONFIGURED",
    "STATUS_HEALTHY",
    "STATUS_DEGRADED",
    "STATUS_UNAVAILABLE",
    "STATUS_UNKNOWN",
    "ERR_AUTH",
    "ERR_INVALID_RESPONSE",
    "ERR_NOT_FOUND",
    "ERR_RATE_LIMIT",
    "ERR_TEMPORARY",
    "ERR_UNAVAILABLE",
    "ERR_PRIVACY_BLOCKED",
    "sanitize_error_text",
]
