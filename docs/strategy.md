# Strategy and Signal Scoring Specification — PHASE 2

## 1. Scope and boundaries

Strategy biến market/regime/level context thành `TradeDecision` và có thể tạo
`TradeCandidate`. Strategy không tính quantity/leverage, không gọi exchange và không
được bypass Risk Engine. PHASE 2 không chọn weights/threshold tối ưu và không khẳng
định strategy profitable.

Inputs cùng `evaluation_id/as_of/versions`:

- `MarketSnapshot`
- ready `IndicatorSnapshot`
- `RegimeAssessment`
- `LevelSet`/`RangeContext`
- `MarketStructure`
- Fee/slippage estimate interface cho planned RR

Outputs:

- Với input strategy hợp lệ luôn có `SignalAssessment`; application luôn tạo
  `DecisionRecord`, kể cả khi dừng trước Strategy.
- Chỉ có `TradeCandidate` khi direction, setup và planned RR đều hợp lệ.

## 2. Evaluation gates trước scoring

MarketSnapshot build fail hoặc indicator not ready khiến application ghi NO_TRADE và
không gọi Strategy. Với invocation hợp lệ, gate fail dẫn `NO_TRADE`; components chỉ
được tính khi inputs đủ an toàn:

1. Snapshot complete/fresh và indicator ready.
2. Versions/as-of/symbol nhất quán.
3. Regime không `UNCERTAIN`/blocked high volatility.
4. Không có active position/pending candidate theo orchestration policy.
5. Setup nằm trong regime/setup table tại §6.
6. SIDEWAY location hợp lệ; middle bị block tuyệt đối.
7. Breakout chỉ eligible sau `RETEST_VALIDATED`.

## 3. Component model

Canonical initial component registry:

| Component | Candidate evidence | Constraint |
|---|---|---|
| `trend_score` | 1h context, EMA structure/slope, regime alignment | Không duplicate toàn bộ regime confidence |
| `momentum_score` | RSI/momentum behavior, non-extreme continuation/reversal context | RSI đơn lẻ không quyết định |
| `structure_score` | Confirmed HH/HL hoặc LH/LL, pullback/invalidation geometry | Chỉ points confirmed tại `as_of` |
| `level_score` | Proximity/quality của S/R, range location, target obstruction | SIDEWAY middle luôn gate fail |
| `volume_score` | Relative volume/statistical confirmation | Cùng source/unit/window version |
| `confirmation_score` | Closed candle rejection/continuation; breakout/retest state | Không dùng candle đang mở |

Mỗi `SignalComponent` lưu `component_name`, `long_points`, `short_points`,
`max_points`, evidence, reason codes và config version. Points/weights là Decimal,
không âm; tổng configured maxima đúng 100.

Nếu component disabled, `max_points=0` và không được redistribute weight ngầm. Một
experiment muốn redistribute phải có config/strategy version mới.

Các hàm canonical dùng chung:

```text
clamp01(x) = min(1, max(0, x))
ramp_up(x, start, full) = clamp01((x - start) / (full - start))
ramp_down(x, full, zero) = 1 - ramp_up(x, full, zero)
```

Với mỗi direction, evidence strength được tính chính xác:

| Component | LONG evidence strengths | SHORT evidence strengths |
|---|---|---|
| `trend_score` | Confirmed TREND_UP candidate score; EMA-up binary; pullback proximity `ramp_down(abs(close-ema20)/atr, 0, trend_pullback_tolerance_atr)` | Đối xứng với TREND_DOWN |
| `momentum_score` | `ramp_up(rsi, rsi_long_start, rsi_long_full)` và `ramp_up(rsi_slope, 0, rsi_slope_full)` | `ramp_down(rsi, rsi_short_full, rsi_short_start)` và `ramp_up(-rsi_slope, 0, rsi_slope_full)` |
| `structure_score` | 1 iff structure BULLISH, else 0 | 1 iff structure BEARISH, else 0 |
| `level_score` | `ramp_down(distance_to_valid_support_atr, level_full_strength_distance_atr, level_zero_strength_distance_atr)` | Dùng distance tới valid resistance đối xứng |
| `volume_score` | `ramp_up(volume_ratio, ratio_start, ratio_full)` khi LONG confirmation true, else 0 | Cùng formula khi SHORT confirmation true |
| `confirmation_score` | 1 iff bullish confirmation rule pass, else 0 | 1 iff bearish confirmation rule pass, else 0 |

