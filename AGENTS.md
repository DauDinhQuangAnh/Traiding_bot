# Repository guidance

- Last approved phase: PHASE 6 out-of-sample validation foundation. Final commit
  `b5319eb304eaa5537843943652384b043765e80f` passed GitHub Actions run #11, job
  `python-312`, and received explicit external human approval. PHASE 7 may be implemented
  as an approval candidate but may not be marked `APPROVED` without explicit human review.
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
  `docs/phase-5-review.md`. PHASE 6 source of truth: `docs/phase-6-plan.md`,
  `docs/validation.md`, and `docs/phase-6-review.md`. PHASE 7 must preserve frozen
  PHASE 5/6 business semantics; its source of truth is `docs/phase-7-plan.md`,
  `docs/ai-benchmark.md`, and `docs/phase-7-review.md`. PHASE 7 implementation commit
  `3467a0ff0d833dd82440b5c46516794f8050b5e0` passed GitHub Actions run #12 job
  `python-312` and is `APPROVED_CANDIDATE`, not `APPROVED`, pending explicit external
  human review. AI output is observational and must never feed strategy, Risk,
  portfolio, or execution. Production datasets and generated backtest/validation/AI
  artifacts stay outside Git.
