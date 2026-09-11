from datetime import UTC, datetime
from pathlib import Path

import pytest

from trading_bot.application.dtos import OrderIntentRecord
from trading_bot.domain.enums import JournalEventType, OrderPurpose
from trading_bot.domain.errors import PersistenceError
from trading_bot.domain.risk_models import JournalEvent
from trading_bot.infrastructure.sqlite_journal import SQLiteJournal


def test_append_is_idempotent_and_revision_guarded(tmp_path):
    journal = SQLiteJournal(tmp_path / "journal.db", Path("migrations/001_initial.sql"))
    now = datetime(2026, 1, 1, tzinfo=UTC)
    event = JournalEvent(
        "event-1",
        "trade-1",
        0,
        JournalEventType.DECISION_EVALUATED,
        now,
        {"decision": "NO_TRADE"},
    )
    first = journal.append(event, expected_stream_revision=-1)
    duplicate = journal.append(event, expected_stream_revision=0)
    assert first.event == duplicate.event
    assert len(journal.get_stream("trade-1")) == 1
    conflict = JournalEvent(
        "event-1",
        "trade-1",
        0,
        JournalEventType.DECISION_EVALUATED,
        now,
        {"decision": "LONG"},
    )
    with pytest.raises(PersistenceError, match="different content"):
        journal.append(conflict, expected_stream_revision=0)
    invalid = JournalEvent("event-2", "trade-1", 2, JournalEventType.RISK_EVALUATED, now, {})
    with pytest.raises(PersistenceError, match="does not follow"):
        journal.append(invalid, expected_stream_revision=0)

    assert journal.reserve_evaluation("evaluation-1", "decision-1")
    assert not journal.reserve_evaluation("evaluation-1", "decision-1")
    with pytest.raises(PersistenceError, match="evaluation ID conflict"):
        journal.reserve_evaluation("evaluation-1", "decision-2")

    intent = OrderIntentRecord("client-1", "plan-1", OrderPurpose.ENTRY, now)
    assert journal.reserve_order_intent(intent)
    assert not journal.reserve_order_intent(intent)
    duplicate_logical_order = OrderIntentRecord("client-2", "plan-1", OrderPurpose.ENTRY, now)
    with pytest.raises(PersistenceError, match="logical order intent"):
        journal.reserve_order_intent(duplicate_logical_order)
    journal.close()
