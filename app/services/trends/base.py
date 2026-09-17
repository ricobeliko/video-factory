from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Status possíveis do Trend Radar
STATUS_NEW = "NEW"
STATUS_REVIEW = "REVIEW"
STATUS_APPROVED = "APPROVED"
STATUS_REJECTED = "REJECTED"
STATUS_USED = "USED"
VALID_STATUSES = {STATUS_NEW, STATUS_REVIEW, STATUS_APPROVED, STATUS_REJECTED, STATUS_USED}

# Níveis de confiança da fonte
CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"

# Verificação
VERIFICATION_SINGLE = "single_source"
VERIFICATION_MULTI = "multi_source"


@dataclass
class TrendSignal:
    """Representa um sinal bruto de tendência coletado por um provider."""
    title: str
    source: str
    source_key: str = ""
    source_url: str = ""
    description: str = ""
    published_at: str = ""
    region: str = ""
    language: str = ""
    raw_score: float = 50.0
    source_confidence: str = "MEDIUM"  # HIGH, MEDIUM, LOW
    normalized_topic: str = ""
    trend_score: float = 0.0
    novelty_score: float = 0.0
    relevance_score: float = 0.0
    opportunity_score: float = 0.0
    source_count: int = 1
    verification: str = VERIFICATION_SINGLE
    status: str = STATUS_NEW
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseTrendProvider(ABC):
    """Interface base para providers de tendências do Trend Radar."""

    name: str = "base"

    @abstractmethod
    def fetch_trends(
        self,
        niche: str = "",
        language: str = "pt-BR",
        region: str = "BR",
        limit: int = 20,
    ) -> List[TrendSignal]:
        """Coleta sinais de tendência de forma segura e resiliente."""
        raise NotImplementedError
