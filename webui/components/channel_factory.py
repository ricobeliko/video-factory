"""
Channel Factory UI Component (Fase V1.5E-B — Generic Channel Onboarding).

Apresenta a experiência de Channel Factory:
- Visão geral de canais/workspaces em cards
- CTA '+ Novo Canal' com onboarding em 4 blocos (Identidade, Publicação, Produção, Ativação)
- Default seguro: produção autônoma sempre nasce pausada até ação explícita do operador
- Gerenciamento e edição de configurações de canais existentes
"""
from typing import Any, Dict, List, Optional
import streamlit as st

from app.config import config
from app.services import autonomous_production, operator_console, post_for_me, profile_manager


def _get_channel_card_data(p: Dict[str, Any], db_path: Optional[str] = None) -> Dict[str, Any]:
    """Coleta informações operacionais consolidadas para o card do canal."""
    pid = p.get("id", "")
    settings = profile_manager.get_profile_settings(pid, db_path=db_path)
    channels = profile_manager.list_channels(profile_id=pid, db_path=db_path)
    yt_channel = next((c for c in channels if c.get("platform") == "youtube"), None)

    is_auto_enabled = autonomous_production.is_profile_autonomous_mode_enabled(pid, db_path=db_path)
    target_stock = autonomous_production.get_target_ready_stock(pid, db_path=db_path)
    try:
        raw_ready = operator_console.get_canonical_ready_stock(profile_id=pid, db_path=db_path)
        if isinstance(raw_ready, dict):
            ready_stock = int(raw_ready.get("total_ready", 0))
        else:
            ready_stock = int(raw_ready or 0)
    except Exception:
        ready_stock = 0

    return {
        "profile": p,
        "settings": settings,
        "yt_channel": yt_channel,
        "autonomous_enabled": is_auto_enabled,
        "target_stock": target_stock,
        "ready_stock": ready_stock,
    }


