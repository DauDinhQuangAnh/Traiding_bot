from __future__ import annotations

from collections.abc import Mapping
from copy import copy
from decimal import Decimal

import pytest

from tests.ai.helpers import (
    analysis_request,
    benchmark_cases,
    benchmark_protocol,
    provider_spec,
    response_json,
)
from trading_bot.ai.benchmark import assemble_benchmark_run, execute_benchmark
from trading_bot.ai.identity import create_benchmark_case
from trading_bot.ai.models import (
    AIAnalysisRequest,
    AIAnalysisResponse,
    AIBenchmarkRunStatus,
    AIProvider,
    AIProviderInvocation,
    AIResponseStatus,
)
from trading_bot.ai.parser import create_response, parse_response
from trading_bot.domain.enums import MarketRegime, TradeDecision
from trading_bot.domain.errors import DomainValidationError


class MappingAnalyst:
    def __init__(self, values: Mapping[str, tuple[TradeDecision, MarketRegime]]) -> None:
        self.values = values
        self.calls = 0

    def analyze(
        self, request: AIAnalysisRequest, invocation: AIProviderInvocation
    ) -> AIAnalysisResponse:
        self.calls += 1
        decision, regime = self.values[request.request_id]
        return parse_response(
            raw_text=response_json(decision, regime),
            request=request,
            invocation=invocation,
            attempts=1,
            input_tokens=10,
            output_tokens=5,
        )


class FailureAnalyst:
    def analyze(
        self, request: AIAnalysisRequest, invocation: AIProviderInvocation
    ) -> AIAnalysisResponse:
        return create_response(
            request=request,
            invocation=invocation,
            status=AIResponseStatus.TIMEOUT,
            attempts=3,
            error_code="TIMEOUT",
        )


def build_run():
    cases = benchmark_cases()
    protocol = benchmark_protocol(cases)
    reference = {
        case.request.request_id: (
            case.request.evidence.reference_decision,
            case.request.evidence.reference_regime,
        )
        for case in cases
    }
    no_trade = {key: (TradeDecision.NO_TRADE, MarketRegime.SIDEWAY) for key in reference}
    openai = MappingAnalyst(reference)
    anthropic = MappingAnalyst(no_trade)
    run = execute_benchmark(
        protocol=protocol,
        cases=cases,
        analysts={
            (AIProvider.OPENAI, "openai-test-model"): openai,
            (AIProvider.ANTHROPIC, "anthropic-test-model"): anthropic,
            (AIProvider.GEMINI, "gemini-test-model"): FailureAnalyst(),
        },
    )
    return run, openai, anthropic


def test_partial_provider_failures_remain_visible_and_do_not_erase_successes() -> None:
    run, openai, anthropic = build_run()
    assert run.status is AIBenchmarkRunStatus.COMPLETED_WITH_PROVIDER_FAILURES
    assert run.metrics.case_count == 3
    assert run.metrics.expected_response_count == 9
    assert run.metrics.success_count == 6
    assert run.metrics.failure_count == 3
    assert openai.calls == anthropic.calls == 3


def test_provider_metrics_have_exact_denominators_reference_breakdown_and_tokens() -> None:
    run, _, _ = build_run()
    openai, anthropic, gemini = run.metrics.provider_metrics
    assert openai.decision_agreement_rate == 1
    assert openai.regime_agreement_rate == 1
    assert openai.input_tokens == 30
    assert openai.output_tokens == 15
    assert tuple(item.agreement_count for item in openai.reference_decision_metrics) == (1, 1, 1)
    assert anthropic.decision_agreement_count == 1
    assert anthropic.no_trade_rate == 1
    assert anthropic.input_tokens == 30
    assert gemini.valid_response_rate == 0
    assert gemini.timeout_count == 3
    assert gemini.average_confidence is None
    assert gemini.long_rate is None
    assert gemini.input_tokens is None


def test_pairwise_metrics_use_only_mutually_successful_cases() -> None:
    run, _, _ = build_run()
    openai_anthropic, openai_gemini, anthropic_gemini = run.metrics.pairwise_metrics
    assert openai_anthropic.comparable_count == 3
    assert openai_anthropic.decision_agreement_count == 1
    assert openai_anthropic.decision_divergence_count == 2
    assert openai_anthropic.decision_agreement_rate == Decimal(1) / Decimal(3)
    assert openai_gemini.comparable_count == 0
    assert openai_gemini.decision_agreement_rate is None
    assert anthropic_gemini.regime_agreement_rate is None


