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
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
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
    "field_retrieve": {"max_papers": int, "max_requests": int},
    "field_network": {"max_isolated_share": (int, float), "max_missing_refs_share": (int, float), "min_papers": int},
    "field_main_path": {"key_routes": int},
    # The descriptive template's data check (src/core/pipeline/data_quality.py).
    "data_quality": {"max_missing_share": (int, float)},
    # The time-series template's checks (src/core/pipeline/forecast_checks.py).
    "forecast_design": {"min_train_periods": int},
    "forecast_evaluation": {"error_tolerance": (int, float)},
}

#: The persona skill specialists read unless the template names another (``base_skill``).
DEFAULT_BASE_SKILL = "base/economist"

#: Text settings and the form each must take.
TEXT_SETTINGS: dict[str, re.Pattern[str]] = {
    # Which package versions the sandbox installs: those current at the
    # replication package's publication date, the newest, or a given date.
    "snapshot": re.compile(r"^(package-date|latest|\d{4}-\d{2}-\d{2})$"),
}

#: Checks that run as a step of their own, in sequence, rather than inside the
#: strategist's dispatch. Each is a function of the workspace and the step's
#: settings that returns a verdict (see `_run_check_step` in the runner).
SEQUENCE_CHECKS: frozenset[str] = frozenset(
    {
        "package_integrity",
        "sandbox",
        "reproduction",
        # The field-map template (src/core/pipeline/fieldmap_checks.py).
        "field_retrieve",
        "field_network",
        "field_main_path",
        "field_robustness",
        "field_map",
        # The number and citation checks of the draft, as steps of their own in a
        # template without a review panel (inside the review step otherwise).
        "numbers",
        "citations",
        # Figures re-read from the data they name (data_quality.py), and the
        # out-of-sample evaluation of a forecast against the frozen hold-out
        # (forecast_checks.py): both after the analysis, before the draft review.
        "figure_data",
        "forecast_evaluation",
    }
)


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
    label: str = ""  # the step's name on the dashboard (src/core/labels.py when empty)
    #: researcher/preregister: the step runs only when the researcher chooses it for the run
    #: (New study's "also stop" choices, ``e2er run --review-at <name>``).
    optional: bool = False

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
    title: str = ""  # the template's name on the dashboard (src/core/labels.py when empty)
    methodologies: tuple[str, ...] = ()
    steps: tuple[StepSpec, ...] = ()
    finalize: tuple[str, ...] = ()
    source: Path | None = None
    #: specialist -> skills / sidecar files this template adds (see components.py)
    skills: dict[str, tuple[str, ...]] = field(default_factory=dict, hash=False)
    sidecars: dict[str, tuple[str, ...]] = field(default_factory=dict, hash=False)
    #: Work this template is based on or draws from (``[[credit]]``), as written in the file.
    credit: tuple[dict[str, Any], ...] = field(default=(), hash=False)
    #: The kind of results the study reports (``result_kinds.py``): which contract the
    #: estimation check holds the results file to, which files the number check reads,
    #: and which schema skill the analysis specialist reads.
    results: str = "regression"
    #: Whether the study makes a causal claim: then the identification strategist's
    #: identification_spec.json is required and the results must implement it.
    causal: bool = True
    #: The persona skill read in place of ``base/economist`` (``base/researcher`` outside economics).
    base_skill: str = DEFAULT_BASE_SKILL
    #: The domain data skills of the data architect and analyst (None: the registry's,
    #: blockchain and DeFi included; a list replaces those with its own).
    data_skills: tuple[str, ...] | None = None
    #: Weight of each reviewer of the panel in the combined score (absent: the default weight).
    review_weights: dict[str, float] = field(default_factory=dict, hash=False)

    def panel(self) -> list[str]:
        """The reviewers of this template: its `aggregate` step's, in the registry's order.

        Without an aggregate step, e2er's default panel (a template that never
        reviews never asks).
        """
        from ..specialists.registry import ALL_REVIEWERS, REVIEWER_SPECIALISTS

        step = next((s for s in self.steps if s.kind == "aggregate"), None)
        if step is None:
            return list(REVIEWER_SPECIALISTS)
        return [r for r in ALL_REVIEWERS if r in step.run]

    def polish(self) -> list[str]:
        """The polish specialists of this template (its ``polish`` step), in the registry's order."""
        from ..specialists.registry import POLISH_SPECIALISTS

        step = self.step("polish")
        if step is None:
            return list(POLISH_SPECIALISTS)
        return [p for p in POLISH_SPECIALISTS if p in step.run]

    def is_default_core(self) -> bool:
        """True when the template keeps e2er's economics defaults (results, causal, persona, data skills)."""
        return (
            self.results == "regression"
            and self.causal
            and self.base_skill == DEFAULT_BASE_SKILL
            and self.data_skills is None
        )

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

    def optional_steps(self) -> list[str]:
        """The steps that run only when the researcher chooses them (``optional = true``)."""
        return [s.name for s in self.steps if s.optional]

    def chosen(self, stages: Iterable[str] | None) -> PipelineSpec:
        """This template as a run follows it: optional steps the researcher did not choose left out."""
        picked = set(stages or ())
        if not any(s.optional and s.name not in picked for s in self.steps):
            return self
        return replace(self, steps=tuple(s for s in self.steps if not s.optional or s.name in picked))


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
        "label",
        "optional",
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
        misplaced = unknown & {
            "name",
            "description",
            "methodologies",
            "finalize",
            "steps",
            "results",
            "causal",
            "base_skill",
            "data_skills",
            "review_weights",
        }
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
        for share in (
            "max_overlap_share",
            "minor_rel_tolerance",
            "max_isolated_share",
            "max_missing_refs_share",
            "max_missing_share",
            "error_tolerance",
        ):
            if share in settings and float(settings[share]) > 1:
                _fail(source, f"{where} ({name}): {share} is a share between 0 and 1")

    optional = raw.get("optional", False)
    if not isinstance(optional, bool):
        _fail(source, f"{where} ({name}): optional must be true or false, not {optional!r}")
    if optional and kind not in RESEARCHER_KINDS:
        _fail(source, f"{where} ({name}): only researcher and preregister steps can be optional")

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
        label=str(raw.get("label", "") or ""),
        optional=optional,
    )


