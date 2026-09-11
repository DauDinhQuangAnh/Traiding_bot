from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, ROUND_UP, Decimal, InvalidOperation, localcontext
from typing import cast

import pytest

from trading_bot.backtest.engine import BacktestEngine
from trading_bot.backtest.execution import (
    EntryExecutionResult,
    create_entry_order,
    try_fill_entry,
)
from trading_bot.backtest.funding import FixedFundingRateProvider, FundingRateEvent
from trading_bot.backtest.models import BacktestResult
from trading_bot.backtest.versions import execution_model_version
from trading_bot.domain.enums import (
    BacktestEventType,
    BacktestStatus,
    BacktestWarning,
    EntryModel,
    FundingMode,
    OrderStatus,
    ReasonCode,
    TradeSide,
)
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.primitives import canonical_json
from trading_bot.domain.value_objects import Target
from trading_bot.infrastructure.sqlite_backtest import SQLiteBacktestRepository

from .helpers import approved_plan, candidate, candle, engine_inputs, evaluation

D = Decimal
FUNDING_RATE = D("0.001")


def _attempt(
    app_config,
    *,
    opening: str = "100",
    side: TradeSide = TradeSide.LONG,
    plan_change: dict[str, object] | None = None,
    current_notional: str = "0",
    available_margin: str = "10000",
) -> EntryExecutionResult:
    start = datetime(2026, 1, 1, 10, 15, tzinfo=UTC)
    spec, configured, instrument, costs, _ = engine_inputs(
        app_config, start, start + timedelta(minutes=5)
    )
    trade = candidate(start, spec.versions, costs, side=side, identity=f"direct-{side}")
    plan = approved_plan(trade, start)
    if plan_change:
        plan = replace(plan, **plan_change)
    order = create_entry_order(trade, plan, start)
    return try_fill_entry(
        order,
        trade,
        plan,
        candle(start, opening, "120", "80", opening),
        instrument,
        configured.backtest,
        configured.execution,
        configured.risk,
        costs,
        configured.calculation,
        current_notional=D(current_notional),
        available_margin=D(available_margin),
        account_equity=configured.backtest.initial_equity,
    )


def _fixed_funding_engine(app_config, start: datetime, bars, rate: str, evaluations):
    backtest = replace(
        app_config.backtest,
        funding_mode=FundingMode.FIXED_ASSUMPTION,
        fixed_funding_rate=D(rate),
    )
    provider = FixedFundingRateProvider(
        D(rate), backtest.funding_interval, backtest.funding_algorithm_version
    )
    spec, configured, instrument, costs, _ = engine_inputs(
        app_config,
        start,
        bars[-1].close_time,
        config=backtest,
        funding_provider=provider,
    )
    resolved = tuple(
        evaluation(candidate(at, spec.versions, costs, side=side, identity=identity))
        for at, side, identity in evaluations
    )
    return (
        BacktestEngine(spec, configured, instrument, costs, provider).run(tuple(bars), resolved),
        instrument,
    )


@pytest.mark.parametrize(
    ("side", "rate", "positive_cash_flow"),
    [
        (TradeSide.LONG, "0.001", False),
        (TradeSide.LONG, "-0.001", True),
        (TradeSide.SHORT, "0.001", True),
        (TradeSide.SHORT, "-0.001", False),
    ],
)
def test_funding_signs_for_positions_owned_before_boundary(
    app_config, side, rate, positive_cash_flow
):
    start = datetime(2026, 1, 1, 15, 40, tzinfo=UTC)
    bars = tuple(
        candle(start + timedelta(minutes=5 * index), "100", "101", "99", "100")
        for index in range(6)
    )
    result, _ = _fixed_funding_engine(
        app_config,
        start,
        bars,
        rate,
        ((bars[0].close_time, side, f"funding-{side}-{rate}"),),
    )
    assert len(result.funding) == 1
    assert (result.funding[0].cash_flow > D("0")) is positive_cash_flow


