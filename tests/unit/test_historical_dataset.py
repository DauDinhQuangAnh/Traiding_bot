from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from trading_bot.domain.enums import HistoricalIngestionStatus, ReasonCode, Timeframe
from trading_bot.domain.errors import DomainValidationError, HistoricalDataError
from trading_bot.historical.dataset import ingest_csv_files, resample_dataset
from trading_bot.historical.manifests import sha256_file
from trading_bot.historical.serialization import canonical_dataset_bytes, canonical_manifest_bytes
from trading_bot.historical.validation import (
    deduplicate_and_sort,
    detect_gaps,
    validate_cross_timeframe,
)

FIXTURES = Path("tests/fixtures/historical")


def _ingest(name, app_config):
    return ingest_csv_files(
        (FIXTURES / name,),
        app_config.historical,
        config_version="config-v1",
        code_version="code-v1",
    )


def test_valid_dataset_and_exact_duplicate_are_deterministic(app_config):
    first = _ingest("valid_m5.csv", app_config)
    second = _ingest("valid_m5.csv", app_config)
    assert first.status is HistoricalIngestionStatus.SUCCESS
    assert first.dataset is not None and first.manifest is not None
    assert canonical_dataset_bytes(first.dataset) == canonical_dataset_bytes(second.dataset)
    assert canonical_manifest_bytes(first.manifest) == canonical_manifest_bytes(second.manifest)
    assert first.dataset.data_version == second.dataset.data_version

    exact = _ingest("duplicate_exact.csv", app_config)
    assert exact.status is HistoricalIngestionStatus.SUCCESS
    assert exact.dataset is not None and exact.dataset.candle_count == 2
    assert exact.quality_report.exact_duplicates == 1
    assert ReasonCode.DATA_DUPLICATE in exact.quality_report.reason_codes


@pytest.mark.parametrize("fixture_name", ["invalid_ohlc.csv", "misaligned_timestamp.csv"])
def test_invalid_fixture_rows_fail_closed(fixture_name, app_config):
    result = _ingest(fixture_name, app_config)
    assert result.status is HistoricalIngestionStatus.FAILED
    assert result.dataset is None and not result.is_backtest_eligible
    assert result.quality_report.rejected_records == 1


def test_manifest_hashes_every_input_file_including_header_only(tmp_path, app_config):
    header_only = tmp_path / "header-only.csv"
    header_only.write_text(
        "timestamp,open,high,low,close,volume,symbol,timeframe,closed\n",
        encoding="utf-8",
    )
    result = ingest_csv_files(
        (FIXTURES / "valid_m5.csv", header_only),
        app_config.historical,
        config_version="config-v1",
        code_version="code-v1",
    )
    assert result.manifest is not None
    assert result.manifest.source_content_hashes == tuple(
        sorted((sha256_file(FIXTURES / "valid_m5.csv"), sha256_file(header_only)))
    )


def test_conflicting_duplicate_and_gaps_fail_closed(app_config):
    conflict = _ingest("duplicate_conflict.csv", app_config)
    assert conflict.status is HistoricalIngestionStatus.FAILED
    assert conflict.dataset is None and not conflict.is_backtest_eligible
    assert conflict.quality_report.conflicting_duplicates == 1
    assert ReasonCode.DATA_CONFLICT in conflict.quality_report.reason_codes

    single_gap = _ingest("gap.csv", app_config)
    assert single_gap.status is HistoricalIngestionStatus.FAILED
    assert single_gap.quality_report.gap_count == 1
    assert single_gap.quality_report.gaps[0].missing_bar_count == 2

    valid = _ingest("valid_m5.csv", app_config).dataset
    assert valid is not None
    multiple = detect_gaps((valid.candles[0], valid.candles[4]))
    assert len(multiple) == 1 and multiple[0].missing_bar_count == 3


def test_ordered_reverse_and_arbitrary_input_are_sorted_with_diagnostics(app_config):
    valid = _ingest("valid_m5.csv", app_config).dataset
    assert valid is not None
    ordered = deduplicate_and_sort(valid.candles)
    reverse = deduplicate_and_sort(tuple(reversed(valid.candles)))
    arbitrary = deduplicate_and_sort(valid.candles[::2] + valid.candles[1::2])
    assert ordered.out_of_order_count == 0
    assert reverse.candles == ordered.candles and reverse.out_of_order_count > 0
    assert arbitrary.candles == ordered.candles and arbitrary.out_of_order_count > 0

    fixture = _ingest("out_of_order.csv", app_config)
    assert fixture.status is HistoricalIngestionStatus.SUCCESS
    assert fixture.dataset is not None
    assert fixture.quality_report.out_of_order_count > 0
    assert ReasonCode.DATA_OUT_OF_ORDER in fixture.quality_report.reason_codes


