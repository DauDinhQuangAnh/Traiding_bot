"""Decimal, UTC and canonical serialization policy."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, TypeVar

from trading_bot.domain.errors import DomainValidationError

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")
_T = TypeVar("_T")
_DURATION_RE = re.compile(r"^(?P<value>[0-9]+(?:\.[0-9]+)?)(?P<unit>ms|s|m|h|d)$")


def decimal_value(value: Decimal | str | int) -> Decimal:
    """Parse Decimal losslessly and reject binary floats and booleans."""
    if isinstance(value, (bool, float)):
        raise DomainValidationError("Decimal input must not be bool or float")
    result = value if isinstance(value, Decimal) else Decimal(str(value))
    if not result.is_finite():
        raise DomainValidationError("Decimal value must be finite")
    return result


def require_non_empty(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise DomainValidationError(f"{field_name} must be non-empty")


def require_finite(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise DomainValidationError(f"{field_name} must be a finite Decimal")


def require_positive(value: Decimal, field_name: str) -> None:
    require_finite(value, field_name)
    if value <= ZERO:
        raise DomainValidationError(f"{field_name} must be positive")


def require_non_negative(value: Decimal, field_name: str) -> None:
    require_finite(value, field_name)
    if value < ZERO:
        raise DomainValidationError(f"{field_name} must be non-negative")


def require_ratio(value: Decimal, field_name: str, *, positive: bool = False) -> None:
    require_finite(value, field_name)
    lower_ok = value > ZERO if positive else value >= ZERO
    if not lower_ok or value > ONE:
        left = "(0" if positive else "[0"
        raise DomainValidationError(f"{field_name} must be in {left},1]")


def require_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainValidationError(f"{field_name} must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise DomainValidationError(f"{field_name} must be normalized UTC")
    return value.astimezone(UTC)


def freeze_mapping(mapping: Mapping[_T, Any]) -> Mapping[_T, Any]:
    return MappingProxyType(dict(mapping))


def floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    require_non_negative(value, "value")
    require_positive(step, "step")
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def ceil_to_step(value: Decimal, step: Decimal) -> Decimal:
    require_non_negative(value, "value")
    require_positive(step, "step")
    return (value / step).to_integral_value(rounding=ROUND_CEILING) * step


def parse_duration(value: str | int | Decimal | timedelta) -> timedelta:
    if isinstance(value, timedelta):
        return value
    if isinstance(value, bool):
        raise DomainValidationError("duration must not be bool")
    if isinstance(value, int):
        return timedelta(seconds=value)
    raw = str(value).strip()
    match = _DURATION_RE.fullmatch(raw)
    if match is None:
        raise DomainValidationError(f"invalid duration: {raw}")
    amount = decimal_value(match.group("value"))
    scale = {
        "ms": Decimal("0.001"),
        "s": ONE,
        "m": Decimal("60"),
        "h": Decimal("3600"),
        "d": Decimal("86400"),
    }[match.group("unit")]
    with localcontext() as context:
        context.prec = 34
        microseconds = (amount * scale * Decimal("1000000")).to_integral_exact()
    return timedelta(microseconds=int(microseconds))


def canonical_data(value: Any) -> Any:
    """Convert supported values to a deterministic JSON-compatible structure."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise DomainValidationError("cannot serialize non-finite Decimal")
        return format(value, "f")
    if isinstance(value, datetime):
        normalized = require_utc(value, "datetime")
        return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, timedelta):
        microseconds = value // timedelta(microseconds=1)
        return f"PT{microseconds}US"
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return value.as_posix()
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: canonical_data(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {
            str(key.value if isinstance(key, Enum) else key): canonical_data(item)
            for key, item in sorted(
                value.items(), key=lambda pair: str(getattr(pair[0], "value", pair[0]))
            )
        }
    if isinstance(value, (tuple, list)):
        return [canonical_data(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(canonical_data(item) for item in value)
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise DomainValidationError(f"unsupported canonical type: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        canonical_data(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
