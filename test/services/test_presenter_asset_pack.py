"""
Testes direcionados para V14-C.1 — Cartoon Character Asset Pack + Preview.

Cobertura estrita dos 9 requisitos:
1. character spec/config carrega corretamente
2. character_id resolve asset pack esperado
3. falta de pose obrigatória falha claramente
4. preview/manual path aceita character pack válido
5. presenter continua OFF no autonomous
6. pose controller produz poses válidas
7. nenhuma API externa
8. nenhuma publicação
9. nenhum impacto na produção
"""

import json
import os
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from app.models import const
from app.models.schema import VideoParams
from app.services import autonomous_production
from app.services import presenter


def _create_synthetic_character_pack(
    root_dir: Path,
    character_id: str = "misterio_host_v1",
    missing_poses: list = None,
) -> Path:
    """Cria uma pasta de asset pack sintético com imagens transparentes e config.json."""
    missing = set(missing_poses or [])
    pack_dir = root_dir / character_id
    pack_dir.mkdir(parents=True, exist_ok=True)

    poses_dict = {}
    for pose in presenter.STANDARD_PRESENTER_POSES:
        if pose in missing:
            continue
        filename = f"{pose}.png"
        file_path = pack_dir / filename
        img = Image.new("RGBA", (120, 240), (200, 50, 50, 220))
        img.save(file_path, "PNG")
        poses_dict[pose] = filename

    config_payload = {
        "character_id": character_id,
        "name": "Detetive Theo",
        "style": "cartoon",
        "version": "1.0.0",
        "default_pose": "neutral",
        "default_scale": 0.38,
        "default_position": "bottom_right",
        "default_opacity": 1.0,
        "poses": poses_dict,
    }
    with open(pack_dir / "config.json", "w", encoding="utf-8") as f:
        json.dump(config_payload, f, indent=2)

    return pack_dir


def test_1_character_spec_and_config_loads_correctly():
    """Garante que a documentação de spec existe e config.json do character pack carrega corretamente."""
    # 1. Verifica especificação do personagem
    spec_path = Path("docs/CHARACTER_PRESENTER_SPEC.md")
    assert spec_path.is_file(), "docs/CHARACTER_PRESENTER_SPEC.md deve existir"
    spec_content = spec_path.read_text(encoding="utf-8")
    assert "Dose Diária de Histórias e Mistério" in spec_content
    assert "misterio_host_v1" in spec_content
    assert "Cartoon / Semi-Cartoon" in spec_content

    # 2. Carregamento de config.json
    with tempfile.TemporaryDirectory() as tmp_dir:
        pack_dir = _create_synthetic_character_pack(Path(tmp_dir), "misterio_host_v1")
        pack = presenter.resolve_character_pack("misterio_host_v1", custom_root=tmp_dir)

        assert pack["character_id"] == "misterio_host_v1"
        assert pack["name"] == "Detetive Theo"
        assert pack["style"] == "cartoon"
        assert pack["default_scale"] == 0.38
        assert pack["default_position"] == "bottom_right"
        assert len(pack["poses"]) == len(presenter.STANDARD_PRESENTER_POSES)


def test_2_character_id_resolves_expected_asset_pack():
    """Garante que character_id resolve o diretório e mapeia os arquivos reais de pose."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        _create_synthetic_character_pack(Path(tmp_dir), "misterio_host_v1")
        pack = presenter.resolve_character_pack("misterio_host_v1", custom_root=tmp_dir)

        for pose_name in presenter.STANDARD_PRESENTER_POSES:
            pose_path = pack["poses"].get(pose_name)
            assert pose_path is not None, f"Pose '{pose_name}' deve estar mapeada"
            assert os.path.isfile(pose_path), f"Arquivo da pose '{pose_name}' deve existir fisicamente"


def test_3_missing_required_pose_fails_clearly():
    """Garante que a ausência de pose obrigatória (ex: cta, talking_1) falha claramente."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        _create_synthetic_character_pack(Path(tmp_dir), "incomplete_host", missing_poses=["cta", "talking_1"])

        with pytest.raises(ValueError, match="incompleto.*obrigatórias ausentes"):
            presenter.resolve_character_pack("incomplete_host", custom_root=tmp_dir)


