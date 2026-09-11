"""Conservative stop-risk sizing and sole ApprovedTradePlan factory."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, DecimalException

from trading_bot.config.calculation import calculation_context
from trading_bot.config.models import CalculationConfig, RiskConfig
from trading_bot.domain.decision_models import TradeCandidate
from trading_bot.domain.enums import ReasonCode, RiskAction, TradeSide
from trading_bot.domain.identifiers import approved_plan_id, risk_approval_id, risk_decision_id
from trading_bot.domain.primitives import ONE, ZERO, ceil_to_step, floor_to_step
from trading_bot.domain.risk_models import (
    ApprovedTradePlan,
    InstrumentMetadata,
    RiskContext,
    RiskDecision,
)
from trading_bot.domain.value_objects import CostRateEstimate, FeeBreakdown, Target


@dataclass(frozen=True, slots=True)
class RiskOutcome:
    decision: RiskDecision
    plan: ApprovedTradePlan | None


def _loss_per_contract(
    entry: Decimal, stop: Decimal, value: Decimal, rates: CostRateEstimate
) -> Decimal:
    return value * (
        abs(entry - stop)
        + entry * (rates.entry_fee_rate + rates.entry_slippage_rate + rates.funding_debit_rate)
        + stop * (rates.stop_exit_fee_rate + rates.stop_slippage_rate)
    )


def _decision(
    candidate: TradeCandidate,
    context: RiskContext,
    metadata: InstrumentMetadata,
    rates: CostRateEstimate,
    action: RiskAction,
    reasons: tuple[ReasonCode, ...],
    observed: dict[str, Decimal],
    now: datetime,
    ttl: timedelta,
    approval: str | None = None,
    plan_id: str | None = None,
) -> RiskDecision:
    identifier = risk_decision_id(
        candidate.candidate_id,
        context.risk_context_id,
        context.state_version,
        candidate.versions.config_version,
        metadata.version,
    )
    return RiskDecision(
        identifier,
        candidate.candidate_id,
        context.risk_context_id,
        action,
        reasons,
        observed,
        approval,
        plan_id,
        now,
        now + ttl,
        candidate.versions.config_version,
        context.state_version,
        metadata.version,
        rates.model_version,
    )


def evaluate_risk(
    candidate: TradeCandidate,
    context: RiskContext,
    metadata: InstrumentMetadata,
    rates: CostRateEstimate,
    config: RiskConfig,
    calculation: CalculationConfig,
    approval_ttl: timedelta,
    now: datetime,
    metadata_max_age: timedelta | None = None,
) -> RiskOutcome:
    with calculation_context(calculation):
        try:
            return _evaluate_risk(
                candidate,
                context,
                metadata,
                rates,
                config,
                approval_ttl,
                now,
                metadata_max_age,
            )
        except (DecimalException, ArithmeticError):
            return RiskOutcome(
                _decision(
                    candidate,
                    context,
                    metadata,
                    rates,
                    RiskAction.HALT,
                    (ReasonCode.NUMERICAL_ERROR,),
                    {},
                    now,
                    approval_ttl,
                ),
                None,
            )


def _evaluate_risk(
    candidate: TradeCandidate,
    context: RiskContext,
    metadata: InstrumentMetadata,
    rates: CostRateEstimate,
    config: RiskConfig,
    approval_ttl: timedelta,
    now: datetime,
    metadata_max_age: timedelta | None,
) -> RiskOutcome:
    observed = {
        "daily_net_pnl": context.daily_net_pnl,
        "daily_drawdown_ratio": context.daily_drawdown_ratio,
        "spread_fraction": context.quote.spread_fraction,
        "current_notional": context.current_notional,
    }
    halt_reasons: list[ReasonCode] = []
    if context.kill_switch_active:
        halt_reasons.append(ReasonCode.STATE_MISMATCH)
    if not context.health.all_healthy:
        halt_reasons.extend(context.health.reason_codes or (ReasonCode.DATA_UNHEALTHY,))
    if not context.account_reconciled or not context.position_state.is_reconciled:
        halt_reasons.append(ReasonCode.STATE_MISMATCH)
    if context.daily_net_pnl <= -config.max_daily_loss:
        halt_reasons.append(ReasonCode.DAILY_LOSS_LIMIT)
    if context.daily_drawdown_ratio >= config.max_daily_drawdown:
        halt_reasons.append(ReasonCode.DAILY_DRAWDOWN_LIMIT)
    if context.consecutive_losses >= config.max_consecutive_losses:
        halt_reasons.append(ReasonCode.CONSECUTIVE_LOSS_LIMIT)
    if halt_reasons:
        return RiskOutcome(
            _decision(
                candidate,
                context,
                metadata,
                rates,
                RiskAction.HALT,
                tuple(dict.fromkeys(halt_reasons)),
                observed,
                now,
                approval_ttl,
            ),
            None,
        )
    reject: list[ReasonCode] = []
    if candidate.symbol != context.symbol or metadata.symbol != candidate.symbol:
        reject.append(ReasonCode.INSTRUMENT_UNSUPPORTED)
    if (
        candidate.versions.config_version != context.config_version
        or context.state_version != context.position_state.state_version
        or candidate.cost_rate_estimate.model_version != rates.model_version
    ):
        reject.append(ReasonCode.VERSION_MISMATCH)
    if not metadata.is_linear_quote_margined:
        reject.append(ReasonCode.INSTRUMENT_UNSUPPORTED)
    if metadata.effective_at > now or (
        metadata_max_age is not None and now - metadata.effective_at > metadata_max_age
    ):
        reject.append(ReasonCode.INSTRUMENT_METADATA_STALE)
    if context.daily_trade_count >= config.max_daily_trades:
        reject.append(ReasonCode.DAILY_TRADE_LIMIT)
    if context.open_position_count >= config.max_open_positions:
        reject.append(ReasonCode.MAX_OPEN_POSITIONS)
    if context.cooldown_until is not None and now < context.cooldown_until:
        reject.append(ReasonCode.COOLDOWN_ACTIVE)
    if context.quote.spread_fraction > config.max_allowed_spread:
        reject.append(ReasonCode.SPREAD_TOO_WIDE)
    if max(rates.entry_slippage_rate, rates.stop_slippage_rate) > config.max_slippage:
        reject.append(ReasonCode.SLIPPAGE_TOO_HIGH)
    if reject:
        return RiskOutcome(
            _decision(
                candidate,
                context,
                metadata,
                rates,
                RiskAction.REJECT,
                tuple(dict.fromkeys(reject)),
                observed,
                now,
                approval_ttl,
            ),
            None,
        )
    entry = (
        ceil_to_step(candidate.entry_price, metadata.tick_size)
        if candidate.side is TradeSide.LONG
        else floor_to_step(candidate.entry_price, metadata.tick_size)
    )
    stop = (
        floor_to_step(candidate.stop_price, metadata.tick_size)
        if candidate.side is TradeSide.LONG
        else ceil_to_step(candidate.stop_price, metadata.tick_size)
    )
    targets = tuple(
        Target(
            target.label,
            floor_to_step(target.price, metadata.tick_size)
            if candidate.side is TradeSide.LONG
            else ceil_to_step(target.price, metadata.tick_size),
            target.quantity_fraction,
        )
        for target in candidate.targets
    )
    distance = abs(entry - stop)
    if (
        distance <= ZERO
        or (candidate.side is TradeSide.LONG and stop >= entry)
        or (candidate.side is TradeSide.SHORT and stop <= entry)
    ):
        reject.append(ReasonCode.INVALID_STOP)
    if (
        distance < candidate.reference_atr * config.stop_min_distance_atr
        or distance < metadata.tick_size * config.stop_minimum_tick_multiple
        or distance < (context.quote.ask - context.quote.bid) * config.stop_minimum_spread_multiple
    ):
        reject.append(ReasonCode.STOP_TOO_CLOSE)
    if distance > candidate.reference_atr * config.stop_max_distance_atr:
        reject.append(ReasonCode.STOP_TOO_FAR)
    if (
        any(target.price <= entry for target in targets)
        if candidate.side is TradeSide.LONG
        else any(target.price >= entry for target in targets)
    ):
        reject.append(ReasonCode.TARGET_INVALID)
    remaining_daily = max(ZERO, config.max_daily_loss + context.daily_net_pnl)
    budget = min(context.eligible_equity * config.risk_per_trade, remaining_daily)
    observed["risk_budget"] = budget
    if context.account_equity <= ZERO or context.eligible_equity <= ZERO or budget <= ZERO:
        reject.append(ReasonCode.RISK_BUDGET_INVALID)
    leverage = min(config.target_leverage, config.max_leverage, metadata.maximum_leverage)
    if leverage < ONE:
        reject.append(ReasonCode.LEVERAGE_CAP_EXCEEDED)
    per_contract = _loss_per_contract(entry, stop, metadata.contract_value_base, rates)
    if per_contract <= ZERO:
        reject.append(ReasonCode.NUMERICAL_ERROR)
    if reject:
        return RiskOutcome(
            _decision(
                candidate,
                context,
                metadata,
                rates,
                RiskAction.REJECT,
                tuple(dict.fromkeys(reject)),
                observed,
                now,
                approval_ttl,
            ),
            None,
        )
    risk_quantity = budget / per_contract
    exposure_capacity = max(ZERO, config.max_total_exposure - context.current_notional)
    margin_capacity = context.available_margin * leverage * (ONE - config.margin_buffer_ratio)
    notional_cap = min(
        config.max_position_notional,
        exposure_capacity,
        context.eligible_equity * config.max_leverage,
        margin_capacity,
        metadata.notional(metadata.maximum_order_quantity, entry),
    )
    cap_quantity = notional_cap / (metadata.contract_value_base * entry)
    quantity = floor_to_step(min(risk_quantity, cap_quantity), metadata.lot_size)
    notional = metadata.notional(quantity, entry) if quantity > ZERO else ZERO
    worst_loss = per_contract * quantity
    observed.update({"quantity": quantity, "notional": notional, "worst_case_loss": worst_loss})
    if quantity < metadata.minimum_quantity or notional < metadata.minimum_notional:
        reject.append(ReasonCode.POSITION_SIZE_TOO_SMALL)
    if exposure_capacity < metadata.minimum_notional:
        reject.append(ReasonCode.POSITION_CAP_EXCEEDED)
    if margin_capacity < metadata.minimum_notional:
        reject.append(ReasonCode.INSUFFICIENT_MARGIN)
    if (
        notional > config.max_position_notional
        or context.current_notional + notional > config.max_total_exposure
        or quantity > metadata.maximum_order_quantity
    ):
        reject.append(ReasonCode.POSITION_CAP_EXCEEDED)
    required_margin = notional / leverage if leverage > ZERO else notional
    if required_margin > context.available_margin * (ONE - config.margin_buffer_ratio):
        reject.append(ReasonCode.INSUFFICIENT_MARGIN)
    if worst_loss > budget:
        reject.append(ReasonCode.RISK_BUDGET_EXCEEDED)
    primary_target = targets[0].price
    gross_reward = metadata.contract_value_base * quantity * abs(primary_target - entry)
    entry_fee = notional * rates.entry_fee_rate
    exit_notional = metadata.notional(quantity, primary_target)
    target_fee = exit_notional * rates.target_exit_fee_rate
    reward_cost = (
        entry_fee
        + target_fee
        + notional
        * (rates.entry_slippage_rate + rates.target_slippage_rate + rates.funding_debit_rate)
    )
    net_reward = gross_reward - reward_cost
    expected_rr = net_reward / worst_loss if worst_loss > ZERO else ZERO
    observed["expected_rr"] = expected_rr
    if net_reward <= ZERO or expected_rr < config.minimum_rr:
        reject.append(ReasonCode.RR_TOO_LOW)
    if reject:
        return RiskOutcome(
            _decision(
                candidate,
                context,
                metadata,
                rates,
                RiskAction.REJECT,
                tuple(dict.fromkeys(reject)),
                observed,
                now,
                approval_ttl,
            ),
            None,
        )
    provisional = _decision(
        candidate,
        context,
        metadata,
        rates,
        RiskAction.REJECT,
        (),
        observed,
        now,
        approval_ttl,
    )
    approval = risk_approval_id(provisional.risk_decision_id)
    fee_breakdown = FeeBreakdown(
        entry_fee,
        metadata.notional(quantity, stop) * rates.stop_exit_fee_rate,
        ZERO,
        notional * rates.entry_slippage_rate
        + metadata.notional(quantity, stop) * rates.stop_slippage_rate,
        -(notional * rates.funding_debit_rate),
    )
    payload = (
        candidate.candidate_id,
        entry,
        stop,
        quantity,
        targets,
        budget,
        worst_loss,
        expected_rr,
        leverage,
        context.state_version,
    )
    plan_identifier = approved_plan_id(approval, payload, metadata.version)
    plan = ApprovedTradePlan(
        plan_identifier,
        approval,
        candidate.candidate_id,
        candidate.symbol,
        candidate.side,
        entry,
        stop,
        quantity,
        notional,
        targets,
        budget,
        worst_loss,
        expected_rr,
        leverage,
        fee_breakdown,
        now,
        now + approval_ttl,
        candidate.versions.config_version,
        context.state_version,
        metadata.version,
        rates.model_version,
    )
    decision = _decision(
        candidate,
        context,
        metadata,
        rates,
        RiskAction.APPROVE,
        (),
        observed,
        now,
        approval_ttl,
        approval,
        plan_identifier,
    )
    return RiskOutcome(decision, plan)
