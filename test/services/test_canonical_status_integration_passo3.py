"""Testes de Integração do Status Canônico Único — Passo 3 (Missão v2/status-canal-passo3).

Valida:
1. Caso Escolhas: canal com autônomo desligado + 1 post agendado.
   Live execution overview mostra channel_status='paused' e reason_code='AUTONOMOUS_DISABLED',
   enquanto execution.status/pipeline_stage preserva o estágio agendado (não quebra o grafo).
2. Fábrica pausada:
   Status 'paused' com reason_code='FACTORY_PAUSED' em Frota, Factory Live, /channels e /profiles/{id}/status.
3. Caso Quiz_Quiz: meta diária atingida (10/10 aprovadas em 24h, estoque < meta).
   Status 'ok' com reason_code='DAILY_GOAL_REACHED' em todas as rotas.
4. Estoque None (falha de leitura):
   /channels propaga ready_stock=None (nunca converte para 0) e status canônico 'attention' com 'STOCK_UNKNOWN'.
5. Prova de Fonte Única:
   Mesmo banco de teste produz status canônico IDÊNTICO em Frota, Diagnóstico, Factory Live e /channels.
"""

from __future__ import annotations

import gc
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import asgi
from app.config import config
from app.services import (
    autonomous_production,
    operator_console,
    production_diagnostics,
    profile_manager,
    safety_gate,
    scheduler,
)


