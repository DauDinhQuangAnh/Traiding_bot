from __future__ import annotations

from copy import copy
from pathlib import Path

import pytest
import yaml

from tests.ai.test_benchmark import build_run
from trading_bot.ai.configuration import projection_limits, provider_specs
from trading_bot.config.loader import app_config_from_mapping, config_version, load_config
from trading_bot.config.secrets import redact, without_secrets
from trading_bot.dashboard.ai_api import ReadOnlyAIBenchmarkApi
from trading_bot.dashboard.ai_services import AIBenchmarkDashboardService
from trading_bot.domain.errors import ConfigurationError, PersistenceError
from trading_bot.domain.primitives import canonical_json
from trading_bot.infrastructure.sqlite_ai_benchmark import SQLiteAIBenchmarkRepository


def test_ai_config_is_typed_disabled_and_contains_no_secret_values() -> None:
    config = load_config(Path("config/base.example.yaml"))
    assert config.ai.enabled is False
    assert all(item.enabled is False for item in config.ai.providers.values())
    assert all(item.enabled is False for item in provider_specs(config.ai))
    assert projection_limits(config.ai).max_observations == 100
    serialized = canonical_json(config.ai)
    assert "API_KEY" not in serialized
    assert "secret" not in serialized.lower()


def test_ai_config_rejects_unknown_provider_and_provider_enablement_under_global_off() -> None:
    raw = yaml.safe_load(Path("config/base.example.yaml").read_text(encoding="utf-8"))
    raw["ai"]["providers"]["UNKNOWN"] = raw["ai"]["providers"]["OPENAI"]
    with pytest.raises(ConfigurationError, match="unknown"):
        app_config_from_mapping(raw)
    raw = yaml.safe_load(Path("config/base.example.yaml").read_text(encoding="utf-8"))
    raw["ai"]["providers"]["OPENAI"]["enabled"] = True
    with pytest.raises(ConfigurationError, match="global AI"):
        app_config_from_mapping(raw)


def test_generic_secret_policy_redacts_all_provider_key_names() -> None:
    secrets = {
        "OPENAI_API_KEY": "openai-secret-value",
        "ANTHROPIC_API_KEY": "anthropic-secret-value",
        "GEMINI_API_KEY": "gemini-secret-value",
        "safe": "visible",
    }
    redacted = redact(secrets)
    safe = without_secrets(secrets)
    assert all("secret-value" not in str(value) for value in redacted.values())
    assert safe == {"safe": "visible"}
    assert config_version(secrets) == config_version({"safe": "visible"})


def test_sqlite_append_is_idempotent_and_rebuild_is_byte_identical(tmp_path: Path) -> None:
    run, _, _ = build_run()
    first = SQLiteAIBenchmarkRepository(tmp_path / "first.db")
    second = SQLiteAIBenchmarkRepository(tmp_path / "second.db")
    try:
        first.append_run(run)
        first.append_run(run)
        second.append_run(run)
        assert first.get_run_json(run.run_id) == second.get_run_json(run.run_id)
        assert first.list_run_ids() == (run.run_id,)
        with pytest.raises(PersistenceError, match="unknown"):
            first.get_run_json("missing")
        with pytest.raises(PersistenceError, match="pagination"):
            first.list_run_ids(limit=0)
    finally:
        first.close()
        second.close()


def test_sqlite_conflicting_identity_fails_without_overwrite(tmp_path: Path) -> None:
    run, _, _ = build_run()
    repository = SQLiteAIBenchmarkRepository(tmp_path / "evidence.db")
    try:
        repository.append_run(run)
        original = repository.get_run_json(run.run_id)
        tampered = copy(run)
        object.__setattr__(tampered, "responses", tuple(reversed(run.responses)))
        with pytest.raises(PersistenceError, match="conflicts"):
            repository.append_run(tampered)
        assert repository.get_run_json(run.run_id) == original
    finally:
        repository.close()


def test_ai_dashboard_is_read_only_and_exposes_persisted_sections(tmp_path: Path) -> None:
    run, _, _ = build_run()
    repository = SQLiteAIBenchmarkRepository(tmp_path / "dashboard.db")
    try:
        repository.append_run(run)
        api = ReadOnlyAIBenchmarkApi(AIBenchmarkDashboardService(repository))
        assert api.handle("GET", "/ai-health").status == 200
        assert api.handle("GET", "/ai-benchmark-runs").body["items"] == (run.run_id,)
        assert api.handle("GET", f"/ai-benchmark-runs/{run.run_id}").body["run_id"] == run.run_id
        assert api.handle("GET", f"/ai-benchmark-runs/{run.run_id}/metrics").status == 200
        assert api.handle("GET", f"/ai-benchmark-runs/{run.run_id}/cases").status == 200
        assert api.handle("HEAD", f"/ai-benchmark-runs/{run.run_id}/responses").body == {}
        assert api.handle("POST", "/ai-benchmark-runs").status == 405
        assert api.handle("DELETE", f"/ai-benchmark-runs/{run.run_id}").status == 405
        assert api.handle("GET", "/ai-benchmark-runs/missing").status == 404
        assert api.handle("GET", "/ai-benchmark-runs", limit=0).status == 400
        with pytest.raises(PersistenceError, match="unknown AI dashboard section"):
            AIBenchmarkDashboardService(repository).get_section(run.run_id, "unknown")
    finally:
        repository.close()


class NonObjectRepository:
    def append_run(self, run: object) -> None:
        del run

    def get_run_json(self, run_id: str) -> str:
        del run_id
        return "[]"

    def list_run_ids(self, *, offset: int = 0, limit: int = 100) -> tuple[str, ...]:
        del offset, limit
        return ()


def test_ai_dashboard_rejects_non_object_storage() -> None:
    service = AIBenchmarkDashboardService(NonObjectRepository())  # type: ignore[arg-type]
    with pytest.raises(PersistenceError, match="not an object"):
        service.get_run("bad")


def test_phase7_source_has_no_trading_reverse_dependency_or_network_sdk() -> None:
    ai_source = "\n".join(
        path.read_text(encoding="utf-8") for path in Path("src/trading_bot/ai").glob("*.py")
    )
    infrastructure_source = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in (
            "src/trading_bot/infrastructure/ai_provider.py",
            "src/trading_bot/infrastructure/ai_fakes.py",
            "src/trading_bot/infrastructure/sqlite_ai_benchmark.py",
        )
    )
    for forbidden in (
        "ApprovedTradePlan",
        "RiskDecision",
        "OrderRequest",
        "ExchangeExecutionPort",
        "submit_order",
        "cancel_order",
        "import requests",
        "httpx",
        "aiohttp",
        "openai import",
        "anthropic import",
        "google.generativeai",
    ):
        assert forbidden not in ai_source + infrastructure_source
