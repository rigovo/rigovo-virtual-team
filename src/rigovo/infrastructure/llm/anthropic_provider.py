"""Anthropic (Claude) LLM provider implementation."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from rigovo.domain.interfaces.llm_provider import LLMProvider, LLMResponse, LLMUsage

logger = logging.getLogger(__name__)

# Retry config for transient API errors (429, 529, 500, etc.)
_MAX_RETRIES = 5
_BASE_DELAY = 1.0  # seconds — doubles each attempt (1, 2, 4, 8, 16)
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}


class AnthropicProvider(LLMProvider):
    """
    LLM provider for Anthropic's Claude models.

    Uses the anthropic SDK directly — not langchain. This gives us
    full control over the API call and response parsing.

    Includes automatic retry with exponential backoff for transient
    API errors (429 rate limit, 529 overloaded, 5xx server errors).
    """

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6") -> None:
        self._api_key = api_key
        self._model = model
        self._client: Any = None

    @property
    def model_name(self) -> str:
        return self._model

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import anthropic
            except ImportError:
                raise ImportError("anthropic SDK required. Install with: pip install anthropic")
            self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
        return self._client

    async def invoke(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        client = self._get_client()

        # Separate system from user/assistant messages
        system_msg = ""
        api_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_msg = msg["content"]
            else:
                api_messages.append(msg)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_msg:
            # Use prompt caching for system prompts — they're identical across
            # rounds in an agentic loop, saving 90% of input tokens after the
            # first call. cache_control type "ephemeral" caches for 5 minutes.
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": system_msg,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        response = await self._invoke_with_retry(client, kwargs)

        # Extract content
        content = ""
        tool_calls = []
        for block in response.content:
            if hasattr(block, "text"):
                content += block.text
            elif hasattr(block, "type") and block.type == "tool_use":
                tool_calls.append(
                    {
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )

        return LLMResponse(
            content=content,
            usage=LLMUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            ),
            model=self._model,
            stop_reason=response.stop_reason or "",
            tool_calls=tool_calls,
            raw=response,
        )

    async def stream(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Any:
        client = self._get_client()

        system_msg = ""
        api_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_msg = msg["content"]
            else:
                api_messages.append(msg)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_msg:
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": system_msg,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        stream = await client.messages.stream(**kwargs).__aenter__()
        try:
            async for text in stream.text_stream:
                yield text
        finally:
            await stream.__aexit__(None, None, None)

    @staticmethod
    async def _invoke_with_retry(client: Any, kwargs: dict[str, Any]) -> Any:
        """Invoke the Anthropic API with exponential backoff retry.

        Retries on transient errors: 429 (rate limit), 529 (overloaded),
        500/502/503 (server errors). Non-retryable errors raise immediately.
        """
        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                return await client.messages.create(**kwargs)
            except Exception as exc:
                # Extract HTTP status code from Anthropic SDK exceptions
                status_code = getattr(exc, "status_code", None)

                if status_code not in _RETRYABLE_STATUS_CODES:
                    raise  # Not retryable — propagate immediately

                last_error = exc
                delay = _BASE_DELAY * (2**attempt)
                logger.warning(
                    "Anthropic API returned %s (attempt %d/%d), retrying in %.1fs: %s",
                    status_code,
                    attempt + 1,
                    _MAX_RETRIES,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)

        # All retries exhausted — raise the last error
        raise last_error  # type: ignore[misc]

    @staticmethod
    def _convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert our tool format to Anthropic's tool format."""
        return [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": t.get("parameters", {"type": "object", "properties": {}}),
            }
            for t in tools
        ]
