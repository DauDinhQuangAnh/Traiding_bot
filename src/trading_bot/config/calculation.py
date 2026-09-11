"""Scoped Decimal arithmetic policy for deterministic domain calculations."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import ROUND_HALF_EVEN, localcontext

from trading_bot.config.models import CalculationConfig
from trading_bot.domain.enums import DecimalRoundingMode


@contextmanager
def calculation_context(config: CalculationConfig) -> Iterator[None]:
    """Apply calculation policy without mutating the process-global Decimal context."""
    rounding_modes = {DecimalRoundingMode.ROUND_HALF_EVEN: ROUND_HALF_EVEN}
    with localcontext() as context:
        context.prec = config.decimal_precision
        context.rounding = rounding_modes[config.rounding_mode]
        yield
