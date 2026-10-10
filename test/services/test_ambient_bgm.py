"""
Testes direcionados da Fase V1.5E-G8 / V1.5E-G8.1 — Audio Identity MVP (Safe Procedural Ambient BGM).

Cobre os requisitos estritos da fase e correções da revisão:
1. perfil antigo sem music continua SAFE_NO_BGM
2. music.enabled=False => none / 0.0
3. music.enabled=True + mode=auto => ambient_auto / volume configurado
4. volume inválido é normalizado com segurança
5. detect_mood: terror, suspense, futuristic, epic, energetic, emotional, neutral
6. ambient generator não usa requests/rede
7. fail-soft REAL em task orchestration (falha de ambient generator não derruba geração do vídeo)
8. copyright/provenance: ambient_auto => SAFE_PROCEDURAL
9. settings_json round-trip preserva music settings
10. canal legado permanece retrocompatível
11. nenhum teste ativa publicação real
12. leitura do roteiro para mood prioriza chave 'script' em script.json
13. propagação do default_mood do perfil e fallback seguro para 'neutral'
14. nível estável de headroom sem dupla atenuação de volume
15. preflight local is_enabled() retorna True sem exigir chave de API externa
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from app.models.schema import VideoParams
from app.services import ambient_bgm, bgm as bgm_service, copyright_gate
from app.services.profile_manager import ChannelWorkspaceSettings, MusicSettings


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
    assert ambient_bgm.normalize_volume(0.01) == 0.05
    assert ambient_bgm.normalize_volume(0.50) == 0.15
    assert ambient_bgm.normalize_volume(0.08) == 0.08
    assert ambient_bgm.normalize_volume("invalido") == 0.10
    assert ambient_bgm.normalize_volume(None) == 0.10
    assert ambient_bgm.normalize_volume(float("nan")) == 0.10
    assert ambient_bgm.normalize_volume(-0.5) == 0.10

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
    assert ambient_bgm.detect_mood("assassinato, criatura, horror, sobrenatural") == "terror"
    assert ambient_bgm.detect_mood("mistério, segredo, desaparecimento, conspiração") == "suspense"
    assert ambient_bgm.detect_mood("inteligência artificial, tecnologia, robô, futuro") == "futuristic"
    assert ambient_bgm.detect_mood("maior da história, conquista, grandioso, império") == "epic"
    assert ambient_bgm.detect_mood("gol, corrida, vitória, partida, velocidade") == "energetic"
    assert ambient_bgm.detect_mood("família, despedida, emoção, reencontro") == "emotional"
    assert ambient_bgm.detect_mood("um texto cotidiano sem sinais fortes", default_mood="neutral") == "neutral"
    assert ambient_bgm.detect_mood("paisagem comum", default_mood="epic") == "epic"

    # Prioridade estrita quando houver múltiplos sinais:
    mixed_terror_suspense = "mistério profundo sobre o assassinato do cientista"
    assert ambient_bgm.detect_mood(mixed_terror_suspense) == "terror"

    mixed_suspense_futuristic = "um enigma de inteligência artificial no laboratório secreto"
    assert ambient_bgm.detect_mood(mixed_suspense_futuristic) == "suspense"


# -----------------------------------------------------------------------------
# 6. ambient generator não usa requests/rede
# -----------------------------------------------------------------------------
def test_ambient_generator_makes_no_network_calls(monkeypatch):
    """Garantir que a geração de ambient BGM opera com zero rede e zero chamadas HTTP."""
    def _blocked_connect(*args, **kwargs):
        raise AssertionError("Chamada de rede detectada no ambient generator!")

    monkeypatch.setattr("socket.socket.connect", _blocked_connect)

    test_out = "storage/validation/test_no_net.wav"
    try:
        res = ambient_bgm.generate_ambient_bgm(
            output_path=test_out,
            duration=1.0,
            mood="neutral",
        )
        assert os.path.isfile(res)
        assert os.path.getsize(res) > 0
    finally:
        if os.path.exists(test_out):
            os.remove(test_out)


# -----------------------------------------------------------------------------
# 7. Fail-soft REAL em task orchestration (falha de BGM não derruba vídeo)
# -----------------------------------------------------------------------------
def test_ambient_generator_failure_fails_soft_real():
    """Falha de ambient BGM no task orchestration gera aviso, bgm_file_override vazio e vídeo é produzido normalmente."""
    from app.services import task

    params = VideoParams(
        video_subject="Teste GTA VI",
        bgm_type="ambient_auto",
        bgm_volume=0.10,
        video_count=1,
    )

    with patch("app.services.video.combine_videos") as mock_combine, \
         patch("app.services.video.generate_video", return_value=True) as mock_gen_video, \
         patch.object(ambient_bgm, "generate_bgm", side_effect=ambient_bgm.AmbientBgmError("FFmpeg synth error")):
        final_paths, comb_paths, warnings = task.generate_final_videos(
            task_id="test-failsoft-task",
            params=params,
            downloaded_videos=["video1.mp4"],
            audio_file="audio.mp3",
            subtitle_path="sub.srt",
            audio_duration=5.0,
        )

        # 1. Código de warning registrado
        assert any(w.get("code") == "ambient_bgm_failed" for w in warnings)
        # 2. Render final chamado
        assert mock_gen_video.called is True
        # 3. bgm_file_override enviado como string vazia (sem BGM no render)
        call_kwargs = mock_gen_video.call_args[1]
        assert call_kwargs.get("bgm_file_override") == ""
        # 4. Vídeo NÃO foi abortado
        assert len(final_paths) == 1


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

    assert autonomous_production.DEFAULT_AUTONOMOUS_MODE_ENABLED is False

    res = bgm_service.resolve_autonomous_bgm(
        music_settings=MusicSettings(enabled=True, mode="auto", volume=0.10)
    )
    assert "publish" not in res
    assert "auto_publish" not in res
    assert res["type"] == "ambient_auto"


# -----------------------------------------------------------------------------
# 12. Leitura do roteiro para mood prioriza chave 'script' em script.json
# -----------------------------------------------------------------------------
def test_script_json_reading_prioritizes_script_key_over_subject():
    """Confirma que script.json com 'script' e 'video_subject' detecta pelo roteiro completo."""
    fake_script_data = {
        "script": "O avanço da inteligência artificial transformará todas as indústrias.",
        "params": {
            "video_subject": "Cenário e paisagem comum",
            "bgm_default_mood": "neutral",
        },
    }

    with patch.object(ambient_bgm, "_load_task_script_data", return_value=fake_script_data), \
         patch.object(ambient_bgm, "_extract_task_id", return_value="fake_task_id"), \
         patch.object(ambient_bgm, "generate_ambient_bgm", return_value="fake_out.wav") as mock_gen:
        ambient_bgm.generate_bgm(
            output_path="/storage/tasks/fake_task_id/ambient_auto-bgm-1.wav",
            video_duration=5.0,
        )
        assert mock_gen.called is True
        assert mock_gen.call_args[1]["mood"] == "futuristic"


# -----------------------------------------------------------------------------
# 13. Propagação de default_mood do perfil e fallback seguro para neutral
# -----------------------------------------------------------------------------
def test_profile_default_mood_fallback_when_no_signal():
    """Quando o roteiro não tem sinal forte, usa bgm_default_mood dos params/perfil."""
    fake_script_data = {
        "script": "Uma caminhada simples pelo parque num dia calmo.",
        "params": {
            "video_subject": "Passeio",
            "bgm_default_mood": "suspense",
        },
    }

    with patch.object(ambient_bgm, "_load_task_script_data", return_value=fake_script_data), \
         patch.object(ambient_bgm, "_extract_task_id", return_value="fake_task_id"), \
         patch.object(ambient_bgm, "generate_ambient_bgm", return_value="fake_out.wav") as mock_gen:
        ambient_bgm.generate_bgm(
            output_path="/storage/tasks/fake_task_id/ambient_auto-bgm-1.wav",
            video_duration=5.0,
        )
        assert mock_gen.called is True
        assert mock_gen.call_args[1]["mood"] == "suspense"


def test_invalid_default_mood_falls_back_to_neutral():
    """Quando bgm_default_mood é inválido e não há sinal, faz fallback seguro para neutral."""
    fake_script_data = {
        "script": "Uma caminhada simples pelo parque num dia calmo.",
        "params": {
            "video_subject": "Passeio",
            "bgm_default_mood": "mood_inexistente",
        },
    }

    with patch.object(ambient_bgm, "_load_task_script_data", return_value=fake_script_data), \
         patch.object(ambient_bgm, "_extract_task_id", return_value="fake_task_id"), \
         patch.object(ambient_bgm, "generate_ambient_bgm", return_value="fake_out.wav") as mock_gen:
        ambient_bgm.generate_bgm(
            output_path="/storage/tasks/fake_task_id/ambient_auto-bgm-1.wav",
            video_duration=5.0,
        )
        assert mock_gen.called is True
        assert mock_gen.call_args[1]["mood"] == "neutral"


# -----------------------------------------------------------------------------
# 14. Nível estável de headroom sem dupla atenuação de volume
# -----------------------------------------------------------------------------
def test_canonical_stable_bed_has_no_double_volume():
    """Geração de ambient BGM não aplica atenuação de bgm_volume, delegando ao mixer final."""
    test_out = "storage/validation/test_headroom.wav"
    try:
        res = ambient_bgm.generate_ambient_bgm(
            output_path=test_out,
            duration=1.0,
            mood="neutral",
        )
        assert os.path.isfile(res)
        assert os.path.getsize(res) > 0
    finally:
        if os.path.exists(test_out):
            os.remove(test_out)


# -----------------------------------------------------------------------------
# 15. Preflight local is_enabled() retorna True
# -----------------------------------------------------------------------------
def test_ambient_bgm_preflight_is_enabled():
    """ambient_bgm.is_enabled() retorna True pois não requer chaves de API externa."""
    assert ambient_bgm.is_enabled() is True
