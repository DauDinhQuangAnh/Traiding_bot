"""Lossless normalization from raw historical provenance to canonical candles."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trading_bot.config.models import HistoricalConfig
from trading_bot.domain.enums import (
    NormalizationStatus,
    ReasonCode,
    TimestampConvention,
    TimestampUnit,
)
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.market_models import Candle
from trading_bot.domain.primitives import decimal_value, require_utc
from trading_bot.historical.models import HistoricalNormalizationResult, RawHistoricalRecord
from trading_bot.market_data.validation import candle_identity

_INTERVALS = {
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
}
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _timestamp(value: str, unit: TimestampUnit) -> datetime:
    if unit is TimestampUnit.ISO8601:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise DomainValidationError("historical ISO8601 timestamp requires timezone")
        normalized = parsed.astimezone(UTC)
        require_utc(normalized, "historical timestamp")
        return normalized
    amount = decimal_value(value.strip())
    if unit is TimestampUnit.UNIX_MILLISECONDS:
        amount /= Decimal("1000")
    microseconds = amount * Decimal("1000000")
    if microseconds != microseconds.to_integral_value():
        raise DomainValidationError("historical timestamp exceeds microsecond precision")
    return _EPOCH + timedelta(microseconds=int(microseconds))


def normalize_record(
    raw: RawHistoricalRecord,
    config: HistoricalConfig,
    data_version: str,
) -> HistoricalNormalizationResult:
    try:
        symbol = config.symbol_mapping.get(raw.raw_symbol.strip())
        if symbol is None:
            raise DomainValidationError(f"unsupported historical symbol: {raw.raw_symbol}")
        timeframe = config.timeframe_mapping.get(raw.raw_timeframe.strip())
        if timeframe is None:
            raise DomainValidationError(f"unsupported historical timeframe: {raw.raw_timeframe}")
        if raw.raw_close_status.strip() not in config.closed_values:
            raise DomainValidationError("historical candle is not explicitly closed")
        timestamp = _timestamp(raw.raw_timestamp, config.timestamp_unit)
        interval = _INTERVALS[timeframe.value]
        if config.timestamp_convention is TimestampConvention.OPEN_TIME:
            open_time, close_time = timestamp, timestamp + interval
        else:
            open_time, close_time = timestamp - interval, timestamp
        prices = tuple(
            decimal_value(value.strip())
            for value in (raw.raw_open, raw.raw_high, raw.raw_low, raw.raw_close, raw.raw_volume)
        )
        candle = Candle(
            candle_identity(raw.source, symbol, timeframe, open_time, data_version),
            symbol,
            timeframe,
            open_time,
            close_time,
            close_time,
            close_time,
            prices[0],
            prices[1],
            prices[2],
            prices[3],
            prices[4],
            True,
            raw.source,
            data_version,
        )
    except (ValueError, ArithmeticError) as error:
        return HistoricalNormalizationResult(
            raw.raw_record_id,
            NormalizationStatus.REJECTED,
            None,
            (ReasonCode.CANDLE_INVALID,),
            str(error),
        )
    return HistoricalNormalizationResult(
        raw.raw_record_id,
        NormalizationStatus.ACCEPTED,
        candle,
        (),
        None,
    )
