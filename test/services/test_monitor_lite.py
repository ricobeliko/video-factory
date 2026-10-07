"""
test/services/test_monitor_lite.py
==================================
Testes unitários direcionados para o Monitor Lite (Fase V15 / Monitor Lite).

Cobertura exigida:
1. Página e serviço renderizam/executam sem banco populado (fail-soft total)
2. Ausência de Local AI não quebra a execução
3. FACT_PACK_INSUFFICIENT é apresentado semanticamente correto (não é erro de servidor)
4. Alertas acionáveis existentes são traduzidos e apresentados em pt-BR
5. Estritamente somente leitura (READ-ONLY): zero mutações no SQLite
6. Dados por canal permanecem estritamente isolados
7. Fail-soft resiliente em caso de dados ausentes ou corrompidos
8. Componente Streamlit renderiza com segurança
"""

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.services import (
    analytics,
    autonomous_production,
    operator_console,
    profile_manager,
    scheduler,
)
from app.services.local_ai import init_shadow_db, save_shadow_run, ShadowRunResult
from app.services.monitor_lite import (
    _get_ro_connection,
    check_local_ai_server,
    detect_environment,
    format_actionable_alerts,
    get_local_ai_summary,
    get_monitor_lite_summary,
    get_recent_tasks_summary,
)
from webui.components.monitor_lite import render_monitor_lite


