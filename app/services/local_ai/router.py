"""
app/services/local_ai/router.py
================================
Roteador Mínimo de IA Local (Fase V1.4B).

Diferencia papéis de execução:
- FAST: tarefas leves (títulos, tags, metadata, classificação, pequenas transformações)
- QUALITY: tarefas críticas (roteiro, hooks estruturais, críticas do FactGuard, planejamento de cenas)
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from loguru import logger

from app.config import config
from app.services.local_ai.provider import LocalAIProvider, LocalAIResponse


class LocalAIRole(str, Enum):
    FAST = "FAST"
    QUALITY = "QUALITY"


class LocalAIRouter:
    """Roteador enxuto que direciona chamadas aos modelos locais adequados à complexidade da tarefa."""

    def __init__(
        self,
        provider: LocalAIProvider,
        fast_model: Optional[str] = None,
        quality_model: Optional[str] = None,
    ):
        self.provider = provider

        # Resolução do modelo FAST (ex: Qwen3-4B ou modelo leve)
        self.fast_model = (
            fast_model
            or config.app.get("local_ai_fast_model")
            or os.getenv("LOCAL_AI_FAST_MODEL")
            or self.provider.config.model
        )

        # Resolução do modelo QUALITY (ex: Qwen3-8B ou modelo mais robusto)
        self.quality_model = (
            quality_model
            or config.app.get("local_ai_quality_model")
            or os.getenv("LOCAL_AI_QUALITY_MODEL")
            or self.provider.config.model
        )

    def get_model_for_role(self, role: Union[LocalAIRole, str]) -> str:
        """Determina o modelo apropriado para o papel solicitado."""
        normalized_role = str(role).upper()
        if "FAST" in normalized_role:
            return self.fast_model
        return self.quality_model

    def dispatch_chat(
        self,
        role: Union[LocalAIRole, str],
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 512,
        timeout: Optional[float] = None,
    ) -> LocalAIResponse:
        """Despacha uma chamada de chat completion usando o modelo configurado para o papel."""
        target_model = self.get_model_for_role(role)
        logger.debug(f"[LocalAIRouter] Despachando tarefa '{role}' para modelo '{target_model}'")
        return self.provider.chat_completion(
            messages=messages,
            model=target_model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
