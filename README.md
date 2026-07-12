# cryptobot_v4 — Trading strategy core

The deterministic core of the trading strategy: the RSI / RSI-VWMA / ADX / ADR
indicators, the entry/exit signal rules, per-coin immutable parameter snapshots,
conservative net-PnL estimation, and the operational safety gates.

The strategy is **fixed and deterministic**. This code does **not** add its own
indicators, extra filters, stop-loss, trailing stop, alternative crossover rules,
or alternative entry/exit logic. Every rule below is implemented exactly as
specified.

## Layout

```
src/cryptobot/
  market/
    candle.py        # immutable 1-minute OHLCV candle
    validation.py    # closed / same-symbol / contiguous / no-dupes / no-gaps
  indicators/
    rsi.py           # Wilder RSI from OPEN prices (+ special cases)
    rsi_vwma.py      # volume-weighted MA of RSI (fail-closed on zero volume)
    adx.py           # Wilder ADX + +DI/-DI (display only)
    adr.py           # average range over candles BEFORE t (excludes t)
  strategy/
    parameters.py    # frozen per-coin CoinStrategyParameters
    indicators.py    # bundle: compute all four, aligned, with t / t-1 access
    position.py      # immutable snapshot + OPEN/EXIT_ARMED/CLOSED state machine
    entry.py         # the five-condition BUY signal (fail-closed)
    exit.py          # normal two-phase exit + withdrawal-mode exit
    engine.py        # signal + gates -> buy intent; exit routing by mode
  execution/
    orderbook.py     # bid-walking sell estimate (captures slippage)
    pnl.py           # conservative estimated net PnL
    gates.py         # operational safety gates + per-candle idempotency
  exchange/          # Binance adapter (pure mapping/mechanics, no I/O)
    filters.py       # symbol filters: order acceptance + increment rounding
    fills.py         # real fills -> RealizedEntry; realized PnL + slippage
    market_data.py   # Binance klines -> Candle[]; depth -> OrderBook
    binance_rest.py  # signed REST client + port adapters (injected transport)
    binance_ws.py    # streaming MarketDataPort (rolling closed-candle buffer)
    http.py          # stdlib urllib transport (production HTTP, no deps)
  runtime/           # composition boundary
    ports.py         # MarketData / Account / Execution / Clock protocols
    orchestrator.py  # thin coordinator: decision core + injected ports
    providers.py     # operational helpers: clock, sizing, data freshness
    service.py       # TradingService: the per-coin scheduler loop
    paper.py         # paper ledger account + simulated executor
    live.py          # real Binance account, reconciliation, guarded runner
    metrics.py       # realized-trade metrics + live status snapshot
    status_server.py # stdlib HTTP server exposing the snapshot as JSON
  backtest/          # historical replay through the SAME live engine
    replay.py        # ReplayMarketData + BacktestClock
    runner.py        # run_backtest + BacktestReport
  cli.py             # runnable entrypoint: paper-trade, backtest, or live
tests/               # 210 tests; exact-boundary and golden-value coverage
```

## Indicators

All signal math runs **only** on candles that are closed, same-symbol,
1-minute, chronologically ordered, duplicate-free and gap-free
(`market/validation.py`). Missing or stale data ⇒ no signal (fail-closed).

* **RSI** (`indicators/rsi.py`) — computed from `open` prices (never `close`),
  Wilder smoothing. Special cases: gain+loss = 0 ⇒ 50; only loss = 0 ⇒ 100;
  only gain = 0 ⇒ 0.
* **RSI-VWMA** (`indicators/rsi_vwma.py`) — `sum(RSI·vol)/sum(vol)` over
  `[t-rsi_ma_period+1, t]`. Zero total volume ⇒ fail-closed (no fabricated value).
* **ADX** (`indicators/adx.py`) — standard Wilder ADX from high/low/close.
  `+DI`/`-DI` are exposed for display only and are **not** entry filters.
* **ADR** (`indicators/adr.py`) — average high-low range over `[t-adr_period, t)`;
  the current candle `t` is **excluded** from its own ADR.

## Entry (BUY) — all five must hold on the last closed candle `t`

```
ENTRY_SIGNAL =
    RSI[t] < rsi_oversold                    # strict
    AND RSI[t-1] <= RSI_VWMA[t-1]            # inclusive
    AND RSI[t] > RSI_VWMA[t]                 # strict  (bullish crossover)
    AND adx_low <= ADX[t] <= adx_high        # inclusive band
    AND ADR[t] > ADR[t-1]                    # strict  (range expanding)
```

Conditions 2 and 3 together are the bullish RSI/RSI-VWMA crossover. `+DI`/`-DI`
are not part of the formula. See `strategy/entry.py`.

A technical signal is necessary but not sufficient. A real order is placed only
when **every** operational gate is open (`execution/gates.py`): runtime RUNNING,
trading enabled, coin active and not pending delete, market data fresh, candles
contiguous, indicators ready, coin+candle not already processed, slots below
`slot_count`, capital below `capital_limit_usdt`, sufficient USDT, Binance symbol
filters accept the order, worker holds a valid lease, reconciliation clean,
system safe. The same coin + same closed candle can never produce a second BUY
(`ProcessedCandleGuard`).

