from __future__ import annotations

from copy import copy
from dataclasses import fields, replace
from datetime import timedelta
from decimal import getcontext, setcontext

import pytest

from tests.ai.helpers import (
    AS_OF,
    analysis_request,
    benchmark_cases,
    benchmark_protocol,
    benchmark_reference,
    changed_request,
    provider_spec,
    response_json,
)
from trading_bot.ai.identity import create_benchmark_case, create_invocation
from trading_bot.ai.models import (
    AIAnalysisResponse,
    AIMarketEvidence,
    AIProvider,
    AIResponseStatus,
)
from trading_bot.ai.parser import create_response, parse_response
from trading_bot.ai.prompts import render_prompt
from trading_bot.ai.versions import PARSER_VERSION
from trading_bot.config.models import CalculationConfig
from trading_bot.domain.enums import (
    DecimalRoundingMode,
    MarketRegime,
    Timeframe,
    TradeDecision,
)
from trading_bot.domain.errors import DomainValidationError
from trading_bot.historical.models import HistoricalVersionSet


def test_request_identity_changes_with_every_frozen_semantic_version() -> None:
    request = analysis_request()
    variants = (
        changed_request(request, code_version="code-v2"),
        changed_request(request, strategy_version="strategy-v2"),
        changed_request(request, config_version="config-v2"),
        changed_request(
            request, historical_versions=HistoricalVersionSet("m5-v2", "m15-v1", "h1-v1")
        ),
        changed_request(request, instrument_version="instrument-v2"),
    )
    assert len({request.request_id, *(item.request_id for item in variants)}) == 6


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("prompt_version", "prompt-v999"),
        ("projection_version", "projection-v999"),
        ("schema_version", "schema-v999"),
    ),
)
def test_request_factory_rejects_unregistered_contract_versions(field: str, value: str) -> None:
    with pytest.raises(DomainValidationError, match="registered contract versions"):
        changed_request(analysis_request(), **{field: value})


def test_request_rejects_tampered_identity_and_projection_bounds() -> None:
    request = analysis_request()
    with pytest.raises(DomainValidationError, match="request_id"):
        replace(request, strategy_version="tampered")
    with pytest.raises(DomainValidationError, match="candle projection"):
        replace(
            request,
            limits=replace(request.limits, max_candles_per_timeframe=1),
            evidence=replace(
                request.evidence,
                candles=(
                    replace(
                        request.evidence.candles[0],
                        close_time=AS_OF + timedelta(minutes=-5),
                    ),
                    *request.evidence.candles[1:],
                    replace(
                        request.evidence.candles[0],
                        candle_id="extra",
                    ),
                ),
            ),
        )


def test_future_candle_and_observation_fail_closed() -> None:
    request = analysis_request()
    with pytest.raises(DomainValidationError, match="future candle"):
        replace(
            request.evidence,
            candles=(
                replace(request.evidence.candles[0], close_time=AS_OF + timedelta(seconds=1)),
                *request.evidence.candles[1:],
            ),
        )
    with pytest.raises(DomainValidationError, match="future observation"):
        replace(
            request.evidence,
            observations=(
                replace(request.evidence.observations[0], observed_at=AS_OF + timedelta(seconds=1)),
            ),
        )


def test_evidence_rejects_missing_timeframe_duplicate_and_bad_order() -> None:
    request = analysis_request()
    with pytest.raises(DomainValidationError, match="M5, M15, and H1"):
        replace(
            request.evidence,
            candles=tuple(
                item for item in request.evidence.candles if item.timeframe is not Timeframe.H1
            ),
        )
    with pytest.raises(DomainValidationError, match="duplicate candle"):
        replace(
            request.evidence,
            candles=(*request.evidence.candles, request.evidence.candles[0]),
        )


def test_provider_and_model_are_bound_to_invocation_identity() -> None:
    request = analysis_request()
    first = create_invocation(request.request_id, provider_spec(), 0)
    repeat = create_invocation(request.request_id, provider_spec(), 1)
    model = create_invocation(request.request_id, provider_spec(model="other-model"), 0)
    provider = create_invocation(request.request_id, provider_spec(AIProvider.GEMINI), 0)
    assert (
        len(
            {first.invocation_id, repeat.invocation_id, model.invocation_id, provider.invocation_id}
        )
        == 4
    )


