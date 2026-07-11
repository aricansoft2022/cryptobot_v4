"""Shared helpers for building candle series in tests."""

from __future__ import annotations

from decimal import Decimal
from typing import List, Optional, Sequence

from cryptobot.market.candle import INTERVAL_MS, Candle
from cryptobot.strategy.parameters import CoinStrategyParameters


def make_candles(
    opens: Sequence[float],
    highs: Optional[Sequence[float]] = None,
    lows: Optional[Sequence[float]] = None,
    closes: Optional[Sequence[float]] = None,
    volumes: Optional[Sequence[float]] = None,
    symbol: str = "BTCUSDT",
    start_open_time: int = 0,
    step_ms: int = INTERVAL_MS,
    is_closed: bool = True,
) -> List[Candle]:
    """Build a contiguous 1-minute candle series from the given fields.

    Missing OHLC fields default sensibly around ``opens`` so validation passes;
    volumes default to 1.0.
    """
    n = len(opens)
    highs = list(highs) if highs is not None else [o + 1.0 for o in opens]
    lows = list(lows) if lows is not None else [o - 1.0 for o in opens]
    closes = list(closes) if closes is not None else list(opens)
    volumes = list(volumes) if volumes is not None else [1.0] * n

    candles: List[Candle] = []
    for i in range(n):
        candles.append(
            Candle(
                symbol=symbol,
                open_time=start_open_time + i * step_ms,
                open=opens[i],
                high=highs[i],
                low=lows[i],
                close=closes[i],
                volume=volumes[i],
                is_closed=is_closed,
            )
        )
    return candles


def default_params(**overrides) -> CoinStrategyParameters:
    """A small-period parameter set convenient for tests, with overrides."""
    base = dict(
        rsi_oversold=45.0,
        rsi_overbought=70.0,
        adx_low=10.0,
        adx_high=90.0,
        min_net_profit_pct=Decimal("0.5"),
        rsi_period=2,
        rsi_ma_period=2,
        adx_period=2,
        adr_period=2,
        capital_limit_usdt=Decimal("1000"),
        slot_count=3,
    )
    base.update(overrides)
    return CoinStrategyParameters(**base)
