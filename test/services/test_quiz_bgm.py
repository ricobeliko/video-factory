"""
Testes do Serviço de BGM Seguro para Quizzes (Missão H - Hotfix V1).

Cobre:
1. Formato com whitelist própria seleciona faixa e roda sem repetir a última.
2. Arquivo fora do licencas.csv é ignorado.
3. Formato sem whitelist cai na pasta _comum.
4. Sem whitelist nenhuma, gera procedural SAFE_PROCEDURAL.
5. Se procedural falhar (mock), devolve path=None e nunca resource/songs.
6. Renderizador (poc) aceita bgm_path=None/vazio sem quebrar ffmpeg.
7. copyright_gate aceita WHITELISTED_MANUAL e SAFE_PROCEDURAL e rejeita resource/songs.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from app.services import copyright_gate, quiz_bgm
from scripts.poc_quiz_paper_render import PaperQuizConfig, PaperQuizEngine
from scripts.poc_quiz_render import QuizConfig, QuizEngine


# -----------------------------------------------------------------------------
# 1. Whitelist própria com seleção e rodízio
# -----------------------------------------------------------------------------
def test_format_whitelist_selection_and_rotation(tmp_path):
    base_wl = tmp_path / "bgm_whitelist"
    fmt_dir = base_wl / "quiz_paper"
    fmt_dir.mkdir(parents=True)

    csv_content = (
        "arquivo,fonte,licenca,url\n"
        "track1.mp3,pixabay,free,https://example.com/1\n"
        "track2.mp3,pixabay,free,https://example.com/2\n"
    )
    (fmt_dir / "licencas.csv").write_text(csv_content, encoding="utf-8")
    (fmt_dir / "track1.mp3").write_bytes(b"audio_bytes_1")
    (fmt_dir / "track2.mp3").write_bytes(b"audio_bytes_2")

    res1 = quiz_bgm.resolve_quiz_bgm(
        format_key="quiz_paper",
        work_dir=str(tmp_path),
        base_whitelist_dir=str(base_wl),
    )
    assert res1["source"] == "whitelist"
    assert res1["provenance_status"] == "WHITELISTED_MANUAL"
    assert res1["track_id"] == "track1.mp3"
    assert os.path.isfile(res1["path"])

    # Segunda chamada deve rodar para track2.mp3 sem repetir
    res2 = quiz_bgm.resolve_quiz_bgm(
        format_key="quiz_paper",
        work_dir=str(tmp_path),
        base_whitelist_dir=str(base_wl),
    )
    assert res2["source"] == "whitelist"
    assert res2["provenance_status"] == "WHITELISTED_MANUAL"
    assert res2["track_id"] == "track2.mp3"
    assert res2["track_id"] != res1["track_id"]

    # Terceira chamada volta para track1.mp3
    res3 = quiz_bgm.resolve_quiz_bgm(
        format_key="quiz_paper",
        work_dir=str(tmp_path),
        base_whitelist_dir=str(base_wl),
    )
    assert res3["track_id"] == "track1.mp3"


# -----------------------------------------------------------------------------
# 2. Arquivo fora do licencas.csv é ignorado
# -----------------------------------------------------------------------------
def test_unlisted_file_in_whitelist_dir_is_ignored(tmp_path):
    base_wl = tmp_path / "bgm_whitelist"
    fmt_dir = base_wl / "quiz_dilemma"
    fmt_dir.mkdir(parents=True)

    csv_content = (
        "arquivo,fonte,licenca,url\n"
        "valid_track.mp3,pixabay,cc0,https://example.com/valid\n"
    )
    (fmt_dir / "licencas.csv").write_text(csv_content, encoding="utf-8")
    (fmt_dir / "valid_track.mp3").write_bytes(b"valid_data")
    (fmt_dir / "unlisted_track.mp3").write_bytes(b"unlisted_data")

    res = quiz_bgm.resolve_quiz_bgm(
        format_key="quiz_dilemma",
        work_dir=str(tmp_path),
        base_whitelist_dir=str(base_wl),
    )
    assert res["track_id"] == "valid_track.mp3"
    assert "unlisted_track" not in res["path"]


# -----------------------------------------------------------------------------
# 3. Formato sem whitelist cai na pasta _comum
# -----------------------------------------------------------------------------
def test_fallback_to_common_whitelist(tmp_path):
    base_wl = tmp_path / "bgm_whitelist"
    comum_dir = base_wl / "_comum"
    comum_dir.mkdir(parents=True)

    csv_content = (
        "arquivo,fonte,licenca,url\n"
        "common_song.mp3,pixabay,cc0,https://example.com/common\n"
    )
    (comum_dir / "licencas.csv").write_text(csv_content, encoding="utf-8")
    (comum_dir / "common_song.mp3").write_bytes(b"common_audio_bytes")

    # Requisita quiz_paper sem existir pasta quiz_paper
    res = quiz_bgm.resolve_quiz_bgm(
        format_key="quiz_paper",
        work_dir=str(tmp_path),
        base_whitelist_dir=str(base_wl),
    )
    assert res["source"] == "whitelist"
    assert res["provenance_status"] == "WHITELISTED_MANUAL"
    assert res["track_id"] == "common_song.mp3"
    assert "common_song.mp3" in res["path"]


# -----------------------------------------------------------------------------
# 4. Sem whitelist nenhuma, gera procedural SAFE_PROCEDURAL
# -----------------------------------------------------------------------------
def test_no_whitelist_generates_procedural_safe_procedural(tmp_path):
    base_wl = tmp_path / "bgm_whitelist"
    base_wl.mkdir(parents=True)

    res = quiz_bgm.resolve_quiz_bgm(
        format_key="quiz_dilemma",
        work_dir=str(tmp_path),
        seed="unique_task_999",
        duration_sec=3.0,
        mood="energetic",
        base_whitelist_dir=str(base_wl),
    )
    assert res["source"] == "procedural"
    assert res["provenance_status"] == "SAFE_PROCEDURAL"
    assert "procedural_energetic_unique_task_999" in res["track_id"]
    assert res["path"] is not None
    assert os.path.isfile(res["path"])
    assert "resource/songs" not in res["path"].replace("\\", "/")


# -----------------------------------------------------------------------------
# 5. Se procedural falhar (mock), devolve path=None e NUNCA resource/songs
# -----------------------------------------------------------------------------
def test_procedural_failure_returns_none_and_never_resource_songs(tmp_path):
    base_wl = tmp_path / "bgm_whitelist"
    base_wl.mkdir(parents=True)

    with patch("app.services.ambient_bgm.generate_ambient_bgm", side_effect=RuntimeError("FFmpeg error")):
        res = quiz_bgm.resolve_quiz_bgm(
            format_key="quiz_paper",
            work_dir=str(tmp_path),
            base_whitelist_dir=str(base_wl),
        )

    assert res["path"] is None
    assert res["source"] == "none"
    assert res["provenance_status"] == "NONE"
    assert res["track_id"] is None


# -----------------------------------------------------------------------------
# 6. Renderizador (poc) aceita bgm_path=None ou vazio sem quebrar ffmpeg
# -----------------------------------------------------------------------------
def test_renderers_accept_bgm_path_none_without_ffmpeg_error(tmp_path):
    # 6a. QuizEngine com bgm_path="" / None
    dummy_scene = tmp_path / "scene1.mp4"
    dummy_scene.write_bytes(b"dummy_mp4_scene")
    out_video = tmp_path / "final_quiz.mp4"

    cfg = QuizConfig(
        output_video_path=str(out_video),
        temp_dir=str(tmp_path),
        video_settings={"bgm_path": "", "bgm_volume": 0.14},
    )
    engine = QuizEngine(config=cfg)

    # Mock probe_media e subprocess.run para inspecionar comando ffmpeg montado
    with patch("scripts.poc_quiz_render.probe_media", return_value={"format_duration": 62.0}), \
         patch("subprocess.run") as mock_sub:
        mock_sub.return_value = MagicMock(returncode=0)
        out_video.write_bytes(b"dummy_rendered_result" * 100)
        # Cria o staged_concat simulado
        (tmp_path / "staged_concat.mp4").write_bytes(b"dummy_staged_content")

        res = engine.concat_and_mix_bgm([str(dummy_scene)])
        assert res is True
        call_args = mock_sub.call_args[0][0]
        # Confirma que -stream_loop e amix NÃO estão no comando final
        assert "-stream_loop" not in call_args
        assert "amix" not in str(call_args)
        assert "-map" in call_args
        assert "0:a" in call_args

    # 6b. PaperQuizEngine com bgm_path=None
    dummy_scene_paper = tmp_path / "scene_paper1.mp4"
    dummy_scene_paper.write_bytes(b"dummy_mp4_scene")
    out_paper_video = tmp_path / "final_paper.mp4"

    paper_cfg = PaperQuizConfig.from_dict({
        "output_video_path": str(out_paper_video),
        "temp_dir": str(tmp_path),
        "video_settings": {"bgm_path": None, "bgm_volume": 0.14},
    })
    paper_engine = PaperQuizEngine(config=paper_cfg)

    with patch("scripts.poc_quiz_paper_render.probe_media", return_value={"format_duration": 64.0}), \
         patch("subprocess.run") as mock_sub_p:
        mock_sub_p.return_value = MagicMock(returncode=0)
        out_paper_video.write_bytes(b"dummy_rendered_paper" * 100)
        (tmp_path / "staged_concat.mp4").write_bytes(b"dummy_staged_content")

        res_p = paper_engine.concat_and_mix_bgm([str(dummy_scene_paper)])
        assert res_p is True
        call_args_p = mock_sub_p.call_args[0][0]
        assert "-stream_loop" not in call_args_p
        assert "amix" not in str(call_args_p)
        assert "-map" in call_args_p
        assert "0:a" in call_args_p


# -----------------------------------------------------------------------------
# 7. copyright_gate aceita WHITELISTED_MANUAL e SAFE_PROCEDURAL e rejeita resource/songs
# -----------------------------------------------------------------------------
def test_copyright_gate_evaluates_quiz_bgm_provenance(tmp_path):
    # 7a. WHITELISTED_MANUAL deve passar
    prov_whitelisted = {
        "bgm": {
            "enabled": True,
            "filename": "licensed_track.mp3",
            "source": "whitelist",
            "license_type": "whitelisted_manual",
            "provenance_status": "WHITELISTED_MANUAL",
            "track_id": "licensed_track.mp3",
        },
        "visual_clips": [],
        "presenter": {"enabled": False, "mode": "none"},
        "provenance_status": "WHITELISTED_MANUAL",
    }
    pass_wl, reason_wl, details_wl = copyright_gate.evaluate_copyright_provenance_gate(
        task_id="task_wl_test",
        task_data={
            "params": {"video_format": "quiz_paper", "bgm_type": "whitelist"},
            "asset_provenance": prov_whitelisted,
        },
    )
    assert pass_wl is True
    assert details_wl.get("bgm_status") == "WHITELISTED_MANUAL"

    # 7b. SAFE_PROCEDURAL deve passar
    prov_procedural = {
        "bgm": {
            "enabled": True,
            "filename": "procedural_bgm.mp3",
            "source": "procedural",
            "license_type": "safe_procedural",
            "provenance_status": "SAFE_PROCEDURAL",
            "track_id": "procedural_energetic_1",
        },
        "visual_clips": [],
        "presenter": {"enabled": False, "mode": "none"},
        "provenance_status": "SAFE_PROCEDURAL",
    }
    pass_proc, reason_proc, details_proc = copyright_gate.evaluate_copyright_provenance_gate(
        task_id="task_proc_test",
        task_data={
            "params": {"video_format": "quiz_dilemma", "bgm_type": "ambient_auto"},
            "asset_provenance": prov_procedural,
        },
    )
    assert pass_proc is True
    assert details_proc.get("bgm_status") == "SAFE_PROCEDURAL"

    # 7c. Faixa legada de resource/songs deve falhar
    prov_legacy = {
        "bgm": {
            "enabled": True,
            "filename": "output000.mp3",
            "source": "legacy_resource_songs",
            "license_type": "unknown",
            "provenance_status": "UNAUDITED_LEGACY",
        },
        "visual_clips": [],
        "presenter": {"enabled": False, "mode": "none"},
        "provenance_status": "UNAUDITED_LEGACY",
    }
    pass_leg, reason_leg, details_leg = copyright_gate.evaluate_copyright_provenance_gate(
        task_id="task_legacy_test",
        task_data={
            "params": {"video_format": "quiz_paper", "bgm_file": "resource/songs/output000.mp3"},
            "asset_provenance": prov_legacy,
        },
    )
    assert pass_leg is False
    assert details_leg.get("bgm_status") == "BLOCKED_LEGACY"
    assert "resource/songs" in reason_leg
