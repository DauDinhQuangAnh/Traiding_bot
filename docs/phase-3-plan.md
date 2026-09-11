# PHASE 3 Plan — Project Scaffold + Core Domain Implementation

## 1. Implementation scope

PHASE 3 translates the approved PHASE 2 contracts into an offline, importable and
testable Python package. It covers immutable domain models, typed validation,
configuration loading/versioning/redaction, market-data validation, indicators,
levels/range/breakout state, regime detection, signal scoring/candidate construction,
position sizing, Risk Engine approval, state machines, deterministic identifiers,
ports, SQLite journal foundations and deterministic replay tests.

Numerical fields marked `BACKTEST_REQUIRED` remain explicit inputs. Test fixtures use
clearly labelled non-production values solely to exercise contracts.

## 2. Package/module structure

```text
src/trading_bot/
├── domain/          # enums, errors, immutable models, Decimal/UTC/ID utilities
├── config/          # typed configuration, loader, canonical hash, redaction
├── market_data/     # series/snapshot validation and deterministic indicators
├── levels/          # swings, structure, levels, ranges and breakout transitions
├── regime/          # pure evidence scoring, precedence and persistence
├── strategy/        # confirmation, components, setup selection and candidate builder
├── risk/            # conservative sizing and sole ApprovedTradePlan factory
├── application/     # ports and pure replay orchestration
└── infrastructure/  # SQLite journal and offline fakes implementing ports

tests/
├── unit/
├── integration/
├── property/
├── golden/
└── fixtures/
```

## 3. Dependency direction

```text
domain <- config / market_data / levels / regime / strategy / risk
       <- application ports and orchestration
       <- infrastructure adapters
```

- Domain imports only Python standard-library modules.
- Application depends on domain-facing contracts, never on SQLite details.
- Infrastructure implements application ports and may import domain models.
- Domain and application never import infrastructure.
- No exchange-specific schema, SDK or network client is allowed.

## 4. Implementation order

1. Scaffold packaging and quality tooling.
2. Implement enums, errors, Decimal/UTC/canonical serialization and identifiers.
3. Implement immutable value objects and aggregate models with validators.
4. Implement typed configuration, strict loader, cross-field validation and redaction.
5. Implement market-data validation and indicator calculations/readiness.
6. Implement structure, level/range construction and breakout transitions.
7. Implement regime detector and deterministic persistence.
8. Implement signal scoring, setup selection and trade-candidate construction.
9. Implement conservative position sizing and Risk Engine approval.
10. Implement state machines, ports, SQLite journal and offline fakes.
11. Add unit/property/golden/replay tests, then run formatter, lint, type checking and tests.
12. Produce `phase-3-review.md` and update README only after the acceptance gate passes.

## 5. Test strategy

- Unit tests cover every validator, formula boundary, transition and rejection path.
- Property tests cover OHLC invariants, range boundaries, candidate geometry and the
  post-quantization risk-budget invariant.
- Golden tests compare canonical serialized outputs and hashes without auto-update.
- Integration tests verify SQLite migrations, transactions, append-only revisions and
  uniqueness of logical execution intents.
- Replay tests run closed candles through the pure domain pipeline twice and require
  byte-equivalent decision sequences.
- An import/dependency test rejects infrastructure imports from domain/application.
- A source scan and offline-only fakes enforce the no-network/no-OKX boundary.

## 6. Acceptance criteria

PHASE 3 is complete only when the package imports, all immutable model/config
validators enforce the specification, deterministic calculations and IDs reproduce,
Risk is the sole plan factory, SQLite constraints work, no forbidden dependency/network
code exists, and the actual pytest, Ruff, formatting and mypy commands all pass.

Any failing critical criterion leaves the phase as `PHASE 3: NEEDS WORK`.

## 7. Explicit out of scope

- OKX REST/WebSocket or any other network/exchange adapter.
- API keys, credential acquisition, Demo/Live order submission or continuous loop.
- Backtest calibration, optimization, profitability claims or PHASE 4 work.
- Web frameworks, dashboards, messaging bots, distributed infrastructure, ML or AI.