def test_funding_at_boundary_uses_open_mark_and_precedes_close_exit(app_config):
    start = datetime(2026, 1, 1, 15, 40, tzinfo=UTC)
    bars = [
        candle(start + timedelta(minutes=5 * index), "100", "101", "99", "100")
        for index in range(6)
    ]
    bars[4] = candle(bars[4].open_time, "100", "120", "99", "120")
    result, instrument = _fixed_funding_engine(
        app_config,
        start,
        bars,
        "0.001",
        ((bars[0].close_time, TradeSide.LONG, "fund-before-exit"),),
    )
    funding = result.funding[0]
    assert funding.event_time == datetime(2026, 1, 1, 16, tzinfo=UTC)
    assert funding.notional == instrument.notional(result.trades[0].initial_quantity, D("100"))
    funding_event = next(
        event for event in result.events if event.event_type is BacktestEventType.FUNDING_APPLIED
    )
    close_event = next(
        event for event in result.events if event.event_type is BacktestEventType.POSITION_CLOSED
    )
    assert funding_event.event_time < close_event.event_time
    assert funding_event.sequence < close_event.sequence
    assert tuple(event.event_time for event in result.events) == tuple(
        sorted(event.event_time for event in result.events)
    )


def test_entry_exactly_at_funding_boundary_is_not_charged(app_config):
    start = datetime(2026, 1, 1, 15, 55, tzinfo=UTC)
    bars = tuple(
        candle(start + timedelta(minutes=5 * index), "100", "101", "99", "100")
        for index in range(3)
    )
    result, _ = _fixed_funding_engine(
        app_config,
        start,
        bars,
        "0.001",
        ((bars[0].close_time, TradeSide.LONG, "entry-at-funding"),),
    )
    assert result.funding == ()


def test_position_closed_before_funding_boundary_is_not_charged(app_config):
    start = datetime(2026, 1, 1, 15, 40, tzinfo=UTC)
    bars = [
        candle(start + timedelta(minutes=5 * index), "100", "101", "99", "100")
        for index in range(6)
    ]
    bars[2] = candle(bars[2].open_time, "100", "111", "99", "110")
    result, _ = _fixed_funding_engine(
        app_config,
        start,
        bars,
        "0.001",
        ((bars[0].close_time, TradeSide.LONG, "closed-before-funding"),),
    )
    assert result.trades[0].exit_time == datetime(2026, 1, 1, 15, 55, tzinfo=UTC)
    assert result.funding == ()


def test_gap_exit_exactly_at_funding_boundary_is_charged_first(app_config):
    start = datetime(2026, 1, 1, 15, 40, tzinfo=UTC)
    bars = [
        candle(start + timedelta(minutes=5 * index), "100", "101", "99", "100")
        for index in range(6)
    ]
    bars[4] = candle(bars[4].open_time, "90", "92", "85", "88")
    result, _ = _fixed_funding_engine(
        app_config,
        start,
        bars,
        "0.001",
        ((bars[0].close_time, TradeSide.LONG, "exit-at-funding"),),
    )
    funding_event = next(
        event for event in result.events if event.event_type is BacktestEventType.FUNDING_APPLIED
    )
    stop_event = next(
        event for event in result.events if event.event_type is BacktestEventType.STOP_FILLED
    )
    assert funding_event.event_time == stop_event.event_time
    assert funding_event.sequence < stop_event.sequence


@dataclass(frozen=True)
class _MisalignedFundingProvider:
    event: FundingRateEvent
    mode: FundingMode = FundingMode.FIXED_ASSUMPTION
    model_version: str = "misaligned-funding-v1"
    maximum_debit_rate: Decimal = FUNDING_RATE

    def validate_range(self, start: datetime, end: datetime) -> None:
        return None

    def rates_between(self, start: datetime, end: datetime):
        return (self.event,) if start <= self.event.timestamp < end else ()


def test_non_m5_aligned_funding_event_fails_closed(app_config):
    start = datetime(2026, 1, 1, 16, tzinfo=UTC)
    bars = (candle(start, "100", "101", "99", "100"),)
    backtest = replace(
        app_config.backtest,
        funding_mode=FundingMode.FIXED_ASSUMPTION,
        fixed_funding_rate=D("0.001"),
    )
    provider = _MisalignedFundingProvider(
        FundingRateEvent(start + timedelta(minutes=2), FUNDING_RATE)
    )
    spec, configured, instrument, costs, _ = engine_inputs(
        app_config,
        start,
        bars[-1].close_time,
        config=backtest,
        funding_provider=provider,
    )
    with pytest.raises(DomainValidationError, match="align exactly"):
        BacktestEngine(spec, configured, instrument, costs, provider).run(bars, ())


