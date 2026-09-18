"""The .gitignore must never let a credential into the repository.

`!examples/showcase/**` was added to stop .gitignore truncating the showcase
bundle, and ignore rules are last-match-wins — so it switched off every rule in
the file for that path. A scratch repository with that .gitignore staged
examples/showcase/.env, id_rsa and data.db on `git add -A`.

Nothing leaked: no such file was ever committed on any branch, the published
0.9.0 wheel carries none, and a scan of every tracked file finds no
credential-shaped string. But the guard was off, and the next run that left a
.env or a data.db in the workspace would have been committable.

These tests run git against a throwaway repository seeded with the real
.gitignore, so they assert what git actually does rather than what the patterns
look like they do.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GITIGNORE = REPO / ".gitignore"

#: Files that must stay out of the repository wherever they appear — including
#: inside examples/showcase, which carries a blanket re-include.
MUST_BE_IGNORED = [
    ".env",
    ".env.local",
    "examples/showcase/.env",
    "examples/showcase/code/.env",
    "examples/showcase/id_rsa",
    "examples/showcase/data.db",
    "examples/showcase/results/analysis.sqlite",
    "examples/showcase/credentials.json",
]

#: The bundle is an artifact: these have to survive the ignore rules, which is
#: why the re-include exists at all.
MUST_BE_TRACKABLE = [
    "examples/showcase/code/scratch/paper_draft.log",
    "examples/showcase/paper/paper.tex",
    "examples/showcase/provenance.json",
]


@pytest.fixture(scope="module")
def staged(tmp_path_factory) -> set[str]:
    """What `git add -A` stages in a fresh repo using the real .gitignore."""
    work = tmp_path_factory.mktemp("ignore-check")
    (work / ".gitignore").write_text(GITIGNORE.read_text(encoding="utf-8"), encoding="utf-8")

    for rel in MUST_BE_IGNORED + MUST_BE_TRACKABLE:
        path = work / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("SECRET=real\n", encoding="utf-8")

    subprocess.run(["git", "init", "-q", "."], cwd=work, check=True)
    subprocess.run(["git", "add", "-A"], cwd=work, check=True)
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "-z"],
        cwd=work,
        capture_output=True,
        text=True,
        check=True,
    )
    return {p for p in out.stdout.split("\0") if p}


def test_no_credential_file_can_be_staged(staged: set[str]):
    leaked = sorted(set(MUST_BE_IGNORED) & staged)
    assert not leaked, f".gitignore would commit credentials: {leaked}"


def test_the_bundle_is_still_committable(staged: set[str]):
    """The re-include has to keep doing its job; tightening it must not
    re-break the truncated-bundle defect it was added for."""
    missing = sorted(set(MUST_BE_TRACKABLE) - staged)
    assert not missing, f".gitignore would truncate the bundle again: {missing}"


#: Keys whose values would be credentials if they were real.
_SECRET_KEY = ("key", "token", "secret", "password", "passwd", "credential")


def test_dotenv_example_carries_no_real_values():
    """The one .env-shaped file committed on purpose.

    Only credential-bearing keys are checked: LLM_BACKEND=anthropic is a config
    value, and flagging it for being long is the same overreach the numbers
    gate makes when it judges a cell by proximity instead of by its own key.
    """
    text = (REPO / ".env.example").read_text(encoding="utf-8")
    offenders = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if not any(marker in key.lower() for marker in _SECRET_KEY):
            continue
        # Drop a trailing "  # comment" before judging the value.
        value = value.split("#")[0].strip().strip("\"'")
        if len(value) < 12:
            continue  # empty or obviously a stub
        if not any(
            marker in value.lower() for marker in ("your", "xxx", "example", "placeholder", "change", "...", "<")
        ):
            offenders.append(line)

    assert not offenders, f".env.example may contain real credentials: {offenders}"
