from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from trading_bot.backtest.engine import BacktestEngine
from trading_bot.backtest.versions import run_id
from trading_bot.domain.enums import (
    BacktestEventType,
    BacktestStatus,
    ExitReason,
    ReasonCode,
    TradeSide,
)
from trading_bot.domain.primitives import canonical_json
from trading_bot.infrastructure.sqlite_backtest import SQLiteBacktestRepository

from .helpers import START, candidate, candle, engine_inputs, evaluation, no_trade_evaluation

D = Decimal


def _run(app_config, bars, trades=(), *, config=None):
    backtest_config = config or app_config.backtest
    start = bars[0].open_time
    end = bars[-1].close_time
    spec, configured, instrument, costs, funding = engine_inputs(
        app_config, start, end, config=backtest_config
    )
    evaluations = tuple(
        evaluation(candidate(time, spec.versions, costs, side=side, identity=identity))
        for time, side, identity in trades
    )
    return BacktestEngine(spec, configured, instrument, costs, funding).run(
        tuple(bars), evaluations
    )


def test_signal_bar_high_cannot_create_historical_instant_win(app_config):
    bars = (
        candle(START, "100", "120", "99", "100"),
        candle(START + timedelta(minutes=5), "100", "105", "99", "102"),
    )
    result = _run(
        app_config,
        bars,
        ((bars[0].close_time, TradeSide.LONG, "lookahead"),),
    )
    assert len(result.trades) == 1
    assert result.trades[0].entry_time == bars[1].open_time
    assert result.trades[0].exit_reason is ExitReason.BACKTEST_END
    assert not any(event.event_type is BacktestEventType.TARGET_FILLED for event in result.events)


def test_same_entry_bar_stop_and_target_uses_worst_case(app_config):
    bars = (
        candle(START, "100", "101", "99", "100"),
        candle(START + timedelta(minutes=5), "100", "111", "94", "105"),
    )
    result = _run(
        app_config,
        bars,
        ((bars[0].close_time, TradeSide.LONG, "ambiguous"),),
    )
    assert result.trades[0].exit_reason is ExitReason.STOP_LOSS
    event_types = tuple(event.event_type for event in result.events)
    assert BacktestEventType.STOP_FILLED in event_types
    assert BacktestEventType.TARGET_FILLED not in event_types


def test_gap_through_long_stop_executes_worse_than_open_and_not_at_stop(app_config):
    bars = (
        candle(START, "100", "101", "99", "100"),
        candle(START + timedelta(minutes=5), "100", "104", "99", "101"),
        candle(START + timedelta(minutes=10), "90", "92", "85", "88"),
    )
    result = _run(
        app_config,
        bars,
        ((bars[0].close_time, TradeSide.LONG, "gap-stop"),),
    )
    stop_fill = next(fill for fill in result.fills if fill.purpose.value == "STOP")
    assert stop_fill.reference_price == D("90")
    assert stop_fill.fill_price < D("90")
    assert stop_fill.fill_price != D("95")


def test_risk_reject_prevents_order_and_fill(app_config):
    wide_spread = replace(app_config.backtest, modeled_spread_rate=D("0.002"))
    bars = (
        candle(START, "100", "101", "99", "100"),
        candle(START + timedelta(minutes=5), "100", "110", "99", "105"),
    )
    result = _run(
        app_config,
        bars,
        ((bars[0].close_time, TradeSide.LONG, "reject"),),
        config=wide_spread,
    )
    assert result.orders == () and result.fills == ()
    assert result.metrics.risk_rejections == 1
    assert any(event.event_type is BacktestEventType.RISK_REJECT for event in result.events)


def test_daily_loss_halt_stops_future_entries(app_config):
    bars = (
        candle(START, "100", "101", "99", "100"),
        candle(START + timedelta(minutes=5), "100", "102", "99", "100"),
        candle(START + timedelta(minutes=10), "70", "72", "65", "68"),
        candle(START + timedelta(minutes=15), "68", "70", "67", "69"),
        candle(START + timedelta(minutes=20), "69", "80", "68", "75"),
    )
    result = _run(
        app_config,
        bars,
        (
            (bars[0].close_time, TradeSide.LONG, "loss"),
            (bars[3].close_time, TradeSide.LONG, "halt-check"),
        ),
    )
    assert result.run.status is BacktestStatus.HALTED
    assert result.metrics.risk_halts == 1
    assert len(result.orders) == 1
    halt = next(event for event in result.events if event.event_type is BacktestEventType.RISK_HALT)
    assert any(code.value == "DAILY_LOSS_LIMIT" for code in halt.reason_codes)


