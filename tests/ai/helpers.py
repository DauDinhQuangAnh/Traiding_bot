from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trading_bot.ai.identity import (
    create_analysis_request,
    create_benchmark_case,
    create_benchmark_protocol,
)
from trading_bot.ai.models import (
    AIAnalysisRequest,
    AIBenchmarkCase,
    AIBenchmarkProtocol,
    AICandleEvidence,
    AIMarketEvidence,
    AIObservation,
    AIProjectionLimits,
    AIProvider,
    AIProviderSpec,
)
from trading_bot.ai.prompts import PROMPT_VERSION, SCHEMA_VERSION
from trading_bot.domain.enums import MarketRegime, ReasonCode, Timeframe, TradeDecision
from trading_bot.historical.models import HistoricalVersionSet

AS_OF = datetime(2024, 1, 1, 12, tzinfo=UTC)
HISTORICAL = HistoricalVersionSet("m5-v1", "m15-v1", "h1-v1")
LIMITS = AIProjectionLimits(20, 100, 20, 240)


def provider_spec(
    provider: AIProvider = AIProvider.OPENAI,
    *,
    model: str | None = None,
    enabled: bool = True,
    max_attempts: int = 3,
) -> AIProviderSpec:
    return AIProviderSpec(
        provider,
        model or f"{provider.value.lower()}-test-model",
        Decimal("0"),
        500,
        timedelta(seconds=30),
        max_attempts,
        timedelta(seconds=1),
        Decimal("2"),
        timedelta(seconds=4),
        f"{provider.value.lower()}-config-v1",
        enabled,
    )


def analysis_request(
    decision: TradeDecision = TradeDecision.NO_TRADE,
    regime: MarketRegime = MarketRegime.SIDEWAY,
    *,
    prompt_version: str = PROMPT_VERSION,
) -> AIAnalysisRequest:
    candles = tuple(
        AICandleEvidence(
            f"{timeframe.value}-candle",
            timeframe,
            AS_OF,
            Decimal("100"),
            Decimal("102"),
            Decimal("99"),
            Decimal("101"),
            Decimal("10"),
        )
        for timeframe in Timeframe
    )
    evidence = AIMarketEvidence(
        "BTC-USDT-SWAP",
        AS_OF,
        candles,
        (
            AIObservation("INDICATOR", "15m.rsi", Decimal("55"), AS_OF, "indicator-1"),
            AIObservation("SIGNAL", "long_score", Decimal("42"), AS_OF, "signal-1"),
        ),
        decision,
        regime,
        (ReasonCode.NO_SIGNAL,) if decision is TradeDecision.NO_TRADE else (),
        None,
    )
    return create_analysis_request(
        evidence=evidence,
        code_version="code-v1",
        strategy_version="strategy-v1",
        config_version="config-v1",
        historical_versions=HISTORICAL,
        instrument_version="instrument-v1",
        prompt_version=prompt_version,
        projection_version="projection-v1",
        schema_version=SCHEMA_VERSION,
        limits=LIMITS,
    )


def response_json(
    decision: TradeDecision,
    regime: MarketRegime,
    confidence: str = "0.8",
) -> str:
    return json.dumps(
        {
            "decision": decision.value,
            "regime": regime.value,
            "confidence": confidence,
            "reasons": ["bounded evidence assessment"],
            "risk_flags": [],
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def benchmark_cases() -> tuple[AIBenchmarkCase, ...]:
    return tuple(
        create_benchmark_case(analysis_request(decision, regime), f"case-{decision.value}")
        for decision, regime in (
            (TradeDecision.LONG, MarketRegime.TREND_UP),
            (TradeDecision.SHORT, MarketRegime.TREND_DOWN),
            (TradeDecision.NO_TRADE, MarketRegime.SIDEWAY),
        )
    )


def benchmark_protocol(
    cases: tuple[AIBenchmarkCase, ...] | None = None,
    specs: tuple[AIProviderSpec, ...] | None = None,
) -> AIBenchmarkProtocol:
    case_values = cases or benchmark_cases()
    spec_values = specs or tuple(provider_spec(provider) for provider in AIProvider)
    return create_benchmark_protocol(
        protocol_version="ai-benchmark-protocol-v1",
        cases=case_values,
        provider_specs=spec_values,
        code_version="code-v1",
        strategy_version="strategy-v1",
        config_version="config-v1",
        historical_versions=HISTORICAL,
        instrument_version="instrument-v1",
        prompt_version=PROMPT_VERSION,
        projection_version="projection-v1",
        schema_version=SCHEMA_VERSION,
        parser_version="strict-json-parser-v1",
        metrics_version="ai-benchmark-metrics-v1",
    )


def changed_request(request: AIAnalysisRequest, **changes: object) -> AIAnalysisRequest:
    values = {
        "evidence": request.evidence,
        "code_version": request.code_version,
        "strategy_version": request.strategy_version,
        "config_version": request.config_version,
        "historical_versions": request.historical_versions,
        "instrument_version": request.instrument_version,
        "prompt_version": request.prompt_version,
        "projection_version": request.projection_version,
        "schema_version": request.schema_version,
        "limits": request.limits,
    }
    values.update(changes)
    return create_analysis_request(
        evidence=values["evidence"],
        code_version=values["code_version"],
        strategy_version=values["strategy_version"],
        config_version=values["config_version"],
        historical_versions=values["historical_versions"],
        instrument_version=values["instrument_version"],
        prompt_version=values["prompt_version"],
        projection_version=values["projection_version"],
        schema_version=values["schema_version"],
        limits=values["limits"],
    )
