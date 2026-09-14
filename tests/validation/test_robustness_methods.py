from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from trading_bot.domain.enums import ExitReason
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.primitives import canonical_json
from trading_bot.validation.benchmarks import buy_and_hold_benchmark, flat_benchmark
from trading_bot.validation.identity import create_validation_protocol
from trading_bot.validation.metrics import project_validation_metrics
from trading_bot.validation.models import (
    CostStressResult,
    PartitionType,
    RobustnessEvidenceRequirements,
    RobustnessStatus,
    SensitivityEvaluation,
    SensitivityResult,
    WalkForwardWindow,
    WalkForwardWindowResult,
)
from trading_bot.validation.robustness import RobustnessRules, classify_robustness
from trading_bot.validation.sensitivity import SensitivitySpec, evaluate_sensitivity
from trading_bot.validation.stress import (
    CostStressEvaluation,
    CostStressSpec,
    evaluate_cost_stress,
    execution_path_fingerprint,
    unchanged_path_cost_monotonic,
)
from trading_bot.validation.uncertainty import BootstrapSpec, bootstrap_trade_results
from trading_bot.validation.walk_forward_metrics import summarize_walk_forward

from .helpers import (
    CALCULATION,
    HISTORICAL,
    START,
    backtest_result,
    evaluation_range,
    trade,
    validation_run,
)

D = Decimal


def _metrics(*pnls: str):
    return project_validation_metrics(
        backtest_result(tuple(trade(index, pnl) for index, pnl in enumerate(pnls))),
        evaluation_range(0, 1),
        minimum_sample_size=2,
        calculation=CALCULATION,
    )


def _sensitivity_evaluation(protocol, metrics, **changes):
    evaluation = SensitivityEvaluation(
        PartitionType.VALIDATION,
        evaluation_range(2, 4),
        "sensitivity-backtest-v1",
        HISTORICAL,
        protocol.strategy_version,
        protocol.config_version,
        protocol.execution_model_version,
        protocol.cost_model_version,
        protocol.funding_model_version,
        protocol.instrument_metadata_version,
        metrics,
    )
    return replace(evaluation, **changes)


def _execution_path(*indexes: int):
    return execution_path_fingerprint(
        tuple(trade(index, "10") for index in indexes),
        tuple(f"entry-order-{index}" for index in indexes),
    )


def test_sensitivity_contains_baseline_once_and_never_selects_winner(app_config):
    protocol = validation_run().protocol
    spec = SensitivitySpec(
        "strategy.long_threshold",
        D("60"),
        (D("0.95"), D("1"), D("1.05")),
        evaluation_range(2, 4),
    )

    results = evaluate_sensitivity(
        protocol,
        spec,
        app_config.calculation,
        lambda value: _sensitivity_evaluation(protocol, _metrics("10", str(value - D("60")))),
    )

    assert sum(result.is_baseline for result in results) == 1
    assert tuple(result.perturbed_value for result in results) == (D("57"), D("60"), D("63"))
    assert all(result.evaluation_partition is PartitionType.VALIDATION for result in results)
    assert all(not hasattr(result, "selected") for result in results)


def test_sensitivity_rejects_dimension_not_allowed_by_protocol(app_config):
    protocol = validation_run().protocol
    spec = SensitivitySpec("risk.unknown", D("1"), (D("1"),), evaluation_range(2, 4))

    with pytest.raises(DomainValidationError, match="not allowed"):
        evaluate_sensitivity(
            protocol,
            spec,
            app_config.calculation,
            lambda _value: _sensitivity_evaluation(protocol, _metrics("1", "-1")),
        )


def test_sensitivity_rejects_missing_or_duplicate_baseline():
    with pytest.raises(DomainValidationError, match="baseline exactly once"):
        SensitivitySpec("threshold", D("60"), (D("0.9"), D("1.1")), evaluation_range(2, 4))
    with pytest.raises(DomainValidationError, match="unique"):
        SensitivitySpec("threshold", D("60"), (D("1"), D("1")), evaluation_range(2, 4))


