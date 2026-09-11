"""Deterministic identities for backtest assumptions and complete runs."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal

from trading_bot.config.models import (
    BacktestConfig,
    CalculationConfig,
    ExecutionConfig,
    RiskConfig,
)
from trading_bot.domain.identifiers import deterministic_id
from trading_bot.domain.risk_models import InstrumentMetadata
from trading_bot.domain.value_objects import VersionSet
from trading_bot.historical.models import HistoricalVersionSet


def execution_model_version(
    config: BacktestConfig,
    execution: ExecutionConfig,
    risk: RiskConfig,
    calculation: CalculationConfig,
) -> str:
    return deterministic_id(
        "backtest-execution-model-v2-last-mile-validation",
        config.execution_model_version,
        config.execution_timeframe,
        config.entry_fill_policy,
        config.intrabar_ambiguity_policy,
        config.allow_same_bar_exit_after_entry,
        config.gap_stop_policy,
        config.target_gap_policy,
        config.limit_fill_policy,
        config.end_position_policy,
        config.halt_stops_run,
        execution.price_deviation_tolerance,
        risk.minimum_rr,
        risk.max_slippage,
        risk.stop_min_distance_atr,
        risk.stop_max_distance_atr,
        risk.stop_minimum_tick_multiple,
        risk.stop_minimum_spread_multiple,
        risk.max_position_notional,
        risk.max_total_exposure,
        risk.max_leverage,
        risk.margin_buffer_ratio,
        risk.funding_buffer_intervals,
        calculation.decimal_precision,
        calculation.rounding_mode,
        "approved-quantity-no-resize",
        "actual-fill-worst-loss-v1",
    )


def cost_model_version(config: BacktestConfig, funding_provider_version: str) -> str:
    return deterministic_id(
        "backtest-cost-model-v1",
        config.spread_model_version,
        config.modeled_spread_rate,
        config.market_slippage_rate,
        config.stop_slippage_rate,
        config.maker_fee_rate,
        config.taker_fee_rate,
        config.funding_mode,
        config.funding_interval,
        config.fixed_funding_rate,
        config.funding_algorithm_version,
        funding_provider_version,
    )


def run_id(
    versions: VersionSet,
    historical_versions: HistoricalVersionSet,
    metadata: InstrumentMetadata,
    execution_version: str,
    cost_version: str,
    funding_version: str,
    start_time: datetime,
    end_time: datetime,
    initial_equity: Decimal,
) -> str:
    return deterministic_id(
        "backtest-run-v1",
        versions.code_version,
        versions.strategy_version,
        versions.config_version,
        historical_versions.m5_data_version,
        historical_versions.m15_data_version,
        historical_versions.h1_data_version,
        historical_versions.snapshot_data_version,
        metadata.version,
        execution_version,
        cost_version,
        funding_version,
        start_time,
        end_time,
        initial_equity,
    )


def historical_run_versions(
    versions: VersionSet, historical_versions: HistoricalVersionSet
) -> VersionSet:
    return replace(versions, data_version=historical_versions.snapshot_data_version)
