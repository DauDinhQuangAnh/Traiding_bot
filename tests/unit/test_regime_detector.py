from dataclasses import replace
from decimal import Decimal

from tests.unit.test_strategy_engine import _inputs
from trading_bot.domain.enums import MarketRegime, ReasonCode, StructureTrend, Timeframe, TradeSide
from trading_bot.domain.value_objects import VersionSet
from trading_bot.regime.detector import detect_regime

D = Decimal


def _run(inputs, app_config, *, regime_config=None, prior=None):
    market, indicators, _, levels = inputs
    return detect_regime(
        market,
        indicators,
        levels,
        regime_config or app_config.regime,
        app_config.calculation,
        indicators.versions.strategy_version,
        prior,
    )


def _sideway_inputs(market_snapshot, versions):
    market, indicators, regime, levels = _inputs(market_snapshot, versions)
    sideway_values = replace(
        indicators.values_by_timeframe[Timeframe.M15],
        ema20=D("160"),
        ema50=D("160"),
        ema200=D("160"),
        ema20_slope_atr=D("0"),
        ema50_slope_atr=D("0"),
        ema200_slope_atr=D("0"),
        adx=D("10"),
    )
    indicators = replace(
        indicators,
        values_by_timeframe={timeframe: sideway_values for timeframe in Timeframe},
    )
    levels = replace(
        levels,
        market_structure=replace(levels.market_structure, trend=StructureTrend.MIXED),
    )
    return market, indicators, regime, levels


def test_trend_up_down_required_confirmation_and_persistence(market_snapshot, app_config, versions):
    for side, expected in (
        (TradeSide.LONG, MarketRegime.TREND_UP),
        (TradeSide.SHORT, MarketRegime.TREND_DOWN),
    ):
        inputs = _inputs(market_snapshot, versions, side=side, regime_value=expected)
        first = _run(inputs, app_config)
        assert first.regime is MarketRegime.UNCERTAIN
        assert first.candidate_regime is expected
        assert first.confirmation_count == 1
        second = _run(inputs, app_config, prior=first)
        assert second.regime is expected
        assert second.confirmation_count == app_config.regime.required_confirmations


def test_sideway_candidate_and_persistence(market_snapshot, app_config, versions):
    inputs = _sideway_inputs(market_snapshot, versions)
    first = _run(inputs, app_config)
    second = _run(inputs, app_config, prior=first)
    assert first.candidate_regime is MarketRegime.SIDEWAY
    assert second.regime is MarketRegime.SIDEWAY
    persisted = _run(inputs, app_config, prior=second)
    assert persisted.regime is MarketRegime.SIDEWAY
    assert persisted.previous_confirmed_regime is MarketRegime.SIDEWAY


def test_high_volatility_has_safety_precedence_without_confirmation(
    market_snapshot, app_config, versions
):
    market, indicators, regime, levels = _inputs(
        market_snapshot, versions, regime_value=MarketRegime.TREND_UP
    )
    extreme = replace(
        indicators.values_by_timeframe[Timeframe.M15],
        atr_percentile=D("100"),
        bb_width_percentile=D("100"),
        atr=D("0.1"),
    )
    indicators = replace(
        indicators, values_by_timeframe={timeframe: extreme for timeframe in Timeframe}
    )
    result = _run((market, indicators, regime, levels), app_config)
    assert result.regime is MarketRegime.HIGH_VOLATILITY
    assert result.confirmation_count == 1


