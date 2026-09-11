"""Immutable lossless DTOs at infrastructure boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from trading_bot.domain.enums import OrderPurpose, TradeSide
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.primitives import (
    decimal_value,
    require_non_empty,
    require_non_negative,
    require_positive,
    require_utc,
)


@dataclass(frozen=True, slots=True)
class RawMarketEvent:
    source_event_id: str
    source: str
    symbol: str
    event_type: str
    payload_reference: str
    payload_hash: str
    event_time: datetime
    receive_time: datetime

    def __post_init__(self) -> None:
        names = (
            "source_event_id",
            "source",
            "symbol",
            "event_type",
            "payload_reference",
            "payload_hash",
        )
        for name in names:
            require_non_empty(getattr(self, name), name)
        require_utc(self.event_time, "event_time")
        require_utc(self.receive_time, "receive_time")


@dataclass(frozen=True, slots=True)
class RawCandle:
    source_event_id: str
    source: str
    symbol: str
    timeframe: str
    open_time: datetime
    close_time: datetime
    event_time: datetime
    receive_time: datetime
    open_text: str
    high_text: str
    low_text: str
    close_text: str
    volume_text: str
    is_closed: bool

    def __post_init__(self) -> None:
        for name in ("source_event_id", "source", "symbol", "timeframe"):
            require_non_empty(getattr(self, name), name)
        for name in ("open_time", "close_time", "event_time", "receive_time"):
            require_utc(getattr(self, name), name)
        for name in ("open_text", "high_text", "low_text", "close_text", "volume_text"):
            decimal_value(getattr(self, name))


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    account_id: str
    equity: Decimal
    eligible_equity: Decimal
    available_margin: Decimal
    currency: str
    event_time: datetime
    receive_time: datetime
    is_reconciled: bool
    state_version: str

    def __post_init__(self) -> None:
        for name in ("account_id", "currency", "state_version"):
            require_non_empty(getattr(self, name), name)
        for name in ("equity", "eligible_equity", "available_margin"):
            require_non_negative(getattr(self, name), name)
        require_utc(self.event_time, "event_time")
        require_utc(self.receive_time, "receive_time")


@dataclass(frozen=True, slots=True)
class BalanceSnapshot:
    account_id: str
    currency: str
    total: Decimal
    available: Decimal
    frozen: Decimal
    as_of: datetime
    state_version: str

    def __post_init__(self) -> None:
        for name in ("account_id", "currency", "state_version"):
            require_non_empty(getattr(self, name), name)
        for name in ("total", "available", "frozen"):
            require_non_negative(getattr(self, name), name)
        if self.available + self.frozen > self.total:
            raise DomainValidationError("available plus frozen balance exceeds total")
        require_utc(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class ExternalPosition:
    symbol: str
    side: TradeSide
    quantity: Decimal
    average_entry: Decimal
    mark_price: Decimal
    margin: Decimal
    leverage: Decimal
    external_position_id: str
    event_time: datetime
    receive_time: datetime

    def __post_init__(self) -> None:
        require_non_empty(self.symbol, "symbol")
        require_non_empty(self.external_position_id, "external_position_id")
        require_non_negative(self.quantity, "quantity")
        for name in ("average_entry", "mark_price", "leverage"):
            require_positive(getattr(self, name), name)
        require_non_negative(self.margin, "margin")
        require_utc(self.event_time, "event_time")
        require_utc(self.receive_time, "receive_time")


@dataclass(frozen=True, slots=True)
class OrderIntentRecord:
    client_order_id: str
    approved_plan_id: str
    purpose: OrderPurpose
    created_at: datetime

    def __post_init__(self) -> None:
        require_non_empty(self.client_order_id, "client_order_id")
        require_non_empty(self.approved_plan_id, "approved_plan_id")
        require_utc(self.created_at, "created_at")
