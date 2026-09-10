# Technical Specification — PHASE 2

## 1. Goals

- Chuyển PHASE 1 architecture thành contracts đủ chính xác để PHASE 3 scaffold code
  mà không phải đoán business logic.
- Giữ deterministic, testable và fail-closed behavior từ market data đến journal.
- Chốt domain models, enums, ports, state transitions, idempotency, persistence,
  reason codes, configuration và versioning.
- Bảo đảm Risk Engine là authority duy nhất phát hành executable trade plan.
- Cho phép backtest, Demo và sau này adapter khác dùng chung domain pipeline.

## 2. Non-goals

PHASE 2 không:

- Gọi OKX REST/WebSocket, tạo key/secret hoặc gửi Demo/Live order.
- Implement strategy/indicator/exchange adapter, UI hoặc AI decision.
- Optimize parameter, train ML hoặc tuyên bố profitability.
- Chọn numerical threshold như giá trị tối ưu.
- Bắt đầu PHASE 3.

## 3. Domain boundaries

Dependency direction:

```text
app/orchestration
  → domain services (indicators, regime, levels, strategy, risk, positions)
  → ports (provider/repository/clock/metadata/execution interfaces)

infrastructure adapters → implement ports
domain ─X→ OKX SDK / SQLite / network / system clock
```

| Boundary | Owns | Must not own |
|---|---|---|
| Market Data | Normalize, validate, closed store, snapshots | Signal/risk decisions |
| Indicators | Point-in-time calculations/warm-up | Regime hoặc order |
| Regime/Levels | Evidence, structure, range/breakout state | Trade size/execution |
| Strategy | Scores, decision, candidate geometry | Quantity/leverage |
| Risk | Limits, sizing, veto, approval, kill switch | Market alpha |
| Execution | Idempotent order protocol | Synthesize approval |
| Positions | Fill/position/protection/reconciliation state | Ignore exchange truth |
| Journal | Append-only audit and repositories | Change past decisions |
| Backtest | Historical provider/simulated execution | Alternate domain rules |

## 4. Data contracts

Canonical models, enums, nullability and validation nằm trong `domain-models.md`.
Cross-cutting rules:

- Price/quantity/money/PnL/fees/risk: Decimal only với configured precision/rounding.
- UTC aware datetime only.
- Closed candle only; all data bounded by `as_of`.
- Immutable snapshots/events; state changes create new revision.
- Every decision carries `VersionSet` and correlation IDs.

## 5. Module interfaces and ports

Signatures dưới đây là language-level contracts, không phải code implementation.
Operations có thể async ở adapters; domain return types/result semantics không đổi.

### 5.1 Domain service interfaces

| Service | Operation | Contract |
|---|---|---|
| `SnapshotBuilder` | `build(trigger, config_version) -> Result[MarketSnapshot]` | Consistent point-in-time read; detects duplicate/gap/future data |
| `IndicatorEngine` | `calculate(snapshot, config) -> IndicatorSnapshot` | No side effects; not-ready explicit |
| `LevelEngine` | `assess(snapshot, indicators, prior_range_state: RangeContext?, config) -> LevelSet` | Confirmed points only; event-sourced range state |
| `RegimeDetector` | `detect(snapshot, indicators, level_set, prior_assessment: RegimeAssessment?, config) -> RegimeAssessment` | Prior assessment is explicit persistence input; uses `level_set.market_structure`; uncertain on conflict |
| `SignalScorer` | `score(snapshot, indicators, level_set, regime_assessment, config) -> SignalAssessment` | Scores both sides; no candidate/order |
| `DecisionEngine` | `decide(snapshot, indicators, level_set, regime_assessment, signal_assessment, config, fee_model) -> DecisionOutcome` | Always DecisionRecord; candidate optional |
| `RiskEngine` | `evaluate(candidate, risk_context, metadata, fee_model, config) -> RiskOutcome` | APPROVE/REJECT/HALT; only creator of approved plan |
| `PositionManager` | `apply(report/event, prior_state) -> PositionTransition` | Validated revision; protection/reconciliation invariants |
| `StateMachine` | `transition(current, event, context) -> Result[Transition]` | Invalid transitions rejected and journaled |

### 5.2 Infrastructure ports

Port DTOs là immutable, Decimal/UTC và không chứa raw SDK object:

