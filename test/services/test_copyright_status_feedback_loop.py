"""Teste direcionado V14-B.2 — Status de Copyright e Exclusão no Closed Feedback Loop.

Cobre os 12 requisitos obrigatórios da especificação:
1. unknown => closed loop excluded (com razão explícita 'copyright_unknown')
2. clean_manual => copyright permite continuar avaliação normal (incluído em samples se válido)
3. claimed => excluded (com razão explícita 'copyright_claimed')
4. blocked => excluded (com razão explícita 'copyright_blocked', incluindo teste com task real)
5. strike => excluded (com razão explícita 'copyright_strike')
6. status manual persiste em operational_events com metadata auditável
7. repeated same status is idempotent (idempotent=True, sem eventos duplicados)
8. source=operator (auditado corretamente)
9. metrics/history não são apagados (content_analytics e publication_events preservados)
10. profile/channel isolation preservado
11. nenhuma rede/API/publicação (bloqueio estrito de socket)
12. Presenter continua OFF (avatar_mode='none' padrão, Nox dormant)
"""

import json
import math
import socket
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models.schema import VideoParams
from app.services import (
    analytics,
    analytics_ingestion,
    copyright_gate,
    operator_console,
    profile_manager,
    quality_score,
    safety_gate,
    scheduler,
)
from app.services.analytics_providers.youtube import YouTubeAnalyticsProvider


@pytest.fixture
def test_env(tmp_path, monkeypatch):
    """Configura ambiente SQLite temporário e bloqueia estritamente qualquer acesso de rede."""
    monkeypatch.setattr(
        socket.socket,
        "connect",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("Network access forbidden")),
    )

    db_path = str(tmp_path / "copyright_test.db")
    operator_console.init_operator_db(db_path)
    profile_manager.ensure_default_profile(db_path)
    analytics.init_analytics_db(db_path)
    safety_gate.init_safety_db(db_path)
    quality_score.init_quality_db(db_path)

    # Garante papel PRIMARY na instância de teste para autorizar operações operacionais
    monkeypatch.setattr(operator_console, "require_primary_instance", lambda *a, **k: None)
    monkeypatch.setattr(operator_console, "is_primary_instance", lambda *a, **k: True)

    with scheduler.get_connection(db_path) as conn:
        channel = conn.execute(
            "SELECT id FROM publishing_channels WHERE platform='youtube' AND profile_id='default'"
        ).fetchone()[0]

    scope = {"platform": "youtube", "profile_id": "default", "channel_id": channel}
    cutoff = datetime.now(timezone.utc) + timedelta(minutes=1)
    counter = [0]

    def add_video(
        task_id: str = None,
        external_id: str = None,
        views: int = 100,
        topic: str = "Como funciona o oceano",
        structure: str = "explainer",
        age_hours: int = 72,
        copyright_status: str = None,
        note: str = None,
        channel_id: str = channel,
        profile_id: str = "default",
    ):
        counter[0] += 1
        i = counter[0]
        t_id = task_id or f"task-{i}"
        ext_id = external_id or f"video{i:06d}"
        published = cutoff - timedelta(days=4)

        profile_manager.save_task_profile(t_id, profile_id, db_path)

        # Grava publicação bem-sucedida
        scheduler.record_publication_event(
            task_id=t_id,
            platform="youtube",
            status="success",
            external_id=ext_id,
            profile_id=profile_id,
            channel_id=channel_id,
            privacy_status="public",
            published_at=published,
            db_path=db_path,
        )
        with scheduler.get_connection(db_path) as conn:
            pub_id = conn.execute(
                "SELECT id FROM publication_events WHERE task_id = ? AND platform = 'youtube' ORDER BY id DESC LIMIT 1",
                (t_id,),
            ).fetchone()[0]

        # Grava safety PASS
        with scheduler.get_connection(db_path) as conn:
            conn.execute(
                "INSERT INTO monetization_safety(task_id, topic, preset, narrative_structure, safety_status, checked_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (t_id, topic, "youtube_shorts_original", structure, "PASS", published.isoformat()),
            )
            conn.execute(
                "INSERT INTO content_quality_scores(task_id, topic, quality_score, quality_label, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (t_id, topic, 80, "GOOD", published.isoformat()),
            )

        # Ingestão de analytics fake
        provider = YouTubeAnalyticsProvider()
        payload = {
            "items": [
                {
                    "id": ext_id,
                    "statistics": {
                        "viewCount": str(views),
                        "likeCount": "5",
                        "commentCount": "2",
                    },
                }
            ]
        }
        with patch.object(provider, "fetch_metrics", return_value=payload), patch.object(
            analytics_ingestion, "get_provider", return_value=provider
        ):
            analytics_ingestion.ingest_analytics_for_publication(
                t_id,
                "youtube",
                channel_id=channel_id,
                collected_at=(published + timedelta(hours=age_hours)).isoformat(),
                db_path=db_path,
            )

        # Se copyright_status foi informado, aplica via operador
        if copyright_status is not None:
            operator_console.set_publication_copyright_status_op(
                publication_event_id=pub_id,
                copyright_status=copyright_status,
                note=note,
                db_path=db_path,
            )

        return pub_id, t_id, ext_id

    return db_path, scope, cutoff, add_video


