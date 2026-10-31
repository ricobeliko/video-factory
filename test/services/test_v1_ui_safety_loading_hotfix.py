import os
import py_compile
import time
from unittest.mock import MagicMock, patch

import pytest

from app.models import const
from app.models.schema import VideoParams
from app.services import (
    autonomous_production,
    operator_console,
    profile_manager,
    quality_score,
    safety_gate,
    scheduler,
)
import webui.Main as main_module
from webui.components import channel_factory
from webui.components import operator_console as op_ui_module


def _build_mock_st(session_state: dict):
    mock_st = MagicMock()
    mock_st.session_state = session_state

    def fake_columns(spec, **kwargs):
        n = spec if isinstance(spec, int) else len(spec)
        cols = []
        for _ in range(n):
            col = MagicMock()
            col.__enter__ = MagicMock(return_value=col)
            col.__exit__ = MagicMock(return_value=None)
            cols.append(col)
        return cols

    def fake_expander(*args, **kwargs):
        exp = MagicMock()
        exp.__enter__ = MagicMock(return_value=exp)
        exp.__exit__ = MagicMock(return_value=None)
        return exp

    mock_st.columns.side_effect = fake_columns
    mock_st.expander.side_effect = fake_expander
    mock_st.selectbox.side_effect = lambda *args, **kwargs: kwargs.get("options", ["all"])[kwargs.get("index", 0)]
    mock_st.number_input.side_effect = lambda *args, **kwargs: kwargs.get("value", 1)
    mock_st.text_input.side_effect = lambda *args, **kwargs: kwargs.get("value", "")
    mock_st.checkbox.side_effect = lambda *args, **kwargs: session_state.get(kwargs.get("key"), kwargs.get("value", False))
    mock_st.button.return_value = False
    return mock_st


def test_01_syntax_and_imports():
    """1. Compilação (py_compile) e imports limpos dos módulos alterados."""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    targets = [
        os.path.join(root, "webui", "Main.py"),
        os.path.join(root, "webui", "components", "operator_console.py"),
        os.path.join(root, "webui", "components", "channel_factory.py"),
        os.path.join(root, "app", "services", "operator_console.py"),
        os.path.join(root, "app", "services", "autonomous_production.py"),
    ]
    for path in targets:
        py_compile.compile(path, doraise=True)

    assert callable(main_module._render_publication_schedule)
    assert callable(main_module._render_publication_schedule_section)
    assert callable(op_ui_module.render_operator_console)
    assert callable(channel_factory.render_channel_factory)
    assert callable(operator_console.render_pass_scope)


def test_02_autopilot_zero_ideas_no_unbound_local_error(tmp_path):
    """2. _render_autopilot_section com autopilot_ideas = [] não lança UnboundLocalError e desabilita add_queue_btn."""
    db_path = str(tmp_path / "test_ap_empty.db")
    scheduler.init_db(db_path)
    quality_score.init_quality_db(db_path)
    profile_manager.init_profile_db(db_path)

    session_state = {
        "autopilot_ideas": [],
        "autopilot_niche_input": "Mistérios",
    }
    mock_st = _build_mock_st(session_state)
    params = VideoParams(video_subject="")

    with patch.object(scheduler, "get_db_path", return_value=db_path), \
         patch.object(main_module, "st", mock_st), \
         patch.object(main_module, "_collect_task_summaries", return_value=[]), \
         patch.object(main_module.webui_task, "submit_generation") as spy_submit:
        main_module._render_autopilot_section(
            params=params,
            voice_mode="tts",
            uploaded_audio_file=None,
            uploaded_bgm_file=None,
            has_local_materials=False,
        )
        spy_submit.assert_not_called()

    add_queue_calls = [
        c for c in mock_st.button.call_args_list
        if c.kwargs.get("key") == "autopilot_add_queue_btn"
    ]
    assert len(add_queue_calls) == 1
    assert add_queue_calls[0].kwargs["disabled"] is True


