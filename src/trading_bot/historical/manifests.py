"""Content hashing and path-independent historical version identities."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from trading_bot.config.models import HistoricalConfig
from trading_bot.domain.enums import Timeframe
from trading_bot.domain.identifiers import deterministic_id
from trading_bot.domain.primitives import canonical_json


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def historical_semantics(config: HistoricalConfig) -> dict[str, object]:
    """Return raw-to-canonical semantics; app and resampling config are excluded."""
    return {
        "raw_format": config.raw_format,
        "source_name": config.source_name,
        "symbol_mapping": config.symbol_mapping,
        "timeframe_mapping": config.timeframe_mapping,
        "column_mapping": config.column_mapping,
        "timestamp_convention": config.timestamp_convention,
        "timestamp_unit": config.timestamp_unit,
        "closed_values": config.closed_values,
        "conflict_policy": config.conflict_policy,
        "gap_policy": config.gap_policy,
        "canonical_timeframe": config.canonical_timeframe,
        "parser_version": config.parser_version,
        "normalization_version": config.normalization_version,
    }


def historical_semantics_version(config: HistoricalConfig) -> str:
    return deterministic_id("historical-semantics-v1", historical_semantics(config))


def raw_data_version(source_content_hashes: tuple[str, ...]) -> str:
    return deterministic_id("historical-raw-source-v1", tuple(sorted(source_content_hashes)))


def historical_data_version(source_content_hashes: tuple[str, ...], semantics_version: str) -> str:
    return deterministic_id(
        "canonical-historical-data-v1",
        raw_data_version(source_content_hashes),
        semantics_version,
    )


def derived_data_version(
    source_data_version: str,
    source_timeframe: Timeframe,
    target_timeframe: Timeframe,
    algorithm_version: str,
) -> str:
    return deterministic_id(
        "derived-historical-data-v1",
        source_data_version,
        source_timeframe,
        target_timeframe,
        algorithm_version,
    )


def canonical_candle_hash(candles: tuple[object, ...]) -> str:
    return sha256(canonical_json(candles).encode("utf-8")).hexdigest()
