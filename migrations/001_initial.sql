PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS journal_events (
    event_id TEXT PRIMARY KEY,
    stream_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 0),
    event_type TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    persisted_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE (stream_id, revision)
);

CREATE INDEX IF NOT EXISTS idx_journal_stream_revision
ON journal_events(stream_id, revision);

CREATE TABLE IF NOT EXISTS evaluation_keys (
    evaluation_id TEXT PRIMARY KEY,
    decision_record_id TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS order_intents (
    client_order_id TEXT PRIMARY KEY,
    approved_plan_id TEXT NOT NULL,
    purpose TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (approved_plan_id, purpose)
);
