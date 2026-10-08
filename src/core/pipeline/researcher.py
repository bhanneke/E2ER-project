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

A study that finished, failed or stopped can be sent back as well:
``apply_rerun`` reruns one template step and every step after it with the
researcher's remark (at a stop, in place of that stop), and the run stops at the next researcher step, which needs
approving again (``e2er rerun <id> --from STEP --remark "…"``).

The run also stops here when a specialist's output still fails its contract
after the last attempt (kind ``contract``, step ``output_contract``): approving
takes the output as it is (recorded, and marked as failing its contract in the
dossier); a send-back of the failed specialist, or a plain resume, gives it
fresh attempts.

And it stops here when the number check still finds numbers in the paper's
tables that differ from the results files after the automatic correction
(kind ``numbers``, step ``number_check``, governance ``full``): approving
continues with those mismatches, each recorded in the dossier as the
researcher's decision; an edit, an instruction or a send-back is followed by
the check running again.

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
#: The researcher step a run stops at when a specialist's output still fails its
#: contract after the last attempt (kind ``contract``; see runner._stop_for_contract).
CONTRACT_STEP = "output_contract"
#: The researcher step a run stops at when the number check (tables against the
#: results files) still fails after the automatic correction, under governance
#: ``full`` (kind ``numbers``; see runner._stop_at_number_check).
NUMBERS_STEP = "number_check"
#: What a researcher can send back from the number check, beside the earlier steps:
#: the drafter, the table layout (section_writer writes table_spec.json) and the
#: work that produced the results.
NUMBERS_SENDABLE = ("paper_drafter", "section_writer", "econometrics_specialist", "data_analyst")
ACTIONS = ("approve", "edit", "instruction", "send_back")
_EDITABLE_SUFFIXES = (".md", ".tex", ".json", ".txt", ".bib")
#: e2er's own record of the run, never offered for editing at a stop.
_NOT_THE_STUDYS = frozenset({"manifest.json"})


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


def contract_reasons(failures: list[dict[str, Any]]) -> list[str]:
    """One line per attempt of each specialist whose output failed its contract, for the researcher."""
    lines: list[str] = []
    for f in failures:
        attempts = f.get("attempts") or []
        for a in attempts:
            what = "; ".join(a.get("violations") or []) or (a.get("error") or "no reason recorded")
            lines.append(f"{f.get('specialist')}, attempt {a.get('attempt')} of {len(attempts)}: {what}")
    return lines


def _plain_number(value: str) -> str:
    """``17.0`` → ``17``; anything else as it is."""
    text = str(value)
    try:
        f = float(text)
    except ValueError:
        return text
    return str(int(f)) if f.is_integer() and abs(f) < 1e15 else text


def mismatch_key(m: Any) -> str:
    """One mismatch of the number check, as a key: the cell, the table's value, the source key."""
    get = m.get if isinstance(m, dict) else lambda k: getattr(m, k, "")
    return f"{get('table_context')}|{get('draft_value')}|{get('source_key')}"


def mismatch_record(m: Any) -> dict[str, Any]:
    """A mismatch of the number check for the researcher and the dossier."""
    source_key = str(getattr(m, "source_key", ""))
    source_file = source_key.split(".json", 1)[0] + ".json" if ".json" in source_key else ""
    return {
        "cell": str(getattr(m, "table_context", "")),
        "in_table": str(getattr(m, "draft_value", "")),
        "in_results": _plain_number(str(getattr(m, "source_value", ""))),
        "source_key": source_key,
        "source_file": source_file,
        "key": mismatch_key(m),
    }


def describe_mismatch(rec: dict[str, Any]) -> str:
    """One line per mismatch, as the researcher reads it."""
    return (
        f"{rec.get('cell')}: the table says {rec.get('in_table')}, the results say {rec.get('in_results')} "
        f"({rec.get('source_key')})"
    )


def _accepted_outputs(workspace: Path, state: PipelineState) -> list[dict[str, Any]]:
    """What the researcher approves at a contract stop: per specialist, its files and the violations left now."""
    from ..specialists.contract_check import check_specialist_artifacts

    out = []
    for f in (state.metadata.get("contract_pause") or {}).get("failed") or []:
        name = f.get("specialist", "")
        now = [f"{c.artifact}: {c.reason}" for c in check_specialist_artifacts(workspace, name) if not c.ok]
        files = [
            {"file": n, "sha256": _sha256((workspace / n).read_bytes())}
            for n in f.get("files") or []
            if (workspace / n).is_file()
        ]
        out.append(
            {
                "specialist": name,
                # True: the output stands although it fails its contract (the
                # researcher's decision). False: an edit made it pass.
                "contract_failed": bool(now),
                "violations": now,
                "attempts": len(f.get("attempts") or []),
                "files": files,
            }
        )
    return out


@dataclass(frozen=True)
class PendingReview:
    stage: str
    kind: str  # researcher | preregister | review_at | gate | deviation | contract | numbers
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
                if p.is_file()
                and p.suffix in _EDITABLE_SUFFIXES
                and not p.name.startswith(".")
                and p.name not in _NOT_THE_STUDYS
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
        if pending.kind == "deviation":
            # The researcher keeps a change to the pre-registered plan: the
            # decision and each changed file (SHA-256 frozen and approved) go
            # into the lock and, through this event, the dossier.
            from .preregistration import approve_deviations

            approved = approve_deviations(workspace)
            payload.update(decision="deviation_approved", deviations=approved)
            state.metadata.pop("preregistration_deviation", None)
            state.metadata.pop("review", None)
        if pending.kind == "numbers":
            # The researcher continues with the tables as they are: each mismatch
            # is recorded (dossier) and the check lets exactly these through.
            mismatches = list((state.metadata.get("number_check") or {}).get("mismatches") or [])
            payload.update(decision="numbers_accepted", mismatches=mismatches)
            keys = state.metadata.setdefault("numbers_accepted", [])
            keys.extend(m["key"] for m in mismatches if m.get("key") and m["key"] not in keys)
        if pending.kind == "contract":
            # The researcher takes the output as it is: recorded for the dossier,
            # each output that still fails its contract marked as such.
            accepted = _accepted_outputs(workspace, state)
            payload.update(decision="accepted_as_is", accepted=accepted)
            state.metadata.setdefault("contract_accepted", []).extend({**a, "at": payload["at"]} for a in accepted)
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


