"""
Testes direcionados para V14-C.2 — Expressive Presenter + Subtitle Interaction.

Cobertura estrita dos 15 requisitos:
1. SRT gera timeline temporal válida
2. talking_1/talking_2 alternam deterministicamente
3. surprise keyword → surprised
4. theory keyword → thinking
5. serious keyword → serious
6. CTA → cta/pointing
7. bottom_right aponta para esquerda
8. bottom_left aponta para direita
9. modo mistério usa comportamento contido
10. eventos não ultrapassam presenter segments
11. eventos não se sobrepõem invalidamente
12. pose ausente usa fallback
13. SRT inválido tem fallback seguro
14. autonomous presenter permanece OFF
15. nenhuma rede/API/publicação
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.models import const
from app.models.schema import VideoParams
from app.services import autonomous_production
from app.services import presenter


SAMPLE_SRT = """1
00:00:00,500 --> 00:00:02,800
Você sabia que a morte dele foi um acidente trágico?

2
00:00:03,000 --> 00:00:04,500
Isso é inacreditável e chocante!

3
00:00:14,500 --> 00:00:17,000
Uma nova teoria pode trazer a explicação.

4
00:00:36,000 --> 00:00:39,000
Inscreva-se no canal e deixa nos comentários!
"""


def test_1_srt_timeline_parser_produces_valid_timeline():
    """1. SRT gera timeline temporal válida."""
    subtitles = presenter.parse_srt_timeline(SAMPLE_SRT)
    assert len(subtitles) == 4
    assert subtitles[0]["start"] == 0.5
    assert subtitles[0]["end"] == 2.8
    assert "morte" in subtitles[0]["text"]
    assert subtitles[1]["start"] == 3.0
    assert subtitles[1]["end"] == 4.5
    assert subtitles[2]["start"] == 14.5
    assert subtitles[3]["start"] == 36.0

    # Testa parsing a partir de arquivo em disco
    with tempfile.NamedTemporaryFile("w", suffix=".srt", delete=False, encoding="utf-8") as f:
        f.write(SAMPLE_SRT)
        f_path = f.name

    try:
        from_file = presenter.parse_srt_timeline(f_path)
        assert len(from_file) == 4
        assert from_file[0]["text"] == subtitles[0]["text"]
    finally:
        if os.path.exists(f_path):
            os.remove(f_path)


def test_2_talking_slices_alternate_deterministically():
    """2. talking_1/talking_2 alternam deterministicamente."""
    slices = presenter._generate_talking_slices(
        start_t=0.0,
        end_t=1.4,
        step=0.35,
        reason="test_talking",
        available_poses={"talking_1": "t1.png", "talking_2": "t2.png", "neutral": "n.png"},
    )
    assert len(slices) == 4
    assert slices[0]["pose"] == "talking_1"
    assert slices[1]["pose"] == "talking_2"
    assert slices[2]["pose"] == "talking_1"
    assert slices[3]["pose"] == "talking_2"
    assert slices[0]["start"] == 0.0
    assert slices[0]["end"] == 0.35
    assert slices[1]["start"] == 0.35
    assert slices[1]["end"] == 0.70


def test_3_surprise_keyword_triggers_surprised_pose():
    """3. surprise keyword → surprised."""
    pose, reason = presenter.classify_subtitle_reaction("Isso é completamente inacreditável e assustador!")
    assert pose == "surprised"
    assert "surprise" in reason


def test_4_theory_keyword_triggers_thinking_pose():
    """4. theory keyword → thinking."""
    pose, reason = presenter.classify_subtitle_reaction("Uma nova teoria ou hipótese ninguém sabe ao certo.")
    assert pose == "thinking"
    assert "thinking" in reason


def test_5_serious_keyword_triggers_serious_pose():
    """5. serious keyword → serious."""
    pose, reason = presenter.classify_subtitle_reaction("O desaparecimento e a morte da vítima foram trágicos.")
    assert pose == "serious"
    assert "serious" in reason


def test_6_cta_triggers_cta_or_pointing():
    """6. CTA → cta/pointing."""
    pose, reason = presenter.classify_subtitle_reaction(
        "Inscreva-se no canal agora!",
        avatar_position="bottom_center",
    )
    assert pose == "cta"
    assert "cta" in reason


def test_7_bottom_right_points_to_left():
    """7. bottom_right aponta para esquerda."""
    pose, reason = presenter.classify_subtitle_reaction(
        "Comenta aqui embaixo o que você acha!",
        avatar_position="bottom_right",
    )
    assert pose == "pointing_left"
    assert reason == "cta_pointing"


def test_8_bottom_left_points_to_right():
    """8. bottom_left aponta para direita."""
    pose, reason = presenter.classify_subtitle_reaction(
        "Compartilhe este vídeo com seus amigos!",
        avatar_position="bottom_left",
    )
    assert pose == "pointing_right"
    assert reason == "cta_pointing"


def test_9_mystery_mode_uses_contained_behavior():
    """9. modo mistério usa comportamento contido."""
    # Em canal comum: surpresa gera 'surprised'
    pose_default, _ = presenter.classify_subtitle_reaction(
        "Isso é chocante e impressionante!",
        channel_context="default",
    )
    assert pose_default == "surprised"

    # No canal de mistério: comportamento sóbrio/contido gera 'serious'
    pose_mystery, reason_mystery = presenter.classify_subtitle_reaction(
        "Isso é chocante e impressionante!",
        channel_context="profile-historias-misterio",
    )
    assert pose_mystery == "serious"
    assert "contained" in reason_mystery


def test_10_and_11_timeline_events_within_segments_and_no_invalid_overlaps():
    """10. eventos não ultrapassam presenter segments.
    11. eventos não se sobrepõem invalidamente.
    """
    total_dur = 40.0
    segments = [(0.0, 3.5), (14.0, 18.0), (35.5, 40.0)]

    timeline = presenter.build_presenter_expression_timeline(
        subtitle_items=SAMPLE_SRT,
        total_duration=total_dur,
        presenter_segments=segments,
        character_id="nox_v1",
        avatar_position="bottom_right",
        mode=const.AVATAR_MODE_HYBRID,
    )

    assert len(timeline) > 0

    # 10. Garante que todos os eventos estão estritamente contidos em algum segmento visível
    for ev in timeline:
        st = ev["start"]
        en = ev["end"]
        assert en > st, f"Evento com duração não-positiva: {ev}"
        inside_any = any(seg[0] <= st and en <= seg[1] for seg in segments)
        assert inside_any, f"Evento fora dos segmentos do presenter: {ev}"

    # 11. Garante ordenação temporal e nenhuma sobreposição inválida
    for i in range(len(timeline) - 1):
        curr = timeline[i]
        nxt = timeline[i + 1]
        assert curr["end"] <= nxt["start"], f"Sobreposição detectada: {curr} e {nxt}"


def test_12_missing_pose_uses_fallback_chain():
    """12. pose ausente usa fallback."""
    # Pack com apenas neutral e talking_1
    available = {
        "neutral": "neutral.png",
        "talking_1": "talking_1.png",
    }
    # Se surprised ausente: fallback para talking_1
    resolved = presenter.resolve_pose_with_fallback("surprised", available)
    assert resolved == "talking_1"

    # Se talking_1 também faltar: fallback para neutral
    resolved_neutral = presenter.resolve_pose_with_fallback("surprised", {"neutral": "neutral.png"})
    assert resolved_neutral == "neutral"


def test_13_invalid_or_missing_srt_has_safe_fallback():
    """13. SRT inválido tem fallback seguro."""
    total_dur = 30.0
    segments = presenter.build_hybrid_presenter_segments(total_dur)

    # Chamada com arquivo que não existe e lixo de texto
    timeline_missing = presenter.build_presenter_expression_timeline(
        subtitle_items="/caminho/nao/existente/fake.srt",
        total_duration=total_dur,
        presenter_segments=segments,
        character_id="nox_v1",
    )
    assert len(timeline_missing) > 0
    for ev in timeline_missing:
        assert "fallback" in ev["reason"]
        assert ev["end"] > ev["start"]

    summary = presenter.summarize_presenter_timeline(timeline_missing, character_id="nox_v1")
    assert summary["events_count"] == len(timeline_missing)
    assert summary["character_id"] == "nox_v1"


def test_14_autonomous_presenter_remains_strictly_off():
    """14. autonomous presenter permanece OFF."""
    # Default de VideoParams
    params = VideoParams(video_subject="Teste de tema")
    assert params.avatar_mode == const.AVATAR_MODE_NONE
    assert params.avatar_mode == "none"

    # build_autonomous_video_params
    auto_params = autonomous_production.build_autonomous_video_params(
        topic="Mistério antigo",
    )
    assert auto_params.avatar_mode == const.AVATAR_MODE_NONE
    assert auto_params.avatar_character_id == ""
    assert auto_params.avatar_asset_path == ""


def test_15_no_network_or_external_api_called():
    """15. nenhuma rede/API/publicação."""
    with patch("urllib.request.urlopen") as mock_urlopen, patch("requests.post") if "requests" in globals() else patch("urllib.request.Request") as mock_req:
        subtitles = presenter.parse_srt_timeline(SAMPLE_SRT)
        timeline = presenter.build_presenter_expression_timeline(
            subtitle_items=subtitles,
            total_duration=40.0,
            character_id="nox_v1",
        )
        assert len(timeline) > 0
        mock_urlopen.assert_not_called()
