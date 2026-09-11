from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from trading_bot.backtest.costs import modeled_quote
from trading_bot.backtest.execution import (
    create_entry_order,
    execute_exit,
    exit_instructions,
    try_fill_entry,
)
from trading_bot.domain.enums import ExitReason, OrderPurpose, OrderStatus, OrderType, TradeSide
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.value_objects import CostRateEstimate, Target

from .helpers import START, approved_plan, candidate, candle, engine_inputs

D = Decimal


def _zero_rates() -> CostRateEstimate:
    return CostRateEstimate(*(D("0") for _ in range(7)), model_version="zero-cost")


def test_long_and_short_market_fills_are_adverse_and_fee_uses_executed_notional(app_config):
    _, config, instrument, _, _ = engine_inputs(app_config, START, START + timedelta(minutes=10))
    spec, _, _, _, _ = engine_inputs(app_config, START, START + timedelta(minutes=10))
    bar = candle(START, "100", "102", "98", "101")
    for side in (TradeSide.LONG, TradeSide.SHORT):
        trade = candidate(START, spec.versions, _zero_rates(), side=side)
        plan = approved_plan(trade, START)
        order = create_entry_order(trade, plan, START)
        filled, execution = try_fill_entry(order, bar, instrument, config.backtest)
        assert execution is not None and filled.status is OrderStatus.FILLED
        quote = modeled_quote(trade.symbol, bar.open, bar.open_time, config.backtest)
        if side is TradeSide.LONG:
            assert execution.fill_price > quote.ask > bar.open
        else:
            assert execution.fill_price < quote.bid < bar.open
        assert execution.fee == execution.notional * config.backtest.taker_fee_rate
        assert execution.spread_cost_estimate > 0
        assert execution.slippage_cost_estimate > 0


def test_entry_never_fills_before_decision_and_limit_needs_future_touch(app_config):
    spec, config, instrument, costs, _ = engine_inputs(
        app_config, START, START + timedelta(minutes=20)
    )
    decision_time = START + timedelta(minutes=5)
    trade = candidate(decision_time, spec.versions, costs)
    plan = approved_plan(trade, decision_time)
    market = create_entry_order(trade, plan, decision_time)
    historical = candle(START, "100", "120", "80", "100")
    unchanged, fill = try_fill_entry(market, historical, instrument, config.backtest)
    assert unchanged == market and fill is None

    limit = create_entry_order(
        trade, plan, decision_time, order_type=OrderType.LIMIT, limit_price=D("99")
    )
    untouched = candle(decision_time, "101", "102", "100", "101")
    still_pending, fill = try_fill_entry(limit, untouched, instrument, config.backtest)
    assert still_pending.status is OrderStatus.INTENT_CREATED and fill is None
    touched = candle(decision_time + timedelta(minutes=5), "101", "102", "98", "100")
    completed, fill = try_fill_entry(still_pending, touched, instrument, config.backtest)
    assert completed.status is OrderStatus.FILLED
    assert fill is not None and fill.fill_price == D("99")

    with pytest.raises(DomainValidationError, match="timing"):
        create_entry_order(trade, plan, decision_time - timedelta(minutes=5))


def test_expired_approval_does_not_fill(app_config):
    spec, config, instrument, costs, _ = engine_inputs(
        app_config, START, START + timedelta(minutes=20)
    )
    trade = candidate(START, spec.versions, costs)
    plan = replace(approved_plan(trade, START), expires_at=START + timedelta(seconds=30))
    order = create_entry_order(trade, plan, START)
    later = candle(START + timedelta(minutes=5), "100", "101", "99", "100")
    expired, fill = try_fill_entry(order, later, instrument, config.backtest)
    assert expired.status is OrderStatus.EXPIRED and fill is None


def test_stop_gap_and_intrabar_worst_case_are_symmetric(app_config):
    spec, config, instrument, costs, _ = engine_inputs(
        app_config, START, START + timedelta(minutes=20)
    )
    scenarios = (
        (TradeSide.LONG, "90", "111", "89", "100", D("95")),
        (TradeSide.SHORT, "110", "111", "89", "100", D("105")),
    )
    for side, opening, high, low, close, stop in scenarios:
        trade = candidate(START, spec.versions, costs, side=side, identity=f"{side}-gap")
        plan = approved_plan(trade, START)
        bar = candle(START + timedelta(minutes=5), opening, high, low, close)
        instructions = exit_instructions(side, stop, ((0, trade.targets[0], D("1")),), D("1"), bar)
        assert len(instructions) == 1
        assert instructions[0].exit_reason is ExitReason.STOP_LOSS
        fill = execute_exit(instructions[0], 0, plan, bar, instrument, config.backtest)
        if side is TradeSide.LONG:
            assert fill.fill_price < D(opening) < stop
        else:
            assert fill.fill_price > D(opening) > stop