#: Step kinds a rerun cannot start from: a researcher's own step is not work to redo.
_NOT_RERUNNABLE = ("researcher", "preregister")


def rerunnable_steps(spec: Any, mode: str) -> list[str]:
    """The template steps a study can be run again from, in order (for the dashboard's choice)."""
    return [s.name for s in spec.steps if s.kind not in _NOT_RERUNNABLE and not s.after and s.applies_to(mode)]


def _withdraw_check_approvals(state: PipelineState, spec: Any, later: list[str]) -> None:
    """The researcher's approvals at the checks of the steps that run again are withdrawn.

    Table numbers continued with at the number check (it runs in the review
    step, or in a check step of its own) and outputs kept as they are at a
    contract stop: the steps produce new output, so the checks decide afresh
    and stop again where they find something.
    """
    meta = state.metadata

    def is_number_check(name: str) -> bool:
        step = spec.step(name)
        return name == "review" or (step is not None and getattr(step, "check", None) == "numbers")

    if any(is_number_check(n) for n in later):
        meta.pop("numbers_accepted", None)
        meta.pop("numbers_patch_tried", None)
        meta.pop("number_check", None)
    if "initial" in later:
        meta.pop("contract_accepted_orders", None)
    skips = [p for p in meta.get("contract_accepted_skip") or [] if p.get("phase") not in later]
    if skips:
        meta["contract_accepted_skip"] = skips
    else:
        meta.pop("contract_accepted_skip", None)
    if "revision" in later:
        meta.pop("deep_revision", None)  # a new revision step may run its deep revision round again


def apply_rerun(workspace: Path, state: PipelineState, spec: Any, step: str, remark: str) -> dict[str, Any]:
    """Send a study back to ``step``: it and every later step run again with ``remark``.

    For a study that finished, failed or stopped. The step must be a template
    step of the study's mode, and not a researcher step. A step that has not run
    yet (the run failed or stopped before it) is accepted too: the run then
    continues from its first unfinished step, with the remark. When the run is
    stopped at a researcher step or a check, the rerun takes the place of that
    stop (recorded as ``replaces``); the checks run again on the way. The
    approvals of the step and of every later step are withdrawn, so the run
    stops at the next researcher step again. The remark goes to
    ``researcher_instructions.md`` for the specialists and into the event
    returned for the dossier; the runner reruns the steps
    (``_settle_researcher_decisions``). Nothing in the workspace is deleted.
    """
    step = str(step or "").strip()
    remark = str(remark or "").strip()
    if not step or not remark:
        raise ResearcherActionError("a rerun needs the step to start from and a remark")
    names = [s.name for s in spec.steps]
    if step not in names:
        raise ResearcherActionError(f"{step!r} is not a step of the template {spec.name} (one of {', '.join(names)})")
    target = spec.step(step)
    if target.kind in _NOT_RERUNNABLE:
        raise ResearcherActionError(f"{step!r} is a researcher step; rerun the step before it")
    if target.after:
        raise ResearcherActionError(f"{step!r} runs inside another step; rerun that step")
    if not target.applies_to(state.mode):
        raise ResearcherActionError(f"{step!r} is not part of a {state.mode.replace('_', ' ')} run")
    done = set(state.completed_stages) | set(state.approved_stages)
    # Where the run picks up: the step, or an earlier one the failed or stopped run had not finished
    # (a step that runs at every start, such as the estimation check, is never left unfinished).
    open_ = [
        n
        for n in names
        if spec.step(n).resumable
        and spec.step(n).will_run(state.mode, done)
        and spec.step(n).kind not in _NOT_RERUNNABLE
    ]
    start = min(names.index(step), names.index(open_[0])) if open_ else names.index(step)
    later = names[names.index(step) :]
    replaces = state.pending_review_stage
    if replaces:
        # The rerun takes the place of the stop the run waits at; its checks run again.
        state.pending_review_stage = None
        for key in ("contract_pause", "preregistration_deviation"):
            state.metadata.pop(key, None)
    state.approved_stages = [a for a in state.approved_stages if a not in later]
    _withdraw_check_approvals(state, spec, later)
    step_done = state.metadata.get("step_done")
    if isinstance(step_done, dict):
        for name in later:  # a step run again runs all of its specialists
            step_done.pop(name, None)
    state.metadata.setdefault("rerun", []).append({"target": step, "remark": remark})
    state.metadata.pop("sent_back", None)
    state.metadata.pop("review", None)
    state.last_status = "in_progress"
    at = _now()
    p = workspace / INSTRUCTIONS_FILE
    prior = p.read_text(encoding="utf-8") if p.is_file() else ""
    p.write_text(
        prior + ("\n\n" if prior else "") + f"(for {step}, rerun of the study, {at}) {remark}\n",
        encoding="utf-8",
    )
    reruns = [n for n in names[start:] if spec.step(n).applies_to(state.mode) and not spec.step(n).after]
    payload: dict[str, Any] = {
        "action": "rerun",
        "step": step,
        "target": step,
        "remark": remark,
        "at": at,
        "reruns": reruns,
    }
    if replaces:
        payload["replaces"] = replaces
    return payload
