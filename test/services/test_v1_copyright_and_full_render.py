"""
test/services/test_v1_copyright_and_full_render.py
==================================================
Suíte direcionada do Hotfix V1 — Copyright + Renderização Completa:
1. Reproduz e valida a correção do AttributeError ('list' object has no attribute 'get')
   quando asset_provenance é persistido como lista pelo pipeline Quiz.
2. Cobre os 5 cenários obrigatórios de asset_provenance:
   - dict válido
   - list válida (Quiz ImageProvenance e Paper Quiz)
   - lista vazia ([])
   - dados malformados / formatos desconhecidos
   - proveniência ausente (None)
3. Valida a renderização integrada na ordem exata:
   1. Channel Factory
   2. Console Operacional completo (incluindo Direitos Autorais e Proveniência, Clip Mode, Observabilidade e Abas)
   3. Agenda de Publicação
   4. Trend Radar e Analytics
   5. Autopilot com e sem ideias
4. Comprova as garantias de segurança operacional:
   - PAUSED não inicia Scheduler nem geração
   - Nenhuma chamada a provedores externos
   - Dois canais Quiz (channel-6224c41b78e4, channel-4e72dde876d4) permanecem bloqueados
   - Nenhum registro de copyright desconhecido ou malformado é aprovado automaticamente
   - Nenhuma mutação indevida no SQLite ocorre durante a renderização passiva
"""

import ast
import json
import os
import py_compile
import socket
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.models import const
from app.services import (
    analytics,
    analytics_scheduler,
    autonomous_production,
    copyright_gate,
    operator_console,
    profile_manager,
    publishing_idempotency,
    quality_recovery,
    quality_score,
    safety_gate,
    scheduler,
    trend_radar,
)


ALLOW_CHANNELS = [
    "channel-default-youtube",
    "channel-default-tiktok",
    "channel-85c572f3bdad",
    "channel-historias-misterio-youtube",
]

DENY_CHANNELS = [
    "channel-6224c41b78e4",
    "channel-4e72dde876d4",
]


class _DummyContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def __getattr__(self, name):
        if name in ("columns", "tabs"):
            return lambda spec, **kw: [
                _DummyContext() for _ in range(spec if isinstance(spec, int) else len(spec))
            ]
        if name in ("expander", "container", "popover", "form", "spinner", "empty"):
            return lambda *a, **kw: _DummyContext()
        if name in ("button", "form_submit_button", "toggle"):
            return lambda *a, **kw: False
        if name == "checkbox":
            return lambda label="", value=False, **kw: value
        if name in ("selectbox", "radio"):
            return lambda label="", options=(), index=0, **kw: (
                list(options)[index] if options and len(options) > index else None
            )
        if name == "multiselect":
            return lambda label="", options=(), default=None, **kw: list(default or [])
        if name in ("text_input", "text_area"):
            return lambda label="", value="", **kw: value
        if name in ("number_input", "slider"):
            return lambda label="", value=0, min_value=0, **kw: (
                value if value is not None else min_value
            )
        return lambda *a, **kw: None


def _build_fake_st(session_state_dict: dict):
    ctx = _DummyContext()
    fake_st = MagicMock()
    fake_st.session_state = session_state_dict
    fake_st.sidebar = ctx

    def _columns(spec, **kw):
        count = spec if isinstance(spec, int) else len(spec)
        return [_DummyContext() for _ in range(count)]

    def _tabs(labels, **kw):
        return [_DummyContext() for _ in labels]

    fake_st.columns.side_effect = _columns
    fake_st.tabs.side_effect = _tabs
    fake_st.expander.side_effect = lambda *a, **kw: _DummyContext()
    fake_st.container.side_effect = lambda *a, **kw: _DummyContext()
    fake_st.popover.side_effect = lambda *a, **kw: _DummyContext()
    fake_st.form.side_effect = lambda *a, **kw: _DummyContext()
    fake_st.spinner.side_effect = lambda *a, **kw: _DummyContext()
    fake_st.empty.side_effect = lambda *a, **kw: _DummyContext()
    fake_st.button.return_value = False
    fake_st.form_submit_button.return_value = False
    fake_st.toggle.return_value = False
    fake_st.checkbox.side_effect = lambda label="", value=False, **kw: value
    fake_st.selectbox.side_effect = lambda label="", options=(), index=0, **kw: (
        list(options)[index] if options and len(options) > index else None
    )
    fake_st.radio.side_effect = lambda label="", options=(), index=0, **kw: (
        list(options)[index] if options and len(options) > index else None
    )
    fake_st.multiselect.side_effect = lambda label="", options=(), default=None, **kw: list(
        default or []
    )
    fake_st.text_input.side_effect = lambda label="", value="", **kw: value
    fake_st.text_area.side_effect = lambda label="", value="", **kw: value
    fake_st.number_input.side_effect = lambda label="", value=0, min_value=0, **kw: (
        value if value is not None else min_value
    )
    fake_st.slider.side_effect = lambda label="", value=0, min_value=0, **kw: (
        value if value is not None else min_value
    )
    return fake_st


