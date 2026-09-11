from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tests.conftest import candle_series

from trading_bot.application.pipeline import evaluate_market, replay_market_sequence
from trading_bot.domain.enums import (
    BreakoutState,
    RangeLocation,
    Timeframe,
    TradeDecision,
)
from trading_bot.domain.market_models import RangeContext
from trading_bot.domain.primitives import canonical_json
from trading_bot.domain.value_objects import CostRateEstimate, Quote
from trading_bot.market_data.validation import create_market_snapshot


def test_offline_pipeline_replay_is_byte_deterministic(market_snapshot, app_config, versions):
    costs = CostRateEstimate(
        Decimal("0.0005"),
        Decimal("0.0007"),
        Decimal("0.7") / Decimal("1000"),
        Decimal("0.0003"),
        Decimal("0.0005"),
        Decimal("0.0005"),
        Decimal("0.0001"),
        "test-costs",
    )
    first = evaluate_market(market_snapshot, app_config, versions, costs)
    second = evaluate_market(market_snapshot, app_config, versions, costs)
    assert canonical_json(first) == canonical_json(second)
    assert first.decision.decision is TradeDecision.NO_TRADE


def _market(as_of, close, index, app_config, versions):
    m5 = candle_series(Timeframe.M5, 250, as_of, step=Decimal("0"))
    m15 = candle_series(Timeframe.M15, 250, as_of, step=Decimal("0"))
    h1_cutoff = as_of.replace(minute=0, second=0, microsecond=0)
    h1 = candle_series(Timeframe.H1, 250, h1_cutoff, step=Decimal("0"))
    trigger = replace(
        m15[-1],
        candle_id=f"trigger-{index}",
        open=Decimal("101") if index == 5 else Decimal("100"),
        high=max(Decimal("102"), close),
        low=Decimal("100.8") if index == 5 else Decimal("99"),
        close=close,
    )
    child = replace(
        m5[-1],
        candle_id=f"child-{index}",
        open=Decimal("100.8"),
        high=Decimal("101.6"),
        low=Decimal("100.7"),
        close=Decimal("101.3"),
    )
    quote = Quote("BTC-USDT-SWAP", "fixture", close, close, as_of, as_of)
    return create_market_snapshot(
        "BTC-USDT-SWAP",
        as_of,
        as_of,
        (*m5[:-1], child),
        (*m15[:-1], trigger),
        h1,
        quote,
        versions,
        app_config.data,
    )


def test_multi_candle_replay_carries_range_and_breakout_state_byte_exactly(app_config, versions):
    start = datetime(2026, 1, 2, 12, tzinfo=UTC)
    closes = tuple(
        Decimal(value) for value in ("100", "101.5", "101.4", "101.3", "101.2", "101.05")
    )
    markets = tuple(
        _market(start + timedelta(minutes=15 * index), close, index, app_config, versions)
        for index, close in enumerate(closes)
    )
    initial = RangeContext(
        "persisted-range",
        "BTC-USDT-SWAP",
        "support",
        "resistance",
        Decimal("99"),
        Decimal("101"),
        Decimal("100"),
        Decimal("2"),
        Decimal("100"),
        Decimal("1"),
        Decimal("0.5"),
        start - timedelta(hours=1),
        start - timedelta(minutes=15),
        start - timedelta(minutes=15),
        3,
        4,
        4,
        0,
        RangeLocation.MIDDLE,
        BreakoutState.NONE,
        None,
        None,
        None,
        None,
        (),
        versions.config_version,
        versions.data_version,
    )
    replay_config = replace(
        app_config,
        regime=replace(
            app_config.regime,
            required_confirmations=1,
            sideway_candidate_threshold=Decimal("0.2"),
            minimum_confidence=Decimal("0.2"),
            high_volatility_candidate_threshold=Decimal("0.9"),
        ),
    )
    costs = CostRateEstimate(*(Decimal("0") for _ in range(7)), model_version="replay")
    first = replay_market_sequence(markets, replay_config, versions, costs, initial_range=initial)
    second = replay_market_sequence(markets, replay_config, versions, costs, initial_range=initial)
    assert canonical_json(first) == canonical_json(second)
    states = tuple(result.levels.range_context.breakout_state for result in first)
    assert states == (
        BreakoutState.NONE,
        BreakoutState.BREAKOUT_DETECTED,
        BreakoutState.WAIT_CONFIRMATION,
        BreakoutState.WAIT_CONFIRMATION,
        BreakoutState.WAIT_RETEST,
        BreakoutState.RETEST_VALIDATED,
    )
    ages = tuple(result.levels.range_context.range_age_bars for result in first)
    assert ages == tuple(sorted(ages))
    assert all(result.regime is not None and result.strategy is not None for result in first)
    assert [result.candidate and result.candidate.candidate_id for result in first] == [
        result.candidate and result.candidate.candidate_id for result in second
    ]
