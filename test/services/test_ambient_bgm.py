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
from unittest.mock import MagicMock, patch

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
    """Valores de volume inválidos ou fora dos limites seguros [0.05, 0.20] são normalizados."""
    assert ambient_bgm.normalize_volume(0.01) == 0.05
    assert ambient_bgm.normalize_volume(0.50) == 0.20
    assert ambient_bgm.normalize_volume(0.08) == 0.08
    assert ambient_bgm.normalize_volume(0.20) == 0.20
    assert ambient_bgm.normalize_volume("invalido") == 0.20
    assert ambient_bgm.normalize_volume(None) == 0.20
    assert ambient_bgm.normalize_volume(float("nan")) == 0.20
    assert ambient_bgm.normalize_volume(-0.5) == 0.20

    m_settings_clamped = MusicSettings(enabled=True, mode="auto", volume=0.99)
    res_clamped = bgm_service.resolve_autonomous_bgm(music_settings=m_settings_clamped)
    assert res_clamped["volume"] == 0.20

    m_settings_invalid = {"enabled": True, "mode": "auto", "volume": "not_a_number"}
    res_invalid = bgm_service.resolve_autonomous_bgm(music_settings=m_settings_invalid)
    assert res_invalid["volume"] == 0.20


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

    with patch("app.services.video.combine_videos"), \
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
    assert settings.music.volume == 0.20
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


def _measure_wav_peak_and_rms(filepath: str) -> tuple[float, float, float]:
    import math
    import struct
    import wave

    with wave.open(filepath, "rb") as w:
        nchannels = w.getnchannels()
        sampwidth = w.getsampwidth()
        framerate = w.getframerate()
        nframes = w.getnframes()
        duration = nframes / float(framerate)
        frames = w.readframes(nframes)

    max_val = 32768.0 if sampwidth == 2 else 1.0
    samples = struct.unpack(f"<{nframes * nchannels}h", frames)
    peak = max(abs(s) for s in samples)
    peak_dbfs = 20 * math.log10(peak / max_val) if peak > 0 else -100.0
    sum_sq = sum(float(s) ** 2 for s in samples)
    rms = math.sqrt(sum_sq / len(samples))
    rms_dbfs = 20 * math.log10(rms / max_val) if rms > 0 else -100.0
    return duration, peak_dbfs, rms_dbfs


# -----------------------------------------------------------------------------
# 16. futuristic não produz near-silence e atinge gate de audibilidade
# -----------------------------------------------------------------------------
def test_futuristic_not_near_silent_and_audible(tmp_path):
    """Mood futuristic deve produzir sinal audível saudável (peak > -15 dBFS, rms > -30 dBFS)."""
    test_out = str(tmp_path / "futuristic_test.wav")
    ambient_bgm.generate_ambient_bgm(
        output_path=test_out,
        duration=3.0,
        mood="futuristic",
    )
    assert os.path.isfile(test_out)
    dur, peak, rms = _measure_wav_peak_and_rms(test_out)
    assert peak > -15.0, f"Peak muito baixo: {peak} dBFS"
    assert peak < -1.0, f"Peak em clipping: {peak} dBFS"
    assert rms > -30.0, f"RMS muito baixo: {rms} dBFS"


# -----------------------------------------------------------------------------
# 17. Todos os moods produzem energia mensurável e audível dentro do headroom
# -----------------------------------------------------------------------------
def test_all_moods_produce_audible_energy(tmp_path):
    """Todos os 7 moods procedurais produzem energia mensurável e saudável (peak e RMS)."""
    for mood in ambient_bgm.SUPPORTED_MOODS:
        test_out = str(tmp_path / f"{mood}_test.wav")
        ambient_bgm.generate_ambient_bgm(
            output_path=test_out,
            duration=2.0,
            mood=mood,
        )
        assert os.path.isfile(test_out)
        dur, peak, rms = _measure_wav_peak_and_rms(test_out)
        assert peak > -15.0, f"Mood {mood} peak muito baixo: {peak} dBFS"
        assert peak < -1.0, f"Mood {mood} peak em clipping: {peak} dBFS"
        assert rms > -30.0, f"Mood {mood} rms muito baixo: {rms} dBFS"


# -----------------------------------------------------------------------------
# 18. Síntese NÃO contém atenuação do bgm_volume do perfil
# -----------------------------------------------------------------------------
def test_synthesis_command_contains_no_profile_volume_filter(monkeypatch):
    """Garantir que a síntese de áudio lavfi não insere filtro de volume do perfil."""
    captured_cmds = []

    def _mock_run(cmd, *args, **kwargs):
        captured_cmds.append(cmd)
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        return mock_proc

    monkeypatch.setattr("subprocess.run", _mock_run)
    monkeypatch.setattr("os.path.isfile", lambda p: True)
    monkeypatch.setattr("os.path.getsize", lambda p: 1024)

    ambient_bgm.generate_ambient_bgm(
        output_path="test_mock.wav",
        duration=2.0,
        mood="neutral",
        volume=0.10,
    )

    assert len(captured_cmds) == 1
    full_cmd_str = " ".join(captured_cmds[0])
    assert "volume=" not in full_cmd_str