def test_uncertain_conflicts_and_margin_conflict(market_snapshot, app_config, versions):
    inputs = _inputs(market_snapshot, versions, regime_value=MarketRegime.TREND_UP)
    none_config = replace(
        app_config.regime,
        trend_candidate_threshold=D("1"),
        sideway_candidate_threshold=D("1"),
        high_volatility_candidate_threshold=D("1"),
    )
    no_candidate = _run(inputs, app_config, regime_config=none_config)
    assert no_candidate.regime is MarketRegime.UNCERTAIN
    assert no_candidate.candidate_regime is None

    market, indicators, regime, levels = inputs
    neutral = replace(
        indicators.values_by_timeframe[Timeframe.M15],
        ema20=market.candles_15m[-1].close,
        ema50=market.candles_15m[-1].close,
        ema200=market.candles_15m[-1].close,
        ema20_slope_atr=D("0"),
        ema50_slope_atr=D("0"),
        adx=D("35"),
    )
    indicators = replace(
        indicators, values_by_timeframe={timeframe: neutral for timeframe in Timeframe}
    )
    conflict_config = replace(
        app_config.regime,
        minimum_evidence_strength=D("0.1"),
        minimum_confidence=D("0.3"),
        trend_candidate_threshold=D("0.3"),
        conflict_tolerance=D("0.3"),
    )
    conflict = _run((market, indicators, regime, levels), app_config, regime_config=conflict_config)
    assert conflict.regime is MarketRegime.UNCERTAIN

    mixed = _sideway_inputs(market_snapshot, versions)
    mixed_market, mixed_indicators, mixed_regime, mixed_levels = mixed
    mixed_levels = replace(
        mixed_levels,
        market_structure=replace(mixed_levels.market_structure, trend=StructureTrend.BULLISH),
    )
    mixed_config = replace(
        app_config.regime,
        minimum_evidence_strength=D("0.1"),
        minimum_confidence=D("0.2"),
        trend_candidate_threshold=D("0.2"),
        sideway_candidate_threshold=D("0.2"),
        minimum_candidate_margin=D("0.9"),
    )
    margin_conflict = _run(
        (mixed_market, mixed_indicators, mixed_regime, mixed_levels),
        app_config,
        regime_config=mixed_config,
    )
    assert margin_conflict.regime is MarketRegime.UNCERTAIN
    assert margin_conflict.candidate_regime is None


def test_invalid_atr_and_version_mismatch_are_uncertain(market_snapshot, app_config, versions):
    market, indicators, regime, levels = _inputs(
        market_snapshot, versions, regime_value=MarketRegime.TREND_UP
    )
    invalid = replace(indicators.values_by_timeframe[Timeframe.M15], atr=D("0"))
    indicators_invalid = replace(
        indicators,
        values_by_timeframe={Timeframe.M5: invalid, Timeframe.M15: invalid, Timeframe.H1: invalid},
    )
    atr_result = _run((market, indicators_invalid, regime, levels), app_config)
    assert atr_result.regime is MarketRegime.UNCERTAIN
    assert atr_result.reason_codes == (ReasonCode.INDICATOR_INVALID,)

    mismatched_levels = replace(levels, config_version="other-config")
    mismatch = _run((market, indicators, regime, mismatched_levels), app_config)
    assert mismatch.regime is MarketRegime.UNCERTAIN
    assert mismatch.reason_codes == (ReasonCode.VERSION_MISMATCH,)


def test_config_version_mismatch_resets_prior_and_exact_threshold_passes(
    market_snapshot, app_config, versions
):
    inputs = _inputs(market_snapshot, versions, regime_value=MarketRegime.TREND_UP)
    first = _run(inputs, app_config)
    confirmed = _run(inputs, app_config, prior=first)
    assert confirmed.regime is MarketRegime.TREND_UP

    market, indicators, regime, levels = inputs
    new_versions = VersionSet(
        versions.code_version, versions.strategy_version, "new-config", versions.data_version
    )
    reset_inputs = (
        market,
        replace(indicators, versions=new_versions),
        regime,
        replace(levels, config_version="new-config"),
    )
    reset = _run(reset_inputs, app_config, prior=confirmed)
    assert reset.confirmation_count == 1
    assert reset.previous_confirmed_regime is None

    exact_config = replace(
        app_config.regime,
        required_confirmations=1,
        trend_candidate_threshold=first.candidate_scores[MarketRegime.TREND_UP],
        minimum_confidence=first.candidate_scores[MarketRegime.TREND_UP],
    )
    exact = _run(inputs, app_config, regime_config=exact_config)
    assert exact.regime is MarketRegime.TREND_UP
