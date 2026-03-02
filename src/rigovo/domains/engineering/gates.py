"""Engineering domain quality gate configuration — Rigour integration.

Phase 7: Gates now carry role-relevance metadata. Each gate specifies
which roles it's primarily relevant to. Gates always run for all roles,
but the RigourSupervisor uses this metadata (via gate categories) to
adjust severity — irrelevant gates produce INFO-level violations instead
of blocking errors.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RigourGateConfig:
    """Configuration for a single Rigour quality gate."""

    gate_id: str
    name: str
    threshold: int | float  # Max violations (0 = zero-tolerance)
    category: str  # security, correctness, style, complexity, size
    enabled: bool = True
    # Phase 7: Which roles this gate is primarily relevant to.
    # Empty = relevant to all roles.
    relevant_roles: list[str] = field(default_factory=list)


def get_engineering_gates() -> list[RigourGateConfig]:
    """Default Rigour gate configuration for engineering domain.

    Phase 7: Gates are organized by category, which maps to
    ROLE_GATE_PROFILES in rigour_supervisor.py for per-role filtering.

    Categories:
    - security: Always enforced at full severity for ALL roles
    - correctness: Enforced for coder, qa, devops, sre
    - complexity: Primarily for coder output
    - style: Primarily for coder output
    - size: For coder and devops
    """
    return [
        # Zero-tolerance gates (security) — universal, never downgraded
        RigourGateConfig(
            "hallucinated-imports",
            "Hallucinated Imports",
            0,
            "correctness",
            relevant_roles=["coder", "qa", "devops", "sre"],
        ),
        RigourGateConfig(
            "hardcoded-secrets",
            "Hardcoded Secrets",
            0,
            "security",
            relevant_roles=[],  # Empty = all roles
        ),
        RigourGateConfig(
            "command-injection",
            "Command Injection",
            0,
            "security",
            relevant_roles=[],
        ),
        RigourGateConfig(
            "sql-injection",
            "SQL Injection",
            0,
            "security",
            relevant_roles=[],
        ),
        RigourGateConfig(
            "xss-patterns",
            "XSS Patterns",
            0,
            "security",
            relevant_roles=[],
        ),
        RigourGateConfig(
            "path-traversal",
            "Path Traversal",
            0,
            "security",
            relevant_roles=[],
        ),
        RigourGateConfig(
            "eval-usage",
            "Eval/Exec Usage",
            0,
            "security",
            relevant_roles=[],
        ),
        RigourGateConfig(
            "prototype-pollution",
            "Prototype Pollution",
            0,
            "security",
            relevant_roles=[],
        ),
        # Threshold gates (complexity) — primarily for coder
        RigourGateConfig(
            "file-size",
            "File Size",
            500,
            "size",
            relevant_roles=["coder", "devops"],
        ),
        RigourGateConfig(
            "function-length",
            "Function Length",
            50,
            "complexity",
            relevant_roles=["coder"],
        ),
        RigourGateConfig(
            "cyclomatic-complexity",
            "Cyclomatic Complexity",
            15,
            "complexity",
            relevant_roles=["coder"],
        ),
        RigourGateConfig(
            "nesting-depth",
            "Nesting Depth",
            4,
            "complexity",
            relevant_roles=["coder"],
        ),
        RigourGateConfig(
            "parameter-count",
            "Parameter Count",
            5,
            "complexity",
            relevant_roles=["coder"],
        ),
        RigourGateConfig(
            "duplicate-code",
            "Duplicate Code",
            10,
            "style",
            relevant_roles=["coder"],
        ),
        # Warning gates (style) — coder only
        RigourGateConfig(
            "missing-types",
            "Missing Type Hints",
            20,
            "style",
            relevant_roles=["coder"],
        ),
        RigourGateConfig(
            "missing-docstrings",
            "Missing Docstrings",
            10,
            "style",
            relevant_roles=["coder"],
        ),
        RigourGateConfig(
            "placeholder-comments",
            "Placeholder Comments",
            5,
            "style",
            relevant_roles=["coder", "qa"],
        ),
        RigourGateConfig(
            "console-logs",
            "Console.log/print Statements",
            3,
            "style",
            relevant_roles=["coder"],
        ),
        RigourGateConfig(
            "unused-variables",
            "Unused Variables",
            5,
            "correctness",
            relevant_roles=["coder", "qa"],
        ),
        RigourGateConfig(
            "unused-imports",
            "Unused Imports",
            3,
            "correctness",
            relevant_roles=["coder", "qa"],
        ),
        # Test quality gates — QA specific
        RigourGateConfig(
            "test-coverage",
            "Test Coverage",
            70,
            "correctness",
            relevant_roles=["qa"],
        ),
        RigourGateConfig(
            "test-assertions",
            "Test Missing Assertions",
            0,
            "correctness",
            relevant_roles=["qa"],
        ),
        # Dependency gates
        RigourGateConfig(
            "outdated-deps",
            "Outdated Dependencies",
            10,
            "correctness",
            relevant_roles=["coder", "devops"],
        ),
        RigourGateConfig(
            "known-cves",
            "Known CVEs in Dependencies",
            0,
            "security",
            relevant_roles=[],
        ),
    ]
