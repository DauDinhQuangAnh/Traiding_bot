"""Deterministic machine- and human-readable backtest reports."""

from __future__ import annotations

from trading_bot.backtest.models import BacktestResult
from trading_bot.domain.primitives import canonical_json

LIMITATIONS = (
    "Historical OHLCV only; no order-book queue or real historical bid/ask.",
    "Spread, slippage and full limit fills are deterministic modeled assumptions.",
    "No venue liquidation, outage, latency, market-impact or true partial-fill model.",
    "Fee/funding/instrument inputs are versioned assumptions, not current OKX verification.",
    "No live execution evidence; technical validity is not evidence of profitability.",
)


def result_json(result: BacktestResult) -> str:
    breakdowns = {
        dimension: tuple(item for item in result.metrics.breakdowns if item.dimension == dimension)
        for dimension in ("side", "regime", "setup", "year", "month")
    }
    return canonical_json(
        {
            "run": result.run,
            "summary": result.metrics,
            "risk": {
                "rejections": result.metrics.risk_rejections,
                "halts": result.metrics.risk_halts,
                "approvals": result.metrics.approvals,
            },
            "costs": {
                "fees": result.metrics.total_fees,
                "funding": result.metrics.total_funding,
                "spread_estimate": result.metrics.estimated_spread_cost,
                "slippage_estimate": result.metrics.estimated_slippage_cost,
            },
            "long": tuple(item for item in breakdowns["side"] if item.value == "LONG"),
            "short": tuple(item for item in breakdowns["side"] if item.value == "SHORT"),
            "by_regime": breakdowns["regime"],
            "by_setup": breakdowns["setup"],
            "yearly": breakdowns["year"],
            "monthly": breakdowns["month"],
            "events": result.events,
            "orders": result.orders,
            "fills": result.fills,
            "funding_cash_flows": result.funding,
            "trades": result.trades,
            "equity_curve": result.equity_curve,
            "warnings": result.run.warnings,
            "limitations": LIMITATIONS,
            "liquidation_model": "NOT_IMPLEMENTED",
        }
    )


def markdown_summary(result: BacktestResult) -> str:
    spec = result.run.spec
    metrics = result.metrics
    profit_factor = (
        "unavailable"
        if metrics.summary.profit_factor is None
        else format(metrics.summary.profit_factor, "f")
    )
    lines = [
        "# Backtest Run",
        "",
        f"- Run ID: `{spec.backtest_run_id}`",
        f"- Dataset versions: M5 `{spec.historical_versions.m5_data_version}`, "
        f"M15 `{spec.historical_versions.m15_data_version}`, "
        f"H1 `{spec.historical_versions.h1_data_version}`",
        f"- Period: {spec.start_time.isoformat()} to {spec.end_time.isoformat()}",
        f"- Strategy version: `{spec.versions.strategy_version}`",
        f"- Execution model: `{spec.execution_model_version}`",
        f"- Cost model: `{spec.cost_model_version}`",
        "",
        "## Summary",
        "",
        f"- Evaluations: {metrics.evaluations}",
        f"- NO_TRADE: {metrics.no_trade_evaluations}",
        f"- Candidates / approvals / trades: {metrics.candidates} / "
        f"{metrics.approvals} / {metrics.summary.trades}",
        f"- Initial / final equity: {metrics.initial_equity} / {metrics.final_equity}",
        f"- Gross / net PnL: {metrics.gross_pnl} / {metrics.net_pnl}",
        f"- Profit factor: {profit_factor}",
        f"- Expectancy / expectancy R: {metrics.summary.expectancy} / "
        f"{metrics.summary.expectancy_r}",
        f"- Maximum drawdown: {metrics.drawdown.maximum_drawdown} "
        f"({metrics.drawdown.maximum_drawdown_ratio})",
        f"- Fees / funding: {metrics.total_fees} / {metrics.total_funding}",
        f"- Estimated spread / slippage cost: {metrics.estimated_spread_cost} / "
        f"{metrics.estimated_slippage_cost}",
        "- Liquidation model: `NOT_IMPLEMENTED`",
        "",
        "## Warnings and limitations",
        "",
        *(f"- `{warning.value}`" for warning in result.run.warnings),
        *(f"- {limitation}" for limitation in LIMITATIONS),
        "",
        "Passing this run's technical checks does not establish a profitable strategy.",
    ]
    return "\n".join(lines) + "\n"