| DTO | Required fields |
|---|---|
| `RawMarketEvent` | source event ID, source, symbol, event type, raw payload reference/hash, event time, receive time |
| `RawCandle` | source fields ở dạng lossless string/UTC timestamp, explicit closed status |
| `AccountSnapshot` | account ID, equity, eligible equity, available margin, currency, event/receive time, reconciliation/state version |
| `BalanceSnapshot` | account ID, currency, total/available/frozen Decimal amounts, as-of/state version |
| `ExternalPosition` | symbol, side, quantity, average entry, mark price, margin/leverage, external position ID, event/receive time |
| `InstrumentMetadata` | symbol/type, base/quote/settle currencies, contract value/unit, tick/lot/min/max sizes, leverage/margin constraints, effective time/version |
| `OrderRequest` | approved plan ID, purpose, symbol, BUY/SELL direction, order type, Decimal quantity/price/trigger, reduce-only flag, client order ID |

Adapter validates raw DTO then maps vào canonical domain model; raw payload chỉ dùng
audit/debug và không được truyền vào domain logic.

#### `MarketDataProvider`

- `stream_events(symbols, timeframes) -> AsyncIterator[RawMarketEvent]`
- `fetch_candles(symbol, timeframe, start, end, limit) -> Sequence[RawCandle]`
- `fetch_latest_quote(symbol) -> Quote`
- `health() -> ComponentHealth`

#### `AccountProvider`

- `get_account_snapshot(account_id) -> AccountSnapshot`
- `get_positions(symbol?) -> Sequence[ExternalPosition]`
- `get_balance(currency) -> BalanceSnapshot`
- `health() -> ComponentHealth`

Account data must carry event/receive time and reconciliation version.

#### `ExchangeExecutionPort`

- `submit_order(order_request) -> ExecutionReport`
- `cancel_order(client_order_id, exchange_order_id?) -> ExecutionReport`
- `get_order(client_order_id, exchange_order_id?) -> ExecutionReport`
- `get_open_orders(symbol) -> Sequence[ExecutionReport]`
- `get_position(symbol) -> ExternalPosition`
- `health() -> ComponentHealth`

Only accepts request derived from unexpired `ApprovedTradePlan`. Timeout result is
`UNKNOWN`, not proof of rejection. Adapter must support query by client ID before retry.

#### `JournalRepository`

- `append(event, expected_stream_revision?) -> PersistedEvent`
- `get_stream(stream_id, after_revision?) -> Sequence[PersistedEvent]`
- `find_by_evaluation_id(evaluation_id) -> DecisionRecord?`
- `find_by_client_order_id(client_order_id) -> OrderIntent?`
- `transaction(operation) -> Result`
- `health() -> ComponentHealth`

Append is durable and idempotent by event ID. No update/delete audit API.

#### `Clock`

- `now_utc() -> datetime`
- `monotonic() -> DurationCounter`

Business logic không gọi system time/sleep trực tiếp.

#### `InstrumentMetadataProvider`

- `get(symbol, as_of) -> InstrumentMetadata`
- `health() -> ComponentHealth`

Metadata includes instrument type, contract/quote/base units, tick/lot/min/max,
contract value, supported order/margin/leverage constraints, version/effective time.
Risk-context assembler tổng hợp component health thành canonical `HealthSnapshot`; một
adapter không được tự suy đoán status của component khác.

#### `FeeModel`

Operations và accounting semantics theo `position-sizing.md` §10–11.

## 6. Configuration

Typed schema và classifications nằm trong `configuration.md`. Required behavior:

- base + environment overlay, unknown key invalid.
- risk/strategy thresholds explicit và `BACKTEST_REQUIRED`.
- secrets chỉ từ environment, excluded from hash/log.
- execution disabled/dry-run in PHASE 2; live environment luôn rejected.
- config change creates new version and invalidates stale candidate/approval.

## 7. Decision pipeline

```text
CandleClosed(15m)
→ dedupe evaluation key
→ build valid multi-timeframe snapshot
→ indicator readiness
→ levels/structure/range state
→ multi-evidence regime
→ regime/setup gates
→ long + short component scores
→ threshold + minimum difference
→ entry/stop/target + net RR
→ DecisionRecord (always)
→ optional TradeCandidate
```

