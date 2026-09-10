# Market Data and Indicator Contract — PHASE 2

## 1. Scope

Tài liệu định nghĩa dữ liệu đầu vào và contract `MarketSnapshot → IndicatorSnapshot`.
Không chọn vendor/API, không gọi OKX và không implement indicator trong PHASE 2.

## 2. Pipeline

```text
Exchange/Historical Source
→ Raw Candle/Event
→ Schema Validation
→ Normalization
→ Deduplication
→ Ordering Buffer
→ Gap Detection / Backfill
→ Closed Candle Store
→ Multi-Timeframe Snapshot
→ Indicator Engine
```

Mọi stage trả kết quả explicit cùng reason codes. Record invalid không được âm thầm
sửa hoặc đưa vào closed store.

## 3. Time semantics

| Field | Definition |
|---|---|
| `event_time` | Thời điểm source/exchange phát hoặc xác nhận event |
| `receive_time` | Thời điểm process local nhận event, lấy từ injected `Clock` |
| `open_time` | Đầu interval candle theo UTC |
| `close_time` | Cuối interval; candle chỉ usable sau khi source xác nhận closed |
| `as_of` | Cutoff point-in-time của snapshot/evaluation; không field nào được phụ thuộc dữ liệu sau mốc này |

Event time dùng ordering/point-in-time semantics; receive time dùng đo latency và
replay arrival behavior. Không thay event time bằng receive time. Clock drift vượt
tolerance làm data health degraded/unhealthy, không tự dịch timestamp để “khớp”.

## 4. Timeframe contract

- `5m`: micro structure và confirmation; phải có đủ ba closed candles tương ứng với
  interval 15m vừa đóng.
- `15m`: timeframe entry và trigger duy nhất của evaluation định kỳ.
- `1h`: context/regime; chỉ dùng candle 1h đã được source xác nhận `is_closed=true`.

Khi candle 15m đóng tại `T`, snapshot lấy mọi candle có `close_time <= T`. Nếu `T`
nằm giữa candle 1h, candle 1h đang chạy bị loại; lấy candle 1h đã đóng gần nhất.
Không tổng hợp 1h bằng 15m tương lai và không chờ rồi retroactively đổi decision cũ.

## 5. Raw validation và normalization

Validation trước normalize:

- Required source fields hiện diện và parse được losslessly.
- Timestamp timezone-aware, interval đúng timeframe và aligned UTC boundary.
- OHLC dương, volume không âm, high/low bao OHLC hợp lệ.
- Symbol mapping được biết; unknown symbol/timeframe bị reject.
- Closed status explicit; không suy đoán closed chỉ từ local wall clock.

Normalization:

- Map symbol/timeframe/status sang canonical enum/value.
- Parse price/volume trực tiếp thành Decimal từ chuỗi; không đi qua float.
- Gắn `source`, event/receive time và deterministic candle ID.
- Preserve raw event immutable để audit/replay; normalized correction là version mới.

## 6. Deduplication và ordering

Canonical candle key: `(source, symbol, timeframe, open_time)`. Cùng key và cùng
payload hash là duplicate: không phát domain event lần hai, nhưng có thể tăng metric.
Cùng key nhưng payload khác là correction/conflict:

1. Không overwrite immutable raw record.
2. Lưu revision mới với provenance.
3. Nếu evaluation liên quan đã chạy, journal `DATA_CORRECTION`; không sửa lịch sử
   decision. Backtest mới dùng data version mới.
4. Live/demo đang chạy phải block evaluation cho tới khi conflict được resolve.

Out-of-order event nằm trong configured ordering window được buffer và sắp theo
`event_time`/sequence. Ngoài window tạo `DATA_OUT_OF_ORDER`; không đưa vào snapshot
cho đến khi consistency được xác minh.

## 7. Gap detection và stale data

Với mỗi timeframe, expected next open time bằng previous open time cộng interval.
Thiếu một interval tạo `DATA_GAP` và pipeline:

1. Đánh dấu series incomplete.
2. Chặn snapshot/evaluation bị ảnh hưởng.
3. Yêu cầu backfill từ provider.
4. Validate/dedupe backfill như dữ liệu thường.
5. Vượt retry/health policy → `DATA_UNHEALTHY` và có thể `HALT`.

Không tạo synthetic candle zero-volume để lấp gap. Market closure không được giả
định cho thị trường BTC 24/7 nếu không có source evidence.

Staleness được kiểm tra riêng:

- Candle stream: last expected closed interval so với `as_of`.
- Quote: `as_of - quote.event_time`.
- Account/position: freshness thuộc RiskContext, không market snapshot.

Vượt configured SLA tạo `DATA_STALE`; stale data không được dùng để approve trade.

## 8. Closed candle store

Logical key: symbol/timeframe/open time/data version. Store phải hỗ trợ:

