# Typed Configuration Specification — PHASE 2

## 1. Mục tiêu

Configuration là input có version của deterministic pipeline. Cấu hình sai hoặc thiếu
phải fail closed trước `OBSERVING`; không có fallback ngầm cho risk-critical field.
PHASE 2 chỉ định schema, không tạo config thực và không bật live trading.

Mỗi field thuộc một trong hai lớp:

- `DEFAULT_FOR_DEVELOPMENT`: giá trị vận hành/kỹ thuật an toàn, không tuyên bố tạo edge.
- `BACKTEST_REQUIRED`: numerical strategy/risk threshold chưa được chứng minh; phải
  khai báo rõ cho experiment và không được mô tả là tối ưu.

## 2. File layering

```text
config/base.yaml     # schema-compatible common settings
config/demo.yaml     # overlay cho OKX Demo, không chứa secrets
config/live.yaml     # fail-closed placeholder; execution disabled
```

Merge order: `base.yaml` → environment overlay → environment variables chỉ dành cho
secret/explicit safety switch. Unknown key là validation error. Deep merge chỉ theo
object key; list được replace toàn bộ, không nối ngầm.

`app_config_version = sha256(canonical_merged_config_without_secrets)` (the existing
`VersionSet.config_version`). Canonical form
sort key, giữ Decimal dưới dạng string và normalize duration/timeframe. Secrets không
đi vào hash, log hoặc journal. Historical dataset identity uses the narrower
`historical_semantics_version` documented in `historical-data.md`; strategy/risk
changes must not churn data versions.

## 3. Top-level schema

| Group | Responsibility |
|---|---|
| `market` | Instrument, environment, account/margin assumptions |
| `calculation` | Decimal arithmetic context và canonical rounding |
| `strategy` | Score components, gates, entry/target behavior |
| `indicators` | Indicator algorithms, periods, warm-up và derived fields |
| `regime` | Multi-evidence regime candidates/conflict policy |
| `levels` | S/R, range, structure, breakout/retest parameters |
| `risk` | Risk budget, caps, limits, stop/RR policy |
| `execution` | Dry-run, approval TTL, timeout, partial-fill/emergency policy |
| `protection` | Stop/TP validation và failure actions |
| `data` | Timeframes, warm-up, freshness, gap/backfill policy |
| `historical` | Offline parser, normalization, mapping and dataset policies |
| `journal` | SQLite path, append/audit behavior, retention |
| `monitoring` | Health thresholds, alerts, reconciliation cadence |

## 4. Field specification

Notation: `DecimalRatio` là Decimal trong `[0,1]` trừ khi field ghi khác;
`Duration` serialize ISO-8601 hoặc chuỗi có unit được parser kiểm tra.

### 4.1 `market`

| Key | Type | Class | Validation/meaning |
|---|---|---|---|
| `market.symbol` | `str` | DEFAULT_FOR_DEVELOPMENT | `BTC-USDT-SWAP`; non-empty |
| `market.environment` | `ExecutionEnvironment` | DEFAULT_FOR_DEVELOPMENT | Chỉ `BACKTEST` hoặc `DEMO` được phép trong MVP |
| `market.quote_currency` | `str` | DEFAULT_FOR_DEVELOPMENT | `USDT`; phải khớp instrument metadata |
| `market.position_mode` | `PositionMode` | BACKTEST_REQUIRED | `NET` hoặc `LONG_SHORT`; cần chốt trước adapter |
| `market.margin_mode` | `MarginMode` | BACKTEST_REQUIRED | `ISOLATED` hoặc `CROSS`; cần chốt trước adapter |
| `market.timezone` | IANA timezone | DEFAULT_FOR_DEVELOPMENT | `UTC`; chỉ dùng presentation/session declaration, storage vẫn UTC |

### 4.2 `calculation`

| Key | Type | Class | Validation/meaning |
|---|---|---|---|
| `calculation.decimal_precision` | `int` | DEFAULT_FOR_DEVELOPMENT | `34`; phải `>= 28`, áp cho domain calculations trước serialization |
| `calculation.rounding_mode` | `DecimalRoundingMode` | DEFAULT_FOR_DEVELOPMENT | `ROUND_HALF_EVEN`; exchange quantization vẫn dùng adverse rules riêng |

### 4.3 `strategy`

