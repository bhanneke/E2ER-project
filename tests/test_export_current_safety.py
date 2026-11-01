"""The current exported folder is never rebuilt over a change made after export, and never lost.

Review of 2026-10-23:

* a re-export replaced a folder with a redaction or an abstract rewrite (amendments in its
  provenance.json) by a fresh copy of the run, silently undoing the redaction;
* the replacement deleted the old folder before the new one existed, with no lock: a failed
  export lost the folder, and two exports of the same run built over each other;
* "the newest folder" was the one with the newest modification time (a redaction of an older
  folder made it the newest), not the one with the highest ``-NN``;
* a run from before 0.14 (no ``paper_id`` in manifest.json) exported folders without
  ``run.paper_id``, so the next export never found them.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from src.core.export import current as cur
from src.core.export import structured

PID = "5b3d53ca-55e9-41fd-848f-c71f55ae5f85"


def _workspace(tmp_path: Path, *, with_id: bool = True) -> Path:
    ws = tmp_path / (PID if not with_id else "ws")
    ws.mkdir()
    manifest = {"title": "FOMC and bank stocks"}
    if with_id:
        manifest["paper_id"] = PID
    (ws / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8", newline="\n")
    (ws / "paper_draft.tex").write_text(
        "\\documentclass{article}\\begin{document}Ann Smith\\end{document}", encoding="utf-8", newline="\n"
    )
    (ws / "estimation_results.json").write_text('{"main": {"coef": 0.5}}', encoding="utf-8", newline="\n")
    return ws


def _touch(p: Path, text: str) -> None:
    p.write_text(text, encoding="utf-8", newline="\n")
    later = time.time() + 5
    os.utime(p, (later, later))


def _export(ws: Path, root: Path) -> tuple[Path, str]:
    return cur.export_current(ws, root, paper_id=PID, date_str="20261008")


def test_a_redacted_folder_is_kept_and_the_next_change_gets_a_new_folder(tmp_path: Path):
    from src.core import redact as rd

    ws, root = _workspace(tmp_path), tmp_path / "exports"
    first, _ = _export(ws, root)
    rd.redact(first, "Ann Smith")
    assert cur.is_amended(first)
    redacted = (first / "paper" / "paper.tex").read_text(encoding="utf-8")
    assert "Ann Smith" not in redacted
    _touch(ws / "estimation_results.json", '{"main": {"coef": 0.6}}')
    second, state = _export(ws, root)
    assert state == "new" and second != first
    # The redaction is still there; nothing rebuilt the folder from the run.
    assert (first / "paper" / "paper.tex").read_text(encoding="utf-8") == redacted
    assert cur.older_copies(root, PID) == []  # an amended folder is never offered for removal either


def test_an_abstract_rewrite_counts_as_an_amendment(tmp_path: Path):
    ws, root = _workspace(tmp_path), tmp_path / "exports"
    first, _ = _export(ws, root)
    prov = json.loads((first / "provenance.json").read_text(encoding="utf-8"))
    prov["amendments"] = [{"path": "paper/abstract.tex", "kind": "abstract_rewritten"}]
    (first / "provenance.json").write_text(json.dumps(prov), encoding="utf-8", newline="\n")
    _touch(ws / "estimation_results.json", '{"main": {"coef": 0.7}}')
    second, state = _export(ws, root)
    assert state == "new" and first.is_dir() and second != first


def test_a_failed_replacement_leaves_the_earlier_folder_as_it_was(tmp_path: Path, monkeypatch):
    ws, root = _workspace(tmp_path), tmp_path / "exports"
    first, _ = _export(ws, root)
    before = (first / "provenance.json").read_text(encoding="utf-8")
    _touch(ws / "estimation_results.json", '{"main": {"coef": 0.8}}')

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(structured, "write_recipe", boom, raising=False)
    monkeypatch.setattr("src.core.export.reproduce_recipe.write_recipe", boom)
    monkeypatch.setattr("src.core.export.provenance.write_provenance", boom)
    with pytest.raises(RuntimeError):
        _export(ws, root)
    assert (first / "provenance.json").read_text(encoding="utf-8") == before
    # No half-built folder or temporary folder is left behind.
    assert sorted(p.name for p in root.iterdir() if not p.name.startswith(".e2er-export-")) == sorted(
        [first.name, cur.INDEX]
    )


def test_a_failed_new_export_leaves_no_empty_numbered_folder(tmp_path: Path, monkeypatch):
    ws, root = _workspace(tmp_path), tmp_path / "exports"

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr("src.core.export.provenance.write_provenance", boom)
    with pytest.raises(RuntimeError):
        _export(ws, root)
    assert [p.name for p in root.iterdir() if not p.name.startswith(".e2er-export-")] == []


def test_two_exports_of_the_same_run_do_not_build_over_each_other(tmp_path: Path, monkeypatch):
    ws, root = _workspace(tmp_path), tmp_path / "exports"
    first, _ = _export(ws, root)
    _touch(ws / "estimation_results.json", '{"main": {"coef": 0.9}}')
    real = structured.export_paper
    inside = 0
    most = 0
    guard = threading.Lock()

    def slow(*a, **k):
        nonlocal inside, most
        with guard:
            inside += 1
            most = max(most, inside)
        try:
            time.sleep(0.2)
            return real(*a, **k)
        finally:
            with guard:
                inside -= 1

    monkeypatch.setattr(structured, "export_paper", slow)
    results: list[tuple[Path, str]] = []
    threads = [threading.Thread(target=lambda: results.append(_export(ws, root))) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert most == 1
    assert sorted(s for _, s in results) == ["replaced", "unchanged"]
    assert [d.name for d in cur.exports_of(root, PID)] == [first.name]


def test_the_newest_folder_is_the_highest_number_not_the_newest_time(tmp_path: Path):
    ws, root = _workspace(tmp_path), tmp_path / "exports"
    a = structured.export_paper(ws, root, date_str="20261008")
    b = structured.export_paper(ws, root, date_str="20261008")
    assert a.name.endswith("-01") and b.name.endswith("-02")
    # Touching the older folder (a redaction, a copy) made it "the newest" before.
    later = time.time() + 100
    os.utime(a, (later, later))
    assert cur.exports_of(root, PID) == [a, b]
    from src.api import finish

    class S:
        def resolved_output_root(self):
            return root

    import src.config

    orig = src.config.get_settings
    src.config.get_settings = lambda: S()  # type: ignore[assignment]
    try:
        assert finish.find_export(PID) == b
    finally:
        src.config.get_settings = orig  # type: ignore[assignment]


def test_a_run_from_before_0_14_keeps_its_id_in_the_export(tmp_path: Path):
    ws, root = _workspace(tmp_path, with_id=False), tmp_path / "exports"
    out = structured.export_paper(ws, root, date_str="20261008")
    assert json.loads((out / "provenance.json").read_text(encoding="utf-8"))["run"]["paper_id"] == PID
    ws2 = tmp_path / "named"
    ws2.mkdir()
    (ws2 / "manifest.json").write_text(json.dumps({"title": "x"}), encoding="utf-8", newline="\n")
    out2 = structured.export_paper(ws2, root, date_str="20261008", paper_id=PID)
    assert json.loads((out2 / "provenance.json").read_text(encoding="utf-8"))["run"]["paper_id"] == PID
    first, s1 = _export(ws2, root)
    again, s2 = _export(ws2, root)
    assert (s2, again) == ("unchanged", first)
