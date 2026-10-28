"""Testes direcionados do Hotfix: Validação de Voz e Taxa no Painel WebUI (V1).

Valida os requisitos da missão hotfix/voz-painel-validada:
1. Voz af-ZA-AdriNeural é recusada e não altera config.ui["voice_name"].
2. Brian e vozes pt-BR-* válidas são gravadas no formato canônico.
3. Não grava se o valor for igual ao já salvo (evita escrita a cada render).
4. voice_rate fora da faixa [0.8, 2.0] ou não finito é recusado; dentro da faixa é gravado.
5. Índice inicial do seletor: voz salva válida > Brian; nunca a primeira da lista (ex: af-ZA) nem idioma da UI.
6. Emissão de log WARNING em gravações recusadas sem vazamento de dados sensíveis.
7. Renderizar sem interação NÃO chama _set_runtime_config para voice_rate (mesmo com 0.8 em session_state).
8. Mudança explícita do operador via callback (_on_voice_rate_changed) para valor válido grava com idempotência.
9. Valor inválido via callback (_on_voice_rate_changed) é recusado e não altera config.ui["voice_rate"].
10. Renderizar sem interação NÃO chama _set_runtime_config para voice_name (mesmo com voz válida diferente no session_state, ex.: pt-BR-FranciscaNeural), preserva params.voice_name e registra on_change no selectbox de voz.
11. Mudança explícita via callback (_on_voice_name_changed) para voz válida grava com idempotência.
12. Voz inválida via callback (_on_voice_name_changed, ex.: af-ZA) é recusada e emite WARNING.
"""

import math
from unittest.mock import patch, MagicMock

import pytest
import streamlit as st

from app.config import config
from app.models.schema import VideoParams
from webui.Main import (
    VOICE_RATE_MIN,
    VOICE_RATE_MAX,
    _on_voice_name_changed,
    _on_voice_rate_changed,
    _render_audio_settings,
    is_valid_ui_voice_rate,
    localized_widget_key,
    resolve_initial_voice_selection,
    save_validated_voice_name,
    save_validated_voice_rate,
)


@pytest.fixture(autouse=True)
def restore_ui_config():
    """Garante restauração do estado original de config.ui e session_state após cada teste."""
    orig_voice_name = config.ui.get("voice_name")
    orig_voice_rate = config.ui.get("voice_rate")
    rate_wkey = localized_widget_key("voice_rate_select")
    had_wkey = rate_wkey in st.session_state
    orig_wkey_val = st.session_state.get(rate_wkey)
    had_raw_key = "voice_rate_select" in st.session_state
    orig_raw_val = st.session_state.get("voice_rate_select")

    voice_base_key = "speech_synthesis_select_azure-tts-v1"
    voice_wkey = localized_widget_key(voice_base_key)
    had_voice_wkey = voice_wkey in st.session_state
    orig_voice_wkey_val = st.session_state.get(voice_wkey)
    had_voice_raw = voice_base_key in st.session_state
    orig_voice_raw_val = st.session_state.get(voice_base_key)

    yield
    if orig_voice_name is not None:
        config.ui["voice_name"] = orig_voice_name
    else:
        config.ui.pop("voice_name", None)

    if orig_voice_rate is not None:
        config.ui["voice_rate"] = orig_voice_rate
    else:
        config.ui.pop("voice_rate", None)

    if had_wkey:
        st.session_state[rate_wkey] = orig_wkey_val
    else:
        st.session_state.pop(rate_wkey, None)

    if had_raw_key:
        st.session_state["voice_rate_select"] = orig_raw_val
    else:
        st.session_state.pop("voice_rate_select", None)

    if had_voice_wkey:
        st.session_state[voice_wkey] = orig_voice_wkey_val
    else:
        st.session_state.pop(voice_wkey, None)

    if had_voice_raw:
        st.session_state[voice_base_key] = orig_voice_raw_val
    else:
        st.session_state.pop(voice_base_key, None)


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
    idx = resolve_initial_voice_selection("pt-BR-AntonioNeural-Male", catalog, "azure-tts-v1")
    assert idx == 2  # Antonio


def test_initial_index_invalid_saved_voice_falls_back_to_brian_never_first_of_list():
    """6. Índice inicial: se a voz salva for inválida (ex.: af-ZA), cai em Brian e NUNCA na primeira da lista."""
    catalog = {
        "af-ZA-AdriNeural-Female": "Adri",  # Índice 0 (nunca deve ser selecionado como fallback)
        "en-US-BrianMultilingualNeural-Male": "Brian",  # Índice 1 (fallback obrigatório)
        "pt-BR-AntonioNeural-Male": "Antonio",  # Índice 2
    }
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


