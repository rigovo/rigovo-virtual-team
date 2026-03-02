"""Intent Gate — zero-LLM intent detection that shapes the entire pipeline.

Runs AFTER classify, BEFORE route_team.  Zero API calls, <5ms.

The Intent Gate answers: "What does the user ACTUALLY want?"

Not every task is "go build code".  A brainstorming request should NOT
trigger a 12-agent pipeline with unlimited file reads that burns 500K tokens.

Intent Categories (mutually exclusive):
    brainstorm   — User is thinking out loud, exploring ideas.
                   NO codebase reading, NO coding agents, planner-only.
    research     — User wants investigation/analysis of existing code.
                   Limited file reads, single agent (planner or investigator).
    build        — User wants working code changes (feature, bug, refactor).
                   Full pipeline, full token budget.
    fix          — User wants a targeted bug fix.
                   Focused file reads, smaller team.

Each intent category sets hard constraints:
    - max_agents:      How many agents can run (1–12)
    - max_tool_rounds: How many tool loop iterations each agent gets (3–25)
    - max_file_reads:  How many files the planner can read (0–unlimited)
    - token_budget:    Per-task token ceiling (50K–500K)
    - planner_mode:    "survey" (read codebase first) or "think" (plan from description)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from rigovo.application.graph.state import TaskState

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Intent Profile — the constraints that shape the pipeline
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class IntentProfile:
    """Hard constraints for a detected intent category."""

    intent: str  # brainstorm | research | build | fix
    max_agents: int  # Pipeline agent cap
    max_tool_rounds: int  # Per-agent tool loop cap
    max_file_reads: int  # Planner file read cap (0 = no codebase access)
    token_budget: int  # Per-task token ceiling
    planner_mode: str  # "think" (no file reads) | "survey" (read codebase)
    confidence: float  # How sure we are about this intent (0.0–1.0)
    matched_signal: str  # What triggered this classification


# Intent profiles — tuned for cost efficiency
INTENT_PROFILES: dict[str, IntentProfile] = {
    "brainstorm": IntentProfile(
        intent="brainstorm",
        max_agents=2,  # planner only (+ maybe reviewer for feedback)
        max_tool_rounds=3,  # Minimal tool use
        max_file_reads=0,  # NO codebase reading
        token_budget=50_000,  # Very low budget
        planner_mode="think",
        confidence=0.0,
        matched_signal="",
    ),
    "research": IntentProfile(
        intent="research",
        max_agents=3,  # planner + maybe coder for exploration
        max_tool_rounds=10,  # Some file reading OK
        max_file_reads=15,  # Limited survey
        token_budget=150_000,
        planner_mode="survey",
        confidence=0.0,
        matched_signal="",
    ),
    "fix": IntentProfile(
        intent="fix",
        max_agents=5,  # planner + coder + reviewer + qa + security
        max_tool_rounds=20,
        max_file_reads=30,  # Focused reading
        token_budget=300_000,
        planner_mode="survey",
        confidence=0.0,
        matched_signal="",
    ),
    "build": IntentProfile(
        intent="build",
        max_agents=12,  # Full pipeline
        max_tool_rounds=25,
        max_file_reads=0,  # 0 = unlimited
        token_budget=500_000,
        planner_mode="survey",
        confidence=0.0,
        matched_signal="",
    ),
}


# ═══════════════════════════════════════════════════════════════════════
# Intent Detection Rules — ordered by priority (first match wins)
# ═══════════════════════════════════════════════════════════════════════

# Brainstorm signals — user is thinking, NOT requesting code
_BRAINSTORM_PATTERNS: list[tuple[re.Pattern[str], float]] = [
    (re.compile(r"\b(?:no\s+idea|not\s+sure|thinking\s+about|brainstorm)", re.I), 0.95),
    (re.compile(r"\b(?:what\s+should\s+(?:i|we)\s+build|help\s+me\s+think)", re.I), 0.90),
    (
        re.compile(r"\b(?:ideas?\s+for|suggest(?:ion)?s?\s+for|explore\s+(?:the\s+)?idea)", re.I),
        0.85,
    ),
    (
        re.compile(
            r"\b(?:planning\s+to\s+(?:create|build|start)|want\s+to\s+(?:create|build))\b.*(?:no\s+idea|not\s+sure|don'?t\s+know)",
            re.I,
        ),
        0.95,
    ),
    (re.compile(r"\b(?:should\s+(?:i|we)|what\s+(?:if|about)|how\s+(?:should|would))", re.I), 0.70),
    (re.compile(r"\b(?:concept|prototype\s+idea|mvp\s+idea|roadmap)", re.I), 0.80),
    (re.compile(r"\b(?:which\s+(?:tech|stack|framework|language)|what\s+tech)", re.I), 0.80),
]

# Research signals — user wants analysis, not code
_RESEARCH_PATTERNS: list[tuple[re.Pattern[str], float]] = [
    (re.compile(r"\b(?:investigate|figure\s+out|find\s+out|analyze|analyse)", re.I), 0.85),
    (re.compile(r"\b(?:why\s+(?:is|does|do)|what\s+(?:causes?|is\s+causing))", re.I), 0.80),
    (re.compile(r"\b(?:trace|debug|profile|diagnose|understand\s+(?:the|how|why))", re.I), 0.80),
    (re.compile(r"\b(?:research|study|compare|evaluate|assess)", re.I), 0.75),
    (re.compile(r"\b(?:explain|walk\s+me\s+through|how\s+does.*work)", re.I), 0.75),
    (re.compile(r"\b(?:audit|review\s+(?:the|our)|check\s+(?:the|our)|survey)", re.I), 0.70),
]

# Fix signals — user wants a targeted bug fix
_FIX_PATTERNS: list[tuple[re.Pattern[str], float]] = [
    (re.compile(r"\b(?:fix\s+(?:the|this|a)|hotfix|patch\s+(?:the|this))", re.I), 0.90),
    (
        re.compile(r"\b(?:broken|crash(?:es|ing)?|error(?:s)?|bug(?:s)?|failing|regression)", re.I),
        0.80,
    ),
    (re.compile(r"\b(?:not\s+working|doesn'?t\s+work|stopped\s+working)", re.I), 0.85),
    (re.compile(r"\b(?:resolve\s+(?:the|this)|troubleshoot)", re.I), 0.80),
]

# Build signals — user wants new code or features (default for ambiguous)
_BUILD_PATTERNS: list[tuple[re.Pattern[str], float]] = [
    (
        re.compile(
            r"\b(?:implement|add\s+(?:a\s+)?(?:new\s+)?|create\s+(?:a\s+)?(?:new\s+)?)", re.I
        ),
        0.85,
    ),
    (re.compile(r"\b(?:build|develop|write|code|scaffold|set\s*up)", re.I), 0.80),
    (re.compile(r"\b(?:refactor|rewrite|restructure|migrate|upgrade)", re.I), 0.80),
    (re.compile(r"\b(?:deploy|ship|release|publish)", re.I), 0.75),
]


def detect_intent(description: str, classification: dict[str, Any] | None = None) -> IntentProfile:
    """Detect user intent from task description + optional classification.

    Zero LLM calls.  Pure regex + heuristics.  <5ms.

    Priority order:
    1. Brainstorm (lowest cost — catch these EARLY to save tokens)
    2. Research (medium cost)
    3. Fix (focused cost)
    4. Build (full cost — default when nothing else matches)

    The classification from the deterministic brain is used as a
    cross-check: if keywords said "investigation" but intent says "build",
    the investigation signal wins (cheaper path).
    """
    desc_lower = description.lower().strip()

    # Short descriptions with vague intent → brainstorm
    word_count = len(desc_lower.split())
    if word_count < 15 and not any(
        p.search(desc_lower) for p, _ in _BUILD_PATTERNS + _FIX_PATTERNS
    ):
        # Short + no action verbs = likely brainstorming
        for pattern, conf in _BRAINSTORM_PATTERNS:
            m = pattern.search(desc_lower)
            if m:
                return _make_profile("brainstorm", conf, m.group())
        # Even without explicit brainstorm keywords, very short + vague = brainstorm
        if word_count < 8 and not any(
            p.search(desc_lower) for p, _ in _FIX_PATTERNS + _BUILD_PATTERNS + _RESEARCH_PATTERNS
        ):
            return _make_profile("brainstorm", 0.60, "short_vague_input")

    # Check brainstorm patterns first (cheapest path)
    best_brainstorm = _best_match(desc_lower, _BRAINSTORM_PATTERNS)
    if best_brainstorm and best_brainstorm[1] >= 0.80:
        return _make_profile("brainstorm", best_brainstorm[1], best_brainstorm[2])

    # Check research patterns
    best_research = _best_match(desc_lower, _RESEARCH_PATTERNS)
    if best_research and best_research[1] >= 0.75:
        return _make_profile("research", best_research[1], best_research[2])

    # Check fix patterns
    best_fix = _best_match(desc_lower, _FIX_PATTERNS)
    if best_fix and best_fix[1] >= 0.80:
        return _make_profile("fix", best_fix[1], best_fix[2])

    # Check build patterns
    best_build = _best_match(desc_lower, _BUILD_PATTERNS)
    if best_build and best_build[1] >= 0.75:
        return _make_profile("build", best_build[1], best_build[2])

    # Cross-check with classification from deterministic brain
    if classification:
        task_type = classification.get("task_type", "")
        if task_type == "investigation":
            return _make_profile("research", 0.70, f"classification={task_type}")
        if task_type == "bug":
            return _make_profile("fix", 0.70, f"classification={task_type}")
        if task_type in ("docs", "test"):
            return _make_profile("build", 0.70, f"classification={task_type}")

    # Default: build (full pipeline) — safest default
    return _make_profile("build", 0.50, "default_fallback")


def _best_match(
    text: str, patterns: list[tuple[re.Pattern[str], float]]
) -> tuple[str, float, str] | None:
    """Find the highest-confidence pattern match."""
    best: tuple[str, float, str] | None = None
    for pattern, confidence in patterns:
        m = pattern.search(text)
        if m:
            if best is None or confidence > best[1]:
                best = (pattern.pattern, confidence, m.group())
    return best


def _make_profile(intent: str, confidence: float, signal: str) -> IntentProfile:
    """Create an IntentProfile by cloning the base and setting confidence/signal."""
    base = INTENT_PROFILES[intent]
    return IntentProfile(
        intent=base.intent,
        max_agents=base.max_agents,
        max_tool_rounds=base.max_tool_rounds,
        max_file_reads=base.max_file_reads,
        token_budget=base.token_budget,
        planner_mode=base.planner_mode,
        confidence=confidence,
        matched_signal=signal,
    )


# ═══════════════════════════════════════════════════════════════════════
# Graph Node — wired between classify and route_team
# ═══════════════════════════════════════════════════════════════════════


async def intent_gate_node(state: TaskState) -> dict[str, Any]:
    """Detect intent and inject constraints into state.

    This node runs in <5ms and sets:
    - intent_profile: The full intent profile dict
    - budget_max_tokens_per_task: Override token budget based on intent
    - planner_mode: "think" or "survey" (used by planner prompt)

    Subsequent nodes (route_team, assemble, execute_agent) read these
    constraints to limit team size, tool rounds, and file reads.
    """
    description = state["description"]
    classification = state.get("classification")
    deterministic = state.get("deterministic_classification")

    # Use deterministic classification if full classification not available
    class_hint = classification or deterministic

    profile = detect_intent(description, class_hint)

    events = list(state.get("events", []))
    events.append(
        {
            "type": "intent_detected",
            "intent": profile.intent,
            "confidence": profile.confidence,
            "matched_signal": profile.matched_signal,
            "max_agents": profile.max_agents,
            "max_tool_rounds": profile.max_tool_rounds,
            "max_file_reads": profile.max_file_reads,
            "token_budget": profile.token_budget,
            "planner_mode": profile.planner_mode,
        }
    )

    logger.info(
        "Intent Gate: intent=%s confidence=%.2f signal=%r → "
        "max_agents=%d tool_rounds=%d file_reads=%s tokens=%dk",
        profile.intent,
        profile.confidence,
        profile.matched_signal,
        profile.max_agents,
        profile.max_tool_rounds,
        profile.max_file_reads or "unlimited",
        profile.token_budget // 1000,
    )

    return {
        "intent_profile": {
            "intent": profile.intent,
            "max_agents": profile.max_agents,
            "max_tool_rounds": profile.max_tool_rounds,
            "max_file_reads": profile.max_file_reads,
            "token_budget": profile.token_budget,
            "planner_mode": profile.planner_mode,
            "confidence": profile.confidence,
            "matched_signal": profile.matched_signal,
        },
        "budget_max_tokens_per_task": profile.token_budget,
        "events": events,
    }
