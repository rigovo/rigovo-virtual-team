"""Semantic Guardrail System — Two-Pass Intent Classification.

Evolution from brittle keyword regex to **Semantic Signatures**:

Pass 1 (Regex):  Instant (<1ms), deterministic, catches obvious intents.
Pass 2 (Vector):  <50ms, zero LLM calls, compares input against "Golden
                  Examples" using LocalEmbeddingProvider (256-dim hashing).

The result is a FLOOR that the Master Agent LLM can upgrade but NEVER
downgrade.  If both passes fail, we default to the safest broad category
and let the LLM refine.

Architecture:
    User Input
        ↓
    Pass 1: Regex Match → high confidence (0.90) if match
        ↓ (no match)
    Pass 2: Vector Similarity → compare against ~70 golden anchors
        ↓
    Resolve: best_match > 0.75 AND gap > 0.15 → confident
             best_match > 0.60 AND gap < 0.15 → ambiguous → broadest match
             best_match < 0.60 → unknown → default feature/medium
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from rigovo.application.master.deterministic_brain import (
    _COMPILED_RULES,
    DeterministicClassification,
)

# ═══════════════════════════════════════════════════════════════════════
# 1. INTENT SIGNATURES — golden examples per task type
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class IntentSignature:
    """A task type's identity: regex patterns + semantic anchor phrases."""

    task_type: str
    complexity_hint: str  # default complexity when this type matches
    patterns: list[re.Pattern[str]]  # Pass 1 regexes (compiled)
    semantic_anchors: list[str]  # Pass 2 golden examples
    anchor_embeddings: list[list[float]] = field(default_factory=list)  # pre-computed


# ── Golden example anchors per task type ─────────────────────────────
# These are NOT keywords — they are complete phrases that represent the
# INTENT of each task type.  The vector similarity finds inputs that
# "feel like" these phrases, even without exact word overlap.

