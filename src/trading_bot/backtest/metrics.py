"""Deterministic performance metrics over closed trades and the M5 equity curve."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import timedelta
from decimal import Decimal
from statistics import median

from trading_bot.backtest.models import (
    BacktestMetrics,
    BacktestTradeResult,
    DrawdownSummary,
    EquityPoint,
    MetricBreakdown,
    PerformanceSummary,
)
from trading_bot.domain.primitives import ZERO


def performance_summary(trades: Iterable[BacktestTradeResult]) -> PerformanceSummary:
    items = tuple(trades)
    pnls = tuple(item.net_pnl for item in items)
    winners = tuple(value for value in pnls if value > ZERO)
    losers = tuple(value for value in pnls if value < ZERO)
    count = len(items)
    gross_profit = sum(winners, ZERO)
    gross_loss = abs(sum(losers, ZERO))
    return PerformanceSummary(
        trades=count,
        wins=len(winners),
        losses=len(losers),
        breakeven=count - len(winners) - len(losers),
        net_pnl=sum(pnls, ZERO),
        win_rate=Decimal(len(winners)) / Decimal(count) if count else None,
        profit_factor=gross_profit / gross_loss if gross_loss > ZERO else None,
        expectancy=sum(pnls, ZERO) / Decimal(count) if count else None,
        expectancy_r=(
            sum((item.net_r_multiple for item in items), ZERO) / Decimal(count) if count else None
        ),
        maximum_loss=min(losers) if losers else None,
    )


def drawdown_summary(equity_curve: tuple[EquityPoint, ...]) -> DrawdownSummary:
    if not equity_curve:
        return DrawdownSummary(ZERO, ZERO, None, None, None)
    running_peak = equity_curve[0].equity
    running_peak_time = equity_curve[0].timestamp
    maximum = ZERO
    maximum_ratio = ZERO
    maximum_peak_time = running_peak_time
    trough_time = running_peak_time
    recovery_time = None
    searching_recovery = False
    for point in equity_curve:
        if point.equity > running_peak:
            running_peak = point.equity
            running_peak_time = point.timestamp
        drawdown = running_peak - point.equity
        ratio = drawdown / running_peak if running_peak > ZERO else ZERO
        if drawdown > maximum or (drawdown == maximum and ratio > maximum_ratio):
            maximum = drawdown
            maximum_ratio = ratio
            maximum_peak_time = running_peak_time
            trough_time = point.timestamp
            recovery_time = None
            searching_recovery = maximum > ZERO
        elif searching_recovery and recovery_time is None and point.equity >= running_peak:
            recovery_time = point.timestamp
            searching_recovery = False
    return DrawdownSummary(
        maximum,
        maximum_ratio,
        maximum_peak_time if maximum > ZERO else None,
        trough_time if maximum > ZERO else None,
        recovery_time,
    )


def calculate_metrics(
    initial_equity: Decimal,
    final_equity: Decimal,
    trades: tuple[BacktestTradeResult, ...],
    equity_curve: tuple[EquityPoint, ...],
    *,
    evaluations: int,
    no_trade_evaluations: int,
    candidates: int,
    risk_rejections: int,
    risk_halts: int,
    approvals: int,
    expired_orders: int,
    exposure_bars: int,
    total_bars: int,
) -> BacktestMetrics:
    summary = performance_summary(trades)
    winners = tuple(item.net_pnl for item in trades if item.net_pnl > ZERO)
    losers = tuple(item.net_pnl for item in trades if item.net_pnl < ZERO)
    r_values = tuple(item.net_r_multiple for item in trades)
    gross_profit = sum(
        (item.gross_price_pnl for item in trades if item.gross_price_pnl > ZERO), ZERO
    )
    total_fees = sum((item.entry_fee + item.exit_fee for item in trades), ZERO)
    total_funding = sum((item.funding_cash_flow for item in trades), ZERO)
    total_spread = sum((item.spread_cost_estimate for item in trades), ZERO)
    total_slippage = sum((item.slippage_cost_estimate for item in trades), ZERO)
    return BacktestMetrics(
        initial_equity=initial_equity,
        final_equity=final_equity,
        gross_pnl=sum((item.gross_price_pnl for item in trades), ZERO),
        net_pnl=final_equity - initial_equity,
        return_ratio=(final_equity - initial_equity) / initial_equity,
        summary=summary,
        average_win=sum(winners, ZERO) / Decimal(len(winners)) if winners else None,
        average_loss=sum(losers, ZERO) / Decimal(len(losers)) if losers else None,
        average_r_multiple=sum(r_values, ZERO) / Decimal(len(r_values)) if r_values else None,
        median_r_multiple=median(r_values) if r_values else None,
        best_trade=max((item.net_pnl for item in trades), default=None),
        worst_trade=min((item.net_pnl for item in trades), default=None),
        drawdown=drawdown_summary(equity_curve),
        max_consecutive_wins=_max_streak(trades, lambda trade: trade.net_pnl > ZERO),
        max_consecutive_losses=_max_streak(trades, lambda trade: trade.net_pnl < ZERO),
        current_consecutive_losses=_current_loss_streak(trades),
        average_holding_duration=(
            sum((item.holding_duration for item in trades), timedelta()) / len(trades)
            if trades
            else None
        ),
        market_exposure_ratio=(
            Decimal(exposure_bars) / Decimal(total_bars) if total_bars else ZERO
        ),
        total_fees=total_fees,
        total_funding=total_funding,
        estimated_spread_cost=total_spread,
        estimated_slippage_cost=total_slippage,
        cost_share_of_gross_profit=(
            (total_fees - total_funding + total_spread + total_slippage) / gross_profit
            if gross_profit > ZERO
            else None
        ),
        evaluations=evaluations,
        no_trade_evaluations=no_trade_evaluations,
        candidates=candidates,
        risk_rejections=risk_rejections,
        risk_halts=risk_halts,
        approvals=approvals,
        expired_orders=expired_orders,
        breakdowns=_breakdowns(trades),
    )


def _max_streak(
    trades: tuple[BacktestTradeResult, ...],
    predicate: Callable[[BacktestTradeResult], bool],
) -> int:
    maximum = 0
    current = 0
    for trade in trades:
        current = current + 1 if predicate(trade) else 0
        maximum = max(maximum, current)
    return maximum


def _current_loss_streak(trades: tuple[BacktestTradeResult, ...]) -> int:
    current = 0
    for trade in reversed(trades):
        if trade.net_pnl >= ZERO:
            break
        current += 1
    return current


def _breakdowns(trades: tuple[BacktestTradeResult, ...]) -> tuple[MetricBreakdown, ...]:
    dimensions: tuple[tuple[str, Callable[[BacktestTradeResult], str]], ...] = (
        ("side", lambda trade: trade.side.value),
        ("regime", lambda trade: trade.entry_regime.value),
        ("setup", lambda trade: trade.setup_type.value),
        ("year", lambda trade: f"{trade.entry_time.year:04d}"),
        ("month", lambda trade: trade.entry_time.strftime("%Y-%m")),
    )
    output: list[MetricBreakdown] = []
    for dimension, key in dimensions:
        values = sorted({key(trade) for trade in trades})
        output.extend(
            MetricBreakdown(
                dimension,
                value,
                performance_summary(trade for trade in trades if key(trade) == value),
            )
            for value in values
        )
    return tuple(output)