def test_copyright_status_persistence_idempotence_and_operator_source(test_env):
    """Itens 6, 7, 8: Status persiste em operational_events, idempotência e source=operator."""
    db_path, scope, cutoff, add_video = test_env

    pub_id, task_id, ext_id = add_video(views=100)

    # 1. Antes de definir: status padrão é 'unknown', source é None
    initial_status = copyright_gate.get_publication_copyright_status(
        publication_event_id=pub_id, db_path=db_path
    )
    assert initial_status["copyright_status"] == copyright_gate.COPYRIGHT_STATUS_UNKNOWN
    assert initial_status["source"] is None
    assert initial_status["note"] is None

    # 2. Define status manual 'clean_manual' por operator
    res1 = operator_console.set_publication_copyright_status_op(
        publication_event_id=pub_id,
        copyright_status=copyright_gate.COPYRIGHT_STATUS_CLEAN_MANUAL,
        note="Revisão manual de direitos autorais OK",
        source="operator",
        db_path=db_path,
    )
    assert res1["success"] is True
    assert res1["idempotent"] is False
    assert res1["copyright_status"] == "clean_manual"
    assert res1["source"] == "operator"
    assert res1["note"] == "Revisão manual de direitos autorais OK"

    # 3. Consulta e valida persistência
    saved = copyright_gate.get_publication_copyright_status(
        publication_event_id=pub_id, db_path=db_path
    )
    assert saved["copyright_status"] == "clean_manual"
    assert saved["source"] == "operator"
    assert saved["note"] == "Revisão manual de direitos autorais OK"
    assert saved["timestamp"] is not None

    # 4. Idempotência: reaplicar o mesmo status e mesma nota não gera novo evento
    with scheduler.get_connection(db_path) as conn:
        count_before = conn.execute(
            "SELECT COUNT(*) FROM operational_events WHERE event_type = 'PUBLICATION_COPYRIGHT_STATUS_SET'"
        ).fetchone()[0]

    res2 = operator_console.set_publication_copyright_status_op(
        publication_event_id=pub_id,
        copyright_status="clean_manual",
        note="Revisão manual de direitos autorais OK",
        db_path=db_path,
    )
    assert res2["success"] is True
    assert res2["idempotent"] is True

    with scheduler.get_connection(db_path) as conn:
        count_after = conn.execute(
            "SELECT COUNT(*) FROM operational_events WHERE event_type = 'PUBLICATION_COPYRIGHT_STATUS_SET'"
        ).fetchone()[0]
    assert count_after == count_before

    # 5. Validação de status inválido
    with pytest.raises(ValueError, match="copyright_status inválido"):
        operator_console.set_publication_copyright_status_op(
            publication_event_id=pub_id,
            copyright_status="invalid_status_xyz",
            db_path=db_path,
        )


def test_closed_feedback_loop_copyright_exclusion_rules(test_env):
    """Itens 1, 2, 3, 4, 5: Exclusão no Closed Loop para unknown, claimed, blocked, strike e inclusão de clean_manual."""
    db_path, scope, cutoff, add_video = test_env

    # 1. Vídeo sem status (legado / unknown)
    _, t_unk, _ = add_video(copyright_status=None)

    # 2. Vídeo marcado 'clean_manual'
    _, t_clean, _ = add_video(copyright_status=copyright_gate.COPYRIGHT_STATUS_CLEAN_MANUAL, note="Auditado")

    # 3. Vídeo marcado 'claimed'
    _, t_claimed, _ = add_video(copyright_status=copyright_gate.COPYRIGHT_STATUS_CLAIMED, note="Content ID claim")

    # 4. Vídeo marcado 'blocked' (simulando a evidência real conhecida XVy8MbpJFqw / 815b0958-b94e-457b-932d-b10dfb0e8dba)
    _, t_blocked, _ = add_video(
        task_id="815b0958-b94e-457b-932d-b10dfb0e8dba",
        external_id="XVy8MbpJFqw",
        copyright_status=copyright_gate.COPYRIGHT_STATUS_BLOCKED,
        note="Bloqueado mundialmente YouTube Studio",
    )

    # 5. Vídeo marcado 'strike'
    _, t_strike, _ = add_video(copyright_status=copyright_gate.COPYRIGHT_STATUS_STRIKE, note="Copyright strike")

    # Executa get_learning_evidence
    evidence = analytics.get_learning_evidence(**scope, cutoff_time=cutoff, db_path=db_path)
    excluded_reasons = evidence.get("excluded_counts_by_reason", {})

    # Valida razões explícitas de exclusão (Item 8 da spec)
    assert excluded_reasons.get("copyright_unknown") == 1, "Status unknown deve ser excluído como copyright_unknown"
    assert excluded_reasons.get("copyright_claimed") == 1, "Status claimed deve ser excluído como copyright_claimed"
    assert excluded_reasons.get("copyright_blocked") == 1, "Status blocked deve ser excluído como copyright_blocked"
    assert excluded_reasons.get("copyright_strike") == 1, "Status strike deve ser excluído como copyright_strike"

    # Valida que apenas o vídeo 'clean_manual' passou do filtro de copyright e chegou a samples
    samples = evidence.get("samples", [])
    assert len(samples) == 1
    assert samples[0]["task_id"] == t_clean
    assert samples[0]["copyright_status"] == "clean_manual"

    # Valida que a task bloqueada conhecida foi de fato excluída do loop de feedback
    sample_tasks = [s["task_id"] for s in samples]
    assert "815b0958-b94e-457b-932d-b10dfb0e8dba" not in sample_tasks


