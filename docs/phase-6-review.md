# PHASE 6 Review — Out-of-Sample Validation Foundation

## IMPLEMENTATION STATUS

`NEEDS_WORK`

The implementation is an `APPROVED_CANDIDATE` based on the completed human-style code
audit and local quality gates. Formal closure remains `NEEDS_WORK` until Python 3.12 CI
passes on the exact final documentation commit and an external human approves PHASE 6.
This document does not self-declare final approval.

The original implementation commit `ccd7249bbd1757effbf3863417167bbbcde1d86a`
passed GitHub Actions workflow `Python quality gates`, run #7, job `python-312`:

https://github.com/DauDinhQuangAnh/Traiding_bot/actions/runs/34586758996

Job evidence: https://github.com/DauDinhQuangAnh/Traiding_bot/actions/runs/34586758996/job/103222646568

The audit found correctness gaps and closed them in remediation commit
`cd38d1149780ad10146ae17b9d9c0cf0f77bfa8b`. That SHA and the later documentation
commit do not yet have their own GitHub Actions evidence and must not reuse run #7.

Local evidence after remediation: 242 tests passed. Overall branch-aware coverage is
86%. Critical PHASE 6 coverage includes validation pipeline 97%, splits 100%, identity
100%, validation metrics 95%, benchmarks 100%, walk-forward generation/aggregation 100%,
sensitivity 93%, stress 97%, uncertainty 90%, SQLite persistence 88%, dashboard API 95%,
and dashboard services 90%.

## STRATEGY ROBUSTNESS STATUS

`NOT_EVALUATED`

No approved production BTC-USDT-SWAP historical dataset exists in the documented project
data locations. No temporal split was selected, no final TEST was consumed, and no
economic result was fabricated. This status is independent of implementation quality.

## Audit findings and remediation

| Severity | Finding | Resolution |
|---|---|---|
| HIGH | Warmup evaluations could reach the backtest engine, allowing pre-partition economic activity and risk/portfolio state despite later metric filtering. | Replay now builds market state from `data_start`, while the engine receives only decisions at or after official `evaluation.start`; regression coverage proves a warmup signal cannot execute. |
| HIGH | Final TEST consumption was initialized as already consumed and was not incremented after execution. | New protocols start at count zero; successful baseline validation increments the immutable protocol count and produces an append-only run identity. |
| HIGH | Frozen protocol validation omitted code and historical-version equality. | Protocol identity now binds the complete historical version set; code/data mismatches fail before backtest execution. |
| HIGH | Cost-stress callbacks could return evidence after changing frozen non-cost semantics. | Typed stress evaluation now verifies strategy, config, execution, instrument, funding policy, and price-deviation tolerance before accepting results. |
| MEDIUM | Sensitivity did not encode its evaluation partition or enforce local perturbation bounds. | Sensitivity is explicitly non-TEST and defaults to a maximum ±5% local deviation. |
| MEDIUM | Empty side/regime/setup groups were absent. | Every declared enum group is emitted with `trade_count=0` and `insufficient_sample=True` where applicable. |
| MEDIUM | Bootstrap omitted documented profit-factor intervals. | Deterministic bootstrap now reports PF percentiles when the sampled loss denominator exists. |
| MEDIUM | Buy-and-hold drawdown did not include entry/final-exit transaction-cost equity marks. | Benchmark equity path now includes initial, entry-cost, mark-to-market, and final realized-cost states. |
| MEDIUM | Walk-forward expectancy denominator included trades from windows whose expectancy was undefined. | Weighting now uses only the trades contributing a defined expectancy numerator. |
| MEDIUM | A global child-result uniqueness constraint prevented an incremented TEST-consumption run from appending deterministic child evidence. | Child identity is unique within each validation run; canonical protocol storage normalizes the mutable audit count while every run retains its actual count. |
| LOW | The earlier review contained stale/duplicated local evidence and incorrectly marked run #7 pending. | Replaced with exact-SHA CI provenance and current local evidence. |

No unresolved blocking correctness finding remains in the audited local implementation.

## Contract audit

- TRAIN, VALIDATION, and TEST are immutable UTC half-open intervals in strict order;
  overlap, reversal, and invalid purge/embargo gaps fail closed.
- Boundary ownership is single-valued: an item at interval end belongs only to the next
  interval.
