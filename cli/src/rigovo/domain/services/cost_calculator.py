"""Cost calculator — token-to-dollar conversion. Pure domain logic."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ModelPricing:
    """
    Pricing table for LLM models.

    Prices are per 1 million tokens. Updated manually when providers
    change pricing. Defaults to a conservative estimate for unknown models.
    """

    prices: dict[str, dict[str, float]] = field(default_factory=lambda: {
        # Anthropic
        "claude-opus-4-5-20251101": {"input": 15.00, "output": 75.00},
        "claude-sonnet-4-5-20250929": {"input": 3.00, "output": 15.00},
        "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
        # OpenAI
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "o1": {"input": 15.00, "output": 60.00},
        "o1-mini": {"input": 3.00, "output": 12.00},
        # Groq (hosted Llama/Mixtral — cheap)
        "llama-3.3-70b-versatile": {"input": 0.59, "output": 0.79},
        "mixtral-8x7b-32768": {"input": 0.24, "output": 0.24},
        # Ollama (local — free, but track for comparison)
        "ollama/llama3": {"input": 0.0, "output": 0.0},
        "ollama/codellama": {"input": 0.0, "output": 0.0},
    })

    # Default pricing for unknown models (conservative estimate)
    default_input: float = 5.00
    default_output: float = 15.00

    def get_pricing(self, model: str) -> tuple[float, float]:
        """Return (input_price_per_M, output_price_per_M) for a model."""
        if model in self.prices:
            p = self.prices[model]
            return p["input"], p["output"]
        return self.default_input, self.default_output


class CostCalculator:
    """
    Converts token usage into dollar cost.

    Pure domain service — no side effects, no I/O.
    """

    def __init__(self, pricing: ModelPricing | None = None) -> None:
        self._pricing = pricing or ModelPricing()

    def calculate(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """
        Calculate the cost of a single LLM call.

        Args:
            model: Model identifier.
            input_tokens: Number of input tokens.
            output_tokens: Number of output tokens.

        Returns:
            Cost in USD, rounded to 6 decimal places.
        """
        input_price, output_price = self._pricing.get_pricing(model)
        input_cost = (input_tokens / 1_000_000) * input_price
        output_cost = (output_tokens / 1_000_000) * output_price
        return round(input_cost + output_cost, 6)

    def estimate_task_cost(
        self,
        model: str,
        agent_count: int,
        avg_tokens_per_agent: int = 4000,
    ) -> float:
        """
        Rough cost estimate for a task before execution.

        Used in approval gates: "This task will cost ~$X. Approve?"
        """
        # Assume 70% input, 30% output ratio
        input_tokens = int(avg_tokens_per_agent * 0.7)
        output_tokens = int(avg_tokens_per_agent * 0.3)
        per_agent = self.calculate(model, input_tokens, output_tokens)
        return round(per_agent * agent_count, 4)
