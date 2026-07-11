"""Normal and withdrawal-mode exit rules.

**Normal exit is two-phase.** A position is never sold just because price went
up, nor sold directly just because RSI rose.

* Phase 1 — RSI arming: on a closed candle ``t``, ``RSI[t] > snapshot.rsi_overbought``
  (strict) moves the position to ``EXIT_ARMED``. Arming is **permanent**; a later
  RSI drop never disarms it, and RSI is never re-checked to cancel a sell.
* Phase 2 — minimum net profit: once armed, the position is watched on the live
  market. A market SELL is sent only when the conservative estimated net PnL
  reaches the target:

  .. code-block:: text

      estimated_net_pnl_usdt >= invested_quote_cost_usdt * min_net_profit_pct / 100

**There is no stop-loss** of any kind.

**Withdrawal mode** (global ``WITHDRAWAL_REQUESTED``): new entries stop; open
positions ignore RSI/arming entirely and are sold as soon as their conservative
net PnL reaches a fixed 0.20% of invested quote cost. Positions below the
threshold are not sold at a loss.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Sequence

from ..execution.orderbook import OrderBook
from ..execution.pnl import ExitCostModel, PnLEstimate, estimate_net_pnl
from ..market.candle import Candle
from ..market.validation import validate_series
from .indicators import compute_indicators
from .position import PositionState, StrategyPosition

#: Fixed minimum net profit (percent) required to exit in withdrawal mode.
WITHDRAWAL_MIN_NET_PROFIT_PCT: Decimal = Decimal("0.20")


@dataclass(frozen=True)
class ExitDecision:
    """Outcome of an exit evaluation."""

    sell: bool
    reason: str
    target_net_pnl: Optional[Decimal] = None
    estimate: Optional[PnLEstimate] = None


def update_exit_arming(
    position: StrategyPosition,
    candles: Sequence[Candle],
) -> bool:
    """Phase 1: arm the exit if the last closed candle's RSI is overbought.

    Reads ``rsi_overbought`` from the position's *snapshot* (never live coin
    settings). Returns ``True`` if the position is armed after this call.

    Arming is permanent: an already-armed position stays armed and its RSI is not
    re-evaluated. On invalid data or an undefined RSI, arming does not occur
    (fail-closed), but an existing armed state is preserved.
    """
    if position.state is PositionState.EXIT_ARMED:
        return True
    if position.state is PositionState.CLOSED:
        return False

    if validate_series(candles):
        return False  # fail-closed on invalid/stale data
    if len(candles) < 1:
        return False

    t = len(candles) - 1
    series = compute_indicators(candles, position.snapshot)
    rsi_t = series.rsi[t]
    if rsi_t is None:
        return False  # indicator not ready -> no arming

    # Strict: equality does not arm.
    if rsi_t > position.snapshot.rsi_overbought:
        position.arm_exit(candles[t].open_time)
        return True
    return False


def _target_net_pnl(invested_quote_cost: Decimal, pct: Decimal) -> Decimal:
    return invested_quote_cost * pct / Decimal("100")


def should_sell_normal(
    position: StrategyPosition,
    order_book: OrderBook,
    cost_model: ExitCostModel,
) -> ExitDecision:
    """Phase 2: decide whether to market-SELL an armed position for net profit.

    A position that is not yet ``EXIT_ARMED`` is never sold here.
    """
    if position.state is not PositionState.EXIT_ARMED:
        return ExitDecision(
            sell=False,
            reason=f"position is {position.state.value}, not EXIT_ARMED",
        )

    estimate = estimate_net_pnl(position, order_book, cost_model)
    target = _target_net_pnl(
        position.entry.invested_quote_cost,
        Decimal(position.snapshot.min_net_profit_pct),
    )
    if estimate.net_pnl >= target:
        return ExitDecision(
            sell=True,
            reason="EXIT_ARMED and estimated net profit target reached",
            target_net_pnl=target,
            estimate=estimate,
        )
    return ExitDecision(
        sell=False,
        reason="EXIT_ARMED but estimated net profit below target",
        target_net_pnl=target,
        estimate=estimate,
    )


def should_sell_withdrawal(
    position: StrategyPosition,
    order_book: OrderBook,
    cost_model: ExitCostModel,
) -> ExitDecision:
    """Withdrawal mode: sell as soon as conservative net PnL reaches 0.20%.

    RSI and ``EXIT_ARMED`` are ignored entirely. Positions below the threshold
    are held (never sold at a loss).
    """
    estimate = estimate_net_pnl(position, order_book, cost_model)
    target = _target_net_pnl(
        position.entry.invested_quote_cost,
        WITHDRAWAL_MIN_NET_PROFIT_PCT,
    )
    if estimate.net_pnl >= target:
        return ExitDecision(
            sell=True,
            reason="withdrawal mode: net profit >= 0.20% of invested cost",
            target_net_pnl=target,
            estimate=estimate,
        )
    return ExitDecision(
        sell=False,
        reason="withdrawal mode: net profit below 0.20% threshold",
        target_net_pnl=target,
        estimate=estimate,
    )
