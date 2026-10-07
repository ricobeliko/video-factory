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
