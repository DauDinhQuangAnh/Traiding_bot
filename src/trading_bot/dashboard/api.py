"""Small local GET-only HTTP contract without trading or mutation endpoints."""

from __future__ import annotations

from typing import ClassVar

from trading_bot.dashboard.schemas import ApiResponse
from trading_bot.dashboard.services import ValidationDashboardService
from trading_bot.domain.errors import DomainValidationError, PersistenceError


class ReadOnlyValidationApi:
    _SECTIONS: ClassVar = {
        "summary",
        "equity",
        "trades",
        "walk-forward",
        "sensitivity",
        "stress",
    }

    def __init__(self, service: ValidationDashboardService) -> None:
        self._service = service

    def handle(
        self,
        method: str,
        path: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> ApiResponse:
        if method not in {"GET", "HEAD"}:
            return ApiResponse(405, {"error": "read-only API"}, (("allow", "GET, HEAD"),))
        try:
            response = self._read(path, offset=offset, limit=limit)
        except DomainValidationError:
            return ApiResponse(400, {"error": "invalid query"})
        except PersistenceError:
            return ApiResponse(404, {"error": "not found"})
        return ApiResponse(response.status, {} if method == "HEAD" else response.body)

    def _read(self, path: str, *, offset: int, limit: int) -> ApiResponse:
        parts = tuple(part for part in path.strip("/").split("/") if part)
        if parts == ("health",):
            return ApiResponse(200, self._service.health())
        if parts == ("validation-runs",):
            return ApiResponse(200, self._service.list_runs(offset=offset, limit=limit))
        if len(parts) == 2 and parts[0] == "validation-runs":
            return ApiResponse(200, self._service.get_run(parts[1]))
        if len(parts) == 3 and parts[0] == "validation-runs" and parts[2] in self._SECTIONS:
            return ApiResponse(200, self._service.get_section(parts[1], parts[2]))
        raise PersistenceError("unknown dashboard route")