def test_protocol_identity_binds_provider_set_and_order() -> None:
    cases = benchmark_cases()
    specs = tuple(provider_spec(provider) for provider in AIProvider)
    baseline = benchmark_protocol(cases, specs)
    reversed_protocol = benchmark_protocol(cases, tuple(reversed(specs)))
    disabled = benchmark_protocol(cases, (replace(specs[0], enabled=False), *specs[1:]))
    changed_calculation = benchmark_protocol(
        cases,
        specs,
        calculation=CalculationConfig(50, DecimalRoundingMode.ROUND_HALF_EVEN),
    )
    assert (
        len(
            {
                baseline.protocol_id,
                reversed_protocol.protocol_id,
                disabled.protocol_id,
                changed_calculation.protocol_id,
            }
        )
        == 4
    )
    with pytest.raises(DomainValidationError, match="unique"):
        replace(baseline, provider_specs=(specs[0], specs[0]))


def test_prompt_is_canonical_bounded_and_contains_no_outcomes_or_execution_fields() -> None:
    prompt = render_prompt(analysis_request())
    assert prompt == render_prompt(analysis_request())
    assert "Do not provide hidden reasoning or chain of thought" in prompt
    for forbidden_reference in (
        "reference_decision",
        "reference_regime",
        "reference_reason_codes",
        "expected_decision",
        "strategy_answer",
        "reference_label",
        "correct_regime",
        "baseline_decision",
    ):
        assert forbidden_reference not in prompt
    for forbidden in ('"pnl"', '"mfe"', '"mae"', '"exit"', '"winner"'):
        assert forbidden not in prompt.lower()
    tampered = copy(analysis_request())
    object.__setattr__(tampered, "prompt_version", "other-prompt")
    with pytest.raises(DomainValidationError, match="unregistered"):
        render_prompt(tampered)


def test_parser_rejects_unregistered_schema_before_parsing() -> None:
    request = analysis_request()
    invocation = create_invocation(request.request_id, provider_spec())
    tampered = copy(request)
    object.__setattr__(tampered, "schema_version", "other-schema")
    with pytest.raises(DomainValidationError, match="unregistered"):
        parse_response(
            raw_text=response_json(TradeDecision.LONG, MarketRegime.TREND_UP),
            request=tampered,
            invocation=invocation,
            attempts=1,
        )
    with pytest.raises(DomainValidationError, match="unregistered"):
        create_response(
            request=tampered,
            invocation=invocation,
            status=AIResponseStatus.TIMEOUT,
            attempts=1,
            error_code="TIMEOUT",
        )


def test_reference_labels_are_not_model_visible() -> None:
    request = analysis_request()
    long_case = create_benchmark_case(
        request,
        benchmark_reference(TradeDecision.LONG, MarketRegime.TREND_UP),
        "same-input",
    )
    short_case = create_benchmark_case(
        request,
        benchmark_reference(TradeDecision.SHORT, MarketRegime.TREND_DOWN),
        "same-input",
    )
    long_protocol = benchmark_protocol((long_case,))
    short_protocol = benchmark_protocol((short_case,))

    model_visible_fields = {item.name for item in fields(AIMarketEvidence)}
    assert "reference_decision" not in model_visible_fields
    assert "reference_regime" not in model_visible_fields
    assert "reference_reason_codes" not in model_visible_fields
    assert long_case.request.request_id == short_case.request.request_id
    assert render_prompt(long_case.request) == render_prompt(short_case.request)
    assert long_case.case_id != short_case.case_id
    assert long_protocol.protocol_id != short_protocol.protocol_id
    with pytest.raises(DomainValidationError, match="unique model-visible request IDs"):
        benchmark_protocol((long_case, short_case))


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("prompt_version", "prompt-v999"),
        ("projection_version", "projection-v999"),
        ("schema_version", "schema-v999"),
        ("parser_version", "parser-v999"),
    ),
)
def test_protocol_factory_rejects_unregistered_contract_versions(field: str, value: str) -> None:
    with pytest.raises(DomainValidationError, match="registered contract versions"):
        benchmark_protocol(**{field: value})


