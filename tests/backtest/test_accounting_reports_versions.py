from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from trading_bot.backtest.engine import BacktestEngine
from trading_bot.backtest.execution import create_entry_order, force_close_fill, try_fill_entry
from trading_bot.backtest.portfolio import BacktestPortfolio
from trading_bot.backtest.reports import LIMITATIONS, markdown_summary, result_json
from trading_bot.backtest.repository import attempt_persist_result
from trading_bot.backtest.versions import (
    cost_model_version,
    execution_model_version,
    run_id,
)
from trading_bot.domain.enums import BacktestFailureKind, BacktestStatus, ExitReason
from trading_bot.domain.errors import PersistenceError
from trading_bot.domain.primitives import canonical_json
from trading_bot.domain.value_objects import VersionSet
from trading_bot.historical.models import HistoricalVersionSet

from .helpers import START, approved_plan, candidate, candle, engine_inputs, evaluation

D = Decimal


def _closed_trade_result(app_config):
    bars = (
        candle(START, "100", "101", "99", "100"),
        candle(START + timedelta(minutes=5), "100", "101", "99", "100"),
        candle(START + timedelta(minutes=10), "100", "111", "99", "110"),
    )
    spec, configured, instrument, costs, funding = engine_inputs(
        app_config, bars[0].open_time, bars[-1].close_time
    )
    return BacktestEngine(spec, configured, instrument, costs, funding).run(
        bars,
        (evaluation(candidate(bars[0].close_time, spec.versions, costs, identity="report")),),
    )


def test_accounting_reconciles_without_double_counting_cost_estimates(app_config):
    result = _closed_trade_result(app_config)
    trade = result.trades[0]
    assert trade.net_pnl == (
        trade.gross_price_pnl - trade.entry_fee - trade.exit_fee + trade.funding_cash_flow
    )
    assert result.metrics.final_equity == result.metrics.initial_equity + trade.net_pnl
    assert result.metrics.net_pnl == trade.net_pnl
    assert result.metrics.total_fees == trade.entry_fee + trade.exit_fee
    assert trade.spread_cost_estimate > D("0")
    assert trade.slippage_cost_estimate > D("0")
    assert all(point.equity == point.cash + point.unrealized_pnl for point in result.equity_curve)
    assert all(point.used_margin >= D("0") for point in result.equity_curve)


def test_entry_only_and_exit_only_fee_accounting(app_config):
    for entry_fee, exit_fee in ((D("10"), D("0")), (D("0"), D("10"))):
        spec, configured, instrument, costs, _ = engine_inputs(
            app_config, START, START + timedelta(minutes=10)
        )
        trade = candidate(START, spec.versions, costs, identity=f"fees-{entry_fee}-{exit_fee}")
        plan = approved_plan(trade, START)
        entry_bar = candle(START, "100", "101", "99", "100")
        order = create_entry_order(trade, plan, START)
        _, entry = try_fill_entry(
            order,
            trade,
            plan,
            entry_bar,
            instrument,
            configured.backtest,
            configured.execution,
            configured.risk,
            trade.cost_rate_estimate,
            current_notional=D("0"),
            available_margin=D("10000"),
            account_equity=D("10000"),
        )
        assert entry is not None
        entry = replace(entry, fee=entry_fee)
        portfolio = BacktestPortfolio(D("10000"), START, instrument, "UTC")
        portfolio.open(trade, plan, entry)
        exit_bar = candle(START + timedelta(minutes=5), "105", "106", "104", "105")
        exit_fill = replace(
            force_close_fill(plan, D("1"), exit_bar, instrument, configured.backtest, 0),
            fee=exit_fee,
        )
        closed = portfolio.apply_exit(exit_fill, ExitReason.BACKTEST_END, configured.risk)
        assert closed is not None
        assert closed.net_pnl == closed.gross_price_pnl - entry_fee - exit_fee
        assert portfolio.position is None


def test_machine_and_human_reports_are_deterministic_and_state_limitations(app_config):
    result = _closed_trade_result(app_config)
    encoded = result_json(result)
    assert encoded == result_json(result)
    assert canonical_json(result.events) in encoded
    assert '"liquidation_model":"NOT_IMPLEMENTED"' in encoded
    assert all(limitation in encoded for limitation in LIMITATIONS)
    markdown = markdown_summary(result)
    assert result.run.spec.backtest_run_id in markdown
    assert "Liquidation model: `NOT_IMPLEMENTED`" in markdown
    assert "does not establish a profitable strategy" in markdown


def test_cost_execution_and_run_versions_change_with_semantic_inputs(app_config):
    base = app_config.backtest
    provider_version = "funding-v1"
    base_cost = cost_model_version(base, provider_version)
    changed_cost = cost_model_version(
        replace(base, market_slippage_rate=base.market_slippage_rate + D("0.0001")),
        provider_version,
    )
    assert changed_cost != base_cost

    base_execution = execution_model_version(
        base, app_config.execution, app_config.risk, app_config.calculation
    )
    changed_execution = execution_model_version(
        replace(base, allow_same_bar_exit_after_entry=not base.allow_same_bar_exit_after_entry),
        app_config.execution,
        app_config.risk,
        app_config.calculation,
    )
    assert changed_execution != base_execution

    spec, _, instrument, _, _ = engine_inputs(app_config, START, START + timedelta(minutes=10))
    changed_strategy = replace(spec.versions, strategy_version="strategy-v2")
    changed_data = HistoricalVersionSet("m5-v2", "m15-v1", "h1-v1")
    identities = {
        run_id(
            versions,
            historical,
            instrument,
            execution,
            cost,
            spec.funding_model_version,
            spec.start_time,
            spec.end_time,
            spec.initial_equity,
        )
        for versions, historical, execution, cost in (
            (spec.versions, spec.historical_versions, base_execution, base_cost),
            (changed_strategy, spec.historical_versions, base_execution, base_cost),
            (
                VersionSet(
                    spec.versions.code_version,
                    spec.versions.strategy_version,
                    spec.versions.config_version,
                    changed_data.snapshot_data_version,
                ),
                changed_data,
                base_execution,
                base_cost,
            ),
            (spec.versions, spec.historical_versions, changed_execution, base_cost),
            (spec.versions, spec.historical_versions, base_execution, changed_cost),
        )
    }
    assert len(identities) == 5


def test_persistence_boundary_returns_typed_failed_status(app_config):
    class BrokenRepository:
        def append_result(self, result):
            raise PersistenceError("disk unavailable")

        def get_result_json(self, backtest_run_id):
            raise AssertionError("not used")

    result = _closed_trade_result(app_config)
    failure = attempt_persist_result(BrokenRepository(), result)
    assert failure is not None
    assert failure.status is BacktestStatus.FAILED
    assert failure.kind is BacktestFailureKind.PERSISTENCE
    assert failure.backtest_run_id == result.run.spec.backtest_run_id
