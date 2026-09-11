# PHASE 4 Review — Historical Data Foundation

## Overall status

**NEEDS_WORK**. The implementation and all local gates pass, but this workstation only
has Python 3.11.9. The mandatory Python 3.12 GitHub Actions run cannot cover this
un-pushed commit, so criterion 23 is not yet evidenced. PHASE 3 remains the last approved
phase and PHASE 5 must not begin.

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
| 12 | Reproducible data version | PASS | golden/property tests |
| 13 | Same bytes at another path keep identity | PASS | path-independent manifest test and replay rebuild |
| 14 | Content correction creates a version | PASS | content-sensitive property/integration tests |
| 15 | Point-in-time repository queries | PASS | SQLite range/count/cutoff/version tests |
| 16 | Future append cannot alter past result | PASS | immutable old-version query and replay tests |
| 17 | Historical `MarketSnapshot` sequence | PASS | warm-up and M5/M15/H1 cutoff integration tests |
| 18 | PHASE 3 replay consumes historical snapshots | PASS | raw→SQLite→snapshot→existing replay integration |
| 19 | Replay is deterministic | PASS | canonical byte equality across two storage rebuilds |
| 20 | No OKX/network client | PASS | changed-file audit; historical package is local-only |
| 21 | No strategy changes | PASS | changed-file audit; no strategy source modified |
| 22 | No threshold optimization | PASS | changed-file audit; example strategy config unchanged |
| 23 | Python 3.12 CI passes | **NEEDS_WORK** | Workflow targets 3.12; current commit has no hosted run |
| 24 | Historical-data documentation complete | PASS | `docs/historical-data.md`, sections 1–22 |
| 25 | Review contains concrete evidence | PASS | this criterion table and gate results |
| 26 | AGENTS handoff updated | PASS | `AGENTS.md` preserves PHASE 3 approval and blocks PHASE 5 |
| 27 | Production data is not committed | PASS | `data/README.md`, `.gitignore`, fixture-only Git inputs |

## Local quality gates

Environment: Windows, CPython 3.11.9.

| Gate | Result |
|---|---|
| `python -m pytest -q` | PASS — 105 tests |
| `python -m pytest --cov=trading_bot --cov-report=term-missing -q` | PASS — 84% total |
| `ruff check src tests` | PASS |
| `ruff format --check src tests` | PASS |
| `python -m mypy src` | PASS — 45 source files |
| `python -m compileall -q src` | PASS |

Historical coverage from the acceptance run: pipeline 90%, dataset 87%, manifests
100%, models 88%, normalization 94%, parser 89%, repository 83%, serialization 100%,
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

## Remaining gate

Commit locally, then run the existing `.github/workflows/ci.yml` on Python 3.12 when a
push is explicitly authorized. Only a green run plus human review can change PHASE 4 to
`APPROVED` and permit proposing PHASE 5.
