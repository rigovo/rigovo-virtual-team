"""Anthropic (Claude) LLM provider implementation."""

from __future__ import annotations

from typing import Any

from rigovo.domain.interfaces.llm_provider import LLMProvider, LLMResponse, LLMUsage


class AnthropicProvider(LLMProvider):
    """
    LLM provider for Anthropic's Claude models.

    Uses the anthropic SDK directly — not langchain. This gives us
    full control over the API call and response parsing.
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
                raise ImportError(
                    "anthropic SDK required. Install with: pip install anthropic"
                )
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

        response = await client.messages.create(**kwargs)

        # Extract content
        content = ""
        tool_calls = []
        for block in response.content:
            if hasattr(block, "text"):
                content += block.text
            elif hasattr(block, "type") and block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

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
