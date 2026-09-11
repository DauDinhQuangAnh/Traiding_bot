"""Incremental Decimal portfolio accounting for deterministic backtests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from trading_bot.backtest.funding import FundingRateEvent, funding_cash_flow
from trading_bot.backtest.models import (
    BacktestTradeResult,
    EquityPoint,
    FundingCashFlow,
    SimulatedFill,
)
from trading_bot.config.models import RiskConfig
from trading_bot.domain.decision_models import TradeCandidate
from trading_bot.domain.enums import (
    ExitReason,
    HealthStatus,
    OrderPurpose,
    PositionStatus,
    TradeSide,
)
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.identifiers import deterministic_id
from trading_bot.domain.primitives import ONE, ZERO, floor_to_step
from trading_bot.domain.risk_models import (
    ApprovedTradePlan,
    InstrumentMetadata,
    PositionState,
    RiskContext,
)
from trading_bot.domain.value_objects import HealthSnapshot, Quote, Target


@dataclass(slots=True)
class OpenBacktestPosition:
    candidate: TradeCandidate
    plan: ApprovedTradePlan
    entry_fill: SimulatedFill
    remaining_quantity: Decimal
    target_remaining: list[Decimal]
    exit_fills: list[SimulatedFill]
    gross_price_pnl: Decimal = ZERO
    exit_fees: Decimal = ZERO
    funding_cash_flow: Decimal = ZERO
    spread_cost_estimate: Decimal = ZERO
    slippage_cost_estimate: Decimal = ZERO


class BacktestPortfolio:
    def __init__(
        self,
        initial_equity: Decimal,
        start_time: datetime,
        metadata: InstrumentMetadata,
        daily_reset_timezone: str,
    ) -> None:
        if initial_equity <= ZERO:
            raise DomainValidationError("initial equity must be positive")
        self.initial_equity = initial_equity
        self.cash = initial_equity
        self.equity = initial_equity
        self.unrealized_pnl = ZERO
        self.metadata = metadata
        try:
            self.daily_reset_timezone = ZoneInfo(daily_reset_timezone)
        except (KeyError, ValueError) as error:
            raise DomainValidationError("invalid backtest daily reset timezone") from error
        self.position: OpenBacktestPosition | None = None
        self.completed_trades: list[BacktestTradeResult] = []
        self.total_fees = ZERO
        self.total_funding = ZERO
        self.total_spread_cost_estimate = ZERO
        self.total_slippage_cost_estimate = ZERO
        self.global_peak_equity = initial_equity
        self.session_peak_equity = initial_equity
        self.daily_net_pnl = ZERO
        self.daily_trade_count = 0
        self.consecutive_losses = 0
        self.cooldown_until: datetime | None = None
        self.session_date = start_time.astimezone(self.daily_reset_timezone).date()
        self.last_mark_price = ZERO
        self.last_mark_time = start_time
        self.exposure_bars = 0
        self.total_bars = 0

    def reset_session_if_needed(self, observed_at: datetime) -> bool:
        session_date = observed_at.astimezone(self.daily_reset_timezone).date()
        if session_date == self.session_date:
            return False
        self.session_date = session_date
        self.daily_net_pnl = ZERO
        self.daily_trade_count = 0
        self.session_peak_equity = self.equity
        return True

    def open(self, candidate: TradeCandidate, plan: ApprovedTradePlan, fill: SimulatedFill) -> None:
        if self.position is not None:
            raise DomainValidationError("cannot open a second backtest position")
        if (
            fill.purpose is not OrderPurpose.ENTRY
            or fill.approved_plan_id != plan.approved_plan_id
            or fill.quantity != plan.quantity
        ):
            raise DomainValidationError("entry fill does not match approved plan")
        targets = self._target_quantities(plan)
        self.position = OpenBacktestPosition(
            candidate=candidate,
            plan=plan,
            entry_fill=fill,
            remaining_quantity=fill.quantity,
            target_remaining=list(targets),
            exit_fills=[],
            spread_cost_estimate=fill.spread_cost_estimate,
            slippage_cost_estimate=fill.slippage_cost_estimate,
        )
        self.cash -= fill.fee
        self.daily_net_pnl -= fill.fee
        self.daily_trade_count += 1
        self.total_fees += fill.fee
        self.total_spread_cost_estimate += fill.spread_cost_estimate
        self.total_slippage_cost_estimate += fill.slippage_cost_estimate

    def apply_exit(
        self,
        fill: SimulatedFill,
        reason: ExitReason,
        risk_config: RiskConfig,
        *,
        target_index: int | None = None,
    ) -> BacktestTradeResult | None:
        position = self._require_position()
        if fill.quantity > position.remaining_quantity or fill.quantity <= ZERO:
            raise DomainValidationError("exit quantity exceeds remaining position")
        if fill.trade_id != position.candidate.candidate_id:
            raise DomainValidationError("exit fill trade identity mismatch")
        base_quantity = self.metadata.base_quantity(fill.quantity)
        if position.plan.side is TradeSide.LONG:
            gross = (fill.fill_price - position.entry_fill.fill_price) * base_quantity
        else:
            gross = (position.entry_fill.fill_price - fill.fill_price) * base_quantity
        position.gross_price_pnl += gross
        position.exit_fees += fill.fee
        position.spread_cost_estimate += fill.spread_cost_estimate
        position.slippage_cost_estimate += fill.slippage_cost_estimate
        position.remaining_quantity -= fill.quantity
        position.exit_fills.append(fill)
        if target_index is not None:
            if not 0 <= target_index < len(position.target_remaining):
                raise DomainValidationError("invalid target index")
            if fill.quantity > position.target_remaining[target_index]:
                raise DomainValidationError("target fill exceeds allocation")
            position.target_remaining[target_index] -= fill.quantity
        elif reason is ExitReason.STOP_LOSS or reason is ExitReason.BACKTEST_END:
            position.target_remaining = [ZERO for _ in position.target_remaining]
        self.cash += gross - fill.fee
        self.daily_net_pnl += gross - fill.fee
        self.total_fees += fill.fee
        self.total_spread_cost_estimate += fill.spread_cost_estimate
        self.total_slippage_cost_estimate += fill.slippage_cost_estimate
        if position.remaining_quantity > ZERO:
            return None
        final_reason = reason
        if reason is ExitReason.TAKE_PROFIT and len(position.plan.targets) > 1:
            final_reason = ExitReason.MULTI_TARGET_COMPLETE
        trade = self._close_result(position, fill.event_time, final_reason)
        self.completed_trades.append(trade)
        self.position = None
        self.unrealized_pnl = ZERO
        if trade.net_pnl < ZERO:
            self.consecutive_losses += 1
            self.cooldown_until = fill.event_time + risk_config.cooldown_after_loss
        elif trade.net_pnl > ZERO:
            self.consecutive_losses = 0
            self.cooldown_until = None
        return trade

    def apply_funding(
        self, event: FundingRateEvent, mark_price: Decimal, model_version: str
    ) -> FundingCashFlow | None:
        if self.position is None:
            return None
        notional = self.metadata.notional(self.position.remaining_quantity, mark_price)
        cash_flow = funding_cash_flow(self.position.plan.side, notional, event.rate)
        record = FundingCashFlow(
            deterministic_id(
                "backtest-funding-cash-flow-v1",
                self.position.candidate.candidate_id,
                event.timestamp,
                event.rate,
                notional,
                model_version,
            ),
            self.position.candidate.candidate_id,
            event.timestamp,
            event.rate,
            notional,
            cash_flow,
            model_version,
        )
        self.position.funding_cash_flow += cash_flow
        self.cash += cash_flow
        self.daily_net_pnl += cash_flow
        self.total_funding += cash_flow
        return record

    def mark(self, mark_price: Decimal, timestamp: datetime) -> EquityPoint:
        self.total_bars += 1
        if self.position is not None:
            self.exposure_bars += 1
            base_quantity = self.metadata.base_quantity(self.position.remaining_quantity)
            if self.position.plan.side is TradeSide.LONG:
                self.unrealized_pnl = (
                    mark_price - self.position.entry_fill.fill_price
                ) * base_quantity
            else:
                self.unrealized_pnl = (
                    self.position.entry_fill.fill_price - mark_price
                ) * base_quantity
        else:
            self.unrealized_pnl = ZERO
        self.equity = self.cash + self.unrealized_pnl
        self.global_peak_equity = max(self.global_peak_equity, self.equity)
        self.session_peak_equity = max(self.session_peak_equity, self.equity)
        drawdown = self.global_peak_equity - self.equity
        drawdown_ratio = (
            min(ONE, max(ZERO, drawdown / self.global_peak_equity))
            if self.global_peak_equity > ZERO
            else ONE
        )
        used_margin = self.used_margin(mark_price)
        available_margin = max(ZERO, self.equity - used_margin)
        self.last_mark_price = mark_price
        self.last_mark_time = timestamp
        return EquityPoint(
            timestamp,
            self.cash,
            self.unrealized_pnl,
            self.equity,
            used_margin,
            available_margin,
            self.global_peak_equity,
            max(ZERO, drawdown),
            drawdown_ratio,
        )

    def used_margin(self, mark_price: Decimal | None = None) -> Decimal:
        if self.position is None:
            return ZERO
        price = mark_price if mark_price is not None else self.last_mark_price
        if price <= ZERO:
            price = self.position.entry_fill.fill_price
        return (
            self.metadata.notional(self.position.remaining_quantity, price)
            / self.position.plan.leverage
        )

    def current_notional(self, mark_price: Decimal) -> Decimal:
        if self.position is None:
            return ZERO
        return self.metadata.notional(self.position.remaining_quantity, mark_price)

    @property
    def state_version(self) -> str:
        position_identity: object = None
        if self.position is not None:
            position_identity = (
                self.position.candidate.candidate_id,
                self.position.remaining_quantity,
                tuple(self.position.target_remaining),
                self.position.gross_price_pnl,
                self.position.exit_fees,
                self.position.funding_cash_flow,
            )
        return deterministic_id(
            "backtest-portfolio-state-v1",
            self.cash,
            self.equity,
            self.daily_net_pnl,
            self.session_peak_equity,
            self.daily_trade_count,
            self.consecutive_losses,
            self.cooldown_until,
            position_identity,
        )

    def risk_context(
        self,
        symbol: str,
        observed_at: datetime,
        quote: Quote,
        config_version: str,
        *,
        kill_switch_active: bool = False,
    ) -> RiskContext:
        if self.equity < ZERO:
            raise DomainValidationError("negative equity cannot create a RiskContext")
        state_version = self.state_version
        position_state = self._position_state(symbol, observed_at, state_version)
        session_drawdown = self.session_peak_equity - self.equity
        daily_drawdown_ratio = (
            min(ONE, max(ZERO, session_drawdown / self.session_peak_equity))
            if self.session_peak_equity > ZERO
            else ONE
        )
        health = HealthSnapshot(
            HealthStatus.HEALTHY,
            HealthStatus.HEALTHY,
            HealthStatus.HEALTHY,
            HealthStatus.HEALTHY,
            observed_at,
            (),
        )
        return RiskContext(
            deterministic_id(
                "backtest-risk-context-v1", state_version, observed_at, quote, kill_switch_active
            ),
            symbol,
            "BACKTEST_ACCOUNT",
            self.equity,
            self.equity,
            max(ZERO, self.equity - self.used_margin(quote.mid)),
            self.current_notional(quote.mid),
            self.daily_net_pnl,
            self.session_peak_equity,
            daily_drawdown_ratio,
            self.daily_trade_count,
            self.consecutive_losses,
            int(self.position is not None),
            self.cooldown_until,
            quote,
            position_state,
            health,
            kill_switch_active,
            True,
            observed_at,
            config_version,
            state_version,
        )

    def target_quantities(self) -> tuple[tuple[int, Target, Decimal], ...]:
        position = self._require_position()
        return tuple(
            (index, target, position.target_remaining[index])
            for index, target in enumerate(position.plan.targets)
        )

    def _position_state(
        self, symbol: str, observed_at: datetime, state_version: str
    ) -> PositionState:
        if self.position is None:
            return PositionState(
                deterministic_id("backtest-flat-position-v1", symbol, state_version),
                symbol,
                state_version,
                PositionStatus.FLAT,
                None,
                ZERO,
                ZERO,
                max(ZERO, self.last_mark_price),
                ZERO,
                ZERO,
                None,
                None,
                None,
                None,
                False,
                True,
                None,
                None,
                observed_at,
                None,
            )
        position = self.position
        stop_id = deterministic_id("backtest-stop-order-v1", position.plan.approved_plan_id)
        target_id = deterministic_id("backtest-target-order-v1", position.plan.approved_plan_id)
        return PositionState(
            deterministic_id("backtest-position-v1", position.candidate.candidate_id),
            symbol,
            state_version,
            PositionStatus.OPEN,
            position.plan.side,
            position.remaining_quantity,
            position.entry_fill.fill_price,
            max(ZERO, self.last_mark_price),
            self.unrealized_pnl,
            position.gross_price_pnl,
            stop_id,
            target_id,
            position.plan.stop_price,
            position.plan.targets[-1].price,
            True,
            True,
            position.entry_fill.event_time,
            None,
            observed_at,
            position.exit_fills[-1].fill_id if position.exit_fills else position.entry_fill.fill_id,
        )

    def _target_quantities(self, plan: ApprovedTradePlan) -> tuple[Decimal, ...]:
        remaining = plan.quantity
        quantities: list[Decimal] = []
        for index, target in enumerate(plan.targets):
            if index == len(plan.targets) - 1:
                quantity = remaining
            else:
                quantity = floor_to_step(
                    plan.quantity * target.quantity_fraction, self.metadata.lot_size
                )
                remaining -= quantity
            quantities.append(quantity)
        return tuple(quantities)

    def _close_result(
        self,
        position: OpenBacktestPosition,
        exit_time: datetime,
        exit_reason: ExitReason,
    ) -> BacktestTradeResult:
        gross = position.gross_price_pnl
        entry_fee = position.entry_fill.fee
        exit_fee = position.exit_fees
        net = gross - entry_fee - exit_fee + position.funding_cash_flow
        initial_risk = position.plan.worst_case_loss
        return BacktestTradeResult(
            position.candidate.candidate_id,
            position.candidate.candidate_id,
            position.plan.approved_plan_id,
            position.plan.side,
            position.candidate.setup_type,
            position.candidate.regime,
            position.candidate.signal_score,
            position.candidate.opposite_score,
            position.entry_fill.event_time,
            position.entry_fill.fill_price,
            position.entry_fill.quantity,
            position.plan.stop_price,
            position.plan.targets,
            exit_time,
            exit_reason,
            tuple(fill.fill_id for fill in position.exit_fills),
            gross,
            entry_fee,
            exit_fee,
            position.funding_cash_flow,
            position.spread_cost_estimate,
            position.slippage_cost_estimate,
            net,
            initial_risk,
            gross / initial_risk,
            net / initial_risk,
            exit_time - position.entry_fill.event_time,
            position.candidate.versions,
        )

    def _require_position(self) -> OpenBacktestPosition:
        if self.position is None:
            raise DomainValidationError("backtest portfolio has no open position")
        return self.position
