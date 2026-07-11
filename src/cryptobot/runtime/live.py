"""Live-execution wiring: real account, reconciliation, and a guarded runner.

This turns the service into a real trader by supplying a Binance-backed
``AccountPort`` and a reconciliation check that feeds the ``reconciliation_clean``
gate. Order placement itself is the already-built ``BinanceExecution``.

Safety is explicit and layered:

* credentials are read from the environment by the caller, never stored here;
* the reconciliation gate halts trading whenever the bot's tracked base holdings
  diverge from the exchange (crash, partial fill, or manual intervention);
* the CLI refuses to trade real money without an explicit acknowledgement.

Single-process operation assumes the worker lease is always held; a multi-instance
deployment must supply a real distributed lease instead of the default.
"""

from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from ..exchange.binance_rest import (
    BinanceExecution,
    BinanceMarketData,
    BinanceRestClient,
)
from ..strategy.position import StrategyPosition
from .orchestrator import split_symbol
from .providers import SystemClock
from .service import OperationalStatus, ServiceConfig, TickReport, TradingService


def _as_decimal(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


class BinanceAccount:
    """An ``AccountPort`` backed by the real Binance account.

    Available quote balance is fetched from the exchange (refresh once per tick);
    committed capital and slot counts are tracked from the bot's own fills via
    :meth:`apply_report`.
    """

    def __init__(self, client: BinanceRestClient, quote_asset: str = "USDT") -> None:
        self._client = client
        self._quote_asset = quote_asset
        self._balance: Optional[Decimal] = None
        self._used: Dict[str, Decimal] = {}
        self._slots: Dict[str, int] = {}

    def refresh_balance(self, account: Optional[Mapping[str, Any]] = None) -> Decimal:
        """Cache the free quote-asset balance (fetches account if not supplied)."""
        if account is None:
            account = self._client.account()
        balance = Decimal("0")
        for entry in account.get("balances", []):
            if entry.get("asset") == self._quote_asset:
                balance = _as_decimal(entry.get("free", "0"))
                break
        self._balance = balance
        return balance

    def available_quote_balance(self) -> Decimal:
        if self._balance is None:
            self.refresh_balance()
        return self._balance

    def used_capital(self, symbol: str) -> Decimal:
        return self._used.get(symbol, Decimal("0"))

    def open_and_reserved_slots(self, symbol: str) -> int:
        return self._slots.get(symbol, 0)

    def apply_report(self, report: TickReport) -> None:
        for position in report.entries:
            self._used[position.symbol] = self.used_capital(position.symbol) + position.entry.invested_quote_cost
            self._slots[position.symbol] = self.open_and_reserved_slots(position.symbol) + 1
        for position, _pnl in report.exits:
            self._used[position.symbol] = self.used_capital(position.symbol) - position.entry.invested_quote_cost
            self._slots[position.symbol] = max(0, self.open_and_reserved_slots(position.symbol) - 1)


@dataclass(frozen=True)
class ReconcileResult:
    """Outcome of comparing tracked positions against exchange balances."""

    clean: bool
    problems: List[str]


def reconcile_positions(
    client: BinanceRestClient,
    positions_by_symbol: Mapping[str, Sequence[StrategyPosition]],
    tolerance: Any = Decimal("0.02"),
    account: Optional[Mapping[str, Any]] = None,
) -> ReconcileResult:
    """Verify the exchange holds at least the base quantity the bot expects.

    A shortfall beyond ``tolerance`` (fractional) — e.g. from a manual sale or an
    unexpected fill — marks reconciliation dirty so trading is halted. Pass a
    pre-fetched ``account`` to avoid an extra REST call.
    """
    tol = _as_decimal(tolerance)
    if account is None:
        account = client.account()
    free = {b.get("asset"): _as_decimal(b.get("free", "0")) for b in account.get("balances", [])}

    problems: List[str] = []
    for symbol, positions in positions_by_symbol.items():
        expected = sum((p.entry.sellable_base_qty for p in positions), Decimal("0"))
        if expected <= 0:
            continue
        base_asset, _quote = split_symbol(symbol)
        actual = free.get(base_asset, Decimal("0"))
        if actual < expected * (Decimal("1") - tol):
            problems.append(
                f"{symbol}: exchange {base_asset} balance {actual} < expected {expected}"
            )
    return ReconcileResult(clean=not problems, problems=problems)


def build_live_service(
    client: BinanceRestClient,
    config: ServiceConfig,
    quote_asset: str = "USDT",
    interval: str = "1m",
):
    """Wire a real-money :class:`TradingService` from a signed client."""
    clock = SystemClock()
    market_data = BinanceMarketData(client, clock, interval)
    execution = BinanceExecution(client)
    account = BinanceAccount(client, quote_asset)
    service = TradingService(market_data, execution, account, clock, config)
    return service, account


def run_live(
    service: TradingService,
    account: BinanceAccount,
    client: BinanceRestClient,
    symbols: Sequence[str],
    *,
    ticks: Optional[int] = None,
    interval_s: float = 60.0,
    base_status: Optional[OperationalStatus] = None,
    reconcile_tolerance: Any = Decimal("0.02"),
    sleep_fn: Callable[[float], None] = time.sleep,
    on_report: Optional[Callable[[int, TickReport, "ReconcileResult"], None]] = None,
) -> None:
    """Run the live loop with a reconciliation gate on every tick.

    Each tick: refresh the real balance, reconcile tracked positions against the
    exchange, and run the service with ``reconciliation_clean`` set from that
    check. A dirty reconciliation keeps the gate closed so no order is placed.
    """
    base = base_status or OperationalStatus()
    i = 0
    while ticks is None or i < ticks:
        raw_account = client.account()
        account.refresh_balance(raw_account)
        positions = {s: service.open_positions(s) for s in symbols}
        recon = reconcile_positions(client, positions, reconcile_tolerance, account=raw_account)
        status = dataclasses.replace(base, reconciliation_clean=recon.clean)

        report = service.tick(status)
        account.apply_report(report)
        if on_report is not None:
            on_report(i, report, recon)
        i += 1
        if ticks is None or i < ticks:
            sleep_fn(interval_s)
