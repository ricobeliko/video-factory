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
        "profile_overview": [
            {
                "profile_id": "default",
                "name": "Video Factory Default",
                "slug": "default",
                "niche": "curiosidades",
                "language": "pt-BR",
                "region": "BR",
                "default_preset": "cross_platform",
                "growth_mode": "normal",
                "is_active": True,
                "is_active_profile": False,
                "channels_count": 2,
                "channels_enabled": 2,
                "ready_stock": 2,
                "pending_processing": 1,
                "scheduled": 2,
                "failed": 0,
            },
            {
                "profile_id": "curiosidades-brasil",
                "name": "Curiosidades Brasil",
                "slug": "curiosidades-brasil",
                "niche": "curiosidades_brasil",
                "language": "pt-BR",
                "region": "BR",
                "default_preset": "cross_platform",
                "growth_mode": "warmup",
                "is_active": True,
                "is_active_profile": True,
                "channels_count": 2,
                "channels_enabled": 2,
                "ready_stock": 3,
                "pending_processing": 0,
                "scheduled": 2,
                "failed": 0,
            },
        ],
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


# ---------------------------------------------------------------------------
# Data Loading Helpers
# ---------------------------------------------------------------------------

def _load_telemetry_data(demo_enabled: bool, scenario_choice: str) -> Dict[str, Any]:
    if demo_enabled:
        return _get_mock_fixtures(scenario_choice)
    sys_status = operator_console.get_system_status()
    inst_info = sys_status.get("instance") or operator_console.get_instance_info()
    stock = operator_console.get_ready_stock()
    provs = operator_console.get_provider_health_summary()
    recent_errs = operator_console.get_recent_errors(limit=10)
    return {
        "factory_state": sys_status["factory_state"],
        "is_paused": sys_status["is_paused"],
        "generation_worker": sys_status["generation_worker"],
        "scheduler_worker": sys_status["scheduler_worker"],
        "auto_publish": sys_status["auto_publish"],
        "dry_run": sys_status["dry_run"],
        "growth_mode": sys_status["growth_mode"],
        "heartbeats": sys_status["heartbeats"],
        "last_publication": sys_status.get("last_publication"),
        "stock": stock,
        "providers": provs,
        "errors": recent_errs,
        "instance": inst_info,
    }


