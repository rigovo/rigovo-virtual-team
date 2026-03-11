"""Graph builder — constructs the LangGraph orchestration graph.

**Primary path** — ``build_langgraph()`` returns a compiled LangGraph
``StateGraph`` with checkpointing, conditional routing, parallel fan-out,
and the full intelligent-agent pipeline.

**Fallback path** — ``run_sequential()`` provides a lightweight executor
for unit tests or environments where ``langgraph`` is not installed.

Features:
- SQLite checkpointing for crash recovery (item 3)
- Interactive approval with interrupt (item 4)
- Parallel fan-out for independent agents (item 8)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rigovo.application.context.memory_retriever import MemoryRetriever
from rigovo.application.graph.edges import (
    advance_to_next_agent,
    check_approval,
    check_gates_and_route,
    check_parallel_postprocess,
    check_reclassify_needed,
    check_replan_result,
    prepare_debate_round,
)
from rigovo.application.graph.nodes.approval import commit_approval_node, plan_approval_node
from rigovo.application.graph.nodes.assemble import assemble_node
from rigovo.application.graph.nodes.classify import classify_node
from rigovo.application.graph.nodes.enrich import enrich_node
from rigovo.application.graph.nodes.execute_agent import (
    execute_agent_node,
    execute_agents_parallel,
)
from rigovo.application.graph.nodes.finalize import finalize_node
from rigovo.application.graph.nodes.intent_gate import intent_gate_node
from rigovo.application.graph.nodes.quality_check import quality_check_node
from rigovo.application.graph.nodes.reclassify import reclassify_node
from rigovo.application.graph.nodes.replan import replan_node
from rigovo.application.graph.nodes.route_team import route_team_node
from rigovo.application.graph.nodes.scan_project import scan_project_node
from rigovo.application.graph.nodes.store_memory import store_memory_node
from rigovo.application.graph.nodes.verify_execution import verify_execution_node
from rigovo.application.graph.state import TaskState
from rigovo.application.master.classifier import TaskClassifier
from rigovo.application.master.enricher import ContextEnricher
from rigovo.application.master.evaluator import AgentEvaluator
from rigovo.application.master.router import TeamRouter
from rigovo.domain.entities.agent import Agent
from rigovo.domain.interfaces.embedding_provider import EmbeddingProvider
from rigovo.domain.interfaces.llm_provider import LLMProvider
from rigovo.domain.interfaces.quality_gate import QualityGate
from rigovo.domain.interfaces.repositories import MemoryRepository
from rigovo.domain.services.cost_calculator import CostCalculator
from rigovo.domain.services.history_state import CheckpointType

logger = logging.getLogger(__name__)

# Roles that can run in parallel (no inter-dependency)
PARALLELIZABLE_ROLES = {"reviewer", "qa", "security", "docs"}


class GraphBuilder:
    """
    Builds the orchestration graph.

    Dependencies are injected at construction time — the graph builder
    doesn't know about concrete LLM providers, databases, or gate
    implementations.
    """

    def __init__(
        self,
        llm_factory: Callable[[str], LLMProvider],
        master_llm: LLMProvider,
        cost_calculator: CostCalculator,
        quality_gates: list[QualityGate],
        agents: list[Agent] | None = None,
        team_agents_by_id: dict[str, list[Agent]] | None = None,
        available_teams: list[dict[str, Any]] | None = None,
        approval_handler: Callable[[TaskState], dict[str, Any]] | None = None,
        auto_approve: bool = True,
        enable_parallel: bool = True,  # ON by default — the magic
        stream_callback: Any | None = None,
        memory_repo: MemoryRepository | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        memory_retriever: MemoryRetriever | None = None,
        classifier: TaskClassifier | None = None,
        router: TeamRouter | None = None,
        enricher: ContextEnricher | None = None,
        evaluator: AgentEvaluator | None = None,
        cache_repo: Any | None = None,
    ) -> None:
        self._llm_factory = llm_factory
        self._master_llm = master_llm
        self._cost_calculator = cost_calculator
        self._quality_gates = quality_gates
        self._agents = agents or []
        self._team_agents_by_id = team_agents_by_id or {}
        self._available_teams = available_teams or []
        self._approval_handler = approval_handler
        self._auto_approve = auto_approve
        self._enable_parallel = enable_parallel
        self._stream_callback = stream_callback
        self._memory_repo = memory_repo
        self._embedding_provider = embedding_provider
        self._memory_retriever = memory_retriever
        self._classifier = classifier
        self._router = router
        self._enricher = enricher
        self._evaluator = evaluator
        self._cache_repo = cache_repo

    @staticmethod
    def _clear_matching_pending_approvals(
        pending_actions: list[dict[str, Any]] | None,
        approval_data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Remove the approval item that has just been resolved."""
        checkpoint = str(approval_data.get("checkpoint", "") or "").strip()
        role = str(approval_data.get("current_role", "") or "").strip()
        kind = str(approval_data.get("kind", "") or "").strip()
        tool_name = str(approval_data.get("tool_name", "") or "").strip()
        summary = str(approval_data.get("summary", "") or "").strip()
        remaining: list[dict[str, Any]] = []
        for item in list(pending_actions or []):
            if not isinstance(item, dict):
                remaining.append(item)
                continue
            same = (
                str(item.get("checkpoint", "") or "").strip() == checkpoint
                and str(item.get("role", "") or "").strip() == role
                and str(item.get("kind", "") or "").strip() == kind
                and str(item.get("tool_name", "") or "").strip() == tool_name
                and str(item.get("summary", "") or "").strip() == summary
            )
            if not same:
                remaining.append(item)
        return remaining

    async def _run_execute_with_budget_approval(self, state: TaskState) -> dict[str, Any]:
        """Run execute_agent_node with interactive approval continuation.

        Handles both token-budget extension checkpoints and risky runtime-action
        checkpoints so the graph can pause and resume on governance decisions.
        """
        current_state = state
        for _ in range(5):
            result = await execute_agent_node(
                current_state,
                self._llm_factory,
                self._cost_calculator,
                stream_callback=self._stream_callback,
                memory_repo=self._memory_repo,
                embedding_provider=self._embedding_provider,
                memory_retriever=self._memory_retriever,
            )
            status = str(result.get("status", "") or "")
            if status not in {"awaiting_budget_approval", "awaiting_runtime_approval"}:
                if current_state is not state:
                    merged_events = list(current_state.get("events", []))
                    for event in list(result.get("events", [])):
                        if event not in merged_events:
                            merged_events.append(event)
                    result = {
                        **result,
                        "events": merged_events,
                        "required_approval_actions": result.get(
                            "required_approval_actions",
                            current_state.get("required_approval_actions", []),
                        ),
                    }
                return result

            approval_state = {**current_state, **result}
            approval_data = result.get("approval_data", {}) or {}
            auto_approvable = bool(
                approval_data.get(
                    "auto_approvable",
                    status == "awaiting_budget_approval"
                    and not bool(approval_data.get("requires_human_approval", False)),
                )
            )
            decision = {"approval_status": "approved", "approval_feedback": "auto-approved"}
            if self._auto_approve and auto_approvable:
                decision = {"approval_status": "approved", "approval_feedback": "auto-approved"}
            elif self._approval_handler:
                decision = await asyncio.to_thread(self._approval_handler, approval_state)
            else:
                return {
                    **result,
                    "status": "failed",
                    "error": (
                        "Approval is required to continue this run, but no approval handler "
                        "is configured."
                    ),
                }

            approval_status = str(decision.get("approval_status", "approved"))
            approval_feedback = str(decision.get("approval_feedback", "") or "")
            events = list(result.get("events", []))
            checkpoint = str(approval_data.get("checkpoint", "checkpoint") or "checkpoint")
            if approval_status == "rejected":
                events.append(
                    {
                        "type": "approval_denied",
                        "checkpoint": checkpoint,
                        "feedback": approval_feedback,
                    }
                )
                return {
                    "status": "rejected",
                    "approval_status": "rejected",
                    "approval_feedback": approval_feedback,
                    "error": result.get("error", ""),
                    "events": events,
                    "required_approval_actions": self._clear_matching_pending_approvals(
                        result.get("required_approval_actions", []),
                        approval_data,
                    ),
                }

            current_state = {
                **current_state,
                **result,
                "events": events,
                "approval_status": "approved",
                "required_approval_actions": self._clear_matching_pending_approvals(
                    result.get("required_approval_actions", []),
                    approval_data,
                ),
            }

            if status == "awaiting_budget_approval":
                current_limit = int(current_state.get("budget_max_tokens_per_task", 0) or 0)
                requested_extension = int(approval_data.get("requested_extension_tokens", 0) or 0)
                extension = (
                    requested_extension
                    if requested_extension > 0
                    else max(50_000, current_limit // 4)
                )
                new_limit = current_limit + extension
                events.append(
                    {
                        "type": "approval_granted",
                        "checkpoint": checkpoint,
                        "previous_token_limit": current_limit,
                        "token_limit": new_limit,
                        "extension_tokens": extension,
                        "feedback": approval_feedback,
                    }
                )
                current_state["budget_max_tokens_per_task"] = new_limit
                current_state["events"] = events
            else:
                events.append(
                    {
                        "type": "approval_granted",
                        "checkpoint": checkpoint,
                        "feedback": approval_feedback,
                        "summary": str(approval_data.get("summary", "") or ""),
                        "kind": str(approval_data.get("kind", "") or ""),
                        "tool_name": str(approval_data.get("tool_name", "") or ""),
                    }
                )
                current_state["events"] = events

        return {
            "status": "failed",
            "error": "Approval was granted repeatedly but execution still could not proceed.",
            "events": current_state.get("events", []),
        }

    # ------------------------------------------------------------------
    # Checkpointer factory (item 3)
    # ------------------------------------------------------------------

    @staticmethod
    def create_sqlite_checkpointer(db_path: str | Path | None = None) -> Any:
        """Create a SQLite checkpointer context for crash recovery.

        Args:
            db_path: Path to SQLite database. Defaults to .rigovo/checkpoints.db.

        Returns:
            A context manager that yields a LangGraph-compatible checkpointer,
            or ``None`` if the SQLite checkpoint package is unavailable.
        """
        try:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        except ImportError:
            try:
                from langgraph.checkpoint.sqlite import SqliteSaver

                path = str(db_path) if db_path else ".rigovo/checkpoints.db"
                return SqliteSaver.from_conn_string(path)
            except ImportError:
                logger.debug("No SQLite checkpointer available")
                return None

        path = str(db_path) if db_path else ".rigovo/checkpoints.db"
        return AsyncSqliteSaver.from_conn_string(path)

    # ------------------------------------------------------------------
    # Primary path — LangGraph compiled graph
    # ------------------------------------------------------------------

    def build_langgraph(self, checkpointer: Any = None) -> Any:
        """
        Build a compiled LangGraph ``StateGraph``.

        Returns the compiled graph ready for ``await graph.ainvoke(state)``.
        Raises ``ImportError`` when ``langgraph`` is not installed.
        """
        from langgraph.graph import END, START, StateGraph

        graph = StateGraph(TaskState)

        # Capture dependencies in closures
        master_llm = self._master_llm
        llm_factory = self._llm_factory
        cost_calc = self._cost_calculator
        gates = self._quality_gates
        agents = self._agents
        team_agents_by_id = self._team_agents_by_id
        available_teams = self._available_teams
        auto_approve = self._auto_approve
        approval_handler = self._approval_handler
        stream_cb = self._stream_callback
        memory_repo = self._memory_repo
        embedding_provider = self._embedding_provider
        memory_retriever = self._memory_retriever
        classifier = self._classifier
        router = self._router
        enricher = self._enricher
        evaluator = self._evaluator

        # --- Node wrappers (bind injected deps) ---

        async def _scan_project(state: TaskState) -> dict:
            return await scan_project_node(state, cache_repo=self._cache_repo)

        async def _classify(state: TaskState) -> dict:
            return await classify_node(
                state,
                master_llm,
                classifier=classifier,
                cache_repo=self._cache_repo,
            )

        async def _intent_gate(state: TaskState) -> dict:
            return await intent_gate_node(state)

        async def _route_team(state: TaskState) -> dict:
            if not available_teams:
                return {
                    "status": "routed",
                    "events": [
                        *state.get("events", []),
                        {
                            "type": "team_routed",
                            "team_name": "engineering",
                            "reasoning": "No team config provided; using default engineering team.",
                        },
                    ],
                }
            return await route_team_node(
                state,
                master_llm,
                available_teams,
                router=router,
                cache_repo=self._cache_repo,
            )

        async def _assemble(state: TaskState) -> dict:
            selected_team_id = str(state.get("team_config", {}).get("team_id", "")).strip()
            selected_agents = team_agents_by_id.get(selected_team_id, agents)
            return await assemble_node(state, agents=selected_agents)

        async def _plan_approval(state: TaskState) -> dict:
            result = await plan_approval_node(state)
            if auto_approve:
                result["approval_status"] = "approved"
            elif approval_handler:
                # Call the approval handler (blocking I/O) in a thread
                handler_result = await asyncio.to_thread(approval_handler, {**state, **result})
                result["approval_status"] = handler_result.get("approval_status", "approved")
                result["approval_feedback"] = handler_result.get("approval_feedback", "")
            return result

        async def _execute_agent(state: TaskState) -> dict:
            return await self._run_execute_with_budget_approval(state)

        async def _verify_execution(state: TaskState) -> dict:
            return await verify_execution_node(state)

        async def _quality_check(state: TaskState) -> dict:
            return await quality_check_node(state, gates)

        async def _route_next(state: TaskState) -> dict:
            return advance_to_next_agent(state)

        async def _commit_approval(state: TaskState) -> dict:
            result = await commit_approval_node(state)
            if auto_approve:
                result["approval_status"] = "approved"
            elif approval_handler:
                handler_result = await asyncio.to_thread(approval_handler, {**state, **result})
                result["approval_status"] = handler_result.get("approval_status", "approved")
                result["approval_feedback"] = handler_result.get("approval_feedback", "")
            return result

        async def _enrich(state: TaskState) -> dict:
            return await enrich_node(state, enricher=enricher, evaluator=evaluator)

        async def _reclassify(state: TaskState) -> dict:
            return await reclassify_node(
                state,
                master_llm,
                classifier=classifier,
                embedding_provider=embedding_provider,
            )

        async def _replan(state: TaskState) -> dict:
            return await replan_node(state, master_llm)

        async def _store_memory(state: TaskState) -> dict:
            return await store_memory_node(
                state,
                master_llm,
                memory_repo=memory_repo,
                embedding_provider=embedding_provider,
            )

        async def _finalize(state: TaskState) -> dict:
            return await finalize_node(state)

        async def _parallel_fan_out(state: TaskState) -> dict:
            """Execute all currently ready parallelizable agent instances simultaneously."""
            team_config = state.get("team_config", {})
            pipeline_order = team_config.get("pipeline_order", [])
            ready_roles = state.get("ready_roles", [])
            if ready_roles:
                remaining_instances = list(ready_roles)
            else:
                current_index = state.get("current_agent_index", 0)
                remaining_instances = pipeline_order[current_index + 1 :]

            # Emit parallel_started event
            events = list(state.get("events", []))
            events.append(
                {
                    "type": "parallel_started",
                    "instances": remaining_instances,
                }
            )

            result = await execute_agents_parallel(
                {**state, "events": events},
                remaining_instances,
                llm_factory,
                cost_calc,
                stream_cb,
                memory_repo=memory_repo,
                embedding_provider=embedding_provider,
                memory_retriever=memory_retriever,
            )

            # Phase 4: Run verification + quality gates for each parallel agent
            merged_state = {**state, **result}
            all_verification_history = list(merged_state.get("verification_history", []))
            for instance_id in remaining_instances:
                per_instance_state = {
                    **merged_state,
                    "current_instance_id": instance_id,
                    "current_agent_role": instance_id,
                    "verification_history": all_verification_history,
                }
                verify_result = await verify_execution_node(per_instance_state)
                # Merge verification events and history
                result_events_so_far = list(result.get("events", []))
                result_events_so_far.extend(
                    e for e in verify_result.get("events", []) if e not in result_events_so_far
                )
                result["events"] = result_events_so_far
                all_verification_history = list(
                    verify_result.get("verification_history", all_verification_history)
                )
                result["execution_verification"] = verify_result.get("execution_verification", {})

                # Run quality gates per parallel instance (prevents bypass)
                gate_state = {**merged_state, **result, **verify_result}
                gate_state["current_instance_id"] = instance_id
                gate_state["current_agent_role"] = instance_id
                try:
                    gate_result = await quality_check_node(gate_state, gates)
                    gate_events = gate_result.get("events", [])
                    result_events_so_far.extend(
                        e for e in gate_events if e not in result_events_so_far
                    )
                    result["events"] = result_events_so_far
                except Exception as qe:
                    logger.warning(
                        "Quality gate for parallel instance %s failed: %s",
                        instance_id, qe,
                    )
            result["verification_history"] = all_verification_history

            # Add parallel_complete event and advance index to end of pipeline
            result_events = list(result.get("events", []))
            result_events.append({"type": "parallel_complete"})
            result["events"] = result_events
            completed_roles = set(state.get("completed_roles", []))
            completed_roles.update(remaining_instances)
            result["completed_roles"] = sorted(completed_roles)

            # Recompute DAG-ready roles after this parallel wave.
            next_update = advance_to_next_agent(
                {
                    **state,
                    **result,
                    "current_agent_role": "",
                    "current_instance_id": "",
                    "completed_roles": sorted(completed_roles),
                }
            )
            result.update(next_update)
            return result

        async def _prepare_debate(state: TaskState) -> dict:
            return prepare_debate_round(state)

        # --- Register nodes ---
        graph.add_node("scan_project", _scan_project)
        graph.add_node("classify", _classify)
        graph.add_node("intent_gate", _intent_gate)
        graph.add_node("route_team", _route_team)
        graph.add_node("assemble", _assemble)
        graph.add_node("plan_approval", _plan_approval)
        graph.add_node("execute_agent", _execute_agent)
        graph.add_node("verify_execution", _verify_execution)
        graph.add_node("quality_check", _quality_check)
        graph.add_node("route_next", _route_next)
        graph.add_node("parallel_fan_out", _parallel_fan_out)
        graph.add_node("debate_check", _prepare_debate)  # Debate prep node
        graph.add_node("commit_approval", _commit_approval)
        graph.add_node("reclassify", _reclassify)  # Late-binding reclassification
        graph.add_node("replan", _replan)
        graph.add_node("enrich", _enrich)
        graph.add_node("store_memory", _store_memory)
        graph.add_node("finalize", _finalize)

        # --- Edges ---
        # Pipeline (intent-first): classify → intent_gate → route_team → assemble
        # → plan_approval → scan_project → execute_agent.
        # This allows Master Brain intent understanding to appear immediately
        # and defers heavier repo perception until execution is confirmed.
        graph.add_edge(START, "classify")
        graph.add_edge("classify", "intent_gate")
        graph.add_edge("intent_gate", "route_team")
        graph.add_edge("route_team", "assemble")
        graph.add_edge("assemble", "plan_approval")

        graph.add_conditional_edges(
            "plan_approval",
            check_approval,
            {
                "approved": "scan_project",
                "rejected": "finalize",
            },
        )
        graph.add_edge("scan_project", "execute_agent")

        # Agent execution → verify execution → reclassify check → quality gates
        graph.add_edge("execute_agent", "verify_execution")

        # After verification: check if agent requested reclassification
        graph.add_conditional_edges(
            "verify_execution",
            check_reclassify_needed,
            {
                "continue": "quality_check",
                "reclassify": "reclassify",
            },
        )

        # After reclassification: re-assemble team with new classification
        graph.add_edge("reclassify", "assemble")

        graph.add_conditional_edges(
            "quality_check",
            check_gates_and_route,
            {
                "pass_next_agent": "route_next",
                "fail_fix_loop": "execute_agent",
                "trigger_replan": "replan",
                "fail_max_retries": "finalize",
            },
        )

        graph.add_conditional_edges(
            "replan",
            check_replan_result,
            {
                "replan_continue": "execute_agent",
                "replan_failed": "finalize",
            },
        )

        # After routing: sequential, parallel fan-out, debate loop, or done
        graph.add_conditional_edges(
            "route_next",
            check_parallel_postprocess,
            {
                "more_agents": "execute_agent",
                "parallel_fan_out": "parallel_fan_out",
                "debate_needed": "debate_check",
                "pipeline_done": "commit_approval",
                "pipeline_failed": "finalize",
            },
        )

        # After parallel fan-out: continue DAG scheduling, or trigger debate loop.
        graph.add_conditional_edges(
            "parallel_fan_out",
            check_parallel_postprocess,
            {
                "more_agents": "execute_agent",
                "parallel_fan_out": "parallel_fan_out",
                "pipeline_done": "commit_approval",
                "pipeline_failed": "finalize",
                "debate_needed": "debate_check",
            },
        )

        # Debate check preps coder re-execution with reviewer feedback
        graph.add_edge("debate_check", "execute_agent")

        graph.add_conditional_edges(
            "commit_approval",
            check_approval,
            {
                "approved": "enrich",
                "rejected": "finalize",
            },
        )

        graph.add_edge("enrich", "store_memory")
        graph.add_edge("store_memory", "finalize")
        graph.add_edge("finalize", END)

        if checkpointer:
            return graph.compile(checkpointer=checkpointer)
        return graph.compile()

    # ------------------------------------------------------------------
    # Fallback path — simple sequential executor (no LangGraph needed)
    # ------------------------------------------------------------------

    async def run_sequential(
        self,
        initial_state: TaskState,
        agents: list[Agent] | None = None,
        available_teams: list[dict[str, Any]] | None = None,
    ) -> TaskState:
        """
        Run the pipeline sequentially without LangGraph.

        No checkpointing, no interrupt(). Useful for unit tests and
        environments where ``langgraph`` is not installed.
        """
        state = dict(initial_state)

        # 0. Classify first — prioritize immediate intent understanding.
        if self._classifier is not None:
            update = await classify_node(
                state,
                self._master_llm,
                classifier=self._classifier,
                cache_repo=self._cache_repo,
            )
        else:
            update = await classify_node(state, self._master_llm, cache_repo=self._cache_repo)
        state.update(update)

        # 0b. Intent Gate — detect user intent and set constraints
        update = await intent_gate_node(state)
        state.update(update)

        # 2. Route team
        available_teams = available_teams if available_teams is not None else self._available_teams
        if available_teams:
            update = await route_team_node(
                state,
                self._master_llm,
                available_teams,
                router=self._router,
                cache_repo=self._cache_repo,
            )
            state.update(update)

        # 3. Assemble pipeline
        selected_team_id = str(state.get("team_config", {}).get("team_id", "")).strip()
        selected_agents = self._team_agents_by_id.get(selected_team_id, self._agents)
        update = await assemble_node(state, selected_agents)
        state.update(update)

        # 4. Plan approval
        update = await plan_approval_node(state)
        state.update(update)
        if self._auto_approve:
            state["approval_status"] = "approved"
        elif self._approval_handler:
            handler_result = await asyncio.to_thread(self._approval_handler, state)
            state["approval_status"] = handler_result.get("approval_status", "approved")
            state["approval_feedback"] = handler_result.get("approval_feedback", "")
        else:
            state["approval_status"] = "approved"

        if state["approval_status"] == "rejected":
            state["status"] = "rejected"
            update = await finalize_node(state)
            state.update(update)
            return state

        # 4. Scan project before agent execution (deferred heavy step).
        update = await scan_project_node(state, cache_repo=self._cache_repo)
        state.update(update)

        # 5. Execute agents
        pipeline_order = state.get("team_config", {}).get("pipeline_order", [])

        if self._enable_parallel:
            # Split into sequential and parallel groups
            agents_cfg = state.get("team_config", {}).get("agents", {})
            sequential, parallel = self._split_pipeline(pipeline_order, agents_cfg)
            await self._run_sequential_agents(state, sequential)
            if parallel:
                update = await execute_agents_parallel(
                    state,
                    parallel,
                    self._llm_factory,
                    self._cost_calculator,
                    self._stream_callback,
                    memory_repo=self._memory_repo,
                    embedding_provider=self._embedding_provider,
                    memory_retriever=self._memory_retriever,
                )
                state.update(update)
        else:
            await self._run_sequential_agents(state, pipeline_order)

        # 6. Commit approval
        update = await commit_approval_node(state)
        state.update(update)
        if self._auto_approve:
            state["approval_status"] = "approved"
        elif self._approval_handler:
            handler_result = await asyncio.to_thread(self._approval_handler, state)
            state["approval_status"] = handler_result.get("approval_status", "approved")
            state["approval_feedback"] = handler_result.get("approval_feedback", "")
        else:
            state["approval_status"] = "approved"

        if state["approval_status"] == "rejected":
            state["status"] = "rejected"
            update = await finalize_node(state)
            state.update(update)
            return state

        # 7. Enrich
        update = await enrich_node(state, enricher=self._enricher, evaluator=self._evaluator)
        state.update(update)

        # 8. Store memory
        update = await store_memory_node(
            state,
            self._master_llm,
            memory_repo=self._memory_repo,
            embedding_provider=self._embedding_provider,
        )
        state.update(update)

        # 9. Finalize
        update = await finalize_node(state)
        state.update(update)

        return state  # type: ignore[return-value]

    async def _run_sequential_agents(
        self,
        state: dict,
        pipeline_order: list[str],
    ) -> None:
        """Run agent instances one-by-one with quality gate retry loops.

        History state awareness: when resuming, skips agents that already
        completed in a previous execution. Uses completed_roles from state
        (restored from checkpoint timeline) to determine what to skip.
        """
        # GAP 3 fix: skip already-completed agents on resume
        skip_set: set[str] = set()
        if state.get("is_resuming"):
            completed = state.get("completed_roles", [])
            if isinstance(completed, list):
                skip_set = set(completed)
            if skip_set:
                logger.info(
                    "Sequential resume: skipping %d already-completed agents: %s",
                    len(skip_set),
                    ", ".join(sorted(skip_set)),
                )
        resume_ctx = state.get("resume_context", {}) or {}
        resume_instance_id = str(resume_ctx.get("resume_instance_id", "") or "").strip()
        resume_from_phase = str(resume_ctx.get("resume_from_phase", "") or "").strip()
        resume_phase_consumed = False

        for i, instance_id in enumerate(pipeline_order):
            # Skip agents that completed in previous execution
            if instance_id in skip_set:
                logger.info("Skipping already-completed agent: %s", instance_id)
                continue

            state["current_agent_index"] = i
            state["current_agent_role"] = instance_id  # Config key = instance_id
            state["current_instance_id"] = instance_id

            skip_execute = (
                state.get("is_resuming")
                and not resume_phase_consumed
                and resume_instance_id == instance_id
                and resume_from_phase in {"verify_execution", "quality_check"}
                and bool((state.get("agent_outputs") or {}).get(instance_id))
            )

            if skip_execute:
                logger.info(
                    "Strict resume: skipping execute_agent for %s and resuming from %s",
                    instance_id,
                    resume_from_phase,
                )
                # One-shot behavior: consume the strict resume hint after first use.
                resume_phase_consumed = True
            else:
                update = await self._run_execute_with_budget_approval(state)
                state.update(update)

            # Phase 4: execution verification before quality gates
            if not skip_execute or resume_from_phase == "verify_execution":
                update = await verify_execution_node(state)
                state.update(update)

            # Late-binding reclassification check
            if state.get("reclassify_requested") and int(state.get("reclassify_count", 0) or 0) < 1:
                logger.info("Sequential path: RECLASSIFY triggered — re-running classification")
                update = await reclassify_node(
                    state,
                    self._master_llm,
                    classifier=self._classifier,
                    embedding_provider=self._embedding_provider,
                )
                state.update(update)
                # Re-assemble with new classification
                selected_team_id = str(state.get("team_config", {}).get("team_id", "")).strip()
                selected_agents = self._team_agents_by_id.get(selected_team_id, self._agents)
                update = await assemble_node(state, selected_agents)
                state.update(update)
                # Restart pipeline with new team
                new_pipeline = state.get("team_config", {}).get("pipeline_order", [])
                if new_pipeline:
                    await self._run_sequential_agents(state, new_pipeline)
                return  # Don't continue the old pipeline

            update = await quality_check_node(state, self._quality_gates)
            state.update(update)

            gate_results = state.get("gate_results", {})
            if not gate_results.get("passed", True):
                retry_count = state.get("retry_count", 0)
                max_retries = state.get("max_retries", 5)

                while retry_count < max_retries and not gate_results.get("passed", True):
                    update = await self._run_execute_with_budget_approval(state)
                    state.update(update)
                    # Phase 4: verify again on retry
                    update = await verify_execution_node(state)
                    state.update(update)
                    update = await quality_check_node(state, self._quality_gates)
                    state.update(update)
                    gate_results = state.get("gate_results", {})
                    retry_count = state.get("retry_count", 0)

                if not gate_results.get("passed", True):
                    break

            # Record checkpoint after agent completes (history state)
            # This ensures sequential resume can skip this agent next time
            completed_roles = list(state.get("completed_roles", []))
            if instance_id not in completed_roles:
                completed_roles.append(instance_id)
                state["completed_roles"] = completed_roles
            _record_sequential_checkpoint(state, instance_id, gate_results)

    @staticmethod
    def _record_heartbeat(state: dict) -> None:
        """Update heartbeat timestamp in state for stale detection."""
        import time as _time

        state["last_heartbeat"] = _time.time()

    @staticmethod
    def _split_pipeline(
        pipeline_order: list[str],
        agents_cfg: dict[str, dict] | None = None,
    ) -> tuple[list[str], list[str]]:
        """Split pipeline into sequential (must run first) and parallel groups.

        Instance-ID aware: resolves base role from agent config to decide
        parallelizability. Falls back to treating the key itself as the role
        for backward compatibility.
        """
        agents_cfg = agents_cfg or {}
        sequential = []
        parallel = []
        for instance_id in pipeline_order:
            role = agents_cfg.get(instance_id, {}).get("role", instance_id)
            if role in PARALLELIZABLE_ROLES:
                parallel.append(instance_id)
            else:
                sequential.append(instance_id)
        return sequential, parallel


def _record_sequential_checkpoint(
    state: dict,
    instance_id: str,
    gate_results: dict,
) -> None:
    """Record a checkpoint in the sequential execution path.

    Appends to the checkpoint_timeline list in state so that on resume,
    the sequential runner knows which agents already completed.
    """
    import time as _time

    gate_passed = gate_results.get("passed", True) if isinstance(gate_results, dict) else True
    checkpoint_type = CheckpointType.GATE_PASSED if gate_passed else CheckpointType.GATE_FAILED

    # Build lightweight checkpoint record
    agent_outputs = state.get("agent_outputs", {})
    agent_summaries: dict[str, str] = {}
    if isinstance(agent_outputs, dict):
        for role, output in agent_outputs.items():
            if isinstance(output, dict):
                agent_summaries[role] = str(output.get("summary", ""))[:200]

    record = {
        "checkpoint_id": f"seq-{len(state.get('checkpoint_timeline', [])) + 1:03d}",
        "checkpoint_type": checkpoint_type,
        "checkpoint_name": f"{instance_id} completed",
        "timestamp": _time.time(),
        "agent_role": state.get("current_agent_role", ""),
        "instance_id": instance_id,
        "phase": "execute_agent",
        "completed_roles": list(state.get("completed_roles", [])),
        "agent_outputs_summary": agent_summaries,
        "gate_passed": gate_passed,
    }

    timeline = state.get("checkpoint_timeline", [])
    if not isinstance(timeline, list):
        timeline = []
    timeline.append(record)
    state["checkpoint_timeline"] = timeline

    # Update heartbeat
    state["last_heartbeat"] = _time.time()
