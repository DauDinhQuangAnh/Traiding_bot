# Repository guidance

- Current phase: PHASE 3 approved offline core; do not start PHASE 4 without explicit
  human approval.
- Source of truth: `README.md` and the approved documents under `docs/`, especially
  `technical-specification.md`, `domain-models.md`, `configuration.md`,
  `market-data.md`, `regime-detection.md`, `strategy.md`, `position-sizing.md`, and
  `risk-management.md`.
- Core philosophy: **NO SETUP = NO TRADE**. Missing, stale, conflicting, or uncertain
  inputs must fail closed to a canonical `NO_TRADE`, `REJECT`, or `HALT` outcome.
- Risk Engine has absolute veto authority and is the only creator of
  `ApprovedTradePlan`.
- Live trading is disabled. Do not add exchange/network SDKs, credentials, order
  submission, Demo/Live loops, or enable execution without explicit phase approval.
- Preserve deterministic Decimal/UTC/versioned behavior, explicit persisted prior
  state, append-only audit history, and replayable IDs. Add boundary and replay tests
  for every contract change.
- Before handoff, run pytest, Ruff lint, Ruff format check, mypy, and compileall using
  the project commands documented in `README.md`.
