from __future__ import annotations

from collections.abc import Mapping
from copy import copy
from decimal import ROUND_DOWN, ROUND_UP, Decimal, localcontext

import pytest

from tests.ai.helpers import (
    analysis_request,
    benchmark_cases,
    benchmark_protocol,
    benchmark_reference,
    changed_request,
    provider_spec,
    response_json,
)
from trading_bot.ai.benchmark import assemble_benchmark_run, calculate_metrics, execute_benchmark
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
from trading_bot.config.models import CalculationConfig
from trading_bot.domain.enums import DecimalRoundingMode, MarketRegime, TradeDecision
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.primitives import canonical_json


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


class ConfidenceAnalyst:
    def __init__(
        self,
        values: Mapping[str, tuple[TradeDecision, MarketRegime, str]],
    ) -> None:
        self.values = values

    def analyze(
        self, request: AIAnalysisRequest, invocation: AIProviderInvocation
    ) -> AIAnalysisResponse:
        decision, regime, confidence = self.values[request.request_id]
        return parse_response(
            raw_text=response_json(decision, regime, confidence),
            request=request,
            invocation=invocation,
            attempts=1,
        )


def build_run():
    cases = benchmark_cases()
    protocol = benchmark_protocol(cases)
    reference = {
        case.request.request_id: (
            case.reference.reference_decision,
            case.reference.reference_regime,
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
            case.reference.reference_decision,
            case.reference.reference_regime,
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
        changed_request(analysis_request(), config_version="config-v2"),
        benchmark_reference(),
        "changed-prompt",
    )
    cases = (changed_case,)
    protocol = benchmark_protocol(cases)
    with pytest.raises(DomainValidationError, match="changed frozen protocol semantics"):
        execute_benchmark(protocol=protocol, cases=cases, analysts={})


def test_benchmark_metrics_ignore_ambient_decimal_context() -> None:
    cases = benchmark_cases()
    protocol = benchmark_protocol(cases, (provider_spec(AIProvider.OPENAI),))
    confidence_values = ("0.1", "0.2", "0.8")
    outputs = {
        case.request.request_id: (
            TradeDecision.LONG,
            case.reference.reference_regime,
            confidence,
        )
        for case, confidence in zip(cases, confidence_values, strict=True)
    }

    def execute():
        return execute_benchmark(
            protocol=protocol,
            cases=cases,
            analysts={
                (AIProvider.OPENAI, "openai-test-model"): ConfidenceAnalyst(outputs),
            },
        )

    with localcontext() as ambient:
        ambient.prec = 6
        ambient.rounding = ROUND_DOWN
        low_precision = execute()
        assert (ambient.prec, ambient.rounding) == (6, ROUND_DOWN)
    with localcontext() as ambient:
        ambient.prec = 50
        ambient.rounding = ROUND_UP
        high_precision = execute()
        assert (ambient.prec, ambient.rounding) == (50, ROUND_UP)

    metrics = low_precision.metrics.provider_metrics[0]
    assert metrics.decision_agreement_count == 1
    assert metrics.decision_agreement_rate == Decimal("0.3333333333333333333333333333")
    assert metrics.average_confidence == Decimal("0.3666666666666666666666666667")
    assert low_precision.metrics == high_precision.metrics
    assert low_precision.metrics.metrics_id == high_precision.metrics.metrics_id
    assert low_precision.run_id == high_precision.run_id
    assert canonical_json(low_precision) == canonical_json(high_precision)


@pytest.mark.parametrize(
    "field",
    ("prompt_version", "projection_version", "schema_version", "parser_version"),
)
def test_replay_rejects_tampered_response_provenance(field: str) -> None:
    run, _, _ = build_run()
    tampered = copy(run.responses[0])
    object.__setattr__(tampered, field, "other-version")
    with pytest.raises(DomainValidationError, match="changed invocation semantics"):
        assemble_benchmark_run(
            protocol=run.protocol,
            cases=run.cases,
            invocations=run.invocations,
            responses=(tampered, *run.responses[1:]),
        )


def test_agreement_metrics_read_benchmark_only_case_reference() -> None:
    request = analysis_request()
    long_case = create_benchmark_case(
        request,
        benchmark_reference(TradeDecision.LONG, MarketRegime.TREND_UP),
        "long-reference",
    )
    short_case = create_benchmark_case(
        request,
        benchmark_reference(TradeDecision.SHORT, MarketRegime.TREND_DOWN),
        "short-reference",
    )
    spec = provider_spec(AIProvider.OPENAI)
    outputs = {request.request_id: (TradeDecision.LONG, MarketRegime.TREND_UP)}
    long_run = execute_benchmark(
        protocol=benchmark_protocol((long_case,), (spec,)),
        cases=(long_case,),
        analysts={(AIProvider.OPENAI, spec.model): MappingAnalyst(outputs)},
    )
    short_run = execute_benchmark(
        protocol=benchmark_protocol((short_case,), (spec,)),
        cases=(short_case,),
        analysts={(AIProvider.OPENAI, spec.model): MappingAnalyst(outputs)},
    )
    assert long_run.metrics.provider_metrics[0].decision_agreement_count == 1
    assert short_run.metrics.provider_metrics[0].decision_agreement_count == 0


def test_metric_calculation_and_protocol_versions_cannot_drift() -> None:
    run, openai, _ = build_run()
    references = {
        case.request.request_id: (
            case.reference.reference_decision,
            case.reference.reference_regime,
        )
        for case in run.cases
    }
    with pytest.raises(DomainValidationError, match="calculation policy"):
        calculate_metrics(
            run.protocol,
            references,
            run.responses,
            CalculationConfig(50, DecimalRoundingMode.ROUND_HALF_EVEN),
        )

    tampered = copy(run.protocol)
    object.__setattr__(tampered, "parser_version", "unknown-parser")
    before = openai.calls
    with pytest.raises(DomainValidationError, match="unregistered contract version"):
        execute_benchmark(protocol=tampered, cases=run.cases, analysts={})
    assert openai.calls == before
