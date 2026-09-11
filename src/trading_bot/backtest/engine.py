"""Event-driven M5 backtest orchestration with strategy and Risk Engine integration."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import pairwise

from trading_bot.application.pipeline import EvaluationResult
from trading_bot.backtest.costs import modeled_quote
from trading_bot.backtest.execution import (
    create_entry_order,
    execute_exit,
    exit_instructions,
    force_close_fill,
    try_fill_entry,
)
from trading_bot.backtest.funding import FundingRateProvider
from trading_bot.backtest.metrics import calculate_metrics
from trading_bot.backtest.models import (
    BacktestEvent,
    BacktestOrderState,
    BacktestResult,
    BacktestRun,
    BacktestRunSpec,
    EquityPoint,
    FundingCashFlow,
    SimulatedFill,
)
from trading_bot.backtest.portfolio import BacktestPortfolio
from trading_bot.backtest.versions import cost_model_version, execution_model_version
from trading_bot.config.models import AppConfig
from trading_bot.domain.decision_models import TradeCandidate
from trading_bot.domain.enums import (
    BacktestEventType,
    BacktestStatus,
    BacktestWarning,
    ExitReason,
    FundingMode,
    OrderStatus,
    ReasonCode,
    RiskAction,
    Timeframe,
    TradeDecision,
    TradeSide,
)
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.identifiers import deterministic_id
from trading_bot.domain.market_models import Candle
from trading_bot.domain.primitives import require_utc
from trading_bot.domain.risk_models import ApprovedTradePlan, InstrumentMetadata
from trading_bot.domain.value_objects import CostRateEstimate
from trading_bot.risk.engine import evaluate_risk


class BacktestEngine:
    def __init__(
        self,
        spec: BacktestRunSpec,
        config: AppConfig,
        metadata: InstrumentMetadata,
        costs: CostRateEstimate,
        funding_provider: FundingRateProvider,
    ) -> None:
        self.spec = spec
        self.config = config
        self.metadata = metadata
        self.costs = costs
        self.funding_provider = funding_provider
        self._events: list[BacktestEvent] = []
        self._orders: list[BacktestOrderState] = []
        self._fills: list[SimulatedFill] = []
        self._funding: list[FundingCashFlow] = []
        self._equity: list[EquityPoint] = []
        self._pending: BacktestOrderState | None = None
        self._candidates: dict[str, TradeCandidate] = {}
        self._plans: dict[str, ApprovedTradePlan] = {}
        self._halted = False
        self._equity_depleted = False
        self._counts = {
            "evaluations": 0,
            "no_trade": 0,
            "candidates": 0,
            "risk_rejections": 0,
            "risk_halts": 0,
            "approvals": 0,
            "expired_orders": 0,
        }

    def run(
        self,
        candles_m5: tuple[Candle, ...],
        evaluations: tuple[EvaluationResult, ...],
    ) -> BacktestResult:
        self._validate_inputs(candles_m5, evaluations)
        self.funding_provider.validate_range(self.spec.start_time, self.spec.end_time)
        portfolio = BacktestPortfolio(
            self.spec.initial_equity,
            self.spec.start_time,
            self.metadata,
            self.config.risk.daily_reset_timezone,
        )
        evaluation_by_time = {item.decision.as_of: item for item in evaluations}
        final_bar: Candle | None = None
        for bar in candles_m5:
            if not (self.spec.start_time <= bar.open_time and bar.close_time <= self.spec.end_time):
                continue
            final_bar = bar
            if portfolio.reset_session_if_needed(bar.open_time):
                self._event(BacktestEventType.SESSION_RESET, bar.open_time, {})
            entered = self._process_pending(bar, portfolio)
            rate_events = self.funding_provider.rates_between(bar.open_time, bar.close_time)
            if any(event.timestamp != bar.open_time for event in rate_events):
                raise DomainValidationError("funding events must align exactly to an M5 bar open")
            if tuple(event.timestamp for event in rate_events) != tuple(
                sorted({event.timestamp for event in rate_events})
            ):
                raise DomainValidationError("funding events must be unique and ordered")
            for rate_event in rate_events:
                record = portfolio.apply_funding(
                    rate_event, bar.open, self.funding_provider.model_version
                )
                if record is not None:
                    self._funding.append(record)
                    self._event(
                        BacktestEventType.FUNDING_APPLIED,
                        rate_event.timestamp,
                        {
                            "funding_id": record.funding_id,
                            "cash_flow": record.cash_flow,
                            "mark_price": bar.open,
                        },
                    )
            if portfolio.position is not None and (
                not entered or self.config.backtest.allow_same_bar_exit_after_entry
            ):
                self._process_position(bar, portfolio)
            mark_price = self._mark_price(bar.close, bar.close_time, portfolio)
            self._equity.append(portfolio.mark_bar_close(mark_price, bar.close_time))
            self._halt_if_equity_depleted(portfolio, bar.close_time)
            evaluation = evaluation_by_time.get(bar.close_time)
            if evaluation is not None and not self._halted:
                self._evaluate(evaluation, bar, portfolio)
            if self._halted and self.config.backtest.halt_stops_run:
                break
        if final_bar is None:
            raise DomainValidationError("requested range contains no complete M5 bar")
        if portfolio.position is not None:
            fill = force_close_fill(
                portfolio.position.plan,
                portfolio.position.remaining_quantity,
                final_bar,
                self.metadata,
                self.config.backtest,
                len(portfolio.position.exit_fills),
            )
            self._fills.append(fill)
            trade = portfolio.apply_exit(
                fill,
                ExitReason.BACKTEST_END,
                self.config.risk,
            )
            assert trade is not None
            self._event(
                BacktestEventType.POSITION_CLOSED,
                fill.event_time,
                {"trade_id": trade.trade_id, "exit_reason": trade.exit_reason},
            )
            self._equity.append(portfolio.revalue(final_bar.close, final_bar.close_time))
            self._halt_if_equity_depleted(portfolio, final_bar.close_time)
        if self._pending is not None:
            self._pending = replace(self._pending, status=OrderStatus.EXPIRED)
            self._replace_order(self._pending)
            self._counts["expired_orders"] += 1
            self._event(
                BacktestEventType.ORDER_EXPIRED,
                final_bar.close_time,
                {"order_id": self._pending.order_id, "reason": "BACKTEST_END"},
            )
        status = BacktestStatus.HALTED if self._halted else BacktestStatus.COMPLETED
        self._event(
            BacktestEventType.BACKTEST_HALTED
            if self._halted
            else BacktestEventType.BACKTEST_COMPLETED,
            final_bar.close_time,
            {},
        )
        metrics = calculate_metrics(
            self.spec.initial_equity,
            portfolio.equity,
            tuple(portfolio.completed_trades),
            tuple(self._equity),
            evaluations=self._counts["evaluations"],
            no_trade_evaluations=self._counts["no_trade"],
            candidates=self._counts["candidates"],
            risk_rejections=self._counts["risk_rejections"],
            risk_halts=self._counts["risk_halts"],
            approvals=self._counts["approvals"],
            expired_orders=self._counts["expired_orders"],
            exposure_bars=portfolio.exposure_bars,
            total_bars=portfolio.total_bars,
        )
        warnings = [
            BacktestWarning.MODELED_SPREAD,
            BacktestWarning.MODELED_SLIPPAGE,
            BacktestWarning.NO_REAL_ORDERBOOK,
            BacktestWarning.NO_LIQUIDATION_MODEL,
            BacktestWarning.FULL_LIMIT_FILL_ASSUMPTION,
        ]
        if self.funding_provider.mode is FundingMode.DISABLED:
            warnings.append(BacktestWarning.FUNDING_DISABLED)
        if self._equity_depleted:
            warnings.append(BacktestWarning.NEGATIVE_EQUITY_WITHOUT_LIQUIDATION_MODEL)
        run = BacktestRun(
            self.spec,
            status,
            final_bar.close_time,
            tuple(warnings),
            None,
        )
        return BacktestResult(
            run,
            tuple(self._events),
            tuple(self._orders),
            tuple(self._fills),
            tuple(self._funding),
            tuple(portfolio.completed_trades),
            tuple(self._equity),
            metrics,
        )

    def _process_pending(self, bar: Candle, portfolio: BacktestPortfolio) -> bool:
        if self._pending is None:
            return False
        candidate = self._candidates[self._pending.candidate_id]
        plan = self._plans[self._pending.approved_plan_id]
        outcome = try_fill_entry(
            self._pending,
            candidate,
            plan,
            bar,
            self.metadata,
            self.config.backtest,
            self.config.execution,
            self.config.risk,
            self.costs,
            current_notional=portfolio.current_notional(bar.open),
            available_margin=max(Decimal("0"), portfolio.equity - portfolio.used_margin(bar.open)),
            account_equity=portfolio.equity,
        )
        updated = outcome.order
        fill = outcome.fill
        self._pending = updated
        self._replace_order(updated)
        if updated.status is OrderStatus.EXPIRED:
            self._counts["expired_orders"] += 1
            self._event(
                BacktestEventType.ORDER_EXPIRED,
                bar.open_time,
                {"order_id": updated.order_id},
                outcome.reason_codes,
            )
            self._pending = None
            return False
        if updated.status is OrderStatus.REJECTED:
            self._event(
                BacktestEventType.ORDER_REJECTED,
                bar.open_time,
                {
                    "order_id": updated.order_id,
                    **dict(outcome.calculations),
                    "reason_codes": tuple(code.value for code in outcome.reason_codes),
                },
                outcome.reason_codes,
            )
            self._pending = None
            return False
        if fill is None:
            return False
        self._fills.append(fill)
        portfolio.open(candidate, plan, fill)
        self._event(
            BacktestEventType.ENTRY_FILLED,
            fill.event_time,
            {"fill_id": fill.fill_id, "fill_price": fill.fill_price},
        )
        self._pending = None
        return True

    def _process_position(self, bar: Candle, portfolio: BacktestPortfolio) -> None:
        position = portfolio.position
        assert position is not None
        instructions = exit_instructions(
            position.plan.side,
            position.plan.stop_price,
            portfolio.target_quantities(),
            position.remaining_quantity,
            bar,
        )
        for instruction in instructions:
            if portfolio.position is None:
                break
            fill = execute_exit(
                instruction,
                len(position.exit_fills),
                position.plan,
                bar,
                self.metadata,
                self.config.backtest,
            )
            self._fills.append(fill)
            event_type = (
                BacktestEventType.STOP_FILLED
                if instruction.exit_reason is ExitReason.STOP_LOSS
                else BacktestEventType.TARGET_FILLED
            )
            self._event(
                event_type,
                fill.event_time,
                {"fill_id": fill.fill_id, "fill_price": fill.fill_price},
            )
            trade = portfolio.apply_exit(
                fill,
                instruction.exit_reason,
                self.config.risk,
                target_index=instruction.target_index,
            )
            if trade is not None:
                self._event(
                    BacktestEventType.POSITION_CLOSED,
                    fill.event_time,
                    {"trade_id": trade.trade_id, "net_pnl": trade.net_pnl},
                )

    def _evaluate(
        self, evaluation: EvaluationResult, bar: Candle, portfolio: BacktestPortfolio
    ) -> None:
        decision = evaluation.decision
        self._counts["evaluations"] += 1
        self._event(
            BacktestEventType.EVALUATION,
            decision.as_of,
            {"evaluation_id": decision.evaluation_id, "decision": decision.decision},
        )
        if decision.decision is TradeDecision.NO_TRADE or evaluation.candidate is None:
            self._counts["no_trade"] += 1
            self._event(
                BacktestEventType.NO_TRADE,
                decision.as_of,
                {"evaluation_id": decision.evaluation_id},
                decision.reason_codes,
            )
            return
        candidate = evaluation.candidate
        self._counts["candidates"] += 1
        self._candidates[candidate.candidate_id] = candidate
        self._event(
            BacktestEventType.CANDIDATE,
            decision.as_of,
            {"candidate_id": candidate.candidate_id},
        )
        quote = modeled_quote(candidate.symbol, bar.close, decision.as_of, self.config.backtest)
        context = portfolio.risk_context(
            candidate.symbol,
            decision.as_of,
            quote,
            candidate.versions.config_version,
            kill_switch_active=self._halted,
        )
        outcome = evaluate_risk(
            candidate,
            context,
            self.metadata,
            self.costs,
            self.config.risk,
            self.config.calculation,
            self.config.execution.approval_ttl,
            decision.as_of,
            None,
        )
        if outcome.decision.action is RiskAction.REJECT:
            self._counts["risk_rejections"] += 1
            self._event(
                BacktestEventType.RISK_REJECT,
                decision.as_of,
                {"risk_decision_id": outcome.decision.risk_decision_id},
                outcome.decision.reason_codes,
            )
            return
        if outcome.decision.action is RiskAction.HALT:
            self._counts["risk_halts"] += 1
            self._halted = True
            self._event(
                BacktestEventType.RISK_HALT,
                decision.as_of,
                {"risk_decision_id": outcome.decision.risk_decision_id},
                outcome.decision.reason_codes,
            )
            return
        plan = outcome.plan
        assert plan is not None
        if self._pending is not None:
            self._counts["risk_rejections"] += 1
            return
        self._counts["approvals"] += 1
        self._plans[plan.approved_plan_id] = plan
        order = create_entry_order(candidate, plan, decision.as_of)
        if any(existing.approved_plan_id == plan.approved_plan_id for existing in self._orders):
            raise DomainValidationError("approved plan cannot create duplicate entry intent")
        self._pending = order
        self._orders.append(order)
        self._event(
            BacktestEventType.RISK_APPROVE,
            decision.as_of,
            {"risk_decision_id": outcome.decision.risk_decision_id},
        )
        self._event(
            BacktestEventType.ORDER_CREATED,
            decision.as_of,
            {"order_id": order.order_id, "eligible_from": order.eligible_from},
        )

    def _mark_price(
        self, close: Decimal, timestamp: datetime, portfolio: BacktestPortfolio
    ) -> Decimal:
        if portfolio.position is None:
            return close
        quote = modeled_quote(self.spec.symbol, close, timestamp, self.config.backtest)
        return quote.bid if portfolio.position.plan.side is TradeSide.LONG else quote.ask

    def _halt_if_equity_depleted(self, portfolio: BacktestPortfolio, event_time: datetime) -> None:
        if portfolio.equity > Decimal("0") or self._equity_depleted:
            return
        self._equity_depleted = True
        self._halted = True
        self._event(
            BacktestEventType.ECONOMIC_HALT,
            event_time,
            {
                "cash": portfolio.cash,
                "equity": portfolio.equity,
                "liquidation_model": "NOT_IMPLEMENTED",
                "reason_codes": (ReasonCode.EQUITY_DEPLETED.value,),
            },
            (ReasonCode.EQUITY_DEPLETED,),
        )

    def _replace_order(self, updated: BacktestOrderState) -> None:
        for index, order in enumerate(self._orders):
            if order.order_id == updated.order_id:
                self._orders[index] = updated
                return
        raise DomainValidationError("pending order is missing from journal")

    def _event(
        self,
        event_type: BacktestEventType,
        event_time: datetime,
        payload: dict[str, object],
        reason_codes: tuple[ReasonCode, ...] = (),
    ) -> None:
        if self._events and event_time < self._events[-1].event_time:
            raise DomainValidationError("backtest event time cannot decrease")
        sequence = len(self._events)
        identifier = deterministic_id(
            "backtest-event-v1",
            self.spec.backtest_run_id,
            sequence,
            event_type,
            event_time,
            payload,
            reason_codes,
        )
        self._events.append(
            BacktestEvent(
                identifier,
                self.spec.backtest_run_id,
                sequence,
                event_time,
                event_type,
                reason_codes,
                payload,
            )
        )

    def _validate_inputs(
        self,
        candles_m5: tuple[Candle, ...],
        evaluations: tuple[EvaluationResult, ...],
    ) -> None:
        require_utc(self.spec.start_time, "start_time")
        require_utc(self.spec.end_time, "end_time")
        if self.metadata.symbol != self.spec.symbol:
            raise DomainValidationError("instrument metadata symbol mismatch")
        if self.metadata.version != self.spec.instrument_metadata_version:
            raise DomainValidationError("instrument metadata version mismatch")
        if not self.metadata.is_linear_quote_margined:
            raise DomainValidationError("backtest supports injected linear metadata only")
        if self.costs.model_version != self.spec.cost_model_version:
            raise DomainValidationError("cost model version mismatch")
        if self.funding_provider.model_version != self.spec.funding_model_version:
            raise DomainValidationError("funding model version mismatch")
        if self.funding_provider.mode is not self.config.backtest.funding_mode:
            raise DomainValidationError("funding mode mismatch")
        if self.spec.execution_model_version != execution_model_version(
            self.config.backtest,
            self.config.execution,
            self.config.risk,
            self.config.calculation,
        ):
            raise DomainValidationError("execution model version mismatch")
        if self.spec.cost_model_version != cost_model_version(
            self.config.backtest, self.funding_provider.model_version
        ):
            raise DomainValidationError("configured cost model version mismatch")
        if self.spec.initial_equity != self.config.backtest.initial_equity:
            raise DomainValidationError("initial equity does not match backtest config")
        if self.spec.versions.strategy_version != self.config.strategy.version:
            raise DomainValidationError("strategy version mismatch")
        if self.spec.start_time < self.metadata.effective_at:
            raise DomainValidationError("instrument metadata is not effective at run start")
        if not candles_m5 or any(
            candle.symbol != self.spec.symbol
            or candle.timeframe is not Timeframe.M5
            or candle.data_version != self.spec.historical_versions.m5_data_version
            for candle in candles_m5
        ):
            raise DomainValidationError("M5 clock identity/version mismatch")
        open_times = tuple(candle.open_time for candle in candles_m5)
        if open_times != tuple(sorted(open_times)) or len(set(open_times)) != len(open_times):
            raise DomainValidationError("M5 clock must be strictly ordered")
        if any(
            candle.close_time - candle.open_time != timedelta(minutes=5) for candle in candles_m5
        ):
            raise DomainValidationError("M5 clock contains an invalid interval")
        if any(
            current.open_time != previous.close_time for previous, current in pairwise(candles_m5)
        ):
            raise DomainValidationError("M5 clock contains a gap")
        if len({item.decision.as_of for item in evaluations}) != len(evaluations):
            raise DomainValidationError("duplicate strategy evaluations")
        if any(
            item.decision.versions.data_version
            != self.spec.historical_versions.snapshot_data_version
            for item in evaluations
        ):
            raise DomainValidationError("evaluation snapshot composite version mismatch")
        if any(
            item.decision.symbol != self.spec.symbol
            or item.decision.as_of < self.spec.start_time
            or item.decision.as_of > self.spec.end_time
            or item.decision.as_of.second != 0
            or item.decision.as_of.microsecond != 0
            or item.decision.as_of.minute % 15 != 0
            for item in evaluations
        ):
            raise DomainValidationError("strategy evaluations must be in-range M15 close events")
        if any(
            item.candidate is not None
            and (
                item.candidate.candidate_id != item.decision.candidate_id
                or item.candidate.created_at != item.decision.as_of
                or item.candidate.symbol != self.spec.symbol
                or item.candidate.versions != item.decision.versions
            )
            for item in evaluations
        ):
            raise DomainValidationError("candidate/evaluation identity mismatch")
