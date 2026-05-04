"""Skills loader — reads skill markdown files and injects into specialist prompts."""
from __future__ import annotations

from pathlib import Path

_SKILLS_DIR = Path(__file__).parent / "files"

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
    "writing_reviewer": ["anti-slop"],
    "data_reviewer": ["cleaning"],
    "identification_reviewer": ["sensitivity", "technical-review"],
    "self_attacker": ["referee-simulation", "argument-audit", "sensitivity"],
    "polish_formula": ["econ-model", "optimization-verification"],
    "polish_numerics": ["cleaning", "consistency-check"],
    "polish_institutions": ["economist", "crypto-defi"],
    "polish_bibliography": ["bibtex", "context-builder"],
    "polish_equilibria": ["game-theory", "proof-strategies"],
    "revisor": ["paper-structure", "personal-style", "anti-slop"],
    "replication_packager": ["cleaning", "researcher"],
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
    """Try to load a skill file by name, searching all subdirectories."""
    if not _SKILLS_DIR.exists():
        return ""
    for path in _SKILLS_DIR.rglob(f"{name}.md"):
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            pass
    return ""


def list_available_skills() -> list[str]:
    if not _SKILLS_DIR.exists():
        return []
    return [p.stem for p in _SKILLS_DIR.rglob("*.md")]
