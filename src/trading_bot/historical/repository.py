"""Point-in-time repository port and local SQLite implementation."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from trading_bot.domain.enums import Timeframe
from trading_bot.domain.errors import HistoricalDataError
from trading_bot.domain.market_models import Candle
from trading_bot.domain.primitives import canonical_json
from trading_bot.historical.models import DatasetManifest, HistoricalDataset


class HistoricalCandleRepository(Protocol):
    def append_dataset(self, dataset: HistoricalDataset, manifest: DatasetManifest) -> None: ...

    def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
        data_version: str,
    ) -> Sequence[Candle]: ...

    def latest_before(
        self,
        symbol: str,
        timeframe: Timeframe,
        as_of: datetime,
        count: int,
        data_version: str,
    ) -> Sequence[Candle]: ...


_SCHEMA = """
CREATE TABLE IF NOT EXISTS historical_datasets (
    dataset_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    data_version TEXT NOT NULL,
    manifest_id TEXT NOT NULL,
    dataset_json TEXT NOT NULL,
    UNIQUE(symbol, timeframe, data_version)
);
CREATE TABLE IF NOT EXISTS historical_manifests (
    manifest_id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL UNIQUE,
    manifest_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS historical_candles (
    data_version TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    open_time TEXT NOT NULL,
    candle_id TEXT NOT NULL,
    close_time TEXT NOT NULL,
    event_time TEXT NOT NULL,
    receive_time TEXT NOT NULL,
    open TEXT NOT NULL,
    high TEXT NOT NULL,
    low TEXT NOT NULL,
    close TEXT NOT NULL,
    volume TEXT NOT NULL,
    is_closed INTEGER NOT NULL CHECK(is_closed = 1),
    source TEXT NOT NULL,
    PRIMARY KEY(data_version, symbol, timeframe, open_time),
    UNIQUE(candle_id)
);
CREATE INDEX IF NOT EXISTS idx_historical_point_in_time
ON historical_candles(data_version, symbol, timeframe, close_time);
"""


class SQLiteHistoricalCandleRepository:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._connection = sqlite3.connect(path)
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.executescript(_SCHEMA)
            self._connection.commit()
        except sqlite3.Error as error:
            raise HistoricalDataError(
                f"cannot initialize historical repository: {error}"
            ) from error

    def close(self) -> None:
        self._connection.close()

    def append_dataset(self, dataset: HistoricalDataset, manifest: DatasetManifest) -> None:
        if not dataset.is_backtest_eligible or (
            manifest.dataset_id != dataset.dataset_id
            or manifest.manifest_id != dataset.manifest_id
            or manifest.data_version != dataset.data_version
            or manifest.symbol != dataset.symbol
            or manifest.timeframe is not dataset.timeframe
        ):
            raise HistoricalDataError("only matching backtest-eligible datasets can be appended")
        dataset_json = canonical_json(dataset)
        manifest_json = canonical_json(manifest)
        try:
            existing = self._connection.execute(
                "SELECT dataset_json FROM historical_datasets WHERE dataset_id = ?",
                (dataset.dataset_id,),
            ).fetchone()
            if existing is not None:
                if existing[0] != dataset_json:
                    raise HistoricalDataError("dataset ID conflicts with stored content")
                return
            with self._connection:
                self._connection.execute(
                    "INSERT INTO historical_datasets VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        dataset.dataset_id,
                        dataset.symbol,
                        dataset.timeframe.value,
                        dataset.data_version,
                        dataset.manifest_id,
                        dataset_json,
                    ),
                )
                self._connection.execute(
                    "INSERT INTO historical_manifests VALUES (?, ?, ?)",
                    (manifest.manifest_id, dataset.dataset_id, manifest_json),
                )
                self._connection.executemany(
                    "INSERT INTO historical_candles VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (self._candle_row(candle) for candle in dataset.candles),
                )
        except sqlite3.IntegrityError as error:
            raise HistoricalDataError(f"historical dataset identity conflict: {error}") from error
        except sqlite3.Error as error:
            raise HistoricalDataError(f"historical repository append failed: {error}") from error

    def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
        data_version: str,
    ) -> tuple[Candle, ...]:
        self._require_version(symbol, timeframe, data_version)
        rows = self._connection.execute(
            "SELECT candle_id, symbol, timeframe, open_time, close_time, event_time, "
            "receive_time, open, high, low, close, volume, is_closed, source, data_version "
            "FROM historical_candles WHERE data_version = ? AND symbol = ? AND timeframe = ? "
            "AND open_time >= ? AND close_time <= ? ORDER BY open_time",
            (data_version, symbol, timeframe.value, start.isoformat(), end.isoformat()),
        ).fetchall()
        return tuple(self._candle_from_row(row) for row in rows)

    def latest_before(
        self,
        symbol: str,
        timeframe: Timeframe,
        as_of: datetime,
        count: int,
        data_version: str,
    ) -> tuple[Candle, ...]:
        if count <= 0:
            raise HistoricalDataError("point-in-time count must be positive")
        self._require_version(symbol, timeframe, data_version)
        rows = self._connection.execute(
            "SELECT candle_id, symbol, timeframe, open_time, close_time, event_time, "
            "receive_time, open, high, low, close, volume, is_closed, source, data_version "
            "FROM historical_candles WHERE data_version = ? AND symbol = ? AND timeframe = ? "
            "AND close_time <= ? ORDER BY open_time DESC LIMIT ?",
            (data_version, symbol, timeframe.value, as_of.isoformat(), count),
        ).fetchall()
        return tuple(self._candle_from_row(row) for row in reversed(rows))

    def get_manifest_json(self, dataset_id: str) -> str:
        row = self._connection.execute(
            "SELECT manifest_json FROM historical_manifests WHERE dataset_id = ?", (dataset_id,)
        ).fetchone()
        if row is None:
            raise HistoricalDataError("unknown historical dataset")
        return str(row[0])

    def _require_version(self, symbol: str, timeframe: Timeframe, data_version: str) -> None:
        row = self._connection.execute(
            "SELECT 1 FROM historical_datasets WHERE symbol = ? AND timeframe = ? "
            "AND data_version = ?",
            (symbol, timeframe.value, data_version),
        ).fetchone()
        if row is None:
            raise HistoricalDataError("unknown historical data version")

    @staticmethod
    def _candle_row(candle: Candle) -> tuple[object, ...]:
        return (
            candle.data_version,
            candle.symbol,
            candle.timeframe.value,
            candle.open_time.isoformat(),
            candle.candle_id,
            candle.close_time.isoformat(),
            candle.event_time.isoformat(),
            candle.receive_time.isoformat(),
            format(candle.open, "f"),
            format(candle.high, "f"),
            format(candle.low, "f"),
            format(candle.close, "f"),
            format(candle.volume, "f"),
            1,
            candle.source,
        )

    @staticmethod
    def _candle_from_row(row: tuple[object, ...]) -> Candle:
        return Candle(
            str(row[0]),
            str(row[1]),
            Timeframe(str(row[2])),
            datetime.fromisoformat(str(row[3])),
            datetime.fromisoformat(str(row[4])),
            datetime.fromisoformat(str(row[5])),
            datetime.fromisoformat(str(row[6])),
            Decimal(str(row[7])),
            Decimal(str(row[8])),
            Decimal(str(row[9])),
            Decimal(str(row[10])),
            Decimal(str(row[11])),
            bool(row[12]),
            str(row[13]),
            str(row[14]),
        )
