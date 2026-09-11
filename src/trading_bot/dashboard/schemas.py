"""Dependency-free DTOs for the local read-only API."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ApiResponse:
    status: int
    body: object
    headers: tuple[tuple[str, str], ...] = (("content-type", "application/json"),)
