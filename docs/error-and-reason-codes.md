# Error and Reason Code Registry — PHASE 2

## 1. Rules

- `ReasonCode` là enum canonical duy nhất; business logic không so sánh free text.
- Code đã phát hành không đổi meaning. Rename cần schema/version migration.
- Mỗi decision/event có thể có nhiều codes, sắp theo deterministic priority:
  safety/halt → data/state → risk → setup → score → informational.
- Human-readable message là metadata để giải thích, không điều khiển flow.
- Journal luôn lưu code, category, severity, observed values, correlation IDs và versions.

Expected action vocabulary:

- `NO_TRADE`: kết thúc evaluation, vẫn journal decision.
- `REJECT`: Risk Engine từ chối candidate, bot có thể tiếp tục observe.
- `RECOVER`: chặn entry, reconcile/backfill/query state.
- `HALT`: kích hoạt kill switch; chỉ risk-reducing actions được phép.
- `CONTINUE`: informational/audit; không tự cho phép trade.

## 2. Canonical registry

### Data and indicators

| Code | Category | Severity | Meaning | Expected action | Journal behavior |
|---|---|---|---|---|---|
| `DATA_MISSING` | DATA | ERROR | Required stream/field absent, chưa xác định là interval gap | NO_TRADE/RECOVER | `DECISION_EVALUATED`; observed source/field |
| `DATA_STALE` | DATA | ERROR | Dữ liệu vượt freshness SLA | NO_TRADE/RECOVER | Decision + age/SLA |
| `DATA_GAP` | DATA | ERROR | Thiếu expected candle interval | NO_TRADE/RECOVER | Decision + missing intervals |
| `DATA_DUPLICATE` | DATA | INFO | Event trùng key và payload | CONTINUE after dedupe | Metric/audit event; không duplicate decision |
| `DATA_CONFLICT` | DATA | ERROR | Cùng canonical key nhưng payload khác | NO_TRADE/RECOVER | Record both hashes/revisions |
| `DATA_OUT_OF_ORDER` | DATA | WARNING | Event đến sai thứ tự | RECOVER/buffer | Event + lateness/window |
| `TIMEFRAME_UNSYNCED` | DATA | ERROR | 5m/15m/1h không cùng valid cutoff | NO_TRADE/RECOVER | Decision + latest close per TF |
| `CLOCK_DRIFT` | DATA | ERROR | Source/local clock lệch quá tolerance | RECOVER | Health event + offsets |
| `DATA_UNHEALTHY` | HEALTH | CRITICAL | Data subsystem không thể khôi phục trong policy | HALT | `KILL_SWITCH_TRIGGERED` |
| `INDICATOR_NOT_READY` | INDICATOR | WARNING | Thiếu warm-up hoặc indicator required | NO_TRADE | Decision + missing counts |
| `INDICATOR_INVALID` | INDICATOR | ERROR | NaN/infinite/domain validation fail | NO_TRADE; repeated → HALT | Decision/health event + field |

### Regime, range and setup

| Code | Category | Severity | Meaning | Expected action | Journal behavior |
|---|---|---|---|---|---|
| `REGIME_UNCERTAIN` | REGIME | INFO | Evidence thiếu/xung đột; output UNCERTAIN | NO_TRADE | Decision + candidate evidence |
| `HIGH_VOLATILITY_BLOCKED` | REGIME | WARNING | High-volatility gate active | NO_TRADE | Decision + volatility evidence |
| `REGIME_DIRECTION_BLOCKED` | REGIME | INFO | Direction trái regime policy | NO_TRADE | Decision + direction/regime |
| `RANGE_INVALID` | SETUP | WARNING | Range thiếu, overlap hoặc không đủ validity | NO_TRADE | Decision + range validation |
| `SIDEWAY_MIDDLE_RANGE` | SETUP | INFO | SIDEWAY price ở middle zone | NO_TRADE | Decision bắt buộc lưu location/levels |
| `NO_CONFIRMATION` | SETUP | INFO | Chưa có closed candle/momentum confirmation | NO_TRADE | Decision + missing evidence |
| `BREAKOUT_CONFIRMATION_PENDING` | SETUP | INFO | Breakout detect, đang chờ confirmation | NO_TRADE | Decision + breakout state |
| `RETEST_PENDING` | SETUP | INFO | Breakout confirmed, chưa có retest | NO_TRADE | Decision + expiry |
| `RETEST_INVALIDATED` | SETUP | INFO | Price action làm retest setup invalid | NO_TRADE/reset setup | Decision + invalidation event |
| `RETEST_EXPIRED` | SETUP | INFO | Không có retest trong configured window | NO_TRADE/reset setup | Decision + expiry event |

