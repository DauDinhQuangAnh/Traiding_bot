# Local historical data

Production historical data must not be committed to Git. Put immutable source files
under `data/raw/` and reproducible canonical SQLite artifacts under `data/canonical/`
(both are ignored). Small reviewable fixtures belong under `tests/fixtures/historical/`.

Dataset locations are local runtime inputs and never participate in dataset identity.
M5 identity comes from a raw data version over SHA-256 source content and typed
raw-to-canonical semantics;
derived timeframe identity additionally includes source lineage, target timeframe and
resampling version. Full application config and code versions belong to run metadata,
not dataset identity. Copying the same bytes to another directory therefore preserves
identity; a source correction creates new M5 and transitive derived versions. Keep prior
source files/databases when old replay artifacts must remain reproducible, and back them
up by content/version rather than modification time.
