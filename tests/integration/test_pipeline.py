from decimal import Decimal

from trading_bot.application.pipeline import evaluate_market
from trading_bot.domain.enums import TradeDecision
from trading_bot.domain.primitives import canonical_json
from trading_bot.domain.value_objects import CostRateEstimate


def test_offline_pipeline_replay_is_byte_deterministic(market_snapshot, app_config, versions):
    costs = CostRateEstimate(
        Decimal("0.0005"),
        Decimal("0.0007"),
        Decimal("0.7") / Decimal("1000"),
        Decimal("0.0003"),
        Decimal("0.0005"),
        Decimal("0.0005"),
        Decimal("0.0001"),
        "test-costs",
    )
    first = evaluate_market(market_snapshot, app_config, versions, costs)
    second = evaluate_market(market_snapshot, app_config, versions, costs)
    assert canonical_json(first) == canonical_json(second)
    assert first.decision.decision is TradeDecision.NO_TRADE
