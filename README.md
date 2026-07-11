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
tests/               # 100 tests; exact-boundary and golden-value coverage
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
Binance fills/commissions; the estimate is only for the pre-trade decision.

## Immutable per-position snapshot

`CoinStrategyParameters` is frozen. When a position opens it captures the
parameter set in force at that moment (`open_position`). Updating a coin's
settings means constructing a **new** parameter object for future decisions —
open positions keep the instance they were opened with, so their entry/exit
rules never change mid-life.

## Scope / boundary

This package is the pure, deterministic **decision core** and performs no I/O.
Live infrastructure — Binance connectivity, market-data streaming, balances,
symbol filters, worker leases, reconciliation, order placement and realized-fill
accounting — is intentionally out of scope here and is represented as injected
inputs (`OperationalGates`, `OrderBook`, realized `RealizedEntry` data). This
keeps every strategy rule unit-testable and exactly auditable against the spec.

## Running the tests

```bash
pytest            # 100 tests
```

(`pyproject.toml` sets `pythonpath = ["src"]`; a root `conftest.py` provides the
same fallback for any pytest version.)
