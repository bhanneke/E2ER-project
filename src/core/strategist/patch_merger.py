"""Patch-file merger for the `patch_revisor` specialist (v0.6 step 2).

The `patch_revisor` writes structured edits to
`paper_draft.tex.edits.json` rather than rewriting the whole
`paper_draft.tex`. This module reads that patch file, validates
each edit's `target` against the work order's `Finding` list, and
applies the in-scope edits to the draft.

Why patch file vs. unified diff (decision recorded in
`docs/V0.6_PLAN.md`): LLMs produce JSON reliably; unified diffs
poorly (line drift, whitespace-sensitive context matching). Per-
edit failures here are debuggable in human terms ("edit targeting
`section:robustness` could not find text X — closest matches: Y")
rather than opaque `hunk #2 FAILED`. The merger emits a unified
diff as a side artifact (`paper_draft.tex.applied.diff`) for
review tooling, getting back the audit benefit.

Scope enforcement is mechanical: the merger refuses any edit
whose `target` isn't in the Finding list passed to the run. This
is the patch-file format's equivalent of unified-diff's
scope-enforcement-by-construction.

Step 2 supports one edit type — `replace_text` — which is general
enough to express table-cell corrections, section-prose edits,
and reference updates. Step 5+ can add `replace_row`,
`insert_after`, `delete_text` as the patch_revisor's vocabulary
expands.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .findings import Finding


@dataclass(frozen=True)
class Edit:
    """One scoped edit emitted by `patch_revisor` into the patch file.

    Fields beyond the schema below are tolerated (and ignored) on
    parse — the patch_revisor may add extra annotations for its own
    bookkeeping without breaking the merger.
    """

    target: str
    edit_type: str
    find: str = ""
    replace: str = ""
    find_must_be_unique: bool = True
    source_finding: str = ""  # provenance: "verify_numbers#0", "review:technical#0"
    edit_id: str = ""


@dataclass
class EditResult:
    """Outcome of attempting a single edit."""

    edit: Edit
    success: bool
    error: str = ""
    matches: int = 0  # how many times `find` matched in the target region


@dataclass
class MergeResult:
    """Full outcome of applying a patch file."""

    original_text: str
    patched_text: str
    applied: list[EditResult] = field(default_factory=list)
    failed: list[EditResult] = field(default_factory=list)
    diff: str = ""

    @property
    def fully_applied(self) -> bool:
        return not self.failed

    @property
    def n_applied(self) -> int:
        return len(self.applied)

    @property
    def n_failed(self) -> int:
        return len(self.failed)


# ---------------------------------------------------------------------------
# Patch file parsing
# ---------------------------------------------------------------------------


def parse_patch_file(path: Path) -> list[Edit]:
    """Parse `paper_draft.tex.edits.json` into a list of `Edit`.

    The patch file is a top-level JSON list of edit objects. Each
    object has at minimum `target` and `edit_type`; the other
    fields depend on the edit type. Unknown fields are tolerated.
    Empty list = "no edits to apply" (valid). Malformed JSON
    raises.
    """
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError(f"patch file must be a top-level JSON list (got {type(data).__name__})")
    edits: list[Edit] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"patch file entry {i}: must be an object")
        edits.append(
            Edit(
                target=str(item.get("target", "")),
                edit_type=str(item.get("edit_type", "replace_text")),
                find=str(item.get("find", "")),
                replace=str(item.get("replace", "")),
                find_must_be_unique=bool(item.get("find_must_be_unique", True)),
                source_finding=str(item.get("source_finding", "")),
                edit_id=str(item.get("id", f"e{i}")),
            )
        )
    return edits


# ---------------------------------------------------------------------------
# Target scope enforcement
# ---------------------------------------------------------------------------


def validate_targets(edits: list[Edit], findings: list[Finding]) -> tuple[list[Edit], list[EditResult]]:
    """Split edits into (in-scope, out-of-scope) based on the findings list.

    An edit is in-scope if any of:
      - its `target` is in the set of finding targets, OR
      - any finding has `target == "paper:full"` (whole-paper scope
        widens to everything).

    Out-of-scope edits are returned as pre-failed `EditResult`s so
    the merger can report exactly which edits were rejected and why.
    This is the scope-enforcement invariant: the merger refuses any
    edit whose target isn't motivated by a recorded Finding. v0.6
    invariant test pins it.
    """
    finding_targets = {f.target for f in findings}
    has_paper_full = "paper:full" in finding_targets

    in_scope: list[Edit] = []
    out_of_scope: list[EditResult] = []
    for edit in edits:
        if has_paper_full or edit.target in finding_targets:
            in_scope.append(edit)
        else:
            out_of_scope.append(
                EditResult(
                    edit=edit,
                    success=False,
                    error=(f"target {edit.target!r} not in work order findings: {sorted(finding_targets) or 'none'}"),
                )
            )
    return in_scope, out_of_scope


# ---------------------------------------------------------------------------
# Region extraction (find the slice of the draft each target points to)
# ---------------------------------------------------------------------------


def _extract_section(text: str, name: str) -> tuple[int, int]:
    """Find the (start, end) char span of a named section.

    `name` is the canonical token after `section:` in the target
    (e.g. `identification`, `institutional_context`). Matching is
    case-insensitive and tolerates the LaTeX section being more
    verbose: `section:identification` matches both
    `\\section{Identification}` and `\\section{4. Identification Strategy}`.

    Returns (-1, -1) when no section matches.
    """
    name_normalized = name.replace("_", " ").lower().strip()
    if not name_normalized:
        return (-1, -1)

    pattern = re.compile(r"\\section\{([^}]+)\}")
    sections: list[tuple[int, str]] = [(m.start(), m.group(1)) for m in pattern.finditer(text)]
    if not sections:
        return (-1, -1)

    chosen_idx = -1
    for i, (_, title) in enumerate(sections):
        if name_normalized in title.lower():
            chosen_idx = i
            break
    if chosen_idx == -1:
        return (-1, -1)

    start = sections[chosen_idx][0]
    if chosen_idx + 1 < len(sections):
        end = sections[chosen_idx + 1][0]
    else:
        # Last section — end at \end{document} or EOF.
        end_match = re.search(r"\\end\{document\}", text[start:])
        end = (end_match.start() + start) if end_match else len(text)
    return (start, end)


def _extract_table(text: str, label: str) -> tuple[int, int]:
    """Find the tabular env identified by `label`.

    Two label forms are supported (matching what
    `findings._table_target_from_context` emits):
      - `tab:<name>` — find `\\label{tab:<name>}`, then the
        tabular env that follows it within the same float/group.
      - `Table_<N>` — fallback for unlabelled tables; takes the
        N-th `\\begin{tabular}` in the document (1-indexed).

    Returns (-1, -1) when no match.
    """
    if label.startswith("tab:"):
        label_match = re.search(re.escape(f"\\label{{{label}}}"), text)
        if not label_match:
            return (-1, -1)
        # Find the tabular env after the label. In practice the label
        # appears inside the \begin{table}...\end{table} float just
        # before the tabular, OR inside the tabular caption. Search
        # both forward and backward for the closest \begin{tabular}.
        forward = text.find(r"\begin{tabular}", label_match.end())
        backward = text.rfind(r"\begin{tabular}", 0, label_match.start())
        # Prefer whichever is closer (within ~500 chars).
        candidates = [c for c in (forward, backward) if c != -1]
        if not candidates:
            return (-1, -1)
        tab_start = min(candidates, key=lambda c: abs(c - label_match.start()))
        end_match = re.search(r"\\end\{tabular\}", text[tab_start:])
        if not end_match:
            return (-1, -1)
        return (tab_start, tab_start + end_match.end())

    if label.startswith("Table_"):
        try:
            n = int(label[len("Table_") :])
        except ValueError:
            return (-1, -1)
        starts = [m.start() for m in re.finditer(r"\\begin\{tabular\}", text)]
        if len(starts) < n or n < 1:
            return (-1, -1)
        tab_start = starts[n - 1]
        end_match = re.search(r"\\end\{tabular\}", text[tab_start:])
        if not end_match:
            return (-1, -1)
        return (tab_start, tab_start + end_match.end())

    return (-1, -1)


def _extract_abstract(text: str) -> tuple[int, int]:
    begin = re.search(r"\\begin\{abstract\}", text)
    end = re.search(r"\\end\{abstract\}", text)
    if begin and end and end.start() > begin.start():
        return (begin.start(), end.end())
    return (-1, -1)


def _extract_references(text: str) -> tuple[int, int]:
    """Locate the `\\bibliography{...}` command's line span.

    Returns the whole line containing `\\bibliography{...}`. The
    actual `references.bib` file is edited out-of-band by other
    tooling; the merger only modifies in-paper-text references.
    """
    m = re.search(r"\\bibliography\{[^}]+\}", text)
    if not m:
        return (-1, -1)
    line_start = text.rfind("\n", 0, m.start()) + 1
    line_end_idx = text.find("\n", m.end())
    line_end = line_end_idx if line_end_idx != -1 else len(text)
    return (line_start, line_end)


def _extract_region(text: str, target: str) -> tuple[int, int]:
    """Resolve a Finding `target` string into a (start, end) char span.

    Returns (-1, -1) when the target cannot be located in `text`.
    """
    if target == "paper:full":
        return (0, len(text))
    if target == "abstract":
        return _extract_abstract(text)
    if target == "references":
        return _extract_references(text)
    if target.startswith("section:"):
        return _extract_section(text, target[len("section:") :])
    if target.startswith("table:"):
        return _extract_table(text, target[len("table:") :])
    return (-1, -1)


# ---------------------------------------------------------------------------
# Edit application
# ---------------------------------------------------------------------------


def apply_edit(text: str, edit: Edit) -> tuple[str, EditResult]:
    """Apply a single edit. Returns (possibly-modified text, result).

    Failure modes (each captured in the EditResult):
      - target region not found in the document
      - find string absent in the target region
      - find_must_be_unique=True and find matched more than once
      - unknown edit_type
    """
    if edit.edit_type != "replace_text":
        return text, EditResult(
            edit=edit,
            success=False,
            error=f"unknown edit_type {edit.edit_type!r}",
        )

    if not edit.find:
        return text, EditResult(edit=edit, success=False, error="replace_text requires non-empty `find`")

    region_start, region_end = _extract_region(text, edit.target)
    if region_start == -1:
        return text, EditResult(
            edit=edit,
            success=False,
            error=f"target region {edit.target!r} not found in document",
        )

    region = text[region_start:region_end]
    matches = region.count(edit.find)
    if matches == 0:
        return text, EditResult(
            edit=edit,
            success=False,
            error=f"find string not found within {edit.target!r}",
            matches=0,
        )
    if edit.find_must_be_unique and matches > 1:
        return text, EditResult(
            edit=edit,
            success=False,
            error=(
                f"find string is ambiguous within {edit.target!r}: "
                f"{matches} matches (set find_must_be_unique=false to "
                f"replace all, or extend the find string to make it unique)"
            ),
            matches=matches,
        )

    count = 1 if edit.find_must_be_unique else -1
    new_region = (
        region.replace(edit.find, edit.replace, count) if count > 0 else region.replace(edit.find, edit.replace)
    )
    new_text = text[:region_start] + new_region + text[region_end:]
    return new_text, EditResult(edit=edit, success=True, matches=matches)


def apply_patch(text: str, edits: list[Edit]) -> MergeResult:
    """Apply a list of edits sequentially to `text`.

    Each edit is attempted independently. A failed edit does not
    halt the run: subsequent edits may target different regions or
    different text and are still worth applying. Failures are
    collected so the runner can re-emit them as new Findings for
    the next revision round.

    The unified diff comparing before vs after is produced
    regardless of pass/fail count.
    """
    original_text = text
    applied: list[EditResult] = []
    failed: list[EditResult] = []
    for edit in edits:
        text, result = apply_edit(text, edit)
        if result.success:
            applied.append(result)
        else:
            failed.append(result)

    diff = "".join(
        difflib.unified_diff(
            original_text.splitlines(keepends=True),
            text.splitlines(keepends=True),
            fromfile="paper_draft.tex (before)",
            tofile="paper_draft.tex (after)",
            n=3,
        )
    )
    return MergeResult(
        original_text=original_text,
        patched_text=text,
        applied=applied,
        failed=failed,
        diff=diff,
    )


# ---------------------------------------------------------------------------
# Top-level workspace entry point
# ---------------------------------------------------------------------------


def merge_patch_file(
    workspace: Path,
    findings: list[Finding],
    *,
    draft_path: Path | None = None,
    patch_path: Path | None = None,
    diff_path: Path | None = None,
    persist: bool = True,
) -> MergeResult:
    """Top-level: read patch file from workspace, apply against the draft.

    Reads `paper_draft.tex.edits.json` + `paper_draft.tex` from
    `workspace`; validates each edit's target against the
    `findings` list; applies in-scope edits; writes the patched
    draft + a unified-diff side artifact.

    When `persist=False`, computes the result without writing
    back — useful for dry-run + test paths.

    Raises:
        FileNotFoundError: when the draft or patch file is missing.
    """
    draft_path = draft_path or (workspace / "paper_draft.tex")
    patch_path = patch_path or (workspace / "paper_draft.tex.edits.json")
    diff_path = diff_path or (workspace / "paper_draft.tex.applied.diff")

    if not draft_path.is_file():
        raise FileNotFoundError(f"draft not found at {draft_path}")
    if not patch_path.is_file():
        raise FileNotFoundError(f"patch file not found at {patch_path}")

    text = draft_path.read_text(encoding="utf-8")
    edits = parse_patch_file(patch_path)
    in_scope, out_of_scope = validate_targets(edits, findings)
    result = apply_patch(text, in_scope)

    # Roll out-of-scope edits into the failure list so the runner sees
    # both kinds of failure in one place.
    result.failed = result.failed + out_of_scope

    if persist:
        draft_path.write_text(result.patched_text, encoding="utf-8")
        diff_path.write_text(result.diff, encoding="utf-8")

    return result
