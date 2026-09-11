from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from trading_bot.domain.enums import (
    BreakoutDirection,
    BreakoutState,
    LevelKind,
    LevelMethod,
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
from trading_bot.domain.market_models import (
    IndicatorSnapshot,
    Level,
    LevelSet,
    RangeContext,
    RegimeAssessment,
)
from trading_bot.domain.value_objects import (
    CostRateEstimate,
    IndicatorValues,
    MarketStructure,
    RegimeEvidence,
    StructurePoint,
)
from trading_bot.strategy.engine import evaluate_strategy

D = Decimal
LEVEL_WIDTH = D("0.3")
ZERO = D("0")


def _costs() -> CostRateEstimate:
    return CostRateEstimate(*(D("0.0001") for _ in range(7)), model_version="cost-v1")


def _level(identifier, kind, price, market, *, width=LEVEL_WIDTH) -> Level:
    return Level(
        identifier,
        market.symbol,
        kind,
        price,
        price - width,
        price + width,
        D("1"),
        LevelMethod.SWING_CLUSTER,
        market.as_of - timedelta(hours=2),
        market.as_of - timedelta(hours=1),
        market.as_of,
        market.as_of,
        4,
        (f"{identifier}-source",),
        None,
    )


def _inputs(
    market_snapshot,
    versions,
    *,
    side=TradeSide.LONG,
    regime_value=MarketRegime.SIDEWAY,
    location=None,
    breakout_state=BreakoutState.NONE,
    breakout_direction=None,
    confirmation=True,
    momentum=True,
    volume=True,
):
    entry = D("160.1") if side is TradeSide.LONG else D("169.9")
    if breakout_state is BreakoutState.RETEST_VALIDATED:
        entry = D("170.1") if breakout_direction is BreakoutDirection.UP else D("159.9")
    trigger = replace(
        market_snapshot.candles_15m[-1],
        open=entry,
        high=entry + D("1"),
        low=entry - D("1"),
        close=entry,
    )
    if side is TradeSide.LONG:
        child = replace(
            market_snapshot.candles_5m[-1],
            open=D("159.8") if confirmation else D("160.3"),
            high=D("160.4"),
            low=D("159.5"),
            close=D("160.2") if confirmation else D("159.7"),
        )
    else:
        child = replace(
            market_snapshot.candles_5m[-1],
            open=D("170.2") if confirmation else D("169.6"),
            high=D("170.5"),
            low=D("169.5"),
            close=D("169.7") if confirmation else D("170.3"),
        )
    market = replace(
        market_snapshot,
        candles_15m=(*market_snapshot.candles_15m[:-1], trigger),
        candles_5m=(*market_snapshot.candles_5m[:-1], child),
    )
    trend_up = side is TradeSide.LONG
    rsi = D("40") if side is TradeSide.LONG else D("60")
    if breakout_state is BreakoutState.RETEST_VALIDATED:
        rsi = D("60") if side is TradeSide.LONG else D("40")
    if not momentum:
        rsi = D("50")
    slope = D("5") if side is TradeSide.LONG else D("-5")
    if not momentum:
        slope = ZERO
    indicator_values = IndicatorValues(
        D("159.1") if trend_up else D("170.9"),
        D("158") if trend_up else D("172"),
        D("157") if trend_up else D("173"),
        D("0.3") if trend_up else D("-0.3"),
        D("0.3") if trend_up else D("-0.3"),
        D("0.2") if trend_up else D("-0.2"),
        rsi,
        slope,
        D("2"),
        D("0.01"),
        D("50"),
        D("30"),
        D("175"),
        D("165"),
        D("155"),
        D("0.1"),
        D("50"),
        D("10"),
        D("1.5") if volume else D("1"),
    )
    indicators = IndicatorSnapshot(
        "indicators",
        market.snapshot_id,
        market.symbol,
        market.as_of,
        {timeframe: indicator_values for timeframe in Timeframe},
        True,
        (),
        (),
        versions,
    )
    support = _level("support", LevelKind.SUPPORT, D("160"), market)
    resistance = _level("resistance", LevelKind.RESISTANCE, D("170"), market)
    outer_resistance = _level("outer-resistance", LevelKind.RESISTANCE, D("180"), market)
    outer_support = _level("outer-support", LevelKind.SUPPORT, D("150"), market)
    structure_trend = StructureTrend.BULLISH if side is TradeSide.LONG else StructureTrend.BEARISH
    point_kind = (
        StructurePointKind.SWING_LOW if side is TradeSide.LONG else StructurePointKind.SWING_HIGH
    )
    point_price = D("158") if side is TradeSide.LONG else D("172")
    point = StructurePoint(
        point_kind,
        point_price,
        market.as_of - timedelta(minutes=30),
        "swing-anchor",
        market.as_of - timedelta(minutes=15),
    )
    structure = MarketStructure(structure_trend, (point,), market.as_of, ())
    context = None
    if regime_value is MarketRegime.SIDEWAY:
        actual_location = location or (
            RangeLocation.NEAR_SUPPORT if side is TradeSide.LONG else RangeLocation.NEAR_RESISTANCE
        )
        position = (entry - D("160")) / D("10")
        context = RangeContext(
            "range",
            market.symbol,
            support.level_id,
            resistance.level_id,
            D("160"),
            D("170"),
            entry,
            D("10"),
            D("165"),
            D("5"),
            position,
            market.as_of - timedelta(hours=2),
            market.as_of,
            market.as_of,
            8,
            4,
            4,
            2 if breakout_state is BreakoutState.WAIT_RETEST else 0,
            actual_location,
            breakout_state,
            breakout_direction,
            market.as_of - timedelta(hours=1) if breakout_direction else None,
            market.as_of if breakout_direction else None,
            market.as_of + timedelta(hours=1) if breakout_direction else None,
            (),
            versions.config_version,
            versions.data_version,
        )
    levels = LevelSet(
        "levels",
        market.snapshot_id,
        market.symbol,
        (outer_support, support),
        (resistance, outer_resistance),
        (support, resistance, outer_support, outer_resistance),
        context,
        structure,
        market.as_of,
        versions.config_version,
        versions.data_version,
    )
    scores = {
        MarketRegime.TREND_UP: D("0.9") if regime_value is MarketRegime.TREND_UP else ZERO,
        MarketRegime.TREND_DOWN: D("0.9") if regime_value is MarketRegime.TREND_DOWN else ZERO,
        MarketRegime.SIDEWAY: D("0.9") if regime_value is MarketRegime.SIDEWAY else ZERO,
        MarketRegime.HIGH_VOLATILITY: ZERO,
    }
    evidence = RegimeEvidence(
        "fixture",
        regime_value,
        D("0.9"),
        D("0.9"),
        "ratio",
        versions.strategy_version,
        ("indicators", "levels"),
    )
    regime = RegimeAssessment(
        "regime",
        indicators.indicator_snapshot_id,
        market.symbol,
        regime_value,
        regime_value,
        None,
        scores,
        D("0.9"),
        (evidence,),
        2,
        (),
        market.as_of,
        versions.config_version,
        versions.strategy_version,
    )
    return market, indicators, regime, levels


def _evaluate(inputs, app_config, *, strategy=None, minimum_rr=None):
    market, indicators, regime, levels = inputs
    return evaluate_strategy(
        market,
        indicators,
        regime,
        levels,
        _costs(),
        strategy or app_config.strategy,
        app_config.calculation,
        app_config.risk.minimum_rr if minimum_rr is None else minimum_rr,
    )


def test_sideway_middle_and_explicit_hard_gates(market_snapshot, app_config, versions):
    middle = _evaluate(
        _inputs(market_snapshot, versions, location=RangeLocation.MIDDLE), app_config
    )
    assert middle.decision is TradeDecision.NO_TRADE
    assert middle.reason_codes == (ReasonCode.SIDEWAY_MIDDLE_RANGE,)

    bearish = _evaluate(_inputs(market_snapshot, versions, confirmation=False), app_config)
    assert bearish.decision is TradeDecision.NO_TRADE
    assert ReasonCode.NO_CONFIRMATION in bearish.reason_codes

    no_momentum = _evaluate(_inputs(market_snapshot, versions, momentum=False), app_config)
    assert no_momentum.decision is TradeDecision.NO_TRADE
    assert ReasonCode.NO_SIGNAL in no_momentum.reason_codes

    no_volume = _evaluate(_inputs(market_snapshot, versions, volume=False), app_config)
    assert no_volume.decision is TradeDecision.NO_TRADE
    assert ReasonCode.NO_SIGNAL in no_volume.reason_codes

    maximums = dict(app_config.strategy.component_max_points)
    maximums[SignalComponentName.MOMENTUM] = ZERO
    maximums[SignalComponentName.STRUCTURE] += D("20")
    weights = {
        name: dict(component_weights)
        for name, component_weights in app_config.strategy.component_evidence_weights.items()
    }
    weights[SignalComponentName.MOMENTUM] = {}
    disabled_momentum = replace(
        app_config.strategy,
        component_max_points=maximums,
        component_evidence_weights=weights,
    )
    disabled = _evaluate(
        _inputs(market_snapshot, versions, momentum=False),
        app_config,
        strategy=disabled_momentum,
    )
    assert disabled.decision is TradeDecision.LONG


def test_valid_sideway_long_short_and_breakout_retest(market_snapshot, app_config, versions):
    for side in (TradeSide.LONG, TradeSide.SHORT):
        outcome = _evaluate(_inputs(market_snapshot, versions, side=side), app_config)
        assert outcome.decision.value == side.value
        assert outcome.candidate is not None
        assert outcome.candidate.setup_type is SetupType.SIDEWAY_MEAN_REVERSION

    breakout = _evaluate(
        _inputs(
            market_snapshot,
            versions,
            breakout_state=BreakoutState.RETEST_VALIDATED,
            breakout_direction=BreakoutDirection.UP,
            location=RangeLocation.OUTSIDE_RANGE,
        ),
        app_config,
    )
    assert breakout.decision is TradeDecision.LONG
    assert breakout.candidate is not None
    assert breakout.candidate.setup_type is SetupType.BREAKOUT_RETEST


def test_trend_pullback_long_and_short(market_snapshot, app_config, versions):
    for side, regime_value in (
        (TradeSide.LONG, MarketRegime.TREND_UP),
        (TradeSide.SHORT, MarketRegime.TREND_DOWN),
    ):
        outcome = _evaluate(
            _inputs(market_snapshot, versions, side=side, regime_value=regime_value),
            app_config,
        )
        assert outcome.decision.value == side.value
        assert outcome.candidate is not None
        assert outcome.candidate.setup_type is SetupType.TREND_PULLBACK


def test_score_threshold_difference_and_rr_boundaries(market_snapshot, app_config, versions):
    inputs = _inputs(market_snapshot, versions)
    baseline = _evaluate(inputs, app_config)
    assert baseline.candidate is not None
    score = baseline.assessment.long_score
    difference = score - baseline.assessment.short_score

    at_score = replace(app_config.strategy, long_threshold=score)
    assert _evaluate(inputs, app_config, strategy=at_score).candidate is not None
    above_score = replace(app_config.strategy, long_threshold=score + D("0.0001"))
    assert _evaluate(inputs, app_config, strategy=above_score).decision is TradeDecision.NO_TRADE

    at_difference = replace(app_config.strategy, minimum_score_difference=difference)
    assert _evaluate(inputs, app_config, strategy=at_difference).candidate is not None
    above_difference = replace(
        app_config.strategy, minimum_score_difference=difference + D("0.0001")
    )
    conflict = _evaluate(inputs, app_config, strategy=above_difference)
    assert conflict.decision is TradeDecision.NO_TRADE
    assert conflict.reason_codes == (ReasonCode.SCORE_DIFFERENCE_TOO_SMALL,)

    rr = baseline.candidate.planned_rr_after_costs
    assert _evaluate(inputs, app_config, minimum_rr=rr).candidate is not None
    rejected_rr = _evaluate(inputs, app_config, minimum_rr=rr + D("0.0001"))
    assert rejected_rr.decision is TradeDecision.NO_TRADE
    assert rejected_rr.reason_codes == (ReasonCode.RR_TOO_LOW,)