def test_render_without_interaction_does_not_write_voice_rate():
    """9. Renderizar o painel de áudio sem interação NÃO chama _set_runtime_config para voice_rate."""
    config.ui["voice_name"] = "en-US-BrianMultilingualNeural"
    config.ui["voice_rate"] = 1.1

    # Simula aba antiga ou tarefa restaurada com 0.8 no session_state da sessão
    rate_wkey = localized_widget_key("voice_rate_select")
    st.session_state[rate_wkey] = 0.8

    captured_selectbox_kwargs = {}

    def _fake_selectbox(label, options, **kwargs):
        key = kwargs.get("key")
        if key == rate_wkey:
            captured_selectbox_kwargs.update(kwargs)
        return st.session_state.get(key, options[0])

    params = VideoParams(video_subject="")
    with (
        patch("webui.Main._set_runtime_config", side_effect=_apply_runtime_config) as mock_set_cfg,
        patch("webui.Main.stable_segmented_control", return_value="tts"),
        patch("webui.Main.st.selectbox", side_effect=_fake_selectbox),
        patch("webui.Main.st.columns", side_effect=lambda spec, **kw: [MagicMock() for _ in range(spec if isinstance(spec, int) else len(spec))]),
        patch("webui.Main.st.container", return_value=MagicMock()),
        patch("webui.Main.st.write"),
        patch("webui.Main.st.info"),
        patch("webui.Main._render_voice_preview"),
        patch("webui.Main._render_background_music_settings", return_value=None),
        patch("webui.Main.voice.get_all_azure_voices", return_value=["en-US-BrianMultilingualNeural-Male"]),
    ):
        _render_audio_settings(MagicMock(), params)

    # Verifica que nenhuma chamada a _set_runtime_config tentou gravar voice_rate durante o render
    voice_rate_writes = [
        call for call in mock_set_cfg.call_args_list
        if len(call.args) >= 2 and call.args[0] == "ui" and call.args[1] == "voice_rate"
    ]
    assert voice_rate_writes == []
    # O valor salvo globalmente permanece 1.1 (não foi sobrescrito pelo 0.8 da sessão)
    assert math.isclose(float(config.ui["voice_rate"]), 1.1)
    # O selectbox de velocidade registrou o callback on_change=_on_voice_rate_changed
    assert captured_selectbox_kwargs.get("on_change") is _on_voice_rate_changed


def test_explicit_operator_change_callback_saves_valid_voice_rate():
    """10. Mudança explícita do operador (callback _on_voice_rate_changed) para valor válido grava."""
    config.ui["voice_rate"] = 1.1
    rate_wkey = localized_widget_key("voice_rate_select")
    st.session_state[rate_wkey] = 1.3

    with patch("webui.Main._set_runtime_config", side_effect=_apply_runtime_config) as mock_set_cfg:
        result = _on_voice_rate_changed()
        assert result is True
        mock_set_cfg.assert_called_once_with("ui", "voice_rate", 1.3)
        assert math.isclose(float(config.ui["voice_rate"]), 1.3)

        # Idempotência: chamar novamente com o mesmo valor não regrava
        mock_set_cfg.reset_mock()
        result_again = _on_voice_rate_changed()
        assert result_again is False
        mock_set_cfg.assert_not_called()


def test_invalid_voice_rate_via_callback_is_refused():
    """11. Valor inválido via callback (_on_voice_rate_changed) é recusado e emite WARNING."""
    config.ui["voice_rate"] = 1.1
    rate_wkey = localized_widget_key("voice_rate_select")

    invalid_values = [0.5, 0.79, 2.01, -1.0, float("nan"), float("inf"), "invalid", None]
    with (
        patch("webui.Main._set_runtime_config") as mock_set_cfg,
        patch("webui.Main.logger.warning") as mock_warn,
    ):
        for bad_val in invalid_values:
            st.session_state[rate_wkey] = bad_val
            assert _on_voice_rate_changed() is False

        mock_set_cfg.assert_not_called()
        assert mock_warn.call_count == len(invalid_values)
        assert math.isclose(float(config.ui["voice_rate"]), 1.1)


