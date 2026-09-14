"""Factories for self-validating PHASE 7 identities."""

from __future__ import annotations

from trading_bot.ai.models import (
    AIAnalysisRequest,
    AIBenchmarkCase,
    AIBenchmarkProtocol,
    AIMarketEvidence,
    AIProjectionLimits,
    AIProviderInvocation,
    AIProviderSpec,
)
from trading_bot.domain.identifiers import deterministic_id
from trading_bot.historical.models import HistoricalVersionSet


def create_analysis_request(
    *,
    evidence: AIMarketEvidence,
    code_version: str,
    strategy_version: str,
    config_version: str,
    historical_versions: HistoricalVersionSet,
    instrument_version: str,
    prompt_version: str,
    projection_version: str,
    schema_version: str,
    limits: AIProjectionLimits,
) -> AIAnalysisRequest:
    parts = (
        evidence,
        code_version,
        strategy_version,
        config_version,
        historical_versions,
        instrument_version,
        prompt_version,
        projection_version,
        schema_version,
        limits,
    )
    return AIAnalysisRequest(
        deterministic_id("ai-analysis-request-v1", *parts),
        evidence,
        code_version,
        strategy_version,
        config_version,
        historical_versions,
        instrument_version,
        prompt_version,
        projection_version,
        schema_version,
        limits,
    )


def create_invocation(
    request_id: str, provider_spec: AIProviderSpec, invocation_sequence: int = 0
) -> AIProviderInvocation:
    identifier = deterministic_id(
        "ai-provider-invocation-v1", request_id, provider_spec, invocation_sequence
    )
    return AIProviderInvocation(identifier, request_id, provider_spec, invocation_sequence)


def create_benchmark_case(request: AIAnalysisRequest, label: str) -> AIBenchmarkCase:
    return AIBenchmarkCase(deterministic_id("ai-benchmark-case-v1", request, label), request, label)


def create_benchmark_protocol(
    *,
    protocol_version: str,
    cases: tuple[AIBenchmarkCase, ...],
    provider_specs: tuple[AIProviderSpec, ...],
    code_version: str,
    strategy_version: str,
    config_version: str,
    historical_versions: HistoricalVersionSet,
    instrument_version: str,
    prompt_version: str,
    projection_version: str,
    schema_version: str,
    parser_version: str,
    metrics_version: str,
) -> AIBenchmarkProtocol:
    case_ids = tuple(item.case_id for item in cases)
    case_set_id = deterministic_id("ai-benchmark-case-set-v1", case_ids)
    parts = (
        protocol_version,
        case_set_id,
        provider_specs,
        code_version,
        strategy_version,
        config_version,
        historical_versions,
        instrument_version,
        prompt_version,
        projection_version,
        schema_version,
        parser_version,
        metrics_version,
    )
    return AIBenchmarkProtocol(
        deterministic_id("ai-benchmark-protocol-v1", *parts),
        protocol_version,
        case_set_id,
        case_ids,
        provider_specs,
        code_version,
        strategy_version,
        config_version,
        historical_versions,
        instrument_version,
        prompt_version,
        projection_version,
        schema_version,
        parser_version,
        metrics_version,
    )
