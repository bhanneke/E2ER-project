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

The paid APIs (OpenRouter, Anthropic) refuse calls for money the same way: no
credits left, or the key's spending limit used up. :func:`detect_billing`
recognises them and the run pauses the same way (``paused_billing_limit``),
with a sentence that says what to do.
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

    #: The event the runner records for the pause.
    event = "paused_plan_limit"

    def __init__(self, backend: str, message: str, resets: str | None = None, specialist: str | None = None) -> None:
        self.backend = backend
        self.message = message
        self.resets = resets
        self.specialist = specialist
        #: The sentence the dashboard and `e2er status` show.
        self.status = status_text(backend, resets)
        super().__init__(self.status)


class BillingLimitReachedError(PlanLimitReachedError):
    """A paid API refuses calls for money: the account has no credits, or the key's spending limit is used up.

    Live, 2026-10-14 (the earthquake demo on OpenRouter): "Error code: 402 -
    This request requires more credits, or fewer max_tokens. You requested up
    to 32768 tokens, but can only afford 14986. ... adjust the key's total
    limit", during a send-back at the draft review; the run went back to the
    same stop with no error shown. Like a plan's limit nothing is broken and
    every call fails the same way until the researcher acts: the run pauses
    (``paused_billing_limit``), no attempt is counted, and Resume runs the
    interrupted specialist again. ``status`` says what to do.
    """

    event = "paused_billing_limit"

    def __init__(self, backend: str, message: str, status: str, specialist: str | None = None) -> None:
        super().__init__(backend, message, None, specialist)
        self.status = status
        self.args = (status,)


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


#: The end of every billing-limit status sentence (see :func:`detect_billing`).
BILLING_TAIL = "or choose another AI provider, then press Resume."

_OPENROUTER_KEY_LIMIT = (
    "The OpenRouter key's spending limit is reached. Raise it at openrouter.ai or choose another AI provider, "
    "then press Resume."
)
_OPENROUTER_CREDITS = (
    "The OpenRouter account has no credits left. Add credits at openrouter.ai or choose another AI provider, "
    "then press Resume."
)
_ANTHROPIC_CREDITS = (
    "The Anthropic API account's credit balance is too low. Add credits at console.anthropic.com or choose "
    "another AI provider, then press Resume."
)
_ANTHROPIC_LIMIT = (
    "The Anthropic API key's usage limit is reached. Raise it at console.anthropic.com or choose another AI "
    "provider, then press Resume."
)

#: (marker, status) per paid API, the first marker that matches wins. The wording is the APIs' own:
#: OpenRouter answers 402 ("Insufficient credits", "This request requires more credits ... can only afford
#: ...", with ``limit_source: openrouter_key_limit`` when the key's own limit is the cause, "Key limit
#: exceeded"); Anthropic answers 400 "Your credit balance is too low to access the Anthropic API" and "You
#: have reached your specified API usage limits".
_BILLING: dict[str, tuple[tuple[re.Pattern[str], str], ...]] = {
    "openrouter": (
        (re.compile(r"openrouter_key_limit|key limit exceeded|key's (?:total )?limit|key's spending limit"),
         _OPENROUTER_KEY_LIMIT),
        (re.compile(r"insufficient credits|requires more credits|can only afford|error code: 402\b|\b402 payment"),
         _OPENROUTER_CREDITS),
    ),
    "anthropic": (
        (re.compile(r"credit balance is too low"), _ANTHROPIC_CREDITS),
        (re.compile(r"reached your specified api usage limits?"), _ANTHROPIC_LIMIT),
    ),
}  # fmt: skip


def detect_billing(backend: str, text: str) -> BillingLimitReachedError | None:
    """A paid API's refusal for money in an error text (no credits, the key's limit), or None."""
    if not text:
        return None
    low = _norm(text)
    for pattern, status in _BILLING.get(backend, ()):
        if pattern.search(low):
            return BillingLimitReachedError(backend, text.strip()[:2000], status)
    return None


async def raise_if_billing(
    backend: str, model: str, result: object, paper_id: str | None, specialist: str | None
) -> None:
    """Raise :class:`BillingLimitReachedError` when a failed tool loop's error is a refusal for money.

    What the loop used before the refusal was billed: it is recorded first,
    because the runner records a loop's usage only when the loop returns.
    """
    if getattr(result, "success", True):
        return
    limit = detect_billing(backend, str(getattr(result, "error", "") or ""))
    if limit is None:
        return
    from ..tracking.usage import record_cancelled_loop

    await record_cancelled_loop(paper_id, specialist, backend, model, getattr(result, "usage", None))
    limit.specialist = specialist
    raise limit


def is_plan_limit_status(text: str | None) -> bool:
    """Whether a stored status text (a paper's ``last_error``) is a plan-limit or billing-limit pause."""
    return bool(text) and (PAUSE_TAIL in str(text) or BILLING_TAIL in str(text))
