def _safe_rerun_app():
    """Reexecuta a aplicação globalmente para propagar mutações estruturais."""
    try:
        st.rerun(scope="app")
    except TypeError:
        st.rerun()
    except Exception:
        pass

"""
Channel Factory UI Component (Fase V1.5E-B — Generic Channel Onboarding).

Apresenta a experiência de Channel Factory:
- Visão geral de canais/workspaces em cards
- CTA '+ Novo Canal' com onboarding em 4 blocos (Identidade, Publicação, Produção, Ativação)
- Default seguro: produção autônoma sempre nasce pausada até ação explícita do operador
- Gerenciamento e edição de configurações de canais existentes
"""
from typing import Any, Dict, Optional
import streamlit as st

from app.config import config
from app.services import autonomous_production, operator_console, post_for_me, profile_manager

VIDEO_FORMAT_CHOICES = ["traditional", "quiz_dilemma", "quiz_paper"]
VIDEO_FORMAT_LABELS = {
    "traditional": "🎬 Vídeo Padrão / Narrativa Tradicional",
    "quiz_dilemma": "❓ Quiz / Escolhas Impossíveis",
    "quiz_paper": "📝 Quiz de Papel / Perguntas & Respostas",
}

CLOSING_TYPE_CHOICES = ["auto", "engagement_cta", "score_challenge", "quiz_choice_religious"]
CLOSING_TYPE_LABELS = {
    "auto": "Auto (CTA neutro para gerais; religioso se nicho de fé)",
    "engagement_cta": "Engajamento Geral (Seguir perfil / Apoiar canal)",
    "score_challenge": "Desafio de Pontuação (Quantas você acertou?)",
    "quiz_choice_religious": "Engajamento Religioso (Curtir & Comentar: Jesus te ama)",
}


def _get_channel_card_data(p: Dict[str, Any], db_path: Optional[str] = None) -> Dict[str, Any]:
    """Coleta informações operacionais consolidadas para o card do canal."""
    pid = p.get("id", "")
    settings = profile_manager.get_profile_settings(pid, db_path=db_path)
    channels = profile_manager.list_channels(profile_id=pid, db_path=db_path)
    yt_channel = next((c for c in channels if c.get("platform") == "youtube"), None)
    tiktok_channel = next((c for c in channels if c.get("platform") == "tiktok"), None)

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

    video_format = getattr(settings.editorial, "video_format", None) or getattr(settings.editorial, "content_style", None) or "traditional"

    return {
        "profile": p,
        "settings": settings,
        "channels": channels,
        "yt_channel": yt_channel,
        "tiktok_channel": tiktok_channel,
        "autonomous_enabled": is_auto_enabled,
        "target_stock": target_stock,
        "ready_stock": ready_stock,
        "video_format": video_format,
    }