def test_target_gap_has_no_price_improvement_and_multiple_targets_keep_allocations(app_config):
    spec, config, instrument, costs, _ = engine_inputs(
        app_config, START, START + timedelta(minutes=20)
    )
    trade = candidate(START, spec.versions, costs)
    targets = (Target("TP1", D("105"), D("0.5")), Target("TP2", D("110"), D("0.5")))
    plan = approved_plan(trade, START, quantity=D("2"), targets=targets)
    bar = candle(START + timedelta(minutes=5), "115", "116", "114", "115")
    instructions = exit_instructions(
        TradeSide.LONG,
        plan.stop_price,
        ((0, targets[0], D("1")), (1, targets[1], D("1"))),
        D("2"),
        bar,
    )
    fills = tuple(
        execute_exit(item, index, plan, bar, instrument, config.backtest)
        for index, item in enumerate(instructions)
    )
    assert tuple(fill.quantity for fill in fills) == (D("1"), D("1"))
    assert tuple(fill.fill_price for fill in fills) == (D("105"), D("110"))
    assert all(fill.purpose is OrderPurpose.TAKE_PROFIT for fill in fills)


def test_normal_stops_and_targets_are_symmetric(app_config):
    spec, config, instrument, costs, _ = engine_inputs(
        app_config, START, START + timedelta(minutes=20)
    )
    cases = (
        (TradeSide.LONG, "100", "110", "94", D("95"), ExitReason.STOP_LOSS),
        (TradeSide.SHORT, "100", "106", "90", D("105"), ExitReason.STOP_LOSS),
        (TradeSide.LONG, "100", "111", "96", D("110"), ExitReason.TAKE_PROFIT),
        (TradeSide.SHORT, "100", "104", "89", D("90"), ExitReason.TAKE_PROFIT),
    )
    for index, (side, opening, high, low, expected, reason) in enumerate(cases):
        trade = candidate(START, spec.versions, costs, side=side, identity=f"normal-{index}")
        plan = approved_plan(trade, START)
        bar = candle(START + timedelta(minutes=5), opening, high, low, "100")
        instructions = exit_instructions(
            side,
            plan.stop_price,
            ((0, plan.targets[0], D("1")),),
            D("1"),
            bar,
        )
        assert instructions[0].exit_reason is reason
        fill = execute_exit(instructions[0], 0, plan, bar, instrument, config.backtest)
        if reason is ExitReason.TAKE_PROFIT:
            assert fill.fill_price == expected
        elif side is TradeSide.LONG:
            assert fill.fill_price < expected
        else:
            assert fill.fill_price > expected


def test_filled_approval_is_one_shot(app_config):
    spec, config, instrument, costs, _ = engine_inputs(
        app_config, START, START + timedelta(minutes=10)
    )
    trade = candidate(START, spec.versions, costs)
    order = create_entry_order(trade, approved_plan(trade, START), START)
    bar = candle(START, "100", "101", "99", "100")
    filled, first = try_fill_entry(order, bar, instrument, config.backtest)
    unchanged, duplicate = try_fill_entry(filled, bar, instrument, config.backtest)
    assert first is not None
    assert unchanged == filled
    assert duplicate is None


def test_same_bar_stop_and_target_worst_case_is_symmetric(app_config):
    spec, _, _, costs, _ = engine_inputs(app_config, START, START + timedelta(minutes=10))
    bar = candle(START + timedelta(minutes=5), "100", "111", "89", "100")
    for side in (TradeSide.LONG, TradeSide.SHORT):
        trade = candidate(START, spec.versions, costs, side=side, identity=f"both-{side}")
        instructions = exit_instructions(
            side,
            trade.stop_price,
            ((0, trade.targets[0], D("1")),),
            D("1"),
            bar,
        )
        assert len(instructions) == 1
        assert instructions[0].exit_reason is ExitReason.STOP_LOSS


def test_short_target_gap_has_no_improvement(app_config):
    spec, config, instrument, costs, _ = engine_inputs(
        app_config, START, START + timedelta(minutes=10)
    )
    trade = candidate(START, spec.versions, costs, side=TradeSide.SHORT, identity="short-gap")
    plan = approved_plan(trade, START)
    bar = candle(START + timedelta(minutes=5), "80", "81", "79", "80")
    instruction = exit_instructions(
        TradeSide.SHORT,
        plan.stop_price,
        ((0, plan.targets[0], D("1")),),
        D("1"),
        bar,
    )[0]
    fill = execute_exit(instruction, 0, plan, bar, instrument, config.backtest)
    assert fill.fill_price == D("90")
