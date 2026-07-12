"""Tests for the CLI config parsing and the paper-run wiring (no network)."""

from __future__ import annotations

import json
import time
from decimal import Decimal

import pytest

from cryptobot.cli import (
    build_paper_service,
    coin_params_from_dict,
    load_klines_file,
    main,
    run_paper,
    service_config_from_dict,
)
from cryptobot.exchange.binance_rest import BinanceRestClient
from cryptobot.execution.pnl import ExitCostModel
from cryptobot.runtime.service import ServiceConfig

from ._helpers import default_params
from .test_binance_rest import FakeBinanceTransport
from .test_entry import (
    FIXTURE_CLOSES,
    FIXTURE_HIGHS,
    FIXTURE_LOWS,
    FIXTURE_OPENS,
    FIXTURE_VOLS,
)

_CONFIG = {
    "coins": {
        "BTCUSDT": {
            "rsi_oversold": 30, "rsi_overbought": 70,
            "adx_low": 20, "adx_high": 50, "min_net_profit_pct": "0.5",
            "rsi_period": 14, "rsi_ma_period": 14, "adx_period": 14, "adr_period": 14,
            "capital_limit_usdt": "1000", "slot_count": 3,
        }
    },
    "cost_model": {"exit_fee_rate": "0.001", "safety_buffer_frac": "0.0005"},
    "candle_buffer": 7,
}


def test_coin_params_from_dict():
    params = coin_params_from_dict(_CONFIG["coins"]["BTCUSDT"])
    assert params.rsi_oversold == 30.0
    assert params.min_net_profit_pct == Decimal("0.5")
    assert params.rsi_period == 14
    assert params.capital_limit_usdt == Decimal("1000")
    assert params.slot_count == 3


def test_service_config_from_dict():
    config = service_config_from_dict(_CONFIG)
    assert set(config.coins) == {"BTCUSDT"}
    assert config.cost_model.exit_fee_rate == Decimal("0.001")
    assert config.candle_buffer == 7


# -- percentage-based capital allocation ------------------------------------

_PCT_COIN = {k: v for k, v in _CONFIG["coins"]["BTCUSDT"].items() if k != "capital_limit_usdt"}
_PCT_COIN["capital_pct"] = 25  # 25% of the total balance


def test_capital_pct_resolves_against_total_balance():
    coin = {**_PCT_COIN, "slot_count": 5}
    params = coin_params_from_dict(coin, total_quote=Decimal("1000"))
    assert params.capital_limit_usdt == Decimal("250.00000000")  # 25% of 1000
    # Per-order size is that limit / slot_count.
    assert params.capital_limit_usdt / params.slot_count == Decimal("50.00000000")


def test_capital_pct_requires_total_balance():
    with pytest.raises(ValueError):
        coin_params_from_dict(_PCT_COIN)  # no total_quote


def test_capital_rejects_both_pct_and_absolute():
    with pytest.raises(ValueError):
        coin_params_from_dict({**_PCT_COIN, "capital_limit_usdt": "800"}, total_quote=Decimal("1000"))


def test_capital_requires_one_of_pct_or_absolute():
    neither = {k: v for k, v in _PCT_COIN.items() if k != "capital_pct"}
    with pytest.raises(ValueError):
        coin_params_from_dict(neither, total_quote=Decimal("1000"))


def test_capital_pct_must_be_in_range():
    for bad in (0, -5, 150):
        with pytest.raises(ValueError):
            coin_params_from_dict({**_PCT_COIN, "capital_pct": bad}, total_quote=Decimal("1000"))


def test_service_config_mixes_absolute_and_percentage():
    data = {
        "coins": {
            "BTCUSDT": {**_CONFIG["coins"]["BTCUSDT"]},   # absolute 1000
            "ETHUSDT": {**_PCT_COIN},                     # 25% of 2000 -> 500
        },
        "cost_model": {},
        "candle_buffer": 5,
    }
    config = service_config_from_dict(data, total_quote=Decimal("2000"))
    assert config.coins["BTCUSDT"].capital_limit_usdt == Decimal("1000")
    assert config.coins["ETHUSDT"].capital_limit_usdt == Decimal("500.00000000")


