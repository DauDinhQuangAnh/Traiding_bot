# PHASE 3 Review — Remediation and Approval

## 1. Status

**PHASE 3: APPROVED — deterministic offline core only.**

This approval covers the offline domain, application pipeline, deterministic replay,
and local SQLite journal. PHASE 4 has not started. No exchange SDK, network client,
credential handling, order submission, Demo loop, or Live-trading path is present.

## 2. Contract gaps found and fixed

| Area | Discrepancy | Remediation |
|---|---|---|
| Range persistence | `evaluate_market()` rebuilt `RangeContext` at `NONE` on each M15 evaluation. | Prior range is now an explicit, serializable pipeline input. Compatible state advances deterministically; range/config/data identity changes reset it. Age, stale, hold, expiry, invalidation, and retest transitions are preserved. |
| Percentile | Ties used mid-rank instead of the canonical inclusive CDF. | Uses `100 * count(value <= current) / count(window)`. |
| Decimal policy | Calculations ignored `CalculationConfig`, and Bollinger used precision 34. | A scoped `decimal.localcontext()` applies configured precision and rounding without mutating global context across indicator, level, regime, strategy, and risk engines. |
| Risk identity/audit | `risk_decision_id` omitted instrument metadata version. Fee/cost version was not persisted on decisions/plans. | IDs include candidate, context, state, config, and instrument versions. Risk output records also retain instrument and fee/cost model versions. |
| Market data | Duration-only candles allowed misaligned intervals; snapshot failure was exception-only. | Enforces UTC boundaries, order, duplicates, gaps, future/closed status, identity, M5 children, H1 context, canonical `as_of`, and quote freshness. Snapshot building returns a typed failure that orchestration converts to `NO_TRADE` with a canonical reason. |
| Strategy gates | SIDEWAY eligibility could depend implicitly on score weights. | Closed-candle confirmation, directional momentum, directional volume, score, confluence, score difference, and cost-adjusted RR are explicit gates, including documented disabled-component semantics. |
| Test depth | Direct boundary/state/version tests and stateful replay evidence were incomplete. | Added focused market-data, regime, strategy, risk, breakout sequence, property, and multi-candle replay coverage. |
| Python 3.12 evidence | No hosted Python 3.12 quality gate existed. | Added a GitHub Actions Python 3.12 workflow for pytest, Ruff, mypy, and compileall. |

The two intentional PHASE 3 model clarifications remain documented:
`RangeContext.reference_close` supplies the canonical range-position formula, and
`TradeCandidate.reference_atr` permits Risk Engine stop-distance revalidation. Neither
adds a strategy rule or changes a calibrated threshold.

## 3. Determinism and replay evidence

- Calculation policy is scoped per call and never mutates the process-wide Decimal
  context.
- Prior regime and range/breakout state are explicit replay inputs; there is no hidden
  mutable trading state.
- Level, range, candidate, and risk IDs include their required logical/version inputs.
- A multi-candle sequence is replayed twice from the same initial state. Canonical
  bytes for every decision, regime assessment, range transition, signal assessment,
  and candidate ID are equal.
- Future candles are rejected or excluded by point-in-time selection, so adding future
  source data cannot change an earlier `as_of` result.

## 4. Tests added

- Breakout progression: normal range → detected → confirmation → wait retest → valid
  retest → `BREAKOUT_RETEST` eligibility, plus failed hold, expired/invalid retest,
  stale range, and identity reset.
- Percentile tie formula and minimum, maximum, all-equal, single-value, and repeated
  boundaries.
- Calculation precision/rounding configuration behavior.
- Candle/snapshot boundary alignment, gaps, duplicates, ordering, future data, closed
  status, M5/M15/H1 consistency, canonical staleness, quote freshness, and identity.
- Direct SIDEWAY, trend pullback, conflict, score, and RR gate boundaries.
- Direct regime candidate, conflict, persistence, high-volatility precedence, version,
  invalid ATR, and exact-threshold cases.
- Risk geometry and every mandatory safety/capacity/cost/version boundary, including
  instrument-version ID regression.
- Property checks: approvals never exceed risk budget; any active hard-gate failure
  cannot approve.

## 5. Verification evidence

Commands are run from the repository root. Local verification uses the interpreter
supplied by the user at `D:\hoctap\python\python.exe`:

| Gate | Exact command | Result |
|---|---|---|
| Tests | `D:\hoctap\python\python.exe -m pytest -q` | PASS — 71 passed |
| Coverage | `D:\hoctap\python\python.exe -m pytest --cov=trading_bot --cov-report=term -q` | PASS — 71 passed, 83% total |
| Ruff lint | `D:\hoctap\python\Scripts\ruff.exe check src tests` | PASS |
| Ruff format | `D:\hoctap\python\Scripts\ruff.exe format --check src tests` | PASS |
| Types | `D:\hoctap\python\python.exe -m mypy src` | PASS — no issues in 35 source files |
| Compile | `D:\hoctap\python\python.exe -m compileall -q src` | PASS |
| Offline boundaries | included in pytest | PASS — forbidden network imports and dependency direction checked |

The table records the final local quality-gate run for this remediation commit.

## 6. Python 3.12 CI status

`.github/workflows/ci.yml` is configured to install the project and run all required
quality gates on Python 3.12. The supplied local interpreter reports Python 3.11.9, so
native 3.12 execution remains pending the first GitHub Actions run after a human-approved
push. The project requirement remains Python `>=3.12`; it was not weakened.

## 7. Safety and remaining risks

- `execution.enabled=false`, `dry_run=true`, and `enable_live_trading=false` remain
  enforced by typed configuration. Live configuration is rejected.
- No exchange/network dependencies or execution path were introduced.
- Example thresholds remain `BACKTEST_REQUIRED`; passing deterministic tests is not
  evidence of trading profitability.
- Historical fee/funding schedules, market impact, and exchange-specific reconciliation
  belong to later explicitly approved phases.
- Hosted Python 3.12 CI evidence is pending a push; local tests ran on Python 3.11.9.

Human review is required before any PHASE 4 work.
