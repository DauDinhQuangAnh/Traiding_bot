"""Modeled quote, adverse fills, fees and risk-rate projection."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from trading_bot.config.models import BacktestConfig
from trading_bot.domain.enums import LiquidityRole, OrderDirection, TradeSide
from trading_bot.domain.risk_models import InstrumentMetadata
from trading_bot.domain.value_objects import CostRateEstimate, Quote

ONE = Decimal("1")
TWO = Decimal("2")


def modeled_quote(
    symbol: str, reference_mid: Decimal, observed_at: datetime, config: BacktestConfig
) -> Quote:
    half_spread = config.modeled_spread_rate / TWO
    return Quote(
        symbol=symbol,
        source=f"MODELLED_BACKTEST:{config.spread_model_version}",
        bid=reference_mid * (ONE - half_spread),
        ask=reference_mid * (ONE + half_spread),
        event_time=observed_at,
        receive_time=observed_at,
    )


def adverse_market_fill(direction: OrderDirection, quote: Quote, slippage_rate: Decimal) -> Decimal:
    if direction is OrderDirection.BUY:
        return quote.ask * (ONE + slippage_rate)
    return quote.bid * (ONE - slippage_rate)


def adverse_stop_fill(
    side: TradeSide,
    stop_price: Decimal,
    bar_open: Decimal,
    symbol: str,
    event_time: datetime,
    config: BacktestConfig,
) -> tuple[Decimal, Decimal]:
    reference = min(stop_price, bar_open) if side is TradeSide.LONG else max(stop_price, bar_open)
    quote = modeled_quote(symbol, reference, event_time, config)
    direction = OrderDirection.SELL if side is TradeSide.LONG else OrderDirection.BUY
    return reference, adverse_market_fill(direction, quote, config.stop_slippage_rate)


def fee_for_fill(
    metadata: InstrumentMetadata,
    quantity: Decimal,
    fill_price: Decimal,
    role: LiquidityRole,
    config: BacktestConfig,
) -> Decimal:
    rate = config.maker_fee_rate if role is LiquidityRole.MAKER else config.taker_fee_rate
    return metadata.notional(quantity, fill_price) * rate


def execution_cost_estimates(
    metadata: InstrumentMetadata,
    quantity: Decimal,
    reference_price: Decimal,
    quote_side_price: Decimal,
    fill_price: Decimal,
) -> tuple[Decimal, Decimal]:
    base_quantity = metadata.base_quantity(quantity)
    spread = abs(quote_side_price - reference_price) * base_quantity
    slippage = abs(fill_price - quote_side_price) * base_quantity
    return spread, slippage


def risk_cost_rates(
    config: BacktestConfig,
    model_version: str,
    funding_debit_rate: Decimal,
) -> CostRateEstimate:
    half_spread = config.modeled_spread_rate / TWO
    entry_adversity = (ONE + half_spread) * (ONE + config.market_slippage_rate) - ONE
    stop_adversity = (ONE + half_spread) * (ONE + config.stop_slippage_rate) - ONE
    return CostRateEstimate(
        entry_fee_rate=config.taker_fee_rate,
        stop_exit_fee_rate=config.taker_fee_rate,
        target_exit_fee_rate=config.taker_fee_rate,
        entry_slippage_rate=entry_adversity,
        stop_slippage_rate=stop_adversity,
        target_slippage_rate=Decimal("0"),
        funding_debit_rate=funding_debit_rate,
        model_version=model_version,
    )
