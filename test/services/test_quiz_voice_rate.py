"""
Testes unitários e direcionados para resolução de velocidade de voz em quizzes.

Valida a decisão arquitetural:
Ritmo de fala é calibrado pelo formato de vídeo (+20% no paper quiz, +12% no quiz de dilemas)
para meta de 60-65s. A velocidade global/numérica do config (ex.: 0.8) é ignorada para os
quizzes, retornando sempre o default do formato. Apenas strings com '%' explícito são mantidas.
"""

import math
import pytest
from app.services import voice


class TestQuizVoiceRateResolution:
    """Testa a função resolve_quiz_voice_rate sob o princípio de formato específico."""

    def test_numeric_rates_ignored_in_favor_of_format_default(self):
        # Velocidades globais numéricas (0.8, 1.0, 1.2) NÃO mandam no ritmo do quiz
        # Devem retornar o default calibrado de cada formato (+20% paper / +12% dilema)
        for default in ("+20%", "+12%"):
            assert voice.resolve_quiz_voice_rate(0.8, default_rate=default) == default
            assert voice.resolve_quiz_voice_rate(1.0, default_rate=default) == default
            assert voice.resolve_quiz_voice_rate(1.2, default_rate=default) == default
            assert voice.resolve_quiz_voice_rate(1, default_rate=default) == default

    def test_none_or_missing_returns_format_default(self):
        for default in ("+20%", "+12%"):
            assert voice.resolve_quiz_voice_rate(None, default_rate=default) == default

    def test_zero_and_non_finite_fall_back_to_format_default(self):
        for default in ("+20%", "+12%"):
            assert voice.resolve_quiz_voice_rate(0, default_rate=default) == default
            assert voice.resolve_quiz_voice_rate(0.0, default_rate=default) == default
            assert voice.resolve_quiz_voice_rate(-0.5, default_rate=default) == default
            assert voice.resolve_quiz_voice_rate(float("nan"), default_rate=default) == default
            assert voice.resolve_quiz_voice_rate(float("inf"), default_rate=default) == default
            assert voice.resolve_quiz_voice_rate(float("-inf"), default_rate=default) == default

    def test_invalid_types_and_unformatted_strings_fall_back_to_format_default(self):
        for default in ("+20%", "+12%"):
            assert voice.resolve_quiz_voice_rate("invalid", default_rate=default) == default
            assert voice.resolve_quiz_voice_rate("", default_rate=default) == default
            assert voice.resolve_quiz_voice_rate("0.8", default_rate=default) == default
            assert voice.resolve_quiz_voice_rate([], default_rate=default) == default
            assert voice.resolve_quiz_voice_rate({}, default_rate=default) == default

    def test_string_with_percent_preserved_for_both_defaults(self):
        # Strings já com '%' são a única exceção (override explícito do formato)
        for default in ("+20%", "+12%"):
            assert voice.resolve_quiz_voice_rate("+15%", default_rate=default) == "+15%"
            assert voice.resolve_quiz_voice_rate("-10%", default_rate=default) == "-10%"
            assert voice.resolve_quiz_voice_rate("+0%", default_rate=default) == "+0%"
            assert voice.resolve_quiz_voice_rate("+25%", default_rate=default) == "+25%"
