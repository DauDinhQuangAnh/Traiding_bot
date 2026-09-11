"""Streaming source-agnostic parser contract and CSV implementation."""

from __future__ import annotations

import csv
from collections.abc import Iterable, Iterator, Mapping
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from trading_bot.domain.errors import HistoricalParserError
from trading_bot.domain.identifiers import deterministic_id
from trading_bot.domain.primitives import canonical_json
from trading_bot.historical.manifests import sha256_file
from trading_bot.historical.models import RawHistoricalRecord

RAW_FIELDS = (
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "symbol",
    "timeframe",
    "closed",
)


class HistoricalDataParser(Protocol):
    def parse(self, path: Path, source: str) -> Iterable[RawHistoricalRecord]: ...


class CsvHistoricalDataParser:
    def __init__(self, column_mapping: Mapping[str, str]) -> None:
        if set(column_mapping) != set(RAW_FIELDS):
            raise HistoricalParserError("CSV column mapping requires the exact raw field schema")
        self._columns = dict(column_mapping)

    def parse(self, path: Path, source: str) -> Iterator[RawHistoricalRecord]:
        try:
            content_hash = sha256_file(path)
            stream = path.open("r", encoding="utf-8", newline="")
        except OSError as error:
            raise HistoricalParserError(f"cannot read historical CSV: {error}") from error
        with stream:
            try:
                reader = csv.DictReader(stream)
                actual = set(reader.fieldnames or ())
                required = set(self._columns.values())
                if not required <= actual:
                    missing = sorted(required - actual)
                    raise HistoricalParserError(
                        f"historical CSV missing required columns: {missing}"
                    )
                for source_row, row in enumerate(reader, start=2):
                    values = {
                        field: "" if row.get(header) is None else str(row[header])
                        for field, header in self._columns.items()
                    }
                    payload_hash = sha256(canonical_json(values).encode("utf-8")).hexdigest()
                    record_id = deterministic_id(
                        "raw-historical-record", source, content_hash, source_row, payload_hash
                    )
                    yield RawHistoricalRecord(
                        record_id,
                        source,
                        path.name,
                        source_row,
                        values["symbol"],
                        values["timeframe"],
                        values["timestamp"],
                        values["open"],
                        values["high"],
                        values["low"],
                        values["close"],
                        values["volume"],
                        values["closed"],
                        content_hash,
                        payload_hash,
                    )
            except (UnicodeError, csv.Error) as error:
                raise HistoricalParserError(f"cannot parse historical CSV: {error}") from error
