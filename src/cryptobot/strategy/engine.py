"""Top-level orchestration: signal + gates -> buy intent, and exit routing.

This layer combines the pure technical signal with the operational safety gates
and the per-candle idempotency guard, and routes exit evaluation to the normal
or withdrawal-mode rules based on the global runtime mode. It performs no I/O:
market data, gate states and order books are supplied by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Sequence

from ..execution.gates import OperationalGates, ProcessedCandleGuard
from ..execution.orderbook import OrderBook
from ..execution.pnl import ExitCostModel
from ..market.candle import Candle
from .entry import EntryEvaluation, evaluate_entry_signal
from .exit import (
    ExitDecision,
    should_sell_normal,
    should_sell_withdrawal,
    update_exit_arming,
)
from .parameters import CoinStrategyParameters
from .position import StrategyPosition


class RuntimeMode(str, Enum):
    """Global runtime mode governing entries and exit rules."""

    RUNNING = "RUNNING"
    WITHDRAWAL_REQUESTED = "WITHDRAWAL_REQUESTED"


@dataclass(frozen=True)
class BuyDecision:
    """Whether a real BUY should be placed, and why."""

    buy: bool
    reason: str
    evaluation: EntryEvaluation
    gates_open: bool
    already_processed: bool


def evaluate_buy(
    symbol: str,
    candles: Sequence[Candle],
    params: CoinStrategyParameters,
    gates: OperationalGates,
    guard: Optional[ProcessedCandleGuard] = None,
    mode: RuntimeMode = RuntimeMode.RUNNING,
) -> BuyDecision:
    """Decide whether the last closed candle should produce a real BUY.

    A BUY requires *all* of: withdrawal mode inactive, the technical entry
    signal, every operational gate open, and the coin+candle not already
    processed. The caller is responsible for marking the candle processed via
    :meth:`ProcessedCandleGuard.mark_processed` once it acts on a buy.
    """
    evaluation = evaluate_entry_signal(candles, params)

    if mode is RuntimeMode.WITHDRAWAL_REQUESTED:
        return BuyDecision(
            buy=False,
            reason="withdrawal mode: no new entries",
            evaluation=evaluation,
            gates_open=False,
            already_processed=False,
        )

    already_processed = False
    if guard is not None and evaluation.candle_open_time is not None:
        already_processed = guard.already_processed(
            symbol, evaluation.candle_open_time
        )

    gates_open = gates.all_open()

    if not evaluation.signal:
        reason = evaluation.reason
    elif already_processed:
        reason = "entry signal present but coin+candle already processed"
    elif not gates_open:
        reason = "entry signal present but gates closed: " + ", ".join(
            gates.blocked_reasons()
        )
    else:
        reason = "buy: entry signal and all operational gates open"

    buy = bool(evaluation.signal) and gates_open and not already_processed
    return BuyDecision(
        buy=buy,
        reason=reason,
        evaluation=evaluation,
        gates_open=gates_open,
        already_processed=already_processed,
    )


def evaluate_exit(
    position: StrategyPosition,
    candles: Sequence[Candle],
    order_book: OrderBook,
    cost_model: ExitCostModel,
    mode: RuntimeMode = RuntimeMode.RUNNING,
) -> ExitDecision:
    """Evaluate whether ``position`` should be sold, per the active mode.

    In :attr:`RuntimeMode.RUNNING` this first updates permanent RSI arming from
    the closed candles, then applies the minimum-net-profit rule. In
    :attr:`RuntimeMode.WITHDRAWAL_REQUESTED` it ignores RSI/arming and applies the
    fixed 0.20% net-profit rule.
    """
    if mode is RuntimeMode.WITHDRAWAL_REQUESTED:
        return should_sell_withdrawal(position, order_book, cost_model)

    update_exit_arming(position, candles)
    return should_sell_normal(position, order_book, cost_model)
