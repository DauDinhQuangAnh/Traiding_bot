from dataclasses import replace
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from trading_bot.config.loader import load_config
from trading_bot.domain.enums import Timeframe
from trading_bot.historical.dataset import ingest_csv_files, resample_dataset
from trading_bot.historical.manifests import historical_data_version
from trading_bot.historical.validation import detect_gaps

FIXTURE = Path("tests/fixtures/historical/valid_m5.csv")
CONFIG = load_config(Path("config/base.example.yaml"))


def _dataset(app_config):
    result = ingest_csv_files(
        (FIXTURE,), app_config.historical, config_version="config-v1", code_version="code-v1"
    )
    assert result.dataset is not None
    return result.dataset


def _resample(dataset, app_config):
    return resample_dataset(
        dataset,
        Timeframe.M15,
        algorithm_version=app_config.historical.resampling_version,
        source_content_hashes=("source",),
        parser_version=app_config.historical.parser_version,
        normalization_version=app_config.historical.normalization_version,
        code_version="code-v1",
        config_version="config-v1",
    ).dataset


@given(offsets=st.lists(st.integers(min_value=0, max_value=1000), min_size=12, max_size=12))
def test_resampling_preserves_exact_ohlcv_aggregation(offsets):
    base = _dataset(CONFIG)
    candles = tuple(
        replace(
            candle,
            open=candle.open + offset,
            high=candle.high + offset,
            low=candle.low + offset,
            close=candle.close + offset,
            volume=candle.volume + offset,
        )
        for candle, offset in zip(base.candles, offsets, strict=True)
    )
    changed = replace(base, candles=candles)
    derived = _resample(changed, CONFIG)
    for index, parent in enumerate(derived.candles):
        children = candles[index * 3 : index * 3 + 3]
        assert parent.open == children[0].open
        assert parent.high == max(child.high for child in children)
        assert parent.low == min(child.low for child in children)
        assert parent.close == children[-1].close
        assert parent.volume == sum(child.volume for child in children)


@given(suffix=st.text(alphabet="abcdef0123456789", min_size=1, max_size=20))
def test_data_version_is_idempotent_and_content_sensitive(suffix):
    first = historical_data_version(("hash-a",), CONFIG.historical, "config-v1")
    repeated = historical_data_version(("hash-a",), CONFIG.historical, "config-v1")
    changed = historical_data_version((f"hash-a-{suffix}",), CONFIG.historical, "config-v1")
    assert first == repeated
    assert changed != first


def test_successful_dataset_is_strict_unique_and_gap_free(app_config):
    dataset = _dataset(app_config)
    keys = tuple(
        (candle.source, candle.symbol, candle.timeframe, candle.open_time)
        for candle in dataset.candles
    )
    assert keys == tuple(sorted(keys, key=lambda key: key[-1]))
    assert len(keys) == len(set(keys))
    assert detect_gaps(dataset.candles) == ()
    assert dataset.is_backtest_eligible
