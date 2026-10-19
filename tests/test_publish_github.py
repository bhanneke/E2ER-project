"""`e2er publish --github`: the study's files in a public GitHub repository, linked at the pushed commit.

GitHub is a local bare repository: git rewrites https://github.com/ to it
(``url.<file>.insteadOf``), and a fake ``gh`` answers who is logged in, whether
a repository exists, and creates one. Nothing reaches github.com.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.cli_publish import publish
from src.cli_verify import FAIL, _run_checks
from src.core import github_files as gf
from src.core.export import package as pkg
from src.core.export.structured import export_paper
from tests.test_derived_data import _gaia_workspace
from tests.test_publish_data_terms import _add, plain_bundle  # noqa: F401 — fixture

ID = dict(owner="ada", project="demo", orcid="0009-0000-7466-9581", name=None)

FAKE_GH = """\
import json, os, subprocess, sys
from pathlib import Path
root = Path(os.environ["FAKE_GH_ROOT"])
args = sys.argv[1:]
with open(root / "calls.log", "a") as f:
    f.write(" ".join(args) + "\\n")
if args[:2] == ["api", "user"]:
    if os.environ.get("FAKE_GH_LOGGED_OUT"):
        print("To get started with GitHub CLI, please run:  gh auth login", file=sys.stderr)
        sys.exit(4)
    print(json.dumps({"login": "ada", "id": 42}))
elif args[:2] == ["repo", "view"]:
    bare = root / (args[2] + ".git")
    if not bare.is_dir():
        print("GraphQL: Could not resolve to a Repository with the name '" + args[2] + "'.", file=sys.stderr)
        sys.exit(1)
    private = (bare / "PRIVATE").exists()
    print(json.dumps({"visibility": "PRIVATE" if private else "PUBLIC", "defaultBranchRef": {"name": "main"},
                      "isArchived": False}))
elif args[:2] == ["repo", "create"]:
    assert "--public" in args, args
    bare = root / (args[2] + ".git")
    bare.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--quiet", "--bare", "-b", "main", str(bare)], check=True)
    print("https://github.com/" + args[2])
else:
    print("fake gh: unexpected " + " ".join(args), file=sys.stderr)
    sys.exit(2)
"""


@pytest.fixture
def github(tmp_path: Path, monkeypatch) -> Path:
    """A fake GitHub: bare repositories under the returned folder, a fake gh first on PATH."""
    root = tmp_path / "github"
    root.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(f"#!{sys.executable}\n" + FAKE_GH, encoding="utf-8")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_GH_ROOT", str(root))
    monkeypatch.delenv("FAKE_GH_LOGGED_OUT", raising=False)
    # git sends https://github.com/<owner>/<repo>.git to the bare repository instead.
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", f"url.file://{root}/.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "https://github.com/")
    for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
        monkeypatch.delenv(k, raising=False)
    real_which = shutil.which
    # No tectonic (the paper is not recompiled in the tests); the fake gh is found.
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: str(gh) if name == "gh" else None)
    monkeypatch.setattr(pkg, "uv_lock", lambda r, p, a: (None, "offline in the tests"))
    monkeypatch.delenv("E2ER_PURPOSE", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    del real_which
    return root


def _git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _tree(bare: Path, ref: str = "main") -> list[str]:
    return sorted(_git("--git-dir", str(bare), "ls-tree", "-r", "--name-only", ref).splitlines())


def _clone(bare: Path, dest: Path) -> Path:
    _git("clone", "--quiet", str(bare), str(dest))
    return dest


def _seed(root: Path, full: str, files: dict[str, str]) -> Path:
    """A repository on the fake GitHub with one commit of ``files``."""
    bare = root / f"{full}.git"
    bare.parent.mkdir(parents=True, exist_ok=True)
    _git("init", "--quiet", "--bare", "-b", "main", str(bare))
    work = root / "seed-work"
    shutil.rmtree(work, ignore_errors=True)
    _git("clone", "--quiet", str(bare), str(work))
    for rel, text in files.items():
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_text(text, encoding="utf-8")
    _git("add", "-A", cwd=work)
    _git("-c", "user.name=t", "-c", "user.email=t@example.org", "commit", "--quiet", "-m", "seed", cwd=work)
    _git("push", "--quiet", "origin", "HEAD:main", cwd=work)
    shutil.rmtree(work)
    return bare


def _manifest(b: Path) -> dict:
    return json.loads((b / "e2er.json").read_text())


@pytest.fixture
def gaia_study(tmp_path: Path, monkeypatch) -> Path:
    """A Gaia study: the raw rows are never exported, data/gaia_clean.csv is built from them (restricted too)."""
    monkeypatch.setattr(pkg, "uv_lock", lambda r, p, a: (None, "offline in the tests"))
    return export_paper(_gaia_workspace(tmp_path), tmp_path / "exports", date_str="20261014")


@pytest.fixture
def who_study(plain_bundle: Path) -> Path:  # noqa: F811
    """A WHO study: a WHO GHO table in data/data.db, plus a data file of the study's own (data/own_counts.csv)."""
    _add(plain_bundle, "data/data.db", b"SQLite format 3\x00 who rows")
    dictionary = {"tables": [{"name": "who_rs198", "source": "who_gho", "version": "2024-04-15", "rows": 204}]}
    _add(plain_bundle, "data/data_dictionary.json", (json.dumps(dictionary, indent=2) + "\n").encode())
    _add(plain_bundle, "data/own_counts.csv", b"region,n\nAFR,47\nEUR,53\n")
    # The derivation edges as export would have recorded them for these data.
    from src.core.export.provenance import _edges

    prov_path = plain_bundle / "provenance.json"
    prov = json.loads(prov_path.read_text(encoding="utf-8"))
    prov["edges"] = _edges(plain_bundle)
    prov_path.write_text(json.dumps(prov, indent=2) + "\n", encoding="utf-8")
    return plain_bundle


