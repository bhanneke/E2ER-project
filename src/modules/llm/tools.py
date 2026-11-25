"""LLM module — tool definitions and file tool handler."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .base import ToolHandler

# Standard file tools available to every specialist
FILE_TOOLS: list[dict[str, Any]] = [
    {
        "name": "read_file",
        "description": "Read the contents of a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to workspace"},
                "start_line": {
                    "type": "integer",
                    "description": "First line to return (1-based; default 1). Use it to read on in a long file.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file (creates parent directories).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Replace old_string with new_string in a file (exact match required).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    {
        "name": "list_directory",
        "description": "List files and directories at a path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path (default: workspace root)",
                },
            },
            "required": [],
        },
    },
]


class FileToolHandler(ToolHandler):
    """Executes file tools sandboxed to a workspace directory."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str) -> Path:
        # Use relative_to, not str.startswith — a string prefix check would let
        # a sibling workspace whose path is a prefix (e.g. /w/abc vs /w/abc-x)
        # escape the sandbox.
        resolved = (self.workspace / path).resolve()
        if resolved != self.workspace and self.workspace not in resolved.parents:
            raise PermissionError(f"Path traversal not allowed: {path}")
        return resolved

    def can_handle(self, tool_name: str) -> bool:
        return tool_name in {"read_file", "write_file", "edit_file", "list_directory"}

    async def handle(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        try:
            if tool_name == "read_file":
                p = self._resolve(tool_input["path"])
                if not p.exists():
                    return f"Error: file not found: {tool_input['path']}"
                text = p.read_text(encoding="utf-8")
                start = tool_input.get("start_line")
                if isinstance(start, int) and not isinstance(start, bool) and start > 1:
                    lines = text.splitlines(keepends=True)
                    if start > len(lines):
                        return f"(the file has {len(lines)} lines; nothing from line {start} on)"
                    return "".join(lines[start - 1 :])
                return text

            elif tool_name == "write_file":
                p = self._resolve(tool_input["path"])
                refused = _refuse_content(tool_input["path"], tool_input["content"], tool_input["content"])
                if refused:
                    return refused
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(tool_input["content"], encoding="utf-8", newline="\n")
                return f"Written {len(tool_input['content'])} chars to {tool_input['path']}"

            elif tool_name == "edit_file":
                p = self._resolve(tool_input["path"])
                if not p.exists():
                    return f"Error: file not found: {tool_input['path']}"
                content = p.read_text(encoding="utf-8")
                old = tool_input["old_string"]
                if old not in content:
                    return f"Error: old_string not found in {tool_input['path']}"
                new_content = content.replace(old, tool_input["new_string"], 1)
                refused = _refuse_content(tool_input["path"], tool_input["new_string"], new_content)
                if refused:
                    return refused
                p.write_text(new_content, encoding="utf-8", newline="\n")
                return f"Edited {tool_input['path']}"

            elif tool_name == "list_directory":
                path_str = tool_input.get("path", ".")
                p = self._resolve(path_str)
                if not p.exists():
                    return f"Error: directory not found: {path_str}"
                entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
                lines = []
                for e in entries:
                    prefix = "  " if e.is_file() else "D "
                    lines.append(f"{prefix}{e.name}")
                return "\n".join(lines) or "(empty directory)"

            return f"Error: unknown file tool: {tool_name}"
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error executing {tool_name}: {e}"


#: The shortened parts of older exchanges (history.ELIDED, and the wording before 0.23).
_ELIDED = re.compile(r"characters[^\]\n]{0,80}?(?:not repeated|left out of this conversation)")


def _refuse_content(path: str, written: str, result: str) -> str | None:
    """Why a write must not happen, or None (live test 2026-11-25).

    A model rewriting a file from its own history copied a shortened part ("[713 characters, not
    repeated]") into it, and a JSON file it edited no longer parsed; a later check stopped the run.
    Refused here, the model sees why at once and writes the file again.
    """
    if _ELIDED.search(written):
        return (
            f"Error: nothing written to {path}. The text holds a placeholder for content left out of this "
            'conversation ("[… characters, …]"). Read the file (read_file) and write its real content.'
        )
    if path.lower().endswith(".json"):
        try:
            json.loads(result)
        except ValueError as e:
            return (
                f"Error: nothing written to {path}: the result would not be valid JSON ({e}). Fix it and write again."
            )
    return None
