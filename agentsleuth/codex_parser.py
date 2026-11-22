"""Convert raw Codex JSONL records into normalized conversation objects."""

import json
import re

from .attachments import all_embedded_refs, extract_file_markers, extract_text_and_media
from .utils import get_turn, safe_text, short


def classify(record):
    p = record.get("payload") or {}
    outer = record.get("type")
    kind = p.get("type")
    if outer == "response_item":
        if kind in {"custom_tool_call", "function_call"}:
            return "Tool Call", kind
        if kind in {"custom_tool_call_output", "function_call_output"}:
            return "Tool Output", kind
        if kind == "message":
            role = p.get("role")
            if role == "user":
                return "User Prompt", kind
            if role == "assistant":
                return "Agent Response", kind
        if kind == "UserMessage":
            return "User Prompt", kind
        if kind == "AgentMessage":
            return "Agent Response", kind
    elif outer == "event_msg" and kind == "item_completed":
        item_kind = (p.get("item") or {}).get("type")
        mapping = {
            "UserMessage": "User Prompt",
            "AgentMessage": "Agent Response",
            "CommandExecution": "Command Execution",
            "FileChange": "File Changes",
            "McpToolCall": "MCP Tool Calling",
        }
        if item_kind in mapping:
            return mapping[item_kind], item_kind
    return None

def describe(record, category):
    p = record.get("payload") or {}
    item = p.get("item") or {}
    if category == "Tool Call":
        return f"{p.get('name', 'tool')} | {short(p.get('input') or p.get('arguments'), 180)}"
    if category == "Tool Output":
        return f"{p.get('call_id', '')} | {short(p.get('output'), 160)}"
    if category == "Command Execution":
        cmd = item.get("command") or []
        cmd_text = cmd[-1] if isinstance(cmd, list) and cmd else cmd
        return f"exit={item.get('exit_code')} pid={item.get('process_id')} | {short(cmd_text, 160)}"
    if category == "File Changes":
        changes = item.get("changes") or {}
        return f"{item.get('status', '')} | {short(', '.join(changes.keys()), 170)}"
    if category == "MCP Tool Calling":
        return f"{item.get('server', '')}/{item.get('tool', '')} | {short(item.get('arguments'), 120)}"
    content = p.get("content") or item.get("content") or []
    if isinstance(content, str):
        return short(content)
    if isinstance(content, list):
        chunks = []
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") in ("input_image", "input_audio"):
                chunks.append("[" + part["type"] + "]")
            elif isinstance(part.get("text"), str):
                chunks.append(part["text"])
        return short(" | ".join(chunks), 220)
    return short(content)

def normalize_message(record):
    p = record.get("payload") or {}
    kind, outer = p.get("type"), record.get("type")
    if outer == "response_item" and kind == "message":
        role = p.get("role")
        if role not in {"user", "assistant"}:
            return None
        content = p.get("content") or []
        phase = p.get("phase") or ""
        item_id = p.get("id")
        origin = "response_item"
    elif outer == "event_msg" and kind == "item_completed":
        item = p.get("item") or {}
        if item.get("type") not in {"UserMessage", "AgentMessage"}:
            return None
        role = "user" if item["type"] == "UserMessage" else "assistant"
        content = item.get("content") or []
        phase = item.get("phase") or ""
        item_id = item.get("id")
        origin = "event_msg"
    else:
        return None
    body, media = extract_text_and_media(content)
    body, file_refs = extract_file_markers(body)
    if not body and not media and not file_refs:
        return None
    # Rollouts may include injected environment metadata as a user-role message.
    # This is kept in the evidence, but not presented as a user-written prompt.
    if role == "user" and body.lstrip().startswith("<environment_context>"):
        return None
    return {
        "kind": "message", "role": role, "text": body, "attachments": media,
        "file_refs": file_refs,
        "phase": phase, "origin": origin, "item_id": item_id or "",
        "ordinal": record["ordinal"], "timestamp": record.get("timestamp", ""),
        "turn_id": get_turn(record),
    }

def js_commands(input_text):
    """Best-effort parser for literal tools.exec_command({cmd: "..."}).

    It is intentionally *not* a JavaScript evaluator. Dynamic expressions are
    not expanded or executed; unmatched commands remain unresolved.
    """
    text = input_text or ""
    pattern = re.compile(
        r'tools\.exec_command\s*\(\s*\{\s*["\']?cmd["\']?\s*:\s*'
        r'("(?:\\.|[^"\\])*")', re.S
    )
    result = []
    for m in pattern.finditer(text):
        try:
            result.append(json.loads(m.group(1)))
        except (ValueError, json.JSONDecodeError):
            pass
    return result

