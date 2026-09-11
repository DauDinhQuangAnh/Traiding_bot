from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st
from tests.unit.test_risk_engine import NOW, candidate, context, metadata, rates

from trading_bot.config.loader import load_config
from trading_bot.domain.enums import RiskAction
from trading_bot.domain.value_objects import VersionSet
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
        timedelta(seconds=30),
        NOW,
    )
    assert outcome.decision.action is RiskAction.APPROVE
    assert outcome.plan is not None
    assert outcome.plan.worst_case_loss <= outcome.plan.risk_budget