# ── what goes up, and what never does ────────────────────────────────────────


def test_a_gaia_study_goes_up_without_its_restricted_or_derived_data_and_verifies_in_a_clone(
    gaia_study: Path, github: Path, tmp_path: Path, capsys
):
    assert (gaia_study / "data" / "gaia_clean.csv").is_file()
    rc = publish(
        str(gaia_study), **ID, no_db=True, github_repo="ada/demos", github_path="pleiades", out=str(tmp_path / "e")
    )
    out = capsys.readouterr().out
    assert rc == 0, out
    bare = github / "ada" / "demos.git"
    assert "repo create ada/demos --public" in (github / "calls.log").read_text(), "a missing repository is created"
    tree = _tree(bare)
    assert all(p.startswith("pleiades/") for p in tree)
    assert "pleiades/data/gaia_clean.csv" not in tree and "pleiades/data/gaia_dr3.csv" not in tree
    assert {
        "pleiades/provenance.json",
        "pleiades/e2er.json",
        "pleiades/e2er-package.json",
        "pleiades/README.md",
    } <= set(tree)
    assert any(p.startswith("pleiades/code/") for p in tree)
    assert "left out: data/gaia_clean.csv" in out
    # The record: repository, folder and the commit that holds the files.
    sha = _git("--git-dir", str(bare), "rev-parse", "main")
    m = _manifest(gaia_study)
    assert m["repository"]["url"] == "https://github.com/ada/demos" and m["repository"]["path"] == "pleiades"
    assert m["repository"]["commit"] == sha and m["repository"]["host"] == "github"
    assert [i["path"] for i in m["repository"]["left_out"]] == ["data/gaia_clean.csv"]
    assert m["availability"]["code"] == {"access": "public", "url": "https://github.com/ada/demos"}
    assert m["availability"]["data"] == {"access": "private"}, "no data file went up, so no data are public"
    assert f"https://github.com/ada/demos/tree/{sha}/pleiades" in out
    record = json.loads((gaia_study / ".e2er" / "github.json").read_text())
    assert record["commit"] == sha and "data/gaia_clean.csv" not in record["files"]
    # The copy in the repository: e2er.json without the commit, README with the dossier and what is left out.
    clone = _clone(bare, tmp_path / "clone")
    pushed = json.loads((clone / "pleiades" / "e2er.json").read_text())
    assert "commit" not in pushed["repository"] and "access" not in pushed
    assert pushed["dossier"]["id"] == m["dossier"]["id"] and pushed["content_id"] == m["content_id"]
    readme = (clone / "pleiades" / "README.md").read_text()
    assert m["dossier"]["url"] in readme and "data/gaia_clean.csv" in readme and "Gaia" in readme
    assert "No licence was set" in readme
    # Anyone can verify the clone: the left-out file is declared and the folder's own records restrict it.
    checks = _run_checks(clone / "pleiades", online=False)
    assert not [c for c in checks if c.status == FAIL], [(c.name, c.detail) for c in checks]
    # And the local folder still verifies, with the amendments recorded.
    assert not [c for c in _run_checks(gaia_study, online=False) if c.status == FAIL]


