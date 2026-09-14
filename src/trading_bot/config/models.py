"""Typed configuration matching docs/configuration.md."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import NoReturn
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from trading_bot.domain.enums import (
    BacktestEntryFillPolicy,
    BacktestLimitFillPolicy,
    DecimalRoundingMode,
    EndOfBacktestPolicy,
    EntryModel,
    ExecutionEnvironment,
    FundingMode,
    GapPolicy,
    GapStopPolicy,
    HistoricalConflictPolicy,
    HistoricalGapPolicy,
    HistoricalRawFormat,
    IntrabarAmbiguityPolicy,
    JournalBackend,
    MarginMode,
    OrderType,
    PartialFillPolicy,
    PositionMode,
    ProtectionFailurePolicy,
    SetupType,
    SignalComponentName,
    SmoothingMethod,
    TakeProfitFailurePolicy,
    TargetGapPolicy,
    TargetModel,
    Timeframe,
    TimestampConvention,
    TimestampUnit,
    VolumeStatistic,
)
from trading_bot.domain.errors import ConfigurationError, DomainValidationError
from trading_bot.domain.primitives import HUNDRED, ONE, ZERO, freeze_mapping, require_finite

EVIDENCE_REGISTRY: Mapping[SignalComponentName, frozenset[str]] = {
    SignalComponentName.TREND: frozenset({"regime_alignment", "ema_alignment", "pullback"}),
    SignalComponentName.MOMENTUM: frozenset({"rsi", "rsi_slope"}),
    SignalComponentName.STRUCTURE: frozenset({"market_structure"}),
    SignalComponentName.LEVEL: frozenset({"proximity"}),
    SignalComponentName.VOLUME: frozenset({"volume_ratio"}),
    SignalComponentName.CONFIRMATION: frozenset({"closed_candle"}),
}


def _error(message: str) -> NoReturn:
    raise ConfigurationError(message)


def _finite(value: Decimal, name: str) -> None:
    try:
        require_finite(value, name)
    except DomainValidationError as error:
        raise ConfigurationError(str(error)) from error


def _positive_decimal(value: Decimal, name: str) -> None:
    _finite(value, name)
    if value <= ZERO:
        _error(f"{name} must be positive")


def _non_negative_decimal(value: Decimal, name: str) -> None:
    _finite(value, name)
    if value < ZERO:
        _error(f"{name} must be non-negative")


def _ratio(value: Decimal, name: str, *, positive: bool = False, below_one: bool = False) -> None:
    _finite(value, name)
    lower_ok = value > ZERO if positive else value >= ZERO
    upper_ok = value < ONE if below_one else value <= ONE
    if not lower_ok or not upper_ok:
        _error(f"{name} is outside its ratio bounds")


def _positive_int(value: int, name: str) -> None:
    if isinstance(value, bool) or value <= 0:
        _error(f"{name} must be a positive integer")


def _non_negative_int(value: int, name: str) -> None:
    if isinstance(value, bool) or value < 0:
        _error(f"{name} must be a non-negative integer")


def _positive_duration(value: timedelta, name: str) -> None:
    if value <= timedelta(0):
        _error(f"{name} must be positive")


def _valid_timezone(value: str, name: str) -> None:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as error:
        raise ConfigurationError(f"{name} must be an IANA timezone") from error


@dataclass(frozen=True, slots=True)
class MarketConfig:
    symbol: str
    environment: ExecutionEnvironment
    quote_currency: str
    position_mode: PositionMode
    margin_mode: MarginMode
    timezone: str

    def __post_init__(self) -> None:
        if not self.symbol.strip() or not self.quote_currency.strip():
            _error("market symbol and quote currency must be non-empty")
        if self.environment is ExecutionEnvironment.LIVE:
            _error("LIVE environment is not supported in PHASE 3")
        _valid_timezone(self.timezone, "market.timezone")


@dataclass(frozen=True, slots=True)
class CalculationConfig:
    decimal_precision: int
    rounding_mode: DecimalRoundingMode

    def __post_init__(self) -> None:
        if self.decimal_precision < 28:
            _error("calculation.decimal_precision must be >= 28")
        if self.rounding_mode is not DecimalRoundingMode.ROUND_HALF_EVEN:
            _error("unsupported Decimal rounding mode")


@dataclass(frozen=True, slots=True)
class DirectionalRsiBand:
    long_min: Decimal
    long_max: Decimal
    short_min: Decimal
    short_max: Decimal

    def __post_init__(self) -> None:
        for name in ("long_min", "long_max", "short_min", "short_max"):
            value = getattr(self, name)
            _finite(value, name)
            if not ZERO <= value <= HUNDRED:
                _error(f"{name} must be in [0,100]")
        if self.long_min > self.long_max or self.short_min > self.short_max:
            _error("RSI band minimum cannot exceed maximum")


@dataclass(frozen=True, slots=True)
class ConfirmationConfig:
    minimum_body_fraction: Decimal
    minimum_rejection_wick_fraction: Decimal
    long_close_location_min: Decimal
    short_close_location_max: Decimal

    def __post_init__(self) -> None:
        for name in self.__slots__:
            _ratio(getattr(self, name), f"strategy.confirmation.{name}")


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    version: str
    long_threshold: Decimal
    short_threshold: Decimal
    minimum_score_difference: Decimal
    component_max_points: Mapping[SignalComponentName, Decimal]
    component_evidence_weights: Mapping[SignalComponentName, Mapping[str, Decimal]]
    minimum_nonzero_components: int
    allowed_setups: frozenset[SetupType]
    entry_model: EntryModel
    target_model: TargetModel
    trend_pullback_tolerance_atr: Decimal
    stop_atr_buffer: Decimal
    level_full_strength_distance_atr: Decimal
    level_zero_strength_distance_atr: Decimal
    momentum_rsi_bands: Mapping[SetupType, DirectionalRsiBand]
    momentum_rsi_slope_full: Decimal
    volume_ratio_start: Decimal
    volume_ratio_full: Decimal
    confirmation: ConfirmationConfig
    high_volatility_enabled: bool

    def __post_init__(self) -> None:
        if not self.version.strip():
            _error("strategy.version must be non-empty")
        for name in ("long_threshold", "short_threshold"):
            value = getattr(self, name)
            if not ZERO < value <= HUNDRED:
                _error(f"strategy.{name} must be in (0,100]")
        if not ZERO <= self.minimum_score_difference <= HUNDRED:
            _error("strategy.minimum_score_difference must be in [0,100]")
        expected = set(SignalComponentName)
        if set(self.component_max_points) != expected:
            _error("strategy.component_max_points must contain exactly six canonical keys")
        if set(self.component_evidence_weights) != expected:
            _error("strategy.component_evidence_weights must contain exactly six canonical keys")
        total = ZERO
        enabled = 0
        enabled_non_trend = 0
        for component in SignalComponentName:
            maximum = self.component_max_points[component]
            _non_negative_decimal(maximum, f"component_max_points[{component.value}]")
            total += maximum
            weights = self.component_evidence_weights[component]
            if maximum == ZERO:
                if weights:
                    _error(f"disabled {component.value} component must have empty weights")
                continue
            enabled += 1
            enabled_non_trend += component is not SignalComponentName.TREND
            if set(weights) != EVIDENCE_REGISTRY[component]:
                _error(f"invalid evidence keys for {component.value}")
            if (
                any(value < ZERO for value in weights.values())
                or sum(weights.values(), ZERO) != ONE
            ):
                _error(f"evidence weights for {component.value} must be non-negative and total 1")
        if total != HUNDRED:
            _error("component maximum points must total 100")
        if not 1 <= self.minimum_nonzero_components <= enabled:
            _error("minimum_nonzero_components is not feasible")
        if not self.allowed_setups or not self.allowed_setups <= set(SetupType):
            _error("strategy.allowed_setups must be a non-empty canonical subset")
        if set(self.momentum_rsi_bands) != set(SetupType):
            _error("momentum RSI bands require every canonical setup")
        if self.entry_model is not EntryModel.CLOSE_REFERENCE:
            _error("PHASE 3 supports CLOSE_REFERENCE only")
        if self.target_model is not TargetModel.NEXT_OPPOSING_LEVEL:
            _error("PHASE 3 supports NEXT_OPPOSING_LEVEL only")
        _positive_decimal(self.trend_pullback_tolerance_atr, "trend_pullback_tolerance_atr")
        _non_negative_decimal(self.stop_atr_buffer, "stop_atr_buffer")
        _non_negative_decimal(
            self.level_full_strength_distance_atr, "level_full_strength_distance_atr"
        )
        if self.level_zero_strength_distance_atr <= self.level_full_strength_distance_atr:
            _error("level zero-strength distance must exceed full-strength distance")
        _positive_decimal(self.momentum_rsi_slope_full, "momentum_rsi_slope_full")
        _non_negative_decimal(self.volume_ratio_start, "volume_ratio_start")
        if self.volume_ratio_full <= self.volume_ratio_start:
            _error("volume_ratio_full must exceed volume_ratio_start")
        if self.high_volatility_enabled:
            _error("HIGH_VOLATILITY trading must remain disabled")
        sideway_allowed = bool(
            self.allowed_setups & {SetupType.SIDEWAY_MEAN_REVERSION, SetupType.BREAKOUT_RETEST}
        )
        sideway_max = HUNDRED - self.component_max_points[SignalComponentName.TREND]
        if sideway_allowed and (
            self.long_threshold > sideway_max
            or self.short_threshold > sideway_max
            or self.minimum_nonzero_components > enabled_non_trend
        ):
            _error("SIDEWAY score/confluence configuration is unreachable")
        object.__setattr__(self, "component_max_points", freeze_mapping(self.component_max_points))
        object.__setattr__(
            self,
            "component_evidence_weights",
            freeze_mapping(
                {
                    key: freeze_mapping(value)
                    for key, value in self.component_evidence_weights.items()
                }
            ),
        )
        object.__setattr__(self, "momentum_rsi_bands", freeze_mapping(self.momentum_rsi_bands))


@dataclass(frozen=True, slots=True)
class IndicatorConfig:
    ema_periods: tuple[int, int, int]
    ema_slope_lookback_bars: int
    ema_stabilization_bars: int
    rsi_period: int
    rsi_method: SmoothingMethod
    rsi_slope_lookback_bars: int
    atr_period: int
    atr_method: SmoothingMethod
    atr_percentile_lookback_bars: int
    adx_period: int
    adx_method: SmoothingMethod
    bollinger_period: int
    bollinger_stddev_multiplier: Decimal
    bollinger_percentile_lookback_bars: int
    volume_lookback_bars: int
    volume_statistic: VolumeStatistic

    def __post_init__(self) -> None:
        if self.ema_periods != (20, 50, 200):
            _error("EMA periods must be exactly (20,50,200)")
        for name in (
            "ema_slope_lookback_bars",
            "rsi_period",
            "rsi_slope_lookback_bars",
            "atr_period",
            "atr_percentile_lookback_bars",
            "adx_period",
            "bollinger_period",
            "bollinger_percentile_lookback_bars",
            "volume_lookback_bars",
        ):
            _positive_int(getattr(self, name), name)
        _non_negative_int(self.ema_stabilization_bars, "ema_stabilization_bars")
        if self.atr_percentile_lookback_bars <= self.atr_period:
            _error("ATR percentile lookback must exceed ATR period")
        if self.bollinger_percentile_lookback_bars <= self.bollinger_period:
            _error("Bollinger percentile lookback must exceed band period")
        _positive_decimal(self.bollinger_stddev_multiplier, "bollinger_stddev_multiplier")
        if any(
            method is not SmoothingMethod.WILDER
            for method in (self.rsi_method, self.atr_method, self.adx_method)
        ):
            _error("RSI, ATR and ADX require WILDER smoothing")
        if self.volume_statistic is not VolumeStatistic.MEAN:
            _error("volume statistic must be MEAN")


@dataclass(frozen=True, slots=True)
class RegimeConfig:
    minimum_evidence_count: int
    minimum_evidence_strength: Decimal
    minimum_confidence: Decimal
    minimum_candidate_margin: Decimal
    conflict_tolerance: Decimal
    required_confirmations: int
    timeframe_weights: Mapping[Timeframe, Decimal]
    trend_candidate_threshold: Decimal
    sideway_candidate_threshold: Decimal
    high_volatility_candidate_threshold: Decimal
    trend_weights: Mapping[str, Decimal]
    sideway_weights: Mapping[str, Decimal]
    high_volatility_weights: Mapping[str, Decimal]
    adx_trend_start: Decimal
    adx_trend_full: Decimal
    adx_sideway_full: Decimal
    adx_sideway_zero: Decimal
    ema_minimum_slope_atr: Decimal
    ema_full_slope_atr: Decimal
    ema_maximum_sideway_slope_atr: Decimal
    ema_maximum_sideway_dispersion_atr: Decimal
    price_location_tolerance_atr: Decimal
    atr_percentile_start: Decimal
    atr_percentile_full: Decimal
    bb_percentile_start: Decimal
    bb_percentile_full: Decimal
    true_range_atr_start: Decimal
    true_range_atr_full: Decimal

    def __post_init__(self) -> None:
        if not 2 <= self.minimum_evidence_count <= 3:
            _error("regime.minimum_evidence_count must be in [2,3]")
        for name in (
            "minimum_evidence_strength",
            "minimum_confidence",
            "conflict_tolerance",
            "trend_candidate_threshold",
            "sideway_candidate_threshold",
            "high_volatility_candidate_threshold",
        ):
            _ratio(getattr(self, name), name, positive=True)
        _ratio(self.minimum_candidate_margin, "minimum_candidate_margin")
        _positive_int(self.required_confirmations, "required_confirmations")
        expected_weights = {
            "trend_weights": {"ema", "slope", "adx", "structure", "price_location"},
            "sideway_weights": {
                "range",
                "ema_compression",
                "slope_flatness",
                "adx_weakness",
                "bounded_structure",
            },
            "high_volatility_weights": {
                "atr_percentile",
                "bb_width_percentile",
                "true_range_shock",
            },
        }
        if set(self.timeframe_weights) != {Timeframe.M15, Timeframe.H1}:
            _error("regime timeframe weights require M15 and H1")
        if (
            any(value < ZERO for value in self.timeframe_weights.values())
            or sum(self.timeframe_weights.values(), ZERO) != ONE
        ):
            _error("regime timeframe weights must be non-negative and total 1")
        for name, keys in expected_weights.items():
            weights = getattr(self, name)
            if (
                set(weights) != keys
                or any(value < ZERO for value in weights.values())
                or sum(weights.values(), ZERO) != ONE
            ):
                _error(f"{name} keys/weights are invalid")
            object.__setattr__(self, name, freeze_mapping(weights))
        object.__setattr__(self, "timeframe_weights", freeze_mapping(self.timeframe_weights))
        ramps = (
            (self.adx_trend_start, self.adx_trend_full, "adx trend"),
            (self.adx_sideway_full, self.adx_sideway_zero, "adx sideway"),
            (self.ema_minimum_slope_atr, self.ema_full_slope_atr, "ema slope"),
            (self.atr_percentile_start, self.atr_percentile_full, "ATR percentile"),
            (self.bb_percentile_start, self.bb_percentile_full, "BB percentile"),
            (self.true_range_atr_start, self.true_range_atr_full, "true range"),
        )
        for start, full, name in ramps:
            _non_negative_decimal(start, name)
            if full <= start:
                _error(f"{name} full bound must exceed start")
        for name in (
            "ema_maximum_sideway_slope_atr",
            "ema_maximum_sideway_dispersion_atr",
        ):
            _positive_decimal(getattr(self, name), name)
        _non_negative_decimal(self.price_location_tolerance_atr, "price_location_tolerance_atr")


@dataclass(frozen=True, slots=True)
class LevelConfig:
    lookback_bars: Mapping[Timeframe, int]
    structure_timeframe: Timeframe
    swing_left_bars: int
    swing_right_bars: int
    structure_comparison_tolerance_atr: Decimal
    minimum_touches: int
    full_strength_touches: int
    level_merge_distance_atr: Decimal
    zone_half_width_atr: Decimal
    minimum_level_strength: Decimal
    support_zone_max_fraction: Decimal
    resistance_zone_min_fraction: Decimal
    outside_tolerance_fraction: Decimal
    minimum_range_width_atr: Decimal
    maximum_range_stale_bars: int
    breakout_buffer_atr: Decimal
    breakout_confirmation_bars: int
    breakout_hold_tolerance_atr: Decimal
    retest_tolerance_atr: Decimal
    retest_expiry_bars: int

    def __post_init__(self) -> None:
        if set(self.lookback_bars) != set(Timeframe):
            _error("levels.lookback_bars requires M5, M15 and H1")
        for timeframe, value in self.lookback_bars.items():
            _positive_int(value, f"lookback_bars[{timeframe.value}]")
        if self.structure_timeframe is not Timeframe.M15:
            _error("canonical structure timeframe must be M15")
        for name in (
            "swing_left_bars",
            "swing_right_bars",
            "maximum_range_stale_bars",
            "breakout_confirmation_bars",
            "retest_expiry_bars",
        ):
            _positive_int(getattr(self, name), name)
        if self.minimum_touches < 2 or self.full_strength_touches < self.minimum_touches:
            _error("invalid level touch thresholds")
        for name in (
            "structure_comparison_tolerance_atr",
            "zone_half_width_atr",
            "outside_tolerance_fraction",
            "breakout_buffer_atr",
            "breakout_hold_tolerance_atr",
            "retest_tolerance_atr",
        ):
            _non_negative_decimal(getattr(self, name), name)
        _positive_decimal(self.level_merge_distance_atr, "level_merge_distance_atr")
        _positive_decimal(self.minimum_range_width_atr, "minimum_range_width_atr")
        _ratio(self.minimum_level_strength, "minimum_level_strength")
        _ratio(self.support_zone_max_fraction, "support_zone_max_fraction")
        _ratio(self.resistance_zone_min_fraction, "resistance_zone_min_fraction")
        if self.support_zone_max_fraction >= self.resistance_zone_min_fraction:
            _error("support zone must be below resistance zone")
        object.__setattr__(self, "lookback_bars", freeze_mapping(self.lookback_bars))


@dataclass(frozen=True, slots=True)
class UnrealizedDrawdownGateConfig:
    enabled: bool
    max_ratio: Decimal | None

    def __post_init__(self) -> None:
        if self.enabled:
            if self.max_ratio is None:
                _error("enabled unrealized drawdown gate requires max_ratio")
            _ratio(self.max_ratio, "unrealized_drawdown.max_ratio", positive=True)
        elif self.max_ratio is not None:
            _error("disabled unrealized drawdown gate requires null max_ratio")


@dataclass(frozen=True, slots=True)
class RiskConfig:
    risk_per_trade: Decimal
    target_leverage: Decimal
    max_leverage: Decimal
    max_position_notional: Decimal
    max_total_exposure: Decimal
    max_daily_loss: Decimal
    max_daily_drawdown: Decimal
    max_daily_trades: int
    max_consecutive_losses: int
    minimum_rr: Decimal
    max_allowed_spread: Decimal
    max_slippage: Decimal
    cooldown_after_loss: timedelta
    daily_reset_timezone: str
    max_open_positions: int
    stop_min_distance_atr: Decimal
    stop_max_distance_atr: Decimal
    stop_minimum_tick_multiple: Decimal
    stop_minimum_spread_multiple: Decimal
    margin_buffer_ratio: Decimal
    funding_buffer_intervals: int
    unrealized_drawdown_gate: UnrealizedDrawdownGateConfig

    def __post_init__(self) -> None:
        _ratio(self.risk_per_trade, "risk_per_trade", positive=True, below_one=True)
        for name in (
            "target_leverage",
            "max_leverage",
            "max_position_notional",
            "max_total_exposure",
            "max_daily_loss",
            "minimum_rr",
            "max_allowed_spread",
            "max_slippage",
            "stop_min_distance_atr",
            "stop_max_distance_atr",
            "stop_minimum_tick_multiple",
            "stop_minimum_spread_multiple",
        ):
            _positive_decimal(getattr(self, name), name)
        if self.target_leverage < ONE or self.max_leverage < ONE:
            _error("leverage values must be >= 1")
        if self.target_leverage > self.max_leverage:
            _error("target leverage exceeds maximum")
        if self.max_total_exposure < self.max_position_notional:
            _error("max total exposure must cover max position notional")
        _ratio(self.max_daily_drawdown, "max_daily_drawdown", positive=True)
        _ratio(self.margin_buffer_ratio, "margin_buffer_ratio", below_one=True)
        for name in ("max_daily_trades", "max_consecutive_losses", "max_open_positions"):
            _positive_int(getattr(self, name), name)
        _non_negative_int(self.funding_buffer_intervals, "funding_buffer_intervals")
        if self.cooldown_after_loss < timedelta(0):
            _error("cooldown_after_loss must be non-negative")
        if self.stop_max_distance_atr <= self.stop_min_distance_atr:
            _error("maximum stop ATR distance must exceed minimum")
        _valid_timezone(self.daily_reset_timezone, "risk.daily_reset_timezone")


@dataclass(frozen=True, slots=True)
class ExecutionConfig:
    enabled: bool
    dry_run: bool
    enable_live_trading: bool
    approval_ttl: timedelta
    submit_timeout: timedelta
    cancel_timeout: timedelta
    price_deviation_tolerance: Decimal
    partial_fill_policy: PartialFillPolicy
    max_query_retries: int
    retry_delay: timedelta
    retry_backoff_multiplier: Decimal
    max_retry_delay: timedelta

    def __post_init__(self) -> None:
        if self.enabled or not self.dry_run or self.enable_live_trading:
            _error("PHASE 3 execution must be disabled, dry-run and never live")
        for name in (
            "approval_ttl",
            "submit_timeout",
            "cancel_timeout",
            "retry_delay",
            "max_retry_delay",
        ):
            _positive_duration(getattr(self, name), name)
        _ratio(self.price_deviation_tolerance, "price_deviation_tolerance")
        _non_negative_int(self.max_query_retries, "max_query_retries")
        if self.retry_backoff_multiplier < ONE:
            _error("retry_backoff_multiplier must be >= 1")
        if self.max_retry_delay < self.retry_delay:
            _error("max_retry_delay must be >= retry_delay")
        if self.partial_fill_policy is not PartialFillPolicy.PROTECT_FILLED_AND_CANCEL_REMAINDER:
            _error("unsupported partial fill policy")


@dataclass(frozen=True, slots=True)
class ProtectionConfig:
    stop_order_type: OrderType
    take_profit_order_type: OrderType
    ack_timeout: timedelta
    require_stop_before_managing: bool
    stop_failure_policy: ProtectionFailurePolicy
    take_profit_failure_policy: TakeProfitFailurePolicy
    max_recovery_attempts: int

    def __post_init__(self) -> None:
        if self.stop_order_type is not OrderType.STOP_MARKET:
            _error("stop protection must use STOP_MARKET")
        if self.take_profit_order_type is not OrderType.TAKE_PROFIT_MARKET:
            _error("take profit protection must use TAKE_PROFIT_MARKET")
        _positive_duration(self.ack_timeout, "protection.ack_timeout")
        if not self.require_stop_before_managing:
            _error("stop must be confirmed before managing position")
        if self.stop_failure_policy is not ProtectionFailurePolicy.CANCEL_REMAINDER_REDUCE_AND_HALT:
            _error("unsupported stop failure policy")
        if (
            self.take_profit_failure_policy
            is not TakeProfitFailurePolicy.RECOVER_THEN_REDUCE_AND_HALT
        ):
            _error("unsupported take profit failure policy")
        _non_negative_int(self.max_recovery_attempts, "max_recovery_attempts")


@dataclass(frozen=True, slots=True)
class DataConfig:
    micro_timeframe: Timeframe
    entry_timeframe: Timeframe
    context_timeframe: Timeframe
    history_bars: Mapping[Timeframe, int]
    warmup_candles: Mapping[Timeframe, int]
    candle_freshness: Mapping[Timeframe, timedelta]
    quote_freshness: timedelta
    account_freshness: timedelta
    position_freshness: timedelta
    instrument_metadata_freshness: timedelta
    gap_policy: GapPolicy
    ordering_window: timedelta
    max_backfill_attempts: int
    clock_drift_tolerance: timedelta
    store_raw: bool

    def __post_init__(self) -> None:
        if (
            self.micro_timeframe,
            self.entry_timeframe,
            self.context_timeframe,
        ) != (Timeframe.M5, Timeframe.M15, Timeframe.H1):
            _error("timeframe hierarchy must be M5/M15/H1")
        for mapping_name in ("history_bars", "warmup_candles", "candle_freshness"):
            mapping = getattr(self, mapping_name)
            if set(mapping) != set(Timeframe):
                _error(f"{mapping_name} requires all timeframes")
            object.__setattr__(self, mapping_name, freeze_mapping(mapping))
        for timeframe in Timeframe:
            _positive_int(self.history_bars[timeframe], f"history[{timeframe.value}]")
            _positive_int(self.warmup_candles[timeframe], f"warmup[{timeframe.value}]")
            if self.history_bars[timeframe] < self.warmup_candles[timeframe]:
                _error("history bars must cover warmup")
            _positive_duration(self.candle_freshness[timeframe], f"freshness[{timeframe.value}]")
        for name in (
            "quote_freshness",
            "account_freshness",
            "position_freshness",
            "instrument_metadata_freshness",
        ):
            _positive_duration(getattr(self, name), name)
        if self.ordering_window < timedelta(0) or self.clock_drift_tolerance < timedelta(0):
            _error("ordering and clock drift durations must be non-negative")
        _non_negative_int(self.max_backfill_attempts, "max_backfill_attempts")
        if self.gap_policy is not GapPolicy.BLOCK_AND_BACKFILL:
            _error("gap policy must block and backfill")


@dataclass(frozen=True, slots=True)
class HistoricalConfig:
    raw_format: HistoricalRawFormat
    source_name: str
    symbol_mapping: Mapping[str, str]
    timeframe_mapping: Mapping[str, Timeframe]
    column_mapping: Mapping[str, str]
    timestamp_convention: TimestampConvention
    timestamp_unit: TimestampUnit
    closed_values: frozenset[str]
    conflict_policy: HistoricalConflictPolicy
    gap_policy: HistoricalGapPolicy
    canonical_timeframe: Timeframe
    parser_version: str
    normalization_version: str
    resampling_version: str

    def __post_init__(self) -> None:
        for name in (
            "source_name",
            "parser_version",
            "normalization_version",
            "resampling_version",
        ):
            if not getattr(self, name).strip():
                _error(f"historical.{name} must be non-empty")
        if self.raw_format is not HistoricalRawFormat.CSV:
            _error("PHASE 4 supports CSV raw input only")
        if self.canonical_timeframe is not Timeframe.M5:
            _error("historical canonical_timeframe must be 5m")
        if self.conflict_policy is not HistoricalConflictPolicy.FAIL:
            _error("historical conflicting duplicates must fail")
        if self.gap_policy is not HistoricalGapPolicy.FAIL:
            _error("historical gaps must fail")
        if not self.symbol_mapping or any(
            not source.strip() or canonical != "BTC-USDT-SWAP"
            for source, canonical in self.symbol_mapping.items()
        ):
            _error("historical symbol mapping must explicitly target BTC-USDT-SWAP")
        if not self.timeframe_mapping or set(self.timeframe_mapping.values()) - set(Timeframe):
            _error("historical timeframe mapping is invalid")
        required_columns = {
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "symbol",
            "timeframe",
            "closed",
        }
        if set(self.column_mapping) != required_columns or any(
            not value.strip() for value in self.column_mapping.values()
        ):
            _error("historical column_mapping must contain the exact canonical schema")
        if len(set(self.column_mapping.values())) != len(self.column_mapping):
            _error("historical column headers must be unique")
        if not self.closed_values or any(not value.strip() for value in self.closed_values):
            _error("historical.closed_values must be non-empty strings")
        object.__setattr__(self, "symbol_mapping", freeze_mapping(self.symbol_mapping))
        object.__setattr__(self, "timeframe_mapping", freeze_mapping(self.timeframe_mapping))
        object.__setattr__(self, "column_mapping", freeze_mapping(self.column_mapping))


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    initial_equity: Decimal
    execution_timeframe: Timeframe
    entry_fill_policy: BacktestEntryFillPolicy
    intrabar_ambiguity_policy: IntrabarAmbiguityPolicy
    modeled_spread_rate: Decimal
    market_slippage_rate: Decimal
    stop_slippage_rate: Decimal
    maker_fee_rate: Decimal
    taker_fee_rate: Decimal
    funding_mode: FundingMode
    funding_interval: timedelta
    fixed_funding_rate: Decimal | None
    allow_same_bar_exit_after_entry: bool
    gap_stop_policy: GapStopPolicy
    target_gap_policy: TargetGapPolicy
    limit_fill_policy: BacktestLimitFillPolicy
    end_position_policy: EndOfBacktestPolicy
    halt_stops_run: bool
    execution_model_version: str
    spread_model_version: str
    funding_algorithm_version: str

    def __post_init__(self) -> None:
        _positive_decimal(self.initial_equity, "backtest.initial_equity")
        if self.execution_timeframe is not Timeframe.M5:
            _error("backtest execution_timeframe must be 5m")
        if self.entry_fill_policy is not BacktestEntryFillPolicy.NEXT_M5_OPEN:
            _error("unsupported backtest entry fill policy")
        if self.intrabar_ambiguity_policy is not IntrabarAmbiguityPolicy.WORST_CASE:
            _error("PHASE 5 requires WORST_CASE intrabar ambiguity")
        for name in (
            "modeled_spread_rate",
            "market_slippage_rate",
            "stop_slippage_rate",
            "maker_fee_rate",
            "taker_fee_rate",
        ):
            _ratio(getattr(self, name), f"backtest.{name}")
        _positive_duration(self.funding_interval, "backtest.funding_interval")
        if self.fixed_funding_rate is not None:
            _finite(self.fixed_funding_rate, "backtest.fixed_funding_rate")
            if abs(self.fixed_funding_rate) > ONE:
                _error("backtest.fixed_funding_rate magnitude must be <= 1")
        if self.funding_mode is FundingMode.FIXED_ASSUMPTION:
            if self.fixed_funding_rate is None:
                _error("fixed funding mode requires fixed_funding_rate")
        elif self.fixed_funding_rate is not None:
            _error("fixed_funding_rate is only valid for FIXED_ASSUMPTION")
        if self.gap_stop_policy is not GapStopPolicy.OPEN_OR_STOP_WORSE:
            _error("unsupported gap stop policy")
        if self.target_gap_policy is not TargetGapPolicy.TARGET_PRICE_NO_IMPROVEMENT:
            _error("unsupported target gap policy")
        if self.limit_fill_policy is not BacktestLimitFillPolicy.ASSUMED_FULL_FILL:
            _error("unsupported limit fill policy")
        if self.end_position_policy is not EndOfBacktestPolicy.FORCE_CLOSE_AT_FINAL_AVAILABLE_MARK:
            _error("unsupported end-of-backtest position policy")
        if not self.halt_stops_run:
            _error("PHASE 5 risk HALT must stop the backtest run")
        for name in (
            "execution_model_version",
            "spread_model_version",
            "funding_algorithm_version",
        ):
            if not getattr(self, name).strip():
                _error(f"backtest.{name} must be non-empty")


@dataclass(frozen=True, slots=True)
class AIProviderConfig:
    enabled: bool
    model: str
    temperature: Decimal
    max_output_tokens: int
    timeout: timedelta
    max_attempts: int
    initial_backoff: timedelta
    backoff_multiplier: Decimal
    maximum_backoff: timedelta
    config_version: str

    def __post_init__(self) -> None:
        if not self.model.strip() or not self.config_version.strip():
            _error("AI provider model and config_version must be non-empty")
        _non_negative_decimal(self.temperature, "AI provider temperature")
        if self.temperature > Decimal("2"):
            _error("AI provider temperature must not exceed 2")
        _positive_int(self.max_output_tokens, "AI provider max_output_tokens")
        _positive_duration(self.timeout, "AI provider timeout")
        if not 1 <= self.max_attempts <= 10:
            _error("AI provider max_attempts must be in [1,10]")
        _positive_duration(self.initial_backoff, "AI provider initial_backoff")
        _finite(self.backoff_multiplier, "AI provider backoff_multiplier")
        if self.backoff_multiplier < ONE:
            _error("AI provider backoff_multiplier must be at least one")
        if self.maximum_backoff < self.initial_backoff:
            _error("AI provider maximum_backoff must not be below initial_backoff")


@dataclass(frozen=True, slots=True)
class AIConfig:
    enabled: bool
    max_candles_per_timeframe: int
    max_observations: int
    max_reason_codes: int
    max_text_length: int
    providers: Mapping[str, AIProviderConfig]

    def __post_init__(self) -> None:
        if not 1 <= self.max_candles_per_timeframe <= 100:
            _error("AI max_candles_per_timeframe must be in [1,100]")
        if not 1 <= self.max_observations <= 200:
            _error("AI max_observations must be in [1,200]")
        if not 1 <= self.max_reason_codes <= 50:
            _error("AI max_reason_codes must be in [1,50]")
        if not 16 <= self.max_text_length <= 500:
            _error("AI max_text_length must be in [16,500]")
        if set(self.providers) != {"OPENAI", "ANTHROPIC", "GEMINI"}:
            _error("AI providers must contain exactly OPENAI, ANTHROPIC, and GEMINI")
        object.__setattr__(self, "providers", freeze_mapping(self.providers))
        if not self.enabled and any(item.enabled for item in self.providers.values()):
            _error("AI providers cannot be enabled while global AI is disabled")


@dataclass(frozen=True, slots=True)
class JournalConfig:
    backend: JournalBackend
    database_path: Path
    append_only: bool
    require_write_before_submit: bool
    busy_timeout: timedelta
    retention_days: int | None

    def __post_init__(self) -> None:
        if self.backend is not JournalBackend.SQLITE:
            _error("journal backend must be SQLITE")
        if not self.append_only or not self.require_write_before_submit:
            _error("journal must be append-only and write-before-submit")
        _positive_duration(self.busy_timeout, "journal.busy_timeout")
        if self.retention_days is not None:
            _positive_int(self.retention_days, "journal.retention_days")


@dataclass(frozen=True, slots=True)
class MonitoringConfig:
    health_interval: timedelta
    reconciliation_interval: timedelta
    api_error_window: timedelta
    api_error_limit: int
    alert_channels: tuple[str, ...]
    kill_switch_requires_manual_reset: bool

    def __post_init__(self) -> None:
        for name in ("health_interval", "reconciliation_interval", "api_error_window"):
            _positive_duration(getattr(self, name), name)
        _positive_int(self.api_error_limit, "api_error_limit")
        if not self.kill_switch_requires_manual_reset:
            _error("kill switch must require manual reset")


@dataclass(frozen=True, slots=True)
class AppConfig:
    market: MarketConfig
    calculation: CalculationConfig
    strategy: StrategyConfig
    indicators: IndicatorConfig
    regime: RegimeConfig
    levels: LevelConfig
    risk: RiskConfig
    execution: ExecutionConfig
    protection: ProtectionConfig
    data: DataConfig
    historical: HistoricalConfig
    backtest: BacktestConfig
    ai: AIConfig
    journal: JournalConfig
    monitoring: MonitoringConfig

    def __post_init__(self) -> None:
        derived = required_bars(self.indicators, self.levels)
        for timeframe in Timeframe:
            if self.data.warmup_candles[timeframe] < derived[timeframe]:
                _error(f"warmup for {timeframe.value} is below derived requirement")


def required_bars(indicators: IndicatorConfig, levels: LevelConfig) -> Mapping[Timeframe, int]:
    ema = 200 + indicators.ema_stabilization_bars + indicators.ema_slope_lookback_bars
    rsi = indicators.rsi_period + 1 + indicators.rsi_slope_lookback_bars
    atr = indicators.atr_period + 1
    adx = 2 * indicators.adx_period + 1
    bb = indicators.bollinger_period
    volume = indicators.volume_lookback_bars
    atr_percentile = atr + indicators.atr_percentile_lookback_bars - 1
    bb_percentile = bb + indicators.bollinger_percentile_lookback_bars - 1
    return freeze_mapping(
        {
            timeframe: max(
                ema,
                rsi,
                atr,
                adx,
                bb,
                volume,
                atr_percentile,
                bb_percentile,
                levels.lookback_bars[timeframe],
            )
            for timeframe in Timeframe
        }
    )