Any missing/uncertain/ambiguous condition ends as journaled `NO_TRADE`. SIDEWAY middle
and breakout before validated retest can never produce candidate.

## 8. Risk pipeline

```text
TradeCandidate + fresh RiskContext + InstrumentMetadata + FeeModel
→ health/reconciliation/kill-switch gates
→ daily/trade/consecutive/cooldown limits
→ spread/slippage/market-quality gates
→ stop/target/RR validation
→ stop-loss risk budget sizing
→ notional/exposure/leverage/margin caps
→ floor precision + recompute worst-case loss
→ APPROVE immutable TTL plan | REJECT | HALT
```

Executor revalidates plan ID/TTL/one-shot use/config-state-instrument versions and
last-mile market conditions. It may reject/expire, never enlarge or repair plan.

### 8.1 Risk counter semantics

- Risk session boundary là 00:00 UTC; reset counter không tự reset active kill switch.
- Daily loss dùng realized `net_pnl` sau fees/funding. Trigger khi
  `daily_net_pnl <= -max_daily_loss`.
- Daily drawdown là `(session_peak_equity - account_equity) / session_peak_equity`;
  peak chỉ tăng trong session và state được persist. Chạm configured cap → HALT.
- Daily trade count tăng đúng một lần khi lifecycle nhận first non-zero entry fill;
  canceled/unfilled order không tính, partial fills cùng lifecycle không tăng thêm.
- Khi lifecycle đóng: `net_pnl < 0` tăng consecutive losses; `net_pnl > 0` reset về
  zero; `net_pnl = 0` giữ nguyên. Counters update transactionally với close event.
- Cooldown bắt đầu khi closed lifecycle có net loss, dùng persisted UTC timestamp.

## 9. State machine contract

Invalid event/state pair returns `INVALID_STATE_TRANSITION`, leaves state unchanged,
and appends `INVALID_TRANSITION`. Repeated/critical invalid transitions escalate by
health policy; they never get silently ignored.

### 9.1 Global bot state

