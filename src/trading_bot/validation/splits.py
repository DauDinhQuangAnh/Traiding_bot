"""Chronological split and warmup derivation."""

from __future__ import annotations

from datetime import timedelta

from trading_bot.config.models import AppConfig, required_bars
from trading_bot.domain.enums import Timeframe
from trading_bot.domain.identifiers import deterministic_id
from trading_bot.validation.models import (
    EvaluationRange,
    PartitionType,
    PartitionWindow,
    TemporalSplitSpec,
)

_INTERVALS = {
    Timeframe.M5: timedelta(minutes=5),
    Timeframe.M15: timedelta(minutes=15),
    Timeframe.H1: timedelta(hours=1),
}


def create_temporal_split(
    train: EvaluationRange,
    validation: EvaluationRange,
    test: EvaluationRange,
    *,
    purge_duration: timedelta = timedelta(0),
    embargo_duration: timedelta = timedelta(0),
    split_version: str = "temporal-split-v1",
) -> TemporalSplitSpec:
    identifier = deterministic_id(
        "temporal-split-v1",
        train,
        validation,
        test,
        purge_duration,
        embargo_duration,
        "UTC",
        split_version,
    )
    return TemporalSplitSpec(
        identifier,
        train,
        validation,
        test,
        purge_duration,
        embargo_duration,
        "UTC",
        split_version,
    )


def minimum_warmup_by_timeframe(config: AppConfig) -> dict[Timeframe, timedelta]:
    """Convert the approved indicator/structure bar requirements into durations."""
    bars = required_bars(config.indicators, config.levels)
    return {timeframe: bars[timeframe] * _INTERVALS[timeframe] for timeframe in Timeframe}


def minimum_warmup_duration(config: AppConfig) -> timedelta:
    return max(minimum_warmup_by_timeframe(config).values())


def partition_windows(
    split: TemporalSplitSpec,
    config: AppConfig,
    *,
    requested_warmup: timedelta | None = None,
) -> tuple[PartitionWindow, ...]:
    """Use one past-only origin so later partitions reconstruct continuous state."""
    minimum = minimum_warmup_duration(config)
    warmup = minimum if requested_warmup is None else requested_warmup
    if warmup < minimum:
        from trading_bot.domain.errors import DomainValidationError

        raise DomainValidationError("requested warmup is below derived minimum")
    data_start = split.train.start - warmup
    return (
        PartitionWindow(PartitionType.TRAIN, data_start, split.train),
        PartitionWindow(PartitionType.VALIDATION, data_start, split.validation),
        PartitionWindow(PartitionType.TEST, data_start, split.test),
    )