| Key | Type | Class | Validation/meaning |
|---|---|---|---|
| `strategy.version` | `str` | DEFAULT_FOR_DEVELOPMENT | SemVer hoặc immutable experiment ID |
| `strategy.long_threshold` | `Decimal` | BACKTEST_REQUIRED | `(0,100]` |
| `strategy.short_threshold` | `Decimal` | BACKTEST_REQUIRED | `(0,100]` |
| `strategy.minimum_score_difference` | `Decimal` | BACKTEST_REQUIRED | `[0,100]` |
| `strategy.component_max_points` | `Mapping[SignalComponentName, Decimal]` | BACKTEST_REQUIRED | Chính xác sáu enum keys; không âm, tổng đúng 100 |
| `strategy.component_evidence_weights` | `Mapping[SignalComponentName, Mapping[str, Decimal]]` | BACKTEST_REQUIRED | Exact evidence registry dưới bảng; mỗi enabled component có weights không âm, tổng 1 |
| `strategy.minimum_nonzero_components` | `int` | BACKTEST_REQUIRED | Minimum confluence; trong `[1,6]` |
| `strategy.allowed_setups` | `set[SetupType]` | BACKTEST_REQUIRED | Subset enum; không dùng free string |
| `strategy.entry_model` | `EntryModel` | DEFAULT_FOR_DEVELOPMENT | MVP: `CLOSE_REFERENCE` |
| `strategy.target_model` | `TargetModel` | DEFAULT_FOR_DEVELOPMENT | MVP: `NEXT_OPPOSING_LEVEL` |
| `strategy.trend_pullback_tolerance_atr` | `Decimal` | BACKTEST_REQUIRED | Dương; khoảng cách close tới EMA/structure |
| `strategy.stop.atr_buffer` | `Decimal` | BACKTEST_REQUIRED | Không âm; buffer Strategy dùng để dựng candidate stop quanh structural anchor |
| `strategy.level_full_strength_distance_atr` | `Decimal` | BACKTEST_REQUIRED | Không âm, `< level_zero_strength_distance_atr` |
| `strategy.level_zero_strength_distance_atr` | `Decimal` | BACKTEST_REQUIRED | Dương |
| `strategy.momentum.rsi_bands` | `Mapping[SetupType, DirectionalRsiBand]` | BACKTEST_REQUIRED | Chính xác ba setup keys; mỗi band có `long_min`, `long_max`, `short_min`, `short_max` trong `[0,100]`, min `<=` max |
| `strategy.momentum.rsi_slope_full` | `Decimal` | BACKTEST_REQUIRED | Dương; symmetric long/short magnitude |
| `strategy.volume.ratio_start` | `Decimal` | BACKTEST_REQUIRED | Không âm |
| `strategy.volume.ratio_full` | `Decimal` | BACKTEST_REQUIRED | Lớn hơn `ratio_start` |
| `strategy.confirmation.minimum_body_fraction` | `DecimalRatio` | BACKTEST_REQUIRED | Candle body/range lower bound |
| `strategy.confirmation.minimum_rejection_wick_fraction` | `DecimalRatio` | BACKTEST_REQUIRED | Wick/range lower bound |
| `strategy.confirmation.long_close_location_min` | `DecimalRatio` | BACKTEST_REQUIRED | Close location lower bound |
| `strategy.confirmation.short_close_location_max` | `DecimalRatio` | BACKTEST_REQUIRED | Close location upper bound |
| `strategy.high_volatility_enabled` | `bool` | DEFAULT_FOR_DEVELOPMENT | Phải `false`; bật yêu cầu strategy/backtest riêng |

Canonical evidence registry: `TREND` dùng đúng `regime_alignment`, `ema_alignment`,
`pullback`; `MOMENTUM` dùng `rsi`, `rsi_slope`; `STRUCTURE` dùng
`market_structure`; `LEVEL` dùng `proximity`; `VOLUME` dùng `volume_ratio`;
`CONFIRMATION` dùng `closed_candle`. Thiếu/thừa component hoặc evidence key là config
error, không tự normalize. Disabled component vẫn hiện diện với max points bằng zero;
evidence weights của nó phải là empty mapping.

### 4.4 `indicators`

| Key | Type | Class | Validation/meaning |
|---|---|---|---|
| `indicators.ema.periods` | `tuple[int,int,int]` | DEFAULT_FOR_DEVELOPMENT | Chính xác `[20,50,200]`, tăng dần |
| `indicators.ema.slope_lookback_bars` | `int` | BACKTEST_REQUIRED | Positive |
| `indicators.ema.stabilization_bars` | `int` | BACKTEST_REQUIRED | Non-negative; cộng EMA200 warm-up |
| `indicators.rsi.period` | `int` | BACKTEST_REQUIRED | Positive |
| `indicators.rsi.method` | `SmoothingMethod` | DEFAULT_FOR_DEVELOPMENT | `WILDER`; đổi method đổi strategy version |
| `indicators.rsi.slope_lookback_bars` | `int` | BACKTEST_REQUIRED | Positive |
| `indicators.atr.period` | `int` | BACKTEST_REQUIRED | Positive |
| `indicators.atr.method` | `SmoothingMethod` | DEFAULT_FOR_DEVELOPMENT | `WILDER` |
| `indicators.atr.percentile_lookback_bars` | `int` | BACKTEST_REQUIRED | Positive và lớn hơn ATR period |
| `indicators.adx.period` | `int` | BACKTEST_REQUIRED | Positive |
| `indicators.adx.method` | `SmoothingMethod` | DEFAULT_FOR_DEVELOPMENT | `WILDER` |
| `indicators.bollinger.period` | `int` | BACKTEST_REQUIRED | Positive |
| `indicators.bollinger.stddev_multiplier` | `Decimal` | BACKTEST_REQUIRED | Dương |
| `indicators.bollinger.percentile_lookback_bars` | `int` | BACKTEST_REQUIRED | Positive và lớn hơn band period |
| `indicators.volume.lookback_bars` | `int` | BACKTEST_REQUIRED | Positive |
| `indicators.volume.statistic` | `VolumeStatistic` | DEFAULT_FOR_DEVELOPMENT | `MEAN`; zero mean → indicator invalid |

