"""Render tables and figures as one step, and refuse to pretend it worked.

Four call sites in the runner repeated the same sequence: render tables, stub
any dangling ``\\input``, render figures, stub any missing figure. Each step
logged a warning on failure and continued, so a paper could reach the reviewers
with every table replaced by ``---`` and nobody stopped.

That is the failure the 2026-08-05 validation cell shipped. The estimation
script crashed, ``estimation_results.json`` was ``{}``, all three table_spec
references failed to resolve, the renderer emitted three tables of ``---`` —
and the drafter quietly wrote four tables of its own with invented numbers,
under the same labels. The rendered files were never referenced.

So the placeholders stay (a compiled PDF is a useful audit artifact even when
incomplete) but they are no longer silent: unresolved table references and
dangling table ``\\input``s are RELIABILITY failures and halt the run.

Figures are treated as a warning rather than a halt. A missing figure is
cosmetic; a missing table is a hole where numbers should be, and holes where
numbers should be are what the drafter fills in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ...logging_config import get_logger

logger = get_logger(__name__)


class RenderIncompleteError(RuntimeError):
    """Tables could not be produced from the analysis outputs."""


@dataclass
class RenderCompleteness:
    """What the render pass could not do."""

    unresolved: list[str] = field(default_factory=list)  # table_spec refs that found no key
    table_stubs: list[str] = field(default_factory=list)  # dangling \input stubbed out
    figure_stubs: list[str] = field(default_factory=list)  # missing figures placeholdered
    errors: list[str] = field(default_factory=list)  # per-table render failures

    @property
    def tables_ok(self) -> bool:
        return not (self.unresolved or self.table_stubs or self.errors)

    def summary(self) -> str:
        parts = []
        if self.unresolved:
            parts.append(f"{len(self.unresolved)} unresolved table reference(s): {', '.join(self.unresolved[:6])}")
        if self.table_stubs:
            parts.append(f"{len(self.table_stubs)} dangling table input(s): {', '.join(self.table_stubs[:6])}")
        if self.errors:
            parts.append(f"{len(self.errors)} render error(s): {'; '.join(self.errors[:3])}")
        return "; ".join(parts)


def render_all(workspace: Path) -> RenderCompleteness:
    """Render tables and figures. Reports what is missing; does not raise."""
    from .figures import ensure_figure_placeholders, render_figures
    from .tables import ensure_input_stubs, render_tables

    treport = render_tables(workspace)
    table_stubs = ensure_input_stubs(workspace)
    render_figures(workspace)
    figure_stubs = ensure_figure_placeholders(workspace)

    completeness = RenderCompleteness(
        unresolved=[f"{u.table}:{u.ref}" for u in treport.unresolved],
        table_stubs=list(table_stubs),
        figure_stubs=list(figure_stubs),
        errors=list(treport.errors),
    )
    if completeness.figure_stubs:
        logger.warning("render: %d figure(s) placeholdered", len(completeness.figure_stubs))
    return completeness


def render_all_or_halt(workspace: Path) -> RenderCompleteness:
    """Render, and raise ``RenderIncompleteError`` if any table could not be built.

    Use on the paths that lead to a draft. A table the renderer could not fill
    is a hole the drafter will fill instead.
    """
    completeness = render_all(workspace)
    if not completeness.tables_ok:
        raise RenderIncompleteError(
            f"tables could not be rendered from the analysis outputs — {completeness.summary()}. "
            "The analysis JSON is missing the keys table_spec.json asks for; "
            "drafting over this produces hand-written numbers."
        )
    return completeness
