"""Operational safety gates between a technical signal and a real order.

A technical BUY signal is *necessary* but not *sufficient*. A real order may be
placed only when every operational gate is open. These gates depend on live
infrastructure (runtime state, balances, Binance symbol filters, worker leases,
reconciliation, …); this module models them as explicit booleans so the decision
is auditable and testable. The data sources are injected by the runtime.

Idempotency: the same coin and the same closed candle must never produce a
second BUY, even across restarts or retries. :class:`ProcessedCandleGuard`
enforces that.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from decimal import Decimal
from typing import TYPE_CHECKING, List, Set, Tuple

if TYPE_CHECKING:  # avoid a runtime import cycle (execution <-> strategy)
    from ..strategy.parameters import CoinStrategyParameters


@dataclass(frozen=True)
class OperationalGates:
    """Every operational precondition required to turn a signal into a buy.

    All fields must be ``True`` for :meth:`all_open` to return ``True``. Each
    field maps directly to a spec requirement.
    """

    runtime_running: bool           # global runtime is RUNNING
    trading_enabled: bool           # trading explicitly enabled
    coin_active: bool               # coin is active
    coin_not_pending_delete: bool   # coin not marked for deletion
    market_data_fresh: bool         # market data is current, not stale
    candles_contiguous: bool        # candle series is contiguous
    indicators_ready: bool          # all required indicators are ready
    not_already_processed: bool     # this coin+candle not already handled
    slot_available: bool            # open+reserved slots < slot_count
    capital_available: bool         # used capital < capital_limit_usdt
    usdt_balance_sufficient: bool   # real available USDT is enough
    symbol_filters_ok: bool         # Binance symbol filters accept the order
    worker_holds_lease: bool        # worker holds a valid lease
    reconciliation_clean: bool      # reconciliation is clean
    system_safe: bool               # system is in a safe state

    def all_open(self) -> bool:
        """True only if every gate is open."""
        return all(getattr(self, f.name) for f in fields(self))

    def blocked_reasons(self) -> List[str]:
        """Names of all gates that are currently closed."""
        return [f.name for f in fields(self) if not getattr(self, f.name)]


class ProcessedCandleGuard:
    """Idempotency guard keyed by ``(symbol, candle_open_time)``.

    Ensures a given coin and closed candle can trigger at most one entry, so a
    restart or retry cannot create a duplicate BUY.
    """

    def __init__(self) -> None:
        self._seen: Set[Tuple[str, int]] = set()

    def already_processed(self, symbol: str, candle_open_time: int) -> bool:
        return (symbol, candle_open_time) in self._seen

    def mark_processed(self, symbol: str, candle_open_time: int) -> None:
        self._seen.add((symbol, candle_open_time))

    def __len__(self) -> int:
        return len(self._seen)


def slots_below_limit(open_and_reserved: int, params: "CoinStrategyParameters") -> bool:
    """Spec gate: open + reserved slot count is below ``slot_count``."""
    return open_and_reserved < params.slot_count


def capital_below_limit(used_capital_usdt, params: "CoinStrategyParameters") -> bool:
    """Spec gate: the coin's used capital is below ``capital_limit_usdt``."""
    used = used_capital_usdt if isinstance(used_capital_usdt, Decimal) else Decimal(str(used_capital_usdt))
    return used < params.capital_limit_usdt
