"""Agent Ops service — Read-only telemetry provider for AgentBridge (Agent Ops V1.1).

Responsibilities:
1. Locate local AgentBridge root via AGENT_BRIDGE_ROOT env var or sibling directory <ProjectsRoot>/AgentBridge.
2. Read state.json, logs/live.ndjson and result.json safely in a 100% read-only manner.
3. Sanitize and project live telemetry:
   - Strip full prompts, secrets, tokens, cookies, environment variables, full file contents.
   - Convert absolute filesystem paths to relative project paths.
   - Normalize actors (ARCHITECT, EXECUTOR, VALIDATOR, HUMAN, SYSTEM).
   - Project tool events into human-readable actions (e.g. 'Analyzing FactoryLiveGraph.jsx').
   - Provide explicit, honest offline notice for OpenAI Architect (pending V2).
"""

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from app.utils import utils


# Maximum number of live events retained in the sanitized projection
MAX_LIVE_EVENTS = 150

# Regex patterns for stripping sensitive data
SECRET_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{8,}", re.IGNORECASE),
    re.compile(r"(?:api[_-]?key|secret|token|password|auth|cookie|passwd)[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9_\-\.]{8,})[\"']?", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9]{20,}", re.IGNORECASE),
]

PROMPT_MARKERS = [
    "<USER_REQUEST>",
    "</USER_REQUEST>",
    "<SYSTEM_MESSAGE>",
    "<TASK_INSTRUCTION>",
    "AUTONOMOUS AGENT BRIDGE TASK",
]


def resolve_agent_bridge_root() -> Optional[str]:
    """Resolve AgentBridge root path following priority:
    1. AGENT_BRIDGE_ROOT environment variable, if set and valid directory;
    2. Sibling directory of the project: <ProjectsRoot>/AgentBridge;
    Returns None if not found or not a directory.
    """
    env_root = os.getenv("AGENT_BRIDGE_ROOT")
    if env_root and os.path.isdir(env_root):
        return os.path.abspath(env_root)

    try:
        project_root = utils.root_dir()
        projects_root = os.path.dirname(project_root)
        sibling = os.path.join(projects_root, "AgentBridge")
        if os.path.isdir(sibling):
            return os.path.abspath(sibling)
    except Exception as exc:
        logger.debug(f"Could not resolve sibling AgentBridge: {exc}")

    if env_root:
        # Return path even if not yet created so caller can report specific target
        return os.path.abspath(env_root)

    return None


def sanitize_relative_path(path_str: Any) -> Optional[str]:
    """Convert an absolute path or raw path into a clean, relative path."""
    if not isinstance(path_str, str) or not path_str.strip():
        return None

    cleaned = path_str.strip().replace("\\", "/")

    # Detect MoneyPrinterTurbo relative segment
    marker = "MoneyPrinterTurbo/"
    idx = cleaned.find(marker)
    if idx != -1:
        return cleaned[idx + len(marker):]

    # Detect AgentBridge relative segment
    bridge_marker = "AgentBridge/"
    b_idx = cleaned.find(bridge_marker)
    if b_idx != -1:
        return cleaned[b_idx + len(bridge_marker):]

    # If starts with drive letter or leading root
    if re.match(r"^[A-Za-z]:/", cleaned):
        parts = cleaned.split("/")
        if len(parts) > 2:
            return "/".join(parts[-3:])
        return parts[-1]

    if cleaned.startswith("/"):
        parts = cleaned.strip("/").split("/")
        if len(parts) > 2:
            return "/".join(parts[-3:])
        return parts[-1]

    return cleaned


def sanitize_text(text: Any, max_length: int = 240) -> str:
    """Sanitize and truncate messages to eliminate secrets, full prompts or dumps."""
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)

    # Check for raw mission prompts
    for marker in PROMPT_MARKERS:
        if marker in text:
            return "Mission instructions received"

    # Redact secrets
    sanitized = text
    for pattern in SECRET_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)

    # Collapse excessive whitespace
    sanitized = re.sub(r"\s+", " ", sanitized).strip()

    if len(sanitized) > max_length:
        return sanitized[: max_length - 3] + "..."
    return sanitized


