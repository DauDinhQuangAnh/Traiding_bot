from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trading_bot.domain.enums import (
    BreakoutDirection,
    BreakoutState,
    RangeLocation,
    ReasonCode,
    Timeframe,
)
from trading_bot.domain.market_models import Candle, RangeContext
from trading_bot.levels.engine import advance_breakout, carry_range_context

D = Decimal
START = datetime(2026, 1, 1, tzinfo=UTC)


def context() -> RangeContext:
    return RangeContext(
        "range-1",
        "BTC-USDT-SWAP",
        "support-1",
        "resistance-1",
        D("90"),
        D("110"),
        D("100"),
        D("20"),
        D("100"),
        D("10"),
        D("0.5"),
        START,
        START,
        START,
        0,
        2,
        2,
        0,
        RangeLocation.MIDDLE,
        BreakoutState.NONE,
        None,
        None,
        None,
        None,
        (),
        "config-v1",
        "data-v1",
    )


def candle(index: int, opening: str, high: str, low: str, close: str) -> Candle:
    open_time = START + timedelta(minutes=15 * index)
    close_time = open_time + timedelta(minutes=15)
    return Candle(
        f"candle-{index}",
        "BTC-USDT-SWAP",
        Timeframe.M15,
        open_time,
        close_time,
        close_time,
        close_time,
        D(opening),
        D(high),
        D(low),
        D(close),
        D("10"),
        True,
        "fixture",
        "data-v1",
    )


def test_breakout_requires_separate_detect_confirm_and_retest_events(app_config):
    current = advance_breakout(
        context(),
        candle(0, "109", "112", "108", "111"),
        D("2"),
        app_config.levels,
        app_config.calculation,
    )
    assert current.breakout_state is BreakoutState.BREAKOUT_DETECTED
    assert current.breakout_direction is BreakoutDirection.UP

    current = advance_breakout(
        current,
        candle(1, "111", "112", "110", "111"),
        D("2"),
        app_config.levels,
        app_config.calculation,
    )
    assert current.breakout_state is BreakoutState.WAIT_CONFIRMATION

    for index in (2, 3):
        current = advance_breakout(
            current,
            candle(index, "111", "112", "110.5", "111"),
            D("2"),
            app_config.levels,
            app_config.calculation,
        )
    assert current.breakout_state is BreakoutState.WAIT_RETEST

    current = advance_breakout(
        current,
        candle(4, "109.9", "111", "109.8", "110.2"),
        D("2"),
        app_config.levels,
        app_config.calculation,
        bullish_confirmation=True,
    )
    assert current.breakout_state is BreakoutState.RETEST_VALIDATED


def _to_wait_retest(app_config) -> RangeContext:
    current = context()
    bars = (
        ("109", "112", "108", "111"),
        ("111", "112", "110", "111"),
        ("111", "112", "110.5", "111"),
        ("111", "112", "110.5", "111"),
    )
    for index, values in enumerate(bars):
        current = advance_breakout(
            current,
            candle(index, *values),
            D("2"),
            app_config.levels,
            app_config.calculation,
        )
    assert current.breakout_state is BreakoutState.WAIT_RETEST
    return current


def test_failed_hold_invalidates_breakout(app_config):
    current = context()
    for index, close in enumerate(("111", "111", "109")):
        current = advance_breakout(
            current,
            candle(index, close, "112", "108", close),
            D("2"),
            app_config.levels,
            app_config.calculation,
        )
    assert current.breakout_state is BreakoutState.INVALIDATED
    assert current.reason_codes == (ReasonCode.BREAKOUT_INVALIDATED,)


def test_invalid_and_expired_retests(app_config):
    waiting = _to_wait_retest(app_config)
    invalid = advance_breakout(
        waiting,
        candle(4, "110", "111", "109.9", "109.9"),
        D("2"),
        app_config.levels,
        app_config.calculation,
        bullish_confirmation=False,
    )
    assert invalid.breakout_state is BreakoutState.INVALIDATED
    assert invalid.reason_codes == (ReasonCode.RETEST_INVALIDATED,)

    expired = advance_breakout(
        waiting,
        candle(12, "112", "113", "111.5", "112"),
        D("2"),
        app_config.levels,
        app_config.calculation,
    )
    assert expired.breakout_state is BreakoutState.EXPIRED
    assert expired.reason_codes == (ReasonCode.RETEST_EXPIRED,)
    reset = advance_breakout(
        expired,
        candle(13, "100", "101", "99", "100"),
        D("2"),
        app_config.levels,
        app_config.calculation,
    )
    assert reset.breakout_state is BreakoutState.NONE
    assert reset.breakout_direction is None


def test_range_stale_and_identity_change_reset(app_config):
    stale = advance_breakout(
        context(),
        candle(21, "100", "101", "99", "100"),
        D("2"),
        app_config.levels,
        app_config.calculation,
    )
    assert stale.reason_codes == (ReasonCode.RANGE_STALE,)

    prior = advance_breakout(
        context(),
        candle(0, "109", "112", "108", "111"),
        D("2"),
        app_config.levels,
        app_config.calculation,
    )
    next_candle = candle(1, "111", "112", "110", "111")
    fresh_identity = replace(
        context(),
        range_id="range-2",
        reference_close=next_candle.close,
        position_in_range=(next_candle.close - D("90")) / D("20"),
        as_of=next_candle.close_time,
    )
    carried = carry_range_context(
        fresh_identity,
        prior,
        next_candle,
        D("2"),
        app_config.levels,
        app_config.calculation,
    )
    assert carried.breakout_state is BreakoutState.NONE
    assert carried.range_id == "range-2"
    for changes in ({"config_version": "config-v2"}, {"data_version": "data-v2"}):
        reset = carry_range_context(
            replace(fresh_identity, range_id="range-1", **changes),
            prior,
            next_candle,
            D("2"),
            app_config.levels,
            app_config.calculation,
        )
        assert reset.breakout_state is BreakoutState.NONE
