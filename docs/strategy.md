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
- `LevelSet` chứa canonical `MarketStructure` và optional `RangeContext`
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
4. Setup nằm trong regime/setup table tại §6.
5. SIDEWAY location hợp lệ; middle bị block tuyệt đối.
6. Breakout chỉ eligible sau `RETEST_VALIDATED`.

Active-position, pending-intent và duplicate-evaluation gates thuộc orchestration/Risk,
không thuộc Strategy vì Strategy không nhận account/order state.

## 3. Component model

Canonical initial component registry:

| `SignalComponentName` | Evidence keys | Constraint |
|---|---|---|
| `TREND` | `regime_alignment`, `ema_alignment`, `pullback` | M15 signal geometry + confirmed regime; không tự quyết định trade |
| `MOMENTUM` | `rsi`, `rsi_slope` | M15 RSI; RSI đơn lẻ không quyết định |
| `STRUCTURE` | `market_structure` | Canonical M15 structure confirmed tại `as_of` |
| `LEVEL` | `proximity` | Setup-specific selected level; SIDEWAY middle gate fail |
| `VOLUME` | `volume_ratio` | M15 relative volume cùng source/unit/window version |
| `CONFIRMATION` | `closed_candle` | Final child M5 candle đã đóng và kết thúc cùng trigger M15 |

Mỗi `SignalComponent` lưu `component_name`, `long_points`, `short_points`,
`max_points`, evidence, reason codes và config version. Points/weights là Decimal,
không âm; tổng configured maxima đúng 100.

`strategy.component_max_points` có đúng sáu enum keys và tổng 100. Nếu component
disabled, `max_points=0`, evidence weights rỗng và không redistribute ngầm. Một
experiment muốn redistribute phải có config/strategy version mới.

Các hàm canonical dùng chung:

```text
clamp01(x) = min(1, max(0, x))
ramp_up(x, start, full) = clamp01((x - start) / (full - start))
ramp_down(x, full, zero) = 1 - ramp_up(x, full, zero)
```

Notation canonical cho Strategy V1:

```text
c15 = trigger 15m candle = last(snapshot.candles_15m), c15.close_time = snapshot.as_of
c5 = last(snapshot.candles_5m), c5.close_time = c15.close_time
i = indicators.values_by_timeframe[M15]
s = level_set.market_structure                 # levels.structure_timeframe = M15
r = regime_assessment
setup, setup_side = kết quả duy nhất của §6
band = strategy.momentum.rsi_bands[setup]
```

Selected signal level được xác định trước scoring:

- `TREND_PULLBACK/LONG`: active support có `zone_lower <= c15.close`, chọn price lớn
  nhất, tie chọn `level_id` lexicographically nhỏ nhất. SHORT đối xứng với active
  resistance có `zone_upper >= c15.close`, price nhỏ nhất, cùng tie-break.
- `SIDEWAY_MEAN_REVERSION`: LONG dùng range support; SHORT dùng range resistance.
- `BREAKOUT_RETEST`: LONG dùng resistance boundary vừa retest; SHORT dùng support
  boundary vừa retest.

```text
distance_to_selected_level_atr =
  0, nếu zone_lower <= c15.close <= zone_upper
  min(abs(c15.close-zone_lower), abs(c15.close-zone_upper)) / i.atr, nếu ngoài zone
```

Với `i.atr > 0`, evidence strength được tính chính xác như sau; mọi strength không
được liệt kê cho direction/setup hiện tại bằng zero:

| Component / evidence key | LONG strength | SHORT strength |
|---|---|---|
| `TREND.regime_alignment` | `r.candidate_scores[TREND_UP]` iff `r.regime=TREND_UP` và setup LONG, else 0 | `r.candidate_scores[TREND_DOWN]` iff `r.regime=TREND_DOWN` và setup SHORT, else 0 |
| `TREND.ema_alignment` | 1 iff aligned TREND_UP setup và `i.ema20 > i.ema50 > i.ema200`, else 0 | 1 iff aligned TREND_DOWN setup và `i.ema20 < i.ema50 < i.ema200`, else 0 |
| `TREND.pullback` | `ramp_down(abs(c15.close-i.ema20)/i.atr, 0, strategy.trend_pullback_tolerance_atr)` iff aligned TREND_UP setup, else 0 | Cùng formula iff aligned TREND_DOWN setup, else 0 |
| `MOMENTUM.rsi` | 1 iff `band.long_min <= i.rsi <= band.long_max`, else 0 | 1 iff `band.short_min <= i.rsi <= band.short_max`, else 0 |
| `MOMENTUM.rsi_slope` | `ramp_up(i.rsi_slope, 0, strategy.momentum.rsi_slope_full)` | `ramp_up(-i.rsi_slope, 0, strategy.momentum.rsi_slope_full)` |
| `STRUCTURE.market_structure` | 1 iff `s.trend=BULLISH`, else 0 | 1 iff `s.trend=BEARISH`, else 0 |
| `LEVEL.proximity` | `ramp_down(distance_to_selected_level_atr, strategy.level_full_strength_distance_atr, strategy.level_zero_strength_distance_atr)` iff selected LONG level exists, else 0 | Cùng formula iff selected SHORT level exists, else 0 |
| `VOLUME.volume_ratio` | `ramp_up(i.volume_ratio, strategy.volume.ratio_start, strategy.volume.ratio_full)` iff bullish confirmation true, else 0 | Cùng ramp iff bearish confirmation true, else 0 |
| `CONFIRMATION.closed_candle` | 1 iff bullish confirmation below is true, else 0 | 1 iff bearish confirmation below is true, else 0 |

