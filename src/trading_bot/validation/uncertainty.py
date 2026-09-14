"""Deterministic descriptive bootstrap for completed trade outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256

from trading_bot.config.calculation import calculation_context
from trading_bot.config.models import CalculationConfig
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.identifiers import deterministic_id
from trading_bot.domain.primitives import ZERO
from trading_bot.validation.models import BootstrapResult


@dataclass(frozen=True, slots=True)
class BootstrapSpec:
    seed: int
    iterations: int
    minimum_trades: int

    def __post_init__(self) -> None:
        if self.seed < 0:
            raise DomainValidationError("bootstrap_seed must be non-negative")
        if self.iterations <= 0 or self.minimum_trades < 2:
            raise DomainValidationError("invalid bootstrap iteration/sample policy")


def bootstrap_trade_results(
    protocol_id: str,
    r_multiples: tuple[Decimal, ...],
    net_pnls: tuple[Decimal, ...],
    spec: BootstrapSpec,
    calculation: CalculationConfig,
) -> BootstrapResult:
    if len(r_multiples) != len(net_pnls):
        raise DomainValidationError("bootstrap R/PnL inputs must align")
    identifier = deterministic_id("trade-bootstrap-v1", protocol_id, spec, r_multiples, net_pnls)
    if len(r_multiples) < spec.minimum_trades:
        return BootstrapResult(
            identifier, spec.seed, spec.iterations, len(r_multiples), *(None,) * 9
        )
    expectancy_samples: list[Decimal] = []
    pnl_samples: list[Decimal] = []
    profit_factor_samples: list[Decimal] = []
    size = len(r_multiples)
    with calculation_context(calculation):
        for iteration in range(spec.iterations):
            indexes = tuple(_draw_index(spec.seed, iteration, draw, size) for draw in range(size))
            expectancy_samples.append(
                sum((r_multiples[index] for index in indexes), ZERO) / Decimal(size)
            )
            sampled_pnls = tuple(net_pnls[index] for index in indexes)
            pnl_samples.append(sum(sampled_pnls, ZERO))
            gross_profit = sum((value for value in sampled_pnls if value > ZERO), ZERO)
            gross_loss = abs(sum((value for value in sampled_pnls if value < ZERO), ZERO))
            if gross_loss > ZERO:
                profit_factor_samples.append(gross_profit / gross_loss)
    expectancy_samples.sort()
    pnl_samples.sort()
    profit_factor_samples.sort()
    return BootstrapResult(
        identifier,
        spec.seed,
        spec.iterations,
        size,
        _percentile(expectancy_samples, 50, 100),
        _percentile(expectancy_samples, 5, 100),
        _percentile(expectancy_samples, 95, 100),
        _percentile(pnl_samples, 50, 100),
        _percentile(pnl_samples, 5, 100),
        _percentile(pnl_samples, 95, 100),
        _percentile(profit_factor_samples, 50, 100) if profit_factor_samples else None,
        _percentile(profit_factor_samples, 5, 100) if profit_factor_samples else None,
        _percentile(profit_factor_samples, 95, 100) if profit_factor_samples else None,
    )


def _draw_index(seed: int, iteration: int, draw: int, size: int) -> int:
    payload = f"{seed}:{iteration}:{draw}".encode()
    return int.from_bytes(sha256(payload).digest()[:8], "big") % size


def _percentile(values: list[Decimal], numerator: int, denominator: int) -> Decimal:
    index = (len(values) - 1) * numerator // denominator
    return values[index]
