"""Offline deterministic market-to-decision orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from trading_bot.config.models import AppConfig
from trading_bot.domain.decision_models import DecisionRecord, TradeCandidate
from trading_bot.domain.enums import MarketRegime, ReasonCode, Timeframe, TradeDecision
from trading_bot.domain.identifiers import deterministic_id
from trading_bot.domain.market_models import (
    IndicatorSnapshot,
    LevelSet,
    MarketSnapshot,
    RegimeAssessment,
)
from trading_bot.domain.value_objects import CostRateEstimate, VersionSet
from trading_bot.levels.engine import build_level_set
from trading_bot.market_data.indicators import calculate_indicators
from trading_bot.regime.detector import detect_regime
from trading_bot.strategy.engine import StrategyOutcome, evaluate_strategy


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    indicators: IndicatorSnapshot
    levels: LevelSet | None
    regime: RegimeAssessment | None
    strategy: StrategyOutcome | None
    candidate: TradeCandidate | None
    decision: DecisionRecord


def evaluate_market(
    market: MarketSnapshot,
    config: AppConfig,
    versions: VersionSet,
    costs: CostRateEstimate,
    prior_regime: RegimeAssessment | None = None,
) -> EvaluationResult:
    indicators = calculate_indicators(market, config.indicators, versions)
    if not indicators.is_ready:
        reasons = indicators.reason_codes
        decision = _decision(
            market,
            versions,
            MarketRegime.UNCERTAIN,
            TradeDecision.NO_TRADE,
            reasons,
            indicators=indicators,
        )
        return EvaluationResult(indicators, None, None, None, None, decision)
    levels = build_level_set(
        market,
        indicators.values_by_timeframe[Timeframe.M15].atr,
        config.levels,
        versions.config_version,
    )
    regime = detect_regime(
        market, indicators, levels, config.regime, versions.strategy_version, prior_regime
    )
    strategy = evaluate_strategy(
        market, indicators, regime, levels, costs, config.strategy, config.risk.minimum_rr
    )
    decision = _decision(
        market,
        versions,
        regime.regime,
        strategy.decision,
        strategy.reason_codes,
        indicators=indicators,
        levels=levels,
        regime=regime,
        strategy=strategy,
    )
    return EvaluationResult(indicators, levels, regime, strategy, strategy.candidate, decision)


def _decision(
    market: MarketSnapshot,
    versions: VersionSet,
    regime_value: MarketRegime,
    result: TradeDecision,
    reasons: tuple[ReasonCode, ...],
    *,
    indicators: IndicatorSnapshot,
    levels: LevelSet | None = None,
    regime: RegimeAssessment | None = None,
    strategy: StrategyOutcome | None = None,
) -> DecisionRecord:
    candidate = strategy.candidate if strategy else None
    location = levels.range_context.current_location if levels and levels.range_context else None
    long_score = strategy.assessment.long_score if strategy else None
    short_score = strategy.assessment.short_score if strategy else None
    identifier = deterministic_id(
        "decision-record",
        market.evaluation_id,
        result,
        reasons,
        candidate and candidate.candidate_id,
    )
    return DecisionRecord(
        identifier,
        market.evaluation_id,
        market.symbol,
        market.created_at,
        market.as_of,
        market.candles_15m[-1].close,
        regime_value,
        result,
        location,
        long_score,
        short_score,
        reasons,
        None,
        market.snapshot_id,
        indicators.indicator_snapshot_id,
        regime.assessment_id if regime else None,
        strategy.assessment.signal_assessment_id if strategy else None,
        candidate.candidate_id if candidate else None,
        None,
        None,
        versions,
    )
