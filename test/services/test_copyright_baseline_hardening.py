"""Testes direcionados para V14-B.1 — Legacy Stock Copyright Quarantine.

Cobre os 8 requisitos da política de testes:
1. legacy params dict + bgm_type=random => provenance detecta BGM legado;
2. legacy random => Copyright Gate FAIL;
3. legacy custom sem provenance => FAIL;
4. legacy asset FAIL não entra no autonomous ready stock;
5. legacy waiting/recovery FAIL não entra no scheduler pelo Autonomous;
6. nova task bgm none + provenance correta continua PASS;
7. manual legacy path permanece disponível / não é globalmente destruído;
8. nenhum publish/API/rede real.
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.models import const
from app.models.schema import VideoParams
from app.services import autonomous_production
from app.services import bgm as bgm_service
from app.services import copyright_gate
from app.services import operator_console
from app.services import profile_manager
from app.services import quality_score
from app.services import safety_gate
from app.services import scheduler
from app.services import task_artifacts


def test_1_legacy_params_dict_bgm_random_detected():
    """Garante que params em formato dict com bgm_type='random' gera proveniência UNAUDITED_LEGACY."""
    legacy_params = {
        "bgm_type": "random",
        "bgm_file": "",
        "bgm_volume": 0.2,
        "video_subject": "História antiga",
    }
    sources = [{"provider": "pexels", "local_file": "v1.mp4"}]

    prov = copyright_gate.build_asset_provenance(
        task_id="task-legacy-dict-01",
        params=legacy_params,
        material_sources=sources,
    )

    assert prov["bgm"]["enabled"] is True
    assert prov["bgm"]["source"] == "legacy_resource_songs"
    assert prov["bgm"]["provenance_status"] == "UNAUDITED_LEGACY"
    assert prov["provenance_status"] == "UNVERIFIED_BGM"


def test_2_legacy_random_fails_copyright_gate():
    """Garante que tarefa antiga com bgm_type='random' falha no Copyright Provenance Gate."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        task_id = "task-legacy-random-02"
        task_path = Path(tmp_dir) / task_id
        task_path.mkdir(parents=True, exist_ok=True)

        script_payload = {
            "params": {
                "bgm_type": "random",
                "bgm_file": "",
                "bgm_volume": 0.2,
                "video_subject": "Curiosidades antigas",
            },
            "material_sources": [{"provider": "pexels", "local_file": "v1.mp4"}],
        }
        with open(task_path / "script.json", "w", encoding="utf-8") as f:
            json.dump(script_payload, f)

        passed, reason, metrics = copyright_gate.evaluate_copyright_provenance_gate(
            task_id=task_id, task_base_dir=tmp_dir
        )
        assert passed is False
        assert "BGM legado de resource/songs" in reason
        assert metrics["copyright_provenance_gate"] == "FAIL"