def _render_onboarding_form(is_primary: bool, db_path: Optional[str] = None):
    """Renderiza os 4 blocos do formulário de criação de novo canal com st.form e fail-closed accounts."""
    st.markdown("#### 🚀 Configurar Novo Canal")
    st.caption("Cadastre um novo canal editorial sem necessidade de alterações no código.")

    if "cf_connected_yt_accounts" not in st.session_state:
        try:
            st.session_state["cf_connected_yt_accounts"] = post_for_me.list_connected_publishing_accounts(platform="youtube")
        except Exception:
            st.session_state["cf_connected_yt_accounts"] = []

    if "cf_connected_tt_accounts" not in st.session_state:
        try:
            st.session_state["cf_connected_tt_accounts"] = post_for_me.list_connected_publishing_accounts(platform="tiktok")
        except Exception:
            st.session_state["cf_connected_tt_accounts"] = []

    yt_accounts = st.session_state.get("cf_connected_yt_accounts", [])
    tt_accounts = st.session_state.get("cf_connected_tt_accounts", [])

    if not yt_accounts and not tt_accounts:
        st.warning("⚠️ Nenhuma conta social (YouTube/TikTok) conectada encontrada no Post for Me. O canal pode ser criado apenas para geração de estoque (publicação desativada).")

    with st.container():
        # 1. Identidade e Formato do Canal
        st.markdown("##### 1. Identidade e Formato do Canal")
        c_name, c_niche = st.columns(2)
        with c_name:
            name_val = st.text_input("Nome do Canal *", placeholder="Ex: GTA Daily DEV", key="cf_new_ch_name")
        with c_niche:
            niche_val = st.text_input("Nicho *", placeholder="Ex: games", key="cf_new_ch_niche")

        c_format, c_lang = st.columns([2, 1])
        with c_format:
            sel_format = st.selectbox(
                "Formato de Vídeo *",
                options=VIDEO_FORMAT_CHOICES,
                format_func=lambda f: VIDEO_FORMAT_LABELS.get(f, f),
                key="cf_new_ch_format",
                help="Define o formato permanente deste canal (Tradicional, Quiz Dilema Q0-R ou Quiz de Papel P1.3).",
            )
        with c_lang:
            st.selectbox("Idioma", options=["pt-BR"], index=0, key="cf_new_ch_lang", disabled=True)

        topic_brief_val = st.text_area(
            "Tema / Descrição Editorial *",
            placeholder="Ex: GTA VI: novidades, notícias oficiais, análises e teorias",
            key="cf_new_ch_topic",
            height=68,
        )

        quiz_closing = "auto"
        quiz_num_q = 8
        if sel_format == "quiz_dilemma":
            st.markdown("###### ⚙️ Configurações do Quiz Engine (Q0-R)")
            c_qc, c_qn = st.columns(2)
            with c_qc:
                quiz_closing = st.selectbox(
                    "Tipo de Encerramento",
                    options=CLOSING_TYPE_CHOICES,
                    format_func=lambda c: CLOSING_TYPE_LABELS.get(c, c),
                    key="cf_new_ch_quiz_closing",
                    help="Define o gancho final. Canais gerais nunca recebem CTA religioso em 'Auto'.",
                )
            with c_qn:
                quiz_num_q = st.number_input(
                    "Quantidade de Dilemas por Vídeo",
                    min_value=4,
                    max_value=12,
                    value=8,
                    step=1,
                    key="cf_new_ch_quiz_num_q",
                    help="Padrão homologado Q0-R: 8 dilemas (duração ~65-75s).",
                )
        elif sel_format == "quiz_paper":
            st.info("📝 **Quiz de Papel (Padrão P1.3 Homologado)**: 5 perguntas factuais com 4 alternativas simultâneas, timer circular de 6s, tela final de comentários de 6s e duração editorial estrita de 60-65s.")

        # 2. Publicação e Destino
        st.markdown("##### 2. Publicação e Destino")
        st.caption("Destinos de publicação via Post for Me (vínculo explícito por plataforma). Escolha YouTube, TikTok, ambos ou nenhum (somente estoque).")

        c_dest_yt, c_dest_tt = st.columns(2)
        with c_dest_yt:
            st.markdown("###### ▶️ Destino YouTube")
            if yt_accounts:
                yt_acc_map = {}
                yt_choices = ["none"]
                yt_labels = {"none": "🚫 Não vincular YouTube"}
                for acc in yt_accounts:
                    k = f"{acc.get('project_id', '')}::{acc['external_account_id']}"
                    yt_acc_map[k] = acc
                    yt_choices.append(k)
                    p_label = f" — [{acc.get('project_name') or acc.get('project_id')}]" if acc.get("project_name") or acc.get("project_id") else ""
                    yt_labels[k] = f"▶️ {acc['display_name']} ({acc['external_account_id']}){p_label}"

                sel_yt_acc = st.selectbox(
                    "Conta YouTube",
                    options=yt_choices,
                    format_func=lambda k: yt_labels.get(k, k),
                    key="cf_new_ch_yt_acc_sel",
                    help="Selecione explicitamente a conta YouTube conectada no Post for Me com seu respectivo projeto.",
                )
            else:
                sel_yt_acc = "none"
                yt_acc_map = {}
                st.caption("ℹ️ Nenhuma conta YouTube conectada no Post for Me.")

        with c_dest_tt:
            st.markdown("###### 🎵 Destino TikTok")
            if tt_accounts:
                tt_acc_map = {}
                tt_choices = ["none"]
                tt_labels = {"none": "🚫 Não vincular TikTok"}
                for acc in tt_accounts:
                    k = f"{acc.get('project_id', '')}::{acc['external_account_id']}"
                    tt_acc_map[k] = acc
                    tt_choices.append(k)
                    p_label = f" — [{acc.get('project_name') or acc.get('project_id')}]" if acc.get("project_name") or acc.get("project_id") else ""
                    tt_labels[k] = f"🎵 {acc['display_name']} ({acc['external_account_id']}){p_label}"

                sel_tt_acc = st.selectbox(
                    "Conta TikTok",
                    options=tt_choices,
                    format_func=lambda k: tt_labels.get(k, k),
                    key="cf_new_ch_tt_acc_sel",
                    help="Selecione explicitamente a conta TikTok conectada no Post for Me com seu respectivo projeto.",
                )
            else:
                sel_tt_acc = "none"
                tt_acc_map = {}
                st.caption("ℹ️ Nenhuma conta TikTok conectada no Post for Me.")

        # 3. Produção & Visual
        st.markdown("##### 3. Produção & Visual")
        global_voice = autonomous_production.get_canonical_global_voice()
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

        submitted = st.button("🚀 Criar Canal", type="primary", use_container_width=True, key="cf_submit_onboard_btn")

        if submitted is True:
            if not is_primary:
                st.error("Apenas o nó PRIMARY pode cadastrar canais.")
                return

            destinations = []
            clean_yt_ext_id = None
            if sel_yt_acc != "none":
                acc = yt_acc_map.get(sel_yt_acc)
                if acc:
                    clean_yt_ext_id = acc["external_account_id"]
                    destinations.append({
                        "platform": "youtube",
                        "external_account_id": clean_yt_ext_id,
                        "project_id": acc.get("project_id"),
                        "is_enabled": True,
                    })
                elif str(sel_yt_acc).startswith("UC"):
                    clean_yt_ext_id = str(sel_yt_acc).strip()
                    destinations.append({
                        "platform": "youtube",
                        "external_account_id": clean_yt_ext_id,
                        "is_enabled": True,
                    })

            if clean_yt_ext_id and not clean_yt_ext_id.startswith("UC"):
                st.error(f"O YouTube Channel ID deve iniciar com 'UC' (recebido: '{clean_yt_ext_id}').")
                return

            if sel_tt_acc != "none":
                acc = tt_acc_map.get(sel_tt_acc)
                if acc:
                    destinations.append({
                        "platform": "tiktok",
                        "external_account_id": acc["external_account_id"],
                        "project_id": acc.get("project_id"),
                        "is_enabled": True,
                    })
                else:
                    destinations.append({
                        "platform": "tiktok",
                        "external_account_id": str(sel_tt_acc).strip(),
                        "is_enabled": True,
                    })

            ext_account_id = clean_yt_ext_id
            require_destination = bool(destinations)

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

            settings_obj = profile_manager.ChannelWorkspaceSettings()
            settings_obj.editorial.topic_brief = clean_topic
            settings_obj.editorial.video_format = sel_format
            settings_obj.editorial.content_style = sel_format
            if sel_format == "quiz_paper":
                settings_obj.editorial.closing_type = "comments"
                settings_obj.editorial.num_questions = 5
            elif sel_format == "quiz_dilemma":
                settings_obj.editorial.closing_type = quiz_closing
                settings_obj.editorial.num_questions = int(quiz_num_q)
            else:
                settings_obj.editorial.closing_type = None
                settings_obj.editorial.num_questions = None

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
                    require_destination=require_destination,
                    db_path=db_path,
                    destinations=destinations,
                )
                new_p = res.get("profile", {})
                st.session_state["channel_factory_feedback"] = {
                    "type": "success",
                    "message": f"Canal '{new_p.get('name')}' criado com sucesso! Status inicial: {'Produção Ativa' if autonomous_start else 'Pausado (Recomendado)'}.",
                    "profile_id": new_p.get("id"),
                }
                _safe_rerun_app()
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