class TestCanonicalStatusIntegrationPasso3(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = os.path.join(self.temp_dir.name, "test_passo3.db")
        config.app["api_key"] = ""

        scheduler.init_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        profile_manager.ensure_default_profile(self.db_path)
        operator_console.init_operator_db(self.db_path)
        safety_gate.init_safety_db(self.db_path)

        self.client = TestClient(asgi.app)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)
        gc.collect()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def _setup_profiles(self, profiles_data):
        now_iso = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            for p in profiles_data:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO content_profiles
                    (id, name, slug, niche, growth_mode, is_active, settings_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        p["id"],
                        p.get("name", p["id"]),
                        p.get("slug", p["id"]),
                        p.get("niche", "general"),
                        p.get("growth_mode", "SCALE"),
                        1 if p.get("is_active", True) else 0,
                        json.dumps(p.get("settings", {})),
                        now_iso,
                        now_iso,
                    ),
                )
                conn.execute(
                    """
                    INSERT OR REPLACE INTO publishing_channels
                    (id, profile_id, platform, display_name, is_enabled, auto_publish_authorized, created_at, updated_at)
                    VALUES (?, ?, 'youtube', ?, 1, 1, ?, ?);
                    """,
                    (
                        f"chan-{p['id']}-youtube",
                        p["id"],
                        f"YouTube {p.get('name', p['id'])}",
                        now_iso,
                        now_iso,
                    ),
                )
            conn.commit()

    def _set_profile_autonomous(self, pid: str, enabled: bool, state: str = "idle"):
        val_str = "True" if enabled else "False"
        autonomous_production.set_autonomous_setting(f"autonomous_mode_enabled:{pid}", val_str, db_path=self.db_path)
        autonomous_production.set_autonomous_setting(f"autonomous_state:{pid}", state if enabled else "disabled", db_path=self.db_path)

    def test_case_1_escolhas_autonomous_disabled_with_scheduled_post(self):
        """Caso 1: Escolhas com autônomo desligado e 1 post agendado.

        Factory Live deve mostrar channel_status='paused' e reason_code='AUTONOMOUS_DISABLED',
        mas o grafo de execução deve manter o estágio do post agendado.
        """
        self._setup_profiles([
            {
                "id": "channel-escolhas",
                "name": "Escolhas Impossíveis",
                "settings": {
                    "schedule": {"autonomous_enabled": False, "posts_per_day": 2},
                    "target_stock": 5,
                },
            }
        ])
        self._set_profile_autonomous("channel-escolhas", False)

        now = datetime.now(timezone.utc)
        sched_time = (now + timedelta(hours=2)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at, profile_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("task-sched-1", "youtube", sched_time, "ready", now.isoformat(), "channel-escolhas"),
            )
            conn.commit()

        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path):

            # Consulta direta de live execution
            live = operator_console.get_live_execution_overview(db_path=self.db_path)
            ch = next(c for c in live.get("channels", []) if c["profile_id"] == "channel-escolhas")

            # Status de saúde é canônico: 'paused'
            self.assertEqual(ch.get("channel_status"), "paused")
            self.assertEqual(ch.get("channel_reason_code"), "AUTONOMOUS_DISABLED")

            # Estágio de execução mantém o post agendado (animação do grafo não quebra)
            self.assertEqual(ch.get("status"), "SCHEDULED")
            self.assertEqual(ch.get("execution", {}).get("status"), "SCHEDULED")
            self.assertEqual(ch.get("execution", {}).get("pipeline_stage"), "SCHEDULER")

            # Consulta via API HTTP GET /api/v2/executions/live
            res = self.client.get("/api/v2/executions/live")
            self.assertEqual(res.status_code, 200)
            data = res.json().get("data", {}).get("channels", [])
            http_ch = next(c for c in data if c["profile_id"] == "channel-escolhas")
            self.assertEqual(http_ch.get("channel_status"), "paused")
            self.assertEqual(http_ch.get("channel_reason_code"), "AUTONOMOUS_DISABLED")
            self.assertEqual(http_ch.get("execution", {}).get("status"), "SCHEDULED")

    def test_case_2_factory_paused_across_all_endpoints(self):
        """Caso 2: Fábrica pausada deve refletir status 'paused' em Frota, Live, /channels e /profiles/{id}/status."""
        self._setup_profiles([
            {
                "id": "channel-active",
                "name": "Canal Ativo",
                "settings": {"schedule": {"autonomous_enabled": True}, "target_stock": 5},
            }
        ])
        self._set_profile_autonomous("channel-active", True)
        operator_console.set_factory_state("PAUSED", db_path=self.db_path)

        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path):

            # 1. Frota
            fleet = operator_console.get_fleet_summary(db_path=self.db_path)
            fleet_ch = next(c for c in fleet["channels"] if c["profile_id"] == "channel-active")
            self.assertEqual(fleet_ch["status"], "paused")
            self.assertEqual(fleet_ch["reason_code"], "FACTORY_PAUSED")

            # 2. Live execution
            live = operator_console.get_live_execution_overview(db_path=self.db_path)
            live_ch = next(c for c in live.get("channels", []) if c["profile_id"] == "channel-active")
            self.assertEqual(live_ch["channel_status"], "paused")
            self.assertEqual(live_ch["channel_reason_code"], "FACTORY_PAUSED")

            # 3. Channels Overview (GET /api/v2/channels)
            res_ch = self.client.get("/api/v2/channels")
            self.assertEqual(res_ch.status_code, 200)
            channels = res_ch.json().get("data", {}).get("channels", [])
            api_ch = next(c for c in channels if c["profile_id"] == "channel-active")
            self.assertEqual(api_ch["channel_status"], "paused")
            self.assertEqual(api_ch["channel_reason_code"], "FACTORY_PAUSED")

            # 4. Profile status (GET /api/v2/profiles/{id}/status)
            res_prof = self.client.get("/api/v2/profiles/channel-active/status")
            self.assertEqual(res_prof.status_code, 200)
            prof_data = res_prof.json().get("data", {})
            self.assertIsNotNone(prof_data.get("canonical_status"))
            self.assertEqual(prof_data["canonical_status"]["status"], "paused")
            self.assertEqual(prof_data["canonical_status"]["reason_code"], "FACTORY_PAUSED")

    def test_case_3_daily_goal_reached_quiz_quiz(self):
        """Caso 3: Canal com meta diária batida (10/10) e estoque < meta é 'ok' com reason_code DAILY_GOAL_REACHED."""
        self._setup_profiles([
            {
                "id": "quiz-quiz",
                "name": "Quiz & Curiosidades",
                "settings": {
                    "schedule": {"autonomous_enabled": True},
                    "target_stock": 10,
                    "quotas": {"max_generations_24h": 10},
                },
            }
        ])
        self._set_profile_autonomous("quiz-quiz", True)
        autonomous_production.set_max_generations_24h(10, profile_id="quiz-quiz", db_path=self.db_path)

        now = datetime.now(timezone.utc)
        recent_time = (now - timedelta(hours=2)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            for i in range(10):
                tid = f"task-approved-{i}"
                conn.execute(
                    "INSERT INTO task_profiles (task_id, profile_id, created_at) VALUES (?, ?, ?)",
                    (tid, "quiz-quiz", recent_time),
                )
                conn.execute(
                    """
                    INSERT INTO operational_events (timestamp, component, severity, event_type, task_id, message)
                    VALUES (?, 'autonomous_production', 'INFO', 'generation_approved', ?, 'Aprovado')
                    """,
                    (recent_time, tid),
                )
            conn.commit()

        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path):

            # Frota
            fleet = operator_console.get_fleet_summary(db_path=self.db_path)
            f_ch = next(c for c in fleet["channels"] if c["profile_id"] == "quiz-quiz")
            self.assertEqual(f_ch["status"], "ok")
            self.assertEqual(f_ch["reason_code"], "DAILY_GOAL_REACHED")

            # Factory Live
            live = operator_console.get_live_execution_overview(db_path=self.db_path)
            l_ch = next(c for c in live.get("channels", []) if c["profile_id"] == "quiz-quiz")
            self.assertEqual(l_ch["channel_status"], "ok")
            self.assertEqual(l_ch["channel_reason_code"], "DAILY_GOAL_REACHED")

            # Channels
            res_ch = self.client.get("/api/v2/channels")
            self.assertEqual(res_ch.status_code, 200)
            c_ch = next(c for c in res_ch.json()["data"]["channels"] if c["profile_id"] == "quiz-quiz")
            self.assertEqual(c_ch["channel_status"], "ok")
            self.assertEqual(c_ch["channel_reason_code"], "DAILY_GOAL_REACHED")

    def test_case_4_ready_stock_none_propagated_as_none_and_attention(self):
        """Caso 4: Falha na leitura de estoque pronto propaga ready_stock=None e vira 'attention' (STOCK_UNKNOWN)."""
        self._setup_profiles([
            {
                "id": "channel-stock-fail",
                "name": "Canal Falha Estoque",
                "settings": {"schedule": {"autonomous_enabled": True}, "target_stock": 5},
            }
        ])
        self._set_profile_autonomous("channel-stock-fail", True)

        with patch("app.services.operator_console.get_canonical_ready_stock", side_effect=RuntimeError("Disco I/O")), \
             patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path):

            # Overview direto
            ov = operator_console.get_profile_operations_overview(db_path=self.db_path)
            ch = next(c for c in ov if c["profile_id"] == "channel-stock-fail")
            self.assertIsNone(ch["ready_stock"], "ready_stock deve ser None quando há falha, nunca 0")
            self.assertEqual(ch["channel_status"], "attention")
            self.assertEqual(ch["channel_reason_code"], "STOCK_UNKNOWN")

            # Endpoint GET /api/v2/channels
            res = self.client.get("/api/v2/channels")
            self.assertEqual(res.status_code, 200)
            channels = res.json()["data"]["channels"]
            api_ch = next(c for c in channels if c["profile_id"] == "channel-stock-fail")
            self.assertIsNone(api_ch["ready_stock"], "Endpoint HTTP não deve transformar None em 0")
            self.assertEqual(api_ch["channel_status"], "attention")
            self.assertEqual(api_ch["channel_reason_code"], "STOCK_UNKNOWN")

    def test_case_5_single_source_of_truth_proof(self):
        """Caso 5: Prova de Fonte Única.

        Frota, Diagnóstico, Factory Live e /channels entregam EXATAMENTE o mesmo status e reason_code
        para cada canal no mesmo banco.
        """
        self._setup_profiles([
            {
                "id": "chan-paused",
                "name": "Canal Pausado",
                "settings": {"schedule": {"autonomous_enabled": False}},
            },
            {
                "id": "chan-attention",
                "name": "Canal Atenção",
                "settings": {"schedule": {"autonomous_enabled": True}, "target_stock": 10},
            },
        ])
        self._set_profile_autonomous("chan-paused", False)
        self._set_profile_autonomous("chan-attention", True)

        now = datetime.now(timezone.utc)
        recent = (now - timedelta(hours=1)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO operational_events (timestamp, component, severity, event_type, task_id, message)
                VALUES (?, 'autonomous_production', 'INFO', 'generation_started', 't-att-1', 'Geração ativa')
                """,
                (recent,),
            )
            conn.execute(
                "INSERT INTO task_profiles (task_id, profile_id, created_at) VALUES ('t-att-1', 'chan-attention', ?)",
                (recent,),
            )
            conn.commit()

        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path):

            fleet = operator_console.get_fleet_summary(db_path=self.db_path)
            diag = production_diagnostics.get_diagnostics_overview(db_path=self.db_path)
            live = operator_console.get_live_execution_overview(db_path=self.db_path)
            res_ch = self.client.get("/api/v2/channels")
            self.assertEqual(res_ch.status_code, 200)
            ch_list = res_ch.json()["data"]["channels"]

            for pid in ["chan-paused", "chan-attention"]:
                f_item = next(c for c in fleet["channels"] if c["profile_id"] == pid)
                d_item = next(c for c in diag["channels"] if c["profile_id"] == pid)
                l_item = next(c for c in live.get("channels", []) if c["profile_id"] == pid)
                c_item = next(c for c in ch_list if c["profile_id"] == pid)

                # Frota == Diagnóstico == Factory Live == /channels
                self.assertEqual(
                    f_item["status"],
                    d_item["status"],
                    f"Divergência entre Frota e Diagnóstico para {pid}",
                )
                self.assertEqual(
                    f_item["status"],
                    l_item["channel_status"],
                    f"Divergência entre Frota e Factory Live para {pid}",
                )
                self.assertEqual(
                    f_item["status"],
                    c_item["channel_status"],
                    f"Divergência entre Frota e /channels para {pid}",
                )

                # Reason codes também devem coincidir
                self.assertEqual(f_item["reason_code"], d_item["reason_code"])
                self.assertEqual(f_item["reason_code"], l_item["channel_reason_code"])
                self.assertEqual(f_item["reason_code"], c_item["channel_reason_code"])

    def test_case_6_n_plus_one_prevention_live_execution_overview(self):
        """Caso 6: Prevenção de N+1 em Live Execution.

        Uma chamada a get_live_execution_overview com 3 canais deve chamar
        get_fleet_summary EXATAMENTE 1 vez (zero chamadas redundantes dentro do loop).
        """
        self._setup_profiles([
            {"id": "chan-1", "name": "Canal 1", "settings": {"schedule": {"autonomous_enabled": True}}},
            {"id": "chan-2", "name": "Canal 2", "settings": {"schedule": {"autonomous_enabled": True}}},
            {"id": "chan-3", "name": "Canal 3", "settings": {"schedule": {"autonomous_enabled": True}}},
        ])

        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path), \
             patch.object(operator_console, "get_fleet_summary", wraps=operator_console.get_fleet_summary) as mock_fleet:

            overview = operator_console.get_live_execution_overview(db_path=self.db_path)
            channels = overview.get("channels", [])
            self.assertGreaterEqual(len(channels), 3)

            # Prova matemática de ausência de N+1
            self.assertEqual(
                mock_fleet.call_count,
                1,
                f"get_fleet_summary deveria ter sido chamado 1 vez, mas foi chamado {mock_fleet.call_count} vezes (N+1 detectado)",
            )

    def test_case_7_n_plus_one_prevention_profile_operations_overview(self):
        """Caso 7: Prevenção de N+1 em Profile Operations Overview.

        Uma chamada a get_profile_operations_overview com 3 canais deve chamar
        get_fleet_summary EXATAMENTE 1 vez.
        """
        self._setup_profiles([
            {"id": "chan-1", "name": "Canal 1", "settings": {"schedule": {"autonomous_enabled": True}}},
            {"id": "chan-2", "name": "Canal 2", "settings": {"schedule": {"autonomous_enabled": True}}},
            {"id": "chan-3", "name": "Canal 3", "settings": {"schedule": {"autonomous_enabled": True}}},
        ])

        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path), \
             patch.object(operator_console, "get_fleet_summary", wraps=operator_console.get_fleet_summary) as mock_fleet:

            overview = operator_console.get_profile_operations_overview(db_path=self.db_path)
            self.assertGreaterEqual(len(overview), 3)

            # Prova matemática de ausência de N+1
            self.assertEqual(
                mock_fleet.call_count,
                1,
                f"get_fleet_summary deveria ter sido chamado 1 vez, mas foi chamado {mock_fleet.call_count} vezes",
            )
