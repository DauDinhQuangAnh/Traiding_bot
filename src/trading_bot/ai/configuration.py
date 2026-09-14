"""Conversion from typed application config to secret-free provider specifications."""

from __future__ import annotations

from trading_bot.ai.models import AIProjectionLimits, AIProvider, AIProviderSpec
from trading_bot.config.models import AIConfig


def projection_limits(config: AIConfig) -> AIProjectionLimits:
    return AIProjectionLimits(
        config.max_candles_per_timeframe,
        config.max_observations,
        config.max_reason_codes,
        config.max_text_length,
    )


def provider_specs(config: AIConfig) -> tuple[AIProviderSpec, ...]:
    return tuple(
        AIProviderSpec(
            provider=provider,
            model=item.model,
            temperature=item.temperature,
            max_output_tokens=item.max_output_tokens,
            timeout=item.timeout,
            max_attempts=item.max_attempts,
            initial_backoff=item.initial_backoff,
            backoff_multiplier=item.backoff_multiplier,
            maximum_backoff=item.maximum_backoff,
            provider_config_version=item.config_version,
            enabled=config.enabled and item.enabled,
        )
        for provider in AIProvider
        for item in (config.providers[provider.value],)
    )
