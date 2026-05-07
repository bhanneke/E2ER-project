"""Tiered context builders — deliver proportional context to each specialist."""

from __future__ import annotations

from pathlib import Path


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
        f"Methodology: {data.get('methodology', 'empirical')}",
        f"Data Available: {', '.join(data.get('datasets', []))}",
        f"Current Stage: {data.get('current_stage', 'unknown')}",
    ]
    return "\n".join(lines)


def build_tier1_context(workspace: Path, paper_id: str) -> str:
    """Tier 1 — standard context: paper plan + latest draft + key findings."""
    tier0 = build_tier0_context(workspace, paper_id)
    sections = [tier0, ""]

    user_data = _list_user_data(workspace)
    if user_data:
        sections.append(
            "## Researcher-Provided Data Files (workspace/data/)\n"
            "Use the read_file tool to load any of these. Do NOT try to query Allium "
            "for these — they are supplied directly by the researcher.\n\n" + user_data
        )

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

    for fname in [
        "literature_review.md",
        "data_summary.md",
        "identification_strategy.md",
        "contributions.json",
        "econometric_spec.md",
    ]:
        content = _read_artifact(workspace, fname)
        if content:
            label = fname.replace("_", " ").replace(".md", "").replace(".json", "").title()
            sections.append(f"## {label}\n" + _truncate(content, 2000))

    return "\n\n".join(s for s in sections if s)


def build_review_context(workspace: Path, paper_id: str) -> str:
    """Full paper context for the review stage.

    Pre-loads the paper draft + key supporting artifacts at FULL size so the
    reviewer doesn't need to make any read_file tool calls. Each tool call
    re-sends the result on every subsequent turn, so eliminating those reads
    cuts review-phase token usage by ~5x in practice.

    Returns the assembled context block. The caller (dispatcher._inject_context)
    routes pure-text reviewer specialists here.
    """
    draft = _read_artifact(workspace, "paper_draft.tex") or _read_artifact(workspace, "paper_draft.md")
    if not draft:
        # No draft yet — fall back so reviewers can at least see whatever
        # design artifacts exist.
        return build_tier2_context(workspace, paper_id)

    header = build_tier0_context(workspace, paper_id)
    sections = [header, f"## Full Paper Draft\n{draft}"]

    # Supporting documents loaded at full size so the reviewer doesn't need to
    # re-read them via read_file. Keep this list in sync with the docs that
    # reviewer skill files actually reference.
    for fname, label in [
        ("identification_strategy.md", "Identification Strategy"),
        ("econometric_spec.md", "Econometric Specification"),
        ("literature_review.md", "Literature Review"),
        ("data_dictionary.json", "Data Dictionary"),
        ("data_summary.md", "Data Summary"),
        ("paper_plan.md", "Paper Plan"),
    ]:
        content = _read_artifact(workspace, fname)
        if content:
            sections.append(f"## {label}\n{content}")

    return "\n\n".join(sections)


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


def _list_user_data(workspace: Path) -> str:
    """List files under workspace/data/ with a short preview for csv/jsonl files."""
    data_dir = workspace / "data"
    if not data_dir.exists():
        return ""
    files = sorted(p for p in data_dir.iterdir() if p.is_file())
    if not files:
        return ""

    lines: list[str] = []
    for path in files:
        size_kb = path.stat().st_size / 1024
        line = f"- `data/{path.name}` ({size_kb:.1f} KB)"
        # First 5 non-empty lines for readable text formats.
        if path.suffix.lower() in {".csv", ".tsv", ".jsonl", ".txt"}:
            try:
                with path.open("r", encoding="utf-8", errors="replace") as f:
                    head = []
                    for raw in f:
                        s = raw.rstrip("\n")
                        if s.strip():
                            head.append(s)
                        if len(head) >= 5:
                            break
                if head:
                    preview = "\n    ".join(h[:200] for h in head)
                    line += f"\n    {preview}"
            except Exception:
                pass
        lines.append(line)
    return "\n".join(lines)


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