def test_03_autopilot_with_ideas_renders_add_queue_and_no_passive_persist(tmp_path):
    """3. _render_autopilot_section com ideias disponíveis habilita Add Selected to Queue fora do else e usa persist=False no render."""
    db_path = str(tmp_path / "test_ap_ideas.db")
    scheduler.init_db(db_path)
    quality_score.init_quality_db(db_path)
    profile_manager.init_profile_db(db_path)

    session_state = {
        "autopilot_ideas": [{"topic": "O segredo do Triângulo das Bermudas", "selected": True}],
        "autopilot_niche_input": "Mistérios",
    }
    mock_st = _build_mock_st(session_state)
    params = VideoParams(video_subject="")

    with patch.object(scheduler, "get_db_path", return_value=db_path), \
         patch.object(main_module, "st", mock_st), \
         patch.object(main_module, "_is_primary_ui_instance", return_value=True), \
         patch.object(main_module, "_collect_task_summaries", return_value=[]), \
         patch.object(main_module.webui_task, "has_active_generation_tasks", return_value=False), \
         patch.object(main_module, "_has_active_generation", return_value=False), \
         patch.object(main_module.autopilot, "evaluate_idea_quality", wraps=main_module.autopilot.evaluate_idea_quality) as spy_q, \
         patch.object(main_module.autopilot, "evaluate_idea_strategy", wraps=main_module.autopilot.evaluate_idea_strategy) as spy_s:
        main_module._render_autopilot_section(
            params=params,
            voice_mode="tts",
            uploaded_audio_file=None,
            uploaded_bgm_file=None,
            has_local_materials=False,
        )

        assert spy_q.called
        for c in spy_q.call_args_list:
            assert c.kwargs.get("persist") is False

        assert spy_s.called
        for c in spy_s.call_args_list:
            assert c.kwargs.get("persist") is False

    add_queue_calls = [
        c for c in mock_st.button.call_args_list
        if c.kwargs.get("key") == "autopilot_add_queue_btn"
    ]
    assert len(add_queue_calls) == 1
    assert add_queue_calls[0].kwargs["disabled"] is False


def test_04_publication_schedule_section_preserves_and_persists_settings(tmp_path):
    """4. _render_publication_schedule_section exibe e persiste scheduler_enabled, auto_publish_enabled e dry_run."""
    db_path = str(tmp_path / "test_pub_sched.db")
    scheduler.init_db(db_path)
    scheduler.set_setting("scheduler_enabled", False, db_path=db_path)
    scheduler.set_setting("auto_publish_enabled", False, db_path=db_path)
    scheduler.set_setting("dry_run", True, db_path=db_path)

    session_state = {}
    mock_st = _build_mock_st(session_state)

    func = getattr(main_module._render_publication_schedule, "__wrapped__", main_module._render_publication_schedule)
    with patch.object(scheduler, "get_db_path", return_value=db_path), \
         patch.object(main_module, "st", mock_st), \
         patch.object(main_module, "_is_primary_ui_instance", return_value=True), \
         patch.object(main_module, "_collect_task_summaries", return_value=[]), \
         patch.object(scheduler, "start_scheduler_worker") as spy_worker:
        func()
        # Com scheduler_enabled=False, NÃO deve iniciar worker
        spy_worker.assert_not_called()

    assert session_state["scheduler_enabled_cb"] is False
    assert session_state["scheduler_auto_publish_cb"] is False
    assert session_state["scheduler_dry_run_cb"] is True

    # Interação explícita em PRIMARY persiste no SQLite
    with patch.object(scheduler, "get_db_path", return_value=db_path), \
         patch.object(main_module, "st", mock_st), \
         patch.object(main_module, "_is_primary_ui_instance", return_value=True), \
         patch.object(scheduler, "start_scheduler_worker") as spy_worker:
        session_state["scheduler_enabled_cb"] = True
        main_module._on_scheduler_enabled_changed()
        assert scheduler.get_all_settings(db_path=db_path)["scheduler_enabled"] is True
        spy_worker.assert_called_once_with(interval_seconds=30)

        session_state["scheduler_auto_publish_cb"] = True
        main_module._on_auto_publish_enabled_changed()
        assert scheduler.get_all_settings(db_path=db_path)["auto_publish_enabled"] is True

        session_state["scheduler_dry_run_cb"] = False
        main_module._on_dry_run_changed()
        assert scheduler.get_all_settings(db_path=db_path)["dry_run"] is False


