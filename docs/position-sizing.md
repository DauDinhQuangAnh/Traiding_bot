# Position Sizing and Fee Model Specification — PHASE 2

## 1. Core invariant

Position size xuất phát từ maximum accepted loss tại protective stop, không từ
`balance × leverage`. Leverage chỉ giới hạn margin requirement sau khi size đã được
tính theo risk.

Mọi phép tính dùng Decimal và explicit unit. Instrument metadata quyết định quantity
là contracts hay base units; không giả định `1 contract = 1 BTC`.

## 2. Inputs

- `TradeCandidate`: side, reference entry, structural stop, targets.
- `RiskContext`: eligible equity, margin, exposure, limits, fresh quote/health.
- `InstrumentMetadata`: contract type/value, tick size, lot size, minimum quantity/
  notional, maximum order size, supported leverage/margin modes, version/effective time.
- `FeeModel`: estimated entry/exit fee, funding, spread and slippage.
- Typed risk/execution config and injected clock.

Output là `RiskDecision`; chỉ APPROVE đi cùng immutable `ApprovedTradePlan`.

## 3. Eligible equity và risk budget

`eligible_equity` là reconciled account equity được phép dùng, sau khi loại trừ phần
không available/không thuộc account scope theo policy. Nó phải dương và fresh.

```text
per_trade_budget = eligible_equity × risk_per_trade
remaining_daily_loss_capacity = max(0, max_daily_loss + daily_net_pnl)
risk_budget = min(per_trade_budget, remaining_daily_loss_capacity)
```

`risk_per_trade` là Decimal ratio `BACKTEST_REQUIRED`. Nếu risk budget không dương,
daily/portfolio limits đã hit, equity stale hoặc account unreconciled thì reject/halt;
không fallback sang balance cached.

## 4. Conservative fill prices

Fee/slippage model trả conservative prices/costs theo side và order role:

- LONG entry adverse fill không thấp hơn reference; LONG stop adverse fill không cao
  hơn stop trigger.
- SHORT entry adverse fill không cao hơn reference; SHORT stop adverse fill không
  thấp hơn stop trigger.
- Spread và slippage phải có definitions loại trừ double counting. Nếu simulated fill
  price đã bao full spread thì `spread_cost` reporting không được trừ lần nữa.

Stop gap/market impact không được coi bằng zero; scenario stress phải cho phép fill
vượt stop/slippage budget. Approval dùng conservative configured buffer, còn realized
loss có thể lớn hơn trong gap — đây là residual risk phải báo cáo.

## 5. Worst-case loss per quantity unit

MVP core chỉ hỗ trợ linear quote-margined contract có `contract_value_base` hợp lệ.
Với `q` contracts:

```text
base_quantity(q) = q × contract_value_base
notional(q, price) = base_quantity(q) × price
price_loss(q) = base_quantity(q) × abs(adverse_entry_fill - adverse_stop_fill)
fee(q, price, rate) = notional(q, price) × rate
```

Metadata là linear nhưng thiếu unit/value, hoặc instrument inverse/unsupported, phải
REJECT `INSTRUMENT_UNSUPPORTED`; không đoán multiplier. Với metadata conversion hợp lệ:

```text
price_loss(q) = absolute quote-currency loss from
                adverse_entry_fill to adverse_stop_fill

entry_fee(q) = FeeModel.entry_fee(adverse_entry_fill, q, assumed_entry_role)
stop_exit_fee(q) = FeeModel.exit_fee(adverse_stop_fill, q, TAKER)
slippage_cost(q) = explicit residual slippage not already in adverse prices
funding_debit_buffer(q) = conservative non-negative funding cost before stop horizon

worst_case_loss(q) = price_loss(q)
                     + entry_fee(q)
                     + stop_exit_fee(q)
                     + slippage_cost(q)
                     + funding_debit_buffer(q)
```

Với linear instrument đơn giản, approximation trước metadata/rounding:

```text
loss_fraction = abs(entry - stop) / entry
                + entry_fee_rate
                + stop_exit_fee_rate
                + slippage_buffer_rate
                + applicable_funding_buffer_rate

raw_notional = risk_budget / loss_fraction
```

