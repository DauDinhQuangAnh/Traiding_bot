"""SQLite adapter for immutable PHASE 5 backtest artifacts."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from trading_bot.backtest.models import BacktestResult
from trading_bot.domain.errors import PersistenceError
from trading_bot.domain.primitives import canonical_json

_SCHEMA = """
CREATE TABLE IF NOT EXISTS backtest_runs (
    backtest_run_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    result_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS backtest_events (
    backtest_run_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    event_id TEXT NOT NULL UNIQUE,
    event_json TEXT NOT NULL,
    PRIMARY KEY(backtest_run_id, sequence),
    FOREIGN KEY(backtest_run_id) REFERENCES backtest_runs(backtest_run_id)
);
CREATE TABLE IF NOT EXISTS backtest_orders (
    backtest_run_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    order_json TEXT NOT NULL,
    PRIMARY KEY(backtest_run_id, order_id),
    FOREIGN KEY(backtest_run_id) REFERENCES backtest_runs(backtest_run_id)
);
CREATE TABLE IF NOT EXISTS backtest_fills (
    backtest_run_id TEXT NOT NULL,
    fill_id TEXT NOT NULL,
    fill_json TEXT NOT NULL,
    PRIMARY KEY(backtest_run_id, fill_id),
    FOREIGN KEY(backtest_run_id) REFERENCES backtest_runs(backtest_run_id)
);
CREATE TABLE IF NOT EXISTS backtest_funding (
    backtest_run_id TEXT NOT NULL,
    funding_id TEXT NOT NULL,
    funding_json TEXT NOT NULL,
    PRIMARY KEY(backtest_run_id, funding_id),
    FOREIGN KEY(backtest_run_id) REFERENCES backtest_runs(backtest_run_id)
);
CREATE TABLE IF NOT EXISTS backtest_trades (
    backtest_run_id TEXT NOT NULL,
    trade_id TEXT NOT NULL,
    trade_json TEXT NOT NULL,
    PRIMARY KEY(backtest_run_id, trade_id),
    FOREIGN KEY(backtest_run_id) REFERENCES backtest_runs(backtest_run_id)
);
CREATE TABLE IF NOT EXISTS backtest_equity_curve (
    backtest_run_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    point_json TEXT NOT NULL,
    PRIMARY KEY(backtest_run_id, sequence),
    FOREIGN KEY(backtest_run_id) REFERENCES backtest_runs(backtest_run_id)
);
CREATE TABLE IF NOT EXISTS backtest_metrics (
    backtest_run_id TEXT PRIMARY KEY,
    metrics_json TEXT NOT NULL,
    FOREIGN KEY(backtest_run_id) REFERENCES backtest_runs(backtest_run_id)
);
"""


class SQLiteBacktestRepository:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._connection = sqlite3.connect(path)
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.executescript(_SCHEMA)
            self._connection.commit()
        except sqlite3.Error as error:
            raise PersistenceError(f"cannot initialize backtest repository: {error}") from error

    def close(self) -> None:
        self._connection.close()

    def append_result(self, result: BacktestResult) -> None:
        run_id = result.run.spec.backtest_run_id
        result_json = canonical_json(result)
        existing = self._connection.execute(
            "SELECT result_json FROM backtest_runs WHERE backtest_run_id = ?", (run_id,)
        ).fetchone()
        if existing is not None:
            if existing[0] != result_json:
                raise PersistenceError("backtest run ID conflicts with stored content")
            return
        try:
            with self._connection:
                self._connection.execute(
                    "INSERT INTO backtest_runs VALUES (?, ?, ?)",
                    (run_id, result.run.status.value, result_json),
                )
                self._connection.executemany(
                    "INSERT INTO backtest_events VALUES (?, ?, ?, ?)",
                    (
                        (run_id, event.sequence, event.event_id, canonical_json(event))
                        for event in result.events
                    ),
                )
                self._connection.executemany(
                    "INSERT INTO backtest_orders VALUES (?, ?, ?)",
                    ((run_id, order.order_id, canonical_json(order)) for order in result.orders),
                )
                self._connection.executemany(
                    "INSERT INTO backtest_fills VALUES (?, ?, ?)",
                    ((run_id, fill.fill_id, canonical_json(fill)) for fill in result.fills),
                )
                self._connection.executemany(
                    "INSERT INTO backtest_funding VALUES (?, ?, ?)",
                    (
                        (run_id, funding.funding_id, canonical_json(funding))
                        for funding in result.funding
                    ),
                )
                self._connection.executemany(
                    "INSERT INTO backtest_trades VALUES (?, ?, ?)",
                    ((run_id, trade.trade_id, canonical_json(trade)) for trade in result.trades),
                )
                self._connection.executemany(
                    "INSERT INTO backtest_equity_curve VALUES (?, ?, ?)",
                    (
                        (run_id, sequence, canonical_json(point))
                        for sequence, point in enumerate(result.equity_curve)
                    ),
                )
                self._connection.execute(
                    "INSERT INTO backtest_metrics VALUES (?, ?)",
                    (run_id, canonical_json(result.metrics)),
                )
        except sqlite3.Error as error:
            raise PersistenceError(f"backtest persistence failed: {error}") from error

    def get_result_json(self, backtest_run_id: str) -> str:
        row = self._connection.execute(
            "SELECT result_json FROM backtest_runs WHERE backtest_run_id = ?",
            (backtest_run_id,),
        ).fetchone()
        if row is None:
            raise PersistenceError("unknown backtest run")
        return str(row[0])
