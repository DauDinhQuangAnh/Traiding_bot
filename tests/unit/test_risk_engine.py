"""Risk engine approval and hard-gate tests."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

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
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.risk_models import InstrumentMetadata, PositionState, RiskContext
from trading_bot.domain.value_objects import (
    CostRateEstimate,
    HealthSnapshot,
    Quote,
    Target,
    VersionSet,
)
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
        app_config.calculation,
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
        app_config.calculation,
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
        app_config.calculation,
        timedelta(seconds=30),
        NOW,
    )
    assert outcome.decision.action is RiskAction.REJECT
    assert ReasonCode.SPREAD_TOO_WIDE in outcome.decision.reason_codes


def run_risk(
    app_config,
    versions,
    *,
    trade=None,
    risk_context=None,
    instrument=None,
    costs=None,
    risk_config=None,
    metadata_max_age=None,
):
    return evaluate_risk(
        trade or candidate(versions),
        risk_context or context(versions),
        instrument or metadata(),
        costs or rates(),
        risk_config or app_config.risk,
        app_config.calculation,
        timedelta(seconds=30),
        NOW,
        metadata_max_age,
    )


def test_long_and_short_stop_geometry(app_config, versions):
    long_result = run_risk(app_config, versions)
    short_trade = replace(
        candidate(versions),
        side=TradeSide.SHORT,
        stop_price=D("102"),
        targets=(Target("TP", D("90"), D("1")),),
    )
    short_result = run_risk(app_config, versions, trade=short_trade)
    assert long_result.decision.action is RiskAction.APPROVE
    assert short_result.decision.action is RiskAction.APPROVE
    with pytest.raises(DomainValidationError):
        replace(candidate(versions), stop_price=D("100"))
    with pytest.raises(DomainValidationError):
        replace(candidate(versions), stop_price=D("0"))
    with pytest.raises(DomainValidationError):
        replace(candidate(versions), stop_price=D("101"))


@pytest.mark.parametrize(
    ("stop", "reason", "approved"),
    [
        ("99.1", ReasonCode.STOP_TOO_CLOSE, False),
        ("99", None, True),
        ("98.99", None, True),
        ("91", ReasonCode.STOP_TOO_FAR, False),
    ],
)
def test_stop_distance_boundaries(app_config, versions, stop, reason, approved):
    outcome = run_risk(app_config, versions, trade=replace(candidate(versions), stop_price=D(stop)))
    assert (outcome.decision.action is RiskAction.APPROVE) is approved
    if reason is not None:
        assert reason in outcome.decision.reason_codes


@pytest.mark.parametrize(
    ("changes", "reason", "action"),
    [
        ({"daily_net_pnl": D("-200")}, ReasonCode.DAILY_LOSS_LIMIT, RiskAction.HALT),
        ({"daily_drawdown_ratio": D("0.05")}, ReasonCode.DAILY_DRAWDOWN_LIMIT, RiskAction.HALT),
        ({"daily_trade_count": 5}, ReasonCode.DAILY_TRADE_LIMIT, RiskAction.REJECT),
        ({"consecutive_losses": 3}, ReasonCode.CONSECUTIVE_LOSS_LIMIT, RiskAction.HALT),
        ({"open_position_count": 1}, ReasonCode.MAX_OPEN_POSITIONS, RiskAction.REJECT),
        (
            {"cooldown_until": NOW + timedelta(seconds=1)},
            ReasonCode.COOLDOWN_ACTIVE,
            RiskAction.REJECT,
        ),
    ],
)
def test_account_limit_boundaries(app_config, versions, changes, reason, action):
    outcome = run_risk(app_config, versions, risk_context=replace(context(versions), **changes))
    assert outcome.decision.action is action
    assert reason in outcome.decision.reason_codes


def test_spread_and_slippage_exact_boundaries(app_config, versions):
    exact_quote = Quote("BTC-USDT-SWAP", "fixture", D("99.95"), D("100.05"), NOW, NOW)
    exact_spread = run_risk(
        app_config,
        versions,
        risk_context=replace(context(versions), quote=exact_quote),
    )
    assert exact_spread.decision.action is RiskAction.APPROVE
    wide_quote = Quote("BTC-USDT-SWAP", "fixture", D("99.949"), D("100.051"), NOW, NOW)
    assert (
        run_risk(
            app_config, versions, risk_context=replace(context(versions), quote=wide_quote)
        ).decision.action
        is RiskAction.REJECT
    )

    exact_rates = replace(rates(), entry_slippage_rate=app_config.risk.max_slippage)
    assert run_risk(app_config, versions, costs=exact_rates).decision.action is RiskAction.APPROVE
    high_rates = replace(rates(), entry_slippage_rate=app_config.risk.max_slippage + D("0.000001"))
    high = run_risk(app_config, versions, costs=high_rates)
    assert high.decision.action is RiskAction.REJECT
    assert ReasonCode.SLIPPAGE_TOO_HIGH in high.decision.reason_codes


def test_version_and_metadata_gates(app_config, versions):
    stale_candidate = replace(
        candidate(versions),
        versions=VersionSet("code", versions.strategy_version, "other-config", "data"),
    )
    assert (
        ReasonCode.VERSION_MISMATCH
        in run_risk(app_config, versions, trade=stale_candidate).decision.reason_codes
    )
    state_mismatch = replace(context(versions), state_version="other-state")
    assert (
        ReasonCode.VERSION_MISMATCH
        in run_risk(app_config, versions, risk_context=state_mismatch).decision.reason_codes
    )
    stale_metadata = replace(metadata(), effective_at=NOW - timedelta(hours=2))
    stale = run_risk(
        app_config,
        versions,
        instrument=stale_metadata,
        metadata_max_age=timedelta(hours=1),
    )
    assert ReasonCode.INSTRUMENT_METADATA_STALE in stale.decision.reason_codes


def test_instrument_version_and_cost_version_change_risk_identity(app_config, versions):
    first = run_risk(app_config, versions)
    second = run_risk(app_config, versions, instrument=replace(metadata(), version="instrument-v2"))
    assert first.decision.risk_decision_id != second.decision.risk_decision_id
    assert second.decision.instrument_version == "instrument-v2"

    new_rates = replace(rates(), model_version="cost-v2")
    trade = replace(candidate(versions), cost_rate_estimate=new_rates)
    cost_changed = run_risk(app_config, versions, trade=trade, costs=new_rates)
    assert cost_changed.decision.cost_model_version == "cost-v2"


def test_quantity_notional_exposure_margin_and_leverage_gates(app_config, versions):
    too_large_minimum = replace(metadata(), minimum_quantity=D("9000"))
    minimum = run_risk(app_config, versions, instrument=too_large_minimum)
    assert ReasonCode.POSITION_SIZE_TOO_SMALL in minimum.decision.reason_codes

    too_large_notional = replace(metadata(), minimum_notional=D("1000000"))
    minimum_notional = run_risk(app_config, versions, instrument=too_large_notional)
    assert ReasonCode.POSITION_SIZE_TOO_SMALL in minimum_notional.decision.reason_codes

    capped_config = replace(
        app_config.risk, max_position_notional=D("100"), max_total_exposure=D("100")
    )
    capped = run_risk(app_config, versions, risk_config=capped_config)
    assert capped.plan is not None
    assert capped.plan.notional <= D("100")

    exposure = run_risk(
        app_config,
        versions,
        risk_context=replace(context(versions), current_notional=D("9999.5")),
    )
    assert ReasonCode.POSITION_CAP_EXCEEDED in exposure.decision.reason_codes

    margin = run_risk(
        app_config,
        versions,
        risk_context=replace(context(versions), available_margin=D("0")),
    )
    assert ReasonCode.INSUFFICIENT_MARGIN in margin.decision.reason_codes

    leverage = run_risk(
        app_config, versions, instrument=replace(metadata(), maximum_leverage=D("0.5"))
    )
    assert ReasonCode.LEVERAGE_CAP_EXCEEDED in leverage.decision.reason_codes


def test_cost_adjusted_risk_and_rr_boundary(app_config, versions):
    zero_rates = CostRateEstimate(*(D("0") for _ in range(7)), model_version="zero")
    zero_trade = replace(candidate(versions), cost_rate_estimate=zero_rates)
    without_costs = run_risk(app_config, versions, trade=zero_trade, costs=zero_rates)
    with_costs = run_risk(app_config, versions)
    assert without_costs.plan is not None and with_costs.plan is not None
    assert with_costs.plan.quantity <= without_costs.plan.quantity
    assert with_costs.plan.fee_estimate.entry_fee > D("0")
    assert with_costs.plan.fee_estimate.funding_cash_flow < D("0")

    exact = replace(app_config.risk, minimum_rr=with_costs.plan.expected_rr)
    assert run_risk(app_config, versions, risk_config=exact).decision.action is RiskAction.APPROVE
    above = replace(app_config.risk, minimum_rr=with_costs.plan.expected_rr + D("0.000001"))
    rr_reject = run_risk(app_config, versions, risk_config=above)
    assert rr_reject.decision.action is RiskAction.REJECT
    assert ReasonCode.RR_TOO_LOW in rr_reject.decision.reason_codes


@pytest.mark.parametrize("field", ["data_status", "api_status", "journal_status", "account_status"])
def test_kill_switch_health_and_reconciliation_halt(app_config, versions, field):
    active = run_risk(
        app_config, versions, risk_context=replace(context(versions), kill_switch_active=True)
    )
    assert active.decision.action is RiskAction.HALT

    health = replace(context(versions).health, **{field: HealthStatus.UNHEALTHY})
    unhealthy = run_risk(
        app_config, versions, risk_context=replace(context(versions), health=health)
    )
    assert unhealthy.decision.action is RiskAction.HALT

    unreconciled_position = replace(context(versions).position_state, is_reconciled=False)
    unreconciled = run_risk(
        app_config,
        versions,
        risk_context=replace(context(versions), position_state=unreconciled_position),
    )
    assert unreconciled.decision.action is RiskAction.HALT
