"""Same at the published precision: e-notation by significant digits, no absolute floor (review B, 3)."""

from __future__ import annotations

import pytest

from src.core import reproduce as rp
from src.core.pipeline.reproduction import _claimed_decimals, _equal_at, _places, equal_to_target


@pytest.mark.parametrize(
    ("published", "produced"),
    [
        (1.2345e-15, 9.9e-14),  # two tiny numbers, a hundredfold apart
        (4.5678e-12, 0.0),  # a p-value published as 4.5678e-12, the rerun gives 0
        (3.1416e-08, 3.2416e-08),  # p-values that differ in the second significant digit
        (2.2204e-16, 2.2205e-16),  # differs in the last published digit
    ],
)
def test_small_numbers_that_differ_are_not_same_at_precision(published: float, produced: float) -> None:
    assert rp.compare_value(published, produced)[0] != rp.AT_PRECISION


@pytest.mark.parametrize(
    ("published", "produced"),
    [
        (1.2345e-15, 1.23452e-15),  # rounds to the published five significant digits
        (4.5678e-12, 4.56781234e-12),
        (6.0221e-23, 6.02214e-23),
    ],
)
def test_small_numbers_that_round_to_the_published_value_are(published: float, produced: float) -> None:
    assert rp.compare_value(published, produced)[0] == rp.AT_PRECISION


def test_places_counts_from_the_exponent() -> None:
    assert _places("0.012***") == 3
    assert _places("1.23e-15") == 17
    assert _places("4.5E+05") == -4
    assert _claimed_decimals(1.2345e-15) == 19
    assert _claimed_decimals(0.0123) == 4


def test_printed_p_value_in_e_notation_is_relative() -> None:
    # A paper prints p = 1.2e-15: the rerun's 9.9e-14 does not round to it, 1.24e-15 does.
    assert not equal_to_target(9.9e-14, 1.2e-15, 2, _places("1.2e-15"))
    assert equal_to_target(1.24e-15, 1.2e-15, 2, _places("1.2e-15"))
    # A printed p of "0.000" still matches any p below 0.0005 (that is what it says).
    assert equal_to_target(1e-9, 0.0, 2, _places("0.000"))


def test_no_absolute_floor() -> None:
    assert not _equal_at(1e-10, 2e-10, 12)
    assert _equal_at(0.1 + 0.2, 0.3, 17)  # floating-point noise relative to the value
