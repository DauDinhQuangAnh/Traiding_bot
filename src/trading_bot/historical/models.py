"""Immutable contracts for raw, normalized, versioned historical data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise

from trading_bot.domain.enums import (
    HistoricalDatasetStatus,
    HistoricalIngestionStatus,
    NormalizationStatus,
    ReasonCode,
    Timeframe,
)
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.market_models import Candle, MarketSnapshot
from trading_bot.domain.primitives import require_non_empty, require_utc


@dataclass(frozen=True, slots=True)
class RawHistoricalRecord:
    raw_record_id: str
    source: str
    source_file: str
    source_row: int
    raw_symbol: str
    raw_timeframe: str
    raw_timestamp: str
    raw_open: str
    raw_high: str
    raw_low: str
    raw_close: str
    raw_volume: str
    raw_close_status: str
    source_content_hash: str
    payload_hash: str

    def __post_init__(self) -> None:
        for name in (
            "raw_record_id",
            "source",
            "source_file",
            "source_content_hash",
            "payload_hash",
        ):
            require_non_empty(getattr(self, name), name)
        if self.source_row < 2:
            raise DomainValidationError("CSV source_row must include header offset")


@dataclass(frozen=True, slots=True)
class HistoricalRejection:
    raw_record_id: str | None
    source_file: str
    source_row: int | None
    reason_codes: tuple[ReasonCode, ...]
    detail: str


@dataclass(frozen=True, slots=True)
class HistoricalNormalizationResult:
    raw_record_id: str
    status: NormalizationStatus
    candle: Candle | None
    reason_codes: tuple[ReasonCode, ...]
    detail: str | None

    def __post_init__(self) -> None:
        accepted = self.status is NormalizationStatus.ACCEPTED
        if accepted != (self.candle is not None):
            raise DomainValidationError("normalization status/candle mismatch")
        if accepted and self.reason_codes:
            raise DomainValidationError("accepted normalization cannot have rejection reasons")
        if not accepted and not self.reason_codes:
            raise DomainValidationError("rejected normalization requires a reason")


@dataclass(frozen=True, slots=True)
class Gap:
    symbol: str
    timeframe: Timeframe
    expected_open_time: datetime
    previous_open_time: datetime
    next_open_time: datetime
    missing_bar_count: int

    def __post_init__(self) -> None:
        for name in ("expected_open_time", "previous_open_time", "next_open_time"):
            require_utc(getattr(self, name), name)
        if self.missing_bar_count <= 0:
            raise DomainValidationError("gap missing_bar_count must be positive")


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    total_raw_records: int
    accepted_records: int
    rejected_records: int
    exact_duplicates: int
    conflicting_duplicates: int
    gap_count: int
    out_of_order_count: int
    first_timestamp: datetime | None
    last_timestamp: datetime | None
    symbol: str | None
    timeframe: Timeframe | None
    data_version: str
    gaps: tuple[Gap, ...]
    reason_codes: tuple[ReasonCode, ...]

    def __post_init__(self) -> None:
        for name in (
            "total_raw_records",
            "accepted_records",
            "rejected_records",
            "exact_duplicates",
            "conflicting_duplicates",
            "gap_count",
            "out_of_order_count",
        ):
            if getattr(self, name) < 0:
                raise DomainValidationError(f"{name} must be non-negative")
        if self.gap_count != len(self.gaps):
            raise DomainValidationError("gap_count must equal the number of gaps")
        if self.first_timestamp is not None:
            require_utc(self.first_timestamp, "first_timestamp")
        if self.last_timestamp is not None:
            require_utc(self.last_timestamp, "last_timestamp")


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    manifest_version: str
    manifest_id: str
    dataset_id: str
    symbol: str
    timeframe: Timeframe
    source_content_hashes: tuple[str, ...]
    parser_version: str
    normalization_version: str
    resampling_version: str
    code_version: str
    config_version: str
    data_version: str
    candle_count: int
    first_open_time: datetime
    last_close_time: datetime
    rejection_count: int
    exact_duplicate_count: int
    conflict_count: int
    gap_count: int
    canonical_hash: str

    def __post_init__(self) -> None:
        for name in (
            "manifest_version",
            "manifest_id",
            "dataset_id",
            "symbol",
            "parser_version",
            "normalization_version",
            "resampling_version",
            "code_version",
            "config_version",
            "data_version",
            "canonical_hash",
        ):
            require_non_empty(getattr(self, name), name)
        if self.candle_count <= 0 or not self.source_content_hashes:
            raise DomainValidationError("manifest requires candles and source hashes")
        require_utc(self.first_open_time, "first_open_time")
        require_utc(self.last_close_time, "last_close_time")


@dataclass(frozen=True, slots=True)
class HistoricalDataset:
    dataset_id: str
    symbol: str
    timeframe: Timeframe
    start_time: datetime
    end_time: datetime
    candle_count: int
    candles: tuple[Candle, ...]
    source: str
    data_version: str
    manifest_id: str
    gap_count: int
    conflict_count: int
    created_by_version: str
    status: HistoricalDatasetStatus
    is_backtest_eligible: bool

    def __post_init__(self) -> None:
        for name in (
            "dataset_id",
            "symbol",
            "source",
            "data_version",
            "manifest_id",
            "created_by_version",
        ):
            require_non_empty(getattr(self, name), name)
        require_utc(self.start_time, "start_time")
        require_utc(self.end_time, "end_time")
        if self.candle_count != len(self.candles) or self.candle_count <= 0:
            raise DomainValidationError("dataset candle_count mismatch")
        if (
            self.start_time != self.candles[0].open_time
            or self.end_time != self.candles[-1].close_time
        ):
            raise DomainValidationError("dataset boundary mismatch")
        if any(
            candle.symbol != self.symbol
            or candle.timeframe is not self.timeframe
            or candle.data_version != self.data_version
            for candle in self.candles
        ):
            raise DomainValidationError("dataset candle identity/version mismatch")
        interval = {
            Timeframe.M5: timedelta(minutes=5),
            Timeframe.M15: timedelta(minutes=15),
            Timeframe.H1: timedelta(hours=1),
        }[self.timeframe]
        if any(
            current.open_time - previous.open_time != interval
            for previous, current in pairwise(self.candles)
        ):
            raise DomainValidationError("valid dataset must be strictly ordered and gap-free")
        keys = {
            (candle.source, candle.symbol, candle.timeframe, candle.open_time)
            for candle in self.candles
        }
        if len(keys) != self.candle_count:
            raise DomainValidationError("valid dataset cannot contain duplicate canonical keys")
        if self.is_backtest_eligible != (
            self.status is HistoricalDatasetStatus.VALID
            and self.gap_count == 0
            and self.conflict_count == 0
        ):
            raise DomainValidationError("dataset eligibility does not match validity")


@dataclass(frozen=True, slots=True)
class HistoricalIngestionResult:
    status: HistoricalIngestionStatus
    dataset: HistoricalDataset | None
    manifest: DatasetManifest | None
    quality_report: DataQualityReport
    rejections: tuple[HistoricalRejection, ...]

    @property
    def is_backtest_eligible(self) -> bool:
        return self.dataset is not None and self.dataset.is_backtest_eligible


@dataclass(frozen=True, slots=True)
class DerivedDatasetResult:
    dataset: HistoricalDataset
    manifest: DatasetManifest


@dataclass(frozen=True, slots=True)
class SnapshotSequenceResult:
    snapshots: tuple[MarketSnapshot, ...]
    skipped_warmup: int
    failures: tuple[tuple[datetime, tuple[ReasonCode, ...], str | None], ...]
