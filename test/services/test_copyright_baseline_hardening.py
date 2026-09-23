"""Testes direcionados para V14-B — Copyright Baseline Hardening.

Cobre os 8 requisitos da política de testes:
1. Nova geração autônoma nunca usa resource/songs
2. Autonomous usa bgm_type=none
3. Uso manual legado não é quebrado
4. Provenance BGM none é persistido
5. Provenance dos visual clips continua presente
6. Provider desconhecido falha no provenance gate (e BGM legado também falha)
7. Nenhuma API de YouTube/Content ID é chamada
8. Nenhuma publicação ocorre no teste
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.models.schema import VideoParams
from app.services import bgm as bgm_service
from app.services import copyright_gate
from app.services import autonomous_production
from app.services import task_artifacts


def test_1_and_2_autonomous_generation_uses_none_and_never_uses_legacy_songs():
    """Garante que a geração autônoma resolve bgm_type='none', volume=0.0 e nunca faixas de resource/songs."""
    # 1. Testa resolução de BGM autônoma direta
    auto_bgm = bgm_service.resolve_autonomous_bgm({"bgm_type": "random", "bgm_volume": 0.5})
    assert auto_bgm["enabled"] is False
    assert auto_bgm["type"] == "none"
    assert auto_bgm["file"] == ""
    assert auto_bgm["volume"] == 0.0
    assert auto_bgm["provenance_status"] == "SAFE_NO_BGM"

    # 2. Testa build_autonomous_video_params forçando safe BGM mesmo se config.ui tivesse random
    def mock_ui_get(key, default=None):
        if key == "bgm_type":
            return "random"
        if key == "voice_name":
            return "pt-BR-AntonioNeural"
        return default

    with patch("app.config.config.ui.get", side_effect=mock_ui_get):
        params = autonomous_production.build_autonomous_video_params("Tópico de Teste Autônomo")
        assert params.bgm_type == "none"
        assert params.bgm_file == ""
        assert params.bgm_volume == 0.0



def test_3_manual_legacy_bgm_preserved():
    """Garante que chamadas manuais legadas continuam funcionando normalmente sem quebra."""
    builtin_songs = bgm_service.list_builtin_bgm_files()
    assert isinstance(builtin_songs, list)
    # Se existirem músicas na pasta resource/songs, a listagem continua acessível para WebUI manual
    if builtin_songs:
        assert any("output" in f for f in builtin_songs)

    # get_bgm_file com "none" ou "" retorna string vazia
    from app.services import video
    assert video.get_bgm_file(bgm_type="none") == ""
    assert video.get_bgm_file(bgm_type="") == ""


def test_4_bgm_none_provenance_persisted():
    """Garante que a proveniência de BGM='none' é construída e persistida com status SAFE_NO_BGM."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        task_id = "test-task-bgm-none-01"
        task_path = Path(tmp_dir) / task_id
        task_path.mkdir(parents=True, exist_ok=True)

        params = VideoParams(
            video_subject="Assunto de Teste",
            bgm_type="none",
            bgm_volume=0.0,
            bgm_file="",
        )

        with patch("app.utils.utils.task_dir", return_value=str(task_path)):
            # Cria script.json inicial
            initial_data = {"params": params.__dict__, "material_sources": []}
            task_artifacts.write_script_data(task_id, initial_data)

            # Constrói proveniência
            prov = copyright_gate.build_asset_provenance(task_id, params, material_sources=[])
            assert prov["bgm"]["enabled"] is False
            assert prov["bgm"]["source"] == "none"
            assert prov["bgm"]["license_type"] == "not_applicable"
            assert prov["bgm"]["provenance_status"] == "SAFE_NO_BGM"

            # Persiste no script.json
            task_artifacts.patch_script_data(task_id, asset_provenance=prov)

            # Lê de volta e valida persistência
            script_file = task_path / "script.json"
            assert script_file.is_file()
            with open(script_file, "r", encoding="utf-8") as f:
                saved = json.load(f)
            assert "asset_provenance" in saved
            assert saved["asset_provenance"]["bgm"]["enabled"] is False
            assert saved["asset_provenance"]["bgm"]["source"] == "none"


def test_5_visual_clips_provenance_present():
    """Garante que os clips visuais retêm provider, external_id, provider_url, local_file e search_term."""
    raw_sources = [
        {
            "provider": "pexels",
            "asset_id": "123456",
            "source_page": "https://www.pexels.com/video/123456/",
            "local_file": "video-1.mp4",
            "search_term": "galaxy stars",
            "duration": 5,
            "used_duration_sec": 4.5,
        },
        {
            "provider": "pixabay",
            "asset_id": "987654",
            "source_page": "https://pixabay.com/videos/id-987654/",
            "local_file": "video-2.mp4",
            "search_term": "deep ocean",
            "duration": 6,
            "used_duration_sec": 5.0,
        },
    ]

    params = VideoParams(video_subject="Teste Visual", bgm_type="none", bgm_volume=0.0)
    prov = copyright_gate.build_asset_provenance("task-visual-01", params, material_sources=raw_sources)

    assert len(prov["visual_clips"]) == 2
    clip1 = prov["visual_clips"][0]
    assert clip1["provider"] == "pexels"
    assert clip1["external_id"] == "123456"
    assert clip1["provider_url"] == "https://www.pexels.com/video/123456/"
    assert clip1["local_file"] == "video-1.mp4"
    assert clip1["search_term"] == "galaxy stars"
    assert clip1["used_duration_sec"] == 4.5

    clip2 = prov["visual_clips"][1]
    assert clip2["provider"] == "pixabay"
    assert clip2["external_id"] == "987654"
    assert clip2["local_file"] == "video-2.mp4"


