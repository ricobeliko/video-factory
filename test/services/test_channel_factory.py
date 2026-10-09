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
        """B. settings_json vazio ou ausente mantém defaults e comportamento legado."""
        p = profile_manager.create_profile(name="Canal Antigo", niche="curiosidades", db_path=self.db_path)
        pid = p["id"]

        settings = profile_manager.get_profile_settings(pid, db_path=self.db_path)
        self.assertEqual(settings.schema_version, 1)
        self.assertEqual(settings.automation.autonomous_enabled, False)
        self.assertTrue(settings.visual.flow_enabled)
        self.assertEqual(settings.visual.flow_scene_count, 5)

        ctx = profile_manager.get_generation_profile_context(pid, db_path=self.db_path)
        self.assertEqual(ctx["profile_id"], pid)
        self.assertEqual(ctx["niche"], "curiosidades")
        self.assertEqual(ctx["voice_name"], "pt-BR-FranciscaNeural")
        self.assertEqual(ctx["visual_director_enabled"], True)
        self.assertEqual(ctx["flow_enabled"], True)

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

        # Resiliência a entradas vazias
        empty_loaded = profile_manager.ChannelWorkspaceSettings.from_json("{}")
        self.assertEqual(empty_loaded.schema_version, 1)
        self.assertEqual(empty_loaded.automation.autonomous_enabled, False)

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


if __name__ == "__main__":
    unittest.main()
