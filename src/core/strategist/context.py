"""Tiered context builders — deliver proportional context to each specialist."""
from __future__ import annotations

from pathlib import Path
from typing import Any


def build_tier0_context(workspace: Path, paper_id: str) -> str:
    """Tier 0 — minimal orientation: paper title, research question, data available."""
    manifest = _read_artifact(workspace, "manifest.json")
    if not manifest:
        return f"Paper ID: {paper_id}\nWorkspace: {workspace}"
    import json
    data = json.loads(manifest)
    lines = [
        f"Paper: {data.get('title', 'Untitled')}",
        f"ID: {paper_id}",
        f"Research Question: {data.get('research_question', 'TBD')}",
        f"Data Available: {', '.join(data.get('datasets', []))}",
        f"Current Stage: {data.get('current_stage', 'unknown')}",
    ]
    return "\n".join(lines)


def build_tier1_context(workspace: Path, paper_id: str) -> str:
    """Tier 1 — standard context: paper plan + latest draft + key findings."""
    tier0 = build_tier0_context(workspace, paper_id)
    sections = [tier0, ""]

    paper_plan = _read_artifact(workspace, "paper_plan.md")
    if paper_plan:
        sections.append("## Paper Plan\n" + _truncate(paper_plan, 3000))

    key_findings = _read_artifact(workspace, "key_findings.md")
    if key_findings:
        sections.append("## Key Findings\n" + _truncate(key_findings, 2000))

    draft = _read_artifact(workspace, "paper_draft.tex") or _read_artifact(workspace, "paper_draft.md")
    if draft:
        sections.append("## Current Draft (excerpt)\n" + _truncate(draft, 4000))

    return "\n\n".join(s for s in sections if s)


def build_tier2_context(workspace: Path, paper_id: str) -> str:
    """Tier 2 — deep context: everything from Tier 1 + lit review + data summary + contributions."""
    tier1 = build_tier1_context(workspace, paper_id)
    sections = [tier1, ""]

    for fname in ["literature_review.md", "data_summary.md", "identification_strategy.md",
                  "contributions.json", "econometric_spec.md"]:
        content = _read_artifact(workspace, fname)
        if content:
            label = fname.replace("_", " ").replace(".md", "").replace(".json", "").title()
            sections.append(f"## {label}\n" + _truncate(content, 2000))

    return "\n\n".join(s for s in sections if s)


def build_review_context(workspace: Path, paper_id: str) -> str:
    """Full paper context for review stage — includes everything."""
    draft = _read_artifact(workspace, "paper_draft.tex") or _read_artifact(workspace, "paper_draft.md")
    if not draft:
        return build_tier2_context(workspace, paper_id)

    header = build_tier0_context(workspace, paper_id)
    return f"{header}\n\n## Full Paper Draft\n{draft}"


def build_self_attack_context(workspace: Path, paper_id: str) -> str:
    """Context for the self-attack adversarial phase."""
    draft = _read_artifact(workspace, "paper_draft.tex") or _read_artifact(workspace, "paper_draft.md")
    identification = _read_artifact(workspace, "identification_strategy.md")
    econometrics = _read_artifact(workspace, "econometric_spec.md")

    sections = []
    if draft:
        sections.append(f"## Paper Draft\n{_truncate(draft, 6000)}")
    if identification:
        sections.append(f"## Identification Strategy\n{_truncate(identification, 2000)}")
    if econometrics:
        sections.append(f"## Econometric Specification\n{_truncate(econometrics, 2000)}")
    return "\n\n".join(sections)


def _read_artifact(workspace: Path, filename: str) -> str | None:
    path = workspace / filename
    if path.exists():
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            pass
    return None


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n\n[...truncated at {max_chars} chars]"
