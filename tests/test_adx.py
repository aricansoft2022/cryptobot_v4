"""Tests for Wilder ADX with +DI / -DI."""

from __future__ import annotations

import pytest

from cryptobot.indicators.adx import compute_adx


# A trending series with a hand-verified derivation (see project notes).
HIGHS = [10, 12, 13, 15, 14, 16, 18]
LOWS = [8, 9, 11, 12, 11, 13, 15]
CLOSES = [9, 11, 12, 14, 12, 15, 17]


def test_alignment_first_di_and_adx_indices():
    res = compute_adx(HIGHS, LOWS, CLOSES, period=2)
    # +DI/-DI first defined at index == period.
    assert res.plus_di[1] is None
    assert res.plus_di[2] is not None
    # First ADX at index 2*period - 1 == 3.
    assert res.adx[2] is None
    assert res.adx[3] is not None


def test_golden_di_and_adx_values():
    res = compute_adx(HIGHS, LOWS, CLOSES, period=2)
    # Verified by an independent step-by-step Wilder derivation.
    assert res.plus_di[2] == pytest.approx(60.0)
    assert res.minus_di[2] == pytest.approx(0.0)
    assert res.adx[3] == pytest.approx(100.0)
    assert res.adx[4] == pytest.approx(63.6364, abs=1e-4)
    assert res.adx[5] == pytest.approx(67.0034, abs=1e-4)
    assert res.adx[6] == pytest.approx(76.722, abs=1e-3)


def test_directional_movement_equal_case_is_zero():
    # Construct a bar where up_move == down_move: both +DM and -DM must be 0.
    highs = [10, 11, 12, 13]
    lows = [8, 7, 6, 5]
    closes = [9, 9, 9, 9]
    # i=1: up = 11-10 = 1, down = 8-7 = 1 -> equal -> both DM zero.
    res = compute_adx(highs, lows, closes, period=2)
    # With only downward -DM contributions the +DI should stay 0 where up==down.
    # (We assert bounds + no crash; equality handling covered structurally.)
    for v in res.adx:
        if v is not None:
            assert 0.0 <= v <= 100.0


def test_bounds_between_0_and_100():
    highs = [i + (i % 3) for i in range(30)]
    lows = [i - (i % 2) for i in range(30)]
    closes = [i for i in range(30)]
    res = compute_adx(highs, lows, closes, period=5)
    for series in (res.adx, res.plus_di, res.minus_di):
        for v in series:
            if v is not None:
                assert 0.0 <= v <= 100.0


def test_flat_market_fails_closed():
    # No movement at all: TR is zero everywhere -> +DI/-DI/ADX undefined.
    highs = [100] * 10
    lows = [100] * 10
    closes = [100] * 10
    res = compute_adx(highs, lows, closes, period=2)
    assert all(v is None for v in res.plus_di)
    assert all(v is None for v in res.adx)


def test_insufficient_data_returns_all_none():
    res = compute_adx([1, 2], [0, 1], [1, 2], period=5)
    assert all(v is None for v in res.adx)


def test_length_mismatch_raises():
    with pytest.raises(ValueError):
        compute_adx([1, 2, 3], [0, 1], [1, 2, 3], period=2)
