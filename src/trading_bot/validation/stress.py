"""Versioned cost-stress orchestration over unchanged strategy semantics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.identifiers import deterministic_id
from trading_bot.domain.primitives import require_non_empty, require_ratio
from trading_bot.validation.models import (
    CostStressResult,
    ValidationMetrics,
    ValidationProtocol,
)


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


@dataclass(frozen=True, slots=True)
class CostStressEvaluation:
    cost_model_version: str
    strategy_version: str
    config_version: str
    execution_model_version: str
    funding_model_version: str
    instrument_metadata_version: str
    price_deviation_tolerance: Decimal
    metrics: ValidationMetrics

    def __post_init__(self) -> None:
        for name in (
            "cost_model_version",
            "strategy_version",
            "config_version",
            "execution_model_version",
            "funding_model_version",
            "instrument_metadata_version",
        ):
            require_non_empty(getattr(self, name), name)
        require_ratio(self.price_deviation_tolerance, "price_deviation_tolerance")


def evaluate_cost_stress(
    protocol: ValidationProtocol,
    spec: CostStressSpec,
    baseline_price_deviation_tolerance: Decimal,
    evaluator: Callable[[Decimal], CostStressEvaluation],
) -> tuple[CostStressResult, ...]:
    require_ratio(baseline_price_deviation_tolerance, "baseline_price_deviation_tolerance")
    output = []
    for multiplier in spec.multipliers:
        evaluation = evaluator(multiplier)
        identities_match = (
            evaluation.strategy_version == protocol.strategy_version
            and evaluation.config_version == protocol.config_version
            and evaluation.execution_model_version == protocol.execution_model_version
            and evaluation.instrument_metadata_version == protocol.instrument_metadata_version
            and (
                spec.stress_funding
                or evaluation.funding_model_version == protocol.funding_model_version
            )
            and evaluation.price_deviation_tolerance == baseline_price_deviation_tolerance
        )
        if not identities_match:
            raise DomainValidationError("cost stress changed frozen non-cost semantics")
        output.append(
            CostStressResult(
                deterministic_id(
                    "cost-stress-result-v1",
                    protocol.protocol_id,
                    spec,
                    multiplier,
                    evaluation.cost_model_version,
                ),
                multiplier,
                evaluation.cost_model_version,
                evaluation.metrics,
            )
        )
    return tuple(output)


def unchanged_path_cost_monotonic(baseline: ValidationMetrics, stressed: ValidationMetrics) -> bool:
    """Check accounting monotonicity only when the executed trade path is unchanged."""
    if baseline.trade_count != stressed.trade_count:
        raise DomainValidationError("cannot apply unchanged-path check to different trade paths")
    return stressed.total_costs >= baseline.total_costs and stressed.net_pnl <= baseline.net_pnl
