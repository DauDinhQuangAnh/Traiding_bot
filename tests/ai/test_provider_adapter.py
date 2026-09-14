from __future__ import annotations

from datetime import timedelta

import pytest

from tests.ai.helpers import analysis_request, provider_spec, response_json
from trading_bot.ai.identity import create_invocation
from trading_bot.ai.models import AIResponseStatus
from trading_bot.domain.enums import MarketRegime, TradeDecision
from trading_bot.infrastructure.ai_fakes import DeterministicFakeAIAnalyst, ScriptedAITransport
from trading_bot.infrastructure.ai_provider import (
    AITransportAuthError,
    AITransportProviderError,
    AITransportRateLimit,
    AITransportResult,
    AITransportTimeout,
    BoundedAIProviderAdapter,
)


def _run(outcomes: list[AITransportResult | Exception], *, attempts: int = 3):
    request = analysis_request()
    spec = provider_spec(max_attempts=attempts)
    invocation = create_invocation(request.request_id, spec)
    transport = ScriptedAITransport(outcomes)
    delays: list[timedelta] = []
    response = BoundedAIProviderAdapter(transport, delay_observer=delays.append).analyze(
        request, invocation
    )
    return response, transport.call_count, delays


@pytest.mark.parametrize(
    ("error", "status"),
    (
        (AITransportTimeout(), AIResponseStatus.TIMEOUT),
        (AITransportRateLimit(), AIResponseStatus.RATE_LIMIT),
        (AITransportProviderError(retryable=True), AIResponseStatus.PROVIDER_ERROR),
    ),
)
def test_retryable_failures_are_bounded_and_do_not_sleep(
    error: Exception, status: AIResponseStatus
) -> None:
    response, calls, delays = _run([error], attempts=3)
    assert response.status is status
    assert response.attempts == 3
    assert calls == 3
    assert delays == [timedelta(seconds=1), timedelta(seconds=2)]


def test_retry_can_recover_and_caps_backoff() -> None:
    result = AITransportResult(
        response_json(TradeDecision.LONG, MarketRegime.TREND_UP),
        "provider-id",
        12,
        7,
    )
    response, calls, delays = _run([AITransportRateLimit(), AITransportTimeout(), result])
    assert response.status is AIResponseStatus.SUCCESS
    assert response.attempts == 3
    assert response.input_tokens == 12
    assert response.output_tokens == 7
    assert calls == 3
    assert delays == [timedelta(seconds=1), timedelta(seconds=2)]


def test_auth_and_non_retryable_provider_errors_are_terminal() -> None:
    auth, auth_calls, auth_delays = _run([AITransportAuthError()])
    provider, provider_calls, provider_delays = _run([AITransportProviderError(retryable=False)])
    assert auth.status is AIResponseStatus.AUTH_ERROR
    assert provider.status is AIResponseStatus.PROVIDER_ERROR
    assert (auth_calls, provider_calls) == (1, 1)
    assert auth_delays == provider_delays == []


def test_disabled_provider_never_touches_transport() -> None:
    request = analysis_request()
    spec = provider_spec(enabled=False)
    invocation = create_invocation(request.request_id, spec)
    transport = ScriptedAITransport([AssertionError("transport must not run")])
    response = BoundedAIProviderAdapter(transport).analyze(request, invocation)
    assert response.status is AIResponseStatus.PROVIDER_ERROR
    assert response.error_code == "PROVIDER_DISABLED"
    assert transport.call_count == 0


def test_deterministic_fake_is_offline_replayable_and_validates_identity() -> None:
    request = analysis_request()
    invocation = create_invocation(request.request_id, provider_spec())
    fake = DeterministicFakeAIAnalyst(response_json(TradeDecision.NO_TRADE, MarketRegime.SIDEWAY))
    first = fake.analyze(request, invocation)
    second = fake.analyze(request, invocation)
    assert first == second
    assert fake.calls == [request.request_id, request.request_id]
    mismatch = create_invocation("other", provider_spec())
    with pytest.raises(Exception, match="mismatch"):
        fake.analyze(request, mismatch)


def test_scripted_transport_requires_an_outcome_and_repeats_last_result() -> None:
    with pytest.raises(Exception, match="requires outcomes"):
        ScriptedAITransport([])
    result = AITransportResult(response_json(TradeDecision.NO_TRADE, MarketRegime.SIDEWAY))
    transport = ScriptedAITransport([result])
    assert transport.send("prompt", object()) == result
    assert transport.send("prompt", object()) == result


def test_adapter_rejects_invocation_request_mismatch() -> None:
    request = analysis_request()
    invocation = create_invocation("other-request", provider_spec())
    adapter = BoundedAIProviderAdapter(ScriptedAITransport([AITransportTimeout()]))
    with pytest.raises(Exception, match="mismatch"):
        adapter.analyze(request, invocation)
