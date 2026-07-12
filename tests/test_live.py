"""Tests for live-execution wiring (offline, via a fake transport)."""

from __future__ import annotations

import time
from decimal import Decimal
from typing import List
from urllib.parse import urlsplit

from cryptobot.exchange.binance_rest import BinanceRestClient
from cryptobot.execution.pnl import ExitCostModel
from cryptobot.runtime.live import (
    BinanceAccount,
    build_live_service,
    fetch_total_quote,
    reconcile_positions,
    run_live,
)
from cryptobot.runtime.service import OperationalStatus, ServiceConfig, TickReport
from cryptobot.strategy.position import RealizedEntry, open_position

from ._helpers import default_params
from .test_entry import (
    FIXTURE_CLOSES,
    FIXTURE_HIGHS,
    FIXTURE_LOWS,
    FIXTURE_OPENS,
    FIXTURE_VOLS,
)


class FakeLiveTransport:
    """Routes REST calls and returns canned account/klines/depth/order JSON."""

    def __init__(self, klines=None, depth=None, balances=None, buy_fills=None):
        self._klines = klines or []
        self._depth = depth or {"bids": [["100", "1000"]], "asks": [["100", "1000"]]}
        self._balances = balances or [{"asset": "USDT", "free": "1000", "locked": "0"}]
        self._buy_fills = buy_fills or [{"price": "100", "qty": "1", "commission": "0", "commissionAsset": "USDT"}]
        self.calls: List[tuple] = []

    def set_balances(self, balances):
        self._balances = balances

    def __call__(self, method, url, headers):
        self.calls.append((method, url))
        path = urlsplit(url).path
        if path == "/api/v3/account":
            return {"balances": self._balances}
        if path == "/api/v3/klines":
            return self._klines
        if path == "/api/v3/depth":
            return self._depth
        if path == "/api/v3/order":
            return {"fills": self._buy_fills}
        raise AssertionError(f"unexpected path {path}")


def _client(transport):
    return BinanceRestClient(transport, api_key="K", api_secret="S", timestamp_ms=lambda: 1)


def _position(symbol="BTCUSDT", sellable="1"):
    entry = RealizedEntry(
        filled_base_qty=Decimal(sellable), avg_entry_price=Decimal("100"),
        true_entry_cost=Decimal("100"), entry_fees_quote=Decimal("0"),
        sellable_base_qty=Decimal(sellable),
    )
    return open_position(symbol, default_params(), entry, 0)


# -- BinanceAccount ----------------------------------------------------------

def test_account_reads_free_quote_balance():
    transport = FakeLiveTransport(balances=[{"asset": "USDT", "free": "532.5", "locked": "0"}])
    account = BinanceAccount(_client(transport))
    assert account.available_quote_balance() == Decimal("532.5")


def test_fetch_total_quote_sums_free_and_locked():
    # capital_pct resolves against total = free + locked USDT.
    transport = FakeLiveTransport(balances=[
        {"asset": "USDT", "free": "100", "locked": "25"},
        {"asset": "BTC", "free": "1", "locked": "0"},
    ])
    assert fetch_total_quote(_client(transport)) == Decimal("125")


def test_account_tracks_used_and_slots_from_reports():
    account = BinanceAccount(_client(FakeLiveTransport()))
    entry_report = TickReport()
    entry_report.entries.append(_position())
    account.apply_report(entry_report)
    assert account.open_and_reserved_slots("BTCUSDT") == 1
    assert account.used_capital("BTCUSDT") == Decimal("100")

    from cryptobot.exchange.fills import RealizedPnL
    exit_report = TickReport()
    exit_report.exits.append((_position(), RealizedPnL(
        gross_proceeds=Decimal("110"), exit_fees_quote=Decimal("0"),
        exit_qty=Decimal("1"), invested_quote_cost=Decimal("100"), net_pnl=Decimal("10"),
    )))
    account.apply_report(exit_report)
    assert account.open_and_reserved_slots("BTCUSDT") == 0
    assert account.used_capital("BTCUSDT") == Decimal("0")


# -- reconciliation ----------------------------------------------------------

