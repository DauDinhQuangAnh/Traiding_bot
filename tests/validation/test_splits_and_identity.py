from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, localcontext
from itertools import pairwise

import pytest

from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.primitives import canonical_json
from trading_bot.validation.identity import (
    create_test_consumption_event_id,
    create_validation_protocol,
)
from trading_bot.validation.models import (
    EvaluationRange,
    PartitionType,
    RobustnessEvidenceRequirements,
    WalkForwardMode,
    WalkForwardSpec,
)
from trading_bot.validation.splits import (
    create_temporal_split,
    minimum_warmup_by_timeframe,
    minimum_warmup_duration,
    partition_windows,
)
from trading_bot.validation.walk_forward import generate_walk_forward_windows

from .helpers import HISTORICAL, START, evaluation_range, validation_policy, validation_run

D = Decimal


def test_chronological_split_is_deterministic_and_typed():
    first = create_temporal_split(
        evaluation_range(0, 10), evaluation_range(10, 20), evaluation_range(20, 30)
    )
    second = create_temporal_split(
        evaluation_range(0, 10), evaluation_range(10, 20), evaluation_range(20, 30)
    )

    assert first == second
    assert first.timezone == "UTC"


def test_split_identity_changes_with_boundary():
    baseline = create_temporal_split(
        evaluation_range(0, 10), evaluation_range(10, 20), evaluation_range(20, 30)
    )
    changed = create_temporal_split(
        evaluation_range(0, 9), evaluation_range(10, 20), evaluation_range(20, 30)
    )

    assert baseline.split_id != changed.split_id


def test_overlapping_split_is_rejected():
    with pytest.raises(DomainValidationError, match="TRAIN and VALIDATION"):
        create_temporal_split(
            evaluation_range(0, 11), evaluation_range(10, 20), evaluation_range(20, 30)
        )


def test_reversed_range_is_rejected():
    with pytest.raises(DomainValidationError, match="after start"):
        EvaluationRange(START + timedelta(days=1), START)


def test_purge_and_embargo_must_fit_gap():
    with pytest.raises(DomainValidationError, match="purge/embargo"):
        create_temporal_split(
            evaluation_range(0, 10),
            evaluation_range(11, 20),
            evaluation_range(21, 30),
            purge_duration=timedelta(days=1),
            embargo_duration=timedelta(hours=1),
        )


def test_warmup_is_derived_and_common_for_continuous_state(app_config):
    split = create_temporal_split(
        evaluation_range(0, 10), evaluation_range(10, 20), evaluation_range(20, 30)
    )
    warmups = minimum_warmup_by_timeframe(app_config)
    windows = partition_windows(split, app_config)

    assert minimum_warmup_duration(app_config) == max(warmups.values())
    assert tuple(window.partition for window in windows) == tuple(PartitionType)
    assert len({window.data_start for window in windows}) == 1


def test_warmup_below_derived_minimum_is_rejected(app_config):
    split = create_temporal_split(
        evaluation_range(0, 10), evaluation_range(10, 20), evaluation_range(20, 30)
    )
    with pytest.raises(DomainValidationError, match="below derived"):
        partition_windows(
            split,
            app_config,
            requested_warmup=minimum_warmup_duration(app_config) - timedelta(seconds=1),
        )


def _walk_spec(mode=WalkForwardMode.ANCHORED):
    return WalkForwardSpec(
        mode,
        START,
        START + timedelta(days=10),
        START + timedelta(days=16),
        timedelta(days=4),
        timedelta(days=2),
        timedelta(days=2),
        timedelta(days=1),
    )


def test_anchored_walk_forward_expands_training_and_keeps_oos_disjoint():
    windows = generate_walk_forward_windows(_walk_spec())

    assert len(windows) == 3
    assert all(window.training.start == START for window in windows)
    assert tuple(window.oos.start for window in windows) == tuple(
        START + timedelta(days=value) for value in (10, 12, 14)
    )
    assert all(left.oos.end <= right.oos.start for left, right in pairwise(windows))


def test_rolling_walk_forward_moves_training_window():
    windows = generate_walk_forward_windows(_walk_spec(WalkForwardMode.ROLLING))

    assert tuple(window.training.start for window in windows) == tuple(
        START + timedelta(days=value) for value in (6, 8, 10)
    )


def test_walk_forward_overlap_fails_closed():
    with pytest.raises(DomainValidationError, match="must not overlap"):
        replace(_walk_spec(), step=timedelta(days=1))


