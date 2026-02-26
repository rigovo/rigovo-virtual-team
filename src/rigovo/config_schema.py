"""rigovo.yml schema — the intelligent, self-documenting project configuration.

This module defines the Pydantic models that parse and validate rigovo.yml.
The schema is designed to be:

1. Auto-generated: `rigovo init` detects tech stack and writes smart defaults
2. Layered: YAML (version-controlled) + .env (secrets) + CLI flags
3. Agent-customizable: per-agent model, rules, tools, cost caps
4. Quality-aware: gate thresholds, custom rules, severity levels
5. Budget-safe: per-task and monthly cost limits with alerts

Detection logic lives in config_detection.py.
Smart agent/quality rules live in config_rules.py.
"""

from __future__ import annotations

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
    approval_required: bool = False              # Require human approval
    max_retries: int = 5
    timeout_seconds: int = 600
    depends_on: list[str] = Field(default_factory=list)   # DAG dependencies by role
    input_contract: dict[str, Any] = Field(default_factory=dict)   # JSON-schema-like
    output_contract: dict[str, Any] = Field(default_factory=dict)  # JSON-schema-like


class CustomAgentSchema(BaseModel):
    """Custom agent plugin defined in rigovo.yml (item 9).

    Allows users to define entirely new agent roles beyond the built-in ones.
    Custom agents participate in the pipeline like any built-in agent.

    Example in rigovo.yml::

        custom_agents:
          - id: "i18n"
            name: "Internationalization Agent"
            role: "i18n"
            system_prompt: "You are an expert in i18n..."
            pipeline_after: "coder"
    """

    id: str                                      # Unique agent identifier
    name: str                                    # Display name
    role: str                                    # Role in pipeline
    system_prompt: str                           # Full system prompt
    pipeline_after: str = "coder"                # Insert after this role
    model: str = ""                              # LLM model override
    temperature: float = 0.0
    max_tokens: int = 4096
    rules: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    timeout_seconds: int = 600
    parallel: bool = False                       # Can run in parallel group
    depends_on: list[str] = Field(default_factory=list)
    input_contract: dict[str, Any] = Field(default_factory=dict)
    output_contract: dict[str, Any] = Field(default_factory=dict)


class TeamSchema(BaseModel):
    """Team-level configuration."""

    enabled: bool = True
    domain: str = "engineering"
    agents: dict[str, AgentOverride] = Field(default_factory=dict)
    custom_agents: list[CustomAgentSchema] = Field(default_factory=list)


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
    rigour_binary: str | None = None
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


class BudgetSchema(BaseModel):
    """Cost controls — prevent surprise bills."""

    max_cost_per_task: float = 25.00      # USD — soft warning only, never hard-stops
    max_tokens_per_task: int = 200_000
    monthly_budget: float = 100.00        # USD
    alert_at_percent: float = 0.80        # Alert at 80%
    hard_stop_at_percent: float = 1.0     # Stop at 100%


class ReplanSchema(BaseModel):
    """Policy-driven mid-run replanning controls."""

    enabled: bool = False
    max_replans_per_task: int = 1
    trigger_retry_count: int = 3
    trigger_gate_violation_count: int = 5
    trigger_contract_failures: bool = True


class OrchestrationSchema(BaseModel):
    """Pipeline and execution configuration."""

    max_retries: int = 5                  # LLM agents need patience
    max_agents_per_task: int = 8
    timeout_per_agent: int = 900          # 15 min batch ceiling (streaming uses idle)
    idle_timeout: int = 120               # 2 min idle = abort (no tokens received)
    parallel_agents: bool = True          # ON by default — independent agents run in parallel
    deep_mode: str = "final"              # never|final|ci|always|critical_only
    deep_pro: bool = False                # Use larger deep model when deep is enabled
    consultation: ConsultationSchema = Field(default_factory=lambda: ConsultationSchema())
    replan: ReplanSchema = Field(default_factory=lambda: ReplanSchema())

    budget: BudgetSchema = Field(default_factory=BudgetSchema)


class ConsultationSchema(BaseModel):
    """Inter-agent consultation policy (advisory-only messaging)."""

    enabled: bool = True
    max_question_chars: int = 1200
    max_response_chars: int = 1200
    allowed_targets: dict[str, list[str]] = Field(default_factory=lambda: {
        "planner": ["lead", "security", "devops"],
        "coder": ["reviewer", "security", "qa"],
        "reviewer": ["planner", "coder", "security", "qa", "devops", "sre", "lead"],
        "security": ["coder", "reviewer", "devops", "sre", "lead"],
        "qa": ["coder", "reviewer"],
        "devops": ["security", "sre", "reviewer", "lead"],
        "sre": ["devops", "security", "reviewer", "lead"],
        "lead": ["planner", "coder", "reviewer", "security", "qa", "devops", "sre"],
    })


