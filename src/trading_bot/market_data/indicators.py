"""Deterministic Decimal indicator calculations over closed candles."""

from __future__ import annotations

from decimal import Decimal, localcontext
from itertools import pairwise

from trading_bot.config.models import IndicatorConfig
from trading_bot.domain.enums import ReasonCode, Timeframe
from trading_bot.domain.errors import IndicatorCalculationError
from trading_bot.domain.identifiers import deterministic_id
from trading_bot.domain.market_models import Candle, IndicatorSnapshot, MarketSnapshot
from trading_bot.domain.primitives import HUNDRED, ONE, ZERO
from trading_bot.domain.value_objects import IndicatorValues, VersionSet


def _mean(values: tuple[Decimal, ...]) -> Decimal:
    return sum(values, ZERO) / Decimal(len(values))


def _wilder(values: tuple[Decimal, ...], period: int) -> tuple[Decimal | None, ...]:
    result: list[Decimal | None] = [None] * len(values)
    if len(values) < period:
        return tuple(result)
    current = _mean(values[:period])
    result[period - 1] = current
    for index in range(period, len(values)):
        current = (current * Decimal(period - 1) + values[index]) / Decimal(period)
        result[index] = current
    return tuple(result)


def ema_series(values: tuple[Decimal, ...], period: int) -> tuple[Decimal | None, ...]:
    result: list[Decimal | None] = [None] * len(values)
    if len(values) < period:
        return tuple(result)
    current = _mean(values[:period])
    result[period - 1] = current
    alpha = Decimal(2) / Decimal(period + 1)
    for index in range(period, len(values)):
        current = alpha * values[index] + (ONE - alpha) * current
        result[index] = current
    return tuple(result)


def rsi_series(closes: tuple[Decimal, ...], period: int) -> tuple[Decimal | None, ...]:
    result: list[Decimal | None] = [None] * len(closes)
    if len(closes) <= period:
        return tuple(result)
    gains = tuple(max(closes[index] - closes[index - 1], ZERO) for index in range(1, len(closes)))
    losses = tuple(max(closes[index - 1] - closes[index], ZERO) for index in range(1, len(closes)))
    average_gain = _mean(gains[:period])
    average_loss = _mean(losses[:period])

    def value() -> Decimal:
        if average_gain == ZERO and average_loss == ZERO:
            return Decimal(50)
        if average_loss == ZERO:
            return HUNDRED
        if average_gain == ZERO:
            return ZERO
        return HUNDRED - HUNDRED / (ONE + average_gain / average_loss)

    result[period] = value()
    for index in range(period + 1, len(closes)):
        average_gain = (average_gain * Decimal(period - 1) + gains[index - 1]) / Decimal(period)
        average_loss = (average_loss * Decimal(period - 1) + losses[index - 1]) / Decimal(period)
        result[index] = value()
    return tuple(result)


def true_ranges(candles: tuple[Candle, ...]) -> tuple[Decimal, ...]:
    values: list[Decimal] = []
    for index, candle in enumerate(candles):
        if index == 0:
            values.append(candle.high - candle.low)
            continue
        previous_close = candles[index - 1].close
        values.append(
            max(
                candle.high - candle.low,
                abs(candle.high - previous_close),
                abs(candle.low - previous_close),
            )
        )
    return tuple(values)


def atr_series(candles: tuple[Candle, ...], period: int) -> tuple[Decimal | None, ...]:
    return _wilder(true_ranges(candles), period)


def adx_series(candles: tuple[Candle, ...], period: int) -> tuple[Decimal | None, ...]:
    length = len(candles)
    result: list[Decimal | None] = [None] * length
    if length <= period * 2:
        return tuple(result)
    tr = true_ranges(candles)[1:]
    plus_dm: list[Decimal] = []
    minus_dm: list[Decimal] = []
    for previous, current in pairwise(candles):
        up = current.high - previous.high
        down = previous.low - current.low
        plus_dm.append(up if up > down and up > ZERO else ZERO)
        minus_dm.append(down if down > up and down > ZERO else ZERO)
    smooth_tr = _wilder(tr, period)
    smooth_plus = _wilder(tuple(plus_dm), period)
    smooth_minus = _wilder(tuple(minus_dm), period)
    dx: list[Decimal | None] = [None] * len(tr)
    for index in range(period - 1, len(tr)):
        denominator = smooth_tr[index]
        if denominator is None or denominator == ZERO:
            dx[index] = ZERO
            continue
        plus_di = HUNDRED * smooth_plus[index] / denominator  # type: ignore[operator]
        minus_di = HUNDRED * smooth_minus[index] / denominator  # type: ignore[operator]
        di_sum = plus_di + minus_di
        dx[index] = ZERO if di_sum == ZERO else HUNDRED * abs(plus_di - minus_di) / di_sum
    first = tuple(value for value in dx[period - 1 : period * 2 - 1] if value is not None)
    if len(first) != period:
        return tuple(result)
    current_adx = _mean(first)
    result[period * 2 - 1] = current_adx
    for index in range(period * 2 - 1, len(dx)):
        current_dx = dx[index]
        if current_dx is None:
            continue
        current_adx = (current_adx * Decimal(period - 1) + current_dx) / Decimal(period)
        result[index + 1] = current_adx
    return tuple(result)


def percentile_rank(history: tuple[Decimal, ...], value: Decimal) -> Decimal:
    if not history:
        raise IndicatorCalculationError("percentile history is empty")
    below = sum(item < value for item in history)
    equal = sum(item == value for item in history)
    return HUNDRED * (Decimal(below) + Decimal(equal) / Decimal(2)) / Decimal(len(history))


