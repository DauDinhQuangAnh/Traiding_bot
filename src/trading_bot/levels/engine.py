"""Deterministic swing, structure, level, range and breakout calculations."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

from trading_bot.config.models import LevelConfig
from trading_bot.domain.enums import (
    BreakoutDirection,
    BreakoutState,
    LevelKind,
    LevelMethod,
    RangeLocation,
    ReasonCode,
    StructurePointKind,
    StructureTrend,
    Timeframe,
)
from trading_bot.domain.identifiers import deterministic_id
from trading_bot.domain.market_models import Candle, Level, LevelSet, MarketSnapshot, RangeContext
from trading_bot.domain.primitives import ONE, ZERO
from trading_bot.domain.value_objects import MarketStructure, StructurePoint


def detect_swings(candles: tuple[Candle, ...], left: int, right: int) -> tuple[StructurePoint, ...]:
    points: list[StructurePoint] = []
    for index in range(left, len(candles) - right):
        candle = candles[index]
        before = candles[index - left : index]
        after = candles[index + 1 : index + right + 1]
        confirmed_at = after[-1].close_time
        if all(candle.high > item.high for item in before + after):
            points.append(
                StructurePoint(
                    StructurePointKind.SWING_HIGH,
                    candle.high,
                    candle.close_time,
                    candle.candle_id,
                    confirmed_at,
                )
            )
        if all(candle.low < item.low for item in before + after):
            points.append(
                StructurePoint(
                    StructurePointKind.SWING_LOW,
                    candle.low,
                    candle.close_time,
                    candle.candle_id,
                    confirmed_at,
                )
            )
    return tuple(sorted(points, key=lambda point: (point.time, point.kind.value)))


def market_structure(
    points: tuple[StructurePoint, ...], atr: Decimal, tolerance_atr: Decimal, as_of: datetime
) -> MarketStructure:
    highs = [point for point in points if point.kind is StructurePointKind.SWING_HIGH]
    lows = [point for point in points if point.kind is StructurePointKind.SWING_LOW]
    classified = list(points)
    trend = StructureTrend.UNDETERMINED
    if len(highs) >= 2 and len(lows) >= 2:
        tolerance = atr * tolerance_atr
        high_delta = highs[-1].price - highs[-2].price
        low_delta = lows[-1].price - lows[-2].price
        high_kind = (
            StructurePointKind.HH
            if high_delta > tolerance
            else StructurePointKind.LH
            if high_delta < -tolerance
            else StructurePointKind.SWING_HIGH
        )
        low_kind = (
            StructurePointKind.HL
            if low_delta > tolerance
            else StructurePointKind.LL
            if low_delta < -tolerance
            else StructurePointKind.SWING_LOW
        )
        classified = [
            replace(point, kind=high_kind)
            if point == highs[-1]
            else replace(point, kind=low_kind)
            if point == lows[-1]
            else point
            for point in points
        ]
        if high_kind is StructurePointKind.HH and low_kind is StructurePointKind.HL:
            trend = StructureTrend.BULLISH
        elif high_kind is StructurePointKind.LH and low_kind is StructurePointKind.LL:
            trend = StructureTrend.BEARISH
        else:
            trend = StructureTrend.MIXED
    return MarketStructure(trend, tuple(classified), as_of, ())


def _clusters(
    points: tuple[StructurePoint, ...], distance: Decimal
) -> tuple[tuple[StructurePoint, ...], ...]:
    groups: list[list[StructurePoint]] = []
    for point in sorted(points, key=lambda item: item.price):
        if not groups or point.price - groups[-1][-1].price > distance:
            groups.append([point])
        else:
            groups[-1].append(point)
    return tuple(tuple(group) for group in groups)


def _level(
    group: tuple[StructurePoint, ...],
    kind: LevelKind,
    symbol: str,
    atr: Decimal,
    config: LevelConfig,
    as_of: datetime,
) -> Level:
    price = sum((point.price for point in group), ZERO) / Decimal(len(group))
    width = atr * config.zone_half_width_atr
    strength = min(ONE, Decimal(len(group)) / Decimal(config.full_strength_touches))
    return Level(
        deterministic_id("level", symbol, kind, tuple(point.candle_id for point in group), price),
        symbol,
        kind,
        price,
        price - width,
        price + width,
        strength,
        LevelMethod.SWING_CLUSTER,
        min(point.time for point in group),
        max(point.confirmed_at for point in group),
        max(point.time for point in group),
        as_of,
        len(group),
        tuple(point.candle_id for point in group),
        None,
    )


def _location(position: Decimal, config: LevelConfig) -> RangeLocation:
    if (
        position < -config.outside_tolerance_fraction
        or position > ONE + config.outside_tolerance_fraction
    ):
        return RangeLocation.OUTSIDE_RANGE
    if position <= config.support_zone_max_fraction:
        return RangeLocation.NEAR_SUPPORT
    if position >= config.resistance_zone_min_fraction:
        return RangeLocation.NEAR_RESISTANCE
    return RangeLocation.MIDDLE


def build_level_set(
    snapshot: MarketSnapshot, atr: Decimal, config: LevelConfig, config_version: str
) -> LevelSet:
    source = snapshot.candles_15m[-config.lookback_bars[Timeframe.M15] :]
    points = detect_swings(source, config.swing_left_bars, config.swing_right_bars)
    structure = market_structure(
        points, atr, config.structure_comparison_tolerance_atr, snapshot.as_of
    )
    high_points = tuple(
        point
        for point in points
        if point.kind
        in {StructurePointKind.SWING_HIGH, StructurePointKind.HH, StructurePointKind.LH}
    )
    low_points = tuple(
        point
        for point in points
        if point.kind
        in {StructurePointKind.SWING_LOW, StructurePointKind.HL, StructurePointKind.LL}
    )
    candidates = [
        *(
            _level(group, LevelKind.SUPPORT, snapshot.symbol, atr, config, snapshot.as_of)
            for group in _clusters(low_points, atr * config.level_merge_distance_atr)
            if len(group) >= config.minimum_touches
        ),
        *(
            _level(group, LevelKind.RESISTANCE, snapshot.symbol, atr, config, snapshot.as_of)
            for group in _clusters(high_points, atr * config.level_merge_distance_atr)
            if len(group) >= config.minimum_touches
        ),
    ]
    active = [level for level in candidates if level.strength >= config.minimum_level_strength]
    close = snapshot.candles_15m[-1].close
    supports = tuple(
        sorted((level for level in active if level.price < close), key=lambda item: item.price)
    )
    resistances = tuple(
        sorted((level for level in active if level.price > close), key=lambda item: item.price)
    )
    range_context = None
    if supports and resistances:
        support, resistance = supports[-1], resistances[0]
        width = resistance.price - support.price
        if width / atr >= config.minimum_range_width_atr:
            position = (close - support.price) / width
            range_context = RangeContext(
                deterministic_id("range", support.level_id, resistance.level_id, config_version),
                snapshot.symbol,
                support.level_id,
                resistance.level_id,
                support.price,
                resistance.price,
                close,
                width,
                (support.price + resistance.price) / Decimal(2),
                width / atr,
                position,
                min(support.first_observed_at, resistance.first_observed_at),
                snapshot.as_of,
                snapshot.as_of,
                0,
                support.test_count,
                resistance.test_count,
                0,
                _location(position, config),
                BreakoutState.NONE,
                None,
                None,
                None,
                None,
                (),
                config_version,
                snapshot.data_version,
            )
    return LevelSet(
        deterministic_id("level-set", snapshot.snapshot_id, config_version),
        snapshot.snapshot_id,
        snapshot.symbol,
        supports,
        resistances,
        tuple(candidates),
        range_context,
        structure,
        snapshot.as_of,
        config_version,
        snapshot.data_version,
    )


def advance_breakout(
    context: RangeContext,
    candle: Candle,
    atr: Decimal,
    config: LevelConfig,
    *,
    bullish_confirmation: bool = False,
    bearish_confirmation: bool = False,
) -> RangeContext:
    if candle.timeframe is not Timeframe.M15 or not candle.is_closed:
        return replace(
            context,
            as_of=candle.close_time,
            reference_close=candle.close,
            position_in_range=(candle.close - context.support) / context.range_width,
            reason_codes=(ReasonCode.CANDLE_INVALID,),
        )
    close, now = candle.close, candle.close_time
    upper_detect = context.resistance + atr * config.breakout_buffer_atr
    lower_detect = context.support - atr * config.breakout_buffer_atr
    state, direction = context.breakout_state, context.breakout_direction
    count, detected, expires = (
        context.breakout_confirmation_count,
        context.breakout_detected_at,
        context.expires_at,
    )
    if state is BreakoutState.NONE and (close > upper_detect or close < lower_detect):
        state = BreakoutState.BREAKOUT_DETECTED
        direction = BreakoutDirection.UP if close > upper_detect else BreakoutDirection.DOWN
        count, detected = 0, now
    elif state is BreakoutState.BREAKOUT_DETECTED:
        state = BreakoutState.WAIT_CONFIRMATION
    elif state is BreakoutState.WAIT_CONFIRMATION and direction is not None:
        boundary = context.resistance if direction is BreakoutDirection.UP else context.support
        held = (
            close >= boundary - atr * config.breakout_hold_tolerance_atr
            if direction is BreakoutDirection.UP
            else close <= boundary + atr * config.breakout_hold_tolerance_atr
        )
        if not held:
            state = BreakoutState.INVALIDATED
        else:
            count += 1
            if count >= config.breakout_confirmation_bars:
                state = BreakoutState.WAIT_RETEST
                expires = now + timedelta(minutes=15 * config.retest_expiry_bars)
    elif state is BreakoutState.WAIT_RETEST and direction is not None:
        boundary = context.resistance if direction is BreakoutDirection.UP else context.support
        if expires is not None and now > expires:
            state = BreakoutState.EXPIRED
        else:
            tolerance = atr * config.retest_tolerance_atr
            if direction is BreakoutDirection.UP:
                touched = candle.low <= boundary + tolerance
                held = close >= boundary and bullish_confirmation
            else:
                touched = candle.high >= boundary - tolerance
                held = close <= boundary and bearish_confirmation
            if touched:
                state = BreakoutState.RETEST_VALIDATED if held else BreakoutState.INVALIDATED
    position = (close - context.support) / context.range_width
    return replace(
        context,
        reference_close=close,
        position_in_range=position,
        as_of=now,
        last_validated_at=now,
        range_age_bars=context.range_age_bars + 1,
        current_location=_location(position, config),
        breakout_state=state,
        breakout_direction=direction,
        breakout_confirmation_count=count,
        breakout_detected_at=detected,
        state_updated_at=now,
        expires_at=expires,
        reason_codes=(ReasonCode.RANGE_STALE,)
        if context.range_age_bars + 1 > config.maximum_range_stale_bars
        else (),
    )