class CloudSchema(BaseModel):
    """Cloud sync configuration (metadata only — never source code)."""

    enabled: bool = False
    sync_on_completion: bool = True
    sync_interval_seconds: int = 300


class CISchema(BaseModel):
    """CI/CD integration settings."""

    enabled: bool = False
    mode: str = "non-interactive"
    output_format: str = "json"
    fail_on_gate_failure: bool = True
    github_actions: bool = False
    gitlab_ci: bool = False


class LoggingSchema(BaseModel):
    """Logging configuration."""

    level: str = "info"
    structured: bool = False
    file: str = ".rigovo/rigovo.log"


class DatabaseSchema(BaseModel):
    """Database backend configuration."""

    backend: str = "sqlite"             # sqlite|postgres
    local_path: str = ".rigovo/local.db"


class PluginsSchema(BaseModel):
    """Plugin ecosystem configuration."""

    enabled: bool = True
    paths: list[str] = Field(default_factory=lambda: [".rigovo/plugins"])
    enabled_plugins: list[str] = Field(default_factory=list)
    allow_unsigned: bool = False
    enable_connector_tools: bool = False
    enable_mcp_tools: bool = False
    enable_action_tools: bool = False
    min_trust_level: str = "verified"  # community|verified|internal
    allowed_plugin_ids: list[str] = Field(default_factory=list)
    dry_run: bool = True


class IdentitySchema(BaseModel):
    """Enterprise identity + persona controls."""

    sso_enabled: bool = False
    auth_mode: str = "email_only"          # email_only|hybrid|sso_required
    provider: str = ""                    # okta|azuread|google|auth0|saml|oidc
    workos_organization_id: str = ""
    issuer_url: str = ""
    client_id: str = ""
    allowed_domains: list[str] = Field(default_factory=list)
    personas: dict[str, list[str]] = Field(default_factory=lambda: {
        "admin": [
            "workspace.manage",
            "teams.manage",
            "plugins.manage",
            "tasks.abort",
            "tasks.approve",
            "audit.read",
        ],
        "operator": [
            "tasks.run",
            "tasks.approve",
            "tasks.resume",
            "audit.read",
        ],
        "viewer": [
            "tasks.read",
            "audit.read",
        ],
    })


# ---------------------------------------------------------------------------
# Root schema
# ---------------------------------------------------------------------------


class RigovoConfig(BaseModel):
    """Root rigovo.yml schema.

    Single source of truth for project configuration.
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
    database: DatabaseSchema = Field(default_factory=DatabaseSchema)
    plugins: PluginsSchema = Field(default_factory=PluginsSchema)
    identity: IdentitySchema = Field(default_factory=IdentitySchema)


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

    data = config.model_dump(exclude_defaults=False)

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

    section_comments = {
        "version:": "\n# Schema version",
        "project:": "\n# ─── Project (auto-detected by `rigovo init`) ───",
        "teams:": "\n# ─── Teams & Agent Configuration ─────────────────",
        "quality:": "\n# ─── Quality Gates ───────────────────────────────",
        "approval:": "\n# ─── Approval Workflow ────────────────────────────",
        "orchestration:": "\n# ─── Orchestration ───────────────────────────────",
        "cloud:": "\n# ─── Cloud Sync ──────────────────────────────────",
        "ci:": "\n# ─── CI/CD Integration ───────────────────────────",
        "logging:": "\n# ─── Logging ─────────────────────────────────────",
        "database:": "\n# ─── Database ───────────────────────────────────",
        "plugins:": "\n# ─── Plugin Ecosystem ───────────────────────────",
        "identity:": "\n# ─── Identity & Personas ───────────────────────",
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
# Project auto-detection (delegates to config_detection + config_rules)
# ---------------------------------------------------------------------------


def detect_project_config(project_root: Path) -> RigovoConfig:
    """Analyze a project directory and generate intelligent rigovo.yml defaults.

    Detects: language, framework, test runner, package manager, monorepo,
    source/test directories, and tailors agent rules + quality gates.
    """
    from rigovo.config_detection import (
        detect_framework,
        detect_language_and_package_manager,
        detect_monorepo,
        detect_project_name,
        detect_source_dir,
        detect_test_dir,
        detect_test_framework,
    )
    from rigovo.config_rules import apply_smart_agent_rules, apply_smart_quality_rules

    config = RigovoConfig()
    project = config.project

    # Language & package manager
    project.language, project.package_manager = detect_language_and_package_manager(
        project_root,
    )

    # Project name
    project.name = detect_project_name(project_root, project.language)

    # Framework, test runner, monorepo, directories
    project.framework = detect_framework(project_root, project.language)
    project.test_framework = detect_test_framework(project_root, project.language)
    project.monorepo = detect_monorepo(project_root)
    project.source_dir = detect_source_dir(project_root, project.language)
    project.test_dir = detect_test_dir(project_root, project.language)

    # Tailor agent rules and quality gates
    apply_smart_agent_rules(config, project_root)
    apply_smart_quality_rules(config)

    return config