def test_a_who_study_goes_up_with_its_own_data_only_and_the_paper_links_the_commit(
    who_study: Path, github: Path, tmp_path: Path, capsys
):
    rc = publish(
        str(who_study), **ID, github_repo=True, license_id="CC-BY-4.0", demonstration=True, out=str(tmp_path / "e")
    )
    out = capsys.readouterr().out
    assert rc == 0, out
    bare = github / "ada" / "demo.git"  # --github alone: <login>/<project>
    tree = _tree(bare)
    assert "data/data.db" not in tree, "WHO's terms keep the table out"
    assert "data/own_counts.csv" in tree and "paper/paper.pdf" in tree
    sha = _git("--git-dir", str(bare), "rev-parse", "main")
    m = _manifest(who_study)
    assert m["availability"]["data"] == {"access": "public", "url": "https://github.com/ada/demo"}
    assert m["access"] == {"status": "public", "pdf": f"https://github.com/ada/demo/raw/{sha}/paper/paper.pdf"}
    assert "path" not in m["repository"]
    assert m["repository"]["left_out"] == [
        {
            "path": "data/data.db",
            "reason": "the terms of the WHO Global Health Observatory (WHO GHO) do not allow passing the data on",
        }
    ]
    readme = _git("--git-dir", str(bare), "show", "main:README.md")
    assert "Code and text: CC-BY-4.0" in readme and "data/data.db" in readme
    assert readme.count("**Demonstration: published as is, not endorsed.** This study was produced") == 1
    assert "Folder guide" in readme or "Reproduce" in readme, "the export's own README stays below the summary"


def test_the_dossier_does_not_name_the_commit_and_dry_run_lists_without_pushing(
    who_study: Path, github: Path, tmp_path: Path, capsys
):
    rc = publish(str(who_study), **ID, github_repo="ada/demos", github_path="who", dry_run=True)
    captured = capsys.readouterr()
    assert rc == 0, captured.out + captured.err
    assert "github: would push" in captured.err and "github   + data/own_counts.csv" in captured.err
    assert "github   left out: data/data.db" in captured.err
    assert "github   + data/data.db" not in captured.err
    assert not (github / "ada").exists(), "a dry run creates no repository and pushes nothing"
    assert not (who_study / "e2er.json").exists()
    body = json.loads(captured.out[: captured.out.rindex("}") + 1])
    assert body["repository"]["commit"] == "0" * 40
    assert "availability" in body["dossier"]["doc"]
    doc = body["dossier"]["doc"]
    assert doc["availability"]["code"] == {"access": "public", "url": "https://github.com/ada/demos"}
    assert "/tree/" not in json.dumps(doc) and "/raw/" not in json.dumps(doc), "the dossier never names a commit"


# ── several studies, new versions, other people's files ──────────────────────


def test_two_studies_share_a_repository_and_files_outside_their_folders_stay(
    gaia_study: Path, who_study: Path, github: Path, tmp_path: Path, capsys
):
    bare = _seed(github, "ada/demos", {"README.md": "# Demos\n", "other/keep.txt": "mine\n"})
    assert (
        publish(
            str(gaia_study),
            **ID,
            no_db=True,
            github_repo="ada/demos",
            github_path="studies/pleiades",
            out=str(tmp_path / "e1"),
        )
        == 0
    )
    first = _git("--git-dir", str(bare), "rev-parse", "main")
    assert (
        publish(
            str(who_study),
            **{**ID, "project": "who"},
            github_repo="ada/demos",
            github_path="studies/who",
            out=str(tmp_path / "e2"),
        )
        == 0
    ), capsys.readouterr().out
    second = _git("--git-dir", str(bare), "rev-parse", "main")
    assert _git("--git-dir", str(bare), "rev-parse", "main^") == first, "a new commit on top, never a rewrite"
    tree = _tree(bare)
    assert "README.md" in tree and "other/keep.txt" in tree
    assert _git("--git-dir", str(bare), "show", "main:other/keep.txt") == "mine"
    assert any(p.startswith("studies/pleiades/") for p in tree) and any(p.startswith("studies/who/") for p in tree)
    assert _manifest(gaia_study)["repository"]["commit"] == first
    assert _manifest(who_study)["repository"]["commit"] == second
    assert "repo create" not in (github / "calls.log").read_text()