def test_3_legacy_custom_without_provenance_fails():
    """Garante que tarefa antiga com bgm_type='custom' sem proveniência/licença falha no Gate."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        task_id = "task-legacy-custom-03"
        task_path = Path(tmp_dir) / task_id
        task_path.mkdir(parents=True, exist_ok=True)

        script_payload = {
            "params": {
                "bgm_type": "custom",
                "bgm_file": "minha_faixa_antiga.mp3",
                "bgm_volume": 0.3,
                "video_subject": "Mistério",
            },
            "material_sources": [{"provider": "pexels", "local_file": "v1.mp4"}],
        }
        with open(task_path / "script.json", "w", encoding="utf-8") as f:
            json.dump(script_payload, f)

        passed, reason, metrics = copyright_gate.evaluate_copyright_provenance_gate(
            task_id=task_id, task_base_dir=tmp_dir
        )
        assert passed is False
        assert "BGM ativa sem whitelist" in reason
        assert metrics["copyright_provenance_gate"] == "FAIL"


def test_4_legacy_asset_fail_excluded_from_autonomous_ready_stock():
    """Garante que um asset antigo com BGM legada NÃO entra no ready_stock do modo autônomo."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_autopilot.db")
        scheduler.init_db(db_path)
        safety_gate.init_safety_db(db_path)
        quality_score.init_quality_db(db_path)
        profile_manager.init_profile_db(db_path)
        profile_manager.ensure_default_profile(db_path=db_path)

        task_id = "legacy-asset-fail-04"
        task_path = Path(tmp_dir) / task_id
        task_path.mkdir(parents=True, exist_ok=True)

        # 1. Cria vídeo final físico em disco
        video_file = task_path / "final-1.mp4"
        video_file.write_bytes(b"dummy mp4 video content")

        # 2. Cria script.json legado (random BGM)
        script_payload = {
            "params": {
                "bgm_type": "random",
                "bgm_file": "",
                "bgm_volume": 0.2,
                "video_subject": "Vídeo Antigo Legado",
            },
            "material_sources": [{"provider": "pexels", "local_file": "v1.mp4"}],
        }
        with open(task_path / "script.json", "w", encoding="utf-8") as f:
            json.dump(script_payload, f)

        # 3. Registra aprovações persistidas de Safety e Quality
        safety_gate.save_safety_assessment(
            {
                "task_id": task_id,
                "preset": "curiosidades",
                "safety_status": const.SAFETY_STATUS_PASS,
                "safety_reasons": [],
            },
            db_path=db_path,
        )
        quality_score.evaluate_quality(
            topic="Vídeo Antigo Legado",
            task_id=task_id,
            persist=True,
            db_path=db_path,
        )
        scheduler.save_task_platforms(task_id, ["youtube"], db_path=db_path)
        profile_manager.save_task_profile(task_id, "default", db_path=db_path)

        # 4. Executa get_autonomous_ready_stock
        stock = autonomous_production.get_autonomous_ready_stock(
            task_base_dir=tmp_dir,
            db_path=db_path,
            profile_id="default",
        )

        # O asset legado deve ser TOTALMENTE EXCLUÍDO do estoque autônomo
        assert stock["ready_count"] == 0
        assert stock["youtube_count"] == 0
        assert len(stock["youtube_ready"]) == 0
        # O arquivo de vídeo físico NÃO foi apagado
        assert video_file.is_file()


