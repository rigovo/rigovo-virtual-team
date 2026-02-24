"""rigovo.yml schema — the intelligent, self-documenting project configuration.

This module defines the Pydantic models that parse and validate rigovo.yml.
The schema is designed to be:

1. Auto-generated: `rigovo init` detects tech stack and writes smart defaults
2. Layered: YAML (version-controlled) + .env (secrets) + CLI flags
3. Agent-customizable: per-agent model, rules, tools, cost caps
4. Quality-aware: gate thresholds, custom rules, severity levels
5. Budget-safe: per-task and monthly cost limits with alerts
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sub-schemas
# ---------------------------------------------------------------------------

class ProjectSchema(BaseModel):
    """Auto-detected project metadata. Written by `rigovo init`."""

    name: str = ""
    language: str = ""           # python, typescript, rust, go, java ...
    framework: str = ""          # nextjs, fastapi, express, django ...
    monorepo: bool = False
    test_framework: str = ""     # pytest, jest, vitest, cargo-test ...
    package_manager: str = ""    # npm, pnpm, yarn, pip, poetry, cargo ...
    source_dir: str = "src"      # conventional source directory
    test_dir: str = "tests"      # conventional test directory


class AgentOverride(BaseModel):
    """Per-agent customisation inside rigovo.yml."""

    model: str = ""                              # Override LLM model
    temperature: float = 0.0
    max_tokens: int = 4096
    rules: list[str] = Field(default_factory=list)    # CTO-defined rules
    tools: list[str] = Field(default_factory=list)     # Restrict tool set
    approval_required: bool = False              # Require human approval for this agent
    max_retries: int = 3
    timeout_seconds: int = 300


class TeamSchema(BaseModel):
    """Team-level configuration."""

    enabled: bool = True
    domain: str = "engineering"
    agents: dict[str, AgentOverride] = Field(default_factory=dict)


class GateOverride(BaseModel):
    """Per-gate threshold and severity override."""

    enabled: bool = True
    severity: str = "error"       # error | warning | info
    threshold: float = 0.0        # 0 = zero-tolerance


class CustomRule(BaseModel):
    """Project-specific quality rule (regex-based)."""

    id: str
    pattern: str
    message: str
    severity: str = "warning"
    file_types: list[str] = Field(default_factory=lambda: ["*.py"])


class QualitySchema(BaseModel):
    """Quality gate configuration."""

    rigour_enabled: bool = True
    rigour_binary: str | None = None   # auto-detect if None
    rigour_timeout: int = 120

    gates: dict[str, GateOverride] = Field(default_factory=lambda: {
        "hardcoded-secrets": GateOverride(severity="error", threshold=0),
        "file-size": GateOverride(severity="warning", threshold=500),
        "function-length": GateOverride(severity="warning", threshold=50),
        "hallucinated-imports": GateOverride(severity="error", threshold=0),
    })

    custom_rules: list[CustomRule] = Field(default_factory=list)


class ApprovalSchema(BaseModel):
    """Human-in-the-loop approval gates."""

    after_planning: bool = True
    after_coding: bool = False
    after_review: bool = False
    before_commit: bool = True

    auto_approve: list[dict[str, Any]] = Field(default_factory=list)
    # e.g. [{"type": "test", "max_files": 3}, {"type": "docs"}]


class BudgetSchema(BaseModel):
    """Cost controls — prevent surprise bills."""

    max_cost_per_task: float = 2.00       # USD
    max_tokens_per_task: int = 200_000
    monthly_budget: float = 100.00        # USD
    alert_at_percent: float = 0.80        # Alert at 80%
    hard_stop_at_percent: float = 1.0     # Stop at 100%


class OrchestrationSchema(BaseModel):
    """Pipeline and execution configuration."""

    max_retries: int = 3
    max_agents_per_task: int = 8
    timeout_per_agent: int = 300          # seconds
    parallel_agents: bool = False

    budget: BudgetSchema = Field(default_factory=BudgetSchema)


class CloudSchema(BaseModel):
    """Cloud sync configuration (metadata only — never source code)."""

    enabled: bool = False
    sync_on_completion: bool = True
    sync_interval_seconds: int = 300


class CISchema(BaseModel):
    """CI/CD integration settings."""

    enabled: bool = False
    mode: str = "non-interactive"         # non-interactive | minimal
    output_format: str = "json"           # json | text
    fail_on_gate_failure: bool = True
    github_actions: bool = False
    gitlab_ci: bool = False


class LoggingSchema(BaseModel):
    """Logging configuration."""

    level: str = "info"                   # debug | info | warning | error
    structured: bool = False              # JSON logging
    file: str = ".rigovo/rigovo.log"


# ---------------------------------------------------------------------------
# Root schema
# ---------------------------------------------------------------------------

class RigovoConfig(BaseModel):
    """
    Root rigovo.yml schema.

    This is the single source of truth for project configuration.
    Secrets (API keys) live in .env — everything else lives here.
    """

    version: str = "1"

    project: ProjectSchema = Field(default_factory=ProjectSchema)
    teams: dict[str, TeamSchema] = Field(default_factory=lambda: {
        "engineering": TeamSchema(domain="engineering"),
    })
    quality: QualitySchema = Field(default_factory=QualitySchema)
    approval: ApprovalSchema = Field(default_factory=ApprovalSchema)
    orchestration: OrchestrationSchema = Field(default_factory=OrchestrationSchema)
    cloud: CloudSchema = Field(default_factory=CloudSchema)
    ci: CISchema = Field(default_factory=CISchema)
    logging: LoggingSchema = Field(default_factory=LoggingSchema)


# ---------------------------------------------------------------------------
# YAML I/O
# ---------------------------------------------------------------------------

def load_rigovo_yml(project_root: Path) -> RigovoConfig:
    """Load and validate rigovo.yml from project root."""
    yml_path = project_root / "rigovo.yml"
    if not yml_path.is_file():
        return RigovoConfig()  # All defaults

    raw = yaml.safe_load(yml_path.read_text(encoding="utf-8")) or {}
    return RigovoConfig.model_validate(raw)


def save_rigovo_yml(config: RigovoConfig, project_root: Path) -> Path:
    """Write rigovo.yml with human-friendly comments."""
    yml_path = project_root / "rigovo.yml"

    # Generate the YAML body from the model
    data = config.model_dump(exclude_defaults=False)

    # Build commented YAML
    lines = [
        "# ═══════════════════════════════════════════════════════════════",
        "# rigovo.yml — Rigovo Teams project configuration",
        "# Generated by `rigovo init`. Version-control this file.",
        "# Secrets (API keys) belong in .env, NOT here.",
        "# ═══════════════════════════════════════════════════════════════",
        "",
    ]

    yaml_str = yaml.dump(
        data,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=100,
    )

    # Insert section comments
    section_comments = {
        "version:": "\n# Schema version",
        "project:": "\n# ─── Project (auto-detected by `rigovo init`) ───────────────────────",
        "teams:": "\n# ─── Teams & Agent Configuration ─────────────────────────────────────\n# Override per-agent: model, rules, tools, approval, timeouts",
        "quality:": "\n# ─── Quality Gates ───────────────────────────────────────────────────\n# Powered by Rigour CLI (deterministic AST checks, no LLM opinions)",
        "approval:": "\n# ─── Approval Workflow ────────────────────────────────────────────────\n# Human-in-the-loop gates. Set to false to auto-approve.",
        "orchestration:": "\n# ─── Orchestration ───────────────────────────────────────────────────\n# Pipeline, retries, and budget controls",
        "cloud:": "\n# ─── Cloud Sync ──────────────────────────────────────────────────────\n# Syncs task metadata (never source code) to app.rigovo.com",
        "ci:": "\n# ─── CI/CD Integration ───────────────────────────────────────────────\n# Non-interactive mode for GitHub Actions / GitLab CI",
        "logging:": "\n# ─── Logging ─────────────────────────────────────────────────────────",
    }

    for yaml_line in yaml_str.splitlines():
        for key, comment in section_comments.items():
            if yaml_line.startswith(key):
                lines.append(comment)
                break
        lines.append(yaml_line)

    yml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return yml_path


# ---------------------------------------------------------------------------
# Project auto-detection → smart defaults
# ---------------------------------------------------------------------------

def detect_project_config(project_root: Path) -> RigovoConfig:
    """
    Analyze a project directory and generate intelligent rigovo.yml defaults.

    Detects: language, framework, test runner, package manager, monorepo,
    source/test directories, and tailors agent rules + quality gates.
    """
    config = RigovoConfig()
    project = config.project

    # --- Language & Package Manager ---
    lang_indicators = [
        ("pyproject.toml", "python", "poetry"),
        ("requirements.txt", "python", "pip"),
        ("Pipfile", "python", "pipenv"),
        ("setup.py", "python", "setuptools"),
        ("tsconfig.json", "typescript", ""),
        ("package.json", "javascript", ""),
        ("Cargo.toml", "rust", "cargo"),
        ("go.mod", "go", "go"),
        ("Gemfile", "ruby", "bundler"),
        ("pom.xml", "java", "maven"),
        ("build.gradle", "java", "gradle"),
        ("composer.json", "php", "composer"),
        ("mix.exs", "elixir", "mix"),
    ]

    for filename, lang, pkg_mgr in lang_indicators:
        if (project_root / filename).is_file():
            if not project.language:
                project.language = lang
            if pkg_mgr and not project.package_manager:
                project.package_manager = pkg_mgr
            break

    # JS/TS package manager detection
    if project.language in ("javascript", "typescript"):
        if (project_root / "pnpm-lock.yaml").is_file():
            project.package_manager = "pnpm"
        elif (project_root / "yarn.lock").is_file():
            project.package_manager = "yarn"
        elif (project_root / "bun.lockb").is_file():
            project.package_manager = "bun"
        else:
            project.package_manager = "npm"

    # --- Project name ---
    project.name = _detect_project_name(project_root, project.language)

    # --- Framework detection ---
    project.framework = _detect_framework(project_root, project.language)

    # --- Test framework ---
    project.test_framework = _detect_test_framework(project_root, project.language)

    # --- Monorepo detection ---
    project.monorepo = _detect_monorepo(project_root)

    # --- Source & test directories ---
    project.source_dir = _detect_source_dir(project_root, project.language)
    project.test_dir = _detect_test_dir(project_root, project.language)

    # --- Tailor agent rules based on detection ---
    _apply_smart_agent_rules(config, project_root)

    # --- Tailor quality gates ---
    _apply_smart_quality_rules(config)

    return config


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

def _detect_project_name(root: Path, language: str) -> str:
    """Extract project name from manifest files.

    Tries manifest files in order: package.json, pyproject.toml, Cargo.toml.
    Falls back to directory name if no manifest is found.

    Args:
        root: Project root directory path.
        language: Detected language (unused, kept for consistency).

    Returns:
        Project name from manifest, or directory name as fallback.
    """
    import json

    # Try Node.js package.json first
    if (root / "package.json").is_file():
        try:
            pkg = json.loads((root / "package.json").read_text())
            return pkg.get("name", root.name)
        except (json.JSONDecodeError, OSError):
            pass

    # Try Python pyproject.toml
    if (root / "pyproject.toml").is_file():
        try:
            content = (root / "pyproject.toml").read_text()
            for line in content.splitlines():
                if line.strip().startswith("name"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except (OSError, IndexError):
            pass

    # Try Rust Cargo.toml
    if (root / "Cargo.toml").is_file():
        try:
            content = (root / "Cargo.toml").read_text()
            for line in content.splitlines():
                if line.strip().startswith("name"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except (OSError, IndexError):
            pass

    # Fallback: use directory name
    return root.name


def _detect_framework(root: Path, language: str) -> str:
    """Detect the primary framework for the detected language.

    Searches dependency files in order of framework popularity.
    Returns the first matching framework, or empty string if none detected.

    Supported frameworks by language:
    - JavaScript/TypeScript: Next.js, React, Vue, Angular, Express, etc.
    - Python: FastAPI, Django, Flask, Starlette, etc.
    - Rust: Actix, Axum, Rocket
    - Go: Gin, Fiber, Echo

    Args:
        root: Project root directory path.
        language: Detected language.

    Returns:
        Framework name (lowercase), or empty string.
    """
    import json

    # JavaScript/TypeScript frameworks
    if language in ("javascript", "typescript"):
        if (root / "package.json").is_file():
            try:
                pkg = json.loads((root / "package.json").read_text())
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}

                # Framework detection priority (first match wins)
                fw_map = [
                    ("next", "nextjs"), ("nuxt", "nuxt"), ("@angular/core", "angular"),
                    ("svelte", "svelte"), ("vue", "vue"), ("react", "react"),
                    ("express", "express"), ("fastify", "fastify"), ("hono", "hono"),
                    ("@nestjs/core", "nestjs"), ("koa", "koa"),
                ]
                for dep, name in fw_map:
                    if dep in deps:
                        return name
            except (json.JSONDecodeError, OSError):
                pass

    # Python frameworks
    if language == "python":
        # Check pyproject.toml and requirements.txt for framework detection
        for depfile in ("pyproject.toml", "requirements.txt"):
            if (root / depfile).is_file():
                try:
                    content = (root / depfile).read_text().lower()
                    fw_map = [
                        ("fastapi", "fastapi"), ("django", "django"), ("flask", "flask"),
                        ("starlette", "starlette"), ("tornado", "tornado"),
                        ("aiohttp", "aiohttp"), ("litestar", "litestar"),
                    ]
                    for dep, name in fw_map:
                        if dep in content:
                            return name
                except OSError:
                    pass

    # Rust frameworks
    if language == "rust":
        if (root / "Cargo.toml").is_file():
            try:
                content = (root / "Cargo.toml").read_text().lower()
                if "actix" in content:
                    return "actix"
                if "axum" in content:
                    return "axum"
                if "rocket" in content:
                    return "rocket"
            except OSError:
                pass

    # Go frameworks
    if language == "go":
        if (root / "go.mod").is_file():
            try:
                content = (root / "go.mod").read_text().lower()
                if "gin-gonic" in content:
                    return "gin"
                if "fiber" in content:
                    return "fiber"
                if "echo" in content:
                    return "echo"
            except OSError:
                pass

    return ""


def _detect_test_framework(root: Path, language: str) -> str:
    """Detect the test runner for the detected language.

    Checks dependency files for test framework packages.
    Returns the first matching test framework, or language default.

    Supported test frameworks:
    - JavaScript/TypeScript: Vitest, Jest, Mocha, Playwright
    - Python: pytest, unittest
    - Rust: cargo-test (built-in)
    - Go: go-test (built-in)

    Args:
        root: Project root directory path.
        language: Detected language.

    Returns:
        Test framework name (lowercase), or empty string.
    """
    import json

    # JavaScript/TypeScript test runners
    if language in ("javascript", "typescript"):
        if (root / "package.json").is_file():
            try:
                pkg = json.loads((root / "package.json").read_text())
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}

                # Check in priority order
                if "vitest" in deps:
                    return "vitest"
                if "jest" in deps or "@jest/core" in deps:
                    return "jest"
                if "mocha" in deps:
                    return "mocha"
                if "playwright" in deps or "@playwright/test" in deps:
                    return "playwright"
            except (json.JSONDecodeError, OSError):
                pass

    # Python test runners
    if language == "python":
        for depfile in ("pyproject.toml", "requirements.txt"):
            if (root / depfile).is_file():
                try:
                    content = (root / depfile).read_text().lower()
                    if "pytest" in content:
                        return "pytest"
                    if "unittest" in content:
                        return "unittest"
                except OSError:
                    pass

    # Rust uses cargo test (built-in)
    if language == "rust":
        return "cargo-test"

    # Go uses go test (built-in)
    if language == "go":
        return "go-test"

    return ""


def _detect_monorepo(root: Path) -> bool:
    """Check if the project is a monorepo.

    Detects monorepo configuration via:
    - Monorepo tool config files (Lerna, Nx, Turbo, pnpm, Rush)
    - workspaces field in package.json
    - Multiple packages in packages/ directory

    Args:
        root: Project root directory path.

    Returns:
        True if monorepo indicators found, False otherwise.
    """
    # Check for explicit monorepo tool configs
    indicators = [
        "lerna.json", "nx.json", "turbo.json", "pnpm-workspace.yaml",
        "rush.json",
    ]
    if any((root / f).is_file() for f in indicators):
        return True

    # Check for workspaces in package.json (npm/yarn workspaces)
    import json
    if (root / "package.json").is_file():
        try:
            pkg = json.loads((root / "package.json").read_text())
            if "workspaces" in pkg:
                return True
        except (json.JSONDecodeError, OSError):
            pass

    # Check for multiple packages/apps directories with their own package.json files
    try:
        dirs_with_pkg = sum(
            1 for d in (root / "packages").iterdir()
            if d.is_dir() and (d / "package.json").is_file()
        ) if (root / "packages").is_dir() else 0
        return dirs_with_pkg > 1
    except OSError:
        return False


def _detect_source_dir(root: Path, language: str) -> str:
    """Find the conventional source directory.

    Checks for common source directory names in order of popularity.
    Returns the first existing directory, or default "src" if none found.

    Args:
        root: Project root directory path.
        language: Detected language (unused, kept for consistency).

    Returns:
        Source directory name ("src", "lib", "app", "source", or default "src").
    """
    candidates = ["src", "lib", "app", "source"]
    for c in candidates:
        if (root / c).is_dir():
            return c
    return "src"


def _detect_test_dir(root: Path, language: str) -> str:
    """Find the conventional test directory.

    Checks for common test directory names in priority order.
    Returns the first existing directory, or language-specific default.

    Args:
        root: Project root directory path.
        language: Detected language ("javascript"/"typescript" defaults to "__tests__").

    Returns:
        Test directory name ("tests", "test", "__tests__", etc.).
    """
    candidates = ["tests", "test", "__tests__", "spec", "specs"]
    for c in candidates:
        if (root / c).is_dir():
            return c

    # Language-specific defaults
    if language in ("javascript", "typescript"):
        return "__tests__"
    return "tests"


def _apply_smart_agent_rules(config: RigovoConfig, root: Path) -> None:
    """Apply language/framework-specific rules to agents.

    This is the "intelligence" layer — Rigovo learns what good looks like
    for each tech stack and pre-configures agent rules accordingly.

    For each agent role (coder, reviewer, qa), adds context-aware rules:
    - Coder: language idioms, framework best practices, type hints, etc.
    - Reviewer: security patterns, error handling conventions
    - QA: test framework idioms, coverage targets, parametrization strategies

    Args:
        config: RigovoConfig to modify (in-place).
        root: Project root (unused, kept for extensibility).

    Side effects:
        Modifies config.teams["engineering"].agents in place.
    """
    lang = config.project.language
    fw = config.project.framework
    team = config.teams.get("engineering", TeamSchema())

    # Coder rules
    coder = team.agents.get("coder", AgentOverride())

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

    # Framework-specific rules
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
    test_fw = config.project.test_framework
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
    team.agents["qa"] = qa

    config.teams["engineering"] = team


def _apply_smart_quality_rules(config: RigovoConfig) -> None:
    """Tailor quality gates based on detected language.

    Adds language-specific linting rules (e.g., no 'any' types for TypeScript,
    no print() for Python). These are enforced alongside the Rigour gates.

    Args:
        config: RigovoConfig to modify (in-place).

    Side effects:
        Appends CustomRule entries to config.quality.custom_rules.
    """
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
