"""Content-derived identities for PHASE 6 artifacts."""

from __future__ import annotations

from dataclasses import replace

from trading_bot.domain.identifiers import deterministic_id
from trading_bot.historical.models import HistoricalVersionSet
from trading_bot.validation.models import (
    PartitionType,
    PartitionWindow,
    RobustnessEvidenceRequirements,
    TemporalSplitSpec,
    ValidationProtocol,
)

_DEFAULT_ROBUSTNESS_EVIDENCE_REQUIREMENTS = RobustnessEvidenceRequirements()


def create_validation_protocol(
    *,
    protocol_version: str,
    code_version: str,
    strategy_version: str,
    config_version: str,
    split_id: str,
    historical_versions: HistoricalVersionSet,
    execution_model_version: str,
    cost_model_version: str,
    funding_model_version: str,
    instrument_metadata_version: str,
    robustness_evidence_requirements: RobustnessEvidenceRequirements = (
        _DEFAULT_ROBUSTNESS_EVIDENCE_REQUIREMENTS
    ),
    allowed_sensitivity_dimensions: tuple[str, ...] = (),
    test_locked: bool = True,
    test_evaluation_count: int = 0,
) -> ValidationProtocol:
    from trading_bot.validation.models import StateContinuityPolicy

    state_policy = StateContinuityPolicy.CONTINUOUS_CHRONOLOGICAL
    identifier = deterministic_id(
        "validation-protocol-v1",
        protocol_version,
        code_version,
        strategy_version,
        config_version,
        split_id,
        historical_versions,
        execution_model_version,
        cost_model_version,
        funding_model_version,
        instrument_metadata_version,
        robustness_evidence_requirements,
        allowed_sensitivity_dimensions,
        state_policy,
        test_locked,
    )
    return ValidationProtocol(
        identifier,
        protocol_version,
        code_version,
        strategy_version,
        config_version,
        split_id,
        historical_versions,
        execution_model_version,
        cost_model_version,
        funding_model_version,
        instrument_metadata_version,
        robustness_evidence_requirements,
        allowed_sensitivity_dimensions,
        state_policy,
        test_locked,
        test_evaluation_count,
    )


def partition_result_id(
    protocol_id: str,
    partition: PartitionType,
    window: PartitionWindow,
    backtest_run_id: str,
) -> str:
    return deterministic_id(
        "validation-partition-result-v1",
        protocol_id,
        partition,
        window,
        backtest_run_id,
    )


def validation_run_id(
    protocol: ValidationProtocol,
    test_consumption_event_id: str,
    split: TemporalSplitSpec,
    historical_versions: HistoricalVersionSet,
    walk_forward_spec: object | None,
    sensitivity_spec: object | None,
    stress_spec: object | None,
    bootstrap_spec: object | None,
    benchmark_spec: object | None,
) -> str:
    return deterministic_id(
        "validation-run-v1",
        replace(protocol, test_evaluation_count=0),
        test_consumption_event_id,
        split,
        historical_versions,
        walk_forward_spec,
        sensitivity_spec,
        stress_spec,
        bootstrap_spec,
        benchmark_spec,
    )


def create_test_consumption_event_id(
    protocol_id: str,
    test_execution_id: str,
    test_backtest_run_id: str,
) -> str:
    return deterministic_id(
        "validation-test-consumption-event-v1",
        protocol_id,
        test_execution_id,
        test_backtest_run_id,
    )
