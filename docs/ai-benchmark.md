# PHASE 7 AI Benchmark and Advisory Contract

## 1. Purpose

PHASE 7 compares structured AI analysis with frozen point-in-time strategy evidence. It is
an evidence and observability subsystem, not a decision engine. Provider validity,
agreement, divergence, confidence, and failures are reportable. Provider selection,
profitability ranking, and trading authority are not.

## 2. Architecture and trust boundary

```text
PHASE 3 immutable snapshots and DecisionRecord
  -> project_market_evidence (past-only and bounded)
  -> AIAnalysisRequest (content-derived identity)
  -> AIProviderInvocation (provider/model/repeat identity)
  -> AIAnalystPort
       -> deterministic fake, or
       -> transport-neutral bounded adapter
  -> AIAnalysisResponse (strict success or typed failure)
  -> AIBenchmarkRun / metrics
  -> SQLiteAIBenchmarkRepository
  -> GET/HEAD-only dashboard
```

Imports and calls flow away from the trading path. The AI package does not import risk or
execution contracts. Provider output is never passed into indicators, levels, regime,
strategy, candidate construction, risk sizing, portfolio, backtest execution, or order
execution. Only the existing Risk Engine may create `ApprovedTradePlan`.

## 3. Evidence projection

`AIMarketEvidence` is the model-visible object. It contains:

- symbol and UTC `as_of`;
- bounded, closed M5/M15/H1 OHLCV candles;
- typed Decimal/string/bool observations for indicators, regime, levels, range, and
  signals, each with `observed_at` and a source ID;

`AIBenchmarkReference` is a separate benchmark-only object containing reference decision,
reference regime, reason codes, and optional setup. Those fields, their aliases, and the
case label are never serialized into a provider prompt. Deterministic regime confidence
may remain visible as `detected_regime_confidence` because it is a point-in-time feature,
not the benchmark regime label.

Each timeframe must exist. Candles are unique and strictly ordered within their timeframe;
every close and observation time is at or before `as_of`. Projection limits independently
bound candles per timeframe, observations, reasons, and text. Canonical projection sorts
observations by category/name/source.

Outcome data has no field in the model: future candles, fills, exits, PnL, MFE, MAE,
winner labels, and subsequent outcomes cannot be included. A future item fails object
construction rather than being silently removed.

## 4. Request identity

`request_id` is SHA-256 over canonical serialization of model-visible evidence, code version, strategy
version, app-config version, exact historical M5/M15/H1 and composite version set,
instrument version, prompt version, projection version, response schema version, and
projection limits. The immutable request recalculates and validates its identity.

Provider/model is deliberately absent from request identity so all providers receive the
same logical input. Benchmark reference is also absent: changing only that reference keeps
the request ID and prompt byte-identical while changing case and protocol IDs. Duplicate
request IDs are forbidden within one protocol to prevent conflicting-label ambiguity.

## 5. Providers

Typed providers are `OPENAI`, `ANTHROPIC`, and `GEMINI`. Each `AIProviderSpec` records:

- exact model label supplied by the experiment owner;
- Decimal temperature and output-token bound;
- timeout and maximum attempt count;
- deterministic initial/multiplier/maximum backoff;
- provider-config version and enabled state.

Example model labels are explicitly unconfigured placeholders, not claims about current
vendor models. Global AI and all provider specs default disabled. There are no vendor SDK
dependencies and no production HTTP adapter. Real adapters remain blocked until vendor
wire contracts are independently verified and approved.

`AIProviderInvocation` binds request ID, the complete provider spec, and a non-negative
invocation sequence. A repeat uses a new explicit sequence; wall time and UUIDs never enter
identity.

## 6. Prompt contract

The registered V1 prompt is rendered deterministically from canonical evidence. It asks
for exactly one decision, regime, Decimal confidence, up to three concise reasons, and
bounded risk flags. It explicitly forbids future/outcome inference, PnL, sizing, leverage,
stops, targets, order/execution instructions, hidden reasoning, and chain of thought.

Prompt version, evidence-projection version, response-schema version, and parser version
are registered V1 constants. Unregistered request versions fail before invoking a provider.

## 7. Response and parser

The strict V1 JSON schema has exactly these keys:

```json
{
  "decision": "LONG | SHORT | NO_TRADE",
  "regime": "TREND_UP | TREND_DOWN | SIDEWAY | HIGH_VOLATILITY | UNCERTAIN",
  "confidence": "Decimal string in [0,1]",
  "reasons": ["at most three concise items"],
  "risk_flags": ["bounded typed labels"]
}
```

Extra fields—including execution-like fields—are invalid. Floats are not accepted for
confidence because binary float parsing would violate lossless Decimal policy. Malformed
JSON becomes `INVALID_RESPONSE`; valid JSON with invalid typed content becomes
`SCHEMA_VALIDATION_FAILED`.