### 4.5 `regime`

| Key | Type | Class | Validation/meaning |
|---|---|---|---|
| `regime.minimum_evidence_count` | `int` | BACKTEST_REQUIRED | `>= 2`; tránh single-indicator rule |
| `regime.minimum_evidence_strength` | `DecimalRatio` | BACKTEST_REQUIRED | `(0,1]`; evidence được đếm khi strength `>=` giá trị này |
| `regime.minimum_confidence` | `DecimalRatio` | BACKTEST_REQUIRED | `(0,1]`; dưới mức này → `UNCERTAIN` |
| `regime.minimum_candidate_margin` | `DecimalRatio` | BACKTEST_REQUIRED | Margin tối thiểu khi trend/range cùng eligible |
| `regime.conflict_tolerance` | `DecimalRatio` | BACKTEST_REQUIRED | `(0,1]`; cả hai directional scores đạt ngưỡng → `UNCERTAIN` |
| `regime.required_confirmations` | `int` | BACKTEST_REQUIRED | `> 0` consecutive candidate evaluations |
| `regime.timeframe_weights` | `Mapping[Timeframe, Decimal]` | BACKTEST_REQUIRED | Chính xác keys `M15`, `H1`; không âm, tổng 1 |
| `regime.trend_candidate_threshold` | `DecimalRatio` | BACKTEST_REQUIRED | `(0,1]`; áp đối xứng UP/DOWN |
| `regime.sideway_candidate_threshold` | `DecimalRatio` | BACKTEST_REQUIRED | `(0,1]` |
| `regime.high_volatility_candidate_threshold` | `DecimalRatio` | BACKTEST_REQUIRED | `(0,1]`; được evaluate trước các regime khác |
| `regime.weights.trend` | `Mapping[str, Decimal]` | BACKTEST_REQUIRED | Keys: ema, slope, adx, structure, price_location; không âm, tổng 1 |
| `regime.weights.sideway` | `Mapping[str, Decimal]` | BACKTEST_REQUIRED | Keys: range, ema_compression, slope_flatness, adx_weakness, bounded_structure; tổng 1 |
| `regime.weights.high_volatility` | `Mapping[str, Decimal]` | BACKTEST_REQUIRED | Keys: atr_percentile, bb_width_percentile, true_range_shock; tổng 1 |
| `regime.adx.trend_start` | `Decimal` | BACKTEST_REQUIRED | `[0,100)` |
| `regime.adx.trend_full` | `Decimal` | BACKTEST_REQUIRED | `(0,100]`; lớn hơn `trend_start` |
| `regime.adx.sideway_full` | `Decimal` | BACKTEST_REQUIRED | `[0,100)` |
| `regime.adx.sideway_zero` | `Decimal` | BACKTEST_REQUIRED | `(0,100]`; lớn hơn `sideway_full` |
| `regime.ema.minimum_slope_atr` | `Decimal` | BACKTEST_REQUIRED | Dương; symmetric direction |
| `regime.ema.full_slope_atr` | `Decimal` | BACKTEST_REQUIRED | Lớn hơn minimum |
| `regime.ema.maximum_sideway_slope_atr` | `Decimal` | BACKTEST_REQUIRED | Dương |
| `regime.ema.maximum_sideway_dispersion_atr` | `Decimal` | BACKTEST_REQUIRED | Dương |
| `regime.price_location_tolerance_atr` | `Decimal` | BACKTEST_REQUIRED | Không âm |
| `regime.high_volatility.atr_percentile_start` | `Decimal` | BACKTEST_REQUIRED | `[0,100)` |
| `regime.high_volatility.atr_percentile_full` | `Decimal` | BACKTEST_REQUIRED | `(0,100]`; lớn hơn start |
| `regime.high_volatility.bb_percentile_start` | `Decimal` | BACKTEST_REQUIRED | `[0,100)` |
| `regime.high_volatility.bb_percentile_full` | `Decimal` | BACKTEST_REQUIRED | `(0,100]`; lớn hơn start |
| `regime.high_volatility.true_range_atr_start` | `Decimal` | BACKTEST_REQUIRED | Dương |
| `regime.high_volatility.true_range_atr_full` | `Decimal` | BACKTEST_REQUIRED | Lớn hơn start |

