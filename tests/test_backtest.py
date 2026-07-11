"""Tests for the historical backtester (replay through the real engine)."""

from __future__ import annotations

from decimal import Decimal

from cryptobot.backtest import run_backtest
from cryptobot.backtest.replay import BacktestClock, ReplayMarketData

from ._helpers import default_params, make_candles
from .test_entry import (
    FIXTURE_CLOSES,
    FIXTURE_HIGHS,
    FIXTURE_LOWS,
    FIXTURE_OPENS,
    FIXTURE_VOLS,
)


def _round_trip_candles():
    """Fixture that enters at index 7, then rises so the exit arms and profits."""
    opens = list(FIXTURE_OPENS)
    highs = list(FIXTURE_HIGHS)
    lows = list(FIXTURE_LOWS)
    closes = list(FIXTURE_CLOSES)
    vols = list(FIXTURE_VOLS)
    for k in range(1, 9):
        o = 101.69 + 6 * k
        opens.append(o)
        highs.append(o + 2)
        lows.append(o - 2)
        closes.append(o + 1)
        vols.append(5.0)
    return make_candles(opens, highs, lows, closes, vols)


def _params():
    return default_params(capital_limit_usdt=Decimal("1000"), slot_count=1)


def test_backtest_round_trip_is_a_winning_trade():
    report = run_backtest(
        "BTCUSDT", _round_trip_candles(), _params(),
        quote_per_order=Decimal("100"), starting_balance=Decimal("1000"),
    )
    assert report.num_trades == 1
    assert report.wins == 1
    assert report.losses == 0
    assert report.win_rate == 1.0
    assert report.open_positions == 0
    trade = report.trades[0]
    assert trade.net_pnl > 0
    # Ledger identity: final == starting + realized net PnL (exact).
    assert report.final_balance == report.starting_balance + report.total_net_pnl


def test_backtest_entry_price_reflects_signal_bar_close():
    # spread 0 -> entry fills at the signal candle's close (99.93).
    report = run_backtest(
        "BTCUSDT", _round_trip_candles(), _params(),
        quote_per_order=Decimal("100"), spread_frac=Decimal("0"),
    )
    assert report.trades[0].entry_price == Decimal("99.93")


def test_backtest_is_deterministic():
    a = run_backtest("BTCUSDT", _round_trip_candles(), _params(), quote_per_order=Decimal("100"))
    b = run_backtest("BTCUSDT", _round_trip_candles(), _params(), quote_per_order=Decimal("100"))
    assert a.num_trades == b.num_trades
    assert a.total_net_pnl == b.total_net_pnl
    assert a.final_balance == b.final_balance


def test_backtest_flat_series_has_no_trades():
    report = run_backtest("BTCUSDT", make_candles([100.0] * 40), _params(), quote_per_order=Decimal("100"))
    assert report.num_trades == 0
    assert report.final_balance == report.starting_balance


def test_fees_reduce_net_pnl():
    candles = _round_trip_candles()
    free = run_backtest("BTCUSDT", candles, _params(), quote_per_order=Decimal("100"), fee_rate=Decimal("0"))
    charged = run_backtest("BTCUSDT", candles, _params(), quote_per_order=Decimal("100"), fee_rate=Decimal("0.002"))
    assert charged.total_net_pnl < free.total_net_pnl


def test_withdrawal_mode_exits_without_arming():
    # Switch to withdrawal right after the entry; it should still close on profit.
    report = run_backtest(
        "BTCUSDT", _round_trip_candles(), _params(),
        quote_per_order=Decimal("100"), withdrawal_at_index=8,
    )
    assert report.num_trades == 1
    assert report.open_positions == 0


def test_capital_limit_blocks_when_exhausted():
    # Starting balance below the order size -> no entry can be funded.
    report = run_backtest(
        "BTCUSDT", _round_trip_candles(), _params(),
        quote_per_order=Decimal("100"), starting_balance=Decimal("10"),
    )
    assert report.num_trades == 0


# -- ReplayMarketData / BacktestClock ---------------------------------------

def test_replay_reveals_only_history_up_to_index():
    candles = make_candles([1, 2, 3, 4, 5])
    replay = ReplayMarketData({"BTCUSDT": candles})
    assert replay.get_closed_candles("BTCUSDT", 10) == []  # index unset
    replay.set_index("BTCUSDT", 2)
    revealed = replay.get_closed_candles("BTCUSDT", 10)
    assert [c.open for c in revealed] == [1, 2, 3]


def test_replay_synthesizes_book_with_spread():
    candles = make_candles([10], closes=[10])
    replay = ReplayMarketData({"BTCUSDT": candles}, spread_frac=Decimal("0.01"))
    replay.set_index("BTCUSDT", 0)
    book = replay.get_order_book("BTCUSDT")
    assert book.bids[0][0] == Decimal("10") * Decimal("0.99")
    assert book.asks[0][0] == Decimal("10") * Decimal("1.01")


def test_backtest_clock_tracks_candle_close():
    from cryptobot.market.candle import INTERVAL_MS
    candles = make_candles([1, 2, 3])
    clock = BacktestClock()
    clock.advance_to(candles[1])
    assert clock.now_ms() == candles[1].open_time + INTERVAL_MS