def test_same_reference_entry_passes_with_exact_decimal_audit(app_config):
    zero_backtest = replace(
        app_config.backtest,
        modeled_spread_rate=D("0"),
        market_slippage_rate=D("0"),
        stop_slippage_rate=D("0"),
        maker_fee_rate=D("0"),
        taker_fee_rate=D("0"),
    )
    result = _attempt(replace(app_config, backtest=zero_backtest))
    assert result.status is OrderStatus.FILLED
    assert result.fill is not None and result.fill.fill_price == D("100")
    assert result.calculations["price_deviation"] == D("0")
    assert result.calculations["actual_worst_case_loss"] == D("5")
    assert result.calculations["actual_expected_rr"] == D("2")


def _zero_cost_config(app_config):
    return replace(
        app_config,
        backtest=replace(
            app_config.backtest,
            modeled_spread_rate=D("0"),
            market_slippage_rate=D("0"),
            stop_slippage_rate=D("0"),
            maker_fee_rate=D("0"),
            taker_fee_rate=D("0"),
        ),
    )


def test_price_deviation_boundary_is_inclusive(app_config):
    configured = _zero_cost_config(app_config)

    at_tolerance = _attempt(configured, opening="100.2")
    above_tolerance = _attempt(configured, opening="100.2001")

    assert at_tolerance.calculations["price_deviation"] == D("0.002")
    assert at_tolerance.status is OrderStatus.FILLED
    assert above_tolerance.calculations["price_deviation"] == D("0.002001")
    assert above_tolerance.reason_codes == (ReasonCode.PRICE_DEVIATION_TOO_HIGH,)


def test_minimum_rr_boundary_is_inclusive(app_config):
    configured = _zero_cost_config(app_config)

    at_minimum = _attempt(
        configured,
        plan_change={"targets": (Target("TP", D("107.5"), D("1")),)},
    )
    below_minimum = _attempt(
        configured,
        plan_change={"targets": (Target("TP", D("107.4999"), D("1")),)},
    )

    assert at_minimum.calculations["actual_expected_rr"] == D("1.5")
    assert at_minimum.status is OrderStatus.FILLED
    assert below_minimum.calculations["actual_expected_rr"] == D("1.49998")
    assert below_minimum.reason_codes == (ReasonCode.RR_TOO_LOW,)


def test_risk_budget_boundary_is_inclusive(app_config):
    configured = _zero_cost_config(app_config)

    at_budget = _attempt(configured, plan_change={"risk_budget": D("5")})
    above_budget = _attempt(
        configured,
        opening="100.0001",
        plan_change={"risk_budget": D("5")},
    )

    assert at_budget.calculations["actual_worst_case_loss"] == D("5")
    assert at_budget.status is OrderStatus.FILLED
    assert above_budget.calculations["actual_worst_case_loss"] == D("5.0001")
    assert above_budget.reason_codes == (ReasonCode.RISK_BUDGET_EXCEEDED,)


def test_margin_capacity_boundary_is_inclusive(app_config):
    configured = _zero_cost_config(
        replace(app_config, risk=replace(app_config.risk, margin_buffer_ratio=D("0")))
    )

    at_capacity = _attempt(configured, available_margin="50")

    assert at_capacity.calculations["required_margin"] == D("50")
    assert at_capacity.calculations["available_margin"] == D("50")
    assert at_capacity.status is OrderStatus.FILLED


def test_last_mile_uses_configured_precision(app_config):
    configured = _zero_cost_config(app_config)
    opening = "100.123456789012345678901234567890123456789"
    precision_28 = replace(
        configured,
        calculation=replace(configured.calculation, decimal_precision=28),
    )
    precision_50 = replace(
        configured,
        calculation=replace(configured.calculation, decimal_precision=50),
    )

    result_28 = _attempt(precision_28, opening=opening)
    result_50 = _attempt(precision_50, opening=opening)

    assert result_28.status is OrderStatus.FILLED
    assert result_50.status is OrderStatus.FILLED
    assert result_28.calculations["price_deviation"] == D("0.001234567890123456789012346")
    assert result_50.calculations["price_deviation"] == D(
        "0.00123456789012345678901234567890123456789"
    )