### 4.6 `levels`

| Key | Type | Class | Validation/meaning |
|---|---|---|---|
| `levels.lookback_bars` | `Mapping[Timeframe, int]` | BACKTEST_REQUIRED | Chính xác keys `M5`, `M15`, `H1`; mỗi value positive |
| `levels.structure_timeframe` | `Timeframe` | DEFAULT_FOR_DEVELOPMENT | `M15` cho canonical `MarketStructure` V1 |
| `levels.swing_left_bars` | `int` | BACKTEST_REQUIRED | Positive |
| `levels.swing_right_bars` | `int` | BACKTEST_REQUIRED | Positive; pivot usable only after this many closed bars |
| `levels.structure_comparison_tolerance_atr` | `Decimal` | BACKTEST_REQUIRED | Không âm; so sánh HH/HL/LH/LL, tách khỏi cluster distance |
| `levels.minimum_touches` | `int` | BACKTEST_REQUIRED | `>= 2` |
| `levels.full_strength_touches` | `int` | BACKTEST_REQUIRED | `>= minimum_touches`; strength đạt 1 tại count này |
| `levels.level_merge_distance_atr` | `Decimal` | BACKTEST_REQUIRED | Dương; clustering distance |
| `levels.zone_half_width_atr` | `Decimal` | BACKTEST_REQUIRED | Không âm; S/R tolerance |
| `levels.minimum_level_strength` | `DecimalRatio` | BACKTEST_REQUIRED | Dưới mức này không đưa vào active set |
| `levels.support_zone_max_fraction` | `DecimalRatio` | BACKTEST_REQUIRED | Upper bound của normalized support zone |
| `levels.resistance_zone_min_fraction` | `DecimalRatio` | BACKTEST_REQUIRED | Lower bound resistance; lớn hơn support max |
| `levels.outside_tolerance_fraction` | `DecimalRatio` | BACKTEST_REQUIRED | Tolerance quanh `[0,1]` trước breakout |
| `levels.minimum_range_width_atr` | `Decimal` | BACKTEST_REQUIRED | Dương; minimum geometric width, RR after costs kiểm riêng |
| `levels.maximum_range_stale_bars` | `int` | BACKTEST_REQUIRED | Positive; quá hạn → RANGE_STALE |
| `levels.breakout_buffer_atr` | `Decimal` | BACKTEST_REQUIRED | Detect, không phải entry trigger |
| `levels.breakout_confirmation_bars` | `int` | BACKTEST_REQUIRED | Positive subsequent closed 15m bars |
| `levels.breakout_hold_tolerance_atr` | `Decimal` | BACKTEST_REQUIRED | Không âm; confirmation close guard |
| `levels.retest_tolerance_atr` | `Decimal` | BACKTEST_REQUIRED | Không âm; boundary touch/hold zone |
| `levels.retest_expiry_bars` | `int` | BACKTEST_REQUIRED | Positive; hết hạn → NO_TRADE |

### 4.7 `risk`

| Key | Type | Class | Validation/meaning |
|---|---|---|---|
| `risk.risk_per_trade` | `DecimalRatio` | BACKTEST_REQUIRED | `0 < value < 1` |
| `risk.target_leverage` | `Decimal` | BACKTEST_REQUIRED | `>= 1` và `<= max_leverage`; chỉ margin planning |
| `risk.max_leverage` | `Decimal` | BACKTEST_REQUIRED | `>= 1`; hard cap, không phải sizing input |
| `risk.max_position_notional` | `Decimal` | BACKTEST_REQUIRED | USDT dương |
| `risk.max_total_exposure` | `Decimal` | BACKTEST_REQUIRED | `>= max_position_notional` cho single symbol |
| `risk.max_daily_loss` | `Decimal` | BACKTEST_REQUIRED | Positive absolute USDT; trigger khi daily realized net PnL `<= -limit` |
| `risk.max_daily_drawdown` | `DecimalRatio` | BACKTEST_REQUIRED | Drawdown từ session peak equity; chạm limit → HALT |
| `risk.max_daily_trades` | `int` | BACKTEST_REQUIRED | Positive; tăng một lần tại first non-zero fill mỗi lifecycle |
| `risk.max_consecutive_losses` | `int` | BACKTEST_REQUIRED | Positive |
| `risk.minimum_rr` | `Decimal` | BACKTEST_REQUIRED | Dương; net-of-estimated-costs |
| `risk.max_allowed_spread` | `DecimalRatio` | BACKTEST_REQUIRED | Dương |
| `risk.max_slippage` | `DecimalRatio` | BACKTEST_REQUIRED | Dương |
| `risk.cooldown_after_loss` | `Duration` | BACKTEST_REQUIRED | Không âm; persisted |
| `risk.daily_reset_timezone` | IANA timezone | DEFAULT_FOR_DEVELOPMENT | UTC được chọn cho development |
| `risk.max_open_positions` | `int` | DEFAULT_FOR_DEVELOPMENT | Một cho MVP; positive |
| `risk.stop.min_distance_atr` | `Decimal` | BACKTEST_REQUIRED | Dương |
| `risk.stop.max_distance_atr` | `Decimal` | BACKTEST_REQUIRED | Lớn hơn min |
| `risk.stop.minimum_tick_multiple` | `Decimal` | BACKTEST_REQUIRED | `>= 1` |
| `risk.stop.minimum_spread_multiple` | `Decimal` | BACKTEST_REQUIRED | Dương |
| `risk.margin_buffer_ratio` | `DecimalRatio` | BACKTEST_REQUIRED | Reserve margin, `< 1` |
| `risk.funding_buffer_intervals` | `int` | BACKTEST_REQUIRED | Non-negative |
| `risk.unrealized_drawdown_gate.enabled` | `bool` | BACKTEST_REQUIRED | Explicit true/false; không có implicit enablement |
| `risk.unrealized_drawdown_gate.max_ratio` | `DecimalRatio?` | BACKTEST_REQUIRED | Bắt buộc `(0,1]` khi enabled; phải null khi disabled; không thay daily realized limit |

