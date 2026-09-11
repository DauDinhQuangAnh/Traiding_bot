from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from trading_bot.backtest.engine import BacktestEngine
from trading_bot.backtest.funding import (
    FixedFundingRateProvider,
    FundingRateEvent,
    HistoricalFundingRateProvider,
    funding_cash_flow,
)
from trading_bot.backtest.metrics import calculate_metrics, drawdown_summary, performance_summary
from trading_bot.backtest.models import BacktestTradeResult, EquityPoint
from trading_bot.domain.enums import ExitReason, FundingMode, MarketRegime, SetupType, TradeSide
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.value_objects import Target, VersionSet

from .helpers import START, candidate, candle, engine_inputs, evaluation

D = Decimal


def _trade(index: int, pnl: str) -> BacktestTradeResult:
    opened = START + timedelta(hours=index)
    net = D(pnl)
    risk = D("100")
    return BacktestTradeResult(
        f"trade-{index}",
        f"trade-{index}",
        f"plan-{index}",
        TradeSide.LONG if index % 2 == 0 else TradeSide.SHORT,
        SetupType.TREND_PULLBACK,
        MarketRegime.TREND_UP if index % 2 == 0 else MarketRegime.TREND_DOWN,
        D("80"),
        D("10"),
        opened,
        D("100"),
        D("1"),
        D("95"),
        (Target("TP", D("110"), D("1")),),
        opened + timedelta(minutes=30),
        ExitReason.TAKE_PROFIT if net > 0 else ExitReason.STOP_LOSS,
        (f"fill-{index}",),
        net,
        D("0"),
        D("0"),
        D("0"),
        D("0"),
        D("0"),
        net,
        risk,
        net / risk,
        net / risk,
        timedelta(minutes=30),
        VersionSet("code", "strategy", "config", "data"),
    )


def test_known_performance_summary_and_consecutive_sequence():
    trades = tuple(_trade(index, pnl) for index, pnl in enumerate(("100", "-50", "40", "-20")))
    summary = performance_summary(trades)
    assert summary.net_pnl == D("70")
    assert summary.profit_factor == D("2")
    assert summary.win_rate == D("0.5")
    assert summary.expectancy == D("17.5")


def test_consecutive_loss_golden_sequence():
    trades = tuple(
        _trade(index, pnl) for index, pnl in enumerate(("1", "-1", "-1", "-1", "1", "-1"))
    )
    metrics = calculate_metrics(
        D("100"),
        D("98"),
        trades,
        (),
        evaluations=6,
        no_trade_evaluations=0,
        candidates=6,
        risk_rejections=0,
        risk_halts=0,
        approvals=6,
        expired_orders=0,
        exposure_bars=6,
        total_bars=6,
    )
    assert metrics.max_consecutive_losses == 3
    assert metrics.current_consecutive_losses == 1


def test_drawdown_golden_uses_equity_curve_not_closed_trades():
    values = ("100", "110", "105", "120", "90", "100", "130")
    points = tuple(
        EquityPoint(
            START + timedelta(minutes=index * 5),
            D(value),
            D("0"),
            D(value),
            D("0"),
            D(value),
            max(D(item) for item in values[: index + 1]),
            max(D(item) for item in values[: index + 1]) - D(value),
            (max(D(item) for item in values[: index + 1]) - D(value))
            / max(D(item) for item in values[: index + 1]),
        )
        for index, value in enumerate(values)
    )
    result = drawdown_summary(points)
    assert result.maximum_drawdown == D("30")
    assert result.maximum_drawdown_ratio == D("0.25")
    assert result.peak_time == START + timedelta(minutes=15)
    assert result.trough_time == START + timedelta(minutes=20)
    assert result.recovery_time == START + timedelta(minutes=30)


@pytest.mark.parametrize(
    ("side", "rate", "expected"),
    [
        (TradeSide.LONG, "0.01", "-10"),
        (TradeSide.SHORT, "0.01", "10"),
        (TradeSide.LONG, "-0.01", "10"),
        (TradeSide.SHORT, "-0.01", "-10"),
    ],
)
def test_funding_direction(side, rate, expected):
    assert funding_cash_flow(side, D("1000"), D(rate)) == D(expected)


def test_funding_timing_and_historical_series_fail_closed():
    provider = FixedFundingRateProvider(D("0.001"), timedelta(hours=8), "funding-v1")
    events = provider.rates_between(START, START + timedelta(hours=24))
    assert tuple(item.timestamp.hour for item in events) == (16, 0, 8)
    historical = HistoricalFundingRateProvider(
        (FundingRateEvent(events[0].timestamp, D("0.001")),),
        timedelta(hours=8),
        "series-v1",
        "algorithm-v1",
    )
    with pytest.raises(DomainValidationError, match="missing"):
        historical.validate_range(START, START + timedelta(hours=24))


def test_open_long_crossing_funding_boundary_is_charged(app_config):
    start = datetime(2026, 1, 1, 15, 40, tzinfo=START.tzinfo)
    bars = tuple(
        candle(start + timedelta(minutes=5 * index), "100", "101", "99", "100")
        for index in range(5)
    )
    backtest_config = replace(
        app_config.backtest,
        funding_mode=FundingMode.FIXED_ASSUMPTION,
        fixed_funding_rate=D("0.001"),
    )
    provider = FixedFundingRateProvider(
        D("0.001"), backtest_config.funding_interval, backtest_config.funding_algorithm_version
    )
    spec, configured, instrument, costs, _ = engine_inputs(
        app_config,
        bars[0].open_time,
        bars[-1].close_time,
        config=backtest_config,
        funding_provider=provider,
    )
    result = BacktestEngine(spec, configured, instrument, costs, provider).run(
        bars,
        (evaluation(candidate(bars[0].close_time, spec.versions, costs, identity="funding-long")),),
    )
    assert len(result.funding) == 1
    assert result.funding[0].event_time.hour == 16
    assert result.funding[0].cash_flow < D("0")
    assert result.trades[0].funding_cash_flow == result.funding[0].cash_flow


def test_no_position_has_no_funding_cash_flow(app_config):
    start = datetime(2026, 1, 1, 15, 55, tzinfo=START.tzinfo)
    bars = (
        candle(start, "100", "101", "99", "100"),
        candle(start + timedelta(minutes=5), "100", "101", "99", "100"),
    )
    backtest_config = replace(
        app_config.backtest,
        funding_mode=FundingMode.FIXED_ASSUMPTION,
        fixed_funding_rate=D("0.001"),
    )
    provider = FixedFundingRateProvider(
        D("0.001"), backtest_config.funding_interval, backtest_config.funding_algorithm_version
    )
    spec, configured, instrument, costs, _ = engine_inputs(
        app_config,
        bars[0].open_time,
        bars[-1].close_time,
        config=backtest_config,
        funding_provider=provider,
    )
    result = BacktestEngine(spec, configured, instrument, costs, provider).run(bars, ())
    assert result.funding == ()