def test_ambient_decimal_context_cannot_change_canonical_entry_result(app_config):
    start = datetime(2026, 1, 1, 10, 15, tzinfo=UTC)
    configured_app = _zero_cost_config(app_config)
    spec, configured, instrument, costs, _ = engine_inputs(
        configured_app, start, start + timedelta(minutes=5)
    )
    trade = candidate(start, spec.versions, costs, identity="ambient-context")
    plan = approved_plan(trade, start)
    order = create_entry_order(trade, plan, start)
    bar = candle(
        start,
        "100.123456789012345678901234567890123456789",
        "120",
        "80",
        "100.123456789012345678901234567890123456789",
    )

    def execute() -> EntryExecutionResult:
        return try_fill_entry(
            order,
            trade,
            plan,
            bar,
            instrument,
            configured.backtest,
            configured.execution,
            configured.risk,
            costs,
            configured.calculation,
            current_notional=D("0"),
            available_margin=D("10000"),
            account_equity=configured.backtest.initial_equity,
        )

    with localcontext() as ambient:
        ambient.prec = 6
        ambient.rounding = ROUND_DOWN
        low_precision_ambient = execute()
        assert ambient.prec == 6
        assert ambient.rounding == ROUND_DOWN
    with localcontext() as ambient:
        ambient.prec = 50
        ambient.rounding = ROUND_UP
        high_precision_ambient = execute()
        assert ambient.prec == 50
        assert ambient.rounding == ROUND_UP

    assert low_precision_ambient.status is high_precision_ambient.status is OrderStatus.FILLED
    assert low_precision_ambient.reason_codes == high_precision_ambient.reason_codes == ()
    assert low_precision_ambient.calculations == high_precision_ambient.calculations
    assert low_precision_ambient.fill == high_precision_ambient.fill
    assert canonical_json(low_precision_ambient) == canonical_json(high_precision_ambient)


def test_last_mile_entry_result_is_exactly_repeatable(app_config):
    configured = _zero_cost_config(app_config)

    canonical_results = {
        canonical_json(
            _attempt(
                configured,
                opening="100.123456789012345678901234567890123456789",
            )
        )
        for _ in range(10)
    }

    assert len(canonical_results) == 1


def test_last_mile_decimal_failure_rejects_with_canonical_reason(app_config, monkeypatch):
    def fail_modeled_quote(*_args, **_kwargs):
        raise InvalidOperation

    monkeypatch.setattr("trading_bot.backtest.execution.modeled_quote", fail_modeled_quote)

    result = _attempt(app_config)

    assert result.status is OrderStatus.REJECTED
    assert result.fill is None
    assert result.reason_codes == (ReasonCode.NUMERICAL_ERROR,)
    assert result.calculations == {}


@pytest.mark.parametrize(
    ("side", "opening"),
    [(TradeSide.LONG, "102"), (TradeSide.SHORT, "98")],
)
def test_adverse_entry_gap_rejects_on_price_deviation(app_config, side, opening):
    result = _attempt(app_config, opening=opening, side=side)
    assert result.status is OrderStatus.REJECTED and result.fill is None
    assert ReasonCode.PRICE_DEVIATION_TOO_HIGH in result.reason_codes


@pytest.mark.parametrize(
    ("side", "opening", "reason"),
    [
        (TradeSide.LONG, "94", ReasonCode.INVALID_STOP),
        (TradeSide.LONG, "111", ReasonCode.TARGET_INVALID),
        (TradeSide.SHORT, "106", ReasonCode.INVALID_STOP),
        (TradeSide.SHORT, "89", ReasonCode.TARGET_INVALID),
    ],
)
def test_actual_fill_geometry_fails_closed(app_config, side, opening, reason):
    execution = replace(app_config.execution, price_deviation_tolerance=D("0.2"))
    result = _attempt(replace(app_config, execution=execution), opening=opening, side=side)
    assert result.status is OrderStatus.REJECTED
    assert reason in result.reason_codes


