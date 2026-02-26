"""Configuration — merges rigovo.yml (project settings) + .env (secrets).

Load order (later overrides earlier):
1. Built-in defaults
2. rigovo.yml (version-controlled project config)
3. .env file (secrets — gitignored, migrated to SQLite on first run)
4. Environment variables (CI overrides)
5. CLI flags (--verbose, --offline, etc.)
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings

from rigovo.config_schema import RigovoConfig, load_rigovo_yml


def _load_env_file(env_path: Path) -> dict[str, str]:
    """Parse a .env file and load its values into os.environ.

    This ensures all BaseSettings sub-models (LLMConfig, CloudConfig, etc.)
    can read the values — not just the top-level AppConfig.
    Returns the dict of key→value pairs that were loaded.
    """
    loaded: dict[str, str] = {}
    if not env_path.is_file():
        return loaded
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and value and key not in os.environ:
            os.environ[key] = value
            loaded[key] = value
    return loaded


class LLMConfig(BaseSettings):
    """LLM provider configuration. Loaded from environment variables.

    Supports all providers from the model catalog:
    Anthropic, OpenAI, Google, DeepSeek, Groq, Mistral, Ollama,
    plus any OpenAI-compatible endpoint via OPENAI_BASE_URL.
    """

    model: str = Field(default="claude-sonnet-4-6", alias="LLM_MODEL")

    # API keys — one per provider
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    google_api_key: str = Field(default="", alias="GOOGLE_API_KEY")
    deepseek_api_key: str = Field(default="", alias="DEEPSEEK_API_KEY")
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    mistral_api_key: str = Field(default="", alias="MISTRAL_API_KEY")

    # Endpoint overrides
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    openai_base_url: str = Field(default="", alias="OPENAI_BASE_URL")  # custom OpenAI-compatible

    model_config = {"extra": "ignore"}

    @property
    def provider(self) -> str:
        """Detect provider from model name (uses model_catalog for accuracy)."""
        try:
            from rigovo.infrastructure.llm.model_catalog import detect_provider
            return detect_provider(self.model)
        except ImportError:
            # Fallback heuristic if catalog not available
            if self.model.startswith("claude"):
                return "anthropic"
            if self.model.startswith(("gpt", "o1", "o3")):
                return "openai"
            if self.model.startswith("gemini"):
                return "google"
            if self.model.startswith("deepseek"):
                return "deepseek"
            if self.model.startswith(("llama", "mixtral", "gemma")):
                return "groq"
            if self.model.startswith(("mistral", "codestral")):
                return "mistral"
            return "ollama"

    @property
    def api_key(self) -> str:
        """Get the API key for the detected provider."""
        key_map = {
            "anthropic": self.anthropic_api_key,
            "openai": self.openai_api_key,
            "google": self.google_api_key,
            "deepseek": self.deepseek_api_key,
            "groq": self.groq_api_key,
            "mistral": self.mistral_api_key,
            "ollama": "",
            "openai_compatible": self.openai_api_key,  # fallback uses openai key
        }
        return key_map.get(self.provider, "")


class CloudConfig(BaseSettings):
    """Cloud sync configuration."""

    api_url: str = Field(default="https://api.rigovo.com", alias="RIGOVO_API_URL")
    api_key: str = Field(default="", alias="RIGOVO_API_KEY")
    enabled: bool = Field(default=True, alias="RIGOVO_CLOUD_ENABLED")

    model_config = {"extra": "ignore"}


class ApprovalConfig(BaseSettings):
    """Human-in-the-loop approval gates."""

    after_planning: bool = Field(default=True, alias="APPROVAL_AFTER_PLANNING")
    after_coding: bool = Field(default=False, alias="APPROVAL_AFTER_CODING")
    after_review: bool = Field(default=False, alias="APPROVAL_AFTER_REVIEW")
    before_commit: bool = Field(default=True, alias="APPROVAL_BEFORE_COMMIT")

    model_config = {"extra": "ignore"}


class IdentityConfig(BaseSettings):
    """Identity and SSO configuration.

    WORKOS_CLIENT_ID is a *public* identifier (like any OAuth client ID) and
    is safe to embed in the shipped binary.  End-users never need to set it.
    WORKOS_API_KEY is a *secret* used only for server-side admin operations
    (org/role lookup, invitations) — optional for basic auth which uses PKCE.
    """

    provider: str = Field(default="workos", alias="RIGOVO_IDENTITY_PROVIDER")
    auth_mode: str = Field(default="email_only", alias="RIGOVO_AUTH_MODE")
    workos_api_key: str = Field(default="", alias="WORKOS_API_KEY")
    # Public client ID — safe to ship in the binary.  Override via env for dev.
    workos_client_id: str = Field(
        default="client_01KECSP9SGAB8RYBZW08A3R9S7",
        alias="WORKOS_CLIENT_ID",
    )
    workos_organization_id: str = Field(default="", alias="WORKOS_ORGANIZATION_ID")

    model_config = {"extra": "ignore"}


class AppConfig(BaseSettings):
    """
    Root application configuration.

    Merges:
    - rigovo.yml (project settings, version-controlled)
    - .env (secrets, gitignored)
    - Environment variables (CI overrides)
    """

    # Project
    project_root: Path = Field(default_factory=Path.cwd)
    workspace_id: str = Field(default="", alias="RIGOVO_WORKSPACE_ID")

    # Database
    db_backend: str = Field(default="sqlite", alias="RIGOVO_DB_BACKEND")  # sqlite|postgres
    db_url: str = Field(default="", alias="RIGOVO_DB_URL")                 # Postgres DSN
    local_db_path: str = Field(default=".rigovo/local.db", alias="RIGOVO_LOCAL_DB")

    # Sub-configs (from .env)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    cloud: CloudConfig = Field(default_factory=CloudConfig)
    approval: ApprovalConfig = Field(default_factory=ApprovalConfig)
    identity: IdentityConfig = Field(default_factory=IdentityConfig)

    # Orchestration
    max_retries: int = Field(default=5, alias="RIGOVO_MAX_RETRIES")
    max_agents_per_task: int = Field(default=8, alias="RIGOVO_MAX_AGENTS")

    # The parsed rigovo.yml (populated by load_config)
    yml: RigovoConfig = Field(default_factory=RigovoConfig)

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @property
    def local_db_full_path(self) -> Path:
        return self.project_root / self.local_db_path


def load_config(project_root: Path | None = None) -> AppConfig:
    """
    Load configuration by merging rigovo.yml + .env + env vars.

    rigovo.yml provides project settings (teams, quality, orchestration).
    .env provides secrets (API keys) — migrated to encrypted SQLite on first run.
    Environment variables override both.
    """
    root = project_root or Path.cwd()

    # 1. Load rigovo.yml
    yml = load_rigovo_yml(root)

    # 2. Load .env into process environment so ALL BaseSettings sub-models
    #    (LLMConfig, CloudConfig, etc.) can read the values.
    env_path = root / ".env"
    _load_env_file(env_path)

    # 3. Create AppConfig (reads from env vars + .env via pydantic-settings)
    app_config = AppConfig(
        project_root=root,
        _env_file=str(env_path) if env_path.exists() else None,
    )
    app_config.yml = yml

    # 3. Merge YAML orchestration into app config
    app_config.max_retries = yml.orchestration.max_retries
    app_config.max_agents_per_task = yml.orchestration.max_agents_per_task

    # 3b. Merge YAML database defaults (secrets still come from env vars)
    app_config.db_backend = yml.database.backend
    app_config.local_db_path = yml.database.local_path

    # 4. Merge YAML approval into app config
    app_config.approval.after_planning = yml.approval.after_planning
    app_config.approval.after_coding = yml.approval.after_coding
    app_config.approval.after_review = yml.approval.after_review
    app_config.approval.before_commit = yml.approval.before_commit

    # 5. Merge cloud settings
    app_config.cloud.enabled = yml.cloud.enabled

    # 6. Merge identity settings
    app_config.identity.provider = yml.identity.provider or app_config.identity.provider
    app_config.identity.auth_mode = yml.identity.auth_mode
    if yml.identity.workos_organization_id:
        app_config.identity.workos_organization_id = yml.identity.workos_organization_id

    return app_config
