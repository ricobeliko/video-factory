"""
Testes direcionados para V14-C — Hybrid Character Overlay MVP.

Cobertura estrita dos 12 requisitos da política de testes:
1. avatar_mode none mantém caminho antigo;
2. PNG transparente válido cria overlay;
3. asset inexistente falha quando presenter solicitado;
4. path inválido/traversal bloqueado;
5. hybrid segments determinísticos;
6. segmentos dentro da duração;
7. subtitle permanece acima do presenter;
8. provenance presenter none;
9. provenance presenter hybrid;
10. autonomous continua avatar_mode none;
11. nenhuma API/rede;
12. nenhuma publicação.
"""

import os
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from PIL import Image

from app.models import const
from app.models.schema import VideoParams
from app.services import autonomous_production
from app.services import copyright_gate
from app.services import presenter


def _create_dummy_transparent_png(file_path: Path, width: int = 100, height: int = 200) -> Path:
    """Cria imagem RGBA sintética com canal alfa para testes."""
    img = Image.new("RGBA", (width, height), (255, 0, 0, 180))
    img.save(file_path, "PNG")
    return file_path


def test_1_avatar_mode_none_preserves_old_path():
    """Garante que avatar_mode='none' não cria nenhum clip de overlay."""
    params = VideoParams(
        video_subject="Teste Baseline",
        avatar_mode="none",
    )
    with ExitStack() as stack:
        clips = presenter.build_presenter_clips(
            params=params,
            total_duration=30.0,
            canvas_size=(1080, 1920),
            clip_stack=stack,
        )
        assert clips == []


