"""Deterministic execution, replay, and descriptive AI benchmark metrics."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from itertools import combinations
from typing import Literal

from trading_bot.ai.identity import create_invocation
from trading_bot.ai.models import (
    AIAnalysisResponse,
    AIBenchmarkCase,
    AIBenchmarkMetrics,
    AIBenchmarkProtocol,
    AIBenchmarkRun,
    AIBenchmarkRunStatus,
    AIPairwiseMetrics,
    AIProvider,
    AIProviderInvocation,
    AIProviderMetrics,
    AIReferenceDecisionMetrics,
    AIResponseStatus,
    confidence_average,
    ratio,
)
from trading_bot.ai.ports import AIAnalystPort
from trading_bot.domain.enums import MarketRegime, TradeDecision
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.identifiers import deterministic_id

ProviderKey = tuple[AIProvider, str]


def execute_benchmark(
    *,
    protocol: AIBenchmarkProtocol,
    cases: tuple[AIBenchmarkCase, ...],
    analysts: Mapping[ProviderKey, AIAnalystPort],
    invocation_sequence: int = 0,
) -> AIBenchmarkRun:
    _validate_cases(protocol, cases)
    invocations: list[AIProviderInvocation] = []
    responses: list[AIAnalysisResponse] = []
    for case in cases:
        for spec in protocol.provider_specs:
            if not spec.enabled:
                continue
            key = (spec.provider, spec.model)
            analyst = analysts.get(key)
            if analyst is None:
                raise DomainValidationError("enabled AI provider has no analyst port")
            invocation = create_invocation(case.request.request_id, spec, invocation_sequence)
            invocations.append(invocation)
            responses.append(analyst.analyze(case.request, invocation))
    if not invocations:
        raise DomainValidationError("benchmark requires at least one enabled provider")
    return assemble_benchmark_run(
        protocol=protocol,
        cases=cases,
        invocations=tuple(invocations),
        responses=tuple(responses),
    )


def assemble_benchmark_run(
    *,
    protocol: AIBenchmarkProtocol,
    cases: tuple[AIBenchmarkCase, ...],
    invocations: tuple[AIProviderInvocation, ...],
    responses: tuple[AIAnalysisResponse, ...],
) -> AIBenchmarkRun:
    """Pure replay path: recompute all metrics without provider/network access."""
    _validate_cases(protocol, cases)
    if len(invocations) != len(responses):
        raise DomainValidationError("replay invocation/response count mismatch")
    _validate_invocation_responses(protocol, cases, invocations, responses)
    request_references = {
        case.request.request_id: (
            case.request.evidence.reference_decision,
            case.request.evidence.reference_regime,
        )
        for case in cases
    }
    metrics = calculate_metrics(protocol, request_references, responses)
    status = (
        AIBenchmarkRunStatus.COMPLETED
        if all(item.status is AIResponseStatus.SUCCESS for item in responses)
        else AIBenchmarkRunStatus.COMPLETED_WITH_PROVIDER_FAILURES
    )
    parts = (protocol, cases, invocations, responses, metrics, status)
    return AIBenchmarkRun(deterministic_id("ai-benchmark-run-v1", *parts), *parts)


def calculate_metrics(
    protocol: AIBenchmarkProtocol,
    references: Mapping[str, tuple[TradeDecision, MarketRegime]],
    responses: tuple[AIAnalysisResponse, ...],
) -> AIBenchmarkMetrics:
    active_specs = tuple(item for item in protocol.provider_specs if item.enabled)
    provider_metrics = tuple(
        _provider_metrics(
            spec.provider,
            spec.model,
            len(protocol.case_ids),
            references,
            tuple(
                response
                for response in responses
                if response.provider is spec.provider and response.model == spec.model
            ),
        )
        for spec in active_specs
    )
    pairwise = tuple(
        _pairwise_metrics(left.provider, left.model, right.provider, right.model, responses)
        for left, right in combinations(active_specs, 2)
    )
    expected = len(protocol.case_ids) * len(active_specs)
    success = sum(item.success_count for item in provider_metrics)
    values = (
        protocol.metrics_version,
        protocol.protocol_id,
        len(protocol.case_ids),
        expected,
        success,
        expected - success,
        provider_metrics,
        pairwise,
    )
    return AIBenchmarkMetrics(
        deterministic_id("ai-benchmark-metrics-v1", *values),
        *values,
    )


def _provider_metrics(
    provider: AIProvider,
    model: str,
    case_count: int,
    references: Mapping[str, tuple[TradeDecision, MarketRegime]],
    responses: tuple[AIAnalysisResponse, ...],
) -> AIProviderMetrics:
    if len(responses) != case_count:
        raise DomainValidationError("provider response count does not cover benchmark cases")
    success = tuple(item for item in responses if item.status is AIResponseStatus.SUCCESS)
    failures = len(responses) - len(success)
    decision_agreement = sum(item.decision == references[item.request_id][0] for item in success)
    regime_agreement = sum(item.regime == references[item.request_id][1] for item in success)
    decisions = {
        decision: sum(item.decision is decision for item in success) for decision in TradeDecision
    }
    reference_metrics = tuple(
        _reference_metrics(decision, references, success) for decision in TradeDecision
    )
    confidences = tuple(item.confidence for item in success if item.confidence is not None)
    input_tokens = _optional_token_sum(success, "input_tokens")
    output_tokens = _optional_token_sum(success, "output_tokens")
    status_count = {
        status: sum(item.status is status for item in responses) for status in AIResponseStatus
    }
    return AIProviderMetrics(
        provider=provider,
        model=model,
        case_count=case_count,
        success_count=len(success),
        failure_count=failures,
        valid_response_rate=ratio(len(success), case_count),
        decision_agreement_count=decision_agreement,
        decision_agreement_rate=ratio(decision_agreement, len(success)),
        regime_agreement_count=regime_agreement,
        regime_agreement_rate=ratio(regime_agreement, len(success)),
        long_count=decisions[TradeDecision.LONG],
        short_count=decisions[TradeDecision.SHORT],
        no_trade_count=decisions[TradeDecision.NO_TRADE],
        long_rate=ratio(decisions[TradeDecision.LONG], len(success)),
        short_rate=ratio(decisions[TradeDecision.SHORT], len(success)),
        no_trade_rate=ratio(decisions[TradeDecision.NO_TRADE], len(success)),
        reference_decision_metrics=reference_metrics,
        timeout_count=status_count[AIResponseStatus.TIMEOUT],
        rate_limit_count=status_count[AIResponseStatus.RATE_LIMIT],
        auth_error_count=status_count[AIResponseStatus.AUTH_ERROR],
        provider_error_count=status_count[AIResponseStatus.PROVIDER_ERROR],
        invalid_response_count=status_count[AIResponseStatus.INVALID_RESPONSE],
        schema_failure_count=status_count[AIResponseStatus.SCHEMA_VALIDATION_FAILED],
        confidence_count=len(confidences),
        average_confidence=confidence_average(confidences),
        minimum_confidence=min(confidences) if confidences else None,
        maximum_confidence=max(confidences) if confidences else None,
        confidence_buckets=_confidence_buckets(confidences),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _reference_metrics(
    decision: TradeDecision,
    references: Mapping[str, tuple[TradeDecision, MarketRegime]],
    successes: tuple[AIAnalysisResponse, ...],
) -> AIReferenceDecisionMetrics:
    comparable = tuple(item for item in successes if references[item.request_id][0] is decision)
    agreement = sum(item.decision is decision for item in comparable)
    return AIReferenceDecisionMetrics(
        decision, len(comparable), agreement, ratio(agreement, len(comparable))
    )


def _pairwise_metrics(
    left_provider: AIProvider,
    left_model: str,
    right_provider: AIProvider,
    right_model: str,
    responses: tuple[AIAnalysisResponse, ...],
) -> AIPairwiseMetrics:
    left = {
        item.request_id: item
        for item in responses
        if item.provider is left_provider
        and item.model == left_model
        and item.status is AIResponseStatus.SUCCESS
    }
    right = {
        item.request_id: item
        for item in responses
        if item.provider is right_provider
        and item.model == right_model
        and item.status is AIResponseStatus.SUCCESS
    }
    common = tuple(sorted(set(left) & set(right)))
    decision_agreement = sum(left[key].decision == right[key].decision for key in common)
    regime_agreement = sum(left[key].regime == right[key].regime for key in common)
    return AIPairwiseMetrics(
        left_provider,
        left_model,
        right_provider,
        right_model,
        len(common),
        decision_agreement,
        len(common) - decision_agreement,
        ratio(decision_agreement, len(common)),
        regime_agreement,
        len(common) - regime_agreement,
        ratio(regime_agreement, len(common)),
    )


def _confidence_buckets(values: tuple[Decimal, ...]) -> tuple[int, int, int, int, int]:
    buckets = [0, 0, 0, 0, 0]
    for value in values:
        index = min(int(value * Decimal("5")), 4)
        buckets[index] += 1
    return tuple(buckets)  # type: ignore[return-value]


def _optional_token_sum(
    responses: tuple[AIAnalysisResponse, ...],
    field: Literal["input_tokens", "output_tokens"],
) -> int | None:
    values = tuple(
        item.input_tokens if field == "input_tokens" else item.output_tokens for item in responses
    )
    if not values or any(value is None for value in values):
        return None
    return sum(value for value in values if value is not None)


def _validate_cases(protocol: AIBenchmarkProtocol, cases: tuple[AIBenchmarkCase, ...]) -> None:
    if tuple(item.case_id for item in cases) != protocol.case_ids:
        raise DomainValidationError("benchmark cases do not match protocol")
    for case in cases:
        request = case.request
        identities = (
            request.code_version == protocol.code_version,
            request.strategy_version == protocol.strategy_version,
            request.config_version == protocol.config_version,
            request.historical_versions == protocol.historical_versions,
            request.instrument_version == protocol.instrument_version,
            request.prompt_version == protocol.prompt_version,
            request.projection_version == protocol.projection_version,
            request.schema_version == protocol.schema_version,
        )
        if not all(identities):
            raise DomainValidationError("benchmark case changed frozen protocol semantics")


def _validate_invocation_responses(
    protocol: AIBenchmarkProtocol,
    cases: tuple[AIBenchmarkCase, ...],
    invocations: tuple[AIProviderInvocation, ...],
    responses: tuple[AIAnalysisResponse, ...],
) -> None:
    enabled_specs = tuple(item for item in protocol.provider_specs if item.enabled)
    expected = tuple((case.request.request_id, spec) for case in cases for spec in enabled_specs)
    actual = tuple((item.request_id, item.provider_spec) for item in invocations)
    if actual != expected:
        raise DomainValidationError("benchmark invocations do not match cases/providers")
    if len({item.invocation_id for item in invocations}) != len(invocations):
        raise DomainValidationError("benchmark invocation IDs must be unique")
    for invocation, response in zip(invocations, responses, strict=True):
        if (
            response.invocation_id != invocation.invocation_id
            or response.request_id != invocation.request_id
            or response.provider is not invocation.provider_spec.provider
            or response.model != invocation.provider_spec.model
            or response.attempts > invocation.provider_spec.max_attempts
        ):
            raise DomainValidationError("benchmark response changed invocation semantics")