def test_positive_costs_cannot_improve_equity_and_artifacts_are_deterministic(app_config, tmp_path):
    bars = (
        candle(START, "100", "101", "99", "100"),
        candle(START + timedelta(minutes=5), "100", "105", "99", "103"),
        candle(START + timedelta(minutes=10), "103", "111", "102", "110"),
    )
    zero = replace(
        app_config.backtest,
        modeled_spread_rate=D("0"),
        market_slippage_rate=D("0"),
        stop_slippage_rate=D("0"),
        maker_fee_rate=D("0"),
        taker_fee_rate=D("0"),
    )
    trades = ((bars[0].close_time, TradeSide.LONG, "cost"),)
    zero_result = _run(app_config, bars, trades, config=zero)
    positive = _run(app_config, bars, trades)
    repeated = _run(app_config, bars, trades)
    assert positive.metrics.final_equity <= zero_result.metrics.final_equity
    assert positive.metrics.total_fees > 0
    assert canonical_json(positive) == canonical_json(repeated)

    first = SQLiteBacktestRepository(tmp_path / "first.db")
    second = SQLiteBacktestRepository(tmp_path / "second.db")
    try:
        first.append_result(positive)
        first.append_result(positive)
        second.append_result(repeated)
        assert first.get_result_json(positive.run.spec.backtest_run_id) == second.get_result_json(
            repeated.run.spec.backtest_run_id
        )
    finally:
        first.close()
        second.close()


def test_no_trade_is_retained_without_order(app_config):
    bars = (
        candle(START, "100", "101", "99", "100"),
        candle(START + timedelta(minutes=5), "100", "101", "99", "100"),
    )
    spec, configured, instrument, costs, funding = engine_inputs(
        app_config, bars[0].open_time, bars[-1].close_time
    )
    result = BacktestEngine(spec, configured, instrument, costs, funding).run(
        bars, (no_trade_evaluation(bars[0].close_time, spec.versions),)
    )
    assert result.metrics.evaluations == 1
    assert result.metrics.no_trade_evaluations == 1
    assert result.orders == () and result.fills == ()
    assert any(event.event_type is BacktestEventType.NO_TRADE for event in result.events)


def test_open_position_causes_risk_max_position_reject(app_config):
    bars = tuple(
        candle(START + timedelta(minutes=5 * index), "100", "101", "99", "100")
        for index in range(5)
    )
    result = _run(
        app_config,
        bars,
        (
            (bars[0].close_time, TradeSide.LONG, "first"),
            (bars[3].close_time, TradeSide.LONG, "second"),
        ),
    )
    rejects = [
        event for event in result.events if event.event_type is BacktestEventType.RISK_REJECT
    ]
    assert len(result.orders) == 1
    assert len(rejects) == 1
    assert ReasonCode.MAX_OPEN_POSITIONS in rejects[0].reason_codes


def test_loss_state_drives_cooldown_and_consecutive_loss_halt(app_config):
    bars = (
        candle(START, "100", "101", "99", "100"),
        candle(START + timedelta(minutes=5), "100", "101", "99", "100"),
        candle(START + timedelta(minutes=10), "96", "97", "94", "96"),
        candle(START + timedelta(minutes=15), "96", "97", "96", "96"),
        candle(START + timedelta(minutes=20), "96", "97", "96", "96"),
    )
    candidates = (
        (bars[0].close_time, TradeSide.LONG, "loss"),
        (bars[3].close_time, TradeSide.LONG, "after-loss"),
    )
    cooldown = _run(app_config, bars, candidates)
    cooldown_event = next(
        event for event in cooldown.events if event.event_type is BacktestEventType.RISK_REJECT
    )
    assert ReasonCode.COOLDOWN_ACTIVE in cooldown_event.reason_codes

    halt_risk = replace(app_config.risk, max_consecutive_losses=1)
    halted = _run(replace(app_config, risk=halt_risk), bars, candidates)
    halt_event = next(
        event for event in halted.events if event.event_type is BacktestEventType.RISK_HALT
    )
    assert ReasonCode.CONSECUTIVE_LOSS_LIMIT in halt_event.reason_codes


