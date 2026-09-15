"""Immutable, provider-independent AI benchmark contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum, unique

from trading_bot.ai.versions import (
    PARSER_VERSION,
    PROJECTION_VERSION,
    PROMPT_VERSION,
    SCHEMA_VERSION,
)
from trading_bot.config.models import CalculationConfig
from trading_bot.domain.enums import MarketRegime, ReasonCode, SetupType, Timeframe, TradeDecision
from trading_bot.domain.errors import DomainValidationError
from trading_bot.domain.identifiers import deterministic_id
from trading_bot.domain.primitives import (
    require_finite,
    require_non_empty,
    require_non_negative,
    require_positive,
    require_ratio,
    require_utc,
)
from trading_bot.historical.models import HistoricalVersionSet


@unique
class AIProvider(StrEnum):
    OPENAI = "OPENAI"
    ANTHROPIC = "ANTHROPIC"
    GEMINI = "GEMINI"


@unique
class AIResponseStatus(StrEnum):
    SUCCESS = "SUCCESS"
    TIMEOUT = "TIMEOUT"
    RATE_LIMIT = "RATE_LIMIT"
    AUTH_ERROR = "AUTH_ERROR"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    SCHEMA_VALIDATION_FAILED = "SCHEMA_VALIDATION_FAILED"


_AI_ERROR_CODES = frozenset(
    {
        "TIMEOUT",
        "RATE_LIMIT",
        "AUTH_ERROR",
        "PROVIDER_ERROR",
        "PROVIDER_DISABLED",
        "MALFORMED_JSON",
        "UNEXPECTED_RESPONSE_SHAPE",
        "SCHEMA_VALIDATION_FAILED",
    }
)


@unique
class AIBenchmarkRunStatus(StrEnum):
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_PROVIDER_FAILURES = "COMPLETED_WITH_PROVIDER_FAILURES"


@dataclass(frozen=True, slots=True)
class AIProjectionLimits:
    max_candles_per_timeframe: int
    max_observations: int
    max_reason_codes: int
    max_text_length: int

    def __post_init__(self) -> None:
        if not 1 <= self.max_candles_per_timeframe <= 100:
            raise DomainValidationError("max_candles_per_timeframe must be in [1,100]")
        if not 1 <= self.max_observations <= 200:
            raise DomainValidationError("max_observations must be in [1,200]")
        if not 1 <= self.max_reason_codes <= 50:
            raise DomainValidationError("max_reason_codes must be in [1,50]")
        if not 16 <= self.max_text_length <= 500:
            raise DomainValidationError("max_text_length must be in [16,500]")


@dataclass(frozen=True, slots=True)
class AICandleEvidence:
    candle_id: str
    timeframe: Timeframe
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def __post_init__(self) -> None:
        require_non_empty(self.candle_id, "candle_id")
        require_utc(self.close_time, "close_time")
        for name in ("open", "high", "low", "close"):
            require_positive(getattr(self, name), name)
        require_non_negative(self.volume, "volume")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise DomainValidationError("AI candle high/low must contain open and close")


@dataclass(frozen=True, slots=True)
class AIObservation:
    category: str
    name: str
    value: Decimal | str | bool
    observed_at: datetime
    source_id: str

    def __post_init__(self) -> None:
        if self.category not in {"INDICATOR", "REGIME", "LEVEL", "RANGE", "SIGNAL"}:
            raise DomainValidationError("unsupported AI observation category")
        require_non_empty(self.name, "observation name")
        require_non_empty(self.source_id, "observation source_id")
        require_utc(self.observed_at, "observed_at")
        if isinstance(self.value, Decimal):
            require_finite(self.value, "observation value")
        elif isinstance(self.value, str):
            require_non_empty(self.value, "observation value")
        elif not isinstance(self.value, bool):
            raise DomainValidationError("AI observation value must be Decimal, string, or bool")


@dataclass(frozen=True, slots=True)
class AIMarketEvidence:
    symbol: str
    as_of: datetime
    candles: tuple[AICandleEvidence, ...]
    observations: tuple[AIObservation, ...]

    def __post_init__(self) -> None:
        require_non_empty(self.symbol, "symbol")
        require_utc(self.as_of, "as_of")
        if not self.candles:
            raise DomainValidationError("AI evidence requires candles")
        counts = {timeframe: 0 for timeframe in Timeframe}
        prior: dict[Timeframe, datetime] = {}
        candle_ids: set[str] = set()
        for candle in self.candles:
            if candle.close_time > self.as_of:
                raise DomainValidationError("AI evidence cannot contain a future candle")
            if candle.candle_id in candle_ids:
                raise DomainValidationError("AI evidence contains duplicate candle IDs")
            previous = prior.get(candle.timeframe)
            if previous is not None and candle.close_time <= previous:
                raise DomainValidationError("AI candles must be ordered per timeframe")
            counts[candle.timeframe] += 1
            prior[candle.timeframe] = candle.close_time
            candle_ids.add(candle.candle_id)
        if any(count == 0 for count in counts.values()):
            raise DomainValidationError("AI evidence requires M5, M15, and H1 candles")
        observation_keys: set[tuple[str, str, str]] = set()
        for observation in self.observations:
            if observation.observed_at > self.as_of:
                raise DomainValidationError("AI evidence cannot contain a future observation")
            key = (observation.category, observation.name, observation.source_id)
            if key in observation_keys:
                raise DomainValidationError("AI evidence contains duplicate observations")
            observation_keys.add(key)


@dataclass(frozen=True, slots=True)
class AIBenchmarkReference:
    reference_decision: TradeDecision
    reference_regime: MarketRegime
    reference_reason_codes: tuple[ReasonCode, ...]
    setup_type: SetupType | None

    def __post_init__(self) -> None:
        if self.reference_decision is TradeDecision.NO_TRADE and not self.reference_reason_codes:
            raise DomainValidationError("reference NO_TRADE requires reason codes")


@dataclass(frozen=True, slots=True)
class AIAnalysisRequest:
    request_id: str
    evidence: AIMarketEvidence
    code_version: str
    strategy_version: str
    config_version: str
    historical_versions: HistoricalVersionSet
    instrument_version: str
    prompt_version: str
    projection_version: str
    schema_version: str
    limits: AIProjectionLimits

    def __post_init__(self) -> None:
        for name in (
            "request_id",
            "code_version",
            "strategy_version",
            "config_version",
            "instrument_version",
            "prompt_version",
            "projection_version",
            "schema_version",
        ):
            require_non_empty(getattr(self, name), name)
        if (
            self.prompt_version != PROMPT_VERSION
            or self.projection_version != PROJECTION_VERSION
            or self.schema_version != SCHEMA_VERSION
        ):
            raise DomainValidationError("AI request uses an unregistered contract version")
        counts = {timeframe: 0 for timeframe in Timeframe}
        for candle in self.evidence.candles:
            counts[candle.timeframe] += 1
        if any(count > self.limits.max_candles_per_timeframe for count in counts.values()):
            raise DomainValidationError("AI candle projection exceeds configured bound")
        if len(self.evidence.observations) > self.limits.max_observations:
            raise DomainValidationError("AI observation projection exceeds configured bound")
        for observation in self.evidence.observations:
            if (
                isinstance(observation.value, str)
                and len(observation.value) > self.limits.max_text_length
            ):
                raise DomainValidationError("AI text observation exceeds configured bound")
        expected = deterministic_id(
            "ai-analysis-request-v1",
            self.evidence,
            self.code_version,
            self.strategy_version,
            self.config_version,
            self.historical_versions,
            self.instrument_version,
            self.prompt_version,
            self.projection_version,
            self.schema_version,
            self.limits,
        )
        if self.request_id != expected:
            raise DomainValidationError("request_id does not match AI request content")


@dataclass(frozen=True, slots=True)
class AIProviderSpec:
    provider: AIProvider
    model: str
    temperature: Decimal
    max_output_tokens: int
    timeout: timedelta
    max_attempts: int
    initial_backoff: timedelta
    backoff_multiplier: Decimal
    maximum_backoff: timedelta
    provider_config_version: str
    enabled: bool

    def __post_init__(self) -> None:
        require_non_empty(self.model, "model")
        require_non_empty(self.provider_config_version, "provider_config_version")
        require_non_negative(self.temperature, "temperature")
        if self.temperature > Decimal("2"):
            raise DomainValidationError("temperature must not exceed 2")
        if self.max_output_tokens <= 0:
            raise DomainValidationError("max_output_tokens must be positive")
        if self.timeout <= timedelta(0):
            raise DomainValidationError("timeout must be positive")
        if not 1 <= self.max_attempts <= 10:
            raise DomainValidationError("max_attempts must be in [1,10]")
        if self.initial_backoff <= timedelta(0):
            raise DomainValidationError("initial_backoff must be positive")
        require_finite(self.backoff_multiplier, "backoff_multiplier")
        if self.backoff_multiplier < Decimal("1"):
            raise DomainValidationError("backoff_multiplier must be at least one")
        if self.maximum_backoff < self.initial_backoff:
            raise DomainValidationError("maximum_backoff must not be below initial_backoff")


@dataclass(frozen=True, slots=True)
class AIProviderInvocation:
    invocation_id: str
    request_id: str
    provider_spec: AIProviderSpec
    invocation_sequence: int

    def __post_init__(self) -> None:
        require_non_empty(self.request_id, "request_id")
        if self.invocation_sequence < 0:
            raise DomainValidationError("invocation_sequence must be non-negative")
        expected = deterministic_id(
            "ai-provider-invocation-v1",
            self.request_id,
            self.provider_spec,
            self.invocation_sequence,
        )
        if self.invocation_id != expected:
            raise DomainValidationError("invocation_id does not match invocation content")


@dataclass(frozen=True, slots=True)
class AIAnalysisResponse:
    response_id: str
    invocation_id: str
    request_id: str
    provider: AIProvider
    model: str
    status: AIResponseStatus
    decision: TradeDecision | None
    regime: MarketRegime | None
    confidence: Decimal | None
    reasons: tuple[str, ...]
    risk_flags: tuple[str, ...]
    provider_response_id: str | None
    prompt_version: str
    projection_version: str
    schema_version: str
    parser_version: str
    attempts: int
    input_tokens: int | None
    output_tokens: int | None
    error_code: str | None

    def __post_init__(self) -> None:
        for name in (
            "response_id",
            "invocation_id",
            "request_id",
            "model",
            "prompt_version",
            "projection_version",
            "schema_version",
            "parser_version",
        ):
            require_non_empty(getattr(self, name), name)
        if (
            self.prompt_version != PROMPT_VERSION
            or self.projection_version != PROJECTION_VERSION
            or self.schema_version != SCHEMA_VERSION
            or self.parser_version != PARSER_VERSION
        ):
            raise DomainValidationError("AI response uses unregistered provenance")
        if self.attempts <= 0:
            raise DomainValidationError("response attempts must be positive")
        if self.provider_response_id is not None:
            require_non_empty(self.provider_response_id, "provider_response_id")
            if len(self.provider_response_id) > 240:
                raise DomainValidationError("provider_response_id must be at most 240 chars")
        for name in ("input_tokens", "output_tokens"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise DomainValidationError(f"{name} must be non-negative")
        if len(self.reasons) > 3:
            raise DomainValidationError("AI response accepts at most three reasons")
        if len(self.risk_flags) > 10:
            raise DomainValidationError("AI response accepts at most ten risk flags")
        if any(not item.strip() or len(item) > 240 for item in self.reasons):
            raise DomainValidationError("AI reasons must be non-empty and at most 240 chars")
        if any(not item.strip() or len(item) > 80 for item in self.risk_flags):
            raise DomainValidationError("AI risk flags must be non-empty and at most 80 chars")
        if self.status is AIResponseStatus.SUCCESS:
            if self.decision is None or self.regime is None or self.confidence is None:
                raise DomainValidationError("successful AI response requires complete analysis")
            require_ratio(self.confidence, "confidence")
            if self.error_code is not None:
                raise DomainValidationError("successful AI response cannot have an error code")
        else:
            if any(value is not None for value in (self.decision, self.regime, self.confidence)):
                raise DomainValidationError("failed AI response cannot contain analysis")
            if self.reasons or self.risk_flags:
                raise DomainValidationError("failed AI response cannot contain analytical text")
            if self.error_code is None:
                raise DomainValidationError("failed AI response requires a sanitized error code")
            if self.error_code not in _AI_ERROR_CODES:
                raise DomainValidationError("failed AI response error code is not canonical")
        expected = deterministic_id(
            "ai-analysis-response-v1",
            self.invocation_id,
            self.request_id,
            self.provider,
            self.model,
            self.status,
            self.decision,
            self.regime,
            self.confidence,
            self.reasons,
            self.risk_flags,
            self.provider_response_id,
            self.prompt_version,
            self.projection_version,
            self.schema_version,
            self.parser_version,
            self.attempts,
            self.input_tokens,
            self.output_tokens,
            self.error_code,
        )
        if self.response_id != expected:
            raise DomainValidationError("response_id does not match AI response content")


@dataclass(frozen=True, slots=True)
class AIBenchmarkCase:
    case_id: str
    request: AIAnalysisRequest
    reference: AIBenchmarkReference
    label: str

    def __post_init__(self) -> None:
        require_non_empty(self.label, "case label")
        if len(self.reference.reference_reason_codes) > self.request.limits.max_reason_codes:
            raise DomainValidationError("AI reference reason projection exceeds configured bound")
        expected = deterministic_id(
            "ai-benchmark-case-v1", self.request, self.reference, self.label
        )
        if self.case_id != expected:
            raise DomainValidationError("case_id does not match benchmark case content")


@dataclass(frozen=True, slots=True)
class AIBenchmarkProtocol:
    protocol_id: str
    protocol_version: str
    case_set_id: str
    case_ids: tuple[str, ...]
    request_ids: tuple[str, ...]
    provider_specs: tuple[AIProviderSpec, ...]
    code_version: str
    strategy_version: str
    config_version: str
    historical_versions: HistoricalVersionSet
    instrument_version: str
    prompt_version: str
    projection_version: str
    schema_version: str
    parser_version: str
    metrics_version: str
    calculation: CalculationConfig

    def __post_init__(self) -> None:
        for name in (
            "protocol_id",
            "protocol_version",
            "case_set_id",
            "code_version",
            "strategy_version",
            "config_version",
            "instrument_version",
            "prompt_version",
            "projection_version",
            "schema_version",
            "parser_version",
            "metrics_version",
        ):
            require_non_empty(getattr(self, name), name)
        if not self.case_ids or len(set(self.case_ids)) != len(self.case_ids):
            raise DomainValidationError("benchmark case IDs must be non-empty and unique")
        if len(self.request_ids) != len(self.case_ids) or len(set(self.request_ids)) != len(
            self.request_ids
        ):
            raise DomainValidationError("benchmark request IDs must cover cases and be unique")
        if (
            self.prompt_version != PROMPT_VERSION
            or self.projection_version != PROJECTION_VERSION
            or self.schema_version != SCHEMA_VERSION
            or self.parser_version != PARSER_VERSION
        ):
            raise DomainValidationError("benchmark protocol uses an unregistered contract version")
        if not self.provider_specs:
            raise DomainValidationError("benchmark protocol requires provider specs")
        provider_models = tuple((item.provider, item.model) for item in self.provider_specs)
        if len(set(provider_models)) != len(provider_models):
            raise DomainValidationError("benchmark provider/model pairs must be unique")
        expected_case_set = deterministic_id("ai-benchmark-case-set-v1", self.case_ids)
        if self.case_set_id != expected_case_set:
            raise DomainValidationError("case_set_id does not match ordered cases")
        expected = deterministic_id(
            "ai-benchmark-protocol-v1",
            self.protocol_version,
            self.case_set_id,
            self.request_ids,
            self.provider_specs,
            self.code_version,
            self.strategy_version,
            self.config_version,
            self.historical_versions,
            self.instrument_version,
            self.prompt_version,
            self.projection_version,
            self.schema_version,
            self.parser_version,
            self.metrics_version,
            self.calculation,
        )
        if self.protocol_id != expected:
            raise DomainValidationError("protocol_id does not match benchmark protocol content")


@dataclass(frozen=True, slots=True)
class AIReferenceDecisionMetrics:
    reference_decision: TradeDecision
    comparable_count: int
    agreement_count: int
    agreement_rate: Decimal | None

    def __post_init__(self) -> None:
        if self.comparable_count < 0 or not 0 <= self.agreement_count <= self.comparable_count:
            raise DomainValidationError("invalid reference-decision metric counts")
        if self.agreement_rate is not None:
            require_ratio(self.agreement_rate, "reference decision agreement_rate")
        if (self.comparable_count == 0) != (self.agreement_rate is None):
            raise DomainValidationError("reference decision rate/denominator mismatch")


@dataclass(frozen=True, slots=True)
class AIProviderMetrics:
    provider: AIProvider
    model: str
    case_count: int
    success_count: int
    failure_count: int
    valid_response_rate: Decimal | None
    decision_agreement_count: int
    decision_agreement_rate: Decimal | None
    regime_agreement_count: int
    regime_agreement_rate: Decimal | None
    long_count: int
    short_count: int
    no_trade_count: int
    long_rate: Decimal | None
    short_rate: Decimal | None
    no_trade_rate: Decimal | None
    reference_decision_metrics: tuple[AIReferenceDecisionMetrics, ...]
    timeout_count: int
    rate_limit_count: int
    auth_error_count: int
    provider_error_count: int
    invalid_response_count: int
    schema_failure_count: int
    confidence_count: int
    average_confidence: Decimal | None
    minimum_confidence: Decimal | None
    maximum_confidence: Decimal | None
    confidence_buckets: tuple[int, int, int, int, int]
    input_tokens: int | None
    output_tokens: int | None

    def __post_init__(self) -> None:
        require_non_empty(self.model, "metrics model")
        counts = (
            self.case_count,
            self.success_count,
            self.failure_count,
            self.decision_agreement_count,
            self.regime_agreement_count,
            self.long_count,
            self.short_count,
            self.no_trade_count,
            self.timeout_count,
            self.rate_limit_count,
            self.auth_error_count,
            self.provider_error_count,
            self.invalid_response_count,
            self.schema_failure_count,
            self.confidence_count,
        )
        if any(value < 0 for value in counts):
            raise DomainValidationError("provider metric counts must be non-negative")
        if self.success_count + self.failure_count != self.case_count:
            raise DomainValidationError("provider success/failure counts must cover cases")
        if self.long_count + self.short_count + self.no_trade_count != self.success_count:
            raise DomainValidationError("provider decision counts must cover successes")
        if tuple(item.reference_decision for item in self.reference_decision_metrics) != tuple(
            TradeDecision
        ):
            raise DomainValidationError("provider requires ordered reference-decision metrics")
        if self.confidence_count != self.success_count:
            raise DomainValidationError("provider confidence count must equal successes")
        for name in (
            "valid_response_rate",
            "decision_agreement_rate",
            "regime_agreement_rate",
            "long_rate",
            "short_rate",
            "no_trade_rate",
        ):
            value = getattr(self, name)
            if value is not None:
                require_ratio(value, name)
        decision_rates = (self.long_rate, self.short_rate, self.no_trade_rate)
        if self.success_count == 0 and any(value is not None for value in decision_rates):
            raise DomainValidationError("empty decision sample must use None rates")
        if self.success_count > 0 and any(value is None for value in decision_rates):
            raise DomainValidationError("decision sample requires all decision rates")
        confidence_values = (
            self.average_confidence,
            self.minimum_confidence,
            self.maximum_confidence,
        )
        if self.confidence_count == 0 and any(value is not None for value in confidence_values):
            raise DomainValidationError("empty confidence sample must use None summaries")
        if self.confidence_count > 0:
            if any(value is None for value in confidence_values):
                raise DomainValidationError("confidence sample requires complete summary")
            for value in confidence_values:
                assert value is not None
                require_ratio(value, "confidence summary")
        if any(value < 0 for value in self.confidence_buckets):
            raise DomainValidationError("confidence buckets must be non-negative")
        if sum(self.confidence_buckets) != self.confidence_count:
            raise DomainValidationError("confidence buckets must cover confidence sample")
        for name in ("input_tokens", "output_tokens"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise DomainValidationError(f"{name} must be non-negative")


@dataclass(frozen=True, slots=True)
class AIPairwiseMetrics:
    left_provider: AIProvider
    left_model: str
    right_provider: AIProvider
    right_model: str
    comparable_count: int
    decision_agreement_count: int
    decision_divergence_count: int
    decision_agreement_rate: Decimal | None
    regime_agreement_count: int
    regime_divergence_count: int
    regime_agreement_rate: Decimal | None

    def __post_init__(self) -> None:
        require_non_empty(self.left_model, "left_model")
        require_non_empty(self.right_model, "right_model")
        if self.comparable_count < 0:
            raise DomainValidationError("pairwise comparable_count must be non-negative")
        if self.decision_agreement_count + self.decision_divergence_count != self.comparable_count:
            raise DomainValidationError("pairwise decision counts must cover comparable cases")
        if self.regime_agreement_count + self.regime_divergence_count != self.comparable_count:
            raise DomainValidationError("pairwise regime counts must cover comparable cases")
        for name in ("decision_agreement_rate", "regime_agreement_rate"):
            value = getattr(self, name)
            if value is not None:
                require_ratio(value, name)


@dataclass(frozen=True, slots=True)
class AIBenchmarkMetrics:
    metrics_id: str
    metrics_version: str
    protocol_id: str
    case_count: int
    expected_response_count: int
    success_count: int
    failure_count: int
    provider_metrics: tuple[AIProviderMetrics, ...]
    pairwise_metrics: tuple[AIPairwiseMetrics, ...]

    def __post_init__(self) -> None:
        for name in ("metrics_id", "metrics_version", "protocol_id"):
            require_non_empty(getattr(self, name), name)
        if (
            min(
                self.case_count,
                self.expected_response_count,
                self.success_count,
                self.failure_count,
            )
            < 0
        ):
            raise DomainValidationError("benchmark metric counts must be non-negative")
        if self.success_count + self.failure_count != self.expected_response_count:
            raise DomainValidationError("benchmark responses must match expected count")
        if sum(item.success_count for item in self.provider_metrics) != self.success_count:
            raise DomainValidationError("provider success totals do not reconcile")
        expected = deterministic_id(
            "ai-benchmark-metrics-v1",
            self.metrics_version,
            self.protocol_id,
            self.case_count,
            self.expected_response_count,
            self.success_count,
            self.failure_count,
            self.provider_metrics,
            self.pairwise_metrics,
        )
        if self.metrics_id != expected:
            raise DomainValidationError("metrics_id does not match benchmark metrics content")


@dataclass(frozen=True, slots=True)
class AIBenchmarkRun:
    run_id: str
    protocol: AIBenchmarkProtocol
    cases: tuple[AIBenchmarkCase, ...]
    invocations: tuple[AIProviderInvocation, ...]
    responses: tuple[AIAnalysisResponse, ...]
    metrics: AIBenchmarkMetrics
    status: AIBenchmarkRunStatus

    def __post_init__(self) -> None:
        if tuple(item.case_id for item in self.cases) != self.protocol.case_ids:
            raise DomainValidationError("benchmark run cases do not match protocol")
        if tuple(item.request.request_id for item in self.cases) != self.protocol.request_ids:
            raise DomainValidationError("benchmark run request IDs do not match protocol")
        enabled_specs = tuple(item for item in self.protocol.provider_specs if item.enabled)
        expected_invocations = tuple(
            (case.request.request_id, spec) for case in self.cases for spec in enabled_specs
        )
        actual_invocations = tuple(
            (item.request_id, item.provider_spec) for item in self.invocations
        )
        if actual_invocations != expected_invocations:
            raise DomainValidationError("benchmark invocations do not match cases/providers")
        if len({item.invocation_id for item in self.invocations}) != len(self.invocations):
            raise DomainValidationError("benchmark invocation IDs must be unique")
        if len(self.invocations) != len(self.responses):
            raise DomainValidationError("every invocation requires one typed response")
        if tuple(item.invocation_id for item in self.invocations) != tuple(
            item.invocation_id for item in self.responses
        ):
            raise DomainValidationError("benchmark response order/identity mismatch")
        requests = {case.request.request_id: case.request for case in self.cases}
        for invocation, response in zip(self.invocations, self.responses, strict=True):
            request = requests[invocation.request_id]
            if (
                response.request_id != invocation.request_id
                or response.provider is not invocation.provider_spec.provider
                or response.model != invocation.provider_spec.model
                or response.attempts > invocation.provider_spec.max_attempts
                or response.prompt_version != request.prompt_version
                or response.projection_version != request.projection_version
                or response.schema_version != request.schema_version
                or response.prompt_version != self.protocol.prompt_version
                or response.projection_version != self.protocol.projection_version
                or response.schema_version != self.protocol.schema_version
                or response.parser_version != self.protocol.parser_version
            ):
                raise DomainValidationError("benchmark response changed invocation semantics")
        if self.metrics.protocol_id != self.protocol.protocol_id:
            raise DomainValidationError("benchmark metrics protocol mismatch")
        if (
            self.metrics.case_count != len(self.cases)
            or self.metrics.expected_response_count != len(self.responses)
            or tuple((item.provider, item.model) for item in self.metrics.provider_metrics)
            != tuple((item.provider, item.model) for item in enabled_specs)
        ):
            raise DomainValidationError("benchmark metrics do not cover cases/providers")
        has_failure = any(item.status is not AIResponseStatus.SUCCESS for item in self.responses)
        expected_status = (
            AIBenchmarkRunStatus.COMPLETED_WITH_PROVIDER_FAILURES
            if has_failure
            else AIBenchmarkRunStatus.COMPLETED
        )
        if self.status is not expected_status:
            raise DomainValidationError("benchmark run status does not match responses")
        expected = deterministic_id(
            "ai-benchmark-run-v1",
            self.protocol,
            self.cases,
            self.invocations,
            self.responses,
            self.metrics,
            self.status,
        )
        if self.run_id != expected:
            raise DomainValidationError("run_id does not match benchmark run content")
