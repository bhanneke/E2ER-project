"""The researcher step: where a run stops for the person whose research it is.

At a researcher step (a `researcher` or `preregister` step in the template, or a
stage named with `--review-at`) the run pauses. The researcher can

  * approve — the run continues;
  * edit one of the step's files — the edit is saved in the workspace and the
    following specialists work from it;
  * give an instruction — it is kept in ``researcher_instructions.md`` and every
    later specialist and the strategist receive it;
  * send a step back — a template step or a specialist runs again with the
    researcher's remark, and the run stops at the same researcher step again.

Every action is written to the event log as ``researcher_action``; the dossier
lists them as steps of type ``researcher``, so a reader sees where the
researcher decided and where the AI worked.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .state import PipelineState

INSTRUCTIONS_FILE = "researcher_instructions.md"
ACTIONS = ("approve", "edit", "instruction", "send_back")
_EDITABLE_SUFFIXES = (".md", ".tex", ".json", ".txt", ".bib")


class ResearcherActionError(ValueError):
    """An action that cannot be applied (no pending step, unknown file, …)."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def instructions_block(workspace: Path) -> str:
    """The researcher's instructions, as a prompt section; empty when there are none."""
    p = workspace / INSTRUCTIONS_FILE
    if not p.is_file():
        return ""
    text = p.read_text(encoding="utf-8").strip()
    if not text:
        return ""
    return (
        "## Instructions from the researcher\n"
        "The researcher whose study this is gave these instructions during the run. "
        "They take precedence over earlier plans; follow them.\n\n" + text
    )


@dataclass(frozen=True)
class PendingReview:
    stage: str
    kind: str  # researcher | preregister | review_at
    files: tuple[str, ...]


def pending_review(
    workspace: Path, state: PipelineState, step_files: dict[str, tuple[str, ...]] | None = None
) -> PendingReview | None:
    """The researcher step the run is currently stopped at, if any."""
    stage = state.pending_review_stage
    if not stage:
        return None
    meta = state.metadata.get("review", {})
    kind = meta.get("kind", "review_at")
    files = tuple(meta.get("files") or (step_files or {}).get(stage, ()))
    if not files:
        # --review-at pause: offer the step's text artifacts that exist.
        files = tuple(
            sorted(
                p.name
                for p in workspace.iterdir()
                if p.is_file() and p.suffix in _EDITABLE_SUFFIXES and not p.name.startswith(".")
            )
        )
    return PendingReview(stage=stage, kind=kind, files=files)


def _allowed(workspace: Path, pending: PendingReview, file: str) -> Path:
    if not file or "/" in file or file.startswith(".") or file not in pending.files:
        raise ResearcherActionError(f"{file!r} is not one of this step's files: {', '.join(pending.files) or 'none'}")
    return workspace / file


def apply_action(
    workspace: Path, state: PipelineState, action: dict[str, Any], *, sendable: list[str] | None = None
) -> dict[str, Any]:
    """Apply one researcher action to the workspace and state; return the event payload.

    The caller logs the payload as a ``researcher_action`` event, saves the
    state, and (for approve and send_back) resumes the run.
    """
    pending = pending_review(workspace, state)
    if pending is None:
        raise ResearcherActionError("the run is not stopped at a researcher step")
    kind = action.get("action")
    if kind not in ACTIONS:
        raise ResearcherActionError(f"unknown action {kind!r} (one of {', '.join(ACTIONS)})")
    payload: dict[str, Any] = {"action": kind, "step": pending.stage, "at": _now()}

    if kind == "approve":
        state.metadata.pop("sent_back", None)
        state.approve(pending.stage)

    elif kind == "edit":
        path = _allowed(workspace, pending, str(action.get("file", "")))
        content = action.get("content")
        if not isinstance(content, str):
            raise ResearcherActionError("an edit needs the new file content")
        before = path.read_bytes() if path.is_file() else b""
        after = content.encode("utf-8")
        if before == after:
            raise ResearcherActionError(f"{path.name} is unchanged")
        path.write_bytes(after)
        payload.update(file=path.name, sha256_before=_sha256(before) if before else None, sha256_after=_sha256(after))

    elif kind == "instruction":
        text = str(action.get("text", "")).strip()
        if not text:
            raise ResearcherActionError("an instruction needs text")
        p = workspace / INSTRUCTIONS_FILE
        prior = p.read_text(encoding="utf-8") if p.is_file() else ""
        p.write_text(
            prior + ("\n\n" if prior else "") + f"(at step {pending.stage}, {payload['at']}) {text}\n", encoding="utf-8"
        )
        payload.update(text=text)

    elif kind == "send_back":
        target = str(action.get("step", "")).strip()
        remark = str(action.get("remark", "")).strip()
        if not target or not remark:
            raise ResearcherActionError("sending back needs the step and a remark")
        if sendable is not None and target not in sendable:
            raise ResearcherActionError(f"{target!r} cannot be sent back from here (one of {', '.join(sendable)})")
        reruns = state.metadata.setdefault("rerun", [])
        reruns.append({"target": target, "remark": remark})
        state.metadata["sent_back"] = True
        p = workspace / INSTRUCTIONS_FILE
        prior = p.read_text(encoding="utf-8") if p.is_file() else ""
        p.write_text(
            prior
            + ("\n\n" if prior else "")
            + f"(for {target}, sent back at step {pending.stage}, {payload['at']}) {remark}\n",
            encoding="utf-8",
        )
        payload.update(target=target, remark=remark)

    return payload
