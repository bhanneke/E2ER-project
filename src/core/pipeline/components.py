"""Skills and sidecar files a template adds to a specialist.

Which skills a specialist reads and which files it writes are global
(``specialists/registry.py``). A template may add to both for its own runs:

    [skills]
    identification_strategist = ["econometrics/event-study"]

    [sidecars]
    identification_strategist = ["event_design.json"]

The additions are merged after the registry's own entries, never instead of
them, so a template can extend a specialist but not strip what the pipeline's
checks rely on. What a template may change is named, and each change comes with
the check it answers to (0.16.0): ``base_skill`` (the persona), ``data_skills``
(the domain data skills), ``results`` (the analysis specialist's schema skill,
checked by the contract of that kind) and ``causal`` (whether the
identification strategist's specification file is required).

The runner makes its template the active one for the length of
the run; the skill loader and the dispatcher read it from here. What was merged
is recorded in the study's description and dossier (``research_object.py``).
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .spec import PipelineSpec

_ACTIVE: ContextVar[PipelineSpec | None] = ContextVar("e2er_active_template", default=None)
#: The step of the active template that is running (the runner sets it as each step starts).
_STEP: ContextVar[str | None] = ContextVar("e2er_active_step", default=None)


def activate(spec: PipelineSpec | None) -> Token:
    """Make ``spec`` the template of the current run (and the tasks it starts)."""
    return _ACTIVE.set(spec)


def deactivate(token: Token) -> None:
    _ACTIVE.reset(token)


def active() -> PipelineSpec | None:
    return _ACTIVE.get()


def _merged(base: list[str], extra: tuple[str, ...]) -> list[str]:
    return list(dict.fromkeys([*base, *extra]))


#: The skills of the analysis specialist that belong to the regression contract.
_REGRESSION_ANALYSIS_SKILLS = frozenset(
    {
        "econometrics/iv-estimation",
        "econometrics/did",
        "econometrics/panel-data",
        "econometrics/event-study",
        "econometrics/estimation-results-schema",
    }
)
#: Specialists whose skills include the domain data skills a template may replace.
_DATA_SKILL_SPECIALISTS = frozenset({"data_architect", "data_analyst", "polish_institutions"})


def _core_skills(specialist: str, spec: PipelineSpec) -> list[str]:
    """The registry's skills for ``specialist`` as the template's core settings change them.

    * ``base_skill``: read in place of ``base/economist``;
    * ``data_skills``: the domain data skills (blockchain, DeFi, Allium) of the
      data specialists are replaced by the template's list;
    * ``results``: the analysis specialist reads the schema and method skills
      of the template's kind of results instead of the regression ones;
    * ``causal = false``: the identification strategist no longer reads the
      schema of identification_spec.json (the file is not required).
    """
    from ..specialists.registry import DOMAIN_DATA_SKILLS, SPECIALIST_SKILLS
    from .result_kinds import get
    from .spec import DEFAULT_BASE_SKILL

    skills = list(SPECIALIST_SKILLS.get(specialist, []))
    if spec.base_skill != DEFAULT_BASE_SKILL:
        skills = [spec.base_skill if s == DEFAULT_BASE_SKILL else s for s in skills]
    if spec.data_skills is not None and specialist in _DATA_SKILL_SPECIALISTS:
        skills = [s for s in skills if s not in DOMAIN_DATA_SKILLS] + list(spec.data_skills)
    if specialist == "econometrics_specialist" and spec.results != "regression":
        kind = get(spec.results)
        skills = [s for s in skills if s not in _REGRESSION_ANALYSIS_SKILLS] + [*kind.method_skills, kind.schema_skill]
    if specialist == "identification_strategist" and not spec.causal:
        skills = [s for s in skills if s != "causal-inference/identification-spec-schema"]
    return skills


def skills_for(specialist: str, spec: PipelineSpec | None = None) -> list[str]:
    """The registry's skills for ``specialist`` (as the template's core settings change them),
    then the template's own, once each."""
    from ..specialists.registry import SPECIALIST_SKILLS

    spec = spec if spec is not None else active()
    if spec is None:
        return _merged(SPECIALIST_SKILLS.get(specialist, []), ())
    return _merged(_core_skills(specialist, spec), spec.skills.get(specialist, ()))


def sidecars_for(specialist: str, spec: PipelineSpec | None = None) -> list[str]:
    """The registry's sidecar files for ``specialist`` plus the template's."""
    from ..specialists.registry import SPECIALIST_SIDECAR_ARTIFACTS

    spec = spec if spec is not None else active()
    extra = spec.sidecars.get(specialist, ()) if spec is not None else ()
    base = SPECIALIST_SIDECAR_ARTIFACTS.get(specialist, [])
    if spec is not None and not spec.causal:
        base = [f for f in base if f not in _CAUSAL_SIDECARS]
    return _merged(base, extra)


#: Sidecars that only a causal template requires.
_CAUSAL_SIDECARS = frozenset({"identification_spec.json"})


def optional_sidecars(specialist: str, spec: PipelineSpec | None = None) -> frozenset[str]:
    """Sidecars of ``specialist`` the contract check does not require: the registry's, and in a
    template that makes no causal claim, the identification specification."""
    from ..specialists.registry import SPECIALIST_OPTIONAL_SIDECARS

    spec = spec if spec is not None else active()
    optional = SPECIALIST_OPTIONAL_SIDECARS.get(specialist, frozenset())
    if spec is not None and not spec.causal:
        optional = optional | _CAUSAL_SIDECARS
    return optional


#: Minutes a call of these specialists gets at least, unless the template or step says otherwise:
#: they load data, and a load of texts or a slow catalogue takes long (the 2026-10-14 text-analysis
#: demo: the data analyst's third attempt ran into the 1,800 s limit while loading Gutenberg texts).
DEFAULT_TIMEOUT_MINUTES: dict[str, int] = {"data_analyst": 60}


def enter_step(name: str | None) -> None:
    """The runner starts the step ``name`` (its ``timeout_minutes`` applies to what it dispatches)."""
    _STEP.set(name)


def timeout_for(specialist: str, spec: PipelineSpec | None = None) -> tuple[int, bool] | None:
    """The time limit of one call of ``specialist``, as ``(seconds, at_least)`` (see cli_support.call_timeout).

    The template's ``[timeouts]`` entry for the specialist, else the running step's
    ``timeout_minutes``, else the built-in minimum for data-loading specialists (the
    backend's own setting wins when longer), else None (the backend's setting).
    """
    spec = spec if spec is not None else active()
    if spec is not None:
        if specialist in spec.timeouts:
            return spec.timeouts[specialist] * 60, False
        name = _STEP.get()
        step = spec.step(name) if name else None
        if step is not None and step.timeout_minutes:
            return step.timeout_minutes * 60, False
    if specialist in DEFAULT_TIMEOUT_MINUTES:
        return DEFAULT_TIMEOUT_MINUTES[specialist] * 60, True
    return None