- Append/revision history, point-in-time query theo `as_of` và data version.
- Unique constraint cho canonical key + revision/hash.
- Query đủ lookback theo timeframe trong deterministic order.
- Transactional write trước phát `CandleClosed` event.
- UTC và Decimal lossless serialization.

Raw và normalized store không nhất thiết cùng database, nhưng provenance phải nối được.

## 9. Snapshot construction

Evaluation key:

```text
(symbol, entry_candle_close_time, strategy_version, config_version)
```

Snapshot builder phải:

1. Acquire consistent read at data version/cutoff.
2. Xác nhận trigger 15m closed và chưa có evaluation cùng key.
3. Load configured lookback cho 5m/15m/1h.
4. Reject duplicate, gap, out-of-order hoặc future candle.
5. Verify 5m children khớp 15m trigger và 1h context đã closed.
6. Gắn quote nếu fresh; historical feed có thể không có quote, nhưng execution risk
   approval sau này bắt buộc quote thật/fresh.
7. Tạo immutable `MarketSnapshot` và `data_version` hash/manifest.

Snapshot construction fail vẫn tạo decision journal `NO_TRADE` với reason code và
failure context thích hợp, nhưng không tạo partial `MarketSnapshot` hoặc đưa partial
series vào Indicator Engine như thể hợp lệ.

## 10. Look-ahead/data-leakage controls

- Repository point-in-time query luôn có upper bound `close_time <= as_of`.
- Swing/structure point chỉ usable từ `confirmed_at`, không từ candle pivot ban đầu.
- Indicator chỉ update theo sequence candle đã đóng.
- Backfill/correction nhận sau không thay decision trong run cũ; tạo data version mới.
- Train/optimization split theo chronological time; fit scaler/percentile chỉ trên
  training window, rồi freeze cho validation/test.
- Funding/fee/instrument metadata dùng version có effective time, không dùng current
  values cho quá khứ.
- Test bắt buộc inject một future candle và chứng minh output trước đó không đổi.

## 11. Indicator Engine contract

Input: một `MarketSnapshot` hợp lệ.

Output: một `IndicatorSnapshot` immutable cùng `as_of`, snapshot ID và versions.

Indicator set:

- EMA20, EMA50, EMA200: value, slope/normalized distance có thể được derived bởi
  regime layer nhưng phải point-in-time.
- RSI: canonical configured method/period; value `[0,100]`.
- ATR: configured method/period; Decimal không âm, cùng price unit.
- ADX: configured method/period; value `[0,100]`; directional indices nếu dùng phải
  được thêm vào typed auxiliary contract.
- Bollinger Bands: upper/middle/lower, configured window/deviation; ordered values.
- Volume statistics: rolling mean/median/ratio/dispersion theo fields được config và
  version hóa; không so volume giữa source/unit không tương thích.

Indicator algorithm, initialization method (SMA seed/Wilder/EMA variant), period,
adjustment và rounding là một phần của `strategy_version`; cùng input/version phải
cho output giống nhau.

## 12. Warm-up requirements

Engine tính derived minimum history cho từng timeframe:

```text
required_bars(timeframe) = max(
    ema_max_period + ema_stabilization_bars,
    rsi_required_bars,
    atr_required_bars,
    adx_required_bars,
    bollinger_required_bars,
    volume_required_bars,
    structure_required_bars
)
```

EMA200 cần ít nhất period history, nhưng stabilization buffer là
`BACKTEST_REQUIRED`; không khẳng định đúng một giá trị chung. ADX/RSI/ATR warm-up
phụ thuộc phương pháp initialization đã chọn và phải có test fixture xác nhận.

Nếu bất kỳ required series/indicator nào thiếu:

- `IndicatorSnapshot.is_ready=false`.
- `missing_requirements` liệt kê exact timeframe/indicator/count.
- Reason code canonical `INDICATOR_NOT_READY`.
- Decision bắt buộc `NO_TRADE`; không forward-fill, backfill giả hoặc dùng zero.

## 13. Provider ports

`MarketDataProvider` contract logic:

- `stream_events(symbols, timeframes) -> async events`
- `fetch_candles(symbol, timeframe, start, end, limit) -> candles`
- `fetch_latest_quote(symbol) -> Quote`
- `health() -> HealthSnapshot`

`Clock` contract: `now_utc()` và monotonic elapsed time cho timeout. Domain không gọi
system clock trực tiếp. Provider implementation/specific OKX schema nằm ngoài domain.

## 14. Required tests cho PHASE 3+

- OHLC/Decimal/timezone validation và lossless round-trip.
- Duplicate identical payload, correction conflict và out-of-order boundary.
- Gap detection/backfill success/failure; tuyệt đối không synthetic fill.
- 15m trigger mapping đúng ba 5m children.
- 1h in-progress exclusion tại mọi quarter-hour trigger.
- Snapshot deterministic theo data version và evaluation ID.
- Indicator known-value fixtures cho từng algorithm/initialization.
- Warm-up boundary `required-1`, `required`, missing one timeframe.
- Future candle/corrected-later data không thay historical decision.
