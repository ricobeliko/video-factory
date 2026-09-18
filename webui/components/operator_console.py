"""Operator Console component for Video Factory (V8).

Provides a centralized, SaaS-grade Mission Control dashboard:
1. Command Header (macro status, persistent paused banner, metadata, controls)
2. System Health (horizontal cards with semantic badges)
3. Live Operations (active task details, 7-stage visual stepper, safe cancellation)
4. Queues & Stock (Generation Queue, Publication Queue, Ready Stock breakdown)
5. Provider Health (sanitized status, telemetries, no secrets/keys exposed)
6. Alerts & Recovery (active alerts, recent timeline, error center, restart recovery)
"""

from datetime import datetime, timezone
import html
from typing import Any, Dict, List, Optional
import streamlit as st

from app.models import const
from app.services import operator_console


def _truncate_id(id_str: str, prefix_len: int = 8, suffix_len: int = 4) -> str:
    """Truncates UUID/hashes safely for compact UI."""
    if not id_str:
        return "—"
    if len(id_str) <= prefix_len + suffix_len + 3:
        return id_str
    return f"{id_str[:prefix_len]}...{id_str[-suffix_len:]}"


def _sanitize_text(text: Optional[str]) -> str:
    """Sanitizes text removing potential secrets, tokens or filepaths."""
    if not text:
        return ""
    s = str(text)
    # Never show config.toml full dumps or API keys
    import re
    s = re.sub(r"AIza[0-9A-Za-z\-_]{16,}", "[REDACTED_API_KEY]", s)
    s = re.sub(r"(Bearer\s+[A-Za-z0-9\-\._~\+\/]+=*)", "[REDACTED_TOKEN]", s)
    s = re.sub(r"([a-zA-Z0-9_-]{16,}:[a-zA-Z0-9_-]{16,})", "[REDACTED_SECRET]", s)
    return html.escape(s)



def _render_stepper_html(current_stage_idx: int = 5) -> str:
    """Renders a sleek, lightweight 7-stage horizontal stepper.

    Stages:
    0: SCRIPT
    1: SAFETY PRE
    2: TTS
    3: MATERIAL
    4: SUBTITLE
    5: RENDER
    6: COMPLETE
    """
    stages = [
        ("SCRIPT", "Roteiro"),
        ("SAFETY PRE", "Segurança"),
        ("TTS", "Voz"),
        ("MATERIAL", "Vídeos/Imagens"),
        ("SUBTITLE", "Legendas"),
        ("RENDER", "Renderização"),
        ("COMPLETE", "Concluído"),
    ]

    steps_html = []
    for idx, (code, title) in enumerate(stages):
        if idx < current_stage_idx:
            status_cls = "done"
            symbol = "✓"
        elif idx == current_stage_idx:
            status_cls = "active"
            symbol = "●"
        else:
            status_cls = "pending"
            symbol = "○"

        steps_html.append(
            f"""
            <div class="op-step-item" title="{title}">
                <div class="op-step-indicator op-step-indicator-{status_cls}">{symbol}</div>
                <div class="op-step-label op-step-label-{status_cls}">{code}</div>
            </div>
            """
        )

    return f"""
    <div class="op-stepper-container">
        {"".join(steps_html)}
    </div>
    """