def test_sensitivity_rejects_final_test_and_non_local_perturbations():
    with pytest.raises(DomainValidationError, match="final TEST"):
        SensitivitySpec(
            "threshold",
            D("60"),
            (D("0.95"), D("1"), D("1.05")),
            evaluation_range(2, 4),
            evaluation_partition=PartitionType.TEST,
        )
    with pytest.raises(DomainValidationError, match="remain local"):
        SensitivitySpec(
            "threshold",
            D("60"),
            (D("0.9"), D("1"), D("1.1")),
            evaluation_range(2, 4),
        )


@pytest.mark.parametrize(
    "change",
    (
        {"partition": PartitionType.TEST},
        {"partition": PartitionType.TRAIN},
        {"evaluation_range": evaluation_range(0, 2)},
        {"historical_versions": replace(HISTORICAL, m5_data_version="other-m5")},
        {"strategy_version": "other-strategy"},
        {"config_version": "other-config"},
        {"execution_model_version": "other-execution"},
        {"cost_model_version": "other-cost"},
        {"funding_model_version": "other-funding"},
        {"instrument_metadata_version": "other-instrument"},
    ),
)
def test_sensitivity_provenance_mismatch_fails_closed(app_config, change):
    protocol = validation_run().protocol
    spec = SensitivitySpec(
        "strategy.long_threshold",
        D("60"),
        (D("1"),),
        evaluation_range(2, 4),
    )

    with pytest.raises(DomainValidationError, match="provenance mismatch"):
        evaluate_sensitivity(
            protocol,
            spec,
            app_config.calculation,
            lambda _value: _sensitivity_evaluation(protocol, _metrics("10", "-5"), **change),
        )


def test_sensitivity_provenance_is_canonical_and_repeatable(app_config):
    protocol = validation_run().protocol
    spec = SensitivitySpec(
        "strategy.long_threshold",
        D("60"),
        (D("0.95"), D("1"), D("1.05")),
        evaluation_range(2, 4),
    )

    def evaluate(_value):
        return _sensitivity_evaluation(protocol, _metrics("10", "-5"))

    first = evaluate_sensitivity(protocol, spec, app_config.calculation, evaluate)
    repeated = evaluate_sensitivity(protocol, spec, app_config.calculation, evaluate)

    assert canonical_json(first) == canonical_json(repeated)
    assert first[0].evaluation.evaluation_range == spec.evaluation_range

    different_backtest = evaluate_sensitivity(
        protocol,
        spec,
        app_config.calculation,
        lambda _value: _sensitivity_evaluation(
            protocol, _metrics("10", "-5"), backtest_run_id="sensitivity-backtest-v2"
        ),
    )
    assert first[0].sensitivity_id != different_backtest[0].sensitivity_id


def test_cost_stress_versions_every_assumption():
    spec = CostStressSpec((D("1"), D("1.5"), D("2")))
    protocol = validation_run().protocol

    def evaluate(value):
        return CostStressEvaluation(
            f"cost-{value}",
            protocol.strategy_version,
            protocol.config_version,
            protocol.execution_model_version,
            protocol.funding_model_version,
            protocol.instrument_metadata_version,
            D("0.01"),
            _execution_path(0, 1),
            _metrics(str(D("20") / value), "-5"),
        )

    results = evaluate_cost_stress(
        protocol,
        spec,
        D("0.01"),
        evaluate,
    )

    assert tuple(result.multiplier for result in results) == spec.multipliers
    assert len({result.stressed_cost_model_version for result in results}) == 3


def test_cost_stress_invalid_specs_fail_closed():
    with pytest.raises(DomainValidationError, match="non-empty and unique"):
        CostStressSpec(())
    with pytest.raises(DomainValidationError, match="baseline exactly once"):
        CostStressSpec((D("1.5"), D("2")))
    with pytest.raises(DomainValidationError, match="at least one stressed dimension"):
        CostStressSpec(
            (D("1"),),
            stress_spread=False,
            stress_slippage=False,
            stress_fees=False,
            stress_funding=False,
        )


