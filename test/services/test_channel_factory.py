"""
Testes unitários e de integração para Channel Factory (Fase V1.5E-B — Generic Channel Onboarding).

Cenários cobertos (A a N):
A. Migration idempotente
B. settings_json vazio mantém comportamento legado
C. Settings tipado serialize/deserialize
D. Onboarding cria profile + channel + settings atomicamente
E. Falha ao criar destination: rollback profile inteiro (zero profile órfão)
F. external_account_id persistido corretamente
G. Nenhum secret persistido no banco
H. Post for Me resolve novo canal via external_account_id no banco
I. Canais antigos continuam resolvendo (backward compatibility)
J. autonomous_enabled começa OFF para novo canal (safe default)
K. Worker descobre novo profile quando ativado
L. Scheduler mantém channel_id correto
M. Cadastro GTA Daily DEV sem código específico
N. Cadastro Tech Daily DEV usando exatamente o mesmo caminho
"""
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.services import (
    autonomous_production,
    operator_console,
    post_for_me,
    profile_manager,
    scheduler,
)


class TestChannelFactory(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_channel_factory.db")

        # Inicializa dbs
        operator_console.init_operator_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        scheduler.init_db(self.db_path)

        # Garante nó local como PRIMARY
        operator_console.reset_instance_for_testing()
        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._is_primary = True

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_a_migration_idempotent(self):
        """A. Migration deve ser aditiva, idempotente e segura para chamadas repetidas."""
        # 1. Executa init_profile_db múltiplas vezes
        profile_manager.init_profile_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)

        with profile_manager.get_connection(self.db_path) as conn:
            p_cols = [r["name"] for r in conn.execute("PRAGMA table_info(content_profiles);").fetchall()]
            ch_cols = [r["name"] for r in conn.execute("PRAGMA table_info(publishing_channels);").fetchall()]

            self.assertIn("settings_json", p_cols)
            self.assertIn("external_account_id", ch_cols)

        # 2. Testa banco legado criado sem as novas colunas
        legacy_db = os.path.join(self.test_dir, "legacy.db")
        conn = sqlite3.connect(legacy_db)
        conn.execute(
            """
            CREATE TABLE content_profiles (
                id TEXT PRIMARY KEY, name TEXT, slug TEXT UNIQUE, niche TEXT,
                language TEXT, region TEXT, default_preset TEXT, growth_mode TEXT,
                is_active INTEGER, created_at TEXT, updated_at TEXT
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE publishing_channels (
                id TEXT PRIMARY KEY, profile_id TEXT, platform TEXT, display_name TEXT,
                external_profile_name TEXT, is_enabled INTEGER, created_at TEXT, updated_at TEXT
            );
            """
        )
        conn.execute("INSERT INTO content_profiles VALUES ('p1', 'Legacy', 'legacy', 'geral', 'pt-BR', 'BR', 'c', 'n', 1, 'now', 'now');")
        conn.commit()
        conn.close()

        # Executa migration no banco legado
        profile_manager.init_profile_db(legacy_db)

        # Verifica preservação de registros e adição de colunas
        with profile_manager.get_connection(legacy_db) as conn:
            p_cols_up = [r["name"] for r in conn.execute("PRAGMA table_info(content_profiles);").fetchall()]
            ch_cols_up = [r["name"] for r in conn.execute("PRAGMA table_info(publishing_channels);").fetchall()]
            self.assertIn("settings_json", p_cols_up)
            self.assertIn("external_account_id", ch_cols_up)

            row = conn.execute("SELECT * FROM content_profiles WHERE id = 'p1';").fetchone()
            self.assertEqual(row["name"], "Legacy")
            self.assertEqual(row["settings_json"], "{}")

    def test_b_empty_settings_json_preserves_legacy_behavior(self):
        """B. settings_json vazio ou ausente mantém comportamento legado (sem Flow e sem overrides forçados)."""
        p = profile_manager.create_profile(name="Canal Antigo", niche="curiosidades", db_path=self.db_path)
        pid = p["id"]

        settings = profile_manager.get_profile_settings(pid, db_path=self.db_path)
        self.assertEqual(settings.schema_version, 1)
        self.assertIsNone(settings.automation.autonomous_enabled)
        self.assertIsNone(settings.visual.flow_enabled)

        ctx = profile_manager.get_generation_profile_context(pid, db_path=self.db_path)
        self.assertEqual(ctx["profile_id"], pid)
        self.assertEqual(ctx["niche"], "curiosidades")
        from app.config import config
        expected_global_voice = config.ui.get("voice_name") or config.app.get("voice_name") or "en-US-BrianMultilingualNeural"
        self.assertEqual(ctx["voice_name"], expected_global_voice)
        self.assertFalse(ctx["visual_director_enabled"])
        self.assertFalse(ctx["flow_enabled"])

    def test_c_typed_settings_serialize_deserialize(self):
        """C. ChannelWorkspaceSettings serialize e deserialize com validação tipada."""
        settings = profile_manager.ChannelWorkspaceSettings()
        settings.editorial.topic_brief = "Análises técnicas detalhadas de IA"
        settings.voice.voice_name = "pt-BR-AntonioNeural"
        settings.visual.flow_scene_count = 7
        settings.automation.autonomous_enabled = True
        settings.automation.target_ready_stock = 5

        json_str = settings.to_json()
        self.assertIn("Análises técnicas", json_str)
        self.assertIn("pt-BR-AntonioNeural", json_str)

        loaded = profile_manager.ChannelWorkspaceSettings.from_json(json_str)
        self.assertEqual(loaded.editorial.topic_brief, "Análises técnicas detalhadas de IA")
        self.assertEqual(loaded.voice.voice_name, "pt-BR-AntonioNeural")
        self.assertEqual(loaded.visual.flow_scene_count, 7)
        self.assertEqual(loaded.automation.autonomous_enabled, True)
        self.assertEqual(loaded.automation.target_ready_stock, 5)

        # Resiliência a entradas vazias: fields opcionais permanecem None para herança
        empty_loaded = profile_manager.ChannelWorkspaceSettings.from_json("{}")
        self.assertEqual(empty_loaded.schema_version, 1)
        self.assertIsNone(empty_loaded.automation.autonomous_enabled)

    def test_d_onboarding_creates_profile_channel_settings(self):
        """D. Onboarding atômico cria profile, destination e settings tipados."""
        res = profile_manager.onboard_channel_workspace(
            name="Canal de Teste D",
            niche="tecnologia",
            topic_brief="Notícias de hardware e semicondutores",
            language="pt-BR",
            external_account_id="UCsample_d_1234567890",
            db_path=self.db_path,
        )

        self.assertIn("profile", res)
        self.assertIn("channel", res)
        self.assertIn("settings", res)

        prof = res["profile"]
        chan = res["channel"]
        sett = res["settings"]

        self.assertEqual(prof["name"], "Canal de Teste D")
        self.assertEqual(prof["niche"], "tecnologia")
        self.assertEqual(chan["profile_id"], prof["id"])
        self.assertEqual(chan["platform"], "youtube")
        self.assertEqual(chan["external_account_id"], "UCsample_d_1234567890")
        self.assertEqual(sett.editorial.topic_brief, "Notícias de hardware e semicondutores")

    def test_e_destination_failure_rolls_back_entire_profile(self):
        """E. Falha ao criar destination faz rollback completo sem deixar profile órfão."""
        from contextlib import contextmanager
        initial_profs = profile_manager.list_profiles(db_path=self.db_path)
        initial_count = len(initial_profs)

        real_get_connection = profile_manager.get_connection

        class FailingConnWrapper:
            def __init__(self, conn):
                self._conn = conn

            def __enter__(self):
                self._conn.__enter__()
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                return self._conn.__exit__(exc_type, exc_val, exc_tb)

            def execute(self, sql, *args):
                if "INSERT INTO publishing_channels" in str(sql):
                    raise sqlite3.OperationalError("Simulated destination failure")
                return self._conn.execute(sql, *args)

            def __getattr__(self, name):
                return getattr(self._conn, name)

        @contextmanager
        def failing_get_connection(db_path=None):
            with real_get_connection(db_path) as conn:
                yield FailingConnWrapper(conn)

        with patch("app.services.profile_manager.get_connection", side_effect=failing_get_connection):
            with self.assertRaises(sqlite3.OperationalError):
                profile_manager.onboard_channel_workspace(
                    name="Canal Falho",
                    niche="teste",
                    external_account_id="UCfail_test_1234567890",
                    db_path=self.db_path,
                )

        # Verifica rollback: nenhum profile órfão criado
        after_profs = profile_manager.list_profiles(db_path=self.db_path)
        self.assertEqual(len(after_profs), initial_count)
        orphan = profile_manager.get_profile("canal-falho", db_path=self.db_path)
        self.assertIsNone(orphan)

    def test_f_external_account_id_persisted_correctly(self):
        """F. external_account_id persistido e consultável no SQLite."""
        expected_uc = "UCalpha_bravo_ch_998877"
        res = profile_manager.onboard_channel_workspace(
            name="Alpha Bravo Channel",
            niche="aviacao",
            external_account_id=expected_uc,
            db_path=self.db_path,
        )
        chan_id = res["channel"]["id"]

        with profile_manager.get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT external_account_id FROM publishing_channels WHERE id = ?;",
                (chan_id,),
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["external_account_id"], expected_uc)

    def test_g_no_secrets_persisted(self):
        """G. Nenhum secret, bearer token ou chave de API persistido no SQLite."""
        res = profile_manager.onboard_channel_workspace(
            name="Canal Seguro",
            niche="seguranca",
            external_account_id="UCseguro_1234567890",
            db_path=self.db_path,
        )

        with profile_manager.get_connection(self.db_path) as conn:
            for table in ("content_profiles", "publishing_channels", "autopilot_settings"):
                rows = conn.execute(f"SELECT * FROM {table};").fetchall()
                for r in rows:
                    for col in r.keys():
                        val = str(r[col] or "")
                        self.assertNotIn("Bearer ", val)
                        self.assertNotIn("POST_FOR_ME_API_KEY", val)
                        self.assertNotIn("sk-", val)

    def test_h_post_for_me_resolves_new_channel_via_external_account_id(self):
        """H. Post for Me resolve novo canal via external_account_id salvo no banco."""
        expected_uc = "UCnew_generic_channel_778899"
        res = profile_manager.onboard_channel_workspace(
            name="Generic Onboarded Channel",
            niche="geral",
            external_account_id=expected_uc,
            db_path=self.db_path,
        )
        chan_id = res["channel"]["id"]
        prof_id = res["profile"]["id"]

        # Resolução por channel_id
        resolved = post_for_me.resolve_target_youtube_channel_id(
            channel_id=chan_id,
            profile_id=prof_id,
            db_path=self.db_path,
        )
        self.assertEqual(resolved, expected_uc)

        # Resolução por profile_id direto
        resolved_by_prof = post_for_me.resolve_target_youtube_channel_id(
            channel_id=None,
            profile_id=prof_id,
            db_path=self.db_path,
        )
        self.assertEqual(resolved_by_prof, expected_uc)

    def test_i_legacy_channels_continue_resolving(self):
        """I. Canais legados continuam resolvendo normalmente."""
        # Default
        res_def = post_for_me.resolve_target_youtube_channel_id(
            post_for_me.CHANNEL_DEFAULT_YOUTUBE,
            db_path=self.db_path,
        )
        self.assertEqual(res_def, post_for_me.CHANNEL_DEFAULT_YT_ID)

        # Mistério
        res_myst = post_for_me.resolve_target_youtube_channel_id(
            post_for_me.CHANNEL_MYSTERY_YOUTUBE,
            db_path=self.db_path,
        )
        self.assertEqual(res_myst, post_for_me.CHANNEL_MYSTERY_YT_ID)

    def test_j_autonomous_enabled_defaults_to_off(self):
        """J. autonomous_enabled começa estritamente OFF para novo canal (safe default)."""
        res = profile_manager.onboard_channel_workspace(
            name="Novo Canal Não Ativado",
            niche="curiosidades",
            external_account_id="UCsafe_off_1234567890",
            db_path=self.db_path,
        )
        pid = res["profile"]["id"]

        is_auto = autonomous_production.is_profile_autonomous_mode_enabled(pid, db_path=self.db_path)
        self.assertFalse(is_auto)

        settings = profile_manager.get_profile_settings(pid, db_path=self.db_path)
        self.assertFalse(settings.automation.autonomous_enabled)

    def test_k_worker_discovers_new_profile_when_enabled(self):
        """K. Worker descobre novo profile e executa ciclo quando ativado pelo operador."""
        res = profile_manager.onboard_channel_workspace(
            name="Canal Produtivo",
            niche="financas",
            external_account_id="UCfinancas_1234567890",
            db_path=self.db_path,
        )
        pid = res["profile"]["id"]

        # Inicialmente desativado: tick ignora
        tick_res = autonomous_production.run_enabled_profiles_autonomous_cycle(db_path=self.db_path)
        self.assertIn(pid, tick_res["results"])
        self.assertTrue(tick_res["results"][pid].get("skipped"))
        self.assertEqual(tick_res["results"][pid].get("status"), "disabled")

        # Operador ativa produção
        autonomous_production.set_profile_autonomous_mode_enabled(pid, True, db_path=self.db_path)
        self.assertTrue(autonomous_production.is_profile_autonomous_mode_enabled(pid, db_path=self.db_path))

        # Resolve canal autônomo associado
        resolved_chan = autonomous_production.resolve_autonomous_youtube_channel(pid, db_path=self.db_path)
        self.assertEqual(resolved_chan, res["channel"]["id"])

    def test_l_scheduler_maintains_correct_channel_id(self):
        """L. Scheduler e task resolution mantêm channel_id correto para o canal onboarded."""
        res = profile_manager.onboard_channel_workspace(
            name="Canal Scheduler Test",
            niche="espaco",
            external_account_id="UCespaco_1234567890",
            db_path=self.db_path,
        )
        pid = res["profile"]["id"]
        cid = res["channel"]["id"]

        # Associa tarefa ao profile
        task_id = "task-cf-test-001"
        profile_manager.save_task_profile(task_id, pid, db_path=self.db_path)

        resolved_chans = profile_manager.resolve_task_channels(task_id, platforms=["youtube"], db_path=self.db_path)
        self.assertEqual(len(resolved_chans), 1)
        self.assertEqual(resolved_chans[0]["id"], cid)
        self.assertEqual(resolved_chans[0]["external_account_id"], "UCespaco_1234567890")

    def test_m_onboard_gta_daily_dev_without_code_changes(self):
        """M. Cadastro GTA Daily DEV via workspace data sem código Python específico."""
        res = profile_manager.onboard_channel_workspace(
            name="GTA Daily DEV",
            niche="games",
            topic_brief="GTA VI: notícias oficiais, trailers, análises e teorias da comunidade",
            language="pt-BR",
            external_account_id="UCgta_daily_dev_channel_001",
            autonomous_enabled=False,
            db_path=self.db_path,
        )

        prof = res["profile"]
        chan = res["channel"]
        sett = res["settings"]

        self.assertEqual(prof["name"], "GTA Daily DEV")
        self.assertEqual(prof["niche"], "games")
        self.assertEqual(chan["external_account_id"], "UCgta_daily_dev_channel_001")
        self.assertIn("GTA VI", sett.editorial.topic_brief)
        self.assertFalse(sett.automation.autonomous_enabled)

        # Contexto de geração incorporado sem nenhuma regra hardcoded
        ctx = profile_manager.get_generation_profile_context(prof["id"], db_path=self.db_path)
        self.assertEqual(ctx["niche"], "games")
        self.assertEqual(ctx["topic_brief"], "GTA VI: notícias oficiais, trailers, análises e teorias da comunidade")

    def test_n_onboard_tech_daily_dev_same_pathway(self):
        """N. Cadastro Tech Daily DEV usando exatamente o mesmo caminho genérico."""
        res = profile_manager.onboard_channel_workspace(
            name="Tech Daily DEV",
            niche="tecnologia",
            topic_brief="Notícias diárias e curiosidades sobre inteligência artificial e tecnologia",
            language="pt-BR",
            external_account_id="UCtech_daily_dev_channel_002",
            autonomous_enabled=False,
            db_path=self.db_path,
        )

        prof = res["profile"]
        chan = res["channel"]
        sett = res["settings"]

        self.assertEqual(prof["name"], "Tech Daily DEV")
        self.assertEqual(prof["niche"], "tecnologia")
        self.assertEqual(chan["external_account_id"], "UCtech_daily_dev_channel_002")
        self.assertIn("inteligência artificial", sett.editorial.topic_brief)

    def test_list_connected_publishing_accounts(self):
        """Valida list_connected_publishing_accounts com mock de API: sanitização e isolamento."""
        mock_client = MagicMock(spec=post_for_me.PostForMeClient)
        mock_client.is_configured.return_value = True
        mock_client.api_key = "test_key"
        mock_client.list_social_accounts.return_value = [
            {
                "id": "spc_1",
                "platform": "youtube",
                "status": "connected",
                "user_id": "UCvalid_acc_111",
                "display_name": "Canal Válido",
                "username": "@canalvalido",
                "token": "secret_token_123",  # Deve ser descartado
            },
            {
                "id": "spc_2",
                "platform": "youtube",
                "status": "disconnected",
                "user_id": "UCdisconn_222",
                "display_name": "Canal Desconectado",
            },
            {
                "id": "spc_3",
                "platform": "youtube",
                "status": "connected",
                "user_id": "invalid_non_uc_id",  # Deve ser ignorado
                "display_name": "Canal Sem UC",
            },
            {
                "id": "spc_4",
                "platform": "tiktok",
                "status": "connected",
                "user_id": "tt_user_1",
                "display_name": "TikTok",
            },
        ]

        accounts = post_for_me.list_connected_publishing_accounts(platform="youtube", client=mock_client)
        self.assertEqual(len(accounts), 1)
        acc = accounts[0]
        self.assertEqual(acc["external_account_id"], "UCvalid_acc_111")
        self.assertEqual(acc["display_name"], "Canal Válido")
        self.assertEqual(acc["username"], "@canalvalido")
        self.assertNotIn("token", acc)
        self.assertNotIn("id", acc)

    def test_legacy_empty_settings_uses_existing_global_voice(self):
        """Settings vazio/legado herda global config da UI mesmo se diferente de Francisca."""
        from app.config import config
        p = profile_manager.create_profile(name="Canal Voz Legada", niche="curiosidades", db_path=self.db_path)
        pid = p["id"]

        orig_voice = config.ui.get("voice_name")
        try:
            config.ui["voice_name"] = "pt-BR-AntonioNeural"
            ctx = profile_manager.get_generation_profile_context(pid, db_path=self.db_path)
            self.assertEqual(ctx["voice_name"], "pt-BR-AntonioNeural")

            params = autonomous_production.build_autonomous_video_params(
                topic="Tema Teste",
                profile_id=pid,
                db_path=self.db_path,
            )
            self.assertEqual(params.voice_name, "pt-BR-AntonioNeural")
        finally:
            if orig_voice is not None:
                config.ui["voice_name"] = orig_voice

    def test_legacy_empty_settings_does_not_enable_flow_implicitly(self):
        """Canais legados com settings_json vazio NÃO ligam Flow nem Visual Director implicitamente."""
        p = profile_manager.create_profile(name="Canal Legado Sem Flow", niche="curiosidades", db_path=self.db_path)
        pid = p["id"]

        ctx = profile_manager.get_generation_profile_context(pid, db_path=self.db_path)
        self.assertFalse(ctx["flow_enabled"])
        self.assertFalse(ctx["visual_director_enabled"])
        self.assertEqual(ctx["flow_scene_count"], profile_manager.DEFAULT_FLOW_PREMIUM_SCENES_PER_SHORT)

    def test_edit_does_not_toggle_autonomous_state(self):
        """Edição de configurações operacionais (voz/visual) NÃO altera status de ativação do canal."""
        res = profile_manager.onboard_channel_workspace(
            name="Canal Toggle Guard",
            niche="games",
            external_account_id="UCtoggle_guard_1234567890",
            db_path=self.db_path,
        )
        pid = res["profile"]["id"]

        # 1. Ativar canal -> editar voz -> salvar -> canal permanece ACTIVE
        autonomous_production.set_profile_autonomous_mode_enabled(pid, True, db_path=self.db_path)
        self.assertTrue(autonomous_production.is_profile_autonomous_mode_enabled(pid, db_path=self.db_path))

        current_settings = profile_manager.get_profile_settings(pid, db_path=self.db_path)
        current_settings.voice.voice_name = "pt-BR-AntonioNeural"
        profile_manager.update_profile_settings(pid, current_settings, db_path=self.db_path)

        self.assertTrue(autonomous_production.is_profile_autonomous_mode_enabled(pid, db_path=self.db_path))

        # 2. Pausar canal -> editar visual -> salvar -> canal permanece PAUSED
        autonomous_production.set_profile_autonomous_mode_enabled(pid, False, db_path=self.db_path)
        self.assertFalse(autonomous_production.is_profile_autonomous_mode_enabled(pid, db_path=self.db_path))

        current_settings.visual.flow_scene_count = 8
        profile_manager.update_profile_settings(pid, current_settings, db_path=self.db_path)

        self.assertFalse(autonomous_production.is_profile_autonomous_mode_enabled(pid, db_path=self.db_path))

    def test_onboarding_requires_connected_external_account(self):
        """Onboarding fail-closed: exige external_account_id válido iniciando com UC para YouTube."""
        # Sem account_id
        with self.assertRaises(ValueError):
            profile_manager.onboard_channel_workspace(
                name="Canal Sem Conta",
                niche="teste",
                external_account_id=None,
                platform="youtube",
                db_path=self.db_path,
            )

        # Com account_id vazio
        with self.assertRaises(ValueError):
            profile_manager.onboard_channel_workspace(
                name="Canal Conta Vazia",
                niche="teste",
                external_account_id="",
                platform="youtube",
                db_path=self.db_path,
            )

        # Com account_id que não inicia com UC
        with self.assertRaises(ValueError):
            profile_manager.onboard_channel_workspace(
                name="Canal Conta Invalida",
                niche="teste",
                external_account_id="INVALID_ID_123",
                platform="youtube",
                db_path=self.db_path,
            )

    def test_db_path_propagates_to_publish_resolver(self):
        """youtube_publisher propaga db_path até PostForMeClient e resolve external_account_id do banco temporário."""
        from app.services import youtube_publisher
        youtube_publisher.set_youtube_publish_provider("post_for_me", db_path=self.db_path)
        custom_uc = "UCresolved_temp_db_1234567890"

        res = profile_manager.onboard_channel_workspace(
            name="Canal Temp DB Publish",
            niche="tecnologia",
            external_account_id=custom_uc,
            db_path=self.db_path,
        )
        chan_id = res["channel"]["id"]
        prof_id = res["profile"]["id"]

        fake_classification = {
            "success_posts": [{
                "post_id": "post_12345",
                "result_info": {
                    "youtube_video_id": "yt_video_123",
                    "url": "https://www.youtube.com/watch?v=yt_video_123",
                    "privacy_status": "public",
                },
            }],
            "active_posts": [],
            "failed_posts": [],
            "inconsistent_posts": [],
        }

        # Mock das chamadas externas de rede
        with patch.object(post_for_me.post_for_me_client, "is_configured", return_value=True), \
             patch.object(post_for_me.post_for_me_client, "resolve_youtube_account", return_value={"id": "acc_1", "external_id": custom_uc}) as mock_resolve, \
             patch.object(post_for_me.post_for_me_client, "classify_existing_posts", return_value=fake_classification), \
             patch("os.path.exists", return_value=True), \
             patch("os.path.getsize", return_value=1024 * 1024):

            pub_res = youtube_publisher.publish_youtube_video(
                video_path=os.path.join(self.test_dir, "fake.mp4"),
                title="Título Teste",
                caption="Legenda Teste",
                task_id="task_test_db_propagation",
                channel_id=chan_id,
                profile_id=prof_id,
                db_path=self.db_path,
            )

            self.assertTrue(pub_res["success"])
            # Prova que resolve_youtube_account foi chamado com o canal resolvido da base temporária (self.db_path)
            mock_resolve.assert_called_once_with(custom_uc)

    def test_topic_brief_reaches_topic_discovery_context(self):
        """Editorial brief chega à descoberta de temas e geração de prompts sem ramificação específica de nicho."""
        from app.services import autopilot

        # 1. GTA workspace -> prompt contém GTA VI
        gta_prompt = autopilot.build_ideas_prompt(
            niche="games",
            count=5,
            language="pt-BR",
            topic_brief="GTA VI: novidades, análises e especulações",
        )
        self.assertIn("games", gta_prompt)
        self.assertIn("GTA VI: novidades, análises e especulações", gta_prompt)

        # 2. Tech workspace -> mesmo caminho contém briefing Tech
        tech_prompt = autopilot.build_ideas_prompt(
            niche="tecnologia",
            count=5,
            language="pt-BR",
            topic_brief="IA generativa e hardware",
        )
        self.assertIn("tecnologia", tech_prompt)
        self.assertIn("IA generativa e hardware", tech_prompt)

        # 3. Teste em discover_candidate_topic com mock de autopilot.generate_ideas
        with patch("app.services.trend_radar.get_trend_items", return_value=[]), \
             patch("app.services.autopilot.generate_ideas", return_value=["Ideia GTA 1"]) as mock_ideas:
            cand = autonomous_production.discover_candidate_topic(
                niche="games",
                language="pt-BR",
                db_path=self.db_path,
                topic_brief="GTA VI: novidades, análises e especulações",
            )
            self.assertIsNotNone(cand)
            self.assertEqual(cand["topic"], "Ideia GTA 1")
            mock_ideas.assert_called_once_with(
                niche="games",
                count=10,
                language="pt-BR",
                topic_brief="GTA VI: novidades, análises e especulações",
            )

    def test_current_two_legacy_channels_preserved(self):
        """Preserva 100% dos dois canais legados homologados e suas identidades."""
        profile_manager.backfill_legacy_channels_external_ids(db_path=self.db_path)

        def_ext = post_for_me.resolve_target_youtube_channel_id(
            channel_id="channel-default-youtube",
            db_path=self.db_path,
        )
        self.assertEqual(def_ext, "UCss-ng7mkGuB2v-5KKtIN9A")

        myst_ext = post_for_me.resolve_target_youtube_channel_id(
            channel_id="channel-historias-misterio-youtube",
            db_path=self.db_path,
        )
        self.assertEqual(myst_ext, "UCGJaC83EuaOwiZ0a3-KqUZA")

    def test_channel_factory_widget_keys_do_not_collide_with_operator_console(self):
        """Valida que as keys de widgets do formulário Channel Factory são isoladas e não colidem com Operator Console."""
        import re
        from pathlib import Path

        cf_path = Path("webui/components/channel_factory.py")
        op_path = Path("webui/components/operator_console.py")
        self.assertTrue(cf_path.exists())
        self.assertTrue(op_path.exists())

        cf_content = cf_path.read_text(encoding="utf-8")
        op_content = op_path.read_text(encoding="utf-8")

        # Extrai keys literais key="..."
        cf_keys = set(re.findall(r'key=["\']([^"\']+)["\']', cf_content))
        op_keys = set(re.findall(r'key=["\']([^"\']+)["\']', op_content))

        # Apenas keys estáticas (não dinâmicas com interpolação que já foram avaliadas)
        static_cf_keys = {k for k in cf_keys if "{" not in k}
        static_op_keys = {k for k in op_keys if "{" not in k}

        overlap = static_cf_keys.intersection(static_op_keys)
        self.assertEqual(overlap, set(), f"Colisão detectada entre chaves de widgets do Streamlit: {overlap}")


if __name__ == "__main__":
    unittest.main()

