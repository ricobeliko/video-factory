"""
app/services/local_ai/__init__.py
==================================
Módulo de IA Local (Fase V1.4B) — Local Brain, FactPack, FactGuard e Router.
"""

from app.services.local_ai.provider import (
    LocalAIConfig,
    LocalAIError,
    LocalAIProvider,
    LocalAIResponse,
    LocalAIResponseFormatError,
    LocalAIServerUnavailableError,
    LocalAITimeoutError,
)
from app.services.local_ai.fact_pack import Fact, FactPack
from app.services.local_ai.router import LocalAIRole, LocalAIRouter
from app.services.local_ai.fact_guard import (
    FactGuard,
    FactGuardResult,
    GroundedContent,
    GroundedScene,
    generate_grounded_content_with_guard,
)

__all__ = [
    "LocalAIConfig",
    "LocalAIError",
    "LocalAIServerUnavailableError",
    "LocalAITimeoutError",
    "LocalAIResponseFormatError",
    "LocalAIResponse",
    "LocalAIProvider",
    "Fact",
    "FactPack",
    "LocalAIRole",
    "LocalAIRouter",
    "FactGuard",
    "FactGuardResult",
    "GroundedContent",
    "GroundedScene",
    "generate_grounded_content_with_guard",
]