Trong BREAKOUT_RETEST, valid level là boundary vừa retest. Trong
SIDEWAY_MEAN_REVERSION, đó là range support/resistance. Trong TREND_PULLBACK, đó là
nearest active directional S/R level. Thiếu level → strength 0 và candidate builder
sau đó fail nếu không có invalidation anchor.

Mỗi component dùng:

```text
component_strength(direction) =
  sum(evidence_strength[name] × configured_evidence_weight[name])
component_points(direction) = max_points × component_strength(direction)
```

Evidence weights của component phải tổng 1. `SignalEvidence` lưu từng operand,
strength và source IDs; không chỉ lưu câu mô tả.

### Closed-candle confirmation

Với trigger candle 15m:

```text
candle_range = high - low
body_fraction = abs(close - open) / candle_range
close_location = (close - low) / candle_range
lower_wick_fraction = (min(open, close) - low) / candle_range
upper_wick_fraction = (high - max(open, close)) / candle_range

bullish_directional = close > open
  AND body_fraction >= minimum_body_fraction
  AND close_location >= long_close_location_min
bullish_rejection = close > open
  AND lower_wick_fraction >= minimum_rejection_wick_fraction
  AND close_location >= long_close_location_min
bullish_confirmation = bullish_directional OR bullish_rejection

bearish_directional = close < open
  AND body_fraction >= minimum_body_fraction
  AND close_location <= short_close_location_max
bearish_rejection = close < open
  AND upper_wick_fraction >= minimum_rejection_wick_fraction
  AND close_location <= short_close_location_max
bearish_confirmation = bearish_directional OR bearish_rejection
```

`candle_range <= 0` tạo `CANDLE_INVALID`; không chia bằng epsilon.

## 4. Score aggregation

```text
long_score  = sum(component.long_points)
short_score = sum(component.short_points)
```

Both scores phải nằm trong `[0,100]`. Sai total/max/NaN là specification violation,
không clamp im lặng: `NO_TRADE` với `SIGNAL_INVALID` và health escalation.

Evidence có thể đóng góp cho cả hai phía nếu context mixed. Strategy không ép
zero phía đối diện để làm score difference đẹp hơn.

Confluence count là số component có directional points `> 0`. Direction không eligible
nếu count `< strategy.minimum_nonzero_components`, reason `CONFLUENCE_TOO_LOW`.

## 5. Direction eligibility

Với thresholds versioned từ config:

```text
long_eligible = regime_allows_long
                AND long_confluence_count >= minimum_nonzero_components
                AND long_score >= long_threshold
                AND (long_score - short_score) >= minimum_score_difference

short_eligible = regime_allows_short
                 AND short_confluence_count >= minimum_nonzero_components
                 AND short_score >= short_threshold
                 AND (short_score - long_score) >= minimum_score_difference
```

`>=` là boundary canonical. Nếu minimum difference không đạt: `NO_TRADE`, kể cả một
score có vẻ cao. Ví dụ LONG 54 và SHORT 47 không có nghĩa là LONG nếu threshold hoặc
difference không pass.

Decision table:

| Long eligible | Short eligible | Result |
|---|---|---|
| False | False | `NO_TRADE` |
| True | False | Xét xây LONG candidate |
| False | True | Xét xây SHORT candidate |
| True | True | `NO_TRADE` + `AMBIGUOUS_SIGNAL`; cấu hình/evidence cần review |

Không tự chọn score lớn hơn trong case ambiguous.

## 6. Regime/setup rules

Setup selection is deterministic and returns at most one setup:

