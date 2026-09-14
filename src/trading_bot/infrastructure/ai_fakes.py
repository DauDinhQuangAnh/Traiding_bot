"""Deterministic fake AI provider/transport for offline tests and examples."""

from __future__ import annotations

from collections.abc import Sequence

from trading_bot.ai.models import AIAnalysisRequest, AIAnalysisResponse, AIProviderInvocation
from trading_bot.ai.parser import parse_response
from trading_bot.domain.errors import DomainValidationError
from trading_bot.infrastructure.ai_provider import AITransportResult


class DeterministicFakeAIAnalyst:
    def __init__(self, response_json: str) -> None:
        self._response_json = response_json
        self.calls: list[str] = []

    def analyze(
        self, request: AIAnalysisRequest, invocation: AIProviderInvocation
    ) -> AIAnalysisResponse:
        if request.request_id != invocation.request_id:
            raise DomainValidationError("fake invocation/request mismatch")
        self.calls.append(request.request_id)
        return parse_response(
            raw_text=self._response_json,
            request=request,
            invocation=invocation,
            attempts=1,
            provider_response_id=f"fake-{invocation.invocation_id[:12]}",
        )


class ScriptedAITransport:
    def __init__(self, outcomes: Sequence[AITransportResult | Exception]) -> None:
        if not outcomes:
            raise DomainValidationError("scripted transport requires outcomes")
        self._outcomes = tuple(outcomes)
        self.call_count = 0

    def send(self, prompt: str, spec: object) -> AITransportResult:
        del prompt, spec
        index = min(self.call_count, len(self._outcomes) - 1)
        self.call_count += 1
        outcome = self._outcomes[index]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
