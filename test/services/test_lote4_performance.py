import os
import time
import pytest

from app.config import config
from app.utils import utils
from app.services import operator_console
from webui.components import channel_factory


def test_config_dirty_detection_and_persistence(tmp_path):
    """Verifica que gravações de config ocorrem apenas sob alteração real."""
    # Salvar sem alterações deve retornar True imediatamente sem I/O
    with config._pending_config_lock:
        config._pending_config_updates.clear()
        config._pending_config_save_requested = False

    saved = config.try_save_config(force=False)
    assert saved is True
    with config._pending_config_lock:
        assert config._pending_config_save_requested is False

    # No-op: atualizar com mesmo valor não marca dirty
    cur_lang = config.ui.get("language", "pt-BR")
    config.update_config_nonblocking(config.ui, "language", cur_lang)
    with config._pending_config_lock:
        assert config._pending_config_save_requested is False
        assert len(config._pending_config_updates) == 0

    # Alteração real deve marcar pendente e persistir
    test_val = "fr-FR"
    try:
        config.update_config_nonblocking(config.ui, "language", test_val)
        with config._pending_config_lock:
            # O save deve ter sido solicitado devido à alteração de valor
            assert config._pending_config_save_requested is True

        # Agora try_save_config deve aplicar, gravar em disco e resetar flag
        saved_after_change = config.try_save_config(force=False)
        assert saved_after_change is True
        assert config.ui.get("language") == test_val
        with config._pending_config_lock:
            assert config._pending_config_save_requested is False
    finally:
        # Restaura valor original
        config.update_config_nonblocking(config.ui, "language", cur_lang)
        config.try_save_config(force=True)
        assert config.ui.get("language") == cur_lang


def test_ffmpeg_check_caching():
    """Verifica que check_ffmpeg_ready utiliza cache in-memory e suporta invalidação."""
    utils.clear_ffmpeg_check_cache()
    # Primeira chamada
    t0 = time.perf_counter()
    r1 = utils.check_ffmpeg_ready()
    t1 = time.perf_counter()

    # Segunda chamada (deve usar cache e ser ordens de grandeza mais rápida)
    t2 = time.perf_counter()
    r2 = utils.check_ffmpeg_ready()
    t3 = time.perf_counter()

    assert r1 == r2
    cached_duration = t3 - t2
    first_duration = t1 - t0
    assert cached_duration < first_duration or cached_duration < 0.005


def test_provider_health_summary_caching():
    """Verifica que o sumário de saúde dos provedores é cacheado por TTL e pode ser invalidado."""
    operator_console.clear_provider_health_cache()
    h1 = operator_console.get_provider_health_summary()
    assert "FFmpeg" in h1
    assert "Gemini" in h1

    # Segunda chamada (em cache)
    h2 = operator_console.get_provider_health_summary()
    assert h1 is h2  # Mesma referência em memória do cache

    # Invalidação forçada
    operator_console.clear_provider_health_cache()
    h3 = operator_console.get_provider_health_summary()
    assert "FFmpeg" in h3


def test_factory_voices_catalog():
    """Verifica consistência do catálogo de vozes aprovadas para a fábrica."""
    voices = channel_factory.get_available_factory_voices()
    assert "en-US-BrianMultilingualNeural" in voices
    assert any("pt-BR" in v for v in voices)
    
    # Com voz corrente válida
    custom_voice = "pt-BR-AntonioNeural"
    voices_with_cur = channel_factory.get_available_factory_voices(current_voice=custom_voice)
    assert custom_voice in voices_with_cur
