from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from trading_bot.application.backtest_pipeline import (
    attempt_historical_backtest,
    run_historical_backtest,
)
from trading_bot.backtest.versions import run_id
from trading_bot.config.loader import config_version
from trading_bot.domain.enums import BacktestFailureKind, BacktestStatus, FundingMode, Timeframe
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.identifiers import deterministic_id
from trading_bot.domain.market_models import Candle
from trading_bot.domain.risk_models import InstrumentMetadata
from trading_bot.domain.value_objects import VersionSet
from trading_bot.historical.models import HistoricalVersionSet

D = Decimal


def _series(
    timeframe: Timeframe,
    count: int,
    end: datetime,
    version: str,
) -> tuple[Candle, ...]:
    interval = {
        Timeframe.M5: timedelta(minutes=5),
        Timeframe.M15: timedelta(minutes=15),
        Timeframe.H1: timedelta(hours=1),
    }[timeframe]
    first = end - interval * count
    return tuple(
        Candle(
            f"{timeframe.value}-{index}",
            "BTC-USDT-SWAP",
            timeframe,
            first + interval * index,
            first + interval * (index + 1),
            first + interval * (index + 1),
            first + interval * (index + 1),
            D("100") + D(index) / D("10"),
            D("101") + D(index) / D("10"),
            D("99") + D(index) / D("10"),
            D("100.5") + D(index) / D("10"),
            D("10"),
            True,
            "pipeline-fixture",
            version,
        )
        for index in range(count)
    )


class _Repository:
    def __init__(self, data: dict[Timeframe, tuple[Candle, ...]]) -> None:
        self.data = data

    def append_dataset(self, dataset, manifest) -> None:
        raise AssertionError("pipeline test repository is read-only")

    def get_candles(self, symbol, timeframe, start, end, data_version):
        return tuple(
            candle
            for candle in self.data[timeframe]
            if candle.symbol == symbol
            and candle.data_version == data_version
            and candle.open_time >= start
            and candle.close_time <= end
        )

    def latest_before(self, symbol, timeframe, as_of, count, data_version):
        eligible = tuple(
            candle
            for candle in self.data[timeframe]
            if candle.symbol == symbol
            and candle.data_version == data_version
            and candle.close_time <= as_of
        )
        return eligible[-count:]


def test_full_historical_pipeline_uses_m15_trigger_and_m5_clock(app_config):
    as_of = datetime(2026, 1, 2, 12, tzinfo=UTC)
    versions = HistoricalVersionSet("m5-pipeline", "m15-pipeline", "h1-pipeline")
    m5_history = _series(Timeframe.M5, 300, as_of, versions.m5_data_version)
    future_m5 = _series(
        Timeframe.M5,
        2,
        as_of + timedelta(minutes=10),
        versions.m5_data_version,
    )
    repository = _Repository(
        {
            Timeframe.M5: (*m5_history, *future_m5),
            Timeframe.M15: _series(Timeframe.M15, 300, as_of, versions.m15_data_version),
            Timeframe.H1: _series(Timeframe.H1, 300, as_of, versions.h1_data_version),
        }
    )
    start = as_of - timedelta(minutes=15)
    end = as_of + timedelta(minutes=10)
    metadata = InstrumentMetadata(
        "BTC-USDT-SWAP",
        "LINEAR_SWAP_FIXTURE",
        "USDT",
        True,
        D("1"),
        D("0.01"),
        D("1"),
        D("1"),
        D("10"),
        D("10000"),
        D("5"),
        start,
        "instrument-pipeline-v1",
    )
    result = run_historical_backtest(
        repository,
        "BTC-USDT-SWAP",
        versions,
        start,
        end,
        app_config,
        VersionSet("code-v1", app_config.strategy.version, config_version(app_config), "pending"),
        metadata,
    )
    assert result.run.status is BacktestStatus.COMPLETED
    assert result.run.spec.historical_versions == versions
    assert result.run.spec.versions.data_version == versions.snapshot_data_version
    assert result.metrics.evaluations == 1
    assert all(point.timestamp.minute % 5 == 0 for point in result.equity_curve)


