"""Skills and sidecar files a template adds to a specialist.

Which skills a specialist reads and which files it writes are global
(``specialists/registry.py``). A template may add to both for its own runs:

    [skills]
    identification_strategist = ["econometrics/event-study"]

    [sidecars]
    identification_strategist = ["event_design.json"]

The additions are merged after the registry's own entries, never instead of
them, so a template can extend a specialist but not strip what the pipeline's
checks rely on. The runner makes its template the active one for the length of
the run; the skill loader and the dispatcher read it from here. What was merged
is recorded in the study's description and dossier (``research_object.py``).
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .spec import PipelineSpec

_ACTIVE: ContextVar[PipelineSpec | None] = ContextVar("e2er_active_template", default=None)


def activate(spec: PipelineSpec | None) -> Token:
    """Make ``spec`` the template of the current run (and the tasks it starts)."""
    return _ACTIVE.set(spec)


def deactivate(token: Token) -> None:
    _ACTIVE.reset(token)


def active() -> PipelineSpec | None:
    return _ACTIVE.get()


def _merged(base: list[str], extra: tuple[str, ...]) -> list[str]:
    return list(dict.fromkeys([*base, *extra]))


def skills_for(specialist: str, spec: PipelineSpec | None = None) -> list[str]:
    """The registry's skills for ``specialist`` plus the template's, in that order, once each."""
    from ..specialists.registry import SPECIALIST_SKILLS

    spec = spec if spec is not None else active()
    extra = spec.skills.get(specialist, ()) if spec is not None else ()
    return _merged(SPECIALIST_SKILLS.get(specialist, []), extra)


def sidecars_for(specialist: str, spec: PipelineSpec | None = None) -> list[str]:
    """The registry's sidecar files for ``specialist`` plus the template's."""
    from ..specialists.registry import SPECIALIST_SIDECAR_ARTIFACTS

    spec = spec if spec is not None else active()
    extra = spec.sidecars.get(specialist, ()) if spec is not None else ()
    return _merged(SPECIALIST_SIDECAR_ARTIFACTS.get(specialist, []), extra)