def test_reconcile_clean_when_exchange_holds_base():
    transport = FakeLiveTransport(balances=[
        {"asset": "USDT", "free": "1000", "locked": "0"},
        {"asset": "BTC", "free": "1.0", "locked": "0"},
    ])
    result = reconcile_positions(_client(transport), {"BTCUSDT": [_position(sellable="1")]})
    assert result.clean is True
    assert result.problems == []


def test_reconcile_dirty_when_base_is_short():
    transport = FakeLiveTransport(balances=[
        {"asset": "USDT", "free": "1000", "locked": "0"},
        {"asset": "BTC", "free": "0.5", "locked": "0"},
    ])
    result = reconcile_positions(_client(transport), {"BTCUSDT": [_position(sellable="1")]})
    assert result.clean is False
    assert result.problems


def test_reconcile_tolerance_allows_small_shortfall():
    transport = FakeLiveTransport(balances=[{"asset": "BTC", "free": "0.99", "locked": "0"}])
    client = _client(transport)
    assert reconcile_positions(client, {"BTCUSDT": [_position(sellable="1")]}, tolerance=Decimal("0.02")).clean is True
    transport.set_balances([{"asset": "BTC", "free": "0.97", "locked": "0"}])
    assert reconcile_positions(client, {"BTCUSDT": [_position(sellable="1")]}, tolerance=Decimal("0.02")).clean is False


def test_reconcile_empty_positions_is_clean():
    result = reconcile_positions(_client(FakeLiveTransport()), {"BTCUSDT": []})
    assert result.clean is True


# -- run_live ----------------------------------------------------------------

def _klines_near_now():
    now = int(time.time() * 1000)
    count = len(FIXTURE_OPENS)
    base = now - count * 60_000
    rows = []
    for i in range(count):
        t = base + i * 60_000
        rows.append([t, str(FIXTURE_OPENS[i]), str(FIXTURE_HIGHS[i]), str(FIXTURE_LOWS[i]),
                     str(FIXTURE_CLOSES[i]), str(FIXTURE_VOLS[i]), t + 59_999, "0", 0, "0", "0", "0"])
    return rows


def _config():
    params = default_params(capital_limit_usdt=Decimal("100"), slot_count=1)
    return ServiceConfig(coins={"BTCUSDT": params}, cost_model=ExitCostModel())


def test_run_live_places_a_buy_on_signal():
    transport = FakeLiveTransport(klines=_klines_near_now())
    client = _client(transport)
    service, account = build_live_service(client, _config())
    run_live(service, account, client, ["BTCUSDT"], ticks=1, sleep_fn=lambda _s: None)

    assert len(service.open_positions("BTCUSDT")) == 1
    assert any("/api/v3/order" in url for _m, url in transport.calls)


def test_run_live_dirty_reconciliation_closes_the_gate(monkeypatch):
    # A tracked position plus a short exchange balance -> reconciliation dirty.
    transport = FakeLiveTransport(
        klines=_klines_near_now(),
        balances=[{"asset": "USDT", "free": "1000"}, {"asset": "BTC", "free": "0.0"}],
    )
    client = _client(transport)
    service, account = build_live_service(client, _config())

    monkeypatch.setattr(service, "open_positions", lambda symbol: [_position(sellable="1")])
    captured = {}

    def fake_tick(status):
        captured["status"] = status
        return TickReport()

    monkeypatch.setattr(service, "tick", fake_tick)
    run_live(service, account, client, ["BTCUSDT"], ticks=1, sleep_fn=lambda _s: None)

    assert captured["status"].reconciliation_clean is False


def test_run_live_uses_base_status_flags(monkeypatch):
    transport = FakeLiveTransport(klines=_klines_near_now())
    client = _client(transport)
    service, account = build_live_service(client, _config())

    captured = {}

    def fake_tick(status):
        captured["status"] = status
        return TickReport()

    monkeypatch.setattr(service, "tick", fake_tick)
    run_live(
        service, account, client, ["BTCUSDT"], ticks=1, sleep_fn=lambda _s: None,
        base_status=OperationalStatus(trading_enabled=False),
    )
    # Operator flag preserved; reconciliation merged in.
    assert captured["status"].trading_enabled is False
    assert captured["status"].reconciliation_clean is True