def _load_live_task_data(demo_enabled: bool, scenario_choice: str) -> Optional[Dict[str, Any]]:
    if demo_enabled:
        return _get_mock_fixtures(scenario_choice).get("active_task")
    from app.services import state as sm
    all_tasks, _ = sm.state.get_all_tasks(1, 30)
    for t in all_tasks:
        if t.get("state") == const.TASK_STATE_PROCESSING:
            from app.services import profile_manager
            task_p_id = t.get("profile_id") or profile_manager.get_task_profile_id(t.get("task_id", ""))
            task_p_obj = profile_manager.get_profile(task_p_id) if task_p_id else None
            task_prof_name = task_p_obj.get("name") if task_p_obj else "Video Factory Default"
            return {
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
    return None


def _load_queues_data(demo_enabled: bool, scenario_choice: str) -> Dict[str, Any]:
    if demo_enabled:
        d = _get_mock_fixtures(scenario_choice)
        return {
            "g_summary": d.get("g_summary", {}),
            "s_summary": d.get("s_summary", {}),
            "stock": d.get("stock", {}),
            "growth_mode": d.get("growth_mode", "normal"),
        }
    return {
        "g_summary": operator_console.get_generation_queue_summary(),
        "s_summary": operator_console.get_scheduler_queue_summary(),
        "stock": operator_console.get_ready_stock(),
        "growth_mode": operator_console.get_system_status().get("growth_mode", "normal"),
    }


# ---------------------------------------------------------------------------
# Section 1 & 2: Command Header & Telemetry Cards
# ---------------------------------------------------------------------------

def _render_command_header_and_telemetry_content(demo_enabled: bool, scenario_choice: str, is_primary: bool):
    data = _load_telemetry_data(demo_enabled, scenario_choice)
    factory_state = data["factory_state"]
    is_paused = data["is_paused"]
    inst_info = data.get("instance") or {}
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

    # Persistent Paused Banner
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

    # Health Cards
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


@st.fragment(run_every="5s")
def _render_command_header_and_telemetry_active(demo_enabled: bool, scenario_choice: str, is_primary: bool):
    _render_command_header_and_telemetry_content(demo_enabled, scenario_choice, is_primary)


@st.fragment(run_every="15s")
def _render_command_header_and_telemetry_idle(demo_enabled: bool, scenario_choice: str, is_primary: bool):
    _render_command_header_and_telemetry_content(demo_enabled, scenario_choice, is_primary)


# ---------------------------------------------------------------------------
# Section 3: Live Operations (Tempo Real)
# ---------------------------------------------------------------------------

def _render_live_operations_content(demo_enabled: bool, scenario_choice: str, is_primary: bool):
    st.markdown("#### ⚡ Operações em Tempo Real")
    active_task = _load_live_task_data(demo_enabled, scenario_choice)
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


@st.fragment(run_every="5s")
def _render_live_operations_active(demo_enabled: bool, scenario_choice: str, is_primary: bool):
    _render_live_operations_content(demo_enabled, scenario_choice, is_primary)


def _render_live_operations_idle(demo_enabled: bool, scenario_choice: str, is_primary: bool):
    _render_live_operations_content(demo_enabled, scenario_choice, is_primary)


# ---------------------------------------------------------------------------
# Section 4: Queues & Ready Stock
# ---------------------------------------------------------------------------

def _render_queues_content(demo_enabled: bool, scenario_choice: str, is_primary: bool):
    st.markdown("#### 📋 Filas Operacionais & Estoque")
    data = _load_queues_data(demo_enabled, scenario_choice)
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
            st.markdown("##### Próximas Publicações Agendadas")
            upcoming = s_sum.get("upcoming_posts", [])

            all_queue_profs = sorted(list({str(p.get("profile_name") or "Default/Legacy") for p in upcoming}))
            all_queue_plats = sorted(list({str(p.get("platform") or "YouTube").capitalize() for p in upcoming}))
            all_queue_stats = sorted(list({str(p.get("status") or "planned").lower() for p in upcoming}))

            with st.expander("🔍 Filtros da Fila", expanded=False):
                q_f1, q_f2, q_f3 = st.columns(3)
                with q_f1:
                    filter_prof = st.selectbox("Perfil:", options=["Todos"] + all_queue_profs, key="op_q_filt_prof")
                with q_f2:
                    filter_plat = st.selectbox("Plataforma:", options=["Todas"] + all_queue_plats, key="op_q_filt_plat")
                with q_f3:
                    filter_stat = st.selectbox("Status:", options=["Todos"] + all_queue_stats, key="op_q_filt_stat")

            filtered_upcoming = []
            for post in upcoming:
                p_name = post.get("profile_name") or "Default/Legacy"
                plat = str(post.get("platform") or "YouTube").capitalize()
                stat = str(post.get("status") or "planned").lower()

                if filter_prof != "Todos" and p_name != filter_prof:
                    continue
                if filter_plat != "Todas" and plat.lower() != filter_plat.lower():
                    continue
                if filter_stat != "Todos" and stat != filter_stat.lower():
                    continue
                filtered_upcoming.append(post)

            if filtered_upcoming:
                for post_item in filtered_upcoming[:5]:
                    p_plat = str(post_item.get("platform") or "YouTube").capitalize()
                    p_time = post_item.get("scheduled_at") or "—"
                    p_top = post_item.get("topic") or f"Task {str(post_item.get('task_id', ''))[:8]}"
                    p_prof = post_item.get("profile_name") or "Default/Legacy"
                    p_chan = post_item.get("channel_name") or "Legacy"
                    p_stat = post_item.get("status") or "planned"
                    p_mode = post_item.get("growth_mode") or data.get("growth_mode", "normal")

                    stat_badge = "🟢 Planned" if p_stat == "planned" else ("🔵 Ready" if p_stat == "ready" else f"⚪ {p_stat}")

                    st.markdown(
                        f"""
                        <div style="background: rgba(59, 130, 246, 0.08); border-left: 4px solid #3b82f6; padding: 6px 10px; border-radius: 4px; font-size: 0.84rem; margin-bottom: 6px;">
                            <div style="display: flex; justify-content: space-between;">
                                <b>🚀 {p_plat.upper()}</b>
                                <span>{stat_badge} &nbsp;|&nbsp; <b>{p_time}</b></span>
                            </div>
                            <b>Perfil:</b> {html.escape(str(p_prof))} &nbsp;|&nbsp; <b>Canal:</b> {html.escape(str(p_chan))}<br>
                            <b>Tema:</b> {html.escape(str(p_top[:42]))}<br>
                            <span style="opacity: 0.8; font-size: 0.78rem;">Growth Mode: {html.escape(str(p_mode))}</span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("Nenhum agendamento encontrado para os filtros selecionados.")

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


@st.fragment(run_every="10s")
def _render_queues_active(demo_enabled: bool, scenario_choice: str, is_primary: bool):
    _render_queues_content(demo_enabled, scenario_choice, is_primary)


@st.fragment(run_every="30s")
def _render_queues_idle(demo_enabled: bool, scenario_choice: str, is_primary: bool):
    _render_queues_content(demo_enabled, scenario_choice, is_primary)


# ---------------------------------------------------------------------------
# Section 4.5: Multi-Profile & Channel Management (STATIC - Sem auto-refresh)
# ---------------------------------------------------------------------------

def _render_profile_management_section(demo_enabled: bool, scenario_choice: str, is_primary: bool):
    st.markdown("#### 📁 Multi-Profile & Channel Management")
    st.caption("Gerenciamento operacional de perfis de conteúdo e canais de distribuição vinculados.")

    from app.services import profile_manager
    active_prof = profile_manager.get_active_profile()
    active_prof_id = active_prof.get("id") or "default"

    if demo_enabled:
        prof_overview = _get_mock_fixtures(scenario_choice).get("profile_overview", [])
    else:
        prof_overview = operator_console.get_profile_operations_overview()

    if not prof_overview:
        raw_profs = profile_manager.list_profiles()
        prof_overview = [
            {
                "profile_id": p["id"],
                "name": p.get("name"),
                "slug": p.get("slug"),
                "niche": p.get("niche") or "—",
                "language": p.get("language") or "pt-BR",
                "region": p.get("region") or "BR",
                "default_preset": p.get("default_preset") or "cross_platform",
                "growth_mode": p.get("growth_mode") or "normal",
                "is_active": bool(p.get("is_active")),
                "is_active_profile": (p["id"] == active_prof_id),
                "channels_count": 0,
                "channels_enabled": 0,
                "ready_stock": 0,
                "pending_processing": 0,
                "scheduled": 0,
                "failed": 0,
            }
            for p in raw_profs
        ]

    # Operations Overview per Profile
    with st.container(border=True):
        st.markdown("##### 📊 Visão Geral Operacional por Perfil")
        p_table_rows = []
        for po in prof_overview:
            act_badge = "🟢 Ativo" if po.get("is_active") else "⚪ Inativo"
            is_cur_active = " ⭐ [ATIVO]" if po.get("is_active_profile") else ""
            p_table_rows.append({
                "Perfil": f"{po.get('name')}{is_cur_active}",
                "Slug": po.get("slug"),
                "Nicho": po.get("niche"),
                "Idioma/Região": f"{po.get('language')}/{po.get('region')}",
                "Preset": po.get("default_preset"),
                "Modo": po.get("growth_mode"),
                "Canais": f"{po.get('channels_enabled')}/{po.get('channels_count')}",
                "Estoque": po.get("ready_stock", 0),
                "Em Andamento": po.get("pending_processing", 0),
                "Agendados": po.get("scheduled", 0),
                "Falhas": po.get("failed", 0),
                "Status": act_badge,
            })
        st.dataframe(p_table_rows, use_container_width=True, hide_index=True)

    # Detalhes e Gestão de Perfil Selecionado
    with st.container(border=True):
        prof_ids = [po["profile_id"] for po in prof_overview]
        prof_labels = {po["profile_id"]: f"{po.get('name')} ({po.get('slug')})" + (" ⭐ [ATIVO]" if po.get("is_active_profile") else "") for po in prof_overview}

        sel_p_idx = 0
        if active_prof_id in prof_ids:
            sel_p_idx = prof_ids.index(active_prof_id)

        col_sel_p, col_p_actions = st.columns([0.65, 0.35])
        with col_sel_p:
            selected_m_prof_id = st.selectbox(
                "Selecionar Perfil para Detalhes / Gestão de Canais:",
                options=prof_ids,
                index=sel_p_idx,
                format_func=lambda pid: prof_labels.get(pid, pid),
                key="op_m_prof_selector",
            )

        cur_selected_po = next((po for po in prof_overview if po["profile_id"] == selected_m_prof_id), prof_overview[0] if prof_overview else {})
        is_sel_active = cur_selected_po.get("is_active_profile", False)

        with col_p_actions:
            st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
            if not is_sel_active and cur_selected_po.get("is_active"):
                if st.button(
                    "⭐ Ativar como Perfil Atual",
                    key=f"op_set_active_btn_{selected_m_prof_id}",
                    disabled=not is_primary,
                    help="Apenas o nó primário pode alternar perfis." if not is_primary else "Torna este o perfil operacional ativo para novas gerações.",
                    use_container_width=True,
                ):
                    if not demo_enabled:
                        profile_manager.set_active_profile(selected_m_prof_id)
                        st.toast(f"Perfil '{cur_selected_po.get('name')}' definido como ativo.", icon="⭐")
                        st.rerun()
                    else:
                        st.toast("Perfil ativo simulado em modo demonstração.", icon="⭐")

        # Visualizar/Editar Perfil e Criar Novo Perfil em Colunas/Expanders
        c_prof_edit, c_prof_create = st.columns(2)

        with c_prof_edit:
            with st.expander(f"✏️ Editar Perfil: {cur_selected_po.get('name')}", expanded=False):
                if not is_primary:
                    st.caption("🔒 View Only — alterações devem ser realizadas no PRIMARY.")
                e_name = st.text_input("Nome do Perfil", value=cur_selected_po.get("name") or "", key=f"edit_p_name_{selected_m_prof_id}", disabled=not is_primary)
                e_niche = st.text_input("Nicho", value=cur_selected_po.get("niche") or "", key=f"edit_p_niche_{selected_m_prof_id}", disabled=not is_primary)

                c_e1, c_e2 = st.columns(2)
                with c_e1:
                    e_lang = st.text_input("Idioma", value=cur_selected_po.get("language") or "pt-BR", key=f"edit_p_lang_{selected_m_prof_id}", disabled=not is_primary)
                with c_e2:
                    e_reg = st.text_input("Região", value=cur_selected_po.get("region") or "BR", key=f"edit_p_reg_{selected_m_prof_id}", disabled=not is_primary)

                c_e3, c_e4 = st.columns(2)
                with c_e3:
                    preset_opts = ["cross_platform", "youtube_shorts_original", "tiktok_rewards"]
                    curr_pr = cur_selected_po.get("default_preset") or "cross_platform"
                    pr_idx = preset_opts.index(curr_pr) if curr_pr in preset_opts else 0
                    e_preset = st.selectbox("Preset Padrão", options=preset_opts, index=pr_idx, key=f"edit_p_preset_{selected_m_prof_id}", disabled=not is_primary)
                with c_e4:
                    growth_opts = ["warmup", "conservative", "normal", "scale"]
                    curr_gw = cur_selected_po.get("growth_mode") or "normal"
                    gw_idx = growth_opts.index(curr_gw) if curr_gw in growth_opts else 2
                    e_growth = st.selectbox("Growth Mode", options=growth_opts, index=gw_idx, key=f"edit_p_growth_{selected_m_prof_id}", disabled=not is_primary)

                is_default_profile = (selected_m_prof_id == "default")
                e_active = st.checkbox(
                    "Perfil Ativo",
                    value=cur_selected_po.get("is_active", True),
                    key=f"edit_p_active_{selected_m_prof_id}",
                    disabled=(not is_primary or is_default_profile),
                    help="O perfil 'default' é a base do sistema e não pode ser desativado." if is_default_profile else None,
                )

                if st.button("Salvar Alterações do Perfil", key=f"btn_save_p_{selected_m_prof_id}", disabled=not is_primary, type="primary"):
                    if not demo_enabled:
                        try:
                            profile_manager.update_profile(
                                profile_id=selected_m_prof_id,
                                name=e_name.strip() or None,
                                niche=e_niche.strip() or None,
                                language=e_lang.strip() or None,
                                region=e_reg.strip() or None,
                                default_preset=e_preset,
                                growth_mode=e_growth,
                                is_active=e_active,
                            )
                            st.toast("Perfil atualizado com sucesso!", icon="💾")
                            st.rerun()
                        except Exception as p_err:
                            st.error(f"Erro ao salvar perfil: {p_err}")
                    else:
                        st.toast("Perfil atualizado em modo demonstração.", icon="💾")

        with c_prof_create:
            with st.expander("➕ Criar Novo Perfil de Conteúdo", expanded=False):
                if not is_primary:
                    st.caption("🔒 View Only — novos perfis devem ser criados no PRIMARY.")
                new_p_name = st.text_input("Nome do Perfil", placeholder="Ex: Curiosidades Brasil", key="new_p_name", disabled=not is_primary)
                new_p_slug = st.text_input("Slug Identificador", placeholder="Ex: curiosidades-brasil", key="new_p_slug", disabled=not is_primary)
                new_p_niche = st.text_input("Nicho Principal", placeholder="Ex: Curiosidades", key="new_p_niche", disabled=not is_primary)

                c_np1, c_np2 = st.columns(2)
                with c_np1:
                    new_p_lang = st.text_input("Idioma", value="pt-BR", key="new_p_lang", disabled=not is_primary)
                with c_np2:
                    new_p_reg = st.text_input("Região", value="BR", key="new_p_reg", disabled=not is_primary)

                c_np3, c_np4 = st.columns(2)
                with c_np3:
                    new_p_preset = st.selectbox("Preset Inicial", options=["cross_platform", "youtube_shorts_original", "tiktok_rewards"], key="new_p_preset", disabled=not is_primary)
                with c_np4:
                    new_p_growth = st.selectbox("Growth Inicial", options=["warmup", "conservative", "normal", "scale"], index=2, key="new_p_growth", disabled=not is_primary)

                if st.button("Criar e Ativar Perfil", key="btn_create_p", disabled=not is_primary, type="primary"):
                    if not new_p_name.strip() or not new_p_slug.strip():
                        st.warning("Nome e Slug são obrigatórios para criar o perfil.")
                    elif not demo_enabled:
                        try:
                            new_p = profile_manager.create_profile(
                                name=new_p_name.strip(),
                                slug=new_p_slug.strip(),
                                niche=new_p_niche.strip() or None,
                                language=new_p_lang.strip() or "pt-BR",
                                region=new_p_reg.strip() or "BR",
                                default_preset=new_p_preset,
                                growth_mode=new_p_growth,
                                is_active=True,
                            )
                            st.toast(f"Perfil '{new_p['name']}' criado com sucesso!", icon="🎉")
                            st.rerun()
                        except Exception as c_err:
                            st.error(f"Erro ao criar perfil: {c_err}")
                    else:
                        st.toast("Perfil criado em modo demonstração.", icon="🎉")

        # Canais Vinculados ao Perfil Selecionado
        st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
        st.markdown(f"##### 📺 Canais de Publicação Vinculados — {cur_selected_po.get('name')}")

        channels = []
        if not demo_enabled:
            channels = profile_manager.list_channels(profile_id=selected_m_prof_id)
        else:
            channels = [
                {
                    "id": "mock_ch_yt",
                    "profile_id": selected_m_prof_id,
                    "platform": "youtube",
                    "display_name": f"{cur_selected_po.get('name')} Oficial",
                    "external_profile_name": "@canal_oficial",
                    "is_enabled": 1,
                    "created_at": "2026-09-18 10:00:00",
                },
                {
                    "id": "mock_ch_tk",
                    "profile_id": selected_m_prof_id,
                    "platform": "tiktok",
                    "display_name": f"{cur_selected_po.get('name')} Shorts",
                    "external_profile_name": "@tiktok_oficial",
                    "is_enabled": 1,
                    "created_at": "2026-09-18 10:00:00",
                }
            ]

        if channels:
            ch_rows = []
            for ch in channels:
                ch_status = "🟢 Habilitado" if ch.get("is_enabled") else "⚪ Desabilitado"
                plat_icon = "▶️ YouTube" if ch.get("platform") == "youtube" else ("🎵 TikTok" if ch.get("platform") == "tiktok" else ch.get("platform"))
                ch_rows.append({
                    "ID": ch["id"],
                    "Plataforma": plat_icon,
                    "Nome de Exibição": ch.get("display_name"),
                    "Identificador Externo": ch.get("external_profile_name") or "—",
                    "Status": ch_status,
                })
            st.dataframe(ch_rows, use_container_width=True, hide_index=True)

            c_ch_sel, c_ch_btn = st.columns([0.7, 0.3])
            with c_ch_sel:
                ch_opts = [ch["id"] for ch in channels]
                ch_lbls = {ch["id"]: f"{ch.get('platform').upper()} — {ch.get('display_name')}" for ch in channels}
                sel_ch_act = st.selectbox("Selecionar Canal para Ação:", options=ch_opts, format_func=lambda cid: ch_lbls.get(cid, cid), key="op_ch_act_sel")
            with c_ch_btn:
                st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
                cur_ch_obj = next((ch for ch in channels if ch["id"] == sel_ch_act), None)
                if cur_ch_obj:
                    ch_is_en = bool(cur_ch_obj.get("is_enabled"))
                    ch_btn_lbl = "Desabilitar Canal" if ch_is_en else "Habilitar Canal"
                    if st.button(ch_btn_lbl, key=f"btn_toggle_ch_{sel_ch_act}", disabled=not is_primary, use_container_width=True):
                        if not demo_enabled:
                            profile_manager.toggle_channel(sel_ch_act, is_enabled=not ch_is_en)
                            st.toast(f"Canal alterado para {'habilitado' if not ch_is_en else 'desabilitado'}.", icon="📺")
                            st.rerun()
                        else:
                            st.toast("Canal alterado em demonstração.", icon="📺")
        else:
            st.info(f"Nenhum canal de publicação vinculado a este perfil. Adicione abaixo.")

        with st.expander("➕ Vincular Novo Canal ao Perfil", expanded=False):
            if not is_primary:
                st.caption("🔒 View Only — novos canais devem ser vinculados no PRIMARY.")
            col_nc1, col_nc2 = st.columns(2)
            with col_nc1:
                new_ch_plat = st.selectbox("Plataforma", options=["youtube", "tiktok"], key="new_ch_plat", disabled=not is_primary)
                new_ch_name = st.text_input("Nome de Exibição", placeholder="Ex: Canal Principal Brasil", key="new_ch_name", disabled=not is_primary)
            with col_nc2:
                new_ch_ext = st.text_input("Identificador Externo / Handle (opcional)", placeholder="Ex: @meucanal", key="new_ch_ext", disabled=not is_primary)
                new_ch_en = st.checkbox("Canal Habilitado para Publicação", value=True, key="new_ch_en", disabled=not is_primary)

            if st.button("Vincular Canal", key="btn_create_ch", disabled=not is_primary, type="primary"):
                if not new_ch_name.strip():
                    st.warning("O nome de exibição é obrigatório.")
                elif not demo_enabled:
                    try:
                        profile_manager.create_channel(
                            profile_id=selected_m_prof_id,
                            platform=new_ch_plat,
                            display_name=new_ch_name.strip(),
                            external_profile_name=new_ch_ext.strip() or None,
                            is_enabled=new_ch_en,
                        )
                        st.toast("Canal vinculado com sucesso!", icon="📺")
                        st.rerun()
                    except Exception as ch_err:
                        st.error(f"Erro ao vincular canal: {ch_err}")
                else:
                    st.toast("Canal vinculado em demonstração.", icon="📺")

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Section 5: Provider Health & Analytics Providers (STATIC - Sem auto-refresh)
# ---------------------------------------------------------------------------

def _render_provider_health_section(demo_enabled: bool, scenario_choice: str, is_primary: bool):
    st.markdown("#### 🩺 Saúde dos Provedores (Provider Health)")
    st.caption("Telemetria passiva e estática baseada em eventos reais. Nenhuma chamada externa desnecessária é realizada.")

    if demo_enabled:
        providers = _get_mock_fixtures(scenario_choice).get("providers", {})
    else:
        providers = operator_console.get_provider_health_summary()

    p_cols = st.columns(4)

    for idx, (p_name, p_val) in enumerate(providers.items()):
        col_idx = idx % 4
        with p_cols[col_idx]:
            p_status = p_val.get("status", "UNKNOWN")
            if p_status not in ("CONFIGURED", "NOT CONFIGURED", "NOT_CONFIGURED", "HEALTHY", "DEGRADED", "UNAVAILABLE", "UNKNOWN"):
                p_status = "UNKNOWN"

            if p_status == "HEALTHY":
                badge_html = "<span class='op-badge op-badge-green'>🟢 HEALTHY</span>"
            elif p_status == "DEGRADED":
                badge_html = "<span class='op-badge op-badge-yellow'>🟡 DEGRADED</span>"
            elif p_status == "UNAVAILABLE":
                badge_html = "<span class='op-badge op-badge-red'>🔴 UNAVAILABLE</span>"
            elif p_status == "CONFIGURED":
                badge_html = "<span class='op-badge op-badge-blue'>🔵 CONFIGURED</span>"
            elif p_status in ("NOT CONFIGURED", "NOT_CONFIGURED"):
                badge_html = "<span class='op-badge op-badge-gray'>⚪ NOT CONFIGURED</span>"
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

                    if p_name in ("YouTube Analytics", "TikTok Analytics"):
                        plat = "youtube" if "youtube" in p_name.lower() else "tiktok"
                        if st.button(f"🔍 Testar Configuração", key=f"op_test_cfg_{plat}", use_container_width=True):
                            res = operator_console.test_analytics_provider_configuration(plat)
                            if res.get("configured"):
                                st.success(f"✓ Configuração do {p_name} válida e pronta para uso.")
                            else:
                                st.warning(f"⚠ Configuração incompleta. Campo(s) ausente(s): {res.get('missing_fields')}")

                        with st.popover(f"📥 Coleta Manual ({plat.upper()})", use_container_width=True):
                            st.markdown(f"**Coleta Manual Controlada — {p_name}**")
                            st.caption("Executa coleta pontual de UMA publicação por vez. Nenhuma coleta em lote ou polling.")
                            fetch_task_id = st.text_input(f"Task ID da publicação ({plat}):", key=f"op_fetch_tid_{plat}")
                            fetch_persist = st.checkbox(
                                "Persistir snapshot no histórico (requer PRIMARY)",
                                value=False,
                                key=f"op_fetch_persist_{plat}",
                                disabled=not is_primary,
                            )
                            if not is_primary and fetch_persist:
                                st.caption(":red[Modo VIEW ONLY: apenas consulta sem persistência permitida.]")
                            st.markdown("**Confirmação explícita:**")
                            st.markdown(f"- Plataforma: `{plat}`")
                            st.markdown(f"- Task: `{fetch_task_id or '(não informada)'}`")
                            st.markdown(f"- Modo: `{'Persistir snapshot' if fetch_persist else 'Consulta apenas (sem gravar)'}`")
                            if st.button("Confirmar e Buscar Métricas", key=f"op_fetch_btn_{plat}", disabled=not fetch_task_id):
                                try:
                                    f_res = operator_console.fetch_real_metrics_for_publication_op(
                                        task_id=fetch_task_id.strip(),
                                        platform=plat,
                                        persist=fetch_persist,
                                    )
                                    st.success(f"✓ Coleta concluída com sucesso! (Persistido: {f_res.get('persisted')})")
                                    st.json(f_res.get("metrics") or f_res.get("snapshot", {}))
                                except Exception as f_err:
                                    st.error(f"Erro na coleta: {f_err}")

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Section 5.5: Automatic Analytics Scheduler (Fase V10-C)
# ---------------------------------------------------------------------------

def _render_automatic_analytics_section(demo_enabled: bool, scenario_choice: str, is_primary: bool):
    st.markdown("#### ⏱️ Coleta Automática de Analytics (Automatic Analytics)")
    st.caption("Ciclo periódico conservador com política de cooldown por idade, rate limits globais e backoff.")

    status_data = operator_console.get_analytics_scheduler_status()
    enabled = status_data.get("auto_collection_enabled", False)
    last_cycle = status_data.get("last_cycle_at") or "—"
    last_success = status_data.get("last_success_at") or "—"
    has_eligible = status_data.get("has_eligible_now", False)
    next_eligible_str = "Agora (candidato disponível)" if has_eligible else "Nenhum candidato no momento"
    backoffs = status_data.get("provider_backoffs", {})
    snapshots_today = status_data.get("snapshots_today", 0)

    status_badge = "<span class='op-badge op-badge-green'>🟢 Ativado (Enabled)</span>" if enabled else "<span class='op-badge op-badge-gray'>⚪ Desativado (Disabled)</span>"

    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(f"**Status:** {status_badge}", unsafe_allow_html=True)
            st.caption(f"Teto por ciclo: `{status_data.get('max_fetches_per_cycle', 3)}` coletas")
        with c2:
            st.markdown(f"**Último Ciclo:** `{last_cycle}`")
            st.markdown(f"**Último Sucesso:** `{last_success}`")
        with c3:
            st.markdown(f"**Snapshots Hoje:** `{snapshots_today}`")
            st.markdown(f"**Próxima Coleta:** `{next_eligible_str}`")

        if backoffs:
            st.markdown("**Backoff ativo por provider:**")
            for plat, binfo in backoffs.items():
                st.warning(f"⚠ Provider **{plat.upper()}** em backoff até `{binfo.get('until')}` (Motivo: `{binfo.get('reason')}`, restante: {binfo.get('remaining_seconds')}s)")

        if is_primary:
            b1, b2, b3 = st.columns(3)
            with b1:
                if not enabled:
                    if st.button("▶️ Ativar Coleta Automática (Enable)", key="op_enable_auto_analytics", use_container_width=True):
                        operator_console.set_analytics_auto_collection_enabled_op(True)
                        st.success("Coleta automática ativada!")
                        st.rerun()
                else:
                    if st.button("⏸️ Desativar Coleta Automática (Disable)", key="op_disable_auto_analytics", use_container_width=True):
                        operator_console.set_analytics_auto_collection_enabled_op(False)
                        st.info("Coleta automática desativada.")
                        st.rerun()
            with b2:
                if st.button("⚡ Executar Um Ciclo Agora (Run One Cycle Now)", key="op_run_one_cycle_now", use_container_width=True):
                    res = operator_console.run_analytics_collection_cycle_op()
                    if res.get("status") == "completed":
                        st.success(f"✓ Ciclo executado com sucesso! ({res.get('processed_count')}/{res.get('candidates_count')} processados)")
                    elif res.get("status") == "idle":
                        st.info(f"ℹ️ Ciclo concluído: {res.get('message')}")
                    else:
                        st.warning(f"⚠ Ciclo ignorado: {res.get('reason')} ({res.get('message')})")
                    st.rerun()
            with b3:
                st.caption("Ações restritas ao nó PRIMARY. Em SECONDARY_VIEW_ONLY os controles são desativados.")
        else:
            st.info("ℹ️ Modo VIEW ONLY: somente leitura. Controles de ativação e execução desabilitados.")

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Section 5.55: Autonomous Production Loop (Fase V12-E - STATIC)
# ---------------------------------------------------------------------------

def _render_autonomous_production_section(demo_enabled: bool, scenario_choice: str, is_primary: bool):
    st.markdown("#### 🤖 Produção Autônoma (Autonomous Production Loop)")
    st.caption("Fábrica autônoma self-feeding: monitoramento de estoque, geração automática de temas, Quality & Safety Gates e abastecimento do Scheduler (YouTube).")

    if demo_enabled:
        enabled = (scenario_choice in ("Factory RUNNING", "Full Showcase (Todos os 7 Estados)"))
        state = "generating" if scenario_choice == "Factory RUNNING" else ("idle" if scenario_choice == "Full Showcase (Todos os 7 Estados)" else "disabled")
        ready_stock = 2
        target_stock = 3
        generated_today = 1
        max_24h = 5
        current_task = "3 fatos surpreendentes sobre buracos negros" if state == "generating" else "—"
        last_cycle = "2026-09-19T22:10:00+00:00"
        next_cycle = "2026-09-19T22:25:00+00:00"
        last_error = None
        message = "Geração autônoma em andamento para YouTube" if state == "generating" else "Estoque em monitoramento"
    else:
        status_data = operator_console.get_autonomous_production_status_op()
        enabled = status_data.get("autonomous_mode_enabled", False)
        state = status_data.get("state", "disabled")
        ready_stock = status_data.get("ready_stock_total", 0)
        target_stock = status_data.get("target_ready_stock", 3)
        generated_today = status_data.get("generated_today_24h", 0)
        max_24h = status_data.get("max_generations_24h", 5)
        current_task = status_data.get("current_task_id") or "—"
        last_cycle = status_data.get("last_tick") or "—"
        next_cycle = status_data.get("next_cycle_at") or "—"
        last_error = status_data.get("last_error")
        message = status_data.get("message") or "—"

    # Badges
    mode_badge = "<span class='op-badge op-badge-green'>🟢 ON (Ativado)</span>" if enabled else "<span class='op-badge op-badge-gray'>⚪ OFF (Desativado)</span>"
    state_col = "green" if state == "idle" else ("yellow" if state in ("generating", "planning", "reviewing", "scheduling") else ("red" if state in ("blocked", "error") else "gray"))
    state_badge = f"<span class='op-badge op-badge-{state_col}'>{state.upper()}</span>"

    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(f"**Modo Autônomo:** {mode_badge}", unsafe_allow_html=True)
            st.markdown(f"**Estado Atual:** {state_badge}", unsafe_allow_html=True)
            st.caption(f"Status: {message}")
        with c2:
            st.markdown(f"**Estoque Pronto:** `{ready_stock} / {target_stock}` vídeos")
            st.markdown(f"**Gerados Hoje (24h):** `{generated_today} / {max_24h}`")
            st.caption(f"Tarefa Atual: `{current_task[:25]}`" if current_task != "—" else "Tarefa Atual: Nenhuma")
        with c3:
            st.markdown(f"**Último Ciclo:** `{last_cycle}`")
            st.markdown(f"**Próximo Ciclo:** `{next_cycle}`")
            if last_error:
                st.caption(f"⚠️ Último Erro: `{last_error[:45]}`")

        if is_primary:
            b1, b2, b3 = st.columns(3)
            with b1:
                if not enabled:
                    if st.button("▶️ Ativar Produção Autônoma", key="op_enable_autonomous_prod", use_container_width=True):
                        if not demo_enabled:
                            operator_console.set_autonomous_mode_enabled_op(True)
                            st.success("Produção autônoma ATIVADA!")
                            st.rerun()
                        else:
                            st.toast("Modo autônomo ativado (simulação demo).", icon="🤖")
                else:
                    if st.button("⏸️ Desativar Produção Autônoma", key="op_disable_autonomous_prod", use_container_width=True):
                        if not demo_enabled:
                            operator_console.set_autonomous_mode_enabled_op(False)
                            st.info("Produção autônoma DESATIVADA.")
                            st.rerun()
                        else:
                            st.toast("Modo autônomo desativado (simulação demo).", icon="⏸️")
            with b2:
                if st.button("⚡ Executar Ciclo Agora (Run Cycle)", key="op_run_autonomous_cycle_now", use_container_width=True):
                    if not demo_enabled:
                        with st.spinner("Executando ciclo autônomo..."):
                            res = operator_console.run_autonomous_cycle_op(force=True)
                            if res.get("status") in ("scheduled", "generation_started"):
                                st.success(f"✓ {res.get('message')}")
                            elif res.get("status") == "idle":
                                st.info(f"ℹ️ {res.get('message')}")
                            elif res.get("status") == "blocked":
                                st.warning(f"⚠️ Bloqueado: {res.get('message')}")
                            else:
                                st.info(f"ℹ️ Resultado: {res.get('status')} — {res.get('message')}")
                            st.rerun()
                    else:
                        st.toast("Ciclo executado no modo demo.", icon="⚡")
            with b3:
                st.caption("Destino Exclusivo: **YouTube** (TikTok bloqueado nesta fase). Publicação realizada pelo Scheduler.")
        else:
            st.info("ℹ️ Modo VIEW ONLY: somente leitura. Controles de ativação e execução desabilitados.")

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)



# ---------------------------------------------------------------------------
# Section 5.6: Clip Mode Foundation (Fase V11-A - STATIC - Sem auto-refresh)
# ---------------------------------------------------------------------------

def _render_clip_mode_section(demo_enabled: bool, scenario_choice: str, is_primary: bool):
    st.markdown("#### 🎬 Clip Mode (Reaproveitamento de Vídeos Longos)")
    st.caption("Biblioteca de mídias longas autorizadas e cadastro de segmentos para cortes verticais.")

    from app.services import profile_manager, clip_mode

    # Busca dados no banco local (zero FFmpeg / zero probe / zero hash na abertura)
    if demo_enabled:
        sources = [
            {
                "id": "src_demo_001",
                "original_filename": "podcast_ep42_autorizado.mp4",
                "profile_id": "default",
                "duration_seconds": 1845.0,
                "width": 1920,
                "height": 1080,
                "fps": 30.0,
                "has_audio": 1,
                "source_origin": "owned",
                "authorization_confirmed": 1,
                "status": "READY",
                "created_at": "2026-09-18T20:00:00+00:00",
            }
        ]
        segments = [
            {
                "id": "seg_demo_001",
                "source_id": "src_demo_001",
                "profile_id": "default",
                "start_seconds": 120.0,
                "end_seconds": 175.0,
                "duration_seconds": 55.0,
                "title": "Momento Chave Podcast",
                "status": "CANDIDATE",
                "selection_method": "manual",
                "created_at": "2026-09-18T20:05:00+00:00",
            }
        ]
        profiles = [{"id": "default", "name": "Video Factory Default"}]
    else:
        sources = operator_console.list_clip_sources_op()
        segments = operator_console.list_clip_segments_op()
        profiles = profile_manager.list_profiles()

    tab_library, tab_import, tab_transcripts, tab_segments, tab_renders = st.tabs([
        "📚 Biblioteca de Fontes (Source Library)",
        "📥 Importar Mídia Autorizada (Import Source)",
        "📜 Transcrições (Transcripts)",
        "✂️ Segmentos e Cortes (Segments)",
        "🎬 Renders & Review (Clips Verticais)",
    ])

    # 1. Source Library
    with tab_library:
        if not sources:
            st.info("ℹ️ Nenhuma fonte cadastrada na biblioteca. Use a aba 'Importar Mídia' para adicionar vídeos autorizados.")
        else:
            for src in sources:
                s_id = src.get("id", "")
                st_color = "green" if src.get("status") == "READY" else ("gray" if src.get("status") == "INACTIVE" else "red")
                badge_html = f"<span class='op-badge op-badge-{st_color}'>{src.get('status')}</span>"
                dur_min = (src.get("duration_seconds") or 0.0) / 60.0
                audio_str = "🔊 Com Áudio" if src.get("has_audio") else "🔇 Sem Áudio"

                # Consulta transcrição mais recente de forma estática (SQLite)
                if demo_enabled:
                    tr_info = {"status": "COMPLETED", "language": "pt", "model_name": "small", "provider": "faster_whisper", "created_at": "2026-09-18T20:02:00+00:00"}
                else:
                    tr_info = operator_console.get_latest_transcript_op(s_id)

                tr_status = tr_info.get("status") if tr_info else "SEM TRANSCRIÇÃO"
                tr_color = "green" if tr_status == "COMPLETED" else ("yellow" if tr_status == "PROCESSING" else ("red" if tr_status == "FAILED" else "gray"))
                tr_badge = f"<span class='op-badge op-badge-{tr_color}'>{tr_status}</span>"

                with st.container(border=True):
                    c1, c2, c3 = st.columns([0.45, 0.35, 0.2])
                    with c1:
                        st.markdown(f"**{src.get('original_filename')}** &nbsp; {badge_html}", unsafe_allow_html=True)
                        st.caption(f"ID: `{s_id}` | Perfil: `{src.get('profile_id')}` | Criado: `{src.get('created_at', '')[:19]}`")
                        st.markdown(f"Transcrição: {tr_badge}", unsafe_allow_html=True)
                        if tr_info:
                            st.caption(f"Modelo: `{tr_info.get('model_name')}` | Idioma: `{tr_info.get('language')}` | Provedor: `{tr_info.get('provider')}`")
                    with c2:
                        st.markdown(f"⏱️ **{dur_min:.1f} min** ({src.get('duration_seconds', 0):.1f}s) &nbsp;|&nbsp; 📐 **{src.get('width')}x{src.get('height')}** ({src.get('fps', 30):.0f} fps)")
                        st.caption(f"{audio_str} | Origem: `{src.get('source_origin')}` ({'✓ Autorizado' if src.get('authorization_confirmed') else 'Não confirmado'})")
                    with c3:
                        if src.get("status") == "READY":
                            if not tr_info or tr_info.get("status") != "COMPLETED":
                                if st.button("Transcrever", key=f"op_tr_btn_{s_id}", use_container_width=True, disabled=not is_primary or not src.get("has_audio")):
                                    if not demo_enabled:
                                        with st.spinner("Transcrevendo áudio com Whisper local..."):
                                            try:
                                                operator_console.transcribe_clip_source_op(s_id)
                                                st.toast(f"Transcrição de {s_id} concluída!", icon="✓")
                                                st.rerun()
                                            except Exception as tr_err:
                                                st.error(f"Erro na transcrição: {tr_err}")
                                    else:
                                        st.toast("Transcrição simulada no modo demo.", icon="✓")
                            else:
                                if st.button("Descobrir Cortes", key=f"op_disc_btn_{s_id}", type="primary", use_container_width=True, disabled=not is_primary):
                                    if not demo_enabled:
                                        with st.spinner("Calculando cortes heurísticos determinísticos..."):
                                            try:
                                                cands = operator_console.discover_clip_candidates_op(tr_info.get("id"))
                                                st.toast(f"{len(cands)} cortes candidatos descobertos!", icon="✂️")
                                                st.rerun()
                                            except Exception as disc_err:
                                                st.error(f"Erro na descoberta de cortes: {disc_err}")
                                    else:
                                        st.toast("Descoberta simulada no modo demo.", icon="✂️")

                                if st.button("Reprocessar Transcrição", key=f"op_re_tr_btn_{s_id}", use_container_width=True, disabled=not is_primary):
                                    if not demo_enabled:
                                        with st.spinner("Reprocessando transcrição..."):
                                            try:
                                                operator_console.transcribe_clip_source_op(s_id, force=True)
                                                st.toast("Transcrição reprocessada!", icon="🔄")
                                                st.rerun()
                                            except Exception as rtr_err:
                                                st.error(f"Erro ao reprocessar: {rtr_err}")
                                    else:
                                        st.toast("Reprocessamento simulado.", icon="🔄")

                            if st.button("Desativar Fonte", key=f"op_deact_src_{s_id}", use_container_width=True, disabled=not is_primary):
                                if not demo_enabled:
                                    operator_console.deactivate_clip_source_op(s_id)
                                    st.toast(f"Fonte {s_id} desativada.", icon="⏸️")
                                    st.rerun()
                                else:
                                    st.toast("Desativação simulada em modo demo.", icon="⏸️")

    # 2. Import Source
    with tab_import:
        st.markdown("**Importação de Mídia Local Autorizada**")
        st.warning("⚠️ **Aviso de Conformidade Legal:** Importe apenas conteúdo próprio ou explicitamente autorizado para reutilização. Não utilize mídias de terceiros sem autorização comprovada.")

        with st.form(key="op_clip_import_form", clear_on_submit=False):
            file_path_input = st.text_input(
                "Caminho do arquivo local de vídeo (.mp4, .mov, .mkv, .webm):",
                placeholder="Exemplo: D:\\MeusVideos\\gravacao_podcast.mp4",
                help="Informe o caminho absoluto ou relativo para o arquivo existente no disco.",
            )

            p_col1, p_col2 = st.columns(2)
            with p_col1:
                prof_opts = [p["id"] for p in profiles] if profiles else ["default"]
                selected_profile = st.selectbox("Perfil de Destino (Profile):", options=prof_opts, index=0)
            with p_col2:
                origin_opts = ["owned", "licensed", "permission", "public_domain", "other_authorized"]
                selected_origin = st.selectbox(
                    "Origem Legal do Conteúdo:",
                    options=origin_opts,
                    format_func=lambda x: f"{x.upper()} — {clip_mode.SOURCE_ORIGIN_DESCRIPTIONS.get(x, x)}",
                    index=0,
                )

            auth_check = st.checkbox(
                "Declaro sob minha responsabilidade que este conteúdo é de minha autoria ou expressamente autorizado para reutilização.",
                value=False,
            )
            auth_note_input = st.text_input("Nota de Autorização / Referência de Licença (opcional):", placeholder="Ex: Licença comercial número #12345 ou Vídeo gravado pelo operador")

            submit_import = st.form_submit_button(
                "📥 Validar e Importar Vídeo-Fonte",
                disabled=not is_primary,
                help="Apenas a instância PRIMARY pode importar vídeos." if not is_primary else None,
            )

            if submit_import:
                if not file_path_input or not file_path_input.strip():
                    st.error("Por favor, informe o caminho do arquivo de vídeo.")
                elif not auth_check:
                    st.error("A importação exige a confirmação explícita da declaração de autorização.")
                else:
                    if demo_enabled:
                        st.success("Importação simulada com sucesso no modo demonstração.")
                    else:
                        try:
                            res = operator_console.import_clip_source_op(
                                file_path=file_path_input.strip(),
                                source_origin=selected_origin,
                                authorization_confirmed=auth_check,
                                profile_id=selected_profile,
                                authorization_note=auth_note_input.strip() or None,
                            )
                            if res.get("status") == "duplicate":
                                st.warning(f"ℹ️ {res.get('message')} (Source ID: `{res.get('source_id')}`)")
                            else:
                                st.success(f"✓ Vídeo importado com sucesso! (Source ID: `{res.get('source_id')}`)")
                                if res.get("warnings"):
                                    for w in res.get("warnings"):
                                        st.warning(f"Aviso: {w}")
                            st.rerun()
                        except Exception as imp_err:
                            st.error(f"Erro na importação: {imp_err}")

    # 3. Transcripts View
    with tab_transcripts:
        st.markdown("**Visualização Leve de Transcrições**")
        ready_with_tr = []
        for s in sources:
            if demo_enabled:
                ready_with_tr.append((s, {"id": "tr_demo_001", "full_text": "Transcrição simulada de demonstração..."}))
            else:
                tr = operator_console.get_latest_transcript_op(s.get("id"))
                if tr and tr.get("status") == "COMPLETED":
                    ready_with_tr.append((s, tr))

        if not ready_with_tr:
            st.info("ℹ️ Nenhuma transcrição concluída disponível para visualização.")
        else:
            tr_choices = {f"{s.get('original_filename')} ({tr.get('id')})": (s, tr) for s, tr in ready_with_tr}
            sel_label = st.selectbox("Selecione a Transcrição:", options=list(tr_choices.keys()))
            chosen_src, chosen_tr = tr_choices[sel_label]

            with st.expander("📝 Texto Completo (Full Text)", expanded=False):
                st.write(chosen_tr.get("full_text") or "(Sem texto)")

            # Lista primeiros 100 segmentos de forma leve
            if demo_enabled:
                tsegs = [
                    {"sequence": 0, "start_seconds": 0.0, "end_seconds": 15.0, "text": "Você sabia que inteligência artificial pode acelerar sua criação?"},
                    {"sequence": 1, "start_seconds": 15.0, "end_seconds": 38.0, "text": "O segredo é estruturar o conteúdo em tópicos objetivos e manter a narrativa coesa."},
                ]
            else:
                tsegs = operator_console.list_clip_transcript_segments_op(chosen_tr.get("id"), limit=100)

            st.caption(f"Mostrando até 100 segmentos temporais ({len(tsegs)} carregados):")
            for tseg in tsegs:
                st.markdown(
                    f"`[{tseg.get('start_seconds', 0):.1f}s ➔ {tseg.get('end_seconds', 0):.1f}s]` &nbsp; {tseg.get('text', '')}"
                )

    # 4. Segments & Cuts
    with tab_segments:
        st.markdown("**Segmentos e Cortes (Manuais & Descoberta Heurística)**")
        ready_sources = [s for s in sources if s.get("status") == "READY"]

        if not ready_sources:
            st.info("ℹ️ Nenhuma fonte READY disponível para criação de segmentos.")
        else:
            with st.expander("➕ Novo Segmento de Corte Manual", expanded=False):
                with st.form(key="op_clip_create_segment_form"):
                    source_choices = {f"{s.get('original_filename')} ({s.get('id')})": s for s in ready_sources}
                    chosen_label = st.selectbox("Selecione a Fonte de Vídeo:", options=list(source_choices.keys()))
                    chosen_src = source_choices[chosen_label]

                    s_col1, s_col2, s_col3 = st.columns(3)
                    with s_col1:
                        start_in = st.number_input("Início (segundos):", min_value=0.0, value=0.0, step=1.0, format="%.2f")
                    with s_col2:
                        max_dur = float(chosen_src.get("duration_seconds") or 60.0)
                        default_end = min(30.0, max_dur)
                        end_in = st.number_input("Fim (segundos):", min_value=0.1, max_value=max_dur, value=default_end, step=1.0, format="%.2f")
                    with s_col3:
                        seg_title = st.text_input("Título / Rótulo do Segmento (opcional):", placeholder="Ex: Introdução ou Destaque 1")

                    create_seg_btn = st.form_submit_button("✂️ Criar Segmento Manual", disabled=not is_primary)

                    if create_seg_btn:
                        if demo_enabled:
                            st.success("Criação de segmento simulada no modo demonstração.")
                        else:
                            try:
                                s_res = operator_console.create_clip_segment_op(
                                    source_id=chosen_src.get("id"),
                                    start_seconds=start_in,
                                    end_seconds=end_in,
                                    title=seg_title.strip() or None,
                                    selection_method="manual",
                                )
                                st.success(f"✓ Segmento `{s_res.get('segment_id')}` criado com sucesso!")
                                if s_res.get("warnings"):
                                    for w in s_res.get("warnings"):
                                        st.warning(f"Aviso: {w}")
                                st.rerun()
                            except Exception as seg_err:
                                st.error(f"Erro ao criar segmento: {seg_err}")

        # Listagem de Segmentos (Heurísticos e Manuais)
        if not segments:
            st.info("ℹ️ Nenhum segmento cadastrado até o momento.")
        else:
            source_map = {s.get("id"): s for s in sources}
            for seg in segments:
                seg_id = seg.get("id", "")
                s_id = seg.get("source_id", "")
                src = source_map.get(s_id, {})
                dur_s = seg.get("duration_seconds", 0.0)
                curr_st = seg.get("status")
                st_cls = "blue" if curr_st == "CANDIDATE" else ("green" if curr_st == "SELECTED" else "red")
                seg_badge = f"<span class='op-badge op-badge-{st_cls}'>{curr_st}</span>"
                method_badge = "<span class='op-badge op-badge-purple'>🤖 Heurística</span>" if seg.get("selection_method") == "heuristic" else "<span class='op-badge op-badge-gray'>👤 Manual</span>"

                # Consulta de Render mais recente para este segmento (estático SQLite)
                latest_rnd = None
                if not demo_enabled:
                    latest_rnd = operator_console.get_latest_completed_render_op(seg_id)
                rnd_badge = "<span class='op-badge op-badge-green'>🎬 RENDER COMPLETED</span>" if latest_rnd else "<span class='op-badge op-badge-gray'>SEM RENDER</span>"

                with st.container(border=True):
                    sc1, sc2, sc3 = st.columns([0.42, 0.33, 0.25])
                    with sc1:
                        title_str = seg.get("title") or "(Sem título)"
                        st.markdown(f"**{title_str}** &nbsp; {seg_badge} {method_badge} {rnd_badge}", unsafe_allow_html=True)
                        st.caption(f"ID: `{seg_id}` | Fonte: `{s_id}` | Perfil: `{seg.get('profile_id')}`")
                        if seg.get("selection_reason"):
                            st.caption(f"💡 *{seg.get('selection_reason')}*")
                    with sc2:
                        st.markdown(f"⏱️ **{seg.get('start_seconds', 0):.1f}s ➔ {seg.get('end_seconds', 0):.1f}s** (Duração: **{dur_s:.1f}s**)")
                        st.caption(f"Criado: `{seg.get('created_at', '')[:19]}`")
                        if latest_rnd:
                            st.caption(f"Último Render: `{latest_rnd.get('id')}` ({latest_rnd.get('render_strategy')})")
                    with sc3:
                        if curr_st == "CANDIDATE":
                            if st.button("Selecionar", key=f"op_sel_seg_{seg_id}", use_container_width=True, disabled=not is_primary):
                                if not demo_enabled:
                                    operator_console.update_clip_segment_status_op(seg_id, "SELECTED")
                                    st.rerun()
                        elif curr_st == "SELECTED":
                            if is_primary:
                                r_strat = st.selectbox(
                                    "Estratégia 9:16:",
                                    options=["fit_blur", "center_crop"],
                                    format_func=lambda x: "FIT & BLUR (Mais Seguro)" if x == "fit_blur" else "CENTER CROP (Pode Cortar Laterais)",
                                    key=f"strat_sel_{seg_id}",
                                )
                                if r_strat == "center_crop":
                                    st.caption("⚠️ *Center Crop pode cortar laterais.*")

                                btn_label = "Re-renderizar 9:16" if latest_rnd else "Renderizar 9:16"
                                if st.button(f"🎬 {btn_label}", key=f"op_rnd_btn_{seg_id}", use_container_width=True):
                                    if not demo_enabled:
                                        with st.spinner(f"Renderizando segmento em 9:16 ({r_strat})..."):
                                            try:
                                                operator_console.render_clip_segment_op(
                                                    segment_id=seg_id,
                                                    strategy=r_strat,
                                                    force=bool(latest_rnd),
                                                )
                                                st.toast("Vídeo vertical renderizado com sucesso!", icon="🎬")
                                                st.rerun()
                                            except Exception as rnd_err:
                                                st.error(f"Erro na renderização: {rnd_err}")
                                    else:
                                        st.toast("Render simulado no modo demo.", icon="🎬")
                            else:
                                st.button("🎬 Renderizar 9:16", key=f"op_rnd_btn_dis_{seg_id}", use_container_width=True, disabled=True, help="Operação restrita ao nó PRIMÁRIO.")

                            if st.button("Rejeitar", key=f"op_rej_seg_{seg_id}", use_container_width=True, disabled=not is_primary):
                                if not demo_enabled:
                                    operator_console.update_clip_segment_status_op(seg_id, "REJECTED")
                                    st.rerun()
                        elif curr_st == "REJECTED":
                            if st.button("Reativar", key=f"op_reac_seg_{seg_id}", use_container_width=True, disabled=not is_primary):
                                if not demo_enabled:
                                    operator_console.update_clip_segment_status_op(seg_id, "CANDIDATE")
                                    st.rerun()

    # 5. Renders & Review
    with tab_renders:
        st.markdown("**Revisão de Vídeos Verticais Renderizados (9:16 MP4)**")
        selected_segs = [s for s in segments if s.get("status") == "SELECTED"]
        if not selected_segs:
            st.info("ℹ️ Nenhum segmento SELECTED disponível para revisão de renders. Selecione segmentos na aba anterior.")
        else:
            seg_choices = {f"{s.get('title') or s.get('id')} ({s.get('id')})": s for s in selected_segs}
            chosen_seg_lbl = st.selectbox("Selecione o Segmento para Revisão:", options=list(seg_choices.keys()), key="rev_seg_sel")
            chosen_seg = seg_choices[chosen_seg_lbl]
            seg_id_chosen = chosen_seg.get("id")

            if demo_enabled:
                renders_list = [{
                    "id": "rend_demo_001",
                    "segment_id": seg_id_chosen,
                    "source_id": chosen_seg.get("source_id"),
                    "render_strategy": "fit_blur",
                    "width": 1080,
                    "height": 1920,
                    "fps": 30.0,
                    "status": "COMPLETED",
                    "duration_seconds": chosen_seg.get("duration_seconds", 30.0),
                    "file_size_bytes": 15420000,
                    "output_path": "storage/clip_sources/demo/renders/rend_demo_001/clip.mp4",
                    "created_at": "2026-09-18T20:10:00+00:00",
                }]
            else:
                renders_list = operator_console.list_clip_renders_for_segment_op(seg_id_chosen)

            if not renders_list:
                st.info(f"ℹ️ Nenhum render executado para o segmento `{seg_id_chosen}`. Dispare o render na aba 'Segmentos e Cortes'.")
            else:
                for rnd in renders_list:
                    r_id = rnd.get("id", "")
                    r_status = rnd.get("status", "")
                    r_col = "green" if r_status == "COMPLETED" else ("yellow" if r_status == "PROCESSING" else "red")
                    r_badge = f"<span class='op-badge op-badge-{r_col}'>{r_status}</span>"
                    dur_val = rnd.get("duration_seconds") or 0.0
                    size_mb = (rnd.get("file_size_bytes") or 0) / (1024 * 1024)

                    with st.container(border=True):
                        st.markdown(f"**Render `{r_id}`** &nbsp; {r_badge} &nbsp; Estratégia: `{rnd.get('render_strategy')}`", unsafe_allow_html=True)
                        rc1, rc2 = st.columns([0.5, 0.5])
                        with rc1:
                            st.caption(f"Resolução: **{rnd.get('width', 1080)}x{rnd.get('height', 1920)}** (9:16) | FPS: **{rnd.get('fps', 30.0):.1f}**")
                            st.caption(f"Duração: **{dur_val:.1f}s** | Tamanho: **{size_mb:.2f} MB**")
                            st.caption(f"Codecs: Vídeo `{rnd.get('video_codec')}` | Áudio `{rnd.get('audio_codec')}`")
                            st.caption(f"Criado em: `{rnd.get('created_at', '')[:19]}`")
                            out_path = rnd.get("output_path", "")
                            st.caption(f"Arquivo: `{out_path}`")

                            # Warnings contextuais
                            src_for_w = next((s for s in sources if s.get("id") == rnd.get("source_id")), {})
                            warns = operator_console.get_render_warnings_op(src_for_w, rnd.get("render_strategy", "fit_blur"))
                            for w in warns:
                                if w == "NO_AUDIO":
                                    st.warning("⚠️ Fonte sem áudio original (render gerado sem trilha de áudio).")
                                elif w == "LOW_SOURCE_RESOLUTION":
                                    st.warning("⚠️ Resolução da fonte original abaixo de 720p.")
                                elif w == "CENTER_CROP_MAY_CUT_SIDES":
                                    st.info("ℹ️ Render gerado com Center Crop (pode cortar laterais do vídeo original).")

                        with rc2:
                            if r_status == "COMPLETED":
                                if not demo_enabled:
                                    if out_path and os.path.isfile(out_path) and not os.path.islink(out_path) and os.path.getsize(out_path) > 0:
                                        st.video(out_path)
                                    else:
                                        st.warning("⚠️ Arquivo renderizado não encontrado em disco ou inválido.")
                                else:
                                    st.info("🎬 Player de demonstração simulado.")
                            elif r_status == "FAILED":
                                st.error(f"Erro no Render: {rnd.get('error_code')} — {rnd.get('error_message')}")
                            elif r_status == "PROCESSING":
                                st.info("⏳ Renderização em andamento no servidor...")

                        # -----------------------------------------------------------
                        # Fase V11-D: Legendas e Revisão Final
                        # -----------------------------------------------------------
                        if r_status == "COMPLETED":
                            st.markdown("---")
                            st.markdown("##### 🔤 Legendas Sincronizadas (Captions)")

                            if demo_enabled:
                                caption_tracks = []
                            else:
                                caption_tracks = operator_console.list_caption_tracks_for_segment_op(seg_id_chosen)

                            latest_track = caption_tracks[0] if caption_tracks else None

                            cap_col1, cap_col2 = st.columns([0.6, 0.4])
                            with cap_col1:
                                if latest_track:
                                    t_style = latest_track.get("style", "CLEAN")
                                    t_cues_cnt = latest_track.get("cue_count", 0)
                                    t_status = latest_track.get("status", "")
                                    st.caption(f"Faixa: `{latest_track.get('id')}` | Estilo: **{t_style}** | Cues: **{t_cues_cnt}** | Status: `{t_status}`")
                                    if not demo_enabled:
                                        cues = operator_console.get_caption_cues_op(latest_track.get("id"))
                                        if cues:
                                            with st.expander(f"Pré-visualização de Cues ({min(len(cues), 5)} de {len(cues)})", expanded=False):
                                                for c in cues[:5]:
                                                    st.text(f"{c.get('start_seconds', 0):.2f}s ➔ {c.get('end_seconds', 0):.2f}s: {c.get('text')}")
                                else:
                                    st.caption("Nenhuma faixa de legendas gerada para este segmento.")

                            with cap_col2:
                                cap_style_sel = st.selectbox(
                                    "Estilo da Legenda:",
                                    options=["CLEAN", "BOLD"],
                                    format_func=lambda x: "CLEAN (Branco / Contorno Fino)" if x == "CLEAN" else "BOLD (Destaque / Negrito)",
                                    key=f"cap_style_{r_id}",
                                    disabled=not is_primary,
                                )
                                btn_cap_label = "Regerar Legendas" if latest_track else "Gerar Legendas"
                                if st.button(f"🔤 {btn_cap_label}", key=f"btn_cap_{r_id}", use_container_width=True, disabled=not is_primary):
                                    if not demo_enabled:
                                        with st.spinner("Gerando legendas sincronizadas..."):
                                            try:
                                                operator_console.generate_clip_captions_op(
                                                    segment_id=seg_id_chosen,
                                                    style=cap_style_sel,
                                                    force=bool(latest_track),
                                                )
                                                st.toast("Legendas geradas com sucesso!", icon="🔤")
                                                st.rerun()
                                            except Exception as cap_err:
                                                st.error(f"Erro ao gerar legendas: {cap_err}")
                                    else:
                                        st.toast("Geração simulada no modo demo.", icon="🔤")

                            # Revisão Final com Burn-In
                            if latest_track and latest_track.get("status") == "COMPLETED":
                                st.markdown("---")
                                st.markdown("##### ✨ Revisão Final (Final Review Output com Burn-In)")

                                if demo_enabled:
                                    reviews_list = []
                                else:
                                    reviews_list = operator_console.list_clip_reviews_for_segment_op(seg_id_chosen)

                                latest_rev = reviews_list[0] if reviews_list else None

                                if not latest_rev:
                                    st.caption("Nenhum vídeo final com burn-in gerado ainda.")
                                    if st.button("🎬 Gerar Final Review (Burn-in)", key=f"btn_make_rev_{r_id}", use_container_width=True, disabled=not is_primary):
                                        if not demo_enabled:
                                            with st.spinner("Renderizando vídeo vertical com legendas burn-in..."):
                                                try:
                                                    operator_console.create_clip_review_output_op(
                                                        render_id=r_id,
                                                        caption_track_id=latest_track.get("id"),
                                                        force=False,
                                                    )
                                                    st.toast("Review final gerado com sucesso!", icon="✨")
                                                    st.rerun()
                                                except Exception as rev_err:
                                                    st.error(f"Erro no burn-in: {rev_err}")
                                        else:
                                            st.toast("Review simulado no modo demo.", icon="✨")
                                else:
                                    rev_id = latest_rev.get("id", "")
                                    rev_st = latest_rev.get("status", "")
                                    rev_app_st = latest_rev.get("review_status", "PENDING_REVIEW")

                                    rev_col = "green" if rev_app_st == "APPROVED" else ("red" if rev_app_st == "REJECTED" else "yellow")
                                    rev_badge = f"<span class='op-badge op-badge-{rev_col}'>{rev_app_st}</span>"

                                    st.markdown(f"**Artefato `{rev_id}`** &nbsp; Status Render: `{rev_st}` &nbsp; Decisão: {rev_badge}", unsafe_allow_html=True)

                                    rv_c1, rv_c2 = st.columns([0.5, 0.5])
                                    with rv_c1:
                                        st.caption(f"Resolução: **{latest_rev.get('width', 1080)}x{latest_rev.get('height', 1920)}** | Duração: **{latest_rev.get('duration_seconds', 0):.1f}s**")
                                        rev_mb = (latest_rev.get("file_size_bytes") or 0) / (1024 * 1024)
                                        st.caption(f"Tamanho: **{rev_mb:.2f} MB** | Estilo: **{latest_track.get('style', 'CLEAN')}**")
                                        st.caption(f"Arquivo Final: `{latest_rev.get('output_path')}`")

                                        b_col1, b_col2, b_col3 = st.columns(3)
                                        with b_col1:
                                            if st.button("✅ Aprovar", key=f"btn_app_{rev_id}", use_container_width=True, disabled=not is_primary or rev_app_st == "APPROVED"):
                                                if not demo_enabled:
                                                    operator_console.approve_clip_review_op(rev_id)
                                                    st.toast("Artefato aprovado com sucesso!", icon="✅")
                                                    st.rerun()
                                        with b_col2:
                                            if st.button("❌ Rejeitar", key=f"btn_rej_{rev_id}", use_container_width=True, disabled=not is_primary or rev_app_st == "REJECTED"):
                                                if not demo_enabled:
                                                    operator_console.reject_clip_review_op(rev_id)
                                                    st.toast("Artefato rejeitado.", icon="❌")
                                                    st.rerun()
                                        with b_col3:
                                            if st.button("🔄 Regerar", key=f"btn_regen_{rev_id}", use_container_width=True, disabled=not is_primary):
                                                if not demo_enabled:
                                                    with st.spinner("Regerando vídeo final com burn-in..."):
                                                        try:
                                                            operator_console.create_clip_review_output_op(
                                                                render_id=r_id,
                                                                caption_track_id=latest_track.get("id"),
                                                                force=True,
                                                            )
                                                            st.toast("Vídeo final regerado!", icon="🔄")
                                                            st.rerun()
                                                        except Exception as regen_err:
                                                            st.error(f"Erro ao regerar: {regen_err}")

                                    with rv_c2:
                                        rev_out_path = latest_rev.get("output_path", "")
                                        if rev_st == "COMPLETED":
                                            if not demo_enabled:
                                                if rev_out_path and os.path.isfile(rev_out_path) and not os.path.islink(rev_out_path) and os.path.getsize(rev_out_path) > 0:
                                                    st.video(rev_out_path)
                                                else:
                                                    st.warning("⚠️ Arquivo final de review não encontrado em disco.")
                                            else:
                                                st.info("🎬 Player final simulado.")
                                        elif rev_st == "FAILED":
                                            st.error(f"Erro no Burn-in: {latest_rev.get('error_code')} — {latest_rev.get('error_message')}")
                                        elif rev_st == "PROCESSING":
                                            st.info("⏳ Processando burn-in de legendas no servidor...")


    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)



# ---------------------------------------------------------------------------
# Section 6: Alerts, Timeline, Errors & Recovery (STATIC - Sem auto-refresh)
# ---------------------------------------------------------------------------


def _render_tabs_section(demo_enabled: bool, scenario_choice: str, is_primary: bool):
    if demo_enabled:
        d = _get_mock_fixtures(scenario_choice)
        alerts = d.get("alerts", [])
        timeline = d.get("timeline", [])
        errs = d.get("errors", [])
        recoverable = d.get("recoverable", [])
    else:
        stock = operator_console.get_ready_stock()
        provs = operator_console.get_provider_health_summary()
        recent_errs = operator_console.get_recent_errors(limit=10)
        recent_events = operator_console.get_operational_events(limit=20)
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

        alerts = []
        if stock.get("is_below_minimum"):
            alerts.append({
                "severity": "WARNING",
                "title": "Ready Stock abaixo do mínimo operacional",
                "desc": f"Estoque atual de {stock.get('total_ready', 0)} vídeos (meta: {stock.get('minimum_threshold', 3)}).",
                "time_ago": "ativo",
            })
        for prov_name, p_data in provs.items():
            if p_data.get("status") in ("DEGRADED", "UNAVAILABLE"):
                alerts.append({
                    "severity": "WARNING" if p_data.get("status") == "DEGRADED" else "ERROR",
                    "title": f"Provedor {prov_name} com instabilidade ({p_data.get('status')})",
                    "desc": _sanitize_text(p_data.get("last_error") or p_data.get("details", "")),
                    "time_ago": "recente",
                })

        timeline = []
        for ev in recent_events[:15]:
            sev = ev.get("severity", "INFO")
            b_color = "green" if sev == "INFO" else ("yellow" if sev == "WARNING" else "red")
            b_icon = "✓" if sev == "INFO" else ("⚠" if sev == "WARNING" else "✕")
            time_raw = ev.get("timestamp", "")
            t_short = time_raw[11:16] if len(time_raw) >= 16 else time_raw
            timeline.append({
                "time": t_short or "—",
                "badge": b_icon,
                "color": b_color,
                "text": f"{ev.get('component', '')}: {ev.get('message', '')}",
            })

        errs = [
            {
                "time": e.get("timestamp", "")[:19],
                "component": e.get("component", ""),
                "severity": e.get("severity", "ERROR"),
                "task_id": e.get("task_id") or "—",
                "message": _sanitize_text(e.get("message", "")),
            }
            for e in recent_errs
        ]

    tab_alerts, tab_timeline, tab_errors, tab_recovery = st.tabs([
        "⚠️ Alert Center",
        "🕘 Linha do Tempo",
        "🛑 Central de Erros",
        "🧯 Central de Recuperação",
    ])

    # Tab 1: Alert Center
    with tab_alerts:
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


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------

def render_operator_console():
    """Main renderer for V8 Operator Console.

    Modular UX Architecture:
    - Top bar: Visual Demo preferences + discrete 'Atualizar agora' button.
    - Command Header & Telemetry: Auto-refresh 5s (active) or 15s (idle).
    - Live Operations: Auto-refresh 5s (when task is processing) or static (idle).
    - Queues & Stock: Auto-refresh 10s (when items in queue) or 30s (idle).
    - Multi-Profile & Channel Management: STATIC (no background auto-refresh).
    - Provider Health: STATIC (no background auto-refresh; test and manual fetch remain stable).
    - Tabs (Alerts, Timeline, Errors, Recovery): STATIC.
    """
    c_pref, c_refresh = st.columns([0.78, 0.22])
    with c_pref:
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
    with c_refresh:
        st.markdown("<div style='height: 4px;'></div>", unsafe_allow_html=True)
        if st.button("🔄 Atualizar agora", key="op_btn_manual_refresh", use_container_width=True, help="Recarrega todos os dados do Operator Console imediatamente"):
            st.toast("Console operacional atualizado.", icon="🔄")
            st.rerun()

    if demo_enabled:
        st.info(f"🎭 **Modo Demonstração Ativo:** Simulando `{scenario_choice}` (nenhum dado real é modificado).")
        is_primary = (scenario_choice != "Secondary VIEW ONLY")
        has_active_gen = (scenario_choice in ("Factory RUNNING", "Full Showcase (Todos os 7 Estados)"))
        has_active_sched = has_active_gen
        has_active_work = has_active_gen
    else:
        is_primary = operator_console.is_primary_instance()
        try:
            from app.services import webui_task
            has_active_gen = webui_task.has_active_generation_tasks()
        except Exception:
            has_active_gen = False
        try:
            from app.services import scheduler
            exec_st = scheduler.get_executor_status()
            has_active_sched = (exec_st.get("state") == "processing")
        except Exception:
            has_active_sched = False
        has_active_work = has_active_gen or has_active_sched

    # 1 & 2. Command Header & Telemetry Cards (5s active / 15s idle)
    if has_active_work:
        _render_command_header_and_telemetry_active(demo_enabled, scenario_choice, is_primary)
    else:
        _render_command_header_and_telemetry_idle(demo_enabled, scenario_choice, is_primary)

    # 3. Live Operations (5s when active / static when idle)
    if has_active_gen:
        _render_live_operations_active(demo_enabled, scenario_choice, is_primary)
    else:
        _render_live_operations_idle(demo_enabled, scenario_choice, is_primary)

    # 4. Queues & Ready Stock (10s active / 30s idle)
    if has_active_work:
        _render_queues_active(demo_enabled, scenario_choice, is_primary)
    else:
        _render_queues_idle(demo_enabled, scenario_choice, is_primary)

    # 4.5 Multi-Profile & Channel Management (STATIC)
    _render_profile_management_section(demo_enabled, scenario_choice, is_primary)

    # 5. Provider Health (STATIC)
    _render_provider_health_section(demo_enabled, scenario_choice, is_primary)

    # 5.5. Automatic Analytics Scheduler (STATIC)
    _render_automatic_analytics_section(demo_enabled, scenario_choice, is_primary)

    # 5.55. Autonomous Production Loop (STATIC - Fase V12-E)
    _render_autonomous_production_section(demo_enabled, scenario_choice, is_primary)

    # 5.6. Clip Mode Foundation (STATIC)
    _render_clip_mode_section(demo_enabled, scenario_choice, is_primary)

    # 6. Alerts, Timeline, Errors & Recovery Tabs (STATIC)
    _render_tabs_section(demo_enabled, scenario_choice, is_primary)
