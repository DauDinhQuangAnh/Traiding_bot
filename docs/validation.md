# PHASE 6 Validation Contract

## 1. Purpose

PHASE 6 evaluates whether the frozen strategy produces stable evidence outside its
development interval. It does not optimize the strategy or certify profitability.
Implementation quality and observed strategy robustness are separate outcomes.

## 2. Why chronological validation

Market observations are ordered and dependent. Official validation never shuffles
candles: past TRAIN precedes VALIDATION, which precedes final TEST. A changed future
observation cannot enter an earlier repository query or partition projection.

## 3. Train / validation / test

`TemporalSplitSpec` contains three non-overlapping, UTC, half-open `EvaluationRange`
values. TRAIN is the strategy-development period, VALIDATION is pre-lock evaluation, and
TEST is the final out-of-sample period. TRAIN is terminology for rules development, not
machine learning. Dates are explicit inputs and part of `split_id`.

## 4. Warmup handling

Every `PartitionWindow` distinguishes `data_start` from `evaluation.start/end`. The
minimum duration is derived deterministically from existing EMA/RSI/ATR/ADX/Bollinger,
percentile, volume and structure requirements via `required_bars()`, converted using the
M5/M15/H1 intervals. A smaller requested duration fails closed. Replay over warmup may
build market state, but only decisions at or after `evaluation.start` reach the backtest
engine. Warmup therefore cannot create economic trades, portfolio/risk state or official
performance for the partition.

## 5. State continuity

Baseline policy is `CONTINUOUS_CHRONOLOGICAL`. TRAIN, VALIDATION and TEST reconstruct
state from the same past-only `data_start`. Indicators, regime, ranges and breakout state
may use preceding observations, while official metrics begin only at each evaluation
start. No future or independently evaluated state object is transferred backward.

## 6. Purge / embargo

Purge and embargo are explicit non-negative durations. Their sum must fit between TRAIN
and VALIDATION and between VALIDATION and TEST. They keep development/evaluation evidence
separated while chronological gap observations may still build continuous market state.
The durations, boundaries and policy are versioned in the split identity.

## 7. Final test policy

TEST execution requires `test_locked=True`. A new frozen protocol begins with
`test_evaluation_count=0` and each execution requires an explicit deterministic execution
identifier. Execution completion creates `test_consumption_event_id`; it does not invent
an authoritative counter in memory. SQLite transactionally assigns the next durable
`consumption_index` when evidence is first persisted and records that same value as the
stored protocol's audit count. Code, strategy, config, split, historical M5/M15/H1/snapshot
versions, execution, cost, funding and instrument identities are frozen in
`ValidationProtocol`. The protocol also freezes one immutable `ValidationPolicy`, which
owns the interpretation rules described below. A semantic mismatch fails before any
backtest. New experiment or interpretation semantics require a new protocol identity;
stored evidence is never silently replaced.

## 8. Validation identity

`validation_run_id` is content-derived from protocol, split, historical M5/M15/H1 and
snapshot versions, walk-forward declarations, sensitivity dimensions, stress assumptions,
bootstrap identity and benchmarks. Protocol identity covers code, strategy, config,
historical versions, execution, costs, funding, metadata, split, lock and state policy.
Machine paths, wall clock and random UUIDs are excluded.

Identity meanings are deliberately separate:

- `validation_policy_id` is SHA-based canonical identity over `policy_version`,
  `minimum_sample_size`, all `RobustnessRules`, and all
  `RobustnessEvidenceRequirements` flags. The immutable policy validates that its ID
  matches its content.
- `protocol_id` identifies frozen experiment semantics plus the complete validation
  policy; the immutable protocol validates that its ID matches its content and excludes
  the TEST viewing count.
- `validation_run_id` identifies one completed evidence payload and includes its
  deterministic TEST consumption event, but excludes the store-assigned sequence number.
- `partition_result_id` binds protocol, partition/window and backtest run.
- `sensitivity_id` binds protocol, perturbation and complete typed evaluation provenance.
- `stress_id` binds protocol, stress specification/cost version and execution-path
  fingerprint.