def test_5_legacy_waiting_recovery_fail_not_entered_into_scheduler():
    """Garante que a recuperação de waiting_task falha para asset legado e não entra no Scheduler."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_autopilot.db")
        scheduler.init_db(db_path)
        safety_gate.init_safety_db(db_path)
        quality_score.init_quality_db(db_path)
        profile_manager.init_profile_db(db_path)
        profile_manager.ensure_default_profile(db_path=db_path)
        operator_console.init_operator_db(db_path)
        operator_console.reset_instance_for_testing()
        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._current_role = operator_console.ROLE_PRIMARY
        operator_console.resume_factory(db_path=db_path)

        task_id = "legacy-waiting-fail-05"
        task_path = Path(tmp_dir) / task_id
        task_path.mkdir(parents=True, exist_ok=True)

        video_file = task_path / "final-1.mp4"
        video_file.write_bytes(b"dummy mp4 video content")

        script_payload = {
            "params": {
                "bgm_type": "random",
                "bgm_file": "",
                "bgm_volume": 0.2,
                "video_subject": "Vídeo Waiting Antigo",
            },
            "material_sources": [{"provider": "pexels", "local_file": "v1.mp4"}],
        }
        with open(task_path / "script.json", "w", encoding="utf-8") as f:
            json.dump(script_payload, f)

        safety_gate.save_safety_assessment(
            {
                "task_id": task_id,
                "preset": "curiosidades",
                "safety_status": const.SAFETY_STATUS_PASS,
                "safety_reasons": [],
            },
            db_path=db_path,
        )
        quality_score.evaluate_quality(
            topic="Vídeo Waiting Antigo",
            task_id=task_id,
            persist=True,
            db_path=db_path,
        )
        scheduler.save_task_platforms(task_id, ["youtube"], db_path=db_path)
        profile_manager.save_task_profile(task_id, "default", db_path=db_path)

        # 1. _recover_waiting_task deve lançar ValueError explícito por falha de Copyright Gate
        with pytest.raises(ValueError, match="waiting_copyright_provenance_failed"):
            autonomous_production._recover_waiting_task(
                task_id=task_id,
                db_path=db_path,
                task_base_dir=tmp_dir,
            )

        # 2. Quando no ciclo autônomo, não agenda a tarefa legada
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_WAITING_TASK_ID, task_id, db_path=db_path
        )
        res = autonomous_production.run_autonomous_cycle(
            force=True,
            one_shot=True,
            db_path=db_path,
            profile_id="default",
            task_base_dir=tmp_dir,
        )
        assert res.get("scheduled_items", 0) == 0
        assert res.get("status") == "waiting_schedule"
        assert res.get("reason") == "waiting_recovery_failed"


def test_6_new_v14b_task_remains_eligible():
    """Garante que nova task com bgm_type='none' e proveniência correta é aprovada e entra no estoque."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_autopilot.db")
        scheduler.init_db(db_path)
        safety_gate.init_safety_db(db_path)
        quality_score.init_quality_db(db_path)
        profile_manager.init_profile_db(db_path)
        profile_manager.ensure_default_profile(db_path=db_path)

        task_id = "new-v14b-pass-06"
        task_path = Path(tmp_dir) / task_id
        task_path.mkdir(parents=True, exist_ok=True)

        video_file = task_path / "final-1.mp4"
        video_file.write_bytes(b"dummy mp4 video content")

        params = VideoParams(
            video_subject="Novo Vídeo Seguro V14-B",
            bgm_type="none",
            bgm_volume=0.0,
            bgm_file="",
        )
        sources = [
            {"provider": "pexels", "asset_id": "999", "local_file": "v1.mp4", "duration": 5}
        ]
        prov = copyright_gate.build_asset_provenance(task_id, params, material_sources=sources)

        script_payload = {
            "params": params.__dict__,
            "material_sources": sources,
            "asset_provenance": prov,
        }
        with open(task_path / "script.json", "w", encoding="utf-8") as f:
            json.dump(script_payload, f)

        safety_gate.save_safety_assessment(
            {
                "task_id": task_id,
                "preset": "curiosidades",
                "safety_status": const.SAFETY_STATUS_PASS,
                "safety_reasons": [],
            },
            db_path=db_path,
        )
        quality_score.evaluate_quality(
            topic="Novo Vídeo Seguro V14-B",
            task_id=task_id,
            persist=True,
            db_path=db_path,
        )
        scheduler.save_task_platforms(task_id, ["youtube"], db_path=db_path)
        profile_manager.save_task_profile(task_id, "default", db_path=db_path)

        # 1. Avaliação do gate individual
        passed, reason, metrics = copyright_gate.evaluate_copyright_provenance_gate(
            task_id=task_id, task_base_dir=tmp_dir
        )
        assert passed is True
        assert metrics["copyright_provenance_gate"] == "PASS"

        # 2. _recover_waiting_task tem sucesso
        recovered = autonomous_production._recover_waiting_task(
            task_id=task_id,
            db_path=db_path,
            task_base_dir=tmp_dir,
        )
        assert recovered["state"] == const.TASK_STATE_COMPLETE
        assert recovered.get("copyright_provenance_gate") == "PASS"

        # 3. Entra no ready_stock autônomo normalmente
        stock = autonomous_production.get_autonomous_ready_stock(
            task_base_dir=tmp_dir,
            db_path=db_path,
            profile_id="default",
        )
        assert stock["ready_count"] == 1
        assert stock["youtube_ready"][0]["task_id"] == task_id


def test_7_manual_legacy_path_preserved():
    """Garante que caminhos manuais legados não foram globalmente destruídos."""
    builtin_songs = bgm_service.list_builtin_bgm_files()
    assert isinstance(builtin_songs, list)
    from app.services import video
    assert video.get_bgm_file(bgm_type="none") == ""
    assert video.get_bgm_file(bgm_type="") == ""


def test_8_no_publish_api_or_real_network():
    """Garante que a verificação de proveniência não realiza chamadas de rede ou publicação."""
    valid_sources = [{"provider": "coverr", "local_file": "c1.mp4"}]
    params = {"bgm_type": "none", "bgm_volume": 0.0}

    with patch("requests.get") as mock_get, patch("requests.post") as mock_post, \
         patch("app.services.scheduler.plan_schedule") as mock_sched:
        prov = copyright_gate.build_asset_provenance("task-no-net", params, material_sources=valid_sources)
        passed, _, _ = copyright_gate.evaluate_copyright_provenance_gate(
            task_id="task-no-net",
            task_data={"params": params, "asset_provenance": prov},
        )
        assert passed is True
        mock_get.assert_not_called()
        mock_post.assert_not_called()
        mock_sched.assert_not_called()
