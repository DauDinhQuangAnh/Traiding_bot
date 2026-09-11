# PHASE 5 Plan — Deterministic Backtest Engine

## 1. Scope

Build a reproducible offline backtest for `BTC-USDT-SWAP` that consumes the PHASE 4
M5/M15/H1 version bundle, evaluates the unchanged PHASE 3 strategy on closed M15
events, passes every candidate through the existing Risk Engine, simulates conservative
execution, maintains position/portfolio state, and produces auditable net performance
analytics and immutable local artifacts.

## 2. Non-goals

- No OKX REST/WebSocket, credentials, CCXT/SDK, order submission, Demo or Live loop.
- No strategy/indicator/regime/risk threshold changes, calibration, parameter search,
  ML/AI, walk-forward optimization, or profitability claim.
- No invented order book, queue, latency, partial-fill, liquidation, exchange outage,
  or venue-specific maintenance-margin model.
- No dashboard; deterministic JSON is the primary report format.

## 3. Backtest architecture

```text
Versioned historical repository
  -> sequential M5 clock
  -> pending-order and open-position execution
  -> funding and M5-close mark
  -> closed-M15 snapshot trigger
  -> existing evaluate_market strategy pipeline
  -> existing RiskEngine
  -> approved-plan-only simulated entry
  -> portfolio and lifecycle ledger
  -> metrics, journal, SQLite and report
```

The application pipeline orchestrates ports and domain services. Backtest core does
not import SQLite or any network adapter. Strategy remains unaware of fills/accounting.

## 4. Event clock

M5 is the only execution clock. Bars are strictly ordered by `(close_time, open_time,
candle_id)`. For each M5 bar the engine: expires/processes pre-existing entries,
activates protection on fill, resolves stop/targets, applies funding, marks equity at
close, updates risk state, evaluates a newly closed M15 interval, then appends audit
records. Collection ordering is explicit and never depends on mapping iteration.

## 5. Market evaluation timing

M15 remains the sole strategy trigger and H1 remains closed higher-timeframe context.
A decision at M15 close `T` may use only candles with `close_time <= T`. Its order has
`eligible_from=T` and can first use the M5 bar whose `open_time >= T`; no high/low from
the completed signal interval can fill it retroactively. Warm-up comes from the PHASE 4
point-in-time snapshot builder; insufficient history is not traded.

## 6. Order simulation semantics

`EntryModel.CLOSE_REFERENCE` is interpreted as a market-like entry at the next eligible
M5 open. Buy fills at modeled ask plus adverse market slippage; sell fills at modeled
bid minus adverse market slippage. A backtest-specific limit interface is retained for
approved plans that explicitly request it: future touch is required and MVP uses a
labelled deterministic full fill. Pending orders have deterministic IDs, one-shot
approval use, creation/eligibility/expiry timestamps, and cannot exist without an
unexpired `ApprovedTradePlan`.

## 7. Intrabar ambiguity policy

Only `WORST_CASE` is supported in the PHASE 5 baseline. If stop and target are both
touched within one M5 bar, stop wins for LONG and SHORT. The same rule applies after
an entry filled at that bar's open when same-bar exits are enabled. No synthetic
intrabar path or random ordering is generated.

## 8. Cost model

Rates are explicit Decimal inputs. A modeled quote is centered on reference mid:
`bid=mid*(1-spread/2)`, `ask=mid*(1+spread/2)`. Spread and slippage are embedded in
fill prices; their counterfactual cost estimates are recorded but never subtracted a
second time. Fees use executed notional and explicit maker/taker role; uncertain and
market/stop execution use taker. Cost-model identity hashes spread, slippage, fees and
funding assumptions.

## 9. Funding model

A `FundingRateProvider` protocol supports `DISABLED`, deterministic fixed assumption,
and versioned historical series without network access. Historical-series gaps fail
closed. At an applicable UTC timestamp, positive rates debit LONG and credit SHORT;
negative rates reverse the sign. Funding uses open-position executed exposure at the
documented event mark. Disabled funding emits a structured warning.

## 10. Portfolio accounting

