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
from trading_bot.validation.models import SensitivityResult, ValidationMetrics, ValidationProtocol


@dataclass(frozen=True, slots=True)
class SensitivitySpec:
    parameter: str
    baseline_value: Decimal
    multipliers: tuple[Decimal, ...]

    def __post_init__(self) -> None:
        require_non_empty(self.parameter, "sensitivity parameter")
        require_finite(self.baseline_value, "sensitivity baseline_value")
        if not self.multipliers or len(set(self.multipliers)) != len(self.multipliers):
            raise DomainValidationError("sensitivity multipliers must be non-empty and unique")
        if self.multipliers.count(Decimal("1")) != 1:
            raise DomainValidationError("sensitivity must contain baseline exactly once")
        if any(not value.is_finite() or value <= Decimal("0") for value in self.multipliers):
            raise DomainValidationError("sensitivity multipliers must be finite and positive")


def evaluate_sensitivity(
    protocol: ValidationProtocol,
    spec: SensitivitySpec,
    calculation: CalculationConfig,
    evaluator: Callable[[Decimal], ValidationMetrics],
) -> tuple[SensitivityResult, ...]:
    """Evaluate every declared perturbation in order and deliberately return no winner."""
    if spec.parameter not in protocol.allowed_sensitivity_dimensions:
        raise DomainValidationError("sensitivity parameter is not allowed by protocol")
    output: list[SensitivityResult] = []
    with calculation_context(calculation):
        for multiplier in spec.multipliers:
            value = spec.baseline_value * multiplier
            metrics = evaluator(value)
            output.append(
                SensitivityResult(
                    deterministic_id(
                        "sensitivity-result-v1",
                        protocol.protocol_id,
                        spec.parameter,
                        value,
                        multiplier,
                    ),
                    spec.parameter,
                    spec.baseline_value,
                    value,
                    multiplier,
                    multiplier == Decimal("1"),
                    metrics,
                )
            )
    return tuple(output)
