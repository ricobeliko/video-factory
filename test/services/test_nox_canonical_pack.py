"""
Testes direcionados para V14-C.3 — Nox Canonical Visual Asset Pack Foundation.

Cobertura estrita dos 10 requisitos:
1. manifest válido;
2. core pack completo aceita;
3. core pack incompleto falha;
4. extended pack ausente não falha;
5. fallback graph funciona;
6. RGBA/transparência validada;
7. dimensões incompatíveis detectadas;
8. preview/contact sheet pode ser criado com assets sintéticos;
9. Autonomous Presenter continua OFF;
10. nenhuma API/rede/publicação.
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from app.models import const
from app.models.schema import VideoParams
from app.services import autonomous_production
from app.services import presenter


def _create_synthetic_pack(
    pack_dir: Path,
    character_id: str = "nox_v1",
    include_core: bool = True,
    missing_core: list = None,
    include_extended: bool = False,
    image_size: tuple = (120, 120),
    opaque_pose: str = None,
    mismatched_size_pose: str = None,
) -> Path:
    """Helper para criar um character pack sintético com imagens e manifest."""
    pack_dir.mkdir(parents=True, exist_ok=True)
    poses_dir = pack_dir / "poses"
    poses_dir.mkdir(parents=True, exist_ok=True)

    missing = set(missing_core or [])
    core_map = {}
    if include_core:
        for pose in presenter.CANONICAL_CORE_POSES:
            if pose in missing:
                continue
            cur_size = (180, 120) if (mismatched_size_pose == pose) else image_size
            f_path = poses_dir / f"{pose}.png"

            if opaque_pose == pose:
                # Cria imagem 100% opaca sem canal alfa transparente
                img = Image.new("RGBA", cur_size, (20, 20, 20, 255))
            else:
                # Imagem com transparência real (canal alfa com píxeis transparentes)
                img = Image.new("RGBA", cur_size, (0, 0, 0, 0))
                # desenha quadrado interno opaco
                for x in range(20, cur_size[0] - 20):
                    for y in range(20, cur_size[1] - 20):
                        img.putpixel((x, y), (120, 40, 180, 220))
            img.save(f_path, "PNG")
            core_map[pose] = f"poses/{pose}.png"

    extended_map = {}
    if include_extended:
        for pose in presenter.CANONICAL_EXTENDED_POSES:
            f_path = poses_dir / f"{pose}.png"
            img = Image.new("RGBA", image_size, (0, 0, 0, 0))
            for x in range(30, image_size[0] - 30):
                for y in range(30, image_size[1] - 30):
                    img.putpixel((x, y), (40, 140, 220, 200))
            img.save(f_path, "PNG")
            extended_map[pose] = f"poses/{pose}.png"

    manifest_data = {
        "character_id": character_id,
        "character_name": "Nox",
        "version": 1,
        "style": "cartoon_semi_cartoon",
        "default_pose": "neutral",
        "default_scale": 0.38,
        "default_position": "bottom_right",
        "default_opacity": 1.0,
        "reference_image": "reference/nox_v1_reference.png",
        "visual_identity": {
            "apparent_age": "20-30",
            "skin_tone": "morena clara",
            "hair": "preto escuro bagunçado",
        },
        "core_poses": core_map,
        "extended_poses": extended_map,
    }

    with open(pack_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)

    return pack_dir


def test_1_canonical_manifest_is_valid():
    """1. manifest válido."""
    manifest_path = Path("assets/presenter/nox_v1/manifest.json")
    assert manifest_path.is_file(), "assets/presenter/nox_v1/manifest.json deve existir"

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data["character_id"] == "nox_v1"
    assert data["character_name"] == "Nox"
    assert data["version"] == 1
    assert data["style"] == "cartoon_semi_cartoon"
    assert data["default_pose"] == "neutral"

    # Confirma que todas as 9 poses core estão mapeadas
    for pose in presenter.CANONICAL_CORE_POSES:
        assert pose in data["core_poses"], f"Core pose '{pose}' deve estar no manifest"

    # Confirma que reference_image é relativa
    ref = data["reference_image"]
    assert not os.path.isabs(ref), "reference_image não deve ser path absoluto"
    assert "reference" in ref

    # Confirma identidade visual
    assert "visual_identity" in data
    assert data["visual_identity"]["skin_tone"] == "morena clara"


def test_2_complete_core_pack_accepted(tmp_path):
    """2. core pack completo aceita."""
    pack_dir = _create_synthetic_pack(tmp_path / "nox_v1", include_core=True)

    is_valid, errors = presenter.validate_character_pack_assets(pack_dir)
    assert is_valid is True, f"Erros inesperados: {errors}"
    assert len(errors) == 0

    resolved = presenter.resolve_character_pack("nox_v1", custom_root=str(tmp_path))
    assert resolved["character_id"] == "nox_v1"
    assert len(resolved["poses"]) >= 9


def test_3_incomplete_core_pack_fails(tmp_path):
    """3. core pack incompleto falha."""
    pack_dir = _create_synthetic_pack(
        tmp_path / "nox_incomplete",
        include_core=True,
        missing_core=["cta", "serious"],
    )

    is_valid, errors = presenter.validate_character_pack_assets(pack_dir)
    assert is_valid is False
    assert any("cta" in err for err in errors)
    assert any("serious" in err for err in errors)

    with pytest.raises(ValueError, match="incompleto"):
        presenter.resolve_character_pack("nox_incomplete", custom_root=str(tmp_path))


def test_4_missing_extended_pack_does_not_fail(tmp_path):
    """4. extended pack ausente não falha."""
    # Pack com core completo e zero extended poses
    pack_dir = _create_synthetic_pack(
        tmp_path / "nox_core_only",
        include_core=True,
        include_extended=False,
    )

    is_valid, errors = presenter.validate_character_pack_assets(pack_dir)
    assert is_valid is True
    assert len(errors) == 0


def test_5_fallback_graph_works():
    """5. fallback graph funciona."""
    core_poses = {p: f"/fake/{p}.png" for p in presenter.CANONICAL_CORE_POSES}

    # confused -> thinking
    assert presenter.resolve_pose_with_fallback("confused", core_poses) == "thinking"
    # warning -> serious
    assert presenter.resolve_pose_with_fallback("warning", core_poses) == "serious"
    # excited -> surprised
    assert presenter.resolve_pose_with_fallback("excited", core_poses) == "surprised"
    # talking_4 -> talking_2
    assert presenter.resolve_pose_with_fallback("talking_4", core_poses) == "talking_2"
    # blink -> neutral
    assert presenter.resolve_pose_with_fallback("blink", core_poses) == "neutral"
    # hand_up -> talking_1
    assert presenter.resolve_pose_with_fallback("hand_up", core_poses) == "talking_1"
    # skeptical -> thinking
    assert presenter.resolve_pose_with_fallback("skeptical", core_poses) == "thinking"


def test_6_rgba_transparency_validated(tmp_path):
    """6. RGBA/transparência validada."""
    # Pack com talking_1 100% opaco
    pack_dir = _create_synthetic_pack(
        tmp_path / "nox_opaque",
        include_core=True,
        opaque_pose="talking_1",
    )

    is_valid, errors = presenter.validate_character_pack_assets(pack_dir)
    assert is_valid is False
    assert any("talking_1" in err and "transparente" in err for err in errors)


def test_7_dimension_mismatch_detected(tmp_path):
    """7. dimensões incompatíveis detectadas."""
    # Pack com neutral 120x120 e surprised 180x120
    pack_dir = _create_synthetic_pack(
        tmp_path / "nox_mismatched",
        include_core=True,
        mismatched_size_pose="surprised",
    )

    is_valid, errors = presenter.validate_character_pack_assets(pack_dir)
    assert is_valid is False
    assert any("incompatíveis" in err and "surprised" in err for err in errors)


def test_8_contact_sheet_preview_creation(tmp_path):
    """8. preview/contact sheet pode ser criado com assets sintéticos."""
    pack_dir = _create_synthetic_pack(
        tmp_path / "nox_v1",
        include_core=True,
        include_extended=True,
    )
    sheet_path = tmp_path / "nox_contact_sheet.png"

    out_file = presenter.generate_contact_sheet(
        character_id_or_pack="nox_v1",
        output_path=str(sheet_path),
        custom_root=str(tmp_path),
        thumbnail_size=(80, 80),
        include_extended=True,
    )
    assert os.path.isfile(out_file)
    assert os.path.getsize(out_file) > 0

    with Image.open(out_file) as sheet_img:
        assert sheet_img.format == "PNG"
        assert sheet_img.width > 200
        assert sheet_img.height > 200


def test_9_autonomous_presenter_remains_strictly_off():
    """9. Autonomous Presenter continua OFF."""
    params = VideoParams(video_subject="Teste de tema")
    assert params.avatar_mode == const.AVATAR_MODE_NONE
    assert params.avatar_mode == "none"

    auto_params = autonomous_production.build_autonomous_video_params(
        topic="Mistério Canônico",
    )
    assert auto_params.avatar_mode == const.AVATAR_MODE_NONE
    assert auto_params.avatar_character_id == ""
    assert auto_params.avatar_asset_path == ""


def test_10_no_network_or_external_api_called(tmp_path):
    """10. nenhuma API/rede/publicação."""
    pack_dir = _create_synthetic_pack(tmp_path / "nox_v1", include_core=True)

    with patch("urllib.request.urlopen") as mock_urlopen:
        is_valid, errors = presenter.validate_character_pack_assets(pack_dir)
        assert is_valid is True

        sheet_path = tmp_path / "sheet.png"
        presenter.generate_contact_sheet(
            character_id_or_pack="nox_v1",
            output_path=str(sheet_path),
            custom_root=str(tmp_path),
            thumbnail_size=(60, 60),
        )
        mock_urlopen.assert_not_called()


def test_11_real_imported_nox_pack_is_valid():
    """11. Validação estrita do pack real importado do Nox v1 e preview."""
    canonical_dir = Path("assets/presenter/nox_v1")
    assert canonical_dir.is_dir(), "Diretório canonical de nox_v1 deve existir"

    # Valida assets e manifest usando a função de integridade do presenter
    is_valid, errors = presenter.validate_character_pack_assets(canonical_dir)
    assert is_valid is True, f"Erros na validação de assets reais: {errors}"
    assert len(errors) == 0

    # Valida imagem de referência
    ref_img_path = canonical_dir / "reference" / "nox_v1_reference.png"
    assert ref_img_path.is_file(), "reference/nox_v1_reference.png deve existir"
    with Image.open(ref_img_path) as ref_img:
        assert ref_img.format == "PNG"
        assert ref_img.mode == "RGBA"
        assert ref_img.size[0] > 0 and ref_img.size[1] > 0

    # Valida as 9 poses core
    poses_dir = canonical_dir / "poses"
    for pose in presenter.CANONICAL_CORE_POSES:
        p_file = poses_dir / f"{pose}.png"
        assert p_file.is_file(), f"Pose core '{pose}.png' deve existir"
        assert p_file.stat().st_size > 0

    # Valida contact sheet real
    sheet_path = canonical_dir / "previews" / "nox_v1_contact_sheet_real.png"
    assert sheet_path.is_file(), "Contact sheet real deve existir"
    assert sheet_path.stat().st_size > 0

    # Valida preview local real (v1 e v2 tuning)
    preview_path = canonical_dir / "previews" / "nox_v1_preview_hybrid.mp4"
    assert preview_path.is_file(), "Vídeo de preview local real deve existir"
    assert preview_path.stat().st_size > 1_000_000, "Vídeo de preview deve ter tamanho substancial (>1MB)"

    preview_v2_path = canonical_dir / "previews" / "nox_v1_preview_hybrid_v2.mp4"
    assert preview_v2_path.is_file(), "Vídeo de preview local v2 deve existir"
    assert preview_v2_path.stat().st_size > 1_000_000, "Vídeo de preview v2 deve ter tamanho substancial (>1MB)"