def test_1_syntax_and_generation_controls_section_order():
    """Valida compilação dos módulos alterados e a ordem 1->2->3->4->5 em _render_generation_controls."""
    files = [
        "app/services/copyright_gate.py",
        "app/services/operator_console.py",
        "app/services/quality_recovery.py",
        "webui/Main.py",
        "webui/components/operator_console.py",
        "webui/components/channel_factory.py",
    ]
    for rel in files:
        py_compile.compile(rel, doraise=True)

    source = Path("webui/Main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    gen_fn = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "_render_generation_controls"
    )
    called_names = [
        stmt.value.func.id
        for stmt in gen_fn.body
        if isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Call)
        and isinstance(stmt.value.func, ast.Name)
    ]
    expected_sequence = [
        "_render_channel_factory_section",
        "_render_operator_console_section",
        "_render_publication_schedule_section",
        "_render_trend_radar_section",
        "_render_analytics_section",
        "_render_autopilot_section",
    ]
    indices = [called_names.index(name) for name in expected_sequence]
    assert indices == sorted(indices), (
        f"Ordem incorreta em _render_generation_controls: {called_names}"
    )


def test_2_asset_provenance_five_formats_regression(tmp_path, monkeypatch):
    """Testa regressão do AttributeError e os 5 cenários de asset_provenance sem perder evidências."""
    monkeypatch.setattr(
        socket.socket,
        "connect",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("Network access forbidden")),
    )
    db_path = str(tmp_path / "copyright_formats.db")
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    scheduler.init_db(db_path)
    operator_console.init_operator_db(db_path)
    safety_gate.init_safety_db(db_path)
    quality_score.init_quality_db(db_path)
    profile_manager.init_profile_db(db_path)
    profile_manager.ensure_default_profile(db_path=db_path)

    def _make_task(task_id: str, script_payload):
        t_dir = tasks_dir / task_id
        t_dir.mkdir(parents=True, exist_ok=True)
        (t_dir / "final-1.mp4").write_bytes(b"VALID_MP4_BINARY_PAYLOAD_" + task_id.encode())
        with open(t_dir / "script.json", "w", encoding="utf-8") as f:
            json.dump(script_payload, f)
        return t_dir

    # -------------------------------------------------------------------------
    # Cenário A: dict válido (formato tradicional canônico)
    # -------------------------------------------------------------------------
    t_dict_dir = _make_task(
        "task-valid-dict",
        {
            "params": {"bgm_type": "none", "bgm_volume": 0.0, "video_subject": "Oceano"},
            "asset_provenance": {
                "bgm": {
                    "enabled": False,
                    "filename": None,
                    "source": "none",
                    "license_type": "not_applicable",
                    "provenance_status": "SAFE_NO_BGM",
                },
                "visual_clips": [
                    {
                        "provider": "pexels",
                        "external_id": "px-1",
                        "provider_url": "https://pexels.com/1",
                        "local_file": str(tasks_dir / "clip1.mp4"),
                        "search_term": "ocean",
                        "used_duration_sec": 5.0,
                    }
                ],
                "presenter": {"enabled": False, "mode": "none"},
                "provenance_status": "SAFE_NO_BGM",
            },
        },
    )
    gate_ok, _, gate_details = copyright_gate.evaluate_copyright_provenance_gate(
        task_id="task-valid-dict", task_base_dir=str(tasks_dir), db_path=db_path
    )
    assert gate_ok is True
    assert gate_details["copyright_provenance_gate"] == "PASS"

    summary_dict = operator_console.get_copyright_provenance_summary_op(
        task_id="task-valid-dict", task_base_dir=str(tasks_dir), db_path=db_path
    )
    assert summary_dict["copyright_gate_status"] == "PASS"
    assert summary_dict["clips_count"] == 1
    assert summary_dict["visual_providers"] == ["Pexels"]
    assert summary_dict["copyright_status"] == copyright_gate.COPYRIGHT_STATUS_UNKNOWN
    assert summary_dict["feedback_loop_eligible"] is False

    # -------------------------------------------------------------------------
    # Cenário B1: list válida (Quiz ImageProvenance com Pexels e local_path)
    # Reproduz exatamente o traceback de produção em copyright_gate.py:1223
    # -------------------------------------------------------------------------
    quiz_img_path = str(tasks_dir / "quiz_img_01.png")
    _make_task(
        "task-quiz-valid-list",
        {
            "params": {"bgm_type": "ambient_auto", "bgm_volume": 0.2, "video_subject": "Quiz"},
            "asset_provenance": [
                {
                    "asset_id": "pexels_998877",
                    "provider": "pexels",
                    "source_url": "https://www.pexels.com/photo/998877",
                    "local_path": quiz_img_path,
                    "query": "ancient temple",
                    "license": "Pexels License",
                    "status": "READY",
                    "fallback_level": 0,
                }
            ],
        },
    )
    # Verifica preservação integral de evidências na normalização
    raw_list = json.loads((tasks_dir / "task-quiz-valid-list" / "script.json").read_text(encoding="utf-8"))[
        "asset_provenance"
    ]
    norm_list = copyright_gate.normalize_asset_provenance(
        raw_prov=raw_list,
        task_id="task-quiz-valid-list",
        params={"bgm_type": "ambient_auto", "bgm_volume": 0.2},
        task_base_dir=str(tasks_dir),
    )
    assert isinstance(norm_list, dict)
    assert norm_list["bgm"]["provenance_status"] == "SAFE_PROCEDURAL"
    assert len(norm_list["visual_clips"]) == 1
    clip0 = norm_list["visual_clips"][0]
    assert clip0["provider"] == "pexels"
    assert clip0["local_file"] == quiz_img_path
    assert clip0["local_path"] == quiz_img_path
    assert clip0["source_url"] == "https://www.pexels.com/photo/998877"
    assert clip0["license"] == "Pexels License"
    assert clip0["status"] == "READY"

    gate_ok_list, _, _ = copyright_gate.evaluate_copyright_provenance_gate(
        task_id="task-quiz-valid-list", task_base_dir=str(tasks_dir), db_path=db_path
    )
    assert gate_ok_list is True

    summary_list = operator_console.get_copyright_provenance_summary_op(
        task_id="task-quiz-valid-list", task_base_dir=str(tasks_dir), db_path=db_path
    )
    assert summary_list["copyright_gate_status"] == "PASS"
    assert summary_list["clips_count"] == 1
    assert summary_list["visual_providers"] == ["Pexels"]
    assert summary_list["bgm_provenance"] == "SAFE_PROCEDURAL"
    assert summary_list["copyright_status"] == copyright_gate.COPYRIGHT_STATUS_UNKNOWN
    assert summary_list["feedback_loop_eligible"] is False

    # -------------------------------------------------------------------------
    # Cenário B2: list válida Paper Quiz (provider procedural interno sem local_file stock)
    # Não pode lançar AttributeError e não pode assumir PASS automático no gate de stock
    # -------------------------------------------------------------------------
    _make_task(
        "task-paper-quiz-list",
        {
            "params": {"bgm_type": "none", "bgm_volume": 0.0, "video_subject": "Paper Quiz"},
            "asset_provenance": [
                {
                    "asset_id": "pillow_paper_sheet",
                    "provider": "paper_canvas_engine",
                    "source_url": "internal://pillow/paper_sheet",
                    "license": "internal_procedural",
                    "verified": True,
                }
            ],
        },
    )
    gate_ok_paper, reason_paper, details_paper = copyright_gate.evaluate_copyright_provenance_gate(
        task_id="task-paper-quiz-list", task_base_dir=str(tasks_dir), db_path=db_path
    )
    assert gate_ok_paper is False
    assert details_paper["copyright_provenance_gate"] == "FAIL"

    summary_paper = operator_console.get_copyright_provenance_summary_op(
        task_id="task-paper-quiz-list", task_base_dir=str(tasks_dir), db_path=db_path
    )
    assert summary_paper["copyright_gate_status"] == "FAIL"
    assert summary_paper["clips_count"] == 1
    assert summary_paper["visual_providers"] == ["Paper_Canvas_Engine"]
    assert summary_paper["copyright_status"] == copyright_gate.COPYRIGHT_STATUS_UNKNOWN
    assert summary_paper["feedback_loop_eligible"] is False

    # -------------------------------------------------------------------------
    # Cenário C: lista vazia ([])
    # -------------------------------------------------------------------------
    _make_task(
        "task-empty-list",
        {
            "params": {"bgm_type": "none", "bgm_volume": 0.0, "video_subject": "Lista Vazia"},
            "asset_provenance": [],
        },
    )
    gate_ok_empty, _, details_empty = copyright_gate.evaluate_copyright_provenance_gate(
        task_id="task-empty-list", task_base_dir=str(tasks_dir), db_path=db_path
    )
    assert gate_ok_empty is False
    assert details_empty["copyright_provenance_gate"] == "FAIL"
    assert details_empty["visual_status"] == "MISSING_CLIPS"

    summary_empty = operator_console.get_copyright_provenance_summary_op(
        task_id="task-empty-list", task_base_dir=str(tasks_dir), db_path=db_path
    )
    assert summary_empty["copyright_gate_status"] == "FAIL"
    assert summary_empty["clips_count"] == 0
    assert summary_empty["visual_providers"] == []
    assert summary_empty["provenance_status"] == "INCOMPLETE_ASSETS"
    assert summary_empty["copyright_status"] == copyright_gate.COPYRIGHT_STATUS_UNKNOWN
    assert summary_empty["feedback_loop_eligible"] is False

    # -------------------------------------------------------------------------
    # Cenário D: dados malformados / formatos desconhecidos
    # Nunca deve assumir Copyright PASS mesmo se material_sources existir no script.json
    # -------------------------------------------------------------------------
    malformed_variants = [
        ("task-malformed-str", "corrupted_provenance_string"),
        ("task-malformed-int", 12345),
        ("task-malformed-bool", True),
        ("task-malformed-list-str", ["not_a_dict_element"]),
        ("task-malformed-list-empty-dict", [{}]),
        ("task-malformed-list-unknown-keys", [{"foo": "bar"}]),
        ("task-malformed-dict-unknown-keys", {"unexpected_key": 123}),
        ("task-malformed-dict-bad-bgm", {"bgm": ["invalid_bgm_list"], "visual_clips": []}),
        ("task-malformed-dict-bad-clips", {"bgm": {}, "visual_clips": "not_a_list"}),
    ]
    for tid, bad_payload in malformed_variants:
        _make_task(
            tid,
            {
                "params": {"bgm_type": "none", "bgm_volume": 0.0, "video_subject": "Malformed"},
                "material_sources": [{"provider": "pexels", "local_file": "v1.mp4"}],
                "asset_provenance": bad_payload,
            },
        )
        g_ok, g_reason, g_det = copyright_gate.evaluate_copyright_provenance_gate(
            task_id=tid, task_base_dir=str(tasks_dir), db_path=db_path
        )
        assert g_ok is False, f"{tid} não poderia passar no gate!"
        assert g_det["copyright_provenance_gate"] == "FAIL"
        assert g_det["provenance_status"] == "MALFORMED_PROVENANCE"
        assert "malformada" in g_reason.lower()

        s_mal = operator_console.get_copyright_provenance_summary_op(
            task_id=tid, task_base_dir=str(tasks_dir), db_path=db_path
        )
        assert s_mal["copyright_gate_status"] == "FAIL"
        assert s_mal["provenance_status"] == "MALFORMED_PROVENANCE"
        assert s_mal["bgm_provenance"] == "MALFORMED_PROVENANCE"
        assert s_mal["visual_providers"] == []
        assert s_mal["clips_count"] == 0
        assert s_mal["copyright_status"] == copyright_gate.COPYRIGHT_STATUS_UNKNOWN
        assert s_mal["feedback_loop_eligible"] is False

        with pytest.raises(ValueError, match="Proveniência de ativos malformada"):
            with patch.object(operator_console, "is_primary_instance", return_value=True):
                operator_console.approve_legacy_task_copyright_op(
                    task_id=tid,
                    confirm="APPROVE_LEGACY_COPYRIGHT",
                    db_path=db_path,
                    task_base_dir=str(tasks_dir),
                )

    # -------------------------------------------------------------------------
    # Cenário E: proveniência ausente (None)
    # -------------------------------------------------------------------------
    _make_task(
        "task-absent-none",
        {
            "params": {"bgm_type": "none", "bgm_volume": 0.0, "video_subject": "Sem Proveniência"},
            "asset_provenance": None,
        },
    )
    gate_ok_none, _, details_none = copyright_gate.evaluate_copyright_provenance_gate(
        task_id="task-absent-none", task_base_dir=str(tasks_dir), db_path=db_path
    )
    assert gate_ok_none is False
    assert details_none["copyright_provenance_gate"] == "FAIL"
    assert details_none["visual_status"] == "MISSING_CLIPS"

    summary_none = operator_console.get_copyright_provenance_summary_op(
        task_id="task-absent-none", task_base_dir=str(tasks_dir), db_path=db_path
    )
    assert summary_none["copyright_gate_status"] == "FAIL"
    assert summary_none["clips_count"] == 0
    assert summary_none["visual_providers"] == []
    assert summary_none["provenance_status"] == "INCOMPLETE_ASSETS"
    assert summary_none["copyright_status"] == copyright_gate.COPYRIGHT_STATUS_UNKNOWN
    assert summary_none["feedback_loop_eligible"] is False


