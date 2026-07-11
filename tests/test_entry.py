"""Tests for the BUY signal: the five conditions and their exact strictness."""

from __future__ import annotations

import pytest

from cryptobot.strategy.entry import (
    evaluate_entry_conditions,
    evaluate_entry_signal,
)
from cryptobot.strategy.indicators import IndicatorSnapshot

from ._helpers import default_params, make_candles


def _snap(index, rsi, vwma, adx, adr):
    return IndicatorSnapshot(
        index=index, rsi=rsi, rsi_vwma=vwma, adx=adx, plus_di=None, minus_di=None, adr=adr
    )


def _passing_pair(params):
    """A (previous, current) snapshot pair that satisfies all five conditions."""
    previous = _snap(0, rsi=20.0, vwma=30.0, adx=50.0, adr=1.0)  # rsi<=vwma
    current = _snap(1, rsi=40.0, vwma=35.0, adx=50.0, adr=2.0)   # rsi<oversold, rsi>vwma, adr rising
    return previous, current


def test_all_conditions_pass():
    params = default_params(rsi_oversold=45.0, adx_low=10.0, adx_high=90.0)
    prev, cur = _passing_pair(params)
    cond = evaluate_entry_conditions(cur, prev, params)
    assert all(cond.values())


def test_rsi_oversold_is_strict():
    params = default_params(rsi_oversold=40.0)
    prev, cur = _passing_pair(params)
    # RSI[t] exactly equal to oversold must NOT pass (strict <).
    cur = _snap(1, rsi=40.0, vwma=35.0, adx=50.0, adr=2.0)
    cond = evaluate_entry_conditions(cur, prev, params)
    assert cond["rsi_below_oversold"] is False


def test_crossover_prev_leg_is_inclusive():
    params = default_params(rsi_oversold=45.0)
    # RSI[t-1] == VWMA[t-1] is allowed (<=).
    prev = _snap(0, rsi=30.0, vwma=30.0, adx=50.0, adr=1.0)
    cur = _snap(1, rsi=40.0, vwma=35.0, adx=50.0, adr=2.0)
    cond = evaluate_entry_conditions(cur, prev, params)
    assert cond["prev_rsi_le_vwma"] is True


def test_crossover_current_leg_is_strict():
    params = default_params(rsi_oversold=45.0)
    prev = _snap(0, rsi=20.0, vwma=30.0, adx=50.0, adr=1.0)
    # RSI[t] == VWMA[t] must NOT pass (strict >).
    cur = _snap(1, rsi=35.0, vwma=35.0, adx=50.0, adr=2.0)
    cond = evaluate_entry_conditions(cur, prev, params)
    assert cond["rsi_above_vwma"] is False


def test_adx_band_is_inclusive_on_both_ends():
    params = default_params(adx_low=20.0, adx_high=60.0, rsi_oversold=45.0)
    prev = _snap(0, rsi=20.0, vwma=30.0, adx=50.0, adr=1.0)
    for adx_value in (20.0, 60.0):  # both bounds inclusive
        cur = _snap(1, rsi=40.0, vwma=35.0, adx=adx_value, adr=2.0)
        cond = evaluate_entry_conditions(cur, prev, params)
        assert cond["adx_in_band"] is True
    for adx_value in (19.999, 60.001):  # just outside
        cur = _snap(1, rsi=40.0, vwma=35.0, adx=adx_value, adr=2.0)
        cond = evaluate_entry_conditions(cur, prev, params)
        assert cond["adx_in_band"] is False


def test_adr_rising_is_strict():
    params = default_params(rsi_oversold=45.0)
    prev = _snap(0, rsi=20.0, vwma=30.0, adx=50.0, adr=2.0)
    # ADR equal is not enough (strict >).
    cur = _snap(1, rsi=40.0, vwma=35.0, adx=50.0, adr=2.0)
    cond = evaluate_entry_conditions(cur, prev, params)
    assert cond["adr_rising"] is False


def test_di_not_part_of_formula():
    params = default_params(rsi_oversold=45.0)
    prev = _snap(0, rsi=20.0, vwma=30.0, adx=50.0, adr=1.0)
    cur = _snap(1, rsi=40.0, vwma=35.0, adx=50.0, adr=2.0)
    cond = evaluate_entry_conditions(cur, prev, params)
    # Exactly five conditions, none referencing +DI / -DI.
    assert set(cond) == {
        "rsi_below_oversold",
        "prev_rsi_le_vwma",
        "rsi_above_vwma",
        "adx_in_band",
        "adr_rising",
    }


# --- End-to-end fixture (a real candle series that fires a BUY) --------------

FIXTURE_OPENS = [102.91, 104.47, 102.17, 100.48, 103.24, 103.06, 101.29, 101.69]
FIXTURE_HIGHS = [103.59, 106.18, 102.83, 101.26, 104.64, 104.11, 102.3, 103.56]
FIXTURE_LOWS = [100.97, 102.48, 100.27, 98.2, 102.32, 101.21, 98.28, 99.65]
FIXTURE_CLOSES = [101.62, 105.6, 100.42, 99.91, 103.76, 102.17, 99.88, 99.93]
FIXTURE_VOLS = [8.73, 1.53, 9.55, 5.8, 9.61, 2.27, 4.89, 8.96]


def _fixture_candles():
    return make_candles(
        FIXTURE_OPENS, FIXTURE_HIGHS, FIXTURE_LOWS, FIXTURE_CLOSES, FIXTURE_VOLS
    )


def test_end_to_end_signal_fires():
    params = default_params()
    ev = evaluate_entry_signal(_fixture_candles(), params)
    assert ev.signal is True
    assert all(ev.conditions.values())
    # Independently confirm the crossover: below oversold, and RSI crossed VWMA.
    assert ev.current.rsi < params.rsi_oversold
    assert ev.previous.rsi <= ev.previous.rsi_vwma
    assert ev.current.rsi > ev.current.rsi_vwma


def test_end_to_end_fails_closed_on_invalid_series():
    candles = _fixture_candles()
    # Break contiguity by dropping a middle candle.
    broken = candles[:3] + candles[4:]
    ev = evaluate_entry_signal(broken, default_params())
    assert ev.signal is False
    assert "invalid candle series" in ev.reason


def test_end_to_end_no_signal_when_indicators_not_ready():
    params = default_params()
    ev = evaluate_entry_signal(_fixture_candles()[:3], params)
    assert ev.signal is False


def test_raising_oversold_threshold_changes_outcome():
    # The fixture RSI[t] ~ 41.75; an oversold of 30 makes condition 1 fail.
    params = default_params(rsi_oversold=30.0)
    ev = evaluate_entry_signal(_fixture_candles(), params)
    assert ev.signal is False
    assert ev.conditions["rsi_below_oversold"] is False
