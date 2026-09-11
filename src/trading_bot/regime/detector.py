"""Pure multi-evidence regime scoring and confirmation persistence."""

from __future__ import annotations

from decimal import Decimal

from trading_bot.config.models import RegimeConfig
from trading_bot.domain.enums import MarketRegime, ReasonCode, StructureTrend, Timeframe
from trading_bot.domain.identifiers import deterministic_id
from trading_bot.domain.market_models import (
    IndicatorSnapshot,
    LevelSet,
    MarketSnapshot,
    RegimeAssessment,
)
from trading_bot.domain.primitives import ONE, ZERO
from trading_bot.domain.value_objects import RegimeEvidence


def clamp01(value: Decimal) -> Decimal:
    return min(ONE, max(ZERO, value))


def ramp_up(value: Decimal, start: Decimal, full: Decimal) -> Decimal:
    return clamp01((value - start) / (full - start))


def ramp_down(value: Decimal, full: Decimal, zero: Decimal) -> Decimal:
    return ONE - ramp_up(value, full, zero)


def _weighted(items: dict[str, Decimal], weights: object) -> Decimal:
    return sum((items[name] * weights[name] for name in items), ZERO)  # type: ignore[index]


def _last_confirmed(
    prior: RegimeAssessment | None, symbol: str, config_version: str
) -> MarketRegime | None:
    if prior is None or prior.symbol != symbol or prior.config_version != config_version:
        return None
    if prior.regime in {MarketRegime.TREND_UP, MarketRegime.TREND_DOWN, MarketRegime.SIDEWAY}:
        return prior.regime
    return prior.previous_confirmed_regime