def bollinger_series(
    closes: tuple[Decimal, ...], period: int, multiplier: Decimal
) -> tuple[tuple[Decimal, Decimal, Decimal] | None, ...]:
    result: list[tuple[Decimal, Decimal, Decimal] | None] = [None] * len(closes)
    for index in range(period - 1, len(closes)):
        window = closes[index - period + 1 : index + 1]
        middle = _mean(window)
        variance = sum(((value - middle) ** 2 for value in window), ZERO) / Decimal(period)
        with localcontext() as context:
            context.prec = 34
            deviation = variance.sqrt() * multiplier
        result[index] = (middle + deviation, middle, middle - deviation)
    return tuple(result)


def _required(value: Decimal | None, name: str) -> Decimal:
    if value is None or not value.is_finite():
        raise IndicatorCalculationError(f"{name} is not ready")
    return value


def calculate_values(candles: tuple[Candle, ...], config: IndicatorConfig) -> IndicatorValues:
    closes = tuple(candle.close for candle in candles)
    volumes = tuple(candle.volume for candle in candles)
    ema20, ema50, ema200 = (ema_series(closes, period) for period in config.ema_periods)
    atrs = atr_series(candles, config.atr_period)
    rsis = rsi_series(closes, config.rsi_period)
    adxs = adx_series(candles, config.adx_period)
    bands = bollinger_series(closes, config.bollinger_period, config.bollinger_stddev_multiplier)
    atr = _required(atrs[-1], "ATR")
    if atr == ZERO or closes[-1] == ZERO:
        raise IndicatorCalculationError("ATR and close must be positive")
    lookback = config.ema_slope_lookback_bars
    rsi_lookback = config.rsi_slope_lookback_bars
    ema_values = (ema20, ema50, ema200)
    slopes = tuple(
        (_required(series[-1], "EMA") - _required(series[-1 - lookback], "EMA slope")) / atr
        for series in ema_values
    )
    rsi = _required(rsis[-1], "RSI")
    rsi_slope = rsi - _required(rsis[-1 - rsi_lookback], "RSI slope")
    current_band = bands[-1]
    if current_band is None:
        raise IndicatorCalculationError("Bollinger bands are not ready")
    upper, middle, lower = current_band
    width = (upper - lower) / middle
    atr_history = tuple(
        value for value in atrs[-config.atr_percentile_lookback_bars :] if value is not None
    )
    widths = tuple(
        (band[0] - band[2]) / band[1]
        for band in bands[-config.bollinger_percentile_lookback_bars :]
        if band is not None
    )
    volume_mean = _mean(volumes[-config.volume_lookback_bars :])
    if volume_mean == ZERO:
        raise IndicatorCalculationError("volume mean is zero")
    return IndicatorValues(
        _required(ema20[-1], "EMA20"),
        _required(ema50[-1], "EMA50"),
        _required(ema200[-1], "EMA200"),
        slopes[0],
        slopes[1],
        slopes[2],
        rsi,
        rsi_slope,
        atr,
        atr / closes[-1],
        percentile_rank(atr_history, atr),
        _required(adxs[-1], "ADX"),
        upper,
        middle,
        lower,
        width,
        percentile_rank(widths, width),
        volume_mean,
        volumes[-1] / volume_mean,
    )


def calculate_indicators(
    snapshot: MarketSnapshot, config: IndicatorConfig, versions: VersionSet
) -> IndicatorSnapshot:
    series = {
        Timeframe.M5: snapshot.candles_5m,
        Timeframe.M15: snapshot.candles_15m,
        Timeframe.H1: snapshot.candles_1h,
    }
    needs = _indicator_required_bars(config)
    missing = tuple(
        f"{timeframe.value}: need {needs[timeframe]}, got {len(candles)}"
        for timeframe, candles in series.items()
        if len(candles) < needs[timeframe]
    )
    identifier = deterministic_id("indicator-snapshot", snapshot.snapshot_id, versions)
    if missing:
        return IndicatorSnapshot(
            identifier,
            snapshot.snapshot_id,
            snapshot.symbol,
            snapshot.as_of,
            {},
            False,
            missing,
            (ReasonCode.INDICATOR_NOT_READY,),
            versions,
        )
    try:
        values = {
            timeframe: calculate_values(candles, config) for timeframe, candles in series.items()
        }
    except IndicatorCalculationError as error:
        return IndicatorSnapshot(
            identifier,
            snapshot.snapshot_id,
            snapshot.symbol,
            snapshot.as_of,
            {},
            False,
            (str(error),),
            (ReasonCode.INDICATOR_NOT_READY, ReasonCode.INDICATOR_INVALID),
            versions,
        )
    return IndicatorSnapshot(
        identifier,
        snapshot.snapshot_id,
        snapshot.symbol,
        snapshot.as_of,
        values,
        True,
        (),
        (),
        versions,
    )


def _indicator_required_bars(config: IndicatorConfig) -> dict[Timeframe, int]:
    need = max(
        200 + config.ema_stabilization_bars + config.ema_slope_lookback_bars,
        config.rsi_period + 1 + config.rsi_slope_lookback_bars,
        config.atr_period + config.atr_percentile_lookback_bars,
        2 * config.adx_period + 1,
        config.bollinger_period + config.bollinger_percentile_lookback_bars - 1,
        config.volume_lookback_bars,
    )
    return dict.fromkeys(Timeframe, need)