def test_cost_stress_rejects_non_cost_semantic_changes():
    protocol = validation_run().protocol
    spec = CostStressSpec((D("1"), D("2")))

    def evaluate(multiplier):
        return CostStressEvaluation(
            f"cost-{multiplier}",
            "mutated-strategy",
            protocol.config_version,
            protocol.execution_model_version,
            protocol.funding_model_version,
            protocol.instrument_metadata_version,
            D("0.01"),
            _execution_path(0, 1),
            _metrics("10", "-5"),
        )

    with pytest.raises(DomainValidationError, match="non-cost semantics"):
        evaluate_cost_stress(protocol, spec, D("0.01"), evaluate)


def test_unchanged_path_higher_cost_cannot_create_accounting_gain():
    baseline = _metrics("20", "-5")
    stressed = replace(baseline, net_pnl=D("10"), total_costs=baseline.total_costs + D("5"))
    path = _execution_path(0, 1)

    assert unchanged_path_cost_monotonic(baseline, stressed, path, path)
    with pytest.raises(DomainValidationError, match="different trade paths"):
        unchanged_path_cost_monotonic(baseline, stressed, path, _execution_path(2, 3))


def test_unchanged_path_cost_property_rejects_accounting_improvements():
    baseline = _metrics("20", "-5")
    path = _execution_path(0, 1)

    assert not unchanged_path_cost_monotonic(
        baseline,
        replace(baseline, net_pnl=baseline.net_pnl + D("1"), total_costs=baseline.total_costs),
        path,
        path,
    )
    assert not unchanged_path_cost_monotonic(
        baseline,
        replace(baseline, total_costs=baseline.total_costs - D("0.1")),
        path,
        path,
    )
    with pytest.raises(DomainValidationError, match="different trade paths"):
        unchanged_path_cost_monotonic(
            baseline,
            replace(baseline, trade_count=3),
            path,
            _execution_path(0, 1, 2),
        )


def test_execution_path_fingerprint_uses_ordered_execution_identity():
    first = trade(0, "10")
    second = trade(1, "-5")
    entry_executions = ("entry-order-0", "entry-order-1")
    baseline = execution_path_fingerprint((first, second), entry_executions)

    assert baseline == execution_path_fingerprint((first, second), entry_executions)
    assert baseline != execution_path_fingerprint(
        (trade(2, "10"), trade(3, "-5")), ("entry-order-2", "entry-order-3")
    )
    assert baseline != execution_path_fingerprint(
        (replace(first, entry_time=first.entry_time + timedelta(minutes=5)), second),
        entry_executions,
    )
    assert baseline != execution_path_fingerprint(
        (replace(first, exit_time=first.exit_time + timedelta(minutes=5)), second),
        entry_executions,
    )
    assert baseline != execution_path_fingerprint(
        (replace(first, exit_reason=ExitReason.BACKTEST_END), second), entry_executions
    )
    assert baseline != execution_path_fingerprint((first, second), ("other-entry", "entry-order-1"))
    assert baseline != execution_path_fingerprint(
        (second, first), tuple(reversed(entry_executions))
    )


def test_execution_path_requires_complete_entry_execution_identity():
    with pytest.raises(DomainValidationError, match="every executed trade"):
        execution_path_fingerprint((trade(0, "10"),), ())
    with pytest.raises(DomainValidationError, match="entry_execution_id"):
        execution_path_fingerprint((trade(0, "10"),), ("",))


def test_cost_evaluation_and_monotonicity_bind_metric_trade_count():
    protocol = validation_run().protocol
    with pytest.raises(DomainValidationError, match="metrics/path trade count"):
        CostStressEvaluation(
            "cost",
            protocol.strategy_version,
            protocol.config_version,
            protocol.execution_model_version,
            protocol.funding_model_version,
            protocol.instrument_metadata_version,
            D("0.01"),
            _execution_path(0),
            _metrics("10", "-5"),
        )

    path = _execution_path(0, 1)
    with pytest.raises(DomainValidationError, match="does not match metric"):
        unchanged_path_cost_monotonic(
            _metrics("10", "-5"),
            replace(_metrics("10", "-5"), trade_count=3),
            path,
            path,
        )