### 4.8 `execution`

| Key | Type | Class | Validation/meaning |
|---|---|---|---|
| `execution.enabled` | `bool` | DEFAULT_FOR_DEVELOPMENT | `false` trong PHASE 2 |
| `execution.dry_run` | `bool` | DEFAULT_FOR_DEVELOPMENT | `true` trong PHASE 2 |
| `execution.enable_live_trading` | `bool` | DEFAULT_FOR_DEVELOPMENT | Luôn `false`; env `ENABLE_LIVE_TRADING` cũng phải false |
| `execution.approval_ttl` | `Duration` | BACKTEST_REQUIRED | Positive; hết hạn phải re-evaluate |
| `execution.submit_timeout` | `Duration` | BACKTEST_REQUIRED | Positive; timeout → query-before-retry |
| `execution.cancel_timeout` | `Duration` | BACKTEST_REQUIRED | Positive |
| `execution.price_deviation_tolerance` | `DecimalRatio` | BACKTEST_REQUIRED | Revalidate reference vs current executable price |
| `execution.partial_fill_policy` | `PartialFillPolicy` | DEFAULT_FOR_DEVELOPMENT | Phải `PROTECT_FILLED_AND_CANCEL_REMAINDER` |
| `execution.max_query_retries` | `int` | BACKTEST_REQUIRED | Bounded query/reconcile retries; non-negative |
| `execution.retry_delay` | `Duration` | BACKTEST_REQUIRED | Positive; chỉ idempotent query/transport retry |
| `execution.retry_backoff_multiplier` | `Decimal` | BACKTEST_REQUIRED | `>= 1`; bounded by max retry delay |
| `execution.max_retry_delay` | `Duration` | BACKTEST_REQUIRED | `>= retry_delay` |

`risk.max_slippage` là canonical slippage tolerance mà execution revalidation dùng;
không tạo key execution khác cùng semantics.

### 4.9 `protection`

| Key | Type | Class | Validation/meaning |
|---|---|---|---|
| `protection.stop_order_type` | `OrderType` | DEFAULT_FOR_DEVELOPMENT | `STOP_MARKET`; reduce-only |
| `protection.take_profit_order_type` | `OrderType` | DEFAULT_FOR_DEVELOPMENT | `TAKE_PROFIT_MARKET`; reduce-only |
| `protection.ack_timeout` | `Duration` | BACKTEST_REQUIRED | Positive; timeout → query, không submit blind |
| `protection.require_stop_before_managing` | `bool` | DEFAULT_FOR_DEVELOPMENT | Phải true |
| `protection.stop_failure_policy` | `ProtectionFailurePolicy` | DEFAULT_FOR_DEVELOPMENT | `CANCEL_REMAINDER_REDUCE_AND_HALT` |
| `protection.take_profit_failure_policy` | `TakeProfitFailurePolicy` | DEFAULT_FOR_DEVELOPMENT | `RECOVER_THEN_REDUCE_AND_HALT` |
| `protection.max_recovery_attempts` | `int` | BACKTEST_REQUIRED | Non-negative, bounded |

### 4.10 `data`

