"""Correctly labeled aggregate and window-level walk-forward statistics."""

from __future__ import annotations

from decimal import Decimal
from statistics import median

from trading_bot.config.calculation import calculation_context
from trading_bot.config.models import CalculationConfig
from trading_bot.domain.primitives import ZERO
from trading_bot.validation.models import WalkForwardSummary, WalkForwardWindowResult


def summarize_walk_forward(
    results: tuple[WalkForwardWindowResult, ...], calculation: CalculationConfig
) -> WalkForwardSummary:
    if not results:
        return WalkForwardSummary(0, 0, 0, None, None, None, None, None, ZERO)
    metrics = tuple(result.result.metrics for result in results)
    positive = sum(item.net_pnl > ZERO for item in metrics)
    negative = sum(item.net_pnl < ZERO for item in metrics)
    expectancy_values = tuple(
        item.expectancy_r for item in metrics if item.expectancy_r is not None
    )
    profit_factors = tuple(item.profit_factor for item in metrics if item.profit_factor is not None)
    trades = sum(item.trade_count for item in metrics)
    gross_profit = sum((item.gross_profit for item in metrics), ZERO)
    gross_loss = sum((item.gross_loss for item in metrics), ZERO)
    with calculation_context(calculation):
        weighted_expectancy = (
            sum(
                (
                    item.expectancy_r * Decimal(item.trade_count)
                    for item in metrics
                    if item.expectancy_r is not None
                ),
                ZERO,
            )
            / Decimal(trades)
            if trades
            else None
        )
        return WalkForwardSummary(
            len(metrics),
            positive,
            negative,
            Decimal(positive) / Decimal(len(metrics)),
            median(expectancy_values) if expectancy_values else None,
            median(profit_factors) if profit_factors else None,
            weighted_expectancy,
            gross_profit / gross_loss if gross_loss > ZERO else None,
            max(item.maximum_drawdown for item in metrics),
        )
