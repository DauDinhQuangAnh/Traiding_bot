"""Immutable contracts emitted by the deterministic backtest engine."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from trading_bot.domain.enums import (
    BacktestEventType,
    BacktestFailureKind,
    BacktestStatus,
    BacktestWarning,
    ExitReason,
    LiquidityRole,
    MarketRegime,
    OrderDirection,
    OrderPurpose,
    OrderStatus,
    OrderType,
    ReasonCode,
    SetupType,
    TradeSide,
)
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.primitives import (
    freeze_mapping,
    require_finite,
    require_non_empty,
    require_non_negative,
    require_positive,
    require_ratio,
    require_utc,
)
from trading_bot.domain.value_objects import Target, VersionSet
from trading_bot.historical.models import HistoricalVersionSet


@dataclass(frozen=True, slots=True)
class BacktestRunSpec:
    backtest_run_id: str
    symbol: str
    start_time: datetime
    end_time: datetime
    initial_equity: Decimal
    versions: VersionSet
    historical_versions: HistoricalVersionSet
    instrument_metadata_version: str
    execution_model_version: str
    cost_model_version: str
    funding_model_version: str

    def __post_init__(self) -> None:
        for name in (
            "backtest_run_id",
            "symbol",
            "instrument_metadata_version",
            "execution_model_version",
            "cost_model_version",
            "funding_model_version",
        ):
            require_non_empty(getattr(self, name), name)
        require_utc(self.start_time, "start_time")
        require_utc(self.end_time, "end_time")
        if self.end_time <= self.start_time:
            raise DomainValidationError("backtest end_time must be after start_time")
        require_positive(self.initial_equity, "initial_equity")
        if self.versions.data_version != self.historical_versions.snapshot_data_version:
            raise DomainValidationError("run VersionSet must contain snapshot composite version")


@dataclass(frozen=True, slots=True)
class BacktestEvent:
    event_id: str
    backtest_run_id: str
    sequence: int
    event_time: datetime
    event_type: BacktestEventType
    reason_codes: tuple[ReasonCode, ...]
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        require_non_empty(self.event_id, "event_id")
        require_non_empty(self.backtest_run_id, "backtest_run_id")
        if self.sequence < 0:
            raise DomainValidationError("backtest event sequence must be non-negative")
        require_utc(self.event_time, "event_time")
        object.__setattr__(self, "payload", freeze_mapping(self.payload))


@dataclass(frozen=True, slots=True)
class BacktestOrderState:
    order_id: str
    approved_plan_id: str
    candidate_id: str
    trade_id: str
    side: TradeSide
    order_type: OrderType
    limit_price: Decimal | None
    requested_quantity: Decimal
    filled_quantity: Decimal
    created_at: datetime
    eligible_from: datetime
    expires_at: datetime
    status: OrderStatus
    filled_at: datetime | None

    def __post_init__(self) -> None:
        for name in ("order_id", "approved_plan_id", "candidate_id", "trade_id"):
            require_non_empty(getattr(self, name), name)
        require_positive(self.requested_quantity, "requested_quantity")
        require_non_negative(self.filled_quantity, "filled_quantity")
        if self.filled_quantity > self.requested_quantity:
            raise DomainValidationError("order fill exceeds requested quantity")
        if self.limit_price is not None:
            require_positive(self.limit_price, "limit_price")
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise DomainValidationError("limit order requires limit_price")
        for name in ("created_at", "eligible_from", "expires_at"):
            require_utc(getattr(self, name), name)
        if self.eligible_from < self.created_at or self.expires_at <= self.created_at:
            raise DomainValidationError("invalid pending order timing")
        if self.filled_at is not None:
            require_utc(self.filled_at, "filled_at")


@dataclass(frozen=True, slots=True)
class SimulatedFill:
    fill_id: str
    order_id: str
    approved_plan_id: str
    trade_id: str
    purpose: OrderPurpose
    direction: OrderDirection
    liquidity_role: LiquidityRole
    reference_price: Decimal
    fill_price: Decimal
    quantity: Decimal
    notional: Decimal
    fee: Decimal
    spread_cost_estimate: Decimal
    slippage_cost_estimate: Decimal
    event_time: datetime

    def __post_init__(self) -> None:
        for name in ("fill_id", "order_id", "approved_plan_id", "trade_id"):
            require_non_empty(getattr(self, name), name)
        for name in ("reference_price", "fill_price", "quantity", "notional"):
            require_positive(getattr(self, name), name)
        for name in ("fee", "spread_cost_estimate", "slippage_cost_estimate"):
            require_non_negative(getattr(self, name), name)
        require_utc(self.event_time, "event_time")


@dataclass(frozen=True, slots=True)
class FundingCashFlow:
    funding_id: str
    trade_id: str
    event_time: datetime
    rate: Decimal
    notional: Decimal
    cash_flow: Decimal
    model_version: str

    def __post_init__(self) -> None:
        for name in ("funding_id", "trade_id", "model_version"):
            require_non_empty(getattr(self, name), name)
        require_utc(self.event_time, "event_time")
        require_finite(self.rate, "rate")
        require_non_negative(self.notional, "notional")
        require_finite(self.cash_flow, "cash_flow")


@dataclass(frozen=True, slots=True)
class BacktestTradeResult:
    trade_id: str
    candidate_id: str
    approved_plan_id: str
    side: TradeSide
    setup_type: SetupType
    entry_regime: MarketRegime
    signal_score: Decimal
    opposite_score: Decimal
    entry_time: datetime
    entry_price: Decimal
    initial_quantity: Decimal
    initial_stop: Decimal
    targets: tuple[Target, ...]
    exit_time: datetime
    exit_reason: ExitReason
    exit_fills: tuple[str, ...]
    gross_price_pnl: Decimal
    entry_fee: Decimal
    exit_fee: Decimal
    funding_cash_flow: Decimal
    spread_cost_estimate: Decimal
    slippage_cost_estimate: Decimal
    net_pnl: Decimal
    initial_risk: Decimal
    gross_r_multiple: Decimal
    net_r_multiple: Decimal
    holding_duration: timedelta
    versions: VersionSet

    def __post_init__(self) -> None:
        for name in ("trade_id", "candidate_id", "approved_plan_id"):
            require_non_empty(getattr(self, name), name)
        for name in ("entry_time", "exit_time"):
            require_utc(getattr(self, name), name)
        if self.exit_time < self.entry_time or self.holding_duration < timedelta(0):
            raise DomainValidationError("trade exit cannot precede entry")
        for name in ("entry_price", "initial_quantity", "initial_stop", "initial_risk"):
            require_positive(getattr(self, name), name)
        for name in (
            "signal_score",
            "opposite_score",
            "entry_fee",
            "exit_fee",
            "spread_cost_estimate",
            "slippage_cost_estimate",
        ):
            require_non_negative(getattr(self, name), name)
        for name in (
            "gross_price_pnl",
            "funding_cash_flow",
            "net_pnl",
            "gross_r_multiple",
            "net_r_multiple",
        ):
            require_finite(getattr(self, name), name)
        expected = self.gross_price_pnl - self.entry_fee - self.exit_fee + self.funding_cash_flow
        if self.net_pnl != expected:
            raise DomainValidationError("trade net PnL does not reconcile")
        if self.net_r_multiple != self.net_pnl / self.initial_risk:
            raise DomainValidationError("net R does not reconcile")


@dataclass(frozen=True, slots=True)
class EquityPoint:
    timestamp: datetime
    cash: Decimal
    unrealized_pnl: Decimal
    equity: Decimal
    used_margin: Decimal
    available_margin: Decimal
    peak_equity: Decimal
    drawdown: Decimal
    drawdown_ratio: Decimal

    def __post_init__(self) -> None:
        require_utc(self.timestamp, "timestamp")
        for name in ("cash", "unrealized_pnl", "equity"):
            require_finite(getattr(self, name), name)
        for name in ("used_margin", "available_margin", "peak_equity", "drawdown"):
            require_non_negative(getattr(self, name), name)
        require_non_negative(self.drawdown_ratio, "drawdown_ratio")
        if self.equity != self.cash + self.unrealized_pnl:
            raise DomainValidationError("equity must equal cash plus unrealized PnL")


@dataclass(frozen=True, slots=True)
class DrawdownSummary:
    maximum_drawdown: Decimal
    maximum_drawdown_ratio: Decimal
    peak_time: datetime | None
    trough_time: datetime | None
    recovery_time: datetime | None

    def __post_init__(self) -> None:
        require_non_negative(self.maximum_drawdown, "maximum_drawdown")
        require_non_negative(self.maximum_drawdown_ratio, "maximum_drawdown_ratio")
        for name in ("peak_time", "trough_time", "recovery_time"):
            value = getattr(self, name)
            if value is not None:
                require_utc(value, name)


@dataclass(frozen=True, slots=True)
class PerformanceSummary:
    trades: int
    wins: int
    losses: int
    breakeven: int
    net_pnl: Decimal
    win_rate: Decimal | None
    profit_factor: Decimal | None
    expectancy: Decimal | None
    expectancy_r: Decimal | None
    maximum_loss: Decimal | None

    def __post_init__(self) -> None:
        for name in ("trades", "wins", "losses", "breakeven"):
            if getattr(self, name) < 0:
                raise DomainValidationError(f"{name} must be non-negative")
        require_finite(self.net_pnl, "net_pnl")
        if self.win_rate is not None:
            require_ratio(self.win_rate, "win_rate")
        for name in ("profit_factor", "expectancy", "expectancy_r", "maximum_loss"):
            value = getattr(self, name)
            if value is not None:
                require_finite(value, name)


@dataclass(frozen=True, slots=True)
class MetricBreakdown:
    dimension: str
    value: str
    summary: PerformanceSummary

    def __post_init__(self) -> None:
        require_non_empty(self.dimension, "dimension")
        require_non_empty(self.value, "value")


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    initial_equity: Decimal
    final_equity: Decimal
    gross_pnl: Decimal
    net_pnl: Decimal
    return_ratio: Decimal
    summary: PerformanceSummary
    average_win: Decimal | None
    average_loss: Decimal | None
    average_r_multiple: Decimal | None
    median_r_multiple: Decimal | None
    best_trade: Decimal | None
    worst_trade: Decimal | None
    drawdown: DrawdownSummary
    max_consecutive_wins: int
    max_consecutive_losses: int
    current_consecutive_losses: int
    average_holding_duration: timedelta | None
    market_exposure_ratio: Decimal
    total_fees: Decimal
    total_funding: Decimal
    estimated_spread_cost: Decimal
    estimated_slippage_cost: Decimal
    cost_share_of_gross_profit: Decimal | None
    evaluations: int
    no_trade_evaluations: int
    candidates: int
    risk_rejections: int
    risk_halts: int
    approvals: int
    expired_orders: int
    breakdowns: tuple[MetricBreakdown, ...]

    def __post_init__(self) -> None:
        for name in (
            "initial_equity",
            "final_equity",
            "gross_pnl",
            "net_pnl",
            "return_ratio",
            "total_funding",
        ):
            require_finite(getattr(self, name), name)
        for name in (
            "market_exposure_ratio",
            "total_fees",
            "estimated_spread_cost",
            "estimated_slippage_cost",
        ):
            require_non_negative(getattr(self, name), name)
        require_ratio(self.market_exposure_ratio, "market_exposure_ratio")
        for name in (
            "max_consecutive_wins",
            "max_consecutive_losses",
            "current_consecutive_losses",
            "evaluations",
            "no_trade_evaluations",
            "candidates",
            "risk_rejections",
            "risk_halts",
            "approvals",
            "expired_orders",
        ):
            if getattr(self, name) < 0:
                raise DomainValidationError(f"{name} must be non-negative")


@dataclass(frozen=True, slots=True)
class BacktestRun:
    spec: BacktestRunSpec
    status: BacktestStatus
    completed_at: datetime
    warnings: tuple[BacktestWarning, ...]
    failure_reason: str | None

    def __post_init__(self) -> None:
        require_utc(self.completed_at, "completed_at")
        if self.status is BacktestStatus.FAILED and not self.failure_reason:
            raise DomainValidationError("failed backtest requires failure_reason")
        if self.status is not BacktestStatus.FAILED and self.failure_reason is not None:
            raise DomainValidationError("non-failed backtest cannot have failure_reason")


@dataclass(frozen=True, slots=True)
class BacktestFailure:
    status: BacktestStatus
    kind: BacktestFailureKind
    detail: str
    backtest_run_id: str | None = None

    def __post_init__(self) -> None:
        if self.status is not BacktestStatus.FAILED:
            raise DomainValidationError("backtest failure status must be FAILED")
        require_non_empty(self.detail, "backtest failure detail")
        if self.backtest_run_id is not None:
            require_non_empty(self.backtest_run_id, "backtest_run_id")


@dataclass(frozen=True, slots=True)
class BacktestResult:
    run: BacktestRun
    events: tuple[BacktestEvent, ...]
    orders: tuple[BacktestOrderState, ...]
    fills: tuple[SimulatedFill, ...]
    funding: tuple[FundingCashFlow, ...]
    trades: tuple[BacktestTradeResult, ...]
    equity_curve: tuple[EquityPoint, ...]
    metrics: BacktestMetrics

    def __post_init__(self) -> None:
        if any(event.backtest_run_id != self.run.spec.backtest_run_id for event in self.events):
            raise DomainValidationError("event belongs to another backtest run")
        if tuple(event.sequence for event in self.events) != tuple(range(len(self.events))):
            raise DomainValidationError("backtest event sequence must be contiguous")
        if any(
            current.event_time < previous.event_time
            for previous, current in zip(self.events, self.events[1:], strict=False)
        ):
            raise DomainValidationError("backtest event time must be monotonic")
