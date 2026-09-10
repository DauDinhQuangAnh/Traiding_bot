# Domain Models — PHASE 2

## 1. Quy ước chung

- Đây là contract cho Python 3.12+, chưa phải implementation.
- `datetime` luôn timezone-aware UTC; datetime không timezone là invalid.
- `Decimal` dùng cho mọi price, quantity, notional, equity, PnL, fee, funding,
  spread, slippage và phép tính risk. Không chuyển qua `float`.
- ID là `str` không rỗng, sinh theo chiến lược deterministic/idempotent.
- Collection trong immutable model dùng `tuple` hoặc read-only `Mapping`.
- Enum serialize bằng canonical value; không dùng string rời rạc thay enum.
- Khi journal: Decimal serialize thành chuỗi thập phân, datetime thành ISO-8601 UTC.
- Validation lỗi làm object không được tạo; không tự fill dữ liệu giả.

## 2. Canonical enums

| Enum | Values |
|---|---|
| `Timeframe` | `M5`, `M15`, `H1` (wire values: `5m`, `15m`, `1h`) |
| `MarketRegime` | `TREND_UP`, `TREND_DOWN`, `SIDEWAY`, `HIGH_VOLATILITY`, `UNCERTAIN` |
| `TradeDecision` | `LONG`, `SHORT`, `NO_TRADE` |
| `TradeSide` | `LONG`, `SHORT` |
| `RiskAction` | `APPROVE`, `REJECT`, `HALT` |
| `BotState` | `STARTING`, `SYNCING`, `OBSERVING`, `EVALUATING`, `SUBMITTING`, `PENDING_ENTRY`, `MANAGING_POSITION`, `EXITING`, `COOLDOWN`, `RECOVERING`, `HALTED` |
| `TradeLifecycleState` | `CANDIDATE_CREATED`, `RISK_REVIEW`, `REJECTED`, `APPROVED`, `SUBMITTING`, `PENDING_ENTRY`, `OPEN`, `CLOSING`, `CLOSED`, `RECOVERY`, `HALTED` |
| `TradeLifecycleEvent` | `RISK_REVIEW_STARTED`, `RISK_REJECTED`, `RISK_APPROVED`, `RISK_HALT`, `ORDER_INTENT_PERSISTED`, `ORDER_ACKNOWLEDGED`, `ORDER_REJECTED`, `SUBMIT_OUTCOME_UNKNOWN`, `ENTRY_CANCELED_UNFILLED`, `ENTRY_FILLED_PROTECTED`, `PARTIAL_FILL`, `TAKE_PROFIT_FAILED`, `EXIT_TRIGGERED`, `STATE_UNCERTAIN`, `PROTECTION_FAILED`, `POSITION_CLOSED`, `EXIT_OUTCOME_UNKNOWN`, `RECONCILED_NO_FILL`, `RECONCILED_PENDING_ORDER`, `RECONCILED_PROTECTED_POSITION`, `RECONCILED_CLOSED`, `RECOVERY_FAILED` |
| `BotEvent` | `CONFIG_VALIDATED`, `STARTUP_VALIDATION_FAILED`, `SYNC_COMPLETED`, `SYNC_FAILED`, `CANDLE_CLOSED`, `LOSS_COOLDOWN_STARTED`, `HEALTH_CRITICAL`, `NO_TRADE`, `RISK_REJECTED`, `RISK_APPROVED`, `RISK_HALT`, `ORDER_ACKNOWLEDGED`, `ORDER_REJECTED`, `SUBMIT_OUTCOME_UNKNOWN`, `ENTRY_CANCELED_UNFILLED`, `ENTRY_FILLED_PROTECTED`, `PARTIAL_FILL_OR_PROTECTION_UNKNOWN`, `EXIT_TRIGGERED`, `STATE_UNCERTAIN`, `PROTECTION_FAILED`, `POSITION_CLOSED`, `EXIT_OUTCOME_UNKNOWN`, `RECONCILED_FLAT`, `RECONCILED_PROTECTED_POSITION`, `RECOVERY_FAILED`, `COOLDOWN_EXPIRED`, `RISK_REDUCING_ACTION`, `OPERATOR_RESET_REQUESTED` |
| `RangeLocation` | `NEAR_SUPPORT`, `MIDDLE`, `NEAR_RESISTANCE`, `OUTSIDE_RANGE` |
| `BreakoutState` | `NONE`, `BREAKOUT_DETECTED`, `WAIT_CONFIRMATION`, `WAIT_RETEST`, `RETEST_VALIDATED`, `INVALIDATED`, `EXPIRED` |
| `BreakoutDirection` | `UP`, `DOWN` |
| `LevelKind` | `SUPPORT`, `RESISTANCE`, `SWING_HIGH`, `SWING_LOW`, `RANGE_BOUNDARY` |
| `LevelMethod` | `SWING_CLUSTER`, `VOLUME_REACTION`, `MARKET_STRUCTURE`, `RANGE_MODEL` |
| `StructureTrend` | `BULLISH`, `BEARISH`, `MIXED`, `UNDETERMINED` |
| `StructurePointKind` | `HH`, `HL`, `LH`, `LL`, `SWING_HIGH`, `SWING_LOW` |
| `Severity` | `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `HealthStatus` | `HEALTHY`, `DEGRADED`, `UNHEALTHY`, `UNKNOWN` |
| `OrderStatus` | `INTENT_CREATED`, `SUBMITTED`, `ACKNOWLEDGED`, `PARTIALLY_FILLED`, `FILLED`, `CANCEL_PENDING`, `CANCELED`, `REJECTED`, `EXPIRED`, `UNKNOWN` |
| `PositionStatus` | `FLAT`, `OPENING`, `OPEN`, `CLOSING`, `CLOSED`, `UNRECONCILED` |
| `ExitReason` | `STOP_LOSS`, `TAKE_PROFIT`, `RISK_REDUCTION`, `EMERGENCY`, `MANUAL`, `UNKNOWN` |
| `LiquidityRole` | `MAKER`, `TAKER`, `UNKNOWN` |
| `OrderPurpose` | `ENTRY`, `STOP`, `TAKE_PROFIT`, `EXIT` |
| `OrderType` | `MARKET`, `LIMIT`, `STOP_MARKET`, `TAKE_PROFIT_MARKET` |
| `OrderDirection` | `BUY`, `SELL` |
| `SetupType` | `TREND_PULLBACK`, `SIDEWAY_MEAN_REVERSION`, `BREAKOUT_RETEST` |
| `EntryModel` | `CLOSE_REFERENCE` |
| `TargetModel` | `NEXT_OPPOSING_LEVEL` |
| `PositionMode` | `NET`, `LONG_SHORT` |
| `MarginMode` | `ISOLATED`, `CROSS` |
| `GapPolicy` | `BLOCK_AND_BACKFILL` |
| `PartialFillPolicy` | `PROTECT_FILLED_AND_CANCEL_REMAINDER` |
| `ProtectionFailurePolicy` | `CANCEL_REMAINDER_REDUCE_AND_HALT` |
| `TakeProfitFailurePolicy` | `RECOVER_THEN_REDUCE_AND_HALT` |
| `JournalBackend` | `SQLITE` |
| `SmoothingMethod` | `WILDER` |
| `VolumeStatistic` | `MEAN` |
| `DecimalRoundingMode` | `ROUND_HALF_EVEN` |
| `ExecutionEnvironment` | `BACKTEST`, `DEMO`, `LIVE` |
| `JournalEventType` | `DECISION_EVALUATED`, `RISK_EVALUATED`, `ORDER_INTENT_CREATED`, `ORDER_SUBMITTED`, `ORDER_ACKNOWLEDGED`, `FILL_RECEIVED`, `PROTECTION_CONFIRMED`, `POSITION_UPDATED`, `EXIT_COMPLETED`, `RECONCILIATION`, `DATA_CORRECTION`, `KILL_SWITCH_TRIGGERED`, `INVALID_TRANSITION` |

`ReasonCode` là enum theo canonical registry tại `error-and-reason-codes.md`.
`LIVE` tồn tại để configuration fail closed; PHASE 2 không implement live execution.

### 2.1 `TradeSide` khác `OrderDirection`

`TradeSide` mô tả exposure; `OrderDirection` mô tả thao tác mua/bán. Mapping canonical:

| Order purpose | LONG trade | SHORT trade |
|---|---|---|
| `ENTRY` | `BUY`, `reduce_only=false` | `SELL`, `reduce_only=false` |
| `STOP`, `TAKE_PROFIT`, `EXIT` | `SELL`, `reduce_only=true` | `BUY`, `reduce_only=true` |

OrderDirection không được suy diễn thành TradeSide nếu thiếu purpose/current position.

## 3. Auxiliary value objects

| Type | Fields | Validation |
|---|---|---|
| `VersionSet` | `code_version: str`, `strategy_version: str`, `config_version: str`, `data_version: str` | Tất cả bắt buộc, không rỗng |
| `Quote` | `symbol: str`, `source: str`, `bid: Decimal`, `ask: Decimal`, `event_time: datetime`, `receive_time: datetime` | `0 < bid <= ask`; UTC; non-empty identity |
| `IndicatorValues` | `ema20`, `ema50`, `ema200`, `ema20_slope_atr`, `ema50_slope_atr`, `ema200_slope_atr`, `rsi`, `rsi_slope`, `atr`, `atr_fraction`, `atr_percentile`, `adx`, `bb_upper`, `bb_middle`, `bb_lower`, `bb_width_fraction`, `bb_width_percentile`, `volume_mean`, `volume_ratio`: `Decimal` | Không NaN/infinite; ATR không âm; percentile/RSI/ADX trong `[0,100]`; bands có thứ tự |
| `StructurePoint` | `kind: StructurePointKind`, `price: Decimal`, `time: datetime`, `candle_id: str`, `confirmed_at: datetime` | Chỉ dùng candle đã đóng; `confirmed_at >= time`; UTC |
| `MarketStructure` | `trend: StructureTrend`, `points: tuple[StructurePoint,...]`, `as_of: datetime`, `reason_codes: tuple[ReasonCode,...]` | Point không sau `as_of`; UTC; immutable |
| `RegimeEvidence` | `name: str`, `supports: MarketRegime`, `strength: Decimal`, `observed_value: Decimal`, `unit: str`, `rule_version: str`, `source_ids: tuple[str,...]` | Strength `[0,1]`; stable registered name; immutable |
| `SignalEvidence` | `name: str`, `long_strength: Decimal`, `short_strength: Decimal`, `observed_value: Decimal`, `unit: str`, `source_ids: tuple[str,...]` | Strength `[0,1]`; stable registered name; immutable |
| `GateResult` | `gate_name: str`, `passed: bool`, `reason_code: ReasonCode?`, `observed_value: Decimal?`, `limit_value: Decimal?`, `unit: str?` | Failed gate phải có reason; stable registered name |
| `Target` | `label: str`, `price: Decimal`, `quantity_fraction: Decimal` | Giá dương; fraction `(0,1]`; parent plan kiểm tra tổng fractions bằng 1 |
| `ComponentHealth` | `component: str`, `status: HealthStatus`, `observed_at: datetime`, `reason_codes: tuple[ReasonCode,...]` | Một provider/repository chỉ báo health của chính nó; UTC; immutable |
| `HealthSnapshot` | `data_status`, `api_status`, `journal_status`, `account_status: HealthStatus`; `observed_at: datetime`; `reason_codes: tuple[ReasonCode,...]` | UTC; Risk chỉ approve khi cả bốn status là `HEALTHY` |
| `CostRateEstimate` | `entry_fee_rate`, `stop_exit_fee_rate`, `target_exit_fee_rate`, `entry_slippage_rate`, `stop_slippage_rate`, `target_slippage_rate`, `funding_debit_rate: Decimal`; `model_version: str` | Mọi rate không âm; slippage/spread không double count; immutable |
| `FeeBreakdown` | `entry_fee`, `exit_fee`, `spread_cost`, `slippage_cost`: `Decimal`; `funding_cash_flow: Decimal` | Costs không âm; funding signed: dương là credit, âm là debit; immutable |

## 4. Model contracts

Mọi field trong bảng là required tại construction; cột Nullable cho biết field có
thể mang `None`, không có nghĩa là có thể bỏ khỏi serialized record.

### 4.1 `Candle`

Responsibility: biểu diễn một OHLCV interval chuẩn hóa. Immutable.

Source: `market_data`. Consumers: store, snapshot builder, indicators, backtest.

| Field | Type | Nullable |
|---|---|---|
| `candle_id` | `str` | No |
| `symbol` | `str` | No |
| `timeframe` | `Timeframe` | No |
| `open_time`, `close_time` | `datetime` | No |
| `event_time`, `receive_time` | `datetime` | No |
| `open`, `high`, `low`, `close`, `volume` | `Decimal` | No |
| `is_closed` | `bool` | No |
| `source` | `str` | No |
| `data_version` | `str` | No |

Validation: price dương; volume không âm; `high >= max(open, close)`,
`low <= min(open, close)`, `high >= low`; `close_time > open_time`;
event/receive time UTC; `candle_id` unique theo source/symbol/timeframe/open time.

### 4.2 `MarketSnapshot`

Responsibility: input đa timeframe nhất quán cho một evaluation. Immutable.

Source: `market_data.snapshot_builder`. Consumers: indicators, regime, strategy, journal.

| Field | Type | Nullable |
|---|---|---|
| `snapshot_id`, `evaluation_id`, `symbol` | `str` | No |
| `as_of`, `created_at`, `entry_candle_close_time` | `datetime` | No |
| `candles_5m`, `candles_15m`, `candles_1h` | `tuple[Candle, ...]` | No |
| `quote` | `Quote` | Yes |
| `data_version` | `str` | No |
| `reason_codes` | `tuple[ReasonCode, ...]` | No |

Validation: chỉ chứa closed candles với `close_time <= as_of`; mỗi series liên tục,
đúng symbol/timeframe, tăng dần và không duplicate; trigger là close 15m. Validation
fail thì không tạo MarketSnapshot; builder trả typed failure để journal NO_TRADE.

### 4.3 `IndicatorSnapshot`

Responsibility: kết quả indicator point-in-time. Immutable.

Source: `indicators`. Consumers: regime, levels, strategy, journal.

| Field | Type | Nullable |
|---|---|---|
| `indicator_snapshot_id`, `market_snapshot_id`, `symbol` | `str` | No |
| `as_of` | `datetime` | No |
| `values_by_timeframe` | `Mapping[Timeframe, IndicatorValues]` | No |
| `is_ready` | `bool` | No |
| `missing_requirements` | `tuple[str, ...]` | No |
| `reason_codes` | `tuple[ReasonCode, ...]` | No |
| `versions` | `VersionSet` | No |

Validation: đủ đúng ba timeframe khi `is_ready=true`; không có NaN/infinite; `as_of`
khớp market snapshot. Không đủ warm-up thì `is_ready=false`, có
`INDICATOR_NOT_READY`, và không tạo giá trị giả.

### 4.4 `RegimeAssessment`

Responsibility: phân loại market regime bằng nhiều evidence. Immutable.

Source: `regime`. Consumers: strategy, risk, journal, analytics.

| Field | Type | Nullable |
|---|---|---|
| `assessment_id`, `indicator_snapshot_id`, `symbol` | `str` | No |
| `regime` | `MarketRegime` | No |
| `candidate_regime`, `previous_confirmed_regime` | `MarketRegime` | Yes |
| `candidate_scores` | `Mapping[MarketRegime, Decimal]` | No |
| `confidence` | `Decimal` | No |
| `evidence` | `tuple[RegimeEvidence, ...]` | No |
| `confirmation_count` | `int` | No |
| `reason_codes` | `tuple[ReasonCode, ...]` | No |
| `as_of` | `datetime` | No |
| `config_version`, `strategy_version` | `str` | No |

Validation: confidence và candidate scores `[0,1]`; score map có chính xác các keys
`TREND_UP`, `TREND_DOWN`, `SIDEWAY`, `HIGH_VOLATILITY` (`UNCERTAIN` chỉ là outcome);
confirmation count không âm;
evidence không rỗng cho regime xác định; evidence mâu thuẫn/không đủ phải cho
`UNCERTAIN`; không có direction side effect.

### 4.5 `RangeContext`

Responsibility: mô tả range SIDEWAY và state breakout/retest. Immutable snapshot;
state mới được tạo từ event, không mutate record cũ.

Source: `levels`. Consumers: regime, strategy, journal.

| Field | Type | Nullable |
|---|---|---|
| `range_id`, `symbol` | `str` | No |
| `support_level_id`, `resistance_level_id` | `str` | No |
| `support`, `resistance`, `range_width`, `range_mid`, `range_width_atr` | `Decimal` | No |
| `position_in_range` | `Decimal` | No |
| `range_started_at`, `last_validated_at`, `as_of` | `datetime` | No |
| `range_age_bars`, `support_tests`, `resistance_tests`, `breakout_confirmation_count` | `int` | No |
| `current_location` | `RangeLocation` | No |
| `breakout_state` | `BreakoutState` | No |
| `breakout_direction` | `BreakoutDirection` | Yes |
| `breakout_detected_at`, `state_updated_at`, `expires_at` | `datetime` | Yes |
| `reason_codes` | `tuple[ReasonCode, ...]` | No |
| `config_version`, `data_version` | `str` | No |

Validation: `0 < support < resistance`; `range_width = resistance - support`;
`range_mid = (support + resistance) / 2`; `position_in_range =
(reference_close - support) / range_width`; counts không âm; range không stale theo
config; direction/time bắt buộc khi breakout state khác `NONE`;
`SIDEWAY + MIDDLE` không được sinh candidate; `RETEST_VALIDATED` phải có chuỗi
event detect → confirmation → retest hợp lệ.

### 4.6 `Level`

Responsibility: một vùng giá có provenance. Immutable.

Source: `levels`. Consumers: `LevelSet`, strategy, stop/target planner.

| Field | Type | Nullable |
|---|---|---|
| `level_id`, `symbol` | `str` | No |
| `kind` | `LevelKind` | No |
| `price`, `zone_lower`, `zone_upper`, `strength` | `Decimal` | No |
| `method` | `LevelMethod` | No |
| `first_observed_at`, `confirmed_at`, `last_tested_at`, `as_of` | `datetime` | No |
| `test_count` | `int` | No |
| `source_candle_ids` | `tuple[str, ...]` | No |
| `invalidated_at` | `datetime` | Yes |

Validation: giá dương; `zone_lower <= price <= zone_upper`; strength `[0,1]`;
test count không âm; confirmation và invalidation không dùng dữ liệu sau `as_of`.

### 4.7 `LevelSet`

Responsibility: tập levels nhất quán tại một `as_of`. Immutable.

Source: `levels`. Consumers: regime, strategy, journal.

| Field | Type | Nullable |
|---|---|---|
| `level_set_id`, `market_snapshot_id`, `symbol` | `str` | No |
| `supports`, `resistances`, `swings` | `tuple[Level, ...]` | No |
| `range_context` | `RangeContext` | Yes |
| `market_structure` | `MarketStructure` | No |
| `as_of` | `datetime` | No |
| `config_version`, `data_version` | `str` | No |

Validation: tất cả child cùng symbol và không sau `as_of`; active supports nằm dưới
hoặc tại reference price, resistances ở trên hoặc tại reference price theo tolerance.

### 4.8 `SignalComponent`

Responsibility: điểm và evidence giải thích được của một factor. Immutable.

Source: `strategy.scoring`. Consumers: assessment, journal, analytics.

| Field | Type | Nullable |
|---|---|---|
| `component_name` | `str` | No |
| `long_points`, `short_points`, `max_points` | `Decimal` | No |
| `evidence` | `tuple[SignalEvidence, ...]` | No |
| `reason_codes` | `tuple[ReasonCode, ...]` | No |
| `config_version` | `str` | No |

Validation: points `[0,max_points]`; max points dương; tên thuộc configured registry;
component không tự phát hành decision.

### 4.9 `SignalAssessment`

Responsibility: tổng hợp score hai phía và gates. Immutable.

Source: `strategy.scoring`. Consumers: decision engine, journal.

| Field | Type | Nullable |
|---|---|---|
| `signal_assessment_id`, `evaluation_id` | `str` | No |
| `long_score`, `short_score` | `Decimal` | No |
| `components` | `tuple[SignalComponent, ...]` | No |
| `gates` | `tuple[GateResult, ...]` | No |
| `reason_codes` | `tuple[ReasonCode, ...]` | No |
| `as_of` | `datetime` | No |
| `versions` | `VersionSet` | No |

Validation: scores `[0,100]`; bằng tổng component tương ứng; tổng configured max là
100; không tự chọn phía chỉ vì score cao hơn.

### 4.10 `TradeCandidate`

Responsibility: trade plan chưa được phép execute. Immutable.

Source: `strategy.decision`. Consumers: risk, journal.

| Field | Type | Nullable |
|---|---|---|
| `candidate_id`, `evaluation_id`, `symbol` | `str` | No |
| `side` | `TradeSide` | No |
| `entry_price`, `stop_price` | `Decimal` | No |
| `targets` | `tuple[Target, ...]` | No |
| `planned_rr_before_costs`, `planned_rr_after_costs` | `Decimal` | No |
| `cost_rate_estimate` | `CostRateEstimate` | No |
| `setup_type` | `SetupType` | No |
| `entry_model` | `EntryModel` | No |
| `target_model` | `TargetModel` | No |
| `signal_assessment_id`, `regime_assessment_id` | `str` | No |
| `range_id` | `str` | Yes |
| `invalidation_level_id` | `str` | No |
| `target_level_ids` | `tuple[str, ...]` | No |
| `reason_codes` | `tuple[ReasonCode, ...]` | No |
| `created_at` | `datetime` | No |
| `versions` | `VersionSet` | No |

Validation: prices dương; stop đúng phía; targets không rỗng và đúng phía entry;
candidate không chứa quantity/leverage; regime không `UNCERTAIN/HIGH_VOLATILITY`;
SIDEWAY middle không được tạo candidate.

### 4.11 `RiskContext`

Responsibility: account/market/system snapshot nhất quán để risk evaluation. Immutable.

Source: risk context assembler. Consumers: risk engine, journal.

| Field | Type | Nullable |
|---|---|---|
| `risk_context_id`, `symbol`, `account_id` | `str` | No |
| `account_equity`, `eligible_equity`, `available_margin`, `current_notional`, `daily_net_pnl` | `Decimal` | No |
| `session_peak_equity`, `daily_drawdown_ratio` | `Decimal` | No |
| `daily_trade_count`, `consecutive_losses`, `open_position_count` | `int` | No |
| `cooldown_until` | `datetime` | Yes |
| `quote` | `Quote` | No |
| `position_state` | `PositionState` | No |
| `health` | `HealthSnapshot` | No |
| `kill_switch_active`, `account_reconciled` | `bool` | No |
| `observed_at` | `datetime` | No |
| `config_version`, `state_version` | `str` | No |

Validation: monetary values không âm trừ daily PnL; drawdown ratio `[0,1]`; counters không âm; quote/account/
health phải fresh theo config; approve bị cấm nếu kill switch active hoặc unreconciled.

### 4.12 `RiskDecision`

Responsibility: kết quả veto/approval có audit. Immutable.

Source: `risk`. Consumers: executor gate, state machine, journal.

| Field | Type | Nullable |
|---|---|---|
| `risk_decision_id`, `candidate_id`, `risk_context_id` | `str` | No |
| `action` | `RiskAction` | No |
| `reason_codes` | `tuple[ReasonCode, ...]` | No |
| `observed_limits` | `Mapping[str, Decimal]` | No |
| `risk_approval_id` | `str` | Yes |
| `approved_plan_id` | `str` | Yes |
| `evaluated_at`, `expires_at` | `datetime` | No |
| `config_version`, `state_version` | `str` | No |

Validation: APPROVE có approval/plan ID và không có hard-failure reason; REJECT/HALT
không có hai ID này; expiry sau evaluated time; HALT phát kill-switch event.

### 4.13 `ApprovedTradePlan`

Responsibility: payload duy nhất executor được nhận để mở vị thế. Immutable.

Source: `risk`. Consumers: execution, positions, journal.

| Field | Type | Nullable |
|---|---|---|
| `approved_plan_id`, `risk_approval_id`, `candidate_id`, `symbol` | `str` | No |
| `side` | `TradeSide` | No |
| `entry_price`, `stop_price`, `quantity`, `notional` | `Decimal` | No |
| `targets` | `tuple[Target, ...]` | No |
| `risk_budget`, `worst_case_loss`, `expected_rr` | `Decimal` | No |
| `leverage` | `Decimal` | No |
| `fee_estimate` | `FeeBreakdown` | No |
| `created_at`, `expires_at` | `datetime` | No |
| `config_version`, `state_version`, `instrument_version` | `str` | No |

Validation: quantity/notional dương và precision hợp lệ; worst-case loss không vượt
risk budget; leverage không vượt cap; stop/targets đúng phía; plan one-shot và có TTL.

### 4.14 `ExecutionReport`

Responsibility: canonical report cho order/fill lifecycle. Immutable event.

Source: execution adapter/simulator. Consumers: positions, journal, reconciliation.

| Field | Type | Nullable |
|---|---|---|
| `execution_report_id`, `client_order_id`, `approved_plan_id`, `symbol` | `str` | No |
| `exchange_order_id` | `str` | Yes |
| `status` | `OrderStatus` | No |
| `purpose` | `OrderPurpose` | No |
| `direction` | `OrderDirection` | No |
| `order_type` | `OrderType` | No |
| `reduce_only` | `bool` | No |
| `requested_quantity`, `cumulative_filled_quantity` | `Decimal` | No |
| `last_fill_quantity`, `last_fill_price`, `average_fill_price` | `Decimal` | Yes |
| `liquidity_role` | `LiquidityRole` | No |
| `fees`, `funding_cash_flow`, `realized_slippage` | `Decimal` | No |
| `event_time`, `receive_time` | `datetime` | No |
| `reason_codes` | `tuple[ReasonCode, ...]` | No |

Validation: fill quantities/fees/slippage không âm và cumulative không vượt requested
ngoài explicit exchange anomaly; funding cash flow signed; fill fields bắt buộc khi
có fill; direction phải map đúng purpose/TradeSide; event id/order id dùng dedupe.

### 4.15 `PositionState`

Responsibility: snapshot vị thế local đã/đang reconcile. Immutable snapshot.

Source: `positions`. Consumers: risk, execution, recovery, journal.

| Field | Type | Nullable |
|---|---|---|
| `position_id`, `symbol`, `state_version` | `str` | No |
| `status` | `PositionStatus` | No |
| `side` | `TradeSide` | Yes |
| `quantity`, `entry_price`, `mark_price`, `unrealized_pnl`, `realized_pnl` | `Decimal` | No |
| `stop_order_id`, `take_profit_order_id` | `str` | Yes |
| `stop_price`, `take_profit_price` | `Decimal` | Yes |
| `is_protected`, `is_reconciled` | `bool` | No |
| `opened_at`, `closed_at` | `datetime` | Yes |
| `as_of` | `datetime` | No |
| `last_execution_report_id` | `str` | Yes |

Validation: FLAT/CLOSED có quantity zero; OPEN có side, quantity/entry dương;
`is_protected=true` yêu cầu confirmed stop cho toàn bộ open quantity; unreconciled
state không được dùng để approve entry.

### 4.16 `DecisionRecord`

Responsibility: audit record cho mọi LONG/SHORT/NO_TRADE evaluation. Immutable,
append-only. Source: application/journal. Consumers: analytics, replay, audit.

| Field | Type | Nullable |
|---|---|---|
| `decision_record_id`, `evaluation_id`, `symbol` | `str` | No |
| `timestamp`, `as_of` | `datetime` | No |
| `current_price` | `Decimal` | Yes |
| `regime`, `decision` | `MarketRegime`, `TradeDecision` | No |
| `range_location` | `RangeLocation` | Yes |
| `long_score`, `short_score` | `Decimal` | Yes |
| `reason_codes` | `tuple[ReasonCode, ...]` | No |
| `human_explanation` | `str` | Yes |
| `market_snapshot_id`, `indicator_snapshot_id`, `regime_assessment_id`, `signal_assessment_id` | `str` | Yes |
| `candidate_id`, `risk_decision_id`, `trade_id` | `str` | Yes |
| `versions` | `VersionSet` | No |

Validation: NO_TRADE phải có ít nhất một reason code và không cần candidate; fields
chưa tới stage tương ứng phải null, không điền zero/fake ID. LONG/SHORT phải có đầy
đủ snapshot/assessment/candidate; free text không được dùng làm branching logic.

### 4.17 `TradeLifecycle`

Responsibility: aggregate liên kết evaluation → risk → orders → position → exit.
Mutable chỉ thông qua validated domain events; mỗi persisted revision là immutable.

Source: application/positions. Consumers: risk counters, journal, analytics, recovery.

| Field | Type | Nullable |
|---|---|---|
| `trade_id`, `evaluation_id`, `candidate_id`, `symbol` | `str` | No |
| `risk_decision_id`, `risk_approval_id`, `approved_plan_id` | `str` | Yes |
| `side` | `TradeSide` | No |
| `state` | `TradeLifecycleState` | No |
| `position_id` | `str` | Yes |
| `client_order_ids`, `execution_report_ids` | `tuple[str, ...]` | No |
| `opened_at`, `closed_at` | `datetime` | Yes |
| `gross_pnl`, `net_pnl` | `Decimal` | Yes |
| `fees` | `FeeBreakdown` | No |
| `exit_reason` | `ExitReason` | Yes |
| `revision` | `int` | No |
| `versions` | `VersionSet` | No |

Validation: IDs đã có không đổi suốt lifecycle; approval/plan chỉ có sau event APPROVED;
REJECTED trực tiếp từ risk review không có approval/plan, còn execution reject sau
approval phải giữ chúng để audit; revision tăng đơn điệu; net PnL chỉ có khi CLOSED và
bằng gross trừ costs cộng signed funding cash flow; transition chỉ theo lifecycle contract.
Trước settlement, `fees` là zero instance có các cost bằng zero, không phải `None`.

## 5. Ownership và mutation policy

- Domain object không gọi provider/repository và không biết OKX schema.
- Modules trao đổi object bằng return value/domain event, không dùng global mutable state.
- `PositionState`, `RangeContext` và `TradeLifecycle` thay đổi theo thời gian bằng cách
  áp event để tạo revision/snapshot mới; lịch sử cũ không bị overwrite.
- Repository kiểm soát optimistic concurrency bằng `revision/state_version`.
- Không module nào ngoài Risk Engine được tạo `RiskDecision` hoặc
  `ApprovedTradePlan`; không module nào ngoài Decision Engine được tạo candidate.

## 6. Cross-model invariants

1. Tất cả object trong một evaluation cùng symbol, `as_of` và version set tương thích.
2. `evaluation_id` duy nhất cho tuple symbol + entry candle close + strategy/config version.
3. `candidate_id` chỉ tồn tại cho directional decision; NO_TRADE không có candidate.
4. Approval tham chiếu đúng candidate/context và chưa hết hạn tại lúc submit.
5. Một approval chỉ tạo tối đa một logical entry order, bất kể retry/network timeout.
6. Position open phải có trade lifecycle và protection được xác nhận hoặc hệ thống halt.
7. Journal event không bị xóa/sửa; correction là event mới có reference tới event cũ.
8. Decision replay phải xác định được code, strategy, config và data version đã dùng.