@pytest.mark.parametrize("violation", ("higher-pnl", "lower-cost"))
def test_cost_stress_enforces_monotonicity_for_identical_paths(violation):
    protocol = validation_run().protocol
    baseline = _metrics("20", "-5")
    path = _execution_path(0, 1)

    def evaluate(multiplier):
        metrics = baseline
        if multiplier > 1 and violation == "higher-pnl":
            metrics = replace(baseline, net_pnl=baseline.net_pnl + D("1"))
        elif multiplier > 1:
            metrics = replace(baseline, total_costs=baseline.total_costs - D("0.1"))
        return CostStressEvaluation(
            f"cost-{multiplier}",
            protocol.strategy_version,
            protocol.config_version,
            protocol.execution_model_version,
            protocol.funding_model_version,
            protocol.instrument_metadata_version,
            D("0.01"),
            path,
            metrics,
        )

    with pytest.raises(DomainValidationError, match="higher costs improved"):
        evaluate_cost_stress(protocol, CostStressSpec((D("1"), D("2"))), D("0.01"), evaluate)


def test_cost_stress_does_not_apply_monotonicity_to_changed_path_with_same_count():
    protocol = validation_run().protocol
    baseline = _metrics("20", "-5")

    def evaluate(multiplier):
        return CostStressEvaluation(
            f"cost-{multiplier}",
            protocol.strategy_version,
            protocol.config_version,
            protocol.execution_model_version,
            protocol.funding_model_version,
            protocol.instrument_metadata_version,
            D("0.01"),
            _execution_path(0, 1) if multiplier == 1 else _execution_path(2, 3),
            baseline if multiplier == 1 else replace(baseline, net_pnl=baseline.net_pnl + D("1")),
        )

    results = evaluate_cost_stress(protocol, CostStressSpec((D("1"), D("2"))), D("0.01"), evaluate)

    assert results[0].execution_path != results[1].execution_path


def test_seeded_bootstrap_is_exactly_reproducible_and_seeded_in_identity(app_config):
    spec = BootstrapSpec(seed=42, iterations=100, minimum_trades=2)
    r_values = (D("1"), D("-0.5"), D("0.25"), D("2"))
    pnls = (D("100"), D("-50"), D("25"), D("200"))

    first = bootstrap_trade_results("protocol", r_values, pnls, spec, app_config.calculation)
    repeated = bootstrap_trade_results("protocol", r_values, pnls, spec, app_config.calculation)
    changed = bootstrap_trade_results(
        "protocol", r_values, pnls, replace(spec, seed=43), app_config.calculation
    )

    assert canonical_json(first) == canonical_json(repeated)
    assert first.bootstrap_id != changed.bootstrap_id
    assert first.expectancy_r_median is not None
    assert first.profit_factor_median is not None
    assert changed.expectancy_r_median is not None


def test_bootstrap_is_unavailable_for_insufficient_sample(app_config):
    result = bootstrap_trade_results(
        "protocol",
        (D("1"),),
        (D("10"),),
        BootstrapSpec(1, 10, 2),
        app_config.calculation,
    )

    assert result.expectancy_r_median is None
    assert result.net_pnl_median is None
    assert result.profit_factor_median is None


def test_flat_and_buy_hold_benchmarks_use_same_oos_range_and_costs(app_config):
    evaluation = evaluation_range(0, 1)
    marks = ((START, D("100")), (START + timedelta(hours=1), D("120")))

    flat = flat_benchmark("protocol", evaluation)
    buy_hold = buy_and_hold_benchmark(
        "protocol", evaluation, marks, D("1000"), D("0.01"), D("0.01"), app_config.calculation
    )

    assert flat.net_pnl == D("0") and flat.evaluation == evaluation
    assert buy_hold.net_pnl == D("178")
    assert buy_hold.return_ratio == D("0.178")
    assert buy_hold.total_costs == D("22")
    assert buy_hold.maximum_drawdown == D("12")


