"""Random-effects meta-analysis: effect sizes, pooling, heterogeneity, small-study checks.

Standard library, numpy and scipy only, and no import from e2er: the synthesis
step copies this file's source into the study's ``run_estimation.py``, so that
``e2er reproduce`` reruns the same code without e2er installed.

Methods (the template credits them):

- Effect sizes on the analysis scale: ratios (OR, RR, HR) on the log scale;
  correlations as Fisher's z; standardised mean differences as Hedges' g from
  group means and standard deviations when no SMD is printed. A standard error
  printed by the study is used as printed; otherwise it follows from the
  confidence interval (on the analysis scale) or from the group sizes.
- Between-study variance tau^2 by restricted maximum likelihood (REML, Fisher
  scoring as in Viechtbauer 2005 and metafor) or by DerSimonian and Laird (1986).
- Pooled estimate, its standard error, z, p and a normal confidence interval;
  Cochran's Q; I^2 = tau^2 / (tau^2 + s^2) with s^2 the typical within-study
  variance (Higgins and Thompson 2002; equal to (Q - df) / Q under DL);
  H^2; a prediction interval with t on k - 2 degrees of freedom (Riley,
  Higgins and Deeks 2011).
- Egger's regression test (Egger et al. 1997): the standardised effect on the
  precision, OLS, the intercept tested with t on k - 2 degrees of freedom.
- Trim and fill (Duval and Tweedie 2000), estimator L0, with the side of the
  missing studies taken from the sign of Egger's intercept.
- Leave-one-out: the pooled estimate without each study in turn.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy import stats as _st

#: Effect measures and how they are pooled.
RATIO_MEASURES = ("OR", "RR", "HR")
LOG_MEASURES = ("logOR", "logRR", "logHR")
DIFFERENCE_MEASURES = ("SMD", "MD", "RD", "generic")
CORRELATION_MEASURES = ("r",)
MEASURES = (*RATIO_MEASURES, *LOG_MEASURES, *DIFFERENCE_MEASURES, *CORRELATION_MEASURES)
TAU2_METHODS = ("REML", "DL")


class EffectError(ValueError):
    """An extracted effect that cannot be put on the analysis scale."""


def _f(x: Any) -> float | None:
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _zcrit(level: float) -> float:
    return float(_st.norm.ppf(0.5 + level / 2.0))


def analysis_scale(measure: str) -> str:
    """The scale effects of ``measure`` are pooled on."""
    if measure in RATIO_MEASURES:
        return f"log {measure}"
    if measure in CORRELATION_MEASURES:
        return "Fisher's z"
    return measure


def back_transform(measure: str, value: float) -> float:
    """A pooled value on the analysis scale, in the measure the studies report."""
    if measure in RATIO_MEASURES:
        return math.exp(value)
    if measure in CORRELATION_MEASURES:
        return math.tanh(value)
    return value


def hedges_g(m1: float, sd1: float, n1: float, m2: float, sd2: float, n2: float) -> tuple[float, float]:
    """Hedges' g and its sampling variance from group means, standard deviations and sizes."""
    if n1 < 2 or n2 < 2 or sd1 <= 0 or sd2 <= 0:
        raise EffectError("group sizes of at least 2 and positive standard deviations are needed for Hedges' g")
    df = n1 + n2 - 2
    sp = math.sqrt(((n1 - 1) * sd1**2 + (n2 - 1) * sd2**2) / df)
    d = (m1 - m2) / sp
    j = 1.0 - 3.0 / (4.0 * df - 1.0)
    g = j * d
    v = j**2 * ((n1 + n2) / (n1 * n2) + d**2 / (2.0 * (n1 + n2)))
    return g, v


