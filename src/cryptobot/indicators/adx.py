"""Wilder ADX with +DI / -DI, computed from high/low/close.

Standard Wilder ADX. For each candle:

.. code-block:: text

    TR = max(high - low, abs(high - prev_close), abs(low - prev_close))

    up_move   = high[t] - high[t-1]
    down_move = low[t-1] - low[t]

    +DM = up_move   if up_move > down_move and up_move > 0   else 0
    -DM = down_move if down_move > up_move and down_move > 0 else 0

Wilder smoothing is applied to TR, +DM, -DM. Then:

.. code-block:: text

    +DI = 100 * smoothed_+DM / smoothed_TR
    -DI = 100 * smoothed_-DM / smoothed_TR
    DX  = 100 * abs(+DI - -DI) / (+DI + -DI)

The first ADX is the average of the first ``adx_period`` DX values; subsequent
ADX values use Wilder smoothing.

.. important::
   ``+DI`` and ``-DI`` are exposed for display only. They are **not** part of the
   entry filter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence


@dataclass(frozen=True)
class AdxResult:
    """Aligned ADX / +DI / -DI series (``None`` where undefined)."""

    adx: List[Optional[float]]
    plus_di: List[Optional[float]]
    minus_di: List[Optional[float]]


def _di_and_dx(
    smoothed_tr: float,
    smoothed_plus_dm: float,
    smoothed_minus_dm: float,
):
    """Return (+DI, -DI, DX) for one bar, or ``(None, None, None)`` if undefined.

    ``smoothed_tr == 0`` means a completely flat window (no true range at all):
    +DI/-DI are undefined and the bar fails closed. When ``+DI + -DI == 0`` (no
    directional movement) DX is taken as ``0`` per the standard convention.
    """
    if smoothed_tr == 0.0:
        return None, None, None
    plus_di = 100.0 * smoothed_plus_dm / smoothed_tr
    minus_di = 100.0 * smoothed_minus_dm / smoothed_tr
    di_sum = plus_di + minus_di
    dx = 0.0 if di_sum == 0.0 else 100.0 * abs(plus_di - minus_di) / di_sum
    return plus_di, minus_di, dx


def compute_adx(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int,
) -> AdxResult:
    """Compute Wilder ADX, +DI and -DI.

    Args:
        highs, lows, closes: Aligned high/low/close of the *closed* candles.
        period: The ADX period (``adx_period``).

    Returns:
        An :class:`AdxResult` whose lists are the same length as the inputs.
    """
    if period < 1:
        raise ValueError(f"adx_period must be >= 1, got {period}")
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("highs, lows and closes must have the same length")

    n = len(highs)
    plus_di: List[Optional[float]] = [None] * n
    minus_di: List[Optional[float]] = [None] * n
    adx: List[Optional[float]] = [None] * n

    # Directional movement / true range are defined from index 1 onward.
    if n < period + 1:
        return AdxResult(adx, plus_di, minus_di)

    tr = [0.0] * n
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    for i in range(1, n):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )

    # Wilder's initial smoothed value is the sum of the first `period` values
    # (indices 1..period), landing the first +DI/-DI/DX at index `period`.
    smoothed_tr = sum(tr[1 : period + 1])
    smoothed_plus = sum(plus_dm[1 : period + 1])
    smoothed_minus = sum(minus_dm[1 : period + 1])

    dx: List[Optional[float]] = [None] * n
    p, m, d = _di_and_dx(smoothed_tr, smoothed_plus, smoothed_minus)
    plus_di[period], minus_di[period], dx[period] = p, m, d

    for i in range(period + 1, n):
        smoothed_tr = smoothed_tr - smoothed_tr / period + tr[i]
        smoothed_plus = smoothed_plus - smoothed_plus / period + plus_dm[i]
        smoothed_minus = smoothed_minus - smoothed_minus / period + minus_dm[i]
        p, m, d = _di_and_dx(smoothed_tr, smoothed_plus, smoothed_minus)
        plus_di[i], minus_di[i], dx[i] = p, m, d

    # First ADX = average of the first `period` DX values (indices period..2*period-1).
    first_adx_index = 2 * period - 1
    if n <= first_adx_index:
        return AdxResult(adx, plus_di, minus_di)

    initial_dx = dx[period : 2 * period]
    if any(value is None for value in initial_dx):
        # A flat window left DX undefined; fail-closed on ADX.
        return AdxResult(adx, plus_di, minus_di)

    adx_value = sum(initial_dx) / period
    adx[first_adx_index] = adx_value
    for i in range(first_adx_index + 1, n):
        current_dx = dx[i]
        if current_dx is None:
            # Degenerate flat window: cannot continue Wilder smoothing. Fail-closed.
            break
        adx_value = (adx_value * (period - 1) + current_dx) / period
        adx[i] = adx_value

    return AdxResult(adx, plus_di, minus_di)