### Signal and plan

| Code | Category | Severity | Meaning | Expected action | Journal behavior |
|---|---|---|---|---|---|
| `SCORE_TOO_LOW` | SIGNAL | INFO | Eligible direction score dưới threshold | NO_TRADE | Decision + both scores/thresholds |
| `SCORE_DIFFERENCE_TOO_SMALL` | SIGNAL | INFO | Directional score difference dưới minimum | NO_TRADE | Decision + difference/minimum |
| `AMBIGUOUS_SIGNAL` | SIGNAL | WARNING | Cả hai direction eligible hoặc evidence ambiguous | NO_TRADE | Decision + components/gates |
| `SIGNAL_INVALID` | SIGNAL | ERROR | Score/component contract invalid | NO_TRADE; repeated → HALT | Decision + validation error |
| `INVALID_STOP` | PLAN | ERROR | Stop zero/wrong side/no provenance | NO_TRADE/REJECT | Decision or risk event |
| `STOP_TOO_CLOSE` | PLAN | INFO | Stop dưới min tick/spread/ATR guard | NO_TRADE/REJECT | Observed distance/minimum |
| `STOP_TOO_FAR` | PLAN | INFO | Stop vượt max risk/ATR guard | NO_TRADE/REJECT | Observed distance/maximum |
| `TARGET_INVALID` | PLAN | ERROR | Target wrong side/missing/invalid level | NO_TRADE/REJECT | Decision/risk event |
| `LEVEL_TOO_CLOSE` | PLAN | INFO | Opposing level làm reward phi thực tế | NO_TRADE | Decision + level ID/distance |
| `RR_TOO_LOW` | PLAN | INFO | Cost-adjusted expected RR dưới minimum | NO_TRADE/REJECT | Both RR and configured minimum |

### Risk limits and sizing

| Code | Category | Severity | Meaning | Expected action | Journal behavior |
|---|---|---|---|---|---|
| `DAILY_LOSS_LIMIT` | RISK_LIMIT | CRITICAL | Realized daily net loss chạm/vượt cap | HALT | Risk event + kill switch + ledger boundary |
| `DAILY_DRAWDOWN_LIMIT` | RISK_LIMIT | CRITICAL | Equity drawdown từ session peak chạm/vượt cap | HALT | Risk event + peak/current equity |
| `DAILY_TRADE_LIMIT` | RISK_LIMIT | WARNING | Closed/opened lifecycle count chạm cap theo policy | REJECT until boundary; no auto-clear active halt | Risk event + counts |
| `CONSECUTIVE_LOSS_LIMIT` | RISK_LIMIT | CRITICAL | Consecutive closed losses chạm/vượt cap | HALT | Risk event + kill switch + trade IDs |
| `COOLDOWN_ACTIVE` | RISK_LIMIT | INFO | Loss cooldown chưa hết | REJECT | Risk event + cooldown_until |
| `RISK_BUDGET_EXCEEDED` | SIZING | ERROR | Recomputed worst-case loss vượt budget | Reduce quantity or REJECT | Risk event + budget/loss |
| `POSITION_SIZE_TOO_SMALL` | SIZING | INFO | Safe rounded quantity dưới exchange minimum | REJECT; never round up | Risk event + lot/minimum |
| `POSITION_CAP_EXCEEDED` | SIZING | WARNING | Notional/exposure vượt configured cap | Reduce quantity or REJECT | Risk event + cap/observed |
| `LEVERAGE_CAP_EXCEEDED` | SIZING | ERROR | Required/requested leverage vượt hard cap | Reduce quantity or REJECT | Risk event + cap/required |
| `INSUFFICIENT_MARGIN` | SIZING | ERROR | Available reconciled margin không đủ | Reduce quantity or REJECT | Risk event + margin requirement |
| `INSTRUMENT_METADATA_STALE` | SIZING | ERROR | Precision/contract metadata missing hoặc stale | RECOVER; severe → HALT | Health/risk event + metadata version |
| `NUMERICAL_ERROR` | SIZING | CRITICAL | Decimal invalid operation/overflow/non-finite result | HALT | Kill switch + sanitized operands/context |

### Market quality, execution and state

