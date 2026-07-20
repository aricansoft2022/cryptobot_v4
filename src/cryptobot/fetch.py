"""Download many Binance klines (paginated) for one or more symbols.

Binance returns at most **1000** klines per request, so a longer history must be
paginated. This walks backwards from now in 1000-candle batches and writes a
combined ``{symbol: [kline, ...]}`` JSON file ready for ``--backtest``.

Run it as a module:

.. code-block:: bash

    python -m cryptobot.fetch BTCUSDT,ETHUSDT --total 5000 --output klines.json

Only the standard library is used. The pagination logic (:func:`paginate`) is
pure and takes an injected batch fetcher, so it is testable without network.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from typing import Callable, Dict, List, Sequence

#: Binance hard cap on klines per request.
MAX_LIMIT = 1000

# fetch_batch(symbol, interval, limit, end_time_ms_or_None) -> list of kline rows
BatchFetcher = Callable[[str, str, int, "int | None"], List[list]]


def paginate(
    symbol: str,
    interval: str,
    total: int,
    fetch_batch: BatchFetcher,
    pause: float = 0.0,
    sleep: Callable[[float], None] = time.sleep,
) -> List[list]:
    """Collect the most recent ``total`` klines by walking backwards in batches.

    Args:
        symbol, interval: Passed through to ``fetch_batch``.
        total: Desired number of candles (may be capped by available history).
        fetch_batch: Returns up to ``limit`` klines ending at ``end_time`` (ms),
            oldest-first, like Binance's ``/api/v3/klines``.
        pause: Seconds to sleep between batches (rate-limit courtesy).
        sleep: Injected sleep (tests pass a no-op).

    Returns:
        Deduplicated klines sorted ascending by open time.
    """
    collected: List[list] = []
    end_time = None
    first = True
    while len(collected) < total:
        if not first and pause:
            sleep(pause)  # between requests only (not before the first, not after the last)
        first = False
        limit = min(MAX_LIMIT, total - len(collected))
        batch = fetch_batch(symbol, interval, limit, end_time)
        if not batch:
            break
        collected = list(batch) + collected
        end_time = int(batch[0][0]) - 1  # next batch ends just before the earliest open
        if len(batch) < limit:
            break  # reached the start of available history

    by_open_time = {int(row[0]): row for row in collected}
    return [by_open_time[t] for t in sorted(by_open_time)]


def binance_fetch_batch(
    symbol: str,
    interval: str,
    limit: int,
    end_time,
    base_url: str = "https://api.binance.com",
    timeout: float = 20.0,
) -> List[list]:
    """Fetch one batch of klines from the real Binance REST endpoint."""
    params = {"symbol": symbol, "interval": interval, "limit": min(limit, MAX_LIMIT)}
    if end_time is not None:
        params["endTime"] = int(end_time)
    url = f"{base_url}/api/v3/klines?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def fetch_symbols(
    symbols: Sequence[str],
    total: int,
    interval: str = "1m",
    base_url: str = "https://api.binance.com",
    pause: float = 0.25,
    on_symbol: Callable[[str, int], None] = lambda s, n: None,
) -> Dict[str, List[list]]:
    """Fetch ``total`` klines for each symbol and return a combined mapping."""
    def fetch(sym, iv, limit, end_time):
        return binance_fetch_batch(sym, iv, limit, end_time, base_url=base_url)

    data: Dict[str, List[list]] = {}
    for symbol in symbols:
        rows = paginate(symbol, interval, total, fetch, pause=pause)
        data[symbol] = rows
        on_symbol(symbol, len(rows))
    return data


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="cryptobot.fetch",
        description="Download paginated Binance klines for backtesting.",
    )
    parser.add_argument("symbols", help="Comma-separated symbols, e.g. BTCUSDT,ETHUSDT")
    parser.add_argument("--total", type=int, default=5000, help="Candles per symbol (default 5000).")
    parser.add_argument("--interval", default="1m", help="Kline interval (default 1m).")
    parser.add_argument("--output", default="klines.json", help="Output file (default klines.json).")
    parser.add_argument("--base-url", default="https://api.binance.com", help="Binance REST base URL.")
    parser.add_argument("--pause", type=float, default=0.25, help="Seconds between batch requests.")
    args = parser.parse_args(argv)

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        print("ERROR: no symbols given", file=sys.stderr)
        return 2

    def report(symbol: str, count: int) -> None:
        print(f"{symbol}: {count} candles", file=sys.stderr)

    data = fetch_symbols(
        symbols, args.total, interval=args.interval,
        base_url=args.base_url, pause=args.pause, on_symbol=report,
    )
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    print(f"wrote {args.output} ({len(symbols)} symbol(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