def test_a_new_version_is_a_new_commit_and_the_same_files_make_none(
    who_study: Path, github: Path, tmp_path: Path, capsys
):
    args = dict(**ID, github_repo="ada/demos", github_path="who")
    assert publish(str(who_study), **args, out=str(tmp_path / "e1")) == 0
    bare = github / "ada" / "demos.git"
    v1 = _git("--git-dir", str(bare), "rev-parse", "main")
    capsys.readouterr()
    assert publish(str(who_study), **args, out=str(tmp_path / "e2")) == 0
    assert _git("--git-dir", str(bare), "rev-parse", "main") == v1, "the same files: no new commit"
    assert "Already on GitHub" in capsys.readouterr().out
    assert publish(str(who_study), **args, license_id="MIT", out=str(tmp_path / "e3")) == 0
    v2 = _git("--git-dir", str(bare), "rev-parse", "main")
    assert v2 != v1 and _git("--git-dir", str(bare), "rev-parse", "main^") == v1
    m = _manifest(who_study)
    assert m["repository"]["commit"] == v2 and v2 in m["access"]["pdf"]
    assert "Code and text: MIT" in _git("--git-dir", str(bare), "show", "main:who/README.md")


def test_a_folder_with_someone_elses_files_is_refused_and_nothing_changes(
    who_study: Path, github: Path, tmp_path: Path, capsys
):
    bare = _seed(github, "ada/demos", {"who/notes.txt": "not a study\n"})
    before = _git("--git-dir", str(bare), "rev-parse", "main")
    rc = publish(str(who_study), **ID, github_repo="ada/demos", github_path="who", out=str(tmp_path / "e"))
    out = capsys.readouterr().out
    assert rc == 1 and "not this study's" in out and "who/notes.txt" not in out or "notes.txt" in out
    assert _git("--git-dir", str(bare), "rev-parse", "main") == before
    assert not (who_study / "e2er.json").exists(), "nothing written when the push is refused"


def test_the_root_of_a_repository_with_other_files_is_refused(who_study: Path, github: Path, tmp_path: Path, capsys):
    bare = _seed(github, "ada/demos", {"README.md": "# Mine\n"})
    before = _git("--git-dir", str(bare), "rev-parse", "main")
    assert publish(str(who_study), **ID, github_repo="ada/demos", out=str(tmp_path / "e")) == 1
    assert "--github-path" in capsys.readouterr().out
    assert _git("--git-dir", str(bare), "rev-parse", "main") == before


def test_a_folder_inside_another_studys_folder_is_refused(
    gaia_study: Path, who_study: Path, github: Path, tmp_path: Path, capsys
):
    assert (
        publish(
            str(gaia_study), **ID, no_db=True, github_repo="ada/demos", github_path="pleiades", out=str(tmp_path / "e1")
        )
        == 0
    )
    before = _git("--git-dir", str(github / "ada" / "demos.git"), "rev-parse", "main")
    capsys.readouterr()
    rc = publish(
        str(who_study),
        **{**ID, "project": "who"},
        github_repo="ada/demos",
        github_path="pleiades/who",
        out=str(tmp_path / "e2"),
    )
    assert rc == 1 and "inside the folder of another study" in capsys.readouterr().out
    assert _git("--git-dir", str(github / "ada" / "demos.git"), "rev-parse", "main") == before


def test_a_private_repository_is_refused(who_study: Path, github: Path, tmp_path: Path, capsys):
    bare = _seed(github, "ada/demos", {"x.txt": "x\n"})
    (bare / "PRIVATE").write_text("")
    assert publish(str(who_study), **ID, github_repo="ada/demos", github_path="who", out=str(tmp_path / "e")) == 1
    assert "public repository" in capsys.readouterr().out


