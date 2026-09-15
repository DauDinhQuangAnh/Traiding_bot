"""Versioned, deterministic prompt rendering without chain-of-thought requests."""

from __future__ import annotations

from trading_bot.ai.models import AIAnalysisRequest
from trading_bot.ai.versions import PROJECTION_VERSION, PROMPT_VERSION, SCHEMA_VERSION
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.primitives import canonical_json


def render_prompt(request: AIAnalysisRequest) -> str:
    if (
        request.prompt_version != PROMPT_VERSION
        or request.projection_version != PROJECTION_VERSION
        or request.schema_version != SCHEMA_VERSION
    ):
        raise DomainValidationError("unregistered AI prompt contract version")
    evidence_json = canonical_json(request.evidence)
    return (
        "You are a read-only market-analysis benchmark. Use only the point-in-time evidence "
        "below. Do not infer future outcomes, PnL, position size, leverage, stops, targets, "
        "orders, or execution actions. Return exactly one JSON object with keys decision, "
        "regime, confidence, reasons, risk_flags. decision must be LONG, SHORT, or NO_TRADE; "
        "regime must be TREND_UP, TREND_DOWN, SIDEWAY, HIGH_VOLATILITY, or UNCERTAIN; "
        "confidence must be a decimal string in [0,1]; reasons must contain at most three "
        "concise items. Do not provide hidden reasoning or chain of thought.\n"
        f"schema_version={request.schema_version}\n"
        f"projection_version={request.projection_version}\n"
        f"evidence={evidence_json}"
    )
