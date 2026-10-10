"""The README's factual claims, checked against the code.

The README cites counts: how many skill files, how many specialist roles.
Those are the first thing a reader uses to judge whether the project knows
itself, and they rot silently — nobody updates a number in a README when they
add a file.

Written after nearly shipping "133 skill files" into the opening paragraph. The
figure came from a different repository's CLAUDE.md; the real count is 58. A
wrong number in the first screen is worse than no number.

Tolerant of drift by design: the counts are rounded down to a floor, so adding
skills does not fail the build. Only a claim that has become an overstatement
does.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def test_the_skill_count_is_not_an_overstatement():
    claimed = int(re.search(r"(\d+) skill files", _readme()).group(1))
    actual = len(list((ROOT / "skills" / "files").rglob("*.md")))

    assert claimed <= actual, f"README claims {claimed} skill files; there are {actual}"


def test_the_specialist_count_is_not_an_overstatement():
    from src.core.specialists.registry import SPECIALIST_ARTIFACTS

    claimed = int(re.search(r"(\d+) specialist roles", _readme()).group(1))

    assert claimed <= len(SPECIALIST_ARTIFACTS), (
        f"README claims {claimed} specialist roles; the registry has {len(SPECIALIST_ARTIFACTS)}"
    )


def test_the_layering_the_readme_describes_exists():
    """Each layer the README names (skills, specialists, templates, checks) exists in the repository."""
    assert (ROOT / "skills" / "files").is_dir(), "skills layer"
    assert (ROOT / "src" / "core" / "specialists" / "registry.py").is_file(), "specialists layer"
    assert (ROOT / "pipelines").is_dir(), "pipelines layer"
    assert (ROOT / "src" / "core" / "governance.py").is_file(), "gates layer"


def test_the_shipped_pipeline_is_real():
    """The README says a template is a .toml file. The shipped one has to load."""
    from src.core.pipeline.spec import available, find_spec

    assert "empirical" in available()
    assert find_spec("empirical").steps


def test_the_floor_claim_is_true():
    """A template that declares no checks still carries the mandatory ones."""
    from src.core.pipeline.spec import MANDATORY_CHECKS, spec_from_dict

    bare = spec_from_dict({"name": "bare", "steps": [{"kind": "strategist", "name": "initial"}]})

    assert bare.declared_checks() == []
    assert set(bare.checks()) >= MANDATORY_CHECKS, "a pipeline that declares nothing still carries the floor"


def test_the_readme_does_not_promise_specialists_as_files_yet():
    """Pipelines are files; specialists are still Python.

    Worth a test because it is the obvious next thing to claim and the claim
    would currently be false — registry.py is where a new role is added. If that
    changes, delete this test in the same commit that makes it wrong.
    """
    from src.core.specialists import registry

    assert isinstance(registry.SPECIALIST_ARTIFACTS, dict)
    assert not (ROOT / "specialists").is_dir(), (
        "specialists/ now exists — update the README, which still says only pipelines are files"
    )


# ── every terminal command is in the README (plan B5) ────────────────────────


def _subcommands(parser) -> list[list[str]]:
    """Every command path of an argparse parser: ``[["add"], ["topics", "add"], …]``."""
    import argparse

    out: list[list[str]] = []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            seen: set[int] = set()
            for name, sub in action.choices.items():
                if id(sub) in seen:  # an alias of a command already listed
                    continue
                seen.add(id(sub))
                out.append([name])
                out += [[name, *rest] for rest in _subcommands(sub)]
    return out


def _main_commands() -> list[list[str]]:
    """The command paths `e2er` itself defines (src/__main__.py), read from its source.

    `main()` builds its parser inline, so the parser tree is rebuilt from the
    `add_parser` / `add_subparsers` calls: ``x_p = subparsers.add_parser("x")`` is
    the command ``x``, ``x_sub = x_p.add_subparsers()`` its group, and
    ``x_sub.add_parser("y")`` the command ``x y``.
    """
    import ast

    tree = ast.parse((ROOT / "src" / "__main__.py").read_text(encoding="utf-8"))
    path_of: dict[str, list[str]] = {"subparsers": []}  # variable -> the command path it adds to (a group)
    parser_of: dict[str, list[str]] = {}  # variable -> the command it is the parser of
    out: list[list[str]] = []

    def call_info(node):
        func = node.func if isinstance(node, ast.Call) else None
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            return node.func.value.id, node.func.attr, node.args
        return None

    for node in ast.walk(tree):
        targets: list[str] = []
        value = None
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        elif isinstance(node, ast.Expr):
            value = node.value
        info = call_info(value)
        if not info:
            continue
        owner, attr, args = info
        if attr == "add_parser" and owner in path_of and args and isinstance(args[0], ast.Constant):
            path = [*path_of[owner], args[0].value]
            out.append(path)
            for t in targets:
                parser_of[t] = path
        elif attr == "add_subparsers" and owner in parser_of:
            for t in targets:
                path_of[t] = parser_of[owner]
    return out


def test_every_terminal_command_is_documented_in_the_readme():
    """Every `e2er` command and subcommand appears in the README as `e2er <command> [<subcommand>]`."""
    from src.cli_corpus import build_parser as library_parser
    from src.cli_skills import build_parser as skills_parser

    commands = _main_commands()
    commands += [["library", *p] for p in _subcommands(library_parser())]
    commands += [["skills", *p] for p in _subcommands(skills_parser())]
    assert ["preregister", "deposit"] in commands and ["dossier", "push"] in commands  # the reader works
    text = _readme()
    missing = [" ".join(p) for p in commands if not re.search(r"\be2er " + re.escape(" ".join(p)) + r"(?![\w-])", text)]
    assert not missing, "the README's terminal commands do not mention: " + ", ".join(f"e2er {m}" for m in missing)