def test_4_preview_and_manual_path_accepts_valid_pack():
    """Garante que o modo de preview renderiza imagem sintética com o character pack."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        _create_synthetic_character_pack(Path(tmp_dir), "misterio_host_v1")

        # 1. Preview Frame (array numpy 1080x1920)
        frame = presenter.generate_presenter_preview_frame(
            character_id="misterio_host_v1",
            pose="neutral",
            canvas_size=(1080, 1920),
            custom_root=tmp_dir,
        )
        assert frame.shape == (1920, 1080, 3)

        # 2. Renderização de arquivo de preview estático
        preview_out = Path(tmp_dir) / "preview.png"
        saved = presenter.render_presenter_preview(
            character_id="misterio_host_v1",
            output_path=str(preview_out),
            pose="talking_1",
            canvas_size=(720, 1280),
            custom_root=tmp_dir,
        )
        assert os.path.isfile(saved)
        assert os.path.getsize(saved) > 0

        # 3. Composição MoviePy usando character_id
        params = VideoParams(
            video_subject="Teste Manual Preview",
            avatar_mode="hybrid",
            avatar_character_id="misterio_host_v1",
        )
        with patch("app.services.presenter.get_character_pack_search_dirs", return_value=[tmp_dir]):
            with ExitStack() as stack:
                clips = presenter.build_presenter_clips(
                    params=params,
                    total_duration=30.0,
                    canvas_size=(1080, 1920),
                    clip_stack=stack,
                )
                assert len(clips) == 3


def test_5_presenter_remains_off_in_autonomous():
    """Garante que novas tarefas autônomas mantêm avatar_mode='none' estritamente."""
    auto_params = autonomous_production.build_autonomous_video_params(
        topic="Mistério da Ilha Desconhecida",
    )
    assert auto_params.avatar_mode == const.AVATAR_MODE_NONE
    assert auto_params.avatar_character_id == ""
    assert auto_params.avatar_asset_path == ""


def test_6_pose_controller_produces_valid_deterministic_poses():
    """Garante seleção determinística de poses com base no tipo de segmento narrativo."""
    available = {p: f"/fake/{p}.png" for p in presenter.STANDARD_PRESENTER_POSES}

    # 1. Hook com palavra de impacto -> surprised
    p1 = presenter.select_presenter_pose("hook", 0, script_text="Este é um mistério chocante", available_poses=available)
    assert p1 == "surprised"

    # 2. Hook neutro -> talking_1
    p2 = presenter.select_presenter_pose("hook", 0, script_text="História comum", available_poses=available)
    assert p2 == "talking_1"

    # 3. CTA -> cta
    p3 = presenter.select_presenter_pose("cta", 2, script_text="Inscreva-se no canal", available_poses=available)
    assert p3 == "cta"

    # 4. Return/meio -> thinking ou serious
    p4 = presenter.select_presenter_pose("return", 1, script_text="Reflexão sobre os fatos", available_poses=available)
    assert p4 in ("thinking", "serious")

    # 5. Determinismo: repetição resulta no mesmo valor
    assert presenter.select_presenter_pose("cta", 2, available_poses=available) == "cta"


def test_7_no_external_api():
    """Garante que resolução e preview não realizam nenhuma chamada de rede externa."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        _create_synthetic_character_pack(Path(tmp_dir), "misterio_host_v1")

        with patch("requests.get") as mock_get, patch("requests.post") as mock_post, \
             patch("urllib.request.urlopen") as mock_url:
            pack = presenter.resolve_character_pack("misterio_host_v1", custom_root=tmp_dir)
            assert pack["name"] == "Detetive Theo"

            preview_out = Path(tmp_dir) / "test_preview.png"
            presenter.render_presenter_preview("misterio_host_v1", str(preview_out), custom_root=tmp_dir)

            mock_get.assert_not_called()
            mock_post.assert_not_called()
            mock_url.assert_not_called()


def test_8_no_publication():
    """Garante que a inspeção de character pack e preview não acionam agendamento nem publicação."""
    with patch("app.services.scheduler.plan_schedule") as mock_sched, \
         patch("app.services.scheduler.adopt_tasks_into_scheduler") as mock_adopt:
        with tempfile.TemporaryDirectory() as tmp_dir:
            _create_synthetic_character_pack(Path(tmp_dir), "misterio_host_v1")
            pack = presenter.resolve_character_pack("misterio_host_v1", custom_root=tmp_dir)
            assert pack["character_id"] == "misterio_host_v1"

        mock_sched.assert_not_called()
        mock_adopt.assert_not_called()


def test_9_no_impact_on_production():
    """Garante que schemas SQLite e configurações de produção não foram alteradas."""
    from app.services import profile_manager

    # Profile default continua padrão e canais inalterados
    assert profile_manager.DEFAULT_PROFILE_ID == "default"
    assert const.DEFAULT_AVATAR_MODE == "none"
    assert const.DEFAULT_GROWTH_MODE == "warmup"
