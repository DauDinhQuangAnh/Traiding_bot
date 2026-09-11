# PHASE 5 Deterministic Backtesting

## 1. Purpose

PHASE 5 answers whether the already approved deterministic strategy and Risk Engine can
be replayed on versioned historical data with conservative, auditable execution and
accounting. It does not optimize the strategy and does not claim profitability.

## 2. Architecture

```text
SQLiteHistoricalCandleRepository (explicit M5/M15/H1 versions)
  -> point-in-time snapshot builder
  -> unchanged PHASE 3 strategy replay on closed M15
  -> sequential M5 BacktestEngine
  -> unchanged evaluate_risk(candidate, current RiskContext)
  -> ApprovedTradePlan-only order simulator
  -> incremental portfolio, equity and risk state
  -> immutable event/order/fill/funding/trade/metric artifacts
  -> SQLiteBacktestRepository + canonical JSON/Markdown reports
```

The application layer owns orchestration. The backtest core has no network dependency,
and the persistence adapter is outside the application/domain boundary.

## 3. Event clock

Closed M5 candles are the execution clock. For each M5 event, ordering is fixed:

1. Reset a configured daily session when its calendar boundary is crossed.
2. Expire or fill the previously approved pending entry at the M5 open.
3. Apply an M5-open-aligned funding event using the M5 open as its mark, but only to a
   position whose entry time is strictly earlier than the funding timestamp.
4. Resolve stop/target touches, including an optional same-entry-bar exit.
5. Mark the portfolio at the M5 close using the side-adverse modeled quote.
6. Evaluate an M15 strategy result whose `as_of` equals that close.
7. Ask the Risk Engine for REJECT, HALT, or an `ApprovedTradePlan`.
8. Journal all outcomes in deterministic sequence order.

Inputs must be unique and strictly time ordered. M15 evaluations must be UTC, in range,
and aligned to a 15-minute close boundary. Journal `event_time` is monotonic; sequence
is the deterministic tie-break when multiple events share a timestamp.

## 4. Signal timing

M15 remains the only strategy trigger. H1 remains context and M5 remains the smallest
execution timeframe. A decision at time `T` uses only candles closed at or before `T`.
The market-like entry intent is created after that decision and the first eligible fill
event is the M5 bar opening at `T`.

## 5. No-look-ahead guarantees

- The PHASE 4 repository requires an explicit version for every query.
- Snapshot construction calls `latest_before(..., as_of=T)` for M5, M15, and H1.
- The strategy sees a completed snapshot, never execution bars after `T`.
- Entry simulation refuses any bar whose `open_time < eligible_from`.
- A signal candle's historical high/low cannot retroactively fill its new order.
- Appending future bars outside a fixed run range leaves the canonical result unchanged.
- Future dataset versions coexist without mutating an old version's query result.

## 6. Entry execution

The approved `CLOSE_REFERENCE` entry model is simulated as market-like execution at the
next eligible M5 open. LONG buys at modeled ask plus adverse slippage; SHORT sells at
modeled bid minus adverse slippage. The order must reference an unexpired
`ApprovedTradePlan`; an unapproved candidate cannot create an order or fill. Immediately
before opening a position, the simulator revalidates the actual fill without calling the
Risk Engine again or resizing: price deviation, side geometry, stop invariants, net RR,
worst-case loss versus the approved risk budget, notional/exposure/leverage, margin, and
maximum slippage must all remain valid. Rejection is terminal and journals the approved
entry, actual entry, deviation, actual RR, actual worst loss, budget, capacities, and
reason codes. Fill construction and every arithmetic input to this last-mile validation
run inside the configured `CalculationConfig` Decimal context. The scope applies the
declared precision and rounding mode with `localcontext`, so caller ambient precision or
rounding cannot alter the canonical result and the context does not leak after return.
Expected arithmetic failures reject with canonical `NUMERICAL_ERROR`. Any entry model
other than `CLOSE_REFERENCE` fails closed.

## 7. Stop execution

Stops are stop-market assumptions and use taker fees. A normal LONG stop sells below
the modeled bid at the stop reference; a normal SHORT stop buys above the modeled ask.
Slippage is always adverse and Decimal-based.

