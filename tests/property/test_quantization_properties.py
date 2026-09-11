from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from trading_bot.domain.primitives import floor_to_step


@given(
    value=st.integers(min_value=0, max_value=1_000_000),
    step=st.integers(min_value=1, max_value=10_000),
)
def test_floor_quantization_never_increases_value(value: int, step: int):
    amount = Decimal(value) / Decimal("100")
    quantum = Decimal(step) / Decimal("100")
    result = floor_to_step(amount, quantum)
    assert Decimal(0) <= result <= amount
    assert result % quantum == 0
