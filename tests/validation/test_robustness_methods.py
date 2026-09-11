from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.primitives import canonical_json
from trading_bot.validation.benchmarks import buy_and_hold_benchmark, flat_benchmark
from trading_bot.validation.metrics import project_validation_metrics
from trading_bot.validation.models import (
    CostStressResult,
    RobustnessStatus,
    SensitivityResult,
    WalkForwardWindow,
    WalkForwardWindowResult,
)
from trading_bot.validation.robustness import RobustnessRules, classify_robustness
from trading_bot.validation.sensitivity import SensitivitySpec, evaluate_sensitivity
from trading_bot.validation.stress import (
    CostStressSpec,
    evaluate_cost_stress,
    unchanged_path_cost_monotonic,
)
from trading_bot.validation.uncertainty import BootstrapSpec, bootstrap_trade_results
from trading_bot.validation.walk_forward_metrics import summarize_walk_forward

from .helpers import CALCULATION, START, backtest_result, evaluation_range, trade, validation_run

D = Decimal


def _metrics(*pnls: str):
    return project_validation_metrics(
        backtest_result(tuple(trade(index, pnl) for index, pnl in enumerate(pnls))),
        evaluation_range(0, 1),
        minimum_sample_size=2,
        calculation=CALCULATION,
    )


def test_sensitivity_contains_baseline_once_and_never_selects_winner(app_config):
    spec = SensitivitySpec("strategy.long_threshold", D("60"), (D("0.95"), D("1"), D("1.05")))

    results = evaluate_sensitivity(
        validation_run().protocol,
        spec,
        app_config.calculation,
        lambda value: _metrics("10", str(value - D("60"))),
    )

    assert sum(result.is_baseline for result in results) == 1
    assert tuple(result.perturbed_value for result in results) == (D("57"), D("60"), D("63"))
    assert all(not hasattr(result, "selected") for result in results)


def test_sensitivity_rejects_dimension_not_allowed_by_protocol(app_config):
    spec = SensitivitySpec("risk.unknown", D("1"), (D("1"),))

    with pytest.raises(DomainValidationError, match="not allowed"):
        evaluate_sensitivity(
            validation_run().protocol,
            spec,
            app_config.calculation,
            lambda _value: _metrics("1", "-1"),
        )


def test_sensitivity_rejects_missing_or_duplicate_baseline():
    with pytest.raises(DomainValidationError, match="baseline exactly once"):
        SensitivitySpec("threshold", D("60"), (D("0.9"), D("1.1")))
    with pytest.raises(DomainValidationError, match="unique"):
        SensitivitySpec("threshold", D("60"), (D("1"), D("1")))


def test_cost_stress_versions_every_assumption():
    spec = CostStressSpec((D("1"), D("1.5"), D("2")))
    results = evaluate_cost_stress(
        "protocol", spec, lambda value: (f"cost-{value}", _metrics(str(D("20") / value), "-5"))
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


def test_unchanged_path_higher_cost_cannot_create_accounting_gain():
    baseline = _metrics("20", "-5")
    stressed = replace(baseline, net_pnl=D("10"), total_costs=baseline.total_costs + D("5"))

    assert unchanged_path_cost_monotonic(baseline, stressed)
    with pytest.raises(DomainValidationError, match="different trade paths"):
        unchanged_path_cost_monotonic(baseline, replace(stressed, trade_count=3))


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
    assert buy_hold.maximum_drawdown == D("0")


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


def test_robustness_status_separates_insufficient_fragile_mixed_and_candidate():
    rules = RobustnessRules(2, D("0.5"), D("0"), D("0.25"))
    healthy = _metrics("20", "10")
    insufficient = _metrics("10")
    fragile = replace(healthy, expectancy_r=D("-0.01"))

    assert (
        classify_robustness(insufficient, (), (), (), rules, CALCULATION)
        is RobustnessStatus.INSUFFICIENT_DATA
    )
    assert classify_robustness(fragile, (), (), (), rules, CALCULATION) is RobustnessStatus.FRAGILE
    assert classify_robustness(healthy, (), (), (), rules, CALCULATION) is RobustnessStatus.MIXED
    windows = (_window_result(healthy, net_pnl="1"), _window_result(healthy, net_pnl="-1"))
    assert (
        classify_robustness(healthy, windows, (), (), rules, CALCULATION)
        is RobustnessStatus.ROBUST_CANDIDATE
    )


def test_sensitivity_and_cost_failures_classify_as_fragile():
    rules = RobustnessRules(2, D("0.5"), D("0"), D("0.1"))
    healthy = _metrics("20", "10")
    sensitivity = (
        SensitivityResult("s1", "threshold", D("60"), D("60"), D("1"), True, healthy),
        SensitivityResult(
            "s2",
            "threshold",
            D("60"),
            D("61"),
            D("1.016"),
            False,
            replace(healthy, expectancy_r=D("-1")),
        ),
    )
    stress = (CostStressResult("c1", D("2"), "cost-2", replace(healthy, expectancy_r=D("-0.1"))),)

    assert (
        classify_robustness(healthy, (), sensitivity, (), rules, CALCULATION)
        is RobustnessStatus.FRAGILE
    )
    assert (
        classify_robustness(healthy, (), (), stress, rules, CALCULATION) is RobustnessStatus.FRAGILE
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
