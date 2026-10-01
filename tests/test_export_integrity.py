"""What `e2er export` puts into a bundle, and what it never does.

Findings of the 2026-10-01 review: two exports on the same day could share
one folder; dotfiles such as ``replication/.env`` (keys) were copied, and links
out of the workspace were followed; ``paper.pdf`` silently overwrote the
paper compiled from ``paper_draft.tex``; ``report.html`` and every file named
``provenance.json`` (at any depth) were left out of the fingerprints.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from src.core.export.structured import create_versioned_folder, export_paper


def _workspace(root: Path) -> Path:
    ws = root / "ws"
    ws.mkdir(parents=True)
    (ws / "manifest.json").write_text(json.dumps({"title": "Synth Study", "pipeline": "empirical"}))
    (ws / "paper_draft.tex").write_text("\\documentclass{article}\\begin{document}x\\end{document}")
    return ws


def test_two_exports_at_the_same_moment_get_two_folders(tmp_path: Path):
    ws = _workspace(tmp_path)
    barrier = threading.Barrier(8)
    out: list[Path] = []

    def go() -> None:
        barrier.wait()
        out.append(export_paper(ws, tmp_path / "race", date_str="20261001"))

    threads = [threading.Thread(target=go) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len({p.name for p in out}) == 8
    for p in out:  # each folder is one complete export
        assert json.loads((p / "provenance.json").read_text())["files"]


def test_the_folder_is_created_atomically_with_the_next_free_number(tmp_path: Path):
    (tmp_path / "synth-study-20261001-01").mkdir()
    (tmp_path / "synth-study-20261001-02").mkdir()
    assert create_versioned_folder(tmp_path, "Synth Study", "20261001").name == "synth-study-20261001-03"


def test_dotfiles_key_files_and_os_files_are_never_exported(tmp_path: Path):
    ws = _workspace(tmp_path)
    for d in ("replication", "tables", "figures"):
        (ws / d).mkdir()
        (ws / d / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-secret-secret")
        (ws / d / "server.pem").write_text("-----BEGIN PRIVATE KEY-----")
        (ws / d / ".DS_Store").write_bytes(b"\0\0\0\1Bud1")
        (ws / d / "Thumbs.db").write_bytes(b"x")
        (ws / d / "kept.txt").write_text("ok")
    (ws / "debug.log").write_text("log")
    (ws / ".hidden.log").write_text("hidden")
    out = export_paper(ws, tmp_path / "out", date_str="20261001")
    names = {p.name for p in out.rglob("*") if p.is_file()}
    assert not names & {".env", "server.pem", ".DS_Store", "Thumbs.db", ".hidden.log"}
    assert (out / "replication" / "kept.txt").is_file()
    assert (out / "code" / "scratch" / "debug.log").is_file()


def test_links_that_leave_the_workspace_are_not_followed(tmp_path: Path):
    ws = _workspace(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("from outside the workspace")
    (outside / "dir").mkdir()
    (outside / "dir" / "a.tex").write_text("outside table")
    (ws / "replication").mkdir()
    os.symlink(outside / "secret.txt", ws / "replication" / "linked.txt")
    os.symlink(outside / "dir", ws / "tables")
    os.symlink(outside / "secret.txt", ws / "notes.md")
    (ws / "replication" / "inside.txt").write_text("inside")
    os.symlink(ws / "replication" / "inside.txt", ws / "replication" / "alias.txt")
    out = export_paper(ws, tmp_path / "out", date_str="20261001")
    texts = [p.read_text(errors="replace") for p in out.rglob("*") if p.is_file()]
    assert not any("from outside the workspace" in t or "outside table" in t for t in texts)
    assert not (out / "paper" / "tables").exists()
    assert (out / "replication" / "alias.txt").read_text() == "inside"  # a link inside the workspace is copied
    assert not any(p.is_symlink() for p in out.rglob("*"))


def test_paper_pdf_never_overwrites_the_pdf_of_the_draft_and_the_readme_says_which(tmp_path: Path):
    ws = _workspace(tmp_path)
    (ws / "paper_draft.pdf").write_bytes(b"%PDF current draft")
    (ws / "paper.pdf").write_bytes(b"%PDF stale older build")
    out = export_paper(ws, tmp_path / "out", date_str="20261001")
    assert (out / "paper" / "paper.pdf").read_bytes() == b"%PDF current draft"
    assert (out / "misc" / "paper.pdf").read_bytes() == b"%PDF stale older build"
    readme = (out / "README.md").read_text()
    assert "`paper/paper.pdf`" in readme and "`misc/paper.pdf`" in readme


def test_report_html_and_nested_files_named_like_the_manifests_are_fingerprinted(tmp_path: Path):
    ws = _workspace(tmp_path)
    (ws / "replication").mkdir()
    (ws / "replication" / "provenance.json").write_text('{"note": "the package\'s own file"}')
    (ws / "replication" / "e2er.json").write_text("{}")
    (ws / "replication" / "report.html").write_text("<p>package page</p>")
    out = export_paper(ws, tmp_path / "out", date_str="20261001")
    files = json.loads((out / "provenance.json").read_text())["files"]
    assert "report.html" in files
    for name in ("provenance.json", "e2er.json", "report.html"):
        assert f"replication/{name}" in files
    assert "provenance.json" not in files  # the inventory cannot list itself
