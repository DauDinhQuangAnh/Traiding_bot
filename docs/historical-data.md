# Historical Data Foundation — PHASE 4

## 1. Purpose

PHASE 4 provides a deterministic, point-in-time, offline data foundation for
`BTC-USDT-SWAP`. It turns reviewable local CSV input into versioned canonical M5,
derived M15/H1 datasets and `MarketSnapshot` sequences consumable by the approved
PHASE 3 pipeline. It is not an execution simulator or a complete backtest engine.

## 2. Raw data versus canonical data

`RawHistoricalRecord` and `Candle` are deliberately separate. Raw records preserve
source strings, file/row diagnostics, content hash and payload hash. Parsing never
constructs a `Candle`. Normalization is the only boundary allowed to construct one,
and every row produces either an accepted candle or a typed rejection.

```text
local CSV bytes
→ RawHistoricalRecord
→ HistoricalNormalizationResult
→ dedupe/order/gap validation
→ HistoricalDataset + DatasetManifest + DataQualityReport
```

Rejected records are never silently skipped into a valid dataset. A mixed accepted/
rejected ingestion is `PARTIAL`, carries no backtest-eligible dataset, and requires an
explicit source correction/new build.

## 3. Supported formats

MVP raw input supports CSV through the source-agnostic `HistoricalDataParser` protocol.
`CsvHistoricalDataParser` receives an explicit canonical-field-to-header mapping. JSONL
or Parquet can implement the same lossless parser contract later; neither is inferred
from an extension. No Pandas, Polars, PyArrow, network, or exchange dependency is used.

Required canonical raw fields are timestamp, open, high, low, close, volume, symbol,
timeframe, and closed status. Missing schema is a typed ingestion failure.

## 4. Timestamp semantics

The parser configuration declares both dimensions; no magnitude heuristic is allowed:

- `TimestampConvention`: `OPEN_TIME` or `CLOSE_TIME`.
- `TimestampUnit`: `ISO8601`, `UNIX_SECONDS`, or `UNIX_MILLISECONDS`.

ISO8601 requires an explicit timezone and is normalized to UTC. UNIX values are parsed
as Decimal strings and must resolve exactly to microsecond precision. For `OPEN_TIME`,
close is open plus the canonical interval; for `CLOSE_TIME`, open is close minus it.

M5 opens must align to minute 00/05/10…, M15 to 00/15/30/45, and H1 to minute 00.
Misaligned input such as 10:02→10:17 is rejected; normalization never snaps it.

For historical candles, deterministic `event_time` and `receive_time` both equal the
canonical close time. This explicitly means “available at interval close” and does not
claim to reproduce real ingestion latency. No `datetime.now()` enters dataset content.

## 5. Decimal policy

OHLCV fields remain strings in raw records and are passed directly to `Decimal`.
Float inputs, non-finite values, invalid OHLC geometry, non-positive prices and negative
volume are rejected. Canonical SQLite columns store Decimal values as text; canonical
serialization emits Decimal strings.

## 6. Symbol mapping

`historical.symbol_mapping` is the sole mapping registry. The development profile maps
`BTCUSDT` and `BTC-USDT-SWAP` explicitly to `BTC-USDT-SWAP`. Unknown source symbols are
rejected; punctuation or venue naming is never guessed. Timeframe mapping follows the
same explicit rule.

## 7. Normalization

Normalization validates mappings, timestamp semantics, close status, Decimal values,
OHLCV geometry and canonical boundaries. Candle identity is deterministic from source,
canonical symbol, timeframe, open time and data version. Result status is `ACCEPTED` or
`REJECTED`, with canonical reason codes and diagnostic detail.

## 8. Deduplication

The logical key is `(source, symbol, timeframe, open_time)`:

- Same key and canonical payload: exact duplicate; one candle is retained and the
  quality report increments `exact_duplicates`. Dataset eligibility is preserved.
- Same key and different payload: conflicting duplicate; both source records remain
  auditable, `DATA_CONFLICT` is reported, and the dataset build fails.

There is no last-write-wins behavior.

## 9. Conflict policy

PHASE 4 supports only `HistoricalConflictPolicy.FAIL`. This is strict typed config, so
unknown policies fail startup instead of weakening validation. A later correction is a
new source-content hash and data version, never a mutation of the old artifact.

## 10. Ordering and gaps

Raw rows may arrive in any order. Valid unique rows are sorted by open time, while
`out_of_order_count` and `DATA_OUT_OF_ORDER` preserve the diagnostic. Canonical datasets
are strictly increasing.

Gap detection assumes BTC trades continuously. It checks expected intervals only
between the first and last supplied candle: no bar is assumed before dataset start or
after dataset end. Each `Gap` records expected, previous and next open times plus the
missing count. A single or multiple internal missing interval makes the build invalid.
No synthetic candle, forward fill or interpolation exists.

## 11. Cross-timeframe consistency

M5 is the canonical imported base. M15 and H1 are derived from M5. If native higher
timeframes are inspected, `validate_cross_timeframe` requires exact child coverage and
exact OHLCV equality by default. There is no implicit epsilon. A future tolerance policy
must be typed, versioned and explicitly approved before use.