Approximation không được dùng để đặt order; final calculation luôn dùng metadata
conversion và recompute theo quantity đã quantize.

## 6. Caps và leverage

```text
risk_limited_quantity = solve_max_q(worst_case_loss(q) <= risk_budget)

notional_cap = min(
    max_position_notional,
    max_total_exposure - current_exposure,
    eligible_equity × max_leverage,
    available_margin × allowed_leverage_adjusted_for_buffer,
    instrument_order_cap
)

cap_limited_quantity = metadata.quantity_for_notional(notional_cap, entry_price)
pre_round_quantity = min(risk_limited_quantity, cap_limited_quantity)
```

Leverage dùng `min(risk.target_leverage, risk.max_leverage,
instrument_max_leverage)`, sau đó validate `>= 1`.
Tăng leverage không làm tăng risk budget hoặc risk-limited quantity. Nếu margin không
đủ ở leverage cap thì giảm quantity hoặc reject; không vượt cap.

## 7. Precision and rounding algorithm

1. Tính `pre_round_quantity` bằng Decimal.
2. Quantize xuống exchange `lot_size`/contract step (floor toward zero).
3. Recompute notional, required margin và toàn bộ worst-case loss.
4. Nếu worst-case loss > budget do nonlinear fees/metadata, giảm từng lot hoặc giải
   lại bằng monotonic search; không bao giờ round lên.
5. Validate minimum quantity/notional. Nếu dưới minimum: REJECT
   `POSITION_SIZE_TOO_SMALL`, không tăng quantity để ép trade.
6. Validate maximum size/exposure/leverage/margin.
7. Chỉ APPROVE nếu recomputed `worst_case_loss <= risk_budget`.

Price quantization theo tick phải adverse/conservative cho validation: LONG entry
round up, stop round down, target round down; SHORT entry round down, stop round up,
target round up. Nếu venue trigger rule đòi rounding khác, adapter có thể làm bảo thủ
hơn nhưng không được giảm computed loss hoặc tăng reward.

## 8. Stop validation

- LONG yêu cầu `stop < entry`; SHORT yêu cầu `stop > entry`.
- Absolute/fraction/ATR-normalized distance đều dương và finite.
- Distance phải nằm trong configured min/max ATR/tick/spread guards.
- Stop có structural provenance (swing/S&R/market structure + configured ATR buffer).
- Không kéo stop gần hơn chỉ để tăng size/RR.
- Liquidation buffer/margin model, khi có metadata, phải đảm bảo stop nằm trước vùng
  liquidation theo conservative policy; chưa đặc tả được → reject.

## 9. Reward/risk validation

Expected net reward dùng target fill estimate trừ entry/target fees, spread/slippage
và applicable funding. Expected loss dùng worst-case loss cùng quantity.

```text
expected_rr = expected_net_reward / worst_case_loss
```

RR denominator phải dương. Target bị level cản hoặc expected RR dưới configured
minimum dẫn tới `RR_TOO_LOW`. Risk Engine tính độc lập để phát hiện candidate stale/
khác cost context; không tin nguyên planned RR từ Strategy.

## 9.1 Approval invariants

Risk Engine chỉ APPROVE khi tất cả đều đúng sau quantization/recomputation:

```text
entry_price > 0
quantity > 0
risk_budget > 0
worst_case_loss > 0
worst_case_loss <= risk_budget
account_equity > 0
eligible_equity > 0
notional <= max_position_notional
total_exposure_after <= max_total_exposure
open_position_count < max_open_positions
1 <= leverage <= max_leverage
expected_rr >= minimum_rr

LONG:  stop_price < entry_price < every target_price
SHORT: every target_price < entry_price < stop_price
sum(target.quantity_fraction) = 1
```

Health (cả bốn subsystem `HEALTHY`), reconciliation, daily, cooldown, open-position,
spread và slippage gates cũng phải pass.
Mỗi invariant fail trả canonical ReasonCode và `REJECT`, trừ health/limit condition
được registry quy định `HALT`. Execution không được tăng quantity/leverage, dời stop
xa entry hoặc dời target để làm plan rủi ro hơn.

