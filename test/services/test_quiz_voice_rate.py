"""
Testes unitários e direcionados para resolução de velocidade de voz em quizzes.

Valida a correção do bug de produção onde voice_rate < 1 (ex.: 0.8) gerava
a string inválida '+-20%' aceita nem pelo edge-tts nem pela renderização.
"""

import math
import pytest
from app.services import voice


class TestQuizVoiceRateResolution:
    """Testa a função resolve_quiz_voice_rate sob todas as condições especificadas."""

    def test_voice_rate_less_than_one_converts_correctly(self):
        # Bug original de produção: 0.8 gerava "+-20%" em vez de "-20%"
        assert voice.resolve_quiz_voice_rate(0.8, default_rate="+20%") == "-20%"
        assert voice.resolve_quiz_voice_rate(0.8, default_rate="+12%") == "-20%"
        assert voice.resolve_quiz_voice_rate(0.9, default_rate="+20%") == "-10%"
        assert voice.resolve_quiz_voice_rate(0.85, default_rate="+12%") == "-15%"

    def test_voice_rate_one_preserves_quiz_defaults(self):
        # Taxa 1.0 (neutra/padrão global) deve preservar o ritmo acelerado de cada quiz
        assert voice.resolve_quiz_voice_rate(1.0, default_rate="+20%") == "+20%"
        assert voice.resolve_quiz_voice_rate(1.0, default_rate="+12%") == "+12%"
        assert voice.resolve_quiz_voice_rate(1, default_rate="+20%") == "+20%"
        assert voice.resolve_quiz_voice_rate(1, default_rate="+12%") == "+12%"

    def test_voice_rate_greater_than_one_converts_with_positive_sign(self):
        # 1.2 -> +20%
        assert voice.resolve_quiz_voice_rate(1.2, default_rate="+20%") == "+20%"
        assert voice.resolve_quiz_voice_rate(1.2, default_rate="+12%") == "+20%"
        assert voice.resolve_quiz_voice_rate(1.15, default_rate="+12%") == "+15%"

    def test_none_or_missing_falls_back_to_default(self):
        # Valores None ou ausentes caem no padrão do quiz
        assert voice.resolve_quiz_voice_rate(None, default_rate="+20%") == "+20%"
        assert voice.resolve_quiz_voice_rate(None, default_rate="+12%") == "+12%"

    def test_string_with_percent_is_preserved(self):
        # Strings já com '%' são preservadas sem alteração
        assert voice.resolve_quiz_voice_rate("+15%", default_rate="+20%") == "+15%"
        assert voice.resolve_quiz_voice_rate("+15%", default_rate="+12%") == "+15%"
        assert voice.resolve_quiz_voice_rate("-10%", default_rate="+20%") == "-10%"
        assert voice.resolve_quiz_voice_rate("+0%", default_rate="+12%") == "+0%"

    def test_zero_or_negative_rate_falls_back_to_default(self):
        # Fallback defensivo para valores <= 0
        assert voice.resolve_quiz_voice_rate(0, default_rate="+20%") == "+20%"
        assert voice.resolve_quiz_voice_rate(0.0, default_rate="+12%") == "+12%"
        assert voice.resolve_quiz_voice_rate(-0.5, default_rate="+20%") == "+20%"
        assert voice.resolve_quiz_voice_rate(-1.0, default_rate="+12%") == "+12%"

    def test_non_finite_values_fall_back_to_default(self):
        # Fallback defensivo para NaN e Inf
        assert voice.resolve_quiz_voice_rate(float("nan"), default_rate="+20%") == "+20%"
        assert voice.resolve_quiz_voice_rate(float("nan"), default_rate="+12%") == "+12%"
        assert voice.resolve_quiz_voice_rate(float("inf"), default_rate="+20%") == "+20%"
        assert voice.resolve_quiz_voice_rate(float("-inf"), default_rate="+12%") == "+12%"

    def test_invalid_string_or_types_fall_back_to_default(self):
        assert voice.resolve_quiz_voice_rate("invalid", default_rate="+20%") == "+20%"
        assert voice.resolve_quiz_voice_rate("", default_rate="+12%") == "+12%"
        assert voice.resolve_quiz_voice_rate([], default_rate="+20%") == "+20%"
