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
        profile_manager.onboard_channel_workspace(
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

    def test_global_voice_selector_uses_persisted_voice(self):
        """1. Seletor usa a voz global persistida."""
        from app.config import config
        from webui.components.channel_factory import get_available_factory_voices

        orig = config.ui.get("voice_name")
        try:
            config.ui["voice_name"] = "pt-BR-FranciscaNeural"
            voices = get_available_factory_voices(current_voice="pt-BR-FranciscaNeural")
            self.assertIn("pt-BR-FranciscaNeural", voices)
        finally:
            if orig is not None:
                config.ui["voice_name"] = orig

    def test_brian_voice_available_and_accepted(self):
        """2. Brian aparece no catálogo e é aceita."""
        from app.config import config
        from webui.components.channel_factory import get_available_factory_voices, save_global_voice

        voices = get_available_factory_voices()
        self.assertIn("en-US-BrianMultilingualNeural", voices)

        orig = config.ui.get("voice_name")
        try:
            with patch.object(config, "try_save_config", return_value=True):
                ok, msg = save_global_voice("en-US-BrianMultilingualNeural")
                self.assertTrue(ok)
                self.assertEqual(config.ui["voice_name"], "en-US-BrianMultilingualNeural")
        finally:
            if orig is not None:
                config.ui["voice_name"] = orig

    def test_incompatible_voice_rejected_fail_closed(self):
        """3. Voz incompatível com contrato pt-BR é rejeitada fail-closed sem alterar config."""
        from app.config import config
        from webui.components.channel_factory import save_global_voice

        orig = config.ui.get("voice_name")
        try:
            config.ui["voice_name"] = "en-US-BrianMultilingualNeural"
            with patch.object(config, "try_save_config") as mock_save:
                ok, msg = save_global_voice("en-US-JennyNeural")
                self.assertFalse(ok)
                self.assertIn("não é permitida", msg)
                self.assertEqual(config.ui["voice_name"], "en-US-BrianMultilingualNeural")
                mock_save.assert_not_called()
        finally:
            if orig is not None:
                config.ui["voice_name"] = orig

    def test_save_global_voice_alters_config_and_calls_try_save(self):
        """4 & 5. Salvar altera config.ui['voice_name'] e chama config.try_save_config."""
        from app.config import config
        from webui.components.channel_factory import save_global_voice

        orig = config.ui.get("voice_name")
        try:
            with patch.object(config, "try_save_config", return_value=True) as mock_save:
                ok, msg = save_global_voice("pt-BR-AntonioNeural-Male")
                self.assertTrue(ok)
                self.assertEqual(config.ui["voice_name"], "pt-BR-AntonioNeural-Male")
                mock_save.assert_called_once()
        finally:
            if orig is not None:
                config.ui["voice_name"] = orig

    @patch("streamlit.empty")
    @patch("streamlit.container")
    @patch("streamlit.columns")
    @patch("streamlit.selectbox")
    @patch("streamlit.button")
    @patch("streamlit.markdown")
    @patch("streamlit.caption")
    def test_view_only_disables_mutation_controls(
        self, mock_caption, mock_markdown, mock_button, mock_selectbox, mock_columns, mock_container, mock_empty
    ):
        """6. Nó não-PRIMARY (VIEW ONLY) desabilita seletor e botão de salvar."""
        from webui.components.channel_factory import _render_global_voice_section

        mock_columns.return_value = [MagicMock(), MagicMock(), MagicMock()]
        _render_global_voice_section(is_primary=False)

        # Selectbox deve ter disabled=True
        self.assertTrue(mock_selectbox.called)
        _, kwargs_sb = mock_selectbox.call_args
        self.assertTrue(kwargs_sb.get("disabled", False))

        # Button deve ter disabled=True
        self.assertTrue(mock_button.called)
        _, kwargs_btn = mock_button.call_args
        self.assertTrue(kwargs_btn.get("disabled", False))

    @patch("streamlit.rerun")
    @patch("streamlit.toast")
    @patch("streamlit.success")
    @patch("streamlit.button")
    @patch("streamlit.selectbox")
    @patch("streamlit.empty")
    @patch("streamlit.columns")
    @patch("streamlit.caption")
    @patch("streamlit.markdown")
    @patch("streamlit.container")
    def test_global_voice_ui_synchronization_bug_regression(
        self,
        mock_container,
        mock_markdown,
        mock_caption,
        mock_columns,
        mock_empty,
        mock_selectbox,
        mock_button,
        mock_success,
        mock_toast,
        mock_rerun,
    ):
        """Regressão G8.9.1 / G8.9.2: Prova que Voz Ativa é sincronizada sem StreamlitAPIException pós-widget."""
        import streamlit as st
        from streamlit.errors import StreamlitAPIException
        from app.config import config
        from webui.components.channel_factory import _render_global_voice_section

        # 1. ESTADO INICIAL: config.ui["voice_name"] = "pt-BR-AntonioNeural-Male"
        orig_voice = config.ui.get("voice_name")
        config.ui["voice_name"] = "pt-BR-AntonioNeural-Male"
        st.session_state.clear()

        # Simula a proteção do Streamlit contra mutação de session_state após instanciação do widget
        widget_instantiated = False

        def selectbox_side_effect(*args, **kwargs):
            nonlocal widget_instantiated
            widget_instantiated = True
            return "en-US-BrianMultilingualNeural"

        original_setitem = st.session_state.__class__.__setitem__

        def protected_setitem(self, key, value):
            if widget_instantiated and key == "cf_global_voice_selector":
                raise StreamlitAPIException(
                    "st.session_state.cf_global_voice_selector cannot be modified after "
                    "the widget with key cf_global_voice_selector is instantiated."
                )
            return original_setitem(self, key, value)

        mock_placeholder = MagicMock()
        mock_empty.return_value = mock_placeholder
        mock_columns.return_value = [MagicMock(), MagicMock(), MagicMock()]
        mock_selectbox.side_effect = selectbox_side_effect
        mock_button.return_value = True  # Usuário clica em 'Salvar Voz Global'

        try:
            with patch.object(st.session_state.__class__, "__setitem__", protected_setitem):
                with patch.object(config, "try_save_config", return_value=True):
                    # Não deve lançar StreamlitAPIException
                    _render_global_voice_section(is_primary=True)

            # VALIDAR 1: config.ui["voice_name"] foi atualizado para Brian
            self.assertEqual(config.ui["voice_name"], "en-US-BrianMultilingualNeural")

            # VALIDAR 2: O placeholder de Voz Ativa foi atualizado para Brian
            self.assertEqual(mock_placeholder.markdown.call_count, 2)
            first_call_text = mock_placeholder.markdown.call_args_list[0][0][0]
            last_call_text = mock_placeholder.markdown.call_args_list[1][0][0]

            self.assertIn("pt-BR-AntonioNeural-Male", first_call_text)
            self.assertIn("en-US-BrianMultilingualNeural", last_call_text)
            self.assertNotIn("pt-BR-AntonioNeural-Male", last_call_text)

            # Validar que st.rerun foi acionado
            mock_rerun.assert_called_once()

            # 2. SIMULAR NOVO RERUN / RELOAD
            widget_instantiated = False
            mock_placeholder.reset_mock()
            mock_button.return_value = False  # Sem novo clique
            mock_selectbox.side_effect = None
            mock_selectbox.return_value = "en-US-BrianMultilingualNeural"

            with patch.object(st.session_state.__class__, "__setitem__", protected_setitem):
                _render_global_voice_section(is_primary=True)

            # No rerun, o placeholder é inicializado diretamente com Brian (já persistido)
            self.assertEqual(mock_placeholder.markdown.call_count, 1)
            rerun_call_text = mock_placeholder.markdown.call_args_list[0][0][0]
            self.assertIn("en-US-BrianMultilingualNeural", rerun_call_text)
            self.assertNotIn("pt-BR-AntonioNeural-Male", rerun_call_text)

            # VALIDAR 3: Seletor no rerun aponta para Brian
            _, kwargs_sb = mock_selectbox.call_args
            options = kwargs_sb["options"]
            index = kwargs_sb["index"]
            self.assertEqual(options[index], "en-US-BrianMultilingualNeural")

        finally:
            if orig_voice is not None:
                config.ui["voice_name"] = orig_voice
            st.session_state.clear()

    def test_all_three_profiles_resolve_global_voice(self):
        """7. Os perfis cadastrados continuam resolvendo a voz global da fábrica."""
        from app.config import config

        p1 = profile_manager.create_profile(name="Canal 1", niche="curiosidades", db_path=self.db_path)
        p2 = profile_manager.create_profile(name="Canal 2", niche="games", db_path=self.db_path)
        p3 = profile_manager.create_profile(name="Canal 3", niche="tech", db_path=self.db_path)

        orig = config.ui.get("voice_name")
        try:
            config.ui["voice_name"] = "en-US-BrianMultilingualNeural"
            for p in (p1, p2, p3):
                ctx = profile_manager.get_generation_profile_context(p["id"], db_path=self.db_path)
                self.assertEqual(ctx["voice_name"], "en-US-BrianMultilingualNeural")
        finally:
            if orig is not None:
                config.ui["voice_name"] = orig

    def test_legacy_profile_settings_voice_values_ignored(self):
        """8. Valores legacy salvos no profile settings não ganham precedência sobre a voz global."""
        from app.config import config

        p = profile_manager.create_profile(name="Canal Legado", niche="historia", db_path=self.db_path)
        pid = p["id"]

        # Salva voz legada no SQLite
        settings = profile_manager.get_profile_settings(pid, db_path=self.db_path)
        settings.voice.voice_name = "pt-BR-FranciscaNeural"
        profile_manager.update_profile_settings(pid, settings, db_path=self.db_path)

        orig = config.ui.get("voice_name")
        try:
            config.ui["voice_name"] = "en-US-BrianMultilingualNeural"
            ctx = profile_manager.get_generation_profile_context(pid, db_path=self.db_path)
            self.assertEqual(ctx["voice_name"], "en-US-BrianMultilingualNeural")
        finally:
            if orig is not None:
                config.ui["voice_name"] = orig

    def test_profile_context_resolves_canonical_voice_when_config_has_gender_suffix(self):
        """9. Config.ui com sufixo de gênero é normalizado para forma canônica no profile context."""
        from app.config import config

        p = profile_manager.create_profile(name="Canal Teste", niche="games", db_path=self.db_path)
        pid = p["id"]

        orig = config.ui.get("voice_name")
        try:
            config.ui["voice_name"] = "en-US-BrianMultilingualNeural-Male"
            ctx = profile_manager.get_generation_profile_context(pid, db_path=self.db_path)
            self.assertEqual(ctx["voice_name"], "en-US-BrianMultilingualNeural")

            config.ui["voice_name"] = "pt-BR-AntonioNeural-Male"
            ctx2 = profile_manager.get_generation_profile_context(pid, db_path=self.db_path)
            self.assertEqual(ctx2["voice_name"], "pt-BR-AntonioNeural")
        finally:
            if orig is not None:
                config.ui["voice_name"] = orig

    def test_all_three_profiles_resolve_homologated_voice_rate_0_8(self):
        """10. Regressão Hotfix: os 3 perfis resolvem voice_rate=0.8 sem normalização indevida."""
        from app.config import config

        p1 = profile_manager.create_profile(name="GTA Daily DEV", niche="games", db_path=self.db_path)
        p2 = profile_manager.create_profile(name="Tech Daily DEV", niche="tech", db_path=self.db_path)
        p3 = profile_manager.create_profile(name="Curiosidades DEV", niche="curiosidades", db_path=self.db_path)

        orig_rate = config.ui.get("voice_rate")
        orig_voice = config.ui.get("voice_name")
        try:
            config.ui["voice_rate"] = 0.8
            config.ui["voice_name"] = "en-US-BrianMultilingualNeural"

            for p in (p1, p2, p3):
                # 1. Contexto do perfil resolve 0.8
                ctx = profile_manager.get_generation_profile_context(p["id"], db_path=self.db_path)
                self.assertEqual(ctx["voice_rate"], 0.8)

                # 2. build_autonomous_video_params preserva 0.8
                params = autonomous_production.build_autonomous_video_params(
                    "Tema Teste", profile_id=p["id"], db_path=self.db_path
                )
                self.assertEqual(params.voice_rate, 0.8)
        finally:
            if orig_rate is not None:
                config.ui["voice_rate"] = orig_rate
            if orig_voice is not None:
                config.ui["voice_name"] = orig_voice

    def test_profile_specific_voice_rate_0_8_preserved(self):
        """11. Regressão Hotfix: profile settings com voice_rate=0.8 preservado em build_autonomous_video_params."""
        p = profile_manager.create_profile(name="Canal Custom", niche="games", db_path=self.db_path)
        pid = p["id"]

        settings = profile_manager.get_profile_settings(pid, db_path=self.db_path)
        settings.voice.voice_rate = 0.8
        profile_manager.update_profile_settings(pid, settings, db_path=self.db_path)

        params = autonomous_production.build_autonomous_video_params(
            "Tema Teste", profile_id=pid, db_path=self.db_path
        )
        self.assertEqual(params.voice_rate, 0.8)

    def test_voice_rate_fail_closed_for_corrupted_or_out_of_range_values(self):
        """12. Regressão Hotfix: valores absurdos/corrompidos (< 0.80 ou > 1.30) normalizam para 1.0 fail-closed."""
        from app.config import config
        orig_rate = config.ui.get("voice_rate")
        try:
            for bad_rate in [0.79, 0.5, 0.0, -1.0, 1.31, 2.0, "invalid"]:
                config.ui["voice_rate"] = bad_rate
                params = autonomous_production.build_autonomous_video_params("Tema Teste", db_path=self.db_path)
                self.assertEqual(params.voice_rate, 1.0)
        finally:
            if orig_rate is not None:
                config.ui["voice_rate"] = orig_rate


if __name__ == "__main__":
    unittest.main()