## 10. `FeeModel` interface

Đây là port, chưa có implementation:

| Operation | Inputs | Output/contract |
|---|---|---|
| `estimate_entry_fee` | instrument, side, price, quantity, assumed role, as_of | Decimal quote-currency fee, không âm |
| `estimate_exit_fee` | instrument, side, price, quantity, assumed role, as_of | Decimal quote-currency fee, không âm |
| `estimate_funding` | instrument, side, notional, open/close interval, as_of data | Signed cash flow; adverse buffer được tách rõ |
| `estimate_spread_cost` | quote/reference price, side, quantity | Decimal cost không âm |
| `estimate_slippage` | side, order intent, quantity, market context | Adverse price hoặc cost cùng explicit semantics |
| `estimate_cost_rates` | instrument, side, market context, conservative notional cap, funding horizon | `CostRateEstimate` dùng cho pre-size planned RR |
| `calculate_realized` | execution reports, funding events | `FeeBreakdown`, không dùng estimate thay actual |

Fee schedule/funding rate có version và effective time. Backtest phải dùng schedule
lịch sử khi có; nếu thiếu thì dùng conservative scenario được ghi rõ, không dùng phí
hiện tại như sự thật lịch sử.

Maker fee chỉ được giả định khi fill model chứng minh maker execution. Protective stop
exit luôn modeled taker/adverse khi approval; realized accounting dùng liquidity role
từ execution report. Funding có thể signed, nhưng profitability report phải tách funding
credit khỏi strategy edge.

## 11. PnL accounting

```text
net_pnl = gross_pnl
          - entry_fee
          - exit_fee
          - spread_cost_not_embedded_in_fills
          - slippage_cost_not_embedded_in_fills
          + funding_cash_flow
```

`funding_cash_flow > 0` là credit và `< 0` là debit. Không vừa điều chỉnh fill price
vừa trừ lại cùng spread/slippage.

Backtest/analytics không được đánh giá profitability chỉ bằng gross PnL.

## 12. Reason codes

- Plan: `INVALID_STOP`, `STOP_TOO_CLOSE`, `STOP_TOO_FAR`, `TARGET_INVALID`, `RR_TOO_LOW`.
- Entry: `INVALID_ENTRY_PRICE`.
- Sizing: `RISK_BUDGET_EXCEEDED`, `POSITION_SIZE_TOO_SMALL`, `POSITION_CAP_EXCEEDED`,
  `LEVERAGE_CAP_EXCEEDED`, `INSUFFICIENT_MARGIN`, `INSTRUMENT_METADATA_STALE`,
  `RISK_BUDGET_INVALID`, `MAX_OPEN_POSITIONS`.
- Instrument: `INSTRUMENT_UNSUPPORTED`.
- Market cost: `SPREAD_TOO_WIDE`, `SLIPPAGE_TOO_HIGH`.
- Numerical/config: `NUMERICAL_ERROR`, `CONFIG_INVALID`.

## 13. Required tests cho PHASE 3+

- LONG/SHORT mirrored price-loss cases.
- Fee-inclusive size nhỏ hơn/equal size bỏ phí.
- Floor rounding và recomputation luôn giữ loss trong budget.
- Minimum lot/notional reject, never round up.
- Mọi cap độc lập và kết hợp; leverage không thay risk budget.
- Contract value/lot/tick conversion fixtures cho linear swap metadata.
- Stop min/max, wrong side, zero distance và liquidation buffer.
- Maker/taker/funding/spread/slippage scenarios; không double count.
- Stale metadata/quote/account, Decimal overflow/invalid operation → fail closed.
- Property: với valid monotonic fee model, approved quantity là non-negative và
  `worst_case_loss <= risk_budget`.

## 14. Open calibration items

Risk per trade, leverage/notional caps, stop ATR bounds/buffer, RR minimum, assumed
holding horizon, fee/funding/slippage scenarios và margin buffer đều
`BACKTEST_REQUIRED` hoặc cần OKX Demo contract validation. Không giá trị nào trong
tài liệu này là recommendation giao dịch.
