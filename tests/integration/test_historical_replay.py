from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trading_bot.application.historical_pipeline import (
    build_historical_snapshot_sequence,
    replay_historical_sequence,
)
from trading_bot.domain.enums import Timeframe
from trading_bot.domain.primitives import canonical_json
from trading_bot.domain.value_objects import CostRateEstimate
from trading_bot.historical.dataset import ingest_csv_files, resample_dataset
from trading_bot.historical.repository import SQLiteHistoricalCandleRepository


def _csv_text(count: int, *, corrected_index: int | None = None) -> str:
    rows = ["timestamp,open,high,low,close,volume,symbol,timeframe,closed"]
    start = datetime(2025, 12, 1, tzinfo=UTC)
    for index in range(count):
        opened = start + timedelta(minutes=5 * index)
        opening = Decimal("100") + Decimal(index) / Decimal("100")
        close = opening + (Decimal("0.007") if index == corrected_index else Decimal("0.005"))
        rows.append(
            ",".join(
                (
                    opened.isoformat().replace("+00:00", "Z"),
                    format(opening, "f"),
                    format(opening + 1, "f"),
                    format(opening - 1, "f"),
                    format(close, "f"),
                    str(10 + index % 3),
                    "BTCUSDT",
                    "5m",
                    "true",
                )
            )
        )
    return "\n".join(rows) + "\n"


def _ingest_bundle(path, app_config, versions):
    ingestion = ingest_csv_files(
        (path,),
        app_config.historical,
        config_version=versions.config_version,
        code_version=versions.code_version,
    )
    assert ingestion.dataset is not None and ingestion.manifest is not None
    base = ingestion.dataset
    common = {
        "algorithm_version": app_config.historical.resampling_version,
        "source_content_hashes": ingestion.manifest.source_content_hashes,
        "parser_version": app_config.historical.parser_version,
        "normalization_version": app_config.historical.normalization_version,
        "code_version": versions.code_version,
        "config_version": versions.config_version,
    }
    m15 = resample_dataset(base, Timeframe.M15, **common)
    h1 = resample_dataset(base, Timeframe.H1, **common)
    return ingestion, m15, h1


def _persist_bundle(repository, bundle):
    ingestion, m15, h1 = bundle
    repository.append_dataset(ingestion.dataset, ingestion.manifest)
    repository.append_dataset(m15.dataset, m15.manifest)
    repository.append_dataset(h1.dataset, h1.manifest)


def _replay(repository, bundle, app_config, versions, *, cutoff=None):
    ingestion = bundle[0]
    dataset = ingestion.dataset
    end = cutoff or dataset.end_time
    start = end - timedelta(minutes=30)
    snapshots = build_historical_snapshot_sequence(
        repository,
        dataset.symbol,
        dataset.data_version,
        start,
        end,
        app_config,
        versions,
    )
    assert snapshots.snapshots and not snapshots.failures
    costs = CostRateEstimate(*(Decimal("0") for _ in range(7)), model_version="historical-v1")
    return snapshots, replay_historical_sequence(snapshots, app_config, versions, costs)


def test_snapshot_builder_reports_insufficient_warmup_without_future_fill(
    tmp_path, app_config, versions
):
    source = tmp_path / "short.csv"
    source.write_text(_csv_text(12), encoding="utf-8")
    bundle = _ingest_bundle(source, app_config, versions)
    repository = SQLiteHistoricalCandleRepository(tmp_path / "short.db")
    try:
        _persist_bundle(repository, bundle)
        dataset = bundle[0].dataset
        result = build_historical_snapshot_sequence(
            repository,
            dataset.symbol,
            dataset.data_version,
            dataset.start_time,
            dataset.end_time,
            app_config,
            versions,
        )
        assert result.snapshots == ()
        assert result.skipped_warmup == 4
        assert result.failures == ()
    finally:
        repository.close()


def test_raw_to_storage_rebuild_to_phase3_replay_is_byte_equivalent(tmp_path, app_config, versions):
    source_a = tmp_path / "a" / "history.csv"
    source_b = tmp_path / "b" / "renamed.csv"
    source_a.parent.mkdir()
    source_b.parent.mkdir()
    content = _csv_text(2664)
    source_a.write_text(content, encoding="utf-8")
    source_b.write_text(content, encoding="utf-8")
    first_bundle = _ingest_bundle(source_a, app_config, versions)
    second_bundle = _ingest_bundle(source_b, app_config, versions)

    first_repository = SQLiteHistoricalCandleRepository(tmp_path / "first.db")
    second_repository = SQLiteHistoricalCandleRepository(tmp_path / "second.db")
    try:
        _persist_bundle(first_repository, first_bundle)
        first_snapshots, first_replay = _replay(
            first_repository, first_bundle, app_config, versions
        )
        _persist_bundle(second_repository, second_bundle)
        second_snapshots, second_replay = _replay(
            second_repository, second_bundle, app_config, versions
        )
    finally:
        first_repository.close()
        second_repository.close()

    assert canonical_json(first_bundle) == canonical_json(second_bundle)
    assert canonical_json(first_snapshots) == canonical_json(second_snapshots)
    assert canonical_json(first_replay) == canonical_json(second_replay)
    assert [result.decision.decision_record_id for result in first_replay] == [
        result.decision.decision_record_id for result in second_replay
    ]
    assert [result.regime and result.regime.assessment_id for result in first_replay] == [
        result.regime and result.regime.assessment_id for result in second_replay
    ]
    assert [
        result.strategy and result.strategy.assessment.signal_assessment_id
        for result in first_replay
    ] == [
        result.strategy and result.strategy.assessment.signal_assessment_id
        for result in second_replay
    ]
    assert [result.candidate and result.candidate.candidate_id for result in first_replay] == [
        result.candidate and result.candidate.candidate_id for result in second_replay
    ]


def test_future_append_and_correction_preserve_old_point_in_time_replay(
    tmp_path, app_config, versions
):
    original_path = tmp_path / "original.csv"
    future_path = tmp_path / "future.csv"
    corrected_path = tmp_path / "corrected.csv"
    original_path.write_text(_csv_text(2664), encoding="utf-8")
    future_path.write_text(_csv_text(2676), encoding="utf-8")
    corrected_path.write_text(_csv_text(2676, corrected_index=100), encoding="utf-8")
    original = _ingest_bundle(original_path, app_config, versions)
    future = _ingest_bundle(future_path, app_config, versions)
    corrected = _ingest_bundle(corrected_path, app_config, versions)
    assert (
        len(
            {
                original[0].dataset.data_version,
                future[0].dataset.data_version,
                corrected[0].dataset.data_version,
            }
        )
        == 3
    )

    repository = SQLiteHistoricalCandleRepository(tmp_path / "versions.db")
    try:
        _persist_bundle(repository, original)
        cutoff = original[0].dataset.end_time
        before = _replay(repository, original, app_config, versions, cutoff=cutoff)
        _persist_bundle(repository, future)
        _persist_bundle(repository, corrected)
        after = _replay(repository, original, app_config, versions, cutoff=cutoff)
        assert canonical_json(before) == canonical_json(after)
        old_query = repository.latest_before(
            original[0].dataset.symbol,
            Timeframe.M5,
            cutoff,
            100,
            original[0].dataset.data_version,
        )
        assert old_query == original[0].dataset.candles[-100:]
    finally:
        repository.close()
