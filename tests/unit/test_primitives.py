from decimal import Decimal

import pytest

from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.identifiers import deterministic_id
from trading_bot.domain.primitives import ceil_to_step, decimal_value, floor_to_step


def test_decimal_input_rejects_float():
    with pytest.raises(DomainValidationError):
        decimal_value(0.1)


def test_adverse_rounding_helpers():
    assert floor_to_step(Decimal("10.19"), Decimal("0.1")) == Decimal("10.1")
    assert ceil_to_step(Decimal("10.11"), Decimal("0.1")) == Decimal("10.2")


def test_deterministic_ids_depend_on_namespace():
    assert deterministic_id("a", Decimal("1.0")) == deterministic_id("a", Decimal("1.0"))
    assert deterministic_id("a", Decimal("1.0")) != deterministic_id("b", Decimal("1.0"))
