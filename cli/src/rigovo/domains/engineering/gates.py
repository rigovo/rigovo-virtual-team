"""Engineering domain quality gate configuration — Rigour integration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RigourGateConfig:
    """Configuration for a single Rigour quality gate."""

    gate_id: str
    name: str
    threshold: int | float  # Max violations (0 = zero-tolerance)
    category: str  # security, correctness, style, complexity, size
    enabled: bool = True


def get_engineering_gates() -> list[RigourGateConfig]:
    """Default Rigour gate configuration for engineering domain."""
    return [
        # Zero-tolerance gates (security + correctness)
        RigourGateConfig("hallucinated-imports", "Hallucinated Imports", 0, "correctness"),
        RigourGateConfig("hardcoded-secrets", "Hardcoded Secrets", 0, "security"),
        RigourGateConfig("command-injection", "Command Injection", 0, "security"),
        RigourGateConfig("sql-injection", "SQL Injection", 0, "security"),
        RigourGateConfig("xss-patterns", "XSS Patterns", 0, "security"),
        RigourGateConfig("path-traversal", "Path Traversal", 0, "security"),
        RigourGateConfig("eval-usage", "Eval/Exec Usage", 0, "security"),
        RigourGateConfig("prototype-pollution", "Prototype Pollution", 0, "security"),

        # Threshold gates (style + complexity)
        RigourGateConfig("file-size", "File Size", 500, "size"),
        RigourGateConfig("function-length", "Function Length", 50, "complexity"),
        RigourGateConfig("cyclomatic-complexity", "Cyclomatic Complexity", 15, "complexity"),
        RigourGateConfig("nesting-depth", "Nesting Depth", 4, "complexity"),
        RigourGateConfig("parameter-count", "Parameter Count", 5, "complexity"),
        RigourGateConfig("duplicate-code", "Duplicate Code", 10, "style"),

        # Warning gates (informational, don't block)
        RigourGateConfig("missing-types", "Missing Type Hints", 20, "style"),
        RigourGateConfig("missing-docstrings", "Missing Docstrings", 10, "style"),
        RigourGateConfig("todo-comments", "TODO Comments", 5, "style"),
        RigourGateConfig("console-logs", "Console.log/print Statements", 3, "style"),
        RigourGateConfig("unused-variables", "Unused Variables", 5, "correctness"),
        RigourGateConfig("unused-imports", "Unused Imports", 3, "correctness"),

        # Test quality gates
        RigourGateConfig("test-coverage", "Test Coverage", 70, "correctness"),
        RigourGateConfig("test-assertions", "Test Missing Assertions", 0, "correctness"),

        # Dependency gates
        RigourGateConfig("outdated-deps", "Outdated Dependencies", 10, "correctness"),
        RigourGateConfig("known-cves", "Known CVEs in Dependencies", 0, "security"),
    ]
