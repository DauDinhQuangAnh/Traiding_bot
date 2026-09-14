"""Local parameter perturbation without ranking or winner selection."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from trading_bot.config.calculation import calculation_context
from trading_bot.config.models import CalculationConfig
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.identifiers import deterministic_id
from trading_bot.domain.primitives import require_finite, require_non_empty
from trading_bot.validation.models import (
    EvaluationRange,
    PartitionType,
    SensitivityEvaluation,
    SensitivityResult,
    ValidationProtocol,
)


@dataclass(frozen=True, slots=True)
class SensitivitySpec:
    parameter: str
    baseline_value: Decimal
    multipliers: tuple[Decimal, ...]
    evaluation_range: EvaluationRange
    evaluation_partition: PartitionType = PartitionType.VALIDATION
    maximum_relative_deviation: Decimal = Decimal("0.05")

    def __post_init__(self) -> None:
        require_non_empty(self.parameter, "sensitivity parameter")
        require_finite(self.baseline_value, "sensitivity baseline_value")
        if not self.multipliers or len(set(self.multipliers)) != len(self.multipliers):
            raise DomainValidationError("sensitivity multipliers must be non-empty and unique")
        if self.multipliers.count(Decimal("1")) != 1:
            raise DomainValidationError("sensitivity must contain baseline exactly once")
        if any(not value.is_finite() or value <= Decimal("0") for value in self.multipliers):
            raise DomainValidationError("sensitivity multipliers must be finite and positive")
        require_finite(self.maximum_relative_deviation, "maximum_relative_deviation")
        if self.maximum_relative_deviation < Decimal("0"):
            raise DomainValidationError("sensitivity maximum deviation must be non-negative")
        if any(
            abs(value - Decimal("1")) > self.maximum_relative_deviation
            for value in self.multipliers
        ):
            raise DomainValidationError("sensitivity perturbations must remain local")
        if self.evaluation_partition is PartitionType.TEST:
            raise DomainValidationError("final TEST cannot be used for sensitivity")


def evaluate_sensitivity(
    protocol: ValidationProtocol,
    spec: SensitivitySpec,
    calculation: CalculationConfig,
    evaluator: Callable[[Decimal], SensitivityEvaluation],
) -> tuple[SensitivityResult, ...]:
    """Evaluate every declared perturbation in order and deliberately return no winner."""
    if spec.parameter not in protocol.allowed_sensitivity_dimensions:
        raise DomainValidationError("sensitivity parameter is not allowed by protocol")
    output: list[SensitivityResult] = []
    with calculation_context(calculation):
        for multiplier in spec.multipliers:
            value = spec.baseline_value * multiplier
            evaluation = evaluator(value)
            identities_match = (
                evaluation.partition is spec.evaluation_partition
                and evaluation.partition is not PartitionType.TEST
                and evaluation.evaluation_range == spec.evaluation_range
                and evaluation.historical_versions == protocol.historical_versions
                and evaluation.strategy_version == protocol.strategy_version
                and evaluation.config_version == protocol.config_version
                and evaluation.execution_model_version == protocol.execution_model_version
                and evaluation.cost_model_version == protocol.cost_model_version
                and evaluation.funding_model_version == protocol.funding_model_version
                and evaluation.instrument_metadata_version == protocol.instrument_metadata_version
                and evaluation.metrics.minimum_sample_size
                == protocol.validation_policy.minimum_sample_size
            )
            if not identities_match:
                raise DomainValidationError("sensitivity evaluation provenance mismatch")
            output.append(
                SensitivityResult(
                    deterministic_id(
                        "sensitivity-result-v1",
                        protocol.protocol_id,
                        spec.parameter,
                        value,
                        multiplier,
                        evaluation,
                    ),
                    spec.parameter,
                    spec.baseline_value,
                    value,
                    multiplier,
                    multiplier == Decimal("1"),
                    evaluation,
                )
            )
    return tuple(output)
