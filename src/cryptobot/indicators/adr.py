"""ADR: average high-low range over the candles *preceding* the current one.

.. code-block:: text

    ADR[t] = average(high[i] - low[i])   for i in [t - adr_period, t)

The current candle ``t`` is intentionally **excluded** from its own ADR — the
window is the ``adr_period`` candles immediately before ``t``.
"""

from __future__ import annotations

from typing import List, Optional, Sequence


def compute_adr(
    highs: Sequence[float],
    lows: Sequence[float],
    period: int,
) -> List[Optional[float]]:
    """Compute ADR aligned to the candle series.

    Args:
        highs, lows: Aligned high/low of the *closed* candles.
        period: The ADR period (``adr_period``).

    Returns:
        A list the same length as the inputs. ``ADR[t]`` is ``None`` until there
        are ``period`` candles strictly before ``t`` (i.e. for ``t < period``).
    """
    if period < 1:
        raise ValueError(f"adr_period must be >= 1, got {period}")
    if len(highs) != len(lows):
        raise ValueError("highs and lows must have the same length")

    n = len(highs)
    out: List[Optional[float]] = [None] * n
    ranges = [highs[i] - lows[i] for i in range(n)]

    for t in range(period, n):
        # Window [t - period, t): excludes the current candle t.
        window = ranges[t - period : t]
        out[t] = sum(window) / period

    return out
