# BTC-USDT-SWAP Trading Bot

Mục tiêu của dự án là xây dựng một trading bot có tính quyết định (deterministic),
ưu tiên bảo toàn vốn và mặc định `NO_TRADE` khi dữ liệu, tín hiệu hoặc điều kiện
an toàn không đủ rõ ràng.

## Trạng thái

- PHASE 1 — Architecture + Flow: **APPROVED**
- PHASE 2 — Technical Specification + Design Gate: **APPROVED**
- Phạm vi thị trường dự kiến: `BTC-USDT-SWAP`, OKX Demo Trading
- Live trading: **không thuộc phạm vi hiện tại và phải luôn mặc định tắt**
- Repository hiện chỉ chứa specification; chưa có mã kết nối hoặc gửi lệnh tới OKX.

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

## Tiếp theo

PHASE 3 — Project Scaffold + Core Domain Implementation. Chưa bắt đầu trong thay đổi
này; repository vẫn không có kết nối OKX, API key, order submission hoặc trading loop.
