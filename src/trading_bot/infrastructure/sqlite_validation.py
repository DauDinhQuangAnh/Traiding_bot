"""Append-only SQLite adapter for canonical PHASE 6 evidence."""

from __future__ import annotations

import sqlite3
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

from trading_bot.domain.errors import PersistenceError
from trading_bot.domain.primitives import canonical_json
from trading_bot.validation.models import TestConsumptionRecord, ValidationRun

_SCHEMA = """
CREATE TABLE IF NOT EXISTS validation_protocols (
    protocol_id TEXT PRIMARY KEY,
    protocol_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS validation_runs (
    validation_run_id TEXT PRIMARY KEY,
    protocol_id TEXT NOT NULL,
    result_json TEXT NOT NULL,
    FOREIGN KEY(protocol_id) REFERENCES validation_protocols(protocol_id)
);
CREATE TABLE IF NOT EXISTS partition_results (
    validation_run_id TEXT NOT NULL,
    partition_result_id TEXT NOT NULL,
    result_json TEXT NOT NULL,
    PRIMARY KEY(validation_run_id, partition_result_id),
    FOREIGN KEY(validation_run_id) REFERENCES validation_runs(validation_run_id)
);
CREATE TABLE IF NOT EXISTS walk_forward_windows (
    validation_run_id TEXT NOT NULL,
    window_id TEXT NOT NULL,
    result_json TEXT NOT NULL,
    PRIMARY KEY(validation_run_id, window_id),
    FOREIGN KEY(validation_run_id) REFERENCES validation_runs(validation_run_id)
);
CREATE TABLE IF NOT EXISTS sensitivity_results (
    validation_run_id TEXT NOT NULL,
    sensitivity_id TEXT NOT NULL,
    result_json TEXT NOT NULL,
    PRIMARY KEY(validation_run_id, sensitivity_id),
    FOREIGN KEY(validation_run_id) REFERENCES validation_runs(validation_run_id)
);
CREATE TABLE IF NOT EXISTS stress_results (
    validation_run_id TEXT NOT NULL,
    stress_id TEXT NOT NULL,
    result_json TEXT NOT NULL,
    PRIMARY KEY(validation_run_id, stress_id),
    FOREIGN KEY(validation_run_id) REFERENCES validation_runs(validation_run_id)
);
CREATE TABLE IF NOT EXISTS benchmark_results (
    validation_run_id TEXT NOT NULL,
    benchmark_id TEXT NOT NULL,
    result_json TEXT NOT NULL,
    PRIMARY KEY(validation_run_id, benchmark_id),
    FOREIGN KEY(validation_run_id) REFERENCES validation_runs(validation_run_id)
);
CREATE TABLE IF NOT EXISTS validation_test_consumptions (
    protocol_id TEXT NOT NULL,
    consumption_index INTEGER NOT NULL,
    consumption_event_id TEXT NOT NULL UNIQUE,
    validation_run_id TEXT NOT NULL UNIQUE,
    evidence_json TEXT NOT NULL,
    PRIMARY KEY(protocol_id, consumption_index),
    FOREIGN KEY(protocol_id) REFERENCES validation_protocols(protocol_id),
    FOREIGN KEY(validation_run_id) REFERENCES validation_runs(validation_run_id)
);
"""


