from __future__ import annotations

import pytest

from app.evals.metrics import percentile, rate, share, wilson_interval


def test_rate_of_nothing_is_unknown_not_zero() -> None:
    assert rate(0, 0) is None
    assert rate(1, 4) == 0.25
    assert share([]) is None
    assert share([True, False, True, True]) == 0.75


def test_percentile_is_nearest_rank() -> None:
    values = [50.0, 10.0, 40.0, 20.0, 30.0]

    assert percentile(values, 50) == 30.0
    assert percentile(values, 95) == 50.0
    assert percentile(values, 100) == 50.0
    assert percentile(values, 1) == 10.0
    assert percentile([7.0], 95) == 7.0
    assert percentile([], 50) is None


def test_p95_of_a_hundred_values_is_the_95th() -> None:
    assert percentile([float(n) for n in range(1, 101)], 95) == 95.0


def test_wilson_interval_contains_the_observed_rate_and_stays_in_range() -> None:
    assert wilson_interval(0, 0) is None

    low, high = wilson_interval(50, 100) or (0, 0)
    assert low == pytest.approx(0.404, abs=0.002)
    assert high == pytest.approx(0.596, abs=0.002)

    low, high = wilson_interval(0, 10) or (1, 1)
    assert low == 0.0 and 0.2 < high < 0.35

    low, high = wilson_interval(10, 10) or (0, 0)
    assert high == 1.0 and 0.65 < low < 0.8


def test_more_games_narrow_the_interval() -> None:
    few = wilson_interval(3, 10) or (0, 0)
    many = wilson_interval(300, 1000) or (0, 0)

    assert many[1] - many[0] < few[1] - few[0]