| Code | Category | Severity | Meaning | Expected action | Journal behavior |
|---|---|---|---|---|---|
| `SPREAD_TOO_WIDE` | MARKET | WARNING | Current spread vượt configured cap | REJECT; persistent severe → HALT | Risk event + bid/ask/spread |
| `SLIPPAGE_TOO_HIGH` | EXECUTION | CRITICAL | Estimated/realized slippage vượt cap | REJECT before submit; HALT after fill | Risk/execution + kill switch when realized |
| `APPROVAL_EXPIRED` | EXECUTION | WARNING | Risk approval TTL hết hoặc context version đổi | REJECT/re-evaluate | Execution event + approval timestamps |
| `DUPLICATE_EVALUATION` | IDEMPOTENCY | INFO | Evaluation key đã xử lý | CONTINUE without new trade | Dedupe metric; link original record |
| `DUPLICATE_ORDER_INTENT` | IDEMPOTENCY | ERROR | Client order ID/approval đã dùng | RECOVER/query exchange | Execution/reconciliation event |
| `ORDER_OUTCOME_UNKNOWN` | EXECUTION | ERROR | Submit timeout, chưa biết exchange accepted | RECOVER/query; never blind retry | Execution event + client ID |
| `ORDER_REJECTED` | EXECUTION | WARNING | Exchange/simulator reject order | REJECT/OBSERVE or RECOVER by cause | Execution report + exchange code sanitized |
| `PARTIAL_FILL_UNRESOLVED` | EXECUTION | CRITICAL | Filled exposure chưa protected/resolved | HALT/protect/reduce | Kill switch + fill/exposure details |
| `PROTECTION_FAILED` | EXECUTION | CRITICAL | Không đặt/xác nhận stop cho open quantity | HALT/protect or reduce | Kill switch + order/position IDs |
| `STATE_MISMATCH` | STATE | CRITICAL | Local order/position khác authoritative exchange | HALT/RECOVER | Reconciliation + kill switch when unresolved |
| `API_UNHEALTHY` | HEALTH | CRITICAL | API/WebSocket lỗi vượt policy | HALT/RECOVER | Health + kill switch event |
| `JOURNAL_UNAVAILABLE` | HEALTH | CRITICAL | Không persist audit-critical event | HALT | Kill switch/fallback local emergency log |
| `CONFIG_INVALID` | CONFIG | CRITICAL | Missing/unknown/inconsistent config | HALT before startup | Startup event; never secrets |
| `VERSION_MISMATCH` | VERSION | ERROR | Context/model versions không nhất quán | REJECT/re-evaluate | Decision/risk event + versions |
| `INVALID_STATE_TRANSITION` | STATE | ERROR | Event không được phép từ current bot state | Reject transition; repeated/severe → HALT | `INVALID_TRANSITION` event |

## 3. Canonical alias mapping từ PHASE 1

PHASE 1 giữ nguyên lịch sử. Khi ingest record/document cũ, normalize như sau:

| PHASE 1 alias | Canonical PHASE 2 code |
|---|---|
| `WARMUP_INCOMPLETE` | `INDICATOR_NOT_READY` |
| `MID_RANGE` | `SIDEWAY_MIDDLE_RANGE` |
| `LONG_SCORE_LOW`, `SHORT_SCORE_LOW` | `SCORE_TOO_LOW` với observed direction |
| `SCORE_DIFFERENCE_LOW` | `SCORE_DIFFERENCE_TOO_SMALL` |
| `RR_BELOW_MINIMUM` | `RR_TOO_LOW` |
| `SIZE_BELOW_MINIMUM` | `POSITION_SIZE_TOO_SMALL` |
| `LOSS_COOLDOWN_ACTIVE` | `COOLDOWN_ACTIVE` |
| `SLIPPAGE_BUDGET_EXCEEDED` | `SLIPPAGE_TOO_HIGH` |
| `DATA_INVALID` | Code data cụ thể; nếu không biết dùng `DATA_MISSING` + detail |
| `SCORE_INSUFFICIENT` | `SCORE_TOO_LOW` hoặc `SCORE_DIFFERENCE_TOO_SMALL` theo evidence |
| `RISK_REJECT` | Reason code cụ thể từ RiskDecision; không persist generic alias mới |
| `PLAN_EXPIRED_OR_MARKET_CHANGED` | `APPROVAL_EXPIRED` hoặc `VERSION_MISMATCH` |

## 4. Journal schema behavior

Mỗi reason occurrence tối thiểu có:

- `reason_code`, canonical category/severity.
- `event_id`, `evaluation_id`; candidate/risk/order/trade IDs nếu tồn tại.
- `observed_at`, `as_of`, config/code/strategy/data versions.
- Typed `observed_value`, `limit_value`, `unit` khi applicable.
- Optional human detail không chứa secrets.

Unknown code khi deserialize là schema compatibility error, không map về free text.
Analytics group theo canonical code/category và giữ original legacy alias trong field
audit riêng nếu migrate dữ liệu cũ.
