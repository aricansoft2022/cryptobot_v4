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
  cli.py             # runnable paper-trading entrypoint (python -m cryptobot)
tests/               # 173 tests; exact-boundary and golden-value coverage
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
pytest            # 173 tests
```

(`pyproject.toml` sets `pythonpath = ["src"]`; a root `conftest.py` provides the
same fallback for any pytest version.)
