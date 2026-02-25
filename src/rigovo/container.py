"""Dependency Injection container — wires everything together at startup.

Composition Root pattern: all wiring happens here, nowhere else.
Modules depend on interfaces, container provides implementations.
"""

from __future__ import annotations

from typing import Any, Callable
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
from rigovo.infrastructure.quality.gate_builder import QualityGateBuilder


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

        # Factories
        self._llm_factory = LLMProviderFactory(config.llm)
        self._gate_builder = QualityGateBuilder(config, self.domains)

        # Lazy infrastructure
        self._quality_gates: list[QualityGate] = []
        self._db = None
        self._event_emitter: EventEmitter | None = None
        self._sync_client = None

    def get_db(self):
        """Get or create the local SQLite database."""
        if self._db is None:
            from rigovo.infrastructure.persistence.sqlite_local import (
                LocalDatabase,
            )
            db_path = self.config.local_db_full_path
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db = LocalDatabase(str(db_path))
        return self._db

    def get_event_emitter(self) -> EventEmitter:
        """Get or create the in-process event emitter."""
        if self._event_emitter is None:
            from rigovo.infrastructure.events import InProcessEventEmitter
            self._event_emitter = InProcessEventEmitter()
        return self._event_emitter

    def get_domain(self, domain_id: str) -> DomainPlugin:
        """Get a domain plugin by ID."""
        if domain_id not in self.domains:
            raise ValueError(
                f"Unknown domain: {domain_id}. "
                f"Available: {list(self.domains.keys())}"
            )
        return self.domains[domain_id]

    def get_llm(self, model: str | None = None) -> LLMProvider:
        """Get an LLM provider for a given model."""
        return self._llm_factory.get(model)

    def get_master_llm(self) -> LLMProvider:
        """Get the LLM provider used by the Master Agent."""
        return self._llm_factory.get(self.config.llm.model)

    def llm_factory(self, model: str) -> LLMProvider:
        """Factory function for creating LLM providers (passed to graph)."""
        return self._llm_factory.get(model)

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
        enable_parallel: bool = False,
        auto_approve: bool = True,
    ):
        """Build a fully-wired RunTaskCommand."""
        from rigovo.application.commands.run_task import RunTaskCommand

        workspace_id = (
            UUID(self.config.workspace_id)
            if self.config.workspace_id
            else UUID(int=0)
        )

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
            approval_handler=approval_handler,
            max_retries=self.config.max_retries,
            consultation_policy=self.config.yml.orchestration.consultation.model_dump(),
            offline=offline,
            enable_streaming=enable_streaming,
            enable_parallel=enable_parallel,
            auto_approve=auto_approve,
        )

    def close(self) -> None:
        """Clean up resources."""
        if self._db:
            self._db.close()
