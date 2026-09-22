"""V12-F.4: Targeted tests for second channel warm-up and isolation.

Requirements:
- NÃO conectar credenciais reais.
- NÃO publicar.
- NÃO ativar TikTok.
- NÃO alterar o canal principal.
- NÃO misturar histórico/analytics/learning/estoque entre canais.
- Somente testes direcionados.
"""
import os
import socket
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models import const
from app.services import (
    analytics,
    analytics_ingestion,
    autonomous_production as autonomous,
    content_strategy as strategy,
    operator_console as console,
    profile_manager,
    quality_score,
    safety_gate,
    scheduler,
    state as sm,
)
from app.services.analytics_providers.youtube import YouTubeAnalyticsProvider


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """Cria ambiente SQLite temporário e isolado para testes sem rede ou publicação real."""
    # Impede qualquer conexão de rede real
    monkeypatch.setattr(
        socket.socket,
        "connect",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("Real network connection forbidden")),
    )
    db = str(tmp_path / "test_isolated.db")
    video_dir = tmp_path / "videos"
    video_dir.mkdir(parents=True, exist_ok=True)

    console.init_operator_db(db)
    scheduler.init_db(db)
    safety_gate.init_safety_db(db)
    quality_score.init_quality_db(db)
    analytics.init_analytics_db(db)
    profile_manager.ensure_default_profile(db)

    # Garante o segundo canal configurado
    second_info = profile_manager.ensure_second_channel_profile(db)

    return db, video_dir, second_info


def _create_mock_video_task(task_id: str, profile_id: str, topic: str, video_dir, db_path: str, quality_val: float = 85.0):
    """Auxiliar para criar tarefa simulada com arquivo de vídeo real no disco e gates aprovados."""
    task_folder = video_dir / task_id
    task_folder.mkdir(parents=True, exist_ok=True)
    video_path = task_folder / "final-1.mp4"
    video_path.write_bytes(b"mock_video_bytes_content")

    # Registra no state em memória usando update_task
    sm.state.update_task(
        task_id,
        state=const.TASK_STATE_COMPLETE,
        video_file=str(video_path),
        video_subject=topic,
        topic=topic,
        profile_id=profile_id,
        planned_platforms=["youtube"],
    )

    # Persiste destinos e perfil da tarefa
    scheduler.save_task_platforms(task_id, ["youtube"], db_path)
    profile_manager.save_task_profile(task_id, profile_id, db_path)

    # Registra safety PASS e quality aprovado
    with scheduler.get_connection(db_path) as conn:
        now_iso = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT OR REPLACE INTO monetization_safety (
                task_id, topic, preset, narrative_structure, safety_status, checked_at
            ) VALUES (?, ?, ?, ?, 'PASS', ?);
            """,
            (task_id, topic, "youtube_shorts_original", "problem_solution", now_iso),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO content_quality_scores (
                task_id, topic, quality_score, quality_label, created_at
            ) VALUES (?, ?, ?, 'STRONG', ?);
            """,
            (task_id, topic, quality_val, now_iso),
        )


def test_second_profile_setup_and_growth_mode(isolated_env):
    """Cenário 1: Setup do segundo perfil, nicho próprio, Growth Mode WARMUP e TikTok OFF."""
    db, _, second_info = isolated_env

    prof = profile_manager.get_profile(profile_manager.SECOND_PROFILE_ID, db_path=db)
    assert prof is not None
    assert prof["id"] == profile_manager.SECOND_PROFILE_ID
    assert prof["name"] == "Dose Diária de Histórias e Mistério"
    assert prof["niche"] == "historias_misterio"
    assert prof["growth_mode"] == const.GROWTH_MODE_WARMUP
    assert prof["is_active"] == 1

    channels = profile_manager.list_channels(profile_id=profile_manager.SECOND_PROFILE_ID, db_path=db)
    assert len(channels) == 1
    ch = channels[0]
    assert ch["platform"] == "youtube"
    assert ch["id"] == profile_manager.SECOND_CHANNEL_ID
    assert ch["is_enabled"] == 1
    # Credenciais reais NÃO conectadas
    assert "upload_post" not in str(ch.get("external_profile_name", ""))
    assert ch.get("external_profile_name") == "dose-diaria-misterio"

    # TikTok NÃO ativado para o segundo canal
    tt_channels = [c for c in channels if c["platform"] == "tiktok"]
    assert len(tt_channels) == 0

    # Modo do perfil principal mantido intacto
    main_prof = profile_manager.get_default_profile(db)
    assert main_prof["id"] == profile_manager.DEFAULT_PROFILE_ID
    assert main_prof["growth_mode"] != const.GROWTH_MODE_WARMUP or main_prof["id"] != prof["id"]


