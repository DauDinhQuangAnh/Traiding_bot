from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from trading_bot.config.loader import config_version
from trading_bot.domain.enums import Timeframe, TimestampConvention
from trading_bot.historical.dataset import ingest_csv_files, resample_dataset
from trading_bot.historical.manifests import historical_semantics_version
from trading_bot.historical.models import HistoricalVersionSet

FIXTURE = Path("tests/fixtures/historical/valid_m5.csv")


def _ingest(historical_config):
    result = ingest_csv_files(
        (FIXTURE,),
        historical_config,
    )
    assert result.dataset is not None and result.manifest is not None
    return result


def test_strategy_config_change_does_not_change_historical_identity(app_config):
    changed_app = replace(
        app_config,
        strategy=replace(
            app_config.strategy,
            long_threshold=app_config.strategy.long_threshold + Decimal("1"),
        ),
    )
    assert config_version(changed_app) != config_version(app_config)
    assert historical_semantics_version(changed_app.historical) == historical_semantics_version(
        app_config.historical
    )
    original = _ingest(app_config.historical)
    changed = _ingest(changed_app.historical)
    assert original.dataset.data_version == changed.dataset.data_version
    assert original.dataset.dataset_id == changed.dataset.dataset_id
    assert original.dataset.candles == changed.dataset.candles
    assert original.manifest == changed.manifest


def test_risk_config_change_does_not_change_historical_identity(app_config):
    changed_app = replace(
        app_config,
        risk=replace(
            app_config.risk,
            risk_per_trade=app_config.risk.risk_per_trade + Decimal("0.001"),
        ),
    )
    assert config_version(changed_app) != config_version(app_config)
    assert (
        _ingest(changed_app.historical).dataset.data_version
        == _ingest(app_config.historical).dataset.data_version
    )


def test_raw_to_canonical_semantic_changes_change_data_version(app_config):
    original_config = app_config.historical
    original = _ingest(original_config)
    changes = (
        replace(
            original_config,
            timestamp_convention=TimestampConvention.CLOSE_TIME,
        ),
        replace(
            original_config,
            symbol_mapping={**original_config.symbol_mapping, "XBTUSDT": "BTC-USDT-SWAP"},
        ),
        replace(original_config, parser_version="csv-v2"),
        replace(original_config, normalization_version="historical-normalization-v2"),
    )
    for changed_config in changes:
        assert historical_semantics_version(changed_config) != historical_semantics_version(
            original_config
        )
        assert _ingest(changed_config).dataset.data_version != original.dataset.data_version


def test_resampling_version_is_excluded_from_canonical_m5_identity(app_config):
    original_config = app_config.historical
    changed_config = replace(original_config, resampling_version="ohlcv-resample-v2")
    assert historical_semantics_version(changed_config) == historical_semantics_version(
        original_config
    )
    assert (
        _ingest(changed_config).dataset.data_version
        == _ingest(original_config).dataset.data_version
    )


def test_derived_versions_are_deterministic_and_resampling_scoped(app_config):
    base = _ingest(app_config.historical)
    first = resample_dataset(
        base.dataset,
        base.manifest,
        Timeframe.M15,
        algorithm_version="resample-v1",
    )
    repeated = resample_dataset(
        base.dataset,
        base.manifest,
        Timeframe.M15,
        algorithm_version="resample-v1",
    )
    changed_algorithm = resample_dataset(
        base.dataset,
        base.manifest,
        Timeframe.M15,
        algorithm_version="resample-v2",
    )
    changed_target = resample_dataset(
        base.dataset,
        base.manifest,
        Timeframe.H1,
        algorithm_version="resample-v1",
    )
    assert first == repeated
    assert first.dataset.data_version != base.dataset.data_version
    assert first.dataset.data_version != changed_algorithm.dataset.data_version
    assert first.dataset.data_version != changed_target.dataset.data_version
    assert first.dataset.dataset_id != changed_algorithm.dataset.dataset_id
    assert first.manifest.manifest_id != changed_algorithm.manifest.manifest_id
    assert tuple(candle.candle_id for candle in first.dataset.candles) != tuple(
        candle.candle_id for candle in changed_algorithm.dataset.candles
    )
    assert all(
        candle.data_version == first.dataset.data_version for candle in first.dataset.candles
    )
    assert first.manifest.lineage is not None
    assert first.manifest.lineage.source_dataset_id == base.dataset.dataset_id
    assert first.manifest.lineage.source_data_version == base.dataset.data_version
    assert first.manifest.lineage.source_timeframe is Timeframe.M5
    assert first.manifest.lineage.target_timeframe is Timeframe.M15
    assert first.manifest.lineage.resampling_version == "resample-v1"


def test_snapshot_composite_version_is_stable_and_timeframe_sensitive():
    versions = HistoricalVersionSet("m5-a", "m15-b", "h1-c")
    assert (
        versions.snapshot_data_version
        == HistoricalVersionSet("m5-a", "m15-b", "h1-c").snapshot_data_version
    )
    assert (
        versions.snapshot_data_version
        != HistoricalVersionSet("m5-a", "m15-other", "h1-c").snapshot_data_version
    )
    assert versions.for_timeframe(Timeframe.M5) == "m5-a"
    assert versions.for_timeframe(Timeframe.M15) == "m15-b"
    assert versions.for_timeframe(Timeframe.H1) == "h1-c"


@pytest.mark.parametrize("field", ["parser_version", "normalization_version"])
def test_named_transformation_versions_are_semantic(field, app_config):
    original = app_config.historical
    changed = replace(original, **{field: f"{getattr(original, field)}-changed"})
    assert historical_semantics_version(changed) != historical_semantics_version(original)
