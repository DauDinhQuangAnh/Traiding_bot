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

`config_version = sha256(canonical_merged_config_without_secrets)`. Canonical form
sort key, giữ Decimal dưới dạng string và normalize duration/timeframe. Secrets không
đi vào hash, log hoặc journal.

## 3. Top-level schema

| Group | Responsibility |
|---|---|
| `market` | Instrument, environment, account/margin assumptions |
| `strategy` | Score components, gates, entry/target behavior |
| `regime` | Multi-evidence regime candidates/conflict policy |
| `levels` | S/R, range, structure, breakout/retest parameters |
| `risk` | Risk budget, caps, limits, stop/RR policy |
| `execution` | Dry-run, approval TTL, timeout, partial-fill/emergency policy |
| `data` | Timeframes, warm-up, freshness, gap/backfill policy |
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
| `market.position_mode` | enum | BACKTEST_REQUIRED | `NET` hoặc `LONG_SHORT`; cần chốt trước adapter |
| `market.margin_mode` | enum | BACKTEST_REQUIRED | `ISOLATED` hoặc `CROSS`; cần chốt trước adapter |
| `market.timezone` | IANA timezone | DEFAULT_FOR_DEVELOPMENT | Storage/event time vẫn UTC |

### 4.2 `strategy`

| Key | Type | Class | Validation/meaning |
|---|---|---|---|
| `strategy.version` | `str` | DEFAULT_FOR_DEVELOPMENT | SemVer hoặc immutable experiment ID |
| `strategy.long_threshold` | `Decimal` | BACKTEST_REQUIRED | `[0,100]` |
| `strategy.short_threshold` | `Decimal` | BACKTEST_REQUIRED | `[0,100]` |
| `strategy.minimum_score_difference` | `Decimal` | BACKTEST_REQUIRED | `[0,100]` |
| `strategy.component_weights` | `Mapping[str, Decimal]` | BACKTEST_REQUIRED | Không âm; configured maxima tổng đúng 100 |
| `strategy.allowed_setups` | `set[str]` | BACKTEST_REQUIRED | Registry có version; unknown setup invalid |
| `strategy.entry_model` | enum | BACKTEST_REQUIRED | Contract, không chứa exchange order type |
| `strategy.target_model` | enum | BACKTEST_REQUIRED | MVP một target; multi-target disabled mặc định |
| `strategy.high_volatility_enabled` | `bool` | DEFAULT_FOR_DEVELOPMENT | Phải `false`; bật yêu cầu strategy/backtest riêng |

### 4.3 `regime`

| Key | Type | Class | Validation/meaning |
|---|---|---|---|
| `regime.minimum_evidence_count` | `int` | BACKTEST_REQUIRED | `>= 2`; tránh single-indicator rule |
| `regime.minimum_confidence` | `DecimalRatio` | BACKTEST_REQUIRED | Dưới mức này → `UNCERTAIN` |
| `regime.conflict_tolerance` | `DecimalRatio` | BACKTEST_REQUIRED | Evidence conflict vượt mức → `UNCERTAIN` |
| `regime.adx.*` | typed Decimal fields | BACKTEST_REQUIRED | Trend-strength candidate, không tự quyết regime |
| `regime.ema_structure.*` | typed fields | BACKTEST_REQUIRED | Alignment/slope/distance candidates |
| `regime.volatility.*` | typed Decimal fields | BACKTEST_REQUIRED | ATR/BB expansion percentiles/windows |
| `regime.structure.*` | typed fields | BACKTEST_REQUIRED | Swing confirmation/lookback |
| `regime.sideway.*` | typed fields | BACKTEST_REQUIRED | Range/evidence candidate rules |

### 4.4 `levels`

| Key | Type | Class | Validation/meaning |
|---|---|---|---|
| `levels.lookback_bars` | mapping timeframe→int | BACKTEST_REQUIRED | Positive; đủ trước `as_of` |
| `levels.swing_confirmation_bars` | `int` | BACKTEST_REQUIRED | Positive; point chỉ usable sau confirmation |
| `levels.cluster_tolerance_atr` | `Decimal` | BACKTEST_REQUIRED | Dương |
| `levels.minimum_level_strength` | `DecimalRatio` | BACKTEST_REQUIRED | Dưới mức này không đưa vào active set |
| `levels.near_boundary_atr` | `Decimal` | BACKTEST_REQUIRED | Phân loại near support/resistance |
| `levels.middle_zone_fraction` | `DecimalRatio` | BACKTEST_REQUIRED | Không overlap edge zones |
| `levels.minimum_range_width_atr` | `Decimal` | BACKTEST_REQUIRED | Range phải đủ rộng sau costs |
| `levels.breakout_buffer_atr` | `Decimal` | BACKTEST_REQUIRED | Detect, không phải entry trigger |
| `levels.confirmation_bars` | `int` | BACKTEST_REQUIRED | Positive |
| `levels.retest_expiry_bars` | `int` | BACKTEST_REQUIRED | Positive; hết hạn → NO_TRADE |