## Normal exit — two phases (no stop-loss, ever)

1. **RSI arming** (`update_exit_arming`): on closed candle `t`,
   `RSI[t] > snapshot.rsi_overbought` (strict) moves the position to
   `EXIT_ARMED`. Arming is **permanent** — a later RSI drop never disarms it and
   RSI is never re-checked to cancel a sell.
2. **Minimum net profit** (`should_sell_normal`): once armed, watch the live
   market and SELL only when the conservative estimated net PnL reaches the
   target:

   ```
   estimated_net_pnl_usdt >= invested_quote_cost_usdt * min_net_profit_pct / 100
   ```

There is **no** stop-loss, trailing stop, time-based loss cut, or profit-only
sell without arming.

## Withdrawal-mode exit

When the global mode is `WITHDRAWAL_REQUESTED`: no new entries; open positions
ignore RSI/arming entirely and SELL as soon as conservative net PnL reaches a
fixed **0.20%** of invested quote cost. Positions below the threshold are held
(never sold at a loss).

## Conservative net PnL

Exit decisions never use `current_price > buy_price`. `execution/pnl.py`
estimates net PnL from: the real entry notional and entry fees, the actually
sellable base quantity, estimated market-sell proceeds walked from the live
order book (slippage), the expected exit commission, and an execution safety
buffer:

```
estimated_net_pnl = exit_proceeds - true_entry_cost - entry_fees
                    - estimated_exit_fees - execution_safety_buffer
```

Realized PnL after a fill is a separate concern and must be computed from real
Binance fills/commissions; the estimate is only for the pre-trade decision
(`exchange/fills.py` `realized_pnl`, including estimate-vs-realized slippage).

## Binance adapter & runtime

`exchange/` translates Binance data into the core's types and back — pure
mechanics, no strategy and no I/O:

* **`filters.py`** — parses `exchangeInfo` symbol filters (`LOT_SIZE` /
  `MARKET_LOT_SIZE`, `PRICE_FILTER`, `NOTIONAL`) and deterministically rounds
  quantities/prices to valid increments and checks acceptance. This backs the
  `symbol_filters_ok` gate and sell-quantity rounding.
* **`fills.py`** — aggregates real fills into an immutable `RealizedEntry`
  (weighted avg price, true cost, fees valued in quote, sellable qty net of
  base-asset commission) and computes realized PnL from real sell fills.
* **`market_data.py`** — maps Binance klines to `Candle`s (dropping the still-open
  one) and a depth snapshot to an `OrderBook`.

`binance_rest.py` holds the real Binance endpoint paths and HMAC-SHA256 request
signing but delegates the actual HTTP call to an **injected transport**, so no
credentials or network live in the codebase. `BinanceMarketData` /
`BinanceExecution` implement the runtime ports on top of it; production injects a
real HTTP client, tests inject a fake. `binance_ws.py` (`StreamingMarketData`) is
a streaming `MarketDataPort`: it folds parsed WebSocket kline/depth messages into
a rolling buffer of **closed** candles (replacing a re-sent final candle, ignoring
stale ones) and the latest order book — the socket loop itself is injected, and
contiguity is still enforced downstream so the fail-closed guarantee holds.

`runtime/` is the composition boundary. `ports.py` declares the injected
dependencies (market data, account, execution, clock) as `Protocol`s;
`orchestrator.py` (`TradingRuntime`) only *coordinates* the existing
`evaluate_buy` / `evaluate_exit` decisions with those ports — order sizing and
gate construction are supplied by the caller, so no signal logic lives there.
`providers.py` offers optional, overridable operational helpers (`SystemClock`,
an equal-slot `equal_slot_quote_amount` sizing default, and an
`is_market_data_fresh` check) — none of which touch the strategy signal.

`service.py` (`TradingService`) is the per-coin scheduler: each `tick` it builds
the operational gates from live account/data state, evaluates entries for every
configured coin and exits for every open position, and tracks positions. Infra
signals it can't derive (runtime RUNNING, trading enabled, worker lease,
reconciliation, system safety, per-coin active / pending-delete) are passed in as
an `OperationalStatus`. It composes the decision core only — it invents no signal.

## Running it

`cli.py` (`python -m cryptobot`) runs the strategy against **real, read-only**
Binance market data while simulating fills in a paper ledger — safe by default,
no API keys required (`runtime/paper.py`). Live order placement is deliberately
not exposed by the CLI; wire `BinanceExecution` into a `TradingService` yourself
to trade for real.

```bash
python -m cryptobot --config examples/config.example.json --ticks 5 --interval 60
```

## Backtesting

