from datetime import timedelta
from pathlib import Path

import pytest

from trading_bot.domain.enums import Timeframe
from trading_bot.domain.errors import HistoricalDataError
from trading_bot.domain.primitives import canonical_json
from trading_bot.historical.dataset import ingest_csv_files, resample_dataset
from trading_bot.historical.repository import SQLiteHistoricalCandleRepository

FIXTURE = Path("tests/fixtures/historical/valid_m5.csv")


def _ingest(path, app_config):
    result = ingest_csv_files(
        (path,), app_config.historical, config_version="config-v1", code_version="code-v1"
    )
    assert result.dataset is not None and result.manifest is not None
    return result


def _derive(dataset, timeframe, app_config, hashes):
    return resample_dataset(
        dataset,
        timeframe,
        algorithm_version=app_config.historical.resampling_version,
        source_content_hashes=hashes,
        parser_version=app_config.historical.parser_version,
        normalization_version=app_config.historical.normalization_version,
        code_version="code-v1",
        config_version="config-v1",
    )


def test_repository_range_count_cutoff_version_and_manifest(tmp_path, app_config):
    ingested = _ingest(FIXTURE, app_config)
    dataset, manifest = ingested.dataset, ingested.manifest
    repository = SQLiteHistoricalCandleRepository(tmp_path / "historical.db")
    try:
        repository.append_dataset(dataset, manifest)
        repository.append_dataset(dataset, manifest)
        ranged = repository.get_candles(
            dataset.symbol,
            Timeframe.M5,
            dataset.candles[2].open_time,
            dataset.candles[5].close_time,
            dataset.data_version,
        )
        assert ranged == dataset.candles[2:6]
        cutoff = repository.latest_before(
            dataset.symbol,
            Timeframe.M5,
            dataset.candles[2].close_time,
            2,
            dataset.data_version,
        )
        assert cutoff == dataset.candles[1:3]
        assert all(candle.close_time <= dataset.candles[2].close_time for candle in cutoff)
        assert repository.get_manifest_json(dataset.dataset_id) == canonical_json(manifest)
        with pytest.raises(HistoricalDataError, match="unknown historical data version"):
            repository.latest_before(
                dataset.symbol, Timeframe.M5, dataset.end_time, 1, "unknown-version"
            )
    finally:
        repository.close()


def test_future_version_append_cannot_change_old_point_in_time_query(tmp_path, app_config):
    original = _ingest(FIXTURE, app_config)
    repository = SQLiteHistoricalCandleRepository(tmp_path / "historical.db")
    try:
        repository.append_dataset(original.dataset, original.manifest)
        cutoff = original.dataset.candles[5].close_time
        before = repository.latest_before(
            original.dataset.symbol,
            Timeframe.M5,
            cutoff,
            100,
            original.dataset.data_version,
        )

        extended_path = tmp_path / "extended.csv"
        existing = FIXTURE.read_text(encoding="utf-8")
        extended_path.write_text(
            existing + "2026-01-01T01:00:00Z,112,114,111,113,22,BTCUSDT,5m,true\n",
            encoding="utf-8",
        )
        extended = _ingest(extended_path, app_config)
        assert extended.dataset.data_version != original.dataset.data_version
        repository.append_dataset(extended.dataset, extended.manifest)
        after = repository.latest_before(
            original.dataset.symbol,
            Timeframe.M5,
            cutoff,
            100,
            original.dataset.data_version,
        )
        assert canonical_json(after) == canonical_json(before)
    finally:
        repository.close()


def test_h1_incomplete_interval_is_excluded_by_point_in_time_query(tmp_path, app_config):
    ingested = _ingest(FIXTURE, app_config)
    hashes = ingested.manifest.source_content_hashes
    h1 = _derive(ingested.dataset, Timeframe.H1, app_config, hashes)
    repository = SQLiteHistoricalCandleRepository(tmp_path / "historical.db")
    try:
        repository.append_dataset(h1.dataset, h1.manifest)
        before_close = h1.dataset.candles[0].close_time - timedelta(microseconds=1)
        assert (
            repository.latest_before(
                h1.dataset.symbol, Timeframe.H1, before_close, 1, h1.dataset.data_version
            )
            == ()
        )
        assert repository.latest_before(
            h1.dataset.symbol,
            Timeframe.H1,
            h1.dataset.candles[0].close_time,
            1,
            h1.dataset.data_version,
        ) == (h1.dataset.candles[0],)
    finally:
        repository.close()