def _resample(source, target, app_config):
    return resample_dataset(
        source,
        target,
        algorithm_version=app_config.historical.resampling_version,
        source_content_hashes=("source-hash",),
        parser_version=app_config.historical.parser_version,
        normalization_version=app_config.historical.normalization_version,
        code_version="code-v1",
        config_version="config-v1",
    )


def test_resampling_m5_to_m15_m5_to_h1_and_m15_to_h1(app_config):
    base = _ingest("valid_m5.csv", app_config).dataset
    assert base is not None
    m15 = _resample(base, Timeframe.M15, app_config)
    h1_direct = _resample(base, Timeframe.H1, app_config)
    h1_via_m15 = _resample(m15.dataset, Timeframe.H1, app_config)
    assert m15.dataset.candle_count == 4
    assert h1_direct.dataset.candle_count == h1_via_m15.dataset.candle_count == 1
    direct = h1_direct.dataset.candles[0]
    via = h1_via_m15.dataset.candles[0]
    assert (direct.open, direct.high, direct.low, direct.close, direct.volume) == (
        via.open,
        via.high,
        via.low,
        via.close,
        via.volume,
    )
    assert direct.open == base.candles[0].open
    assert direct.high == max(candle.high for candle in base.candles)
    assert direct.low == min(candle.low for candle in base.candles)
    assert direct.close == base.candles[-1].close
    assert direct.volume == sum(candle.volume for candle in base.candles)
    assert validate_cross_timeframe(base.candles, m15.dataset.candles).is_consistent


def test_resampling_rejects_incomplete_gap_misalignment_and_downsampling(app_config):
    base = _ingest("valid_m5.csv", app_config).dataset
    assert base is not None
    incomplete = replace(
        base,
        candles=base.candles[:-1],
        candle_count=base.candle_count - 1,
        end_time=base.candles[-2].close_time,
    )
    with pytest.raises(HistoricalDataError, match="insufficient"):
        _resample(incomplete, Timeframe.M15, app_config)

    with pytest.raises(DomainValidationError, match="gap-free"):
        replace(
            base,
            candles=(base.candles[0], *base.candles[2:]),
            candle_count=base.candle_count - 1,
            end_time=base.end_time,
        )

    shifted_candles = tuple(
        replace(
            candle,
            open_time=candle.open_time + timedelta(minutes=5),
            close_time=candle.close_time + timedelta(minutes=5),
            event_time=candle.event_time + timedelta(minutes=5),
            receive_time=candle.receive_time + timedelta(minutes=5),
        )
        for candle in base.candles
    )
    shifted = replace(
        base,
        candles=shifted_candles,
        start_time=shifted_candles[0].open_time,
        end_time=shifted_candles[-1].close_time,
    )
    with pytest.raises(HistoricalDataError, match="misaligned"):
        _resample(shifted, Timeframe.M15, app_config)
    with pytest.raises(HistoricalDataError, match="unsupported"):
        _resample(_resample(base, Timeframe.M15, app_config).dataset, Timeframe.M5, app_config)


def test_cross_timeframe_detects_native_payload_mismatch(app_config):
    base = _ingest("valid_m5.csv", app_config).dataset
    assert base is not None
    m15 = _resample(base, Timeframe.M15, app_config).dataset
    changed = (replace(m15.candles[0], close=m15.candles[0].close + 1), *m15.candles[1:])
    result = validate_cross_timeframe(base.candles, changed)
    assert not result.is_consistent
    assert result.reason_codes == (ReasonCode.TIMEFRAME_UNSYNCED,)


def test_manifest_identity_is_path_independent_and_content_sensitive(tmp_path, app_config):
    source = (FIXTURES / "valid_m5.csv").read_bytes()
    left = tmp_path / "left" / "copy.csv"
    right = tmp_path / "right" / "renamed.csv"
    left.parent.mkdir()
    right.parent.mkdir()
    left.write_bytes(source)
    right.write_bytes(source)
    first = ingest_csv_files(
        (left,), app_config.historical, config_version="config-v1", code_version="code-v1"
    )
    second = ingest_csv_files(
        (right,), app_config.historical, config_version="config-v1", code_version="code-v1"
    )
    assert first.dataset is not None and second.dataset is not None
    assert first.dataset.dataset_id == second.dataset.dataset_id
    assert first.dataset.data_version == second.dataset.data_version
    assert first.manifest == second.manifest

    corrected = tmp_path / "corrected.csv"
    corrected.write_bytes(source.replace(b",112,21,", b",112.5,21,"))
    changed = ingest_csv_files(
        (corrected,), app_config.historical, config_version="config-v1", code_version="code-v1"
    )
    assert changed.dataset is not None
    assert changed.dataset.data_version != first.dataset.data_version