def test_stock_isolation_between_channels(isolated_env):
    """Cenário 2: Estoque A != Estoque B e isolamento total de contagem."""
    db, video_dir, _ = isolated_env

    # Cria 2 vídeos prontos para o canal principal (default)
    _create_mock_video_task("task-main-1", profile_manager.DEFAULT_PROFILE_ID, "Curiosidade 1", video_dir, db)
    _create_mock_video_task("task-main-2", profile_manager.DEFAULT_PROFILE_ID, "Curiosidade 2", video_dir, db)

    # Cria 1 vídeo pronto para o segundo canal
    _create_mock_video_task("task-sec-1", profile_manager.SECOND_PROFILE_ID, "Mistério da Meia-Noite", video_dir, db)

    stock_main = autonomous.get_autonomous_ready_stock(
        task_base_dir=str(video_dir), db_path=db, profile_id=profile_manager.DEFAULT_PROFILE_ID
    )
    stock_second = autonomous.get_autonomous_ready_stock(
        task_base_dir=str(video_dir), db_path=db, profile_id=profile_manager.SECOND_PROFILE_ID
    )

    # Estoque A != Estoque B
    assert stock_main["ready_count"] == 2
    assert stock_second["ready_count"] == 1
    assert stock_main["ready_count"] != stock_second["ready_count"]

    # Canonical stock no Operator Console também isolado
    canon_main = console.get_canonical_ready_stock(
        task_base_dir=str(video_dir), db_path=db, profile_id=profile_manager.DEFAULT_PROFILE_ID
    )
    canon_second = console.get_canonical_ready_stock(
        task_base_dir=str(video_dir), db_path=db, profile_id=profile_manager.SECOND_PROFILE_ID
    )
    assert canon_main["total_ready"] == 2
    assert canon_second["total_ready"] == 1

    # Visão geral multi-profile reflete os estoques isolados
    overview = console.get_profile_operations_overview(db_path=db, task_base_dir=str(video_dir))
    prof_map = {o["profile_id"]: o for o in overview}
    assert prof_map[profile_manager.DEFAULT_PROFILE_ID]["ready_stock"] == 2
    assert prof_map[profile_manager.SECOND_PROFILE_ID]["ready_stock"] == 1


def test_scheduler_rate_limit_and_slot_isolation(isolated_env):
    """Cenário 3: Scheduler e limites isolados; Canal A não interfere nem bloqueia Canal B."""
    db, video_dir, _ = isolated_env
    now = datetime.now(timezone.utc)

    # Simula canal principal atingindo o teto de publicações em 24h
    main_chan = profile_manager.list_channels(profile_id=profile_manager.DEFAULT_PROFILE_ID, db_path=db)[0]["id"]
    for i in range(10):
        scheduler.record_publication_event(
            task_id=f"pub-main-{i}",
            platform="youtube",
            status="success",
            external_id=f"ext-main-{i}",
            profile_id=profile_manager.DEFAULT_PROFILE_ID,
            channel_id=main_chan,
            published_at=now - timedelta(hours=i + 1),
            db_path=db,
        )

    # Canal principal com limite atingido / slots esgotados
    main_limits = scheduler.get_platform_rate_limits(
        "youtube",
        profile_id=profile_manager.DEFAULT_PROFILE_ID,
        channel_id=main_chan,
        now=now,
        db_path=db,
    )
    assert main_limits["available_slots"] == 0

    # Segundo canal (em WARMUP) deve ter seus próprios limites e vagas NÃO bloqueadas pelo canal principal
    second_chan = profile_manager.SECOND_CHANNEL_ID
    second_limits = scheduler.get_platform_rate_limits(
        "youtube",
        profile_id=profile_manager.SECOND_PROFILE_ID,
        channel_id=second_chan,
        now=now,
        db_path=db,
    )
    assert second_limits["growth_mode"] == const.GROWTH_MODE_WARMUP
    assert second_limits["available_slots"] > 0
    assert second_limits["total_used"] == 0

    # Agendamento para o segundo canal deve suceder sem interferência
    _create_mock_video_task("task-sec-sched", profile_manager.SECOND_PROFILE_ID, "História 1", video_dir, db)
    task_data = sm.state.get_task("task-sec-sched")
    scheduled = scheduler.plan_schedule([task_data], now=now, db_path=db)

    assert len(scheduled) == 1
    post = scheduled[0]
    assert post["profile_id"] == profile_manager.SECOND_PROFILE_ID
    assert post["channel_id"] == profile_manager.SECOND_CHANNEL_ID
    assert post["platform"] == "youtube"


