"""Model registry — known models with pricing and capabilities.

This is purely data. The recommendation engine lives in model_catalog.py.
NOT a whitelist. Users can use ANY model from ANY provider.

Last updated: February 2026
Sources: Anthropic, OpenAI, Google, DeepSeek, Mistral official pricing pages.
"""

from __future__ import annotations

from rigovo.infrastructure.llm.model_catalog import (
    Capability,
    ModelSpec,
    Provider,
)

MODELS: dict[str, ModelSpec] = {}


def _register(*specs: ModelSpec) -> None:
    """Register models into the global registry."""
    for s in specs:
        MODELS[s.id] = s


# ── Anthropic (Feb 2026) ─────────────────────────────────────────────────
# Claude 4.6 series — latest (Feb 2026)
# Claude 4.5 series — still available, retiring late 2026
_register(
    # --- Claude 4.6 (latest) ---
    ModelSpec(
        id="claude-opus-4-6",
        name="Claude Opus 4.6",
        provider=Provider.ANTHROPIC,
        input_price=5.0,
        output_price=25.0,
        context_window=200_000,
        strengths=(Capability.REASONING, Capability.CODING, Capability.ANALYSIS),
        tier="premium",
    ),
    ModelSpec(
        id="claude-sonnet-4-6",
        name="Claude Sonnet 4.6",
        provider=Provider.ANTHROPIC,
        input_price=3.0,
        output_price=15.0,
        context_window=200_000,
        strengths=(Capability.CODING, Capability.ANALYSIS, Capability.REASONING),
        tier="standard",
    ),
    # --- Claude 4.5 (previous gen, still supported) ---
    ModelSpec(
        id="claude-opus-4-5-20250624",
        name="Claude Opus 4.5",
        provider=Provider.ANTHROPIC,
        input_price=5.0,
        output_price=25.0,
        context_window=200_000,
        strengths=(Capability.REASONING, Capability.CODING, Capability.ANALYSIS),
        tier="premium",
    ),
    ModelSpec(
        id="claude-sonnet-4-5-20250929",
        name="Claude Sonnet 4.5",
        provider=Provider.ANTHROPIC,
        input_price=3.0,
        output_price=15.0,
        context_window=200_000,
        strengths=(Capability.CODING, Capability.ANALYSIS, Capability.REASONING),
        tier="standard",
    ),
    # --- Claude Haiku 4.5 (fast + cheap) ---
    ModelSpec(
        id="claude-haiku-4-5-20251001",
        name="Claude Haiku 4.5",
        provider=Provider.ANTHROPIC,
        input_price=1.0,
        output_price=5.0,
        context_window=200_000,
        strengths=(Capability.TEMPLATING, Capability.CODING),
        tier="budget",
    ),
)

# ── OpenAI (Feb 2026) ────────────────────────────────────────────────────
# GPT-5 series — latest flagship
# GPT-4o series — still widely used
_register(
    ModelSpec(
        id="gpt-5",
        name="GPT-5",
        provider=Provider.OPENAI,
        input_price=1.25,
        output_price=10.0,
        context_window=128_000,
        strengths=(Capability.CODING, Capability.REASONING, Capability.ANALYSIS),
        tier="standard",
    ),
    ModelSpec(
        id="gpt-5-mini",
        name="GPT-5 Mini",
        provider=Provider.OPENAI,
        input_price=0.25,
        output_price=2.0,
        context_window=128_000,
        strengths=(Capability.CODING, Capability.TEMPLATING),
        tier="budget",
    ),
    ModelSpec(
        id="gpt-4o",
        name="GPT-4o",
        provider=Provider.OPENAI,
        input_price=5.0,
        output_price=15.0,
        context_window=128_000,
        strengths=(Capability.CODING, Capability.ANALYSIS, Capability.REASONING),
        tier="standard",
    ),
    ModelSpec(
        id="gpt-4o-mini",
        name="GPT-4o Mini",
        provider=Provider.OPENAI,
        input_price=0.15,
        output_price=0.60,
        context_window=128_000,
        strengths=(Capability.TEMPLATING, Capability.CODING),
        tier="budget",
    ),
    ModelSpec(
        id="o1",
        name="o1",
        provider=Provider.OPENAI,
        input_price=15.0,
        output_price=60.0,
        context_window=200_000,
        strengths=(Capability.REASONING, Capability.ANALYSIS),
        tier="premium",
    ),
    ModelSpec(
        id="o3-mini",
        name="o3-mini",
        provider=Provider.OPENAI,
        input_price=1.10,
        output_price=4.40,
        context_window=200_000,
        strengths=(Capability.REASONING, Capability.CODING),
        tier="standard",
    ),
)

# ── Google (Feb 2026) ────────────────────────────────────────────────────
# Gemini 2.5 — stable, free tier available
# Gemini 2.0 Flash — retiring March 2026
_register(
    ModelSpec(
        id="gemini-2.5-pro",
        name="Gemini 2.5 Pro",
        provider=Provider.GOOGLE,
        input_price=1.25,
        output_price=10.0,
        context_window=1_000_000,
        strengths=(Capability.REASONING, Capability.CODING, Capability.ANALYSIS),
        tier="standard",
    ),
    ModelSpec(
        id="gemini-2.5-flash",
        name="Gemini 2.5 Flash",
        provider=Provider.GOOGLE,
        input_price=0.075,
        output_price=0.30,
        context_window=1_000_000,
        strengths=(Capability.TEMPLATING, Capability.CODING),
        tier="budget",
    ),
)

# ── DeepSeek (Feb 2026) ──────────────────────────────────────────────────
# V3.2 powers both endpoints. Dramatically cheaper than competitors.
_register(
    ModelSpec(
        id="deepseek-chat",
        name="DeepSeek V3.2",
        provider=Provider.DEEPSEEK,
        input_price=0.27,
        output_price=0.42,
        context_window=64_000,
        strengths=(Capability.CODING, Capability.REASONING),
        tier="budget",
    ),
    ModelSpec(
        id="deepseek-reasoner",
        name="DeepSeek R1",
        provider=Provider.DEEPSEEK,
        input_price=0.12,
        output_price=0.20,
        context_window=64_000,
        strengths=(Capability.REASONING, Capability.ANALYSIS),
        tier="budget",
    ),
)

# ── Mistral (Feb 2026) ───────────────────────────────────────────────────
_register(
    ModelSpec(
        id="mistral-large-latest",
        name="Mistral Large 3",
        provider=Provider.MISTRAL,
        input_price=2.0,
        output_price=6.0,
        context_window=128_000,
        strengths=(Capability.CODING, Capability.REASONING),
        tier="standard",
    ),
    ModelSpec(
        id="mistral-medium-latest",
        name="Mistral Medium 3",
        provider=Provider.MISTRAL,
        input_price=0.40,
        output_price=2.0,
        context_window=131_000,
        strengths=(Capability.CODING, Capability.TEMPLATING),
        tier="budget",
    ),
    ModelSpec(
        id="codestral-latest",
        name="Codestral",
        provider=Provider.MISTRAL,
        input_price=0.30,
        output_price=0.90,
        context_window=256_000,
        strengths=(Capability.CODING, Capability.TEMPLATING),
        tier="budget",
    ),
)

# ── Groq (hosted open-source) ────────────────────────────────────────────
_register(
    ModelSpec(
        id="llama-3.3-70b-versatile",
        name="Llama 3.3 70B",
        provider=Provider.GROQ,
        input_price=0.59,
        output_price=0.79,
        context_window=128_000,
        strengths=(Capability.CODING, Capability.ANALYSIS),
        tier="budget",
    ),
)