def test_historical_funding_mode_fails_closed_without_provider(app_config):
    configured = replace(
        app_config,
        backtest=replace(app_config.backtest, funding_mode=FundingMode.HISTORICAL_SERIES),
    )
    now = datetime(2026, 1, 2, 12, tzinfo=UTC)
    metadata = InstrumentMetadata(
        "BTC-USDT-SWAP",
        "LINEAR_SWAP_FIXTURE",
        "USDT",
        True,
        D("1"),
        D("0.01"),
        D("1"),
        D("1"),
        D("10"),
        D("10000"),
        D("5"),
        now,
        "instrument-v1",
    )
    with pytest.raises(DomainValidationError, match="injected"):
        run_historical_backtest(
            _Repository({timeframe: () for timeframe in Timeframe}),
            "BTC-USDT-SWAP",
            HistoricalVersionSet("m5", "m15", "h1"),
            now,
            now + timedelta(minutes=5),
            configured,
            VersionSet(
                "code",
                configured.strategy.version,
                config_version(configured),
                "pending",
            ),
            metadata,
        )

    failure = attempt_historical_backtest(
        _Repository({timeframe: () for timeframe in Timeframe}),
        "BTC-USDT-SWAP",
        HistoricalVersionSet("m5", "m15", "h1"),
        now,
        now,
        app_config,
        VersionSet("code", app_config.strategy.version, "config", "pending"),
        metadata,
    )
    assert failure.status is BacktestStatus.FAILED
    assert failure.kind is BacktestFailureKind.VALIDATION


def test_state_warmup_replays_market_state_but_cannot_execute_warmup_signal(
    app_config, monkeypatch
):
    official_start = datetime(2026, 1, 2, 12, tzinfo=UTC)
    warmup_start = official_start - timedelta(days=2)
    end = official_start + timedelta(minutes=30)
    versions = HistoricalVersionSet("m5-warmup", "m15-warmup", "h1-warmup")
    warmup_evaluation = SimpleNamespace(
        decision=SimpleNamespace(as_of=official_start - timedelta(minutes=15))
    )
    official_evaluation = SimpleNamespace(decision=SimpleNamespace(as_of=official_start))
    captured = {}

    def build(_repository, _symbol, _versions, start, stop, _config, _run_versions):
        captured["snapshot_range"] = (start, stop)
        return SimpleNamespace(snapshots=(object(),), failures=())

    monkeypatch.setattr(
        "trading_bot.application.backtest_pipeline.build_historical_snapshot_sequence",
        build,
    )
    monkeypatch.setattr(
        "trading_bot.application.backtest_pipeline.replay_historical_sequence",
        lambda *_args: (warmup_evaluation, official_evaluation),
    )

    class RecordingEngine:
        def __init__(self, spec, *_args):
            captured["spec"] = spec

        def run(self, candles, evaluations):
            captured["candles"] = candles
            captured["evaluations"] = evaluations
            return SimpleNamespace(run=SimpleNamespace(spec=captured["spec"]))

    monkeypatch.setattr("trading_bot.application.backtest_pipeline.BacktestEngine", RecordingEngine)
    metadata = InstrumentMetadata(
        "BTC-USDT-SWAP",
        "LINEAR_SWAP_FIXTURE",
        "USDT",
        True,
        D("1"),
        D("0.01"),
        D("1"),
        D("1"),
        D("10"),
        D("10000"),
        D("5"),
        official_start,
        "instrument-warmup-v1",
    )

    result = run_historical_backtest(
        _Repository({timeframe: () for timeframe in Timeframe}),
        "BTC-USDT-SWAP",
        versions,
        official_start,
        end,
        app_config,
        VersionSet(
            "code-v1",
            app_config.strategy.version,
            config_version(app_config),
            versions.snapshot_data_version,
        ),
        metadata,
        state_warmup_start_time=warmup_start,
    )

    assert captured["snapshot_range"] == (warmup_start, end)
    assert captured["spec"].start_time == official_start
    assert captured["evaluations"] == (official_evaluation,)
    spec = result.run.spec
    base_identifier = run_id(
        spec.versions,
        versions,
        metadata,
        spec.execution_model_version,
        spec.cost_model_version,
        spec.funding_model_version,
        official_start,
        end,
        spec.initial_equity,
    )
    assert spec.backtest_run_id == deterministic_id(
        "state-warmed-backtest-v1", base_identifier, warmup_start
    )
