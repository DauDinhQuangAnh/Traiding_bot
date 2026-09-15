"""Factories for self-validating PHASE 7 identities."""

from __future__ import annotations

from trading_bot.ai.models import (
    AIAnalysisRequest,
    AIBenchmarkCase,
    AIBenchmarkProtocol,
    AIBenchmarkReference,
    AIMarketEvidence,
    AIProjectionLimits,
    AIProviderInvocation,
    AIProviderSpec,
)
from trading_bot.ai.versions import (
    PARSER_VERSION,
    PROJECTION_VERSION,
    PROMPT_VERSION,
    SCHEMA_VERSION,
)
from trading_bot.config.models import CalculationConfig
from trading_bot.domain.errors import DomainValidationError
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
    if (
        prompt_version != PROMPT_VERSION
        or projection_version != PROJECTION_VERSION
        or schema_version != SCHEMA_VERSION
    ):
        raise DomainValidationError("AI request factory requires registered contract versions")
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


def create_benchmark_case(
    request: AIAnalysisRequest, reference: AIBenchmarkReference, label: str
) -> AIBenchmarkCase:
    parts = (request, reference, label)
    return AIBenchmarkCase(deterministic_id("ai-benchmark-case-v1", *parts), *parts)


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
    calculation: CalculationConfig,
) -> AIBenchmarkProtocol:
    if (
        prompt_version != PROMPT_VERSION
        or projection_version != PROJECTION_VERSION
        or schema_version != SCHEMA_VERSION
        or parser_version != PARSER_VERSION
    ):
        raise DomainValidationError("benchmark factory requires registered contract versions")
    case_ids = tuple(item.case_id for item in cases)
    request_ids = tuple(item.request.request_id for item in cases)
    if len(set(request_ids)) != len(request_ids):
        raise DomainValidationError("benchmark cases require unique model-visible request IDs")
    case_set_id = deterministic_id("ai-benchmark-case-set-v1", case_ids)
    parts = (
        protocol_version,
        case_set_id,
        request_ids,
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
        calculation,
    )
    return AIBenchmarkProtocol(
        deterministic_id("ai-benchmark-protocol-v1", *parts),
        protocol_version,
        case_set_id,
        case_ids,
        request_ids,
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
        calculation,
    )
