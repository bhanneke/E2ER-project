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