_RAW_SIGNATURES: dict[str, dict[str, Any]] = {
    "new_project": {
        "complexity_hint": "high",
        "patterns": [
            r"\b(?:create\s+(?:new\s+)?(?:repo|project|app|application|service))\b",
            r"\b(?:build\s+(?:a\s+|an\s+)?(?:new\s+)?(?:app|application|service|platform|system|saas|tool))\b",
            r"\b(?:create\s+(?:a\s+|an\s+)?(?:app|application|service|platform|system|saas|tool))\b",
            r"\b(?:create\s+(?:a\s+|an\s+)?new\s+folder)\b",
            r"\b(?:create\s+\w+(?:\s+\w+){0,4}\s+(?:saas|platform|system|service|application|app|tool)\s+in\s+(?:python|typescript|javascript|go|rust|java|node(?:\.js)?))\b",
            r"\b(?:init(?:ialize)?|scaffold|bootstrap|start\s+(?:a\s+)?new)\b",
            r"\b(?:new\s+repo(?:sitory)?|from\s+scratch|brand\s*new)\b",
            r"\b(?:set\s*up\s+(?:a\s+)?(?:project|repo|codebase))\b",
        ],
        "anchors": [
            "build a new authentication SaaS from scratch",
            "create a REST API for a todo application",
            "scaffold a React dashboard with TypeScript",
            "spin up a new landing page with Next.js",
            "initialize a Python microservice for payments",
            "start a new CLI tool for data processing",
            "set up a new monorepo with turborepo",
        ],
    },
    "feature": {
        "complexity_hint": "medium",
        "patterns": [
            r"\b(?:add|implement|develop|integrate|enable|support)\b",
        ],
        "anchors": [
            "add user authentication to the existing app",
            "implement dark mode toggle in settings",
            "integrate Stripe payment gateway",
            "add email notification system",
            "build a dashboard showing analytics",
            "implement file upload with drag and drop",
            "add search functionality with filters",
            "enable two-factor authentication",
        ],
    },
    "bug": {
        "complexity_hint": "medium",
        "patterns": [
            r"\b(?:fix\s+(?:a\s+|the\s+)?bug|broken|crash(?:es|ing)?|error|regression|hotfix)\b",
            r"\b(?:doesn'?t\s+work|not\s+working|fails?\s+(?:to|when)|issue\s+with)\b",
        ],
        "anchors": [
            "fix a broken feature that stopped working after deployment",
            "debug an error in the login flow",
            "the button crashes when clicked on mobile",
            "unexpected behavior in payment processing",
            "regression after the last release",
            "UI visual glitch on mobile safari",
            "the API returns 500 errors intermittently",
        ],
    },
    "refactor": {
        "complexity_hint": "medium",
        "patterns": [
            r"\b(?:refactor|clean\s*up|reorgani[sz]e|restructure|simplify|modernize)\b",
        ],
        "anchors": [
            "stitch these two modules together into one",
            "simplify the database access layer",
            "extract the auth logic into a separate service",
            "modernize the legacy callback-based code to async await",
            "reduce duplication across the API route handlers",
            "restructure the project directory for better organization",
        ],
    },
    "test": {
        "complexity_hint": "medium",
        "patterns": [
            r"\b(?:write\s+tests?|add\s+tests?|test\s+coverage|unit\s+test|integration\s+test|e2e)\b",
        ],
        "anchors": [
            "write unit tests for the authentication module",
            "add integration test coverage for the API",
            "create end-to-end tests for the checkout flow",
            "increase test coverage to above 80 percent",
            "add snapshot tests for the React components",
        ],
    },
    "docs": {
        "complexity_hint": "low",
        "patterns": [
            r"\b(?:document(?:ation)?|write\s+docs?|readme|api\s+docs?|jsdoc|docstring)\b",
        ],
        "anchors": [
            "document all the API endpoints with examples",
            "write a comprehensive README for the project",
            "add JSDoc comments to all exported functions",
            "create an architecture decision record",
            "write onboarding documentation for new developers",
        ],
    },
    "infra": {
        "complexity_hint": "medium",
        "patterns": [
            r"\b(?:deploy|docker|kubernetes|k8s|ci\s*/?\\s*cd|terraform|infra(?:structure)?|helm)\b",
        ],
        "anchors": [
            "set up Docker containers for the microservices",
            "configure a CI CD pipeline with GitHub Actions",
            "add Terraform for AWS infrastructure provisioning",
            "deploy the application to Kubernetes cluster",
            "set up monitoring with Prometheus and Grafana",
            "configure auto-scaling for the API servers",
        ],
    },
    "security": {
        "complexity_hint": "high",
        "patterns": [
            r"\b(?:security\s+audit|vulnerability|cve|penetration|auth(?:entication|orization)\s+fix)\b",
        ],
        "anchors": [
            "audit the codebase for SQL injection vulnerabilities",
            "fix the cross-site scripting vulnerability in the form",
            "add rate limiting to prevent brute force attacks",
            "implement CORS policy for the API endpoints",
            "review authentication flow for security weaknesses",
            "add input sanitization to all user-facing endpoints",
        ],
    },
    "performance": {
        "complexity_hint": "medium",
        "patterns": [
            r"\b(?:performance|optimi[sz]e|slow|latency|speed\s*up|profil(?:e|ing)|benchmark)\b",
        ],
        "anchors": [
            "optimize the slow database queries on the dashboard",
            "reduce the initial page load time below 2 seconds",
            "profile memory usage and fix the leak in the worker",
            "speed up the CI pipeline from 15 minutes to under 5",
            "add caching layer to reduce API response latency",
        ],
    },
    "investigation": {
        "complexity_hint": "medium",
        "patterns": [
            r"\b(?:investigate|debug|trace|diagnose|understand|figure\s+out|look\s+into)\b",
        ],
        "anchors": [
            "figure out why the deployments are slow on Friday",
            "trace the source of the memory leak in production",
            "investigate why the test suite is flaky",
            "understand the data flow between services",
            "look into the intermittent timeout errors",
        ],
    },
}