`backtest/` replays a historical candle series through the **exact same**
`TradingService` — identical signals, gates, and exit rules — one tick per candle,
with fills simulated against a replayed order book (`ReplayMarketData` reveals only
history up to the current index, so the engine never sees the future). It adds no
strategy logic; backtest fills are an explicit approximation, never a substitute
for real execution. `run_backtest(...)` returns a `BacktestReport` (trades, net
PnL, win rate, final balance). From the CLI, point `--backtest` at a JSON klines
file (`{symbol: [binance kline array, …]}`):

```bash
python -m cryptobot --config examples/config.example.json \
    --backtest klines.json --quote-per-order 100 --quote-balance 1000
```

By default the backtest uses the full available history as warmup so Wilder
indicators are fully converged; a live deployment must fetch adequate warmup to
match.

## Live execution ⚠️

`runtime/live.py` wires the service to place **real Binance orders**
(`BinanceExecution`), backed by a real `BinanceAccount` (live balance + tracked
slots/capital) and a **reconciliation gate**: every tick it checks that the
exchange still holds at least the base quantity the bot expects, and halts trading
(`reconciliation_clean = False`) on any shortfall from a manual sale, unexpected
fill, or crash.

Live trading is opt-in and hard to trigger by accident:

- credentials come only from `BINANCE_API_KEY` / `BINANCE_API_SECRET` (never
  stored or logged);
- `--live` refuses to run without them;
- real money requires an explicit `--yes-trade-real-money`; otherwise use
  `--testnet` (Binance testnet, fake money).

```bash
export BINANCE_API_KEY=... BINANCE_API_SECRET=...
python -m cryptobot --config examples/config.example.json --live --testnet        # safe
python -m cryptobot --config examples/config.example.json --live --yes-trade-real-money
```

Single-process operation assumes the worker lease is always held; a multi-instance
deployment must supply a real distributed lease. Test on `--testnet` first and
start with small `capital_limit_usdt`.

## Monitoring

Pass `--status-port N` to any paper or live run to serve a read-only JSON status
snapshot at `http://127.0.0.1:N/status` (and a `/health` probe). `MetricsTracker`
accumulates realized trades from each tick; `build_status` adds the open positions
with a **conservative unrealized-PnL estimate** (same estimator as the exit
decision, against the current book). Example payload:

```json
{
  "available_quote": "900",
  "open_positions": [
    {"symbol": "BTCUSDT", "state": "OPEN", "qty": "1", "invested_quote": "100",
     "estimated_net_pnl": "-1"}
  ],
  "open_invested_quote": "100", "estimated_unrealized_net_pnl": "-1",
  "realized_trades": 0, "realized_net_pnl": "0", "wins": 0, "losses": 0, "win_rate": 0.0
}
```

```bash
python -m cryptobot --config examples/config.example.json --status-port 8787
```

## Per-coin configuration

Every coin under the config's `coins` map is independent — add or remove a coin
by editing the file and restarting (there is no runtime add/remove). Per coin you
set:

- **Signal thresholds**: `rsi_oversold`, `rsi_overbought`, `adx_low`, `adx_high`
  (plus periods `rsi_period` / `rsi_ma_period` / `adx_period` / `adr_period` and
  `min_net_profit_pct`).
- **Capital** — choose exactly one:
  - `capital_limit_usdt` — a fixed absolute cap; or
  - `capital_pct` — a percentage of your **total USDT balance** (free + locked),
    resolved to an absolute cap **once at startup** and then fixed for the session
    (restart to re-resolve). Paper/backtest resolve it against `--quote-balance`;
    live reads your real balance.
- **`slot_count`** — how many parts the capital is split into: each order uses
  `capital / slot_count`, and at most `slot_count` positions are open at once.

```json
"BTCUSDT": { "...": "...", "capital_limit_usdt": "1000", "slot_count": 3 },
"ETHUSDT": { "...": "...", "capital_pct": 30,            "slot_count": 2 }
```

BTC gets a fixed 1000 USDT split into 3 (~333 each); ETH gets 30% of your total
USDT split into 2. Each open position captures these as an immutable snapshot, so
later config changes never affect positions already open.

## Immutable per-position snapshot

`CoinStrategyParameters` is frozen. When a position opens it captures the
parameter set in force at that moment (`open_position`). Updating a coin's
settings means constructing a **new** parameter object for future decisions —
open positions keep the instance they were opened with, so their entry/exit
rules never change mid-life.

## Scope / boundary

The decision core and the Binance adapter are both pure and perform **no I/O**.
Live connectivity — REST/websocket transport, API credentials, balances, worker
leases, reconciliation, and the actual placement of orders — is injected through
the `runtime/` ports (`MarketDataPort`, `AccountPort`, `ExecutionPort`,
`ClockPort`) and the `OperationalGates`. This keeps every strategy rule and every
mapping unit-testable and exactly auditable against the spec, with no secrets or
network in the codebase.

## Running the tests

```bash
pytest            # 210 tests
```

(`pyproject.toml` sets `pythonpath = ["src"]`; a root `conftest.py` provides the
same fallback for any pytest version.)
