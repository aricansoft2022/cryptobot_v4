"""Monitoring surface: realized-trade metrics and a live status snapshot.

`MetricsTracker` accumulates realized trades from each tick's exits.
`build_status` combines the currently open positions (with a conservative
unrealized-PnL estimate) and those realized metrics into a JSON-serializable
:class:`StatusSnapshot` for dashboards / health checks. Read-only; no strategy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence

from ..execution.pnl import ExitCostModel, estimate_net_pnl
from .service import TickReport


def _d(value: Decimal) -> str:
    """Serialize a Decimal as a string (JSON-safe, lossless)."""
    return str(value)


@dataclass(frozen=True)
class TradeRecord:
    """A completed round trip, recorded when the position closes."""

    symbol: str
    entry_open_time: int
    entry_price: Decimal
    qty: Decimal
    invested_quote: Decimal
    net_pnl: Decimal
    closed_at_ms: int

    def as_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "entry_open_time": self.entry_open_time,
            "entry_price": _d(self.entry_price),
            "qty": _d(self.qty),
            "invested_quote": _d(self.invested_quote),
            "net_pnl": _d(self.net_pnl),
            "closed_at_ms": self.closed_at_ms,
        }


@dataclass(frozen=True)
class OpenPositionView:
    """A read-only view of one open position for monitoring."""

    symbol: str
    state: str
    entry_price: Decimal
    qty: Decimal
    invested_quote: Decimal
    estimated_net_pnl: Optional[Decimal]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "state": self.state,
            "entry_price": _d(self.entry_price),
            "qty": _d(self.qty),
            "invested_quote": _d(self.invested_quote),
            "estimated_net_pnl": None if self.estimated_net_pnl is None else _d(self.estimated_net_pnl),
        }


class MetricsTracker:
    """Accumulates realized trades from tick reports."""

    def __init__(self) -> None:
        self._trades: List[TradeRecord] = []

    def record_report(self, report: TickReport, now_ms: int) -> None:
        for position, pnl in report.exits:
            self._trades.append(
                TradeRecord(
                    symbol=position.symbol,
                    entry_open_time=position.entry_candle_open_time,
                    entry_price=position.entry.avg_entry_price,
                    qty=position.entry.filled_base_qty,
                    invested_quote=position.entry.invested_quote_cost,
                    net_pnl=pnl.net_pnl,
                    closed_at_ms=now_ms,
                )
            )

    @property
    def trades(self) -> List[TradeRecord]:
        return list(self._trades)

    @property
    def num_trades(self) -> int:
        return len(self._trades)

    @property
    def realized_net_pnl(self) -> Decimal:
        return sum((t.net_pnl for t in self._trades), Decimal("0"))

    @property
    def wins(self) -> int:
        return sum(1 for t in self._trades if t.net_pnl > 0)

    @property
    def losses(self) -> int:
        return sum(1 for t in self._trades if t.net_pnl < 0)

    @property
    def win_rate(self) -> float:
        return self.wins / self.num_trades if self._trades else 0.0


@dataclass(frozen=True)
class StatusSnapshot:
    """A point-in-time monitoring snapshot of the running bot."""

    generated_at_ms: int
    available_quote: Decimal
    open_positions: List[OpenPositionView]
    open_invested_quote: Decimal
    estimated_unrealized_net_pnl: Decimal
    realized_trades: int
    realized_net_pnl: Decimal
    wins: int
    losses: int
    win_rate: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "generated_at_ms": self.generated_at_ms,
            "available_quote": _d(self.available_quote),
            "open_positions": [p.as_dict() for p in self.open_positions],
            "open_invested_quote": _d(self.open_invested_quote),
            "estimated_unrealized_net_pnl": _d(self.estimated_unrealized_net_pnl),
            "realized_trades": self.realized_trades,
            "realized_net_pnl": _d(self.realized_net_pnl),
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": self.win_rate,
        }


def build_status(
    symbols: Sequence[str],
    service,
    account,
    market_data,
    cost_model: ExitCostModel,
    metrics: MetricsTracker,
    now_ms: int,
) -> StatusSnapshot:
    """Assemble a :class:`StatusSnapshot` from live service/account/market state.

    Unrealized PnL uses the same conservative estimator as the exit decision,
    against the current order book. Positions with no book depth report ``None``.
    """
    views: List[OpenPositionView] = []
    open_invested = Decimal("0")
    unrealized = Decimal("0")

    for symbol in symbols:
        for position in service.open_positions(symbol):
            book = market_data.get_order_book(symbol)
            estimated: Optional[Decimal] = None
            if book.bids:
                estimated = estimate_net_pnl(position, book, cost_model).net_pnl
                unrealized += estimated
            open_invested += position.entry.invested_quote_cost
            views.append(
                OpenPositionView(
                    symbol=symbol,
                    state=position.state.value,
                    entry_price=position.entry.avg_entry_price,
                    qty=position.entry.filled_base_qty,
                    invested_quote=position.entry.invested_quote_cost,
                    estimated_net_pnl=estimated,
                )
            )

    return StatusSnapshot(
        generated_at_ms=now_ms,
        available_quote=account.available_quote_balance(),
        open_positions=views,
        open_invested_quote=open_invested,
        estimated_unrealized_net_pnl=unrealized,
        realized_trades=metrics.num_trades,
        realized_net_pnl=metrics.realized_net_pnl,
        wins=metrics.wins,
        losses=metrics.losses,
        win_rate=metrics.win_rate,
    )
