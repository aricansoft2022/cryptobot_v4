"""Tests for RSI-VWMA (volume-weighted moving average of RSI)."""

from __future__ import annotations

import pytest

from cryptobot.indicators.rsi_vwma import compute_rsi_vwma


def test_window_and_weighting():
    rsi = [None, None, 50.0, 80.0, 90.0]
    volumes = [1, 1, 2, 3, 4]
    out = compute_rsi_vwma(rsi, volumes, period=2)
    assert len(out) == len(rsi)
    # t=3 window [2,3]: (50*2 + 80*3) / (2+3) = 340/5 = 68
    assert out[3] == pytest.approx((50 * 2 + 80 * 3) / 5)
    # t=4 window [3,4]: (80*3 + 90*4) / (3+4)
    assert out[4] == pytest.approx((80 * 3 + 90 * 4) / 7)


def test_none_in_window_yields_none():
    rsi = [None, 50.0, 60.0]
    volumes = [1, 1, 1]
    out = compute_rsi_vwma(rsi, volumes, period=2)
    # t=1 window [0,1] contains a None -> None
    assert out[1] is None
    # t=2 window [1,2] fully defined -> value
    assert out[2] == pytest.approx(55.0)


def test_zero_total_volume_fails_closed():
    rsi = [50.0, 60.0, 70.0]
    volumes = [0, 0, 0]
    out = compute_rsi_vwma(rsi, volumes, period=2)
    # Never fabricate a value when there is no volume.
    assert out == [None, None, None]


def test_partial_zero_volume_still_weights_correctly():
    rsi = [50.0, 60.0, 70.0]
    volumes = [0, 0, 5]
    out = compute_rsi_vwma(rsi, volumes, period=2)
    # t=2 window [1,2]: (60*0 + 70*5)/5 = 70
    assert out[2] == pytest.approx(70.0)


def test_window_before_start_is_none():
    rsi = [50.0, 60.0, 70.0]
    volumes = [1, 1, 1]
    out = compute_rsi_vwma(rsi, volumes, period=3)
    assert out[0] is None
    assert out[1] is None
    assert out[2] == pytest.approx((50 + 60 + 70) / 3)


def test_length_mismatch_raises():
    with pytest.raises(ValueError):
        compute_rsi_vwma([50.0, 60.0], [1.0], period=2)


def test_period_must_be_positive():
    with pytest.raises(ValueError):
        compute_rsi_vwma([50.0], [1.0], period=0)
