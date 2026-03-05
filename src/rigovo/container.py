"""Dependency Injection container — wires everything together at startup.

Composition Root pattern: all wiring happens here, nowhere else.
Modules depend on interfaces, container provides implementations.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from uuid import UUID

from rigovo.config import AppConfig
from rigovo.domain.interfaces.domain_plugin import DomainPlugin
from rigovo.domain.interfaces.event_emitter import EventEmitter
from rigovo.domain.interfaces.llm_provider import LLMProvider
from rigovo.domain.interfaces.quality_gate import QualityGate
from rigovo.domain.services.cost_calculator import CostCalculator, ModelPricing
from rigovo.domain.services.memory_ranker import MemoryRanker
from rigovo.domain.services.team_assembler import TeamAssemblerService
from rigovo.domains.engineering import EngineeringDomain
from rigovo.infrastructure.llm.llm_factory import LLMProviderFactory
from rigovo.infrastructure.persistence.sqlite_memory_repo import SqliteMemoryRepository
from rigovo.infrastructure.quality.gate_builder import QualityGateBuilder

logger = logging.getLogger(__name__)


class Container:
    """
    Application root — creates and holds all dependencies.

    Delegates creation to focused factories (LLMProviderFactory,
    QualityGateBuilder) and lazily initialises infrastructure.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config

        # Domain Services (pure, no infra deps)
        self.model_pricing = ModelPricing()
        self.cost_calculator = CostCalculator(self.model_pricing)
        self.team_assembler = TeamAssemblerService()
        self.memory_ranker = MemoryRanker()

        # Domain Plugins
        self.domains: dict[str, DomainPlugin] = {
            "engineering": EngineeringDomain(),
        }

        # Factories — LLM factory is rebuilt lazily once DB is available
        self._llm_factory: LLMProviderFactory | None = None
        self._gate_builder = QualityGateBuilder(config, self.domains)

        # Lazy infrastructure
        self._quality_gates: list[QualityGate] = []
        self._local_db = None  # Always local SQLite — settings/secrets
        self._app_db = None  # Application database — sqlite or postgres
        self._settings_repo = None
        self._event_emitter: EventEmitter | None = None
        self._sync_client = None
        self._plugin_registry = None

    def _get_local_db(self):
        """Local SQLite (always `.rigovo/local.db`).

        Used for encrypted settings (API keys, DSN, secrets).
        Bootstrap-safe: readable before postgres is available.
        """
        if self._local_db is None:
            from rigovo.infrastructure.persistence.sqlite_local import LocalDatabase

            db_path = self.config.local_db_full_path
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._local_db = LocalDatabase(str(db_path))
        return self._local_db

    def get_db(self):
        """Application database (sqlite or postgres based on config).

        Used for tasks, audit logs, memories, cost tracking.
        Settings/secrets always use local SQLite via get_settings_repo().
        """
        if self._app_db is None:
            backend = str(self.config.db_backend).strip().lower()

            if backend == "postgres":
                # Read DSN from encrypted local SQLite (bootstrap-safe)
                dsn = self.config.db_url
                if not dsn:
                    try:
                        repo = self.get_settings_repo()
                        dsn = repo.get("RIGOVO_DB_URL", "")
                    except Exception:
                        pass
                if not dsn:
                    logger.warning("Postgres configured but no DSN found — falling back to SQLite")
                    return self._get_local_db()

                from rigovo.infrastructure.persistence.postgres_local import (
                    PostgresDatabase,
                )

                self._app_db = PostgresDatabase(dsn)
            else:
                self._app_db = self._get_local_db()
        return self._app_db

    def get_settings_repo(self):
        """Encrypted settings repository — ALWAYS local SQLite.

        Never postgres.  Avoids chicken-and-egg: the DSN needed to connect
        to postgres is itself a secret stored in this repo.
        """
        if self._settings_repo is None:
            from rigovo.infrastructure.persistence.sqlite_settings_repo import (
                SqliteSettingsRepository,
            )

            self._settings_repo = SqliteSettingsRepository(self._get_local_db())
        return self._settings_repo

    def _get_llm_factory(self) -> LLMProviderFactory:
        """Get or create the LLM factory with live key resolution."""
        if self._llm_factory is None:
            settings = self.get_settings_repo()
            self._llm_factory = LLMProviderFactory(
                config=self.config.llm,
                key_resolver=settings.get,  # reads from encrypted SQLite
            )
        return self._llm_factory

    def get_event_emitter(self) -> EventEmitter:
        """Get or create the in-process event emitter."""
        if self._event_emitter is None:
            from rigovo.infrastructure.events import InProcessEventEmitter

            self._event_emitter = InProcessEventEmitter()
        return self._event_emitter

    def get_domain(self, domain_id: str) -> DomainPlugin:
        """Get a domain plugin by ID."""
        if domain_id not in self.domains:
            raise ValueError(f"Unknown domain: {domain_id}. Available: {list(self.domains.keys())}")
        return self.domains[domain_id]

    def get_llm(self, model: str | None = None) -> LLMProvider:
        """Get an LLM provider for a given model."""
        return self._get_llm_factory().get(model)

    def get_master_llm(self) -> LLMProvider:
        """Get the LLM provider used by the Master Agent.

        Uses LLM_MASTER_MODEL if set (allows faster/cheaper model for
        classification), otherwise falls back to the main model.
        """
        model = self.config.llm.master_model or self.config.llm.model
        return self._get_llm_factory().get(model)

    def get_agent_model(self, role: str) -> str:
        """Get the resolved model for an agent role.

        Priority: LLM_AGENT_MODELS env var > ROLE_DEFAULT_MODELS > LLM_MODEL
        """
        env_overrides = self.config.llm.agent_model_overrides
        if role in env_overrides:
            return env_overrides[role]
        try:
            from rigovo.infrastructure.llm.model_catalog import ROLE_DEFAULT_MODELS

            return ROLE_DEFAULT_MODELS.get(role, self.config.llm.model)
        except ImportError:
            return self.config.llm.model

    def llm_factory(self, model: str) -> LLMProvider:
        """Factory function for creating LLM providers (passed to graph)."""
        return self._get_llm_factory().get(model)

    def get_quality_gates(self) -> list[QualityGate]:
        """Get configured quality gates."""
        if not self._quality_gates:
            self._quality_gates = self._gate_builder.build()
        return self._quality_gates

    def get_sync_client(self):
        """Get or create the cloud sync client."""
        if self._sync_client is None:
            from rigovo.infrastructure.cloud.sync_client import (
                CloudSyncClient,
            )

            workspace_id = None
            if self.config.workspace_id:
                try:
                    workspace_id = UUID(self.config.workspace_id)
                except ValueError:
                    pass
            self._sync_client = CloudSyncClient(
                api_url=self.config.cloud.api_url,
                api_key=self.config.cloud.api_key,
                workspace_id=workspace_id,
            )
        return self._sync_client

    def get_embedding_provider(self):
        """Get the local embedding provider."""
        from rigovo.infrastructure.embeddings.local_embeddings import (
            LocalEmbeddingProvider,
        )

        return LocalEmbeddingProvider()

    def build_run_task_command(
        self,
        offline: bool = False,
        approval_handler: Callable | None = None,
        enable_streaming: bool = True,
        enable_parallel: bool = True,
        auto_approve: bool = True,
        ci_mode: bool = False,
    ):
        """Build a fully-wired RunTaskCommand."""
        from rigovo.application.commands.run_task import RunTaskCommand

        workspace_id = UUID(self.config.workspace_id) if self.config.workspace_id else UUID(int=0)

        cmd = RunTaskCommand(
            workspace_id=workspace_id,
            project_root=self.config.project_root,
            master_llm=self.get_master_llm(),
            llm_factory=self.llm_factory,
            cost_calculator=self.cost_calculator,
            team_assembler=self.team_assembler,
            quality_gates=self.get_quality_gates(),
            domain_plugins=self.domains,
            event_emitter=self.get_event_emitter(),
            db=self.get_db(),
            approval_handler=approval_handler,
            max_retries=self.config.max_retries,
            team_configs=self.config.yml.teams,
            consultation_policy=self.config.yml.orchestration.consultation.model_dump(),
            subagent_policy=self.config.yml.orchestration.subagents.model_dump(),
            deep_mode=self.config.yml.orchestration.deep_mode,
            deep_pro=self.config.yml.orchestration.deep_pro,
            replan_policy=self.config.yml.orchestration.replan.model_dump(),
            memory_repo=SqliteMemoryRepository(self.get_db()),
            embedding_provider=self.get_embedding_provider(),
            plugin_registry=self.get_plugin_registry() if self.config.yml.plugins.enabled else None,
            integration_policy={
                "enable_connector_tools": self.config.yml.plugins.enable_connector_tools,
                "enable_mcp_tools": self.config.yml.plugins.enable_mcp_tools,
                "enable_action_tools": self.config.yml.plugins.enable_action_tools,
                "min_trust_level": self.config.yml.plugins.min_trust_level,
                "allowed_plugin_ids": list(self.config.yml.plugins.allowed_plugin_ids),
                "allowed_connector_operations": list(
                    self.config.yml.plugins.allowed_connector_operations
                ),
                "allowed_mcp_operations": list(self.config.yml.plugins.allowed_mcp_operations),
                "allowed_action_operations": list(
                    self.config.yml.plugins.allowed_action_operations
                ),
                "allow_approval_required_actions": bool(
                    self.config.yml.plugins.allow_approval_required_actions
                ),
                "allow_sensitive_payload_keys": bool(
                    self.config.yml.plugins.allow_sensitive_payload_keys
                ),
                "allowed_shell_commands": list(self.config.yml.plugins.allowed_shell_commands),
                "dry_run": self.config.yml.plugins.dry_run,
            },
            ci_mode=ci_mode,
            offline=offline,
            enable_streaming=enable_streaming,
            enable_parallel=enable_parallel,
            auto_approve=auto_approve,
            budget_max_cost_per_task=float(self.config.yml.orchestration.budget.max_cost_per_task),
            budget_max_tokens_per_task=int(
                self.config.yml.orchestration.budget.max_tokens_per_task
            ),
        )
        # Inject per-agent model overrides from LLM_AGENT_MODELS env var
        cmd._agent_model_overrides = self.config.llm.agent_model_overrides
        return cmd

    def get_plugin_registry(self):
        """Get or create the local plugin registry."""
        if self._plugin_registry is None:
            from rigovo.infrastructure.plugins.loader import PluginRegistry

            self._plugin_registry = PluginRegistry(
                project_root=self.config.project_root,
                plugin_paths=self.config.yml.plugins.paths,
                enabled_plugins=self.config.yml.plugins.enabled_plugins,
            )
        return self._plugin_registry

    def reload_config(self) -> None:
        """Hot-reload rigovo.yml into the running container.

        Called after POST /v1/settings saves changes so the next task
        picks up new orchestration, team, and agent settings without
        restarting the engine process.

        Safe to call while no task is running.  Does NOT touch the
        database connections or settings repo (those are stable across
        reloads).
        """
        from rigovo.config_schema import load_rigovo_yml

        yml = load_rigovo_yml(self.config.project_root)
        self.config.yml = yml

        # Re-merge YAML orchestration into AppConfig
        self.config.max_retries = yml.orchestration.max_retries
        self.config.max_agents_per_task = yml.orchestration.max_agents_per_task
        self.config.db_backend = yml.database.backend
        self.config.local_db_path = yml.database.local_path
        self.config.approval.after_planning = yml.approval.after_planning
        self.config.approval.after_coding = yml.approval.after_coding
        self.config.approval.after_review = yml.approval.after_review
        self.config.approval.before_commit = yml.approval.before_commit
        self.config.cloud.enabled = yml.cloud.enabled
        self.config.identity.provider = yml.identity.provider or self.config.identity.provider
        self.config.identity.auth_mode = yml.identity.auth_mode
        if yml.identity.workos_organization_id:
            self.config.identity.workos_organization_id = yml.identity.workos_organization_id

        # Reset lazy caches that depend on config — they'll rebuild on next use
        self._llm_factory = None
        self._quality_gates = []
        self._gate_builder = QualityGateBuilder(self.config, self.domains)

        logger.info("Hot-reloaded rigovo.yml — next task will use updated settings")

    def close(self) -> None:
        """Clean up resources."""
        if self._app_db:
            self._app_db.close()
        if self._local_db and self._local_db is not self._app_db:
            self._local_db.close()