def test_protocol_identity_changes_for_strategy_cost_and_split():
    policy = validation_policy()
    kwargs = dict(
        protocol_version="v1",
        code_version="code",
        strategy_version="strategy",
        config_version="config",
        split_id="split",
        historical_versions=HISTORICAL,
        execution_model_version="execution",
        cost_model_version="cost",
        funding_model_version="funding",
        instrument_metadata_version="instrument",
        validation_policy=policy,
    )
    baseline = create_validation_protocol(**kwargs)
    changed_strategy = create_validation_protocol(**(kwargs | {"strategy_version": "strategy-2"}))
    changed_cost = create_validation_protocol(**(kwargs | {"cost_model_version": "cost-2"}))
    changed_split = create_validation_protocol(**(kwargs | {"split_id": "split-2"}))
    changed_history = create_validation_protocol(
        **(kwargs | {"historical_versions": replace(HISTORICAL, m5_data_version="m5-v2")})
    )
    changed_requirements = create_validation_protocol(
        **(
            kwargs
            | {
                "validation_policy": validation_policy(
                    requirements=RobustnessEvidenceRequirements(require_cost_stress=False)
                )
            }
        )
    )
    consumed = create_validation_protocol(**(kwargs | {"test_evaluation_count": 1}))

    assert (
        len(
            {
                baseline.protocol_id,
                changed_strategy.protocol_id,
                changed_cost.protocol_id,
                changed_split.protocol_id,
                changed_history.protocol_id,
                changed_requirements.protocol_id,
            }
        )
        == 6
    )
    assert consumed.protocol_id == baseline.protocol_id


def _policy_protocol(policy):
    return create_validation_protocol(
        protocol_version="v1",
        code_version="code",
        strategy_version="strategy",
        config_version="config",
        split_id="split",
        historical_versions=HISTORICAL,
        execution_model_version="execution",
        cost_model_version="cost",
        funding_model_version="funding",
        instrument_metadata_version="instrument",
        validation_policy=policy,
    )


def test_validation_policy_identity_is_repeatable():
    baseline = validation_policy()
    repeated = validation_policy()

    assert baseline.validation_policy_id == repeated.validation_policy_id
    assert canonical_json(baseline) == canonical_json(repeated)
    assert _policy_protocol(baseline).protocol_id == _policy_protocol(repeated).protocol_id


@pytest.mark.parametrize(
    "changed_policy",
    (
        validation_policy(policy_version="phase6-test-policy-v2"),
        validation_policy(minimum_sample_size=3),
        validation_policy(minimum_oos_trades=3),
        validation_policy(minimum_positive_window_ratio=D("0.75")),
        validation_policy(minimum_expectancy_r=D("0.5")),
        validation_policy(maximum_sensitivity_range_r=D("0.10")),
        validation_policy(requirements=RobustnessEvidenceRequirements(require_sensitivity=False)),
    ),
    ids=(
        "policy-version",
        "minimum-sample-size",
        "minimum-oos-trades",
        "positive-window-ratio",
        "minimum-expectancy",
        "sensitivity-range",
        "evidence-requirements",
    ),
)
def test_each_policy_semantic_changes_policy_and_protocol_identity(changed_policy):
    baseline = validation_policy()

    assert changed_policy.validation_policy_id != baseline.validation_policy_id
    assert _policy_protocol(changed_policy).protocol_id != _policy_protocol(baseline).protocol_id


@pytest.mark.parametrize("minimum_sample_size", (0, -1))
def test_validation_policy_rejects_non_positive_minimum_sample(minimum_sample_size):
    with pytest.raises(DomainValidationError, match="minimum_sample_size"):
        validation_policy(minimum_sample_size=minimum_sample_size)


def test_validation_policy_rejects_identity_that_does_not_match_content():
    policy = validation_policy()

    with pytest.raises(DomainValidationError, match="does not match policy content"):
        replace(policy, minimum_sample_size=policy.minimum_sample_size + 1)


def test_protocol_rejects_policy_change_without_new_protocol_identity():
    protocol = validation_run().protocol

    with pytest.raises(DomainValidationError, match="protocol_id does not match"):
        replace(
            protocol,
            validation_policy=validation_policy(minimum_expectancy_r=D("0.5")),
        )


def test_policy_identity_is_independent_of_ambient_decimal_context():
    baseline = validation_policy(minimum_expectancy_r=D("0.123456789"))

    with localcontext() as context:
        context.prec = 2
        repeated = validation_policy(minimum_expectancy_r=D("0.123456789"))

    assert repeated.validation_policy_id == baseline.validation_policy_id


def test_validation_run_identity_changes_with_frozen_policy():
    baseline = validation_run(policy=validation_policy(minimum_expectancy_r=D("0")))
    changed = validation_run(policy=validation_policy(minimum_expectancy_r=D("0.5")))

    assert baseline.protocol.protocol_id != changed.protocol.protocol_id
    assert baseline.validation_run_id != changed.validation_run_id


def test_identical_policy_protocol_and_evidence_are_canonical():
    first = validation_run()
    repeated = validation_run()

    assert first.validation_run_id == repeated.validation_run_id
    assert canonical_json(first) == canonical_json(repeated)


def test_test_consumption_event_identity_is_repeatable_and_execution_specific():
    first = create_test_consumption_event_id("protocol", "execution-1", "test-backtest")

    assert first == create_test_consumption_event_id("protocol", "execution-1", "test-backtest")
    assert first != create_test_consumption_event_id("protocol", "execution-2", "test-backtest")
