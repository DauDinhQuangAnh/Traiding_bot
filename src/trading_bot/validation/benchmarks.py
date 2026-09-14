"""Local deterministic flat and buy-and-hold benchmarks."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from trading_bot.config.calculation import calculation_context
from trading_bot.config.models import CalculationConfig
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.identifiers import deterministic_id
from trading_bot.domain.primitives import ZERO, require_positive, require_ratio, require_utc
from trading_bot.validation.models import BenchmarkResult, EvaluationRange


def flat_benchmark(protocol_id: str, evaluation: EvaluationRange) -> BenchmarkResult:
    return BenchmarkResult(
        deterministic_id("flat-benchmark-v1", protocol_id, evaluation),
        "FLAT_NO_TRADE",
        evaluation,
        ZERO,
        ZERO,
        ZERO,
        ZERO,
        ZERO,
        ZERO,
    )


def buy_and_hold_benchmark(
    protocol_id: str,
    evaluation: EvaluationRange,
    marks: tuple[tuple[datetime, Decimal], ...],
    initial_equity: Decimal,
    entry_cost_rate: Decimal,
    exit_cost_rate: Decimal,
    calculation: CalculationConfig,
) -> BenchmarkResult:
    require_positive(initial_equity, "benchmark initial_equity")
    require_ratio(entry_cost_rate, "benchmark entry_cost_rate")
    require_ratio(exit_cost_rate, "benchmark exit_cost_rate")
    for timestamp, _ in marks:
        require_utc(timestamp, "benchmark mark timestamp")
    selected = tuple(
        (timestamp, price)
        for timestamp, price in marks
        if evaluation.start <= timestamp < evaluation.end
    )
    if len(selected) < 2 or tuple(item[0] for item in selected) != tuple(
        sorted(item[0] for item in selected)
    ):
        raise DomainValidationError("buy-and-hold requires at least two ordered OOS marks")
    if any(not price.is_finite() or price <= ZERO for _, price in selected):
        raise DomainValidationError("buy-and-hold marks must be finite and positive")
    with calculation_context(calculation):
        entry = selected[0][1]
        exit_price = selected[-1][1]
        quantity = initial_equity / entry
        entry_cost = initial_equity * entry_cost_rate
        exit_notional = quantity * exit_price
        exit_cost = exit_notional * exit_cost_rate
        net_pnl = (exit_price - entry) * quantity - entry_cost - exit_cost
        equities = (
            initial_equity,
            *(initial_equity - entry_cost + (price - entry) * quantity for _, price in selected),
            initial_equity + net_pnl,
        )
        peak = equities[0]
        maximum_drawdown = ZERO
        maximum_ratio = ZERO
        for equity in equities:
            peak = max(peak, equity)
            drawdown = peak - equity
            ratio = drawdown / peak if peak > ZERO else ZERO
            if drawdown > maximum_drawdown:
                maximum_drawdown = drawdown
                maximum_ratio = ratio
        return_ratio = net_pnl / initial_equity
    return BenchmarkResult(
        deterministic_id(
            "buy-hold-benchmark-v1",
            protocol_id,
            evaluation,
            selected,
            initial_equity,
            entry_cost_rate,
            exit_cost_rate,
        ),
        "BUY_AND_HOLD",
        evaluation,
        net_pnl,
        return_ratio,
        maximum_drawdown,
        maximum_ratio,
        Decimal("1"),
        entry_cost + exit_cost,
    )
