# Repository guidance

- Last approved phase: PHASE 5 deterministic backtest foundation. Final commit
  `191fd72` passed GitHub Actions run #6 job `python-312` and received explicit external
  human approval. PHASE 6 is an implementation candidate awaiting human approval and may
  not be marked `APPROVED` without that explicit review. Its exact final-commit Python
  3.12 CI evidence is also pending.
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
- PHASE 5 source of truth: `docs/phase-5-plan.md`, `docs/backtesting.md`, and
  `docs/phase-5-review.md`. PHASE 6 is under review and must preserve the frozen PHASE 5
  business semantics. PHASE 6 source of truth: `docs/phase-6-plan.md` and
  `docs/validation.md`; review evidence is in `docs/phase-6-review.md`. Production
  datasets and generated backtest/validation artifacts stay outside Git.
