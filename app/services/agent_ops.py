"""Agent Ops service — Read-only telemetry provider for AgentBridge (Agent Ops V1.1 / Polish).

Responsibilities:
1. Locate local AgentBridge root via AGENT_BRIDGE_ROOT env var or sibling directory <ProjectsRoot>/AgentBridge.
2. Read state.json, logs/live.ndjson and result.json safely in a 100% read-only manner.
3. Sanitize and project live telemetry following the official stream-json contract:
   - Handle step_update unwrapping (step_type, tool_name, tool_info, text_delta, state ACTIVE/DONE).
   - Map tool events from AGY as EXECUTOR:
     * view_file/read_file -> Lendo <arquivo relativo>
     * grep_search/find_by_name -> Buscando no código
     * search_web/read_url_content -> Pesquisando referências
     * replace_file_content/multi_replace_file_content/write_to_file -> Editando <arquivo relativo>
     * browser_* -> Pesquisa/Navegação web
     * invoke_subagent/browser_subagent -> Delegando subagente
   - Agent response events as EXECUTOR (sanitize text_delta, strip thinking/internal reasoning, ignore empty).
   - Bridge & Validator events as VALIDATOR or SYSTEM (Build iniciado, Build PASS/FAIL, Git check PASS/FAIL, Mission success, permission recovery).
   - Noise reduction: eliminate empty/generic activity steps, collapse ACTIVE+DONE into DONE with duration, retain ~150 useful events.
   - Mission metadata derivation: branch from MISSION_STARTED payload, started_at from first MISSION_STARTED, elapsed factually calculated (or None/—, never fake 00:00).
   - Security: strip full prompts, secrets, tokens, cookies, env vars, absolute paths, raw file dumps.
   - Honest offline notice for OpenAI Architect (pending V2).
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


def parse_datetime(val: Any) -> Optional[datetime]:
    """Parse integer timestamp, float or ISO date string into UTC datetime."""
    if not val:
        return None
    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(val, tz=timezone.utc)
        except Exception:
            return None
    if isinstance(val, str):
        try:
            clean = val.strip().replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None
    return None


def format_elapsed(diff_seconds: int) -> str:
    """Format elapsed seconds as mm:ss or Xh Ym Zs."""
    if diff_seconds < 0:
        diff_seconds = 0
    minutes, seconds = divmod(diff_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    return f"{minutes:02d}:{seconds:02d}"


def format_duration(diff_seconds: float) -> str:
    """Format duration for tool steps (e.g. 2s, 350ms, 1m 12s)."""
    if diff_seconds < 0:
        diff_seconds = 0.0
    if diff_seconds >= 60.0:
        m = int(diff_seconds // 60)
        s = int(diff_seconds % 60)
        return f"{m}m {s}s"
    if diff_seconds >= 1.0:
        return f"{int(round(diff_seconds))}s"
    return f"{int(round(diff_seconds * 1000))}ms"


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


def extract_tool_args(raw_tool_info: Any, raw: Dict[str, Any]) -> Dict[str, Any]:
    """Extract argument dictionary safely from tool_info or raw payload."""
    tool_args: Dict[str, Any] = {}
    if isinstance(raw_tool_info, dict):
        if "args" in raw_tool_info and isinstance(raw_tool_info["args"], dict):
            tool_args = raw_tool_info["args"]
        elif "parameters" in raw_tool_info and isinstance(raw_tool_info["parameters"], dict):
            tool_args = raw_tool_info["parameters"]
        elif "input" in raw_tool_info and isinstance(raw_tool_info["input"], dict):
            tool_args = raw_tool_info["input"]
        else:
            tool_args = raw_tool_info
    elif isinstance(raw.get("parameters"), dict):
        tool_args = raw["parameters"]
    elif isinstance(raw.get("args"), dict):
        tool_args = raw["args"]
    elif isinstance(raw.get("tool_args"), dict):
        tool_args = raw["tool_args"]
    return tool_args


def extract_relative_path(args: Dict[str, Any]) -> Optional[str]:
    """Find and sanitize target file/path from argument dictionary."""
    if not isinstance(args, dict):
        return None
    for key in (
        "TargetFile",
        "AbsolutePath",
        "TargetDir",
        "path",
        "file",
        "file_path",
        "target_file",
        "absolute_path",
        "relative_path",
        "filename",
        "Cwd",
    ):
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            rel = sanitize_relative_path(val)
            if rel:
                return rel
    return None


def extract_useful_agent_response(text: Any) -> Optional[str]:
    """Sanitize and extract useful content from agent_response text_delta.
    Returns None if text is empty, whitespace, or solely internal reasoning.
    """
    if not text:
        return None
    if not isinstance(text, str):
        text = str(text)

    # Strip thinking / internal reasoning blocks
    cleaned = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<thinking>.*?</thinking>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"^thought:\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^thinking:\s*", "", cleaned, flags=re.IGNORECASE)

    # Prompt markers check
    for marker in PROMPT_MARKERS:
        if marker in cleaned:
            return "Instruções da missão recebidas"

    cleaned = sanitize_text(cleaned, max_length=140).strip()
    if not cleaned or len(cleaned) < 2 or cleaned in (".", "..", "...", "-", "--"):
        return None

    return cleaned


def derive_tool_action(
    tool_name: Optional[str],
    args: Dict[str, Any],
    raw_action: Optional[str] = None,
    source: Optional[str] = None,
) -> Tuple[str, Optional[str]]:
    """Derive human-friendly tool action and safe relative path based on official AGY tool contract.

    Mapeamento canônico:
    - view_file/read_file -> Lendo <arquivo relativo>
    - grep_search/find_by_name -> Buscando no código
    - search_web/read_url_content -> Pesquisando referências
    - replace_file_content/multi_replace_file_content/write_to_file -> Editando <arquivo relativo>
    - browser_* -> Pesquisa/Navegação web
    - invoke_subagent/browser_subagent -> Delegando subagente
    """
    target_path = extract_relative_path(args)
    if not tool_name:
        if raw_action and isinstance(raw_action, str) and raw_action.strip():
            cleaned_act = sanitize_text(raw_action.strip(), max_length=90)
            if cleaned_act.lower() not in ("activity step", "activity", "step update", "step_update"):
                return cleaned_act, target_path
        return "", target_path

    name = tool_name.strip().lower()

    if name in ("view_file", "read_file"):
        return (f"Lendo {target_path}" if target_path else "Lendo arquivo"), target_path

    if name in ("grep_search", "find_by_name"):
        return "Buscando no código", target_path

    if name in ("search_web", "read_url_content"):
        return "Pesquisando referências", None

    if name in ("replace_file_content", "multi_replace_file_content", "write_to_file"):
        return (f"Editando {target_path}" if target_path else "Editando arquivo"), target_path

    # Specific subagent tools must be classified before the generic
    # browser_* rule because browser_subagent also starts with "browser_".
    if name in ("invoke_subagent", "browser_subagent", "define_subagent"):
        return "Delegando subagente", None

    if name.startswith("browser_") or name in ("browser", "browse"):
        return "Pesquisa/Navegação web", None

    if name in ("list_dir", "list_directory"):
        return (f"Listando {target_path}" if target_path else "Listando diretório"), target_path

    if name == "run_command":
        if source == "validator":
            if raw_action and isinstance(raw_action, str) and raw_action.strip():
                return sanitize_text(raw_action.strip(), max_length=90), None
            return "Verificação de comando", None
        if raw_action and isinstance(raw_action, str) and raw_action.strip():
            return sanitize_text(raw_action.strip(), max_length=90), None
        return "Executando comando", None

    if raw_action and isinstance(raw_action, str) and raw_action.strip():
        cleaned_act = sanitize_text(raw_action.strip(), max_length=90)
        if cleaned_act.lower() not in ("activity step", "activity", "step update", "step_update"):
            return cleaned_act, target_path

    return f"Ferramenta: {tool_name}", target_path


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
    """Parse and project a single line of logs/live.ndjson into a sanitized telemetry record.
    Follows the official stream-json contract:
    - step_update unwrapping (step_type, tool_name, tool_info, text_delta, state)
    - Drops empty/uninformative step_updates to eliminate noise.
    - Classifies tools and agent_response as EXECUTOR.
    - Classifies validator and bridge events as VALIDATOR or SYSTEM.
    """
    line_str = line_str.strip()
    if not line_str:
        return None

    try:
        raw = json.loads(line_str)
    except Exception:
        return None

    if not isinstance(raw, dict):
        return None

    # 1. Unwrap stream-json step_update if present
    step_update = raw.get("step_update")
    if not isinstance(step_update, dict):
        step_update = {}

    step_type = (step_update.get("step_type") or raw.get("step_type") or "").strip().lower()

    tool_name = (
        step_update.get("tool_name")
        or raw.get("tool_name")
        or step_update.get("tool")
        or raw.get("tool")
        or step_update.get("function")
        or raw.get("function")
    )
    if isinstance(tool_name, str):
        tool_name = tool_name.strip()
    else:
        tool_name = None

    raw_tool_info = step_update.get("tool_info") or raw.get("tool_info")
    tool_args = extract_tool_args(raw_tool_info, raw)

    state = (
        step_update.get("state")
        or raw.get("state")
        or step_update.get("status")
        or raw.get("status")
        or ""
    ).strip().upper()

    step_id = (
        step_update.get("step_id")
        or step_update.get("id")
        or raw.get("step_id")
        or raw.get("id")
    )

    text_delta = (
        step_update.get("text_delta")
        or raw.get("text_delta")
        or step_update.get("content")
        or raw.get("content")
        or step_update.get("text")
        or raw.get("text")
    )

    raw_action = (
        step_update.get("toolAction")
        or raw.get("toolAction")
        or (raw_tool_info.get("toolAction") if isinstance(raw_tool_info, dict) else None)
        or step_update.get("tool_action")
        or raw.get("tool_action")
        or (raw_tool_info.get("tool_action") if isinstance(raw_tool_info, dict) else None)
        or step_update.get("action")
        or raw.get("action")
    )

    raw_source = (raw.get("source") or raw.get("sender") or "").strip().lower()
    raw_actor = raw.get("actor")
    event_type = (raw.get("event_type") or raw.get("type") or (f"step_{step_type}" if step_type else "activity")).strip()
    raw_message = raw.get("message") or raw.get("summary") or raw.get("short_message")

    # 2. Extract timestamp
    raw_ts = raw.get("timestamp") or raw.get("ts") or raw.get("time") or raw.get("created_at")
    time_display = "00:00:00"
    iso_timestamp = None
    if raw_ts:
        dt = parse_datetime(raw_ts)
        if dt:
            time_display = dt.strftime("%H:%M:%S")
            iso_timestamp = dt.isoformat()
        elif isinstance(raw_ts, str):
            iso_timestamp = raw_ts
            match = re.search(r"T(\d{2}:\d{2}:\d{2})", raw_ts)
            if match:
                time_display = match.group(1)
            else:
                time_display = raw_ts[:8]

    # 3. Classify event and derive semantic projection
    actor: str = "SYSTEM"
    action_text: str = ""
    message_text: str = ""
    rel_path: Optional[str] = None
    final_status: str = state or str(raw.get("status") or "info").upper()

    is_validator = (
        raw_source == "validator"
        or (raw_actor and str(raw_actor).upper() == "VALIDATOR")
        or "validator" in event_type.lower()
        or "build" in event_type.lower()
        or "git" in event_type.lower()
    )

    ev_upper = event_type.upper()
    msg_str = str(raw_message or raw_action or "").strip()
    msg_upper = msg_str.upper()

    # Case A: Bridge Validator
    if is_validator:
        actor = "VALIDATOR"
        ev_lower = event_type.lower()
        msg_lower = msg_str.lower()
        stat_upper = str(raw.get("status") or state or "").upper()

        if "git" in ev_lower or "git" in msg_lower:
            if stat_upper in ("PASS", "SUCCESS") or "pass" in msg_lower or "success" in msg_lower:
                action_text = "Git check PASS"
                final_status = "PASS"
            elif stat_upper in ("FAIL", "FAILED", "ERROR") or "fail" in msg_lower or "error" in msg_lower:
                action_text = "Git check FAIL"
                final_status = "FAIL"
            else:
                action_text = "Git check"
                final_status = stat_upper or "info"
        elif "build" in ev_lower or "build" in msg_lower or (raw_action and "build" in str(raw_action).lower()):
            if stat_upper in ("PASS", "SUCCESS") or "pass" in msg_lower or "success" in msg_lower:
                action_text = "Build PASS"
                final_status = "PASS"
            elif stat_upper in ("FAIL", "FAILED", "ERROR") or "fail" in msg_lower or "error" in msg_lower:
                action_text = "Build FAIL"
                final_status = "FAIL"
            elif state == "ACTIVE" or "start" in ev_lower or "iniciad" in msg_lower or "running" in msg_lower:
                action_text = "Build iniciado"
                final_status = "ACTIVE"
            else:
                action_text = sanitize_text(raw_action or raw_message or "Build", max_length=90)
                final_status = stat_upper or "info"
        elif "valida" in ev_lower or "valida" in msg_lower:
            if stat_upper in ("PASS", "SUCCESS") or "pass" in msg_lower or "success" in msg_lower:
                action_text = "Validação PASS"
                final_status = "PASS"
            elif stat_upper in ("FAIL", "FAILED", "ERROR") or "fail" in msg_lower or "error" in msg_lower:
                action_text = "Validação FAIL"
                final_status = "FAIL"
            else:
                action_text = "Validação iniciada"
                final_status = "ACTIVE"
        else:
            action_text = sanitize_text(raw_action or raw_message or "Validação", max_length=90)
            final_status = stat_upper or "info"

        message_text = action_text

    # Case B: Bridge Lifecycle & Recovery
    elif "MISSION_STARTED" in ev_upper or "MISSION STARTED" in msg_upper:
        actor = "SYSTEM"
        action_text = msg_str if (raw_message and "mission started" in raw_message.lower()) else "Missão iniciada"
        message_text = action_text
        final_status = "info"

    elif "MISSION_SUCCESS" in ev_upper or "MISSION SUCCESS" in msg_upper:
        actor = "SYSTEM"
        action_text = "Mission success"
        message_text = "Mission success"
        final_status = "SUCCESS"

    elif "MISSION_FAILED" in ev_upper or "MISSION FAILED" in msg_upper:
        actor = "SYSTEM"
        action_text = "Mission failed"
        message_text = "Mission failed"
        final_status = "FAILED"

    elif "PERMISSION RECOVERY" in msg_upper or "PERMISSION_RECOVERY" in ev_upper or "permission recovery" in msg_str.lower():
        actor = "SYSTEM"
        action_text = "Recuperação de permissão"
        message_text = "Recuperação de permissão"
        final_status = "info"

    # Case C: AGY Tool Execution (Always EXECUTOR)
    elif step_type == "tool" or tool_name:
        actor = "EXECUTOR"
        action_text, rel_path = derive_tool_action(tool_name, tool_args, raw_action, raw_source)
        if not action_text:
            return None
        message_text = action_text
        final_status = state or "info"

    # Case D: Agent Response (Always EXECUTOR, text_delta sanitized)
    elif step_type == "agent_response":
        actor = "EXECUTOR"
        useful_text = extract_useful_agent_response(text_delta or raw_message)
        if not useful_text:
            # Noise reduction: do not emit cards for empty agent_response steps
            return None
        action_text = useful_text
        message_text = useful_text
        final_status = state or "info"

    # Case E: User input
    elif step_type == "user_input":
        actor = "HUMAN"
        action_text = "Instruções da missão recebidas"
        message_text = "Instruções da missão recebidas"
        final_status = "info"

    # Case F: Checkpoint
    elif step_type == "checkpoint":
        actor = "SYSTEM"
        action_text = sanitize_text(raw_message or "Checkpoint criado", max_length=90)
        message_text = action_text
        final_status = "info"

    # Case G: Generic fallback — filter noise
    else:
        candidate_msg = raw_message or raw_action
        if not candidate_msg:
            # Empty step without information -> drop
            return None
        cleaned_msg = sanitize_text(candidate_msg, max_length=140)
        if not cleaned_msg or cleaned_msg.lower() in ("activity step", "activity", "step update", "step_update"):
            # Noise reduction: never create generic Activity step cards
            return None
        actor = normalize_actor(raw_actor, source=raw_source, event_type=event_type)
        action_text = cleaned_msg
        message_text = cleaned_msg
        final_status = state or "info"

    # Abbreviate conversation ID
    conv_id = raw.get("conversation_id") or raw.get("conv_id")
    conv_short = None
    if conv_id and isinstance(conv_id, str):
        conv_short = conv_id[:8] + "..." if len(conv_id) > 8 else conv_id

    return {
        "id": raw.get("id") or f"evt-{index}",
        "step_id": step_id,
        "step_type": step_type or None,
        "state": state or None,
        "timestamp": time_display,
        "iso_timestamp": iso_timestamp,
        "actor": actor,
        "source": raw_source or "bridge",
        "event_type": event_type,
        "status": final_status,
        "tool_name": tool_name if isinstance(tool_name, str) else None,
        "tool_action": action_text,
        "relative_path": rel_path,
        "message": message_text,
        "task_id": raw.get("task_id"),
        "cycle": raw.get("cycle"),
        "conversation_id_short": conv_short,
        "duration": None,
    }


def read_live_ndjson(bridge_root: str, max_events: int = MAX_LIVE_EVENTS) -> List[Dict[str, Any]]:
    """Read logs/live.ndjson and project a sanitized, noise-reduced list of useful events.
    Collapses ACTIVE + DONE steps of the same tool into a single DONE event with duration.
    Retains up to ~150 useful events.
    """
    ndjson_path = os.path.join(bridge_root, "logs", "live.ndjson")
    if not os.path.isfile(ndjson_path):
        return []

    try:
        with open(ndjson_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as exc:
        logger.warning(f"Error reading live.ndjson from {ndjson_path}: {exc}")
        return []

    if not lines:
        return []

    sanitized_events: List[Dict[str, Any]] = []
    # Key -> index in sanitized_events for collapsing ACTIVE + DONE
    pending_active: Dict[str, int] = {}

    for idx, line in enumerate(lines):
        parsed = parse_ndjson_line(line, idx + 1)
        if not parsed:
            continue

        step_id = parsed.get("step_id")
        tool_name = parsed.get("tool_name")
        rel_path = parsed.get("relative_path")
        actor = parsed.get("actor")
        state = (parsed.get("state") or parsed.get("status") or "").upper()

        # Build collapsing key
        step_key = None
        if step_id:
            step_key = f"id:{step_id}"
        elif tool_name:
            step_key = f"tool:{actor}:{tool_name}:{rel_path or ''}"

        if state == "ACTIVE":
            if step_key and step_key in pending_active:
                # Update existing active event in place
                active_idx = pending_active[step_key]
                sanitized_events[active_idx] = parsed
            else:
                curr_idx = len(sanitized_events)
                sanitized_events.append(parsed)
                if step_key:
                    pending_active[step_key] = curr_idx

        elif state in ("DONE", "COMPLETED", "FINISHED"):
            if step_key and step_key in pending_active:
                active_idx = pending_active.pop(step_key)
                active_ev = sanitized_events[active_idx]

                # Calculate duration between ACTIVE and DONE
                duration_str = None
                t_active = parse_datetime(active_ev.get("iso_timestamp"))
                t_done = parse_datetime(parsed.get("iso_timestamp"))
                if t_active and t_done:
                    diff_sec = (t_done - t_active).total_seconds()
                    duration_str = format_duration(diff_sec)

                parsed["status"] = "DONE"
                if duration_str:
                    parsed["duration"] = duration_str
                if not parsed.get("relative_path") and active_ev.get("relative_path"):
                    parsed["relative_path"] = active_ev.get("relative_path")
                if not parsed.get("tool_action") and active_ev.get("tool_action"):
                    parsed["tool_action"] = active_ev.get("tool_action")

                # Replace the ACTIVE card with the completed DONE card
                sanitized_events[active_idx] = parsed
            else:
                parsed["status"] = "DONE"
                sanitized_events.append(parsed)
        else:
            sanitized_events.append(parsed)

    # Retain at most max_events useful items
    if len(sanitized_events) > max_events:
        sanitized_events = sanitized_events[-max_events:]

    return sanitized_events


def scan_mission_started_events(bridge_root: str) -> List[Dict[str, Any]]:
    """Scan logs/live.ndjson for MISSION_STARTED records to extract metadata."""
    ndjson_path = os.path.join(bridge_root, "logs", "live.ndjson")
    if not os.path.isfile(ndjson_path):
        return []

    mission_events = []
    try:
        with open(ndjson_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except Exception:
                    continue
                if not isinstance(raw, dict):
                    continue
                ev_type = str(raw.get("event_type") or raw.get("type") or "").upper()
                msg = str(raw.get("message") or "").upper()
                if "MISSION_STARTED" in ev_type or "MISSION STARTED" in msg:
                    mission_events.append(raw)
    except Exception as exc:
        logger.debug(f"Error scanning live.ndjson for MISSION_STARTED: {exc}")

    return mission_events


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
                    return {
                        "status": data.get("status"),
                        "task_id": data.get("task_id"),
                        "branch": data.get("branch"),
                        "completed_at": data.get("completed_at") or data.get("timestamp"),
                        "summary": sanitize_text(data.get("summary") or data.get("message") or "", max_length=300),
                        "validation_passed": data.get("validation_passed", data.get("status") == "SUCCESS"),
                    }
            except Exception as exc:
                logger.debug(f"Could not parse result.json at {p}: {exc}")

    return None


def calculate_mission_elapsed(
    started_at_val: Any,
    status: str,
    raw_state: Dict[str, Any],
    result_data: Optional[Dict[str, Any]],
    events: List[Dict[str, Any]],
) -> Tuple[Optional[int], Optional[str]]:
    """Derive elapsed seconds and formatted time strictly factually.
    - If mission is RUNNING/WORKING: diff between started_at and now.
    - If mission is SUCCESS/FAILED/BLOCKED: diff between started_at and factual end (result, state, or last event).
    - If timestamps are insufficient: returns (None, None). NEVER returns fake 00:00.
    """
    if not started_at_val:
        return None, None

    dt_start = parse_datetime(started_at_val)
    if not dt_start:
        return None, None

    st = (status or "").strip().upper()
    is_running = st in ("AGENT_WORKING", "RUNNING", "IN_PROGRESS", "ACTIVE", "VALIDATING")

    if is_running:
        now = datetime.now(timezone.utc)
        diff = int((now - dt_start).total_seconds())
        if diff < 0:
            diff = 0
        return diff, format_elapsed(diff)

    # For non-running missions (SUCCESS, FAILED, BLOCKED, BLOCKED_HUMAN, COMPLETE, etc.):
    dt_end = None

    # 1. From result_data
    if result_data:
        end_cand = result_data.get("completed_at") or result_data.get("timestamp")
        if end_cand:
            dt_end = parse_datetime(end_cand)

    # 2. From raw_state
    if not dt_end:
        for k in ("updated_at", "ended_at", "completed_at", "finished_at"):
            if raw_state.get(k):
                dt_end = parse_datetime(raw_state[k])
                if dt_end:
                    break

    # 3. From last factual event in live.ndjson
    if not dt_end and events:
        for evt in reversed(events):
            iso_ts = evt.get("iso_timestamp")
            if iso_ts:
                dt_end = parse_datetime(iso_ts)
                if dt_end:
                    break

    if not dt_end:
        # Insufficient factual timestamps for end time
        return None, None

    diff = int((dt_end - dt_start).total_seconds())
    if diff < 0:
        diff = 0
    return diff, format_elapsed(diff)


def calculate_elapsed(started_at_val: Any) -> Tuple[Optional[int], Optional[str]]:
    """Backward-compatible helper."""
    return calculate_mission_elapsed(started_at_val, "AGENT_WORKING", {}, None, [])


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

    # 4. Scan MISSION_STARTED events to derive missing metadata
    mission_started_events = scan_mission_started_events(bridge_root)
    task_id = raw_state.get("task_id") or raw_state.get("current_task_id")

    # Match MISSION_STARTED for the current mission
    matching_m_event = None
    if task_id:
        for m_ev in mission_started_events:
            p_load = m_ev.get("payload") if isinstance(m_ev.get("payload"), dict) else {}
            if p_load.get("task_id") == task_id or m_ev.get("task_id") == task_id:
                matching_m_event = m_ev
                break

    if not matching_m_event and mission_started_events:
        matching_m_event = mission_started_events[0]

    derived_branch = None
    derived_started_at = None
    if matching_m_event:
        p_load = matching_m_event.get("payload") if isinstance(matching_m_event.get("payload"), dict) else {}
        derived_branch = p_load.get("branch") or matching_m_event.get("branch")
        derived_started_at = p_load.get("started_at") or matching_m_event.get("timestamp") or matching_m_event.get("ts")

    # Extract & derive mission parameters
    raw_status = (raw_state.get("status") or raw_state.get("state") or "AGENT_WORKING").strip().upper()
    cycle = raw_state.get("cycle") or raw_state.get("current_cycle") or 1

    # Branch: state.json -> result.json -> MISSION_STARTED payload
    branch = raw_state.get("branch") or raw_state.get("current_branch")
    if not branch and result_data:
        branch = result_data.get("branch")
    if not branch and derived_branch:
        branch = derived_branch

    # Started_at: derived from first MISSION_STARTED of current mission, then state.json
    started_at = derived_started_at or raw_state.get("started_at") or raw_state.get("start_time")

    conv_id = raw_state.get("conversation_id")
    conv_id_short = conv_id[:8] + "..." if conv_id and len(conv_id) > 8 else conv_id

    # Factual elapsed calculation
    elapsed_seconds, elapsed_formatted = calculate_mission_elapsed(
        started_at,
        raw_status,
        raw_state,
        result_data,
        events,
    )

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