## 12. Resampling

Allowed upward conversions are M5→M15, M5→H1 and M15→H1. Downsampling is rejected.
Each target interval requires exactly 3, 12 or 4 contiguous aligned children:

```text
open   = first child open
high   = max(child highs)
low    = min(child lows)
close  = last child close
volume = sum(child volumes)
```

An incomplete group, child gap or misaligned first interval fails the operation. Derived
source names encode the path, and IDs include ordered child IDs, target timeframe,
resampling algorithm version and data version.

## 13. Dataset manifest

Every valid dataset has a deterministic manifest containing manifest/dataset IDs,
symbol/timeframe, sorted source content hashes, parser/normalizer/resampling/code/config
versions, counts, bounds and canonical candle hash. Absolute path, file modification
time and ingestion wall-clock are excluded. SHA-256 is used for files and canonical
artifacts.

## 14. Data versioning

`data_version` derives from source byte hashes and all parsing/normalization/resampling
semantics plus config version. Therefore it changes when input bytes, correction,
parser semantics or normalization/resampling versions change. Copying identical bytes
to another path does not change dataset, manifest or data version.

All three canonical timeframes share the same bundle data version; timeframe and
canonical content distinguish dataset/manifest IDs. Old versions remain queryable.

## 15. Repository queries

`HistoricalCandleRepository` exposes only explicitly bounded operations:

- `get_candles(symbol, timeframe, start, end, data_version)`
- `latest_before(symbol, timeframe, as_of, count, data_version)`

SQLite stores versioned immutable candles and manifests transactionally, with uniqueness
on dataset identity and `(data_version, symbol, timeframe, open_time)`. Unknown versions
fail explicitly. There is no unbounded `get_latest()` in the replay path.

## 16. Point-in-time rules

Every returned candle satisfies `close_time <= as_of`. An H1 candle still forming at
the cutoff is excluded. Adding a future or corrected dataset creates another version;
querying the persisted old version before and after that append is byte-identical.

This resolves an apparent acceptance tension: IDs intentionally contain `data_version`,
so replaying the same cutoff under a *new* version must produce new audit IDs. The
look-ahead invariant is instead proven by querying/replaying the same immutable old
version after newer versions are stored. Market values may also be compared separately,
but IDs from different versions must not be asserted equal.

## 17. Snapshot generation

Each closed M15 candle in the bounded trigger range is an evaluation candidate. The
builder obtains `required_bars()` for every timeframe, requests only candles closing by
the trigger cutoff, and skips early triggers until all three histories satisfy warm-up.
It does not reduce indicator requirements or borrow future bars. It then calls the
existing typed PHASE 3 snapshot builder with `quote=None` and deterministic
`created_at=as_of`.

Historical OHLCV has no fabricated bid/ask quote. PHASE 3 market strategy may produce
a candidate, but historical execution/risk approval assumptions belong to PHASE 5.
Any quote used by isolated tests is labelled synthetic test data.

## 18. Data corrections

A corrected file produces a new SHA-256 source hash, data version, candles and manifests.
SQLite retains both versions. Existing snapshot/replay artifacts retain their original
version and reproduce without retroactive edits.

## 19. Reproducibility

Golden tests pin canonical first/last candles, dataset/manifest IDs, canonical hash and
serialized artifact hashes. Integration tests ingest identical bytes at different paths,
recreate SQLite storage, rebuild snapshots and replay PHASE 3; manifests, snapshot IDs,
decisions, regimes, signals and candidate IDs are canonical-equal.

## 20. Backtest eligibility

A dataset is eligible only when normalization has no rejected rows, identity/timeframe
is supported, conflict count and gap count are zero, order is strict, keys are unique,
manifest is complete and data version exists. Exact duplicates may be deduplicated while
remaining fully reported. `PARTIAL` and `FAILED` ingestion never expose an eligible
dataset.

## 21. Limitations and performance

- CSV is the only raw format in this phase.
- Canonical SQLite is development-scale; no unmeasured throughput claim is made.
- Parser iteration is streaming, but dataset-wide deterministic sorting/deduplication
  currently materializes one single-symbol/timeframe build dataset in memory.
- Historical receive latency, bid/ask, funding and execution fills are not modeled.
- Native higher-timeframe tolerance reconciliation is validation-only and exact.

Core scans are O(N log N) for canonical sorting and O(N) for validation/resampling.
Correctness, determinism and auditability take precedence over premature chunking.

## 22. PHASE 4 acceptance criteria

Acceptance requires typed lossless parser/normalizer results; UTC/boundary/Decimal
validation; explicit mappings; duplicate/conflict/gap behavior; deterministic upward
resampling; cross-timeframe validation; path-independent SHA-256 manifests/data version;
immutable point-in-time repository; warm-up-safe snapshot sequence; deterministic PHASE
3 replay; future/correction isolation; no network/exchange/strategy changes; all local
quality gates passing; and an actual green run of the existing Python 3.12 CI workflow.
Configuration alone is not CI evidence: until that run exists, the review status remains
`NEEDS_WORK` and PHASE 5 must not begin.
