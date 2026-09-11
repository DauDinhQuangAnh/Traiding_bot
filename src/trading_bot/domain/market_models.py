"""Immutable market, indicator, structure, level and range models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import pairwise

from trading_bot.domain.enums import (
    BreakoutDirection,
    BreakoutState,
    LevelKind,
    LevelMethod,
    MarketRegime,
    RangeLocation,
    ReasonCode,
    Timeframe,
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
from trading_bot.domain.value_objects import (
    IndicatorValues,
    MarketStructure,
    Quote,
    RegimeEvidence,
    VersionSet,
)

_INTERVALS = {
    Timeframe.M5: timedelta(minutes=5),
    Timeframe.M15: timedelta(minutes=15),
    Timeframe.H1: timedelta(hours=1),
}


def _require_ids(instance: object, *names: str) -> None:
    for name in names:
        require_non_empty(getattr(instance, name), name)


@dataclass(frozen=True, slots=True)
class Candle:
    candle_id: str
    symbol: str
    timeframe: Timeframe
    open_time: datetime
    close_time: datetime
    event_time: datetime
    receive_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    is_closed: bool
    source: str
    data_version: str

    def __post_init__(self) -> None:
        _require_ids(self, "candle_id", "symbol", "source", "data_version")
        for name in ("open_time", "close_time", "event_time", "receive_time"):
            require_utc(getattr(self, name), name)
        for name in ("open", "high", "low", "close"):
            require_positive(getattr(self, name), name)
        require_non_negative(self.volume, "volume")
        if self.close_time <= self.open_time:
            raise DomainValidationError("close_time must be after open_time")
        if self.close_time - self.open_time != _INTERVALS[self.timeframe]:
            raise DomainValidationError("candle interval does not match timeframe")
        if self.open_time.second != 0 or self.open_time.microsecond != 0:
            raise DomainValidationError("candle interval is not aligned to a UTC boundary")
        if self.timeframe is Timeframe.M5 and self.open_time.minute % 5 != 0:
            raise DomainValidationError("M5 candle is not aligned to a UTC boundary")
        if self.timeframe is Timeframe.M15 and self.open_time.minute % 15 != 0:
            raise DomainValidationError("M15 candle is not aligned to a UTC boundary")
        if self.timeframe is Timeframe.H1 and self.open_time.minute != 0:
            raise DomainValidationError("H1 candle is not aligned to a UTC boundary")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise DomainValidationError("high/low must contain open and close")
        if self.high < self.low:
            raise DomainValidationError("high must be at or above low")
        if not self.is_closed:
            raise DomainValidationError("canonical candles must be closed")


def validate_candle_series(
    candles: tuple[Candle, ...], timeframe: Timeframe, symbol: str, as_of: datetime
) -> None:
    if not candles:
        raise DomainValidationError(f"{timeframe.value} candle series must not be empty")
    expected_interval = _INTERVALS[timeframe]
    canonical_keys = tuple(
        (candle.source, candle.symbol, candle.timeframe, candle.open_time) for candle in candles
    )
    if len(set(canonical_keys)) != len(canonical_keys):
        raise DomainValidationError("duplicate canonical candle key")
    if any(current.open_time <= previous.open_time for previous, current in pairwise(candles)):
        raise DomainValidationError("candle series must be strictly ordered")
    seen: set[tuple[str, str, Timeframe, datetime]] = set()
    previous: Candle | None = None
    for candle in candles:
        if candle.symbol != symbol or candle.timeframe is not timeframe:
            raise DomainValidationError("candle series identity mismatch")
        if not candle.is_closed or candle.close_time > as_of:
            raise DomainValidationError("snapshot may contain only closed, non-future candles")
        key = (candle.source, candle.symbol, candle.timeframe, candle.open_time)
        if key in seen:
            raise DomainValidationError("duplicate canonical candle key")
        seen.add(key)
        if previous is not None:
            if candle.open_time <= previous.open_time:
                raise DomainValidationError("candle series must be strictly ordered")
            if candle.open_time - previous.open_time != expected_interval:
                raise DomainValidationError("candle series contains a gap")
        previous = candle


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    snapshot_id: str
    evaluation_id: str
    symbol: str
    as_of: datetime
    created_at: datetime
    entry_candle_close_time: datetime
    candles_5m: tuple[Candle, ...]
    candles_15m: tuple[Candle, ...]
    candles_1h: tuple[Candle, ...]
    quote: Quote | None
    data_version: str
    reason_codes: tuple[ReasonCode, ...]

    def __post_init__(self) -> None:
        _require_ids(self, "snapshot_id", "evaluation_id", "symbol", "data_version")
        for name in ("as_of", "created_at", "entry_candle_close_time"):
            require_utc(getattr(self, name), name)
        if self.entry_candle_close_time != self.as_of:
            raise DomainValidationError("entry candle close must equal snapshot as_of")
        validate_candle_series(self.candles_5m, Timeframe.M5, self.symbol, self.as_of)
        validate_candle_series(self.candles_15m, Timeframe.M15, self.symbol, self.as_of)
        validate_candle_series(self.candles_1h, Timeframe.H1, self.symbol, self.as_of)
        if self.candles_15m[-1].close_time != self.as_of:
            raise DomainValidationError("last M15 candle must be the evaluation trigger")
        if self.candles_5m[-1].close_time != self.as_of:
            raise DomainValidationError("last M5 child must close with the M15 trigger")
        trigger_open = self.candles_15m[-1].open_time
        children = self.candles_5m[-3:]
        if len(children) != 3 or tuple(candle.open_time for candle in children) != tuple(
            trigger_open + timedelta(minutes=5 * index) for index in range(3)
        ):
            raise DomainValidationError("M15 trigger requires exactly aligned M5 children")
        expected_h1_close = self.as_of.replace(minute=0, second=0, microsecond=0)
        if self.candles_1h[-1].close_time != expected_h1_close:
            raise DomainValidationError("latest H1 context is not the canonical closed interval")
        if self.quote is not None:
            if self.quote.symbol != self.symbol:
                raise DomainValidationError("quote symbol mismatch")
            if self.quote.event_time > self.as_of:
                raise DomainValidationError("snapshot quote is from the future")


@dataclass(frozen=True, slots=True)
class IndicatorSnapshot:
    indicator_snapshot_id: str
    market_snapshot_id: str
    symbol: str
    as_of: datetime
    values_by_timeframe: Mapping[Timeframe, IndicatorValues]
    is_ready: bool
    missing_requirements: tuple[str, ...]
    reason_codes: tuple[ReasonCode, ...]
    versions: VersionSet

    def __post_init__(self) -> None:
        _require_ids(self, "indicator_snapshot_id", "market_snapshot_id", "symbol")
        require_utc(self.as_of, "as_of")
        object.__setattr__(self, "values_by_timeframe", freeze_mapping(self.values_by_timeframe))
        expected = {Timeframe.M5, Timeframe.M15, Timeframe.H1}
        if self.is_ready:
            if set(self.values_by_timeframe) != expected:
                raise DomainValidationError("ready indicator snapshot requires all timeframes")
            if self.missing_requirements:
                raise DomainValidationError(
                    "ready indicator snapshot cannot have missing requirements"
                )
            if ReasonCode.INDICATOR_NOT_READY in self.reason_codes:
                raise DomainValidationError("ready snapshot cannot contain not-ready reason")
        else:
            if not self.missing_requirements:
                raise DomainValidationError("not-ready snapshot must list missing requirements")
            if ReasonCode.INDICATOR_NOT_READY not in self.reason_codes:
                raise DomainValidationError("not-ready snapshot requires INDICATOR_NOT_READY")


@dataclass(frozen=True, slots=True)
class RegimeAssessment:
    assessment_id: str
    indicator_snapshot_id: str
    symbol: str
    regime: MarketRegime
    candidate_regime: MarketRegime | None
    previous_confirmed_regime: MarketRegime | None
    candidate_scores: Mapping[MarketRegime, Decimal]
    confidence: Decimal
    evidence: tuple[RegimeEvidence, ...]
    confirmation_count: int
    reason_codes: tuple[ReasonCode, ...]
    as_of: datetime
    config_version: str
    strategy_version: str

    def __post_init__(self) -> None:
        _require_ids(
            self,
            "assessment_id",
            "indicator_snapshot_id",
            "symbol",
            "config_version",
            "strategy_version",
        )
        require_utc(self.as_of, "as_of")
        require_ratio(self.confidence, "confidence")
        expected = {
            MarketRegime.TREND_UP,
            MarketRegime.TREND_DOWN,
            MarketRegime.SIDEWAY,
            MarketRegime.HIGH_VOLATILITY,
        }
        if set(self.candidate_scores) != expected:
            raise DomainValidationError("candidate score keys must be the four candidate regimes")
        for regime, score in self.candidate_scores.items():
            require_ratio(score, f"candidate_scores[{regime.value}]")
        object.__setattr__(self, "candidate_scores", freeze_mapping(self.candidate_scores))
        if self.candidate_regime is MarketRegime.UNCERTAIN:
            raise DomainValidationError("candidate_regime cannot be UNCERTAIN")
        if self.previous_confirmed_regime not in {
            None,
            MarketRegime.TREND_UP,
            MarketRegime.TREND_DOWN,
            MarketRegime.SIDEWAY,
        }:
            raise DomainValidationError("invalid previous_confirmed_regime")
        if self.confirmation_count < 0:
            raise DomainValidationError("confirmation_count must be non-negative")
        if self.regime is not MarketRegime.UNCERTAIN and not self.evidence:
            raise DomainValidationError("determined regime requires evidence")


@dataclass(frozen=True, slots=True)
class RangeContext:
    range_id: str
    symbol: str
    support_level_id: str
    resistance_level_id: str
    support: Decimal
    resistance: Decimal
    reference_close: Decimal
    range_width: Decimal
    range_mid: Decimal
    range_width_atr: Decimal
    position_in_range: Decimal
    range_started_at: datetime
    last_validated_at: datetime
    as_of: datetime
    range_age_bars: int
    support_tests: int
    resistance_tests: int
    breakout_confirmation_count: int
    current_location: RangeLocation
    breakout_state: BreakoutState
    breakout_direction: BreakoutDirection | None
    breakout_detected_at: datetime | None
    state_updated_at: datetime | None
    expires_at: datetime | None
    reason_codes: tuple[ReasonCode, ...]
    config_version: str
    data_version: str

    def __post_init__(self) -> None:
        _require_ids(
            self,
            "range_id",
            "symbol",
            "support_level_id",
            "resistance_level_id",
            "config_version",
            "data_version",
        )
        for name in ("support", "resistance", "reference_close", "range_width"):
            require_positive(getattr(self, name), name)
        require_non_negative(self.range_width_atr, "range_width_atr")
        require_finite(self.range_mid, "range_mid")
        require_finite(self.position_in_range, "position_in_range")
        if self.support >= self.resistance:
            raise DomainValidationError("support must be below resistance")
        if self.range_width != self.resistance - self.support:
            raise DomainValidationError("range_width mismatch")
        if self.range_mid != (self.support + self.resistance) / Decimal("2"):
            raise DomainValidationError("range_mid mismatch")
        if self.position_in_range != (self.reference_close - self.support) / self.range_width:
            raise DomainValidationError("position_in_range mismatch")
        for name in ("range_started_at", "last_validated_at", "as_of"):
            require_utc(getattr(self, name), name)
        for name in ("breakout_detected_at", "state_updated_at", "expires_at"):
            value = getattr(self, name)
            if value is not None:
                require_utc(value, name)
        for name in (
            "range_age_bars",
            "support_tests",
            "resistance_tests",
            "breakout_confirmation_count",
        ):
            if getattr(self, name) < 0:
                raise DomainValidationError(f"{name} must be non-negative")
        if self.breakout_state is BreakoutState.NONE:
            if self.breakout_direction is not None:
                raise DomainValidationError("NONE breakout state cannot have direction")
        elif self.breakout_direction is None or self.state_updated_at is None:
            raise DomainValidationError("active breakout state requires direction and update time")


@dataclass(frozen=True, slots=True)
class Level:
    level_id: str
    symbol: str
    kind: LevelKind
    price: Decimal
    zone_lower: Decimal
    zone_upper: Decimal
    strength: Decimal
    method: LevelMethod
    first_observed_at: datetime
    confirmed_at: datetime
    last_tested_at: datetime
    as_of: datetime
    test_count: int
    source_candle_ids: tuple[str, ...]
    invalidated_at: datetime | None

    def __post_init__(self) -> None:
        _require_ids(self, "level_id", "symbol")
        for name in ("price", "zone_lower", "zone_upper"):
            require_positive(getattr(self, name), name)
        require_ratio(self.strength, "strength")
        if not self.zone_lower <= self.price <= self.zone_upper:
            raise DomainValidationError("level price must be inside its zone")
        if self.test_count < 0:
            raise DomainValidationError("test_count must be non-negative")
        if not self.source_candle_ids:
            raise DomainValidationError("level requires source candle IDs")
        for name in ("first_observed_at", "confirmed_at", "last_tested_at", "as_of"):
            require_utc(getattr(self, name), name)
        if self.confirmed_at > self.as_of or self.last_tested_at > self.as_of:
            raise DomainValidationError("level contains future confirmation/test")
        if self.invalidated_at is not None:
            require_utc(self.invalidated_at, "invalidated_at")
            if self.invalidated_at > self.as_of:
                raise DomainValidationError("future level invalidation")


@dataclass(frozen=True, slots=True)
class LevelSet:
    level_set_id: str
    market_snapshot_id: str
    symbol: str
    supports: tuple[Level, ...]
    resistances: tuple[Level, ...]
    swings: tuple[Level, ...]
    range_context: RangeContext | None
    market_structure: MarketStructure
    as_of: datetime
    config_version: str
    data_version: str

    def __post_init__(self) -> None:
        _require_ids(
            self,
            "level_set_id",
            "market_snapshot_id",
            "symbol",
            "config_version",
            "data_version",
        )
        require_utc(self.as_of, "as_of")
        children = self.supports + self.resistances + self.swings
        if any(level.symbol != self.symbol or level.as_of > self.as_of for level in children):
            raise DomainValidationError("level set child identity/as_of mismatch")
        if self.market_structure.as_of != self.as_of:
            raise DomainValidationError("market structure as_of mismatch")
        if self.range_context is not None and (
            self.range_context.symbol != self.symbol or self.range_context.as_of != self.as_of
        ):
            raise DomainValidationError("range context identity/as_of mismatch")