def spec_from_dict(data: dict[str, Any], *, source: Path | str = "<dict>") -> PipelineSpec:
    """Build and validate a spec from parsed TOML."""
    unknown = set(data) - {
        "name",
        "title",
        "description",
        "methodologies",
        "steps",
        "finalize",
        "skills",
        "sidecars",
        "credit",
        "results",
        "causal",
        "base_skill",
        "data_skills",
        "review_weights",
    }
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

    results, causal = _results(data, source)
    _check_panel(steps, source)

    return PipelineSpec(
        name=name,
        description=data.get("description", ""),
        title=str(data.get("title", "") or ""),
        methodologies=tuple(data.get("methodologies", ()) or ()),
        steps=steps,
        finalize=finalize,
        source=Path(source) if isinstance(source, Path) else None,
        skills=_components(data.get("skills"), "skills", source),
        sidecars=_components(data.get("sidecars"), "sidecars", source),
        credit=_credit(data.get("credit"), source),
        results=results,
        causal=causal,
        base_skill=_base_skill(data.get("base_skill"), source),
        data_skills=_data_skills(data.get("data_skills"), source),
        review_weights=_review_weights(data.get("review_weights"), steps, source),
    )


def _results(data: dict[str, Any], source: Path | str) -> tuple[str, bool]:
    """``results`` (the kind of results) and ``causal``, checked; causal follows the kind unless stated."""
    from .result_kinds import DEFAULT_KIND, KINDS

    results = data.get("results", DEFAULT_KIND)
    if not isinstance(results, str) or results not in KINDS:
        _fail(source, f"results must be one of {', '.join(KINDS)}, not {results!r}")
    causal = data.get("causal", KINDS[results].causal_by_default)
    if not isinstance(causal, bool):
        _fail(source, f"causal must be true or false, not {causal!r}")
    return results, causal