SIDEWAY đặt toàn bộ `TREND` evidence hai phía bằng zero. Missing selected level đặt
`LEVEL.proximity=0`; candidate builder sau đó fail nếu thiếu invalidation anchor.
`i.volume_ratio` chỉ tồn tại khi configured volume mean dương và đủ history; nếu không,
Indicator Engine trả not-ready/invalid và Strategy không được gọi.

Mỗi row/evidence key tạo một `SignalEvidence`: `long_observed_value` và
`short_observed_value` là hai directional operands cuối trước normalize (binary 0/1,
RSI, signed RSI slope, ATR distance hoặc volume ratio). `unit` là `binary`,
`rsi_point`, `atr_multiple` hoặc `ratio`; `source_ids` chứa trigger candle, indicator
assessment, regime/level IDs đã dùng. Không được tạo evidence chỉ bằng text.

Mỗi component dùng:

```text
component_strength(direction) =
  sum(evidence_strength[name]
      × strategy.component_evidence_weights[component][name])
component_points(direction) =
  strategy.component_max_points[component] × component_strength(direction)
```

Evidence weights của component phải tổng 1. `SignalEvidence` lưu từng operand,
strength và source IDs; không chỉ lưu câu mô tả.

Khi một setup yêu cầu component strength dương, gate canonical là:

```text
directional_component_gate(component, direction) =
  strategy.component_max_points[component] == 0
  OR component_points(direction) > 0
```

Vì vậy disable component bằng max points zero cũng disable riêng gate của component đó;
không có khái niệm optional evidence ngầm.

### Closed-candle confirmation

Với `c5`, tức 5m confirmation candle cuối cùng nằm trọn trong trigger 15m:

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

Sau khi chọn theo thứ tự trên, setup chỉ đi tiếp nếu nằm trong
`strategy.allowed_setups`; nếu không trả `NO_TRADE` + `SETUP_DISABLED`.

### Trend

- TREND_UP: chỉ setup LONG theo trend trong MVP.
- TREND_DOWN: chỉ setup SHORT theo trend trong MVP.
- Counter-trend score có thể được tính để diagnostic nhưng bị regime gate block.
- Pullback pass khi `abs(c15.close - i.ema20) / i.atr <=
  strategy.trend_pullback_tolerance_atr`;
  opposing level phải cho target hợp lệ theo §7. ATR invalid → NO_TRADE.

### SIDEWAY mean reversion

- `MIDDLE`: luôn `NO_TRADE`; không gọi candidate builder.
- `NEAR_SUPPORT`: chỉ LONG nếu bullish closed-candle confirmation,
  `directional_component_gate` của `VOLUME` và `MOMENTUM`, scores, confluence và
  cost-adjusted RR pass.
- `NEAR_RESISTANCE`: chỉ SHORT với điều kiện đối xứng.
- Overlapping edge zones/range invalid: `NO_TRADE`, không chọn nearest side.

### Breakout

- `BREAKOUT_DETECTED`, `WAIT_CONFIRMATION`, `WAIT_RETEST`: `NO_TRADE`.
- Chỉ `RETEST_VALIDATED` có thể mở scoring gate theo breakout direction.
- State expired/invalidated hoặc không có retest: `NO_TRADE`; không FOMO market price.

### Blocked regimes

HIGH_VOLATILITY và UNCERTAIN không tạo candidate bất kể score.

## 7. Candidate construction

Candidate builder chỉ được gọi khi market snapshot hợp lệ, indicators ready, regime
không blocked, setup/side duy nhất, score/confluence/advantage pass và confirmation
pass. Thứ tự bắt buộc:

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
   `zone_lower > entry` nhỏ nhất, tie chọn `level_id` lexicographically nhỏ nhất;
   target = `zone_lower`. SHORT chọn active support có `zone_upper < entry` lớn nhất,
   cùng tie-break; target = `zone_upper`. Không có target →
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
10. Phát immutable `TradeCandidate` không có quantity/leverage; attach confirmed
    regime, selected/opposite scores, assessment/level IDs, `CostRateEstimate`,
    setup/entry/target enums, reason metadata và versions.

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
  `SETUP_DISABLED`, `BREAKOUT_CONFIRMATION_PENDING`, `RETEST_PENDING`,
  `RETEST_INVALIDATED`, `RETEST_EXPIRED`.
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
