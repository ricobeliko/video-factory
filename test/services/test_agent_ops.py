"""Targeted tests for Agent Ops telemetry service and endpoint (Agent Ops V1.1).

Covers:
1. Root resolution order (AGENT_BRIDGE_ROOT env var, sibling directory, fallback);
2. Graceful disconnected payload when AgentBridge does not exist;
3. Sanitized state reading with factually derived elapsed time and abbreviated conv_id;
4. Sanitized live.ndjson projection (stripping prompts, secrets, absolute paths);
5. Normalization of actors (ARCHITECT, EXECUTOR, VALIDATOR, HUMAN, SYSTEM);
6. OpenAI Architect offline notice ('OpenAI Architect será conectado na V2');
7. BLOCKED_HUMAN status highlight detection;
8. Fast-path FastAPI controller integration test.
"""

import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.services import agent_ops


class TestAgentOpsService(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.bridge_dir = os.path.join(self.test_dir, "AgentBridge")
        os.makedirs(self.bridge_dir, exist_ok=True)
        os.makedirs(os.path.join(self.bridge_dir, "logs"), exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    # 1. Root resolution via AGENT_BRIDGE_ROOT env var
    def test_resolve_agent_bridge_root_env_priority(self):
        with patch.dict(os.environ, {"AGENT_BRIDGE_ROOT": self.bridge_dir}):
            resolved = agent_ops.resolve_agent_bridge_root()
            self.assertEqual(os.path.abspath(resolved), os.path.abspath(self.bridge_dir))

    # 2. Root resolution via sibling directory fallback
    def test_resolve_agent_bridge_root_sibling_fallback(self):
        # Fake project root inside self.test_dir/MoneyPrinterTurbo
        fake_mpt = os.path.join(self.test_dir, "MoneyPrinterTurbo")
        os.makedirs(fake_mpt, exist_ok=True)

        with patch.dict(os.environ, {}, clear=True):
            if "AGENT_BRIDGE_ROOT" in os.environ:
                del os.environ["AGENT_BRIDGE_ROOT"]
            with patch("app.utils.utils.root_dir", return_value=fake_mpt):
                resolved = agent_ops.resolve_agent_bridge_root()
                self.assertEqual(os.path.abspath(resolved), os.path.abspath(self.bridge_dir))

    # 3. Disconnected payload when AgentBridge is missing
    def test_get_agent_ops_snapshot_disconnected(self):
        non_existent = os.path.join(self.test_dir, "DoesNotExist")
        snapshot = agent_ops.get_agent_ops_snapshot(bridge_root=non_existent)

        self.assertFalse(snapshot["connected"])
        self.assertIsNone(snapshot["mission"])
        self.assertEqual(snapshot["events"], [])
        self.assertEqual(snapshot["architect"]["status"], "OFFLINE")
        self.assertFalse(snapshot["architect"]["connected"])
        self.assertIn("V2", snapshot["architect"]["notice"])
        self.assertEqual(snapshot["actors"]["architect"]["role"], "ARCHITECT")
        self.assertEqual(snapshot["actors"]["executor"]["role"], "EXECUTOR")
        self.assertEqual(snapshot["actors"]["validator"]["role"], "VALIDATOR")
        self.assertEqual(snapshot["actors"]["human"]["role"], "HUMAN")

    # 4. Security sanitization: secrets, prompts and absolute paths
    def test_security_sanitization(self):
        # Sensitive text with prompt marker
        msg_prompt = "Here is <USER_REQUEST> secret instruction </USER_REQUEST>"
        self.assertEqual(agent_ops.sanitize_text(msg_prompt), "Mission instructions received")

        # Secret tokens
        msg_secret = "Using token Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9 and sk-1234567890123456789012"
        sanitized_secret = agent_ops.sanitize_text(msg_secret)
        self.assertNotIn("Bearer eyJhbGci", sanitized_secret)
        self.assertNotIn("sk-1234567890123456789012", sanitized_secret)
        self.assertIn("[REDACTED]", sanitized_secret)

        # Path sanitization
        abs_path_win = r"D:\Projetos\MoneyPrinterTurbo\webui-v2\src\components\FactoryLiveGraph.jsx"
        rel_path = agent_ops.sanitize_relative_path(abs_path_win)
        self.assertEqual(rel_path, "webui-v2/src/components/FactoryLiveGraph.jsx")

    # 5. Connected snapshot with real state.json and live.ndjson
    def test_get_agent_ops_snapshot_connected(self):
        # Write state.json
        state_data = {
            "task_id": "agent-ops-v11",
            "status": "AGENT_WORKING",
            "cycle": 1,
            "branch": "feat/web-ui-v2-read-api",
            "conversation_id": "81d05246-f67d-44b0-88d5-d89371858fc1",
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(os.path.join(self.bridge_dir, "state.json"), "w", encoding="utf-8") as f:
            json.dump(state_data, f)

        # Write logs/live.ndjson with various events
        ndjson_events = [
            {
                "timestamp": "2026-10-12T10:42:21Z",
                "source": "system",
                "event_type": "mission_started",
                "message": "Mission started",
            },
            {
                "timestamp": "2026-10-12T10:42:26Z",
                "source": "executor",
                "actor": "EXECUTOR",
                "tool_name": "view_file",
                "toolAction": "Analyzing FactoryLiveGraph.jsx",
                "parameters": {"AbsolutePath": r"D:\Projetos\MoneyPrinterTurbo\webui-v2\src\components\FactoryLiveGraph.jsx"},
            },
            {
                "timestamp": "2026-10-12T10:43:04Z",
                "source": "antigravity",
                "tool_name": "replace_file_content",
                "toolAction": "Editing ChannelCard.jsx",
                "parameters": {"TargetFile": r"D:\Projetos\MoneyPrinterTurbo\webui-v2\src\components\ChannelCard.jsx"},
            },
            {
                "timestamp": "2026-10-12T10:45:17Z",
                "source": "validator",
                "actor": "VALIDATOR",
                "tool_name": "run_command",
                "toolAction": "npm run build",
            },
        ]

        ndjson_path = os.path.join(self.bridge_dir, "logs", "live.ndjson")
        with open(ndjson_path, "w", encoding="utf-8") as f:
            for ev in ndjson_events:
                f.write(json.dumps(ev) + "\n")

        # Snapshot evaluation
        snapshot = agent_ops.get_agent_ops_snapshot(bridge_root=self.bridge_dir)

        self.assertTrue(snapshot["connected"])
        self.assertEqual(snapshot["mission"]["task_id"], "agent-ops-v11")
        self.assertEqual(snapshot["mission"]["status"], "AGENT_WORKING")
        self.assertEqual(snapshot["mission"]["cycle"], 1)
        self.assertEqual(snapshot["mission"]["branch"], "feat/web-ui-v2-read-api")
        self.assertEqual(snapshot["mission"]["conversation_id_short"], "81d05246...")
        self.assertIsNotNone(snapshot["mission"]["elapsed_formatted"])

        # OpenAI Architect must be explicitly OFFLINE
        self.assertEqual(snapshot["architect"]["status"], "OFFLINE")
        self.assertEqual(snapshot["actors"]["architect"]["status_text"], "V2 — OpenAI Architect pending")

        # Events verification
        events = snapshot["events"]
        self.assertEqual(len(events), 4)

        # 1. System
        self.assertEqual(events[0]["actor"], "SYSTEM")
        self.assertIn("Mission started", events[0]["message"])

        # 2. Executor view_file
        self.assertEqual(events[1]["actor"], "EXECUTOR")
        self.assertEqual(events[1]["tool_action"], "Analyzing FactoryLiveGraph.jsx")
        self.assertEqual(events[1]["relative_path"], "webui-v2/src/components/FactoryLiveGraph.jsx")

        # 3. Executor replace_file_content
        self.assertEqual(events[2]["actor"], "EXECUTOR")
        self.assertEqual(events[2]["tool_action"], "Editing ChannelCard.jsx")
        self.assertEqual(events[2]["relative_path"], "webui-v2/src/components/ChannelCard.jsx")

        # 4. Validator
        self.assertEqual(events[3]["actor"], "VALIDATOR")
        self.assertEqual(events[3]["tool_action"], "npm run build")

    # 6. BLOCKED_HUMAN status highlight
    def test_blocked_human_status_highlight(self):
        state_data = {
            "task_id": "agent-ops-v11",
            "status": "BLOCKED_HUMAN",
            "cycle": 2,
        }
        with open(os.path.join(self.bridge_dir, "state.json"), "w", encoding="utf-8") as f:
            json.dump(state_data, f)

        snapshot = agent_ops.get_agent_ops_snapshot(bridge_root=self.bridge_dir)

        self.assertTrue(snapshot["mission"]["is_blocked_human"])
        self.assertEqual(snapshot["actors"]["human"]["status"], "BLOCKED_HUMAN")
        self.assertTrue(snapshot["actors"]["human"]["is_highlighted"])

    # 7. Endpoint /api/v2/agent-ops integration test
    def test_fastapi_agent_ops_endpoint(self):
        from unittest.mock import MagicMock
        from app.controllers.v2.operations import get_agent_ops

        mock_request = MagicMock()
        with patch("app.services.agent_ops.resolve_agent_bridge_root", return_value=self.bridge_dir):
            response = get_agent_ops(mock_request)
            self.assertEqual(response["status"], 200)
            self.assertIn("data", response)
            self.assertTrue(response["data"]["connected"])
            self.assertIn("actors", response["data"])


if __name__ == "__main__":
    unittest.main()
