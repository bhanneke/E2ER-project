"""p-values follow from the test statistic.

A results file states, per coefficient, an estimate, a standard error, a t
statistic and a p-value. They are not four facts but one: t is the estimate
over its standard error, and the p-value is the tail probability of t under
the stated distribution. A model that writes the four numbers can get the
relation wrong (the FOMC demonstration study reported t = -2.00 with 20
events and p = 0.32; the two-sided p is 0.06), and nothing downstream
notices, because every number in the paper traces to the file.

This check recomputes the relation for every coefficient that states them:

  (a) t equals estimate / se, allowing for the rounding of all three;
  (b) the p-value equals the two-sided (or declared one-sided) tail
      probability of t with the stated degrees of freedom, within 0.005, or
      within half a unit of the declared rounding (``p_value_decimals``).

Degrees of freedom, in order: ``df`` on the coefficient, the entry or its
diagnostics; for standard errors clustered on G groups, anything from t with
G - 1 df to the normal (software differs); ``df_residual``; n - k when the
entry states ``n_parameters`` (or ``k``); n - 1 for a one-sample mean test
(one coefficient, a test of a mean). When none is known the p-value must lie
in the band between the normal approximation and the t distribution with the
fewest degrees of freedom the entry allows, and the check says df was
unknown. A coefficient whose p-value does not come from t (``p_value_method``
such as "bootstrap" or "permutation") is left out, and listed.

scipy is not a dependency, so the t distribution is computed here from the
regularized incomplete beta function (Lentz's continued fraction); the tests
compare it with closed forms and published critical values.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

#: Default absolute tolerance on a p-value.
P_TOLERANCE = 0.005
#: Relative slack on t beyond the rounding of estimate, se and t.
T_REL_TOLERANCE = 0.01
#: p-value methods that are the t or normal tail and so are checked.
_ANALYTIC = frozenset({"", "t", "student_t", "students_t", "normal", "z", "wald", "analytic"})
_MEAN_TEST = re.compile(r"t-?test|one[- ]sample|mean", re.IGNORECASE)

_EPS = 3e-16
_FPMIN = 1e-300


# ── the t distribution ──────────────────────────────────────────────────────


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (modified Lentz)."""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < _FPMIN:
        d = _FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, 100_000):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = _FPMIN if abs(d) < _FPMIN else d
        c = 1.0 + aa / c
        c = _FPMIN if abs(c) < _FPMIN else c
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = _FPMIN if abs(d) < _FPMIN else d
        c = 1.0 + aa / c
        c = _FPMIN if abs(c) < _FPMIN else c
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            return h
    raise ArithmeticError(f"incomplete beta did not converge (a={a}, b={b}, x={x})")


