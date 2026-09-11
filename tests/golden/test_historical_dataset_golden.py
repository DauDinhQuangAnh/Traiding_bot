import json
from hashlib import sha256
from pathlib import Path

from trading_bot.domain.primitives import canonical_data
from trading_bot.historical.dataset import ingest_csv_files
from trading_bot.historical.serialization import canonical_dataset_bytes, canonical_manifest_bytes

FIXTURES = Path("tests/fixtures/historical")


def test_valid_m5_dataset_matches_reviewed_golden_artifact(app_config):
    expected = json.loads((FIXTURES / "valid_m5.expected.json").read_text(encoding="utf-8"))
    result = ingest_csv_files(
        (FIXTURES / "valid_m5.csv",),
        app_config.historical,
    )
    assert result.dataset is not None and result.manifest is not None
    dataset, manifest = result.dataset, result.manifest
    actual = {
        "candle_count": dataset.candle_count,
        "canonical_hash": manifest.canonical_hash,
        "data_version": dataset.data_version,
        "dataset_bytes_sha256": sha256(canonical_dataset_bytes(dataset)).hexdigest(),
        "dataset_id": dataset.dataset_id,
        "first_candle": canonical_data(dataset.candles[0]),
        "last_candle": canonical_data(dataset.candles[-1]),
        "manifest_bytes_sha256": sha256(canonical_manifest_bytes(manifest)).hexdigest(),
        "manifest_id": manifest.manifest_id,
        "manifest_version": manifest.manifest_version,
        "raw_data_version": manifest.raw_data_version,
        "historical_semantics_version": manifest.historical_semantics_version,
    }
    assert actual == expected
