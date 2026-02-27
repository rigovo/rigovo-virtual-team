"""LLM provider factory — creates providers for given models.

Routes to the correct SDK based on model_catalog.detect_provider():
- anthropic  → AnthropicProvider (native SDK)
- openai     → OpenAIProvider (native SDK)
- google     → OpenAIProvider with Gemini OpenAI-compat endpoint
- deepseek   → OpenAIProvider with DeepSeek base_url
- groq       → OpenAIProvider with Groq base_url
- mistral    → OpenAIProvider with Mistral base_url
- ollama     → OpenAIProvider with Ollama base_url
- openai_compatible → OpenAIProvider with user's custom base_url

All non-Anthropic providers use OpenAIProvider because they all expose
OpenAI-compatible chat completion endpoints.

Key resolution:
- Primary: ``key_resolver`` callable (reads encrypted keys from SQLite).
- Fallback: ``LLMConfig`` attributes (for CLI / CI where no DB exists).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from rigovo.config import LLMConfig
from rigovo.domain.interfaces.llm_provider import LLMProvider

logger = logging.getLogger(__name__)

# Base URLs for known providers (OpenAI-compatible endpoints)
_PROVIDER_BASE_URLS: dict[str, str] = {
    "google": "https://generativelanguage.googleapis.com/v1beta/openai",
    "deepseek": "https://api.deepseek.com",
    "groq": "https://api.groq.com/openai/v1",
    "mistral": "https://api.mistral.ai/v1",
    # ollama uses config.ollama_base_url (default http://localhost:11434)
}

# Maps provider name → settings DB key for the API key
_PROVIDER_DB_KEY: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "ollama": "",
    "openai_compatible": "OPENAI_API_KEY",
}

# Maps provider name → LLMConfig attribute (fallback for CLI)
_PROVIDER_KEY_ATTR: dict[str, str] = {
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
    "google": "google_api_key",
    "deepseek": "deepseek_api_key",
    "groq": "groq_api_key",
    "mistral": "mistral_api_key",
    "ollama": "",
    "openai_compatible": "openai_api_key",
}

# Type alias: key_resolver(db_key) → value
KeyResolver = Callable[[str], str]


class LLMProviderFactory:
    """Creates LLM provider instances.

    Providers are **not cached** — each ``get()`` call reads the latest
    API key from the settings DB so that UI key changes take effect
    immediately without restarting the engine.
    """

    def __init__(
        self,
        config: LLMConfig,
        key_resolver: KeyResolver | None = None,
    ) -> None:
        self._config = config
        self._key_resolver = key_resolver  # reads from SQLite settings

    def get(self, model: str | None = None) -> LLMProvider:
        """Create an LLM provider for a given model.

        NOT cached — always reads the latest key so Settings changes
        propagate without restarting the engine.
        """
        model = model or self._config.model
        return self._create(model)

    def _create(self, model: str) -> LLMProvider:
        from rigovo.infrastructure.llm.model_catalog import detect_provider

        provider = detect_provider(model)
        api_key = self._resolve_api_key(provider)

        if not api_key and provider not in ("ollama",):
            logger.warning(
                "No API key for provider '%s'. "
                "Set it in Settings → API Keys before creating tasks.",
                provider,
            )

        logger.info(
            "Creating LLM provider: model=%s provider=%s key_set=%s",
            model,
            provider,
            bool(api_key),
        )

        # Anthropic uses its own SDK (not OpenAI-compatible)
        if provider == "anthropic":
            from rigovo.infrastructure.llm.anthropic_provider import (
                AnthropicProvider,
            )

            return AnthropicProvider(api_key=api_key, model=model)

        # Everything else uses OpenAI-compatible SDK
        from rigovo.infrastructure.llm.openai_provider import OpenAIProvider

        base_url = self._resolve_base_url(provider)
        return OpenAIProvider(api_key=api_key, model=model, base_url=base_url)

    def _resolve_api_key(self, provider: str) -> str:
        """Resolve API key: DB first, then config fallback."""
        db_key = _PROVIDER_DB_KEY.get(provider, "")
        if not db_key:
            return ""  # ollama needs no key

        # Primary: read from encrypted SQLite settings
        if self._key_resolver:
            try:
                val = self._key_resolver(db_key)
                if val:
                    logger.info(
                        "Resolved API key for %s from SQLite (%d chars)",
                        provider,
                        len(val),
                    )
                    return val
                logger.debug("SQLite returned empty for %s", db_key)
            except Exception as exc:
                logger.warning(
                    "key_resolver failed for %s: %s",
                    db_key,
                    exc,
                )
        else:
            logger.debug("No key_resolver set — skipping SQLite lookup")

        # Fallback: read from LLMConfig (env / .env for CLI usage)
        attr = _PROVIDER_KEY_ATTR.get(provider, "")
        fallback = getattr(self._config, attr, "") if attr else ""
        if fallback:
            logger.info(
                "Resolved API key for %s from config fallback (%d chars)",
                provider,
                len(fallback),
            )
        else:
            logger.warning(
                "No API key found for provider '%s' — checked SQLite key '%s' and config attr '%s'",
                provider,
                db_key,
                attr,
            )
        return fallback

    def _resolve_base_url(self, provider: str) -> str | None:
        """Resolve the base URL for a provider."""
        if provider == "openai":
            url = self._resolve_setting("OPENAI_BASE_URL", self._config.openai_base_url)
            return url or None

        if provider == "ollama":
            base = self._resolve_setting("OLLAMA_BASE_URL", self._config.ollama_base_url).rstrip(
                "/"
            )
            return f"{base}/v1"

        if provider == "openai_compatible":
            url = self._resolve_setting("OPENAI_BASE_URL", self._config.openai_base_url)
            if not url:
                logger.warning(
                    "Model uses openai_compatible provider but no base URL set. "
                    "Set a custom endpoint in Settings → API Keys."
                )
                return None
            return url

        return _PROVIDER_BASE_URLS.get(provider)

    def _resolve_setting(self, db_key: str, fallback: str) -> str:
        """Read a non-secret setting: DB first, then config."""
        if self._key_resolver:
            val = self._key_resolver(db_key)
            if val:
                return val
        return fallback
