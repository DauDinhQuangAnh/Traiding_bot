# PHASE 5 Review — Deterministic Backtest

## Review status

`NEEDS_WORK`

The implementation and local gates are complete, but this document does not
auto-approve PHASE 5. Python 3.12 GitHub Actions has not yet run for the final PHASE 5
commit, and explicit human review is still required. PHASE 4 remains the last approved
phase.

## Evidence baseline

- Approved PHASE 4 inputs: baseline `635303d`, identity remediation `68bedeb`.
- PHASE 5 plan/reconciliation commit: `0847af3`.
- PHASE 5 implementation baseline: `5cd8a52`.
- Local interpreter: Python 3.11.9 at `D:\hoctap\python\python.exe`.
- Local gate result before final commit: 155 tests passed with 85% total branch-aware
  coverage. Critical PHASE 5 modules: engine 81%, execution 96%, portfolio 87%,
  metrics 100%, models 92%, reports 100%, and versions 100%.
- Critical implementation: `src/trading_bot/backtest/`,
  `src/trading_bot/application/backtest_pipeline.py`, and
  `src/trading_bot/infrastructure/sqlite_backtest.py`.
- Focused evidence: `tests/backtest/` and
  `tests/integration/test_backtest_pipeline.py`.

## Acceptance criteria

| # | Criterion | Status | Evidence |
|---:|---|---|---|
| 1 | Event-driven backtest exists | PASS | `BacktestEngine.run` advances once per ordered M5 event and journals each transition. |
| 2 | M5 is execution clock | PASS | Engine rejects non-M5 clock input; pipeline integration test asserts M5 equity timestamps. |
| 3 | M15 remains strategy trigger | PASS | Historical pipeline builds evaluations only from closed M15 trigger candles; engine validates 15-minute boundaries. |
| 4 | No fill before decision timestamp | PASS | `test_entry_never_fills_before_decision_and_limit_needs_future_touch`. |
| 5 | Same-bar look-ahead regression | PASS | `test_signal_bar_high_cannot_create_historical_instant_win`. |
| 6 | Approved PHASE 3 strategy reused unchanged | PASS | PHASE 5 calls `replay_historical_sequence`; no strategy/regime/indicator business file is modified. |
| 7 | Existing Risk Engine used for every candidate | PASS | `_evaluate` calls unchanged `evaluate_risk`; orchestration tests cover APPROVE, REJECT, and HALT consequences. |
| 8 | ApprovedTradePlan required before entry | PASS | `create_entry_order` accepts and validates the plan; only Risk APPROVE invokes it. |
| 9 | Risk REJECT prevents entry | PASS | Spread, margin, RR, cooldown, daily-trade, and max-position integration cases assert no order/fill. |
| 10 | Risk HALT respected | PASS | Daily-loss, drawdown, and consecutive-loss cases end with typed `HALTED`. |
| 11 | Pending approvals expire | PASS | `test_expired_approval_does_not_fill`; end-of-run pending intents are explicitly expired. |
| 12 | LONG market execution tested | PASS | Adverse bid/ask, slippage, and actual-notional fee test. |
| 13 | SHORT market execution tested | PASS | Symmetric adverse market execution test. |
| 14 | Limit semantics tested | PASS | Historical touch ignored, future untouched remains pending, future touch fills fully. |
| 15 | Gap-through-stop is adverse | PASS | LONG and SHORT gap tests; golden LONG asserts fill below the gap open and not at stop. |
| 16 | STOP + TP same bar uses WORST_CASE | PASS | Entry-bar golden plus symmetric direct execution tests always choose stop. |
| 17 | Spread explicitly modeled | PASS | Symmetric quote model, structured warning, configured Decimal rate, and positive attribution assertion. |
| 18 | Slippage explicitly modeled | PASS | Separate market/stop rates, adverse formulas, structured warning, and execution assertions. |
| 19 | Fees use executed notional | PASS | Fill invariant asserts `fee == fill.notional * taker_fee_rate`; entry-only/exit-only accounting cases exist. |
| 20 | Funding typed and auditable | PASS | DISABLED/FIXED/HISTORICAL providers, signed `FundingCashFlow`, missing-series failure, and open-LONG golden. |
| 21 | Costs not double-counted | PASS | Net reconciliation excludes attribution estimates; positive-cost versus zero-cost final-equity property. |
| 22 | Portfolio accounting deterministic | PASS | Decimal-only incremental ledger, reconciliation validators, exact accounting and canonical-repeat tests. |
| 23 | Open-position mark-to-market included | PASS | M5 side-adverse marks populate `unrealized_pnl`; every point validates `equity=cash+unrealized`. |
| 24 | Maximum drawdown uses equity curve | PASS | Golden `100,110,105,120,90,100,130` produces exact 30 / 25%. |
| 25 | Daily risk state persists | PASS | Daily loss/drawdown/trade count flow from fills through later RiskContext evaluations. |
| 26 | Cooldown/consecutive loss gates future trades | PASS | `test_loss_state_drives_cooldown_and_consecutive_loss_halt`. |
| 27 | Max open position respected | PASS | Open-position orchestration case produces `MAX_OPEN_POSITIONS` and no second order. |
| 28 | No martingale/pyramiding | PASS | One-position portfolio invariant; Risk Engine sizing remains unchanged; no scaling path exists. |
| 29 | Metadata injected/versioned | PASS | Metadata is a required run input, included in run identity, validated before execution, and used for all contract math. |
| 30 | No invented OKX semantics | PASS | Only injected linear fixture metadata is supported; liquidation is explicitly not implemented. |
| 31 | Deterministic run identity | PASS | Run ID is content-derived and identity-change tests cover strategy/data/execution/cost inputs. |
| 32 | Deterministic cost identity | PASS | Hash covers all rates and funding assumptions; changed slippage changes ID. |
| 33 | Deterministic execution identity | PASS | Hash covers clock/fill/ambiguity/gap/end policies; policy change test changes ID. |
| 34 | Per-timeframe historical versions recorded | PASS | `HistoricalVersionSet` is embedded in `BacktestRunSpec` and report. |
| 35 | Snapshot composite recorded | PASS | Run `VersionSet.data_version` must equal the M5/M15/H1 composite or construction fails. |
| 36 | Repeat complete run is canonical-identical | PASS | Repeated run asserts byte-equivalent `canonical_json` including all artifacts. |
| 37 | Storage rebuild is identical | PASS | Two newly created SQLite files contain identical canonical run bytes. |
| 38 | Future data cannot alter old run | PASS | Fixed-range appended-future backtest test plus PHASE 4 old-version SQLite isolation test. |
| 39 | Trade journal complete | PASS | Ordered events, orders, fills, funding, closed trades, equity, and metrics are persisted and reported. |
| 40 | NO_TRADE retained | PASS | NO_TRADE event and counter remain present with no simulator consequence. |
| 41 | Gross and net PnL available | PASS | Both are immutable trade and aggregate metric fields with reconciliation. |
| 42 | Fee/funding/slippage attribution | PASS | Trade and aggregate fields, individual funding rows, and reports expose the components. |
| 43 | Profit factor implemented/tested | PASS | Exact synthetic result `140 / 70 = 2`. |
| 44 | Expectancy implemented/tested | PASS | Synthetic `+100,-50,+40,-20` produces 17.5. |
| 45 | R-multiple implemented/tested | PASS | Gross/net R are stored per trade; average/median/expectancy-R are aggregated. |
| 46 | Maximum drawdown implemented/tested | PASS | Exact Decimal golden with peak/trough/recovery timestamps. |
| 47 | Win/loss streaks implemented/tested | PASS | `W,L,L,L,W,L` produces max losses 3 and current losses 1. |
| 48 | LONG/SHORT breakdown | PASS | Deterministic `side` breakdown and explicit report keys. |
| 49 | Regime breakdown | PASS | Entry-regime summaries emitted as `by_regime`. |
| 50 | Setup breakdown | PASS | Setup summaries emitted as `by_setup`. |
| 51 | End-position policy explicit | PASS | Typed force-close policy uses final M5 close plus adverse spread/slippage and fee; exit reason is `BACKTEST_END`. |
| 52 | Structured report limitations | PASS | Warnings are enums; canonical JSON includes limitations and `liquidation_model=NOT_IMPLEMENTED`. |
| 53 | No strategy optimization | PASS | No search/tuning code or performance-to-config feedback exists. |
| 54 | No AI integration | PASS | No AI dependency or runtime path added. |
| 55 | No OKX/network client | PASS | Backtest consumes local repository ports only; no exchange SDK, credential, or network code added. |
| 56 | Existing PHASE 1–4 tests pass | PASS | Full local pytest suite passes without skipped/disabled legacy tests. |
| 57 | Python 3.12 CI passes final commit | NEEDS_WORK | Final PHASE 5 commit has not yet been pushed; remote GitHub Actions evidence is unavailable. |
| 58 | Ruff passes | PASS | `ruff check src tests` and `ruff format --check src tests` pass locally. |
| 59 | Mypy passes | PASS | Strict `mypy src` passes locally. |
| 60 | `docs/backtesting.md` complete | PASS | All 26 required sections are present. |
| 61 | Review contains explicit evidence | PASS | This table maps every mandatory criterion to implementation/test evidence. |

