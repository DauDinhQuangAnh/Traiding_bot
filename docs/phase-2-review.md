# PHASE 2 Review / Design Gate

## 1. Scope and result

Review này đối chiếu toàn bộ README, tài liệu PHASE 1 đã approved và tám tài liệu
PHASE 2. Lần audit đầu phát hiện các khoảng trống critical về model lifecycle, công
thức regime/strategy, typed configuration, funding semantics, idempotency và recovery.
Các specification liên quan đã được sửa tối thiểu, sau đó review lại theo cùng acceptance
criteria.

Kết quả cuối: không còn mục critical buộc PHASE 3 phải tự sáng tạo business rule.
Các giá trị gắn `BACKTEST_REQUIRED` vẫn phải được cung cấp/calibrate trước khi chạy;
missing value là startup error, không phải default ngầm.

## 2. Review table

| Review Area | Status | Evidence | Issue | Required Action |
|---|---|---|---|---|
| Domain Models | PASS | `domain-models.md` §3–6 | Đã bổ sung indicator derivatives, evidence, range provenance, execution fields và lifecycle IDs/state | Implement validators đúng contract; không thêm nullable/default ngầm |
| Enums | PASS | `domain-models.md` §2; `error-and-reason-codes.md` | Đã tách bot state/lifecycle state và TradeSide/OrderDirection | Dùng duy nhất canonical enums/alias migration đã ghi |
| Configuration | PASS | `configuration.md` §3–7 | Đã loại wildcard/semantic duplicate; thêm indicator, regime, level, retry, protection và validation chéo | Mọi `BACKTEST_REQUIRED` value phải explicit trước runtime |
| Strategy | PASS | `strategy.md` §2–8 | Qualitative terms đã được thay bằng ramp, formula, gate và tie-break deterministic | Implement pure functions và golden tests |
| Regime Detection | PASS | `regime-detection.md` §2–10 | Đã chốt score, evidence count, precedence, persistence và range/breakout rules | Inject prior assessment/range state; không đọc state ẩn |
| Position Sizing | PASS | `position-sizing.md` §3–10 | Đã chốt multiplier support, adverse rounding, recomputation và approval invariants | Chứng minh property `worst_case_loss <= risk_budget` |
| Market Data | PASS | `market-data.md` §3–12 | Closed-only, UTC, identity, ordering, gap, stale, warm-up và indicator formulas đã rõ | Reject corrupted input; không synthetic fill/future candle |
| Error Codes | PASS | `error-and-reason-codes.md` §2–4 | Đã bổ sung coverage data/signal/risk/execution/recovery và map legacy aliases | Persist canonical code + typed observed/limit values |
| State Machine | PASS | `technical-specification.md` §9; `domain-models.md` §2, §4.17 | Đã tách global bot state và per-trade lifecycle, có legal/illegal transition rules | StateMachine là owner duy nhất của transition |
| Risk Engine | PASS | `risk-management.md`; `position-sizing.md` §9.1; `technical-specification.md` §8 | Final veto, health/limit gates và only-creator rule cho ApprovedTradePlan nhất quán | Property-test từng hard gate và không cho downstream nới risk |
| Execution Contract | PASS | `technical-specification.md` §5, §9.3, §11 | Request/report fields, approval gate, deterministic IDs và query-before-retry đã rõ | Adapter chỉ phát facts, không tự đổi domain state |
| Persistence / Journal | PASS | `technical-specification.md` §10–13; `domain-models.md` §4.16–6 | Write-ahead, append-only, revisions, correlation/version IDs và every-decision journal đã rõ | Enforce unique constraints và optimistic concurrency |
| Recovery | PASS | `technical-specification.md` §9.3; `error-and-reason-codes.md` | Đã chốt unknown submit, partial fill, SL/TP failure, restart và exhausted behavior | Reconcile authoritative external state trước mọi retry/new entry |

## 3. Cross-document consistency

### 3.1 Canonical model usage

