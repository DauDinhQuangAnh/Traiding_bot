from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

from trading_bot.application.pipeline import EvaluationResult
from trading_bot.backtest.costs import risk_cost_rates
from trading_bot.backtest.funding import DisabledFundingRateProvider, FundingRateProvider
from trading_bot.backtest.models import BacktestRunSpec
from trading_bot.backtest.versions import (
    cost_model_version,
    execution_model_version,
    historical_run_versions,
    run_id,
)
from trading_bot.config.models import AppConfig, BacktestConfig
from trading_bot.domain.decision_models import DecisionRecord, TradeCandidate
from trading_bot.domain.enums import (
    EntryModel,
    MarketRegime,
    ReasonCode,
    SetupType,
    TargetModel,
    Timeframe,
    TradeDecision,
    TradeSide,
)
from trading_bot.domain.market_models import Candle, IndicatorSnapshot
from trading_bot.domain.risk_models import ApprovedTradePlan, InstrumentMetadata
from trading_bot.domain.value_objects import CostRateEstimate, FeeBreakdown, Target, VersionSet
from trading_bot.historical.models import HistoricalVersionSet

D = Decimal
ONE = D("1")
START = datetime(2026, 1, 1, 10, 10, tzinfo=UTC)
HISTORICAL_VERSIONS = HistoricalVersionSet("m5-v1", "m15-v1", "h1-v1")


def candle(
    opened: datetime,
    opening: str,
    high: str,
    low: str,
    close: str,
    *,
    data_version: str = "m5-v1",
) -> Candle:
    closed = opened + timedelta(minutes=5)
    return Candle(
        f"m5-{opened.isoformat()}",
        "BTC-USDT-SWAP",
        Timeframe.M5,
        opened,
        closed,
        closed,
        closed,
        D(opening),
        D(high),
        D(low),
        D(close),
        D("10"),
        True,
        "fixture",
        data_version,
    )


def metadata(effective_at: datetime = START) -> InstrumentMetadata:
    return InstrumentMetadata(
        "BTC-USDT-SWAP",
        "LINEAR_SWAP_FIXTURE",
        "USDT",
        True,
        D("1"),
        D("0.01"),
        D("1"),
        D("1"),
        D("10"),
        D("10000"),
        D("5"),
        effective_at,
        "instrument-fixture-v1",
    )


def candidate(
    created_at: datetime,
    versions: VersionSet,
    costs: CostRateEstimate,
    *,
    side: TradeSide = TradeSide.LONG,
    identity: str = "candidate-1",
) -> TradeCandidate:
    stop = D("95") if side is TradeSide.LONG else D("105")
    target = D("110") if side is TradeSide.LONG else D("90")
    regime = MarketRegime.TREND_UP if side is TradeSide.LONG else MarketRegime.TREND_DOWN
    return TradeCandidate(
        identity,
        f"evaluation-{identity}",
        "BTC-USDT-SWAP",
        side,
        regime,
        D("80"),
        D("10"),
        D("100"),
        stop,
        D("5"),
        (Target("TP", target, D("1")),),
        D("2"),
        D("1.8"),
        costs,
        SetupType.TREND_PULLBACK,
        EntryModel.CLOSE_REFERENCE,
        TargetModel.NEXT_OPPOSING_LEVEL,
        f"signal-{identity}",
        f"regime-{identity}",
        None,
        f"invalidation-{identity}",
        (f"target-level-{identity}",),
        (),
        created_at,
        versions,
    )


def evaluation(trade: TradeCandidate) -> EvaluationResult:
    decision = DecisionRecord(
        f"decision-{trade.candidate_id}",
        trade.evaluation_id,
        trade.symbol,
        trade.created_at,
        trade.created_at,
        trade.entry_price,
        trade.regime,
        TradeDecision.LONG if trade.side is TradeSide.LONG else TradeDecision.SHORT,
        None,
        trade.signal_score,
        trade.opposite_score,
        (),
        None,
        f"snapshot-{trade.candidate_id}",
        f"indicator-{trade.candidate_id}",
        trade.regime_assessment_id,
        trade.signal_assessment_id,
        trade.candidate_id,
        None,
        None,
        trade.versions,
    )
    return EvaluationResult(
        cast(IndicatorSnapshot, None),
        None,
        None,
        None,
        trade,
        decision,
    )


def no_trade_evaluation(as_of: datetime, versions: VersionSet) -> EvaluationResult:
    decision = DecisionRecord(
        f"decision-no-trade-{as_of.isoformat()}",
        f"evaluation-no-trade-{as_of.isoformat()}",
        "BTC-USDT-SWAP",
        as_of,
        as_of,
        D("100"),
        MarketRegime.SIDEWAY,
        TradeDecision.NO_TRADE,
        None,
        D("0"),
        D("0"),
        (ReasonCode.NO_SIGNAL,),
        None,
        f"snapshot-no-trade-{as_of.isoformat()}",
        f"indicator-no-trade-{as_of.isoformat()}",
        f"regime-no-trade-{as_of.isoformat()}",
        f"signal-no-trade-{as_of.isoformat()}",
        None,
        None,
        None,
        versions,
    )
    return EvaluationResult(cast(IndicatorSnapshot, None), None, None, None, None, decision)


def engine_inputs(
    app_config: AppConfig,
    start: datetime,
    end: datetime,
    *,
    config: BacktestConfig | None = None,
    funding_provider: FundingRateProvider | None = None,
):
    configured = replace(app_config, backtest=config or app_config.backtest)
    provider = funding_provider or DisabledFundingRateProvider("funding-fixture-disabled-v1")
    cost_version = cost_model_version(configured.backtest, provider.model_version)
    costs = risk_cost_rates(configured.backtest, cost_version, provider.maximum_debit_rate)
    versions = historical_run_versions(
        VersionSet("code-v1", configured.strategy.version, "config-v1", "placeholder"),
        HISTORICAL_VERSIONS,
    )
    instrument = metadata(start)
    execution_version = execution_model_version(configured.backtest)
    identifier = run_id(
        versions,
        HISTORICAL_VERSIONS,
        instrument,
        execution_version,
        cost_version,
        provider.model_version,
        start,
        end,
        configured.backtest.initial_equity,
    )
    spec = BacktestRunSpec(
        identifier,
        "BTC-USDT-SWAP",
        start,
        end,
        configured.backtest.initial_equity,
        versions,
        HISTORICAL_VERSIONS,
        instrument.version,
        execution_version,
        cost_version,
        provider.model_version,
    )
    return spec, configured, instrument, costs, provider


def approved_plan(
    trade: TradeCandidate,
    created_at: datetime,
    *,
    quantity: Decimal = ONE,
    targets: tuple[Target, ...] | None = None,
) -> ApprovedTradePlan:
    actual_targets = targets or trade.targets
    return ApprovedTradePlan(
        f"plan-{trade.candidate_id}",
        f"approval-{trade.candidate_id}",
        trade.candidate_id,
        trade.symbol,
        trade.side,
        trade.entry_price,
        trade.stop_price,
        quantity,
        trade.entry_price * quantity,
        actual_targets,
        D("10"),
        D("5"),
        D("2"),
        D("2"),
        FeeBreakdown.zero(),
        created_at,
        created_at + timedelta(minutes=10),
        trade.versions.config_version,
        "state-v1",
        "instrument-fixture-v1",
        trade.cost_rate_estimate.model_version,
    )
