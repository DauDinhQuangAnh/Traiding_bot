"""Read-only query service over persisted AI benchmark evidence."""

from __future__ import annotations

import json

from trading_bot.ai.repository import AIBenchmarkRepository
from trading_bot.domain.errors import DomainValidationError, PersistenceError


class AIBenchmarkDashboardService:
    def __init__(self, repository: AIBenchmarkRepository) -> None:
        self._repository = repository

    def health(self) -> dict[str, str]:
        return {"status": "ok", "mode": "ai-benchmark-read-only"}

    def list_runs(self, *, offset: int = 0, limit: int = 100) -> dict[str, object]:
        if offset < 0 or not 1 <= limit <= 100:
            raise DomainValidationError("invalid AI dashboard pagination")
        return {
            "items": self._repository.list_run_ids(offset=offset, limit=limit),
            "offset": offset,
            "limit": limit,
        }

    def get_run(self, run_id: str) -> dict[str, object]:
        value = json.loads(self._repository.get_run_json(run_id))
        if not isinstance(value, dict):
            raise PersistenceError("stored AI benchmark result is not an object")
        return value

    def get_section(self, run_id: str, section: str) -> object:
        run = self.get_run(run_id)
        aliases = {"metrics": "metrics", "cases": "cases", "responses": "responses"}
        key = aliases.get(section)
        if key is None:
            raise PersistenceError("unknown AI dashboard section")
        return run[key]
