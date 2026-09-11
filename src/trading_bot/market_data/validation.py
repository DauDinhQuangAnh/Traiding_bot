"""Closed-candle identity, freshness and snapshot construction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from trading_bot.config.models import DataConfig
from trading_bot.domain.enums import ReasonCode, Timeframe
from trading_bot.domain.errors import DomainValidationError, MarketDataValidationError
from trading_bot.domain.identifiers import deterministic_id, evaluation_id
from trading_bot.domain.market_models import Candle, MarketSnapshot
from trading_bot.domain.value_objects import Quote, VersionSet


@dataclass(frozen=True, slots=True)
class SnapshotBuildResult:
    """Explicit success/failure boundary; a failure never carries a partial snapshot."""

    snapshot: MarketSnapshot | None
    reason_codes: tuple[ReasonCode, ...]
    detail: str | None

    @property
    def succeeded(self) -> bool:
        return self.snapshot is not None


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
    result = build_market_snapshot(
        symbol,
        as_of,
        created_at,
        candles_5m,
        candles_15m,
        candles_1h,
        quote,
        versions,
        config,
    )
    if result.snapshot is None:
        codes = ", ".join(code.value for code in result.reason_codes)
        raise MarketDataValidationError(f"snapshot build failed ({codes}): {result.detail}")
    return result.snapshot


def build_market_snapshot(
    symbol: str,
    as_of: datetime,
    created_at: datetime,
    candles_5m: tuple[Candle, ...],
    candles_15m: tuple[Candle, ...],
    candles_1h: tuple[Candle, ...],
    quote: Quote | None,
    versions: VersionSet,
    config: DataConfig,
) -> SnapshotBuildResult:
    series = {Timeframe.M5: candles_5m, Timeframe.M15: candles_15m, Timeframe.H1: candles_1h}
    reasons: list[ReasonCode] = []
    for timeframe, candles in series.items():
        if not candles:
            reasons.append(ReasonCode.DATA_MISSING)
            continue
        if as_of - candles[-1].close_time > config.candle_freshness[timeframe]:
            reasons.append(ReasonCode.DATA_STALE)
    if quote is not None and as_of - quote.event_time > config.quote_freshness:
        reasons.append(ReasonCode.DATA_STALE)
    if reasons:
        return SnapshotBuildResult(None, tuple(dict.fromkeys(reasons)), "missing or stale data")
    evaluation = evaluation_id(symbol, as_of, versions.strategy_version, versions.config_version)
    snapshot_id = deterministic_id(
        "market-snapshot",
        evaluation,
        tuple(candle.candle_id for values in series.values() for candle in values),
        quote,
        versions.data_version,
    )
    try:
        snapshot = MarketSnapshot(
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
    except DomainValidationError as error:
        detail = str(error)
        code = (
            ReasonCode.DATA_GAP
            if "gap" in detail
            else ReasonCode.DATA_DUPLICATE
            if "duplicate" in detail
            else ReasonCode.DATA_OUT_OF_ORDER
            if "ordered" in detail
            else ReasonCode.TIMEFRAME_UNSYNCED
            if any(token in detail for token in ("identity", "trigger", "children", "H1"))
            else ReasonCode.CANDLE_INVALID
        )
        return SnapshotBuildResult(None, (code,), detail)
    return SnapshotBuildResult(snapshot, (), None)


def point_in_time_candles(candles: tuple[Candle, ...], as_of: datetime) -> tuple[Candle, ...]:
    """Repository-style cutoff used by replay to prevent future-data leakage."""
    return tuple(candle for candle in candles if candle.close_time <= as_of)
