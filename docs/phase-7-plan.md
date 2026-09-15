# PHASE 7 Plan — Multi-Provider AI Benchmark and Advisory Layer

## 1. Objective

PHASE 7 builds a deterministic, offline-first evidence framework for comparing structured
AI analyses from OpenAI, Anthropic, and Gemini against the frozen strategy decision and
regime. The layer is advisory and observational only. It measures response validity,
agreement, divergence, confidence, and provider failures without ranking a provider or
changing any trading outcome.

## 2. Trust boundary

The dependency direction is one way:

```text
persisted point-in-time market/strategy evidence
  -> bounded AI evidence projection
  -> versioned request/prompt
  -> AIAnalystPort
  -> typed response/failure
  -> benchmark metrics and append-only evidence
  -> GET/HEAD-only dashboard
```

There is no reverse edge into indicators, regime detection, strategy, candidate creation,
Risk Engine, portfolio, backtest execution, exchange execution, configuration mutation, or
order state. AI cannot create `TradeCandidate`, `RiskDecision`, `ApprovedTradePlan`, or
`OrderRequest`; approve a rejected trade; change size/leverage/stops/targets; or submit or
cancel an order.

## 3. Non-goals

PHASE 7 does not add provider SDKs or production network adapters, store credentials,
enable AI by default, add OKX connectivity, start Demo/Live trading, optimize strategy,
select a winning provider, tune prompts from TEST profitability, predict PnL, expose chain
of thought, or claim trading edge. Real provider adapters remain blocked until their API
contracts are separately verified and approved.

## 4. Canonical point-in-time evidence

`AIMarketEvidence` is model-visible and contains only symbol, UTC `as_of`, bounded
closed-candle contexts for exactly M5/M15/H1, and typed indicator/regime/level/range/signal
observations. `AIBenchmarkReference` separately contains the frozen reference decision,
regime, reason codes, and optional setup. Reference labels are never sent to providers.
Every observation carries an `observed_at <= as_of`. Every candle is closed and has
`close_time <= as_of`.

Outcome fields do not exist in the projection: no future candle, exit, PnL, MFE, MAE,
winner label, subsequent fill, or post-`as_of` observation can be serialized. Projection
limits bound candle count, observation count, reason count, and text length. Reordering
semantically unordered observations produces one canonical order.

## 5. Request contract

`AIAnalysisRequest` binds its content-derived ID to:

- canonical evidence and evidence-projection version;
- code, strategy, app-config, historical M5/M15/H1/snapshot, and instrument versions;
- prompt template version and response schema version.

No provider or model belongs to request identity because the same evidence request is
compared across providers. The request validates its own ID and rejects missing versions,
future evidence, duplicate observations, unsupported timeframes, and oversized payloads.
Changing only a benchmark reference leaves `request_id` and prompt bytes unchanged while
changing case, case-set, and protocol identities.

## 6. Provider and invocation contracts

`AIProviderSpec` is immutable and identifies provider, exact model string, temperature,
maximum output tokens, timeout, maximum attempts, deterministic bounded backoff policy,
provider-config version, and enabled state. OpenAI, Anthropic, and Gemini are the only
initial typed providers. All example providers and global AI configuration are disabled by
default.

`AIProviderInvocation` binds request, provider specification, and explicit invocation
sequence. It distinguishes a deliberate repeat without wall time or UUIDs. Provider/model
changes alter invocation identity.

`AIAnalystPort` accepts only a canonical request plus invocation and returns one typed
response. The foundation supplies a deterministic fake and a transport-neutral bounded
adapter. It performs no network I/O in tests or CI.

## 7. Prompt and schema versioning

Prompt rendering is deterministic from a registered immutable template version and the
canonical evidence projection. The prompt requests only:

- one `TradeDecision`: LONG, SHORT, or NO_TRADE;
- one `MarketRegime`;
- Decimal confidence in `[0,1]`;
- at most three concise rationale items;
- bounded typed risk flags.

It forbids chain-of-thought requests and actionable execution instructions. Prompt,
projection, and response schema versions are separate identities; changing any one creates
new request/protocol evidence.

## 8. Response contract and parser

`AIAnalysisResponse` records response ID, invocation/request/provider/model identities,
status, optional provider response ID, parsed decision/regime/confidence, concise reasons,
risk flags, prompt/projection/schema/parser versions, attempt count, and optional
input/output token counts. Provenance must match both request and protocol before metrics
or replay are accepted.

Success requires the complete strict schema. Failure requires all analytical fields to be
absent and preserves a typed sanitized status: `TIMEOUT`, `RATE_LIMIT`, `AUTH_ERROR`,
`PROVIDER_ERROR`, `INVALID_RESPONSE`, or `SCHEMA_VALIDATION_FAILED`. Provider failure is
never converted to a fabricated `NO_TRADE`. Unknown/extra executable fields and malformed
JSON fail parsing. Response identity derives only from canonical content, never wall time
or random UUID.

