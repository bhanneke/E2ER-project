"""Keeping an in-process tool loop's conversation small.

The SDK backends that speak the OpenAI chat format (OpenRouter) send the whole
conversation again on every turn. One data-analyst attempt on DeepSeek V4 Pro
(2026-10-13, demo 8) grew to 785k fresh and 8.6M cached input tokens and cost
$1.44, because every file it had read and every data preview it had fetched
was sent again on each of the following turns.

Two rules keep the conversation bounded:

* **A cap on each tool result when it enters the conversation.** A longer
  result is cut at a line break, with a note that says so and how to read on
  (``read_file`` takes ``start_line``). Nothing is cut silently.
* **Older tool exchanges are summarised.** The last ``keep_full`` exchanges
  (an assistant turn with tool calls plus their results) stay in full. Once
  ``keep_full + batch`` exchanges are in full, the oldest are summarised down
  to ``keep_full`` in one step: long results become a one-line note with their
  first lines, long arguments (a ``write_file`` body) become their length.
  Summarising in batches, not every turn, keeps the start of the conversation
  unchanged between batches, so the provider's prompt cache still matches it.

The functions return new message lists and never change a message in place.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

#: A tool result longer than this (characters) is cut when it enters the conversation.
RESULT_CAP_CHARS = 40_000
#: Tool exchanges kept in full; older ones are summarised.
KEEP_FULL_EXCHANGES = 6
#: How many exchanges beyond ``KEEP_FULL_EXCHANGES`` build up before a summarising step.
COMPACT_BATCH = 6
#: In a summarised exchange, results and argument values up to this length stay as they are.
_SHORT = 600
_PREVIEW_LINES = 3
_PREVIEW_CHARS = 300


def cap_tool_result(text: str, tool_name: str, tool_input: dict[str, Any], cap: int = RESULT_CAP_CHARS) -> str:
    """``text`` cut to about ``cap`` characters at a line break, with a note saying what was left out."""
    if len(text) <= cap:
        return text
    cut = text.rfind("\n", 0, cap)
    mid_line = cut <= cap // 2
    if mid_line:
        cut = cap
    head = text[:cut]
    shown_lines = head.count("\n") + 1
    total_lines = text.count("\n") + 1
    if tool_name == "read_file":
        start = int(tool_input.get("start_line") or 1)
        # Cut at a line break: the next line is new. Cut mid-line: read that line again.
        nxt = start + shown_lines - (1 if mid_line else 0)
        how = f"call read_file with path={json.dumps(str(tool_input.get('path', '')))} and start_line={nxt} to read on"
    else:
        how = "ask for less (fewer rows, fewer columns or a narrower query) to see the rest"
    return (
        f"{head.rstrip()}\n\n[cut to save space: {len(head):,} of {len(text):,} characters shown "
        f"(about {shown_lines:,} of {total_lines:,} lines); {how}]"
    )


@dataclass
class _Exchange:
    """Index of an assistant message with tool calls; the tool results follow it."""

    start: int
    end: int  # exclusive


def _exchanges(msgs: list[dict[str, Any]]) -> list[_Exchange]:
    out: list[_Exchange] = []
    i = 0
    while i < len(msgs):
        m = msgs[i]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            j = i + 1
            while j < len(msgs) and msgs[j].get("role") == "tool":
                j += 1
            out.append(_Exchange(i, j))
            i = j
        else:
            i += 1
    return out


def _preview(text: str) -> str:
    lines = [ln for ln in text.splitlines() if ln.strip()][:_PREVIEW_LINES]
    joined = " | ".join(ln.strip() for ln in lines)
    return joined[:_PREVIEW_CHARS]


def _summarise_args(arguments: Any, tool_name: str) -> Any:
    """Long string values in a tool call's arguments replaced by their length (still valid JSON)."""
    if not isinstance(arguments, str) or len(arguments) <= _SHORT:
        return arguments
    try:
        parsed = json.loads(arguments)
    except (json.JSONDecodeError, ValueError):
        return json.dumps({"summary": f"[{len(arguments):,} characters of arguments to {tool_name}, not repeated]"})
    if not isinstance(parsed, dict):
        return json.dumps({"summary": f"[{len(arguments):,} characters of arguments to {tool_name}, not repeated]"})
    short: dict[str, Any] = {}
    for key, value in parsed.items():
        if isinstance(value, str) and len(value) > _SHORT:
            short[key] = f"[{len(value):,} characters, not repeated]"
        elif not isinstance(value, str) and len(json.dumps(value)) > _SHORT:
            short[key] = f"[{len(json.dumps(value)):,} characters of {type(value).__name__}, not repeated]"
        else:
            short[key] = value
    return json.dumps(short)


