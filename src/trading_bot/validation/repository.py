"""Persistence port for immutable validation evidence."""

from typing import Protocol

from trading_bot.validation.models import TestConsumptionRecord, ValidationRun


class ValidationRepository(Protocol):
    def append_result(self, result: ValidationRun) -> TestConsumptionRecord: ...

    def get_result_json(self, validation_run_id: str) -> str: ...

    def list_run_ids(self, *, offset: int = 0, limit: int = 100) -> tuple[str, ...]: ...

    def list_test_consumptions(self, protocol_id: str) -> tuple[TestConsumptionRecord, ...]: ...