| Current State | Event | Guard | Next State | Side effect |
|---|---|---|---|---|
| `STARTING` | `CONFIG_VALIDATED` | Security/config valid, live disabled | `SYNCING` | Journal startup/version set |
| `STARTING` | `STARTUP_VALIDATION_FAILED` | Any hard failure | `HALTED` | Activate kill switch, journal codes |
| `SYNCING` | `SYNC_COMPLETED` | Data/account/orders/position reconciled | `OBSERVING` | Persist reconciliation snapshot |
| `SYNCING` | `SYNC_FAILED` | Timeout/unresolved mismatch | `HALTED` | Kill switch + alert |
| `OBSERVING` | `CANDLE_CLOSED` | 15m closed, unique evaluation key, health OK | `EVALUATING` | Reserve evaluation ID |
| `OBSERVING` | `LOSS_COOLDOWN_STARTED` | Closed loss, policy active | `COOLDOWN` | Persist cooldown_until |
| `OBSERVING` | `HEALTH_CRITICAL` | Critical trigger | `HALTED` | Kill switch |
| `EVALUATING` | `NO_TRADE` | Decision persisted | `OBSERVING` | Append decision/reasons |
| `EVALUATING` | `RISK_REJECTED` | Risk event persisted | `OBSERVING` | Append veto/reasons |
| `EVALUATING` | `RISK_APPROVED` | Plan persisted, unexpired | `SUBMITTING` | Write-ahead order intent |
| `EVALUATING` | `RISK_HALT` | HALT decision persisted | `HALTED` | Kill switch |
| `SUBMITTING` | `ORDER_ACKNOWLEDGED` | Client/plan IDs match | `PENDING_ENTRY` | Persist execution report |
| `SUBMITTING` | `ORDER_REJECTED` | Authoritative rejected status | `OBSERVING` | Close intent, journal |
| `SUBMITTING` | `SUBMIT_OUTCOME_UNKNOWN` | Timeout/no authoritative result | `RECOVERING` | Query by client ID; no blind retry |
| `PENDING_ENTRY` | `ENTRY_CANCELED_UNFILLED` | Confirmed zero fill | `OBSERVING` | Close lifecycle without trade count per policy |
| `PENDING_ENTRY` | `ENTRY_FILLED_PROTECTED` | Fill accepted; stop and TP cover filled quantity | `MANAGING_POSITION` | Persist position/protection |
| `PENDING_ENTRY` | `PARTIAL_FILL_OR_PROTECTION_UNKNOWN` | Exposure/state unresolved | `RECOVERING` | Block entries, protect/reduce |
| `PENDING_ENTRY` | `PROTECTION_FAILED` | Stop cannot be confirmed for filled quantity | `HALTED` | Cancel remainder, reduce-only close, kill switch |
| `MANAGING_POSITION` | `EXIT_TRIGGERED` | Valid SL/TP/risk-reducing intent | `EXITING` | Persist reduce-only intent |
| `MANAGING_POSITION` | `STATE_UNCERTAIN` | Disconnect/mismatch | `RECOVERING` | Block entry, reconcile |
| `MANAGING_POSITION` | `PROTECTION_FAILED` | Open quantity unprotected | `HALTED` | Protect/reduce + kill switch |
| `EXITING` | `POSITION_CLOSED` | Exchange flat, reports reconciled | `OBSERVING` | Finalize PnL/fees/funding/counters |
| `EXITING` | `EXIT_OUTCOME_UNKNOWN` | Timeout/mismatch | `RECOVERING` | Query/reconcile; no duplicate exit |
| `RECOVERING` | `RECONCILED_FLAT` | Authoritative flat and health OK | `OBSERVING` | Persist correction/reconciliation |
| `RECOVERING` | `RECONCILED_PROTECTED_POSITION` | Position exists, full stop confirmed | `MANAGING_POSITION` | Restore lifecycle/state |
| `RECOVERING` | `RECOVERY_FAILED` | Cannot reach safe known state | `HALTED` | Kill switch + alert |
| `COOLDOWN` | `COOLDOWN_EXPIRED` | Clock reached persisted time, health/sync OK | `OBSERVING` | Journal end of cooldown |
| `COOLDOWN` | `HEALTH_CRITICAL` | Critical trigger | `HALTED` | Kill switch |
| `HALTED` | `RISK_REDUCING_ACTION` | Existing exposure only, reduce/protect/cancel safe | `HALTED` | Journal; never open exposure |
| `HALTED` | `OPERATOR_RESET_REQUESTED` | Cause resolved + full sync + audit identity/reason | `SYNCING` | Persist reset request; kill switch remains until sync |

Any state may receive a critical health event and enter `HALTED`, except that
transition implementation must be idempotent when already halted.

### 9.2 Trade lifecycle state

NO_TRADE không tạo TradeLifecycle. Directional candidate tạo lifecycle có
`trade_id = candidate_id`; global `BotState` và `TradeLifecycleState` là hai enum riêng.

