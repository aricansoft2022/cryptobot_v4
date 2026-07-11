"""Compute all strategy indicators for a candle series in one pass.

This bundles RSI (from opens), RSI-VWMA, ADX/+DI/-DI and ADR, all aligned to the
candle series, and exposes convenient access to the values at the last closed
candle ``t`` and the previous candle ``t-1``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

from ..indicators.adr import compute_adr
from ..indicators.adx import compute_adx
from ..indicators.rsi import compute_rsi
from ..indicators.rsi_vwma import compute_rsi_vwma
from ..market.candle import Candle
from .parameters import CoinStrategyParameters


@dataclass(frozen=True)
class IndicatorSnapshot:
    """Indicator values at a single candle index (any field may be ``None``)."""

    index: int
    rsi: Optional[float]
    rsi_vwma: Optional[float]
    adx: Optional[float]
    plus_di: Optional[float]
    minus_di: Optional[float]
    adr: Optional[float]

    @property
    def is_complete(self) -> bool:
        """True when every indicator required by the strategy is defined.

        ``+DI`` / ``-DI`` are display-only and deliberately excluded here.
        """
        return None not in (self.rsi, self.rsi_vwma, self.adx, self.adr)


@dataclass(frozen=True)
class IndicatorSeries:
    """Aligned indicator series for a candle sequence."""

    rsi: List[Optional[float]]
    rsi_vwma: List[Optional[float]]
    adx: List[Optional[float]]
    plus_di: List[Optional[float]]
    minus_di: List[Optional[float]]
    adr: List[Optional[float]]

    def __len__(self) -> int:
        return len(self.rsi)

    def at(self, index: int) -> IndicatorSnapshot:
        """Return the :class:`IndicatorSnapshot` at ``index``."""
        return IndicatorSnapshot(
            index=index,
            rsi=self.rsi[index],
            rsi_vwma=self.rsi_vwma[index],
            adx=self.adx[index],
            plus_di=self.plus_di[index],
            minus_di=self.minus_di[index],
            adr=self.adr[index],
        )


def compute_indicators(
    candles: Sequence[Candle],
    params: CoinStrategyParameters,
) -> IndicatorSeries:
    """Compute every strategy indicator for ``candles`` using ``params``.

    The caller is responsible for passing a validated, signal-eligible series
    (see :func:`cryptobot.market.validation.ensure_valid_series`).
    """
    opens = [c.open for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    closes = [c.close for c in candles]
    volumes = [c.volume for c in candles]

    rsi = compute_rsi(opens, params.rsi_period)
    rsi_vwma = compute_rsi_vwma(rsi, volumes, params.rsi_ma_period)
    adx_result = compute_adx(highs, lows, closes, params.adx_period)
    adr = compute_adr(highs, lows, params.adr_period)

    return IndicatorSeries(
        rsi=rsi,
        rsi_vwma=rsi_vwma,
        adx=adx_result.adx,
        plus_di=adx_result.plus_di,
        minus_di=adx_result.minus_di,
        adr=adr,
    )
