"""Versioned cost-stress orchestration over unchanged strategy semantics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.identifiers import deterministic_id
from trading_bot.validation.models import CostStressResult, ValidationMetrics


@dataclass(frozen=True, slots=True)
class CostStressSpec:
    multipliers: tuple[Decimal, ...]
    stress_spread: bool = True
    stress_slippage: bool = True
    stress_fees: bool = True
    stress_funding: bool = False

    def __post_init__(self) -> None:
        if not self.multipliers or len(set(self.multipliers)) != len(self.multipliers):
            raise DomainValidationError("cost stress multipliers must be non-empty and unique")
        if self.multipliers.count(Decimal("1")) != 1:
            raise DomainValidationError("cost stress must contain baseline exactly once")
        if any(not value.is_finite() or value < Decimal("1") for value in self.multipliers):
            raise DomainValidationError("cost stress multipliers must be finite and >= 1")
        if not any(
            (self.stress_spread, self.stress_slippage, self.stress_fees, self.stress_funding)
        ):
            raise DomainValidationError("cost stress requires at least one stressed dimension")


def evaluate_cost_stress(
    protocol_id: str,
    spec: CostStressSpec,
    evaluator: Callable[[Decimal], tuple[str, ValidationMetrics]],
) -> tuple[CostStressResult, ...]:
    output = []
    for multiplier in spec.multipliers:
        cost_model_version, metrics = evaluator(multiplier)
        output.append(
            CostStressResult(
                deterministic_id(
                    "cost-stress-result-v1", protocol_id, spec, multiplier, cost_model_version
                ),
                multiplier,
                cost_model_version,
                metrics,
            )
        )
    return tuple(output)


def unchanged_path_cost_monotonic(baseline: ValidationMetrics, stressed: ValidationMetrics) -> bool:
    """Check accounting monotonicity only when the executed trade path is unchanged."""
    if baseline.trade_count != stressed.trade_count:
        raise DomainValidationError("cannot apply unchanged-path check to different trade paths")
    return stressed.total_costs >= baseline.total_costs and stressed.net_pnl <= baseline.net_pnl
