"""Strict YAML layering and typed AppConfig construction."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Any, TypeVar, cast

import yaml

from trading_bot.config.models import (
    AppConfig,
    BacktestConfig,
    CalculationConfig,
    ConfirmationConfig,
    DataConfig,
    DirectionalRsiBand,
    ExecutionConfig,
    HistoricalConfig,
    IndicatorConfig,
    JournalConfig,
    LevelConfig,
    MarketConfig,
    MonitoringConfig,
    ProtectionConfig,
    RegimeConfig,
    RiskConfig,
    StrategyConfig,
    UnrealizedDrawdownGateConfig,
)
from trading_bot.config.secrets import without_secrets
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
from trading_bot.domain.primitives import canonical_json, decimal_value, parse_duration

_E = TypeVar("_E", bound=Enum)


def _map(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{name} must be a mapping")
    return {str(key): item for key, item in value.items()}


def _keys(value: Mapping[str, Any], expected: set[str], name: str) -> None:
    missing = expected - set(value)
    unknown = set(value) - expected
    if missing or unknown:
        raise ConfigurationError(
            f"{name} keys invalid; missing={sorted(missing)}, unknown={sorted(unknown)}"
        )


def _decimal(value: Any, name: str) -> Decimal:
    try:
        if isinstance(value, float):
            raise DomainValidationError("YAML float is lossy; quote Decimal values")
        return decimal_value(value)
    except (DomainValidationError, ArithmeticError) as error:
        raise ConfigurationError(f"invalid Decimal at {name}: {error}") from error


def _duration(value: Any, name: str) -> timedelta:
    try:
        return parse_duration(value)
    except DomainValidationError as error:
        raise ConfigurationError(f"invalid duration at {name}: {error}") from error


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigurationError(f"{name} must be a boolean")
    return value


def _enum(enum_type: type[_E], value: Any, name: str) -> _E:
    try:
        return enum_type(value)
    except (ValueError, TypeError) as error:
        raise ConfigurationError(f"invalid enum at {name}: {value}") from error


def _deep_merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(base))
    for key, value in overlay.items():
        if key not in result:
            raise ConfigurationError(f"unknown overlay key: {key}")
        if isinstance(result[key], Mapping) and isinstance(value, Mapping):
            result[key] = _deep_merge(_map(result[key], key), _map(value, key))
        else:
            result[key] = deepcopy(value)
    return result


def load_yaml(path: Path) -> Mapping[str, Any]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ConfigurationError(f"cannot load config {path}: {error}") from error
    return _map(loaded, str(path))


def load_config(base_path: Path, overlay_path: Path | None = None) -> AppConfig:
    raw = load_yaml(base_path)
    if overlay_path is not None:
        raw = _deep_merge(raw, load_yaml(overlay_path))
    return app_config_from_mapping(raw)


def config_version(raw_or_config: Mapping[str, Any] | AppConfig) -> str:
    safe = without_secrets(raw_or_config)
    return sha256(canonical_json(safe).encode("utf-8")).hexdigest()


def _timeframe_map(raw: Mapping[str, Any], converter: Any, name: str) -> dict[Timeframe, Any]:
    _keys(raw, {"5m", "15m", "1h"}, name)
    return {Timeframe(key): converter(value, f"{name}.{key}") for key, value in raw.items()}


def app_config_from_mapping(raw_value: Mapping[str, Any]) -> AppConfig:
    raw = _map(raw_value, "root")
    groups = {
        "market",
        "calculation",
        "strategy",
        "indicators",
        "regime",
        "levels",
        "risk",
        "execution",
        "protection",
        "data",
        "historical",
        "backtest",
        "journal",
        "monitoring",
    }
    _keys(raw, groups, "root")

    market = _map(raw["market"], "market")
    _keys(
        market,
        {"symbol", "environment", "quote_currency", "position_mode", "margin_mode", "timezone"},
        "market",
    )
    market_config = MarketConfig(
        symbol=str(market["symbol"]),
        environment=_enum(ExecutionEnvironment, market["environment"], "market.environment"),
        quote_currency=str(market["quote_currency"]),
        position_mode=_enum(PositionMode, market["position_mode"], "market.position_mode"),
        margin_mode=_enum(MarginMode, market["margin_mode"], "market.margin_mode"),
        timezone=str(market["timezone"]),
    )
    calculation = _map(raw["calculation"], "calculation")
    _keys(calculation, {"decimal_precision", "rounding_mode"}, "calculation")
    calculation_config = CalculationConfig(
        decimal_precision=int(calculation["decimal_precision"]),
        rounding_mode=_enum(
            DecimalRoundingMode, calculation["rounding_mode"], "calculation.rounding_mode"
        ),
    )
    strategy_config = _strategy(_map(raw["strategy"], "strategy"))
    indicator_config = _indicators(_map(raw["indicators"], "indicators"))
    regime_config = _regime(_map(raw["regime"], "regime"))
    level_config = _levels(_map(raw["levels"], "levels"))
    risk_config = _risk(_map(raw["risk"], "risk"))
    execution_config = _execution(_map(raw["execution"], "execution"))
    protection_config = _protection(_map(raw["protection"], "protection"))
    data_config = _data(_map(raw["data"], "data"))
    historical_config = _historical(_map(raw["historical"], "historical"))
    backtest_config = _backtest(_map(raw["backtest"], "backtest"))
    journal_config = _journal(_map(raw["journal"], "journal"))
    monitoring_config = _monitoring(_map(raw["monitoring"], "monitoring"))
    return AppConfig(
        market_config,
        calculation_config,
        strategy_config,
        indicator_config,
        regime_config,
        level_config,
        risk_config,
        execution_config,
        protection_config,
        data_config,
        historical_config,
        backtest_config,
        journal_config,
        monitoring_config,
    )


def _strategy(raw: Mapping[str, Any]) -> StrategyConfig:
    expected = {
        "version",
        "long_threshold",
        "short_threshold",
        "minimum_score_difference",
        "component_max_points",
        "component_evidence_weights",
        "minimum_nonzero_components",
        "allowed_setups",
        "entry_model",
        "target_model",
        "trend_pullback_tolerance_atr",
        "stop",
        "level_full_strength_distance_atr",
        "level_zero_strength_distance_atr",
        "momentum",
        "volume",
        "confirmation",
        "high_volatility_enabled",
    }
    _keys(raw, expected, "strategy")
    maximums = _map(raw["component_max_points"], "strategy.component_max_points")
    weights = _map(raw["component_evidence_weights"], "strategy.component_evidence_weights")
    stop = _map(raw["stop"], "strategy.stop")
    momentum = _map(raw["momentum"], "strategy.momentum")
    volume = _map(raw["volume"], "strategy.volume")
    confirmation = _map(raw["confirmation"], "strategy.confirmation")
    _keys(stop, {"atr_buffer"}, "strategy.stop")
    _keys(momentum, {"rsi_bands", "rsi_slope_full"}, "strategy.momentum")
    _keys(volume, {"ratio_start", "ratio_full"}, "strategy.volume")
    confirmation_keys = {
        "minimum_body_fraction",
        "minimum_rejection_wick_fraction",
        "long_close_location_min",
        "short_close_location_max",
    }
    _keys(confirmation, confirmation_keys, "strategy.confirmation")
    bands_raw = _map(momentum["rsi_bands"], "strategy.momentum.rsi_bands")
    bands: dict[SetupType, DirectionalRsiBand] = {}
    band_keys = {"long_min", "long_max", "short_min", "short_max"}
    for key, value in bands_raw.items():
        band = _map(value, f"strategy.momentum.rsi_bands.{key}")
        _keys(band, band_keys, f"strategy.momentum.rsi_bands.{key}")
        bands[_enum(SetupType, key, "strategy.momentum.rsi_bands key")] = DirectionalRsiBand(
            **{
                name: _decimal(band[name], f"strategy.momentum.rsi_bands.{key}.{name}")
                for name in band_keys
            }
        )
    component_max_points = {
        _enum(SignalComponentName, key, "strategy.component_max_points key"): _decimal(
            value, f"strategy.component_max_points.{key}"
        )
        for key, value in maximums.items()
    }
    component_evidence_weights = {
        _enum(SignalComponentName, key, "strategy.component_evidence_weights key"): {
            evidence: _decimal(weight, f"strategy.component_evidence_weights.{key}.{evidence}")
            for evidence, weight in _map(
                value, f"strategy.component_evidence_weights.{key}"
            ).items()
        }
        for key, value in weights.items()
    }
    return StrategyConfig(
        version=str(raw["version"]),
        long_threshold=_decimal(raw["long_threshold"], "strategy.long_threshold"),
        short_threshold=_decimal(raw["short_threshold"], "strategy.short_threshold"),
        minimum_score_difference=_decimal(
            raw["minimum_score_difference"], "strategy.minimum_score_difference"
        ),
        component_max_points=component_max_points,
        component_evidence_weights=component_evidence_weights,
        minimum_nonzero_components=int(raw["minimum_nonzero_components"]),
        allowed_setups=frozenset(
            _enum(SetupType, value, "strategy.allowed_setups") for value in raw["allowed_setups"]
        ),
        entry_model=_enum(EntryModel, raw["entry_model"], "strategy.entry_model"),
        target_model=_enum(TargetModel, raw["target_model"], "strategy.target_model"),
        trend_pullback_tolerance_atr=_decimal(
            raw["trend_pullback_tolerance_atr"], "strategy.trend_pullback_tolerance_atr"
        ),
        stop_atr_buffer=_decimal(stop["atr_buffer"], "strategy.stop.atr_buffer"),
        level_full_strength_distance_atr=_decimal(
            raw["level_full_strength_distance_atr"], "strategy.level_full_strength_distance_atr"
        ),
        level_zero_strength_distance_atr=_decimal(
            raw["level_zero_strength_distance_atr"], "strategy.level_zero_strength_distance_atr"
        ),
        momentum_rsi_bands=bands,
        momentum_rsi_slope_full=_decimal(
            momentum["rsi_slope_full"], "strategy.momentum.rsi_slope_full"
        ),
        volume_ratio_start=_decimal(volume["ratio_start"], "strategy.volume.ratio_start"),
        volume_ratio_full=_decimal(volume["ratio_full"], "strategy.volume.ratio_full"),
        confirmation=ConfirmationConfig(
            **{
                name: _decimal(confirmation[name], f"strategy.confirmation.{name}")
                for name in confirmation_keys
            }
        ),
        high_volatility_enabled=_boolean(
            raw["high_volatility_enabled"], "strategy.high_volatility_enabled"
        ),
    )


def _indicators(raw: Mapping[str, Any]) -> IndicatorConfig:
    _keys(raw, {"ema", "rsi", "atr", "adx", "bollinger", "volume"}, "indicators")
    ema, rsi, atr = (_map(raw[name], f"indicators.{name}") for name in ("ema", "rsi", "atr"))
    adx, bb, volume = (
        _map(raw[name], f"indicators.{name}") for name in ("adx", "bollinger", "volume")
    )
    _keys(ema, {"periods", "slope_lookback_bars", "stabilization_bars"}, "indicators.ema")
    _keys(rsi, {"period", "method", "slope_lookback_bars"}, "indicators.rsi")
    _keys(atr, {"period", "method", "percentile_lookback_bars"}, "indicators.atr")
    _keys(adx, {"period", "method"}, "indicators.adx")
    _keys(bb, {"period", "stddev_multiplier", "percentile_lookback_bars"}, "indicators.bollinger")
    _keys(volume, {"lookback_bars", "statistic"}, "indicators.volume")
    periods = tuple(int(value) for value in ema["periods"])
    return IndicatorConfig(
        cast(tuple[int, int, int], periods),
        int(ema["slope_lookback_bars"]),
        int(ema["stabilization_bars"]),
        int(rsi["period"]),
        _enum(SmoothingMethod, rsi["method"], "indicators.rsi.method"),
        int(rsi["slope_lookback_bars"]),
        int(atr["period"]),
        _enum(SmoothingMethod, atr["method"], "indicators.atr.method"),
        int(atr["percentile_lookback_bars"]),
        int(adx["period"]),
        _enum(SmoothingMethod, adx["method"], "indicators.adx.method"),
        int(bb["period"]),
        _decimal(bb["stddev_multiplier"], "indicators.bollinger.stddev_multiplier"),
        int(bb["percentile_lookback_bars"]),
        int(volume["lookback_bars"]),
        _enum(VolumeStatistic, volume["statistic"], "indicators.volume.statistic"),
    )


def _regime(raw: Mapping[str, Any]) -> RegimeConfig:
    nested = {"weights", "adx", "ema", "high_volatility"}
    simple = {
        "minimum_evidence_count",
        "minimum_evidence_strength",
        "minimum_confidence",
        "minimum_candidate_margin",
        "conflict_tolerance",
        "required_confirmations",
        "timeframe_weights",
        "trend_candidate_threshold",
        "sideway_candidate_threshold",
        "high_volatility_candidate_threshold",
        "price_location_tolerance_atr",
    }
    _keys(raw, nested | simple, "regime")
    weights = _map(raw["weights"], "regime.weights")
    _keys(weights, {"trend", "sideway", "high_volatility"}, "regime.weights")
    adx, ema, high = (
        _map(raw[name], f"regime.{name}") for name in ("adx", "ema", "high_volatility")
    )
    _keys(adx, {"trend_start", "trend_full", "sideway_full", "sideway_zero"}, "regime.adx")
    _keys(
        ema,
        {
            "minimum_slope_atr",
            "full_slope_atr",
            "maximum_sideway_slope_atr",
            "maximum_sideway_dispersion_atr",
        },
        "regime.ema",
    )
    _keys(
        high,
        {
            "atr_percentile_start",
            "atr_percentile_full",
            "bb_percentile_start",
            "bb_percentile_full",
            "true_range_atr_start",
            "true_range_atr_full",
        },
        "regime.high_volatility",
    )

    def weight_map(name: str) -> dict[str, Decimal]:
        return {
            key: _decimal(value, f"regime.weights.{name}.{key}")
            for key, value in _map(weights[name], f"regime.weights.{name}").items()
        }

    return RegimeConfig(
        minimum_evidence_count=int(raw["minimum_evidence_count"]),
        minimum_evidence_strength=_decimal(
            raw["minimum_evidence_strength"], "regime.minimum_evidence_strength"
        ),
        minimum_confidence=_decimal(raw["minimum_confidence"], "regime.minimum_confidence"),
        minimum_candidate_margin=_decimal(
            raw["minimum_candidate_margin"], "regime.minimum_candidate_margin"
        ),
        conflict_tolerance=_decimal(raw["conflict_tolerance"], "regime.conflict_tolerance"),
        required_confirmations=int(raw["required_confirmations"]),
        timeframe_weights={
            _enum(Timeframe, key, "regime.timeframe_weights key"): _decimal(
                value, f"regime.timeframe_weights.{key}"
            )
            for key, value in _map(raw["timeframe_weights"], "regime.timeframe_weights").items()
        },
        trend_candidate_threshold=_decimal(
            raw["trend_candidate_threshold"], "regime.trend_candidate_threshold"
        ),
        sideway_candidate_threshold=_decimal(
            raw["sideway_candidate_threshold"], "regime.sideway_candidate_threshold"
        ),
        high_volatility_candidate_threshold=_decimal(
            raw["high_volatility_candidate_threshold"], "regime.high_volatility_candidate_threshold"
        ),
        trend_weights=weight_map("trend"),
        sideway_weights=weight_map("sideway"),
        high_volatility_weights=weight_map("high_volatility"),
        adx_trend_start=_decimal(adx["trend_start"], "regime.adx.trend_start"),
        adx_trend_full=_decimal(adx["trend_full"], "regime.adx.trend_full"),
        adx_sideway_full=_decimal(adx["sideway_full"], "regime.adx.sideway_full"),
        adx_sideway_zero=_decimal(adx["sideway_zero"], "regime.adx.sideway_zero"),
        ema_minimum_slope_atr=_decimal(ema["minimum_slope_atr"], "regime.ema.minimum_slope_atr"),
        ema_full_slope_atr=_decimal(ema["full_slope_atr"], "regime.ema.full_slope_atr"),
        ema_maximum_sideway_slope_atr=_decimal(
            ema["maximum_sideway_slope_atr"], "regime.ema.maximum_sideway_slope_atr"
        ),
        ema_maximum_sideway_dispersion_atr=_decimal(
            ema["maximum_sideway_dispersion_atr"], "regime.ema.maximum_sideway_dispersion_atr"
        ),
        price_location_tolerance_atr=_decimal(
            raw["price_location_tolerance_atr"], "regime.price_location_tolerance_atr"
        ),
        atr_percentile_start=_decimal(
            high["atr_percentile_start"], "regime.high_volatility.atr_percentile_start"
        ),
        atr_percentile_full=_decimal(
            high["atr_percentile_full"], "regime.high_volatility.atr_percentile_full"
        ),
        bb_percentile_start=_decimal(
            high["bb_percentile_start"], "regime.high_volatility.bb_percentile_start"
        ),
        bb_percentile_full=_decimal(
            high["bb_percentile_full"], "regime.high_volatility.bb_percentile_full"
        ),
        true_range_atr_start=_decimal(
            high["true_range_atr_start"], "regime.high_volatility.true_range_atr_start"
        ),
        true_range_atr_full=_decimal(
            high["true_range_atr_full"], "regime.high_volatility.true_range_atr_full"
        ),
    )


def _levels(raw: Mapping[str, Any]) -> LevelConfig:
    names = tuple(field for field in LevelConfig.__dataclass_fields__ if field != "lookback_bars")
    _keys(raw, {"lookback_bars", *names}, "levels")
    ints = {
        "swing_left_bars",
        "swing_right_bars",
        "minimum_touches",
        "full_strength_touches",
        "maximum_range_stale_bars",
        "breakout_confirmation_bars",
        "retest_expiry_bars",
    }
    kwargs: dict[str, Any] = {
        "lookback_bars": _timeframe_map(
            _map(raw["lookback_bars"], "levels.lookback_bars"),
            lambda value, _: int(value),
            "levels.lookback_bars",
        ),
        "structure_timeframe": _enum(
            Timeframe, raw["structure_timeframe"], "levels.structure_timeframe"
        ),
    }
    for name in set(names) - {"structure_timeframe"}:
        kwargs[name] = int(raw[name]) if name in ints else _decimal(raw[name], f"levels.{name}")
    return LevelConfig(**kwargs)


def _risk(raw: Mapping[str, Any]) -> RiskConfig:
    direct = {
        "risk_per_trade",
        "target_leverage",
        "max_leverage",
        "max_position_notional",
        "max_total_exposure",
        "max_daily_loss",
        "max_daily_drawdown",
        "max_daily_trades",
        "max_consecutive_losses",
        "minimum_rr",
        "max_allowed_spread",
        "max_slippage",
        "cooldown_after_loss",
        "daily_reset_timezone",
        "max_open_positions",
        "margin_buffer_ratio",
        "funding_buffer_intervals",
        "stop",
        "unrealized_drawdown_gate",
    }
    _keys(raw, direct, "risk")
    stop = _map(raw["stop"], "risk.stop")
    _keys(
        stop,
        {
            "min_distance_atr",
            "max_distance_atr",
            "minimum_tick_multiple",
            "minimum_spread_multiple",
        },
        "risk.stop",
    )
    gate = _map(raw["unrealized_drawdown_gate"], "risk.unrealized_drawdown_gate")
    _keys(gate, {"enabled", "max_ratio"}, "risk.unrealized_drawdown_gate")
    decimal_names = (
        "risk_per_trade",
        "target_leverage",
        "max_leverage",
        "max_position_notional",
        "max_total_exposure",
        "max_daily_loss",
        "max_daily_drawdown",
        "minimum_rr",
        "max_allowed_spread",
        "max_slippage",
        "margin_buffer_ratio",
    )
    values = {name: _decimal(raw[name], f"risk.{name}") for name in decimal_names}
    return RiskConfig(
        **values,
        max_daily_trades=int(raw["max_daily_trades"]),
        max_consecutive_losses=int(raw["max_consecutive_losses"]),
        cooldown_after_loss=_duration(raw["cooldown_after_loss"], "risk.cooldown_after_loss"),
        daily_reset_timezone=str(raw["daily_reset_timezone"]),
        max_open_positions=int(raw["max_open_positions"]),
        stop_min_distance_atr=_decimal(stop["min_distance_atr"], "risk.stop.min_distance_atr"),
        stop_max_distance_atr=_decimal(stop["max_distance_atr"], "risk.stop.max_distance_atr"),
        stop_minimum_tick_multiple=_decimal(
            stop["minimum_tick_multiple"], "risk.stop.minimum_tick_multiple"
        ),
        stop_minimum_spread_multiple=_decimal(
            stop["minimum_spread_multiple"], "risk.stop.minimum_spread_multiple"
        ),
        funding_buffer_intervals=int(raw["funding_buffer_intervals"]),
        unrealized_drawdown_gate=UnrealizedDrawdownGateConfig(
            _boolean(gate["enabled"], "risk.unrealized_drawdown_gate.enabled"),
            None
            if gate["max_ratio"] is None
            else _decimal(gate["max_ratio"], "risk.unrealized_drawdown_gate.max_ratio"),
        ),
    )


def _execution(raw: Mapping[str, Any]) -> ExecutionConfig:
    names = set(ExecutionConfig.__dataclass_fields__)
    _keys(raw, names, "execution")
    return ExecutionConfig(
        enabled=_boolean(raw["enabled"], "execution.enabled"),
        dry_run=_boolean(raw["dry_run"], "execution.dry_run"),
        enable_live_trading=_boolean(raw["enable_live_trading"], "execution.enable_live_trading"),
        approval_ttl=_duration(raw["approval_ttl"], "execution.approval_ttl"),
        submit_timeout=_duration(raw["submit_timeout"], "execution.submit_timeout"),
        cancel_timeout=_duration(raw["cancel_timeout"], "execution.cancel_timeout"),
        price_deviation_tolerance=_decimal(
            raw["price_deviation_tolerance"], "execution.price_deviation_tolerance"
        ),
        partial_fill_policy=_enum(
            PartialFillPolicy, raw["partial_fill_policy"], "execution.partial_fill_policy"
        ),
        max_query_retries=int(raw["max_query_retries"]),
        retry_delay=_duration(raw["retry_delay"], "execution.retry_delay"),
        retry_backoff_multiplier=_decimal(
            raw["retry_backoff_multiplier"], "execution.retry_backoff_multiplier"
        ),
        max_retry_delay=_duration(raw["max_retry_delay"], "execution.max_retry_delay"),
    )


def _protection(raw: Mapping[str, Any]) -> ProtectionConfig:
    _keys(raw, set(ProtectionConfig.__dataclass_fields__), "protection")
    return ProtectionConfig(
        _enum(OrderType, raw["stop_order_type"], "protection.stop_order_type"),
        _enum(OrderType, raw["take_profit_order_type"], "protection.take_profit_order_type"),
        _duration(raw["ack_timeout"], "protection.ack_timeout"),
        _boolean(raw["require_stop_before_managing"], "protection.require_stop_before_managing"),
        _enum(
            ProtectionFailurePolicy, raw["stop_failure_policy"], "protection.stop_failure_policy"
        ),
        _enum(
            TakeProfitFailurePolicy,
            raw["take_profit_failure_policy"],
            "protection.take_profit_failure_policy",
        ),
        int(raw["max_recovery_attempts"]),
    )


def _data(raw: Mapping[str, Any]) -> DataConfig:
    _keys(
        raw,
        {
            "timeframes",
            "history_bars",
            "warmup_candles",
            "freshness",
            "gap_policy",
            "ordering_window",
            "max_backfill_attempts",
            "clock_drift_tolerance",
            "store_raw",
        },
        "data",
    )
    timeframes, freshness = (
        _map(raw["timeframes"], "data.timeframes"),
        _map(raw["freshness"], "data.freshness"),
    )
    _keys(timeframes, {"micro", "entry", "context"}, "data.timeframes")
    _keys(
        freshness,
        {
            "candle_5m",
            "candle_15m",
            "candle_1h",
            "quote",
            "account",
            "position",
            "instrument_metadata",
        },
        "data.freshness",
    )
    return DataConfig(
        _enum(Timeframe, timeframes["micro"], "data.timeframes.micro"),
        _enum(Timeframe, timeframes["entry"], "data.timeframes.entry"),
        _enum(Timeframe, timeframes["context"], "data.timeframes.context"),
        _timeframe_map(
            _map(raw["history_bars"], "data.history_bars"),
            lambda value, _: int(value),
            "data.history_bars",
        ),
        _timeframe_map(
            _map(raw["warmup_candles"], "data.warmup_candles"),
            lambda value, _: int(value),
            "data.warmup_candles",
        ),
        {
            Timeframe.M5: _duration(freshness["candle_5m"], "data.freshness.candle_5m"),
            Timeframe.M15: _duration(freshness["candle_15m"], "data.freshness.candle_15m"),
            Timeframe.H1: _duration(freshness["candle_1h"], "data.freshness.candle_1h"),
        },
        _duration(freshness["quote"], "data.freshness.quote"),
        _duration(freshness["account"], "data.freshness.account"),
        _duration(freshness["position"], "data.freshness.position"),
        _duration(freshness["instrument_metadata"], "data.freshness.instrument_metadata"),
        _enum(GapPolicy, raw["gap_policy"], "data.gap_policy"),
        _duration(raw["ordering_window"], "data.ordering_window"),
        int(raw["max_backfill_attempts"]),
        _duration(raw["clock_drift_tolerance"], "data.clock_drift_tolerance"),
        _boolean(raw["store_raw"], "data.store_raw"),
    )


def _historical(raw: Mapping[str, Any]) -> HistoricalConfig:
    expected = {
        "raw_format",
        "source_name",
        "symbol_mapping",
        "timeframe_mapping",
        "column_mapping",
        "timestamp_convention",
        "timestamp_unit",
        "closed_values",
        "conflict_policy",
        "gap_policy",
        "canonical_timeframe",
        "parser_version",
        "normalization_version",
        "resampling_version",
    }
    _keys(raw, expected, "historical")
    symbols = _map(raw["symbol_mapping"], "historical.symbol_mapping")
    timeframes = _map(raw["timeframe_mapping"], "historical.timeframe_mapping")
    columns = _map(raw["column_mapping"], "historical.column_mapping")
    closed_values = raw["closed_values"]
    if not isinstance(closed_values, list) or not all(
        isinstance(value, str) for value in closed_values
    ):
        raise ConfigurationError("historical.closed_values must be a string list")
    return HistoricalConfig(
        _enum(HistoricalRawFormat, raw["raw_format"], "historical.raw_format"),
        str(raw["source_name"]),
        {str(key): str(value) for key, value in symbols.items()},
        {
            str(key): _enum(Timeframe, value, f"historical.timeframe_mapping.{key}")
            for key, value in timeframes.items()
        },
        {str(key): str(value) for key, value in columns.items()},
        _enum(
            TimestampConvention,
            raw["timestamp_convention"],
            "historical.timestamp_convention",
        ),
        _enum(TimestampUnit, raw["timestamp_unit"], "historical.timestamp_unit"),
        frozenset(closed_values),
        _enum(
            HistoricalConflictPolicy,
            raw["conflict_policy"],
            "historical.conflict_policy",
        ),
        _enum(HistoricalGapPolicy, raw["gap_policy"], "historical.gap_policy"),
        _enum(Timeframe, raw["canonical_timeframe"], "historical.canonical_timeframe"),
        str(raw["parser_version"]),
        str(raw["normalization_version"]),
        str(raw["resampling_version"]),
    )


def _backtest(raw: Mapping[str, Any]) -> BacktestConfig:
    expected = set(BacktestConfig.__dataclass_fields__)
    _keys(raw, expected, "backtest")
    fixed_rate = raw["fixed_funding_rate"]
    return BacktestConfig(
        initial_equity=_decimal(raw["initial_equity"], "backtest.initial_equity"),
        execution_timeframe=_enum(
            Timeframe, raw["execution_timeframe"], "backtest.execution_timeframe"
        ),
        entry_fill_policy=_enum(
            BacktestEntryFillPolicy,
            raw["entry_fill_policy"],
            "backtest.entry_fill_policy",
        ),
        intrabar_ambiguity_policy=_enum(
            IntrabarAmbiguityPolicy,
            raw["intrabar_ambiguity_policy"],
            "backtest.intrabar_ambiguity_policy",
        ),
        modeled_spread_rate=_decimal(raw["modeled_spread_rate"], "backtest.modeled_spread_rate"),
        market_slippage_rate=_decimal(raw["market_slippage_rate"], "backtest.market_slippage_rate"),
        stop_slippage_rate=_decimal(raw["stop_slippage_rate"], "backtest.stop_slippage_rate"),
        maker_fee_rate=_decimal(raw["maker_fee_rate"], "backtest.maker_fee_rate"),
        taker_fee_rate=_decimal(raw["taker_fee_rate"], "backtest.taker_fee_rate"),
        funding_mode=_enum(FundingMode, raw["funding_mode"], "backtest.funding_mode"),
        funding_interval=_duration(raw["funding_interval"], "backtest.funding_interval"),
        fixed_funding_rate=(
            None if fixed_rate is None else _decimal(fixed_rate, "backtest.fixed_funding_rate")
        ),
        allow_same_bar_exit_after_entry=_boolean(
            raw["allow_same_bar_exit_after_entry"],
            "backtest.allow_same_bar_exit_after_entry",
        ),
        gap_stop_policy=_enum(GapStopPolicy, raw["gap_stop_policy"], "backtest.gap_stop_policy"),
        target_gap_policy=_enum(
            TargetGapPolicy, raw["target_gap_policy"], "backtest.target_gap_policy"
        ),
        limit_fill_policy=_enum(
            BacktestLimitFillPolicy,
            raw["limit_fill_policy"],
            "backtest.limit_fill_policy",
        ),
        end_position_policy=_enum(
            EndOfBacktestPolicy,
            raw["end_position_policy"],
            "backtest.end_position_policy",
        ),
        halt_stops_run=_boolean(raw["halt_stops_run"], "backtest.halt_stops_run"),
        execution_model_version=str(raw["execution_model_version"]),
        spread_model_version=str(raw["spread_model_version"]),
        funding_algorithm_version=str(raw["funding_algorithm_version"]),
    )


def _journal(raw: Mapping[str, Any]) -> JournalConfig:
    _keys(raw, set(JournalConfig.__dataclass_fields__), "journal")
    return JournalConfig(
        _enum(JournalBackend, raw["backend"], "journal.backend"),
        Path(str(raw["database_path"])),
        _boolean(raw["append_only"], "journal.append_only"),
        _boolean(raw["require_write_before_submit"], "journal.require_write_before_submit"),
        _duration(raw["busy_timeout"], "journal.busy_timeout"),
        None if raw["retention_days"] is None else int(raw["retention_days"]),
    )


def _monitoring(raw: Mapping[str, Any]) -> MonitoringConfig:
    _keys(raw, set(MonitoringConfig.__dataclass_fields__), "monitoring")
    return MonitoringConfig(
        _duration(raw["health_interval"], "monitoring.health_interval"),
        _duration(raw["reconciliation_interval"], "monitoring.reconciliation_interval"),
        _duration(raw["api_error_window"], "monitoring.api_error_window"),
        int(raw["api_error_limit"]),
        tuple(str(value) for value in raw["alert_channels"]),
        _boolean(
            raw["kill_switch_requires_manual_reset"], "monitoring.kill_switch_requires_manual_reset"
        ),
    )