def _call_label(name: str, arguments: Any) -> str:
    try:
        parsed = json.loads(arguments) if isinstance(arguments, str) and arguments.strip() else {}
    except (json.JSONDecodeError, ValueError):
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    shown = {k: v for k, v in parsed.items() if isinstance(v, (str, int, float, bool)) and len(str(v)) <= 80}
    inner = ", ".join(f"{k}={json.dumps(v)}" for k, v in list(shown.items())[:3])
    return f"{name}({inner})"


def _summarise_exchange(msgs: list[dict[str, Any]], ex: _Exchange) -> list[dict[str, Any]]:
    assistant = msgs[ex.start]
    calls = assistant.get("tool_calls") or []
    names = {c.get("id"): (c.get("function") or {}).get("name", "tool") for c in calls}
    labels = {
        c.get("id"): _call_label(
            (c.get("function") or {}).get("name", "tool"), (c.get("function") or {}).get("arguments")
        )
        for c in calls
    }
    new_calls = []
    for c in calls:
        fn = dict(c.get("function") or {})
        fn["arguments"] = _summarise_args(fn.get("arguments"), fn.get("name", "tool"))
        new_calls.append({**c, "function": fn})
    content = assistant.get("content") or ""
    if isinstance(content, str) and len(content) > 4 * _SHORT:
        content = content[: 2 * _SHORT].rstrip() + f" [… {len(content):,} characters, rest not repeated]"
    out: list[dict[str, Any]] = [{**assistant, "content": content, "tool_calls": new_calls}]
    for m in msgs[ex.start + 1 : ex.end]:
        text = m.get("content")
        if isinstance(text, str) and len(text) > _SHORT:
            label = labels.get(m.get("tool_call_id")) or names.get(m.get("tool_call_id")) or "a tool"
            text = (
                f"[earlier result of {label}: {len(text):,} characters, summarised to save space; "
                f"it began: {_preview(text)}. Call the tool again if you need it.]"
            )
        out.append({**m, "content": text})
    return out


def compact_history(
    msgs: list[dict[str, Any]],
    keep_full: int = KEEP_FULL_EXCHANGES,
    batch: int = COMPACT_BATCH,
) -> tuple[list[dict[str, Any]], int]:
    """The conversation with old tool exchanges summarised, and how many were summarised now.

    Summarises only when ``keep_full + batch`` exchanges are in full, and then
    all but the last ``keep_full``. Exchanges summarised earlier stay as they are.
    """
    exchanges = _exchanges(msgs)
    full = [ex for ex in exchanges if not _is_summarised(msgs, ex)]
    if len(full) < keep_full + batch:
        return msgs, 0
    to_summarise = full[: len(full) - keep_full]
    out: list[dict[str, Any]] = []
    i = 0
    targets = {ex.start: ex for ex in to_summarise}
    while i < len(msgs):
        ex = targets.get(i)
        if ex is None:
            out.append(msgs[i])
            i += 1
            continue
        summarised = _summarise_exchange(msgs, ex)
        summarised[0] = {**summarised[0], "_summarised": True}
        out.extend(summarised)
        i = ex.end
    return out, len(to_summarise)


def _is_summarised(msgs: list[dict[str, Any]], ex: _Exchange) -> bool:
    return bool(msgs[ex.start].get("_summarised"))


def for_request(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The messages as sent: e2er's own bookkeeping keys removed."""
    return [{k: v for k, v in m.items() if not k.startswith("_")} if "_summarised" in m else m for m in msgs]


def history_chars(msgs: list[dict[str, Any]]) -> int:
    """Size of a conversation in characters (content plus tool-call arguments)."""
    n = 0
    for m in msgs:
        c = m.get("content")
        if isinstance(c, str):
            n += len(c)
        elif isinstance(c, list):
            n += sum(len(str(p.get("text", ""))) for p in c if isinstance(p, dict))
        for tc in m.get("tool_calls") or []:
            n += len(str((tc.get("function") or {}).get("arguments") or ""))
    return n
