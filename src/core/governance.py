"""Governance regimes — which mechanisms BLOCK a run (WS-B).

E2ER's institutions are mechanical: specialist output contracts, the
estimation gate, the numbers gate, the citation gate. The regime decides
which of them *block*:

  * ``full``      — every mechanism blocks (E2ER's default stack)
  * ``contracts`` — only the specialist output contracts block
  * ``off``       — nothing blocks

A mechanism that is not enforced still RUNS. It computes its verdict and
logs a ``gate_shadow`` event instead of a ``gate_enforced`` one, so what the
institutions *would* have caught is measured rather than absent. That
shadowing is what makes the governance experiment's ``off`` cell a real
control: same pipeline, same specialists, same verdicts computed — only the
blocking removed.

The matrix lives here, not on the runner, because enforcement decisions are
made at two levels: the strategist runner (the three deterministic gates)
and the specialist layer (output contracts, the contract-coaching retry, and
the missing-artifact cascade guard). Both must read the same table, or a
regime is only half-applied — which is exactly how ``off`` and ``contracts``
became indistinguishable.

Not governance, and therefore regime-independent: the budget cap, explicit
specialist/backend errors, and the circuit breaker that stops a genuinely
failing specialist from being re-dispatched forever. Those are operational
limits, not verification institutions — no regime should turn them off.
"""

from __future__ import annotations

#: Re-exported so callers reason about check kinds without importing the
#: specialist layer. Defined there because that is where checks are produced.
from .specialists.contract_check import KIND_RELIABILITY, KIND_VERIFICATION  # noqa: F401

REGIMES: tuple[str, ...] = ("off", "contracts", "full")
DEFAULT_REGIME = "full"

#: Every mechanism a regime can switch between blocking and shadow.
GATES: tuple[str, ...] = ("contracts", "estimation", "numbers", "citations")

_ENFORCEMENT: dict[str, frozenset[str]] = {
    "full": frozenset(GATES),
    "contracts": frozenset({"contracts"}),
    "off": frozenset(),
}


def enforces(regime: str, gate: str) -> bool:
    """True iff `gate` should BLOCK under `regime`. Unknown regime → `full`,
    so a typo fails closed (all institutions on) rather than silently open."""
    return gate in _ENFORCEMENT.get(regime, _ENFORCEMENT[DEFAULT_REGIME])


def enforces_check(regime: str, gate: str, kind: str) -> bool:
    """True iff a check of `kind` should BLOCK under `regime`.

    Reliability checks block in EVERY regime, including ``off``. Whether the
    estimation script ran and wrote a parseable non-empty result is a question
    about the pipeline, not about the paper, and the answer is the same in
    every arm of the experiment.

    Conflating the two is what made the ``off`` cell meaningless. In the
    2026-08-05 validation cell the estimation script crashed on a timezone
    comparison and wrote ``{}``; because ``off`` shadowed the artifact check,
    nothing flipped the specialist to failure, the captured traceback was
    never fed back for a retry, and the drafter wrote four tables of invented
    numbers over the hole. The run measured a broken pipeline, not an
    ungoverned one, and fabrication was confounded with completion.
    """
    if kind == KIND_RELIABILITY:
        return True
    return enforces(regime, gate)