def test_a_file_that_holds_a_token_is_never_pushed(who_study: Path, github: Path, tmp_path: Path, capsys):
    _add(who_study, "code/settings.py", b'TOKEN = "ghp_' + b"a1B2c3D4e5F6g7H8i9J0k1L2m3N4" + b'"\n')
    assert publish(str(who_study), **ID, github_repo="ada/demos", github_path="who", out=str(tmp_path / "e")) == 1
    out = capsys.readouterr().out
    assert "code/settings.py: looks like a GitHub token" in out
    assert not (github / "ada" / "demos.git").exists() or not _tree(github / "ada" / "demos.git")


def test_restricted_files_are_checked_again_right_before_the_commit(who_study: Path, github: Path, tmp_path: Path):
    """Even a staged copy that somehow held WHO's table is refused at the last step."""
    staged = gf.Staged(root=tmp_path / "s", files=["data/data.db"], left_out=[])
    (tmp_path / "s" / "data").mkdir(parents=True)
    (tmp_path / "s" / "data" / "data.db").write_bytes(b"x")
    _seed(github, "ada/demos", {"x.txt": "x\n"})
    with pytest.raises(gf.GitHubError, match="terms keep it out"):
        gf.push(
            gf.Target("ada", "demos", "who"),
            staged,
            study_ids={"ada/demo"},
            message="m",
            user={"login": "ada", "id": 42},
            restricted={"data/data.db"},
            exists=True,
        )
    assert gf.kept_out(who_study, staged) == ["data/data.db"]


# ── gh: missing, logged out; options that do not go together ────────────────


def test_without_gh_publish_says_what_to_install_and_changes_nothing(
    who_study: Path, github: Path, monkeypatch, capsys
):
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: None)
    assert publish(str(who_study), **ID, github_repo=True) == 1
    out = capsys.readouterr().out
    assert "https://cli.github.com" in out and "gh auth login" in out and "never receives a GitHub token" in out
    assert not (who_study / "e2er.json").exists()