def test_metrics_and_history_preserved(test_env):
    """Item 9: Métricas e histórico de publicação NÃO são apagados ou modificados."""
    db_path, scope, cutoff, add_video = test_env

    pub_id, task_id, ext_id = add_video(
        views=5432,
        copyright_status=copyright_gate.COPYRIGHT_STATUS_BLOCKED,
        note="Blocked post-publish",
    )

    # Executa Closed Feedback Loop
    _ = analytics.get_learning_evidence(**scope, cutoff_time=cutoff, db_path=db_path)

    # Verifica que registros em publication_events e content_analytics continuam intactos
    with scheduler.get_connection(db_path) as conn:
        pub_row = conn.execute("SELECT * FROM publication_events WHERE id = ?", (pub_id,)).fetchone()
        assert pub_row is not None
        assert pub_row["status"] == "success"
        assert pub_row["external_id"] == ext_id

        analytics_row = conn.execute("SELECT * FROM content_analytics WHERE task_id = ?", (task_id,)).fetchone()
        assert analytics_row is not None
        assert analytics_row["views"] == 5432
        assert analytics_row["likes"] == 5
        assert analytics_row["comments"] == 2


def test_channel_profile_isolation(test_env):
    """Item 10: Isolamento entre perfis e canais é rigorosamente preservado."""
    db_path, scope_a, cutoff, add_video = test_env

    # Cria segundo perfil e segundo canal no mesmo banco
    with scheduler.get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO content_profiles (id, slug, name, is_active, created_at, updated_at) "
            "VALUES ('profile-b', 'canal-b', 'Canal B', 1, ?, ?)",
            (cutoff.isoformat(), cutoff.isoformat()),
        )
        conn.execute(
            "INSERT INTO publishing_channels (id, profile_id, platform, display_name, is_enabled, created_at, updated_at) "
            "VALUES ('channel-b-youtube', 'profile-b', 'youtube', 'Canal B YT', 1, ?, ?)",
            (cutoff.isoformat(), cutoff.isoformat()),
        )

    scope_b = {"platform": "youtube", "profile_id": "profile-b", "channel_id": "channel-b-youtube"}

    # Vídeo no Canal A com clean_manual
    add_video(
        views=150,
        copyright_status=copyright_gate.COPYRIGHT_STATUS_CLEAN_MANUAL,
        channel_id=scope_a["channel_id"],
        profile_id="default",
    )

    # Vídeo no Canal B com blocked
    add_video(
        views=300,
        copyright_status=copyright_gate.COPYRIGHT_STATUS_BLOCKED,
        channel_id=scope_b["channel_id"],
        profile_id="profile-b",
    )

    ev_a = analytics.get_learning_evidence(**scope_a, cutoff_time=cutoff, db_path=db_path)
    ev_b = analytics.get_learning_evidence(**scope_b, cutoff_time=cutoff, db_path=db_path)

    # Canal A tem 1 sample elegível e 0 blocked
    assert len(ev_a.get("samples", [])) == 1
    assert ev_a.get("excluded_counts_by_reason", {}).get("copyright_blocked", 0) == 0

    # Canal B tem 0 samples elegíveis e 1 blocked
    assert len(ev_b.get("samples", [])) == 0
    assert ev_b.get("excluded_counts_by_reason", {}).get("copyright_blocked") == 1


def test_presenter_remains_off_and_dormant():
    """Item 12: Presenter / Nox continua estritamente OFF (DORMANT)."""
    # 1. Parâmetros de vídeo padrão mantêm avatar_mode = 'none'
    params = VideoParams(video_subject="Teste")
    assert params.avatar_mode == "none"

    # 2. Resumo de copyright provenance summary
    summary = copyright_gate.get_copyright_provenance_summary()
    assert summary["presenter_mode"] == "none"
    assert summary["presenter_character_id"] == "none"
    assert summary["feedback_loop_eligible"] is False  # unknown fail-closed