def effect_on_scale(effect: dict[str, Any], measure: str) -> tuple[float, float, str]:
    """(yi, vi, how) for one study's extracted effect.

    ``effect`` holds what the study prints: ``value`` with ``se`` or with
    ``ci_lower``/``ci_upper`` (and ``ci_level``, default 0.95), a correlation
    ``value`` with ``n``, an SMD with ``n1``/``n2``, or group statistics
    ``mean1``, ``sd1``, ``n1``, ``mean2``, ``sd2``, ``n2`` (an SMD as Hedges' g).
    """
    if measure not in MEASURES:
        raise EffectError(f"unknown effect measure {measure!r} (known: {', '.join(MEASURES)})")
    value, se = _f(effect.get("value")), _f(effect.get("se"))
    lo, hi = _f(effect.get("ci_lower")), _f(effect.get("ci_upper"))
    level = _f(effect.get("ci_level")) or 0.95
    if not 0 < level < 1:
        raise EffectError("ci_level must be a share between 0 and 1 (e.g. 0.95)")
    n, n1, n2 = _f(effect.get("n")), _f(effect.get("n1")), _f(effect.get("n2"))
    groups = [_f(effect.get(k)) for k in ("mean1", "sd1", "n1", "mean2", "sd2", "n2")]

    if measure == "SMD" and value is None and all(g is not None for g in groups):
        m1, sd1, gn1, m2, sd2, gn2 = (float(g) for g in groups)  # type: ignore[arg-type]
        g, v = hedges_g(m1, sd1, gn1, m2, sd2, gn2)
        return g, v, "Hedges' g from group means, SDs and sizes"
    if value is None:
        raise EffectError("no effect value (and no group means, SDs and sizes for an SMD)")

    if measure in CORRELATION_MEASURES:
        if not -1 < value < 1:
            raise EffectError(f"a correlation must lie between -1 and 1, not {value}")
        if n is None or n <= 3:
            raise EffectError("a correlation needs the sample size n (more than 3)")
        return math.atanh(value), 1.0 / (n - 3.0), "Fisher's z of r, variance 1/(n - 3)"

    if measure in RATIO_MEASURES:
        if value <= 0:
            raise EffectError(f"a ratio must be positive, not {value}")
        y = math.log(value)
        if se is not None:
            # A printed SE of a ratio is the SE of its logarithm (as regression output prints it).
            return y, se**2, f"log {measure}, SE as printed (log scale)"
        if lo is not None and hi is not None:
            if not 0 < lo < hi:
                raise EffectError("the confidence interval of a ratio needs 0 < lower < upper")
            s = (math.log(hi) - math.log(lo)) / (2.0 * _zcrit(level))
            return y, s**2, f"log {measure}, SE from the {level:.0%} CI"
        raise EffectError(f"a {measure} needs a standard error or a confidence interval")

    y = value
    if se is not None:
        if se <= 0:
            raise EffectError("a standard error must be positive")
        return y, se**2, "SE as printed"
    if lo is not None and hi is not None:
        if not lo < hi:
            raise EffectError("the confidence interval needs lower < upper")
        s = (hi - lo) / (2.0 * _zcrit(level))
        return y, s**2, f"SE from the {level:.0%} CI"
    if measure == "SMD" and n1 is not None and n2 is not None and n1 > 1 and n2 > 1:
        v = (n1 + n2) / (n1 * n2) + y**2 / (2.0 * (n1 + n2))
        return y, v, "SMD variance from n1 and n2"
    raise EffectError("the effect needs a standard error, a confidence interval or (for an SMD) group sizes")


# ── tau^2 ───────────────────────────────────────────────────────────────────


def _fixed(y: np.ndarray, v: np.ndarray) -> tuple[float, float, float]:
    w = 1.0 / v
    mu = float(np.sum(w * y) / np.sum(w))
    q = float(np.sum(w * (y - mu) ** 2))
    return mu, float(math.sqrt(1.0 / np.sum(w))), q


def tau2_dl(y: np.ndarray, v: np.ndarray) -> float:
    """DerSimonian and Laird's method-of-moments estimate of tau^2."""
    k = len(y)
    if k < 2:
        return 0.0
    w = 1.0 / v
    _, _, q = _fixed(y, v)
    c = float(np.sum(w) - np.sum(w**2) / np.sum(w))
    return max(0.0, (q - (k - 1)) / c)


