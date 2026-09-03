"""Run identity (v1.0 plan, Phase 2.2).

The question these protect: *which code produced this result?* It was answered
wrongly once already — the API server runs without `--reload`, so a canary was
measured against pre-fix code on 2026-08-20 while `git log` in the same tree
advertised the fix. Nothing in the run record contradicted it.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from src.core.experiment import (
    ROW_FIELDS,
    _identity_from_events,
    _provenance_lines,
    check_server_is_current,
    harvest_run,
)
from src.core.run_identity import identity_summary, run_identity


def _identity_event(sha: str = "abc1234def", dirty: bool | None = False) -> dict:
    return {
        "event_type": "run_identity",
        "payload": {"git_sha": sha, "git_short_sha": sha[:7], "git_dirty": dirty},
    }


# ── the stamp itself ─────────────────────────────────────────────────────────


def test_identity_reports_the_running_interpreter_and_source():
    import sys
    from pathlib import Path

    i = run_identity()
    assert i["python_executable"] == sys.executable
    # source_root must be the tree this module was actually imported from —
    # that is what makes the SHA checkable rather than merely stated.
    assert (Path(i["source_root"]) / "src" / "core" / "run_identity.py").is_file()
    assert i["pid"] > 0
    assert i["captured_at"]


def test_identity_carries_the_settings_that_shaped_dispatch():
    i = run_identity()
    assert "backend" in i and "model" in i
    # Concurrency lives nowhere else in the record, and it is the one knob the
    # validation cell changes.
    assert "max_concurrent_specialists" in i


def test_identity_is_cached_so_it_describes_the_loaded_code():
    """Capture-once is the whole mechanism. If this became a fresh read per
    call, a server would start reporting commits it never loaded."""
    assert run_identity() is run_identity()


def test_identity_survives_a_missing_git():
    """A pip-installed copy has no .git. That must degrade to `None`, not raise
    — losing the stamp must never lose the run."""
    run_identity.cache_clear()
    try:
        with patch("src.core.run_identity._git", return_value=None):
            i = run_identity()
        assert i["git_sha"] is None
        # None, not False: "clean" and "could not tell" are different claims.
        assert i["git_dirty"] is None
        assert i["python_executable"]
    finally:
        run_identity.cache_clear()


def test_identity_summary_flags_a_dirty_tree():
    run_identity.cache_clear()
    try:
        with patch("src.core.run_identity._git", side_effect=lambda *a: "M f.py" if a[0] == "status" else "abc1234"):
            assert "+dirty" in identity_summary()
    finally:
        run_identity.cache_clear()


# ── harvesting it into the experiment record ─────────────────────────────────


def test_results_csv_carries_the_code_columns():
    assert "code_sha" in ROW_FIELDS
    assert "code_dirty" in ROW_FIELDS


def test_harvest_reads_identity_from_the_runs_own_events():
    """The SHA must come from the server process that ran the paper, never from
    the driver's working tree — the driver's tree is what lied last time."""
    row = harvest_run(
        rq_idx=0,
        regime="off",
        backend="claude_code",
        repeat=1,
        paper_id="p1",
        status="completed",
        bundle_path=None,
        events=[_identity_event("abc1234def")],
    )
    assert row["code_sha"] == "abc1234"
    assert row["code_dirty"] == "clean"


def test_harvest_tolerates_a_json_encoded_payload():
    """Events arrive as dicts from the DB driver and as JSON text over HTTP."""
    raw = {"event_type": "run_identity", "payload": json.dumps({"git_short_sha": "deadbee", "git_dirty": True})}
    assert _identity_from_events([raw]) == ("deadbee", "dirty")


def test_harvest_leaves_an_unstamped_run_blank():
    """Blank, not a fabricated SHA. An unattributable run is a finding."""
    assert _identity_from_events([{"event_type": "phase_start"}]) == ("", "")


def test_unknown_dirtiness_is_not_reported_as_clean():
    assert _identity_from_events([_identity_event(dirty=None)]) == ("abc1234", "")


# ── what the summary says about it ───────────────────────────────────────────


def test_summary_flags_a_cell_that_spans_commits():
    """n runs from n commits is not n repeats of one pipeline."""
    rows = [
        {"code_sha": "aaa1111", "code_dirty": "clean"},
        {"code_sha": "bbb2222", "code_dirty": "clean"},
    ]
    text = "\n".join(_provenance_lines(rows))
    assert "did NOT come from one commit" in text


def test_summary_is_quiet_when_one_clean_commit_produced_everything():
    rows = [{"code_sha": "aaa1111", "code_dirty": "clean"} for _ in range(3)]
    text = "\n".join(_provenance_lines(rows))
    assert "aaa1111" in text
    assert "did NOT come from one commit" not in text
    assert "DIRTY" not in text


def test_summary_flags_a_dirty_tree_and_unstamped_runs():
    rows = [{"code_sha": "aaa1111", "code_dirty": "dirty"}, {"code_sha": "", "code_dirty": ""}]
    text = "\n".join(_provenance_lines(rows))
    assert "DIRTY working tree" in text
    assert "no identity stamp" in text


# ── the stale-server detector ────────────────────────────────────────────────


def test_stale_server_is_detected_before_the_run_is_spent():
    """The 2026-08-20 failure, caught up front instead of discovered after."""
    with patch("src.core.run_identity._git", return_value="n" * 40):
        warning = check_server_is_current({"git_sha": "o" * 40})
    assert warning is not None
    assert "does not reload" in warning
    assert "Restart the server" in warning


def test_matching_server_and_tree_produce_no_warning():
    with patch("src.core.run_identity._git", return_value="s" * 40):
        assert check_server_is_current({"git_sha": "s" * 40, "git_dirty": False}) is None


def test_a_matching_but_dirty_server_still_warns():
    """Same SHA, uncommitted changes: the run is not reproducible from it."""
    with patch("src.core.run_identity._git", return_value="s" * 40):
        warning = check_server_is_current({"git_sha": "s" * 40, "git_dirty": True})
    assert warning is not None
    assert "UNCOMMITTED" in warning


def test_undeterminable_provenance_does_not_block_the_run():
    """No git, no server stamp — say nothing rather than cry wolf."""
    assert check_server_is_current({}) is None
