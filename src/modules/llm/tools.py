"""LLM module — tool definitions and file tool handler."""
from __future__ import annotations

import json
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
                "path": {"type": "string", "description": "Directory path (default: workspace root)"},
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
        resolved = (self.workspace / path).resolve()
        if not str(resolved).startswith(str(self.workspace)):
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
                return p.read_text(encoding="utf-8")

            elif tool_name == "write_file":
                p = self._resolve(tool_input["path"])
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(tool_input["content"], encoding="utf-8")
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
                p.write_text(new_content, encoding="utf-8")
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
