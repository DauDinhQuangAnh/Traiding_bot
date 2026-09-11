"""Read services over persisted canonical validation artifacts."""

from __future__ import annotations

import json

from trading_bot.domain.errors import DomainValidationError, PersistenceError
from trading_bot.validation.repository import ValidationRepository


class ValidationDashboardService:
    def __init__(self, repository: ValidationRepository) -> None:
        self._repository = repository

    def health(self) -> dict[str, str]:
        return {"status": "ok", "mode": "historical-read-only"}

    def list_runs(self, *, offset: int = 0, limit: int = 100) -> dict[str, object]:
        if offset < 0 or not 1 <= limit <= 100:
            raise DomainValidationError("invalid dashboard pagination")
        identifiers = self._repository.list_run_ids(offset=offset, limit=limit)
        return {"items": identifiers, "offset": offset, "limit": limit}

    def get_run(self, validation_run_id: str) -> dict[str, object]:
        value = json.loads(self._repository.get_result_json(validation_run_id))
        if not isinstance(value, dict):
            raise PersistenceError("stored validation result is not an object")
        return value

    def get_section(self, validation_run_id: str, section: str) -> object:
        run = self.get_run(validation_run_id)
        aliases = {
            "summary": ("implementation_status", "robustness_status"),
            "equity": (),
            "trades": (),
            "walk-forward": ("walk_forward",),
            "sensitivity": ("sensitivity",),
            "stress": ("stress",),
        }
        keys = aliases.get(section)
        if keys is None:
            raise PersistenceError("unknown dashboard section")
        if section == "summary":
            return {key: run[key] for key in keys}
        if section in {"equity", "trades"}:
            return {
                "available": False,
                "reason": "partition projections do not duplicate PHASE 5 row artifacts",
            }
        return run[keys[0]]
