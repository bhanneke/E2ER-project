"""ReplayBackend: an LLM backend that replays a recorded run instead of calling a model.

Test-only. It is not in the backend registry and not shipped in the wheel
(``tests*`` is excluded); the end-to-end harness installs it into a server
process with :func:`tests.replay.harness.install`.

A *scenario* is a folder ``tests/fixtures/replay/<name>/`` with
``scenario.json`` and ``files/<specialist>/<workspace-relative path>``, made
by ``tests/replay/extract.py`` from a recorded demonstration run.

* A specialist call writes that specialist's recorded files into the
  workspace (text files with ``@@PAPER_ID@@`` / ``@@WORKSPACE@@`` filled in),
  reports the recorded token counts, and succeeds. Everything that follows
  (contract checks, post-execution, gates, the researcher steps) is the real
  code acting on those files.
* A strategist call answers with the plan the real run followed: the
  initial phase's groups of specialists, ``complete`` for an iterative
  decision, ``proceed_to_review`` for a ceiling check, no findings for a
  self-attack.
* Calls with no recording fail visibly ("replay has no recording for …"),
  never silently.

Variations a story needs (a specialist that fails, or writes a different file
on its first attempt) come from an overrides file named by
``E2ER_REPLAY_OVERRIDES``, read on every call so a story can change it while
the server runs::

    {"identification_strategist": {"attempts": [
        {"replace": {"event_design.json": [["\\"2020-03-16\\"", "\\"2020-03-15\\""]]}}
    ]},
     "econometrics_specialist": {"attempts": [{"fail": "no data"}]}}

Attempt *n* (counted per paper and specialist in this process) uses entry
*n* of ``attempts``; later attempts replay the recording unchanged.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

from src.modules.llm.base import (
    CompositeToolHandler,
    LLMBackend,
    TokenUsage,
    ToolHandler,
    ToolLoopResult,
)
from src.modules.llm.tools import FileToolHandler

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "replay"
ENV_SCENARIO = "E2ER_REPLAY_SCENARIO"
ENV_OVERRIDES = "E2ER_REPLAY_OVERRIDES"

_TEXT_SUFFIXES = {".md", ".json", ".tex", ".py", ".txt", ".csv", ".bib", ".r", ".R", ".do", ".toml", ".yaml", ".yml"}


def scenario_dir(name: str) -> Path:
    path = Path(name)
    if not path.is_absolute():
        path = FIXTURES / name
    if not (path / "scenario.json").is_file():
        raise FileNotFoundError(f"replay scenario not found: {path}/scenario.json")
    return path


def _workspace_of(handler: ToolHandler | None) -> Path | None:
    if isinstance(handler, FileToolHandler):
        return handler.workspace
    if isinstance(handler, CompositeToolHandler):
        for h in handler._handlers:  # noqa: SLF001 — test code reading the composite
            ws = _workspace_of(h)
            if ws is not None:
                return ws
    return None


class ReplayBackend(LLMBackend):
    """Replays the files a recorded run's specialists wrote (see module docstring)."""

    #: Calls per (paper id, specialist) in this process, across every backend instance.
    _attempts: dict[tuple[str, str], int] = {}
    #: Every call, in order, for assertions: (paper id, specialist or strategist kind).
    calls: list[tuple[str, str]] = []

    def __init__(self, scenario: str | Path | None = None) -> None:
        name = str(scenario or os.environ.get(ENV_SCENARIO) or "fomc")
        self.root = scenario_dir(name)
        self.scenario: dict[str, Any] = json.loads((self.root / "scenario.json").read_text(encoding="utf-8"))

    # ── overrides ──────────────────────────────────────────────────────────

    @staticmethod
    def _overrides() -> dict[str, Any]:
        path = os.environ.get(ENV_OVERRIDES)
        if not path or not Path(path).is_file():
            return {}
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def _variant(self, paper_id: str, specialist: str) -> dict[str, Any]:
        key = (paper_id, specialist)
        n = ReplayBackend._attempts.get(key, 0)
        ReplayBackend._attempts[key] = n + 1
        attempts = ((self._overrides().get(specialist) or {}).get("attempts")) or []
        return attempts[n] if n < len(attempts) and isinstance(attempts[n], dict) else {}

    # ── the backend ────────────────────────────────────────────────────────

    async def tool_loop(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_handler: ToolHandler | None,
        max_turns: int = 30,
        *,
        paper_id: str | None = None,
        specialist: str | None = None,
    ) -> ToolLoopResult:
        t0 = time.time()
        if specialist is None:
            return self._strategist(system, messages, t0)
        ReplayBackend.calls.append((paper_id or "", specialist))
        workspace = _workspace_of(tool_handler)
        rec = (self.scenario.get("specialists") or {}).get(specialist)
        if workspace is None:
            return ToolLoopResult(success=False, output="", error="replay: the call has no workspace")
        if rec is None:
            return ToolLoopResult(
                success=False,
                output="",
                error=f"replay has no recording for {specialist} in scenario {self.scenario.get('name')}",
                duration_seconds=time.time() - t0,
            )
        variant = self._variant(paper_id or "", specialist)
        if variant.get("fail"):
            return ToolLoopResult(
                success=False, output="", error=f"replay: {variant['fail']}", duration_seconds=time.time() - t0
            )
        written = []
        skip = set(variant.get("skip") or [])
        replace: dict[str, list[list[str]]] = variant.get("replace") or {}
        for rel in rec.get("files") or []:
            if rel in skip:
                continue
            self._write(workspace, specialist, rel, paper_id or "", replace.get(rel) or [])
            written.append(rel)
        u = rec.get("usage") or {}
        return ToolLoopResult(
            success=True,
            output=rec.get("output") or f"Wrote {', '.join(written)}.",
            tool_calls_made=len(written),
            usage=TokenUsage(
                input_tokens=int(u.get("input_tokens") or 0),
                output_tokens=int(u.get("output_tokens") or 0),
                cache_read_tokens=int(u.get("cache_read_tokens") or 0),
                cache_write_tokens=int(u.get("cache_write_tokens") or 0),
            ),
            duration_seconds=time.time() - t0,
        )

    def _write(self, workspace: Path, specialist: str, rel: str, paper_id: str, replace: list[list[str]]) -> None:
        src = self.root / "files" / specialist / rel
        dest = workspace / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_symlink() or dest.exists():
            dest.unlink()
        if src.suffix not in _TEXT_SUFFIXES:
            shutil.copyfile(src, dest)
            return
        text = src.read_text(encoding="utf-8")
        text = text.replace("@@WORKSPACE@@", str(workspace.resolve())).replace("@@PAPER_ID@@", paper_id)
        for old, new in replace:
            if old not in text:
                raise AssertionError(f"replay override: {old!r} not found in {specialist}/{rel}")
            text = text.replace(old, new)
        dest.write_text(text, encoding="utf-8")

    def _strategist(self, system: str, messages: list[dict[str, Any]], t0: float) -> ToolLoopResult:
        prompt = "\n".join(str(m.get("content", "")) for m in messages if m.get("role") == "user")
        ReplayBackend.calls.append(("", "strategist"))
        if "Decide what to do next" in prompt:
            status = (re.search(r"Paper status: (\w+)", prompt) or [None, ""])[1]
            groups = self.scenario.get("initial_groups") or []
            if status == "designing" and groups:
                orders = [
                    {
                        "specialist": sp,
                        "focus": f"Carry out your part of this study as your skills describe ({sp}).",
                        "parallel_group": g,
                        "context_tier": 1,
                    }
                    for g, group in enumerate(groups)
                    for sp in group
                ]
                decision = {
                    "action": "dispatch_parallel",
                    "work_orders": orders,
                    "rationale": "replay: the plan of the recorded run",
                }
            else:
                decision = {"action": "complete", "rationale": "replay: nothing further in the recorded run"}
            out = json.dumps(decision)
        elif "SelfAttackReport" in prompt:
            out = json.dumps({"findings": [], "overall_severity": 0})
        elif "verdict" in prompt or "Iteration:" in prompt:
            out = json.dumps({"verdict": "proceed_to_review", "reason": "replay", "suggested_pivots": []})
        else:
            return ToolLoopResult(
                success=False, output="", error="replay has no recording for this call", duration_seconds=0.0
            )
        return ToolLoopResult(success=True, output=out, duration_seconds=time.time() - t0)
