"""Targeted tests for Agent Ops telemetry service and endpoint (Agent Ops V1.1 / Polish).

Covers:
1. Root resolution order (AGENT_BRIDGE_ROOT env var, sibling directory, fallback);
2. Graceful disconnected payload when AgentBridge does not exist;
3. Sanitized state reading with factually derived elapsed time and abbreviated conv_id;
4. Sanitized live.ndjson projection (stripping prompts, secrets, absolute paths);
5. Canonical AGY tool mapping (view_file, read_file, grep_search, etc.);
6. Stream-json unwrapping (step_update.step_type, tool_name, tool_info, state);
7. AGENT_RESPONSE text_delta sanitization & thinking block stripping;
8. Bridge & Validator events (Build iniciado, Build PASS/FAIL, Git check PASS/FAIL);
9. Noise reduction: elimination of Activity step and collapsing ACTIVE + DONE;
10. Mission metadata derivation (branch & started_at from MISSION_STARTED);
11. Factual elapsed calculation (None when missing, exact diff when finished);
12. OpenAI Architect honest offline notice;
13. BLOCKED_HUMAN status highlight detection;
14. Fast-path FastAPI controller integration test.
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

        # 2. Executor view_file mapped canonically
        self.assertEqual(events[1]["actor"], "EXECUTOR")
        self.assertEqual(events[1]["tool_action"], "Lendo webui-v2/src/components/FactoryLiveGraph.jsx")
        self.assertEqual(events[1]["relative_path"], "webui-v2/src/components/FactoryLiveGraph.jsx")

        # 3. Executor replace_file_content mapped canonically
        self.assertEqual(events[2]["actor"], "EXECUTOR")
        self.assertEqual(events[2]["tool_action"], "Editando webui-v2/src/components/ChannelCard.jsx")
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

    # 8. Stream-JSON tool unwrapping & canonical AGY mapping (Rule 1)
    def test_stream_json_tool_mapping(self):
        test_cases = [
            ("view_file", {"AbsolutePath": r"D:\Projetos\MoneyPrinterTurbo\app\services\flow.py"}, "Lendo app/services/flow.py", "app/services/flow.py"),
            ("read_file", {"path": r"D:\Projetos\MoneyPrinterTurbo\docs\ROADMAP.md"}, "Lendo docs/ROADMAP.md", "docs/ROADMAP.md"),
            ("grep_search", {"path": "app/services"}, "Buscando no código", "app/services"),
            ("find_by_name", {"filename": "utils.py"}, "Buscando no código", "utils.py"),
            ("search_web", {"query": "FastAPI read-only patterns"}, "Pesquisando referências", None),
            ("read_url_content", {"Url": "https://example.com/api"}, "Pesquisando referências", None),
            ("replace_file_content", {"TargetFile": r"D:\Projetos\MoneyPrinterTurbo\app\utils\utils.py"}, "Editando app/utils/utils.py", "app/utils/utils.py"),
            ("multi_replace_file_content", {"TargetFile": "app/main.py"}, "Editando app/main.py", "app/main.py"),
            ("write_to_file", {"TargetFile": r"D:\Projetos\MoneyPrinterTurbo\docs\NEW.md"}, "Editando docs/NEW.md", "docs/NEW.md"),
            ("browser_navigate", {"url": "http://localhost:3000"}, "Pesquisa/Navegação web", None),
            ("invoke_subagent", {"Role": "Codebase Researcher"}, "Delegando subagente", None),
            ("browser_subagent", {}, "Delegando subagente", None),
        ]

        for tool, args, expected_action, expected_path in test_cases:
            action, rel_path = agent_ops.derive_tool_action(tool, args)
            self.assertEqual(action, expected_action, f"Mismatch for tool {tool}")
            self.assertEqual(rel_path, expected_path, f"Path mismatch for tool {tool}")

        # Stream-json line with step_update wrapper
        raw_stream_line = json.dumps({
            "step_update": {
                "step_id": "step-42",
                "step_type": "tool",
                "tool_name": "view_file",
                "state": "ACTIVE",
                "tool_info": {
                    "args": {"AbsolutePath": r"D:\Projetos\MoneyPrinterTurbo\app\models\schema.py"}
                }
            },
            "timestamp": "2026-10-12T11:00:00Z"
        })
        parsed = agent_ops.parse_ndjson_line(raw_stream_line, 1)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["actor"], "EXECUTOR")
        self.assertEqual(parsed["tool_name"], "view_file")
        self.assertEqual(parsed["tool_action"], "Lendo app/models/schema.py")
        self.assertEqual(parsed["relative_path"], "app/models/schema.py")
        self.assertEqual(parsed["status"], "ACTIVE")

    # 9. AGENT_RESPONSE: text_delta sanitization & noise filtering (Rule 2 & 4)
    def test_agent_response_sanitization(self):
        # 1. Useful response with thinking tags -> thinking stripped, text kept
        raw_with_thinking = json.dumps({
            "step_update": {
                "step_type": "agent_response",
                "state": "DONE",
                "text_delta": "<thought>Analyzing the problem internally...</thought>Iniciando refatoração do endpoint.",
            },
            "timestamp": "2026-10-12T11:05:00Z"
        })
        parsed = agent_ops.parse_ndjson_line(raw_with_thinking, 1)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["actor"], "EXECUTOR")
        self.assertNotIn("Analyzing the problem", parsed["tool_action"])
        self.assertEqual(parsed["tool_action"], "Iniciando refatoração do endpoint.")

        # 2. Empty or whitespace-only response -> noise filtered out (None)
        raw_empty = json.dumps({
            "step_update": {
                "step_type": "agent_response",
                "state": "ACTIVE",
                "text_delta": "   \n\t  ",
            }
        })
        self.assertIsNone(agent_ops.parse_ndjson_line(raw_empty, 2))

        # 3. Only thinking tags without content -> noise filtered out (None)
        raw_only_thinking = json.dumps({
            "step_update": {
                "step_type": "agent_response",
                "state": "ACTIVE",
                "text_delta": "<thought>Deep internal reasoning that should not be visible</thought>",
            }
        })
        self.assertIsNone(agent_ops.parse_ndjson_line(raw_only_thinking, 3))

        # 4. Generic Activity step -> noise filtered out (None)
        raw_generic = json.dumps({
            "event_type": "activity",
            "message": "Activity step",
        })
        self.assertIsNone(agent_ops.parse_ndjson_line(raw_generic, 4))

    # 10. Bridge & Validator events (Rule 3)
    def test_bridge_and_validator_events(self):
        cases = [
            ({"source": "validator", "event_type": "build", "status": "ACTIVE"}, "VALIDATOR", "Build iniciado"),
            ({"source": "validator", "event_type": "build", "status": "PASS"}, "VALIDATOR", "Build PASS"),
            ({"source": "validator", "event_type": "build", "status": "FAIL"}, "VALIDATOR", "Build FAIL"),
            ({"source": "validator", "event_type": "git_check", "status": "PASS"}, "VALIDATOR", "Git check PASS"),
            ({"source": "validator", "event_type": "git_check", "status": "FAIL"}, "VALIDATOR", "Git check FAIL"),
            ({"event_type": "MISSION_SUCCESS"}, "SYSTEM", "Mission success"),
            ({"message": "Permission recovery on workspace"}, "SYSTEM", "Recuperação de permissão"),
        ]

        for payload, expected_actor, expected_action in cases:
            parsed = agent_ops.parse_ndjson_line(json.dumps(payload), 1)
            self.assertIsNotNone(parsed)
            self.assertEqual(parsed["actor"], expected_actor)
            self.assertEqual(parsed["tool_action"], expected_action)

    # 11. Collapsing ACTIVE + DONE of the same tool with duration (Rule 4)
    def test_collapse_active_and_done_tool_events(self):
        ndjson_path = os.path.join(self.bridge_dir, "logs", "live.ndjson")
        events_data = [
            # Active tool
            {
                "timestamp": "2026-10-12T11:10:00Z",
                "step_update": {
                    "step_id": "tool-step-1",
                    "step_type": "tool",
                    "tool_name": "view_file",
                    "state": "ACTIVE",
                    "tool_info": {"args": {"AbsolutePath": r"D:\Projetos\MoneyPrinterTurbo\app\config.py"}},
                }
            },
            # Completed tool 3 seconds later
            {
                "timestamp": "2026-10-12T11:10:03Z",
                "step_update": {
                    "step_id": "tool-step-1",
                    "step_type": "tool",
                    "tool_name": "view_file",
                    "state": "DONE",
                    "tool_info": {"args": {"AbsolutePath": r"D:\Projetos\MoneyPrinterTurbo\app\config.py"}},
                }
            },
        ]
        with open(ndjson_path, "w", encoding="utf-8") as f:
            for ev in events_data:
                f.write(json.dumps(ev) + "\n")

        read_events = agent_ops.read_live_ndjson(self.bridge_dir)
        # Should collapse into a SINGLE event with status DONE and duration
        self.assertEqual(len(read_events), 1)
        self.assertEqual(read_events[0]["status"], "DONE")
        self.assertEqual(read_events[0]["duration"], "3s")
        self.assertEqual(read_events[0]["tool_action"], "Lendo app/config.py")

    # 12. Mission metadata derivation from MISSION_STARTED (Rule 5)
    def test_mission_metadata_derivation(self):
        # state.json without branch or started_at
        state_data = {
            "task_id": "agent-ops-polish",
            "status": "AGENT_WORKING",
            "cycle": 1,
        }
        with open(os.path.join(self.bridge_dir, "state.json"), "w", encoding="utf-8") as f:
            json.dump(state_data, f)

        # live.ndjson with MISSION_STARTED carrying payload
        ndjson_events = [
            {
                "timestamp": "2026-10-12T11:00:00Z",
                "event_type": "MISSION_STARTED",
                "payload": {
                    "branch": "feat/telemetry-stream-contract",
                    "task_id": "agent-ops-polish",
                    "started_at": "2026-10-12T11:00:00Z",
                }
            }
        ]
        with open(os.path.join(self.bridge_dir, "logs", "live.ndjson"), "w", encoding="utf-8") as f:
            for ev in ndjson_events:
                f.write(json.dumps(ev) + "\n")

        snapshot = agent_ops.get_agent_ops_snapshot(bridge_root=self.bridge_dir)
        self.assertEqual(snapshot["mission"]["branch"], "feat/telemetry-stream-contract")
        self.assertEqual(snapshot["mission"]["started_at"], "2026-10-12T11:00:00Z")
        self.assertIsNotNone(snapshot["mission"]["elapsed_formatted"])

    # 13. Elapsed calculation: factual vs non-running vs missing timestamps (Rule 5)
    def test_elapsed_factual_calculations(self):
        # 1. Missing started_at -> returns (None, None), NEVER "00:00"
        diff, formatted = agent_ops.calculate_mission_elapsed(
            None, "AGENT_WORKING", {}, None, []
        )
        self.assertIsNone(diff)
        self.assertIsNone(formatted)

        # 2. Non-running (SUCCESS) without factual end timestamp -> returns (None, None), NEVER "00:00"
        diff, formatted = agent_ops.calculate_mission_elapsed(
            "2026-10-12T11:00:00Z", "SUCCESS", {}, None, []
        )
        self.assertIsNone(diff)
        self.assertIsNone(formatted)

        # 3. Non-running (SUCCESS) with result completed_at -> exact factual duration
        result_data = {
            "completed_at": "2026-10-12T11:05:30Z",
            "status": "SUCCESS"
        }
        diff, formatted = agent_ops.calculate_mission_elapsed(
            "2026-10-12T11:00:00Z", "SUCCESS", {}, result_data, []
        )
        self.assertEqual(diff, 330)
        self.assertEqual(formatted, "05:30")


if __name__ == "__main__":
    unittest.main()
