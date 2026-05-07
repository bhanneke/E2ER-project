"""Skills loader — reads skill markdown files and injects into specialist prompts."""

from __future__ import annotations

from pathlib import Path

# Search in two locations: src/skills/files/ (installed package) and
# project-root skills/files/ (development checkout, Docker mount).
_SKILLS_DIRS = [
    Path(__file__).parent / "files",
    Path(__file__).parent.parent.parent / "skills" / "files",
]

_SPECIALIST_SKILLS: dict[str, list[str]] = {
    "idea_developer": ["economist", "researcher", "creative-ideation", "novelty"],
    "literature_scanner": ["researcher", "context-builder"],
    "data_architect": ["blockchain", "crypto-defi", "economist"],
    "identification_strategist": ["judge-designs", "natural-experiments", "identification"],
    "econometrics_specialist": ["iv-estimation", "did", "panel-data", "event-study"],
    "data_analyst": ["cleaning", "figure-spec", "panel-data"],
    "paper_drafter": ["paper-structure", "personal-style", "researcher"],
    "section_writer": ["paper-structure", "personal-style", "anti-slop"],
    "abstract_writer": ["abstract", "anti-slop"],
    "latex_formatter": ["econ-model", "tables"],
    "mechanism_reviewer": ["referee-simulation", "market-microstructure"],
    "technical_reviewer": ["technical-review", "consistency-check"],
    "literature_reviewer": ["referee-simulation", "context-builder"],
    "writing_reviewer": ["writing-quality", "anti-slop"],
    "data_reviewer": ["data-quality", "cleaning"],
    "identification_reviewer": ["sensitivity", "technical-review"],
    "self_attacker": ["referee-simulation", "argument-audit", "sensitivity"],
    "polish_formula": ["econ-model", "optimization-verification"],
    "polish_numerics": ["cleaning", "consistency-check"],
    "polish_institutions": ["economist", "crypto-defi"],
    "polish_bibliography": ["bibtex", "context-builder"],
    "polish_equilibria": ["game-theory", "proof-strategies"],
    "revisor": ["paper-structure", "personal-style", "anti-slop"],
    "replication_packager": ["cleaning", "researcher", "replication-package"],
}


def load_skills_for_specialist(specialist: str) -> str:
    """Load and concatenate skill files for a specialist. Returns empty string if none found."""
    skill_names = _SPECIALIST_SKILLS.get(specialist, [])
    parts = []
    for name in skill_names:
        content = _load_skill(name)
        if content:
            parts.append(content)
    return "\n\n---\n\n".join(parts)


def _load_skill(name: str) -> str:
    """Search all skills directories for a skill file by stem name."""
    for skills_dir in _SKILLS_DIRS:
        if not skills_dir.exists():
            continue
        for path in skills_dir.rglob(f"{name}.md"):
            try:
                return path.read_text(encoding="utf-8")
            except Exception:
                pass
    return ""


def list_available_skills() -> list[str]:
    """List all skill file stems found across all search directories."""
    seen: set[str] = set()
    for skills_dir in _SKILLS_DIRS:
        if not skills_dir.exists():
            continue
        for p in skills_dir.rglob("*.md"):
            seen.add(p.stem)
    return sorted(seen)
