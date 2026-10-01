"""Study dossiers: the settings a study was produced with, addressed by a hash.

A dossier lists the E2ER version, the run settings (template, mode, governance,
backend, models), every template, specialist, skill and connector the study
used with a content hash of the file that defines it, and the SHA-256 of the
input data files, and the workflow: every step of the run in order, the
specialist and model that did it, the checks at each gate, steps a check
stopped, and the intermediate file each step wrote with its SHA-256 when the
file is in the exported folder. It deliberately leaves out the paper: the paper carries the
dossier's address in a footnote, so the dossier cannot depend on the paper.

The dossier's id is ``sha256:`` plus the SHA-256 of its canonical JSON (object
keys sorted, no whitespace, UTF-8). The E2ER site computes and checks ids the
same way, so ``https://e2er.org/d/<first 16 hex characters>`` resolves to
exactly this document.

Files are pinned by their git blob SHA (sha1 of ``blob <size>\\0`` + content),
which equals ``git rev-parse <commit>:<path>`` for the same file, so anyone can
compare a pin with the repository.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import sqlite3
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from .availability import any_public
from .demonstration import DEMONSTRATION, disclaimer

SCHEMA = "e2er-dossier/0.3"
#: Used only when a dossier records researcher steps or a pre-registration, so a
#: study without them keeps exactly the 0.3 document (and its address).
SCHEMA_RESEARCHER = "e2er-dossier/0.4"
#: A dossier that states public data or code (``availability``). Studies whose data
#: and code are private keep the 0.3/0.4 document, and their addresses.
SCHEMA_AVAILABILITY = "e2er-dossier/0.5"
#: A dossier built from the run database: segments (one per process that ran
#: part of the run), pins per commit, per-step outputs, events and outcome.
SCHEMA_RUN = "e2er-dossier/0.6"
SITE = "https://e2er.org"
ROOT = Path(__file__).resolve().parents[2]  # the E2ER checkout or installed package root
BACKEND_CONNECTOR = {
    "anthropic": "anthropic",
    "openrouter": "openrouter",
    "claude_code": "claude-code",
    "codex": "codex",
    "gemini": "gemini",
}


class CanonicalError(ValueError):
    """A value has no canonical form: NaN, Infinity, an integer beyond ±(2^53 − 1), a non-JSON type."""


#: The largest integer every JSON reader (JavaScript included) reads back exactly.
MAX_SAFE_INTEGER = 2**53 - 1


def _es_number(x: float) -> str:
    """ECMAScript's Number::toString for a finite float (what ``JSON.stringify`` writes).

    Python's ``repr`` gives the same shortest round-tripping digits as JavaScript;
    only the layout differs (``1.0`` vs ``1``, ``1e-05`` vs ``0.00001``,
    ``1e+16`` vs ``10000000000000000``), so the digits are laid out by the rules
    of ECMA-262 §6.1.6.1.20.
    """
    if x == 0:
        return "0"  # -0 included
    sign = "-" if x < 0 else ""
    r = repr(abs(x))
    mant, _, exp = r.partition("e")
    whole, _, frac = mant.partition(".")
    digits = (whole + frac).lstrip("0")
    # n: position of the decimal point relative to the first significant digit
    n = len(whole.lstrip("0")) if whole.strip("0") else -(len(frac) - len(frac.lstrip("0")))
    n += int(exp or 0)
    digits = digits.rstrip("0") or "0"
    k = len(digits)
    if k <= n <= 21:
        out = digits + "0" * (n - k)
    elif 0 < n <= 21:
        out = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        out = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        es = ("+" if e >= 0 else "-") + str(abs(e))
        out = digits[0] + ("." + digits[1:] if k > 1 else "") + "e" + es
    return sign + out


def _string(s: str, at: str) -> str:
    try:
        s.encode("utf-8")
    except UnicodeEncodeError as e:
        raise CanonicalError(f"{at} contains a lone surrogate, which has no UTF-8 form") from e
    return json.dumps(s, ensure_ascii=False)


def _canon(obj: Any, at: str) -> str:
    if obj is None:
        return "null"
    if obj is True:
        return "true"
    if obj is False:
        return "false"
    if isinstance(obj, int):
        if abs(obj) > MAX_SAFE_INTEGER:
            raise CanonicalError(
                f"{at} is {obj}, beyond ±(2^53 − 1). Such a number is not read back exactly everywhere "
                "(RFC 8785), so its hash would differ; write it as a string."
            )
        return str(int(obj))
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            raise CanonicalError(
                f"{at} is {obj}. NaN and Infinity are not JSON, so the document has no canonical form; "
                "write the value as a string or leave it out."
            )
        if obj.is_integer() and abs(obj) > MAX_SAFE_INTEGER:
            raise CanonicalError(
                f"{at} is {obj!r}, beyond ±(2^53 − 1). Such a number is not read back exactly everywhere "
                "(RFC 8785), so its hash would differ; write it as a string."
            )
        return _es_number(obj)
    if isinstance(obj, str):
        return _string(obj, at)
    if isinstance(obj, list | tuple):
        return "[" + ",".join(_canon(v, f"{at}[{i}]") for i, v in enumerate(obj)) + "]"
    if isinstance(obj, dict):
        for k in obj:
            if not isinstance(k, str):
                raise CanonicalError(f"{at} has the key {k!r}, which is not a string")
        # RFC 8785: keys in the order of their UTF-16 code units (JavaScript's Array#sort).
        keys = sorted(obj, key=lambda k: k.encode("utf-16-be", "surrogatepass"))
        return "{" + ",".join(_string(k, at) + ":" + _canon(obj[k], f"{at}.{k}") for k in keys) + "}"
    raise CanonicalError(f"{at} is a {type(obj).__name__}, which has no JSON form")


def canonical(obj: Any) -> str:
    """The canonical JSON of ``obj``, exactly as e2er.org writes it (RFC 8785, JCS).

    Object keys sorted by their UTF-16 code units at every level, no
    whitespace, numbers as ECMAScript writes them, strings as ``JSON.stringify``
    writes them. NaN, Infinity and integers beyond ±(2^53 − 1) have no canonical
    form and raise :class:`CanonicalError`. The site's function is
    ``canonical`` in e2er-site ``src/lib/integrity-core.mjs``;
    tests/test_canonical_json.py runs both on the same documents.
    """
    return _canon(obj, "$")


def dossier_id(doc: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical(doc).encode("utf-8")).hexdigest()


def short_id(did: str) -> str:
    return did.removeprefix("sha256:")[:16]


def dossier_url(did: str) -> str:
    return f"{SITE}/d/{short_id(did)}"


def git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


@lru_cache(maxsize=4096)
def _blob_at(commit: str, rel: str) -> str | None:
    """git blob SHA of ``rel`` at ``commit`` in the E2ER checkout, if both exist."""
    out = _git("rev-parse", f"{commit}:{rel}")
    return out.strip() if out else None


@lru_cache(maxsize=256)
def _registry_skills_at(commit: str) -> dict[str, list[str]] | None:
    """``SPECIALIST_SKILLS`` as the registry defined it at ``commit``, read from git (never today's)."""
    import ast

    text = _git("show", f"{commit}:src/core/specialists/registry.py")
    if text is None:
        return None
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            target: ast.expr | None = node.target
        elif isinstance(node, ast.Assign):
            target = node.targets[0]
        else:
            continue
        if isinstance(target, ast.Name) and target.id == "SPECIALIST_SKILLS" and node.value is not None:
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                return None
            return {str(k): [str(s) for s in v] for k, v in value.items()} if isinstance(value, dict) else None
    return None


def _path_for(component: str) -> str | None:
    kind, _, rest = component.partition(":")
    if kind == "template":
        return f"pipelines/{rest}.toml"
    if kind == "agent" and "/" not in rest:
        return "src/core/specialists/registry.py"
    if kind == "skill" and rest.startswith("e2er/"):
        return f"skills/files/{rest.removeprefix('e2er/')}.md"
    if kind == "connector":
        backend = {v: k for k, v in BACKEND_CONNECTOR.items()}.get(rest)
        return f"src/modules/llm/{backend}.py" if backend else None
    return None


def _pin(component: str, repository: str | None, commit: str | None) -> dict[str, Any]:
    """Where ``component`` is defined at ``commit``: its path and git blob there.

    A blob that cannot be resolved (no recorded commit, or a commit or path
    this checkout does not have) is recorded as unresolved. It is never
    replaced by the file as it is today.
    """
    rel = _path_for(component)
    if rel is None:
        return {"note": "built into E2ER; no separate file"}
    if not commit:
        return {"path": rel, "note": "unresolved: the run recorded no E2ER commit"}
    pin: dict[str, Any] = {"path": rel}
    if repository:
        pin["repository"] = repository
    pin["commit"] = commit
    blob = _blob_at(commit, rel)
    if blob:
        pin["git_blob"] = blob
    else:
        pin["note"] = f"unresolved: {rel} at {commit[:12]} is not in the E2ER checkout this dossier was built from"
    return pin


def _tables(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _utc(value: Any) -> str | None:
    """A timestamp as UTC ISO 8601 ending in Z (``2026-09-28T14:56:39Z``); None stays None.

    SQLite's ``datetime('now')`` (``2026-09-28 14:56:39``) is UTC without a
    zone; e2er's own stamps end in Z or carry an offset; folder stamps are
    compact (``20260929T091500Z``). A value that is no timestamp is kept as is.
    """
    if value is None or value == "":
        return None
    s = str(value).strip()
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z", s)
    if m:
        s = f"{m[1]}-{m[2]}-{m[3]}T{m[4]}:{m[5]}:{m[6]}Z"
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T", 1))
    except ValueError:
        return s
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


#: Workspace files export renames (structured.EXPORT_MAP); the others keep their name.
_EXPORT_RENAMES = {
    "paper_draft.tex": "paper/paper.tex",
    "literature.bib": "paper/refs.bib",
    "paper_draft.pdf": "paper/paper.pdf",
}


def _workspace_name(path: str, paper_id: str | None) -> str:
    """A file a step wrote, relative to the run's workspace; never a path of this machine.

    The runner records absolute paths (``/Users/…/workspaces/<paper id>/x``).
    The part after the paper's workspace folder is kept; without one, only
    the file name.
    """
    p = path.replace("\\", "/")
    if paper_id and f"/{paper_id}/" in p:
        return p.split(f"/{paper_id}/", 1)[1]
    if not p.startswith("/") and ".." not in p.split("/") and not re.match(r"^[A-Za-z]:", p):
        return p
    return p.rsplit("/", 1)[-1]


def _bundle_file(name: str, files: dict[str, Any]) -> str | None:
    """Where a workspace file ended up in the exported folder: export's renames, else by its path tail."""
    if name in _EXPORT_RENAMES and _EXPORT_RENAMES[name] in files:
        return _EXPORT_RENAMES[name]
    parts = Path(name).parts
    for n in range(len(parts), 0, -1):
        tail = "/".join(parts[-n:])
        hits = sorted(f for f in files if f == tail or f.endswith("/" + tail))
        if hits:
            return hits[0]
    return None


def _clip(value: Any, limit: int = 20000) -> Any:
    """Strings within the site's limit; lists and objects clipped inside."""
    if isinstance(value, str):
        return value if len(value) <= limit else value[: limit - 1] + "…"
    if isinstance(value, list):
        return [_clip(v, limit) for v in value]
    if isinstance(value, dict):
        return {k: _clip(v, limit) for k, v in value.items()}
    return value


@dataclass
class RunRecord:
    """What the run database recorded about one paper's run, read once for the dossier and e2er.json."""

    segments: list[dict[str, Any]] = field(default_factory=list)
    workflow: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    outcome: dict[str, Any] = field(default_factory=dict)
    #: specialists that ran, in order of first appearance; skill per agent; segments per component
    agents: list[str] = field(default_factory=list)
    skills: dict[str, list[str]] = field(default_factory=dict)
    component_segments: dict[str, list[int]] = field(default_factory=dict)
    recorded: bool = False  # the database has this run's events


#: Events that are part of the run's history but not one of the dossier's step types.
_RUN_EVENTS = {
    "awaiting_review",
    "paper_paused",
    "failed",
    "cancelled",
    "circuit_breaker_tripped",
    "paused_budget",
    "estimation_set_aside",
    "preregistration",
}


def read_run(db: Path, paper_id: str, files: dict[str, Any] | None = None) -> RunRecord:
    """The run as its database recorded it: steps, system events, segments and outcome.

    * **Segments.** Each ``run_identity`` event starts a segment: the E2ER
      commit, version and tree state of the process that ran the steps after
      it. A step names its segment, and so the commit it ran on.
    * **Steps** (``workflow``) are of the three kinds the dossier format has:
      ``specialist`` (one dispatch: model and backend from the ``llm_usage``
      rows inside its start and end, the ``contributions`` row likewise),
      ``check`` (gate verdicts, halts, the pre-registration check) and
      ``researcher`` (one per ``researcher_action`` row, all its fields kept,
      plus files the researcher supplied). A send-back's rerun of a specialist
      (``researcher_rerun``, written by the runner) is noted on the specialist
      step it caused, not counted as a researcher action again.
    * **Events** keep the rest of the run's history: stops for review, pauses,
      failures, cancellations, set-asides, the pre-registration's freezing,
      reruns of whole steps.
    * **Outputs.** A step records the SHA-256 of each file it wrote
      (``specialist_end`` → ``outputs``, recorded since e2er 0.13). For steps
      of older runs only the exported file's hash is known: it is given as
      ``sha256_at_export`` on the last accepted step that wrote the file, with
      ``recorded: false``; earlier steps that wrote it carry no hash.
    """
    files = files or {}
    rec = RunRecord()
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        tables = _tables(con)
        if "pipeline_events" not in tables:
            return rec
        events = con.execute(
            "SELECT event_type, stage, specialist, payload, created_at FROM pipeline_events "
            "WHERE paper_id = ? ORDER BY created_at, rowid",
            (paper_id,),
        ).fetchall()
        contribs = (
            con.execute(
                "SELECT specialist, output_file, success, error_msg, created_at FROM contributions "
                "WHERE paper_id = ? ORDER BY created_at, rowid",
                (paper_id,),
            ).fetchall()
            if "contributions" in tables
            else []
        )
        calls = (
            con.execute(
                "SELECT specialist, backend, model, created_at FROM llm_usage WHERE paper_id = ? "
                "ORDER BY created_at, rowid",
                (paper_id,),
            ).fetchall()
            if "llm_usage" in tables
            else []
        )
        paper: tuple[Any, ...] | None = None
        if "papers" in tables:
            cols = {r[1] for r in con.execute("PRAGMA table_info(papers)")}
            want = [c for c in ("status", "last_error", "updated_at") if c in cols]
            if want:
                paper = con.execute(f"SELECT {', '.join(want)} FROM papers WHERE id = ?", (paper_id,)).fetchone()
                if paper is not None:
                    rec.outcome = {
                        k: v for k, v in zip(want, paper, strict=True) if v not in (None, "") and k != "updated_at"
                    }
                    if "updated_at" in want and paper[want.index("updated_at")]:
                        rec.outcome["at"] = _utc(paper[want.index("updated_at")])
    finally:
        con.close()
    rec.recorded = bool(events)
    if "last_error" in rec.outcome:
        rec.outcome["error"] = _clip(str(rec.outcome.pop("last_error")), 2000)

    used_contribs: set[int] = set()
    used_calls: set[int] = set()

    def in_window(at: str | None, start: str | None, end: str | None) -> bool:
        return at is not None and (start is None or at >= start) and (end is None or at <= end)

    phase: str | None = None
    seg = -1
    started: dict[str, tuple[str | None, dict[str, Any]]] = {}
    pending_rerun: dict[str, dict[str, Any]] = {}
    template_skills: dict[int, dict[str, list[str]]] = {}
    step_skills: dict[int, dict[str, list[str]]] = {}  # recorded at dispatch (e2er ≥ 0.13)

    for etype, stage, sp, payload, created in events:
        data = json.loads(payload) if payload else {}
        data = data if isinstance(data, dict) else {"value": data}
        at = _utc(created)
        where = {"segment": seg} if seg >= 0 else {}
        if etype == "run_identity":
            seg += 1
            rec.segments.append(
                {
                    "commit": data.get("git_sha"),
                    "version": data.get("package_version"),
                    **({"uncommitted_changes": bool(data["git_dirty"])} if data.get("git_dirty") is not None else {}),
                    "from": at,
                }
            )
        elif etype == "template_components":
            if seg >= 0:
                rec.segments[seg]["template"] = data.get("template")
            template_skills[seg] = {k: list(v) for k, v in (data.get("skills") or {}).items()}
        elif etype == "phase_start":
            phase = stage
        elif etype == "specialist_start":
            started[sp] = (at, data)
        elif etype in ("specialist_end", "specialist_failed"):
            start_at, start_data = started.pop(sp, (None, {}))
            c = next(
                (
                    (i, r)
                    for i, r in enumerate(contribs)
                    if i not in used_contribs and r[0] == sp and in_window(_utc(r[4]), start_at, at)
                ),
                None,
            )
            if c is not None:
                used_contribs.add(c[0])
            mine = [
                i
                for i, r in enumerate(calls)
                if i not in used_calls and r[0] == sp and in_window(_utc(r[3]), start_at, at)
            ]
            used_calls.update(mine)
            models = list(dict.fromkeys((calls[i][1], calls[i][2]) for i in mine))
            ok = etype == "specialist_end" and bool(data.get("success", c[1][2] if c else True))
            step: dict[str, Any] = {
                "type": "specialist",
                "phase": phase,
                "specialist": sp,
                **where,
                "backend": models[0][0] if models else None,
                "model": models[0][1] if models else None,
                "started": start_at,
                "ended": at,
                "accepted": ok,
            }
            if len(models) > 1:
                step["models"] = [{"backend": b, "model": m} for b, m in models]
            why = (c[1][3] if c else None) or (data.get("error") if etype == "specialist_failed" else None)
            if why:
                step["stopped_by"] = _clip(str(why), 2000)
            if sp in pending_rerun:
                step["sent_back"] = pending_rerun.pop(sp)
            outputs = data.get("outputs")
            if isinstance(outputs, list):  # recorded by the runner at the time
                shown = []
                for o in outputs:
                    if not isinstance(o, dict) or not o.get("file"):
                        continue
                    name = _workspace_name(str(o["file"]), paper_id)
                    where_now = _bundle_file(name, files)
                    shown.append(
                        {
                            "file": where_now or name,
                            "sha256": o.get("sha256"),
                            **({} if where_now else {"exported": False}),
                            **({"unchanged": True} if o.get("changed") is False else {}),
                        }
                    )
                if shown:
                    step["output"] = shown[0]
                    if len(shown) > 1:
                        step["outputs"] = shown
            elif c and c[1][1]:
                name = _workspace_name(str(c[1][1]), paper_id)
                where_now = _bundle_file(name, files)
                step["output"] = {"file": where_now or name, "recorded": False, "exported": bool(where_now)}
            if isinstance(start_data.get("skills"), list) and seg >= 0:
                step_skills.setdefault(seg, {})[sp] = [str(s) for s in start_data["skills"]]
            if sp not in rec.agents and not str(sp).startswith("strategist"):
                rec.agents.append(sp)
            rec.workflow.append(step)
        elif etype == "gate_enforced":
            rec.workflow.append(
                {
                    "type": "check",
                    "phase": phase,
                    "check": data.get("gate") or stage,
                    **where,
                    "passed": bool(data.get("passed")),
                    "enforced": bool(data.get("enforced")),
                    "at": at,
                    **(
                        {"detail": _clip(str(data["detail"]), 2000)}
                        if data.get("detail") and not data.get("passed")
                        else {}
                    ),
                }
            )
        elif etype == "gate_halted":
            reasons = data.get("reasons") or []
            rec.workflow.append(
                {
                    "type": "check",
                    "phase": phase,
                    "check": stage,
                    **where,
                    "passed": False,
                    "enforced": True,
                    "halted": True,
                    "at": at,
                    "detail": _clip("; ".join(str(r) for r in reasons), 2000),
                }
            )
        elif etype == "preregistration_check":
            rec.workflow.append(
                {
                    "type": "check",
                    "phase": phase,
                    "check": "preregistration",
                    **where,
                    "passed": bool(data.get("passed")),
                    "enforced": True,
                    "at": at,
                    "deviations": _clip(list(data.get("deviations") or [])),
                    **({"frozen_at": _utc(data["frozen_at"])} if data.get("frozen_at") else {}),
                }
            )
        elif etype == "researcher_action":
            rec.workflow.append({**researcher_step(data, created, phase), **where})
        elif etype == "researcher_input":
            rec.workflow.append(
                {
                    "type": "researcher",
                    "action": "supplied_input",
                    "phase": phase,
                    "step": stage,
                    **where,
                    "at": at,
                    "file": data.get("file"),
                    "sha256": data.get("sha256"),
                    "supplied_by": data.get("supplied_by", "researcher"),
                    **({"replaces_sha256": data["replaces_sha256"]} if data.get("replaces_sha256") else {}),
                }
            )
        elif etype == "researcher_rerun":
            # The runner carrying out a send-back or a rerun (the researcher's own
            # action is the researcher_action row before it).
            pending_rerun[stage] = {"at": at, "remark": _clip(data.get("remark"))}
        elif etype in ("phase_end", "specialist_skipped"):
            continue
        else:
            name = {"preregistration": "preregistration_frozen"}.get(etype, etype)
            ev: dict[str, Any] = {"event": name, **({"step": stage} if stage else {}), **where, "at": at}
            for k, v in data.items():
                if k in ev:
                    continue
                ev[k] = _utc(v) if k.endswith(("_at", "at")) and isinstance(v, str) else _clip(v)
            rec.events.append(ev)
    for target, info in pending_rerun.items():
        rec.events.append({"event": "rerun", "step": target, **info})
    rec.events.sort(key=lambda e: e.get("at") or "")

    if rec.workflow and not any(isinstance(s.get("output"), dict) and "sha256" in s["output"] for s in rec.workflow):
        # An older run: the export's hash goes to the last accepted step that wrote each file.
        last: dict[str, dict[str, Any]] = {}
        for s in rec.workflow:
            out = s.get("output")
            if isinstance(out, dict) and out.get("recorded") is False and s.get("accepted"):
                last[out["file"]] = s
        for s in rec.workflow:
            out = s.get("output")
            if not (isinstance(out, dict) and out.get("recorded") is False):
                continue
            if last.get(out["file"]) is s and out.get("exported"):
                out["sha256_at_export"] = files[out["file"]]["sha256"]
            elif out.get("exported") and s.get("accepted"):
                out["superseded"] = True

    # Skills per agent and segment: recorded at dispatch, else the registry at the
    # segment's commit plus the template's additions recorded in that segment.
    for i, segment in enumerate(rec.segments):
        registry = _registry_skills_at(segment["commit"]) if segment.get("commit") else None
        ran = {s["specialist"] for s in rec.workflow if s.get("type") == "specialist" and s.get("segment") == i}
        recorded = step_skills.get(i, {})
        if ran - set(recorded) and registry is None:
            segment["skills"] = "unresolved: the registry at this commit could not be read"
        elif ran - set(recorded):
            segment["skills"] = "the registry at this commit and the template's additions"
        elif ran:
            segment["skills"] = "recorded at dispatch"
        for agent in sorted(ran):
            got = recorded.get(agent)
            if got is None:
                base = (registry or {}).get(agent, [])
                got = list(dict.fromkeys([*base, *template_skills.get(i, {}).get(agent, [])]))
            merged = rec.skills.setdefault(agent, [])
            merged += [x for x in got if x not in merged]
            for comp in [f"agent:{agent}", *(f"skill:e2er/{x}" for x in got)]:
                segs = rec.component_segments.setdefault(comp, [])
                if i not in segs:
                    segs.append(i)
        if segment.get("template"):
            segs = rec.component_segments.setdefault(f"template:{segment['template']}", [])
            if i not in segs:
                segs.append(i)
        for s in rec.workflow:
            if s.get("type") == "specialist" and s.get("segment") == i and s.get("backend"):
                conn = BACKEND_CONNECTOR.get(s["backend"])
                if conn:
                    segs = rec.component_segments.setdefault(f"connector:{conn}", [])
                    if i not in segs:
                        segs.append(i)
        segment["steps"] = sum(1 for s in rec.workflow if s.get("segment") == i)
    return rec


def recorded_workflow(db: Path, paper_id: str, bundle: Path | None = None) -> list[dict[str, Any]]:
    """The run's steps in order (see :func:`read_run`)."""
    return read_run(db, paper_id, _bundle_files(bundle)).workflow


def _bundle_files(bundle: Path | None) -> dict[str, Any]:
    if bundle is not None and (bundle / "provenance.json").is_file():
        files = json.loads((bundle / "provenance.json").read_text(encoding="utf-8")).get("files", {})
        return files if isinstance(files, dict) else {}
    return {}


def researcher_step(data: dict[str, Any], at: str, phase: str | None = None) -> dict[str, Any]:
    """A dossier workflow step for one researcher action (see core/pipeline/researcher.py).

    Every field of the action is kept (a cancellation's ``by``, ``via`` and
    ``previous_status``, a rerun's ``reruns``), times in UTC.
    """
    step: dict[str, Any] = {
        "type": "researcher",
        "action": data.get("action"),
        "phase": phase,
        "step": data.get("step"),
        "at": _utc(data.get("at") or at),
    }
    for key, value in data.items():
        if key not in step and value is not None:
            step[key] = _clip(value)
    return step


def _component_entry(cid: str, repository: str | None, commits: list[str | None]) -> dict[str, Any]:
    pins = [_pin(cid, repository, c) for c in commits] or [_pin(cid, repository, None)]
    entry: dict[str, Any] = {"id": cid, "kind": cid.split(":", 1)[0], "name": cid.split(":", 1)[1].split("/")[-1]}
    entry["pin"] = pins[-1]
    if len(pins) > 1:
        entry["pins"] = pins
    return entry


def build_dossier(
    manifest: dict[str, Any],
    repository: str | None = "https://github.com/bhanneke/E2ER-project",
    db: Path | None = None,
    bundle: Path | None = None,
    availability: dict[str, dict[str, Any]] | None = None,
    run: RunRecord | None = None,
) -> dict[str, Any]:
    """The dossier document for a research-object manifest (see research_object.py).

    With the run database (or its ``run`` record), the dossier says what the
    run recorded: every step, the E2ER commit of each part of the run
    (``e2er.segments``), every template, specialist, skill and connector
    pinned at each commit it ran on, the run's events and its outcome.
    Without it (``e2er publish --no-db``) the workflow is absent and the
    dossier says so; nothing is filled in from the machine that publishes.

    A manifest with ``purpose`` (and ``kind``) passes them into the dossier.
    ``availability`` is deep-copied: the caller's later changes never reach
    a dossier whose id was already computed.
    """
    paper_id = (manifest.get("process") or {}).get("paper_id") or (manifest.get("run") or {}).get("paper_id")
    if paper_id is None and bundle is not None and (bundle / "provenance.json").is_file():
        paper_id = json.loads((bundle / "provenance.json").read_text(encoding="utf-8")).get("run", {}).get("paper_id")
    if run is None and db is not None and paper_id:
        run = read_run(db, paper_id, _bundle_files(bundle))
    ai, proc = manifest["ai"], manifest["process"]
    models = sorted({(u["backend"], u["model"]) for u in ai.get("usage", [])})
    prereg = _preregistration(bundle)
    recorded = run is not None and run.recorded
    doc: dict[str, Any] = {"study": {"title": manifest["title"]}}
    if recorded:
        assert run is not None
        segments = run.segments
        last = segments[-1] if segments else {}
        commit = last.get("commit")
        doc["schema"] = SCHEMA_RUN
        doc["e2er"] = {
            "version": last.get("version"),
            "repository": repository if commit else None,
            "commit": commit,
            **({"uncommitted_changes": any(s.get("uncommitted_changes") for s in segments)} if segments else {}),
            "segments": segments,
            "exported_with": proc.get("e2er_version"),
        }
        commits_of = {cid: [segments[i].get("commit") for i in segs] for cid, segs in run.component_segments.items()}
        uses = list(manifest["dependencies"]["uses"])
        backend_conn = BACKEND_CONNECTOR.get(ai.get("backend") or "")
        if backend_conn:
            uses.append(f"connector:{backend_conn}")
        components = []
        for cid in sorted(set(uses) | set(commits_of)):
            commits = list(dict.fromkeys(commits_of.get(cid) or [c.get("commit") for c in segments[-1:]]))
            components.append(_component_entry(cid, repository, commits))
        workflow = run.workflow
    else:
        doc["schema"] = SCHEMA
        doc["e2er"] = {"version": proc.get("e2er_version"), "repository": None, "commit": None}
        uses = list(manifest["dependencies"]["uses"])
        backend_conn = BACKEND_CONNECTOR.get(ai.get("backend") or "")
        if backend_conn:
            uses.append(f"connector:{backend_conn}")
        components = [_component_entry(c, repository, []) for c in sorted(set(uses))]
        workflow = []
    doc["run"] = {
        "template": proc.get("template"),
        "mode": proc.get("mode"),
        "governance": proc.get("governance"),
        "backend": ai.get("backend"),
        "models": [{"backend": b, "model": m} for b, m in models]
        or ([{"backend": ai.get("backend"), "model": ai.get("model")}] if ai.get("model") else []),
        "exported": proc.get("exported"),
    }
    if recorded:
        assert run is not None
        doc["run"]["outcome"] = run.outcome
        doc["run"]["events"] = run.events
    else:
        doc["run"]["workflow_recorded"] = False
        doc["run"]["note"] = (
            "Published without the run database: the steps of the run, the commit it ran on and the "
            "researcher's actions are not recorded in this dossier."
        )
    doc["components"] = components
    doc["data"] = [{"path": d["path"], "sha256": d["sha256"]} for d in manifest.get("data", [])]
    doc["workflow"] = workflow
    if not recorded and (prereg is not None or any(w.get("type") == "researcher" for w in workflow)):
        doc["schema"] = SCHEMA_RESEARCHER
    if prereg is not None:
        doc["preregistration"] = prereg
    if any_public(availability):
        if not recorded:
            doc["schema"] = SCHEMA_AVAILABILITY
        doc["availability"] = copy.deepcopy(availability)
    if manifest.get("purpose"):
        doc["purpose"] = manifest["purpose"]
        if manifest.get("kind"):
            doc["kind"] = manifest["kind"]
    if manifest.get("amendments"):
        doc["amendments"] = copy.deepcopy(manifest["amendments"])
    return doc


def _preregistration(bundle: Path | None) -> dict[str, Any] | None:
    """The frozen pre-registration of an exported study: file, fingerprint, time, plan files, deposit."""
    if bundle is None:
        return None
    from .pipeline.preregistration import load_lock

    lock = load_lock(bundle / "design")
    if lock is None:
        return None
    out = {
        "file": f"design/{lock.get('file', 'preregistration.md')}",
        "sha256": lock.get("sha256"),
        "frozen_at": _utc(lock.get("frozen_at")),
    }
    if isinstance(lock.get("plan_files"), dict) and lock["plan_files"]:
        out["plan_files"] = dict(lock["plan_files"])
    if lock.get("deposit"):
        out["deposit"] = lock["deposit"]
    return out


_AUTHOR = re.compile(r"\\author\{((?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*)\}")
_E2ER_THANKS = re.compile(r"\\thanks\{(?:This paper was produced with e2er|Demonstration\.)(?:[^{}]|\{[^{}]*\})*\}")
_WITH_E2ER = re.compile(r"\s*with e2er\s*$")


def footnote(doc: dict[str, Any] | None, did: str) -> str:
    """The first-page footnote: what the dossier at ``did`` lists, and only what it lists."""
    url = f"\\url{{{dossier_url(did)}}}"
    if doc is not None and doc.get("run", {}).get("workflow_recorded") is False:
        return (
            "This paper was produced with e2er. Its dossier records the template, specialists, skills, connectors "
            "and AI models used and the fingerprints of the data; it was published without the run's database, so "
            f"the steps of the run are not recorded: {url}."
        )
    unresolved = doc is not None and any(
        "unresolved" in str(p.get("note", "")) for c in doc.get("components", []) for p in c.get("pins", [c["pin"]])
    )
    pinned = (
        "pinned to the versions the run used where E2ER's repository holds them"
        if unresolved
        else "each pinned to the version the run used"
    )
    return (
        "This paper was produced with e2er. Its dossier lists every step of the run (the specialists, the checks "
        "and the researcher's actions), the files the steps produced, and the template, specialists, skills, "
        f"connectors and AI models used, {pinned}: {url}."
    )


def stamp_paper(
    tex: str,
    author: str | None,
    did: str,
    *,
    purpose: str | None = None,
    kind: str | None = None,
    doc: dict[str, Any] | None = None,
) -> str:
    """Write the dossier footnote (and the disclaimer) into a paper's first page; the author line with ``author``.

    With ``author``: ``\\author{<author> with e2er\\thanks{...}}``. Without: the
    paper's own author line is kept and the footnote added to it (a paper
    without one gets ``\\author{e2er\\thanks{...}}``). An existing stamp is
    replaced, so stamping twice gives the same text. A demonstration study
    (``purpose="demonstration"``) gets the disclaimer as a second footnote,
    the replication wording when ``kind="replication"``; without a purpose an
    earlier disclaimer is removed.
    """
    notes = f"\\thanks{{{footnote(doc, did)}}}"
    if purpose == DEMONSTRATION:
        notes += f"\\thanks{{{disclaimer(kind)}}}"
    m = _AUTHOR.search(tex)
    if author:
        block = f"\\author{{{author} with e2er{notes}}}"
    else:
        own = _E2ER_THANKS.sub("", m.group(1)).strip() if m else ""
        block = f"\\author{{{own or 'e2er'}{notes}}}"
    if m:
        return tex[: m.start()] + block + tex[m.end() :]
    return tex.replace("\\begin{document}", block + "\n\\begin{document}", 1)