def test_actual_cost_risk_budget_and_rr_are_revalidated(app_config):
    tolerant = replace(app_config.execution, price_deviation_tolerance=D("0.1"))
    configured = replace(app_config, execution=tolerant)
    budget = _attempt(configured, plan_change={"risk_budget": D("5.01")})
    assert ReasonCode.RISK_BUDGET_EXCEEDED in budget.reason_codes
    rr = _attempt(configured, opening="102")
    assert ReasonCode.RR_TOO_LOW in rr.reason_codes


def test_actual_notional_margin_and_slippage_caps_are_not_ignored(app_config):
    tight_cap = replace(
        app_config.risk,
        max_position_notional=D("50"),
        max_total_exposure=D("50"),
    )
    capped = _attempt(replace(app_config, risk=tight_cap))
    assert ReasonCode.POSITION_CAP_EXCEEDED in capped.reason_codes

    exposure = _attempt(app_config, current_notional="9950")
    assert ReasonCode.POSITION_CAP_EXCEEDED in exposure.reason_codes

    margin = _attempt(app_config, available_margin="10")
    assert ReasonCode.INSUFFICIENT_MARGIN in margin.reason_codes

    leverage = _attempt(app_config, plan_change={"leverage": D("6")})
    assert ReasonCode.LEVERAGE_CAP_EXCEEDED in leverage.reason_codes

    low_slippage = replace(app_config.risk, max_slippage=D("0.0001"))
    slippage = _attempt(replace(app_config, risk=low_slippage))
    assert ReasonCode.SLIPPAGE_TOO_HIGH in slippage.reason_codes


def test_rejected_entry_is_terminal_and_engine_journals_calculations(app_config):
    start = datetime(2026, 1, 1, 10, 10, tzinfo=UTC)
    bars = (
        candle(start, "100", "101", "99", "100"),
        candle(start + timedelta(minutes=5), "102", "103", "101", "102"),
        candle(start + timedelta(minutes=10), "100", "101", "99", "100"),
    )
    spec, configured, instrument, costs, provider = engine_inputs(
        app_config, start, bars[-1].close_time
    )
    result = BacktestEngine(spec, configured, instrument, costs, provider).run(
        bars,
        (evaluation(candidate(bars[0].close_time, spec.versions, costs, identity="stale")),),
    )
    assert result.fills == ()
    assert result.orders[0].status is OrderStatus.REJECTED
    rejected = next(
        event for event in result.events if event.event_type is BacktestEventType.ORDER_REJECTED
    )
    assert ReasonCode.PRICE_DEVIATION_TOO_HIGH in rejected.reason_codes
    for field in (
        "approved_entry_price",
        "actual_entry_price",
        "price_deviation",
        "risk_budget",
        "actual_worst_case_loss",
        "actual_expected_rr",
    ):
        assert field in rejected.payload


def test_execution_identity_covers_last_mile_configuration(app_config):
    base = execution_model_version(
        app_config.backtest,
        app_config.execution,
        app_config.risk,
        app_config.calculation,
    )
    changed_tolerance = execution_model_version(
        app_config.backtest,
        replace(app_config.execution, price_deviation_tolerance=D("0.003")),
        app_config.risk,
        app_config.calculation,
    )
    changed_rr = execution_model_version(
        app_config.backtest,
        app_config.execution,
        replace(app_config.risk, minimum_rr=D("1.6")),
        app_config.calculation,
    )
    changed_precision = execution_model_version(
        app_config.backtest,
        app_config.execution,
        app_config.risk,
        replace(app_config.calculation, decimal_precision=40),
    )
    assert len({base, changed_tolerance, changed_rr, changed_precision}) == 4


def test_unknown_entry_model_fails_closed_before_order_creation(app_config):
    start = datetime(2026, 1, 1, 10, 15, tzinfo=UTC)
    spec, _, _, costs, _ = engine_inputs(app_config, start, start + timedelta(minutes=5))
    trade = replace(
        candidate(start, spec.versions, costs),
        entry_model=cast(EntryModel, "FUTURE_ENTRY_MODEL"),
    )
    with pytest.raises(DomainValidationError, match="entry model"):
        create_entry_order(trade, approved_plan(trade, start), start)


