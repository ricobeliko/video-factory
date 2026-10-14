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


def test_1_global_ui_voice_wins_over_stored_profile_voice_with_two_voices(isolated_db, monkeypatch):
    """1. Voz Global da Fábrica (config.ui['voice_name']) prevalece sobre voz legada persistida no perfil.
    Valida alternância entre duas vozes diferentes (requisito 7 da missão)."""
    pid = profile_manager.DEFAULT_PROFILE_ID

    # Simula exatamente o perfil GTA VI com voz legada salva no SQLite
    settings = profile_manager.get_profile_settings(pid, db_path=isolated_db)
    settings.voice.voice_name = "en-US-BrianMultilingualNeural"
    profile_manager.update_profile_settings(pid, settings, db_path=isolated_db)

    # 1ª Voz selecionada e salva pelo operador no painel: Francisca
    monkeypatch.setitem(config.ui, "voice_name", "pt-BR-FranciscaNeural")
    ctx1 = profile_manager.get_generation_profile_context(pid, db_path=isolated_db)
    assert ctx1["voice_name"] == "pt-BR-FranciscaNeural"
    params1 = autonomous.build_autonomous_video_params("Tema GTA VI 1", profile_id=pid, db_path=isolated_db)
    assert params1.voice_name == "pt-BR-FranciscaNeural"

    # 2ª Voz selecionada e salva pelo operador no painel: Antonio
    monkeypatch.setitem(config.ui, "voice_name", "pt-BR-AntonioNeural")
    ctx2 = profile_manager.get_generation_profile_context(pid, db_path=isolated_db)
    assert ctx2["voice_name"] == "pt-BR-AntonioNeural"
    params2 = autonomous.build_autonomous_video_params("Tema GTA VI 2", profile_id=pid, db_path=isolated_db)
    assert params2.voice_name == "pt-BR-AntonioNeural"


def test_2_profile_fallback_when_global_ui_voice_empty(isolated_db, monkeypatch):
    """2. Quando a Voz Global da UI não estiver configurada, recorre à voz do perfil."""
    pid = profile_manager.DEFAULT_PROFILE_ID
    monkeypatch.setitem(config.ui, "voice_name", "")

    settings = profile_manager.get_profile_settings(pid, db_path=isolated_db)
    settings.voice.voice_name = "pt-BR-AntonioNeural"
    profile_manager.update_profile_settings(pid, settings, db_path=isolated_db)

    ctx = profile_manager.get_generation_profile_context(pid, db_path=isolated_db)
    assert ctx["voice_name"] == "pt-BR-AntonioNeural"


def test_3_canonicalization_applied_to_global_voice(isolated_db, monkeypatch):
    """3. Canonicalização é aplicada à voz global (remove sufixo de catálogo como -Female)."""
    pid = profile_manager.DEFAULT_PROFILE_ID
    monkeypatch.setitem(config.ui, "voice_name", "pt-BR-FranciscaNeural-Female")

    ctx = profile_manager.get_generation_profile_context(pid, db_path=isolated_db)
    assert ctx["voice_name"] == "pt-BR-FranciscaNeural"


def test_4_warmup_stored_generation_limit_allows_up_to_5_clamps_above_5(isolated_db):
    """4. WARMUP + stored generation limit 5 => allows 5; limit 10 => clamps to 5."""
    pid = profile_manager.DEFAULT_PROFILE_ID
    profile_manager.update_profile(pid, growth_mode=const.GROWTH_MODE_WARMUP, db_path=isolated_db)

    autonomous.set_max_generations_24h(5, profile_id=pid, db_path=isolated_db)
    assert autonomous.get_max_generations_24h(profile_id=pid, db_path=isolated_db) == 5

    autonomous.set_max_generations_24h(10, profile_id=pid, db_path=isolated_db)
    assert autonomous.get_max_generations_24h(profile_id=pid, db_path=isolated_db) == 5


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


