"""Past-only projection from canonical PHASE 3 artifacts."""

from __future__ import annotations

from trading_bot.ai.models import AICandleEvidence, AIMarketEvidence, AIObservation
from trading_bot.domain.decision_models import DecisionRecord, SignalAssessment
from trading_bot.domain.enums import Timeframe
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.market_models import (
    IndicatorSnapshot,
    LevelSet,
    MarketSnapshot,
    RegimeAssessment,
)


def project_market_evidence(
    *,
    market: MarketSnapshot,
    indicators: IndicatorSnapshot,
    regime: RegimeAssessment,
    levels: LevelSet,
    signals: SignalAssessment,
    decision: DecisionRecord,
    candles_per_timeframe: int,
) -> AIMarketEvidence:
    """Build a bounded projection without outcome or post-as-of fields."""
    identities = (
        market.symbol == indicators.symbol == regime.symbol == levels.symbol == decision.symbol,
        market.as_of == indicators.as_of == regime.as_of == levels.as_of == signals.as_of,
        market.as_of == decision.as_of,
        decision.evaluation_id == market.evaluation_id == signals.evaluation_id,
    )
    if not all(identities):
        raise DomainValidationError("AI evidence source identities do not match")
    if candles_per_timeframe <= 0:
        raise DomainValidationError("candles_per_timeframe must be positive")
    source_series = (
        (Timeframe.M5, market.candles_5m),
        (Timeframe.M15, market.candles_15m),
        (Timeframe.H1, market.candles_1h),
    )
    candles = tuple(
        AICandleEvidence(
            candle.candle_id,
            timeframe,
            candle.close_time,
            candle.open,
            candle.high,
            candle.low,
            candle.close,
            candle.volume,
        )
        for timeframe, series in source_series
        for candle in series[-candles_per_timeframe:]
    )
    observations: list[AIObservation] = []
    for timeframe, values in indicators.values_by_timeframe.items():
        for name in ("ema20", "ema50", "ema200", "rsi", "atr", "adx", "volume_ratio"):
            observations.append(
                AIObservation(
                    "INDICATOR",
                    f"{timeframe.value}.{name}",
                    getattr(values, name),
                    indicators.as_of,
                    indicators.indicator_snapshot_id,
                )
            )
    observations.extend(
        (
            AIObservation(
                "REGIME",
                "reference_regime_confidence",
                regime.confidence,
                regime.as_of,
                regime.assessment_id,
            ),
            AIObservation(
                "SIGNAL",
                "long_score",
                signals.long_score,
                signals.as_of,
                signals.signal_assessment_id,
            ),
            AIObservation(
                "SIGNAL",
                "short_score",
                signals.short_score,
                signals.as_of,
                signals.signal_assessment_id,
            ),
        )
    )
    if levels.range_context is not None:
        context = levels.range_context
        observations.extend(
            (
                AIObservation("RANGE", "support", context.support, context.as_of, context.range_id),
                AIObservation(
                    "RANGE", "resistance", context.resistance, context.as_of, context.range_id
                ),
                AIObservation(
                    "RANGE",
                    "location",
                    context.current_location.value,
                    context.as_of,
                    context.range_id,
                ),
            )
        )
    observations.sort(key=lambda item: (item.category, item.name, item.source_id))
    return AIMarketEvidence(
        market.symbol,
        market.as_of,
        candles,
        tuple(observations),
        decision.decision,
        decision.regime,
        decision.reason_codes,
        None,
    )
