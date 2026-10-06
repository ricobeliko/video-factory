"""
test/services/test_adaptive_visual_feedback.py
=============================================
Testes direcionados para V16.11 — Adaptive Visual Feedback.
"""

import os
import sqlite3
import subprocess
import sys
import tempfile
import pytest

from app.services.adaptive_visual_feedback import (
    ADAPTIVE_CAP_MAX,
    ADAPTIVE_CAP_MIN,
    HumanFeedback,
    VisualExperienceRecord,
    bootstrap_mars_benchmark_experience,
    compute_adaptive_adjustment,
    get_task_feedback,
    get_task_visual_experiences,
    init_db,
    record_human_feedback,
    record_visual_experience,
)


@pytest.fixture
def temp_db_path():
    """Cria um banco SQLite temporário isolado para cada teste."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    try:
        if os.path.exists(db_path):
            os.remove(db_path)
    except Exception:
        pass


def test_migration_idempotent(temp_db_path):
    """Verifica que a migração do banco é idempotente e cria índices requeridos."""
    conn = sqlite3.connect(temp_db_path)
    try:
        # Executa a primeira vez
        init_db(conn)
        # Executa a segunda vez para garantir idempotência
        init_db(conn)

        cursor = conn.cursor()
        # Verifica tabela visual_experience
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='visual_experience'")
        assert cursor.fetchone() is not None

        # Verifica tabela task_feedback
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='task_feedback'")
        assert cursor.fetchone() is not None

        # Verifica índices
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indices = {row[0] for row in cursor.fetchall()}
        assert "idx_visexp_subject" in indices
        assert "idx_visexp_provider" in indices
        assert "idx_visexp_asset" in indices
        assert "idx_visexp_query" in indices
        assert "idx_visexp_feedback" in indices
        assert "idx_visexp_task" in indices
        assert "idx_visexp_created" in indices
    finally:
        conn.close()


def test_insert_idempotent(temp_db_path):
    """Verifica inserção idempotente e preservação de feedback humano existente."""
    rec = VisualExperienceRecord(
        task_id="task-123",
        video_subject="Espaço e Astronomia",
        scene_index=1,
        narration="Marte é o planeta vermelho",
        visual_intent="landscape",
        search_query="mars surface",
        provider="wikimedia_commons",
        provider_type="thematic",
        asset_id="asset-mars-001",
        source_url="https://example.com/mars1.jpg",
        strategy_selected="THEMATIC_SOURCE_PREFERRED",
        stock_score=65.0,
        thematic_score=85.0,
        final_score=85.0,
    )

    # Primeiro insert
    success1 = record_visual_experience(rec, db_path=temp_db_path)
    assert success1 is True

    # Aplica feedback humano na cena
    record_human_feedback(
        task_id="task-123",
        scene_index=1,
        feedback="GOOD",
        score=5,
        reason="Excelente textura",
        db_path=temp_db_path,
    )

    # Segundo insert idêntico (ex: retry ou re-execução da cena)
    success2 = record_visual_experience(rec, db_path=temp_db_path)
    assert success2 is True

    # Verifica que não duplicou e preservou o feedback humano
    exps = get_task_visual_experiences("task-123", db_path=temp_db_path)
    assert len(exps) == 1
    assert exps[0]["human_feedback"] == "GOOD"
    assert exps[0]["human_score"] == 5
    assert exps[0]["feedback_reason"] == "Excelente textura"


def test_no_history_original_behavior(temp_db_path):
    """Sem histórico, o ajuste adaptativo deve ser neutro (0.0) e o score base inalterado."""
    res = compute_adaptive_adjustment(
        asset_id="brand_new_asset",
        provider="pexels",
        search_query="new search query",
        video_subject="Novas Tecnologias",
        current_task_asset_ids=[],
        base_score=75.0,
        db_path=temp_db_path,
    )
    assert res.adaptive_adjustment == 0.0
    assert res.adaptive_reason == "neutral"
    assert res.final_score == 75.0


def test_good_bonus(temp_db_path):
    """Verifica bônus leve para asset com histórico GOOD / human_score 5 (+8) e score 4 (+5)."""
    import datetime
    past_date = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=10)).isoformat()

    # Asset com nota 5
    rec_score5 = VisualExperienceRecord(
        task_id="task-prev-1",
        video_subject="Ciência",
        scene_index=1,
        asset_id="asset-high-quality",
        search_query="telescope",
        human_feedback=HumanFeedback.GOOD.value,
        human_score=5,
        created_at=past_date,
    )
    record_visual_experience(rec_score5, db_path=temp_db_path)

    res5 = compute_adaptive_adjustment(
        asset_id="asset-high-quality",
        provider="pexels",
        search_query="telescope space",
        video_subject="Ciência",
        current_task_asset_ids=[],
        base_score=70.0,
        db_path=temp_db_path,
    )
    assert res5.adaptive_adjustment >= 8.0
    assert "human_score_5_bonus" in res5.adaptive_reason
    assert res5.final_score >= 78.0

    # Asset com nota 4
    rec_score4 = VisualExperienceRecord(
        task_id="task-prev-2",
        video_subject="Ciência",
        scene_index=1,
        asset_id="asset-good-4",
        search_query="telescope",
        human_feedback=HumanFeedback.GOOD.value,
        human_score=4,
        created_at=past_date,
    )
    record_visual_experience(rec_score4, db_path=temp_db_path)

    res4 = compute_adaptive_adjustment(
        asset_id="asset-good-4",
        provider="pexels",
        search_query="telescope space",
        video_subject="Ciência",
        current_task_asset_ids=[],
        base_score=70.0,
        db_path=temp_db_path,
    )
    assert res4.adaptive_adjustment >= 5.0
    assert "human_score_4_bonus" in res4.adaptive_reason


def test_bad_penalty(temp_db_path):
    """Verifica penalidade para asset com histórico BAD (-10) e nota 1 (-12)."""
    import datetime
    past_date = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=10)).isoformat()

    # BAD genérico
    rec_bad = VisualExperienceRecord(
        task_id="task-bad-1",
        video_subject="História",
        scene_index=1,
        provider="prov_bad_test",
        asset_id="asset-bad-generic",
        human_feedback=HumanFeedback.BAD.value,
        human_score=2,
        created_at=past_date,
    )
    record_visual_experience(rec_bad, db_path=temp_db_path)

    res_bad = compute_adaptive_adjustment(
        asset_id="asset-bad-generic",
        provider="prov_bad_test",
        search_query="ancient castle",
        video_subject="História",
        current_task_asset_ids=[],
        base_score=80.0,
        db_path=temp_db_path,
    )
    assert res_bad.adaptive_adjustment <= -10.0
    assert "history_bad_penalty" in res_bad.adaptive_reason

    # BAD nota 1
    rec_score1 = VisualExperienceRecord(
        task_id="task-bad-2",
        video_subject="História",
        scene_index=2,
        provider="prov_score1_test",
        asset_id="asset-worst",
        human_feedback=HumanFeedback.BAD.value,
        human_score=1,
        created_at=past_date,
    )
    record_visual_experience(rec_score1, db_path=temp_db_path)

    res_worst = compute_adaptive_adjustment(
        asset_id="asset-worst",
        provider="prov_score1_test",
        search_query="ancient battle",
        video_subject="História",
        current_task_asset_ids=[],
        base_score=80.0,
        db_path=temp_db_path,
    )
    assert res_worst.adaptive_adjustment <= -12.0
    assert "human_score_1_penalty" in res_worst.adaptive_reason


def test_duplicate_penalty(temp_db_path):
    """Verifica penalidade de repetição (-15) no mesmo vídeo ou histórico recente."""
    # Repetição no mesmo vídeo (task atual)
    res_same = compute_adaptive_adjustment(
        asset_id="asset-used-scene-1",
        provider="pexels",
        search_query="nature river",
        video_subject="Natureza",
        current_task_asset_ids=["asset-used-scene-1"],
        base_score=90.0,
        db_path=temp_db_path,
    )
    assert res_same.adaptive_adjustment == -15.0
    assert "same_video" in res_same.adaptive_reason

    # Repetição recente em vídeo anterior
    rec_past = VisualExperienceRecord(
        task_id="task-yesterday",
        video_subject="Natureza",
        scene_index=1,
        asset_id="asset-used-yesterday",
    )
    record_visual_experience(rec_past, db_path=temp_db_path)

    res_past = compute_adaptive_adjustment(
        asset_id="asset-used-yesterday",
        provider="pexels",
        search_query="forest trees",
        video_subject="Natureza",
        current_task_asset_ids=[],
        base_score=90.0,
        db_path=temp_db_path,
    )
    assert res_past.adaptive_adjustment == -15.0
    assert "recent" in res_past.adaptive_reason


def test_query_fallback_penalty(temp_db_path):
    """Verifica penalidade quando query tem histórico frequente de fallback (> 50%)."""
    # Insere 3 registros com fallback_used=True para a mesma query
    for i in range(3):
        rec = VisualExperienceRecord(
            task_id=f"task-fb-{i}",
            video_subject="Espaço",
            scene_index=1,
            search_query="rare nebulas unknown coordinates",
            fallback_used=True,
            fallback_reason="stock_low_confidence",
        )
        record_visual_experience(rec, db_path=temp_db_path)

    res = compute_adaptive_adjustment(
        asset_id="some_asset",
        provider="pexels",
        search_query="rare nebulas unknown coordinates",
        video_subject="Espaço",
        current_task_asset_ids=[],
        base_score=60.0,
        db_path=temp_db_path,
    )
    assert res.adaptive_adjustment <= -5.0
    assert "query_high_fallback_rate" in res.adaptive_reason


def test_provider_success_bonus(temp_db_path):
    """Verifica bônus para provider com taxa de sucesso alta (> 85%) em tema semelhante."""
    for i in range(5):
        rec = VisualExperienceRecord(
            task_id=f"task-prov-{i}",
            video_subject="Exploração Espacial e Astronomia",
            scene_index=1,
            provider="nasa_image_library",
            technical_success=True,
            fallback_used=False,
            human_feedback=HumanFeedback.UNREVIEWED.value,
        )
        record_visual_experience(rec, db_path=temp_db_path)

    res = compute_adaptive_adjustment(
        asset_id="nasa_new_photo",
        provider="nasa_image_library",
        search_query="saturn rings",
        video_subject="Exploração Espacial e Marte",
        current_task_asset_ids=[],
        base_score=70.0,
        db_path=temp_db_path,
    )
    assert res.adaptive_adjustment >= 3.0
    assert "provider_theme_track_record_bonus" in res.adaptive_reason


def test_adaptive_adjustment_cap(temp_db_path):
    """Garante que o ajuste adaptativo nunca ultrapassa a faixa [-15.0, +15.0]."""
    # Caso de bônus acumulados
    for i in range(5):
        rec = VisualExperienceRecord(
            task_id=f"task-bonus-{i}",
            video_subject="Física Quântica",
            scene_index=1,
            asset_id="asset-super-winner",
            provider="super_provider",
            human_feedback=HumanFeedback.GOOD.value,
            human_score=5,
            technical_success=True,
            fallback_used=False,
        )
        record_visual_experience(rec, db_path=temp_db_path)

    res_max = compute_adaptive_adjustment(
        asset_id="asset-super-winner",
        provider="super_provider",
        search_query="quantum particles",
        video_subject="Física Quântica",
        current_task_asset_ids=[],
        base_score=80.0,
        db_path=temp_db_path,
    )
    assert res_max.adaptive_adjustment <= ADAPTIVE_CAP_MAX
    assert res_max.adaptive_adjustment >= ADAPTIVE_CAP_MIN

    # Caso de penalidades acumuladas
    res_min = compute_adaptive_adjustment(
        asset_id="asset-used-many-times",
        provider="failing_provider",
        search_query="bad query with fallback",
        video_subject="Tema X",
        current_task_asset_ids=["asset-used-many-times"],
        base_score=80.0,
        db_path=temp_db_path,
    )
    assert res_min.adaptive_adjustment >= ADAPTIVE_CAP_MIN
    assert res_min.adaptive_adjustment <= ADAPTIVE_CAP_MAX


def test_unrelated_topic_minimal_influence(temp_db_path):
    """Histórico de tema completamente não relacionado não deve conferir bônus temático."""
    for i in range(5):
        rec = VisualExperienceRecord(
            task_id=f"task-cook-{i}",
            video_subject="Culinária e Receitas Italianas",
            scene_index=1,
            provider="special_pasta_source",
            technical_success=True,
            fallback_used=False,
        )
        record_visual_experience(rec, db_path=temp_db_path)

    # Consulta com tema completamente diferente (Aeroespacial)
    res = compute_adaptive_adjustment(
        asset_id="unrelated_asset",
        provider="special_pasta_source",
        search_query="rocket propulsion",
        video_subject="Engenharia Aeroespacial de Foguetes",
        current_task_asset_ids=[],
        base_score=70.0,
        db_path=temp_db_path,
    )
    # Não deve receber provider_theme_track_record_bonus
    assert "provider_theme_track_record_bonus" not in res.adaptive_reason
    assert res.adaptive_adjustment == 0.0


def test_human_feedback_service_and_protection(temp_db_path):
    """Verifica serviço de feedback e proteção de confirmação explícita global."""
    for i in range(1, 4):
        rec = VisualExperienceRecord(
            task_id="task-multi-scene",
            video_subject="Test Video",
            scene_index=i,
            asset_id=f"asset-{i}",
        )
        record_visual_experience(rec, db_path=temp_db_path)

    # 1. Feedback individual na cena 2
    res_scene = record_human_feedback(
        task_id="task-multi-scene",
        scene_index=2,
        feedback="GOOD",
        score=5,
        reason="Cena perfeita",
        db_path=temp_db_path,
    )
    assert res_scene["success"] is True
    assert res_scene["scope"] == "scene"

    exps = get_task_visual_experiences("task-multi-scene", db_path=temp_db_path)
    assert exps[0]["human_feedback"] == "UNREVIEWED"  # Cena 1
    assert exps[1]["human_feedback"] == "GOOD"        # Cena 2
    assert exps[2]["human_feedback"] == "UNREVIEWED"  # Cena 3

    # 2. Feedback global sem confirm_all: NÃO deve alterar as cenas para GOOD
    res_global_unconfirmed = record_human_feedback(
        task_id="task-multi-scene",
        feedback="GOOD",
        score=5,
        confirm_all=False,
        db_path=temp_db_path,
    )
    assert res_global_unconfirmed["success"] is True
    assert res_global_unconfirmed["scope"] == "global_only"

    exps_after_unconfirmed = get_task_visual_experiences("task-multi-scene", db_path=temp_db_path)
    assert exps_after_unconfirmed[0]["human_feedback"] == "UNREVIEWED"
    assert exps_after_unconfirmed[1]["human_feedback"] == "GOOD"
    assert exps_after_unconfirmed[2]["human_feedback"] == "UNREVIEWED"

    # 3. Feedback global COM confirm_all: agora sim altera todas as cenas
    res_global_confirmed = record_human_feedback(
        task_id="task-multi-scene",
        feedback="GOOD",
        score=5,
        confirm_all=True,
        db_path=temp_db_path,
    )
    assert res_global_confirmed["success"] is True
    assert res_global_confirmed["scope"] == "global_and_scenes"

    exps_confirmed = get_task_visual_experiences("task-multi-scene", db_path=temp_db_path)
    for s in exps_confirmed:
        assert s["human_feedback"] == "GOOD"


def test_bootstrap_mars_benchmark(temp_db_path):
    """Verifica bootstrap da homologação canônica de Marte V16.10."""
    bootstrapped_count = bootstrap_mars_benchmark_experience(db_path=temp_db_path)
    assert bootstrapped_count == 7

    # Verifica status global
    task_meta = get_task_feedback("17386147-cb1b-4192-b827-251a1bbd411f", db_path=temp_db_path)
    assert task_meta is not None
    assert task_meta["global_feedback"] == "GOOD"
    assert task_meta["human_score"] == 5 or task_meta.get("global_score") == 5
    assert task_meta["production_homologation"] == "PASS"

    # Verifica cenas: todas devem estar UNREVIEWED por regra de não marcar automaticamente
    scenes = get_task_visual_experiences("17386147-cb1b-4192-b827-251a1bbd411f", db_path=temp_db_path)
    assert len(scenes) == 7
    for sc in scenes:
        assert sc["human_feedback"] == HumanFeedback.UNREVIEWED.value


def test_cli_rate_visual_task(temp_db_path):
    """Executa o script CLI scripts.rate_visual_task via subprocess."""
    # Primeiro popula com o bootstrap
    bootstrap_mars_benchmark_experience(db_path=temp_db_path)

    # 1. Executa CLI para listar
    cmd_list = [
        sys.executable,
        "-m",
        "scripts.rate_visual_task",
        "17386147-cb1b-4192-b827-251a1bbd411f",
        "--list",
        "--db-path",
        temp_db_path,
    ]
    res_list = subprocess.run(cmd_list, capture_output=True, text=True)
    assert res_list.returncode == 0
    assert "STOCK_HIGH_CONFIDENCE" in res_list.stdout

    # 2. Executa CLI para avaliar uma cena
    cmd_rate = [
        sys.executable,
        "-m",
        "scripts.rate_visual_task",
        "17386147-cb1b-4192-b827-251a1bbd411f",
        "--scene",
        "3",
        "--feedback",
        "GOOD",
        "--score",
        "5",
        "--reason",
        "Ótima textura temática",
        "--db-path",
        temp_db_path,
    ]
    res_rate = subprocess.run(cmd_rate, capture_output=True, text=True)
    assert res_rate.returncode == 0

    # Verifica se a cena 3 foi atualizada no banco
    scenes = get_task_visual_experiences("17386147-cb1b-4192-b827-251a1bbd411f", db_path=temp_db_path)
    scene_3 = next(s for s in scenes if s["scene_index"] == 3)
    assert scene_3["human_feedback"] == "GOOD"
    assert scene_3["human_score"] == 5
    assert scene_3["feedback_reason"] == "Ótima textura temática"
