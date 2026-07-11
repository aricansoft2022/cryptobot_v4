"""Thin orchestration that composes the decision core with injected ports.

The runtime does not make strategy decisions — it only *coordinates* the existing
deterministic functions (``evaluate_buy`` / ``evaluate_exit``) with market data,
execution and the operational gates. Order sizing and gate construction are
supplied by the caller (operational concerns), so no signal logic lives here.
"""

from __future__ import annotations

from decimal import Decimal
from typing import List, Optional, Sequence

from ..execution.gates import OperationalGates, ProcessedCandleGuard
from ..execution.pnl import ExitCostModel
from ..exchange.fills import Fill, RealizedPnL, aggregate_entry, realized_pnl
from ..exchange.filters import SymbolFilters
from ..strategy.engine import RuntimeMode, evaluate_buy, evaluate_exit
from ..strategy.parameters import CoinStrategyParameters
from ..strategy.position import StrategyPosition, open_position
from .ports import ExecutionPort, MarketDataPort

#: Binance quote assets, longest-first, used to split a symbol into base/quote.
_DEFAULT_QUOTES: Sequence[str] = ("USDT", "FDUSD", "USDC", "TUSD", "BUSD", "BTC", "ETH", "BNB")


def split_symbol(symbol: str, quotes: Sequence[str] = _DEFAULT_QUOTES) -> tuple[str, str]:
    """Split e.g. ``"BTCUSDT"`` into ``("BTC", "USDT")``.

    Tries the known quote assets longest-first. Raises if none match.
    """
    for quote in sorted(quotes, key=len, reverse=True):
        if symbol.endswith(quote) and len(symbol) > len(quote):
            return symbol[: -len(quote)], quote
    raise ValueError(f"cannot determine base/quote assets for symbol {symbol!r}")


class TradingRuntime:
    """Coordinates entry and exit for one account across symbols.

    Args:
        market_data: Candle / order-book source.
        execution: Order placement returning real fills.
        guard: Per-candle idempotency guard (shared across calls).
        candle_lookback_buffer: Extra candles fetched beyond the strategy minimum.
    """

    def __init__(
        self,
        market_data: MarketDataPort,
        execution: ExecutionPort,
        guard: Optional[ProcessedCandleGuard] = None,
        candle_lookback_buffer: int = 5,
    ) -> None:
        self._market_data = market_data
        self._execution = execution
        self._guard = guard or ProcessedCandleGuard()
        self._buffer = max(0, candle_lookback_buffer)

    @property
    def guard(self) -> ProcessedCandleGuard:
        return self._guard

    def _fetch_candles(self, symbol: str, params: CoinStrategyParameters):
        limit = params.min_candles_for_signal + self._buffer
        return self._market_data.get_closed_candles(symbol, limit)

    def try_enter(
        self,
        symbol: str,
        params: CoinStrategyParameters,
        gates: OperationalGates,
        quote_amount: Decimal,
        mode: RuntimeMode = RuntimeMode.RUNNING,
        commission_rates=None,
    ) -> Optional[StrategyPosition]:
        """Evaluate entry; if a real buy is warranted, place it and open a position.

        ``quote_amount`` is the operational order size (must already respect the
        coin's ``capital_limit_usdt`` / ``slot_count``); this method does not size
        the order itself. Returns the opened position, or ``None`` if no buy.
        """
        candles = self._fetch_candles(symbol, params)
        decision = evaluate_buy(symbol, candles, params, gates, self._guard, mode)
        if not decision.buy:
            return None

        base_asset, quote_asset = split_symbol(symbol)
        fills = self._execution.market_buy(symbol, quote_amount)
        entry = aggregate_entry(fills, base_asset, quote_asset, commission_rates)

        candle_open_time = decision.evaluation.candle_open_time
        position = open_position(symbol, params, entry, candle_open_time)
        # Idempotency: this coin+candle must never produce a second buy.
        self._guard.mark_processed(symbol, candle_open_time)
        return position

    def try_exit(
        self,
        position: StrategyPosition,
        cost_model: ExitCostModel,
        mode: RuntimeMode = RuntimeMode.RUNNING,
        filters: Optional[SymbolFilters] = None,
        commission_rates=None,
    ) -> Optional[RealizedPnL]:
        """Evaluate exit; if a sell is warranted, place it and realize PnL.

        With ``filters`` provided, the sell quantity is floored to the symbol's
        ``stepSize`` before submission. Returns realized PnL, or ``None`` if hold.
        """
        candles = self._fetch_candles(position.symbol, position.snapshot)
        order_book = self._market_data.get_order_book(position.symbol)
        decision = evaluate_exit(position, candles, order_book, cost_model, mode)
        if not decision.sell:
            return None

        base_asset, quote_asset = split_symbol(position.symbol)
        sell_qty = position.entry.sellable_base_qty
        if filters is not None:
            sell_qty = filters.round_quantity(sell_qty)

        fills: List[Fill] = self._execution.market_sell(position.symbol, sell_qty)
        pnl = realized_pnl(position.entry, fills, base_asset, quote_asset, commission_rates)
        position.mark_closed()
        return pnl