def _build_signatures() -> dict[str, IntentSignature]:
    """Build IntentSignature objects from raw config.  Compiles regexes."""
    result: dict[str, IntentSignature] = {}
    for task_type, cfg in _RAW_SIGNATURES.items():
        compiled = [re.compile(p, re.IGNORECASE) for p in cfg.get("patterns", [])]
        result[task_type] = IntentSignature(
            task_type=task_type,
            complexity_hint=cfg.get("complexity_hint", "medium"),
            patterns=compiled,
            semantic_anchors=cfg.get("anchors", []),
        )
    return result


INTENT_SIGNATURES: dict[str, IntentSignature] = _build_signatures()


# ═══════════════════════════════════════════════════════════════════════
# 2. SEMANTIC CLASSIFIER — two-pass classification
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class SemanticClassification:
    """Result of the two-pass semantic classification."""

    task_type: str
    complexity: str
    confidence: float  # 0.0–1.0
    source: str  # "regex", "semantic", "default"
    matched_pattern: str  # what matched (regex pattern or anchor text)
    best_similarity: float  # highest cosine similarity (Pass 2)
    runner_up_type: str  # second-best task type
    runner_up_similarity: float  # second-best similarity
    is_ambiguous: bool  # True if gap between best and runner-up < 0.15


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class SemanticClassifier:
    """Two-pass classifier: Regex (Pass 1) + Vector Similarity (Pass 2).

    Initialisation pre-computes embeddings for all golden anchors using
    the provided embedding provider.  This is a one-time cost (~50ms)
    that makes subsequent classifications instant.

    Usage::

        from rigovo.infrastructure.embeddings.local_embeddings import LocalEmbeddingProvider

        classifier = SemanticClassifier(LocalEmbeddingProvider())
        await classifier.initialize()  # pre-embed anchors (once)

        result = await classifier.classify("stitch these two modules together")
        # result.task_type == "refactor", result.source == "semantic"
    """

    def __init__(self, embedding_provider: Any | None = None) -> None:
        self._embedding_provider = embedding_provider
        self._initialized = False

    async def initialize(self) -> None:
        """Pre-compute embeddings for all golden anchor phrases.

        This must be called once before classify().  It's fast (~50ms)
        because LocalEmbeddingProvider uses hash-based embeddings.
        """
        if self._initialized or self._embedding_provider is None:
            return

        for sig in INTENT_SIGNATURES.values():
            if sig.semantic_anchors and not sig.anchor_embeddings:
                embeddings = await self._embedding_provider.embed_batch(sig.semantic_anchors)
                sig.anchor_embeddings = embeddings

        self._initialized = True

    async def classify(self, text: str) -> SemanticClassification:
        """Run the two-pass classification.

        Pass 1: Regex patterns (instant, <1ms)
        Pass 2: Vector similarity against golden examples (<50ms)
        Resolution: combine both passes into final result.
        """
        text = text.strip()
        if not text:
            return self._default_result()

        # ── Pass 1: Regex ────────────────────────────────────────────
        pass1 = self._pass1_regex(text)
        if pass1 is not None:
            return pass1

        # ── Pass 2: Vector similarity ────────────────────────────────
        if self._initialized and self._embedding_provider is not None:
            pass2 = await self._pass2_semantic(text)
            if pass2 is not None:
                return pass2

        # ── Default: unknown intent ──────────────────────────────────
        return self._default_result()

    def _pass1_regex(self, text: str) -> SemanticClassification | None:
        """Pass 1: Try compiled regex rules (reuses deterministic brain's rules).

        Returns high-confidence result if a pattern matches.  Returns None
        if no pattern matches (trigger Pass 2).
        """
        # Use the existing compiled rules from deterministic_brain
        for compiled_re, task_type, complexity in _COMPILED_RULES:
            match = compiled_re.search(text)
            if match:
                return SemanticClassification(
                    task_type=task_type,
                    complexity=complexity,
                    confidence=0.90,
                    source="regex",
                    matched_pattern=match.group(),
                    best_similarity=1.0,
                    runner_up_type="",
                    runner_up_similarity=0.0,
                    is_ambiguous=False,
                )
        return None

    async def _pass2_semantic(self, text: str) -> SemanticClassification | None:
        """Pass 2: Compare input embedding against all anchor embeddings.

        Finds the task type whose golden examples are most similar to
        the input.  Returns None if confidence is too low.
        """
        input_embedding = await self._embedding_provider.embed(text)

        # Score each task type: best similarity across its anchors
        type_scores: list[tuple[str, float, str]] = []  # (task_type, best_sim, best_anchor)

        for task_type, sig in INTENT_SIGNATURES.items():
            if not sig.anchor_embeddings:
                continue

            best_sim = 0.0
            best_anchor = ""
            for anchor_text, anchor_emb in zip(sig.semantic_anchors, sig.anchor_embeddings):
                sim = _cosine_similarity(input_embedding, anchor_emb)
                if sim > best_sim:
                    best_sim = sim
                    best_anchor = anchor_text

            type_scores.append((task_type, best_sim, best_anchor))

        if not type_scores:
            return None

        # Sort by similarity descending
        type_scores.sort(key=lambda x: x[1], reverse=True)
        best_type, best_sim, best_anchor = type_scores[0]

        runner_up_type = type_scores[1][0] if len(type_scores) > 1 else ""
        runner_up_sim = type_scores[1][1] if len(type_scores) > 1 else 0.0

        gap = best_sim - runner_up_sim
        is_ambiguous = gap < 0.15

        # Confidence rules
        if best_sim > 0.75 and gap > 0.15:
            # High confidence — clear winner
            complexity = INTENT_SIGNATURES[best_type].complexity_hint
            return SemanticClassification(
                task_type=best_type,
                complexity=complexity,
                confidence=best_sim,
                source="semantic",
                matched_pattern=best_anchor,
                best_similarity=best_sim,
                runner_up_type=runner_up_type,
                runner_up_similarity=runner_up_sim,
                is_ambiguous=False,
            )
        elif best_sim > 0.60:
            # Moderate confidence — use match but flag ambiguity
            complexity = INTENT_SIGNATURES[best_type].complexity_hint
            return SemanticClassification(
                task_type=best_type,
                complexity=complexity,
                confidence=best_sim * 0.9,  # slightly lower confidence
                source="semantic",
                matched_pattern=best_anchor,
                best_similarity=best_sim,
                runner_up_type=runner_up_type,
                runner_up_similarity=runner_up_sim,
                is_ambiguous=is_ambiguous,
            )
        else:
            # Low confidence — not enough signal
            return None

    @staticmethod
    def _default_result() -> SemanticClassification:
        """Safe default when both passes fail."""
        return SemanticClassification(
            task_type="feature",
            complexity="medium",
            confidence=0.3,
            source="default",
            matched_pattern="",
            best_similarity=0.0,
            runner_up_type="",
            runner_up_similarity=0.0,
            is_ambiguous=True,
        )


# ═══════════════════════════════════════════════════════════════════════
# 3. CONVENIENCE — convert SemanticClassification to DeterministicClassification
# ═══════════════════════════════════════════════════════════════════════


def semantic_to_deterministic(sc: SemanticClassification) -> DeterministicClassification:
    """Convert a SemanticClassification to the existing DeterministicClassification format.

    This allows the rest of the system (classify_node, enforce_minimum_team)
    to work with a unified interface.
    """
    return DeterministicClassification(
        task_type=sc.task_type,
        complexity=sc.complexity,
        confidence=sc.confidence,
        matched_pattern=sc.matched_pattern,
        is_deterministic=sc.source in ("regex", "semantic"),
    )
