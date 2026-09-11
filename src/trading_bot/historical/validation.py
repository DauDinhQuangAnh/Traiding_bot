"""Deterministic deduplication, gap, and cross-timeframe validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from itertools import pairwise

from trading_bot.domain.enums import ReasonCode, Timeframe
from trading_bot.domain.market_models import Candle
from trading_bot.historical.models import Gap

_INTERVALS = {
    Timeframe.M5: timedelta(minutes=5),
    Timeframe.M15: timedelta(minutes=15),
    Timeframe.H1: timedelta(hours=1),
}


@dataclass(frozen=True, slots=True)
class DeduplicationResult:
    candles: tuple[Candle, ...]
    exact_duplicate_count: int
    conflicting_duplicate_count: int
    out_of_order_count: int
    reason_codes: tuple[ReasonCode, ...]


@dataclass(frozen=True, slots=True)
class CrossTimeframeValidationResult:
    is_consistent: bool
    reason_codes: tuple[ReasonCode, ...]
    detail: str | None


def _key(candle: Candle) -> tuple[str, str, Timeframe, object]:
    return candle.source, candle.symbol, candle.timeframe, candle.open_time


def _payload(candle: Candle) -> tuple[object, ...]:
    return (
        candle.close_time,
        candle.event_time,
        candle.open,
        candle.high,
        candle.low,
        candle.close,
        candle.volume,
        candle.is_closed,
    )


def deduplicate_and_sort(candles: tuple[Candle, ...]) -> DeduplicationResult:
    seen: dict[tuple[str, str, Timeframe, object], Candle] = {}
    exact = conflicts = disorder = 0
    maximum_open = None
    for candle in candles:
        if maximum_open is not None and candle.open_time < maximum_open:
            disorder += 1
        maximum_open = (
            candle.open_time if maximum_open is None else max(maximum_open, candle.open_time)
        )
        key = _key(candle)
        prior = seen.get(key)
        if prior is None:
            seen[key] = candle
        elif _payload(prior) == _payload(candle):
            exact += 1
        else:
            conflicts += 1
    reasons: list[ReasonCode] = []
    if exact:
        reasons.append(ReasonCode.DATA_DUPLICATE)
    if conflicts:
        reasons.append(ReasonCode.DATA_CONFLICT)
    if disorder:
        reasons.append(ReasonCode.DATA_OUT_OF_ORDER)
    return DeduplicationResult(
        tuple(sorted(seen.values(), key=lambda item: item.open_time)),
        exact,
        conflicts,
        disorder,
        tuple(reasons),
    )


def detect_gaps(candles: tuple[Candle, ...]) -> tuple[Gap, ...]:
    if len(candles) < 2:
        return ()
    interval = _INTERVALS[candles[0].timeframe]
    gaps: list[Gap] = []
    for previous, current in pairwise(candles):
        difference = current.open_time - previous.open_time
        if difference > interval:
            gaps.append(
                Gap(
                    previous.symbol,
                    previous.timeframe,
                    previous.open_time + interval,
                    previous.open_time,
                    current.open_time,
                    int(difference / interval) - 1,
                )
            )
    return tuple(gaps)


def validate_cross_timeframe(
    children: tuple[Candle, ...], parents: tuple[Candle, ...]
) -> CrossTimeframeValidationResult:
    if not children or not parents:
        return CrossTimeframeValidationResult(
            False, (ReasonCode.DATA_MISSING,), "cross-timeframe series is empty"
        )
    child_interval = _INTERVALS[children[0].timeframe]
    parent_interval = _INTERVALS[parents[0].timeframe]
    if parent_interval <= child_interval or parent_interval % child_interval:
        return CrossTimeframeValidationResult(
            False, (ReasonCode.TIMEFRAME_UNSYNCED,), "unsupported timeframe relationship"
        )
    expected_count = parent_interval // child_interval
    children_by_open = {candle.open_time: candle for candle in children}
    for parent in parents:
        group = tuple(
            children_by_open.get(parent.open_time + child_interval * index)
            for index in range(expected_count)
        )
        if any(candle is None for candle in group):
            return CrossTimeframeValidationResult(
                False, (ReasonCode.TIMEFRAME_UNSYNCED,), "parent lacks aligned children"
            )
        complete = tuple(candle for candle in group if candle is not None)
        expected = (
            complete[0].open,
            max(candle.high for candle in complete),
            min(candle.low for candle in complete),
            complete[-1].close,
            sum((candle.volume for candle in complete), start=complete[0].volume * 0),
        )
        actual = (parent.open, parent.high, parent.low, parent.close, parent.volume)
        if actual != expected:
            return CrossTimeframeValidationResult(
                False, (ReasonCode.TIMEFRAME_UNSYNCED,), "parent OHLCV differs from children"
            )
    return CrossTimeframeValidationResult(True, (), None)
