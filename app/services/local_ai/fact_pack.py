"""
app/services/local_ai/fact_pack.py
===================================
Estruturas de dados canônicas para Fatos e Pacotes Factuais (Fase V1.4B).

O FactPack garante que a geração de conteúdo seja estritamente ancorada
(grounded) em fatos reais conhecidos, prevenindo alucinações e adições não verificadas.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class Fact(BaseModel):
    """Representa um fato atômico verificado."""

    id: str = Field(..., description="Identificador único do fato, ex: F1, F2")
    text: str = Field(..., min_length=3, description="Enunciado factual atômico")
    source: str = Field(default="", description="Fonte ou documento de origem")
    source_type: Optional[str] = Field(default=None, description="Tipo da fonte, ex: historical_record, paper, news")
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Nível de confiança (0.0 a 1.0)")


# Razão conservadora de expansão narrativa padrão (Fase V1.4D.2):
# Cada palavra de fato atômico verificado suporta com segurança até 2.0 palavras no roteiro final.
DEFAULT_SAFE_EXPANSION_RATIO: float = 2.0


class FactSufficiencyResult(BaseModel):
    """Resultado estruturado da validação pré-geração de densidade factual (Fase V1.4D.2)."""

    sufficient: bool = Field(..., description="Indica se os fatos suportam com segurança a duração solicitada")
    target_words: int = Field(..., description="Meta de palavras calculada para a duração solicitada")
    fact_count: int = Field(..., description="Quantidade de fatos atômicos presentes no FactPack")
    fact_word_count: int = Field(..., description="Quantidade de palavras contidas no texto dos fatos")
    safe_target_words: int = Field(..., description="Capacidade máxima segura de palavras expandíveis")
    recommended_duration_seconds: float = Field(..., description="Duração máxima recomendada para o volume de fatos")
    reason: str = Field(..., description="Justificativa determinística do parecer de suficiência")
    expansion_ratio: float = Field(default=DEFAULT_SAFE_EXPANSION_RATIO, description="Razão de expansão utilizada")


class FactPack(BaseModel):
    """Conjunto delimitado de fatos autoritativos para ancorar a criação de um vídeo."""

    topic: str = Field(..., min_length=2, description="Tema ou assunto do vídeo")
    facts: List[Fact] = Field(..., min_length=1, description="Lista de fatos verificados")
    source_urls: List[str] = Field(default_factory=list, description="URLs de referência externa consultadas")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Timestamp ISO da criação do FactPack",
    )
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadados contextuais adicionais")

    @field_validator("facts")
    @classmethod
    def validate_unique_fact_ids(cls, v: List[Fact]) -> List[Fact]:
        seen = set()
        for f in v:
            fid = f.id.strip().upper()
            if fid in seen:
                raise ValueError(f"ID de fato duplicado detectado no FactPack: '{f.id}'")
            seen.add(fid)
        return v

    def get_fact(self, fact_id: str) -> Optional[Fact]:
        """Recupera um fato pelo seu ID."""
        target = fact_id.strip().upper()
        for f in self.facts:
            if f.id.strip().upper() == target:
                return f
        return None

    def get_fact_ids(self) -> List[str]:
        """Retorna a lista de IDs de fatos disponíveis."""
        return [f.id for f in self.facts]

    def format_for_prompt(self) -> str:
        """Formata o FactPack de forma estruturada para injeção em prompts de sistema."""
        lines = [f"FACT PACK: TEMA '{self.topic}'"]
        for f in self.facts:
            source_info = f" (Fonte: {f.source})" if f.source else ""
            lines.append(f"[{f.id.upper()}] {f.text}{source_info}")
        return "\n".join(lines)

    def total_word_count(self) -> int:
        """Calcula o total de palavras faladas somadas no texto de todos os fatos."""
        clean = " ".join(f.text for f in self.facts)
        return len([w for w in clean.split() if w.strip()])

    def evaluate_sufficiency(
        self,
        requested_duration_seconds: float,
        words_per_second: float = 2.4,
        expansion_ratio: float = DEFAULT_SAFE_EXPANSION_RATIO,
    ) -> FactSufficiencyResult:
        """Avalia se o FactPack possui densidade factual suficiente para a duração solicitada."""
        return evaluate_fact_sufficiency(
            self,
            requested_duration_seconds=requested_duration_seconds,
            words_per_second=words_per_second,
            expansion_ratio=expansion_ratio,
        )

    def validate_integrity(self) -> bool:
        """Verifica se o pacote é válido e tem conteúdo utilizável."""
        if not self.topic or not self.topic.strip():
            return False
        if not self.facts:
            return False
        ids = [f.id.strip().upper() for f in self.facts]
        if len(ids) != len(set(ids)):
            return False
        return True


def evaluate_fact_sufficiency(
    fact_pack: FactPack,
    requested_duration_seconds: float,
    words_per_second: float = 2.4,
    expansion_ratio: float = DEFAULT_SAFE_EXPANSION_RATIO,
) -> FactSufficiencyResult:
    """
    Avalia deterministicamente se o FactPack possui conteúdo factual suficiente
    para preencher a duração do vídeo sem induzir o modelo a alucinar informações externas.
    """
    fact_count = len(fact_pack.facts)
    fact_words = fact_pack.total_word_count()
    target_words = int(round(requested_duration_seconds * words_per_second))
    safe_target = int(round(fact_words * expansion_ratio))
    rec_duration = round(safe_target / words_per_second, 1) if words_per_second > 0 else 0.0

    if target_words > safe_target:
        sufficient = False
        reason = (
            f"FactPack insuficiente para {requested_duration_seconds:.1f}s: contém {fact_words} palavras em {fact_count} fatos, "
            f"permitindo com segurança até {safe_target} palavras narrativas (~{rec_duration:.1f}s a {expansion_ratio:.1f}x). "
            f"A duração solicitada demanda {target_words} palavras."
        )
    else:
        sufficient = True
        reason = (
            f"FactPack suficiente: {fact_words} palavras em {fact_count} fatos suportam até {safe_target} palavras "
            f"(meta solicitada: {target_words} palavras para {requested_duration_seconds:.1f}s)."
        )

    return FactSufficiencyResult(
        sufficient=sufficient,
        target_words=target_words,
        fact_count=fact_count,
        fact_word_count=fact_words,
        safe_target_words=safe_target,
        recommended_duration_seconds=rec_duration,
        reason=reason,
        expansion_ratio=expansion_ratio,
    )
