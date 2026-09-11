"""Canonical dashboard/report source serialization."""

from trading_bot.domain.primitives import canonical_json
from trading_bot.validation.models import ValidationRun


def validation_json(result: ValidationRun) -> str:
    return canonical_json(result)
