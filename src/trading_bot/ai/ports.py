"""Provider-independent AI analysis port."""

from typing import Protocol

from trading_bot.ai.models import AIAnalysisRequest, AIAnalysisResponse, AIProviderInvocation


class AIAnalystPort(Protocol):
    def analyze(
        self, request: AIAnalysisRequest, invocation: AIProviderInvocation
    ) -> AIAnalysisResponse: ...
