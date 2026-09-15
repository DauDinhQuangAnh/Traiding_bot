# BTC-USDT-SWAP Trading Bot

Mục tiêu của dự án là xây dựng một trading bot có tính quyết định (deterministic),
ưu tiên bảo toàn vốn và mặc định `NO_TRADE` khi dữ liệu, tín hiệu hoặc điều kiện
an toàn không đủ rõ ràng.

## Trạng thái

- PHASE 1 — **APPROVED**
- PHASE 2 — Technical Specification: **COMPLETE**
- PHASE 2 Design Gate — **APPROVED**
- PHASE 3 — Deterministic Offline Core: **APPROVED after remediation**
- PHASE 4 — Historical Data Foundation: **APPROVED after version-identity remediation**
- PHASE 5 — Backtest Engine: **APPROVED after final Decimal-determinism closure**
- PHASE 6 — Out-of-Sample Validation and Local Dashboard: **APPROVED**
- PHASE 7 — Multi-Provider AI Benchmark and Advisory Layer: **APPROVED_CANDIDATE**
- Phạm vi thị trường dự kiến: `BTC-USDT-SWAP`, OKX Demo Trading
- Live trading: **không thuộc phạm vi hiện tại và phải luôn mặc định tắt**
- Repository có package Python chạy offline; không có mã kết nối hoặc gửi lệnh tới OKX.

## Tài liệu PHASE 1

- [System Architecture](docs/architecture.md)
- [Trading Decision Flow](docs/trading-flow.md)
- [Risk Management Flow](docs/risk-management.md)
- [PHASE 1 Review](docs/phase-1-review.md)

## Tài liệu PHASE 2

- [Technical Specification](docs/technical-specification.md)
- [Domain Models](docs/domain-models.md)
- [Typed Configuration](docs/configuration.md)
- [Market Data and Indicator Contract](docs/market-data.md)
- [Market Regime and SIDEWAY](docs/regime-detection.md)
- [Strategy and Signal Scoring](docs/strategy.md)
- [Position Sizing and Fee Model](docs/position-sizing.md)
- [Error and Reason Codes](docs/error-and-reason-codes.md)
- [PHASE 2 Review](docs/phase-2-review.md)

## PHASE 3

- [Implementation plan](docs/phase-3-plan.md)
- [Implementation review](docs/phase-3-review.md)
- Cài dependencies (Python 3.12+): `python -m pip install -e .[dev]`
- Chạy test: `python -m pytest -q`
- Chạy quality gates: `ruff check src tests`, `ruff format --check src tests`, `mypy src`
- Python 3.12 CI: [`.github/workflows/ci.yml`](.github/workflows/ci.yml)

PHASE 3 chỉ triển khai domain core, pipeline replay và SQLite journal local. OKX adapter,
API key, network I/O, order submission, trading loop và live trading vẫn ngoài phạm vi.

## PHASE 4

- [Implementation plan](docs/phase-4-plan.md)
- [Historical data contract](docs/historical-data.md)
- [Acceptance review](docs/phase-4-review.md)
- Baseline commit: `635303d`; version-identity remediation: `68bedeb`.
- GitHub Actions Python 3.12 passed for remediation commit `68bedeb`, and external
  human review approved PHASE 4.
- The approved PHASE 4 baseline contains no production historical dataset, exchange
  client, network I/O, strategy calibration, or backtest execution behavior.

## PHASE 5

- [Implementation plan](docs/phase-5-plan.md)
- [Backtesting contract](docs/backtesting.md)
- [Acceptance review](docs/phase-5-review.md)
- Final commit: `191fd72`; GitHub Actions run #6 job `python-312` passed on the exact
  commit, and external human review approved PHASE 5.
- PHASE 5 is deterministic historical simulation only; no Demo/Live execution,
  exchange client, parameter optimization, AI integration, or profitability claim.

## PHASE 6

- Status: **APPROVED**. Final commit `b5319eb304eaa5537843943652384b043765e80f`
  passed GitHub Actions run #11, job `python-312`, and received explicit external human
  approval.
- [Implementation plan](docs/phase-6-plan.md)
- [Validation contract](docs/validation.md)
- [Implementation review](docs/phase-6-review.md)
- Scope is chronological out-of-sample validation, fixed-strategy robustness evidence,
  and a local read-only dashboard foundation.
- PHASE 6 does not authorize exchange connectivity, Demo/Live trading, automatic
  optimization, parameter tuning against the final test set, or a profitability claim.

## PHASE 7

- Status: **APPROVED_CANDIDATE** after final benchmark-integrity remediation. Model input
  excludes benchmark labels, metrics use explicit Decimal calculation policy, and response
  provenance is replay-verified. External human review is still required before `APPROVED`.
- [Implementation plan](docs/phase-7-plan.md)
- [AI benchmark contract](docs/ai-benchmark.md)
- [Implementation review](docs/phase-7-review.md)
- Scope is an offline-first, provider-independent benchmark and advisory evidence layer
  over frozen point-in-time market/strategy evidence.
- AI output is observational only. It cannot alter strategy, Risk Engine, portfolio,
  execution, orders, configuration, or any Demo/Live state.
- OpenAI, Anthropic, and Gemini are represented by disabled provider specifications and
  a common port. No provider SDK, network adapter, credential value, or network CI path
  is introduced in the foundation.
- Strategy robustness remains **NOT_EVALUATED**; PHASE 7 provider agreement is not a
  profitability or trading-authorization result.
