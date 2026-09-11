from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trading_bot.domain.enums import (
    BreakoutDirection,
    BreakoutState,
    RangeLocation,
    Timeframe,
)
from trading_bot.domain.market_models import Candle, RangeContext
from trading_bot.levels.engine import advance_breakout

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
        context(), candle(0, "109", "112", "108", "111"), D("2"), app_config.levels
    )
    assert current.breakout_state is BreakoutState.BREAKOUT_DETECTED
    assert current.breakout_direction is BreakoutDirection.UP

    current = advance_breakout(
        current, candle(1, "111", "112", "110", "111"), D("2"), app_config.levels
    )
    assert current.breakout_state is BreakoutState.WAIT_CONFIRMATION

    for index in (2, 3):
        current = advance_breakout(
            current,
            candle(index, "111", "112", "110.5", "111"),
            D("2"),
            app_config.levels,
        )
    assert current.breakout_state is BreakoutState.WAIT_RETEST

    current = advance_breakout(
        current,
        candle(4, "109.9", "111", "109.8", "110.2"),
        D("2"),
        app_config.levels,
        bullish_confirmation=True,
    )
    assert current.breakout_state is BreakoutState.RETEST_VALIDATED
