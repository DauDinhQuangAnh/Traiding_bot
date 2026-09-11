from trading_bot.application.state_machines import transition_bot, transition_trade
from trading_bot.domain.enums import (
    BotEvent,
    BotState,
    ReasonCode,
    TradeLifecycleEvent,
    TradeLifecycleState,
)


def test_global_bot_transition_and_invalid_pair():
    accepted = transition_bot(BotState.STARTING, BotEvent.CONFIG_VALIDATED)
    assert accepted.accepted and accepted.current is BotState.SYNCING
    invalid = transition_bot(BotState.STARTING, BotEvent.CANDLE_CLOSED)
    assert not invalid.accepted and invalid.current is BotState.STARTING
    assert invalid.reason_codes == (ReasonCode.INVALID_STATE_TRANSITION,)


def test_critical_health_halts_from_any_state_idempotently():
    assert (
        transition_bot(BotState.MANAGING_POSITION, BotEvent.HEALTH_CRITICAL).current
        is BotState.HALTED
    )
    assert transition_bot(BotState.HALTED, BotEvent.HEALTH_CRITICAL).current is BotState.HALTED


def test_trade_happy_path_prefix():
    first = transition_trade(
        TradeLifecycleState.CANDIDATE_CREATED, TradeLifecycleEvent.RISK_REVIEW_STARTED
    )
    second = transition_trade(first.current, TradeLifecycleEvent.RISK_APPROVED)
    third = transition_trade(second.current, TradeLifecycleEvent.ORDER_INTENT_PERSISTED)
    assert third.current is TradeLifecycleState.SUBMITTING
