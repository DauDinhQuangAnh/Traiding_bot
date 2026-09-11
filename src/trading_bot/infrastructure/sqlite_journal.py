"""Transactional append-only SQLite journal."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from trading_bot.application.dtos import OrderIntentRecord
from trading_bot.application.ports import PersistedEvent
from trading_bot.domain.enums import HealthStatus, JournalEventType
from trading_bot.domain.errors import PersistenceError
from trading_bot.domain.primitives import canonical_json
from trading_bot.domain.risk_models import JournalEvent
from trading_bot.domain.value_objects import ComponentHealth

_Result = TypeVar("_Result")


class SQLiteJournal:
    def __init__(self, path: Path, migration_path: Path, *, busy_timeout_ms: int = 5_000) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path)
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
        self._connection.executescript(migration_path.read_text(encoding="utf-8"))
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def append(
        self, event: JournalEvent, expected_stream_revision: int | None = None
    ) -> PersistedEvent:
        persisted_at = datetime.now(UTC)
        try:
            with self._connection:
                existing = self._connection.execute(
                    "SELECT stream_id, revision, event_type, observed_at, "
                    "persisted_at, payload_json FROM journal_events WHERE event_id = ?",
                    (event.event_id,),
                ).fetchone()
                if existing is not None:
                    persisted = self._row(event.event_id, existing)
                    if persisted.event != event:
                        raise PersistenceError("event ID conflict with different content")
                    return persisted
                latest = self._connection.execute(
                    "SELECT MAX(revision) FROM journal_events WHERE stream_id = ?",
                    (event.stream_id,),
                ).fetchone()[0]
                actual = -1 if latest is None else int(latest)
                if expected_stream_revision is not None and actual != expected_stream_revision:
                    raise PersistenceError(
                        f"revision conflict: expected {expected_stream_revision}, got {actual}"
                    )
                if event.revision != actual + 1:
                    raise PersistenceError(
                        f"event revision {event.revision} does not follow {actual}"
                    )
                self._connection.execute(
                    "INSERT INTO journal_events VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        event.event_id,
                        event.stream_id,
                        event.revision,
                        event.event_type.value,
                        event.observed_at.isoformat(),
                        persisted_at.isoformat(),
                        canonical_json(event.payload),
                    ),
                )
        except sqlite3.Error as error:
            raise PersistenceError(f"journal append failed: {error}") from error
        return PersistedEvent(event, persisted_at)

    def get_stream(
        self, stream_id: str, after_revision: int | None = None
    ) -> Sequence[PersistedEvent]:
        floor = -1 if after_revision is None else after_revision
        rows = self._connection.execute(
            "SELECT event_id, stream_id, revision, event_type, observed_at, "
            "persisted_at, payload_json FROM journal_events "
            "WHERE stream_id = ? AND revision > ? ORDER BY revision",
            (stream_id, floor),
        ).fetchall()
        return tuple(self._row(row[0], row[1:]) for row in rows)

    def reserve_evaluation(self, evaluation_id: str, decision_record_id: str) -> bool:
        row = self._connection.execute(
            "SELECT decision_record_id FROM evaluation_keys WHERE evaluation_id = ?",
            (evaluation_id,),
        ).fetchone()
        if row is not None:
            if row[0] != decision_record_id:
                raise PersistenceError("evaluation ID conflict with different decision")
            return False
        try:
            with self._connection:
                self._connection.execute(
                    "INSERT INTO evaluation_keys VALUES (?, ?)",
                    (evaluation_id, decision_record_id),
                )
        except sqlite3.Error as error:
            raise PersistenceError(f"evaluation reservation failed: {error}") from error
        return True

    def reserve_order_intent(self, intent: OrderIntentRecord) -> bool:
        row = self._connection.execute(
            "SELECT approved_plan_id, purpose, created_at FROM order_intents "
            "WHERE client_order_id = ?",
            (intent.client_order_id,),
        ).fetchone()
        expected = (intent.approved_plan_id, intent.purpose.value, intent.created_at.isoformat())
        if row is not None:
            if tuple(row) != expected:
                raise PersistenceError("client order ID conflict with different intent")
            return False
        try:
            with self._connection:
                self._connection.execute(
                    "INSERT INTO order_intents VALUES (?, ?, ?, ?)",
                    (intent.client_order_id, *expected),
                )
        except sqlite3.IntegrityError as error:
            raise PersistenceError(f"logical order intent already exists: {error}") from error
        except sqlite3.Error as error:
            raise PersistenceError(f"order-intent reservation failed: {error}") from error
        return True

    def transaction(self, operation: Callable[[], _Result]) -> _Result:
        try:
            with self._connection:
                return operation()
        except sqlite3.Error as error:
            raise PersistenceError(f"journal transaction failed: {error}") from error

    def health(self) -> ComponentHealth:
        observed_at = datetime.now(UTC)
        try:
            self._connection.execute("SELECT 1").fetchone()
        except sqlite3.Error:
            return ComponentHealth("journal", HealthStatus.UNHEALTHY, observed_at, ())
        return ComponentHealth("journal", HealthStatus.HEALTHY, observed_at, ())

    @staticmethod
    def _row(event_id: str, row: tuple[Any, ...]) -> PersistedEvent:
        stream_id, revision, event_type, observed_at, persisted_at, payload = row
        event = JournalEvent(
            event_id,
            str(stream_id),
            int(revision),
            JournalEventType(str(event_type)),
            datetime.fromisoformat(str(observed_at)),
            json.loads(str(payload)),
        )
        return PersistedEvent(event, datetime.fromisoformat(str(persisted_at)))
