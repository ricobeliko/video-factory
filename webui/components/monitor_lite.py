"""
webui/components/monitor_lite.py
================================
Componente visual de apresentação do Monitor Lite (Fase V15).

PRINCÍPIOS DE DESIGN & UX:
- Compreensão em ~10 segundos da saúde e operação da Video Factory.
- Estritamente somente leitura (READ-ONLY): zero botões de mutação ou controle.
- Clareza absoluta: cards visuais, badges coloridos, barras de progresso limpas.
- Cores semânticas rigorosas: verde para saudável, amarelo para estoque baixo,
  cinza para sem dados / neutro, vermelho para falha.
- Indicador explícito de ambiente (DEV vs PRODUÇÃO).
- Atualização passiva a cada 30s via st.fragment.
- Sem poluição técnica na tela principal: JSON e diagnósticos em expander colapsado.
- Fail-soft total: dados ausentes exibem 'Sem dados' ou '—' sem quebrar o layout.
"""

from __future__ import annotations

import streamlit as st
from typing import Any, Dict, Optional

from app.services.monitor_lite import get_monitor_lite_summary


def _render_channel_card(ch: Dict[str, Any]):
    """Renderiza um card visual individual de canal."""
    with st.container(border=True):
        st.markdown(f"**{ch.get('status_badge', '⚪')} {ch.get('name', 'Canal')}**")

        stock_cnt = ch.get("ready_stock", 0)
        stock_tgt = ch.get("target_stock", 3)
        stock_st = ch.get("stock_status", "UNKNOWN")
        stock_lbl = ch.get("stock_label", "—")

        # Semântica visual estrita de estoque (sem backticks verdes enganosos)
        if stock_st == "UNKNOWN" or "Sem dados" in str(stock_lbl):
            stock_html = f'<span style="color: #888888; font-weight: 600;">{stock_lbl}</span>'
        elif stock_st == "LOW" or stock_cnt < stock_tgt:
            stock_html = f'<span style="color: #eab308; font-weight: 600;">⚠️ {stock_lbl}</span>'
        else:
            stock_html = f'<span style="color: #22c55e; font-weight: 600;">✅ {stock_lbl}</span>'

        st.markdown(f"📦 **Estoque Pronto:** {stock_html}", unsafe_allow_html=True)

        last_pub = ch.get("last_published", {})
        st.markdown(f"🚀 **Última Publicação:** {last_pub.get('title', '—')}")

        # Semântica visual estrita de próximo slot (neutro quando não agendado)
        next_sl = ch.get("next_slot", {})
        time_until = next_sl.get("time_until", "—")
        if not next_sl.get("scheduled_at") or "Nenhum" in str(time_until):
            slot_html = f'<span style="color: #888888;">{time_until}</span>'
        else:
            slot_html = f'<span style="color: #22c55e; font-weight: 500;">{time_until}</span>'

        st.markdown(f"⏰ **Próximo Slot:** {slot_html}", unsafe_allow_html=True)


