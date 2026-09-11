"""Deterministic M5 order and fill semantics for historical OHLCV."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, DecimalException

from trading_bot.backtest.costs import (
    adverse_market_fill,
    adverse_stop_fill,
    fee_for_fill,
    modeled_quote,
)
from trading_bot.backtest.models import BacktestOrderState, SimulatedFill
from trading_bot.config.calculation import calculation_context
from trading_bot.config.models import (
    BacktestConfig,
    CalculationConfig,
    ExecutionConfig,
    RiskConfig,
)
from trading_bot.domain.decision_models import TradeCandidate
from trading_bot.domain.enums import (
    EntryModel,
    ExitReason,
    LiquidityRole,
    OrderDirection,
    OrderPurpose,
    OrderStatus,
    OrderType,
    ReasonCode,
    TradeSide,
)
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.identifiers import client_order_id, deterministic_id
from trading_bot.domain.market_models import Candle
from trading_bot.domain.primitives import ONE, freeze_mapping
from trading_bot.domain.risk_models import ApprovedTradePlan, InstrumentMetadata
from trading_bot.domain.value_objects import CostRateEstimate, Target

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class ExitInstruction:
    purpose: OrderPurpose
    exit_reason: ExitReason
    target_index: int | None
    reference_price: Decimal
    quantity: Decimal


@dataclass(frozen=True, slots=True)
class EntryExecutionResult:
    """Typed, auditable outcome of attempting one approved entry intent."""

    order: BacktestOrderState
    fill: SimulatedFill | None
    status: OrderStatus
    reason_codes: tuple[ReasonCode, ...]
    calculations: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        if self.status is not self.order.status:
            raise DomainValidationError("entry execution status must match order status")
        if self.fill is not None and self.status is not OrderStatus.FILLED:
            raise DomainValidationError("an entry fill requires FILLED status")
        object.__setattr__(self, "calculations", freeze_mapping(self.calculations))

    def __iter__(self) -> Iterator[BacktestOrderState | SimulatedFill | None]:
        """Retain tuple-unpacking compatibility for existing callers."""
        yield self.order
        yield self.fill


def create_entry_order(
    candidate: TradeCandidate,
    plan: ApprovedTradePlan,
    decision_time: datetime,
    *,
    order_type: OrderType = OrderType.MARKET,
    limit_price: Decimal | None = None,
) -> BacktestOrderState:
    if candidate.entry_model is not EntryModel.CLOSE_REFERENCE:
        raise DomainValidationError("unsupported candidate entry model")
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
    candidate: TradeCandidate,
    plan: ApprovedTradePlan,
    bar: Candle,
    metadata: InstrumentMetadata,
    config: BacktestConfig,
    execution: ExecutionConfig,
    risk: RiskConfig,
    costs: CostRateEstimate,
    calculation: CalculationConfig,
    *,
    current_notional: Decimal,
    available_margin: Decimal,
    account_equity: Decimal,
) -> EntryExecutionResult:
    if candidate.entry_model is not EntryModel.CLOSE_REFERENCE:
        rejected = replace(order, status=OrderStatus.REJECTED)
        return EntryExecutionResult(
            rejected,
            None,
            rejected.status,
            (ReasonCode.INVALID_ENTRY_PRICE,),
            {},
        )
    if (
        order.candidate_id != candidate.candidate_id
        or order.approved_plan_id != plan.approved_plan_id
        or plan.candidate_id != candidate.candidate_id
    ):
        raise DomainValidationError("entry execution identities do not match")
    if (
        order.expires_at != plan.expires_at
        or plan.instrument_version != metadata.version
        or plan.cost_model_version != costs.model_version
        or candidate.cost_rate_estimate.model_version != costs.model_version
    ):
        rejected = replace(order, status=OrderStatus.REJECTED)
        return EntryExecutionResult(
            rejected,
            None,
            rejected.status,
            (ReasonCode.VERSION_MISMATCH,),
            {},
        )
    if order.status is not OrderStatus.INTENT_CREATED:
        return EntryExecutionResult(order, None, order.status, (), {})
    if bar.open_time < order.eligible_from:
        return EntryExecutionResult(order, None, order.status, (), {})
    if bar.open_time >= order.expires_at:
        expired = replace(order, status=OrderStatus.EXPIRED)
        return EntryExecutionResult(
            expired,
            None,
            expired.status,
            (ReasonCode.APPROVAL_EXPIRED,),
            {},
        )
    try:
        with calculation_context(calculation):
            fill = _entry_fill(order, bar, metadata, config)
            if fill is None:
                return EntryExecutionResult(order, None, order.status, (), {})
            reasons, calculations = _validate_entry_fill(
                candidate,
                plan,
                fill,
                bar,
                metadata,
                config,
                execution,
                risk,
                costs,
                current_notional=current_notional,
                available_margin=available_margin,
                account_equity=account_equity,
            )
    except (DecimalException, ArithmeticError):
        rejected = replace(order, status=OrderStatus.REJECTED)
        return EntryExecutionResult(
            rejected,
            None,
            rejected.status,
            (ReasonCode.NUMERICAL_ERROR,),
            {},
        )
    if reasons:
        rejected = replace(order, status=OrderStatus.REJECTED)
        return EntryExecutionResult(rejected, None, rejected.status, reasons, calculations)
    filled = replace(
        order,
        filled_quantity=order.requested_quantity,
        status=OrderStatus.FILLED,
        filled_at=bar.open_time,
    )
    return EntryExecutionResult(filled, fill, filled.status, (), calculations)


def _entry_fill(
    order: BacktestOrderState,
    bar: Candle,
    metadata: InstrumentMetadata,
    config: BacktestConfig,
) -> SimulatedFill | None:
    """Build the executable fill inside the configured Decimal calculation scope."""
    if order.order_type is OrderType.LIMIT:
        assert order.limit_price is not None
        touched = (
            bar.low <= order.limit_price
            if order.side is TradeSide.LONG
            else bar.high >= order.limit_price
        )
        if not touched:
            return None
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
    return fill


def _validate_entry_fill(
    candidate: TradeCandidate,
    plan: ApprovedTradePlan,
    fill: SimulatedFill,
    bar: Candle,
    metadata: InstrumentMetadata,
    config: BacktestConfig,
    execution: ExecutionConfig,
    risk: RiskConfig,
    costs: CostRateEstimate,
    *,
    current_notional: Decimal,
    available_margin: Decimal,
    account_equity: Decimal,
) -> tuple[tuple[ReasonCode, ...], Mapping[str, Decimal]]:
    """Revalidate the approved quantity against the executable fill without resizing."""
    actual = fill.fill_price
    deviation = abs(actual - plan.entry_price) / plan.entry_price
    base_quantity = metadata.base_quantity(plan.quantity)
    actual_notional = fill.notional
    stop_distance = abs(actual - plan.stop_price)
    stop_quote = modeled_quote(plan.symbol, actual, bar.open_time, config)
    stop_spread = stop_quote.ask - stop_quote.bid
    _, modeled_stop_fill = adverse_stop_fill(
        plan.side,
        plan.stop_price,
        plan.stop_price,
        plan.symbol,
        bar.open_time,
        config,
    )
    stop_notional = metadata.notional(plan.quantity, modeled_stop_fill)
    stop_fee = stop_notional * costs.stop_exit_fee_rate
    funding_buffer = actual_notional * costs.funding_debit_rate
    actual_worst_loss = (
        abs(actual - modeled_stop_fill) * base_quantity + fill.fee + stop_fee + funding_buffer
    )
    primary_target = plan.targets[0].price
    gross_reward = abs(primary_target - actual) * base_quantity
    target_fee = metadata.notional(plan.quantity, primary_target) * costs.target_exit_fee_rate
    net_reward = gross_reward - fill.fee - target_fee - funding_buffer
    actual_rr = net_reward / actual_worst_loss if actual_worst_loss > ZERO else ZERO
    required_margin = actual_notional / plan.leverage if plan.leverage > ZERO else actual_notional
    margin_capacity = available_margin * (ONE - risk.margin_buffer_ratio)
    calculations = {
        "approved_entry_price": plan.entry_price,
        "actual_entry_price": actual,
        "price_deviation": deviation,
        "risk_budget": plan.risk_budget,
        "actual_worst_case_loss": actual_worst_loss,
        "actual_expected_rr": actual_rr,
        "actual_notional": actual_notional,
        "required_margin": required_margin,
        "available_margin": available_margin,
        "current_notional": current_notional,
    }
    reasons: list[ReasonCode] = []
    if deviation > execution.price_deviation_tolerance:
        reasons.append(ReasonCode.PRICE_DEVIATION_TOO_HIGH)
    stop_valid = (
        plan.stop_price < actual if plan.side is TradeSide.LONG else actual < plan.stop_price
    )
    targets_valid = (
        all(actual < target.price for target in plan.targets)
        if plan.side is TradeSide.LONG
        else all(target.price < actual for target in plan.targets)
    )
    if not stop_valid:
        reasons.append(ReasonCode.INVALID_STOP)
    if not targets_valid:
        reasons.append(ReasonCode.TARGET_INVALID)
    if (
        stop_distance < candidate.reference_atr * risk.stop_min_distance_atr
        or stop_distance < metadata.tick_size * risk.stop_minimum_tick_multiple
        or stop_distance < stop_spread * risk.stop_minimum_spread_multiple
    ):
        reasons.append(ReasonCode.STOP_TOO_CLOSE)
    if stop_distance > candidate.reference_atr * risk.stop_max_distance_atr:
        reasons.append(ReasonCode.STOP_TOO_FAR)
    if net_reward <= ZERO or actual_rr < risk.minimum_rr:
        reasons.append(ReasonCode.RR_TOO_LOW)
    if actual_worst_loss > plan.risk_budget:
        reasons.append(ReasonCode.RISK_BUDGET_EXCEEDED)
    if max(costs.entry_slippage_rate, costs.stop_slippage_rate) > risk.max_slippage:
        reasons.append(ReasonCode.SLIPPAGE_TOO_HIGH)
    if (
        plan.quantity > metadata.maximum_order_quantity
        or actual_notional > risk.max_position_notional
        or current_notional + actual_notional > risk.max_total_exposure
    ):
        reasons.append(ReasonCode.POSITION_CAP_EXCEEDED)
    if (
        plan.leverage < ONE
        or plan.leverage > risk.max_leverage
        or plan.leverage > metadata.maximum_leverage
        or actual_notional > account_equity * risk.max_leverage
    ):
        reasons.append(ReasonCode.LEVERAGE_CAP_EXCEEDED)
    if required_margin > margin_capacity:
        reasons.append(ReasonCode.INSUFFICIENT_MARGIN)
    return tuple(dict.fromkeys(reasons)), calculations


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
