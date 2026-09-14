"""Append-only SQLite persistence for PHASE 7 benchmark evidence."""

from __future__ import annotations

import sqlite3
from contextlib import suppress
from pathlib import Path

from trading_bot.ai.models import AIBenchmarkRun
from trading_bot.domain.errors import PersistenceError
from trading_bot.domain.primitives import canonical_json

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_benchmark_protocols (
    protocol_id TEXT PRIMARY KEY,
    protocol_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_analysis_requests (
    request_id TEXT PRIMARY KEY,
    request_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_benchmark_cases (
    case_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    case_json TEXT NOT NULL,
    FOREIGN KEY(request_id) REFERENCES ai_analysis_requests(request_id)
);
CREATE TABLE IF NOT EXISTS ai_provider_invocations (
    invocation_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    invocation_json TEXT NOT NULL,
    FOREIGN KEY(request_id) REFERENCES ai_analysis_requests(request_id)
);
CREATE TABLE IF NOT EXISTS ai_analysis_responses (
    response_id TEXT PRIMARY KEY,
    invocation_id TEXT NOT NULL UNIQUE,
    response_json TEXT NOT NULL,
    FOREIGN KEY(invocation_id) REFERENCES ai_provider_invocations(invocation_id)
);
CREATE TABLE IF NOT EXISTS ai_benchmark_metrics (
    metrics_id TEXT PRIMARY KEY,
    protocol_id TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    FOREIGN KEY(protocol_id) REFERENCES ai_benchmark_protocols(protocol_id)
);
CREATE TABLE IF NOT EXISTS ai_benchmark_runs (
    run_id TEXT PRIMARY KEY,
    protocol_id TEXT NOT NULL,
    metrics_id TEXT NOT NULL,
    run_json TEXT NOT NULL,
    FOREIGN KEY(protocol_id) REFERENCES ai_benchmark_protocols(protocol_id),
    FOREIGN KEY(metrics_id) REFERENCES ai_benchmark_metrics(metrics_id)
);
CREATE TABLE IF NOT EXISTS ai_benchmark_run_cases (
    run_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    case_id TEXT NOT NULL,
    PRIMARY KEY(run_id, sequence),
    UNIQUE(run_id, case_id),
    FOREIGN KEY(run_id) REFERENCES ai_benchmark_runs(run_id),
    FOREIGN KEY(case_id) REFERENCES ai_benchmark_cases(case_id)
);
CREATE TABLE IF NOT EXISTS ai_benchmark_run_responses (
    run_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    response_id TEXT NOT NULL,
    PRIMARY KEY(run_id, sequence),
    UNIQUE(run_id, response_id),
    FOREIGN KEY(run_id) REFERENCES ai_benchmark_runs(run_id),
    FOREIGN KEY(response_id) REFERENCES ai_analysis_responses(response_id)
);
"""


class SQLiteAIBenchmarkRepository:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._connection = sqlite3.connect(path)
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.executescript(_SCHEMA)
            self._connection.commit()
        except sqlite3.Error as error:
            raise PersistenceError(f"cannot initialize AI benchmark repository: {error}") from error

    def close(self) -> None:
        self._connection.close()

    def append_run(self, run: AIBenchmarkRun) -> None:
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._append_exact(
                "ai_benchmark_protocols",
                "protocol_id",
                run.protocol.protocol_id,
                "protocol_json",
                canonical_json(run.protocol),
            )
            for case in run.cases:
                self._append_exact(
                    "ai_analysis_requests",
                    "request_id",
                    case.request.request_id,
                    "request_json",
                    canonical_json(case.request),
                )
                self._append_case(
                    case.case_id,
                    case.request.request_id,
                    canonical_json(case),
                )
            for invocation in run.invocations:
                self._append_invocation(
                    invocation.invocation_id,
                    invocation.request_id,
                    canonical_json(invocation),
                )
            for response in run.responses:
                self._append_response(
                    response.response_id,
                    response.invocation_id,
                    canonical_json(response),
                )
            self._append_metrics(
                run.metrics.metrics_id,
                run.protocol.protocol_id,
                canonical_json(run.metrics),
            )
            self._append_run_row(
                run.run_id,
                run.protocol.protocol_id,
                run.metrics.metrics_id,
                canonical_json(run),
            )
            self._append_links(run)
            self._connection.commit()
        except PersistenceError:
            self._rollback()
            raise
        except sqlite3.IntegrityError as error:
            self._rollback()
            raise PersistenceError(f"AI benchmark identity conflict: {error}") from error
        except sqlite3.Error as error:
            self._rollback()
            raise PersistenceError(f"AI benchmark append failed: {error}") from error

    def _append_exact(
        self,
        table: str,
        id_column: str,
        identifier: str,
        json_column: str,
        content: str,
    ) -> None:
        existing = self._connection.execute(
            f"SELECT {json_column} FROM {table} WHERE {id_column} = ?", (identifier,)
        ).fetchone()
        if existing is None:
            self._connection.execute(
                f"INSERT INTO {table} ({id_column}, {json_column}) VALUES (?, ?)",
                (identifier, content),
            )
        elif existing[0] != content:
            raise PersistenceError(f"{table} identity conflicts with stored content")

    def _append_case(self, case_id: str, request_id: str, content: str) -> None:
        self._append_multi(
            "ai_benchmark_cases",
            "case_id",
            case_id,
            ("request_id", "case_json"),
            (request_id, content),
        )

    def _append_invocation(self, invocation_id: str, request_id: str, content: str) -> None:
        self._append_multi(
            "ai_provider_invocations",
            "invocation_id",
            invocation_id,
            ("request_id", "invocation_json"),
            (request_id, content),
        )

    def _append_response(self, response_id: str, invocation_id: str, content: str) -> None:
        self._append_multi(
            "ai_analysis_responses",
            "response_id",
            response_id,
            ("invocation_id", "response_json"),
            (invocation_id, content),
        )

    def _append_metrics(self, metrics_id: str, protocol_id: str, content: str) -> None:
        self._append_multi(
            "ai_benchmark_metrics",
            "metrics_id",
            metrics_id,
            ("protocol_id", "metrics_json"),
            (protocol_id, content),
        )

    def _append_run_row(self, run_id: str, protocol_id: str, metrics_id: str, content: str) -> None:
        self._append_multi(
            "ai_benchmark_runs",
            "run_id",
            run_id,
            ("protocol_id", "metrics_id", "run_json"),
            (protocol_id, metrics_id, content),
        )

    def _append_multi(
        self,
        table: str,
        id_column: str,
        identifier: str,
        columns: tuple[str, ...],
        values: tuple[str, ...],
    ) -> None:
        selected = ", ".join(columns)
        existing = self._connection.execute(
            f"SELECT {selected} FROM {table} WHERE {id_column} = ?", (identifier,)
        ).fetchone()
        if existing is None:
            names = ", ".join((id_column, *columns))
            placeholders = ", ".join("?" for _ in range(len(values) + 1))
            self._connection.execute(
                f"INSERT INTO {table} ({names}) VALUES ({placeholders})",
                (identifier, *values),
            )
        elif tuple(str(item) for item in existing) != values:
            raise PersistenceError(f"{table} identity conflicts with stored content")

    def _append_links(self, run: AIBenchmarkRun) -> None:
        existing_cases = self._connection.execute(
            "SELECT sequence, case_id FROM ai_benchmark_run_cases "
            "WHERE run_id = ? ORDER BY sequence",
            (run.run_id,),
        ).fetchall()
        expected_cases = tuple(enumerate(item.case_id for item in run.cases))
        self._append_link_rows(
            "ai_benchmark_run_cases", "case_id", run.run_id, existing_cases, expected_cases
        )
        existing_responses = self._connection.execute(
            "SELECT sequence, response_id FROM ai_benchmark_run_responses "
            "WHERE run_id = ? ORDER BY sequence",
            (run.run_id,),
        ).fetchall()
        expected_responses = tuple(enumerate(item.response_id for item in run.responses))
        self._append_link_rows(
            "ai_benchmark_run_responses",
            "response_id",
            run.run_id,
            existing_responses,
            expected_responses,
        )

    def _append_link_rows(
        self,
        table: str,
        value_column: str,
        run_id: str,
        existing: list[tuple[object, object]],
        expected: tuple[tuple[int, str], ...],
    ) -> None:
        normalized = tuple((int(str(item[0])), str(item[1])) for item in existing)
        if normalized and normalized != expected:
            raise PersistenceError(f"{table} links conflict with stored content")
        if not normalized:
            self._connection.executemany(
                f"INSERT INTO {table} (run_id, sequence, {value_column}) VALUES (?, ?, ?)",
                ((run_id, sequence, identifier) for sequence, identifier in expected),
            )

    def _rollback(self) -> None:
        with suppress(sqlite3.Error):
            self._connection.rollback()

    def get_run_json(self, run_id: str) -> str:
        row = self._connection.execute(
            "SELECT run_json FROM ai_benchmark_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise PersistenceError("unknown AI benchmark run")
        return str(row[0])

    def list_run_ids(self, *, offset: int = 0, limit: int = 100) -> tuple[str, ...]:
        if offset < 0 or not 1 <= limit <= 100:
            raise PersistenceError("invalid AI benchmark pagination")
        rows = self._connection.execute(
            "SELECT run_id FROM ai_benchmark_runs ORDER BY run_id LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return tuple(str(row[0]) for row in rows)
