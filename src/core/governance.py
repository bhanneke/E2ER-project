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
