"""RunTaskCommand — orchestrates the full task lifecycle.

This is the application-layer entry point for `rigovo run`.
It wires together classification, routing, assembly, execution,
quality gates, approval, memory storage, and finalization.

Features:
- Streaming agent output to terminal (item 2)
- LangGraph checkpointing for crash recovery (item 3)
- Interactive approval handler (item 4)
- Parallel fan-out for independent agents (item 8)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid4, uuid5

from rigovo.application.graph.builder import GraphBuilder
from rigovo.application.graph.state import TaskState
from rigovo.application.master.classifier import TaskClassifier
from rigovo.application.master.enricher import ContextEnricher
from rigovo.application.master.evaluator import AgentEvaluator
from rigovo.application.master.router import TeamRouter
from rigovo.domain.entities.agent import Agent
from rigovo.domain.entities.audit_entry import AuditAction, AuditEntry
from rigovo.domain.entities.task import PipelineStep, Task, TaskComplexity, TaskType
from rigovo.domain.interfaces.domain_plugin import DomainPlugin
from rigovo.domain.interfaces.embedding_provider import EmbeddingProvider
from rigovo.domain.interfaces.event_emitter import EventEmitter
from rigovo.domain.interfaces.llm_provider import LLMProvider
from rigovo.domain.interfaces.quality_gate import QualityGate
from rigovo.domain.interfaces.repositories import MemoryRepository
from rigovo.domain.services.cost_calculator import CostCalculator
from rigovo.domain.services.history_state import (
    HistoryStateManager,
)
from rigovo.domain.services.team_assembler import TeamAssemblerService
from rigovo.infrastructure.llm.model_catalog import resolve_model_for_role
from rigovo.infrastructure.persistence.sqlite_audit_repo import SqliteAuditRepository
from rigovo.infrastructure.persistence.sqlite_cost_repo import SqliteCostRepository
from rigovo.infrastructure.persistence.sqlite_local import LocalDatabase
from rigovo.infrastructure.persistence.sqlite_task_repo import SqliteTaskRepository
from rigovo.infrastructure.quality.rigour_gate import RigourQualityGate

logger = logging.getLogger(__name__)


def _write_failure_log(
    project_root: str | Path,
    task_id: str,
    failure_reason: str,
    final_state: dict,
) -> None:
    """Write detailed failure diagnostics to .rigovo/logs/ for debugging.

    Creates a human-readable log file that the user can inspect to
    understand exactly why a pipeline failed. Includes gate results,
    agent outputs, events, and cost data.
    """
    try:
        log_dir = Path(project_root) / ".rigovo" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"pipeline_failure_{task_id[:8]}.log"

        lines = [
            "=== Pipeline Failure Report ===",
            f"Task ID: {task_id}",
            f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Failure reason: {failure_reason or 'unknown'}",
            "",
            "--- Pipeline State ---",
            f"Status: {final_state.get('status', 'unknown')}",
            f"Current agent: {final_state.get('current_agent_role', 'N/A')}",
            f"Completed roles: {', '.join(final_state.get('completed_roles', []))}",
            f"Retry count: {final_state.get('retry_count', 0)} / {final_state.get('max_retries', 5)}",
            "",
        ]

        # Gate results
        gate_results = final_state.get("gate_results", {})
        if gate_results:
            lines.append("--- Quality Gate Results ---")
            lines.append(f"Passed: {gate_results.get('passed', 'N/A')}")
            lines.append(f"Score: {gate_results.get('score', 'N/A')}")
            for v in gate_results.get("violations", []):
                if isinstance(v, dict):
                    lines.append(
                        f"  VIOLATION: [{v.get('gate', '?')}] {v.get('message', '?')} (severity: {v.get('severity', '?')})"
                    )
            lines.append("")

        # Gate history
        gate_history = final_state.get("gate_history", [])
        if gate_history:
            lines.append("--- Gate History ---")
            for entry in gate_history:
                if isinstance(entry, dict):
                    status = "PASS" if entry.get("passed") else "FAIL"
                    lines.append(
                        f"  [{status}] {entry.get('role', '?')}: {entry.get('message', '')}"
                    )
            lines.append("")

        # Agent outputs (summaries only)
        agent_outputs = final_state.get("agent_outputs", {})
        if agent_outputs:
            lines.append("--- Agent Outputs ---")
            for role, output in agent_outputs.items():
                if isinstance(output, dict):
                    summary = str(output.get("summary", ""))[:300]
                    files = output.get("files_changed", [])
                    lines.append(f"  [{role}] {summary}")
                    if files:
                        lines.append(f"    Files: {', '.join(files[:10])}")
            lines.append("")

        # Recent events
        events = final_state.get("events", [])
        if events:
            lines.append("--- Recent Events (last 20) ---")
            for ev in events[-20:]:
                if isinstance(ev, dict):
                    lines.append(
                        f"  [{ev.get('type', '?')}] {ev.get('message', ev.get('detail', ''))}"
                    )
            lines.append("")

        # Error field
        error = final_state.get("error", "")
        if error:
            lines.append("--- Error ---")
            lines.append(error)
            lines.append("")

        log_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Failure log written to %s", log_path)
    except Exception as e:
        logger.warning("Could not write failure log: %s", e)


class RunTaskCommand:
    """
    Executes a task through the full pipeline.

    Responsibilities:
    - Creates task entity and persists it
    - Builds initial graph state
    - Runs the graph (LangGraph with checkpointing, or sequential fallback)
    - Streams agent output to terminal in real-time
    - Handles interactive approval when --approve is set
    - Emits events for terminal UI
    - Persists results (task, costs, audit)
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
        max_retries: int = 5,
        team_configs: dict[str, Any] | None = None,
        consultation_policy: dict[str, Any] | None = None,
        subagent_policy: dict[str, Any] | None = None,
        deep_mode: str = "smart",
        deep_pro: bool = False,
        replan_policy: dict[str, Any] | None = None,
        memory_repo: MemoryRepository | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        plugin_registry: Any | None = None,
        integration_policy: dict[str, Any] | None = None,
        ci_mode: bool = False,
        offline: bool = False,
        enable_streaming: bool = True,
        enable_parallel: bool = False,
        auto_approve: bool = True,
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
        self._team_configs = team_configs or {}
        self._consultation_policy = consultation_policy or {}
        self._subagent_policy = subagent_policy or {}
        self._deep_mode = deep_mode
        self._deep_pro = deep_pro
        self._replan_policy = replan_policy or {}
        self._memory_repo = memory_repo
        self._embedding_provider = embedding_provider
        self._plugin_registry = plugin_registry
        self._integration_policy = integration_policy or {}
        self._ci_mode = ci_mode
        self._offline = offline
        self._enable_streaming = enable_streaming
        self._enable_parallel = enable_parallel
        self._auto_approve = auto_approve
        self._budget_max_cost: float = 25.00  # soft warning only, never hard-stops
        self._budget_max_tokens: int = 500_000  # token soft limit
        self._agent_model_overrides: dict[str, str] = {}  # Set via set_agent_model_overrides()

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
        resume_thread_id: str | None = None,
        task_id: str | UUID | None = None,
        project_id: str | UUID | None = None,
        tier: str = "auto",
        workspace_path: str = "",
        workspace_label: str = "",
    ) -> dict[str, Any]:
        """
        Execute a task end-to-end.

        Args:
            description: Task description.
            team_name: Optional target team name.
            resume_thread_id: Optional thread ID to resume from checkpoint (item 3).
            task_id: Optional pre-assigned task ID (from API create/resume).
                     If None, a new UUID is generated.
            project_id: Optional project UUID to associate this task with.
            tier: Approval tier — "auto" | "notify" | "approve".
            workspace_path: Optional absolute path of the target repo/folder for this task.
            workspace_label: Optional human-readable label for the workspace.

        Returns:
            Final state dict with status, costs, files changed, etc.
        """
        start_time = time.monotonic()
        task_id = UUID(str(task_id)) if task_id else uuid4()

        # --- 1. Create or resume task ---
        existing_task = await self._task_repo.get(task_id) if self._task_repo else None

        if existing_task:
            # Resuming — reuse DB record, just update status
            task = existing_task
            task.start()
            if self._task_repo:
                await self._task_repo.update_status(task)
            logger.info("Resuming existing task %s", task_id)
            _is_resuming = True
        else:
            _is_resuming = False
            # New task — create DB record
            task = Task(
                workspace_id=self._workspace_id,
                description=description,
                id=task_id,
                workspace_path=workspace_path.strip() if workspace_path else "",
                workspace_label=workspace_label.strip() if workspace_label else "",
            )
            # Store project context and approval tier for resume durability
            if project_id:
                try:
                    task.project_id = UUID(str(project_id))
                except (ValueError, AttributeError):
                    pass
            task.tier = tier if tier in ("auto", "notify", "approve") else "auto"
            task.start()
            if self._task_repo:
                await self._task_repo.save(task)
            logger.info("Created new task %s", task_id)

        self._emit_sync(
            "task_started",
            {
                "task_id": str(task_id),
                "description": description,
            },
        )

        # --- 2. Build initial state ---
        try:
            available_teams, team_agents_by_id = self._build_available_teams(team_name)
        except Exception as e:
            task.fail(str(e))
            if self._task_repo:
                await self._task_repo.save(task)
            self._emit_sync("task_failed", {"task_id": str(task_id), "error": str(e)})
            return {"status": "failed", "error": str(e), "task_id": str(task_id)}

        if not available_teams:
            err = "No enabled teams with available agents"
            task.fail(err)
            if self._task_repo:
                await self._task_repo.save(task)
            self._emit_sync("task_failed", {"task_id": str(task_id), "error": err})
            return {"status": "failed", "error": err, "task_id": str(task_id)}

        domain_id = available_teams[0].get("domain", "engineering")

        initial_state: TaskState = {
            "task_id": str(task_id),
            "workspace_id": str(self._workspace_id),
            "project_root": str(self._project_root),
            "worktree_mode": str(os.environ.get("RIGOVO_WORKTREE_MODE", "project")),
            "worktree_root": str(os.environ.get("RIGOVO_WORKTREE_ROOT", "")),
            "filesystem_sandbox_mode": str(
                os.environ.get("RIGOVO_FILESYSTEM_SANDBOX_MODE", "project_root")
            ),
            "description": description,
            "domain": domain_id,
            "requested_team_name": team_name or "",
            "task_type": None,
            "complexity": None,
            "team_config": {},
            "current_agent_index": 0,
            "current_agent_role": None,
            "agent_outputs": {},
            "agent_messages": [],
            "gate_results": {},
            "gate_history": [],
            "retry_count": 0,
            "max_retries": self._max_retries,
            "consultation_policy": self._consultation_policy,
            "subagent_policy": self._subagent_policy,
            "deep_mode": self._deep_mode,
            "deep_pro": self._deep_pro,
            "replan_policy": self._replan_policy,
            "replan_count": 0,
            "replan_history": [],
            "ci_mode": self._ci_mode,
            "debate_round": 0,
            "max_debate_rounds": 2,
            "reviewer_feedback": "",
            "debate_target_role": "",
            "fix_packet": None,
            "approval_status": None,
            "approval_feedback": None,
            "current_checkpoint": None,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "budget_max_cost_per_task": self._budget_max_cost,
            "budget_max_tokens_per_task": self._budget_max_tokens,
            "memories_to_store": [],
            "memory_context_by_role": {},
            "memory_retrieval_log": {},
            "memory_learning_metrics": {},
            "integration_policy": self._integration_policy,
            "integration_catalog": self._build_integration_catalog(),
            "status": "running",
            "events": [],
            "checkpoint_timeline": [],
            "last_heartbeat": time.time(),
            "is_resuming": False,
        }

        # GAP 5 fix: inject resume context when resuming
        if _is_resuming and task.checkpoint_timeline:
            history_mgr = HistoryStateManager()
            timeline = history_mgr.load_timeline(str(task_id), task.checkpoint_timeline)
            resume_ctx = history_mgr.build_resume_context(str(task_id))

            initial_state["is_resuming"] = True
            initial_state["checkpoint_timeline"] = task.checkpoint_timeline
            initial_state["completed_roles"] = timeline.completed_agents
            initial_state["resume_context"] = {
                "is_resuming": True,
                "resumed_from_checkpoint": resume_ctx.resumed_from_checkpoint,
                "completed_agents": resume_ctx.completed_agents,
                "last_successful_phase": resume_ctx.last_successful_phase,
                "files_already_changed": resume_ctx.files_already_changed,
                "previous_agent_summaries": resume_ctx.previous_agent_summaries,
                "accumulated_tokens": resume_ctx.accumulated_tokens,
                "accumulated_cost": resume_ctx.accumulated_cost,
            }
            logger.info(
                "Resume context injected: %d agents already completed, resuming from %s",
                len(resume_ctx.completed_agents),
                resume_ctx.resumed_from_checkpoint,
            )

        # --- 3. Resolve default agents (fallback safety)
        default_agents = team_agents_by_id.get(available_teams[0]["id"], [])

        # --- 4. Stream callback for real-time output (item 2) ---
        stream_callback = None
        if self._enable_streaming and self._event_emitter:

            def stream_callback(role: str, chunk: str) -> None:
                self._emit_sync(
                    "agent_streaming",
                    {
                        "role": role,
                        "chunk": chunk,
                    },
                )

        # --- 5. Prefetch Rigour CLI (runs in background while graph executes) ---
        rigour_prefetch = asyncio.create_task(self._prefetch_rigour())

        # --- 6. Build and run graph ---
        graph_builder = GraphBuilder(
            llm_factory=self._llm_factory,
            master_llm=self._master_llm,
            cost_calculator=self._cost_calculator,
            quality_gates=self._quality_gates,
            agents=default_agents,
            team_agents_by_id=team_agents_by_id,
            available_teams=available_teams,
            approval_handler=self._approval_handler,
            auto_approve=self._auto_approve,
            enable_parallel=self._enable_parallel,
            stream_callback=stream_callback,
            memory_repo=self._memory_repo,
            embedding_provider=self._embedding_provider,
            classifier=self._classifier,
            router=self._router,
            enricher=self._enricher,
            evaluator=self._evaluator,
        )

        try:
            final_state = await self._run_graph(
                graph_builder,
                initial_state,
                resume_thread_id=resume_thread_id,
            )
        except Exception as e:
            error_msg = str(e)

            # Provide human-readable messages for known failure types
            if "recursion limit" in error_msg.lower() or "recursion_limit" in error_msg.lower():
                error_msg = (
                    f"Pipeline exceeded step limit: {error_msg}. "
                    "This usually means agents are stuck in a retry loop. "
                    "Check .rigovo/logs/ for the failure report."
                )
            elif "psycopg" in error_msg.lower() or "connection refused" in error_msg.lower():
                error_msg = f"Database connection error: {error_msg}"

            logger.exception("Task execution failed: %s", error_msg)

            # Write failure log even for exceptions
            _write_failure_log(str(self._project_root), str(task_id), error_msg, initial_state)

            task.fail(error_msg)
            if self._task_repo:
                await self._task_repo.save(task)
            self._emit_sync(
                "task_failed",
                {
                    "task_id": str(task_id),
                    "error": error_msg,
                },
            )
            return {
                "status": "failed",
                "error": error_msg,
                "task_id": str(task_id),
            }

        # --- 6. Update task from final state ---
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        status = final_state.get("status", "completed")

        if status == "completed":
            task.complete()
        elif status == "rejected":
            task.reject(feedback=final_state.get("approval_feedback", ""))
        else:
            # Capture the pipeline error reason so UI can display it.
            # Check multiple failure sources in priority order.
            failure_reason = final_state.get("error", "")

            if not failure_reason:
                # Check events for pipeline_failed_dependency / dag_blocked
                for ev in reversed(final_state.get("events", [])):
                    if isinstance(ev, dict) and ev.get("type") in (
                        "dag_blocked",
                        "pipeline_failed_dependency",
                    ):
                        remaining = ev.get("remaining_instances", [])
                        failure_reason = (
                            f"Pipeline stalled: unresolved dependencies for {', '.join(remaining)}"
                        )
                        break

            if not failure_reason:
                # Check quality gate failures
                gate_results = final_state.get("gate_results", {})
                if isinstance(gate_results, dict) and not gate_results.get("passed", True):
                    violations = gate_results.get("violations", [])
                    if violations:
                        viol_summary = "; ".join(
                            v.get("message", v.get("gate", "unknown"))
                            for v in violations[:3]
                            if isinstance(v, dict)
                        )
                        failure_reason = f"Quality gate failed: {viol_summary}"
                    else:
                        failure_reason = (
                            f"Quality gate failed (score: {gate_results.get('score', 'N/A')})"
                        )

            if not failure_reason:
                # Check gate_history for the last failure
                gate_history = final_state.get("gate_history", [])
                for entry in reversed(gate_history):
                    if isinstance(entry, dict) and not entry.get("passed", True):
                        failure_reason = f"Quality gate failed for {entry.get('role', 'unknown')}: {entry.get('message', '')}"
                        break

            if not failure_reason:
                # Check if we hit a recursion limit (LangGraph)
                retry_count = final_state.get("retry_count", 0)
                max_retries = final_state.get("max_retries", 5)
                if retry_count >= max_retries:
                    role = final_state.get("current_agent_role", "unknown")
                    failure_reason = f"Max retries ({max_retries}) exhausted for agent '{role}'"

            # Write detailed failure log for debugging
            _write_failure_log(str(self._project_root), str(task_id), failure_reason, final_state)

            task.fail(failure_reason)

        # Persist classification from Master Agent (prevents "unclassified" in UI)
        classification = final_state.get("classification", {})
        if isinstance(classification, dict):
            raw_type = classification.get("task_type")
            if raw_type:
                try:
                    task.task_type = TaskType(raw_type)
                except ValueError:
                    task.task_type = TaskType.FEATURE
            raw_complexity = classification.get("complexity")
            if raw_complexity:
                try:
                    task.complexity = TaskComplexity(raw_complexity)
                except ValueError:
                    task.complexity = TaskComplexity.MEDIUM

        # Extract totals from finalize_node state or fall back to cost_accumulator
        task.total_tokens = final_state.get("total_tokens", 0)
        task.total_cost_usd = final_state.get("total_cost_usd", 0.0)

        # If finalize_node set them, they'll be non-zero; otherwise sum from cost_accumulator
        if task.total_tokens == 0:
            cost_acc = final_state.get("cost_accumulator", {})
            task.total_tokens = sum(v.get("tokens", 0) for v in cost_acc.values())
        if task.total_cost_usd == 0.0:
            cost_acc = final_state.get("cost_accumulator", {})
            task.total_cost_usd = round(sum(v.get("cost", 0.0) for v in cost_acc.values()), 6)
        task.duration_ms = elapsed_ms

        # --- Persist agent outputs as PipelineStep records ---
        agent_outputs_raw = final_state.get("agent_outputs", {})
        # Build a role→gate_entry lookup from gate_history for structured violations
        gate_history = final_state.get("gate_history", [])
        gate_by_role: dict[str, list[dict]] = {}
        if isinstance(gate_history, list):
            for gh in gate_history:
                if not isinstance(gh, dict):
                    continue
                gh_role = gh.get("role", "")
                if gh_role:
                    gate_by_role.setdefault(gh_role, []).append(gh)

        if isinstance(agent_outputs_raw, dict):
            pipeline_steps: list[PipelineStep] = []
            for role, output in agent_outputs_raw.items():
                # Build structured gate_violations from gate_history
                gate_violations: list[dict] = []
                for gh in gate_by_role.get(role, []):
                    passed = gh.get("passed", True)
                    violation_count = gh.get("violation_count", 0)
                    gates_run = gh.get("gates_run", 0)
                    reason = gh.get("reason", "")
                    gate_name = "rigour"
                    if reason == "persona_violation":
                        gate_name = "persona"
                    elif reason == "contract_failed":
                        gate_name = "contract"
                    elif reason == "no_files_produced":
                        gate_name = "no-files"

                    gate_violations.append(
                        {
                            "gate": gate_name,
                            "passed": passed,
                            "message": reason
                            if reason
                            else (
                                f"{gates_run} gate{'s' if gates_run != 1 else ''} passed"
                                if passed
                                else f"{violation_count} violation{'s' if violation_count != 1 else ''}"
                            ),
                            "severity": "info" if passed else "error",
                            "violation_count": violation_count,
                            "gates_run": gates_run,
                            "deep": gh.get("deep", False),
                            "pro": gh.get("pro", False),
                        }
                    )

                # Derive gate_passed from structured data
                gate_passed = output.get("gate_passed")
                if gate_passed is None and gate_violations:
                    gate_passed = all(gv.get("passed", True) for gv in gate_violations)

                # Humanize instance agent names: "backend-engineer-1" → "Backend Engineer 1"
                _agent_name = role.replace("-", " ").replace("_", " ").title()
                step = PipelineStep(
                    agent_id=uuid5(NAMESPACE_DNS, f"{task_id}:{role}"),
                    agent_role=role,
                    agent_name=_agent_name,
                    status="completed",
                    duration_ms=output.get("duration_ms", 0),
                    total_tokens=output.get("tokens", 0),
                    cost_usd=output.get("cost", 0.0),
                    summary=output.get("summary", ""),
                    files_changed=output.get("files_changed", []),
                    gate_passed=gate_passed,
                    gate_score=output.get("gate_score"),
                    gate_violations=gate_violations,
                    execution_log=output.get("execution_log", []),
                    execution_verified=output.get("execution_verified", False),
                )
                pipeline_steps.append(step)
            task.pipeline_steps = pipeline_steps

        # Persist collaboration evidence so UI can replay consult/debate/tool interactions.
        raw_events = final_state.get("events", [])
        raw_messages = final_state.get("agent_messages", [])
        collaboration_events = []
        if isinstance(raw_events, list):
            for ev in raw_events:
                if not isinstance(ev, dict):
                    continue
                ev_type = str(ev.get("type", "")).strip()
                if ev_type in {
                    "agent_consult_requested",
                    "agent_consult_completed",
                    "debate_round",
                    "integration_invoked",
                    "integration_blocked",
                    "replan_triggered",
                    "replan_failed",
                    "approval_requested",
                    "approval_granted",
                    "approval_denied",
                }:
                    event_copy = dict(ev)
                    event_copy.setdefault("created_at", time.time())
                    collaboration_events.append(event_copy)
        collaboration_messages = []
        if isinstance(raw_messages, list):
            for msg in raw_messages:
                if not isinstance(msg, dict):
                    continue
                if str(msg.get("type", "")).strip() in {"consult_request", "consult_response"}:
                    collaboration_messages.append(msg)
        task.approval_data = {
            **(task.approval_data or {}),
            "collaboration": {
                "events": collaboration_events[-200:],
                "messages": collaboration_messages[-200:],
                "debate_round": int(final_state.get("debate_round", 0) or 0),
            },
        }

        # Persist checkpoint timeline from graph state (history states)
        raw_timeline = final_state.get("checkpoint_timeline", [])
        if isinstance(raw_timeline, list) and raw_timeline:
            task.checkpoint_timeline = raw_timeline

        if self._task_repo:
            await self._task_repo.save(task)

        # --- 7. Audit log ---
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

        # --- 8. Emit finalization event ---
        agent_outputs = final_state.get("agent_outputs", {})
        self._emit_sync(
            "task_finalized",
            {
                "type": "task_finalized",
                "status": status,
                "total_cost": task.total_cost_usd,
                "total_tokens": task.total_tokens,
                "agents_run": [o.get("role", "?") for o in agent_outputs]
                if isinstance(agent_outputs, list)
                else list(agent_outputs.keys()),
                "retries": final_state.get("retry_count", 0),
                "memories_stored": len(final_state.get("memories_to_store", [])),
            },
        )

        return {
            "status": status,
            "task_id": str(task_id),
            "total_tokens": task.total_tokens,
            "total_cost_usd": task.total_cost_usd,
            "duration_ms": elapsed_ms,
            "agents_run": [o.get("role", "?") for o in agent_outputs]
            if isinstance(agent_outputs, list)
            else list(agent_outputs.keys()),
            "files_changed": self._extract_files_changed(agent_outputs),
        }

    async def _run_graph(
        self,
        graph_builder: GraphBuilder,
        initial_state: TaskState,
        resume_thread_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Execute the orchestration graph.

        Primary: LangGraph with SQLite checkpointing and streaming.
        Fallback: sequential executor when langgraph is unavailable.
        """
        try:
            # --- Item 3: Checkpointing for crash recovery ---
            checkpointer = None
            checkpoint_db = self._project_root / ".rigovo" / "checkpoints.db"
            try:
                checkpointer = GraphBuilder.create_sqlite_checkpointer(checkpoint_db)
            except Exception:
                logger.debug("Checkpointer unavailable, running without recovery")

            compiled = graph_builder.build_langgraph(checkpointer=checkpointer)
            logger.info("Running task via LangGraph orchestration engine")

            # Configure for resume or fresh run.
            # Default LangGraph recursion_limit is 25 which is too low for
            # multi-agent pipelines with verification, quality gates, debate
            # loops, and reclassification.  100 handles even complex tasks.
            config: dict[str, Any] = {"recursion_limit": 100}
            if resume_thread_id:
                config["configurable"] = {"thread_id": resume_thread_id}
                logger.info("Resuming from checkpoint: %s", resume_thread_id)
            elif checkpointer:
                config["configurable"] = {"thread_id": initial_state["task_id"]}

            result = await self._stream_graph(compiled, initial_state, config)
            return result
        except ImportError:
            logger.info("LangGraph not installed — falling back to sequential runner")
            return await graph_builder.run_sequential(initial_state=initial_state)

    async def _stream_graph(
        self,
        compiled: Any,
        initial_state: TaskState,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Stream graph execution, emitting events after each node."""
        seen_event_count = len(initial_state.get("events", []))
        final_state: dict[str, Any] = dict(initial_state)

        stream_kwargs: dict[str, Any] = {"stream_mode": "updates"}
        if config:
            stream_kwargs["config"] = config

        async for chunk in compiled.astream(initial_state, **stream_kwargs):
            for node_name, update in chunk.items():
                if not isinstance(update, dict):
                    continue
                final_state.update(update)

                # Broadcast any NEW events added by this node
                all_events = update.get("events", [])
                new_events = all_events[seen_event_count:]
                for event in new_events:
                    # Inject task_id so API event listeners can track per-task
                    if "task_id" not in event:
                        event["task_id"] = str(initial_state.get("task_id", ""))
                    await self._append_replan_audit_if_needed(event, initial_state)
                    self._emit_sync(event.get("type", node_name), event)
                seen_event_count = len(final_state.get("events", []))

        return final_state

    async def _append_replan_audit_if_needed(
        self,
        event: dict[str, Any],
        initial_state: TaskState,
    ) -> None:
        """Persist replan lifecycle events into durable audit trail."""
        audit_repo = getattr(self, "_audit_repo", None)
        if not audit_repo:
            return
        event_type = str(event.get("type", "") or "")
        if event_type not in {"replan_triggered", "replan_failed"}:
            return

        task_id_raw = str(event.get("task_id") or initial_state.get("task_id", "")).strip()
        try:
            task_uuid = UUID(task_id_raw)
        except ValueError:
            return

        action = (
            AuditAction.REPLAN_TRIGGERED
            if event_type == "replan_triggered"
            else AuditAction.REPLAN_FAILED
        )
        summary = (
            f"Replan #{event.get('replan_count', '?')} "
            f"{'triggered' if event_type == 'replan_triggered' else 'failed'}"
        )
        await audit_repo.append(
            AuditEntry(
                workspace_id=self._workspace_id,
                task_id=task_uuid,
                action=action,
                agent_role="system",
                summary=summary,
                metadata={
                    "trigger_reason": event.get("trigger_reason", ""),
                    "strategy": event.get("strategy", ""),
                    "target_role": event.get("target_role", ""),
                    "max_replans_per_task": event.get("max_replans_per_task"),
                },
            )
        )

    def _emit_sync(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit an event synchronously."""
        if self._event_emitter:
            self._event_emitter.emit(event_type, data)

    def _build_available_teams(
        self,
        requested_team_name: str | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, list[Agent]]]:
        """Build team routing metadata and per-team agent pools."""
        teams_config = self._team_configs or {}
        if not teams_config:
            # Backward-compatible fallback: single engineering team.
            teams_config = {
                "engineering": type(
                    "TeamCfg", (), {"enabled": True, "domain": "engineering", "agents": {}}
                )()
            }

        selected_key = (requested_team_name or "").strip().lower()
        available_teams: list[dict[str, Any]] = []
        team_agents_by_id: dict[str, list[Agent]] = {}

        for team_key, team_cfg in teams_config.items():
            if not getattr(team_cfg, "enabled", True):
                continue
            if selected_key and team_key.lower() != selected_key:
                continue

            domain_id = str(getattr(team_cfg, "domain", "engineering") or "engineering")
            domain_plugin = self._domain_plugins.get(domain_id)
            if not domain_plugin:
                continue

            role_defs = {r.role_id: r for r in domain_plugin.get_agent_roles()}
            agents = self._build_agents_for_team(team_key, role_defs, team_cfg)
            if not agents:
                continue

            team_id = team_key
            team_agents_by_id[team_id] = agents
            pipeline_order = [a.role for a in sorted(agents, key=lambda a: a.pipeline_order)]
            available_teams.append(
                {
                    "id": team_id,
                    "name": team_key,
                    "domain": domain_id,
                    "agents": {},
                    "pipeline_order": pipeline_order,
                }
            )

        if selected_key and not available_teams:
            raise ValueError(f"Requested team '{requested_team_name}' not found or disabled")

        return available_teams, team_agents_by_id

    def _build_integration_catalog(self) -> dict[str, Any]:
        """Load enabled plugins and expose connector/MCP/action capabilities."""
        if not self._plugin_registry:
            return {}
        try:
            manifests = self._plugin_registry.load(include_disabled=False)
        except Exception as exc:
            logger.warning("Plugin registry load failed: %s", exc)
            return {}

        catalog: dict[str, Any] = {}
        for manifest in manifests:
            connector_operations = {
                c.id: list(getattr(c, "outbound_actions", []) or [])
                for c in getattr(manifest, "connectors", [])
            }
            mcp_operations = {
                m.id: list(getattr(m, "operations", []) or [])
                for m in getattr(manifest, "mcp_servers", [])
            }
            action_requires_approval = {
                a.id: bool(getattr(a, "requires_approval", False))
                for a in getattr(manifest, "actions", [])
            }
            catalog[manifest.id] = {
                "name": manifest.name,
                "enabled": bool(getattr(manifest, "enabled", True)),
                "trust_level": str(getattr(manifest, "trust_level", "community")),
                "capabilities": list(getattr(manifest, "capabilities", [])),
                "connectors": [c.id for c in getattr(manifest, "connectors", [])],
                "connector_operations": connector_operations,
                "mcp_servers": [m.id for m in getattr(manifest, "mcp_servers", [])],
                "mcp_operations": mcp_operations,
                "actions": [a.id for a in getattr(manifest, "actions", [])],
                "action_requires_approval": action_requires_approval,
            }
        return catalog

    def _build_agents_for_team(
        self,
        team_key: str,
        agent_roles: dict[str, Any],
        team_cfg: Any,
    ) -> list[Agent]:
        """Build agent entities from domain role definitions.

        Model resolution priority (highest → lowest):
        1. rigovo.yml per-agent override (teams.engineering.agents.coder.model)
        2. LLM_AGENT_MODELS env var (JSON: {"coder":"claude-opus-4-6"})
        3. Role definition default (role_def.default_llm_model)
        4. ROLE_DEFAULT_MODELS in model_catalog.py
        5. LLM_MODEL fallback
        """
        agents = []
        stable_team_uuid = (
            uuid5(self._workspace_id or UUID(int=0), team_key)
            if self._workspace_id
            else uuid5(NAMESPACE_DNS, team_key)
        )
        # Env var overrides: LLM_AGENT_MODELS='{"coder":"...","qa":"..."}'
        env_agent_models = getattr(self, "_agent_model_overrides", {})
        for role_id, role_def in agent_roles.items():
            override = (
                team_cfg.agents.get(role_id)
                if getattr(team_cfg, "agents", None) and hasattr(team_cfg.agents, "get")
                else None
            )
            # Resolve model: YAML override > env var override > role default > catalog default
            yaml_model = override.model if override and getattr(override, "model", "") else ""
            env_model = env_agent_models.get(role_id, "")
            user_model = yaml_model or env_model or role_def.default_llm_model
            model = resolve_model_for_role(
                role_id=role_id,
                user_model=user_model,
            )
            tools = (
                list(override.tools)
                if override and getattr(override, "tools", None)
                else list(role_def.default_tools)
                if role_def.default_tools
                else []
            )
            custom_rules = (
                list(override.rules) if override and getattr(override, "rules", None) else []
            )
            input_contract = (
                dict(override.input_contract)
                if override and getattr(override, "input_contract", None)
                else {}
            )
            output_contract = (
                dict(override.output_contract)
                if override and getattr(override, "output_contract", None)
                else {}
            )
            depends_on = (
                list(override.depends_on)
                if override and getattr(override, "depends_on", None)
                else []
            )
            agent = Agent(
                workspace_id=self._workspace_id,
                team_id=stable_team_uuid,
                name=role_def.name,
                role=role_id,
                llm_model=model,
                system_prompt=role_def.default_system_prompt,
                tools=tools,
                custom_rules=custom_rules,
                depends_on=depends_on,
                input_contract=input_contract,
                output_contract=output_contract,
                pipeline_order=getattr(role_def, "pipeline_order", 0),
            )
            agents.append(agent)
        return agents

    @staticmethod
    async def _prefetch_rigour() -> None:
        """Pre-install Rigour CLI in background while agents execute.

        This runs alongside the planner/coder so the CLI is ready
        by the time quality gates need it. Eliminates 30-60s first-run lag.
        """
        try:
            await RigourQualityGate.ensure_binary()
        except Exception as e:
            logger.debug("Rigour prefetch failed (non-fatal): %s", e)

    @staticmethod
    def _extract_files_changed(agent_outputs: Any) -> list[str]:
        """Extract all files changed across all agent outputs."""
        files = []
        seen: set[str] = set()
        items = agent_outputs if isinstance(agent_outputs, list) else agent_outputs.values()
        for output in items:
            if isinstance(output, dict):
                for f in output.get("files_changed", []):
                    if f not in seen:
                        files.append(f)
                        seen.add(f)
        return files