## 8. Target execution

A touched target fills at its exact approved target price and pays the configured taker
fee. The model grants no favorable gap improvement. This is intentionally conservative
and does not pretend to know order-book queue position.

## 9. Gap handling

For a LONG gap below its stop, the reference becomes the lower M5 open, followed by
adverse spread and stop slippage. A SHORT gap above its stop is symmetric. The engine
never reports the original stop as the fill when the open already crossed it. A gap
beyond a target still fills at the target, without improvement.

## 10. Intrabar ambiguity

`WORST_CASE` is the only supported PHASE 5 policy. If one M5 candle touches both the
stop and one or more targets, the stop consumes all remaining quantity for both LONG
and SHORT. When entry, stop, and target all occur in one M5 OHLC envelope, the same
rule applies. No random or synthetic intrabar path is invented.

## 11. Spread model

The deterministic historical quote is centered on a reference mid:

```text
bid = mid * (1 - modeled_spread_rate / 2)
ask = mid * (1 + modeled_spread_rate / 2)
```

The model source and version are recorded. The development rate is an assumption, not
historical bid/ask evidence and not a current OKX fact.

## 12. Slippage model

Market buys multiply ask by `(1 + market_slippage_rate)` and market sells multiply bid
by `(1 - market_slippage_rate)`. Stop exits use their separate adverse stop rate.
Spread/slippage are embedded in executed prices; attribution fields are counterfactual
estimates and are never subtracted from account equity a second time.

## 13. Fee model

Fees equal `actual executed notional * configured fee rate`. Market, stop, target, and
the conservative limit baseline use taker liquidity. The maker rate remains versioned
for an explicitly modeled future maker policy; it is not silently selected. Fees are
non-negative and charged once per fill.

## 14. Funding model

`FundingRateProvider` has three typed modes:

- `DISABLED`: no cash flow and a structured warning.
- `FIXED_ASSUMPTION`: deterministic UTC epoch-aligned events using an explicit rate and
  interval.
- `HISTORICAL_SERIES`: explicit ordered observations and version; every required event
  in the requested range must exist or validation fails closed.

Positive rates debit LONG and credit SHORT; negative rates reverse that direction.
Funding uses the remaining position notional at the event mark and is recorded as an
individual cash-flow artifact. PHASE 5 supports funding only when its timestamp equals
an M5 open; an event strictly inside a bar fails validation. The boundary mark is
`bar.open`, never close/high/low. An entry at the exact funding timestamp is not charged;
a pre-existing position exiting at that timestamp is charged before its exit is resolved.

## 15. Instrument metadata

PnL, notional, quantity steps, minimums, margin, and leverage use an injected,
versioned `InstrumentMetadata`. PHASE 5 supports only explicitly declared linear,
quote-margined semantics. It contains no hard-coded OKX contract multiplier or
liquidation tier.

## 16. Risk integration

Every candidate reaches the unchanged `evaluate_risk` function with a fresh
`RiskContext` derived from portfolio state, modeled quote, metadata, versions, daily
counters, cooldown, consecutive losses, open-position count, and margin. REJECT creates
no order. HALT ends the historical run as `HALTED`. Only the Risk Engine creates the
`ApprovedTradePlan` used by the simulator.

## 17. Portfolio accounting

For a linear contract with injected base multiplier:

```text
LONG gross fill PnL  = (exit_fill - entry_fill) * base_quantity
SHORT gross fill PnL = (entry_fill - exit_fill) * base_quantity
trade net PnL        = gross price PnL - entry fees - exit fees + funding cash flow
equity               = cash + unrealized PnL
```

Spread and slippage already affect fill prices. Their analytics fields are not extra
cash debits. Remaining quantity, target allocations, fees, margin, and equity have
explicit non-negative/finite invariants where applicable. A fully closed trade is
emitted exactly once. A catastrophic gap may legitimately make cash and equity negative.
Because liquidation is not modeled, that outcome is retained, emits an `ECONOMIC_HALT`
with `EQUITY_DEPLETED`, blocks future entries, and ends deterministically as `HALTED`
rather than being converted into an input-validation failure or clamped to zero.

## 18. Equity curve