def tau2_reml(y: np.ndarray, v: np.ndarray, *, tol: float = 1e-10, max_iter: int = 100) -> tuple[float, bool]:
    """REML estimate of tau^2 by Fisher scoring with step halving (as metafor); (tau2, converged)."""
    k = len(y)
    if k < 2:
        return 0.0, True
    tau2 = tau2_dl(y, v)
    for _ in range(max_iter):
        w = 1.0 / (v + tau2)
        sw = float(np.sum(w))
        mu = float(np.sum(w * y) / sw)
        py = w * (y - mu)
        tr_p = sw - float(np.sum(w**2)) / sw
        tr_pp = float(np.sum(w**2)) - 2.0 * float(np.sum(w**3)) / sw + (float(np.sum(w**2)) / sw) ** 2
        adj = (float(np.sum(py**2)) - tr_p) / tr_pp
        while tau2 + adj < 0:
            adj /= 2.0
            if abs(adj) < tol:
                adj = -tau2
                break
        tau2 += adj
        if abs(adj) < tol:
            return max(0.0, tau2), True
    return max(0.0, tau2), False


def estimate_tau2(y: np.ndarray, v: np.ndarray, method: str) -> tuple[float, bool]:
    if method == "DL":
        return tau2_dl(y, v), True
    if method == "REML":
        return tau2_reml(y, v)
    raise ValueError(f"unknown tau2 method {method!r} (known: {', '.join(TAU2_METHODS)})")


# ── pooling ─────────────────────────────────────────────────────────────────


def pool(y: Any, v: Any, *, method: str = "REML", level: float = 0.95) -> dict[str, Any]:
    """The random-effects meta-analysis of effects ``y`` with sampling variances ``v``."""
    y = np.asarray(y, dtype=float)
    v = np.asarray(v, dtype=float)
    k = len(y)
    if k == 0:
        raise ValueError("no studies to pool")
    if np.any(v <= 0):
        raise ValueError("every sampling variance must be positive")
    tau2, converged = estimate_tau2(y, v, method)
    w = 1.0 / (v + tau2)
    sw = float(np.sum(w))
    mu = float(np.sum(w * y) / sw)
    se = math.sqrt(1.0 / sw)
    z = mu / se
    zc = _zcrit(level)
    fe_mu, fe_se, q = _fixed(y, v)
    df = k - 1
    wf = 1.0 / v
    # Typical within-study variance (Higgins and Thompson 2002, eq. 9).
    s2 = df * float(np.sum(wf)) / (float(np.sum(wf)) ** 2 - float(np.sum(wf**2))) if k > 1 else float(v[0])
    i2 = 100.0 * tau2 / (tau2 + s2) if k > 1 else 0.0
    h2 = (tau2 + s2) / s2 if k > 1 else 1.0
    out: dict[str, Any] = {
        "k": k,
        "estimate": mu,
        "se": se,
        "z": z,
        "p_value": float(2.0 * _st.norm.sf(abs(z))),
        "ci_lower": mu - zc * se,
        "ci_upper": mu + zc * se,
        "tau2": tau2,
        "tau": math.sqrt(tau2),
        "tau2_method": method,
        "tau2_converged": converged,
        "i2": i2,
        "h2": h2,
        "q": q,
        "q_df": df,
        "q_p_value": float(_st.chi2.sf(q, df)) if df > 0 else None,
        "weights_percent": [float(x) for x in 100.0 * w / sw],
        "fixed_effect": {
            "estimate": fe_mu,
            "se": fe_se,
            "ci_lower": fe_mu - zc * fe_se,
            "ci_upper": fe_mu + zc * fe_se,
        },
    }
    if k >= 3:
        tc = float(_st.t.ppf(0.5 + level / 2.0, k - 2))
        half = tc * math.sqrt(tau2 + se**2)
        out["prediction_interval"] = {"lower": mu - half, "upper": mu + half, "df": k - 2}
    else:
        out["prediction_interval"] = None
    return out