@pytest.mark.parametrize(
    ("raw", "status"),
    (
        ("not-json", AIResponseStatus.INVALID_RESPONSE),
        ('{"decision":"LONG"}', AIResponseStatus.INVALID_RESPONSE),
        (
            '{"decision":"LONG","regime":"TREND_UP","confidence":0.8,"reasons":[],"risk_flags":[]}',
            AIResponseStatus.SCHEMA_VALIDATION_FAILED,
        ),
        (
            '{"decision":"BUY","regime":"TREND_UP","confidence":"0.8","reasons":[],"risk_flags":[]}',
            AIResponseStatus.SCHEMA_VALIDATION_FAILED,
        ),
        (
            '{"decision":"LONG","regime":"TREND_UP","confidence":"2","reasons":[],"risk_flags":[]}',
            AIResponseStatus.SCHEMA_VALIDATION_FAILED,
        ),
        (
            '{"decision":"LONG","regime":"TREND_UP","confidence":"0.8","reasons":[],"risk_flags":[],"quantity":"1"}',
            AIResponseStatus.INVALID_RESPONSE,
        ),
        (
            '{"decision":1,"regime":"TREND_UP","confidence":"0.8","reasons":[],"risk_flags":[]}',
            AIResponseStatus.SCHEMA_VALIDATION_FAILED,
        ),
        (
            '{"decision":"LONG","regime":"TREND_UP","confidence":"0.8","reasons":"bad","risk_flags":[]}',
            AIResponseStatus.SCHEMA_VALIDATION_FAILED,
        ),
        (
            '{"decision":"LONG","regime":"TREND_UP","confidence":"0.8","reasons":[""],"risk_flags":[]}',
            AIResponseStatus.SCHEMA_VALIDATION_FAILED,
        ),
    ),
)
def test_parser_returns_typed_failures_without_fabricated_no_trade(
    raw: str, status: AIResponseStatus
) -> None:
    request = analysis_request()
    invocation = create_invocation(request.request_id, provider_spec())
    response = parse_response(raw_text=raw, request=request, invocation=invocation, attempts=1)
    assert response.status is status
    assert response.decision is None
    assert response.regime is None
    assert response.confidence is None


def test_success_response_is_strict_and_decimal_context_independent() -> None:
    request = analysis_request()
    invocation = create_invocation(request.request_id, provider_spec())
    original = getcontext().copy()
    try:
        getcontext().prec = 6
        first = parse_response(
            raw_text=response_json(TradeDecision.LONG, MarketRegime.TREND_UP, "0.812345"),
            request=request,
            invocation=invocation,
            attempts=1,
        )
        getcontext().prec = 28
        second = parse_response(
            raw_text=response_json(TradeDecision.LONG, MarketRegime.TREND_UP, "0.812345"),
            request=request,
            invocation=invocation,
            attempts=1,
        )
    finally:
        setcontext(original)
    assert first == second
    assert first.status is AIResponseStatus.SUCCESS


def test_failure_response_cannot_masquerade_as_no_trade() -> None:
    request = analysis_request()
    invocation = create_invocation(request.request_id, provider_spec())
    failure = create_response(
        request=request,
        invocation=invocation,
        status=AIResponseStatus.TIMEOUT,
        attempts=3,
        error_code="TIMEOUT",
    )
    assert failure.decision is None
    assert failure.parser_version == PARSER_VERSION
    with pytest.raises(DomainValidationError, match="failed AI response"):
        replace(failure, decision=TradeDecision.NO_TRADE)
    with pytest.raises(DomainValidationError, match="response_id"):
        replace(failure, attempts=2)


def test_direct_invalid_response_contracts_are_rejected() -> None:
    request = analysis_request()
    invocation = create_invocation(request.request_id, provider_spec())
    success = parse_response(
        raw_text=response_json(TradeDecision.LONG, MarketRegime.TREND_UP),
        request=request,
        invocation=invocation,
        attempts=1,
    )
    with pytest.raises(DomainValidationError, match="three reasons"):
        replace(success, reasons=("a", "b", "c", "d"))
    assert isinstance(success, AIAnalysisResponse)
