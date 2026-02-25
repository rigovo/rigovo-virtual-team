"""LLM provider factory — creates providers for given models."""

from __future__ import annotations

from rigovo.config import LLMConfig
from rigovo.domain.interfaces.llm_provider import LLMProvider


class LLMProviderFactory:
    """
    Creates and caches LLM provider instances.

    Strategy Pattern: selects the correct provider implementation
    based on model name and configuration.
    """

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._cache: dict[str, LLMProvider] = {}

    def get(self, model: str | None = None) -> LLMProvider:
        """Get an LLM provider for a given model. Lazy-init and cached."""
        model = model or self._config.model
        if model not in self._cache:
            self._cache[model] = self._create(model)
        return self._cache[model]

    def _create(self, model: str) -> LLMProvider:
        """Create an LLM provider for a specific model."""
        provider = self._config.provider

        if provider == "anthropic" or model.startswith("claude"):
            from rigovo.infrastructure.llm.anthropic_provider import (
                AnthropicProvider,
            )
            return AnthropicProvider(
                api_key=self._config.anthropic_api_key,
                model=model,
            )
        elif provider == "openai" or model.startswith(("gpt", "o1")):
            from rigovo.infrastructure.llm.openai_provider import OpenAIProvider
            return OpenAIProvider(
                api_key=self._config.openai_api_key,
                model=model,
            )
        else:
            raise ValueError(
                f"Unsupported LLM provider for model '{model}'. "
                f"Supported: anthropic (claude-*), openai (gpt-*, o1-*)"
            )
