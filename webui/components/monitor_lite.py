"""
webui/components/monitor_lite.py
================================
Componente visual de apresentação do Monitor Lite (Fase V15).

PRINCÍPIOS DE DESIGN & UX:
- Compreensão em ~10 segundos da saúde e operação da Video Factory.
- Estritamente somente leitura (READ-ONLY): zero botões de mutação ou controle.
- Clareza absoluta: cards visuais, badges coloridos, barras de progresso limpas.
- Sem poluição técnica na tela principal: JSON, hashes e paths isolados em "Detalhes Técnicos".
- Fail-soft total: dados ausentes exibem 'Sem dados' ou '—' sem quebrar o layout.
"""

from __future__ import annotations

import streamlit as st
from typing import Any, Dict, Optional

from app.services.monitor_lite import get_monitor_lite_summary


def render_monitor_lite(db_path: Optional[str] = None):
    """Renderiza o painel executivo do Monitor Lite no Streamlit."""
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
    # 1. HEADER: Sistema & Status Geral
    # -------------------------------------------------------------------------
    col_title, col_status = st.columns([0.7, 0.3], vertical_alignment="center")
    with col_title:
        st.markdown("### 🏭 VIDEO FACTORY")
        st.caption(f"{sys_info.get('role_label', 'Instância Primária')} &nbsp;•&nbsp; Atualizado em tempo real")
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
            st.caption(f"**Canal:** {current_prod.get('profile_name', '—')} &nbsp;|&nbsp; **Etapa:** `{current_prod.get('stage', '—')}`")
            prog = current_prod.get("progress_percent", 50)
            st.progress(prog / 100.0, text=f"{current_prod.get('status_label')} ({prog}%)")
        else:
            st.markdown(
                """
                <div style="padding: 12px; text-align: center; border-radius: 8px; background: rgba(128, 128, 128, 0.08); font-size: 0.95rem;">
                    ⚪ <b>Ocioso</b> &nbsp;•&nbsp; Nenhuma geração ativa no momento. Fábrica pronta para o próximo ciclo autônomo.
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

    # -------------------------------------------------------------------------
    # 4. CANAIS: Visão Operacional Lado a Lado
    # -------------------------------------------------------------------------
    st.markdown("##### 📺 Canais Operacionais")
    c_col1, c_col2 = st.columns(2)

    for i, ch in enumerate(channels):
        target_col = c_col1 if i == 0 else c_col2
        with target_col:
            with st.container(border=True):
                st.markdown(f"**{ch.get('status_badge')} {ch.get('name')}**")
                st.write(f"📦 **Estoque Pronto:** `{ch.get('stock_label')}`")
                last_pub = ch.get("last_published", {})
                st.write(f"🚀 **Última Publicação:** {last_pub.get('title', '—')}")
                next_sl = ch.get("next_slot", {})
                st.write(f"⏰ **Próximo Slot:** `{next_sl.get('time_until', '—')}`")

    st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

    # -------------------------------------------------------------------------
    # 5 & 6. LOCAL AI & APRENDIZADO
    # -------------------------------------------------------------------------
    sec_col1, sec_col2 = st.columns(2)

    with sec_col1:
        st.markdown("##### 🧠 Local AI (Local Brain)")
        with st.container(border=True):
            lr = local_ai.get("last_run", {})
            st.markdown(f"**Modelo:** `{local_ai.get('model')}` &nbsp;|&nbsp; **Modo:** `{local_ai.get('configured_mode')}`")
            st.markdown(f"**Servidor (8089):** {local_ai.get('server_badge')}")
            st.divider()
            st.markdown(f"**Último Shadow:** `{lr.get('status_badge')}`")
            st.caption(f"**FactGuard:** `{lr.get('fact_guard_status')}` &nbsp;|&nbsp; **Latência:** {lr.get('latency_seconds')}s &nbsp;|&nbsp; **Calls:** {lr.get('total_calls')}")
            st.caption(f"**Duração:** {lr.get('duration_text')} &nbsp;|&nbsp; **Palavras:** {lr.get('words_text')}")
            if lr.get("description"):
                st.info(lr.get("description"), icon="ℹ️")

    with sec_col2:
        st.markdown("##### 📈 Aprendizado & Feedback")
        with st.container(border=True):
            an = learning.get("analytics_auto", {})
            cl = learning.get("closed_loop", {})
            st.markdown(f"**Analytics Auto:** {an.get('badge')}")
            st.caption(f"Snapshots hoje: {an.get('snapshots_today')} &nbsp;|&nbsp; Último ciclo: {an.get('last_cycle')}")
            st.divider()
            st.markdown(f"**Closed Feedback Loop:** {cl.get('badge')}")
            st.caption(f"Modo: `{cl.get('mode')}` &nbsp;|&nbsp; Amostras: {cl.get('sample_count')} (`{cl.get('evidence_state')}`)")
            st.caption(f"Isolamento: `{cl.get('isolation')}`")

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
                    st.caption(f"`{t.get('channel')}` (`{t.get('task_id')}`)")
        else:
            st.caption("Nenhuma tarefa recente encontrada.")

    # -------------------------------------------------------------------------
    # 9. DETALHES TÉCNICOS (COLAPSADO POR PADRÃO)
    # -------------------------------------------------------------------------
    with st.expander("🔍 Detalhes Técnicos & Diagnósticos (Avançado)", expanded=False):
        st.caption("Dados brutos passivos coletados pelo serviço de observabilidade:")
        st.json(data.get("raw_observability", {}))
