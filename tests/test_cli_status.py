"""`e2er status` and `e2er cancel` — re-attach + stop commands.

The deterministic surface (formatting helpers, error-code paths,
unreachable-API branch, confirmation prompt) is unit-tested here.
The polling/tail integration is exercised by `cli_run`'s
`_poll_status` tests; we don't duplicate that coverage.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.cli_status import (
    _format_money,
    _format_status_summary,
    _truncate,
    cancel,
    resume,
    status,
)

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


class TestTruncate:
    def test_short_strings_unchanged(self):
        assert _truncate("hello", 10) == "hello"

    def test_long_strings_get_ellipsis(self):
        out = _truncate("the quick brown fox jumps over the lazy dog", 20)
        assert out.endswith("...")
        assert len(out) == 20

    def test_no_dangling_whitespace_before_ellipsis(self):
        # Without the rstrip the truncation would emit '...the quick brow ...'
        out = _truncate("the quick brown fox", 12)
        assert out == "the quick..." or out.endswith("...")
        assert "  " not in out, f"double-space in truncation output: {out!r}"


class TestFormatMoney:
    def test_two_decimals(self):
        """`$8.462921999999999` (float noise) → `$8.46`. The whole
        reason we have this helper."""
        assert _format_money(8.462921999999999) == "8.46"

    def test_string_input(self):
        # FastAPI sometimes returns Decimal serialized as a string
        assert _format_money("12.5") == "12.50"

    def test_none_returns_question_mark(self):
        assert _format_money(None) == "?"

    def test_empty_string_returns_question_mark(self):
        assert _format_money("") == "?"

    def test_unparseable_returns_input_string(self):
        # Defensive: never crash; show what came in so the user can debug.
        assert _format_money("not_a_number") == "not_a_number"


class TestFormatStatusSummary:
    def _payload(self, **overrides) -> dict:
        base = {
            "id": "abc-123",
            "title": "Test paper",
            "research_question": "Does X affect Y?",
            "status": "completed",
            "methodology": "empirical",
            "mode": "single_pass",
            "workspace": "workspaces/abc-123",
            "max_cost_usd": 5.0,
            "last_error": None,
            "usage": {
                "specialist_calls": 12,
                "total_tokens": 1_234_567,
                "total_cost_usd": 3.456,
                "cost_is_estimate": False,
            },
        }
        base.update(overrides)
        return base

    def test_status_is_first_line(self):
        """The first line of the output is the most important field —
        the user usually only needs to look at this one to know what's
        happening."""
        out = _format_status_summary(self._payload(status="rejected"))
        first = out.splitlines()[0]
        assert first.startswith("Status:")
        assert "rejected" in first

    def test_cost_uses_two_decimals(self):
        out = _format_status_summary(self._payload(usage={"total_cost_usd": 8.462921999999999, "specialist_calls": 1}))
        assert "$8.46" in out
        assert "8.4629" not in out  # the noisy form must be gone

    def test_estimate_marker_when_flat_rate_backend(self):
        out = _format_status_summary(self._payload(usage={"total_cost_usd": 5.0, "cost_is_estimate": True}))
        assert "estimate" in out
        # Without the flag, no marker
        out2 = _format_status_summary(self._payload(usage={"total_cost_usd": 5.0, "cost_is_estimate": False}))
        assert "estimate" not in out2

    def test_last_error_only_shown_when_present(self):
        ok = _format_status_summary(self._payload(last_error=None))
        bad = _format_status_summary(self._payload(last_error="BudgetExceededError"))
        assert "Last error" not in ok
        assert "Last error" in bad
        assert "BudgetExceededError" in bad

    def test_long_last_error_truncated(self):
        long_err = "BudgetExceededError: " + ("x" * 500)
        out = _format_status_summary(self._payload(last_error=long_err))
        # Output line still fits in a reasonable terminal width
        last_error_line = next(line for line in out.splitlines() if line.startswith("Last error"))
        assert len(last_error_line) <= 140
        assert last_error_line.endswith("...")

    def test_dashboard_url_uses_api_root(self):
        out = _format_status_summary(self._payload(id="some-uuid"))
        assert "/papers/some-uuid" in out


# ---------------------------------------------------------------------------
# status() exit codes
# ---------------------------------------------------------------------------


class TestStatusExitCodes:
    def test_api_unreachable_returns_3(self, capsys):
        with patch("src.cli_status._api_reachable", return_value=False):
            code = status("abc")
        assert code == 3
        captured = capsys.readouterr()
        assert "unreachable" in captured.err

    def test_404_returns_4(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with (
            patch("src.cli_status._api_reachable", return_value=True),
            patch("httpx.get", return_value=mock_resp),
        ):
            code = status("missing-paper-id")
        assert code == 4

    def test_non_200_non_404_returns_5(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "internal server error"
        with (
            patch("src.cli_status._api_reachable", return_value=True),
            patch("httpx.get", return_value=mock_resp),
        ):
            code = status("abc")
        assert code == 5

    def test_request_exception_returns_3(self):
        with (
            patch("src.cli_status._api_reachable", return_value=True),
            patch("httpx.get", side_effect=ConnectionError("nope")),
        ):
            code = status("abc")
        assert code == 3

    def test_200_returns_0_and_prints_summary(self, capsys):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "abc",
            "title": "Test",
            "research_question": "?",
            "status": "completed",
            "methodology": "empirical",
            "mode": "single_pass",
            "workspace": "/tmp/x",
            "max_cost_usd": 5.0,
            "usage": {"total_cost_usd": 3.0, "specialist_calls": 5, "total_tokens": 100},
        }
        with (
            patch("src.cli_status._api_reachable", return_value=True),
            patch("httpx.get", return_value=mock_resp),
        ):
            code = status("abc")
        assert code == 0
        captured = capsys.readouterr()
        assert "completed" in captured.out
        assert "$3.00" in captured.out

    def test_tail_skips_polling_on_terminal_status(self, capsys):
        """If the paper is already at a terminal status, --tail must
        not waste a polling round. Print the snapshot + a hint."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "abc",
            "status": "completed",
            "title": "T",
            "research_question": "?",
            "methodology": "empirical",
            "mode": "single_pass",
            "workspace": "x",
            "max_cost_usd": 5.0,
            "usage": {},
        }
        with (
            patch("src.cli_status._api_reachable", return_value=True),
            patch("httpx.get", return_value=mock_resp),
            # _poll_status MUST NOT be called when status is already terminal
            patch("src.cli_status._poll_status") as mock_poll,
        ):
            code = status("abc", tail=True)
        assert code == 0
        assert mock_poll.call_count == 0
        captured = capsys.readouterr()
        assert "nothing to wait" in captured.out


