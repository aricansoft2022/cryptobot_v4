"""Tests for mapping raw Binance market data into core types."""

from __future__ import annotations

from decimal import Decimal

from cryptobot.exchange.market_data import parse_depth, parse_klines
from cryptobot.market.validation import is_valid_series


def _kline(open_time, o, h, l, c, v):
    close_time = open_time + 59_999
    return [open_time, str(o), str(h), str(l), str(c), str(v), close_time, "0", 0, "0", "0", "0"]


def test_parse_klines_basic_fields():
    raw = [_kline(60_000, 10, 12, 9, 11, 100)]
    candles = parse_klines(raw, "BTCUSDT")
    assert len(candles) == 1
    c = candles[0]
    assert (c.symbol, c.open_time, c.open, c.high, c.low, c.close, c.volume) == (
        "BTCUSDT", 60_000, 10.0, 12.0, 9.0, 11.0, 100.0
    )
    assert c.is_closed is True


def test_parse_klines_drops_unclosed_last():
    raw = [_kline(60_000, 10, 12, 9, 11, 100), _kline(120_000, 11, 13, 10, 12, 200)]
    # now between the two close times: first closed (119999 < now), second open.
    candles = parse_klines(raw, "BTCUSDT", now_ms=150_000)
    assert [c.open_time for c in candles] == [60_000]


def test_parse_klines_keeps_unclosed_when_not_dropping():
    raw = [_kline(120_000, 11, 13, 10, 12, 200)]
    candles = parse_klines(raw, "BTCUSDT", now_ms=150_000, drop_unclosed=False)
    assert len(candles) == 1
    assert candles[0].is_closed is False


def test_parsed_contiguous_klines_validate():
    raw = [_kline(60_000 * i, 10 + i, 12 + i, 9 + i, 11 + i, 100) for i in range(1, 6)]
    candles = parse_klines(raw, "BTCUSDT")
    assert is_valid_series(candles)


def test_parse_depth_builds_sorted_orderbook():
    depth = {"bids": [["100", "1"], ["101", "2"]], "asks": [["103", "1"], ["102", "2"]]}
    book = parse_depth(depth, "BTCUSDT")
    # Bids best-first (highest price first).
    assert book.bids[0] == (Decimal("101"), Decimal("2"))
    est = book.estimate_sell_proceeds(Decimal("2"))
    assert est.gross_proceeds == Decimal("101") * Decimal("2")  # 2 @ best bid 101
