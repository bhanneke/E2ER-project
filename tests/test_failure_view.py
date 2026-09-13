"""Explain a failure where the person who hit it is looking.

Built against a real one. The journey paper died with three specialists
exhausting three attempts each, and everything needed to understand it was
already recorded: last_error held the full message, .contract_feedback/ held one
file per specialist naming the artifact it never wrote, and the events held nine
specialist_start entries for three specialists. The page said `failed` and
printed the raw blob; the diagnosis took an hour and a server log.

The hint in test_all_specialists_failing_points_at_the_environment is the one
that matters. Every specialist failing identically is almost never three models
misbehaving at once — it is the workspace or the login — and learning that the
first time cost a 53-minute run.
"""

from __future__ import annotations

from pathlib import Path

from src.api.app import _failure_detail


def _ws(tmp_path: Path, feedback: dict[str, str]) -> Path:
    ws = tmp_path / "ws"
    fb = ws / ".contract_feedback"
    fb.mkdir(parents=True)
    for name, text in feedback.items():
        (fb / f"{name}.txt").write_text(text, encoding="utf-8")
    return ws


def _starts(*names: str) -> list[dict]:
    return [{"event_type": "specialist_start", "specialist": n, "stage": None} for n in names]


def test_a_running_paper_has_no_failure_panel(tmp_path: Path):
    assert _failure_detail(tmp_path, {"status": "designing"}, [])["failed"] is False


def test_each_specialist_is_named_with_what_it_did_not_write(tmp_path: Path):
    ws = _ws(
        tmp_path,
        {
            "idea_developer": "paper_plan.md: file not written",
            "literature_scanner": "literature_review.md: file not written",
        },
    )
    detail = _failure_detail(
        ws,
        {"status": "failed", "last_error": "RuntimeError: All specialists failed in parallel batch"},
        _starts("idea_developer", "idea_developer", "idea_developer", "literature_scanner"),
    )

    by_name = {s["name"]: s for s in detail["specialists"]}
    assert by_name["idea_developer"]["attempts"] == 3
    assert "paper_plan.md" in by_name["idea_developer"]["violation"]
    assert by_name["literature_scanner"]["attempts"] == 1


def test_the_headline_drops_the_exception_class(tmp_path: Path):
    """ "RuntimeError:" is noise to the person reading it."""
    ws = _ws(tmp_path, {})
    detail = _failure_detail(ws, {"status": "failed", "last_error": "RuntimeError: the estimation script wrote {}"}, [])
    assert not detail["headline"].startswith("RuntimeError")
    assert "estimation script" in detail["headline"]


def test_all_specialists_failing_points_at_the_environment(tmp_path: Path):
    """The 53-minute lesson, made automatic.

    Three specialists failing identically with "file not written" meant the
    Claude Code CLI was refusing to write to a workspace under its own config
    directory. Nothing on screen said so.
    """
    ws = _ws(
        tmp_path,
        {
            "idea_developer": "paper_plan.md: file not written",
            "literature_scanner": "literature_review.md: file not written",
            "identification_strategist": "identification_strategy.md: file not written",
        },
    )
    detail = _failure_detail(ws, {"status": "failed", "last_error": "x"}, [])

    hint = " ".join(detail["hints"]).lower()
    assert "environment" in hint
    assert "preflight" in hint


def test_one_specialist_failing_does_not_blame_the_environment(tmp_path: Path):
    """If the others wrote their files, the workspace is plainly writable."""
    ws = _ws(
        tmp_path,
        {
            "idea_developer": "paper_plan.md: file not written",
            "literature_scanner": "literature_review.md: file is empty (0 bytes)",
        },
    )
    detail = _failure_detail(ws, {"status": "failed", "last_error": "x"}, [])
    assert not any("environment" in h.lower() for h in detail["hints"])


def test_rejected_is_explained_as_a_gate_not_a_crash(tmp_path: Path):
    """Rejected and failed look identical to a newcomer and are not the same."""
    detail = _failure_detail(tmp_path, {"status": "rejected", "last_error": ""}, [])
    assert detail["failed"] is True
    assert any("gate" in h.lower() for h in detail["hints"])


def test_paused_says_the_workspace_survived(tmp_path: Path):
    detail = _failure_detail(tmp_path, {"status": "paused", "last_error": ""}, [])
    assert any("resum" in h.lower() for h in detail["hints"])


def test_a_failure_with_nothing_recorded_still_says_something(tmp_path: Path):
    """Silence is the one thing the panel must never produce."""
    detail = _failure_detail(tmp_path, {"status": "failed", "last_error": ""}, [])
    assert detail["headline"]