def test_05_view_only_blocks_publication_schedule_mutations(tmp_path):
    """5. Em SECONDARY_VIEW_ONLY, controles ficam desabilitados e callbacks não alteram o SQLite."""
    db_path = str(tmp_path / "test_view_only.db")
    scheduler.init_db(db_path)
    scheduler.set_setting("scheduler_enabled", False, db_path=db_path)
    scheduler.set_setting("auto_publish_enabled", False, db_path=db_path)
    scheduler.set_setting("dry_run", True, db_path=db_path)

    session_state = {
        "scheduler_enabled_cb": True,
        "scheduler_auto_publish_cb": True,
        "scheduler_dry_run_cb": False,
    }
    mock_st = _build_mock_st(session_state)

    with patch.object(scheduler, "get_db_path", return_value=db_path), \
         patch.object(main_module, "st", mock_st), \
         patch.object(main_module, "_is_primary_ui_instance", return_value=False):
        main_module._on_scheduler_enabled_changed()
        main_module._on_auto_publish_enabled_changed()
        main_module._on_dry_run_changed()

        settings = scheduler.get_all_settings(db_path=db_path)
        assert settings["scheduler_enabled"] is False
        assert settings["auto_publish_enabled"] is False
        assert settings["dry_run"] is True

        func = getattr(main_module._render_publication_schedule, "__wrapped__", main_module._render_publication_schedule)
        with patch.object(main_module, "_collect_task_summaries", return_value=[]):
            func()

    cb_calls = {
        c.kwargs.get("key"): c.kwargs.get("disabled")
        for c in mock_st.checkbox.call_args_list
        if c.kwargs.get("key") in ("scheduler_enabled_cb", "scheduler_auto_publish_cb", "scheduler_dry_run_cb")
    }
    assert cb_calls == {
        "scheduler_enabled_cb": True,
        "scheduler_auto_publish_cb": True,
        "scheduler_dry_run_cb": True,
    }


def test_06_paused_factory_does_not_start_scheduler_worker_or_polling(tmp_path):
    """6. Fábrica em PAUSED não inicia start_scheduler_worker e usa fragmentos estáticos no Operator Console."""
    db_path = str(tmp_path / "test_paused.db")
    scheduler.init_db(db_path)
    operator_console.init_operator_db(db_path)
    scheduler.set_setting("scheduler_enabled", True, db_path=db_path)
    scheduler.set_setting("factory_state", operator_console.FACTORY_STATE_PAUSED, db_path=db_path)

    session_state = {}
    mock_st = _build_mock_st(session_state)

    func = getattr(main_module._render_publication_schedule, "__wrapped__", main_module._render_publication_schedule)
    with patch.object(scheduler, "get_db_path", return_value=db_path), \
         patch.object(main_module, "st", mock_st), \
         patch.object(main_module, "_is_primary_ui_instance", return_value=True), \
         patch.object(main_module, "_collect_task_summaries", return_value=[]), \
         patch.object(scheduler, "start_scheduler_worker") as spy_worker:
        assert main_module._should_start_scheduler_worker() is False
        func()
        spy_worker.assert_not_called()

    # Verifica que render_operator_console em PAUSED chama _render_command_header_and_telemetry_paused e _render_queues_paused
    with patch.object(scheduler, "get_db_path", return_value=db_path), \
         patch.object(op_ui_module, "st", mock_st), \
         patch.object(operator_console, "is_primary_instance", return_value=True), \
         patch.object(operator_console, "is_factory_paused", return_value=True), \
         patch.object(op_ui_module, "_render_command_header_and_telemetry_paused") as spy_hdr_paused, \
         patch.object(op_ui_module, "_render_queues_paused") as spy_q_paused, \
         patch.object(op_ui_module, "_render_live_operations_idle"), \
         patch.object(op_ui_module, "_render_profile_management_section"), \
         patch.object(op_ui_module, "_render_provider_health_section"), \
         patch.object(op_ui_module, "_render_automatic_analytics_section"), \
         patch.object(op_ui_module, "_render_autonomous_production_section"), \
         patch.object(op_ui_module, "_render_copyright_provenance_section"), \
         patch.object(op_ui_module, "_render_clip_mode_section"), \
         patch.object(op_ui_module, "_render_observability_section"), \
         patch.object(op_ui_module, "_render_tabs_section"):
        op_ui_module.render_operator_console()
        spy_hdr_paused.assert_called_once()
        spy_q_paused.assert_called_once()


