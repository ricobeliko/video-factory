"""
test/services/test_llm_gemini_retry.py
======================================
Validação da política de retry do Gemini para erros temporários (Missão v2/retry-gemini):
1. Constantes canônicas GEMINI_RETRY_DELAYS_SECONDS e marcadores transitórios (FONTE ÚNICA 1).
2. Helper _is_gemini_transient_error identifica erros transitórios (503, 429, UNAVAILABLE, etc.)
   e ignora erros não transitórios (400, 403, etc.).
3. Falha transitória 503 na 1ª tentativa e sucesso na 2ª (sleep chamado com 5s).
4. Erro 400 não transitório não faz retry e falha imediatamente na 1ª tentativa.
5. Falha transitória 503 em todas as tentativas esgota retries após 4 chamadas (sleeps 5, 15, 45).
"""

import types as py_types
from unittest.mock import patch, call
import pytest

from app.config import config
from app.services import llm


@pytest.fixture(autouse=True)
def restore_config():
    """Restaura o estado original de config.app após cada teste."""
    orig_app = dict(config.app) if isinstance(config.app, dict) else {}
    yield
    config.app.clear()
    config.app.update(orig_app)


def test_gemini_retry_policy_constants_and_helper():
    """FONTE ÚNICA 1: Constantes e detecção de erros transitórios."""
    assert llm.GEMINI_RETRY_DELAYS_SECONDS == (5, 15, 45)
    for marker in ("503", "unavailable", "429", "resource_exhausted", "high demand", "overloaded"):
        assert marker in llm.GEMINI_TRANSIENT_ERROR_MARKERS

    # Casos transitórios
    assert llm._is_gemini_transient_error(
        Exception("503 UNAVAILABLE: This model is currently experiencing high demand")
    )
    assert llm._is_gemini_transient_error(
        Exception("Rate limit reached: 429 RESOURCE_EXHAUSTED")
    )
    assert llm._is_gemini_transient_error(
        Exception("The server is temporarily overloaded. Please try again.")
    )

    class CustomErrorWithAttrs(Exception):
        pass

    err_code = CustomErrorWithAttrs("Service error")
    err_code.code = 503
    assert llm._is_gemini_transient_error(err_code)

    err_status = CustomErrorWithAttrs("Failure")
    err_status.status = "UNAVAILABLE"
    assert llm._is_gemini_transient_error(err_status)

    # Casos não transitórios
    err_400 = CustomErrorWithAttrs("400 Bad Request: Invalid argument")
    err_400.code = 400
    assert not llm._is_gemini_transient_error(err_400)
    assert not llm._is_gemini_transient_error(ValueError("Invalid API key"))
    assert not llm._is_gemini_transient_error(Exception("403 PERMISSION_DENIED"))


def test_gemini_retry_transient_503_succeeds_on_second_attempt():
    """Item a: falha com 503 na 1ª e passa na 2ª (sleep chamado com 5s)."""
    config.app.update({
        "llm_provider": "gemini",
        "gemini_api_key": "fake-key-retry",
        "gemini_model_name": "gemini-2.5-flash",
        "gemini_base_url": "",
    })

    call_count = 0

    class FakeModels:
        def generate_content(self, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("503 UNAVAILABLE: This model is currently experiencing high demand")
            return py_types.SimpleNamespace(text="gemini recovered response")

    class FakeClient:
        def __init__(self, **kwargs):
            self.models = FakeModels()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("google.genai.Client", FakeClient), patch("app.services.llm.time.sleep") as mock_sleep:
        result = llm._generate_response("Prompt teste retry")

    assert result == "gemini recovered response"
    assert call_count == 2
    mock_sleep.assert_called_once_with(5)


def test_gemini_non_transient_400_no_retry():
    """Item b: erro 400 (não transitório) não faz retry, falha na 1ª."""
    config.app.update({
        "llm_provider": "gemini",
        "gemini_api_key": "fake-key-retry",
        "gemini_model_name": "gemini-2.5-flash",
        "gemini_base_url": "",
    })

    call_count = 0

    class FakeModels:
        def generate_content(self, **kwargs):
            nonlocal call_count
            call_count += 1
            err = Exception("400 Bad Request: Invalid argument")
            err.code = 400
            raise err

    class FakeClient:
        def __init__(self, **kwargs):
            self.models = FakeModels()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("google.genai.Client", FakeClient), patch("app.services.llm.time.sleep") as mock_sleep:
        result = llm._generate_response("Prompt teste non-transient")

    assert call_count == 1
    mock_sleep.assert_not_called()
    assert result.startswith("Error: 400 Bad Request")


def test_gemini_transient_503_exhausts_retries_after_4_calls():
    """Item c: falha 4x com 503 esgota retries (sleeps 5, 15, 45)."""
    config.app.update({
        "llm_provider": "gemini",
        "gemini_api_key": "fake-key-retry",
        "gemini_model_name": "gemini-2.5-flash",
        "gemini_base_url": "",
    })

    call_count = 0

    class FakeModels:
        def generate_content(self, **kwargs):
            nonlocal call_count
            call_count += 1
            raise Exception("503 UNAVAILABLE: This model is currently experiencing high demand")

    class FakeClient:
        def __init__(self, **kwargs):
            self.models = FakeModels()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("google.genai.Client", FakeClient), patch("app.services.llm.time.sleep") as mock_sleep:
        result = llm._generate_response("Prompt teste exhaust retries")

    # 1 inicial + 3 retries = 4 chamadas no total
    assert call_count == 4
    assert mock_sleep.call_count == 3
    mock_sleep.assert_has_calls([call(5), call(15), call(45)])
    assert result.startswith("Error: 503 UNAVAILABLE")