| Current lifecycle state | Event | Guard | Next lifecycle state | Persisted effect |
|---|---|---|---|---|
| `CANDIDATE_CREATED` | `RISK_REVIEW_STARTED` | Candidate valid | `RISK_REVIEW` | Candidate + lifecycle revision |
| `RISK_REVIEW` | `RISK_REJECTED` | RiskDecision REJECT | `REJECTED` | Risk decision/reasons; terminal |
| `RISK_REVIEW` | `RISK_APPROVED` | Approval/plan valid | `APPROVED` | Risk decision + immutable plan |
| `RISK_REVIEW` | `RISK_HALT` | RiskDecision HALT | `HALTED` | Kill switch event |
| `APPROVED` | `ORDER_INTENT_PERSISTED` | Unique entry client ID, plan unexpired | `SUBMITTING` | Write-ahead intent before I/O |
| `SUBMITTING` | `ORDER_ACKNOWLEDGED` | IDs match | `PENDING_ENTRY` | Execution report |
| `SUBMITTING` | `ORDER_REJECTED` | Authoritative reject, zero fill | `REJECTED` | Terminal report/reason |
| `SUBMITTING` | `SUBMIT_OUTCOME_UNKNOWN` | Timeout/no authoritative state | `RECOVERY` | Preserve client ID; query only |
| `PENDING_ENTRY` | `ENTRY_CANCELED_UNFILLED` | Confirmed zero cumulative fill | `REJECTED` | Cancel report; no trade count |
| `PENDING_ENTRY` | `ENTRY_FILLED_PROTECTED` | Filled quantity, stop and TP confirmed | `OPEN` | Position/protection snapshot |
| `PENDING_ENTRY` | `PARTIAL_FILL` | Cumulative fill between zero/requested | `RECOVERY` | Cancel remainder, protect fill |
| `PENDING_ENTRY` | `TAKE_PROFIT_FAILED` | Stop confirmed nhưng TP chưa confirmed | `RECOVERY` | Keep stop; recover TP or reduce |
| `OPEN` | `EXIT_TRIGGERED` | Reduce-only intent valid | `CLOSING` | Write-ahead exit intent |
| `OPEN` | `STATE_UNCERTAIN` | Disconnect/mismatch | `RECOVERY` | Reconciliation event |
| `OPEN` | `PROTECTION_FAILED` | Stop absent/invalid | `HALTED` | Reduce-only close + kill switch |
| `CLOSING` | `POSITION_CLOSED` | Authoritative flat and reports reconciled | `CLOSED` | Final PnL/counters |
| `CLOSING` | `EXIT_OUTCOME_UNKNOWN` | Timeout/mismatch | `RECOVERY` | Query/reconcile |
| `RECOVERY` | `RECONCILED_NO_FILL` | No order and zero position | `REJECTED` | Resolve intent terminally |
| `RECOVERY` | `RECONCILED_PENDING_ORDER` | Authoritative pending entry | `PENDING_ENTRY` | Restore order state |
| `RECOVERY` | `RECONCILED_PROTECTED_POSITION` | Filled position, stop and TP confirmed | `OPEN` | Restore position state |
| `RECOVERY` | `RECONCILED_CLOSED` | Authoritative flat after prior fill/exit | `CLOSED` | Finalize reports/PnL |
| `RECOVERY` | `RECOVERY_FAILED` | Attempts exhausted/state unsafe | `HALTED` | Reduce if possible + kill switch |
| `HALTED` | `POSITION_CLOSED` | Risk-reducing close confirmed flat | `CLOSED` | Finalize PnL; global bot remains HALTED |

Execution adapter chỉ phát facts (`ExecutionReport`); application StateMachine là nơi
duy nhất áp transition. Mọi revision persist state, triggering event ID, reason codes,
order/position references và VersionSet để restart replay không phải suy đoán.

### 9.3 Failure and recovery protocol

1. **Submit timeout/unknown result:** persist `ORDER_TIMEOUT` và
   `ORDER_OUTCOME_UNKNOWN`, chuyển global/lifecycle sang recovery, query cùng
   `client_order_id`. Không tạo client ID hoặc submit mới. Bounded query hết mà chưa
   có authoritative state → `RECOVERY_EXHAUSTED`, HALT.
2. **Partial entry fill:** chặn entry mới, cancel unfilled remainder và xác nhận cancel;
   lấy exact cumulative fill, đặt STOP reduce-only trước rồi TAKE_PROFIT cho đúng filled
   quantity bằng deterministic purpose IDs. Cả hai confirmed → OPEN; outcome chưa rõ
   vẫn RECOVERY.
3. **Stop placement failure:** cancel remainder, phát reduce-only MARKET close cho
   filled quantity bằng deterministic emergency EXIT ID, kích hoạt HALT. Close timeout
   tiếp tục query trong HALTED/RECOVERY; không coi position đã flat khi chưa xác nhận.
4. **Take-profit placement failure:** chỉ áp dụng khi stop đã confirmed. Giữ stop,
   cancel entry remainder, RECOVERY và query/retry cùng TP client ID theo bounded policy.
   Hết attempts → reduce-only close và HALT với `RECOVERY_EXHAUSTED`.
5. **Journal failure trước submit:** không gọi execution port; HALT. Sau fill: block
   entry, bảo vệ/reduce exposure trước, ghi emergency local diagnostic không chứa secret,
   và HALT; audit chính phải reconcile bổ sung khi repository phục hồi.
6. **State mismatch/restart:** exchange/account provider là authoritative cho current
   order/position; local append-only events vẫn là audit truth. Chặn entry, query open
   orders/position, rebuild revisions; mismatch không resolve trong bounded policy → HALT.
7. **Invalid config:** fail tại STARTING, không tạo provider/execution side effect.

