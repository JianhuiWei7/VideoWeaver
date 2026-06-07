import argparse
import csv
import json
import re
import shlex
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_IGNORED_TOOLS_BY_FORMAT = {
    "openclaw": {"read", "edit"},
    "claude_code": {"Read", "Edit"},
    "codex": {"write_stdin"},
}
DEFAULT_IGNORED_TOOLS = DEFAULT_IGNORED_TOOLS_BY_FORMAT["openclaw"]
DEFAULT_IGNORED_COMMANDS = {"/status"}
DEFAULT_REPORT_FILE_NAME = "execution_error_report.json"

ERROR_TEXT_PATTERNS = [
    re.compile(r"❌\s*[^。\n]*(?:失败|error)", re.IGNORECASE),
    re.compile(r"\bError code:\s*[45]\d\d\b", re.IGNORECASE),
    re.compile(r"\b(?:BadRequest|InvalidParameter|Unauthorized|Forbidden|RateLimit)\b"),
    re.compile(r"\bTraceback \(most recent call last\):"),
    re.compile(r"\bExit code ([1-9]\d*)\b"),
    re.compile(r"\b(?:Command|Process) exited with code ([1-9]\d*)\b"),
    re.compile(r"\bexitCode['\"]?\s*[:=]\s*([1-9]\d*)\b"),
    re.compile(r"\b(?:FileNotFoundError|ModuleNotFoundError|PermissionError|TimeoutError)\b"),
    re.compile(r"\b(?:ENOENT|ECONNREFUSED|ETIMEDOUT|ENOTFOUND)\b"),
]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                rows.append(
                    {
                        "type": "parse_error",
                        "line_no": line_no,
                        "error": f"{exc.__class__.__name__}: {exc}",
                    }
                )
                continue
            row["_line_no"] = line_no
            rows.append(row)
    return rows


def is_under_evals(path: str | Path) -> bool:
    return "evals" in Path(path).parts


def content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    texts = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            texts.append(str(item.get("text", "")))
        elif item.get("type") == "tool_result":
            texts.append(str(item.get("content", "")))
    return "\n".join(texts)


def first_openclaw_tool_call(message: dict[str, Any]) -> dict[str, Any] | None:
    for item in message.get("content") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") in {"toolCall", "tool_call"}:
            return item
    return None


def first_claude_tool_call(message: dict[str, Any]) -> dict[str, Any] | None:
    for item in message.get("content") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "tool_use":
            return {
                "id": item.get("id"),
                "name": item.get("name"),
                "arguments": item.get("input"),
            }
    return None


def detect_trace_format(rows: list[dict[str, Any]]) -> str:
    openclaw_signals = 0
    claude_code_signals = 0
    codex_signals = 0
    for row in rows:
        message = row.get("message") if isinstance(row.get("message"), dict) else {}
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        role = message.get("role")
        if role == "toolResult" or message.get("toolName"):
            openclaw_signals += 1
        if role == "assistant" and first_openclaw_tool_call(message):
            openclaw_signals += 1
        if row.get("type") in {"custom-title", "agent-name", "queue-operation", "last-prompt"}:
            claude_code_signals += 1
        if row.get("toolUseResult") is not None:
            claude_code_signals += 1
        if role == "assistant" and first_claude_tool_call(message):
            claude_code_signals += 1
        if is_claude_tool_result_message(message):
            claude_code_signals += 1
        if row.get("type") in {"session_meta", "turn_context"}:
            codex_signals += 1
        if row.get("type") in {"response_item", "event_msg"}:
            codex_signals += 1
        if payload.get("type") in {
            "function_call",
            "function_call_output",
            "custom_tool_call",
            "custom_tool_call_output",
        }:
            codex_signals += 1

    active_formats = sum(bool(count) for count in (openclaw_signals, claude_code_signals, codex_signals))
    if active_formats > 1:
        return "mixed"
    if codex_signals:
        return "codex"
    if claude_code_signals:
        return "claude_code"
    if openclaw_signals:
        return "openclaw"
    return "unknown"


