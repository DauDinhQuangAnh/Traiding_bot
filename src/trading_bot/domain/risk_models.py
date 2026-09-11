"""Immutable risk, execution, position and journal boundary models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from trading_bot.domain.decision_models import validate_trade_geometry
from trading_bot.domain.enums import (
    JournalEventType,
    LiquidityRole,
    OrderDirection,
    OrderPurpose,
    OrderStatus,
    OrderType,
    PositionStatus,
    ReasonCode,
    RiskAction,
    TradeSide,
)
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.primitives import (
    ZERO,
    freeze_mapping,
    require_finite,
    require_non_empty,
    require_non_negative,
    require_positive,
    require_ratio,
    require_utc,
)
from trading_bot.domain.value_objects import FeeBreakdown, HealthSnapshot, Quote, Target


@dataclass(frozen=True, slots=True)
class PositionState:
    position_id: str
    symbol: str
    state_version: str
    status: PositionStatus
    side: TradeSide | None
    quantity: Decimal
    entry_price: Decimal
    mark_price: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    stop_order_id: str | None
    take_profit_order_id: str | None
    stop_price: Decimal | None
    take_profit_price: Decimal | None
    is_protected: bool
    is_reconciled: bool
    opened_at: datetime | None
    closed_at: datetime | None
    as_of: datetime
    last_execution_report_id: str | None

    def __post_init__(self) -> None:
        for name in ("position_id", "symbol", "state_version"):
            require_non_empty(getattr(self, name), name)
        require_non_negative(self.quantity, "quantity")
        for name in ("entry_price", "mark_price"):
            require_non_negative(getattr(self, name), name)
        require_finite(self.unrealized_pnl, "unrealized_pnl")
        require_finite(self.realized_pnl, "realized_pnl")
        require_utc(self.as_of, "as_of")
        for name in ("opened_at", "closed_at"):
            value = getattr(self, name)
            if value is not None:
                require_utc(value, name)
        if self.status in {PositionStatus.FLAT, PositionStatus.CLOSED} and self.quantity != ZERO:
            raise DomainValidationError("flat/closed position must have zero quantity")
        if self.status is PositionStatus.OPEN and (
            self.side is None or self.quantity <= ZERO or self.entry_price <= ZERO
        ):
            raise DomainValidationError("open position requires side, quantity and entry")
        if self.is_protected and (
            self.stop_order_id is None or self.stop_price is None or self.quantity <= ZERO
        ):
            raise DomainValidationError("protected position requires confirmed stop")


@dataclass(frozen=True, slots=True)
class RiskContext:
    risk_context_id: str
    symbol: str
    account_id: str
    account_equity: Decimal
    eligible_equity: Decimal
    available_margin: Decimal
    current_notional: Decimal
    daily_net_pnl: Decimal
    session_peak_equity: Decimal
    daily_drawdown_ratio: Decimal
    daily_trade_count: int
    consecutive_losses: int
    open_position_count: int
    cooldown_until: datetime | None
    quote: Quote
    position_state: PositionState
    health: HealthSnapshot
    kill_switch_active: bool
    account_reconciled: bool
    observed_at: datetime
    config_version: str
    state_version: str

    def __post_init__(self) -> None:
        for name in ("risk_context_id", "symbol", "account_id", "config_version", "state_version"):
            require_non_empty(getattr(self, name), name)
        for name in (
            "account_equity",
            "eligible_equity",
            "available_margin",
            "current_notional",
            "session_peak_equity",
        ):
            require_non_negative(getattr(self, name), name)
        require_finite(self.daily_net_pnl, "daily_net_pnl")
        require_ratio(self.daily_drawdown_ratio, "daily_drawdown_ratio")
        for name in ("daily_trade_count", "consecutive_losses", "open_position_count"):
            if getattr(self, name) < 0:
                raise DomainValidationError(f"{name} must be non-negative")
        require_utc(self.observed_at, "observed_at")
        if self.cooldown_until is not None:
            require_utc(self.cooldown_until, "cooldown_until")
        if self.quote.symbol != self.symbol or self.position_state.symbol != self.symbol:
            raise DomainValidationError("risk context symbol mismatch")


@dataclass(frozen=True, slots=True)
class RiskDecision:
    risk_decision_id: str
    candidate_id: str
    risk_context_id: str
    action: RiskAction
    reason_codes: tuple[ReasonCode, ...]
    observed_limits: Mapping[str, Decimal]
    risk_approval_id: str | None
    approved_plan_id: str | None
    evaluated_at: datetime
    expires_at: datetime
    config_version: str
    state_version: str

    def __post_init__(self) -> None:
        for name in (
            "risk_decision_id",
            "candidate_id",
            "risk_context_id",
            "config_version",
            "state_version",
        ):
            require_non_empty(getattr(self, name), name)
        require_utc(self.evaluated_at, "evaluated_at")
        require_utc(self.expires_at, "expires_at")
        if self.expires_at <= self.evaluated_at:
            raise DomainValidationError("risk decision expiry must be later than evaluation")
        for name, value in self.observed_limits.items():
            require_non_empty(name, "observed limit name")
            require_finite(value, name)
        object.__setattr__(self, "observed_limits", freeze_mapping(self.observed_limits))
        if self.action is RiskAction.APPROVE:
            if self.risk_approval_id is None or self.approved_plan_id is None:
                raise DomainValidationError("APPROVE requires approval and plan IDs")
        elif self.risk_approval_id is not None or self.approved_plan_id is not None:
            raise DomainValidationError("REJECT/HALT must not contain approval IDs")


@dataclass(frozen=True, slots=True)
class ApprovedTradePlan:
    approved_plan_id: str
    risk_approval_id: str
    candidate_id: str
    symbol: str
    side: TradeSide
    entry_price: Decimal
    stop_price: Decimal
    quantity: Decimal
    notional: Decimal
    targets: tuple[Target, ...]
    risk_budget: Decimal
    worst_case_loss: Decimal
    expected_rr: Decimal
    leverage: Decimal
    fee_estimate: FeeBreakdown
    created_at: datetime
    expires_at: datetime
    config_version: str
    state_version: str
    instrument_version: str

    def __post_init__(self) -> None:
        for name in (
            "approved_plan_id",
            "risk_approval_id",
            "candidate_id",
            "symbol",
            "config_version",
            "state_version",
            "instrument_version",
        ):
            require_non_empty(getattr(self, name), name)
        validate_trade_geometry(self.side, self.entry_price, self.stop_price, self.targets)
        for name in ("quantity", "notional", "risk_budget", "worst_case_loss", "expected_rr"):
            require_positive(getattr(self, name), name)
        require_positive(self.leverage, "leverage")
        if self.worst_case_loss > self.risk_budget:
            raise DomainValidationError("worst_case_loss exceeds risk_budget")
        require_utc(self.created_at, "created_at")
        require_utc(self.expires_at, "expires_at")
        if self.expires_at <= self.created_at:
            raise DomainValidationError("approved plan TTL must be positive")


@dataclass(frozen=True, slots=True)
class ExecutionReport:
    execution_report_id: str
    client_order_id: str
    approved_plan_id: str
    symbol: str
    exchange_order_id: str | None
    status: OrderStatus
    purpose: OrderPurpose
    direction: OrderDirection
    order_type: OrderType
    reduce_only: bool
    requested_quantity: Decimal
    cumulative_filled_quantity: Decimal
    last_fill_quantity: Decimal | None
    last_fill_price: Decimal | None
    average_fill_price: Decimal | None
    liquidity_role: LiquidityRole
    fees: Decimal
    funding_cash_flow: Decimal
    realized_slippage: Decimal
    event_time: datetime
    receive_time: datetime
    reason_codes: tuple[ReasonCode, ...]

    def __post_init__(self) -> None:
        for name in ("execution_report_id", "client_order_id", "approved_plan_id", "symbol"):
            require_non_empty(getattr(self, name), name)
        require_positive(self.requested_quantity, "requested_quantity")
        require_non_negative(self.cumulative_filled_quantity, "cumulative_filled_quantity")
        if self.cumulative_filled_quantity > self.requested_quantity:
            raise DomainValidationError("cumulative fill exceeds requested quantity")
        for name in ("fees", "realized_slippage"):
            require_non_negative(getattr(self, name), name)
        require_finite(self.funding_cash_flow, "funding_cash_flow")
        require_utc(self.event_time, "event_time")
        require_utc(self.receive_time, "receive_time")
        if self.cumulative_filled_quantity > ZERO:
            if self.average_fill_price is None or self.last_fill_quantity is None:
                raise DomainValidationError(
                    "fill report requires fill quantities and average price"
                )
            require_positive(self.average_fill_price, "average_fill_price")
            require_positive(self.last_fill_quantity, "last_fill_quantity")
        if self.purpose is OrderPurpose.ENTRY and self.reduce_only:
            raise DomainValidationError("entry order cannot be reduce-only")
        if self.purpose is not OrderPurpose.ENTRY and not self.reduce_only:
            raise DomainValidationError("protection/exit order must be reduce-only")


@dataclass(frozen=True, slots=True)
class InstrumentMetadata:
    symbol: str
    instrument_type: str
    quote_currency: str
    is_linear_quote_margined: bool
    contract_value_base: Decimal
    tick_size: Decimal
    lot_size: Decimal
    minimum_quantity: Decimal
    minimum_notional: Decimal
    maximum_order_quantity: Decimal
    maximum_leverage: Decimal
    effective_at: datetime
    version: str

    def __post_init__(self) -> None:
        for name in ("symbol", "instrument_type", "quote_currency", "version"):
            require_non_empty(getattr(self, name), name)
        for name in (
            "contract_value_base",
            "tick_size",
            "lot_size",
            "minimum_quantity",
            "minimum_notional",
            "maximum_order_quantity",
            "maximum_leverage",
        ):
            require_positive(getattr(self, name), name)
        require_utc(self.effective_at, "effective_at")

    def base_quantity(self, contracts: Decimal) -> Decimal:
        require_non_negative(contracts, "contracts")
        return contracts * self.contract_value_base

    def notional(self, contracts: Decimal, price: Decimal) -> Decimal:
        require_positive(price, "price")
        return self.base_quantity(contracts) * price


@dataclass(frozen=True, slots=True)
class OrderRequest:
    approved_plan_id: str
    purpose: OrderPurpose
    symbol: str
    direction: OrderDirection
    order_type: OrderType
    quantity: Decimal
    price: Decimal | None
    trigger_price: Decimal | None
    reduce_only: bool
    client_order_id: str

    def __post_init__(self) -> None:
        for name in ("approved_plan_id", "symbol", "client_order_id"):
            require_non_empty(getattr(self, name), name)
        require_positive(self.quantity, "quantity")
        for name in ("price", "trigger_price"):
            value = getattr(self, name)
            if value is not None:
                require_positive(value, name)
        if self.purpose is OrderPurpose.ENTRY and self.reduce_only:
            raise DomainValidationError("entry request cannot be reduce-only")
        if self.purpose is not OrderPurpose.ENTRY and not self.reduce_only:
            raise DomainValidationError("exit/protection request must be reduce-only")


@dataclass(frozen=True, slots=True)
class JournalEvent:
    event_id: str
    stream_id: str
    revision: int
    event_type: JournalEventType
    observed_at: datetime
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        require_non_empty(self.event_id, "event_id")
        require_non_empty(self.stream_id, "stream_id")
        if self.revision < 0:
            raise DomainValidationError("revision must be non-negative")
        require_utc(self.observed_at, "observed_at")
        object.__setattr__(self, "payload", freeze_mapping(self.payload))
