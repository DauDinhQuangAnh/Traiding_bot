# Local historical data

Production historical data must not be committed to Git. Put immutable source files
under `data/raw/` and reproducible canonical SQLite artifacts under `data/canonical/`
(both are ignored). Small reviewable fixtures belong under `tests/fixtures/historical/`.

Dataset locations are local runtime inputs and never participate in dataset identity.
Identity comes from SHA-256 source content, parser/normalization/resampling versions,
typed normalization semantics, config version, and canonical candle content. Copying
the same bytes to another directory therefore preserves identity; a source correction
creates a new data version. Keep prior source files/databases when old replay artifacts
must remain reproducible, and back them up by content/version rather than modification
time.