from functools import lru_cache


@lru_cache(maxsize=1)
def _get_base_approved_voices() -> list[str]:
    """Catálogo em cache de vozes Azure/Edge aprovadas para pt-BR."""
    candidates = ["en-US-BrianMultilingualNeural"]
    try:
        from app.services import voice
        for v in voice.get_all_azure_voices():
            base_v = voice.parse_voice_name(v)
            if autonomous_production.is_valid_pt_br_voice(v):
                candidates.append(v)
            if autonomous_production.is_valid_pt_br_voice(base_v):
                candidates.append(base_v)
    except Exception:
        pass

    static_approved = [
        "en-US-BrianMultilingualNeural",
        "pt-BR-AntonioNeural-Male",
        "pt-BR-AntonioNeural",
        "pt-BR-FranciscaNeural-Female",
        "pt-BR-FranciscaNeural",
        "pt-BR-ThalitaMultilingualNeural-Female",
        "pt-BR-ThalitaMultilingualNeural",
    ]
    candidates.extend(static_approved)

    seen = set()
    result = []
    for c in candidates:
        if c not in seen and autonomous_production.is_valid_pt_br_voice(c):
            seen.add(c)
            result.append(c)
    return result


def get_available_factory_voices(current_voice: Optional[str] = None) -> list[str]:
    """Retorna opções de vozes aprovadas para a fábrica a partir do catálogo Azure/Edge.

    Inclui obrigatoriamente Brian (en-US-BrianMultilingualNeural) e vozes pt-BR nativas.
    Todas as opções retornadas passam estritamente por autonomous_production.is_valid_pt_br_voice.
    """
    base = list(_get_base_approved_voices())
    if current_voice and autonomous_production.is_valid_pt_br_voice(current_voice):
        if current_voice not in base:
            base.insert(1, current_voice)
    return base


