"""The finish page without mess: one current study folder, plain refusals, plain network errors.

* "Prepare the folder" (and every stop of the run) used to add a numbered copy
  (``…-01`` to ``…-05``): :mod:`src.core.export.current` keeps one current folder,
  keeps a published one, and removes older copies on request.
* A refused preview or publish showed what `e2er publish` printed: now one
  sentence first, the output folded with this computer's paths and full ids
  shortened.
* Publishing offline before tectonic downloaded its LaTeX packages says so.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from src.core.export import current as cur

PID = "5b3d53ca-55e9-41fd-848f-c71f55ae5f85"


def _workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "manifest.json").write_text(json.dumps({"paper_id": PID, "title": "FOMC and bank stocks"}))
    (ws / "paper_draft.tex").write_text("\\documentclass{article}\\begin{document}x\\end{document}")
    (ws / "estimation_results.json").write_text('{"main": {"coef": 0.5}}')
    return ws


def _touch(p: Path, text: str) -> None:
    p.write_text(text)
    later = time.time() + 5
    os.utime(p, (later, later))


def _export(ws: Path, root: Path) -> tuple[Path, str]:
    out, state = cur.export_current(ws, root, paper_id=PID, date_str="20261008")
    # export_paper records the run in provenance.json; the tests make sure it names this run.
    prov = json.loads((out / "provenance.json").read_text())
    assert (prov.get("run") or {}).get("paper_id") == PID
    return out, state


def test_an_unchanged_run_reuses_its_folder_and_a_changed_one_replaces_it(tmp_path: Path):
    ws, root = _workspace(tmp_path), tmp_path / "exports"
    first, s1 = _export(ws, root)
    again, s2 = _export(ws, root)
    assert (s1, s2) == ("new", "unchanged") and again == first
    _touch(ws / "estimation_results.json", '{"main": {"coef": 0.6}}')
    third, s3 = _export(ws, root)
    assert s3 == "replaced" and third.name == first.name
    assert [d.name for d in cur.exports_of(root, PID)] == [first.name]


def test_a_published_folder_stays_and_the_next_change_gets_a_new_folder(tmp_path: Path):
    ws, root = _workspace(tmp_path), tmp_path / "exports"
    first, _ = _export(ws, root)
    (first / ".e2er").mkdir()
    (first / ".e2er" / "link.json").write_text(json.dumps({"owner_project": "kim/fomc", "version": 1}))
    assert cur.is_published(first)
    _touch(ws / "estimation_results.json", '{"main": {"coef": 0.7}}')
    second, state = _export(ws, root)
    assert state == "new" and second != first and first.is_dir()


def test_remove_older_copies_never_removes_the_current_or_the_published_folder(tmp_path: Path):
    from src.core.export.structured import export_paper

    ws, root = _workspace(tmp_path), tmp_path / "exports"
    old1 = export_paper(ws, root, date_str="20261007")  # copies `e2er export` or an older e2er made
    old2 = export_paper(ws, root, date_str="20261007")
    (old2 / ".e2er").mkdir()
    (old2 / ".e2er" / "link.json").write_text("{}")
    (root / f"{old1.name}-registry-entry").mkdir()
    time.sleep(0.01)
    now, _ = _export(ws, root)
    assert cur.older_copies(root, PID) == [old1]
    assert cur.remove_older_copies(root, PID) == [old1.name]
    assert not old1.exists() and not (root / f"{old1.name}-registry-entry").exists()
    assert old2.is_dir() and now.is_dir()


def test_a_refusal_is_one_plain_sentence_and_the_output_is_shortened():
    from src.api.finish import plain_failure, shorten
    from src.cli_publish import LATEX_OFFLINE

    out = (
        f"note: the run's steps are read from /Users/ann/.e2er/papers.db (paper {PID})\n"
        "error: recompiling paper.tex would break the PDF (2 citation(s) unresolved: a, b); nothing was changed\n"
        f"dossier sha256:{'a' * 64}"
    )
    short = shorten(out)
    assert "/Users/ann" not in short and PID not in short and "5b3d53ca…" in short
    assert f"sha256:{'a' * 12}…" in short
    assert plain_failure(out, [], "https://e2er.org") == (
        "Recompiling paper.tex would break the PDF (2 citation(s) unresolved: a, b); nothing was changed."
    )
    assert "tick the box" in plain_failure("error: x", ["yfinance"], "https://e2er.org")
    assert plain_failure("error: not signed in to https://e2er.org", [], "https://e2er.org").startswith("Sign in")
    assert plain_failure("error: could not reach https://e2er.org: boom", [], "https://e2er.org") == (
        "https://e2er.org could not be reached. Check the internet connection and try again."
    )
    assert plain_failure(f"error: {LATEX_OFFLINE}", [], "x") == LATEX_OFFLINE
    assert plain_failure("", [], "x").startswith("e2er could not publish the study")


def test_tectonic_without_its_packages_offline_is_recognised():
    from src.cli_publish import latex_packages_missing

    panic = (
        "called `Result::unwrap()` on an `Err` value: this bundle isn't cached, and we couldn't get it from the "
        "internet. Error: error sending request for url (https://relay.fullyjustified.net/default_bundle_v33.tar)"
    )
    assert latex_packages_missing(panic)
    assert not latex_packages_missing("! Undefined control sequence.")


def test_network_errors_on_preflight_are_one_plain_sentence():
    from src.core.labels import check_detail

    raw = (
        "ConnectionError: Failed to perform, curl: (7) Failed to connect to query2.finance.yahoo.com:443 over "
        "proxy 127.0.0.1 after 0 ms"
    )
    assert check_detail("data.yfinance.history", raw) == (
        "Yahoo Finance could not be reached. Check the internet connection; e2er tries again when you start a study."
    )
    assert check_detail("data.fred.observations", "transport error: All connection attempts failed").startswith(
        "FRED could not be reached"
    )
    assert "could not run" in check_detail("data.list_data_sources", "RuntimeError('boom')")