def test_daily_trade_and_drawdown_state_gate_future_candidate(app_config):
    bars = (
        candle(START, "100", "101", "99", "100"),
        candle(START + timedelta(minutes=5), "100", "101", "99", "100"),
        candle(START + timedelta(minutes=10), "100", "111", "99", "110"),
        candle(START + timedelta(minutes=15), "110", "111", "109", "110"),
        candle(START + timedelta(minutes=20), "110", "111", "109", "110"),
    )
    candidates = (
        (bars[0].close_time, TradeSide.LONG, "win"),
        (bars[3].close_time, TradeSide.LONG, "daily-limit"),
    )
    trade_limit_risk = replace(
        app_config.risk,
        max_daily_trades=1,
        cooldown_after_loss=timedelta(0),
    )
    limited = _run(replace(app_config, risk=trade_limit_risk), bars, candidates)
    rejection = next(
        event for event in limited.events if event.event_type is BacktestEventType.RISK_REJECT
    )
    assert ReasonCode.DAILY_TRADE_LIMIT in rejection.reason_codes

    loss_bars = (
        bars[0],
        bars[1],
        candle(START + timedelta(minutes=10), "96", "97", "94", "96"),
        candle(START + timedelta(minutes=15), "96", "97", "96", "96"),
        candle(START + timedelta(minutes=20), "96", "97", "96", "96"),
    )
    drawdown_risk = replace(
        app_config.risk,
        max_daily_loss=D("10000"),
        max_daily_drawdown=D("0.001"),
    )
    drawdown = _run(replace(app_config, risk=drawdown_risk), loss_bars, candidates)
    halt = next(
        event for event in drawdown.events if event.event_type is BacktestEventType.RISK_HALT
    )
    assert ReasonCode.DAILY_DRAWDOWN_LIMIT in halt.reason_codes


def test_margin_and_minimum_rr_rejections_have_no_simulator_consequence(app_config):
    bars = (
        candle(START, "100", "101", "99", "100"),
        candle(START + timedelta(minutes=5), "100", "101", "99", "100"),
    )
    trade = ((bars[0].close_time, TradeSide.LONG, "gate"),)
    risk_variants = (
        (
            replace(app_config.risk, margin_buffer_ratio=D("0.9999")),
            ReasonCode.INSUFFICIENT_MARGIN,
        ),
        (replace(app_config.risk, minimum_rr=D("3")), ReasonCode.RR_TOO_LOW),
    )
    for risk, reason in risk_variants:
        result = _run(replace(app_config, risk=risk), bars, trade)
        rejection = next(
            event for event in result.events if event.event_type is BacktestEventType.RISK_REJECT
        )
        assert reason in rejection.reason_codes
        assert result.orders == () and result.fills == ()


def test_injected_instrument_leverage_cap_rejects_entry(app_config):
    bars = (
        candle(START, "100", "101", "99", "100"),
        candle(START + timedelta(minutes=5), "100", "101", "99", "100"),
    )
    base_spec, configured, instrument, costs, funding = engine_inputs(
        app_config, bars[0].open_time, bars[-1].close_time
    )
    capped = replace(instrument, maximum_leverage=D("0.5"), version="instrument-capped-v1")
    identifier = run_id(
        base_spec.versions,
        base_spec.historical_versions,
        capped,
        base_spec.execution_model_version,
        base_spec.cost_model_version,
        base_spec.funding_model_version,
        base_spec.start_time,
        base_spec.end_time,
        base_spec.initial_equity,
    )
    spec = replace(
        base_spec,
        backtest_run_id=identifier,
        instrument_metadata_version=capped.version,
    )
    result = BacktestEngine(spec, configured, capped, costs, funding).run(
        bars,
        (evaluation(candidate(bars[0].close_time, spec.versions, costs, identity="leverage-cap")),),
    )
    rejection = next(
        event for event in result.events if event.event_type is BacktestEventType.RISK_REJECT
    )
    assert ReasonCode.LEVERAGE_CAP_EXCEEDED in rejection.reason_codes
    assert result.orders == () and result.fills == ()


def test_appended_future_bars_do_not_change_fixed_range_result(app_config):
    fixed = (
        candle(START, "100", "101", "99", "100"),
        candle(START + timedelta(minutes=5), "100", "101", "99", "100"),
    )
    spec, configured, instrument, costs, funding = engine_inputs(
        app_config, fixed[0].open_time, fixed[-1].close_time
    )
    evaluations = (
        evaluation(candidate(fixed[0].close_time, spec.versions, costs, identity="fixed")),
    )
    original = BacktestEngine(spec, configured, instrument, costs, funding).run(fixed, evaluations)
    appended = (*fixed, candle(START + timedelta(minutes=10), "500", "900", "1", "700"))
    repeated = BacktestEngine(spec, configured, instrument, costs, funding).run(
        appended, evaluations
    )
    assert canonical_json(original) == canonical_json(repeated)


def test_daily_session_resets_at_configured_timezone_boundary(app_config):
    start = START.replace(hour=23, minute=55)
    bars = (
        candle(start, "100", "101", "99", "100"),
        candle(start + timedelta(minutes=5), "100", "101", "99", "100"),
    )
    result = _run(app_config, bars)
    resets = [
        event for event in result.events if event.event_type is BacktestEventType.SESSION_RESET
    ]
    assert len(resets) == 1
    assert resets[0].event_time == start + timedelta(minutes=5)
