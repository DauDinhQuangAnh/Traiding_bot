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

- Luôn có `SignalAssessment` và `DecisionRecord`.
- Chỉ có `TradeCandidate` khi direction, setup và planned RR đều hợp lệ.

## 2. Evaluation gates trước scoring

Gate fail dẫn trực tiếp `NO_TRADE` với reason code, nhưng có thể vẫn ghi diagnostic
components nếu input an toàn để tính:

1. Snapshot complete/fresh và indicator ready.
2. Versions/as-of/symbol nhất quán.
3. Regime không `UNCERTAIN`/blocked high volatility.
4. Không có active position/pending candidate theo orchestration policy.
5. Setup phù hợp regime.
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

## 4. Score aggregation

```text
long_score  = sum(component.long_points)
short_score = sum(component.short_points)
```

Both scores phải nằm trong `[0,100]`. Sai total/max/NaN là specification violation,
không clamp im lặng: `NO_TRADE` với `SIGNAL_INVALID` và health escalation.

Evidence có thể đóng góp cho cả hai phía nếu context mixed. Strategy không ép
zero phía đối diện để làm score difference đẹp hơn.

## 5. Direction eligibility

Với thresholds versioned từ config:

```text
long_eligible = regime_allows_long
                AND long_score >= long_threshold
                AND (long_score - short_score) >= minimum_score_difference

short_eligible = regime_allows_short
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

### Trend

- TREND_UP: chỉ setup LONG theo trend trong MVP.
- TREND_DOWN: chỉ setup SHORT theo trend trong MVP.
- Counter-trend score có thể được tính để diagnostic nhưng bị regime gate block.
- Price extension, nearby opposing level hoặc volatility guard có thể block setup.

### SIDEWAY mean reversion

- `MIDDLE`: luôn `NO_TRADE`; không gọi candidate builder.
- `NEAR_SUPPORT`: chỉ LONG nếu bullish closed-candle confirmation, configured volume/
  momentum evidence, scores và cost-adjusted RR pass.
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

1. Chọn eligible direction/setup.
2. Derive entry reference từ configured entry model và available closed context.
3. Derive structural invalidation và stop từ swing/S&R/market structure cộng ATR
   buffer; không dùng fixed percent toàn market.
4. Derive target từ next valid level/target model.
5. Validate stop/target đúng phía và không dùng future level.
6. Estimate gross reward/loss và costs qua `FeeModel`/slippage policy.
7. Tính planned RR before/after costs.
8. Nếu cost-adjusted RR không đạt configured minimum: `NO_TRADE`.
9. Phát immutable `TradeCandidate` không có quantity/leverage.

Strategy không được kéo stop gần entry hoặc bỏ level cản để tăng RR. Risk Engine sẽ
tính lại plan/worst-case loss; khác biệt vượt tolerance dẫn tới reject.

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

## 12. Parameters chưa được hard-code

Weights, thresholds, lookbacks, confirmation definition, ATR buffers, range zones,
entry/target model và minimum RR đều `BACKTEST_REQUIRED`. PHASE 2 chỉ chốt interface,
validation và fail-safe behavior.
