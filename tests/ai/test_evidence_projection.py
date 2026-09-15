from __future__ import annotations

from copy import copy
from dataclasses import fields
from decimal import Decimal

import pytest

from trading_bot.ai.evidence import project_benchmark_reference, project_market_evidence
from trading_bot.ai.models import AIMarketEvidence
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
    assert {"long_score", "short_score", "detected_regime_confidence"} <= serialized_names
    model_visible_fields = {item.name for item in fields(AIMarketEvidence)}
    assert (
        not {
            "reference_decision",
            "reference_regime",
            "reference_reason_codes",
        }
        & model_visible_fields
    )
    reference = project_benchmark_reference(result.decision)
    assert reference.reference_decision is result.decision.decision
    assert reference.reference_regime is result.decision.regime
    assert reference.reference_reason_codes == result.decision.reason_codes
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
        "candles_per_timeframe": 1,
    }
    mismatched_signals = copy(result.strategy.assessment)
    object.__setattr__(mismatched_signals, "evaluation_id", "other-evaluation")
    with pytest.raises(DomainValidationError, match="identities"):
        project_market_evidence(**{**arguments, "signals": mismatched_signals})
    with pytest.raises(DomainValidationError, match="positive"):
        project_market_evidence(**{**arguments, "candles_per_timeframe": 0})
