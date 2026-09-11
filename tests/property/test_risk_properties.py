from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st
from tests.unit.test_risk_engine import NOW, candidate, context, metadata, rates

from trading_bot.config.loader import load_config
from trading_bot.domain.enums import HealthStatus, RiskAction
from trading_bot.domain.value_objects import Quote, VersionSet
from trading_bot.risk.engine import evaluate_risk

CONFIG = load_config(Path("config/base.example.yaml"))


@settings(deadline=None)
@given(equity=st.integers(min_value=100, max_value=100_000))
def test_approved_loss_never_exceeds_generated_budget(equity: int):
    versions = VersionSet("code", CONFIG.strategy.version, "test-config", "data")
    amount = Decimal(equity)
    risk_context = replace(
        context(versions),
        account_equity=amount,
        eligible_equity=amount,
    )
    outcome = evaluate_risk(
        candidate(versions),
        risk_context,
        metadata(),
        rates(),
        CONFIG.risk,
        CONFIG.calculation,
        timedelta(seconds=30),
        NOW,
    )
    assert outcome.decision.action is RiskAction.APPROVE
    assert outcome.plan is not None
    assert outcome.plan.worst_case_loss <= outcome.plan.risk_budget


@settings(deadline=None)
@given(
    gate=st.sampled_from(
        (
            "kill_switch",
            "health",
            "account_reconciled",
            "position_reconciled",
            "daily_loss",
            "daily_drawdown",
            "consecutive_loss",
            "daily_trade",
            "open_position",
            "cooldown",
            "spread",
            "slippage",
            "config_version",
            "state_version",
            "metadata_stale",
        )
    )
)
def test_any_active_hard_gate_never_approves(gate: str):
    versions = VersionSet("code", CONFIG.strategy.version, "test-config", "data")
    trade = candidate(versions)
    risk_context = context(versions)
    instrument = metadata()
    cost_rates = rates()
    metadata_max_age = None
    if gate == "kill_switch":
        risk_context = replace(risk_context, kill_switch_active=True)
    elif gate == "health":
        risk_context = replace(
            risk_context,
            health=replace(risk_context.health, data_status=HealthStatus.UNHEALTHY),
        )
    elif gate == "account_reconciled":
        risk_context = replace(risk_context, account_reconciled=False)
    elif gate == "position_reconciled":
        risk_context = replace(
            risk_context,
            position_state=replace(risk_context.position_state, is_reconciled=False),
        )
    elif gate == "daily_loss":
        risk_context = replace(risk_context, daily_net_pnl=-CONFIG.risk.max_daily_loss)
    elif gate == "daily_drawdown":
        risk_context = replace(risk_context, daily_drawdown_ratio=CONFIG.risk.max_daily_drawdown)
    elif gate == "consecutive_loss":
        risk_context = replace(risk_context, consecutive_losses=CONFIG.risk.max_consecutive_losses)
    elif gate == "daily_trade":
        risk_context = replace(risk_context, daily_trade_count=CONFIG.risk.max_daily_trades)
    elif gate == "open_position":
        risk_context = replace(risk_context, open_position_count=CONFIG.risk.max_open_positions)
    elif gate == "cooldown":
        risk_context = replace(risk_context, cooldown_until=NOW + timedelta(seconds=1))
    elif gate == "spread":
        risk_context = replace(
            risk_context,
            quote=Quote("BTC-USDT-SWAP", "fixture", Decimal("99"), Decimal("101"), NOW, NOW),
        )
    elif gate == "slippage":
        cost_rates = replace(
            cost_rates, entry_slippage_rate=CONFIG.risk.max_slippage + Decimal("0.001")
        )
    elif gate == "config_version":
        risk_context = replace(risk_context, config_version="other")
    elif gate == "state_version":
        risk_context = replace(risk_context, state_version="other")
    elif gate == "metadata_stale":
        instrument = replace(instrument, effective_at=NOW - timedelta(hours=2))
        metadata_max_age = timedelta(hours=1)
    outcome = evaluate_risk(
        trade,
        risk_context,
        instrument,
        cost_rates,
        CONFIG.risk,
        CONFIG.calculation,
        timedelta(seconds=30),
        NOW,
        metadata_max_age,
    )
    assert outcome.decision.action is not RiskAction.APPROVE