def test_07_ca03_regression_four_traditional_authorized_two_quiz_blocked(tmp_path):
    """7. Regressão CA-03: 4 canais tradicionais autorizados (1) e 2 canais Quiz bloqueados (0) respeitados."""
    db_path = str(tmp_path / "test_ca03.db")
    scheduler.init_db(db_path)
    profile_manager.init_profile_db(db_path)

    profiles_cfg = [
        ("default", "Video Factory Default", "default", "Geral"),
        ("profile-historias-misterio", "Mistérios", "historias-misterio", "Mistérios"),
        ("profile-quiz-dilema", "Quiz Dilema", "quiz-dilema", "Quiz"),
        ("profile-quiz-papel", "Quiz Papel", "quiz-papel", "Quiz"),
    ]
    channels_cfg = [
        ("channel-default-youtube", "default", "youtube", 1),
        ("channel-default-tiktok", "default", "tiktok", 1),
        ("channel-85c572f3bdad", "profile-historias-misterio", "tiktok", 1),
        ("channel-historias-misterio-youtube", "profile-historias-misterio", "youtube", 1),
        ("channel-6224c41b78e4", "profile-quiz-dilema", "tiktok", 0),
        ("channel-4e72dde876d4", "profile-quiz-papel", "tiktok", 0),
    ]
    with scheduler.get_connection(db_path) as conn:
        for pid, pname, pslug, pniche in profiles_cfg:
            conn.execute(
                """
                INSERT OR REPLACE INTO content_profiles (
                    id, name, slug, niche, language, region,
                    default_preset, growth_mode, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'pt-BR', 'BR', 'cross_platform', 'normal', 1, '2026-10-20T00:00:00Z', '2026-10-20T00:00:00Z');
                """,
                (pid, pname, pslug, pniche),
            )
        for cid, pid, plat, auth in channels_cfg:
            conn.execute(
                """
                INSERT OR REPLACE INTO publishing_channels (
                    id, profile_id, platform, display_name, external_profile_name,
                    is_enabled, auto_publish_authorized, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?, '2026-10-20T00:00:00Z', '2026-10-20T00:00:00Z');
                """,
                (cid, pid, plat, cid, cid, auth),
            )

    # Com scheduler_enabled=True mas auto_publish_enabled=False -> run_scheduler_cycle bloqueia por auto_publish_disabled
    scheduler.set_setting("scheduler_enabled", True, db_path=db_path)
    scheduler.set_setting("auto_publish_enabled", False, db_path=db_path)
    cycle_res = scheduler.run_scheduler_cycle(db_path=db_path)
    assert cycle_res["status"] == "skipped"
    assert cycle_res["reason"] == "auto_publish_disabled"

    # Valida a autorização individual por canal (CA-03): 4 tradicionais True, 2 Quiz False
    scheduler.set_setting("auto_publish_enabled", True, db_path=db_path)
    for cid, pid, plat, auth in channels_cfg:
        expected = bool(auth == 1)
        actual = scheduler.is_channel_auto_publish_authorized(cid, profile_id=pid, platform=plat, db_path=db_path)
        assert actual is expected, f"Falha CA-03 no canal {cid}: esperado {expected}, obtido {actual}"
    operator_console.reset_instance_for_testing()


