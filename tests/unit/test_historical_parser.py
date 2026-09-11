from dataclasses import replace
from pathlib import Path

import pytest

from trading_bot.domain.enums import (
    HistoricalIngestionStatus,
    NormalizationStatus,
    TimestampConvention,
    TimestampUnit,
)
from trading_bot.domain.errors import HistoricalParserError
from trading_bot.historical.dataset import ingest_csv_files
from trading_bot.historical.normalization import normalize_record
from trading_bot.historical.parsers import CsvHistoricalDataParser

FIXTURES = Path("tests/fixtures/historical")


def _raw(app_config):
    parser = CsvHistoricalDataParser(app_config.historical.column_mapping)
    return next(iter(parser.parse(FIXTURES / "valid_m5.csv", "local_csv")))


def test_valid_csv_is_streamed_with_lossless_provenance(app_config):
    records = tuple(
        CsvHistoricalDataParser(app_config.historical.column_mapping).parse(
            FIXTURES / "valid_m5.csv", "local_csv"
        )
    )
    assert len(records) == 12
    assert records[0].raw_open == "100"
    assert records[0].source_row == 2
    assert records[0].source_file == "valid_m5.csv"
    assert records[0].source_content_hash
    assert records[0].payload_hash


def test_missing_required_csv_column_is_typed_failure(tmp_path, app_config):
    path = tmp_path / "missing.csv"
    path.write_text("timestamp,open\n2026-01-01T00:00:00Z,100\n", encoding="utf-8")
    parser = CsvHistoricalDataParser(app_config.historical.column_mapping)
    with pytest.raises(HistoricalParserError, match="missing required columns"):
        tuple(parser.parse(path, "local_csv"))
    result = ingest_csv_files((path,), app_config.historical)
    assert result.status is HistoricalIngestionStatus.FAILED
    assert not result.is_backtest_eligible


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("raw_open", "not-a-decimal"),
        ("raw_timestamp", "not-a-time"),
        ("raw_symbol", "UNKNOWN"),
        ("raw_timeframe", "2m"),
        ("raw_close_status", "false"),
        ("raw_volume", "-1"),
        ("raw_high", "99"),
    ],
)
def test_bad_raw_values_are_auditable_rejections(app_config, field, value):
    result = normalize_record(
        replace(_raw(app_config), **{field: value}), app_config.historical, "data-v1"
    )
    assert result.status is NormalizationStatus.REJECTED
    assert result.candle is None
    assert result.reason_codes
    assert result.detail


@pytest.mark.parametrize("raw_timeframe", ["5m", "15m", "1h"])
def test_all_canonical_timeframe_boundaries_accept_and_misalignment_rejects(
    app_config, raw_timeframe
):
    raw = replace(_raw(app_config), raw_timeframe=raw_timeframe)
    valid = normalize_record(raw, app_config.historical, "data-v1")
    assert valid.status is NormalizationStatus.ACCEPTED
    invalid = normalize_record(
        replace(raw, raw_timestamp="2026-01-01T00:02:00Z"),
        app_config.historical,
        "data-v1",
    )
    assert invalid.status is NormalizationStatus.REJECTED


def test_timestamp_convention_and_unit_are_explicit(app_config):
    raw = _raw(app_config)
    seconds_config = replace(
        app_config.historical,
        timestamp_unit=TimestampUnit.UNIX_SECONDS,
        timestamp_convention=TimestampConvention.OPEN_TIME,
    )
    seconds = normalize_record(replace(raw, raw_timestamp="1767225600"), seconds_config, "data-v1")
    milliseconds_config = replace(seconds_config, timestamp_unit=TimestampUnit.UNIX_MILLISECONDS)
    milliseconds = normalize_record(
        replace(raw, raw_timestamp="1767225600000"), milliseconds_config, "data-v1"
    )
    assert seconds.candle is not None and milliseconds.candle is not None
    assert seconds.candle.open_time == milliseconds.candle.open_time

    close_config = replace(
        app_config.historical,
        timestamp_convention=TimestampConvention.CLOSE_TIME,
    )
    close_semantics = normalize_record(
        replace(raw, raw_timestamp="2026-01-01T00:05:00Z"), close_config, "data-v1"
    )
    assert close_semantics.candle is not None
    assert close_semantics.candle.open_time.isoformat() == "2026-01-01T00:00:00+00:00"