def normalize_activity(record):
    p = record.get("payload") or {}
    item = p.get("item") or {}
    if record.get("type") != "event_msg" or p.get("type") != "item_completed":
        return None
    kind = item.get("type")
    if kind not in {"CommandExecution", "FileChange", "McpToolCall", "DynamicToolCall", "CollabAgentToolCall"}:
        return None
    command = item.get("command") or []
    cmd = (command[-1] if isinstance(command, list) and command else safe_text(command))
    if kind == "CommandExecution":
        display = cmd
        details = (f"Process ID: {item.get('process_id')}\n"
                   f"Directory: {item.get('cwd', '')}\n"
                   f"Status: {item.get('status', '')}\nExit code: {item.get('exit_code')}\n"
                   f"Command:\n{safe_text(command)}\n\nOutput:\n{safe_text(item.get('aggregated_output'))}")
    elif kind == "FileChange":
        change_lines = []
        for filename, value in (item.get("changes") or {}).items():
            change_lines.append(f"{filename}  [{(value or {}).get('type', 'change')}]")
        display = "\n".join(change_lines) or "File changes"
        details = (f"Changes:\n{display}\n\n"
                   f"stdout:\n{safe_text(item.get('stdout'))}\n\n"
                   f"stderr:\n{safe_text(item.get('stderr'))}")
    else:
        display = f"{kind}: {item.get('tool') or item.get('name') or item.get('server') or ''}"
        details = safe_text(item)
    return {
        "kind": "activity", "activity_type": kind, "item_id": item.get("id") or "",
        "ordinal": record["ordinal"], "timestamp": record.get("timestamp", ""),
        "turn_id": get_turn(record), "status": item.get("status", ""),
        "exit_code": item.get("exit_code"), "pid": item.get("process_id"),
        "cwd": item.get("cwd"), "command": cmd,
        "display": display, "details": details,
        "attachments": all_embedded_refs(item),
        "item": item,
    }

def normalize_call(record):
    p = record.get("payload") or {}
    if record.get("type") != "response_item" or p.get("type") not in {"custom_tool_call", "function_call"}:
        return None
    input_value = p.get("input") if p.get("input") is not None else p.get("arguments")
    return {
        "kind": "tool", "ordinal": record["ordinal"], "timestamp": record.get("timestamp", ""),
        "turn_id": get_turn(record), "call_id": p.get("call_id") or "",
        "tool_name": p.get("name") or "unknown", "tool_type": p.get("type"),
        "input": safe_text(input_value), "nested_commands": js_commands(input_value),
        "attachments": all_embedded_refs(p), "activities": [],
        "output": None, "relation": "not_correlated",
    }

def normalize_output(record):
    p = record.get("payload") or {}
    if record.get("type") != "response_item" or p.get("type") not in {"custom_tool_call_output", "function_call_output"}:
        return None
    output = p.get("output")
    content, _ = extract_text_and_media(output)
    return {
        "kind": "tool_output", "ordinal": record["ordinal"],
        "timestamp": record.get("timestamp", ""), "turn_id": get_turn(record),
        "call_id": p.get("call_id") or "", "text": content or safe_text(output),
        "attachments": all_embedded_refs(output),
    }

def deduplicate_messages(messages):
    # Drop alternate event_msg item_completed copies if corresponding
    # response_item.message text/role/phase/turn appears nearby.
    response_entries = [m for m in messages if m["origin"] == "response_item"]
    result = []
    for m in messages:
        if m["origin"] == "event_msg":
            duplicated = any(
                r["turn_id"] == m["turn_id"] and
                r["role"] == m["role"] and
                r["text"].strip() == m["text"].strip() and
                r["phase"] == m["phase"] and
                abs(r["ordinal"] - m["ordinal"]) <= 7
                for r in response_entries
            )
            if duplicated:
                continue
        result.append(m)
    return result

def correlate(calls, outputs, activities):
    outputs_by_id = {}
    for output in outputs:
        if output["call_id"]:
            outputs_by_id.setdefault(output["call_id"], []).append(output)
    matched_output_ids = set()
    for call in calls:
        choices = [o for o in outputs_by_id.get(call["call_id"], [])
                   if o["ordinal"] > call["ordinal"] and
                   (not call["turn_id"] or not o["turn_id"] or call["turn_id"] == o["turn_id"])]
        if choices:
            output = min(choices, key=lambda o: o["ordinal"])
            call["output"] = output
            matched_output_ids.add(id(output))

    # Avoid crediting the same activity to overlapping calls. Strong exact
    # command matches are preferred to generic interval matches.
    for activity in activities:
        candidates = []
        for call in calls:
            end = call["output"]["ordinal"] if call["output"] else None
            if not call["turn_id"] or call["turn_id"] != activity["turn_id"]:
                continue
            if activity["ordinal"] <= call["ordinal"]:
                continue
            if end is None or activity["ordinal"] >= end:
                continue
            score = 1
            if activity["activity_type"] == "CommandExecution":
                if activity["command"] in call["nested_commands"]:
                    score = 10
                elif not call["nested_commands"] and activity["command"] and activity["command"] in call["input"]:
                    score = 7
            elif activity["activity_type"] == "FileChange" and "tools.apply_patch" in call["input"]:
                score = 8
            elif activity["activity_type"] in {"McpToolCall", "DynamicToolCall"}:
                if "mcp" in call["tool_name"].lower() or "tools." in call["input"]:
                    score = 3
            candidates.append((score, call))
        if not candidates:
            continue
        candidates.sort(key=lambda x: -x[0])
        score, winner = candidates[0]
        if len(candidates) > 1 and candidates[1][0] == score:
            # Unresolved ambiguity. Preserve as standalone for honest analysis.
            activity["correlation_note"] = "Multiple overlapping candidate tool calls"
            continue
        activity["correlation_note"] = (
            "inferred_command_match" if score >= 7 else
            "candidate_ordinal_window_only"
        )
        winner["activities"].append(activity)
        activity["parent_call_id"] = winner["call_id"]
        winner["relation"] = "contains_correlated_activities"
    return matched_output_ids

