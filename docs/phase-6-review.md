# PHASE 6 Review — Out-of-Sample Validation Foundation

## IMPLEMENTATION STATUS

`APPROVED`

External human review approved PHASE 6 at final commit
`b5319eb304eaa5537843943652384b043765e80f`. GitHub Actions workflow `Python quality
gates`, run #11, job `python-312`, completed SUCCESS for that exact SHA. This records an
external decision; it is not a self-declared approval.

Run evidence: https://github.com/DauDinhQuangAnh/Traiding_bot/actions/runs/34827076107

Job evidence: https://github.com/DauDinhQuangAnh/Traiding_bot/actions/runs/34827076107/job/103921582603

Pre-policy-closure baseline commit:
`d96ac3f538f1359e147c050d9443fa2fee52984b` (`docs: close phase 6 external review
findings`). GitHub Actions workflow `Python quality gates`, run #10, job `python-312`,
completed SUCCESS for that exact SHA. The policy-identity closure documented below is
included in the approved final commit.

Run evidence: https://github.com/DauDinhQuangAnh/Traiding_bot/actions/runs/34808253865

Job evidence: https://github.com/DauDinhQuangAnh/Traiding_bot/actions/runs/34808253865/job/103864292466

The reviewed evidence-integrity implementation commit is
`211c97b28c2b1e6095a2f8a3b495fe6f4d4b2214` (`fix: finalize phase 6 evidence
integrity`). GitHub Actions workflow `Python quality gates`, run #9, job `python-312`,
completed SUCCESS for that exact SHA.

Run evidence: https://github.com/DauDinhQuangAnh/Traiding_bot/actions/runs/34808005005

Job evidence: https://github.com/DauDinhQuangAnh/Traiding_bot/actions/runs/34808005005/job/103863571706

The original implementation commit `ccd7249bbd1757effbf3863417167bbbcde1d86a`
passed GitHub Actions workflow `Python quality gates`, run #7, job `python-312`:

https://github.com/DauDinhQuangAnh/Traiding_bot/actions/runs/34586758996

Job evidence: https://github.com/DauDinhQuangAnh/Traiding_bot/actions/runs/34586758996/job/103222646568

The first audit found correctness gaps and closed them in remediation commit
`cd38d1149780ad10146ae17b9d9c0cf0f77bfa8b`. Final evidence-integrity remediation after
external review is `211c97b28c2b1e6095a2f8a3b495fe6f4d4b2214`.

Local evidence after policy-identity remediation: 291 tests passed. Overall branch-aware
coverage is 86%. Critical coverage is validation models 84%, identity 100%, validation
pipeline 97%, robustness 100%, stress 97%, sensitivity 94%, and SQLite persistence 98%.

## STRATEGY ROBUSTNESS STATUS

`NOT_EVALUATED`

No approved production BTC-USDT-SWAP historical dataset exists in the documented project
data locations. No temporal split was selected, no final TEST was consumed, and no
economic result was fabricated. This status is independent of implementation quality.

## Final policy-identity external review

The final policy-identity review identified three interpretation-semantic gaps. They were
recorded as `OPEN` before source changes and are now locally resolved after focused
regressions and all project quality gates passed:

| Finding | Status | Required invariant |
|---|---|---|
| A. Robustness rules are not frozen | RESOLVED LOCALLY | Every classification threshold is owned by an immutable validation policy whose identity participates in `protocol_id`; the classifier has no free rules input. |
| B. Minimum sample policy is not frozen | RESOLVED LOCALLY | One protocol-owned `minimum_sample_size` controls baseline partition/group evidence, is retained on all validation metrics, and mismatched evidence fails closed. |
| C. Cost-stress 1x baseline is not bound to the frozen cost model | RESOLVED LOCALLY | Multiplier `1` must use exactly `protocol.cost_model_version`; stressed versions are deterministically derived from baseline cost assumptions and the complete stress specification. |

## Remaining external-review findings

The final evidence-integrity review identified four mandatory findings. Their typed
contracts and regression tests are now locally verified:

| Finding | Status | Required invariant |
|---|---|---|
| A. Robustness evidence completeness | RESOLVED LOCALLY | Frozen requirements demand complete, sample-sufficient walk-forward, sensitivity, and cost-stress evidence before `ROBUST_CANDIDATE`. |
| B. Execution-path identity | RESOLVED LOCALLY | Cost monotonicity applies only when ordered trade execution fingerprints are identical, never from trade count alone. |
| C. Durable TEST consumption | RESOLVED LOCALLY | SQLite owns an atomic, append-only, monotonic consumption sequence with idempotent event retries. |
| D. Sensitivity provenance | RESOLVED LOCALLY | Typed evaluator provenance proves partition/range/run/data and frozen semantic identities; TEST cannot masquerade as VALIDATION. |

## Audit findings and remediation