def detect_regime(
    market: MarketSnapshot,
    indicators: IndicatorSnapshot,
    levels: LevelSet,
    config: RegimeConfig,
    strategy_version: str,
    prior: RegimeAssessment | None = None,
) -> RegimeAssessment:
    last_confirmed = _last_confirmed(prior, market.symbol, indicators.versions.config_version)
    scores = {
        regime: ZERO
        for regime in (
            MarketRegime.TREND_UP,
            MarketRegime.TREND_DOWN,
            MarketRegime.SIDEWAY,
            MarketRegime.HIGH_VOLATILITY,
        )
    }
    identifier_parts = (
        indicators.indicator_snapshot_id,
        levels.level_set_id,
        prior and prior.assessment_id,
    )
    if not indicators.is_ready:
        return RegimeAssessment(
            deterministic_id("regime-assessment", *identifier_parts),
            indicators.indicator_snapshot_id,
            market.symbol,
            MarketRegime.UNCERTAIN,
            None,
            last_confirmed,
            scores,
            ZERO,
            (),
            0,
            (ReasonCode.INDICATOR_NOT_READY,),
            market.as_of,
            indicators.versions.config_version,
            strategy_version,
        )
    atoms: dict[MarketRegime, dict[str, Decimal]] = {regime: {} for regime in scores}
    weighted_by_tf: dict[str, Decimal] = {}
    for name in (
        "ema_up",
        "ema_down",
        "slope_up",
        "slope_down",
        "adx",
        "price_up",
        "price_down",
        "compression",
        "flatness",
        "weakness",
        "atr_extreme",
        "bb_extreme",
    ):
        weighted_by_tf[name] = ZERO
    closes = {
        Timeframe.M15: market.candles_15m[-1].close,
        Timeframe.H1: market.candles_1h[-1].close,
    }
    for timeframe, weight in config.timeframe_weights.items():
        values = indicators.values_by_timeframe[timeframe]
        if values.atr <= ZERO:
            return RegimeAssessment(
                deterministic_id("regime-assessment", *identifier_parts),
                indicators.indicator_snapshot_id,
                market.symbol,
                MarketRegime.UNCERTAIN,
                None,
                last_confirmed,
                scores,
                ZERO,
                (),
                0,
                (ReasonCode.INDICATOR_INVALID,),
                market.as_of,
                indicators.versions.config_version,
                strategy_version,
            )
        measures = {
            "ema_up": ONE if values.ema20 > values.ema50 > values.ema200 else ZERO,
            "ema_down": ONE if values.ema20 < values.ema50 < values.ema200 else ZERO,
            "slope_up": min(
                ramp_up(
                    values.ema20_slope_atr, config.ema_minimum_slope_atr, config.ema_full_slope_atr
                ),
                ramp_up(
                    values.ema50_slope_atr, config.ema_minimum_slope_atr, config.ema_full_slope_atr
                ),
            ),
            "slope_down": min(
                ramp_up(
                    -values.ema20_slope_atr, config.ema_minimum_slope_atr, config.ema_full_slope_atr
                ),
                ramp_up(
                    -values.ema50_slope_atr, config.ema_minimum_slope_atr, config.ema_full_slope_atr
                ),
            ),
            "adx": ramp_up(values.adx, config.adx_trend_start, config.adx_trend_full),
            "price_up": ONE
            if closes[timeframe] >= values.ema20 - config.price_location_tolerance_atr * values.atr
            else ZERO,
            "price_down": ONE
            if closes[timeframe] <= values.ema20 + config.price_location_tolerance_atr * values.atr
            else ZERO,
            "compression": ramp_down(
                (
                    max(values.ema20, values.ema50, values.ema200)
                    - min(values.ema20, values.ema50, values.ema200)
                )
                / values.atr,
                ZERO,
                config.ema_maximum_sideway_dispersion_atr,
            ),
            "flatness": min(
                ramp_down(abs(values.ema20_slope_atr), ZERO, config.ema_maximum_sideway_slope_atr),
                ramp_down(abs(values.ema50_slope_atr), ZERO, config.ema_maximum_sideway_slope_atr),
            ),
            "weakness": ramp_down(values.adx, config.adx_sideway_full, config.adx_sideway_zero),
            "atr_extreme": ramp_up(
                values.atr_percentile, config.atr_percentile_start, config.atr_percentile_full
            ),
            "bb_extreme": ramp_up(
                values.bb_width_percentile, config.bb_percentile_start, config.bb_percentile_full
            ),
        }
        for name, value in measures.items():
            weighted_by_tf[name] += value * weight
    trend = levels.market_structure.trend
    atoms[MarketRegime.TREND_UP] = {
        "ema": weighted_by_tf["ema_up"],
        "slope": weighted_by_tf["slope_up"],
        "adx": weighted_by_tf["adx"],
        "structure": ONE if trend is StructureTrend.BULLISH else ZERO,
        "price_location": weighted_by_tf["price_up"],
    }
    atoms[MarketRegime.TREND_DOWN] = {
        "ema": weighted_by_tf["ema_down"],
        "slope": weighted_by_tf["slope_down"],
        "adx": weighted_by_tf["adx"],
        "structure": ONE if trend is StructureTrend.BEARISH else ZERO,
        "price_location": weighted_by_tf["price_down"],
    }
    valid_range = levels.range_context is not None and not levels.range_context.reason_codes
    atoms[MarketRegime.SIDEWAY] = {
        "range": ONE if valid_range else ZERO,
        "ema_compression": weighted_by_tf["compression"],
        "slope_flatness": weighted_by_tf["flatness"],
        "adx_weakness": weighted_by_tf["weakness"],
        "bounded_structure": ONE if trend is StructureTrend.MIXED else ZERO,
    }
    trigger = market.candles_15m[-1]
    previous_close = market.candles_15m[-2].close
    true_range = max(
        trigger.high - trigger.low,
        abs(trigger.high - previous_close),
        abs(trigger.low - previous_close),
    )
    m15_atr = indicators.values_by_timeframe[Timeframe.M15].atr
    atoms[MarketRegime.HIGH_VOLATILITY] = {
        "atr_percentile": weighted_by_tf["atr_extreme"],
        "bb_width_percentile": weighted_by_tf["bb_extreme"],
        "true_range_shock": ramp_up(
            true_range / m15_atr,
            config.true_range_atr_start,
            config.true_range_atr_full,
        ),
    }
    scores = {
        MarketRegime.TREND_UP: _weighted(atoms[MarketRegime.TREND_UP], config.trend_weights),
        MarketRegime.TREND_DOWN: _weighted(atoms[MarketRegime.TREND_DOWN], config.trend_weights),
        MarketRegime.SIDEWAY: _weighted(atoms[MarketRegime.SIDEWAY], config.sideway_weights),
        MarketRegime.HIGH_VOLATILITY: _weighted(
            atoms[MarketRegime.HIGH_VOLATILITY], config.high_volatility_weights
        ),
    }
    thresholds = {
        MarketRegime.TREND_UP: config.trend_candidate_threshold,
        MarketRegime.TREND_DOWN: config.trend_candidate_threshold,
        MarketRegime.SIDEWAY: config.sideway_candidate_threshold,
        MarketRegime.HIGH_VOLATILITY: config.high_volatility_candidate_threshold,
    }

    def qualified(candidate: MarketRegime) -> bool:
        strong = sum(
            strength >= config.minimum_evidence_strength for strength in atoms[candidate].values()
        )
        return (
            scores[candidate] >= thresholds[candidate]
            and scores[candidate] >= config.minimum_confidence
            and strong >= config.minimum_evidence_count
        )

    candidate: MarketRegime | None = None
    reason_codes: tuple[ReasonCode, ...] = ()
    output = MarketRegime.UNCERTAIN
    count = 0
    confidence = ZERO
    if qualified(MarketRegime.HIGH_VOLATILITY):
        candidate = output = MarketRegime.HIGH_VOLATILITY
        count = 1
        confidence = scores[candidate]
    elif (
        min(scores[MarketRegime.TREND_UP], scores[MarketRegime.TREND_DOWN])
        >= config.conflict_tolerance
    ):
        reason_codes = (ReasonCode.REGIME_UNCERTAIN,)
    else:
        eligible = [
            item
            for item in (MarketRegime.TREND_UP, MarketRegime.TREND_DOWN, MarketRegime.SIDEWAY)
            if qualified(item)
        ]
        directionals = {MarketRegime.TREND_UP, MarketRegime.TREND_DOWN} & set(eligible)
        if len(directionals) > 1:
            reason_codes = (ReasonCode.REGIME_UNCERTAIN,)
        elif len(eligible) == 1:
            candidate = eligible[0]
        elif len(eligible) == 2:
            ordered = sorted(eligible, key=scores.__getitem__, reverse=True)
            if scores[ordered[0]] - scores[ordered[1]] >= config.minimum_candidate_margin:
                candidate = ordered[0]
            else:
                reason_codes = (ReasonCode.REGIME_UNCERTAIN,)
        else:
            reason_codes = (ReasonCode.REGIME_UNCERTAIN,)
        if candidate is not None:
            compatible = (
                prior is not None
                and prior.symbol == market.symbol
                and prior.config_version == indicators.versions.config_version
                and prior.candidate_regime is candidate
            )
            count = min(
                config.required_confirmations,
                (prior.confirmation_count + 1) if compatible and prior is not None else 1,
            )
            if count >= config.required_confirmations:
                output = candidate
                confidence = scores[candidate]
            else:
                reason_codes = (ReasonCode.REGIME_UNCERTAIN,)
    evidence: tuple[RegimeEvidence, ...] = ()
    if candidate is not None:
        evidence = tuple(
            RegimeEvidence(
                name,
                candidate,
                strength,
                strength,
                "ratio",
                strategy_version,
                (indicators.indicator_snapshot_id, levels.level_set_id),
            )
            for name, strength in atoms[candidate].items()
        )
    assessment_id = deterministic_id(
        "regime-assessment",
        *identifier_parts,
        scores,
        candidate,
        output,
        count,
    )
    return RegimeAssessment(
        assessment_id,
        indicators.indicator_snapshot_id,
        market.symbol,
        output,
        candidate,
        last_confirmed,
        scores,
        confidence,
        evidence,
        count,
        reason_codes,
        market.as_of,
        indicators.versions.config_version,
        strategy_version,
    )
