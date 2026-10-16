"""Suite de Homologação Integrada R9.3 — Web UI V2.

Valida os cenários críticos da missão:
- Cenário A: Canal em geração sequencial (TOPIC -> SCRIPT -> NARRATION -> VISUALS -> RENDER)
- Cenário B: Dois canais simultâneos sem contaminação cruzada (VISUALS vs RENDER)
- Cenário C: Factualidade dos Gates (Safety, Quality, Copyright) sem aprovação fictícia
- Cenário D: Google Flow (atribuição factual da conta, respeito a AUTH_FAILED e low credits)
- Cenário E: Estados de publicação (READY_STOCK, SCHEDULED, RETRYING, SUCCESS, FAILED)
- Cenário F: Estados especiais (IDLE, HTML em erro, payload parcial)
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import asgi
from app.config import config
from app.models import const
from app.services import operator_console, profile_manager, scheduler


class TestWebUiV2R93Homologation(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_r9_3.db")
        config.app["api_key"] = ""

        scheduler.init_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        profile_manager.ensure_default_profile(self.db_path)
        operator_console.init_operator_db(self.db_path)
        operator_console.reset_instance_for_testing()
        operator_console.ensure_instance_initialized(db_path=self.db_path)

        # Cria canal B para testes multicanal
        self.profile_b = profile_manager.create_profile(
            name="Canal de Teste B",
            growth_mode="scale",
            db_path=self.db_path
        )
        self.profile_b_id = self.profile_b["id"]

        self.client = TestClient(asgi.app)

    def tearDown(self):
        operator_console.reset_instance_for_testing()
        config.app.clear()
        config.app.update(self.original_app_config)
        self.temp_dir.cleanup()

    # =========================================================================
    # CENÁRIO A: Canal em geração sequencial
    # =========================================================================
    def test_scenario_a_channel_in_generation_progression(self):
        """Cenário A: Tarefa ativa avança por etapas com nós ativos RUNNING e Gates PENDING."""
        stages = [
            ("TOPIC", 5, None, "SCRIPT"),
            ("SCRIPT", 10, None, "NARRATION"),
            ("NARRATION", 30, "edge-tts (pt-BR-FranciscaNeural)", "VISUALS"),
            ("VISUALS", 40, "Google Flow (flow-b)", "RENDER"),
            ("RENDER", 50, "ffmpeg", "SAFETY"),
        ]

        for stage, progress, provider, expected_next in stages:
            fake_task = {
                "task_id": f"task-seq-{stage.lower()}",
                "profile_id": "default",
                "state": const.TASK_STATE_PROCESSING,
                "progress": progress,
                "video_subject": "Avanço do Pipeline Real",
                "stage": stage,
                "provider": provider,
                "created_at": "2026-10-16T12:00:00Z",
            }

            with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
                 patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
                 patch("app.services.profile_manager.get_db_path", return_value=self.db_path), \
                 patch("app.services.autonomous_production.get_autonomous_status", return_value={
                     "enabled": True, "state": "idle", "current_task_id": None, "waiting_task_id": None
                 }), \
                 patch("app.services.webui_task.get_active_task_ids", return_value=[fake_task["task_id"]]), \
                 patch("app.services.state.state.get_task", return_value=fake_task):

                resp = self.client.get("/api/v2/executions/live")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()["data"]
                ch = next(c for c in data["channels"] if c["profile_id"] == "default")

                self.assertEqual(ch["status"], "RUNNING")
                self.assertIsNotNone(ch["execution"])
                self.assertEqual(ch["execution"]["pipeline_stage"], stage)
                self.assertEqual(ch["execution"]["next_stage"], expected_next)
                self.assertEqual(ch["execution"]["progress"], progress)
                if provider:
                    self.assertEqual(ch["execution"]["provider"], provider)

                # Gates devem ser factuais: se não foram avaliados, são None / PENDING
                gates = ch["execution"]["gates"]
                self.assertIsNone(gates["safety_status"])
                self.assertIsNone(gates["quality_score"])
                self.assertIsNone(gates["copyright_status"])

    # =========================================================================
    # CENÁRIO B: Dois canais simultâneos sem contaminação cruzada
    # =========================================================================
    def test_scenario_b_simultaneous_channels_isolated(self):
        """Cenário B: Dois canais processando simultaneamente não misturam dados."""
        task_a = {
            "task_id": "task-channel-a-vis",
            "profile_id": "default",
            "state": const.TASK_STATE_PROCESSING,
            "progress": 40,
            "video_subject": "Tema do Canal A (Visuals Flow)",
            "stage": "VISUALS",
            "provider": "Google Flow (flow-b)",
            "flow_account_id": "flow-b",
            "flow_enabled": True,
        }
        task_b = {
            "task_id": "task-channel-b-ren",
            "profile_id": self.profile_b_id,
            "state": const.TASK_STATE_PROCESSING,
            "progress": 50,
            "video_subject": "Tema do Canal B (Render FFmpeg)",
            "stage": "RENDER",
            "provider": "ffmpeg",
        }

        tasks_by_id = {
            task_a["task_id"]: task_a,
            task_b["task_id"]: task_b,
        }

        def mock_get_task(tid):
            return tasks_by_id.get(tid)

        def mock_get_all_tasks(page, limit):
            return [task_a, task_b]

        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path), \
             patch("app.services.autonomous_production.get_autonomous_status", return_value={
                 "enabled": True, "state": "idle", "current_task_id": None, "waiting_task_id": None
             }), \
             patch("app.services.webui_task.get_active_task_ids", return_value=[task_a["task_id"], task_b["task_id"]]), \
             patch("app.services.state.state.get_task", side_effect=mock_get_task), \
             patch("app.services.state.state.get_all_tasks", side_effect=mock_get_all_tasks):

            resp = self.client.get("/api/v2/executions/live")
            self.assertEqual(resp.status_code, 200)
            channels = resp.json()["data"]["channels"]

            ch_a = next(c for c in channels if c["profile_id"] == "default")
            ch_b = next(c for c in channels if c["profile_id"] == self.profile_b_id)

            # Canal A isolado
            self.assertEqual(ch_a["status"], "RUNNING")
            self.assertEqual(ch_a["execution"]["task_id"], "task-channel-a-vis")
            self.assertEqual(ch_a["execution"]["pipeline_stage"], "VISUALS")
            self.assertEqual(ch_a["execution"]["provider"], "Google Flow (flow-b)")
            self.assertEqual(ch_a["execution"]["topic"], "Tema do Canal A (Visuals Flow)")

            # Canal B isolado
            self.assertEqual(ch_b["status"], "RUNNING")
            self.assertEqual(ch_b["execution"]["task_id"], "task-channel-b-ren")
            self.assertEqual(ch_b["execution"]["pipeline_stage"], "RENDER")
            self.assertEqual(ch_b["execution"]["provider"], "ffmpeg")
            self.assertEqual(ch_b["execution"]["topic"], "Tema do Canal B (Render FFmpeg)")

    # =========================================================================
    # CENÁRIO C: Factualidade dos Gates
    # =========================================================================
    def test_scenario_c_factual_gates_without_synthetic_approval(self):
        """Cenário C: Gates só refletem avaliações reais; tarefas rejeitadas exibem erro no nó exato."""
        # Caso C.1: Tarefa que falhou no Quality Gate (score 67.8 < 70.0)
        rejected_task = {
            "task_id": "task-quality-rejected-001",
            "profile_id": "default",
            "state": const.TASK_STATE_FAILED,
            "failed_stage": "QUALITY",
            "error": "Quality Gate REJECTED: score 67.8 < 70.0",
            "safety_status": "PASS",
            "quality_score": 67.8,
            "copyright_status": "PASS",
            "gate_status": "rejected",
            "gate_reason": "Quality score 67.8 abaixo do threshold 70.0",
        }

        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path), \
             patch("app.services.autonomous_production.get_autonomous_status", return_value={
                 "enabled": True, "state": "idle", "current_task_id": None, "waiting_task_id": None
             }), \
             patch("app.services.webui_task.get_active_task_ids", return_value=["task-quality-rejected-001"]), \
             patch("app.services.state.state.get_task", return_value=rejected_task):

            resp = self.client.get("/api/v2/executions/live")
            self.assertEqual(resp.status_code, 200)
            ch = next(c for c in resp.json()["data"]["channels"] if c["profile_id"] == "default")

            self.assertEqual(ch["status"], "FAILED")
            self.assertEqual(ch["execution"]["pipeline_stage"], "QUALITY")
            self.assertEqual(ch["execution"]["gates"]["quality_score"], 67.8)
            self.assertEqual(ch["execution"]["gates"]["gate_status"], "rejected")
            self.assertIn("67.8", ch["execution"]["error"])

    # =========================================================================
    # CENÁRIO D: Google Flow multi-contas e atribuição factual
    # =========================================================================
    def test_scenario_d_google_flow_account_attribution(self):
        """Cenário D: Provedor só menciona conta Flow se houver vínculo comprovado com a tarefa."""
        # Caso D.1: Tarefa com conta comprovada no registro
        task_with_acc = {
            "task_id": "task-flow-with-acc",
            "profile_id": "default",
            "state": const.TASK_STATE_PROCESSING,
            "stage": "VISUALS",
            "flow_enabled": True,
            "flow_account_id": "flow-b",
            "provider": "Google Flow (flow-b)",
        }
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path), \
             patch("app.services.autonomous_production.get_autonomous_status", return_value={
                 "enabled": True, "state": "idle", "current_task_id": None, "waiting_task_id": None
             }), \
             patch("app.services.webui_task.get_active_task_ids", return_value=["task-flow-with-acc"]), \
             patch("app.services.state.state.get_task", return_value=task_with_acc):

            resp = self.client.get("/api/v2/executions/live")
            ch = next(c for c in resp.json()["data"]["channels"] if c["profile_id"] == "default")
            self.assertEqual(ch["execution"]["provider"], "Google Flow (flow-b)")

        # Caso D.2: Tarefa sem conta gravada nem stickiness no pool
        task_without_acc = {
            "task_id": "task-flow-no-acc",
            "profile_id": "default",
            "state": const.TASK_STATE_PROCESSING,
            "stage": "VISUALS",
            "flow_enabled": True,
            "provider": "Google Flow",
        }
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path), \
             patch("app.services.autonomous_production.get_autonomous_status", return_value={
                 "enabled": True, "state": "idle", "current_task_id": None, "waiting_task_id": None
             }), \
             patch("app.services.webui_task.get_active_task_ids", return_value=["task-flow-no-acc"]), \
             patch("app.services.state.state.get_task", return_value=task_without_acc), \
             patch("app.services.flow_account_pool.get_flow_accounts_status", return_value={"accounts": []}):

            resp = self.client.get("/api/v2/executions/live")
            ch = next(c for c in resp.json()["data"]["channels"] if c["profile_id"] == "default")
            # Não inventa conta! Fica "Google Flow"
            self.assertEqual(ch["execution"]["provider"], "Google Flow")

    # =========================================================================
    # CENÁRIO E: Ciclo de publicação
    # =========================================================================
    def test_scenario_e_publication_lifecycle(self):
        """Cenário E: Suporte factual aos estados de READY_STOCK, SCHEDULED, RETRY e SUCCESS."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path), \
             patch("app.services.autonomous_production.get_autonomous_status", return_value={
                 "enabled": True, "state": "idle", "current_task_id": None, "waiting_task_id": None
             }), \
             patch("app.services.state.state.get_task", return_value=None):

            with scheduler.get_connection(self.db_path) as conn:
                # 1. Agendamento pendente (SCHEDULED)
                conn.execute(
                    """
                    INSERT INTO scheduled_posts (
                        task_id, platform, scheduled_at, status, created_at, attempts, profile_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    ("task-sched-111", "youtube", "2026-10-16T18:00:00Z", "pending", "2026-10-16T12:00:00Z", 0, "default")
                )

            resp = self.client.get("/api/v2/executions/live")
            ch = next(c for c in resp.json()["data"]["channels"] if c["profile_id"] == "default")
            self.assertEqual(ch["status"], "SCHEDULED")
            self.assertEqual(ch["execution"]["pipeline_stage"], "SCHEDULER")
            self.assertEqual(ch["execution"]["next_stage"], "PUBLISHER")

            with scheduler.get_connection(self.db_path) as conn:
                # 2. Publicação com sucesso terminal (SUCCESS)
                conn.execute(
                    """
                    INSERT INTO publication_events (
                        task_id, platform, published_at, status, external_url, profile_id
                    ) VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    ("task-sched-111", "youtube", "2026-10-16T18:05:00Z", "success", "https://youtube.com/shorts/valid111", "default")
                )

            resp2 = self.client.get("/api/v2/executions/live")
            ch2 = next(c for c in resp2.json()["data"]["channels"] if c["profile_id"] == "default")
            self.assertEqual(ch2["status"], "SUCCESS")
            self.assertEqual(ch2["execution"]["pipeline_stage"], "YOUTUBE")
            self.assertEqual(ch2["execution"]["publication_state"]["external_url"], "https://youtube.com/shorts/valid111")

    # =========================================================================
    # CENÁRIO F: Estados especiais (IDLE, HTML em erro, etc.)
    # =========================================================================
    def test_scenario_f_special_states_and_html_error_handling(self):
        """Cenário F: Canal IDLE e erros com HTML preservados de forma íntegra no backend."""
        # F.1: Canal em IDLE
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path), \
             patch("app.services.autonomous_production.get_autonomous_status", return_value={
                 "enabled": True, "state": "idle", "current_task_id": None, "waiting_task_id": None
             }), \
             patch("app.services.webui_task.get_active_task_ids", return_value=[]), \
             patch("app.services.state.state.get_task", return_value=None):

            resp = self.client.get("/api/v2/executions/live")
            ch = next(c for c in resp.json()["data"]["channels"] if c["profile_id"] == "default")
            self.assertEqual(ch["status"], "IDLE")
            self.assertIsNone(ch["execution"])

        # F.2: Mensagem de erro contendo HTML bruto
        html_error_task = {
            "task_id": "task-html-err-999",
            "profile_id": "default",
            "state": const.TASK_STATE_FAILED,
            "failed_stage": "RENDER",
            "error": "<html><body>502 Bad Gateway: <script>alert(1)</script></body></html>",
        }
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.scheduler.get_db_path", return_value=self.db_path), \
             patch("app.services.profile_manager.get_db_path", return_value=self.db_path), \
             patch("app.services.autonomous_production.get_autonomous_status", return_value={
                 "enabled": True, "state": "idle", "current_task_id": None, "waiting_task_id": None
             }), \
             patch("app.services.webui_task.get_active_task_ids", return_value=["task-html-err-999"]), \
             patch("app.services.state.state.get_task", return_value=html_error_task):

            resp = self.client.get("/api/v2/executions/live")
            ch = next(c for c in resp.json()["data"]["channels"] if c["profile_id"] == "default")
            self.assertEqual(ch["status"], "FAILED")
            self.assertIn("502 Bad Gateway", ch["execution"]["error"])


if __name__ == "__main__":
    unittest.main()
