"""Cost calculator — token-to-dollar conversion. Pure domain logic."""

from __future__ import annotations

from dataclasses import dataclass, field

# --- Named constants for pricing defaults and estimation ---
DEFAULT_INPUT_PRICE_PER_M = 5.00  # Conservative default for unknown models
DEFAULT_OUTPUT_PRICE_PER_M = 15.00
TOKENS_PER_MILLION = 1_000_000
COST_PRECISION = 6  # Decimal places for cost rounding
ESTIMATE_PRECISION = 4
DEFAULT_AVG_TOKENS_PER_AGENT = 4000
INPUT_TOKEN_RATIO = 0.7  # 70% input, 30% output estimate
OUTPUT_TOKEN_RATIO = 0.3


@dataclass
class ModelPricing:
    """
    Pricing table for LLM models.

    Prices are per 1 million tokens. Updated manually when providers
    change pricing. Defaults to a conservative estimate for unknown models.
    """

    prices: dict[str, dict[str, float]] = field(
        default_factory=lambda: {
            # Anthropic (Feb 2026)
            "claude-opus-4-6": {"input": 5.00, "output": 25.00, "cached_input": 0.50},
            "claude-sonnet-4-6": {"input": 3.00, "output": 15.00, "cached_input": 0.30},
            "claude-opus-4-5-20250624": {"input": 5.00, "output": 25.00, "cached_input": 0.50},
            "claude-sonnet-4-5-20250929": {
                "input": 3.00,
                "output": 15.00,
                "cached_input": 0.30,
            },
            "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00, "cached_input": 0.10},
            # OpenAI (Feb 2026)
            "gpt-5": {"input": 1.25, "output": 10.00, "cached_input": 0.625},
            "gpt-5-mini": {"input": 0.25, "output": 2.00, "cached_input": 0.125},
            "gpt-4o": {"input": 5.00, "output": 15.00, "cached_input": 2.50},
            "gpt-4o-mini": {"input": 0.15, "output": 0.60, "cached_input": 0.075},
            "o1": {"input": 15.00, "output": 60.00, "cached_input": 7.50},
            "o3-mini": {"input": 1.10, "output": 4.40, "cached_input": 0.55},
            # Google (Feb 2026)
            "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
            "gemini-2.5-flash": {"input": 0.075, "output": 0.30},
            # DeepSeek (Feb 2026) — dramatically cheaper
            "deepseek-chat": {"input": 0.27, "output": 0.42},
            "deepseek-reasoner": {"input": 0.12, "output": 0.20},
            # Mistral (Feb 2026)
            "mistral-large-latest": {"input": 2.00, "output": 6.00},
            "mistral-medium-latest": {"input": 0.40, "output": 2.00},
            "codestral-latest": {"input": 0.30, "output": 0.90},
            # Groq (hosted open-source)
            "llama-3.3-70b-versatile": {"input": 0.59, "output": 0.79},
            # Ollama (local — free, but track for comparison)
            "ollama/llama3": {"input": 0.0, "output": 0.0},
            "ollama/codellama": {"input": 0.0, "output": 0.0},
        }
    )

    # Default pricing for unknown models (conservative estimate)
    default_input: float = DEFAULT_INPUT_PRICE_PER_M
    default_output: float = DEFAULT_OUTPUT_PRICE_PER_M

    def get_pricing(self, model: str) -> tuple[float, float]:
        """Return (input_price_per_M, output_price_per_M) for a model."""
        if model in self.prices:
            p = self.prices[model]
            return p["input"], p["output"]
        return self.default_input, self.default_output

    def get_cached_input_pricing(self, model: str) -> float | None:
        """Return cached-input price per 1M tokens, if configured."""
        p = self.prices.get(model)
        if not p:
            return None
        raw = p.get("cached_input")
        return float(raw) if raw is not None else None

    def get_cache_write_pricing(self, model: str) -> float | None:
        """Return cache-write/create input price per 1M tokens, if configured."""
        p = self.prices.get(model)
        if not p:
            return None
        raw = p.get("cache_write")
        return float(raw) if raw is not None else None


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
        cached_input_tokens: int = 0,
        cache_write_tokens: int = 0,
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
        cached_input_price = self._pricing.get_cached_input_pricing(model)
        cache_write_price = self._pricing.get_cache_write_pricing(model)

        input_cost = (input_tokens / TOKENS_PER_MILLION) * input_price
        # If a model-specific cached-input rate is unavailable, charge at normal input rate.
        input_cost += (cached_input_tokens / TOKENS_PER_MILLION) * (
            cached_input_price if cached_input_price is not None else input_price
        )
        # If a model-specific cache-write rate is unavailable, charge at normal input rate.
        input_cost += (cache_write_tokens / TOKENS_PER_MILLION) * (
            cache_write_price if cache_write_price is not None else input_price
        )
        output_cost = (output_tokens / TOKENS_PER_MILLION) * output_price
        return round(input_cost + output_cost, COST_PRECISION)

    def calculate_uncached_baseline(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_input_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> float:
        """Estimate cost if provider caching gave no discount."""
        input_price, output_price = self._pricing.get_pricing(model)
        full_input_tokens = max(0, input_tokens) + max(0, cached_input_tokens) + max(
            0, cache_write_tokens
        )
        input_cost = (full_input_tokens / TOKENS_PER_MILLION) * input_price
        output_cost = (max(0, output_tokens) / TOKENS_PER_MILLION) * output_price
        return round(input_cost + output_cost, COST_PRECISION)

    def estimate_task_cost(
        self,
        model: str,
        agent_count: int,
        avg_tokens_per_agent: int = DEFAULT_AVG_TOKENS_PER_AGENT,
    ) -> float:
        """
        Rough cost estimate for a task before execution.

        Used in approval gates: "This task will cost ~$X. Approve?"
        """
        input_tokens = int(avg_tokens_per_agent * INPUT_TOKEN_RATIO)
        output_tokens = int(avg_tokens_per_agent * OUTPUT_TOKEN_RATIO)
        per_agent = self.calculate(model, input_tokens, output_tokens)
        return round(per_agent * agent_count, ESTIMATE_PRECISION)
