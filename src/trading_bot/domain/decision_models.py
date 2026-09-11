"""Immutable signal, candidate, decision and lifecycle models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from trading_bot.domain.enums import (
    EntryModel,
    ExitReason,
    MarketRegime,
    RangeLocation,
    ReasonCode,
    SetupType,
    SignalComponentName,
    TargetModel,
    TradeDecision,
    TradeLifecycleState,
    TradeSide,
)
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.primitives import (
    HUNDRED,
    ONE,
    ZERO,
    require_finite,
    require_non_empty,
    require_non_negative,
    require_positive,
    require_utc,
)
from trading_bot.domain.value_objects import (
    CostRateEstimate,
    FeeBreakdown,
    GateResult,
    SignalEvidence,
    Target,
    VersionSet,
)


def validate_trade_geometry(
    side: TradeSide,
    entry: Decimal,
    stop: Decimal,
    targets: tuple[Target, ...],
) -> None:
    require_positive(entry, "entry_price")
    require_positive(stop, "stop_price")
    if not targets:
        raise DomainValidationError("targets must not be empty")
    if sum((target.quantity_fraction for target in targets), ZERO) != ONE:
        raise DomainValidationError("target quantity fractions must sum to one")
    if side is TradeSide.LONG:
        if stop >= entry or any(target.price <= entry for target in targets):
            raise DomainValidationError("LONG requires stop < entry < every target")
    elif stop <= entry or any(target.price >= entry for target in targets):
        raise DomainValidationError("SHORT requires every target < entry < stop")


@dataclass(frozen=True, slots=True)
class SignalComponent:
    component_name: SignalComponentName
    long_points: Decimal
    short_points: Decimal
    max_points: Decimal
    evidence: tuple[SignalEvidence, ...]
    reason_codes: tuple[ReasonCode, ...]
    config_version: str

    def __post_init__(self) -> None:
        require_non_empty(self.config_version, "config_version")
        require_non_negative(self.max_points, "max_points")
        for name in ("long_points", "short_points"):
            value = getattr(self, name)
            require_non_negative(value, name)
            if value > self.max_points:
                raise DomainValidationError(f"{name} exceeds max_points")
        if self.max_points == ZERO and (self.long_points != ZERO or self.short_points != ZERO):
            raise DomainValidationError("disabled component must have zero points")


@dataclass(frozen=True, slots=True)
class SignalAssessment:
    signal_assessment_id: str
    evaluation_id: str
    long_score: Decimal
    short_score: Decimal
    components: tuple[SignalComponent, ...]
    gates: tuple[GateResult, ...]
    reason_codes: tuple[ReasonCode, ...]
    as_of: datetime
    versions: VersionSet

    def __post_init__(self) -> None:
        require_non_empty(self.signal_assessment_id, "signal_assessment_id")
        require_non_empty(self.evaluation_id, "evaluation_id")
        require_utc(self.as_of, "as_of")
        for name in ("long_score", "short_score"):
            value = getattr(self, name)
            require_finite(value, name)
            if not ZERO <= value <= HUNDRED:
                raise DomainValidationError(f"{name} must be in [0,100]")
        names = tuple(component.component_name for component in self.components)
        if set(names) != set(SignalComponentName) or len(names) != len(SignalComponentName):
            raise DomainValidationError("assessment requires each signal component exactly once")
        if sum((component.max_points for component in self.components), ZERO) != HUNDRED:
            raise DomainValidationError("component maxima must total 100")
        if self.long_score != sum((component.long_points for component in self.components), ZERO):
            raise DomainValidationError("long_score does not equal component sum")
        if self.short_score != sum((component.short_points for component in self.components), ZERO):
            raise DomainValidationError("short_score does not equal component sum")


@dataclass(frozen=True, slots=True)
class TradeCandidate:
    candidate_id: str
    evaluation_id: str
    symbol: str
    side: TradeSide
    regime: MarketRegime
    signal_score: Decimal
    opposite_score: Decimal
    entry_price: Decimal
    stop_price: Decimal
    reference_atr: Decimal
    targets: tuple[Target, ...]
    planned_rr_before_costs: Decimal
    planned_rr_after_costs: Decimal
    cost_rate_estimate: CostRateEstimate
    setup_type: SetupType
    entry_model: EntryModel
    target_model: TargetModel
    signal_assessment_id: str
    regime_assessment_id: str
    range_id: str | None
    invalidation_level_id: str
    target_level_ids: tuple[str, ...]
    reason_codes: tuple[ReasonCode, ...]
    created_at: datetime
    versions: VersionSet

    def __post_init__(self) -> None:
        for name in (
            "candidate_id",
            "evaluation_id",
            "symbol",
            "signal_assessment_id",
            "regime_assessment_id",
            "invalidation_level_id",
        ):
            require_non_empty(getattr(self, name), name)
        require_utc(self.created_at, "created_at")
        validate_trade_geometry(self.side, self.entry_price, self.stop_price, self.targets)
        require_positive(self.reference_atr, "reference_atr")
        for name in (
            "signal_score",
            "opposite_score",
            "planned_rr_before_costs",
            "planned_rr_after_costs",
        ):
            require_non_negative(getattr(self, name), name)
        if self.signal_score > HUNDRED or self.opposite_score > HUNDRED:
            raise DomainValidationError("signal scores must not exceed 100")
        if self.regime in {MarketRegime.UNCERTAIN, MarketRegime.HIGH_VOLATILITY}:
            raise DomainValidationError("blocked regime cannot create a candidate")
        if len(self.target_level_ids) != len(self.targets) or not self.target_level_ids:
            raise DomainValidationError("each target requires a source level ID")


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    decision_record_id: str
    evaluation_id: str
    symbol: str
    timestamp: datetime
    as_of: datetime
    current_price: Decimal | None
    regime: MarketRegime
    decision: TradeDecision
    range_location: RangeLocation | None
    long_score: Decimal | None
    short_score: Decimal | None
    reason_codes: tuple[ReasonCode, ...]
    human_explanation: str | None
    market_snapshot_id: str | None
    indicator_snapshot_id: str | None
    regime_assessment_id: str | None
    signal_assessment_id: str | None
    candidate_id: str | None
    risk_decision_id: str | None
    trade_id: str | None
    versions: VersionSet

    def __post_init__(self) -> None:
        for name in ("decision_record_id", "evaluation_id", "symbol"):
            require_non_empty(getattr(self, name), name)
        require_utc(self.timestamp, "timestamp")
        require_utc(self.as_of, "as_of")
        if self.current_price is not None:
            require_positive(self.current_price, "current_price")
        for name in ("long_score", "short_score"):
            value = getattr(self, name)
            if value is not None:
                require_non_negative(value, name)
                if value > HUNDRED:
                    raise DomainValidationError(f"{name} must not exceed 100")
        if self.decision is TradeDecision.NO_TRADE:
            if not self.reason_codes:
                raise DomainValidationError("NO_TRADE requires a reason code")
            if self.candidate_id is not None:
                raise DomainValidationError("NO_TRADE cannot reference a candidate")
        else:
            required = (
                self.market_snapshot_id,
                self.indicator_snapshot_id,
                self.regime_assessment_id,
                self.signal_assessment_id,
                self.candidate_id,
            )
            if any(value is None for value in required):
                raise DomainValidationError("directional decision requires full provenance")


@dataclass(frozen=True, slots=True)
class TradeLifecycle:
    trade_id: str
    evaluation_id: str
    candidate_id: str
    symbol: str
    risk_decision_id: str | None
    risk_approval_id: str | None
    approved_plan_id: str | None
    side: TradeSide
    state: TradeLifecycleState
    position_id: str | None
    client_order_ids: tuple[str, ...]
    execution_report_ids: tuple[str, ...]
    opened_at: datetime | None
    closed_at: datetime | None
    gross_pnl: Decimal | None
    net_pnl: Decimal | None
    fees: FeeBreakdown
    exit_reason: ExitReason | None
    revision: int
    versions: VersionSet

    def __post_init__(self) -> None:
        for name in ("trade_id", "evaluation_id", "candidate_id", "symbol"):
            require_non_empty(getattr(self, name), name)
        if self.trade_id != self.candidate_id:
            raise DomainValidationError("trade_id must equal candidate_id")
        if self.revision < 0:
            raise DomainValidationError("revision must be non-negative")
        for name in ("opened_at", "closed_at"):
            value = getattr(self, name)
            if value is not None:
                require_utc(value, name)
        if self.state is TradeLifecycleState.CLOSED:
            if self.gross_pnl is None or self.net_pnl is None or self.closed_at is None:
                raise DomainValidationError("closed lifecycle requires PnL and closed_at")
            expected = self.gross_pnl - self.fees.debit_total + self.fees.funding_cash_flow
            if self.net_pnl != expected:
                raise DomainValidationError("net_pnl does not match fee accounting")
        elif self.net_pnl is not None:
            raise DomainValidationError("net_pnl exists only for closed lifecycle")
        if self.state in {
            TradeLifecycleState.APPROVED,
            TradeLifecycleState.SUBMITTING,
            TradeLifecycleState.PENDING_ENTRY,
            TradeLifecycleState.OPEN,
            TradeLifecycleState.CLOSING,
            TradeLifecycleState.CLOSED,
        } and any(
            value is None
            for value in (self.risk_decision_id, self.risk_approval_id, self.approved_plan_id)
        ):
            raise DomainValidationError("post-approval lifecycle requires approval IDs")
