"""Canonical historical artifact serialization used by golden/replay checks."""

from __future__ import annotations

from trading_bot.domain.primitives import canonical_json
from trading_bot.historical.models import DatasetManifest, HistoricalDataset


def canonical_dataset_bytes(dataset: HistoricalDataset) -> bytes:
    return canonical_json(dataset).encode("utf-8")


def canonical_manifest_bytes(manifest: DatasetManifest) -> bytes:
    return canonical_json(manifest).encode("utf-8")