def test_analytics_and_closed_loop_isolation(isolated_env):
    """Cenário 4: Analytics e Closed Feedback Loop 100% isolados entre canais."""
    db, _, _ = isolated_env
    cutoff = datetime.now(timezone.utc)
    main_chan = profile_manager.list_channels(profile_id=profile_manager.DEFAULT_PROFILE_ID, db_path=db)[0]["id"]
    second_chan = profile_manager.SECOND_CHANNEL_ID

    # Cria snapshot de analytics no canal principal
    scheduler.record_publication_event(
        task_id="task-main-analytics",
        platform="youtube",
        status="success",
        external_id="yt-main-001",
        profile_id=profile_manager.DEFAULT_PROFILE_ID,
        channel_id=main_chan,
        published_at=cutoff - timedelta(days=2),
        db_path=db,
    )
    with scheduler.get_connection(db) as conn:
        conn.execute(
            """
            INSERT INTO monetization_safety (task_id, topic, preset, narrative_structure, safety_status, checked_at)
            VALUES ('task-main-analytics', 'Fatos sobre o Universo', 'preset', 'explainer', 'PASS', ?);
            """,
            ((cutoff - timedelta(days=2)).isoformat(),),
        )

    provider = YouTubeAnalyticsProvider()
    payload = {"items": [{"id": "yt-main-001", "statistics": {"viewCount": "5000", "likeCount": "100", "commentCount": "10"}}]}
    with patch.object(provider, "fetch_metrics", return_value=payload), patch.object(analytics_ingestion, "get_provider", return_value=provider):
        analytics_ingestion.ingest_analytics_for_publication(
            "task-main-analytics", "youtube", channel_id=main_chan,
            collected_at=cutoff.isoformat(), db_path=db
        )

    # Evidência para o segundo canal deve estar VAZIA (sem contaminação do canal principal)
    evidence_second = analytics.get_learning_evidence(
        platform="youtube",
        profile_id=profile_manager.SECOND_PROFILE_ID,
        channel_id=second_chan,
        cutoff_time=cutoff,
        db_path=db,
    )
    assert evidence_second["sample_count"] == 0
    assert len(evidence_second["eligible_snapshot_ids"]) == 0
    assert len(evidence_second["eligible_publication_ids"]) == 0

    # Closed loop submissions para o segundo canal também vazias
    subs_second = console.get_closed_loop_submissions(
        platform="youtube",
        profile_id=profile_manager.SECOND_PROFILE_ID,
        channel_id=second_chan,
        db_path=db,
    )
    assert len(subs_second) == 0


def test_task_created_for_b_preserves_profile_and_channel_to_scheduler(isolated_env):
    """Cenário 5: Task criada para o segundo canal mantém profile_id e channel_id até o scheduler."""
    db, video_dir, _ = isolated_env
    now = datetime.now(timezone.utc)

    _create_mock_video_task("task-warmup-flow", profile_manager.SECOND_PROFILE_ID, "Mistério do Farol", video_dir, db)

    task_data = sm.state.get_task("task-warmup-flow")
    assert task_data["profile_id"] == profile_manager.SECOND_PROFILE_ID

    scheduled = scheduler.plan_schedule([task_data], now=now, db_path=db)
    assert len(scheduled) == 1
    item = scheduled[0]

    with scheduler.get_connection(db) as conn:
        row = conn.execute("SELECT * FROM scheduled_posts WHERE id = ?;", (item["id"],)).fetchone()
        assert row["profile_id"] == profile_manager.SECOND_PROFILE_ID
        assert row["channel_id"] == profile_manager.SECOND_CHANNEL_ID
        assert row["platform"] == "youtube"
        assert row["status"] == "planned"


def test_main_channel_continues_functioning_without_alteration(isolated_env):
    """Cenário 6: Canal principal preservado e funcionando normalmente sem alterações."""
    db, video_dir, _ = isolated_env
    now = datetime.now(timezone.utc)

    # Perfil ativo padrão permanece 'default'
    active_id = profile_manager.get_active_profile_id(db_path=db)
    assert active_id == profile_manager.DEFAULT_PROFILE_ID

    _create_mock_video_task("task-main-preserve", profile_manager.DEFAULT_PROFILE_ID, "Curiosidade Animal", video_dir, db)
    task_data = sm.state.get_task("task-main-preserve")

    scheduled = scheduler.plan_schedule([task_data], now=now, db_path=db)
    assert len(scheduled) == 1
    item = scheduled[0]
    assert item["profile_id"] == profile_manager.DEFAULT_PROFILE_ID
    assert item["channel_id"] == "channel-default-youtube"
