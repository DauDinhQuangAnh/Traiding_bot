# BTC-USDT-SWAP Trading Bot

Mục tiêu của dự án là xây dựng một trading bot có tính quyết định (deterministic),
ưu tiên bảo toàn vốn và mặc định `NO_TRADE` khi dữ liệu, tín hiệu hoặc điều kiện
an toàn không đủ rõ ràng.

## Trạng thái

- Giai đoạn hiện tại: **PHASE 1 — Architecture + Flow**
- Phạm vi thị trường dự kiến: `BTC-USDT-SWAP`, OKX Demo Trading
- Live trading: **không thuộc PHASE 1 và phải luôn mặc định tắt**
- PHASE 1 chỉ chứa tài liệu thiết kế; chưa có mã kết nối hoặc gửi lệnh tới OKX.

## Tài liệu PHASE 1

- [System Architecture](docs/architecture.md)
- [Trading Decision Flow](docs/trading-flow.md)
- [Risk Management Flow](docs/risk-management.md)

Không chuyển sang PHASE 2 cho đến khi toàn bộ acceptance criteria trong
[System Architecture](docs/architecture.md#acceptance-criteria-của-phase-1) được
review và chấp thuận.