### 4.5 `risk`

| Key | Type | Class | Validation/meaning |
|---|---|---|---|
| `risk.risk_per_trade` | `DecimalRatio` | BACKTEST_REQUIRED | `0 < value < 1` |
| `risk.max_leverage` | `Decimal` | BACKTEST_REQUIRED | `>= 1`; hard cap, không phải sizing input |
| `risk.max_position_notional` | `Decimal` | BACKTEST_REQUIRED | USDT dương |
| `risk.max_total_exposure` | `Decimal` | BACKTEST_REQUIRED | `>= max_position_notional` cho single symbol |
| `risk.max_daily_loss` | `Decimal` | BACKTEST_REQUIRED | Positive absolute USDT; trigger khi daily realized net PnL `<= -limit` |
| `risk.max_daily_drawdown` | `DecimalRatio` | BACKTEST_REQUIRED | Drawdown từ session peak equity; chạm limit → HALT |
| `risk.max_daily_trades` | `int` | BACKTEST_REQUIRED | Positive; theo closed lifecycle |
| `risk.max_consecutive_losses` | `int` | BACKTEST_REQUIRED | Positive |
| `risk.minimum_rr` | `Decimal` | BACKTEST_REQUIRED | Dương; net-of-estimated-costs |
| `risk.max_allowed_spread` | `DecimalRatio` | BACKTEST_REQUIRED | Dương |
| `risk.max_slippage` | `DecimalRatio` | BACKTEST_REQUIRED | Dương |
| `risk.cooldown_after_loss` | `Duration` | BACKTEST_REQUIRED | Không âm; persisted |
| `risk.daily_reset_timezone` | IANA timezone | DEFAULT_FOR_DEVELOPMENT | UTC được chọn cho development |
| `risk.max_open_positions` | `int` | DEFAULT_FOR_DEVELOPMENT | Một cho MVP; positive |
| `risk.stop.min_distance_atr` | `Decimal` | BACKTEST_REQUIRED | Dương |
| `risk.stop.max_distance_atr` | `Decimal` | BACKTEST_REQUIRED | Lớn hơn min |
| `risk.stop.atr_buffer` | `Decimal` | BACKTEST_REQUIRED | Không âm |
| `risk.unrealized_drawdown_gate` | typed optional limit | BACKTEST_REQUIRED | Nếu unset phải ghi rõ disabled; không thay daily realized limit |

### 4.6 `execution`

| Key | Type | Class | Validation/meaning |
|---|---|---|---|
| `execution.enabled` | `bool` | DEFAULT_FOR_DEVELOPMENT | `false` trong PHASE 2 |
| `execution.dry_run` | `bool` | DEFAULT_FOR_DEVELOPMENT | `true` trong PHASE 2 |
| `execution.enable_live_trading` | `bool` | DEFAULT_FOR_DEVELOPMENT | Luôn `false`; env `ENABLE_LIVE_TRADING` cũng phải false |
| `execution.approval_ttl` | `Duration` | BACKTEST_REQUIRED | Positive; hết hạn phải re-evaluate |
| `execution.submit_timeout` | `Duration` | BACKTEST_REQUIRED | Positive; timeout → query-before-retry |
| `execution.cancel_timeout` | `Duration` | BACKTEST_REQUIRED | Positive |
| `execution.partial_fill_policy` | enum | BACKTEST_REQUIRED | `PROTECT_FILLED_AND_CANCEL_REMAINDER` là candidate policy, chưa chốt |
| `execution.protection_failure_policy` | enum | BACKTEST_REQUIRED | Fail closed; phải có reduce/reconcile contract |
| `execution.max_order_retries` | `int` | DEFAULT_FOR_DEVELOPMENT | Retry transport không đồng nghĩa submit lại; non-negative |

### 4.7 `data`

