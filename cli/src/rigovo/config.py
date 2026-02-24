"""Configuration — loads rigovo.yml + .env into typed settings."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings


class LLMConfig(BaseSettings):
    """LLM provider configuration. Loaded from environment variables."""

    model: str = Field(default="claude-sonnet-4-5-20250929", alias="LLM_MODEL")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")

    @property
    def provider(self) -> str:
        """Detect provider from model name."""
        if self.model.startswith("claude"):
            return "anthropic"
        if self.model.startswith(("gpt", "o1")):
            return "openai"
        if self.model.startswith(("llama", "mixtral")):
            return "groq"
        return "ollama"

    @property
    def api_key(self) -> str:
        """Get the API key for the detected provider."""
        key_map = {
            "anthropic": self.anthropic_api_key,
            "openai": self.openai_api_key,
            "groq": self.groq_api_key,
            "ollama": "",
        }
        return key_map.get(self.provider, "")


class CloudConfig(BaseSettings):
    """Cloud sync configuration."""

    api_url: str = Field(default="https://api.rigovo.com", alias="RIGOVO_API_URL")
    api_key: str = Field(default="", alias="RIGOVO_API_KEY")
    enabled: bool = Field(default=True, alias="RIGOVO_CLOUD_ENABLED")


class ApprovalConfig(BaseSettings):
    """Human-in-the-loop approval gates."""

    after_planning: bool = Field(default=True, alias="APPROVAL_AFTER_PLANNING")
    after_coding: bool = Field(default=False, alias="APPROVAL_AFTER_CODING")
    after_review: bool = Field(default=False, alias="APPROVAL_AFTER_REVIEW")
    before_commit: bool = Field(default=True, alias="APPROVAL_BEFORE_COMMIT")


class AppConfig(BaseSettings):
    """Root application configuration."""

    # Project
    project_root: Path = Field(default_factory=Path.cwd)
    workspace_id: str = Field(default="", alias="RIGOVO_WORKSPACE_ID")

    # Database
    local_db_path: str = Field(default=".rigovo/local.db", alias="RIGOVO_LOCAL_DB")

    # Sub-configs
    llm: LLMConfig = Field(default_factory=LLMConfig)
    cloud: CloudConfig = Field(default_factory=CloudConfig)
    approval: ApprovalConfig = Field(default_factory=ApprovalConfig)

    # Orchestration
    max_retries: int = Field(default=3, alias="RIGOVO_MAX_RETRIES")
    max_agents_per_task: int = Field(default=8, alias="RIGOVO_MAX_AGENTS")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def local_db_full_path(self) -> Path:
        return self.project_root / self.local_db_path


def load_config(project_root: Path | None = None) -> AppConfig:
    """Load configuration from environment and rigovo.yml."""
    root = project_root or Path.cwd()
    return AppConfig(project_root=root)