def test_buy_hold_reports_drawdown_and_rejects_invalid_marks(app_config):
    evaluation = evaluation_range(0, 1)
    marks = (
        (START, D("100")),
        (START + timedelta(hours=1), D("80")),
        (START + timedelta(hours=2), D("120")),
    )

    result = buy_and_hold_benchmark(
        "protocol", evaluation, marks, D("1000"), D("0"), D("0"), app_config.calculation
    )

    assert result.maximum_drawdown == D("200")
    assert result.maximum_drawdown_ratio == D("0.2")
    with pytest.raises(DomainValidationError, match="ordered OOS marks"):
        buy_and_hold_benchmark(
            "protocol",
            evaluation,
            tuple(reversed(marks)),
            D("1000"),
            D("0"),
            D("0"),
            app_config.calculation,
        )
    with pytest.raises(DomainValidationError, match="finite and positive"):
        buy_and_hold_benchmark(
            "protocol",
            evaluation,
            ((START, D("100")), (START + timedelta(hours=1), D("0"))),
            D("1000"),
            D("0"),
            D("0"),
            app_config.calculation,
        )


def _window_result(metrics, *, net_pnl: str | None = None):
    run = validation_run()
    partition = run.partitions[2]
    oos = partition.window.evaluation
    window = WalkForwardWindow(
        f"window-{metrics.net_pnl}-{net_pnl}",
        0,
        evaluation_range(0, 2),
        oos,
        START - timedelta(days=1),
    )
    result = replace(
        partition,
        metrics=metrics if net_pnl is None else replace(metrics, net_pnl=D(net_pnl)),
    )
    return WalkForwardWindowResult(window, result)


def _sensitivity_results(metrics, *, changed_metrics=None):
    protocol = validation_run().protocol
    baseline_evaluation = _sensitivity_evaluation(protocol, metrics)
    changed_evaluation = _sensitivity_evaluation(
        protocol, changed_metrics if changed_metrics is not None else metrics
    )
    return (
        SensitivityResult("s1", "threshold", D("60"), D("60"), D("1"), True, baseline_evaluation),
        SensitivityResult(
            "s2", "threshold", D("60"), D("63"), D("1.05"), False, changed_evaluation
        ),
    )


def _stress_results(metrics, *, changed_metrics=None):
    path = _execution_path(0, 1)
    stressed_metrics = changed_metrics if changed_metrics is not None else metrics
    return (
        CostStressResult("c1", D("1"), "cost-1", path, metrics),
        CostStressResult("c2", D("2"), "cost-2", path, stressed_metrics),
    )


def test_robustness_requires_complete_multidimensional_evidence():
    rules = RobustnessRules(2, D("0.5"), D("0"), D("0.25"))
    protocol = validation_run().protocol
    healthy = _metrics("20", "10")
    insufficient = _metrics("10")
    windows = (_window_result(healthy, net_pnl="1"), _window_result(healthy, net_pnl="-1"))
    sensitivity = _sensitivity_results(healthy)
    stress = _stress_results(healthy)

    assert (
        classify_robustness(insufficient, (), (), (), protocol, rules, CALCULATION)
        is RobustnessStatus.INSUFFICIENT_DATA
    )
    assert (
        classify_robustness(healthy, windows, (), stress, protocol, rules, CALCULATION)
        is RobustnessStatus.MIXED
    )
    assert (
        classify_robustness(healthy, windows, sensitivity, (), protocol, rules, CALCULATION)
        is RobustnessStatus.MIXED
    )
    assert (
        classify_robustness(healthy, (), sensitivity, stress, protocol, rules, CALCULATION)
        is RobustnessStatus.MIXED
    )
    insufficient_window = (_window_result(_metrics("10"), net_pnl="1"),)
    assert (
        classify_robustness(
            healthy,
            insufficient_window,
            sensitivity,
            stress,
            protocol,
            rules,
            CALCULATION,
        )
        is RobustnessStatus.MIXED
    )
    assert (
        classify_robustness(healthy, windows, sensitivity, stress, protocol, rules, CALCULATION)
        is RobustnessStatus.ROBUST_CANDIDATE
    )