class SQLiteValidationRepository:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._connection = sqlite3.connect(path)
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.executescript(_SCHEMA)
            self._connection.commit()
            runs = self._connection.execute("SELECT COUNT(*) FROM validation_runs").fetchone()[0]
            consumptions = self._connection.execute(
                "SELECT COUNT(*) FROM validation_test_consumptions"
            ).fetchone()[0]
            legacy_partition_identity = any(
                bool(row[2])
                and tuple(
                    str(column[0])
                    for column in self._connection.execute(
                        "SELECT name FROM pragma_index_info(?) ORDER BY seqno",
                        (str(row[1]),),
                    ).fetchall()
                )
                == ("partition_result_id",)
                for row in self._connection.execute(
                    "PRAGMA index_list('partition_results')"
                ).fetchall()
            )
            if runs != consumptions or legacy_partition_identity:
                self._connection.close()
                raise PersistenceError(
                    "unsupported validation repository schema: existing evidence lacks "
                    "the current append-only TEST consumption identity"
                )
        except sqlite3.Error as error:
            raise PersistenceError(f"cannot initialize validation repository: {error}") from error

    def close(self) -> None:
        self._connection.close()

    def append_result(self, result: ValidationRun) -> TestConsumptionRecord:
        evidence = replace(
            result,
            protocol=replace(result.protocol, test_evaluation_count=0),
            test_consumption_index=None,
        )
        evidence_json = canonical_json(evidence)
        protocol_json = canonical_json(replace(result.protocol, test_evaluation_count=0))
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            existing_event = self._connection.execute(
                "SELECT protocol_id, consumption_index, validation_run_id, evidence_json "
                "FROM validation_test_consumptions WHERE consumption_event_id = ?",
                (result.test_consumption_event_id,),
            ).fetchone()
            if existing_event is not None:
                if (
                    existing_event[0] != result.protocol.protocol_id
                    or existing_event[2] != result.validation_run_id
                    or existing_event[3] != evidence_json
                ):
                    raise PersistenceError("TEST consumption event conflicts with stored content")
                self._connection.commit()
                return TestConsumptionRecord(
                    str(existing_event[0]),
                    result.test_consumption_event_id,
                    int(existing_event[1]),
                    str(existing_event[2]),
                )
            stored_protocol = self._connection.execute(
                "SELECT protocol_json FROM validation_protocols WHERE protocol_id = ?",
                (result.protocol.protocol_id,),
            ).fetchone()
            if stored_protocol is not None and stored_protocol[0] != protocol_json:
                raise PersistenceError("validation protocol ID conflicts with stored content")
            next_index = int(
                self._connection.execute(
                    "SELECT COALESCE(MAX(consumption_index), 0) + 1 "
                    "FROM validation_test_consumptions WHERE protocol_id = ?",
                    (result.protocol.protocol_id,),
                ).fetchone()[0]
            )
            persisted = replace(
                result,
                protocol=replace(result.protocol, test_evaluation_count=next_index),
                test_consumption_index=next_index,
            )
            result_json = canonical_json(persisted)
            if stored_protocol is None:
                self._connection.execute(
                    "INSERT INTO validation_protocols VALUES (?, ?)",
                    (result.protocol.protocol_id, protocol_json),
                )
            self._connection.execute(
                "INSERT INTO validation_runs VALUES (?, ?, ?)",
                (result.validation_run_id, result.protocol.protocol_id, result_json),
            )
            self._connection.executemany(
                "INSERT INTO partition_results VALUES (?, ?, ?)",
                (
                    (result.validation_run_id, item.partition_result_id, canonical_json(item))
                    for item in result.partitions
                ),
            )
            self._connection.executemany(
                "INSERT INTO walk_forward_windows VALUES (?, ?, ?)",
                (
                    (result.validation_run_id, item.window.window_id, canonical_json(item))
                    for item in result.walk_forward
                ),
            )
            self._connection.executemany(
                "INSERT INTO sensitivity_results VALUES (?, ?, ?)",
                (
                    (result.validation_run_id, item.sensitivity_id, canonical_json(item))
                    for item in result.sensitivity
                ),
            )
            self._connection.executemany(
                "INSERT INTO stress_results VALUES (?, ?, ?)",
                (
                    (result.validation_run_id, item.stress_id, canonical_json(item))
                    for item in result.stress
                ),
            )
            self._connection.executemany(
                "INSERT INTO benchmark_results VALUES (?, ?, ?)",
                (
                    (result.validation_run_id, item.benchmark_id, canonical_json(item))
                    for item in result.benchmarks
                ),
            )
            self._connection.execute(
                "INSERT INTO validation_test_consumptions VALUES (?, ?, ?, ?, ?)",
                (
                    result.protocol.protocol_id,
                    next_index,
                    result.test_consumption_event_id,
                    result.validation_run_id,
                    evidence_json,
                ),
            )
            self._connection.commit()
            return TestConsumptionRecord(
                result.protocol.protocol_id,
                result.test_consumption_event_id,
                next_index,
                result.validation_run_id,
            )
        except PersistenceError:
            self._rollback()
            raise
        except sqlite3.IntegrityError as error:
            self._rollback()
            raise PersistenceError(f"validation identity conflict: {error}") from error
        except sqlite3.Error as error:
            self._rollback()
            raise PersistenceError(f"validation repository append failed: {error}") from error

    def _rollback(self) -> None:
        with suppress(sqlite3.Error):
            self._connection.rollback()

    def get_result_json(self, validation_run_id: str) -> str:
        row = self._connection.execute(
            "SELECT result_json FROM validation_runs WHERE validation_run_id = ?",
            (validation_run_id,),
        ).fetchone()
        if row is None:
            raise PersistenceError("unknown validation run")
        return str(row[0])

    def list_run_ids(self, *, offset: int = 0, limit: int = 100) -> tuple[str, ...]:
        if offset < 0 or not 1 <= limit <= 100:
            raise PersistenceError("invalid validation pagination")
        rows = self._connection.execute(
            "SELECT validation_run_id FROM validation_runs "
            "ORDER BY validation_run_id LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def list_test_consumptions(self, protocol_id: str) -> tuple[TestConsumptionRecord, ...]:
        rows = self._connection.execute(
            "SELECT consumption_event_id, consumption_index, validation_run_id "
            "FROM validation_test_consumptions WHERE protocol_id = ? "
            "ORDER BY consumption_index",
            (protocol_id,),
        ).fetchall()
        return tuple(
            TestConsumptionRecord(protocol_id, str(row[0]), int(row[1]), str(row[2]))
            for row in rows
        )
