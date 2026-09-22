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

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from ..governance import GATES

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
KNOWN_CHECKS: frozenset[str] = frozenset(GATES) | {"claims"}

STEP_KINDS: frozenset[str] = frozenset({"strategist", "specialists", "gate", "aggregate"})
FINALIZE_ACTIONS: frozenset[str] = frozenset({"compile", "audit_export", "github_push", "structured_export"})
RUN_MODES: frozenset[str] = frozenset({"single_pass", "iterative"})


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

    def applies_to(self, mode: str) -> bool:
        return not self.modes or mode in self.modes

    def will_run(self, mode: str, complete: frozenset[str] | set[str]) -> bool:
        """Would this step execute, given the mode and what is already done?"""
        if not self.applies_to(mode):
            return False
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

    unknown = set(raw) - {"kind", "name", "run", "check", "on_fail", "parallel", "modes", "resumable"}
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
    )


def spec_from_dict(data: dict[str, Any], *, source: Path | str = "<dict>") -> PipelineSpec:
    """Build and validate a spec from parsed TOML."""
    unknown = set(data) - {"name", "description", "methodologies", "steps", "finalize"}
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
    )


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