def test_replay_is_pure_and_canonical() -> None:
    run, openai, anthropic = build_run()
    before = (openai.calls, anthropic.calls)
    replay = assemble_benchmark_run(
        protocol=run.protocol,
        cases=run.cases,
        invocations=run.invocations,
        responses=run.responses,
    )
    assert replay == run
    assert before == (openai.calls, anthropic.calls)


def test_all_success_run_is_completed() -> None:
    cases = benchmark_cases()
    protocol = benchmark_protocol(cases)
    values = {
        case.request.request_id: (
            case.request.evidence.reference_decision,
            case.request.evidence.reference_regime,
        )
        for case in cases
    }
    analysts = {
        (spec.provider, spec.model): MappingAnalyst(values) for spec in protocol.provider_specs
    }
    run = execute_benchmark(protocol=protocol, cases=cases, analysts=analysts)
    assert run.status is AIBenchmarkRunStatus.COMPLETED
    assert run.metrics.failure_count == 0


def test_missing_analyst_and_changed_case_semantics_fail_before_execution() -> None:
    cases = benchmark_cases()
    protocol = benchmark_protocol(cases)
    with pytest.raises(DomainValidationError, match="no analyst"):
        execute_benchmark(protocol=protocol, cases=cases, analysts={})
    with pytest.raises(DomainValidationError, match="do not match"):
        execute_benchmark(protocol=protocol, cases=tuple(reversed(cases)), analysts={})


def test_disabled_providers_are_skipped_and_all_disabled_fails_closed() -> None:
    cases = benchmark_cases()
    protocol = benchmark_protocol(
        cases,
        (provider_spec(AIProvider.OPENAI, enabled=False),),
    )
    with pytest.raises(DomainValidationError, match="at least one enabled provider"):
        execute_benchmark(protocol=protocol, cases=cases, analysts={})


def test_replay_rejects_count_order_and_duplicate_invocation_ids() -> None:
    run, _, _ = build_run()
    with pytest.raises(DomainValidationError, match="count mismatch"):
        assemble_benchmark_run(
            protocol=run.protocol,
            cases=run.cases,
            invocations=run.invocations,
            responses=run.responses[:-1],
        )
    with pytest.raises(DomainValidationError, match="do not match cases/providers"):
        assemble_benchmark_run(
            protocol=run.protocol,
            cases=run.cases,
            invocations=tuple(reversed(run.invocations)),
            responses=tuple(reversed(run.responses)),
        )

    duplicate = copy(run.invocations[1])
    object.__setattr__(duplicate, "invocation_id", run.invocations[0].invocation_id)
    invocations = (run.invocations[0], duplicate, *run.invocations[2:])
    with pytest.raises(DomainValidationError, match="IDs must be unique"):
        assemble_benchmark_run(
            protocol=run.protocol,
            cases=run.cases,
            invocations=invocations,
            responses=run.responses,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("request_id", "different-request"),
        ("model", "different-model"),
        ("attempts", 999),
    ),
)
def test_replay_rejects_response_that_changes_invocation_semantics(
    field: str, value: object
) -> None:
    run, _, _ = build_run()
    changed = copy(run.responses[0])
    object.__setattr__(changed, field, value)
    responses = (changed, *run.responses[1:])
    with pytest.raises(DomainValidationError, match="changed invocation semantics"):
        assemble_benchmark_run(
            protocol=run.protocol,
            cases=run.cases,
            invocations=run.invocations,
            responses=responses,
        )


def test_case_that_changes_frozen_protocol_semantics_is_rejected() -> None:
    changed_case = create_benchmark_case(
        analysis_request(prompt_version="ai-advisory-prompt-v999"),
        "changed-prompt",
    )
    cases = (changed_case,)
    protocol = benchmark_protocol(cases)
    with pytest.raises(DomainValidationError, match="changed frozen protocol semantics"):
        execute_benchmark(protocol=protocol, cases=cases, analysts={})
