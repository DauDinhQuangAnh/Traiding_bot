"""Deterministic offline perpetual-funding abstractions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from trading_bot.config.models import BacktestConfig
from trading_bot.domain.enums import FundingMode, TradeSide
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.identifiers import deterministic_id
from trading_bot.domain.primitives import ZERO, require_finite, require_non_empty, require_utc


@dataclass(frozen=True, slots=True)
class FundingRateEvent:
    timestamp: datetime
    rate: Decimal

    def __post_init__(self) -> None:
        require_utc(self.timestamp, "funding timestamp")
        require_finite(self.rate, "funding rate")
        if abs(self.rate) > Decimal("1"):
            raise DomainValidationError("funding rate magnitude must be <= 1")


class FundingRateProvider(Protocol):
    @property
    def mode(self) -> FundingMode: ...

    @property
    def model_version(self) -> str: ...

    @property
    def maximum_debit_rate(self) -> Decimal: ...

    def validate_range(self, start: datetime, end: datetime) -> None: ...

    def rates_between(
        self, start_inclusive: datetime, end_exclusive: datetime
    ) -> tuple[FundingRateEvent, ...]: ...


def _boundaries(start: datetime, end: datetime, interval: timedelta) -> tuple[datetime, ...]:
    require_utc(start, "funding range start")
    require_utc(end, "funding range end")
    if end <= start:
        return ()
    interval_us = interval // timedelta(microseconds=1)
    if interval_us <= 0:
        raise DomainValidationError("funding interval must be positive")
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    start_us = (start - epoch) // timedelta(microseconds=1)
    next_multiple = ((start_us + interval_us - 1) // interval_us) * interval_us
    result: list[datetime] = []
    current = epoch + timedelta(microseconds=next_multiple)
    while current < end:
        result.append(current)
        current += interval
    return tuple(result)


@dataclass(frozen=True, slots=True)
class DisabledFundingRateProvider:
    model_version: str = "funding-disabled-v1"
    mode: FundingMode = FundingMode.DISABLED

    def __post_init__(self) -> None:
        require_non_empty(self.model_version, "funding model_version")

    @property
    def maximum_debit_rate(self) -> Decimal:
        return ZERO

    def validate_range(self, start: datetime, end: datetime) -> None:
        require_utc(start, "start")
        require_utc(end, "end")

    def rates_between(
        self, start_inclusive: datetime, end_exclusive: datetime
    ) -> tuple[FundingRateEvent, ...]:
        return ()


@dataclass(frozen=True, slots=True)
class FixedFundingRateProvider:
    rate: Decimal
    interval: timedelta
    algorithm_version: str
    mode: FundingMode = FundingMode.FIXED_ASSUMPTION

    def __post_init__(self) -> None:
        require_finite(self.rate, "fixed funding rate")
        if abs(self.rate) > Decimal("1"):
            raise DomainValidationError("fixed funding rate magnitude must be <= 1")
        if self.interval <= timedelta(0):
            raise DomainValidationError("funding interval must be positive")
        require_non_empty(self.algorithm_version, "funding algorithm_version")

    @property
    def model_version(self) -> str:
        return deterministic_id(
            "fixed-funding-model-v1", self.rate, self.interval, self.algorithm_version
        )

    @property
    def maximum_debit_rate(self) -> Decimal:
        return abs(self.rate)

    def validate_range(self, start: datetime, end: datetime) -> None:
        require_utc(start, "start")
        require_utc(end, "end")

    def rates_between(
        self, start_inclusive: datetime, end_exclusive: datetime
    ) -> tuple[FundingRateEvent, ...]:
        return tuple(
            FundingRateEvent(timestamp, self.rate)
            for timestamp in _boundaries(start_inclusive, end_exclusive, self.interval)
        )


@dataclass(frozen=True, slots=True)
class HistoricalFundingRateProvider:
    observations: tuple[FundingRateEvent, ...]
    interval: timedelta
    series_version: str
    algorithm_version: str
    mode: FundingMode = FundingMode.HISTORICAL_SERIES

    def __post_init__(self) -> None:
        if self.interval <= timedelta(0):
            raise DomainValidationError("funding interval must be positive")
        require_non_empty(self.series_version, "funding series_version")
        require_non_empty(self.algorithm_version, "funding algorithm_version")
        timestamps = tuple(item.timestamp for item in self.observations)
        if timestamps != tuple(sorted(timestamps)) or len(set(timestamps)) != len(timestamps):
            raise DomainValidationError("funding observations must be unique and ordered")

    @property
    def model_version(self) -> str:
        return deterministic_id(
            "historical-funding-model-v1",
            self.series_version,
            self.interval,
            self.algorithm_version,
            self.observations,
        )

    @property
    def maximum_debit_rate(self) -> Decimal:
        return max((abs(item.rate) for item in self.observations), default=ZERO)

    def validate_range(self, start: datetime, end: datetime) -> None:
        expected = _boundaries(start, end, self.interval)
        available = {item.timestamp for item in self.observations}
        missing = tuple(timestamp for timestamp in expected if timestamp not in available)
        if missing:
            raise DomainValidationError(
                f"historical funding series missing {len(missing)} required event(s)"
            )

    def rates_between(
        self, start_inclusive: datetime, end_exclusive: datetime
    ) -> tuple[FundingRateEvent, ...]:
        return tuple(
            item for item in self.observations if start_inclusive <= item.timestamp < end_exclusive
        )


def funding_cash_flow(side: TradeSide, notional: Decimal, rate: Decimal) -> Decimal:
    require_finite(rate, "funding rate")
    signed_rate = -rate if side is TradeSide.LONG else rate
    return notional * signed_rate


def provider_from_config(config: BacktestConfig) -> FundingRateProvider:
    if config.funding_mode is FundingMode.DISABLED:
        return DisabledFundingRateProvider(
            model_version=deterministic_id("funding-disabled-v1", config.funding_algorithm_version)
        )
    if config.funding_mode is FundingMode.FIXED_ASSUMPTION:
        assert config.fixed_funding_rate is not None
        return FixedFundingRateProvider(
            config.fixed_funding_rate,
            config.funding_interval,
            config.funding_algorithm_version,
        )
    raise DomainValidationError(
        "HISTORICAL_SERIES requires an explicitly injected HistoricalFundingRateProvider"
    )
