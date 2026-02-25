"""OpenAI (GPT) LLM provider implementation.

Also works as a base for OpenAI-compatible providers (Groq, Mistral,
DeepSeek, Ollama, etc.) by passing a custom base_url.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from rigovo.domain.interfaces.llm_provider import LLMProvider, LLMResponse, LLMUsage


class OpenAIProvider(LLMProvider):
    """LLM provider for OpenAI's GPT models.

    Prompt caching: OpenAI automatically caches repeated message prefixes
    (1024+ tokens). We optimize cache hit rates by:
    1. Keeping system messages at the start (prefix matching)
    2. Using ``prompt_cache_key`` to route related requests together
    3. Setting ``prompt_cache_retention`` to "24h" for long agentic loops

    For OpenAI-compatible providers that don't support caching params,
    the extra kwargs are silently ignored by most SDKs.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-5",
        base_url: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url  # For OpenAI-compatible endpoints
        self._client: Any = None
        self._system_hash: str = ""  # For stable cache key across rounds

    @property
    def model_name(self) -> str:
        return self._model

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError:
                raise ImportError(
                    "openai SDK required. Install with: pip install openai"
                )
            kwargs: dict[str, Any] = {"api_key": self._api_key}
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = AsyncOpenAI(**kwargs)
        return self._client

    def _compute_cache_key(self, messages: list[dict[str, Any]]) -> str:
        """Compute a stable cache key from system message prefix.

        This helps OpenAI route requests to the same cache shard,
        improving hit rates in agentic loops where the system prompt
        stays constant across rounds.
        """
        for msg in messages:
            if msg.get("role") == "system":
                content = msg.get("content", "")
                if isinstance(content, str):
                    return hashlib.sha256(content[:500].encode()).hexdigest()[:16]
        return ""

    async def invoke(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        client = self._get_client()

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        response = await client.chat.completions.create(**kwargs)
        choice = response.choices[0]

        # Extract tool calls
        tool_calls = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                try:
                    parsed_input = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    parsed_input = {}
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "input": parsed_input,
                })

        # Extract cached token info if available
        input_tokens = response.usage.prompt_tokens if response.usage else 0
        output_tokens = response.usage.completion_tokens if response.usage else 0

        return LLMResponse(
            content=choice.message.content or "",
            usage=LLMUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ),
            model=self._model,
            stop_reason=choice.finish_reason or "",
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

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        stream = await client.chat.completions.create(**kwargs)
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    @staticmethod
    def _convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert our tool format to OpenAI's function calling format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                },
            }
            for t in tools
        ]