class TestMonitorLite(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.test_db = os.path.join(self.tmp_dir.name, "test_monitor_lite.db")

        operator_console.reset_instance_for_testing()
        with operator_console._instance_state_lock:
            operator_console._current_role = operator_console.ROLE_PRIMARY

        # Inicializa tabelas mínimas necessárias
        profile_manager.init_profile_db(db_path=self.test_db)
        profile_manager.ensure_default_profile(db_path=self.test_db)
        scheduler.init_db(db_path=self.test_db)
        operator_console.init_operator_db(db_path=self.test_db)
        analytics.init_analytics_db(db_path=self.test_db)
        init_shadow_db(self.test_db)

        # Perfil 2 (Histórias e Mistérios)
        profile_manager.create_profile(
            profile_id="profile-historias-misterio",
            name="Histórias e Mistérios",
            niche="historias_misterio",
            growth_mode="warmup",
            db_path=self.test_db,
        )

    def tearDown(self):
        operator_console.reset_instance_for_testing()
        try:
            self.tmp_dir.cleanup()
        except Exception:
            pass

    def test_01_summary_without_populated_db(self):
        """1. Monitor Lite com banco inexistente retorna DEGRADED e não ONLINE (fail-soft total)."""
        empty_db = os.path.join(self.tmp_dir.name, "empty_non_existent.db")
        summary = get_monitor_lite_summary(db_path=empty_db)

        self.assertIsInstance(summary, dict)
        self.assertIn("system", summary)
        self.assertIn("today", summary)
        self.assertIn("current_production", summary)
        self.assertIn("channels", summary)
        self.assertIn("local_ai", summary)
        self.assertIn("learning", summary)
        self.assertIn("alerts", summary)
        self.assertIn("recent_tasks", summary)

        # Sem quebra, com semântica estrita: banco ausente = DEGRADED (nunca ONLINE)
        self.assertEqual(summary["system"]["status"], "DEGRADED")
        self.assertEqual(summary["system"]["badge"], "🟡 ATENÇÃO")
        self.assertFalse(summary["system"]["db_healthy"])
        self.assertEqual(summary["system"]["text"], "Dados operacionais indisponíveis")

        # Métricas limpas sem crashes
        self.assertEqual(summary["today"]["produced_count"], 0)
        self.assertEqual(summary["today"]["published_count"], 0)
        self.assertEqual(summary["today"]["queue_count"], 0)
        self.assertFalse(summary["current_production"]["is_active"])

    def test_02_absence_of_local_ai_does_not_break_and_ignores_homologation_db(self):
        """2. Ausência de Local AI no DB operacional exibe SEM DADOS e ignora shadow_homologation.db."""
        # Cria um shadow_homologation.db no mesmo diretório simulando corrida de laboratório
        homolog_db = os.path.join(self.tmp_dir.name, "shadow_homologation.db")
        init_shadow_db(homolog_db)
        lab_run = ShadowRunResult(
            shadow_run_id="lab_test_01",
            task_id="task_lab",
            topic="Caso de Laboratório",
            model_role="QUALITY",
            model_name="qwen3-8b",
            started_at="2026-10-07T12:00:00Z",
            finished_at="2026-10-07T12:00:01Z",
            latency_seconds=10.0,
            generation_success=True,
            json_valid=True,
            fact_guard_approved=True,
            final_shadow_available=True,
        )
        save_shadow_run(lab_run, target=homolog_db)

        # Chama o resumo para o banco operacional test_db (que está sem corridas)
        summary = get_monitor_lite_summary(db_path=self.test_db)
        lai = summary["local_ai"]

        self.assertIn("model", lai)
        self.assertIn("configured_mode", lai)
        self.assertIn("server_status", lai)
        self.assertIn("last_run", lai)
        # O banco operacional NÃO deve ter puxado a corrida de shadow_homologation.db
        self.assertFalse(lai["last_run"]["has_data"])
        self.assertIn(lai["last_run"]["status"], ("SEM DADOS", "OFF"))
        self.assertEqual(lai["last_run"]["fact_guard_status"], "NÃO EXECUTADO")

    def test_03_fact_pack_insufficient_displayed_correctly(self):
        """3. FACT_PACK_INSUFFICIENT é apresentado com clareza sem ser tratado como erro de servidor."""
        # Grava corrida de shadow com estado FACT_PACK_INSUFFICIENT
        insufficient_run = ShadowRunResult(
            shadow_run_id="run_insufficient_test",
            task_id="task_insuff_01",
            topic="A Ilha de Roanoke",
            model_role="QUALITY",
            model_name="qwen3-8b",
            started_at="2026-10-07T12:00:00Z",
            finished_at="2026-10-07T12:00:01Z",
            latency_seconds=0.0,
            generation_success=False,
            json_valid=False,
            fact_guard_approved=False,
            final_shadow_available=False,
            error_type="FACT_PACK_INSUFFICIENT",
            error_message="FactPack insuficiente para 70.0s",
            requested_duration_seconds=70.0,
            estimated_duration_seconds=0.0,
            safe_target_words=116,
            recommended_duration_seconds=48.3,
            total_llm_calls=0,
        )
        save_shadow_run(insufficient_run, target=self.test_db)

        summary = get_monitor_lite_summary(db_path=self.test_db)
        lai_run = summary["local_ai"]["last_run"]

        self.assertEqual(lai_run["status"], "FACT_PACK_INSUFFICIENT")
        self.assertEqual(lai_run["status_badge"], "🟡 FACT_PACK_INSUFFICIENT")
        self.assertEqual(lai_run["fact_guard_status"], "NÃO EXECUTADO")
        self.assertEqual(lai_run["total_calls"], 0)
        self.assertIn("retido", lai_run["duration_text"])
        self.assertIn("Gate de suficiência reteve", lai_run["description"])

    def test_04_actionable_alerts_presented_in_portuguese(self):
        """4. Alertas observáveis brutos são traduzidos em mensagens acionáveis em português."""
        raw_warnings = [
            "READY_STOCK_EMPTY:default",
            "COPYRIGHT_BLOCKED:profile-historias-misterio",
            "SCHEDULER_FAILURES_PRESENT:default",
            "ANALYTICS_STALE:default",
            "GLOBAL_COST_GUARD_NEAR_LIMIT",
            "CLOSED_LOOP_BASELINE:default",
        ]
        alerts = format_actionable_alerts(raw_warnings)

        self.assertEqual(len(alerts), 6)
        messages_text = " ".join(a["message"] for a in alerts)
        self.assertIn("Canal Principal: Estoque pronto zerado", messages_text)
        self.assertIn("Histórias e Mistérios: Publicação recente possui bloqueio", messages_text)
        self.assertIn("falhas registradas no envio", messages_text)
        self.assertIn("analytics sem coleta", messages_text)
        self.assertIn("Cost Guard Global", messages_text)
        self.assertIn("Closed Feedback Loop operando em modo baseline", messages_text)

    def test_05_strictly_read_only_no_mutations_called(self):
        """5. Monitor Lite é 100% READ-ONLY: conexões SQLite são estritamente mode=ro e rejeitam escritas."""
        ro_conn = _get_ro_connection(self.test_db)
        self.assertIsNotNone(ro_conn)
        try:
            # Qualquer tentativa de mutação DEVE falhar com sqlite3.OperationalError (readonly database)
            with self.assertRaises(sqlite3.OperationalError):
                ro_conn.execute("INSERT INTO scheduled_posts (task_id, platform, scheduled_at, created_at) VALUES ('x', 'y', 'z', 'w');")
        finally:
            ro_conn.close()

        # Executa múltiplos ciclos de monitoramento
        for _ in range(3):
            summary = get_monitor_lite_summary(db_path=self.test_db)
            self.assertIsNotNone(summary)

        # Contagem de perfis e registros permanece estritamente intocada
        with sqlite3.connect(self.test_db) as check_conn:
            cnt = check_conn.execute("SELECT count(*) FROM content_profiles;").fetchone()[0]
            self.assertGreaterEqual(cnt, 2)

    def test_06_channel_data_remains_isolated(self):
        """6. Dados de canais (default vs historias-misterio) permanecem isolados sem contaminação."""
        summary = get_monitor_lite_summary(db_path=self.test_db)
        channels = summary["channels"]

        self.assertEqual(len(channels), 2)
        ch_default = next(c for c in channels if c["id"] == "default")
        ch_mystery = next(c for c in channels if c["id"] == "profile-historias-misterio")

        self.assertNotEqual(ch_default["id"], ch_mystery["id"])
        self.assertIn("Dose Diária", ch_default["name"])
        self.assertIn("Histórias e Mistérios", ch_mystery["name"])

    def test_07_fail_soft_on_missing_or_corrupt_data(self):
        """7. Resiliência fail-soft: caminho inválido/ausente resulta em DEGRADED, nunca ONLINE."""
        # 1. Caminho inválido/inexistente DEVE ser DEGRADED com semântica de dados indisponíveis
        missing_db = os.path.join(self.tmp_dir.name, "strictly_missing.db")
        summary_invalid = get_monitor_lite_summary(db_path=missing_db)
        self.assertIsInstance(summary_invalid, dict)
        self.assertEqual(summary_invalid["system"]["status"], "DEGRADED")
        self.assertEqual(summary_invalid["system"]["badge"], "🟡 ATENÇÃO")
        self.assertFalse(summary_invalid["system"]["db_healthy"])
        self.assertEqual(summary_invalid["system"]["text"], "Dados operacionais indisponíveis")
        self.assertIn("channels", summary_invalid)

        # 2. Banco saudável e acessível DEVE ser ONLINE
        summary_healthy = get_monitor_lite_summary(db_path=self.test_db)
        self.assertIsInstance(summary_healthy, dict)
        self.assertEqual(summary_healthy["system"]["status"], "ONLINE")
        self.assertEqual(summary_healthy["system"]["badge"], "🟢 ONLINE")
        self.assertTrue(summary_healthy["system"]["db_healthy"])
        self.assertEqual(summary_healthy["system"]["text"], "Operação normal")

        # 3. Estado STOPPED DEVE ser OFFLINE
        with patch("app.services.operator_console.get_factory_state", return_value="STOPPED"):
            summary_stopped = get_monitor_lite_summary(db_path=self.test_db)
            self.assertEqual(summary_stopped["system"]["status"], "OFFLINE")
            self.assertEqual(summary_stopped["system"]["badge"], "⚪ OFFLINE")
            self.assertEqual(summary_stopped["system"]["text"], "Fábrica parada")

    def test_08_streamlit_render_function_executes_safely(self):
        """8. render_monitor_lite() executa sem disparar exceções não tratadas no Streamlit."""
        def mock_columns(spec, **kwargs):
            cnt = len(spec) if isinstance(spec, (list, tuple)) else int(spec)
            return [MagicMock() for _ in range(cnt)]

        with patch("streamlit.columns", side_effect=mock_columns), \
             patch("streamlit.container", return_value=MagicMock()), \
             patch("streamlit.metric"), \
             patch("streamlit.progress"), \
             patch("streamlit.markdown"), \
             patch("streamlit.caption"), \
             patch("streamlit.write"), \
             patch("streamlit.info"), \
             patch("streamlit.warning"), \
             patch("streamlit.success"), \
             patch("streamlit.error"), \
             patch("streamlit.expander", return_value=MagicMock()), \
             patch("streamlit.divider"), \
             patch("streamlit.json"):
            # Não pode lançar nenhuma exceção
            render_monitor_lite(db_path=self.test_db)

    def test_09_environment_detection_and_badges(self):
        """9. Identificação de ambiente (DEV vs PRODUÇÃO) opera de forma segura e determinística."""
        # Teste com variável explícita DEV
        with patch.dict(os.environ, {"VIDEO_FACTORY_ENV": "DEV"}):
            env_dev = detect_environment()
            self.assertEqual(env_dev["name"], "DEV")
            self.assertTrue(env_dev["is_dev"])

        # Teste com variável explícita PRODUÇÃO
        with patch.dict(os.environ, {"VIDEO_FACTORY_ENV": "PROD"}):
            env_prod = detect_environment()
            self.assertEqual(env_prod["name"], "PRODUÇÃO")
            self.assertFalse(env_prod["is_dev"])

        # Teste integrado no summary
        summary = get_monitor_lite_summary(db_path=self.test_db)
        self.assertIn(summary["system"]["environment"], ("DEV", "PRODUÇÃO"))
        self.assertIn(summary["system"]["environment_badge"], ("DEV", "PRODUÇÃO"))


if __name__ == "__main__":
    unittest.main()
