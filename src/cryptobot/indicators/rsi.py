"""RSI computed from candle *open* prices using Wilder smoothing.

Deviating from the textbook RSI, this strategy computes RSI from ``open`` prices
(never ``close``). The math:

.. code-block:: text

    change[t] = open[t] - open[t-1]
    gain[t]   = max(change[t], 0)
    loss[t]   = max(-change[t], 0)

The first average gain/loss is the arithmetic mean of the first ``rsi_period``
gains/losses. Subsequent values use Wilder smoothing:

.. code-block:: text

    avg_gain[t] = (avg_gain[t-1] * (rsi_period - 1) + gain[t]) / rsi_period
    avg_loss[t] = (avg_loss[t-1] * (rsi_period - 1) + loss[t]) / rsi_period
    RSI[t]      = 100 * avg_gain[t] / (avg_gain[t] + avg_loss[t])

Special cases (spec-mandated):

* ``avg_gain + avg_loss == 0``  -> RSI = 50
* ``avg_loss == 0`` (gain > 0)  -> RSI = 100
* ``avg_gain == 0`` (loss > 0)  -> RSI = 0
"""

from __future__ import annotations

from typing import List, Optional, Sequence


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    """Apply the RSI formula including the three spec-mandated special cases."""
    if avg_gain + avg_loss == 0.0:
        return 50.0
    if avg_loss == 0.0:
        return 100.0
    if avg_gain == 0.0:
        return 0.0
    return 100.0 * avg_gain / (avg_gain + avg_loss)


def compute_rsi(opens: Sequence[float], period: int) -> List[Optional[float]]:
    """Compute Wilder RSI over ``opens``.

    Args:
        opens: Open prices of the *closed* candles, in chronological order.
        period: The RSI period (``rsi_period``).

    Returns:
        A list the same length as ``opens``. Entries are ``None`` for indices
        where RSI is not yet defined (the first ``period`` candles), and the RSI
        value otherwise. Index ``i`` corresponds to candle ``i``.
    """
    if period < 1:
        raise ValueError(f"rsi_period must be >= 1, got {period}")

    n = len(opens)
    rsi: List[Optional[float]] = [None] * n
    # Need `period` price changes, i.e. `period + 1` opens, before the first RSI.
    if n < period + 1:
        return rsi

    gains = [0.0] * n
    losses = [0.0] * n
    for i in range(1, n):
        change = opens[i] - opens[i - 1]
        if change > 0:
            gains[i] = change
        elif change < 0:
            losses[i] = -change

    # First average = arithmetic mean of the first `period` changes (indices 1..period).
    avg_gain = sum(gains[1 : period + 1]) / period
    avg_loss = sum(losses[1 : period + 1]) / period
    rsi[period] = _rsi_from_averages(avg_gain, avg_loss)

    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rsi[i] = _rsi_from_averages(avg_gain, avg_loss)

    return rsi
