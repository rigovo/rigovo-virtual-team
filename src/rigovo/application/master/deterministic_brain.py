"""Deterministic Brain — zero-LLM decision layer for task routing.

This module provides INSTANT, RELIABLE decisions that the LLM-based
Master Agent can enhance but NEVER degrade.  Every function here runs
in < 50 ms with zero external calls.

The philosophy:
    The LLM decides WHAT to build (understanding natural language).
    The Deterministic Brain decides WHO builds it and in WHAT ORDER.

Four components:
1. **Keyword Classifier** — task_type from regex patterns (instant, <1ms)
2. **Semantic Classifier** — two-pass: regex + vector similarity (<50ms)
3. **Minimum Team Table** — floor team that the LLM cannot reduce
4. **Role Eligibility** — prevents nonsensical assignments (reviewer on empty repo)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# ═══════════════════════════════════════════════════════════════════════
# 1. KEYWORD CLASSIFIER — instant task_type from text patterns
# ═══════════════════════════════════════════════════════════════════════

# Ordered by priority — first match wins.
# Patterns are case-insensitive.  Each tuple is (pattern, task_type, complexity_hint).
_KEYWORD_RULES: list[tuple[str, str, str]] = [
    # New project — highest priority (explicit creation language)
    (
        r"\b(?:create\s+(?:new\s+)?(?:repo|project|app|application|service))\b",
        "new_project",
        "high",
    ),
    (
        r"\b(?:build\s+(?:a\s+|an\s+)?(?:new\s+)?(?:app|application|service|platform|system|saas|tool))\b",
        "new_project",
        "high",
    ),
    (
        r"\b(?:create\s+(?:a\s+|an\s+)?(?:app|application|service|platform|system|saas|tool))\b",
        "new_project",
        "high",
    ),
    (
        r"\b(?:create\s+(?:a\s+|an\s+)?new\s+folder)\b",
        "new_project",
        "medium",
    ),
    (
        r"\b(?:create\s+\w+(?:\s+\w+){0,4}\s+(?:saas|platform|system|service|application|app|tool)\s+in\s+(?:python|typescript|javascript|go|rust|java|node(?:\.js)?))\b",
        "new_project",
        "high",
    ),
    (r"\b(?:init(?:ialize)?|scaffold|bootstrap|start\s+(?:a\s+)?new)\b", "new_project", "medium"),
    (r"\b(?:new\s+repo(?:sitory)?|from\s+scratch|brand\s*new)\b", "new_project", "high"),
    (r"\b(?:set\s*up\s+(?:a\s+)?(?:project|repo|codebase))\b", "new_project", "medium"),
    # Security
    (
        r"\b(?:security\s+audit|vulnerability|cve|penetration|auth(?:entication|orization)\s+fix)\b",
        "security",
        "high",
    ),
    # Infrastructure
    (
        r"\b(?:deploy|docker|kubernetes|k8s|ci\s*/?\s*cd|terraform|infra(?:structure)?|helm)\b",
        "infra",
        "medium",
    ),
    # Bug fix
    (
        r"\b(?:fix\s+(?:\w+\s+)*bug|broken|crash(?:es|ing)?|error|regression|hotfix)\b",
        "bug",
        "medium",
    ),
    (r"\b(?:doesn'?t\s+work|not\s+working|fails?\s+(?:to|when)|issue\s+with)\b", "bug", "medium"),
    # Refactor
    (
        r"\b(?:refactor|clean\s*up|reorgani[sz]e|restructure|simplify|modernize)\b",
        "refactor",
        "medium",
    ),
    # Tests
    (
        r"\b(?:write\s+(?:\w+\s+)?tests?|add\s+(?:\w+\s+)?tests?|test\s+coverage|unit\s+test|integration\s+test|e2e)\b",
        "test",
        "medium",
    ),
    # Documentation
    (r"\b(?:document(?:ation)?|write\s+docs?|readme|api\s+docs?|jsdoc|docstring)\b", "docs", "low"),
    # Performance
    (
        r"\b(?:performance|optimi[sz]e|slow|latency|speed\s*up|profil(?:e|ing)|benchmark)\b",
        "performance",
        "medium",
    ),
    # Investigation
    (
        r"\b(?:investigate|debug|trace|diagnose|understand|figure\s+out|look\s+into)\b",
        "investigation",
        "medium",
    ),
    # Feature (broad catch — must be LAST)
    (r"\b(?:add|implement|develop|integrate|enable|support)\b", "feature", "medium"),
]

# Compile once at import time for speed.
_COMPILED_RULES = [
    (re.compile(pattern, re.IGNORECASE), task_type, complexity)
    for pattern, task_type, complexity in _KEYWORD_RULES
]


@dataclass
class DeterministicClassification:
    """Result of the keyword-based pre-classification."""

    task_type: str  # feature, bug, new_project, etc.
    complexity: str  # low, medium, high, critical
    confidence: float  # 0.0-1.0 — how sure we are
    matched_pattern: str  # which regex matched (for debugging)
    is_deterministic: bool  # True = keyword match; False = default


def classify_by_keywords(description: str) -> DeterministicClassification:
    """Classify a task description using keyword patterns.

    This runs in < 1ms with zero external calls.  The result is a FLOOR
    that the LLM-based Master Agent can upgrade but never downgrade.

    Returns:
        DeterministicClassification with task_type and complexity.
        If no pattern matches, returns feature/medium with low confidence.
    """
    text = description.strip()
    if not text:
        return DeterministicClassification(
            task_type="feature",
            complexity="medium",
            confidence=0.0,
            matched_pattern="",
            is_deterministic=False,
        )

    for compiled_re, task_type, complexity in _COMPILED_RULES:
        match = compiled_re.search(text)
        if match:
            return DeterministicClassification(
                task_type=task_type,
                complexity=complexity,
                confidence=0.85,
                matched_pattern=match.group(),
                is_deterministic=True,
            )

    return DeterministicClassification(
        task_type="feature",
        complexity="medium",
        confidence=0.3,
        matched_pattern="",
        is_deterministic=False,
    )


# ═══════════════════════════════════════════════════════════════════════
# 2. MINIMUM TEAM TABLE — deterministic floor per task type
# ═══════════════════════════════════════════════════════════════════════

# The LLM can ADD roles but NEVER REMOVE roles from this minimum.
# Every task type has a floor team that guarantees basic competence.

MINIMUM_TEAM: dict[str, list[str]] = {
    "new_project": ["planner", "lead", "coder", "reviewer"],
    "feature": ["planner", "coder", "reviewer"],
    "bug": ["coder", "reviewer"],
    "refactor": ["coder", "reviewer"],
    "test": ["coder", "qa"],
    "docs": ["planner", "coder"],
    "infra": ["planner", "devops", "reviewer"],
    "security": ["planner", "security", "coder", "reviewer"],
    "performance": ["coder", "reviewer"],
    "investigation": ["planner", "coder"],
}

# Default minimum if task_type not in table
_DEFAULT_MINIMUM = ["planner", "coder", "reviewer"]


@dataclass
class MinimumTeamSpec:
    """The non-negotiable minimum team for a task type."""

    task_type: str
    required_roles: list[str]  # Roles that MUST be present
    default_assignments: dict[str, str]  # role → default assignment text


def get_minimum_team(task_type: str, description: str = "") -> MinimumTeamSpec:
    """Get the minimum team composition for a task type.

    This is a FLOOR.  The Master Agent can add agents (security, lead, qa)
    but can NEVER produce a team with fewer roles than this.

    Args:
        task_type: Classified task type (from keyword classifier or LLM).
        description: Original task description (for assignment context).

    Returns:
        MinimumTeamSpec with required roles and default assignments.
    """
    required_roles = list(MINIMUM_TEAM.get(task_type, _DEFAULT_MINIMUM))

    # Generate sensible default assignments per role
    short_desc = description[:200] if description else "the requested task"
    assignments: dict[str, str] = {}
    for role in required_roles:
        assignments[role] = _default_assignment(role, task_type, short_desc)

    return MinimumTeamSpec(
        task_type=task_type,
        required_roles=required_roles,
        default_assignments=assignments,
    )


def _default_assignment(role: str, task_type: str, description: str) -> str:
    """Generate a sensible default assignment for a role + task_type."""
    _TEMPLATES: dict[str, dict[str, str]] = {
        "planner": {
            "new_project": f"Analyze requirements for: {description}. Design the project architecture, choose tech stack, and create a file-by-file implementation plan with verification steps.",
            "feature": f"Break down the feature request into subtasks: {description}. Identify which files to create/modify, define acceptance criteria, and plan the implementation order.",
            "bug": f"Investigate and diagnose the root cause of: {description}. Produce a fix plan with specific file and line targets.",
            "_default": f"Analyze requirements and produce a structured implementation plan for: {description}.",
        },
        "coder": {
            "new_project": f"Implement the full project structure as specified in the plan: {description}. Create all files, install dependencies, and verify the project builds successfully.",
            "feature": f"Implement the feature as described in the plan: {description}. Write production-quality code, run tests, and verify the build.",
            "bug": f"Fix the bug described in the plan: {description}. Apply the minimal, focused fix and verify it resolves the issue.",
            "_default": f"Implement the changes described in the plan for: {description}. Write clean code, run tests, verify the build.",
        },
        "reviewer": {
            "_default": f"Review all code changes for correctness, patterns, security, and maintainability. Verify the code matches the plan for: {description}.",
        },
        "security": {
            "_default": f"Audit all code changes for security vulnerabilities, authentication/authorization issues, and compliance: {description}.",
        },
        "qa": {
            "_default": f"Write and run tests for: {description}. Ensure adequate coverage for all changed code paths.",
        },
        "devops": {
            "_default": f"Set up infrastructure, CI/CD, and deployment configuration for: {description}.",
        },
        "lead": {
            "_default": f"Perform final architectural review of all work done for: {description}. Verify design decisions, code quality, and completeness.",
        },
    }

    role_templates = _TEMPLATES.get(
        role, {"_default": f"Complete your role's responsibilities for: {description}."}
    )
    return role_templates.get(
        task_type, role_templates.get("_default", f"Handle {role} tasks for: {description}.")
    )


# ═══════════════════════════════════════════════════════════════════════
# 3. ROLE ELIGIBILITY — prevent nonsensical agent assignments
# ═══════════════════════════════════════════════════════════════════════

# Roles that REQUIRE code to exist before they can do their job.
# If the workspace is empty AND no coder has run yet, these roles
# are DEFERRED (not removed) until their prerequisites are met.

ROLES_REQUIRING_CODE: set[str] = {"reviewer", "security", "qa"}

# Roles that can ALWAYS run, even on an empty workspace.
ROLES_ALWAYS_ELIGIBLE: set[str] = {"planner", "coder", "devops", "sre", "lead", "docs"}


def check_role_eligible(
    role: str,
    workspace_has_code: bool,
    coder_has_completed: bool,
    task_type: str,
) -> bool:
    """Check if a role is eligible to run right now.

    Args:
        role: The agent role to check.
        workspace_has_code: Whether the workspace already has source files.
        coder_has_completed: Whether at least one coder has completed in this pipeline.
        task_type: The task type (new_project, feature, etc.).

    Returns:
        True if the role can run now, False if it should be deferred.
    """
    if role in ROLES_ALWAYS_ELIGIBLE:
        return True

    if role in ROLES_REQUIRING_CODE:
        # Reviewer/security/QA need something to review/audit/test
        if workspace_has_code or coder_has_completed:
            return True
        # Exception: for bug/refactor on existing projects, code already exists
        if task_type in ("bug", "refactor", "performance") and workspace_has_code:
            return True
        return False

    # Unknown roles — allow by default
    return True


# ═══════════════════════════════════════════════════════════════════════
# 4. ENFORCE MINIMUM TEAM on LLM staffing plan
# ═══════════════════════════════════════════════════════════════════════


def enforce_minimum_team(
    llm_agents: list[dict[str, Any]],
    task_type: str,
    description: str = "",
) -> list[dict[str, Any]]:
    """Enforce the minimum team on an LLM-generated staffing plan.

    The LLM can ADD agents but NEVER produce fewer than the minimum.
    If the minimum team includes a role that the LLM omitted, we add
    a default agent for that role.

    Args:
        llm_agents: The agents list from the LLM's staffing plan.
        task_type: Classified task type.
        description: Original task description.

    Returns:
        Augmented agents list with minimum team guaranteed.
    """
    minimum = get_minimum_team(task_type, description)
    existing_roles = {a.get("role", "") for a in llm_agents}
    augmented = list(llm_agents)

    for role in minimum.required_roles:
        if role not in existing_roles:
            # The LLM omitted a required role — add a default agent
            instance_id = f"{role}-1"
            # Avoid instance_id collision
            existing_ids = {a.get("instance_id", "") for a in augmented}
            counter = 1
            while instance_id in existing_ids:
                counter += 1
                instance_id = f"{role}-{counter}"

            augmented.append(
                {
                    "instance_id": instance_id,
                    "role": role,
                    "specialisation": "general",
                    "assignment": minimum.default_assignments.get(role, ""),
                    "depends_on": [],
                    "tools_required": [],
                    "verification": f"Verify {role} output meets acceptance criteria.",
                }
            )

    return augmented


# ═══════════════════════════════════════════════════════════════════════
# 5. SEMANTIC CLASSIFICATION — upgraded two-pass entry point
# ═══════════════════════════════════════════════════════════════════════


async def classify_semantic(
    description: str,
    embedding_provider: Any | None = None,
) -> DeterministicClassification:
    """Two-pass classification: regex (Pass 1) + vector similarity (Pass 2).

    This is the RECOMMENDED entry point for the Deterministic Brain.
    It subsumes ``classify_by_keywords`` — if regex matches, it returns
    immediately.  If not, it falls through to semantic vector comparison
    against golden examples.

    If no embedding_provider is available, falls back to pure keyword
    classification (backward compatible).

    Args:
        description: The task description to classify.
        embedding_provider: Optional EmbeddingProvider for Pass 2.

    Returns:
        DeterministicClassification with task_type, complexity, and confidence.
    """
    # Fast path: try keywords first (always available, <1ms)
    keyword_result = classify_by_keywords(description)
    if keyword_result.is_deterministic and keyword_result.confidence >= 0.85:
        return keyword_result

    # Slow path: try semantic classifier if embedding provider available
    if embedding_provider is not None:
        try:
            from rigovo.application.master.intent_signatures import (
                SemanticClassifier,
                semantic_to_deterministic,
            )

            classifier = SemanticClassifier(embedding_provider)
            await classifier.initialize()
            semantic_result = await classifier.classify(description)

            # If semantic is more confident than keyword, use it
            if semantic_result.confidence > keyword_result.confidence:
                return semantic_to_deterministic(semantic_result)

        except Exception:
            # If semantic fails for any reason, fall back to keywords
            pass

    return keyword_result