## Golden scenarios

| Golden | Status | Evidence |
|---|---|---|
| A — clean LONG win | PASS | Report/accounting fixture enters on next M5 and closes at target with positive gross PnL. |
| B — LONG stop | PASS | Cooldown/consecutive-loss fixture enters then closes at normal stop with negative R. |
| C — gap through stop | PASS | Gap fill uses modeled execution around 90, never the 95 stop. |
| D — same bar TP + SL | PASS | Worst-case test emits STOP and no TARGET. |
| E — signal look-ahead trap | PASS | Prior signal-bar high cannot generate an instant win. |
| F — high cost destroys edge | PASS | Positive-cost final equity is not greater than zero-cost final equity. |
| G — daily loss halt | PASS | Loss reaches the configured gate; next M15 candidate receives HALT and no new order. |
| H — consecutive loss gate | PASS | Persisted loss count causes configured Risk HALT. |
| I — funding | PASS | LONG held over positive fixed funding gets one negative cash flow. |
| J — reproducibility | PASS | Complete repeat plus rebuilt SQLite artifacts are canonical byte-identical. |

## Execution and safety conclusion

The implementation is conservative, deterministic, offline, and fail-closed at its
declared boundaries. It is not liquidation-aware, order-book-aware, latency-aware, or
evidence of profitable live behavior. No strategy parameter was changed in response to
backtest output.

## Required external review

1. Commit the final PHASE 5 implementation and evidence locally.
2. Push once when explicitly requested or when the agreed batch is ready.
3. Require GitHub Actions Python 3.12 to pass that exact commit.
4. Obtain explicit human review before changing PHASE 5 to `APPROVED` or starting
   PHASE 6.