def short_text(text: str, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def error_focused_text(text: str, limit: int = 500) -> str:
    for pattern in ERROR_TEXT_PATTERNS:
        match = pattern.search(text)
        if match:
            start = max(match.start() - 160, 0)
            return short_text(text[start:], limit)
    return short_text(text, limit)


def command_summary(arguments: Any) -> str:
    if not isinstance(arguments, dict):
        return ""
    command = arguments.get("command") or arguments.get("cmd")
    if not isinstance(command, str):
        return ""
    try:
        parts = shlex.split(command)
    except ValueError:
        return short_text(command, 180)
    if not parts:
        return ""
    if len(parts) >= 2 and Path(parts[0]).name.startswith("python"):
        return " ".join(parts[:2])
    return " ".join(parts[:4])


def command_text(arguments: Any) -> str:
    if not isinstance(arguments, dict):
        return ""
    command = arguments.get("command") or arguments.get("cmd")
    return command.strip() if isinstance(command, str) else ""


def should_ignore_call(tool_name: str, arguments: Any, ignored_commands: set[str]) -> bool:
    command = command_text(arguments)
    return tool_name.lower() in {"exec", "bash", "exec_command"} and command in ignored_commands


def should_ignore_tool(tool_name: str, ignored_tools: set[str]) -> bool:
    return tool_name in ignored_tools or tool_name.lower() in ignored_tools


def is_claude_tool_result_message(message: dict[str, Any]) -> bool:
    if message.get("role") != "user":
        return False
    content = message.get("content")
    return isinstance(content, list) and any(
        isinstance(item, dict) and item.get("type") == "tool_result"
        for item in content
    )


def iter_claude_tool_result_messages(
    row: dict[str, Any],
    message: dict[str, Any],
    calls_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    content = message.get("content")
    if not isinstance(content, list):
        return []

    normalized = []
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "tool_result":
            continue

        call_id = item.get("tool_use_id") or item.get("toolCallId")
        call_info = calls_by_id.get(str(call_id)) if call_id else {}
        if call_info is None:
            call_info = {}
        tool_name = call_info.get("tool") or "unknown"
        result_text = item.get("content", "")
        if not isinstance(result_text, str):
            result_text = json.dumps(result_text, ensure_ascii=False, default=str)

        tool_use_result = row.get("toolUseResult")
        if isinstance(tool_use_result, dict):
            details = dict(tool_use_result)
            details.setdefault("aggregated", result_text)
        elif tool_use_result is not None:
            details = {"aggregated": str(tool_use_result)}
        else:
            details = {"aggregated": result_text}

        is_error = item.get("is_error") is True
        if isinstance(tool_use_result, str) and tool_use_result.startswith("Error:"):
            is_error = True
        if isinstance(tool_use_result, dict) and tool_use_result.get("success") is False:
            is_error = True

        normalized.append(
            {
                "role": "toolResult",
                "toolName": tool_name,
                "toolCallId": call_id,
                "content": [{"type": "text", "text": result_text}],
                "details": details,
                "isError": is_error,
            }
        )
    return normalized


def parse_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def codex_tool_call(row: dict[str, Any]) -> dict[str, Any] | None:
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    payload_type = payload.get("type")
    if payload_type == "function_call":
        return {
            "id": payload.get("call_id"),
            "name": payload.get("name") or "unknown",
            "arguments": parse_json_object(payload.get("arguments")),
        }
    if payload_type == "custom_tool_call":
        return {
            "id": payload.get("call_id"),
            "name": payload.get("name") or "unknown",
            "arguments": {"input": payload.get("input")},
        }
    return None


def parse_codex_exit_code(output: str, payload: dict[str, Any]) -> int | None:
    if payload.get("type") == "custom_tool_call_output":
        parsed = parse_json_object(payload.get("output"))
        metadata = parsed.get("metadata") if isinstance(parsed.get("metadata"), dict) else {}
        exit_code = metadata.get("exit_code")
        if isinstance(exit_code, int):
            return exit_code
    match = re.search(r"\bProcess exited with code ([0-9]+)\b", output)
    if match:
        return int(match.group(1))
    match = re.search(r"\bCommand exited with code ([0-9]+)\b", output)
    if match:
        return int(match.group(1))
    match = re.search(r"\bExit code ([0-9]+)\b", output)
    if match:
        return int(match.group(1))
    return None


def codex_tool_result_message(
    row: dict[str, Any],
    calls_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    if payload.get("type") not in {"function_call_output", "custom_tool_call_output"}:
        return None
    call_id = payload.get("call_id")
    call_info = calls_by_id.get(str(call_id)) if call_id else {}
    if call_info is None:
        call_info = {}
    tool_name = call_info.get("tool") or "unknown"
    output = payload.get("output", "")
    if not isinstance(output, str):
        output = json.dumps(output, ensure_ascii=False, default=str)
    exit_code = parse_codex_exit_code(output, payload)
    details = {
        "status": "completed",
        "aggregated": output,
    }
    if exit_code is not None:
        details["exitCode"] = exit_code
    return {
        "role": "toolResult",
        "toolName": tool_name,
        "toolCallId": call_id,
        "content": [{"type": "text", "text": output}],
        "details": details,
        "isError": isinstance(exit_code, int) and exit_code != 0,
    }


def is_ignorable_non_program_error(evidence: Any) -> bool:
    text = str(evidence or "").lower()
    return (
        "tpm" in text
        or "tokens per minute" in text
        or "ratelimit" in text
        or "rate limit" in text
        or "too many requests" in text
        or "toomanyrequests" in text
        or "modelaccounttpmratelimitexceeded" in text
    )


def is_parallel_tool_cancellation(evidence: Any) -> bool:
    text = str(evidence or "").lower()
    return (
        "cancelled: parallel tool call" in text
        and "errored" in text
    )


def extract_error_text(
    message: dict[str, Any],
    ignore_parallel_cancellation: bool = False,
) -> tuple[bool, str, str]:
    """Return (is_error, reason, evidence) for a toolResult message."""
    details = message.get("details") if isinstance(message.get("details"), dict) else {}
    text = content_to_text(message.get("content"))
    evidence_blob = text or json.dumps(details, ensure_ascii=False)

    # Claude Code reports sibling tool calls as cancelled when one parallel
    # tool call fails. Only ignore those cancelled siblings when the preceding
    # root failure was a known non-program issue such as TPM/rate limiting.
    if is_parallel_tool_cancellation(evidence_blob):
        if ignore_parallel_cancellation:
            return False, "", ""
        return True, "parallel_tool_cancelled", short_text(evidence_blob)

    exit_code = details.get("exitCode")
    if isinstance(exit_code, int) and exit_code != 0:
        evidence = details.get("aggregated") or text or json.dumps(details, ensure_ascii=False)
        if is_ignorable_non_program_error(evidence):
            return False, "", ""
        return True, f"exit_code_{exit_code}", error_focused_text(str(evidence))
    if isinstance(exit_code, int) and exit_code == 0:
        return False, "", ""

    if message.get("isError") is True:
        if is_ignorable_non_program_error(evidence_blob):
            return False, "", ""
        return True, "tool_result_is_error", short_text(evidence_blob)

    status = str(details.get("status", "")).lower()
    if status == "error":
        evidence = details.get("error") or text or json.dumps(details, ensure_ascii=False)
        if is_ignorable_non_program_error(evidence):
            return False, "", ""
        return True, "details_status_error", short_text(str(evidence))

    # Some older traces put a structured error only in the content text while
    # leaving isError=false, so parse JSON-like tool output before regex checks.
    stripped = text.strip()
    if stripped.startswith("{") and '"status"' in stripped and '"error"' in stripped:
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and str(parsed.get("status", "")).lower() == "error":
            if is_ignorable_non_program_error(parsed.get("error") or text):
                return False, "", ""
            return True, "content_status_error", short_text(str(parsed.get("error") or text))

    blob_parts = []
    for key in ("error", "aggregated", "tail"):
        value = details.get(key)
        if value:
            blob_parts.append(str(value))
    # Fall back to plain content for command/process-like results only; this
    # avoids counting skill documents that merely describe failure modes.
    if str(message.get("toolName") or "").lower() in {"exec", "process", "bash", "shell"}:
        blob_parts.append(text)
    blob = "\n".join(blob_parts)
    for pattern in ERROR_TEXT_PATTERNS:
        match = pattern.search(blob)
        if match:
            if is_ignorable_non_program_error(blob):
                return False, "", ""
            return True, f"text_match:{pattern.pattern}", short_text(blob[max(match.start() - 160, 0) :])

    return False, "", ""


def classify_error(tool_name: str, evidence: str, arguments: Any) -> str:
    blob = f"{tool_name}\n{json.dumps(arguments, ensure_ascii=False, default=str)}\n{evidence}".lower()
    evidence_blob = f"{tool_name}\n{evidence}".lower()
    if "duration" in blob and ("invalidparameter" in blob or "not valid" in blob):
        return "invalid_duration_parameter"
    if "found " in blob and "occurrences" in blob and "text must be unique" in blob:
        return "non_unique_edit_match"
    if "enoent" in blob or "no such file or directory" in blob or "filenotfounderror" in blob:
        return "missing_file_or_path"
    if "permission" in blob or "forbidden" in blob or "unauthorized" in blob:
        return "permission_or_auth"
    if "ratelimit" in blob or "rate limit" in blob:
        return "rate_limit"
    if "timeout" in evidence_blob or "timed out" in evidence_blob or "etimedout" in evidence_blob:
        return "timeout"
    if "traceback" in blob or "exception" in blob:
        return "python_exception"
    return "execution_error"


def find_start_line(rows: list[dict[str, Any]], start_user_index: int) -> int:
    if start_user_index <= 1:
        return 1
    user_seen = 0
    for row in rows:
        message = row.get("message") if isinstance(row.get("message"), dict) else {}
        if (
            message.get("role") == "user"
            and not row.get("isMeta")
            and not is_claude_tool_result_message(message)
        ):
            user_seen += 1
            if user_seen == start_user_index:
                return int(row.get("_line_no") or 1)
    return 1


def analyze_trace_file(
    path: str | Path,
    start_user_index: int = 2,
    ignored_tools: set[str] | None = None,
    ignored_commands: set[str] | None = None,
) -> dict[str, Any]:
    path = Path(path)
    ignored_commands = set(DEFAULT_IGNORED_COMMANDS if ignored_commands is None else ignored_commands)
    rows = load_jsonl(path)
    trace_format = detect_trace_format(rows)
    default_ignored_tools = DEFAULT_IGNORED_TOOLS_BY_FORMAT.get(trace_format, set())
    ignored_tools = set(default_ignored_tools if ignored_tools is None else ignored_tools)
    start_line = find_start_line(rows, start_user_index)
    calls_by_id: dict[str, dict[str, Any]] = {}
    last_call_by_tool: dict[str, dict[str, Any]] = {}
    ignored_call_ids = set()
    tool_calls = []
    tool_results = []
    errors = []
    ignore_parallel_cancellations = False

    def record_tool_result(message: dict[str, Any], line_no: int | None) -> None:
        nonlocal ignore_parallel_cancellations
        tool_name = str(message.get("toolName") or "unknown")
        if should_ignore_tool(tool_name, ignored_tools):
            return
        call_id = message.get("toolCallId")
        if call_id and str(call_id) in ignored_call_ids:
            return
        call_info = calls_by_id.get(str(call_id)) if call_id else None
        if call_info is None:
            call_info = last_call_by_tool.get(tool_name, {})

        details = message.get("details") if isinstance(message.get("details"), dict) else {}
        result_info = {
            "line": line_no,
            "call_id": call_id,
            "tool": tool_name,
            "details_status": details.get("status"),
            "exit_code": details.get("exitCode"),
        }
        tool_results.append(result_info)

        text = content_to_text(message.get("content"))
        evidence_blob = text or json.dumps(details, ensure_ascii=False)
        is_parallel_cancellation = is_parallel_tool_cancellation(evidence_blob)
        is_error, reason, evidence = extract_error_text(
            message,
            ignore_parallel_cancellation=ignore_parallel_cancellations,
        )
        if is_parallel_cancellation and ignore_parallel_cancellations:
            return
        if not is_parallel_cancellation:
            ignore_parallel_cancellations = is_ignorable_non_program_error(evidence_blob)
        if is_error:
            errors.append(
                {
                    "line": line_no,
                    "call_line": call_info.get("line"),
                    "call_id": call_id,
                    "tool": tool_name,
                    "category": classify_error(tool_name, evidence, call_info.get("arguments")),
                    "reason": reason,
                    "command_summary": call_info.get("command_summary", ""),
                    "arguments": call_info.get("arguments"),
                    "evidence": evidence,
                }
            )

    for row in rows:
        if row.get("type") == "parse_error":
            errors.append(
                {
                    "line": row.get("line_no"),
                    "tool": "jsonl",
                    "category": "bad_json_line",
                    "reason": row.get("error"),
                    "evidence": row.get("error"),
                }
            )
            continue

        message = row.get("message") if isinstance(row.get("message"), dict) else {}
        role = message.get("role")
        line_no = row.get("_line_no")
        if isinstance(line_no, int) and line_no < start_line:
            continue

        if trace_format in {"codex", "mixed"}:
            call = codex_tool_call(row)
            if call:
                tool_name = str(call.get("name") or "unknown")
                if should_ignore_tool(tool_name, ignored_tools):
                    if call.get("id"):
                        ignored_call_ids.add(str(call.get("id")))
                    continue
                if should_ignore_call(tool_name, call.get("arguments"), ignored_commands):
                    if call.get("id"):
                        ignored_call_ids.add(str(call.get("id")))
                    continue
                call_info = {
                    "line": line_no,
                    "call_id": call.get("id"),
                    "tool": tool_name,
                    "arguments": call.get("arguments"),
                    "command_summary": command_summary(call.get("arguments")),
                }
                tool_calls.append(call_info)
                if call_info["call_id"]:
                    calls_by_id[str(call_info["call_id"])] = call_info
                if call_info["tool"]:
                    last_call_by_tool[str(call_info["tool"])] = call_info
                continue

            result_message = codex_tool_result_message(row, calls_by_id)
            if result_message:
                record_tool_result(result_message, line_no)
                continue

        if role == "assistant":
            if trace_format == "openclaw":
                call = first_openclaw_tool_call(message)
            elif trace_format == "claude_code":
                call = first_claude_tool_call(message)
            elif trace_format == "mixed":
                call = first_openclaw_tool_call(message) or first_claude_tool_call(message)
            else:
                call = None
            if call:
                tool_name = str(call.get("name") or "unknown")
                if should_ignore_tool(tool_name, ignored_tools):
                    if call.get("id"):
                        ignored_call_ids.add(str(call.get("id")))
                    continue
                if should_ignore_call(tool_name, call.get("arguments"), ignored_commands):
                    if call.get("id"):
                        ignored_call_ids.add(str(call.get("id")))
                    continue
                call_info = {
                    "line": line_no,
                    "call_id": call.get("id"),
                    "tool": tool_name,
                    "arguments": call.get("arguments"),
                    "command_summary": command_summary(call.get("arguments")),
                }
                tool_calls.append(call_info)
                if call_info["call_id"]:
                    calls_by_id[str(call_info["call_id"])] = call_info
                if call_info["tool"]:
                    last_call_by_tool[str(call_info["tool"])] = call_info
            continue

        if trace_format == "claude_code" and is_claude_tool_result_message(message):
            for normalized_message in iter_claude_tool_result_messages(row, message, calls_by_id):
                record_tool_result(normalized_message, line_no)
            continue

        if trace_format == "openclaw":
            if role != "toolResult":
                continue
            record_tool_result(message, line_no)
            continue

        if trace_format == "mixed":
            if is_claude_tool_result_message(message):
                for normalized_message in iter_claude_tool_result_messages(row, message, calls_by_id):
                    record_tool_result(normalized_message, line_no)
            elif role == "toolResult":
                record_tool_result(message, line_no)

    tool_counter = Counter(call["tool"] or "unknown" for call in tool_calls)
    tool_result_counter = Counter(result["tool"] or "unknown" for result in tool_results)
    error_counter = Counter(error["tool"] or "unknown" for error in errors)
    category_counter = Counter(error["category"] for error in errors)
    return {
        "schema_version": 1,
        "path": str(path),
        "trace_format": trace_format,
        "start_user_index": start_user_index,
        "start_line": start_line,
        "ignored_tools": sorted(ignored_tools),
        "ignored_commands": sorted(ignored_commands),
        "line_count": len(rows),
        "total_execution_count": len(tool_results),
        "error_execution_count": len(errors),
        "tool_call_count": len(tool_calls),
        "tool_result_count": len(tool_results),
        "error_count": len(errors),
        "error_rate": (len(errors) / len(tool_results)) if tool_results else 0.0,
        "tool_call_counts": dict(sorted(tool_counter.items())),
        "tool_result_counts_by_tool": dict(sorted(tool_result_counter.items())),
        "error_counts_by_tool": dict(sorted(error_counter.items())),
        "error_counts_by_category": dict(sorted(category_counter.items())),
        "errors": errors,
    }


def execution_error_report_path(trace_path: str | Path) -> Path:
    trace_path = Path(trace_path)
    return trace_path.parent / "evals" / DEFAULT_REPORT_FILE_NAME


def simplify_arguments(arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        return {}
    simplified = {}
    for key in ("command", "cmd", "path", "output", "output_file_name", "sessionId", "action"):
        if key in arguments:
            value = arguments[key]
            simplified[key] = short_text(value, 260) if isinstance(value, str) else value
    return simplified


def concise_reason(evidence: Any) -> str:
    text = short_text(str(evidence or ""), 800)
    message_match = re.search(
        r"['\"]message['\"]:\s*['\"](.+?)(?:\s+Request id:|['\"]\s*,\s*['\"]param)",
        text,
        flags=re.IGNORECASE,
    )
    if message_match:
        return short_text(message_match.group(1), 320)
    simple_patterns = [
        r"(/bin/bash:[^。]+)",
        r"(Tool [^。]+ not found)",
        r"(Web fetch failed \([^)]+\):[^。]+)",
        r"(Reference image not found:[^。]+)",
        r"(Command exited with code \d+)",
        r"(Process exited with code \d+)",
    ]
    for pattern in simple_patterns:
        match = re.search(pattern, text)
        if match:
            return short_text(match.group(1), 320)
    traceback_match = re.findall(r"([A-Za-z_][\w.]*Error:[^。]+|[A-Za-z_][\w.]*Exception:[^。]+)", text)
    if traceback_match:
        return short_text(traceback_match[-1], 320)
    return short_text(text, 320)


def build_concise_report(report: dict[str, Any]) -> dict[str, Any]:
    concise_errors = []
    for error in report.get("errors", []):
        concise_errors.append(
            {
                "toolName": error.get("tool"),
                "line": error.get("line"),
                "where": error.get("command_summary") or f"trace line {error.get('line')}",
                "why": concise_reason(error.get("evidence")),
                "command": error.get("command_summary") or None,
            }
        )
    return {
        "trace_path": report.get("path"),
        "trace_format": report.get("trace_format", "unknown"),
        "total_execution_count": report.get("total_execution_count", 0),
        "error_execution_count": report.get("error_execution_count", 0),
        "error_rate": report.get("error_rate", 0.0),
        "toolNames": sorted((report.get("tool_result_counts_by_tool") or {}).keys()),
        "tool_result_counts_by_tool": report.get("tool_result_counts_by_tool", {}),
        "errors": concise_errors,
    }


def write_execution_error_report(
    jsonl_path: str | Path,
    start_user_index: int = 2,
    ignored_tools: set[str] | None = None,
    ignored_commands: set[str] | None = None,
    report_path: str | Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Analyze one trace and write evals/execution_error_report.json next to it.

    The default output path is:
        <jsonl所在文件夹>/evals/execution_error_report.json
    """
    if is_under_evals(jsonl_path):
        raise ValueError(f"Refusing to analyze eval trace under evals/: {jsonl_path}")

    report = analyze_trace_file(
        jsonl_path,
        start_user_index=start_user_index,
        ignored_tools=ignored_tools,
        ignored_commands=ignored_commands,
    )
    output_path = Path(report_path) if report_path is not None else execution_error_report_path(jsonl_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    concise_report = build_concise_report(report)
    output_path.write_text(
        json.dumps(concise_report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report["report_path"] = str(output_path)
    report["concise_report"] = concise_report
    return output_path, report


def load_execution_error_report(report_path: str | Path) -> dict[str, Any]:
    return json.loads(Path(report_path).read_text(encoding="utf-8"))


def find_trace_files(inputs: list[Path], direct_original_react_only: bool = False) -> list[Path]:
    files = []
    for path in inputs:
        if path.is_file():
            if path.suffix == ".jsonl" and not is_under_evals(path):
                files.append(path)
        elif path.is_dir():
            if direct_original_react_only:
                files.extend(
                    sorted(
                        child / "original_ReAct.jsonl"
                        for child in path.iterdir()
                        if child.is_dir() and (child / "original_ReAct.jsonl").is_file()
                        and not is_under_evals(child / "original_ReAct.jsonl")
                    )
                )
            else:
                files.extend(p for p in sorted(path.rglob("*.jsonl")) if not is_under_evals(p))
    return files


def summarize_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    category_counter = Counter()
    tool_counter = Counter()
    total_execution_count = 0
    error_execution_count = 0
    tasks_with_errors = 0
    for report in reports:
        total_execution_count += report["total_execution_count"]
        error_execution_count += report["error_execution_count"]
        if report["error_execution_count"]:
            tasks_with_errors += 1
        category_counter.update(report["error_counts_by_category"])
        tool_counter.update(report["error_counts_by_tool"])
    return {
        "trace_count": len(reports),
        "total_execution_count": total_execution_count,
        "error_execution_count": error_execution_count,
        "tasks_with_errors": tasks_with_errors,
        "task_error_rate": tasks_with_errors / len(reports) if reports else 0.0,
        "execution_error_rate": error_execution_count / total_execution_count
        if total_execution_count
        else 0.0,
        "error_counts_by_category": dict(category_counter.most_common()),
        "error_counts_by_tool": dict(tool_counter.most_common()),
    }


def flatten_errors(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for report in reports:
        task_name = Path(report["path"]).parent.name
        for error_index, error in enumerate(report["errors"], 1):
            rows.append(
                {
                    "task_name": task_name,
                    "trace_path": report["path"],
                    "error_index_in_task": error_index,
                    "line": error.get("line"),
                    "call_line": error.get("call_line"),
                    "tool": error.get("tool"),
                    "category": error.get("category"),
                    "reason": error.get("reason"),
                    "command_summary": error.get("command_summary"),
                    "evidence": error.get("evidence"),
                    "arguments": json.dumps(error.get("arguments"), ensure_ascii=False, default=str),
                }
            )
    return rows


def format_error_details_markdown(summary: dict[str, Any], error_rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Execution Error Details",
        "",
        f"- trace count: {summary['trace_count']}",
        f"- total execution count: {summary['total_execution_count']}",
        f"- error execution count: {summary['error_execution_count']}",
        f"- tasks with errors: {summary['tasks_with_errors']}",
        f"- execution error rate: {summary['execution_error_rate']:.2%}",
        "",
        "## Error Type Summary",
    ]
    for category, count in summary["error_counts_by_category"].items():
        lines.append(f"- `{category}`: {count}")
    lines.append("")
    lines.append("## Concrete Errors")
    for idx, row in enumerate(error_rows, 1):
        lines.append(
            f"{idx}. `{row['category']}` via `{row['tool']}` in `{row['task_name']}` "
            f"at line {row['line']}"
        )
        if row.get("command_summary"):
            lines.append(f"   - command: `{row['command_summary']}`")
        lines.append(f"   - evidence: {row.get('evidence')}")
    return "\n".join(lines) + "\n"


def format_error_category_samples_markdown(error_rows: list[dict[str, Any]], sample_limit: int = 8) -> str:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in error_rows:
        grouped.setdefault(str(row.get("category") or "unknown"), []).append(row)

    lines = ["# Execution Error Categories", ""]
    for category, rows in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        lines.append(f"## {category}")
        lines.append(f"- count: {len(rows)}")
        lines.append("- examples:")
        for row in rows[:sample_limit]:
            lines.append(
                f"  - `{row['tool']}` in `{row['task_name']}` line {row['line']}: "
                f"{row.get('evidence')}"
            )
        lines.append("")
    return "\n".join(lines)


def write_output_dir(output_dir: Path, summary: dict[str, Any], reports: list[dict[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    error_rows = flatten_errors(reports)

    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "summary.md").write_text(
        format_multi_markdown(summary, reports) if len(reports) > 1 else format_markdown(reports[0]),
        encoding="utf-8",
    )
    (output_dir / "reports.json").write_text(
        json.dumps({"summary": summary, "reports": reports}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "errors.json").write_text(
        json.dumps(error_rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "errors.md").write_text(
        format_error_details_markdown(summary, error_rows),
        encoding="utf-8",
    )
    (output_dir / "error_categories.md").write_text(
        format_error_category_samples_markdown(error_rows),
        encoding="utf-8",
    )

    csv_path = output_dir / "errors.csv"
    fieldnames = [
        "task_name",
        "trace_path",
        "error_index_in_task",
        "line",
        "call_line",
        "tool",
        "category",
        "reason",
        "command_summary",
        "evidence",
        "arguments",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(error_rows)


def format_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Execution Error Analysis",
        "",
        f"- trace: `{report['path']}`",
        f"- trace format: `{report.get('trace_format', 'unknown')}`",
        f"- start line: {report['start_line']} (user message #{report['start_user_index']})",
        f"- ignored tools: {', '.join(f'`{tool}`' for tool in report['ignored_tools']) or 'none'}",
        f"- ignored commands: {', '.join(f'`{cmd}`' for cmd in report.get('ignored_commands', [])) or 'none'}",
        f"- total execution count: {report['total_execution_count']}",
        f"- error execution count: {report['error_execution_count']}",
        f"- tool calls: {report['tool_call_count']}",
        f"- tool results: {report['tool_result_count']}",
        f"- errors: {report['error_count']}",
        f"- error rate: {report['error_rate']:.2%}",
        "",
    ]
    if report["error_counts_by_tool"]:
        lines.append("## Errors By Tool")
        for tool, count in report["error_counts_by_tool"].items():
            lines.append(f"- `{tool}`: {count}")
        lines.append("")
    if report["error_counts_by_category"]:
        lines.append("## Errors By Category")
        for category, count in report["error_counts_by_category"].items():
            lines.append(f"- `{category}`: {count}")
        lines.append("")
    if report["errors"]:
        lines.append("## Error Details")
        for idx, error in enumerate(report["errors"], 1):
            location = f"line {error.get('line')}"
            call_line = error.get("call_line")
            if call_line:
                location += f" (call line {call_line})"
            lines.append(
                f"{idx}. `{error.get('tool')}` {location}: "
                f"{error.get('category')} / {error.get('reason')}"
            )
            if error.get("command_summary"):
                lines.append(f"   - command: `{error['command_summary']}`")
            lines.append(f"   - evidence: {error.get('evidence')}")
    return "\n".join(lines) + "\n"


def format_multi_markdown(summary: dict[str, Any], reports: list[dict[str, Any]]) -> str:
    lines = [
        "# Execution Error Analysis",
        "",
        f"- trace count: {summary['trace_count']}",
        f"- total execution count: {summary['total_execution_count']}",
        f"- error execution count: {summary['error_execution_count']}",
        f"- tasks with errors: {summary['tasks_with_errors']}",
        f"- task error rate: {summary['task_error_rate']:.2%}",
        f"- execution error rate: {summary['execution_error_rate']:.2%}",
        "",
    ]
    if summary["error_counts_by_tool"]:
        lines.append("## Errors By Tool")
        for tool, count in summary["error_counts_by_tool"].items():
            lines.append(f"- `{tool}`: {count}")
        lines.append("")
    if summary["error_counts_by_category"]:
        lines.append("## Errors By Category")
        for category, count in summary["error_counts_by_category"].items():
            lines.append(f"- `{category}`: {count}")
        lines.append("")
    lines.append("## Worst Tasks")
    worst = sorted(
        reports,
        key=lambda item: (
            -item["error_execution_count"],
            -item["total_execution_count"],
            item["path"],
        ),
    )
    for report in worst[:20]:
        if not report["error_execution_count"]:
            break
        lines.append(
            f"- {report['error_execution_count']}/{report['total_execution_count']} "
            f"`{Path(report['path']).parent.name}`"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze OpenClaw/agent ReAct jsonl traces and extract tool-call execution errors."
    )
    parser.add_argument("paths", nargs="+", type=Path, help="Trace .jsonl file(s) or directories.")
    parser.add_argument(
        "--start-user-index",
        type=int,
        default=2,
        help="Start analysis from the Nth user message. Default: 2, to skip session-startup messages.",
    )
    parser.add_argument(
        "--ignored-tools",
        default=None,
        help=(
            "Comma-separated tool names to ignore. By default this is chosen from "
            "the detected trace format: openclaw=read,edit; claude_code=Read,Edit; "
            "codex=write_stdin."
        ),
    )
    parser.add_argument(
        "--ignored-commands",
        default=",".join(sorted(DEFAULT_IGNORED_COMMANDS)),
        help="Comma-separated exact shell commands to ignore. Default: /status.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
        help="Output format. Default: markdown.",
    )
    parser.add_argument("--output", type=Path, help="Optional output file.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Optional directory for automated summary/detail reports.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Accepted for readability; directories are always scanned recursively.",
    )
    parser.add_argument(
        "--direct-original-react-only",
        action="store_true",
        help="For directory inputs, analyze only immediate child directories' original_ReAct.jsonl files.",
    )
    parser.add_argument(
        "--skip-local-reports",
        action="store_true",
        help="Do not write per-trace evals/execution_error_report.json files.",
    )
    args = parser.parse_args()

    trace_files = find_trace_files(
        args.paths,
        direct_original_react_only=args.direct_original_react_only,
    )
    if not trace_files:
        raise SystemExit("No .jsonl trace files found.")

    ignored_tools = (
        None
        if args.ignored_tools is None
        else {tool.strip() for tool in args.ignored_tools.split(",") if tool.strip()}
    )
    ignored_commands = {cmd.strip() for cmd in args.ignored_commands.split(",") if cmd.strip()}
    reports = []
    for path in trace_files:
        if args.skip_local_reports:
            reports.append(
                analyze_trace_file(
                    path,
                    start_user_index=args.start_user_index,
                    ignored_tools=ignored_tools,
                    ignored_commands=ignored_commands,
                )
            )
        else:
            _, report = write_execution_error_report(
                path,
                start_user_index=args.start_user_index,
                ignored_tools=ignored_tools,
                ignored_commands=ignored_commands,
            )
            reports.append(report)
    summary = summarize_reports(reports)
    output_data: Any = reports[0] if len(reports) == 1 else {"summary": summary, "reports": reports}

    if args.format == "json":
        rendered = json.dumps(output_data, ensure_ascii=False, indent=2) + "\n"
    elif len(reports) == 1:
        rendered = format_markdown(reports[0])
    else:
        rendered = format_multi_markdown(summary, reports)

    if args.output_dir:
        write_output_dir(args.output_dir, summary, reports)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
