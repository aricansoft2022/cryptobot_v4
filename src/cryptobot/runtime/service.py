"""A config-driven trading service: the per-coin scheduler loop.

`TradingService` turns the deterministic core plus the injected ports into an
actual running process. Each ``tick`` it evaluates entries for every configured
coin and exits for every open position, building the operational gates from live
account/data state. It performs no strategy reasoning of its own — it only
composes the existing `evaluate_buy` / `evaluate_exit` decisions (via
`TradingRuntime`) with sizing, gate construction, and position bookkeeping.

Infrastructure signals the service cannot derive (runtime RUNNING, trading
enabled, worker lease, reconciliation, system safety, per-coin active /
pending-delete) are supplied each tick as an :class:`OperationalStatus`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Dict, List, Mapping, Optional, Tuple

from ..execution.gates import OperationalGates, ProcessedCandleGuard
from ..execution.pnl import ExitCostModel
from ..exchange.fills import RealizedPnL
from ..exchange.filters import SymbolFilters
from ..market.candle import INTERVAL_MS
from ..market.validation import is_valid_series
from ..strategy.engine import RuntimeMode
from ..strategy.parameters import CoinStrategyParameters
from ..strategy.position import StrategyPosition
from .orchestrator import TradingRuntime
from .ports import AccountPort, ClockPort, ExecutionPort, MarketDataPort
from .providers import equal_slot_quote_amount, is_market_data_fresh

SizingPolicy = Callable[[CoinStrategyParameters, int, Decimal], Decimal]


@dataclass(frozen=True)
class OperationalStatus:
    """Infra-level signals the service cannot derive from market/account data.

    Defaults are permissive so tests and simple deployments can pass an empty
    status; a real deployment supplies the live values every tick.
    """

    runtime_running: bool = True
    trading_enabled: bool = True
    worker_holds_lease: bool = True
    reconciliation_clean: bool = True
    system_safe: bool = True
    inactive_coins: frozenset = frozenset()
    pending_delete_coins: frozenset = frozenset()


@dataclass(frozen=True)
class ServiceConfig:
    """Static configuration for a :class:`TradingService`."""

    coins: Mapping[str, CoinStrategyParameters]
    cost_model: ExitCostModel
    candle_buffer: int = 5
    max_data_lag_ms: int = 2 * INTERVAL_MS
    filters: Mapping[str, SymbolFilters] = field(default_factory=dict)
    commission_rates: Optional[Mapping[str, Decimal]] = None


@dataclass
class TickReport:
    """What happened during one :meth:`TradingService.tick`."""

    entries: List[StrategyPosition] = field(default_factory=list)
    exits: List[Tuple[StrategyPosition, RealizedPnL]] = field(default_factory=list)


class TradingService:
    """Drives entries and exits for a set of coins over successive ticks."""

    def __init__(
        self,
        market_data: MarketDataPort,
        execution: ExecutionPort,
        account: AccountPort,
        clock: ClockPort,
        config: ServiceConfig,
        sizing: SizingPolicy = equal_slot_quote_amount,
    ) -> None:
        self._md = market_data
        self._account = account
        self._clock = clock
        self._config = config
        self._sizing = sizing
        self._guard = ProcessedCandleGuard()
        self._runtime = TradingRuntime(
            market_data, execution, guard=self._guard,
            candle_lookback_buffer=config.candle_buffer,
        )
        self._positions: Dict[str, List[StrategyPosition]] = {s: [] for s in config.coins}
        self._mode = RuntimeMode.RUNNING

    # -- mode ---------------------------------------------------------------

    @property
    def mode(self) -> RuntimeMode:
        return self._mode

    def request_withdrawal(self) -> None:
        """Enter withdrawal mode: stop new entries; exit on the 0.20% rule."""
        self._mode = RuntimeMode.WITHDRAWAL_REQUESTED

    def resume(self) -> None:
        """Return to normal RUNNING mode."""
        self._mode = RuntimeMode.RUNNING

    def open_positions(self, symbol: str) -> List[StrategyPosition]:
        return list(self._positions.get(symbol, []))

    # -- internals ----------------------------------------------------------

    def _candle_limit(self, params: CoinStrategyParameters) -> int:
        return params.min_candles_for_signal + self._config.candle_buffer

    def _order_size(self, symbol: str, params: CoinStrategyParameters) -> Decimal:
        return self._sizing(
            params,
            self._account.open_and_reserved_slots(symbol),
            self._account.used_capital(symbol),
        )

    def _symbol_filters_ok(self, symbol: str, order_quote: Decimal) -> bool:
        filt = self._config.filters.get(symbol)
        if filt is None:
            return True
        # Market BUY by quote amount: Binance derives the base qty, so the
        # binding check is the minimum notional.
        return order_quote >= filt.min_notional

    def _build_gates(
        self,
        symbol: str,
        params: CoinStrategyParameters,
        candles,
        order_quote: Decimal,
        status: OperationalStatus,
    ) -> OperationalGates:
        now = self._clock.now_ms()
        last_open_time = candles[-1].open_time if candles else None
        return OperationalGates(
            runtime_running=status.runtime_running,
            trading_enabled=status.trading_enabled,
            coin_active=symbol not in status.inactive_coins,
            coin_not_pending_delete=symbol not in status.pending_delete_coins,
            market_data_fresh=is_market_data_fresh(candles, now, self._config.max_data_lag_ms),
            candles_contiguous=is_valid_series(candles),
            indicators_ready=len(candles) >= params.min_candles_for_signal,
            not_already_processed=(
                last_open_time is not None
                and not self._guard.already_processed(symbol, last_open_time)
            ),
            slot_available=self._account.open_and_reserved_slots(symbol) < params.slot_count,
            capital_available=self._account.used_capital(symbol) < params.capital_limit_usdt,
            usdt_balance_sufficient=(
                order_quote > 0 and self._account.available_quote_balance() >= order_quote
            ),
            symbol_filters_ok=self._symbol_filters_ok(symbol, order_quote),
            worker_holds_lease=status.worker_holds_lease,
            reconciliation_clean=status.reconciliation_clean,
            system_safe=status.system_safe,
        )

    # -- the loop -----------------------------------------------------------

    def tick(self, status: OperationalStatus = OperationalStatus()) -> TickReport:
        """Run one iteration: evaluate entries, then exits, for every coin."""
        report = TickReport()

        entries_allowed = (
            self._mode is RuntimeMode.RUNNING
            and status.runtime_running
            and status.trading_enabled
        )
        if entries_allowed:
            for symbol, params in self._config.coins.items():
                candles = self._md.get_closed_candles(symbol, self._candle_limit(params))
                order_quote = self._order_size(symbol, params)
                gates = self._build_gates(symbol, params, candles, order_quote, status)
                position = self._runtime.try_enter(
                    symbol, params, gates, order_quote, self._mode,
                    self._config.commission_rates, candles=candles,
                )
                if position is not None:
                    self._positions[symbol].append(position)
                    report.entries.append(position)

        for symbol, params in self._config.coins.items():
            open_positions = self._positions.get(symbol, [])
            if not open_positions:
                continue
            candles = self._md.get_closed_candles(symbol, self._candle_limit(params))
            order_book = self._md.get_order_book(symbol)
            still_open: List[StrategyPosition] = []
            for position in open_positions:
                pnl = self._runtime.try_exit(
                    position, self._config.cost_model, self._mode,
                    self._config.filters.get(symbol), self._config.commission_rates,
                    candles=candles, order_book=order_book,
                )
                if pnl is not None:
                    report.exits.append((position, pnl))
                else:
                    still_open.append(position)
            self._positions[symbol] = still_open

        return report

    def run(
        self,
        ticks: int,
        status_provider: Optional[Callable[[], OperationalStatus]] = None,
        sleep_fn: Optional[Callable[[float], None]] = None,
        interval_s: float = 1.0,
    ) -> List[TickReport]:
        """Run ``ticks`` iterations, sleeping between them via ``sleep_fn``.

        ``status_provider`` yields the live :class:`OperationalStatus` each tick
        (defaults to a permissive status). ``sleep_fn`` is injected so tests run
        with no real delay. Returns the per-tick reports.
        """
        reports: List[TickReport] = []
        for i in range(ticks):
            status = status_provider() if status_provider else OperationalStatus()
            reports.append(self.tick(status))
            if sleep_fn is not None and i < ticks - 1:
                sleep_fn(interval_s)
        return reports