def betainc(a: float, b: float, x: float) -> float:
    """The regularized incomplete beta function I_x(a, b)."""
    if not (a > 0 and b > 0):
        raise ValueError("a and b must be positive")
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_front = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    front = math.exp(ln_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def normal_two_sided_p(t: float) -> float:
    return math.erfc(abs(t) / math.sqrt(2.0))


def t_two_sided_p(t: float, df: float | None) -> float:
    """P(|T| >= |t|) for Student's t with ``df`` degrees of freedom (None or inf: normal)."""
    if df is None or math.isinf(df):
        return normal_two_sided_p(t)
    if df <= 0:
        raise ValueError("degrees of freedom must be positive")
    return betainc(df / 2.0, 0.5, df / (df + t * t))


def t_sf(t: float, df: float | None) -> float:
    """P(T >= t), the upper tail."""
    half = t_two_sided_p(t, df) / 2.0
    return half if t >= 0 else 1.0 - half


def p_from_t(t: float, df: float | None, alternative: str = "two-sided") -> float:
    if alternative == "greater":
        return t_sf(t, df)
    if alternative == "less":
        return t_sf(-t, df)
    return t_two_sided_p(t, df)


# ── the check ───────────────────────────────────────────────────────────────


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def _half_unit(v: float) -> float:
    """Half a unit in the last printed decimal of a JSON number (0 for full-precision floats)."""
    text = repr(v)
    if "e" in text or "E" in text:
        mantissa, exp = text.lower().split("e")
        decimals = len(mantissa.split(".", 1)[1]) if "." in mantissa else 0
        return 0.5 * 10.0 ** (int(exp) - decimals)
    decimals = len(text.split(".", 1)[1].rstrip("0")) if "." in text else 0
    return 0.5 * 10.0 ** (-decimals) if decimals < 10 else 0.0


def _int(v: Any) -> int | None:
    f = _num(v)
    return int(f) if f is not None and f == int(f) and f > 0 else None


def _alternative(coef: dict[str, Any], entry: dict[str, Any]) -> str:
    raw = str(coef.get("alternative") or entry.get("alternative") or "").lower().replace("_", "-")
    sided = coef.get("sided", entry.get("sided"))
    if raw in ("greater", "less"):
        return raw
    if raw in ("one-sided", "one") or sided in (1, "one", "one-sided"):
        # A one-sided test in the direction of the estimate.
        return "greater" if (_num(coef.get("t_stat")) or _num(coef.get("estimate")) or 0) >= 0 else "less"
    return "two-sided"


@dataclass
class _DF:
    value: float | None  # a single df; None: a band
    basis: str
    band_min: float | None = None  # the band runs from t with band_min df to the normal
    unknown: bool = False


def _clustered(entry: dict[str, Any]) -> int | None:
    level = str(entry.get("cluster_level") or "").strip().lower()
    clusters = _int(entry.get("n_clusters"))
    return clusters if clusters and clusters > 1 and level not in ("", "none") else None


def _degrees_of_freedom(name: str, coef: dict[str, Any], entry: dict[str, Any]) -> _DF:
    diag: dict[str, Any] = entry["diagnostics"] if isinstance(entry.get("diagnostics"), dict) else {}
    # An inference df stated for the test itself.
    for holder, where in ((coef, "coefficient"), (entry, "entry"), (diag, "diagnostics")):
        v = _num(holder.get("df"))
        if v is not None and v > 0:
            return _DF(v, f"df on the {where}")
    # Clustered standard errors: software uses t with G - 1 df (Stata, fixest,
    # statsmodels) or the normal (linearmodels), so both ends are accepted.
    clusters = _clustered(entry)
    if clusters:
        return _DF(None, f"clustered on {clusters} groups", band_min=float(clusters - 1))
    for holder, where in ((coef, "coefficient"), (entry, "entry"), (diag, "diagnostics")):
        for key in ("df_residual", "df_resid"):
            v = _num(holder.get(key))
            if v is not None and v > 0:
                return _DF(v, f"{key} on the {where}")
    n = _int(entry.get("n_observations")) or _int(entry.get("n_events")) or _int(diag.get("n_observations"))
    k = _int(entry.get("n_parameters")) or _int(entry.get("k"))
    if n and k and n > k:
        return _DF(float(n - k), f"n - k = {n} - {k}")
    coefs: dict[str, Any] = entry["coefficients"] if isinstance(entry.get("coefficients"), dict) else {}
    text = " ".join(str(entry.get(k_) or "") for k_ in ("method", "specification", "test", "estimator"))
    if n and n > 1 and len(coefs) == 1 and (_MEAN_TEST.search(text) or name.lower().startswith("mean")):
        return _DF(float(n - 1), f"n - 1 = {n} - 1 (one-sample mean test)")
    band_min = float(max(1, n - len(coefs) - 1)) if n else 1.0
    return _DF(None, "df unknown", band_min=band_min, unknown=True)


@dataclass
class StatisticsReport:
    checked: int = 0
    problems: list[str] = field(default_factory=list)
    df_unknown: list[str] = field(default_factory=list)
    not_analytic: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def summary(self) -> str:
        bits = [f"{self.checked} coefficient(s) checked, {len(self.problems)} inconsistent"]
        if self.df_unknown:
            shown = ", ".join(self.df_unknown[:5]) + (" …" if len(self.df_unknown) > 5 else "")
            bits.append(f"df unknown for {len(self.df_unknown)} (checked against a band): {shown}")
        if self.not_analytic:
            bits.append(f"{len(self.not_analytic)} with a non-analytic p-value left out")
        return "; ".join(bits)


def _entries(obj: Any, path: str = "") -> list[tuple[str, dict[str, Any]]]:
    """Every object with a ``coefficients`` dict, with its dotted path."""
    out: list[tuple[str, dict[str, Any]]] = []
    if isinstance(obj, dict):
        if isinstance(obj.get("coefficients"), dict):
            out.append((path or "(top level)", obj))
        for k, v in obj.items():
            if k != "coefficients":
                out += _entries(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += _entries(v, f"{path}[{i}]")
    return out


def _decimals_declared(coef: dict[str, Any], entry: dict[str, Any], doc: dict[str, Any]) -> int | None:
    """Declared rounding of p-values: ``p_value_decimals`` on the coefficient or
    entry, or ``{"rounding": {"p_value": 2}}`` at the top of the file."""
    rounding: dict[str, Any] = doc["rounding"] if isinstance(doc.get("rounding"), dict) else {}
    for v in (coef.get("p_value_decimals"), entry.get("p_value_decimals"), rounding.get("p_value")):
        if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 12:
            return v
    return None


def check_coefficient(
    label: str, name: str, coef: dict[str, Any], entry: dict[str, Any], doc: dict[str, Any], report: StatisticsReport
) -> None:
    est, se, t, p = (_num(coef.get(k)) for k in ("estimate", "se", "t_stat", "p_value"))
    if se is None:
        se = _num(coef.get("std_error"))
    if t is None:
        t = _num(coef.get("t"))
    if est is None or se is None or t is None or p is None or se <= 0:
        return
    where = f"{label}.{name}"
    method = str(coef.get("p_value_method") or entry.get("p_value_method") or "").lower()
    if method not in _ANALYTIC:
        report.not_analytic.append(where)
        return
    report.checked += 1

    # (a) t = estimate / se, with the rounding of all three.
    # A t printed with fewer than two decimals is taken at two: "2.0" is 2.00.
    de, ds, dt = _half_unit(est), _half_unit(se), min(_half_unit(t), 0.005)
    ratios = [(est + a) / (se + b) for a in (-de, de) for b in (-ds, ds) if se + b > 0]
    lo, hi = min(ratios), max(ratios)
    slack = T_REL_TOLERANCE * max(abs(t), 1.0) + dt
    if not (lo - slack <= t <= hi + slack):
        report.problems.append(f"{where}: t_stat {t:g} is not estimate / se ({est:g} / {se:g} = {est / se:.4g})")
        return

    # (b) p from t.
    decimals = _decimals_declared(coef, entry, doc)
    tol = max(P_TOLERANCE, 0.5 * 10.0 ** (-decimals)) if decimals is not None else P_TOLERANCE
    alt = _alternative(coef, entry)
    df = _degrees_of_freedom(name, coef, entry)
    t_lo, t_hi = abs(t) - dt, abs(t) + dt
    sign = 1.0 if t >= 0 else -1.0
    if df.value is not None:
        ps = [p_from_t(sign * x, df.value, alt) for x in (max(t_lo, 0.0), t_hi)]
        basis = f"t with {df.value:g} df ({df.basis})"
    else:
        if df.unknown:
            report.df_unknown.append(where)
        ps = [p_from_t(sign * x, d, alt) for x in (max(t_lo, 0.0), t_hi) for d in (None, df.band_min)]
        basis = f"t with {df.band_min:g} df to the normal ({df.basis})"
    p_lo, p_hi = min(ps), max(ps)
    if not (p_lo - tol <= p <= p_hi + tol):
        want = f"{p_lo:.4f}" if abs(p_hi - p_lo) < 5e-5 else f"{p_lo:.4f} to {p_hi:.4f}"
        side = "" if alt == "two-sided" else f" ({alt}, one-sided)"
        report.problems.append(f"{where}: p_value {p:g} does not follow from t = {t:.4g}{side}: {basis} gives {want}")


def check_statistics(docs: list[tuple[str, Any]]) -> StatisticsReport:
    """Check every coefficient of the given results files: [(file name, parsed JSON)]."""
    report = StatisticsReport()
    for fname, doc in docs:
        if not isinstance(doc, dict):
            continue
        for path, entry in _entries(doc):
            for name, coef in entry["coefficients"].items():
                if isinstance(coef, dict):
                    check_coefficient(f"{fname}#{path}", str(name), coef, entry, doc, report)
    return report