| Key | Type | Class | Validation/meaning |
|---|---|---|---|
| `data.timeframes.micro` | `Timeframe` | DEFAULT_FOR_DEVELOPMENT | `5m` |
| `data.timeframes.entry` | `Timeframe` | DEFAULT_FOR_DEVELOPMENT | `15m`; evaluation trigger |
| `data.timeframes.context` | `Timeframe` | DEFAULT_FOR_DEVELOPMENT | `1h`; closed only |
| `data.history_bars.5m` | `int` | BACKTEST_REQUIRED | `>=` derived 5m warm-up requirement |
| `data.history_bars.15m` | `int` | BACKTEST_REQUIRED | `>=` derived 15m warm-up requirement |
| `data.history_bars.1h` | `int` | BACKTEST_REQUIRED | `>=` derived 1h warm-up requirement |
| `data.warmup_candles.5m` | `int` | BACKTEST_REQUIRED | Derived/validated, explicit for 5m |
| `data.warmup_candles.15m` | `int` | BACKTEST_REQUIRED | Derived/validated, explicit for 15m |
| `data.warmup_candles.1h` | `int` | BACKTEST_REQUIRED | Derived/validated, explicit for 1h |
| `data.freshness.candle_5m` | `Duration` | BACKTEST_REQUIRED | Positive 5m stream SLA |
| `data.freshness.candle_15m` | `Duration` | BACKTEST_REQUIRED | Positive 15m stream SLA |
| `data.freshness.candle_1h` | `Duration` | BACKTEST_REQUIRED | Positive 1h stream SLA |
| `data.freshness.quote` | `Duration` | BACKTEST_REQUIRED | Positive quote SLA |
| `data.freshness.account` | `Duration` | BACKTEST_REQUIRED | Positive account SLA |
| `data.freshness.position` | `Duration` | BACKTEST_REQUIRED | Positive position SLA |
| `data.freshness.instrument_metadata` | `Duration` | BACKTEST_REQUIRED | Positive metadata SLA |
| `data.gap_policy` | `GapPolicy` | DEFAULT_FOR_DEVELOPMENT | `BLOCK_AND_BACKFILL`; không fill synthetic |
| `data.ordering_window` | `Duration` | BACKTEST_REQUIRED | Non-negative receive delay buffer |
| `data.max_backfill_attempts` | `int` | BACKTEST_REQUIRED | Non-negative; vượt → unhealthy/halt policy |
| `data.clock_drift_tolerance` | `Duration` | BACKTEST_REQUIRED | Non-negative |
| `data.store_raw` | `bool` | DEFAULT_FOR_DEVELOPMENT | True cho reproducibility; raw immutable |

### 4.11 `historical`

| Key | Type | Class | Validation/meaning |
|---|---|---|---|
| `historical.raw_format` | `HistoricalRawFormat` | DEFAULT_FOR_DEVELOPMENT | PHASE 4: `CSV` only; never inferred from path |
| `historical.source_name` | `str` | DEFAULT_FOR_DEVELOPMENT | Stable non-empty logical source, not an absolute path |
| `historical.symbol_mapping` | `Mapping[str,str]` | DEFAULT_FOR_DEVELOPMENT | Explicit source → `BTC-USDT-SWAP`; unknown rejects |
| `historical.timeframe_mapping` | `Mapping[str,Timeframe]` | DEFAULT_FOR_DEVELOPMENT | Explicit source values; no duration heuristic |
| `historical.column_mapping` | `Mapping[str,str]` | DEFAULT_FOR_DEVELOPMENT | Exact raw schema registry for timestamp/OHLCV/symbol/timeframe/closed |
| `historical.timestamp_convention` | `TimestampConvention` | DEFAULT_FOR_DEVELOPMENT | `OPEN_TIME` or `CLOSE_TIME` |
| `historical.timestamp_unit` | `TimestampUnit` | DEFAULT_FOR_DEVELOPMENT | `ISO8601`, `UNIX_SECONDS` or `UNIX_MILLISECONDS`; no guessing |
| `historical.closed_values` | `set[str]` | DEFAULT_FOR_DEVELOPMENT | Explicit accepted source close-status strings |
| `historical.conflict_policy` | `HistoricalConflictPolicy` | DEFAULT_FOR_DEVELOPMENT | PHASE 4 requires `FAIL` |
| `historical.gap_policy` | `HistoricalGapPolicy` | DEFAULT_FOR_DEVELOPMENT | PHASE 4 requires `FAIL`; no synthetic fill |
| `historical.canonical_timeframe` | `Timeframe` | DEFAULT_FOR_DEVELOPMENT | Must be `5m`; M15/H1 derived |
| `historical.parser_version` | `str` | DEFAULT_FOR_DEVELOPMENT | Non-empty; semantic change changes data version |
| `historical.normalization_version` | `str` | DEFAULT_FOR_DEVELOPMENT | Non-empty; semantic change changes data version |
| `historical.resampling_version` | `str` | DEFAULT_FOR_DEVELOPMENT | Non-empty; changes derived M15/H1 versions, not canonical M5 |

### 4.12 `backtest`

