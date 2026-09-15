from __future__ import annotations

from copy import copy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from tests.ai.helpers import (
    AS_OF,
    analysis_request,
    benchmark_protocol,
    benchmark_reference,
    changed_request,
    provider_spec,
    response_json,
)
from tests.ai.test_benchmark import build_run
from trading_bot.ai.identity import create_benchmark_case, create_invocation
from trading_bot.ai.models import (
    AIObservation,
    AIProjectionLimits,
    AIProviderMetrics,
    AIReferenceDecisionMetrics,
    AIResponseStatus,
)
from trading_bot.ai.parser import create_response, parse_response
from trading_bot.domain.enums import MarketRegime, ReasonCode, TradeDecision
from trading_bot.domain.errors import DomainValidationError


@pytest.mark.parametrize(
    "limits",
    (
        (0, 100, 20, 240),
        (20, 0, 20, 240),
        (20, 100, 0, 240),
        (20, 100, 20, 15),
    ),
)
def test_projection_limit_boundaries(limits: tuple[int, int, int, int]) -> None:
    with pytest.raises(DomainValidationError):
        AIProjectionLimits(*limits)


def test_candle_and_observation_validation_boundaries() -> None:
    request = analysis_request()
    candle = request.evidence.candles[0]
    with pytest.raises(DomainValidationError, match="high/low"):
        replace(candle, high=Decimal("99"))
    with pytest.raises(DomainValidationError, match="category"):
        AIObservation("OUTCOME", "future_pnl", Decimal("1"), AS_OF, "source")
    with pytest.raises(DomainValidationError, match="must be Decimal"):
        AIObservation("SIGNAL", "invalid", 1, AS_OF, "source")  # type: ignore[arg-type]
    assert AIObservation("SIGNAL", "flag", True, AS_OF, "source").value is True
    assert AIObservation("SIGNAL", "label", "safe", AS_OF, "source").value == "safe"


def test_evidence_empty_order_duplicate_observation_and_reference_reason_guards() -> None:
    request = analysis_request()
    with pytest.raises(DomainValidationError, match="requires candles"):
        replace(request.evidence, candles=())
    earlier = replace(
        request.evidence.candles[0],
        candle_id="earlier",
        close_time=AS_OF - timedelta(minutes=5),
    )
    with pytest.raises(DomainValidationError, match="ordered"):
        replace(request.evidence, candles=(*request.evidence.candles, earlier))
    with pytest.raises(DomainValidationError, match="duplicate observations"):
        replace(
            request.evidence,
            observations=(request.evidence.observations[0], request.evidence.observations[0]),
        )
    with pytest.raises(DomainValidationError, match="requires reason"):
        replace(benchmark_reference(), reference_reason_codes=())


def test_request_observation_reason_and_text_bounds() -> None:
    request = analysis_request()
    many = tuple(
        replace(item, name=f"item-{index}")
        for index, item in enumerate(request.evidence.observations * 2)
    )
    with pytest.raises(DomainValidationError, match="observation projection"):
        replace(
            request,
            evidence=replace(request.evidence, observations=many),
            limits=replace(request.limits, max_observations=2),
        )
    with pytest.raises(DomainValidationError, match="reason projection"):
        create_benchmark_case(
            changed_request(request, limits=replace(request.limits, max_reason_codes=1)),
            replace(
                benchmark_reference(),
                reference_reason_codes=(ReasonCode.NO_SIGNAL, ReasonCode.SCORE_TOO_LOW),
            ),
            "too-many-reasons",
        )
    text = AIObservation("SIGNAL", "label", "x" * 17, AS_OF, "source-text")
    with pytest.raises(DomainValidationError, match="text observation"):
        replace(
            request,
            evidence=replace(request.evidence, observations=(text,)),
            limits=replace(request.limits, max_text_length=16),
        )


@pytest.mark.parametrize(
    "change",
    (
        {"temperature": Decimal("2.1")},
        {"max_output_tokens": 0},
        {"timeout": timedelta(0)},
        {"max_attempts": 0},
        {"initial_backoff": timedelta(0)},
        {"backoff_multiplier": Decimal("0.9")},
        {"maximum_backoff": timedelta(milliseconds=1)},
    ),
)
def test_provider_spec_rejects_unbounded_or_invalid_policy(change: dict[str, object]) -> None:
    with pytest.raises(DomainValidationError):
        replace(provider_spec(), **change)


def test_invocation_sequence_and_identity_are_self_validating() -> None:
    request = analysis_request()
    invocation = create_invocation(request.request_id, provider_spec())
    with pytest.raises(DomainValidationError, match="non-negative"):
        create_invocation(request.request_id, provider_spec(), -1)
    with pytest.raises(DomainValidationError, match="invocation_id"):
        replace(invocation, request_id="changed")


