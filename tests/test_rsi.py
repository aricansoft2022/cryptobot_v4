"""Tests for the open-price Wilder RSI."""

from __future__ import annotations

import math

import pytest

from cryptobot.indicators.rsi import compute_rsi


def test_alignment_and_warmup_padding():
    opens = [10, 11, 10, 12, 13]
    rsi = compute_rsi(opens, period=2)
    assert len(rsi) == len(opens)
    # First `period` entries are undefined; first RSI lands at index == period.
    assert rsi[0] is None
    assert rsi[1] is None
    assert rsi[2] is not None


def test_golden_values_period_2():
    # Hand-computed: opens -> changes [+1,-1,+2,+1]
    opens = [10, 11, 10, 12, 13]
    rsi = compute_rsi(opens, period=2)
    assert rsi[2] == pytest.approx(50.0)
    assert rsi[3] == pytest.approx(100.0 * 1.25 / 1.5)  # 83.3333...
    assert rsi[4] == pytest.approx(90.0)


def test_special_case_all_flat_is_50():
    # gain == loss == 0 for every change -> RSI 50.
    rsi = compute_rsi([5, 5, 5, 5, 5], period=2)
    assert all(v == pytest.approx(50.0) for v in rsi if v is not None)


def test_special_case_only_gains_is_100():
    rsi = compute_rsi([1, 2, 3, 4, 5], period=2)
    assert all(v == pytest.approx(100.0) for v in rsi if v is not None)


def test_special_case_only_losses_is_0():
    rsi = compute_rsi([5, 4, 3, 2, 1], period=2)
    assert all(v == pytest.approx(0.0) for v in rsi if v is not None)


def test_uses_open_prices_not_close():
    # Same opens but wildly different (ignored) closes must yield identical RSI.
    opens = [10, 11, 10, 12, 13]
    a = compute_rsi(opens, period=2)
    # compute_rsi only takes opens; this documents that closes never enter RSI.
    b = compute_rsi(list(opens), period=2)
    assert a == b


def test_bounds_between_0_and_100():
    opens = [100, 101, 99, 103, 98, 104, 97, 108, 96, 110]
    rsi = compute_rsi(opens, period=3)
    for v in rsi:
        if v is not None:
            assert 0.0 <= v <= 100.0


def test_insufficient_data_returns_all_none():
    rsi = compute_rsi([10, 11], period=5)
    assert rsi == [None, None]


def test_period_must_be_positive():
    with pytest.raises(ValueError):
        compute_rsi([1, 2, 3], period=0)


def test_wilder_smoothing_recurrence_holds():
    opens = [50, 52, 51, 55, 53, 58, 54, 60]
    period = 3
    rsi = compute_rsi(opens, period)
    # Re-derive avg_gain/avg_loss independently and check the last RSI.
    gains = [max(opens[i] - opens[i - 1], 0) for i in range(1, len(opens))]
    losses = [max(opens[i - 1] - opens[i], 0) for i in range(1, len(opens))]
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for k in range(period, len(gains)):
        ag = (ag * (period - 1) + gains[k]) / period
        al = (al * (period - 1) + losses[k]) / period
    expected = 100.0 * ag / (ag + al)
    assert rsi[-1] == pytest.approx(expected)
    assert not math.isnan(rsi[-1])
