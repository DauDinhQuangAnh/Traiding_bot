"""Dataset construction and deterministic upward OHLCV resampling."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from trading_bot.config.models import HistoricalConfig
from trading_bot.domain.enums import (
    HistoricalDatasetStatus,
    HistoricalIngestionStatus,
    ReasonCode,
    Timeframe,
)
from trading_bot.domain.errors import HistoricalDataError, HistoricalParserError
from trading_bot.domain.identifiers import deterministic_id
from trading_bot.domain.market_models import Candle
from trading_bot.historical.manifests import (
    canonical_candle_hash,
    derived_data_version,
    historical_data_version,
    historical_semantics_version,
    raw_data_version,
    sha256_file,
)
from trading_bot.historical.models import (
    DataQualityReport,
    DatasetManifest,
    DerivedDatasetLineage,
    DerivedDatasetResult,
    Gap,
    HistoricalDataset,
    HistoricalIngestionResult,
    HistoricalRejection,
    RawHistoricalRecord,
)
from trading_bot.historical.normalization import normalize_record
from trading_bot.historical.parsers import CsvHistoricalDataParser
from trading_bot.historical.validation import deduplicate_and_sort, detect_gaps

_INTERVALS = {
    Timeframe.M5: timedelta(minutes=5),
    Timeframe.M15: timedelta(minutes=15),
    Timeframe.H1: timedelta(hours=1),
}
_ALLOWED_RESAMPLING = {
    (Timeframe.M5, Timeframe.M15),
    (Timeframe.M5, Timeframe.H1),
    (Timeframe.M15, Timeframe.H1),
}
_MANIFEST_VERSION = "historical-manifest-v2"


def _manifest_and_dataset(
    candles: tuple[Candle, ...],
    *,
    source: str,
    source_content_hashes: tuple[str, ...],
    data_version: str,
    historical_semantics_version: str,
    parser_version: str,
    normalization_version: str,
    resampling_version: str | None,
    lineage: DerivedDatasetLineage | None = None,
    rejection_count: int = 0,
    exact_duplicate_count: int = 0,
    conflict_count: int = 0,
    gap_count: int = 0,
) -> tuple[HistoricalDataset, DatasetManifest]:
    canonical_hash = canonical_candle_hash(candles)
    dataset_id = deterministic_id(
        "historical-dataset",
        candles[0].symbol,
        candles[0].timeframe,
        data_version,
        canonical_hash,
    )
    manifest_fields = (
        _MANIFEST_VERSION,
        dataset_id,
        candles[0].symbol,
        candles[0].timeframe,
        source_content_hashes,
        raw_data_version(source_content_hashes),
        historical_semantics_version,
        parser_version,
        normalization_version,
        resampling_version,
        data_version,
        lineage,
        len(candles),
        candles[0].open_time,
        candles[-1].close_time,
        rejection_count,
        exact_duplicate_count,
        conflict_count,
        gap_count,
        canonical_hash,
    )
    manifest_id = deterministic_id("historical-manifest", manifest_fields)
    manifest = DatasetManifest(
        manifest_version=_MANIFEST_VERSION,
        manifest_id=manifest_id,
        dataset_id=dataset_id,
        symbol=candles[0].symbol,
        timeframe=candles[0].timeframe,
        source_content_hashes=source_content_hashes,
        raw_data_version=raw_data_version(source_content_hashes),
        historical_semantics_version=historical_semantics_version,
        parser_version=parser_version,
        normalization_version=normalization_version,
        resampling_version=resampling_version,
        data_version=data_version,
        lineage=lineage,
        candle_count=len(candles),
        first_open_time=candles[0].open_time,
        last_close_time=candles[-1].close_time,
        rejection_count=rejection_count,
        exact_duplicate_count=exact_duplicate_count,
        conflict_count=conflict_count,
        gap_count=gap_count,
        canonical_hash=canonical_hash,
    )
    dataset = HistoricalDataset(
        dataset_id,
        candles[0].symbol,
        candles[0].timeframe,
        candles[0].open_time,
        candles[-1].close_time,
        len(candles),
        candles,
        source,
        data_version,
        manifest_id,
        gap_count,
        conflict_count,
        HistoricalDatasetStatus.VALID,
        gap_count == 0 and conflict_count == 0,
    )
    return dataset, manifest


def _failed_report(
    data_version: str,
    total: int,
    accepted: int,
    rejected: int,
    reasons: tuple[ReasonCode, ...],
    *,
    exact: int = 0,
    conflicts: int = 0,
    disorder: int = 0,
    gaps: tuple[Gap, ...] = (),
    symbol: str | None = None,
    timeframe: Timeframe | None = None,
) -> DataQualityReport:
    return DataQualityReport(
        total,
        accepted,
        rejected,
        exact,
        conflicts,
        len(gaps),
        disorder,
        None,
        None,
        symbol,
        timeframe,
        data_version,
        tuple(gaps),
        reasons,
    )


def ingest_csv_files(
    paths: tuple[Path, ...],
    config: HistoricalConfig,
) -> HistoricalIngestionResult:
    semantics_version = historical_semantics_version(config)
    parser = CsvHistoricalDataParser(config.column_mapping)
    raw_records: list[RawHistoricalRecord] = []
    content_hashes: list[str] = []
    try:
        for path in paths:
            content_hash = sha256_file(path)
            content_hashes.append(content_hash)
            records = tuple(parser.parse(path, config.source_name))
            if any(record.source_content_hash != content_hash for record in records):
                raise HistoricalParserError("historical CSV changed while it was being read")
            raw_records.extend(records)
    except (HistoricalParserError, OSError) as error:
        failed_version = deterministic_id(
            "historical-ingestion-failed", semantics_version, str(error)
        )
        rejection = HistoricalRejection(None, "", None, (ReasonCode.DATA_MISSING,), str(error))
        report = _failed_report(failed_version, len(raw_records), 0, 1, rejection.reason_codes)
        return HistoricalIngestionResult(
            HistoricalIngestionStatus.FAILED, None, None, report, (rejection,)
        )
    if not raw_records:
        version = deterministic_id("historical-empty", semantics_version)
        rejection = HistoricalRejection(
            None, "", None, (ReasonCode.DATA_MISSING,), "historical input has no records"
        )
        return HistoricalIngestionResult(
            HistoricalIngestionStatus.FAILED,
            None,
            None,
            _failed_report(version, 0, 0, 1, rejection.reason_codes),
            (rejection,),
        )
    hashes = tuple(sorted(content_hashes))
    data_version = historical_data_version(hashes, semantics_version)
    normalized = tuple(normalize_record(record, config, data_version) for record in raw_records)
    rejections = tuple(
        HistoricalRejection(
            result.raw_record_id,
            raw.source_file,
            raw.source_row,
            result.reason_codes,
            result.detail or "normalization rejected",
        )
        for raw, result in zip(raw_records, normalized, strict=True)
        if result.candle is None
    )
    accepted = tuple(result.candle for result in normalized if result.candle is not None)
    if not accepted:
        report = _failed_report(
            data_version,
            len(raw_records),
            0,
            len(rejections),
            tuple(
                dict.fromkeys(code for rejection in rejections for code in rejection.reason_codes)
            ),
        )
        return HistoricalIngestionResult(
            HistoricalIngestionStatus.FAILED, None, None, report, rejections
        )
    identities = {(candle.symbol, candle.timeframe) for candle in accepted}
    if len(identities) != 1 or next(iter(identities))[1] is not config.canonical_timeframe:
        rejection = HistoricalRejection(
            None,
            "",
            None,
            (ReasonCode.TIMEFRAME_UNSYNCED,),
            "one ingestion must contain one canonical M5 symbol/timeframe",
        )
        report = _failed_report(
            data_version,
            len(raw_records),
            len(accepted),
            len(rejections) + 1,
            rejection.reason_codes,
        )
        return HistoricalIngestionResult(
            HistoricalIngestionStatus.FAILED, None, None, report, (*rejections, rejection)
        )
    deduped = deduplicate_and_sort(accepted)
    gaps = detect_gaps(deduped.candles)
    symbol, timeframe = next(iter(identities))
    reasons = list(deduped.reason_codes)
    if gaps:
        reasons.append(ReasonCode.DATA_GAP)
    report = DataQualityReport(
        len(raw_records),
        len(accepted),
        len(rejections),
        deduped.exact_duplicate_count,
        deduped.conflicting_duplicate_count,
        len(gaps),
        deduped.out_of_order_count,
        deduped.candles[0].open_time,
        deduped.candles[-1].close_time,
        symbol,
        timeframe,
        data_version,
        gaps,
        tuple(dict.fromkeys(reasons)),
    )
    if deduped.conflicting_duplicate_count or gaps:
        return HistoricalIngestionResult(
            HistoricalIngestionStatus.FAILED, None, None, report, rejections
        )
    if rejections:
        return HistoricalIngestionResult(
            HistoricalIngestionStatus.PARTIAL, None, None, report, rejections
        )
    dataset, manifest = _manifest_and_dataset(
        deduped.candles,
        source=config.source_name,
        source_content_hashes=hashes,
        data_version=data_version,
        historical_semantics_version=semantics_version,
        parser_version=config.parser_version,
        normalization_version=config.normalization_version,
        resampling_version=None,
        exact_duplicate_count=deduped.exact_duplicate_count,
    )
    return HistoricalIngestionResult(
        HistoricalIngestionStatus.SUCCESS, dataset, manifest, report, ()
    )


def resample_dataset(
    source: HistoricalDataset,
    source_manifest: DatasetManifest,
    target_timeframe: Timeframe,
    *,
    algorithm_version: str,
) -> DerivedDatasetResult:
    if (
        source_manifest.dataset_id != source.dataset_id
        or source_manifest.data_version != source.data_version
        or source_manifest.timeframe is not source.timeframe
    ):
        raise HistoricalDataError("source dataset and manifest lineage do not match")
    relationship = (source.timeframe, target_timeframe)
    if relationship not in _ALLOWED_RESAMPLING:
        raise HistoricalDataError("unsupported or downward resampling relationship")
    source_interval = _INTERVALS[source.timeframe]
    target_interval = _INTERVALS[target_timeframe]
    child_count = target_interval // source_interval
    if source.start_time != source.start_time.replace(
        minute=0 if target_timeframe is Timeframe.H1 else source.start_time.minute // 15 * 15,
        second=0,
        microsecond=0,
    ):
        raise HistoricalDataError("source begins on a misaligned target boundary")
    if len(source.candles) % child_count:
        raise HistoricalDataError("insufficient child candles for complete resampling")
    output_data_version = derived_data_version(
        source.data_version,
        source.timeframe,
        target_timeframe,
        algorithm_version,
    )
    derived: list[Candle] = []
    for offset in range(0, len(source.candles), child_count):
        group = source.candles[offset : offset + child_count]
        expected_opens = tuple(group[0].open_time + source_interval * i for i in range(child_count))
        if tuple(candle.open_time for candle in group) != expected_opens:
            raise HistoricalDataError("resampling child gap or misalignment")
        close_time = group[0].open_time + target_interval
        if group[-1].close_time != close_time:
            raise HistoricalDataError("resampling children do not cover target interval")
        child_ids = tuple(candle.candle_id for candle in group)
        source_name = f"derived:{source.timeframe.value}->{target_timeframe.value}"
        derived.append(
            Candle(
                deterministic_id(
                    "derived-candle",
                    child_ids,
                    target_timeframe,
                    algorithm_version,
                    source.data_version,
                    output_data_version,
                ),
                source.symbol,
                target_timeframe,
                group[0].open_time,
                close_time,
                close_time,
                close_time,
                group[0].open,
                max(candle.high for candle in group),
                min(candle.low for candle in group),
                group[-1].close,
                sum((candle.volume for candle in group), start=group[0].volume * 0),
                True,
                source_name,
                output_data_version,
            )
        )
    dataset, manifest = _manifest_and_dataset(
        tuple(derived),
        source=f"derived:{source.timeframe.value}->{target_timeframe.value}",
        source_content_hashes=source_manifest.source_content_hashes,
        data_version=output_data_version,
        historical_semantics_version=source_manifest.historical_semantics_version,
        parser_version=source_manifest.parser_version,
        normalization_version=source_manifest.normalization_version,
        resampling_version=algorithm_version,
        lineage=DerivedDatasetLineage(
            source.dataset_id,
            source.data_version,
            source.timeframe,
            target_timeframe,
            algorithm_version,
        ),
    )
    return DerivedDatasetResult(dataset, manifest)
