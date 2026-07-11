"""Tests for the Binance WebSocket streaming market data component."""

from __future__ import annotations

from decimal import Decimal
from typing import List

from cryptobot.exchange.binance_ws import StreamingMarketData
from cryptobot.exchange.fills import Fill
from cryptobot.execution.gates import OperationalGates
from cryptobot.runtime.orchestrator import TradingRuntime

from ._helpers import default_params
from .test_entry import _fixture_candles


def _kline_msg(symbol, t, o, h, l, c, v, closed):
    return {
        "stream": f"{symbol.lower()}@kline_1m",
        "data": {"e": "kline", "s": symbol, "k": {
            "t": t, "o": str(o), "h": str(h), "l": str(l), "c": str(c), "v": str(v), "x": closed,
        }},
    }


def test_open_kline_ignored_closed_kline_stored():
    smd = StreamingMarketData()
    smd.process_message(_kline_msg("BTCUSDT", 60_000, 10, 12, 9, 11, 100, closed=False))
    assert smd.get_closed_candles("BTCUSDT", 10) == []
    smd.process_message(_kline_msg("BTCUSDT", 60_000, 10, 12, 9, 11, 100, closed=True))
    assert len(smd.get_closed_candles("BTCUSDT", 10)) == 1


def test_same_open_time_is_replaced_not_duplicated():
    smd = StreamingMarketData()
    smd.process_message(_kline_msg("BTCUSDT", 60_000, 10, 12, 9, 11, 100, closed=True))
    smd.process_message(_kline_msg("BTCUSDT", 60_000, 10, 13, 8, 12, 150, closed=True))
    candles = smd.get_closed_candles("BTCUSDT", 10)
    assert len(candles) == 1
    assert candles[-1].high == 13.0  # replaced with the newer payload


def test_stale_out_of_order_kline_ignored():
    smd = StreamingMarketData()
    smd.process_message(_kline_msg("BTCUSDT", 120_000, 10, 12, 9, 11, 100, closed=True))
    smd.process_message(_kline_msg("BTCUSDT", 60_000, 1, 2, 0, 1, 5, closed=True))  # older
    candles = smd.get_closed_candles("BTCUSDT", 10)
    assert [c.open_time for c in candles] == [120_000]


def test_depth_from_combined_stream_updates_book():
    smd = StreamingMarketData()
    smd.process_message({
        "stream": "btcusdt@depth20@100ms",
        "data": {"lastUpdateId": 1, "bids": [["100", "1"], ["101", "2"]], "asks": [["103", "1"]]},
    })
    book = smd.get_order_book("BTCUSDT")
    assert book.bids[0] == (Decimal("101"), Decimal("2"))
    assert smd.has_order_book("BTCUSDT")


def test_raw_message_without_envelope():
    smd = StreamingMarketData()
    smd.apply_kline("BTCUSDT", {"t": 60_000, "o": "10", "h": "12", "l": "9", "c": "11", "v": "100", "x": True})
    assert len(smd.get_closed_candles("BTCUSDT", 10)) == 1


def test_seed_candles_only_keeps_closed_and_limits():
    smd = StreamingMarketData(max_candles=3)
    smd.seed_candles("BTCUSDT", _fixture_candles())  # 8 closed candles
    kept = smd.get_closed_candles("BTCUSDT", 10)
    assert len(kept) == 3  # buffer capped at max_candles
    assert kept[-1].open_time == _fixture_candles()[-1].open_time


def test_get_order_book_empty_when_absent():
    smd = StreamingMarketData()
    assert smd.get_order_book("ETHUSDT").bids == ()


def test_get_closed_candles_respects_limit():
    smd = StreamingMarketData()
    smd.seed_candles("BTCUSDT", _fixture_candles())
    assert len(smd.get_closed_candles("BTCUSDT", 3)) == 3


# -- end-to-end: streaming buffer drives a runtime entry ---------------------

class _FakeExecution:
    def __init__(self):
        self.buys: List[tuple] = []

    def market_buy(self, symbol, quote_amount):
        self.buys.append((symbol, quote_amount))
        return [Fill(Decimal("100"), quote_amount / Decimal("100"), Decimal("0"), "USDT")]

    def market_sell(self, symbol, base_qty):
        return [Fill(Decimal("110"), base_qty, Decimal("0"), "USDT")]


def _open_gates() -> OperationalGates:
    return OperationalGates(
        runtime_running=True, trading_enabled=True, coin_active=True,
        coin_not_pending_delete=True, market_data_fresh=True, candles_contiguous=True,
        indicators_ready=True, not_already_processed=True, slot_available=True,
        capital_available=True, usdt_balance_sufficient=True, symbol_filters_ok=True,
        worker_holds_lease=True, reconciliation_clean=True, system_safe=True,
    )


def test_end_to_end_entry_from_streamed_candles():
    smd = StreamingMarketData()
    # Prime with all-but-last fixture candles, then "stream" the final closed one.
    fixture = _fixture_candles()
    smd.seed_candles("BTCUSDT", fixture[:-1])
    last = fixture[-1]
    smd.apply_kline("BTCUSDT", {
        "t": last.open_time, "o": str(last.open), "h": str(last.high),
        "l": str(last.low), "c": str(last.close), "v": str(last.volume), "x": True,
    })

    execution = _FakeExecution()
    runtime = TradingRuntime(smd, execution)
    position = runtime.try_enter("BTCUSDT", default_params(), _open_gates(), Decimal("100"))
    assert position is not None
    assert execution.buys == [("BTCUSDT", Decimal("100"))]