def test_render_without_interaction_does_not_write_voice_name_even_with_valid_stale_session_voice():
    """12. Render sem interação NÃO chama _set_runtime_config para voice_name, mesmo com voz válida diferente (Francisca) no session_state, e registra on_change."""
    config.ui["voice_name"] = "en-US-BrianMultilingualNeural"
    config.ui["voice_rate"] = 1.1

    # Simula aba antiga com outra voz válida (pt-BR-FranciscaNeural-Female) no session_state
    voice_wkey = localized_widget_key("speech_synthesis_select_azure-tts-v1")
    st.session_state[voice_wkey] = "pt-BR-FranciscaNeural-Female"

    captured_voice_selectbox_kwargs = {}

    def _fake_selectbox(label, options, **kwargs):
        key = kwargs.get("key")
        if key == voice_wkey:
            captured_voice_selectbox_kwargs.update(kwargs)
        return st.session_state.get(key, options[0])

    params = VideoParams(video_subject="")
    with (
        patch("webui.Main._set_runtime_config", side_effect=_apply_runtime_config) as mock_set_cfg,
        patch("webui.Main.stable_segmented_control", return_value="tts"),
        patch("webui.Main.st.selectbox", side_effect=_fake_selectbox),
        patch("webui.Main.st.columns", side_effect=lambda spec, **kw: [MagicMock() for _ in range(spec if isinstance(spec, int) else len(spec))]),
        patch("webui.Main.st.container", return_value=MagicMock()),
        patch("webui.Main.st.write"),
        patch("webui.Main.st.info"),
        patch("webui.Main._render_voice_preview"),
        patch("webui.Main._render_background_music_settings", return_value=None),
        patch(
            "webui.Main.voice.get_all_azure_voices",
            return_value=[
                "af-ZA-AdriNeural-Female",
                "en-US-BrianMultilingualNeural-Male",
                "pt-BR-FranciscaNeural-Female",
            ],
        ),
    ):
        _render_audio_settings(MagicMock(), params)

    # Nenhuma gravação de voice_name durante o render
    voice_name_writes = [
        call for call in mock_set_cfg.call_args_list
        if len(call.args) >= 2 and call.args[0] == "ui" and call.args[1] == "voice_name"
    ]
    assert voice_name_writes == []
    # config.ui["voice_name"] global permanece Brian (não sobrescrito por Francisca da aba antiga)
    assert config.ui["voice_name"] == "en-US-BrianMultilingualNeural"
    # params.voice_name da sessão manual continua refletindo o valor retornado pelo selectbox
    assert params.voice_name == "pt-BR-FranciscaNeural-Female"
    # O seletor de voz registrou on_change=_on_voice_name_changed
    assert captured_voice_selectbox_kwargs.get("on_change") is _on_voice_name_changed
    assert captured_voice_selectbox_kwargs.get("args") == ("azure-tts-v1",)


def test_explicit_operator_change_callback_saves_valid_voice_name():
    """13. Mudança explícita via callback (_on_voice_name_changed) para voz válida grava."""
    config.ui["voice_name"] = "en-US-BrianMultilingualNeural"
    voice_wkey = localized_widget_key("speech_synthesis_select_azure-tts-v1")
    st.session_state[voice_wkey] = "pt-BR-FranciscaNeural-Female"

    with patch("webui.Main._set_runtime_config", side_effect=_apply_runtime_config) as mock_set_cfg:
        result = _on_voice_name_changed("azure-tts-v1")
        assert result is True
        mock_set_cfg.assert_called_once_with("ui", "voice_name", "pt-BR-FranciscaNeural")
        assert config.ui["voice_name"] == "pt-BR-FranciscaNeural"

        # Idempotência: chamar de novo com a mesma voz não grava novamente
        mock_set_cfg.reset_mock()
        result_again = _on_voice_name_changed("azure-tts-v1")
        assert result_again is False
        mock_set_cfg.assert_not_called()


def test_invalid_voice_name_via_callback_is_refused():
    """14. Voz inválida via callback (_on_voice_name_changed, ex.: af-ZA) é recusada."""
    config.ui["voice_name"] = "en-US-BrianMultilingualNeural"
    voice_wkey = localized_widget_key("speech_synthesis_select_azure-tts-v1")
    st.session_state[voice_wkey] = "af-ZA-AdriNeural-Female"

    with (
        patch("webui.Main._set_runtime_config") as mock_set_cfg,
        patch("webui.Main.logger.warning") as mock_warn,
    ):
        result = _on_voice_name_changed("azure-tts-v1")
        assert result is False
        mock_set_cfg.assert_not_called()
        assert mock_warn.called
        assert "af-ZA-AdriNeural" in mock_warn.call_args[0][0]
        assert config.ui["voice_name"] == "en-US-BrianMultilingualNeural"
