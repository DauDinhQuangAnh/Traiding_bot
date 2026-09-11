# PHASE 4 Plan — Historical Market Data and Dataset Foundation

## 1. Scope

Build an offline, source-agnostic pipeline for `BTC-USDT-SWAP` historical OHLCV:
raw local files → provenance-preserving records → typed normalization → deterministic
deduplication/validation → canonical M5 datasets → derived M15/H1 datasets → versioned
SQLite repository → point-in-time `MarketSnapshot` sequences → existing PHASE 3 replay.

## 2. Non-goals

- No OKX/API/WebSocket/network client, credentials, Demo/Live execution, order, or loop.
- No full backtest execution/fill/PnL engine; that belongs to PHASE 5.
- No strategy, indicator, regime, scoring, state-machine, risk, or threshold changes.
- No production-size market dataset in Git and no profitability claim.

## 3. Data architecture

`RawHistoricalRecord` is lossless source evidence and is never treated as a `Candle`.
A parser emits raw strings plus row/file/content provenance. A normalizer maps explicit
symbol/timeframe/timestamp conventions and emits an accepted canonical `Candle` or a
typed rejection. Dataset building sorts valid rows, audits input disorder, distinguishes
exact from conflicting duplicates, detects gaps, and fails closed for conflicts/gaps.

M5 is the canonical imported base timeframe. M15 and H1 are deterministically derived
from complete M5 groups. Native M15/H1 inputs may be normalized and compared by an
explicit exact/tolerance policy in future, but are not mixed into derived canonical data.

## 4. Package and module changes

```text
src/trading_bot/historical/
  models.py           immutable raw/result/dataset/report contracts
  parsers.py          protocol and configurable streaming CSV parser
  normalization.py    lossless Decimal/time/symbol normalization
  validation.py       dedupe, gap and cross-timeframe checks
  dataset.py          deterministic build and resampling
  repository.py       repository protocol and local SQLite implementation
  manifests.py        SHA-256 content and canonical manifest/version identities
  serialization.py    canonical JSONL dataset export/import helpers
src/trading_bot/application/historical_pipeline.py
tests/fixtures/historical/
data/README.md
```

Configuration gains a strict `historical` group for format/source, parser and
normalization versions, explicit symbol mapping, timestamp convention/unit, conflict
and gap policies, and canonical base timeframe.

## 5. Dataset and storage format

CSV is the raw MVP format because it is reviewable and parsed losslessly as strings.
Canonical storage uses SQLite with numeric/time fields serialized as canonical text,
primary keys including data version, and indexes for bounded range/count queries.
This avoids Pandas/PyArrow dependencies while giving deterministic ordering and
development-scale range queries. Canonical JSON serialization is used for hashing and
golden evidence, not as the query store.

## 6. Provenance model

Each raw record retains source, logical source-file name, one-based source row, raw
symbol/timeframe/timestamp/OHLCV/close status, file content hash, and row payload hash.
Physical absolute paths and file modification times are diagnostic only and never enter
dataset identity. Rejections retain raw-record identity, canonical reason codes, and
sanitized detail.

## 7. Validation pipeline

1. Validate readable file and exact configured CSV schema.
2. Emit raw records without numeric/timestamp inference.
3. Normalize explicit timestamp convention/unit to UTC interval boundaries.
4. Parse OHLCV directly from strings to `Decimal`; reject malformed rows explicitly.
5. Apply explicit symbol/timeframe mappings and closed-status rule.
6. Sort accepted rows by canonical key while reporting input disorder.
7. Dedupe exact payloads; mark any same-key/different-payload conflict fatal.
8. Detect all missing 24/7 intervals without filling or interpolation; any gap is fatal.
9. Build immutable dataset/report/manifest only when invariants permit it.

Expected bad rows produce typed rejections. Unreadable files and malformed schema
produce typed ingestion failure. Programmer/invariant errors still raise.

## 8. Point-in-time semantics

Every repository read requires explicit symbol, timeframe, `data_version`, and either
a bounded time range or `as_of`. Returned candles always satisfy `close_time <= as_of`.
Appending future data or another dataset version cannot alter a prior version/query.
No unbounded `get_latest()` API is exposed on the backtest-critical path.

## 9. Multi-timeframe strategy

- Import canonical M5.
- Derive M15 from exactly three aligned M5 children.
- Derive H1 from exactly twelve aligned M5 children (M15 → H1 is also supported with
  exactly four children and identical aggregation rules).
- Aggregate open=first, high=max, low=min, close=last, volume=sum.
- Reject upward resampling with an incomplete group, gap, misalignment, mixed identity,
  or unsupported/downward conversion.
- Derived IDs include ordered child IDs, target timeframe, resampling algorithm version,
  and data version; source identifies the derivation path.
- Cross-timeframe validation compares exact OHLCV and aligned child coverage by default.
  No undocumented epsilon is used.

## 10. Test strategy

Unit tests cover parser/schema/row failures, time and Decimal normalization, symbols,
dedupe/conflict/order/gaps, all resampling pairs and failures, manifests/versioning,
repository queries, and snapshot warm-up/cutoffs. Golden tests pin canonical dataset,
manifest, and data version. Hypothesis checks aggregation invariants, ordering,
idempotent ingestion, version sensitivity, no duplicate valid keys, no eligible gaps,
and point-in-time stability. Integration tests rebuild storage and replay PHASE 3 twice,
including future append and corrected-version isolation.

## 11. Performance expectations

Parser and normalization are streaming. Dataset validation/build is `O(N log N)` due
to deterministic sorting; sequential gap/dedupe/resampling passes are `O(N)`. SQLite
queries use `(data_version, symbol, timeframe, close_time)` indexes. No benchmark claim
is made in PHASE 4; correctness, determinism, and auditability take priority.

## 12. Acceptance criteria

PHASE 4 passes only when all 27 user acceptance items are evidenced: typed raw parser,
lossless Decimal/UTC normalization, explicit mappings, deterministic dedupe/gaps/
resampling/manifest/data version, point-in-time repository and snapshot sequence,
byte-equivalent PHASE 3 replay/storage rebuild, correction isolation, no look-ahead,
no forbidden dependency or strategy change, complete docs, and all pytest/Ruff/mypy/
compileall gates green. Hosted Python 3.12 remains a separately reported CI status.

## 13. Explicit out of scope

Production data acquisition, network downloaders, Parquet optimization, partial-segment
backtesting, tolerance calibration for native cross-source bars, fill simulation,
portfolio analytics, parameter optimization, and PHASE 5 implementation.