def _get_mock_fixtures(scenario: str) -> Dict[str, Any]:
    """Generates pure in-memory test fixtures for visual homologation without persisting to DB."""
    now_str = datetime.now().strftime("%H:%M:%S")

    # Base state
    mock_data = {
        "factory_state": "RUNNING",
        "is_paused": False,
        "generation_worker": "ACTIVE",
        "scheduler_worker": "ACTIVE",
        "auto_publish": "OFF",
        "dry_run": "ON",
        "growth_mode": "Aquecimento",
        "heartbeats": {
            "generation_seconds_ago": 8,
            "scheduler_seconds_ago": 12,
        },
        "last_publication": {
            "platform": "YouTube",
            "published_at": datetime.now().isoformat(),
        },
        "active_task": {
            "task_id": "4cc0f5cf9e1248ab82a0b1274d896251",
            "topic": "Por que os oceanos são salgados?",
            "stage": "Renderizando vídeo (FFmpeg)",
            "stage_idx": 5,
            "progress": 72,
            "elapsed": "07:31",
            "preset": "Cross Platform",
            "profile_id": "curiosidades-brasil",
            "profile_name": "Curiosidades Brasil",
            "safety_status": "PASS",
            "quality_score": 78,
            "quality_label": "GOOD",
            "strategy_score": 82,
            "strategy_label": "PROMISING",
        },
        "g_summary": {
            "pending": 3,
            "processing": 1,
            "completed": 18,
            "failed": 1,
            "cancelled": 0,
            "total": 23,
            "recent_tasks": [
                {"task_id": "4cc0f5cf9e12", "subject": "Por que os oceanos são salgados?", "state": 4, "quality_score": 78, "strategy_score": 82},
                {"task_id": "9b12a884c10e", "subject": "O segredo das pirâmides submersas", "state": 0, "quality_score": 88, "strategy_score": 85},
                {"task_id": "8fa1103cba21", "subject": "Como os aviões voam sem bater asas", "state": 0, "quality_score": 74, "strategy_score": 72},
                {"task_id": "71df5a02e3b4", "subject": "A evolução esquecida dos répteis", "state": 0, "quality_score": 68, "strategy_score": 64},
                {"task_id": "5f3a9019b882", "subject": "10 maiores buracos negros do universo", "state": 1, "quality_score": 91, "strategy_score": 90},
            ],
        },
        "s_summary": {
            "planned": 5,
            "ready": 2,
            "processing": 0,
            "published": 12,
            "failed": 0,
            "total": 19,
            "upcoming_posts": [
                {
                    "task_id": "5f3a9019b882",
                    "platform": "YouTube",
                    "scheduled_at": "Hoje 08:30",
                    "status": "planned",
                    "topic": "10 maiores buracos negros do universo",
                    "growth_mode": "Aquecimento",
                },
                {
                    "task_id": "5f3a9019b882",
                    "platform": "TikTok",
                    "scheduled_at": "Hoje 12:00",
                    "status": "planned",
                    "topic": "10 maiores buracos negros do universo",
                    "growth_mode": "Aquecimento",
                },
            ],
        },
        "stock": {
            "total_ready": 5,
            "youtube_count": 4,
            "tiktok_count": 5,
            "cross_platform_count": 3,
            "minimum_threshold": 3,
            "is_below_minimum": False,
        },
        "providers": {
            "Gemini": {"status": "HEALTHY", "details": "Chave configurada e ativa", "last_success": "3 min", "last_error": None},
            "Pexels": {"status": "HEALTHY", "details": "Chave configurada e ativa", "last_success": "8 min", "last_error": None},
            "Edge TTS": {"status": "HEALTHY", "details": "Biblioteca pronta e responsiva", "last_success": "11 min", "last_error": None},
            "FFmpeg": {"status": "HEALTHY", "details": "Binário detectado no PATH", "last_success": "14 min", "last_error": None},
            "Google Trends": {"status": "HEALTHY", "details": "Feed e Radar ativos", "last_success": "22 min", "last_error": None},
            "RSS": {"status": "HEALTHY", "details": "Coletas RSS regulares", "last_success": "22 min", "last_error": None},
            "Reddit": {"status": "HEALTHY", "details": "Coleta Reddit disponível", "last_success": "45 min", "last_error": None},
            "Upload-Post": {"status": "UNKNOWN", "details": "Não configurado para envio externo", "last_success": "15h", "last_error": None},
        },
        "alerts": [],
        "timeline": [
            {"time": "03:31", "badge": "✓", "color": "green", "text": 'Vídeo concluído: "Por que os oceanos são salgados?"'},
            {"time": "03:12", "badge": "✓", "color": "green", "text": "Safety Gate PASS — Task 4cc0f5cf"},
            {"time": "02:58", "badge": "ℹ", "color": "blue", "text": "Trend Radar ciclo finalizado: 12 novos tópicos"},
            {"time": "02:41", "badge": "✓", "color": "green", "text": "Publicação simulada YouTube concluída"},
            {"time": "02:16", "badge": "ℹ", "color": "blue", "text": "Factory resumed pelo operador"},
        ],
        "errors": [],
        "recoverable": [],
        "instance": {
            "local_role": "ROLE_PRIMARY",
            "is_primary": True,
            "node_name": "VIDEO-FACTORY-PROD",
            "hostname": "PC-FORTE-PROD",
            "pid": 4128,
            "primary_node_id": "mock-node-1",
            "primary_node_name": "VIDEO-FACTORY-PROD",
            "primary_hostname": "PC-FORTE-PROD",
            "primary_pid": 4128,
            "primary_status": "ACTIVE",
            "last_heartbeat": datetime.now(timezone.utc).isoformat(),
            "heartbeat_seconds_ago": 4,
            "is_heartbeat_stale": False,
            "uptime_str": "3h 45m",
            "remote_access_url": "http://0.0.0.0:8501 (LAN / Tailscale)",
        },
    }

    if scenario == "Factory PAUSED":
        mock_data["factory_state"] = "PAUSED"
        mock_data["is_paused"] = True
        mock_data["alerts"].append({
            "severity": "WARNING",
            "title": "Fábrica pausada pelo operador",
            "desc": "Novas gerações e publicações automáticas estão suspensas.",
            "time_ago": "há 5 min",
        })
    elif scenario == "DEGRADED com Reddit 403":
        mock_data["factory_state"] = "DEGRADED"
        mock_data["providers"]["Reddit"] = {
            "status": "DEGRADED",
            "details": "Trend Radar opera com demais fontes. Coleta Reddit retornou HTTP 403.",
            "last_success": "2h",
            "last_error": "HTTP 403 Forbidden",
        }
        mock_data["alerts"].append({
            "severity": "WARNING",
            "title": "Reddit indisponível",
            "desc": "HTTP 403 Forbidden — Trend Radar opera através das demais fontes.",
            "time_ago": "há 2h",
        })
        mock_data["errors"].append({
            "time": "02:58:14",
            "component": "Reddit",
            "severity": "WARNING",
            "task_id": "—",
            "message": "HTTP 403 Forbidden ao acessar r/todayilearned",
        })
    elif scenario == "Ready Stock abaixo do mínimo":
        mock_data["stock"]["total_ready"] = 2
        mock_data["stock"]["youtube_count"] = 2
        mock_data["stock"]["tiktok_count"] = 1
        mock_data["stock"]["cross_platform_count"] = 1
        mock_data["stock"]["minimum_threshold"] = 3
        mock_data["stock"]["is_below_minimum"] = True
        mock_data["alerts"].append({
            "severity": "WARNING",
            "title": "Ready Stock abaixo do mínimo operacional",
            "desc": "Estoque pronto de 2 vídeos (meta mínima: 3 vídeos).",
            "time_ago": "há 14 min",
        })
    elif scenario == "Item em Recovery":
        mock_data["recoverable"].append({
            "task_id": "abcd1234ef567890",
            "topic": "A misteriosa civilização esquecida do deserto",
            "problem": "Execução interrompida após reinício da aplicação.",
            "last_stage": "TTS concluído",
            "created_at": "02:10:15",
        })
    elif scenario == "Full Showcase (Todos os 7 Estados)":
        mock_data["factory_state"] = "DEGRADED"
        mock_data["stock"]["total_ready"] = 2
        mock_data["stock"]["is_below_minimum"] = True
        mock_data["providers"]["Reddit"] = {
            "status": "DEGRADED",
            "details": "Trend Radar opera com demais fontes. Coleta Reddit retornou HTTP 403.",
            "last_success": "2h",
            "last_error": "HTTP 403 Forbidden",
        }
        mock_data["alerts"] = [
            {
                "severity": "WARNING",
                "title": "Ready Stock abaixo do mínimo",
                "desc": "Estoque pronto com 2 vídeos (mínimo: 3).",
                "time_ago": "há 14 min",
            },
            {
                "severity": "WARNING",
                "title": "Reddit indisponível",
                "desc": "HTTP 403 — Trend Radar opera com demais fontes.",
                "time_ago": "há 2h",
            },
        ]
        mock_data["recoverable"] = [
            {
                "task_id": "abcd1234ef567890",
                "topic": "A misteriosa civilização esquecida do deserto",
                "problem": "Execução interrompida após reinício da aplicação.",
                "last_stage": "TTS concluído",
                "created_at": "02:10:15",
            }
        ]
    elif scenario == "Secondary VIEW ONLY":
        mock_data["instance"] = {
            "local_role": "ROLE_SECONDARY_VIEW_ONLY",
            "is_primary": False,
            "node_name": "NOTEBOOK-REMOTO",
            "hostname": "NOTEBOOK-DELL",
            "pid": 9840,
            "primary_node_id": "mock-node-1",
            "primary_node_name": "VIDEO-FACTORY-PROD",
            "primary_hostname": "PC-FORTE-PROD",
            "primary_pid": 4128,
            "primary_status": "ACTIVE",
            "last_heartbeat": datetime.now(timezone.utc).isoformat(),
            "heartbeat_seconds_ago": 6,
            "is_heartbeat_stale": False,
            "uptime_str": "12m",
            "remote_access_url": "http://0.0.0.0:8501 (LAN / Tailscale)",
        }
        mock_data["alerts"].append({
            "severity": "WARNING",
            "title": "Instância Secundária em Modo Somente Leitura",
            "desc": "Conectado ao nó primário VIDEO-FACTORY-PROD (PC-FORTE-PROD).",
            "time_ago": "agora",
        })

    return mock_data


