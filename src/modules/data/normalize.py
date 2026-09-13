"""Normalise a DataFrame before it becomes a specialist's input.

Generated analysis code hits the same pandas failure again and again:

    TypeError: Invalid comparison between dtype=datetime64[ns, UTC] and Timestamp

A tz-aware column will not compare against the tz-naive `pd.Timestamp("2024-01-11")`
that any reasonable script writes for an event date. yfinance returns tz-aware
timestamps for some intervals and tz-naive for others, so whether the generated
script crashes depends on which ticker and interval the analyst happened to pull.

That is the crash that killed the 2026-08-05 validation cell: `run_estimation.py`
died on this comparison, wrote `{}`, and the paper was drafted over the hole.

Prompting the model to "be careful with timezones" is not a fix — it is asking
the model to be reliable about something the data layer can simply guarantee.
So we normalise once, here, where data crosses into the workspace:

  * tz-aware datetime columns become tz-naive UTC
  * a DatetimeIndex is moved into a real column, because both write paths use
    `index=False` and would otherwise drop the timestamps entirely
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...logging_config import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pandas as pd

logger = get_logger(__name__)


def normalize_for_materialization(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Return ``(normalised_df, notes)``. Never raises; never mutates the input."""
    import pandas as pd

    notes: list[str] = []

    if isinstance(df.index, pd.DatetimeIndex):
        name = df.index.name or "timestamp"
        df = df.rename_axis(name).reset_index()
        notes.append(f"moved the DatetimeIndex into a column named {name!r} (writes use index=False)")
    else:
        df = df.copy()

    for col in df.columns:
        dtype = df[col].dtype
        if isinstance(dtype, pd.DatetimeTZDtype):
            df[col] = df[col].dt.tz_convert("UTC").dt.tz_localize(None)
            notes.append(f"{col}: {dtype} -> tz-naive UTC")

    if notes:
        logger.info("data normalisation: %s", "; ".join(notes))
    return df, notes
