"""Deterministic M5 order and fill semantics for historical OHLCV."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from trading_bot.backtest.costs import (
    adverse_market_fill,
    adverse_stop_fill,
    fee_for_fill,
    modeled_quote,
)
from trading_bot.backtest.models import BacktestOrderState, SimulatedFill
from trading_bot.config.models import BacktestConfig
from trading_bot.domain.decision_models import TradeCandidate
from trading_bot.domain.enums import (
    ExitReason,
    LiquidityRole,
    OrderDirection,
    OrderPurpose,
    OrderStatus,
    OrderType,
    TradeSide,
)
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.identifiers import client_order_id, deterministic_id
from trading_bot.domain.market_models import Candle
from trading_bot.domain.risk_models import ApprovedTradePlan, InstrumentMetadata
from trading_bot.domain.value_objects import Target

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class ExitInstruction:
    purpose: OrderPurpose
    exit_reason: ExitReason
    target_index: int | None
    reference_price: Decimal
    quantity: Decimal


def create_entry_order(
    candidate: TradeCandidate,
    plan: ApprovedTradePlan,
    decision_time: datetime,
    *,
    order_type: OrderType = OrderType.MARKET,
    limit_price: Decimal | None = None,
) -> BacktestOrderState:
    if plan.candidate_id != candidate.candidate_id or plan.side is not candidate.side:
        raise DomainValidationError("candidate and approved plan do not match")
    if decision_time != candidate.created_at or plan.created_at != decision_time:
        raise DomainValidationError("entry intent timing does not match candidate approval")
    if order_type not in {OrderType.MARKET, OrderType.LIMIT}:
        raise DomainValidationError("backtest entry supports MARKET or LIMIT only")
    order_id = client_order_id(plan.approved_plan_id, OrderPurpose.ENTRY, 0)
    return BacktestOrderState(
        order_id=order_id,
        approved_plan_id=plan.approved_plan_id,
        candidate_id=candidate.candidate_id,
        trade_id=candidate.candidate_id,
        side=plan.side,
        order_type=order_type,
        limit_price=limit_price,
        requested_quantity=plan.quantity,
        filled_quantity=ZERO,
        created_at=decision_time,
        eligible_from=decision_time,
        expires_at=plan.expires_at,
        status=OrderStatus.INTENT_CREATED,
        filled_at=None,
    )


def try_fill_entry(
    order: BacktestOrderState,
    bar: Candle,
    metadata: InstrumentMetadata,
    config: BacktestConfig,
) -> tuple[BacktestOrderState, SimulatedFill | None]:
    if order.status is not OrderStatus.INTENT_CREATED:
        return order, None
    if bar.open_time < order.eligible_from:
        return order, None
    if bar.open_time >= order.expires_at:
        return replace(order, status=OrderStatus.EXPIRED), None
    if order.order_type is OrderType.LIMIT:
        assert order.limit_price is not None
        touched = (
            bar.low <= order.limit_price
            if order.side is TradeSide.LONG
            else bar.high >= order.limit_price
        )
        if not touched:
            return order, None
        reference = order.limit_price
        fill_price = order.limit_price
        role = LiquidityRole.TAKER
        spread_cost = ZERO
        slippage_cost = ZERO
    else:
        reference = bar.open
        quote = modeled_quote(bar.symbol, reference, bar.open_time, config)
        direction = OrderDirection.BUY if order.side is TradeSide.LONG else OrderDirection.SELL
        fill_price = adverse_market_fill(direction, quote, config.market_slippage_rate)
        role = LiquidityRole.TAKER
        base_quantity = metadata.base_quantity(order.requested_quantity)
        executable_quote = quote.ask if direction is OrderDirection.BUY else quote.bid
        spread_cost = abs(executable_quote - reference) * base_quantity
        slippage_cost = abs(fill_price - executable_quote) * base_quantity
    direction = OrderDirection.BUY if order.side is TradeSide.LONG else OrderDirection.SELL
    fill = _fill(
        order.order_id,
        order.approved_plan_id,
        order.trade_id,
        OrderPurpose.ENTRY,
        direction,
        role,
        reference,
        fill_price,
        order.requested_quantity,
        spread_cost,
        slippage_cost,
        bar.open_time,
        metadata,
        config,
    )
    return (
        replace(
            order,
            filled_quantity=order.requested_quantity,
            status=OrderStatus.FILLED,
            filled_at=bar.open_time,
        ),
        fill,
    )


def exit_instructions(
    side: TradeSide,
    stop_price: Decimal,
    target_quantities: tuple[tuple[int, Target, Decimal], ...],
    remaining_quantity: Decimal,
    bar: Candle,
) -> tuple[ExitInstruction, ...]:
    stop_touched = bar.low <= stop_price if side is TradeSide.LONG else bar.high >= stop_price
    touched_targets = tuple(
        (index, target, quantity)
        for index, target, quantity in target_quantities
        if quantity > ZERO
        and (bar.high >= target.price if side is TradeSide.LONG else bar.low <= target.price)
    )
    if stop_touched:
        return (
            ExitInstruction(
                OrderPurpose.STOP,
                ExitReason.STOP_LOSS,
                None,
                stop_price,
                remaining_quantity,
            ),
        )
    return tuple(
        ExitInstruction(
            OrderPurpose.TAKE_PROFIT,
            ExitReason.TAKE_PROFIT,
            index,
            target.price,
            quantity,
        )
        for index, target, quantity in touched_targets
    )


def execute_exit(
    instruction: ExitInstruction,
    order_sequence: int,
    plan: ApprovedTradePlan,
    bar: Candle,
    metadata: InstrumentMetadata,
    config: BacktestConfig,
) -> SimulatedFill:
    direction = OrderDirection.SELL if plan.side is TradeSide.LONG else OrderDirection.BUY
    role = LiquidityRole.TAKER
    if instruction.purpose is OrderPurpose.STOP:
        reference, fill_price = adverse_stop_fill(
            plan.side,
            instruction.reference_price,
            bar.open,
            plan.symbol,
            bar.open_time,
            config,
        )
        quote = modeled_quote(plan.symbol, reference, bar.open_time, config)
        executable_quote = quote.bid if direction is OrderDirection.SELL else quote.ask
        base_quantity = metadata.base_quantity(instruction.quantity)
        spread_cost = abs(executable_quote - reference) * base_quantity
        slippage_cost = abs(fill_price - executable_quote) * base_quantity
        is_gap = (
            bar.open < instruction.reference_price
            if plan.side is TradeSide.LONG
            else bar.open > instruction.reference_price
        )
        event_time = bar.open_time if is_gap else bar.close_time
    else:
        reference = instruction.reference_price
        fill_price = reference
        spread_cost = ZERO
        slippage_cost = ZERO
        event_time = bar.close_time
    order_id = client_order_id(plan.approved_plan_id, instruction.purpose, order_sequence)
    return _fill(
        order_id,
        plan.approved_plan_id,
        plan.candidate_id,
        instruction.purpose,
        direction,
        role,
        reference,
        fill_price,
        instruction.quantity,
        spread_cost,
        slippage_cost,
        event_time,
        metadata,
        config,
    )


def force_close_fill(
    plan: ApprovedTradePlan,
    quantity: Decimal,
    final_bar: Candle,
    metadata: InstrumentMetadata,
    config: BacktestConfig,
    order_sequence: int,
) -> SimulatedFill:
    direction = OrderDirection.SELL if plan.side is TradeSide.LONG else OrderDirection.BUY
    quote = modeled_quote(plan.symbol, final_bar.close, final_bar.close_time, config)
    fill_price = adverse_market_fill(direction, quote, config.market_slippage_rate)
    base_quantity = metadata.base_quantity(quantity)
    executable_quote = quote.bid if direction is OrderDirection.SELL else quote.ask
    order_id = client_order_id(plan.approved_plan_id, OrderPurpose.EXIT, order_sequence)
    return _fill(
        order_id,
        plan.approved_plan_id,
        plan.candidate_id,
        OrderPurpose.EXIT,
        direction,
        LiquidityRole.TAKER,
        final_bar.close,
        fill_price,
        quantity,
        abs(executable_quote - final_bar.close) * base_quantity,
        abs(fill_price - executable_quote) * base_quantity,
        final_bar.close_time,
        metadata,
        config,
    )


def _fill(
    order_id: str,
    approved_plan_id: str,
    trade_id: str,
    purpose: OrderPurpose,
    direction: OrderDirection,
    role: LiquidityRole,
    reference_price: Decimal,
    fill_price: Decimal,
    quantity: Decimal,
    spread_cost: Decimal,
    slippage_cost: Decimal,
    event_time: datetime,
    metadata: InstrumentMetadata,
    config: BacktestConfig,
) -> SimulatedFill:
    notional = metadata.notional(quantity, fill_price)
    fee = fee_for_fill(metadata, quantity, fill_price, role, config)
    identifier = deterministic_id(
        "backtest-fill-v1",
        order_id,
        purpose,
        direction,
        event_time,
        quantity,
        fill_price,
    )
    return SimulatedFill(
        identifier,
        order_id,
        approved_plan_id,
        trade_id,
        purpose,
        direction,
        role,
        reference_price,
        fill_price,
        quantity,
        notional,
        fee,
        spread_cost,
        slippage_cost,
        event_time,
    )