- `bootstrap_id` binds protocol, inputs, seed, iterations and minimum sample.
- `benchmark_id` binds protocol, benchmark policy, official range, marks and costs.
- `test_consumption_event_id` identifies a completed TEST execution; retrying that event
  is idempotent.
- `(protocol_id, consumption_index)` is the store-authoritative monotonic viewing sequence.
- `ExecutionPathFingerprint.fingerprint` identifies ordered trade executions independently
  of cost-sensitive PnL and prices.

## 9. Walk-forward

Anchored windows keep one TRAIN start and expand chronological history before successive
OOS windows. Rolling windows use explicit training duration. OOS overlap is rejected by
default. There is no fitting inside a window. Aggregation reports positive/negative window
counts and ratio, median window PF/expectancy, trade-weighted expectancy, worst drawdown,
and overall PF from aggregated gross profit/loss—not the mean of PF values.

## 10. Sensitivity

`SensitivitySpec` accepts one existing declared scalar parameter, its Decimal baseline
and a small unique multiplier sequence. Multiplier `1` must occur exactly once and every
perturbation must stay within the explicit local deviation bound (±5% by default). Results
record a non-TEST evaluation partition and expected half-open range, preserve input order
and record every perturbation. The evaluator must return typed provenance containing the
partition, range, backtest run, historical versions and frozen strategy/config/execution/
cost/funding/instrument identities. Any mismatch fails closed. That provenance participates
in `sensitivity_id` and is stored with the result. No field, function or pipeline selects,
ranks, recommends or applies a winner.

## 11. Cost stress

`CostStressSpec` versions explicit multipliers of at least `1` for spread, slippage, fees
and optionally funding. Typed evaluation verifies frozen strategy/config/execution/
instrument semantics and does not widen price-deviation tolerance. Funding identity may
change only when funding is the declared stress dimension. When the executed trade path is
unchanged, higher total costs cannot improve net PnL. If friction changes entry acceptance,
non-monotonic trade-level metrics are reported rather than disguised.

Multiplier `1` is exactly the frozen baseline: its evaluation cost identity must equal
`protocol.cost_model_version` or evaluation fails closed. For every multiplier greater
than `1`, the required stressed-cost identity is deterministically derived from the frozen
baseline cost version, the complete `CostStressSpec`, and the multiplier. An arbitrary
different version string is not accepted. `stress_id` binds that derived version together
with protocol, specification, multiplier, and execution path.

Unchanged path means an identical SHA-based fingerprint over the supplied execution order:
trade/candidate/approved-plan identity, stable entry execution identity, direction, entry
time, exit time and exit reason. Entry/exit prices, fees, cost estimates and PnL are excluded
because those may legitimately change under cost stress. Equal trade count is not path
equality. Reordered trades are a different path. The cost-monotonicity property is rejected
as not applicable when fingerprints differ.

## 12. Benchmarks

The flat benchmark returns zero under the stated no-cash-yield assumption. Buy-and-hold
enters at the first official OOS mark, exits at the final official mark and charges
explicit modeled entry/exit costs. Both retain the identical OOS range. Return, drawdown,
exposure and costs are reported together; net PnL alone does not determine superiority.

## 13. Statistical uncertainty

The optional trade bootstrap is deterministic: seed, iterations, minimum sample and
inputs are included in identity. SHA-256-derived draw indices avoid unseeded or runtime
global randomness. It reports descriptive expectancy-R and net-PnL percentiles. Too few
trades return unavailable values. IID resampling ignores dependence and clustering and is
not a price-path simulation or forecast. Profit-factor intervals are reported only for
resamples with a defined loss denominator.

## 14. Sample size

`minimum_sample_size` comes only from the protocol's immutable `ValidationPolicy` during
official orchestration. Every partition metric records that frozen threshold; every
side/regime/setup group carries `trade_count` and a matching explicit
`insufficient_sample` flag. `ValidationMetrics` rejects inconsistent flags, and assembled
runs, sensitivity, cost stress, and robustness classification reject evidence carrying a
different sample threshold. Low-level projection accepts an explicit threshold only to
perform the calculation; the official pipeline supplies it from the policy and exposes no
competing runtime argument. Zero trades, one trade, no losses, no wins and undefined PF
remain valid typed cases; undefined is `null`, never a fabricated zero.

