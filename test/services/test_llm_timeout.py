"""
test/services/test_llm_timeout.py
=================================
Validação do timeout de chamadas HTTP de LLM (Missão v2/timeout-llm):
1. Verificação da constante canônica LLM_REQUEST_TIMEOUT_SECONDS = 90 (FONTE ÚNICA 1).
2. Verificação de que o cliente Gemini recebe HttpOptions(timeout=90000) (em milissegundos).
3. Verificação de que o cliente OpenAI recebe timeout=90 (em segundos).
4. Verificação de que config.app["llm_request_timeout_seconds"] sobrescreve o timeout
   para todos os clientes (Gemini em ms, OpenAI em segundos).
"""

import types as py_types
from unittest.mock import patch, MagicMock
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


def test_llm_request_timeout_constant():
    """FONTE ÚNICA 1: Constante canônica LLM_REQUEST_TIMEOUT_SECONDS deve ser 90."""
    assert llm.LLM_REQUEST_TIMEOUT_SECONDS == 90
    # Sem override no config, get_llm_request_timeout_seconds retorna 90.0
    config.app.pop("llm_request_timeout_seconds", None)
    assert llm.get_llm_request_timeout_seconds() == 90.0


def test_gemini_client_receives_timeout_ms_default():
    """
    FONTE ÚNICA 2: Gemini usa google-genai, que espera timeout em MILISSEGUNDOS (90000 ms).
    """
    config.app.pop("llm_request_timeout_seconds", None)
    config.app.update({
        "llm_provider": "gemini",
        "gemini_api_key": "fake-key-123",
        "gemini_model_name": "gemini-2.5-flash",
        "gemini_base_url": "",
    })

    captured = {}

    class FakeModels:
        def generate_content(self, **kwargs):
            return py_types.SimpleNamespace(text="gemini response text")

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            self.models = FakeModels()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("google.genai.Client", FakeClient):
        result = llm._generate_response("Teste de prompt Gemini")

    assert result == "gemini response text"
    assert "client_kwargs" in captured
    http_options = captured["client_kwargs"].get("http_options")
    assert http_options is not None, "http_options deve ser fornecido ao Client"
    # google-genai HttpOptions timeout em ms
    assert http_options.timeout == 90000, f"Esperava timeout=90000 ms, obteve {http_options.timeout}"


def test_openai_client_receives_timeout_seconds_default():
    """
    FONTE ÚNICA 2: OpenAI usa timeout em SEGUNDOS (90 s).
    """
    config.app.pop("llm_request_timeout_seconds", None)
    config.app.update({
        "llm_provider": "openai",
        "openai_api_key": "sk-fake-openai-key",
        "openai_model_name": "gpt-4o-mini",
        "openai_base_url": "",
    })

    captured = {}

    class FakeChatCompletions:
        def create(self, **kwargs):
            choice = py_types.SimpleNamespace(
                message=py_types.SimpleNamespace(content="openai response text")
            )
            return py_types.SimpleNamespace(choices=[choice])

    class FakeChat:
        completions = FakeChatCompletions()

    def fake_openai_init(**kwargs):
        captured["openai_kwargs"] = kwargs
        mock_instance = MagicMock()
        mock_instance.chat = FakeChat()
        return mock_instance

    with patch.object(llm, "ChatCompletion", py_types.SimpleNamespace):
        with patch("app.services.llm.OpenAI", side_effect=fake_openai_init):
            result = llm._generate_response("Teste de prompt OpenAI")

    assert result == "openai response text"
    assert "openai_kwargs" in captured
    timeout = captured["openai_kwargs"].get("timeout")
    assert timeout == 90.0 or timeout == 90, f"Esperava timeout=90s, obteve {timeout}"


def test_config_override_affects_gemini_and_openai():
    """
    Verifica que config.app['llm_request_timeout_seconds'] sobrescreve o valor padrão
    para Gemini (em ms) e OpenAI (em s).
    """
    # Define override para 45 segundos
    config.app["llm_request_timeout_seconds"] = 45

    assert llm.get_llm_request_timeout_seconds() == 45.0

    # 1. Valida Gemini com override de 45s -> 45000 ms
    config.app.update({
        "llm_provider": "gemini",
        "gemini_api_key": "fake-key-gemini",
        "gemini_model_name": "gemini-2.5-flash",
        "gemini_base_url": "",
    })
    captured_gemini = {}

    class FakeModels:
        def generate_content(self, **kwargs):
            return py_types.SimpleNamespace(text="gemini 45s")

    class FakeClient:
        def __init__(self, **kwargs):
            captured_gemini["client_kwargs"] = kwargs
            self.models = FakeModels()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("google.genai.Client", FakeClient):
        result_gemini = llm._generate_response("Prompt Gemini 45s")

    assert result_gemini == "gemini 45s"
    http_opts = captured_gemini["client_kwargs"].get("http_options")
    assert http_opts.timeout == 45000, f"Esperava timeout=45000 ms, obteve {http_opts.timeout}"

    # 2. Valida OpenAI com override de 45s -> 45.0 s
    config.app.update({
        "llm_provider": "openai",
        "openai_api_key": "sk-fake-key",
        "openai_model_name": "gpt-4o-mini",
        "openai_base_url": "",
    })
    captured_openai = {}

    def fake_openai_init(**kwargs):
        captured_openai["openai_kwargs"] = kwargs
        mock_instance = MagicMock()
        choice = py_types.SimpleNamespace(
            message=py_types.SimpleNamespace(content="openai 45s")
        )
        mock_instance.chat.completions.create.return_value = py_types.SimpleNamespace(choices=[choice])
        return mock_instance

    with patch.object(llm, "ChatCompletion", py_types.SimpleNamespace):
        with patch("app.services.llm.OpenAI", side_effect=fake_openai_init):
            result_openai = llm._generate_response("Prompt OpenAI 45s")

    assert result_openai == "openai 45s"
    timeout_openai = captured_openai["openai_kwargs"].get("timeout")
    assert timeout_openai == 45.0 or timeout_openai == 45, (
        f"Esperava timeout=45s, obteve {timeout_openai}"
    )


def test_generate_ideas_raises_runtime_error_on_llm_error():
    """
    FONTE ÚNICA: Resposta de erro do LLM ('Error: ...') não pode ser interpretada como ideia.
    autopilot.generate_ideas deve levantar RuntimeError e NÃO devolver lista de ideias.
    """
    from app.services import autopilot

    error_response = "Error: Request timed out."

    with patch("app.services.llm._generate_response", return_value=error_response):
        with pytest.raises(RuntimeError) as exc_info:
            autopilot.generate_ideas(niche="curiosidades", count=5)

    err_str = str(exc_info.value)
    assert "Error: Request timed out." in err_str


def test_generate_ideas_returns_ideas_on_normal_response():
    """
    Com resposta normal de 3 linhas do LLM, generate_ideas devolve 3 ideias limpas.
    """
    from app.services import autopilot

    normal_response = (
        "1. Mistérios do Fundo do Oceano\n"
        "2. Segredos do Universo Antigo\n"
        "3. Como Funcionam os Buracos Negros\n"
    )

    with patch("app.services.llm._generate_response", return_value=normal_response):
        ideas = autopilot.generate_ideas(niche="curiosidades", count=3)

    assert isinstance(ideas, list)
    assert len(ideas) == 3
    assert ideas[0] == "Mistérios do Fundo do Oceano"
    assert ideas[1] == "Segredos do Universo Antigo"
    assert ideas[2] == "Como Funcionam os Buracos Negros"