| Key | Type | Class | Validation/meaning |
|---|---|---|---|
| `backtest.initial_equity` | `Decimal` | DEFAULT_FOR_DEVELOPMENT | Positive starting equity; part of run identity |
| `backtest.execution_timeframe` | `Timeframe` | BACKTEST_REQUIRED | PHASE 5 requires `5m` |
| `backtest.entry_fill_policy` | `BacktestEntryFillPolicy` | BACKTEST_REQUIRED | Only `NEXT_M5_OPEN` |
| `backtest.intrabar_ambiguity_policy` | `IntrabarAmbiguityPolicy` | BACKTEST_REQUIRED | Only conservative `WORST_CASE` |
| `backtest.modeled_spread_rate` | `Decimal` | DEFAULT_FOR_DEVELOPMENT | Non-negative ratio; explicit modeled assumption |
| `backtest.market_slippage_rate` | `Decimal` | DEFAULT_FOR_DEVELOPMENT | Non-negative adverse market rate |
| `backtest.stop_slippage_rate` | `Decimal` | DEFAULT_FOR_DEVELOPMENT | Non-negative adverse stop rate |
| `backtest.maker_fee_rate` | `Decimal` | DEFAULT_FOR_DEVELOPMENT | Non-negative assumption; unused without maker semantics |
| `backtest.taker_fee_rate` | `Decimal` | DEFAULT_FOR_DEVELOPMENT | Fee on actual executed notional |
| `backtest.funding_mode` | `FundingMode` | BACKTEST_REQUIRED | `DISABLED`, `FIXED_ASSUMPTION`, or `HISTORICAL_SERIES` |
| `backtest.funding_interval` | `Duration` | BACKTEST_REQUIRED | Positive deterministic event interval |
| `backtest.fixed_funding_rate` | optional `Decimal` | DEFAULT_FOR_DEVELOPMENT | Required only for fixed mode; magnitude at most 1 |
| `backtest.allow_same_bar_exit_after_entry` | `bool` | BACKTEST_REQUIRED | Applies declared ambiguity policy after entry |
| `backtest.gap_stop_policy` | `GapStopPolicy` | BACKTEST_REQUIRED | Only `OPEN_OR_STOP_WORSE` |
| `backtest.target_gap_policy` | `TargetGapPolicy` | BACKTEST_REQUIRED | Only `TARGET_PRICE_NO_IMPROVEMENT` |
| `backtest.limit_fill_policy` | `BacktestLimitFillPolicy` | BACKTEST_REQUIRED | Full fill only after a future touch |
| `backtest.end_position_policy` | `EndOfBacktestPolicy` | BACKTEST_REQUIRED | Force close at final M5 mark |
| `backtest.halt_stops_run` | `bool` | BACKTEST_REQUIRED | Must be true in PHASE 5 |
| `backtest.execution_model_version` | `str` | BACKTEST_REQUIRED | Non-empty execution algorithm label |
| `backtest.spread_model_version` | `str` | BACKTEST_REQUIRED | Non-empty spread algorithm label |
| `backtest.funding_algorithm_version` | `str` | BACKTEST_REQUIRED | Non-empty funding algorithm label |

All numeric YAML values use quoted Decimal strings. These development values are
reproducible assumptions, not current venue facts. M5, worst-case ambiguity, adverse
gap handling, funding-mode coherence, and halt-stop behavior are cross-field enforced.

### 4.13 `journal`

| Key | Type | Class | Validation/meaning |
|---|---|---|---|
| `journal.backend` | `JournalBackend` | DEFAULT_FOR_DEVELOPMENT | `SQLITE` cho MVP |
| `journal.database_path` | path | DEFAULT_FOR_DEVELOPMENT | `var/trading_bot.db`; không nằm trong Git, parent writable |
| `journal.append_only` | `bool` | DEFAULT_FOR_DEVELOPMENT | Phải true cho audit events |
| `journal.require_write_before_submit` | `bool` | DEFAULT_FOR_DEVELOPMENT | Phải true |
| `journal.busy_timeout` | `Duration` | BACKTEST_REQUIRED | Positive |
| `journal.retention_days` | optional int | DEFAULT_FOR_DEVELOPMENT | Mặc định null nghĩa giữ vô hạn; không xóa audit đang dùng |

### 4.14 `monitoring`

| Key | Type | Class | Validation/meaning |
|---|---|---|---|
| `monitoring.health_interval` | `Duration` | BACKTEST_REQUIRED | Positive |
| `monitoring.reconciliation_interval` | `Duration` | BACKTEST_REQUIRED | Positive; Demo validation cần kiểm chứng |
| `monitoring.api_error_window` | `Duration` | BACKTEST_REQUIRED | Positive |
| `monitoring.api_error_limit` | `int` | BACKTEST_REQUIRED | Positive |
| `monitoring.alert_channels` | `tuple[str,...]` | DEFAULT_FOR_DEVELOPMENT | Mặc định empty tuple local; journal vẫn bắt buộc |
| `monitoring.kill_switch_requires_manual_reset` | `bool` | DEFAULT_FOR_DEVELOPMENT | Phải true |