| Severity | Finding | Resolution |
|---|---|---|
| HIGH | Warmup evaluations could reach the backtest engine, allowing pre-partition economic activity and risk/portfolio state despite later metric filtering. | Replay now builds market state from `data_start`, while the engine receives only decisions at or after official `evaluation.start`; regression coverage proves a warmup signal cannot execute. |
| HIGH | Final TEST consumption was initialized as already consumed and was not durably sequenced. | New protocols start at count zero; execution creates a deterministic event and SQLite atomically assigns the monotonic index without trusting caller count. |
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
  event ID, store-assigned index, semantic versions, and distinct run identities. Retry of
  the same event is idempotent; new events receive increasing indices transactionally.
- Anchored and rolling walk-forward windows are deterministic and chronological; OOS
  overlap policy is enforced and there is no fitting inside a window.
- Aggregate PF uses total gross profit divided by absolute total gross loss. Overall
  expectancy is trade-weighted only across defined window expectancy values.
- Sensitivity has exactly one baseline, stays local, excludes final TEST, preserves
  declaration order, carries partition/range/backtest/data/semantic provenance, and
  contains no optimizer or automatic winner selection.
- Cost stress changes only declared friction assumptions; frozen signal semantics and
  price-deviation tolerance are checked. Ordered execution fingerprints—not trade count—
  determine whether monotonic PnL is applicable.
- Frozen robustness requirements make missing or sample-insufficient walk-forward,
  sensitivity, or cost-stress evidence ineligible for `ROBUST_CANDIDATE`.
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
| Pre-remediation review CI | PASS | `d91991b`; GitHub Actions run #8, `python-312`, SUCCESS. |
| Audit remediation | PASS locally | `cd38d11`; focused tests and full local gates pass. |
| External-review evidence remediation | PASS locally | Completeness, path, durable consumption, and provenance regressions pass. |
| Chronological split and boundary ownership | PASS locally | Ordering, overlap, half-open boundary, and deterministic identity regressions. |
| Warmup and past-only state | PASS locally | State replay begins at bounded `data_start`; engine executes official decisions only. |
| Purge/embargo and leakage guards | PASS locally | Gap validation plus TEST-only/post-TEST golden regressions. |
| Final TEST lock and durable consumption | PASS locally | Pre-run lock/identity checks plus transactional ledger indices 1/2/3 and idempotent retry. |
| Walk-forward and aggregation | PASS locally | Anchored/rolling chronology, overlap policy, aggregate PF, weighted expectancy. |
| Sensitivity without optimization | PASS locally | Exactly one baseline, local bound, typed provenance, non-TEST partition, no winner output. |
| Cost stress isolation/accounting | PASS locally | Frozen-semantics guard, ordered path fingerprint and path-qualified monotonic property. |
| Robustness evidence completeness | PASS locally | Missing required walk-forward/sensitivity/stress evidence returns `MIXED`. |
| Sample-size and edge cases | PASS locally | Complete group matrix, zero/one/no-win/no-loss/breakeven/undefined cases. |
| Bootstrap and benchmarks | PASS locally | Seed replay/different identity/PF intervals and cost-aware benchmark drawdown. |
| Append-only persistence | PASS locally | Authoritative monotonic ledger, retry idempotency, conflict rejection and explicit legacy-schema failure. |
| Dashboard read-only boundary | PASS locally | GET/HEAD behavior, write 405, and forbidden-capability source audit. |
| Validation policy identity closure | PASS locally | Immutable typed policy freezes sample size, all robustness rules, and evidence requirements; individual identity and classifier-source regressions pass. |
| Cost-stress baseline identity closure | PASS locally | Frozen 1x baseline, deterministic >1x identity, and arbitrary-version rejection regressions pass. |
| Full regression suite | PASS locally | 291 tests; no prior test disabled. |
| Branch-aware coverage | PASS locally | 86% overall; models 84%, identity 100%, pipeline 97%, robustness 100%, stress 97%, sensitivity 94%, SQLite 98%. |
| Ruff, mypy, compileall | PASS locally | All project commands pass. |
| Exact implementation-remediation Python 3.12 CI | PASS | `211c97b`; run #9, job `python-312`, SUCCESS. |
| Exact final evidence-commit Python 3.12 CI | PASS | `d96ac3f`; run #10, job `python-312`, SUCCESS. |
| Exact policy-identity remediation Python 3.12 CI | PASS | `b5319eb`; run #11, job `python-312`, SUCCESS. |
| External human review | APPROVED | Explicit approval received for `b5319eb` after successful run #11. |

## Limitations and interpretation

The system retains M5 OHLC intrabar ambiguity and modeled spread, slippage, fees, and
funding. It has no order-book, queue, latency, market-impact, or liquidation model.
Trade-level bootstrap is IID and does not model clustered markets. BTC-only evidence would
not establish cross-market robustness, and historical evidence cannot guarantee future
results.

A technically approved validation framework does not imply the strategy is profitable.
The external review authorizes PHASE 7 implementation only. It does not authorize OKX
connectivity, Demo trading, Live trading, or treating AI output as trading authority.