1. `HIGH_VOLATILITY`/`UNCERTAIN` → none.
2. `TREND_UP` + LONG pullback condition → `TREND_PULLBACK/LONG`; otherwise none.
3. `TREND_DOWN` + SHORT pullback condition → `TREND_PULLBACK/SHORT`; otherwise none.
4. `SIDEWAY` + `RETEST_VALIDATED` → `BREAKOUT_RETEST` in breakout direction.
5. Else `SIDEWAY + NEAR_SUPPORT` → `SIDEWAY_MEAN_REVERSION/LONG`.
6. Else `SIDEWAY + NEAR_RESISTANCE` → `SIDEWAY_MEAN_REVERSION/SHORT`.
7. Mọi case còn lại → none/NO_TRADE. BREAKOUT_RETEST precedes mean reversion so one
   evaluation cannot emit two candidates.

### Trend

- TREND_UP: chỉ setup LONG theo trend trong MVP.
- TREND_DOWN: chỉ setup SHORT theo trend trong MVP.
- Counter-trend score có thể được tính để diagnostic nhưng bị regime gate block.
- Pullback pass khi `abs(close - ema20) / atr <= trend_pullback_tolerance_atr`;
  opposing level phải cho target hợp lệ theo §7. ATR invalid → NO_TRADE.

### SIDEWAY mean reversion

- `MIDDLE`: luôn `NO_TRADE`; không gọi candidate builder.
- `NEAR_SUPPORT`: chỉ LONG nếu bullish closed-candle confirmation, volume/momentum
  component strengths dương, scores, confluence và cost-adjusted RR pass.
- `NEAR_RESISTANCE`: chỉ SHORT với điều kiện đối xứng.
- Overlapping edge zones/range invalid: `NO_TRADE`, không chọn nearest side.

### Breakout

- `BREAKOUT_DETECTED`, `WAIT_CONFIRMATION`, `WAIT_RETEST`: `NO_TRADE`.
- Chỉ `RETEST_VALIDATED` có thể mở scoring gate theo breakout direction.
- State expired/invalidated hoặc không có retest: `NO_TRADE`; không FOMO market price.

### Blocked regimes

HIGH_VOLATILITY và UNCERTAIN không tạo candidate bất kể score.

## 7. Candidate construction

Thứ tự bắt buộc:

1. Chọn eligible direction và `SetupType` từ regime/location/breakout gates.
2. Với `EntryModel.CLOSE_REFERENCE`, `entry_price` bằng close của trigger 15m. Đây là
   reference, không phải guaranteed fill.
3. Chọn invalidation anchor:
   - TREND_PULLBACK LONG/SHORT: confirmed swing low/high gần nhất theo thời gian nằm
   đúng phía entry; chọn `confirmed_at` lớn nhất, nếu bằng nhau chọn `candle_id`
   lexicographically nhỏ nhất.
   - SIDEWAY_MEAN_REVERSION LONG: `support.zone_lower`; SHORT: `resistance.zone_upper`.
   - BREAKOUT_RETEST LONG: zone lower của resistance vừa retest; SHORT: zone upper
     của support vừa retest.
4. LONG stop = anchor `- strategy.stop.atr_buffer × ATR`; SHORT stop = anchor `+`
   buffer.
   Không có anchor/ATR hợp lệ → `INVALID_STOP`.
5. Với `TargetModel.NEXT_OPPOSING_LEVEL`: LONG chọn active resistance có
   `zone_lower > entry` nhỏ nhất; target = `zone_lower`. SHORT chọn active support có
   `zone_upper < entry` lớn nhất; target = `zone_upper`. Không có target →
   `TARGET_INVALID`. SIDEWAY ưu tiên boundary đối diện vì đó chính là nearest level.
6. Validate direction: LONG `stop < entry < target`; SHORT `target < entry < stop`.
7. Lấy `CostRateEstimate` từ FeeModel cho cùng symbol/as_of/version, dùng conservative
   quantity/notional cap do Risk configuration cung cấp; không tự giả định maker fill.
8. Tính:

