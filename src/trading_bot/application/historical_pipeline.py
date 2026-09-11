"""Point-in-time snapshot construction over canonical historical repositories."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from trading_bot.application.pipeline import EvaluationResult, replay_market_sequence
from trading_bot.config.models import AppConfig, required_bars
from trading_bot.domain.enums import Timeframe
from trading_bot.domain.value_objects import CostRateEstimate, VersionSet
from trading_bot.historical.models import SnapshotSequenceResult
from trading_bot.historical.repository import HistoricalCandleRepository
from trading_bot.market_data.validation import build_market_snapshot


def build_historical_snapshot_sequence(
    repository: HistoricalCandleRepository,
    symbol: str,
    data_version: str,
    start: datetime,
    end: datetime,
    config: AppConfig,
    versions: VersionSet,
) -> SnapshotSequenceResult:
    needs = required_bars(config.indicators, config.levels)
    triggers = repository.get_candles(symbol, Timeframe.M15, start, end, data_version)
    historical_versions = replace(versions, data_version=data_version)
    snapshots = []
    failures = []
    skipped = 0
    for trigger in triggers:
        as_of = trigger.close_time
        series = {
            timeframe: tuple(
                repository.latest_before(
                    symbol,
                    timeframe,
                    as_of,
                    needs[timeframe],
                    data_version,
                )
            )
            for timeframe in Timeframe
        }
        if any(len(series[timeframe]) < needs[timeframe] for timeframe in Timeframe):
            skipped += 1
            continue
        build = build_market_snapshot(
            symbol,
            as_of,
            as_of,
            series[Timeframe.M5],
            series[Timeframe.M15],
            series[Timeframe.H1],
            None,
            historical_versions,
            config.data,
        )
        if build.snapshot is None:
            failures.append((as_of, build.reason_codes, build.detail))
        else:
            snapshots.append(build.snapshot)
    return SnapshotSequenceResult(tuple(snapshots), skipped, tuple(failures))


def replay_historical_sequence(
    snapshots: SnapshotSequenceResult,
    config: AppConfig,
    versions: VersionSet,
    costs: CostRateEstimate,
) -> tuple[EvaluationResult, ...]:
    if not snapshots.snapshots:
        return ()
    historical_versions = replace(versions, data_version=snapshots.snapshots[0].data_version)
    return replay_market_sequence(snapshots.snapshots, config, historical_versions, costs)
