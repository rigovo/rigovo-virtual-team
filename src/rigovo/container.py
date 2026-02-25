"""Dependency Injection container — wires everything together at startup."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from rigovo.config import AppConfig
from rigovo.domain.interfaces.domain_plugin import DomainPlugin
from rigovo.domain.interfaces.event_emitter import EventEmitter
from rigovo.domain.interfaces.llm_provider import LLMProvider
from rigovo.domain.interfaces.quality_gate import QualityGate
from rigovo.domain.services.cost_calculator import CostCalculator, ModelPricing
from rigovo.domain.services.team_assembler import TeamAssemblerService
from rigovo.domain.services.memory_ranker import MemoryRanker
from rigovo.domains.engineering import EngineeringDomain


class Container:
    """
    Application root — creates and holds all dependencies.

    Follows Composition Root pattern: all wiring happens here,
    nowhere else. Modules depend on interfaces, container provides
    implementations.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config

        # --- Domain Services (pure, no infra deps) ---
        self.model_pricing = ModelPricing()
        self.cost_calculator = CostCalculator(self.model_pricing)
        self.team_assembler = TeamAssemblerService()
        self.memory_ranker = MemoryRanker()

        # --- Domain Plugins ---
        self.domains: dict[str, DomainPlugin] = {
            "engineering": EngineeringDomain(),
        }

        # --- Infrastructure (lazy init — set up when needed) ---
        self._llm_providers: dict[str, LLMProvider] = {}
        self._quality_gates: list[QualityGate] = []
        self._master_llm: LLMProvider | None = None
        self._db = None
        self._event_emitter: EventEmitter | None = None
        self._sync_client = None

    # --- Database ---

    def get_db(self):
        """Get or create the local SQLite database."""
        if self._db is None:
            from rigovo.infrastructure.persistence.sqlite_local import LocalDatabase
            db_path = self.config.local_db_full_path
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db = LocalDatabase(str(db_path))
        return self._db

    # --- Event Emitter ---

    def get_event_emitter(self) -> EventEmitter:
        """Get or create the in-process event emitter."""
        if self._event_emitter is None:
            from rigovo.infrastructure.events import InProcessEventEmitter
            self._event_emitter = InProcessEventEmitter()
        return self._event_emitter

    # --- Domain Plugins ---

    def get_domain(self, domain_id: str) -> DomainPlugin:
        """Get a domain plugin by ID."""
        if domain_id not in self.domains:
            raise ValueError(
                f"Unknown domain: {domain_id}. "
                f"Available: {list(self.domains.keys())}"
            )
        return self.domains[domain_id]

    # --- LLM Providers ---

    def get_llm(self, model: str | None = None) -> LLMProvider:
        """Get an LLM provider for a given model. Lazy-init and cached."""
        model = model or self.config.llm.model

        if model not in self._llm_providers:
            self._llm_providers[model] = self._create_llm_provider(model)

        return self._llm_providers[model]

    def get_master_llm(self) -> LLMProvider:
        """Get the LLM provider used by the Master Agent."""
        if self._master_llm is None:
            self._master_llm = self.get_llm(self.config.llm.model)
        return self._master_llm

    def llm_factory(self, model: str) -> LLMProvider:
        """Factory function for creating LLM providers (passed to graph nodes)."""
        return self.get_llm(model)

    # --- Quality Gates ---

    def get_quality_gates(self) -> list[QualityGate]:
        """Get configured quality gates. Creates Rigour gate if not yet built."""
        if not self._quality_gates:
            self._quality_gates = self._build_quality_gates()
        return self._quality_gates

    def _build_quality_gates(self) -> list[QualityGate]:
        """
        Build quality gates from rigovo.yml + domain plugins.

        Priority:
        1. rigovo.yml quality.gates overrides (user-configurable thresholds)
        2. Domain plugin gate configs (sensible defaults)
        3. Rigour CLI when available, built-in AST fallback otherwise
        """
        from rigovo.domain.entities.quality import ViolationSeverity
        from rigovo.infrastructure.quality.rigour_gate import (
            RigourGateConfig,
            RigourQualityGate,
        )

        yml_quality = self.config.yml.quality
        all_configs: list[RigourGateConfig] = []

        # Build configs from rigovo.yml gate overrides
        severity_map = {
            "error": ViolationSeverity.ERROR,
            "warning": ViolationSeverity.WARNING,
            "info": ViolationSeverity.INFO,
        }

        for gate_id, gate_override in yml_quality.gates.items():
            all_configs.append(
                RigourGateConfig(
                    gate_id=gate_id,
                    name=gate_id.replace("-", " ").title(),
                    threshold=gate_override.threshold,
                    severity=severity_map.get(gate_override.severity, ViolationSeverity.ERROR),
                    enabled=gate_override.enabled,
                )
            )

        # Add any extra gates from domain plugins (deduped)
        existing_ids = {c.gate_id for c in all_configs}
        for domain in self.domains.values():
            domain_gates = domain.get_quality_gates()
            for gate_cfg in domain_gates:
                if gate_cfg.gate_id not in existing_ids:
                    all_configs.append(
                        RigourGateConfig(
                            gate_id=gate_cfg.gate_id,
                            name=gate_cfg.name,
                            threshold=gate_cfg.threshold,
                        )
                    )

        return [RigourQualityGate(
            gate_configs=all_configs,
            rigour_binary=yml_quality.rigour_binary,
            timeout_seconds=yml_quality.rigour_timeout,
        )]

    # --- Cloud Sync ---

    def get_sync_client(self):
        """Get or create the cloud sync client."""
        if self._sync_client is None:
            from rigovo.infrastructure.cloud.sync_client import CloudSyncClient
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

    # --- Embedding Provider ---

    def get_embedding_provider(self):
        """Get the local embedding provider."""
        from rigovo.infrastructure.embeddings.local_embeddings import LocalEmbeddingProvider
        return LocalEmbeddingProvider()

    # --- Run Task Command ---

    def build_run_task_command(self, offline: bool = False):
        """Build a fully-wired RunTaskCommand."""
        from rigovo.application.commands.run_task import RunTaskCommand

        workspace_id = UUID(self.config.workspace_id) if self.config.workspace_id else UUID(int=0)

        return RunTaskCommand(
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
            max_retries=self.config.max_retries,
            offline=offline,
        )

    # --- Private ---

    def _create_llm_provider(self, model: str) -> LLMProvider:
        """Create an LLM provider for a specific model."""
        provider = self.config.llm.provider

        if provider == "anthropic" or model.startswith("claude"):
            from rigovo.infrastructure.llm.anthropic_provider import AnthropicProvider
            return AnthropicProvider(
                api_key=self.config.llm.anthropic_api_key,
                model=model,
            )
        elif provider == "openai" or model.startswith(("gpt", "o1")):
            from rigovo.infrastructure.llm.openai_provider import OpenAIProvider
            return OpenAIProvider(
                api_key=self.config.llm.openai_api_key,
                model=model,
            )
        else:
            raise ValueError(
                f"Unsupported LLM provider for model '{model}'. "
                f"Supported: anthropic (claude-*), openai (gpt-*, o1-*)"
            )

    def close(self) -> None:
        """Clean up resources."""
        if self._db:
            self._db.close()
