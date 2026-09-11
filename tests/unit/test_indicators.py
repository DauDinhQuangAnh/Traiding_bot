from decimal import Decimal

from trading_bot.domain.enums import Timeframe
from trading_bot.market_data.indicators import calculate_indicators, percentile_rank, rsi_series


def test_rsi_constant_series_is_neutral():
    result = rsi_series(tuple(Decimal("100") for _ in range(20)), 14)
    assert result[-1] == Decimal("50")


def test_percentile_rank_uses_midrank_for_ties():
    values = (Decimal("1"), Decimal("2"), Decimal("2"), Decimal("3"))
    assert percentile_rank(values, Decimal("2")) == Decimal("50")


def test_indicator_snapshot_is_ready(market_snapshot, app_config, versions):
    result = calculate_indicators(market_snapshot, app_config.indicators, versions)
    assert result.is_ready
    assert set(result.values_by_timeframe) == set(Timeframe)
    assert result.values_by_timeframe[Timeframe.M15].atr > 0
