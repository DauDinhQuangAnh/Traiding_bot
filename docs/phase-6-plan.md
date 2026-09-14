# PHASE 6 Plan — Out-of-Sample Validation and Local Dashboard

## 1. Objective

PHASE 6 builds deterministic evidence about whether the frozen PHASE 5 strategy behaves
consistently outside development data. It introduces chronological partitions,
walk-forward evaluation, sensitivity and cost-stress evidence, deterministic uncertainty,
benchmarks, append-only validation persistence, and a local read-only dashboard boundary.
Implementation correctness and strategy robustness are reported separately.

## 2. Non-goals

PHASE 6 does not optimize or modify strategy rules, select a best parameter, connect to
OKX or another network service, submit orders, enable Demo/Live trading, add AI/ML,
claim profitability, or treat historical evidence as a future guarantee. PHASE 5 business
semantics remain frozen. A PHASE 5 defect discovered during implementation stops PHASE 6
and requires a dedicated remediation.

## 3. Terminology

- `TRAIN`: chronological design/inspection interval; it does not imply machine learning.
- `VALIDATION`: chronological pre-lock evaluation interval.
- `TEST`: final, explicitly locked out-of-sample interval.
- `data_start`: earliest history allowed to build indicators and deterministic prior state.
- `evaluation_start` / `evaluation_end`: half-open interval `[start, end)` whose trades,
  PnL, equity and metrics belong to a partition.
- `OOS`: evaluation interval outside a walk-forward training interval.
- implementation status and strategy robustness status are independent typed outcomes.

## 4. Dataset partitioning

`TemporalSplitSpec` is immutable and UTC-only. It contains train, validation and test
half-open intervals, purge and embargo durations, timezone and a content-derived split
identity. The order is strictly TRAIN then VALIDATION then TEST; overlap, reversal,
random shuffling and implicit boundaries are invalid. Dates are run inputs, never global
constants. Each result retains the exact M5/M15/H1 and snapshot-composite versions.

## 5. Temporal leakage prevention

Official orchestration queries only the declared historical versions and time bounds.
Changing a candle can affect only an evaluation interval at or after that candle;
appending data at or after `test_end` cannot change current protocol artifacts. Warmup
history is excluded from performance projection. Inputs are always sorted and validated;
there is no randomized split path.

## 6. Purge and embargo rules

The deterministic minimum warmup is derived from the existing
`derive_minimum_warmup(indicators, levels)` contract per timeframe and converted to
duration using M5/M15/H1 intervals. A requested warmup below that bound fails closed.
`purge_duration` separates information used for development from the next evaluation;
`embargo_duration` excludes the declared post-boundary interval from reuse. Both are
non-negative, explicit, versioned and must fit without overlapping evaluation windows.
They are evidence boundaries, not invented trading candles.

## 7. Train / validation / test semantics

All three partitions use identical strategy, app-config, execution, cost, funding and
instrument semantic identities. Only time bounds differ. A partition stores both its
warmup/data interval and official evaluation interval. Signals or trades before
`evaluation_start` never contribute to its trades, PnL or metrics. Undefined metrics
remain `null`, not fabricated zero.

## 8. State continuity and warmup

Baseline policy is `CONTINUOUS_CHRONOLOGICAL`: each partition reconstructs indicator,
regime, range and breakout state from chronological history beginning at its validated
`data_start`; it never imports serialized state from a future or independently evaluated
partition. Warmup may influence the first official decision but cannot create a reported
trade. Open economic positions are not silently transferred across independently scored
partition reports; a boundary policy must be explicit in each run. Metrics start only at
`evaluation_start`.

## 9. Final test policy

`ValidationProtocol` freezes code, strategy, config, split, execution, cost, funding,
instrument, historical M5/M15/H1/snapshot versions, sensitivity/stress/walk-forward
specifications and whether TEST is locked. A protocol starts with an unconsumed count;
successfully consuming TEST records `test_consumed` and increments an auditable
evaluation count.
Changing any semantic input creates a different protocol/run identity; existing TEST
evidence is append-only and never overwritten. The software makes contamination visible,
but cannot prevent a developer from creating a deliberately new protocol.

## 10. Walk-forward design

The required baseline is anchored walk-forward: a fixed training start expands to each
successive OOS boundary. Optional rolling windows use explicit training duration, OOS
duration and step. Windows are UTC, deterministic, ordered, non-overlapping in OOS when
the policy requires it, and contain no fitting or parameter selection. Overall PF is
computed from aggregate profits/losses; median window PF is labeled separately. Overall
expectancy is trade-weighted; median window expectancy is also separate.

## 11. Allowed parameter sensitivity

Sensitivity uses a small, declared list of existing scalar config paths and explicit
Decimal multipliers/values. The baseline appears exactly once, the final TEST partition is
forbidden, and the default local deviation bound is ±5%. Invalid perturbations fail
configuration validation; bounds are not silently clamped. Outputs retain parameter,
baseline and perturbed values plus OOS metrics. Results preserve declaration order and
never rank, recommend, apply or persist a winner. Final TEST is not used for sensitivity.