def _render_onboarding_form(is_primary: bool, db_path: Optional[str] = None):
    """Renderiza os 4 blocos do formulário de criação de novo canal com st.form e fail-closed accounts."""
    st.markdown("#### 🚀 Configurar Novo Canal")
    st.caption("Cadastre um novo canal editorial sem necessidade de alterações no código.")

    if "cf_connected_accounts" not in st.session_state:
        try:
            st.session_state["cf_connected_accounts"] = post_for_me.list_connected_publishing_accounts(platform="youtube")
        except Exception:
            st.session_state["cf_connected_accounts"] = []

    accounts = st.session_state.get("cf_connected_accounts", [])

    if not accounts:
        st.warning("⚠️ Nenhuma conta YouTube conectada encontrada no Post for Me. Conecte uma conta antes de cadastrar um canal operacional.")

    with st.form("new_channel_onboarding_form"):
        # 1. Identidade
        st.markdown("##### 1. Identidade do Canal")
        c_name, c_niche = st.columns(2)
        with c_name:
            name_val = st.text_input("Nome do Canal *", placeholder="Ex: GTA Daily DEV", key="cf_new_ch_name")
        with c_niche:
            niche_val = st.text_input("Nicho *", placeholder="Ex: games", key="cf_new_ch_niche")

        c_topic, c_lang = st.columns([2, 1])
        with c_topic:
            topic_brief_val = st.text_area(
                "Tema / Descrição Editorial *",
                placeholder="Ex: GTA VI: novidades, notícias oficiais, análises e teorias",
                key="cf_new_ch_topic",
                height=68,
            )
        with c_lang:
            lang_val = st.selectbox("Idioma", options=["pt-BR"], index=0, key="cf_new_ch_lang", disabled=True)

        # 2. Publicação (Post for Me / YouTube) - Fail-Closed
        st.markdown("##### 2. Publicação e Destino")
        st.caption("MVP: YouTube via Post for Me (conta conectada obrigatória)")

        ext_account_id = None
        if accounts:
            acc_labels = [f"{acc['display_name']} ({acc['external_account_id']})" for acc in accounts]
            sel_idx = st.selectbox(
                "Conta YouTube Conectada *",
                options=range(len(accounts)),
                format_func=lambda i: acc_labels[i],
                key="cf_new_ch_yt_acc_sel",
            )
            ext_account_id = accounts[sel_idx]["external_account_id"]
        else:
            st.error("Nenhuma conta YouTube disponível. Conexão obrigatória no Post for Me para habilitar o destino.")

        # 3. Produção & Visual
        st.markdown("##### 3. Produção & Visual")
        global_voice = config.ui.get("voice_name") or config.app.get("voice_name") or "en-US-BrianMultilingualNeural"
        c_voice, c_stock = st.columns(2)
        with c_voice:
            st.text_input("Voz Global da Fábrica", value=f"Global: {global_voice}", key="cf_new_ch_voice", disabled=True)
        with c_stock:
            stock_target = st.number_input("Meta de Estoque de Vídeos", min_value=1, max_value=10, value=3, key="cf_new_ch_stock")

        st.caption("ℹ️ Visual Director e Google Flow integrados ao pipeline.")
        c_vd, c_flow, c_fallback = st.columns(3)
        with c_vd:
            vd_enabled = st.checkbox("Visual Director Ativo", value=True, key="cf_new_ch_vd")
        with c_flow:
            flow_enabled = st.checkbox("Google Flow Ativo", value=True, key="cf_new_ch_flow")
        with c_fallback:
            fallback_enabled = st.checkbox("Stock Fallback Ativo", value=True, key="cf_new_ch_fallback")

        flow_scenes = profile_manager.DEFAULT_FLOW_PREMIUM_SCENES_PER_SHORT
        if flow_enabled:
            flow_scenes = st.slider("Cenas Flow por Vídeo", min_value=1, max_value=10, value=profile_manager.DEFAULT_FLOW_PREMIUM_SCENES_PER_SHORT, key="cf_new_ch_scenes")

        # 3.1 Som Ambiente (Fase V1.5E-G8)
        st.markdown("##### 🎵 Som Ambiente")
        music_enabled = st.checkbox("Ativar som ambiente", value=False, key="cf_new_ch_music_enabled")
        c_music_mode, c_music_vol, c_music_mood = st.columns(3)
        with c_music_mode:
            st.selectbox("Modo", options=["Auto pelo roteiro"], index=0, key="cf_new_ch_music_mode", disabled=True)
        with c_music_vol:
            music_vol_options = [0.05, 0.08, 0.10, 0.12, 0.15, 0.20]
            music_vol_labels = ["5%", "8%", "10%", "12%", "15%", "20%"]
            sel_vol_idx = st.selectbox(
                "Volume",
                options=range(len(music_vol_options)),
                format_func=lambda i: music_vol_labels[i],
                index=5,
                key="cf_new_ch_music_vol",
            )
            music_volume = music_vol_options[sel_vol_idx]
        with c_music_mood:
            music_mood_options = ["Neutral", "Suspense", "Terror", "Futuristic", "Epic", "Energetic", "Emotional"]
            music_default_mood = st.selectbox(
                "Mood padrão",
                options=music_mood_options,
                index=0,
                key="cf_new_ch_music_mood",
            ).lower()

        # 4. Ativação (Default Seguro: Pausado)
        st.markdown("##### 4. Ativação")
        st.warning("⚠️ **Recomendado:** Deixar a produção autônoma pausada inicialmente para validação do canal antes da ativação contínua.")
        autonomous_start = st.checkbox("Ativar produção automática imediatamente", value=False, key="cf_new_ch_auto_start")

        st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

        submitted = st.form_submit_button("🚀 Criar Canal", type="primary", use_container_width=True)

        if submitted:
            if not is_primary:
                st.error("Apenas o nó PRIMARY pode cadastrar canais.")
                return

            if not accounts or not ext_account_id:
                st.error("Onboarding fail-closed: uma conta YouTube conectada é obrigatória para criar o canal.")
                return

            clean_name = str(name_val or "").strip()
            clean_niche = str(niche_val or "").strip()
            clean_topic = str(topic_brief_val or "").strip()

            if not clean_name:
                st.error("Informe o Nome do Canal.")
                return
            if not clean_niche:
                st.error("Informe o Nicho.")
                return
            if not clean_topic:
                st.error("Informe o Tema / Linha Editorial.")
                return
            if not ext_account_id or not ext_account_id.startswith("UC"):
                st.error(f"O YouTube Channel ID deve iniciar com 'UC' (recebido: '{ext_account_id}').")
                return

            settings_obj = profile_manager.ChannelWorkspaceSettings()
            settings_obj.editorial.topic_brief = clean_topic
            settings_obj.voice.voice_name = global_voice
            settings_obj.visual.visual_director_enabled = bool(vd_enabled)
            settings_obj.visual.flow_enabled = bool(flow_enabled)
            settings_obj.visual.flow_scene_count = int(flow_scenes)
            settings_obj.visual.stock_fallback_enabled = bool(fallback_enabled)
            settings_obj.automation.autonomous_enabled = bool(autonomous_start)
            settings_obj.automation.target_ready_stock = int(stock_target)
            settings_obj.music.enabled = bool(music_enabled)
            settings_obj.music.mode = "auto"
            settings_obj.music.volume = float(music_volume)
            settings_obj.music.default_mood = str(music_default_mood).lower()

            try:
                res = profile_manager.onboard_channel_workspace(
                    name=clean_name,
                    niche=clean_niche,
                    topic_brief=clean_topic,
                    language="pt-BR",
                    external_account_id=ext_account_id,
                    settings=settings_obj,
                    autonomous_enabled=autonomous_start,
                    db_path=db_path,
                )
                new_p = res.get("profile", {})
                st.session_state["channel_factory_feedback"] = {
                    "type": "success",
                    "message": f"Canal '{new_p.get('name')}' criado com sucesso! Status inicial: {'Produção Ativa' if autonomous_start else 'Pausado (Recomendado)'}.",
                    "profile_id": new_p.get("id"),
                }
                st.rerun()
            except Exception as exc:
                st.error(f"Falha ao cadastrar canal: {exc}")