Equity is marked once per processed M5 close, plus a final revaluation point after a
forced close.
An open LONG is marked at modeled bid and an open SHORT at modeled ask. Used margin is
current notional divided by approved leverage; available margin is conservatively
floored at zero. Exposure is measured as marked M5 bars with an open position. The final
forced-close revaluation does not increment the M5-bar denominator, so a 10-bar run
exposed for five closes reports exactly `0.5`.

## 19. Drawdown

Maximum drawdown is computed from the equity curve, not only closed trades. The report
stores absolute drawdown, peak-to-trough ratio, peak time, trough time, and first
recovery time when present. The golden curve `100,110,105,120,90,100,130` produces an
exact Decimal drawdown of `30` and `25%`.

## 20. Metrics

Implemented metrics include gross/net PnL, return, trade/win/loss/breakeven counts,
win rate, profit factor, expectancy, expectancy-R, average/median R, average win/loss,
best/worst trade, drawdown, maximum/current streaks, holding duration, market exposure,
fees, funding, modeled spread/slippage attribution, cost share, evaluation/NO_TRADE/
candidate/Risk/order counters, and end equity. Undefined ratios are `null`, never a
fabricated zero. Sharpe and Sortino are not implemented in this baseline.

## 21. Regime/setup breakdown

The same performance summary is grouped deterministically by LONG/SHORT side, entry
regime, setup type, year, and month. Results report behavior only; they never disable a
side, regime, or setup and never feed results back into strategy parameters.

## 22. Version identity

`backtest_run_id` hashes code, strategy, app-config, M5/M15/H1 and snapshot-composite
versions, instrument metadata, execution model, cost model, funding model, explicit UTC
range, and initial equity. Execution identity hashes timing and ambiguity policies,
the last-mile validation version, deviation tolerance, relevant risk caps/invariants,
funding-buffer interval count, and the same Decimal calculation policy used by actual
last-mile fill construction and validation. Changing configured Decimal precision changes
execution identity even when a particular simple fixture happens to round identically.
Cost identity hashes spread, slippage, fees, funding mode/rate/interval, and provider
version. Host paths, wall clock, UUIDs, and database location are excluded.

## 23. Persistence

`SQLiteBacktestRepository` transactionally appends the canonical run, ordered events,
orders, fills, funding, trades, equity curve, and metrics. Re-appending identical bytes
is idempotent. The same run ID with different content fails; nothing is overwritten.
The persistence port converts an expected adapter failure into a typed `FAILED` result,
while programming invariants still raise.

## 24. Determinism

The engine uses Decimal, UTC timestamps, deterministic content-derived IDs, stable
collection ordering, immutable emitted models, explicit prior portfolio state, and no
randomness. Last-mile entry math explicitly overrides surrounding Decimal precision and
rounding within a non-leaking local scope. Two complete runs must have byte-identical
canonical JSON. Rebuilding the SQLite database must preserve the same stored bytes.

## 25. Limitations

- Historical OHLCV only; no order-book queue or true historical bid/ask.
- Modeled spread, slippage, full limit fill, and zero latency.
- No sub-M5 price path; ambiguity is resolved by declared worst case.
- No true partial fills, market impact, exchange outage, or network behavior.
- `liquidation_model = NOT_IMPLEMENTED`; no invented venue maintenance-margin rules.
- Development fees/funding/metadata are assumptions unless separately sourced and
  versioned; they are not current OKX verification.
- End-of-run open positions are forcibly closed at the last available M5 close using
  modeled spread, slippage, and fee.
- No production dataset is committed and no live-execution evidence exists.
- Funding observations not aligned to an M5 open are rejected; no intrabar ownership
  ordering is invented.
- Negative equity is reported without a liquidation-price or bankruptcy-fill model and
  therefore carries a structured warning.
- Technical reproducibility does not establish an economic edge.

## 26. Acceptance criteria

Implementation evidence is enumerated in [PHASE 5 Review](phase-5-review.md). Local
pytest, Ruff, mypy, format, and compile gates must pass. Python 3.12 GitHub Actions and
explicit human review remain external gates; until both are complete, PHASE 5 remains
`NEEDS_WORK` and PHASE 4 remains the last approved phase.