```text
gross_loss_fraction = abs(entry - stop) / entry
gross_reward_fraction = abs(target - entry) / entry
planned_loss_fraction = gross_loss_fraction
  + entry_fee_rate + stop_exit_fee_rate
  + entry_slippage_rate + stop_slippage_rate + funding_debit_rate
planned_reward_fraction = gross_reward_fraction
  - entry_fee_rate - target_exit_fee_rate
  - entry_slippage_rate - target_slippage_rate - funding_debit_rate
planned_rr_before_costs = gross_reward_fraction / gross_loss_fraction
planned_rr_after_costs = planned_reward_fraction / planned_loss_fraction
```

9. Denominator/reward không dương hoặc RR dưới `risk.minimum_rr` → `RR_TOO_LOW`.
10. Phát immutable `TradeCandidate` không có quantity/leverage; attach selected level
    IDs, `CostRateEstimate`, setup/entry/target enums và versions.

Strategy không được kéo stop gần entry hoặc bỏ level cản để tăng RR. Risk Engine sẽ
tính lại bằng fresh context và là kết quả authoritative; bất kỳ invariant/version gate
nào fail đều dẫn tới reject thay vì tin planned RR của Strategy.

## 8. Explainability contract

Mọi assessment phải trả lời được:

- Mỗi component cho bao nhiêu điểm mỗi phía và evidence nào tạo điểm.
- Regime/location/setup gate nào pass/fail.
- Threshold/difference/config version nào đã dùng.
- Tại sao decision là LONG/SHORT/NO_TRADE.
- Entry/stop/target bắt nguồn từ snapshot/level IDs nào.

Free-text explanation được render từ structured evidence/reason codes và chỉ phục vụ
con người. Không parse free text ngược lại để điều khiển logic.

## 9. Canonical strategy reason codes

- Input/gate: `INDICATOR_NOT_READY`, `REGIME_UNCERTAIN`,
  `HIGH_VOLATILITY_BLOCKED`, `REGIME_DIRECTION_BLOCKED`.
- SIDEWAY: `SIDEWAY_MIDDLE_RANGE`, `RANGE_INVALID`, `NO_CONFIRMATION`,
  `BREAKOUT_CONFIRMATION_PENDING`, `RETEST_PENDING`, `RETEST_INVALIDATED`, `RETEST_EXPIRED`.
- Score: `SCORE_TOO_LOW`, `SCORE_DIFFERENCE_TOO_SMALL`, `AMBIGUOUS_SIGNAL`, `SIGNAL_INVALID`.
- Plan: `INVALID_STOP`, `TARGET_INVALID`, `LEVEL_TOO_CLOSE`, `RR_TOO_LOW`.

Một decision có thể có nhiều reason codes; primary reason là code đầu tiên theo
deterministic precedence ở registry, không theo thứ tự phát hiện ngẫu nhiên.

## 10. Journaling

Với mọi evaluation, kể cả gate fail sớm, journal lưu:

- Evaluation/snapshot/version IDs và current price.
- Regime, range location và breakout state nếu có.
- Component breakdown, long/short scores và configured boundaries.
- Decision, primary/all reason codes và human explanation.
- Candidate/entry/stop/targets/planned RR nếu được tạo.

NO_TRADE record là first-class data để đo missed setups, over-filtering và behavior
theo regime; không chỉ log ra console.

## 11. Testing contract cho PHASE 3+

- Same inputs/version/state → same scores/decision/candidate ID.
- Mỗi component boundary và aggregate total/max validation.
- Score threshold và minimum difference tại below/equal/above boundary.
- Ambiguous case không chọn score cao hơn.
- Regime gate override mọi score; SIDEWAY middle không gọi candidate builder.
- Breakout state trước retest không tạo candidate.
- LONG/SHORT symmetry cho mirrored fixture.
- Candidate stop/target direction, provenance và RR after costs.
- Missing indicator/evidence → NO_TRADE, không default/fake values.
- Golden DecisionRecord gồm đầy đủ NO_TRADE reason/version fields.

## 12. Parameters và model selection

Numerical weights, thresholds, look/confirmation windows, ATR buffers, range zones và
minimum RR đều `BACKTEST_REQUIRED`. Confirmation formulas và MVP entry/target models đã
được chốt; PHASE 3 không được thay chúng bằng runtime rule không version hóa.
