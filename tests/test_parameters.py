"""Tests for per-coin strategy parameters and their validation."""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest

from cryptobot.strategy.parameters import CoinStrategyParameters

from ._helpers import default_params


def test_parameters_are_frozen():
    params = default_params()
    with pytest.raises(dataclasses.FrozenInstanceError):
        params.rsi_oversold = 10.0  # type: ignore[misc]


def test_rejects_non_positive_periods():
    for field in ("rsi_period", "rsi_ma_period", "adx_period", "adr_period"):
        with pytest.raises(ValueError):
            default_params(**{field: 0})


def test_rejects_bad_rsi_thresholds():
    with pytest.raises(ValueError):
        default_params(rsi_oversold=-1.0)
    with pytest.raises(ValueError):
        default_params(rsi_overbought=101.0)


def test_rejects_adx_low_above_high():
    with pytest.raises(ValueError):
        default_params(adx_low=50.0, adx_high=40.0)


def test_rejects_non_positive_capital():
    with pytest.raises(ValueError):
        default_params(capital_limit_usdt=Decimal("0"))


def test_rejects_zero_slots():
    with pytest.raises(ValueError):
        default_params(slot_count=0)


def test_min_candles_for_signal_accounts_for_all_indicators():
    params = default_params(rsi_period=2, rsi_ma_period=2, adx_period=2, adr_period=2)
    # vwma_ready = (2+1)+2-1 = 4; adx_ready = 4; adr_ready = 3; +1 => 5
    assert params.min_candles_for_signal == 5

    params2 = default_params(rsi_period=14, rsi_ma_period=14, adx_period=14, adr_period=14)
    # adx_ready = 28 dominates; +1 => 29
    assert params2.min_candles_for_signal == 29