def test_3_integrated_full_ui_render_sections_1_to_5(tmp_path, monkeypatch):
    """Valida a renderização integrada 1 -> 2 -> 3 -> 4 -> 5 sobre SQLite representativo com mocks."""
    # Bloqueia qualquer acesso de rede
    monkeypatch.setattr(
        socket.socket,
        "connect",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("Network access forbidden")),
    )

    db_path = str(tmp_path / "integrated_ui_render.db")
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    # Inicializa todos os schemas antes da medição de mutações SQLite
    scheduler.init_db(db_path)
    operator_console.init_operator_db(db_path)
    safety_gate.init_safety_db(db_path)
    quality_score.init_quality_db(db_path)
    profile_manager.init_profile_db(db_path)
    profile_manager.ensure_default_profile(db_path=db_path)
    trend_radar.init_trend_db(db_path)
    analytics.init_analytics_db(db_path)

    monkeypatch.setattr(scheduler, "get_db_path", lambda custom=None: custom or db_path)
    monkeypatch.setattr("app.utils.utils.task_dir", lambda *a, **kw: str(tasks_dir))

    # Estado de produção: fábrica em PAUSED, Scheduler/AutoPublish OFF, autonomia OFF
    operator_console.reset_instance_for_testing()
    with operator_console._instance_state_lock:
        operator_console._instance_initialized = True
        operator_console._current_role = operator_console.ROLE_PRIMARY
    operator_console.pause_factory(db_path=db_path)
    scheduler.set_setting("scheduler_enabled", False, db_path=db_path)
    scheduler.set_setting("auto_publish_enabled", False, db_path=db_path)
    scheduler.set_setting("dry_run_mode", True, db_path=db_path)
    autonomous_production.set_autonomous_setting(
        autonomous_production.KEY_AUTONOMOUS_ENABLED, False, db_path=db_path
    )

    # Cria perfil Quiz e os 6 canais CA-03 (4 permitidos + 2 Quiz bloqueados)
    now_iso = "2026-10-21T12:00:00+00:00"
    with scheduler.get_connection(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO content_profiles (id, slug, name, is_active, created_at, updated_at) "
            "VALUES ('profile-quiz', 'quiz-escolhas', 'Quiz / Escolhas', 1, ?, ?)",
            (now_iso, now_iso),
        )
        for cid in ALLOW_CHANNELS:
            plat = "tiktok" if "tiktok" in cid else "youtube"
            conn.execute(
                "INSERT OR REPLACE INTO publishing_channels "
                "(id, profile_id, platform, display_name, is_enabled, auto_publish_authorized, created_at, updated_at) "
                "VALUES (?, 'default', ?, ?, 1, 1, ?, ?)",
                (cid, plat, f"Allow {cid}", now_iso, now_iso),
            )
        for cid in DENY_CHANNELS:
            plat = "tiktok" if "6224" in cid else "youtube"
            conn.execute(
                "INSERT OR REPLACE INTO publishing_channels "
                "(id, profile_id, platform, display_name, is_enabled, auto_publish_authorized, created_at, updated_at) "
                "VALUES (?, 'profile-quiz', ?, ?, 1, 0, ?, ?)",
                (cid, plat, f"Quiz Deny {cid}", now_iso, now_iso),
            )

    # Popula tasks representativas no disco e SQLite (incluindo Quiz list, [], malformed, None, dict)
    representative_tasks = [
        (
            "task-prod-quiz-list",
            "profile-quiz",
            [
                {
                    "asset_id": "px_quiz_01",
                    "provider": "pexels",
                    "source_url": "https://www.pexels.com/photo/1",
                    "local_path": str(tasks_dir / "quiz_01.png"),
                    "query": "mystery door",
                    "license": "Pexels License",
                    "status": "READY",
                }
            ],
        ),
        ("task-prod-empty-list", "profile-quiz", []),
        ("task-prod-malformed", "default", "corrupted_legacy_payload"),
        ("task-prod-none", "default", None),
        (
            "task-prod-valid-dict",
            "default",
            {
                "bgm": {
                    "enabled": False,
                    "filename": None,
                    "source": "none",
                    "license_type": "not_applicable",
                    "provenance_status": "SAFE_NO_BGM",
                },
                "visual_clips": [
                    {
                        "provider": "pexels",
                        "local_file": str(tasks_dir / "stock_01.mp4"),
                        "external_id": "st_01",
                    }
                ],
                "presenter": {"enabled": False, "mode": "none"},
                "provenance_status": "SAFE_NO_BGM",
            },
        ),
    ]

    for tid, prof_id, prov_payload in representative_tasks:
        t_dir = tasks_dir / tid
        t_dir.mkdir(parents=True, exist_ok=True)
        (t_dir / "final-1.mp4").write_bytes(b"MP4_DATA_" + tid.encode())
        with open(t_dir / "script.json", "w", encoding="utf-8") as f:
            json.dump(
                {
                    "params": {
                        "bgm_type": "none",
                        "bgm_volume": 0.0,
                        "video_subject": f"Subject {tid}",
                    },
                    "asset_provenance": prov_payload,
                },
                f,
            )
        safety_gate.save_safety_assessment(
            {
                "task_id": tid,
                "preset": "youtube_shorts_original",
                "safety_status": const.SAFETY_STATUS_PASS,
                "safety_reasons": [],
            },
            db_path=db_path,
        )
        quality_score.evaluate_quality(
            topic=f"Subject {tid}", task_id=tid, persist=True, db_path=db_path
        )
        scheduler.save_task_platforms(tid, ["youtube"], db_path=db_path)
        profile_manager.save_task_profile(tid, prof_id, db_path=db_path)

    # Define a task com asset_provenance em formato list como current_task_id
    # para exercitar diretamente o ponto exato do crash em _render_copyright_provenance_section
    autonomous_production.set_autonomous_setting(
        autonomous_production.KEY_AUTONOMOUS_CURRENT_TASK_ID,
        "task-prod-quiz-list",
        db_path=db_path,
    )

    from webui import Main as webui_main
    from webui.components import channel_factory as cf_ui
    from webui.components import operator_console as oc_ui

    def _snapshot_db():
        snap = {}
        with scheduler.get_connection(db_path) as conn:
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                ).fetchall()
            ]
            for tbl in tables:
                snap[tbl] = [
                    dict(r) for r in conn.execute(f"SELECT * FROM {tbl}").fetchall()
                ]
        return snap

    session_dict = {
        "scheduler_enabled_cb": False,
        "scheduler_auto_publish_cb": False,
        "scheduler_dry_run_cb": True,
        "autopilot_ideas": [],
        "generation_queue_tasks": [],
        "active_profile_id": "default",
    }
    fake_st = _build_fake_st(session_dict)

    execution_log: list[str] = []

    def _wrap(label: str, fn):
        def _inner(*a, **kw):
            execution_log.append(label)
            return fn(*a, **kw)

        return _inner

    dummy_params = webui_main.VideoParams(video_subject="Teste Render Completo")

    with patch.object(webui_main, "st", fake_st), \
         patch.object(oc_ui, "st", fake_st), \
         patch.object(cf_ui, "st", fake_st), \
         patch.object(scheduler, "start_scheduler_worker") as mock_start_worker, \
         patch.object(webui_main.webui_task, "submit_generation") as mock_start_task, \
         patch.object(webui_main.tm, "start") as mock_tm_start, \
         patch("app.services.analytics_ingestion.get_provider") as mock_ext_analytics, \
         patch.object(scheduler, "run_scheduler_cycle") as mock_ext_publisher, \
         patch.object(
             oc_ui,
             "_render_copyright_provenance_section",
             wraps=_wrap("2a_copyright_provenance", oc_ui._render_copyright_provenance_section),
         ), \
         patch.object(
             oc_ui,
             "_render_clip_mode_section",
             wraps=_wrap("2b_clip_mode", oc_ui._render_clip_mode_section),
         ), \
         patch.object(
             oc_ui,
             "_render_observability_section",
             wraps=_wrap("2c_observability", oc_ui._render_observability_section),
         ), \
         patch.object(
             oc_ui,
             "_render_tabs_section",
             wraps=_wrap("2d_tabs", oc_ui._render_tabs_section),
         ):

        # Aquecimento de eventuais caches de leitura / tabelas antes de tirar o snapshot pré-render
        db_before = _snapshot_db()

        with operator_console.render_pass_scope():
            # 1. Channel Factory
            execution_log.append("1_channel_factory")
            webui_main._render_channel_factory_section()

            # 2. Console Operacional completo
            execution_log.append("2_operator_console")
            webui_main._render_operator_console_section()

            # 3. Agenda de Publicação
            execution_log.append("3_publication_schedule")
            webui_main._render_publication_schedule_section()

            # 4. Trend Radar e Analytics
            execution_log.append("4a_trend_radar")
            webui_main._render_trend_radar_section()
            execution_log.append("4b_analytics")
            webui_main._render_analytics_section()

            # 5A. Autopilot sem ideias
            execution_log.append("5a_autopilot_empty")
            session_dict["autopilot_ideas"] = []
            webui_main._render_autopilot_section(
                params=dummy_params,
                voice_mode="tts",
                uploaded_audio_file=None,
                uploaded_bgm_file=None,
                has_local_materials=False,
            )

            # 5B. Autopilot com ideias
            execution_log.append("5b_autopilot_with_ideas")
            session_dict["autopilot_ideas"] = [
                {
                    "topic": "Mistério das fossas oceânicas",
                    "hook": "O que existe a 11 km de profundidade?",
                    "angle": "Ciência extrema",
                    "selected": True,
                }
            ]
            webui_main._render_autopilot_section(
                params=dummy_params,
                voice_mode="tts",
                uploaded_audio_file=None,
                uploaded_bgm_file=None,
                has_local_materials=False,
            )

        db_after = _snapshot_db()

    # 1. Verifica que todas as seções 1 -> 2 (incluindo sub-seções pós-Copyright) -> 3 -> 4 -> 5 executaram
    assert execution_log == [
        "1_channel_factory",
        "2_operator_console",
        "2a_copyright_provenance",
        "2b_clip_mode",
        "2c_observability",
        "2d_tabs",
        "3_publication_schedule",
        "4a_trend_radar",
        "4b_analytics",
        "5a_autopilot_empty",
        "5b_autopilot_with_ideas",
    ]

    # 2. Verifica que PAUSED não iniciou Scheduler nem geração
    mock_start_worker.assert_not_called()
    mock_start_task.assert_not_called()
    mock_tm_start.assert_not_called()

    # 3. Verifica que nenhuma chamada a provedores externos ocorreu
    mock_ext_analytics.assert_not_called()
    mock_ext_publisher.assert_not_called()

    # 4. Verifica que os dois canais Quiz permanecem bloqueados
    with scheduler.get_connection(db_path) as conn:
        for deny_cid in DENY_CHANNELS:
            row = conn.execute(
                "SELECT auto_publish_authorized FROM publishing_channels WHERE id = ?",
                (deny_cid,),
            ).fetchone()
            assert row is not None and int(row["auto_publish_authorized"]) == 0
            assert (
                scheduler.is_channel_auto_publish_authorized(deny_cid, db_path=db_path)
                is False
            )

    # 5. Verifica que nenhum registro de copyright desconhecido foi aprovado automaticamente
    with scheduler.get_connection(db_path) as conn:
        auto_approvals = conn.execute(
            "SELECT COUNT(*) FROM operational_events WHERE event_type IN (?, ?)",
            (
                "PUBLICATION_COPYRIGHT_STATUS_SET",
                copyright_gate.EVENT_TASK_COPYRIGHT_MANUAL_APPROVAL,
            ),
        ).fetchone()[0]
        assert auto_approvals == 0

    # 6. Verifica que não houve nenhuma mutação indevida no SQLite durante a renderização passiva
    assert db_after == db_before
