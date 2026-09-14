from datetime import timedelta
from decimal import Decimal

from trading_bot.domain.enums import MarketRegime, SetupType, TradeSide
from trading_bot.validation.metrics import project_validation_metrics

from .helpers import CALCULATION, START, backtest_result, equity_point, evaluation_range, trade

D = Decimal


def test_warmup_trade_is_excluded_from_partition_metrics():
    result = backtest_result(
        (
            trade(0, "100", opened=START - timedelta(hours=1)),
            trade(1, "-20", opened=START + timedelta(hours=1)),
        )
    )

    metrics = project_validation_metrics(
        result,
        evaluation_range(0, 1),
        minimum_sample_size=2,
        calculation=CALCULATION,
    )

    assert metrics.trade_count == 1
    assert metrics.net_pnl == D("-20")
    assert metrics.insufficient_sample


def test_grouped_metrics_always_show_sample_count():
    trades = (
        trade(0, "100", side=TradeSide.LONG, regime=MarketRegime.TREND_UP),
        trade(
            1,
            "-50",
            side=TradeSide.SHORT,
            regime=MarketRegime.TREND_DOWN,
            setup=SetupType.BREAKOUT_RETEST,
        ),
    )
    metrics = project_validation_metrics(
        backtest_result(trades),
        evaluation_range(0, 1),
        minimum_sample_size=2,
        calculation=CALCULATION,
    )

    groups = {(item.dimension, item.value): item for item in metrics.groups}
    assert groups[("side", "LONG")].trade_count == 1
    assert groups[("side", "SHORT")].trade_count == 1
    assert groups[("regime", "TREND_UP")].insufficient_sample
    assert groups[("setup", "BREAKOUT_RETEST")].trade_count == 1
    assert groups[("side", "LONG")].insufficient_sample
    assert groups[("regime", "SIDEWAY")].trade_count == 0
    assert groups[("regime", "SIDEWAY")].insufficient_sample
    assert groups[("setup", "SIDEWAY_MEAN_REVERSION")].trade_count == 0


def test_zero_trade_metrics_keep_undefined_ratios_unavailable():
    metrics = project_validation_metrics(
        backtest_result(()),
        evaluation_range(0, 1),
        minimum_sample_size=1,
        calculation=CALCULATION,
    )

    assert metrics.trade_count == 0
    assert metrics.profit_factor is None
    assert metrics.expectancy_r is None
    assert metrics.win_rate is None
    assert metrics.net_pnl == D("0")


def test_one_winning_trade_has_undefined_profit_factor():
    metrics = project_validation_metrics(
        backtest_result((trade(0, "10"),)),
        evaluation_range(0, 1),
        minimum_sample_size=1,
        calculation=CALCULATION,
    )

    assert metrics.trade_count == 1
    assert metrics.profit_factor is None
    assert metrics.expectancy_r == D("0.1")


def test_no_winning_trades_have_zero_profit_factor():
    metrics = project_validation_metrics(
        backtest_result((trade(0, "-10"), trade(1, "-20"))),
        evaluation_range(0, 1),
        minimum_sample_size=1,
        calculation=CALCULATION,
    )

    assert metrics.profit_factor == D("0")


def test_partition_drawdown_and_exposure_use_only_official_window():
    points = (
        equity_point(-1, "50", exposed=True),
        equity_point(0, "100", exposed=True),
        equity_point(1, "90", exposed=False),
    )
    metrics = project_validation_metrics(
        backtest_result((), points),
        evaluation_range(0, 1),
        minimum_sample_size=1,
        calculation=CALCULATION,
    )

    assert metrics.maximum_drawdown == D("10")
    assert metrics.exposure == D("0.5")


def test_half_open_partition_boundary_has_single_trade_owner():
    at_start = trade(0, "10", opened=START)
    at_end = trade(1, "20", opened=START + timedelta(days=1))

    first = project_validation_metrics(
        backtest_result((at_start, at_end)),
        evaluation_range(0, 1),
        minimum_sample_size=1,
        calculation=CALCULATION,
    )
    second = project_validation_metrics(
        backtest_result((at_start, at_end)),
        evaluation_range(1, 2),
        minimum_sample_size=1,
        calculation=CALCULATION,
    )

    assert first.trade_count == 1 and first.net_pnl == D("10")
    assert second.trade_count == 1 and second.net_pnl == D("20")


def test_all_breakeven_metrics_are_zero_only_when_mathematically_defined():
    metrics = project_validation_metrics(
        backtest_result((trade(0, "0"), trade(1, "0"))),
        evaluation_range(0, 1),
        minimum_sample_size=1,
        calculation=CALCULATION,
    )

    assert metrics.net_pnl == D("0")
    assert metrics.expectancy_r == D("0")
    assert metrics.profit_factor is None
