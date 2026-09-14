from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from tests.backtest.helpers import metadata
from trading_bot.application.validation_pipeline import run_baseline_validation
from trading_bot.backtest.funding import provider_from_config
from trading_bot.backtest.versions import cost_model_version, execution_model_version
from trading_bot.config.loader import config_version
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.identifiers import deterministic_id
from trading_bot.domain.primitives import canonical_json
from trading_bot.domain.value_objects import VersionSet
from trading_bot.validation.identity import create_validation_protocol
from trading_bot.validation.models import PartitionType
from trading_bot.validation.splits import create_temporal_split

from .helpers import HISTORICAL, START, backtest_result, evaluation_range, trade


class _RecordingRepository:
    def __init__(self) -> None:
        self.requested_starts: list[datetime] = []

    def get_candles(self, _symbol, _timeframe, start, _end, _version):
        self.requested_starts.append(start)
        return ()

    def latest_before(self, _symbol, _timeframe, as_of, _count, _version):
        return (
            SimpleNamespace(open_time=as_of - timedelta(days=100)),
            SimpleNamespace(open_time=as_of - timedelta(minutes=5)),
        )


def _inputs(app_config):
    split = create_temporal_split(
        evaluation_range(0, 10), evaluation_range(10, 20), evaluation_range(20, 30)
    )
    provider = provider_from_config(app_config.backtest)
    configured_version = config_version(app_config)
    versions = VersionSet(
        "phase6-code",
        app_config.strategy.version,
        configured_version,
        HISTORICAL.snapshot_data_version,
    )
    instrument = metadata(START - timedelta(days=30))
    protocol = create_validation_protocol(
        protocol_version="protocol-v1",
        code_version=versions.code_version,
        strategy_version=versions.strategy_version,
        config_version=versions.config_version,
        split_id=split.split_id,
        historical_versions=HISTORICAL,
        execution_model_version=execution_model_version(
            app_config.backtest,
            app_config.execution,
            app_config.risk,
            app_config.calculation,
        ),
        cost_model_version=cost_model_version(app_config.backtest, provider.model_version),
        funding_model_version=provider.model_version,
        instrument_metadata_version=instrument.version,
    )
    return split, protocol, versions, instrument, provider


def _runner(split, test_pnl):
    def run(
        repository,
        _symbol,
        historical,
        start,
        end,
        _config,
        versions,
        instrument,
        _provider,
        *,
        state_warmup_start_time=None,
    ):
        assert state_warmup_start_time is not None
        repository.get_candles(
            "BTC-USDT-SWAP",
            None,
            state_warmup_start_time - timedelta(days=1),
            end,
            "v",
        )
        latest = repository.latest_before("BTC-USDT-SWAP", None, end, 2, "v")
        assert all(item.open_time >= state_warmup_start_time for item in latest)
        trades = [trade(0, "10", opened=split.train.start)]
        if end >= split.validation.end:
            trades.append(trade(1, "20", opened=split.validation.start))
        if end >= split.test.end:
            trades.append(trade(2, test_pnl, opened=split.test.start))
        base = backtest_result(tuple(trades))
        run_versions = replace(versions, data_version=historical.snapshot_data_version)
        spec = replace(
            base.run.spec,
            backtest_run_id=deterministic_id("fake-backtest", start, end, trades),
            start_time=start,
            end_time=end,
            versions=run_versions,
            historical_versions=historical,
            instrument_metadata_version=instrument.version,
            execution_model_version=execution_model_version(
                _config.backtest, _config.execution, _config.risk, _config.calculation
            ),
            cost_model_version=cost_model_version(_config.backtest, _provider.model_version),
            funding_model_version=_provider.model_version,
        )
        return replace(base, run=replace(base.run, spec=spec, completed_at=end))

    return run


