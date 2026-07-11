"""The deterministic BUY signal.

A BUY signal requires **all five** conditions on the last closed candle ``t``:

.. code-block:: text

    ENTRY_SIGNAL =
        RSI[t] < rsi_oversold
        AND RSI[t-1] <= RSI_VWMA[t-1]
        AND RSI[t] > RSI_VWMA[t]
        AND adx_low <= ADX[t] <= adx_high
        AND ADR[t] > ADR[t-1]

Conditions 2 and 3 together define a bullish RSI / RSI-VWMA crossover (RSI
crossing the VWMA from below). ``+DI`` / ``-DI`` are **not** part of this formula.

The signal is *fail-closed*: an invalid candle series, or any missing indicator
value at ``t`` or ``t-1``, yields no signal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Sequence

from ..market.candle import Candle
from ..market.validation import validate_series
from .indicators import IndicatorSnapshot, compute_indicators
from .parameters import CoinStrategyParameters

#: Ordered names of the five entry conditions (spec formula order).
ENTRY_CONDITION_NAMES = (
    "rsi_below_oversold",
    "prev_rsi_le_vwma",
    "rsi_above_vwma",
    "adx_in_band",
    "adr_rising",
)


@dataclass(frozen=True)
class EntryEvaluation:
    """Result of evaluating the entry signal on a candle series.

    Attributes:
        signal: ``True`` only if all five conditions hold on the last candle.
        reason: Human-readable explanation (why not, or "all conditions met").
        conditions: Per-condition boolean breakdown (empty when fail-closed).
        candle_open_time: ``open_time`` of the evaluated last closed candle, or
            ``None`` when the series was empty/invalid.
        current: Indicator snapshot at ``t`` (``None`` when unavailable).
        previous: Indicator snapshot at ``t-1`` (``None`` when unavailable).
    """

    signal: bool
    reason: str
    conditions: Dict[str, bool]
    candle_open_time: Optional[int]
    current: Optional[IndicatorSnapshot]
    previous: Optional[IndicatorSnapshot]


def evaluate_entry_conditions(
    current: IndicatorSnapshot,
    previous: IndicatorSnapshot,
    params: CoinStrategyParameters,
) -> Dict[str, bool]:
    """Return the five entry conditions as a name->bool mapping.

    This is the pure heart of the entry formula and assumes every indicator
    value it reads is defined (not ``None``). The strictness of each comparison
    is spec-mandated and must not change:

    * ``rsi_below_oversold``: ``RSI[t] < rsi_oversold`` (strict)
    * ``prev_rsi_le_vwma``:  ``RSI[t-1] <= RSI_VWMA[t-1]`` (inclusive)
    * ``rsi_above_vwma``:    ``RSI[t] > RSI_VWMA[t]`` (strict)
    * ``adx_in_band``:       ``adx_low <= ADX[t] <= adx_high`` (inclusive)
    * ``adr_rising``:        ``ADR[t] > ADR[t-1]`` (strict)
    """
    return {
        "rsi_below_oversold": current.rsi < params.rsi_oversold,
        "prev_rsi_le_vwma": previous.rsi <= previous.rsi_vwma,
        "rsi_above_vwma": current.rsi > current.rsi_vwma,
        "adx_in_band": params.adx_low <= current.adx <= params.adx_high,
        "adr_rising": current.adr > previous.adr,
    }


def _no_signal(reason: str, candle_open_time=None) -> EntryEvaluation:
    return EntryEvaluation(
        signal=False,
        reason=reason,
        conditions={},
        candle_open_time=candle_open_time,
        current=None,
        previous=None,
    )


def evaluate_entry_signal(
    candles: Sequence[Candle],
    params: CoinStrategyParameters,
) -> EntryEvaluation:
    """Evaluate the BUY signal on the last closed candle of ``candles``.

    This computes the *technical* signal only. Whether the signal may become a
    real order is decided separately by the operational safety gates
    (:mod:`cryptobot.execution.gates`).
    """
    problems = validate_series(candles)
    if problems:
        return _no_signal(f"invalid candle series: {problems[0]}")

    if len(candles) < 2:
        return _no_signal("need at least two closed candles")

    t = len(candles) - 1
    last_open_time = candles[t].open_time

    series = compute_indicators(candles, params)
    current: IndicatorSnapshot = series.at(t)
    previous: IndicatorSnapshot = series.at(t - 1)

    # Fail-closed: every indicator used by the formula must be defined at both
    # t and t-1 (RSI-VWMA at t-1, ADR at t-1 are needed too).
    if not current.is_complete:
        return _no_signal("indicators not ready at t", last_open_time)
    if previous.rsi is None or previous.rsi_vwma is None or previous.adr is None:
        return _no_signal("indicators not ready at t-1", last_open_time)

    conditions = evaluate_entry_conditions(current, previous, params)
    signal = all(conditions.values())

    if signal:
        reason = "all entry conditions met"
    else:
        failed = [name for name, ok in conditions.items() if not ok]
        reason = "entry conditions not met: " + ", ".join(failed)

    return EntryEvaluation(
        signal=signal,
        reason=reason,
        conditions=conditions,
        candle_open_time=last_open_time,
        current=current,
        previous=previous,
    )
