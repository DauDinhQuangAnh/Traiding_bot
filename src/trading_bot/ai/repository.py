"""Persistence port for append-only AI benchmark evidence."""

from typing import Protocol

from trading_bot.ai.models import AIBenchmarkRun


class AIBenchmarkRepository(Protocol):
    def append_run(self, run: AIBenchmarkRun) -> None: ...

    def get_run_json(self, run_id: str) -> str: ...

    def list_run_ids(self, *, offset: int = 0, limit: int = 100) -> tuple[str, ...]: ...
