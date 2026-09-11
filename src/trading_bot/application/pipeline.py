"""Offline deterministic market-to-decision orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from trading_bot.config.models import AppConfig
from trading_bot.domain.decision_models import DecisionRecord, TradeCandidate
from trading_bot.domain.enums import MarketRegime, ReasonCode, Timeframe, TradeDecision
from trading_bot.domain.identifiers import deterministic_id
from trading_bot.domain.market_models import (
    Candle,
    IndicatorSnapshot,
    LevelSet,
    MarketSnapshot,
    RangeContext,
    RegimeAssessment,
)
from trading_bot.domain.value_objects import CostRateEstimate, Quote, VersionSet
from trading_bot.levels.engine import build_level_set
from trading_bot.market_data.indicators import calculate_indicators
from trading_bot.market_data.validation import SnapshotBuildResult, build_market_snapshot
from trading_bot.regime.detector import detect_regime
from trading_bot.strategy.engine import StrategyOutcome, candle_confirmation, evaluate_strategy


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    indicators: IndicatorSnapshot
    levels: LevelSet | None
    regime: RegimeAssessment | None
    strategy: StrategyOutcome | None
    candidate: TradeCandidate | None
    decision: DecisionRecord


@dataclass(frozen=True, slots=True)
class SnapshotFailureEvaluation:
    build_result: SnapshotBuildResult
    decision: DecisionRecord


def evaluate_market(
    market: MarketSnapshot,
    config: AppConfig,
    versions: VersionSet,
    costs: CostRateEstimate,
    prior_regime: RegimeAssessment | None = None,
    prior_range: RangeContext | None = None,
) -> EvaluationResult:
    indicators = calculate_indicators(market, config.indicators, config.calculation, versions)
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
    bullish, bearish = candle_confirmation(market.candles_5m[-1], config.strategy)
    levels = build_level_set(
        market,
        indicators.values_by_timeframe[Timeframe.M15].atr,
        config.levels,
        config.calculation,
        versions.config_version,
        prior_range,
        bullish_confirmation=bullish,
        bearish_confirmation=bearish,
    )
    regime = detect_regime(
        market,
        indicators,
        levels,
        config.regime,
        config.calculation,
        versions.strategy_version,
        prior_regime,
    )
    strategy = evaluate_strategy(
        market,
        indicators,
        regime,
        levels,
        costs,
        config.strategy,
        config.calculation,
        config.risk.minimum_rr,
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


def replay_market_sequence(
    markets: tuple[MarketSnapshot, ...],
    config: AppConfig,
    versions: VersionSet,
    costs: CostRateEstimate,
    *,
    initial_regime: RegimeAssessment | None = None,
    initial_range: RangeContext | None = None,
) -> tuple[EvaluationResult, ...]:
    """Replay successive closed evaluations with all persistence inputs explicit."""
    prior_regime = initial_regime
    prior_range = initial_range
    results: list[EvaluationResult] = []
    for market in markets:
        result = evaluate_market(
            market,
            config,
            versions,
            costs,
            prior_regime=prior_regime,
            prior_range=prior_range,
        )
        results.append(result)
        if result.regime is not None:
            prior_regime = result.regime
        if result.levels is not None and result.levels.range_context is not None:
            prior_range = result.levels.range_context
    return tuple(results)


def evaluate_snapshot_inputs(
    symbol: str,
    as_of: datetime,
    created_at: datetime,
    candles_5m: tuple[Candle, ...],
    candles_15m: tuple[Candle, ...],
    candles_1h: tuple[Candle, ...],
    quote: Quote | None,
    config: AppConfig,
    versions: VersionSet,
    costs: CostRateEstimate,
    *,
    prior_regime: RegimeAssessment | None = None,
    prior_range: RangeContext | None = None,
) -> EvaluationResult | SnapshotFailureEvaluation:
    """Build a snapshot and translate expected build failures into canonical NO_TRADE."""
    build = build_market_snapshot(
        symbol,
        as_of,
        created_at,
        candles_5m,
        candles_15m,
        candles_1h,
        quote,
        versions,
        config.data,
    )
    if build.snapshot is not None:
        return evaluate_market(
            build.snapshot,
            config,
            versions,
            costs,
            prior_regime=prior_regime,
            prior_range=prior_range,
        )
    evaluation = deterministic_id(
        "evaluation", symbol, as_of, versions.strategy_version, versions.config_version
    )
    reasons = build.reason_codes or (ReasonCode.DATA_MISSING,)
    record = DecisionRecord(
        deterministic_id("decision-record", evaluation, TradeDecision.NO_TRADE, reasons),
        evaluation,
        symbol,
        created_at,
        as_of,
        None,
        MarketRegime.UNCERTAIN,
        TradeDecision.NO_TRADE,
        None,
        None,
        None,
        reasons,
        build.detail,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        versions,
    )
    return SnapshotFailureEvaluation(build, record)


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