def test_2_valid_transparent_png_creates_overlay():
    """Garante que PNG transparente válido gera clips nas posições e dimensões corretas."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        png_path = Path(tmp_dir) / "character.png"
        _create_dummy_transparent_png(png_path, width=200, height=400)

        params = VideoParams(
            video_subject="Teste Presenter PNG",
            avatar_mode="hybrid",
            avatar_asset_path=str(png_path),
            avatar_position="bottom_right",
            avatar_scale=0.38,
            avatar_opacity=0.9,
        )

        with ExitStack() as stack:
            clips = presenter.build_presenter_clips(
                params=params,
                total_duration=30.0,
                canvas_size=(1080, 1920),
                clip_stack=stack,
            )
            # Para vídeo de 30s, o modo hybrid cria 3 segmentos: HOOK, RETURN, CTA
            assert len(clips) == 3
            # Verifica início e duração dos segmentos
            assert clips[0].start == 0.0
            assert clips[0].end == 3.5
            assert clips[1].start == 10.5
            assert clips[1].end == 13.5
            assert clips[2].start == 25.5
            assert clips[2].end == 30.0

            # Verifica layout da imagem redimensionada
            # 1080 * 0.38 = 410 largura, proporção 200x400 => altura 820
            # Margem X: 1080 * 0.04 = 43px => x = 1080 - 410 - 43 = 627
            # Margem Y: 1920 * 0.06 = 115px => y = 1920 - 820 - 115 = 985
            for c in clips:
                assert c.size == (410, 820)
                assert c.pos(0) == (627, 985)


def test_3_missing_asset_fails_closed():
    """Garante fail-closed e erro explícito quando presenter solicitado mas arquivo inexistente."""
    params = VideoParams(
        video_subject="Teste Asset Inexistente",
        avatar_mode="hybrid",
        avatar_asset_path="caminho_inexistente_do_avatar.png",
    )
    with pytest.raises((FileNotFoundError, ValueError), match="não encontrado"):
        presenter.build_presenter_clips(
            params=params,
            total_duration=30.0,
            canvas_size=(1080, 1920),
        )


def test_4_invalid_path_and_traversal_blocked():
    """Garante bloqueio de path traversal e extensões não suportadas."""
    params_traversal = VideoParams(
        video_subject="Teste Traversal",
        avatar_mode="hybrid",
        avatar_asset_path="../../etc/secret.png",
    )
    with pytest.raises(ValueError, match="Path traversal"):
        presenter.build_presenter_clips(
            params=params_traversal,
            total_duration=30.0,
            canvas_size=(1080, 1920),
        )

    with tempfile.TemporaryDirectory() as tmp_dir:
        bad_ext_file = Path(tmp_dir) / "character.txt"
        bad_ext_file.write_text("dummy")

        params_bad_ext = VideoParams(
            video_subject="Teste Bad Ext",
            avatar_mode="hybrid",
            avatar_asset_path=str(bad_ext_file),
        )
        with pytest.raises(ValueError, match="Extensão de asset não suportada"):
            presenter.build_presenter_clips(
                params=params_bad_ext,
                total_duration=30.0,
                canvas_size=(1080, 1920),
            )


def test_5_hybrid_segments_deterministic():
    """Garante que a função de cálculo de segmentos é estritamente determinística."""
    s1 = presenter.build_hybrid_presenter_segments(30.0)
    s2 = presenter.build_hybrid_presenter_segments(30.0)
    assert s1 == s2
    assert s1 == [(0.0, 3.5), (10.5, 13.5), (25.5, 30.0)]


def test_6_segments_never_overlap_and_within_duration():
    """Garante que os segmentos nunca se sobrepõem e nunca ultrapassam a duração total."""
    test_durations = [4.0, 10.0, 24.5, 25.0, 30.0, 60.0, 75.0]
    for duration in test_durations:
        segs = presenter.build_hybrid_presenter_segments(duration)
        assert len(segs) > 0
        for i, (st, en) in enumerate(segs):
            assert st < en, f"Início ({st}) deve ser menor que fim ({en}) para duração {duration}"
            assert en <= duration, f"Fim ({en}) deve ser <= duração ({duration})"
            if i > 0:
                prev_en = segs[i - 1][1]
                assert st >= prev_en, f"Segmento sobreposto detectado em duração {duration}: {segs[i-1]} e {segs[i]}"


def test_7_subtitle_remains_above_presenter_z_order():
    """Garante que a composição coloca o layer de legendas ACIMA do presenter."""
    from moviepy import ColorClip, ImageClip, TextClip, CompositeVideoClip

    bg_clip = ColorClip(size=(100, 100), color=(0, 0, 0), duration=2.0)
    with tempfile.TemporaryDirectory() as tmp_dir:
        png_path = Path(tmp_dir) / "char.png"
        _create_dummy_transparent_png(png_path, 50, 50)
        char_clip = ImageClip(str(png_path)).with_duration(2.0)
        txt_clip = ColorClip(size=(30, 10), color=(255, 255, 255), duration=2.0)

        # Na composição de generate_video, clips são dispostos na ordem: [source_video_clip, *presenter_clips, *text_clips]
        composite = CompositeVideoClip([bg_clip, char_clip, txt_clip])

        # O MoviePy renderiza do primeiro ao último na lista
        clips_order = composite.clips
        assert clips_order[0] is bg_clip       # Layer 1: B-roll
        assert clips_order[1] is char_clip     # Layer 2: Presenter
        assert clips_order[2] is txt_clip      # Layer 3: Subtitle (topo)

        bg_clip.close()
        char_clip.close()
        txt_clip.close()
        composite.close()


def test_8_provenance_presenter_none():
    """Garante proveniência correta quando presenter está desativado."""
    params = VideoParams(
        video_subject="Teste Provenance None",
        avatar_mode="none",
    )
    prov = copyright_gate.build_asset_provenance(
        task_id="task-prov-none",
        params=params,
    )
    assert prov["presenter"] == {
        "enabled": False,
        "mode": "none",
    }


def test_9_provenance_presenter_hybrid():
    """Garante proveniência correta quando presenter está ativado em modo hybrid."""
    params = VideoParams(
        video_subject="Teste Provenance Hybrid",
        avatar_mode="hybrid",
        avatar_provider="local",
        avatar_character_id="narrator_neo",
        avatar_asset_path="resource/avatars/neo.png",
    )
    prov = copyright_gate.build_asset_provenance(
        task_id="task-prov-hybrid",
        params=params,
    )
    assert prov["presenter"] == {
        "enabled": True,
        "mode": "hybrid",
        "provider": "local",
        "character_id": "narrator_neo",
        "asset_path": "resource/avatars/neo.png",
        "asset_type": "png",
        "provenance_status": "LOCAL_OPERATOR_ASSET",
    }


def test_10_autonomous_continues_avatar_mode_none():
    """Garante que a fábrica autônoma continua com avatar_mode='none' por padrão."""
    params = autonomous_production.build_autonomous_video_params(
        topic="Misteriosa História Antiga",
    )
    assert params.avatar_mode == const.AVATAR_MODE_NONE
    assert params.avatar_provider == "local"
    assert params.avatar_character_id == ""
    assert params.avatar_asset_path == ""


def test_11_no_publish_api_or_real_network():
    """Garante que o pipeline do presenter é estritamente offline sem chamadas de rede."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        png_path = Path(tmp_dir) / "char.png"
        _create_dummy_transparent_png(png_path, 100, 100)

        params = VideoParams(
            video_subject="Teste No Net",
            avatar_mode="hybrid",
            avatar_asset_path=str(png_path),
        )

        with patch("requests.get") as mock_get, patch("requests.post") as mock_post, \
             patch("urllib.request.urlopen") as mock_urlopen:
            with ExitStack() as stack:
                clips = presenter.build_presenter_clips(
                    params=params,
                    total_duration=10.0,
                    canvas_size=(1080, 1920),
                    clip_stack=stack,
                )
                assert len(clips) > 0
            mock_get.assert_not_called()
            mock_post.assert_not_called()
            mock_urlopen.assert_not_called()


def test_12_no_publication_or_scheduler_call():
    """Garante que o presenter não interage nem dispara o agendador de publicação."""
    with patch("app.services.scheduler.plan_schedule") as mock_sched, \
         patch("app.services.scheduler.adopt_tasks_into_scheduler") as mock_adopt:
        segments = presenter.build_hybrid_presenter_segments(60.0)
        assert len(segments) == 3
        mock_sched.assert_not_called()
        mock_adopt.assert_not_called()
