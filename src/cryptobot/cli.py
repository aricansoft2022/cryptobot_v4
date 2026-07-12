"""A runnable entrypoint that wires the transport, ports and engine together.

Runs the deterministic strategy against **real, read-only** Binance market data
while simulating fills in a paper ledger — so ``python -m cryptobot`` is safe by
default and needs no API credentials. Live order placement is intentionally not
exposed here; wire :class:`~cryptobot.exchange.binance_rest.BinanceExecution`
into a :class:`~cryptobot.runtime.service.TradingService` yourself to trade for
real.

Config is JSON, e.g.::

    {
      "coins": {
        "BTCUSDT": {
          "rsi_oversold": 30, "rsi_overbought": 70,
          "adx_low": 20, "adx_high": 50, "min_net_profit_pct": "0.5",
          "rsi_period": 14, "rsi_ma_period": 14, "adx_period": 14, "adr_period": 14,
          "capital_limit_usdt": "1000", "slot_count": 3
        }
      },
      "cost_model": {"exit_fee_rate": "0.001", "safety_buffer_frac": "0.0005"},
      "candle_buffer": 5
    }
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from decimal import Decimal
from typing import Any, Callable, Mapping, Optional, Tuple

from .exchange.binance_rest import BinanceMarketData, BinanceRestClient
from .exchange.http import urllib_transport
from .execution.pnl import ExitCostModel
from .runtime.live import build_live_service, fetch_total_quote, run_live
from .runtime.metrics import MetricsTracker, build_status
from .runtime.paper import LedgerAccount, PaperExecution
from .runtime.providers import SystemClock
from .runtime.service import OperationalStatus, ServiceConfig, TickReport, TradingService
from .runtime.status_server import StatusServer
from .strategy.parameters import CoinStrategyParameters


def _resolve_capital_limit(data: Mapping[str, Any], total_quote: Optional[Any]) -> Decimal:
    """Resolve a coin's absolute capital limit from ``capital_limit_usdt`` or
    ``capital_pct`` (a percentage of the total quote balance).

    ``capital_pct`` is resolved once, here at startup, against ``total_quote``
    (your total USDT balance), and then stays fixed for the session.
    """
    has_abs = "capital_limit_usdt" in data
    has_pct = "capital_pct" in data
    if has_abs and has_pct:
        raise ValueError("specify either capital_limit_usdt or capital_pct, not both")
    if has_abs:
        return Decimal(str(data["capital_limit_usdt"]))
    if has_pct:
        pct = Decimal(str(data["capital_pct"]))
        if not (Decimal("0") < pct <= Decimal("100")):
            raise ValueError(f"capital_pct must be within (0, 100], got {pct}")
        if total_quote is None:
            raise ValueError("capital_pct requires a known total quote balance")
        limit = Decimal(str(total_quote)) * pct / Decimal("100")
        return limit.quantize(Decimal("0.00000001"))
    raise ValueError("coin config needs either capital_limit_usdt or capital_pct")


def coin_params_from_dict(
    data: Mapping[str, Any], total_quote: Optional[Any] = None
) -> CoinStrategyParameters:
    """Build :class:`CoinStrategyParameters` from a JSON-decoded mapping.

    ``total_quote`` (the total USDT balance) is only required when a coin uses
    ``capital_pct`` instead of an absolute ``capital_limit_usdt``.
    """
    return CoinStrategyParameters(
        rsi_oversold=float(data["rsi_oversold"]),
        rsi_overbought=float(data["rsi_overbought"]),
        adx_low=float(data["adx_low"]),
        adx_high=float(data["adx_high"]),
        min_net_profit_pct=Decimal(str(data["min_net_profit_pct"])),
        rsi_period=int(data["rsi_period"]),
        rsi_ma_period=int(data["rsi_ma_period"]),
        adx_period=int(data["adx_period"]),
        adr_period=int(data["adr_period"]),
        capital_limit_usdt=_resolve_capital_limit(data, total_quote),
        slot_count=int(data["slot_count"]),
    )


def service_config_from_dict(
    data: Mapping[str, Any], total_quote: Optional[Any] = None
) -> ServiceConfig:
    """Build a :class:`ServiceConfig` from a JSON-decoded mapping.

    Pass ``total_quote`` (total USDT balance) when any coin uses ``capital_pct``.
    """
    coins = {sym: coin_params_from_dict(p, total_quote) for sym, p in data["coins"].items()}
    cm = data.get("cost_model", {})
    cost_model = ExitCostModel(
        exit_fee_rate=Decimal(str(cm.get("exit_fee_rate", "0"))),
        safety_buffer_frac=Decimal(str(cm.get("safety_buffer_frac", "0"))),
    )
    return ServiceConfig(
        coins=coins,
        cost_model=cost_model,
        candle_buffer=int(data.get("candle_buffer", 5)),
    )


def build_paper_service(
    client: BinanceRestClient,
    config: ServiceConfig,
    quote_balance: Any,
    interval: str = "1m",
) -> Tuple[TradingService, LedgerAccount]:
    """Wire a read-only, paper-trading :class:`TradingService`."""
    clock = SystemClock()
    market_data = BinanceMarketData(client, clock, interval)
    execution = PaperExecution(market_data)
    account = LedgerAccount(quote_balance)
    service = TradingService(market_data, execution, account, clock, config)
    return service, account


def run_paper(
    service: TradingService,
    account: LedgerAccount,
    ticks: Optional[int] = None,
    interval_s: float = 60.0,
    status_provider: Optional[Callable[[], OperationalStatus]] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    on_report: Optional[Callable[[int, TickReport, LedgerAccount], None]] = None,
) -> None:
    """Run the paper loop, folding each tick into ``account``.

    ``ticks=None`` runs until interrupted. ``sleep_fn`` is injected so tests run
    with no delay.
    """
    i = 0
    while ticks is None or i < ticks:
        status = status_provider() if status_provider else OperationalStatus()
        report = service.tick(status)
        account.apply_report(report)
        if on_report is not None:
            on_report(i, report, account)
        i += 1
        if ticks is None or i < ticks:
            sleep_fn(interval_s)


def _print_report(i: int, report: TickReport, account: LedgerAccount) -> None:
    if report.entries or report.exits:
        for pos in report.entries:
            print(f"[tick {i}] BUY  {pos.symbol} qty={pos.entry.filled_base_qty} "
                  f"cost={pos.entry.true_entry_cost}")
        for pos, pnl in report.exits:
            print(f"[tick {i}] SELL {pos.symbol} net_pnl={pnl.net_pnl}")
    print(f"[tick {i}] quote_balance={account.available_quote_balance()}")


def load_klines_file(path: str) -> Mapping[str, Any]:
    """Load ``{symbol: [binance kline array, ...]}`` and map to closed candles."""
    from .exchange.market_data import parse_klines

    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return {symbol: parse_klines(rows, symbol) for symbol, rows in data.items()}


def _run_backtest(args, config: ServiceConfig) -> int:
    from .backtest import run_backtest

    klines = load_klines_file(args.backtest)
    quote_per_order = Decimal(args.quote_per_order) if args.quote_per_order else None
    for symbol, params in config.coins.items():
        candles = klines.get(symbol)
        if not candles:
            print(f"[backtest] {symbol}: no klines in file, skipping")
            continue
        report = run_backtest(
            symbol, candles, params,
            quote_per_order=quote_per_order,
            starting_balance=Decimal(args.quote_balance),
            fee_rate=config.cost_model.exit_fee_rate,
            safety_buffer_frac=config.cost_model.safety_buffer_frac,
        )
        print(
            f"[backtest] {symbol}: trades={report.num_trades} "
            f"net_pnl={report.total_net_pnl} win_rate={report.win_rate:.0%} "
            f"final_balance={report.final_balance} open={report.open_positions}"
        )
    return 0


def _setup_monitoring(symbols, service, account, cost_model, status_port):
    """Wire a metrics tracker + optional status HTTP server.

    Returns ``(update, server)`` where ``update(report)`` folds a tick into the
    metrics and refreshes the served snapshot, and ``server`` is a started
    :class:`StatusServer` or ``None``.
    """
    metrics = MetricsTracker()
    holder = {"snapshot": {}}

    def update(report: TickReport) -> None:
        now = int(time.time() * 1000)
        metrics.record_report(report, now)
        holder["snapshot"] = build_status(
            symbols, service, account, service.market_data, cost_model, metrics, now
        ).as_dict()

    update(TickReport())  # prime the snapshot before serving
    server = None
    if status_port is not None:
        server = StatusServer(lambda: holder["snapshot"], port=int(status_port)).start()
        print(f"Status server on {server.url}")
    return update, server


def _live_report(i: int, report: TickReport, recon) -> None:
    if not recon.clean:
        print(f"[tick {i}] reconciliation DIRTY — trading halted: {recon.problems}")
    for pos in report.entries:
        print(f"[tick {i}] BUY  {pos.symbol} qty={pos.entry.filled_base_qty} cost={pos.entry.true_entry_cost}")
    for pos, pnl in report.exits:
        print(f"[tick {i}] SELL {pos.symbol} net_pnl={pnl.net_pnl}")


def _run_live(args, raw_config: Mapping[str, Any]) -> int:
    api_key = os.environ.get("BINANCE_API_KEY", "")
    api_secret = os.environ.get("BINANCE_API_SECRET", "")
    if not api_key or not api_secret:
        print("ERROR: --live requires BINANCE_API_KEY and BINANCE_API_SECRET environment variables.", file=sys.stderr)
        return 2
    if not args.testnet and not args.yes_trade_real_money:
        print("ERROR: refusing to trade real money. Use --testnet, or pass --yes-trade-real-money to confirm.", file=sys.stderr)
        return 2

    base_url = "https://testnet.binance.vision" if args.testnet else args.base_url
    client = BinanceRestClient(
        urllib_transport, api_key=api_key, api_secret=api_secret, base_url=base_url
    )
    # Resolve any percentage-based capital against the real total USDT balance now.
    total_quote = fetch_total_quote(client)
    config = service_config_from_dict(raw_config, total_quote=total_quote)
    print(f"Total USDT balance: {total_quote}")
    service, account = build_live_service(client, config)
    where = "TESTNET" if args.testnet else "REAL MONEY"
    print(f"*** LIVE trading on {where}: {list(config.coins)} ***")
    update, server = _setup_monitoring(
        list(config.coins), service, account, config.cost_model, args.status_port
    )

    def on_report(i, report, recon):
        update(report)
        _live_report(i, report, recon)

    try:
        run_live(
            service, account, client, list(config.coins),
            ticks=args.ticks or None, interval_s=args.interval,
            on_report=on_report,
        )
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        if server is not None:
            server.stop()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="cryptobot", description="Paper-run, backtest, or live-trade the strategy.")
    parser.add_argument("--config", required=True, help="Path to the JSON config file.")
    parser.add_argument("--quote-balance", default="1000", help="Starting paper/backtest quote balance.")
    parser.add_argument("--ticks", type=int, default=0, help="Number of ticks (0 = run until interrupted).")
    parser.add_argument("--interval", type=float, default=60.0, help="Seconds between ticks.")
    parser.add_argument("--base-url", default="https://api.binance.com", help="Binance REST base URL.")
    parser.add_argument("--backtest", default=None, help="Path to a JSON klines file to backtest instead of paper-running.")
    parser.add_argument("--quote-per-order", default=None, help="Fixed quote size per order (backtest only).")
    parser.add_argument("--live", action="store_true", help="Trade live via Binance (requires API keys + confirmation).")
    parser.add_argument("--testnet", action="store_true", help="Use the Binance testnet (safe, fake money).")
    parser.add_argument("--yes-trade-real-money", action="store_true", help="Required to trade REAL money in --live mode.")
    parser.add_argument("--status-port", type=int, default=None, help="Serve a JSON status snapshot on this port (paper/live).")
    args = parser.parse_args(argv)

    with open(args.config, "r", encoding="utf-8") as handle:
        raw_config = json.load(handle)

    if args.live:
        return _run_live(args, raw_config)

    # Paper/backtest: percentages resolve against the (paper) starting balance.
    config = service_config_from_dict(raw_config, total_quote=Decimal(args.quote_balance))
    if args.backtest:
        return _run_backtest(args, config)

    client = BinanceRestClient(urllib_transport, base_url=args.base_url)
    service, account = build_paper_service(client, config, args.quote_balance)

    print(f"Paper trading {list(config.coins)} — starting balance {args.quote_balance}")
    update, server = _setup_monitoring(
        list(config.coins), service, account, config.cost_model, args.status_port
    )

    def on_report(i, report, acct):
        update(report)
        _print_report(i, report, acct)

    try:
        run_paper(
            service, account,
            ticks=args.ticks or None,
            interval_s=args.interval,
            on_report=on_report,
        )
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        if server is not None:
            server.stop()
    return 0