def egger(y: Any, v: Any) -> dict[str, Any]:
    """Egger's regression test: y/se on 1/se by OLS; the intercept's t test on k - 2 df."""
    y = np.asarray(y, dtype=float)
    se = np.sqrt(np.asarray(v, dtype=float))
    k = len(y)
    if k < 3:
        return {"skipped": f"needs at least 3 studies, has {k}"}
    snd = y / se
    prec = 1.0 / se
    x = np.column_stack([np.ones(k), prec])
    beta, *_ = np.linalg.lstsq(x, snd, rcond=None)
    resid = snd - x @ beta
    df = k - 2
    if df <= 0:
        return {"skipped": "no degrees of freedom left"}
    sigma2 = float(np.sum(resid**2)) / df
    cov = sigma2 * np.linalg.inv(x.T @ x)
    b0, se0 = float(beta[0]), float(math.sqrt(cov[0, 0]))
    t = b0 / se0 if se0 > 0 else float("inf")
    return {
        "intercept": b0,
        "se": se0,
        "t": t,
        "df": df,
        "p_value": float(2.0 * _st.t.sf(abs(t), df)),
        "slope": float(beta[1]),
    }


def trim_and_fill(y: Any, v: Any, *, method: str = "REML", level: float = 0.95, side: str = "") -> dict[str, Any]:
    """Duval and Tweedie's trim and fill, estimator L0 (iterated until the number to trim is stable)."""
    y = np.asarray(y, dtype=float)
    v = np.asarray(v, dtype=float)
    k = len(y)
    if k < 3:
        return {"skipped": f"needs at least 3 studies, has {k}"}
    if not side:
        e = egger(y, v)
        side = "left" if e.get("intercept", 0.0) > 0 else "right"
    sign = 1.0 if side == "left" else -1.0
    # Work as if the missing studies were on the left: flip for the right.
    ys = sign * y
    order = np.argsort(ys)
    ys, vs = ys[order], v[order]
    k0 = 0
    for _ in range(100):
        trimmed_y, trimmed_v = ys[: k - k0], vs[: k - k0]
        mu = pool(trimmed_y, trimmed_v, method=method, level=level)["estimate"]
        dev = ys - mu
        ranks = _st.rankdata(np.abs(dev))
        tn = float(np.sum(ranks[dev > 0]))
        l0 = (4.0 * tn - k * (k + 1)) / (2.0 * k - 1.0)
        new = max(0, int(round(l0)))
        new = min(new, k - 2)
        if new == k0:
            break
        k0 = new
    trimmed_y, trimmed_v = ys[: k - k0], vs[: k - k0]
    mu = pool(trimmed_y, trimmed_v, method=method, level=level)["estimate"]
    filled_y = 2.0 * mu - ys[k - k0 :]
    all_y = np.concatenate([ys, filled_y]) * sign
    all_v = np.concatenate([vs, vs[k - k0 :]])
    res = pool(all_y, all_v, method=method, level=level)
    return {
        "k0": k0,
        "side": side,
        "estimator": "L0",
        "estimate": res["estimate"],
        "se": res["se"],
        "ci_lower": res["ci_lower"],
        "ci_upper": res["ci_upper"],
        "tau2": res["tau2"],
        "filled": [float(x) for x in filled_y * sign],
        "filled_se": [float(math.sqrt(x)) for x in vs[k - k0 :]],
    }


def leave_one_out(y: Any, v: Any, ids: list[str], *, method: str = "REML", level: float = 0.95) -> list[dict[str, Any]]:
    """The pooled estimate with each study left out in turn (needs at least 3 studies)."""
    y = np.asarray(y, dtype=float)
    v = np.asarray(v, dtype=float)
    if len(y) < 3:
        return []
    out = []
    for i, sid in enumerate(ids):
        keep = np.arange(len(y)) != i
        r = pool(y[keep], v[keep], method=method, level=level)
        out.append(
            {
                "omitted": sid,
                "estimate": r["estimate"],
                "ci_lower": r["ci_lower"],
                "ci_upper": r["ci_upper"],
                "tau2": r["tau2"],
                "i2": r["i2"],
            }
        )
    return out
