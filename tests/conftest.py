from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from trading_bot.config.loader import load_config
from trading_bot.domain.enums import Timeframe
from trading_bot.domain.market_models import Candle, MarketSnapshot
from trading_bot.domain.value_objects import Quote, VersionSet
from trading_bot.market_data.validation import create_market_snapshot

UTC = UTC


@pytest.fixture
def app_config():
    return load_config(Path("config/base.example.yaml"))


@pytest.fixture
def versions() -> VersionSet:
    return VersionSet("test-code", "0.1.0-test", "test-config", "test-data")


def candle_series(
    timeframe: Timeframe,
    count: int,
    as_of: datetime,
    *,
    step: Decimal = Decimal("0.25"),
) -> tuple[Candle, ...]:
    interval = {
        Timeframe.M5: timedelta(minutes=5),
        Timeframe.M15: timedelta(minutes=15),
        Timeframe.H1: timedelta(hours=1),
    }[timeframe]
    first_open = as_of - interval * count
    candles = []
    for index in range(count):
        open_time = first_open + interval * index
        close_time = open_time + interval
        opening = Decimal("100") + step * Decimal(index)
        close = opening + step / Decimal(2)
        candles.append(
            Candle(
                f"{timeframe.value}-{index}",
                "BTC-USDT-SWAP",
                timeframe,
                open_time,
                close_time,
                close_time,
                close_time,
                opening,
                max(opening, close) + Decimal("1"),
                min(opening, close) - Decimal("1"),
                close,
                Decimal("10") + Decimal(index % 3),
                True,
                "fixture",
                "test-data",
            )
        )
    return tuple(candles)


@pytest.fixture
def market_snapshot(app_config, versions) -> MarketSnapshot:
    as_of = datetime(2026, 1, 2, 12, tzinfo=UTC)
    quote = Quote(
        "BTC-USDT-SWAP",
        "fixture",
        Decimal("162.60"),
        Decimal("162.62"),
        as_of,
        as_of,
    )
    return create_market_snapshot(
        "BTC-USDT-SWAP",
        as_of,
        as_of,
        candle_series(Timeframe.M5, 250, as_of),
        candle_series(Timeframe.M15, 250, as_of),
        candle_series(Timeframe.H1, 250, as_of),
        quote,
        versions,
        app_config.data,
    )
