from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trading_bot.application.validation_pipeline import assemble_validation_run
from trading_bot.backtest.metrics import calculate_metrics
from trading_bot.backtest.models import (
    BacktestResult,
    BacktestRun,
    BacktestRunSpec,
    BacktestTradeResult,
    EquityPoint,
)
from trading_bot.config.models import CalculationConfig
from trading_bot.domain.enums import (
    BacktestStatus,
    DecimalRoundingMode,
    ExitReason,
    MarketRegime,
    SetupType,
    TradeSide,
)
from trading_bot.domain.value_objects import Target, VersionSet
from trading_bot.historical.models import HistoricalVersionSet
from trading_bot.validation.identity import create_validation_protocol, partition_result_id
from trading_bot.validation.metrics import project_validation_metrics
from trading_bot.validation.models import PartitionResult, PartitionType, PartitionWindow
from trading_bot.validation.splits import create_temporal_split

D = Decimal
START = datetime(2026, 1, 1, tzinfo=UTC)
HISTORICAL = HistoricalVersionSet("m5-v1", "m15-v1", "h1-v1")
VERSIONS = VersionSet("code-v1", "strategy-v1", "config-v1", HISTORICAL.snapshot_data_version)
CALCULATION = CalculationConfig(34, DecimalRoundingMode.ROUND_HALF_EVEN)


def trade(
    index: int,
    pnl: str,
    *,
    opened: datetime | None = None,
    side: TradeSide | None = None,
    regime: MarketRegime | None = None,
    setup: SetupType = SetupType.TREND_PULLBACK,
) -> BacktestTradeResult:
    entry_time = opened or START + timedelta(hours=index)
    net = D(pnl)
    risk = D("100")
    actual_side = side or (TradeSide.LONG if index % 2 == 0 else TradeSide.SHORT)
    actual_regime = regime or (
        MarketRegime.TREND_UP if actual_side is TradeSide.LONG else MarketRegime.TREND_DOWN
    )
    return BacktestTradeResult(
        f"trade-{index}",
        f"trade-{index}",
        f"plan-{index}",
        actual_side,
        setup,
        actual_regime,
        D("80"),
        D("10"),
        entry_time,
        D("100"),
        D("1"),
        D("95"),
        (Target("TP", D("110"), D("1")),),
        entry_time + timedelta(minutes=30),
        ExitReason.TAKE_PROFIT if net > 0 else ExitReason.STOP_LOSS,
        (f"fill-{index}",),
        net + D("1"),
        D("0.2"),
        D("0.3"),
        D("-0.5"),
        D("0.1"),
        D("0.2"),
        net,
        risk,
        (net + D("1")) / risk,
        net / risk,
        timedelta(minutes=30),
        VERSIONS,
    )


def equity_point(index: int, value: str, *, exposed: bool = False) -> EquityPoint:
    equity = D(value)
    return EquityPoint(
        START + timedelta(hours=index),
        equity,
        D("0"),
        equity,
        D("10") if exposed else D("0"),
        max(equity - D("10"), D("0")) if exposed else equity,
        max(equity, D("100")),
        max(D("100") - equity, D("0")),
        max(D("100") - equity, D("0")) / D("100"),
    )


def backtest_result(
    trades: tuple[BacktestTradeResult, ...],
    points: tuple[EquityPoint, ...] = (),
) -> BacktestResult:
    spec = BacktestRunSpec(
        "backtest-v1",
        "BTC-USDT-SWAP",
        START - timedelta(days=1),
        START + timedelta(days=10),
        D("10000"),
        VERSIONS,
        HISTORICAL,
        "instrument-v1",
        "execution-v1",
        "cost-v1",
        "funding-v1",
    )
    metrics = calculate_metrics(
        D("10000"),
        D("10000") + sum((item.net_pnl for item in trades), D("0")),
        trades,
        points,
        evaluations=len(trades),
        no_trade_evaluations=0,
        candidates=len(trades),
        risk_rejections=0,
        risk_halts=0,
        approvals=len(trades),
        expired_orders=0,
        exposure_bars=sum(point.used_margin > 0 for point in points),
        total_bars=len(points),
    )
    return BacktestResult(
        BacktestRun(spec, BacktestStatus.COMPLETED, spec.end_time, (), None),
        (),
        (),
        (),
        (),
        trades,
        points,
        metrics,
    )


def validation_run():
    split = create_temporal_split(
        evaluation_range(0, 2), evaluation_range(2, 4), evaluation_range(4, 6)
    )
    protocol = create_validation_protocol(
        protocol_version="protocol-v1",
        code_version="code-v1",
        strategy_version="strategy-v1",
        config_version="config-v1",
        split_id=split.split_id,
        historical_versions=HISTORICAL,
        execution_model_version="execution-v1",
        cost_model_version="cost-v1",
        funding_model_version="funding-v1",
        instrument_metadata_version="instrument-v1",
        allowed_sensitivity_dimensions=("strategy.long_threshold",),
        test_evaluation_count=1,
    )
    results = []
    for partition, evaluation in (
        (PartitionType.TRAIN, split.train),
        (PartitionType.VALIDATION, split.validation),
        (PartitionType.TEST, split.test),
    ):
        window = PartitionWindow(partition, START - timedelta(days=2), evaluation)
        metrics = project_validation_metrics(
            backtest_result((trade(0, "10", opened=evaluation.start),)),
            evaluation,
            minimum_sample_size=5,
            calculation=CALCULATION,
        )
        results.append(
            PartitionResult(
                partition_result_id(protocol.protocol_id, partition, window, f"bt-{partition}"),
                partition,
                window,
                f"bt-{partition}",
                "strategy-v1",
                "config-v1",
                "execution-v1",
                "cost-v1",
                "funding-v1",
                "instrument-v1",
                HISTORICAL,
                metrics,
            )
        )
    return assemble_validation_run(
        protocol,
        split,
        HISTORICAL,
        tuple(results),
        CALCULATION,
        limitations=("historical-only",),
    )


def evaluation_range(start_day: int, end_day: int):
    from trading_bot.validation.models import EvaluationRange

    return EvaluationRange(START + timedelta(days=start_day), START + timedelta(days=end_day))
