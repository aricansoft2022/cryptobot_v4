"""Per-coin strategy parameters.

Every coin owns an independent set of these parameters. The dataclass is frozen:
once a position captures a parameter set as its snapshot, that snapshot can never
change. Updating a coin's settings means constructing a *new*
:class:`CoinStrategyParameters` instance for future decisions — open positions
keep the instance they were opened with.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CoinStrategyParameters:
    """Immutable strategy configuration for a single coin.

    Attributes:
        rsi_oversold: Entry requires ``RSI[t] < rsi_oversold`` (strict).
        rsi_overbought: Normal exit arms when ``RSI[t] > rsi_overbought`` (strict).
        adx_low: Inclusive lower bound of the allowed ADX band.
        adx_high: Inclusive upper bound of the allowed ADX band.
        min_net_profit_pct: Minimum net profit target (percent) for normal exit.
        rsi_period: RSI Wilder period.
        rsi_ma_period: RSI-VWMA window length.
        adx_period: ADX Wilder period.
        adr_period: ADR window length (candles before the current one).
        capital_limit_usdt: Maximum total capital (USDT) the coin may use.
        slot_count: Maximum number of open + reserved slots for the coin.
    """

    rsi_oversold: float
    rsi_overbought: float
    adx_low: float
    adx_high: float
    min_net_profit_pct: Decimal
    rsi_period: int
    rsi_ma_period: int
    adx_period: int
    adr_period: int
    capital_limit_usdt: Decimal
    slot_count: int

    def __post_init__(self) -> None:
        for name in ("rsi_period", "rsi_ma_period", "adx_period", "adr_period"):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be an int >= 1, got {value!r}")
        if self.slot_count < 1:
            raise ValueError(f"slot_count must be >= 1, got {self.slot_count}")
        for name in ("rsi_oversold", "rsi_overbought"):
            value = getattr(self, name)
            if not 0.0 <= value <= 100.0:
                raise ValueError(f"{name} must be within [0, 100], got {value}")
        if self.adx_low > self.adx_high:
            raise ValueError(
                f"adx_low ({self.adx_low}) must be <= adx_high ({self.adx_high})"
            )
        if self.adx_low < 0.0:
            raise ValueError(f"adx_low must be >= 0, got {self.adx_low}")
        if Decimal(self.min_net_profit_pct) < 0:
            raise ValueError(
                f"min_net_profit_pct must be >= 0, got {self.min_net_profit_pct}"
            )
        if Decimal(self.capital_limit_usdt) <= 0:
            raise ValueError(
                f"capital_limit_usdt must be > 0, got {self.capital_limit_usdt}"
            )

    @property
    def min_candles_for_signal(self) -> int:
        """Minimum number of closed candles needed to evaluate an entry.

        Entry needs indicator values at ``t`` and ``t-1`` for RSI, RSI-VWMA, ADX
        and ADR. The binding indicators are ADX (needs ``2 * adx_period`` bars),
        RSI-VWMA (needs ``rsi_period + rsi_ma_period`` bars) and ADR (needs
        ``adr_period + 1`` bars). One extra bar is required for the ``t-1``
        comparisons.
        """
        rsi_ready = self.rsi_period + 1
        vwma_ready = rsi_ready + self.rsi_ma_period - 1
        adx_ready = 2 * self.adx_period
        adr_ready = self.adr_period + 1
        # +1 so that both t and t-1 are defined for every indicator.
        return max(vwma_ready, adx_ready, adr_ready) + 1
