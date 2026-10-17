"""
test/services/test_quiz_assets.py
=================================
Testes unitários direcionados para o gerenciador de ativos visuais de quiz (Fase Q3).
Valida:
1. Preparação e aspect-fill de imagem em resolução 1200x1066.
2. Deduplicação persistente de IDs e hashes de imagens.
3. Fallback determinístico estilizado com tipografia.
4. Processamento completo de JSON de quiz da Q2 gerando proveniência e compatibilidade com QuizConfig (Q1).
"""

import io
import json
import os
import tempfile
import pytest
from PIL import Image

from app.services.quiz_assets import QuizAssetManager
from scripts.poc_quiz_render import QuizConfig


@pytest.fixture
def temp_asset_manager():
    with tempfile.TemporaryDirectory() as temp_dir:
        history_dir = os.path.join(temp_dir, "history")
        images_dir = os.path.join(temp_dir, "images")
        manager = QuizAssetManager(history_dir=history_dir, default_images_dir=images_dir)
        yield manager, temp_dir


def test_prepare_image_aspect_fill(temp_asset_manager):
    manager, _ = temp_asset_manager

    # Cria imagem de teste 800x400 (aspect 2:1)
    orig = Image.new("RGBA", (800, 400), (255, 0, 0, 255))
    buf = io.BytesIO()
    orig.save(buf, format="PNG")
    raw_bytes = buf.getvalue()

    # Prepara para 1200x1066
    prepared = manager.prepare_image(raw_bytes, target_size=(1200, 1066))
    assert prepared.size == (1200, 1066)
    assert prepared.mode == "RGB"


def test_image_deduplication(temp_asset_manager):
    manager, _ = temp_asset_manager

    assert manager.is_image_used(asset_id="99999") is False
    manager.record_used_image(
        asset_id="99999",
        provider="pexels",
        content_hash="mock_hash_1",
        query="lion",
    )

    assert manager.is_image_used(asset_id="99999") is True
    assert manager.is_image_used(asset_id="other_id", content_hash="mock_hash_1") is True
    assert manager.is_image_used(asset_id="other_id", content_hash="different_hash") is False


def test_fallback_card_generation(temp_asset_manager):
    manager, _ = temp_asset_manager

    raw_bytes, meta = manager._create_fallback_card(
        title="Ganhar um milhão",
        theme_slot="top",
        target_size=(1200, 1066),
    )

    assert meta["provider"] == "local_fallback"
    assert "Internal Generated" in meta["license"]
    assert len(raw_bytes) > 1000

    img = Image.open(io.BytesIO(raw_bytes))
    assert img.size == (1200, 1066)


def test_process_quiz_pipeline(temp_asset_manager):
    manager, temp_dir = temp_asset_manager
    out_images = os.path.join(temp_dir, "out_imgs")
    out_json = os.path.join(temp_dir, "ready.json")

    quiz_mock = {
        "niche": "test_niche",
        "quiz_title": "TESTE QUAL VOCÊ ESCOLHE?",
        "questions": [
            {
                "id": "q1",
                "narration": "Pergunta teste",
                "top": {
                    "title": "SUPER PODER",
                    "tag": "OPÇÃO A",
                    "image_query": "superhero flying sky",
                    "theme": "red",
                },
                "bottom": {
                    "title": "INVISIBILIDADE",
                    "tag": "OPÇÃO B",
                    "image_query": "invisible shadow empty room",
                    "theme": "blue",
                },
            }
        ]
    }

    result = manager.process_quiz(
        quiz_data=quiz_mock,
        output_images_dir=out_images,
        output_json_path=out_json,
    )

    assert result["assets_ready"] is True
    assert os.path.exists(out_json)
    assert len(result["asset_provenance"]) == 2

    # Verifica se os arquivos de imagem foram criados e são válidos
    prov_top = result["asset_provenance"][0]
    prov_bot = result["asset_provenance"][1]
    assert os.path.exists(prov_top["local_path"])
    assert os.path.exists(prov_bot["local_path"])
    assert prov_top["asset_id"] != prov_bot["asset_id"]

    # Verifica compatibilidade com QuizConfig (Q1)
    cfg = QuizConfig.from_dict(result)
    assert cfg.quiz_title == "TESTE QUAL VOCÊ ESCOLHE?"
    assert len(cfg.questions) == 1
