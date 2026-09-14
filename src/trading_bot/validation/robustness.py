"""Explicit, decomposable robustness classification."""

from __future__ import annotations

from decimal import Decimal

from trading_bot.config.calculation import calculation_context
from trading_bot.config.models import CalculationConfig
from trading_bot.domain.errors import DomainValidationError
from trading_bot.validation.models import (
    CostStressResult,
    RobustnessEvidenceRequirements,
    RobustnessStatus,
    SensitivityResult,
    ValidationMetrics,
    ValidationProtocol,
    WalkForwardWindowResult,
)


def classify_robustness(
    baseline: ValidationMetrics,
    windows: tuple[WalkForwardWindowResult, ...],
    sensitivity: tuple[SensitivityResult, ...],
    stress: tuple[CostStressResult, ...],
    protocol: ValidationProtocol,
    calculation: CalculationConfig,
) -> RobustnessStatus:
    policy = protocol.validation_policy
    rules = policy.robustness_rules
    evidence_metrics = (
        baseline,
        *(item.result.metrics for item in windows),
        *(item.metrics for item in sensitivity),
        *(item.metrics for item in stress),
    )
    if any(
        metrics.minimum_sample_size != policy.minimum_sample_size for metrics in evidence_metrics
    ):
        raise DomainValidationError("robustness evidence does not match frozen sample policy")
    if (
        baseline.trade_count < rules.minimum_oos_trades
        or baseline.insufficient_sample
        or baseline.expectancy_r is None
    ):
        return RobustnessStatus.INSUFFICIENT_DATA
    if _missing_required_evidence(
        windows,
        sensitivity,
        stress,
        policy.robustness_evidence_requirements,
    ):
        return RobustnessStatus.MIXED
    expectancy_values = tuple(
        result.metrics.expectancy_r
        for result in sensitivity
        if result.metrics.expectancy_r is not None
    )
    sensitivity_fragile = any(result.metrics.expectancy_r is None for result in sensitivity) or (
        bool(expectancy_values)
        and max(expectancy_values) - min(expectancy_values) > rules.maximum_sensitivity_range_r
    )
    cost_fragile = any(
        result.multiplier > Decimal("1")
        and (
            result.metrics.expectancy_r is None
            or result.metrics.expectancy_r < rules.minimum_expectancy_r
        )
        for result in stress
    )
    if baseline.expectancy_r < rules.minimum_expectancy_r or sensitivity_fragile or cost_fragile:
        return RobustnessStatus.FRAGILE
    if windows:
        positive = sum(result.result.metrics.net_pnl > Decimal("0") for result in windows)
        with calculation_context(calculation):
            positive_ratio = Decimal(positive) / Decimal(len(windows))
        if positive_ratio < rules.minimum_positive_window_ratio:
            return RobustnessStatus.MIXED
    return RobustnessStatus.ROBUST_CANDIDATE


def _missing_required_evidence(
    windows: tuple[WalkForwardWindowResult, ...],
    sensitivity: tuple[SensitivityResult, ...],
    stress: tuple[CostStressResult, ...],
    requirements: RobustnessEvidenceRequirements,
) -> bool:
    sensitivity_complete = any(item.is_baseline for item in sensitivity) and any(
        not item.is_baseline for item in sensitivity
    )
    stress_complete = any(item.multiplier == Decimal("1") for item in stress) and any(
        item.multiplier > Decimal("1") for item in stress
    )
    return (
        (requirements.require_walk_forward and not windows)
        or (
            requirements.require_walk_forward
            and any(item.result.metrics.insufficient_sample for item in windows)
        )
        or (requirements.require_sensitivity and not sensitivity_complete)
        or (
            requirements.require_sensitivity
            and any(item.metrics.insufficient_sample for item in sensitivity)
        )
        or (requirements.require_cost_stress and not stress_complete)
        or (
            requirements.require_cost_stress
            and any(item.metrics.insufficient_sample for item in stress)
        )
    )
