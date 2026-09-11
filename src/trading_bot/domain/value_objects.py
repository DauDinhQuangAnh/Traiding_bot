"""Immutable auxiliary value objects shared by core domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from trading_bot.domain.enums import (
    HealthStatus,
    MarketRegime,
    ReasonCode,
    StructurePointKind,
    StructureTrend,
)
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.primitives import (
    HUNDRED,
    ZERO,
    require_finite,
    require_non_empty,
    require_non_negative,
    require_positive,
    require_ratio,
    require_utc,
)


@dataclass(frozen=True, slots=True)
class VersionSet:
    code_version: str
    strategy_version: str
    config_version: str
    data_version: str

    def __post_init__(self) -> None:
        for name in ("code_version", "strategy_version", "config_version", "data_version"):
            require_non_empty(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class Quote:
    symbol: str
    source: str
    bid: Decimal
    ask: Decimal
    event_time: datetime
    receive_time: datetime

    def __post_init__(self) -> None:
        require_non_empty(self.symbol, "symbol")
        require_non_empty(self.source, "source")
        require_positive(self.bid, "bid")
        require_positive(self.ask, "ask")
        if self.bid > self.ask:
            raise DomainValidationError("bid must not exceed ask")
        require_utc(self.event_time, "event_time")
        require_utc(self.receive_time, "receive_time")

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / Decimal("2")

    @property
    def spread_fraction(self) -> Decimal:
        return (self.ask - self.bid) / self.mid


@dataclass(frozen=True, slots=True)
class IndicatorValues:
    ema20: Decimal
    ema50: Decimal
    ema200: Decimal
    ema20_slope_atr: Decimal
    ema50_slope_atr: Decimal
    ema200_slope_atr: Decimal
    rsi: Decimal
    rsi_slope: Decimal
    atr: Decimal
    atr_fraction: Decimal
    atr_percentile: Decimal
    adx: Decimal
    bb_upper: Decimal
    bb_middle: Decimal
    bb_lower: Decimal
    bb_width_fraction: Decimal
    bb_width_percentile: Decimal
    volume_mean: Decimal
    volume_ratio: Decimal

    def __post_init__(self) -> None:
        for name in self.__slots__:
            require_finite(getattr(self, name), name)
        for name in ("ema20", "ema50", "ema200", "bb_middle"):
            require_positive(getattr(self, name), name)
        for name in ("atr", "atr_fraction", "bb_width_fraction", "volume_mean", "volume_ratio"):
            require_non_negative(getattr(self, name), name)
        for name in ("rsi", "atr_percentile", "adx", "bb_width_percentile"):
            value = getattr(self, name)
            if not ZERO <= value <= HUNDRED:
                raise DomainValidationError(f"{name} must be in [0,100]")
        if not self.bb_lower <= self.bb_middle <= self.bb_upper:
            raise DomainValidationError("Bollinger bands must be ordered")


@dataclass(frozen=True, slots=True)
class StructurePoint:
    kind: StructurePointKind
    price: Decimal
    time: datetime
    candle_id: str
    confirmed_at: datetime

    def __post_init__(self) -> None:
        require_positive(self.price, "price")
        require_non_empty(self.candle_id, "candle_id")
        require_utc(self.time, "time")
        require_utc(self.confirmed_at, "confirmed_at")
        if self.confirmed_at < self.time:
            raise DomainValidationError("confirmed_at must be at or after pivot time")


@dataclass(frozen=True, slots=True)
class MarketStructure:
    trend: StructureTrend
    points: tuple[StructurePoint, ...]
    as_of: datetime
    reason_codes: tuple[ReasonCode, ...]

    def __post_init__(self) -> None:
        require_utc(self.as_of, "as_of")
        if any(point.confirmed_at > self.as_of for point in self.points):
            raise DomainValidationError("market structure contains a future point")


@dataclass(frozen=True, slots=True)
class RegimeEvidence:
    name: str
    supports: MarketRegime
    strength: Decimal
    observed_value: Decimal
    unit: str
    rule_version: str
    source_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        require_non_empty(self.name, "name")
        require_non_empty(self.unit, "unit")
        require_non_empty(self.rule_version, "rule_version")
        require_ratio(self.strength, "strength")
        require_finite(self.observed_value, "observed_value")
        if self.supports is MarketRegime.UNCERTAIN:
            raise DomainValidationError("UNCERTAIN is an outcome, not an evidence candidate")


@dataclass(frozen=True, slots=True)
class SignalEvidence:
    name: str
    long_strength: Decimal
    short_strength: Decimal
    long_observed_value: Decimal
    short_observed_value: Decimal
    unit: str
    source_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        require_non_empty(self.name, "name")
        require_non_empty(self.unit, "unit")
        require_ratio(self.long_strength, "long_strength")
        require_ratio(self.short_strength, "short_strength")
        require_finite(self.long_observed_value, "long_observed_value")
        require_finite(self.short_observed_value, "short_observed_value")


@dataclass(frozen=True, slots=True)
class GateResult:
    gate_name: str
    passed: bool
    reason_code: ReasonCode | None
    observed_value: Decimal | None
    limit_value: Decimal | None
    unit: str | None

    def __post_init__(self) -> None:
        require_non_empty(self.gate_name, "gate_name")
        if not self.passed and self.reason_code is None:
            raise DomainValidationError("failed gate requires a reason code")
        for name in ("observed_value", "limit_value"):
            value = getattr(self, name)
            if value is not None:
                require_finite(value, name)


@dataclass(frozen=True, slots=True)
class Target:
    label: str
    price: Decimal
    quantity_fraction: Decimal

    def __post_init__(self) -> None:
        require_non_empty(self.label, "label")
        require_positive(self.price, "price")
        require_ratio(self.quantity_fraction, "quantity_fraction", positive=True)


@dataclass(frozen=True, slots=True)
class ComponentHealth:
    component: str
    status: HealthStatus
    observed_at: datetime
    reason_codes: tuple[ReasonCode, ...]

    def __post_init__(self) -> None:
        require_non_empty(self.component, "component")
        require_utc(self.observed_at, "observed_at")


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    data_status: HealthStatus
    api_status: HealthStatus
    journal_status: HealthStatus
    account_status: HealthStatus
    observed_at: datetime
    reason_codes: tuple[ReasonCode, ...]

    def __post_init__(self) -> None:
        require_utc(self.observed_at, "observed_at")

    @property
    def all_healthy(self) -> bool:
        return all(
            status is HealthStatus.HEALTHY
            for status in (
                self.data_status,
                self.api_status,
                self.journal_status,
                self.account_status,
            )
        )


@dataclass(frozen=True, slots=True)
class CostRateEstimate:
    entry_fee_rate: Decimal
    stop_exit_fee_rate: Decimal
    target_exit_fee_rate: Decimal
    entry_slippage_rate: Decimal
    stop_slippage_rate: Decimal
    target_slippage_rate: Decimal
    funding_debit_rate: Decimal
    model_version: str

    def __post_init__(self) -> None:
        for name in self.__slots__:
            value = getattr(self, name)
            if isinstance(value, Decimal):
                require_non_negative(value, name)
        require_non_empty(self.model_version, "model_version")


@dataclass(frozen=True, slots=True)
class FeeBreakdown:
    entry_fee: Decimal
    exit_fee: Decimal
    spread_cost: Decimal
    slippage_cost: Decimal
    funding_cash_flow: Decimal

    def __post_init__(self) -> None:
        for name in ("entry_fee", "exit_fee", "spread_cost", "slippage_cost"):
            require_non_negative(getattr(self, name), name)
        require_finite(self.funding_cash_flow, "funding_cash_flow")

    @classmethod
    def zero(cls) -> FeeBreakdown:
        return cls(ZERO, ZERO, ZERO, ZERO, ZERO)

    @property
    def debit_total(self) -> Decimal:
        return self.entry_fee + self.exit_fee + self.spread_cost + self.slippage_cost
