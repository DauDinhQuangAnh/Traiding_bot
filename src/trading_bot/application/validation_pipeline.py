"""Application orchestration for fixed-semantics chronological validation."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import cast

from trading_bot.application.backtest_pipeline import run_historical_backtest
from trading_bot.backtest.funding import FundingRateProvider, provider_from_config
from trading_bot.backtest.models import BacktestResult
from trading_bot.backtest.versions import cost_model_version, execution_model_version
from trading_bot.config.loader import config_version
from trading_bot.config.models import AppConfig, CalculationConfig
from trading_bot.domain.enums import Timeframe
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.market_models import Candle
from trading_bot.domain.risk_models import InstrumentMetadata
from trading_bot.domain.value_objects import VersionSet
from trading_bot.historical.models import HistoricalVersionSet
from trading_bot.historical.repository import HistoricalCandleRepository
from trading_bot.validation.identity import partition_result_id, validation_run_id
from trading_bot.validation.metrics import project_validation_metrics
from trading_bot.validation.models import (
    BenchmarkResult,
    BootstrapResult,
    CostStressResult,
    ImplementationStatus,
    PartitionResult,
    PartitionWindow,
    RobustnessStatus,
    SensitivityResult,
    TemporalSplitSpec,
    ValidationProtocol,
    ValidationRun,
    WalkForwardWindowResult,
)
from trading_bot.validation.splits import partition_windows
from trading_bot.validation.walk_forward_metrics import summarize_walk_forward


class _BoundedHistoricalRepository:
    """Prevent snapshot warmup from reading before the declared data boundary."""

    def __init__(self, delegate: HistoricalCandleRepository, data_start: datetime) -> None:
        self._delegate = delegate
        self._data_start = data_start

    def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
        data_version: str,
    ) -> Sequence[Candle]:
        return self._delegate.get_candles(
            symbol, timeframe, max(start, self._data_start), end, data_version
        )

    def latest_before(
        self,
        symbol: str,
        timeframe: Timeframe,
        as_of: datetime,
        count: int,
        data_version: str,
    ) -> Sequence[Candle]:
        return tuple(
            candle
            for candle in self._delegate.latest_before(
                symbol, timeframe, as_of, count, data_version
            )
            if candle.open_time >= self._data_start
        )


def run_baseline_validation(
    repository: HistoricalCandleRepository,
    symbol: str,
    historical_versions: HistoricalVersionSet,
    split: TemporalSplitSpec,
    protocol: ValidationProtocol,
    config: AppConfig,
    versions: VersionSet,
    metadata: InstrumentMetadata,
    *,
    minimum_sample_size: int,
    requested_warmup: timedelta | None = None,
    funding_provider: FundingRateProvider | None = None,
) -> ValidationRun:
    """Run one frozen strategy/config across TRAIN, VALIDATION and final TEST."""
    _validate_protocol(protocol, split.split_id, config, versions, metadata, funding_provider)
    windows = partition_windows(split, config, requested_warmup=requested_warmup)
    partitions = tuple(
        _run_partition(
            repository,
            symbol,
            historical_versions,
            window,
            protocol,
            config,
            versions,
            metadata,
            minimum_sample_size,
            funding_provider,
        )
        for window in windows
    )
    return assemble_validation_run(
        protocol,
        split,
        historical_versions,
        partitions,
        config.calculation,
        limitations=(
            "M5 OHLC has no intrabar path or order-book queue.",
            "Spread, slippage, fees and funding are modeled assumptions.",
            "No liquidation model; historical evidence is not a future guarantee.",
        ),
    )


def assemble_validation_run(
    protocol: ValidationProtocol,
    split: TemporalSplitSpec,
    historical_versions: HistoricalVersionSet,
    partitions: tuple[PartitionResult, ...],
    calculation: CalculationConfig,
    *,
    walk_forward: tuple[WalkForwardWindowResult, ...] = (),
    sensitivity: tuple[SensitivityResult, ...] = (),
    stress: tuple[CostStressResult, ...] = (),
    benchmarks: tuple[BenchmarkResult, ...] = (),
    uncertainty: BootstrapResult | None = None,
    robustness_status: RobustnessStatus = RobustnessStatus.NOT_EVALUATED,
    limitations: tuple[str, ...],
) -> ValidationRun:
    identifier = validation_run_id(
        protocol,
        split,
        historical_versions,
        tuple(item.window for item in walk_forward),
        tuple((item.parameter, item.baseline_value, item.multiplier) for item in sensitivity),
        tuple(item.multiplier for item in stress),
        None if uncertainty is None else uncertainty.bootstrap_id,
        tuple(item.benchmark_id for item in benchmarks),
    )
    return ValidationRun(
        identifier,
        protocol,
        split,
        historical_versions,
        partitions,
        walk_forward,
        summarize_walk_forward(walk_forward, calculation),
        sensitivity,
        stress,
        benchmarks,
        uncertainty,
        ImplementationStatus.PASS,
        robustness_status,
        protocol.test_evaluation_count > 0,
        limitations,
    )


def _run_partition(
    repository: HistoricalCandleRepository,
    symbol: str,
    historical_versions: HistoricalVersionSet,
    window: PartitionWindow,
    protocol: ValidationProtocol,
    config: AppConfig,
    versions: VersionSet,
    metadata: InstrumentMetadata,
    minimum_sample_size: int,
    funding_provider: FundingRateProvider | None,
) -> PartitionResult:
    bounded = _BoundedHistoricalRepository(repository, window.data_start)
    backtest = run_historical_backtest(
        cast(HistoricalCandleRepository, bounded),
        symbol,
        historical_versions,
        window.data_start,
        window.evaluation.end,
        config,
        versions,
        metadata,
        funding_provider,
    )
    _validate_backtest_identity(backtest, protocol)
    metrics = project_validation_metrics(
        backtest,
        window.evaluation,
        minimum_sample_size=minimum_sample_size,
        calculation=config.calculation,
    )
    spec = backtest.run.spec
    return PartitionResult(
        partition_result_id(protocol.protocol_id, window.partition, window, spec.backtest_run_id),
        window.partition,
        window,
        spec.backtest_run_id,
        spec.versions.strategy_version,
        spec.versions.config_version,
        spec.execution_model_version,
        spec.cost_model_version,
        spec.funding_model_version,
        spec.instrument_metadata_version,
        spec.historical_versions,
        metrics,
    )


def _validate_protocol(
    protocol: ValidationProtocol,
    split_id: str,
    config: AppConfig,
    versions: VersionSet,
    metadata: InstrumentMetadata,
    funding_provider: FundingRateProvider | None,
) -> None:
    if not protocol.test_locked or protocol.test_evaluation_count <= 0:
        raise DomainValidationError("final TEST evaluation requires an explicit locked protocol")
    provider = funding_provider or provider_from_config(config.backtest)
    expected = {
        "strategy": config.strategy.version,
        "config": config_version(config),
        "split": split_id,
        "execution": execution_model_version(
            config.backtest, config.execution, config.risk, config.calculation
        ),
        "cost": cost_model_version(config.backtest, provider.model_version),
        "funding": provider.model_version,
        "instrument": metadata.version,
    }
    actual = {
        "strategy": protocol.strategy_version,
        "config": protocol.config_version,
        "split": protocol.split_id,
        "execution": protocol.execution_model_version,
        "cost": protocol.cost_model_version,
        "funding": protocol.funding_model_version,
        "instrument": protocol.instrument_metadata_version,
    }
    if (
        actual != expected
        or versions.strategy_version != protocol.strategy_version
        or versions.config_version != protocol.config_version
    ):
        raise DomainValidationError("validation protocol semantic identity mismatch")


def _validate_backtest_identity(result: BacktestResult, protocol: ValidationProtocol) -> None:
    spec = result.run.spec
    identities = (
        spec.versions.strategy_version == protocol.strategy_version,
        spec.versions.config_version == protocol.config_version,
        spec.execution_model_version == protocol.execution_model_version,
        spec.cost_model_version == protocol.cost_model_version,
        spec.funding_model_version == protocol.funding_model_version,
        spec.instrument_metadata_version == protocol.instrument_metadata_version,
    )
    if not all(identities):
        raise DomainValidationError("partition backtests changed frozen semantics")
