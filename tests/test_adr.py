"""Tests for ADR (average range, excluding the current candle)."""

from __future__ import annotations

import pytest

from cryptobot.indicators.adr import compute_adr


def test_excludes_current_candle():
    highs = [10, 12, 11, 15, 14]
    lows = [8, 9, 10, 11, 12]
    # ranges = [2, 3, 1, 4, 2]
    adr = compute_adr(highs, lows, period=2)
    assert len(adr) == len(highs)
    assert adr[0] is None
    assert adr[1] is None
    # ADR[2] window [0,2) = ranges[0:2] = (2+3)/2 = 2.5  (excludes range at 2)
    assert adr[2] == pytest.approx(2.5)
    # ADR[3] window [1,3) = (3+1)/2 = 2.0
    assert adr[3] == pytest.approx(2.0)
    # ADR[4] window [2,4) = (1+4)/2 = 2.5
    assert adr[4] == pytest.approx(2.5)


def test_current_candle_range_does_not_affect_its_own_adr():
    highs = [10, 12, 11, 15]
    lows = [8, 9, 10, 11]
    base = compute_adr(highs, lows, period=2)
    # Change ONLY the last candle's range; its own ADR must be unchanged.
    highs2 = [10, 12, 11, 99]
    lows2 = [8, 9, 10, -99]
    changed = compute_adr(highs2, lows2, period=2)
    assert changed[3] == pytest.approx(base[3])


def test_period_one():
    highs = [10, 12, 11]
    lows = [8, 9, 10]
    # ranges = [2, 3, 1]; ADR[t] = range[t-1]
    adr = compute_adr(highs, lows, period=1)
    assert adr[0] is None
    assert adr[1] == pytest.approx(2.0)
    assert adr[2] == pytest.approx(3.0)


def test_length_mismatch_raises():
    with pytest.raises(ValueError):
        compute_adr([1, 2, 3], [0, 1], period=2)


def test_period_must_be_positive():
    with pytest.raises(ValueError):
        compute_adr([1, 2], [0, 1], period=0)
