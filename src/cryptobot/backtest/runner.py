"""Run a historical backtest by replaying candles through ``TradingService``.

Every entry/exit decision is made by the exact same engine used live. Fills are
simulated (``PaperExecution`` against the replayed order book); this is an
explicit backtest approximation, never a stand-in for real execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, List, Optional, Sequence

from ..execution.pnl import ExitCostModel
from ..market.candle import Candle
from ..runtime.paper import LedgerAccount, PaperExecution
from ..runtime.providers import equal_slot_quote_amount
from ..runtime.service import OperationalStatus, ServiceConfig, TradingService
from ..strategy.parameters import CoinStrategyParameters
from .replay import BacktestClock, ReplayMarketData


def _as_decimal(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _fixed_sizer(amount: Decimal):
    """A sizing policy returning a fixed quote amount, capped by slots/capital."""

    def size(params: CoinStrategyParameters, slots: int, used) -> Decimal:
        if slots >= params.slot_count:
            return Decimal("0")
        remaining = params.capital_limit_usdt - _as_decimal(used)
        if remaining <= 0:
            return Decimal("0")
        return amount if amount <= remaining else remaining

    return size


@dataclass(frozen=True)
class BacktestTrade:
    """One completed round trip recorded from real engine decisions."""

    symbol: str
    entry_open_time: int
    entry_price: Decimal
    qty: Decimal
    invested_quote: Decimal
    net_pnl: Decimal


@dataclass
class BacktestReport:
    """Aggregate result of a backtest run."""

    symbol: str
    trades: List[BacktestTrade] = field(default_factory=list)
    starting_balance: Decimal = Decimal("0")
    final_balance: Decimal = Decimal("0")
    open_positions: int = 0

    @property
    def num_trades(self) -> int:
        return len(self.trades)

    @property
    def total_net_pnl(self) -> Decimal:
        return sum((t.net_pnl for t in self.trades), Decimal("0"))

    @property
    def wins(self) -> int:
        return sum(1 for t in self.trades if t.net_pnl > 0)

    @property
    def losses(self) -> int:
        return sum(1 for t in self.trades if t.net_pnl < 0)

    @property
    def win_rate(self) -> float:
        return self.wins / self.num_trades if self.trades else 0.0


def run_backtest(
    symbol: str,
    candles: Sequence[Candle],
    params: CoinStrategyParameters,
    *,
    quote_per_order: Optional[Any] = None,
    starting_balance: Any = Decimal("100000"),
    fee_rate: Any = Decimal("0"),
    spread_frac: Any = Decimal("0"),
    safety_buffer_frac: Any = Decimal("0"),
    candle_buffer: Optional[int] = None,
    withdrawal_at_index: Optional[int] = None,
    status: Optional[OperationalStatus] = None,
) -> BacktestReport:
    """Replay ``candles`` through the live engine and return a report.

    Args:
        symbol: The symbol being tested.
        candles: The full historical, contiguous 1-minute series.
        params: The coin's strategy parameters (captured immutably per position).
        quote_per_order: Fixed quote size per entry; defaults to the equal-slot
            sizing policy.
        starting_balance: Initial paper quote balance.
        fee_rate: Per-fill commission rate (quote-denominated) applied to both
            the simulated fills and the exit-decision cost model.
        spread_frac: Half-spread modelling slippage around each candle close.
        safety_buffer_frac: Extra conservative margin in the exit decision.
        candle_buffer: Extra candles fetched beyond the strategy minimum. Defaults
            to the full available history so Wilder indicators are fully warmed;
            a live bot must likewise fetch adequate warmup to match.
        withdrawal_at_index: If set, switches to withdrawal mode at this index.
        status: Operational status supplied each tick (defaults to permissive).
    """
    fee_rate = _as_decimal(fee_rate)
    replay = ReplayMarketData({symbol: candles}, spread_frac=spread_frac)
    clock = BacktestClock()
    execution = PaperExecution(replay, fee_rate=fee_rate)
    account = LedgerAccount(starting_balance)
    cost_model = ExitCostModel(
        exit_fee_rate=fee_rate, safety_buffer_frac=_as_decimal(safety_buffer_frac)
    )
    # Default to full-history lookback so indicators are fully warmed at each tick.
    effective_buffer = len(candles) if candle_buffer is None else candle_buffer
    config = ServiceConfig(
        coins={symbol: params}, cost_model=cost_model, candle_buffer=effective_buffer
    )
    sizing = _fixed_sizer(_as_decimal(quote_per_order)) if quote_per_order is not None else equal_slot_quote_amount
    service = TradingService(replay, execution, account, clock, config, sizing=sizing)

    tick_status = status or OperationalStatus()
    trades: List[BacktestTrade] = []

    for index in range(len(candles)):
        replay.set_index(symbol, index)
        clock.advance_to(candles[index])
        if withdrawal_at_index is not None and index == withdrawal_at_index:
            service.request_withdrawal()

        report = service.tick(tick_status)
        account.apply_report(report)
        for position, pnl in report.exits:
            trades.append(
                BacktestTrade(
                    symbol=position.symbol,
                    entry_open_time=position.entry_candle_open_time,
                    entry_price=position.entry.avg_entry_price,
                    qty=position.entry.filled_base_qty,
                    invested_quote=position.entry.invested_quote_cost,
                    net_pnl=pnl.net_pnl,
                )
            )

    return BacktestReport(
        symbol=symbol,
        trades=trades,
        starting_balance=_as_decimal(starting_balance),
        final_balance=account.available_quote_balance(),
        open_positions=len(service.open_positions(symbol)),
    )