if hasattr(st, "dialog"):
    @st.dialog("➕ Cadastrar Novo Canal", width="large")
    def _open_new_channel_dialog(is_primary: bool, db_path: Optional[str] = None):
        _render_onboarding_form(is_primary=is_primary, db_path=db_path)
else:
    def _open_new_channel_dialog(is_primary: bool, db_path: Optional[str] = None):
        with st.expander("➕ Cadastrar Novo Canal", expanded=True):
            _render_onboarding_form(is_primary=is_primary, db_path=db_path)


def render_channel_factory(is_primary: Optional[bool] = None, db_path: Optional[str] = None):
    """Renderiza a experiência completa de Channel Factory."""
    if is_primary is None:
        try:
            is_primary = operator_console.is_primary_instance(db_path=db_path)
        except Exception:
            is_primary = True

    feedback = st.session_state.pop("channel_factory_feedback", None)
    if feedback:
        if feedback["type"] == "success":
            st.success(feedback["message"])
            if feedback.get("profile_id"):
                p_id = feedback["profile_id"]
                if not autonomous_production.is_profile_autonomous_mode_enabled(p_id, db_path=db_path):
                    if st.button("▶️ Ativar Produção Deste Canal Agora", key=f"activate_new_{p_id}"):
                        autonomous_production.set_profile_autonomous_mode_enabled(p_id, True, db_path=db_path)
                        st.success("Produção ativada com sucesso!")
                        st.rerun()
        else:
            st.error(feedback["message"])

    # Header & CTA
    col_title, col_cta = st.columns([0.7, 0.3])
    with col_title:
        st.markdown("### 📺 Canais")
        st.caption("Channel Factory — Cadastre e gerencie canais autônomos sem alterar código Python.")
    with col_cta:
        st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
        if st.button(
            "➕ Novo Canal",
            type="primary",
            use_container_width=True,
            disabled=not is_primary,
            help="Cadastra um novo canal editorial." if is_primary else "Disponível apenas no nó PRIMARY.",
            key="cf_open_onboard_modal_btn",
        ):
            _open_new_channel_dialog(is_primary=is_primary, db_path=db_path)

    # Lista de Canais Existentes
    profiles = profile_manager.list_profiles(db_path=db_path)
    if not profiles:
        st.info("Nenhum canal cadastrado no momento. Clique em '+ Novo Canal' para começar.")
        return

    for prof in profiles:
        card = _get_channel_card_data(prof, db_path=db_path)
        p = card["profile"]
        settings = card["settings"]
        yt = card["yt_channel"]
        is_auto = card["autonomous_enabled"]
        p_id = p.get("id", "")

        with st.container(border=True):
            col_id, col_ops, col_actions = st.columns([0.45, 0.35, 0.20])

            with col_id:
                st.markdown(f"#### {p.get('name')}")
                st.markdown(f"🏷️ **Nicho:** `{p.get('niche') or 'Geral'}` | 🌐 **Idioma:** `{p.get('language') or 'pt-BR'}`")
                brief = settings.editorial.topic_brief or "Sem descrição editorial configurada."
                st.caption(f"📝 {brief[:120]}{'...' if len(brief) > 120 else ''}")

            with col_ops:
                dest_label = "Não configurado"
                if yt:
                    acc_display = yt.get("external_account_id") or yt.get("display_name") or "Conectado"
                    dest_label = f"YouTube ({acc_display})"
                st.markdown(f"📡 **Destino:** `{dest_label}`")

                auto_badge = "🟢 Produção ON" if is_auto else "⏸️ Produção PAUSADA"
                st.markdown(f"⚙️ **Status:** **{auto_badge}**")
                ready_val = card["ready_stock"].get("total_ready", 0) if isinstance(card.get("ready_stock"), dict) else (card.get("ready_stock") or 0)
                st.caption(f"📦 Estoque: **{ready_val}** / Meta: **{card['target_stock']}** vídeos")

            with col_actions:
                st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
                if is_auto:
                    if st.button("⏸️ Pausar", key=f"pause_prof_{p_id}", use_container_width=True, disabled=not is_primary):
                        autonomous_production.set_profile_autonomous_mode_enabled(p_id, False, db_path=db_path)
                        st.toast(f"Produção de '{p.get('name')}' pausada.")
                        st.rerun()
                else:
                    if st.button("▶️ Ativar", type="secondary", key=f"activate_prof_{p_id}", use_container_width=True, disabled=not is_primary):
                        autonomous_production.set_profile_autonomous_mode_enabled(p_id, True, db_path=db_path)
                        st.toast(f"Produção de '{p.get('name')}' ativada.")
                        st.rerun()

            # Expander de Gestão do Canal
            with st.expander(f"⚙️ Gerenciar Canal: {p.get('name')}", expanded=False):
                if not is_primary:
                    st.caption("🔒 View Only — alterações devem ser feitas no nó PRIMARY.")

                c_m_name, c_m_niche = st.columns(2)
                with c_m_name:
                    m_name = st.text_input("Nome", value=p.get("name") or "", key=f"m_name_{p_id}", disabled=not is_primary)
                with c_m_niche:
                    m_niche = st.text_input("Nicho", value=p.get("niche") or "", key=f"m_niche_{p_id}", disabled=not is_primary)

                m_brief = st.text_area("Tema / Linha Editorial", value=settings.editorial.topic_brief or "", key=f"m_brief_{p_id}", disabled=not is_primary)

                global_voice = config.ui.get("voice_name") or config.app.get("voice_name") or "en-US-BrianMultilingualNeural"
                c_m_v, c_m_stk = st.columns(2)
                with c_m_v:
                    st.text_input("Voz Global da Fábrica", value=f"Global: {global_voice}", key=f"m_voice_{p_id}", disabled=True)
                with c_m_stk:
                    m_target_stock = st.number_input("Meta de Estoque", min_value=1, max_value=10, value=int(settings.automation.target_ready_stock or 3), key=f"m_stock_{p_id}", disabled=not is_primary)

                st.caption("ℹ️ Visual Director e Google Flow integrados ao pipeline.")
                c_m_vd, c_m_flow, c_m_scenes = st.columns(3)
                with c_m_vd:
                    m_vd = st.checkbox("Visual Director", value=bool(settings.visual.visual_director_enabled), key=f"m_vd_{p_id}", disabled=not is_primary)
                with c_m_flow:
                    m_flow = st.checkbox("Google Flow", value=bool(settings.visual.flow_enabled), key=f"m_flow_{p_id}", disabled=not is_primary)
                with c_m_scenes:
                    m_scenes = st.number_input("Cenas Flow", min_value=1, max_value=10, value=int(settings.visual.flow_scene_count or profile_manager.DEFAULT_FLOW_PREMIUM_SCENES_PER_SHORT), key=f"m_scenes_{p_id}", disabled=not is_primary)

                m_fallback = st.checkbox("Fallback para Stock", value=bool(settings.visual.stock_fallback_enabled), key=f"m_fallback_{p_id}", disabled=not is_primary)

                # Som Ambiente (Fase V1.5E-G8)
                st.markdown("##### 🎵 Som Ambiente")
                cur_music = getattr(settings, "music", None) or profile_manager.MusicSettings()
                m_music_enabled = st.checkbox("Ativar som ambiente", value=bool(cur_music.enabled), key=f"m_music_en_{p_id}", disabled=not is_primary)
                c_mm_mode, c_mm_vol, c_mm_mood = st.columns(3)
                with c_mm_mode:
                    st.selectbox("Modo", options=["Auto pelo roteiro"], index=0, key=f"m_music_mode_{p_id}", disabled=True)
                with c_mm_vol:
                    m_vol_options = [0.05, 0.08, 0.10, 0.12, 0.15, 0.20]
                    m_vol_labels = ["5%", "8%", "10%", "12%", "15%", "20%"]
                    cur_vol_val = float(cur_music.volume if cur_music.volume is not None else 0.20)
                    cur_vol_idx = min(range(len(m_vol_options)), key=lambda i: abs(m_vol_options[i] - cur_vol_val))
                    sel_m_vol_idx = st.selectbox(
                        "Volume",
                        options=range(len(m_vol_options)),
                        format_func=lambda i: m_vol_labels[i],
                        index=cur_vol_idx,
                        key=f"m_music_vol_{p_id}",
                        disabled=not is_primary,
                    )
                    m_music_volume = m_vol_options[sel_m_vol_idx]
                with c_mm_mood:
                    m_mood_options = ["Neutral", "Suspense", "Terror", "Futuristic", "Epic", "Energetic", "Emotional"]
                    cur_mood_val = str(cur_music.default_mood or "neutral").capitalize()
                    cur_mood_idx = m_mood_options.index(cur_mood_val) if cur_mood_val in m_mood_options else 0
                    m_music_default_mood = st.selectbox(
                        "Mood padrão",
                        options=m_mood_options,
                        index=cur_mood_idx,
                        key=f"m_music_mood_{p_id}",
                        disabled=not is_primary,
                    ).lower()

                # Destino YouTube
                if yt:
                    m_yt_enabled = st.checkbox("Destino YouTube Habilitado", value=bool(yt.get("is_enabled")), key=f"m_yt_en_{p_id}", disabled=not is_primary)
                    m_yt_ext = st.text_input("YouTube Channel ID (UC...)", value=yt.get("external_account_id") or "", key=f"m_yt_ext_{p_id}", disabled=not is_primary)
                else:
                    m_yt_enabled = False
                    m_yt_ext = ""

                if st.button("💾 Salvar Alterações", key=f"save_prof_{p_id}", disabled=not is_primary):
                    clean_m_name = str(m_name).strip()
                    clean_m_niche = str(m_niche).strip()
                    if not clean_m_name or not clean_m_niche:
                        st.error("Nome e nicho não podem ser vazios.")
                    else:
                        profile_manager.update_profile(p_id, name=clean_m_name, niche=clean_m_niche, db_path=db_path)
                        updated_settings = settings.model_copy(deep=True)
                        updated_settings.editorial.topic_brief = str(m_brief or "").strip()
                        updated_settings.voice.voice_name = settings.voice.voice_name or global_voice
                        updated_settings.visual.visual_director_enabled = bool(m_vd)
                        updated_settings.visual.flow_enabled = bool(m_flow)
                        updated_settings.visual.flow_scene_count = int(m_scenes)
                        updated_settings.visual.stock_fallback_enabled = bool(m_fallback)
                        updated_settings.automation.target_ready_stock = int(m_target_stock)
                        updated_settings.music.enabled = bool(m_music_enabled)
                        updated_settings.music.mode = "auto"
                        updated_settings.music.volume = float(m_music_volume)
                        updated_settings.music.default_mood = str(m_music_default_mood).lower()
                        profile_manager.update_profile_settings(p_id, updated_settings, db_path=db_path)

                        if yt:
                            profile_manager.update_channel(
                                yt["id"],
                                is_enabled=bool(m_yt_enabled),
                                external_account_id=str(m_yt_ext).strip() if m_yt_ext else None,
                                db_path=db_path,
                            )
                        st.toast(f"Canal '{clean_m_name}' atualizado com sucesso!")
                        st.rerun()
