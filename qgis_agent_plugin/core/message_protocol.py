"""Utilities for keeping OpenAI-compatible tool message sequences valid."""

from copy import deepcopy
from typing import Any, Dict, Iterable, List, Tuple


def _tool_call_parts(tool_call: Any) -> Tuple[str, str]:
    if isinstance(tool_call, dict):
        call_id = str(tool_call.get("id") or "")
        function = tool_call.get("function") or {}
        name = str(function.get("name") or "") if isinstance(function, dict) else ""
        return call_id, name
    call_id = str(getattr(tool_call, "id", "") or "")
    function = getattr(tool_call, "function", None)
    return call_id, str(getattr(function, "name", "") or "")


def reconcile_tool_messages(
    messages: Iterable[Dict[str, Any]],
    cancelled_content: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """Return a valid message sequence and a list of repairs.

    Every assistant message containing tool calls is immediately followed by one
    tool result for each call. Orphan and duplicate tool results are removed.
    Missing results are represented as cancelled tool calls so an interrupted
    session can safely continue.
    """

    source = [deepcopy(message) for message in messages or []]
    repaired: List[Dict[str, Any]] = []
    repairs: List[Dict[str, str]] = []
    index = 0

    while index < len(source):
        message = source[index]
        role = message.get("role")
        tool_calls = message.get("tool_calls") if role == "assistant" else None

        if role == "tool":
            repairs.append({
                "action": "drop_orphan_tool_result",
                "tool_call_id": str(message.get("tool_call_id") or ""),
            })
            index += 1
            continue

        repaired.append(message)
        index += 1
        if not tool_calls:
            continue

        expected = []
        names = {}
        for tool_call in tool_calls:
            call_id, name = _tool_call_parts(tool_call)
            if call_id and call_id not in names:
                expected.append(call_id)
                names[call_id] = name

        seen = set()
        tool_results = {}
        while index < len(source) and source[index].get("role") == "tool":
            tool_message = source[index]
            call_id = str(tool_message.get("tool_call_id") or "")
            if call_id in names and call_id not in seen:
                seen.add(call_id)
                tool_results[call_id] = tool_message
            else:
                repairs.append({
                    "action": "drop_duplicate_or_unknown_tool_result",
                    "tool_call_id": call_id,
                })
            index += 1

        for call_id in expected:
            if call_id in tool_results:
                repaired.append(tool_results[call_id])
                continue
            repaired.append({
                "role": "tool",
                "tool_call_id": call_id,
                "name": names.get(call_id, ""),
                "content": cancelled_content,
            })
            repairs.append({
                "action": "insert_cancelled_tool_result",
                "tool_call_id": call_id,
                "tool": names.get(call_id, ""),
            })

    return repaired, repairs


def build_cancelled_tool_results(
    tool_calls: Iterable[Dict[str, Any]],
    cancelled_content: str,
) -> List[Dict[str, Any]]:
    """Build protocol-complete results for tool calls skipped after cancellation."""
    results: List[Dict[str, Any]] = []
    for tool_call in tool_calls or []:
        call_id, name = _tool_call_parts(tool_call)
        if not call_id:
            continue
        results.append({
            "role": "tool",
            "tool_call_id": call_id,
            "name": name,
            "content": cancelled_content,
        })
    return results


def validate_tool_message_sequence(messages: Iterable[Dict[str, Any]]) -> List[str]:
    """Return protocol errors without changing the input sequence."""

    errors: List[str] = []
    source = list(messages or [])
    index = 0
    while index < len(source):
        message = source[index]
        if message.get("role") == "tool":
            errors.append(f"orphan tool result: {message.get('tool_call_id', '')}")
            index += 1
            continue
        tool_calls = message.get("tool_calls") if message.get("role") == "assistant" else None
        index += 1
        if not tool_calls:
            continue
        expected = [_tool_call_parts(call)[0] for call in tool_calls]
        expected = [call_id for call_id in expected if call_id]
        actual = []
        while index < len(source) and source[index].get("role") == "tool":
            actual.append(str(source[index].get("tool_call_id") or ""))
            index += 1
        if len(actual) != len(set(actual)):
            errors.append("duplicate tool results after assistant tool_calls")
        missing = [call_id for call_id in expected if call_id not in actual]
        unknown = [call_id for call_id in actual if call_id not in expected]
        if missing:
            errors.append("missing tool results: " + ", ".join(missing))
        if unknown:
            errors.append("unknown tool results: " + ", ".join(unknown))
    return errors
