"""Versioned deterministic identifiers."""

from __future__ import annotations

from hashlib import sha256
from typing import Any

from trading_bot.domain.enums import OrderPurpose, SetupType, TradeSide
from trading_bot.domain.primitives import canonical_json


def deterministic_id(namespace: str, *parts: Any) -> str:
    payload = canonical_json({"namespace": namespace, "version": 1, "parts": parts})
    return sha256(payload.encode("utf-8")).hexdigest()


def evaluation_id(symbol: str, close_time: Any, strategy_version: str, config_version: str) -> str:
    return deterministic_id("evaluation", symbol, close_time, strategy_version, config_version)


def candidate_id(
    evaluation: str,
    side: TradeSide,
    setup: SetupType,
    entry: Any,
    stop: Any,
    targets: Any,
    assessment_id: str,
) -> str:
    return deterministic_id(
        "candidate", evaluation, side, setup, entry, stop, targets, assessment_id
    )


def trade_id(candidate: str) -> str:
    return candidate


def risk_decision_id(candidate: str, context: str, *versions: str) -> str:
    return deterministic_id("risk-decision", candidate, context, versions)


def risk_approval_id(decision: str) -> str:
    return deterministic_id("risk-approval", decision, "APPROVE")


def approved_plan_id(approval: str, plan_payload: Any, instrument_version: str) -> str:
    return deterministic_id("approved-plan", approval, plan_payload, instrument_version)


def client_order_id(plan: str, purpose: OrderPurpose, sequence: int) -> str:
    return deterministic_id("client-order", plan, purpose, sequence)


def event_id(producer: str, aggregate_id: str, event_type: str, sequence: int, payload: Any) -> str:
    return deterministic_id("event", producer, aggregate_id, event_type, sequence, payload)