# ---------------------------------------------------------------------------
# cancel()
# ---------------------------------------------------------------------------


class TestCancel:
    def _make_lookup(self, status_value: str, title: str = "Test"):
        """Build a httpx-style mock that returns a paper at the named status."""
        mock = MagicMock()
        mock.status_code = 200
        mock.json.return_value = {
            "id": "abc",
            "title": title,
            "status": status_value,
            "usage": {"total_cost_usd": 2.5, "specialist_calls": 3},
        }
        return mock

    def test_api_unreachable_returns_3(self, capsys):
        with patch("src.cli_status._api_reachable", return_value=False):
            code = cancel("abc", yes=True)
        assert code == 3
        assert "unreachable" in capsys.readouterr().err

    def test_404_returns_4(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with (
            patch("src.cli_status._api_reachable", return_value=True),
            patch("httpx.get", return_value=mock_resp),
        ):
            code = cancel("abc", yes=True)
        assert code == 4

    def test_terminal_status_short_circuits_with_message(self, capsys):
        """If the paper is already at a terminal status, cancel is a
        no-op + a clear message rather than a confusing POST that
        returns 409."""
        with (
            patch("src.cli_status._api_reachable", return_value=True),
            patch("httpx.get", return_value=self._make_lookup("completed")),
        ):
            code = cancel("abc", yes=True)
        assert code == 0
        out = capsys.readouterr().out
        assert "already at terminal status" in out
        assert "completed" in out

    def test_confirmation_prompt_n_aborts(self, capsys):
        """Without --yes, the prompt is shown; 'n' aborts and the
        paper is NOT cancelled."""
        with (
            patch("src.cli_status._api_reachable", return_value=True),
            patch("httpx.get", return_value=self._make_lookup("in_progress")),
            patch("builtins.input", return_value="n"),
            patch("httpx.post") as mock_post,
        ):
            code = cancel("abc", yes=False)
        assert code == 0
        assert mock_post.call_count == 0, "POST /cancel must not be called when user declined"
        out = capsys.readouterr().out
        assert "aborted" in out.lower()

    def test_yes_flag_skips_prompt(self):
        post_resp = MagicMock()
        post_resp.status_code = 200
        # Subsequent GETs during the post-cancel poll loop.
        cancelled_resp = MagicMock()
        cancelled_resp.status_code = 200
        cancelled_resp.json.return_value = {"id": "abc", "status": "cancelled"}

        get_responses = [self._make_lookup("in_progress"), cancelled_resp]

        with (
            patch("src.cli_status._api_reachable", return_value=True),
            patch("httpx.get", side_effect=get_responses),
            patch("httpx.post", return_value=post_resp) as mock_post,
            # input() must NOT be called when --yes
            patch("builtins.input", side_effect=AssertionError("prompted despite --yes")),
            patch("time.sleep"),  # don't actually wait in the poll loop
        ):
            code = cancel("abc", yes=True)
        assert code == 0
        # POST was issued
        assert mock_post.call_count == 1
        post_url = mock_post.call_args.args[0]
        assert post_url.endswith("/api/papers/abc/cancel")

    def test_post_404_treated_as_success(self, capsys):
        """Race condition: paper was in_progress when we looked it up,
        finished before we POSTed /cancel. The POST returns 404. From
        the user's perspective the paper is no longer in flight —
        which is what they asked for."""
        post_resp = MagicMock()
        post_resp.status_code = 404

        with (
            patch("src.cli_status._api_reachable", return_value=True),
            patch("httpx.get", return_value=self._make_lookup("in_progress")),
            patch("httpx.post", return_value=post_resp),
            patch("builtins.input", return_value="y"),
            patch("time.sleep"),
        ):
            code = cancel("abc", yes=False)
        assert code == 0
        assert "no longer in flight" in capsys.readouterr().out

    def test_post_non_200_returns_5(self, capsys):
        post_resp = MagicMock()
        post_resp.status_code = 500
        post_resp.text = "internal server error"
        with (
            patch("src.cli_status._api_reachable", return_value=True),
            patch("httpx.get", return_value=self._make_lookup("in_progress")),
            patch("httpx.post", return_value=post_resp),
        ):
            code = cancel("abc", yes=True)
        assert code == 5
        assert "500" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# resume()
# ---------------------------------------------------------------------------


class TestResume:
    def _make_lookup(self, status_value: str, **extras) -> MagicMock:
        mock = MagicMock()
        mock.status_code = 200
        base = {
            "id": "abc",
            "title": "Test",
            "status": status_value,
            "max_cost_usd": 5.0,
            "last_error": None,
            "usage": {"total_cost_usd": 0.0, "specialist_calls": 0},
        }
        base.update(extras)
        mock.json.return_value = base
        return mock

    def _resume_response(self, status: str = "resuming") -> MagicMock:
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {
            "status": status,
            "paper_id": "abc",
            "from_status": "paused",
        }
        return post_resp

    # --- happy paths ---------------------------------------------------------

    def _patch_ensure_api(self, ok: bool = True, err: str | None = None):
        return patch(
            "src.cli_run._ensure_api_up",
            return_value=(ok, err),
        )

    def test_resume_paused_paper_no_cap_change(self, capsys):
        """Common case: paper PAUSED on budget but operator wants to
        retry with the same cap (e.g. circuit-breaker pause).
        Resume body is empty {}; the API uses the row's existing cap."""
        post_resp = self._resume_response()
        with (
            self._patch_ensure_api(ok=True),
            patch("httpx.get", return_value=self._make_lookup("paused")),
            patch("httpx.post", return_value=post_resp) as mock_post,
        ):
            code = resume("abc")
        assert code == 0
        # Body sent was empty dict (no cap change)
        body = mock_post.call_args.kwargs["json"]
        assert body == {}
        out = capsys.readouterr().out
        assert "Resuming" in out
        assert "(unchanged)" in out

    def test_resume_with_raised_cap(self, capsys):
        """Budget-PAUSED paper with --max-cost: the new cap is sent
        in the body and reflected in the user-facing summary."""
        post_resp = self._resume_response()
        with (
            self._patch_ensure_api(ok=True),
            patch(
                "httpx.get",
                return_value=self._make_lookup("paused", max_cost_usd=5.0, last_error="BudgetExceededError: ..."),
            ),
            patch("httpx.post", return_value=post_resp) as mock_post,
        ):
            code = resume("abc", max_cost=15.0)
        assert code == 0
        body = mock_post.call_args.kwargs["json"]
        assert body == {"max_cost_usd": 15.0}
        out = capsys.readouterr().out
        # Cap delta visible
        assert "$5.00 → $15.00" in out
        # last_error gets surfaced so the user knows what was wrong
        assert "BudgetExceededError" in out

    # --- failure / edge paths ------------------------------------------------

    def test_api_unreachable_returns_3(self, capsys):
        with self._patch_ensure_api(ok=False, err="cannot start uvicorn (timeout)"):
            code = resume("abc")
        assert code == 3
        assert "timeout" in capsys.readouterr().err

    def test_404_paper_returns_4(self, capsys):
        not_found = MagicMock()
        not_found.status_code = 404
        with (
            self._patch_ensure_api(ok=True),
            patch("httpx.get", return_value=not_found),
        ):
            code = resume("abc")
        assert code == 4
        assert "not found" in capsys.readouterr().err

    def test_completed_paper_short_circuits_with_message(self, capsys):
        """Cannot resume a completed paper — print a message and exit 0.
        Different from cancelled (which IS resumable per the v0.4
        state-machine softening)."""
        with (
            self._patch_ensure_api(ok=True),
            patch("httpx.get", return_value=self._make_lookup("completed")),
            patch("httpx.post") as mock_post,
        ):
            code = resume("abc")
        assert code == 0
        assert mock_post.call_count == 0, "POST must not be called for a completed paper"
        assert "already completed" in capsys.readouterr().out

    def test_400_validation_error_returns_5(self, capsys):
        """v0.5+ ResumeRequest rejects non-positive max_cost_usd. The
        CLI surfaces the API's detail directly."""
        bad_resp = MagicMock()
        bad_resp.status_code = 400
        bad_resp.json.return_value = {"detail": "max_cost_usd must be positive, got 0.0"}
        bad_resp.text = "bad request"
        with (
            self._patch_ensure_api(ok=True),
            patch("httpx.get", return_value=self._make_lookup("paused")),
            patch("httpx.post", return_value=bad_resp),
        ):
            code = resume("abc", max_cost=0.0)
        assert code == 5
        # The detail message reaches the user
        assert "must be positive" in capsys.readouterr().err

    def test_409_already_running_returns_5_with_cancel_hint(self, capsys):
        """Resume refuses when a paper is already running. The user
        needs to know they can `e2er cancel` first."""
        conflict = MagicMock()
        conflict.status_code = 409
        conflict.json.return_value = {"detail": "A pipeline task is already running for this paper"}
        conflict.text = "conflict"
        with (
            self._patch_ensure_api(ok=True),
            patch("httpx.get", return_value=self._make_lookup("in_progress")),
            patch("httpx.post", return_value=conflict),
        ):
            code = resume("abc")
        assert code == 5
        err = capsys.readouterr().err
        assert "already running" in err
        # And the hint mentioning cancel
        assert "e2er cancel" in err

    def test_other_non_200_returns_5(self, capsys):
        bad = MagicMock()
        bad.status_code = 503
        bad.text = "service unavailable"
        with (
            self._patch_ensure_api(ok=True),
            patch("httpx.get", return_value=self._make_lookup("paused")),
            patch("httpx.post", return_value=bad),
        ):
            code = resume("abc")
        assert code == 5
        assert "503" in capsys.readouterr().err

    def test_tail_flag_invokes_poll(self):
        """With --tail the resume command re-uses _poll_status. Mock
        it to ensure resume hands off correctly without actually
        looping."""
        post_resp = self._resume_response()
        with (
            self._patch_ensure_api(ok=True),
            patch("httpx.get", return_value=self._make_lookup("paused")),
            patch("httpx.post", return_value=post_resp),
            patch("src.cli_status._poll_status", return_value="completed") as mock_poll,
        ):
            code = resume("abc", tail=True, monitor_seconds=60.0)
        assert code == 0
        assert mock_poll.call_count == 1
        # Forwards the monitor budget
        assert mock_poll.call_args.kwargs.get("total_seconds") == 60.0 or mock_poll.call_args.args[1] == 60.0