def _base_skill(raw: Any, source: Path | str) -> str:
    if raw is None:
        return DEFAULT_BASE_SKILL
    from ...skills.loader import skill_exists

    if not isinstance(raw, str) or not skill_exists(raw):
        _fail(source, f"base_skill: no skill {raw!r} (a path under skills/files, without .md)")
    return str(raw)


def _data_skills(raw: Any, source: Path | str) -> tuple[str, ...] | None:
    if raw is None:
        return None
    from ...skills.loader import skill_exists

    if not isinstance(raw, list) or not all(isinstance(i, str) and i for i in raw):
        _fail(source, "data_skills must be a list of skill names")
    for item in raw:
        if not skill_exists(item):
            _fail(source, f"data_skills: no skill {item!r} (a path under skills/files, without .md)")
    return tuple(dict.fromkeys(raw))


def _check_panel(steps: tuple[StepSpec, ...], source: Path | str) -> None:
    """An `aggregate` step runs reviewers only: a name that is not one would never be scored."""
    from ..specialists.registry import ALL_REVIEWERS

    for s in steps:
        if s.kind != "aggregate":
            continue
        unknown = [r for r in s.run if r not in ALL_REVIEWERS]
        if unknown:
            _fail(
                source,
                f"step {s.name!r}: {', '.join(unknown)} is not a reviewer (reviewers: {', '.join(ALL_REVIEWERS)})",
            )


def _review_weights(raw: Any, steps: tuple[StepSpec, ...], source: Path | str) -> dict[str, float]:
    """``review_weights``: reviewer -> its weight in the combined score; only reviewers of the panel."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        _fail(source, "review_weights must be a table of reviewer = weight")
    panel = {r for s in steps if s.kind == "aggregate" for r in s.run}
    out: dict[str, float] = {}
    for reviewer, weight in raw.items():
        if reviewer not in panel:
            _fail(source, f"review_weights: {reviewer!r} is not a reviewer of this template's panel")
        if isinstance(weight, bool) or not isinstance(weight, int | float) or not weight > 0:
            _fail(source, f"review_weights: {reviewer} must be a positive number, not {weight!r}")
        out[reviewer] = float(weight)
    return out


#: What every `[[credit]]` entry names: who, what they contributed, and where it is.
CREDIT_REQUIRED = ("creator", "role", "relation", "title", "url", "accessed")
CREDIT_RELATIONS = ("based_on", "related_work", "cites")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _credit(raw: Any, source: Path | str) -> tuple[dict[str, Any], ...]:
    """`[[credit]]`: the work a template is based on, with its creator and where it was found.

    Checked at load, so a template cannot carry a credit line without the address
    and the date it was read.
    """
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(c, dict) for c in raw):
        _fail(source, "[[credit]] must be a list of tables")
    for i, c in enumerate(raw, start=1):
        missing = [k for k in CREDIT_REQUIRED if not str(c.get(k) or "").strip()]
        if missing:
            _fail(source, f"credit {i} has no {', '.join(missing)}")
        if c["relation"] not in CREDIT_RELATIONS:
            _fail(source, f"credit {i}: relation must be one of {', '.join(CREDIT_RELATIONS)}")
        if not str(c["url"]).startswith("https://"):
            _fail(source, f"credit {i}: url must be an https:// address")
        for key in ("published", "accessed"):
            if key in c and not _DATE_RE.match(str(c[key])):
                _fail(source, f"credit {i}: {key} must be a date YYYY-MM-DD")
    return tuple(dict(c) for c in raw)


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
