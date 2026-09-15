"""Transport-neutral bounded provider adapter; no provider SDK or network client."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Protocol

from trading_bot.ai.models import (
    AIAnalysisRequest,
    AIAnalysisResponse,
    AIProviderInvocation,
    AIProviderSpec,
    AIResponseStatus,
)
from trading_bot.ai.parser import create_response, parse_response
from trading_bot.ai.prompts import render_prompt
from trading_bot.ai.versions import PROJECTION_VERSION, PROMPT_VERSION, SCHEMA_VERSION
from trading_bot.domain.errors import DomainValidationError


@dataclass(frozen=True, slots=True)
class AITransportResult:
    text: str
    provider_response_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class AITransport(Protocol):
    def send(self, prompt: str, spec: AIProviderSpec) -> AITransportResult: ...


class AITransportTimeout(Exception):
    """Provider transport exceeded the declared timeout."""


class AITransportRateLimit(Exception):
    """Provider transport reported rate limiting."""


class AITransportAuthError(Exception):
    """Provider transport reported authentication failure."""


class AITransportProviderError(Exception):
    def __init__(self, *, retryable: bool) -> None:
        super().__init__("sanitized provider error")
        self.retryable = retryable


class BoundedAIProviderAdapter:
    """Normalizes provider failures without knowing any vendor wire format."""

    def __init__(
        self,
        transport: AITransport,
        *,
        delay_observer: Callable[[timedelta], None] | None = None,
    ) -> None:
        self._transport = transport
        self._delay_observer = delay_observer or (lambda _: None)

    def analyze(
        self, request: AIAnalysisRequest, invocation: AIProviderInvocation
    ) -> AIAnalysisResponse:
        spec = invocation.provider_spec
        if invocation.request_id != request.request_id:
            raise DomainValidationError("AI invocation/request mismatch")
        if (
            request.prompt_version != PROMPT_VERSION
            or request.projection_version != PROJECTION_VERSION
            or request.schema_version != SCHEMA_VERSION
        ):
            raise DomainValidationError("AI request uses an unregistered contract version")
        if not spec.enabled:
            return create_response(
                request=request,
                invocation=invocation,
                status=AIResponseStatus.PROVIDER_ERROR,
                attempts=1,
                error_code="PROVIDER_DISABLED",
            )
        prompt = render_prompt(request)
        for attempt in range(1, spec.max_attempts + 1):
            try:
                result = self._transport.send(prompt, spec)
            except AITransportAuthError:
                return self._failure(request, invocation, AIResponseStatus.AUTH_ERROR, attempt)
            except AITransportTimeout:
                response = self._failure(request, invocation, AIResponseStatus.TIMEOUT, attempt)
            except AITransportRateLimit:
                response = self._failure(request, invocation, AIResponseStatus.RATE_LIMIT, attempt)
            except AITransportProviderError as error:
                response = self._failure(
                    request, invocation, AIResponseStatus.PROVIDER_ERROR, attempt
                )
                if not error.retryable:
                    return response
            else:
                return parse_response(
                    raw_text=result.text,
                    request=request,
                    invocation=invocation,
                    attempts=attempt,
                    provider_response_id=result.provider_response_id,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                )
            if attempt < spec.max_attempts:
                self._delay_observer(_backoff(spec, attempt))
        return response

    @staticmethod
    def _failure(
        request: AIAnalysisRequest,
        invocation: AIProviderInvocation,
        status: AIResponseStatus,
        attempts: int,
    ) -> AIAnalysisResponse:
        return create_response(
            request=request,
            invocation=invocation,
            status=status,
            attempts=attempts,
            error_code=status.value,
        )


def _backoff(spec: AIProviderSpec, completed_attempts: int) -> timedelta:
    initial_microseconds = spec.initial_backoff // timedelta(microseconds=1)
    maximum_microseconds = spec.maximum_backoff // timedelta(microseconds=1)
    multiplier = spec.backoff_multiplier ** Decimal(completed_attempts - 1)
    value = int((Decimal(initial_microseconds) * multiplier).to_integral_value())
    return timedelta(microseconds=min(value, maximum_microseconds))