Recovery retry chỉ áp dụng idempotent query/cancel hoặc cùng logical client ID theo port
contract. Delay/backoff/attempt limits lấy từ typed config, không hard-code.

## 10. Persistence

SQLite MVP logical stores/tables:

| Store | Key/constraint | Purpose |
|---|---|---|
| `candles` | source/symbol/timeframe/open_time/revision unique | Normalized closed data + versions |
| `evaluations` | `evaluation_id` unique; evaluation tuple unique | Dedupe and DecisionRecord |
| `domain_events` | `event_id` unique; stream/revision unique | Append-only audit/event replay |
| `trade_candidates` | `candidate_id` unique | Immutable pre-risk plan |
| `risk_decisions` | `risk_decision_id` unique | Veto/approval audit |
| `approved_plans` | plan/approval unique; consumed flag via event/revision | One-shot executable plan |
| `order_intents` | `client_order_id` unique; approval unique for entry | Write-ahead/idempotency |
| `execution_reports` | report/event ID unique | Ack/fill/cancel dedupe |
| `position_snapshots` | position/state_version unique | Reconciliation/history |
| `trade_lifecycles` | trade/revision unique | PnL/counter/exit lifecycle |
| `kill_switch_events` | event ID unique | Trigger/reset audit |

Write-ahead rule: persist plan and order intent transactionally before external submit.
If journal-critical write fails, do not submit and halt. Database correction is a new
event/revision; no audit history overwrite.

## 11. Idempotency

Canonical IDs derive from canonical serialized inputs and a namespace/versioned hash;
adapters may encode/truncate to venue constraints but must persist reversible mapping.

| ID | Deterministic input |
|---|---|
| `evaluation_id` (`decisionId`) | symbol + 15m close time + strategy version + config version |
| `candidate_id` | evaluation ID + side + setup type + entry/stop/targets + assessment ID |
| `trade_id` | Candidate ID; stable từ lúc lifecycle được tạo |
| `risk_decision_id` | Candidate ID + risk-context ID + state/config/instrument versions |
| `risk_approval_id` | Risk decision ID + canonical `APPROVE` marker; chỉ có khi approved |
| `approved_plan_id` | Risk approval ID + canonical quantized plan payload + instrument version |
| `client_order_id` | Approved plan ID + `OrderPurpose` (`ENTRY`, `STOP`, `TAKE_PROFIT`, `EXIT`) + sequence |
| `event_id` | producer + aggregate ID + event type + producer sequence/payload hash |

Rules:

1. Unique DB constraint enforces one evaluation per evaluation tuple and one lifecycle
   per candidate/trade ID.
2. A candidate may receive at most one APPROVE result. If its plan expires before
   write-ahead intent, that lifecycle becomes terminal; a fresh candle evaluation must
   create a new candidate instead of re-approving the old one.
3. Unique `(trade_id, OrderPurpose, sequence)` enforces one logical purpose order; one
   risk approval can therefore create at most one logical ENTRY client ID.
4. Transport retry reuses the same client ID; it never creates a new logical order.
5. Submit timeout transitions to RECOVERING and queries exchange by client ID.
6. Duplicate execution reports are discarded by event/report ID after audit metric.
7. Process restart loads unresolved intents and reconciles before new evaluation.

### 11.1 Correlated journal records

Every 15m evaluation stores LONG/SHORT/NO_TRADE. Minimum DecisionRecord fields follow
`domain-models.md`; structured context includes current price, regime/evidence,
range location, both scores/components, decision/reason codes and all four versions.

Directional lifecycle additionally stores entry/stop/targets, quantity/leverage,
risk budget/worst loss/RR, reports/fills, gross PnL, fee breakdown, funding cash flow, net PnL
and exit reason. Free text only explains structured data.

Example semantics:

```text
symbol=BTC-USDT-SWAP
regime=SIDEWAY
range_location=MIDDLE
long_score=42
short_score=48
decision=NO_TRADE
reason_code=SIDEWAY_MIDDLE_RANGE
```

## 12. Error handling

- Expected domain rejection uses `Result`/typed outcome and canonical ReasonCode,
  not exception-driven control flow.
- Programming/invariant/IO failures use typed exceptions at boundary, translated once
  into health/state action and sanitized journal event.