def test_robustness_rejects_weak_walk_forward_and_versions_optional_requirements():
    healthy = _metrics("20", "10")
    sensitivity = _sensitivity_results(healthy)
    stress = _stress_results(healthy)
    strict_protocol = validation_run().protocol
    weak_windows = (
        _window_result(healthy, net_pnl="-1"),
        _window_result(healthy, net_pnl="-2"),
    )
    rules = RobustnessRules(2, D("0.5"), D("0"), D("0.25"))

    assert (
        classify_robustness(
            healthy,
            weak_windows,
            sensitivity,
            stress,
            strict_protocol,
            rules,
            CALCULATION,
        )
        is RobustnessStatus.MIXED
    )
    optional_walk_forward = create_validation_protocol(
        protocol_version=strict_protocol.protocol_version,
        code_version=strict_protocol.code_version,
        strategy_version=strict_protocol.strategy_version,
        config_version=strict_protocol.config_version,
        split_id=strict_protocol.split_id,
        historical_versions=strict_protocol.historical_versions,
        execution_model_version=strict_protocol.execution_model_version,
        cost_model_version=strict_protocol.cost_model_version,
        funding_model_version=strict_protocol.funding_model_version,
        instrument_metadata_version=strict_protocol.instrument_metadata_version,
        robustness_evidence_requirements=RobustnessEvidenceRequirements(require_walk_forward=False),
        allowed_sensitivity_dimensions=strict_protocol.allowed_sensitivity_dimensions,
    )
    assert (
        classify_robustness(
            healthy,
            (),
            sensitivity,
            stress,
            optional_walk_forward,
            rules,
            CALCULATION,
        )
        is RobustnessStatus.ROBUST_CANDIDATE
    )


def test_robustness_rules_reject_invalid_thresholds():
    with pytest.raises(DomainValidationError, match="minimum_oos_trades"):
        RobustnessRules(0, D("0.5"), D("0"), D("0.1"))
    with pytest.raises(DomainValidationError, match="maximum_sensitivity"):
        RobustnessRules(2, D("0.5"), D("0"), D("-0.1"))


def test_sensitivity_and_cost_failures_classify_as_fragile():
    rules = RobustnessRules(2, D("0.5"), D("0"), D("0.1"))
    protocol = validation_run().protocol
    healthy = _metrics("20", "10")
    windows = (_window_result(healthy, net_pnl="1"),)
    sensitivity = _sensitivity_results(
        healthy, changed_metrics=replace(healthy, expectancy_r=D("-1"))
    )
    stress = _stress_results(healthy, changed_metrics=replace(healthy, expectancy_r=D("-0.1")))
    healthy_sensitivity = _sensitivity_results(healthy)
    healthy_stress = _stress_results(healthy)

    assert (
        classify_robustness(
            healthy,
            windows,
            sensitivity,
            healthy_stress,
            protocol,
            rules,
            CALCULATION,
        )
        is RobustnessStatus.FRAGILE
    )
    assert (
        classify_robustness(
            healthy,
            windows,
            healthy_sensitivity,
            stress,
            protocol,
            rules,
            CALCULATION,
        )
        is RobustnessStatus.FRAGILE
    )
    assert (
        classify_robustness(
            replace(healthy, expectancy_r=D("-0.1")),
            windows,
            healthy_sensitivity,
            healthy_stress,
            protocol,
            rules,
            CALCULATION,
        )
        is RobustnessStatus.FRAGILE
    )


def test_walk_forward_aggregation_weights_expectancy_and_aggregates_raw_profit():
    results = (
        _window_result(_metrics("200")),
        _window_result(_metrics("-100")),
        _window_result(_metrics("100")),
    )

    summary = summarize_walk_forward(results, CALCULATION)

    assert summary.positive_windows == 2
    assert summary.negative_windows == 1
    assert summary.positive_window_ratio == D("0.6666666666666666666666666666666667")
    assert summary.median_window_expectancy_r == D("1")
    assert summary.weighted_expectancy_r == D("0.6666666666666666666666666666666667")
    assert summary.aggregate_profit_factor == D("3")


def test_walk_forward_weighted_expectancy_excludes_only_undefined_samples():
    defined = _metrics("20", "10")
    undefined = replace(_metrics(), trade_count=7, expectancy_r=None)

    summary = summarize_walk_forward(
        (_window_result(defined), _window_result(undefined)), CALCULATION
    )

    assert summary.weighted_expectancy_r == defined.expectancy_r
