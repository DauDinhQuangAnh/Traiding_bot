"""Persistence port for immutable deterministic backtest artifacts."""

from __future__ import annotations

from typing import Protocol

from trading_bot.backtest.models import BacktestFailure, BacktestResult
from trading_bot.domain.enums import BacktestFailureKind, BacktestStatus
from trading_bot.domain.errors import PersistenceError


class BacktestRepository(Protocol):
    def append_result(self, result: BacktestResult) -> None: ...

    def get_result_json(self, backtest_run_id: str) -> str: ...


def attempt_persist_result(
    repository: BacktestRepository, result: BacktestResult
) -> BacktestFailure | None:
    try:
        repository.append_result(result)
    except PersistenceError as error:
        return BacktestFailure(
            BacktestStatus.FAILED,
            BacktestFailureKind.PERSISTENCE,
            str(error),
            result.run.spec.backtest_run_id,
        )
    return None
