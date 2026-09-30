"""A research process as data.

Today `PipelineRunner.run()` sequences phases in Python. This module reads the
same sequence from a file, so a researcher can define their own process —
phases, specialists, checks — without writing code, and so a paper can ship the
exact pipeline that produced it.

Nothing here drives the runner yet. It is loaded, validated, and asserted
against what the runner actually does, which is the order the refactor has to
happen in: pin the behaviour as data first, change the executor second.

Two things the design missed and the sequence test found, both encoded here:

  * The sequence is conditional on mode. `iterative`, `self_attack` and `polish`
    only run in iterative mode, so `steps` carry `modes`.
  * Teardown is not a step. compile, audit export, GitHub push and structured
    export run however the run ended, swallow their own errors, and cannot halt
    anything — so they are a separate `finalize` list, not entries in `steps`.

See docs/PIPELINES.md.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from ..governance import GATES, RELIABILITY_CHECKS

logger = get_logger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "docs" / "schemas" / "pipeline.schema.json"

#: Checks that run whether or not a pipeline asks for them. A pipeline may add
#: checks and may enforce them harder; it may not remove these. Without a floor,
#: "the gates are not yours" stops being true the moment somebody writes their
#: own pipeline, because they would simply omit them.
MANDATORY_CHECKS: frozenset[str] = frozenset({"contracts"})

#: `claims` is not in governance.GATES yet — it arrived with the corpus and is
#: enforced by the extractor rather than the runner. Allowed in a pipeline so a
#: theory process can declare it, and listed apart so the difference is visible.
KNOWN_CHECKS: frozenset[str] = frozenset(GATES) | {"claims"} | frozenset(RELIABILITY_CHECKS)

STEP_KINDS: frozenset[str] = frozenset({"strategist", "specialists", "gate", "aggregate", "researcher", "preregister"})

#: Steps where the run stops for the researcher. `researcher` lets them approve,
#: edit the named files, give an instruction for the following steps or send a
#: step back; `preregister` does the same for the assembled pre-registration and
#: freezes it on approval. With `after = [...]` either one sits inside the
#: strategist's dispatch, right after those specialists have written their
#: output (e.g. between the design specialists and estimation).
RESEARCHER_KINDS: frozenset[str] = frozenset({"researcher", "preregister"})
FINALIZE_ACTIONS: frozenset[str] = frozenset({"compile", "audit_export", "github_push", "structured_export"})
RUN_MODES: frozenset[str] = frozenset({"single_pass", "iterative"})

#: Settings a gate step may carry, per check, with their type. A check that is
#: not listed takes none. Unknown keys are refused, like every other typo.
CHECK_SETTINGS: dict[str, dict[str, type | tuple[type, ...]]] = {
    "event_window": {"min_estimation_days": int, "min_gap_days": int, "max_overlap_share": (int, float)},
    "package_integrity": {"max_mb": int},
    "sandbox": {
        "cpus": int,
        "memory_gb": int,
        "timeout_minutes": int,
        "install_timeout_minutes": int,
        "snapshot": str,
    },
    "reproduction": {"minor_rel_tolerance": (int, float)},
}

#: Text settings and the form each must take.
TEXT_SETTINGS: dict[str, re.Pattern[str]] = {
    # Which package versions the sandbox installs: those current at the
    # replication package's publication date, the newest, or a given date.
    "snapshot": re.compile(r"^(package-date|latest|\d{4}-\d{2}-\d{2})$"),
}

#: Checks that run as a step of their own, in sequence, rather than inside the
#: strategist's dispatch. Each is a function of the workspace and the step's
#: settings that returns a verdict (see `_run_check_step` in the runner).
SEQUENCE_CHECKS: frozenset[str] = frozenset({"package_integrity", "sandbox", "reproduction"})


class PipelineError(ValueError):
    """A pipeline file that cannot be trusted to run.

    Always raised at load time, never mid-run: the point of validating a
    pipeline is that a typo costs a clear message instead of forty minutes and
    a model bill.
    """


@dataclass(frozen=True)
class StepSpec:
    kind: str
    name: str
    run: tuple[str, ...] = ()
    check: str = ""
    on_fail: str = "halt"
    parallel: bool = False
    modes: tuple[str, ...] = ()  # empty = every mode
    resumable: bool = True
    files: tuple[str, ...] = ()  # researcher/preregister: files the researcher sees and may edit
    after: tuple[str, ...] = ()  # researcher/preregister/gate: act right after these specialists
    settings: dict[str, Any] = field(default_factory=dict, hash=False)  # gate: the check's parameters

    def applies_to(self, mode: str) -> bool:
        return not self.modes or mode in self.modes

    def will_run(self, mode: str, complete: frozenset[str] | set[str]) -> bool:
        """Would this step execute, given the mode and what is already done?"""
        if not self.applies_to(mode):
            return False
        if self.after:
            return False  # happens inside another step (the strategist's dispatch), not in sequence
        if self.resumable and self.name in complete:
            return False
        return True


@dataclass(frozen=True)
class PipelineSpec:
    name: str
    description: str = ""
    methodologies: tuple[str, ...] = ()
    steps: tuple[StepSpec, ...] = ()
    finalize: tuple[str, ...] = ()
    source: Path | None = None
    #: specialist -> skills / sidecar files this template adds (see components.py)
    skills: dict[str, tuple[str, ...]] = field(default_factory=dict, hash=False)
    sidecars: dict[str, tuple[str, ...]] = field(default_factory=dict, hash=False)

    def sequence_for(self, mode: str, complete: frozenset[str] | set[str] = frozenset()) -> list[str]:
        """The stage names that would run, in order.

        The spec's own prediction of the sequence. Comparing it against what the
        runner actually does is how the refactor is kept honest — two
        independent derivations of the same list.
        """
        return [s.name for s in self.steps if s.will_run(mode, complete)]

    def checks(self) -> list[str]:
        """Every check this pipeline declares, plus the floor it cannot remove."""
        declared = {s.check for s in self.steps if s.kind == "gate" and s.check}
        return sorted(declared | MANDATORY_CHECKS)

    def declared_checks(self) -> list[str]:
        """Only what the file asked for — so a report can distinguish the two."""
        return sorted({s.check for s in self.steps if s.kind == "gate" and s.check})

    def step(self, name: str) -> StepSpec | None:
        return next((s for s in self.steps if s.name == name), None)


# ── parsing ──────────────────────────────────────────────────────────────────


def _fail(source: Path | str, message: str) -> None:
    raise PipelineError(f"{source}: {message}")


def _step_from(raw: Any, source: Path | str, index: int) -> StepSpec:
    where = f"step {index + 1}"
    if not isinstance(raw, dict):
        _fail(source, f"{where} is not a table")

    unknown = set(raw) - {
        "kind",
        "name",
        "run",
        "check",
        "on_fail",
        "parallel",
        "modes",
        "resumable",
        "files",
        "after",
        "settings",
    }
    if unknown:
        # A typo is a mistake, not an extension point. Silently ignoring
        # `specialists = [...]` where `run = [...]` was meant would produce a
        # step that dispatches nobody.
        #
        # One case deserves its own sentence, because the file looks right and
        # TOML disagrees: a bare key-value after a table array belongs to that
        # table, so a top-level setting written at the foot of the file is
        # parsed as a key of the last step. Written this file that way first
        # time; "unknown key: finalize" is a baffling thing to be told.
        misplaced = unknown & {"name", "description", "methodologies", "finalize", "steps"}
        if misplaced:
            _fail(
                source,
                f"{where} has {', '.join(sorted(misplaced))}, which is a top-level setting. "
                "In TOML a bare key after a [[steps]] table belongs to that table — "
                "move it above the first [[steps]].",
            )
        _fail(source, f"{where} has unknown key(s): {', '.join(sorted(unknown))}")

    kind = raw.get("kind", "")
    name = raw.get("name", "")
    if kind not in STEP_KINDS:
        _fail(source, f"{where} has unknown kind {kind!r} (expected one of {', '.join(sorted(STEP_KINDS))})")
    if not name:
        _fail(source, f"{where} has no name")

    run = tuple(raw.get("run", ()) or ())
    check = raw.get("check", "") or ""
    modes = tuple(raw.get("modes", ()) or ())

    if kind in ("specialists", "aggregate") and not run:
        _fail(source, f"{where} ({name}) is a {kind} step with no specialists to run")
    if kind == "gate":
        if not check:
            _fail(source, f"{where} ({name}) is a gate with no check")
        if check not in KNOWN_CHECKS:
            _fail(source, f"{where} ({name}) names unknown check {check!r} (known: {', '.join(sorted(KNOWN_CHECKS))})")

    files = tuple(raw.get("files", ()) or ())
    after = tuple(raw.get("after", ()) or ())
    if kind in RESEARCHER_KINDS:
        if run or check:
            _fail(source, f"{where} ({name}) is a {kind} step; it runs no specialists and no check")
        bad = [f for f in files if "/" in f or f.startswith(".")]
        if bad:
            _fail(source, f"{where} ({name}) names files outside the workspace: {', '.join(bad)}")
    elif kind == "gate" and after and check in SEQUENCE_CHECKS:
        _fail(source, f"{where} ({name}): the {check} check runs as a step of its own; it takes no `after`")
    elif kind == "gate" and after:
        # A gate with `after` runs inside the strategist's dispatch, right after
        # those specialists and before anything else of that phase — which is
        # how a design check can sit between the design and the estimation.
        if files:
            _fail(source, f"{where} ({name}): `files` belongs to researcher and preregister steps")
    elif files or after:
        _fail(source, f"{where} ({name}): `files` and `after` belong to researcher, preregister and gate steps")

    settings: dict[str, Any] = raw.get("settings", {}) or {}
    if settings:
        if kind != "gate":
            _fail(source, f"{where} ({name}): `settings` belongs to gate steps")
        if not isinstance(settings, dict):
            _fail(source, f"{where} ({name}): `settings` must be a table")
        allowed = CHECK_SETTINGS.get(check, {})
        bad_keys = set(settings) - set(allowed)
        if bad_keys:
            _fail(
                source,
                f"{where} ({name}): check {check!r} has no setting(s) {', '.join(sorted(bad_keys))}"
                + (f" (known: {', '.join(sorted(allowed))})" if allowed else ""),
            )
        for key, value in settings.items():
            if allowed[key] is str:
                pattern = TEXT_SETTINGS[key]
                if not isinstance(value, str) or not pattern.match(value):
                    _fail(source, f"{where} ({name}): setting {key} must match {pattern.pattern}, not {value!r}")
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                _fail(source, f"{where} ({name}): setting {key} must be a non-negative number, not {value!r}")
            if not isinstance(value, allowed[key]):
                _fail(source, f"{where} ({name}): setting {key} must be a whole number, not {value!r}")
        for share in ("max_overlap_share", "minor_rel_tolerance"):
            if share in settings and float(settings[share]) > 1:
                _fail(source, f"{where} ({name}): {share} is a share between 0 and 1")

    on_fail = raw.get("on_fail", "halt")
    if on_fail not in ("halt", "retry", "shadow"):
        _fail(source, f"{where} ({name}) has unknown on_fail {on_fail!r}")

    bad_modes = set(modes) - RUN_MODES
    if bad_modes:
        _fail(source, f"{where} ({name}) names unknown mode(s): {', '.join(sorted(bad_modes))}")

    return StepSpec(
        kind=kind,
        name=name,
        run=run,
        check=check,
        on_fail=on_fail,
        parallel=bool(raw.get("parallel", False)),
        modes=modes,
        resumable=bool(raw.get("resumable", True)),
        files=files,
        after=after,
        settings=dict(settings),
    )


def spec_from_dict(data: dict[str, Any], *, source: Path | str = "<dict>") -> PipelineSpec:
    """Build and validate a spec from parsed TOML."""
    unknown = set(data) - {"name", "description", "methodologies", "steps", "finalize", "skills", "sidecars"}
    if unknown:
        _fail(source, f"unknown top-level key(s): {', '.join(sorted(unknown))}")

    name = data.get("name", "")
    if not name:
        _fail(source, "pipeline has no name")

    raw_steps = data.get("steps") or []
    if not raw_steps:
        _fail(source, "pipeline has no steps")

    steps = tuple(_step_from(raw, source, i) for i, raw in enumerate(raw_steps))

    seen: set[str] = set()
    for s in steps:
        if s.name in seen:
            # Stage names are the resume key. Two steps sharing one means the
            # second is skipped forever after the first completes.
            _fail(source, f"duplicate step name {s.name!r}")
        seen.add(s.name)

    finalize = tuple(data.get("finalize", ()) or ())
    bad = set(finalize) - FINALIZE_ACTIONS
    if bad:
        _fail(source, f"unknown finalize action(s): {', '.join(sorted(bad))}")

    return PipelineSpec(
        name=name,
        description=data.get("description", ""),
        methodologies=tuple(data.get("methodologies", ()) or ()),
        steps=steps,
        finalize=finalize,
        source=Path(source) if isinstance(source, Path) else None,
        skills=_components(data.get("skills"), "skills", source),
        sidecars=_components(data.get("sidecars"), "sidecars", source),
    )


def _components(raw: Any, table: str, source: Path | str) -> dict[str, tuple[str, ...]]:
    """`[skills]` or `[sidecars]`: specialist -> what the template adds to it.

    Checked at load: the specialist must exist, a skill must resolve to a file
    e2er ships or has installed, and a sidecar must be a top-level JSON file —
    a skill that silently fails to load would make the template claim a method
    its specialists never read.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        _fail(source, f"[{table}] must be a table of specialist = [...]")
    from ...skills.loader import skill_exists
    from ..specialists.registry import SPECIALIST_ARTIFACTS

    out: dict[str, tuple[str, ...]] = {}
    for specialist, items in raw.items():
        if specialist not in SPECIALIST_ARTIFACTS:
            _fail(source, f"[{table}] names unknown specialist {specialist!r}")
        if not isinstance(items, list) or not all(isinstance(i, str) and i for i in items):
            _fail(source, f"[{table}] {specialist} must be a list of names")
        for item in items:
            if table == "skills" and not skill_exists(item):
                _fail(source, f"[skills] {specialist}: no skill {item!r} (a path under skills/files, without .md)")
            if table == "sidecars" and ("/" in item or item.startswith(".") or not item.endswith(".json")):
                _fail(source, f"[sidecars] {specialist}: {item!r} must be a top-level .json file name")
        out[specialist] = tuple(dict.fromkeys(items))
    return out


