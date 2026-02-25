"""Model catalog — types, recommendation engine, and provider detection.

NOT a whitelist. Users can use ANY model from ANY provider. This catalog
is purely for Rigovo's internal use:

1. Cost estimation — show live $ during task execution (known models)
2. Smart defaults — recommend models per agent role in presets
3. Provider routing — detect which SDK to use (Anthropic vs OpenAI-compatible)

Models NOT in this catalog still work fine:
- Rigovo tracks tokens (from API response usage field)
- User optionally provides pricing in rigovo.yml for live $ display
- Provider routing falls back to OpenAI-compatible SDK (works with most)

Pricing is per 1M tokens. Updated periodically from public pricing pages.
Model data (the actual registry) lives in model_registry.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Provider(str, Enum):
    """Known LLM providers (internal — NOT a restriction)."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GOOGLE = "google"
    DEEPSEEK = "deepseek"
    GROQ = "groq"
    MISTRAL = "mistral"
    OLLAMA = "ollama"


class Capability(str, Enum):
    """What an agent role needs from a model."""

    REASONING = "reasoning"
    CODING = "coding"
    ANALYSIS = "analysis"
    TEMPLATING = "templating"


@dataclass(frozen=True)
class ModelSpec:
    """A model's capabilities and pricing."""

    id: str
    name: str
    provider: Provider
    input_price: float        # USD per 1M input tokens
    output_price: float       # USD per 1M output tokens
    context_window: int = 128_000
    strengths: tuple[Capability, ...] = ()
    tier: str = "standard"    # "budget" | "standard" | "premium"

    @property
    def short_name(self) -> str:
        """Short display name for TUI tables."""
        return self.name

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost for a single invocation."""
        return (
            (input_tokens / 1_000_000) * self.input_price
            + (output_tokens / 1_000_000) * self.output_price
        )


# ---------------------------------------------------------------------------
# Agent role → capability mapping
# ---------------------------------------------------------------------------

ROLE_REQUIREMENTS: dict[str, tuple[Capability, ...]] = {
    "lead": (Capability.REASONING, Capability.ANALYSIS),
    "planner": (Capability.REASONING,),
    "coder": (Capability.CODING,),
    "reviewer": (Capability.ANALYSIS, Capability.REASONING),
    "security": (Capability.ANALYSIS, Capability.REASONING),
    "qa": (Capability.CODING,),
    "devops": (Capability.TEMPLATING,),
    "sre": (Capability.TEMPLATING,),
}

ROLE_TOKEN_ESTIMATES: dict[str, tuple[int, int]] = {
    "lead": (4000, 2000),
    "planner": (6000, 3000),
    "coder": (8000, 6000),
    "reviewer": (6000, 2000),
    "security": (5000, 2000),
    "qa": (6000, 4000),
    "devops": (3000, 2000),
    "sre": (3000, 2000),
}


# ---------------------------------------------------------------------------
# Recommendation engine
# ---------------------------------------------------------------------------


@dataclass
class ModelRecommendation:
    """A model recommendation for a specific agent role."""

    role_id: str
    model: ModelSpec
    estimated_cost: float


@dataclass
class Preset:
    """A complete model assignment for all agent roles."""

    name: str
    description: str
    assignments: dict[str, ModelRecommendation] = field(default_factory=dict)

    @property
    def estimated_cost_per_task(self) -> float:
        """Total estimated cost for one full pipeline run."""
        return sum(r.estimated_cost for r in self.assignments.values())


def _get_models() -> dict[str, ModelSpec]:
    """Lazy-load the model registry to avoid circular imports."""
    from rigovo.infrastructure.llm.model_registry import MODELS

    return MODELS


def _score_model(
    model: ModelSpec,
    requirements: tuple[Capability, ...],
) -> float:
    """Score a model against role requirements. Higher = better fit."""
    score = 0.0
    for req in requirements:
        if req in model.strengths:
            idx = model.strengths.index(req)
            score += 1.0 - (idx * 0.15)
    return score


def _pick_best(
    requirements: tuple[Capability, ...],
    tier: str,
    available_providers: set[Provider] | None = None,
) -> ModelSpec | None:
    """Pick the best model for given requirements and tier."""
    models = _get_models()
    candidates = [
        m for m in models.values()
        if m.tier == tier
        and (available_providers is None or m.provider in available_providers)
    ]
    if not candidates:
        return None

    scored = [(m, _score_model(m, requirements)) for m in candidates]
    scored.sort(key=lambda x: (-x[1], x[0].input_price))
    return scored[0][0] if scored else None


def _estimate_agent_cost(model: ModelSpec, role_id: str) -> float:
    """Estimate USD cost for one agent invocation on a typical task."""
    input_tokens, output_tokens = ROLE_TOKEN_ESTIMATES.get(
        role_id, (5000, 3000),
    )
    return model.estimate_cost(input_tokens, output_tokens)


def build_presets(
    available_providers: set[Provider] | None = None,
) -> dict[str, Preset]:
    """Build all three presets (budget / recommended / premium)."""
    presets: dict[str, Preset] = {
        "budget": Preset(
            name="budget",
            description="Cheapest — still good for most tasks",
        ),
        "recommended": Preset(
            name="recommended",
            description="Best quality/cost ratio",
        ),
        "premium": Preset(
            name="premium",
            description="Maximum quality — for critical tasks",
        ),
    }

    tier_map = {
        "budget": "budget",
        "recommended": "standard",
        "premium": "premium",
    }

    for preset_name, preset in presets.items():
        tier = tier_map[preset_name]
        for role_id, requirements in ROLE_REQUIREMENTS.items():
            model = _pick_best(requirements, tier, available_providers)

            if model is None and tier != "standard":
                model = _pick_best(requirements, "standard", available_providers)
            if model is None:
                model = _pick_best(requirements, "budget", available_providers)
            if model is None:
                continue

            cost = _estimate_agent_cost(model, role_id)
            preset.assignments[role_id] = ModelRecommendation(
                role_id=role_id,
                model=model,
                estimated_cost=cost,
            )

    return presets


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------


def detect_available_providers(
    anthropic_key: str = "",
    openai_key: str = "",
    google_key: str = "",
    deepseek_key: str = "",
    groq_key: str = "",
    mistral_key: str = "",
) -> set[Provider]:
    """Detect which providers the user has API keys for."""
    providers: set[Provider] = set()

    if anthropic_key:
        providers.add(Provider.ANTHROPIC)
    if openai_key:
        providers.add(Provider.OPENAI)
    if google_key:
        providers.add(Provider.GOOGLE)
    if deepseek_key:
        providers.add(Provider.DEEPSEEK)
    if groq_key:
        providers.add(Provider.GROQ)
    if mistral_key:
        providers.add(Provider.MISTRAL)

    providers.add(Provider.OLLAMA)  # Always available (local)
    return providers


def get_model(model_id: str) -> ModelSpec | None:
    """Look up a model by its ID."""
    return _get_models().get(model_id)


def detect_provider(model_id: str) -> str:
    """Detect provider from model name string.

    For known models, returns the exact provider.
    For unknown models, uses name-prefix heuristics.
    Falls back to "openai_compatible" — works with most providers.
    """
    models = _get_models()
    spec = models.get(model_id)
    if spec:
        return spec.provider.value

    prefixes: list[tuple[tuple[str, ...], str]] = [
        (("claude",), "anthropic"),
        (("gpt", "o1", "o3", "chatgpt"), "openai"),
        (("gemini",), "google"),
        (("deepseek",), "deepseek"),
        (("llama", "mixtral", "gemma"), "groq"),
        (("mistral", "codestral", "pixtral"), "mistral"),
    ]
    for name_prefixes, provider in prefixes:
        if model_id.startswith(name_prefixes):
            return provider

    return "openai_compatible"


# ---------------------------------------------------------------------------
# Custom provider support
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CustomProvider:
    """User-defined provider from rigovo.yml.

    Enables any OpenAI-compatible endpoint.
    """

    name: str
    base_url: str
    api_key_env: str = ""
    input_price: float = 0.0
    output_price: float = 0.0

    @property
    def has_pricing(self) -> bool:
        """Whether pricing data is available."""
        return self.input_price > 0 or self.output_price > 0

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
    ) -> float | None:
        """Estimate cost. Returns None if pricing unknown."""
        if not self.has_pricing:
            return None
        return (
            (input_tokens / 1_000_000) * self.input_price
            + (output_tokens / 1_000_000) * self.output_price
        )


def estimate_cost(
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    custom_providers: dict[str, CustomProvider] | None = None,
) -> float | None:
    """Estimate cost for any model — known or custom.

    Returns USD cost if pricing is known, None if unknown.
    """
    models = _get_models()
    spec = models.get(model_id)
    if spec:
        return spec.estimate_cost(input_tokens, output_tokens)

    if custom_providers:
        provider_name = detect_provider(model_id)
        custom = custom_providers.get(provider_name)
        if custom:
            return custom.estimate_cost(input_tokens, output_tokens)

    return None
