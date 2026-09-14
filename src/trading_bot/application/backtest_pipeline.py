"""Application orchestration for a complete versioned historical backtest."""

from __future__ import annotations

from datetime import datetime

from trading_bot.application.historical_pipeline import (
    build_historical_snapshot_sequence,
    replay_historical_sequence,
)
from trading_bot.backtest.costs import risk_cost_rates
from trading_bot.backtest.engine import BacktestEngine
from trading_bot.backtest.funding import FundingRateProvider, provider_from_config
from trading_bot.backtest.models import BacktestFailure, BacktestResult, BacktestRunSpec
from trading_bot.backtest.versions import (
    cost_model_version,
    execution_model_version,
    historical_run_versions,
    run_id,
)
from trading_bot.config.loader import config_version
from trading_bot.config.models import AppConfig
from trading_bot.domain.enums import (
    BacktestFailureKind,
    BacktestStatus,
    ExecutionEnvironment,
    FundingMode,
    Timeframe,
)
from trading_bot.domain.errors import DomainValidationError, HistoricalDataError
from trading_bot.domain.identifiers import deterministic_id
from trading_bot.domain.primitives import require_utc
from trading_bot.domain.risk_models import InstrumentMetadata
from trading_bot.domain.value_objects import VersionSet
from trading_bot.historical.models import HistoricalVersionSet
from trading_bot.historical.repository import HistoricalCandleRepository


def attempt_historical_backtest(
    repository: HistoricalCandleRepository,
    symbol: str,
    historical_versions: HistoricalVersionSet,
    start_time: datetime,
    end_time: datetime,
    config: AppConfig,
    versions: VersionSet,
    metadata: InstrumentMetadata,
    funding_provider: FundingRateProvider | None = None,
    *,
    state_warmup_start_time: datetime | None = None,
) -> BacktestResult | BacktestFailure:
    """Convert expected invalid-input/data failures into a typed FAILED outcome."""
    try:
        return run_historical_backtest(
            repository,
            symbol,
            historical_versions,
            start_time,
            end_time,
            config,
            versions,
            metadata,
            funding_provider,
            state_warmup_start_time=state_warmup_start_time,
        )
    except HistoricalDataError as error:
        return BacktestFailure(
            BacktestStatus.FAILED,
            BacktestFailureKind.HISTORICAL_DATA,
            str(error),
        )
    except DomainValidationError as error:
        return BacktestFailure(
            BacktestStatus.FAILED,
            BacktestFailureKind.VALIDATION,
            str(error),
        )


def run_historical_backtest(
    repository: HistoricalCandleRepository,
    symbol: str,
    historical_versions: HistoricalVersionSet,
    start_time: datetime,
    end_time: datetime,
    config: AppConfig,
    versions: VersionSet,
    metadata: InstrumentMetadata,
    funding_provider: FundingRateProvider | None = None,
    *,
    state_warmup_start_time: datetime | None = None,
) -> BacktestResult:
    require_utc(start_time, "backtest start_time")
    require_utc(end_time, "backtest end_time")
    if end_time <= start_time:
        raise DomainValidationError("backtest end_time must be after start_time")
    if state_warmup_start_time is not None:
        require_utc(state_warmup_start_time, "state_warmup_start_time")
        if state_warmup_start_time >= start_time:
            raise DomainValidationError("state warmup must begin before backtest start_time")
    if config.market.environment is not ExecutionEnvironment.BACKTEST:
        raise DomainValidationError("historical backtest requires BACKTEST environment")
    if symbol != config.market.symbol or metadata.symbol != symbol:
        raise DomainValidationError("backtest symbol/config/metadata mismatch")
    if metadata.quote_currency != config.market.quote_currency:
        raise DomainValidationError("instrument quote currency mismatch")
    if metadata.effective_at > start_time:
        raise DomainValidationError("instrument metadata is not effective at backtest start")
    if versions.strategy_version != config.strategy.version:
        raise DomainValidationError("strategy version does not match loaded strategy")
    if versions.config_version != config_version(config):
        raise DomainValidationError("config version does not match loaded configuration")
    provider = funding_provider or provider_from_config(config.backtest)
    if provider.mode is not config.backtest.funding_mode:
        raise DomainValidationError("funding provider mode does not match backtest config")
    if config.backtest.funding_mode is FundingMode.HISTORICAL_SERIES and funding_provider is None:
        raise DomainValidationError("historical funding mode requires an injected provider")
    provider.validate_range(start_time, end_time)
    execution_version = execution_model_version(
        config.backtest, config.execution, config.risk, config.calculation
    )
    cost_version = cost_model_version(config.backtest, provider.model_version)
    funding_debit_rate = provider.maximum_debit_rate * config.risk.funding_buffer_intervals
    costs = risk_cost_rates(config.backtest, cost_version, funding_debit_rate)
    run_versions = historical_run_versions(versions, historical_versions)
    snapshot_start = state_warmup_start_time or start_time
    snapshots = build_historical_snapshot_sequence(
        repository,
        symbol,
        historical_versions,
        snapshot_start,
        end_time,
        config,
        run_versions,
    )
    if snapshots.failures:
        raise DomainValidationError("historical snapshot sequence contains failures")
    if not snapshots.snapshots:
        raise DomainValidationError("backtest range has no warmup-eligible M15 snapshots")
    replayed_evaluations = replay_historical_sequence(snapshots, config, run_versions, costs)
    evaluations = tuple(
        evaluation for evaluation in replayed_evaluations if evaluation.decision.as_of >= start_time
    )
    if not evaluations:
        raise DomainValidationError("backtest range has no official M15 evaluations")
    candles_m5 = tuple(
        repository.get_candles(
            symbol,
            Timeframe.M5,
            start_time,
            end_time,
            historical_versions.m5_data_version,
        )
    )
    identifier = run_id(
        run_versions,
        historical_versions,
        metadata,
        execution_version,
        cost_version,
        provider.model_version,
        start_time,
        end_time,
        config.backtest.initial_equity,
    )
    if state_warmup_start_time is not None:
        identifier = deterministic_id(
            "state-warmed-backtest-v1",
            identifier,
            state_warmup_start_time,
        )
    spec = BacktestRunSpec(
        identifier,
        symbol,
        start_time,
        end_time,
        config.backtest.initial_equity,
        run_versions,
        historical_versions,
        metadata.version,
        execution_version,
        cost_version,
        provider.model_version,
    )
    return BacktestEngine(spec, config, metadata, costs, provider).run(candles_m5, evaluations)