def test_08_render_pass_scope_performance_and_zero_persistent_cache(tmp_path):
    """8. Medição Antes/Depois de render_pass_scope e comprovação de ZERO cache persistente fora do escopo."""
    db_path = str(tmp_path / "test_perf.db")
    task_base_dir = str(tmp_path / "tasks")
    os.makedirs(task_base_dir, exist_ok=True)

    scheduler.init_db(db_path)
    operator_console.init_operator_db(db_path)
    quality_score.init_quality_db(db_path)
    safety_gate.init_safety_db(db_path)
    profile_manager.init_profile_db(db_path)

    # Cria 3 perfis e canais YouTube habilitados diretamente no SQLite de teste
    prof_ids = ["default", "prof-misterio", "prof-curiosidades"]
    with scheduler.get_connection(db_path) as conn:
        for pid in prof_ids:
            cid = "channel-default-youtube" if pid == "default" else f"chan-{pid}"
            conn.execute(
                """
                INSERT OR REPLACE INTO content_profiles (
                    id, name, slug, niche, language, region,
                    default_preset, growth_mode, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, 'Geral', 'pt-BR', 'BR', 'cross_platform', 'normal', 1, '2026-10-20T00:00:00Z', '2026-10-20T00:00:00Z');
                """,
                (pid, pid, pid),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO publishing_channels (
                    id, profile_id, platform, display_name, external_profile_name,
                    is_enabled, auto_publish_authorized, created_at, updated_at
                ) VALUES (?, ?, 'youtube', ?, ?, 1, 1, '2026-10-20T00:00:00Z', '2026-10-20T00:00:00Z');
                """,
                (cid, pid, f"YT {pid}", f"yt-{pid}"),
            )

    # Popula 30 tasks completas com vídeo físico, script.json, safety PASS e quality GOOD
    for i in range(30):
        tid = f"task-perf-{i:02d}"
        pid = prof_ids[i % len(prof_ids)]
        cid = "channel-default-youtube" if pid == "default" else f"chan-{pid}"
        t_dir = os.path.join(task_base_dir, tid)
        os.makedirs(t_dir, exist_ok=True)
        with open(os.path.join(t_dir, "final-1.mp4"), "wb") as vf:
            vf.write(b"\x00" * 128)
        with open(os.path.join(t_dir, "script.json"), "w", encoding="utf-8") as sf:
            sf.write(f'{{"params": {{"video_subject": "Tema {i}", "profile_id": "{pid}", "channel_id": "{cid}"}}}}')

        with scheduler.get_connection(db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO monetization_safety (task_id, preset, safety_status, checked_at) VALUES (?, 'cross_platform', 'PASS', '2026-10-20T00:00:00Z');",
                (tid,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO content_quality_scores (task_id, topic, quality_score, quality_label, created_at) VALUES (?, ?, 82.0, 'GOOD', '2026-10-20T00:00:00Z');",
                (tid, f"Tema {i}"),
            )
            conn.execute(
                "INSERT OR REPLACE INTO task_profiles (task_id, profile_id, created_at) VALUES (?, ?, '2026-10-20T00:00:00Z');",
                (tid, pid),
            )
        scheduler.save_task_platforms(tid, ["youtube"], db_path=db_path)

    def simulate_single_page_render_queries():
        # Simula exatamente as chamadas feitas em 1 carregamento completo da página:
        # 1. Topbar + Autopilot + Publication Schedule (_collect_task_summaries x3)
        main_module._collect_task_summaries(limit=20)
        main_module._collect_task_summaries(limit=1000)
        main_module._collect_task_summaries(limit=1000)
        # 2. Channel Factory + Operator Console (11 leituras de ready stock + 2 system_status + 2 queue summary)
        for pid in prof_ids:
            operator_console.get_canonical_ready_stock(task_base_dir=task_base_dir, db_path=db_path, profile_id=pid)
        operator_console.get_system_status(db_path=db_path, profile_id="default")
        operator_console.get_system_status(db_path=db_path, profile_id="default")
        operator_console.get_generation_queue_summary()
        operator_console.get_generation_queue_summary()
        operator_console.get_profile_operations_overview(db_path=db_path, task_base_dir=task_base_dir)
        for pid in prof_ids:
            operator_console.get_canonical_ready_stock(task_base_dir=task_base_dir, db_path=db_path, profile_id=pid)

    with patch.object(scheduler, "get_db_path", return_value=db_path), \
         patch.object(main_module.utils, "task_dir", return_value=task_base_dir), \
         patch.object(operator_console.utils, "task_dir", return_value=task_base_dir), \
         patch.object(autonomous_production.utils, "task_dir", return_value=task_base_dir):

        # Garante cache de provedores aquecido igualmente para comparar o custo das consultas por render
        operator_console.get_provider_health_summary(db_path=db_path)

        # A) SEM render_pass_scope (Antes)
        assert operator_console.get_render_pass_cache() is None
        with patch.object(autonomous_production, "_recover_waiting_task", wraps=autonomous_production._recover_waiting_task) as spy_rec_before, \
             patch.object(main_module, "_scan_history_tasks", wraps=main_module._scan_history_tasks) as spy_scan_before:
            t0 = time.perf_counter()
            simulate_single_page_render_queries()
            ms_before = (time.perf_counter() - t0) * 1000.0
            recover_calls_before = spy_rec_before.call_count
            scan_calls_before = spy_scan_before.call_count

        # B) COM render_pass_scope (Depois)
        with patch.object(autonomous_production, "_recover_waiting_task", wraps=autonomous_production._recover_waiting_task) as spy_rec_after, \
             patch.object(main_module, "_scan_history_tasks", wraps=main_module._scan_history_tasks) as spy_scan_after:
            t1 = time.perf_counter()
            with operator_console.render_pass_scope():
                assert operator_console.get_render_pass_cache() is not None
                simulate_single_page_render_queries()
            ms_after = (time.perf_counter() - t1) * 1000.0
            recover_calls_after = spy_rec_after.call_count
            scan_calls_after = spy_scan_after.call_count

        # Fora do bloco with, o cache efêmero DEVE ser None (ZERO cache persistente)
        assert operator_console.get_render_pass_cache() is None

        print(
            f"\n[HOTFIX PERF METRICS] "
            f"_recover_waiting_task: {recover_calls_before} -> {recover_calls_after} calls | "
            f"_scan_history_tasks: {scan_calls_before} -> {scan_calls_after} calls | "
            f"Render queries time: {ms_before:.1f}ms -> {ms_after:.1f}ms"
        )

        assert recover_calls_before <= 30 * 11  # <= 330 chamadas (menos é melhor: get_profile_operations_overview já usa escopo interno)
        assert recover_calls_after == 30        # Apenas 1 varredura completa = 30 chamadas (redução de 11x)
        assert scan_calls_before == 3
        assert scan_calls_after == 1
        assert ms_after < ms_before
    operator_console.reset_instance_for_testing()