def test_6_unknown_provider_and_legacy_bgm_fail_provenance_gate():
    """Garante que provedores não autorizados ou uso de BGM legada resultam em FAIL no gate."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        task_id = "test-gate-fail-01"
        task_path = Path(tmp_dir) / task_id
        task_path.mkdir(parents=True, exist_ok=True)

        # Caso A: Provedor desconhecido / não autorizado
        shady_sources = [
            {
                "provider": "unauthorized_pirate_tube",
                "asset_id": "bad123",
                "local_file": "shady-video.mp4",
            }
        ]
        params_ok = VideoParams(video_subject="Teste Fail", bgm_type="none", bgm_volume=0.0)
        with patch("app.utils.utils.task_dir", return_value=str(task_path)):
            prov = copyright_gate.build_asset_provenance(task_id, params_ok, material_sources=shady_sources)
            task_artifacts.write_script_data(task_id, {"params": params_ok.__dict__, "asset_provenance": prov})

            passed, reason, metrics = copyright_gate.evaluate_copyright_provenance_gate(
                task_id=task_id, task_base_dir=tmp_dir
            )
            assert passed is False
            assert "Provedor visual não autorizado" in reason
            assert metrics["copyright_provenance_gate"] == "FAIL"

        # Caso B: BGM com tipo legado em produção autônoma
        valid_sources = [
            {"provider": "pexels", "asset_id": "111", "local_file": "clip.mp4"}
        ]
        params_legacy_bgm = VideoParams(
            video_subject="Teste Legacy BGM",
            bgm_type="random",
            bgm_volume=0.2,
            bgm_file="output001.mp3",
        )
        task_id_bgm = "test-gate-legacy-bgm-02"
        task_path_bgm = Path(tmp_dir) / task_id_bgm
        task_path_bgm.mkdir(parents=True, exist_ok=True)

        with patch("app.utils.utils.task_dir", return_value=str(task_path_bgm)):
            prov_bgm = copyright_gate.build_asset_provenance(
                task_id_bgm, params_legacy_bgm, material_sources=valid_sources, bgm_file_used="resource/songs/output001.mp3"
            )
            task_artifacts.write_script_data(task_id_bgm, {"params": params_legacy_bgm.__dict__, "asset_provenance": prov_bgm})

            passed, reason, metrics = copyright_gate.evaluate_copyright_provenance_gate(
                task_id=task_id_bgm, task_base_dir=tmp_dir
            )
            assert passed is False
            assert "BGM legado" in reason
            assert metrics["copyright_provenance_gate"] == "FAIL"

        # Caso C: Sucesso (Pexels + bgm none)
        task_id_pass = "test-gate-pass-03"
        task_path_pass = Path(tmp_dir) / task_id_pass
        task_path_pass.mkdir(parents=True, exist_ok=True)
        with patch("app.utils.utils.task_dir", return_value=str(task_path_pass)):
            prov_pass = copyright_gate.build_asset_provenance(task_id_pass, params_ok, material_sources=valid_sources)
            task_artifacts.write_script_data(task_id_pass, {"params": params_ok.__dict__, "asset_provenance": prov_pass})

            passed, reason, metrics = copyright_gate.evaluate_copyright_provenance_gate(
                task_id=task_id_pass, task_base_dir=tmp_dir
            )
            assert passed is True
            assert "COPYRIGHT_PROVENANCE_GATE = PASS" in reason
            assert metrics["copyright_provenance_gate"] == "PASS"
            # NUNCA promete CONTENT_ID_SAFE
            assert "content_id_safe" not in metrics


def test_7_no_youtube_or_content_id_api_called():
    """Garante que a avaliação de proveniência não invoca rede, YouTube API ou scanners externos."""
    valid_sources = [{"provider": "coverr", "local_file": "c1.mp4"}]
    params = VideoParams(video_subject="Teste Local", bgm_type="none", bgm_volume=0.0)

    with patch("requests.get") as mock_get, patch("requests.post") as mock_post:
        prov = copyright_gate.build_asset_provenance("task-no-net", params, material_sources=valid_sources)
        passed, _, _ = copyright_gate.evaluate_copyright_provenance_gate(
            task_id="task-no-net",
            task_data={"params": params.__dict__, "asset_provenance": prov},
        )
        assert passed is True
        mock_get.assert_not_called()
        mock_post.assert_not_called()


def test_8_no_publication_occurs():
    """Garante que a verificação de proveniência é puramente passiva e nunca aciona publicação ou scheduler."""
    with patch("app.services.scheduler.plan_schedule") as mock_sched, \
         patch("app.services.scheduler.adopt_tasks_into_scheduler") as mock_adopt:
        
        summary = copyright_gate.get_copyright_provenance_summary(task_id="task-summary-only")
        assert summary["copyright_gate_status"] == "FAIL"  # Sem assets registrados
        mock_sched.assert_not_called()
        mock_adopt.assert_not_called()

