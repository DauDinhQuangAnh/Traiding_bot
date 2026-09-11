from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tests.conftest import candle_series
from trading_bot.application.pipeline import (
    SnapshotFailureEvaluation,
    evaluate_market,
    evaluate_snapshot_inputs,
)
from trading_bot.domain.enums import ReasonCode, Timeframe, TradeDecision
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.market_models import Candle
from trading_bot.domain.primitives import canonical_json
from trading_bot.domain.value_objects import CostRateEstimate, Quote
from trading_bot.market_data.validation import (
    build_market_snapshot,
    point_in_time_candles,
)

D = Decimal


def _costs() -> CostRateEstimate:
    return CostRateEstimate(*(D("0") for _ in range(7)), model_version="cost-v1")


def test_candle_requires_utc_boundary_alignment():
    opened = datetime(2026, 1, 1, 10, 2, tzinfo=UTC)
    with pytest.raises(DomainValidationError, match="aligned"):
        Candle(
            "misaligned",
            "BTC-USDT-SWAP",
            Timeframe.M15,
            opened,
            opened + timedelta(minutes=15),
            opened + timedelta(minutes=15),
            opened + timedelta(minutes=15),
            D("100"),
            D("101"),
            D("99"),
            D("100"),
            D("1"),
            True,
            "fixture",
            "data-v1",
        )


def test_canonical_candle_rejects_open_status(market_snapshot):
    with pytest.raises(DomainValidationError, match="closed"):
        replace(market_snapshot.candles_15m[-1], is_closed=False)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda values: values[:5] + values[6:], ReasonCode.DATA_GAP),
        (lambda values: (*values, values[-1]), ReasonCode.DATA_DUPLICATE),
        (lambda values: (*values[:-2], values[-1], values[-2]), ReasonCode.DATA_OUT_OF_ORDER),
    ],
)
def test_snapshot_rejects_gap_duplicate_and_ordering(
    market_snapshot, app_config, versions, mutation, expected
):
    result = build_market_snapshot(
        market_snapshot.symbol,
        market_snapshot.as_of,
        market_snapshot.created_at,
        market_snapshot.candles_5m,
        mutation(market_snapshot.candles_15m),
        market_snapshot.candles_1h,
        market_snapshot.quote,
        versions,
        app_config.data,
    )
    assert result.snapshot is None
    assert result.reason_codes == (expected,)


def test_snapshot_rejects_child_context_quote_and_symbol_mismatch(
    market_snapshot, app_config, versions
):
    cases = [
        {
            "candles_5m": market_snapshot.candles_5m[-2:],
            "expected": ReasonCode.TIMEFRAME_UNSYNCED,
        },
        {
            "candles_1h": candle_series(
                Timeframe.H1, 250, market_snapshot.as_of - timedelta(hours=1)
            ),
            "expected": ReasonCode.TIMEFRAME_UNSYNCED,
        },
        {
            "quote": Quote(
                market_snapshot.symbol,
                "fixture",
                D("100"),
                D("101"),
                market_snapshot.as_of + timedelta(seconds=1),
                market_snapshot.as_of + timedelta(seconds=1),
            ),
            "expected": ReasonCode.CANDLE_INVALID,
        },
        {
            "candles_15m": tuple(
                replace(candle, symbol="OTHER") for candle in market_snapshot.candles_15m
            ),
            "expected": ReasonCode.TIMEFRAME_UNSYNCED,
        },
    ]
    defaults = {
        "candles_5m": market_snapshot.candles_5m,
        "candles_15m": market_snapshot.candles_15m,
        "candles_1h": market_snapshot.candles_1h,
        "quote": market_snapshot.quote,
    }
    for case in cases:
        expected = case.pop("expected")
        inputs = defaults | case
        result = build_market_snapshot(
            market_snapshot.symbol,
            market_snapshot.as_of,
            market_snapshot.created_at,
            inputs["candles_5m"],
            inputs["candles_15m"],
            inputs["candles_1h"],
            inputs["quote"],
            versions,
            app_config.data,
        )
        assert result.snapshot is None
        assert result.reason_codes == (expected,)


def test_staleness_uses_canonical_as_of_and_quote_sla(market_snapshot, app_config, versions):
    replay_build = build_market_snapshot(
        market_snapshot.symbol,
        market_snapshot.as_of,
        market_snapshot.created_at + timedelta(days=30),
        market_snapshot.candles_5m,
        market_snapshot.candles_15m,
        market_snapshot.candles_1h,
        market_snapshot.quote,
        versions,
        app_config.data,
    )
    assert replay_build.succeeded

    stale_quote = replace(
        market_snapshot.quote,
        event_time=market_snapshot.as_of
        - app_config.data.quote_freshness
        - timedelta(microseconds=1),
    )
    stale_build = build_market_snapshot(
        market_snapshot.symbol,
        market_snapshot.as_of,
        market_snapshot.created_at,
        market_snapshot.candles_5m,
        market_snapshot.candles_15m,
        market_snapshot.candles_1h,
        stale_quote,
        versions,
        app_config.data,
    )
    assert stale_build.reason_codes == (ReasonCode.DATA_STALE,)


def test_future_data_is_rejected_and_point_in_time_output_is_unchanged(
    market_snapshot, app_config, versions
):
    future_as_of = market_snapshot.as_of + timedelta(minutes=15)
    future = candle_series(Timeframe.M15, 1, future_as_of)[0]
    rejected = build_market_snapshot(
        market_snapshot.symbol,
        market_snapshot.as_of,
        market_snapshot.created_at,
        market_snapshot.candles_5m,
        (*market_snapshot.candles_15m, future),
        market_snapshot.candles_1h,
        market_snapshot.quote,
        versions,
        app_config.data,
    )
    assert rejected.snapshot is None
    assert rejected.reason_codes == (ReasonCode.CANDLE_INVALID,)
    filtered = point_in_time_candles((*market_snapshot.candles_15m, future), market_snapshot.as_of)
    assert filtered == market_snapshot.candles_15m
    rebuilt = build_market_snapshot(
        market_snapshot.symbol,
        market_snapshot.as_of,
        market_snapshot.created_at,
        market_snapshot.candles_5m,
        filtered,
        market_snapshot.candles_1h,
        market_snapshot.quote,
        versions,
        app_config.data,
    )
    assert rebuilt.snapshot is not None
    baseline = evaluate_market(market_snapshot, app_config, versions, _costs())
    replayed = evaluate_market(rebuilt.snapshot, app_config, versions, _costs())
    assert canonical_json(replayed) == canonical_json(baseline)


def test_snapshot_failure_becomes_canonical_no_trade(market_snapshot, app_config, versions):
    result = evaluate_snapshot_inputs(
        market_snapshot.symbol,
        market_snapshot.as_of,
        market_snapshot.created_at,
        market_snapshot.candles_5m,
        market_snapshot.candles_15m[:-1],
        market_snapshot.candles_1h,
        market_snapshot.quote,
        app_config,
        versions,
        _costs(),
    )
    assert isinstance(result, SnapshotFailureEvaluation)
    assert result.build_result.snapshot is None
    assert result.decision.decision is TradeDecision.NO_TRADE
    assert result.decision.reason_codes
