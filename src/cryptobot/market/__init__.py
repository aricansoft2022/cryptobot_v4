"""Market data primitives: the closed-candle model and strict series validation."""

from .candle import INTERVAL_MS, Candle
from .validation import (
    CandleSeriesError,
    ensure_valid_series,
    validate_series,
)

__all__ = [
    "INTERVAL_MS",
    "Candle",
    "CandleSeriesError",
    "ensure_valid_series",
    "validate_series",
]
