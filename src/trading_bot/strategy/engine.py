"""Pure signal scoring and quantity-free TradeCandidate construction."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from trading_bot.config.models import StrategyConfig
from trading_bot.domain.decision_models import SignalAssessment, SignalComponent, TradeCandidate
from trading_bot.domain.enums import (
    BreakoutDirection,
    BreakoutState,
    MarketRegime,
    RangeLocation,
    ReasonCode,
    SetupType,
    SignalComponentName,
    StructurePointKind,
    StructureTrend,
    Timeframe,
    TradeDecision,
    TradeSide,
)
from trading_bot.domain.identifiers import candidate_id, deterministic_id
from trading_bot.domain.market_models import (
    Candle,
    IndicatorSnapshot,
    Level,
    LevelSet,
    MarketSnapshot,
    RegimeAssessment,
)
from trading_bot.domain.primitives import ONE, ZERO
from trading_bot.domain.value_objects import CostRateEstimate, GateResult, SignalEvidence, Target
from trading_bot.regime.detector import ramp_down, ramp_up


@dataclass(frozen=True, slots=True)
class StrategyOutcome:
    assessment: SignalAssessment
    decision: TradeDecision
    candidate: TradeCandidate | None
    reason_codes: tuple[ReasonCode, ...]


def candle_confirmation(candle: Candle, config: StrategyConfig) -> tuple[bool, bool]:
    candle_range = candle.high - candle.low
    if candle_range <= ZERO:
        return False, False
    body = abs(candle.close - candle.open) / candle_range
    location = (candle.close - candle.low) / candle_range
    lower_wick = (min(candle.open, candle.close) - candle.low) / candle_range
    upper_wick = (candle.high - max(candle.open, candle.close)) / candle_range
    rules = config.confirmation
    bullish = (
        candle.close > candle.open
        and location >= rules.long_close_location_min
        and (
            body >= rules.minimum_body_fraction
            or lower_wick >= rules.minimum_rejection_wick_fraction
        )
    )
    bearish = (
        candle.close < candle.open
        and location <= rules.short_close_location_max
        and (
            body >= rules.minimum_body_fraction
            or upper_wick >= rules.minimum_rejection_wick_fraction
        )
    )
    return bullish, bearish


def _select_setup(
    regime: RegimeAssessment,
    levels: LevelSet,
    close: Decimal,
    ema20: Decimal,
    atr: Decimal,
    config: StrategyConfig,
) -> tuple[SetupType, TradeSide] | None:
    if regime.regime is MarketRegime.TREND_UP:
        return (
            (SetupType.TREND_PULLBACK, TradeSide.LONG)
            if abs(close - ema20) / atr <= config.trend_pullback_tolerance_atr
            else None
        )
    if regime.regime is MarketRegime.TREND_DOWN:
        return (
            (SetupType.TREND_PULLBACK, TradeSide.SHORT)
            if abs(close - ema20) / atr <= config.trend_pullback_tolerance_atr
            else None
        )
    context = levels.range_context
    if regime.regime is not MarketRegime.SIDEWAY or context is None:
        return None
    if context.breakout_state is BreakoutState.RETEST_VALIDATED:
        side = (
            TradeSide.LONG
            if context.breakout_direction is BreakoutDirection.UP
            else TradeSide.SHORT
        )
        return SetupType.BREAKOUT_RETEST, side
    if context.current_location is RangeLocation.NEAR_SUPPORT:
        return SetupType.SIDEWAY_MEAN_REVERSION, TradeSide.LONG
    if context.current_location is RangeLocation.NEAR_RESISTANCE:
        return SetupType.SIDEWAY_MEAN_REVERSION, TradeSide.SHORT
    return None


def _selected_level(levels: LevelSet, setup: SetupType, side: TradeSide) -> Level | None:
    target_id: str | None
    if setup is SetupType.BREAKOUT_RETEST:
        if levels.range_context is None:
            return None
        target_id = (
            levels.range_context.resistance_level_id
            if side is TradeSide.LONG
            else levels.range_context.support_level_id
        )
    elif side is TradeSide.LONG:
        target_id = (
            levels.range_context.support_level_id if levels.range_context is not None else None
        )
    else:
        target_id = (
            levels.range_context.resistance_level_id if levels.range_context is not None else None
        )
    choices = levels.supports + levels.resistances + levels.swings
    if target_id is not None:
        return next((level for level in choices if level.level_id == target_id), None)
    return (
        levels.supports[-1]
        if side is TradeSide.LONG and levels.supports
        else levels.resistances[0]
        if side is TradeSide.SHORT and levels.resistances
        else None
    )


def _evidence(
    name: str,
    long: Decimal,
    short: Decimal,
    observed_long: Decimal,
    observed_short: Decimal,
    unit: str,
    sources: tuple[str, ...],
) -> SignalEvidence:
    return SignalEvidence(name, long, short, observed_long, observed_short, unit, sources)


def _components(
    market: MarketSnapshot,
    indicators: IndicatorSnapshot,
    regime: RegimeAssessment,
    levels: LevelSet,
    selected: Level | None,
    setup: SetupType,
    side: TradeSide,
    config: StrategyConfig,
) -> tuple[SignalComponent, ...]:
    values = indicators.values_by_timeframe[Timeframe.M15]
    close = market.candles_15m[-1].close
    bullish, bearish = candle_confirmation(market.candles_5m[-1], config)
    trend_aligned_long = regime.regime is MarketRegime.TREND_UP and side is TradeSide.LONG
    trend_aligned_short = regime.regime is MarketRegime.TREND_DOWN and side is TradeSide.SHORT
    distance = (
        ZERO
        if selected is not None and selected.zone_lower <= close <= selected.zone_upper
        else min(abs(close - selected.zone_lower), abs(close - selected.zone_upper)) / values.atr
        if selected is not None
        else config.level_zero_strength_distance_atr
    )
    band = config.momentum_rsi_bands[setup]
    sources = (
        market.candles_15m[-1].candle_id,
        indicators.indicator_snapshot_id,
        regime.assessment_id,
        levels.level_set_id,
    )
    raw: dict[SignalComponentName, tuple[SignalEvidence, ...]] = {
        SignalComponentName.TREND: (
            _evidence(
                "regime_alignment",
                regime.candidate_scores[MarketRegime.TREND_UP] if trend_aligned_long else ZERO,
                regime.candidate_scores[MarketRegime.TREND_DOWN] if trend_aligned_short else ZERO,
                regime.candidate_scores[MarketRegime.TREND_UP],
                regime.candidate_scores[MarketRegime.TREND_DOWN],
                "ratio",
                sources,
            ),
            _evidence(
                "ema_alignment",
                ONE if trend_aligned_long and values.ema20 > values.ema50 > values.ema200 else ZERO,
                ONE
                if trend_aligned_short and values.ema20 < values.ema50 < values.ema200
                else ZERO,
                ONE if values.ema20 > values.ema50 > values.ema200 else ZERO,
                ONE if values.ema20 < values.ema50 < values.ema200 else ZERO,
                "binary",
                sources,
            ),
            _evidence(
                "pullback",
                ramp_down(
                    abs(close - values.ema20) / values.atr,
                    ZERO,
                    config.trend_pullback_tolerance_atr,
                )
                if trend_aligned_long
                else ZERO,
                ramp_down(
                    abs(close - values.ema20) / values.atr,
                    ZERO,
                    config.trend_pullback_tolerance_atr,
                )
                if trend_aligned_short
                else ZERO,
                abs(close - values.ema20) / values.atr,
                abs(close - values.ema20) / values.atr,
                "atr_multiple",
                sources,
            ),
        ),
        SignalComponentName.MOMENTUM: (
            _evidence(
                "rsi",
                ONE if band.long_min <= values.rsi <= band.long_max else ZERO,
                ONE if band.short_min <= values.rsi <= band.short_max else ZERO,
                values.rsi,
                values.rsi,
                "rsi_point",
                sources,
            ),
            _evidence(
                "rsi_slope",
                ramp_up(values.rsi_slope, ZERO, config.momentum_rsi_slope_full),
                ramp_up(-values.rsi_slope, ZERO, config.momentum_rsi_slope_full),
                values.rsi_slope,
                -values.rsi_slope,
                "rsi_point",
                sources,
            ),
        ),
        SignalComponentName.STRUCTURE: (
            _evidence(
                "market_structure",
                ONE if levels.market_structure.trend is StructureTrend.BULLISH else ZERO,
                ONE if levels.market_structure.trend is StructureTrend.BEARISH else ZERO,
                ONE if levels.market_structure.trend is StructureTrend.BULLISH else ZERO,
                ONE if levels.market_structure.trend is StructureTrend.BEARISH else ZERO,
                "binary",
                sources,
            ),
        ),
        SignalComponentName.LEVEL: (
            _evidence(
                "proximity",
                ramp_down(
                    distance,
                    config.level_full_strength_distance_atr,
                    config.level_zero_strength_distance_atr,
                )
                if selected is not None and side is TradeSide.LONG
                else ZERO,
                ramp_down(
                    distance,
                    config.level_full_strength_distance_atr,
                    config.level_zero_strength_distance_atr,
                )
                if selected is not None and side is TradeSide.SHORT
                else ZERO,
                distance,
                distance,
                "atr_multiple",
                sources,
            ),
        ),
        SignalComponentName.VOLUME: (
            _evidence(
                "volume_ratio",
                ramp_up(values.volume_ratio, config.volume_ratio_start, config.volume_ratio_full)
                if bullish
                else ZERO,
                ramp_up(values.volume_ratio, config.volume_ratio_start, config.volume_ratio_full)
                if bearish
                else ZERO,
                values.volume_ratio,
                values.volume_ratio,
                "ratio",
                sources,
            ),
        ),
        SignalComponentName.CONFIRMATION: (
            _evidence(
                "closed_candle",
                ONE if bullish else ZERO,
                ONE if bearish else ZERO,
                ONE if bullish else ZERO,
                ONE if bearish else ZERO,
                "binary",
                sources,
            ),
        ),
    }
    if regime.regime is MarketRegime.SIDEWAY:
        raw[SignalComponentName.TREND] = tuple(
            _evidence(
                item.name,
                ZERO,
                ZERO,
                item.long_observed_value,
                item.short_observed_value,
                item.unit,
                item.source_ids,
            )
            for item in raw[SignalComponentName.TREND]
        )
    components = []
    for name in SignalComponentName:
        evidence = raw[name]
        weights = config.component_evidence_weights[name]
        maximum = config.component_max_points[name]
        long_points = (
            maximum * sum((item.long_strength * weights[item.name] for item in evidence), ZERO)
            if maximum
            else ZERO
        )
        short_points = (
            maximum * sum((item.short_strength * weights[item.name] for item in evidence), ZERO)
            if maximum
            else ZERO
        )
        components.append(
            SignalComponent(
                name,
                long_points,
                short_points,
                maximum,
                evidence,
                (),
                indicators.versions.config_version,
            )
        )
    return tuple(components)


def evaluate_strategy(
    market: MarketSnapshot,
    indicators: IndicatorSnapshot,
    regime: RegimeAssessment,
    levels: LevelSet,
    costs: CostRateEstimate,
    config: StrategyConfig,
    minimum_rr: Decimal,
) -> StrategyOutcome:
    m15 = indicators.values_by_timeframe.get(Timeframe.M15)
    setup_side = (
        None
        if m15 is None
        else _select_setup(regime, levels, market.candles_15m[-1].close, m15.ema20, m15.atr, config)
    )
    reasons: list[ReasonCode] = []
    if not indicators.is_ready:
        reasons.append(ReasonCode.INDICATOR_NOT_READY)
    elif regime.regime is MarketRegime.UNCERTAIN:
        reasons.append(ReasonCode.REGIME_UNCERTAIN)
    elif regime.regime is MarketRegime.HIGH_VOLATILITY:
        reasons.append(ReasonCode.HIGH_VOLATILITY_BLOCKED)
    elif setup_side is None:
        reasons.append(
            ReasonCode.SIDEWAY_MIDDLE_RANGE
            if regime.regime is MarketRegime.SIDEWAY
            else ReasonCode.NO_SIGNAL
        )
    elif setup_side[0] not in config.allowed_setups:
        reasons.append(ReasonCode.SETUP_DISABLED)
    setup = setup_side[0] if setup_side else SetupType.TREND_PULLBACK
    side = setup_side[1] if setup_side else TradeSide.LONG
    selected = _selected_level(levels, setup, side) if setup_side else None
    components = (
        _components(market, indicators, regime, levels, selected, setup, side, config)
        if indicators.is_ready
        else _zero_components(config, indicators.versions.config_version)
    )
    long_score = sum((component.long_points for component in components), ZERO)
    short_score = sum((component.short_points for component in components), ZERO)
    assessment_id = deterministic_id(
        "signal-assessment", market.evaluation_id, regime.assessment_id, components
    )
    gates = (
        GateResult(
            "setup",
            setup_side is not None and not reasons,
            reasons[0] if reasons else None,
            None,
            None,
            None,
        ),
    )
    assessment = SignalAssessment(
        assessment_id,
        market.evaluation_id,
        long_score,
        short_score,
        components,
        gates,
        tuple(reasons),
        market.as_of,
        indicators.versions,
    )
    if reasons or setup_side is None:
        return StrategyOutcome(assessment, TradeDecision.NO_TRADE, None, tuple(reasons))
    long_count = sum(component.long_points > ZERO for component in components)
    short_count = sum(component.short_points > ZERO for component in components)
    allows_long, allows_short = side is TradeSide.LONG, side is TradeSide.SHORT
    long_ok = (
        allows_long
        and long_count >= config.minimum_nonzero_components
        and long_score >= config.long_threshold
        and long_score - short_score >= config.minimum_score_difference
    )
    short_ok = (
        allows_short
        and short_count >= config.minimum_nonzero_components
        and short_score >= config.short_threshold
        and short_score - long_score >= config.minimum_score_difference
    )
    if long_ok and short_ok:
        reasons.append(ReasonCode.AMBIGUOUS_SIGNAL)
    elif not long_ok and not short_ok:
        if (long_count if allows_long else short_count) < config.minimum_nonzero_components:
            reasons.append(ReasonCode.CONFLUENCE_TOO_LOW)
        elif (long_score if allows_long else short_score) < (
            config.long_threshold if allows_long else config.short_threshold
        ):
            reasons.append(ReasonCode.SCORE_TOO_LOW)
        else:
            reasons.append(ReasonCode.SCORE_DIFFERENCE_TOO_SMALL)
    if reasons:
        assessment = replace(assessment, reason_codes=tuple(reasons))
        return StrategyOutcome(assessment, TradeDecision.NO_TRADE, None, tuple(reasons))
    candidate, candidate_reasons = _build_candidate(
        market,
        indicators,
        regime,
        levels,
        assessment,
        selected,
        setup,
        side,
        costs,
        config,
        minimum_rr,
    )
    decision = TradeDecision.LONG if side is TradeSide.LONG else TradeDecision.SHORT
    if candidate is None:
        decision = TradeDecision.NO_TRADE
        assessment = replace(assessment, reason_codes=candidate_reasons)
    return StrategyOutcome(assessment, decision, candidate, candidate_reasons)


def _zero_components(config: StrategyConfig, config_version: str) -> tuple[SignalComponent, ...]:
    return tuple(
        SignalComponent(name, ZERO, ZERO, config.component_max_points[name], (), (), config_version)
        for name in SignalComponentName
    )


def _build_candidate(
    market: MarketSnapshot,
    indicators: IndicatorSnapshot,
    regime: RegimeAssessment,
    levels: LevelSet,
    assessment: SignalAssessment,
    selected: Level | None,
    setup: SetupType,
    side: TradeSide,
    costs: CostRateEstimate,
    config: StrategyConfig,
    minimum_rr: Decimal,
) -> tuple[TradeCandidate | None, tuple[ReasonCode, ...]]:
    entry = market.candles_15m[-1].close
    atr = indicators.values_by_timeframe[Timeframe.M15].atr
    if setup is SetupType.TREND_PULLBACK:
        wanted = (
            {StructurePointKind.SWING_LOW, StructurePointKind.HL, StructurePointKind.LL}
            if side is TradeSide.LONG
            else {StructurePointKind.SWING_HIGH, StructurePointKind.HH, StructurePointKind.LH}
        )
        points = [
            point
            for point in levels.market_structure.points
            if point.kind in wanted
            and (point.price < entry if side is TradeSide.LONG else point.price > entry)
        ]
        anchor_point = (
            sorted(points, key=lambda item: (-item.confirmed_at.timestamp(), item.candle_id))[0]
            if points
            else None
        )
        anchor, invalidation_id = (
            (anchor_point.price, anchor_point.candle_id) if anchor_point else (None, "")
        )
    else:
        anchor, invalidation_id = (
            (selected.price if selected else None),
            (selected.level_id if selected else ""),
        )
        if selected is not None:
            anchor = selected.zone_lower if side is TradeSide.LONG else selected.zone_upper
    if anchor is None:
        return None, (ReasonCode.INVALID_STOP,)
    stop = (
        anchor - config.stop_atr_buffer * atr
        if side is TradeSide.LONG
        else anchor + config.stop_atr_buffer * atr
    )
    if side is TradeSide.LONG:
        options = sorted(
            (level for level in levels.resistances if level.zone_lower > entry),
            key=lambda item: (item.zone_lower, item.level_id),
        )
        target_price = options[0].zone_lower if options else None
    else:
        options = sorted(
            (level for level in levels.supports if level.zone_upper < entry),
            key=lambda item: (-item.zone_upper, item.level_id),
        )
        target_price = options[0].zone_upper if options else None
    if target_price is None:
        return None, (ReasonCode.TARGET_INVALID,)
    loss = abs(entry - stop) / entry
    reward = abs(target_price - entry) / entry
    planned_loss = (
        loss
        + costs.entry_fee_rate
        + costs.stop_exit_fee_rate
        + costs.entry_slippage_rate
        + costs.stop_slippage_rate
        + costs.funding_debit_rate
    )
    planned_reward = (
        reward
        - costs.entry_fee_rate
        - costs.target_exit_fee_rate
        - costs.entry_slippage_rate
        - costs.target_slippage_rate
        - costs.funding_debit_rate
    )
    if loss <= ZERO or planned_loss <= ZERO or planned_reward <= ZERO:
        return None, (ReasonCode.RR_TOO_LOW,)
    before, after = reward / loss, planned_reward / planned_loss
    if after < minimum_rr:
        return None, (ReasonCode.RR_TOO_LOW,)
    target = Target("primary", target_price, ONE)
    chosen_score = assessment.long_score if side is TradeSide.LONG else assessment.short_score
    opposite = assessment.short_score if side is TradeSide.LONG else assessment.long_score
    identifier = candidate_id(
        market.evaluation_id, side, setup, entry, stop, (target,), assessment.signal_assessment_id
    )
    candidate = TradeCandidate(
        identifier,
        market.evaluation_id,
        market.symbol,
        side,
        regime.regime,
        chosen_score,
        opposite,
        entry,
        stop,
        atr,
        (target,),
        before,
        after,
        costs,
        setup,
        config.entry_model,
        config.target_model,
        assessment.signal_assessment_id,
        regime.assessment_id,
        levels.range_context.range_id if levels.range_context else None,
        invalidation_id,
        (options[0].level_id,),
        (),
        market.as_of,
        indicators.versions,
    )
    return candidate, ()
