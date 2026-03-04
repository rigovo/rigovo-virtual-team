"""LLM Provider interface — abstraction over Claude, GPT, Groq, Ollama."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMUsage:
    """Token usage from a single LLM call."""

    input_tokens: int = 0
    output_tokens: int = 0
    # Provider prompt-cache read tokens (discounted billing path)
    cached_input_tokens: int = 0
    # Provider cache-write/create tokens (if provider reports separately)
    cache_write_tokens: int = 0
    # provider | rigovo_exact | rigovo_semantic | none
    cache_source: str = "none"

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.cached_input_tokens
            + self.cache_write_tokens
            + self.output_tokens
        )


@dataclass
class LLMResponse:
    """Standardised response from any LLM provider."""

    content: str
    usage: LLMUsage
    model: str
    stop_reason: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    raw: Any = None  # Provider-specific raw response


class LLMProvider(ABC):
    """
    Abstract interface for LLM providers.

    Infrastructure layer implements this for Anthropic, OpenAI, Groq, Ollama.
    The application layer only depends on this interface — never on a concrete SDK.
    """

    @property
    @abstractmethod
    def model_name(self) -> str:
        """The model identifier (e.g. 'claude-sonnet-4-6')."""
        ...

    @abstractmethod
    async def invoke(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """
        Send messages to the LLM and get a response.

        Args:
            messages: List of {role: str, content: str} messages.
            tools: Optional tool definitions for function calling.
            temperature: Sampling temperature (0.0 = deterministic).
            max_tokens: Maximum tokens in the response.

        Returns:
            Standardised LLMResponse with content, usage, and tool calls.
        """
        await asyncio.sleep(0)  # abstract — subclasses must override
        raise NotImplementedError

    @abstractmethod
    async def stream(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Any:
        """
        Stream messages from the LLM.

        Returns an async iterator of partial responses.
        Used for real-time terminal display.
        """
        await asyncio.sleep(0)  # abstract — subclasses must override
        raise NotImplementedError
