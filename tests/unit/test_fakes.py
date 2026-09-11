from datetime import timedelta
from decimal import Decimal

from trading_bot.domain.enums import HealthStatus, Timeframe
from trading_bot.domain.value_objects import CostRateEstimate
from trading_bot.infrastructure.fakes import FrozenClock, InMemoryMarketDataProvider, StaticFeeModel


def test_frozen_clock_and_market_provider(market_snapshot):
    clock = FrozenClock(market_snapshot.as_of)
    clock.advance(timedelta(seconds=5))
    assert clock.now_utc() == market_snapshot.as_of + timedelta(seconds=5)
    assert clock.monotonic() == timedelta(seconds=5)

    provider = InMemoryMarketDataProvider(
        candles={(market_snapshot.symbol, Timeframe.M15): market_snapshot.candles_15m},
        quotes={market_snapshot.symbol: market_snapshot.quote},
        observed_at=market_snapshot.as_of,
    )
    fetched = provider.fetch_candles(
        market_snapshot.symbol,
        Timeframe.M15,
        market_snapshot.candles_15m[-2].open_time,
        market_snapshot.as_of,
        2,
    )
    assert len(fetched) == 2
    assert provider.health().status is HealthStatus.HEALTHY


def test_static_fee_model_returns_exact_versioned_rates(market_snapshot):
    rates = CostRateEstimate(
        Decimal("0.001"),
        Decimal("0.001"),
        Decimal("0.001"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        "fixture",
    )
    model = StaticFeeModel(rates)
    assert model.estimate(market_snapshot.symbol, market_snapshot.as_of) is rates
