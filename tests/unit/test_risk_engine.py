"""Risk engine approval and hard-gate tests."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trading_bot.domain.decision_models import TradeCandidate
from trading_bot.domain.enums import (
    EntryModel,
    HealthStatus,
    MarketRegime,
    PositionStatus,
    ReasonCode,
    RiskAction,
    SetupType,
    TargetModel,
    TradeSide,
)
from trading_bot.domain.risk_models import InstrumentMetadata, PositionState, RiskContext
from trading_bot.domain.value_objects import CostRateEstimate, HealthSnapshot, Quote, Target
from trading_bot.risk.engine import evaluate_risk

NOW = datetime(2026, 1, 1, tzinfo=UTC)
D = Decimal


def rates() -> CostRateEstimate:
    return CostRateEstimate(
        D("0.0005"),
        D("0.0007"),
        D("0.0007"),
        D("0.0002"),
        D("0.0004"),
        D("0.0004"),
        D("0.0001"),
        "cost-v1",
    )


def candidate(versions) -> TradeCandidate:
    return TradeCandidate(
        "candidate-1",
        "evaluation-1",
        "BTC-USDT-SWAP",
        TradeSide.LONG,
        MarketRegime.TREND_UP,
        D("80"),
        D("10"),
        D("100"),
        D("98"),
        D("2"),
        (Target("TP", D("110"), D("1")),),
        D("5"),
        D("4"),
        rates(),
        SetupType.TREND_PULLBACK,
        EntryModel.CLOSE_REFERENCE,
        TargetModel.NEXT_OPPOSING_LEVEL,
        "signal-1",
        "regime-1",
        None,
        "swing-1",
        ("resistance-1",),
        (),
        NOW,
        versions,
    )


def context(versions) -> RiskContext:
    quote = Quote("BTC-USDT-SWAP", "fixture", D("99.98"), D("100.02"), NOW, NOW)
    position = PositionState(
        "position-1",
        "BTC-USDT-SWAP",
        "state-v1",
        PositionStatus.FLAT,
        None,
        D("0"),
        D("0"),
        D("100"),
        D("0"),
        D("0"),
        None,
        None,
        None,
        None,
        False,
        True,
        None,
        None,
        NOW,
        None,
    )
    health = HealthSnapshot(
        HealthStatus.HEALTHY,
        HealthStatus.HEALTHY,
        HealthStatus.HEALTHY,
        HealthStatus.HEALTHY,
        NOW,
        (),
    )
    return RiskContext(
        "risk-context-1",
        "BTC-USDT-SWAP",
        "account-1",
        D("10000"),
        D("10000"),
        D("5000"),
        D("0"),
        D("0"),
        D("10000"),
        D("0"),
        0,
        0,
        0,
        None,
        quote,
        position,
        health,
        False,
        True,
        NOW,
        versions.config_version,
        "state-v1",
    )


def metadata() -> InstrumentMetadata:
    return InstrumentMetadata(
        "BTC-USDT-SWAP",
        "SWAP",
        "USDT",
        True,
        D("0.01"),
        D("0.1"),
        D("1"),
        D("1"),
        D("10"),
        D("10000"),
        D("5"),
        NOW,
        "instrument-v1",
    )


def test_risk_engine_approves_with_recomputed_budget(app_config, versions):
    outcome = evaluate_risk(
        candidate(versions),
        context(versions),
        metadata(),
        rates(),
        app_config.risk,
        timedelta(seconds=30),
        NOW,
    )
    assert outcome.decision.action is RiskAction.APPROVE
    assert outcome.plan is not None
    assert outcome.plan.worst_case_loss <= outcome.plan.risk_budget
    assert outcome.plan.quantity % metadata().lot_size == 0


def test_risk_engine_halts_on_unreconciled_state(app_config, versions):
    unsafe = replace(context(versions), account_reconciled=False)
    outcome = evaluate_risk(
        candidate(versions),
        unsafe,
        metadata(),
        rates(),
        app_config.risk,
        timedelta(seconds=30),
        NOW,
    )
    assert outcome.decision.action is RiskAction.HALT
    assert ReasonCode.STATE_MISMATCH in outcome.decision.reason_codes


def test_risk_engine_rejects_wide_spread(app_config, versions):
    wide = Quote("BTC-USDT-SWAP", "fixture", D("99"), D("101"), NOW, NOW)
    market = replace(context(versions), quote=wide)
    outcome = evaluate_risk(
        candidate(versions),
        market,
        metadata(),
        rates(),
        app_config.risk,
        timedelta(seconds=30),
        NOW,
    )
    assert outcome.decision.action is RiskAction.REJECT
    assert ReasonCode.SPREAD_TOO_WIDE in outcome.decision.reason_codes
