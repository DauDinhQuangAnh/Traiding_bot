"""Pure global and per-trade transition tables from the PHASE 2 contract."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar

from trading_bot.domain.enums import (
    BotEvent,
    BotState,
    ReasonCode,
    TradeLifecycleEvent,
    TradeLifecycleState,
)

_State = TypeVar("_State", bound=StrEnum)


@dataclass(frozen=True, slots=True)
class TransitionResult(Generic[_State]):
    previous: _State
    current: _State
    accepted: bool
    reason_codes: tuple[ReasonCode, ...]


BOT_TRANSITIONS: dict[tuple[BotState, BotEvent], BotState] = {
    (BotState.STARTING, BotEvent.CONFIG_VALIDATED): BotState.SYNCING,
    (BotState.STARTING, BotEvent.STARTUP_VALIDATION_FAILED): BotState.HALTED,
    (BotState.SYNCING, BotEvent.SYNC_COMPLETED): BotState.OBSERVING,
    (BotState.SYNCING, BotEvent.SYNC_FAILED): BotState.HALTED,
    (BotState.OBSERVING, BotEvent.CANDLE_CLOSED): BotState.EVALUATING,
    (BotState.OBSERVING, BotEvent.LOSS_COOLDOWN_STARTED): BotState.COOLDOWN,
    (BotState.OBSERVING, BotEvent.HEALTH_CRITICAL): BotState.HALTED,
    (BotState.EVALUATING, BotEvent.NO_TRADE): BotState.OBSERVING,
    (BotState.EVALUATING, BotEvent.RISK_REJECTED): BotState.OBSERVING,
    (BotState.EVALUATING, BotEvent.RISK_APPROVED): BotState.SUBMITTING,
    (BotState.EVALUATING, BotEvent.RISK_HALT): BotState.HALTED,
    (BotState.SUBMITTING, BotEvent.ORDER_ACKNOWLEDGED): BotState.PENDING_ENTRY,
    (BotState.SUBMITTING, BotEvent.ORDER_REJECTED): BotState.OBSERVING,
    (BotState.SUBMITTING, BotEvent.SUBMIT_OUTCOME_UNKNOWN): BotState.RECOVERING,
    (BotState.PENDING_ENTRY, BotEvent.ENTRY_CANCELED_UNFILLED): BotState.OBSERVING,
    (BotState.PENDING_ENTRY, BotEvent.ENTRY_FILLED_PROTECTED): BotState.MANAGING_POSITION,
    (BotState.PENDING_ENTRY, BotEvent.PARTIAL_FILL_OR_PROTECTION_UNKNOWN): BotState.RECOVERING,
    (BotState.PENDING_ENTRY, BotEvent.PROTECTION_FAILED): BotState.HALTED,
    (BotState.MANAGING_POSITION, BotEvent.EXIT_TRIGGERED): BotState.EXITING,
    (BotState.MANAGING_POSITION, BotEvent.STATE_UNCERTAIN): BotState.RECOVERING,
    (BotState.MANAGING_POSITION, BotEvent.PROTECTION_FAILED): BotState.HALTED,
    (BotState.EXITING, BotEvent.POSITION_CLOSED): BotState.OBSERVING,
    (BotState.EXITING, BotEvent.EXIT_OUTCOME_UNKNOWN): BotState.RECOVERING,
    (BotState.RECOVERING, BotEvent.RECONCILED_FLAT): BotState.OBSERVING,
    (BotState.RECOVERING, BotEvent.RECONCILED_PROTECTED_POSITION): BotState.MANAGING_POSITION,
    (BotState.RECOVERING, BotEvent.RECOVERY_FAILED): BotState.HALTED,
    (BotState.COOLDOWN, BotEvent.COOLDOWN_EXPIRED): BotState.OBSERVING,
    (BotState.COOLDOWN, BotEvent.HEALTH_CRITICAL): BotState.HALTED,
    (BotState.HALTED, BotEvent.RISK_REDUCING_ACTION): BotState.HALTED,
    (BotState.HALTED, BotEvent.OPERATOR_RESET_REQUESTED): BotState.SYNCING,
}

TRADE_TRANSITIONS: dict[tuple[TradeLifecycleState, TradeLifecycleEvent], TradeLifecycleState] = {
    (
        TradeLifecycleState.CANDIDATE_CREATED,
        TradeLifecycleEvent.RISK_REVIEW_STARTED,
    ): TradeLifecycleState.RISK_REVIEW,
    (
        TradeLifecycleState.RISK_REVIEW,
        TradeLifecycleEvent.RISK_REJECTED,
    ): TradeLifecycleState.REJECTED,
    (
        TradeLifecycleState.RISK_REVIEW,
        TradeLifecycleEvent.RISK_APPROVED,
    ): TradeLifecycleState.APPROVED,
    (TradeLifecycleState.RISK_REVIEW, TradeLifecycleEvent.RISK_HALT): TradeLifecycleState.HALTED,
    (
        TradeLifecycleState.APPROVED,
        TradeLifecycleEvent.ORDER_INTENT_PERSISTED,
    ): TradeLifecycleState.SUBMITTING,
    (
        TradeLifecycleState.SUBMITTING,
        TradeLifecycleEvent.ORDER_ACKNOWLEDGED,
    ): TradeLifecycleState.PENDING_ENTRY,
    (
        TradeLifecycleState.SUBMITTING,
        TradeLifecycleEvent.ORDER_REJECTED,
    ): TradeLifecycleState.REJECTED,
    (
        TradeLifecycleState.SUBMITTING,
        TradeLifecycleEvent.SUBMIT_OUTCOME_UNKNOWN,
    ): TradeLifecycleState.RECOVERY,
    (
        TradeLifecycleState.PENDING_ENTRY,
        TradeLifecycleEvent.ENTRY_CANCELED_UNFILLED,
    ): TradeLifecycleState.REJECTED,
    (
        TradeLifecycleState.PENDING_ENTRY,
        TradeLifecycleEvent.ENTRY_FILLED_PROTECTED,
    ): TradeLifecycleState.OPEN,
    (
        TradeLifecycleState.PENDING_ENTRY,
        TradeLifecycleEvent.PARTIAL_FILL,
    ): TradeLifecycleState.RECOVERY,
    (
        TradeLifecycleState.PENDING_ENTRY,
        TradeLifecycleEvent.TAKE_PROFIT_FAILED,
    ): TradeLifecycleState.RECOVERY,
    (TradeLifecycleState.OPEN, TradeLifecycleEvent.EXIT_TRIGGERED): TradeLifecycleState.CLOSING,
    (TradeLifecycleState.OPEN, TradeLifecycleEvent.STATE_UNCERTAIN): TradeLifecycleState.RECOVERY,
    (TradeLifecycleState.OPEN, TradeLifecycleEvent.PROTECTION_FAILED): TradeLifecycleState.HALTED,
    (TradeLifecycleState.CLOSING, TradeLifecycleEvent.POSITION_CLOSED): TradeLifecycleState.CLOSED,
    (
        TradeLifecycleState.CLOSING,
        TradeLifecycleEvent.EXIT_OUTCOME_UNKNOWN,
    ): TradeLifecycleState.RECOVERY,
    (
        TradeLifecycleState.RECOVERY,
        TradeLifecycleEvent.RECONCILED_NO_FILL,
    ): TradeLifecycleState.REJECTED,
    (
        TradeLifecycleState.RECOVERY,
        TradeLifecycleEvent.RECONCILED_PENDING_ORDER,
    ): TradeLifecycleState.PENDING_ENTRY,
    (
        TradeLifecycleState.RECOVERY,
        TradeLifecycleEvent.RECONCILED_PROTECTED_POSITION,
    ): TradeLifecycleState.OPEN,
    (
        TradeLifecycleState.RECOVERY,
        TradeLifecycleEvent.RECONCILED_CLOSED,
    ): TradeLifecycleState.CLOSED,
    (TradeLifecycleState.RECOVERY, TradeLifecycleEvent.RECOVERY_FAILED): TradeLifecycleState.HALTED,
    (TradeLifecycleState.HALTED, TradeLifecycleEvent.POSITION_CLOSED): TradeLifecycleState.CLOSED,
}


def transition_bot(
    current: BotState, event: BotEvent, *, guard_passed: bool = True
) -> TransitionResult[BotState]:
    if event is BotEvent.HEALTH_CRITICAL:
        return TransitionResult(current, BotState.HALTED, True, ())
    next_state = BOT_TRANSITIONS.get((current, event)) if guard_passed else None
    if next_state is None:
        return TransitionResult(current, current, False, (ReasonCode.INVALID_STATE_TRANSITION,))
    return TransitionResult(current, next_state, True, ())


def transition_trade(
    current: TradeLifecycleState,
    event: TradeLifecycleEvent,
    *,
    guard_passed: bool = True,
) -> TransitionResult[TradeLifecycleState]:
    next_state = TRADE_TRANSITIONS.get((current, event)) if guard_passed else None
    if next_state is None:
        return TransitionResult(current, current, False, (ReasonCode.INVALID_STATE_TRANSITION,))
    return TransitionResult(current, next_state, True, ())
