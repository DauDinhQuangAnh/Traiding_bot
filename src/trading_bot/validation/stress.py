"""Versioned cost-stress orchestration over unchanged strategy semantics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from trading_bot.backtest.models import BacktestTradeResult
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.identifiers import deterministic_id
from trading_bot.domain.primitives import require_non_empty, require_ratio
from trading_bot.validation.models import (
    CostStressResult,
    ExecutionPathFingerprint,
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
    execution_path: ExecutionPathFingerprint
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
        if self.metrics.trade_count != self.execution_path.trade_count:
            raise DomainValidationError("cost stress metrics/path trade count mismatch")


def cost_stress_model_version(
    baseline_cost_model_version: str,
    spec: CostStressSpec,
    multiplier: Decimal,
) -> str:
    """Derive the declared cost identity from the frozen baseline and stress policy."""
    require_non_empty(baseline_cost_model_version, "baseline_cost_model_version")
    if multiplier not in spec.multipliers:
        raise DomainValidationError("cost stress multiplier is not declared by the specification")
    if multiplier == Decimal("1"):
        return baseline_cost_model_version
    return deterministic_id(
        "validation-stressed-cost-model-v1",
        baseline_cost_model_version,
        spec,
        multiplier,
    )


def execution_path_fingerprint(
    trades: tuple[BacktestTradeResult, ...],
    entry_execution_ids: tuple[str, ...],
) -> ExecutionPathFingerprint:
    """Hash the supplied execution order without cost-sensitive prices or PnL."""
    if len(trades) != len(entry_execution_ids):
        raise DomainValidationError("every executed trade requires an entry execution identity")
    for entry_execution_id in entry_execution_ids:
        require_non_empty(entry_execution_id, "entry_execution_id")
    ordered_execution_identity = tuple(
        (
            trade.trade_id,
            trade.candidate_id,
            trade.approved_plan_id,
            entry_execution_id,
            trade.side,
            trade.entry_time,
            trade.exit_time,
            trade.exit_reason,
        )
        for trade, entry_execution_id in zip(trades, entry_execution_ids, strict=True)
    )
    return ExecutionPathFingerprint(
        len(trades),
        deterministic_id("validation-execution-path-v1", ordered_execution_identity),
    )


def evaluate_cost_stress(
    protocol: ValidationProtocol,
    spec: CostStressSpec,
    baseline_price_deviation_tolerance: Decimal,
    evaluator: Callable[[Decimal], CostStressEvaluation],
) -> tuple[CostStressResult, ...]:
    require_ratio(baseline_price_deviation_tolerance, "baseline_price_deviation_tolerance")
    output: list[CostStressResult] = []
    evaluations: list[tuple[Decimal, CostStressEvaluation]] = []
    for multiplier in spec.multipliers:
        evaluation = evaluator(multiplier)
        expected_cost_model_version = cost_stress_model_version(
            protocol.cost_model_version,
            spec,
            multiplier,
        )
        if evaluation.cost_model_version != expected_cost_model_version:
            if multiplier == Decimal("1"):
                raise DomainValidationError("cost stress baseline does not match frozen cost model")
            raise DomainValidationError(
                "stressed cost model does not match frozen stress specification"
            )
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
            and evaluation.metrics.minimum_sample_size
            == protocol.validation_policy.minimum_sample_size
        )
        if not identities_match:
            raise DomainValidationError("cost stress changed frozen non-cost semantics")
        evaluations.append((multiplier, evaluation))
        output.append(
            CostStressResult(
                deterministic_id(
                    "cost-stress-result-v1",
                    protocol.protocol_id,
                    spec,
                    multiplier,
                    evaluation.cost_model_version,
                    evaluation.execution_path,
                ),
                multiplier,
                evaluation.cost_model_version,
                evaluation.execution_path,
                evaluation.metrics,
            )
        )
    baseline = next(evaluation for multiplier, evaluation in evaluations if multiplier == 1)
    for multiplier, evaluation in evaluations:
        if (
            multiplier > 1
            and evaluation.execution_path == baseline.execution_path
            and not unchanged_path_cost_monotonic(
                baseline.metrics,
                evaluation.metrics,
                baseline.execution_path,
                evaluation.execution_path,
            )
        ):
            raise DomainValidationError("higher costs improved an unchanged execution path")
    return tuple(output)


def unchanged_path_cost_monotonic(
    baseline: ValidationMetrics,
    stressed: ValidationMetrics,
    baseline_path: ExecutionPathFingerprint,
    stressed_path: ExecutionPathFingerprint,
) -> bool:
    """Check accounting monotonicity only when the executed trade path is unchanged."""
    if baseline_path != stressed_path:
        raise DomainValidationError("cannot apply unchanged-path check to different trade paths")
    if (
        baseline.trade_count != baseline_path.trade_count
        or stressed.trade_count != stressed_path.trade_count
    ):
        raise DomainValidationError("execution path does not match metric trade count")
    return stressed.total_costs >= baseline.total_costs and stressed.net_pnl <= baseline.net_pnl
