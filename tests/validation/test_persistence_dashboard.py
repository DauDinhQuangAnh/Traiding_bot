import json
import sqlite3
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
    path = tmp_path / "validation.db"
    repository = SQLiteValidationRepository(path)
    try:
        first = repository.append_result(result)
        persisted = replace(
            result,
            protocol=replace(result.protocol, test_evaluation_count=1),
            test_consumption_index=1,
        )
        retry = repository.append_result(persisted)

        assert first == retry
        assert first.consumption_index == 1
        assert repository.get_result_json(result.validation_run_id) == canonical_json(persisted)
        assert repository.list_run_ids() == (result.validation_run_id,)
        assert validation_json(result) == canonical_json(result)
        connection = sqlite3.connect(path)
        stored_protocol = json.loads(
            connection.execute(
                "SELECT protocol_json FROM validation_protocols WHERE protocol_id = ?",
                (result.protocol.protocol_id,),
            ).fetchone()[0]
        )
        connection.close()
        assert stored_protocol["validation_policy"] == json.loads(
            canonical_json(result.protocol.validation_policy)
        )
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


def test_validation_sqlite_rejects_conflicting_protocol_identity(tmp_path):
    result = validation_run("protocol-first")
    path = tmp_path / "validation.db"
    repository = SQLiteValidationRepository(path)
    try:
        connection = sqlite3.connect(path)
        connection.execute(
            "INSERT INTO validation_protocols VALUES (?, ?)",
            (result.protocol.protocol_id, '{"conflicting":"policy bytes"}'),
        )
        connection.commit()
        connection.close()
        with pytest.raises(PersistenceError, match="protocol ID conflicts"):
            repository.append_result(result)
    finally:
        repository.close()


def test_validation_sqlite_owns_monotonic_test_consumption_sequence(tmp_path):
    executions = tuple(validation_run(f"fixture-execution-{index}") for index in range(1, 4))
    path = tmp_path / "validation.db"
    repository = SQLiteValidationRepository(path)
    second_writer = SQLiteValidationRepository(path)
    try:
        records = (
            repository.append_result(executions[0]),
            second_writer.append_result(executions[1]),
            repository.append_result(executions[2]),
        )
        retry = repository.append_result(executions[0])

        assert tuple(record.consumption_index for record in records) == (1, 2, 3)
        assert retry == records[0]
        assert len(repository.list_run_ids()) == 3
        assert len({result.validation_run_id for result in executions}) == 3
        assert len({result.protocol.protocol_id for result in executions}) == 1
        assert repository.list_test_consumptions(executions[0].protocol.protocol_id) == records
        assert tuple(
            json.loads(repository.get_result_json(result.validation_run_id))[
                "test_consumption_index"
            ]
            for result in executions
        ) == (1, 2, 3)
    finally:
        second_writer.close()
        repository.close()


def test_validation_sqlite_rejects_legacy_runs_without_consumption_ledger(tmp_path):
    path = tmp_path / "legacy-validation.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE validation_runs (validation_run_id TEXT PRIMARY KEY, "
        "protocol_id TEXT NOT NULL, result_json TEXT NOT NULL)"
    )
    connection.execute("INSERT INTO validation_runs VALUES ('run', 'protocol', '{}')")
    connection.commit()
    connection.close()

    with pytest.raises(PersistenceError, match="existing evidence lacks"):
        SQLiteValidationRepository(path)


def test_validation_sqlite_rejects_legacy_global_partition_identity(tmp_path):
    path = tmp_path / "legacy-partition-identity.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE partition_results (validation_run_id TEXT NOT NULL, "
        "partition_result_id TEXT NOT NULL UNIQUE, result_json TEXT NOT NULL, "
        "PRIMARY KEY(validation_run_id, partition_result_id))"
    )
    connection.commit()
    connection.close()

    with pytest.raises(PersistenceError, match="existing evidence lacks"):
        SQLiteValidationRepository(path)


def test_validation_sqlite_reports_initialization_and_closed_connection_errors(tmp_path):
    with pytest.raises(PersistenceError, match="cannot initialize"):
        SQLiteValidationRepository(tmp_path)

    repository = SQLiteValidationRepository(tmp_path / "validation.db")
    repository.close()
    with pytest.raises(PersistenceError, match="append failed"):
        repository.append_result(validation_run())


def test_validation_sqlite_rejects_invalid_repository_pagination(tmp_path):
    repository = SQLiteValidationRepository(tmp_path / "validation.db")
    try:
        with pytest.raises(PersistenceError, match="pagination"):
            repository.list_run_ids(limit=0)
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
