"""Closed-candle identity, freshness and snapshot construction."""

from __future__ import annotations

from datetime import datetime

from trading_bot.config.models import DataConfig
from trading_bot.domain.enums import ReasonCode, Timeframe
from trading_bot.domain.errors import MarketDataValidationError
from trading_bot.domain.identifiers import deterministic_id, evaluation_id
from trading_bot.domain.market_models import Candle, MarketSnapshot
from trading_bot.domain.value_objects import Quote, VersionSet


def candle_identity(
    source: str,
    symbol: str,
    timeframe: Timeframe,
    open_time: datetime,
    data_version: str,
) -> str:
    return deterministic_id("candle", source, symbol, timeframe, open_time, data_version)


def create_market_snapshot(
    symbol: str,
    as_of: datetime,
    created_at: datetime,
    candles_5m: tuple[Candle, ...],
    candles_15m: tuple[Candle, ...],
    candles_1h: tuple[Candle, ...],
    quote: Quote | None,
    versions: VersionSet,
    config: DataConfig,
) -> MarketSnapshot:
    series = {Timeframe.M5: candles_5m, Timeframe.M15: candles_15m, Timeframe.H1: candles_1h}
    reasons: list[ReasonCode] = []
    for timeframe, candles in series.items():
        if not candles:
            raise MarketDataValidationError(f"missing {timeframe.value} candles")
        if created_at - candles[-1].close_time > config.candle_freshness[timeframe]:
            reasons.append(ReasonCode.DATA_STALE)
    if quote is not None and created_at - quote.event_time > config.quote_freshness:
        reasons.append(ReasonCode.DATA_STALE)
    if reasons:
        raise MarketDataValidationError("stale market data cannot form a snapshot")
    evaluation = evaluation_id(symbol, as_of, versions.strategy_version, versions.config_version)
    snapshot_id = deterministic_id(
        "market-snapshot",
        evaluation,
        tuple(candle.candle_id for values in series.values() for candle in values),
        quote,
        versions.data_version,
    )
    return MarketSnapshot(
        snapshot_id,
        evaluation,
        symbol,
        as_of,
        created_at,
        as_of,
        candles_5m,
        candles_15m,
        candles_1h,
        quote,
        versions.data_version,
        (),
    )