- Warmup begins at explicit `data_start`, may build indicators/regime/levels/breakout
  state, and cannot create official trades, portfolio state, or performance.
- Continuous chronological state is replayed only from past observations bounded by
  `data_start`; no future result or independently evaluated future state flows backward.
- TEST requires a locked protocol. Code, strategy, config, split, historical data,
  execution, cost, funding, and instrument identities are checked before execution.
- TEST consumption is visible and append-only through `protocol_id`, lock state, count,
  semantic versions, and distinct run identities.
- Anchored and rolling walk-forward windows are deterministic and chronological; OOS
  overlap policy is enforced and there is no fitting inside a window.
- Aggregate PF uses total gross profit divided by absolute total gross loss. Overall
  expectancy is trade-weighted only across defined window expectancy values.
- Sensitivity has exactly one baseline, stays local, excludes final TEST, preserves
  declaration order, and contains no optimizer or automatic winner selection.
- Cost stress changes only declared friction assumptions; frozen signal semantics and
  price-deviation tolerance are checked. Monotonic PnL is required only for identical
  executed paths.
- Partition and side/regime/setup evidence includes sample counts and explicit
  insufficiency; typed edge cases retain `null` when mathematically undefined.
- Bootstrap is seeded and deterministic, has minimum-sample behavior, and is descriptive
  IID trade resampling rather than market-path simulation.
- Flat and buy-and-hold benchmarks use the same official OOS range, explicit endpoint
  marks, and modeled transaction costs without best-entry/exit look-ahead.
- SQLite evidence is append-only and canonical: identical ID/content is idempotent;
  conflicting content fails. The dashboard is GET/HEAD-only and reads persisted evidence.

## Acceptance checklist

| Criterion | Status | Evidence |
|---|---|---|
| PHASE 5 closure | PASS | `191fd72`; exact PHASE 5 CI run #6 and external human approval recorded. |
| Original PHASE 6 implementation CI | PASS | `ccd7249`; GitHub Actions run #7, `python-312`, SUCCESS. |
| Audit remediation | PASS locally | `cd38d11`; focused tests and full local gates pass. |
| Chronological split and boundary ownership | PASS locally | Ordering, overlap, half-open boundary, and deterministic identity regressions. |
| Warmup and past-only state | PASS locally | State replay begins at bounded `data_start`; engine executes official decisions only. |
| Purge/embargo and leakage guards | PASS locally | Gap validation plus TEST-only/post-TEST golden regressions. |
| Final TEST lock and audit count | PASS locally | Pre-run lock/identity checks and post-success count increment. |
| Walk-forward and aggregation | PASS locally | Anchored/rolling chronology, overlap policy, aggregate PF, weighted expectancy. |
| Sensitivity without optimization | PASS locally | Exactly one baseline, ±5% bound, non-TEST partition, no winner output. |
| Cost stress isolation/accounting | PASS locally | Typed frozen-semantics guard and identical-path monotonic property. |
| Sample-size and edge cases | PASS locally | Complete group matrix, zero/one/no-win/no-loss/breakeven/undefined cases. |
| Bootstrap and benchmarks | PASS locally | Seed replay/different identity/PF intervals and cost-aware benchmark drawdown. |
| Append-only persistence | PASS locally | Idempotency, conflict rejection, and incremented consumption append. |
| Dashboard read-only boundary | PASS locally | GET/HEAD behavior, write 405, and forbidden-capability source audit. |
| Full regression suite | PASS locally | 242 tests; no prior test disabled. |
| Branch-aware coverage | PASS locally | 86% overall; critical PHASE 6 modules at least 88%. |
| Ruff, mypy, compileall | PASS locally | All project commands pass. |
| Exact final-commit Python 3.12 CI | PENDING | Final documentation commit is not pushed; run #7 belongs only to `ccd7249`. |
| External human review | PENDING | Required before `APPROVED`. |

## Limitations and interpretation

The system retains M5 OHLC intrabar ambiguity and modeled spread, slippage, fees, and
funding. It has no order-book, queue, latency, market-impact, or liquidation model.
Trade-level bootstrap is IID and does not model clustered markets. BTC-only evidence would
not establish cross-market robustness, and historical evidence cannot guarantee future
results.

A technically approved validation framework does not imply the strategy is profitable.
No result authorizes PHASE 7, AI benchmarking, OKX connectivity, Demo trading, or Live
trading.
