"""The name is written lowercase, "e2er", in all visible text.

Checked: the CLI help of every command, the dashboard templates, README.md
and docs/*.md. Allowed: the repository name "E2ER-project", environment
variables (E2ER_*), paths of the old repository ("E2ER/src/..."), and the
published title "E2ER: End-to-End Researcher" in citation metadata.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPPER = re.compile(r"E2ER(?![-_/A-Za-z0-9])")
PUBLISHED_TITLE = re.compile(r"E2ER: End-to-End Researcher")


def _hits(text: str) -> list[str]:
    text = PUBLISHED_TITLE.sub("", text)
    return [text[max(0, m.start() - 40) : m.end() + 40].replace("\n", " ") for m in UPPER.finditer(text)]


def _help(*args: str) -> str:
    out = subprocess.run([sys.executable, "-m", "src", *args, "--help"], cwd=ROOT, capture_output=True, text=True)
    return out.stdout + out.stderr


def _subcommands() -> list[str]:
    m = re.search(r"\{([a-z0-9,-]+)\}", _help())
    return m.group(1).split(",") if m else []


def test_cli_help_writes_e2er_lowercase():
    hits = {"(main)": _hits(_help())}
    for cmd in _subcommands():
        hits[cmd] = _hits(_help(cmd))
    assert not {k: v for k, v in hits.items() if v}, hits


def test_dashboard_templates_write_e2er_lowercase():
    hits = {p.name: _hits(p.read_text(encoding="utf-8")) for p in (ROOT / "src" / "api" / "templates").glob("*.html")}
    assert not {k: v for k, v in hits.items() if v}, hits


def test_readme_and_docs_write_e2er_lowercase():
    files = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
    hits = {p.name: _hits(p.read_text(encoding="utf-8")) for p in files}
    assert not {k: v for k, v in hits.items() if v}, hits
