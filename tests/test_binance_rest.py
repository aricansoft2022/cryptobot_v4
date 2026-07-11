"""Tests for the Binance REST client, port adapters, and an end-to-end path."""

from __future__ import annotations

import hashlib
import hmac
from decimal import Decimal
from urllib.parse import parse_qs, urlencode, urlsplit

from cryptobot.exchange.binance_rest import (
    BinanceExecution,
    BinanceMarketData,
    BinanceRestClient,
)
from cryptobot.execution.gates import OperationalGates
from cryptobot.runtime.orchestrator import TradingRuntime

from ._helpers import default_params
from .test_entry import (
    FIXTURE_CLOSES,
    FIXTURE_HIGHS,
    FIXTURE_LOWS,
    FIXTURE_OPENS,
    FIXTURE_VOLS,
)


class FixedClock:
    def __init__(self, now_ms: int) -> None:
        self._now = now_ms

    def now_ms(self) -> int:
        return self._now


def _fixture_klines():
    rows = []
    for i in range(len(FIXTURE_OPENS)):
        open_time = i * 60_000
        rows.append([
            open_time,
            str(FIXTURE_OPENS[i]), str(FIXTURE_HIGHS[i]), str(FIXTURE_LOWS[i]),
            str(FIXTURE_CLOSES[i]), str(FIXTURE_VOLS[i]),
            open_time + 59_999, "0", 0, "0", "0", "0",
        ])
    return rows


class FakeBinanceTransport:
    """Routes requests by path and returns canned Binance JSON."""

    def __init__(self, klines=None, depth=None, buy_fills=None, sell_fills=None):
        self._klines = klines or []
        self._depth = depth or {"bids": [], "asks": []}
        self._buy_fills = buy_fills or []
        self._sell_fills = sell_fills or []
        self.calls = []

    def __call__(self, method, url, headers):
        self.calls.append((method, url, dict(headers)))
        parts = urlsplit(url)
        path = parts.path
        if path == "/api/v3/klines":
            return self._klines
        if path == "/api/v3/depth":
            return self._depth
        if path == "/api/v3/order":
            side = parse_qs(parts.query).get("side", [""])[0]
            return {"fills": self._buy_fills if side == "BUY" else self._sell_fills}
        if path == "/api/v3/account":
            return {"balances": []}
        raise AssertionError(f"unexpected path {path}")


def _open_gates() -> OperationalGates:
    return OperationalGates(
        runtime_running=True, trading_enabled=True, coin_active=True,
        coin_not_pending_delete=True, market_data_fresh=True, candles_contiguous=True,
        indicators_ready=True, not_already_processed=True, slot_available=True,
        capital_available=True, usdt_balance_sufficient=True, symbol_filters_ok=True,
        worker_holds_lease=True, reconciliation_clean=True, system_safe=True,
    )


# -- signing / request construction -----------------------------------------

def test_signed_request_has_deterministic_signature():
    transport = FakeBinanceTransport()
    client = BinanceRestClient(
        transport, api_key="KEY", api_secret="SECRET",
        timestamp_ms=lambda: 1_600_000_000_000, recv_window=5000,
    )
    client.account()
    _, url, headers = transport.calls[-1]
    query = urlsplit(url).query
    # Signature is HMAC-SHA256 over the query string up to '&signature='.
    unsigned = query.split("&signature=")[0]
    expected = hmac.new(b"SECRET", unsigned.encode(), hashlib.sha256).hexdigest()
    assert f"signature={expected}" in query
    assert headers["X-MBX-APIKEY"] == "KEY"


def test_public_request_is_unsigned_and_keyless():
    transport = FakeBinanceTransport(klines=_fixture_klines())
    client = BinanceRestClient(transport)  # no key/secret
    client.get_klines("BTCUSDT", "1m", 10)
    method, url, headers = transport.calls[-1]
    assert method == "GET"
    assert "signature=" not in url
    assert headers == {}
    q = parse_qs(urlsplit(url).query)
    assert q["symbol"] == ["BTCUSDT"] and q["interval"] == ["1m"]


def test_market_buy_sends_quote_order_qty_and_signs():
    transport = FakeBinanceTransport(buy_fills=[{"price": "100", "qty": "1"}])
    client = BinanceRestClient(transport, api_key="K", api_secret="S", timestamp_ms=lambda: 1)
    execution = BinanceExecution(client)
    fills = execution.market_buy("BTCUSDT", Decimal("100"))
    method, url, _ = transport.calls[-1]
    q = parse_qs(urlsplit(url).query)
    assert method == "POST"
    assert q["side"] == ["BUY"] and q["type"] == ["MARKET"]
    assert q["quoteOrderQty"] == ["100"]
    assert "signature" in q
    assert fills[0].price == Decimal("100") and fills[0].qty == Decimal("1")


# -- port adapters -----------------------------------------------------------

def test_market_data_maps_klines_and_drops_open():
    klines = _fixture_klines()
    # Append an in-progress candle whose close is in the future.
    open_time = len(klines) * 60_000
    klines.append([open_time, "1", "2", "0", "1", "5", open_time + 59_999, "0", 0, "0", "0", "0"])
    transport = FakeBinanceTransport(klines=klines)
    client = BinanceRestClient(transport)
    # now is just past the fixture's last close but before the appended candle closes.
    md = BinanceMarketData(client, FixedClock(now_ms=len(klines) * 60_000 - 60_000 + 1))
    candles = md.get_closed_candles("BTCUSDT", 100)
    # The final, still-open candle is dropped.
    assert all(c.is_closed for c in candles)
    assert candles[-1].open_time == (len(klines) - 2) * 60_000


def test_market_data_builds_orderbook():
    transport = FakeBinanceTransport(depth={"bids": [["100", "1"], ["101", "2"]], "asks": []})
    md = BinanceMarketData(BinanceRestClient(transport), FixedClock(0))
    book = md.get_order_book("BTCUSDT")
    assert book.bids[0] == (Decimal("101"), Decimal("2"))


# -- end-to-end: live transport -> runtime -> position -----------------------

def test_end_to_end_entry_through_rest_transport():
    transport = FakeBinanceTransport(
        klines=_fixture_klines(),
        buy_fills=[{"price": "100", "qty": "1", "commission": "0", "commissionAsset": "USDT"}],
    )
    client = BinanceRestClient(transport, api_key="K", api_secret="S", timestamp_ms=lambda: 1)
    # now_ms after the fixture's last close so every candle is closed.
    clock = FixedClock(now_ms=len(FIXTURE_OPENS) * 60_000)
    market_data = BinanceMarketData(client, clock)
    execution = BinanceExecution(client)

    runtime = TradingRuntime(market_data, execution)
    position = runtime.try_enter(
        "BTCUSDT", default_params(), _open_gates(), quote_amount=Decimal("100")
    )
    assert position is not None
    assert position.entry.true_entry_cost == Decimal("100")
    assert position.entry.sellable_base_qty == Decimal("1")
    # A BUY order was actually placed via the transport.
    assert any("/api/v3/order" in call[1] for call in transport.calls)