- Unknown external outcome is not success/failure; enter recovery and query.
- No blanket catch-and-continue around risk/execution/journal.
- No secrets/raw credential values in error or structured context.
- Retry only declared idempotent reads/transport operations with bounded backoff;
  order submit never blind retry.

Full registry: `error-and-reason-codes.md`.

## 13. Versioning and reproducibility

Every DecisionRecord carries:

- `code_version`: immutable Git commit/build identifier; dirty build must be marked.
- `strategy_version`: algorithm/indicator initialization/component registry version.
- `config_version`: canonical merged non-secret config hash.
- `data_version`: immutable dataset/source/revision manifest hash.

Instrument and fee schedule versions are also persisted where sizing/PnL uses them.
Reproduction requires archived config, data manifest, code commit, prior range/state
events and deterministic clock/event ordering. Nếu không tái tạo được “tại sao LONG
tại thời điểm này”, run không đạt acceptance.

## 14. Testing strategy

- Unit: model validation, scoring boundaries, regime evidence, sizing/fees, reason codes.
- Property: Decimal risk invariants, symmetry, no future data, approved loss <= budget.
- State-machine: every allowed row + all invalid state/event combinations.
- Contract: real/simulated adapters conform ports; domain does not import SDK.
- Integration: SQLite atomicity/idempotency/restart recovery and write-before-submit.
- Scenario: SIDEWAY middle/edges, breakout-confirm/retest, stale/gap, partial fill,
  unknown order, protection failure, state mismatch, kill-switch reset.
- Replay/golden: same versions/input/events produce same serialized decisions.
- Backtest validation later: chronological split, walk-forward, holdout, costs/stress,
  regime-segmented metrics and no leakage.

## 15. Calibration and adapter inputs still required

Các mục sau là typed inputs/empirical values, không phải business logic để PHASE 3 tự
sáng tạo. Missing value phải fail startup theo `BACKTEST_REQUIRED` hoặc metadata
contract:

1. Chọn position/margin mode và cung cấp exact instrument metadata từ adapter fixture.
2. Điền periods/lookbacks, thresholds, weights, caps và cooldown trong versioned config,
   sau đó calibration bằng backtest; formulas và precedence đã cố định trong spec.
3. Cung cấp historical fee/funding/spread/slippage data hoặc conservative versioned
   scenario theo FeeModel contract.
4. Chọn historical dataset/source/depth và final holdout period, ghi bằng data version.
5. Quyết định có bật optional unrealized drawdown gate hay để explicit disabled; daily
   realized loss và session drawdown gates vẫn bắt buộc.

## 16. PHASE 2 acceptance criteria

| Criterion | Status | Evidence |
|---|---|---|
| PHASE 1 reviewed against all acceptance criteria | PASS | `phase-1-review.md` |
| Required models have types/nullability/validation/mutability/ownership | PASS | `domain-models.md` |
| Canonical enums defined without string duplication | PASS | `domain-models.md` §2 |
| Reason codes define category/severity/action/journal behavior | PASS | `error-and-reason-codes.md` |
| Typed config groups and dev/backtest classification defined | PASS | `configuration.md` |
| Market data timing/gap/dedupe/closed-candle/no-look-ahead defined | PASS | `market-data.md` |
| Indicator contract and warm-up fail closed | PASS | `market-data.md` §11–12 |
| Multi-evidence regime and SIDEWAY/retest rules defined | PASS | `regime-detection.md` |
| Explainable dual scoring and candidate gates defined | PASS | `strategy.md` |
| Stop-risk sizing, floor rounding, fees/funding/slippage defined | PASS | `position-sizing.md` |
| Ports/adapters specified without OKX dependency | PASS | This document §5 |
| Full state transition table and invalid transition behavior defined | PASS | This document §9 |
| Evaluation/order idempotency and unknown-submit recovery defined | PASS | This document §11 |
| Four-version reproducibility contract defined | PASS | This document §13 |
| Persistence/journal includes every NO_TRADE | PASS | This document §10–11 |
| Testing strategy covers safety-critical contracts | PASS | This document §14 |
| No API integration, orders, secrets, optimization or live enablement added | PASS | Repository scope review |

**PHASE 2: APPROVED — xem `phase-2-review.md`.**

Không tự động bắt đầu PHASE 3.
