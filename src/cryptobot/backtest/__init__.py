"""Historical backtesting that replays candles through the real trading engine.

The backtester drives the exact same :class:`~cryptobot.runtime.service.TradingService`
used live — same signals, same gates, same exit rules — over a historical candle
series, one tick per candle. It introduces **no** strategy logic; it only replays
data and models fills. Backtest fills are an explicit approximation and never a
substitute for real Binance execution.
"""

from .replay import BacktestClock, ReplayMarketData
from .runner import BacktestReport, BacktestTrade, run_backtest

__all__ = [
    "BacktestClock",
    "ReplayMarketData",
    "BacktestReport",
    "BacktestTrade",
    "run_backtest",
]
