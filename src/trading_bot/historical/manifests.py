"""Content hashing and path-independent historical version identities."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from trading_bot.config.models import HistoricalConfig
from trading_bot.domain.identifiers import deterministic_id
from trading_bot.domain.primitives import canonical_json


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def historical_semantics(config: HistoricalConfig) -> dict[str, object]:
    """Return only content semantics; physical path and ingestion time are excluded."""
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
        "resampling_version": config.resampling_version,
    }


def historical_data_version(
    source_content_hashes: tuple[str, ...], config: HistoricalConfig, config_version: str
) -> str:
    return deterministic_id(
        "historical-data-version",
        tuple(sorted(source_content_hashes)),
        historical_semantics(config),
        config_version,
    )


def canonical_candle_hash(candles: tuple[object, ...]) -> str:
    return sha256(canonical_json(candles).encode("utf-8")).hexdigest()
