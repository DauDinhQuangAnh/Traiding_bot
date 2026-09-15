"""Strict structured-response parsing and typed failure construction."""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from trading_bot.ai.models import (
    AIAnalysisRequest,
    AIAnalysisResponse,
    AIProviderInvocation,
    AIResponseStatus,
)
from trading_bot.ai.versions import PARSER_VERSION, SCHEMA_VERSION
from trading_bot.domain.enums import MarketRegime, TradeDecision
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.identifiers import deterministic_id
from trading_bot.domain.primitives import require_ratio

_FIELDS = {"decision", "regime", "confidence", "reasons", "risk_flags"}
SUPPORTED_SCHEMA_VERSION = SCHEMA_VERSION


def create_response(
    *,
    request: AIAnalysisRequest,
    invocation: AIProviderInvocation,
    status: AIResponseStatus,
    attempts: int,
    decision: TradeDecision | None = None,
    regime: MarketRegime | None = None,
    confidence: Decimal | None = None,
    reasons: tuple[str, ...] = (),
    risk_flags: tuple[str, ...] = (),
    provider_response_id: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    error_code: str | None = None,
) -> AIAnalysisResponse:
    if request.schema_version != SUPPORTED_SCHEMA_VERSION:
        raise DomainValidationError("unregistered AI response schema version")
    values = (
        invocation.invocation_id,
        request.request_id,
        invocation.provider_spec.provider,
        invocation.provider_spec.model,
        status,
        decision,
        regime,
        confidence,
        reasons,
        risk_flags,
        provider_response_id,
        request.prompt_version,
        request.projection_version,
        request.schema_version,
        PARSER_VERSION,
        attempts,
        input_tokens,
        output_tokens,
        error_code,
    )
    return AIAnalysisResponse(
        deterministic_id("ai-analysis-response-v1", *values),
        *values,
    )


def parse_response(
    *,
    raw_text: str,
    request: AIAnalysisRequest,
    invocation: AIProviderInvocation,
    attempts: int,
    provider_response_id: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> AIAnalysisResponse:
    if request.schema_version != SUPPORTED_SCHEMA_VERSION:
        raise DomainValidationError("unregistered AI response schema version")
    try:
        value = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        return create_response(
            request=request,
            invocation=invocation,
            status=AIResponseStatus.INVALID_RESPONSE,
            attempts=attempts,
            error_code="MALFORMED_JSON",
        )
    if not isinstance(value, Mapping) or set(value) != _FIELDS:
        return create_response(
            request=request,
            invocation=invocation,
            status=AIResponseStatus.INVALID_RESPONSE,
            attempts=attempts,
            error_code="UNEXPECTED_RESPONSE_SHAPE",
        )
    try:
        response = _parse_mapping(value)
        return create_response(
            request=request,
            invocation=invocation,
            status=AIResponseStatus.SUCCESS,
            attempts=attempts,
            decision=response[0],
            regime=response[1],
            confidence=response[2],
            reasons=response[3],
            risk_flags=response[4],
            provider_response_id=provider_response_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    except (ValueError, InvalidOperation, DomainValidationError, TypeError):
        return create_response(
            request=request,
            invocation=invocation,
            status=AIResponseStatus.SCHEMA_VALIDATION_FAILED,
            attempts=attempts,
            error_code="SCHEMA_VALIDATION_FAILED",
        )


def _parse_mapping(
    value: Mapping[str, Any],
) -> tuple[TradeDecision, MarketRegime, Decimal, tuple[str, ...], tuple[str, ...]]:
    if not isinstance(value["decision"], str) or not isinstance(value["regime"], str):
        raise TypeError("decision and regime must be strings")
    if not isinstance(value["confidence"], str):
        raise TypeError("confidence must be a lossless decimal string")
    confidence = Decimal(value["confidence"])
    require_ratio(confidence, "AI response confidence")
    reasons = _string_tuple(value["reasons"], maximum=3, maximum_length=240)
    flags = _string_tuple(value["risk_flags"], maximum=10, maximum_length=80)
    return (
        TradeDecision(value["decision"]),
        MarketRegime(value["regime"]),
        confidence,
        reasons,
        flags,
    )


def _string_tuple(value: Any, *, maximum: int, maximum_length: int) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > maximum:
        raise TypeError("invalid response list")
    if any(
        not isinstance(item, str) or not item.strip() or len(item) > maximum_length
        for item in value
    ):
        raise TypeError("invalid response text")
    return tuple(value)