def save_global_voice(voice_name: str) -> tuple[bool, str]:
    """Valida e persiste a nova voz global em config.ui['voice_name'].

    Fail-closed: Se a voz não for aprovada por autonomous_production.is_valid_pt_br_voice,
    não atualiza nem persiste config.ui.
    """
    clean_voice = str(voice_name).strip() if voice_name else ""
    if not autonomous_production.is_valid_pt_br_voice(clean_voice):
        return False, f"Voz '{clean_voice}' não é permitida pelo contrato de conteúdo pt-BR."

    config.update_config_nonblocking(config.ui, "voice_name", clean_voice)
    config.try_save_config(force=True)
    return True, f"Voz global atualizada para '{clean_voice}' com sucesso!"


def _render_global_voice_section(is_primary: bool):
    """Renderiza a seção de controle da Voz Global da Fábrica (Fase V1.5E-G8.9 / G8.9.1)."""
    with st.container(border=True):
        st.markdown("#### 🎙️ Voz Global da Fábrica")
        st.caption("Esta configuração define a voz TTS única utilizada por **todos** os canais da fábrica.")

        # Fonte canônica da Voz Ativa é estritamente config.ui["voice_name"]
        current_global_voice = (
            config.ui.get("voice_name")
            or config.app.get("voice_name")
            or "en-US-BrianMultilingualNeural"
        )

        if not is_primary:
            st.caption("🔒 View Only — alterações da voz global devem ser realizadas no nó PRIMARY.")

        col_curr, col_sel, col_btn = st.columns([0.30, 0.45, 0.25])
        with col_curr:
            active_voice_placeholder = st.empty()
            active_voice_placeholder.markdown(f"**Voz Ativa:**\n`{current_global_voice}`")
        with col_sel:
            voice_options = get_available_factory_voices(current_global_voice)
            cur_idx = voice_options.index(current_global_voice) if current_global_voice in voice_options else 0
            selected_voice = st.selectbox(
                "Voz Global",
                options=voice_options,
                index=cur_idx,
                disabled=not is_primary,
                key="cf_global_voice_selector",
                label_visibility="collapsed",
            )
        with col_btn:
            st.markdown("<div style='height: 4px;'></div>", unsafe_allow_html=True)
            if st.button(
                "💾 Salvar Voz Global",
                key="cf_save_global_voice_btn",
                disabled=not is_primary,
                type="primary",
                use_container_width=True,
            ):
                ok, msg = save_global_voice(selected_voice)
                if ok:
                    active_voice_placeholder.markdown(f"**Voz Ativa:**\n`{selected_voice}`")
                    st.toast(msg)
                    st.success(msg)
                    _safe_rerun_app()
                else:
                    st.error(msg)


