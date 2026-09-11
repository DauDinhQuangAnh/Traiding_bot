"""Infrastructure-neutral ports; PHASE 3 adapters remain offline."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol, TypeVar

from trading_bot.application.dtos import (
    AccountSnapshot,
    BalanceSnapshot,
    ExternalPosition,
    OrderIntentRecord,
)
from trading_bot.domain.enums import Timeframe
from trading_bot.domain.market_models import Candle
from trading_bot.domain.risk_models import (
    ExecutionReport,
    InstrumentMetadata,
    JournalEvent,
    OrderRequest,
)
from trading_bot.domain.value_objects import ComponentHealth, CostRateEstimate, Quote


@dataclass(frozen=True, slots=True)
class PersistedEvent:
    event: JournalEvent
    persisted_at: datetime


class MarketDataProvider(Protocol):
    def fetch_candles(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime, limit: int
    ) -> Sequence[Candle]: ...
    def fetch_latest_quote(self, symbol: str) -> Quote: ...
    def health(self) -> ComponentHealth: ...


class AccountProvider(Protocol):
    def get_account_snapshot(self, account_id: str) -> AccountSnapshot: ...

    def get_positions(self, symbol: str | None = None) -> Sequence[ExternalPosition]: ...

    def get_balance(self, currency: str) -> BalanceSnapshot: ...

    def health(self) -> ComponentHealth: ...


class ExchangeExecutionPort(Protocol):
    def submit_order(self, request: OrderRequest) -> ExecutionReport: ...
    def cancel_order(
        self, client_order_id: str, exchange_order_id: str | None = None
    ) -> ExecutionReport: ...
    def get_order(
        self, client_order_id: str, exchange_order_id: str | None = None
    ) -> ExecutionReport: ...
    def get_open_orders(self, symbol: str) -> Sequence[ExecutionReport]: ...
    def health(self) -> ComponentHealth: ...


class InstrumentMetadataProvider(Protocol):
    def get(self, symbol: str, as_of: datetime) -> InstrumentMetadata: ...
    def health(self) -> ComponentHealth: ...


class FeeModel(Protocol):
    def estimate(self, symbol: str, as_of: datetime) -> CostRateEstimate: ...


_Result = TypeVar("_Result")


class JournalRepository(Protocol):
    def append(
        self, event: JournalEvent, expected_stream_revision: int | None = None
    ) -> PersistedEvent: ...
    def get_stream(
        self, stream_id: str, after_revision: int | None = None
    ) -> Sequence[PersistedEvent]: ...
    def reserve_evaluation(self, evaluation_id: str, decision_record_id: str) -> bool: ...
    def reserve_order_intent(self, intent: OrderIntentRecord) -> bool: ...
    def transaction(self, operation: Callable[[], _Result]) -> _Result: ...
    def health(self) -> ComponentHealth: ...


class Clock(Protocol):
    def now_utc(self) -> datetime: ...
    def monotonic(self) -> timedelta: ...


class QuantityCostModel(Protocol):
    def worst_case_loss_per_contract(
        self,
        entry_price: Decimal,
        stop_price: Decimal,
        contract_value_base: Decimal,
        rates: CostRateEstimate,
    ) -> Decimal: ...
