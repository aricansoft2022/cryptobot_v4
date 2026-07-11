"""Binance REST client and port adapters, with an injected HTTP transport.

This holds the real Binance endpoint paths and the HMAC-SHA256 request signing,
but delegates the actual network call to an injected ``transport`` callable. That
keeps credentials and I/O out of the codebase: production injects a real HTTP
client, tests inject a fake. No strategy logic lives here.

The transport contract is::

    transport(method: str, url: str, headers: Mapping[str, str]) -> Any

where the returned value is the parsed JSON body. All query parameters
(including any signature) are already baked into ``url`` by the client, so the
transport only performs the HTTP call.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from decimal import Decimal
from typing import Any, Callable, List, Mapping, Optional
from urllib.parse import urlencode

from ..execution.orderbook import OrderBook
from ..market.candle import Candle
from .fills import Fill
from .market_data import parse_depth, parse_klines

Transport = Callable[[str, str, Mapping[str, str]], Any]

_PUBLIC = "https://api.binance.com"


class BinanceRestClient:
    """Builds and signs Binance REST requests; performs them via ``transport``."""

    def __init__(
        self,
        transport: Transport,
        api_key: str = "",
        api_secret: str = "",
        base_url: str = _PUBLIC,
        recv_window: int = 5000,
        timestamp_ms: Optional[Callable[[], int]] = None,
    ) -> None:
        self._transport = transport
        self._api_key = api_key
        self._api_secret = api_secret
        self._base_url = base_url.rstrip("/")
        self._recv_window = recv_window
        self._now_ms = timestamp_ms or (lambda: int(time.time() * 1000))

    # -- request plumbing ---------------------------------------------------

    def _sign(self, query: str) -> str:
        return hmac.new(
            self._api_secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()

    def _build_url(self, path: str, params: Optional[Mapping[str, Any]], signed: bool) -> str:
        items = dict(params or {})
        if signed:
            items["timestamp"] = self._now_ms()
            items["recvWindow"] = self._recv_window
            query = urlencode(items)
            query = f"{query}&signature={self._sign(query)}"
        else:
            query = urlencode(items)
        url = self._base_url + path
        return f"{url}?{query}" if query else url

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Mapping[str, Any]] = None,
        signed: bool = False,
    ) -> Any:
        url = self._build_url(path, params, signed)
        headers = {"X-MBX-APIKEY": self._api_key} if self._api_key else {}
        return self._transport(method, url, headers)

    # -- public endpoints ---------------------------------------------------

    def get_klines(self, symbol: str, interval: str = "1m", limit: int = 200) -> Any:
        return self._request(
            "GET", "/api/v3/klines",
            {"symbol": symbol, "interval": interval, "limit": limit},
        )

    def get_order_book(self, symbol: str, limit: int = 100) -> Any:
        return self._request("GET", "/api/v3/depth", {"symbol": symbol, "limit": limit})

    def get_exchange_info(self, symbol: str) -> Any:
        return self._request("GET", "/api/v3/exchangeInfo", {"symbol": symbol})

    # -- signed endpoints ---------------------------------------------------

    def account(self) -> Any:
        return self._request("GET", "/api/v3/account", signed=True)

    def market_buy_quote(self, symbol: str, quote_amount: Any) -> Any:
        return self._request(
            "POST", "/api/v3/order",
            {
                "symbol": symbol,
                "side": "BUY",
                "type": "MARKET",
                "quoteOrderQty": str(quote_amount),
                "newOrderRespType": "FULL",
            },
            signed=True,
        )

    def market_sell_qty(self, symbol: str, base_qty: Any) -> Any:
        return self._request(
            "POST", "/api/v3/order",
            {
                "symbol": symbol,
                "side": "SELL",
                "type": "MARKET",
                "quantity": str(base_qty),
                "newOrderRespType": "FULL",
            },
            signed=True,
        )


class BinanceMarketData:
    """``MarketDataPort`` backed by :class:`BinanceRestClient` (polling)."""

    def __init__(self, client: BinanceRestClient, clock, interval: str = "1m") -> None:
        self._client = client
        self._clock = clock
        self._interval = interval

    def get_closed_candles(self, symbol: str, limit: int) -> List[Candle]:
        # Fetch one extra to tolerate dropping the still-open candle.
        raw = self._client.get_klines(symbol, self._interval, limit + 1)
        candles = parse_klines(raw, symbol, now_ms=self._clock.now_ms())
        return candles[-limit:] if limit else candles

    def get_order_book(self, symbol: str) -> OrderBook:
        return parse_depth(self._client.get_order_book(symbol), symbol)


class BinanceExecution:
    """``ExecutionPort`` backed by :class:`BinanceRestClient`."""

    def __init__(self, client: BinanceRestClient) -> None:
        self._client = client

    def market_buy(self, symbol: str, quote_amount: Decimal) -> List[Fill]:
        resp = self._client.market_buy_quote(symbol, quote_amount)
        return [Fill.from_binance(f) for f in resp.get("fills", [])]

    def market_sell(self, symbol: str, base_qty: Decimal) -> List[Fill]:
        resp = self._client.market_sell_qty(symbol, base_qty)
        return [Fill.from_binance(f) for f in resp.get("fills", [])]