| Model | Canonical producer | Main consumers | Cross-document conclusion |
|---|---|---|---|
| `Candle` | market-data validation/store | snapshot, indicators, backtest | Decimal OHLCV, UTC, closed status và stable identity thống nhất |
| `MarketSnapshot` | `SnapshotBuilder` | indicators, levels, regime, strategy | Một `as_of`, closed multi-timeframe data, no future data |
| `IndicatorSnapshot` | `IndicatorEngine` | levels, regime, strategy | Readiness explicit; không tạo fake values |
| `RegimeAssessment` | `RegimeDetector` | strategy, risk, journal | Bốn candidate scores; `UNCERTAIN` là outcome; prior assessment là explicit input |
| `RangeContext` | `LevelEngine` | regime, strategy, journal | Boundary IDs, width/mid/location, freshness và breakout revision đủ để replay |
| `Level` | `LevelEngine` | `LevelSet`, stop/target planning | Provenance, confirmation time, tests/strength và invalidation point-in-time |
| `LevelSet` | `LevelEngine` | regime, strategy, journal | Chứa supports/resistances/swings, structure và optional range cùng `as_of` |
| `SignalComponent` | `SignalScorer` | assessment, journal, analytics | Points và structured evidence tái tạo được từ config |
| `SignalAssessment` | `SignalScorer` | `DecisionEngine`, journal | Dual score, gate results và versions; không tự chọn side |
| `TradeCandidate` | `DecisionEngine` | risk, journal | Không có quantity/leverage; có setup, stop/target provenance và cost estimate |
| `RiskContext` | risk-context assembler | `RiskEngine`, journal | Equity/exposure/session counters, quote, health và reconciliation cùng version |
| `RiskDecision` | `RiskEngine` | state/execution gate, journal | APPROVE/REJECT/HALT; IDs nullable theo action |
| `ApprovedTradePlan` | `RiskEngine` only | execution, positions, journal | Immutable, quantized, TTL, risk budget/loss/RR và approval identity |
| `ExecutionReport` | execution adapter/simulator | positions, state, journal, recovery | Direction/purpose/status, cumulative fill, Decimal costs và UTC timestamps |
| `PositionState` | `PositionManager` | risk, execution, recovery | Immutable revision; open quantity phải protected hoặc fail-safe |
| `DecisionRecord` | application/journal | replay, analytics, audit | Có record cho mọi outcome; early-stage fields nullable thay vì fake value |
| `TradeLifecycle` | application/positions via events | counters, journal, recovery | Dùng `TradeLifecycleState`, giữ IDs sau approval và revision đơn điệu |

Tất cả price, quantity, PnL, fee và risk dùng `Decimal`; mọi event time/as-of dùng UTC.
Snapshot/event là immutable. `PositionState`, `RangeContext` và `TradeLifecycle` tiến
hóa bằng persisted revision/event thay vì mutate lịch sử.

### 3.2 Enum and identifier decisions

- `TradeSide` (`LONG`, `SHORT`) biểu diễn exposure; `OrderDirection` (`BUY`, `SELL`)
  biểu diễn hành động order. Mapping còn phụ thuộc `OrderPurpose` và `reduce_only`.
- `BotState` là process-wide state; `TradeLifecycleState` là state của một candidate/
  trade. Hai state machine không dùng chung enum.
- `ReasonCode` chỉ có một registry. Tên PHASE 1 hoặc tên tương đương trong acceptance
  được normalize bằng alias table, không tạo duplicate semantics.
- `evaluation_id` là `decisionId`; `candidate_id` là `tradeCandidateId`;
  `approved_plan_id` là `approvedTradePlanId`; `client_order_id` là idempotency boundary
  của từng logical purpose order.

### 3.3 Deterministic decision boundary

```text
closed MarketSnapshot
  + IndicatorSnapshot
  + prior RangeContext / prior RegimeAssessment
  + versioned Configuration
  -> LevelSet
  -> RegimeAssessment
  -> SignalAssessment
  -> TradeCandidate | NO_TRADE
```

Prior state là input persisted, không phải hidden mutable state. Cùng canonical inputs,
versions và event ordering phải tạo serialized output giống nhau. Risk evaluation thêm
fresh `RiskContext`, instrument metadata và FeeModel version; vì vậy strategy không thể
tự cấp quyền execution.

## 4. Contradictions found and resolved

| Initial contradiction/gap | Standardized decision |
|---|---|
| `TradeLifecycle.state` dùng global `BotState` | Tạo `TradeLifecycleState` và transition table riêng |
| LONG/SHORT có nguy cơ bị dùng như BUY/SELL | Tách `TradeSide` và `OrderDirection`, map theo purpose/reduce-only |
| Regime/strategy dùng từ định tính và wildcard config | Chốt formulas, ramps, evidence keys, thresholds, precedence và tie-breaks |
| Stateful regime persistence không xuất hiện trong interface | `prior_assessment` trở thành input nullable explicit; missing recovery state fail closed |
| Range edge/breakout có thể overlap hoặc chọn tùy ý | Chốt normalized zones, exact boundary inequalities và breakout-before-mean-reversion priority |
| Stop ATR buffer nằm trong risk config dù Strategy dựng candidate | Chuyển thành `strategy.stop.atr_buffer`; Risk chỉ validate min/max/tick/spread guards |
| Hai config ordering window cùng semantics | Giữ duy nhất `data.ordering_window` |
| Funding vừa được mô tả như cost không âm vừa như cash flow signed | Cost estimate dùng non-negative debit; realized `funding_cash_flow` signed |
| Risk health gate cho phép hiểu `DEGRADED` là approvable | Chỉ APPROVE khi bốn health statuses đều `HEALTHY` |
| Lifecycle REJECTED bị cấm giữ approval IDs dù exchange có thể reject sau approval | Risk-rejected không có IDs; execution-rejected giữ IDs để audit |
| Risk decision ID chứa evaluation time và có thể tạo nhiều approval cho cùng candidate | Bỏ wall-clock khỏi deterministic ID; một candidate tối đa một APPROVE và một lifecycle |
| Unknown submit/partial fill/TP failure chưa có end-state duy nhất | Chốt query-before-retry, protect-stop-first, bounded recovery và reduce/halt khi exhausted |
| Reason names giữa yêu cầu và PHASE 1/2 khác nhau | Giữ canonical registry và explicit alias mapping |

