# BTC-USDT-SWAP Trading Bot

Mục tiêu của dự án là xây dựng một trading bot có tính quyết định (deterministic),
ưu tiên bảo toàn vốn và mặc định `NO_TRADE` khi dữ liệu, tín hiệu hoặc điều kiện
an toàn không đủ rõ ràng.

## Trạng thái

- PHASE 1 — **APPROVED**
- PHASE 2 — Technical Specification: **COMPLETE**
- PHASE 2 Design Gate — **APPROVED**
- PHASE 3 — Deterministic Offline Core: **APPROVED after remediation**
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

## PHASE 4 review candidate

- [Implementation plan](docs/phase-4-plan.md)
- [Historical data contract](docs/historical-data.md)
- [Acceptance review](docs/phase-4-review.md)
- The offline implementation is complete, but the last approved phase remains PHASE 3
  until the new commit passes the existing Python 3.12 GitHub Actions workflow.
- No production historical dataset, exchange client, network I/O, strategy calibration,
  or PHASE 5 backtest engine is included.