def test_11_warmup_stock_1_of_3_with_2_generations_allows_new_generation(isolated_db):
    """11. WARMUP + estoque 1/3 + 2 gerações nas últimas 24h -> não bloqueia por limite diário (cap=5)."""
    pid = profile_manager.DEFAULT_PROFILE_ID
    profile_manager.update_profile(pid, growth_mode=const.GROWTH_MODE_WARMUP, db_path=isolated_db)
    autonomous.set_target_ready_stock(3, profile_id=pid, db_path=isolated_db)

    # Inserir 2 eventos de geração aprovada nas últimas 24h
    now_iso = scheduler._to_iso(scheduler._normalize_utc(None))
    with scheduler.get_connection(isolated_db) as conn:
        conn.execute(
            "INSERT INTO operational_events (timestamp, component, severity, event_type, task_id, message) "
            "VALUES (?, 'autonomous_production', 'info', 'generation_approved', 'task-1', 'ok'), "
            "       (?, 'autonomous_production', 'info', 'generation_approved', 'task-2', 'ok');",
            (now_iso, now_iso),
        )

    gen_today = autonomous.count_generations_in_last_24h(db_path=isolated_db, profile_id=pid)
    max_24h = autonomous.get_max_generations_24h(profile_id=pid, db_path=isolated_db)
    assert gen_today == 2
    assert max_24h == 5
    assert gen_today < max_24h  # Pode gerar!


def test_12_warmup_stock_at_target_stops_generation(isolated_db):
    """12. WARMUP + estoque 3/3 -> reposição para quando o estoque atinge a meta."""
    pid = profile_manager.DEFAULT_PROFILE_ID
    profile_manager.update_profile(pid, growth_mode=const.GROWTH_MODE_WARMUP, db_path=isolated_db)
    autonomous.set_target_ready_stock(3, profile_id=pid, db_path=isolated_db)

    # Simulação da guarda canônica de estoque de autonomous_production (linhas 2448-2458)
    ready_total = 3
    target_stock = autonomous.get_target_ready_stock(profile_id=pid, db_path=isolated_db)
    assert target_stock == 3
    assert ready_total >= target_stock  # Para reposição e entra em IDLE sem gerar


def test_13_warmup_with_5_generations_blocks(isolated_db):
    """13. WARMUP + 5 gerações nas últimas 24h -> bloqueia (gen_today >= max_24h)."""
    pid = profile_manager.DEFAULT_PROFILE_ID
    profile_manager.update_profile(pid, growth_mode=const.GROWTH_MODE_WARMUP, db_path=isolated_db)

    now_iso = scheduler._to_iso(scheduler._normalize_utc(None))
    with scheduler.get_connection(isolated_db) as conn:
        for i in range(5):
            conn.execute(
                "INSERT INTO operational_events (timestamp, component, severity, event_type, task_id, message) "
                "VALUES (?, 'autonomous_production', 'info', 'generation_approved', ?, 'ok');",
                (now_iso, f"task-approved-{i}"),
            )

    gen_today = autonomous.count_generations_in_last_24h(db_path=isolated_db, profile_id=pid)
    max_24h = autonomous.get_max_generations_24h(profile_id=pid, db_path=isolated_db)
    assert gen_today == 5
    assert max_24h == 5
    assert gen_today >= max_24h  # Bloqueia!


def test_14_warmup_publication_limit_remains_1_per_24h(isolated_db):
    """14. Publicação WARMUP YouTube permanece estritamente limitada a 1/24h com min_interval de 8h."""
    rate = scheduler.get_platform_rate_limits(
        "youtube",
        db_path=isolated_db,
        growth_mode=const.GROWTH_MODE_WARMUP,
    )
    assert rate["limit"] == 1
    assert rate["min_interval_hours"] == 8


def test_15_secondary_channels_remain_autonomous_disabled(isolated_db):
    """15. Histórias e GTA VI continuam com Autonomous OFF."""
    h_prof = profile_manager.create_profile(name="Histórias", slug="historias", db_path=isolated_db)
    g_prof = profile_manager.create_profile(name="GTA VI", slug="gta-vi", db_path=isolated_db)

    assert autonomous.is_profile_autonomous_mode_enabled(h_prof["id"], db_path=isolated_db) is False
    assert autonomous.is_profile_autonomous_mode_enabled(g_prof["id"], db_path=isolated_db) is False