## 9. Retry and failure policy

Retries are bounded by the provider spec. Timeout, rate-limit, authentication, provider,
and invalid-response outcomes are normalized once at the adapter boundary. Only timeout,
rate-limit, and explicitly retryable provider failures may retry; authentication and
schema failures are terminal. Backoff values are deterministic and capped. Tests inject a
delay observer and never sleep. Error details are sanitized and never persist raw payloads,
headers, credentials, or environment values.

## 10. Benchmark cases and protocol

`AIBenchmarkCase` binds one request, one benchmark-only reference, and a stable label.
`AIBenchmarkProtocol` freezes the ordered case set, provider specifications, code/strategy/
config/historical/instrument versions, prompt/projection/schema versions, parser version,
metrics version, protocol version, and `CalculationConfig`. Provider-set/provider-order or
calculation-policy changes produce a different protocol identity. Duplicate cases,
duplicate model-visible request IDs, or duplicate provider/model pairs fail closed.

Execution is all-cases by all-enabled-providers. One provider failure does not erase other
provider evidence. The run ends `COMPLETED` or `COMPLETED_WITH_PROVIDER_FAILURES`; a
structurally invalid protocol fails before invocation. Replay accepts persisted responses
and recomputes metrics without calling a provider.

## 11. Metrics

Metrics are descriptive and retain denominators and counts:

- total case count and expected response count;
- success/failure/valid-response counts and ratios per provider;
- decision and regime agreement with the reference, including per-reference
  LONG/SHORT/NO_TRADE counts and ratios;
- provider decision rates;
- pairwise comparable-case counts, agreement/divergence counts and ratios;
- confidence sample count, average, minimum, maximum, and bounded histogram;
- parse/schema, timeout, rate-limit, authentication, and provider-error counts;
- optional aggregate token counts only when providers supplied them.

Zero denominators yield `None`, never a fabricated zero. There is no winner, score-based
selection, profitability metric, or automated feedback into prompts/strategy/config.
Pricing/cost estimation is omitted until an explicit versioned pricing configuration is
approved.

All ratios and confidence averages run inside the frozen project `calculation_context`.
Ambient Decimal precision or rounding cannot alter metrics, canonical JSON, metrics ID,
or run ID, and the caller Decimal context is restored afterward.

## 12. Persistence

SQLite uses additive append-only tables for protocols, cases, requests, invocations,
responses, runs, and metrics. Same identity plus byte-identical canonical JSON is
idempotent; same identity plus different bytes raises `PersistenceError`. No update,
delete, migration drop, or overwrite API exists. Decimal and UTC values use existing
canonical serialization. Generated benchmark databases and artifacts stay outside Git.

## 13. Dashboard

The local dashboard exposes only GET/HEAD routes for run listing, run detail, metrics,
cases, and responses. It reads persisted evidence through a query service. It has no route
that invokes a provider, accepts a credential, edits configuration, executes SQL/shell,
polls markets, or touches trading state. Unknown IDs return 404, invalid pagination 400,
and every write method 405.

## 14. Configuration and secrets

Typed `ai` configuration contains global enabled state, projection limits, and the three
provider specifications. `ai.enabled=false` and every provider `enabled=false` in the
example profile. Only environment-variable names are documented:
`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and `GEMINI_API_KEY`. Values are never loaded by the
foundation, included in config identity, logged, journaled, serialized, persisted, or
committed. Existing redaction recognizes generic API-key names.

## 15. Testing and acceptance

Required tests cover immutable validation, identity changes, provider/model collision
prevention, canonical prompt golden output, future-candle/observation rejection, bounded
payloads, strict parsing, typed failures, retry caps/no real sleep, partial provider
failure, metric golden examples and empty denominators, token optionality, Decimal-context
independence, replay without network, append-only SQLite idempotency/conflicts, dashboard
read-only behavior, source-level trust-boundary audits, and secret leakage scans.

Before handoff, run all README project commands: full pytest, branch-aware coverage, Ruff
lint, Ruff format check, strict mypy, and compileall. Overall branch coverage must remain at
least 85%; practical critical PHASE 7 modules target at least 90%. The exact final commit
must pass GitHub Actions Python 3.12.

## 16. Phase status

PHASE 7 may be marked only `APPROVED_CANDIDATE` after local gates and exact-final-commit CI
pass. It cannot be marked `APPROVED` without explicit external human review. Strategy
robustness remains `NOT_EVALUATED` in the absence of an approved production validation
dataset.

PHASE 8 is not started and must not begin during PHASE 7.
