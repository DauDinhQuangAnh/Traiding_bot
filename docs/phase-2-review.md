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

| Area | Status | Evidence | Notes |
|---|---|---|---|
| Domain Models | PASS | `domain-models.md` §2–6 | Canonical enums, immutable models, nullability, provenance và validators đã định nghĩa; `TradeCandidate` mang regime và hai score nhưng không có quantity/leverage. |
| Configuration | PASS | `configuration.md` §3–7 | Không còn wildcard business config; mọi key, type, range, cross-field rule và failure behavior đều explicit. |
| Regime Detection | PASS | `regime-detection.md` §2–6 | Evidence atoms, normalization, candidate qualification, conflict, precedence và persisted confirmation algorithm đều deterministic. |
| Strategy | PASS | `strategy.md` §2–8 | Sáu canonical components có exact operands, timeframe, formulas, configured maxima/weights, aggregation, gates và tie-breaks. |
| Sideway Logic | PASS | `regime-detection.md` §7–10; `strategy.md` §6 | Range construction, validity, normalized location, middle-range block và ordered breakout/retest transitions đã khóa. |
| Position Sizing | PASS | `position-sizing.md` §3–10 | Contract multiplier, adverse rounding, caps và recomputation bắt buộc chứng minh `worst_case_loss <= risk_budget`. |
| Risk Engine | PASS | `risk-management.md`; `position-sizing.md` §9.1; `technical-specification.md` §8 | Risk là final veto và owner duy nhất tạo `ApprovedTradePlan`; execution không được nới risk. |
| Market Data | PASS | `market-data.md` §3–12 | Closed-only, UTC, identity/order/gap/stale/warm-up và canonical indicator formulas đã rõ. |
| State Machine | PASS | `technical-specification.md` §9; `domain-models.md` §4.17 | Global bot state và per-trade lifecycle tách biệt, legal/illegal transitions explicit. |
| Idempotency | PASS | `technical-specification.md` §9.3, §11–13 | Deterministic IDs, uniqueness, write-ahead intent và query-before-retry đã định nghĩa. |
| Recovery | PASS | `technical-specification.md` §9.3; `error-and-reason-codes.md` | Unknown submit, partial fill, protection failure, restart và exhausted outcomes đều fail-safe. |
| Error Codes | PASS | `error-and-reason-codes.md` §2–4 | Canonical registry bao phủ data/config/signal/risk/execution/recovery; aliases không tạo semantics mới. |
| Secret Handling | PASS | `configuration.md` §6 | Secrets chỉ đến từ environment, bị loại khỏi config hash/log/Git và không được tạo trong Phase 2. |

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
| `SignalComponent` | `SignalScorer` | assessment, journal, analytics | Enum name, directional points/operands và structured evidence tái tạo được từ config |
| `SignalAssessment` | `SignalScorer` | `DecisionEngine`, journal | Dual score, gate results và versions; không tự chọn side |
| `TradeCandidate` | `DecisionEngine` | risk, journal | Không có quantity/leverage; có regime, selected/opposite scores, setup, stop/target provenance và cost estimate |
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
| Component config dùng `<name>` và không khóa evidence registry | Dùng exact six-key `SignalComponentName` mappings; từng component có exact evidence keys, enabled/disabled validation và tổng max score 100 |
| Score chưa khóa timeframe, operand và confirmation source | Dùng M15 indicators/structure, trigger M15 close, final child M5 confirmation và setup-specific RSI bands; evidence lưu operand/unit/source IDs |
| Strategy từng nêu active-position/pending-order gate nhưng không nhận account/order input | Chuyển gate này về orchestration/Risk; Strategy chỉ xử lý market/regime/level/config inputs |
| Structure dùng chung cluster tolerance và không khóa timeframe | Chốt canonical structure ở M15 và dùng riêng `levels.structure_comparison_tolerance_atr` |
| Stateful regime persistence không xuất hiện trong interface | `prior_assessment` trở thành input nullable explicit; missing recovery state fail closed |
| Regime persistence chưa định nghĩa previous confirmed state/count update | Chốt exact `last_confirmed`, candidate count, high-volatility bypass, wait/confirm/reset và restart algorithm |
| Setup bị config disable chưa có outcome canonical | Chốt `NO_TRADE` với `SETUP_DISABLED` và đăng ký reason code duy nhất |
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
| Entry/stop/target rules deterministic | PASS | Setup order, structural anchors, buffers, opposing-level selection and RR formulas |
| Config fields and validation explicit | PASS | Exact typed keys, evidence registries, ranges, feasibility checks and startup HALT |
| Signal conflict behavior defined | PASS | Regime → `UNCERTAIN`; strategy → `NO_TRADE` + `AMBIGUOUS_SIGNAL` |
| Unknown regime behavior defined | PASS | Canonical `UNCERTAIN` is fail-closed and always blocks candidate creation |
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

## 7. Implementation readiness test

Một developer bắt đầu PHASE 3 chỉ từ các tài liệu hiện tại có phải tự quyết định các
business rule sau không?

| Question | Answer | Contract that removes the decision |
|---|---|---|
| Indicator nào dùng? | **NO** | `market-data.md` khóa EMA20/50/200, RSI, ATR, ADX, Bollinger width và volume mean/ratio; không được tự thêm indicator. |
| Period bao nhiêu? | **NO** | EMA cố định `[20,50,200]`; các period/lookback còn lại là typed `BACKTEST_REQUIRED` inputs. Missing value làm `CONFIG_INVALID`, không cho developer chọn default. |
| Regime xác định thế nào? | **NO** | `regime-detection.md` §2–6 có exact atoms, ramps, weights, qualification, conflict, precedence và confirmation state. |
| Score tính thế nào? | **NO** | `strategy.md` §3–5 định nghĩa six-component strengths, configured weights/maxima, sum, confluence và advantage gates. |
| Near support nghĩa là gì? | **NO** | `position_in_range` và inclusive boundaries ở `regime-detection.md` §7 quyết định location. |
| Breakout nghĩa là gì? | **NO** | §9 định nghĩa exact M15 detect, subsequent confirmation, retest, invalidation và expiry inequalities. |
| Confirmation nghĩa là gì? | **NO** | `strategy.md` §3 khóa body/wick/close-location formulas trên final closed M5 child candle. |
| Quantity round thế nào? | **NO** | `position-sizing.md` khóa floor-to-lot, contract conversion, caps và post-round risk recomputation. |
| Invalid config xử lý sao? | **NO** | `configuration.md` §5: `CONFIG_INVALID`, global `HALTED`, không tạo provider/execution side effect. |
| Signal conflict xử lý sao? | **NO** | Regime conflict → `UNCERTAIN`; dual eligible strategy signal → `NO_TRADE` + `AMBIGUOUS_SIGNAL`; không tie-break tùy ý. |

### Remaining assumptions

- Numerical values gắn `BACKTEST_REQUIRED` phải được một versioned experiment/config
  cung cấp và calibrate trước runtime. Đây là input vận hành, không phải quyền tự chọn
  business rule của developer; missing/invalid luôn fail startup.
- Provider/adapter phải cung cấp point-in-time candles, instrument metadata, fee,
  slippage và funding estimates theo các port contracts. Strategy không được tự giả lập
  giá trị bị thiếu.
- Evaluation đầu tiên hoặc restart không khôi phục được prior assessment dùng
  `prior_assessment=null` và phải tích lũy lại đủ confirmation count.
- Profitability và numerical tuning chưa được khẳng định; chúng thuộc backtest/validation
  sau này và không thay đổi deterministic formulas nếu không tăng version.

## 8. Gate decision and next scope

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
