"""RunTaskCommand — orchestrates the full task lifecycle.

This is the application-layer entry point for `rigovo run`.
It wires together classification, routing, assembly, execution,
quality gates, approval, memory storage, and finalization.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Callable
from uuid import UUID, uuid4

from rigovo.application.graph.builder import GraphBuilder
from rigovo.application.graph.state import TaskState
from rigovo.application.master.classifier import TaskClassifier
from rigovo.application.master.enricher import ContextEnricher
from rigovo.application.master.evaluator import AgentEvaluator
from rigovo.application.master.router import TeamRouter
from rigovo.domain.entities.agent import Agent
from rigovo.domain.entities.audit_entry import AuditAction, AuditEntry
from rigovo.domain.entities.task import Task, TaskStatus
from rigovo.domain.entities.team import Team
from rigovo.domain.interfaces.domain_plugin import DomainPlugin
from rigovo.domain.interfaces.event_emitter import EventEmitter
from rigovo.domain.interfaces.llm_provider import LLMProvider
from rigovo.domain.interfaces.quality_gate import QualityGate
from rigovo.domain.services.cost_calculator import CostCalculator
from rigovo.domain.services.team_assembler import TeamAssemblerService
from rigovo.infrastructure.persistence.sqlite_local import LocalDatabase
from rigovo.infrastructure.persistence.sqlite_task_repo import SqliteTaskRepository
from rigovo.infrastructure.persistence.sqlite_audit_repo import SqliteAuditRepository
from rigovo.infrastructure.persistence.sqlite_cost_repo import SqliteCostRepository

logger = logging.getLogger(__name__)


class RunTaskCommand:
    """
    Executes a task through the full pipeline.

    Responsibilities:
    - Creates task entity and persists it
    - Builds initial graph state
    - Runs the graph (sequential or LangGraph)
    - Emits events for terminal UI
    - Persists results (task, costs, audit)
    - Syncs to cloud if configured
    """

    def __init__(
        self,
        workspace_id: UUID,
        project_root: Path,
        master_llm: LLMProvider,
        llm_factory: Callable[[str], LLMProvider],
        cost_calculator: CostCalculator,
        team_assembler: TeamAssemblerService,
        quality_gates: list[QualityGate],
        domain_plugins: dict[str, DomainPlugin],
        event_emitter: EventEmitter | None = None,
        db: LocalDatabase | None = None,
        approval_handler: Callable | None = None,
        max_retries: int = 3,
        offline: bool = False,
    ) -> None:
        self._workspace_id = workspace_id
        self._project_root = project_root
        self._master_llm = master_llm
        self._llm_factory = llm_factory
        self._cost_calculator = cost_calculator
        self._team_assembler = team_assembler
        self._quality_gates = quality_gates
        self._domain_plugins = domain_plugins
        self._event_emitter = event_emitter
        self._db = db
        self._approval_handler = approval_handler
        self._max_retries = max_retries
        self._offline = offline

        # Master Agent sub-services
        self._classifier = TaskClassifier(master_llm)
        self._enricher = ContextEnricher(master_llm)
        self._evaluator = AgentEvaluator()
        self._router = TeamRouter(master_llm)

        # Repos (initialized if db provided)
        self._task_repo = SqliteTaskRepository(db) if db else None
        self._audit_repo = SqliteAuditRepository(db) if db else None
        self._cost_repo = SqliteCostRepository(db) if db else None

    async def execute(
        self,
        description: str,
        team_name: str | None = None,
    ) -> dict[str, Any]:
        """
        Execute a task end-to-end.

        Returns:
            Final state dict with status, costs, files changed, etc.
        """
        start_time = time.monotonic()
        task_id = uuid4()

        # --- 1. Create and persist task ---
        task = Task(
            workspace_id=self._workspace_id,
            description=description,
            id=task_id,
        )
        task.start()

        if self._task_repo:
            await self._task_repo.save(task)

        await self._emit("task_started", {
            "task_id": str(task_id),
            "description": description,
        })

        # --- 2. Build initial state ---
        # Resolve team and domain
        domain_id = "engineering"  # Default; router picks if multiple
        domain_plugin = self._domain_plugins.get(domain_id)

        # Get agent role definitions from domain plugin
        agent_roles = {}
        if domain_plugin:
            agent_roles = {r.role_id: r for r in domain_plugin.get_agent_roles()}

        # Build initial graph state
        initial_state: TaskState = {
            "task_id": str(task_id),
            "workspace_id": str(self._workspace_id),
            "project_root": str(self._project_root),
            "description": description,
            "domain": domain_id,
            # Classification (filled by classify node)
            "task_type": None,
            "complexity": None,
            # Team (filled by assemble node)
            "team_config": {},
            "current_agent_index": 0,
            "current_agent_role": None,
            # Execution
            "agent_outputs": [],
            "gate_results": {},
            "retry_count": 0,
            "max_retries": self._max_retries,
            "fix_packet": None,
            # Approval
            "approval_status": None,
            "approval_feedback": None,
            "current_checkpoint": None,
            # Cost tracking
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "budget_max_cost_per_task": 2.00,
            "budget_max_tokens_per_task": 200_000,
            # Memory
            "memories_to_store": [],
            # Final
            "status": "running",
            "events": [],
        }

        # --- 3. Build agents from domain plugin ---
        agents = self._build_agents(domain_id, agent_roles)

        # --- 4. Build and run graph ---
        graph_builder = GraphBuilder(
            llm_factory=self._llm_factory,
            master_llm=self._master_llm,
            cost_calculator=self._cost_calculator,
            quality_gates=self._quality_gates,
            approval_handler=self._approval_handler,
        )

        try:
            final_state = await graph_builder.run_sequential(
                initial_state=initial_state,
                agents=agents,
            )
        except Exception as e:
            logger.exception("Task execution failed: %s", e)
            task.fail()
            if self._task_repo:
                await self._task_repo.save(task)
            await self._emit("task_failed", {
                "task_id": str(task_id),
                "error": str(e),
            })
            return {
                "status": "failed",
                "error": str(e),
                "task_id": str(task_id),
            }

        # --- 5. Update task from final state ---
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        status = final_state.get("status", "completed")

        if status == "completed":
            task.complete()
        elif status == "rejected":
            task.reject(feedback=final_state.get("approval_feedback", ""))
        else:
            task.fail()

        task.total_tokens = final_state.get("total_tokens", 0)
        task.total_cost_usd = final_state.get("total_cost_usd", 0.0)
        task.duration_ms = elapsed_ms

        if self._task_repo:
            await self._task_repo.save(task)

        # --- 6. Audit log ---
        if self._audit_repo:
            await self._audit_repo.append(
                AuditEntry(
                    workspace_id=self._workspace_id,
                    task_id=task_id,
                    action=AuditAction.TASK_COMPLETED,
                    agent_role="system",
                    summary=f"Task {status}: {description[:100]}",
                    metadata={
                        "total_tokens": task.total_tokens,
                        "total_cost_usd": task.total_cost_usd,
                        "duration_ms": elapsed_ms,
                        "status": status,
                    },
                )
            )

        # --- 7. Emit finalization event ---
        agent_outputs = final_state.get("agent_outputs", [])
        await self._emit("task_finalized", {
            "type": "task_finalized",
            "status": status,
            "total_cost": task.total_cost_usd,
            "total_tokens": task.total_tokens,
            "agents_run": [o.get("role", "?") for o in agent_outputs],
            "retries": final_state.get("retry_count", 0),
            "memories_stored": len(final_state.get("memories_to_store", [])),
        })

        return {
            "status": status,
            "task_id": str(task_id),
            "total_tokens": task.total_tokens,
            "total_cost_usd": task.total_cost_usd,
            "duration_ms": elapsed_ms,
            "agents_run": [o.get("role", "?") for o in agent_outputs],
            "files_changed": self._extract_files_changed(agent_outputs),
        }

    def _build_agents(
        self,
        domain_id: str,
        agent_roles: dict[str, Any],
    ) -> list[Agent]:
        """Build agent entities from domain role definitions."""
        agents = []
        for role_id, role_def in agent_roles.items():
            agent = Agent(
                workspace_id=self._workspace_id,
                team_id=uuid4(),  # Placeholder
                name=role_def.name,
                role=role_id,
                llm_model=role_def.default_llm_model,
                system_prompt=role_def.default_system_prompt,
            )
            agents.append(agent)
        return agents

    @staticmethod
    def _extract_files_changed(agent_outputs: list[dict[str, Any]]) -> list[str]:
        """Extract all files changed across all agent outputs."""
        files = []
        seen = set()
        for output in agent_outputs:
            for f in output.get("files_changed", []):
                if f not in seen:
                    files.append(f)
                    seen.add(f)
        return files

    async def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit an event if event emitter is available."""
        if self._event_emitter:
            await self._event_emitter.emit(event_type, data)