## 5. Failure / recovery matrix

| Failure Scenario | Expected Behavior | Reason Code | State |
|---|---|---|---|
| Market data stale | `NO_TRADE`; backfill/recover, không tạo snapshot hợp lệ | `DATA_STALE` | Global `OBSERVING` hoặc `RECOVERING`; no lifecycle |
| Indicator unavailable | `NO_TRADE`; giữ readiness false, không fake value | `INDICATOR_NOT_READY` | Global trở về `OBSERVING`; no lifecycle |
| Invalid risk | Risk final veto; không tạo approved plan | Code cụ thể, ví dụ `RISK_BUDGET_INVALID` / `RISK_BUDGET_EXCEEDED` | Global `OBSERVING`; lifecycle `REJECTED` |
| Exchange timeout | Không submit lại; query cùng client ID | `ORDER_TIMEOUT` + `ORDER_OUTCOME_UNKNOWN` khi outcome chưa rõ | Global `RECOVERING`; lifecycle `RECOVERY` |
| Unknown order result | Block entry và reconcile authoritative order/position | `ORDER_OUTCOME_UNKNOWN` | Global `RECOVERING`; lifecycle `RECOVERY` |
| Partial fill | Cancel remainder, xác nhận cumulative fill, đặt stop trước rồi TP cho filled quantity | `PARTIAL_FILL`; unresolved dùng `PARTIAL_FILL_UNRESOLVED` | `RECOVERING` / `RECOVERY`, rồi `MANAGING_POSITION` / `OPEN` nếu protected |
| SL placement failure | Cancel remainder, reduce-only emergency close, activate kill switch | `PROTECTION_FAILED` | Global và lifecycle `HALTED` cho tới khi flat/reconciled |
| TP placement failure | Giữ confirmed stop; retry/query cùng TP ID; exhausted thì reduce-only close + halt | `TAKE_PROFIT_PLACEMENT_FAILED`; exhausted thêm `RECOVERY_EXHAUSTED` | `RECOVERING` / `RECOVERY`, có thể `HALTED` |
| Journal write failure | Trước submit: không I/O; sau fill: block entry, protect/reduce, emergency diagnostic và reconcile later | `JOURNAL_UNAVAILABLE` | Global `HALTED`; lifecycle giữ durable revision gần nhất rồi reconcile |
| State mismatch | Block entry, query authoritative state, rebuild revisions; exhausted thì halt | `STATE_MISMATCH`; exhausted thêm `RECOVERY_EXHAUSTED` | `RECOVERING` / `RECOVERY` → có thể `HALTED` |
| Config invalid | Fail startup trước khi tạo provider/execution side effect | `CONFIG_INVALID` | Global `HALTED`; no lifecycle |

## 6. Acceptance criteria rerun

| Criterion | Status | Evidence |
|---|---|---|
| Domain models consistent | PASS | §3.1; `domain-models.md` |
| Enum definitions canonical | PASS | §3.2; canonical enum table |
| No undefined business terms | PASS | Formula/gate/registry audit |
| No critical magic numbers | PASS | Typed config + cross-field validation |
| Strategy deterministic | PASS | `strategy.md` formulas and tie-breaks |
| Regime detection deterministic | PASS | Candidate formulas, precedence and persistence input |
| SIDEWAY logic deterministic | PASS | Range location and breakout/retest state machine |
| Position sizing mathematically complete | PASS | Metadata conversion, floor rounding and recomputation |
| Risk invariants explicit | PASS | `position-sizing.md` §9.1 |
| Market data validation defined | PASS | `market-data.md` validation/readiness contract |
| Reason codes complete | PASS | Registry and alias coverage |
| State machine complete | PASS | Global + lifecycle transition tables |
| Idempotency strategy defined | PASS | ID derivation, uniqueness and query-before-retry |
| Recovery behavior defined | PASS | §5 and technical recovery protocol |
| Secret boundary defined | PASS | `configuration.md` §6; no secret material created |
| No cross-document contradictions remain | PASS | Second-pass cross-reference review |
| PHASE 3 need not invent business logic | PASS | Remaining inputs are typed calibration/adapter data only |

## 7. Gate decision and next scope

**PHASE 2: APPROVED**

Proposed PHASE 3 scope only:

1. Create Python project scaffold, package boundaries and quality/test tooling.
2. Implement canonical enums, immutable value objects/models and validation errors.
3. Implement typed configuration loading, canonical hashing and secret redaction boundary.
4. Implement pure indicator, level/range, regime, strategy and risk-domain functions
   behind the documented interfaces, beginning with unit/property/golden tests.
5. Implement repository interfaces and SQLite append-only journal/idempotency constraints
   with local test doubles only.

PHASE 3 is not started by this review. No OKX connection, credential, order submission
or real trading loop was created.