## 5. Cross-field validation

1. Decimal precision ít nhất 28 và rounding mode đúng canonical enum; thay đổi arithmetic
   context phải đổi strategy/config version.
2. Timeframes phải đúng `5m/15m/1h`, khác nhau và chia hết theo hierarchy.
3. `history_bars` phải đáp ứng max indicator/level warm-up cộng confirmation lag.
4. `warmup_candles` mỗi timeframe `>=` công thức derived trong `market-data.md` và
   `history_bars >= warmup_candles`.
5. EMA periods đúng `[20,50,200]`; mọi indicator period/lookback dương; percentile
   lookback lớn hơn base period theo field contract.
6. `component_max_points` có đúng sáu `SignalComponentName` keys và tổng 100.
   Enabled component (`max_points > 0`) có đúng evidence keys cùng weights tổng 1;
   disabled component có empty weights. `minimum_nonzero_components` nằm trong
   `[1, enabled_component_count]`. Nếu `SIDEWAY_MEAN_REVERSION` hoặc
   `BREAKOUT_RETEST` được allow, cả hai direction thresholds phải không vượt
   `100 - component_max_points[TREND]` và minimum confluence phải `<=` số enabled non-TREND
   components, vì SIDEWAY bắt buộc cho toàn bộ TREND evidence bằng zero.
7. `rsi_bands` có đúng ba setup keys và mỗi min/max thỏa declared bounds. Mọi ramp có
   full bound lớn hơn start bound; regime family/timeframe weights tổng 1;
   `minimum_evidence_count` nằm trong `[2,3]` vì family nhỏ nhất có ba evidence atoms.
8. `levels.structure_timeframe` phải là `M15`; structure comparison tolerance không âm.
   Range zones thỏa `0 <= support_zone_max_fraction <
   resistance_zone_min_fraction <= 1`; outside tolerance không âm;
   `2 <= minimum_touches <= full_strength_touches`; stale, breakout-confirmation và
   retest-expiry bar counts đều positive.
9. `risk.target_leverage <= risk.max_leverage`; stop max distance lớn hơn min;
   `strategy.stop.atr_buffer >= 0`; daily, position, exposure và margin caps dương;
   `max_total_exposure >= max_position_notional`; `margin_buffer_ratio < 1`.
   Unrealized drawdown `max_ratio` phải `(0,1]` iff gate enabled, ngược lại phải null.
10. Retry counts hữu hạn và không âm; `0 < retry_delay <= max_retry_delay`; backoff
    multiplier `>= 1`. Protection policies phải đúng canonical fail-safe values;
    không cho enum extension qua YAML.
11. Demo yêu cầu environment `DEMO`, live switch false và credentials chỉ từ env.
12. Nếu environment `LIVE`, application PHASE 3 phải reject vì live implementation
    chưa tồn tại, kể cả khi một switch bị đặt true.
13. `execution.enabled=false` không được override bằng CLI shortcut không audit.
14. Mọi `BACKTEST_REQUIRED` field phải explicit; null/missing là startup error, không
    tự lấy “best practice” làm default.
15. Historical parser assumptions phải explicit; mappings/schema đúng exact registry;
    base timeframe là M5; conflict/gap policy đều `FAIL`; path/mtime không tham gia
    data identity. Full app config hash không tham gia historical identity; resampling
    version chỉ tham gia identity của derived timeframe.

Bất kỳ field hoặc cross-field rule nào fail đều phát `CONFIG_INVALID`, giữ global state
ở `HALTED` và không khởi tạo execution/provider side effect.

## 6. Secret policy

| Configuration class | Storage | Examples | Logging/Git rule |
|---|---|---|---|
| Normal application config | Versioned YAML | symbol, periods, thresholds, limits, policies | Có thể commit; journal bằng config hash |
| Secret config | Environment hoặc local `.env` | `OKX_API_KEY`, `OKX_API_SECRET`, `OKX_PASSPHRASE` | Không commit, hash, exception, log hoặc journal plaintext |

Demo credential không được có withdrawal permission. `.env` chỉ dành local và nằm
trong `.gitignore`. Logger/error serializer phải redact theo secret field names và
không dump environment/raw authentication request. Thiếu secret ở phase cần adapter
phải fail startup; PHASE 2 không tạo secret thật.

## 7. Reload và versioning

- MVP load config lúc startup; không hot-reload risk/strategy config giữa trade.
- Nếu hỗ trợ reload sau này: validate toàn bộ, tạo version mới atomically, invalidate
  candidate/approval cũ và journal event.
- Open position tiếp tục dùng policy/version đã gắn với trade, trừ emergency risk rule
  được định nghĩa và audit rõ; không trộn version âm thầm.