def _klines_near_now():
    """Fixture OHLCV placed so the last candle just closed relative to now."""
    now = int(time.time() * 1000)
    count = len(FIXTURE_OPENS)
    base = now - count * 60_000
    rows = []
    for i in range(count):
        open_time = base + i * 60_000
        rows.append([
            open_time,
            str(FIXTURE_OPENS[i]), str(FIXTURE_HIGHS[i]), str(FIXTURE_LOWS[i]),
            str(FIXTURE_CLOSES[i]), str(FIXTURE_VOLS[i]),
            open_time + 59_999, "0", 0, "0", "0", "0",
        ])
    return rows


def test_paper_run_opens_position_and_updates_ledger():
    transport = FakeBinanceTransport(
        klines=_klines_near_now(),
        depth={"bids": [["99", "1000"]], "asks": [["100", "1000"]]},
    )
    client = BinanceRestClient(transport)  # public data only, no keys
    # Clean sizing: 100 USDT per order.
    params = default_params(capital_limit_usdt=Decimal("100"), slot_count=1)
    config = ServiceConfig(coins={"BTCUSDT": params}, cost_model=ExitCostModel())

    service, account = build_paper_service(client, config, quote_balance=Decimal("1000"))
    run_paper(service, account, ticks=1, sleep_fn=lambda _s: None)

    assert len(service.open_positions("BTCUSDT")) == 1
    # Paper buy at ask 100 for 100 USDT -> 1 unit, ledger drops to 900.
    assert account.available_quote_balance() == Decimal("900")


def test_paper_run_respects_tick_count_and_sleeps_between():
    transport = FakeBinanceTransport(klines=_klines_near_now(), depth={"bids": [], "asks": []})
    client = BinanceRestClient(transport)
    config = ServiceConfig(
        coins={"BTCUSDT": default_params(capital_limit_usdt=Decimal("100"), slot_count=1)},
        cost_model=ExitCostModel(),
    )
    service, account = build_paper_service(client, config, quote_balance=Decimal("1000"))

    slept = []
    run_paper(service, account, ticks=3, sleep_fn=slept.append, interval_s=0.25)
    assert slept == [0.25, 0.25]  # between ticks only


# -- backtest CLI mode (offline: klines from a file) ------------------------

_SMALL_PERIOD_COIN = {
    "rsi_oversold": 45, "rsi_overbought": 70, "adx_low": 10, "adx_high": 90,
    "min_net_profit_pct": "0.5", "rsi_period": 2, "rsi_ma_period": 2,
    "adx_period": 2, "adr_period": 2, "capital_limit_usdt": "1000", "slot_count": 1,
}


def _round_trip_klines():
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
    rows = []
    for i in range(len(opens)):
        t = i * 60_000
        rows.append([t, str(opens[i]), str(highs[i]), str(lows[i]), str(closes[i]),
                     str(vols[i]), t + 59_999, "0", 0, "0", "0", "0"])
    return rows


def test_load_klines_file(tmp_path):
    path = tmp_path / "klines.json"
    path.write_text(json.dumps({"BTCUSDT": _round_trip_klines()}))
    loaded = load_klines_file(str(path))
    assert "BTCUSDT" in loaded
    assert len(loaded["BTCUSDT"]) == 16
    assert loaded["BTCUSDT"][0].is_closed


def test_main_backtest_mode(tmp_path, capsys):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "coins": {"BTCUSDT": _SMALL_PERIOD_COIN},
        "cost_model": {"exit_fee_rate": "0", "safety_buffer_frac": "0"},
        "candle_buffer": 5,
    }))
    klines_path = tmp_path / "klines.json"
    klines_path.write_text(json.dumps({"BTCUSDT": _round_trip_klines()}))

    rc = main([
        "--config", str(config_path),
        "--backtest", str(klines_path),
        "--quote-per-order", "100",
        "--quote-balance", "1000",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "[backtest] BTCUSDT:" in out
    assert "trades=1" in out
