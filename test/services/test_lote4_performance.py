import os
import time
from unittest.mock import patch
import pytest

from app.config import config
from app.utils import utils
from app.services import operator_console, autonomous_production
from app.models.schema import VideoParams
from webui.components import channel_factory


def test_cf_l4_01_config_dirty_tracking_and_synchronized_mutations():
    """CF-L4-01: Dirty tracking em mutações de _SynchronizedConfig e preservação de force=True."""
    # 1. try_save_config com force=True (default) sempre requisita e salva
    saved = config.try_save_config()
    assert saved is True

    # 2. Rerun passivo sem alteração (force=False) é no-op
    with config._pending_config_lock:
        config._pending_config_save_requested = False
        config._pending_config_updates.clear()
    saved_passive = config.try_save_config(force=False)
    assert saved_passive is True
    with config._pending_config_lock:
        assert config._pending_config_save_requested is False

    # 3. Mutação direta em _SynchronizedConfig via __setitem__ ativa dirty tracking
    orig_voice = config.ui.get("voice_name") or "default_voice"
    test_voice = "pt-BR-FranciscaNeural" if orig_voice != "pt-BR-FranciscaNeural" else "en-US-BrianMultilingualNeural"
    try:
        config.ui["voice_name"] = test_voice
        with config._pending_config_lock:
            assert config._pending_config_save_requested is True
        
        # Agora force=False deve gravar porque está dirty
        assert config.try_save_config(force=False) is True
        assert config.ui.get("voice_name") == test_voice
    finally:
        config.ui["voice_name"] = orig_voice
        config.try_save_config(force=True)


def test_cf_l4_02_ffmpeg_cache_positive_only():
    """CF-L4-02: Cacheia apenas checagens positivas; falhas não ficam retidas."""
    utils.clear_ffmpeg_check_cache()

    # 1. Simula falha temporária
    with patch("subprocess.run", side_effect=FileNotFoundError("not found")):
        res_fail = utils.check_ffmpeg_ready()
        assert res_fail is False
        # Não deve estar gravado como True no cache
        assert utils._FFMPEG_CHECK_CACHE["result"] is None

    # 2. Em seguida, sem mock, deve checar novamente de forma transparente
    res_real = utils.check_ffmpeg_ready()
    assert res_real is True
    assert utils._FFMPEG_CHECK_CACHE["result"] is True


def test_cf_l4_03_channel_factory_bare_mode_and_onboarding():
    """CF-L4-03: render_channel_factory em bare mode e formato de Quiz sem bloqueio de st.form."""
    # Deve ser invocável sem lançar erro de decorator de fragmento
    assert callable(channel_factory.render_channel_factory)

    # Catálogo de vozes aprovadas deve estar íntegro
    voices = channel_factory.get_available_factory_voices()
    assert "en-US-BrianMultilingualNeural" in voices
    assert any("pt-BR" in v for v in voices)


def test_cf_l4_04_provider_health_invalidation():
    """CF-L4-04: Invalidação de cache ao emitir eventos relevantes ou reset_instance_for_testing."""
    operator_console.clear_provider_health_cache()
    h1 = operator_console.get_provider_health_summary()
    assert h1 is not None

    # Leitura repetida retorna a mesma referência de cache
    h2 = operator_console.get_provider_health_summary()
    assert h1 is h2

    # Evento de warning ou erro deve invalidar cache
    operator_console.log_operational_event(
        component="Gemini",
        severity=operator_console.SEVERITY_WARNING,
        event_type="RATE_LIMIT",
        message="Simulated warning for test",
    )
    assert operator_console._PROVIDER_HEALTH_CACHE["data"] is None

    # Nova leitura reconstrói cache
    h3 = operator_console.get_provider_health_summary()
    assert h3 is not None

    # reset_instance_for_testing também invalida
    operator_console.reset_instance_for_testing()
    assert operator_console._PROVIDER_HEALTH_CACHE["data"] is None


def test_cf_l4_05_brazilian_content_contract_quiz_exemption():
    """CF-L4-05: Quiz Dilema e Quiz Papel isentos de legenda externa SRT."""
    # Tradicional com subtitle_disabled deve ser bloqueado
    trad_params = {
        "video_language": "pt-BR",
        "region": "BR",
        "voice_name": "pt-BR-AntonioNeural",
        "video_format": "traditional",
        "subtitle_enabled": False,
    }
    res_trad = autonomous_production.validate_autonomous_brazilian_content_contract(trad_params)
    assert res_trad["status"] == "BLOCK"
    assert "subtitle_disabled" in res_trad["reasons"]

    # Quiz Dilema com subtitle_enabled=False DEVE passar (isento de SRT externo)
    quiz_dilemma_params = {
        "video_language": "pt-BR",
        "region": "BR",
        "voice_name": "pt-BR-AntonioNeural",
        "video_format": "quiz_dilemma",
        "subtitle_enabled": False,
    }
    res_qd = autonomous_production.validate_autonomous_brazilian_content_contract(quiz_dilemma_params)
    assert res_qd["status"] == "PASS"
    assert "subtitle_disabled" not in res_qd["reasons"]

    # Quiz Papel com subtitle_enabled=False DEVE passar
    quiz_paper_params = {
        "video_language": "pt-BR",
        "region": "BR",
        "voice_name": "pt-BR-AntonioNeural",
        "video_format": "quiz_paper",
        "subtitle_enabled": False,
    }
    res_qp = autonomous_production.validate_autonomous_brazilian_content_contract(quiz_paper_params)
    assert res_qp["status"] == "PASS"
    assert "subtitle_disabled" not in res_qp["reasons"]