def test_response_success_and_failure_shape_guards() -> None:
    request = analysis_request()
    invocation = create_invocation(request.request_id, provider_spec())
    success = parse_response(
        raw_text=response_json(TradeDecision.LONG, MarketRegime.TREND_UP),
        request=request,
        invocation=invocation,
        attempts=1,
    )
    failure = create_response(
        request=request,
        invocation=invocation,
        status=AIResponseStatus.TIMEOUT,
        attempts=1,
        error_code="TIMEOUT",
    )
    invalid_changes = (
        (success, {"attempts": 0}),
        (success, {"input_tokens": -1}),
        (success, {"provider_response_id": ""}),
        (success, {"provider_response_id": "x" * 241}),
        (success, {"prompt_version": "other-prompt"}),
        (success, {"projection_version": "other-projection"}),
        (success, {"schema_version": "other-schema"}),
        (success, {"parser_version": "other-parser"}),
        (success, {"risk_flags": tuple("x" for _ in range(11))}),
        (success, {"reasons": ("",)}),
        (success, {"risk_flags": ("x" * 81,)}),
        (success, {"decision": None}),
        (success, {"error_code": "ERROR"}),
        (failure, {"reasons": ("fake analysis",)}),
        (failure, {"error_code": None}),
        (failure, {"error_code": "raw provider exception text"}),
    )
    for value, change in invalid_changes:
        with pytest.raises(DomainValidationError):
            replace(value, **change)


def test_protocol_case_and_provider_requirements_are_strict() -> None:
    protocol = benchmark_protocol()
    with pytest.raises(DomainValidationError, match="case IDs"):
        replace(protocol, case_ids=())
    with pytest.raises(DomainValidationError, match="request IDs"):
        replace(protocol, request_ids=(protocol.request_ids[0],) * len(protocol.request_ids))
    with pytest.raises(DomainValidationError, match="provider specs"):
        replace(protocol, provider_specs=())
    with pytest.raises(DomainValidationError, match="case_set_id"):
        replace(protocol, case_set_id="tampered")
    with pytest.raises(DomainValidationError, match="protocol_id"):
        replace(protocol, metrics_version="changed")


def test_metric_and_run_reconciliation_guards() -> None:
    run, _, _ = build_run()
    provider = run.metrics.provider_metrics[0]
    invalid_provider_changes = (
        {"case_count": -1},
        {"failure_count": 1},
        {"long_count": provider.long_count + 1},
        {"reference_decision_metrics": ()},
        {"confidence_count": 0},
        {"confidence_buckets": (-1, 1, 1, 0, 0)},
        {"input_tokens": -1},
    )
    for change in invalid_provider_changes:
        with pytest.raises(DomainValidationError):
            replace(provider, **change)
    empty_reference = AIReferenceDecisionMetrics(TradeDecision.LONG, 0, 0, None)
    assert empty_reference.agreement_rate is None
    with pytest.raises(DomainValidationError):
        AIReferenceDecisionMetrics(TradeDecision.LONG, 0, 1, None)
    with pytest.raises(DomainValidationError):
        AIReferenceDecisionMetrics(TradeDecision.LONG, 0, 0, Decimal("0"))
    pair = run.metrics.pairwise_metrics[0]
    with pytest.raises(DomainValidationError):
        replace(pair, comparable_count=-1)
    with pytest.raises(DomainValidationError):
        replace(pair, decision_divergence_count=0)
    with pytest.raises(DomainValidationError):
        replace(pair, regime_divergence_count=0)
    with pytest.raises(DomainValidationError, match="responses must match"):
        replace(run.metrics, expected_response_count=8)
    with pytest.raises(DomainValidationError, match="success totals"):
        replace(run.metrics, success_count=7, failure_count=2)
    with pytest.raises(DomainValidationError, match="metrics_id"):
        replace(run.metrics, metrics_version="changed")
    with pytest.raises(DomainValidationError, match="cases do not match"):
        replace(run, cases=tuple(reversed(run.cases)))
    with pytest.raises(DomainValidationError, match="requires one typed response"):
        replace(run, responses=run.responses[:-1])
    with pytest.raises(DomainValidationError, match="order/identity"):
        replace(run, responses=tuple(reversed(run.responses)))
    mismatched_metrics = copy(run.metrics)
    object.__setattr__(mismatched_metrics, "protocol_id", "other")
    with pytest.raises(DomainValidationError, match="protocol mismatch"):
        replace(run, metrics=mismatched_metrics)
    with pytest.raises(DomainValidationError, match="status"):
        replace(run, status=run.status.__class__.COMPLETED)
    with pytest.raises(DomainValidationError, match="run_id"):
        replace(run, run_id="tampered")


def test_provider_metric_explicit_empty_sample_rules() -> None:
    run, _, _ = build_run()
    empty = run.metrics.provider_metrics[2]
    assert isinstance(empty, AIProviderMetrics)
    with pytest.raises(DomainValidationError, match="empty decision"):
        replace(empty, long_rate=Decimal("0"))
    with pytest.raises(DomainValidationError, match="empty confidence"):
        replace(empty, average_confidence=Decimal("0"))
