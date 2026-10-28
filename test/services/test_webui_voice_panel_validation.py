"""Testes direcionados do Hotfix: Validação de Voz e Taxa no Painel WebUI (V1).

Valida os requisitos da missão hotfix/voz-painel-validada:
1. Voz af-ZA-AdriNeural é recusada e não altera config.ui["voice_name"].
2. Brian e vozes pt-BR-* válidas são gravadas no formato canônico.
3. Não grava se o valor for igual ao já salvo (evita escrita a cada render).
4. voice_rate fora da faixa [0.8, 2.0] ou não finito é recusado; dentro da faixa é gravado.
5. Índice inicial do seletor: voz salva válida > Brian; nunca a primeira da lista (ex: af-ZA) nem idioma da UI.
6. Emissão de log WARNING em gravações recusadas sem vazamento de dados sensíveis.
"""

import math
from unittest.mock import patch, MagicMock

import pytest

from app.config import config
from webui.Main import (
    VOICE_RATE_MIN,
    VOICE_RATE_MAX,
    is_valid_ui_voice_rate,
    resolve_initial_voice_selection,
    save_validated_voice_name,
    save_validated_voice_rate,
)


@pytest.fixture(autouse=True)
def restore_ui_config():
    """Garante restauração do estado original de config.ui após cada teste."""
    orig_voice_name = config.ui.get("voice_name")
    orig_voice_rate = config.ui.get("voice_rate")
    yield
    if orig_voice_name is not None:
        config.ui["voice_name"] = orig_voice_name
    else:
        config.ui.pop("voice_name", None)

    if orig_voice_rate is not None:
        config.ui["voice_rate"] = orig_voice_rate
    else:
        config.ui.pop("voice_rate", None)


def _apply_runtime_config(section, key, val):
    if section == "ui":
        config.ui[key] = val
    return True


def test_af_za_voice_is_refused_and_does_not_modify_config_ui():
    """1. Voz af-ZA-AdriNeural é recusada e NÃO altera config.ui."""
    config.ui["voice_name"] = "en-US-BrianMultilingualNeural"

    with patch("webui.Main._set_runtime_config") as mock_set:
        saved = save_validated_voice_name("af-ZA-AdriNeural-Female", "azure-tts-v1")
        assert saved is False
        mock_set.assert_not_called()
        assert config.ui["voice_name"] == "en-US-BrianMultilingualNeural"

        # Variação com identificador simples
        saved_simple = save_validated_voice_name("af-ZA-AdriNeural", "azure-tts-v1")
        assert saved_simple is False
        mock_set.assert_not_called()
        assert config.ui["voice_name"] == "en-US-BrianMultilingualNeural"


def test_brian_and_valid_pt_br_voices_are_persisted():
    """2. Brian e vozes pt-BR-* válidas são gravadas no formato canônico."""
    config.ui["voice_name"] = ""

    # Brian
    with patch("webui.Main._set_runtime_config", side_effect=_apply_runtime_config):
        saved_brian = save_validated_voice_name("en-US-BrianMultilingualNeural-Male", "azure-tts-v1")
        assert saved_brian is True
        assert config.ui.get("voice_name") == "en-US-BrianMultilingualNeural"

    # pt-BR Francisca
    with patch("webui.Main._set_runtime_config", side_effect=_apply_runtime_config):
        saved_francisca = save_validated_voice_name("pt-BR-FranciscaNeural-Female", "azure-tts-v1")
        assert saved_francisca is True
        assert config.ui.get("voice_name") == "pt-BR-FranciscaNeural"

    # pt-BR Antonio
    with patch("webui.Main._set_runtime_config", side_effect=_apply_runtime_config):
        saved_antonio = save_validated_voice_name("pt-BR-AntonioNeural-Male", "azure-tts-v1")
        assert saved_antonio is True
        assert config.ui.get("voice_name") == "pt-BR-AntonioNeural"


def test_voice_name_not_written_if_already_equal():
    """3. Não grava se a voz for idêntica à já salva (evita escrita a cada render)."""
    config.ui["voice_name"] = "pt-BR-AntonioNeural"

    with patch("webui.Main._set_runtime_config") as mock_set:
        saved = save_validated_voice_name("pt-BR-AntonioNeural-Male", "azure-tts-v1")
        assert saved is False
        mock_set.assert_not_called()
        assert config.ui["voice_name"] == "pt-BR-AntonioNeural"


