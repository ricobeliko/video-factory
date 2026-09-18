"""
Base interfaces and data structures for Analytics Providers.
V10-A — Automatic Analytics Provider Foundation.
"""
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Provider Health / Status constants
STATUS_CONFIGURED = "CONFIGURED"
STATUS_NOT_CONFIGURED = "NOT_CONFIGURED"
STATUS_HEALTHY = "HEALTHY"
STATUS_DEGRADED = "DEGRADED"
STATUS_UNAVAILABLE = "UNAVAILABLE"
STATUS_UNKNOWN = "UNKNOWN"

# Standard Error Codes
ERR_AUTH = "AUTH_ERROR"
ERR_RATE_LIMIT = "RATE_LIMIT"
ERR_NOT_FOUND = "NOT_FOUND"
ERR_TEMPORARY = "TEMPORARY"
ERR_UNAVAILABLE = "UNAVAILABLE"
ERR_INVALID_RESPONSE = "INVALID_RESPONSE"


class AnalyticsProviderError(Exception):
    """Exceção padronizada para falhas de provedores de analytics."""

    def __init__(self, message: str, code: str = ERR_UNAVAILABLE, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass
class NormalizedAnalytics:
    """Modelo normalizado de métricas de engajamento e retenção."""

    platform: str
    external_post_id: Optional[str] = None
    external_url: Optional[str] = None
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    favorites: int = 0
    watch_time_seconds: Optional[float] = None
    average_view_duration_seconds: Optional[float] = None
    average_view_percentage: Optional[float] = None
    retention_rate: Optional[float] = None  # completion_rate (0.0 - 1.0)
    engagement_rate: Optional[float] = None
    followers_gained: Optional[int] = None  # subscribers_gained
    collected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    provider: str = "unknown"
    raw_metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AnalyticsProvider(ABC):
    """Interface abstrata mínima para provedores de analytics de plataformas."""

    provider_name: str
    platform: str

    @abstractmethod
    def get_status(self, db_path: Optional[str] = None) -> str:
        """Retorna o status operacional estático (sem requisições externas desnecessárias)."""
        pass

    @abstractmethod
    def fetch_metrics(
        self,
        external_post_id: str,
        dry_run: bool = False,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Obtém dados brutos de métricas do provedor para a publicação especificada."""
        pass

    @abstractmethod
    def normalize_metrics(
        self,
        raw_data: Dict[str, Any],
        external_post_id: Optional[str] = None,
        external_url: Optional[str] = None,
    ) -> NormalizedAnalytics:
        """Converte dados brutos da API para o modelo normalizado padronizado."""
        pass
