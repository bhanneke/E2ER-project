"""A subscription CLI says its plan's usage limit is reached: the run pauses, it does not fail.

Codex (a ChatGPT plan), Claude Code (a Claude plan) and the Gemini CLI run on
the researcher's own sign-in. When that plan's limit is used up, every call
fails the same way until the limit resets, so retrying is pointless and
failing the run is wrong: nothing is broken. The backend raises
:class:`PlanLimitReachedError`; the runner pauses the run (``paused_plan_limit``)
with a plain sentence, and Resume runs the interrupted specialist again.

The wording recognised here is the CLIs' own, as seen live:

* Codex: "You’ve hit your usage limit. Upgrade to Pro (…), visit … or try
  again at 2:30 PM." (2026-10-11, e2er 0.15.2), ``usage_limit_reached``.
* Claude Code: "Claude AI usage limit reached|1760190000" (a Unix time),
  "Claude usage limit reached. Your limit will reset at 2pm (Europe/Berlin).",
  "5-hour limit reached ∙ resets 3pm", "You've hit your limit · resets 2pm",
  "Weekly limit reached ∙ resets Oct 14, 9am", "Opus weekly limit reached".
* Gemini CLI: "You have exhausted your daily quota …", "Quota exceeded for
  quota metric '… per day …'". A per-minute rate limit is not one of them.
"""

from __future__ import annotations

import re
from datetime import datetime

#: What each backend's limit is called in the status sentence.
_LIMIT_NAMES = {
    "codex": "Your ChatGPT plan's usage limit",
    "claude_code": "Your Claude plan's usage limit",
    "gemini": "Your Gemini usage limit",
}

#: The end of every plan-limit status sentence: how the dashboard and `e2er status` recognise it.
PAUSE_TAIL = "The run is paused; press Resume when the limit has reset."

_MARKERS: dict[str, tuple[re.Pattern[str], ...]] = {
    "codex": (
        re.compile(r"hit your usage limit"),
        re.compile(r"usage_limit_reached"),
        re.compile(r"usage limit (?:has been )?reached"),
    ),
    "claude_code": (
        re.compile(r"claude(?: ai)? usage limit reached"),
        re.compile(r"\busage limit reached"),
        re.compile(r"hit your (?:usage )?limit"),
        re.compile(r"\b(?:5-hour|five-hour|session|daily|weekly|opus|sonnet)(?: weekly)? limit reached"),
        re.compile(r"limit will reset at"),
    ),
    "gemini": (
        re.compile(r"exhausted your daily quota"),
        re.compile(r"quota exceeded for quota metric[^\n]*per ?day"),
        re.compile(r"daily (?:request )?(?:quota|limit) (?:exceeded|reached)"),
    ),
}

_UNIX = re.compile(r"limit reached\s*\|\s*(\d{10})\b")
_RESETS = re.compile(r"\bresets?\s+(?:at\s+|on\s+)?([^.·∙|\n]+?)\s*(?:[.·∙|\n]|$)", re.I)
_TRY_AGAIN = re.compile(r"\btry again (at|in|after)\s+([^\n]+?)\s*(?:\.(?:\s|$)|$)", re.I)


class PlanLimitReachedError(Exception):
    """The CLI's subscription plan has reached its usage limit; calls fail until it resets.

    ``backend`` is the e2er backend (``codex``, ``claude_code``, ``gemini``),
    ``resets`` when the limit resets as the CLI said it (``at 14:30``,
    ``in 2 hours``), or None when it did not say; ``specialist`` is set by the
    dispatcher to the specialist whose call hit the limit.
    """

    def __init__(self, backend: str, message: str, resets: str | None = None, specialist: str | None = None) -> None:
        self.backend = backend
        self.message = message
        self.resets = resets
        self.specialist = specialist
        super().__init__(status_text(backend, resets))


def _norm(text: str) -> str:
    return text.replace("’", "'").replace("‘", "'").lower()


def _local_time(ts: int) -> str:
    when = datetime.fromtimestamp(ts)
    return when.strftime("%H:%M") if when.date() == datetime.now().date() else when.strftime("%d %b %H:%M")


def reset_time(text: str) -> str | None:
    """When the limit resets, as the CLI said it (``at 14:30``, ``in 2 hours``), or None.

    A time zone in brackets becomes a comma (``at 2pm, Europe/Berlin``): the
    status sentence puts the whole phrase in brackets already.
    """
    when = _reset_phrase(text)
    return re.sub(r"\s*\(([^()]*)\)", r", \1", when).strip() if when else None


def _reset_phrase(text: str) -> str | None:
    if m := _UNIX.search(text):
        return f"at {_local_time(int(m.group(1)))}"
    if m := _TRY_AGAIN.search(text):
        prep = m.group(1).lower()
        return f"{'at' if prep == 'after' else prep} {m.group(2).strip()}"
    if m := _RESETS.search(text):
        when = m.group(1).strip().rstrip(",;")
        # "resets in 2 hours" keeps its "in"; a bare time or date is "at" it.
        return when if when.lower().startswith("in ") else f"at {when}"
    return None


def detect(backend: str, text: str) -> PlanLimitReachedError | None:
    """The plan-limit error in a CLI's output, or None when the text is about something else."""
    if not text:
        return None
    low = _norm(text)
    if not any(p.search(low) for p in _MARKERS.get(backend, ())):
        return None
    resets = reset_time(text.replace("’", "'"))
    return PlanLimitReachedError(backend, text.strip()[:2000], resets)


def status_text(backend: str, resets: str | None = None) -> str:
    """The sentence the dashboard and `e2er status` show for a run paused at its plan's limit."""
    what = _LIMIT_NAMES.get(backend, "Your AI provider's usage limit")
    return f"{what} is reached{f' (resets {resets})' if resets else ''}. {PAUSE_TAIL}"


def is_plan_limit_status(text: str | None) -> bool:
    """Whether a stored status text (a paper's ``last_error``) is a plan-limit pause."""
    return bool(text) and PAUSE_TAIL in str(text)