## 12. Forbidden optimization

Grid search for maximum PnL, genetic/Bayesian optimization, reinforcement learning,
auto-retraining, automated winner selection and repeated test-set tuning are absent.
Negative, mixed and fragile results are retained as evidence and never trigger a strategy
mutation.

## 13. Cost stress testing

Declared non-negative Decimal multipliers (baseline exactly `1`) stress spread,
slippage and fees through existing PHASE 5 configuration and execution semantics.
Funding is a separate explicit dimension. Price-deviation tolerance does not expand.
The typed result boundary rejects changes to frozen non-cost semantics. Higher friction
may reject trades, so every metric need not be monotonic; for an identical executed path,
additional non-negative costs must not manufacture accounting gains. Stress results retain
unchanged strategy/config identity plus explicit stressed-cost identity and never replace
the baseline.

## 14. Robustness metrics and classification

Results expose trade count, net PnL, PF, expectancy R, maximum drawdown, win rate,
exposure, costs and side/regime/setup breakdowns by reusing PHASE 5 metrics. Every group
shows sample size. A configured minimum produces `INSUFFICIENT_SAMPLE`. Structured
classification is one of `INSUFFICIENT_DATA`, `FRAGILE`, `MIXED`, or
`ROBUST_CANDIDATE`; thresholds are explicit protocol inputs and the component evidence
remains visible. No magic profitability score is introduced.

## 15. Statistical uncertainty

Optional trade-level bootstrap uses an explicit integer seed and iteration count, both in
identity. It reports percentile intervals for expectancy R and net PnL, and PF only when
defined. Insufficient samples produce unavailable intervals. Any trade-sequence
resampling is labeled descriptive IID sequence analysis, not price simulation or future
prediction; dependence and regime clustering remain documented limitations.

## 16. Benchmarks

The same OOS range includes deterministic flat/no-trade and buy-and-hold comparisons.
Buy-and-hold uses an explicit first-entry/final-exit policy and existing modeled
transaction costs without future knowledge. Entry and final-exit costs are included in the
benchmark equity path and drawdown. Reports compare return, drawdown, descriptive
return/drawdown ratio, exposure and costs; they do not rank solely by net PnL.

## 17. Dashboard architecture

The dashboard is a local read-only adapter over application query services and persisted
canonical validation artifacts. Initial scope is dependency-light HTTP/JSON endpoints for
health, run listing, run detail, summary, equity, trades, walk-forward, sensitivity and
stress. Only GET/HEAD are allowed; mutation routes, arbitrary SQL/filesystem access,
shell execution, credentials, market polling and trading controls do not exist. Decimal
values use canonical string serialization. UI/presentation never owns strategy logic.

## 18. Persistence and version identity

`validation_run_id` hashes code/strategy/config versions, historical version set, split,
execution/cost/funding/instrument identities, protocol, walk-forward, stress, sensitivity
and uncertainty specifications. Host paths, wall time and random UUIDs are excluded.
SQLite stores protocols, runs and typed child artifacts as canonical JSON. Same ID and
same bytes is idempotent; same ID and different bytes raises `PersistenceError`; rows are
never updated or deleted by validation/dashboard code.

## 19. Testing strategy

Tests cover split chronology and invalid bounds, derived warmup, purge/embargo, exclusion
of warmup performance, future/test leakage, identity changes, deterministic replay,
anchored/rolling windows, correct weighted aggregation, one baseline sensitivity result,
absence of winner selection, versioned stress, cost accounting, sample-size warnings,
all metric breakdowns and edge cases, deterministic seeded bootstrap, benchmarks,
SQLite idempotency/conflicts, and read-only dashboard behavior. Existing PHASE 1–5 tests
remain unchanged and green.

## 20. Limitations

Validation inherits PHASE 5 OHLC, spread, slippage, funding, latency, order-book and
no-liquidation limitations. Purge/warmup reduces but cannot prove absence of every research
bias. IID bootstrap does not model clustered markets. Small samples and one instrument
cannot establish a general edge. A technically correct system may report a fragile or
negative strategy, and `ROBUST_CANDIDATE` never authorizes Demo/Live trading.

## 21. Acceptance criteria

PHASE 6 is an approval candidate only when chronological TRAIN/VALIDATION/TEST and final
TEST lock are explicit; warmup is derived and excluded; leakage and deterministic
identity tests pass; fixed semantics hold across partitions; anchored walk-forward,
sensitivity without selection, cost stress, grouped/sample-aware robustness, benchmarks,
append-only persistence and read-only dashboard foundations exist; optional uncertainty
is seeded; canonical reruns match; documentation and review are complete; all Python
quality gates and exact-commit Python 3.12 CI pass; and implementation status is reported
separately from strategy robustness. External human review is always required before
`APPROVED`.