def test_baseline_pipeline_uses_frozen_semantics_and_declared_data_boundary(
    app_config, monkeypatch
):
    split, protocol, versions, instrument, provider = _inputs(app_config)
    repository = _RecordingRepository()
    monkeypatch.setattr(
        "trading_bot.application.validation_pipeline.run_historical_backtest",
        _runner(split, "30"),
    )

    result = run_baseline_validation(
        repository,
        "BTC-USDT-SWAP",
        HISTORICAL,
        split,
        protocol,
        app_config,
        versions,
        instrument,
        minimum_sample_size=5,
        funding_provider=provider,
    )

    assert tuple(item.partition for item in result.partitions) == tuple(PartitionType)
    assert tuple(item.metrics.net_pnl for item in result.partitions) == (10, 20, 30)
    assert len(set(repository.requested_starts)) == 1
    assert repository.requested_starts[0] == result.partitions[0].window.data_start
    assert result.test_consumed and result.protocol.test_locked
    assert result.protocol.test_evaluation_count == 1


def test_future_test_change_cannot_affect_train_or_validation(app_config, monkeypatch):
    split, protocol, versions, instrument, provider = _inputs(app_config)
    repository = _RecordingRepository()

    def execute(test_pnl):
        monkeypatch.setattr(
            "trading_bot.application.validation_pipeline.run_historical_backtest",
            _runner(split, test_pnl),
        )
        return run_baseline_validation(
            repository,
            "BTC-USDT-SWAP",
            HISTORICAL,
            split,
            protocol,
            app_config,
            versions,
            instrument,
            minimum_sample_size=1,
            funding_provider=provider,
        )

    original = execute("30")
    changed = execute("-30")

    assert canonical_json(original.partitions[0].metrics) == canonical_json(
        changed.partitions[0].metrics
    )
    assert canonical_json(original.partitions[1].metrics) == canonical_json(
        changed.partitions[1].metrics
    )
    assert original.partitions[2].metrics.net_pnl == 30
    assert changed.partitions[2].metrics.net_pnl == -30


def test_protocol_semantic_mismatch_fails_before_any_backtest(app_config):
    split, protocol, versions, instrument, provider = _inputs(app_config)
    repository = _RecordingRepository()

    with pytest.raises(DomainValidationError, match="semantic identity mismatch"):
        run_baseline_validation(
            repository,
            "BTC-USDT-SWAP",
            HISTORICAL,
            split,
            replace(protocol, strategy_version="mutated-after-test"),
            app_config,
            versions,
            instrument,
            minimum_sample_size=1,
            funding_provider=provider,
        )

    assert repository.requested_starts == []


@pytest.mark.parametrize(
    ("protocol_change", "version_change"),
    (
        ({"code_version": "different-code"}, {}),
        ({}, {"data_version": "different-history"}),
    ),
)
def test_code_and_historical_semantic_mismatch_fail_before_backtest(
    app_config, protocol_change, version_change
):
    split, protocol, versions, instrument, provider = _inputs(app_config)
    repository = _RecordingRepository()

    with pytest.raises(DomainValidationError, match="semantic identity mismatch"):
        run_baseline_validation(
            repository,
            "BTC-USDT-SWAP",
            HISTORICAL,
            split,
            replace(protocol, **protocol_change),
            app_config,
            replace(versions, **version_change),
            instrument,
            minimum_sample_size=1,
            funding_provider=provider,
        )

    assert repository.requested_starts == []


def test_final_test_requires_explicit_protocol_lock(app_config):
    split, protocol, versions, instrument, provider = _inputs(app_config)

    with pytest.raises(DomainValidationError, match="explicit locked protocol"):
        run_baseline_validation(
            _RecordingRepository(),
            "BTC-USDT-SWAP",
            HISTORICAL,
            split,
            replace(protocol, test_locked=False, test_evaluation_count=0),
            app_config,
            versions,
            instrument,
            minimum_sample_size=1,
            funding_provider=provider,
        )


def test_post_test_trade_cannot_change_current_partition_metrics(app_config):
    from trading_bot.validation.metrics import project_validation_metrics

    inside = trade(0, "10", opened=START + timedelta(days=20))
    after = trade(1, "999", opened=START + timedelta(days=31))

    current = project_validation_metrics(
        backtest_result((inside,)),
        evaluation_range(20, 30),
        minimum_sample_size=1,
        calculation=app_config.calculation,
    )
    appended = project_validation_metrics(
        backtest_result((inside, after)),
        evaluation_range(20, 30),
        minimum_sample_size=1,
        calculation=app_config.calculation,
    )

    assert canonical_json(current) == canonical_json(appended)
