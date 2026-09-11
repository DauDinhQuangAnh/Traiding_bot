"""Secret redaction boundary; values never enter config models or hashes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SECRET_NAMES = frozenset({"OKX_API_KEY", "OKX_API_SECRET", "OKX_PASSPHRASE"})
REDACTED = "<redacted>"


def is_secret_name(name: str) -> bool:
    normalized = name.upper()
    return normalized in SECRET_NAMES or any(
        token in normalized for token in ("API_KEY", "API_SECRET", "PASSPHRASE", "PASSWORD")
    )


def redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if is_secret_name(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def without_secrets(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): without_secrets(item)
            for key, item in value.items()
            if not is_secret_name(str(key))
        }
    if isinstance(value, tuple):
        return tuple(without_secrets(item) for item in value)
    if isinstance(value, list):
        return [without_secrets(item) for item in value]
    return value