def load_spec(path: Path) -> PipelineSpec:
    """Read one pipeline file."""
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        # tomllib reports the line; keep it, and add the file the reader needs
        # in order to go and look.
        raise PipelineError(f"{path}: not valid TOML: {e}") from e
    except OSError as e:
        raise PipelineError(f"{path}: cannot read: {e}") from e
    return spec_from_dict(raw, source=path)


# ── discovery ────────────────────────────────────────────────────────────────


def search_paths(project: Path | None = None) -> list[Path]:
    """Where pipelines are looked for, most specific first.

    Project-local wins so a paper can carry the exact pipeline that produced it
    — which is what makes a pipeline a citable artifact rather than a local
    preference.
    """
    here = Path(project or Path.cwd())
    return [
        here / "pipelines",
        Path.home() / ".e2er" / "pipelines",
        Path(__file__).resolve().parents[3] / "pipelines",
    ]


def find_spec(name: str, *, project: Path | None = None) -> PipelineSpec:
    """Resolve a pipeline by name. Raises with every location tried."""
    looked: list[Path] = []
    for root in search_paths(project):
        candidate = root / f"{name}.toml"
        looked.append(candidate)
        if candidate.is_file():
            logger.debug("pipeline %r resolved to %s", name, candidate)
            return load_spec(candidate)

    raise PipelineError(f"no pipeline named {name!r}. Looked in:\n  " + "\n  ".join(str(p) for p in looked))


def available(project: Path | None = None) -> dict[str, Path]:
    """Every pipeline that can be resolved, name -> the file that wins."""
    found: dict[str, Path] = {}
    for root in search_paths(project):
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.toml")):
            found.setdefault(path.stem, path)
    return found