All financial values use Decimal. The linear contract formula uses injected
`InstrumentMetadata.contract_value_base`; unsupported or incomplete metadata fails
before the run. Realized account value changes by gross exit PnL minus fill fees plus
funding cash flow. Open positions are marked at M5 close using the side-adverse modeled
quote without an additional fee. Equity equals realized account value plus unrealized
PnL. Margin, peak equity, drawdown, daily net PnL/trade count, consecutive losses,
cooldown and open-position count are updated incrementally. Daily boundaries are UTC.

## 11. Risk Engine integration

Every candidate receives a fresh `RiskContext` assembled from current portfolio,
modeled quote, injected metadata, deterministic health/state and current UTC event.
The existing `RiskEngine.evaluate()` is called unchanged. REJECT creates no pending
entry. HALT makes the run `HALTED`, cancels entries and permits only risk-reducing
position handling. Only APPROVE supplies the immutable plan used by the simulator.
Risk state is never reset between evaluations except the documented UTC session reset;
an active kill switch is not automatically cleared.

## 12. Trade lifecycle integration

Canonical `trade_id` remains the candidate ID. The backtest records candidate, risk
decision, plan, order, fills, position revisions and close exactly once. Multiple
targets respect each target fraction and remaining quantity; the stop remains unchanged
after partial targets because the approved strategy defines no break-even/trailing rule.
Trade count increments at first non-zero entry fill; consecutive loss and cooldown
update only on full close.

## 13. Performance metrics

Implement net/gross PnL, return, trade/win/loss/breakeven counts and rates, net profit
factor, expectancy and expectancy-R, average/median R, average wins/losses, best/worst
trade, equity-curve maximum drawdown and timestamps, consecutive wins/losses, holding
time, exposure, fees/funding/spread/slippage attribution, cost share, and breakdowns by
side, entry regime, setup, year and month. Undefined denominators produce `None`, not a
misleading zero. Sharpe/Sortino are outside the baseline.

## 14. Persistence

SQLite stores immutable runs, ordered events, orders, fills, trades, equity points and
metrics. Same run ID with canonical-identical content is idempotent; different content
under that ID is an error. Persistence is transactional per completed run and failure
returns `FAILED`; audit rows are never silently overwritten. Canonical JSON report
serialization is the reproducibility artifact.

## 15. Reproducibility and versioning

`backtest_run_id` hashes code, strategy and app-config versions; explicit M5/M15/H1
versions and their snapshot composite; instrument metadata version; execution, cost
and funding model versions; UTC start/end; and initial equity. Model versions hash the
actual assumptions. Paths, host, wall-clock and UUIDs are excluded. Same input and
state yield byte-identical ordered artifacts; a changed dataset, strategy or cost
assumption changes the run ID.

## 16. Testing

Use reviewable synthetic fixtures and focused unit, property, orchestration,
persistence and golden tests. Mandatory coverage includes future-only entry timing,
same-M15 leakage trap, LONG/SHORT market fills, limit touch/no-touch, normal/gap stops,
target gaps, stop/target ambiguity, plan expiry/one-shot IDs, all cost combinations,
funding signs/timing, risk reject/halt/counters/cooldown/capacity, accounting invariants,
known metrics/drawdown sequences, future-version isolation, double-run/rebuilt-storage
canonical equality, and conservative end-of-run close.

## 17. Acceptance criteria

All 61 criteria in the approved PHASE 5 request require concrete test or code evidence.
PHASE 1-4 tests, Ruff lint/format, mypy and compileall must pass locally. Python 3.12
CI must pass before PHASE 5 can be externally approved. `docs/backtesting.md` and
`docs/phase-5-review.md` must identify every assumption and limitation. Until all gates
and human review pass, PHASE 4 remains the last approved phase and PHASE 5 status is
`NEEDS_WORK`.

## 18. Explicit limitations

- Historical OHLCV is the only price path; no bid/ask history or order-book queue.
- Spread/slippage, market-like entry and deterministic full limit fill are modeled.
- No random or sub-M5 path; ambiguous OHLC resolves to worst case.
- No true partial-fill, latency, market-impact, outage or venue liquidation model.
- Instrument semantics and rates are injected fixtures/assumptions, not claimed current
  OKX facts; historical funding mode fails on missing required observations.
- Forced end-of-run close uses final M5 mark, modeled spread/slippage and exit fee.
- A technically valid backtest is not evidence that the strategy has an edge.
