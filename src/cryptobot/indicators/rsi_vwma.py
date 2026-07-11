"""RSI-VWMA: the volume-weighted moving average of RSI values.

.. code-block:: text

    RSI_VWMA[t] = sum(RSI[i] * volume[i]) / sum(volume[i])
    window: [t - rsi_ma_period + 1, t]

If the total volume over the window is zero, the indicator must *fail closed*:
no synthetic value is produced, so no signal can be derived from it.
"""

from __future__ import annotations

from typing import List, Optional, Sequence


def compute_rsi_vwma(
    rsi: Sequence[Optional[float]],
    volumes: Sequence[float],
    period: int,
) -> List[Optional[float]]:
    """Compute the volume-weighted moving average of ``rsi``.

    Args:
        rsi: RSI values aligned to the candle series (``None`` where undefined).
        volumes: Base-asset volumes aligned to the same candle series.
        period: The averaging window length (``rsi_ma_period``).

    Returns:
        A list the same length as ``rsi``. An entry is ``None`` when the window
        extends before the series start, when any RSI in the window is ``None``,
        or when the window's total volume is zero (fail-closed).
    """
    if period < 1:
        raise ValueError(f"rsi_ma_period must be >= 1, got {period}")
    if len(rsi) != len(volumes):
        raise ValueError("rsi and volumes must have the same length")

    n = len(rsi)
    out: List[Optional[float]] = [None] * n

    for t in range(n):
        start = t - period + 1
        if start < 0:
            continue

        window_rsi = rsi[start : t + 1]
        if any(value is None for value in window_rsi):
            continue

        window_vol = volumes[start : t + 1]
        total_volume = sum(window_vol)
        if total_volume == 0:
            # Fail-closed: never fabricate a value when there is no volume.
            continue

        weighted = sum(r * v for r, v in zip(window_rsi, window_vol))
        out[t] = weighted / total_volume

    return out
