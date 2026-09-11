from dataclasses import replace
from decimal import Decimal

from trading_bot.domain.enums import Timeframe
from trading_bot.domain.value_objects import VersionSet
from trading_bot.market_data.indicators import calculate_indicators, percentile_rank, rsi_series


def test_rsi_constant_series_is_neutral():
    result = rsi_series(tuple(Decimal("100") for _ in range(20)), 14)
    assert result[-1] == Decimal("50")


def test_percentile_rank_uses_inclusive_empirical_cdf_for_ties():
    values = (Decimal("1"), Decimal("2"), Decimal("2"), Decimal("3"))
    assert percentile_rank(values, Decimal("2")) == Decimal("75")


def test_percentile_rank_boundaries_and_repeated_values():
    values = tuple(Decimal(value) for value in (1, 2, 2, 3))
    assert percentile_rank(values, Decimal("1")) == Decimal("25")
    assert percentile_rank(values, Decimal("3")) == Decimal("100")
    assert percentile_rank((Decimal("2"),) * 4, Decimal("2")) == Decimal("100")
    assert percentile_rank((Decimal("7"),), Decimal("7")) == Decimal("100")
    assert percentile_rank(values, Decimal("2.5")) == Decimal("75")


def test_indicator_snapshot_is_ready(market_snapshot, app_config, versions):
    result = calculate_indicators(
        market_snapshot, app_config.indicators, app_config.calculation, versions
    )
    assert result.is_ready
    assert set(result.values_by_timeframe) == set(Timeframe)
    assert result.values_by_timeframe[Timeframe.M15].atr > 0


def test_calculation_precision_is_applied_and_scoped(market_snapshot, app_config, versions):
    low_policy = replace(app_config.calculation, decimal_precision=28)
    high_policy = replace(app_config.calculation, decimal_precision=50)
    low_versions = VersionSet(
        versions.code_version,
        versions.strategy_version,
        "config-precision-28",
        versions.data_version,
    )
    high_versions = VersionSet(
        versions.code_version,
        versions.strategy_version,
        "config-precision-50",
        versions.data_version,
    )
    low = calculate_indicators(market_snapshot, app_config.indicators, low_policy, low_versions)
    high = calculate_indicators(market_snapshot, app_config.indicators, high_policy, high_versions)
    assert (
        low.values_by_timeframe[Timeframe.M15].ema20
        != high.values_by_timeframe[Timeframe.M15].ema20
    )
    assert (
        calculate_indicators(market_snapshot, app_config.indicators, low_policy, low_versions)
        == low
    )
