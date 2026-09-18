"""Datetime normalisation at the data boundary (ROBUSTNESS_REVIEW.md, rec. 5).

The 2026-08-05 validation cell died on

    TypeError: Invalid comparison between dtype=datetime64[ns, UTC] and Timestamp

in generated analysis code. `run_estimation.py` crashed, wrote `{}`, and the
paper was drafted over the hole with hand-written tables. The data layer can
guarantee what the prompt can only request.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.modules.data.normalize import normalize_for_materialization


def test_tz_aware_column_becomes_naive_utc():
    df = pd.DataFrame({"ts": pd.to_datetime(["2024-01-11T15:30:00Z", "2024-01-12T15:30:00Z"])})
    assert isinstance(df["ts"].dtype, pd.DatetimeTZDtype)

    out, notes = normalize_for_materialization(df)

    assert out["ts"].dtype == "datetime64[ns]"
    assert notes


def test_the_comparison_that_crashed_the_cell_now_works():
    """This is the exact failure, reduced."""
    df = pd.DataFrame({"ts": pd.to_datetime(["2024-01-11T15:30:00Z"]), "px": [42.0]})
    with pytest.raises(TypeError, match="Invalid comparison"):
        _ = df["ts"] >= pd.Timestamp("2024-01-11")

    out, _ = normalize_for_materialization(df)
    assert bool((out["ts"] >= pd.Timestamp("2024-01-11")).iloc[0])


def test_non_utc_zone_is_converted_not_just_stripped():
    """Dropping the zone without converting would shift the instant."""
    df = pd.DataFrame({"ts": pd.to_datetime(["2024-01-11T00:30:00-05:00"])})
    out, _ = normalize_for_materialization(df)
    assert out["ts"].iloc[0] == pd.Timestamp("2024-01-11T05:30:00")


def test_datetime_index_is_preserved_as_a_column():
    """Both write paths use index=False, so a DatetimeIndex would be lost —
    which is how a yfinance frame silently arrives without its dates."""
    idx = pd.to_datetime(["2024-01-11", "2024-01-12"])
    df = pd.DataFrame({"close": [1.0, 2.0]}, index=idx)

    out, notes = normalize_for_materialization(df)

    assert "timestamp" in out.columns
    assert list(out["close"]) == [1.0, 2.0]
    assert any("DatetimeIndex" in n for n in notes)


def test_named_datetime_index_keeps_its_name():
    idx = pd.to_datetime(["2024-01-11"])
    idx.name = "Date"
    df = pd.DataFrame({"close": [1.0]}, index=idx)
    out, _ = normalize_for_materialization(df)
    assert "Date" in out.columns


def test_tz_aware_index_is_both_preserved_and_naive():
    idx = pd.to_datetime(["2024-01-11T15:30:00Z"])
    df = pd.DataFrame({"close": [1.0]}, index=idx)
    out, _ = normalize_for_materialization(df)
    assert out["timestamp"].dtype == "datetime64[ns]"


def test_ordinary_frames_are_untouched():
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    out, notes = normalize_for_materialization(df)
    assert notes == []
    pd.testing.assert_frame_equal(out, df)


def test_input_is_not_mutated():
    df = pd.DataFrame({"ts": pd.to_datetime(["2024-01-11T15:30:00Z"])})
    before = df["ts"].dtype
    normalize_for_materialization(df)
    assert df["ts"].dtype == before
