# PHASE 4 Review — Historical Data Foundation

## Overall status

**NEEDS_WORK pending remediation CI**. GitHub Actions Python 3.12 passed for baseline
commit `635303d`. External review then found two semantic identity gaps: the M5 version
depended on full app config, and derived timeframes reused the M5 version. Both are
remediated locally, but the remediation commit still needs its own green Python 3.12
run and human review. PHASE 3 remains the last approved phase; PHASE 5 must not begin.

## Acceptance evidence

| # | Criterion | Status | Evidence |
|---:|---|---|---|
| 1 | Typed historical raw parser | PASS | `historical/parsers.py`; parser unit tests |
| 2 | No float in parsing | PASS | `historical/normalization.py` parses strings directly to `Decimal` |
| 3 | Deterministic UTC timestamps | PASS | explicit ISO/Unix unit tests |
| 4 | Boundary alignment enforced | PASS | M5/M15/H1 valid and invalid boundary tests |
| 5 | Explicit symbol mapping | PASS | strict `HistoricalConfig`; unsupported-symbol test |
| 6 | Exact/conflicting duplicates distinguished | PASS | deduplication fixture tests and audit counts |
| 7 | Gap detection works | PASS | single/multiple missing-candle tests |
| 8 | Critical gap/conflict invalidates ingestion | PASS | fail-closed dataset tests |
| 9 | Deterministic resampling | PASS | M5→M15, M5→H1 and M15→H1 unit/property tests |
| 10 | Cross-timeframe validation | PASS | exact child coverage/OHLCV consistency tests |
| 11 | Deterministic manifest | PASS | golden and repeated-ingestion tests |
| 12 | Reproducible data version | PASS | semantic isolation, golden and property tests |
| 13 | Same bytes at another path keep identity | PASS | path-independent manifest test and replay rebuild |
| 14 | Content correction creates a version | PASS | content-sensitive property/integration tests |
| 15 | Point-in-time repository queries | PASS | SQLite range/count/cutoff/version tests |
| 16 | Future append cannot alter past result | PASS | immutable old-version query and replay tests |
| 17 | Historical `MarketSnapshot` sequence | PASS | typed per-timeframe versions, composite identity and cutoff tests |
| 18 | PHASE 3 replay consumes historical snapshots | PASS | raw→SQLite→snapshot→existing replay integration |
| 19 | Replay is deterministic | PASS | canonical byte equality across two storage rebuilds |
| 20 | No OKX/network client | PASS | changed-file audit; historical package is local-only |
| 21 | No strategy changes | PASS | changed-file audit; no strategy source modified |
| 22 | No threshold optimization | PASS | changed-file audit; example strategy config unchanged |
| 23 | Python 3.12 CI passes | PASS for baseline | GitHub Actions passed for `635303d`; remediation run pending |
| 24 | Historical-data documentation complete | PASS | `docs/historical-data.md`, sections 1–22 |
| 25 | Review contains concrete evidence | PASS | this criterion table and gate results |
| 26 | AGENTS handoff updated | PASS | `AGENTS.md` preserves PHASE 3 approval and blocks PHASE 5 |
| 27 | Production data is not committed | PASS | `data/README.md`, `.gitignore`, fixture-only Git inputs |

## Local quality gates

Environment: Windows, CPython 3.11.9.

| Gate | Result |
|---|---|
| `python -m pytest -q` | PASS — 114 tests |
| `python -m pytest --cov=trading_bot --cov-report=term-missing -q` | PASS — 84% total |
| `ruff check src tests` | PASS |
| `ruff format --check src tests` | PASS |
| `python -m mypy src` | PASS — 45 source files |
| `python -m compileall -q src` | PASS |

Historical coverage from the remediation run: pipeline 90%, dataset 86%, manifests
100%, models 86%, normalization 94%, parser 89%, repository 83%, serialization 100%,
and validation 92%.

## Determinism and look-ahead findings

- Identical source bytes under different paths produce equal datasets, manifests,
  snapshots, replay results, decision IDs, regime IDs, signal IDs, and candidate IDs.
- Rebuilding a separate SQLite store produces canonical byte-equivalent replay output.
- Every point-in-time query uses an explicit data version and `close_time <= as_of`.
- Appending future and corrected versions leaves the old version's bounded query and
  replay byte-identical.
- Corrections intentionally create a new `data_version`; IDs from distinct versions
  are not expected to match.

## Version identity remediation

| External-review gap | Result | Evidence |
|---|---|---|
| Full app config polluted M5 identity | FIXED | strategy/risk changes alter app config hash but preserve historical semantics version, M5 version, dataset ID and candles |
| Derived M15/H1 reused M5 version | FIXED | derived version hashes source version, source/target timeframe and resampler version |
| Derived lineage was free text only | FIXED | typed manifest lineage records source dataset/version/timeframe, target timeframe and resampler |
| Snapshot accepted one shared version | FIXED | `HistoricalVersionSet` drives per-timeframe queries and a deterministic composite snapshot version |
| Multiple derived algorithms could collide | FIXED | SQLite coexistence test persists and queries M15 resample-v1 and resample-v2 explicitly |

The reviewed M5 golden artifact changed because the former identity included the
arbitrary full-app `config-v1` hash. The replacement pins the intentional
raw-content + historical-semantics identity. OHLCV values and candle count did not
change.

Concrete deterministic fixture evidence:

- Strategy threshold change: app config
  `fc0fb6ac… → aefbdab9…`, while historical semantics stays
  `45f23166…` and M5 stays `d115846e…`.
- Same M5 with resample-v1 gives M15 `7c87ed39…`; resample-v2 gives
  `4089c2a9…`.
- The same M5 with target H1 gives `9e87b826…`, distinct from both M15 versions.
- Composite `(M5 d115846e…, M15 7c87ed39…, H1 9e87b826…)` gives snapshot version
  `b2c20fa1…`.

## Remaining gate

Commit remediation locally, then run the existing `.github/workflows/ci.yml` on Python
3.12 when a push is explicitly authorized. Only a green remediation run plus human
review can change PHASE 4 to `APPROVED` and permit proposing PHASE 5.