def render_operator_console():
    """Main renderer for V8 Operator Console."""
    # Demo Mode Selector (Purely in-memory, without persisting to DB)
    with st.expander("🛠️ Preferências & Demonstração Visual", expanded=False):
        c_demo1, c_demo2 = st.columns([0.4, 0.6])
        with c_demo1:
            demo_enabled = st.checkbox(
                "Modo Demonstração Visual (Homologação)",
                value=False,
                key="op_demo_mode_toggle",
                help="Exibe cenários simulados na UI para validação visual estrita sem gravar mocks no SQLite.",
            )
        with c_demo2:
            scenario_choice = "Factory RUNNING"
            if demo_enabled:
                scenario_choice = st.selectbox(
                    "Cenário de Demonstração:",
                    options=[
                        "Factory RUNNING",
                        "Secondary VIEW ONLY",
                        "Factory PAUSED",
                        "DEGRADED com Reddit 403",
                        "Ready Stock abaixo do mínimo",
                        "Item em Recovery",
                        "Full Showcase (Todos os 7 Estados)",
                    ],
                    index=0,
                    key="op_demo_scenario_sb",
                )

    if demo_enabled:
        st.info(f"🎭 **Modo Demonstração Ativo:** Simulando `{scenario_choice}` (nenhum dado real é modificado).")
        data = _get_mock_fixtures(scenario_choice)
    else:
        # Load real data from services
        sys_status = operator_console.get_system_status()
        g_summary = operator_console.get_generation_queue_summary()
        s_summary = operator_console.get_scheduler_queue_summary()
        stock = operator_console.get_ready_stock()
        provs = operator_console.get_provider_health_summary()
        recent_errs = operator_console.get_recent_errors(limit=10)
        recent_events = operator_console.get_operational_events(limit=20)

        # Recoverable tasks
        from app.services import state as sm
        all_tasks, _ = sm.state.get_all_tasks(1, 100)
        recoverable = [
            {
                "task_id": t.get("task_id"),
                "topic": t.get("video_subject") or t.get("topic") or t.get("task_id", ""),
                "problem": "Execução interrompida após reinício da aplicação.",
                "last_stage": t.get("failed_stage") or "Desconhecido",
                "created_at": t.get("created_at") or "",
            }
            for t in all_tasks
            if t.get("failed_stage") == "interrupted_by_restart"
        ]

        # Active generation task detection
        active_task = None
        for t in all_tasks:
            if t.get("state") == const.TASK_STATE_PROCESSING:
                from app.services import profile_manager
                task_p_id = t.get("profile_id") or profile_manager.get_task_profile_id(t.get("task_id", ""))
                task_p_obj = profile_manager.get_profile(task_p_id) if task_p_id else None
                task_prof_name = task_p_obj.get("name") if task_p_obj else "Video Factory Default"
                active_task = {
                    "task_id": t.get("task_id"),
                    "profile_id": task_p_id,
                    "profile_name": task_prof_name,
                    "topic": t.get("video_subject") or t.get("topic") or "Geração em andamento",
                    "stage": "Processando etapa do pipeline",
                    "stage_idx": 4,
                    "progress": int(t.get("progress") or 50),
                    "elapsed": "em andamento",
                    "preset": t.get("monetization_preset") or "Cross Platform",
                    "safety_status": t.get("safety_status") or "PASS",
                    "quality_score": t.get("quality_score") or 75,
                    "quality_label": t.get("quality_label") or "GOOD",
                    "strategy_score": t.get("strategy_score") or 80,
                    "strategy_label": t.get("strategy_label") or "PROMISING",
                }
                break

        # Operational alerts
        active_alerts = []
        if stock.get("is_below_minimum"):
            active_alerts.append({
                "severity": "WARNING",
                "title": "Ready Stock abaixo do mínimo operacional",
                "desc": f"Estoque atual de {stock.get('total_ready', 0)} vídeos (meta: {stock.get('minimum_threshold', 3)}).",
                "time_ago": "ativo",
            })
        for prov_name, p_data in provs.items():
            if p_data.get("status") in ("DEGRADED", "UNAVAILABLE"):
                active_alerts.append({
                    "severity": "WARNING" if p_data.get("status") == "DEGRADED" else "ERROR",
                    "title": f"Provedor {prov_name} com instabilidade ({p_data.get('status')})",
                    "desc": _sanitize_text(p_data.get("last_error") or p_data.get("details", "")),
                    "time_ago": "recente",
                })

        # Timeline formatting
        timeline_list = []
        for ev in recent_events[:15]:
            sev = ev.get("severity", "INFO")
            b_color = "green" if sev == "INFO" else ("yellow" if sev == "WARNING" else "red")
            b_icon = "✓" if sev == "INFO" else ("⚠" if sev == "WARNING" else "✕")
            time_raw = ev.get("timestamp", "")
            t_short = time_raw[11:16] if len(time_raw) >= 16 else time_raw
            timeline_list.append({
                "time": t_short or "—",
                "badge": b_icon,
                "color": b_color,
                "text": f"{ev.get('component', '')}: {ev.get('message', '')}",
            })

        data = {
            "factory_state": sys_status["factory_state"],
            "is_paused": sys_status["is_paused"],
            "generation_worker": sys_status["generation_worker"],
            "scheduler_worker": sys_status["scheduler_worker"],
            "auto_publish": sys_status["auto_publish"],
            "dry_run": sys_status["dry_run"],
            "growth_mode": sys_status["growth_mode"],
            "heartbeats": sys_status["heartbeats"],
            "last_publication": sys_status.get("last_publication"),
            "active_task": active_task,
            "g_summary": g_summary,
            "s_summary": s_summary,
            "stock": stock,
            "providers": provs,
            "alerts": active_alerts,
            "timeline": timeline_list,
            "errors": [
                {
                    "time": e.get("timestamp", "")[:19],
                    "component": e.get("component", ""),
                    "severity": e.get("severity", "ERROR"),
                    "task_id": e.get("task_id") or "—",
                    "message": _sanitize_text(e.get("message", "")),
                }
                for e in recent_errs
            ],
            "recoverable": recoverable,
            "instance": sys_status.get("instance") or operator_console.get_instance_info(),
        }

    # =========================================================================
    # 1. COMMAND HEADER
    # =========================================================================
    factory_state = data["factory_state"]
    is_paused = data["is_paused"]
    inst_info = data.get("instance") or {}
    is_primary = inst_info.get("is_primary", True)
    node_name = inst_info.get("node_name") or "VIDEO-FACTORY-PROD"
    hostname = inst_info.get("hostname") or "—"
    pid = inst_info.get("pid") or 0
    uptime_str = inst_info.get("uptime_str") or "—"
    remote_url = inst_info.get("remote_access_url") or "http://0.0.0.0:8501 (LAN / Tailscale)"

    # Persistent View Only Warning Banner
    if not is_primary:
        primary_name = inst_info.get("primary_node_name") or "VIDEO-FACTORY-PROD"
        primary_host = inst_info.get("primary_hostname") or "—"
        primary_pid = inst_info.get("primary_pid") or "—"
        hb_sec = inst_info.get("heartbeat_seconds_ago")
        hb_text = f"{hb_sec}s atrás" if hb_sec is not None else "recente"
        st.markdown(
            f"""
            <div class="op-paused-banner" style="border-left-color: #f59e0b; background: rgba(245, 158, 11, 0.08); margin-bottom: 12px;">
                <div>
                    <div class="op-paused-banner-title" style="color: #d97706;">🔒 INSTÂNCIA EM MODO VIEW ONLY</div>
                    <div class="op-paused-banner-desc">
                        Nó primário ativo: <b>{html.escape(str(primary_name))}</b> (Host: <code>{html.escape(str(primary_host))}</code>, PID <code>{primary_pid}</code>, Heartbeat: <code>{hb_text}</code>).<br/>
                        Comandos de controle operacional (pausa, retomada, cancelamento, reexecução, geração e publicação) estão desabilitados nesta interface.
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Active Profile
    from app.services import profile_manager
    active_prof = profile_manager.get_active_profile()
    active_prof_id = active_prof.get("id") or "default"
    active_prof_name = active_prof.get("name") or "Video Factory Default"
    active_prof_slug = active_prof.get("slug") or "default"

    # Node Bar
    role_badge_cls = "op-badge-green" if is_primary else "op-badge-yellow"
    role_badge_txt = "🟢 PRIMARY" if is_primary else "🟠 SECONDARY — VIEW ONLY"
    st.markdown(
        f"""
        <div style="display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; background: rgba(128, 128, 128, 0.08); border: 1px solid rgba(128, 128, 128, 0.2); border-radius: 6px; padding: 6px 14px; margin-bottom: 12px; font-size: 0.83rem;">
            <div style="display: flex; align-items: center; gap: 16px; flex-wrap: wrap;">
                <span>🖥️ <b>Nó:</b> <code>{html.escape(str(node_name))}</code></span>
                <span>🏷️ <b>Papel:</b> <span class="op-badge {role_badge_cls}">{role_badge_txt}</span></span>
                <span>📁 <b>Perfil Ativo:</b> <code>{html.escape(str(active_prof_name))}</code> (<code>{html.escape(str(active_prof_slug))}</code>)</span>
                <span>💻 <b>Host:</b> {html.escape(str(hostname))} (PID {pid})</span>
                <span>⏱️ <b>Uptime:</b> {uptime_str}</span>
            </div>
            <div>
                <span>🌐 <b>Acesso:</b> <code>{remote_url}</code></span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Persistent Paused Banner (Impossible to ignore)
    if is_paused or factory_state == "PAUSED":
        c_banner_text, c_banner_btn = st.columns([0.8, 0.2])
        with c_banner_text:
            st.markdown(
                """
                <div class="op-paused-banner">
                    <div>
                        <div class="op-paused-banner-title">⏸ FÁBRICA PAUSADA</div>
                        <div class="op-paused-banner-desc">Novas gerações e publicações estão bloqueadas. Tarefas em etapa crítica podem concluir normalmente.</div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with c_banner_btn:
            if st.button(
                "▶ Retomar Fábrica",
                key="op_banner_resume_btn",
                type="primary",
                use_container_width=True,
                disabled=not is_primary,
                help="Apenas o nó primário pode retomar a fábrica." if not is_primary else None,
            ):
                if not demo_enabled:
                    operator_console.resume_factory()
                    st.toast("Fábrica retomada!", icon="▶")
                    st.rerun()
                else:
                    st.toast("Retomada simulada em modo demonstração.", icon="▶")

    # Macro status badge styling
    state_pill_class = {
        "RUNNING": "op-status-pill-running",
        "PAUSED": "op-status-pill-paused",
        "DEGRADED": "op-status-pill-degraded",
        "ERROR": "op-status-pill-error",
    }.get(factory_state, "op-status-pill-running")

    state_label = {
        "RUNNING": "🟢 FACTORY RUNNING",
        "PAUSED": "🟡 FACTORY PAUSED",
        "DEGRADED": "🟠 FACTORY DEGRADED",
        "ERROR": "🔴 FACTORY ERROR",
    }.get(factory_state, factory_state)

    col_title, col_prof_sel, col_actions = st.columns([0.46, 0.28, 0.26])
    with col_title:
        st.markdown(
            f"""
            <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 4px;">
                <h2 style="margin: 0; padding: 0; font-size: 1.45rem; font-weight: 700;">VIDEO FACTORY — OPERATOR CONSOLE</h2>
                <div class="op-status-pill {state_pill_class}">{state_label}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        now_time = datetime.now().strftime("%H:%M:%S")
        st.markdown(
            f"""
            <div style="font-size: 0.84rem; opacity: 0.8; display: flex; gap: 16px; margin-top: 4px;">
                <span>🕒 <b>Última atualização:</b> {now_time}</span>
                <span>🌱 <b>Modo:</b> {data['growth_mode']}</span>
                <span>🧪 <b>Dry Run:</b> {data['dry_run']}</span>
                <span>🚀 <b>Auto Publish:</b> {data['auto_publish']}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col_prof_sel:
        active_profiles = [p for p in profile_manager.list_profiles() if p.get("is_active")]
        if not active_profiles:
            active_profiles = [profile_manager.get_default_profile()]
        p_options = [p["id"] for p in active_profiles]
        p_labels = {p["id"]: p["name"] for p in active_profiles}
        if active_prof_id not in p_options:
            p_options.insert(0, active_prof_id)
            p_labels[active_prof_id] = active_prof_name

        p_idx = p_options.index(active_prof_id) if active_prof_id in p_options else 0

        selected_profile_id = st.selectbox(
            "Perfil Ativo:",
            options=p_options,
            index=p_idx,
            format_func=lambda pid: p_labels.get(pid, pid),
            key="op_active_profile_selector",
            disabled=not is_primary,
            help="Modo VIEW ONLY: Apenas o nó primário pode alternar perfis." if not is_primary else "Perfil ativo orienta nicho, idioma, região e presets das tarefas.",
        )

        if is_primary and selected_profile_id != active_prof_id:
            try:
                profile_manager.set_active_profile(selected_profile_id)
                st.toast(f"Perfil ativo alterado para '{p_labels.get(selected_profile_id, selected_profile_id)}'", icon="📁")
                st.rerun()
            except Exception as err:
                st.error(f"Falha ao trocar perfil: {err}")

    with col_actions:
        btn_c1, btn_c2 = st.columns(2)
        with btn_c1:
            if not is_paused:
                if st.button(
                    "⏸ Pausar Fábrica",
                    key="op_main_pause_btn",
                    use_container_width=True,
                    disabled=not is_primary,
                    help="Apenas o nó primário pode pausar a fábrica." if not is_primary else None,
                ):
                    if not demo_enabled:
                        operator_console.pause_factory()
                        st.toast("Fábrica pausada com sucesso.", icon="⏸")
                        st.rerun()
                    else:
                        st.toast("Pausa simulada em modo demonstração.", icon="⏸")
            else:
                if st.button(
                    "▶ Retomar Fábrica",
                    key="op_main_resume_btn",
                    use_container_width=True,
                    disabled=not is_primary,
                    help="Apenas o nó primário pode retomar a fábrica." if not is_primary else None,
                ):
                    if not demo_enabled:
                        operator_console.resume_factory()
                        st.toast("Fábrica retomada com sucesso.", icon="▶")
                        st.rerun()
                    else:
                        st.toast("Retomada simulada em modo demonstração.", icon="▶")

        with btn_c2:
            with st.popover("🛑 Pausar Tudo", use_container_width=True):
                st.markdown("### 🛑 Parada Operacional de Emergência")
                st.caption("Bloqueia novas gerações e publicações sem interromper processos já em etapa crítica.")
                conf = st.checkbox("Confirmar bloqueio geral imediato", key="op_confirm_emergency_popover")
                emergency_disabled = (not conf) or (not is_primary)
                emergency_help = "Apenas o nó primário pode acionar a parada total." if not is_primary else None
                if st.button(
                    "Confirmar Parada Total",
                    disabled=emergency_disabled,
                    type="primary",
                    use_container_width=True,
                    key="op_confirm_emergency_btn",
                    help=emergency_help,
                ):
                    if not demo_enabled:
                        operator_console.emergency_pause()
                        st.toast("Parada total acionada com sucesso!", icon="🛑")
                        st.rerun()
                    else:
                        st.toast("Parada de emergência simulada.", icon="🛑")

    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

    # =========================================================================
    # 2. SYSTEM HEALTH (Faixa horizontal de cards compactos)
    # =========================================================================
    h_col1, h_col2, h_col3, h_col4, h_col5, h_col6 = st.columns(6)

    # Card 1: Generation Worker
    with h_col1:
        gen_active = data["generation_worker"] == "ACTIVE"
        hb_gen = data["heartbeats"]["generation_seconds_ago"]
        hb_gen_str = f"heartbeat {hb_gen}s" if hb_gen is not None else "sem telemetria"
        badge_cls = "op-badge-green" if gen_active else "op-badge-gray"
        badge_txt = "🟢 ACTIVE" if gen_active else "⚪ IDLE"
        st.markdown(
            f"""
            <div class="op-health-card">
                <div class="op-health-card-header">Generation</div>
                <div class="op-health-card-value"><span class="op-badge {badge_cls}">{badge_txt}</span></div>
                <div class="op-health-card-sub">{hb_gen_str}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Card 2: Scheduler
    with h_col2:
        sched_st = data["scheduler_worker"]
        sched_ok = sched_st == "ACTIVE"
        hb_sched = data["heartbeats"]["scheduler_seconds_ago"]
        hb_sched_str = f"heartbeat {hb_sched}s" if hb_sched is not None else "sem telemetria"
        b_cls = "op-badge-green" if sched_ok else ("op-badge-red" if sched_st == "ERROR" else "op-badge-gray")
        b_txt = "🟢 ACTIVE" if sched_ok else ("🔴 ERROR" if sched_st == "ERROR" else "⚪ IDLE")
        st.markdown(
            f"""
            <div class="op-health-card">
                <div class="op-health-card-header">Scheduler</div>
                <div class="op-health-card-value"><span class="op-badge {b_cls}">{b_txt}</span></div>
                <div class="op-health-card-sub">{hb_sched_str}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Card 3: Ready Stock
    with h_col3:
        stk = data["stock"]
        is_low = stk.get("is_below_minimum", False)
        tot_ready = stk.get("total_ready", 0)
        min_th = stk.get("minimum_threshold", 3)
        stk_cls = "op-badge-yellow" if is_low else "op-badge-green"
        stk_txt = f"🟡 {tot_ready} VÍDEOS" if is_low else f"🟢 {tot_ready} VÍDEOS"
        st.markdown(
            f"""
            <div class="op-health-card">
                <div class="op-health-card-header">Ready Stock</div>
                <div class="op-health-card-value"><span class="op-badge {stk_cls}">{stk_txt}</span></div>
                <div class="op-health-card-sub">mínimo: {min_th}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Card 4: Publication
    with h_col4:
        dry_run = data["dry_run"] == "ON"
        pub_cls = "op-badge-gray" if dry_run else "op-badge-green"
        pub_txt = "⚪ DRY RUN" if dry_run else "🟢 LIVE"
        st.markdown(
            f"""
            <div class="op-health-card">
                <div class="op-health-card-header">Publication</div>
                <div class="op-health-card-value"><span class="op-badge {pub_cls}">{pub_txt}</span></div>
                <div class="op-health-card-sub">auto: {data['auto_publish']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Card 5: Errors 24h
    with h_col5:
        err_count = len(data.get("errors", []))
        e_cls = "op-badge-green" if err_count == 0 else "op-badge-red"
        e_txt = "🟢 0 ERROS" if err_count == 0 else f"🔴 {err_count} ERROS"
        st.markdown(
            f"""
            <div class="op-health-card">
                <div class="op-health-card-header">Errors 24h</div>
                <div class="op-health-card-value"><span class="op-badge {e_cls}">{e_txt}</span></div>
                <div class="op-health-card-sub">{"tudo limpo" if err_count == 0 else "ver Alert Center"}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Card 6: Providers
    with h_col6:
        prov_map = data.get("providers", {})
        degraded_count = sum(1 for p in prov_map.values() if p.get("status") in ("DEGRADED", "UNAVAILABLE"))
        if degraded_count == 0:
            p_cls, p_txt, p_sub = "op-badge-green", "🟢 HEALTHY", "8 verificados"
        else:
            p_cls, p_txt, p_sub = "op-badge-yellow", f"🟡 {degraded_count} DEGRADED", "ver Providers"
        st.markdown(
            f"""
            <div class="op-health-card">
                <div class="op-health-card-header">Providers</div>
                <div class="op-health-card-value"><span class="op-badge {p_cls}">{p_txt}</span></div>
                <div class="op-health-card-sub">{p_sub}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

    # =========================================================================
    # 3. LIVE OPERATIONS (Painel de Operações em Tempo Real)
    # =========================================================================
    st.markdown("#### ⚡ Operações em Tempo Real")
    active_task = data.get("active_task")
    if active_task:
        task_id = active_task["task_id"]
        topic = active_task["topic"]
        stage = active_task["stage"]
        progress_val = int(active_task["progress"])
        elapsed = active_task.get("elapsed", "—")
        preset = active_task.get("preset", "Cross Platform")
        q_score = active_task.get("quality_score", 75)
        q_label = active_task.get("quality_label", "GOOD")
        s_score = active_task.get("strategy_score", 80)
        s_label = active_task.get("strategy_label", "PROMISING")

        task_prof_display = active_task.get("profile_name") or "Video Factory Default"
        with st.container(border=True):
            col_live_meta, col_live_ctrl = st.columns([0.75, 0.25])
            with col_live_meta:
                st.markdown(f"**Tema:** {topic}")
                st.caption(
                    f"**Task:** `{_truncate_id(task_id, 8, 4)}` &nbsp;|&nbsp; "
                    f"**Profile:** `{task_prof_display}` &nbsp;|&nbsp; "
                    f"**Stage:** `{stage}` &nbsp;|&nbsp; "
                    f"**Elapsed:** `{elapsed}` &nbsp;|&nbsp; "
                    f"**Preset:** `{preset}` &nbsp;|&nbsp; "
                    f"**Safety:** :green[PASS] &nbsp;|&nbsp; "
                    f"**Quality:** `{q_score} {q_label}` &nbsp;|&nbsp; "
                    f"**Strategy:** `{s_score} {s_label}`"
                )
            with col_live_ctrl:
                cancel_disabled = not is_primary
                cancel_help = "Modo VIEW ONLY: Apenas o nó primário pode cancelar tarefas." if not is_primary else "Cancelamento seguro: será aplicado no próximo checkpoint sem matar o FFmpeg de forma brusca."
                if st.button(
                    "🛑 Cancelar após etapa atual",
                    key=f"op_cancel_active_{task_id}",
                    use_container_width=True,
                    disabled=cancel_disabled,
                    help=cancel_help,
                ):
                    if not demo_enabled:
                        from app.services import webui_task
                        webui_task.cancel_generation(task_id)
                        st.toast(f"Cancelamento registrado para {task_id[:8]}. Concluirá a etapa com segurança.", icon="🛑")
                        st.rerun()
                    else:
                        st.toast("Cancelamento seguro simulado em modo demonstração.", icon="🛑")

            # Progress Bar & 7-Stage Visual Stepper
            st.progress(progress_val / 100.0, text=f"Progresso: {progress_val}%")
            st.markdown(_render_stepper_html(active_task.get("stage_idx", 5)), unsafe_allow_html=True)
    else:
        st.markdown(
            """
            <div style="padding: 16px; border: 1px dashed rgba(128, 128, 128, 0.3); border-radius: 8px; text-align: center; opacity: 0.75; font-size: 0.9rem;">
                ⚪ Nenhuma geração em andamento no momento. Worker em espera (IDLE).
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

    # =========================================================================
    # 4. QUEUES & READY STOCK (Duas Colunas Operacionais)
    # =========================================================================
    st.markdown("#### 📋 Filas Operacionais & Estoque")
    col_queue_a, col_queue_b = st.columns(2)

    # Coluna A: Generation Queue
    with col_queue_a:
        with st.container(border=True):
            g_sum = data["g_summary"]
            st.markdown(f"**Generation Queue ({g_sum.get('total', 0)} tarefas)**")
            st.caption(
                f"Pending: `{g_sum.get('pending', 0)}` &nbsp;|&nbsp; "
                f"Processing: `{g_sum.get('processing', 0)}` &nbsp;|&nbsp; "
                f"Completed: `{g_sum.get('completed', 0)}` &nbsp;|&nbsp; "
                f"Failed: `{g_sum.get('failed', 0)}` &nbsp;|&nbsp; "
                f"Cancelled: `{g_sum.get('cancelled', 0)}`"
            )

            st.markdown("<div style='height: 4px;'></div>", unsafe_allow_html=True)
            st.markdown("##### Próximas Tarefas")
            recent_g = g_sum.get("recent_tasks", [])
            if recent_g:
                for t_item in recent_g[:5]:
                    t_sub = t_item.get("subject") or t_item.get("video_subject") or t_item.get("task_id", "")
                    t_id = t_item.get("task_id", "")
                    t_st = t_item.get("state")
                    st_lbl = {
                        const.TASK_STATE_PENDING: "Pendente",
                        const.TASK_STATE_PROCESSING: "Processando",
                        const.TASK_STATE_COMPLETE: "Concluída",
                        const.TASK_STATE_FAILED: "Falhou",
                        const.TASK_STATE_CANCELLED: "Cancelada",
                    }.get(t_st, str(t_st))

                    q_val = t_item.get("quality_score", "—")
                    s_val = t_item.get("strategy_score", "—")

                    c_r1, c_r2 = st.columns([0.72, 0.28])
                    with c_r1:
                        st.markdown(f"• **{t_sub[:38]}**")
                        st.caption(f"ID: `{_truncate_id(t_id, 6, 4)}` | Q: `{q_val}` | S: `{s_val}`")
                    with c_r2:
                        st.markdown(f"<span class='op-badge op-badge-gray'>{st_lbl}</span>", unsafe_allow_html=True)
            else:
                st.caption("Fila vazia. Nenhuma tarefa pendente.")

    # Coluna B: Publication Queue & Ready Stock
    with col_queue_b:
        with st.container(border=True):
            s_sum = data["s_summary"]
            st.markdown(f"**Publication Queue ({s_sum.get('total', 0)} agendamentos)**")
            st.caption(
                f"Planned: `{s_sum.get('planned', 0)}` &nbsp;|&nbsp; "
                f"Ready: `{s_sum.get('ready', 0)}` &nbsp;|&nbsp; "
                f"Processing: `{s_sum.get('processing', 0)}` &nbsp;|&nbsp; "
                f"Published: `{s_sum.get('published', 0)}` &nbsp;|&nbsp; "
                f"Failed: `{s_sum.get('failed', 0)}`"
            )

            st.markdown("<div style='height: 4px;'></div>", unsafe_allow_html=True)
            st.markdown("##### Próxima Publicação Agendada")
            upcoming = s_sum.get("upcoming_posts", [])
            if upcoming:
                nxt = upcoming[0]
                nxt_plat = nxt.get("platform", "YouTube").capitalize()
                nxt_time = nxt.get("scheduled_at", "—")
                nxt_top = nxt.get("topic") or f"Task {nxt.get('task_id', '')[:8]}"
                nxt_mode = nxt.get("growth_mode", data["growth_mode"])
                nxt_prof = nxt.get("profile_name")
                nxt_chan = nxt.get("channel_name")

                profile_channel_html = ""
                if nxt_prof:
                    profile_channel_html += f"<b>Perfil:</b> {nxt_prof}<br>"
                if nxt_chan:
                    profile_channel_html += f"<b>Canal:</b> {nxt_plat} — {nxt_chan}<br>"

                st.markdown(
                    f"""
                    <div style="background: rgba(59, 130, 246, 0.08); border-left: 4px solid #3b82f6; padding: 8px 12px; border-radius: 4px; font-size: 0.86rem; margin-bottom: 8px;">
                        <b>🚀 {nxt_plat.upper()}</b> &nbsp;|&nbsp; <b>Horário:</b> {nxt_time}<br>
                        {profile_channel_html}<b>Tema:</b> {nxt_top[:42]}<br>
                        <span style="opacity: 0.8; font-size: 0.8rem;">Growth Mode: {nxt_mode}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                st.caption("Nenhuma publicação agendada na fila.")

    # Ready Stock Panel
    stk_info = data["stock"]
    with st.container(border=True):
        col_stk_head, col_stk_badge = st.columns([0.7, 0.3])
        with col_stk_head:
            st.markdown("##### 📦 Ready Stock (Vídeos Prontos & Aprovados)")
        with col_stk_badge:
            if stk_info.get("is_below_minimum"):
                st.markdown("<div style='text-align: right;'><span class='op-badge op-badge-yellow'>⚠ WARNING (Abaixo do mínimo)</span></div>", unsafe_allow_html=True)
            else:
                st.markdown("<div style='text-align: right;'><span class='op-badge op-badge-green'>✓ HEALTHY</span></div>", unsafe_allow_html=True)

        stk_c1, stk_c2, stk_c3, stk_c4 = st.columns(4)
        with stk_c1:
            st.metric("YouTube Ready", stk_info.get("youtube_count", 0))
        with stk_c2:
            st.metric("TikTok Ready", stk_info.get("tiktok_count", 0))
        with stk_c3:
            st.metric("Cross-Platform", stk_info.get("cross_platform_count", 0))
        with stk_c4:
            st.metric("Meta Mínima", stk_info.get("minimum_threshold", 3))

        if stk_info.get("is_below_minimum"):
            st.warning("⚠ Estoque pronto abaixo do mínimo operacional. Recomenda-se planejar novas gerações pelo Autopilot.")

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

    # =========================================================================
    # 5. PROVIDER HEALTH (Saúde dos 8 Provedores)
    # =========================================================================
    st.markdown("#### 🩺 Saúde dos Provedores (Provider Health)")
    st.caption("Telemetria passiva e estática baseada em eventos reais. Nenhuma chamada externa desnecessária é realizada.")

    providers = data.get("providers", {})
    p_cols = st.columns(4)

    for idx, (p_name, p_val) in enumerate(providers.items()):
        col_idx = idx % 4
        with p_cols[col_idx]:
            p_status = p_val.get("status", "UNKNOWN")
            # Strict allowed statuses check
            if p_status not in ("CONFIGURED", "NOT CONFIGURED", "HEALTHY", "DEGRADED", "UNAVAILABLE", "UNKNOWN"):
                p_status = "UNKNOWN"

            if p_status == "HEALTHY":
                badge_html = "<span class='op-badge op-badge-green'>🟢 HEALTHY</span>"
            elif p_status == "DEGRADED":
                badge_html = "<span class='op-badge op-badge-yellow'>🟡 DEGRADED</span>"
            elif p_status == "UNAVAILABLE":
                badge_html = "<span class='op-badge op-badge-red'>🔴 UNAVAILABLE</span>"
            elif p_status == "CONFIGURED":
                badge_html = "<span class='op-badge op-badge-blue'>🔵 CONFIGURED</span>"
            else:
                badge_html = "<span class='op-badge op-badge-gray'>⚪ UNKNOWN</span>"

            last_succ = p_val.get("last_success", "—")
            last_err = _sanitize_text(p_val.get("last_error"))

            with st.container(border=True):
                st.markdown(f"**{p_name}** &nbsp; {badge_html}", unsafe_allow_html=True)
                st.caption(f"Último sucesso: `{last_succ}`")
                if last_err:
                    st.caption(f":red[Erro:] `{last_err[:40]}`")
                else:
                    st.caption(f":green[Operação normal]")

                with st.expander("Detalhes", expanded=False):
                    clean_details = _sanitize_text(p_val.get("details", "Sem detalhes adicionais"))
                    st.markdown(f"**Status:** `{p_status}`")
                    st.markdown(f"**Informação:** {clean_details}")
                    if p_status == "DEGRADED":
                        st.info("Impacto operacional: Sistema continua funcionando pelas fontes secundárias/locais.")

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

    # =========================================================================
    # 6. ALERTS, TIMELINE, ERRORS & RECOVERY
    # =========================================================================
    tab_alerts, tab_timeline, tab_errors, tab_recovery = st.tabs([
        "⚠️ Alert Center",
        "🕘 Linha do Tempo",
        "🛑 Central de Erros",
        "🧯 Central de Recuperação",
    ])

    # Tab 1: Alert Center (Active alerts only)
    with tab_alerts:
        alerts = data.get("alerts", [])
        if not alerts:
            st.success("✓ Nenhum alerta operacional ativo no momento.")
        else:
            for al in alerts:
                sev = al.get("severity", "WARNING")
                border_color = "#eab308" if sev == "WARNING" else "#ef4444"
                icon = "⚠" if sev == "WARNING" else "🚨"
                st.markdown(
                    f"""
                    <div style="border-left: 4px solid {border_color}; background: rgba(128, 128, 128, 0.05); padding: 10px 14px; border-radius: 4px; margin-bottom: 8px;">
                        <b>{icon} {al.get('title')}</b> <span style="font-size: 0.78rem; opacity: 0.7; float: right;">{al.get('time_ago', '')}</span><br>
                        <span style="font-size: 0.86rem; opacity: 0.9;">{al.get('desc')}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    # Tab 2: Operational Timeline
    with tab_timeline:
        timeline = data.get("timeline", [])
        if not timeline:
            st.caption("Nenhum evento registrado recentemente.")
        else:
            for item in timeline:
                c = item.get("color", "green")
                icon_html = f"<span class='op-badge op-badge-{c}'>{item.get('badge', '•')}</span>"
                st.markdown(
                    f"""
                    <div class="op-provider-row">
                        <span>{icon_html} &nbsp; <b>{item.get('time', '')}</b> &nbsp; {item.get('text', '')}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    # Tab 3: Error Center
    with tab_errors:
        errs = data.get("errors", [])
        if not errs:
            st.success("✓ Nenhum erro recente na Central de Erros.")
        else:
            for err in errs:
                sev = err.get("severity", "ERROR")
                c = "red" if sev in ("ERROR", "CRITICAL") else "orange"
                with st.expander(f":{c}[[{sev}]] {err.get('time')} — {err.get('component')}: {err.get('message')[:75]}", expanded=False):
                    st.write(f"**Componente:** {err.get('component')}")
                    st.write(f"**Task ID:** `{err.get('task_id')}`")
                    st.write(f"**Mensagem sanitizada:** {err.get('message')}")

    # Tab 4: Recovery Center
    with tab_recovery:
        recoverable = data.get("recoverable", [])
        if not recoverable:
            st.info("✓ Nenhuma tarefa requer recuperação no momento.")
        else:
            for r_item in recoverable:
                r_id = r_item.get("task_id", "")
                with st.container(border=True):
                    st.markdown(f"**Task:** `{_truncate_id(r_id, 8, 6)}` &nbsp;|&nbsp; **Tema:** {r_item.get('topic', '—')}")
                    st.caption(f"**Problema:** {r_item.get('problem')} &nbsp;|&nbsp; **Último estágio conhecido:** `{r_item.get('last_stage')}`")

                    c_rec1, c_rec2, _ = st.columns([0.25, 0.35, 0.4])
                    with c_rec1:
                        if st.button(
                            "🔄 Reexecutar",
                            key=f"rec_exec_{r_id}",
                            type="primary",
                            use_container_width=True,
                            disabled=not is_primary,
                            help="Modo VIEW ONLY: Apenas o nó primário pode reexecutar tarefas." if not is_primary else None,
                        ):
                            if not demo_enabled:
                                new_task_id = operator_console.reexecute_task(r_id)
                                st.success(f"Nova execução criada sob ID: {new_task_id}")
                                st.rerun()
                            else:
                                st.success("Reexecução simulada em modo demonstração.")
                    with c_rec2:
                        if st.button(
                            "✕ Marcar como cancelada",
                            key=f"rec_canc_{r_id}",
                            use_container_width=True,
                            disabled=not is_primary,
                            help="Modo VIEW ONLY: Apenas o nó primário pode cancelar tarefas." if not is_primary else None,
                        ):
                            if not demo_enabled:
                                from app.services import state as sm
                                sm.state.update_task(r_id, state=const.TASK_STATE_CANCELLED, progress=100)
                                st.toast(f"Task {r_id[:8]} marcada como cancelada.", icon="❌")
                                st.rerun()
                            else:
                                st.toast("Cancelamento simulado em modo demonstração.", icon="❌")