def test_logged_out_gh_says_what_to_run(who_study: Path, github: Path, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_GH_LOGGED_OUT", "1")
    assert publish(str(who_study), **ID, github_repo="ada/demos") == 1
    out = capsys.readouterr().out
    assert "gh auth login" in out and "GH_TOKEN" in out


@pytest.mark.parametrize(
    "extra, words",
    [
        ({"data": "private"}, "--data private"),
        ({"code": "private"}, "--code private"),
        ({"zenodo": True}, "--zenodo"),
        ({"commit": "abc1234"}, "--commit"),
        ({"paper_url": "https://example.org/p.pdf"}, "--paper-url"),
    ],
)
def test_options_that_contradict_github_are_refused(who_study: Path, github: Path, extra, words, capsys):
    assert publish(str(who_study), **ID, github_repo=True, **extra) == 2
    assert words in capsys.readouterr().out


def test_github_path_needs_github(who_study: Path, capsys):
    assert publish(str(who_study), **ID, github_path="x") == 2


@pytest.mark.parametrize("bad", ["../x", ".git", "a//b", "a/.hidden", "a\\b"])
def test_a_folder_that_is_not_plain_is_refused(bad: str):
    with pytest.raises(ValueError):
        gf.clean_path(bad)


def test_the_command_line_reads_github_as_before_and_as_a_repository(monkeypatch):
    import argparse

    from src import __main__ as cli

    def ns(value):
        return argparse.Namespace(github=value, github_login=None)

    assert cli._github_login(ns("bhanneke")) == "bhanneke" and cli._github_repo(ns("bhanneke")) is None
    assert cli._github_repo(ns("bhanneke/e2er-demos")) == "bhanneke/e2er-demos"
    assert cli._github_login(ns("bhanneke/e2er-demos")) is None
    assert cli._github_repo(ns(True)) is True
    assert cli._github_login(argparse.Namespace(github=True, github_login="ada")) == "ada"


def test_publishing_to_e2er_org_sends_the_repository_at_the_pushed_commit_and_no_token(
    who_study: Path, github: Path, tmp_path: Path, monkeypatch, capsys
):
    import jsonschema

    from src.core import platform_client as pc

    schema = json.loads((Path(__file__).parent.parent / "docs/schemas/research-object.schema.json").read_text())
    sent: list[dict] = []

    def server(base, method, path, token=None, body=None):
        sent.append(body)
        oid = body["manifest"]["id"]
        return 201, {"id": oid, "owner_project": oid, "version": 1, "study_url": f"{base}/{oid}", "dossier_url": "x"}

    monkeypatch.setattr(pc, "request", server)
    monkeypatch.setattr(pc, "load_token", lambda base: "tok")
    monkeypatch.setenv("GH_TOKEN", "ghp_" + "Z" * 36)
    rc = publish(str(who_study), **ID, github_repo="ada/demos", github_path="who", to_url="https://e2er.example")
    out = capsys.readouterr().out
    assert rc == 0, out
    bare = github / "ada" / "demos.git"
    sha = _git("--git-dir", str(bare), "rev-parse", "main")
    assert _git("--git-dir", str(bare), "rev-list", "--count", "main") == "1", "the rehearsal pushed nothing"
    (body,) = sent
    assert body["repository"]["commit"] == sha and body["repository"]["path"] == "who"
    assert body["manifest"]["access"]["pdf"] == f"https://github.com/ada/demos/raw/{sha}/who/paper/paper.pdf"
    assert "ghp_" not in json.dumps(body), "e2er.org never receives the GitHub token"
    d = body["dossier"]
    jsonschema.Draft202012Validator(schema).validate(
        {**body["manifest"], "dossier": {"id": d["id"], "url": body["manifest"]["dossier"]["url"], "doc": d["doc"]}}
    )
    link = json.loads((who_study / ".e2er" / "link.json").read_text())
    assert link["files"] == f"https://github.com/ada/demos/tree/{sha}/who"
    assert f"files https://github.com/ada/demos/tree/{sha}/who" in out


def test_the_summary_at_the_top_of_readme_changes_neither_the_title_nor_the_question(
    gaia_study: Path, github: Path, tmp_path: Path, capsys
):
    """The export's README names the study (heading cut short) and its question; the summary above it does not."""
    from src.core.export.provenance import _edges
    from src.core.research_object import _question_and_title

    readme = "# Which stars are Pleiades memb...\n\n**Research question:** Which stars are members?\n"
    _add(gaia_study, "README.md", readme.encode())
    _add(
        gaia_study,
        "paper/paper.tex",
        b"\\title{Which Stars Are Pleiades Members? A Full Title}\n\\begin{document}\\end{document}\n",
    )
    prov_path = gaia_study / "provenance.json"
    prov = json.loads(prov_path.read_text(encoding="utf-8"))
    prov["edges"] = _edges(gaia_study)
    prov_path.write_text(json.dumps(prov, indent=2) + "\n", encoding="utf-8")
    before = _question_and_title(gaia_study)
    rc = publish(str(gaia_study), **ID, no_db=True, github_repo="ada/demos", github_path="p", out=str(tmp_path / "e"))
    assert rc == 0, capsys.readouterr().out
    text = (gaia_study / "README.md").read_text()
    assert text.startswith("<!-- e2er:github begin -->\n# Which Stars Are Pleiades Members? A Full Title")
    assert text.endswith(readme), "the export's README stays below the summary"
    assert _question_and_title(gaia_study) == before
    m = _manifest(gaia_study)
    assert m["title"] == m["dossier"]["doc"]["study"]["title"] == "Which stars are Pleiades memb..."
    clone = _clone(github / "ada" / "demos.git", tmp_path / "clone")
    assert not [c for c in _run_checks(clone / "p", online=False) if c.status == FAIL]
    assert not [c for c in _run_checks(gaia_study, online=False) if c.status == FAIL]


# ── 2026-10-19: what the demos found ─────────────────────────────────────────


def test_a_file_github_would_refuse_for_its_size_stops_publish_before_anything_is_pushed(
    who_study: Path, github: Path, tmp_path: Path, monkeypatch, capsys
):
    """The weather-words demo: data/data.db is 145 MB, over GitHub's 100 MB limit; the dry run said it would go up."""
    monkeypatch.setattr(gf, "GITHUB_FILE_LIMIT", 10)
    rc = publish(str(who_study), **ID, github_repo="ada/demos", github_path="who", dry_run=True)
    captured = capsys.readouterr()
    assert rc != 0
    assert "GitHub refuses files larger than 100 MB" in captured.out + captured.err
    rc = publish(str(who_study), **ID, github_repo="ada/demos", github_path="who", out=str(tmp_path / "e"))
    captured = capsys.readouterr()
    assert rc != 0 and "GitHub refuses files larger than 100 MB" in captured.out + captured.err
    assert not (github / "ada" / "demos.git").exists(), "no repository was made and nothing was pushed"