def _render_monitor_lite_content(db_path: Optional[str] = None):
    """Renderiza o conteúdo visual completo do painel executivo do Monitor Lite."""
    try:
        data = get_monitor_lite_summary(db_path=db_path)
    except Exception as exc:
        st.error(f"Erro ao carregar dados do Monitor Lite: {exc}")
        return

    sys_info = data.get("system", {})
    today = data.get("today", {})
    current_prod = data.get("current_production", {})
    channels = data.get("channels", [])
    local_ai = data.get("local_ai", {})
    learning = data.get("learning", {})
    alerts = data.get("alerts", [])
    recent_tasks = data.get("recent_tasks", [])

    # -------------------------------------------------------------------------
    # 1. HEADER: Sistema, Ambiente & Status Geral
    # -------------------------------------------------------------------------
    col_title, col_status = st.columns([0.7, 0.3], vertical_alignment="center")
    with col_title:
        env_name = str(sys_info.get("environment") or "DESCONHECIDO").upper()
        if "PROD" in env_name:
            env_color = "#3b82f6"
            env_bg = "rgba(59, 130, 246, 0.15)"
            env_border = "rgba(59, 130, 246, 0.4)"
        elif "DEV" in env_name:
            env_color = "#eab308"
            env_bg = "rgba(234, 179, 8, 0.15)"
            env_border = "rgba(234, 179, 8, 0.4)"
        else:
            env_color = "#9ca3af"
            env_bg = "rgba(156, 163, 175, 0.15)"
            env_border = "rgba(156, 163, 175, 0.4)"

        st.markdown(
            f"""
            <div style="display: flex; align-items: center; gap: 10px;">
                <span style="font-size: 1.5rem; font-weight: 700;">🏭 VIDEO FACTORY</span>
                <span style="font-size: 0.78rem; font-weight: 700; padding: 3px 9px; border-radius: 6px; color: {env_color}; background: {env_bg}; border: 1px solid {env_border}; letter-spacing: 0.5px;">
                    {env_name}
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        refresh_text = "Atualizado a cada 30s" if hasattr(st, "fragment") else "Atualizado ao recarregar"
        st.caption(f"{sys_info.get('role_label', 'Instância Primária')} &nbsp;•&nbsp; {refresh_text}")

    with col_status:
        st.markdown(
            f"""
            <div style="text-align: right; padding: 4px;">
                <span style="font-size: 1.15rem; font-weight: 700; padding: 6px 14px; border-radius: 20px; background: rgba(34, 197, 94, 0.15); border: 1px solid rgba(34, 197, 94, 0.4);">
                    {sys_info.get('badge', '🟢 ONLINE')}
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height: 4px;'></div>", unsafe_allow_html=True)

    # -------------------------------------------------------------------------
    # 2. HOJE: 4 Métricas Visuais em Destaque
    # -------------------------------------------------------------------------
    st.markdown("##### 📅 Hoje")
    kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)

    with kpi_col1:
        st.metric(
            label="🎬 Produzidos (24h)",
            value=today.get("produced_count", 0),
            help="Vídeos gerados e aprovados nas últimas 24 horas em todos os canais.",
        )
    with kpi_col2:
        st.metric(
            label="🚀 Publicados",
            value=today.get("published_count", 0),
            help="Vídeos publicados hoje no YouTube.",
        )
    with kpi_col3:
        st.metric(
            label="⏳ Fila Agendada",
            value=today.get("queue_count", 0),
            help="Posts agendados no scheduler aguardando horário de publicação.",
        )
    with kpi_col4:
        alert_cnt = today.get("alerts_count", 0)
        st.metric(
            label="⚠️ Alertas Ativos",
            value=alert_cnt,
            delta="Atenção" if alert_cnt > 0 else None,
            delta_color="inverse" if alert_cnt > 0 else "normal",
            help="Alertas operacionais acionáveis que requerem acompanhamento.",
        )

    st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

    # -------------------------------------------------------------------------
    # 3. PRODUÇÃO ATUAL: Status Visual & Progresso
    # -------------------------------------------------------------------------
    st.markdown("##### ⚙️ Produção Atual")
    with st.container(border=True):
        if current_prod.get("is_active"):
            st.markdown(f"**Tema:** {current_prod.get('topic', '—')}")
            st.caption(f"**Canal:** {current_prod.get('profile_name', '—')} &nbsp;|&nbsp; **Etapa:** {current_prod.get('stage', '—')}")
            prog = current_prod.get("progress_percent", 50)
            st.progress(prog / 100.0, text=f"{current_prod.get('status_label')} ({prog}%)")
        else:
            st.markdown(
                """
                <div style="padding: 12px; text-align: center; border-radius: 8px; background: rgba(128, 128, 128, 0.08); font-size: 0.95rem; color: #888888;">
                    ⚪ <b>Ocioso</b> &nbsp;•&nbsp; Nenhuma geração ativa no momento. Fábrica pronta para o próximo ciclo autônomo.
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

    # -------------------------------------------------------------------------
    # 4. CANAIS: Visão Operacional com Grid Dinâmico (2 colunas por linha)
    # -------------------------------------------------------------------------
    st.markdown("##### 📺 Canais Operacionais")
    if not channels:
        st.info("Nenhum canal ativo cadastrado.", icon="ℹ️")
    elif len(channels) == 1:
        cols = st.columns(1)
        with cols[0]:
            _render_channel_card(channels[0])
    else:
        for i in range(0, len(channels), 2):
            cols = st.columns(2)
            with cols[0]:
                _render_channel_card(channels[i])
            if i + 1 < len(channels):
                with cols[1]:
                    _render_channel_card(channels[i + 1])

    st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

    # -------------------------------------------------------------------------
    # 5 & 6. LOCAL AI & APRENDIZADO
    # -------------------------------------------------------------------------
    sec_col1, sec_col2 = st.columns(2)

    with sec_col1:
        st.markdown("##### 🧠 Local AI (Local Brain)")
        with st.container(border=True):
            lr = local_ai.get("last_run", {})
            st.markdown(f"**Modelo:** {local_ai.get('model')} &nbsp;|&nbsp; **Modo:** {local_ai.get('configured_mode')}")
            st.markdown(f"**Servidor (8089):** {local_ai.get('server_badge')}")
            st.divider()
            st.markdown(f"**Último Shadow:** **{lr.get('status_badge')}**")
            st.caption(f"**FactGuard:** {lr.get('fact_guard_status')} &nbsp;•&nbsp; **Latência:** {lr.get('latency_seconds')}s &nbsp;•&nbsp; **Calls:** {lr.get('total_calls')}")
            st.caption(f"**Duração:** {lr.get('duration_text')} &nbsp;•&nbsp; **Palavras:** {lr.get('words_text')}")
            if lr.get("description"):
                st.info(lr.get("description"), icon="ℹ️")

    with sec_col2:
        st.markdown("##### 📈 Aprendizado & Feedback")
        with st.container(border=True):
            an = learning.get("analytics_auto", {})
            cl = learning.get("closed_loop", {})
            st.markdown(f"**Analytics Auto:** {an.get('badge')}")
            st.caption(f"Snapshots hoje: {an.get('snapshots_today')} &nbsp;•&nbsp; Último ciclo: {an.get('last_cycle')}")
            st.divider()
            st.markdown(f"**Closed Feedback Loop:** {cl.get('badge')}")
            st.caption(f"Modo: {cl.get('mode')} &nbsp;•&nbsp; Amostras: {cl.get('sample_count')} ({cl.get('evidence_state')})")
            st.caption(f"Isolamento: {cl.get('isolation')}")

    st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

    # -------------------------------------------------------------------------
    # 7. ALERTAS ACIONÁVEIS
    # -------------------------------------------------------------------------
    st.markdown("##### 🚨 Alertas Operacionais")
    if alerts:
        for a in alerts:
            sev = a.get("severity")
            msg = a.get("message")
            if sev == "CRITICAL":
                st.error(msg, icon="🚫")
            elif sev == "WARNING":
                st.warning(msg, icon="⚠️")
            else:
                st.info(msg, icon="ℹ️")
    else:
        st.success("✅ Nenhum alerta pendente. A fábrica de vídeos está saudável e operando normalmente.", icon="✅")

    st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

    # -------------------------------------------------------------------------
    # 8. ÚLTIMAS TAREFAS
    # -------------------------------------------------------------------------
    st.markdown("##### 📋 Últimas Tarefas")
    with st.container(border=True):
        if recent_tasks:
            for t in recent_tasks:
                c1, c2, c3 = st.columns([0.15, 0.60, 0.25])
                with c1:
                    st.markdown(f"**{t.get('status_icon')} {t.get('status_text')}**")
                with c2:
                    st.write(f"**{t.get('topic')}**")
                with c3:
                    st.caption(f"{t.get('channel')} (#{t.get('task_id')})")
        else:
            st.caption("Nenhuma tarefa recente encontrada.")

    # -------------------------------------------------------------------------
    # 9. DETALHES TÉCNICOS (COLAPSADO POR PADRÃO)
    # -------------------------------------------------------------------------
    with st.expander("🔍 Detalhes Técnicos & Diagnósticos (Avançado)", expanded=False):
        st.caption("Dados brutos passivos coletados pelo serviço de observabilidade:")
        st.json(data.get("raw_observability", {}))


# Wrapper com st.fragment para atualização passiva a cada 30 segundos
if hasattr(st, "fragment"):
    @st.fragment(run_every="30s")
    def _render_fragment_wrapper(db_path: Optional[str] = None):
        _render_monitor_lite_content(db_path=db_path)
else:
    _render_fragment_wrapper = None


def render_monitor_lite(db_path: Optional[str] = None):
    """
    Ponto de entrada do Monitor Lite no Streamlit.
    Utiliza st.fragment(run_every='30s') para recarregar o snapshot passivamente
    sem recarregar o restante da aplicação ou disparar qualquer mutação.
    """
    try:
        from streamlit.runtime.scriptrunner_utils.script_run_context import get_script_run_ctx
        ctx = get_script_run_ctx()
    except Exception:
        ctx = None

    if ctx is not None and _render_fragment_wrapper is not None:
        _render_fragment_wrapper(db_path=db_path)
    else:
        _render_monitor_lite_content(db_path=db_path)