## 15. Robustness interpretation

The allowed statuses are `INSUFFICIENT_DATA`, `FRAGILE`, `MIXED` and
`ROBUST_CANDIDATE`. Rules declare minimum OOS trades, minimum positive-window ratio,
minimum expectancy and maximum sensitivity dispersion. Component results remain visible.
Rules and `RobustnessEvidenceRequirements` are owned by the immutable validation policy
and participate in both policy and protocol identity. The classifier accepts the protocol,
not an independent rules argument, and reads both objects from `protocol.validation_policy`.
Requirements demand walk-forward, sensitivity and cost-stress evidence by default.
Required sensitivity must contain baseline and non-baseline scenarios; required stress
must contain baseline and stressed scenarios; required evidence must not be
sample-insufficient. Missing or incomplete required evidence returns `MIXED` and can never
produce `ROBUST_CANDIDATE`.
`ROBUST_CANDIDATE` is historical evidence only and never means profitable or authorized
for Demo/Live trading.

## 16. Persistence

`SQLiteValidationRepository` stores canonical protocols, validation runs, partitions,
walk-forward windows, sensitivity, stress and benchmarks in append-only tables. Same ID
plus identical bytes is idempotent. Same ID plus different bytes raises
`PersistenceError`. Historical version sets are retained on the protocol, run, and every
partition result. Canonical protocol JSON contains the complete frozen validation policy;
the same protocol ID with different policy bytes is a conflict, never an overwrite.
`validation_test_consumptions` is an append-only ledger keyed by protocol and monotonic
index, with unique deterministic event/run identities. `BEGIN IMMEDIATE`
serializes read-next-index plus evidence/ledger insertion atomically. A retry with identical
event ID/content returns its original record without incrementing; conflicting content
fails. A new event receives `MAX(index)+1` even when its caller reused the original
count-zero protocol. Unsupported older schemas fail explicitly during initialization;
tables are never silently dropped and prior evidence is never deleted.

## 17. Dashboard

The local foundation is a dependency-free read service and GET/HEAD-only API contract.
It lists runs and exposes detail, summary, walk-forward, sensitivity and stress projections.
Equity/trade routes explicitly report that row artifacts remain in PHASE 5 rather than
duplicating business data. Unknown IDs return 404, invalid pagination returns 400 and all
write methods return 405. There are no controls, credentials, arbitrary SQL/files, shell
execution, market polling or exchange connections.

## 18. Limitations

All PHASE 5 limitations remain: M5 OHLC cannot reveal intrabar order, spread/slippage/
funding are modeled, no queue/latency/impact or liquidation model exists, and forced-close
semantics are synthetic. One instrument and small samples do not establish generality.
Bootstrap IID assumptions may be false. No production validation dataset is committed,
so strategy robustness remains `NOT_EVALUATED`.

## 19. Anti-overfitting rules

Final TEST is not a tuning loop. No automatic optimization, best-parameter selection,
genetic/Bayesian search, ML, auto-retraining or performance-to-config feedback exists.
Sensitivity is local evidence, not selection. Negative TEST or bad windows remain stored
and reported. A changed strategy/config creates a new protocol instead of rewriting a bad
run.

## 20. Acceptance criteria

Acceptance requires valid chronological splits, derived warmup, explicit purge/embargo,
locked TEST metadata, semantic consistency, leakage and canonical replay tests, anchored
walk-forward, correct aggregation, sensitivity without selection, cost stress, sample-aware
groups, deterministic bootstrap, flat/buy-hold benchmarks, immutable SQLite evidence and
read-only dashboard behavior. Existing PHASE 1–5 tests and all Python quality gates must
pass on the exact final commit. PHASE 6 stays unapproved until explicit human review.