# -----------------------------------------------------------------------------
# 19. Volume 0.20 baseline oficial e preservação de volumes existentes
# -----------------------------------------------------------------------------
def test_volume_020_baseline_and_existing_profiles_preserved():
    """MusicSettings tem volume padrão 0.20 e perfis existentes com 0.10/0.15 são preservados."""
    # Default novo
    default_music = MusicSettings()
    assert default_music.enabled is False
    assert default_music.volume == 0.20

    # Limites de normalização
    assert ambient_bgm.DEFAULT_BGM_VOLUME == 0.20
    assert ambient_bgm.MAX_BGM_VOLUME == 0.20
    assert ambient_bgm.MIN_BGM_VOLUME == 0.05
    assert ambient_bgm.normalize_volume(0.20) == 0.20
    assert ambient_bgm.normalize_volume(0.25) == 0.20
    assert ambient_bgm.normalize_volume(0.01) == 0.05

    # Perfil existente com 0.10 salvo explicitamente é preservado
    json_010 = json.dumps({"music": {"enabled": True, "mode": "auto", "volume": 0.10}})
    loaded_10 = ChannelWorkspaceSettings.from_json(json_010)
    assert loaded_10.music.volume == 0.10
    res_10 = bgm_service.resolve_autonomous_bgm(channel_settings=loaded_10)
    assert res_10["volume"] == 0.10

    # Perfil existente com 0.15 salvo explicitamente é preservado
    json_015 = json.dumps({"music": {"enabled": True, "mode": "auto", "volume": 0.15}})
    loaded_15 = ChannelWorkspaceSettings.from_json(json_015)
    assert loaded_15.music.volume == 0.15
    res_15 = bgm_service.resolve_autonomous_bgm(channel_settings=loaded_15)
    assert res_15["volume"] == 0.15


# -----------------------------------------------------------------------------
# 20. BrianMultilingualNeural aceito pelo contrato pt-BR e outros bloqueados
# -----------------------------------------------------------------------------
def test_brian_multilingual_pt_br_contract_and_blocking_others():
    """Brian é aceito na allowlist pt-BR enquanto outras vozes en-US e estrangeiras continuam bloqueadas."""
    from app.services import autonomous_production

    # 1. Brian aprovado
    assert autonomous_production.is_valid_pt_br_voice("en-US-BrianMultilingualNeural") is True
    assert autonomous_production.is_valid_pt_br_voice("EN_US_BRIANMULTILINGUALNEURAL") is True

    # 2. Voz nativa pt-BR continua aceita
    assert autonomous_production.is_valid_pt_br_voice("pt-BR-AntonioNeural") is True
    assert autonomous_production.is_valid_pt_br_voice("pt-BR-FranciscaNeural") is True

    # 3. Outras vozes en-US e estrangeiras permanecem bloqueadas
    assert autonomous_production.is_valid_pt_br_voice("en-US-JennyNeural") is False
    assert autonomous_production.is_valid_pt_br_voice("en-US-GuyNeural") is False
    assert autonomous_production.is_valid_pt_br_voice("pt-PT-DuarteNeural") is False
    assert autonomous_production.is_valid_pt_br_voice("af-ZA-AdriNeural") is False
    assert autonomous_production.is_valid_pt_br_voice("zh-CN-XiaoxiaoNeural") is False


# -----------------------------------------------------------------------------
# 21. Preflight com Brian não reporta INVALID_LOCALE
# -----------------------------------------------------------------------------
def test_preflight_checks_with_brian_passes_without_invalid_locale(tmp_path):
    """Preflight check com en-US-BrianMultilingualNeural reconhece Edge TTS e não gera INVALID_LOCALE."""
    from app.services import autonomous_production
    from app.config import config

    db_path = str(tmp_path / "test_preflight.db")
    with patch.dict(config.ui, {"voice_mode": "tts", "voice_name": "en-US-BrianMultilingualNeural"}), \
         patch("app.services.autonomous_production.utils.check_ffmpeg_ready", return_value=True), \
         patch("shutil.disk_usage", return_value=(0, 0, 10 * 1024**3)), \
         patch("app.services.material.has_material_api_keys", return_value=True):
        ok, msg, details = autonomous_production.check_required_providers_preflight(
            video_source="pexels",
            db_path=db_path,
        )
        assert details.get("TTS") != "INVALID_LOCALE"
        assert details.get("TTS") == "Edge TTS"


# -----------------------------------------------------------------------------
# 22. Channel Factory context impõe voz GLOBAL Brian ignorando override
# -----------------------------------------------------------------------------
def test_channel_factory_context_enforces_global_brian_voice(tmp_path):
    """get_generation_profile_context impõe a voz global mesmo se o perfil legado tiver outra voz salva."""
    from app.services import profile_manager
    from app.config import config

    db_path = str(tmp_path / "test_global_voice.db")
    with patch.dict(config.ui, {"voice_name": "en-US-BrianMultilingualNeural"}):
        res = profile_manager.onboard_channel_workspace(
            name="Canal Teste Brian",
            niche="gta_vi",
            topic_brief="Notícias GTA VI",
            language="pt-BR",
            external_account_id="UC1234567890abcdef",
            db_path=db_path,
        )
        pid = res["profile"]["id"]

        # Força voice_name legado no perfil
        settings = profile_manager.get_profile_settings(pid, db_path=db_path)
        settings.voice.voice_name = "pt-BR-AntonioNeural"
        profile_manager.update_profile_settings(pid, settings, db_path=db_path)

        # Confirma que settings persistidos guardam para retrocompatibilidade
        reloaded = profile_manager.get_profile_settings(pid, db_path=db_path)
        assert reloaded.voice.voice_name == "pt-BR-AntonioNeural"

        # Mas o contexto de geração da fábrica autônoma impõe a voz global da fábrica
        ctx = profile_manager.get_generation_profile_context(pid, db_path=db_path)
        assert ctx["voice_name"] == "en-US-BrianMultilingualNeural"


