"""Smart agent rules — language/framework-specific defaults for agents and gates.

This is the "intelligence" layer that auto-configures agent rules and quality
gates based on the detected tech stack. Called after project detection to tailor
the configuration for the specific project.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rigovo.config_schema import (
        AgentOverride,
        CustomRule,
        RigovoConfig,
        TeamSchema,
    )


def apply_smart_agent_rules(config: "RigovoConfig", root: Path) -> None:
    """Apply language/framework-specific rules to agents.

    For each agent role (coder, reviewer, qa), adds context-aware rules
    based on the detected language and framework.

    Args:
        config: RigovoConfig to modify (in-place).
        root: Project root (unused, kept for extensibility).
    """
    from rigovo.config_schema import AgentOverride, TeamSchema

    lang = config.project.language
    fw = config.project.framework
    team = config.teams.get("engineering", TeamSchema())

    # Coder rules
    coder = team.agents.get("coder", AgentOverride())
    _apply_coder_language_rules(coder, lang)
    _apply_coder_framework_rules(coder, fw)
    team.agents["coder"] = coder

    # Reviewer rules
    reviewer = team.agents.get("reviewer", AgentOverride())
    reviewer.rules.extend([
        "Check for security vulnerabilities (injection, XSS, SSRF)",
        "Verify error handling completeness",
        "Flag any hardcoded values that should be configurable",
    ])
    team.agents["reviewer"] = reviewer

    # QA rules based on test framework
    qa = team.agents.get("qa", AgentOverride())
    _apply_qa_rules(qa, config.project.test_framework)
    team.agents["qa"] = qa

    config.teams["engineering"] = team


def apply_smart_quality_rules(config: "RigovoConfig") -> None:
    """Tailor quality gates based on detected language.

    Adds language-specific linting rules enforced alongside Rigour gates.

    Args:
        config: RigovoConfig to modify (in-place).
    """
    from rigovo.config_schema import CustomRule

    lang = config.project.language

    if lang == "typescript":
        config.quality.custom_rules.extend([
            CustomRule(
                id="no-any-type",
                pattern=r":\s*any\b",
                message="Avoid 'any' type — use proper typing",
                severity="warning",
                file_types=["*.ts", "*.tsx"],
            ),
            CustomRule(
                id="no-console-log",
                pattern=r"console\.log\(",
                message="Remove console.log — use a proper logger",
                severity="warning",
                file_types=["*.ts", "*.tsx", "*.js", "*.jsx"],
            ),
        ])

    if lang == "python":
        config.quality.custom_rules.extend([
            CustomRule(
                id="no-print-statements",
                pattern=r"^\s*print\(",
                message="Use logging instead of print()",
                severity="info",
                file_types=["*.py"],
            ),
            CustomRule(
                id="no-bare-except",
                pattern=r"except\s*:",
                message="Avoid bare except — catch specific exceptions",
                severity="warning",
                file_types=["*.py"],
            ),
        ])


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _apply_coder_language_rules(coder: "AgentOverride", lang: str) -> None:
    """Add language-specific rules for the coder agent."""
    if lang == "typescript":
        coder.rules.extend([
            "Use TypeScript strict mode — no `any` types",
            "All exported functions must have JSDoc documentation",
            "Use const assertions where possible",
            "Prefer type-only imports for types",
        ])
    elif lang == "python":
        coder.rules.extend([
            "Use type hints on all function signatures",
            "Follow PEP 8 conventions",
            "Use dataclasses or Pydantic models for structured data",
            "Use pathlib.Path instead of os.path",
        ])
    elif lang == "rust":
        coder.rules.extend([
            "Use Result<T, E> for fallible operations — no unwrap() in production",
            "Add #[derive(Debug)] to all structs",
            "Use clippy::pedantic lint level",
        ])
    elif lang == "go":
        coder.rules.extend([
            "Handle all errors — no blank identifiers for error returns",
            "Use context.Context as first parameter for I/O functions",
            "Follow Go naming conventions (exported = PascalCase)",
        ])


def _apply_coder_framework_rules(coder: "AgentOverride", fw: str) -> None:
    """Add framework-specific rules for the coder agent."""
    if fw == "nextjs":
        coder.rules.extend([
            "Use App Router conventions (app/ directory)",
            "Prefer Server Components — use 'use client' only when needed",
            "Use next/image for all images",
        ])
    elif fw == "fastapi":
        coder.rules.extend([
            "Use Pydantic models for all request/response schemas",
            "Add OpenAPI descriptions to all endpoints",
            "Use dependency injection for services",
        ])
    elif fw == "django":
        coder.rules.extend([
            "Follow Django project structure conventions",
            "Use Django ORM — no raw SQL unless justified",
            "Add migrations for all model changes",
        ])
    elif fw == "express":
        coder.rules.extend([
            "Use middleware for cross-cutting concerns",
            "Validate request bodies with zod or joi",
            "Use async/await — no callback patterns",
        ])


def _apply_qa_rules(qa: "AgentOverride", test_fw: str) -> None:
    """Add test-framework-specific rules for the QA agent."""
    if test_fw == "pytest":
        qa.rules.extend([
            "Use pytest fixtures for test setup",
            "Aim for 80%+ branch coverage",
            "Use parametrize for testing multiple inputs",
        ])
    elif test_fw in ("jest", "vitest"):
        qa.rules.extend([
            "Use describe/it block structure",
            "Mock external dependencies with vi.mock or jest.mock",
            "Test both success and error paths",
        ])
