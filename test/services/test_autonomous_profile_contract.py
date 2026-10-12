"""Targeted tests for autonomous profile contract hotfix:
- Profile voice precedence and canonicalization
- Growth Mode safety caps (WARMUP / SCALE) for 24h approvals and attempts
"""
import pytest

from app.config import config
from app.models import const
from app.services import (
    autonomous_production as autonomous,
    operator_console as console,
    profile_manager,
    scheduler,
)


@pytest.fixture
def isolated_db(tmp_path):
    """Cria banco isolado em diretório temporário para garantir zero mutação no banco real."""
    db = str(tmp_path / "test_autonomous_contract.db")
    console.init_operator_db(db)
    scheduler.init_db(db)
    profile_manager.init_profile_db(db)
    profile_manager.ensure_default_profile(db)
    return db


def test_1_profile_voice_wins_over_global_voice(isolated_db, monkeypatch):
    """1. Profile voice definida vence voz global."""
    pid = profile_manager.DEFAULT_PROFILE_ID
    monkeypatch.setitem(config.ui, "voice_name", "en-US-BrianMultilingualNeural")

    settings = profile_manager.get_profile_settings(pid, db_path=isolated_db)
    settings.voice.voice_name = "pt-BR-FranciscaNeural"
    profile_manager.update_profile_settings(pid, settings, db_path=isolated_db)

    ctx = profile_manager.get_generation_profile_context(pid, db_path=isolated_db)
    assert ctx["voice_name"] == "pt-BR-FranciscaNeural"


def test_2_profile_without_voice_uses_global_fallback(isolated_db, monkeypatch):
    """2. Profile sem voice usa fallback global."""
    pid = profile_manager.DEFAULT_PROFILE_ID
    monkeypatch.setitem(config.ui, "voice_name", "pt-BR-AntonioNeural")

    settings = profile_manager.get_profile_settings(pid, db_path=isolated_db)
    settings.voice.voice_name = None
    profile_manager.update_profile_settings(pid, settings, db_path=isolated_db)

    ctx = profile_manager.get_generation_profile_context(pid, db_path=isolated_db)
    assert ctx["voice_name"] == "pt-BR-AntonioNeural"


def test_3_canonicalization_applied_to_profile_voice(isolated_db, monkeypatch):
    """3. Canonicalização existente continua aplicada à voz do perfil (remove sufixo de catálogo)."""
    pid = profile_manager.DEFAULT_PROFILE_ID
    monkeypatch.setitem(config.ui, "voice_name", "en-US-BrianMultilingualNeural")

    settings = profile_manager.get_profile_settings(pid, db_path=isolated_db)
    settings.voice.voice_name = "pt-BR-FranciscaNeural-Female"
    profile_manager.update_profile_settings(pid, settings, db_path=isolated_db)

    ctx = profile_manager.get_generation_profile_context(pid, db_path=isolated_db)
    assert ctx["voice_name"] == "pt-BR-FranciscaNeural"


def test_4_warmup_stored_generation_limit_5_clamps_to_2(isolated_db):
    """4. WARMUP + stored generation limit 5 => 2."""
    pid = profile_manager.DEFAULT_PROFILE_ID
    profile_manager.update_profile(pid, growth_mode=const.GROWTH_MODE_WARMUP, db_path=isolated_db)

    autonomous.set_max_generations_24h(5, profile_id=pid, db_path=isolated_db)
    assert autonomous.get_max_generations_24h(profile_id=pid, db_path=isolated_db) == 2


def test_5_warmup_stored_generation_limit_1_allows_1(isolated_db):
    """5. WARMUP + stored generation limit 1 => 1."""
    pid = profile_manager.DEFAULT_PROFILE_ID
    profile_manager.update_profile(pid, growth_mode=const.GROWTH_MODE_WARMUP, db_path=isolated_db)

    autonomous.set_max_generations_24h(1, profile_id=pid, db_path=isolated_db)
    assert autonomous.get_max_generations_24h(profile_id=pid, db_path=isolated_db) == 1


def test_6_warmup_stored_attempt_limit_15_clamps_to_8(isolated_db):
    """6. WARMUP + stored attempt limit 15 => 8."""
    pid = profile_manager.DEFAULT_PROFILE_ID
    profile_manager.update_profile(pid, growth_mode=const.GROWTH_MODE_WARMUP, db_path=isolated_db)

    autonomous.set_max_attempts_24h(15, profile_id=pid, db_path=isolated_db)
    assert autonomous.get_max_attempts_24h(profile_id=pid, db_path=isolated_db) == 8


def test_7_warmup_stored_attempt_limit_4_allows_4(isolated_db):
    """7. WARMUP + stored attempt limit 4 => 4."""
    pid = profile_manager.DEFAULT_PROFILE_ID
    profile_manager.update_profile(pid, growth_mode=const.GROWTH_MODE_WARMUP, db_path=isolated_db)

    autonomous.set_max_attempts_24h(4, profile_id=pid, db_path=isolated_db)
    assert autonomous.get_max_attempts_24h(profile_id=pid, db_path=isolated_db) == 4


def test_8_scale_respects_ceiling_5_15(isolated_db):
    """8. SCALE respeita teto 5/15: clamp acima do cap, permite abaixo."""
    scale_profile = profile_manager.create_profile(
        name="Canal Scale Teste",
        slug="canal-scale-teste",
        growth_mode=const.GROWTH_MODE_SCALE,
        db_path=isolated_db,
    )
    scale_pid = scale_profile["id"]

    # Generations: 10 clamped to 5; 3 allowed
    autonomous.set_max_generations_24h(10, profile_id=scale_pid, db_path=isolated_db)
    assert autonomous.get_max_generations_24h(profile_id=scale_pid, db_path=isolated_db) == 5

    autonomous.set_max_generations_24h(3, profile_id=scale_pid, db_path=isolated_db)
    assert autonomous.get_max_generations_24h(profile_id=scale_pid, db_path=isolated_db) == 3

    # Attempts: 20 clamped to 15; 10 allowed
    autonomous.set_max_attempts_24h(20, profile_id=scale_pid, db_path=isolated_db)
    assert autonomous.get_max_attempts_24h(profile_id=scale_pid, db_path=isolated_db) == 15

    autonomous.set_max_attempts_24h(10, profile_id=scale_pid, db_path=isolated_db)
    assert autonomous.get_max_attempts_24h(profile_id=scale_pid, db_path=isolated_db) == 10


def test_9_no_mutation_of_real_database(isolated_db):
    """9. Nenhum teste altera banco real: o caminho utilizado é estritamente o do tmp_path."""
    assert "test_autonomous_contract.db" in isolated_db
    # Operações executadas não tocam o caminho default
    default_db = profile_manager.get_db_path()
    assert default_db != isolated_db


def test_10_no_regression_in_autonomous_enable_disable(isolated_db):
    """10. Nenhuma regressão em autonomous enable/disable é introduzida."""
    pid = profile_manager.DEFAULT_PROFILE_ID
    # Inicialmente desligado
    assert autonomous.is_profile_autonomous_mode_enabled(pid, db_path=isolated_db) is False

    # Habilita
    autonomous.set_profile_autonomous_mode_enabled(pid, True, db_path=isolated_db)
    assert autonomous.is_profile_autonomous_mode_enabled(pid, db_path=isolated_db) is True

    # Desabilita
    autonomous.set_profile_autonomous_mode_enabled(pid, False, db_path=isolated_db)
    assert autonomous.is_profile_autonomous_mode_enabled(pid, db_path=isolated_db) is False
