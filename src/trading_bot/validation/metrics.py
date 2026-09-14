"""Sample-aware validation projections reusing PHASE 5 trade semantics."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from trading_bot.backtest.metrics import drawdown_summary, performance_summary
from trading_bot.backtest.models import BacktestResult, BacktestTradeResult
from trading_bot.config.calculation import calculation_context
from trading_bot.config.models import CalculationConfig
from trading_bot.domain.enums import MarketRegime, SetupType, TradeSide
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.primitives import ZERO
from trading_bot.validation.models import EvaluationRange, GroupMetric, ValidationMetrics


def project_validation_metrics(
    result: BacktestResult,
    evaluation: EvaluationRange,
    *,
    minimum_sample_size: int,
    calculation: CalculationConfig,
) -> ValidationMetrics:
    if minimum_sample_size <= 0:
        raise DomainValidationError("minimum_sample_size must be positive")
    with calculation_context(calculation):
        trades = tuple(
            trade
            for trade in result.trades
            if evaluation.start <= trade.entry_time < evaluation.end
        )
        points = tuple(
            point
            for point in result.equity_curve
            if evaluation.start <= point.timestamp < evaluation.end
        )
        summary = performance_summary(trades)
        drawdown = drawdown_summary(points)
        gross_profit = sum((trade.net_pnl for trade in trades if trade.net_pnl > ZERO), ZERO)
        gross_loss = abs(sum((trade.net_pnl for trade in trades if trade.net_pnl < ZERO), ZERO))
        total_costs = sum(
            (
                trade.entry_fee
                + trade.exit_fee
                + trade.spread_cost_estimate
                + trade.slippage_cost_estimate
                + max(-trade.funding_cash_flow, ZERO)
                for trade in trades
            ),
            ZERO,
        )
        exposure = (
            Decimal(sum(point.used_margin > ZERO for point in points)) / Decimal(len(points))
            if points
            else ZERO
        )
        initial_equity = result.run.spec.initial_equity
        return ValidationMetrics(
            trade_count=len(trades),
            net_pnl=summary.net_pnl,
            return_ratio=summary.net_pnl / initial_equity,
            profit_factor=summary.profit_factor,
            expectancy_r=summary.expectancy_r,
            maximum_drawdown=drawdown.maximum_drawdown,
            maximum_drawdown_ratio=drawdown.maximum_drawdown_ratio,
            win_rate=summary.win_rate,
            exposure=exposure,
            total_costs=total_costs,
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            groups=_group_metrics(trades, minimum_sample_size),
            insufficient_sample=len(trades) < minimum_sample_size,
        )


def _group_metrics(
    trades: tuple[BacktestTradeResult, ...], minimum_sample_size: int
) -> tuple[GroupMetric, ...]:
    dimensions: tuple[tuple[str, Callable[[BacktestTradeResult], str], tuple[str, ...]], ...] = (
        ("side", lambda trade: trade.side.value, tuple(item.value for item in TradeSide)),
        (
            "regime",
            lambda trade: trade.entry_regime.value,
            tuple(item.value for item in MarketRegime),
        ),
        ("setup", lambda trade: trade.setup_type.value, tuple(item.value for item in SetupType)),
    )
    output: list[GroupMetric] = []
    for dimension, key, values in dimensions:
        for value in values:
            members = tuple(trade for trade in trades if key(trade) == value)
            summary = performance_summary(members)
            output.append(
                GroupMetric(
                    dimension,
                    value,
                    len(members),
                    summary.net_pnl,
                    summary.profit_factor,
                    summary.expectancy_r,
                    len(members) < minimum_sample_size,
                )
            )
    return tuple(output)
