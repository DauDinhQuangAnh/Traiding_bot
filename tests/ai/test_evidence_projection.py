from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from trading_bot.ai.evidence import project_market_evidence
from trading_bot.application.pipeline import evaluate_market
from trading_bot.domain.enums import Timeframe
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.value_objects import CostRateEstimate


def test_project_market_evidence_is_past_only_bounded_and_canonical(
    market_snapshot, app_config, versions
) -> None:
    costs = CostRateEstimate(*(Decimal("0.0001") for _ in range(7)), model_version="cost-v1")
    result = evaluate_market(market_snapshot, app_config, versions, costs)
    assert result.levels is not None
    assert result.regime is not None
    assert result.strategy is not None
    evidence = project_market_evidence(
        market=market_snapshot,
        indicators=result.indicators,
        regime=result.regime,
        levels=result.levels,
        signals=result.strategy.assessment,
        decision=result.decision,
        candles_per_timeframe=2,
    )
    assert evidence.as_of == market_snapshot.as_of
    assert len(evidence.candles) == 6
    assert {item.timeframe for item in evidence.candles} == set(Timeframe)
    assert all(item.close_time <= evidence.as_of for item in evidence.candles)
    assert tuple(
        (item.category, item.name, item.source_id) for item in evidence.observations
    ) == tuple(sorted((item.category, item.name, item.source_id) for item in evidence.observations))
    serialized_names = {item.name for item in evidence.observations}
    assert {"long_score", "short_score", "reference_regime_confidence"} <= serialized_names
    for forbidden in {"pnl", "mfe", "mae", "exit", "winner"}:
        assert all(forbidden not in name.lower() for name in serialized_names)


def test_projection_rejects_source_identity_mismatch_and_invalid_bound(
    market_snapshot, app_config, versions
) -> None:
    costs = CostRateEstimate(*(Decimal("0.0001") for _ in range(7)), model_version="cost-v1")
    result = evaluate_market(market_snapshot, app_config, versions, costs)
    assert result.levels is not None
    assert result.regime is not None
    assert result.strategy is not None
    arguments = {
        "market": market_snapshot,
        "indicators": result.indicators,
        "regime": result.regime,
        "levels": result.levels,
        "signals": result.strategy.assessment,
        "decision": result.decision,
        "candles_per_timeframe": 1,
    }
    with pytest.raises(DomainValidationError, match="identities"):
        project_market_evidence(
            **{**arguments, "decision": replace(result.decision, symbol="ETH-USDT-SWAP")}
        )
    with pytest.raises(DomainValidationError, match="positive"):
        project_market_evidence(**{**arguments, "candles_per_timeframe": 0})