def test_catastrophic_gap_retains_negative_equity_halts_and_persists(app_config, tmp_path):
    start = datetime(2026, 1, 1, 10, 10, tzinfo=UTC)
    zero_backtest = replace(
        app_config.backtest,
        initial_equity=D("100"),
        modeled_spread_rate=D("0"),
        market_slippage_rate=D("0"),
        stop_slippage_rate=D("0"),
        maker_fee_rate=D("0"),
        taker_fee_rate=D("0"),
    )
    risk = replace(
        app_config.risk,
        risk_per_trade=D("0.99"),
        target_leverage=D("5"),
        max_leverage=D("5"),
        margin_buffer_ratio=D("0"),
    )
    configured_app = replace(app_config, backtest=zero_backtest, risk=risk)
    bars = (
        candle(start, "100", "101", "99", "100"),
        candle(start + timedelta(minutes=5), "100", "101", "99", "100"),
        candle(start + timedelta(minutes=10), "0.01", "0.02", "0.005", "0.01"),
        candle(start + timedelta(minutes=15), "100", "120", "90", "110"),
    )
    spec, configured, instrument, costs, provider = engine_inputs(
        configured_app, start, bars[-1].close_time
    )
    result = BacktestEngine(spec, configured, instrument, costs, provider).run(
        bars,
        (
            evaluation(candidate(bars[0].close_time, spec.versions, costs, identity="catastrophe")),
            evaluation(
                candidate(bars[3].close_time, spec.versions, costs, identity="future-entry")
            ),
        ),
    )
    assert result.run.status is BacktestStatus.HALTED
    assert result.metrics.final_equity < D("0")
    assert len(result.trades) == 1 and result.trades[0].net_pnl < -D("100")
    assert result.run.completed_at == bars[2].close_time
    assert len(result.orders) == 1
    halt = next(
        event for event in result.events if event.event_type is BacktestEventType.ECONOMIC_HALT
    )
    assert halt.reason_codes == (ReasonCode.EQUITY_DEPLETED,)
    assert BacktestWarning.NEGATIVE_EQUITY_WITHOUT_LIQUIDATION_MODEL in result.run.warnings

    repository = SQLiteBacktestRepository(tmp_path / "catastrophic.db")
    try:
        repository.append_result(result)
        assert repository.get_result_json(spec.backtest_run_id) is not None
    finally:
        repository.close()


def test_force_close_revaluation_does_not_inflate_exposure_denominator(app_config):
    start = datetime(2026, 1, 1, 10, 5, tzinfo=UTC)
    bars = tuple(
        candle(start + timedelta(minutes=5 * index), "100", "101", "99", "100")
        for index in range(10)
    )
    spec, configured, instrument, costs, provider = engine_inputs(
        app_config, start, bars[-1].close_time
    )
    result: BacktestResult = BacktestEngine(spec, configured, instrument, costs, provider).run(
        bars,
        (evaluation(candidate(bars[4].close_time, spec.versions, costs, identity="exposure")),),
    )
    assert result.metrics.market_exposure_ratio == D("0.5")
    assert len(result.equity_curve) == 11


def test_no_position_finalization_keeps_exact_bar_denominator(app_config):
    start = datetime(2026, 1, 1, 10, 5, tzinfo=UTC)
    bars = tuple(
        candle(start + timedelta(minutes=5 * index), "100", "101", "99", "100")
        for index in range(10)
    )
    spec, configured, instrument, costs, provider = engine_inputs(
        app_config, start, bars[-1].close_time
    )
    result = BacktestEngine(spec, configured, instrument, costs, provider).run(bars, ())
    assert result.metrics.market_exposure_ratio == D("0")
    assert len(result.equity_curve) == 10


def test_backtest_result_rejects_decreasing_event_time(app_config):
    start = datetime(2026, 1, 1, 10, 10, tzinfo=UTC)
    bars = (
        candle(start, "100", "101", "99", "100"),
        candle(start + timedelta(minutes=5), "100", "101", "99", "100"),
    )
    spec, configured, instrument, costs, provider = engine_inputs(
        app_config, start, bars[-1].close_time
    )
    result = BacktestEngine(spec, configured, instrument, costs, provider).run(
        bars,
        (evaluation(candidate(bars[0].close_time, spec.versions, costs)),),
    )
    corrupted = (
        result.events[0],
        replace(result.events[1], event_time=result.events[0].event_time - timedelta(seconds=1)),
        *result.events[2:],
    )
    with pytest.raises(DomainValidationError, match="monotonic"):
        replace(result, events=corrupted)
