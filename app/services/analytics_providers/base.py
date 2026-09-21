"""
Base interfaces and data structures for Analytics Providers.
V10-A — Automatic Analytics Provider Foundation.
"""
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import re
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
# V12-F.1C: bloqueio fail-closed por privacidade não confirmada como PUBLIC
# (nunca dispara a requisição externa real quando este código é usado).
ERR_PRIVACY_BLOCKED = "PRIVACY_BLOCKED"

# V12-F.1A: padrões usados para nunca expor API key/token/query sensível em
# mensagens de erro (exceções de rede podem ecoar a URL completa da requisição).
_SENSITIVE_QUERY_PATTERN = re.compile(
    r"(key|token|access_token|api_key|secret)=([^&\s'\"]+)", re.IGNORECASE
)
_SENSITIVE_BEARER_PATTERN = re.compile(r"Bearer\s+[A-Za-z0-9\-_\.]+", re.IGNORECASE)


def sanitize_error_text(text: Any) -> str:
    """Remove valores sensíveis (query params de credenciais, tokens Bearer) de um texto de erro."""
    clean_text = str(text) if text is not None else ""
    clean_text = _SENSITIVE_QUERY_PATTERN.sub(lambda m: f"{m.group(1)}=***REDACTED***", clean_text)
    clean_text = _SENSITIVE_BEARER_PATTERN.sub("Bearer ***REDACTED***", clean_text)
    return clean_text


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

    def get_missing_fields(self) -> list:
        """Retorna lista de nomes dos campos faltantes na configuração."""
        return []

    def validate_configuration(self, db_path: Optional[str] = None) -> Dict[str, Any]:
        """Retorna validação estruturada da configuração sem expor segredos."""
        status = self.get_status(db_path=db_path)
        is_configured = status == STATUS_CONFIGURED
        missing = self.get_missing_fields() if not is_configured else []
        return {
            "provider": self.provider_name,
            "platform": self.platform,
            "configured": is_configured,
            "missing_fields": missing,
            "status": status,
        }

    def validate_external_id(self, external_post_id: str) -> str:
        """Valida que o ID externo tem formato plausível antes de requisições externas."""
        if not external_post_id or not str(external_post_id).strip():
            raise AnalyticsProviderError("external_post_id não informado ou vazio.", code=ERR_NOT_FOUND)
        clean_id = str(external_post_id).strip()
        if any(c in clean_id for c in (" ", "\t", "\n", "/", "?", "&", "=")):
            raise AnalyticsProviderError(
                f"external_post_id inválido ('{clean_id}'). Deve ser o ID bruto da publicação e não uma URL.",
                code=ERR_NOT_FOUND,
            )
        return clean_id