def _get_current_script_run_ctx():
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx()
    except Exception:
        try:
            from streamlit.runtime.scriptrunner_utils.script_run_context import get_script_run_ctx
            return get_script_run_ctx()
        except Exception:
            return None


def _channel_factory_fragment(func):
    """Aplica st.fragment em tempo de chamada se em contexto Streamlit ativo; em bare mode executa direto."""
    if not hasattr(st, "fragment"):
        return func
    try:
        fragment_func = st.fragment(func)
    except Exception:
        return func

    def wrapper(*args, **kwargs):
        if _get_current_script_run_ctx() is None:
            return func(*args, **kwargs)
        return fragment_func(*args, **kwargs)

    return wrapper


@_channel_factory_fragment
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
                        _safe_rerun_app()
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

    # Seção: Voz Global da Fábrica (Fase V1.5E-G8.9)
    _render_global_voice_section(is_primary=is_primary)

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
        tiktok = card.get("tiktok_channel")
        is_auto = card["autonomous_enabled"]
        p_id = p.get("id", "")

        with st.container(border=True):
            col_id, col_ops, col_actions = st.columns([0.45, 0.35, 0.20])

            with col_id:
                st.markdown(f"#### {p.get('name')}")
                v_format = card.get("video_format") or "traditional"
                format_badge = VIDEO_FORMAT_LABELS.get(v_format, v_format)
                st.markdown(f"🏷️ **Nicho:** `{p.get('niche') or 'Geral'}` | 🎬 **Formato:** `{format_badge}`")
                brief = settings.editorial.topic_brief or "Sem descrição editorial configurada."
                st.caption(f"📝 {brief[:120]}{'...' if len(brief) > 120 else ''}")

            with col_ops:
                dest_parts = []
                if yt and yt.get("is_enabled"):
                    acc_display = yt.get("external_account_id") or yt.get("display_name") or "Conectado"
                    proj_disp = f" [{yt.get('project_id')}]" if yt.get("project_id") else ""
                    dest_parts.append(f"YouTube ({acc_display}{proj_disp})")
                if tiktok and tiktok.get("is_enabled"):
                    acc_display = tiktok.get("external_account_id") or tiktok.get("display_name") or "Conectado"
                    proj_disp = f" [{tiktok.get('project_id')}]" if tiktok.get("project_id") else ""
                    dest_parts.append(f"TikTok ({acc_display}{proj_disp})")
                dest_label = " + ".join(dest_parts) if dest_parts else "Somente Estoque (Sem publicação)"
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
                        _safe_rerun_app()
                else:
                    if st.button("▶️ Ativar", type="secondary", key=f"activate_prof_{p_id}", use_container_width=True, disabled=not is_primary):
                        autonomous_production.set_profile_autonomous_mode_enabled(p_id, True, db_path=db_path)
                        st.toast(f"Produção de '{p.get('name')}' ativada.")
                        _safe_rerun_app()

            # Expander de Gestão do Canal
            with st.expander(f"⚙️ Gerenciar Canal: {p.get('name')}", expanded=False):
                if not is_primary:
                    st.caption("🔒 View Only — alterações devem ser feitas no nó PRIMARY.")

                prof_channels = card.get("channels") or profile_manager.list_channels(profile_id=p_id, db_path=db_path)
                m_yt = next((c for c in prof_channels if c.get("platform") == "youtube"), None)
                m_tiktok = next((c for c in prof_channels if c.get("platform") == "tiktok"), None)

                c_m_name, c_m_niche = st.columns(2)
                with c_m_name:
                    m_name = st.text_input("Nome", value=p.get("name") or "", key=f"m_name_{p_id}", disabled=not is_primary)
                with c_m_niche:
                    m_niche = st.text_input("Nicho", value=p.get("niche") or "", key=f"m_niche_{p_id}", disabled=not is_primary)

                # Formato de Vídeo e Configurações Editoriais
                cur_v_format = getattr(settings.editorial, "video_format", None) or "traditional"
                cur_f_idx = VIDEO_FORMAT_CHOICES.index(cur_v_format) if cur_v_format in VIDEO_FORMAT_CHOICES else 0
                c_m_fmt, c_m_close = st.columns(2)
                with c_m_fmt:
                    m_video_format = st.selectbox(
                        "Formato de Vídeo",
                        options=VIDEO_FORMAT_CHOICES,
                        index=cur_f_idx,
                        format_func=lambda f: VIDEO_FORMAT_LABELS.get(f, f),
                        key=f"m_fmt_{p_id}",
                        disabled=not is_primary,
                    )

                cur_closing = getattr(settings.editorial, "closing_type", None) or "auto"
                cur_num_q = int(getattr(settings.editorial, "num_questions", None) or 8)

                if m_video_format == "quiz_dilemma":
                    with c_m_close:
                        cur_c_idx = CLOSING_TYPE_CHOICES.index(cur_closing) if cur_closing in CLOSING_TYPE_CHOICES else 0
                        m_closing_type = st.selectbox(
                            "Tipo de Encerramento (Quiz)",
                            options=CLOSING_TYPE_CHOICES,
                            index=cur_c_idx,
                            format_func=lambda c: CLOSING_TYPE_LABELS.get(c, c),
                            key=f"m_close_{p_id}",
                            disabled=not is_primary,
                        )
                    m_num_questions = st.number_input(
                        "Quantidade de Dilemas por Vídeo",
                        min_value=4,
                        max_value=12,
                        value=cur_num_q,
                        step=1,
                        key=f"m_num_q_{p_id}",
                        disabled=not is_primary,
                    )
                elif m_video_format == "quiz_paper":
                    with c_m_close:
                        st.caption("📝 Padrão P1.3 Homologado: 5 perguntas factuais, timer circular 6s, encerramento de 6s.")
                    m_closing_type = "comments"
                    m_num_questions = 5
                else:
                    with c_m_close:
                        st.caption("ℹ️ Formato padrão utiliza narrativa tradicional linear.")
                    m_closing_type = None
                    m_num_questions = None

                m_brief = st.text_area("Tema / Linha Editorial", value=settings.editorial.topic_brief or "", key=f"m_brief_{p_id}", disabled=not is_primary)

                global_voice = autonomous_production.get_canonical_global_voice()
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

                # Destinos de Publicação
                st.markdown("##### 📡 Destinos de Publicação")
                c_dest_yt_m, c_dest_tt_m = st.columns(2)
                with c_dest_yt_m:
                    st.markdown("###### ▶️ YouTube")
                    yt_is_en = bool(m_yt.get("is_enabled")) if m_yt else False
                    m_yt_enabled = st.checkbox("Destino YouTube Habilitado", value=yt_is_en, key=f"m_yt_en_{p_id}", disabled=not is_primary)
                    m_yt_ext = st.text_input("YouTube Channel ID (UC...)", value=(m_yt.get("external_account_id") or "") if m_yt else "", key=f"m_yt_ext_{p_id}", disabled=not is_primary)

                with c_dest_tt_m:
                    st.markdown("###### 🎵 TikTok")
                    tt_is_en = bool(m_tiktok.get("is_enabled")) if m_tiktok else False
                    m_tiktok_enabled = st.checkbox("Destino TikTok Habilitado", value=tt_is_en, key=f"m_tt_en_{p_id}", disabled=not is_primary)
                    m_tiktok_ext = st.text_input("TikTok Account / User ID", value=(m_tiktok.get("external_account_id") or "") if m_tiktok else "", key=f"m_tt_ext_{p_id}", disabled=not is_primary)

                if st.button("💾 Salvar Alterações", key=f"save_prof_{p_id}", disabled=not is_primary):
                    clean_m_name = str(m_name).strip()
                    clean_m_niche = str(m_niche).strip()
                    if not clean_m_name or not clean_m_niche:
                        st.error("Nome e nicho não podem ser vazios.")
                    else:
                        profile_manager.update_profile(p_id, name=clean_m_name, niche=clean_m_niche, db_path=db_path)
                        updated_settings = settings.model_copy(deep=True)
                        updated_settings.editorial.topic_brief = str(m_brief or "").strip()
                        updated_settings.editorial.video_format = str(m_video_format)
                        if m_video_format == "quiz_paper":
                            updated_settings.editorial.closing_type = "comments"
                            updated_settings.editorial.num_questions = 5
                        elif m_video_format == "quiz_dilemma":
                            updated_settings.editorial.closing_type = str(m_closing_type) if m_closing_type else None
                            updated_settings.editorial.num_questions = int(m_num_questions) if m_num_questions else None
                        else:
                            updated_settings.editorial.closing_type = None
                            updated_settings.editorial.num_questions = None

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

                        # Atualiza ou cria destino YouTube
                        if m_yt:
                            profile_manager.update_channel(
                                m_yt["id"],
                                is_enabled=bool(m_yt_enabled),
                                external_account_id=str(m_yt_ext).strip() if m_yt_ext else None,
                                db_path=db_path,
                            )
                        elif m_yt_ext:
                            profile_manager.create_channel(
                                profile_id=p_id,
                                platform="youtube",
                                display_name=f"{clean_m_name} (YouTube)",
                                external_profile_name=clean_m_name,
                                external_account_id=str(m_yt_ext).strip(),
                                is_enabled=bool(m_yt_enabled),
                                db_path=db_path,
                            )

                        # Atualiza ou cria destino TikTok
                        if m_tiktok:
                            profile_manager.update_channel(
                                m_tiktok["id"],
                                is_enabled=bool(m_tiktok_enabled),
                                external_account_id=str(m_tiktok_ext).strip() if m_tiktok_ext else None,
                                db_path=db_path,
                            )
                        elif m_tiktok_ext:
                            profile_manager.create_channel(
                                profile_id=p_id,
                                platform="tiktok",
                                display_name=f"{clean_m_name} (TikTok)",
                                external_profile_name=clean_m_name,
                                external_account_id=str(m_tiktok_ext).strip(),
                                is_enabled=bool(m_tiktok_enabled),
                                db_path=db_path,
                            )

                        st.toast(f"Canal '{clean_m_name}' atualizado com sucesso!")
                        _safe_rerun_app()