| Key | Type | Class | Validation/meaning |
|---|---|---|---|
| `data.timeframes.micro` | `Timeframe` | DEFAULT_FOR_DEVELOPMENT | `5m` |
| `data.timeframes.entry` | `Timeframe` | DEFAULT_FOR_DEVELOPMENT | `15m`; evaluation trigger |
| `data.timeframes.context` | `Timeframe` | DEFAULT_FOR_DEVELOPMENT | `1h`; closed only |
| `data.history_bars` | mapping timeframe→int | BACKTEST_REQUIRED | Phải >= derived warm-up requirement |
| `data.freshness` | mapping stream→Duration | BACKTEST_REQUIRED | Quote/candle/account có SLA riêng |
| `data.gap_policy` | enum | DEFAULT_FOR_DEVELOPMENT | `BLOCK_AND_BACKFILL`; không fill synthetic |
| `data.max_backfill_attempts` | `int` | DEFAULT_FOR_DEVELOPMENT | Non-negative; vượt → unhealthy/halt policy |
| `data.clock_drift_tolerance` | `Duration` | BACKTEST_REQUIRED | Non-negative |
| `data.store_raw` | `bool` | DEFAULT_FOR_DEVELOPMENT | True cho reproducibility; raw immutable |

### 4.8 `journal`

| Key | Type | Class | Validation/meaning |
|---|---|---|---|
| `journal.backend` | enum | DEFAULT_FOR_DEVELOPMENT | `SQLITE` cho MVP |
| `journal.database_path` | path | DEFAULT_FOR_DEVELOPMENT | Không nằm trong Git; parent writable |
| `journal.append_only` | `bool` | DEFAULT_FOR_DEVELOPMENT | Phải true cho audit events |
| `journal.require_write_before_submit` | `bool` | DEFAULT_FOR_DEVELOPMENT | Phải true |
| `journal.busy_timeout` | `Duration` | DEFAULT_FOR_DEVELOPMENT | Positive |
| `journal.retention_days` | optional int | DEFAULT_FOR_DEVELOPMENT | Null nghĩa giữ vô hạn; không xóa audit đang dùng |

### 4.9 `monitoring`

| Key | Type | Class | Validation/meaning |
|---|---|---|---|
| `monitoring.health_interval` | `Duration` | DEFAULT_FOR_DEVELOPMENT | Positive |
| `monitoring.reconciliation_interval` | `Duration` | BACKTEST_REQUIRED | Positive; Demo validation cần kiểm chứng |
| `monitoring.api_error_window` | `Duration` | BACKTEST_REQUIRED | Positive |
| `monitoring.api_error_limit` | `int` | BACKTEST_REQUIRED | Positive |
| `monitoring.alert_channels` | `tuple[str,...]` | DEFAULT_FOR_DEVELOPMENT | Có thể rỗng local; journal vẫn bắt buộc |
| `monitoring.kill_switch_requires_manual_reset` | `bool` | DEFAULT_FOR_DEVELOPMENT | Phải true |

## 5. Cross-field validation

1. Timeframes phải đúng `5m/15m/1h`, khác nhau và chia hết theo hierarchy.
2. `history_bars` phải đáp ứng max indicator/level warm-up cộng confirmation lag.
3. Component weights/maxima phải tổng 100 cho mỗi phía.
4. Range middle/edge zones không overlap; support luôn dưới resistance.
5. Stop max distance lớn hơn min; risk caps dương và coherent.
6. Demo yêu cầu environment `DEMO`, live switch false và credentials chỉ từ env.
7. Nếu environment `LIVE`, application PHASE 3 phải reject vì live implementation
   chưa tồn tại, kể cả khi một switch bị đặt true.
8. `execution.enabled=false` không được override bằng CLI shortcut không audit.
9. Mọi `BACKTEST_REQUIRED` field phải explicit; null/missing là startup error, không
   tự lấy “best practice” làm default.

## 6. Secret policy

Tên biến dự kiến: `OKX_API_KEY`, `OKX_API_SECRET`, `OKX_PASSPHRASE`. Không field nào
được ghi trong YAML, config hash, exception, log hoặc journal. Demo credential không
được có withdrawal permission. `.env` chỉ dành local và nằm trong `.gitignore`.

## 7. Reload và versioning

- MVP load config lúc startup; không hot-reload risk/strategy config giữa trade.
- Nếu hỗ trợ reload sau này: validate toàn bộ, tạo version mới atomically, invalidate
  candidate/approval cũ và journal event.
- Open position tiếp tục dùng policy/version đã gắn với trade, trừ emergency risk rule
  được định nghĩa và audit rõ; không trộn version âm thầm.