A `SUCCESS` response requires decision, regime, and confidence. Any failure requires
those fields to be `None`, analytical text to be empty, and a sanitized error code. Failure
is never represented as `NO_TRADE`. Response identity binds invocation/request/provider/
model, parsed content, prompt/projection/schema/parser provenance, attempts, optional
provider response ID and optional token usage. Replay requires provenance to match both
request and protocol. It excludes wall time, latency, raw payloads, and random IDs.

## 8. Failure and retry semantics

The transport-neutral adapter maps declared transport exceptions to `TIMEOUT`,
`RATE_LIMIT`, `AUTH_ERROR`, or `PROVIDER_ERROR`. Timeout, rate limit, and explicitly
retryable provider errors retry only within `max_attempts`. Authentication, non-retryable
provider errors, parser failures, and schema failures are terminal. Backoff is Decimal-
derived, deterministic, and capped. The injected delay observer defaults to a no-op; tests
never sleep.

Unexpected programming errors are not swallowed. Raw exception messages, request headers,
provider payloads, and secrets are not stored in the response.

## 9. Benchmark protocol and execution

`AIBenchmarkCase` binds one request, benchmark-only reference, and label. Ordered case IDs
form `case_set_id`.
`AIBenchmarkProtocol` freezes ordered cases, ordered provider specs, all semantic versions,
parser version, metrics version, and exact `CalculationConfig`. Reordering/changing cases,
providers, references, or calculation policy changes the protocol ID. Duplicate case IDs,
duplicate model-visible request IDs, and duplicate provider/model pairs fail validation.

Execution traverses cases then enabled provider specs in declaration order. Missing ports
for an enabled provider fail before that invocation. Each invoked provider must return a
typed response. Provider failure remains a row and does not erase successful rows from
other providers. A pure assembly path recalculates the complete run from persisted
invocations/responses and performs no provider call.

## 10. Metrics

Every provider reports case/success/failure counts, valid response rate, reference decision
and regime agreement, per-reference LONG/SHORT/NO_TRADE agreement, output decision counts
and rates, typed failure counts, confidence count/average/min/max/five fixed buckets, and
optional token totals. Token totals are `None` unless all successful responses for that
provider supplied the field.

Every provider pair reports mutually successful comparable-case count plus decision and
regime agreement/divergence counts and ratios. A zero denominator returns `None`. Overall
success/failure counts reconcile exactly with cases times enabled providers.

Metrics do not contain winner, rank, recommendation, PnL, return, or a feedback action.
Provider pricing is `None`/not implemented until an explicit immutable pricing policy is
approved.

All ratios and confidence averages execute under the protocol's scoped project
`calculation_context`. Non-terminating values such as `1/3` and `1.1/3` are independent of
ambient Decimal precision/rounding, and the outer context is not mutated.

## 11. Persistence and replay

SQLite tables are additive and append-only for protocols, requests, cases, invocations,
responses, metrics, runs, and ordered run links. Canonical JSON is stored losslessly. Same
ID and same bytes is idempotent. Same ID and different content raises `PersistenceError`
and rolls back the transaction. There is no update, delete, or table-drop operation.

Cases are content-addressed independently of protocols, allowing the same evidence case to
participate in multiple provider sets without duplication or false conflict. Generated
databases remain outside Git.

The remediation changes canonical PHASE 7 request/case/protocol/response JSON and IDs.
Existing pre-production development evidence remains append-only but is not silently
rewritten and is not compatible with typed V1 remediation replay.

## 12. Dashboard

The dependency-free dashboard routes are:

- `GET|HEAD /ai-health`
- `GET|HEAD /ai-benchmark-runs`
- `GET|HEAD /ai-benchmark-runs/{run_id}`
- `GET|HEAD /ai-benchmark-runs/{run_id}/metrics`
- `GET|HEAD /ai-benchmark-runs/{run_id}/cases`
- `GET|HEAD /ai-benchmark-runs/{run_id}/responses`

Invalid pagination returns 400, missing artifacts 404, and every non-GET/HEAD method 405.
No route invokes a provider or exposes credentials, SQL, filesystem/shell, market polling,
configuration mutation, or trading controls.

## 13. Secrets

Only these environment-variable names are documented: `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, and `GEMINI_API_KEY`. The PHASE 7 foundation does not read their
values. Existing generic `API_KEY` redaction removes them from canonical config hashing,
logging helpers, and persistence inputs. Values must never enter YAML, Git, prompts,
exceptions, identities, responses, databases, or dashboards.

## 14. Limitations

No real provider API call is implemented, so the foundation proves contracts and failure
semantics but does not yet prove vendor wire compatibility. Model labels and provider
behavior can change externally. Agreement is descriptive and is not correctness,
profitability, calibration, or safety proof. Reference decisions inherit all documented
PHASE 3–6 data/model limitations. No production benchmark dataset or generated provider
evidence is committed.

Strategy robustness remains `NOT_EVALUATED`.