def test_voice_rate_out_of_range_is_refused_and_in_range_is_persisted():
    """4. voice_rate fora da faixa [0.8, 2.0] ou não finito é recusado; dentro da faixa é gravado."""
    config.ui["voice_rate"] = 1.0

    # Valores inválidos / fora de faixa
    bad_rates = [
        0.79, 0.5, 0.0, -1.0, 2.01, 3.0, 999.0,
        float("nan"), float("inf"), float("-inf"),
        "invalid", None,
    ]
    with patch("webui.Main._set_runtime_config") as mock_set:
        for bad in bad_rates:
            assert is_valid_ui_voice_rate(bad) is False
            saved = save_validated_voice_rate(bad)
            assert saved is False
            assert config.ui["voice_rate"] == 1.0
        mock_set.assert_not_called()

    # Valores válidos
    valid_rates = [0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5, 1.8, 2.0]
    for good in valid_rates:
        assert is_valid_ui_voice_rate(good) is True

    # Persistência de valor válido e diferente
    with patch("webui.Main._set_runtime_config", side_effect=_apply_runtime_config):
        saved = save_validated_voice_rate(1.2)
        assert saved is True
        assert math.isclose(float(config.ui["voice_rate"]), 1.2)

        # Mesma taxa: idempotência (não grava novamente)
        with patch("webui.Main._set_runtime_config") as mock_duplicate:
            saved_again = save_validated_voice_rate(1.2)
            assert saved_again is False
            mock_duplicate.assert_not_called()


def test_initial_index_valid_saved_voice_over_brian():
    """5. Índice inicial: voz salva válida e existente no catálogo tem precedência."""
    catalog = {
        "af-ZA-AdriNeural-Female": "Adri",
        "en-US-BrianMultilingualNeural-Male": "Brian",
        "pt-BR-AntonioNeural-Male": "Antonio",
    }
    # Voz salva válida presente no catálogo
    idx = resolve_initial_voice_selection("pt-BR-AntonioNeural-Male", catalog, "azure-tts-v1")
    assert idx == 2  # Antonio


def test_initial_index_invalid_saved_voice_falls_back_to_brian_never_first_of_list():
    """6. Índice inicial: se a voz salva for inválida (ex.: af-ZA), cai em Brian e NUNCA na primeira da lista."""
    catalog = {
        "af-ZA-AdriNeural-Female": "Adri",  # Índice 0 (nunca deve ser selecionado como fallback)
        "en-US-BrianMultilingualNeural-Male": "Brian",  # Índice 1 (fallback obrigatório)
        "pt-BR-AntonioNeural-Male": "Antonio",  # Índice 2
    }
    # af-ZA é inválida para pt-BR
    idx = resolve_initial_voice_selection("af-ZA-AdriNeural-Female", catalog, "azure-tts-v1")
    assert idx == 1  # Brian!
    assert idx != 0  # NUNCA a primeira da lista!


def test_initial_index_unknown_or_missing_saved_voice_falls_back_to_brian():
    """7. Índice inicial: voz não encontrada no catálogo cai em Brian, nunca no índice 0."""
    catalog = {
        "af-ZA-AdriNeural-Female": "Adri",
        "en-US-BrianMultilingualNeural-Male": "Brian",
        "pt-BR-AntonioNeural-Male": "Antonio",
    }
    # Voz vazia ou inexistente
    assert resolve_initial_voice_selection("", catalog, "azure-tts-v1") == 1
    assert resolve_initial_voice_selection("non-existent-voice", catalog, "azure-tts-v1") == 1


def test_warnings_logged_when_writes_refused():
    """8. Registrar log WARNING quando uma gravação for recusada (sem segredos)."""
    with patch("webui.Main.logger.warning") as mock_warn:
        save_validated_voice_name("af-ZA-AdriNeural", "azure-tts-v1")
        assert mock_warn.called
        assert "af-ZA-AdriNeural" in mock_warn.call_args[0][0]

    with patch("webui.Main.logger.warning") as mock_warn_rate:
        save_validated_voice_rate(0.5)
        assert mock_warn_rate.called
        assert "0.5" in mock_warn_rate.call_args[0][0]
