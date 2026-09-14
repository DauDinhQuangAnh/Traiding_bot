"""Immutable PHASE 6 validation contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum, unique

from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.primitives import (
    require_finite,
    require_non_empty,
    require_non_negative,
    require_ratio,
    require_utc,
)
from trading_bot.historical.models import HistoricalVersionSet


@unique
class PartitionType(StrEnum):
    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    TEST = "TEST"


@unique
class StateContinuityPolicy(StrEnum):
    CONTINUOUS_CHRONOLOGICAL = "CONTINUOUS_CHRONOLOGICAL"


@unique
class WalkForwardMode(StrEnum):
    ANCHORED = "ANCHORED"
    ROLLING = "ROLLING"


@unique
class RobustnessStatus(StrEnum):
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    FRAGILE = "FRAGILE"
    MIXED = "MIXED"
    ROBUST_CANDIDATE = "ROBUST_CANDIDATE"
    NOT_EVALUATED = "NOT_EVALUATED"


@unique
class ImplementationStatus(StrEnum):
    PASS = "PASS"
    NEEDS_WORK = "NEEDS_WORK"


@dataclass(frozen=True, slots=True)
class RobustnessEvidenceRequirements:
    require_walk_forward: bool = True
    require_sensitivity: bool = True
    require_cost_stress: bool = True


@dataclass(frozen=True, slots=True)
class EvaluationRange:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        require_utc(self.start, "range start")
        require_utc(self.end, "range end")
        if self.end <= self.start:
            raise DomainValidationError("range end must be after start")


@dataclass(frozen=True, slots=True)
class TemporalSplitSpec:
    split_id: str
    train: EvaluationRange
    validation: EvaluationRange
    test: EvaluationRange
    purge_duration: timedelta
    embargo_duration: timedelta
    timezone: str
    split_version: str

    def __post_init__(self) -> None:
        for name in ("split_id", "timezone", "split_version"):
            require_non_empty(getattr(self, name), name)
        if self.timezone != "UTC":
            raise DomainValidationError("temporal split timezone must be UTC")
        for name in ("purge_duration", "embargo_duration"):
            if getattr(self, name) < timedelta(0):
                raise DomainValidationError(f"{name} must be non-negative")
        separation = self.purge_duration + self.embargo_duration
        if self.train.end + separation > self.validation.start:
            raise DomainValidationError("TRAIN and VALIDATION violate purge/embargo boundary")
        if self.validation.end + separation > self.test.start:
            raise DomainValidationError("VALIDATION and TEST violate purge/embargo boundary")


@dataclass(frozen=True, slots=True)
class PartitionWindow:
    partition: PartitionType
    data_start: datetime
    evaluation: EvaluationRange

    def __post_init__(self) -> None:
        require_utc(self.data_start, "partition data_start")
        if self.data_start > self.evaluation.start:
            raise DomainValidationError("partition data_start cannot follow evaluation start")


@dataclass(frozen=True, slots=True)
class WalkForwardSpec:
    mode: WalkForwardMode
    train_start: datetime
    first_oos_start: datetime
    end: datetime
    training_window: timedelta
    oos_window: timedelta
    step: timedelta
    warmup_duration: timedelta
    allow_oos_overlap: bool = False

    def __post_init__(self) -> None:
        for name in ("train_start", "first_oos_start", "end"):
            require_utc(getattr(self, name), name)
        if not self.train_start < self.first_oos_start < self.end:
            raise DomainValidationError("walk-forward boundaries must be chronological")
        for name in ("training_window", "oos_window", "step"):
            if getattr(self, name) <= timedelta(0):
                raise DomainValidationError(f"{name} must be positive")
        if self.warmup_duration < timedelta(0):
            raise DomainValidationError("warmup_duration must be non-negative")
        if not self.allow_oos_overlap and self.step < self.oos_window:
            raise DomainValidationError("walk-forward OOS windows must not overlap")
        if (
            self.mode is WalkForwardMode.ROLLING
            and self.first_oos_start - self.train_start < self.training_window
        ):
            raise DomainValidationError("first rolling window lacks training history")


@dataclass(frozen=True, slots=True)
class WalkForwardWindow:
    window_id: str
    sequence: int
    training: EvaluationRange
    oos: EvaluationRange
    data_start: datetime

    def __post_init__(self) -> None:
        require_non_empty(self.window_id, "window_id")
        if self.sequence < 0:
            raise DomainValidationError("walk-forward sequence must be non-negative")
        require_utc(self.data_start, "walk-forward data_start")
        if self.data_start > self.training.start or self.training.end > self.oos.start:
            raise DomainValidationError("invalid walk-forward chronology")


@dataclass(frozen=True, slots=True)
class GroupMetric:
    dimension: str
    value: str
    trade_count: int
    net_pnl: Decimal
    profit_factor: Decimal | None
    expectancy_r: Decimal | None
    insufficient_sample: bool

    def __post_init__(self) -> None:
        require_non_empty(self.dimension, "group dimension")
        require_non_empty(self.value, "group value")
        if self.trade_count < 0:
            raise DomainValidationError("group trade_count must be non-negative")
        require_finite(self.net_pnl, "group net_pnl")
        for name in ("profit_factor", "expectancy_r"):
            value = getattr(self, name)
            if value is not None:
                require_finite(value, name)


@dataclass(frozen=True, slots=True)
class ValidationMetrics:
    trade_count: int
    net_pnl: Decimal
    return_ratio: Decimal
    profit_factor: Decimal | None
    expectancy_r: Decimal | None
    maximum_drawdown: Decimal
    maximum_drawdown_ratio: Decimal
    win_rate: Decimal | None
    exposure: Decimal
    total_costs: Decimal
    gross_profit: Decimal
    gross_loss: Decimal
    groups: tuple[GroupMetric, ...]
    insufficient_sample: bool

    def __post_init__(self) -> None:
        if self.trade_count < 0:
            raise DomainValidationError("trade_count must be non-negative")
        for name in (
            "net_pnl",
            "return_ratio",
            "maximum_drawdown",
            "maximum_drawdown_ratio",
            "exposure",
            "total_costs",
            "gross_profit",
            "gross_loss",
        ):
            require_finite(getattr(self, name), name)
        require_non_negative(self.maximum_drawdown, "maximum_drawdown")
        require_non_negative(self.maximum_drawdown_ratio, "maximum_drawdown_ratio")
        require_non_negative(self.total_costs, "total_costs")
        require_non_negative(self.gross_profit, "gross_profit")
        require_non_negative(self.gross_loss, "gross_loss")
        require_ratio(self.exposure, "exposure")
        if self.win_rate is not None:
            require_ratio(self.win_rate, "win_rate")
        for name in ("profit_factor", "expectancy_r"):
            value = getattr(self, name)
            if value is not None:
                require_finite(value, name)


@dataclass(frozen=True, slots=True)
class ExecutionPathFingerprint:
    trade_count: int
    fingerprint: str

    def __post_init__(self) -> None:
        if self.trade_count < 0:
            raise DomainValidationError("execution path trade_count must be non-negative")
        require_non_empty(self.fingerprint, "execution path fingerprint")


@dataclass(frozen=True, slots=True)
class PartitionResult:
    partition_result_id: str
    partition: PartitionType
    window: PartitionWindow
    backtest_run_id: str
    strategy_version: str
    config_version: str
    execution_model_version: str
    cost_model_version: str
    funding_model_version: str
    instrument_metadata_version: str
    historical_versions: HistoricalVersionSet
    metrics: ValidationMetrics

    def __post_init__(self) -> None:
        for name in (
            "partition_result_id",
            "backtest_run_id",
            "strategy_version",
            "config_version",
            "execution_model_version",
            "cost_model_version",
            "funding_model_version",
            "instrument_metadata_version",
        ):
            require_non_empty(getattr(self, name), name)
        if self.partition is not self.window.partition:
            raise DomainValidationError("partition result/window mismatch")


@dataclass(frozen=True, slots=True)
class ValidationProtocol:
    protocol_id: str
    protocol_version: str
    code_version: str
    strategy_version: str
    config_version: str
    split_id: str
    historical_versions: HistoricalVersionSet
    execution_model_version: str
    cost_model_version: str
    funding_model_version: str
    instrument_metadata_version: str
    robustness_evidence_requirements: RobustnessEvidenceRequirements
    allowed_sensitivity_dimensions: tuple[str, ...]
    state_policy: StateContinuityPolicy
    test_locked: bool
    test_evaluation_count: int

    def __post_init__(self) -> None:
        for name in (
            "protocol_id",
            "protocol_version",
            "code_version",
            "strategy_version",
            "config_version",
            "split_id",
            "execution_model_version",
            "cost_model_version",
            "funding_model_version",
            "instrument_metadata_version",
        ):
            require_non_empty(getattr(self, name), name)
        if len(set(self.allowed_sensitivity_dimensions)) != len(
            self.allowed_sensitivity_dimensions
        ):
            raise DomainValidationError("sensitivity dimensions must be unique")
        if self.test_evaluation_count < 0:
            raise DomainValidationError("test_evaluation_count must be non-negative")
        if self.test_evaluation_count and not self.test_locked:
            raise DomainValidationError("consumed TEST requires a locked protocol")


@dataclass(frozen=True, slots=True)
class WalkForwardWindowResult:
    window: WalkForwardWindow
    result: PartitionResult

    def __post_init__(self) -> None:
        if self.result.partition is not PartitionType.TEST:
            raise DomainValidationError("walk-forward result must be OOS/TEST typed")
        if self.result.window.evaluation != self.window.oos:
            raise DomainValidationError("walk-forward result range mismatch")


@dataclass(frozen=True, slots=True)
class WalkForwardSummary:
    window_count: int
    positive_windows: int
    negative_windows: int
    positive_window_ratio: Decimal | None
    median_window_expectancy_r: Decimal | None
    median_window_profit_factor: Decimal | None
    weighted_expectancy_r: Decimal | None
    aggregate_profit_factor: Decimal | None
    worst_oos_drawdown: Decimal

    def __post_init__(self) -> None:
        if min(self.window_count, self.positive_windows, self.negative_windows) < 0:
            raise DomainValidationError("walk-forward counts must be non-negative")
        if self.positive_windows + self.negative_windows > self.window_count:
            raise DomainValidationError("walk-forward sign counts exceed window count")
        if self.positive_window_ratio is not None:
            require_ratio(self.positive_window_ratio, "positive_window_ratio")
        for name in (
            "median_window_expectancy_r",
            "median_window_profit_factor",
            "weighted_expectancy_r",
            "aggregate_profit_factor",
        ):
            value = getattr(self, name)
            if value is not None:
                require_finite(value, name)
        require_non_negative(self.worst_oos_drawdown, "worst_oos_drawdown")


@dataclass(frozen=True, slots=True)
class SensitivityEvaluation:
    partition: PartitionType
    evaluation_range: EvaluationRange
    backtest_run_id: str
    historical_versions: HistoricalVersionSet
    strategy_version: str
    config_version: str
    execution_model_version: str
    cost_model_version: str
    funding_model_version: str
    instrument_metadata_version: str
    metrics: ValidationMetrics

    def __post_init__(self) -> None:
        for name in (
            "backtest_run_id",
            "strategy_version",
            "config_version",
            "execution_model_version",
            "cost_model_version",
            "funding_model_version",
            "instrument_metadata_version",
        ):
            require_non_empty(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class SensitivityResult:
    sensitivity_id: str
    parameter: str
    baseline_value: Decimal
    perturbed_value: Decimal
    multiplier: Decimal
    is_baseline: bool
    evaluation: SensitivityEvaluation

    def __post_init__(self) -> None:
        require_non_empty(self.sensitivity_id, "sensitivity_id")
        require_non_empty(self.parameter, "parameter")
        for name in ("baseline_value", "perturbed_value", "multiplier"):
            require_finite(getattr(self, name), name)
        if self.multiplier <= Decimal("0"):
            raise DomainValidationError("sensitivity multiplier must be positive")
        if self.is_baseline != (self.multiplier == Decimal("1")):
            raise DomainValidationError("sensitivity baseline marker mismatch")
        if self.evaluation.partition is PartitionType.TEST:
            raise DomainValidationError("final TEST cannot be used for sensitivity")

    @property
    def evaluation_partition(self) -> PartitionType:
        return self.evaluation.partition

    @property
    def metrics(self) -> ValidationMetrics:
        return self.evaluation.metrics


@dataclass(frozen=True, slots=True)
class CostStressResult:
    stress_id: str
    multiplier: Decimal
    stressed_cost_model_version: str
    execution_path: ExecutionPathFingerprint
    metrics: ValidationMetrics

    def __post_init__(self) -> None:
        require_non_empty(self.stress_id, "stress_id")
        require_non_empty(self.stressed_cost_model_version, "stressed_cost_model_version")
        require_finite(self.multiplier, "stress multiplier")
        if self.multiplier < Decimal("1"):
            raise DomainValidationError("cost stress multiplier must be at least one")
        if self.metrics.trade_count != self.execution_path.trade_count:
            raise DomainValidationError("cost stress metrics/path trade count mismatch")


@dataclass(frozen=True, slots=True)
class TestConsumptionRecord:
    protocol_id: str
    consumption_event_id: str
    consumption_index: int
    validation_run_id: str

    def __post_init__(self) -> None:
        for name in ("protocol_id", "consumption_event_id", "validation_run_id"):
            require_non_empty(getattr(self, name), name)
        if self.consumption_index <= 0:
            raise DomainValidationError("consumption_index must be positive")


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    benchmark_id: str
    benchmark_type: str
    evaluation: EvaluationRange
    net_pnl: Decimal
    return_ratio: Decimal
    maximum_drawdown: Decimal
    maximum_drawdown_ratio: Decimal
    exposure: Decimal
    total_costs: Decimal

    def __post_init__(self) -> None:
        require_non_empty(self.benchmark_id, "benchmark_id")
        require_non_empty(self.benchmark_type, "benchmark_type")
        for name in (
            "net_pnl",
            "return_ratio",
            "maximum_drawdown",
            "maximum_drawdown_ratio",
            "exposure",
            "total_costs",
        ):
            require_finite(getattr(self, name), name)
        require_non_negative(self.maximum_drawdown, "benchmark maximum_drawdown")
        require_non_negative(self.maximum_drawdown_ratio, "benchmark maximum_drawdown_ratio")
        require_ratio(self.exposure, "benchmark exposure")
        require_non_negative(self.total_costs, "benchmark total_costs")


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    bootstrap_id: str
    seed: int
    iterations: int
    sample_size: int
    expectancy_r_median: Decimal | None
    expectancy_r_p05: Decimal | None
    expectancy_r_p95: Decimal | None
    net_pnl_median: Decimal | None
    net_pnl_p05: Decimal | None
    net_pnl_p95: Decimal | None
    profit_factor_median: Decimal | None
    profit_factor_p05: Decimal | None
    profit_factor_p95: Decimal | None

    def __post_init__(self) -> None:
        require_non_empty(self.bootstrap_id, "bootstrap_id")
        if self.iterations <= 0 or self.sample_size < 0:
            raise DomainValidationError("invalid bootstrap counts")
        for name in (
            "expectancy_r_median",
            "expectancy_r_p05",
            "expectancy_r_p95",
            "net_pnl_median",
            "net_pnl_p05",
            "net_pnl_p95",
            "profit_factor_median",
            "profit_factor_p05",
            "profit_factor_p95",
        ):
            value = getattr(self, name)
            if value is not None:
                require_finite(value, name)


@dataclass(frozen=True, slots=True)
class ValidationRun:
    validation_run_id: str
    protocol: ValidationProtocol
    split: TemporalSplitSpec
    historical_versions: HistoricalVersionSet
    partitions: tuple[PartitionResult, ...]
    walk_forward: tuple[WalkForwardWindowResult, ...]
    walk_forward_summary: WalkForwardSummary
    sensitivity: tuple[SensitivityResult, ...]
    stress: tuple[CostStressResult, ...]
    benchmarks: tuple[BenchmarkResult, ...]
    bootstrap: BootstrapResult | None
    implementation_status: ImplementationStatus
    robustness_status: RobustnessStatus
    test_consumed: bool
    test_consumption_event_id: str
    test_consumption_index: int | None
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        require_non_empty(self.validation_run_id, "validation_run_id")
        require_non_empty(self.test_consumption_event_id, "test_consumption_event_id")
        if self.protocol.split_id != self.split.split_id:
            raise DomainValidationError("validation protocol/split mismatch")
        if self.protocol.historical_versions != self.historical_versions:
            raise DomainValidationError("validation protocol/historical version mismatch")
        if tuple(item.partition for item in self.partitions) != tuple(PartitionType):
            raise DomainValidationError("validation run requires ordered TRAIN/VALIDATION/TEST")
        for partition_result in self.partitions:
            identities = (
                partition_result.strategy_version == self.protocol.strategy_version,
                partition_result.config_version == self.protocol.config_version,
                partition_result.execution_model_version == self.protocol.execution_model_version,
                partition_result.cost_model_version == self.protocol.cost_model_version,
                partition_result.funding_model_version == self.protocol.funding_model_version,
                partition_result.instrument_metadata_version
                == self.protocol.instrument_metadata_version,
                partition_result.historical_versions == self.historical_versions,
            )
            if not all(identities):
                raise DomainValidationError("validation partition changed frozen semantics")
        for sensitivity_result in self.sensitivity:
            evaluation = sensitivity_result.evaluation
            identities = (
                evaluation.historical_versions == self.historical_versions,
                evaluation.strategy_version == self.protocol.strategy_version,
                evaluation.config_version == self.protocol.config_version,
                evaluation.execution_model_version == self.protocol.execution_model_version,
                evaluation.cost_model_version == self.protocol.cost_model_version,
                evaluation.funding_model_version == self.protocol.funding_model_version,
                evaluation.instrument_metadata_version == self.protocol.instrument_metadata_version,
            )
            if not all(identities):
                raise DomainValidationError("sensitivity changed frozen semantics")
        if not self.test_consumed:
            raise DomainValidationError("validation run must record final TEST consumption")
        if self.test_consumed and not self.protocol.test_locked:
            raise DomainValidationError("TEST consumption requires protocol lock")
        if self.test_consumption_index is None:
            if self.protocol.test_evaluation_count != 0:
                raise DomainValidationError("unpersisted TEST consumption count must be zero")
        elif (
            self.test_consumption_index <= 0
            or self.protocol.test_evaluation_count != self.test_consumption_index
        ):
            raise DomainValidationError("persisted TEST consumption index/count mismatch")
        if not self.limitations:
            raise DomainValidationError("validation run must disclose limitations")