def derive_tool_action(tool_name: Optional[str], args: Dict[str, Any], raw_action: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """Derive human-friendly tool action and safe relative path."""
    if raw_action and isinstance(raw_action, str) and raw_action.strip():
        action_text = sanitize_text(raw_action.strip(), max_length=90)
        # Check if we can extract a relative path from args anyway
        target_path = None
        for key in ("TargetFile", "AbsolutePath", "path", "file"):
            if key in args and isinstance(args[key], str):
                target_path = sanitize_relative_path(args[key])
                break
        return action_text, target_path

    if not tool_name:
        return "Activity step", None

    target_path = None
    for key in ("TargetFile", "AbsolutePath", "path", "file", "TargetDir", "Cwd"):
        if key in args and isinstance(args[key], str):
            target_path = sanitize_relative_path(args[key])
            break

    name = tool_name.lower()
    if name == "view_file":
        return (f"Analyzing {target_path}" if target_path else "Reading file"), target_path
    if name in ("replace_file_content", "multi_replace_file_content"):
        return (f"Editing {target_path}" if target_path else "Editing component"), target_path
    if name == "write_to_file":
        return (f"Writing {target_path}" if target_path else "Creating file"), target_path
    if name == "run_command":
        cmd = args.get("CommandLine", "")
        if cmd:
            # Only keep first 2-3 words of safe command without arguments
            cmd_clean = sanitize_text(cmd.split("\n")[0], max_length=50)
            return f"Executing {cmd_clean}", None
        return "Executing command", None
    if name == "search_web":
        query = args.get("query", "")
        if query:
            return f"Web search: {sanitize_text(query, max_length=40)}", None
        return "Searching web", None
    if name == "list_dir":
        return (f"Listing {target_path}" if target_path else "Scanning directory"), target_path
    if name in ("define_subagent", "invoke_subagent"):
        role = args.get("Role") or args.get("TypeName") or "subagent"
        return f"Delegating to {sanitize_text(str(role), max_length=30)}", None

    return f"Tool: {tool_name}", target_path


def normalize_actor(raw_actor: Optional[str], source: Optional[str] = None, event_type: Optional[str] = None) -> str:
    """Normalize actor to one of ARCHITECT, EXECUTOR, VALIDATOR, HUMAN, SYSTEM."""
    candidate = (raw_actor or source or "").strip().upper()

    if candidate == "ARCHITECT" or "ARCHITECT" in candidate:
        return "ARCHITECT"
    if candidate in ("VALIDATOR", "BRIDGE_VALIDATOR") or "VALIDAT" in candidate or (event_type and any(v in event_type.lower() for v in ("validation", "build", "git"))):
        return "VALIDATOR"
    if candidate in ("HUMAN", "USER", "OPERATOR") or "BLOCKED_HUMAN" in str(candidate):
        return "HUMAN"
    if candidate in ("EXECUTOR", "AGENT", "ANTIGRAVITY", "MODEL", "ASSISTANT") or (event_type and "tool" in event_type.lower()):
        return "EXECUTOR"
    if candidate in ("SYSTEM", "BRIDGE", "DAEMON") or (event_type and any(s in event_type.lower() for s in ("mission_start", "lifecycle", "state_change"))):
        return "SYSTEM"

    return "EXECUTOR" if (event_type and "tool" in event_type.lower()) else "SYSTEM"


def parse_ndjson_line(line_str: str, index: int) -> Optional[Dict[str, Any]]:
    """Parse and project a single line of logs/live.ndjson into a sanitized telemetry record."""
    line_str = line_str.strip()
    if not line_str:
        return None

    try:
        raw = json.loads(line_str)
    except Exception:
        # If line is corrupt or partial, safely skip
        return None

    if not isinstance(raw, dict):
        return None

    event_type = str(raw.get("event_type") or raw.get("type") or "activity").strip()
    raw_source = str(raw.get("source") or raw.get("sender") or raw.get("role") or "").strip()
    raw_actor = raw.get("actor")

    actor = normalize_actor(raw_actor, source=raw_source, event_type=event_type)

    raw_ts = raw.get("timestamp") or raw.get("ts") or raw.get("time") or raw.get("created_at")
    time_display = "00:00:00"
    iso_timestamp = None

    if raw_ts:
        if isinstance(raw_ts, (int, float)):
            try:
                dt = datetime.fromtimestamp(raw_ts, tz=timezone.utc)
                time_display = dt.strftime("%H:%M:%S")
                iso_timestamp = dt.isoformat()
            except Exception:
                time_display = str(raw_ts)[:8]
        elif isinstance(raw_ts, str):
            iso_timestamp = raw_ts
            # If ISO formatted string, extract HH:MM:SS
            match = re.search(r"T(\d{2}:\d{2}:\d{2})", raw_ts)
            if match:
                time_display = match.group(1)
            else:
                time_display = raw_ts[:8]

    # Extract tool information if present
    tool_name = raw.get("tool_name") or raw.get("tool") or raw.get("function")
    tool_args = raw.get("parameters") or raw.get("arguments") or raw.get("args") or raw.get("tool_args") or {}
    if not isinstance(tool_args, dict):
        tool_args = {}

    raw_action = raw.get("toolAction") or raw.get("tool_action") or raw.get("action")
    action_text, rel_path = derive_tool_action(tool_name, tool_args, raw_action)

    # Extract short message
    msg_candidate = raw.get("message") or raw.get("short_message") or raw.get("summary") or raw.get("text_delta") or raw.get("content")
    if not msg_candidate and not tool_name:
        msg_candidate = action_text

    message = sanitize_text(msg_candidate, max_length=220)

    # Abbreviate conversation ID
    conv_id = raw.get("conversation_id") or raw.get("conv_id")
    conv_short = None
    if conv_id and isinstance(conv_id, str):
        conv_short = conv_id[:8] + "..." if len(conv_id) > 8 else conv_id

    return {
        "id": raw.get("id") or f"evt-{index}",
        "timestamp": time_display,
        "iso_timestamp": iso_timestamp,
        "actor": actor,
        "source": raw_source or "bridge",
        "event_type": event_type,
        "status": raw.get("status") or "info",
        "tool_name": tool_name if isinstance(tool_name, str) else None,
        "tool_action": action_text,
        "relative_path": rel_path,
        "message": message,
        "task_id": raw.get("task_id"),
        "cycle": raw.get("cycle"),
        "conversation_id_short": conv_short,
    }


def read_live_ndjson(bridge_root: str, max_events: int = MAX_LIVE_EVENTS) -> List[Dict[str, Any]]:
    """Read the last ~100-200 lines of logs/live.ndjson and return a sanitized list of events."""
    ndjson_path = os.path.join(bridge_root, "logs", "live.ndjson")
    if not os.path.isfile(ndjson_path):
        return []

    try:
        # Read lines safely with UTF-8
        with open(ndjson_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        # Slice to last max_events lines to avoid excessive memory or unbounded growth
        recent_lines = lines[-max_events:] if len(lines) > max_events else lines

        sanitized_events = []
        for idx, line in enumerate(recent_lines):
            item = parse_ndjson_line(line, idx + 1)
            if item:
                sanitized_events.append(item)

        return sanitized_events
    except Exception as exc:
        logger.warning(f"Error reading live.ndjson from {ndjson_path}: {exc}")
        return []


def read_state_json(bridge_root: str) -> Dict[str, Any]:
    """Read and sanitize state.json from AgentBridge root."""
    state_path = os.path.join(bridge_root, "state.json")
    if not os.path.isfile(state_path):
        return {}

    try:
        with open(state_path, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning(f"Error reading state.json from {state_path}: {exc}")
        return {}


def read_result_json(bridge_root: str) -> Optional[Dict[str, Any]]:
    """Read result.json of current or most recent mission if available."""
    # Check directly in bridge_root or in results/ directory
    candidates = [
        os.path.join(bridge_root, "result.json"),
        os.path.join(bridge_root, "results", "result.json"),
    ]

    for p in candidates:
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    # Sanitize result fields
                    return {
                        "status": data.get("status"),
                        "task_id": data.get("task_id"),
                        "completed_at": data.get("completed_at") or data.get("timestamp"),
                        "summary": sanitize_text(data.get("summary") or data.get("message") or "", max_length=300),
                        "validation_passed": data.get("validation_passed", data.get("status") == "SUCCESS"),
                    }
            except Exception as exc:
                logger.debug(f"Could not parse result.json at {p}: {exc}")

    return None


def calculate_elapsed(started_at_val: Any) -> Tuple[Optional[int], Optional[str]]:
    """Derive elapsed seconds and formatted time mm:ss or Xm Ys factually from start time."""
    if not started_at_val:
        return None, None

    dt_start = None
    if isinstance(started_at_val, (int, float)):
        try:
            dt_start = datetime.fromtimestamp(started_at_val, tz=timezone.utc)
        except Exception:
            return None, None
    elif isinstance(started_at_val, str):
        try:
            # Handle ISO format
            clean_str = started_at_val.replace("Z", "+00:00")
            dt_start = datetime.fromisoformat(clean_str)
            if dt_start.tzinfo is None:
                dt_start = dt_start.replace(tzinfo=timezone.utc)
        except Exception:
            return None, None

    if not dt_start:
        return None, None

    now = datetime.now(timezone.utc)
    diff = int((now - dt_start).total_seconds())
    if diff < 0:
        diff = 0

    minutes, seconds = divmod(diff, 60)
    hours, minutes = divmod(minutes, 60)

    if hours > 0:
        formatted = f"{hours}h {minutes}m {seconds}s"
    else:
        formatted = f"{minutes:02d}:{seconds:02d}"

    return diff, formatted


def get_agent_ops_snapshot(bridge_root: Optional[str] = None) -> Dict[str, Any]:
    """Assemble consolidated, read-only, sanitized Agent Ops telemetry.

    If AgentBridge is missing or not reachable, returns clean connected=False payload.
    Never alters, creates or modifies any AgentBridge files.
    """
    if bridge_root is None:
        bridge_root = resolve_agent_bridge_root()

    if not bridge_root or not os.path.isdir(bridge_root):
        return {
            "connected": False,
            "bridge_root": None,
            "mission": None,
            "architect": {
                "status": "OFFLINE",
                "connected": False,
                "notice": "OpenAI Architect será conectado na V2",
            },
            "actors": {
                "architect": {
                    "name": "OpenAI Architect",
                    "role": "ARCHITECT",
                    "status": "OFFLINE",
                    "status_text": "V2 — OpenAI Architect pending",
                    "color": "violet",
                },
                "executor": {
                    "name": "Antigravity",
                    "role": "EXECUTOR",
                    "status": "DISCONNECTED",
                    "status_text": "AgentBridge not connected",
                    "color": "cyan",
                },
                "validator": {
                    "name": "Bridge Validator",
                    "role": "VALIDATOR",
                    "status": "DISCONNECTED",
                    "status_text": "AgentBridge not connected",
                    "color": "green",
                },
                "human": {
                    "name": "Human Operator",
                    "role": "HUMAN",
                    "status": "STANDBY",
                    "status_text": "Standby",
                    "color": "gold",
                },
            },
            "events": [],
            "result": None,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    # 1. Read state.json
    raw_state = read_state_json(bridge_root)

    # 2. Read live.ndjson
    events = read_live_ndjson(bridge_root, max_events=MAX_LIVE_EVENTS)

    # 3. Read result.json
    result_data = read_result_json(bridge_root)

    # Extract mission parameters
    task_id = raw_state.get("task_id") or raw_state.get("current_task_id")
    raw_status = (raw_state.get("status") or raw_state.get("state") or "AGENT_WORKING").strip().upper()
    cycle = raw_state.get("cycle") or raw_state.get("current_cycle") or 1
    branch = raw_state.get("branch") or raw_state.get("current_branch")
    conv_id = raw_state.get("conversation_id")
    conv_id_short = conv_id[:8] + "..." if conv_id and len(conv_id) > 8 else conv_id
    started_at = raw_state.get("started_at") or raw_state.get("start_time")

    elapsed_seconds, elapsed_formatted = calculate_elapsed(started_at)

    # Derive last active tool from events if executor is working
    latest_executor_action = None
    for evt in reversed(events):
        if evt.get("actor") == "EXECUTOR" and evt.get("tool_action"):
            latest_executor_action = evt.get("tool_action")
            break

    # Determine actor operational statuses
    is_blocked_human = "BLOCKED" in raw_status or any("BLOCKED_HUMAN" in e.get("message", "") for e in events[-5:])
    is_validating = raw_status == "VALIDATING" or any(e.get("actor") == "VALIDATOR" for e in events[-2:])

    executor_status = "AGENT_WORKING"
    if raw_status in ("SUCCESS", "FAILED", "COMPLETE"):
        executor_status = raw_status
    elif is_blocked_human:
        executor_status = "WAITING_HUMAN"

    validator_status = "VALIDATING" if is_validating else "IDLE"

    human_status = "BLOCKED_HUMAN" if is_blocked_human else "STANDBY"
    human_status_text = "Action required (BLOCKED_HUMAN)" if is_blocked_human else "Standby (monitoring)"

    mission_data = {
        "task_id": task_id,
        "status": raw_status,
        "cycle": cycle,
        "branch": branch,
        "conversation_id": conv_id,
        "conversation_id_short": conv_id_short,
        "started_at": started_at,
        "elapsed_seconds": elapsed_seconds,
        "elapsed_formatted": elapsed_formatted,
        "is_blocked_human": is_blocked_human,
    }

    actors_data = {
        "architect": {
            "name": "OpenAI Architect",
            "role": "ARCHITECT",
            "status": "OFFLINE",
            "status_text": "V2 — OpenAI Architect pending",
            "color": "violet",
            "notice": "OpenAI Architect será conectado na V2",
        },
        "executor": {
            "name": "Antigravity",
            "role": "EXECUTOR",
            "status": executor_status,
            "status_text": latest_executor_action or ("Working" if executor_status == "AGENT_WORKING" else executor_status),
            "color": "cyan",
        },
        "validator": {
            "name": "Bridge Validator",
            "role": "VALIDATOR",
            "status": validator_status,
            "status_text": "Validation / Build / Git",
            "color": "green",
        },
        "human": {
            "name": "Human Operator",
            "role": "HUMAN",
            "status": human_status,
            "status_text": human_status_text,
            "color": "gold",
            "is_highlighted": is_blocked_human,
        },
    }

    return {
        "connected": True,
        "bridge_root": "AgentBridge",
        "mission": mission_data,
        "architect": {
            "status": "OFFLINE",
            "connected": False,
            "notice": "OpenAI Architect será conectado na V2",
        },
        "actors": actors_data,
        "events": events,
        "result": result_data,
        "total_events": len(events),
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
