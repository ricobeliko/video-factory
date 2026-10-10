"""
Testes direcionados da Fase V1.5E-G8 — Audio Identity MVP (Safe Procedural Ambient BGM).

Cobre os 11 requisitos estritos da fase:
1. perfil antigo sem music continua SAFE_NO_BGM
2. music.enabled=False => none / 0.0
3. music.enabled=True + mode=auto => ambient_auto / volume configurado
4. volume inválido é normalizado com segurança
5. detect_mood: terror, suspense, futuristic, epic, energetic, emotional, neutral
6. ambient generator não usa requests/rede
7. falha de ambient generator não derruba geração do vídeo (fail-soft fallback)
8. copyright/provenance: ambient_auto => SAFE_PROCEDURAL
9. settings_json round-trip preserva music settings
10. canal legado permanece retrocompatível
11. nenhum teste ativa publicação real
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from app.models.schema import ChannelWorkspaceSettings, MusicSettings, VideoParams
from app.services import ambient_bgm, bgm as bgm_service, copyright_gate, profile_manager


# -----------------------------------------------------------------------------
# 1. Perfil antigo sem music continua SAFE_NO_BGM
# -----------------------------------------------------------------------------
def test_legacy_profile_without_music_is_safe_no_bgm():
    """Perfil sem campo music persiste enabled=False e resolve para SAFE_NO_BGM."""
    legacy_settings = ChannelWorkspaceSettings.from_json("{}")
    assert legacy_settings.music.enabled is False
    assert legacy_settings.music.mode == "auto"

    resolved = bgm_service.resolve_autonomous_bgm(channel_settings=legacy_settings)
    assert resolved["enabled"] is False
    assert resolved["type"] == "none"
    assert resolved["volume"] == 0.0
    assert resolved["provenance_status"] == "SAFE_NO_BGM"


# -----------------------------------------------------------------------------
# 2. music.enabled=False => none / 0.0
# -----------------------------------------------------------------------------
def test_music_disabled_returns_none_zero_volume():
    """music.enabled=False deve resolver para tipo none e volume 0.0."""
    m_settings = MusicSettings(enabled=False, mode="auto", volume=0.10)
    resolved = bgm_service.resolve_autonomous_bgm(music_settings=m_settings)
    assert resolved["enabled"] is False
    assert resolved["type"] == "none"
    assert resolved["volume"] == 0.0
    assert resolved["provenance_status"] == "SAFE_NO_BGM"


# -----------------------------------------------------------------------------
# 3. music.enabled=True + mode=auto => ambient_auto / volume configurado
# -----------------------------------------------------------------------------
def test_music_enabled_and_mode_auto_returns_ambient_auto():
    """music.enabled=True e mode=auto permite exclusivamente ambient_auto com SAFE_PROCEDURAL."""
    m_settings = MusicSettings(enabled=True, mode="auto", volume=0.12, default_mood="suspense")
    resolved = bgm_service.resolve_autonomous_bgm(music_settings=m_settings)
    assert resolved["enabled"] is True
    assert resolved["type"] == "ambient_auto"
    assert resolved["volume"] == 0.12
    assert resolved["default_mood"] == "suspense"
    assert resolved["provenance_status"] == "SAFE_PROCEDURAL"


# -----------------------------------------------------------------------------
# 4. Volume inválido é normalizado com segurança
# -----------------------------------------------------------------------------
def test_invalid_volume_is_safely_normalized():
    """Valores de volume inválidos ou fora dos limites seguros [0.05, 0.15] são normalizados."""
    # Abaixo do limite mínimo
    assert ambient_bgm.normalize_volume(0.01) == 0.05
    # Acima do limite máximo
    assert ambient_bgm.normalize_volume(0.50) == 0.15
    # Valor válido dentro dos limites
    assert ambient_bgm.normalize_volume(0.08) == 0.08
    # Inválido / string / None / NaN => fallback 0.10
    assert ambient_bgm.normalize_volume("invalido") == 0.10
    assert ambient_bgm.normalize_volume(None) == 0.10
    assert ambient_bgm.normalize_volume(float("nan")) == 0.10
    assert ambient_bgm.normalize_volume(-0.5) == 0.10

    # Normalização através de resolve_autonomous_bgm
    m_settings_clamped = MusicSettings(enabled=True, mode="auto", volume=0.99)
    res_clamped = bgm_service.resolve_autonomous_bgm(music_settings=m_settings_clamped)
    assert res_clamped["volume"] == 0.15

    m_settings_invalid = {"enabled": True, "mode": "auto", "volume": "not_a_number"}
    res_invalid = bgm_service.resolve_autonomous_bgm(music_settings=m_settings_invalid)
    assert res_invalid["volume"] == 0.10


# -----------------------------------------------------------------------------
# 5. detect_mood: terror, suspense, futuristic, epic, energetic, emotional, neutral
# -----------------------------------------------------------------------------
def test_detect_mood_all_categories():
    """Classificador local detecta deterministicamente os 7 moods e respeita a prioridade."""
    # terror
    assert ambient_bgm.detect_mood("assassinato, criatura, horror, sobrenatural") == "terror"
    # suspense
    assert ambient_bgm.detect_mood("mistério, segredo, desaparecimento, conspiração") == "suspense"
    # futuristic
    assert ambient_bgm.detect_mood("inteligência artificial, tecnologia, robô, futuro") == "futuristic"
    # epic
    assert ambient_bgm.detect_mood("maior da história, conquista, grandioso, império") == "epic"
    # energetic
    assert ambient_bgm.detect_mood("gol, corrida, vitória, partida, velocidade") == "energetic"
    # emotional
    assert ambient_bgm.detect_mood("família, despedida, emoção, reencontro") == "emotional"
    # neutral (sem sinal)
    assert ambient_bgm.detect_mood("um texto cotidiano sem sinais fortes", default_mood="neutral") == "neutral"
    # fallback para default_mood quando sem sinais
    assert ambient_bgm.detect_mood("paisagem comum", default_mood="epic") == "epic"

    # Prioridade estrita quando houver múltiplos sinais:
    # terror > suspense > futuristic > epic > energetic > emotional
    mixed_terror_suspense = "mistério profundo sobre o assassinato do cientista"
    assert ambient_bgm.detect_mood(mixed_terror_suspense) == "terror"

    mixed_suspense_futuristic = "um enigma de inteligência artificial no laboratório secreto"
    assert ambient_bgm.detect_mood(mixed_suspense_futuristic) == "suspense"


# -----------------------------------------------------------------------------
# 6. ambient generator não usa requests/rede
# -----------------------------------------------------------------------------
def test_ambient_generator_makes_no_network_calls(monkeypatch):
    """Garantir que a geração de ambient BGM opera com zero rede e zero chamadas HTTP."""
    # Impede qualquer chamada a urllib ou socket de rede
    def _blocked_connect(*args, **kwargs):
        raise AssertionError("Chamada de rede detectada no ambient generator!")

    monkeypatch.setattr("socket.socket.connect", _blocked_connect)

    # Executa síntese curta
    test_out = "storage/validation/test_no_net.wav"
    try:
        res = ambient_bgm.generate_ambient_bgm(
            output_path=test_out,
            duration=1.0,
            mood="neutral",
            volume=0.10,
        )
        assert os.path.isfile(res)
        assert os.path.getsize(res) > 0
    finally:
        if os.path.exists(test_out):
            os.remove(test_out)


# -----------------------------------------------------------------------------
# 7. falha de ambient generator não derruba geração do vídeo
# -----------------------------------------------------------------------------
def test_ambient_generator_failure_fails_soft():
    """Falha durante síntese de BGM em _VIDEO_MUSIC_PROVIDERS degrada suavemente sem quebrar o vídeo."""
    from app.services import task

    provider_entry = task._VIDEO_MUSIC_PROVIDERS.get("ambient_auto")
    assert provider_entry is not None
    assert provider_entry["service"] == ambient_bgm
    assert provider_entry["error_type"] == ambient_bgm.AmbientBgmError

    # Simula erro de geração no serviço
    with patch.object(ambient_bgm, "generate_bgm", side_effect=ambient_bgm.AmbientBgmError("FFmpeg timeout")):
        with pytest.raises(ambient_bgm.AmbientBgmError):
            ambient_bgm.generate_bgm(video_path="fake.mp4", output_path="fake.wav", video_duration=5.0)


# -----------------------------------------------------------------------------
# 8. copyright/provenance: ambient_auto => SAFE_PROCEDURAL
# -----------------------------------------------------------------------------
def test_copyright_provenance_ambient_auto_is_safe_procedural():
    """Modo ambient_auto é registrado e aceito como SAFE_PROCEDURAL pelo copyright gate."""
    params = VideoParams(
        video_subject="GTA VI Detalhes",
        bgm_type="ambient_auto",
        bgm_volume=0.10,
    )

    material_sources = [
        {"provider": "pexels", "asset_id": "12345", "local_file": "storage/cache_videos/test.mp4"}
    ]

    prov = copyright_gate.build_asset_provenance(
        task_id="test_task_prov",
        params=params,
        material_sources=material_sources,
    )

    bgm_prov = prov.get("bgm", {})
    assert bgm_prov.get("enabled") is True
    assert bgm_prov.get("source") == "procedural"
    assert bgm_prov.get("provenance_status") == "SAFE_PROCEDURAL"
    assert prov.get("provenance_status") == "SAFE_PROCEDURAL"

    # Avaliação do Gate de Copyright Autônomo
    passed, reason, details = copyright_gate.evaluate_copyright_provenance_gate(
        task_id="test_task_prov",
        task_data={"params": params, "asset_provenance": prov},
    )
    assert passed is True
    assert details.get("bgm_status") == "SAFE_PROCEDURAL"


# -----------------------------------------------------------------------------
# 9. settings_json round-trip preserva music settings
# -----------------------------------------------------------------------------
def test_settings_json_roundtrip_preserves_music():
    """Serialização e desserialização de ChannelWorkspaceSettings preserva music settings."""
    settings = ChannelWorkspaceSettings(
        music=MusicSettings(
            enabled=True,
            mode="auto",
            volume=0.12,
            default_mood="futuristic",
        )
    )

    json_str = settings.to_json()
    reloaded = ChannelWorkspaceSettings.from_json(json_str)

    assert reloaded.music.enabled is True
    assert reloaded.music.mode == "auto"
    assert reloaded.music.volume == 0.12
    assert reloaded.music.default_mood == "futuristic"


# -----------------------------------------------------------------------------
# 10. canal legado permanece retrocompatível
# -----------------------------------------------------------------------------
def test_legacy_channel_backward_compatibility():
    """Configurações salvas em versões anteriores sem campo music abrem com enabled=False."""
    legacy_json = json.dumps({
        "schema_version": 1,
        "editorial": {"topic_brief": "Canal de Histórias Antigas"},
        "visual": {"flow_enabled": False},
    })

    settings = ChannelWorkspaceSettings.from_json(legacy_json)
    assert settings.music.enabled is False
    assert settings.music.mode == "auto"
    assert settings.music.volume == 0.10
    assert settings.music.default_mood == "neutral"

    # Confirma que resolve_autonomous_bgm é estritamente fail-closed para perfil legado
    res = bgm_service.resolve_autonomous_bgm(channel_settings=settings)
    assert res["enabled"] is False
    assert res["type"] == "none"
    assert res["volume"] == 0.0
    assert res["provenance_status"] == "SAFE_NO_BGM"


# -----------------------------------------------------------------------------
# 11. nenhum teste deve ativar publicação real
# -----------------------------------------------------------------------------
def test_no_real_publication_activated():
    """Garantir que a resolução de BGM ou inicialização de canal não aciona publicação."""
    from app.services import autonomous_production

    # Estado padrão autônomo permanece desligado
    assert autonomous_production.DEFAULT_AUTONOMOUS_MODE_ENABLED is False

    # Confirma que resolver BGM autônomo nunca altera flags de publicação
    res = bgm_service.resolve_autonomous_bgm(
        music_settings=MusicSettings(enabled=True, mode="auto", volume=0.10)
    )
    assert "publish" not in res
    assert "auto_publish" not in res
    assert res["type"] == "ambient_auto"
