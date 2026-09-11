from dataclasses import replace

import pytest

from trading_bot.dashboard.api import ReadOnlyValidationApi
from trading_bot.dashboard.services import ValidationDashboardService
from trading_bot.domain.errors import PersistenceError
from trading_bot.domain.primitives import canonical_json
from trading_bot.infrastructure.sqlite_validation import SQLiteValidationRepository
from trading_bot.validation.models import RobustnessStatus
from trading_bot.validation.reports import validation_json

from .helpers import validation_run


def test_validation_sqlite_is_idempotent_and_canonical(tmp_path):
    result = validation_run()
    repository = SQLiteValidationRepository(tmp_path / "validation.db")
    try:
        repository.append_result(result)
        repository.append_result(result)

        assert repository.get_result_json(result.validation_run_id) == canonical_json(result)
        assert repository.list_run_ids() == (result.validation_run_id,)
        assert validation_json(result) == canonical_json(result)
    finally:
        repository.close()


def test_validation_sqlite_rejects_conflicting_same_id(tmp_path):
    result = validation_run()
    conflict = replace(result, robustness_status=RobustnessStatus.MIXED)
    repository = SQLiteValidationRepository(tmp_path / "validation.db")
    try:
        repository.append_result(result)
        with pytest.raises(PersistenceError, match="conflicts"):
            repository.append_result(conflict)
    finally:
        repository.close()


def test_dashboard_lists_and_retrieves_known_run_without_mutation(tmp_path):
    result = validation_run()
    repository = SQLiteValidationRepository(tmp_path / "validation.db")
    try:
        repository.append_result(result)
        before = repository.get_result_json(result.validation_run_id)
        api = ReadOnlyValidationApi(ValidationDashboardService(repository))

        listed = api.handle("GET", "/validation-runs")
        detail = api.handle("GET", f"/validation-runs/{result.validation_run_id}")
        summary = api.handle("GET", f"/validation-runs/{result.validation_run_id}/summary")

        assert listed.status == detail.status == summary.status == 200
        assert listed.body["items"] == (result.validation_run_id,)
        assert summary.body == {
            "implementation_status": "PASS",
            "robustness_status": "NOT_EVALUATED",
        }
        assert repository.get_result_json(result.validation_run_id) == before
    finally:
        repository.close()


def test_dashboard_unknown_run_is_404_and_write_methods_are_405(tmp_path):
    repository = SQLiteValidationRepository(tmp_path / "validation.db")
    try:
        api = ReadOnlyValidationApi(ValidationDashboardService(repository))

        assert api.handle("GET", "/validation-runs/unknown").status == 404
        denied = api.handle("POST", "/trade")
        assert denied.status == 405
        assert denied.body == {"error": "read-only API"}
    finally:
        repository.close()


def test_dashboard_validates_pagination_and_supports_head(tmp_path):
    repository = SQLiteValidationRepository(tmp_path / "validation.db")
    try:
        api = ReadOnlyValidationApi(ValidationDashboardService(repository))

        assert api.handle("GET", "/validation-runs", limit=0).status == 400
        response = api.handle("HEAD", "/health")
        assert response.status == 200 and response.body == {}
    finally:
        repository.close()


@pytest.mark.parametrize("section", ("walk-forward", "sensitivity", "stress", "equity", "trades"))
def test_dashboard_sections_are_read_only_serialized_views(tmp_path, section):
    result = validation_run()
    repository = SQLiteValidationRepository(tmp_path / "validation.db")
    try:
        repository.append_result(result)
        api = ReadOnlyValidationApi(ValidationDashboardService(repository))

        response = api.handle("GET", f"/validation-runs/{result.validation_run_id}/{section}")

        assert response.status == 200
    finally:
        repository.close()
